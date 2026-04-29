# ============================================================================
# PATCH — Integração de Preços + Planos Recorrentes Stripe
# ============================================================================
# Salve como ui_planos_stripe.py e adicione ao final do app.py:
#   exec(open('ui_planos_stripe.py').read())
#
# O QUE FAZ:
#   1. Preços da ProdutoPreco aplicados em todos os produtos (compliance, etc)
#   2. Planos criados automaticamente no Stripe quando salvos em /admin/monetizacao
#   3. Cliente assina plano → Stripe subscription → webhook renova créditos
#   4. Tela /planos — cliente vê e assina planos disponíveis
#   5. Tela /minha-assinatura — cliente vê plano, saldo, histórico, cancela
# ============================================================================

import math as _math2


# ── 1. Sobrescreve _price_cents para usar ProdutoPreco ───────────────────────

def _price_cents_from_precificacao(session, company_id: int, product_code: str,
                                   cost_cents: int, markup_pct: int) -> int:
    """
    Retorna o preço em cents de um produto de compliance.
    Prioridade: ProdutoPreco > cálculo original (cost + markup).
    """
    try:
        codigo_prec = f"compliance_{product_code}"
        pp = session.exec(
            select(ProdutoPreco)
            .where(ProdutoPreco.company_id == company_id,
                   ProdutoPreco.codigo == codigo_prec,
                   ProdutoPreco.ativo == True)
        ).first()
        if pp and pp.creditos > 0:
            return pp.creditos * 100  # creditos → cents
    except Exception:
        pass
    # Fallback: cálculo original
    markup = max(50, int(markup_pct or 50))
    return int(_math2.ceil(cost_cents * (1.0 + markup / 100.0)))


# ── Função auxiliar para sincronizar preços compliance → QueryProduct ─────────

def _sync_compliance_prices(session, company_id: int):
    """Atualiza price_cents dos QueryProducts baseado na ProdutoPreco."""
    try:
        qps = session.exec(
            select(QueryProduct).where(QueryProduct.company_id == company_id)
        ).all()
        for qp in qps:
            preco_pp = None
            try:
                pp = session.exec(
                    select(ProdutoPreco)
                    .where(ProdutoPreco.company_id == company_id,
                           ProdutoPreco.codigo == f"compliance_{qp.code}",
                           ProdutoPreco.ativo == True)
                ).first()
                if pp and pp.creditos > 0:
                    preco_pp = pp.creditos * 100
            except Exception:
                pass

            if preco_pp is not None:
                qp.price_cents = preco_pp
                session.add(qp)
        session.commit()
    except Exception as e:
        print(f"[planos_stripe] Erro sync compliance: {e}")


# ── 2. Planos Stripe: criação automática ─────────────────────────────────────

def _criar_plano_stripe(plano) -> tuple[str, str]:
    """
    Cria produto e preço recorrente no Stripe.
    Retorna (stripe_product_id, stripe_price_id).
    """
    try:
        import stripe as _stripe
        _stripe.api_key = os.environ.get("STRIPE_SECRET_KEY", "")

        # Cria produto
        product = _stripe.Product.create(
            name=plano.nome,
            description=f"{plano.creditos_mes} créditos/mês — Maffezzolli Capital",
        )

        # Cria preço recorrente
        price = _stripe.Price.create(
            product=product.id,
            currency="brl",
            unit_amount=plano.preco_cents,
            recurring={"interval": "month"},
        )

        return product.id, price.id
    except Exception as e:
        print(f"[planos_stripe] Erro ao criar plano no Stripe: {e}")
        return "", ""


# ── Patch na rota POST /admin/monetizacao/plano para criar no Stripe ──────────

_orig_monetizacao_plano = None
for _r in app.routes:
    if hasattr(_r, 'path') and _r.path == '/admin/monetizacao/plano' and hasattr(_r, 'methods') and 'POST' in (_r.methods or set()):
        _orig_monetizacao_plano = _r.endpoint
        break

if _orig_monetizacao_plano:
    # Remove a rota antiga e recria com criação no Stripe
    app.routes = [r for r in app.routes if not (
        hasattr(r, 'path') and r.path == '/admin/monetizacao/plano' and
        hasattr(r, 'methods') and 'POST' in (r.methods or set())
    )]

@app.post("/admin/monetizacao/plano")
@require_login
async def monetizacao_plano_post_v2(request: Request, session: Session = Depends(get_session)):
    ctx = get_tenant_context(request, session)
    if not ctx or ctx.membership.role not in ("admin", "equipe"):
        return RedirectResponse("/admin/monetizacao", status_code=303)

    form = await request.form()
    preco_reais = float(form.get("preco_reais", 0) or 0)

    plano = PlanoCredito(
        company_id=ctx.company.id,
        nome=form.get("nome", ""),
        creditos_mes=int(form.get("creditos_mes", 300) or 300),
        preco_cents=int(preco_reais * 100),
        ativo=True,
        created_at=str(utcnow()),
    )
    session.add(plano)
    session.commit()
    session.refresh(plano)

    # Cria no Stripe automaticamente
    if plano.preco_cents > 0:
        _, price_id = _criar_plano_stripe(plano)
        if price_id:
            plano.stripe_price_id = price_id
            session.add(plano)
            session.commit()
            set_flash(request, f"Plano criado e sincronizado com o Stripe (price_id: {price_id[:20]}...)")
        else:
            set_flash(request, "Plano criado. Não foi possível criar no Stripe — configure manualmente.")
    else:
        set_flash(request, "Plano criado.")

    return RedirectResponse("/admin/monetizacao", status_code=303)


# ── 3. Rota GET /planos — cliente vê e assina ────────────────────────────────

@app.get("/planos", response_class=HTMLResponse)
@require_login
async def planos_get(request: Request, session: Session = Depends(get_session)):
    ctx = get_tenant_context(request, session)
    if not ctx:
        request.session.clear()
        return RedirectResponse("/login", status_code=303)

    cc = get_client_or_none(session, ctx.company.id,
                            get_active_client_id(request, session, ctx))

    planos = session.exec(
        select(PlanoCredito)
        .where(PlanoCredito.company_id == ctx.company.id,
               PlanoCredito.ativo == True)
        .order_by(PlanoCredito.creditos_mes)
    ).all()

    # Plano atual do cliente
    plano_atual = None
    if cc:
        cp = session.exec(
            select(ClientePlano)
            .where(ClientePlano.company_id == ctx.company.id,
                   ClientePlano.client_id  == cc.id,
                   ClientePlano.ativo == True)
        ).first()
        if cp:
            plano_atual = session.get(PlanoCredito, cp.plano_id)

    # Saldo atual
    saldo = 0.0
    if cc:
        try:
            w = session.exec(
                select(CreditWallet)
                .where(CreditWallet.company_id == ctx.company.id,
                       CreditWallet.client_id  == cc.id)
            ).first()
            saldo = (w.balance_cents / 100) if w else 0.0
        except Exception:
            pass

    return render("planos.html", request=request, context={
        "current_user":    ctx.user,
        "current_company": ctx.company,
        "role":            ctx.membership.role,
        "current_client":  cc,
        "planos":          planos,
        "plano_atual":     plano_atual,
        "saldo":           saldo,
    })


# ── 4. Rota POST /planos/assinar/{plano_id} ───────────────────────────────────

@app.post("/planos/assinar/{plano_id}")
@require_login
async def planos_assinar(plano_id: int, request: Request, session: Session = Depends(get_session)):
    ctx = get_tenant_context(request, session)
    if not ctx:
        return RedirectResponse("/login", status_code=303)

    cc = get_client_or_none(session, ctx.company.id,
                            get_active_client_id(request, session, ctx))
    if not cc:
        set_flash(request, "Selecione um cliente primeiro.")
        return RedirectResponse("/planos", status_code=303)

    plano = session.get(PlanoCredito, plano_id)
    if not plano or plano.company_id != ctx.company.id or not plano.ativo:
        set_flash(request, "Plano não encontrado.")
        return RedirectResponse("/planos", status_code=303)

    if not plano.stripe_price_id:
        set_flash(request, "Este plano ainda não está disponível para compra. Contate o suporte.")
        return RedirectResponse("/planos", status_code=303)

    try:
        import stripe as _stripe
        _stripe.api_key = os.environ.get("STRIPE_SECRET_KEY", "")

        success_url = str(request.base_url).rstrip("/") + "/minha-assinatura?success=1"
        cancel_url  = str(request.base_url).rstrip("/") + "/planos?canceled=1"

        checkout = _stripe.checkout.Session.create(
            mode="subscription",
            success_url=success_url,
            cancel_url=cancel_url,
            line_items=[{"price": plano.stripe_price_id, "quantity": 1}],
            metadata={
                "company_id": str(ctx.company.id),
                "client_id":  str(cc.id),
                "plano_id":   str(plano.id),
                "tipo":       "plano_recorrente",
            },
        )
        return RedirectResponse(checkout.url, status_code=303)
    except Exception as e:
        set_flash(request, f"Erro ao iniciar assinatura: {e}")
        return RedirectResponse("/planos", status_code=303)


# ── 5. Rota GET /minha-assinatura ────────────────────────────────────────────

@app.get("/minha-assinatura", response_class=HTMLResponse)
@require_login
async def minha_assinatura(request: Request, session: Session = Depends(get_session)):
    ctx = get_tenant_context(request, session)
    if not ctx:
        request.session.clear()
        return RedirectResponse("/login", status_code=303)

    cc = get_client_or_none(session, ctx.company.id,
                            get_active_client_id(request, session, ctx))

    plano_atual = None
    cliente_plano = None
    saldo = 0.0
    historico = []

    if cc:
        cliente_plano = session.exec(
            select(ClientePlano)
            .where(ClientePlano.company_id == ctx.company.id,
                   ClientePlano.client_id  == cc.id,
                   ClientePlano.ativo == True)
        ).first()
        if cliente_plano:
            plano_atual = session.get(PlanoCredito, cliente_plano.plano_id)

        try:
            w = session.exec(
                select(CreditWallet)
                .where(CreditWallet.company_id == ctx.company.id,
                       CreditWallet.client_id  == cc.id)
            ).first()
            saldo = (w.balance_cents / 100) if w else 0.0
        except Exception:
            pass

        try:
            historico = session.exec(
                select(CreditLedger)
                .where(CreditLedger.company_id == ctx.company.id,
                       CreditLedger.client_id  == cc.id)
                .order_by(CreditLedger.id.desc())
                .limit(20)
            ).all()
        except Exception:
            pass

    success = request.query_params.get("success") == "1"

    return render("minha_assinatura.html", request=request, context={
        "current_user":    ctx.user,
        "current_company": ctx.company,
        "role":            ctx.membership.role,
        "current_client":  cc,
        "plano_atual":     plano_atual,
        "cliente_plano":   cliente_plano,
        "saldo":           saldo,
        "historico":       historico,
        "success":         success,
    })


# ── 6. Rota POST /minha-assinatura/cancelar ───────────────────────────────────

@app.post("/minha-assinatura/cancelar")
@require_login
async def cancelar_assinatura(request: Request, session: Session = Depends(get_session)):
    ctx = get_tenant_context(request, session)
    if not ctx:
        return RedirectResponse("/login", status_code=303)

    cc = get_client_or_none(session, ctx.company.id,
                            get_active_client_id(request, session, ctx))
    if not cc:
        return RedirectResponse("/minha-assinatura", status_code=303)

    cp = session.exec(
        select(ClientePlano)
        .where(ClientePlano.company_id == ctx.company.id,
               ClientePlano.client_id  == cc.id,
               ClientePlano.ativo == True)
    ).first()

    if cp:
        # Cancela no Stripe
        if cp.stripe_sub_id:
            try:
                import stripe as _stripe
                _stripe.api_key = os.environ.get("STRIPE_SECRET_KEY", "")
                _stripe.Subscription.cancel(cp.stripe_sub_id)
            except Exception as e:
                print(f"[planos_stripe] Erro cancelar Stripe: {e}")

        cp.ativo = False
        session.add(cp)
        session.commit()
        set_flash(request, "Assinatura cancelada com sucesso.")

    return RedirectResponse("/minha-assinatura", status_code=303)


# ── 7. Webhook Stripe: subscription ativo → registra ClientePlano ─────────────
# Estende o webhook existente para tratar planos recorrentes

_orig_webhook = None
for _r in app.routes:
    if hasattr(_r, 'path') and '/stripe/webhook' in (_r.path or '') and hasattr(_r, 'methods') and 'POST' in (_r.methods or set()):
        _orig_webhook = _r.endpoint
        break

if _orig_webhook:
    app.routes = [r for r in app.routes if not (
        hasattr(r, 'path') and '/stripe/webhook' in (_r.path or '') and
        hasattr(r, 'methods') and 'POST' in (r.methods or set())
    )]

@app.post("/stripe/webhook")
async def stripe_webhook_v2(request: Request, session: Session = Depends(get_session)):
    import stripe as _stripe
    if _stripe is None or not os.getenv("STRIPE_WEBHOOK_SECRET"):
        return Response(status_code=400)

    payload = await request.body()
    sig = request.headers.get("stripe-signature", "")
    _stripe.api_key = os.getenv("STRIPE_SECRET_KEY", "")

    try:
        event = _stripe.Webhook.construct_event(payload, sig, os.environ["STRIPE_WEBHOOK_SECRET"])
    except Exception:
        return Response(status_code=400)

    etype = event.get("type", "")
    obj   = (event.get("data") or {}).get("object") or {}
    meta  = obj.get("metadata") or {}

    # ── Checkout avulso (pagamento único) ────────────────────────────────────
    if etype == "checkout.session.completed":
        tipo = meta.get("tipo", "")

        if tipo == "plano_recorrente":
            # Registra assinatura
            company_id  = int(meta.get("company_id") or 0)
            client_id   = int(meta.get("client_id") or 0)
            plano_id    = int(meta.get("plano_id") or 0)
            sub_id      = str(obj.get("subscription") or "")

            if company_id and client_id and plano_id:
                # Desativa plano anterior se existir
                cp_ant = session.exec(
                    select(ClientePlano)
                    .where(ClientePlano.company_id == company_id,
                           ClientePlano.client_id  == client_id,
                           ClientePlano.ativo == True)
                ).first()
                if cp_ant:
                    cp_ant.ativo = False
                    session.add(cp_ant)

                # Cria novo
                cp = ClientePlano(
                    company_id=company_id,
                    client_id=client_id,
                    plano_id=plano_id,
                    stripe_sub_id=sub_id,
                    proximo_ciclo=(utcnow() + __import__('datetime').timedelta(days=30)).strftime("%Y-%m-%d"),
                    ativo=True,
                    created_at=str(utcnow()),
                )
                session.add(cp)

                # Renova créditos imediatamente
                try:
                    _renovar_plano_cliente(session, company_id, client_id)
                except Exception:
                    pass

                session.commit()

        else:
            # Pagamento avulso original
            credits     = int(meta.get("credits") or 0)
            company_id  = int(meta.get("company_id") or 0)
            client_id   = int(meta.get("client_id") or 0)
            session_id  = str(obj.get("id") or "")

            if company_id and client_id and credits and session_id:
                already = session.exec(
                    select(CreditLedger)
                    .where(CreditLedger.ref_type == "stripe_session",
                           CreditLedger.ref_id   == session_id,
                           CreditLedger.kind      == "TOPUP_CONFIRMED")
                ).first()
                if not already:
                    _wallet_credit(session, company_id=company_id, client_id=client_id,
                                   amount_cents=credits * 100, stripe_session_id=session_id)

    # ── Fatura paga (renovação mensal) ───────────────────────────────────────
    elif etype == "invoice.paid":
        sub_id = str(obj.get("subscription") or "")
        if sub_id:
            cp = session.exec(
                select(ClientePlano)
                .where(ClientePlano.stripe_sub_id == sub_id,
                       ClientePlano.ativo == True)
            ).first()
            if cp:
                try:
                    _renovar_plano_cliente(session, cp.company_id, cp.client_id)
                except Exception as e:
                    print(f"[webhook] Erro renovar plano: {e}")

    # ── Assinatura cancelada ─────────────────────────────────────────────────
    elif etype in ("customer.subscription.deleted", "customer.subscription.canceled"):
        sub_id = str(obj.get("id") or "")
        if sub_id:
            cp = session.exec(
                select(ClientePlano)
                .where(ClientePlano.stripe_sub_id == sub_id)
            ).first()
            if cp:
                cp.ativo = False
                session.add(cp)
                session.commit()

    return Response(status_code=200)


# ── Templates ─────────────────────────────────────────────────────────────────

TEMPLATES["planos.html"] = r"""
{% extends "base.html" %}
{% block content %}
<style>
  .pl-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:1.25rem;margin-bottom:2rem;}
  .pl-card{border:1px solid var(--mc-border);border-radius:16px;padding:1.5rem;background:#fff;display:flex;flex-direction:column;gap:.75rem;transition:box-shadow .15s;}
  .pl-card:hover{box-shadow:0 4px 20px rgba(0,0,0,.08);}
  .pl-card.atual{border:2px solid var(--mc-primary);background:#fff7f0;}
  .pl-nome{font-size:1.1rem;font-weight:700;}
  .pl-creditos{font-size:2rem;font-weight:800;color:var(--mc-primary);letter-spacing:-.03em;}
  .pl-preco{font-size:1rem;font-weight:600;color:#374151;}
  .pl-desc{font-size:.8rem;color:var(--mc-muted);line-height:1.5;}
  .pl-saldo{background:#f0fdf4;border:1px solid #bbf7d0;border-radius:12px;padding:1rem 1.25rem;margin-bottom:1.5rem;}
</style>

{% if success %}
<div class="alert alert-success mb-3">
  <strong>✅ Assinatura ativada com sucesso!</strong> Seus créditos foram adicionados à carteira.
</div>
{% endif %}

<h4 class="mb-1">Planos de Crédito</h4>
<div class="muted small mb-3">Escolha o plano ideal para sua empresa. A cobrança é mensal e os créditos são renovados automaticamente.</div>

{% if current_client %}
<div class="pl-saldo">
  <div class="d-flex justify-content-between align-items-center flex-wrap gap-2">
    <div>
      <div class="fw-bold">Saldo atual</div>
      <div style="font-size:1.5rem;font-weight:800;color:#16a34a;">{{ "%.0f"|format(saldo) }} créditos</div>
    </div>
    {% if plano_atual %}
    <div class="text-end">
      <div class="muted small">Plano ativo</div>
      <div class="fw-bold">{{ plano_atual.nome }}</div>
      <div class="muted small">{{ plano_atual.creditos_mes }} cr/mês</div>
    </div>
    {% endif %}
  </div>
</div>
{% endif %}

{% if planos %}
<div class="pl-grid">
  {% for p in planos %}
  <div class="pl-card {{ 'atual' if plano_atual and plano_atual.id == p.id else '' }}">
    {% if plano_atual and plano_atual.id == p.id %}
    <div class="badge text-bg-warning" style="width:fit-content;">Plano atual</div>
    {% endif %}
    <div class="pl-nome">{{ p.nome }}</div>
    <div class="pl-creditos">{{ p.creditos_mes }} <span style="font-size:1rem;font-weight:400;color:var(--mc-muted);">créditos/mês</span></div>
    <div class="pl-preco">R$ {{ "%.2f"|format(p.preco_cents/100) }}<span style="font-size:.8rem;font-weight:400;color:var(--mc-muted);">/mês</span></div>
    <div class="pl-desc">
      Renova mensalmente completando seu saldo até {{ p.creditos_mes }} créditos.
      Se você tiver saldo sobrando, só recebe a diferença.
    </div>
    {% if current_client %}
      {% if plano_atual and plano_atual.id == p.id %}
        <a href="/minha-assinatura" class="btn btn-outline-secondary btn-sm mt-auto">Gerenciar assinatura</a>
      {% elif p.stripe_price_id %}
        <form method="post" action="/planos/assinar/{{ p.id }}">
          <button type="submit" class="btn btn-primary w-100 mt-auto">
            {{ 'Fazer upgrade' if plano_atual else 'Assinar plano' }}
          </button>
        </form>
      {% else %}
        <button class="btn btn-outline-secondary w-100 mt-auto" disabled>Em breve</button>
      {% endif %}
    {% else %}
      <div class="alert alert-warning" style="font-size:.8rem;">Selecione um cliente para assinar.</div>
    {% endif %}
  </div>
  {% endfor %}
</div>
{% else %}
<div class="card p-4 text-center">
  <div style="font-size:2rem;margin-bottom:.5rem;">📦</div>
  <h5>Nenhum plano disponível</h5>
  <div class="muted">Aguarde — novos planos serão disponibilizados em breve.</div>
</div>
{% endif %}
{% endblock %}
"""

TEMPLATES["minha_assinatura.html"] = r"""
{% extends "base.html" %}
{% block content %}
<style>
  .ma-card{border:1px solid var(--mc-border);border-radius:14px;padding:1.25rem;background:#fff;margin-bottom:1.25rem;}
  .ma-saldo{font-size:2.5rem;font-weight:800;color:var(--mc-primary);letter-spacing:-.03em;}
  .hist-row{display:flex;justify-content:space-between;align-items:center;padding:.45rem 0;border-bottom:1px solid var(--mc-border);font-size:.84rem;}
  .hist-row:last-child{border-bottom:0;}
  .cr-pos{color:#16a34a;font-weight:600;}
  .cr-neg{color:#dc2626;}
</style>

{% if success %}
<div class="alert alert-success mb-3"><strong>✅ Assinatura ativada!</strong> Bem-vindo ao plano.</div>
{% endif %}

<h4 class="mb-3">Minha Assinatura</h4>

<div class="row g-3">
  <div class="col-md-4">
    <div class="ma-card text-center">
      <div class="muted small mb-1">Saldo disponível</div>
      <div class="ma-saldo">{{ "%.0f"|format(saldo) }}</div>
      <div class="muted small">créditos</div>
    </div>
  </div>
  <div class="col-md-8">
    <div class="ma-card">
      {% if plano_atual %}
      <div class="d-flex justify-content-between align-items-start flex-wrap gap-2">
        <div>
          <div class="muted small">Plano ativo</div>
          <div class="fw-bold fs-5">{{ plano_atual.nome }}</div>
          <div class="muted small">{{ plano_atual.creditos_mes }} créditos/mês · R$ {{ "%.2f"|format(plano_atual.preco_cents/100) }}/mês</div>
          {% if cliente_plano and cliente_plano.proximo_ciclo %}
          <div class="muted small mt-1">Próxima renovação: {{ cliente_plano.proximo_ciclo }}</div>
          {% endif %}
        </div>
        <div class="d-flex gap-2 flex-wrap">
          <a href="/planos" class="btn btn-outline-primary btn-sm">Fazer upgrade</a>
          <form method="post" action="/minha-assinatura/cancelar"
                onsubmit="return confirm('Cancelar assinatura? Seus créditos restantes serão mantidos.')">
            <button type="submit" class="btn btn-outline-danger btn-sm">Cancelar</button>
          </form>
        </div>
      </div>
      {% else %}
      <div class="text-center py-2">
        <div class="muted mb-2">Você não possui um plano ativo.</div>
        <a href="/planos" class="btn btn-primary">Ver planos disponíveis</a>
      </div>
      {% endif %}
    </div>
  </div>
</div>

<div class="ma-card">
  <h6 class="mb-3">Histórico de uso</h6>
  {% if historico %}
    {% for h in historico %}
    <div class="hist-row">
      <div>
        <div>{{ h.note or h.kind }}</div>
        <div class="muted" style="font-size:.72rem;">{{ h.created_at[:16] if h.created_at else '' }}</div>
      </div>
      <div class="{{ 'cr-pos' if h.amount_cents > 0 else 'cr-neg' }}">
        {{ '+' if h.amount_cents > 0 else '' }}{{ "%.0f"|format(h.amount_cents/100) }} cr
      </div>
    </div>
    {% endfor %}
  {% else %}
    <div class="muted small">Nenhum histórico ainda.</div>
  {% endif %}
</div>
{% endblock %}
"""

# ── Adiciona /planos e /minha-assinatura ao FEATURE_KEYS ─────────────────────
if "planos" not in FEATURE_KEYS:
    FEATURE_KEYS["planos"] = {"title": "Planos", "desc": "Ver e assinar planos de crédito.", "href": "/planos"}
    FEATURE_KEYS["minha_assinatura"] = {"title": "Minha Assinatura", "desc": "Gerenciar assinatura e histórico.", "href": "/minha-assinatura"}
    FEATURE_VISIBLE_ROLES["planos"] = {"admin", "equipe", "cliente"}
    FEATURE_VISIBLE_ROLES["minha_assinatura"] = {"admin", "equipe", "cliente"}
    for _g in FEATURE_GROUPS:
        if _g.get("key") == "solucoes":
            for _fk in ["planos", "minha_assinatura"]:
                if _fk not in _g["features"]:
                    _g["features"].append(_fk)
            break

# ── Sincroniza preços compliance ao iniciar ───────────────────────────────────
try:
    from sqlmodel import Session as _SessSync
    with _SessSync(engine) as _sess_sync:
        from sqlmodel import select as _sel_sync
        _companies = _sess_sync.exec(_sel_sync(Company)).all()
        for _co in _companies:
            _sync_compliance_prices(_sess_sync, _co.id)
except Exception as _e_sync:
    print(f"[planos_stripe] Sync compliance ao iniciar: {_e_sync}")

if hasattr(templates_env.loader, "mapping"):
    templates_env.loader.mapping = TEMPLATES

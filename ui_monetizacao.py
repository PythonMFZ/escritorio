# ============================================================================
# PATCH — Sistema de Monetização Completo
# ============================================================================
# Salve como ui_monetizacao.py e adicione ao final do app.py:
#   exec(open('ui_monetizacao.py').read())
#
# CORRIGE: patches anteriores usavam balance_credits (inexistente)
#          sistema real usa balance_cents (1 crédito = 100 cents)
#
# INCLUI:
#   1. FreemiumCampanha — X créditos automáticos no cadastro (período configurável)
#   2. PlanoCredito — cardápio de planos recorrentes (renova para o teto, não acumula)
#   3. Avaliação — 1 grátis/mês, demais bloqueiam se sem crédito
#   4. Correção dos patches de Augur e Viabilidade (usa cents corretamente)
#   5. Tela /admin/monetizacao — gerencia campanhas e planos
# ============================================================================

from typing import Optional as _OptM
from datetime import datetime as _dtM, timedelta as _tdM
from sqlmodel import Field as _FM, SQLModel as _SMM


# ── Modelos ───────────────────────────────────────────────────────────────────

class FreemiumCampanha(_SMM, table=True):
    """Campanha de créditos gratuitos para novos cadastros."""
    __tablename__  = "freemiumcampanha"
    __table_args__ = {"extend_existing": True}
    id:           _OptM[int] = _FM(default=None, primary_key=True)
    company_id:   int        = _FM(index=True)
    nome:         str        = _FM(default="")
    creditos:     int        = _FM(default=100)        # créditos (não cents)
    data_inicio:  str        = _FM(default="")         # YYYY-MM-DD
    data_fim:     str        = _FM(default="")         # YYYY-MM-DD
    ativa:        bool       = _FM(default=True)
    created_at:   str        = _FM(default="")


class PlanoCredito(_SMM, table=True):
    """Plano de créditos recorrente — renova para o teto a cada 30 dias."""
    __tablename__  = "planocredito"
    __table_args__ = {"extend_existing": True}
    id:            _OptM[int] = _FM(default=None, primary_key=True)
    company_id:    int        = _FM(index=True)
    nome:          str        = _FM(default="")        # Ex: "Plano 300"
    creditos_mes:  int        = _FM(default=300)       # teto mensal em créditos
    preco_cents:   int        = _FM(default=29900)     # preço em centavos (R$ 299,00)
    stripe_price_id: str      = _FM(default="")        # Stripe Price ID para recorrência
    ativo:         bool       = _FM(default=True)
    created_at:    str        = _FM(default="")


class ClientePlano(_SMM, table=True):
    """Assinatura ativa de um cliente em um plano."""
    __tablename__  = "clienteplano"
    __table_args__ = {"extend_existing": True}
    id:             _OptM[int] = _FM(default=None, primary_key=True)
    company_id:     int        = _FM(index=True)
    client_id:      int        = _FM(index=True)
    plano_id:       int        = _FM(index=True)
    stripe_sub_id:  str        = _FM(default="")       # Stripe Subscription ID
    proximo_ciclo:  str        = _FM(default="")       # YYYY-MM-DD
    ativo:          bool       = _FM(default=True)
    created_at:     str        = _FM(default="")


try:
    _SMM.metadata.create_all(engine, tables=[
        FreemiumCampanha.__table__,
        PlanoCredito.__table__,
        ClientePlano.__table__,
    ])
except Exception:
    pass


# ── Helpers de crédito (corrigidos para usar cents) ───────────────────────────

def _creditos_to_cents(creditos: int) -> int:
    """Converte créditos para centavos (1 crédito = 100 cents)."""
    return int(creditos) * 100


def _cents_to_creditos(cents: int) -> float:
    """Converte centavos para créditos."""
    return cents / 100


def _wallet_balance_creditos(session, company_id: int, client_id: int) -> float:
    """Retorna saldo da carteira em créditos."""
    w = _get_or_create_wallet(session, company_id=company_id, client_id=client_id)
    return _cents_to_creditos(w.balance_cents)


def _creditar_creditos(session, company_id: int, client_id: int,
                       creditos: int, motivo: str = "", kind: str = "ADJUSTMENT") -> bool:
    """Credita X créditos na carteira do cliente."""
    try:
        cents = _creditos_to_cents(creditos)
        w = _get_or_create_wallet(session, company_id=company_id, client_id=client_id)
        w.balance_cents += cents
        w.updated_at = utcnow()
        session.add(w)
        ledger = CreditLedger(
            company_id=company_id,
            client_id=client_id,
            kind=kind,
            amount_cents=cents,
            ref_type="manual",
            ref_id="",
            note=motivo or f"+{creditos} créditos",
        )
        session.add(ledger)
        session.commit()
        return True
    except Exception as e:
        print(f"[monetizacao] Erro ao creditar: {e}")
        return False


def _debitar_creditos(session, company_id: int, client_id: int,
                      creditos: int, motivo: str = "") -> bool:
    """Debita X créditos da carteira. Retorna False se saldo insuficiente."""
    try:
        cents = _creditos_to_cents(creditos)
        w = _get_or_create_wallet(session, company_id=company_id, client_id=client_id)
        if w.balance_cents < cents:
            return False
        w.balance_cents -= cents
        w.updated_at = utcnow()
        session.add(w)
        ledger = CreditLedger(
            company_id=company_id,
            client_id=client_id,
            kind="CONSULT_CAPTURED",
            amount_cents=-cents,
            ref_type="manual",
            ref_id="",
            note=motivo or f"-{creditos} créditos",
        )
        session.add(ledger)
        session.commit()
        return True
    except Exception as e:
        print(f"[monetizacao] Erro ao debitar: {e}")
        return False


def _get_or_create_wallet(session, company_id: int, client_id: int) -> CreditWallet:
    """Busca ou cria carteira do cliente."""
    w = session.exec(
        select(CreditWallet)
        .where(CreditWallet.company_id == company_id,
               CreditWallet.client_id  == client_id)
    ).first()
    if not w:
        w = CreditWallet(company_id=company_id, client_id=client_id,
                         balance_cents=0, updated_at=utcnow())
        session.add(w)
        session.commit()
        session.refresh(w)
    return w


# ── Freemium: créditos automáticos no cadastro ───────────────────────────────

def _aplicar_freemium(session, company_id: int, client_id: int) -> int:
    """
    Verifica campanhas ativas e aplica créditos ao novo cliente.
    Retorna total de créditos aplicados.
    """
    hoje = _dtM.utcnow().strftime("%Y-%m-%d")
    campanhas = session.exec(
        select(FreemiumCampanha)
        .where(
            FreemiumCampanha.company_id == company_id,
            FreemiumCampanha.ativa == True,
            FreemiumCampanha.data_inicio <= hoje,
            FreemiumCampanha.data_fim >= hoje,
        )
    ).all()

    total = 0
    for c in campanhas:
        ok = _creditar_creditos(
            session, company_id=company_id, client_id=client_id,
            creditos=c.creditos,
            motivo=f"Bônus freemium: {c.nome}",
            kind="ADJUSTMENT",
        )
        if ok:
            total += c.creditos

    return total


# ── Avaliação: 1 grátis por mês, demais bloqueiam ────────────────────────────

def _pode_fazer_avaliacao(session, company_id: int, client_id: int) -> tuple[bool, str]:
    """
    Verifica se o cliente pode fazer uma nova avaliação.
    Retorna (pode, motivo).
    """
    # Verifica quantas avaliações no mês corrente
    inicio_mes = _dtM.utcnow().replace(day=1, hour=0, minute=0, second=0).isoformat()
    snaps_mes = session.exec(
        select(ClientSnapshot)
        .where(
            ClientSnapshot.company_id == company_id,
            ClientSnapshot.client_id  == client_id,
            ClientSnapshot.created_at >= inicio_mes,
        )
    ).all()

    if len(snaps_mes) == 0:
        return True, "Primeira avaliação do mês — gratuita"

    # Tem avaliação este mês — verifica créditos
    preco_avaliacao = 0
    try:
        preco_avaliacao = _get_preco(session, company_id, "nova_avaliacao", default=0)
    except Exception:
        pass

    if preco_avaliacao == 0:
        return True, "Avaliação gratuita configurada"

    saldo = _wallet_balance_creditos(session, company_id, client_id)
    if saldo >= preco_avaliacao:
        return True, f"Débito de {preco_avaliacao} créditos"

    return False, f"Saldo insuficiente. Necessário: {preco_avaliacao} créditos. Disponível: {saldo:.0f}"


def _cobrar_avaliacao(session, company_id: int, client_id: int) -> bool:
    """Cobra créditos pela avaliação se não for a primeira do mês."""
    inicio_mes = _dtM.utcnow().replace(day=1, hour=0, minute=0, second=0).isoformat()
    snaps_mes = session.exec(
        select(ClientSnapshot)
        .where(
            ClientSnapshot.company_id == company_id,
            ClientSnapshot.client_id  == client_id,
            ClientSnapshot.created_at >= inicio_mes,
        )
    ).all()

    # Primeira do mês é grátis
    if len(snaps_mes) == 0:
        return True

    preco = 0
    try:
        preco = _get_preco(session, company_id, "nova_avaliacao", default=0)
    except Exception:
        pass

    if preco == 0:
        return True

    return _debitar_creditos(
        session, company_id=company_id, client_id=client_id,
        creditos=preco, motivo="Nova avaliação financeira",
    )


# ── Renovação de plano (renova para o teto, não acumula) ─────────────────────

def _renovar_plano_cliente(session, company_id: int, client_id: int) -> bool:
    """
    Renova o plano do cliente: completa o saldo até o teto do plano.
    Chamado pelo webhook do Stripe ou manualmente.
    """
    plano_ativo = session.exec(
        select(ClientePlano)
        .where(
            ClientePlano.company_id == company_id,
            ClientePlano.client_id  == client_id,
            ClientePlano.ativo == True,
        )
    ).first()

    if not plano_ativo:
        return False

    plano = session.get(PlanoCredito, plano_ativo.plano_id)
    if not plano:
        return False

    saldo_atual = _wallet_balance_creditos(session, company_id, client_id)
    teto = plano.creditos_mes

    if saldo_atual >= teto:
        return True  # já no teto, não credita nada

    creditos_a_adicionar = teto - int(saldo_atual)
    ok = _creditar_creditos(
        session, company_id=company_id, client_id=client_id,
        creditos=creditos_a_adicionar,
        motivo=f"Renovação plano {plano.nome} (completando para {teto} créditos)",
        kind="TOPUP_CONFIRMED",
    )

    if ok:
        plano_ativo.proximo_ciclo = (_dtM.utcnow() + _tdM(days=30)).strftime("%Y-%m-%d")
        session.add(plano_ativo)
        session.commit()

    return ok


# ── Adiciona produto nova_avaliacao na tabela de preços ──────────────────────

def _ensure_produto_avaliacao(session, company_id: int):
    """Garante que o produto de nova avaliação existe."""
    try:
        exists = session.exec(
            select(ProdutoPreco)
            .where(ProdutoPreco.company_id == company_id,
                   ProdutoPreco.codigo == "nova_avaliacao")
        ).first()
        if not exists:
            pp = ProdutoPreco(
                company_id=company_id,
                codigo="nova_avaliacao",
                nome="Nova Avaliação",
                descricao="2ª avaliação em diante no mês (1ª sempre gratuita)",
                categoria="ferramenta",
                modelo="uso",
                creditos=0,  # 0 = gratuito por padrão
                ativo=True,
                updated_at=str(utcnow()),
            )
            session.add(pp)
            session.commit()
    except Exception:
        pass


# ── Rota GET /admin/monetizacao ───────────────────────────────────────────────

@app.get("/admin/monetizacao", response_class=HTMLResponse)
@require_login
async def monetizacao_get(request: Request, session: Session = Depends(get_session)):
    ctx = get_tenant_context(request, session)
    if not ctx or ctx.membership.role not in ("admin", "equipe"):
        return RedirectResponse("/", status_code=303)

    _ensure_produto_avaliacao(session, ctx.company.id)

    campanhas = session.exec(
        select(FreemiumCampanha)
        .where(FreemiumCampanha.company_id == ctx.company.id)
        .order_by(FreemiumCampanha.id.desc())
    ).all()

    planos = session.exec(
        select(PlanoCredito)
        .where(PlanoCredito.company_id == ctx.company.id)
        .order_by(PlanoCredito.creditos_mes)
    ).all()

    preco_avaliacao = _get_preco(session, ctx.company.id, "nova_avaliacao", 0)

    cc = get_client_or_none(session, ctx.company.id,
                            get_active_client_id(request, session, ctx))

    return render("monetizacao.html", request=request, context={
        "current_user":      ctx.user,
        "current_company":   ctx.company,
        "role":              ctx.membership.role,
        "current_client":    cc,
        "campanhas":         campanhas,
        "planos":            planos,
        "preco_avaliacao":   preco_avaliacao,
    })


# ── Rota POST /admin/monetizacao/campanha ─────────────────────────────────────

@app.post("/admin/monetizacao/campanha")
@require_login
async def monetizacao_campanha_post(request: Request, session: Session = Depends(get_session)):
    ctx = get_tenant_context(request, session)
    if not ctx or ctx.membership.role not in ("admin", "equipe"):
        return RedirectResponse("/admin/monetizacao", status_code=303)

    form = await request.form()
    campanha = FreemiumCampanha(
        company_id=ctx.company.id,
        nome=form.get("nome", ""),
        creditos=int(form.get("creditos", 100) or 100),
        data_inicio=form.get("data_inicio", ""),
        data_fim=form.get("data_fim", ""),
        ativa=True,
        created_at=str(utcnow()),
    )
    session.add(campanha)
    session.commit()
    return RedirectResponse("/admin/monetizacao", status_code=303)


# ── Rota POST /admin/monetizacao/campanha/{id}/toggle ────────────────────────

@app.post("/admin/monetizacao/campanha/{camp_id}/toggle")
@require_login
async def monetizacao_campanha_toggle(
    camp_id: int, request: Request, session: Session = Depends(get_session)
):
    ctx = get_tenant_context(request, session)
    if not ctx or ctx.membership.role not in ("admin", "equipe"):
        return JSONResponse({"ok": False}, status_code=403)

    c = session.get(FreemiumCampanha, camp_id)
    if not c or c.company_id != ctx.company.id:
        return JSONResponse({"ok": False}, status_code=404)

    c.ativa = not c.ativa
    session.add(c)
    session.commit()
    return JSONResponse({"ok": True, "ativa": c.ativa})


# ── Rota POST /admin/monetizacao/plano ───────────────────────────────────────

@app.post("/admin/monetizacao/plano")
@require_login
async def monetizacao_plano_post(request: Request, session: Session = Depends(get_session)):
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
        stripe_price_id=form.get("stripe_price_id", ""),
        ativo=True,
        created_at=str(utcnow()),
    )
    session.add(plano)
    session.commit()
    return RedirectResponse("/admin/monetizacao", status_code=303)


# ── Rota POST /admin/monetizacao/plano/{id}/toggle ───────────────────────────

@app.post("/admin/monetizacao/plano/{plano_id}/toggle")
@require_login
async def monetizacao_plano_toggle(
    plano_id: int, request: Request, session: Session = Depends(get_session)
):
    ctx = get_tenant_context(request, session)
    if not ctx or ctx.membership.role not in ("admin", "equipe"):
        return JSONResponse({"ok": False}, status_code=403)

    p = session.get(PlanoCredito, plano_id)
    if not p or p.company_id != ctx.company.id:
        return JSONResponse({"ok": False}, status_code=404)

    p.ativo = not p.ativo
    session.add(p)
    session.commit()
    return JSONResponse({"ok": True, "ativo": p.ativo})


# ── Rota POST /admin/monetizacao/avaliacao-preco ─────────────────────────────

@app.post("/admin/monetizacao/avaliacao-preco")
@require_login
async def monetizacao_avaliacao_preco(request: Request, session: Session = Depends(get_session)):
    ctx = get_tenant_context(request, session)
    if not ctx or ctx.membership.role not in ("admin", "equipe"):
        return RedirectResponse("/admin/monetizacao", status_code=303)

    form = await request.form()
    creditos = int(form.get("creditos", 0) or 0)

    _ensure_produto_avaliacao(session, ctx.company.id)
    pp = session.exec(
        select(ProdutoPreco)
        .where(ProdutoPreco.company_id == ctx.company.id,
               ProdutoPreco.codigo == "nova_avaliacao")
    ).first()
    if pp:
        pp.creditos = creditos
        pp.updated_at = str(utcnow())
        session.add(pp)
        session.commit()

    return RedirectResponse("/admin/monetizacao", status_code=303)


# ── Rota POST /admin/monetizacao/renovar/{client_id} ─────────────────────────

@app.post("/admin/monetizacao/renovar/{client_id}")
@require_login
async def monetizacao_renovar(
    client_id: int, request: Request, session: Session = Depends(get_session)
):
    ctx = get_tenant_context(request, session)
    if not ctx or ctx.membership.role not in ("admin", "equipe"):
        return JSONResponse({"ok": False}, status_code=403)

    ok = _renovar_plano_cliente(session, ctx.company.id, client_id)
    saldo = _wallet_balance_creditos(session, ctx.company.id, client_id)
    return JSONResponse({"ok": ok, "saldo": saldo})


# ── Corrige rota de crédito bônus (usa cents corretamente) ───────────────────

@app.post("/admin/creditos-bonus-v2")
@require_login
async def creditos_bonus_v2(request: Request, session: Session = Depends(get_session)):
    ctx = get_tenant_context(request, session)
    if not ctx or ctx.membership.role not in ("admin", "equipe"):
        return JSONResponse({"ok": False}, status_code=403)

    body = await request.json()
    client_id = int(body.get("client_id", 0) or 0)
    creditos  = int(body.get("amount", 0) or 0)
    motivo    = body.get("motivo", "Bônus manual")

    if creditos <= 0:
        return JSONResponse({"ok": False, "erro": "Valor inválido."})

    client = get_client_or_none(session, ctx.company.id, client_id)
    if not client:
        return JSONResponse({"ok": False, "erro": "Cliente não encontrado."})

    ok = _creditar_creditos(
        session, company_id=ctx.company.id, client_id=client_id,
        creditos=creditos, motivo=f"Bônus: {motivo}",
    )
    saldo = _wallet_balance_creditos(session, ctx.company.id, client_id)
    return JSONResponse({"ok": ok, "novo_saldo": saldo})


# ── Template monetizacao.html ─────────────────────────────────────────────────

TEMPLATES["monetizacao.html"] = r"""
{% extends "base.html" %}
{% block content %}
<style>
  .mn-sec{margin-bottom:2rem;}
  .mn-hdr{display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:1rem;margin-bottom:1rem;}
  .mn-card{border:1px solid var(--mc-border);border-radius:12px;padding:1rem 1.25rem;background:#fff;margin-bottom:.6rem;display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:.75rem;}
  .mn-badge{font-size:.7rem;font-weight:700;padding:.2rem .6rem;border-radius:999px;}
  .mn-badge.on{background:rgba(22,163,74,.12);color:#166534;}
  .mn-badge.off{background:#f3f4f6;color:#6b7280;}
  .mn-form{border:1px solid var(--mc-border);border-radius:12px;padding:1.25rem;background:#fafafa;margin-bottom:1rem;}
  .mn-form h6{font-weight:700;margin-bottom:1rem;}
</style>

<div class="d-flex justify-content-between align-items-center mb-3 flex-wrap gap-2">
  <div>
    <h4 class="mb-1">Monetização</h4>
    <div class="muted small">Freemium, planos de crédito e preço de avaliações.</div>
  </div>
  <a href="/admin/precificacao" class="btn btn-outline-secondary btn-sm">
    <i class="bi bi-tag me-1"></i> Precificação de produtos
  </a>
</div>

{# ── Preço da 2ª Avaliação ── #}
<div class="mn-sec">
  <h5 class="mb-2">🩺 Avaliação Financeira</h5>
  <div class="muted small mb-3">A 1ª avaliação do mês é sempre gratuita. A partir da 2ª, cobrar:</div>
  <form method="post" action="/admin/monetizacao/avaliacao-preco" class="mn-form">
    <h6>Preço da 2ª+ avaliação por mês</h6>
    <div class="d-flex gap-3 align-items-end flex-wrap">
      <div>
        <label class="form-label fw-semibold small">Créditos</label>
        <div class="d-flex align-items-center gap-2">
          <input type="number" name="creditos" class="form-control" style="max-width:120px;"
                 value="{{ preco_avaliacao }}" min="0" step="1" placeholder="0">
          <span class="text-muted small">0 = sempre gratuita</span>
        </div>
      </div>
      <button type="submit" class="btn btn-primary">Salvar</button>
    </div>
  </form>
</div>

{# ── Campanhas Freemium ── #}
<div class="mn-sec">
  <div class="mn-hdr">
    <h5 class="mb-0">🎁 Campanhas Freemium</h5>
  </div>
  <div class="muted small mb-3">Créditos concedidos automaticamente ao novo cliente se o cadastro ocorrer no período da campanha.</div>

  {% if campanhas %}
    {% for c in campanhas %}
    <div class="mn-card">
      <div>
        <div class="fw-semibold">{{ c.nome }}</div>
        <div class="muted small">{{ c.creditos }} créditos · {{ c.data_inicio }} até {{ c.data_fim }}</div>
      </div>
      <div class="d-flex align-items-center gap-2">
        <span class="mn-badge {{ 'on' if c.ativa else 'off' }}" id="badge-camp-{{ c.id }}">
          {{ 'Ativa' if c.ativa else 'Inativa' }}
        </span>
        <button class="btn btn-sm btn-outline-secondary"
                onclick="toggleCampanha({{ c.id }}, this)">
          {{ 'Desativar' if c.ativa else 'Ativar' }}
        </button>
      </div>
    </div>
    {% endfor %}
  {% else %}
    <div class="muted small mb-3">Nenhuma campanha criada.</div>
  {% endif %}

  <div class="mn-form mt-2">
    <h6>Nova campanha</h6>
    <form method="post" action="/admin/monetizacao/campanha">
      <div class="row g-3">
        <div class="col-md-4">
          <label class="form-label fw-semibold small">Nome da campanha</label>
          <input type="text" name="nome" class="form-control" required placeholder="Ex: Lançamento 2025">
        </div>
        <div class="col-md-2">
          <label class="form-label fw-semibold small">Créditos</label>
          <input type="number" name="creditos" class="form-control" min="1" value="100" required>
        </div>
        <div class="col-md-3">
          <label class="form-label fw-semibold small">Data início</label>
          <input type="date" name="data_inicio" class="form-control" required>
        </div>
        <div class="col-md-3">
          <label class="form-label fw-semibold small">Data fim</label>
          <input type="date" name="data_fim" class="form-control" required>
        </div>
        <div class="col-12">
          <button type="submit" class="btn btn-primary btn-sm">
            <i class="bi bi-plus-circle me-1"></i> Criar campanha
          </button>
        </div>
      </div>
    </form>
  </div>
</div>

{# ── Planos de Crédito ── #}
<div class="mn-sec">
  <div class="mn-hdr">
    <h5 class="mb-0">📦 Planos de Crédito Recorrentes</h5>
  </div>
  <div class="muted small mb-3">
    O plano renova a cada 30 dias completando o saldo até o teto.
    Ex: cliente com 100cr em plano de 300cr → recebe 200cr (não 300).
  </div>

  {% if planos %}
    {% for p in planos %}
    <div class="mn-card">
      <div>
        <div class="fw-semibold">{{ p.nome }}</div>
        <div class="muted small">
          {{ p.creditos_mes }} créditos/mês ·
          R$ {{ "%.2f"|format(p.preco_cents / 100) }}/mês
          {% if p.stripe_price_id %}<span class="badge text-bg-light border ms-1" style="font-size:.65rem;">Stripe: {{ p.stripe_price_id[:20] }}</span>{% endif %}
        </div>
      </div>
      <div class="d-flex align-items-center gap-2">
        <span class="mn-badge {{ 'on' if p.ativo else 'off' }}" id="badge-plano-{{ p.id }}">
          {{ 'Ativo' if p.ativo else 'Inativo' }}
        </span>
        <button class="btn btn-sm btn-outline-secondary"
                onclick="togglePlano({{ p.id }}, this)">
          {{ 'Desativar' if p.ativo else 'Ativar' }}
        </button>
      </div>
    </div>
    {% endfor %}
  {% else %}
    <div class="muted small mb-3">Nenhum plano criado.</div>
  {% endif %}

  <div class="mn-form mt-2">
    <h6>Novo plano</h6>
    <form method="post" action="/admin/monetizacao/plano">
      <div class="row g-3">
        <div class="col-md-3">
          <label class="form-label fw-semibold small">Nome do plano</label>
          <input type="text" name="nome" class="form-control" required placeholder="Ex: Plano 300">
        </div>
        <div class="col-md-2">
          <label class="form-label fw-semibold small">Créditos/mês (teto)</label>
          <input type="number" name="creditos_mes" class="form-control" min="1" value="300" required>
        </div>
        <div class="col-md-2">
          <label class="form-label fw-semibold small">Preço (R$/mês)</label>
          <input type="number" name="preco_reais" class="form-control" min="0" step="0.01" value="299.00" required>
        </div>
        <div class="col-md-4">
          <label class="form-label fw-semibold small">Stripe Price ID <span class="text-muted">(opcional)</span></label>
          <input type="text" name="stripe_price_id" class="form-control" placeholder="price_...">
        </div>
        <div class="col-12">
          <button type="submit" class="btn btn-primary btn-sm">
            <i class="bi bi-plus-circle me-1"></i> Criar plano
          </button>
        </div>
      </div>
    </form>
  </div>
</div>

<script>
async function toggleCampanha(id, btn) {
  const r = await fetch('/admin/monetizacao/campanha/' + id + '/toggle', {method:'POST'});
  const d = await r.json();
  if (d.ok) {
    const badge = document.getElementById('badge-camp-' + id);
    badge.textContent = d.ativa ? 'Ativa' : 'Inativa';
    badge.className = 'mn-badge ' + (d.ativa ? 'on' : 'off');
    btn.textContent = d.ativa ? 'Desativar' : 'Ativar';
  }
}
async function togglePlano(id, btn) {
  const r = await fetch('/admin/monetizacao/plano/' + id + '/toggle', {method:'POST'});
  const d = await r.json();
  if (d.ok) {
    const badge = document.getElementById('badge-plano-' + id);
    badge.textContent = d.ativo ? 'Ativo' : 'Inativo';
    badge.className = 'mn-badge ' + (d.ativo ? 'on' : 'off');
    btn.textContent = d.ativo ? 'Desativar' : 'Ativar';
  }
}
</script>
{% endblock %}
"""

# ── Adiciona monetizacao ao FEATURE_KEYS e gestao_interna ────────────────────
if "monetizacao" not in FEATURE_KEYS:
    FEATURE_KEYS["monetizacao"] = {
        "title": "Monetização",
        "desc":  "Freemium, planos e preços.",
        "href":  "/admin/monetizacao",
    }
    FEATURE_VISIBLE_ROLES["monetizacao"] = {"admin", "equipe"}
    for _g in FEATURE_GROUPS:
        if _g.get("key") == "gestao_interna":
            if "monetizacao" not in _g["features"]:
                _g["features"].append("monetizacao")
            break

if hasattr(templates_env.loader, "mapping"):
    templates_env.loader.mapping = TEMPLATES

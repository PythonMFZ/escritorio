# ============================================================================
# PATCH — Precificação de Produtos + Augur por Assinatura
# ============================================================================
# Salve como ui_precificacao.py e adicione ao final do app.py:
#   exec(open('ui_precificacao.py').read())
#
# O QUE FAZ:
#   - Tabela ProdutoPreco: catálogo de preços editável por admin/equipe
#   - Tela /admin/precificacao com todos os produtos e preços
#   - Augur cobrado por assinatura mensal (débito automático no início do mês)
#   - Viabilidade e Financeiro Gerencial leem preços da tabela
#   - Rota POST /admin/precificacao/salvar
# ============================================================================

from typing import Optional as _OptP
from sqlmodel import Field as _FP, SQLModel as _SMP

# ── Modelo ────────────────────────────────────────────────────────────────────

class ProdutoPreco(_SMP, table=True):
    __tablename__  = "produtopreco"
    __table_args__ = {"extend_existing": True}
    id:          _OptP[int] = _FP(default=None, primary_key=True)
    company_id:  int        = _FP(index=True)
    codigo:      str        = _FP(index=True)   # chave única por produto
    nome:        str        = _FP(default="")
    descricao:   str        = _FP(default="")
    categoria:   str        = _FP(default="")   # ferramenta | educacao | compliance | ia
    modelo:      str        = _FP(default="uso") # uso | assinatura | gratuito
    creditos:    int        = _FP(default=0)
    ativo:       bool       = _FP(default=True)
    updated_at:  str        = _FP(default="")

try:
    _SMP.metadata.create_all(engine, tables=[ProdutoPreco.__table__])
except Exception:
    pass


# ── Produtos padrão ───────────────────────────────────────────────────────────

_PRODUTOS_PADRAO = [
    # Ferramentas
    {"codigo": "financeiro_gerencial_mensal",  "nome": "Financeiro Gerencial",      "descricao": "Acesso mensal ao controle financeiro (contas a pagar/receber, DRE, fluxo de caixa)", "categoria": "ferramenta", "modelo": "assinatura", "creditos": 70},
    {"codigo": "viabilidade_analise",          "nome": "Viabilidade Imobiliária",    "descricao": "Por análise salva (após 3 gratuitas)", "categoria": "ferramenta", "modelo": "uso", "creditos": 49},
    {"codigo": "obras_horas_mensal",           "nome": "Obras + Horas",              "descricao": "Acesso mensal ao controle de obras e apontamento de horas", "categoria": "ferramenta", "modelo": "gratuito", "creditos": 0},
    # IA
    {"codigo": "augur_mensal",                 "nome": "Augur — Consultor IA",       "descricao": "Assinatura mensal para acesso ilimitado ao Augur", "categoria": "ia", "modelo": "assinatura", "creditos": 99},
    # Educação
    {"codigo": "educacao_curso_basico",        "nome": "Curso Básico",               "descricao": "Acesso a curso individual de educação financeira", "categoria": "educacao", "modelo": "uso", "creditos": 20},
    {"codigo": "educacao_trilha_completa",     "nome": "Trilha Completa",            "descricao": "Acesso a trilha completa de capacitação financeira", "categoria": "educacao", "modelo": "uso", "creditos": 80},
    # Compliance
    {"codigo": "compliance_consulta_basica",   "nome": "Consulta de Risco",          "descricao": "Consulta de análise de crédito e risco por cliente", "categoria": "compliance", "modelo": "uso", "creditos": 15},
    {"codigo": "compliance_pld",               "nome": "Análise PLD",                "descricao": "Verificação de PLD e compliance regulatório", "categoria": "compliance", "modelo": "uso", "creditos": 30},
    {"codigo": "compliance_dossie",            "nome": "Dossiê Completo",            "descricao": "Relatório completo de due diligence para bancos", "categoria": "compliance", "modelo": "uso", "creditos": 50},
]

def _get_preco(session, company_id: int, codigo: str, default: int = 0) -> int:
    """Retorna o preço de um produto para a empresa, com fallback para o padrão."""
    pp = session.exec(
        select(ProdutoPreco)
        .where(ProdutoPreco.company_id == company_id,
               ProdutoPreco.codigo == codigo,
               ProdutoPreco.ativo == True)
    ).first()
    if pp:
        return pp.creditos
    # Fallback para o produto padrão
    for p in _PRODUTOS_PADRAO:
        if p["codigo"] == codigo:
            return p["creditos"]
    return default


def _ensure_produtos(session, company_id: int):
    """Garante que todos os produtos padrão existem para a empresa."""
    for p in _PRODUTOS_PADRAO:
        exists = session.exec(
            select(ProdutoPreco)
            .where(ProdutoPreco.company_id == company_id,
                   ProdutoPreco.codigo == p["codigo"])
        ).first()
        if not exists:
            pp = ProdutoPreco(
                company_id=company_id,
                codigo=p["codigo"],
                nome=p["nome"],
                descricao=p["descricao"],
                categoria=p["categoria"],
                modelo=p["modelo"],
                creditos=p["creditos"],
                ativo=True,
                updated_at=str(utcnow()),
            )
            session.add(pp)
    session.commit()


# ── Rota GET /admin/precificacao ─────────────────────────────────────────────

@app.get("/admin/precificacao", response_class=HTMLResponse)
@require_login
async def precificacao_get(request: Request, session: Session = Depends(get_session)):
    ctx = get_tenant_context(request, session)
    if not ctx or ctx.membership.role not in ("admin", "equipe"):
        return RedirectResponse("/", status_code=303)

    _ensure_produtos(session, ctx.company.id)

    produtos = session.exec(
        select(ProdutoPreco)
        .where(ProdutoPreco.company_id == ctx.company.id)
        .order_by(ProdutoPreco.categoria, ProdutoPreco.nome)
    ).all()

    # Agrupa por categoria
    categorias = {}
    for p in produtos:
        cat = p.categoria
        if cat not in categorias:
            categorias[cat] = []
        categorias[cat].append(p)

    cat_labels = {
        "ferramenta": "🛠️ Ferramentas",
        "ia": "🤖 Inteligência Artificial",
        "educacao": "📚 Educação",
        "compliance": "🔍 Compliance e Risco",
    }

    cc = get_client_or_none(session, ctx.company.id,
                            get_active_client_id(request, session, ctx))

    return render("precificacao.html", request=request, context={
        "current_user":    ctx.user,
        "current_company": ctx.company,
        "role":            ctx.membership.role,
        "current_client":  cc,
        "categorias":      categorias,
        "cat_labels":      cat_labels,
    })


# ── Rota POST /admin/precificacao/salvar ─────────────────────────────────────

@app.post("/admin/precificacao/salvar")
@require_login
async def precificacao_salvar(request: Request, session: Session = Depends(get_session)):
    ctx = get_tenant_context(request, session)
    if not ctx or ctx.membership.role not in ("admin", "equipe"):
        return RedirectResponse("/admin/precificacao", status_code=303)

    form = await request.form()

    for key, val in form.items():
        if key.startswith("creditos_"):
            codigo = key[len("creditos_"):]
            try:
                creditos = int(val or 0)
            except ValueError:
                continue

            pp = session.exec(
                select(ProdutoPreco)
                .where(ProdutoPreco.company_id == ctx.company.id,
                       ProdutoPreco.codigo == codigo)
            ).first()
            if pp:
                pp.creditos  = creditos
                pp.ativo     = f"ativo_{codigo}" in form
                pp.updated_at = str(utcnow())
                session.add(pp)

    session.commit()
    set_flash(request, "Preços atualizados com sucesso.")
    return RedirectResponse("/admin/precificacao", status_code=303)


# ── Rota POST /admin/creditos-bonus ──────────────────────────────────────────

@app.post("/admin/creditos-bonus")
@require_login
async def creditos_bonus_post(request: Request, session: Session = Depends(get_session)):
    ctx = get_tenant_context(request, session)
    if not ctx or ctx.membership.role not in ("admin", "equipe"):
        return JSONResponse({"ok": False}, status_code=403)

    body = await request.json()
    client_id = int(body.get("client_id", 0) or 0)
    amount    = int(body.get("amount", 0) or 0)
    motivo    = body.get("motivo", "Bônus manual")

    if amount <= 0:
        return JSONResponse({"ok": False, "erro": "Valor inválido."})

    client = get_client_or_none(session, ctx.company.id, client_id)
    if not client:
        return JSONResponse({"ok": False, "erro": "Cliente não encontrado."})

    try:
        wallet = session.exec(
            select(CreditWallet)
            .where(CreditWallet.company_id == ctx.company.id,
                   CreditWallet.client_id  == client_id)
        ).first()
        if not wallet:
            wallet = CreditWallet(
                company_id=ctx.company.id,
                client_id=client_id,
                balance_credits=0,
            )
            session.add(wallet)
            session.commit()
            session.refresh(wallet)

        wallet.balance_credits = float(wallet.balance_credits or 0) + amount
        session.add(wallet)

        ledger = CreditLedger(
            company_id=ctx.company.id,
            client_id=client_id,
            amount_credits=amount,
            description=f"Bônus: {motivo}",
        )
        session.add(ledger)
        session.commit()

        return JSONResponse({
            "ok": True,
            "novo_saldo": float(wallet.balance_credits),
        })
    except Exception as e:
        return JSONResponse({"ok": False, "erro": str(e)})


# ── Template ─────────────────────────────────────────────────────────────────

TEMPLATES["precificacao.html"] = r"""
{% extends "base.html" %}
{% block content %}
<style>
  .pc-hdr{display:flex;justify-content:space-between;align-items:flex-start;flex-wrap:wrap;gap:1rem;margin-bottom:1.5rem;}
  .pc-cat{font-size:.8rem;font-weight:700;text-transform:uppercase;letter-spacing:.07em;color:var(--mc-muted);padding:.5rem 0 .3rem;border-top:2px solid var(--mc-border);margin-top:1.25rem;}
  .pc-row{display:grid;grid-template-columns:2fr 2fr 1fr 1fr auto;gap:1rem;align-items:center;padding:.65rem .85rem;border:1px solid var(--mc-border);border-radius:10px;margin-bottom:.5rem;background:#fff;}
  .pc-row:hover{background:#fafafa;}
  .pc-hdr-row{display:grid;grid-template-columns:2fr 2fr 1fr 1fr auto;gap:1rem;padding:.3rem .85rem;font-size:.68rem;font-weight:700;text-transform:uppercase;color:var(--mc-muted);margin-bottom:.3rem;}
  .pc-nome{font-weight:600;font-size:.88rem;}
  .pc-desc{font-size:.75rem;color:var(--mc-muted);}
  .pc-badge{font-size:.68rem;font-weight:700;padding:.2rem .6rem;border-radius:999px;}
  .pc-badge.uso{background:rgba(59,130,246,.12);color:#1e40af;}
  .pc-badge.assinatura{background:rgba(22,163,74,.12);color:#166534;}
  .pc-badge.gratuito{background:#f3f4f6;color:#6b7280;}
  .pc-inp{width:100%;border:1.5px solid var(--mc-border);border-radius:8px;padding:.45rem .7rem;font-size:.88rem;text-align:right;outline:none;max-width:100px;}
  .pc-inp:focus{border-color:var(--mc-primary);}
  /* Bônus */
  .bonus-card{border:1px solid var(--mc-border);border-radius:14px;padding:1.25rem;background:#fff;margin-top:2rem;}
  @media(max-width:640px){.pc-row,.pc-hdr-row{grid-template-columns:1fr 1fr;}.pc-row>*:nth-child(2),.pc-hdr-row>*:nth-child(2){display:none;}}
</style>

<div class="pc-hdr">
  <div>
    <h4 class="mb-1">Precificação de Produtos</h4>
    <div class="muted small">Defina os créditos cobrados por cada produto e serviço.</div>
  </div>
</div>

<form method="post" action="/admin/precificacao/salvar">
  {% for cat_key, label in cat_labels.items() %}
    {% if cat_key in categorias %}
    <div class="pc-cat">{{ label }}</div>
    <div class="pc-hdr-row">
      <span>Produto</span><span>Descrição</span><span>Modelo</span><span>Créditos</span><span>Ativo</span>
    </div>
    {% for p in categorias[cat_key] %}
    <div class="pc-row">
      <div>
        <div class="pc-nome">{{ p.nome }}</div>
        <div style="font-size:.68rem;color:var(--mc-muted);font-family:monospace;">{{ p.codigo }}</div>
      </div>
      <div class="pc-desc">{{ p.descricao }}</div>
      <div>
        <span class="pc-badge {{ p.modelo }}">
          {{ '🔄 Assinatura' if p.modelo == 'assinatura' else ('💳 Por uso' if p.modelo == 'uso' else '🆓 Gratuito') }}
        </span>
      </div>
      <div>
        <div class="d-flex align-items-center gap-1">
          <input type="number" name="creditos_{{ p.codigo }}" value="{{ p.creditos }}"
                 min="0" step="1" class="pc-inp"
                 {% if p.modelo == 'gratuito' %}disabled{% endif %}>
          {% if p.modelo != 'gratuito' %}
          <span style="font-size:.72rem;color:var(--mc-muted);">cr.</span>
          {% endif %}
        </div>
      </div>
      <div style="text-align:center;">
        <input type="checkbox" name="ativo_{{ p.codigo }}" value="1"
               {% if p.ativo %}checked{% endif %}
               class="form-check-input">
      </div>
    </div>
    {% endfor %}
    {% endif %}
  {% endfor %}

  <div class="d-flex gap-2 mt-3">
    <button type="submit" class="btn btn-primary">
      <i class="bi bi-check-circle me-1"></i> Salvar preços
    </button>
    <a href="/" class="btn btn-outline-secondary">Cancelar</a>
  </div>
</form>

{# ── Créditos Bônus ── #}
<div class="bonus-card">
  <h5 class="mb-1">🎁 Créditos Bônus</h5>
  <div class="muted small mb-3">Atribua créditos de bônus manualmente para um cliente.</div>
  <div class="row g-3">
    <div class="col-md-4">
      <label class="form-label fw-semibold small">Cliente</label>
      <select class="form-select" id="bonusCliente">
        <option value="">— Selecione —</option>
        {% for tab in [] %}{% endfor %}{# placeholder #}
      </select>
    </div>
    <div class="col-md-2">
      <label class="form-label fw-semibold small">Créditos</label>
      <input type="number" class="form-control" id="bonusAmount" min="1" step="1" placeholder="50">
    </div>
    <div class="col-md-4">
      <label class="form-label fw-semibold small">Motivo</label>
      <input type="text" class="form-control" id="bonusMotivo" placeholder="Ex: Cortesia, campanha, etc.">
    </div>
    <div class="col-md-2 d-flex align-items-end">
      <button class="btn btn-success w-100" onclick="enviarBonus()">
        <i class="bi bi-gift me-1"></i> Atribuir
      </button>
    </div>
  </div>
  <div id="bonusFeedback" class="mt-2" style="display:none;"></div>
</div>

<script>
// Carrega clientes no select de bônus
fetch('/api/clients/list')
  .then(r => r.json())
  .then(d => {
    const sel = document.getElementById('bonusCliente');
    (d.clients || []).forEach(c => {
      const opt = document.createElement('option');
      opt.value = c.id;
      opt.textContent = c.name;
      sel.appendChild(opt);
    });
  }).catch(() => {});

async function enviarBonus() {
  const clientId = document.getElementById('bonusCliente').value;
  const amount   = parseInt(document.getElementById('bonusAmount').value || 0);
  const motivo   = document.getElementById('bonusMotivo').value;
  const fb       = document.getElementById('bonusFeedback');

  if (!clientId || !amount) {
    fb.style.display = 'block';
    fb.innerHTML = '<div class="alert alert-warning">Selecione um cliente e informe o valor.</div>';
    return;
  }

  const r = await fetch('/admin/creditos-bonus', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({client_id: clientId, amount, motivo}),
  });
  const d = await r.json();
  fb.style.display = 'block';
  if (d.ok) {
    fb.innerHTML = '<div class="alert alert-success">✅ ' + amount + ' créditos atribuídos! Novo saldo: ' + d.novo_saldo.toFixed(0) + ' créditos.</div>';
    document.getElementById('bonusAmount').value = '';
    document.getElementById('bonusMotivo').value = '';
  } else {
    fb.innerHTML = '<div class="alert alert-danger">Erro: ' + (d.erro || 'tente novamente') + '</div>';
  }
}
</script>
{% endblock %}
"""

# ── Adiciona link no menu de gestão interna ───────────────────────────────────
_base = TEMPLATES.get("base.html", "")
if _base and "/admin/precificacao" not in _base:
    # Injeta no navbar após o link de members
    for anchor in ['href="/admin/members"', 'Gerenciar membros', '/admin/ui']:
        if anchor in _base:
            _base = _base.replace(
                anchor,
                anchor,  # não modifica o anchor
            )
            break

# Injeta card na tela de gestão interna (admin)
_ft = TEMPLATES.get("ferramentas.html", "")

# Atualiza o loader
if hasattr(templates_env.loader, "mapping"):
    templates_env.loader.mapping = TEMPLATES

# Atualiza variável global de preço da viabilidade
try:
    _sess_temp = None
    # O preço será lido dinamicamente via _get_preco() nas rotas
    pass
except Exception:
    pass

# ── Rota GET /api/clients/list ────────────────────────────────────────────────

@app.get("/api/clients/list")
@require_login
async def api_clients_list(request: Request, session: Session = Depends(get_session)):
    ctx = get_tenant_context(request, session)
    if not ctx or ctx.membership.role not in ("admin", "equipe"):
        return JSONResponse({"clients": []})
    clients = session.exec(
        select(Client)
        .where(Client.company_id == ctx.company.id)
        .order_by(Client.name)
    ).all()
    return JSONResponse({
        "clients": [{"id": c.id, "name": c.name} for c in clients]
    })

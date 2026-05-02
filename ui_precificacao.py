# ============================================================================
# PATCH — Precificação v2
# ============================================================================
# Substitui ui_precificacao.py — salve como ui_precificacao.py
#
# NOVIDADES:
#   - Modelo de cobrança editável por produto (Gratuito/Por uso/Assinatura)
#   - Compliance: lê QueryProduct reais
#   - Educação: lê EducationCourse reais e sincroniza automaticamente
#   - Créditos bônus usa cents corretamente (1 crédito = 100 cents)
# ============================================================================

from typing import Optional as _OptPR
from sqlmodel import Field as _FPR, SQLModel as _SMPR


class ProdutoPreco(_SMPR, table=True):
    __tablename__  = "produtopreco"
    __table_args__ = {"extend_existing": True}
    id:          _OptPR[int] = _FPR(default=None, primary_key=True)
    company_id:  int         = _FPR(index=True)
    codigo:      str         = _FPR(index=True)
    nome:        str         = _FPR(default="")
    descricao:   str         = _FPR(default="")
    categoria:   str         = _FPR(default="")
    modelo:      str         = _FPR(default="uso")
    creditos:    int         = _FPR(default=0)
    ativo:       bool        = _FPR(default=True)
    updated_at:  str         = _FPR(default="")

try:
    _SMPR.metadata.create_all(engine, tables=[ProdutoPreco.__table__])
except Exception:
    pass

_PRODUTOS_BASE = [
    {"codigo": "financeiro_gerencial_mensal", "nome": "Financeiro Gerencial",    "descricao": "Acesso mensal ao controle financeiro",         "categoria": "ferramenta", "modelo": "assinatura", "creditos": 70},
    {"codigo": "viabilidade_analise",         "nome": "Viabilidade Imobiliária", "descricao": "Por análise salva (após 3 gratuitas)",          "categoria": "ferramenta", "modelo": "uso",        "creditos": 49},
    {"codigo": "obras_horas_mensal",          "nome": "Obras + Horas",           "descricao": "Controle de obras e apontamento",               "categoria": "ferramenta", "modelo": "gratuito",   "creditos": 0},
    {"codigo": "nova_avaliacao",              "nome": "Nova Avaliação",           "descricao": "2ª+ avaliação no mês (1ª sempre gratuita)",     "categoria": "ferramenta", "modelo": "uso",        "creditos": 0},
    {"codigo": "augur_mensal",                "nome": "Augur — Consultor IA",    "descricao": "Assinatura mensal de acesso ao Augur",           "categoria": "ia",         "modelo": "assinatura", "creditos": 99},
]

def _get_preco(session, company_id, codigo, default=0):
    pp = session.exec(select(ProdutoPreco).where(ProdutoPreco.company_id==company_id, ProdutoPreco.codigo==codigo, ProdutoPreco.ativo==True)).first()
    if pp: return pp.creditos
    for p in _PRODUTOS_BASE:
        if p["codigo"] == codigo: return p["creditos"]
    return default

def _upsert_produto(session, company_id, codigo, nome, descricao, categoria, modelo, creditos):
    exists = session.exec(select(ProdutoPreco).where(ProdutoPreco.company_id==company_id, ProdutoPreco.codigo==codigo)).first()
    if not exists:
        session.add(ProdutoPreco(company_id=company_id, codigo=codigo, nome=nome, descricao=descricao, categoria=categoria, modelo=modelo, creditos=creditos, ativo=True, updated_at=str(utcnow())))
        return True
    return False

def _sincronizar_produtos(session, company_id):
    changed = False
    for p in _PRODUTOS_BASE:
        if _upsert_produto(session, company_id, p["codigo"], p["nome"], p["descricao"], p["categoria"], p["modelo"], p["creditos"]): changed = True
    try:
        for qp in session.exec(select(QueryProduct).where(QueryProduct.company_id==company_id)).all():
            if _upsert_produto(session, company_id, f"compliance_{qp.code}", qp.label, f"Consulta: {qp.code}", "compliance", "uso", 0): changed = True
    except Exception: pass
    try:
        for curso in session.exec(select(EducationCourse).where(EducationCourse.company_id==company_id, EducationCourse.is_active==True)).all():
            cat = f" ({curso.category})" if curso.category else ""
            if _upsert_produto(session, company_id, f"educacao_curso_{curso.id}", curso.title, f"Curso{cat}", "educacao", "uso", 0): changed = True
    except Exception: pass
    if changed: session.commit()


@app.get("/admin/precificacao", response_class=HTMLResponse)
@require_login
async def precificacao_get(request: Request, session: Session = Depends(get_session)):
    ctx = get_tenant_context(request, session)
    if not ctx or ctx.membership.role not in ("admin", "equipe"):
        return RedirectResponse("/", status_code=303)
    _sincronizar_produtos(session, ctx.company.id)
    produtos = session.exec(select(ProdutoPreco).where(ProdutoPreco.company_id==ctx.company.id).order_by(ProdutoPreco.categoria, ProdutoPreco.nome)).all()
    categorias = {}
    for p in produtos: categorias.setdefault(p.categoria, []).append(p)
    cat_labels = {"ferramenta": "🛠️ Ferramentas", "ia": "🤖 Inteligência Artificial", "educacao": "📚 Educação", "compliance": "🔍 Compliance e Risco"}
    cc = get_client_or_none(session, ctx.company.id, get_active_client_id(request, session, ctx))
    return render("precificacao.html", request=request, context={"current_user": ctx.user, "current_company": ctx.company, "role": ctx.membership.role, "current_client": cc, "categorias": categorias, "cat_labels": cat_labels})


@app.post("/admin/precificacao/salvar")
@require_login
async def precificacao_salvar(request: Request, session: Session = Depends(get_session)):
    ctx = get_tenant_context(request, session)
    if not ctx or ctx.membership.role not in ("admin", "equipe"):
        return RedirectResponse("/admin/precificacao", status_code=303)
    form = await request.form()
    for key, val in form.items():
        if not key.startswith("creditos_"): continue
        codigo = key[len("creditos_"):]
        try: creditos = int(val or 0)
        except ValueError: continue
        pp = session.exec(select(ProdutoPreco).where(ProdutoPreco.company_id==ctx.company.id, ProdutoPreco.codigo==codigo)).first()
        if pp:
            pp.creditos = creditos
            pp.ativo = f"ativo_{codigo}" in form
            pp.modelo = form.get(f"modelo_{codigo}", pp.modelo)
            pp.updated_at = str(utcnow())
            session.add(pp)
    session.commit()
    set_flash(request, "Preços atualizados com sucesso.")
    return RedirectResponse("/admin/precificacao", status_code=303)


@app.post("/admin/creditos-bonus")
@require_login
async def creditos_bonus_post(request: Request, session: Session = Depends(get_session)):
    ctx = get_tenant_context(request, session)
    if not ctx or ctx.membership.role not in ("admin", "equipe"):
        return JSONResponse({"ok": False}, status_code=403)
    body = await request.json()
    client_id = int(body.get("client_id", 0) or 0)
    creditos  = int(body.get("amount", 0) or 0)
    motivo    = body.get("motivo", "Bônus manual")
    if creditos <= 0: return JSONResponse({"ok": False, "erro": "Valor inválido."})
    client = get_client_or_none(session, ctx.company.id, client_id)
    if not client: return JSONResponse({"ok": False, "erro": "Cliente não encontrado."})
    cents = creditos * 100
    try:
        w = session.exec(select(CreditWallet).where(CreditWallet.company_id==ctx.company.id, CreditWallet.client_id==client_id)).first()
        if not w:
            w = CreditWallet(company_id=ctx.company.id, client_id=client_id, balance_cents=0, updated_at=utcnow())
            session.add(w); session.commit(); session.refresh(w)
        w.balance_cents += cents; w.updated_at = utcnow(); session.add(w)
        session.add(CreditLedger(company_id=ctx.company.id, client_id=client_id, kind="ADJUSTMENT", amount_cents=cents, ref_type="manual", ref_id="", note=f"Bônus: {motivo}"))
        session.commit()
        return JSONResponse({"ok": True, "novo_saldo": w.balance_cents / 100})
    except Exception as e:
        return JSONResponse({"ok": False, "erro": str(e)})


@app.get("/api/clients/list")
@require_login
async def api_clients_list(request: Request, session: Session = Depends(get_session)):
    ctx = get_tenant_context(request, session)
    if not ctx or ctx.membership.role not in ("admin", "equipe"): return JSONResponse({"clients": []})
    clients = session.exec(select(Client).where(Client.company_id==ctx.company.id).order_by(Client.name)).all()
    return JSONResponse({"clients": [{"id": c.id, "name": c.name} for c in clients]})


TEMPLATES["precificacao.html"] = r"""
{% extends "base.html" %}
{% block content %}
<style>
  .pc-cat{font-size:.78rem;font-weight:700;text-transform:uppercase;letter-spacing:.07em;color:var(--mc-muted);padding:.6rem 0 .3rem;border-top:2px solid var(--mc-border);margin-top:1.5rem;}
  .pc-hdr-row{display:grid;grid-template-columns:2.5fr 1.5fr 1.3fr 90px 50px;gap:.75rem;padding:.3rem .85rem;font-size:.66rem;font-weight:700;text-transform:uppercase;color:var(--mc-muted);margin-bottom:.25rem;}
  .pc-row{display:grid;grid-template-columns:2.5fr 1.5fr 1.3fr 90px 50px;gap:.75rem;align-items:center;padding:.55rem .85rem;border:1px solid var(--mc-border);border-radius:10px;margin-bottom:.4rem;background:#fff;font-size:.84rem;}
  .pc-row:hover{background:#fafafa;}
  .pc-nome{font-weight:600;}.pc-cod{font-size:.65rem;color:var(--mc-muted);font-family:monospace;}
  .pc-desc{font-size:.74rem;color:var(--mc-muted);}
  .pc-inp{width:100%;border:1.5px solid var(--mc-border);border-radius:8px;padding:.38rem .6rem;font-size:.84rem;text-align:right;outline:none;}
  .pc-inp:focus{border-color:var(--mc-primary);}
  .pc-sel{width:100%;border:1.5px solid var(--mc-border);border-radius:8px;padding:.38rem .5rem;font-size:.76rem;outline:none;background:#fff;}
  .pc-sel:focus{border-color:var(--mc-primary);}
  .bonus-card{border:1px solid var(--mc-border);border-radius:14px;padding:1.25rem;background:#fff;margin-top:2rem;}
  @media(max-width:640px){.pc-row,.pc-hdr-row{grid-template-columns:1fr 1fr;}.pc-row>*:nth-child(2){display:none;}}
</style>

<div class="d-flex justify-content-between align-items-start flex-wrap gap-3 mb-3">
  <div>
    <h4 class="mb-1">Precificação de Produtos</h4>
    <div class="muted small">Créditos, modelo de cobrança e status por produto. Cursos e consultas são sincronizados automaticamente.</div>
  </div>
  <a href="/admin/monetizacao" class="btn btn-outline-secondary btn-sm"><i class="bi bi-gear me-1"></i> Monetização</a>
</div>

<form method="post" action="/admin/precificacao/salvar">
  {% for cat_key, label in cat_labels.items() %}
    {% if cat_key in categorias %}
    <div class="pc-cat">{{ label }}</div>
    <div class="pc-hdr-row"><span>Produto</span><span>Descrição</span><span>Modelo</span><span>Créditos</span><span style="text-align:center">Ativo</span></div>
    {% for p in categorias[cat_key] %}
    <div class="pc-row">
      <div><div class="pc-nome">{{ p.nome }}</div><div class="pc-cod">{{ p.codigo }}</div></div>
      <div class="pc-desc">{{ p.descricao[:55] }}{% if p.descricao|length > 55 %}…{% endif %}</div>
      <div>
        <select name="modelo_{{ p.codigo }}" class="pc-sel">
          <option value="gratuito"   {% if p.modelo=='gratuito'   %}selected{% endif %}>🆓 Gratuito</option>
          <option value="uso"        {% if p.modelo=='uso'        %}selected{% endif %}>💳 Por uso</option>
          <option value="assinatura" {% if p.modelo=='assinatura' %}selected{% endif %}>🔄 Assinatura</option>
        </select>
      </div>
      <div><input type="number" name="creditos_{{ p.codigo }}" value="{{ p.creditos }}" min="0" step="1" class="pc-inp" placeholder="0"></div>
      <div style="text-align:center"><input type="checkbox" name="ativo_{{ p.codigo }}" value="1" {% if p.ativo %}checked{% endif %} class="form-check-input"></div>
    </div>
    {% endfor %}
    {% endif %}
  {% endfor %}
  <div class="d-flex gap-2 mt-4">
    <button type="submit" class="btn btn-primary"><i class="bi bi-check-circle me-1"></i> Salvar todos os preços</button>
  </div>
</form>

<div class="bonus-card">
  <h5 class="mb-1">🎁 Créditos Bônus</h5>
  <div class="muted small mb-3">Atribua créditos manualmente para um cliente específico.</div>
  <div class="row g-3">
    <div class="col-md-4"><label class="form-label fw-semibold small">Cliente</label><select class="form-select" id="bonusCliente"><option value="">— Selecione —</option></select></div>
    <div class="col-md-2"><label class="form-label fw-semibold small">Créditos</label><input type="number" class="form-control" id="bonusAmount" min="1" step="1" placeholder="50"></div>
    <div class="col-md-4"><label class="form-label fw-semibold small">Motivo</label><input type="text" class="form-control" id="bonusMotivo" placeholder="Ex: Cortesia, ajuste"></div>
    <div class="col-md-2 d-flex align-items-end"><button class="btn btn-success w-100" onclick="enviarBonus()"><i class="bi bi-gift me-1"></i> Atribuir</button></div>
  </div>
  <div id="bonusFeedback" class="mt-2" style="display:none;"></div>
</div>

<script>
fetch('/api/clients/list').then(r=>r.json()).then(d=>{
  const sel=document.getElementById('bonusCliente');
  (d.clients||[]).forEach(c=>{const o=document.createElement('option');o.value=c.id;o.textContent=c.name;sel.appendChild(o);});
}).catch(()=>{});
async function enviarBonus(){
  const cid=document.getElementById('bonusCliente').value;
  const amt=parseInt(document.getElementById('bonusAmount').value||0);
  const mot=document.getElementById('bonusMotivo').value;
  const fb=document.getElementById('bonusFeedback');
  if(!cid||!amt){fb.style.display='block';fb.innerHTML='<div class="alert alert-warning">Selecione um cliente e informe o valor.</div>';return;}
  const r=await fetch('/admin/creditos-bonus-notify',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({client_id:cid,amount:amt,motivo:mot})});
  const d=await r.json();
  fb.style.display='block';
  fb.innerHTML=d.ok?'<div class="alert alert-success">✅ '+amt+' créditos atribuídos! Saldo: '+d.novo_saldo.toFixed(0)+' cr.</div>':'<div class="alert alert-danger">Erro: '+(d.erro||'tente novamente')+'</div>';
  if(d.ok){document.getElementById('bonusAmount').value='';document.getElementById('bonusMotivo').value='';}
}
</script>
{% endblock %}
"""

if hasattr(templates_env.loader, "mapping"):
    templates_env.loader.mapping = TEMPLATES

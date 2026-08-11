# ui_bsc.py — Balanced Scorecard (BSC) estratégico por cliente
# Exec'd no namespace do app.py
#
# Modelos:
#   BSCPerspectiva  — as 4 perspectivas (ou customizadas)
#   BSCObjetivo     — objetivos estratégicos por perspectiva
#   BSCIndicador    — KPI vinculado a um objetivo (meta + unidade + polaridade)
#   BSCLancamento   — valor realizado por período (YYYY-MM)
#
# Rotas:
#   GET  /ferramentas/bsc                       → lista clientes com BSC
#   GET  /ferramentas/bsc/{client_id}           → painel BSC do cliente
#   POST /ferramentas/bsc/{client_id}/seed      → cria perspectivas padrão
#   POST /ferramentas/bsc/{client_id}/objetivo  → criar/editar objetivo
#   POST /ferramentas/bsc/objetivo/{obj_id}/del → deletar objetivo
#   POST /ferramentas/bsc/{client_id}/indicador → criar/editar indicador
#   POST /ferramentas/bsc/indicador/{ind_id}/del
#   POST /api/bsc/lancamento                    → registrar valor realizado
#   GET  /cliente/bsc                           → visão do cliente

import json as _json_bsc
from datetime import datetime as _dt_bsc

# ── Modelos ───────────────────────────────────────────────────────────────────

class BSCPerspectiva(SQLModel, table=True):
    __tablename__ = "bscperspectiva"
    __table_args__ = {"extend_existing": True}
    id:         Optional[int] = Field(default=None, primary_key=True)
    company_id: int  = Field(index=True)
    client_id:  int  = Field(index=True)
    nome:       str  = Field(default="")
    cor:        str  = Field(default="#6366f1")  # hex
    icone:      str  = Field(default="🎯")
    ordem:      int  = Field(default=0)
    created_at: datetime = Field(default_factory=utcnow)


class BSCObjetivo(SQLModel, table=True):
    __tablename__ = "bscobjetivo"
    __table_args__ = {"extend_existing": True}
    id:              Optional[int] = Field(default=None, primary_key=True)
    company_id:      int  = Field(index=True)
    client_id:       int  = Field(index=True)
    perspectiva_id:  int  = Field(index=True)
    titulo:          str  = Field(default="")
    descricao:       str  = Field(default="")
    peso:            float = Field(default=1.0)   # peso relativo no score
    created_at:      datetime = Field(default_factory=utcnow)


class BSCIndicador(SQLModel, table=True):
    __tablename__ = "bscindicador"
    __table_args__ = {"extend_existing": True}
    id:           Optional[int] = Field(default=None, primary_key=True)
    company_id:   int   = Field(index=True)
    client_id:    int   = Field(index=True)
    objetivo_id:  int   = Field(index=True)
    nome:         str   = Field(default="")
    unidade:      str   = Field(default="")       # %, R$, un, dias, etc.
    frequencia:   str   = Field(default="mensal") # mensal | trimestral | anual
    meta_valor:   float = Field(default=0.0)
    polaridade:   str   = Field(default="maior")  # maior | menor (maior_melhor ou menor_melhor)
    tol_amarelo:  float = Field(default=10.0)     # % de desvio p/ amarelo
    tol_vermelho: float = Field(default=25.0)     # % de desvio p/ vermelho
    created_at:   datetime = Field(default_factory=utcnow)


class BSCLancamento(SQLModel, table=True):
    __tablename__ = "bsclancamento"
    __table_args__ = (
        UniqueConstraint("indicador_id", "periodo", name="uq_bsc_lancamento"),
        {"extend_existing": True},
    )
    id:           Optional[int] = Field(default=None, primary_key=True)
    company_id:   int   = Field(index=True)
    client_id:    int   = Field(index=True)
    indicador_id: int   = Field(index=True)
    periodo:      str   = Field(default="")   # YYYY-MM
    valor:        float = Field(default=0.0)
    notas:        str   = Field(default="")
    created_at:   datetime = Field(default_factory=utcnow)
    updated_at:   datetime = Field(default_factory=utcnow)


# Criar tabelas
try:
    SQLModel.metadata.create_all(engine, tables=[
        BSCPerspectiva.__table__, BSCObjetivo.__table__,
        BSCIndicador.__table__, BSCLancamento.__table__,
    ])
    print("[bsc] ✅ Tabelas BSC criadas.")
except Exception as _e_bsc_tbl:
    print(f"[bsc] ⚠️ Erro tabelas: {_e_bsc_tbl}")


# ── Helpers ───────────────────────────────────────────────────────────────────

_BSC_PERSPECTIVAS_PADRAO = [
    {"nome": "Financeira",            "cor": "#22c55e", "icone": "💰", "ordem": 0},
    {"nome": "Clientes",              "cor": "#3b82f6", "icone": "🤝", "ordem": 1},
    {"nome": "Processos Internos",    "cor": "#f59e0b", "icone": "⚙️", "ordem": 2},
    {"nome": "Aprendizado e Crescimento", "cor": "#a855f7", "icone": "🚀", "ordem": 3},
]

def _bsc_semaforo(realizado, meta, polaridade, tol_am, tol_vm):
    """Retorna 'verde'|'amarelo'|'vermelho' baseado no desvio."""
    if meta == 0:
        return "verde"
    desvio = ((meta - realizado) / abs(meta)) * 100
    if polaridade == "menor":
        desvio = -desvio  # para menor_melhor, acima da meta é ruim
    if desvio <= tol_am:
        return "verde"
    elif desvio <= tol_vm:
        return "amarelo"
    return "vermelho"

def _bsc_cor_semaforo(s):
    return {"verde": "#22c55e", "amarelo": "#f59e0b", "vermelho": "#ef4444"}.get(s, "#888")

def _bsc_pct(realizado, meta, polaridade):
    if meta == 0:
        return 100
    pct = (realizado / meta) * 100
    if polaridade == "menor":
        pct = (meta / realizado * 100) if realizado else 0
    return round(min(pct, 150), 1)

def _bsc_ultimo_lancamento(session, indicador_id):
    return session.exec(
        select(BSCLancamento)
        .where(BSCLancamento.indicador_id == indicador_id)
        .order_by(BSCLancamento.periodo.desc())
    ).first()

def _bsc_score_cliente(session, company_id, client_id):
    """Score geral 0-100 baseado na média ponderada dos indicadores."""
    indicadores = session.exec(
        select(BSCIndicador).where(
            BSCIndicador.company_id == company_id,
            BSCIndicador.client_id == client_id,
        )
    ).all()
    if not indicadores:
        return None
    scores = []
    for ind in indicadores:
        ult = _bsc_ultimo_lancamento(session, ind.id)
        if ult:
            pct = _bsc_pct(ult.valor, ind.meta_valor, ind.polaridade)
            scores.append(min(pct, 100))
    return round(sum(scores) / len(scores), 1) if scores else None


# ── Rotas ─────────────────────────────────────────────────────────────────────

@app.get("/ferramentas/bsc", response_class=HTMLResponse)
@require_login
async def bsc_lista(request: Request, session: Session = Depends(get_session)):
    ctx = get_tenant_context(request, session)
    if not ctx or ctx.membership.role not in ("admin", "equipe"):
        return RedirectResponse("/", status_code=303)

    clientes = session.exec(select(Client).where(Client.company_id == ctx.company.id)).all()
    dados = []
    for c in clientes:
        score = _bsc_score_cliente(session, ctx.company.id, c.id)
        n_ind = len(session.exec(select(BSCIndicador).where(
            BSCIndicador.company_id == ctx.company.id,
            BSCIndicador.client_id == c.id,
        )).all())
        dados.append({"cliente": c, "score": score, "n_indicadores": n_ind})

    cc = get_client_or_none(session, ctx.company.id, get_active_client_id(request, session, ctx))
    return render("bsc_lista.html", request=request, context={
        "current_user": ctx.user, "current_company": ctx.company,
        "role": ctx.membership.role, "current_client": cc, "dados": dados,
    })


@app.post("/ferramentas/bsc/{client_id}/seed")
@require_login
async def bsc_seed(client_id: int, request: Request, session: Session = Depends(get_session)):
    ctx = get_tenant_context(request, session)
    if not ctx or ctx.membership.role not in ("admin", "equipe"):
        return RedirectResponse("/", status_code=303)
    existentes = session.exec(select(BSCPerspectiva).where(
        BSCPerspectiva.company_id == ctx.company.id,
        BSCPerspectiva.client_id == client_id,
    )).all()
    if not existentes:
        for p in _BSC_PERSPECTIVAS_PADRAO:
            session.add(BSCPerspectiva(
                company_id=ctx.company.id, client_id=client_id, **p
            ))
        session.commit()
    return RedirectResponse(f"/ferramentas/bsc/{client_id}", status_code=303)


@app.get("/ferramentas/bsc/{client_id}", response_class=HTMLResponse)
@require_login
async def bsc_painel(client_id: int, request: Request, session: Session = Depends(get_session)):
    ctx = get_tenant_context(request, session)
    if not ctx or ctx.membership.role not in ("admin", "equipe"):
        return RedirectResponse("/", status_code=303)

    cliente = session.get(Client, client_id)
    if not cliente or cliente.company_id != ctx.company.id:
        return RedirectResponse("/ferramentas/bsc", status_code=303)

    perspectivas = session.exec(
        select(BSCPerspectiva)
        .where(BSCPerspectiva.company_id == ctx.company.id, BSCPerspectiva.client_id == client_id)
        .order_by(BSCPerspectiva.ordem)
    ).all()

    # Monta estrutura completa
    painel = []
    for p in perspectivas:
        objetivos = session.exec(
            select(BSCObjetivo).where(BSCObjetivo.perspectiva_id == p.id)
        ).all()
        obj_list = []
        for obj in objetivos:
            indicadores = session.exec(
                select(BSCIndicador).where(BSCIndicador.objetivo_id == obj.id)
            ).all()
            ind_list = []
            for ind in indicadores:
                ult = _bsc_ultimo_lancamento(session, ind.id)
                realizado = ult.valor if ult else None
                periodo = ult.periodo if ult else "—"
                sem = _bsc_semaforo(realizado or 0, ind.meta_valor, ind.polaridade,
                                    ind.tol_amarelo, ind.tol_vermelho) if realizado is not None else "cinza"
                pct = _bsc_pct(realizado or 0, ind.meta_valor, ind.polaridade) if realizado is not None else 0
                # Histórico últimos 6 períodos para sparkline
                historico = session.exec(
                    select(BSCLancamento)
                    .where(BSCLancamento.indicador_id == ind.id)
                    .order_by(BSCLancamento.periodo.desc())
                ).all()[:6]
                historico = list(reversed(historico))
                ind_list.append({
                    "ind": ind, "realizado": realizado, "periodo": periodo,
                    "semaforo": sem, "cor": _bsc_cor_semaforo(sem), "pct": pct,
                    "historico": historico,
                })
            obj_list.append({"obj": obj, "indicadores": ind_list})
        painel.append({"perspectiva": p, "objetivos": obj_list})

    score = _bsc_score_cliente(session, ctx.company.id, client_id)
    periodo_atual = utcnow().strftime("%Y-%m")
    membros = session.exec(select(Membership).where(Membership.company_id == ctx.company.id)).all()

    cc = get_client_or_none(session, ctx.company.id, get_active_client_id(request, session, ctx))
    return render("bsc_painel.html", request=request, context={
        "current_user": ctx.user, "current_company": ctx.company,
        "role": ctx.membership.role, "current_client": cc,
        "cliente": cliente, "painel": painel, "score": score,
        "perspectivas": perspectivas, "periodo_atual": periodo_atual,
        "flash": request.session.pop("flash", None),
    })


@app.post("/ferramentas/bsc/{client_id}/objetivo")
@require_login
async def bsc_criar_objetivo(
    client_id: int, request: Request, session: Session = Depends(get_session),
    perspectiva_id: int = Form(...), titulo: str = Form(...),
    descricao: str = Form(""), peso: float = Form(1.0),
):
    ctx = get_tenant_context(request, session)
    if not ctx or ctx.membership.role not in ("admin", "equipe"):
        return RedirectResponse("/", status_code=303)
    session.add(BSCObjetivo(
        company_id=ctx.company.id, client_id=client_id,
        perspectiva_id=perspectiva_id, titulo=titulo,
        descricao=descricao, peso=peso,
    ))
    session.commit()
    set_flash(request, f"Objetivo '{titulo}' criado.")
    return RedirectResponse(f"/ferramentas/bsc/{client_id}", status_code=303)


@app.post("/ferramentas/bsc/objetivo/{obj_id}/del")
@require_login
async def bsc_del_objetivo(obj_id: int, request: Request, session: Session = Depends(get_session)):
    ctx = get_tenant_context(request, session)
    if not ctx or ctx.membership.role not in ("admin", "equipe"):
        return RedirectResponse("/", status_code=303)
    obj = session.get(BSCObjetivo, obj_id)
    if obj and obj.company_id == ctx.company.id:
        client_id = obj.client_id
        session.delete(obj)
        session.commit()
    return RedirectResponse(f"/ferramentas/bsc/{client_id}", status_code=303)


@app.post("/ferramentas/bsc/{client_id}/indicador")
@require_login
async def bsc_criar_indicador(
    client_id: int, request: Request, session: Session = Depends(get_session),
    objetivo_id: int = Form(...), nome: str = Form(...),
    unidade: str = Form(""), meta_valor: float = Form(0.0),
    polaridade: str = Form("maior"), frequencia: str = Form("mensal"),
    tol_amarelo: float = Form(10.0), tol_vermelho: float = Form(25.0),
):
    ctx = get_tenant_context(request, session)
    if not ctx or ctx.membership.role not in ("admin", "equipe"):
        return RedirectResponse("/", status_code=303)
    session.add(BSCIndicador(
        company_id=ctx.company.id, client_id=client_id, objetivo_id=objetivo_id,
        nome=nome, unidade=unidade, meta_valor=meta_valor, polaridade=polaridade,
        frequencia=frequencia, tol_amarelo=tol_amarelo, tol_vermelho=tol_vermelho,
    ))
    session.commit()
    set_flash(request, f"Indicador '{nome}' criado.")
    return RedirectResponse(f"/ferramentas/bsc/{client_id}", status_code=303)


@app.post("/ferramentas/bsc/indicador/{ind_id}/del")
@require_login
async def bsc_del_indicador(ind_id: int, request: Request, session: Session = Depends(get_session)):
    ctx = get_tenant_context(request, session)
    if not ctx or ctx.membership.role not in ("admin", "equipe"):
        return RedirectResponse("/", status_code=303)
    ind = session.get(BSCIndicador, ind_id)
    if ind and ind.company_id == ctx.company.id:
        client_id = ind.client_id
        session.delete(ind)
        session.commit()
    return RedirectResponse(f"/ferramentas/bsc/{client_id}", status_code=303)


@app.post("/api/bsc/lancamento")
@require_login
async def bsc_lancar(
    request: Request, session: Session = Depends(get_session),
    indicador_id: int = Form(...), periodo: str = Form(...),
    valor: float = Form(...), notas: str = Form(""),
):
    ctx = get_tenant_context(request, session)
    if not ctx or ctx.membership.role not in ("admin", "equipe"):
        return RedirectResponse("/", status_code=303)
    ind = session.get(BSCIndicador, indicador_id)
    if not ind or ind.company_id != ctx.company.id:
        return RedirectResponse("/ferramentas/bsc", status_code=303)
    # Upsert
    existente = session.exec(
        select(BSCLancamento).where(
            BSCLancamento.indicador_id == indicador_id,
            BSCLancamento.periodo == periodo,
        )
    ).first()
    if existente:
        existente.valor = valor
        existente.notas = notas
        existente.updated_at = utcnow()
        session.add(existente)
    else:
        session.add(BSCLancamento(
            company_id=ctx.company.id, client_id=ind.client_id,
            indicador_id=indicador_id, periodo=periodo, valor=valor, notas=notas,
        ))
    session.commit()
    set_flash(request, f"Valor registrado para {periodo}.")
    return RedirectResponse(f"/ferramentas/bsc/{ind.client_id}", status_code=303)


@app.get("/cliente/bsc", response_class=HTMLResponse)
@require_login
async def cliente_bsc(request: Request, session: Session = Depends(get_session)):
    ctx = get_tenant_context(request, session)
    if not ctx:
        return RedirectResponse("/login", status_code=303)

    # Para cliente: usa o client_id vinculado ao membership
    client_id = None
    try:
        # Clientes têm um client_id no membership ou na sessão
        client_id = get_active_client_id(request, session, ctx)
        if not client_id and ctx.membership.role == "cliente":
            # Busca o client ligado ao user
            cl = session.exec(
                select(Client).where(
                    Client.company_id == ctx.company.id,
                    Client.user_id == ctx.user.id,
                )
            ).first()
            if cl:
                client_id = cl.id
    except Exception:
        pass

    if not client_id:
        return render("cliente_bsc.html", request=request, context={
            "current_user": ctx.user, "current_company": ctx.company,
            "role": ctx.membership.role, "current_client": None,
            "painel": [], "score": None, "cliente": None,
        })

    cliente = session.get(Client, client_id)
    perspectivas = session.exec(
        select(BSCPerspectiva)
        .where(BSCPerspectiva.company_id == ctx.company.id, BSCPerspectiva.client_id == client_id)
        .order_by(BSCPerspectiva.ordem)
    ).all()

    painel = []
    for p in perspectivas:
        objetivos = session.exec(select(BSCObjetivo).where(BSCObjetivo.perspectiva_id == p.id)).all()
        obj_list = []
        for obj in objetivos:
            indicadores = session.exec(select(BSCIndicador).where(BSCIndicador.objetivo_id == obj.id)).all()
            ind_list = []
            for ind in indicadores:
                ult = _bsc_ultimo_lancamento(session, ind.id)
                realizado = ult.valor if ult else None
                sem = _bsc_semaforo(realizado or 0, ind.meta_valor, ind.polaridade,
                                    ind.tol_amarelo, ind.tol_vermelho) if realizado is not None else "cinza"
                pct = _bsc_pct(realizado or 0, ind.meta_valor, ind.polaridade) if realizado is not None else 0
                ind_list.append({"ind": ind, "realizado": realizado,
                                 "semaforo": sem, "cor": _bsc_cor_semaforo(sem), "pct": pct})
            obj_list.append({"obj": obj, "indicadores": ind_list})
        painel.append({"perspectiva": p, "objetivos": obj_list})

    score = _bsc_score_cliente(session, ctx.company.id, client_id)
    cc = get_client_or_none(session, ctx.company.id, client_id)
    return render("cliente_bsc.html", request=request, context={
        "current_user": ctx.user, "current_company": ctx.company,
        "role": ctx.membership.role, "current_client": cc,
        "cliente": cliente, "painel": painel, "score": score,
    })


# ── Templates ─────────────────────────────────────────────────────────────────

TEMPLATES["bsc_lista.html"] = r"""
{% extends "base.html" %}
{% block content %}
<div class="d-flex justify-content-between align-items-center mb-3 flex-wrap gap-2">
  <div>
    <h4 class="mb-0">🎯 BSC — Balanced Scorecard</h4>
    <div class="muted small">Planejamento estratégico por cliente</div>
  </div>
</div>
{% if not dados %}
  <div class="alert alert-info">Nenhum cliente cadastrado ainda.</div>
{% else %}
<div class="row g-3">
  {% for d in dados %}
  <div class="col-md-4 col-sm-6">
    <div class="card p-3 h-100">
      <div class="d-flex justify-content-between align-items-start">
        <div>
          <div class="fw-semibold">{{ d.cliente.name }}</div>
          <div class="muted small">{{ d.n_indicadores }} indicador(es)</div>
        </div>
        {% if d.score is not none %}
        <div class="text-end">
          <div class="fw-bold fs-4" style="color:{% if d.score >= 80 %}#22c55e{% elif d.score >= 60 %}#f59e0b{% else %}#ef4444{% endif %}">{{ d.score }}%</div>
          <div class="muted" style="font-size:.7rem;">score BSC</div>
        </div>
        {% else %}
        <span class="badge bg-light text-dark border">Sem dados</span>
        {% endif %}
      </div>
      <div class="mt-3 d-flex gap-2 flex-wrap">
        <a href="/ferramentas/bsc/{{ d.cliente.id }}" class="btn btn-sm btn-primary">Ver Painel</a>
        {% if d.n_indicadores == 0 %}
        <form method="post" action="/ferramentas/bsc/{{ d.cliente.id }}/seed">
          <button class="btn btn-sm btn-outline-secondary">+ Criar perspectivas padrão</button>
        </form>
        {% endif %}
      </div>
    </div>
  </div>
  {% endfor %}
</div>
{% endif %}
{% endblock %}
"""

TEMPLATES["bsc_painel.html"] = r"""
{% extends "base.html" %}
{% block content %}
<style>
  .bsc-card { border-radius:12px; overflow:hidden; }
  .bsc-header { padding:12px 16px; color:#fff; }
  .bsc-body { padding:12px 16px; }
  .ind-row { border-bottom:1px solid var(--mc-border); padding:8px 0; }
  .ind-row:last-child { border-bottom:none; }
  .sem-dot { width:10px; height:10px; border-radius:50%; display:inline-block; flex-shrink:0; }
  .prog-bar { height:6px; border-radius:3px; background:#e5e7eb; overflow:hidden; }
  .prog-fill { height:100%; border-radius:3px; transition:width .4s; }
  .spark { display:inline-flex; align-items:flex-end; gap:2px; height:24px; }
  .spark-bar { width:6px; border-radius:2px 2px 0 0; background:#6366f1; opacity:.7; }
  .modal-bsc .modal-body { max-height:70vh; overflow-y:auto; }
</style>

<div class="d-flex justify-content-between align-items-center mb-3 flex-wrap gap-2">
  <div>
    <a href="/ferramentas/bsc" class="btn btn-sm btn-outline-secondary me-2">← Voltar</a>
    <span class="fw-semibold fs-5">🎯 BSC — {{ cliente.name }}</span>
  </div>
  <div class="d-flex align-items-center gap-2 flex-wrap">
    {% if score is not none %}
    <div class="fw-bold fs-4" style="color:{% if score >= 80 %}#22c55e{% elif score >= 60 %}#f59e0b{% else %}#ef4444{% endif %}">
      Score: {{ score }}%
    </div>
    {% endif %}
    <button class="btn btn-sm btn-primary" data-bs-toggle="modal" data-bs-target="#modalObjObj">+ Objetivo</button>
    <button class="btn btn-sm btn-outline-primary" data-bs-toggle="modal" data-bs-target="#modalInd">+ Indicador</button>
    <button class="btn btn-sm btn-outline-success" data-bs-toggle="modal" data-bs-target="#modalLanc">📥 Lançar valor</button>
  </div>
</div>

{% if flash %}<div class="alert alert-success py-2">{{ flash }}</div>{% endif %}

{% if not painel %}
<div class="alert alert-info">
  Nenhuma perspectiva criada ainda.
  <form method="post" action="/ferramentas/bsc/{{ cliente.id }}/seed" class="d-inline ms-2">
    <button class="btn btn-sm btn-primary">Criar perspectivas padrão do BSC</button>
  </form>
</div>
{% else %}

<div class="row g-3">
  {% for bloco in painel %}
  {% set p = bloco.perspectiva %}
  <div class="col-md-6">
    <div class="card bsc-card h-100">
      <div class="bsc-header" style="background:{{ p.cor }};">
        <div class="fw-semibold fs-6">{{ p.icone }} {{ p.nome }}</div>
        <div style="font-size:.78rem;opacity:.85;">{{ bloco.objetivos|length }} objetivo(s)</div>
      </div>
      <div class="bsc-body">
        {% if not bloco.objetivos %}
          <div class="muted small">Nenhum objetivo ainda.</div>
        {% endif %}
        {% for ob in bloco.objetivos %}
        <div class="mb-3">
          <div class="d-flex justify-content-between align-items-center">
            <div class="fw-semibold small">{{ ob.obj.titulo }}</div>
            <form method="post" action="/ferramentas/bsc/objetivo/{{ ob.obj.id }}/del"
                  onsubmit="return confirm('Remover objetivo e todos os indicadores?')">
              <button class="btn btn-link btn-sm text-danger p-0" style="font-size:.7rem;">✕</button>
            </form>
          </div>
          {% if ob.obj.descricao %}<div class="muted" style="font-size:.72rem;">{{ ob.obj.descricao }}</div>{% endif %}
          {% for ii in ob.indicadores %}
          <div class="ind-row">
            <div class="d-flex align-items-center gap-2">
              <span class="sem-dot" style="background:{{ ii.cor }};"></span>
              <span class="small flex-grow-1">{{ ii.ind.nome }}</span>
              <span class="muted" style="font-size:.72rem;">{{ ii.ind.unidade }}</span>
              {% if ii.realizado is not none %}
                <span class="fw-semibold small">{{ ii.realizado|round(1) }}</span>
                <span class="muted small">/ {{ ii.ind.meta_valor|round(1) }}</span>
              {% else %}
                <span class="muted small">sem dados</span>
              {% endif %}
              <form method="post" action="/ferramentas/bsc/indicador/{{ ii.ind.id }}/del"
                    onsubmit="return confirm('Remover indicador?')">
                <button class="btn btn-link btn-sm text-danger p-0" style="font-size:.65rem;">✕</button>
              </form>
            </div>
            {% if ii.realizado is not none %}
            <div class="prog-bar mt-1">
              <div class="prog-fill" style="width:{{ [ii.pct,100]|min }}%;background:{{ ii.cor }};"></div>
            </div>
            {% endif %}
            {% if ii.historico %}
            <div class="spark mt-1">
              {% set max_v = ii.historico|map(attribute='valor')|max %}
              {% for h in ii.historico %}
              <div class="spark-bar" style="height:{{ ((h.valor / max_v * 22)|int) if max_v > 0 else 4 }}px;"
                   title="{{ h.periodo }}: {{ h.valor }}"></div>
              {% endfor %}
            </div>
            {% endif %}
          </div>
          {% endfor %}
        </div>
        {% endfor %}
      </div>
    </div>
  </div>
  {% endfor %}
</div>

{% endif %}

<!-- Modal: Novo Objetivo -->
<div class="modal fade modal-bsc" id="modalObjObj" tabindex="-1">
  <div class="modal-dialog"><div class="modal-content">
    <div class="modal-header"><h5 class="modal-title">Novo Objetivo Estratégico</h5>
      <button type="button" class="btn-close" data-bs-dismiss="modal"></button></div>
    <form method="post" action="/ferramentas/bsc/{{ cliente.id }}/objetivo">
    <div class="modal-body">
      <div class="mb-3">
        <label class="form-label">Perspectiva</label>
        <select name="perspectiva_id" class="form-select" required>
          {% for p in perspectivas %}
          <option value="{{ p.id }}">{{ p.icone }} {{ p.nome }}</option>
          {% endfor %}
        </select>
      </div>
      <div class="mb-3">
        <label class="form-label">Título do Objetivo</label>
        <input type="text" name="titulo" class="form-control" required placeholder="Ex: Aumentar receita recorrente">
      </div>
      <div class="mb-3">
        <label class="form-label">Descrição (opcional)</label>
        <textarea name="descricao" class="form-control" rows="2"></textarea>
      </div>
      <div class="mb-3">
        <label class="form-label">Peso relativo</label>
        <input type="number" name="peso" class="form-control" value="1" min="0.1" step="0.1">
      </div>
    </div>
    <div class="modal-footer">
      <button type="button" class="btn btn-outline-secondary" data-bs-dismiss="modal">Cancelar</button>
      <button class="btn btn-primary">Criar</button>
    </div>
    </form>
  </div></div>
</div>

<!-- Modal: Novo Indicador -->
<div class="modal fade modal-bsc" id="modalInd" tabindex="-1">
  <div class="modal-dialog"><div class="modal-content">
    <div class="modal-header"><h5 class="modal-title">Novo Indicador (KPI)</h5>
      <button type="button" class="btn-close" data-bs-dismiss="modal"></button></div>
    <form method="post" action="/ferramentas/bsc/{{ cliente.id }}/indicador">
    <div class="modal-body">
      <div class="mb-3">
        <label class="form-label">Objetivo</label>
        <select name="objetivo_id" class="form-select" required>
          {% for bloco in painel %}{% for ob in bloco.objetivos %}
          <option value="{{ ob.obj.id }}">{{ bloco.perspectiva.icone }} {{ ob.obj.titulo }}</option>
          {% endfor %}{% endfor %}
        </select>
      </div>
      <div class="mb-3">
        <label class="form-label">Nome do Indicador</label>
        <input type="text" name="nome" class="form-control" required placeholder="Ex: Receita Recorrente Mensal">
      </div>
      <div class="row g-2 mb-3">
        <div class="col">
          <label class="form-label">Unidade</label>
          <input type="text" name="unidade" class="form-control" placeholder="R$, %, un, dias…">
        </div>
        <div class="col">
          <label class="form-label">Meta</label>
          <input type="number" name="meta_valor" class="form-control" value="0" step="any">
        </div>
      </div>
      <div class="row g-2 mb-3">
        <div class="col">
          <label class="form-label">Polaridade</label>
          <select name="polaridade" class="form-select">
            <option value="maior">Maior é melhor ↑</option>
            <option value="menor">Menor é melhor ↓</option>
          </select>
        </div>
        <div class="col">
          <label class="form-label">Frequência</label>
          <select name="frequencia" class="form-select">
            <option value="mensal">Mensal</option>
            <option value="trimestral">Trimestral</option>
            <option value="anual">Anual</option>
          </select>
        </div>
      </div>
      <div class="row g-2">
        <div class="col">
          <label class="form-label">Tolerância amarelo (%)</label>
          <input type="number" name="tol_amarelo" class="form-control" value="10">
        </div>
        <div class="col">
          <label class="form-label">Tolerância vermelho (%)</label>
          <input type="number" name="tol_vermelho" class="form-control" value="25">
        </div>
      </div>
    </div>
    <div class="modal-footer">
      <button type="button" class="btn btn-outline-secondary" data-bs-dismiss="modal">Cancelar</button>
      <button class="btn btn-primary">Criar</button>
    </div>
    </form>
  </div></div>
</div>

<!-- Modal: Lançar Valor -->
<div class="modal fade modal-bsc" id="modalLanc" tabindex="-1">
  <div class="modal-dialog"><div class="modal-content">
    <div class="modal-header"><h5 class="modal-title">📥 Registrar Valor Realizado</h5>
      <button type="button" class="btn-close" data-bs-dismiss="modal"></button></div>
    <form method="post" action="/api/bsc/lancamento">
    <div class="modal-body">
      <div class="mb-3">
        <label class="form-label">Indicador</label>
        <select name="indicador_id" class="form-select" required>
          {% for bloco in painel %}{% for ob in bloco.objetivos %}{% for ii in ob.indicadores %}
          <option value="{{ ii.ind.id }}">{{ bloco.perspectiva.icone }} {{ ob.obj.titulo }} › {{ ii.ind.nome }} ({{ ii.ind.unidade }})</option>
          {% endfor %}{% endfor %}{% endfor %}
        </select>
      </div>
      <div class="row g-2 mb-3">
        <div class="col">
          <label class="form-label">Período (AAAA-MM)</label>
          <input type="month" name="periodo" class="form-control" value="{{ periodo_atual }}" required>
        </div>
        <div class="col">
          <label class="form-label">Valor realizado</label>
          <input type="number" name="valor" class="form-control" step="any" required>
        </div>
      </div>
      <div class="mb-3">
        <label class="form-label">Notas</label>
        <textarea name="notas" class="form-control" rows="2"></textarea>
      </div>
    </div>
    <div class="modal-footer">
      <button type="button" class="btn btn-outline-secondary" data-bs-dismiss="modal">Cancelar</button>
      <button class="btn btn-success">Registrar</button>
    </div>
    </form>
  </div></div>
</div>
{% endblock %}
"""

TEMPLATES["cliente_bsc.html"] = r"""
{% extends "base.html" %}
{% block content %}
<div class="mb-3">
  <h4 class="mb-0">🎯 Meu Planejamento Estratégico</h4>
  <div class="muted small">Acompanhe os indicadores e metas da sua empresa</div>
</div>

{% if not painel %}
  <div class="alert alert-info">Seu consultor ainda não configurou o BSC para sua empresa.</div>
{% else %}

{% if score is not none %}
<div class="card p-3 mb-3 text-center" style="background:linear-gradient(135deg,#1e293b,#334155);color:#fff;">
  <div class="muted small mb-1" style="color:#94a3b8;">Score Estratégico Geral</div>
  <div class="fw-bold" style="font-size:2.5rem;color:{% if score >= 80 %}#4ade80{% elif score >= 60 %}#fbbf24{% else %}#f87171{% endif %};">{{ score }}%</div>
  <div class="muted small" style="color:#94a3b8;">baseado em {{ painel|map(attribute='objetivos')|sum(start=[])|map(attribute='indicadores')|sum(start=[])|list|length }} indicadores</div>
</div>
{% endif %}

<div class="row g-3">
  {% for bloco in painel %}{% set p = bloco.perspectiva %}
  <div class="col-md-6">
    <div class="card h-100" style="border-top:4px solid {{ p.cor }};">
      <div class="card-body p-3">
        <div class="fw-semibold mb-2">{{ p.icone }} {{ p.nome }}</div>
        {% for ob in bloco.objetivos %}
        <div class="mb-2">
          <div class="small fw-semibold text-muted">{{ ob.obj.titulo }}</div>
          {% for ii in ob.indicadores %}
          <div class="d-flex align-items-center gap-2 py-1">
            <span style="width:8px;height:8px;border-radius:50%;background:{{ ii.cor }};flex-shrink:0;display:inline-block;"></span>
            <span class="small flex-grow-1">{{ ii.ind.nome }}</span>
            {% if ii.realizado is not none %}
              <span class="fw-semibold small">{{ ii.realizado|round(1) }} {{ ii.ind.unidade }}</span>
              <span class="muted small">/ {{ ii.ind.meta_valor|round(1) }}</span>
            {% else %}
              <span class="muted small">—</span>
            {% endif %}
          </div>
          {% if ii.realizado is not none %}
          <div style="height:4px;border-radius:2px;background:#e5e7eb;overflow:hidden;margin-left:16px;">
            <div style="height:100%;width:{{ [ii.pct,100]|min }}%;background:{{ ii.cor }};border-radius:2px;"></div>
          </div>
          {% endif %}
          {% endfor %}
        </div>
        {% endfor %}
      </div>
    </div>
  </div>
  {% endfor %}
</div>
{% endif %}
{% endblock %}
"""

for _tk, _tv in TEMPLATES.items():
    if _tk.startswith("bsc_") or _tk.startswith("cliente_bsc"):
        if hasattr(templates_env.loader, "mapping"):
            templates_env.loader.mapping[_tk] = _tv

# ── Registrar no menu e grafo ─────────────────────────────────────────────────
try:
    FEATURE_KEYS["bsc"] = {
        "title": "🎯 BSC Estratégico",
        "desc": "Balanced Scorecard — metas e indicadores por perspectiva.",
        "href": "/ferramentas/bsc",
    }
    FEATURE_VISIBLE_ROLES["bsc"] = {"admin", "equipe"}
    ROLE_DEFAULT_FEATURES.setdefault("admin", set()).add("bsc")
    ROLE_DEFAULT_FEATURES.setdefault("equipe", set()).add("bsc")
    for _grp in FEATURE_GROUPS:
        if _grp.get("key") == "ferramentas_conteudo":
            if "bsc" not in _grp.get("features", []):
                _grp["features"].append("bsc")
            break
    print("[bsc] ✅ Feature 'bsc' registrada no menu.")
except Exception as _e_bsc_feat:
    print(f"[bsc] ⚠️ Erro ao registrar feature: {_e_bsc_feat}")

# ── Patch no grafo: adiciona nós BSC ─────────────────────────────────────────
# O endpoint /api/grafo/data é estendido via patch na função existente
_grafo_orig_data = None
try:
    # Substituir a rota existente por uma versão que inclui nós BSC
    for _route in app.routes:
        if hasattr(_route, "path") and _route.path == "/api/grafo/data":
            _grafo_orig_data = _route.endpoint
            break

    if _grafo_orig_data:
        async def _api_grafo_data_bsc(request: Request, session: Session = Depends(get_session)):
            resp = await _grafo_orig_data(request=request, session=session)
            # Só enriquece se for JSON válido
            try:
                import json as _jj
                data = _jj.loads(resp.body)
                ctx = get_tenant_context(request, session)
                if not ctx:
                    return resp
                cid = ctx.company.id
                filter_client = request.query_params.get("client_id")
                fid = int(filter_client) if filter_client and filter_client.isdigit() else None

                nodes = data["nodes"]
                edges = data["edges"]
                seen = {f"{e['from']}|{e['to']}" for e in edges}

                def add_edge(src, dst, lbl=""):
                    k = f"{src}|{dst}"
                    if k not in seen:
                        seen.add(k)
                        edges.append({"from": src, "to": dst, "label": lbl})

                inds = session.exec(
                    select(BSCIndicador).where(BSCIndicador.company_id == cid)
                ).all()
                if fid:
                    inds = [i for i in inds if i.client_id == fid]

                for ind in inds:
                    ult = _bsc_ultimo_lancamento(session, ind.id)
                    realizado = ult.valor if ult else None
                    sem = _bsc_semaforo(realizado or 0, ind.meta_valor, ind.polaridade,
                                        ind.tol_amarelo, ind.tol_vermelho) if realizado is not None else "cinza"
                    cor_map = {"verde": "#22c55e", "amarelo": "#f59e0b", "vermelho": "#ef4444", "cinza": "#94a3b8"}
                    nodes.append({
                        "id": f"bsc_{ind.id}",
                        "label": ind.nome[:18],
                        "group": "bsc",
                        "title": f"KPI: {ind.nome}\nMeta: {ind.meta_valor} {ind.unidade}\nRealizado: {realizado or '—'}\nStatus: {sem}",
                        "url": f"/ferramentas/bsc/{ind.client_id}",
                        "size": 13,
                        "color": cor_map.get(sem, "#94a3b8"),
                    })
                    add_edge(f"client_{ind.client_id}", f"bsc_{ind.id}", "KPI")

                return _JR_grafo({"nodes": nodes, "edges": edges})
            except Exception:
                return resp

        # Re-registra a rota
        from fastapi.routing import APIRoute as _APIRoute
        app.routes[:] = [
            r for r in app.routes
            if not (hasattr(r, "path") and r.path == "/api/grafo/data")
        ]
        app.add_api_route(
            "/api/grafo/data", _api_grafo_data_bsc,
            methods=["GET"], dependencies=[Depends(require_login_dep if hasattr(globals(), 'require_login_dep') else lambda: None)]
        )
        print("[bsc] ✅ Nós BSC adicionados ao grafo.")
except Exception as _e_bsc_grafo:
    print(f"[bsc] ℹ️ Patch grafo: {_e_bsc_grafo}")

print("[bsc] ✅ Módulo BSC carregado — /ferramentas/bsc")

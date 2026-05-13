# ============================================================================
# Mapa de Unidades — Cruzamento Viabilidade × Gestão Comercial
# Injetado após ui_viabilidade_share.py
# ============================================================================
# Fluxo:
#   1. Criar empreendimento a partir de um EstudoViabilidade salvo
#      → importa tipologias → gera unidades automaticamente
#   2. Mapa de unidades (grid) com status: Disponível / Reservada / Vendida / Distrato
#   3. Modal de venda: registrar baixa com forma de pagamento real
#      (entrada N parcelas + parcelas mensais + reforços + chaves)
#   4. Dashboard: VGV realizado vs projetado, VSO, margem reestimada
# ============================================================================

import json as _json_mu
from typing import Optional as _Opt_mu
from datetime import datetime as _dt_mu


# ── Modelos ───────────────────────────────────────────────────────────────────

class Empreendimento(SQLModel, table=True):
    __tablename__ = "mapa_empreendimento"
    id: _Opt_mu[int] = Field(default=None, primary_key=True)
    company_id: int = Field(index=True)
    client_id: _Opt_mu[int] = Field(default=None, index=True)   # isolamento por cliente (padrão obras)
    estudo_id: _Opt_mu[int] = Field(default=None, index=True)  # FK EstudoViabilidade
    nome: str = Field(default="")
    dados_viabilidade_json: str = Field(default="{}")  # snapshot das premissas
    status: str = Field(default="ativo")               # ativo / encerrado
    criado_em: str = Field(default="")


class UnidadeEmpreendimento(SQLModel, table=True):
    __tablename__ = "mapa_unidade"
    id: _Opt_mu[int] = Field(default=None, primary_key=True)
    empreendimento_id: int = Field(index=True)
    tipologia_nome: str = Field(default="")
    numero: str = Field(default="")       # ex: "101", "AP-A-02"
    andar: int = Field(default=1)
    metragem: float = Field(default=0.0)
    valor_vgv_projetado: float = Field(default=0.0)
    permuta: bool = Field(default=False)
    status: str = Field(default="disponivel")  # disponivel / reservada / vendida / distrato


class VendaUnidade(SQLModel, table=True):
    __tablename__ = "mapa_venda"
    id: _Opt_mu[int] = Field(default=None, primary_key=True)
    unidade_id: int = Field(index=True)
    empreendimento_id: int = Field(index=True)
    comprador_nome: str = Field(default="")
    data_venda: str = Field(default="")
    valor_total: float = Field(default=0.0)
    forma_pagamento_json: str = Field(default="{}")  # entrada, parcelas, reforcos, chaves
    status: str = Field(default="ativa")              # ativa / distrato
    observacoes: str = Field(default="")
    criado_em: str = Field(default="")


for _mu_cls in (Empreendimento, UnidadeEmpreendimento, VendaUnidade):
    try:
        _mu_cls.__table__.create(engine, checkfirst=True)
    except Exception:
        pass

# Migração: adiciona client_id se a coluna não existir
try:
    with engine.connect() as _conn_mu:
        _conn_mu.exec_driver_sql("ALTER TABLE mapa_empreendimento ADD COLUMN client_id INTEGER")
        _conn_mu.commit()
except Exception:
    pass


# ── Helpers ───────────────────────────────────────────────────────────────────

def _brl_mu(v):
    try:
        return f"R$ {float(v):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except Exception:
        return "R$ 0,00"


def _gerar_unidades(emp: Empreendimento, tipologias: list) -> list[UnidadeEmpreendimento]:
    """Gera objetos UnidadeEmpreendimento a partir das tipologias do estudo."""
    unidades = []
    for tip in tipologias:
        nome_tip  = tip.get("nome") or "Sem nome"
        metragem  = float(tip.get("metragem", 0) or 0)
        qtd       = int(tip.get("quantidade", 0) or 0)
        preco_m2  = float(tip.get("preco_m2", 0) or 0)
        andar_ini = int(tip.get("andar_inicio", 1) or 1)
        permuta   = bool(tip.get("permuta", False))
        dif_andar = 0.005  # 0.5% por andar (padrão viabilidade)
        for u in range(qtd):
            andar   = andar_ini + u
            pm2_u   = preco_m2 * (1 + dif_andar * (andar - 1))
            vgv_u   = metragem * pm2_u
            numero  = f"{nome_tip}-{u+1:02d}"
            unidades.append(UnidadeEmpreendimento(
                empreendimento_id=emp.id,
                tipologia_nome=nome_tip,
                numero=numero,
                andar=andar,
                metragem=metragem,
                valor_vgv_projetado=round(vgv_u, 2),
                permuta=permuta,
                status="disponivel",
            ))
    return unidades


def _dashboard_emp(emp_id: int, session) -> dict:
    """Calcula indicadores de acompanhamento do empreendimento."""
    emp = session.get(Empreendimento, emp_id)
    if not emp:
        return {}
    unidades = session.exec(
        select(UnidadeEmpreendimento).where(UnidadeEmpreendimento.empreendimento_id == emp_id)
    ).all()
    vendas = session.exec(
        select(VendaUnidade).where(
            VendaUnidade.empreendimento_id == emp_id,
            VendaUnidade.status == "ativa",
        )
    ).all()

    total = len(unidades)
    permutadas = sum(1 for u in unidades if u.permuta)
    disponiveis = sum(1 for u in unidades if u.status == "disponivel" and not u.permuta)
    reservadas  = sum(1 for u in unidades if u.status == "reservada")
    vendidas    = sum(1 for u in unidades if u.status == "vendida")
    distratos   = sum(1 for u in unidades if u.status == "distrato")

    vgv_projetado = sum(u.valor_vgv_projetado for u in unidades if not u.permuta)
    vgv_realizado = sum(v.valor_total for v in vendas)

    # Para unidades não vendidas: usa valor projetado como estimativa futura
    nao_vendidas_vgv = sum(
        u.valor_vgv_projetado for u in unidades
        if u.status in ("disponivel", "reservada") and not u.permuta
    )
    vgv_reestimado = vgv_realizado + nao_vendidas_vgv

    vso = round(vendidas / max(total - permutadas, 1) * 100, 1)

    # Custo proporcional da viabilidade
    dv = _json_mu.loads(emp.dados_viabilidade_json or "{}")
    custo_total_proj = float(dv.get("custo_total", 0) or 0)
    vgv_proj_ref     = float(dv.get("vgv_liquido", 0) or 0) or vgv_projetado or 1
    margem_proj_pct  = float(dv.get("margem_vgv", 0) or 0)

    # Margem reestimada: mantém custo da viabilidade, atualiza VGV
    resultado_reest  = vgv_reestimado - custo_total_proj if custo_total_proj else None
    margem_reest     = round(resultado_reest / max(vgv_reestimado, 1) * 100, 1) if resultado_reest is not None else None

    return {
        "total": total,
        "permutadas": permutadas,
        "disponiveis": disponiveis,
        "reservadas": reservadas,
        "vendidas": vendidas,
        "distratos": distratos,
        "vgv_projetado": vgv_projetado,
        "vgv_realizado": vgv_realizado,
        "vgv_reestimado": vgv_reestimado,
        "vso": vso,
        "margem_proj_pct": margem_proj_pct,
        "custo_total_proj": custo_total_proj,
        "resultado_reest": resultado_reest,
        "margem_reest": margem_reest,
        "nome_projeto": dv.get("nome_projeto", emp.nome),
    }


# ── Rotas ────────────────────────────────────────────────────────────────────

@app.get("/ferramentas/mapa-unidades", response_class=HTMLResponse)
@require_login
async def mapa_unidades_list(
    request: Request, session: Session = Depends(get_session),
) -> HTMLResponse:
    ctx = get_tenant_context(request, session)
    if not ctx:
        request.session.clear()
        return RedirectResponse("/login", status_code=303)
    cc = get_client_or_none(session, ctx.company.id, get_active_client_id(request, session, ctx))
    if not cc:
        return RedirectResponse("/ferramentas", status_code=303)

    empreendimentos = session.exec(
        select(Empreendimento)
        .where(Empreendimento.company_id == ctx.company.id, Empreendimento.client_id == cc.id)
        .order_by(Empreendimento.id.desc())
    ).all()

    estudos = session.exec(
        select(EstudoViabilidade)
        .where(EstudoViabilidade.company_id == ctx.company.id)
        .order_by(EstudoViabilidade.id.desc())
    ).all()

    emps_data = []
    for emp in empreendimentos:
        dash = _dashboard_emp(emp.id, session)
        emps_data.append({"emp": emp, "dash": dash})

    return render("mapa_unidades_list.html", request=request, context={
        "current_user": ctx.user, "current_company": ctx.company,
        "role": ctx.membership.role, "current_client": cc,
        "emps_data": emps_data, "estudos": estudos,
    })


@app.post("/ferramentas/mapa-unidades/criar")
@require_login
async def mapa_unidades_criar(
    request: Request, session: Session = Depends(get_session),
):
    ctx = get_tenant_context(request, session)
    if not ctx:
        request.session.clear()
        return RedirectResponse("/login", status_code=303)
    cc = get_client_or_none(session, ctx.company.id, get_active_client_id(request, session, ctx))
    if not cc:
        return RedirectResponse("/ferramentas", status_code=303)
    form = await request.form()
    estudo_id = int(form.get("estudo_id", 0) or 0)

    estudo = session.get(EstudoViabilidade, estudo_id)
    if not estudo or estudo.company_id != ctx.company.id:
        return RedirectResponse("/ferramentas/mapa-unidades", status_code=303)

    dados_input = _json_mu.loads(estudo.dados_input_json or "{}")
    resultado_json = estudo.resultado_realista_json or "{}"
    resultado = _json_mu.loads(resultado_json) if resultado_json else {}

    # Snapshot das premissas relevantes para o dashboard
    snap = {
        "nome_projeto":   estudo.nome_projeto,
        "tipologias":     dados_input.get("tipologias", []),
        "vgv_liquido":    resultado.get("vgv_liquido", 0),
        "custo_total":    resultado.get("custo_total", 0),
        "margem_vgv":     resultado.get("margem_vgv", 0),
        "tir_anual":      resultado.get("tir_anual", 0),
        "vpl":            resultado.get("vpl", 0),
        "unidades_total": resultado.get("unidades_total", 0),
    }

    emp = Empreendimento(
        company_id=ctx.company.id,
        client_id=cc.id,
        estudo_id=estudo_id,
        nome=estudo.nome_projeto,
        dados_viabilidade_json=_json_mu.dumps(snap, default=str),
        status="ativo",
        criado_em=_dt_mu.now().strftime("%d/%m/%Y %H:%M"),
    )
    session.add(emp)
    session.commit()
    session.refresh(emp)

    tipologias = dados_input.get("tipologias", [])
    unidades = _gerar_unidades(emp, tipologias)
    for u in unidades:
        session.add(u)
    session.commit()

    return RedirectResponse(f"/ferramentas/mapa-unidades/{emp.id}", status_code=303)


@app.get("/ferramentas/mapa-unidades/{emp_id}", response_class=HTMLResponse)
@require_login
async def mapa_unidades_view(
    request: Request, emp_id: int, session: Session = Depends(get_session),
) -> HTMLResponse:
    ctx = get_tenant_context(request, session)
    if not ctx:
        request.session.clear()
        return RedirectResponse("/login", status_code=303)
    cc = get_client_or_none(session, ctx.company.id, get_active_client_id(request, session, ctx))
    if not cc:
        return RedirectResponse("/ferramentas", status_code=303)

    emp = session.get(Empreendimento, emp_id)
    if not emp or emp.company_id != ctx.company.id or emp.client_id != cc.id:
        return RedirectResponse("/ferramentas/mapa-unidades", status_code=303)

    unidades = session.exec(
        select(UnidadeEmpreendimento)
        .where(UnidadeEmpreendimento.empreendimento_id == emp_id)
        .order_by(UnidadeEmpreendimento.tipologia_nome, UnidadeEmpreendimento.andar)
    ).all()

    # Enriquecer unidades com dados de venda ativa
    venda_map: dict[int, VendaUnidade] = {}
    if unidades:
        vendas = session.exec(
            select(VendaUnidade).where(
                VendaUnidade.empreendimento_id == emp_id,
                VendaUnidade.status == "ativa",
            )
        ).all()
        for v in vendas:
            venda_map[v.unidade_id] = v

    # Agrupar por tipologia
    grupos: dict[str, list] = {}
    for u in unidades:
        grupos.setdefault(u.tipologia_nome, []).append(u)

    dash = _dashboard_emp(emp_id, session)
    dv = _json_mu.loads(emp.dados_viabilidade_json or "{}")

    return render("mapa_unidades_view.html", request=request, context={
        "current_user": ctx.user, "current_company": ctx.company,
        "role": ctx.membership.role, "current_client": cc,
        "emp": emp, "grupos": grupos, "dash": dash,
        "venda_map": venda_map, "dv": dv,
    })


@app.post("/ferramentas/mapa-unidades/{emp_id}/vender/{und_id}")
@require_login
async def mapa_unidades_vender(
    request: Request, emp_id: int, und_id: int,
    session: Session = Depends(get_session),
):
    ctx = get_tenant_context(request, session)
    if not ctx:
        request.session.clear()
        return RedirectResponse("/login", status_code=303)
    cc = get_client_or_none(session, ctx.company.id, get_active_client_id(request, session, ctx))
    if not cc:
        return RedirectResponse("/ferramentas", status_code=303)

    emp = session.get(Empreendimento, emp_id)
    if not emp or emp.company_id != ctx.company.id or emp.client_id != cc.id:
        return RedirectResponse("/ferramentas/mapa-unidades", status_code=303)

    unidade = session.get(UnidadeEmpreendimento, und_id)
    if not unidade or unidade.empreendimento_id != emp_id:
        return RedirectResponse(f"/ferramentas/mapa-unidades/{emp_id}", status_code=303)

    form = await request.form()
    comprador  = str(form.get("comprador_nome", "")).strip()
    data_venda = str(form.get("data_venda", "")).strip()
    valor_total = float(form.get("valor_total", 0) or 0)
    status_novo = str(form.get("status_unidade", "vendida"))
    observacoes = str(form.get("observacoes", "")).strip()

    # Forma de pagamento
    fp = {
        "entrada_pct":  float(form.get("entrada_pct", 0) or 0),
        "n_entrada":    int(form.get("n_entrada", 1) or 1),
        "parcelas_pct": float(form.get("parcelas_pct", 0) or 0),
        "n_parcelas":   int(form.get("n_parcelas", 0) or 0),
        "corr_parcelas": float(form.get("corr_parcelas", 0) or 0),
        "reforco_pct":  float(form.get("reforco_pct", 0) or 0),
        "n_reforcos":   int(form.get("n_reforcos", 0) or 0),
        "chaves_pct":   float(form.get("chaves_pct", 0) or 0),
    }

    # Cancela venda ativa anterior (se houver — caso de nova negociação)
    venda_ant = session.exec(
        select(VendaUnidade).where(
            VendaUnidade.unidade_id == und_id,
            VendaUnidade.status == "ativa",
        )
    ).first()
    if venda_ant:
        venda_ant.status = "distrato"
        session.add(venda_ant)

    venda = VendaUnidade(
        unidade_id=und_id,
        empreendimento_id=emp_id,
        comprador_nome=comprador,
        data_venda=data_venda,
        valor_total=valor_total,
        forma_pagamento_json=_json_mu.dumps(fp, default=str),
        status="ativa",
        observacoes=observacoes,
        criado_em=_dt_mu.now().strftime("%d/%m/%Y %H:%M"),
    )
    session.add(venda)

    unidade.status = status_novo
    session.add(unidade)
    session.commit()

    return RedirectResponse(f"/ferramentas/mapa-unidades/{emp_id}", status_code=303)


@app.post("/ferramentas/mapa-unidades/{emp_id}/distrato/{und_id}")
@require_login
async def mapa_unidades_distrato(
    request: Request, emp_id: int, und_id: int,
    session: Session = Depends(get_session),
):
    ctx = get_tenant_context(request, session)
    if not ctx:
        request.session.clear()
        return RedirectResponse("/login", status_code=303)
    cc = get_client_or_none(session, ctx.company.id, get_active_client_id(request, session, ctx))
    if not cc:
        return RedirectResponse("/ferramentas", status_code=303)

    emp = session.get(Empreendimento, emp_id)
    if not emp or emp.company_id != ctx.company.id or emp.client_id != cc.id:
        return RedirectResponse("/ferramentas/mapa-unidades", status_code=303)

    unidade = session.get(UnidadeEmpreendimento, und_id)
    if not unidade or unidade.empreendimento_id != emp_id:
        return RedirectResponse(f"/ferramentas/mapa-unidades/{emp_id}", status_code=303)

    venda = session.exec(
        select(VendaUnidade).where(
            VendaUnidade.unidade_id == und_id,
            VendaUnidade.status == "ativa",
        )
    ).first()
    if venda:
        venda.status = "distrato"
        session.add(venda)

    unidade.status = "distrato"
    session.add(unidade)
    session.commit()

    return RedirectResponse(f"/ferramentas/mapa-unidades/{emp_id}", status_code=303)


@app.post("/ferramentas/mapa-unidades/{emp_id}/reativar/{und_id}")
@require_login
async def mapa_unidades_reativar(
    request: Request, emp_id: int, und_id: int,
    session: Session = Depends(get_session),
):
    """Volta unidade em distrato para disponível."""
    ctx = get_tenant_context(request, session)
    if not ctx:
        request.session.clear()
        return RedirectResponse("/login", status_code=303)

    cc = get_client_or_none(session, ctx.company.id, get_active_client_id(request, session, ctx))
    emp = session.get(Empreendimento, emp_id)
    if not emp or emp.company_id != ctx.company.id or (cc and emp.client_id != cc.id):
        return RedirectResponse("/ferramentas/mapa-unidades", status_code=303)

    unidade = session.get(UnidadeEmpreendimento, und_id)
    if unidade and unidade.empreendimento_id == emp_id:
        unidade.status = "disponivel"
        session.add(unidade)
        session.commit()

    return RedirectResponse(f"/ferramentas/mapa-unidades/{emp_id}", status_code=303)


@app.delete("/ferramentas/mapa-unidades/{emp_id}")
@require_login
async def mapa_unidades_excluir(
    request: Request, emp_id: int, session: Session = Depends(get_session),
):
    ctx = get_tenant_context(request, session)
    if not ctx:
        return {"ok": False, "erro": "Não autenticado"}
    cc = get_client_or_none(session, ctx.company.id, get_active_client_id(request, session, ctx))

    emp = session.get(Empreendimento, emp_id)
    if not emp or emp.company_id != ctx.company.id or (cc and emp.client_id != cc.id):
        return {"ok": False, "erro": "Não encontrado"}

    unidades = session.exec(
        select(UnidadeEmpreendimento).where(UnidadeEmpreendimento.empreendimento_id == emp_id)
    ).all()
    for u in unidades:
        vendas = session.exec(
            select(VendaUnidade).where(VendaUnidade.unidade_id == u.id)
        ).all()
        for v in vendas:
            session.delete(v)
        session.delete(u)
    session.delete(emp)
    session.commit()
    return {"ok": True}


# ── Templates ────────────────────────────────────────────────────────────────

TEMPLATES["mapa_unidades_list.html"] = r"""
{% extends "base.html" %}
{% block content %}
<style>
  .mu-hdr{display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:1rem;margin-bottom:1.5rem;}
  .mu-card{background:#fff;border:1px solid #e2e8f0;border-radius:16px;padding:1.25rem 1.5rem;margin-bottom:1rem;display:flex;align-items:center;justify-content:space-between;gap:1rem;flex-wrap:wrap;transition:box-shadow .15s;}
  .mu-card:hover{box-shadow:0 4px 16px rgba(0,0,0,.08);}
  .mu-stat{text-align:center;padding:0 1rem;}
  .mu-stat-val{font-size:1.3rem;font-weight:800;color:#ea580c;}
  .mu-stat-lbl{font-size:.7rem;color:#64748b;text-transform:uppercase;letter-spacing:.05em;}
  .mu-badge{display:inline-block;padding:.2rem .65rem;border-radius:20px;font-size:.72rem;font-weight:700;}
  .mu-badge.ativo{background:#dcfce7;color:#166534;}
  .mu-badge.encerrado{background:#f1f5f9;color:#64748b;}
  .mu-empty{text-align:center;padding:4rem 2rem;color:#94a3b8;}
  .mu-modal-bg{display:none;position:fixed;inset:0;background:rgba(0,0,0,.45);z-index:1050;align-items:center;justify-content:center;}
  .mu-modal-bg.open{display:flex;}
  .mu-modal{background:#fff;border-radius:20px;padding:2rem;max-width:520px;width:90%;max-height:90vh;overflow-y:auto;box-shadow:0 20px 60px rgba(0,0,0,.2);}
  .mu-row2{display:grid;grid-template-columns:1fr 1fr;gap:.75rem;margin-bottom:.75rem;}
  .mu-lbl{font-size:.74rem;font-weight:700;text-transform:uppercase;letter-spacing:.05em;color:#64748b;margin-bottom:.25rem;}
  .mu-inp{width:100%;border:1.5px solid #e2e8f0;border-radius:10px;padding:.55rem .8rem;font-size:.88rem;outline:none;transition:border .15s;}
  .mu-inp:focus{border-color:#ea580c;}
</style>

<div class="mu-hdr">
  <div>
    <h2 style="font-size:1.4rem;font-weight:800;margin:0;">Mapa de Unidades</h2>
    <p style="color:#64748b;font-size:.85rem;margin:.25rem 0 0;">Cruzamento entre viabilidade projetada e comercialização realizada</p>
  </div>
  {% if estudos %}
  <button class="btn btn-primary" style="background:#ea580c;border:none;border-radius:12px;font-weight:700;" onclick="document.getElementById('modalCriar').classList.add('open')">
    <i class="bi bi-plus-circle me-1"></i>Novo Empreendimento
  </button>
  {% endif %}
</div>

{% if emps_data %}
  {% for item in emps_data %}
  {% set e = item.emp %}
  {% set d = item.dash %}
  <div class="mu-card">
    <div style="flex:1;min-width:180px;">
      <div style="font-weight:800;font-size:1rem;">{{ e.nome }}</div>
      <div style="font-size:.75rem;color:#64748b;margin-top:.2rem;">
        <i class="bi bi-calendar3 me-1"></i>{{ e.criado_em }}
        &nbsp;·&nbsp;
        <span class="mu-badge {{ e.status }}">{{ e.status|title }}</span>
      </div>
    </div>
    <div style="display:flex;gap:.5rem;flex-wrap:wrap;">
      <div class="mu-stat">
        <div class="mu-stat-val">{{ d.total }}</div>
        <div class="mu-stat-lbl">Total</div>
      </div>
      <div class="mu-stat">
        <div class="mu-stat-val" style="color:#16a34a;">{{ d.vendidas }}</div>
        <div class="mu-stat-lbl">Vendidas</div>
      </div>
      <div class="mu-stat">
        <div class="mu-stat-val" style="color:#ca8a04;">{{ d.reservadas }}</div>
        <div class="mu-stat-lbl">Reservadas</div>
      </div>
      <div class="mu-stat">
        <div class="mu-stat-val" style="color:#94a3b8;">{{ d.disponiveis }}</div>
        <div class="mu-stat-lbl">Disponíveis</div>
      </div>
      <div class="mu-stat">
        <div class="mu-stat-val">{{ d.vso }}%</div>
        <div class="mu-stat-lbl">VSO</div>
      </div>
    </div>
    <div style="display:flex;gap:.5rem;flex-shrink:0;">
      <a href="/ferramentas/mapa-unidades/{{ e.id }}" class="btn btn-sm" style="background:#ea580c;color:#fff;border:none;border-radius:10px;font-weight:700;">
        <i class="bi bi-grid-3x3-gap me-1"></i>Ver Mapa
      </a>
      <button onclick="excluirEmp({{ e.id }},'{{ e.nome|replace("'","") }}')" class="btn btn-sm btn-outline-danger" style="border-radius:10px;" title="Excluir">
        <i class="bi bi-trash3"></i>
      </button>
    </div>
  </div>
  {% endfor %}
{% else %}
  <div class="mu-empty">
    <i class="bi bi-buildings" style="font-size:3rem;display:block;margin-bottom:1rem;"></i>
    <p style="font-size:1rem;font-weight:600;">Nenhum empreendimento cadastrado ainda.</p>
    <p style="font-size:.85rem;">Crie um empreendimento a partir de um estudo de viabilidade salvo no Histórico.</p>
    {% if estudos %}
    <button class="btn btn-primary mt-2" style="background:#ea580c;border:none;border-radius:12px;font-weight:700;" onclick="document.getElementById('modalCriar').classList.add('open')">
      <i class="bi bi-plus-circle me-1"></i>Criar primeiro empreendimento
    </button>
    {% else %}
    <p class="mt-3" style="font-size:.82rem;color:#94a3b8;">Salve um estudo de viabilidade primeiro (use "Salvar &amp; Compartilhar" na ferramenta de Viabilidade).</p>
    {% endif %}
  </div>
{% endif %}

<!-- Modal: Criar empreendimento -->
<div class="mu-modal-bg" id="modalCriar" onclick="if(event.target===this)this.classList.remove('open')">
  <div class="mu-modal">
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:1.25rem;">
      <h5 style="font-weight:800;margin:0;color:#ea580c;"><i class="bi bi-building-add me-2"></i>Novo Empreendimento</h5>
      <button onclick="document.getElementById('modalCriar').classList.remove('open')" style="background:none;border:none;font-size:1.3rem;cursor:pointer;color:#94a3b8;">&times;</button>
    </div>
    <form method="post" action="/ferramentas/mapa-unidades/criar">
      <div class="mb-3">
        <div class="mu-lbl">Estudo de Viabilidade</div>
        <select name="estudo_id" class="mu-inp" required>
          <option value="">— Selecione um estudo salvo —</option>
          {% for est in estudos %}
          <option value="{{ est.id }}">{{ est.nome_projeto }} (salvo em {{ est.criado_em }})</option>
          {% endfor %}
        </select>
        <div style="font-size:.75rem;color:#94a3b8;margin-top:.4rem;">As tipologias e unidades serão importadas automaticamente.</div>
      </div>
      <button type="submit" class="btn w-100" style="background:#ea580c;color:#fff;border:none;border-radius:12px;font-weight:700;padding:.7rem;">
        <i class="bi bi-check-circle me-1"></i>Criar e gerar unidades
      </button>
    </form>
  </div>
</div>

<script>
async function excluirEmp(id, nome){
  if(!confirm(`Excluir "${nome}" e todas as suas unidades e vendas? Esta ação não pode ser desfeita.`))return;
  const resp = await fetch('/ferramentas/mapa-unidades/'+id,{method:'DELETE'});
  const data = await resp.json();
  if(data.ok) location.reload();
  else alert('Erro: '+(data.erro||'desconhecido'));
}
</script>
{% endblock %}
"""


TEMPLATES["mapa_unidades_view.html"] = r"""
{% extends "base.html" %}
{% block content %}
<style>
  .mu-hdr{display:flex;align-items:center;gap:1rem;margin-bottom:1.5rem;flex-wrap:wrap;}
  /* Dashboard */
  .mu-kpi-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:.75rem;margin-bottom:1.75rem;}
  .mu-kpi{background:#fff;border:1px solid #e2e8f0;border-radius:14px;padding:1rem 1.25rem;text-align:center;}
  .mu-kpi-val{font-size:1.15rem;font-weight:800;color:#ea580c;}
  .mu-kpi-lbl{font-size:.7rem;color:#64748b;text-transform:uppercase;letter-spacing:.05em;margin-top:.2rem;}
  .mu-prog-wrap{background:#f1f5f9;border-radius:8px;height:8px;margin-top:.5rem;overflow:hidden;}
  .mu-prog-bar{height:100%;border-radius:8px;background:#ea580c;transition:width .5s;}
  /* Mapa */
  .mu-grupo{margin-bottom:2rem;}
  .mu-grupo-hdr{font-size:.82rem;font-weight:700;text-transform:uppercase;letter-spacing:.06em;color:#64748b;margin-bottom:.75rem;padding-bottom:.4rem;border-bottom:2px solid #f1f5f9;}
  .mu-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(120px,1fr));gap:.6rem;}
  .mu-unit{border-radius:12px;padding:.75rem .6rem;text-align:center;cursor:pointer;transition:transform .1s,box-shadow .1s;position:relative;border:2px solid transparent;}
  .mu-unit:hover{transform:translateY(-2px);box-shadow:0 4px 12px rgba(0,0,0,.12);}
  .mu-unit.disponivel{background:#dcfce7;border-color:#86efac;color:#14532d;}
  .mu-unit.reservada{background:#fef9c3;border-color:#fde047;color:#713f12;}
  .mu-unit.vendida{background:#ffedd5;border-color:#fb923c;color:#7c2d12;}
  .mu-unit.distrato{background:#f1f5f9;border-color:#cbd5e1;color:#64748b;text-decoration:line-through;}
  .mu-unit.permuta{background:#ede9fe;border-color:#c4b5fd;color:#4c1d95;}
  .mu-unit-num{font-size:.78rem;font-weight:800;display:block;}
  .mu-unit-val{font-size:.65rem;opacity:.85;display:block;margin-top:.15rem;}
  .mu-unit-status{font-size:.6rem;font-weight:700;text-transform:uppercase;letter-spacing:.05em;display:block;margin-top:.2rem;opacity:.7;}
  /* Legenda */
  .mu-legend{display:flex;gap:1rem;flex-wrap:wrap;margin-bottom:1.25rem;}
  .mu-leg-dot{width:12px;height:12px;border-radius:50%;display:inline-block;margin-right:.3rem;}
  /* Modal */
  .mu-modal-bg{display:none;position:fixed;inset:0;background:rgba(0,0,0,.5);z-index:1050;align-items:center;justify-content:center;}
  .mu-modal-bg.open{display:flex;}
  .mu-modal{background:#fff;border-radius:20px;padding:2rem;max-width:540px;width:92%;max-height:92vh;overflow-y:auto;box-shadow:0 20px 60px rgba(0,0,0,.25);}
  .mu-row2{display:grid;grid-template-columns:1fr 1fr;gap:.75rem;margin-bottom:.75rem;}
  .mu-row3{display:grid;grid-template-columns:1fr 1fr 1fr;gap:.6rem;margin-bottom:.75rem;}
  .mu-lbl{font-size:.72rem;font-weight:700;text-transform:uppercase;letter-spacing:.05em;color:#64748b;margin-bottom:.2rem;}
  .mu-inp{width:100%;border:1.5px solid #e2e8f0;border-radius:10px;padding:.52rem .75rem;font-size:.86rem;outline:none;transition:border .15s;}
  .mu-inp:focus{border-color:#ea580c;}
  .mu-sec-hdr{font-size:.78rem;font-weight:800;text-transform:uppercase;letter-spacing:.06em;color:#ea580c;margin:.9rem 0 .5rem;padding-bottom:.3rem;border-bottom:1px solid #fed7aa;}
  /* Painel detalhes venda */
  .mu-venda-panel{background:#fff7ed;border:1px solid #fed7aa;border-radius:12px;padding:.9rem 1rem;margin-top:-.5rem;}
  .mu-venda-row{display:flex;justify-content:space-between;font-size:.8rem;padding:.2rem 0;border-bottom:1px solid #fde68a;}
  .mu-venda-row:last-child{border-bottom:none;font-weight:700;}
</style>

<div class="mu-hdr">
  <a href="/ferramentas/mapa-unidades" class="btn btn-sm btn-outline-secondary" style="border-radius:10px;">
    <i class="bi bi-arrow-left me-1"></i>Voltar
  </a>
  <div>
    <h2 style="font-size:1.3rem;font-weight:800;margin:0;">{{ emp.nome }}</h2>
    <div style="font-size:.78rem;color:#64748b;">Criado em {{ emp.criado_em }}</div>
  </div>
</div>

<!-- Dashboard KPIs -->
<div class="mu-kpi-grid">
  <div class="mu-kpi">
    <div class="mu-kpi-val">{{ dash.total }}</div>
    <div class="mu-kpi-lbl">Total de Unidades</div>
  </div>
  <div class="mu-kpi">
    <div class="mu-kpi-val" style="color:#16a34a;">{{ dash.vendidas }}</div>
    <div class="mu-kpi-lbl">Vendidas</div>
  </div>
  <div class="mu-kpi">
    <div class="mu-kpi-val" style="color:#ca8a04;">{{ dash.reservadas }}</div>
    <div class="mu-kpi-lbl">Reservadas</div>
  </div>
  <div class="mu-kpi">
    <div class="mu-kpi-val" style="color:#64748b;">{{ dash.disponiveis }}</div>
    <div class="mu-kpi-lbl">Disponíveis</div>
  </div>
  {% if dash.distratos %}
  <div class="mu-kpi">
    <div class="mu-kpi-val" style="color:#dc2626;">{{ dash.distratos }}</div>
    <div class="mu-kpi-lbl">Distratos</div>
  </div>
  {% endif %}
  <div class="mu-kpi">
    <div class="mu-kpi-val">{{ dash.vso }}%</div>
    <div class="mu-kpi-lbl">VSO</div>
    <div class="mu-prog-wrap"><div class="mu-prog-bar" style="width:{{ [dash.vso,100]|min }}%"></div></div>
  </div>
  <div class="mu-kpi">
    <div class="mu-kpi-val" style="font-size:.92rem;">{{ dash.vgv_realizado|brl }}</div>
    <div class="mu-kpi-lbl">VGV Realizado</div>
  </div>
  <div class="mu-kpi">
    <div class="mu-kpi-val" style="font-size:.92rem;color:#94a3b8;">{{ dash.vgv_projetado|brl }}</div>
    <div class="mu-kpi-lbl">VGV Projetado</div>
  </div>
  {% if dash.margem_reest is not none %}
  <div class="mu-kpi">
    <div class="mu-kpi-val" style="color:{% if dash.margem_reest >= 20 %}#16a34a{% elif dash.margem_reest >= 15 %}#ca8a04{% else %}#dc2626{% endif %};">
      {{ "%.1f"|format(dash.margem_reest) }}%
    </div>
    <div class="mu-kpi-lbl">Margem Reestimada</div>
  </div>
  {% endif %}
  {% if dash.margem_proj_pct %}
  <div class="mu-kpi">
    <div class="mu-kpi-val" style="font-size:.95rem;color:#94a3b8;">{{ "%.1f"|format(dash.margem_proj_pct) }}%</div>
    <div class="mu-kpi-lbl">Margem Projetada</div>
  </div>
  {% endif %}
</div>

<!-- Legenda -->
<div class="mu-legend">
  <span style="font-size:.78rem;color:#64748b;align-self:center;">Legenda:</span>
  <span style="font-size:.78rem;"><span class="mu-leg-dot" style="background:#86efac;"></span>Disponível</span>
  <span style="font-size:.78rem;"><span class="mu-leg-dot" style="background:#fde047;"></span>Reservada</span>
  <span style="font-size:.78rem;"><span class="mu-leg-dot" style="background:#fb923c;"></span>Vendida</span>
  <span style="font-size:.78rem;"><span class="mu-leg-dot" style="background:#c4b5fd;"></span>Permuta</span>
  <span style="font-size:.78rem;"><span class="mu-leg-dot" style="background:#cbd5e1;"></span>Distrato</span>
  <span style="margin-left:auto;font-size:.78rem;color:#64748b;">Clique em uma unidade para registrar venda ou ver detalhes</span>
</div>

<!-- Mapa por tipologia -->
{% for tip_nome, units in grupos.items() %}
<div class="mu-grupo">
  <div class="mu-grupo-hdr">
    {{ tip_nome }}
    <span style="font-weight:400;margin-left:.5rem;">{{ units|length }} unidade{{ 's' if units|length != 1 else '' }}</span>
  </div>
  <div class="mu-grid">
    {% for u in units %}
    {% set venda = venda_map.get(u.id) %}
    {% set css = 'permuta' if u.permuta else u.status %}
    <div class="mu-unit {{ css }}" onclick="abrirUnit({{ u.id }},'{{ u.numero|replace("'","") }}','{{ u.tipologia_nome|replace("'","") }}',{{ u.metragem }},{{ u.valor_vgv_projetado }},'{{ u.status }}',{{ 'true' if u.permuta else 'false' }})">
      <span class="mu-unit-num">{{ u.numero }}</span>
      <span class="mu-unit-val">{{ u.metragem }}m² · {{ u.valor_vgv_projetado|brl }}</span>
      {% if venda %}
      <span class="mu-unit-val" style="opacity:1;font-weight:700;">{{ venda.valor_total|brl }}</span>
      <span class="mu-unit-status">{{ venda.comprador_nome[:12] if venda.comprador_nome else u.status }}</span>
      {% else %}
      <span class="mu-unit-status">{{ 'permuta' if u.permuta else u.status }}</span>
      {% endif %}
    </div>
    {% endfor %}
  </div>
</div>
{% endfor %}

<!-- Modal de Unidade -->
<div class="mu-modal-bg" id="modalUnit" onclick="if(event.target===this)fecharModal()">
  <div class="mu-modal">
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:1.25rem;">
      <h5 style="font-weight:800;margin:0;color:#ea580c;" id="modalUnitTitulo">Unidade</h5>
      <button onclick="fecharModal()" style="background:none;border:none;font-size:1.3rem;cursor:pointer;color:#94a3b8;">&times;</button>
    </div>
    <div id="modalUnitBody"></div>
  </div>
</div>

<script>
let _currentUnitId = null;
let _currentStatus = null;
const empId = {{ emp.id }};

function fecharModal(){
  document.getElementById('modalUnit').classList.remove('open');
  _currentUnitId = null;
}

function abrirUnit(uid, numero, tipNome, metragem, vgvProj, status, permuta){
  _currentUnitId = uid;
  _currentStatus = status;
  const titulo = document.getElementById('modalUnitTitulo');
  titulo.textContent = `${numero} — ${tipNome}`;

  const body = document.getElementById('modalUnitBody');
  const brl = v => 'R$ ' + parseFloat(v||0).toLocaleString('pt-BR',{minimumFractionDigits:2,maximumFractionDigits:2});

  // Dados viabilidade
  let infoHtml = `
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:.5rem;margin-bottom:1rem;font-size:.82rem;">
      <div><span style="color:#64748b;">Área:</span> <strong>${metragem}m²</strong></div>
      <div><span style="color:#64748b;">VGV Projetado:</span> <strong>${brl(vgvProj)}</strong></div>
      <div><span style="color:#64748b;">Status:</span> <strong>${status}</strong></div>
      ${permuta ? '<div><span style="color:#7c3aed;font-weight:700;">Unidade de Permuta</span></div>' : ''}
    </div>
  `;

  // Ações disponíveis
  let acoesHtml = '';
  if(permuta){
    acoesHtml = '<p style="color:#7c3aed;font-size:.85rem;text-align:center;padding:1rem;">Unidade de permuta — não disponível para venda.</p>';
  } else if(status === 'disponivel' || status === 'reservada'){
    acoesHtml = formVenda(uid, vgvProj);
  } else if(status === 'vendida'){
    acoesHtml = `
      ${vendaInfo()}
      <div style="display:flex;gap:.5rem;margin-top:1rem;">
        <button onclick="novaVenda(${uid},${vgvProj})" class="btn btn-sm btn-outline-secondary" style="flex:1;border-radius:10px;">
          <i class="bi bi-arrow-repeat me-1"></i>Renegociar
        </button>
        <form method="post" action="/ferramentas/mapa-unidades/${empId}/distrato/${uid}" style="flex:1;">
          <button type="submit" class="btn btn-sm btn-outline-danger w-100" style="border-radius:10px;"
            onclick="return confirm('Confirmar distrato desta unidade?')">
            <i class="bi bi-x-circle me-1"></i>Registrar Distrato
          </button>
        </form>
      </div>
    `;
  } else if(status === 'distrato'){
    acoesHtml = `
      <p style="color:#dc2626;font-size:.85rem;margin-bottom:1rem;"><i class="bi bi-x-circle me-1"></i>Unidade com distrato registrado.</p>
      <div style="display:flex;gap:.5rem;">
        <form method="post" action="/ferramentas/mapa-unidades/${empId}/reativar/${uid}" style="flex:1;">
          <button type="submit" class="btn btn-sm btn-outline-success w-100" style="border-radius:10px;">
            <i class="bi bi-arrow-counterclockwise me-1"></i>Reativar (Disponível)
          </button>
        </form>
        ${formVendaCollapsed(uid, vgvProj)}
      </div>
    `;
  }

  body.innerHTML = infoHtml + acoesHtml;
  document.getElementById('modalUnit').classList.add('open');
}

function vendaInfo(){
  // Carregamos via fetch lazy quando abrimos unidade vendida
  return `<div id="vendaDetalhes" style="font-size:.83rem;color:#64748b;text-align:center;padding:.5rem;">
    <i class="bi bi-hourglass-split"></i> Carregando dados da venda...
  </div>`;
  // A função abaixo é chamada após renderização
}

function novaVenda(uid, vgvProj){
  const body = document.getElementById('modalUnitBody');
  const infoEl = body.querySelector('[data-vinfo]');
  const formEl = document.getElementById('formVenda_'+uid);
  if(formEl){ formEl.style.display='block'; return; }
  const extra = document.createElement('div');
  extra.innerHTML = formVenda(uid, vgvProj);
  body.appendChild(extra);
}

function formVenda(uid, vgvProj){
  const brl = v => parseFloat(v||0).toLocaleString('pt-BR',{minimumFractionDigits:2});
  return `
<form id="formVenda_${uid}" method="post" action="/ferramentas/mapa-unidades/${empId}/vender/${uid}">
  <div class="mu-sec-hdr"><i class="bi bi-person-fill-check me-1"></i>Registrar Venda / Reserva</div>
  <div class="mu-row2">
    <div>
      <div class="mu-lbl">Comprador</div>
      <input class="mu-inp" name="comprador_nome" placeholder="Nome do comprador" required>
    </div>
    <div>
      <div class="mu-lbl">Data da Venda</div>
      <input class="mu-inp" type="date" name="data_venda">
    </div>
  </div>
  <div class="mu-row2">
    <div>
      <div class="mu-lbl">Valor Total Negociado (R$)</div>
      <input class="mu-inp" type="number" step="0.01" name="valor_total" value="${vgvProj}" required>
    </div>
    <div>
      <div class="mu-lbl">Status</div>
      <select class="mu-inp" name="status_unidade">
        <option value="vendida">Vendida</option>
        <option value="reservada">Reservada</option>
      </select>
    </div>
  </div>

  <div class="mu-sec-hdr"><i class="bi bi-cash-stack me-1"></i>Forma de Pagamento</div>
  <div class="mu-row3">
    <div>
      <div class="mu-lbl">Entrada (%)</div>
      <input class="mu-inp" type="number" step="0.01" name="entrada_pct" placeholder="10">
    </div>
    <div>
      <div class="mu-lbl">N° Parcelas Entrada</div>
      <input class="mu-inp" type="number" name="n_entrada" placeholder="1" value="1">
    </div>
    <div></div>
  </div>
  <div class="mu-row3">
    <div>
      <div class="mu-lbl">Parcelas Mensais (%)</div>
      <input class="mu-inp" type="number" step="0.01" name="parcelas_pct" placeholder="70">
    </div>
    <div>
      <div class="mu-lbl">N° Parcelas</div>
      <input class="mu-inp" type="number" name="n_parcelas" placeholder="36">
    </div>
    <div>
      <div class="mu-lbl">Correção (%a.m.)</div>
      <input class="mu-inp" type="number" step="0.001" name="corr_parcelas" placeholder="0.52">
    </div>
  </div>
  <div class="mu-row3">
    <div>
      <div class="mu-lbl">Reforços (%)</div>
      <input class="mu-inp" type="number" step="0.01" name="reforco_pct" placeholder="0">
    </div>
    <div>
      <div class="mu-lbl">N° Reforços</div>
      <input class="mu-inp" type="number" name="n_reforcos" placeholder="0" value="0">
    </div>
    <div>
      <div class="mu-lbl">Chaves (%)</div>
      <input class="mu-inp" type="number" step="0.01" name="chaves_pct" placeholder="20">
    </div>
  </div>

  <div class="mb-3">
    <div class="mu-lbl">Observações</div>
    <textarea class="mu-inp" name="observacoes" rows="2" placeholder="Notas opcionais sobre a negociação"></textarea>
  </div>

  <button type="submit" class="btn w-100" style="background:#ea580c;color:#fff;border:none;border-radius:12px;font-weight:700;padding:.7rem;">
    <i class="bi bi-check-circle me-1"></i>Confirmar Venda
  </button>
</form>`;
}

function formVendaCollapsed(uid, vgvProj){
  return `<button type="button" onclick="novaVenda(${uid},${vgvProj})" class="btn btn-sm btn-outline-primary" style="flex:1;border-radius:10px;">
    <i class="bi bi-person-fill-check me-1"></i>Nova Venda
  </button>`;
}

// Após modal abrir, carregar detalhes da venda se vendida
document.addEventListener('DOMContentLoaded', ()=>{});
</script>

{% endblock %}
"""

# ============================================================================
# ui_bsc_cliente_v2.py — Template BSC do cliente refeito
# ============================================================================
# Substitui cliente_bsc.html com:
#   - Hero com score em anel circular
#   - Cards de perspectiva com header colorido
#   - Barras de progresso por indicador
#   - Sparklines de histórico
#   - Seção de ações corretivas abertas
# ============================================================================

TEMPLATES["cliente_bsc.html"] = r"""
{% extends "base.html" %}
{% block content %}
<style>
/* ── Hero score ─────────────────────────────────────────────────────────── */
.bsc-hero {
  border-radius: 20px;
  background: linear-gradient(135deg, #0B1E1E 0%, #1a3a3a 100%);
  color: #fff; padding: 28px 32px; margin-bottom: 24px;
  display: flex; align-items: center; gap: 32px; flex-wrap: wrap;
}
.bsc-hero-title { font-size: 1.1rem; font-weight: 700; opacity: .55; letter-spacing: .04em; text-transform: uppercase; }
.bsc-hero-name  { font-size: 1.6rem; font-weight: 800; line-height: 1.2; }
.bsc-hero-sub   { font-size: .8rem; opacity: .5; margin-top: 4px; }

/* Score ring */
.bsc-ring-wrap { position: relative; width: 110px; height: 110px; flex-shrink: 0; }
.bsc-ring-wrap svg { transform: rotate(-90deg); }
.bsc-ring-bg  { fill: none; stroke: rgba(255,255,255,.1); stroke-width: 8; }
.bsc-ring-val { fill: none; stroke-width: 8; stroke-linecap: round; transition: stroke-dashoffset .8s ease; }
.bsc-ring-label {
  position: absolute; inset: 0; display: flex; flex-direction: column;
  align-items: center; justify-content: center;
}
.bsc-ring-pct  { font-size: 1.4rem; font-weight: 800; line-height: 1; }
.bsc-ring-txt  { font-size: .6rem; opacity: .5; text-transform: uppercase; letter-spacing: .05em; }

/* ── Perspectiva cards ──────────────────────────────────────────────────── */
.bsc-card { border-radius: 14px; overflow: hidden; border: 1px solid rgba(0,0,0,.07); }
.bsc-card-header { padding: 13px 16px; color: #fff; }
.bsc-card-header .bsc-ph-title { font-weight: 700; font-size: .95rem; }
.bsc-card-header .bsc-ph-sub   { font-size: .72rem; opacity: .75; margin-top: 2px; }
.bsc-card-body { padding: 12px 14px; background: #fff; }

/* ── KPI row ────────────────────────────────────────────────────────────── */
.kpi-row { padding: 8px 0; border-bottom: 1px solid #f1f5f9; }
.kpi-row:last-child { border-bottom: none; }
.kpi-dot { width: 9px; height: 9px; border-radius: 50%; flex-shrink: 0; }
.kpi-name { font-size: .83rem; flex-grow: 1; }
.kpi-val  { font-size: .83rem; font-weight: 600; font-variant-numeric: tabular-nums; }
.kpi-meta { font-size: .72rem; color: #9ca3af; }
.prog-track { height: 5px; border-radius: 3px; background: #f1f5f9; overflow: hidden; margin-top: 5px; margin-left: 17px; }
.prog-fill  { height: 100%; border-radius: 3px; transition: width .5s ease; }

/* sparkline */
.spark { display: inline-flex; align-items: flex-end; gap: 2px; height: 20px; margin-left: 17px; margin-top: 3px; }
.spark-b { width: 5px; border-radius: 2px 2px 0 0; }

/* ── Objetivo heading ───────────────────────────────────────────────────── */
.obj-title {
  font-size: .72rem; font-weight: 700; text-transform: uppercase;
  letter-spacing: .06em; color: #6b7280; padding: 6px 0 2px;
  border-bottom: 1px dashed #e5e7eb; margin-bottom: 4px;
}

/* ── Ações section ──────────────────────────────────────────────────────── */
.acao-item { padding: 8px 12px; border-radius: 10px; background: #fef9f5; border: 1px solid #fed7aa; margin-bottom: 8px; }
.acao-item .acao-titulo { font-size: .85rem; font-weight: 600; }
.acao-item .acao-meta   { font-size: .72rem; color: #9ca3af; }
.badge-prio-alta   { background: #fee2e2; color: #dc2626; }
.badge-prio-media  { background: #fef3c7; color: #d97706; }
.badge-prio-baixa  { background: #dcfce7; color: #16a34a; }

/* empty state */
.bsc-empty { text-align: center; padding: 48px 24px; color: #9ca3af; }
.bsc-empty-icon { font-size: 3rem; margin-bottom: 12px; }
</style>

{% if not painel %}
<div class="bsc-empty">
  <div class="bsc-empty-icon">🎯</div>
  <div class="fw-semibold mb-1">Planejamento estratégico não iniciado</div>
  <div class="small mb-3">Crie seu BSC agora com as 4 perspectivas padrão e comece a monitorar seus indicadores.</div>
  <form method="post" action="/cliente/bsc/seed">
    <button type="submit" class="btn btn-primary">Criar meu planejamento</button>
  </form>
</div>
{% else %}

<!-- ── Hero ──────────────────────────────────────────────────────────────── -->
{% set total_inds = painel|map(attribute='objetivos')|sum(start=[])|map(attribute='indicadores')|sum(start=[])|list|length %}
{% set score_val  = score if score is not none else 0 %}
{% set ring_color = '#4ade80' if score_val >= 80 else ('#fbbf24' if score_val >= 60 else '#f87171') %}
{% set circum = 283 %}
{% set dash   = (score_val / 100 * circum)|round(1) %}

<div class="bsc-hero">
  <div class="flex-grow-1">
    <div class="bsc-hero-title">Planejamento Estratégico</div>
    <div class="bsc-hero-name">{{ cliente.name if cliente else "Minha Empresa" }}</div>
    <div class="bsc-hero-sub">{{ total_inds }} indicador(es) monitorado(s)</div>
  </div>

  {% if score is not none %}
  <div class="bsc-ring-wrap">
    <svg width="110" height="110" viewBox="0 0 100 100">
      <circle class="bsc-ring-bg" cx="50" cy="50" r="45"/>
      <circle class="bsc-ring-val"
              cx="50" cy="50" r="45"
              stroke="{{ ring_color }}"
              stroke-dasharray="{{ circum }}"
              stroke-dashoffset="{{ (circum - dash)|round(1) }}"/>
    </svg>
    <div class="bsc-ring-label">
      <span class="bsc-ring-pct" style="color:{{ ring_color }}">{{ score_val|int }}%</span>
      <span class="bsc-ring-txt">score</span>
    </div>
  </div>
  {% endif %}
</div>

<!-- ── Perspectivas ───────────────────────────────────────────────────────── -->
<div class="row g-3 mb-4">
  {% for bloco in painel %}{% set p = bloco.perspectiva %}
  <div class="col-md-6">
    <div class="card bsc-card h-100">
      <div class="bsc-card-header" style="background:{{ p.cor }};">
        <div class="bsc-ph-title">{{ p.icone }} {{ p.nome }}</div>
        <div class="bsc-ph-sub">{{ bloco.objetivos|length }} objetivo(s)</div>
      </div>
      <div class="bsc-card-body">
        {% if not bloco.objetivos %}
          <div class="muted small py-2">Nenhum objetivo configurado.</div>
        {% endif %}
        {% for ob in bloco.objetivos %}
        <div class="obj-title d-flex justify-content-between align-items-center">
          <span>{{ ob.obj.titulo }}</span>
          <button class="btn btn-link btn-sm p-0 text-muted" style="font-size:.75rem"
            onclick="bscToggleForm('ind-form-{{ ob.obj.id }}')">+ Indicador</button>
        </div>
        <div id="ind-form-{{ ob.obj.id }}" style="display:none;margin-bottom:.5rem;">
          <form method="post" action="/ferramentas/bsc/{{ cliente.id }}/indicador" class="d-flex flex-wrap gap-1 mt-1">
            <input type="hidden" name="objetivo_id" value="{{ ob.obj.id }}">
            <input name="nome" placeholder="Nome do indicador" class="form-control form-control-sm" style="min-width:120px;flex:1" required>
            <input name="unidade" placeholder="Unidade" class="form-control form-control-sm" style="width:70px">
            <input name="meta_valor" placeholder="Meta" type="number" step="any" class="form-control form-control-sm" style="width:70px" required>
            <button type="submit" class="btn btn-sm btn-primary">Salvar</button>
          </form>
        </div>
        {% for ii in ob.indicadores %}
        <div class="kpi-row">
          <div class="d-flex align-items-center gap-2">
            <span class="kpi-dot" style="background:{{ ii.cor }};"></span>
            <span class="kpi-name">{{ ii.ind.nome }}</span>
            {% if ii.realizado is not none %}
              <span class="kpi-val" style="color:{{ ii.cor }}">{{ ii.realizado|round(1) }}</span>
              <span class="kpi-meta">/ {{ ii.ind.meta_valor|round(1) }} {{ ii.ind.unidade }}</span>
            {% else %}
              <span class="kpi-meta">— sem dados</span>
            {% endif %}
            <button class="btn btn-link btn-sm p-0 ms-auto text-muted" style="font-size:.7rem"
              onclick="bscToggleForm('lanc-{{ ii.ind.id }}')">+ Valor</button>
          </div>
          <div id="lanc-{{ ii.ind.id }}" style="display:none;margin-top:.25rem;">
            <form method="post" action="/api/bsc/lancamento" class="d-flex gap-1">
              <input type="hidden" name="indicador_id" value="{{ ii.ind.id }}">
              <input name="periodo" type="month" class="form-control form-control-sm" style="width:130px" required>
              <input name="valor" type="number" step="any" placeholder="Valor" class="form-control form-control-sm" style="width:90px" required>
              <button type="submit" class="btn btn-sm btn-success">OK</button>
            </form>
          </div>
          {% if ii.realizado is not none %}
          <div class="prog-track">
            <div class="prog-fill" style="width:{{ [ii.pct,100]|min }}%;background:{{ ii.cor }};"></div>
          </div>
          {% endif %}
          {% if ii.historico is defined and ii.historico %}
          <div class="spark">
            {% set max_v = ii.historico|map(attribute='valor')|max %}
            {% for h in ii.historico %}
            <div class="spark-b" title="{{ h.periodo }}: {{ h.valor }}"
                 style="height:{{ ((h.valor / max_v * 18)|int if max_v > 0 else 3) }}px;background:{{ ii.cor }};opacity:.6;"></div>
            {% endfor %}
          </div>
          {% endif %}
        </div>
        {% endfor %}
        {% endfor %}
        <!-- Novo objetivo -->
        <div class="mt-2 pt-2 border-top">
          <button class="btn btn-link btn-sm p-0 text-muted" style="font-size:.75rem"
            onclick="bscToggleForm('obj-form-{{ p.id }}')">+ Objetivo</button>
          <div id="obj-form-{{ p.id }}" style="display:none;margin-top:.4rem;">
            <form method="post" action="/ferramentas/bsc/{{ cliente.id }}/objetivo" class="d-flex gap-1">
              <input type="hidden" name="perspectiva_id" value="{{ p.id }}">
              <input name="titulo" placeholder="Título do objetivo" class="form-control form-control-sm" style="flex:1" required>
              <button type="submit" class="btn btn-sm btn-primary">Salvar</button>
            </form>
          </div>
        </div>
      </div>
    </div>
  </div>
  {% endfor %}
</div>

<!-- ── Ações corretivas ───────────────────────────────────────────────────── -->
{% if acoes_abertas is defined and acoes_abertas %}
<div class="mb-4">
  <h6 class="fw-bold mb-3">⚡ Ações Corretivas em Aberto</h6>
  {% for a in acoes_abertas %}
  <div class="acao-item">
    <div class="d-flex align-items-start gap-2 justify-content-between">
      <div>
        <div class="acao-titulo">{{ a.titulo }}</div>
        <div class="acao-meta">
          {% if a.responsavel %}Responsável: {{ a.responsavel }} · {% endif %}
          Prazo: {{ a.prazo_previsto or "—" }}
        </div>
      </div>
      <span class="badge rounded-pill
        {% if a.prioridade == 'alta' %}badge-prio-alta
        {% elif a.prioridade == 'media' %}badge-prio-media
        {% else %}badge-prio-baixa{% endif %}">
        {{ a.prioridade or "—" }}
      </span>
    </div>
  </div>
  {% endfor %}
</div>
{% endif %}

{% endif %}
<script>
function bscToggleForm(id) {
  var el = document.getElementById(id);
  if (el) el.style.display = el.style.display === 'none' ? 'block' : 'none';
}
</script>
{% endblock %}
"""

# Propaga ao Jinja2 loader
if hasattr(templates_env.loader, "mapping"):
    templates_env.loader.mapping["cliente_bsc.html"] = TEMPLATES["cliente_bsc.html"]
    print("[bsc_cliente_v2] ✅ cliente_bsc.html propagado ao loader.")

# ── Enriquecer rota /cliente/bsc com ações abertas ──────────────────────────
# Faz patch na rota para também passar acoes_abertas ao contexto

import re as _re_bscv2

try:
    from fastapi.responses import HTMLResponse as _HTML_bscv2
    from fastapi import Request as _Req_bscv2, Depends as _Dep_bscv2
    from sqlmodel import Session as _Sess_bscv2, select as _sel_bscv2

    # Remove rota atual
    app.routes[:] = [r for r in app.routes if not (hasattr(r, "path") and r.path == "/cliente/bsc")]

    @app.get("/cliente/bsc", response_class=_HTML_bscv2)
    @require_login
    async def cliente_bsc_v2(request: _Req_bscv2, session: _Sess_bscv2 = _Dep_bscv2(get_session)):
        from fastapi.responses import RedirectResponse as _RR
        ctx = get_tenant_context(request, session)
        if not ctx:
            return _RR("/login", status_code=303)

        client_id = None
        try:
            client_id = get_active_client_id(request, session, ctx)
            if not client_id and ctx.membership.role == "cliente":
                cl = session.exec(
                    _sel_bscv2(Client).where(
                        Client.company_id == ctx.company.id,
                        Client.user_id == ctx.user.id,
                    )
                ).first()
                if cl:
                    client_id = cl.id
        except Exception:
            pass

        if client_id:
            return _RR(f"/ferramentas/bsc/{client_id}", status_code=303)
        # fallback: no client_id found
        client_id = None  # reset for legacy path below

        base_ctx = {
            "current_user": ctx.user,
            "current_company": ctx.company,
            "role": ctx.membership.role,
            "current_client": None,
        }

        if not client_id:
            return render("cliente_bsc.html", request=request, context={
                **base_ctx, "painel": [], "score": None, "cliente": None,
            })

        cliente = session.get(Client, client_id)
        perspectivas = session.exec(
            _sel_bscv2(BSCPerspectiva)
            .where(BSCPerspectiva.company_id == ctx.company.id, BSCPerspectiva.client_id == client_id)
            .order_by(BSCPerspectiva.ordem)
        ).all()

        painel = []
        for p in perspectivas:
            objetivos = session.exec(_sel_bscv2(BSCObjetivo).where(BSCObjetivo.perspectiva_id == p.id)).all()
            obj_list = []
            for obj in objetivos:
                indicadores = session.exec(_sel_bscv2(BSCIndicador).where(BSCIndicador.objetivo_id == obj.id)).all()
                ind_list = []
                for ind in indicadores:
                    ult = _bsc_ultimo_lancamento(session, ind.id)
                    realizado = ult.valor if ult else None
                    sem = _bsc_semaforo(realizado or 0, ind.meta_valor, ind.polaridade,
                                        ind.tol_amarelo, ind.tol_vermelho) if realizado is not None else "cinza"
                    pct = _bsc_pct(realizado or 0, ind.meta_valor, ind.polaridade) if realizado is not None else 0
                    # Histórico (últimos 6 lançamentos)
                    historico = []
                    try:
                        hist_rows = session.exec(
                            _sel_bscv2(BSCLancamento)
                            .where(BSCLancamento.indicador_id == ind.id)
                            .order_by(BSCLancamento.periodo.desc())
                            .limit(6)
                        ).all()
                        historico = list(reversed(hist_rows))
                    except Exception:
                        pass
                    ind_list.append({
                        "ind": ind, "realizado": realizado,
                        "semaforo": sem, "cor": _bsc_cor_semaforo(sem),
                        "pct": pct, "historico": historico,
                    })
                obj_list.append({"obj": obj, "indicadores": ind_list})
            painel.append({"perspectiva": p, "objetivos": obj_list})

        score = _bsc_score_cliente(session, ctx.company.id, client_id)

        # Ações corretivas abertas do cliente
        acoes_abertas = []
        try:
            acoes_abertas = session.exec(
                _sel_bscv2(MeetingAcao)
                .where(
                    MeetingAcao.company_id == ctx.company.id,
                    MeetingAcao.client_id == client_id,
                    MeetingAcao.status.in_(["aberta", "em_andamento"]),
                )
                .order_by(MeetingAcao.prazo_previsto)
                .limit(10)
            ).all()
        except Exception:
            pass

        cc = get_client_or_none(session, ctx.company.id, client_id)
        return render("cliente_bsc.html", request=request, context={
            **base_ctx,
            "current_client": cc,
            "cliente": cliente,
            "painel": painel,
            "score": score,
            "acoes_abertas": acoes_abertas,
        })

    print("[bsc_cliente_v2] ✅ Rota /cliente/bsc v2 registrada com ações.")

    # ── Rota seed para o próprio cliente ────────────────────────────────────
    from fastapi.responses import RedirectResponse as _RR_seed
    from fastapi import Form as _Form_seed

    @app.post("/cliente/bsc/seed")
    @require_login
    async def cliente_bsc_seed(request: _Req_bscv2, session: _Sess_bscv2 = _Dep_bscv2(get_session)):
        ctx = get_tenant_context(request, session)
        if not ctx:
            return _RR_seed("/login", status_code=303)

        client_id = None
        try:
            client_id = get_active_client_id(request, session, ctx)
            if not client_id and ctx.membership.role == "cliente":
                cl = session.exec(
                    _sel_bscv2(Client).where(
                        Client.company_id == ctx.company.id,
                        Client.user_id == ctx.user.id,
                    )
                ).first()
                if cl:
                    client_id = cl.id
        except Exception:
            pass

        if not client_id:
            return _RR_seed("/cliente/bsc", status_code=303)

        # Cria perspectivas padrão se ainda não existirem
        existentes = session.exec(
            _sel_bscv2(BSCPerspectiva).where(
                BSCPerspectiva.company_id == ctx.company.id,
                BSCPerspectiva.client_id == client_id,
            )
        ).all()
        if not existentes:
            PERSPECTIVAS_PADRAO = [
                {"nome": "Financeiro",         "icone": "💰", "cor": "#22c55e", "ordem": 1},
                {"nome": "Clientes",           "icone": "🤝", "cor": "#3b82f6", "ordem": 2},
                {"nome": "Processos Internos", "icone": "⚙️",  "cor": "#f59e0b", "ordem": 3},
                {"nome": "Aprendizado & Crescimento", "icone": "🌱", "cor": "#8b5cf6", "ordem": 4},
            ]
            for p in PERSPECTIVAS_PADRAO:
                session.add(BSCPerspectiva(
                    company_id=ctx.company.id, client_id=client_id,
                    nome=p["nome"], icone=p["icone"], cor=p["cor"], ordem=p["ordem"],
                ))
            session.commit()

        return _RR_seed(f"/ferramentas/bsc/{client_id}", status_code=303)

except Exception as _e_bscv2:
    print(f"[bsc_cliente_v2] ⚠️ Erro ao registrar rota: {_e_bscv2}")

print("[bsc_cliente_v2] ✅ Módulo BSC cliente v2 carregado.")

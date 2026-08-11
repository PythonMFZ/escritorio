# ============================================================================
# ui_orcamento_v2.py — Melhorias na ferramenta de Orçamento
# ============================================================================
# Adiciona:
#   1. BudgetAlert — metas de tolerância de desvio por conta
#   2. Dashboard de desvios com semáforo (verde/amarelo/vermelho)
#   3. Visão executiva do cliente (resumo simplificado, não planilha bruta)
#   4. Gráfico de evolução mensal orçado vs realizado (barras)
#   5. Botão de conexão com reuniões: abrir ação corretiva a partir de desvio
#
# Rotas novas:
#   GET  /ferramentas/orcamento/{plan_id}/dashboard   → painel de desvios
#   GET  /cliente/orcamento                           → visão executiva cliente
#   POST /api/orcamento/conta/{acc_id}/meta           → definir tolerância %
#   POST /api/orcamento/{plan_id}/acao-reuniao        → criar MeetingAcao do desvio
# ============================================================================

import json as _json_orc2
from datetime import datetime as _dt_orc2

from fastapi import Form as _Form_orc2
from fastapi.responses import HTMLResponse as _HTML_orc2, RedirectResponse as _RR_orc2, JSONResponse as _JSON_orc2
from sqlmodel import Field as _Field_orc2, select as _sel_orc2, SQLModel as _SQL_orc2


# ── Novo modelo: tolerância de desvio por conta ───────────────────────────────

class BudgetAlert(_SQL_orc2, table=True):
    """Tolerância de desvio % por conta do orçamento."""
    __tablename__ = "budgetalert"
    id: int | None = _Field_orc2(default=None, primary_key=True)
    company_id: int = _Field_orc2(index=True)
    account_id: int = _Field_orc2(index=True, foreign_key="budgetaccount.id")
    tolerance_pct: float = _Field_orc2(default=10.0)  # desvio % que aciona amarelo
    critical_pct: float  = _Field_orc2(default=20.0)  # desvio % que aciona vermelho
    updated_at: _dt_orc2 = _Field_orc2(default_factory=utcnow)


try:
    BudgetAlert.__table__.create(engine, checkfirst=True)
    print("[orcamento_v2] ✅ Tabela BudgetAlert garantida.")
except Exception as _e_orc2:
    print(f"[orcamento_v2] ⚠️ BudgetAlert: {_e_orc2}")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _orc2_semaforo(desvio_pct: float, tol: float, crit: float) -> str:
    """Retorna 'verde', 'amarelo' ou 'vermelho' baseado no desvio."""
    a = abs(desvio_pct)
    if a >= crit:
        return "vermelho"
    if a >= tol:
        return "amarelo"
    return "verde"


def _orc2_load_dashboard(session, company_id: int, plan_id: int, client_id):
    """Carrega dados de desvio por conta, enriquecidos com semáforo."""
    rows = _load_grid(session, company_id, plan_id, client_id)
    if not rows:
        return []

    # Carrega alertas configurados
    alerts_raw = session.exec(
        _sel_orc2(BudgetAlert).where(BudgetAlert.company_id == company_id)
    ).all()
    alert_by_acc = {a.account_id: a for a in alerts_raw}

    result = []
    for row in rows:
        tb = row["total_b"]
        tr = row["total_r"]
        if tb == 0 and tr == 0:
            continue
        desvio_abs = tr - tb
        desvio_pct = ((tr - tb) / abs(tb) * 100) if tb else 0.0

        al = alert_by_acc.get(row["id"])
        tol = al.tolerance_pct if al else 10.0
        crit = al.critical_pct if al else 20.0
        semaforo = _orc2_semaforo(desvio_pct, tol, crit) if tb != 0 else "cinza"

        # Dados mensais para gráfico
        meses_b = [row["months"][m]["b"] for m in range(1, 13)]
        meses_r = [row["months"][m]["r"] for m in range(1, 13)]

        result.append({
            **row,
            "desvio_abs": round(desvio_abs, 2),
            "desvio_pct": round(desvio_pct, 1),
            "semaforo": semaforo,
            "tolerance_pct": tol,
            "critical_pct": crit,
            "meses_b": meses_b,
            "meses_r": meses_r,
        })

    return result


def _orc2_resumo_executivo(rows: list) -> dict:
    """Extrai KPIs chave para visão do cliente."""
    key_codes = {"02T", "03T", "05T", "07T", "10T"}
    kpis = {}
    for row in rows:
        if row["code"] in key_codes:
            tb, tr = row["total_b"], row["total_r"]
            var = ((tr - tb) / abs(tb) * 100) if tb else 0
            kpis[row["code"]] = {
                "name": row["name"],
                "orcado": tb,
                "realizado": tr,
                "variacao_pct": round(var, 1),
                "semaforo": _orc2_semaforo(var, 10, 20),
            }
    return kpis


# ── Templates ─────────────────────────────────────────────────────────────────

TEMPLATES["orcamento_dashboard.html"] = r"""
{% extends "base.html" %}
{% block content %}
<style>
.sem-verde   { color: #198754; }
.sem-amarelo { color: #ffc107; }
.sem-vermelho{ color: #dc3545; }
.sem-cinza   { color: #6c757d; }
.sem-dot { display:inline-block;width:10px;height:10px;border-radius:50%;margin-right:6px; }
.dot-verde    { background:#198754; }
.dot-amarelo  { background:#ffc107; }
.dot-vermelho { background:#dc3545; }
.dot-cinza    { background:#adb5bd; }
</style>

<div class="d-flex justify-content-between align-items-center mb-3 flex-wrap gap-2">
  <div>
    <h5 class="mb-0">Dashboard — {{ plan.name }}</h5>
    <div class="muted small">
      {% if current_client %}<b>{{ current_client.name }}</b> · {% endif %}
      Desvios do orçamento com semáforo automático
    </div>
  </div>
  <div class="d-flex gap-2 flex-wrap">
    <a href="/ferramentas/orcamento/{{ plan.id }}" class="btn btn-outline-secondary btn-sm">← Planilha</a>
    {% if role in ['admin','equipe'] %}
    <a href="/ferramentas/orcamento/{{ plan.id }}/dashboard?config=1" class="btn btn-outline-secondary btn-sm">⚙ Tolerâncias</a>
    {% endif %}
  </div>
</div>

{# ── Semáforo resumo ── #}
{% set n_verm = rows | selectattr('semaforo','eq','vermelho') | list | length %}
{% set n_amar = rows | selectattr('semaforo','eq','amarelo') | list | length %}
{% set n_verd = rows | selectattr('semaforo','eq','verde') | list | length %}
<div class="row g-3 mb-4">
  <div class="col-md-4">
    <div class="card p-3 text-center border-danger">
      <div class="fs-2 fw-bold text-danger">{{ n_verm }}</div>
      <div class="muted small">Contas críticas (vermelho)</div>
    </div>
  </div>
  <div class="col-md-4">
    <div class="card p-3 text-center border-warning">
      <div class="fs-2 fw-bold text-warning">{{ n_amar }}</div>
      <div class="muted small">Contas em atenção (amarelo)</div>
    </div>
  </div>
  <div class="col-md-4">
    <div class="card p-3 text-center border-success">
      <div class="fs-2 fw-bold text-success">{{ n_verd }}</div>
      <div class="muted small">Contas no orçamento (verde)</div>
    </div>
  </div>
</div>

{# ── Gráfico mensal (totalizadoras chave) ── #}
{% set chart_rows = rows | selectattr('is_totalizer') | list %}
{% if chart_rows %}
<div class="card p-3 mb-4">
  <h6 class="mb-3">Evolução Mensal — Orçado vs Realizado</h6>
  <div class="mb-2">
    <select id="chartSelect" class="form-select form-select-sm" style="max-width:320px">
      {% for r in chart_rows %}
      <option value="{{ loop.index0 }}">{{ r.code }} — {{ r.name }}</option>
      {% endfor %}
    </select>
  </div>
  <canvas id="orc2Chart" height="80"></canvas>
</div>
{% endif %}

{# ── Tabela de desvios ── #}
<div class="card p-0 overflow-hidden">
  <table class="table table-sm mb-0" style="font-size:.82rem">
    <thead class="table-light">
      <tr>
        <th style="min-width:220px">Conta</th>
        <th class="text-end">Orçado</th>
        <th class="text-end">Realizado</th>
        <th class="text-end">Desvio R$</th>
        <th class="text-end">Desvio %</th>
        <th class="text-center">Status</th>
        {% if role in ['admin','equipe'] %}
        <th class="text-center">Ação</th>
        {% endif %}
      </tr>
    </thead>
    <tbody>
      {% for row in rows %}
      {% if row.total_b != 0 or row.total_r != 0 %}
      <tr {% if row.is_totalizer %}class="table-primary fw-bold"{% elif row.has_children %}class="table-light"{% endif %}>
        <td>
          <span class="sem-dot dot-{{ row.semaforo }}"></span>
          <span class="text-muted" style="font-size:.72rem">{{ row.code }}</span>
          {{ '  ' * row.depth }}{{ row.name }}
        </td>
        <td class="text-end">{{ row.total_b | brl }}</td>
        <td class="text-end">{{ row.total_r | brl }}</td>
        <td class="text-end {% if row.desvio_abs > 0 %}text-success{% elif row.desvio_abs < 0 %}text-danger{% endif %}">
          {{ row.desvio_abs | brl }}
        </td>
        <td class="text-end sem-{{ row.semaforo }}">
          {% if row.total_b != 0 %}{{ row.desvio_pct }}%{% else %}—{% endif %}
        </td>
        <td class="text-center">
          {% if row.semaforo == 'vermelho' %}🔴
          {% elif row.semaforo == 'amarelo' %}🟡
          {% elif row.semaforo == 'verde' %}🟢
          {% else %}⚪{% endif %}
        </td>
        {% if role in ['admin','equipe'] %}
        <td class="text-center">
          {% if row.semaforo in ['vermelho','amarelo'] and current_client %}
          <button class="btn btn-outline-warning btn-sm"
            onclick="abrirAcao({{ plan.id }}, {{ row.id }}, '{{ row.name | replace("'","") }}', {{ row.desvio_pct }})">
            ⚡ Ação
          </button>
          {% endif %}
        </td>
        {% endif %}
      </tr>
      {% endif %}
      {% endfor %}
    </tbody>
  </table>
</div>

{# ── Config tolerâncias ── #}
{% if config and role in ['admin','equipe'] %}
<div class="card p-3 mt-4">
  <h6 class="mb-3">⚙ Configurar Tolerâncias de Desvio</h6>
  <div class="muted small mb-3">Define quando uma conta entra em atenção (amarelo) ou crítica (vermelho).</div>
  <div class="table-responsive">
    <table class="table table-sm" style="font-size:.82rem">
      <thead class="table-light">
        <tr><th>Conta</th><th>Atenção (%)</th><th>Crítico (%)</th><th></th></tr>
      </thead>
      <tbody>
        {% for row in rows if not row.has_children and not row.is_totalizer %}
        <tr>
          <td>{{ row.code }} — {{ row.name }}</td>
          <form method="post" action="/api/orcamento/conta/{{ row.id }}/meta" class="contents">
            <td><input type="number" name="tolerance_pct" value="{{ row.tolerance_pct }}" class="form-control form-control-sm" style="width:80px" min="0" max="100" step="1"></td>
            <td><input type="number" name="critical_pct" value="{{ row.critical_pct }}" class="form-control form-control-sm" style="width:80px" min="0" max="100" step="1"></td>
            <td><button class="btn btn-sm btn-outline-primary">Salvar</button></td>
          </form>
        </tr>
        {% endfor %}
      </tbody>
    </table>
  </div>
</div>
{% endif %}

{# Modal ação corretiva #}
<div class="modal fade" id="modalAcao" tabindex="-1">
  <div class="modal-dialog">
    <div class="modal-content p-3">
      <div class="modal-header border-0 pb-1">
        <h6 class="modal-title">⚡ Criar Ação Corretiva</h6>
        <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
      </div>
      <form method="post" action="/api/orcamento/{{ plan.id }}/acao-reuniao">
        <div class="modal-body pt-1">
          <input type="hidden" name="account_id" id="modalAccId">
          <div class="mb-2">
            <label class="form-label small">Título</label>
            <input type="text" name="titulo" id="modalTitulo" class="form-control form-control-sm" required>
          </div>
          <div class="mb-2">
            <label class="form-label small">Vincular à reunião (opcional)</label>
            <select name="meeting_id" class="form-select form-select-sm">
              <option value="">Sem reunião vinculada</option>
              {% for m in reunioes %}
              <option value="{{ m.id }}">{{ m.meeting_date or '' }} — {{ m.title or 'Reunião' }}</option>
              {% endfor %}
            </select>
          </div>
          <div class="mb-2">
            <label class="form-label small">Prazo</label>
            <input type="text" name="prazo" class="form-control form-control-sm" placeholder="DD/MM/AAAA">
          </div>
          <div class="mb-2">
            <label class="form-label small">Prioridade</label>
            <select name="prioridade" class="form-select form-select-sm">
              <option value="alta">Alta</option>
              <option value="media" selected>Média</option>
              <option value="baixa">Baixa</option>
            </select>
          </div>
        </div>
        <div class="modal-footer border-0 pt-0">
          <button type="button" class="btn btn-sm btn-outline-secondary" data-bs-dismiss="modal">Cancelar</button>
          <button class="btn btn-sm btn-primary">Criar ação</button>
        </div>
      </form>
    </div>
  </div>
</div>

<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<script>
var _chartRows = {{ rows_json | safe }};
var _months = ["Jan","Fev","Mar","Abr","Mai","Jun","Jul","Ago","Set","Out","Nov","Dez"];
var _chart = null;

function renderChart(idx) {
  var row = _chartRows[idx];
  if (!row) return;
  var ctx = document.getElementById('orc2Chart');
  if (!ctx) return;
  if (_chart) _chart.destroy();
  _chart = new Chart(ctx, {
    type: 'bar',
    data: {
      labels: _months,
      datasets: [
        { label: 'Orçado', data: row.meses_b, backgroundColor: 'rgba(59,91,219,.25)', borderColor: '#3b5bdb', borderWidth: 1 },
        { label: 'Realizado', data: row.meses_r, backgroundColor: 'rgba(25,135,84,.25)', borderColor: '#198754', borderWidth: 1 },
      ]
    },
    options: {
      responsive: true,
      plugins: { legend: { position: 'top' }, title: { display: true, text: row.code + ' — ' + row.name } },
      scales: { y: { ticks: { callback: v => 'R$ ' + v.toLocaleString('pt-BR') } } }
    }
  });
}

var sel = document.getElementById('chartSelect');
if (sel) {
  renderChart(0);
  sel.addEventListener('change', function(){ renderChart(parseInt(this.value)); });
}

function abrirAcao(planId, accId, accName, desvioPct) {
  document.getElementById('modalAccId').value = accId;
  document.getElementById('modalTitulo').value =
    'Corrigir desvio em "' + accName + '" (' + desvioPct + '%)';
  new bootstrap.Modal(document.getElementById('modalAcao')).show();
}
</script>
{% endblock %}
"""


TEMPLATES["cliente_orcamento.html"] = r"""
{% extends "base.html" %}
{% block content %}
<style>
.kpi-card { border-left: 4px solid #dee2e6; }
.kpi-card.verm { border-left-color: #dc3545; }
.kpi-card.amar { border-left-color: #ffc107; }
.kpi-card.verd { border-left-color: #198754; }
</style>

<h4 class="mb-1">Orçamento {{ plan.year if plan else '' }}</h4>
<p class="text-muted small mb-4">Visão executiva — Orçado vs Realizado nos indicadores principais.</p>

{% if not plan %}
<div class="text-muted">Nenhum orçamento disponível ainda.</div>
{% else %}

{# KPIs chave #}
<div class="row g-3 mb-4">
  {% for code, kpi in kpis.items() %}
  <div class="col-md-6 col-lg-4">
    <div class="card p-3 kpi-card {{ kpi.semaforo[:4] if kpi.semaforo != 'verde' else 'verd' }}">
      <div class="muted small mb-1">{{ kpi.name }}</div>
      <div class="d-flex justify-content-between align-items-end">
        <div>
          <div class="fw-bold fs-5">{{ kpi.realizado | brl }}</div>
          <div class="text-muted small">Meta: {{ kpi.orcado | brl }}</div>
        </div>
        <div class="text-end">
          <div class="fw-semibold {% if kpi.variacao_pct >= 0 %}text-success{% else %}text-danger{% endif %}">
            {{ '+' if kpi.variacao_pct >= 0 else '' }}{{ kpi.variacao_pct }}%
          </div>
          <div class="small">
            {% if kpi.semaforo == 'vermelho' %}🔴 Crítico
            {% elif kpi.semaforo == 'amarelo' %}🟡 Atenção
            {% else %}🟢 OK{% endif %}
          </div>
        </div>
      </div>
    </div>
  </div>
  {% endfor %}
</div>

{# Gráfico evolução receita líquida #}
{% if chart_row %}
<div class="card p-3 mb-4">
  <h6 class="mb-3">{{ chart_row.name }} — Evolução Mensal</h6>
  <canvas id="clientChart" height="90"></canvas>
</div>
{% endif %}

{% endif %}

<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<script>
{% if chart_row %}
(function(){
  var ctx = document.getElementById('clientChart');
  if (!ctx) return;
  new Chart(ctx, {
    type: 'bar',
    data: {
      labels: ["Jan","Fev","Mar","Abr","Mai","Jun","Jul","Ago","Set","Out","Nov","Dez"],
      datasets: [
        { label: 'Orçado', data: {{ chart_row.meses_b | tojson }}, backgroundColor: 'rgba(59,91,219,.2)', borderColor:'#3b5bdb', borderWidth:1 },
        { label: 'Realizado', data: {{ chart_row.meses_r | tojson }}, backgroundColor: 'rgba(25,135,84,.2)', borderColor:'#198754', borderWidth:1 },
      ]
    },
    options: {
      responsive: true,
      plugins: { legend: { position: 'top' } },
      scales: { y: { ticks: { callback: v => 'R$ ' + v.toLocaleString('pt-BR') } } }
    }
  });
})();
{% endif %}
</script>
{% endblock %}
"""


# ── Rotas ─────────────────────────────────────────────────────────────────────

@app.get("/ferramentas/orcamento/{plan_id}/dashboard", response_class=_HTML_orc2)
@require_login
async def orc2_dashboard(request: Request, session: Session = Depends(get_session),
                          plan_id: int = 0, config: str = ""):
    ctx = get_tenant_context(request, session)
    if not ctx or ctx.membership.role not in _ORC_ROLES:
        return _RR_orc2("/", status_code=303)
    plan = session.get(BudgetPlan, plan_id)
    if not plan or plan.company_id != ctx.company.id:
        return _RR_orc2("/ferramentas/orcamento", status_code=303)

    client_id = get_active_client_id(request, session, ctx)
    cc = get_client_or_none(session, ctx.company.id, client_id)

    rows = _orc2_load_dashboard(session, ctx.company.id, plan_id, client_id)

    # Reuniões recentes para vincular ação
    reunioes = []
    if client_id:
        from sqlmodel import select as _s2
        reunioes = session.exec(
            _s2(Meeting)
            .where(Meeting.company_id == ctx.company.id, Meeting.client_id == client_id)
            .order_by(Meeting.created_at.desc())
            .limit(10)
        ).all()

    return render("orcamento_dashboard.html", request=request, context={
        "current_user": ctx.user, "current_company": ctx.company,
        "role": ctx.membership.role, "current_client": cc,
        "plan": plan, "rows": rows,
        "rows_json": _json_orc2.dumps(rows, default=str),
        "reunioes": reunioes,
        "config": bool(config),
        "flash": request.session.pop("flash", None),
    })


@app.get("/cliente/orcamento", response_class=_HTML_orc2)
@require_login
async def orc2_cliente_view(request: Request, session: Session = Depends(get_session)):
    ctx = get_tenant_context(request, session)
    if not ctx:
        return _RR_orc2("/login", status_code=303)

    client_id = ctx.membership.client_id if ctx.membership.role == "cliente" else get_active_client_id(request, session, ctx)
    cc = get_client_or_none(session, ctx.company.id, client_id)

    # Plano ativo mais recente
    plan = session.exec(
        _sel_orc2(BudgetPlan)
        .where(BudgetPlan.company_id == ctx.company.id,
               BudgetPlan.client_id == client_id,
               BudgetPlan.is_active == True)
        .order_by(BudgetPlan.year.desc())
    ).first()

    kpis = {}
    chart_row = None
    if plan:
        rows = _orc2_load_dashboard(session, ctx.company.id, plan.id, client_id)
        kpis = _orc2_resumo_executivo(rows)
        # Gráfico: usa 02T (receita bruta) ou primeira totalizadora
        chart_row = next((r for r in rows if r["code"] == "02T"), None) or \
                    next((r for r in rows if r["is_totalizer"]), None)

    return render("cliente_orcamento.html", request=request, context={
        "current_user": ctx.user, "current_company": ctx.company,
        "role": ctx.membership.role, "current_client": cc,
        "plan": plan, "kpis": kpis, "chart_row": chart_row,
        "flash": request.session.pop("flash", None),
    })


@app.post("/api/orcamento/conta/{acc_id}/meta")
@require_role({"admin", "equipe"})
async def orc2_set_meta(request: Request, session: Session = Depends(get_session),
                         acc_id: int = 0,
                         tolerance_pct: float = _Form_orc2(10.0),
                         critical_pct: float = _Form_orc2(20.0)):
    ctx = get_tenant_context(request, session)
    assert ctx
    acc = session.get(BudgetAccount, acc_id)
    if not acc or acc.company_id != ctx.company.id:
        return _JSON_orc2({"ok": False}, status_code=403)

    existing = session.exec(
        _sel_orc2(BudgetAlert)
        .where(BudgetAlert.company_id == ctx.company.id, BudgetAlert.account_id == acc_id)
    ).first()
    if existing:
        existing.tolerance_pct = tolerance_pct
        existing.critical_pct = critical_pct
        existing.updated_at = utcnow()
        session.add(existing)
    else:
        session.add(BudgetAlert(
            company_id=ctx.company.id,
            account_id=acc_id,
            tolerance_pct=tolerance_pct,
            critical_pct=critical_pct,
        ))
    session.commit()
    # Volta para a config do dashboard
    referer = request.headers.get("referer", "/ferramentas/orcamento")
    return _RR_orc2(referer, status_code=303)


@app.post("/api/orcamento/{plan_id}/acao-reuniao")
@require_role({"admin", "equipe"})
async def orc2_criar_acao(
    request: Request,
    session: Session = Depends(get_session),
    plan_id: int = 0,
    account_id: str = _Form_orc2(""),
    meeting_id: str = _Form_orc2(""),
    titulo: str = _Form_orc2(""),
    prazo: str = _Form_orc2(""),
    prioridade: str = _Form_orc2("media"),
):
    ctx = get_tenant_context(request, session)
    assert ctx
    plan = session.get(BudgetPlan, plan_id)
    if not plan or plan.company_id != ctx.company.id:
        return _RR_orc2("/ferramentas/orcamento", status_code=303)

    client_id = get_active_client_id(request, session, ctx)
    titulo = titulo.strip()

    # Resolve meeting — se não informado, cria ação sem reunião (meeting_id=0)
    mt_id = int(meeting_id) if meeting_id.isdigit() else None
    if mt_id:
        mt = session.get(Meeting, mt_id)
        if not mt or mt.company_id != ctx.company.id:
            mt_id = None

    # Cria MeetingAcao (se tiver reunião) ou apenas uma ação isolada
    if mt_id and titulo:
        try:
            acao = MeetingAcao(
                meeting_id=mt_id,
                company_id=ctx.company.id,
                client_id=client_id or 0,
                titulo=titulo,
                descricao=f"Desvio identificado no orçamento — conta vinculada ao plano {plan.name} ({plan.year}).",
                prazo=_normalize_date_input(prazo),
                prioridade=prioridade if prioridade in ("alta", "media", "baixa") else "media",
                status="aberta",
            )
            session.add(acao)
            session.commit()
            set_flash(request, f"Ação '{titulo}' criada e vinculada à reunião.")
        except Exception as _e:
            set_flash(request, f"Erro ao criar ação: {_e}")
    elif titulo:
        set_flash(request, "Ação não criada: selecione uma reunião para vincular.")
    else:
        set_flash(request, "Título obrigatório.")

    return _RR_orc2(f"/ferramentas/orcamento/{plan_id}/dashboard", status_code=303)


# ── Adicionar botão Dashboard na planilha de orçamento ───────────────────────

def _orc2_patch_grid_template():
    """Injeta botão 'Dashboard' na barra de ações da planilha."""
    tpl = TEMPLATES.get("orcamento_grid.html", "")
    marker = '<a href="/ferramentas/orcamento" class="btn btn-outline-secondary btn-sm">← Planos</a>'
    if marker in tpl and "dashboard" not in tpl:
        new_btn = marker + '\n    <a href="/ferramentas/orcamento/{{ plan.id }}/dashboard" class="btn btn-outline-info btn-sm">📊 Dashboard</a>'
        TEMPLATES["orcamento_grid.html"] = tpl.replace(marker, new_btn, 1)
        # Propaga para o Jinja env se já carregado
        try:
            templates_env.loader.mapping["orcamento_grid.html"] = TEMPLATES["orcamento_grid.html"]
        except Exception:
            pass
        print("[orcamento_v2] ✅ Botão Dashboard injetado em orcamento_grid.html")

_orc2_patch_grid_template()


# ── Card de orçamento na dashboard do cliente ────────────────────────────────

def _orc2_patch_dashboard():
    """Adiciona card 'Orçamento' na dashboard para role=cliente."""
    tpl = TEMPLATES.get("dashboard.html", "")
    marker = '{% if role == "cliente" %}\n  <div class="col-12">\n    <div class="card p-4">\n      <div class="d-flex justify-content-between align-items-center mb-2">\n        <div>\n          <h5 class="mb-0">📋 Reuniões &amp; Ações</h5>'
    orc_card = """  {% if role == "cliente" %}
  <div class="col-12">
    <div class="card p-4">
      <div class="d-flex justify-content-between align-items-center mb-2">
        <div>
          <h5 class="mb-0">📊 Orçamento</h5>
          <div class="muted small">Acompanhe o realizado versus o orçado da sua empresa.</div>
        </div>
        <a class="btn btn-outline-primary btn-sm" href="/cliente/orcamento">Ver painel</a>
      </div>
    </div>
  </div>
  {% endif %}

"""
    if marker in tpl and "/cliente/orcamento" not in tpl:
        TEMPLATES["dashboard.html"] = tpl.replace(marker, orc_card + marker, 1)
        try:
            templates_env.loader.mapping["dashboard.html"] = TEMPLATES["dashboard.html"]
        except Exception:
            pass
        print("[orcamento_v2] ✅ Card Orçamento injetado na dashboard do cliente")

_orc2_patch_dashboard()


print("[orcamento_v2] ✅ Módulo Orçamento v2 carregado.")

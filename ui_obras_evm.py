# ============================================================================
# PATCH — EVM (Earned Value Management) para Gestão de Obras
# ============================================================================
# Salve como ui_obras_evm.py e adicione ao final do app.py:
#   exec(open('ui_obras_evm.py').read())
#
# INDICADORES:
#   PV  — Planned Value (valor planejado até hoje)
#   EV  — Earned Value (valor agregado = % físico × orçado)
#   AC  — Actual Cost (custo real apontado)
#   IDC — Índice Desempenho Custo (EV/AC) > 1 = abaixo do orçado
#   IDP — Índice Desempenho Prazo (EV/PV) > 1 = adiantado
#   EAC — Estimate at Completion (projeção custo final = orçado/IDC)
#   VAC — Variance at Completion (orçado - EAC)
#   BAC — Budget at Completion (orçado total)
#   Curva S — PV vs EV vs AC ao longo do tempo
# ============================================================================

import json as _json_evm
from datetime import datetime as _dt_evm, date as _date_evm, timedelta as _td_evm


# ── Cálculo EVM ───────────────────────────────────────────────────────────────

def _parse_date(s: str):
    """Converte string de data para date. Aceita DD/MM/AAAA ou YYYY-MM-DD."""
    if not s:
        return None
    s = s.strip()
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d/%m/%y"):
        try:
            return _dt_evm.strptime(s, fmt).date()
        except Exception:
            pass
    return None


def _calcular_evm(session, obra) -> dict:
    """
    Calcula todos os indicadores EVM para uma obra.
    Retorna dict com PV, EV, AC, IDC, IDP, EAC, VAC, BAC e curva_s.
    """
    from sqlmodel import select as _sel_evm
    hoje = _date_evm.today()

    fases = session.exec(
        select(ObraFase).where(ObraFase.obra_id == obra.id).order_by(ObraFase.ordem)
    ).all()

    # Coleta todas as etapas com apontamentos
    etapas_data = []
    for fase in fases:
        etapas = session.exec(
            select(ObraEtapa).where(ObraEtapa.fase_id == fase.id).order_by(ObraEtapa.ordem)
        ).all()
        for etapa in etapas:
            # Último apontamento
            apt = session.exec(
                select(ObraApontamento)
                .where(ObraApontamento.etapa_id == etapa.id)
                .order_by(ObraApontamento.id.desc())
                .limit(1)
            ).first()

            dt_inicio = _parse_date(etapa.data_inicio)
            dt_fim    = _parse_date(etapa.data_fim)

            # PV: quanto deveria estar gasto até hoje (proporcional ao período)
            pv_etapa = 0.0
            if dt_inicio and dt_fim and dt_fim > dt_inicio:
                duracao_total = (dt_fim - dt_inicio).days
                if hoje <= dt_inicio:
                    pv_etapa = 0.0
                elif hoje >= dt_fim:
                    pv_etapa = float(etapa.orcado_rs)
                else:
                    dias_decorridos = (hoje - dt_inicio).days
                    pv_etapa = float(etapa.orcado_rs) * (dias_decorridos / duracao_total)
            elif dt_fim and hoje >= dt_fim:
                pv_etapa = float(etapa.orcado_rs)

            # EV: valor agregado real (% físico × orçado)
            fisico_pct = float(apt.fisico_pct if apt else 0) / 100.0
            ev_etapa   = float(etapa.orcado_rs) * fisico_pct

            # AC: custo real apontado
            ac_etapa = float(apt.financeiro_rs if apt else 0)

            etapas_data.append({
                "id":         etapa.id,
                "descricao":  etapa.descricao,
                "fase":       fase.nome,
                "orcado":     float(etapa.orcado_rs),
                "pv":         pv_etapa,
                "ev":         ev_etapa,
                "ac":         ac_etapa,
                "fisico_pct": float(apt.fisico_pct if apt else 0),
                "dt_inicio":  str(dt_inicio) if dt_inicio else "",
                "dt_fim":     str(dt_fim) if dt_fim else "",
            })

    # Totais
    BAC = sum(e["orcado"] for e in etapas_data)
    PV  = sum(e["pv"]     for e in etapas_data)
    EV  = sum(e["ev"]     for e in etapas_data)
    AC  = sum(e["ac"]     for e in etapas_data)

    # Índices
    IDC = round(EV / AC,  3) if AC  > 0 else None
    IDP = round(EV / PV,  3) if PV  > 0 else None

    # Projeções
    EAC = round(BAC / IDC, 2) if IDC and IDC > 0 else BAC
    VAC = round(BAC - EAC, 2)
    ETC = round(EAC - AC, 2)  # Estimate to Complete

    # % físico geral
    fisico_geral = round((EV / BAC * 100), 1) if BAC > 0 else 0

    # Status do IDC
    def _idc_status(idc):
        if idc is None:    return ("—", "secondary")
        if idc >= 1.05:    return ("Ótimo", "success")
        if idc >= 0.95:    return ("Normal", "primary")
        if idc >= 0.85:    return ("Atenção", "warning")
        return ("Crítico", "danger")

    def _idp_status(idp):
        if idp is None:    return ("—", "secondary")
        if idp >= 1.05:    return ("Adiantado", "success")
        if idp >= 0.95:    return ("No prazo", "primary")
        if idp >= 0.85:    return ("Atrasado", "warning")
        return ("Muito atrasado", "danger")

    idc_label, idc_color = _idc_status(IDC)
    idp_label, idp_color = _idp_status(IDP)

    # Curva S — pontos mensais
    curva_s = _calcular_curva_s(etapas_data, obra)

    return {
        "BAC":         round(BAC, 2),
        "PV":          round(PV, 2),
        "EV":          round(EV, 2),
        "AC":          round(AC, 2),
        "IDC":         IDC,
        "IDP":         IDP,
        "EAC":         EAC,
        "VAC":         VAC,
        "ETC":         ETC,
        "fisico_geral": fisico_geral,
        "idc_label":   idc_label,
        "idc_color":   idc_color,
        "idp_label":   idp_label,
        "idp_color":   idp_color,
        "etapas":      etapas_data,
        "curva_s":     curva_s,
        "hoje":        str(hoje),
    }


def _calcular_curva_s(etapas_data: list, obra) -> dict:
    """
    Gera pontos mensais para a Curva S.
    Retorna dict com labels (meses) e series PV, EV, AC.
    """
    if not etapas_data:
        return {"labels": [], "pv": [], "ev": [], "ac": []}

    # Encontra range de datas
    datas = [e["dt_inicio"] for e in etapas_data if e["dt_inicio"]]
    datas += [e["dt_fim"]   for e in etapas_data if e["dt_fim"]]

    if not datas:
        return {"labels": [], "pv": [], "ev": [], "ac": []}

    try:
        dt_min = min(_date_evm.fromisoformat(d) for d in datas if d)
        dt_max = max(_date_evm.fromisoformat(d) for d in datas if d)
    except Exception:
        return {"labels": [], "pv": [], "ev": [], "ac": []}

    hoje = _date_evm.today()
    dt_max = max(dt_max, hoje)

    # Gera meses
    meses = []
    d = _date_evm(dt_min.year, dt_min.month, 1)
    while d <= dt_max:
        meses.append(d)
        if d.month == 12:
            d = _date_evm(d.year + 1, 1, 1)
        else:
            d = _date_evm(d.year, d.month + 1, 1)

    labels = [f"{m.strftime('%b/%y')}" for m in meses]
    pv_series = []
    ev_series = []
    ac_series = []

    for mes in meses:
        fim_mes = _date_evm(
            mes.year if mes.month < 12 else mes.year + 1,
            mes.month + 1 if mes.month < 12 else 1, 1
        ) - _td_evm(days=1)

        pv_acum = 0.0
        ev_acum = 0.0
        ac_acum = 0.0

        for e in etapas_data:
            dt_i = _date_evm.fromisoformat(e["dt_inicio"]) if e["dt_inicio"] else None
            dt_f = _date_evm.fromisoformat(e["dt_fim"])    if e["dt_fim"]    else None

            # PV acumulado até fim do mês
            if dt_i and dt_f and dt_f > dt_i:
                duracao = (dt_f - dt_i).days
                if fim_mes <= dt_i:
                    pv_etapa = 0.0
                elif fim_mes >= dt_f:
                    pv_etapa = e["orcado"]
                else:
                    dias = (fim_mes - dt_i).days
                    pv_etapa = e["orcado"] * (dias / duracao)
                pv_acum += pv_etapa
            elif dt_f and fim_mes >= dt_f:
                pv_acum += e["orcado"]

            # EV e AC: assume distribuição até hoje
            if fim_mes >= hoje:
                ev_acum += e["ev"]
                ac_acum += e["ac"]
            elif fim_mes >= (dt_f or hoje):
                ev_acum += e["ev"]
                ac_acum += e["ac"]

        pv_series.append(round(pv_acum, 2))
        ev_series.append(round(ev_acum, 2))
        ac_series.append(round(ac_acum, 2))

    return {"labels": labels, "pv": pv_series, "ev": ev_series, "ac": ac_series}


# ── Rota GET /ferramentas/obras/{id}/evm ─────────────────────────────────────

@app.get("/ferramentas/obras/{obra_id}/evm", response_class=HTMLResponse)
@require_login
async def obras_evm_get(obra_id: int, request: Request, session: Session = Depends(get_session)):
    ctx = get_tenant_context(request, session)
    if not ctx:
        request.session.clear()
        return RedirectResponse("/login", status_code=303)

    obra = session.exec(
        select(Obra)
        .where(Obra.id == obra_id, Obra.company_id == ctx.company.id)
    ).first()
    if not obra:
        return RedirectResponse("/ferramentas/obras", status_code=303)

    evm = _calcular_evm(session, obra)
    cc  = get_client_or_none(session, ctx.company.id,
                             get_active_client_id(request, session, ctx))

    return render("obras_evm.html", request=request, context={
        "current_user":    ctx.user,
        "current_company": ctx.company,
        "role":            ctx.membership.role,
        "current_client":  cc,
        "obra":            obra,
        "evm":             evm,
        "curva_s_json":    _json_evm.dumps(evm["curva_s"]),
    })


# ── Template ──────────────────────────────────────────────────────────────────

TEMPLATES["obras_evm.html"] = r"""
{% extends "base.html" %}
{% block content %}
<style>
  .evm-kpi{border:1px solid var(--mc-border);border-radius:12px;padding:1rem;background:#fff;text-align:center;}
  .evm-kpi-val{font-size:1.6rem;font-weight:800;letter-spacing:-.03em;}
  .evm-kpi-lbl{font-size:.72rem;text-transform:uppercase;letter-spacing:.06em;color:var(--mc-muted);margin-top:.2rem;}
  .evm-kpi-sub{font-size:.78rem;margin-top:.25rem;}
  .evm-tbl{width:100%;border-collapse:collapse;font-size:.82rem;}
  .evm-tbl th{background:#f9fafb;padding:.4rem .6rem;text-align:left;font-size:.7rem;text-transform:uppercase;letter-spacing:.05em;color:var(--mc-muted);border-bottom:2px solid var(--mc-border);}
  .evm-tbl td{padding:.4rem .6rem;border-bottom:1px solid var(--mc-border);}
  .evm-tbl tr:hover td{background:#fafafa;}
  .idc-ok{color:#16a34a;font-weight:700;}
  .idc-warn{color:#ca8a04;font-weight:700;}
  .idc-bad{color:#dc2626;font-weight:700;}
  .curva-wrap{border:1px solid var(--mc-border);border-radius:12px;padding:1rem;background:#fff;}
</style>

<div class="d-flex justify-content-between align-items-start flex-wrap gap-2 mb-3">
  <div>
    <a href="/ferramentas/obras/{{ obra.id }}" class="btn btn-outline-secondary btn-sm mb-2">← Cronograma</a>
    <h4 class="mb-1">📊 EVM — {{ obra.nome }}</h4>
    <div class="muted small">Earned Value Management · Data de referência: {{ evm.hoje }}</div>
  </div>
  <a href="/ferramentas/obras/{{ obra.id }}" class="btn btn-outline-secondary btn-sm">Ver cronograma</a>
</div>

{# ── KPIs principais ── #}
<div class="row g-3 mb-3">
  <div class="col-6 col-md-2">
    <div class="evm-kpi">
      <div class="evm-kpi-val" style="color:var(--mc-primary);">{{ "%.0f"|format(evm.fisico_geral) }}%</div>
      <div class="evm-kpi-lbl">Físico geral</div>
    </div>
  </div>
  <div class="col-6 col-md-2">
    <div class="evm-kpi">
      <div class="evm-kpi-val text-{{ evm.idc_color }}">{{ evm.IDC or '—' }}</div>
      <div class="evm-kpi-lbl">IDC</div>
      <div class="evm-kpi-sub text-{{ evm.idc_color }}">{{ evm.idc_label }}</div>
    </div>
  </div>
  <div class="col-6 col-md-2">
    <div class="evm-kpi">
      <div class="evm-kpi-val text-{{ evm.idp_color }}">{{ evm.IDP or '—' }}</div>
      <div class="evm-kpi-lbl">IDP</div>
      <div class="evm-kpi-sub text-{{ evm.idp_color }}">{{ evm.idp_label }}</div>
    </div>
  </div>
  <div class="col-6 col-md-2">
    <div class="evm-kpi">
      <div class="evm-kpi-val" style="color:#3b82f6;">R$ {{ "%.0f"|format(evm.EAC/1000) }}k</div>
      <div class="evm-kpi-lbl">EAC (projeção)</div>
      <div class="evm-kpi-sub {% if evm.VAC >= 0 %}text-success{% else %}text-danger{% endif %}">
        VAC: {{ '+' if evm.VAC >= 0 else '' }}R$ {{ "%.0f"|format(evm.VAC/1000) }}k
      </div>
    </div>
  </div>
  <div class="col-6 col-md-2">
    <div class="evm-kpi">
      <div class="evm-kpi-val">R$ {{ "%.0f"|format(evm.ETC/1000) }}k</div>
      <div class="evm-kpi-lbl">ETC (a incorrer)</div>
    </div>
  </div>
  <div class="col-6 col-md-2">
    <div class="evm-kpi">
      <div class="evm-kpi-val">R$ {{ "%.0f"|format(evm.BAC/1000) }}k</div>
      <div class="evm-kpi-lbl">BAC (orçado)</div>
    </div>
  </div>
</div>

{# ── Linha EV/PV/AC ── #}
<div class="row g-3 mb-3">
  <div class="col-md-4">
    <div class="evm-kpi">
      <div class="evm-kpi-val text-success">R$ {{ "%.0f"|format(evm.EV/1000) }}k</div>
      <div class="evm-kpi-lbl">EV — Valor Agregado</div>
      <div class="evm-kpi-sub muted">O quanto da obra está "pronta" em R$</div>
    </div>
  </div>
  <div class="col-md-4">
    <div class="evm-kpi">
      <div class="evm-kpi-val" style="color:#8b5cf6;">R$ {{ "%.0f"|format(evm.PV/1000) }}k</div>
      <div class="evm-kpi-lbl">PV — Valor Planejado</div>
      <div class="evm-kpi-sub muted">O quanto deveria estar pronto hoje</div>
    </div>
  </div>
  <div class="col-md-4">
    <div class="evm-kpi">
      <div class="evm-kpi-val" style="color:#f59e0b;">R$ {{ "%.0f"|format(evm.AC/1000) }}k</div>
      <div class="evm-kpi-lbl">AC — Custo Real</div>
      <div class="evm-kpi-sub muted">O quanto já foi gasto de fato</div>
    </div>
  </div>
</div>

{# ── Legenda dos índices ── #}
<div class="row g-2 mb-3">
  <div class="col-12">
    <div class="alert alert-light border" style="font-size:.8rem;">
      <strong>Como ler:</strong>
      IDC > 1 = abaixo do orçado ✅ | IDC < 1 = acima do orçado ⚠️ |
      IDP > 1 = adiantado ✅ | IDP < 1 = atrasado ⚠️ |
      EAC = projeção do custo final | VAC = economia/estouro projetado
    </div>
  </div>
</div>

{# ── Curva S ── #}
<div class="curva-wrap mb-3">
  <h6 class="mb-3">📈 Curva S — PV × EV × AC</h6>
  <canvas id="curvaSChart" style="max-height:300px;"></canvas>
</div>

{# ── Tabela por etapa ── #}
<div class="curva-wrap">
  <h6 class="mb-3">📋 Desempenho por Etapa</h6>
  <div class="table-responsive">
    <table class="evm-tbl">
      <thead>
        <tr>
          <th>Fase / Etapa</th>
          <th>Orçado</th>
          <th>PV</th>
          <th>EV</th>
          <th>AC</th>
          <th>IDC</th>
          <th>Físico</th>
          <th>Período</th>
        </tr>
      </thead>
      <tbody>
        {% for e in evm.etapas %}
        {% set idc_e = (e.ev / e.ac) if e.ac > 0 else None %}
        <tr>
          <td>
            <div style="font-size:.7rem;color:var(--mc-muted);">{{ e.fase }}</div>
            <div>{{ e.descricao }}</div>
          </td>
          <td>R$ {{ "%.0f"|format(e.orcado) }}</td>
          <td>R$ {{ "%.0f"|format(e.pv) }}</td>
          <td style="color:#16a34a;">R$ {{ "%.0f"|format(e.ev) }}</td>
          <td style="color:#f59e0b;">R$ {{ "%.0f"|format(e.ac) }}</td>
          <td>
            {% if idc_e is not none %}
            <span class="{% if idc_e >= 1 %}idc-ok{% elif idc_e >= 0.85 %}idc-warn{% else %}idc-bad{% endif %}">
              {{ "%.2f"|format(idc_e) }}
            </span>
            {% else %}—{% endif %}
          </td>
          <td>
            <div style="display:flex;align-items:center;gap:.35rem;">
              <div style="width:50px;height:6px;background:#f3f4f6;border-radius:3px;overflow:hidden;">
                <div style="width:{{ e.fisico_pct }}%;height:100%;background:var(--mc-primary);border-radius:3px;"></div>
              </div>
              <span style="font-size:.75rem;font-weight:600;">{{ "%.0f"|format(e.fisico_pct) }}%</span>
            </div>
          </td>
          <td style="font-size:.72rem;color:var(--mc-muted);">
            {{ e.dt_inicio }} →<br>{{ e.dt_fim }}
          </td>
        </tr>
        {% endfor %}
      </tbody>
    </table>
  </div>
</div>

<script src="https://cdn.jsdelivr.net/npm/chart.js@4/dist/chart.umd.min.js"></script>
<script>
(function() {
  const dados = {{ curva_s_json|safe }};
  if (!dados.labels || !dados.labels.length) return;

  const ctx = document.getElementById('curvaSChart');
  new Chart(ctx, {
    type: 'line',
    data: {
      labels: dados.labels,
      datasets: [
        {
          label: 'PV — Planejado',
          data: dados.pv,
          borderColor: '#8b5cf6',
          backgroundColor: 'rgba(139,92,246,.1)',
          fill: false,
          tension: .3,
          borderDash: [5,3],
        },
        {
          label: 'EV — Agregado',
          data: dados.ev,
          borderColor: '#16a34a',
          backgroundColor: 'rgba(22,163,74,.1)',
          fill: false,
          tension: .3,
        },
        {
          label: 'AC — Real',
          data: dados.ac,
          borderColor: '#f59e0b',
          backgroundColor: 'rgba(245,158,11,.1)',
          fill: false,
          tension: .3,
        },
      ],
    },
    options: {
      responsive: true,
      plugins: {
        legend: { position: 'top' },
        tooltip: {
          callbacks: {
            label: ctx => ctx.dataset.label + ': R$ ' +
              ctx.raw.toLocaleString('pt-BR', {minimumFractionDigits:0})
          }
        }
      },
      scales: {
        y: {
          ticks: {
            callback: v => 'R$ ' + (v/1000).toFixed(0) + 'k'
          }
        }
      }
    }
  });
})();
</script>
{% endblock %}
"""

# ── Injeta botão EVM na tela da obra ─────────────────────────────────────────
_obras_tmpl = TEMPLATES.get("obras_detail.html", "")
if _obras_tmpl and "evm" not in _obras_tmpl:
    for _anchor in ['<a href="/ferramentas/obras/{{ obra.id }}/editar"',
                    'href="/ferramentas/obras']:
        if _anchor in _obras_tmpl:
            _obras_tmpl = _obras_tmpl.replace(
                _anchor,
                f'<a href="/ferramentas/obras/{{{{ obra.id }}}}/evm" class="btn btn-outline-primary btn-sm">'
                f'<i class="bi bi-graph-up me-1"></i>EVM</a>\n    ' + _anchor,
                1,
            )
            TEMPLATES["obras_detail.html"] = _obras_tmpl
            break

if hasattr(templates_env.loader, "mapping"):
    templates_env.loader.mapping = TEMPLATES

print("[evm] Patch EVM carregado.")

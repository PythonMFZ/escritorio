# ============================================================================
# PATCH — Sprint 5: Painel de Carteira de Clientes
# ============================================================================
# Cole ao final do app.py (após o exec do snapshot_detail).
# Ou salve como ui_upgrade_sprint5.py e adicione:
#   exec(open('ui_upgrade_sprint5.py').read())
#
# O QUE FAZ:
#   1. Rota GET /carteira — lista todos os clientes da company com
#      último snapshot, score, classificação G4, indicadores principais
#      ordenados do pior (score mais baixo) para o melhor
#   2. Template carteira.html — painel visual com ranking, filtros e
#      link para abrir cada cliente no dashboard
#   3. Injeta link "Carteira" no dashboard.html para admin/equipe
#
# ZERO mudança em models, banco ou rotas existentes.
# ============================================================================


# ── 1. Rota /carteira ─────────────────────────────────────────────────────────

@app.get("/carteira", response_class=HTMLResponse)
@require_login
async def carteira_page(
    request: Request,
    session: Session = Depends(get_session),
) -> HTMLResponse:
    ctx = get_tenant_context(request, session)
    if not ctx:
        request.session.clear()
        return RedirectResponse("/login", status_code=303)

    # Só admin e equipe podem ver a carteira completa
    if ctx.membership.role not in ("admin", "equipe"):
        return RedirectResponse("/", status_code=303)

    # Busca todos os clientes ativos da company
    try:
        all_clients = session.exec(
            select(Client)
            .where(Client.company_id == ctx.company.id)
            .order_by(Client.name)
        ).all()
    except Exception:
        all_clients = []

    # Para cada cliente: busca último snapshot e monta card
    carteira: list[dict] = []
    for client in all_clients:
        try:
            snap = session.exec(
                select(ClientSnapshot)
                .where(
                    ClientSnapshot.company_id == ctx.company.id,
                    ClientSnapshot.client_id  == client.id,
                )
                .order_by(ClientSnapshot.created_at.desc())
                .limit(1)
            ).first()

            profile = None
            try:
                profile = get_or_create_business_profile(
                    session,
                    company_id=ctx.company.id,
                    client_id=client.id,
                )
            except Exception:
                pass

            # Score
            if snap:
                score_total    = float(snap.score_total or 0)
                score_process  = float(snap.score_process or 0)
                score_fin      = float(snap.score_financial or 0)
                snap_date      = snap.created_at
                dias_sem_update = (utcnow() - snap.created_at).days if snap.created_at else 999
            else:
                score_total = score_process = score_fin = 0.0
                snap_date = None
                dias_sem_update = 999

            # Classificação G4
            rev  = float(getattr(profile, "cash_and_investments_brl", 0) or 0) if profile else float(client.cash_balance_brl or 0)
            ac   = float(getattr(profile, "cash_and_investments_brl", 0) or 0) + \
                   float(getattr(profile, "receivables_brl", 0) or 0) + \
                   float(getattr(profile, "inventory_brl", 0) or 0) + \
                   float(getattr(profile, "other_current_assets_brl", 0) or 0) if profile else 0
            anc  = float(getattr(profile, "immobilized_brl", 0) or 0) + \
                   float(getattr(profile, "other_non_current_assets_brl", 0) or 0) if profile else 0
            pc   = float(getattr(profile, "payables_360_brl", 0) or 0) + \
                   float(getattr(profile, "short_term_debt_brl", 0) or 0) + \
                   float(getattr(profile, "tax_liabilities_brl", 0) or 0) + \
                   float(getattr(profile, "labor_liabilities_brl", 0) or 0) + \
                   float(getattr(profile, "other_current_liabilities_brl", 0) or 0) if profile else 0
            pnc  = float(getattr(profile, "long_term_debt_brl", 0) or 0) if profile else 0
            at   = ac + anc
            pt   = pc + pnc
            pl   = at - pt

            if at > 0:
                if pl >= anc:
                    g4 = "saudavel"
                elif (pl + pnc) >= anc:
                    g4 = "alerta"
                else:
                    g4 = "deficiente"
            else:
                g4 = "sem_dados"

            # Indicadores rápidos
            liq = round(ac / pc, 2) if pc > 0 else None
            debt_rev = round(float(client.debt_total_brl or 0) / max(float(client.revenue_monthly_brl or 1), 1), 2)

            # Alertas não lidos
            try:
                alertas = session.exec(
                    select(func.count())
                    .select_from(SmartAlert)
                    .where(
                        SmartAlert.company_id == ctx.company.id,
                        SmartAlert.client_id  == client.id,
                        SmartAlert.is_read    == False,
                    )
                ).one() or 0
            except Exception:
                alertas = 0

            carteira.append({
                "client":          client,
                "score_total":     score_total,
                "score_process":   score_process,
                "score_fin":       score_fin,
                "snap_date":       snap_date,
                "dias":            dias_sem_update,
                "g4":              g4,
                "liq":             liq,
                "debt_rev":        debt_rev,
                "alertas":         alertas,
                "revenue":         float(client.revenue_monthly_brl or 0),
                "cash":            float(client.cash_balance_brl or 0),
                "debt":            float(client.debt_total_brl or 0),
            })
        except Exception:
            continue

    # Ordena: sem dados no final, resto por score crescente (pior primeiro)
    def sort_key(r):
        if r["g4"] == "sem_dados":
            return (2, 999)
        return (0, r["score_total"])

    carteira.sort(key=sort_key)

    # Resumo da carteira
    com_dados    = [r for r in carteira if r["g4"] != "sem_dados"]
    n_saudavel   = sum(1 for r in com_dados if r["g4"] == "saudavel")
    n_alerta     = sum(1 for r in com_dados if r["g4"] == "alerta")
    n_deficiente = sum(1 for r in com_dados if r["g4"] == "deficiente")
    n_sem_dados  = sum(1 for r in carteira if r["g4"] == "sem_dados")
    score_medio  = round(sum(r["score_total"] for r in com_dados) / max(len(com_dados), 1), 1)
    n_alertas_total = sum(r["alertas"] for r in carteira)

    return render(
        "carteira.html",
        request=request,
        context={
            "current_user":    ctx.user,
            "current_company": ctx.company,
            "role":            ctx.membership.role,
            "current_client":  None,
            "carteira":        carteira,
            "n_total":         len(carteira),
            "n_saudavel":      n_saudavel,
            "n_alerta":        n_alerta,
            "n_deficiente":    n_deficiente,
            "n_sem_dados":     n_sem_dados,
            "score_medio":     score_medio,
            "n_alertas_total": n_alertas_total,
        },
    )


# ── 2. Template carteira.html ─────────────────────────────────────────────────

TEMPLATES["carteira.html"] = r"""
{% extends "base.html" %}
{% block content %}
<style>
  /* ── Header ── */
  .cw-header{ display:flex; justify-content:space-between; align-items:flex-start; flex-wrap:wrap; gap:1rem; margin-bottom:1.5rem; }

  /* ── KPIs da carteira ── */
  .cw-kpis{ display:grid; grid-template-columns:repeat(auto-fit,minmax(120px,1fr)); gap:.65rem; margin-bottom:1.5rem; }
  .cw-kpi{ background:#fff; border:1px solid var(--mc-border); border-radius:14px; padding:.9rem 1rem; text-align:center; }
  .cw-kpi-val{ font-size:26px; font-weight:700; letter-spacing:-.02em; }
  .cw-kpi-lbl{ font-size:.72rem; color:var(--mc-muted); margin-top:.2rem; }

  /* ── Filtro ── */
  .cw-filter{ display:flex; gap:.5rem; flex-wrap:wrap; margin-bottom:1rem; }
  .cw-filter-btn{
    padding:.35rem .85rem; border-radius:999px; font-size:.8rem; font-weight:600;
    border:2px solid var(--mc-border); background:#fff; cursor:pointer;
    transition:all .15s;
  }
  .cw-filter-btn:hover{ border-color:var(--mc-primary); color:var(--mc-primary); }
  .cw-filter-btn.active{ background:var(--mc-primary); border-color:var(--mc-primary); color:#fff; }
  .cw-filter-btn.f-saudavel.active{ background:#16a34a; border-color:#16a34a; }
  .cw-filter-btn.f-alerta.active{ background:#ca8a04; border-color:#ca8a04; }
  .cw-filter-btn.f-deficiente.active{ background:#dc2626; border-color:#dc2626; }

  /* ── Cards de cliente ── */
  .cw-card{
    background:#fff; border:1px solid var(--mc-border); border-radius:16px;
    padding:1.1rem 1.25rem; margin-bottom:.65rem;
    display:grid; grid-template-columns:auto 1fr auto; gap:1rem; align-items:center;
    transition:all .15s; text-decoration:none; color:inherit;
    position:relative; overflow:hidden;
  }
  .cw-card:hover{ border-color:var(--mc-primary); transform:translateX(3px); color:inherit; }
  .cw-card.saudavel{ border-left:4px solid #16a34a; }
  .cw-card.alerta{ border-left:4px solid #ca8a04; }
  .cw-card.deficiente{ border-left:4px solid #dc2626; }
  .cw-card.sem_dados{ border-left:4px solid #9ca3af; opacity:.8; }

  /* Posição no ranking */
  .cw-rank{
    width:36px; height:36px; border-radius:50%; flex-shrink:0;
    display:flex; align-items:center; justify-content:center;
    font-size:.8rem; font-weight:700; color:#fff;
  }
  .cw-rank.saudavel{ background:#16a34a; }
  .cw-rank.alerta{ background:#ca8a04; }
  .cw-rank.deficiente{ background:#dc2626; }
  .cw-rank.sem_dados{ background:#9ca3af; }

  /* Info do cliente */
  .cw-name{ font-weight:700; font-size:.95rem; }
  .cw-meta{ font-size:.75rem; color:var(--mc-muted); margin-top:.1rem; display:flex; gap:.75rem; flex-wrap:wrap; }

  /* Scores inline */
  .cw-scores{ display:flex; gap:.5rem; flex-wrap:wrap; margin-top:.5rem; }
  .cw-score-chip{
    font-size:.72rem; font-weight:600; padding:.2rem .55rem;
    border-radius:999px; border:1px solid var(--mc-border);
  }

  /* Lado direito */
  .cw-right{ text-align:right; flex-shrink:0; }
  .cw-score-big{ font-size:28px; font-weight:700; line-height:1; letter-spacing:-.02em; }
  .cw-g4-badge{
    display:inline-block; font-size:.68rem; font-weight:700;
    text-transform:uppercase; letter-spacing:.07em;
    padding:.2rem .55rem; border-radius:999px; margin-top:.3rem;
  }
  .cw-g4-badge.saudavel{ background:rgba(22,163,74,.12); color:#166534; }
  .cw-g4-badge.alerta{ background:rgba(202,138,4,.12); color:#854d0e; }
  .cw-g4-badge.deficiente{ background:rgba(220,38,38,.12); color:#991b1b; }
  .cw-g4-badge.sem_dados{ background:#f3f4f6; color:#6b7280; }

  /* Alerta badge */
  .cw-alert-dot{
    position:absolute; top:.75rem; right:.75rem;
    background:#dc2626; color:#fff; border-radius:999px;
    font-size:.65rem; font-weight:700; padding:.15rem .45rem;
  }

  /* Sem dados */
  .cw-empty{ text-align:center; padding:3rem 1rem; color:var(--mc-muted); }

  @media(max-width:600px){
    .cw-card{ grid-template-columns:auto 1fr; }
    .cw-right{ display:none; }
    .cw-kpis{ grid-template-columns:1fr 1fr 1fr; }
  }
</style>

{# ── HEADER ── #}
<div class="cw-header">
  <div>
    <h4 class="mb-1">Carteira de Clientes</h4>
    <div class="muted small">Ranqueados do mais crítico ao mais saudável · {{ n_total }} cliente(s)</div>
  </div>
  <div class="d-flex gap-2">
    <a href="/" class="btn btn-outline-secondary btn-sm"><i class="bi bi-arrow-left"></i> Dashboard</a>
    <a href="/client/switch" class="btn btn-outline-primary btn-sm"><i class="bi bi-person-badge"></i> Trocar cliente</a>
  </div>
</div>

{# ── KPIs DA CARTEIRA ── #}
<div class="cw-kpis">
  <div class="cw-kpi">
    <div class="cw-kpi-val">{{ n_total }}</div>
    <div class="cw-kpi-lbl">Total de clientes</div>
  </div>
  <div class="cw-kpi">
    <div class="cw-kpi-val" style="color:#dc2626;">{{ n_deficiente }}</div>
    <div class="cw-kpi-lbl">🔴 Deficiente</div>
  </div>
  <div class="cw-kpi">
    <div class="cw-kpi-val" style="color:#ca8a04;">{{ n_alerta }}</div>
    <div class="cw-kpi-lbl">🟡 Alerta</div>
  </div>
  <div class="cw-kpi">
    <div class="cw-kpi-val" style="color:#16a34a;">{{ n_saudavel }}</div>
    <div class="cw-kpi-lbl">🟢 Saudável</div>
  </div>
  <div class="cw-kpi">
    <div class="cw-kpi-val">{{ score_medio }}</div>
    <div class="cw-kpi-lbl">Score médio</div>
  </div>
  {% if n_alertas_total > 0 %}
  <div class="cw-kpi" style="border-color:rgba(220,38,38,.3);">
    <div class="cw-kpi-val" style="color:#dc2626;">{{ n_alertas_total }}</div>
    <div class="cw-kpi-lbl">Alertas abertos</div>
  </div>
  {% endif %}
  {% if n_sem_dados > 0 %}
  <div class="cw-kpi">
    <div class="cw-kpi-val" style="color:#9ca3af;">{{ n_sem_dados }}</div>
    <div class="cw-kpi-lbl">Sem diagnóstico</div>
  </div>
  {% endif %}
</div>

{# ── FILTROS ── #}
<div class="cw-filter" id="cwFilters">
  <button class="cw-filter-btn active" onclick="cwFilter('todos', this)">Todos ({{ n_total }})</button>
  {% if n_deficiente > 0 %}
  <button class="cw-filter-btn f-deficiente" onclick="cwFilter('deficiente', this)">🔴 Deficiente ({{ n_deficiente }})</button>
  {% endif %}
  {% if n_alerta > 0 %}
  <button class="cw-filter-btn f-alerta" onclick="cwFilter('alerta', this)">🟡 Alerta ({{ n_alerta }})</button>
  {% endif %}
  {% if n_saudavel > 0 %}
  <button class="cw-filter-btn f-saudavel" onclick="cwFilter('saudavel', this)">🟢 Saudável ({{ n_saudavel }})</button>
  {% endif %}
  {% if n_sem_dados > 0 %}
  <button class="cw-filter-btn" onclick="cwFilter('sem_dados', this)">📊 Sem dados ({{ n_sem_dados }})</button>
  {% endif %}
</div>

{# ── RANKING ── #}
{% if carteira %}
  <div id="cwList">
  {% for r in carteira %}
    {% set c = r.client %}
    {% set g4_label = {"saudavel": "Saudável", "alerta": "Alerta", "deficiente": "Deficiente", "sem_dados": "Sem dados"} %}
    <a href="/client/switch?client_id={{ c.id }}&next=/"
       class="cw-card {{ r.g4 }}"
       data-g4="{{ r.g4 }}"
       title="Clique para abrir o dashboard de {{ c.name }}">

      {% if r.alertas > 0 %}
        <span class="cw-alert-dot">{{ r.alertas }} alerta{{ 's' if r.alertas > 1 else '' }}</span>
      {% endif %}

      {# Rank ── posição #}
      <div class="cw-rank {{ r.g4 }}">{{ loop.index }}</div>

      {# Info ── centro #}
      <div>
        <div class="cw-name">{{ c.name }}</div>
        <div class="cw-meta">
          {% if c.cnpj %}<span>{{ c.cnpj }}</span>{% endif %}
          {% if r.snap_date %}
            <span>Último diagn.: {{ r.snap_date.strftime("%d/%m/%Y") }}</span>
            {% if r.dias > 30 %}
              <span style="color:#dc2626;">⚠️ {{ r.dias }}d sem atualizar</span>
            {% endif %}
          {% else %}
            <span style="color:#9ca3af;">Sem diagnóstico</span>
          {% endif %}
          {% if r.revenue > 0 %}
            <span>Fat. {{ r.revenue|brl }}/mês</span>
          {% endif %}
        </div>

        {# Scores individuais #}
        {% if r.snap_date %}
        <div class="cw-scores mt-1">
          <span class="cw-score-chip" style="background:rgba(11,114,133,.08);color:#0b7285;">
            Proc. {{ "%.0f"|format(r.score_process) }}
          </span>
          <span class="cw-score-chip" style="background:rgba(224,112,32,.08);color:#c85f1b;">
            Fin. {{ "%.0f"|format(r.score_fin) }}
          </span>
          {% if r.liq is not none %}
          <span class="cw-score-chip" style="background:{% if r.liq >= 1.5 %}rgba(22,163,74,.08);color:#166534;{% elif r.liq >= 1 %}rgba(202,138,4,.08);color:#854d0e;{% else %}rgba(220,38,38,.08);color:#991b1b;{% endif %}">
            Liq. {{ r.liq }}×
          </span>
          {% endif %}
          {% if r.debt > 0 and r.revenue > 0 %}
          <span class="cw-score-chip" style="background:{% if r.debt_rev <= 1.5 %}rgba(22,163,74,.08);color:#166534;{% elif r.debt_rev <= 3 %}rgba(202,138,4,.08);color:#854d0e;{% else %}rgba(220,38,38,.08);color:#991b1b;{% endif %}">
            Dív/Fat {{ r.debt_rev }}×
          </span>
          {% endif %}
        </div>
        {% endif %}
      </div>

      {# Score ── direita #}
      <div class="cw-right">
        <div class="cw-score-big" style="color:{% if r.score_total >= 65 %}#16a34a{% elif r.score_total >= 50 %}#E07020{% else %}#dc2626{% endif %};">
          {% if r.snap_date %}{{ "%.0f"|format(r.score_total) }}{% else %}—{% endif %}
        </div>
        <div class="cw-g4-badge {{ r.g4 }}">{{ g4_label.get(r.g4, r.g4) }}</div>
      </div>
    </a>
  {% endfor %}
  </div>

  <div id="cwEmpty" class="cw-empty" style="display:none;">
    <i class="bi bi-search" style="font-size:2rem;"></i>
    <div class="mt-2">Nenhum cliente neste filtro.</div>
  </div>

{% else %}
  <div class="cw-empty">
    <i class="bi bi-people" style="font-size:2rem;"></i>
    <div class="mt-2 fw-semibold">Nenhum cliente cadastrado ainda.</div>
  </div>
{% endif %}

<script>
function cwFilter(g4, btn) {
  // Atualiza botões
  document.querySelectorAll('.cw-filter-btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');

  // Filtra cards
  const cards = document.querySelectorAll('.cw-card[data-g4]');
  let visible = 0;
  cards.forEach(card => {
    const show = g4 === 'todos' || card.dataset.g4 === g4;
    card.style.display = show ? '' : 'none';
    if (show) visible++;
  });

  // Atualiza números do ranking visível
  let rank = 1;
  cards.forEach(card => {
    if (card.style.display !== 'none') {
      const rankEl = card.querySelector('.cw-rank');
      if (rankEl) rankEl.textContent = rank++;
    }
  });

  // Mensagem vazia
  document.getElementById('cwEmpty').style.display = visible === 0 ? 'block' : 'none';
}
</script>
{% endblock %}
"""


# ── 3. Injeta link "Carteira" no dashboard para admin/equipe ─────────────────

_tpl_dash = TEMPLATES.get("dashboard.html", "")
_CARTEIRA_LINK = r"""
{# ── SPRINT 5: link carteira ── #}
{% if role in ["admin", "equipe"] %}
<div class="mb-3">
  <a href="/carteira" class="btn btn-outline-secondary btn-sm">
    <i class="bi bi-people-fill me-1"></i> Ver carteira completa
    <span class="badge text-bg-light border ms-1">{{ n_total_clientes or "" }}</span>
  </a>
</div>
{% endif %}
{# ── /SPRINT 5 ── #}
"""

_DASH_ANCHOR = "{# ── SPRINT 3: banner de diagnóstico pendente ── #}"
if _tpl_dash and _DASH_ANCHOR in _tpl_dash and "SPRINT 5: link carteira" not in _tpl_dash:
    TEMPLATES["dashboard.html"] = _tpl_dash.replace(
        _DASH_ANCHOR,
        _CARTEIRA_LINK + "\n" + _DASH_ANCHOR,
        1,
    )

# ── 4. Injeta link Carteira no navbar do base.html ───────────────────────────
# Âncora: href="/logout">Sair — existe no base.html original do app

_base_tpl = TEMPLATES.get("base.html", "")
_NAV_ANCHOR = '<a class="btn btn-outline-secondary btn-sm" href="/logout">Sair</a>'
_CARTEIRA_BTN = (
    '{% if role in ["admin", "equipe"] %}'
    '<a class="btn btn-outline-secondary btn-sm me-1" href="/carteira" title="Carteira de clientes">'
    '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" fill="currentColor" viewBox="0 0 16 16">'
    '<path d="M15 14s1 0 1-1-1-4-5-4-5 3-5 4 1 1 1 1zm-7.978-1L7 12.996c.001-.264.167-1.03.76-1.72C8.312 10.629 9.282 10 11 10c1.717 0 2.687.63 3.24 1.276.593.69.758 1.457.76 1.72l-.008.002-.014.002zM11 7a2 2 0 1 0 0-4 2 2 0 0 0 0 4m3-2a3 3 0 1 1-6 0 3 3 0 0 1 6 0M6.936 9.28a6 6 0 0 0-1.23-.247A7 7 0 0 0 5 9c-4 0-5 3-5 4q0 1 1 1h4.216A2.24 2.24 0 0 1 5 13c0-1.01.377-2.042 1.09-2.904.243-.294.526-.569.846-.816M4.92 10A5.5 5.5 0 0 0 4 13H1c0-.26.164-1.03.76-1.724.545-.636 1.492-1.256 3.16-1.275ZM1.5 5.5a3 3 0 1 1 6 0 3 3 0 0 1-6 0m3-2a2 2 0 1 0 0 4 2 2 0 0 0 0-4"/>'
    '</svg>'
    '</a>'
    '{% endif %}'
    '\n            '
    + _NAV_ANCHOR
)
if _base_tpl and _NAV_ANCHOR in _base_tpl and 'href="/carteira"' not in _base_tpl:
    TEMPLATES["base.html"] = _base_tpl.replace(_NAV_ANCHOR, _CARTEIRA_BTN, 1)

# Atualiza loader
if hasattr(templates_env.loader, "mapping"):
    templates_env.loader.mapping = TEMPLATES

# ============================================================================
# FIM DO PATCH — Sprint 5: Carteira de Clientes
# ============================================================================

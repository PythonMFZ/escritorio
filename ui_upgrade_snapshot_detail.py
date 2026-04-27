# ============================================================================
# PATCH — Tela de resultado do diagnóstico (G4-style)
# ============================================================================
# Cole APÓS todos os patches anteriores no final do app.py.
#
# O QUE FAZ:
#   1. Patch na rota /perfil/avaliacao/{snapshot_id} — injeta business_profile
#      e indicadores calculados no contexto (sem reescrever a rota)
#   2. Novo TEMPLATES["perfil_snapshot_detail.html"] com:
#      - Estrutura de Capital visual (blocos proporcionais Ativo vs Passivo+PL)
#      - Classificação G4: Saudável 🟢 / Alerta 🟡 / Deficiente 🔴
#      - DRE resumida com margem bruta, resultado operacional
#      - Ponto de Equilíbrio estimado
#      - Indicadores de atividade (prazo médio de recebimento, cobertura)
#      - Checklist de processos com score visual
#      - Comparativo com diagnóstico anterior (delta de score)
#      - CTA para nova avaliação
#
# ZERO mudança em rotas, models ou banco.
# ============================================================================


# ── 1. Helper: calcular indicadores completos a partir do snapshot + profile ──

def _build_diagnostico_indicators(snap: Any, profile: Any) -> dict:
    """
    Calcula todos os indicadores financeiros para a tela de resultado.
    Usa dados do ClientSnapshot (receita, dívida, caixa, scores)
    e do ClientBusinessProfile (balanço completo, DRE).
    """
    # Receita e basics
    rev   = float(getattr(snap, "revenue_monthly_brl", 0) or 0)
    debt  = float(getattr(snap, "debt_total_brl", 0) or 0)
    cash  = float(getattr(snap, "cash_balance_brl", 0) or 0)

    # Scores
    s_total   = float(getattr(snap, "score_total", 0) or 0)
    s_process = float(getattr(snap, "score_process", 0) or 0)
    s_fin     = float(getattr(snap, "score_financial", 0) or 0)

    # Balanço do profile (se existir)
    p = profile
    cash_inv  = float(getattr(p, "cash_and_investments_brl", 0) or 0) if p else cash
    recv      = float(getattr(p, "receivables_brl", 0) or 0) if p else 0
    inv       = float(getattr(p, "inventory_brl", 0) or 0) if p else 0
    oca       = float(getattr(p, "other_current_assets_brl", 0) or 0) if p else 0
    imob      = float(getattr(p, "immobilized_brl", 0) or 0) if p else 0
    onca      = float(getattr(p, "other_non_current_assets_brl", 0) or 0) if p else 0
    pay       = float(getattr(p, "payables_360_brl", 0) or 0) if p else 0
    std       = float(getattr(p, "short_term_debt_brl", 0) or 0) if p else 0
    tax_l     = float(getattr(p, "tax_liabilities_brl", 0) or 0) if p else 0
    lab_l     = float(getattr(p, "labor_liabilities_brl", 0) or 0) if p else 0
    ocl       = float(getattr(p, "other_current_liabilities_brl", 0) or 0) if p else 0
    ltd       = float(getattr(p, "long_term_debt_brl", 0) or 0) if p else 0
    oncl      = float(getattr(p, "other_non_current_liabilities_brl", 0) or 0) if p else 0
    collat    = float(getattr(p, "collateral_brl", 0) or 0) if p else 0
    delinq    = float(getattr(p, "delinquency_brl", 0) or 0) if p else 0

    # DRE
    cmv     = float(getattr(p, "monthly_fixed_cost_brl", 0) or 0) if p else 0
    payroll = float(getattr(p, "payroll_monthly_brl", 0) or 0) if p else 0
    opex    = float(getattr(p, "average_ticket_brl", 0) or 0) if p else 0

    # Totais do balanço
    ac  = cash_inv + recv + inv + oca
    anc = imob + onca
    pc  = pay + std + tax_l + lab_l + ocl
    pnc = ltd + oncl
    at  = ac + anc
    pt  = pc + pnc
    pl  = at - pt

    # Se balanço não foi preenchido, usa dados simples do snapshot
    if at == 0 and rev > 0:
        ac  = cash
        anc = 0
        pc  = debt * 0.6  # estimativa: 60% da dívida é CP
        pnc = debt * 0.4
        at  = ac + anc
        pt  = pc + pnc
        pl  = at - pt

    # ── Estrutura de Capital (classificação G4) ────────────────────────────
    # Saudável: PL financia ANC e sobra para AC  → PL > ANC
    # Alerta:   PL + PNC financia ANC e sobra    → PL + PNC > ANC mas PL < ANC
    # Deficiente: PL + PNC < ANC                 → recursos insuficientes para LP
    if at > 0:
        if pl >= anc:
            estrutura = "saudavel"
            estrutura_label = "Saudável"
            estrutura_icon = "✅"
            estrutura_color = "success"
            estrutura_desc = (
                "Recursos próprios financiam todos os ativos de longo prazo "
                "e ainda há sobra para o capital de giro. Empresa bem estruturada."
            )
        elif (pl + pnc) >= anc:
            estrutura = "alerta"
            estrutura_label = "Alerta"
            estrutura_icon = "⚠️"
            estrutura_color = "warning"
            estrutura_desc = (
                "Recursos próprios e dívidas de longo prazo financiam o ativo permanente, "
                "mas a dependência de capital de terceiros exige atenção à alavancagem."
            )
        else:
            estrutura = "deficiente"
            estrutura_label = "Deficiente"
            estrutura_icon = "🔴"
            estrutura_color = "danger"
            estrutura_desc = (
                "Recursos próprios e dívidas de longo prazo são insuficientes para financiar "
                "os ativos permanentes. Parte do capital de giro está financiando ativo fixo — "
                "situação de risco que pressiona o caixa operacional."
            )
    else:
        estrutura = "indefinida"
        estrutura_label = "Sem dados de balanço"
        estrutura_icon = "📊"
        estrutura_color = "secondary"
        estrutura_desc = "Complete o balanço patrimonial no diagnóstico para ver a análise de estrutura de capital."

    # ── Indicadores de liquidez ────────────────────────────────────────────
    liq_corrente  = round(ac / pc, 2) if pc > 0 else None
    liq_seca      = round((ac - inv) / pc, 2) if pc > 0 else None
    ccl           = ac - pc  # Capital de Giro Líquido
    endiv_pl      = round(pt / pl, 2) if pl > 0 else None
    endiv_rev     = round(debt / rev, 2) if rev > 0 else None

    # ── DRE simplificada ──────────────────────────────────────────────────
    mb      = rev - cmv
    mb_pct  = round((mb / rev) * 100, 1) if rev > 0 else 0
    ebitda  = mb - payroll - opex
    ebitda_pct = round((ebitda / rev) * 100, 1) if rev > 0 else 0

    # ── Ponto de Equilíbrio ───────────────────────────────────────────────
    # PE = Gastos Fixos / Taxa de Contribuição
    gastos_fixos = payroll + opex
    taxa_contrib = mb_pct / 100 if mb_pct > 0 else None
    pe_mensal    = round(gastos_fixos / taxa_contrib) if taxa_contrib and taxa_contrib > 0 else None
    margem_seg   = round(((rev - pe_mensal) / rev) * 100, 1) if pe_mensal and rev > 0 and pe_mensal < rev else None

    # ── Prazo médio de recebimento estimado ──────────────────────────────
    pmrv = round((recv / rev) * 30, 0) if rev > 0 and recv > 0 else None

    # ── Proporcionalidade para os blocos visuais ──────────────────────────
    # Usamos % do total para desenhar os blocos proporcionais
    def pct(v, total):
        if total <= 0: return 0
        return max(2, round((v / total) * 100))

    blocos_ativo = {
        "ac": pct(ac, at),
        "anc": pct(anc, at),
    }
    blocos_passivo = {
        "pc":  pct(pc, at),
        "pnc": pct(pnc, at),
        "pl":  pct(max(pl, 0), at),
    }

    # ── Score classificação ───────────────────────────────────────────────
    def score_band(v):
        if v >= 80: return ("Excelente", "success")
        if v >= 65: return ("Bom", "primary")
        if v >= 50: return ("Atenção", "warning")
        return ("Em Risco", "danger")

    return {
        # Balanço
        "ac": ac, "anc": anc, "at": at,
        "pc": pc, "pnc": pnc, "pt": pt, "pl": pl,
        "cash_inv": cash_inv, "recv": recv, "inv": inv,
        "imob": imob, "pay": pay, "std": std,
        "tax_l": tax_l, "lab_l": lab_l, "ltd": ltd,
        "collat": collat, "delinq": delinq,
        # Estrutura G4
        "estrutura": estrutura,
        "estrutura_label": estrutura_label,
        "estrutura_icon": estrutura_icon,
        "estrutura_color": estrutura_color,
        "estrutura_desc": estrutura_desc,
        "blocos_ativo": blocos_ativo,
        "blocos_passivo": blocos_passivo,
        # Liquidez
        "liq_corrente": liq_corrente,
        "liq_seca": liq_seca,
        "ccl": ccl,
        "endiv_pl": endiv_pl,
        "endiv_rev": endiv_rev,
        # DRE
        "rev": rev, "cmv": cmv, "mb": mb, "mb_pct": mb_pct,
        "payroll": payroll, "opex": opex,
        "ebitda": ebitda, "ebitda_pct": ebitda_pct,
        # PE
        "gastos_fixos": gastos_fixos,
        "pe_mensal": pe_mensal,
        "margem_seg": margem_seg,
        "taxa_contrib": round(taxa_contrib * 100, 1) if taxa_contrib else None,
        # Outros
        "pmrv": pmrv,
        "cash": cash, "debt": debt,
        # Scores
        "s_total": s_total, "s_process": s_process, "s_fin": s_fin,
        "s_total_band": score_band(s_total),
        "s_process_band": score_band(s_process),
        "s_fin_band": score_band(s_fin),
    }


# ── 2. Patch no render(): injeta indicadores quando template=snapshot_detail ─

_render_before_snap_detail = render


def render(
    template_name: str,
    *,
    request: Request,
    context: Optional[dict[str, Any]] = None,
    status_code: int = 200,
) -> HTMLResponse:
    ctx = dict(context or {})

    if template_name == "perfil_snapshot_detail.html" and "indicadores" not in ctx:
        snap = ctx.get("snap")
        client = ctx.get("client")
        profile = None
        snap_anterior = None

        if snap and client:
            try:
                with Session(engine) as _db:
                    profile = get_or_create_business_profile(
                        _db,
                        company_id=snap.company_id,
                        client_id=snap.client_id,
                    )
                    # Busca snapshot anterior para delta
                    snap_anterior = _db.exec(
                        select(ClientSnapshot)
                        .where(
                            ClientSnapshot.company_id == snap.company_id,
                            ClientSnapshot.client_id  == snap.client_id,
                            ClientSnapshot.id         != snap.id,
                            ClientSnapshot.created_at < snap.created_at,
                        )
                        .order_by(ClientSnapshot.created_at.desc())
                        .limit(1)
                    ).first()
            except Exception:
                pass

        ctx["indicadores"]      = _build_diagnostico_indicators(snap, profile)
        ctx["business_profile"] = profile
        ctx["snap_anterior"]    = snap_anterior
        if snap_anterior:
            ctx["delta_score"] = round(
                float(snap.score_total or 0) - float(snap_anterior.score_total or 0), 1
            )
        else:
            ctx["delta_score"] = None

    return _render_before_snap_detail(
        template_name,
        request=request,
        context=ctx,
        status_code=status_code,
    )


# ── 3. Novo template da tela de resultado ────────────────────────────────────

TEMPLATES["perfil_snapshot_detail.html"] = r"""
{% extends "base.html" %}
{% block content %}
{% set ind = indicadores or {} %}
{% set snap_date = snap.created_at.strftime("%d/%m/%Y às %H:%M") if snap.created_at else "—" %}

<style>
  /* ── Layout ── */
  .res-header{ display:flex; justify-content:space-between; align-items:flex-start; flex-wrap:wrap; gap:1rem; margin-bottom:1.5rem; }
  .res-back{ font-size:.85rem; }

  /* Score gauge circular */
  .score-ring{
    width:120px; height:120px; border-radius:50%; position:relative;
    display:flex; align-items:center; justify-content:center; flex-shrink:0;
    background:conic-gradient(var(--ring-color,#E07020) 0deg var(--ring-deg,0deg), #edf0f5 var(--ring-deg,0deg) 360deg);
  }
  .score-inner{
    width:82px; height:82px; border-radius:50%; background:#fff;
    display:flex; flex-direction:column; align-items:center; justify-content:center;
    position:absolute;
  }
  .score-num{ font-size:22px; font-weight:700; line-height:1; }
  .score-lbl{ font-size:.65rem; color:var(--mc-muted); }

  /* KPIs topo */
  .kpi-strip{ display:grid; grid-template-columns:repeat(auto-fit,minmax(140px,1fr)); gap:.75rem; margin-bottom:1.5rem; }
  .kpi-box{ background:#fff; border:1px solid var(--mc-border); border-radius:14px; padding:1rem 1.1rem; }
  .kpi-box-label{ font-size:.7rem; font-weight:700; text-transform:uppercase; letter-spacing:.06em; color:var(--mc-muted); }
  .kpi-box-value{ font-size:22px; font-weight:700; letter-spacing:-.02em; margin-top:.25rem; }
  .kpi-box-foot{ font-size:.75rem; margin-top:.2rem; }

  /* ── Estrutura de Capital G4 ── */
  .g4-wrap{ display:grid; grid-template-columns:1fr 1fr; gap:1.5rem; margin-bottom:1.5rem; }
  .g4-col-title{ font-size:.72rem; font-weight:700; text-transform:uppercase; letter-spacing:.07em; color:var(--mc-muted); margin-bottom:.5rem; }
  .g4-stack{ display:flex; flex-direction:column; gap:3px; }
  .g4-block{
    border-radius:8px; display:flex; align-items:center; justify-content:center;
    font-size:.75rem; font-weight:600; color:#fff; transition:all .2s;
    min-height:28px; padding:.3rem .5rem; text-align:center;
  }
  .g4-block.ac { background:#3b82f6; }
  .g4-block.anc{ background:#1e40af; }
  .g4-block.pc { background:#ef4444; }
  .g4-block.pnc{ background:#b91c1c; }
  .g4-block.pl { background:#16a34a; }
  .g4-block.pl.neg { background:#6b7280; }

  .g4-verdict{
    border-radius:14px; padding:1.1rem 1.25rem;
    border:1px solid var(--mc-border); background:#fff;
  }
  .g4-verdict-badge{
    display:inline-flex; align-items:center; gap:.4rem;
    font-size:.75rem; font-weight:700; text-transform:uppercase; letter-spacing:.07em;
    padding:.3rem .75rem; border-radius:999px; margin-bottom:.65rem;
  }
  .g4-verdict-badge.success{ background:rgba(22,163,74,.12); color:#166534; }
  .g4-verdict-badge.warning{ background:rgba(202,138,4,.12); color:#854d0e; }
  .g4-verdict-badge.danger{  background:rgba(220,38,38,.12);  color:#991b1b; }
  .g4-verdict-badge.secondary{ background:#f3f4f6; color:var(--mc-muted); }

  /* ── DRE ── */
  .dre-row{
    display:flex; justify-content:space-between; align-items:center;
    padding:.45rem 0; border-bottom:1px solid var(--mc-border); font-size:.88rem;
  }
  .dre-row:last-child{ border-bottom:0; }
  .dre-row.total{ font-weight:700; background:var(--mc-primary-soft); padding:.55rem .75rem; border-radius:8px; margin-top:.25rem; border-bottom:0; }
  .dre-lbl{ color:var(--mc-text); }
  .dre-sub{ color:var(--mc-muted); font-size:.78rem; margin-left:.5rem; }
  .dre-val{ font-weight:600; }
  .dre-val.pos{ color:var(--mc-success); }
  .dre-val.neg{ color:var(--mc-danger); }
  .dre-val.neu{ color:var(--mc-text); }

  /* ── Indicadores grid ── */
  .ind-grid{ display:grid; grid-template-columns:1fr 1fr; gap:.65rem; }
  .ind-row{
    display:flex; justify-content:space-between; align-items:center;
    padding:.5rem .75rem; border-radius:10px;
    background:#f9fafb; font-size:.85rem;
  }
  .ind-lbl{ color:var(--mc-muted); }
  .ind-val{ font-weight:700; }
  .ind-val.ok  { color:var(--mc-success); }
  .ind-val.warn{ color:#ca8a04; }
  .ind-val.bad { color:var(--mc-danger); }
  .ind-val.neu { color:var(--mc-text); }

  /* ── Checklist ── */
  .chk-section-title{ font-size:.7rem; font-weight:700; text-transform:uppercase; letter-spacing:.07em; color:var(--mc-muted); margin:.85rem 0 .35rem; }
  .chk-item{ display:flex; align-items:center; gap:.75rem; padding:.45rem 0; border-bottom:1px solid var(--mc-border); font-size:.88rem; }
  .chk-item:last-child{ border-bottom:0; }
  .chk-icon{ font-size:1rem; width:20px; text-align:center; flex-shrink:0; }

  /* ── Delta score ── */
  .delta-pill{
    display:inline-flex; align-items:center; gap:.35rem;
    font-size:.8rem; font-weight:600; padding:.25rem .65rem;
    border-radius:999px; border:1px solid var(--mc-border);
  }
  .delta-pill.up  { color:var(--mc-success); border-color:rgba(22,163,74,.25); background:rgba(22,163,74,.07); }
  .delta-pill.down{ color:var(--mc-danger);  border-color:rgba(220,38,38,.25); background:rgba(220,38,38,.07); }
  .delta-pill.flat{ color:var(--mc-muted); }

  /* PE e margem */
  .pe-box{ background:var(--mc-primary-soft); border-radius:12px; padding:1rem 1.1rem; }

  @media(max-width:640px){
    .g4-wrap{ grid-template-columns:1fr; }
    .ind-grid{ grid-template-columns:1fr; }
    .kpi-strip{ grid-template-columns:1fr 1fr; }
  }
</style>

{# ── Helper macro: formata BRL ── #}
{# Usamos filtro brl e brnum já registrados no app #}

{# ── HEADER ── #}
<div class="res-header">
  <div>
    <a href="/perfil" class="btn btn-outline-secondary btn-sm res-back">
      <i class="bi bi-arrow-left"></i> Voltar
    </a>
    <h4 class="mt-2 mb-0">Diagnóstico Financeiro</h4>
    <div class="muted small">
      {{ client.name if client else "—" }} ·
      <span class="mono">{{ snap_date }}</span>
    </div>
  </div>

  {# Score gauge #}
  <div style="text-align:center;">
    <div class="score-ring"
         style="--ring-color:{% if ind.s_total >= 65 %}#16a34a{% elif ind.s_total >= 50 %}#E07020{% else %}#ef4444{% endif %};
                --ring-deg:{{ (ind.s_total / 100 * 360)|round }}deg;">
      <div class="score-inner">
        <div class="score-num">{{ "%.0f"|format(ind.s_total) }}</div>
        <div class="score-lbl">/ 100</div>
      </div>
    </div>
    <div class="mt-1 small fw-semibold">
      <span class="badge text-bg-{{ ind.s_total_band[1] }}">{{ ind.s_total_band[0] }}</span>
    </div>
    {% if delta_score is not none %}
      <div class="mt-1">
        <span class="delta-pill {% if delta_score > 0 %}up{% elif delta_score < 0 %}down{% else %}flat{% endif %}">
          {% if delta_score > 0 %}<i class="bi bi-arrow-up-right"></i> +{{ "%.1f"|format(delta_score) }}
          {% elif delta_score < 0 %}<i class="bi bi-arrow-down-right"></i> {{ "%.1f"|format(delta_score) }}
          {% else %}<i class="bi bi-dash"></i> sem variação{% endif %}
          vs. avaliação anterior
        </span>
      </div>
    {% endif %}
  </div>
</div>

{# ── KPIs RÁPIDOS ── #}
<div class="kpi-strip">
  <div class="kpi-box">
    <div class="kpi-box-label">Score Processos</div>
    <div class="kpi-box-value" style="color:{% if ind.s_process >= 65 %}var(--mc-success){% elif ind.s_process >= 50 %}var(--mc-primary){% else %}var(--mc-danger){% endif %};">
      {{ "%.0f"|format(ind.s_process) }}
    </div>
    <div class="kpi-box-foot"><span class="badge text-bg-{{ ind.s_process_band[1] }}">{{ ind.s_process_band[0] }}</span></div>
  </div>
  <div class="kpi-box">
    <div class="kpi-box-label">Score Financeiro</div>
    <div class="kpi-box-value" style="color:{% if ind.s_fin >= 65 %}var(--mc-success){% elif ind.s_fin >= 50 %}var(--mc-primary){% else %}var(--mc-danger){% endif %};">
      {{ "%.0f"|format(ind.s_fin) }}
    </div>
    <div class="kpi-box-foot"><span class="badge text-bg-{{ ind.s_fin_band[1] }}">{{ ind.s_fin_band[0] }}</span></div>
  </div>
  <div class="kpi-box">
    <div class="kpi-box-label">Faturamento Mensal</div>
    <div class="kpi-box-value">{{ ind.rev|brl }}</div>
    <div class="kpi-box-foot muted">Receita bruta</div>
  </div>
  <div class="kpi-box">
    <div class="kpi-box-label">Capital de Giro Líq.</div>
    <div class="kpi-box-value" style="color:{% if ind.ccl >= 0 %}var(--mc-success){% else %}var(--mc-danger){% endif %};">
      {{ ind.ccl|brl }}
    </div>
    <div class="kpi-box-foot muted">AC − PC</div>
  </div>
  {% if ind.mb_pct %}
  <div class="kpi-box">
    <div class="kpi-box-label">Margem Bruta</div>
    <div class="kpi-box-value" style="color:{% if ind.mb_pct >= 40 %}var(--mc-success){% elif ind.mb_pct >= 20 %}var(--mc-primary){% else %}var(--mc-danger){% endif %};">
      {{ ind.mb_pct }}%
    </div>
    <div class="kpi-box-foot muted">{{ ind.mb|brl }}/mês</div>
  </div>
  {% endif %}
  {% if ind.ebitda_pct %}
  <div class="kpi-box">
    <div class="kpi-box-label">Resultado Operac.</div>
    <div class="kpi-box-value" style="color:{% if ind.ebitda >= 0 %}var(--mc-success){% else %}var(--mc-danger){% endif %};">
      {{ ind.ebitda_pct }}%
    </div>
    <div class="kpi-box-foot muted">{{ ind.ebitda|brl }}/mês</div>
  </div>
  {% endif %}
</div>

{# ── ESTRUTURA DE CAPITAL — Análise G4 ── #}
{% if ind.at > 0 %}
<div class="card p-4 mb-3">
  <h5 class="mb-3">Estrutura de Capital</h5>
  <div class="g4-wrap">

    {# Blocos visuais proporcionais #}
    <div>
      <div style="display:grid; grid-template-columns:1fr 1fr; gap:.75rem;">
        {# Ativo #}
        <div>
          <div class="g4-col-title">O que a empresa tem</div>
          <div class="g4-stack">
            {% if ind.blocos_ativo.ac > 0 %}
            <div class="g4-block ac" style="height:{{ [ind.blocos_ativo.ac * 2, 28]|max }}px;">
              Circulante {{ ind.blocos_ativo.ac }}%
            </div>
            {% endif %}
            {% if ind.blocos_ativo.anc > 0 %}
            <div class="g4-block anc" style="height:{{ [ind.blocos_ativo.anc * 2, 28]|max }}px;">
              Não Circ. {{ ind.blocos_ativo.anc }}%
            </div>
            {% endif %}
          </div>
          <div class="text-center tiny fw-bold mt-1">Total: {{ ind.at|brl }}</div>
        </div>

        {# Passivo + PL #}
        <div>
          <div class="g4-col-title">O que deve + capital próprio</div>
          <div class="g4-stack">
            {% if ind.blocos_passivo.pc > 0 %}
            <div class="g4-block pc" style="height:{{ [ind.blocos_passivo.pc * 2, 28]|max }}px;">
              Pass. Circ. {{ ind.blocos_passivo.pc }}%
            </div>
            {% endif %}
            {% if ind.blocos_passivo.pnc > 0 %}
            <div class="g4-block pnc" style="height:{{ [ind.blocos_passivo.pnc * 2, 28]|max }}px;">
              Pass. LP {{ ind.blocos_passivo.pnc }}%
            </div>
            {% endif %}
            {% if ind.blocos_passivo.pl > 0 %}
            <div class="g4-block pl" style="height:{{ [ind.blocos_passivo.pl * 2, 28]|max }}px;">
              Patr. Líq. {{ ind.blocos_passivo.pl }}%
            </div>
            {% elif ind.pl < 0 %}
            <div class="g4-block pl neg" style="height:28px;">PL Negativo</div>
            {% endif %}
          </div>
          <div class="text-center tiny fw-bold mt-1">Total: {{ ind.at|brl }}</div>
        </div>
      </div>

      {# Legenda #}
      <div class="d-flex flex-wrap gap-2 mt-2" style="font-size:.72rem;">
        <span><span style="display:inline-block;width:10px;height:10px;background:#3b82f6;border-radius:3px;"></span> Ativo Circ.</span>
        <span><span style="display:inline-block;width:10px;height:10px;background:#1e40af;border-radius:3px;"></span> Ativo NC</span>
        <span><span style="display:inline-block;width:10px;height:10px;background:#ef4444;border-radius:3px;"></span> Pass. CP</span>
        <span><span style="display:inline-block;width:10px;height:10px;background:#b91c1c;border-radius:3px;"></span> Pass. LP</span>
        <span><span style="display:inline-block;width:10px;height:10px;background:#16a34a;border-radius:3px;"></span> Patr. Líq.</span>
      </div>
    </div>

    {# Veredicto G4 #}
    <div class="g4-verdict">
      <div class="g4-verdict-badge {{ ind.estrutura_color }}">
        {{ ind.estrutura_icon }} {{ ind.estrutura_label }}
      </div>
      <div style="font-size:.9rem; line-height:1.5;">{{ ind.estrutura_desc }}</div>

      <div style="height:1px; background:var(--mc-border); margin:1rem 0;"></div>

      {# Resumo do balanço #}
      <div class="dre-row">
        <span class="dre-lbl">Ativo Circulante <span class="dre-sub">(recebe em até 1 ano)</span></span>
        <span class="dre-val neu">{{ ind.ac|brl }}</span>
      </div>
      <div class="dre-row">
        <span class="dre-lbl">Ativo Não Circulante <span class="dre-sub">(bens de longo prazo)</span></span>
        <span class="dre-val neu">{{ ind.anc|brl }}</span>
      </div>
      <div class="dre-row">
        <span class="dre-lbl">Passivo Circulante <span class="dre-sub">(vence em até 1 ano)</span></span>
        <span class="dre-val {% if ind.pc > ind.ac %}bad{% else %}neu{% endif %}">{{ ind.pc|brl }}</span>
      </div>
      <div class="dre-row">
        <span class="dre-lbl">Passivo Longo Prazo</span>
        <span class="dre-val neu">{{ ind.pnc|brl }}</span>
      </div>
      <div class="dre-row total">
        <span>Patrimônio Líquido</span>
        <span class="{% if ind.pl >= 0 %}dre-val pos{% else %}dre-val neg{% endif %}">
          {{ ind.pl|brl }}
        </span>
      </div>
    </div>
  </div>
</div>
{% endif %}

{# ── INDICADORES DE LIQUIDEZ E ATIVIDADE ── #}
<div class="card p-4 mb-3">
  <h5 class="mb-3">Indicadores financeiros</h5>
  <div class="ind-grid">

    {% if ind.liq_corrente is not none %}
    <div class="ind-row">
      <span class="ind-lbl">Liquidez Corrente <span class="tiny">(ideal &gt; 1)</span></span>
      <span class="ind-val {% if ind.liq_corrente >= 1.5 %}ok{% elif ind.liq_corrente >= 1 %}warn{% else %}bad{% endif %}">
        {{ ind.liq_corrente }}×
      </span>
    </div>
    {% endif %}

    {% if ind.liq_seca is not none %}
    <div class="ind-row">
      <span class="ind-lbl">Liquidez Seca <span class="tiny">(sem estoque)</span></span>
      <span class="ind-val {% if ind.liq_seca >= 1 %}ok{% elif ind.liq_seca >= 0.7 %}warn{% else %}bad{% endif %}">
        {{ ind.liq_seca }}×
      </span>
    </div>
    {% endif %}

    {% if ind.endiv_rev is not none %}
    <div class="ind-row">
      <span class="ind-lbl">Dívida / Faturamento mensal</span>
      <span class="ind-val {% if ind.endiv_rev <= 1.5 %}ok{% elif ind.endiv_rev <= 3 %}warn{% else %}bad{% endif %}">
        {{ ind.endiv_rev }}×
      </span>
    </div>
    {% endif %}

    {% if ind.endiv_pl is not none %}
    <div class="ind-row">
      <span class="ind-lbl">Endividamento / Patrimônio</span>
      <span class="ind-val {% if ind.endiv_pl <= 1 %}ok{% elif ind.endiv_pl <= 2.5 %}warn{% else %}bad{% endif %}">
        {{ ind.endiv_pl }}×
      </span>
    </div>
    {% endif %}

    {% if ind.pmrv is not none %}
    <div class="ind-row">
      <span class="ind-lbl">Prazo médio de recebimento</span>
      <span class="ind-val {% if ind.pmrv <= 30 %}ok{% elif ind.pmrv <= 60 %}warn{% else %}bad{% endif %}">
        {{ ind.pmrv|int }} dias
      </span>
    </div>
    {% endif %}

    {% if ind.delinq > 0 %}
    <div class="ind-row">
      <span class="ind-lbl">Inadimplência da carteira</span>
      <span class="ind-val {% if ind.delinq / ind.recv <= 0.05 if ind.recv > 0 else True %}ok{% elif ind.delinq / ind.recv <= 0.15 if ind.recv > 0 else True %}warn{% else %}bad{% endif %}">
        {{ ind.delinq|brl }}
      </span>
    </div>
    {% endif %}

    {% if ind.collat > 0 %}
    <div class="ind-row">
      <span class="ind-lbl">Garantias disponíveis</span>
      <span class="ind-val ok">{{ ind.collat|brl }}</span>
    </div>
    {% endif %}

  </div>
</div>

{# ── DRE SIMPLIFICADA ── #}
{% if ind.rev > 0 and (ind.cmv > 0 or ind.payroll > 0) %}
<div class="card p-4 mb-3">
  <h5 class="mb-3">Demonstração de Resultado <span class="badge text-bg-light border fw-normal" style="font-size:.75rem;">DRE mensal estimada</span></h5>

  <div class="dre-row">
    <span class="dre-lbl">Receita bruta mensal</span>
    <span class="dre-val neu">{{ ind.rev|brl }}</span>
  </div>
  {% if ind.cmv > 0 %}
  <div class="dre-row">
    <span class="dre-lbl">(−) Custo do produto/serviço <span class="dre-sub">CMV</span></span>
    <span class="dre-val neg">−{{ ind.cmv|brl }}</span>
  </div>
  {% endif %}
  <div class="dre-row total">
    <span>(=) Margem Bruta</span>
    <span class="{% if ind.mb >= 0 %}dre-val pos{% else %}dre-val neg{% endif %}">
      {{ ind.mb|brl }}
      {% if ind.mb_pct %}<span style="font-weight:400; font-size:.78rem; opacity:.8;">({{ ind.mb_pct }}%)</span>{% endif %}
    </span>
  </div>
  {% if ind.payroll > 0 %}
  <div class="dre-row">
    <span class="dre-lbl">(−) Folha de pagamento</span>
    <span class="dre-val neg">−{{ ind.payroll|brl }}</span>
  </div>
  {% endif %}
  {% if ind.opex > 0 %}
  <div class="dre-row">
    <span class="dre-lbl">(−) Outras despesas fixas</span>
    <span class="dre-val neg">−{{ ind.opex|brl }}</span>
  </div>
  {% endif %}
  {% if ind.payroll > 0 or ind.opex > 0 %}
  <div class="dre-row total">
    <span>(=) Resultado Operacional</span>
    <span class="{% if ind.ebitda >= 0 %}dre-val pos{% else %}dre-val neg{% endif %}">
      {{ ind.ebitda|brl }}
      {% if ind.ebitda_pct %}<span style="font-weight:400; font-size:.78rem; opacity:.8;">({{ ind.ebitda_pct }}%)</span>{% endif %}
    </span>
  </div>
  {% endif %}

  {# Ponto de Equilíbrio #}
  {% if ind.pe_mensal %}
  <div class="pe-box mt-3">
    <div class="fw-semibold small mb-2">📊 Ponto de Equilíbrio mensal</div>
    <div class="row g-2 small">
      <div class="col-6 col-md-3">
        <div class="muted tiny">Ponto de Equilíbrio</div>
        <div class="fw-bold">{{ ind.pe_mensal|brl }}</div>
      </div>
      <div class="col-6 col-md-3">
        <div class="muted tiny">Taxa de Contribuição</div>
        <div class="fw-bold">{{ ind.taxa_contrib }}%</div>
      </div>
      {% if ind.margem_seg is not none %}
      <div class="col-6 col-md-3">
        <div class="muted tiny">Margem de Segurança</div>
        <div class="fw-bold {% if ind.margem_seg >= 20 %}text-success{% elif ind.margem_seg >= 10 %}text-warning{% else %}text-danger{% endif %}">
          {{ ind.margem_seg }}%
        </div>
      </div>
      {% endif %}
      <div class="col-6 col-md-3">
        <div class="muted tiny">Gastos Fixos Totais</div>
        <div class="fw-bold">{{ ind.gastos_fixos|brl }}/mês</div>
      </div>
    </div>
    {% if ind.margem_seg is not none and ind.margem_seg < 15 %}
    <div class="tiny mt-2" style="color:#854d0e;">
      ⚠️ Margem de segurança baixa — qualquer queda de receita acima de {{ ind.margem_seg }}% gera prejuízo.
    </div>
    {% endif %}
  </div>
  {% endif %}
</div>
{% endif %}

{# ── CHECKLIST DE PROCESSOS ── #}
{% if survey and answers %}
<div class="card p-4 mb-3">
  <div class="d-flex justify-content-between align-items-center mb-3">
    <h5 class="mb-0">Checklist de processos</h5>
    <span class="badge text-bg-{{ ind.s_process_band[1] }}">
      Score {{ "%.0f"|format(ind.s_process) }} · {{ ind.s_process_band[0] }}
    </span>
  </div>

  {% set sec = namespace(val="") %}
  {% for q in survey %}
    {% if q.section != sec.val %}
      {% set sec.val = q.section %}
      <div class="chk-section-title">{{ q.section }}</div>
    {% endif %}
    <div class="chk-item">
      {% if answers.get(q.id) %}
        <span class="chk-icon" style="color:var(--mc-success);">✅</span>
      {% else %}
        <span class="chk-icon" style="color:var(--mc-danger);">❌</span>
      {% endif %}
      <span style="{% if not answers.get(q.id) %}color:var(--mc-muted);{% endif %}">{{ q.q }}</span>
    </div>
  {% endfor %}
</div>
{% endif %}

{# ── OBSERVAÇÕES ── #}
{% if snap.notes %}
<div class="card p-4 mb-3">
  <h5 class="mb-2">Observações do diagnóstico</h5>
  <pre class="small" style="white-space:pre-wrap;">{{ snap.notes }}</pre>
</div>
{% endif %}

{# ── CTA FINAL ── #}
<div class="card p-4 mb-3" style="background:linear-gradient(135deg,#fff7f1,#ffede0); border:1px solid rgba(224,112,32,.2);">
  <div class="d-flex flex-wrap justify-content-between align-items-center gap-3">
    <div>
      <div class="fw-semibold">Pronto para o próximo diagnóstico?</div>
      <div class="muted small mt-1">
        Mantendo atualização mensal, a IA detecta tendências e destrava ofertas mais precisas.
      </div>
    </div>
    <div class="d-flex gap-2 flex-wrap">
      <a href="/perfil/avaliacao/nova" class="btn btn-primary">
        <i class="bi bi-clipboard2-pulse me-1"></i> Nova avaliação
      </a>
      <a href="/ofertas" class="btn btn-outline-primary">
        <i class="bi bi-stars me-1"></i> Ver ofertas
      </a>
    </div>
  </div>
</div>

{% endblock %}
"""

if hasattr(templates_env.loader, "mapping"):
    templates_env.loader.mapping = TEMPLATES

# ============================================================================
# FIM DO PATCH — Tela de resultado G4-style
# ============================================================================

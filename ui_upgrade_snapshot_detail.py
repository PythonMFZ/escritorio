# ============================================================================
# ui_upgrade_snapshot_detail.py — v3
# Chama _original_render_delivery3 diretamente (linha 12644 do app.py)
# Zero empilhamento. Uma camada só.
# ============================================================================

def _build_indicators(snap, profile):
    rev   = float(getattr(snap, "revenue_monthly_brl", 0) or 0)
    debt  = float(getattr(snap, "debt_total_brl", 0) or 0)
    cash  = float(getattr(snap, "cash_balance_brl", 0) or 0)
    s_tot = float(getattr(snap, "score_total", 0) or 0)
    s_pro = float(getattr(snap, "score_process", 0) or 0)
    s_fin = float(getattr(snap, "score_financial", 0) or 0)
    p = profile
    def gp(a, fb=0.0): return float(getattr(p, a, fb) or fb) if p else fb
    cash_inv = gp("cash_and_investments_brl", cash)
    recv=gp("receivables_brl"); inv=gp("inventory_brl"); oca=gp("other_current_assets_brl")
    imob=gp("immobilized_brl"); onca=gp("other_non_current_assets_brl")
    pay=gp("payables_360_brl"); std=gp("short_term_debt_brl")
    tax_l=gp("tax_liabilities_brl"); lab_l=gp("labor_liabilities_brl")
    ocl=gp("other_current_liabilities_brl"); ltd=gp("long_term_debt_brl")
    collat=gp("collateral_brl"); delinq=gp("delinquency_brl")
    cmv=gp("monthly_fixed_cost_brl"); payroll=gp("payroll_monthly_brl"); opex=gp("average_ticket_brl")
    ac=cash_inv+recv+inv+oca; anc=imob+onca
    pc=pay+std+tax_l+lab_l+ocl; pnc=ltd
    at=ac+anc; pt=pc+pnc; pl=at-pt
    if at==0 and rev>0:
        ac=cash; pc=debt*0.6; pnc=debt*0.4; at=ac; pt=pc+pnc; pl=at-pt
    if at>0:
        if pl>=anc: est,elbl,eico,ecol,edesc="saudavel","Saudável","✅","success","Recursos próprios financiam todo o ativo permanente e ainda sobra para capital de giro."
        elif (pl+pnc)>=anc: est,elbl,eico,ecol,edesc="alerta","Alerta","⚠️","warning","PL + dívida LP cobrem o ativo fixo, mas dependência de terceiros exige atenção."
        else: est,elbl,eico,ecol,edesc="deficiente","Deficiente","🔴","danger","Recursos insuficientes para o ativo permanente — parte do giro financia ativo fixo."
    else: est,elbl,eico,ecol,edesc="indefinida","Sem dados","📊","secondary","Complete o balanço para ver a análise de estrutura de capital."
    lc=round(ac/pc,2) if pc>0 else None
    ls=round((ac-inv)/pc,2) if pc>0 else None
    ccl=ac-pc; epl=round(pt/pl,2) if pl>0 else None; erev=round(debt/rev,2) if rev>0 else None
    mb=rev-cmv; mb_pct=round((mb/rev)*100,1) if rev>0 else 0
    ebitda=mb-payroll-opex; eb_pct=round((ebitda/rev)*100,1) if rev>0 else 0
    gf=payroll+opex; tc=mb_pct/100 if mb_pct>0 else None
    pe=round(gf/tc) if tc and tc>0 and gf>0 else None
    ms=round(((rev-pe)/rev)*100,1) if pe and rev>0 and pe<rev else None
    pmrv=round((recv/rev)*30,0) if rev>0 and recv>0 else None
    def pct(v,t): return max(2,round((v/t)*100)) if t>0 else 0
    def band(v):
        if v>=80: return("Excelente","success")
        if v>=65: return("Bom","primary")
        if v>=50: return("Atenção","warning")
        return("Em Risco","danger")
    return dict(
        ac=ac,anc=anc,at=at,pc=pc,pnc=pnc,pt=pt,pl=pl,
        recv=recv,inv=inv,imob=imob,collat=collat,delinq=delinq,
        estrutura=est,estrutura_label=elbl,estrutura_icon=eico,
        estrutura_color=ecol,estrutura_desc=edesc,
        blocos_ativo={"ac":pct(ac,at),"anc":pct(anc,at)},
        blocos_passivo={"pc":pct(pc,at),"pnc":pct(pnc,at),"pl":pct(max(pl,0),at)},
        liq_corrente=lc,liq_seca=ls,ccl=ccl,endiv_pl=epl,endiv_rev=erev,
        rev=rev,cmv=cmv,mb=mb,mb_pct=mb_pct,payroll=payroll,opex=opex,
        ebitda=ebitda,ebitda_pct=eb_pct,gastos_fixos=gf,pe_mensal=pe,
        margem_seg=ms,taxa_contrib=round(tc*100,1) if tc else None,
        pmrv=pmrv,cash=cash,debt=debt,
        s_total=s_tot,s_process=s_pro,s_fin=s_fin,
        s_total_band=band(s_tot),s_process_band=band(s_pro),s_fin_band=band(s_fin),
    )


# Aponta direto para o render original (linha 12644) — sem passar pelas camadas
_render_v3_base = _original_render_delivery3  # noqa: F821


def render(
    template_name: str,
    *,
    request,
    context=None,
    status_code: int = 200,
):
    ctx = dict(context or {})

    # Sino global
    ctx.setdefault("smart_alerts_global", [])
    ctx.setdefault("smart_alerts_global_count", 0)
    try:
        _cli = ctx.get("current_client")
        if _cli:
            with Session(engine) as _db:  # noqa
                _t = get_tenant_context(request, _db)  # noqa
                if _t and ensure_can_access_client(_t, _cli.id):  # noqa
                    _al = get_unread_smart_alerts(_db, company_id=_t.company.id, client_id=_cli.id, limit=5)  # noqa
                    ctx["smart_alerts_global"] = _al
                    ctx["smart_alerts_global_count"] = len(_al)
    except Exception:
        pass

    # Dashboard
    if template_name == "dashboard.html":
        if "segment" not in ctx:
            _c = ctx.get("current_client")
            _s = _infer_segment(_c) if _c else "pme"  # noqa
            ctx["segment"] = _s
            ctx["segment_meta"] = _segment_meta(_s)  # noqa
        if "score_evolution" not in ctx:
            _snaps: list = []
            try:
                _c2 = ctx.get("current_client")
                if _c2:
                    with Session(engine) as _db2:  # noqa
                        _t2 = get_tenant_context(request, _db2)  # noqa
                        if _t2 and ensure_can_access_client(_t2, _c2.id):  # noqa
                            _snaps = list(_db2.exec(
                                select(ClientSnapshot)  # noqa
                                .where(ClientSnapshot.company_id == _t2.company.id,  # noqa
                                       ClientSnapshot.client_id == _c2.id)
                                .order_by(ClientSnapshot.created_at.asc()).limit(6)
                            ).all())
            except Exception:
                _snaps = []
            ctx["score_evolution"] = _score_evolution_narrative(_snaps)  # noqa
            ctx["snapshots_count"] = len(_snaps)
        if "diagnostico_banner" not in ctx:
            try:
                _c3 = ctx.get("current_client")
                if _c3:
                    with Session(engine) as _db3:  # noqa
                        _lat = _db3.exec(
                            select(ClientSnapshot).where(ClientSnapshot.client_id == _c3.id)  # noqa
                            .order_by(ClientSnapshot.created_at.desc()).limit(1)
                        ).first()
                        _cut = utcnow() - timedelta(days=30)  # noqa
                        if _lat is None:
                            ctx["diagnostico_banner"] = {"type":"first","msg":"Você ainda não fez o diagnóstico. Leva menos de 5 min.","cta":"Fazer agora","href":"/perfil/avaliacao/nova"}
                        elif _lat.created_at < _cut:
                            ctx["diagnostico_banner"] = {"type":"stale","msg":f"Diagnóstico há {(utcnow()-_lat.created_at).days} dias. Atualize para manter scores precisos.","cta":"Atualizar","href":"/perfil/avaliacao/nova"}  # noqa
                        else:
                            ctx["diagnostico_banner"] = None
            except Exception:
                ctx["diagnostico_banner"] = None

    # Perfil
    if template_name == "perfil.html" and "snapshots" not in ctx:
        try:
            _cp = ctx.get("current_client")
            if _cp:
                with Session(engine) as _dbp:  # noqa
                    _sp = list(_dbp.exec(
                        select(ClientSnapshot).where(ClientSnapshot.client_id == _cp.id)  # noqa
                        .order_by(ClientSnapshot.created_at.desc()).limit(6)
                    ).all())
                    ctx["snapshots"] = _sp
                    ctx["latest_snapshot"] = _sp[0] if _sp else None
        except Exception:
            ctx["snapshots"] = []
            ctx["latest_snapshot"] = None

    # Snapshot detail
    if template_name == "perfil_snapshot_detail.html" and "indicadores" not in ctx:
        _sn = ctx.get("snap")
        _pf = None; _sa = None
        if _sn:
            try:
                with Session(engine) as _dbd:  # noqa
                    _pf = get_or_create_business_profile(_dbd, company_id=_sn.company_id, client_id=_sn.client_id)  # noqa
                    _sa = _dbd.exec(
                        select(ClientSnapshot).where(  # noqa
                            ClientSnapshot.company_id == _sn.company_id,
                            ClientSnapshot.client_id == _sn.client_id,
                            ClientSnapshot.id != _sn.id,
                            ClientSnapshot.created_at < _sn.created_at,
                        ).order_by(ClientSnapshot.created_at.desc()).limit(1)
                    ).first()
            except Exception:
                pass
        ctx["indicadores"] = _build_indicators(_sn, _pf)
        ctx["business_profile"] = _pf
        ctx["snap_anterior"] = _sa
        ctx["delta_score"] = round(float(_sn.score_total or 0)-float(_sa.score_total or 0),1) if _sa and _sn else None

    if hasattr(templates_env.loader, "mapping"):  # noqa
        templates_env.loader.mapping = TEMPLATES  # noqa

    return _render_v3_base(template_name, request=request, context=ctx, status_code=status_code)


TEMPLATES["perfil_snapshot_detail.html"] = r"""
{% extends "base.html" %}
{% block content %}
{% set ind = indicadores or {} %}
{% set snap_date = snap.created_at.strftime("%d/%m/%Y %H:%M") if snap and snap.created_at else "—" %}
<style>
  .res-hdr{display:flex;justify-content:space-between;align-items:flex-start;flex-wrap:wrap;gap:1rem;margin-bottom:1.5rem;}
  .score-ring{width:110px;height:110px;border-radius:50%;position:relative;display:flex;align-items:center;justify-content:center;flex-shrink:0;}
  .score-inner{width:76px;height:76px;border-radius:50%;background:#fff;display:flex;flex-direction:column;align-items:center;justify-content:center;position:absolute;}
  .score-num{font-size:20px;font-weight:700;line-height:1;}
  .score-lbl{font-size:.6rem;color:var(--mc-muted);}
  .kpi-strip{display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:.65rem;margin-bottom:1.25rem;}
  .kpi-box{background:#fff;border:1px solid var(--mc-border);border-radius:14px;padding:.9rem 1rem;}
  .kpi-lbl{font-size:.68rem;font-weight:700;text-transform:uppercase;letter-spacing:.06em;color:var(--mc-muted);}
  .kpi-val{font-size:20px;font-weight:700;letter-spacing:-.02em;margin-top:.2rem;}
  .kpi-ft{font-size:.72rem;margin-top:.15rem;}
  .g4-wrap{display:grid;grid-template-columns:1fr 1fr;gap:1.25rem;margin-bottom:1.25rem;}
  .g4-ct{font-size:.68rem;font-weight:700;text-transform:uppercase;letter-spacing:.07em;color:var(--mc-muted);margin-bottom:.4rem;}
  .g4-stack{display:flex;flex-direction:column;gap:3px;}
  .g4b{border-radius:8px;display:flex;align-items:center;justify-content:center;font-size:.72rem;font-weight:600;color:#fff;min-height:26px;padding:.25rem .4rem;text-align:center;}
  .g4b.ac{background:#3b82f6;}.g4b.anc{background:#1e40af;}.g4b.pc{background:#ef4444;}.g4b.pnc{background:#b91c1c;}.g4b.plok{background:#16a34a;}.g4b.plneg{background:#6b7280;}
  .gv{border-radius:14px;padding:1rem 1.15rem;border:1px solid var(--mc-border);background:#fff;}
  .gb{display:inline-flex;align-items:center;gap:.4rem;font-size:.72rem;font-weight:700;text-transform:uppercase;letter-spacing:.07em;padding:.28rem .65rem;border-radius:999px;margin-bottom:.6rem;}
  .gb.success{background:rgba(22,163,74,.12);color:#166534;}.gb.warning{background:rgba(202,138,4,.12);color:#854d0e;}.gb.danger{background:rgba(220,38,38,.12);color:#991b1b;}.gb.secondary{background:#f3f4f6;color:var(--mc-muted);}
  .dr{display:flex;justify-content:space-between;align-items:center;padding:.4rem 0;border-bottom:1px solid var(--mc-border);font-size:.86rem;}
  .dr:last-child{border-bottom:0;}.dr-tot{font-weight:700;background:var(--mc-primary-soft);padding:.5rem .7rem;border-radius:8px;margin-top:.2rem;border-bottom:0;}
  .dr-sub{color:var(--mc-muted);font-size:.75rem;margin-left:.4rem;}
  .ig{display:grid;grid-template-columns:1fr 1fr;gap:.5rem;}
  .ir{display:flex;justify-content:space-between;align-items:center;padding:.45rem .65rem;border-radius:9px;background:#f9fafb;font-size:.83rem;}
  .il{color:var(--mc-muted);}
  .ok{color:var(--mc-success);font-weight:700;}.warn{color:#ca8a04;font-weight:700;}.bad{color:var(--mc-danger);font-weight:700;}.neu{color:var(--mc-text);font-weight:700;}
  .cs{font-size:.68rem;font-weight:700;text-transform:uppercase;letter-spacing:.07em;color:var(--mc-muted);margin:.8rem 0 .3rem;}
  .ci{display:flex;align-items:center;gap:.65rem;padding:.4rem 0;border-bottom:1px solid var(--mc-border);font-size:.86rem;}.ci:last-child{border-bottom:0;}
  .dp{display:inline-flex;align-items:center;gap:.3rem;font-size:.78rem;font-weight:600;padding:.2rem .6rem;border-radius:999px;border:1px solid var(--mc-border);}
  .dp-up{color:var(--mc-success);border-color:rgba(22,163,74,.25);background:rgba(22,163,74,.07);}
  .dp-dn{color:var(--mc-danger);border-color:rgba(220,38,38,.25);background:rgba(220,38,38,.07);}
  .dp-fl{color:var(--mc-muted);}
  .pe-box{background:var(--mc-primary-soft);border-radius:12px;padding:.9rem 1rem;}
  @media(max-width:640px){.g4-wrap,.ig{grid-template-columns:1fr;}.kpi-strip{grid-template-columns:1fr 1fr;}}
</style>

<div class="res-hdr">
  <div>
    <a href="/perfil" class="btn btn-outline-secondary btn-sm"><i class="bi bi-arrow-left"></i> Voltar</a>
    <h4 class="mt-2 mb-0">Diagnóstico Financeiro</h4>
    <div class="muted small">{{ client.name if client else "—" }} · <span class="mono">{{ snap_date }}</span></div>
  </div>
  <div style="text-align:center;">
    {% set rc = "#16a34a" if ind.s_total >= 65 else ("#E07020" if ind.s_total >= 50 else "#ef4444") %}
    {% set rd = (ind.s_total / 100 * 360)|round|int %}
    <div class="score-ring" style="background:conic-gradient({{ rc }} 0deg {{ rd }}deg,#edf0f5 {{ rd }}deg 360deg);">
      <div class="score-inner">
        <div class="score-num">{{ "%.0f"|format(ind.s_total) }}</div>
        <div class="score-lbl">/ 100</div>
      </div>
    </div>
    <div class="mt-1 small fw-semibold"><span class="badge text-bg-{{ ind.s_total_band[1] }}">{{ ind.s_total_band[0] }}</span></div>
    {% if delta_score is not none %}
      <div class="mt-1">
        {% if delta_score > 0 %}
          <span class="dp dp-up"><i class="bi bi-arrow-up-right"></i> +{{ "%.1f"|format(delta_score) }} vs anterior</span>
        {% elif delta_score < 0 %}
          <span class="dp dp-dn"><i class="bi bi-arrow-down-right"></i> {{ "%.1f"|format(delta_score) }} vs anterior</span>
        {% else %}
          <span class="dp dp-fl"><i class="bi bi-dash"></i> sem variação</span>
        {% endif %}
      </div>
    {% endif %}
  </div>
</div>

<div class="kpi-strip">
  {% set pc2 = "#16a34a" if ind.s_process >= 65 else ("#E07020" if ind.s_process >= 50 else "#ef4444") %}
  {% set fc2 = "#16a34a" if ind.s_fin >= 65 else ("#E07020" if ind.s_fin >= 50 else "#ef4444") %}
  <div class="kpi-box"><div class="kpi-lbl">Score Processos</div><div class="kpi-val" style="color:{{ pc2 }};">{{ "%.0f"|format(ind.s_process) }}</div><div class="kpi-ft"><span class="badge text-bg-{{ ind.s_process_band[1] }}">{{ ind.s_process_band[0] }}</span></div></div>
  <div class="kpi-box"><div class="kpi-lbl">Score Financeiro</div><div class="kpi-val" style="color:{{ fc2 }};">{{ "%.0f"|format(ind.s_fin) }}</div><div class="kpi-ft"><span class="badge text-bg-{{ ind.s_fin_band[1] }}">{{ ind.s_fin_band[0] }}</span></div></div>
  <div class="kpi-box"><div class="kpi-lbl">Faturamento</div><div class="kpi-val">{{ ind.rev|brl }}</div><div class="kpi-ft muted">Receita bruta/mês</div></div>
  {% set cc2 = "#16a34a" if ind.ccl >= 0 else "#ef4444" %}
  <div class="kpi-box"><div class="kpi-lbl">Capital de Giro Líq.</div><div class="kpi-val" style="color:{{ cc2 }};">{{ ind.ccl|brl }}</div><div class="kpi-ft muted">AC − PC</div></div>
  {% if ind.mb_pct %}
  {% set mc3 = "#16a34a" if ind.mb_pct >= 40 else ("#E07020" if ind.mb_pct >= 20 else "#ef4444") %}
  <div class="kpi-box"><div class="kpi-lbl">Margem Bruta</div><div class="kpi-val" style="color:{{ mc3 }};">{{ ind.mb_pct }}%</div><div class="kpi-ft muted">{{ ind.mb|brl }}/mês</div></div>
  {% endif %}
  {% if ind.ebitda_pct %}
  {% set ec3 = "#16a34a" if ind.ebitda >= 0 else "#ef4444" %}
  <div class="kpi-box"><div class="kpi-lbl">Resultado Operac.</div><div class="kpi-val" style="color:{{ ec3 }};">{{ ind.ebitda_pct }}%</div><div class="kpi-ft muted">{{ ind.ebitda|brl }}/mês</div></div>
  {% endif %}
</div>

{% if ind.at > 0 %}
<div class="card p-4 mb-3">
  <h5 class="mb-3">Estrutura de Capital</h5>
  <div class="g4-wrap">
    <div>
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:.65rem;">
        <div>
          <div class="g4-ct">O que a empresa tem</div>
          <div class="g4-stack">
            {% if ind.blocos_ativo.ac > 0 %}<div class="g4b ac" style="height:{{ [ind.blocos_ativo.ac*2,26]|max }}px;">Circ. {{ ind.blocos_ativo.ac }}%</div>{% endif %}
            {% if ind.blocos_ativo.anc > 0 %}<div class="g4b anc" style="height:{{ [ind.blocos_ativo.anc*2,26]|max }}px;">NC {{ ind.blocos_ativo.anc }}%</div>{% endif %}
          </div>
          <div class="text-center tiny fw-bold mt-1">{{ ind.at|brl }}</div>
        </div>
        <div>
          <div class="g4-ct">Deve + capital próprio</div>
          <div class="g4-stack">
            {% if ind.blocos_passivo.pc > 0 %}<div class="g4b pc" style="height:{{ [ind.blocos_passivo.pc*2,26]|max }}px;">CP {{ ind.blocos_passivo.pc }}%</div>{% endif %}
            {% if ind.blocos_passivo.pnc > 0 %}<div class="g4b pnc" style="height:{{ [ind.blocos_passivo.pnc*2,26]|max }}px;">LP {{ ind.blocos_passivo.pnc }}%</div>{% endif %}
            {% if ind.pl >= 0 and ind.blocos_passivo.pl > 0 %}
              <div class="g4b plok" style="height:{{ [ind.blocos_passivo.pl*2,26]|max }}px;">PL {{ ind.blocos_passivo.pl }}%</div>
            {% elif ind.pl < 0 %}
              <div class="g4b plneg" style="height:26px;">PL Negativo</div>
            {% endif %}
          </div>
          <div class="text-center tiny fw-bold mt-1">{{ ind.at|brl }}</div>
        </div>
      </div>
      <div class="d-flex flex-wrap gap-2 mt-2" style="font-size:.7rem;">
        <span><span style="display:inline-block;width:9px;height:9px;background:#3b82f6;border-radius:2px;"></span> Ativo Circ.</span>
        <span><span style="display:inline-block;width:9px;height:9px;background:#1e40af;border-radius:2px;"></span> Ativo NC</span>
        <span><span style="display:inline-block;width:9px;height:9px;background:#ef4444;border-radius:2px;"></span> Pass. CP</span>
        <span><span style="display:inline-block;width:9px;height:9px;background:#b91c1c;border-radius:2px;"></span> Pass. LP</span>
        <span><span style="display:inline-block;width:9px;height:9px;background:#16a34a;border-radius:2px;"></span> PL</span>
      </div>
    </div>
    <div class="gv">
      <div class="gb {{ ind.estrutura_color }}">{{ ind.estrutura_icon }} {{ ind.estrutura_label }}</div>
      <div style="font-size:.88rem;line-height:1.5;">{{ ind.estrutura_desc }}</div>
      <hr class="my-3">
      <div class="dr"><span class="il">Ativo Circulante <span class="dr-sub">(até 1 ano)</span></span><span class="neu">{{ ind.ac|brl }}</span></div>
      <div class="dr"><span class="il">Ativo Não Circulante <span class="dr-sub">(longo prazo)</span></span><span class="neu">{{ ind.anc|brl }}</span></div>
      <div class="dr"><span class="il">Passivo Circulante</span><span style="color:{{ '#ef4444' if ind.pc > ind.ac else 'inherit' }};">{{ ind.pc|brl }}</span></div>
      <div class="dr"><span class="il">Passivo Longo Prazo</span><span class="neu">{{ ind.pnc|brl }}</span></div>
      <div class="dr dr-tot"><span>Patrimônio Líquido</span><span style="color:{{ '#16a34a' if ind.pl >= 0 else '#ef4444' }};">{{ ind.pl|brl }}</span></div>
    </div>
  </div>
</div>
{% endif %}

<div class="card p-4 mb-3">
  <h5 class="mb-3">Indicadores financeiros</h5>
  <div class="ig">
    {% if ind.liq_corrente is not none %}<div class="ir"><span class="il">Liquidez Corrente <span style="font-size:.72rem;">(ideal &gt;1)</span></span><span class="{{ 'ok' if ind.liq_corrente >= 1.5 else ('warn' if ind.liq_corrente >= 1 else 'bad') }}">{{ ind.liq_corrente }}×</span></div>{% endif %}
    {% if ind.liq_seca is not none %}<div class="ir"><span class="il">Liquidez Seca</span><span class="{{ 'ok' if ind.liq_seca >= 1 else ('warn' if ind.liq_seca >= 0.7 else 'bad') }}">{{ ind.liq_seca }}×</span></div>{% endif %}
    {% if ind.endiv_rev is not none %}<div class="ir"><span class="il">Dívida / Faturamento</span><span class="{{ 'ok' if ind.endiv_rev <= 1.5 else ('warn' if ind.endiv_rev <= 3 else 'bad') }}">{{ ind.endiv_rev }}×</span></div>{% endif %}
    {% if ind.endiv_pl is not none %}<div class="ir"><span class="il">Endividamento / PL</span><span class="{{ 'ok' if ind.endiv_pl <= 1 else ('warn' if ind.endiv_pl <= 2.5 else 'bad') }}">{{ ind.endiv_pl }}×</span></div>{% endif %}
    {% if ind.pmrv is not none %}<div class="ir"><span class="il">Prazo médio recebimento</span><span class="{{ 'ok' if ind.pmrv <= 30 else ('warn' if ind.pmrv <= 60 else 'bad') }}">{{ ind.pmrv|int }} dias</span></div>{% endif %}
    {% if ind.collat > 0 %}<div class="ir"><span class="il">Garantias disponíveis</span><span class="ok">{{ ind.collat|brl }}</span></div>{% endif %}
  </div>
</div>

{% if ind.rev > 0 and (ind.cmv > 0 or ind.payroll > 0 or ind.opex > 0) %}
<div class="card p-4 mb-3">
  <h5 class="mb-3">Resultado mensal <span class="badge text-bg-light border fw-normal" style="font-size:.72rem;">DRE simplificada</span></h5>
  <div class="dr"><span class="il">Receita bruta</span><span class="neu">{{ ind.rev|brl }}</span></div>
  {% if ind.cmv > 0 %}<div class="dr"><span class="il">(−) CMV</span><span class="bad">−{{ ind.cmv|brl }}</span></div>{% endif %}
  <div class="dr dr-tot"><span>(=) Margem Bruta</span><span style="color:{{ '#16a34a' if ind.mb >= 0 else '#ef4444' }};">{{ ind.mb|brl }} {% if ind.mb_pct %}<span style="font-weight:400;font-size:.76rem;">({{ ind.mb_pct }}%)</span>{% endif %}</span></div>
  {% if ind.payroll > 0 %}<div class="dr"><span class="il">(−) Folha</span><span class="bad">−{{ ind.payroll|brl }}</span></div>{% endif %}
  {% if ind.opex > 0 %}<div class="dr"><span class="il">(−) Despesas fixas</span><span class="bad">−{{ ind.opex|brl }}</span></div>{% endif %}
  <div class="dr dr-tot"><span>(=) Resultado Operacional</span><span style="color:{{ '#16a34a' if ind.ebitda >= 0 else '#ef4444' }};">{{ ind.ebitda|brl }} {% if ind.ebitda_pct %}<span style="font-weight:400;font-size:.76rem;">({{ ind.ebitda_pct }}%)</span>{% endif %}</span></div>
  {% if ind.pe_mensal %}
  <div class="pe-box mt-3">
    <div class="fw-semibold small mb-2">📊 Ponto de Equilíbrio</div>
    <div class="row g-2 small">
      <div class="col-6 col-md-3"><div class="muted tiny">PE Mensal</div><div class="fw-bold">{{ ind.pe_mensal|brl }}</div></div>
      <div class="col-6 col-md-3"><div class="muted tiny">Taxa de Contribuição</div><div class="fw-bold">{{ ind.taxa_contrib }}%</div></div>
      {% if ind.margem_seg is not none %}<div class="col-6 col-md-3"><div class="muted tiny">Margem de Segurança</div><div class="fw-bold" style="color:{{ '#16a34a' if ind.margem_seg >= 20 else ('#ca8a04' if ind.margem_seg >= 10 else '#ef4444') }};">{{ ind.margem_seg }}%</div></div>{% endif %}
      <div class="col-6 col-md-3"><div class="muted tiny">Gastos Fixos</div><div class="fw-bold">{{ ind.gastos_fixos|brl }}/mês</div></div>
    </div>
  </div>
  {% endif %}
</div>
{% endif %}

{% if survey and answers %}
<div class="card p-4 mb-3">
  <div class="d-flex justify-content-between align-items-center mb-3">
    <h5 class="mb-0">Checklist de processos</h5>
    <span class="badge text-bg-{{ ind.s_process_band[1] }}">{{ "%.0f"|format(ind.s_process) }} · {{ ind.s_process_band[0] }}</span>
  </div>
  {% set sec = namespace(val="") %}
  {% for q in survey %}
    {% if q.section != sec.val %}{% set sec.val = q.section %}<div class="cs">{{ q.section }}</div>{% endif %}
    <div class="ci">
      {% if answers.get(q.id) %}<span style="color:var(--mc-success);">✅</span>{% else %}<span style="color:var(--mc-danger);">❌</span>{% endif %}
      <span style="{{ 'color:var(--mc-muted);' if not answers.get(q.id) else '' }}">{{ q.q }}</span>
    </div>
  {% endfor %}
</div>
{% endif %}

{% if snap and snap.notes %}
<div class="card p-4 mb-3"><h5 class="mb-2">Observações</h5><pre class="small" style="white-space:pre-wrap;">{{ snap.notes }}</pre></div>
{% endif %}

<div class="card p-4 mb-3" style="background:linear-gradient(135deg,#fff7f1,#ffede0);border:1px solid rgba(224,112,32,.2);">
  <div class="d-flex flex-wrap justify-content-between align-items-center gap-3">
    <div><div class="fw-semibold">Pronto para o próximo diagnóstico?</div><div class="muted small mt-1">Atualização mensal mantém scores e ofertas precisos.</div></div>
    <div class="d-flex gap-2">
      <a href="/perfil/avaliacao/nova" class="btn btn-primary"><i class="bi bi-clipboard2-pulse me-1"></i> Nova avaliação</a>
      <a href="/ofertas" class="btn btn-outline-primary"><i class="bi bi-stars me-1"></i> Ver ofertas</a>
    </div>
  </div>
</div>
{% endblock %}
"""

if hasattr(templates_env.loader, "mapping"):  # noqa
    templates_env.loader.mapping = TEMPLATES  # noqa

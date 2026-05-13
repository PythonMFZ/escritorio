# ============================================================================
# Viabilidade — Histórico & Compartilhamento público
# Injetado após ui_viabilidade_v3.py
# ============================================================================

import uuid as _uuid_s
import json as _json_s
import copy as _copy_s
from typing import Optional as _Opt_s
from datetime import datetime as _datetime_s


# ── Modelo ────────────────────────────────────────────────────────────────────

class EstudoViabilidade(SQLModel, table=True):
    __tablename__ = "estudo_viabilidade"
    id: _Opt_s[int] = Field(default=None, primary_key=True)
    company_id: int = Field(index=True)
    nome_projeto: str = Field(default="Sem nome")
    dados_input_json: str = Field(default="{}")           # inputs originais (não escalados)
    resultado_realista_json: str = Field(default="{}")    # compact result para share
    resultado_otimista_json: str = Field(default="{}")
    resultado_pessimista_json: str = Field(default="{}")
    share_token: str = Field(unique=True, index=True, default="")
    criado_em: str = Field(default="")
    criado_por_id: _Opt_s[int] = Field(default=None)

try:
    EstudoViabilidade.__table__.create(engine, checkfirst=True)
except Exception:
    pass


# ── Helpers ───────────────────────────────────────────────────────────────────

def _parse_form_viabilidade(form_data: dict) -> dict:
    """Parse flat form data into structured dados dict (tipologias, fases)."""
    dados = dict(form_data)
    tipologias = []
    i = 0
    while f"tip_nome_{i}" in dados or f"tip_metragem_{i}" in dados:
        met = float(dados.get(f"tip_metragem_{i}", 0) or 0)
        qtd = int(dados.get(f"tip_qtd_{i}", 0) or 0)
        if met > 0 and qtd > 0:
            tipologias.append({
                "nome":         dados.get(f"tip_nome_{i}", ""),
                "tipo":         dados.get(f"tip_tipo_{i}", "Residencial"),
                "metragem":     met,
                "quantidade":   qtd,
                "preco_m2":     float(dados.get(f"tip_preco_{i}", 0) or 0) or float(dados.get("preco_m2_base", 12500)),
                "andar_inicio": int(dados.get(f"tip_andar_{i}", 1) or 1),
                "permuta":      dados.get(f"tip_permuta_{i}") == "1",
            })
        i += 1
    dados["tipologias"] = tipologias
    fases = []
    j = 0
    while f"fase_nome_{j}" in dados:
        fases.append({
            "nome":         dados.get(f"fase_nome_{j}", ""),
            "meta":         float(dados.get(f"fase_meta_{j}", 0) or 0),
            "reajuste":     float(dados.get(f"fase_reajuste_{j}", 0) or 0),
            "duracao":      int(dados.get(f"fase_duracao_{j}", 12) or 12),
            "entrada_pct":  float(dados.get(f"fase_entrada_{j}", 10) or 10),
            "n_entrada":    int(dados.get(f"fase_nentrada_{j}", 1) or 1),
            "parcelas_pct": float(dados.get(f"fase_parcelas_{j}", 80) or 80),
            "n_parcelas":   int(dados.get(f"fase_nparcelas_{j}", 24) or 24),
            "reforco_pct":  float(dados.get(f"fase_reforco_{j}", 0) or 0),
            "n_reforcos":   int(dados.get(f"fase_nreforcos_{j}", 0) or 0),
        })
        j += 1
    if fases:
        dados["fases"] = fases
    return dados


def _calc_cenario_viab(dados_orig: dict, cenario: str) -> dict:
    """Calcula result para um cenário a partir dos inputs originais (não escalados)."""
    d = _copy_s.deepcopy(dados_orig)
    mult = {"otimista": 1.15, "realista": 1.00, "pessimista": 0.85}.get(cenario, 1.00)
    if mult != 1.00:
        preco_orig = float(d.get("preco_m2_base", 12500) or 12500)
        d["preco_m2_base"] = preco_orig * mult
        if d.get("tipologias"):
            for t in d["tipologias"]:
                t["preco_m2"] = float(t.get("preco_m2", preco_orig) or preco_orig) * mult
    d["cenario"] = cenario
    return _calcular_v3(d)


def _compact_result(r: dict) -> dict:
    """Extrai apenas os campos necessários para a share page (sem fluxo completo)."""
    fin = r.get("financiamento") or {}
    return {
        "cenario":          r.get("cenario"),
        "resultado_bruto":  r.get("resultado_bruto"),
        "margem_vgv":       r.get("margem_vgv"),
        "margem_custo":     r.get("margem_custo"),
        "tir_anual":        r.get("tir_anual"),
        "vpl":              r.get("vpl"),
        "vf_resultado":     r.get("vf_resultado"),
        "vf_margem_vgv":    r.get("vf_margem_vgv"),
        "vf_margem_custo":  r.get("vf_margem_custo"),
        "tir_vf_anual":     r.get("tir_vf_anual"),
        "vpl_vf":           r.get("vpl_vf"),
        "exposicao_maxima": r.get("exposicao_maxima"),
        "vgv_bruto":        r.get("vgv_bruto"),
        "vgv_liquido":      r.get("vgv_liquido"),
        "custo_total":      r.get("custo_total"),
        "status":           r.get("status"),
        "dre":              r.get("dre", []),
        "chart_labels":     r.get("chart_labels", []),
        "chart_pag":        r.get("chart_pag", []),
        "chart_rec":        r.get("chart_rec", []),
        "chart_exp":        r.get("chart_exp", []),
        "vp_receitas":  r.get("vp_receitas"),
        "vp_custos":    r.get("vp_custos"),
        "dre_vf":       r.get("dre_vf", []),
        # Custos e Despesas tab
        "custo_obra_total":  r.get("custo_obra_total"),
        "custo_cub":         r.get("custo_cub"),
        "itens_extra":       r.get("itens_extra"),
        "custo_indiretos":   r.get("custo_indiretos"),
        "valor_terreno":     r.get("valor_terreno"),
        "custo_comercial":   r.get("custo_comercial"),
        "custo_impostos":    r.get("custo_impostos"),
        "vf_custo_obra":     r.get("vf_custo_obra"),
        "vf_custo_total":    r.get("vf_custo_total"),
        "vf_vgv":            r.get("vf_vgv"),
        # Produto tab
        "unidades_total":    r.get("unidades_total"),
        "unidades_permuta":  r.get("unidades_permuta"),
        "area_privativa":    r.get("area_privativa"),
        "vgv_medio_m2":      r.get("vgv_medio_m2"),
        "valor_permuta":     r.get("valor_permuta"),
        # Sensibilidade
        "sensibilidade":     r.get("sensibilidade"),
        "indicadores_adicionais": r.get("indicadores_adicionais"),
        "financiamento": {
            "valor_financiado":  fin.get("valor_financiado"),
            "custo_fin_total":   fin.get("custo_fin_total"),
            "resultado_sem_fin": fin.get("resultado_sem_fin"),
            "resultado_com_fin": fin.get("resultado_com_fin"),
            "margem_sem_fin":    fin.get("margem_sem_fin"),
            "margem_com_fin":    fin.get("margem_com_fin"),
            "exposicao_com_fin": fin.get("exposicao_com_fin"),
            "reducao_exposicao": fin.get("reducao_exposicao"),
            "tir_alavancada":    fin.get("tir_alavancada"),
            "roe":               fin.get("roe"),
            "tipo_amortizacao":  fin.get("tipo_amortizacao"),
            "pct_fin":           fin.get("pct_fin"),
            "taxa_am":           fin.get("taxa_am"),
            "vpl_alavancado":    fin.get("vpl_alavancado"),
            "vpl_sem_fin_calc":  fin.get("vpl_sem_fin_calc"),
            "delta_vpl":         fin.get("delta_vpl"),
        } if fin else None,
    }


# ── Rota: salvar ──────────────────────────────────────────────────────────────

app.router.routes = [r for r in app.router.routes if not (
    hasattr(r, "path") and r.path == "/ferramentas/viabilidade/salvar"
)]

@app.post("/ferramentas/viabilidade/salvar")
@require_login
async def viabilidade_salvar_v1(
    request: Request, session: Session = Depends(get_session)
):
    from fastapi.responses import JSONResponse as _JRS
    ctx = get_tenant_context(request, session)
    if not ctx:
        return _JRS({"ok": False, "error": "Não autorizado"}, status_code=401)
    form = await request.form()
    dados = _parse_form_viabilidade(dict(form))
    nome_projeto = (dados.get("nome_projeto") or "Sem nome").strip() or "Sem nome"
    try:
        r_real = _calc_cenario_viab(dados, "realista")
        r_otim = _calc_cenario_viab(dados, "otimista")
        r_pess = _calc_cenario_viab(dados, "pessimista")
    except Exception as ex:
        return _JRS({"ok": False, "error": f"Erro no cálculo: {ex}"})
    token = str(_uuid_s.uuid4())
    estudo = EstudoViabilidade(
        company_id=ctx.company.id,
        nome_projeto=nome_projeto,
        dados_input_json=_json_s.dumps(dados, default=str),
        resultado_realista_json=_json_s.dumps(_compact_result(r_real), default=str),
        resultado_otimista_json=_json_s.dumps(_compact_result(r_otim), default=str),
        resultado_pessimista_json=_json_s.dumps(_compact_result(r_pess), default=str),
        share_token=token,
        criado_em=_datetime_s.utcnow().isoformat(),
        criado_por_id=getattr(ctx.user, "id", None),
    )
    session.add(estudo)
    session.commit()
    session.refresh(estudo)
    return _JRS({"ok": True, "id": estudo.id, "token": token, "url": f"/viabilidade/share/{token}"})


# ── Rota: histórico ───────────────────────────────────────────────────────────

app.router.routes = [r for r in app.router.routes if not (
    hasattr(r, "path") and r.path == "/ferramentas/viabilidade/historico"
)]

@app.get("/ferramentas/viabilidade/historico")
@require_login
async def viabilidade_historico_v1(
    request: Request, session: Session = Depends(get_session)
):
    from fastapi.responses import JSONResponse as _JRS
    ctx = get_tenant_context(request, session)
    if not ctx:
        return _JRS({"estudos": []})
    estudos = session.exec(
        select(EstudoViabilidade)
        .where(EstudoViabilidade.company_id == ctx.company.id)
        .order_by(EstudoViabilidade.id.desc())
        .limit(50)
    ).all()
    result = []
    for e in estudos:
        try:
            r = _json_s.loads(e.resultado_realista_json)
            margem = r.get("margem_vgv") or 0
        except Exception:
            margem = 0
        try:
            dt = _datetime_s.fromisoformat(e.criado_em)
            dt_fmt = dt.strftime("%d/%m/%Y %H:%M")
        except Exception:
            dt_fmt = (e.criado_em or "")[:10] or "—"
        result.append({
            "id":           e.id,
            "nome_projeto": e.nome_projeto,
            "criado_em_fmt":dt_fmt,
            "margem_vgv":   round(float(margem), 1),
            "share_url":    f"/viabilidade/share/{e.share_token}",
            "open_url":     f"/ferramentas/viabilidade/abrir/{e.id}",
        })
    return _JRS({"estudos": result})


# ── Rota: excluir estudo ──────────────────────────────────────────────────────

app.router.routes = [r for r in app.router.routes if not (
    hasattr(r, "path") and r.path == "/ferramentas/viabilidade/historico/{estudo_id}"
)]

@app.delete("/ferramentas/viabilidade/historico/{estudo_id}")
@require_login
async def viabilidade_excluir_v1(
    estudo_id: int,
    request: Request, session: Session = Depends(get_session)
):
    from fastapi.responses import JSONResponse as _JRS
    ctx = get_tenant_context(request, session)
    if not ctx:
        return _JRS({"ok": False, "erro": "Não autenticado"}, status_code=401)
    estudo = session.get(EstudoViabilidade, estudo_id)
    if not estudo or estudo.company_id != ctx.company.id:
        return _JRS({"ok": False, "erro": "Não encontrado"}, status_code=404)
    session.delete(estudo)
    session.commit()
    return _JRS({"ok": True})


# ── Rota: reabrir ─────────────────────────────────────────────────────────────

app.router.routes = [r for r in app.router.routes if not (
    hasattr(r, "path") and r.path == "/ferramentas/viabilidade/abrir/{estudo_id}"
)]

@app.get("/ferramentas/viabilidade/abrir/{estudo_id}", response_class=HTMLResponse)
@require_login
async def viabilidade_abrir_v1(
    estudo_id: int,
    request: Request, session: Session = Depends(get_session)
):
    ctx = get_tenant_context(request, session)
    if not ctx:
        request.session.clear()
        return RedirectResponse("/login", status_code=303)
    estudo = session.get(EstudoViabilidade, estudo_id)
    if not estudo or estudo.company_id != ctx.company.id:
        return RedirectResponse("/ferramentas/viabilidade", status_code=303)
    cc = get_client_or_none(session, ctx.company.id, get_active_client_id(request, session, ctx))
    try:
        dados = _json_s.loads(estudo.dados_input_json)
        dados["cenario"] = "realista"
        resultado = _calc_cenario_viab(dados, "realista")
    except Exception:
        return RedirectResponse("/ferramentas/viabilidade", status_code=303)
    return render("ferramenta_viabilidade.html", request=request, context={
        "current_user":    ctx.user,
        "current_company": ctx.company,
        "role":            ctx.membership.role,
        "current_client":  cc,
        "resultado":       resultado,
        "dados":           dados,
        "share_token":     estudo.share_token,
    })


# ── Rota pública: share ───────────────────────────────────────────────────────

app.router.routes = [r for r in app.router.routes if not (
    hasattr(r, "path") and r.path == "/viabilidade/share/{token}"
)]

@app.get("/viabilidade/share/{token}", response_class=HTMLResponse)
async def viabilidade_share_publico(
    token: str, session: Session = Depends(get_session)
):
    estudo = session.exec(
        select(EstudoViabilidade).where(EstudoViabilidade.share_token == token)
    ).first()
    if not estudo:
        return HTMLResponse("<html><body style='font-family:sans-serif;padding:3rem;text-align:center'>"
                            "<h2>Estudo não encontrado</h2><p>O link pode ter expirado ou ser inválido.</p></body></html>",
                            status_code=404)
    try:
        r_real = _json_s.loads(estudo.resultado_realista_json)
        r_otim = _json_s.loads(estudo.resultado_otimista_json)
        r_pess = _json_s.loads(estudo.resultado_pessimista_json)
    except Exception:
        return HTMLResponse("<html><body>Erro ao carregar estudo.</body></html>", status_code=500)
    tem_fin = bool(r_real.get("financiamento"))
    try:
        dt = _datetime_s.fromisoformat(estudo.criado_em)
        dt_fmt = dt.strftime("%d/%m/%Y")
    except Exception:
        dt_fmt = "—"
    cenarios_json = _json_s.dumps({"realista": r_real, "otimista": r_otim, "pessimista": r_pess}, default=str)
    try:
        dados_input = _json_s.loads(estudo.dados_input_json)
    except Exception:
        dados_input = {}
    fases_share = dados_input.get("fases") or []
    corr_obra_share     = float(dados_input.get("correcao_obra", 0.52) or 0.52)
    corr_pos_obra_share = float(dados_input.get("correcao_pos_obra", 1.04) or 1.04)
    html = templates_env.from_string(TEMPLATES["viabilidade_share.html"]).render(
        nome_projeto=estudo.nome_projeto,
        data=dt_fmt,
        tem_fin=tem_fin,
        cenarios_json=cenarios_json,
        fases=fases_share,
        corr_obra=corr_obra_share,
        corr_pos_obra=corr_pos_obra_share,
    )
    return HTMLResponse(html)


# ── Template: página pública de compartilhamento ──────────────────────────────

TEMPLATES["viabilidade_share.html"] = """<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{{ nome_projeto }} | Viabilidade Imobiliária — Maffezzolli Capital</title>
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11/font/bootstrap-icons.min.css">
<script src="https://cdn.jsdelivr.net/npm/chart.js@4/dist/chart.umd.min.js"></script>
<style>
*{box-sizing:border-box;margin:0;padding:0;}
body{font-family:-apple-system,BlinkMacSystemFont,'Inter','Segoe UI',sans-serif;background:#f8fafc;color:#1e293b;}
.sp-header{background:linear-gradient(135deg,#ea580c 0%,#f97316 100%);color:#fff;padding:1.5rem 2rem;}
.sp-logo{font-size:.78rem;font-weight:700;text-transform:uppercase;letter-spacing:.12em;opacity:.85;margin-bottom:.35rem;}
.sp-title{font-size:1.5rem;font-weight:800;letter-spacing:-.02em;}
.sp-meta{font-size:.78rem;opacity:.72;margin-top:.3rem;}
.sp-body{max-width:1100px;margin:0 auto;padding:1.5rem 1.25rem;}
.sp-controls{display:flex;gap:1rem;flex-wrap:wrap;margin-bottom:1.5rem;align-items:flex-end;}
.sp-ctrl-group{display:flex;flex-direction:column;gap:.4rem;}
.sp-ctrl-lbl{font-size:.68rem;font-weight:700;text-transform:uppercase;letter-spacing:.07em;color:#94a3b8;}
.sp-cg{display:flex;gap:.35rem;flex-wrap:wrap;}
.sp-cb{padding:.42rem 1rem;border:2px solid #e2e8f0;border-radius:999px;background:#fff;font-size:.82rem;font-weight:700;cursor:pointer;transition:all .15s;}
.sp-cb:hover{border-color:#f97316;color:#f97316;}
.sp-cb.cn-realista{background:#f97316;color:#fff;border-color:#f97316;}
.sp-cb.cn-otimista{background:#22c55e;color:#fff;border-color:#22c55e;}
.sp-cb.cn-pessimista{background:#dc2626;color:#fff;border-color:#dc2626;}
.sp-fb{padding:.42rem .9rem;border:2px solid #e2e8f0;border-radius:999px;background:#fff;font-size:.8rem;font-weight:600;cursor:pointer;transition:all .15s;}
.sp-fb:hover{border-color:#1e40af;color:#1e40af;}
.sp-fb.on{background:#1e40af;color:#fff;border-color:#1e40af;}
.sp-kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(195px,1fr));gap:.85rem;margin-bottom:1.5rem;}
.sp-kpi{background:#fff;border:1px solid #e2e8f0;border-radius:14px;padding:1.1rem 1.25rem;box-shadow:0 2px 6px rgba(0,0,0,.05);}
.sp-kpi-l{font-size:.65rem;font-weight:700;text-transform:uppercase;letter-spacing:.07em;color:#94a3b8;margin-bottom:.3rem;}
.sp-kpi-v{font-size:1.3rem;font-weight:700;letter-spacing:-.02em;line-height:1.2;}
.sp-kpi-s{font-size:.7rem;color:#94a3b8;margin-top:.2rem;}
.sp-grid{display:grid;grid-template-columns:1fr 1fr;gap:1.25rem;margin-bottom:1.5rem;}
@media(max-width:720px){.sp-grid{grid-template-columns:1fr;}}
.sp-card{background:#fff;border:1px solid #e2e8f0;border-radius:14px;padding:1.25rem;}
.sp-card h6{font-size:.76rem;font-weight:700;text-transform:uppercase;letter-spacing:.06em;color:#f97316;margin-bottom:.85rem;}
.dre-t{width:100%;border-collapse:collapse;font-size:.83rem;}
.dre-t td{padding:.4rem .65rem;border-bottom:1px solid #f1f5f9;}
.dre-row-subtotal td{background:#fff7ed;font-weight:700;color:#f97316;}
.dre-row-resultado td{background:#f97316;color:#fff;font-weight:700;}
.dre-row-pct td{background:#fff7ed;font-style:italic;color:#ea580c;}
.dre-row-receita td{font-weight:600;}
.dre-row-deducao td{color:#475569;}
.dre-val{text-align:right;font-variant-numeric:tabular-nums;}
.sp-fin{background:#eff6ff;border:2px solid #bfdbfe;border-radius:14px;padding:1.1rem 1.25rem;margin-bottom:1.5rem;}
.sp-fin h6{font-size:.76rem;font-weight:700;text-transform:uppercase;letter-spacing:.06em;color:#1e40af;margin-bottom:.85rem;}
.fin-cmp{display:grid;grid-template-columns:1fr auto 1fr;gap:.75rem;align-items:start;}
.fin-row{display:flex;justify-content:space-between;font-size:.84rem;padding:.18rem 0;}
.fin-lbl{color:#64748b;}
.fin-val{font-weight:700;}
.sp-footer{text-align:center;padding:2rem 1rem;font-size:.73rem;color:#94a3b8;border-top:1px solid #e2e8f0;margin-top:1rem;}
.sp-rtab{padding:.45rem .9rem;border:none;background:none;font-size:.82rem;font-weight:600;color:#64748b;cursor:pointer;border-bottom:2px solid transparent;margin-bottom:-2px;white-space:nowrap;transition:all .15s;}
.sp-rtab:hover{color:#f97316;}
.sp-rtab.on{color:#f97316;border-bottom-color:#f97316;}
.sp-sec{display:none;}.sp-sec.on{display:block;}
.sen-t{width:100%;border-collapse:collapse;font-size:.78rem;}
.sen-t th{background:#1e293b;color:#fff;padding:.4rem .6rem;text-align:center;font-size:.7rem;}
.sen-t td{padding:.35rem .6rem;text-align:center;border-bottom:1px solid #e2e8f0;}
.bk-row{display:flex;justify-content:space-between;padding:.42rem .75rem;font-size:.84rem;border-bottom:1px solid #f1f5f9;}
.bk-lbl{color:#64748b;}
.sp-badge{display:inline-flex;align-items:center;gap:.3rem;padding:.25rem .7rem;border-radius:999px;font-size:.73rem;font-weight:700;margin-bottom:.85rem;}
.badge-r{background:rgba(249,115,22,.1);color:#f97316;border:1px solid rgba(249,115,22,.2);}
.badge-o{background:rgba(22,163,74,.1);color:#16a34a;border:1px solid rgba(22,163,74,.2);}
.badge-p{background:rgba(220,38,38,.1);color:#dc2626;border:1px solid rgba(220,38,38,.2);}
</style>
</head>
<body>
<div class="sp-header">
  <div class="sp-logo"><i class="bi bi-building-fill me-1"></i>Maffezzolli Capital &nbsp;·&nbsp; Viabilidade Imobiliária</div>
  <div class="sp-title">{{ nome_projeto }}</div>
  <div class="sp-meta">Gerado em {{ data }} &nbsp;·&nbsp; Documento confidencial &nbsp;·&nbsp; Não constitui oferta ou garantia de retorno</div>
</div>

<div class="sp-body">
  <div class="sp-controls">
    <div class="sp-ctrl-group">
      <div class="sp-ctrl-lbl">Cenário de análise</div>
      <div class="sp-cg">
        <button class="sp-cb cn-realista" id="cn-realista" onclick="setCenario('realista')"><i class="bi bi-dash me-1"></i>Realista</button>
        <button class="sp-cb" id="cn-otimista" onclick="setCenario('otimista')"><i class="bi bi-arrow-up-right me-1"></i>Otimista +15%</button>
        <button class="sp-cb" id="cn-pessimista" onclick="setCenario('pessimista')"><i class="bi bi-arrow-down-right me-1"></i>Pessimista −15%</button>
      </div>
    </div>
    {% if tem_fin %}
    <div class="sp-ctrl-group">
      <div class="sp-ctrl-lbl">Financiamento de obra</div>
      <div class="sp-cg">
        <button class="sp-fb" id="fin-btn-sem" onclick="setFin(false)"><i class="bi bi-x-circle me-1"></i>Sem financiamento</button>
        <button class="sp-fb on" id="fin-btn-com" onclick="setFin(true)"><i class="bi bi-bank2 me-1"></i>Com financiamento</button>
      </div>
    </div>
    {% endif %}
  </div>

  <div id="sp-status-bar"></div>

  <div style="font-size:.65rem;font-weight:700;text-transform:uppercase;letter-spacing:.08em;color:#94a3b8;margin-bottom:.4rem;">Valor Final — corrigido pelo índice configurado / CUB</div>
  <div class="sp-kpis">
    <div class="sp-kpi">
      <div class="sp-kpi-l"><i class="bi bi-graph-up-arrow me-1"></i>Resultado VF</div>
      <div class="sp-kpi-v" id="kpi-resultado">—</div>
      <div class="sp-kpi-s" id="kpi-resultado-sub"></div>
    </div>
    <div class="sp-kpi">
      <div class="sp-kpi-l"><i class="bi bi-percent me-1"></i>Margem VF</div>
      <div class="sp-kpi-v" id="kpi-margem">—</div>
      <div class="sp-kpi-s" id="kpi-margem-sub">Sobre VGV corrigido</div>
    </div>
    <div class="sp-kpi">
      <div class="sp-kpi-l"><i class="bi bi-bar-chart-line me-1"></i>TIR VF</div>
      <div class="sp-kpi-v" id="kpi-tir">—</div>
      <div class="sp-kpi-s" id="kpi-tir-sub">Retorno (Corrigido)</div>
    </div>
    <div class="sp-kpi">
      <div class="sp-kpi-l"><i class="bi bi-arrow-down-circle me-1"></i>Exposição Máxima</div>
      <div class="sp-kpi-v" id="kpi-exposicao" style="color:#dc2626;">—</div>
      <div class="sp-kpi-s">Capital necessário no pico</div>
    </div>
  </div>

  {# ── ABAS ── #}
  <div style="display:flex;gap:.2rem;border-bottom:2px solid #e2e8f0;margin-bottom:1.25rem;flex-wrap:wrap;overflow-x:auto;">
    <button class="sp-rtab on" id="sptab-btn-indicadores" onclick="spTab('indicadores',this)"><i class="bi bi-table me-1"></i>Indicadores / DRE</button>
    <button class="sp-rtab" id="sptab-btn-fluxo"       onclick="spTab('fluxo',this)"><i class="bi bi-activity me-1"></i>Fluxo de Caixa</button>
    <button class="sp-rtab" id="sptab-btn-custos"      onclick="spTab('custos',this)"><i class="bi bi-hammer me-1"></i>Custos</button>
    <button class="sp-rtab" id="sptab-btn-comercial"   onclick="spTab('comercial',this)"><i class="bi bi-tags me-1"></i>Comercialização</button>
    <button class="sp-rtab" id="sptab-btn-sensib"      onclick="spTab('sensib',this)"><i class="bi bi-grid-3x3 me-1"></i>Sensibilidade</button>
  </div>

  {# ── ABA 1: Indicadores / DRE ── #}
  <div class="sp-sec on" id="sptab-indicadores">
    <div class="sp-grid">
      <div class="sp-card">
        <h6><i class="bi bi-receipt me-1"></i>DRE VP — Projeção Nominal</h6>
        <table class="dre-t"><tbody id="dre-body"></tbody></table>
      </div>
      <div class="sp-card">
        <h6 style="color:#ea580c;"><i class="bi bi-receipt-cutoff me-1"></i>DRE VF — Valor Final</h6>
        <table class="dre-t"><tbody id="dre-vf-body"></tbody></table>
      </div>
    </div>

    {% if tem_fin %}
    <div class="sp-fin">
      <h6><i class="bi bi-bank2 me-1"></i>Impacto do Financiamento — Antes vs. Depois</h6>
      <div class="fin-cmp">
        <div>
          <div style="font-size:.68rem;font-weight:700;text-transform:uppercase;color:#64748b;margin-bottom:.5rem;">Sem Financiamento</div>
          <div class="fin-row"><span class="fin-lbl">Resultado</span><span class="fin-val" id="fin-sem-res">—</span></div>
          <div class="fin-row"><span class="fin-lbl">Margem VGV</span><span class="fin-val" id="fin-sem-mg">—</span></div>
          <div class="fin-row"><span class="fin-lbl">TIR</span><span class="fin-val" id="fin-sem-tir">—</span></div>
          <div class="fin-row"><span class="fin-lbl">Exposição</span><span class="fin-val" id="fin-sem-exp" style="color:#dc2626;">—</span></div>
        </div>
        <div style="display:flex;align-items:center;padding:0 .5rem;"><i class="bi bi-arrow-right" style="font-size:1.3rem;color:#94a3b8;"></i></div>
        <div>
          <div style="font-size:.68rem;font-weight:700;text-transform:uppercase;color:#1e40af;margin-bottom:.5rem;">Com Financiamento</div>
          <div class="fin-row"><span class="fin-lbl">Resultado</span><span class="fin-val" id="fin-com-res">—</span></div>
          <div class="fin-row"><span class="fin-lbl">Margem VGV</span><span class="fin-val" id="fin-com-mg">—</span></div>
          <div class="fin-row"><span class="fin-lbl">TIR alavancada</span><span class="fin-val" id="fin-com-tir" style="color:#6366f1;">—</span></div>
          <div class="fin-row"><span class="fin-lbl">Exposição</span><span class="fin-val" id="fin-com-exp" style="color:#16a34a;">—</span></div>
        </div>
      </div>
      <div style="margin-top:.85rem;padding-top:.75rem;border-top:1px solid #bfdbfe;font-size:.78rem;color:#475569;" id="fin-costs-row"></div>
    </div>
    {% endif %}
  </div>

  {# ── ABA 2: Fluxo de Caixa ── #}
  <div class="sp-sec" id="sptab-fluxo">
    <div class="sp-card">
      <h6><i class="bi bi-activity me-1"></i>Fluxo de Caixa</h6>
      <canvas id="chartFluxo" style="max-height:380px;"></canvas>
    </div>
  </div>

  {# ── ABA 3: Custos e Despesas ── #}
  <div class="sp-sec" id="sptab-custos">
    <div class="sp-grid" style="margin-bottom:1.25rem;">
      <div class="sp-card">
        <h6><i class="bi bi-hammer me-1"></i>Custos VP (nominal)</h6>
        <div id="custos-vp-body"></div>
      </div>
      <div class="sp-card">
        <h6 style="color:#ea580c;"><i class="bi bi-hammer me-1"></i>Custos VF (Corrigido)</h6>
        <div id="custos-vf-body"></div>
      </div>
    </div>
  </div>

  {# ── ABA 4: Comercialização ── #}
  <div class="sp-sec" id="sptab-comercial">
    {% if fases %}
    <div class="sp-card">
      <h6 style="margin-bottom:.75rem;"><i class="bi bi-tags me-1"></i>Estrutura de Comercialização</h6>
      <div style="font-size:.72rem;color:#64748b;margin-bottom:.75rem;">
        Correção durante obra: <strong>{{ corr_obra }}% a.m.</strong> &nbsp;·&nbsp; Pós-obra: <strong>{{ corr_pos_obra }}% a.m.</strong>
      </div>
      <div style="overflow-x:auto;">
      <table style="width:100%;border-collapse:collapse;font-size:.8rem;">
        <thead>
          <tr style="background:#fff7ed;color:#ea580c;font-size:.68rem;font-weight:700;text-transform:uppercase;letter-spacing:.05em;">
            <th style="padding:.55rem .75rem;text-align:left;border-bottom:2px solid #fed7aa;">Fase</th>
            <th style="padding:.55rem .75rem;text-align:center;border-bottom:2px solid #fed7aa;">Meta</th>
            <th style="padding:.55rem .75rem;text-align:center;border-bottom:2px solid #fed7aa;">Duração</th>
            <th style="padding:.55rem .75rem;text-align:center;border-bottom:2px solid #fed7aa;">Entrada</th>
            <th style="padding:.55rem .75rem;text-align:center;border-bottom:2px solid #fed7aa;">Parc. Entrada</th>
            <th style="padding:.55rem .75rem;text-align:center;border-bottom:2px solid #fed7aa;">Parcelas</th>
            <th style="padding:.55rem .75rem;text-align:center;border-bottom:2px solid #fed7aa;">Nº Parc.</th>
            <th style="padding:.55rem .75rem;text-align:center;border-bottom:2px solid #fed7aa;">Reforços</th>
            <th style="padding:.55rem .75rem;text-align:center;border-bottom:2px solid #fed7aa;">Reajuste</th>
          </tr>
      </thead>
      <tbody>
        {% for f in fases %}
        <tr style="border-bottom:1px solid #f1f5f9;{% if loop.index is even %}background:#fafafa;{% endif %}">
          <td style="padding:.5rem .75rem;font-weight:600;">{{ f.nome or ('Fase ' ~ loop.index) }}</td>
          <td style="padding:.5rem .75rem;text-align:center;">{{ f.meta }}%</td>
          <td style="padding:.5rem .75rem;text-align:center;">{{ f.duracao }} m</td>
          <td style="padding:.5rem .75rem;text-align:center;">{{ f.entrada_pct }}%</td>
          <td style="padding:.5rem .75rem;text-align:center;">{{ f.n_entrada|default(1) }}x</td>
          <td style="padding:.5rem .75rem;text-align:center;">{{ f.parcelas_pct }}%</td>
          <td style="padding:.5rem .75rem;text-align:center;">{{ f.n_parcelas }}</td>
          <td style="padding:.5rem .75rem;text-align:center;">{% if f.reforco_pct and f.reforco_pct > 0 %}{{ f.reforco_pct }}% × {{ f.n_reforcos }}{% else %}—{% endif %}</td>
          <td style="padding:.5rem .75rem;text-align:center;color:{% if f.reajuste and f.reajuste > 0 %}#16a34a{% elif f.reajuste and f.reajuste < 0 %}#dc2626{% else %}#64748b{% endif %};font-weight:600;">{% if f.reajuste %}{{ '%+.1f'|format(f.reajuste|float) }}%{% else %}0%{% endif %}</td>
        </tr>
        {% endfor %}
      </tbody>
      </table>
      </div>
    </div>
    {% endif %}
  </div>

  {# ── ABA 5: Sensibilidade ── #}
  <div class="sp-sec" id="sptab-sensib">
    <div id="sensib-body"></div>
  </div>

</div>

<div class="sp-footer">
  <strong>Maffezzolli Capital</strong> &nbsp;·&nbsp; Estudo de Viabilidade Imobiliária<br>
  Este documento é confidencial e foi gerado automaticamente pela plataforma Maffezzolli Capital.
  Não constitui oferta, promessa ou garantia de retorno financeiro.
</div>

<script>
const CENARIOS = {{ cenarios_json | safe }};
const TEM_FIN = {{ 'true' if tem_fin else 'false' }};
let curCenario = 'realista';
let curFin = TEM_FIN;
let spChart = null;

function brl(v) {
  if (v === null || v === undefined) return '—';
  const s = 'R$ ' + Math.abs(v).toLocaleString('pt-BR', {minimumFractionDigits: 0, maximumFractionDigits: 0});
  return v < 0 ? '(' + s + ')' : s;
}
function pct(v, suffix) {
  if (v === null || v === undefined) return '—';
  return parseFloat(v).toFixed(1) + '%' + (suffix || '');
}
function mgColor(v) { return v >= 20 ? '#16a34a' : v >= 15 ? '#ca8a04' : '#dc2626'; }
function el(id) { return document.getElementById(id); }

function setCenario(c) {
  curCenario = c;
  ['realista','otimista','pessimista'].forEach(x => {
    const b = el('cn-' + x);
    if (!b) return;
    b.className = 'sp-cb' + (x === c ? ' cn-' + x : '');
  });
  render();
}

function setFin(f) {
  curFin = f;
  const bs = el('fin-btn-sem'), bc = el('fin-btn-com');
  if (bs) bs.classList.toggle('on', !f);
  if (bc) bc.classList.toggle('on', f);
  render();
}

function spTab(name, btn) {
  document.querySelectorAll('.sp-sec').forEach(s => s.classList.remove('on'));
  document.querySelectorAll('.sp-rtab').forEach(b => b.classList.remove('on'));
  const sec = el('sptab-' + name);
  if (sec) sec.classList.add('on');
  if (btn) btn.classList.add('on');
  if (name === 'fluxo') { const r = CENARIOS[curCenario]; if (r) renderChart(r.chart_labels, r.chart_pag, r.chart_rec, r.chart_exp); }
}

function renderDRE(dre) {
  const tbody = el('dre-body');
  if (!tbody || !dre) return;
  tbody.innerHTML = dre.map(row => {
    const v = row.tipo === 'pct'
      ? parseFloat(row.valor).toFixed(2) + '%'
      : brl(row.valor);
    return `<tr class="dre-row-${row.tipo}"><td>${row.desc}</td><td class="dre-val">${v}</td></tr>`;
  }).join('');
}

function renderChart(labels, pag, rec, exp) {
  const canvas = el('chartFluxo');
  if (!canvas) return;
  if (spChart) { spChart.destroy(); spChart = null; }
  if (!labels || !labels.length) return;
  spChart = new Chart(canvas, {
    type: 'line',
    data: {
      labels,
      datasets: [
        {label:'Pagamentos', data:pag, borderColor:'#ef4444', backgroundColor:'rgba(239,68,68,.1)', tension:.3, fill:true, pointRadius:0},
        {label:'Recebimentos', data:rec, borderColor:'#22c55e', backgroundColor:'rgba(34,197,94,.1)', tension:.3, fill:true, pointRadius:0},
        {label:'Exposição Acum.', data:exp, borderColor:'#94a3b8', borderDash:[5,5], tension:.3, fill:false, pointRadius:0}
      ]
    },
    options:{
      responsive:true,
      plugins:{legend:{position:'top'}},
      scales:{y:{ticks:{callback:v=>'R$'+v.toLocaleString('pt-BR')}}}
    }
  });
}

function render() {
  const r = CENARIOS[curCenario];
  if (!r) return;
  const fin = r.financiamento;

  // KPI VF como primário; VP nominal como fallback/referência
  let resultado, margem, tir, tirSub, exposicao;
  if (fin && curFin) {
    resultado = fin.resultado_com_fin; margem = fin.margem_com_fin;
    tir = fin.tir_alavancada; tirSub = 'TIR alavancada (equity)';
    exposicao = fin.exposicao_com_fin;
  } else {
    resultado = r.vf_resultado != null ? r.vf_resultado : r.resultado_bruto;
    margem    = r.vf_margem_vgv != null ? r.vf_margem_vgv : r.margem_vgv;
    tir       = r.tir_vf_anual != null ? r.tir_vf_anual : r.tir_anual;
    tirSub    = r.tir_vf_anual != null ? 'TIR VF — Corrigido' : 'Retorno interno do projeto';
    exposicao = r.exposicao_maxima;
  }

  // KPIs
  if (el('kpi-resultado')) {
    el('kpi-resultado').textContent = brl(resultado);
    el('kpi-resultado').style.color = (resultado || 0) >= 0 ? '#f97316' : '#dc2626';
    const vpSub = (r.vf_resultado != null && !curFin)
      ? ' · VP nominal: ' + brl(r.resultado_bruto)
      : '';
    if (el('kpi-resultado-sub')) el('kpi-resultado-sub').textContent = pct(margem) + '% sobre VGV' + vpSub;
  }
  if (el('kpi-margem')) {
    el('kpi-margem').textContent = pct(margem);
    el('kpi-margem').style.color = (margem || 0) >= 20 ? '#f97316' : (margem || 0) >= 15 ? '#ca8a04' : '#dc2626';
    if (el('kpi-margem-sub') && r.vf_margem_vgv != null && !curFin)
      el('kpi-margem-sub').textContent = 'VP nominal: ' + pct(r.margem_vgv);
  }
  if (el('kpi-tir')) {
    el('kpi-tir').textContent = tir ? parseFloat(tir).toFixed(1) + '% a.a.' : '—';
    el('kpi-tir').style.color = (tir || 0) >= 20 ? '#f97316' : (tir || 0) >= 15 ? '#ca8a04' : '#dc2626';
    if (el('kpi-tir-sub')) el('kpi-tir-sub').textContent = tirSub;
  }
  if (el('kpi-exposicao')) el('kpi-exposicao').textContent = brl(exposicao);

  // Status badge
  const cnBadge = {'realista':'badge-r','otimista':'badge-o','pessimista':'badge-p'}[curCenario];
  const st = r.status || {};
  if (el('sp-status-bar'))
    el('sp-status-bar').innerHTML = `<span class="sp-badge ${cnBadge}">${st.icon||''} ${st.label||curCenario}</span>`;

  // DRE VP
  renderDRE(r.dre);

  // DRE VF
  const dvfBody = el('dre-vf-body');
  if (dvfBody && r.dre_vf && r.dre_vf.length) {
    dvfBody.innerHTML = '<table class="dre-t"><tbody>' + r.dre_vf.map(row => {
      let v;
      if (row.tipo === 'pct') v = parseFloat(row.valor).toFixed(2) + '%';
      else if (row.tipo === 'subtotal') v = `<strong style="color:#f97316">${brl(row.valor)}</strong>`;
      else v = brl(row.valor);
      return `<tr class="dre-row-${row.tipo}"><td>${row.desc}</td><td class="dre-val">${v}</td></tr>`;
    }).join('') + '</tbody></table>';
  }

  // Chart (só renderiza se aba ativa)
  const fluxoSec = el('sptab-fluxo');
  if (fluxoSec && fluxoSec.classList.contains('on'))
    renderChart(r.chart_labels, r.chart_pag, r.chart_rec, r.chart_exp);
  else if (spChart) { /* preserva chart existente */ }
  else renderChart(r.chart_labels, r.chart_pag, r.chart_rec, r.chart_exp);

  // Custos VP
  const cvp = el('custos-vp-body');
  if (cvp) {
    const rows = [
      ['CUB × Área equiv.',    r.custo_cub],
      ['Itens fora CUB',       r.itens_extra],
      ['Despesas indiretas',   r.custo_indiretos],
      ['Terreno',              r.valor_terreno],
      ['Comercialização',      r.custo_comercial],
      ['Impostos s/ receita',  r.custo_impostos],
      ['<strong>Custo Total</strong>', r.custo_total],
    ];
    cvp.innerHTML = rows.filter(([,v])=>v!=null&&v!==0||true).map(([l,v])=>
      `<div class="bk-row"><span class="bk-lbl">${l}</span><span>${brl(v)}</span></div>`
    ).join('');
  }
  // Custos VF
  const cvf = el('custos-vf-body');
  if (cvf) {
    const ganho = (r.vf_resultado!=null && r.resultado_bruto!=null) ? r.vf_resultado - r.resultado_bruto : null;
    const rows = [
      ['VGV Corrigido',         r.vf_vgv],
      ['Custo de Obra (VF)',            r.vf_custo_obra],
      ['Custo Total (VF)',              r.vf_custo_total],
      ['Resultado VF',                  r.vf_resultado],
      ['Margem VF',                     r.vf_margem_vgv != null ? pct(r.vf_margem_vgv) : null, true],
      ['<strong style="color:#f97316">↑ Ganho VF vs VP</strong>', ganho],
    ];
    cvf.innerHTML = rows.filter(([,v])=>v!=null).map(([l,v,isPct])=>
      `<div class="bk-row"><span class="bk-lbl">${l}</span><span style="${l.includes('Ganho')?'color:#f97316;font-weight:700':''}"> ${isPct ? v : brl(v)}</span></div>`
    ).join('');
  }

  // Sensibilidade
  const sensib = el('sensib-body');
  if (sensib && r.sensibilidade) {
    const s = r.sensibilidade;
    const hdrs = s.fatores_custo || [];
    const mkTable = (title, rows, colorFn) => {
      const thead = `<tr><th style="text-align:left;">VGV \\ Custo</th>${hdrs.map(h=>`<th>${h}</th>`).join('')}</tr>`;
      const tbody = (rows||[]).map(row=>`<tr><td style="font-weight:700;background:#1e293b;color:#fff;padding:.4rem .6rem;">${row.label}</td>${(row.valores||[]).map(v=>{const c=colorFn(v);return `<td style="background:${c.bg};color:${c.fg};font-weight:600;">${v!=null?v+'%':'—'}</td>`;}).join('')}</tr>`).join('');
      return `<div class="sp-card" style="margin-bottom:1rem;"><h6>${title}</h6><div style="overflow-x:auto;"><table class="sen-t"><thead>${thead}</thead><tbody>${tbody}</tbody></table></div></div>`;
    };
    const tirColor = v => v==null?{bg:'#f1f5f9',fg:'#94a3b8'}:v>=25?{bg:'#dcfce7',fg:'#15803d'}:v>=18?{bg:'#fef9c3',fg:'#854d0e'}:{bg:'#fee2e2',fg:'#dc2626'};
    const mgColor2 = v => v==null?{bg:'#f1f5f9',fg:'#94a3b8'}:v>=25?{bg:'#dcfce7',fg:'#15803d'}:v>=15?{bg:'#fef9c3',fg:'#854d0e'}:{bg:'#fee2e2',fg:'#dc2626'};
    sensib.innerHTML = mkTable('<i class="bi bi-bar-chart-line me-1"></i>Sensibilidade — TIR (%)', s.rows_tir, tirColor)
                     + mkTable('<i class="bi bi-percent me-1"></i>Sensibilidade — Margem VGV (%)', s.rows_margem, mgColor2);
  } else if (sensib) {
    sensib.innerHTML = '<div class="sp-card"><p style="color:#94a3b8;font-size:.84rem;">Dados de sensibilidade não disponíveis. Salve e compartilhe novamente.</p></div>';
  }

  // Financing comparison
  if (fin) {
    if (el('fin-sem-res')) el('fin-sem-res').textContent = brl(fin.resultado_sem_fin);
    if (el('fin-sem-mg')) { el('fin-sem-mg').textContent = pct(fin.margem_sem_fin); el('fin-sem-mg').style.color = mgColor(fin.margem_sem_fin||0); }
    if (el('fin-sem-tir')) el('fin-sem-tir').textContent = r.tir_anual ? parseFloat(r.tir_anual).toFixed(1)+'% a.a.' : '—';
    if (el('fin-sem-exp')) el('fin-sem-exp').textContent = brl((fin.exposicao_com_fin||0)+(fin.reducao_exposicao||0));
    if (el('fin-com-res')) { el('fin-com-res').textContent = brl(fin.resultado_com_fin); el('fin-com-res').style.color = (fin.resultado_com_fin||0)>=0?'#16a34a':'#dc2626'; }
    if (el('fin-com-mg')) { el('fin-com-mg').textContent = pct(fin.margem_com_fin); el('fin-com-mg').style.color = mgColor(fin.margem_com_fin||0); }
    if (el('fin-com-tir')) el('fin-com-tir').textContent = fin.tir_alavancada ? parseFloat(fin.tir_alavancada).toFixed(1)+'% a.a.' : '—';
    if (el('fin-com-exp')) el('fin-com-exp').textContent = brl(fin.exposicao_com_fin);
    if (el('fin-costs-row')) el('fin-costs-row').innerHTML =
      `<i class="bi bi-info-circle me-1"></i>Custo total de juros: <strong style="color:#dc2626">${brl(fin.custo_fin_total)}</strong>`+
      ` &nbsp;·&nbsp; Crédito captado máximo: <strong style="color:#1e40af">${brl(fin.valor_financiado)}</strong>`;
  }
}

document.addEventListener('DOMContentLoaded', function() { render(); });
</script>
</body>
</html>"""


# ── Patch do template existente: adiciona botões salvar/histórico ─────────────

_vb_tmpl = TEMPLATES.get("ferramenta_viabilidade.html", "")

# 1) Adiciona "Salvar & Compartilhar" após o botão de Exportar PDF
_vb_tmpl = _vb_tmpl.replace(
    '    <button onclick="window.print()" class="btn btn-outline-secondary btn-sm">\n'
    '      <i class="bi bi-printer me-1"></i> Exportar PDF\n'
    '    </button>\n'
    '    {% endif %}',
    '    <button onclick="window.print()" class="btn btn-outline-secondary btn-sm">\n'
    '      <i class="bi bi-printer me-1"></i> Exportar PDF\n'
    '    </button>\n'
    '    <button type="button" id="btnSalvar" class="btn btn-sm" style="background:#6366f1;color:#fff;border:none;" onclick="salvarEstudo()">\n'
    '      <i class="bi bi-share me-1"></i> Salvar &amp; Compartilhar\n'
    '    </button>\n'
    '    {% endif %}',
    1
)

# 2) Adiciona aba Histórico na barra de abas
_vb_tmpl = _vb_tmpl.replace(
    '  {% if resultado %}<button type="button" class="vb-tab" onclick="vbTab(\'resultado\',this)">✅ Resultado</button>{% endif %}\n</div>',
    '  {% if resultado %}<button type="button" class="vb-tab" onclick="vbTab(\'resultado\',this)">✅ Resultado</button>{% endif %}\n'
    '  <button type="button" class="vb-tab" onclick="vbTab(\'historico\',this);loadHistorico()">📁 Histórico</button>\n</div>',
    1
)

# 3) Adiciona painel de histórico + link de abertura antes do </form>
_historico_panel = (
    '\n{# ── PAINEL HISTÓRICO ── #}\n'
    '<div class="vb-sec card p-4 mb-3" id="tab-historico">\n'
    '  <h5 class="mb-3">📁 Histórico de Estudos de Viabilidade</h5>\n'
    '  <p class="small text-muted mb-3">Todos os estudos salvos pela sua empresa. Clique em <strong>Abrir</strong> para reeditar ou <strong>Ver link</strong> para copiar o link de compartilhamento.</p>\n'
    '  <div id="historicoList"><div class="text-muted small text-center py-3"><i class="bi bi-hourglass-split me-1"></i>Clique na aba Histórico para carregar.</div></div>\n'
    '</div>\n'
)
_vb_tmpl = _vb_tmpl.replace('\n</form>\n', _historico_panel + '\n</form>\n', 1)

# 4) Adiciona modal de compartilhamento após </form>
_share_modal = (
    '\n{# Modal compartilhar #}\n'
    '<div id="shareModal" style="display:none;position:fixed;inset:0;background:rgba(0,0,0,.5);z-index:9999;align-items:center;justify-content:center;">\n'
    '  <div style="background:#fff;border-radius:16px;padding:2rem;max-width:520px;width:90%;box-shadow:0 20px 60px rgba(0,0,0,.3);">\n'
    '    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:1.1rem;">\n'
    '      <h5 style="margin:0;color:#f97316;"><i class="bi bi-share me-2"></i>Estudo Salvo!</h5>\n'
    '      <button type="button" onclick="document.getElementById(\'shareModal\').style.display=\'none\'" style="background:none;border:none;font-size:1.3rem;cursor:pointer;color:#64748b;">&times;</button>\n'
    '    </div>\n'
    '    <p style="color:#475569;font-size:.88rem;margin-bottom:1rem;">Compartilhe com investidores e parceiros. Eles poderão ver os 3 cenários e o impacto do financiamento — sem editar as premissas.</p>\n'
    '    <div style="display:flex;gap:.5rem;margin-bottom:1rem;">\n'
    '      <input type="text" id="shareUrlInput" readonly style="flex:1;border:1.5px solid #e2e8f0;border-radius:10px;padding:.55rem .85rem;font-size:.83rem;background:#f8fafc;">\n'
    '      <button type="button" onclick="copyShareUrl()" id="copyBtn" style="background:#f97316;color:#fff;border:none;border-radius:10px;padding:.55rem 1rem;font-size:.83rem;font-weight:600;cursor:pointer;white-space:nowrap;">'
    '<i class="bi bi-clipboard me-1"></i>Copiar</button>\n'
    '    </div>\n'
    '    <a id="shareUrlLink" href="#" target="_blank" style="display:block;text-align:center;font-size:.84rem;color:#f97316;text-decoration:none;font-weight:600;">\n'
    '      <i class="bi bi-box-arrow-up-right me-1"></i>Abrir em nova aba\n'
    '    </a>\n'
    '  </div>\n'
    '</div>\n'
)
_vb_tmpl = _vb_tmpl.replace('\n{# Modal compartilhar #}', '', 1)  # limpa se já existir
_vb_tmpl = _vb_tmpl.replace(
    '\n{% if resultado %}\n<script>',
    _share_modal + '\n{% if resultado %}\n<script>',
    1
)

# 5) Adiciona funções JS (salvarEstudo, copyShareUrl, loadHistorico) antes do </script> final
_js_extras = r"""
async function salvarEstudo(){
  const form=document.getElementById('vbForm');
  const btn=document.getElementById('btnSalvar');
  if(btn){btn.disabled=true;btn.innerHTML='<i class="bi bi-hourglass-split me-1"></i>Salvando...';}
  try{
    const resp=await fetch('/ferramentas/viabilidade/salvar',{method:'POST',body:new FormData(form)});
    const data=await resp.json();
    if(data.ok){
      const url=window.location.origin+data.url;
      document.getElementById('shareUrlInput').value=url;
      document.getElementById('shareUrlLink').href=url;
      document.getElementById('shareModal').style.display='flex';
    }else{alert('Erro ao salvar: '+(data.error||'Tente novamente'));}
  }catch(e){alert('Erro de conexão ao salvar.');}
  if(btn){btn.disabled=false;btn.innerHTML='<i class="bi bi-share me-1"></i>Salvar &amp; Compartilhar';}
}
function copyShareUrl(){
  const inp=document.getElementById('shareUrlInput');
  navigator.clipboard.writeText(inp.value).then(()=>{
    const b=document.getElementById('copyBtn');
    b.innerHTML='<i class="bi bi-check me-1"></i>Copiado!';
    setTimeout(()=>{b.innerHTML='<i class="bi bi-clipboard me-1"></i>Copiar';},2200);
  }).catch(()=>{inp.select();document.execCommand('copy');});
}
async function loadHistorico(){
  const el=document.getElementById('historicoList');
  if(!el)return;
  el.innerHTML='<div class="text-muted small text-center py-3"><i class="bi bi-hourglass-split me-1"></i>Carregando...</div>';
  try{
    const resp=await fetch('/ferramentas/viabilidade/historico');
    const data=await resp.json();
    const estudos=data.estudos||[];
    if(!estudos.length){
      el.innerHTML='<div class="text-muted small text-center py-3">Nenhum estudo salvo ainda. Calcule uma viabilidade e clique em <strong>Salvar &amp; Compartilhar</strong>.</div>';
      return;
    }
    el.innerHTML=estudos.map(e=>`
      <div id="hist-row-${e.id}" style="display:flex;align-items:center;justify-content:space-between;padding:.75rem 1rem;border:1px solid #e2e8f0;border-radius:12px;margin-bottom:.5rem;gap:.75rem;flex-wrap:wrap;background:#fff;">
        <div>
          <div style="font-weight:700;font-size:.93rem;">${e.nome_projeto||'Sem nome'}</div>
          <div style="font-size:.74rem;color:#64748b;margin-top:.2rem;">
            <i class="bi bi-calendar3 me-1"></i>${e.criado_em_fmt}
            &nbsp;·&nbsp; Margem VGV (realista):
            <strong style="color:${e.margem_vgv>=20?'#16a34a':e.margem_vgv>=15?'#ca8a04':'#dc2626'}">${e.margem_vgv}%</strong>
          </div>
        </div>
        <div style="display:flex;gap:.5rem;flex-shrink:0;">
          <a href="${e.share_url}" target="_blank" class="btn btn-sm btn-outline-secondary" style="font-size:.8rem;">
            <i class="bi bi-share me-1"></i>Ver link</a>
          <a href="${e.open_url}" class="btn btn-sm" style="background:#f97316;color:#fff;border:none;font-size:.8rem;">
            <i class="bi bi-folder2-open me-1"></i>Abrir</a>
          <a href="/ferramentas/mapa-unidades" onclick="ativarEmpStudo(event,${e.id})" class="btn btn-sm btn-outline-primary" style="font-size:.8rem;" title="Criar empreendimento a partir deste estudo">
            <i class="bi bi-buildings me-1"></i>Mapa</a>
          <button onclick="excluirEstudo(${e.id})" class="btn btn-sm btn-outline-danger" style="font-size:.8rem;" title="Excluir estudo">
            <i class="bi bi-trash3"></i></button>
        </div>
      </div>
    `).join('');
  }catch(e){
    el.innerHTML='<div class="text-muted small text-center py-3 text-danger"><i class="bi bi-exclamation-circle me-1"></i>Erro ao carregar histórico.</div>';
  }
}
async function excluirEstudo(id){
  if(!confirm('Excluir este estudo? Esta ação não pode ser desfeita.'))return;
  try{
    const resp=await fetch('/ferramentas/viabilidade/historico/'+id,{method:'DELETE'});
    const data=await resp.json();
    if(data.ok){
      const row=document.getElementById('hist-row-'+id);
      if(row)row.remove();
    }else{
      alert('Erro ao excluir: '+(data.erro||'desconhecido'));
    }
  }catch(e){
    alert('Erro de conexão ao excluir estudo.');
  }
}
async function ativarEmpStudo(ev, estudoId){
  ev.preventDefault();
  if(!confirm('Criar empreendimento no Mapa de Unidades a partir deste estudo?\n\nAs tipologias e unidades serão geradas automaticamente.'))return;
  const fd=new FormData();
  fd.append('estudo_id',estudoId);
  const resp=await fetch('/ferramentas/mapa-unidades/criar',{method:'POST',body:fd});
  if(resp.redirected){window.location.href=resp.url;}
  else{window.location.href='/ferramentas/mapa-unidades';}
}
"""
_vb_tmpl = _vb_tmpl.replace(
    "function rmFase(i){const el=document.getElementById('fase-'+i);if(el)el.remove();}",
    "function rmFase(i){const el=document.getElementById('fase-'+i);if(el)el.remove();}" + _js_extras,
    1
)

TEMPLATES["ferramenta_viabilidade.html"] = _vb_tmpl

if hasattr(templates_env.loader, "mapping"):
    templates_env.loader.mapping = TEMPLATES

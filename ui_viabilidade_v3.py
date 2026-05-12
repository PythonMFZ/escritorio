# ============================================================================
# PATCH — Ferramenta Viabilidade Imobiliária v3
# ============================================================================
# Extensão do motor v2 com:
#   - Módulo de financiamento de obra (SAC / PRICE)
#   - Indicadores CRI (Certificado de Recebíveis Imobiliários)
#   - Análise de sensibilidade 5×5 (VGV × Custo)
#   - Indicadores adicionais: VSO, Payback Descontado, IL, Múltiplo, PE, Spread CDI
# ============================================================================

import json as _json
import math as _math
from datetime import datetime as _dt


# ── TIR helper (autônoma para não depender de escopo externo) ─────────────────

def _tir_v3(fluxos: list, max_iter: int = 300) -> float | None:
    if not fluxos or not any(f > 0 for f in fluxos):
        return None
    r = 0.01
    for _ in range(max_iter):
        try:
            npv  = sum(f / (1 + r) ** i for i, f in enumerate(fluxos))
            dnpv = sum(-i * f / (1 + r) ** (i + 1) for i, f in enumerate(fluxos))
            if abs(dnpv) < 1e-10:
                break
            r_new = r - npv / dnpv
            if abs(r_new - r) < 1e-9:
                r = r_new
                break
            r = max(-0.99, r_new)
        except Exception:
            break
    return r if -1 < r < 10 else None


# ── Motor v3 ──────────────────────────────────────────────────────────────────

def _calcular_v3(dados: dict) -> dict:
    """Motor v3: chama _calcular_viabilidade_v2 e adiciona financiamento, CRI e sensibilidade."""

    base = _calcular_viabilidade_v2(dados)

    # Dados de referência do base
    vgv_liquido       = base["vgv_liquido"]
    custo_total       = base["custo_total"]
    custo_obra_total  = base["custo_obra_total"]
    resultado_bruto   = base["resultado_bruto"]
    tir_anual_base    = base.get("tir_anual") or 0.0
    vpl_base          = base.get("vpl") or 0.0
    unidades_total    = base["unidades_total"]
    unidades_permuta  = base["unidades_permuta"]
    duracao_obra      = int(dados.get("duracao_obra", 36) or 36)
    mes_inicio_obra   = int(dados.get("mes_inicio_obra", 12) or 12)
    duracao_analise   = int(dados.get("duracao_analise", 129) or 129)
    tma_mensal        = (1.12 ** (1/12)) - 1

    # ── A. MÓDULO DE FINANCIAMENTO ─────────────────────────────────────────
    usar_fin = dados.get("usar_financiamento", "0") == "1"
    fin_result = None

    if usar_fin:
        pct_fin    = float(dados.get("pct_fin", 70) or 70) / 100
        taxa_am    = float(dados.get("taxa_juros_am", 1.20) or 1.20) / 100
        tipo_amort = dados.get("tipo_amortizacao", "SAC")
        carencia   = int(dados.get("carencia_meses", 6) or 6)
        haircut_pct = float(dados.get("haircut_pct", 20) or 20) / 100
        sub_ratio  = float(dados.get("sub_ratio", 20) or 20) / 100
        cdi_ref    = float(dados.get("cdi_ref", 13.75) or 13.75)

        # Mapa de desembolso por mês absoluto (somente durante a obra)
        dd_map = {}
        for f in base["fluxo"]:
            if mes_inicio_obra <= f["mes"] < mes_inicio_obra + duracao_obra:
                dd_map[f["mes"]] = f["custo_obra"] * pct_fin

        schedule = []
        saldo = 0.0
        juros_total = 0.0

        # Fase 1: Desembolso (durante a obra) — saldo cresce com drawdowns + juros
        for k in range(duracao_obra):
            mes_abs = mes_inicio_obra + k
            dd      = dd_map.get(mes_abs, 0.0)
            juros   = saldo * taxa_am
            saldo   = saldo + juros + dd
            juros_total += juros
            schedule.append({"mes": mes_abs, "fase": "Desembolso",
                              "drawdown": round(dd, 2), "juros": round(juros, 2),
                              "amortizacao": 0.0, "saldo_devedor": round(saldo, 2),
                              "servico_divida": round(juros, 2)})

        # Fase 2: Carência — saldo cresce só com juros (sem amortizar)
        for k in range(carencia):
            mes_abs = mes_inicio_obra + duracao_obra + k
            juros   = saldo * taxa_am
            saldo   = saldo + juros
            juros_total += juros
            schedule.append({"mes": mes_abs, "fase": "Carência",
                              "drawdown": 0.0, "juros": round(juros, 2),
                              "amortizacao": 0.0, "saldo_devedor": round(saldo, 2),
                              "servico_divida": round(juros, 2)})

        saldo_pico = saldo   # máximo real = fim da carência

        # Fase 3: Amortização (SAC ou PRICE) — prazo = mesmo da obra
        meses_amort = max(duracao_obra, 12)
        saldo_amort = saldo_pico

        if tipo_amort == "SAC":
            amort_unit = saldo_amort / meses_amort
            for k in range(meses_amort):
                mes_abs = mes_inicio_obra + duracao_obra + carencia + k
                juros_k = saldo_amort * taxa_am
                amort_k = min(amort_unit, saldo_amort)
                saldo_amort = max(saldo_amort - amort_k, 0)
                servico = juros_k + amort_k
                juros_total += juros_k
                schedule.append({"mes": mes_abs, "fase": "Amortização",
                                  "drawdown": 0.0, "juros": round(juros_k, 2),
                                  "amortizacao": round(amort_k, 2),
                                  "saldo_devedor": round(saldo_amort, 2),
                                  "servico_divida": round(servico, 2)})
        else:  # PRICE
            if taxa_am > 0 and meses_amort > 0:
                parcela = saldo_amort * taxa_am / (1 - (1 + taxa_am) ** (-meses_amort))
            else:
                parcela = saldo_amort / max(meses_amort, 1)
            for k in range(meses_amort):
                mes_abs = mes_inicio_obra + duracao_obra + carencia + k
                juros_k = saldo_amort * taxa_am
                amort_k = max(min(parcela - juros_k, saldo_amort), 0)
                saldo_amort = max(saldo_amort - amort_k, 0)
                servico = juros_k + amort_k
                juros_total += juros_k
                schedule.append({"mes": mes_abs, "fase": "Amortização",
                                  "drawdown": 0.0, "juros": round(juros_k, 2),
                                  "amortizacao": round(amort_k, 2),
                                  "saldo_devedor": round(saldo_amort, 2),
                                  "servico_divida": round(servico, 2)})

        custo_fin_total = round(juros_total, 2)
        valor_financiado = round(saldo_pico, 2)

        # TIR alavancada: fluxo do equity (custo - drawdown + amortizacao)
        fluxo_equity = []
        for i, f in enumerate(base["fluxo"]):
            sc  = schedule[i] if i < len(schedule) else {}
            dd  = sc.get("drawdown", 0)
            am  = sc.get("amortizacao", 0)
            jj  = sc.get("juros", 0)
            # Equity: receita - custo (sem drawdown, pois drawdown cobre parte) - amortização - juros + drawdown recebido
            saldo_equity = f["saldo_mes"] + dd - am - jj
            fluxo_equity.append(saldo_equity)

        tir_alav_m = _tir_v3(fluxo_equity[:min(len(fluxo_equity), 120)])
        tir_alavancada = ((1 + tir_alav_m) ** 12 - 1) * 100 if tir_alav_m is not None else None

        equity_investido = custo_total - valor_financiado
        roe = resultado_bruto / equity_investido * 100 if equity_investido > 0 else None

        # Exposição com financiamento
        saldo_acum_fin = 0.0
        exposicao_fin  = 0.0
        for i, f in enumerate(base["fluxo"]):
            sc  = schedule[i] if i < len(schedule) else {}
            dd  = sc.get("drawdown", 0)
            am  = sc.get("amortizacao", 0)
            jj  = sc.get("juros", 0)
            saldo_acum_fin += f["saldo_mes"] + dd - am - jj
            if saldo_acum_fin < exposicao_fin:
                exposicao_fin = saldo_acum_fin
        exposicao_com_fin = abs(exposicao_fin)

        # DSCR médio
        dscr_list = []
        for i, f in enumerate(base["fluxo"]):
            sc  = schedule[i] if i < len(schedule) else {}
            serv = sc.get("servico_divida", 0)
            if serv > 0:
                dscr_list.append(f["receita"] / serv)
        dscr_medio = sum(dscr_list) / len(dscr_list) if dscr_list else None

        # ── B. INDICADORES CRI ────────────────────────────────────────────
        pct_entrada_media = 0.10
        fases_d = dados.get("fases", [])
        if fases_d:
            entradas = [float(f.get("entrada_pct", 10) or 10) / 100 for f in fases_d]
            pct_entrada_media = sum(entradas) / len(entradas)

        carteira_recebiveis_pico = vgv_liquido * (1 - pct_entrada_media)
        emissao_cri_bruta = carteira_recebiveis_pico * (1 - haircut_pct)
        sr_senior  = emissao_cri_bruta * (1 - sub_ratio)
        sr_sub     = emissao_cri_bruta * sub_ratio
        ltv_cri    = emissao_cri_bruta / vgv_liquido * 100 if vgv_liquido > 0 else 0
        cobertura_min = 1 / (1 - haircut_pct) if haircut_pct < 1 else 0
        spread_cdi_fin = tir_alavancada - cdi_ref if tir_alavancada is not None else None

        fin_result = {
            "valor_financiado":         round(valor_financiado, 2),
            "custo_fin_total":          round(custo_fin_total, 2),
            "tir_alavancada":           round(tir_alavancada, 2) if tir_alavancada is not None else None,
            "roe":                      round(roe, 2) if roe is not None else None,
            "exposicao_com_fin":        round(exposicao_com_fin, 2),
            "dscr_medio":               round(dscr_medio, 2) if dscr_medio is not None else None,
            "carteira_recebiveis_pico": round(carteira_recebiveis_pico, 2),
            "emissao_cri_bruta":        round(emissao_cri_bruta, 2),
            "sr_senior":                round(sr_senior, 2),
            "sr_sub":                   round(sr_sub, 2),
            "ltv_cri":                  round(ltv_cri, 2),
            "cobertura_min":            round(cobertura_min, 4),
            "spread_cdi":               round(spread_cdi_fin, 2) if spread_cdi_fin is not None else None,
            "schedule":                 schedule[:24],
            "tipo_amortizacao":         tipo_amort,
            "pct_fin":                  round(pct_fin * 100, 1),
            "taxa_am":                  round(taxa_am * 100, 2),
            "carencia":                 carencia,
            "haircut_pct":              round(haircut_pct * 100, 1),
            "sub_ratio":                round(sub_ratio * 100, 1),
            "cdi_ref":                  cdi_ref,
        }

    # ── C. ANÁLISE DE SENSIBILIDADE ────────────────────────────────────────
    preco_m2_base = float(dados.get("preco_m2_base", 12500) or 12500)
    cub_base      = float(dados.get("cub_m2", 3019) or 3019)
    vgv_fatores   = [0.80, 0.90, 1.00, 1.10, 1.20]
    cst_fatores   = [0.80, 0.90, 1.00, 1.10, 1.20]

    sen_tir     = []
    sen_margem  = []
    sen_result  = []

    for vf in vgv_fatores:
        row_tir    = []
        row_margem = []
        row_result = []
        for cf in cst_fatores:
            d_sen = dict(dados)
            d_sen["preco_m2_base"] = preco_m2_base * vf
            d_sen["cub_m2"]        = cub_base * cf
            # Ajustar tipologias: preço base multiplicado
            if dados.get("tipologias"):
                tips_adj = []
                for t in dados["tipologias"]:
                    ta = dict(t)
                    ta["preco_m2"] = float(t.get("preco_m2", preco_m2_base) or preco_m2_base) * vf
                    tips_adj.append(ta)
                d_sen["tipologias"] = tips_adj
            try:
                r_sen = _calcular_viabilidade_v2(d_sen)
                row_tir.append(round(r_sen.get("tir_anual") or 0, 2))
                row_margem.append(round(r_sen.get("margem_vgv") or 0, 2))
                row_result.append(round(r_sen.get("resultado_bruto") or 0, 2))
            except Exception:
                row_tir.append(None)
                row_margem.append(None)
                row_result.append(None)
        sen_tir.append(row_tir)
        sen_margem.append(row_margem)
        sen_result.append(row_result)

    lbl_vgv  = [f"{int(f*100)}%" for f in vgv_fatores]
    lbl_cust = [f"{int(f*100)}%" for f in cst_fatores]
    sensibilidade = {
        "fatores_vgv":   lbl_vgv,
        "fatores_custo": lbl_cust,
        "tir":     sen_tir,
        "margem":  sen_margem,
        "resultado": sen_result,
        # Estrutura pré-pronta para Jinja2 (evita enumerate)
        "rows_tir":    [{"label": lbl_vgv[i], "valores": sen_tir[i]}    for i in range(5)],
        "rows_margem": [{"label": lbl_vgv[i], "valores": sen_margem[i]} for i in range(5)],
    }

    # ── D. INDICADORES ADICIONAIS ───────────────────────────────────────────
    vso_mensal = (unidades_total - unidades_permuta) / max(duracao_analise, 1)

    # Payback descontado
    payback_desc = None
    acum_desc = 0.0
    for i, f in enumerate(base["fluxo"]):
        acum_desc += f["saldo_mes"] / ((1 + tma_mensal) ** i)
        if acum_desc > 0 and payback_desc is None:
            payback_desc = f["mes"]

    indice_lucratividade = (vpl_base + custo_total) / custo_total if custo_total > 0 else None
    multiplo_capital     = vgv_liquido / custo_total if custo_total > 0 else None
    ponto_equilibrio_pct = custo_total / vgv_liquido * 100 if vgv_liquido > 0 else None
    spread_cdi_base      = tir_anual_base - float(dados.get("cdi_ref", 13.75) or 13.75)

    indicadores_adicionais = {
        "vso_mensal":           round(vso_mensal, 2),
        "payback_descontado":   payback_desc,
        "indice_lucratividade": round(indice_lucratividade, 4) if indice_lucratividade else None,
        "multiplo_capital":     round(multiplo_capital, 2) if multiplo_capital else None,
        "ponto_equilibrio_pct": round(ponto_equilibrio_pct, 2) if ponto_equilibrio_pct else None,
        "spread_cdi":           round(spread_cdi_base, 2),
    }

    # DRE (Demonstrativo de Resultado)
    vgv_bruto = base["vgv_bruto"]
    dre_rows = [
        {"desc": "Receita Bruta de Vendas",    "valor": vgv_bruto,                        "tipo": "receita"},
        {"desc": "(−) Permuta",                "valor": -base["valor_permuta"],            "tipo": "deducao"},
        {"desc": "VGV Líquido",                "valor": vgv_liquido,                       "tipo": "subtotal"},
        {"desc": "(−) Impostos s/ Receita",    "valor": -base["custo_impostos"],           "tipo": "deducao"},
        {"desc": "(−) Custo de Obra",          "valor": -base["custo_obra_total"],         "tipo": "deducao"},
        {"desc": "(−) Terreno",                "valor": -base["valor_terreno"],            "tipo": "deducao"},
        {"desc": "(−) Comercialização",        "valor": -base["custo_comercial"],          "tipo": "deducao"},
        {"desc": "Resultado Operacional",      "valor": resultado_bruto,                   "tipo": "resultado"},
        {"desc": "Lucratividade",              "valor": round(resultado_bruto/vgv_liquido*100 if vgv_liquido else 0, 2), "tipo": "pct"},
    ]

    # Chart data — only non-zero months, max 120
    chart_labels, chart_pag, chart_rec, chart_exp = [], [], [], []
    for f in base["fluxo"][:120]:
        if f["receita"] != 0 or f["custo_obra"] != 0 or f["saldo_mes"] != 0:
            chart_labels.append(f["mes"])
            chart_pag.append(round(-(f["custo_obra"] + f["comissao"] + f["tributos"]), 2))
            chart_rec.append(round(f["receita"], 2))
            chart_exp.append(round(f["saldo_acumulado"], 2))

    # Desembolso anual aggregated
    from collections import defaultdict as _dd
    anual = _dd(float)
    for f in base["fluxo"][:120]:
        if f["custo_obra"] > 0:
            ano = (f["mes"] // 12) + 1
            anual[ano] += f["custo_obra"]
    desembolso_anual = [{"ano": f"Ano {k}", "valor": round(v,2)} for k,v in sorted(anual.items())]

    base["dre"]                = dre_rows
    base["chart_labels"]       = chart_labels
    base["chart_pag"]          = chart_pag
    base["chart_rec"]          = chart_rec
    base["chart_exp"]          = chart_exp
    base["desembolso_anual"]   = desembolso_anual
    base["cenario"]            = dados.get("cenario", "realista")

    base["financiamento"]          = fin_result
    base["sensibilidade"]          = sensibilidade
    base["indicadores_adicionais"] = indicadores_adicionais

    # Quando financiamento ativo: armazena resultado SEM e COM para comparação
    if fin_result:
        custo_fin = fin_result["custo_fin_total"]
        res_sem   = base["resultado_bruto"]
        res_com   = res_sem - custo_fin
        mgm_sem   = round(res_sem / vgv_liquido * 100, 2) if vgv_liquido else 0
        mgm_com   = round(res_com / vgv_liquido * 100, 2) if vgv_liquido else 0
        fin_result["resultado_sem_fin"] = round(res_sem, 2)
        fin_result["resultado_com_fin"] = round(res_com, 2)
        fin_result["margem_sem_fin"]    = mgm_sem
        fin_result["margem_com_fin"]    = mgm_com
        fin_result["reducao_exposicao"] = round(base["exposicao_maxima"] - fin_result["exposicao_com_fin"], 2)
        # Atualiza os KPIs principais com financiamento incluído
        base["resultado_bruto"] = round(res_com, 2)
        base["margem_vgv"]      = mgm_com
        base["margem_custo"]    = round(res_com / (base["custo_total"] + custo_fin) * 100, 2) if base["custo_total"] else 0
        base["exposicao_maxima"] = fin_result["exposicao_com_fin"]
        base["status"] = _classificar(mgm_com / 100, (fin_result.get("tir_alavancada") or base.get("tir_anual") or 0) / 100)
        # Atualiza DRE com custo financeiro
        base["dre"].insert(-2, {"desc": "(−) Custo Financeiro (CCB)", "valor": -custo_fin, "tipo": "deducao"})
        base["dre"][-2] = {"desc": "Resultado Operacional", "valor": round(res_com, 2), "tipo": "resultado"}
        base["dre"][-1] = {"desc": "Lucratividade", "valor": mgm_com, "tipo": "pct"}

    return base


# ── Override da rota POST ─────────────────────────────────────────────────────

app.router.routes = [
    r for r in app.router.routes
    if not (
        hasattr(r, "path")
        and r.path == "/ferramentas/viabilidade/calcular"
        and "POST" in [m.upper() for m in getattr(r, "methods", [])]
    )
]


@app.post("/ferramentas/viabilidade/calcular", response_class=HTMLResponse)
@require_login
async def ferramenta_viabilidade_post_v3(
    request: Request, session: Session = Depends(get_session),
) -> HTMLResponse:
    ctx = get_tenant_context(request, session)
    if not ctx:
        request.session.clear()
        return RedirectResponse("/login", status_code=303)
    cc = get_client_or_none(session, ctx.company.id, get_active_client_id(request, session, ctx))
    form  = await request.form()
    dados: dict = dict(form)

    # Tipologias
    tipologias = []
    i = 0
    while f"tip_nome_{i}" in dados or f"tip_metragem_{i}" in dados:
        met = float(dados.get(f"tip_metragem_{i}", 0) or 0)
        qtd = int(dados.get(f"tip_qtd_{i}", 0) or 0)
        if met > 0 and qtd > 0:
            tipologias.append({
                "nome":        dados.get(f"tip_nome_{i}", ""),
                "tipo":        dados.get(f"tip_tipo_{i}", "Residencial"),
                "metragem":    met,
                "quantidade":  qtd,
                "preco_m2":    float(dados.get(f"tip_preco_{i}", 0) or 0) or float(dados.get("preco_m2_base", 12500)),
                "andar_inicio": int(dados.get(f"tip_andar_{i}", 1) or 1),
                "permuta":     dados.get(f"tip_permuta_{i}") == "1",
            })
        i += 1
    dados["tipologias"] = tipologias

    # Fases de venda
    fases = []
    j = 0
    while f"fase_nome_{j}" in dados:
        fases.append({
            "nome":        dados.get(f"fase_nome_{j}", ""),
            "meta":        float(dados.get(f"fase_meta_{j}", 0) or 0),
            "reajuste":    float(dados.get(f"fase_reajuste_{j}", 0) or 0),
            "duracao":     int(dados.get(f"fase_duracao_{j}", 12) or 12),
            "entrada_pct": float(dados.get(f"fase_entrada_{j}", 10) or 10),
            "parcelas_pct": float(dados.get(f"fase_parcelas_{j}", 80) or 80),
            "n_parcelas":  int(dados.get(f"fase_nparcelas_{j}", 24) or 24),
            "reforco_pct": float(dados.get(f"fase_reforco_{j}", 0) or 0),
            "n_reforcos":  int(dados.get(f"fase_nreforcos_{j}", 0) or 0),
        })
        j += 1
    if fases:
        dados["fases"] = fases

    # Cenário multiplier
    cenario = dados.get("cenario", "realista")
    mult = {"otimista": 1.15, "realista": 1.00, "pessimista": 0.85}.get(cenario, 1.00)
    if mult != 1.00:
        dados["preco_m2_base"] = float(dados.get("preco_m2_base", 12500) or 12500) * mult
        if dados.get("tipologias"):
            for t in dados["tipologias"]:
                t["preco_m2"] = float(t.get("preco_m2", 0) or 0) * mult
    dados["cenario"] = cenario

    resultado = _calcular_v3(dados)
    return render("ferramenta_viabilidade.html", request=request, context={
        "current_user":    ctx.user,
        "current_company": ctx.company,
        "role":            ctx.membership.role,
        "current_client":  cc,
        "resultado":       resultado,
        "dados":           dados,
    })


# ── Template override ─────────────────────────────────────────────────────────

TEMPLATES["ferramenta_viabilidade.html"] = r"""
{% extends "base.html" %}
{% block content %}
<script src="https://cdn.jsdelivr.net/npm/chart.js@4/dist/chart.umd.min.js"></script>
<style>
  :root{--teal:#0d9488;--teal-light:rgba(13,148,136,.1);--teal-border:rgba(13,148,136,.3);}
  .vb-hdr{display:flex;justify-content:space-between;align-items:flex-start;flex-wrap:wrap;gap:1rem;margin-bottom:1.5rem;}
  .vb-tabs{display:flex;gap:.2rem;border-bottom:2px solid var(--mc-border);margin-bottom:1.5rem;flex-wrap:wrap;overflow-x:auto;}
  .vb-tab{padding:.5rem 1rem;border:none;background:none;font-size:.86rem;font-weight:600;color:var(--mc-muted);cursor:pointer;border-bottom:2px solid transparent;margin-bottom:-2px;white-space:nowrap;transition:all .15s;}
  .vb-tab:hover{color:var(--teal);}
  .vb-tab.on{color:var(--teal);border-bottom-color:var(--teal);}
  .vb-sec{display:none;}.vb-sec.on{display:block;}
  /* Result sub-tabs */
  .res-tabs{display:flex;gap:.15rem;border-bottom:2px solid #e2e8f0;margin-bottom:1.25rem;flex-wrap:wrap;overflow-x:auto;}
  .res-tab{padding:.45rem .9rem;border:none;background:none;font-size:.82rem;font-weight:600;color:#64748b;cursor:pointer;border-bottom:2px solid transparent;margin-bottom:-2px;white-space:nowrap;transition:all .15s;}
  .res-tab:hover{color:var(--teal);}
  .res-tab.on{color:var(--teal);border-bottom-color:var(--teal);}
  .res-sec{display:none;}.res-sec.on{display:block;}
  .vb-row{display:grid;grid-template-columns:1fr 1fr;gap:1rem;margin-bottom:1rem;}
  .vb-row3{display:grid;grid-template-columns:1fr 1fr 1fr;gap:1rem;margin-bottom:1rem;}
  .vb-row4{display:grid;grid-template-columns:1fr 1fr 1fr 1fr;gap:.75rem;margin-bottom:1rem;}
  .vb-lbl{font-size:.74rem;font-weight:700;text-transform:uppercase;letter-spacing:.05em;color:var(--mc-muted);margin-bottom:.3rem;}
  .vb-inp{width:100%;border:1.5px solid var(--mc-border);border-radius:10px;padding:.58rem .85rem;font-size:.88rem;outline:none;transition:border .15s;}
  .vb-inp:focus{border-color:var(--mc-primary);}
  .vb-sel{width:100%;border:1.5px solid var(--mc-border);border-radius:10px;padding:.58rem .85rem;font-size:.88rem;outline:none;background:#fff;}
  .pw{position:relative;}.pw .pre{position:absolute;left:.85rem;top:50%;transform:translateY(-50%);color:var(--mc-muted);font-size:.82rem;pointer-events:none;}
  .pw .suf{position:absolute;right:.85rem;top:50%;transform:translateY(-50%);color:var(--mc-muted);font-size:.82rem;pointer-events:none;}
  .pw .vb-inp.pl{padding-left:2.1rem;}.pw .vb-inp.pr{padding-right:2.1rem;}
  .vb-sep{font-size:.7rem;font-weight:700;text-transform:uppercase;letter-spacing:.07em;color:var(--mc-muted);padding:.55rem 0 .3rem;border-top:1px solid var(--mc-border);margin-top:.75rem;}
  .vb-hint{font-size:.72rem;color:var(--mc-muted);margin-top:.2rem;}
  /* Tipologias */
  .tip-hdr{display:grid;grid-template-columns:1.5fr .7fr 1fr 1fr .7fr .5fr .5fr auto;gap:.5rem;font-size:.68rem;font-weight:700;text-transform:uppercase;color:var(--mc-muted);margin-bottom:.4rem;}
  .tip-row{display:grid;grid-template-columns:1.5fr .7fr 1fr 1fr .7fr .5fr .5fr auto;gap:.5rem;margin-bottom:.5rem;align-items:center;}
  /* Fases */
  .fase-card{border:1px solid var(--mc-border);border-radius:12px;padding:1rem;margin-bottom:.75rem;}
  .fase-hdr{display:flex;justify-content:space-between;align-items:center;margin-bottom:.75rem;}
  /* KPIs */
  .kpi-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(155px,1fr));gap:.65rem;margin-bottom:1.25rem;}
  .kpi{background:#fff;border:1px solid var(--mc-border);border-radius:13px;padding:.9rem 1rem;box-shadow:0 1px 3px rgba(0,0,0,.05);}
  .kpi-l{font-size:.68rem;font-weight:700;text-transform:uppercase;letter-spacing:.06em;color:var(--mc-muted);}
  .kpi-v{font-size:21px;font-weight:700;letter-spacing:-.02em;margin-top:.2rem;}
  .kpi-f{font-size:.72rem;color:var(--mc-muted);margin-top:.15rem;}
  /* Large KPI cards */
  .kpi-large{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:.75rem;margin-bottom:1.5rem;}
  .kpi-card{background:#fff;border:1px solid var(--mc-border);border-radius:16px;padding:1.1rem 1.25rem;box-shadow:0 2px 6px rgba(0,0,0,.06);display:flex;align-items:flex-start;gap:.85rem;}
  .kpi-icon{width:42px;height:42px;border-radius:12px;display:flex;align-items:center;justify-content:center;font-size:1.2rem;flex-shrink:0;}
  .kpi-icon.teal{background:rgba(13,148,136,.12);color:#0d9488;}
  .kpi-icon.green{background:rgba(22,163,74,.12);color:#16a34a;}
  .kpi-icon.red{background:rgba(220,38,38,.12);color:#dc2626;}
  .kpi-icon.blue{background:rgba(59,130,246,.12);color:#2563eb;}
  .kpi-card-body{}
  .kpi-card-lbl{font-size:.69rem;font-weight:700;text-transform:uppercase;letter-spacing:.06em;color:#94a3b8;}
  .kpi-card-val{font-size:1.35rem;font-weight:700;letter-spacing:-.02em;margin-top:.15rem;line-height:1.2;}
  .kpi-card-sub{font-size:.72rem;color:#94a3b8;margin-top:.15rem;}
  /* Cenario badge */
  .cenario-badge{display:inline-flex;align-items:center;gap:.3rem;font-size:.74rem;font-weight:700;padding:.28rem .75rem;border-radius:999px;text-transform:capitalize;}
  .cenario-realista{background:rgba(13,148,136,.1);color:#0d9488;border:1px solid rgba(13,148,136,.2);}
  .cenario-otimista{background:rgba(22,163,74,.1);color:#16a34a;border:1px solid rgba(22,163,74,.2);}
  .cenario-pessimista{background:rgba(239,68,68,.1);color:#dc2626;border:1px solid rgba(239,68,68,.2);}
  /* DRE table */
  .dre-table{width:100%;border-collapse:collapse;font-size:.85rem;}
  .dre-table td{padding:.42rem .75rem;border-bottom:1px solid #f1f5f9;}
  .dre-row-subtotal td{background:#f0fdfa;font-weight:700;color:#0d9488;border-top:1.5px solid #99f6e4;}
  .dre-row-resultado td{background:#0d9488;color:#fff;font-weight:700;}
  .dre-row-pct td{background:#f0fdfa;font-style:italic;color:#0f766e;}
  .dre-row-receita td{font-weight:600;}
  .dre-val{text-align:right;font-variant-numeric:tabular-nums;}
  /* Breakdown */
  .bk{border:1px solid var(--mc-border);border-radius:12px;overflow:hidden;margin-bottom:1rem;}
  .bk-r{display:flex;justify-content:space-between;padding:.48rem 1rem;font-size:.86rem;border-bottom:1px solid var(--mc-border);}
  .bk-r:last-child{border-bottom:0;}
  .bk-t{font-weight:700;background:var(--mc-primary-soft);}
  .bk-l{color:var(--mc-muted);}
  /* Fluxo de caixa */
  .fc-table{width:100%;border-collapse:collapse;font-size:.78rem;}
  .fc-table th{background:var(--mc-primary);color:#fff;padding:.4rem .6rem;text-align:right;position:sticky;top:0;}
  .fc-table th:first-child{text-align:left;}
  .fc-table td{padding:.35rem .6rem;text-align:right;border-bottom:1px solid var(--mc-border);}
  .fc-table td:first-child{text-align:left;font-weight:600;}
  .fc-table tr:hover td{background:#f9fafb;}
  .fc-pos{color:#16a34a;}
  .fc-neg{color:#dc2626;}
  .fc-wrap{max-height:480px;overflow-y:auto;border:1px solid var(--mc-border);border-radius:12px;}
  /* Verdict */
  .verdict{border-radius:14px;padding:1rem 1.2rem;border:1px solid var(--mc-border);background:#fff;margin-bottom:1.25rem;}
  .v-badge{display:inline-flex;align-items:center;gap:.4rem;font-size:.74rem;font-weight:700;text-transform:uppercase;letter-spacing:.07em;padding:.28rem .7rem;border-radius:999px;margin-bottom:.55rem;}
  .v-badge.success{background:rgba(22,163,74,.12);color:#166534;}
  .v-badge.primary{background:rgba(59,130,246,.12);color:#1e40af;}
  .v-badge.warning{background:rgba(202,138,4,.12);color:#854d0e;}
  .v-badge.danger{background:rgba(220,38,38,.12);color:#991b1b;}
  /* Toggle switch */
  .vb-toggle-wrap{display:flex;align-items:center;gap:.75rem;padding:.75rem 0;margin-bottom:.5rem;}
  .vb-toggle{position:relative;width:46px;height:25px;flex-shrink:0;}
  .vb-toggle input{opacity:0;width:0;height:0;}
  .vb-toggle-slider{position:absolute;cursor:pointer;top:0;left:0;right:0;bottom:0;background:#d1d5db;border-radius:25px;transition:.3s;}
  .vb-toggle-slider:before{position:absolute;content:"";height:19px;width:19px;left:3px;bottom:3px;background:#fff;border-radius:50%;transition:.3s;}
  .vb-toggle input:checked + .vb-toggle-slider{background:var(--mc-primary);}
  .vb-toggle input:checked + .vb-toggle-slider:before{transform:translateX(21px);}
  #finInputs{transition:opacity .2s;}
  /* Heatmap sensibilidade */
  .sen-table{width:100%;border-collapse:collapse;font-size:.8rem;}
  .sen-table th{background:#1e293b;color:#fff;padding:.45rem .6rem;text-align:center;font-size:.72rem;}
  .sen-table td{padding:.4rem .6rem;text-align:center;border:1px solid var(--mc-border);font-weight:600;}
  .sen-green{background:#dcfce7;color:#166534;}
  .sen-yellow{background:#fef9c3;color:#854d0e;}
  .sen-red{background:#fee2e2;color:#991b1b;}
  /* Fin schedule */
  .fs-table{width:100%;border-collapse:collapse;font-size:.78rem;}
  .fs-table th{background:#1e293b;color:#fff;padding:.4rem .6rem;text-align:right;}
  .fs-table th:first-child{text-align:left;}
  .fs-table td{padding:.35rem .6rem;text-align:right;border-bottom:1px solid var(--mc-border);}
  .fs-table td:first-child{text-align:left;font-weight:600;}
  .fs-wrap{max-height:380px;overflow-y:auto;border:1px solid var(--mc-border);border-radius:12px;margin-top:.5rem;}
  @media(max-width:640px){.vb-row,.vb-row3,.vb-row4{grid-template-columns:1fr;}.tip-hdr,.tip-row{grid-template-columns:1fr 1fr 1fr auto;}.tip-hdr span:nth-child(4),.tip-row>div:nth-child(4),.tip-hdr span:nth-child(5),.tip-row>div:nth-child(5),.tip-hdr span:nth-child(6),.tip-row>div:nth-child(6),.tip-hdr span:nth-child(7),.tip-row>div:nth-child(7){display:none;}}
  @media print{.vb-tabs,form button,nav,.navbar,aside,#augurCard{display:none!important;}.vb-sec{display:block!important;}.card{page-break-inside:avoid;}}
</style>

<div class="vb-hdr">
  <div>
    <a href="/ferramentas" class="btn btn-outline-secondary btn-sm mb-2"><i class="bi bi-arrow-left"></i> Ferramentas</a>
    <div style="display:flex;align-items:center;gap:.75rem;flex-wrap:wrap;">
      <h4 class="mb-0">{% if dados and dados.nome_projeto %}{{ dados.nome_projeto }}{% else %}Viabilidade Imobiliária{% endif %}</h4>
      {% if resultado %}
      {% set _cn = resultado.cenario or 'realista' %}
      <span class="cenario-badge cenario-{{ _cn }}">
        {% if _cn == 'otimista' %}<i class="bi bi-arrow-up-right"></i>{% elif _cn == 'pessimista' %}<i class="bi bi-arrow-down-right"></i>{% else %}<i class="bi bi-dash"></i>{% endif %}
        {{ _cn|capitalize }}
      </span>
      {% endif %}
    </div>
    <div class="muted small">Análise completa com fluxo de caixa mensal, TIR, VPL e DRE</div>
  </div>
  <div style="display:flex;gap:.5rem;flex-wrap:wrap;align-items:center;">
    {% if resultado %}
    <button type="button" class="btn btn-sm" style="background:#0d9488;color:#fff;border:none;" onclick="vbTab('premissas',document.querySelector('[onclick*=premissas]'));setTimeout(()=>document.getElementById('vbForm').submit(),100);">
      <i class="bi bi-arrow-clockwise me-1"></i> Recalcular
    </button>
    <button onclick="window.print()" class="btn btn-outline-secondary btn-sm">
      <i class="bi bi-printer me-1"></i> Exportar PDF
    </button>
    {% endif %}
  </div>
</div>

<form method="post" action="/ferramentas/viabilidade/calcular" id="vbForm">
<div class="vb-tabs">
  <button type="button" class="vb-tab on" onclick="vbTab('premissas',this)">📋 Premissas</button>
  <button type="button" class="vb-tab" onclick="vbTab('produto',this)">🏢 Produto &amp; VGV</button>
  <button type="button" class="vb-tab" onclick="vbTab('custos',this)">🔨 Custos</button>
  <button type="button" class="vb-tab" onclick="vbTab('comercial',this)">📈 Comercialização</button>
  <button type="button" class="vb-tab" onclick="vbTab('financiamento',this)">💰 Financiamento</button>
  {% if resultado %}<button type="button" class="vb-tab" onclick="vbTab('resultado',this)">✅ Resultado</button>{% endif %}
</div>

{# ── ABA 1: PREMISSAS ── #}
<div class="vb-sec on card p-4 mb-3" id="tab-premissas">
  <h5 class="mb-3">Premissas do Projeto</h5>
  <div class="vb-row">
    <div><div class="vb-lbl">Nome do Projeto</div><input class="vb-inp" type="text" name="nome_projeto" placeholder="Ex: Residencial Jardins" value="{{ dados.nome_projeto or '' }}"></div>
    <div><div class="vb-lbl">Área do Terreno (m²)</div><input class="vb-inp" type="number" name="area_terreno" step="0.01" min="0" required placeholder="1.918,80" value="{{ dados.area_terreno or '' }}"></div>
  </div>
  <div class="vb-row3">
    <div><div class="vb-lbl">Índice de Aproveitamento</div><input class="vb-inp" type="number" name="indice_aproveitamento" step="0.01" min="0" placeholder="5.0" value="{{ dados.indice_aproveitamento or '5' }}"></div>
    <div><div class="vb-lbl">Índice c/ Outorga</div><input class="vb-inp" type="number" name="indice_outorga" step="0.01" min="0" placeholder="6.5" value="{{ dados.indice_outorga or '0' }}"></div>
    <div><div class="vb-lbl">Taxa de Ocupação (%)</div><input class="vb-inp" type="number" name="taxa_ocupacao" step="1" min="0" max="100" placeholder="85" value="{{ dados.taxa_ocupacao or '85' }}"></div>
  </div>
  <div class="vb-row3">
    <div><div class="vb-lbl">Permeabilidade (%)</div><input class="vb-inp" type="number" name="permeabilidade" step="1" min="0" max="100" placeholder="15" value="{{ dados.permeabilidade or '15' }}"></div>
    <div><div class="vb-lbl">% Permuta do Terreno</div><input class="vb-inp" type="number" name="pct_permuta" step="0.5" min="0" max="100" placeholder="13.75" value="{{ dados.pct_permuta or '0' }}"><div class="vb-hint">0% = compra total · 100% = permuta total</div></div>
    <div><div class="vb-lbl">Valor do Terreno (R$)</div><div class="pw"><span class="pre">R$</span><input class="vb-inp pl" type="number" name="valor_terreno" step="1000" min="0" placeholder="0" value="{{ dados.valor_terreno or '0' }}"></div><div class="vb-hint">Se permuta, deixe 0</div></div>
  </div>
  <div class="vb-row">
    <div>
      <div class="vb-lbl">Cenário de Análise</div>
      <select class="vb-sel" name="cenario">
        <option value="realista" {% if not dados or dados.cenario == 'realista' or not dados.cenario %}selected{% endif %}>Realista (base)</option>
        <option value="otimista" {% if dados and dados.cenario == 'otimista' %}selected{% endif %}>Otimista (+15% VGV)</option>
        <option value="pessimista" {% if dados and dados.cenario == 'pessimista' %}selected{% endif %}>Pessimista (−15% VGV)</option>
      </select>
      <div class="vb-hint">Multiplica o preço/m² por 1,15 ou 0,85</div>
    </div>
    <div></div>
  </div>
  <div class="vb-sep">Cronograma</div>
  <div class="vb-row3">
    <div><div class="vb-lbl">Mês de Início da Obra</div><input class="vb-inp" type="number" name="mes_inicio_obra" step="1" min="1" placeholder="12" value="{{ dados.mes_inicio_obra or '12' }}"><div class="vb-hint">Relativo ao lançamento (mês 1)</div></div>
    <div><div class="vb-lbl">Duração da Obra (meses)</div><input class="vb-inp" type="number" name="duracao_obra" step="1" min="6" placeholder="60" value="{{ dados.duracao_obra or '60' }}"></div>
    <div><div class="vb-lbl">Início das Vendas (mês)</div><input class="vb-inp" type="number" name="mes_inicio_vendas" step="1" min="1" placeholder="3" value="{{ dados.mes_inicio_vendas or '3' }}"><div class="vb-hint">Relativo ao lançamento</div></div>
  </div>
  <div class="d-flex justify-content-end mt-3">
    <button type="button" class="btn btn-primary" onclick="vbTab('produto',document.querySelector('[onclick*=produto]'))">Produto &amp; VGV <i class="bi bi-arrow-right ms-1"></i></button>
  </div>
</div>

{# ── ABA 2: PRODUTO ── #}
<div class="vb-sec card p-4 mb-3" id="tab-produto">
  <h5 class="mb-3">Produto &amp; VGV</h5>
  <div class="vb-row">
    <div><div class="vb-lbl">Preço base (R$/m²)</div><div class="pw"><span class="pre">R$</span><input class="vb-inp pl" type="number" name="preco_m2_base" step="100" min="0" placeholder="12.500" value="{{ dados.preco_m2_base or '12500' }}"></div></div>
    <div><div class="vb-lbl">Diferencial por andar (%)</div><div class="pw"><span class="suf">%</span><input class="vb-inp pr" type="number" name="diferencial_andar" step="0.1" min="0" max="5" placeholder="0.5" value="{{ dados.diferencial_andar or '0.5' }}"></div><div class="vb-hint">Incremento no preço/m² a cada andar</div></div>
  </div>
  <div class="vb-sep">Tipologias</div>
  <div class="tip-hdr">
    <span>Nome / Descrição</span><span>Tipo</span><span>Metragem (m²)</span><span>Qtd</span><span>Preço/m²</span><span>Andar ini.</span><span>Permuta</span><span></span>
  </div>
  <div id="tipCont">
    {% set tips = dados.tipologias if dados.tipologias else [] %}
    {% if not tips %}
    <div class="tip-row" id="tip-0">
      <div><input class="vb-inp" type="text" name="tip_nome_0" placeholder="Apart. 101"></div>
      <div><select class="vb-sel" name="tip_tipo_0"><option>Residencial</option><option>Comercial</option></select></div>
      <div><input class="vb-inp" type="number" name="tip_metragem_0" step="0.5" min="0" placeholder="102"></div>
      <div><input class="vb-inp" type="number" name="tip_qtd_0" step="1" min="0" placeholder="1"></div>
      <div><div class="pw"><span class="pre">R$</span><input class="vb-inp pl" type="number" name="tip_preco_0" step="100" placeholder="12.500"></div></div>
      <div><input class="vb-inp" type="number" name="tip_andar_0" step="1" min="1" placeholder="1"></div>
      <div style="display:flex;align-items:center;gap:.3rem;"><input type="checkbox" name="tip_permuta_0" value="1" id="perm0"><label for="perm0" style="font-size:.8rem;">Sim</label></div>
      <div></div>
    </div>
    {% else %}
    {% for t in tips %}
    <div class="tip-row" id="tip-{{ loop.index0 }}">
      <div><input class="vb-inp" type="text" name="tip_nome_{{ loop.index0 }}" value="{{ t.nome or '' }}" placeholder="Nome"></div>
      <div><select class="vb-sel" name="tip_tipo_{{ loop.index0 }}"><option {% if t.tipo=='Residencial' %}selected{% endif %}>Residencial</option><option {% if t.tipo=='Comercial' %}selected{% endif %}>Comercial</option></select></div>
      <div><input class="vb-inp" type="number" name="tip_metragem_{{ loop.index0 }}" step="0.5" value="{{ t.metragem }}"></div>
      <div><input class="vb-inp" type="number" name="tip_qtd_{{ loop.index0 }}" step="1" value="{{ t.quantidade }}"></div>
      <div><div class="pw"><span class="pre">R$</span><input class="vb-inp pl" type="number" name="tip_preco_{{ loop.index0 }}" step="100" value="{{ t.preco_m2 }}"></div></div>
      <div><input class="vb-inp" type="number" name="tip_andar_{{ loop.index0 }}" step="1" value="{{ t.andar_inicio }}"></div>
      <div style="display:flex;align-items:center;gap:.3rem;"><input type="checkbox" name="tip_permuta_{{ loop.index0 }}" value="1" id="perm{{ loop.index0 }}" {% if t.permuta %}checked{% endif %}><label for="perm{{ loop.index0 }}" style="font-size:.8rem;">Sim</label></div>
      <div><button type="button" class="btn btn-sm btn-outline-danger" onclick="rmTip({{ loop.index0 }})">×</button></div>
    </div>
    {% endfor %}
    {% endif %}
  </div>
  <button type="button" class="btn btn-outline-secondary btn-sm mt-2" onclick="addTip()"><i class="bi bi-plus-circle me-1"></i> Adicionar tipologia</button>
  <div class="d-flex justify-content-between mt-3">
    <button type="button" class="btn btn-outline-secondary" onclick="vbTab('premissas',document.querySelector('[onclick*=premissas]'))"><i class="bi bi-arrow-left me-1"></i> Voltar</button>
    <button type="button" class="btn btn-primary" onclick="vbTab('custos',document.querySelector('[onclick*=custos]'))">Custos <i class="bi bi-arrow-right ms-1"></i></button>
  </div>
</div>

{# ── ABA 3: CUSTOS ── #}
<div class="vb-sec card p-4 mb-3" id="tab-custos">
  <h5 class="mb-3">Custos de Produção</h5>
  <div class="vb-sep">CUB e Área Equivalente</div>
  <div class="vb-row3">
    <div><div class="vb-lbl">CUB de Referência (R$/m²)</div><div class="pw"><span class="pre">R$</span><input class="vb-inp pl" type="number" name="cub_m2" step="10" min="0" placeholder="3.019" value="{{ dados.cub_m2 or '3019' }}"></div><div class="vb-hint">CUB ajustado para o projeto</div></div>
    <div><div class="vb-lbl">Área de Garagem (m²)</div><input class="vb-inp" type="number" name="area_garagem" step="1" min="0" placeholder="5.583" value="{{ dados.area_garagem or '0' }}"></div>
    <div><div class="vb-lbl">Coef. Equivalente Garagem</div><input class="vb-inp" type="number" name="coef_garagem" step="0.05" min="0" max="1" placeholder="0.70" value="{{ dados.coef_garagem or '0.7' }}"><div class="vb-hint">Padrão NBR 12.721: 0,50–0,75</div></div>
  </div>
  <div class="vb-row">
    <div><div class="vb-lbl">Área Residual (m²)</div><input class="vb-inp" type="number" name="area_residual" step="1" min="0" placeholder="6.888" value="{{ dados.area_residual or '0' }}"><div class="vb-hint">Área total construída menos garagem e área privativa</div></div>
    <div><div class="vb-lbl">Eficiência da Planta (%)</div><div class="pw"><span class="suf">%</span><input class="vb-inp pr" type="number" name="eficiencia" step="1" min="10" max="90" placeholder="50" value="{{ dados.eficiencia or '50' }}"></div><div class="vb-hint">Usada se garagem e residual não preenchidos</div></div>
  </div>
  <div class="vb-sep">Itens fora do CUB</div>
  <div class="vb-row3">
    <div><div class="vb-lbl">Número de Elevadores</div><input class="vb-inp" type="number" name="n_elevadores" step="1" min="0" placeholder="4" value="{{ dados.n_elevadores or '0' }}"></div>
    <div><div class="vb-lbl">Valor por Elevador (R$)</div><div class="pw"><span class="pre">R$</span><input class="vb-inp pl" type="number" name="vl_elevador" step="10000" min="0" placeholder="380.000" value="{{ dados.vl_elevador or '380000' }}"></div></div>
    <div><div class="vb-lbl">Recreação / Lazer (R$)</div><div class="pw"><span class="pre">R$</span><input class="vb-inp pl" type="number" name="vl_recreacao" step="10000" min="0" placeholder="780.000" value="{{ dados.vl_recreacao or '0' }}"></div></div>
  </div>
  <div class="vb-row">
    <div><div class="vb-lbl">Outros itens fora CUB (R$)</div><div class="pw"><span class="pre">R$</span><input class="vb-inp pl" type="number" name="vl_outros_cub" step="10000" min="0" placeholder="0" value="{{ dados.vl_outros_cub or '0' }}"></div></div>
    <div><div class="vb-lbl">Despesas Indiretas (%)</div><div class="pw"><span class="suf">%</span><input class="vb-inp pr" type="number" name="pct_indiretos" step="0.5" min="0" max="30" placeholder="6.5" value="{{ dados.pct_indiretos or '6.5' }}"></div><div class="vb-hint">Gerenciamento, projetos, laudos, seguros</div></div>
  </div>
  <div class="vb-sep">Comercialização e Impostos (% sobre VGV líquido)</div>
  <div class="vb-row4">
    <div><div class="vb-lbl">Corretagem (%)</div><div class="pw"><span class="suf">%</span><input class="vb-inp pr" type="number" name="pct_corretagem" step="0.1" min="0" placeholder="5.0" value="{{ dados.pct_corretagem or '5.0' }}"></div></div>
    <div><div class="vb-lbl">Gestão Comercial (%)</div><div class="pw"><span class="suf">%</span><input class="vb-inp pr" type="number" name="pct_gestao_comercial" step="0.1" min="0" placeholder="1.5" value="{{ dados.pct_gestao_comercial or '1.5' }}"></div></div>
    <div><div class="vb-lbl">Marketing (%)</div><div class="pw"><span class="suf">%</span><input class="vb-inp pr" type="number" name="pct_marketing" step="0.1" min="0" placeholder="0.75" value="{{ dados.pct_marketing or '0.75' }}"></div></div>
    <div><div class="vb-lbl">Outros comerciais (%)</div><div class="pw"><span class="suf">%</span><input class="vb-inp pr" type="number" name="pct_outros_com" step="0.1" min="0" placeholder="1.2" value="{{ dados.pct_outros_com or '1.2' }}"></div></div>
  </div>
  <div class="vb-row">
    <div><div class="vb-lbl">Impostos sobre Receita (%)</div><div class="pw"><span class="suf">%</span><input class="vb-inp pr" type="number" name="pct_impostos" step="0.5" min="0" placeholder="4.0" value="{{ dados.pct_impostos or '4.0' }}"></div></div>
    <div></div>
  </div>
  <div class="d-flex justify-content-between mt-3">
    <button type="button" class="btn btn-outline-secondary" onclick="vbTab('produto',document.querySelector('[onclick*=produto]'))"><i class="bi bi-arrow-left me-1"></i> Voltar</button>
    <button type="button" class="btn btn-primary" onclick="vbTab('comercial',document.querySelector('[onclick*=comercial]'))">Comercialização <i class="bi bi-arrow-right ms-1"></i></button>
  </div>
</div>

{# ── ABA 4: COMERCIALIZAÇÃO ── #}
<div class="vb-sec card p-4 mb-3" id="tab-comercial">
  <h5 class="mb-3">Fases de Comercialização</h5>
  <div class="vb-row">
    <div><div class="vb-lbl">Correção durante obra (% a.m.)</div><div class="pw"><span class="suf">%</span><input class="vb-inp pr" type="number" name="correcao_obra" step="0.01" min="0" placeholder="0.52" value="{{ dados.correcao_obra or '0.52' }}"></div></div>
    <div><div class="vb-lbl">Correção pós-obra (% a.m.)</div><div class="pw"><span class="suf">%</span><input class="vb-inp pr" type="number" name="correcao_pos_obra" step="0.01" min="0" placeholder="1.04" value="{{ dados.correcao_pos_obra or '1.04' }}"></div></div>
  </div>
  <div class="vb-sep">Fases de Venda</div>
  <div id="faseCont">
    {% set fases_dados = dados.fases if dados.fases else [
      {"nome":"Lançamento","meta":15,"reajuste":-15,"duracao":12,"entrada_pct":10,"parcelas_pct":90,"n_parcelas":24,"reforco_pct":0,"n_reforcos":0},
      {"nome":"Pós-Lançamento","meta":85,"reajuste":5,"duracao":24,"entrada_pct":15,"parcelas_pct":40,"n_parcelas":48,"reforco_pct":25,"n_reforcos":4}
    ] %}
    {% for f in fases_dados %}
    <div class="fase-card" id="fase-{{ loop.index0 }}">
      <div class="fase-hdr">
        <input class="vb-inp" type="text" name="fase_nome_{{ loop.index0 }}" value="{{ f.nome }}" placeholder="Nome da fase" style="max-width:200px;">
        <button type="button" class="btn btn-sm btn-outline-danger" onclick="rmFase({{ loop.index0 }})">Remover fase</button>
      </div>
      <div class="vb-row4">
        <div><div class="vb-lbl">Meta de Vendas (%)</div><div class="pw"><span class="suf">%</span><input class="vb-inp pr" type="number" name="fase_meta_{{ loop.index0 }}" step="1" min="0" max="100" value="{{ f.meta }}"></div></div>
        <div><div class="vb-lbl">Reajuste de Preço (%)</div><div class="pw"><span class="suf">%</span><input class="vb-inp pr" type="number" name="fase_reajuste_{{ loop.index0 }}" step="1" value="{{ f.reajuste }}"></div><div class="vb-hint">Negativo = desconto</div></div>
        <div><div class="vb-lbl">Duração (meses)</div><input class="vb-inp" type="number" name="fase_duracao_{{ loop.index0 }}" step="1" min="1" value="{{ f.duracao }}"></div>
        <div><div class="vb-lbl">Entrada (%)</div><div class="pw"><span class="suf">%</span><input class="vb-inp pr" type="number" name="fase_entrada_{{ loop.index0 }}" step="1" min="0" max="100" value="{{ f.entrada_pct }}"></div></div>
      </div>
      <div class="vb-row4">
        <div><div class="vb-lbl">Parcelas (%)</div><div class="pw"><span class="suf">%</span><input class="vb-inp pr" type="number" name="fase_parcelas_{{ loop.index0 }}" step="1" min="0" max="100" value="{{ f.parcelas_pct }}"></div></div>
        <div><div class="vb-lbl">Nº de Parcelas</div><input class="vb-inp" type="number" name="fase_nparcelas_{{ loop.index0 }}" step="1" min="1" value="{{ f.n_parcelas }}"></div>
        <div><div class="vb-lbl">Reforços (%)</div><div class="pw"><span class="suf">%</span><input class="vb-inp pr" type="number" name="fase_reforco_{{ loop.index0 }}" step="1" min="0" max="100" value="{{ f.reforco_pct }}"></div></div>
        <div><div class="vb-lbl">Nº de Reforços</div><input class="vb-inp" type="number" name="fase_nreforcos_{{ loop.index0 }}" step="1" min="0" value="{{ f.n_reforcos }}"></div>
      </div>
    </div>
    {% endfor %}
  </div>
  <button type="button" class="btn btn-outline-secondary btn-sm mt-1" onclick="addFase()"><i class="bi bi-plus-circle me-1"></i> Adicionar fase</button>
  <div class="d-flex justify-content-between mt-3">
    <button type="button" class="btn btn-outline-secondary" onclick="vbTab('custos',document.querySelector('[onclick*=custos]'))"><i class="bi bi-arrow-left me-1"></i> Voltar</button>
    <button type="button" class="btn btn-primary" onclick="vbTab('financiamento',document.querySelector('[onclick*=financiamento]'))">Financiamento <i class="bi bi-arrow-right ms-1"></i></button>
  </div>
</div>

{# ── ABA 5: FINANCIAMENTO ── #}
<div class="vb-sec card p-4 mb-3" id="tab-financiamento">
  <h5 class="mb-3">Simulação de Financiamento de Obra</h5>
  <div class="vb-toggle-wrap">
    <label class="vb-toggle">
      <input type="checkbox" name="usar_financiamento" value="1" id="toggleFin" onchange="toggleFinInputs(this)" {% if dados.usar_financiamento == '1' %}checked{% endif %}>
      <span class="vb-toggle-slider"></span>
    </label>
    <span style="font-weight:600;font-size:.95rem;">Simular financiamento de obra</span>
    <span class="vb-hint ms-1">(linha de crédito à produção / SFH)</span>
  </div>

  <div id="finInputs" style="{% if dados.usar_financiamento != '1' %}opacity:.4;pointer-events:none;{% endif %}">
    <div class="vb-sep">Estrutura do Crédito</div>
    <div class="vb-row3">
      <div><div class="vb-lbl">% do Custo Financiado</div><div class="pw"><span class="suf">%</span><input class="vb-inp pr" type="number" name="pct_fin" step="1" min="0" max="100" placeholder="70" value="{{ dados.pct_fin or '70' }}"></div><div class="vb-hint">Parcela do custo de obra coberta pelo crédito</div></div>
      <div><div class="vb-lbl">Taxa de Juros a.m. (%)</div><div class="pw"><span class="suf">%</span><input class="vb-inp pr" type="number" name="taxa_juros_am" step="0.01" min="0" placeholder="1.20" value="{{ dados.taxa_juros_am or '1.20' }}"></div><div class="vb-hint">Taxa efetiva mensal do financiamento</div></div>
      <div><div class="vb-lbl">Sistema de Amortização</div><select class="vb-sel" name="tipo_amortizacao"><option value="SAC" {% if dados.tipo_amortizacao == 'SAC' or not dados.tipo_amortizacao %}selected{% endif %}>SAC — amortização constante</option><option value="PRICE" {% if dados.tipo_amortizacao == 'PRICE' %}selected{% endif %}>PRICE — parcela constante</option></select></div>
    </div>
    <div class="vb-row">
      <div><div class="vb-lbl">Carência (meses)</div><input class="vb-inp" type="number" name="carencia_meses" step="1" min="0" placeholder="6" value="{{ dados.carencia_meses or '6' }}"><div class="vb-hint">Meses de juros apenas (sem amortizar) após término da obra</div></div>
      <div><div class="vb-lbl">TMA de Referência (CDI % a.a.)</div><div class="pw"><span class="suf">%</span><input class="vb-inp pr" type="number" name="cdi_ref" step="0.25" min="0" placeholder="13.75" value="{{ dados.cdi_ref or '13.75' }}"></div><div class="vb-hint">Benchmark para cálculo do spread</div></div>
    </div>

    <div class="vb-sep">Estrutura CRI (Certificado de Recebíveis Imobiliários)</div>
    <div class="vb-row">
      <div><div class="vb-lbl">Haircut CRI (%)</div><div class="pw"><span class="suf">%</span><input class="vb-inp pr" type="number" name="haircut_pct" step="1" min="0" max="80" placeholder="20" value="{{ dados.haircut_pct or '20' }}"></div><div class="vb-hint">Desconto aplicado sobre carteira de recebíveis</div></div>
      <div><div class="vb-lbl">% Subordinação</div><div class="pw"><span class="suf">%</span><input class="vb-inp pr" type="number" name="sub_ratio" step="1" min="0" max="80" placeholder="20" value="{{ dados.sub_ratio or '20' }}"></div><div class="vb-hint">Cota subordinada para proteção da cota sênior</div></div>
    </div>
  </div>

  <div class="d-flex justify-content-between mt-3">
    <button type="button" class="btn btn-outline-secondary" onclick="vbTab('comercial',document.querySelector('[onclick*=comercial]'))"><i class="bi bi-arrow-left me-1"></i> Voltar</button>
    <button type="button" class="btn btn-primary px-4" id="calcBtn" onclick="document.getElementById('vbForm').submit()">
      <i class="bi bi-calculator me-2"></i> Calcular Viabilidade
    </button>
  </div>
</div>

{# ── ABA 6: RESULTADO ── #}
{% if resultado %}
{% set r = resultado %}
{% set st = r.status %}
{% set ia = r.indicadores_adicionais %}
{% set fin = r.financiamento %}
{% set sen = r.sensibilidade %}
<div class="vb-sec card p-4 mb-3" id="tab-resultado">

  {# Verdict banner #}
  <div class="verdict mb-3">
    <div class="v-badge {{ st.color }}">{{ st.icon }} {{ st.label }}</div>
    <div style="font-size:.9rem;line-height:1.5;">{{ st.desc }}</div>
  </div>

  {# 4 Large KPI cards #}
  <div class="kpi-large">
    <div class="kpi-card">
      <div class="kpi-icon teal"><i class="bi bi-graph-up-arrow"></i></div>
      <div class="kpi-card-body">
        <div class="kpi-card-lbl">Resultado Bruto</div>
        <div class="kpi-card-val" style="color:{{ '#16a34a' if r.resultado_bruto >= 0 else '#dc2626' }};">{{ r.resultado_bruto|brl }}</div>
        <div class="kpi-card-sub">{{ r.margem_vgv }}% sobre VGV líquido</div>
      </div>
    </div>
    <div class="kpi-card">
      <div class="kpi-icon green"><i class="bi bi-percent"></i></div>
      <div class="kpi-card-body">
        <div class="kpi-card-lbl">Lucratividade</div>
        <div class="kpi-card-val" style="color:{{ '#16a34a' if r.margem_custo >= 20 else ('#ca8a04' if r.margem_custo >= 10 else '#dc2626') }};">{{ r.margem_custo }}%</div>
        <div class="kpi-card-sub">Margem sobre custo total</div>
      </div>
    </div>
    <div class="kpi-card">
      <div class="kpi-icon blue"><i class="bi bi-bar-chart-line"></i></div>
      <div class="kpi-card-body">
        <div class="kpi-card-lbl">VPL (TMA 12% a.a.)</div>
        <div class="kpi-card-val" style="color:{{ '#16a34a' if r.vpl and r.vpl >= 0 else '#dc2626' }};">{% if r.vpl %}{{ r.vpl|brl }}{% else %}—{% endif %}</div>
        <div class="kpi-card-sub">Valor presente líquido</div>
      </div>
    </div>
    <div class="kpi-card">
      <div class="kpi-icon red"><i class="bi bi-arrow-down-circle"></i></div>
      <div class="kpi-card-body">
        <div class="kpi-card-lbl">Exposição Máxima</div>
        <div class="kpi-card-val" style="color:#dc2626;">{{ r.exposicao_maxima|brl }}</div>
        <div class="kpi-card-sub">Capital necessário no pico</div>
      </div>
    </div>
  </div>

  {# ── PAINEL DE FINANCIAMENTO (quando ativo) ── #}
  {% if fin %}
  <div style="border:2px solid #1e40af;border-radius:14px;padding:1.1rem 1.25rem;margin-bottom:1.25rem;background:#eff6ff;">
    <div class="d-flex align-items-center gap-2 mb-3">
      <i class="bi bi-bank2" style="font-size:1.2rem;color:#1e40af;"></i>
      <strong style="color:#1e40af;font-size:.95rem;">Financiamento Ativo — {{ fin.tipo_amortizacao }} · {{ fin.pct_fin }}% da obra · {{ fin.taxa_am }}% a.m. · {{ fin.carencia }} meses de carência</strong>
    </div>
    {# Linha 1: valor financiado e custo #}
    <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:.75rem;margin-bottom:.9rem;">
      <div style="background:#fff;border-radius:10px;padding:.7rem .9rem;border:1px solid #bfdbfe;">
        <div style="font-size:.68rem;font-weight:700;text-transform:uppercase;color:#1e40af;letter-spacing:.05em;">Crédito captado (pico)</div>
        <div style="font-size:1.15rem;font-weight:700;color:#1e40af;">{{ fin.valor_financiado|brl }}</div>
        <div style="font-size:.72rem;color:#64748b;">Saldo devedor máximo durante a obra</div>
      </div>
      <div style="background:#fff;border-radius:10px;padding:.7rem .9rem;border:1px solid #fca5a5;">
        <div style="font-size:.68rem;font-weight:700;text-transform:uppercase;color:#dc2626;letter-spacing:.05em;">Custo financeiro total (juros)</div>
        <div style="font-size:1.15rem;font-weight:700;color:#dc2626;">{{ fin.custo_fin_total|brl }}</div>
        <div style="font-size:.72rem;color:#64748b;">{{ "%.1f"|format(fin.custo_fin_total / r.vgv_liquido * 100 if r.vgv_liquido else 0) }}% do VGV líquido</div>
      </div>
      <div style="background:#fff;border-radius:10px;padding:.7rem .9rem;border:1px solid #bbf7d0;">
        <div style="font-size:.68rem;font-weight:700;text-transform:uppercase;color:#16a34a;letter-spacing:.05em;">Redução da exposição</div>
        <div style="font-size:1.15rem;font-weight:700;color:#16a34a;">{{ fin.reducao_exposicao|brl }}</div>
        <div style="font-size:.72rem;color:#64748b;">Capital próprio que o crédito substitui</div>
      </div>
      {% if fin.tir_alavancada %}
      <div style="background:#fff;border-radius:10px;padding:.7rem .9rem;border:1px solid #e0e7ff;">
        <div style="font-size:.68rem;font-weight:700;text-transform:uppercase;color:#6366f1;letter-spacing:.05em;">TIR alavancada</div>
        <div style="font-size:1.15rem;font-weight:700;color:#6366f1;">{{ fin.tir_alavancada }}% a.a.</div>
        <div style="font-size:.72rem;color:#64748b;">Retorno sobre o equity investido</div>
      </div>
      {% endif %}
    </div>
    {# Linha 2: comparação antes/depois #}
    <div style="background:#fff;border-radius:10px;padding:.75rem 1rem;border:1px solid #bfdbfe;">
      <div style="font-size:.72rem;font-weight:700;text-transform:uppercase;color:#1e40af;margin-bottom:.6rem;">Impacto do financiamento nos resultados</div>
      <div style="display:grid;grid-template-columns:1fr auto 1fr;gap:.5rem;align-items:center;">
        <div>
          <div style="font-size:.7rem;color:#64748b;font-weight:600;margin-bottom:.3rem;">SEM FINANCIAMENTO</div>
          <div style="font-size:.88rem;"><span style="color:#64748b;">Resultado:</span> <strong>{{ fin.resultado_sem_fin|brl }}</strong></div>
          <div style="font-size:.88rem;"><span style="color:#64748b;">Margem VGV:</span> <strong>{{ fin.margem_sem_fin }}%</strong></div>
          <div style="font-size:.88rem;"><span style="color:#64748b;">Exposição:</span> <strong style="color:#dc2626;">{{ (fin.resultado_sem_fin + fin.reducao_exposicao)|abs|brl }}</strong></div>
          <div style="font-size:.88rem;"><span style="color:#64748b;">TIR:</span> <strong>{% if r.tir_anual %}{{ r.tir_anual }}% a.a.{% else %}—{% endif %}</strong></div>
        </div>
        <div style="text-align:center;padding:0 .5rem;">
          <i class="bi bi-arrow-right" style="font-size:1.4rem;color:#94a3b8;"></i>
        </div>
        <div>
          <div style="font-size:.7rem;color:#1e40af;font-weight:700;margin-bottom:.3rem;">COM FINANCIAMENTO</div>
          <div style="font-size:.88rem;"><span style="color:#64748b;">Resultado:</span> <strong style="color:{{ '#16a34a' if fin.resultado_com_fin >= 0 else '#dc2626' }};">{{ fin.resultado_com_fin|brl }}</strong></div>
          <div style="font-size:.88rem;"><span style="color:#64748b;">Margem VGV:</span> <strong style="color:{{ '#16a34a' if fin.margem_com_fin >= 15 else ('#ca8a04' if fin.margem_com_fin >= 10 else '#dc2626') }};">{{ fin.margem_com_fin }}%</strong></div>
          <div style="font-size:.88rem;"><span style="color:#64748b;">Exposição:</span> <strong style="color:#16a34a;">{{ fin.exposicao_com_fin|brl }}</strong></div>
          <div style="font-size:.88rem;"><span style="color:#64748b;">TIR:</span> <strong style="color:#6366f1;">{% if fin.tir_alavancada %}{{ fin.tir_alavancada }}% a.a.{% else %}—{% endif %}</strong></div>
        </div>
      </div>
    </div>
    {% if fin.dscr_medio %}<div class="mt-2 small" style="color:#475569;"><i class="bi bi-shield-check me-1" style="color:#16a34a;"></i>DSCR médio: <strong>{{ "%.2f"|format(fin.dscr_medio) }}x</strong> — cobertura do serviço da dívida pelo fluxo de recebimentos</div>{% endif %}
  </div>
  {% endif %}

  {# Result sub-tabs #}
  <div class="res-tabs">
    <button type="button" class="res-tab on" onclick="resTab('indicadores',this)"><i class="bi bi-table me-1"></i>Indicadores / DRE</button>
    <button type="button" class="res-tab" onclick="resTab('fluxo',this)"><i class="bi bi-activity me-1"></i>Fluxo de Caixa</button>
    <button type="button" class="res-tab" onclick="resTab('custos',this)"><i class="bi bi-hammer me-1"></i>Custos e Despesas</button>
    <button type="button" class="res-tab" onclick="resTab('vendas',this)"><i class="bi bi-building me-1"></i>Vendas e Recebimentos</button>
    <button type="button" class="res-tab" onclick="resTab('sensibilidade',this)"><i class="bi bi-grid-3x3 me-1"></i>Sensibilidade</button>
  </div>

  {# ── SUB-TAB 1: Indicadores / DRE ── #}
  <div class="res-sec on" id="restab-indicadores">
    <div class="row g-3">
      <div class="col-md-6">
        <h6 class="mb-2" style="color:#0d9488;"><i class="bi bi-speedometer2 me-1"></i>Indicadores de Viabilidade</h6>
        <div class="bk">
          {% if r.tir_anual is not none %}<div class="bk-r"><span class="bk-l">TIR Anual (equity puro)</span><span style="color:{{ '#16a34a' if r.tir_anual >= 20 else ('#ca8a04' if r.tir_anual >= 15 else '#dc2626') }};font-weight:700;">{{ r.tir_anual }}%</span></div>{% endif %}
          <div class="bk-r"><span class="bk-l">Margem VGV</span><span style="font-weight:600;">{{ r.margem_vgv }}%</span></div>
          {% if r.payback_mes %}<div class="bk-r"><span class="bk-l">Payback Simples</span><span>Mês {{ r.payback_mes }}</span></div>{% endif %}
          {% if ia %}
          <div class="bk-r"><span class="bk-l">VSO Mensal</span><span>{{ "%.1f"|format(ia.vso_mensal) }} un./mês</span></div>
          {% if ia.payback_descontado %}<div class="bk-r"><span class="bk-l">Payback Descontado</span><span>Mês {{ ia.payback_descontado }}</span></div>{% endif %}
          {% if ia.multiplo_capital %}<div class="bk-r"><span class="bk-l">Múltiplo do Capital</span><span style="color:{{ '#16a34a' if ia.multiplo_capital >= 1.2 else '#ca8a04' }};font-weight:600;">{{ "%.2f"|format(ia.multiplo_capital) }}x</span></div>{% endif %}
          {% if ia.indice_lucratividade %}<div class="bk-r"><span class="bk-l">Índice de Lucratividade (IL)</span><span style="color:{{ '#16a34a' if ia.indice_lucratividade >= 1 else '#dc2626' }};font-weight:600;">{{ "%.2f"|format(ia.indice_lucratividade) }}x</span></div>{% endif %}
          {% if ia.ponto_equilibrio_pct %}<div class="bk-r"><span class="bk-l">Ponto de Equilíbrio</span><span>{{ "%.1f"|format(ia.ponto_equilibrio_pct) }}% do VGV</span></div>{% endif %}
          <div class="bk-r bk-t"><span>Spread vs CDI</span><span style="color:{{ '#16a34a' if ia.spread_cdi >= 5 else ('#ca8a04' if ia.spread_cdi >= 0 else '#dc2626') }};">{{ "%.2f"|format(ia.spread_cdi) }}%</span></div>
          {% endif %}
        </div>

        {# Potencial construtivo #}
        <h6 class="mb-2 mt-3" style="color:#0d9488;"><i class="bi bi-rulers me-1"></i>Potencial Construtivo</h6>
        <div class="row g-2">
          {% set pc_items = [("Área Terreno", r.area_terreno|round(1), "m²"), ("Potencial Base", r.potencial_base|round(1), "m²"), ("Potencial c/ Outorga", r.potencial_outorga|round(1), "m²"), ("Área Equiv. CUB", r.area_equivalente|round(1), "m²"), ("Área Privativa", r.area_privativa|round(1), "m²"), ("VGV Médio/m²", r.vgv_medio_m2|round(0), "R$/m²")] %}
          {% for lb, vl, un in pc_items %}
          <div class="col-6"><div style="background:#f0fdfa;border-radius:10px;padding:.5rem .75rem;border:1px solid #99f6e4;"><div style="font-size:.65rem;color:#0f766e;font-weight:700;text-transform:uppercase;">{{ lb }}</div><div style="font-size:.92rem;font-weight:700;color:#134e4a;">{{ vl }} {{ un }}</div></div></div>
          {% endfor %}
        </div>
      </div>
      <div class="col-md-6">
        <h6 class="mb-2" style="color:#0d9488;"><i class="bi bi-receipt me-1"></i>DRE — Projeção do Resultado</h6>
        {% if r.dre %}
        <table class="dre-table">
          <tbody>
            {% for row in r.dre %}
            <tr class="dre-row-{{ row.tipo }}">
              <td>{{ row.desc }}</td>
              <td class="dre-val">
                {% if row.tipo == 'pct' %}{{ "%.2f"|format(row.valor) }}%{% else %}{{ row.valor|brl }}{% endif %}
              </td>
            </tr>
            {% endfor %}
          </tbody>
        </table>
        {% endif %}

        {# Financiamento summary if active #}
        {% if fin %}
        <h6 class="mb-2 mt-3" style="color:#1e40af;"><i class="bi bi-bank2 me-1"></i>Financiamento de Obra</h6>
        <div class="bk">
          <div class="bk-r"><span class="bk-l">Valor Financiado</span><span style="color:#1e40af;font-weight:600;">{{ fin.valor_financiado|brl }}</span></div>
          <div class="bk-r"><span class="bk-l">Custo do Crédito</span><span style="color:#dc2626;">{{ fin.custo_fin_total|brl }}</span></div>
          {% if fin.tir_alavancada is not none %}<div class="bk-r"><span class="bk-l">TIR Alavancada</span><span style="font-weight:600;">{{ "%.2f"|format(fin.tir_alavancada) }}%</span></div>{% endif %}
          {% if fin.roe is not none %}<div class="bk-r"><span class="bk-l">ROE</span><span>{{ "%.2f"|format(fin.roe) }}%</span></div>{% endif %}
          {% if fin.dscr_medio is not none %}<div class="bk-r bk-t"><span>DSCR Médio</span><span>{{ "%.2f"|format(fin.dscr_medio) }}x</span></div>{% endif %}
        </div>
        {% endif %}
      </div>
    </div>
  </div>

  {# ── SUB-TAB 2: Fluxo de Caixa ── #}
  <div class="res-sec" id="restab-fluxo">
    <div style="background:#fff;border:1px solid var(--mc-border);border-radius:14px;padding:1.25rem;margin-bottom:1.25rem;">
      <canvas id="chartFluxo" style="max-height:340px;"></canvas>
    </div>
    <h6 class="mb-2">Fluxo de Caixa Mensal</h6>
    <div class="fc-wrap">
      <table class="fc-table">
        <thead>
          <tr>
            <th style="text-align:left;">Mês</th>
            <th>Receita</th>
            <th>Comissão</th>
            <th>Tributos</th>
            <th>Custo Obra</th>
            <th>Saldo Mês</th>
            <th>Saldo Acumulado</th>
          </tr>
        </thead>
        <tbody>
          {% for f in r.fluxo %}
          {% if f.receita != 0 or f.custo_obra != 0 or f.saldo_mes != 0 %}
          <tr>
            <td>{{ f.mes }}</td>
            <td class="fc-pos">{{ f.receita|brl }}</td>
            <td class="fc-neg">{{ f.comissao|brl }}</td>
            <td class="fc-neg">{{ f.tributos|brl }}</td>
            <td class="fc-neg">{{ f.custo_obra|brl }}</td>
            <td class="{{ 'fc-pos' if f.saldo_mes >= 0 else 'fc-neg' }}">{{ f.saldo_mes|brl }}</td>
            <td class="{{ 'fc-pos' if f.saldo_acumulado >= 0 else 'fc-neg' }}">{{ f.saldo_acumulado|brl }}</td>
          </tr>
          {% endif %}
          {% endfor %}
        </tbody>
      </table>
    </div>
  </div>

  {# ── SUB-TAB 3: Custos e Despesas ── #}
  <div class="res-sec" id="restab-custos">
    <div class="kpi-grid" style="margin-bottom:1.25rem;">
      <div class="kpi"><div class="kpi-l"><i class="bi bi-hammer me-1"></i>Custo de Obra</div><div class="kpi-v" style="color:#0d9488;">{{ r.custo_obra_total|brl }}</div><div class="kpi-f">CUB + itens extras</div></div>
      <div class="kpi"><div class="kpi-l"><i class="bi bi-gear me-1"></i>Indiretos</div><div class="kpi-v">{{ r.custo_indiretos|brl }}</div><div class="kpi-f">Projetos, gerenciamento</div></div>
      <div class="kpi"><div class="kpi-l"><i class="bi bi-geo-alt me-1"></i>Terreno</div><div class="kpi-v">{{ r.valor_terreno|brl }}</div><div class="kpi-f">Custo de aquisição</div></div>
      <div class="kpi"><div class="kpi-l"><i class="bi bi-megaphone me-1"></i>Comercialização</div><div class="kpi-v">{{ r.custo_comercial|brl }}</div><div class="kpi-f">Corretagem + mktg</div></div>
      <div class="kpi"><div class="kpi-l"><i class="bi bi-receipt me-1"></i>Impostos</div><div class="kpi-v">{{ r.custo_impostos|brl }}</div><div class="kpi-f">Sobre receita</div></div>
    </div>
    {% if r.desembolso_anual %}
    <div style="background:#fff;border:1px solid var(--mc-border);border-radius:14px;padding:1.25rem;margin-bottom:1.25rem;">
      <h6 class="mb-3" style="color:#0d9488;">Desembolso Anual de Obra</h6>
      <canvas id="chartDesembolso" style="max-height:280px;"></canvas>
    </div>
    {% endif %}
    <h6 class="mb-2">Breakdown de Custos</h6>
    <div class="bk">
      <div class="bk-r"><span class="bk-l">CUB × Área equivalente</span><span>{{ r.custo_cub|brl }}</span></div>
      {% if r.itens_extra > 0 %}<div class="bk-r"><span class="bk-l">Itens fora do CUB</span><span>{{ r.itens_extra|brl }}</span></div>{% endif %}
      <div class="bk-r"><span class="bk-l">Despesas indiretas</span><span>{{ r.custo_indiretos|brl }}</span></div>
      {% if r.valor_terreno > 0 %}<div class="bk-r"><span class="bk-l">Terreno</span><span>{{ r.valor_terreno|brl }}</span></div>{% endif %}
      <div class="bk-r"><span class="bk-l">Comercialização</span><span>{{ r.custo_comercial|brl }}</span></div>
      <div class="bk-r"><span class="bk-l">Impostos s/ Receita</span><span>{{ r.custo_impostos|brl }}</span></div>
      <div class="bk-r bk-t"><span>Custo Total</span><span>{{ r.custo_total|brl }}</span></div>
    </div>
    {# Cronograma do financiamento #}
    {% if fin and fin.schedule %}
    <h6 class="mb-1 mt-3" style="color:#1e40af;"><i class="bi bi-calendar3 me-1"></i>Cronograma do CCB — como o dinheiro flui</h6>
    <div class="small text-muted mb-2">
      🔵 <strong>Desembolso:</strong> banco libera parcelas conforme o avanço da obra &nbsp;|&nbsp;
      🟡 <strong>Carência:</strong> só paga juros, sem amortizar o principal &nbsp;|&nbsp;
      🔴 <strong>Amortização:</strong> devolve o principal + juros ({{ fin.tipo_amortizacao }})
    </div>
    <div class="fs-wrap">
      <table class="fs-table">
        <thead>
          <tr>
            <th style="text-align:left;">Mês</th>
            <th style="text-align:left;">Fase</th>
            <th>Desembolso recebido</th>
            <th>Juros pagos</th>
            <th>Amortização</th>
            <th>Saldo devedor</th>
            <th>Total saída</th>
          </tr>
        </thead>
        <tbody>
          {% for s in fin.schedule %}
          {% if s.drawdown != 0 or s.juros != 0 or s.amortizacao != 0 or s.saldo_devedor != 0 %}
          {% set fase_cls = 'background:#eff6ff;' if s.drawdown > 0 else ('background:#fefce8;' if s.amortizacao == 0 else 'background:#fff1f2;') %}
          {% set fase_nome = 'Desembolso' if s.drawdown > 0 else ('Carência' if s.amortizacao == 0 else 'Amortização') %}
          <tr style="{{ fase_cls }}">
            <td>{{ s.mes }}</td>
            <td><span style="font-size:.72rem;font-weight:700;color:{{ '#1e40af' if s.drawdown > 0 else ('#854d0e' if s.amortizacao == 0 else '#dc2626') }};">{{ fase_nome }}</span></td>
            <td style="color:#16a34a;font-weight:600;">{% if s.drawdown > 0 %}+{{ s.drawdown|brl }}{% else %}—{% endif %}</td>
            <td class="fc-neg">{{ s.juros|brl }}</td>
            <td style="color:{{ '#dc2626' if s.amortizacao > 0 else '#94a3b8' }};">{% if s.amortizacao > 0 %}{{ s.amortizacao|brl }}{% else %}—{% endif %}</td>
            <td style="color:#1e40af;font-weight:600;">{{ s.saldo_devedor|brl }}</td>
            <td class="fc-neg">{{ s.servico_divida|brl }}</td>
          </tr>
          {% endif %}
          {% endfor %}
        </tbody>
      </table>
    </div>
    <div class="small text-muted mt-2">
      <i class="bi bi-info-circle me-1"></i>Custo total de juros: <strong style="color:#dc2626;">{{ fin.custo_fin_total|brl }}</strong>
      &nbsp;·&nbsp; Crédito captado máximo: <strong style="color:#1e40af;">{{ fin.valor_financiado|brl }}</strong>
    </div>
    {% endif %}
  </div>

  {# ── SUB-TAB 4: Vendas e Recebimentos ── #}
  <div class="res-sec" id="restab-vendas">
    <div class="kpi-grid" style="margin-bottom:1.25rem;">
      <div class="kpi"><div class="kpi-l"><i class="bi bi-cash-stack me-1"></i>VGV Bruto</div><div class="kpi-v" style="color:#0d9488;">{{ r.vgv_bruto|brl }}</div><div class="kpi-f">{{ r.unidades_total }} unidades</div></div>
      <div class="kpi"><div class="kpi-l"><i class="bi bi-currency-dollar me-1"></i>VGV Líquido</div><div class="kpi-v" style="color:#16a34a;">{{ r.vgv_liquido|brl }}</div><div class="kpi-f">Após permuta</div></div>
      <div class="kpi"><div class="kpi-l"><i class="bi bi-arrow-left-right me-1"></i>Permuta</div><div class="kpi-v" style="color:#ca8a04;">{{ r.valor_permuta|brl }}</div><div class="kpi-f">{{ r.unidades_permuta }} unidades permutadas</div></div>
      <div class="kpi"><div class="kpi-l"><i class="bi bi-building me-1"></i>Área Privativa</div><div class="kpi-v">{{ r.area_privativa|round|int }} m²</div><div class="kpi-f">VGV médio {{ r.vgv_medio_m2|round|int }} R$/m²</div></div>
    </div>
    {% if dados and dados.tipologias %}
    <h6 class="mb-2" style="color:#0d9488;"><i class="bi bi-grid me-1"></i>Tipologias</h6>
    <div style="overflow-x:auto;border:1px solid var(--mc-border);border-radius:12px;margin-bottom:1.25rem;">
      <table style="width:100%;border-collapse:collapse;font-size:.84rem;">
        <thead><tr style="background:#0d9488;color:#fff;">
          <th style="padding:.45rem .75rem;text-align:left;">Tipologia</th>
          <th style="padding:.45rem .75rem;text-align:center;">Tipo</th>
          <th style="padding:.45rem .75rem;text-align:right;">Metragem</th>
          <th style="padding:.45rem .75rem;text-align:right;">Qtd</th>
          <th style="padding:.45rem .75rem;text-align:right;">Preço/m²</th>
          <th style="padding:.45rem .75rem;text-align:right;">VGV Tipologia</th>
          <th style="padding:.45rem .75rem;text-align:center;">Permuta</th>
        </tr></thead>
        <tbody>
          {% for t in dados.tipologias %}
          <tr style="border-bottom:1px solid #f1f5f9;">
            <td style="padding:.4rem .75rem;font-weight:600;">{{ t.nome or '—' }}</td>
            <td style="padding:.4rem .75rem;text-align:center;"><span style="font-size:.75rem;padding:.15rem .5rem;border-radius:999px;background:#f0fdfa;color:#0d9488;font-weight:600;">{{ t.tipo }}</span></td>
            <td style="padding:.4rem .75rem;text-align:right;">{{ t.metragem }} m²</td>
            <td style="padding:.4rem .75rem;text-align:right;">{{ t.quantidade }}</td>
            <td style="padding:.4rem .75rem;text-align:right;">{{ t.preco_m2|brl }}</td>
            <td style="padding:.4rem .75rem;text-align:right;font-weight:600;color:#0d9488;">{{ (t.metragem * t.quantidade * t.preco_m2)|brl }}</td>
            <td style="padding:.4rem .75rem;text-align:center;">{% if t.permuta %}<span style="color:#dc2626;font-weight:600;">Sim</span>{% else %}—{% endif %}</td>
          </tr>
          {% endfor %}
        </tbody>
      </table>
    </div>
    {% endif %}
    {% if dados and dados.fases %}
    <h6 class="mb-2" style="color:#0d9488;"><i class="bi bi-bar-chart-steps me-1"></i>Fases de Venda</h6>
    <div style="overflow-x:auto;border:1px solid var(--mc-border);border-radius:12px;">
      <table style="width:100%;border-collapse:collapse;font-size:.84rem;">
        <thead><tr style="background:#0d9488;color:#fff;">
          <th style="padding:.45rem .75rem;text-align:left;">Fase</th>
          <th style="padding:.45rem .75rem;text-align:right;">Meta %</th>
          <th style="padding:.45rem .75rem;text-align:right;">Reajuste %</th>
          <th style="padding:.45rem .75rem;text-align:right;">Duração</th>
          <th style="padding:.45rem .75rem;text-align:right;">Entrada %</th>
          <th style="padding:.45rem .75rem;text-align:right;">Parcelas %</th>
          <th style="padding:.45rem .75rem;text-align:right;">N Parcelas</th>
        </tr></thead>
        <tbody>
          {% for f in dados.fases %}
          <tr style="border-bottom:1px solid #f1f5f9;">
            <td style="padding:.4rem .75rem;font-weight:600;">{{ f.nome }}</td>
            <td style="padding:.4rem .75rem;text-align:right;">{{ f.meta }}%</td>
            <td style="padding:.4rem .75rem;text-align:right;color:{{ '#16a34a' if f.reajuste >= 0 else '#dc2626' }};">{{ f.reajuste }}%</td>
            <td style="padding:.4rem .75rem;text-align:right;">{{ f.duracao }} meses</td>
            <td style="padding:.4rem .75rem;text-align:right;">{{ f.entrada_pct }}%</td>
            <td style="padding:.4rem .75rem;text-align:right;">{{ f.parcelas_pct }}%</td>
            <td style="padding:.4rem .75rem;text-align:right;">{{ f.n_parcelas }}</td>
          </tr>
          {% endfor %}
        </tbody>
      </table>
    </div>
    {% endif %}
  </div>

  {# ── SUB-TAB 5: Sensibilidade ── #}
  <div class="res-sec" id="restab-sensibilidade">
    {% if sen %}
    <h6 class="mb-3" style="color:#0d9488;"><i class="bi bi-grid-3x3 me-1"></i>Análise de Sensibilidade — TIR Anual (%)</h6>
    <div style="overflow-x:auto;margin-bottom:1.5rem;">
      <table class="sen-table">
        <thead>
          <tr>
            <th>VGV \ Custo</th>
            {% for fc in sen.fatores_custo %}<th>Custo {{ fc }}</th>{% endfor %}
          </tr>
        </thead>
        <tbody>
          {% for row in sen.rows_tir %}
          <tr>
            <td style="background:#1e293b;color:#fff;font-weight:700;text-align:left;padding:.4rem .6rem;">VGV {{ row.label }}</td>
            {% for val in row.valores %}
            <td class="{% if val is not none and val >= 20 %}sen-green{% elif val is not none and val >= 15 %}sen-yellow{% else %}sen-red{% endif %}">
              {% if val is not none %}{{ "%.1f"|format(val) }}%{% else %}—{% endif %}
            </td>
            {% endfor %}
          </tr>
          {% endfor %}
        </tbody>
      </table>
    </div>
    <h6 class="mb-3" style="color:#0d9488;"><i class="bi bi-grid-3x3 me-1"></i>Análise de Sensibilidade — Margem VGV (%)</h6>
    <div style="overflow-x:auto;">
      <table class="sen-table">
        <thead>
          <tr>
            <th>VGV \ Custo</th>
            {% for fc in sen.fatores_custo %}<th>Custo {{ fc }}</th>{% endfor %}
          </tr>
        </thead>
        <tbody>
          {% for row in sen.rows_margem %}
          <tr>
            <td style="background:#1e293b;color:#fff;font-weight:700;text-align:left;padding:.4rem .6rem;">VGV {{ row.label }}</td>
            {% for val in row.valores %}
            <td class="{% if val is not none and val >= 20 %}sen-green{% elif val is not none and val >= 15 %}sen-yellow{% else %}sen-red{% endif %}">
              {% if val is not none %}{{ "%.1f"|format(val) }}%{% else %}—{% endif %}
            </td>
            {% endfor %}
          </tr>
          {% endfor %}
        </tbody>
      </table>
    </div>
    {% endif %}
  </div>

  <div class="d-flex gap-2 flex-wrap mt-3">
    <button type="button" class="btn btn-outline-secondary" onclick="vbTab('premissas',document.querySelector('[onclick*=premissas]'))"><i class="bi bi-pencil me-1"></i> Editar premissas</button>
    <button onclick="window.print()" type="button" class="btn btn-outline-primary"><i class="bi bi-printer me-1"></i> Exportar PDF</button>
  </div>
</div>
{% endif %}

</form>

{% if resultado %}
<script>
document.addEventListener('DOMContentLoaded',function(){
  vbTab('resultado',document.querySelector('[onclick*="resultado"]'));
  {% if resultado.chart_labels %}
  new Chart(document.getElementById('chartFluxo'), {
    type: 'line',
    data: {
      labels: {{ resultado.chart_labels | tojson }},
      datasets: [
        {label:'Pagamentos', data: {{ resultado.chart_pag | tojson }}, borderColor:'#ef4444', backgroundColor:'rgba(239,68,68,.1)', tension:.3, fill:true},
        {label:'Recebimentos', data: {{ resultado.chart_rec | tojson }}, borderColor:'#22c55e', backgroundColor:'rgba(34,197,94,.1)', tension:.3, fill:true},
        {label:'Exposição Acum.', data: {{ resultado.chart_exp | tojson }}, borderColor:'#94a3b8', borderDash:[5,5], tension:.3, fill:false}
      ]
    },
    options: { responsive:true, plugins:{legend:{position:'top'}}, scales:{y:{ticks:{callback: function(v){return 'R$'+v.toLocaleString('pt-BR');}}}}}
  });
  {% endif %}
  {% if resultado.desembolso_anual %}
  new Chart(document.getElementById('chartDesembolso'), {
    type: 'bar',
    data: {
      labels: {{ resultado.desembolso_anual | map(attribute='ano') | list | tojson }},
      datasets: [{label:'Desembolso (R$)', data: {{ resultado.desembolso_anual | map(attribute='valor') | list | tojson }}, backgroundColor:'#0d9488'}]
    },
    options: { responsive:true, plugins:{legend:{display:false}}, scales:{y:{ticks:{callback: function(v){return 'R$'+v.toLocaleString('pt-BR');}}}}}
  });
  {% endif %}
});
</script>
{% endif %}

<script>
function vbTab(id,btn){
  document.querySelectorAll('.vb-sec').forEach(s=>s.classList.remove('on'));
  document.querySelectorAll('.vb-tab').forEach(b=>b.classList.remove('on'));
  const s=document.getElementById('tab-'+id);if(s)s.classList.add('on');
  if(btn)btn.classList.add('on');
  window.scrollTo({top:0,behavior:'smooth'});
}
function resTab(id,btn){
  document.querySelectorAll('.res-sec').forEach(s=>s.classList.remove('on'));
  document.querySelectorAll('.res-tab').forEach(b=>b.classList.remove('on'));
  const s=document.getElementById('restab-'+id);if(s)s.classList.add('on');
  if(btn)btn.classList.add('on');
}
function toggleFinInputs(el){
  const box=document.getElementById('finInputs');
  if(el.checked){box.style.opacity='1';box.style.pointerEvents='auto';}
  else{box.style.opacity='.4';box.style.pointerEvents='none';}
}
let tipN=document.querySelectorAll('[id^="tip-"]').length||1;
function addTip(){
  const c=document.getElementById('tipCont'),i=tipN++;
  const d=document.createElement('div');d.className='tip-row';d.id='tip-'+i;
  d.innerHTML=`<div><input class="vb-inp" type="text" name="tip_nome_${i}" placeholder="Nome"></div><div><select class="vb-sel" name="tip_tipo_${i}"><option>Residencial</option><option>Comercial</option></select></div><div><input class="vb-inp" type="number" name="tip_metragem_${i}" step="0.5" min="0" placeholder="102"></div><div><input class="vb-inp" type="number" name="tip_qtd_${i}" step="1" min="0" placeholder="1"></div><div><div class="pw"><span class="pre">R$</span><input class="vb-inp pl" type="number" name="tip_preco_${i}" step="100"></div></div><div><input class="vb-inp" type="number" name="tip_andar_${i}" step="1" min="1" placeholder="1"></div><div style="display:flex;align-items:center;gap:.3rem;"><input type="checkbox" name="tip_permuta_${i}" value="1" id="perm${i}"><label for="perm${i}" style="font-size:.8rem;">Sim</label></div><div><button type="button" class="btn btn-sm btn-outline-danger" onclick="rmTip(${i})">x</button></div>`;
  c.appendChild(d);
}
function rmTip(i){const el=document.getElementById('tip-'+i);if(el)el.remove();}
let faseN=document.querySelectorAll('[id^="fase-"]').length||2;
function addFase(){
  const c=document.getElementById('faseCont'),i=faseN++;
  const d=document.createElement('div');d.className='fase-card';d.id='fase-'+i;
  d.innerHTML=`<div class="fase-hdr"><input class="vb-inp" type="text" name="fase_nome_${i}" placeholder="Nome da fase" style="max-width:200px;"><button type="button" class="btn btn-sm btn-outline-danger" onclick="rmFase(${i})">Remover fase</button></div><div class="vb-row4"><div><div class="vb-lbl">Meta (%)</div><div class="pw"><span class="suf">%</span><input class="vb-inp pr" type="number" name="fase_meta_${i}" step="1" min="0" max="100" placeholder="15"></div></div><div><div class="vb-lbl">Reajuste (%)</div><div class="pw"><span class="suf">%</span><input class="vb-inp pr" type="number" name="fase_reajuste_${i}" step="1" placeholder="0"></div></div><div><div class="vb-lbl">Duração (meses)</div><input class="vb-inp" type="number" name="fase_duracao_${i}" step="1" min="1" placeholder="12"></div><div><div class="vb-lbl">Entrada (%)</div><div class="pw"><span class="suf">%</span><input class="vb-inp pr" type="number" name="fase_entrada_${i}" step="1" min="0" placeholder="10"></div></div></div><div class="vb-row4"><div><div class="vb-lbl">Parcelas (%)</div><div class="pw"><span class="suf">%</span><input class="vb-inp pr" type="number" name="fase_parcelas_${i}" step="1" min="0" placeholder="80"></div></div><div><div class="vb-lbl">N Parcelas</div><input class="vb-inp" type="number" name="fase_nparcelas_${i}" step="1" min="1" placeholder="24"></div><div><div class="vb-lbl">Reforços (%)</div><div class="pw"><span class="suf">%</span><input class="vb-inp pr" type="number" name="fase_reforco_${i}" step="1" min="0" placeholder="0"></div></div><div><div class="vb-lbl">N Reforços</div><input class="vb-inp" type="number" name="fase_nreforcos_${i}" step="1" min="0" placeholder="0"></div></div>`;
  c.appendChild(d);
}
function rmFase(i){const el=document.getElementById('fase-'+i);if(el)el.remove();}
document.getElementById('vbForm')?.addEventListener('submit',()=>{
  const b=document.getElementById('calcBtn');
  if(b){b.disabled=true;b.innerHTML='<i class="bi bi-hourglass-split me-2"></i>Calculando...';}
});
</script>
{% endblock %}
"""

if hasattr(templates_env.loader, "mapping"):
    templates_env.loader.mapping = TEMPLATES

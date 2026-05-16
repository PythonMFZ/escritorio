# ============================================================================
# MÓDULO CRI — Maffezzolli Capital
# Simulação de CRI integrada ao motor v3.
# Calcula: CET real, breakdown de custos, receita da Maffezzolli,
#          WACC, DSCR, veredicto semáforo e comparativo Banco vs CRI.
# Integra os custos do CRI no fluxo de caixa do projeto:
#   - entrada do volume líquido na emissão
#   - recorrentes debitados mensalmente
#   - resgate bullet ao final do prazo
#   - TIR, exposição e DRE do projeto são recomputados
# ============================================================================

import math as _math_cri


# ── Cálculo do módulo CRI ────────────────────────────────────────────────────

def _calcular_cri(dados: dict, base: dict) -> dict:
    """
    Recebe os dados do formulário e o resultado base (_calcular_v3).
    Retorna dict com todos os indicadores do CRI.
    tir_projeto aqui é a TIR SEM CRI — usada para o semáforo de viabilidade.
    """
    volume          = float(dados.get("cri_volume", 0) or 0)
    indexador       = dados.get("cri_indexador", "IPCA+")
    spread          = float(dados.get("cri_spread", 12.0) or 12.0)
    ipca_proj       = float(dados.get("cri_ipca", 4.5) or 4.5)
    duracao_obra    = int(dados.get("duracao_obra", 56) or 56)
    carencia_cri    = int(dados.get("cri_carencia", 6) or 6)
    regime          = dados.get("cri_regime", "bullet")
    retorno_equity  = float(dados.get("cri_retorno_equity", 20.0) or 20.0)

    if indexador == "CDI+":
        cdi_ref      = float(dados.get("cdi_ref", 14.75) or 14.75)
        taxa_nom_aa  = cdi_ref + spread
    else:
        taxa_nom_aa  = ipca_proj + spread

    prazo_total_m   = duracao_obra + carencia_cri
    prazo_total_a   = prazo_total_m / 12.0

    valor_resgate   = volume * ((1 + taxa_nom_aa / 100) ** prazo_total_a)

    fee_estrt_pct   = float(dados.get("cri_fee_estrut", 2.0) or 2.0) / 100
    fee_orig_pct    = float(dados.get("cri_fee_orig",   1.5) or 1.5) / 100
    fee_monit_pct   = float(dados.get("cri_fee_monit",  0.3) or 0.3) / 100

    sec_emissao     = float(dados.get("cri_sec_emissao", 50000) or 50000)
    sec_adm_pct     = float(dados.get("cri_sec_adm",     0.15)  or 0.15) / 100
    agente_impl     = float(dados.get("cri_agente_impl", 15000) or 15000)
    agente_adm_ano  = float(dados.get("cri_agente_adm",  20000) or 20000)
    juridico        = float(dados.get("cri_juridico",    80000) or 80000)
    engenharia_m    = float(dados.get("cri_engenharia",   4000) or 4000) if duracao_obra > 0 else 0
    laudo           = float(dados.get("cri_laudo",        10000) or 10000)
    b3_cartorio     = float(dados.get("cri_b3",           20000) or 20000)
    usar_rating     = dados.get("cri_rating_on", "0") == "1"
    rating_fixo     = float(dados.get("cri_rating",      80000) or 80000) if usar_rating else 0
    rating_anual    = float(dados.get("cri_rating_anual", 25000) or 25000) if usar_rating else 0
    distribuidora_pct = float(dados.get("cri_distrib",    1.0) or 1.0) / 100

    prazo_anos      = prazo_total_a

    sec_adm_total   = sec_adm_pct * volume * prazo_anos
    agente_adm_tot  = agente_adm_ano * prazo_anos
    rating_anual_tot= rating_anual * prazo_anos
    eng_total       = engenharia_m * duracao_obra

    saldo_medio     = volume * 0.60
    monit_total     = fee_monit_pct * saldo_medio * prazo_anos

    upfront = (
        fee_estrt_pct * volume
        + fee_orig_pct * volume
        + sec_emissao
        + agente_impl
        + juridico
        + laudo
        + b3_cartorio
        + rating_fixo
    )

    recorrentes = sec_adm_total + agente_adm_tot + eng_total + monit_total + rating_anual_tot

    custo_total_estrut  = upfront + recorrentes
    caixa_liquido       = volume - upfront

    custo_distribuidora = distribuidora_pct * volume

    if caixa_liquido > 0 and prazo_total_a > 0:
        cet_aa = ((valor_resgate / caixa_liquido) ** (1 / prazo_total_a) - 1) * 100
    else:
        cet_aa = taxa_nom_aa

    fee_estrt_r   = fee_estrt_pct * volume
    fee_orig_r    = fee_orig_pct  * volume
    fee_monit_r   = monit_total
    receita_bruta = fee_estrt_r + fee_orig_r + fee_monit_r
    resultado_liq = receita_bruta - custo_distribuidora

    custo_total_proj = base.get("custo_total", 1)
    pct_divida  = min(volume / custo_total_proj, 1.0) if custo_total_proj > 0 else 0
    pct_equity  = 1 - pct_divida
    wacc        = pct_divida * (cet_aa / 100) + pct_equity * (retorno_equity / 100)
    wacc_pct    = wacc * 100

    tir_projeto = base.get("tir_anual", 0) or 0

    vgv_liquido = base.get("vgv_liquido", 0) or 0
    dscr = (vgv_liquido / valor_resgate) if valor_resgate > 0 else 0

    alertas = []
    if volume < 5_000_000:
        alertas.append({"tipo": "danger", "msg": "⚠️ Volume abaixo de R$5M — custos fixos tornam a operação inviável."})
    if prazo_total_m > 84:
        alertas.append({"tipo": "warning", "msg": f"⚠️ Prazo de {prazo_total_m} meses excede 84 meses — mercado tende a rejeitar CRI de obra acima desse prazo."})
    if tir_projeto > 0 and tir_projeto < cet_aa:
        alertas.append({"tipo": "danger", "msg": f"🔴 TIR do projeto ({tir_projeto:.1f}% a.a.) é menor que o CET ({cet_aa:.1f}% a.a.) — projeto não suporta o custo do CRI."})
    if dscr < 1.2 and dscr > 0:
        alertas.append({"tipo": "danger", "msg": f"🔴 DSCR de {dscr:.2f}x abaixo de 1,2x — recebíveis não cobrem o serviço da dívida."})

    if tir_projeto <= 0:
        semaforo = {"zona": "cinza", "label": "Sem dados", "icon": "⚪", "cor": "#94a3b8",
                    "desc": "Calcule primeiro a TIR do projeto para verificar a viabilidade do CRI."}
    elif tir_projeto < cet_aa:
        semaforo = {"zona": "vermelho", "label": "Zona Vermelha", "icon": "🔴", "cor": "#dc2626",
                    "desc": f"TIR do projeto ({tir_projeto:.1f}%) abaixo do CET ({cet_aa:.1f}%). Não estruturar."}
    elif tir_projeto < wacc_pct * 1.35:
        semaforo = {"zona": "laranja", "label": "Zona Laranja", "icon": "🟡", "cor": "#d97706",
                    "desc": f"Paga a dívida mas equity ganha pouco (TIR: {tir_projeto:.1f}%). Risco alto."}
    elif tir_projeto < 35:
        semaforo = {"zona": "verde", "label": "Zona Verde", "icon": "🟢", "cor": "#16a34a",
                    "desc": f"Equity satisfeito. Projeto viável com CRI (TIR: {tir_projeto:.1f}%). Estruturar."}
    else:
        semaforo = {"zona": "azul", "label": "Zona Azul", "icon": "🔵", "cor": "#2563eb",
                    "desc": f"Excelente. TIR de {tir_projeto:.1f}% — priorizar na originação."}

    breakdown = [
        {"desc": f"Fee Maffezzolli — Estruturação ({fee_estrt_pct*100:.1f}%)",
         "valor": fee_estrt_r, "quando": "Upfront", "quem": "maffezzolli"},
        {"desc": f"Fee Maffezzolli — Originação ({fee_orig_pct*100:.1f}%)",
         "valor": fee_orig_r,  "quando": "Liquidação", "quem": "maffezzolli"},
        {"desc": f"Fee Maffezzolli — Monitoramento ({fee_monit_pct*100:.1f}% a.a. × {prazo_anos:.1f} anos)",
         "valor": fee_monit_r, "quando": "Anual", "quem": "maffezzolli"},
        {"desc": "Securitizadora — Emissão (fixo)",
         "valor": sec_emissao,    "quando": "Emissão", "quem": "terceiro"},
        {"desc": f"Securitizadora — Administração ({sec_adm_pct*100:.2f}% a.a. × {prazo_anos:.1f} anos)",
         "valor": sec_adm_total,  "quando": "Anual", "quem": "terceiro"},
        {"desc": "Agente Fiduciário — Implantação (fixo)",
         "valor": agente_impl,    "quando": "Emissão", "quem": "terceiro"},
        {"desc": f"Agente Fiduciário — Administração (R${agente_adm_ano:,.0f}/ano × {prazo_anos:.1f} anos)",
         "valor": agente_adm_tot, "quando": "Anual", "quem": "terceiro"},
        {"desc": "Escritório Jurídico (due diligence + docs + legal opinion)",
         "valor": juridico,       "quando": "Estruturação", "quem": "terceiro"},
    ]
    if duracao_obra > 0:
        breakdown.append(
            {"desc": f"Engenharia Independente (R${engenharia_m:,.0f}/mês × {duracao_obra} meses)",
             "valor": eng_total,    "quando": "Mensal/obra", "quem": "terceiro"}
        )
    breakdown += [
        {"desc": "Laudo de Avaliação (imóvel + atualizações)",
         "valor": laudo,           "quando": "Emissão", "quem": "terceiro"},
        {"desc": "Registro B3 + Cartório",
         "valor": b3_cartorio,     "quando": "Emissão", "quem": "terceiro"},
    ]
    if usar_rating:
        breakdown += [
            {"desc": "Agência de Rating — Emissão (fixo)",
             "valor": rating_fixo,      "quando": "Emissão", "quem": "terceiro"},
            {"desc": f"Agência de Rating — Atualização anual × {prazo_anos:.1f} anos",
             "valor": rating_anual_tot, "quando": "Anual", "quem": "terceiro"},
        ]

    breakdown_distrib = {
        "desc": f"Distribuidora/Plataforma ({distribuidora_pct*100:.1f}% sobre volume) — custo Maffezzolli",
        "valor": custo_distribuidora, "quando": "Liquidação", "quem": "maffezzolli_custo"
    }

    return {
        "volume":           round(volume, 2),
        "indexador":        indexador,
        "spread":           spread,
        "ipca_proj":        ipca_proj,
        "taxa_nom_aa":      round(taxa_nom_aa, 2),
        "prazo_total_m":    prazo_total_m,
        "prazo_total_a":    round(prazo_total_a, 2),
        "regime":           regime,
        "valor_resgate":    round(valor_resgate, 2),
        "upfront":          round(upfront, 2),
        "recorrentes":      round(recorrentes, 2),
        "custo_total":      round(custo_total_estrut, 2),
        "custo_pct_vol":    round(custo_total_estrut / volume * 100, 2) if volume > 0 else 0,
        "caixa_liquido":    round(caixa_liquido, 2),
        "cet_aa":           round(cet_aa, 2),
        "spread_real":      round(cet_aa - ipca_proj, 2) if indexador == "IPCA+" else round(cet_aa - float(dados.get("cdi_ref", 14.75) or 14.75), 2),
        "fee_estrt_r":          round(fee_estrt_r, 2),
        "fee_orig_r":           round(fee_orig_r, 2),
        "fee_monit_r":          round(fee_monit_r, 2),
        "receita_bruta":        round(receita_bruta, 2),
        "custo_distribuidora":  round(custo_distribuidora, 2),
        "resultado_liq":        round(resultado_liq, 2),
        "tir_projeto":  round(tir_projeto, 2),
        "wacc_pct":     round(wacc_pct, 2),
        "pct_divida":   round(pct_divida * 100, 1),
        "pct_equity":   round(pct_equity * 100, 1),
        "dscr":         round(dscr, 2),
        "semaforo":     semaforo,
        "alertas":      alertas,
        "breakdown":    breakdown,
        "breakdown_distrib": breakdown_distrib,
    }


# ── Patch no motor v3 — integra CRI no fluxo de caixa do projeto ─────────────

_calcular_v3_original_cri = _calcular_v3  # type: ignore[name-defined]

def _calcular_v3_com_cri(dados: dict) -> dict:
    base = _calcular_v3_original_cri(dados)

    if dados.get("cri_on", "0") != "1":
        base["cri"] = None
        return base

    cri = _calcular_cri(dados, base)

    # ── Parâmetros de timing ──────────────────────────────────────────────────
    duracao_obra    = int(dados.get("duracao_obra", 36) or 36)
    mes_inicio_obra = int(dados.get("mes_inicio_obra", 12) or 12)
    carencia_cri    = int(dados.get("cri_carencia", 6) or 6)

    volume        = cri["volume"]
    caixa_liq     = cri["caixa_liquido"]   # volume - upfront (entrada líquida)
    recorrentes   = cri["recorrentes"]
    valor_resgate = cri["valor_resgate"]

    mes_emissao   = mes_inicio_obra
    prazo_recorr  = duracao_obra + carencia_cri
    mes_resgate   = mes_inicio_obra + duracao_obra + carencia_cri

    # ── Mapa de deltas mensais do CRI sobre o fluxo base ─────────────────────
    delta_map: dict = {}

    # Emissão: incorporador recebe o caixa líquido (volume − upfront)
    delta_map[mes_emissao] = delta_map.get(mes_emissao, 0.0) + caixa_liq

    # Custos recorrentes divididos igualmente ao longo de obra + carência
    if prazo_recorr > 0:
        recorr_mensal = recorrentes / prazo_recorr
        for k in range(prazo_recorr):
            m = mes_inicio_obra + k
            delta_map[m] = delta_map.get(m, 0.0) - recorr_mensal

    # Resgate bullet (principal + juros acumulados) ao final do prazo
    delta_map[mes_resgate] = delta_map.get(mes_resgate, 0.0) - valor_resgate

    # ── Construir fluxo com CRI para TIR e exposição ──────────────────────────
    fluxo_base    = base["fluxo"]
    fluxo_com_cri = [f["saldo_mes"] + delta_map.get(f["mes"], 0.0) for f in fluxo_base]

    # TIR recomputada com CRI
    tir_m_cri  = _tir_v3(fluxo_com_cri)  # type: ignore[name-defined]
    tir_com_cri = round(((1 + tir_m_cri) ** 12 - 1) * 100, 2) if tir_m_cri is not None else None

    # Exposição máxima recomputada com CRI
    saldo_acum = 0.0
    exp_cri    = 0.0
    for s in fluxo_com_cri:
        saldo_acum += s
        if saldo_acum < exp_cri:
            exp_cri = saldo_acum
    exposicao_com_cri = abs(exp_cri)

    # ── Custo total do CRI para o incorporador (impacta resultado) ────────────
    # Estruturação: upfront + recorrentes
    # Encargo financeiro: resgate − volume (= juros capitalizados)
    custo_estrut_cri     = round(cri["custo_total"], 2)
    custo_financeiro_cri = round(valor_resgate - volume, 2)
    custo_total_cri      = custo_estrut_cri + custo_financeiro_cri

    # Resultado sem e com CRI
    fin = base.get("financiamento")
    if fin:
        # CCB já está descontado — parte de cima da CRI é sobre resultado pós-CCB
        resultado_base_para_cri = fin["resultado_com_fin"]
    else:
        resultado_base_para_cri = base["resultado_bruto"]

    resultado_sem_cri = round(resultado_base_para_cri, 2)
    resultado_com_cri = round(resultado_base_para_cri - custo_total_cri, 2)
    exposicao_sem_cri = base["exposicao_maxima"]
    vgv_liq           = base.get("vgv_liquido") or 1
    mgm_com_cri       = round(resultado_com_cri / vgv_liq * 100, 2) if vgv_liq else 0

    # ── Enriquecer dict cri com dados de impacto ──────────────────────────────
    cri.update({
        "tir_sem_cri":           round(base.get("tir_anual") or 0, 2),
        "tir_com_cri":           tir_com_cri,
        "resultado_sem_cri":     resultado_sem_cri,
        "resultado_com_cri":     resultado_com_cri,
        "margem_com_cri":        mgm_com_cri,
        "exposicao_sem_cri":     round(exposicao_sem_cri, 2),
        "exposicao_com_cri":     round(exposicao_com_cri, 2),
        "reducao_exposicao":     round(exposicao_sem_cri - exposicao_com_cri, 2),
        "custo_financeiro_cri":  custo_financeiro_cri,
        "custo_estrut_cri":      custo_estrut_cri,
        "custo_total_cri":       custo_total_cri,
        "label_sem_cri":         "sem CCB e sem CRI" if not fin else "com CCB, sem CRI",
    })

    # ── Atualizar exposição máxima no base (reflete no KPI principal) ─────────
    base["exposicao_maxima"] = exposicao_com_cri

    # ── DRE: inserir linhas de custo CRI ─────────────────────────────────────
    if fin:
        # CCB já modificou a DRE; remove as últimas 2 linhas (resultado_com_fin + lucratividade)
        base["dre"] = base["dre"][:-2]
        base["dre"].append({"desc": "Resultado com CCB (sem CRI)",
                             "valor": round(fin["resultado_com_fin"], 2), "tipo": "subtotal"})
        base["dre"].append({"desc": "(+) Volume CRI emitido (antecipação de recebíveis)",
                             "valor": volume,             "tipo": "receita"})
        base["dre"].append({"desc": "(−) Custos de Estruturação CRI",
                             "valor": -custo_estrut_cri,  "tipo": "deducao"})
        base["dre"].append({"desc": "(−) Resgate CRI — bullet ao vencimento",
                             "valor": -valor_resgate,     "tipo": "deducao"})
        base["dre"].append({"desc": "Resultado com CCB + CRI",
                             "valor": resultado_com_cri,  "tipo": "resultado"})
        base["dre"].append({"desc": "Lucratividade (CCB + CRI)",
                             "valor": mgm_com_cri,        "tipo": "pct"})
    else:
        # Apenas CRI: remove resultado/lucratividade originais e insere com CRI
        base["dre"] = base["dre"][:-2]
        base["dre"].append({"desc": "Resultado Operacional (sem CRI)",
                             "valor": round(base["resultado_bruto"], 2), "tipo": "subtotal"})
        base["dre"].append({"desc": "(+) Volume CRI emitido (antecipação de recebíveis)",
                             "valor": volume,             "tipo": "receita"})
        base["dre"].append({"desc": "(−) Custos de Estruturação CRI",
                             "valor": -custo_estrut_cri,  "tipo": "deducao"})
        base["dre"].append({"desc": "(−) Resgate CRI — bullet ao vencimento",
                             "valor": -valor_resgate,     "tipo": "deducao"})
        base["dre"].append({"desc": "Resultado com CRI",
                             "valor": resultado_com_cri,  "tipo": "resultado"})
        base["dre"].append({"desc": "Lucratividade (com CRI)",
                             "valor": mgm_com_cri,        "tipo": "pct"})

    base["cri"] = cri
    return base

_calcular_v3 = _calcular_v3_com_cri  # type: ignore[name-defined]


# ── Patch no template ─────────────────────────────────────────────────────────

def _patch_cri_template() -> None:
    tpl = TEMPLATES.get("ferramenta_viabilidade.html", "")  # type: ignore[name-defined]
    if not tpl:
        return
    if "_cri_module_v1" in tpl:
        return

    # ── 1. Adicionar aba "CRI" no nav de input ────────────────────────────
    OLD_TAB_FIN = '<button type="button" class="vb-tab" onclick="vbTab(\'financiamento\',this)">💰 Financiamento</button>'
    NEW_TAB_FIN = (
        '<button type="button" class="vb-tab" onclick="vbTab(\'financiamento\',this)">💰 Financiamento</button>'
        '\n  <button type="button" class="vb-tab" onclick="vbTab(\'cri_sim\',this)" id="tabBtnCri">📊 CRI Maffezzolli</button>'
    )
    if OLD_TAB_FIN in tpl:
        tpl = tpl.replace(OLD_TAB_FIN, NEW_TAB_FIN, 1)

    # ── 2. Injetar aba CRI após o fechamento da aba de Financiamento ──────
    OLD_AFTER_FIN = '{# ── ABA 6: RESULTADO ── #}'
    NEW_CRI_TAB = _CRI_INPUT_TAB + '\n{# ── ABA 6: RESULTADO ── #}'
    if OLD_AFTER_FIN in tpl:
        tpl = tpl.replace(OLD_AFTER_FIN, NEW_CRI_TAB, 1)

    # ── 3. Injetar painel de resultado CRI após o cronograma de financiamento
    OLD_AFTER_CRONOGRAMA = '{# Cronograma do financiamento #}'
    NEW_AFTER_CRONOGRAMA = '{# Cronograma do financiamento #}\n' + _CRI_RESULT_BLOCK
    if OLD_AFTER_CRONOGRAMA in tpl:
        tpl = tpl.replace(OLD_AFTER_CRONOGRAMA, NEW_AFTER_CRONOGRAMA, 1)

    # ── 4. Injetar JS no final ────────────────────────────────────────────
    tpl = tpl.replace("</script>\n{% endblock %}", _CRI_JS + "\n</script>\n{% endblock %}", 1)

    # ── Sentinela ─────────────────────────────────────────────────────────
    tpl = tpl.replace("</script>\n{% endblock %}", "/* _cri_module_v1 */\n</script>\n{% endblock %}", 1)

    TEMPLATES["ferramenta_viabilidade.html"] = tpl  # type: ignore[name-defined]
    if hasattr(templates_env.loader, "mapping"):  # type: ignore[name-defined]
        templates_env.loader.mapping = TEMPLATES  # type: ignore[name-defined]
    print("[cri_module] template patched OK")


# ── Conteúdo HTML da aba de input CRI ─────────────────────────────────────────

_CRI_INPUT_TAB = r"""
{# ── ABA CRI MAFFEZZOLLI ── #}
<div class="vb-sec card p-4 mb-3" id="tab-cri_sim">
  <h5 class="mb-1" style="color:#1e3a5f;">📊 Simulação CRI — Maffezzolli Capital</h5>
  <p class="muted small mb-3">Compare o custo real do CRI com o financiamento bancário. Calcule o CET, receita da Maffezzolli e viabilidade para o incorporador.</p>

  <div class="vb-toggle-wrap mb-3">
    <label class="vb-toggle">
      <input type="checkbox" name="cri_on" value="1" id="toggleCri" onchange="toggleCriInputs(this)" {% if dados.cri_on == '1' %}checked{% endif %}>
      <span class="vb-toggle-slider"></span>
    </label>
    <span style="font-weight:600;font-size:.95rem;">Simular emissão de CRI (Maffezzolli Capital)</span>
    <span class="vb-hint ms-1">— ativo/inativo</span>
  </div>

  <div id="criInputs" style="{% if dados.cri_on != '1' %}opacity:.4;pointer-events:none;{% endif %}">

    <div class="vb-sep">Estrutura do Papel</div>
    <div class="vb-row3">
      <div>
        <div class="vb-lbl">Volume da Emissão (R$)</div>
        <div class="pw"><span class="pre">R$</span><input class="vb-inp pl" type="number" name="cri_volume" step="100000" min="0" placeholder="20000000" value="{{ dados.cri_volume or '' }}"></div>
        <div class="vb-hint">Volume mínimo viável: R$5M</div>
      </div>
      <div>
        <div class="vb-lbl">Indexador</div>
        <select class="vb-sel" name="cri_indexador" id="criIndexador" onchange="criUpdateLabel()">
          <option value="IPCA+" {% if not dados.cri_indexador or dados.cri_indexador == 'IPCA+' %}selected{% endif %}>IPCA+</option>
          <option value="CDI+"  {% if dados.cri_indexador == 'CDI+' %}selected{% endif %}>CDI+</option>
        </select>
      </div>
      <div>
        <div class="vb-lbl">Spread ao Investidor (% a.a.)</div>
        <div class="pw"><span class="suf">%</span><input class="vb-inp pr" type="number" name="cri_spread" step="0.5" min="0" placeholder="12.0" value="{{ dados.cri_spread or '12.0' }}"></div>
        <div class="vb-hint" id="criSpreadHint">Faixa de mercado: IPCA+10%–13% (perfil menor porte)</div>
      </div>
    </div>
    <div class="vb-row3">
      <div>
        <div class="vb-lbl" id="criIndexLabel">IPCA Projetado (% a.a.)</div>
        <div class="pw"><span class="suf">%</span><input class="vb-inp pr" type="number" name="cri_ipca" step="0.1" min="0" placeholder="4.5" value="{{ dados.cri_ipca or '4.5' }}"></div>
        <div class="vb-hint">Referência: ~4,5% a.a. (mai/2026)</div>
      </div>
      <div>
        <div class="vb-lbl">Carência pós-obra (meses)</div>
        <input class="vb-inp" type="number" name="cri_carencia" step="1" min="0" max="24" placeholder="6" value="{{ dados.cri_carencia or '6' }}">
        <div class="vb-hint">Prazo total = obra + carência</div>
      </div>
      <div>
        <div class="vb-lbl">Regime de Amortização</div>
        <select class="vb-sel" name="cri_regime">
          <option value="bullet"      {% if not dados.cri_regime or dados.cri_regime == 'bullet' %}selected{% endif %}>Bullet (resgate único)</option>
          <option value="sac"         {% if dados.cri_regime == 'sac' %}selected{% endif %}>SAC</option>
          <option value="price"       {% if dados.cri_regime == 'price' %}selected{% endif %}>Price</option>
          <option value="recebiveis"  {% if dados.cri_regime == 'recebiveis' %}selected{% endif %}>Vinculado a recebíveis</option>
        </select>
      </div>
    </div>
    <div class="vb-row">
      <div>
        <div class="vb-lbl">Retorno mínimo exigido pelo Equity (% a.a.)</div>
        <div class="pw"><span class="suf">%</span><input class="vb-inp pr" type="number" name="cri_retorno_equity" step="1" min="0" placeholder="20" value="{{ dados.cri_retorno_equity or '20' }}"></div>
        <div class="vb-hint">Usado no cálculo do WACC</div>
      </div>
    </div>

    <div class="vb-sep">Custos de Estruturação — Fees Maffezzolli Capital</div>
    <div class="vb-row3">
      <div>
        <div class="vb-lbl">Fee Estruturação (% sobre volume)</div>
        <div class="pw"><span class="suf">%</span><input class="vb-inp pr" type="number" name="cri_fee_estrut" step="0.1" min="0" placeholder="2.0" value="{{ dados.cri_fee_estrut or '2.0' }}"></div>
        <div class="vb-hint">Padrão: 1,5%–2,5% · pago upfront</div>
      </div>
      <div>
        <div class="vb-lbl">Fee Originação (% sobre volume)</div>
        <div class="pw"><span class="suf">%</span><input class="vb-inp pr" type="number" name="cri_fee_orig" step="0.1" min="0" placeholder="1.5" value="{{ dados.cri_fee_orig or '1.5' }}"></div>
        <div class="vb-hint">Padrão: 0,5%–1,5% · pago na liquidação</div>
      </div>
      <div>
        <div class="vb-lbl">Fee Monitoramento (% a.a. sobre saldo)</div>
        <div class="pw"><span class="suf">%</span><input class="vb-inp pr" type="number" name="cri_fee_monit" step="0.05" min="0" placeholder="0.3" value="{{ dados.cri_fee_monit or '0.3' }}"></div>
        <div class="vb-hint">Padrão: 0,2%–0,5% a.a. · anual</div>
      </div>
    </div>

    <div class="vb-sep">Custos Repassados ao Tomador — Terceiros</div>
    <div class="vb-row3">
      <div>
        <div class="vb-lbl">Securitizadora — Emissão (R$ fixo)</div>
        <div class="pw"><span class="pre">R$</span><input class="vb-inp pl" type="number" name="cri_sec_emissao" step="1000" min="0" placeholder="50000" value="{{ dados.cri_sec_emissao or '50000' }}"></div>
        <div class="vb-hint">Faixa: R$30k–R$80k</div>
      </div>
      <div>
        <div class="vb-lbl">Securitizadora — Adm. Anual (% a.a.)</div>
        <div class="pw"><span class="suf">%</span><input class="vb-inp pr" type="number" name="cri_sec_adm" step="0.01" min="0" placeholder="0.15" value="{{ dados.cri_sec_adm or '0.15' }}"></div>
        <div class="vb-hint">Faixa: 0,10%–0,25% a.a.</div>
      </div>
      <div>
        <div class="vb-lbl">Agente Fiduciário — Implantação (R$)</div>
        <div class="pw"><span class="pre">R$</span><input class="vb-inp pl" type="number" name="cri_agente_impl" step="1000" min="0" placeholder="15000" value="{{ dados.cri_agente_impl or '15000' }}"></div>
        <div class="vb-hint">Faixa: R$8k–R$20k</div>
      </div>
    </div>
    <div class="vb-row3">
      <div>
        <div class="vb-lbl">Agente Fiduciário — Adm. Anual (R$/ano)</div>
        <div class="pw"><span class="pre">R$</span><input class="vb-inp pl" type="number" name="cri_agente_adm" step="1000" min="0" placeholder="20000" value="{{ dados.cri_agente_adm or '20000' }}"></div>
        <div class="vb-hint">Faixa: R$12k–R$30k/ano</div>
      </div>
      <div>
        <div class="vb-lbl">Escritório Jurídico (R$ fixo total)</div>
        <div class="pw"><span class="pre">R$</span><input class="vb-inp pl" type="number" name="cri_juridico" step="1000" min="0" placeholder="80000" value="{{ dados.cri_juridico or '80000' }}"></div>
        <div class="vb-hint">Due diligence + docs + legal opinion</div>
      </div>
      <div>
        <div class="vb-lbl">Engenharia Independente (R$/mês)</div>
        <div class="pw"><span class="pre">R$</span><input class="vb-inp pl" type="number" name="cri_engenharia" step="500" min="0" placeholder="4000" value="{{ dados.cri_engenharia or '4000' }}"></div>
        <div class="vb-hint">Faixa: R$2k–R$8k/mês × meses de obra</div>
      </div>
    </div>
    <div class="vb-row3">
      <div>
        <div class="vb-lbl">Laudo de Avaliação (R$)</div>
        <div class="pw"><span class="pre">R$</span><input class="vb-inp pl" type="number" name="cri_laudo" step="1000" min="0" placeholder="10000" value="{{ dados.cri_laudo or '10000' }}"></div>
        <div class="vb-hint">Faixa: R$3k–R$15k</div>
      </div>
      <div>
        <div class="vb-lbl">Registro B3 + Cartório (R$)</div>
        <div class="pw"><span class="pre">R$</span><input class="vb-inp pl" type="number" name="cri_b3" step="1000" min="0" placeholder="20000" value="{{ dados.cri_b3 or '20000' }}"></div>
        <div class="vb-hint">Faixa: R$10k–R$35k</div>
      </div>
      <div>
        <div class="vb-lbl">Distribuidora / Plataforma (% sobre volume)</div>
        <div class="pw"><span class="suf">%</span><input class="vb-inp pr" type="number" name="cri_distrib" step="0.1" min="0" placeholder="1.0" value="{{ dados.cri_distrib or '1.0' }}"></div>
        <div class="vb-hint">Custo da Maffezzolli — não repassa ao tomador</div>
      </div>
    </div>

    <div class="vb-sep">Agência de Rating (opcional)</div>
    <div class="vb-toggle-wrap mb-2">
      <label class="vb-toggle">
        <input type="checkbox" name="cri_rating_on" value="1" id="toggleRating" onchange="toggleRatingInputs(this)" {% if dados.cri_rating_on == '1' %}checked{% endif %}>
        <span class="vb-toggle-slider"></span>
      </label>
      <span style="font-size:.9rem;font-weight:500;">Incluir rating na estrutura</span>
    </div>
    <div id="ratingInputs" style="{% if dados.cri_rating_on != '1' %}opacity:.4;pointer-events:none;{% endif %}">
      <div class="vb-row">
        <div>
          <div class="vb-lbl">Rating — Emissão (R$ fixo)</div>
          <div class="pw"><span class="pre">R$</span><input class="vb-inp pl" type="number" name="cri_rating" step="5000" min="0" placeholder="80000" value="{{ dados.cri_rating or '80000' }}"></div>
          <div class="vb-hint">Faixa: R$40k–R$150k</div>
        </div>
        <div>
          <div class="vb-lbl">Rating — Atualização Anual (R$/ano)</div>
          <div class="pw"><span class="pre">R$</span><input class="vb-inp pl" type="number" name="cri_rating_anual" step="5000" min="0" placeholder="25000" value="{{ dados.cri_rating_anual or '25000' }}"></div>
          <div class="vb-hint">Faixa: R$15k–R$50k/ano</div>
        </div>
      </div>
    </div>

  </div>{# /criInputs #}

  <div class="d-flex justify-content-between mt-4">
    <button type="button" class="btn btn-outline-secondary" onclick="vbTab('financiamento',document.querySelector('[onclick*=financiamento]'))"><i class="bi bi-arrow-left me-1"></i> Financiamento</button>
    <button type="button" class="btn px-4" style="background:#1e3a5f;color:#fff;" id="calcBtnCri" onclick="document.getElementById('vbForm').submit()">
      <i class="bi bi-calculator me-2"></i> Calcular Viabilidade + CRI
    </button>
  </div>
</div>
"""


# ── Bloco de resultado CRI ────────────────────────────────────────────────────

_CRI_RESULT_BLOCK = r"""
{# ── RESULTADO CRI — aparece dentro da aba Resultado ── #}
{% if r.cri %}
{% set cri = r.cri %}
<div style="margin-top:2rem;border-top:2px solid #1e3a5f;padding-top:1.5rem;">
  <div style="display:flex;align-items:center;gap:.75rem;margin-bottom:1rem;flex-wrap:wrap;">
    <span style="font-size:1.1rem;font-weight:800;color:#1e3a5f;">📊 Simulação CRI — Maffezzolli Capital</span>
    <span style="font-size:.75rem;font-weight:700;background:{{ cri.semaforo.cor }};color:#fff;padding:.2rem .75rem;border-radius:40px;">{{ cri.semaforo.icon }} {{ cri.semaforo.label }}</span>
  </div>
  <p class="muted small mb-3">{{ cri.semaforo.desc }}</p>

  {# Alertas #}
  {% for al in cri.alertas %}
  <div style="background:{% if al.tipo == 'danger' %}#fef2f2{% else %}#fffbeb{% endif %};border:1px solid {% if al.tipo == 'danger' %}#fca5a5{% else %}#fcd34d{% endif %};border-radius:8px;padding:.6rem 1rem;font-size:.82rem;margin-bottom:.6rem;">{{ al.msg }}</div>
  {% endfor %}

  {# KPIs CRI — 4 cards #}
  <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:1rem;margin-bottom:1.5rem;">
    <div style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:10px;padding:1rem;">
      <div style="font-size:.68rem;font-weight:700;text-transform:uppercase;color:#64748b;margin-bottom:.3rem;">Volume Emitido</div>
      <div style="font-size:1.4rem;font-weight:800;color:#1e3a5f;">{{ cri.volume|brl }}</div>
      <div style="font-size:.75rem;color:#94a3b8;">{{ cri.indexador }}{{ "%.1f"|format(cri.spread) }}% a.a. · {{ cri.prazo_total_m }}m</div>
    </div>
    <div style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:10px;padding:1rem;">
      <div style="font-size:.68rem;font-weight:700;text-transform:uppercase;color:#64748b;margin-bottom:.3rem;">Custo Efetivo Total (CET)</div>
      <div style="font-size:1.4rem;font-weight:800;color:#dc2626;">{{ "%.2f"|format(cri.cet_aa) }}% a.a.</div>
      <div style="font-size:.75rem;color:#94a3b8;">Taxa nominal: {{ "%.2f"|format(cri.taxa_nom_aa) }}% a.a. · {{ cri.indexador }}{{ "%.1f"|format(cri.spread_real) }}% real</div>
    </div>
    <div style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:10px;padding:1rem;">
      <div style="font-size:.68rem;font-weight:700;text-transform:uppercase;color:#64748b;margin-bottom:.3rem;">Valor de Resgate (Bullet)</div>
      <div style="font-size:1.4rem;font-weight:800;color:#dc2626;">{{ cri.valor_resgate|brl }}</div>
      <div style="font-size:.75rem;color:#94a3b8;">Caixa líquido recebido: {{ cri.caixa_liquido|brl }}</div>
    </div>
    <div style="background:{% if cri.resultado_liq > 0 %}#f0fdf4{% else %}#fef2f2{% endif %};border:1px solid {% if cri.resultado_liq > 0 %}#86efac{% else %}#fca5a5{% endif %};border-radius:10px;padding:1rem;">
      <div style="font-size:.68rem;font-weight:700;text-transform:uppercase;color:#64748b;margin-bottom:.3rem;">Resultado Líquido Maffezzolli</div>
      <div style="font-size:1.4rem;font-weight:800;color:{% if cri.resultado_liq > 0 %}#16a34a{% else %}#dc2626{% endif %};">{{ cri.resultado_liq|brl }}</div>
      <div style="font-size:.75rem;color:#94a3b8;">Bruto: {{ cri.receita_bruta|brl }} (−) Distribuidora: {{ cri.custo_distribuidora|brl }}</div>
    </div>
  </div>

  {# ── Impacto no Resultado do Projeto ── #}
  <div style="background:#fff;border:2px solid #1e3a5f;border-radius:12px;padding:1.5rem;margin-bottom:1.5rem;">
    <div style="font-size:.85rem;font-weight:800;text-transform:uppercase;color:#1e3a5f;margin-bottom:1rem;letter-spacing:.04em;">📈 Impacto do CRI no Resultado do Projeto</div>
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:1.5rem;margin-bottom:1rem;">
      <div style="background:#f8fafc;border-radius:8px;padding:1rem;">
        <div style="font-size:.7rem;font-weight:700;text-transform:uppercase;color:#64748b;margin-bottom:.5rem;">{{ cri.label_sem_cri|upper }}</div>
        <div style="font-size:.88rem;margin-bottom:.25rem;"><span style="color:#64748b;">Resultado:</span> <strong>{{ cri.resultado_sem_cri|brl }}</strong></div>
        <div style="font-size:.88rem;margin-bottom:.25rem;"><span style="color:#64748b;">Exposição máx.:</span> <strong style="color:#dc2626;">{{ cri.exposicao_sem_cri|brl }}</strong></div>
        <div style="font-size:.88rem;"><span style="color:#64748b;">TIR:</span> <strong>{{ cri.tir_sem_cri }}% a.a.</strong></div>
      </div>
      <div style="background:#f0fdf4;border:1px solid #86efac;border-radius:8px;padding:1rem;">
        <div style="font-size:.7rem;font-weight:700;text-transform:uppercase;color:#15803d;margin-bottom:.5rem;">COM CRI</div>
        <div style="font-size:.88rem;margin-bottom:.25rem;"><span style="color:#64748b;">Resultado:</span> <strong style="color:{% if cri.resultado_com_cri >= 0 %}#16a34a{% else %}#dc2626{% endif %};">{{ cri.resultado_com_cri|brl }}</strong></div>
        <div style="font-size:.88rem;margin-bottom:.25rem;"><span style="color:#64748b;">Exposição máx.:</span> <strong style="color:#f97316;">{{ cri.exposicao_com_cri|brl }}</strong></div>
        <div style="font-size:.88rem;"><span style="color:#64748b;">TIR:</span> <strong style="color:#6366f1;">{% if cri.tir_com_cri %}{{ cri.tir_com_cri }}% a.a.{% else %}—{% endif %}</strong></div>
      </div>
    </div>
    {# Fluxo financeiro do CRI: entrada e saídas explícitas #}
    <div style="background:#f8fafc;border-radius:8px;padding:.9rem 1rem;margin-bottom:.75rem;">
      <div style="font-size:.7rem;font-weight:700;text-transform:uppercase;color:#64748b;margin-bottom:.5rem;letter-spacing:.04em;">Fluxo Financeiro CRI (entrada e saídas)</div>
      <div style="display:flex;justify-content:space-between;padding:.25rem 0;border-bottom:1px solid #e2e8f0;">
        <span style="font-size:.82rem;color:#15803d;font-weight:600;">(+) Volume CRI emitido</span>
        <span style="font-size:.85rem;font-weight:700;color:#16a34a;">+{{ cri.volume|brl }}</span>
      </div>
      <div style="display:flex;justify-content:space-between;padding:.25rem 0;border-bottom:1px solid #e2e8f0;">
        <span style="font-size:.82rem;color:#64748b;">(−) Custos de estruturação</span>
        <span style="font-size:.82rem;font-weight:600;color:#dc2626;">−{{ cri.custo_estrut_cri|brl }}</span>
      </div>
      <div style="display:flex;justify-content:space-between;padding:.25rem 0;border-bottom:2px solid #cbd5e1;">
        <span style="font-size:.82rem;color:#64748b;">(−) Resgate bullet ao vencimento</span>
        <span style="font-size:.82rem;font-weight:600;color:#dc2626;">−{{ cri.valor_resgate|brl }}</span>
      </div>
      <div style="display:flex;justify-content:space-between;padding:.3rem 0;">
        <span style="font-size:.85rem;font-weight:700;color:#1e293b;">Impacto líquido no resultado</span>
        <span style="font-size:.9rem;font-weight:800;color:{% if cri.resultado_com_cri >= cri.resultado_sem_cri %}#16a34a{% else %}#dc2626{% endif %};">{{ (cri.resultado_com_cri - cri.resultado_sem_cri)|brl }}</span>
      </div>
    </div>
    <div style="display:flex;gap:1rem;flex-wrap:wrap;">
      {% if cri.reducao_exposicao > 0 %}
      <div style="flex:1;min-width:180px;background:#f0fdf4;border-radius:6px;padding:.6rem .75rem;text-align:center;">
        <div style="font-size:.65rem;color:#64748b;text-transform:uppercase;font-weight:600;">Redução de Exposição de Caixa</div>
        <div style="font-size:1rem;font-weight:800;color:#16a34a;">{{ cri.reducao_exposicao|brl }}</div>
        <div style="font-size:.65rem;color:#94a3b8;margin-top:.2rem;">Volume antecipado libera caixa durante a obra</div>
      </div>
      {% else %}
      <div style="flex:1;min-width:180px;background:#fef2f2;border-radius:6px;padding:.6rem .75rem;text-align:center;">
        <div style="font-size:.65rem;color:#64748b;text-transform:uppercase;font-weight:600;">Variação de Exposição</div>
        <div style="font-size:1rem;font-weight:800;color:#dc2626;">+{{ (cri.exposicao_com_cri - cri.exposicao_sem_cri)|brl }}</div>
        <div style="font-size:.65rem;color:#94a3b8;margin-top:.2rem;">Resgate bullet aumenta exposição ao final</div>
      </div>
      {% endif %}
      <div style="flex:1;min-width:180px;background:#f8fafc;border-radius:6px;padding:.6rem .75rem;text-align:center;">
        <div style="font-size:.65rem;color:#64748b;text-transform:uppercase;font-weight:600;">DSCR (Cobertura do Serviço)</div>
        <div style="font-size:1rem;font-weight:800;color:{% if cri.dscr >= 1.2 %}#16a34a{% else %}#dc2626{% endif %};">{{ "%.2f"|format(cri.dscr) }}x</div>
        <div style="font-size:.65rem;color:#94a3b8;margin-top:.2rem;">Mínimo recomendado: 1,20x</div>
      </div>
    </div>
  </div>

  {# Grid: Breakdown + Receita Maffezzolli + Análise #}
  <div style="display:grid;grid-template-columns:1fr 1fr;gap:1.5rem;margin-bottom:1.5rem;">

    {# Breakdown de Custos #}
    <div style="background:#fff;border:1px solid #e2e8f0;border-radius:10px;padding:1.25rem;">
      <div style="font-size:.78rem;font-weight:700;text-transform:uppercase;color:#1e3a5f;margin-bottom:1rem;">📋 Breakdown de Custos ao Incorporador</div>
      {% for item in cri.breakdown %}
      <div style="display:flex;justify-content:space-between;align-items:flex-start;padding:.35rem 0;border-bottom:1px solid #f1f5f9;gap:.5rem;">
        <div style="font-size:.75rem;color:#475569;flex:1;">
          <span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:{% if item.quem == 'maffezzolli' %}#f97316{% else %}#64748b{% endif %};margin-right:.35rem;flex-shrink:0;"></span>
          {{ item.desc }}
          <span style="font-size:.65rem;color:#94a3b8;display:block;margin-left:14px;">{{ item.quando }}</span>
        </div>
        <div style="font-size:.78rem;font-weight:600;color:#1e293b;white-space:nowrap;">{{ item.valor|brl }}</div>
      </div>
      {% endfor %}
      <div style="display:flex;justify-content:space-between;padding:.5rem 0 0;margin-top:.25rem;">
        <span style="font-size:.8rem;font-weight:700;color:#1e293b;">Estruturação total ({{ "%.1f"|format(cri.custo_pct_vol) }}% do volume)</span>
        <span style="font-size:.85rem;font-weight:800;color:#dc2626;">{{ cri.custo_total|brl }}</span>
      </div>
      <div style="font-size:.68rem;color:#94a3b8;margin-top:.5rem;">
        <span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:#f97316;margin-right:.35rem;"></span>Maffezzolli &nbsp;
        <span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:#64748b;margin-right:.35rem;margin-left:.5rem;"></span>Terceiros
      </div>
      {# Distribuidora separada #}
      <div style="background:#fef3c7;border:1px solid #fcd34d;border-radius:6px;padding:.5rem .75rem;margin-top:.75rem;font-size:.75rem;color:#92400e;">
        <strong>+ {{ cri.breakdown_distrib.desc }}</strong><br>
        <span style="float:right;font-weight:700;">{{ cri.breakdown_distrib.valor|brl }}</span>
        <span style="clear:both;display:block;font-size:.68rem;color:#b45309;margin-top:.15rem;">Não entra no CET do incorporador — reduz margem da Maffezzolli</span>
      </div>
      {# Encargo financeiro separado #}
      <div style="background:#fef2f2;border:1px solid #fca5a5;border-radius:6px;padding:.5rem .75rem;margin-top:.5rem;font-size:.75rem;color:#991b1b;">
        <strong>+ Encargo Financeiro (resgate − volume)</strong>
        <span style="float:right;font-weight:700;">{{ cri.custo_financeiro_cri|brl }}</span>
        <span style="clear:both;display:block;font-size:.68rem;color:#b91c1c;margin-top:.15rem;">Juros capitalizados embutidos no valor de resgate bullet</span>
      </div>
    </div>

    {# Receita Maffezzolli + Análise WACC/DSCR #}
    <div style="display:flex;flex-direction:column;gap:1rem;">

      <div style="background:#fff;border:1px solid #e2e8f0;border-radius:10px;padding:1.25rem;">
        <div style="font-size:.78rem;font-weight:700;text-transform:uppercase;color:#f97316;margin-bottom:.75rem;">💰 Receita Maffezzolli Capital</div>
        <div style="display:flex;justify-content:space-between;padding:.3rem 0;border-bottom:1px solid #f1f5f9;">
          <span style="font-size:.78rem;color:#475569;">Fee de Estruturação</span>
          <span style="font-size:.78rem;font-weight:600;">{{ cri.fee_estrt_r|brl }}</span>
        </div>
        <div style="display:flex;justify-content:space-between;padding:.3rem 0;border-bottom:1px solid #f1f5f9;">
          <span style="font-size:.78rem;color:#475569;">Fee de Originação</span>
          <span style="font-size:.78rem;font-weight:600;">{{ cri.fee_orig_r|brl }}</span>
        </div>
        <div style="display:flex;justify-content:space-between;padding:.3rem 0;border-bottom:1px solid #f1f5f9;">
          <span style="font-size:.78rem;color:#475569;">Fee de Monitoramento (total)</span>
          <span style="font-size:.78rem;font-weight:600;">{{ cri.fee_monit_r|brl }}</span>
        </div>
        <div style="display:flex;justify-content:space-between;padding:.35rem 0;border-bottom:2px solid #e2e8f0;margin-top:.15rem;">
          <span style="font-size:.82rem;font-weight:700;">Total Bruto Recebido</span>
          <span style="font-size:.85rem;font-weight:700;color:#1e3a5f;">{{ cri.receita_bruta|brl }}</span>
        </div>
        <div style="display:flex;justify-content:space-between;padding:.3rem 0;color:#dc2626;">
          <span style="font-size:.78rem;">(−) Distribuidora / Plataforma</span>
          <span style="font-size:.78rem;font-weight:600;">−{{ cri.custo_distribuidora|brl }}</span>
        </div>
        <div style="display:flex;justify-content:space-between;padding:.4rem 0;background:#f0fdf4;border-radius:6px;padding:.5rem .75rem;margin-top:.5rem;">
          <span style="font-size:.9rem;font-weight:800;color:#15803d;">Resultado Líquido</span>
          <span style="font-size:.95rem;font-weight:800;color:#15803d;">{{ cri.resultado_liq|brl }}</span>
        </div>
      </div>

      <div style="background:#fff;border:1px solid #e2e8f0;border-radius:10px;padding:1.25rem;">
        <div style="font-size:.78rem;font-weight:700;text-transform:uppercase;color:#1e3a5f;margin-bottom:.75rem;">📐 Análise de Viabilidade</div>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:.5rem;">
          <div style="background:#f8fafc;border-radius:6px;padding:.5rem .75rem;">
            <div style="font-size:.65rem;color:#64748b;text-transform:uppercase;font-weight:600;">TIR sem CRI</div>
            <div style="font-size:1.1rem;font-weight:800;color:#475569;">{{ cri.tir_sem_cri if cri.tir_sem_cri else "—" }}{% if cri.tir_sem_cri %}%{% endif %}</div>
          </div>
          <div style="background:#f8fafc;border-radius:6px;padding:.5rem .75rem;">
            <div style="font-size:.65rem;color:#64748b;text-transform:uppercase;font-weight:600;">TIR com CRI</div>
            <div style="font-size:1.1rem;font-weight:800;color:#6366f1;">{% if cri.tir_com_cri %}{{ cri.tir_com_cri }}%{% else %}—{% endif %}</div>
          </div>
          <div style="background:#f8fafc;border-radius:6px;padding:.5rem .75rem;">
            <div style="font-size:.65rem;color:#64748b;text-transform:uppercase;font-weight:600;">CET (custo real)</div>
            <div style="font-size:1.1rem;font-weight:800;color:#dc2626;">{{ "%.1f"|format(cri.cet_aa) }}%</div>
          </div>
          <div style="background:#f8fafc;border-radius:6px;padding:.5rem .75rem;">
            <div style="font-size:.65rem;color:#64748b;text-transform:uppercase;font-weight:600;">WACC ({{ "%.0f"|format(cri.pct_divida) }}% dívida)</div>
            <div style="font-size:1.1rem;font-weight:800;color:#1e3a5f;">{{ "%.1f"|format(cri.wacc_pct) }}%</div>
          </div>
        </div>
        <div style="margin-top:.75rem;padding:.5rem .75rem;background:{{ cri.semaforo.cor }}15;border:1px solid {{ cri.semaforo.cor }}40;border-radius:6px;font-size:.78rem;font-weight:600;color:#1e293b;">
          {{ cri.semaforo.icon }} {{ cri.semaforo.label }} — {{ cri.semaforo.desc }}
        </div>
      </div>

    </div>
  </div>

  {# Comparativo Banco vs CRI — só exibe se ambos ativos #}
  {% if fin and fin.custo_fin_total and cri.volume > 0 %}
  <div style="background:#fff;border:2px solid #1e3a5f;border-radius:12px;padding:1.5rem;margin-top:.5rem;">
    <div style="font-size:.85rem;font-weight:800;text-transform:uppercase;color:#1e3a5f;margin-bottom:1rem;letter-spacing:.05em;">⚖️ Comparativo: Banco (CCB/SFH) vs CRI Maffezzolli Capital</div>
    <div style="overflow-x:auto;">
      <table style="width:100%;border-collapse:collapse;font-size:.82rem;">
        <thead>
          <tr style="background:#1e3a5f;color:#fff;">
            <th style="padding:.6rem 1rem;text-align:left;border-radius:6px 0 0 0;">Indicador</th>
            <th style="padding:.6rem 1rem;text-align:right;">🏦 Banco (CCB/SFH)</th>
            <th style="padding:.6rem 1rem;text-align:right;border-radius:0 6px 0 0;">📊 CRI Maffezzolli</th>
          </tr>
        </thead>
        <tbody>
          <tr style="border-bottom:1px solid #f1f5f9;">
            <td style="padding:.5rem 1rem;color:#475569;">Taxa Efetiva ao tomador</td>
            <td style="padding:.5rem 1rem;text-align:right;font-weight:600;">{{ "%.2f"|format(fin.taxa_am * 12) }}% a.a. (nom.)</td>
            <td style="padding:.5rem 1rem;text-align:right;font-weight:600;color:#dc2626;">{{ "%.2f"|format(cri.cet_aa) }}% a.a. (CET)</td>
          </tr>
          <tr style="border-bottom:1px solid #f1f5f9;background:#f8fafc;">
            <td style="padding:.5rem 1rem;color:#475569;">Custo financeiro total (R$)</td>
            <td style="padding:.5rem 1rem;text-align:right;font-weight:600;color:#dc2626;">{{ fin.custo_fin_total|brl }}</td>
            <td style="padding:.5rem 1rem;text-align:right;font-weight:600;color:#dc2626;">{{ cri.custo_total_cri|brl }}</td>
          </tr>
          <tr style="border-bottom:1px solid #f1f5f9;">
            <td style="padding:.5rem 1rem;color:#475569;">TIR alavancada do Equity</td>
            <td style="padding:.5rem 1rem;text-align:right;font-weight:700;color:{% if fin.tir_alavancada and fin.tir_alavancada > 15 %}#16a34a{% else %}#dc2626{% endif %};">{{ "%.2f"|format(fin.tir_alavancada) if fin.tir_alavancada else "—" }}% a.a.</td>
            <td style="padding:.5rem 1rem;text-align:right;font-weight:700;color:#6366f1;">{% if cri.tir_com_cri %}{{ cri.tir_com_cri }}% a.a.{% else %}—{% endif %}</td>
          </tr>
          <tr style="border-bottom:1px solid #f1f5f9;background:#f8fafc;">
            <td style="padding:.5rem 1rem;color:#475569;">DSCR médio</td>
            <td style="padding:.5rem 1rem;text-align:right;font-weight:600;">{{ "%.2f"|format(fin.dscr_medio) if fin.dscr_medio else "—" }}x</td>
            <td style="padding:.5rem 1rem;text-align:right;font-weight:600;">{{ "%.2f"|format(cri.dscr) }}x</td>
          </tr>
          <tr>
            <td style="padding:.5rem 1rem;color:#475569;">Exposição máxima de caixa</td>
            <td style="padding:.5rem 1rem;text-align:right;font-weight:600;">{{ fin.exposicao_com_fin|brl }}</td>
            <td style="padding:.5rem 1rem;text-align:right;font-weight:600;color:#f97316;">{{ cri.exposicao_com_cri|brl }}</td>
          </tr>
        </tbody>
      </table>
    </div>
    <div style="margin-top:1rem;padding:.75rem 1rem;background:#f0fdf4;border-radius:8px;font-size:.8rem;color:#166534;font-weight:600;">
      💡 O CRI reduz o custo operacional do incorporador ao substituir a linha bancária, mas exige estruturação prévia. A Maffezzolli Capital garante o processo completo — da emissão à distribuição.
    </div>
  </div>
  {% endif %}

</div>
{% endif %}
{# /CRI result #}
"""


# ── JS do módulo CRI ──────────────────────────────────────────────────────────

_CRI_JS = r"""
function toggleCriInputs(el){
  const box=document.getElementById('criInputs');
  if(el.checked){box.style.opacity='1';box.style.pointerEvents='auto';}
  else{box.style.opacity='.4';box.style.pointerEvents='none';}
}
function toggleRatingInputs(el){
  const box=document.getElementById('ratingInputs');
  if(el.checked){box.style.opacity='1';box.style.pointerEvents='auto';}
  else{box.style.opacity='.4';box.style.pointerEvents='none';}
}
function criUpdateLabel(){
  const idx=document.getElementById('criIndexador');
  const lbl=document.getElementById('criIndexLabel');
  const hint=document.getElementById('criSpreadHint');
  if(!idx||!lbl)return;
  if(idx.value==='CDI+'){
    lbl.textContent='CDI de Referência (% a.a.)';
    if(hint)hint.textContent='Faixa de mercado: CDI+2%–5% para CRI/CRA (perfil menor porte)';
  }else{
    lbl.textContent='IPCA Projetado (% a.a.)';
    if(hint)hint.textContent='Faixa de mercado: IPCA+10%–13% (perfil menor porte, mai/2026)';
  }
}
document.addEventListener('DOMContentLoaded',function(){criUpdateLabel();});
"""


# ── Aplicar patch ─────────────────────────────────────────────────────────────
_patch_cri_template()
print("[cri_module] Módulo CRI Maffezzolli carregado.")

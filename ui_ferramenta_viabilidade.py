# ============================================================================
# PATCH — Ferramenta Viabilidade Imobiliária v2
# ============================================================================
# Motor fiel à Planilha de Viabilidade MFZ II:
#   - Tipologias com diferencial por andar (0.5% a.a. por padrão)
#   - CUB com coeficiente de equivalência por área (garagem, residual, etc)
#   - Itens fora do CUB (elevadores, recreação, outros)
#   - Distribuição de custos com curva S mensal real
#   - Comercialização em fases (lançamento + pós-lançamento)
#   - Condições comerciais: entrada, parcelas mensais, reforços, chaves
#   - Correção monetária sobre parcelas (0.52% obra, 1.04% pós-obra)
#   - Fluxo de caixa mensal com VP e VF
#   - TIR mensal → anual, VPL, exposição máxima
# ============================================================================

import json as _json
import math as _math
from datetime import datetime as _dt


# ── Motor de cálculo ─────────────────────────────────────────────────────────

def _calcular_viabilidade_v2(dados: dict) -> dict:
    """Motor completo de viabilidade imobiliária fiel à planilha MFZ II."""

    # ── PREMISSAS GERAIS ─────────────────────────────────────────────────
    nome_projeto    = dados.get("nome_projeto", "Sem nome")
    area_terreno    = float(dados.get("area_terreno", 0) or 0)
    indice_aprov    = float(dados.get("indice_aproveitamento", 5) or 5)
    indice_outorga  = float(dados.get("indice_outorga", 0) or 0)
    taxa_ocupacao   = float(dados.get("taxa_ocupacao", 85) or 85) / 100
    permeabilidade  = float(dados.get("permeabilidade", 15) or 15) / 100
    pct_permuta     = float(dados.get("pct_permuta", 0) or 0) / 100

    duracao_obra    = int(dados.get("duracao_obra", 36) or 36)
    mes_inicio_obra = int(dados.get("mes_inicio_obra", 12) or 12)  # mês relativo ao lançamento
    mes_inicio_vend = int(dados.get("mes_inicio_vendas", 3) or 3)  # mês relativo ao lançamento

    # Potenciais construtivos
    potencial_base    = area_terreno * indice_aprov
    potencial_outorga = area_terreno * indice_outorga if indice_outorga > 0 else potencial_base
    ocupacao_maxima   = area_terreno * taxa_ocupacao
    area_permeavel    = area_terreno * permeabilidade

    # ── PRODUTO & VGV ─────────────────────────────────────────────────────
    tipologias     = dados.get("tipologias", [])
    preco_m2_base  = float(dados.get("preco_m2_base", 12500) or 12500)
    dif_andar      = float(dados.get("diferencial_andar", 0.5) or 0.5) / 100  # % por andar

    unidades = []
    vgv_bruto = 0.0
    vgv_liquido = 0.0
    area_privativa_total = 0.0
    area_permutada = 0.0
    valor_permuta = 0.0
    unidades_total = 0
    unidades_permuta_n = 0

    for tip in tipologias:
        tipo        = tip.get("tipo", "Residencial")
        nome        = tip.get("nome", "")
        metragem    = float(tip.get("metragem", 0) or 0)
        qtd         = int(tip.get("quantidade", 0) or 0)
        andar_ini   = int(tip.get("andar_inicio", 1) or 1)
        preco_base  = float(tip.get("preco_m2", preco_m2_base) or preco_m2_base)
        permuta     = bool(tip.get("permuta", False))

        for u in range(qtd):
            andar = andar_ini + u
            preco_m2_u = preco_base * (1 + dif_andar * (andar - 1))
            valor_u = metragem * preco_m2_u

            vgv_bruto += valor_u
            area_privativa_total += metragem
            unidades_total += 1

            if permuta:
                area_permutada += metragem
                valor_permuta += valor_u
                unidades_permuta_n += 1
            else:
                vgv_liquido += valor_u

            unidades.append({
                "nome": nome or f"{tipo} {andar:02d}",
                "tipo": tipo,
                "metragem": metragem,
                "andar": andar,
                "preco_m2": round(preco_m2_u, 2),
                "valor": round(valor_u, 2),
                "permuta": permuta,
            })

    # Fallback se não cadastrou tipologias
    if not tipologias or vgv_bruto == 0:
        n_un = int(dados.get("unidades_total", 0) or 0)
        met  = float(dados.get("metragem_media", 80) or 80)
        area_privativa_total = n_un * met
        vgv_bruto  = area_privativa_total * preco_m2_base
        n_perm     = round(n_un * pct_permuta)
        area_permutada = n_perm * met
        valor_permuta  = area_permutada * preco_m2_base
        vgv_liquido    = vgv_bruto - valor_permuta
        unidades_total = n_un
        unidades_permuta_n = n_perm

    vgv_medio_m2 = vgv_liquido / area_privativa_total if area_privativa_total > 0 else 0

    # ── CUSTO DE OBRA ─────────────────────────────────────────────────────
    cub_base        = float(dados.get("cub_m2", 3019) or 3019)
    area_garagem    = float(dados.get("area_garagem", 0) or 0)
    coef_garagem    = float(dados.get("coef_garagem", 0.7) or 0.7)
    area_residual   = float(dados.get("area_residual", 0) or 0)

    # Área equivalente CUB
    area_equiv_garagem = area_garagem * coef_garagem
    area_equiv_residual = area_residual  # coef 1.0
    area_equivalente = area_equiv_garagem + area_equiv_residual + area_privativa_total

    if area_equivalente == 0:
        # Estimativa: área construída = área privativa / eficiência
        eficiencia = float(dados.get("eficiencia", 0.50) or 0.50)
        area_construida = area_privativa_total / eficiencia if eficiencia > 0 else area_privativa_total * 2
        area_equivalente = area_construida

    custo_cub = cub_base * area_equivalente

    # Itens fora do CUB
    n_elevadores    = int(dados.get("n_elevadores", 0) or 0)
    vl_elevador     = float(dados.get("vl_elevador", 380000) or 380000)
    vl_recreacao    = float(dados.get("vl_recreacao", 0) or 0)
    vl_outros_cub   = float(dados.get("vl_outros_cub", 0) or 0)
    itens_extra     = n_elevadores * vl_elevador + vl_recreacao + vl_outros_cub

    custo_obra_direto = custo_cub + itens_extra

    # Despesas indiretas
    pct_indiretos   = float(dados.get("pct_indiretos", 6.5) or 6.5) / 100
    custo_indiretos = custo_obra_direto * pct_indiretos
    custo_obra_total = custo_obra_direto + custo_indiretos

    custo_m2_equiv  = custo_obra_total / area_equivalente if area_equivalente > 0 else 0

    # Terreno
    valor_terreno   = float(dados.get("valor_terreno", 0) or 0)

    # ── COMERCIALIZAÇÃO ───────────────────────────────────────────────────
    # Taxas
    pct_corretagem  = float(dados.get("pct_corretagem", 5.0) or 5.0) / 100
    pct_gestao      = float(dados.get("pct_gestao_comercial", 1.5) or 1.5) / 100
    pct_marketing   = float(dados.get("pct_marketing", 0.75) or 0.75) / 100
    pct_outros_com  = float(dados.get("pct_outros_com", 1.2) or 1.2) / 100
    pct_impostos    = float(dados.get("pct_impostos", 4.0) or 4.0) / 100
    pct_total_com   = pct_corretagem + pct_gestao + pct_marketing + pct_outros_com

    custo_comercial = vgv_liquido * pct_total_com
    custo_impostos  = vgv_liquido * pct_impostos

    # ── FASES DE VENDA ────────────────────────────────────────────────────
    fases = dados.get("fases", [])
    if not fases:
        # Default: 2 fases como na planilha original
        fases = [
            {"nome": "Lançamento",      "meta": 15, "reajuste": -15,
             "duracao": 12, "entrada_pct": 10, "n_entrada": 1, "parcelas_pct": 90, "n_parcelas": 24,
             "reforco_pct": 0, "n_reforcos": 0, "chaves_pct": 0},
            {"nome": "Pós-Lançamento",  "meta": 85, "reajuste": 5,
             "duracao": 24, "entrada_pct": 15, "n_entrada": 1, "parcelas_pct": 40, "n_parcelas": 48,
             "reforco_pct": 25, "n_reforcos": 4, "chaves_pct": 20},
        ]

    corr_obra     = float(dados.get("correcao_obra", 0.52) or 0.52) / 100   # a.m.
    corr_pos_obra = float(dados.get("correcao_pos_obra", 1.04) or 1.04) / 100

    # ── DISTRIBUIÇÃO DE CUSTOS (curva S) ─────────────────────────────────
    # Percentuais mensais extraídos da planilha (60 meses)
    dist_padrao = [
        0.01050, 0.00855, 0.00841, 0.00751, 0.00673, 0.00667, 0.00811, 0.00811,
        0.00811, 0.00811, 0.00979, 0.01285, 0.01459, 0.01501, 0.01633, 0.01898,
        0.01953, 0.02124, 0.01990, 0.02116, 0.02116, 0.02116, 0.02116, 0.02116,
        0.02116, 0.02116, 0.02116, 0.02116, 0.02116, 0.02116, 0.02116, 0.02116,
        0.02116, 0.02116, 0.02116, 0.02116, 0.02116, 0.02116, 0.02116, 0.02116,
        0.02116, 0.02116, 0.02116, 0.02116, 0.02116, 0.02116, 0.02116, 0.02116,
        0.02116, 0.02116, 0.02116, 0.02116, 0.02116, 0.02116, 0.02116, 0.02116,
        0.02116, 0.02116, 0.02116, 0.02116,
    ]

    # Normaliza para o número de meses de obra do usuário
    def _dist_para_meses(duracao: int) -> list:
        if duracao == len(dist_padrao):
            return dist_padrao[:]
        # Interpola linearmente
        result = []
        for i in range(duracao):
            pos = i / max(duracao - 1, 1) * (len(dist_padrao) - 1)
            lo, hi = int(pos), min(int(pos) + 1, len(dist_padrao) - 1)
            frac = pos - lo
            result.append(dist_padrao[lo] * (1 - frac) + dist_padrao[hi] * frac)
        total = sum(result)
        return [v / total for v in result]

    dist_custos = _dist_para_meses(duracao_obra)

    # ── MONTAGEM DO FLUXO DE CAIXA MENSAL ────────────────────────────────
    # Número total de meses da análise
    mes_fim_obra = mes_inicio_obra + duracao_obra - 1
    duracao_total_vendas = int(dados.get("duracao_analise", 129) or 129)
    n_meses = max(mes_fim_obra + 60, duracao_total_vendas + 10)

    receita_mensal  = [0.0] * (n_meses + 1)
    comissao_mensal = [0.0] * (n_meses + 1)
    tributo_mensal  = [0.0] * (n_meses + 1)
    custo_mensal    = [0.0] * (n_meses + 1)

    # Custo do terreno no mês 0
    custo_mensal[0] += valor_terreno

    # Distribuição de custos de obra
    for i, pct in enumerate(dist_custos):
        m = mes_inicio_obra + i
        if m <= n_meses:
            custo_mensal[m] += custo_obra_total * pct

    # ── Receitas por fase ─────────────────────────────────────────────────
    mes_atual_venda = mes_inicio_vend
    unidades_disponiveis = unidades_total - unidades_permuta_n
    vgv_disponivel = vgv_liquido

    for fase in fases:
        meta_pct     = float(fase.get("meta", 15)) / 100
        reajuste_pct = float(fase.get("reajuste", 0)) / 100
        duracao_f    = int(fase.get("duracao", 12))
        ent_pct      = float(fase.get("entrada_pct", 10)) / 100
        n_ent        = max(1, int(fase.get("n_entrada", 1) or 1))   # parcelas da entrada
        par_pct      = float(fase.get("parcelas_pct", 80)) / 100
        n_par        = int(fase.get("n_parcelas", 24))
        ref_pct      = float(fase.get("reforco_pct", 0)) / 100
        n_ref        = int(fase.get("n_reforcos", 0))
        chv_pct      = max(0.0, 1.0 - ent_pct - par_pct - ref_pct)

        un_fase       = round(unidades_disponiveis * meta_pct)
        preco_fase    = vgv_disponivel / max(unidades_disponiveis, 1) * (1 + reajuste_pct)
        vgv_fase      = un_fase * preco_fase
        vgv_un_fase   = preco_fase

        # Velocidade: distribui unidades ao longo da fase
        un_por_mes    = un_fase / max(duracao_f, 1)

        for m_rel in range(duracao_f):
            m_abs = mes_atual_venda + m_rel
            if m_abs > n_meses:
                break

            venda_mes = un_por_mes * vgv_un_fase

            # Fix 1: comissão sobre VENDA TOTAL (não só sobre entrada)
            comissao_mensal[m_abs] += venda_mes * pct_total_com

            # Fix 3: entrada parcelada em n_ent prestações mensais
            ent_total   = venda_mes * ent_pct
            ent_parcela = ent_total / n_ent
            for e_i in range(n_ent):
                m_e = m_abs + e_i
                if m_e <= n_meses:
                    receita_mensal[m_e] += ent_parcela

            # Parcelas mensais durante n_par meses (começam após a entrada)
            parc_total = venda_mes * par_pct
            parc_mensal_v = parc_total / max(n_par, 1)
            for p in range(n_par):
                m_p = m_abs + n_ent + p   # começa após as parcelas de entrada
                if m_p <= n_meses:
                    if m_p <= mes_fim_obra:
                        corr = corr_obra
                    else:
                        corr = corr_pos_obra
                    parc_corr = parc_mensal_v * ((1 + corr) ** p)
                    receita_mensal[m_p] += parc_corr

            # Reforços: distribuídos ao longo da obra
            if n_ref > 0 and ref_pct > 0:
                ref_total = venda_mes * ref_pct
                ref_unit  = ref_total / n_ref
                for r in range(n_ref):
                    m_r = m_abs + int((duracao_obra / max(n_ref, 1)) * (r + 1))
                    if m_r <= n_meses:
                        receita_mensal[m_r] += ref_unit

            # Chaves: no mês de conclusão da obra
            if chv_pct > 0:
                chv_total = venda_mes * chv_pct
                m_chaves  = mes_fim_obra
                if m_chaves <= n_meses:
                    receita_mensal[m_chaves] += chv_total

        mes_atual_venda += duracao_f
        unidades_disponiveis = max(0, unidades_disponiveis - un_fase)
        vgv_disponivel = max(0.0, vgv_disponivel - vgv_fase)

    # ── FLUXO LÍQUIDO ─────────────────────────────────────────────────────
    fluxo = []
    saldo_acum = 0.0
    exposicao_maxima = 0.0
    tma_mensal = (1.12 ** (1/12)) - 1  # 12% a.a.

    for m in range(n_meses + 1):
        rec = receita_mensal[m]
        com = comissao_mensal[m]
        # Fix 2: impostos sobre toda receita recebida no mês (não só entrada na venda)
        tri = rec * pct_impostos
        cst = custo_mensal[m]
        saldo_mes = rec - com - tri - cst
        saldo_acum += saldo_mes
        if saldo_acum < exposicao_maxima:
            exposicao_maxima = saldo_acum

        fluxo.append({
            "mes": m,
            "receita": round(rec, 2),
            "comissao": round(com, 2),
            "tributos": round(tri, 2),
            "custo_obra": round(cst, 2),
            "saldo_mes": round(saldo_mes, 2),
            "saldo_acumulado": round(saldo_acum, 2),
        })

    # ── INDICADORES FINAIS ────────────────────────────────────────────────
    custo_total = custo_obra_total + custo_comercial + custo_impostos + valor_terreno
    resultado_bruto = vgv_liquido - custo_total
    margem_vgv    = resultado_bruto / vgv_liquido if vgv_liquido > 0 else 0
    margem_custo  = resultado_bruto / custo_total if custo_total > 0 else 0

    # TIR / VPL — base VP (nominal)
    fluxo_raw = [f["saldo_mes"] for f in fluxo[:min(len(fluxo), 120)]]
    tir_mensal = _tir(fluxo_raw)
    tir_anual  = ((1 + tir_mensal) ** 12 - 1) if tir_mensal is not None else None

    vpl = sum(f["saldo_mes"] / ((1 + tma_mensal) ** m)
              for m, f in enumerate(fluxo) if m < 120)

    # ── VF: Valor Final com correção monetária ────────────────────────────────
    # Durante obra: recebíveis e custo corrigidos por corr_obra (CUB/INCC).
    # Pós-obra: saldo devedor das parcelas atualizado por corr_pos_obra.
    # Comissão fica nominal.
    vf_fluxo_raw = []
    vf_total_rec = 0.0
    vf_total_cst = 0.0
    vf_total_com = 0.0
    for f in fluxo[:min(len(fluxo), 120)]:
        m = f["mes"]
        if m == 0:
            cf_m = 1.0
        elif m <= mes_fim_obra:
            cf_m = (1 + corr_obra) ** m
        else:
            cf_m = (1 + corr_obra) ** mes_fim_obra * (1 + corr_pos_obra) ** (m - mes_fim_obra)
        vf_rec = f["receita"] * cf_m
        vf_cst = f["custo_obra"] * cf_m
        vf_com = f["comissao"]          # comissão fica nominal
        vf_tri = vf_rec * pct_impostos
        vf_saldo = vf_rec - vf_com - vf_tri - vf_cst
        vf_total_rec += vf_rec
        vf_total_cst += vf_cst
        vf_total_com += vf_com
        vf_fluxo_raw.append(vf_saldo)

    vf_custo_com     = vf_total_com
    vf_custo_imp     = vf_total_rec * pct_impostos
    vf_resultado     = vf_total_rec - vf_total_cst - vf_custo_com - vf_custo_imp - valor_terreno
    vf_custo_total   = vf_total_cst + vf_custo_com + vf_custo_imp + valor_terreno
    vf_margem_vgv    = vf_resultado / vf_total_rec if vf_total_rec > 0 else 0
    vf_margem_custo  = vf_resultado / vf_custo_total if vf_custo_total > 0 else 0

    tir_vf_m     = _tir(vf_fluxo_raw)
    tir_vf_anual = ((1 + tir_vf_m) ** 12 - 1) if tir_vf_m is not None else None
    vpl_vf       = sum(v / (1 + tma_mensal) ** i for i, v in enumerate(vf_fluxo_raw))

    # Payback
    payback = None
    for f in fluxo:
        if f["saldo_acumulado"] > 0 and payback is None:
            payback = f["mes"]

    # Classificação
    status = _classificar(margem_vgv, tir_anual)

    # Resumo do fluxo para gráfico (trimestral para não pesar)
    fluxo_trimestral = []
    for i in range(0, min(len(fluxo), 120), 3):
        bloco = fluxo[i:i+3]
        fluxo_trimestral.append({
            "mes": i,
            "saldo_acumulado": bloco[-1]["saldo_acumulado"] if bloco else 0,
            "receita": sum(b["receita"] for b in bloco),
            "custo": sum(b["custo_obra"] + b["comissao"] + b["tributos"] for b in bloco),
        })

    return {
        # Terreno
        "area_terreno": area_terreno,
        "potencial_base": potencial_base,
        "potencial_outorga": potencial_outorga,
        "ocupacao_maxima": ocupacao_maxima,
        "area_permeavel": area_permeavel,
        "area_equivalente": area_equivalente,
        # Produto
        "unidades_total": unidades_total,
        "unidades_permuta": unidades_permuta_n,
        "area_privativa": area_privativa_total,
        "area_permutada": area_permutada,
        "vgv_bruto": round(vgv_bruto, 2),
        "vgv_liquido": round(vgv_liquido, 2),
        "valor_permuta": round(valor_permuta, 2),
        "vgv_medio_m2": round(vgv_medio_m2, 2),
        # Custos
        "cub_base": cub_base,
        "custo_cub": round(custo_cub, 2),
        "itens_extra": round(itens_extra, 2),
        "custo_obra_direto": round(custo_obra_direto, 2),
        "custo_indiretos": round(custo_indiretos, 2),
        "custo_obra_total": round(custo_obra_total, 2),
        "custo_m2_equiv": round(custo_m2_equiv, 2),
        "custo_comercial": round(custo_comercial, 2),
        "custo_impostos": round(custo_impostos, 2),
        "valor_terreno": round(valor_terreno, 2),
        "custo_total": round(custo_total, 2),
        # Resultado
        "resultado_bruto": round(resultado_bruto, 2),
        "margem_vgv": round(margem_vgv * 100, 2),
        "margem_custo": round(margem_custo * 100, 2),
        "exposicao_maxima": round(abs(exposicao_maxima), 2),
        "tir_mensal": round(tir_mensal * 100, 4) if tir_mensal is not None else None,
        "tir_anual": round(tir_anual * 100, 2) if tir_anual is not None else None,
        "vpl": round(vpl, 2),
        # VF (Valor Final) — corrigido pelo índice configurado
        "vf_vgv": round(vf_total_rec, 2),
        "vf_custo_obra": round(vf_total_cst, 2),
        "vf_custo_total": round(vf_custo_total, 2),
        "vf_resultado": round(vf_resultado, 2),
        "vf_margem_vgv": round(vf_margem_vgv * 100, 2),
        "vf_margem_custo": round(vf_margem_custo * 100, 2),
        "tir_vf_anual": round(tir_vf_anual * 100, 2) if tir_vf_anual is not None else None,
        "vpl_vf": round(vpl_vf, 2),
        "dre_vf": [
            {"desc": "VGV Corrigido",        "valor": round(vf_total_rec, 2),                          "tipo": "receita"},
            {"desc": "(−) Impostos s/ Receita VF",  "valor": -round(vf_custo_imp, 2),                         "tipo": "deducao"},
            {"desc": "(−) Comercialização",         "valor": -round(vf_custo_com, 2),                         "tipo": "deducao"},
            {"desc": "(−) Custo de Obra (VF)",      "valor": -round(vf_total_cst, 2),                         "tipo": "deducao"},
            {"desc": "(−) Terreno",                 "valor": -round(valor_terreno, 2),                         "tipo": "deducao"},
            {"desc": "Resultado VF",                "valor": round(vf_resultado, 2),                           "tipo": "resultado"},
            {"desc": "Margem VF s/ VGV corrigido",  "valor": round(vf_margem_vgv * 100, 2),                   "tipo": "pct"},
            {"desc": "↑ Ganho VF vs VP nominal",    "valor": round(vf_resultado - resultado_bruto, 2),         "tipo": "subtotal"},
        ],
        "payback_mes": payback,
        "status": status,
        # Fluxo
        "fluxo": fluxo[:min(len(fluxo), 120)],
        "fluxo_trimestral": fluxo_trimestral,
    }


def _tir(fluxos: list, max_iter: int = 200) -> float | None:
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


def _classificar(margem: float, tir: float | None) -> dict:
    tir = tir or 0
    if margem >= 0.20 and tir >= 0.20:
        return {"label": "Excelente", "color": "success", "icon": "✅",
                "desc": "Margem e TIR acima dos benchmarks. Empreendimento altamente atrativo."}
    if margem >= 0.15 and tir >= 0.15:
        return {"label": "Viável", "color": "primary", "icon": "👍",
                "desc": "Indicadores dentro do padrão de mercado. Empreendimento viável."}
    if margem >= 0.10:
        return {"label": "Atenção", "color": "warning", "icon": "⚠️",
                "desc": "Margem apertada. Desvios de custo ou velocidade de vendas podem comprometer o resultado."}
    return {"label": "Inviável", "color": "danger", "icon": "🔴",
            "desc": "Margem abaixo do mínimo viável. Revisar premissas de custo, preço ou produto."}


# ── Rotas ────────────────────────────────────────────────────────────────────

@app.get("/ferramentas/viabilidade", response_class=HTMLResponse)
@require_login
async def ferramenta_viabilidade_get(
    request: Request, session: Session = Depends(get_session),
) -> HTMLResponse:
    ctx = get_tenant_context(request, session)
    if not ctx:
        request.session.clear()
        return RedirectResponse("/login", status_code=303)
    cc = get_client_or_none(session, ctx.company.id, get_active_client_id(request, session, ctx))
    return render("ferramenta_viabilidade.html", request=request, context={
        "current_user": ctx.user, "current_company": ctx.company,
        "role": ctx.membership.role, "current_client": cc,
        "resultado": None, "dados": {},
    })


@app.post("/ferramentas/viabilidade/calcular", response_class=HTMLResponse)
@require_login
async def ferramenta_viabilidade_post(
    request: Request, session: Session = Depends(get_session),
) -> HTMLResponse:
    ctx = get_tenant_context(request, session)
    if not ctx:
        request.session.clear()
        return RedirectResponse("/login", status_code=303)
    cc = get_client_or_none(session, ctx.company.id, get_active_client_id(request, session, ctx))
    form = await request.form()
    dados: dict = dict(form)

    # Tipologias
    tipologias = []
    i = 0
    while f"tip_nome_{i}" in dados or f"tip_metragem_{i}" in dados:
        met = float(dados.get(f"tip_metragem_{i}", 0) or 0)
        qtd = int(dados.get(f"tip_qtd_{i}", 0) or 0)
        if met > 0 and qtd > 0:
            tipologias.append({
                "nome": dados.get(f"tip_nome_{i}", ""),
                "tipo": dados.get(f"tip_tipo_{i}", "Residencial"),
                "metragem": met,
                "quantidade": qtd,
                "preco_m2": float(dados.get(f"tip_preco_{i}", 0) or 0) or float(dados.get("preco_m2_base", 12500)),
                "andar_inicio": int(dados.get(f"tip_andar_{i}", 1) or 1),
                "permuta": dados.get(f"tip_permuta_{i}") == "1",
            })
        i += 1
    dados["tipologias"] = tipologias

    # Fases de venda
    fases = []
    j = 0
    while f"fase_nome_{j}" in dados:
        fases.append({
            "nome": dados.get(f"fase_nome_{j}", ""),
            "meta": float(dados.get(f"fase_meta_{j}", 0) or 0),
            "reajuste": float(dados.get(f"fase_reajuste_{j}", 0) or 0),
            "duracao": int(dados.get(f"fase_duracao_{j}", 12) or 12),
            "entrada_pct": float(dados.get(f"fase_entrada_{j}", 10) or 10),
            "n_entrada":   int(dados.get(f"fase_nentrada_{j}", 1) or 1),
            "parcelas_pct": float(dados.get(f"fase_parcelas_{j}", 80) or 80),
            "n_parcelas": int(dados.get(f"fase_nparcelas_{j}", 24) or 24),
            "reforco_pct": float(dados.get(f"fase_reforco_{j}", 0) or 0),
            "n_reforcos": int(dados.get(f"fase_nreforcos_{j}", 0) or 0),
        })
        j += 1
    if fases:
        dados["fases"] = fases

    resultado = _calcular_viabilidade_v2(dados)
    return render("ferramenta_viabilidade.html", request=request, context={
        "current_user": ctx.user, "current_company": ctx.company,
        "role": ctx.membership.role, "current_client": cc,
        "resultado": resultado, "dados": dados,
    })


# ── Template ─────────────────────────────────────────────────────────────────

TEMPLATES["ferramenta_viabilidade.html"] = r"""
{% extends "base.html" %}
{% block content %}
<style>
  .vb-hdr{display:flex;justify-content:space-between;align-items:flex-start;flex-wrap:wrap;gap:1rem;margin-bottom:1.5rem;}
  .vb-tabs{display:flex;gap:.2rem;border-bottom:2px solid var(--mc-border);margin-bottom:1.5rem;flex-wrap:wrap;overflow-x:auto;}
  .vb-tab{padding:.5rem 1rem;border:none;background:none;font-size:.86rem;font-weight:600;color:var(--mc-muted);cursor:pointer;border-bottom:2px solid transparent;margin-bottom:-2px;white-space:nowrap;transition:all .15s;}
  .vb-tab:hover{color:var(--mc-primary);}
  .vb-tab.on{color:var(--mc-primary);border-bottom-color:var(--mc-primary);}
  .vb-sec{display:none;}.vb-sec.on{display:block;}
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
  .kpi{background:#fff;border:1px solid var(--mc-border);border-radius:13px;padding:.9rem 1rem;}
  .kpi-l{font-size:.68rem;font-weight:700;text-transform:uppercase;letter-spacing:.06em;color:var(--mc-muted);}
  .kpi-v{font-size:21px;font-weight:700;letter-spacing:-.02em;margin-top:.2rem;}
  .kpi-f{font-size:.72rem;color:var(--mc-muted);margin-top:.15rem;}
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
  .fc-pos{color:var(--mc-success);}
  .fc-neg{color:var(--mc-danger);}
  .fc-wrap{max-height:480px;overflow-y:auto;border:1px solid var(--mc-border);border-radius:12px;}
  /* Verdict */
  .verdict{border-radius:14px;padding:1rem 1.2rem;border:1px solid var(--mc-border);background:#fff;margin-bottom:1.25rem;}
  .v-badge{display:inline-flex;align-items:center;gap:.4rem;font-size:.74rem;font-weight:700;text-transform:uppercase;letter-spacing:.07em;padding:.28rem .7rem;border-radius:999px;margin-bottom:.55rem;}
  .v-badge.success{background:rgba(22,163,74,.12);color:#166534;}
  .v-badge.primary{background:rgba(59,130,246,.12);color:#1e40af;}
  .v-badge.warning{background:rgba(202,138,4,.12);color:#854d0e;}
  .v-badge.danger{background:rgba(220,38,38,.12);color:#991b1b;}
  @media(max-width:640px){.vb-row,.vb-row3,.vb-row4{grid-template-columns:1fr;}.tip-hdr,.tip-row{grid-template-columns:1fr 1fr 1fr auto;}.tip-hdr span:nth-child(4),.tip-row>div:nth-child(4),.tip-hdr span:nth-child(5),.tip-row>div:nth-child(5),.tip-hdr span:nth-child(6),.tip-row>div:nth-child(6),.tip-hdr span:nth-child(7),.tip-row>div:nth-child(7){display:none;}}
  @media print{.vb-tabs,form button,nav,.navbar,aside,#augurCard{display:none!important;}.vb-sec{display:block!important;}.card{page-break-inside:avoid;}}
</style>

<div class="vb-hdr">
  <div>
    <a href="/ferramentas" class="btn btn-outline-secondary btn-sm mb-2"><i class="bi bi-arrow-left"></i> Ferramentas</a>
    <h4 class="mb-0">Viabilidade Imobiliária</h4>
    <div class="muted small">Análise completa com fluxo de caixa mensal, TIR e VPL</div>
  </div>
  {% if resultado %}
  <button onclick="window.print()" class="btn btn-outline-secondary btn-sm">
    <i class="bi bi-printer me-1"></i> Exportar PDF
  </button>
  {% endif %}
</div>

<form method="post" action="/ferramentas/viabilidade/calcular" id="vbForm">
<div class="vb-tabs">
  <button type="button" class="vb-tab on" onclick="vbTab('premissas',this)">📋 Premissas</button>
  <button type="button" class="vb-tab" onclick="vbTab('produto',this)">🏢 Produto & VGV</button>
  <button type="button" class="vb-tab" onclick="vbTab('custos',this)">🔨 Custos</button>
  <button type="button" class="vb-tab" onclick="vbTab('comercial',this)">📈 Comercialização</button>
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
  <div class="vb-sep">Cronograma</div>
  <div class="vb-row3">
    <div><div class="vb-lbl">Mês de Início da Obra</div><input class="vb-inp" type="number" name="mes_inicio_obra" step="1" min="1" placeholder="12" value="{{ dados.mes_inicio_obra or '12' }}"><div class="vb-hint">Relativo ao lançamento (mês 1)</div></div>
    <div><div class="vb-lbl">Duração da Obra (meses)</div><input class="vb-inp" type="number" name="duracao_obra" step="1" min="6" placeholder="60" value="{{ dados.duracao_obra or '60' }}"></div>
    <div><div class="vb-lbl">Início das Vendas (mês)</div><input class="vb-inp" type="number" name="mes_inicio_vendas" step="1" min="1" placeholder="3" value="{{ dados.mes_inicio_vendas or '3' }}"><div class="vb-hint">Relativo ao lançamento</div></div>
  </div>
  <div class="d-flex justify-content-end mt-3">
    <button type="button" class="btn btn-primary" onclick="vbTab('produto',document.querySelector('[onclick*=produto]'))">Produto & VGV <i class="bi bi-arrow-right ms-1"></i></button>
  </div>
</div>

{# ── ABA 2: PRODUTO ── #}
<div class="vb-sec card p-4 mb-3" id="tab-produto">
  <h5 class="mb-3">Produto & VGV</h5>
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
      {"nome":"Lançamento","meta":15,"reajuste":-15,"duracao":12,"entrada_pct":10,"n_entrada":1,"parcelas_pct":90,"n_parcelas":24,"reforco_pct":0,"n_reforcos":0},
      {"nome":"Pós-Lançamento","meta":85,"reajuste":5,"duracao":24,"entrada_pct":15,"n_entrada":1,"parcelas_pct":40,"n_parcelas":48,"reforco_pct":25,"n_reforcos":4}
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
        <div><div class="vb-lbl">Nº Parcelas Entrada</div><input class="vb-inp" type="number" name="fase_nentrada_{{ loop.index0 }}" step="1" min="1" max="24" value="{{ f.n_entrada|default(1) }}"><div class="vb-hint">1 = à vista</div></div>
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
    <button type="button" class="btn btn-primary px-4" id="calcBtn" onclick="document.getElementById('vbForm').submit()">
  <i class="bi bi-calculator me-2"></i> Calcular Viabilidade
</button>
  </div>
</div>

{# ── ABA 5: RESULTADO ── #}
{% if resultado %}
{% set r = resultado %}
{% set st = r.status %}
<div class="vb-sec card p-4 mb-3" id="tab-resultado">
  <div class="d-flex justify-content-between align-items-center mb-3">
    <h5 class="mb-0">Resultado da Análise</h5>
    {% if dados.nome_projeto %}<span class="badge text-bg-light border fw-normal">{{ dados.nome_projeto }}</span>{% endif %}
  </div>

  <div class="verdict mb-3">
    <div class="v-badge {{ st.color }}">{{ st.icon }} {{ st.label }}</div>
    <div style="font-size:.9rem;line-height:1.5;">{{ st.desc }}</div>
  </div>

  {# KPIs #}
  <div class="kpi-grid">
    <div class="kpi"><div class="kpi-l">VGV Líquido</div><div class="kpi-v" style="color:var(--mc-primary);">{{ r.vgv_liquido|brl }}</div><div class="kpi-f">{{ r.unidades_total }} unidades · {{ r.area_privativa|round|int }} m² priv.</div></div>
    <div class="kpi"><div class="kpi-l">Custo Total</div><div class="kpi-v">{{ r.custo_total|brl }}</div><div class="kpi-f">{{ r.custo_m2_equiv|round|int }} R$/m² equiv.</div></div>
    <div class="kpi"><div class="kpi-l">Resultado Bruto</div><div class="kpi-v" style="color:{{ '#16a34a' if r.resultado_bruto >= 0 else '#dc2626' }};">{{ r.resultado_bruto|brl }}</div><div class="kpi-f">{{ r.margem_vgv }}% sobre VGV</div></div>
    <div class="kpi"><div class="kpi-l">Margem s/ Custo</div><div class="kpi-v" style="color:{{ '#16a34a' if r.margem_custo >= 20 else ('#ca8a04' if r.margem_custo >= 10 else '#dc2626') }};">{{ r.margem_custo }}%</div><div class="kpi-f">Retorno sobre o investimento</div></div>
    {% if r.tir_anual is not none %}<div class="kpi"><div class="kpi-l">TIR Anual</div><div class="kpi-v" style="color:{{ '#16a34a' if r.tir_anual >= 20 else ('#ca8a04' if r.tir_anual >= 15 else '#dc2626') }};">{{ r.tir_anual }}%</div><div class="kpi-f">Taxa interna de retorno</div></div>{% endif %}
    <div class="kpi"><div class="kpi-l">Exposição Máxima</div><div class="kpi-v" style="color:#dc2626;">{{ r.exposicao_maxima|brl }}</div><div class="kpi-f">Capital necessário no pico</div></div>
    {% if r.vpl %}<div class="kpi"><div class="kpi-l">VPL (TMA 12% a.a.)</div><div class="kpi-v" style="color:{{ '#16a34a' if r.vpl >= 0 else '#dc2626' }};">{{ r.vpl|brl }}</div><div class="kpi-f">Valor presente líquido</div></div>{% endif %}
    {% if r.payback_mes %}<div class="kpi"><div class="kpi-l">Payback</div><div class="kpi-v">Mês {{ r.payback_mes }}</div><div class="kpi-f">Retorno do capital</div></div>{% endif %}
  </div>

  {# Breakdown de custos #}
  <div class="row g-3 mb-3">
    <div class="col-md-6">
      <h6 class="mb-2">Composição de Custos</h6>
      <div class="bk">
        <div class="bk-r"><span class="bk-l">CUB × Área equivalente</span><span>{{ r.custo_cub|brl }}</span></div>
        {% if r.itens_extra > 0 %}<div class="bk-r"><span class="bk-l">Itens fora do CUB</span><span>{{ r.itens_extra|brl }}</span></div>{% endif %}
        <div class="bk-r"><span class="bk-l">Despesas indiretas</span><span>{{ r.custo_indiretos|brl }}</span></div>
        {% if r.valor_terreno > 0 %}<div class="bk-r"><span class="bk-l">Terreno</span><span>{{ r.valor_terreno|brl }}</span></div>{% endif %}
        <div class="bk-r"><span class="bk-l">Comercialização</span><span>{{ r.custo_comercial|brl }}</span></div>
        <div class="bk-r"><span class="bk-l">Impostos</span><span>{{ r.custo_impostos|brl }}</span></div>
        <div class="bk-r bk-t"><span>Custo Total</span><span>{{ r.custo_total|brl }}</span></div>
      </div>
    </div>
    <div class="col-md-6">
      <h6 class="mb-2">Composição do VGV</h6>
      <div class="bk">
        <div class="bk-r"><span class="bk-l">VGV Bruto</span><span>{{ r.vgv_bruto|brl }}</span></div>
        {% if r.valor_permuta > 0 %}<div class="bk-r"><span class="bk-l">(−) Permuta ({{ r.unidades_permuta }} un.)</span><span style="color:#dc2626;">−{{ r.valor_permuta|brl }}</span></div>{% endif %}
        <div class="bk-r bk-t"><span>VGV Líquido</span><span>{{ r.vgv_liquido|brl }}</span></div>
        <div class="bk-r"><span class="bk-l">(−) Custo Total</span><span style="color:#dc2626;">−{{ r.custo_total|brl }}</span></div>
        <div class="bk-r bk-t" style="color:{{ '#16a34a' if r.resultado_bruto >= 0 else '#dc2626' }};"><span>Resultado</span><span>{{ r.resultado_bruto|brl }}</span></div>
      </div>
    </div>
  </div>

  {# Potencial construtivo #}
  <h6 class="mb-2">Potencial Construtivo</h6>
  <div class="row g-2 mb-3">
    {% for lb, vl, un in [("Área Terreno",r.area_terreno|round(1),"m²"),("Potencial Base",r.potencial_base|round(1),"m²"),("Potencial c/ Outorga",r.potencial_outorga|round(1),"m²"),("Área Equiv. CUB",r.area_equivalente|round(1),"m²"),("Área Privativa",r.area_privativa|round(1),"m²"),("VGV Médio/m²",r.vgv_medio_m2|round(0),"R$/m²")] %}
    <div class="col-6 col-md-4"><div style="background:#f9fafb;border-radius:10px;padding:.55rem .8rem;"><div style="font-size:.68rem;color:var(--mc-muted);font-weight:600;text-transform:uppercase;">{{ lb }}</div><div style="font-size:.95rem;font-weight:700;">{{ vl }} {{ un }}</div></div></div>
    {% endfor %}
  </div>

  {# Fluxo de caixa mensal #}
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
          <td>{{ f.receita|brl }}</td>
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

  <div class="d-flex gap-2 flex-wrap mt-3">
    <button type="button" class="btn btn-outline-secondary" onclick="vbTab('premissas',document.querySelector('[onclick*=premissas]'))"><i class="bi bi-pencil me-1"></i> Editar premissas</button>
    <button onclick="window.print()" type="button" class="btn btn-outline-primary"><i class="bi bi-printer me-1"></i> Exportar PDF</button>
  </div>
</div>
{% endif %}

</form>

{% if resultado %}
<script>document.addEventListener('DOMContentLoaded',function(){vbTab('resultado',document.querySelector('[onclick*="resultado"]'));});</script>
{% endif %}

<script>
function vbTab(id,btn){
  document.querySelectorAll('.vb-sec').forEach(s=>s.classList.remove('on'));
  document.querySelectorAll('.vb-tab').forEach(b=>b.classList.remove('on'));
  const s=document.getElementById('tab-'+id);if(s)s.classList.add('on');
  if(btn)btn.classList.add('on');
  window.scrollTo({top:0,behavior:'smooth'});
}
let tipN=document.querySelectorAll('[id^="tip-"]').length||1;
function addTip(){
  const c=document.getElementById('tipCont'),i=tipN++;
  const d=document.createElement('div');d.className='tip-row';d.id='tip-'+i;
  d.innerHTML=`<div><input class="vb-inp" type="text" name="tip_nome_${i}" placeholder="Nome"></div><div><select class="vb-sel" name="tip_tipo_${i}"><option>Residencial</option><option>Comercial</option></select></div><div><input class="vb-inp" type="number" name="tip_metragem_${i}" step="0.5" min="0" placeholder="102"></div><div><input class="vb-inp" type="number" name="tip_qtd_${i}" step="1" min="0" placeholder="1"></div><div><div class="pw"><span class="pre">R$</span><input class="vb-inp pl" type="number" name="tip_preco_${i}" step="100"></div></div><div><input class="vb-inp" type="number" name="tip_andar_${i}" step="1" min="1" placeholder="1"></div><div style="display:flex;align-items:center;gap:.3rem;"><input type="checkbox" name="tip_permuta_${i}" value="1" id="perm${i}"><label for="perm${i}" style="font-size:.8rem;">Sim</label></div><div><button type="button" class="btn btn-sm btn-outline-danger" onclick="rmTip(${i})">×</button></div>`;
  c.appendChild(d);
}
function rmTip(i){const el=document.getElementById('tip-'+i);if(el)el.remove();}
let faseN=document.querySelectorAll('[id^="fase-"]').length||2;
function addFase(){
  const c=document.getElementById('faseCont'),i=faseN++;
  const d=document.createElement('div');d.className='fase-card';d.id='fase-'+i;
  d.innerHTML=`<div class="fase-hdr"><input class="vb-inp" type="text" name="fase_nome_${i}" placeholder="Nome da fase" style="max-width:200px;"><button type="button" class="btn btn-sm btn-outline-danger" onclick="rmFase(${i})">Remover fase</button></div><div class="vb-row4"><div><div class="vb-lbl">Meta (%)</div><div class="pw"><span class="suf">%</span><input class="vb-inp pr" type="number" name="fase_meta_${i}" step="1" min="0" max="100" placeholder="15"></div></div><div><div class="vb-lbl">Reajuste (%)</div><div class="pw"><span class="suf">%</span><input class="vb-inp pr" type="number" name="fase_reajuste_${i}" step="1" placeholder="0"></div></div><div><div class="vb-lbl">Duração (meses)</div><input class="vb-inp" type="number" name="fase_duracao_${i}" step="1" min="1" placeholder="12"></div><div><div class="vb-lbl">Entrada (%)</div><div class="pw"><span class="suf">%</span><input class="vb-inp pr" type="number" name="fase_entrada_${i}" step="1" min="0" placeholder="10"></div></div><div><div class="vb-lbl">Nº Parcelas Entrada</div><input class="vb-inp" type="number" name="fase_nentrada_${i}" step="1" min="1" max="24" placeholder="1"><div class="vb-hint">1 = à vista</div></div></div><div class="vb-row4"><div><div class="vb-lbl">Parcelas (%)</div><div class="pw"><span class="suf">%</span><input class="vb-inp pr" type="number" name="fase_parcelas_${i}" step="1" min="0" placeholder="80"></div></div><div><div class="vb-lbl">Nº Parcelas</div><input class="vb-inp" type="number" name="fase_nparcelas_${i}" step="1" min="1" placeholder="24"></div><div><div class="vb-lbl">Reforços (%)</div><div class="pw"><span class="suf">%</span><input class="vb-inp pr" type="number" name="fase_reforco_${i}" step="1" min="0" placeholder="0"></div></div><div><div class="vb-lbl">Nº Reforços</div><input class="vb-inp" type="number" name="fase_nreforcos_${i}" step="1" min="0" placeholder="0"></div></div>`;
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

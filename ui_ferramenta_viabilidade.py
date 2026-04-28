# ============================================================================
# PATCH — Ferramenta: Viabilidade Imobiliária
# ============================================================================
# Salve como ui_ferramenta_viabilidade.py e adicione ao final do app.py:
#   exec(open('ui_ferramenta_viabilidade.py').read())
#
# ROTAS:
#   GET  /ferramentas/viabilidade          — wizard de entrada
#   POST /ferramentas/viabilidade/calcular — processa e exibe resultado
#   GET  /ferramentas/viabilidade/exportar — gera relatório PDF/HTML
#
# LÓGICA:
#   Baseada na Planilha de Viabilidade MFZ II com:
#   - Premissas do terreno (área, índices, permuta)
#   - Produto (tipologias, VGV, permuta)
#   - Custos (CUB, indiretos, taxas, comercialização)
#   - Fluxo de caixa simplificado mensal
#   - KPIs: VGV, Margem, TIR (simplificada), VPL, Exposição máxima
# ============================================================================

import json as _json
import math as _math


# ── Cálculo do motor de viabilidade ─────────────────────────────────────────

def _calcular_viabilidade(dados: dict) -> dict:
    """
    Motor de cálculo de viabilidade imobiliária.
    Recebe dict com inputs do wizard e retorna dict com resultados.
    """

    # ── TERRENO ───────────────────────────────────────────────────────────
    area_terreno    = float(dados.get("area_terreno", 0) or 0)
    indice_aprov    = float(dados.get("indice_aproveitamento", 2) or 2)
    indice_outorga  = float(dados.get("indice_outorga", 0) or 0)
    taxa_ocupacao   = float(dados.get("taxa_ocupacao", 0.5) or 0.5)
    permeabilidade  = float(dados.get("permeabilidade", 0.15) or 0.15)
    pct_permuta     = float(dados.get("pct_permuta", 0) or 0) / 100

    # Potenciais construtivos
    potencial_base   = area_terreno * indice_aprov
    potencial_outorga = area_terreno * indice_outorga if indice_outorga > 0 else potencial_base
    ocupacao_maxima  = area_terreno * taxa_ocupacao
    area_permeavel   = area_terreno * permeabilidade

    # ── PRODUTO & VGV ─────────────────────────────────────────────────────
    tipologias       = dados.get("tipologias", [])
    preco_m2_base    = float(dados.get("preco_m2_base", 12000) or 12000)
    diferencial_andar = float(dados.get("diferencial_andar", 0.005) or 0.005)  # % por andar

    vgv_total = 0.0
    vgv_liquido = 0.0
    area_privativa_total = 0.0
    area_permutada = 0.0
    valor_permuta = 0.0
    unidades_total = 0
    unidades_permuta = 0

    for tip in tipologias:
        metragem  = float(tip.get("metragem", 0) or 0)
        qtd       = int(tip.get("quantidade", 0) or 0)
        preco_m2  = float(tip.get("preco_m2", preco_m2_base) or preco_m2_base)
        eh_permuta = bool(tip.get("permuta", False))

        valor_unidade = metragem * preco_m2
        vgv_tip = valor_unidade * qtd
        vgv_total += vgv_tip
        area_privativa_total += metragem * qtd
        unidades_total += qtd

        if eh_permuta:
            area_permutada += metragem * qtd
            valor_permuta  += vgv_tip
            unidades_permuta += qtd
        else:
            vgv_liquido += vgv_tip

    # Se não cadastrou tipologias, usa inputs simplificados
    if not tipologias or vgv_total == 0:
        unidades_total       = int(dados.get("unidades_total", 0) or 0)
        metragem_media       = float(dados.get("metragem_media", 80) or 80)
        area_privativa_total = unidades_total * metragem_media
        vgv_total            = area_privativa_total * preco_m2_base
        unidades_permuta     = round(unidades_total * pct_permuta)
        area_permutada       = unidades_permuta * metragem_media
        valor_permuta        = area_permutada * preco_m2_base
        vgv_liquido          = vgv_total - valor_permuta

    # ── ÁREA CONSTRUÍDA ───────────────────────────────────────────────────
    eficiencia       = float(dados.get("eficiencia", 0.50) or 0.50)
    area_construida  = area_privativa_total / eficiencia if eficiencia > 0 else area_privativa_total * 2

    vgv_por_m2_priv  = vgv_liquido / area_privativa_total if area_privativa_total > 0 else 0
    vgv_por_m2_const = vgv_liquido / area_construida if area_construida > 0 else 0

    # ── CUSTOS ────────────────────────────────────────────────────────────
    # Custo de obra (CUB/m²)
    cub_m2           = float(dados.get("cub_m2", 3500) or 3500)
    custo_obra_bruto = cub_m2 * area_construida

    # Despesas indiretas (% sobre custo obra)
    pct_indiretos    = float(dados.get("pct_indiretos", 0.065) or 0.065)
    custo_indiretos  = custo_obra_bruto * pct_indiretos

    # Custo de aquisição do terreno (se não for 100% permuta)
    valor_terreno    = float(dados.get("valor_terreno", 0) or 0)

    # Comercialização
    pct_corretagem    = float(dados.get("pct_corretagem", 0.05) or 0.05)
    pct_gestao_com    = float(dados.get("pct_gestao_comercial", 0.015) or 0.015)
    pct_marketing     = float(dados.get("pct_marketing", 0.0075) or 0.0075)
    pct_outros_com    = float(dados.get("pct_outros_com", 0.012) or 0.012)
    pct_impostos      = float(dados.get("pct_impostos", 0.04) or 0.04)
    pct_total_com     = pct_corretagem + pct_gestao_com + pct_marketing + pct_outros_com

    custo_comercial   = vgv_liquido * pct_total_com
    custo_impostos    = vgv_liquido * pct_impostos

    # Custo total
    custo_obra_total  = custo_obra_bruto + custo_indiretos
    custo_total       = custo_obra_total + custo_comercial + custo_impostos + valor_terreno

    # ── RESULTADOS ────────────────────────────────────────────────────────
    resultado_bruto   = vgv_liquido - custo_total
    margem_bruta      = resultado_bruto / vgv_liquido if vgv_liquido > 0 else 0
    margem_sobre_custo = resultado_bruto / custo_total if custo_total > 0 else 0

    # Custo/m² construído
    custo_m2_construido = custo_obra_total / area_construida if area_construida > 0 else 0

    # ── FLUXO DE CAIXA SIMPLIFICADO ──────────────────────────────────────
    duracao_obra     = int(dados.get("duracao_obra", 36) or 36)
    inicio_vendas    = int(dados.get("inicio_vendas_mes", 1) or 1)
    duracao_vendas   = int(dados.get("duracao_vendas", duracao_obra + 24) or (duracao_obra + 24))

    # Curva de custos (S-curve simplificada)
    # 10% pré-obra, 75% durante obra (distribuído), 15% pós-obra
    meses_total = max(duracao_vendas, duracao_obra) + 12
    custos_mensais  = [0.0] * (meses_total + 1)
    receitas_mensais = [0.0] * (meses_total + 1)

    # Distribuição de custos de obra (curva S)
    for m in range(1, duracao_obra + 1):
        # Curva S: sin² normalizado
        prog = m / duracao_obra
        fator = _math.sin(_math.pi * prog) ** 0.5
        peso = fator
        custos_mensais[m] += (custo_obra_total * 0.75 / duracao_obra) * peso

    # Custos pré-obra (primeiros 3 meses)
    custo_pre = custo_obra_total * 0.10
    for m in range(0, min(3, meses_total)):
        custos_mensais[m] += custo_pre / 3

    # Terreno no mês 0
    custos_mensais[0] += valor_terreno

    # Distribuição de receitas
    # Comercial: entrada no mês da venda, parcelas durante obra, reforços e chaves no final
    # Entrada: 10% do VGV líquido
    # Parcelas: 70% distribuído
    # Chaves: 20% no mês de conclusão
    pct_entrada  = float(dados.get("pct_entrada", 0.10) or 0.10)
    pct_parcelas = float(dados.get("pct_parcelas", 0.70) or 0.70)
    pct_chaves   = 1.0 - pct_entrada - pct_parcelas

    velocidade_meses = duracao_vendas - inicio_vendas + 1
    if velocidade_meses <= 0:
        velocidade_meses = 12

    receita_mensal_venda = vgv_liquido / velocidade_meses

    for m in range(inicio_vendas, min(inicio_vendas + velocidade_meses, meses_total)):
        receitas_mensais[m] += receita_mensal_venda * pct_entrada

    for m in range(inicio_vendas, min(duracao_obra + 1, meses_total)):
        idx = m - inicio_vendas
        if idx >= 0:
            receitas_mensais[m] += receita_mensal_venda * pct_parcelas / duracao_obra

    # Chaves no mês de conclusão da obra
    if duracao_obra < meses_total:
        receitas_mensais[duracao_obra] += vgv_liquido * pct_chaves

    # Calcula saldos
    saldo_acumulado = []
    saldo = 0.0
    exposicao_maxima = 0.0

    for m in range(meses_total):
        saldo += receitas_mensais[m] - custos_mensais[m]
        saldo_acumulado.append(saldo)
        if saldo < exposicao_maxima:
            exposicao_maxima = saldo

    # TIR simplificada (IRR mensal → anualizada)
    # Usa Newton-Raphson simples
    fluxo_caixa = [receitas_mensais[m] - custos_mensais[m] for m in range(meses_total)]
    tir_anual = _calcular_tir(fluxo_caixa)

    # VPL (taxa 12% a.a. = 0.95% a.m.)
    taxa_mensal = 0.0095
    vpl = sum(fc / (1 + taxa_mensal) ** m for m, fc in enumerate(fluxo_caixa))

    # Múltiplo do investimento
    multiplo = (vgv_liquido - custo_total + custo_total) / custo_total if custo_total > 0 else 0
    multiplo = resultado_bruto / abs(exposicao_maxima) if exposicao_maxima < 0 else 0

    # Payback (mês em que saldo acumulado fica positivo)
    payback_mes = None
    for i, s in enumerate(saldo_acumulado):
        if s > 0:
            payback_mes = i
            break

    return {
        # Terreno
        "area_terreno":       area_terreno,
        "potencial_base":     potencial_base,
        "potencial_outorga":  potencial_outorga,
        "ocupacao_maxima":    ocupacao_maxima,
        "area_permeavel":     area_permeavel,
        # Produto
        "unidades_total":     unidades_total,
        "unidades_permuta":   unidades_permuta,
        "area_privativa":     area_privativa_total,
        "area_construida":    area_construida,
        "area_permutada":     area_permutada,
        "eficiencia":         eficiencia,
        # VGV
        "vgv_total":          vgv_total,
        "vgv_liquido":        vgv_liquido,
        "valor_permuta":      valor_permuta,
        "vgv_por_m2_priv":    vgv_por_m2_priv,
        "vgv_por_m2_const":   vgv_por_m2_const,
        # Custos
        "custo_obra_bruto":   custo_obra_bruto,
        "custo_indiretos":    custo_indiretos,
        "custo_obra_total":   custo_obra_total,
        "custo_comercial":    custo_comercial,
        "custo_impostos":     custo_impostos,
        "valor_terreno":      valor_terreno,
        "custo_total":        custo_total,
        "custo_m2_construido": custo_m2_construido,
        # Resultado
        "resultado_bruto":    resultado_bruto,
        "margem_bruta":       round(margem_bruta * 100, 2),
        "margem_sobre_custo": round(margem_sobre_custo * 100, 2),
        # Fluxo
        "exposicao_maxima":   abs(exposicao_maxima),
        "tir_anual":          round(tir_anual * 100, 2) if tir_anual else None,
        "vpl":                vpl,
        "payback_mes":        payback_mes,
        "saldo_acumulado":    [round(s) for s in saldo_acumulado[:duracao_obra + 25]],
        # Classificação
        "viavel":             margem_bruta >= 0.15 and (tir_anual or 0) >= 0.15,
        "status":             _classificar_viabilidade(margem_bruta, tir_anual),
    }


def _calcular_tir(fluxos: list, max_iter: int = 100) -> float | None:
    """TIR mensal via Newton-Raphson → retorna taxa anual."""
    if not fluxos or sum(1 for f in fluxos if f > 0) == 0:
        return None
    r = 0.01
    for _ in range(max_iter):
        npv  = sum(f / (1 + r) ** i for i, f in enumerate(fluxos))
        dnpv = sum(-i * f / (1 + r) ** (i + 1) for i, f in enumerate(fluxos))
        if abs(dnpv) < 1e-10:
            break
        r_new = r - npv / dnpv
        if abs(r_new - r) < 1e-8:
            r = r_new
            break
        r = r_new
    if r <= -1:
        return None
    return (1 + r) ** 12 - 1  # anualiza


def _classificar_viabilidade(margem: float, tir: float | None) -> dict:
    """Classifica o empreendimento com cor e descrição."""
    tir = tir or 0
    if margem >= 0.20 and tir >= 0.20:
        return {"label": "Excelente", "color": "success", "icon": "✅",
                "desc": "Margem e TIR acima dos benchmarks do setor. Empreendimento atrativo."}
    if margem >= 0.15 and tir >= 0.15:
        return {"label": "Viável", "color": "primary", "icon": "👍",
                "desc": "Indicadores dentro do padrão de mercado. Revisão de premissas pode melhorar o resultado."}
    if margem >= 0.10:
        return {"label": "Atenção", "color": "warning", "icon": "⚠️",
                "desc": "Margem apertada. Qualquer desvio de custo ou velocidade de vendas pode comprometer o resultado."}
    return {"label": "Inviável", "color": "danger", "icon": "🔴",
            "desc": "Margem abaixo do mínimo viável para o setor. Rever premissas de custo, preço ou produto."}


# ── Rota GET /ferramentas/viabilidade ────────────────────────────────────────

@app.get("/ferramentas/viabilidade", response_class=HTMLResponse)
@require_login
async def ferramenta_viabilidade_get(
    request: Request,
    session: Session = Depends(get_session),
) -> HTMLResponse:
    ctx = get_tenant_context(request, session)
    if not ctx:
        request.session.clear()
        return RedirectResponse("/login", status_code=303)
    current_client = get_client_or_none(
        session, ctx.company.id,
        get_active_client_id(request, session, ctx)
    )
    return render(
        "ferramenta_viabilidade.html",
        request=request,
        context={
            "current_user":    ctx.user,
            "current_company": ctx.company,
            "role":            ctx.membership.role,
            "current_client":  current_client,
            "resultado":       None,
            "dados":           {},
        },
    )


# ── Rota POST /ferramentas/viabilidade/calcular ──────────────────────────────

@app.post("/ferramentas/viabilidade/calcular", response_class=HTMLResponse)
@require_login
async def ferramenta_viabilidade_post(
    request: Request,
    session: Session = Depends(get_session),
) -> HTMLResponse:
    ctx = get_tenant_context(request, session)
    if not ctx:
        request.session.clear()
        return RedirectResponse("/login", status_code=303)
    current_client = get_client_or_none(
        session, ctx.company.id,
        get_active_client_id(request, session, ctx)
    )

    form = await request.form()
    dados: dict = {}
    for key, val in form.items():
        dados[key] = val

    # Parseia tipologias (campos dinâmicos tip_metragem_0, tip_qtd_0, etc.)
    tipologias = []
    i = 0
    while f"tip_metragem_{i}" in dados:
        metragem = float(dados.get(f"tip_metragem_{i}", 0) or 0)
        qtd      = int(dados.get(f"tip_qtd_{i}", 0) or 0)
        preco    = float(dados.get(f"tip_preco_{i}", 0) or 0)
        permuta  = dados.get(f"tip_permuta_{i}") == "1"
        if metragem > 0 and qtd > 0:
            tipologias.append({
                "metragem":   metragem,
                "quantidade": qtd,
                "preco_m2":   preco,
                "permuta":    permuta,
            })
        i += 1
    dados["tipologias"] = tipologias

    resultado = _calcular_viabilidade(dados)

    return render(
        "ferramenta_viabilidade.html",
        request=request,
        context={
            "current_user":    ctx.user,
            "current_company": ctx.company,
            "role":            ctx.membership.role,
            "current_client":  current_client,
            "resultado":       resultado,
            "dados":           dados,
        },
    )


# ── Template ─────────────────────────────────────────────────────────────────

TEMPLATES["ferramenta_viabilidade.html"] = r"""
{% extends "base.html" %}
{% block content %}
<style>
  .vb-hdr{ display:flex; justify-content:space-between; align-items:flex-start; flex-wrap:wrap; gap:1rem; margin-bottom:1.5rem; }
  .vb-tab-nav{ display:flex; gap:.25rem; border-bottom:2px solid var(--mc-border); margin-bottom:1.5rem; flex-wrap:wrap; }
  .vb-tab-btn{
    padding:.55rem 1.1rem; border:none; background:none; font-size:.88rem; font-weight:600;
    color:var(--mc-muted); cursor:pointer; border-bottom:2px solid transparent; margin-bottom:-2px;
    transition:all .15s;
  }
  .vb-tab-btn:hover{ color:var(--mc-primary); }
  .vb-tab-btn.active{ color:var(--mc-primary); border-bottom-color:var(--mc-primary); }
  .vb-section{ display:none; }
  .vb-section.active{ display:block; }
  .vb-row{ display:grid; grid-template-columns:1fr 1fr; gap:1rem; margin-bottom:1rem; }
  .vb-row3{ display:grid; grid-template-columns:1fr 1fr 1fr; gap:1rem; margin-bottom:1rem; }
  .vb-label{ font-size:.78rem; font-weight:600; color:var(--mc-muted); text-transform:uppercase; letter-spacing:.05em; margin-bottom:.3rem; }
  .vb-inp{ width:100%; border:1.5px solid var(--mc-border); border-radius:10px; padding:.6rem .9rem; font-size:.9rem; outline:none; transition:border .15s; }
  .vb-inp:focus{ border-color:var(--mc-primary); }
  .vb-inp-wrap{ position:relative; }
  .vb-inp-wrap .prefix{ position:absolute; left:.9rem; top:50%; transform:translateY(-50%); color:var(--mc-muted); font-size:.85rem; pointer-events:none; }
  .vb-inp-wrap .suffix{ position:absolute; right:.9rem; top:50%; transform:translateY(-50%); color:var(--mc-muted); font-size:.85rem; pointer-events:none; }
  .vb-inp-wrap .vb-inp.has-prefix{ padding-left:2.2rem; }
  .vb-inp-wrap .vb-inp.has-suffix{ padding-right:2.2rem; }
  .vb-sep{ font-size:.72rem; font-weight:700; text-transform:uppercase; letter-spacing:.07em; color:var(--mc-muted); padding:.6rem 0 .3rem; border-top:1px solid var(--mc-border); margin-top:.5rem; }
  .vb-tip-row{ display:grid; grid-template-columns:2fr 1fr 2fr 1fr auto; gap:.65rem; align-items:end; margin-bottom:.65rem; }
  .vb-kpi-grid{ display:grid; grid-template-columns:repeat(auto-fit,minmax(160px,1fr)); gap:.75rem; margin-bottom:1.5rem; }
  .vb-kpi{ background:#fff; border:1px solid var(--mc-border); border-radius:14px; padding:1rem 1.1rem; }
  .vb-kpi-label{ font-size:.68rem; font-weight:700; text-transform:uppercase; letter-spacing:.06em; color:var(--mc-muted); }
  .vb-kpi-val{ font-size:22px; font-weight:700; letter-spacing:-.02em; margin-top:.2rem; }
  .vb-kpi-foot{ font-size:.72rem; margin-top:.15rem; color:var(--mc-muted); }
  .vb-breakdown{ border:1px solid var(--mc-border); border-radius:12px; overflow:hidden; margin-bottom:1.25rem; }
  .vb-br-row{ display:flex; justify-content:space-between; padding:.55rem 1rem; font-size:.88rem; border-bottom:1px solid var(--mc-border); }
  .vb-br-row:last-child{ border-bottom:0; }
  .vb-br-row.total{ font-weight:700; background:var(--mc-primary-soft); }
  .vb-br-lbl{ color:var(--mc-muted); }
  .vb-bar-wrap{ background:#f3f4f6; border-radius:999px; height:8px; margin:.4rem 0; overflow:hidden; }
  .vb-bar{ height:100%; border-radius:999px; transition:width .5s ease; }
  .vb-verdict{ border-radius:14px; padding:1.1rem 1.25rem; border:1px solid var(--mc-border); background:#fff; margin-bottom:1.25rem; }
  .vb-badge{ display:inline-flex; align-items:center; gap:.4rem; font-size:.78rem; font-weight:700; text-transform:uppercase; letter-spacing:.07em; padding:.3rem .75rem; border-radius:999px; margin-bottom:.6rem; }
  .vb-badge.success{ background:rgba(22,163,74,.12); color:#166534; }
  .vb-badge.primary{ background:rgba(59,130,246,.12); color:#1e40af; }
  .vb-badge.warning{ background:rgba(202,138,4,.12); color:#854d0e; }
  .vb-badge.danger{ background:rgba(220,38,38,.12); color:#991b1b; }
  @media(max-width:640px){ .vb-row,.vb-row3{ grid-template-columns:1fr; } .vb-tip-row{ grid-template-columns:1fr 1fr; } }
</style>

<div class="vb-hdr">
  <div>
    <a href="/ferramentas" class="btn btn-outline-secondary btn-sm mb-2"><i class="bi bi-arrow-left"></i> Ferramentas</a>
    <h4 class="mb-0">Viabilidade Imobiliária</h4>
    <div class="muted small">Estude a viabilidade de um empreendimento antes de decidir</div>
  </div>
  {% if resultado %}
  <div class="d-flex gap-2">
    <button onclick="window.print()" class="btn btn-outline-secondary btn-sm">
      <i class="bi bi-printer me-1"></i> Imprimir / PDF
    </button>
  </div>
  {% endif %}
</div>

<form method="post" action="/ferramentas/viabilidade/calcular" id="vbForm">

{# ── ABAS ── #}
<div class="vb-tab-nav">
  <button type="button" class="vb-tab-btn active" onclick="vbTab('terreno',this)">🏗️ Terreno</button>
  <button type="button" class="vb-tab-btn" onclick="vbTab('produto',this)">🏢 Produto</button>
  <button type="button" class="vb-tab-btn" onclick="vbTab('custos',this)">💰 Custos</button>
  <button type="button" class="vb-tab-btn" onclick="vbTab('comercial',this)">📊 Comercialização</button>
  {% if resultado %}<button type="button" class="vb-tab-btn" onclick="vbTab('resultado',this)">✅ Resultado</button>{% endif %}
</div>

{# ── ABA 1: TERRENO ── #}
<div class="vb-section active card p-4 mb-3" id="tab-terreno">
  <h5 class="mb-3">Dados do Terreno</h5>

  <div class="vb-row">
    <div>
      <div class="vb-label">Nome do Projeto</div>
      <input class="vb-inp" type="text" name="nome_projeto" placeholder="Ex: Residencial Jardins"
             value="{{ dados.nome_projeto or '' }}">
    </div>
    <div>
      <div class="vb-label">Área do Terreno (m²)</div>
      <input class="vb-inp" type="number" name="area_terreno" step="0.01" min="0" required
             placeholder="1.918,80" value="{{ dados.area_terreno or '' }}">
    </div>
  </div>

  <div class="vb-row3">
    <div>
      <div class="vb-label">Índice de Aproveitamento</div>
      <input class="vb-inp" type="number" name="indice_aproveitamento" step="0.01" min="0"
             placeholder="5.0" value="{{ dados.indice_aproveitamento or '5' }}">
    </div>
    <div>
      <div class="vb-label">Índice c/ Outorga</div>
      <input class="vb-inp" type="number" name="indice_outorga" step="0.01" min="0"
             placeholder="6.5" value="{{ dados.indice_outorga or '0' }}">
    </div>
    <div>
      <div class="vb-label">Taxa de Ocupação</div>
      <div class="vb-inp-wrap">
        <span class="suffix">%</span>
        <input class="vb-inp has-suffix" type="number" name="taxa_ocupacao" step="1" min="0" max="100"
               placeholder="85" value="{{ (dados.taxa_ocupacao|float * 100)|round|int if dados.taxa_ocupacao else '85' }}">
      </div>
    </div>
  </div>

  <div class="vb-row3">
    <div>
      <div class="vb-label">Permeabilidade Mínima</div>
      <div class="vb-inp-wrap">
        <span class="suffix">%</span>
        <input class="vb-inp has-suffix" type="number" name="permeabilidade" step="1" min="0" max="100"
               placeholder="15" value="{{ (dados.permeabilidade|float * 100)|round|int if dados.permeabilidade else '15' }}">
      </div>
    </div>
    <div>
      <div class="vb-label">% Permuta do Terreno</div>
      <div class="vb-inp-wrap">
        <span class="suffix">%</span>
        <input class="vb-inp has-suffix" type="number" name="pct_permuta" step="0.5" min="0" max="100"
               placeholder="13.75" value="{{ dados.pct_permuta or '0' }}">
      </div>
      <div class="muted tiny mt-1">0% = compra, 100% = permuta total</div>
    </div>
    <div>
      <div class="vb-label">Valor do Terreno (R$)</div>
      <div class="vb-inp-wrap">
        <span class="prefix">R$</span>
        <input class="vb-inp has-prefix" type="number" name="valor_terreno" step="1000" min="0"
               placeholder="0" value="{{ dados.valor_terreno or '0' }}">
      </div>
      <div class="muted tiny mt-1">Se for permuta, deixe 0</div>
    </div>
  </div>

  <div class="d-flex justify-content-end mt-3">
    <button type="button" class="btn btn-primary" onclick="vbTab('produto',document.querySelector('[onclick*=produto]'))">
      Próximo: Produto <i class="bi bi-arrow-right ms-1"></i>
    </button>
  </div>
</div>

{# ── ABA 2: PRODUTO ── #}
<div class="vb-section card p-4 mb-3" id="tab-produto">
  <h5 class="mb-3">Produto & VGV</h5>

  <div class="vb-row">
    <div>
      <div class="vb-label">Preço base (R$/m²)</div>
      <div class="vb-inp-wrap">
        <span class="prefix">R$</span>
        <input class="vb-inp has-prefix" type="number" name="preco_m2_base" step="100" min="0"
               placeholder="12.500" value="{{ dados.preco_m2_base or '12500' }}">
      </div>
    </div>
    <div>
      <div class="vb-label">Eficiência da planta</div>
      <div class="vb-inp-wrap">
        <span class="suffix">%</span>
        <input class="vb-inp has-suffix" type="number" name="eficiencia" step="1" min="10" max="90"
               placeholder="50" value="{{ (dados.eficiencia|float * 100)|round|int if dados.eficiencia else '50' }}">
      </div>
      <div class="muted tiny mt-1">Área privativa / área construída total</div>
    </div>
  </div>

  <div class="vb-sep">Tipologias</div>
  <div class="muted small mb-3">Adicione cada tipo de unidade. Marque "Permuta" para unidades que vão para o dono do terreno.</div>

  <div id="tipologiasContainer">
    <div class="vb-tip-row mb-2" style="font-size:.72rem;font-weight:700;color:var(--mc-muted);text-transform:uppercase;">
      <span>Metragem (m²)</span><span>Qtd</span><span>Preço/m²</span><span>Permuta</span><span></span>
    </div>

    {% set tips = dados.tipologias if dados.tipologias else [] %}
    {% if not tips %}
      <div class="vb-tip-row" id="tip-row-0">
        <div><input class="vb-inp" type="number" name="tip_metragem_0" step="0.5" min="0" placeholder="102"></div>
        <div><input class="vb-inp" type="number" name="tip_qtd_0" step="1" min="0" placeholder="30"></div>
        <div><div class="vb-inp-wrap"><span class="prefix">R$</span><input class="vb-inp has-prefix" type="number" name="tip_preco_0" step="100" placeholder="12.500"></div></div>
        <div style="display:flex;align-items:center;gap:.4rem;"><input type="checkbox" name="tip_permuta_0" value="1" id="perm0"><label for="perm0" style="font-size:.82rem;">Sim</label></div>
        <div></div>
      </div>
    {% else %}
      {% for t in tips %}
      <div class="vb-tip-row" id="tip-row-{{ loop.index0 }}">
        <div><input class="vb-inp" type="number" name="tip_metragem_{{ loop.index0 }}" step="0.5" min="0" value="{{ t.metragem }}"></div>
        <div><input class="vb-inp" type="number" name="tip_qtd_{{ loop.index0 }}" step="1" min="0" value="{{ t.quantidade }}"></div>
        <div><div class="vb-inp-wrap"><span class="prefix">R$</span><input class="vb-inp has-prefix" type="number" name="tip_preco_{{ loop.index0 }}" step="100" value="{{ t.preco_m2 }}"></div></div>
        <div style="display:flex;align-items:center;gap:.4rem;"><input type="checkbox" name="tip_permuta_{{ loop.index0 }}" value="1" id="perm{{ loop.index0 }}" {% if t.permuta %}checked{% endif %}><label for="perm{{ loop.index0 }}" style="font-size:.82rem;">Sim</label></div>
        <div><button type="button" class="btn btn-sm btn-outline-danger" onclick="removeTip({{ loop.index0 }})">×</button></div>
      </div>
      {% endfor %}
    {% endif %}
  </div>

  <button type="button" class="btn btn-outline-secondary btn-sm mt-2" onclick="addTip()">
    <i class="bi bi-plus-circle me-1"></i> Adicionar tipologia
  </button>

  <div class="d-flex justify-content-between mt-3">
    <button type="button" class="btn btn-outline-secondary" onclick="vbTab('terreno',document.querySelector('[onclick*=terreno]'))">
      <i class="bi bi-arrow-left me-1"></i> Terreno
    </button>
    <button type="button" class="btn btn-primary" onclick="vbTab('custos',document.querySelector('[onclick*=custos]'))">
      Próximo: Custos <i class="bi bi-arrow-right ms-1"></i>
    </button>
  </div>
</div>

{# ── ABA 3: CUSTOS ── #}
<div class="vb-section card p-4 mb-3" id="tab-custos">
  <h5 class="mb-3">Custos de Produção</h5>

  <div class="vb-row">
    <div>
      <div class="vb-label">CUB / Custo de Obra (R$/m²)</div>
      <div class="vb-inp-wrap">
        <span class="prefix">R$</span>
        <input class="vb-inp has-prefix" type="number" name="cub_m2" step="50" min="0"
               placeholder="3.500" value="{{ dados.cub_m2 or '3500' }}">
      </div>
      <div class="muted tiny mt-1">Custo por m² construído (inclui acabamento)</div>
    </div>
    <div>
      <div class="vb-label">Despesas Indiretas</div>
      <div class="vb-inp-wrap">
        <span class="suffix">%</span>
        <input class="vb-inp has-suffix" type="number" name="pct_indiretos" step="0.5" min="0" max="30"
               placeholder="6.5" value="{{ dados.pct_indiretos or '6.5' }}">
      </div>
      <div class="muted tiny mt-1">% sobre custo de obra (gerenciamento, projetos, laudos)</div>
    </div>
  </div>

  <div class="vb-sep">Comercialização e Impostos</div>

  <div class="vb-row3">
    <div>
      <div class="vb-label">Corretagem</div>
      <div class="vb-inp-wrap">
        <span class="suffix">%</span>
        <input class="vb-inp has-suffix" type="number" name="pct_corretagem" step="0.5" min="0"
               placeholder="5.0" value="{{ dados.pct_corretagem or '5.0' }}">
      </div>
    </div>
    <div>
      <div class="vb-label">Gestão Comercial</div>
      <div class="vb-inp-wrap">
        <span class="suffix">%</span>
        <input class="vb-inp has-suffix" type="number" name="pct_gestao_comercial" step="0.1" min="0"
               placeholder="1.5" value="{{ dados.pct_gestao_comercial or '1.5' }}">
      </div>
    </div>
    <div>
      <div class="vb-label">Marketing</div>
      <div class="vb-inp-wrap">
        <span class="suffix">%</span>
        <input class="vb-inp has-suffix" type="number" name="pct_marketing" step="0.1" min="0"
               placeholder="0.75" value="{{ dados.pct_marketing or '0.75' }}">
      </div>
    </div>
  </div>

  <div class="vb-row">
    <div>
      <div class="vb-label">Outros custos comerciais</div>
      <div class="vb-inp-wrap">
        <span class="suffix">%</span>
        <input class="vb-inp has-suffix" type="number" name="pct_outros_com" step="0.1" min="0"
               placeholder="1.2" value="{{ dados.pct_outros_com or '1.2' }}">
      </div>
    </div>
    <div>
      <div class="vb-label">Impostos (sobre receita)</div>
      <div class="vb-inp-wrap">
        <span class="suffix">%</span>
        <input class="vb-inp has-suffix" type="number" name="pct_impostos" step="0.5" min="0"
               placeholder="4.0" value="{{ dados.pct_impostos or '4.0' }}">
      </div>
    </div>
  </div>

  <div class="d-flex justify-content-between mt-3">
    <button type="button" class="btn btn-outline-secondary" onclick="vbTab('produto',document.querySelector('[onclick*=produto]'))">
      <i class="bi bi-arrow-left me-1"></i> Produto
    </button>
    <button type="button" class="btn btn-primary" onclick="vbTab('comercial',document.querySelector('[onclick*=comercial]'))">
      Próximo: Comercialização <i class="bi bi-arrow-right ms-1"></i>
    </button>
  </div>
</div>

{# ── ABA 4: COMERCIALIZAÇÃO ── #}
<div class="vb-section card p-4 mb-3" id="tab-comercial">
  <h5 class="mb-3">Cronograma e Comercialização</h5>

  <div class="vb-row3">
    <div>
      <div class="vb-label">Duração da Obra (meses)</div>
      <input class="vb-inp" type="number" name="duracao_obra" step="1" min="6"
             placeholder="36" value="{{ dados.duracao_obra or '36' }}">
    </div>
    <div>
      <div class="vb-label">Início das Vendas (mês)</div>
      <input class="vb-inp" type="number" name="inicio_vendas_mes" step="1" min="1"
             placeholder="1" value="{{ dados.inicio_vendas_mes or '1' }}">
      <div class="muted tiny mt-1">Mês 1 = lançamento</div>
    </div>
    <div>
      <div class="vb-label">Duração das Vendas (meses)</div>
      <input class="vb-inp" type="number" name="duracao_vendas" step="1" min="1"
             placeholder="60" value="{{ dados.duracao_vendas or '60' }}">
    </div>
  </div>

  <div class="vb-sep">Condições Comerciais</div>

  <div class="vb-row3">
    <div>
      <div class="vb-label">Entrada</div>
      <div class="vb-inp-wrap">
        <span class="suffix">%</span>
        <input class="vb-inp has-suffix" type="number" name="pct_entrada" step="1" min="0" max="100"
               placeholder="10" value="{{ dados.pct_entrada or '10' }}">
      </div>
    </div>
    <div>
      <div class="vb-label">Parcelas (durante obra)</div>
      <div class="vb-inp-wrap">
        <span class="suffix">%</span>
        <input class="vb-inp has-suffix" type="number" name="pct_parcelas" step="1" min="0" max="100"
               placeholder="70" value="{{ dados.pct_parcelas or '70' }}">
      </div>
    </div>
    <div>
      <div class="vb-label">Chaves (conclusão)</div>
      <div class="vb-inp-wrap">
        <span class="suffix">%</span>
        <input class="vb-inp has-suffix" type="number" id="pct_chaves_display"
               placeholder="20" value="20" readonly style="background:#f9fafb;">
      </div>
      <div class="muted tiny mt-1">Calculado automaticamente</div>
    </div>
  </div>

  <div class="d-flex justify-content-between mt-3">
    <button type="button" class="btn btn-outline-secondary" onclick="vbTab('custos',document.querySelector('[onclick*=custos]'))">
      <i class="bi bi-arrow-left me-1"></i> Custos
    </button>
    <button type="submit" class="btn btn-primary px-4" id="calcBtn">
      <i class="bi bi-calculator me-2"></i> Calcular Viabilidade
    </button>
  </div>
</div>

{# ── ABA 5: RESULTADO ── #}
{% if resultado %}
{% set r = resultado %}
{% set status = r.status %}
<div class="vb-section {% if resultado %}active{% endif %} card p-4 mb-3" id="tab-resultado">

  <div class="d-flex justify-content-between align-items-center mb-3">
    <h5 class="mb-0">Resultado da Análise</h5>
    {% if dados.nome_projeto %}
      <span class="badge text-bg-light border fw-normal">{{ dados.nome_projeto }}</span>
    {% endif %}
  </div>

  {# Veredicto #}
  <div class="vb-verdict mb-3">
    <div class="vb-badge {{ status.color }}">{{ status.icon }} {{ status.label }}</div>
    <div style="font-size:.9rem;line-height:1.5;">{{ status.desc }}</div>
  </div>

  {# KPIs principais #}
  <div class="vb-kpi-grid">
    <div class="vb-kpi">
      <div class="vb-kpi-label">VGV Líquido</div>
      <div class="vb-kpi-val" style="color:var(--mc-primary);">{{ r.vgv_liquido|brl }}</div>
      <div class="vb-kpi-foot">{{ r.unidades_total }} unidades · {{ r.area_privativa|round|int }} m² priv.</div>
    </div>
    <div class="vb-kpi">
      <div class="vb-kpi-label">Custo Total</div>
      <div class="vb-kpi-val">{{ r.custo_total|brl }}</div>
      <div class="vb-kpi-foot">{{ r.custo_m2_construido|round|int }} R$/m² construído</div>
    </div>
    <div class="vb-kpi">
      <div class="vb-kpi-label">Resultado Bruto</div>
      <div class="vb-kpi-val" style="color:{{ '#16a34a' if r.resultado_bruto >= 0 else '#dc2626' }};">
        {{ r.resultado_bruto|brl }}
      </div>
      <div class="vb-kpi-foot">{{ r.margem_bruta }}% sobre VGV</div>
    </div>
    <div class="vb-kpi">
      <div class="vb-kpi-label">Margem s/ Custo</div>
      <div class="vb-kpi-val" style="color:{{ '#16a34a' if r.margem_sobre_custo >= 20 else ('#ca8a04' if r.margem_sobre_custo >= 10 else '#dc2626') }};">
        {{ r.margem_sobre_custo }}%
      </div>
      <div class="vb-kpi-foot">Retorno sobre investimento</div>
    </div>
    {% if r.tir_anual is not none %}
    <div class="vb-kpi">
      <div class="vb-kpi-label">TIR Anual</div>
      <div class="vb-kpi-val" style="color:{{ '#16a34a' if r.tir_anual >= 20 else ('#ca8a04' if r.tir_anual >= 15 else '#dc2626') }};">
        {{ r.tir_anual }}%
      </div>
      <div class="vb-kpi-foot">Taxa interna de retorno</div>
    </div>
    {% endif %}
    <div class="vb-kpi">
      <div class="vb-kpi-label">Exposição Máxima</div>
      <div class="vb-kpi-val" style="color:#dc2626;">{{ r.exposicao_maxima|brl }}</div>
      <div class="vb-kpi-foot">Capital necessário no pico</div>
    </div>
    {% if r.vpl %}
    <div class="vb-kpi">
      <div class="vb-kpi-label">VPL (TMA 12% a.a.)</div>
      <div class="vb-kpi-val" style="color:{{ '#16a34a' if r.vpl >= 0 else '#dc2626' }};">
        {{ r.vpl|brl }}
      </div>
      <div class="vb-kpi-foot">Valor presente líquido</div>
    </div>
    {% endif %}
    {% if r.payback_mes %}
    <div class="vb-kpi">
      <div class="vb-kpi-label">Payback</div>
      <div class="vb-kpi-val">Mês {{ r.payback_mes }}</div>
      <div class="vb-kpi-foot">Retorno do capital investido</div>
    </div>
    {% endif %}
  </div>

  {# Breakdown de custos #}
  <div class="row g-3 mb-3">
    <div class="col-md-6">
      <h6 class="mb-2">Composição de Custos</h6>
      <div class="vb-breakdown">
        <div class="vb-br-row"><span class="vb-br-lbl">Obra (diretos)</span><span>{{ r.custo_obra_bruto|brl }}</span></div>
        <div class="vb-br-row"><span class="vb-br-lbl">Despesas indiretas</span><span>{{ r.custo_indiretos|brl }}</span></div>
        {% if r.valor_terreno > 0 %}
        <div class="vb-br-row"><span class="vb-br-lbl">Terreno</span><span>{{ r.valor_terreno|brl }}</span></div>
        {% endif %}
        <div class="vb-br-row"><span class="vb-br-lbl">Comercialização</span><span>{{ r.custo_comercial|brl }}</span></div>
        <div class="vb-br-row"><span class="vb-br-lbl">Impostos</span><span>{{ r.custo_impostos|brl }}</span></div>
        <div class="vb-br-row total"><span>Custo Total</span><span>{{ r.custo_total|brl }}</span></div>
      </div>
    </div>
    <div class="col-md-6">
      <h6 class="mb-2">Composição do VGV</h6>
      <div class="vb-breakdown">
        <div class="vb-br-row"><span class="vb-br-lbl">VGV Bruto Total</span><span>{{ r.vgv_total|brl }}</span></div>
        {% if r.valor_permuta > 0 %}
        <div class="vb-br-row"><span class="vb-br-lbl">(−) Permuta ({{ r.unidades_permuta }} un.)</span><span style="color:#dc2626;">−{{ r.valor_permuta|brl }}</span></div>
        {% endif %}
        <div class="vb-br-row total"><span>VGV Líquido</span><span>{{ r.vgv_liquido|brl }}</span></div>
        <div class="vb-br-row"><span class="vb-br-lbl">(−) Custo Total</span><span style="color:#dc2626;">−{{ r.custo_total|brl }}</span></div>
        <div class="vb-br-row total" style="color:{{ '#16a34a' if r.resultado_bruto >= 0 else '#dc2626' }};"><span>Resultado</span><span>{{ r.resultado_bruto|brl }}</span></div>
      </div>
    </div>
  </div>

  {# Barras de composição #}
  <h6 class="mb-2">Distribuição do VGV</h6>
  {% set pct_custo = (r.custo_total / r.vgv_liquido * 100)|round|int if r.vgv_liquido > 0 else 0 %}
  {% set pct_resultado = (r.resultado_bruto / r.vgv_liquido * 100)|round|int if r.vgv_liquido > 0 else 0 %}
  <div class="mb-1 small d-flex justify-content-between"><span>Custo total</span><span>{{ pct_custo }}%</span></div>
  <div class="vb-bar-wrap mb-2"><div class="vb-bar" style="width:{{ pct_custo }}%;background:#ef4444;"></div></div>
  <div class="mb-1 small d-flex justify-content-between"><span>Resultado</span><span>{{ pct_resultado }}%</span></div>
  <div class="vb-bar-wrap mb-3"><div class="vb-bar" style="width:{{ [pct_resultado, 0]|max }}%;background:#16a34a;"></div></div>

  {# Informações do terreno #}
  <h6 class="mb-2">Potencial Construtivo</h6>
  <div class="row g-2 mb-3">
    {% for label, val, unit in [
      ("Área do Terreno", r.area_terreno|round(1), "m²"),
      ("Potencial Base", r.potencial_base|round(1), "m²"),
      ("Potencial c/ Outorga", r.potencial_outorga|round(1), "m²"),
      ("Área Construída", r.area_construida|round(1), "m²"),
      ("Área Privativa", r.area_privativa|round(1), "m²"),
      ("Eficiência", (r.eficiencia * 100)|round(1), "%"),
    ] %}
    <div class="col-6 col-md-4">
      <div style="background:#f9fafb;border-radius:10px;padding:.6rem .8rem;">
        <div style="font-size:.7rem;color:var(--mc-muted);font-weight:600;text-transform:uppercase;">{{ label }}</div>
        <div style="font-size:1rem;font-weight:700;">{{ val }} {{ unit }}</div>
      </div>
    </div>
    {% endfor %}
  </div>

  <div class="d-flex gap-2 flex-wrap mt-3">
    <button type="button" class="btn btn-outline-secondary" onclick="vbTab('terreno',document.querySelector('[onclick*=terreno]'))">
      <i class="bi bi-pencil me-1"></i> Editar premissas
    </button>
    <button onclick="window.print()" type="button" class="btn btn-outline-primary">
      <i class="bi bi-printer me-1"></i> Exportar PDF
    </button>
  </div>
</div>
{% endif %}

</form>

{# Injeta resultado na aba correta se existir #}
{% if resultado %}
<script>
document.addEventListener('DOMContentLoaded', function() {
  vbTab('resultado', document.querySelector('[onclick*="resultado"]'));
});
</script>
{% endif %}

<script>
// ── Navegação entre abas ───────────────────────────────────────────────────
function vbTab(id, btn) {
  document.querySelectorAll('.vb-section').forEach(s => s.classList.remove('active'));
  document.querySelectorAll('.vb-tab-btn').forEach(b => b.classList.remove('active'));
  const sec = document.getElementById('tab-' + id);
  if (sec) sec.classList.add('active');
  if (btn) btn.classList.add('active');
  window.scrollTo({top: 0, behavior: 'smooth'});
}

// ── Tipologias dinâmicas ───────────────────────────────────────────────────
let tipCount = document.querySelectorAll('[id^="tip-row-"]').length || 1;

function addTip() {
  const cont = document.getElementById('tipologiasContainer');
  const idx = tipCount++;
  const row = document.createElement('div');
  row.className = 'vb-tip-row';
  row.id = 'tip-row-' + idx;
  row.innerHTML = `
    <div><input class="vb-inp" type="number" name="tip_metragem_${idx}" step="0.5" min="0" placeholder="102"></div>
    <div><input class="vb-inp" type="number" name="tip_qtd_${idx}" step="1" min="0" placeholder="1"></div>
    <div><div class="vb-inp-wrap"><span class="prefix">R$</span><input class="vb-inp has-prefix" type="number" name="tip_preco_${idx}" step="100" placeholder="12.500"></div></div>
    <div style="display:flex;align-items:center;gap:.4rem;"><input type="checkbox" name="tip_permuta_${idx}" value="1" id="perm${idx}"><label for="perm${idx}" style="font-size:.82rem;">Sim</label></div>
    <div><button type="button" class="btn btn-sm btn-outline-danger" onclick="removeTip(${idx})">×</button></div>
  `;
  cont.appendChild(row);
}

function removeTip(idx) {
  const row = document.getElementById('tip-row-' + idx);
  if (row) row.remove();
}

// ── Calcula % chaves automaticamente ──────────────────────────────────────
function atualizaChaves() {
  const ent = parseFloat(document.querySelector('[name=pct_entrada]')?.value || 10);
  const par = parseFloat(document.querySelector('[name=pct_parcelas]')?.value || 70);
  const chv = Math.max(0, 100 - ent - par);
  const el = document.getElementById('pct_chaves_display');
  if (el) el.value = chv.toFixed(1);
}
document.querySelector('[name=pct_entrada]')?.addEventListener('input', atualizaChaves);
document.querySelector('[name=pct_parcelas]')?.addEventListener('input', atualizaChaves);
atualizaChaves();

// ── Anti double-submit ─────────────────────────────────────────────────────
document.getElementById('vbForm')?.addEventListener('submit', () => {
  const b = document.getElementById('calcBtn');
  if (b) { b.disabled = true; b.innerHTML = '<i class="bi bi-hourglass-split me-2"></i>Calculando...'; }
});
</script>

<style>
@media print {
  .vb-tab-nav, form button, nav, .navbar, aside, #augurCard { display: none !important; }
  .vb-section { display: block !important; }
  .card { border: 1px solid #ddd !important; page-break-inside: avoid; }
}
</style>
{% endblock %}
"""

# Atualiza loader
if hasattr(templates_env.loader, "mapping"):
    templates_env.loader.mapping = TEMPLATES

# ============================================================================
# FIM DO PATCH — Ferramenta: Viabilidade Imobiliária
# ============================================================================

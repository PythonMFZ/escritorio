# ============================================================================
# ui_predio_consultoria.py — 6º andar do prédio: Consultoria e Entrega
# ============================================================================
# Exec'd no namespace do app.py, DEPOIS de ui_predio.py e dos módulos de marketing,
# comercial, M&A e crédito (usa _pr_*, _mk_salvar_gerado, _mk_slug, _cm_brl).
#
# AGENTES (o Gestor de Carteira e o Secretário de Reuniões já existiam)
#   analista_financeiro — fluxo de caixa, orçamento x realizado, documentos do cliente
#                         e indicadores calculados em Python (liquidez, margens, ciclo
#                         financeiro, NCG, endividamento, rentabilidade)
#   orcamento_bsc       — orçado x realizado com a tolerância de cada conta, BSC e
#                         ações corretivas (viram tarefas com aprovação)
#   relatorio_mensal    — relatório do mês em Word (executivo ou RMA), com tabelas,
#                         seguindo o modelo anexado quando houver
# ============================================================================

import io as _io_ct
import re as _re_ct


def _ct_cliente(s, cid, cliente):
    c, cands = _pr_resolver_cliente(s, cid, cliente)
    return c, (None if c else _pr_nao_achei(cliente, cands))


# ── Fluxo de caixa ────────────────────────────────────────────────────────────

def _ct_t_fluxo(s, cid, cliente, meses_passados, meses_futuros):
    CF, CFG = globals().get("CashFlowEntry"), globals().get("CashFlowConfig")
    if CF is None:
        return {"erro": "Fluxo de caixa indisponível."}
    c, erro = _ct_cliente(s, cid, cliente)
    if erro:
        return erro
    hoje = _pr_hoje()
    mp, mf = max(1, min(int(meses_passados or 6), 24)), max(0, min(int(meses_futuros or 3), 12))
    ini = (hoje.replace(day=1) - _td_pr(days=31 * (mp - 1))).replace(day=1).isoformat()
    fim_fut = (hoje.replace(day=1) + _td_pr(days=31 * (mf + 1))).replace(day=1).isoformat()
    base = _sel_pr(CF).where(CF.company_id == cid, CF.client_id == c.id, CF.status != "cancelado")
    mes_real = _func_pr.substr(CF.data_pagamento, 1, 7)
    real = s.exec(_sel_pr(mes_real, CF.tipo, _func_pr.sum(CF.valor_cents)).where(
        CF.company_id == cid, CF.client_id == c.id, CF.status == "realizado", CF.data_pagamento >= ini)
        .group_by(mes_real, CF.tipo)).all()
    mes_prev = _func_pr.substr(CF.data_vencimento, 1, 7)
    prev = s.exec(_sel_pr(mes_prev, CF.tipo, _func_pr.sum(CF.valor_cents)).where(
        CF.company_id == cid, CF.client_id == c.id, CF.status == "previsto", CF.data_vencimento >= hoje.isoformat(),
        CF.data_vencimento < fim_fut).group_by(mes_prev, CF.tipo)).all()
    vencidos = s.exec(_sel_pr(CF.tipo, _func_pr.count(CF.id), _func_pr.sum(CF.valor_cents)).where(
        CF.company_id == cid, CF.client_id == c.id, CF.status == "previsto", CF.data_vencimento < hoje.isoformat())
        .group_by(CF.tipo)).all()
    cats = s.exec(_sel_pr(CF.categoria, _func_pr.sum(CF.valor_cents)).where(
        CF.company_id == cid, CF.client_id == c.id, CF.status == "realizado", CF.tipo == "saida",
        CF.data_pagamento >= ini).group_by(CF.categoria).order_by(_func_pr.sum(CF.valor_cents).desc()).limit(10)).all()

    def meses(linhas):
        out = {}
        for mes, tipo, v in linhas:
            if not mes:
                continue
            d = out.setdefault(mes, {"mes": mes, "entradas": 0.0, "saidas": 0.0})
            d["entradas" if tipo == "entrada" else "saidas"] += (v or 0) / 100
        for d in out.values():
            d["saldo_do_mes"] = round(d["entradas"] - d["saidas"], 2)
            d["entradas"], d["saidas"] = round(d["entradas"], 2), round(d["saidas"], 2)
        return [out[k] for k in sorted(out)]

    cfg = s.exec(_sel_pr(CFG).where(CFG.company_id == cid, CFG.client_id == c.id)).first() if CFG is not None else None
    total = s.exec(_sel_pr(_func_pr.count(CF.id)).where(CF.company_id == cid, CF.client_id == c.id)).one()
    return {"cliente": c.name, "lancamentos_no_sistema": total,
            "saldo_inicial": {"valor": (cfg.saldo_inicial_cents / 100) if cfg else None, "data": cfg.saldo_data if cfg else ""},
            "limite_conta": (cfg.limite_cc_cents / 100) if cfg else None,
            "realizado_por_mes": meses(real), "previsto_proximos_meses": meses(prev),
            "previstos_vencidos_nao_baixados": [{"tipo": t, "quantidade": n, "valor": round((v or 0) / 100, 2)} for t, n, v in vencidos],
            "maiores_saidas_por_categoria": [{"categoria": k, "valor": round((v or 0) / 100, 2)} for k, v in cats],
            "observacao": ("Sem lançamentos de fluxo de caixa para este cliente na plataforma." if not total else
                           "Valores em R$. 'Previstos vencidos' são lançamentos previstos com vencimento passado e não baixados.")}


# ── Orçamento x realizado ─────────────────────────────────────────────────────

def _ct_t_orcamento(s, cid, cliente, ano, mes_ate):
    BP, BA, BE = globals().get("BudgetPlan"), globals().get("BudgetAccount"), globals().get("BudgetEntry")
    if BP is None:
        return {"erro": "Orçamento indisponível."}
    c, erro = _ct_cliente(s, cid, cliente)
    if erro:
        return erro
    ano = int(ano or _pr_hoje().year)
    mes_ate = max(1, min(int(mes_ate or _pr_hoje().month), 12))
    plano = s.exec(_sel_pr(BP).where(BP.company_id == cid, BP.client_id == c.id, BP.year == ano)
                   .order_by(BP.is_active.desc(), BP.id.desc())).first()
    if not plano:
        return {"cliente": c.name, "erro": f"Sem orçamento de {ano} para este cliente na plataforma."}
    contas = {a.id: a for a in s.exec(_sel_pr(BA).where(BA.company_id == cid, BA.client_id == c.id)).all()}
    tol = {}
    BAL = globals().get("BudgetAlert")
    if BAL is not None:
        tol = {a.account_id: (a.tolerance_pct, a.critical_pct) for a in s.exec(_sel_pr(BAL).where(BAL.company_id == cid)).all()}
    soma = s.exec(_sel_pr(BE.account_id, _func_pr.sum(BE.value_budgeted), _func_pr.sum(BE.value_realized))
                  .where(BE.plan_id == plano.id, BE.month <= mes_ate).group_by(BE.account_id)).all()
    linhas, por_tipo = [], {}
    for acc_id, orc, real in soma:
        a = contas.get(acc_id)
        if not a or a.is_totalizer:
            continue
        orc, real = float(orc or 0), float(real or 0)
        desvio = ((real - orc) / abs(orc) * 100) if orc else None
        t_amar, t_verm = tol.get(acc_id, (10.0, 20.0))
        # despesa acima do orçado é ruim; receita abaixo do orçado é ruim
        ruim = desvio is not None and ((a.account_type == "receita" and desvio < 0) or (a.account_type != "receita" and desvio > 0))
        nivel = "verde"
        if desvio is not None and ruim and abs(desvio) >= t_verm:
            nivel = "vermelho"
        elif desvio is not None and ruim and abs(desvio) >= t_amar:
            nivel = "amarelo"
        linhas.append({"conta": f"{a.code} {a.name}".strip(), "tipo": a.account_type, "orcado": round(orc, 2),
                       "realizado": round(real, 2), "desvio_pct": round(desvio, 1) if desvio is not None else None,
                       "semaforo": nivel})
        t = por_tipo.setdefault(a.account_type, {"orcado": 0.0, "realizado": 0.0})
        t["orcado"] += orc
        t["realizado"] += real
    criticos = sorted([x for x in linhas if x["semaforo"] != "verde"],
                      key=lambda x: (x["semaforo"] != "vermelho", -abs(x["realizado"] - x["orcado"])))
    return {"cliente": c.name, "plano": plano.name, "ano": ano, "acumulado_ate_mes": mes_ate,
            "totais_por_tipo": {k: {"orcado": round(v["orcado"], 2), "realizado": round(v["realizado"], 2)} for k, v in por_tipo.items()},
            "contas_fora_da_tolerancia": criticos[:25], "contas_no_orcamento": len(linhas),
            "observacao": "Semáforo pela tolerância de cada conta (padrão: amarelo 10%, vermelho 20%)."}


# ── Indicadores financeiros (Python) ──────────────────────────────────────────

_CT_PROPS_IND = {k: {"type": "number", "description": d} for k, d in {
    "receita_bruta": "Receita bruta do período (R$).", "deducoes": "Impostos sobre vendas e devoluções.",
    "custo_vendas": "CMV/CPV/CSP.", "despesas_operacionais": "Despesas administrativas, comerciais e gerais (sem depreciação).",
    "depreciacao": "Depreciação e amortização.", "despesas_financeiras": "Juros e despesas financeiras.",
    "receitas_financeiras": "Receitas financeiras.", "ir_csll": "IR e CSLL do período.",
    "caixa": "Caixa e aplicações.", "contas_receber": "Clientes/contas a receber.", "estoques": "Estoques.",
    "ativo_circulante": "Ativo circulante total.", "ativo_total": "Ativo total.", "fornecedores": "Fornecedores.",
    "passivo_circulante": "Passivo circulante total.", "emprestimos_cp": "Empréstimos e financiamentos de curto prazo.",
    "emprestimos_lp": "Empréstimos e financiamentos de longo prazo.", "patrimonio_liquido": "Patrimônio líquido.",
    "dias_periodo": "Dias do período da DRE (360 = ano, 30 = mês)."}.items()}


def _ct_indicadores(p: dict) -> dict:
    g = lambda k: float(p.get(k) or 0)
    dias = g("dias_periodo") or 360
    rl = g("receita_bruta") - g("deducoes")
    if rl <= 0:
        raise ValueError("Informe a receita bruta (e as deduções) do período.")
    lb = rl - g("custo_vendas")
    ebitda = lb - g("despesas_operacionais")
    ebit = ebitda - g("depreciacao")
    ll = ebit - g("despesas_financeiras") + g("receitas_financeiras") - g("ir_csll")
    div_bruta = g("emprestimos_cp") + g("emprestimos_lp")
    div_liq = div_bruta - g("caixa")
    ebitda_anual = ebitda * 360 / dias

    def r(a, b, n=2):
        return round(a / b, n) if b else None

    pmr = r(g("contas_receber"), rl / dias, 0)
    pme = r(g("estoques"), g("custo_vendas") / dias, 0) if g("custo_vendas") else None
    pmp = r(g("fornecedores"), g("custo_vendas") / dias, 0) if g("custo_vendas") else None
    ncg = g("contas_receber") + g("estoques") - g("fornecedores")
    cg = g("ativo_circulante") - g("passivo_circulante")
    alertas = []
    lc = r(g("ativo_circulante"), g("passivo_circulante"))
    if lc is not None and lc < 1:
        alertas.append("Liquidez corrente abaixo de 1: obrigações de curto prazo maiores que os ativos de curto prazo.")
    dl_ebitda = r(div_liq, ebitda_anual)
    if dl_ebitda is not None and dl_ebitda > 3:
        alertas.append("Dívida líquida acima de 3x o EBITDA anualizado: alavancagem elevada.")
    cob = r(ebitda, g("despesas_financeiras"))
    if cob is not None and cob < 1.5:
        alertas.append("EBITDA cobre menos de 1,5x as despesas financeiras.")
    if cg - ncg < 0:
        alertas.append("Saldo de tesouraria negativo: a operação está sendo financiada por dívida de curto prazo.")
    ciclo_fin = (pmr or 0) + (pme or 0) - (pmp or 0) if pmr is not None else None
    return {
        "dre": {"receita_liquida": round(rl, 2), "lucro_bruto": round(lb, 2), "ebitda": round(ebitda, 2), "ebit": round(ebit, 2),
                "lucro_liquido": round(ll, 2)},
        "margens_pct": {"bruta": r(lb * 100, rl, 1), "ebitda": r(ebitda * 100, rl, 1), "operacional": r(ebit * 100, rl, 1),
                        "liquida": r(ll * 100, rl, 1)},
        "liquidez": {"corrente": lc, "seca": r(g("ativo_circulante") - g("estoques"), g("passivo_circulante")),
                     "imediata": r(g("caixa"), g("passivo_circulante"))},
        "endividamento": {"divida_bruta": round(div_bruta, 2), "divida_liquida": round(div_liq, 2),
                          "divida_liquida_sobre_ebitda_anual": dl_ebitda, "cobertura_juros_ebitda": cob,
                          "divida_cp_pct_do_total": r(g("emprestimos_cp") * 100, div_bruta, 1),
                          "capital_terceiros_sobre_pl": r(g("ativo_total") - g("patrimonio_liquido"), g("patrimonio_liquido"))},
        "capital_de_giro": {"pmr_dias": pmr, "pme_dias": pme, "pmp_dias": pmp, "ciclo_financeiro_dias": ciclo_fin,
                            "ncg": round(ncg, 2), "capital_de_giro": round(cg, 2), "saldo_tesouraria": round(cg - ncg, 2)},
        "rentabilidade_pct": {"roe_anualizado": r(ll * 360 / dias * 100, g("patrimonio_liquido"), 1),
                              "roa_anualizado": r(ll * 360 / dias * 100, g("ativo_total"), 1)},
        "alertas": alertas,
    }


def _ct_t_indicadores(s, cid, **p):
    try:
        return {"ok": True, **_ct_indicadores(p)}
    except (ValueError, TypeError, ZeroDivisionError) as e:
        return {"ok": False, "erro": str(e)}


# ── Relatório em Word ─────────────────────────────────────────────────────────

def _ct_docx(r: dict) -> bytes:
    from docx import Document
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.shared import Pt, RGBColor, Cm

    LAR, CINZA = RGBColor(0xE8, 0x77, 0x2E), RGBColor(0x6B, 0x72, 0x80)
    doc = Document()
    for sec in doc.sections:
        sec.left_margin = sec.right_margin = Cm(2)
        sec.top_margin, sec.bottom_margin = Cm(2.2), Cm(2)
        cab = sec.header.paragraphs[0]
        run = cab.add_run("M. CAPITAL")
        run.bold, run.font.size, run.font.color.rgb = True, Pt(12), LAR
        run = cab.add_run("  |  Advisory & Structured Finance")
        run.font.size, run.font.color.rgb = Pt(8.5), CINZA
        rod = sec.footer.paragraphs[0]
        rod.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        run = rod.add_run(f"{r['cliente']} · {r['periodo']} · Confidencial · página ")
        run.font.size, run.font.color.rgb = Pt(8), CINZA
        for tipo_campo in ("begin", "instr", "end"):  # número da página
            if tipo_campo == "instr":
                el = OxmlElement("w:instrText"); el.set(qn("xml:space"), "preserve"); el.text = "PAGE"
            else:
                el = OxmlElement("w:fldChar"); el.set(qn("w:fldCharType"), tipo_campo)
            r_ = rod.add_run(); r_.font.size = Pt(8); r_._r.append(el)
    estilo = doc.styles["Normal"]
    estilo.font.name, estilo.font.size = "Arial", Pt(10)

    def titulo(texto, tam=15):
        p = doc.add_paragraph()
        run = p.add_run(texto)
        run.bold, run.font.size, run.font.color.rgb = True, Pt(tam), LAR
        p.paragraph_format.space_before, p.paragraph_format.space_after = Pt(12), Pt(4)

    def texto(t):
        p = doc.add_paragraph()
        partes = _re_ct.split(r"(\*\*.+?\*\*)", str(t or ""))
        for parte in partes:
            if parte.startswith("**") and parte.endswith("**"):
                p.add_run(parte[2:-2]).bold = True
            elif parte:
                p.add_run(parte)
        p.paragraph_format.space_after = Pt(6)

    def sombrear(celula, cor):
        tc = celula._tc.get_or_add_tcPr()
        sh = OxmlElement("w:shd"); sh.set(qn("w:val"), "clear"); sh.set(qn("w:color"), "auto"); sh.set(qn("w:fill"), cor)
        tc.append(sh)

    p = doc.add_paragraph(); p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = p.add_run(r["titulo"].upper()); run.bold, run.font.size, run.font.color.rgb = True, Pt(20), LAR
    p = doc.add_paragraph(); p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = p.add_run(f"{r['cliente']}\n{r['periodo']}"); run.bold, run.font.size = True, Pt(12)
    if r.get("destaques"):
        titulo("Destaques do período", 13)
        for d in r["destaques"]:
            doc.add_paragraph(str(d), style="List Bullet")
    for i, sec in enumerate(r["secoes"], 1):
        titulo(f"{i}. {sec.get('titulo', '')}")
        for par in sec.get("paragrafos") or []:
            texto(par)
        for tb in sec.get("tabelas") or []:
            cols = [str(x) for x in (tb.get("colunas") or [])]
            linhas = [[str(v) for v in l] for l in (tb.get("linhas") or []) if isinstance(l, list)]
            if not cols:
                continue
            if tb.get("titulo"):
                p = doc.add_paragraph(); run = p.add_run(tb["titulo"]); run.bold, run.font.size = True, Pt(9.5)
            t = doc.add_table(rows=1, cols=len(cols))
            t.style = "Table Grid"
            for j, ccol in enumerate(cols):
                cel = t.rows[0].cells[j]
                cel.text = ""
                run = cel.paragraphs[0].add_run(ccol); run.bold, run.font.size = True, Pt(9)
                run.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
                sombrear(cel, "E8772E")
            for k, lin in enumerate(linhas):
                row = t.add_row().cells
                for j in range(len(cols)):
                    row[j].text = ""
                    run = row[j].paragraphs[0].add_run(lin[j] if j < len(lin) else "")
                    run.font.size = Pt(9)
                    if j:
                        row[j].paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.RIGHT
                    if k % 2:
                        sombrear(row[j], "F6F7F9")
            doc.add_paragraph()
    if r.get("ressalvas"):
        p = doc.add_paragraph(); run = p.add_run(r["ressalvas"]); run.italic, run.font.size, run.font.color.rgb = True, Pt(8), CINZA
    buf = _io_ct.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def _ct_t_gerar_relatorio(s, cid, cliente, titulo, periodo, tipo, destaques, secoes, ressalvas):
    secoes = [x for x in (secoes or []) if isinstance(x, dict) and (x.get("titulo") or "").strip()]
    if len(secoes) < 2:
        return {"ok": False, "erro": "O relatório precisa de pelo menos 2 seções com conteúdo."}
    for sec in secoes:
        for tb in sec.get("tabelas") or []:
            if isinstance(tb, dict) and len(tb.get("linhas") or []) > 400:
                return {"ok": False, "erro": f"Tabela '{tb.get('titulo')}' longa demais (máx. 400 linhas): resuma."}
    r = {"cliente": cliente or "Cliente", "titulo": titulo or "Relatório Mensal", "periodo": periodo or "",
         "destaques": [str(d) for d in (destaques or [])][:12], "secoes": secoes, "ressalvas": ressalvas or ""}
    try:
        dados = _ct_docx(r)
    except Exception as e:
        return {"ok": False, "erro": f"Não foi possível montar o Word: {e}"}
    prefixo = "RMA" if tipo == "rma" else "Relatorio"
    nome = f"{prefixo}_-_{_mk_slug(r['cliente'], 30).replace('-', '_')}_-_{_mk_slug(r['periodo'], 20).replace('-', '_')}.docx"
    a = _mk_salvar_gerado(s, cid, nome, "application/vnd.openxmlformats-officedocument.wordprocessingml.document", dados)
    return {"ok": True, "anexo_id": a.id, "arquivo": a.nome, "secoes": len(secoes),
            "observacao": "Word editável em 'Arquivos gerados' no chamado: revise antes de enviar."}


# ── Registro ──────────────────────────────────────────────────────────────────

_CT_S = {"type": "string"}
_CT_TABELA = {"type": "object", "additionalProperties": False, "required": ["titulo", "colunas", "linhas"],
              "properties": {"titulo": _CT_S, "colunas": {"type": "array", "items": _CT_S},
                             "linhas": {"type": "array", "items": {"type": "array", "items": _CT_S}}}}
_CT_FERRAMENTAS = {
    "fc_resumo": {
        "fn": _ct_t_fluxo, "rotulo": "Analisou o fluxo de caixa do cliente",
        "description": "Fluxo de caixa do cliente na plataforma: realizado por mês (entradas, saídas, saldo), previsto dos "
                       "próximos meses, previstos vencidos não baixados e maiores saídas por categoria.",
        "props": {"cliente": _CT_S, "meses_passados": {"type": "integer", "description": "1 a 24 (padrão 6)."},
                  "meses_futuros": {"type": "integer", "description": "0 a 12 (padrão 3)."}}},
    "orc_vs_real": {
        "fn": _ct_t_orcamento, "rotulo": "Comparou orçado x realizado",
        "description": "Orçamento do cliente x realizado acumulado até o mês, com semáforo pela tolerância de cada conta "
                       "e as contas fora da tolerância (receita abaixo ou despesa acima do orçado).",
        "props": {"cliente": _CT_S, "ano": {"type": "integer"}, "mes_ate": {"type": "integer", "description": "1 a 12."}}},
    "fin_indicadores": {
        "fn": _ct_t_indicadores, "rotulo": "Calculou os indicadores financeiros",
        "description": "Calcula a partir da DRE e do balanço: margens, EBITDA, liquidez, endividamento (dívida líquida/"
                       "EBITDA, cobertura de juros), prazos médios, ciclo financeiro, NCG, saldo de tesouraria, ROE e ROA, "
                       "com alertas. Use sempre para os números: nunca calcule de cabeça.",
        "props": _CT_PROPS_IND},
    "rel_gerar_relatorio": {
        "fn": _ct_t_gerar_relatorio, "rotulo": "Gerou o relatório em Word",
        "description": "Gera o relatório em Word editável (padrão M. Capital): título, destaques e seções numeradas com "
                       "parágrafos e tabelas.",
        "props": {"cliente": _CT_S, "titulo": {"type": "string", "description": "Ex.: Relatório Mensal de Atividades."},
                  "periodo": {"type": "string", "description": "Ex.: Outubro/2026."},
                  "tipo": {"type": "string", "enum": ["executivo", "rma", "diagnostico", "outro"]},
                  "destaques": {"type": "array", "items": _CT_S},
                  "secoes": {"type": "array", "items": {"type": "object", "additionalProperties": False,
                                                        "required": ["titulo", "paragrafos", "tabelas"],
                                                        "properties": {"titulo": _CT_S, "paragrafos": {"type": "array", "items": _CT_S},
                                                                       "tabelas": {"type": "array", "items": _CT_TABELA}}}},
                  "ressalvas": _CT_S}},
}

for _nome_ct, _spec_ct in _CT_FERRAMENTAS.items():
    _pr_registrar_ferramenta(_nome_ct, _spec_ct)

_CT_LEITURA = ["fc_resumo", "orc_vs_real", "val_dados_cliente", "cli_panorama", "dr_documentos", "dr_ler_documento",
               "reu_listar", "reu_conteudo", "conh_buscar", "conh_ler"]

_CT_AGENTES = {
    "analista_financeiro": {
        "ferramentas": _CT_LEITURA + ["fin_indicadores", "rel_gerar_relatorio", "ops_propor_tarefa"],
        "instrucoes": (
            "Você é o analista financeiro dos clientes do escritório. Trabalha com os números reais: DRE, balanço e "
            "balancetes (documentos do cliente com dr_documentos/dr_ler_documento ou anexados ao chamado), fluxo de "
            "caixa (fc_resumo) e orçamento (orc_vs_real).\n"
            "- Indicadores: extraia as contas da DRE e do balanço e calcule SEMPRE com fin_indicadores — nunca de "
            "cabeça. Diga de onde veio cada número (arquivo, aba, período) e o que precisou estimar.\n"
            "- Análise: comece pelo que importa para o caixa e a sobrevivência (liquidez, ciclo financeiro, saldo de "
            "tesouraria, alavancagem e custo da dívida), depois rentabilidade. Compare com o período anterior quando "
            "houver. Explique em linguagem de empresário e termine com 3 a 5 recomendações concretas.\n"
            "- Inconsistências (balanço que não fecha, DRE que não bate com o fluxo de caixa): aponte em vez de "
            "esconder.\n"
            "- Quando pedido, entregue em Word com rel_gerar_relatorio (tipo 'diagnostico') e proponha tarefas para "
            "os próximos passos.")},
    "orcamento_bsc": {
        "ferramentas": ["orc_vs_real", "fc_resumo", "cli_panorama", "reu_listar", "reu_conteudo", "conh_buscar",
                        "rel_gerar_relatorio", "ops_propor_tarefa"],
        "instrucoes": (
            "Você acompanha o orçamento e o BSC dos clientes.\n"
            "- Orçado x realizado (orc_vs_real): destaque as contas no vermelho e no amarelo, explique o desvio (preço, "
            "volume, pontual ou tendência — use o fluxo de caixa e as reuniões para entender) e estime o impacto no "
            "resultado do ano se nada mudar.\n"
            "- BSC (no panorama do cliente): indicadores fora da meta e a relação com os desvios do orçamento.\n"
            "- Ações corretivas: para cada problema relevante, uma ação concreta com responsável e prazo; proponha "
            "como tarefa (ops_propor_tarefa). Não proponha ação genérica ('reduzir custos'): diga qual custo e quanto.\n"
            "- Quando pedido, gere o relatório de acompanhamento em Word.")},
    "relatorio_mensal": {
        "ferramentas": _CT_LEITURA + ["fin_indicadores", "rel_gerar_relatorio", "ops_propor_tarefa"],
        "instrucoes": (
            "Você monta o relatório do mês de cada cliente em Word (rel_gerar_relatorio).\n"
            "Se o usuário anexar um relatório anterior ou um modelo, siga exatamente a mesma estrutura, títulos, "
            "ordem e tom — é o padrão do escritório. Sem modelo, use:\n"
            "• Relatório executivo (tipo 'executivo'): destaques do mês; resultado e caixa (fluxo realizado x previsto); "
            "orçamento x realizado; indicadores (fin_indicadores) e BSC; o que foi feito no mês (reuniões, tarefas e "
            "ações concluídas); riscos e pontos de atenção; próximos passos com responsável e prazo.\n"
            "• RMA — Relatório Mensal de Atividades da recuperação judicial (tipo 'rma'), no padrão da Recomendação "
            "CNJ 72/2020: 1. Considerações iniciais e andamento processual; 2. Informações da recuperanda (atividade, "
            "estrutura societária, quadro de funcionários, estabelecimentos); 3. Análise econômico-financeira (balanço, "
            "DRE e fluxo de caixa do mês e acumulado, indicadores e variações relevantes); 4. Endividamento (concursal "
            "por classe, extraconcursal e tributário); 5. Cumprimento do plano e pagamentos do mês; 6. Diligências, "
            "visitas e informações solicitadas; 7. Considerações finais. Tabelas com valores do mês, mês anterior e "
            "variação.\n"
            "Regras: todo número vem de um documento, do sistema ou de fin_indicadores — cite a fonte; o que não tiver, "
            "deixe como [PENDENTE: ...] em vez de inventar; linguagem técnica e objetiva. No chat, liste o que ficou "
            "pendente e o que o sócio deve revisar.")},
}

for _key_ct, _cfg_ct in _CT_AGENTES.items():
    _ag_ct = _PREDIO_AGENTES.get(_key_ct)
    if not _ag_ct:
        continue
    _ag_ct.update(ferramentas=list(_cfg_ct["ferramentas"]), web=False, ativo=True)
    _PR_INSTRUCOES[_key_ct] = _cfg_ct["instrucoes"]

print("[predio_consultoria] Andar de Consultoria e Entrega completo.")

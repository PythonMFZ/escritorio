# ============================================================================
# ui_predio_credito.py — 5º andar do prédio: Crédito e Mercado de Capitais
# ============================================================================
# Exec'd no namespace do app.py, DEPOIS de ui_predio.py e dos módulos de marketing,
# comercial e M&A (usa _pr_*, _mk_salvar_gerado, _mk_slug, _cm_brl, _ma_doc).
#
# AGENTES
#   estruturador           — desenha a operação (bancária, CRI, CRA, debênture, FIDC),
#                            compara estruturas com simulação calculada em Python
#                            (parcelas, CET, DSCR), cruza com os produtos dos parceiros
#                            e monta o book de crédito em PDF
#   analista_risco         — SCR e dossiês do ConstruRisk já consultados, capacidade de
#                            pagamento, garantias, rating interno e covenants
#   relacao_investidores   — parceiros (bancos, securitizadoras, fundos), operações em
#                            andamento e envio do book ao parceiro (só admin aprova;
#                            o e-mail sai para o contato cadastrado do parceiro)
#
# Nenhuma consulta paga (SCR/dossiê) é disparada pelos agentes: eles usam as que
# já existem e dizem qual consulta pedir.
# ============================================================================


# ── Simulação de dívida ───────────────────────────────────────────────────────

def _cr_taxa_mensal(alt: dict, cdi_aa: float, ipca_aa: float) -> float:
    taxa = float(alt.get("taxa_aa") or 0) / 100
    idx = (alt.get("indexador") or "pre").lower()
    if idx == "cdi":
        anual = (1 + cdi_aa / 100) * (1 + taxa) - 1
    elif idx == "ipca":
        anual = (1 + ipca_aa / 100) * (1 + taxa) - 1
    else:
        anual = taxa
    return (1 + anual) ** (1 / 12) - 1


def _cr_tir_mensal(fluxos: list) -> float:
    """TIR mensal por bisseção (fluxo 0 positivo = dinheiro recebido)."""
    def vpl(r):
        return sum(f / (1 + r) ** i for i, f in enumerate(fluxos))
    lo, hi = -0.99, 1.0
    if vpl(lo) * vpl(hi) > 0:
        return float("nan")
    for _ in range(200):
        meio = (lo + hi) / 2
        if vpl(lo) * vpl(meio) <= 0:
            hi = meio
        else:
            lo = meio
    return (lo + hi) / 2


def _cr_simular_uma(alt: dict, valor: float, prazo: int, carencia: int, cdi: float, ipca: float, caixa_mensal: float) -> dict:
    i = _cr_taxa_mensal(alt, cdi, ipca)
    amort = (alt.get("amortizacao") or "PRICE").upper()
    custo_ini = valor * float(alt.get("custos_iniciais_pct") or 0) / 100
    custo_anual = float(alt.get("custos_anuais_pct") or 0) / 100
    saldo, fluxos, parcelas, juros_tot = valor, [valor - custo_ini], [], 0.0
    n_amort = max(prazo - carencia, 1)
    pmt_price = valor * i / (1 - (1 + i) ** -n_amort) if i > 0 else valor / n_amort
    for m in range(1, prazo + 1):
        juros = saldo * i
        custo = saldo * custo_anual / 12
        if m <= carencia:
            principal = 0.0
        elif amort == "SAC":
            principal = valor / n_amort
        elif amort == "BULLET":
            principal = saldo if m == prazo else 0.0
        else:
            principal = pmt_price - juros
        principal = min(principal, saldo)
        pag = juros + principal + custo
        saldo -= principal
        juros_tot += juros
        parcelas.append(pag)
        fluxos.append(-pag)
    tir = _cr_tir_mensal(fluxos)
    cet = (1 + tir) ** 12 - 1 if tir == tir else None
    anos = []
    for a in range(0, prazo, 12):
        anos.append({"ano": a // 12 + 1, "pago": sum(parcelas[a:a + 12])})
    dscr = None
    if caixa_mensal > 0:
        pagas = [p for p in parcelas if p > 0]
        dscr = min(caixa_mensal / p for p in pagas) if pagas else None
    return {"nome": alt.get("nome") or "Alternativa", "indexador": alt.get("indexador"), "amortizacao": amort,
            "taxa_efetiva_aa_pct": ((1 + i) ** 12 - 1) * 100, "cet_aa_pct": cet * 100 if cet is not None else None,
            "valor_liquido_recebido": valor - custo_ini, "primeira_parcela": parcelas[0] if parcelas else 0,
            "maior_parcela": max(parcelas) if parcelas else 0, "total_pago": sum(parcelas), "juros_totais": juros_tot,
            "dscr_minimo": dscr, "por_ano": anos}


def _cr_simular(p: dict) -> dict:
    valor = float(p.get("valor") or 0)
    prazo = int(p.get("prazo_meses") or 0)
    carencia = int(p.get("carencia_meses") or 0)
    if valor <= 0 or not 1 <= prazo <= 360:
        raise ValueError("Informe valor maior que zero e prazo entre 1 e 360 meses.")
    if carencia >= prazo:
        raise ValueError("A carência precisa ser menor que o prazo.")
    alts = [a for a in (p.get("alternativas") or []) if isinstance(a, dict)][:6]
    if not alts:
        raise ValueError("Informe pelo menos uma alternativa de estrutura.")
    cdi, ipca = float(p.get("cdi_aa") or 0), float(p.get("ipca_aa") or 0)
    caixa = float(p.get("geracao_caixa_mensal") or 0)
    res = [_cr_simular_uma(a, valor, prazo, carencia, cdi, ipca, caixa) for a in alts]
    validos = [r for r in res if r["cet_aa_pct"] is not None]
    melhor = min(validos, key=lambda r: r["cet_aa_pct"])["nome"] if validos else None
    return {"valor": valor, "prazo_meses": prazo, "carencia_meses": carencia, "cdi_aa_pct": cdi, "ipca_aa_pct": ipca,
            "geracao_caixa_mensal": caixa, "alternativas": res, "menor_cet": melhor}


def _cr_resumo(r: dict) -> dict:
    def m(v):
        return None if v is None else round(v / 1e3, 1)
    return {"unidade": "R$ mil", "menor_cet": r["menor_cet"], "alternativas": [
        {"nome": a["nome"], "amortizacao": a["amortizacao"], "taxa_efetiva_aa_pct": round(a["taxa_efetiva_aa_pct"], 2),
         "cet_aa_pct": round(a["cet_aa_pct"], 2) if a["cet_aa_pct"] is not None else None,
         "valor_liquido_recebido": m(a["valor_liquido_recebido"]), "primeira_parcela": m(a["primeira_parcela"]),
         "maior_parcela": m(a["maior_parcela"]), "total_pago": m(a["total_pago"]), "juros_totais": m(a["juros_totais"]),
         "dscr_minimo": round(a["dscr_minimo"], 2) if a["dscr_minimo"] is not None else None,
         "alerta": ("DSCR abaixo de 1,2: o caixa mal cobre a parcela." if a["dscr_minimo"] is not None and a["dscr_minimo"] < 1.2
                    else "")}
        for a in r["alternativas"]]}


_CR_PROPS_SIM = {
    "valor": {"type": "number", "description": "Valor captado em R$."},
    "prazo_meses": {"type": "integer"},
    "carencia_meses": {"type": "integer", "description": "Meses só com juros (0 se não houver)."},
    "cdi_aa": {"type": "number", "description": "CDI projetado % a.a. (use mkt_indicadores)."},
    "ipca_aa": {"type": "number", "description": "IPCA projetado % a.a."},
    "geracao_caixa_mensal": {"type": "number", "description": "Caixa operacional mensal disponível para a dívida (0 = sem DSCR)."},
    "alternativas": {"type": "array", "description": "Até 6 estruturas a comparar.", "items": {
        "type": "object", "additionalProperties": False,
        "required": ["nome", "indexador", "taxa_aa", "amortizacao", "custos_iniciais_pct", "custos_anuais_pct"],
        "properties": {"nome": {"type": "string", "description": "Ex.: Capital de giro Banco X, CRI IPCA+."},
                       "indexador": {"type": "string", "enum": ["pre", "cdi", "ipca"]},
                       "taxa_aa": {"type": "number", "description": "Taxa prefixada ou spread sobre o indexador, % a.a."},
                       "amortizacao": {"type": "string", "enum": ["PRICE", "SAC", "BULLET"]},
                       "custos_iniciais_pct": {"type": "number", "description": "Estruturação, TAC, registro etc., % do valor."},
                       "custos_anuais_pct": {"type": "number", "description": "Custos recorrentes (agente fiduciário, custódia), % a.a. do saldo."}}}},
}


def _cr_t_simular(s, cid, **p):
    try:
        return {"ok": True, **_cr_resumo(_cr_simular(p))}
    except (ValueError, TypeError, ZeroDivisionError, OverflowError) as e:
        return {"ok": False, "erro": str(e)}


# ── Dados de crédito já existentes na plataforma ──────────────────────────────

def _cr_t_scr(s, cid, cliente):
    c, cands = _pr_resolver_cliente(s, cid, cliente)
    if not c:
        return _pr_nao_achei(cliente, cands)
    R = CreditReport
    linhas = s.exec(_sel_pr(R.created_at, R.document_type, R.document_value, R.status, R.score, R.faixa_risco,
                            R.risco_total_brl, R.carteira_total_brl, R.carteira_vencer_brl, R.carteira_vencido_brl,
                            R.carteira_prejuizo_brl, R.quantidade_instituicoes, R.quantidade_operacoes, R.message)
                    .where(R.company_id == cid, R.client_id == c.id).order_by(R.created_at.desc()).limit(6)).all()
    return {"cliente": c.name, "consultas": [
        {"data": _pr_fmt_data(x[0].date()) if x[0] else "", "documento": f"{x[1].upper()} ***{(x[2] or '')[-4:]}",
         "status": x[3], "score": x[4], "faixa_risco": x[5], "risco_total": x[6], "carteira_total": x[7],
         "a_vencer": x[8], "vencido": x[9], "prejuizo": x[10], "instituicoes": x[11], "operacoes": x[12],
         "mensagem": (x[13] or "")[:200]} for x in linhas],
        "observacao": ("Nenhuma consulta SCR deste cliente. Ela é paga e exige autorização do cliente: peça para fazer em "
                       "Consultas de Risco." if not linhas else "Dados do Registrato/SCR do Banco Central via consulta já feita.")}


def _cr_t_dossies(s, cid, cliente):
    D = globals().get("ConstruRiskDossie")
    if D is None:
        return {"erro": "ConstruRisk indisponível."}
    c, cands = _pr_resolver_cliente(s, cid, cliente)
    if not c:
        return _pr_nao_achei(cliente, cands)
    linhas = s.exec(_sel_pr(D.id, D.nome, D.person_type, D.document, D.status, D.created_at,
                            _func_pr.substr(D.parecer_ia, 1, 8000))
                    .where(D.company_id == cid, D.client_id == c.id).order_by(D.id.desc()).limit(8)).all()
    return {"cliente": c.name, "dossies": [
        {"dossie_id": x[0], "nome": x[1], "tipo": x[2], "documento": f"***{(x[3] or '')[-4:]}", "status": x[4],
         "data": (x[5] or "")[:10], "parecer": x[6] or ""} for x in linhas],
        "observacao": ("Nenhum dossiê do ConstruRisk deste cliente (sócios ou empresa). A consulta é paga: indique quem "
                       "consultar." if not linhas else "Pareceres de crédito e PLD gerados no ConstruRisk.")}


def _cr_t_produtos(s, cid, valor, faturamento_anual, prazo_meses, area):
    q = _sel_pr(PartnerProduct, Partner).where(PartnerProduct.company_id == cid, PartnerProduct.is_active == True,  # noqa: E712
                                              Partner.id == PartnerProduct.partner_id, Partner.is_active == True)  # noqa: E712
    termos = [_pr_norm(t) for t in (area or "").split() if len(t) > 2]
    saida = []
    for pp, pa in s.exec(q).all():
        texto = _pr_norm(f"{pp.area} {pp.family_code} {pp.family_slug} {pp.name} {pa.name} {pp.notes}")
        if termos and not any(t in texto for t in termos):
            continue
        motivos = []
        v, fat, pr = float(valor or 0), float(faturamento_anual or 0), int(prazo_meses or 0)
        if v and pp.ticket_min_brl and v < pp.ticket_min_brl:
            motivos.append(f"ticket mínimo {_cm_brl(pp.ticket_min_brl)}")
        if v and pp.ticket_max_brl and v > pp.ticket_max_brl:
            motivos.append(f"ticket máximo {_cm_brl(pp.ticket_max_brl)}")
        if fat and pp.revenue_min_brl and fat < pp.revenue_min_brl:
            motivos.append(f"faturamento mínimo {_cm_brl(pp.revenue_min_brl)}")
        if fat and pp.revenue_max_brl and fat > pp.revenue_max_brl:
            motivos.append(f"faturamento máximo {_cm_brl(pp.revenue_max_brl)}")
        if pr and pp.term_max_months and pr > pp.term_max_months:
            motivos.append(f"prazo máximo {pp.term_max_months} meses")
        saida.append({"parceiro": pa.name, "tipo_parceiro": pa.partner_type, "produto": pp.name, "area": pp.area,
                      "taxa_aa_pct": pp.rate_default_pct, "cet_aa_pct": pp.cet_default_pct,
                      "prazo_meses": f"{pp.term_min_months}–{pp.term_max_months}", "carencia_max": pp.grace_max_months,
                      "amortizacao": pp.amortization_default, "ltv_max_pct": pp.ltv_max_pct,
                      "exige_garantia": pp.requires_collateral, "comissao": pp.commission_text,
                      "observacoes": (pp.notes or "")[:300], "atende": not motivos, "nao_atende_por": motivos})
    saida.sort(key=lambda x: (not x["atende"], x["taxa_aa_pct"] or 999))
    return {"produtos": saida[:40], "total": len(saida),
            "observacao": "Produtos cadastrados em Parceiros. Taxas são as de referência do cadastro: confirme com o parceiro."}


def _cr_t_parceiros(s, cid, tipo):
    q = _sel_pr(Partner).where(Partner.company_id == cid, Partner.is_active == True)  # noqa: E712
    if (tipo or "").strip():
        q = q.where(Partner.partner_type == tipo.strip())
    out = []
    for pa in s.exec(q.order_by(Partner.name)).all():
        n = len(s.exec(_sel_pr(PartnerProduct.id).where(PartnerProduct.partner_id == pa.id,
                                                       PartnerProduct.is_active == True)).all())  # noqa: E712
        out.append({"parceiro_id": pa.id, "nome": pa.name, "tipo": pa.partner_type, "contato": pa.contact_name,
                    "tem_email": bool((pa.contact_email or "").strip()), "produtos_ativos": n, "notas": (pa.notes or "")[:300]})
    return {"parceiros": out, "total": len(out)}


_CR_SERVICOS_CREDITO = ("capta", "cri", "cra", "debent", "credito", "crédito", "fidc", "divida", "dívida", "dcm", "estrutur")


def _cr_t_operacoes(s, cid):
    rotulos = {st["key"]: st["label"] for st in globals().get("CRM_STAGES", [])}
    nomes = _pr_clientes(s, cid)
    out = []
    for d in s.exec(_sel_pr(BusinessDeal).where(BusinessDeal.company_id == cid,
                                                BusinessDeal.stage.notin_(["perdido"])).order_by(BusinessDeal.updated_at.desc())).all():
        alvo = _pr_norm(f"{d.service_name} {d.title}")
        if not any(_pr_norm(k) in alvo for k in _CR_SERVICOS_CREDITO):
            continue
        notas = s.exec(_sel_pr(BusinessDealNote.message, BusinessDealNote.created_at).where(BusinessDealNote.deal_id == d.id)
                       .order_by(BusinessDealNote.created_at.desc()).limit(3)).all()
        out.append({"negocio_id": d.id, "operacao": d.title, "cliente": nomes.get(d.client_id, ""), "servico": d.service_name,
                    "etapa": rotulos.get(d.stage, d.stage), "valor": d.value_estimate_brl, "proximo_passo": d.next_step,
                    "data_proximo_passo": d.next_step_date, "atualizado": _pr_quando(d.updated_at),
                    "notas_recentes": [n[0][:200] for n in notas]})
    return {"operacoes": out[:40], "total": len(out)}


# ── Book de crédito (PDF) ─────────────────────────────────────────────────────

def _cr_pdf_book(b: dict, sim: dict) -> bytes:
    from reportlab.platypus import PageBreak, Paragraph, Spacer

    def construir(S, C, LARG):
        P = lambda t, e="corpo": Paragraph(_ma_txt(t), S[e])
        h = [Spacer(1, 20), P("BOOK DE CRÉDITO", "titulo"), Spacer(1, 4), P(b["empresa"], "sub"),
             P(f"{b.get('operacao', '')} · {_cm_brl(sim['valor'])} · {sim['prazo_meses']} meses", "sub_c"), Spacer(1, 16),
             P("Resumo da operação", "h1"), Spacer(1, 3), P(b.get("resumo", "")), Spacer(1, 8),
             P("Uso dos recursos", "h1"), Spacer(1, 3), P(b.get("uso_recursos", "")), Spacer(1, 8),
             P("A empresa", "h1"), Spacer(1, 3), P(b.get("empresa_descricao", ""))]
        if b.get("indicadores"):
            t = [[Paragraph("INDICADOR", S["cab"]), Paragraph("VALOR", S["cab"]), Paragraph("COMENTÁRIO", S["cab"])]]
            t += [[P(i.get("indicador"), "neg"), P(i.get("valor"), "cel"), P(i.get("comentario"), "cel_e")] for i in b["indicadores"]]
            h += [Spacer(1, 10), P("Indicadores", "h1"), Spacer(1, 3), _ma_tabela(t, [LARG * 0.3, LARG * 0.2, LARG * 0.5], C)]
        h += [PageBreak(), P("Estruturas comparadas", "h1"), Spacer(1, 3)]
        cab = ["", *[a["nome"] for a in sim["alternativas"]]]
        n = len(cab)

        def lin(rot, f):
            return [P(rot, "neg")] + [P(f(a), "cel") for a in sim["alternativas"]]
        pct = lambda v: "—" if v is None else f"{v:.2f}%".replace(".", ",")
        t = [[Paragraph(x, S["cab"]) for x in cab],
             lin("Amortização", lambda a: a["amortizacao"]),
             lin("Taxa efetiva a.a.", lambda a: pct(a["taxa_efetiva_aa_pct"])),
             lin("CET a.a.", lambda a: pct(a["cet_aa_pct"])),
             lin("Líquido recebido", lambda a: _cm_brl(a["valor_liquido_recebido"])),
             lin("1ª parcela", lambda a: _cm_brl(a["primeira_parcela"])),
             lin("Maior parcela", lambda a: _cm_brl(a["maior_parcela"])),
             lin("Total pago", lambda a: _cm_brl(a["total_pago"])),
             lin("DSCR mínimo", lambda a: "—" if a["dscr_minimo"] is None else f"{a['dscr_minimo']:.2f}x".replace(".", ","))]
        h += [_ma_tabela(t, [LARG * 0.24] + [LARG * 0.76 / (n - 1)] * (n - 1), C), Spacer(1, 4),
              P(f"Premissas: CDI {pct(sim['cdi_aa_pct'])} e IPCA {pct(sim['ipca_aa_pct'])} a.a.; carência de "
                f"{sim['carencia_meses']} meses. CET calculado com os custos informados de cada estrutura.", "nota"),
              Spacer(1, 10), P("Estrutura recomendada", "h1"), Spacer(1, 3), P(b.get("recomendacao", ""))]
        if b.get("garantias"):
            h += [Spacer(1, 8), P("Garantias", "h1"), Spacer(1, 3)] + [P(f"•  {g}") for g in b["garantias"]]
        if b.get("riscos"):
            t = [[Paragraph("RISCO", S["cab"]), Paragraph("MITIGANTE", S["cab"])]]
            t += [[P(r.get("risco"), "cel_e"), P(r.get("mitigante"), "cel_e")] for r in b["riscos"]]
            h += [Spacer(1, 10), P("Riscos e mitigantes", "h1"), Spacer(1, 3), _ma_tabela(t, [LARG * 0.45, LARG * 0.55], C)]
        h += [Spacer(1, 12), P("Documento confidencial, para uso exclusivo do destinatário na análise da operação. Informações "
                               "fornecidas pela empresa, sem auditoria; taxas e custos indicativos, sujeitos a aprovação de "
                               "crédito.", "nota")]
        return h

    return _ma_doc("Book de Crédito — Confidencial", construir)


def _cr_t_gerar_book(s, cid, empresa, operacao, resumo, uso_recursos, empresa_descricao, indicadores, simulacao,
                     recomendacao, garantias, riscos):
    if not isinstance(simulacao, dict):
        return {"ok": False, "erro": "Envie a simulação (os mesmos dados de cred_simular)."}
    try:
        sim = _cr_simular(simulacao)
    except (ValueError, TypeError, ZeroDivisionError, OverflowError) as e:
        return {"ok": False, "erro": str(e)}
    if len((resumo or "").strip()) < 40 or len((recomendacao or "").strip()) < 20:
        return {"ok": False, "erro": "Escreva o resumo da operação e a estrutura recomendada."}
    b = {"empresa": empresa, "operacao": operacao, "resumo": resumo, "uso_recursos": uso_recursos,
         "empresa_descricao": empresa_descricao, "indicadores": indicadores or [], "recomendacao": recomendacao,
         "garantias": garantias or [], "riscos": riscos or []}
    a = _mk_salvar_gerado(s, cid, f"Book_de_credito_-_{_mk_slug(empresa, 40).replace('-', '_')}.pdf", "application/pdf",
                          _cr_pdf_book(b, sim))
    return {"ok": True, "anexo_id": a.id, "arquivo": a.nome, "simulacao": _cr_resumo(sim)}


# ── Envio ao parceiro (banco, securitizadora, fundo) ──────────────────────────

def _cr_t_propor_envio(s, cid, parceiro, assunto, corpo, anexo_ids):
    alvo = _pr_norm(parceiro)
    pas = [p for p in s.exec(_sel_pr(Partner).where(Partner.company_id == cid, Partner.is_active == True)).all()  # noqa: E712
           if alvo and alvo in _pr_norm(p.name)]
    if len(pas) != 1:
        return {"ok": False, "erro": "Parceiro não encontrado ou ambíguo: use o nome exato de ri_parceiros.",
                "candidatos": [p.name for p in pas][:8]}
    pa = pas[0]
    if "@" not in (pa.contact_email or ""):
        return {"ok": False, "erro": f"{pa.name} não tem e-mail de contato no cadastro de parceiros. Peça para cadastrar."}
    if not (assunto or "").strip() or len((corpo or "").strip()) < 40:
        return {"ok": False, "erro": "Assunto e corpo do e-mail são obrigatórios."}
    anexos = []
    for aid in anexo_ids or []:
        a = s.get(PredioAnexo, int(aid))
        if not a or a.company_id != cid or a.conteudo is None:
            return {"ok": False, "erro": f"Arquivo {aid} não encontrado."}
        anexos.append({"id": a.id, "nome": a.nome})
    acao = _pr_registrar_proposta(
        s, cid, tipo="email_parceiro", titulo=f"E-mail para {pa.name}",
        destinatario=pa.contact_email.strip(), assunto=assunto.strip()[:200], corpo=corpo.strip()[:20000],
        payload_json=_json_pr.dumps({"anexos": anexos, "parceiro_id": pa.id}, ensure_ascii=False))
    return {"ok": True, "proposta_id": acao.id, "status": "aguardando aprovação de um admin",
            "observacao": f"Vai para {pa.contact_email} (cadastro do parceiro) com {len(anexos)} arquivo(s). Nada foi enviado."}


_PR_EXECUTORES_EXTRA["email_parceiro"] = _mk_exec_email_agencia  # mesmo envio: e-mail com anexos gerados no chamado


# ── Registro ──────────────────────────────────────────────────────────────────

_CR_S = {"type": "string"}
_CR_FERRAMENTAS = {
    "cred_simular": {
        "fn": _cr_t_simular, "rotulo": "Simulou as estruturas de dívida",
        "description": "Compara até 6 estruturas de dívida (pré, CDI+ ou IPCA+; PRICE, SAC ou bullet; carência; custos "
                       "iniciais e recorrentes): taxa efetiva, CET, líquido recebido, parcelas, total pago e DSCR mínimo. "
                       "Use sempre para os números: nunca calcule de cabeça.",
        "props": _CR_PROPS_SIM},
    "cred_scr": {
        "fn": _cr_t_scr, "rotulo": "Consultou o SCR do cliente",
        "description": "Consultas SCR (Banco Central) já feitas para o cliente: carteira, a vencer, vencido, prejuízo, "
                       "instituições, operações e score. Não dispara consulta nova.",
        "props": {"cliente": _CR_S}},
    "cred_dossies": {
        "fn": _cr_t_dossies, "rotulo": "Leu os dossiês do ConstruRisk",
        "description": "Dossiês do ConstruRisk já feitos para o cliente e sócios, com o parecer de crédito e PLD.",
        "props": {"cliente": _CR_S}},
    "cred_produtos_parceiros": {
        "fn": _cr_t_produtos, "rotulo": "Cruzou com os produtos dos parceiros",
        "description": "Produtos de crédito dos parceiros cadastrados (bancos, securitizadoras, fundos) com taxa, prazo, "
                       "LTV, garantia e se atendem ao valor, faturamento e prazo da operação.",
        "props": {"valor": {"type": "number"}, "faturamento_anual": {"type": "number"}, "prazo_meses": {"type": "integer"},
                  "area": {"type": "string", "description": "Filtro por palavra (ex.: CRI, capital de giro, imobiliário) ou vazio."}}},
    "cred_gerar_book": {
        "fn": _cr_t_gerar_book, "rotulo": "Gerou o book de crédito",
        "description": "Gera o book de crédito em PDF (resumo, uso dos recursos, empresa, indicadores, estruturas comparadas "
                       "com a simulação, recomendação, garantias, riscos e mitigantes).",
        "props": {"empresa": {"type": "string", "description": "Nome da empresa (ou codinome, se for sigiloso)."},
                  "operacao": {"type": "string", "description": "Ex.: CRI de R$ 30 mi para obra residencial."},
                  "resumo": _CR_S, "uso_recursos": _CR_S, "empresa_descricao": _CR_S,
                  "indicadores": {"type": "array", "items": {"type": "object", "additionalProperties": False,
                                                             "required": ["indicador", "valor", "comentario"],
                                                             "properties": {"indicador": _CR_S, "valor": _CR_S, "comentario": _CR_S}}},
                  "simulacao": {"type": "object", "description": "Os mesmos dados de cred_simular.", "additionalProperties": False,
                                "required": list(_CR_PROPS_SIM), "properties": _CR_PROPS_SIM},
                  "recomendacao": _CR_S, "garantias": {"type": "array", "items": _CR_S},
                  "riscos": {"type": "array", "items": {"type": "object", "additionalProperties": False,
                                                        "required": ["risco", "mitigante"],
                                                        "properties": {"risco": _CR_S, "mitigante": _CR_S}}}}},
    "ri_parceiros": {
        "fn": _cr_t_parceiros, "rotulo": "Listou os parceiros",
        "description": "Parceiros cadastrados (bancos, securitizadoras, fundos, assessorias) com contato e produtos ativos.",
        "props": {"tipo": {"type": "string", "description": "Tipo do parceiro (ex.: financeiro) ou vazio para todos."}}},
    "ri_operacoes": {
        "fn": _cr_t_operacoes, "rotulo": "Levantou as operações de crédito em andamento",
        "description": "Negócios de captação/crédito/mercado de capitais no CRM, com etapa, valor, próximo passo e notas.",
        "props": {}},
    "ri_propor_envio": {
        "fn": _cr_t_propor_envio, "rotulo": "Propôs e-mail ao parceiro",
        "description": "Cria uma PROPOSTA de e-mail ao parceiro (para o e-mail do cadastro de parceiros), com arquivos "
                       "gerados no chamado (ex.: book de crédito). Só um admin aprova; nada é enviado agora.",
        "props": {"parceiro": {"type": "string", "description": "Nome do parceiro como em ri_parceiros."}, "assunto": _CR_S,
                  "corpo": _CR_S, "anexo_ids": {"type": "array", "items": {"type": "integer"}}}},
}

for _nome_cr, _spec_cr in _CR_FERRAMENTAS.items():
    _pr_registrar_ferramenta(_nome_cr, _spec_cr)

_CR_AGENTES = {
    "estruturador": {
        "web": True,
        "ferramentas": ["val_dados_cliente", "cli_panorama", "cred_scr", "cred_produtos_parceiros", "cred_simular",
                        "cred_gerar_book", "mkt_indicadores", "dr_documentos", "dr_ler_documento", "conh_buscar", "conh_ler",
                        "com_negocios", "com_propor_negocio"],
        "instrucoes": (
            "Você estrutura operações de crédito e mercado de capitais para médias empresas: crédito bancário (capital de "
            "giro, investimento, BNDES/repasses), CRI e CRA, debêntures, notas comerciais e FIDC.\n"
            "Método: 1) entenda a necessidade (valor, prazo, uso dos recursos) e a capacidade de pagamento — documentos "
            "do cliente, SCR (cred_scr) e cadastro; 2) veja as garantias possíveis (imóveis, recebíveis, aval, cessão "
            "fiduciária) e o que cada estrutura exige; 3) cruze com os produtos dos parceiros (cred_produtos_parceiros); "
            "4) compare 2 a 4 estruturas com cred_simular usando CDI/IPCA atuais (mkt_indicadores) e custos realistas — "
            "mercado de capitais tem custo de estruturação (tipicamente 2% a 4% do valor) e custos anuais (agente "
            "fiduciário, custódia, rating), e só compensa a partir de volumes maiores; 5) recomende a estrutura com o "
            "porquê (CET, prazo, carência, DSCR, garantias, tempo para sair); 6) quando pedido, gere o book com "
            "cred_gerar_book.\n"
            "Nunca calcule parcelas ou CET de cabeça. Taxas de parceiros são referência: diga que precisam de cotação.")},
    "analista_risco": {
        "web": True,
        "ferramentas": ["cred_scr", "cred_dossies", "val_dados_cliente", "cli_panorama", "dr_documentos", "dr_ler_documento",
                        "cred_simular", "conh_buscar", "conh_ler", "conh_propor_registro"],
        "instrucoes": (
            "Você é o analista de risco de crédito do escritório. Monte o parecer do tomador:\n"
            "1) endividamento atual pelo SCR (cred_scr): carteira total, concentração em curto prazo, vencidos e prejuízo, "
            "número de instituições; 2) dossiês do ConstruRisk da empresa e dos sócios (cred_dossies): restrições, "
            "processos, PLD; 3) capacidade de pagamento: geração de caixa x serviço da dívida atual e proposto (use "
            "cred_simular para o DSCR); 4) garantias: liquidez, LTV e documentação; 5) pesquisa na web sobre a empresa e "
            "os sócios (notícias, processos relevantes, recuperação judicial).\n"
            "Conclua com rating interno (A a E, com critério), limite sugerido, covenants recomendados (dívida líquida/"
            "EBITDA, DSCR mínimo, garantias) e pontos que impedem a operação. Se faltar SCR ou dossiê, diga exatamente qual "
            "consulta pedir (são pagas e exigem autorização). Ao final, proponha registrar o parecer na base com "
            "conh_propor_registro vinculado ao cliente só se ele puder ver; caso contrário, interno.")},
    "relacao_investidores": {
        "web": True,
        "ferramentas": ["ri_parceiros", "ri_operacoes", "cred_produtos_parceiros", "com_negocios", "conh_buscar", "conh_ler",
                        "ri_propor_envio", "ops_propor_tarefa"],
        "instrucoes": (
            "Você cuida da relação com bancos, securitizadoras, fundos e investidores em cada operação.\n"
            "- Para uma operação: indique os parceiros com maior aderência (produtos, ticket, apetite pelo setor), o que "
            "cada um costuma pedir e a ordem de abordagem; pesquise na web securitizadoras/fundos ativos no tipo de "
            "operação quando o cadastro for insuficiente (sem fazer contato).\n"
            "- Acompanhamento: liste as operações em andamento (ri_operacoes), onde cada uma está, o próximo passo e o "
            "que está atrasado; proponha tarefas para quem cuida.\n"
            "- Envio: proponha o e-mail ao parceiro com o book anexado (ri_propor_envio). Só vai depois de um admin "
            "aprovar, para o e-mail do cadastro. Nunca inclua dados do cliente sem o book/NDA combinados.")},
}

for _key_cr, _cfg_cr in _CR_AGENTES.items():
    _ag_cr = _PREDIO_AGENTES.get(_key_cr)
    if not _ag_cr:
        continue
    _ag_cr.update(ferramentas=list(_cfg_cr["ferramentas"]), web=_cfg_cr["web"], ativo=True)
    _PR_INSTRUCOES[_key_cr] = _cfg_cr["instrucoes"]

print("[predio_credito] Andar de Crédito e Mercado de Capitais carregado.")

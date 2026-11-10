# ============================================================================
# ui_predio_financeiro.py — 9º andar do prédio: Contas a Pagar e conciliação
# ============================================================================
# Exec'd no namespace do app.py, DEPOIS de ui_predio.py e dos demais módulos do
# prédio (usa _pr_*, _cm_brl, _cm_digitos).
#
# AGENTE contas_pagar (só admin)
#   - agenda de pagamentos: vencidas, próximos dias, por fornecedor/categoria
#   - lança contas a pagar a partir de boletos/notas anexados (com aprovação),
#     avisando de possível duplicidade
#   - baixa de pagamentos e conciliação do extrato importado com os lançamentos
#     (com aprovação)
# ============================================================================


def _fi_nomes(s, cid, modelo, campo="name", **filtro):
    M = globals().get(modelo)
    if M is None:
        return {}
    q = _sel_pr(M).where(M.company_id == cid)
    for k, v in filtro.items():
        q = q.where(getattr(M, k) == v)
    return {x.id: getattr(x, campo) for x in s.exec(q).all()}


def _fi_t_agenda(s, cid, dias):
    E = OfficeFinancialEntry
    hoje = _pr_hoje()
    dias = max(1, min(int(dias or 30), 120))
    forn = _fi_nomes(s, cid, "OfficeSupplier")
    cats = _fi_nomes(s, cid, "OfficeCategory")
    vencidas, proximas, por_forn, por_cat, sem_venc = [], [], {}, {}, 0
    for e in s.exec(_sel_pr(E).where(E.company_id == cid, E.entry_kind == "pagar", E.status == "aberto")).all():
        d = _pr_data(e.due_date)
        item = {"lancamento_id": e.id, "descricao": e.description, "fornecedor": forn.get(e.supplier_id, ""),
                "categoria": cats.get(e.category_id, ""), "vencimento": _pr_fmt_data(d) if d else "",
                "valor": round(e.amount_expected_brl or 0, 2), "documento": e.document_number}
        if not d:
            sem_venc += 1
            continue
        if d < hoje:
            item["dias_atraso"] = (hoje - d).days
            vencidas.append(item)
        elif d <= hoje + _td_pr(days=dias):
            proximas.append(item)
        else:
            continue
        chave_f, chave_c = item["fornecedor"] or "(sem fornecedor)", item["categoria"] or "(sem categoria)"
        por_forn[chave_f] = por_forn.get(chave_f, 0) + item["valor"]
        por_cat[chave_c] = por_cat.get(chave_c, 0) + item["valor"]
    vencidas.sort(key=lambda x: -x["dias_atraso"])
    proximas.sort(key=lambda x: _pr_data(x["vencimento"]))
    semanas = {}
    for p in proximas:
        d = _pr_data(p["vencimento"])
        ini = d - _td_pr(days=d.weekday())
        k = _pr_fmt_data(ini)
        semanas[k] = round(semanas.get(k, 0) + p["valor"], 2)
    return {"vencidas": vencidas[:40], "total_vencido": round(sum(x["valor"] for x in vencidas), 2),
            "proximos_dias": dias, "a_vencer": proximas[:60], "total_a_vencer": round(sum(x["valor"] for x in proximas), 2),
            "por_semana": [{"semana_de": k, "valor": v} for k, v in semanas.items()],
            "maiores_fornecedores": sorted(({"fornecedor": k, "valor": round(v, 2)} for k, v in por_forn.items()),
                                           key=lambda x: -x["valor"])[:10],
            "por_categoria": sorted(({"categoria": k, "valor": round(v, 2)} for k, v in por_cat.items()),
                                    key=lambda x: -x["valor"])[:12],
            "abertas_sem_vencimento": sem_venc}


def _fi_t_cadastros(s, cid):
    return {"fornecedores": sorted(_fi_nomes(s, cid, "OfficeSupplier").values()),
            "categorias_despesa": sorted(_fi_nomes(s, cid, "OfficeCategory", category_kind="despesa").values()),
            "centros_de_custo": sorted(_fi_nomes(s, cid, "OfficeCostCenter").values()),
            "contas_bancarias": sorted(_fi_nomes(s, cid, "OfficeBankAccount").values())}


def _fi_resolver(s, cid, modelo, nome, **filtro):
    if not (nome or "").strip():
        return None, ""
    alvo = _pr_norm(nome)
    nomes = _fi_nomes(s, cid, modelo, **filtro)
    exatos = [i for i, n in nomes.items() if _pr_norm(n) == alvo]
    if exatos:
        return exatos[0], nomes[exatos[0]]
    parciais = [i for i, n in nomes.items() if alvo in _pr_norm(n)]
    return (parciais[0], nomes[parciais[0]]) if len(parciais) == 1 else (None, "")


def _fi_t_propor_lancamento(s, cid, descricao, fornecedor, documento_fornecedor, categoria, centro_custo, vencimento,
                            competencia, valor, documento, observacao):
    d = _pr_data(vencimento)
    if not d or float(valor or 0) <= 0 or len((descricao or "").strip()) < 3:
        return {"ok": False, "erro": "Informe descrição, vencimento (DD/MM/AAAA) e valor maior que zero."}
    forn_id, forn_nome = _fi_resolver(s, cid, "OfficeSupplier", fornecedor)
    cat_id, cat_nome = _fi_resolver(s, cid, "OfficeCategory", categoria, category_kind="despesa")
    cc_id, cc_nome = _fi_resolver(s, cid, "OfficeCostCenter", centro_custo)
    E = OfficeFinancialEntry
    valor = round(float(valor), 2)
    duplicados = []
    for e in s.exec(_sel_pr(E).where(E.company_id == cid, E.entry_kind == "pagar", E.status != "cancelado")).all():
        mesmo_doc = (documento or "").strip() and (e.document_number or "").strip() == documento.strip()
        mesmo_valor_data = abs((e.amount_expected_brl or 0) - valor) < 0.01 and e.due_date == d.isoformat() and \
            (not forn_id or e.supplier_id == forn_id)
        if mesmo_doc or mesmo_valor_data:
            duplicados.append({"lancamento_id": e.id, "descricao": e.description, "vencimento": _pr_fmt_data(_pr_data(e.due_date)),
                               "valor": e.amount_expected_brl, "status": e.status})
    payload = {"descricao": descricao.strip()[:200], "fornecedor_id": forn_id,
               "fornecedor_novo": "" if forn_id else (fornecedor or "").strip()[:120],
               "fornecedor_documento": _cm_digitos(documento_fornecedor), "categoria_id": cat_id, "centro_custo_id": cc_id,
               "vencimento": d.isoformat(), "competencia": (_pr_data(competencia) or d).isoformat(), "valor": valor,
               "documento": (documento or "").strip()[:80], "observacao": (observacao or "").strip()[:500]}
    aviso = ""
    if duplicados:
        aviso = "\n\n⚠ Possível duplicidade com: " + "; ".join(f"#{x['lancamento_id']} {x['descricao']} ({x['status']})" for x in duplicados[:3])
    acao = _pr_registrar_proposta(
        s, cid, tipo="lancar_conta_pagar", titulo=f"Lançar conta a pagar: {payload['descricao']} — {_cm_brl(valor)}",
        destinatario=f"Financeiro do escritório · vence em {_pr_fmt_data(d)}", assunto=payload["descricao"],
        corpo=(f"Fornecedor: {forn_nome or (payload['fornecedor_novo'] + ' (novo cadastro)' if payload['fornecedor_novo'] else '—')}\n"
               f"Categoria: {cat_nome or '—'} · Centro de custo: {cc_nome or '—'}\nValor: {_cm_brl(valor)} · Documento: "
               f"{payload['documento'] or '—'}" + aviso),
        payload_json=_json_pr.dumps(payload, ensure_ascii=False))
    return {"ok": True, "proposta_id": acao.id, "possivel_duplicidade": duplicados[:3],
            "categoria_reconhecida": cat_nome or None, "fornecedor_reconhecido": forn_nome or None,
            "observacao": "Nada foi lançado. " + ("Avise o sócio da possível duplicidade." if duplicados else "")}


def _fi_exec_lancar(s, acao) -> str:
    p = _json_pr.loads(acao.payload_json or "{}")
    forn_id = p.get("fornecedor_id")
    criado = ""
    if not forn_id and p.get("fornecedor_novo"):
        F = globals().get("OfficeSupplier")
        existente = s.exec(_sel_pr(F).where(F.company_id == acao.company_id, F.name == p["fornecedor_novo"])).first()
        if existente:
            forn_id = existente.id
        else:
            f = F(company_id=acao.company_id, name=p["fornecedor_novo"], document=p.get("fornecedor_documento", ""))
            s.add(f)
            s.commit()
            s.refresh(f)
            forn_id, criado = f.id, f" Fornecedor '{f.name}' cadastrado."
    e = OfficeFinancialEntry(company_id=acao.company_id, created_by_user_id=acao.decidido_por_user_id or 0, entry_kind="pagar",
                             status="aberto", supplier_id=forn_id, category_id=p.get("categoria_id"),
                             cost_center_id=p.get("centro_custo_id"), description=p["descricao"], document_number=p.get("documento", ""),
                             competence_date=p.get("competencia", ""), due_date=p["vencimento"], amount_expected_brl=p["valor"],
                             notes=p.get("observacao", ""))
    s.add(e)
    s.commit()
    s.refresh(e)
    return f"Conta a pagar #{e.id} lançada, vence em {_pr_fmt_data(_pr_data(e.due_date))}." + criado


def _fi_t_propor_baixa(s, cid, lancamento_id, data_pagamento, valor_pago, conta_bancaria):
    e = s.get(OfficeFinancialEntry, int(lancamento_id or 0))
    if not e or e.company_id != cid or e.entry_kind != "pagar":
        return {"ok": False, "erro": "Conta a pagar não encontrada (use o lancamento_id da agenda)."}
    if e.status != "aberto":
        return {"ok": False, "erro": f"Essa conta já está '{e.status}'."}
    d = _pr_data(data_pagamento)
    if not d or d > _pr_hoje():
        return {"ok": False, "erro": "Data de pagamento inválida ou no futuro."}
    conta_id, conta_nome = _fi_resolver(s, cid, "OfficeBankAccount", conta_bancaria)
    valor = round(float(valor_pago or e.amount_expected_brl or 0), 2)
    acao = _pr_registrar_proposta(
        s, cid, tipo="baixar_conta_pagar", titulo=f"Baixar pagamento: {e.description} — {_cm_brl(valor)}",
        destinatario=f"Financeiro do escritório · lançamento #{e.id}", assunto=e.description,
        corpo=f"Pago em {_pr_fmt_data(d)} · {_cm_brl(valor)}" + (f" · conta {conta_nome}" if conta_nome else "")
              + (f"\nValor diferente do previsto ({_cm_brl(e.amount_expected_brl)})." if abs(valor - (e.amount_expected_brl or 0)) >= 0.01 else ""),
        payload_json=_json_pr.dumps({"lancamento_id": e.id, "data": d.isoformat(), "valor": valor, "conta_id": conta_id}))
    return {"ok": True, "proposta_id": acao.id, "status": "aguardando aprovação"}


def _fi_exec_baixar(s, acao) -> str:
    p = _json_pr.loads(acao.payload_json or "{}")
    e = s.get(OfficeFinancialEntry, int(p.get("lancamento_id") or 0))
    if not e or e.company_id != acao.company_id:
        raise _PrErro("Lançamento não encontrado.")
    if e.status != "aberto":
        raise _PrErro(f"O lançamento já está '{e.status}'.")
    e.status, e.settlement_date, e.amount_realized_brl = "pago", p["data"], p["valor"]
    if p.get("conta_id"):
        e.bank_account_id = p["conta_id"]
    e.updated_by_user_id, e.updated_at = acao.decidido_por_user_id, _dt_pr.utcnow()
    s.add(e)
    s.commit()
    return f"Pagamento #{e.id} baixado em {_pr_fmt_data(_pr_data(p['data']))}."


# ── Conciliação do extrato ────────────────────────────────────────────────────

def _fi_sugestao(s, cid, linha):
    E = OfficeFinancialEntry
    valor = abs(linha.amount_cents) / 100
    tipo = "receber" if linha.amount_cents > 0 else "pagar"
    d = _pr_data(linha.release_date)
    if not d:
        return []
    cands = s.exec(_sel_pr(E).where(E.company_id == cid, E.entry_kind == tipo, E.status == "aberto",
                                   E.due_date >= (d - _td_pr(days=7)).isoformat(),
                                   E.due_date <= (d + _td_pr(days=7)).isoformat())).all()
    out = [{"lancamento_id": e.id, "descricao": e.description, "vencimento": _pr_fmt_data(_pr_data(e.due_date)),
            "valor": e.amount_expected_brl, "diferenca_dias": abs((_pr_data(e.due_date) - d).days)}
           for e in cands if abs((e.amount_expected_brl or 0) - valor) < 0.02]
    return sorted(out, key=lambda x: x["diferenca_dias"])


def _fi_t_conciliacao(s, cid):
    L = globals().get("BankStatementLine")
    if L is None:
        return {"erro": "Conciliação indisponível."}
    linhas = s.exec(_sel_pr(L).where(L.company_id == cid, L.status == "pendente").order_by(L.release_date).limit(80)).all()
    out = []
    for l in linhas:
        sug = _fi_sugestao(s, cid, l)
        out.append({"linha_id": l.id, "data": _pr_fmt_data(_pr_data(l.release_date)) if _pr_data(l.release_date) else l.release_date,
                    "historico": l.transaction_type, "referencia": l.reference_id, "valor": l.amount_cents / 100,
                    "sugestoes": sug[:3], "sugestao_unica": len(sug) == 1})
    total = s.exec(_sel_pr(_func_pr.count(L.id)).where(L.company_id == cid, L.status == "pendente")).one()
    return {"linhas_pendentes": total, "linhas": out,
            "observacao": "Sugestões: lançamentos em aberto do mesmo tipo, mesmo valor e vencimento até 7 dias da data do "
                          "extrato. Débito = pagar, crédito = receber."}


def _fi_t_propor_conciliacao(s, cid, pares):
    L = globals().get("BankStatementLine")
    validos, recusados = [], []
    for p in (pares or [])[:60]:
        l = s.get(L, int((p or {}).get("linha_id") or 0)) if L is not None else None
        e = s.get(OfficeFinancialEntry, int((p or {}).get("lancamento_id") or 0))
        ok = (l and e and l.company_id == cid and e.company_id == cid and l.status == "pendente" and e.status == "aberto"
              and e.entry_kind == ("receber" if l.amount_cents > 0 else "pagar")
              and abs((e.amount_expected_brl or 0) - abs(l.amount_cents) / 100) < 0.02)
        (validos if ok else recusados).append({"linha_id": p.get("linha_id"), "lancamento_id": p.get("lancamento_id")})
    if not validos:
        return {"ok": False, "erro": "Nenhum par válido (mesmo tipo, mesmo valor, linha pendente e lançamento em aberto).",
                "recusados": recusados}
    acao = _pr_registrar_proposta(
        s, cid, tipo="conciliar_extrato", titulo=f"Conciliar {len(validos)} linha(s) do extrato",
        destinatario="Financeiro do escritório · lançamentos viram pagos/recebidos na data do extrato",
        assunto="Conciliação do extrato", corpo="\n".join(f"• linha #{v['linha_id']} ↔ lançamento #{v['lancamento_id']}" for v in validos),
        payload_json=_json_pr.dumps({"pares": validos}))
    return {"ok": True, "proposta_id": acao.id, "pares": len(validos), "recusados": recusados}


def _fi_exec_conciliar(s, acao) -> str:
    L = globals().get("BankStatementLine")
    n = 0
    for p in _json_pr.loads(acao.payload_json or "{}").get("pares") or []:
        l, e = s.get(L, p["linha_id"]), s.get(OfficeFinancialEntry, p["lancamento_id"])
        if not l or not e or l.status != "pendente" or e.status != "aberto" or l.company_id != acao.company_id \
                or e.company_id != acao.company_id:
            continue
        e.amount_realized_brl = abs(l.amount_cents) / 100
        e.settlement_date = l.release_date
        e.status = "recebido" if e.entry_kind == "receber" else "pago"
        l.matched_entry_id, l.status = e.id, "conciliado"
        s.add(e)
        s.add(l)
        n += 1
    s.commit()
    return f"{n} linha(s) conciliada(s)."


# ── Registro ──────────────────────────────────────────────────────────────────

_FI_S = {"type": "string"}
_FI_FERRAMENTAS = {
    "cp_agenda": {
        "fn": _fi_t_agenda, "rotulo": "Montou a agenda de pagamentos",
        "description": "Contas a pagar do escritório em aberto: vencidas (com dias de atraso), a vencer nos próximos dias "
                       "(por semana), maiores fornecedores e categorias. Cada item traz o lancamento_id.",
        "props": {"dias": {"type": "integer", "description": "Janela à frente em dias (1 a 120)."}}},
    "cp_cadastros": {
        "fn": _fi_t_cadastros, "rotulo": "Consultou fornecedores e categorias",
        "description": "Fornecedores, categorias de despesa, centros de custo e contas bancárias cadastrados (use os nomes "
                       "exatos ao propor lançamentos).",
        "props": {}},
    "cp_propor_lancamento": {
        "fn": _fi_t_propor_lancamento, "rotulo": "Propôs lançar uma conta a pagar",
        "description": "Cria uma PROPOSTA de conta a pagar (a partir de boleto/nota anexada ou do pedido). Aponta possível "
                       "duplicidade. Fornecedor não cadastrado é criado na aprovação. Só um admin aprova.",
        "props": {"descricao": _FI_S, "fornecedor": _FI_S,
                  "documento_fornecedor": {"type": "string", "description": "CNPJ/CPF do fornecedor ou vazio."},
                  "categoria": {"type": "string", "description": "Nome da categoria de despesa (de cp_cadastros) ou vazio."},
                  "centro_custo": {"type": "string", "description": "Nome do centro de custo ou vazio."},
                  "vencimento": {"type": "string", "description": "DD/MM/AAAA"},
                  "competencia": {"type": "string", "description": "DD/MM/AAAA (mês a que a despesa se refere) ou vazio."},
                  "valor": {"type": "number"}, "documento": {"type": "string", "description": "Nº da nota/boleto ou vazio."},
                  "observacao": _FI_S}},
    "cp_propor_baixa": {
        "fn": _fi_t_propor_baixa, "rotulo": "Propôs baixar um pagamento",
        "description": "Cria uma PROPOSTA de baixa de uma conta a pagar já paga (data, valor e conta bancária).",
        "props": {"lancamento_id": {"type": "integer"}, "data_pagamento": {"type": "string", "description": "DD/MM/AAAA"},
                  "valor_pago": {"type": "number", "description": "0 = valor previsto."},
                  "conta_bancaria": {"type": "string", "description": "Nome da conta (de cp_cadastros) ou vazio."}}},
    "cp_conciliacao": {
        "fn": _fi_t_conciliacao, "rotulo": "Revisou o extrato pendente de conciliação",
        "description": "Linhas do extrato importado ainda não conciliadas, com sugestões de lançamentos (mesmo valor, até 7 "
                       "dias de diferença).",
        "props": {}},
    "cp_propor_conciliacao": {
        "fn": _fi_t_propor_conciliacao, "rotulo": "Propôs conciliar o extrato",
        "description": "Cria uma PROPOSTA de conciliação: cada linha do extrato com o lançamento correspondente (que vira "
                       "pago/recebido na data do extrato). Só pares de mesmo tipo e valor.",
        "props": {"pares": {"type": "array", "items": {"type": "object", "additionalProperties": False,
                                                       "required": ["linha_id", "lancamento_id"],
                                                       "properties": {"linha_id": {"type": "integer"}, "lancamento_id": {"type": "integer"}}}}}},
}

for _nome_fi, _spec_fi in _FI_FERRAMENTAS.items():
    _pr_registrar_ferramenta(_nome_fi, _spec_fi)

_PR_EXECUTORES_EXTRA["lancar_conta_pagar"] = _fi_exec_lancar
_PR_EXECUTORES_EXTRA["baixar_conta_pagar"] = _fi_exec_baixar
_PR_EXECUTORES_EXTRA["conciliar_extrato"] = _fi_exec_conciliar

_ag_fi = _PREDIO_AGENTES.get("contas_pagar")
if _ag_fi:
    _ag_fi.update(ativo=True, web=False, papeis=_PR_ADMIN,
                  ferramentas=["cp_agenda", "cp_cadastros", "cp_propor_lancamento", "cp_propor_baixa", "cp_conciliacao",
                               "cp_propor_conciliacao", "fin_resumo_caixa", "fin_despesas_por_categoria"])
    _PR_INSTRUCOES["contas_pagar"] = (
        "Você cuida das contas a pagar do escritório e da conciliação bancária.\n"
        "- Agenda: o que está vencido (priorize multa/juros e fornecedores críticos: aluguel, folha, impostos, sistemas), o "
        "que vence nos próximos dias por semana e se o caixa previsto (fin_resumo_caixa) cobre; sugira o que pagar primeiro "
        "se faltar caixa.\n"
        "- Lançar: quando o sócio anexar boleto, nota fiscal ou fatura, leia valor, vencimento, fornecedor (com CNPJ), nº "
        "do documento e competência; escolha a categoria e o centro de custo pelos cadastros (cp_cadastros) e proponha "
        "com cp_propor_lancamento. Se houver possível duplicidade, diga claramente.\n"
        "- Baixa: quando o sócio disser que pagou, proponha a baixa com a data e a conta.\n"
        "- Conciliação: revise o extrato pendente (cp_conciliacao); proponha conciliar só os pares com sugestão única e "
        "clara; liste os que precisam de decisão humana (sem sugestão, várias sugestões, valores diferentes).\n"
        "Nunca lance, baixe ou concilie sem a proposta: tudo passa pela aprovação de um admin.")

print("[predio_financeiro] Contas a Pagar e conciliação carregados.")

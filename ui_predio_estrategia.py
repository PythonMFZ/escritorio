# ============================================================================
# ui_predio_estrategia.py — Cobertura do prédio: Estratégia
# ============================================================================
# Exec'd no namespace do app.py, DEPOIS de ui_predio.py e dos demais módulos do
# prédio (usa _pr_*, _cm_brl, rel_gerar_relatorio).
#
# AGENTE estrategia (só admin)
#   - KPIs do escritório calculados mês a mês a partir dos dados (receita, despesas,
#     resultado de caixa, MRR de contratos, clientes ativos, negócios ganhos/perdidos,
#     pipeline, inadimplência, concentração, horas e receita por hora)
#   - BSC interno do escritório (plano da ferramenta BSC sem cliente vinculado)
#   - propõe metas no BSC, lançamento mensal dos valores calculados e ações
#     estratégicas — tudo com aprovação
# ============================================================================


def _es_mes_ini_fim(ano: int, mes: int):
    from datetime import date as _d
    ini = _d(ano, mes, 1)
    fim = (_d(ano + (mes == 12), mes % 12 + 1, 1)) - _td_pr(days=1)
    return ini, fim


def _es_meses(n: int) -> list:
    hoje = _pr_hoje()
    out, a, m = [], hoje.year, hoje.month
    for _ in range(n):
        out.append((a, m))
        m -= 1
        if m == 0:
            a, m = a - 1, 12
    return list(reversed(out))


def _es_kpis(s, cid, meses: int) -> dict:
    E = OfficeFinancialEntry
    hoje = _pr_hoje()
    lista = _es_meses(max(1, min(int(meses or 6), 24)))
    ini_total = _es_mes_ini_fim(*lista[0])[0]
    receb, pago = {}, {}
    for e in s.exec(_sel_pr(E).where(E.company_id == cid, E.status != "cancelado")).all():
        quando = _pr_data_realizacao(e)
        valor = float(e.amount_realized_brl or 0)
        if not quando or valor <= 0 or quando < ini_total:
            continue
        k = (quando.year, quando.month)
        alvo = receb if e.entry_kind == "receber" else pago
        alvo[k] = alvo.get(k, 0.0) + valor
    CC = globals().get("ContratoCliente")
    contratos = s.exec(_sel_pr(CC).where(CC.company_id == cid)).all() if CC is not None else []
    deals = s.exec(_sel_pr(BusinessDeal.stage, BusinessDeal.updated_at, BusinessDeal.value_estimate_brl)
                   .where(BusinessDeal.company_id == cid, BusinessDeal.stage.in_(["ganho", "perdido"]))).all()
    TWS = globals().get("TaskWorkSession")
    horas = {}
    if TWS is not None:
        for ini, fim in s.exec(_sel_pr(TWS.started_at, TWS.ended_at).where(TWS.company_id == cid,
                                                                          TWS.started_at >= _dt_pr.combine(ini_total, _dt_pr.min.time()))).all():
            if ini and fim and fim > ini:
                k = (ini.year, ini.month)
                horas[k] = horas.get(k, 0.0) + (fim - ini).total_seconds() / 3600
    linhas = []
    for a, m in lista:
        ini, fim = _es_mes_ini_fim(a, m)
        ativos = [c for c in contratos if _pr_data(c.data_inicio) and _pr_data(c.data_inicio) <= fim
                  and (not _pr_data(c.data_fim) or _pr_data(c.data_fim) >= fim) and c.status != "cancelado"]
        ganhos = [d for d in deals if d[0] == "ganho" and d[1] and ini <= d[1].date() <= fim]
        perdidos = [d for d in deals if d[0] == "perdido" and d[1] and ini <= d[1].date() <= fim]
        r, p, h = receb.get((a, m), 0.0), pago.get((a, m), 0.0), horas.get((a, m), 0.0)
        linhas.append({"mes": f"{m:02d}/{a}", "receita_recebida": round(r, 2), "despesas_pagas": round(p, 2),
                       "resultado_caixa": round(r - p, 2), "margem_caixa_pct": round((r - p) / r * 100, 1) if r else None,
                       "mrr_contratos": round(sum(c.valor_cents for c in ativos) / 100, 2),
                       "clientes_com_contrato": len({c.client_id for c in ativos}),
                       "negocios_ganhos": len(ganhos), "valor_ganho": round(sum(d[2] or 0 for d in ganhos), 2),
                       "negocios_perdidos": len(perdidos), "horas_trabalhadas": round(h, 1),
                       "receita_por_hora": round(r / h, 2) if h else None, "parcial": (a, m) == (hoje.year, hoje.month)})
    # retrato atual
    abertos = s.exec(_sel_pr(E).where(E.company_id == cid, E.entry_kind == "receber", E.status == "aberto")).all()
    vencido = sum(float(e.amount_expected_brl or 0) for e in abertos if _pr_data(e.due_date) and _pr_data(e.due_date) < hoje)
    a_receber = sum(float(e.amount_expected_brl or 0) for e in abertos)
    por_cli, _ = _pr_recebido_por_cliente(s, cid, hoje - _td_pr(days=365), hoje)
    total12 = sum(por_cli.values())
    nomes = _pr_clientes(s, cid)
    top = sorted(por_cli.items(), key=lambda x: -x[1])[:3]
    pipe = _pr_t_pipeline(s, cid)
    return {"meses": linhas, "atual": {
        "inadimplencia_pct_do_a_receber": round(vencido / a_receber * 100, 1) if a_receber else 0.0,
        "vencido": round(vencido, 2), "a_receber_em_aberto": round(a_receber, 2),
        "receita_12m": round(total12, 2),
        "concentracao_top3_pct": [{"cliente": nomes.get(k, ""), "pct": round(v / total12 * 100, 1)} for k, v in top] if total12 else [],
        "pipeline_valor": pipe["valor_total"], "pipeline_ponderado": pipe["valor_ponderado"],
        "negocios_em_aberto": pipe["em_aberto"]},
        "observacao": "Receita/despesa pelo regime de caixa (data de realização). O mês corrente é parcial."}


def _es_t_kpis(s, cid, meses):
    return _es_kpis(s, cid, meses)


# ── BSC interno do escritório ─────────────────────────────────────────────────

_ES_PERSPECTIVAS = ["financeira", "clientes", "processos", "aprendizado"]


def _es_plano(s, cid, ano):
    P = globals().get("BSCPlan")
    if P is None:
        return None
    return s.exec(_sel_pr(P).where(P.company_id == cid, P.client_id == None, P.year == ano)  # noqa: E711
                  .order_by(P.is_active.desc(), P.id.desc())).first()


def _es_t_bsc(s, cid, ano):
    O, I, V, A = (globals().get(n) for n in ("BSCObjective", "BSCIndicator", "BSCIndicatorValue", "BSCAction"))
    if O is None:
        return {"erro": "Ferramenta BSC indisponível."}
    ano = int(ano or _pr_hoje().year)
    plano = _es_plano(s, cid, ano)
    if not plano:
        return {"ano": ano, "plano": None, "observacao": "O escritório ainda não tem BSC interno para este ano: proponha as metas."}
    objs = []
    for o in s.exec(_sel_pr(O).where(O.plan_id == plano.id, O.is_active == True).order_by(O.perspective, O.sort_order)).all():  # noqa: E712
        inds = []
        for ind in s.exec(_sel_pr(I).where(I.objective_id == o.id, I.is_active == True)).all():  # noqa: E712
            vals = s.exec(_sel_pr(V.month, V.value).where(V.indicator_id == ind.id, V.year == ano).order_by(V.month)).all()
            ultimo = vals[-1][1] if vals else None
            atingido = None
            if ultimo is not None and ind.target_value:
                atingido = ultimo >= ind.target_value if ind.direction == "maior" else ultimo <= ind.target_value
            inds.append({"indicador_id": ind.id, "indicador": ind.name, "unidade": ind.unit, "meta": ind.target_value,
                         "sentido": ind.direction, "base": ind.baseline_value,
                         "valores": [{"mes": m, "valor": v} for m, v in vals], "ultimo": ultimo,
                         "semaforo": None if atingido is None else ("verde" if atingido else "vermelho")})
        acoes = [{"acao": a.title, "responsavel": a.responsible, "prazo": a.due_date, "status": a.status, "progresso": a.progress}
                 for a in s.exec(_sel_pr(A).where(A.objective_id == o.id, A.is_active == True,  # noqa: E712
                                                  A.status != "concluida")).all()] if A is not None else []
        objs.append({"objetivo_id": o.id, "perspectiva": o.perspective, "objetivo": o.title, "dono": o.owner,
                     "indicadores": inds, "acoes_abertas": acoes})
    return {"ano": ano, "plano": plano.name, "objetivos": objs}


def _es_t_propor_meta(s, cid, ano, perspectiva, objetivo, indicador, unidade, meta, sentido, base, dono):
    if perspectiva not in _ES_PERSPECTIVAS or len((objetivo or "").strip()) < 3 or len((indicador or "").strip()) < 3:
        return {"ok": False, "erro": "Informe perspectiva, objetivo e indicador."}
    ano = int(ano or _pr_hoje().year)
    payload = {"ano": ano, "perspectiva": perspectiva, "objetivo": objetivo.strip()[:200], "indicador": indicador.strip()[:200],
               "unidade": (unidade or "").strip()[:20], "meta": float(meta or 0), "sentido": "menor" if sentido == "menor" else "maior",
               "base": float(base or 0), "dono": (dono or "").strip()[:80]}
    acao = _pr_registrar_proposta(
        s, cid, tipo="criar_meta_bsc", titulo=f"Meta no BSC do escritório: {payload['indicador']}",
        destinatario=f"BSC interno {ano} · perspectiva {perspectiva}", assunto=payload["indicador"],
        corpo=(f"Objetivo: {payload['objetivo']}\nIndicador: {payload['indicador']} ({payload['unidade']})\n"
               f"Meta: {payload['meta']:g} ({'quanto maior, melhor' if payload['sentido'] == 'maior' else 'quanto menor, melhor'}) · "
               f"base {payload['base']:g}\nDono: {payload['dono'] or '—'}"),
        payload_json=_json_pr.dumps(payload, ensure_ascii=False))
    return {"ok": True, "proposta_id": acao.id, "status": "aguardando aprovação"}


def _es_exec_meta(s, acao) -> str:
    P, O, I = globals()["BSCPlan"], globals()["BSCObjective"], globals()["BSCIndicator"]
    p = _json_pr.loads(acao.payload_json or "{}")
    plano = _es_plano(s, acao.company_id, p["ano"])
    if not plano:
        plano = P(company_id=acao.company_id, client_id=None, name=f"Planejamento Estratégico {p['ano']}", year=p["ano"])
        s.add(plano)
        s.commit()
        s.refresh(plano)
    obj = s.exec(_sel_pr(O).where(O.plan_id == plano.id, O.title == p["objetivo"])).first()
    if not obj:
        obj = O(company_id=acao.company_id, plan_id=plano.id, perspective=p["perspectiva"], title=p["objetivo"], owner=p["dono"])
        s.add(obj)
        s.commit()
        s.refresh(obj)
    ind = I(company_id=acao.company_id, objective_id=obj.id, name=p["indicador"], unit=p["unidade"], target_value=p["meta"],
            baseline_value=p["base"], direction=p["sentido"], aggregation="ultimo")
    s.add(ind)
    s.commit()
    s.refresh(ind)
    return f"Indicador #{ind.id} criado no objetivo '{obj.title}' do BSC {p['ano']}."


def _es_t_propor_valores(s, cid, ano, mes, valores):
    I = globals().get("BSCIndicator")
    plano = _es_plano(s, cid, int(ano or 0))
    if I is None or not plano:
        return {"ok": False, "erro": "Sem BSC interno para esse ano."}
    mes = int(mes or 0)
    if not 1 <= mes <= 12:
        return {"ok": False, "erro": "Mês entre 1 e 12."}
    ids_plano = {i.id: i.name for i in s.exec(_sel_pr(I).join(globals()["BSCObjective"], globals()["BSCObjective"].id == I.objective_id)
                                               .where(globals()["BSCObjective"].plan_id == plano.id)).all()}
    validos = [{"indicador_id": int(v["indicador_id"]), "valor": float(v["valor"]), "nota": str(v.get("nota", ""))[:200]}
               for v in (valores or []) if isinstance(v, dict) and int(v.get("indicador_id") or 0) in ids_plano]
    if not validos:
        return {"ok": False, "erro": "Nenhum indicador válido do BSC interno (use indicador_id de est_bsc)."}
    acao = _pr_registrar_proposta(
        s, cid, tipo="lancar_valores_bsc", titulo=f"Lançar {len(validos)} valor(es) no BSC — {mes:02d}/{ano}",
        destinatario=f"BSC interno {ano}", assunto=f"Valores de {mes:02d}/{ano}",
        corpo="\n".join(f"• {ids_plano[v['indicador_id']]}: {v['valor']:g}" + (f" ({v['nota']})" if v["nota"] else "") for v in validos),
        payload_json=_json_pr.dumps({"ano": int(ano), "mes": mes, "valores": validos}, ensure_ascii=False))
    return {"ok": True, "proposta_id": acao.id, "valores": len(validos)}


def _es_exec_valores(s, acao) -> str:
    V = globals()["BSCIndicatorValue"]
    p = _json_pr.loads(acao.payload_json or "{}")
    for v in p["valores"]:
        reg = s.exec(_sel_pr(V).where(V.indicator_id == v["indicador_id"], V.year == p["ano"], V.month == p["mes"])).first()
        if reg:
            reg.value, reg.note, reg.updated_at = v["valor"], v["nota"], _dt_pr.utcnow()
        else:
            reg = V(indicator_id=v["indicador_id"], company_id=acao.company_id, year=p["ano"], month=p["mes"], value=v["valor"],
                    note=v["nota"])
        s.add(reg)
    s.commit()
    return f"{len(p['valores'])} valor(es) lançado(s) no BSC de {p['mes']:02d}/{p['ano']}."


def _es_t_propor_acao(s, cid, objetivo_id, titulo, descricao, responsavel, prazo, prioridade):
    O = globals().get("BSCObjective")
    o = s.get(O, int(objetivo_id or 0)) if O is not None else None
    if not o or o.company_id != cid:
        return {"ok": False, "erro": "Objetivo não encontrado (use objetivo_id de est_bsc)."}
    if (prazo or "").strip() and not _pr_data(prazo):
        return {"ok": False, "erro": "Prazo inválido: DD/MM/AAAA."}
    payload = {"objetivo_id": o.id, "titulo": titulo.strip()[:200], "descricao": (descricao or "").strip()[:2000],
               "responsavel": (responsavel or "").strip()[:80], "prazo": _pr_fmt_data(_pr_data(prazo)) if _pr_data(prazo) else "",
               "prioridade": prioridade if prioridade in ("alta", "media", "baixa") else "media"}
    acao = _pr_registrar_proposta(
        s, cid, tipo="criar_acao_bsc", titulo=f"Ação estratégica: {payload['titulo']}", destinatario=f"BSC interno · objetivo '{o.title}'",
        assunto=payload["titulo"], corpo=f"{payload['descricao']}\nResponsável: {payload['responsavel'] or '—'} · prazo "
                                           f"{payload['prazo'] or '—'} · prioridade {payload['prioridade']}",
        payload_json=_json_pr.dumps(payload, ensure_ascii=False))
    return {"ok": True, "proposta_id": acao.id}


def _es_exec_acao(s, acao) -> str:
    A = globals()["BSCAction"]
    p = _json_pr.loads(acao.payload_json or "{}")
    a = A(company_id=acao.company_id, objective_id=p["objetivo_id"], title=p["titulo"], description=p["descricao"],
          responsible=p["responsavel"], due_date=p["prazo"], priority=p["prioridade"])
    s.add(a)
    s.commit()
    s.refresh(a)
    return f"Ação #{a.id} criada no BSC interno."


# ── Registro ──────────────────────────────────────────────────────────────────

_ES_S = {"type": "string"}
_ES_FERRAMENTAS = {
    "est_kpis": {
        "fn": _es_t_kpis, "rotulo": "Calculou os indicadores do escritório",
        "description": "KPIs do escritório mês a mês a partir dos dados: receita recebida, despesas pagas, resultado e margem "
                       "de caixa, MRR de contratos, clientes com contrato, negócios ganhos/perdidos, horas e receita por hora; e "
                       "o retrato atual: inadimplência, receita 12 meses, concentração nos 3 maiores clientes e pipeline.",
        "props": {"meses": {"type": "integer", "description": "1 a 24 (padrão 6)."}}},
    "est_bsc": {
        "fn": _es_t_bsc, "rotulo": "Consultou o BSC interno",
        "description": "BSC do próprio escritório (plano sem cliente) no ano: objetivos por perspectiva, indicadores com meta, "
                       "valores lançados e semáforo, e ações abertas.",
        "props": {"ano": {"type": "integer"}}},
    "est_propor_meta": {
        "fn": _es_t_propor_meta, "rotulo": "Propôs uma meta no BSC",
        "description": "Cria uma PROPOSTA de indicador com meta no BSC interno (cria o plano e o objetivo se não existirem).",
        "props": {"ano": {"type": "integer"}, "perspectiva": {"type": "string", "enum": _ES_PERSPECTIVAS}, "objetivo": _ES_S,
                  "indicador": _ES_S, "unidade": {"type": "string", "description": "Ex.: R$, %, nº, h."}, "meta": {"type": "number"},
                  "sentido": {"type": "string", "enum": ["maior", "menor"]}, "base": {"type": "number", "description": "Valor de partida."},
                  "dono": _ES_S}},
    "est_propor_valores": {
        "fn": _es_t_propor_valores, "rotulo": "Propôs lançar os valores do mês no BSC",
        "description": "Cria uma PROPOSTA de lançamento dos valores do mês nos indicadores do BSC interno (normalmente "
                       "calculados com est_kpis).",
        "props": {"ano": {"type": "integer"}, "mes": {"type": "integer"},
                  "valores": {"type": "array", "items": {"type": "object", "additionalProperties": False,
                                                         "required": ["indicador_id", "valor", "nota"],
                                                         "properties": {"indicador_id": {"type": "integer"}, "valor": {"type": "number"},
                                                                        "nota": _ES_S}}}}},
    "est_propor_acao": {
        "fn": _es_t_propor_acao, "rotulo": "Propôs uma ação estratégica",
        "description": "Cria uma PROPOSTA de ação no BSC interno, ligada a um objetivo.",
        "props": {"objetivo_id": {"type": "integer"}, "titulo": _ES_S, "descricao": _ES_S, "responsavel": _ES_S,
                  "prazo": {"type": "string", "description": "DD/MM/AAAA ou vazio."},
                  "prioridade": {"type": "string", "enum": ["alta", "media", "baixa"]}}},
}

for _nome_es, _spec_es in _ES_FERRAMENTAS.items():
    _pr_registrar_ferramenta(_nome_es, _spec_es)

_PR_EXECUTORES_EXTRA.update({"criar_meta_bsc": _es_exec_meta, "lancar_valores_bsc": _es_exec_valores,
                             "criar_acao_bsc": _es_exec_acao})

_ag_es = _PREDIO_AGENTES.get("estrategia")
if _ag_es:
    _ag_es.update(ativo=True, web=True, papeis=_PR_ADMIN,
                  ferramentas=["est_kpis", "est_bsc", "est_propor_meta", "est_propor_valores", "est_propor_acao",
                               "fin_receita_por_cliente", "fin_despesas_por_categoria", "fin_horas_vs_receita", "com_pipeline",
                               "cli_carteira", "conh_buscar", "conh_ler", "rel_gerar_relatorio"])
    _PR_INSTRUCOES["estrategia"] = (
        "Você é o estrategista dos sócios: olha o escritório como negócio.\n"
        "- Diagnóstico: use est_kpis (tendência de 6 a 12 meses) e explique o que está melhorando ou piorando e por quê — "
        "crescimento de receita, previsibilidade (MRR), margem de caixa, concentração em poucos clientes, inadimplência, "
        "conversão do pipeline e receita por hora (capacidade da equipe).\n"
        "- BSC interno (est_bsc): se não existir, proponha um BSC enxuto — 2 a 3 objetivos por perspectiva (financeira, "
        "clientes, processos, aprendizado), cada um com 1 indicador mensurável pelos dados, meta e dono. Metas ambiciosas "
        "mas realistas, a partir da base atual. Todo mês, proponha lançar os valores calculados (est_propor_valores) e, "
        "para indicadores no vermelho, ações concretas com responsável e prazo (est_propor_acao).\n"
        "- Mercado: quando útil, pesquise referências do mercado de consultoria/assessoria financeira na web, com fonte.\n"
        "- Entregue a conclusão primeiro e, quando pedido, o plano estratégico em Word (rel_gerar_relatorio).")

print("[predio_estrategia] Estratégia (Cobertura) carregada.")

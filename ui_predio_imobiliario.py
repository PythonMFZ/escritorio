# ============================================================================
# ui_predio_imobiliario.py — 4º andar do prédio: Imobiliário
# ============================================================================
# Exec'd no namespace do app.py, DEPOIS de ui_predio.py, das ferramentas de
# viabilidade (_calcular_viabilidade_v2), do mapa de unidades (Empreendimento,
# UnidadeEmpreendimento, VendaUnidade) e de obras (Obra, ObraFase, ObraEtapa,
# ObraApontamento, _calcular_evm).
#
# AGENTES (admin e equipe; dados do cliente, nunca do financeiro do escritório)
#   viabilidade     — lê os estudos salvos, roda o motor de viabilidade (o mesmo da
#                     ferramenta) com premissas novas e compara cenários e sensibilidade
#   produto_vendas  — mapa de unidades: estoque, vendas, preço médio x tabela, velocidade,
#                     meses de estoque e aderência ao estudo de viabilidade
#   obras           — físico x financeiro por EVM (IDC, IDP, EAC), etapas que estouram o
#                     orçamento ou atrasam, e ações corretivas (tarefas com aprovação)
# ============================================================================


def _im_cliente_ok(s, cid, cliente):
    if not (cliente or "").strip():
        return None, None
    c, cands = _pr_resolver_cliente(s, cid, cliente)
    return (c, None) if c else (None, _pr_nao_achei(cliente, cands))


def _im_json(v) -> dict:
    try:
        d = _json_pr.loads(v or "{}")
        return d if isinstance(d, dict) else {}
    except ValueError:
        return {}


_IM_CHAVES_RES = ("vgv_bruto", "vgv_liquido", "custo_total", "custo_obra_total", "resultado_bruto", "margem_vgv",
                  "margem_custo", "tir_anual", "tir_cap_risco_anual", "vpl", "exposicao_maxima", "payback_mes",
                  "unidades_total", "unidades_permuta", "area_privativa", "vgv_medio_m2", "custo_m2_equiv")


def _im_resumo_resultado(r: dict) -> dict:
    out = {k: r.get(k) for k in _IM_CHAVES_RES if k in r}
    st = r.get("status")
    if isinstance(st, dict):
        out["status"] = st.get("label")
    return out


# ── Viabilidade ──────────────────────────────────────────────────────────────

def _im_t_estudos(s, cid, cliente):
    c, erro = _im_cliente_ok(s, cid, cliente)
    if erro:
        return erro
    out = []
    EV = globals().get("EstudoViabilidade")
    if EV is not None:
        q = _sel_pr(EV).where(EV.company_id == cid)
        if c:
            q = q.where(EV.client_id == c.id)
        for e in s.exec(q.order_by(EV.id.desc()).limit(40)).all():
            out.append({"estudo_id": e.id, "origem": "estudo", "projeto": e.nome_projeto, "criado": e.criado_em,
                        "realista": _im_resumo_resultado(_im_json(e.resultado_realista_json))})
    VA = globals().get("ViabilidadeAnalise")
    if VA is not None:
        q = _sel_pr(VA).where(VA.company_id == cid)
        if c:
            q = q.where(VA.client_id == c.id)
        for a in s.exec(q.order_by(VA.id.desc()).limit(40)).all():
            out.append({"analise_id": a.id, "origem": "analise_salva", "projeto": a.nome, "criado": a.created_at,
                        "resultado": _im_resumo_resultado(_im_json(a.resultado_json))})
    return {"estudos": out, "total": len(out)}


def _im_t_estudo(s, cid, estudo_id, origem):
    if origem == "analise_salva":
        VA = globals().get("ViabilidadeAnalise")
        a = s.get(VA, int(estudo_id or 0)) if VA is not None else None
        if not a or a.company_id != cid:
            return {"erro": "Análise não encontrada."}
        return {"projeto": a.nome, "premissas": _im_json(a.dados_json), "resultado": _im_resumo_resultado(_im_json(a.resultado_json))}
    EV = globals().get("EstudoViabilidade")
    e = s.get(EV, int(estudo_id or 0)) if EV is not None else None
    if not e or e.company_id != cid:
        return {"erro": "Estudo não encontrado (use estudo_id de imob_estudos)."}
    return {"projeto": e.nome_projeto, "premissas": _im_json(e.dados_input_json),
            "realista": _im_resumo_resultado(_im_json(e.resultado_realista_json)),
            "otimista": _im_resumo_resultado(_im_json(e.resultado_otimista_json)),
            "pessimista": _im_resumo_resultado(_im_json(e.resultado_pessimista_json))}


def _im_t_calcular(s, cid, premissas, sensibilidade):
    calc = globals().get("_calcular_viabilidade_v2")
    if calc is None:
        return {"ok": False, "erro": "Motor de viabilidade indisponível."}
    p = dict(premissas or {})
    tips = [t for t in (p.get("tipologias") or []) if isinstance(t, dict) and float(t.get("metragem") or 0) > 0]
    if not tips or float(p.get("area_terreno") or 0) <= 0:
        return {"ok": False, "erro": "Informe ao menos área do terreno e uma tipologia (metragem e quantidade)."}
    p["tipologias"] = tips
    try:
        base = calc(p)
    except Exception as e:
        return {"ok": False, "erro": f"O motor recusou as premissas: {str(e)[:200]}"}
    out = {"ok": True, "resultado": _im_resumo_resultado(base),
           "observacao": "Mesmo motor da ferramenta de Viabilidade. Valores em R$; margens e TIR em %."}
    if sensibilidade:
        grade = []
        for dp in (-10, 0, 10):
            linha = {"variacao_preco_pct": dp, "por_variacao_custo": []}
            for dc in (-10, 0, 10):
                q = dict(p)
                q["preco_m2_base"] = float(p.get("preco_m2_base") or 12500) * (1 + dp / 100)
                q["tipologias"] = [dict(t, preco_m2=float(t["preco_m2"]) * (1 + dp / 100)) if t.get("preco_m2") else t for t in tips]
                q["cub_m2"] = float(p.get("cub_m2") or 3019) * (1 + dc / 100)
                try:
                    r = calc(q)
                    linha["por_variacao_custo"].append({"variacao_custo_pct": dc, "margem_vgv": r.get("margem_vgv"),
                                                        "tir_anual": r.get("tir_anual")})
                except Exception:
                    linha["por_variacao_custo"].append({"variacao_custo_pct": dc, "erro": True})
            grade.append(linha)
        out["sensibilidade_preco_x_custo"] = grade
    return out


# ── Produto e vendas ─────────────────────────────────────────────────────────

def _im_t_empreendimentos(s, cid, cliente):
    Emp, Un, Vd = (globals().get(n) for n in ("Empreendimento", "UnidadeEmpreendimento", "VendaUnidade"))
    if Emp is None:
        return {"erro": "Mapa de unidades indisponível."}
    c, erro = _im_cliente_ok(s, cid, cliente)
    if erro:
        return erro
    q = _sel_pr(Emp).where(Emp.company_id == cid)
    if c:
        q = q.where(Emp.client_id == c.id)
    hoje = _pr_hoje()
    nomes = _pr_clientes(s, cid)
    out = []
    for e in s.exec(q.order_by(Emp.id.desc()).limit(30)).all():
        us = s.exec(_sel_pr(Un).where(Un.empreendimento_id == e.id)).all()
        vendas = [v for v in s.exec(_sel_pr(Vd).where(Vd.empreendimento_id == e.id, Vd.status == "ativa")).all()]
        cont = {}
        for u in us:
            cont[u.status] = cont.get(u.status, 0) + 1
        vendaveis = [u for u in us if not u.permuta]
        vgv_tabela = sum(u.valor_vgv_projetado for u in vendaveis)
        vendidas_ids = {v.unidade_id for v in vendas}
        area_vendida = sum(u.metragem for u in us if u.id in vendidas_ids)
        valor_vendido = sum(v.valor_total for v in vendas)
        tabela_vendidas = sum(u.valor_vgv_projetado for u in us if u.id in vendidas_ids)
        recentes = [v for v in vendas if _pr_data(v.data_venda) and (hoje - _pr_data(v.data_venda)).days <= 180]
        ritmo = round(len(recentes) / 6, 2)
        estoque = sum(1 for u in vendaveis if u.status == "disponivel")
        out.append({"empreendimento_id": e.id, "nome": e.nome, "cliente": nomes.get(e.client_id, ""), "status": e.status,
                    "unidades": len(us), "permuta": sum(1 for u in us if u.permuta), "por_status": cont,
                    "vgv_tabela_vendavel": round(vgv_tabela, 2), "valor_vendido": round(valor_vendido, 2),
                    "pct_vgv_vendido": round(valor_vendido / vgv_tabela * 100, 1) if vgv_tabela else None,
                    "preco_m2_medio_vendido": round(valor_vendido / area_vendida, 2) if area_vendida else None,
                    "desconto_medio_sobre_tabela_pct": round((1 - valor_vendido / tabela_vendidas) * 100, 1) if tabela_vendidas else None,
                    "vendas_ultimos_6_meses": len(recentes), "ritmo_vendas_mes": ritmo,
                    "meses_de_estoque": round(estoque / ritmo, 1) if ritmo else None, "estoque_disponivel": estoque,
                    "estudo_id": e.estudo_id})
    return {"empreendimentos": out, "total": len(out)}


def _im_t_unidades(s, cid, empreendimento_id):
    Emp, Un, Vd = (globals().get(n) for n in ("Empreendimento", "UnidadeEmpreendimento", "VendaUnidade"))
    e = s.get(Emp, int(empreendimento_id or 0)) if Emp is not None else None
    if not e or e.company_id != cid:
        return {"erro": "Empreendimento não encontrado (use empreendimento_id de imob_empreendimentos)."}
    vendas = {v.unidade_id: v for v in s.exec(_sel_pr(Vd).where(Vd.empreendimento_id == e.id, Vd.status == "ativa")).all()}
    linhas = []
    for u in s.exec(_sel_pr(Un).where(Un.empreendimento_id == e.id).order_by(Un.andar, Un.numero)).all()[:400]:
        v = vendas.get(u.id)
        linhas.append({"unidade": u.numero, "tipologia": u.tipologia_nome, "andar": u.andar, "m2": u.metragem,
                       "tabela": u.valor_vgv_projetado, "status": u.status, "permuta": u.permuta,
                       "vendido_por": v.valor_total if v else None, "data_venda": v.data_venda if v else "",
                       "preco_m2": round((v.valor_total if v else u.valor_vgv_projetado) / u.metragem, 2) if u.metragem else None})
    return {"empreendimento": e.nome, "unidades": linhas, "total": len(linhas)}


# ── Obras ────────────────────────────────────────────────────────────────────

def _im_t_obras(s, cid, cliente):
    Ob = globals().get("Obra")
    if Ob is None:
        return {"erro": "Ferramenta de obras indisponível."}
    c, erro = _im_cliente_ok(s, cid, cliente)
    if erro:
        return erro
    q = _sel_pr(Ob).where(Ob.company_id == cid)
    if c:
        q = q.where(Ob.client_id == c.id)
    nomes = _pr_clientes(s, cid)
    out = []
    for o in s.exec(q.order_by(Ob.id.desc()).limit(30)).all():
        item = {"obra_id": o.id, "obra": o.nome, "cliente": nomes.get(o.client_id, ""), "status": o.status,
                "orcamento": o.orcamento_total, "inicio": o.data_inicio, "fim": o.data_fim}
        evm = globals().get("_calcular_evm")
        if evm is not None:
            try:
                r = evm(s, o)
                item.update({k: r.get(k) for k in ("BAC", "PV", "EV", "AC", "IDC", "IDP", "EAC", "VAC", "fisico_geral") if k in r})
            except Exception as e:
                item["evm_erro"] = str(e)[:120]
        out.append(item)
    return {"obras": out, "total": len(out),
            "legenda": "IDC = EV/AC (abaixo de 1: gastando mais que o executado); IDP = EV/PV (abaixo de 1: atrasada); "
                       "EAC = custo final projetado; VAC = BAC − EAC (negativo: estouro previsto)."}


def _im_t_obra(s, cid, obra_id):
    Ob = globals().get("Obra")
    o = s.get(Ob, int(obra_id or 0)) if Ob is not None else None
    if not o or o.company_id != cid:
        return {"erro": "Obra não encontrada (use obra_id de imob_obras)."}
    evm = globals().get("_calcular_evm")
    if evm is None:
        return {"erro": "Cálculo de EVM indisponível."}
    r = evm(s, o)
    etapas = r.get("etapas") or []
    estouros = sorted([e for e in etapas if e.get("ac", 0) > e.get("ev", 0) * 1.05 and e.get("ac", 0) > 0],
                      key=lambda e: -(e["ac"] - e["ev"]))[:10]
    atrasos = sorted([e for e in etapas if e.get("pv", 0) > e.get("ev", 0) * 1.05],
                     key=lambda e: -(e["pv"] - e["ev"]))[:10]
    enx = lambda e: {k: (round(v, 2) if isinstance(v, float) else v) for k, v in e.items()
                     if k in ("descricao", "fase", "orcado", "pv", "ev", "ac", "fisico_pct", "dt_inicio", "dt_fim")}
    return {"obra": o.nome, "orcamento": o.orcamento_total, "inicio": o.data_inicio, "fim": o.data_fim, "status": o.status,
            "indicadores": {k: r.get(k) for k in ("BAC", "PV", "EV", "AC", "IDC", "IDP", "EAC", "VAC", "ETC", "fisico_geral") if k in r},
            "etapas_acima_do_custo": [dict(enx(e), estouro=round(e["ac"] - e["ev"], 2)) for e in estouros],
            "etapas_atrasadas": [dict(enx(e), atraso_valor=round(e["pv"] - e["ev"], 2)) for e in atrasos],
            "total_etapas": len(etapas)}


# ── Registro ──────────────────────────────────────────────────────────────────

_IM_S = {"type": "string"}
_IM_N = {"type": "number"}
_IM_FERRAMENTAS = {
    "imob_estudos": {
        "fn": _im_t_estudos, "rotulo": "Consultou os estudos de viabilidade",
        "description": "Estudos de viabilidade salvos (e análises salvas) com o resultado-resumo: VGV, custo, resultado, "
                       "margem, TIR, VPL, exposição máxima e payback.",
        "props": {"cliente": {"type": "string", "description": "Nome do cliente ou vazio para todos."}}},
    "imob_estudo": {
        "fn": _im_t_estudo, "rotulo": "Leu um estudo de viabilidade",
        "description": "Premissas completas e resultados (realista, otimista, pessimista) de um estudo.",
        "props": {"estudo_id": {"type": "integer"}, "origem": {"type": "string", "enum": ["estudo", "analise_salva"]}}},
    "imob_calcular": {
        "fn": _im_t_calcular, "rotulo": "Calculou a viabilidade",
        "description": "Roda o motor de viabilidade (o mesmo da ferramenta) com as premissas dadas e devolve VGV, custos, "
                       "resultado, margem, TIR, VPL, exposição e payback; com sensibilidade, a grade preço x custo (±10%). "
                       "Premissas: area_terreno, indice_aproveitamento, valor_terreno, pct_permuta, preco_m2_base, "
                       "diferencial_andar (% por andar), cub_m2, duracao_obra, mes_inicio_obra, mes_inicio_vendas, "
                       "pct_corretagem, pct_impostos, pct_indiretos, tipologias [{nome, tipo, metragem, quantidade, "
                       "andar_inicio, preco_m2, permuta}]. Para comparar com um estudo salvo, parta das premissas dele "
                       "(imob_estudo) e mude só o que for testar.",
        "props": {"premissas": {"type": "object"}, "sensibilidade": {"type": "boolean"}}},
    "imob_empreendimentos": {
        "fn": _im_t_empreendimentos, "rotulo": "Analisou os empreendimentos",
        "description": "Mapa de vendas por empreendimento: unidades por status, VGV de tabela, vendido, % do VGV, preço "
                       "médio/m² vendido, desconto médio sobre a tabela, ritmo de vendas (6 meses) e meses de estoque.",
        "props": {"cliente": {"type": "string", "description": "Nome do cliente ou vazio para todos."}}},
    "imob_unidades": {
        "fn": _im_t_unidades, "rotulo": "Leu o mapa de unidades",
        "description": "Unidades de um empreendimento: tipologia, andar, m², tabela, status, valor e data de venda e preço/m².",
        "props": {"empreendimento_id": {"type": "integer"}}},
    "imob_obras": {
        "fn": _im_t_obras, "rotulo": "Analisou as obras",
        "description": "Obras com indicadores de valor agregado: orçamento (BAC), planejado (PV), executado (EV), gasto (AC), "
                       "IDC, IDP, custo final projetado (EAC), estouro previsto (VAC) e % físico.",
        "props": {"cliente": {"type": "string", "description": "Nome do cliente ou vazio para todos."}}},
    "imob_obra": {
        "fn": _im_t_obra, "rotulo": "Analisou uma obra",
        "description": "Uma obra em detalhe: indicadores de valor agregado e as etapas que mais estouram o custo e as que "
                       "mais atrasam.",
        "props": {"obra_id": {"type": "integer"}}},
}

for _nome_im, _spec_im in _IM_FERRAMENTAS.items():
    _pr_registrar_ferramenta(_nome_im, _spec_im)

_IM_COMUNS = ["cli_panorama", "conh_buscar", "conh_ler", "rel_gerar_relatorio", "an_gerar_excel"]
_IM_AGENTES = {
    "viabilidade": {
        "web": True,
        "atribuicoes": "Monta e compara estudos de viabilidade (VGV, custo, margem, TIR, exposição) com o motor da "
                       "ferramenta, sensibilidade preço x custo e financiamento da obra.",
        "ferramentas": ["imob_estudos", "imob_estudo", "imob_calcular", "an_cenarios", "an_projecao_caixa", "cred_simular"] + _IM_COMUNS,
        "instrucoes": (
            "Você é o analista de viabilidade imobiliária da M. Capital (incorporação residencial e comercial).\n"
            "- Números SEMPRE pelo motor (imob_calcular), nunca de cabeça. Para revisar um estudo salvo, leia as "
            "premissas (imob_estudo) e altere só o que está sendo testado; diga o que mudou.\n"
            "- Leitura: margem sobre VGV (benchmark ≥ 20% saudável, 15% mínimo), TIR anual, exposição máxima de caixa "
            "e payback. Rode a sensibilidade (preço e custo ±10%) e diga o que derruba a viabilidade.\n"
            "- Premissas de mercado (preço/m² da região, CUB, velocidade de vendas): pesquise na web e cite a fonte; "
            "o que for estimativa, diga.\n"
            "- Financiamento da obra (plano empresário, CRI): simule com cred_simular e mostre o efeito na exposição.\n"
            "- Entregue o comparativo em tabela e, quando pedido, em Excel (an_gerar_excel) ou Word (rel_gerar_relatorio).")},
    "produto_vendas": {
        "web": True,
        "atribuicoes": "Mapa de unidades, tabela de preços e ritmo de vendas: estoque, desconto sobre tabela, meses de "
                       "estoque e aderência ao estudo de viabilidade.",
        "ferramentas": ["imob_empreendimentos", "imob_unidades", "imob_estudo", "imob_calcular"] + _IM_COMUNS,
        "instrucoes": (
            "Você cuida do produto e das vendas dos empreendimentos dos clientes.\n"
            "- Situação (imob_empreendimentos): % do VGV vendido, ritmo de vendas, meses de estoque e desconto médio "
            "sobre a tabela; compare com a premissa do estudo de viabilidade (imob_estudo) e diga se o resultado "
            "projetado está em risco (se necessário, recalcule com imob_calcular usando o preço e o ritmo reais).\n"
            "- Tabela de preços: proponha reajuste por andar, tipologia ou posição a partir do que vende e do que "
            "encalha (imob_unidades), com a lógica explicada; entregue em Excel quando pedido.\n"
            "- Mercado: preços e lançamentos concorrentes da região, pesquisados na web com fonte.\n"
            "- Seja específico: unidades, valores e datas.")},
    "obras": {
        "web": False,
        "atribuicoes": "Físico x financeiro das obras por valor agregado (IDC, IDP, custo final projetado) e alertas de "
                       "desvio, com ações corretivas.",
        "ferramentas": ["imob_obras", "imob_obra", "ops_propor_tarefa", "an_projecao_caixa"] + _IM_COMUNS,
        "instrucoes": (
            "Você acompanha as obras dos clientes pelo valor agregado.\n"
            "- Visão geral (imob_obras) e, para cada obra relevante, o detalhe (imob_obra).\n"
            "- Interprete: IDC < 1 = gastando mais que o executado; IDP < 1 = atrasada; EAC = custo final se o ritmo "
            "de custo continuar; VAC negativo = estouro previsto. Aponte as etapas que mais pesam no desvio.\n"
            "- Ações corretivas concretas (renegociar empreitada, revisar compra de insumo, replanejar etapa), com "
            "responsável e prazo; proponha como tarefa (ops_propor_tarefa) quando o sócio pedir ou o desvio for grave.\n"
            "- Se não houver apontamentos recentes, diga que a análise está desatualizada antes de concluir.")},
}

for _key_im, _cfg_im in _IM_AGENTES.items():
    _ag_im = _PREDIO_AGENTES.get(_key_im)
    if not _ag_im:
        continue
    _ag_im.update(ativo=True, web=_cfg_im["web"], atribuicoes=_cfg_im["atribuicoes"],
                  ferramentas=[f for f in _cfg_im["ferramentas"] if f in _PR_TOOLS])
    _PR_INSTRUCOES[_key_im] = _cfg_im["instrucoes"]

print("[predio_imobiliario] 4º andar (Imobiliário) carregado.")

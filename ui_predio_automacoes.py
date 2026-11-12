# ============================================================================
# ui_predio_automacoes.py — Automações do prédio: agentes que agem sozinhos
# ============================================================================
# Exec'd no namespace do app.py, DEPOIS de todos os módulos do prédio.
#
# Cada automação abre um chamado para um agente quando algo acontece (ou na data
# certa). O agente prepara tudo e deixa PROPOSTAS: nada é enviado, emitido ou
# lançado sem aprovação. Liga/desliga, última execução e custo no card da home.
#
#   pos_reuniao          — transcrição pronta → Secretário: ata, tarefas e e-mail de follow-up
#   faturamento_mensal   — dia X do mês (padrão 1º), 9h → Faturamento: NF e boleto de todos os contratos
#   cobranca_atrasos     — dias úteis, 10h, só se houver título vencido há 3+ dias sem cobrança
#                          recente → Cobrança: e-mails no tom certo para cada atraso
#   contas_pagar_semanal — segunda, 8h → Contas a Pagar: agenda da semana e conciliação
#
# Cada disparo é gravado em PredioAutomacaoEvento com chave única (empresa, automação,
# referência): com 2 workers, só um dispara.
#
# ROTAS (admin)
#   POST /predio/automacoes/{chave}/alternar   — liga/desliga
#   POST /predio/automacoes/{chave}/rodar      — roda agora
#   POST /predio/automacoes/{chave}/config     — parâmetros (dia do faturamento)
# ============================================================================

from sqlalchemy import UniqueConstraint as _UQ_au
from sqlalchemy.exc import IntegrityError as _IntegrityError_au


class PredioAutomacao(_SM_pr, table=True):
    __tablename__ = "predio_automacao"
    __table_args__ = (_UQ_au("company_id", "chave", name="uq_predio_automacao"), {"extend_existing": True})
    id: _Opt_pr[int] = _F_pr(default=None, primary_key=True)
    company_id: int = _F_pr(index=True)
    chave: str = _F_pr(default="")
    ativo: bool = _F_pr(default=False)
    ativado_em: _Opt_pr[_dt_pr] = _F_pr(default=None)
    config_json: str = _F_pr(default="{}")
    ultimo_em: _Opt_pr[_dt_pr] = _F_pr(default=None)
    ultimo_chamado_id: _Opt_pr[int] = _F_pr(default=None)
    ultimo_resumo: str = _F_pr(default="")


class PredioAutomacaoEvento(_SM_pr, table=True):
    __tablename__ = "predio_automacao_evento"
    __table_args__ = (_UQ_au("company_id", "chave", "ref", name="uq_predio_automacao_evento"), {"extend_existing": True})
    id: _Opt_pr[int] = _F_pr(default=None, primary_key=True)
    company_id: int = _F_pr(index=True)
    chave: str = _F_pr(default="", index=True)
    ref: str = _F_pr(default="")
    chamado_id: _Opt_pr[int] = _F_pr(default=None, index=True)
    resumo: str = _F_pr(default="")
    criado_em: _dt_pr = _F_pr(default_factory=lambda: _dt_pr.utcnow(), index=True)


try:
    _SM_pr.metadata.create_all(engine, tables=[PredioAutomacao.__table__, PredioAutomacaoEvento.__table__], checkfirst=True)
except Exception as _e_au_tab:
    print(f"[predio_automacoes] create_all: {_e_au_tab}")


_AU_DEFS = {
    "pos_reuniao": {
        "nome": "Depois de cada reunião", "agente": "secretario_reunioes",
        "quando": "Assim que a transcrição fica pronta",
        "faz": "Ata, tarefas combinadas (com responsável e prazo) e e-mail de follow-up aos participantes da reunião, para você aprovar."},
    "faturamento_mensal": {
        "nome": "Faturamento do mês", "agente": "faturamento",
        "quando": "Todo mês, no dia escolhido, às 9h",
        "faz": "Proposta única com NFS-e e boleto de todos os contratos do mês; aponta o que falta no cadastro."},
    "cobranca_atrasos": {
        "nome": "Cobrança de atrasos", "agente": "cobranca",
        "quando": "Dias úteis, às 10h — só quando há título vencido há 3 dias ou mais",
        "faz": "E-mail de cobrança no tom certo para cada cliente em atraso (sem repetir quem foi cobrado nos últimos 7 dias)."},
    "briefing_reuniao": {
        "nome": "Briefing antes da reunião", "agente": "gestor_carteira",
        "quando": "Todo dia às 17h, para as reuniões da agenda do dia seguinte",
        "faz": "Resumo do cliente para quem vai atender: situação, o que foi combinado na última reunião, tarefas e pendências."},
    "relatorio_mensal": {
        "nome": "Relatório mensal dos clientes", "agente": "relatorio_mensal",
        "quando": "Todo mês, no dia escolhido, às 9h — um por cliente com contrato ativo",
        "faz": "Rascunho em Word do relatório do mês anterior (executivo, ou RMA em recuperação judicial) para revisar e enviar."},
    "renovacoes": {
        "nome": "Renovações e vendas adicionais", "agente": "sucesso_cliente",
        "quando": "Todo mês, no dia escolhido, às 9h",
        "faz": "Contratos que vencem em 90 dias com a conversa de renovação preparada (tarefa para quem cuida) e "
               "oportunidades de venda adicional tiradas das reuniões."},
    "lead_site": {
        "nome": "Lead do site", "agente": "chief_of_staff",
        "quando": "Assim que chega um lead pelo site (simulação de crédito, calculadora de valuation, teste do Augur)",
        "faz": "A Prospecção pesquisa a empresa e classifica; para os quentes ou mornos, a Propostas deixa um "
               "rascunho de proposta pronto."},
    "cliente_novo": {
        "nome": "Cliente novo", "agente": "compliance",
        "quando": "Assim que um cliente novo é cadastrado",
        "faz": "KYC e checagem de conflito de interesse, com parecer de aceitação."},
    "contas_pagar_semanal": {
        "nome": "Contas a pagar da semana", "agente": "contas_pagar",
        "quando": "Toda segunda, às 8h",
        "faz": "Agenda de pagamentos da semana, o que está vencido e o extrato pendente de conciliação."},
}


def _au_reg(s, cid: int, chave: str) -> PredioAutomacao:
    r = s.exec(_sel_pr(PredioAutomacao).where(PredioAutomacao.company_id == cid, PredioAutomacao.chave == chave)).first()
    if not r:
        r = PredioAutomacao(company_id=cid, chave=chave)
        s.add(r)
        try:
            s.commit()
        except _IntegrityError_au:
            s.rollback()
            r = s.exec(_sel_pr(PredioAutomacao).where(PredioAutomacao.company_id == cid, PredioAutomacao.chave == chave)).first()
        s.refresh(r)
    return r


def _au_cfg(r) -> dict:
    try:
        d = _json_pr.loads(r.config_json or "{}")
        return d if isinstance(d, dict) else {}
    except ValueError:
        return {}


def _au_reivindicar(cid: int, chave: str, ref: str) -> bool:
    """Grava o evento; se outro worker já gravou (chave única), devolve False."""
    with _Sess_pr(engine) as s:
        s.add(PredioAutomacaoEvento(company_id=cid, chave=chave, ref=ref))
        try:
            s.commit()
            return True
        except _IntegrityError_au:
            s.rollback()
            return False


def _au_admin(s, cid: int):
    m = s.exec(_sel_pr(Membership).where(Membership.company_id == cid, Membership.role == "admin")).first()
    return m.user_id if m else None


def _au_disparar(cid: int, chave: str, ref: str, titulo: str, pedido: str, resumo: str = "",
                 para_user_id: _Opt_pr[int] = None) -> _Opt_pr[int]:
    """Abre o chamado da automação (o evento já foi reivindicado) e registra a execução.
    para_user_id: abre em nome dessa pessoa (ela recebe o aviso quando ficar pronto); padrão, um admin."""
    _pr_sincronizar_agentes()
    d = _AU_DEFS[chave]
    with _Sess_pr(engine) as s:
        autor, papel = _au_admin(s, cid), "admin"
        if para_user_id:
            mb = s.exec(_sel_pr(Membership).where(Membership.company_id == cid, Membership.user_id == para_user_id,
                                                  Membership.role.in_(["admin", "equipe"]))).first()
            if mb:
                autor, papel = para_user_id, mb.role
        if not autor or not _pr_pode_usar(_PREDIO_AGENTES.get(d["agente"]), papel):
            return None
        ch = PredioChamado(company_id=cid, created_by_user_id=autor, papel_solicitante=papel, titulo=titulo[:200],
                           pedido=pedido, agente_key=d["agente"], roteamento="agenda",
                           motivo_roteamento=f"Automação: {d['nome']}.")
        s.add(ch)
        s.commit()
        s.refresh(ch)
        ev = s.exec(_sel_pr(PredioAutomacaoEvento).where(PredioAutomacaoEvento.company_id == cid,
                                                         PredioAutomacaoEvento.chave == chave,
                                                         PredioAutomacaoEvento.ref == ref)).first()
        if ev:
            ev.chamado_id, ev.resumo = ch.id, resumo[:300]
            s.add(ev)
        r = _au_reg(s, cid, chave)
        r.ultimo_em, r.ultimo_chamado_id, r.ultimo_resumo = _dt_pr.utcnow(), ch.id, resumo[:300]
        s.add(r)
        s.commit()
        chid = ch.id
    _pr_disparar(chid)
    print(f"[predio_automacoes] {chave} ({ref}) → chamado {chid}")
    return chid


def _au_registrar_sem_chamado(cid: int, chave: str, ref: str, resumo: str) -> None:
    with _Sess_pr(engine) as s:
        ev = s.exec(_sel_pr(PredioAutomacaoEvento).where(PredioAutomacaoEvento.company_id == cid,
                                                         PredioAutomacaoEvento.chave == chave,
                                                         PredioAutomacaoEvento.ref == ref)).first()
        if ev:
            ev.resumo = resumo[:300]
            s.add(ev)
        r = _au_reg(s, cid, chave)
        r.ultimo_em, r.ultimo_chamado_id, r.ultimo_resumo = _dt_pr.utcnow(), None, resumo[:300]
        s.add(r)
        s.commit()


# ── 1. Depois de cada reunião ────────────────────────────────────────────────

def _au_pedido_reuniao(s, cid, m) -> str:
    cliente = _pr_clientes(s, cid).get(m.client_id, "")
    return (f"A reunião #{m.id} \"{m.title or 'sem título'}\" com {cliente or 'o cliente'} acabou de ser transcrita. "
            "Faça o pós-reunião:\n"
            f"1. Leia o conteúdo completo (reu_conteudo com reuniao_id {m.id}).\n"
            "2. Escreva a ata: participantes, assuntos tratados, decisões, pendências do cliente e do escritório, "
            "próximos passos com responsável e prazo.\n"
            "3. Proponha cada tarefa combinada com ops_propor_tarefa (responsável e prazo; prazo em DD/MM/AAAA).\n"
            f"4. Proponha o e-mail de follow-up aos participantes com reu_propor_followup (reuniao_id {m.id}): cordial, "
            "objetivo, com o resumo das decisões, o que cada lado ficou de fazer e a próxima data, se houver. "
            "Nada de informação interna do escritório (honorários de outros clientes, opiniões sobre o cliente).\n"
            "Se a reunião for interna (sem cliente) ou a transcrição estiver vazia/inaudível, faça só a ata e diga isso.")


def _au_pos_reuniao(cid: int, r, forcar: bool = False) -> int:
    M = globals().get("Meeting")
    if M is None:
        return 0
    desde = _dt_pr.utcnow() - _td_pr(days=7 if forcar else 3)
    if not forcar and r.ativado_em and r.ativado_em > desde:
        desde = r.ativado_em
    with _Sess_pr(engine) as s:
        prontas = s.exec(_sel_pr(M.id).where(M.company_id == cid, M.notion_status == "notes_ready", M.updated_at >= desde)
                         .order_by(M.updated_at.desc()).limit(20)).all()
        feitas = set(s.exec(_sel_pr(PredioAutomacaoEvento.ref).where(PredioAutomacaoEvento.company_id == cid,
                                                                     PredioAutomacaoEvento.chave == "pos_reuniao")).all())
    n = 0
    for mid in prontas:
        ref = f"reuniao-{mid}"
        if ref in feitas:
            continue
        if not _au_reivindicar(cid, "pos_reuniao", ref):
            continue
        with _Sess_pr(engine) as s:
            m = s.get(M, mid)
            pedido, titulo = _au_pedido_reuniao(s, cid, m), f"Pós-reunião: {m.title or ('reunião #' + str(mid))}"
        _au_disparar(cid, "pos_reuniao", ref, titulo, pedido, f"Reunião #{mid}")
        n += 1
        if n >= (1 if forcar else 3):
            break
    return n


# ── 2. Faturamento do mês ────────────────────────────────────────────────────

def _au_faturamento(cid: int, r, forcar: bool = False) -> bool:
    agora = _pr_agora_brt()
    dia = max(1, min(int(_au_cfg(r).get("dia") or 1), 28))
    comp = agora.strftime("%Y-%m")
    if not forcar and (agora.day < dia or (agora.day == dia and agora.hour < 9)):
        return False
    ref = comp if not forcar else f"manual-{_dt_pr.utcnow().isoformat()}"
    if not _au_reivindicar(cid, "faturamento_mensal", ref):
        return False
    pedido = (f"Faturamento automático da competência {comp}.\n"
              f"1. Confira a competência com fat_competencia ({comp}).\n"
              "2. Proponha, numa proposta só, a emissão de NFS-e e boleto de todos os contratos ativos "
              f"(fat_propor_emissao, competência {comp}, documentos boleto_e_nfse). Ela já gera as cobranças que faltam.\n"
              "3. Liste o que ficou de fora e o que corrigir (cadastro incompleto, valor zero, já pago) e proponha as "
              "correções de contrato que dependerem só de dado do contrato.\n"
              "4. Aponte valores diferentes do contrato ou contratos vencendo nos próximos 60 dias.\n"
              "Se tudo já estiver emitido, diga isso em uma linha.")
    _au_disparar(cid, "faturamento_mensal", ref, f"Faturamento de {comp[5:]}/{comp[:4]}", pedido, f"Competência {comp}")
    return True


# ── 3. Cobrança de atrasos ───────────────────────────────────────────────────

def _au_atrasos(s, cid: int) -> list:
    hoje = _pr_hoje()
    E = OfficeFinancialEntry
    nomes = _pr_clientes(s, cid)
    por_cliente = {}
    for e in s.exec(_sel_pr(E).where(E.company_id == cid, E.entry_kind == "receber", E.status == "aberto")).all():
        venc = _pr_data(e.due_date)
        valor = float(e.amount_expected_brl or 0) - float(e.amount_realized_brl or 0)
        if not venc or valor <= 0 or (hoje - venc).days < 3 or not e.client_id:
            continue
        p = por_cliente.setdefault(e.client_id, {"cliente": nomes.get(e.client_id, f"#{e.client_id}"), "titulos": 0,
                                                 "valor": 0.0, "maior_atraso": 0})
        p["titulos"] += 1
        p["valor"] += valor
        p["maior_atraso"] = max(p["maior_atraso"], (hoje - venc).days)
    if not por_cliente:
        return []
    recentes = set(s.exec(_sel_pr(PredioAcao.client_id).where(
        PredioAcao.company_id == cid, PredioAcao.tipo == "email_cobranca", PredioAcao.status != "rejeitada",
        PredioAcao.criado_em >= _dt_pr.utcnow() - _td_pr(days=7))).all())
    return sorted([p for k, p in por_cliente.items() if k not in recentes], key=lambda p: -p["maior_atraso"])


def _au_cobranca(cid: int, r, forcar: bool = False) -> bool:
    agora = _pr_agora_brt()
    if not forcar and (agora.weekday() >= 5 or agora.hour < 10):
        return False
    ref = agora.date().isoformat() if not forcar else f"manual-{_dt_pr.utcnow().isoformat()}"
    if not _au_reivindicar(cid, "cobranca_atrasos", ref):
        return False
    with _Sess_pr(engine) as s:
        lista = _au_atrasos(s, cid)
    if not lista:
        _au_registrar_sem_chamado(cid, "cobranca_atrasos", ref, "Nada a cobrar hoje.")
        return True
    linhas = "\n".join(f"- {p['cliente']}: {p['titulos']} título(s), R$ {p['valor']:,.2f}, maior atraso {p['maior_atraso']} dias"
                       .replace(",", "X").replace(".", ",").replace("X", ".") for p in lista[:25])
    pedido = ("Cobrança automática dos atrasos de hoje. Clientes com título vencido há 3 dias ou mais e sem e-mail de "
              f"cobrança nos últimos 7 dias:\n{linhas}\n\n"
              "Para cada um: veja o histórico (cob_historico_cliente) e proponha UM e-mail de cobrança consolidando os "
              "títulos (cob_propor_email), no tom certo para o atraso. Se o histórico mostrar acordo em andamento, "
              "pagamento recente ou motivo para não cobrar, não proponha e explique. Atrasos acima de 30 dias: "
              "recomende ao sócio uma ligação. Termine com uma tabela: cliente, valor, atraso, o que foi proposto.")
    _au_disparar(cid, "cobranca_atrasos", ref, f"Cobrança de atrasos — {agora.strftime('%d/%m')}", pedido,
                 f"{len(lista)} cliente(s) em atraso")
    return True


# ── Briefing antes da reunião ────────────────────────────────────────────────

def _au_briefing(cid: int, r, forcar: bool = False) -> int:
    B = globals().get("AgendaBooking")
    if B is None:
        return 0
    agora = _pr_agora_brt()
    if not forcar and agora.hour < 17:
        return 0
    amanha = agora.date() + _td_pr(days=1)
    dias = [amanha] if not forcar else [agora.date(), amanha, amanha + _td_pr(days=1)]
    with _Sess_pr(engine) as s:
        cands = [b for b in s.exec(_sel_pr(B).where(B.company_id == cid, B.status != "cancelado")).all()
                 if _pr_data(b.data) in dias]
        cands.sort(key=lambda b: (_pr_data(b.data), b.hora_inicio or ""))
        feitas = set(s.exec(_sel_pr(PredioAutomacaoEvento.ref).where(PredioAutomacaoEvento.company_id == cid,
                                                                     PredioAutomacaoEvento.chave == "briefing_reuniao")).all())
        itens = []
        for b in cands:
            ref = f"agenda-{b.id}"
            if ref in feitas:
                continue
            cli = s.get(Client, b.client_id) if b.client_id else None
            mb = s.get(globals()["AgendaMembro"], b.membro_id) if b.membro_id and "AgendaMembro" in globals() else None
            sv = s.get(globals()["AgendaServico"], b.servico_id) if b.servico_id and "AgendaServico" in globals() else None
            itens.append((ref, b.id, _pr_fmt_data(_pr_data(b.data)), b.hora_inicio or "", cli.name if cli else "",
                          b.solicitante_nome or "", (mb.nome if mb else ""), (mb.user_id if mb else None),
                          (getattr(sv, "nome", "") if sv else ""), b.local or "", (b.notas or "")[:500]))
    n = 0
    for ref, bid, data, hora, cliente, solicitante, membro, membro_uid, servico, local, notas in itens:
        if not _au_reivindicar(cid, "briefing_reuniao", ref):
            continue
        quem = cliente or solicitante or "contato sem cadastro"
        pedido = (f"Reunião da agenda em {data} às {hora} com {quem}"
                  + (f" ({servico})" if servico else "") + (f", local: {local}" if local else "")
                  + (f". Quem atende: {membro}" if membro else "") + (f".\nObservações do agendamento: {notas}" if notas else ".")
                  + "\n\nPrepare o briefing para quem vai atender, curto e direto (cabe numa tela):\n"
                  + ("1. Situação do cliente (cli_panorama): contrato, projetos, saúde da conta, financeiro relevante.\n"
                     "2. O que foi combinado na última reunião (reu_listar e reu_conteudo da mais recente) e o que foi cumprido.\n"
                     "3. Tarefas atrasadas e pendências abertas do cliente e do escritório.\n"
                     "4. Pauta sugerida: 3 a 5 pontos, com o que precisa sair decidido.\n"
                     if cliente else
                     "É um contato sem cadastro de cliente (provável lead): diga o que se sabe pelo agendamento e sugira "
                     "uma pauta de primeira conversa (entender a empresa, a dor, o momento financeiro e o próximo passo).\n")
                  + "Não proponha tarefas: é só o briefing.")
        _au_disparar(cid, "briefing_reuniao", ref, f"Briefing: {quem} — {data} {hora}", pedido,
                     f"{quem} em {data} {hora}", para_user_id=membro_uid)
        n += 1
        if n >= (1 if forcar else 5):
            break
    if forcar and not n:
        _au_registrar_sem_chamado_simples(cid, "briefing_reuniao", "Nenhuma reunião na agenda hoje, amanhã ou depois.")
    return n


# ── Relatório mensal dos clientes ────────────────────────────────────────────

def _au_relatorio(cid: int, r, forcar: bool = False) -> int:
    CC = globals().get("ContratoCliente")
    if CC is None:
        return 0
    agora = _pr_agora_brt()
    dia = max(1, min(int(_au_cfg(r).get("dia") or 5), 28))
    if not forcar and (agora.day < dia or (agora.day == dia and agora.hour < 9)):
        return 0
    ref_mes = (agora.date().replace(day=1) - _td_pr(days=1))
    mes, mes_txt = ref_mes.strftime("%Y-%m"), ref_mes.strftime("%m/%Y")
    with _Sess_pr(engine) as s:
        ids = sorted({c for c in s.exec(_sel_pr(CC.client_id).where(CC.company_id == cid, CC.status == "ativo")).all() if c})
        nomes = _pr_clientes(s, cid)
        feitas = set(s.exec(_sel_pr(PredioAutomacaoEvento.ref).where(PredioAutomacaoEvento.company_id == cid,
                                                                     PredioAutomacaoEvento.chave == "relatorio_mensal")).all())
    n = 0
    for cl in ids:
        ref = f"{mes}-cliente-{cl}"
        if ref in feitas and not forcar:
            continue
        if forcar:
            ref = f"manual-{_dt_pr.utcnow().isoformat()}-{cl}"
            if f"{mes}-cliente-{cl}" in feitas:
                continue
        if not _au_reivindicar(cid, "relatorio_mensal", ref):
            continue
        if forcar:
            _au_reivindicar(cid, "relatorio_mensal", f"{mes}-cliente-{cl}")
        nome = nomes.get(cl, f"cliente #{cl}")
        pedido = (f"Relatório mensal de {mes_txt} do cliente {nome}, em Word (rel_gerar_relatorio).\n"
                  "- Tipo: 'rma' se o cliente estiver em recuperação judicial (veja o panorama, o contrato e as reuniões); "
                  "senão, 'executivo'.\n"
                  f"- Use os dados de {mes_txt}: reuniões do mês, fluxo de caixa (fc_resumo), orçamento x realizado "
                  "(orc_vs_real), indicadores (fin_indicadores, se houver DRE/balanço nos documentos) e o que foi feito.\n"
                  "- O que não tiver dado, deixe [PENDENTE: ...] — nunca invente.\n"
                  "- No chat: o que o sócio precisa revisar ou completar antes de enviar.")
        _au_disparar(cid, "relatorio_mensal", ref, f"Relatório {mes_txt}: {nome}", pedido, f"{nome} — {mes_txt}")
        n += 1
        if n >= (1 if forcar else 3):   # espalha os relatórios pelos ciclos do agendador
            break
    if forcar and not n:
        _au_registrar_sem_chamado_simples(cid, "relatorio_mensal", f"Todos os clientes com contrato já têm o relatório de {mes_txt}.")
    return n


def _au_registrar_sem_chamado_simples(cid: int, chave: str, resumo: str) -> None:
    with _Sess_pr(engine) as s:
        r = _au_reg(s, cid, chave)
        r.ultimo_em, r.ultimo_chamado_id, r.ultimo_resumo = _dt_pr.utcnow(), None, resumo[:300]
        s.add(r)
        s.commit()


# ── Renovações e vendas adicionais ───────────────────────────────────────────

def _au_renovacoes(cid: int, r, forcar: bool = False) -> bool:
    agora = _pr_agora_brt()
    dia = max(1, min(int(_au_cfg(r).get("dia") or 3), 28))
    mes = agora.strftime("%Y-%m")
    if not forcar and (agora.day < dia or (agora.day == dia and agora.hour < 9)):
        return False
    ref = mes if not forcar else f"manual-{_dt_pr.utcnow().isoformat()}"
    if not _au_reivindicar(cid, "renovacoes", ref):
        return False
    hoje = agora.date()
    lista = []
    CC = globals().get("ContratoCliente")
    if CC is not None:
        with _Sess_pr(engine) as s:
            nomes = _pr_clientes(s, cid)
            for k in s.exec(_sel_pr(CC).where(CC.company_id == cid, CC.status == "ativo")).all():
                fim_ = _pr_data(k.data_fim)
                if fim_ and hoje <= fim_ <= hoje + _td_pr(days=90):
                    lista.append(f"- {nomes.get(k.client_id, k.nome_cliente)} — {k.nome_contrato}: termina em "
                                 f"{_pr_fmt_data(fim_)} ({(fim_ - hoje).days} dias), R$ {(k.valor_cents or 0) / 100:,.2f}/mês"
                                 .replace(",", "X").replace(".", ",").replace("X", "."))
    pedido = ("Revisão mensal da carteira (automática).\n"
              + ("CONTRATOS QUE TERMINAM EM ATÉ 90 DIAS:\n" + "\n".join(lista) + "\n\n" if lista else
                 "Nenhum contrato termina nos próximos 90 dias.\n\n")
              + "1. Para cada contrato acima: veja o que foi entregue (reuniões, BSC, panorama) e prepare a conversa de "
                "renovação — o que mostrar, o que propor (reajuste, ampliação de escopo) e o risco de não renovar. "
                "Proponha UMA tarefa por cliente (ops_propor_tarefa) para quem cuida dele, com prazo 30 dias antes do "
                "término. Se já houver tarefa ou negócio de renovação aberto (com_negocios), não repita.\n"
                "2. Venda adicional: nas reuniões dos últimos 60 dias dos clientes ativos, procure dores que outro "
                "serviço resolve e aponte as 3 melhores oportunidades com o trecho que as sustenta; proponha o negócio "
                "no CRM só quando a oportunidade estiver clara.\n"
                "3. Sinais de risco de cancelamento (com_saude_clientes), com o próximo passo.\n"
                "Termine com um quadro: cliente, situação, ação proposta.")
    _au_disparar(cid, "renovacoes", ref, f"Renovações e vendas — {agora.strftime('%m/%Y')}", pedido,
                 f"{len(lista)} contrato(s) vencendo em 90 dias")
    return True


# ── Lead do site ─────────────────────────────────────────────────────────────

_AU_LEADS = (("credito", "LeadCredito", "Site — simulação de crédito"),
             ("valuation", "LeadValuation", "Site — calculadora de valuation"),
             ("trial", "TrialLead", "Teste grátis do Augur PME"))


def _au_leads_base(s, cid) -> dict:
    """Maior id de cada fonte de lead no momento em que a automação é ligada (não processa o passado)."""
    out = {}
    for k, modelo, _ in _AU_LEADS:
        M = globals().get(modelo)
        if M is not None:
            out[f"lead_{k}"] = int(s.exec(_sel_pr(_func_pr.coalesce(_func_pr.max(M.id), 0))).one() or 0)
    return out


def _au_lead_texto(k, l) -> str:
    g = lambda a: str(getattr(l, a, "") or "").strip()
    linhas = [f"Nome: {g('nome')}", f"Empresa: {g('empresa')}", f"CNPJ: {g('cnpj') or '—'}",
              f"E-mail: {g('email') or '—'}", f"WhatsApp: {g('whatsapp') or '—'}"]
    if k == "credito":
        linhas += [f"Finalidade: {g('finalidade')}", f"Valor pedido: R$ {g('valor')}", f"Prazo: {g('prazo')} meses",
                   f"Faturamento informado: R$ {g('faturamento')}", f"Garantias: {g('garantias')}"]
    elif k == "valuation":
        linhas += [f"Setor: {g('setor')}", f"Faturamento anual: {g('faturamento')}", f"EBITDA: {g('ebitda')}",
                   f"Funcionários: {g('funcionarios')}", f"Valuation estimado pela calculadora: {g('valuation')}"]
    return "\n".join(linhas)


def _au_lead_site(cid: int, r, forcar: bool = False) -> int:
    cfg = _au_cfg(r)
    n = 0
    for k, modelo, origem in _AU_LEADS:
        M = globals().get(modelo)
        if M is None:
            continue
        base = int(cfg.get(f"lead_{k}") or 0)
        with _Sess_pr(engine) as s:
            q = _sel_pr(M).where(M.id > base) if not forcar else _sel_pr(M).order_by(M.id.desc()).limit(1)
            novos = s.exec(q.order_by(M.id) if not forcar else q).all()
            itens = [(l.id, _au_lead_texto(k, l), (getattr(l, "empresa", "") or getattr(l, "nome", "") or "").strip()) for l in novos]
        for lid, texto, quem in itens[:5]:
            ref = f"{k}-{lid}" if not forcar else f"manual-{_dt_pr.utcnow().isoformat()}-{k}-{lid}"
            if not _au_reivindicar(cid, "lead_site", ref):
                continue
            pedido = (f"Lead novo pelo {origem}:\n{texto}\n\n"
                      "Conduza assim, com cos_delegar:\n"
                      "1. Passe à Prospecção ('prospeccao'): verificar se já é cliente ou está no CRM, pesquisar a empresa "
                      "na web (porte, setor, notícias, sinais de aperto ou de oportunidade), classificar (Quente, Morno "
                      "ou Fora do perfil) e sugerir a abordagem e a primeira mensagem. Inclua todos os dados do lead.\n"
                      "2. Se vier Quente ou Morno, passe à Propostas ('propostas') um RASCUNHO de proposta para "
                      "revisão (com_gerar_proposta), com a pesquisa e a demanda do lead; honorários como sugestão.\n"
                      "3. Responda com: classificação, resumo da empresa, abordagem sugerida e o que revisar na "
                      "proposta. Ninguém faz contato com o lead: só preparamos para a equipe.")
            _au_disparar(cid, "lead_site", ref, f"Lead do site: {quem or 'sem nome'}", pedido, f"{origem}: {quem}")
            n += 1
        if itens and not forcar:
            cfg[f"lead_{k}"] = max(base, max(i[0] for i in itens[:5]))
    if not forcar and n:
        with _Sess_pr(engine) as s:
            reg_ = _au_reg(s, cid, "lead_site")
            atual = _au_cfg(reg_)
            atual.update({k_: v for k_, v in cfg.items() if k_.startswith("lead_")})
            reg_.config_json = _json_pr.dumps(atual)
            s.add(reg_)
            s.commit()
    if forcar and not n:
        _au_registrar_sem_chamado_simples(cid, "lead_site", "Nenhum lead gravado ainda.")
    return n


# ── Cliente novo ─────────────────────────────────────────────────────────────

def _au_clientes_base(s, cid) -> dict:
    return {"cliente_id": int(s.exec(_sel_pr(_func_pr.coalesce(_func_pr.max(Client.id), 0)).where(Client.company_id == cid)).one() or 0)}


def _au_cliente_novo(cid: int, r, forcar: bool = False) -> int:
    base = int(_au_cfg(r).get("cliente_id") or 0)
    with _Sess_pr(engine) as s:
        q = _sel_pr(Client).where(Client.company_id == cid)
        q = q.where(Client.id > base).order_by(Client.id) if not forcar else q.order_by(Client.id.desc()).limit(1)
        novos = [(c.id, c.name, c.cnpj or "") for c in s.exec(q).all()]
        feitas = set(s.exec(_sel_pr(PredioAutomacaoEvento.ref).where(PredioAutomacaoEvento.company_id == cid,
                                                                     PredioAutomacaoEvento.chave == "cliente_novo")).all())
    n = 0
    for clid, nome, cnpj in novos[:5]:
        ref = f"cliente-{clid}"
        if ref in feitas or not _au_reivindicar(cid, "cliente_novo", ref):
            continue
        pedido = (f"Cliente novo cadastrado: {nome}" + (f", CNPJ {cnpj}" if cnpj else " (sem CNPJ no cadastro)") + ".\n"
                  "Faça o KYC e a checagem de conflito de interesse antes de o escritório seguir com o trabalho:\n"
                  "1. Conflitos (comp_conflitos) com o nome e o CNPJ da empresa e dos sócios que encontrar.\n"
                  "2. Checklist de KYC/PLD (comp_checklist_kyc) e o que já existe de dossiê e SCR (cred_dossies, cred_scr).\n"
                  "3. Pesquisa pública na web: situação cadastral, sócios, processos relevantes, notícias negativas, "
                  "PEP e listas restritivas, citando a fonte.\n"
                  "4. Parecer de aceitação: aprovar, aprovar com ressalvas ou não aceitar, com o motivo, e os documentos "
                  "a pedir ao cliente (proponha a tarefa de coleta, se faltar algo).")
        _au_disparar(cid, "cliente_novo", ref, f"KYC: {nome}", pedido, nome)
        n += 1
    if forcar and not n:
        _au_registrar_sem_chamado_simples(cid, "cliente_novo", "Nenhum cliente novo sem KYC.")
    return n


# ── 4. Contas a pagar da semana ──────────────────────────────────────────────

def _au_contas_pagar(cid: int, r, forcar: bool = False) -> bool:
    agora = _pr_agora_brt()
    if not forcar and (agora.weekday() != 0 or agora.hour < 8):
        return False
    ano, semana, _ = agora.isocalendar()
    ref = f"{ano}-S{semana:02d}" if not forcar else f"manual-{_dt_pr.utcnow().isoformat()}"
    if not _au_reivindicar(cid, "contas_pagar_semanal", ref):
        return False
    pedido = ("Contas a pagar da semana (automático).\n"
              "1. Agenda (cp_agenda, 7 dias): o que vence esta semana por dia, o que está vencido e o total.\n"
              "2. Compare com o caixa previsto (fin_resumo_caixa) e diga se cobre; se faltar, o que pagar primeiro.\n"
              "3. Extrato pendente de conciliação (cp_conciliacao): proponha conciliar só os pares com sugestão única; "
              "liste os que precisam de decisão.\n"
              "Não proponha baixas de pagamento: isso só quando o sócio confirmar que pagou.")
    _au_disparar(cid, "contas_pagar_semanal", ref, f"Contas a pagar — semana {semana}", pedido, f"Semana {semana}/{ano}")
    return True


_AU_RODAR = {"pos_reuniao": _au_pos_reuniao, "faturamento_mensal": _au_faturamento,
             "cobranca_atrasos": _au_cobranca, "contas_pagar_semanal": _au_contas_pagar,
             "briefing_reuniao": _au_briefing, "relatorio_mensal": _au_relatorio,
             "renovacoes": _au_renovacoes, "lead_site": _au_lead_site, "cliente_novo": _au_cliente_novo}
_AU_COM_DIA = {"faturamento_mensal": 1, "relatorio_mensal": 5, "renovacoes": 3}
_AU_AO_LIGAR = {"lead_site": _au_leads_base, "cliente_novo": _au_clientes_base}  # marco inicial: não processa o passado


def _au_ciclo() -> None:
    with _Sess_pr(engine) as s:
        ativas = s.exec(_sel_pr(PredioAutomacao).where(PredioAutomacao.ativo == True)).all()  # noqa: E712
        ativas = [(a.company_id, a.chave, a) for a in ativas]
    for cid, chave, r in ativas:
        fn = _AU_RODAR.get(chave)
        if not fn:
            continue
        try:
            fn(cid, r)
        except Exception as e:
            print(f"[predio_automacoes] {chave}: {e}")


def _au_agendador() -> None:
    _time_pr.sleep(90)
    while True:
        try:
            _au_ciclo()
        except Exception as e:
            print(f"[predio_automacoes] agendador: {e}")
        _time_pr.sleep(120)


_thr_pr.Thread(target=_so_no_lider(_au_agendador), daemon=True, name="predio-automacoes").start()


# ── Follow-up da reunião (proposta de e-mail ao cliente) ─────────────────────

def _au_t_propor_followup(s, cid, reuniao_id, assunto, corpo):
    M = globals().get("Meeting")
    m = s.get(M, int(reuniao_id or 0)) if M is not None else None
    if not m or m.company_id != cid:
        return {"ok": False, "erro": "Reunião não encontrada."}
    c = s.get(Client, m.client_id) if m.client_id else None
    participantes = _au_participantes(s, m.id)
    if not participantes:
        return {"ok": False, "erro": "A reunião não tem participantes com e-mail cadastrados (Reunião › Participantes). "
                                     "Deixe o texto do follow-up no chat e avise o sócio para cadastrar os participantes."}
    destino = ", ".join(e for _, e in participantes)
    if not (assunto or "").strip() or len((corpo or "").strip()) < 40:
        return {"ok": False, "erro": "Assunto e corpo do e-mail são obrigatórios."}
    pend = s.exec(_sel_pr(PredioAcao).where(PredioAcao.company_id == cid, PredioAcao.tipo == "email_followup",
                                            PredioAcao.status == "pendente")).all()
    for p in pend:
        if _json_pr.loads(p.payload_json or "{}").get("reuniao_id") == m.id:
            return {"ok": False, "erro": f"Já existe um follow-up desta reunião aguardando aprovação (#{p.id})."}
    acao = _pr_registrar_proposta(
        s, cid, tipo="email_followup", client_id=c.id if c else None,
        titulo=f"Follow-up da reunião: {m.title or (c.name if c else '#' + str(m.id))}",
        destinatario=destino, assunto=assunto.strip()[:200], corpo=corpo.strip()[:8000],
        payload_json=_json_pr.dumps({"reuniao_id": m.id}))
    return {"ok": True, "proposta_id": acao.id, "status": "aguardando aprovação",
            "destinatarios": [n for n, _ in participantes],
            "observacao": "Vai para os participantes cadastrados na reunião depois que um sócio aprovar (dá para editar antes)."}


def _au_participantes(s, meeting_id: int) -> list:
    """(nome, e-mail) dos participantes cadastrados na reunião."""
    P = globals().get("MeetingParticipante")
    if P is None:
        return []
    import re as _re_au
    out = []
    for nome, email in s.exec(_sel_pr(User.name, User.email).join(P, P.user_id == User.id).where(P.meeting_id == meeting_id)).all():
        e = (email or "").strip()
        if _re_au.fullmatch(r"[^@\s,;]+@[^@\s,;]+\.[^@\s,;]+", e) and e.lower() not in {x.lower() for _, x in out}:
            out.append((nome or e, e))
    return out


def _au_exec_followup(s, acao) -> str:
    import html as _html_au
    corpo_html = ("<div style=\"font-family:Arial,sans-serif;font-size:14px;line-height:1.6;color:#1f2933\">"
                  + _html_au.escape(acao.corpo).replace("\n", "<br>") + "</div>")
    destinos = [e.strip() for e in (acao.destinatario or "").split(",") if e.strip()]
    if not destinos:
        raise _PrErro("Sem destinatários.")
    enviados, falhas = [], []
    for e in destinos:  # um e-mail por participante (sem expor a lista para todos)
        try:
            _smtp_send_email(to_email=e, subject=acao.assunto, html_body=corpo_html, text_body=acao.corpo)
            enviados.append(e)
        except Exception as ex:
            falhas.append(f"{e} ({str(ex)[:60]})")
    if falhas and not enviados:
        raise _PrErro("Falhou para todos: " + "; ".join(falhas))
    return f"Follow-up enviado para {', '.join(enviados)}." + (f" Falhou: {'; '.join(falhas)}." if falhas else "")


_pr_registrar_ferramenta("reu_propor_followup", {
    "fn": _au_t_propor_followup, "rotulo": "Propôs o e-mail de follow-up",
    "description": "Cria uma PROPOSTA de e-mail de follow-up da reunião para os PARTICIPANTES cadastrados nela (um "
                   "e-mail para cada). O sócio revisa, edita e aprova antes do envio.",
    "props": {"reuniao_id": {"type": "integer"}, "assunto": {"type": "string"}, "corpo": {"type": "string"}}})
_PR_EXECUTORES_EXTRA["email_followup"] = _au_exec_followup

_ag_sec = _PREDIO_AGENTES.get("secretario_reunioes")
if _ag_sec and "reu_propor_followup" not in _ag_sec["ferramentas"]:
    _ag_sec["ferramentas"] = _ag_sec["ferramentas"] + ["reu_propor_followup"]
    _PR_INSTRUCOES["secretario_reunioes"] = _PR_INSTRUCOES.get("secretario_reunioes", "") + (
        "\n\nFollow-up: quando o cliente deve receber o resumo, proponha o e-mail com reu_propor_followup (vai para "
        "aprovação). Tarefas combinadas: uma proposta por tarefa, com responsável e prazo.")


# ── Card na home e rotas ─────────────────────────────────────────────────────

def _au_view(company_id: int) -> list:
    out = []
    ini_mes = _pr_agora_brt().replace(day=1, hour=0, minute=0, second=0, microsecond=0) + _td_pr(hours=3)
    with _Sess_pr(engine) as s:
        for chave, d in _AU_DEFS.items():
            r = s.exec(_sel_pr(PredioAutomacao).where(PredioAutomacao.company_id == company_id,
                                                      PredioAutomacao.chave == chave)).first()
            chamados = s.exec(_sel_pr(PredioAutomacaoEvento.chamado_id).where(
                PredioAutomacaoEvento.company_id == company_id, PredioAutomacaoEvento.chave == chave,
                PredioAutomacaoEvento.criado_em >= ini_mes, PredioAutomacaoEvento.chamado_id != None)).all()  # noqa: E711
            n_mes = len(chamados)
            custo = 0.0
            U = globals().get("PredioUso")
            if U is not None and chamados:
                custo = float(s.exec(_sel_pr(_func_pr.coalesce(_func_pr.sum(U.custo_usd), 0)).where(
                    U.chamado_id.in_(chamados))).one() or 0)
            out.append({"chave": chave, "nome": d["nome"], "quando": d["quando"], "faz": d["faz"],
                        "agente": _PREDIO_AGENTES.get(d["agente"], {}).get("nome", d["agente"]),
                        "ativo": bool(r and r.ativo), "com_dia": chave in _AU_COM_DIA,
                        "dia": int(_au_cfg(r).get("dia") or _AU_COM_DIA.get(chave, 1)) if r else _AU_COM_DIA.get(chave, 1),
                        "ultimo": _pr_quando(r.ultimo_em) if r and r.ultimo_em else "",
                        "ultimo_chamado_id": r.ultimo_chamado_id if r else None,
                        "ultimo_resumo": (r.ultimo_resumo if r else "") or "",
                        "execucoes_mes": n_mes, "custo_mes": custo})
    return out


def _au_ctx_ok(request, session):
    ctx = _pr_ctx(request, session)
    return ctx if ctx and ctx.membership.role == "admin" else None


@app.post("/predio/automacoes/{chave}/alternar")
@require_login
async def predio_automacao_alternar(chave: str, request: Request, session: Session = Depends(get_session)):
    ctx = _au_ctx_ok(request, session)
    if ctx and chave in _AU_DEFS:
        r = _au_reg(session, ctx.company.id, chave)
        r.ativo = not r.ativo
        if r.ativo:
            r.ativado_em = _dt_pr.utcnow()
            if chave in _AU_AO_LIGAR:
                cfg = _au_cfg(r)
                cfg.update(_AU_AO_LIGAR[chave](session, ctx.company.id))
                r.config_json = _json_pr.dumps(cfg)
        session.add(r)
        session.commit()
    return RedirectResponse("/predio#automacoes", status_code=303)


@app.post("/predio/automacoes/{chave}/config")
@require_login
async def predio_automacao_config(chave: str, request: Request, session: Session = Depends(get_session)):
    ctx = _au_ctx_ok(request, session)
    if ctx and chave in _AU_COM_DIA:
        form = await request.form()
        try:
            dia = max(1, min(int(str(form.get("dia") or "1")), 28))
        except ValueError:
            dia = 1
        r = _au_reg(session, ctx.company.id, chave)
        cfg = _au_cfg(r)
        cfg["dia"] = dia
        r.config_json = _json_pr.dumps(cfg)
        session.add(r)
        session.commit()
    return RedirectResponse("/predio#automacoes", status_code=303)


@app.post("/predio/automacoes/{chave}/rodar")
@require_login
async def predio_automacao_rodar(chave: str, request: Request, session: Session = Depends(get_session)):
    ctx = _au_ctx_ok(request, session)
    if not ctx or chave not in _AU_RODAR:
        return RedirectResponse("/predio", status_code=303)
    r = _au_reg(session, ctx.company.id, chave)
    from starlette.concurrency import run_in_threadpool as _rtp_au
    await _rtp_au(_AU_RODAR[chave], ctx.company.id, r, True)
    session.refresh(r)
    if r.ultimo_chamado_id and r.ultimo_em and r.ultimo_em > _dt_pr.utcnow() - _td_pr(seconds=30):
        return RedirectResponse(f"/predio/chamados/{r.ultimo_chamado_id}", status_code=303)
    return RedirectResponse("/predio#automacoes", status_code=303)


_AU_CARD = r"""
    {% if automacoes %}
    <div class="card p-3" id="automacoes">
      <h2 class="h6 fw-bold mb-1">Automações</h2>
      <p class="small text-body-secondary mb-3">Os agentes preparam sozinhos e deixam as propostas para você aprovar. Nada é enviado, emitido ou lançado sem o seu clique.</p>
      <div class="d-grid gap-2">
        {% for a in automacoes %}
        <div class="border rounded-3 p-2 px-3">
          <div class="d-flex flex-wrap justify-content-between align-items-start gap-2">
            <div style="min-width:0;flex:1 1 16rem">
              <div class="fw-semibold small">{{ a.nome }} <span class="text-body-secondary fw-normal">· {{ a.agente }}</span></div>
              <div class="small text-body-secondary">{{ a.quando }}{% if a.com_dia %} (dia {{ a.dia }}){% endif %}. {{ a.faz }}</div>
              <div class="small mt-1">
                {% if a.ultimo %}Última: {{ a.ultimo }}{% if a.ultimo_chamado_id %} · <a href="/predio/chamados/{{ a.ultimo_chamado_id }}">ver chamado</a>{% endif %}{% if a.ultimo_resumo %} · {{ a.ultimo_resumo }}{% endif %}{% else %}<span class="text-body-secondary">Ainda não rodou.</span>{% endif %}
                {% if a.execucoes_mes %} · este mês: {{ a.execucoes_mes }}× · US$ {{ ('%.2f'|format(a.custo_mes))|replace('.', ',') }}{% endif %}
              </div>
            </div>
            <div class="d-flex flex-wrap gap-1 align-items-center">
              {% if a.com_dia %}
              <form method="post" action="/predio/automacoes/{{ a.chave }}/config" class="d-flex gap-1 align-items-center">
                <label class="small text-body-secondary" for="auDia{{ loop.index }}">Dia</label>
                <input id="auDia{{ loop.index }}" class="form-control form-control-sm" style="width:4.2rem" type="number" min="1" max="28" name="dia" value="{{ a.dia }}">
                <button class="btn btn-outline-secondary btn-sm" type="submit">OK</button>
              </form>
              {% endif %}
              <form method="post" action="/predio/automacoes/{{ a.chave }}/rodar" onsubmit="this.querySelector('button').disabled=true;">
                <button class="btn btn-outline-primary btn-sm" type="submit">Rodar agora</button>
              </form>
              <form method="post" action="/predio/automacoes/{{ a.chave }}/alternar">
                <button class="btn btn-sm {{ 'btn-success' if a.ativo else 'btn-outline-secondary' }}" type="submit">{{ 'Ligada' if a.ativo else 'Ligar' }}</button>
              </form>
            </div>
          </div>
        </div>
        {% endfor %}
      </div>
    </div>
    {% endif %}
"""

_au_tpl = TEMPLATES.get("predio.html", "")
_au_ancora = "    {% if custos %}\n"
if _au_ancora in _au_tpl and 'id="automacoes"' not in _au_tpl:
    TEMPLATES["predio.html"] = _au_tpl.replace(_au_ancora, _AU_CARD.strip("\n") + "\n" + _au_ancora, 1)
else:
    print("[predio_automacoes] card 'Automações' não inserido (âncora não encontrada)")

print("[predio_automacoes] Automações do prédio carregadas.")

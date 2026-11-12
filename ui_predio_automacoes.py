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


def _au_disparar(cid: int, chave: str, ref: str, titulo: str, pedido: str, resumo: str = "") -> _Opt_pr[int]:
    """Abre o chamado da automação (o evento já foi reivindicado) e registra a execução."""
    _pr_sincronizar_agentes()
    d = _AU_DEFS[chave]
    with _Sess_pr(engine) as s:
        admin = _au_admin(s, cid)
        if not admin or not _pr_pode_usar(_PREDIO_AGENTES.get(d["agente"]), "admin"):
            return None
        ch = PredioChamado(company_id=cid, created_by_user_id=admin, papel_solicitante="admin", titulo=titulo[:200],
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
             "cobranca_atrasos": _au_cobranca, "contas_pagar_semanal": _au_contas_pagar}


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


_thr_pr.Thread(target=_au_agendador, daemon=True, name="predio-automacoes").start()


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
                        "ativo": bool(r and r.ativo), "dia": int(_au_cfg(r).get("dia") or 1) if r else 1,
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
        session.add(r)
        session.commit()
    return RedirectResponse("/predio#automacoes", status_code=303)


@app.post("/predio/automacoes/{chave}/config")
@require_login
async def predio_automacao_config(chave: str, request: Request, session: Session = Depends(get_session)):
    ctx = _au_ctx_ok(request, session)
    if ctx and chave == "faturamento_mensal":
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
              <div class="small text-body-secondary">{{ a.quando }}{% if a.chave == 'faturamento_mensal' %} (dia {{ a.dia }}){% endif %}. {{ a.faz }}</div>
              <div class="small mt-1">
                {% if a.ultimo %}Última: {{ a.ultimo }}{% if a.ultimo_chamado_id %} · <a href="/predio/chamados/{{ a.ultimo_chamado_id }}">ver chamado</a>{% endif %}{% if a.ultimo_resumo %} · {{ a.ultimo_resumo }}{% endif %}{% else %}<span class="text-body-secondary">Ainda não rodou.</span>{% endif %}
                {% if a.execucoes_mes %} · este mês: {{ a.execucoes_mes }}× · US$ {{ ('%.2f'|format(a.custo_mes))|replace('.', ',') }}{% endif %}
              </div>
            </div>
            <div class="d-flex flex-wrap gap-1 align-items-center">
              {% if a.chave == 'faturamento_mensal' %}
              <form method="post" action="/predio/automacoes/{{ a.chave }}/config" class="d-flex gap-1 align-items-center">
                <label class="small text-body-secondary" for="auDia">Dia</label>
                <input id="auDia" class="form-control form-control-sm" style="width:4.2rem" type="number" min="1" max="28" name="dia" value="{{ a.dia }}">
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

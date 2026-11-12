# ============================================================================
# ui_predio_pessoas.py — 8º andar do prédio: Pessoas (RH da equipe E dos agentes)
# ============================================================================
# Exec'd no namespace do app.py, DEPOIS de ui_predio.py e dos demais módulos do
# prédio (usa _pr_*, _PR_TOOLS, rel_gerar_relatorio, conh_*).
#
# AGENTES (só admin)
#   capacidade   — carga da equipe (horas, tarefas abertas e atrasadas) e dos agentes
#                  (chamados, erros, perguntas de continuação, aprovações e rejeições)
#   recrutamento — lê a demanda que o prédio não atende e propõe CONTRATAR agentes novos
#                  (montados com as ferramentas que já existem) ou desligar os sem uso;
#                  para pessoas: descrição de vaga e triagem de currículos
#   treinamento  — aprimora os agentes com LIÇÕES APRENDIDAS tiradas do histórico (erros,
#                  rejeições com motivo, perguntas de continuação), que entram no prompt
#                  do agente; para pessoas: trilhas de onboarding na Educação
#
# Tudo com aprovação de admin. Agentes contratados e lições ficam no banco e são
# carregados em todos os workers (_pr_sincronizar_agentes, a cada 15 s).
#
# ROTINA MENSAL (liga/desliga no card "Pessoas e agentes"): todo dia 1º, a partir das
# 10h, abre um chamado para o Treinamento (revisão dos agentes) e outro para o
# Recrutamento (demanda não atendida).
#
# ROTAS (admin)
#   POST /predio/rh/config                   — liga/desliga a revisão mensal
#   POST /predio/rh/revisao-agora            — roda a revisão agora
#   POST /predio/rh/agentes/{id}/desligar    — desliga um agente contratado
# ============================================================================

import re as _re_rh
import unicodedata as _ud_rh


class PredioAgenteNovo(_SM_pr, table=True):
    """Agente contratado pelo Recrutamento (aprovado por um admin)."""
    __tablename__ = "predio_agente_novo"
    __table_args__ = {"extend_existing": True}
    id: _Opt_pr[int] = _F_pr(default=None, primary_key=True)
    company_id: int = _F_pr(index=True)
    key: str = _F_pr(index=True, unique=True)
    nome: str = _F_pr(default="")
    andar_key: str = _F_pr(default="")
    atribuicoes: str = _F_pr(default="")
    instrucoes: str = _F_pr(default="")
    ferramentas_json: str = _F_pr(default="[]")
    acesso: str = _F_pr(default="admin")  # admin | todos
    web: bool = _F_pr(default=False)
    ativo: bool = _F_pr(default=True, index=True)
    justificativa: str = _F_pr(default="")
    acao_id: _Opt_pr[int] = _F_pr(default=None)
    criado_em: _dt_pr = _F_pr(default_factory=lambda: _dt_pr.utcnow())
    atualizado_em: _dt_pr = _F_pr(default_factory=lambda: _dt_pr.utcnow())


class PredioAgenteLicao(_SM_pr, table=True):
    """Lições aprendidas de um agente (aprovadas por um admin); entram no prompt do agente."""
    __tablename__ = "predio_agente_licao"
    __table_args__ = {"extend_existing": True}
    id: _Opt_pr[int] = _F_pr(default=None, primary_key=True)
    company_id: int = _F_pr(index=True)
    agente_key: str = _F_pr(index=True)
    licoes_json: str = _F_pr(default="[]")
    versao: int = _F_pr(default=0)
    motivo: str = _F_pr(default="")
    historico_json: str = _F_pr(default="[]")  # versões anteriores: [{versao, licoes, em}]
    atualizado_em: _dt_pr = _F_pr(default_factory=lambda: _dt_pr.utcnow())


try:
    _SM_pr.metadata.create_all(engine, tables=[PredioAgenteNovo.__table__, PredioAgenteLicao.__table__], checkfirst=True)
except Exception as _e_rh_tab:
    print(f"[predio_pessoas] create_all: {_e_rh_tab}")


# ── Registro dinâmico: agentes contratados e lições ──────────────────────────

_RH_BASE_ANDARES = _PREDIO_ANDARES          # o prédio "de fábrica", sem contratados
_RH_ESTADO = {"em": 0.0, "assinatura": None}
_RH_LOCK = _thr_pr.Lock()
_RH_TTL_S = 15
_RH_LICOES: dict = {}                        # (company_id, agente_key) -> {"licoes": [...], "versao": n}
_RH_MAX_LICOES = 12
# ferramentas que um agente contratado não recebe (delegação e o próprio RH dos agentes)
_RH_FERRAMENTAS_RESERVADAS = {"cos_delegar", "rh_propor_novo_agente", "rh_propor_desligar_agente", "rh_propor_aprimoramento"}


def _rh_agente_dict(n: PredioAgenteNovo, andar: dict) -> dict:
    try:
        ferramentas = [f for f in _json_pr.loads(n.ferramentas_json or "[]")
                       if f in _PR_TOOLS and f not in _RH_FERRAMENTAS_RESERVADAS]
    except ValueError:
        ferramentas = []
    if n.acesso == "todos":
        equipe = _rh_ferramentas_equipe()
        ferramentas = [f for f in ferramentas if f in equipe]
    return {"key": n.key, "nome": n.nome, "papeis": _PR_TODOS if n.acesso == "todos" else _PR_ADMIN, "ativo": True,
            "atribuicoes": n.atribuicoes, "instrucoes": n.instrucoes, "ferramentas": ferramentas, "web": bool(n.web),
            "andar_key": andar["key"], "andar_nome": andar["nome"], "contratado": True, "contratado_id": n.id,
            "company_id": n.company_id}


def _rh_sincronizar(forcar: bool = False) -> None:
    """Recarrega do banco os agentes contratados e as lições. Barato: roda no máximo a cada 15 s por worker.
    Monta dicionários NOVOS e troca os globais de uma vez (quem estiver iterando o antigo não é afetado)."""
    if not forcar and _time_pr.time() - _RH_ESTADO["em"] < _RH_TTL_S:
        return
    with _RH_LOCK:
        if not forcar and _time_pr.time() - _RH_ESTADO["em"] < _RH_TTL_S:
            return
        try:
            with _Sess_pr(engine) as s:
                novos = s.exec(_sel_pr(PredioAgenteNovo).where(PredioAgenteNovo.ativo == True)  # noqa: E712
                               .order_by(PredioAgenteNovo.id)).all()
                licoes = s.exec(_sel_pr(PredioAgenteLicao)).all()
        except Exception as e:
            print(f"[predio_pessoas] sincronizar: {e}")
            return
        _RH_ESTADO["em"] = _time_pr.time()
        mapa_licoes = {}
        for l in licoes:
            try:
                itens = [str(x) for x in _json_pr.loads(l.licoes_json or "[]")][:_RH_MAX_LICOES]
            except ValueError:
                itens = []
            if itens:
                mapa_licoes[(l.company_id, l.agente_key)] = {"licoes": itens, "versao": l.versao}
        globals()["_RH_LICOES"] = mapa_licoes
        assinatura = tuple((n.id, n.atualizado_em) for n in novos)
        if assinatura == _RH_ESTADO["assinatura"]:
            return
        andares = []
        for base in _RH_BASE_ANDARES:
            andar = dict(base)
            andar["agentes"] = list(base["agentes"]) + [_rh_agente_dict(n, base) for n in novos if n.andar_key == base["key"]]
            andares.append(andar)
        agentes = {a["key"]: a for andar in andares for a in andar["agentes"]}
        globals()["_PREDIO_ANDARES"] = andares
        globals()["_PREDIO_AGENTES"] = agentes
        # o Chief of Staff passa a poder delegar aos contratados
        cos = _PR_TOOLS.get("cos_delegar")
        if cos:
            enum = cos["schema"]["input_schema"]["properties"]["agente"].get("enum")
            if isinstance(enum, list):
                base_enum = [k for k in enum if not k.startswith("ag_")]
                cos["schema"]["input_schema"]["properties"]["agente"]["enum"] = base_enum + [n.key for n in novos]
        _RH_ESTADO["assinatura"] = assinatura


def _rh_licoes_texto(agente_key: str, company_id) -> str:
    item = _RH_LICOES.get((company_id, agente_key))
    if not item:
        return ""
    return ("Lições aprendidas (aprovadas pelos sócios a partir do seu histórico; siga-as):\n"
            + "\n".join(f"- {l}" for l in item["licoes"]) + "\n\n")


_pr_sincronizar_agentes = _rh_sincronizar
_pr_licoes_texto = _rh_licoes_texto


# ── Helpers ───────────────────────────────────────────────────────────────────

def _rh_desde(dias, padrao=30, maximo=365):
    dias = max(1, min(int(dias or padrao), maximo))
    return dias, _dt_pr.utcnow() - _td_pr(days=dias)


def _rh_trecho(texto, n=240) -> str:
    t = " ".join(str(texto or "").split())
    return t if len(t) <= n else t[:n - 1] + "…"


def _rh_slug(nome: str) -> str:
    t = _ud_rh.normalize("NFKD", nome or "").encode("ascii", "ignore").decode().lower()
    return _re_rh.sub(r"[^a-z0-9]+", "_", t).strip("_")[:30]


def _rh_lista_json(valor) -> list:
    try:
        dado = _json_pr.loads(valor or "[]")
        return dado if isinstance(dado, list) else []
    except ValueError:
        return []


# ── Capacidade da equipe ──────────────────────────────────────────────────────

_RH_HORAS_SEMANA_LIMITE = 44


def _rh_t_capacidade_equipe(s, cid, dias):
    dias, desde = _rh_desde(dias, 30, 180)
    hoje = _pr_hoje()
    membros = s.exec(_sel_pr(Membership.user_id, Membership.role).where(
        Membership.company_id == cid, Membership.role.in_(["admin", "equipe"]))).all()
    nomes = _pr_usuarios(s, cid)
    pessoas = {uid: {"pessoa": nomes.get(uid, f"usuário #{uid}"), "papel": papel, "minutos": 0, "clientes": set(),
                     "tarefas_abertas": 0, "atrasadas": 0, "vencem_7_dias": 0} for uid, papel in membros}
    for ws in s.exec(_sel_pr(TaskWorkSession).where(TaskWorkSession.company_id == cid,
                                                    TaskWorkSession.started_at >= desde)).all():
        p = pessoas.get(ws.user_id)
        if p is not None:
            p["minutos"] += _task_work_minutes(ws)
            p["clientes"].add(ws.client_id)
    sem_responsavel = 0
    for uid, due in s.exec(_sel_pr(Task.assignee_user_id, Task.due_date).where(
            Task.company_id == cid, Task.status != "concluida")).all():
        p = pessoas.get(uid)
        if p is None:
            sem_responsavel += 1
            continue
        p["tarefas_abertas"] += 1
        venc = _pr_data(due)
        if venc and venc < hoje:
            p["atrasadas"] += 1
        elif venc and venc <= hoje + _td_pr(days=7):
            p["vencem_7_dias"] += 1
    semanas = max(dias / 7, 1)
    linhas = []
    for p in pessoas.values():
        horas = p["minutos"] / 60
        hs = round(horas / semanas, 1)
        alertas = []
        if hs > _RH_HORAS_SEMANA_LIMITE:
            alertas.append(f"sobrecarga: {hs:g} h/semana apontadas")
        if p["atrasadas"] >= 3:
            alertas.append(f"{p['atrasadas']} tarefas atrasadas")
        if p["tarefas_abertas"] >= 15:
            alertas.append(f"{p['tarefas_abertas']} tarefas abertas")
        linhas.append({"pessoa": p["pessoa"], "papel": p["papel"], "horas_apontadas": round(horas, 1), "horas_por_semana": hs,
                       "clientes_atendidos": len(p["clientes"]), "tarefas_abertas": p["tarefas_abertas"],
                       "atrasadas": p["atrasadas"], "vencem_7_dias": p["vencem_7_dias"], "alertas": alertas})
    linhas.sort(key=lambda x: (-len(x["alertas"]), -x["horas_por_semana"]))
    return {"periodo_dias": dias, "pessoas": linhas, "tarefas_abertas_sem_responsavel": sem_responsavel,
            "observacao": "Horas vêm do apontamento em tarefas (quem não aponta aparece com 0 h). "
                          f"Sobrecarga = acima de {_RH_HORAS_SEMANA_LIMITE} h/semana apontadas."}


# ── Desempenho dos agentes ────────────────────────────────────────────────────

def _rh_chamados(s, cid, desde, agente_key=None, limite=None):
    C = PredioChamado
    q = _sel_pr(C.id, C.agente_key, C.status, C.tipo, C.titulo, C.pedido, C.erro, C.created_at, C.concluido_em,
                C.conversa_json, C.passos_json, C.roteamento, C.motivo_roteamento, C.resultado
                ).where(C.company_id == cid, C.created_at >= desde)
    if agente_key:
        q = q.where(C.agente_key == agente_key)
    q = q.order_by(C.created_at.desc())
    if limite:
        q = q.limit(limite)
    return s.exec(q).all()


def _rh_t_desempenho_agentes(s, cid, dias):
    _rh_sincronizar()
    dias, desde = _rh_desde(dias, 30, 180)
    stats = {}

    def st(key):
        return stats.setdefault(key, {"chamados": 0, "concluidos": 0, "erros": 0, "minutos": [], "continuacoes": 0,
                                      "falhas_ferramenta": 0, "delegacoes_recebidas": 0, "reunioes": 0,
                                      "propostas": {"total": 0, "executadas": 0, "rejeitadas": 0, "falharam": 0, "pendentes": 0}})

    sem_agente = 0
    for row in _rh_chamados(s, cid, desde):
        if row.status == "sem_agente":
            sem_agente += 1
            continue
        if row.tipo == "reuniao":
            st(row.agente_key or "chief_of_staff")["reunioes"] += 1
        if row.agente_key:
            x = st(row.agente_key)
            x["chamados"] += 1
            x["concluidos"] += row.status == "concluido"
            x["erros"] += row.status == "erro"
            x["continuacoes"] += len(_rh_lista_json(row.conversa_json))
            if row.concluido_em and row.created_at and row.status == "concluido":
                x["minutos"].append((row.concluido_em - row.created_at).total_seconds() / 60)
        delegados = set()
        for p in _rh_lista_json(row.passos_json):
            if not isinstance(p, dict):
                continue
            autor = p.get("autor") or row.agente_key
            if autor and not p.get("ok", True):
                st(autor)["falhas_ferramenta"] += 1
            if autor and autor != row.agente_key and row.tipo != "reuniao":
                delegados.add(autor)
        for d in delegados:
            st(d)["delegacoes_recebidas"] += 1
    for key, status, n in s.exec(_sel_pr(PredioAcao.agente_key, PredioAcao.status, _func_pr.count(PredioAcao.id))
                                 .where(PredioAcao.company_id == cid, PredioAcao.criado_em >= desde)
                                 .group_by(PredioAcao.agente_key, PredioAcao.status)).all():
        if not key:
            continue
        pr = st(key)["propostas"]
        pr["total"] += n
        campo = {"executada": "executadas", "rejeitada": "rejeitadas", "erro": "falharam", "pendente": "pendentes"}.get(status)
        if campo:
            pr[campo] += n
    linhas, sem_uso = [], []
    for a in _PREDIO_AGENTES.values():
        if a["key"] == "recepcionista" or not a.get("ativo"):
            continue
        x = stats.get(a["key"])
        if not x or (x["chamados"] + x["delegacoes_recebidas"] + x["reunioes"] + x["propostas"]["total"]) == 0:
            sem_uso.append({"agente": a["key"], "nome": a["nome"], "andar": a["andar_nome"], "contratado": bool(a.get("contratado"))})
            continue
        pr = x["propostas"]
        decididas = pr["executadas"] + pr["rejeitadas"]
        sinais = []
        if x["chamados"] >= 3 and x["erros"] / x["chamados"] >= 0.2:
            sinais.append("muitos erros")
        if decididas >= 3 and pr["rejeitadas"] / decididas >= 0.3:
            sinais.append("propostas muito rejeitadas")
        if x["chamados"] >= 3 and x["continuacoes"] / x["chamados"] >= 1.5:
            sinais.append("respostas pedem muitas perguntas de continuação")
        if x["falhas_ferramenta"] >= 5:
            sinais.append("ferramentas falhando")
        if pr["pendentes"] >= 5:
            sinais.append("propostas acumuladas sem decisão")
        lic = _RH_LICOES.get((cid, a["key"]))
        mins = x["minutos"]
        linhas.append({"agente": a["key"], "nome": a["nome"], "andar": a["andar_nome"], "contratado": bool(a.get("contratado")),
                       "chamados": x["chamados"], "concluidos": x["concluidos"], "erros": x["erros"],
                       "delegacoes_recebidas": x["delegacoes_recebidas"], "reunioes_conduzidas": x["reunioes"],
                       "perguntas_de_continuacao": x["continuacoes"], "falhas_de_ferramenta": x["falhas_ferramenta"],
                       "duracao_media_min": round(sum(mins) / len(mins), 1) if mins else None,
                       "propostas": pr, "taxa_aprovacao_pct": round(pr["executadas"] / decididas * 100, 1) if decididas else None,
                       "licoes_versao": lic["versao"] if lic else 0, "sinais": sinais})
    linhas.sort(key=lambda x: (-len(x["sinais"]), -x["chamados"]))
    inativos = [{"agente": a["key"], "nome": a["nome"], "andar": a["andar_nome"]} for a in _PREDIO_AGENTES.values()
                if not a.get("ativo")]
    return {"periodo_dias": dias, "agentes": linhas, "ativos_sem_uso": sem_uso, "agentes_inativos": inativos,
            "chamados_sem_agente": sem_agente,
            "observacao": "Continuações = perguntas feitas depois da primeira resposta (sinal de resposta incompleta "
                          "ou de conversa produtiva: confira com rh_historico_agente)."}


def _rh_resolver_agente(agente: str):
    _rh_sincronizar()
    a = _PREDIO_AGENTES.get((agente or "").strip())
    if a:
        return a
    alvo = _pr_norm(agente)
    return next((x for x in _PREDIO_AGENTES.values() if _pr_norm(x["nome"]) == alvo), None)


def _rh_t_historico_agente(s, cid, agente, dias):
    a = _rh_resolver_agente(agente)
    if not a:
        return {"erro": f"Agente '{agente}' não encontrado. Use a chave de rh_desempenho_agentes."}
    dias, desde = _rh_desde(dias, 60, 365)
    chamados = []
    for row in _rh_chamados(s, cid, desde, a["key"], 15):
        falhas = [_rh_trecho(p.get("rotulo") or p.get("ferramenta"), 120) for p in _rh_lista_json(row.passos_json)
                  if isinstance(p, dict) and not p.get("ok", True) and (p.get("autor") or row.agente_key) == a["key"]]
        conversa = _rh_lista_json(row.conversa_json)
        chamados.append({"chamado_id": row.id, "data": _pr_fmt_data(row.created_at.date()) if row.created_at else "",
                         "pedido": _rh_trecho(row.titulo or row.pedido, 300), "status": row.status,
                         "erro": _rh_trecho(row.erro, 300), "falhas_de_ferramenta": falhas[:6],
                         "perguntas_de_continuacao": [_rh_trecho(c.get("pergunta"), 200) for c in conversa if isinstance(c, dict)][:6],
                         "inicio_da_resposta": _rh_trecho(row.resultado, 400)})
    A = PredioAcao
    propostas = [{"proposta_id": x.id, "tipo": x.tipo, "titulo": _rh_trecho(x.titulo, 150), "status": x.status,
                  "corpo": _rh_trecho(x.corpo, 300), "resultado_ou_motivo": _rh_trecho(x.resultado, 300)}
                 for x in s.exec(_sel_pr(A).where(A.company_id == cid, A.agente_key == a["key"], A.criado_em >= desde,
                                                  A.status.in_(["rejeitada", "erro"])).order_by(A.criado_em.desc()).limit(15)).all()]
    reg = s.exec(_sel_pr(PredioAgenteLicao).where(PredioAgenteLicao.company_id == cid,
                                                  PredioAgenteLicao.agente_key == a["key"])).first()
    return {"agente": a["key"], "nome": a["nome"], "andar": a["andar_nome"], "atribuicoes": a["atribuicoes"],
            "instrucoes_atuais": _rh_trecho(_PR_INSTRUCOES.get(a["key"]) or a.get("instrucoes", ""), 3000),
            "ferramentas": a.get("ferramentas", []), "web": bool(a.get("web")),
            "licoes_atuais": _rh_lista_json(reg.licoes_json) if reg else [], "licoes_versao": reg.versao if reg else 0,
            "chamados_recentes": chamados, "propostas_rejeitadas_ou_falhas": propostas}


# ── Treinamento: lições aprendidas ───────────────────────────────────────────

def _rh_t_propor_aprimoramento(s, cid, agente, licoes, motivo):
    a = _rh_resolver_agente(agente)
    if not a or a["key"] == "recepcionista":
        return {"ok": False, "erro": f"Agente '{agente}' não encontrado."}
    itens = []
    for l in licoes or []:
        t = " ".join(str(l or "").split())
        if 10 <= len(t) <= 400 and t not in itens:
            itens.append(t)
    if not itens:
        return {"ok": False, "erro": "Escreva de 1 a 12 lições objetivas (10 a 400 caracteres cada)."}
    if len(itens) > _RH_MAX_LICOES:
        return {"ok": False, "erro": f"No máximo {_RH_MAX_LICOES} lições: consolide as mais importantes."}
    if len((motivo or "").strip()) < 10:
        return {"ok": False, "erro": "Explique o motivo (o que no histórico pede essas lições)."}
    reg = s.exec(_sel_pr(PredioAgenteLicao).where(PredioAgenteLicao.company_id == cid,
                                                  PredioAgenteLicao.agente_key == a["key"])).first()
    atuais = _rh_lista_json(reg.licoes_json) if reg else []
    removidas = [l for l in atuais if l not in itens]
    corpo = (f"Motivo: {motivo.strip()[:1000]}\n\nLições (versão {(reg.versao if reg else 0) + 1}, substituem as atuais):\n"
             + "\n".join(f"• {l}" for l in itens)
             + ("\n\nSaem:\n" + "\n".join(f"• {l}" for l in removidas) if removidas else ""))
    acao = _pr_registrar_proposta(
        s, cid, tipo="aprimorar_agente", titulo=f"Treinamento: {len(itens)} lição(ões) para {a['nome']}",
        destinatario=f"Agente {a['nome']} ({a['andar_nome']})", assunto=a["nome"], corpo=corpo,
        payload_json=_json_pr.dumps({"agente": a["key"], "licoes": itens, "motivo": motivo.strip()[:1000]}, ensure_ascii=False))
    return {"ok": True, "proposta_id": acao.id, "status": "aguardando aprovação", "licoes": len(itens),
            "removidas": len(removidas)}


def _rh_exec_aprimorar(s, acao) -> str:
    p = _json_pr.loads(acao.payload_json or "{}")
    reg = s.exec(_sel_pr(PredioAgenteLicao).where(PredioAgenteLicao.company_id == acao.company_id,
                                                  PredioAgenteLicao.agente_key == p["agente"])).first()
    if not reg:
        reg = PredioAgenteLicao(company_id=acao.company_id, agente_key=p["agente"])
    hist = _rh_lista_json(reg.historico_json)
    if reg.versao:
        hist = (hist + [{"versao": reg.versao, "licoes": _rh_lista_json(reg.licoes_json),
                         "em": reg.atualizado_em.isoformat() if reg.atualizado_em else ""}])[-10:]
    reg.historico_json = _json_pr.dumps(hist, ensure_ascii=False)
    reg.licoes_json = _json_pr.dumps(p["licoes"][:_RH_MAX_LICOES], ensure_ascii=False)
    reg.versao = (reg.versao or 0) + 1
    reg.motivo = p.get("motivo", "")
    reg.atualizado_em = _dt_pr.utcnow()
    s.add(reg)
    s.commit()
    _rh_sincronizar(forcar=True)
    nome = _PREDIO_AGENTES.get(p["agente"], {}).get("nome", p["agente"])
    return f"{nome} treinado: versão {reg.versao} com {len(p['licoes'])} lição(ões), já valendo nos próximos chamados."


# ── Recrutamento: demanda e contratação de agentes ───────────────────────────

def _rh_t_demanda(s, cid, dias):
    _rh_sincronizar()
    dias, desde = _rh_desde(dias, 60, 365)
    nao_atendidos, com_erro, por_agente, recentes = [], [], {}, []
    for row in _rh_chamados(s, cid, desde):
        if row.status == "sem_agente":
            nao_atendidos.append({"data": _pr_fmt_data(row.created_at.date()), "pedido": _rh_trecho(row.pedido, 260),
                                  "recepcao": _rh_trecho(row.resultado or row.motivo_roteamento, 200)})
            continue
        if row.agente_key:
            por_agente[row.agente_key] = por_agente.get(row.agente_key, 0) + 1
        if row.status == "erro":
            com_erro.append({"agente": row.agente_key, "pedido": _rh_trecho(row.pedido, 200), "erro": _rh_trecho(row.erro, 200)})
        if len(recentes) < 40:
            recentes.append({"agente": row.agente_key, "pedido": _rh_trecho(row.titulo or row.pedido, 160),
                             "via": row.roteamento})
    nomes = {k: a["nome"] for k, a in _PREDIO_AGENTES.items()}
    return {"periodo_dias": dias,
            "nao_atendidos": nao_atendidos[:30], "total_nao_atendidos": len(nao_atendidos),
            "com_erro": com_erro[:15],
            "volume_por_agente": sorted([{"agente": k, "nome": nomes.get(k, k), "chamados": n} for k, n in por_agente.items()],
                                        key=lambda x: -x["chamados"]),
            "pedidos_recentes": recentes,
            "agentes_inativos": [{"agente": a["key"], "nome": a["nome"], "andar": a["andar_nome"], "atribuicoes": a["atribuicoes"]}
                                 for a in _PREDIO_AGENTES.values() if not a.get("ativo")],
            "observacao": "Não atendidos = a Recepção não achou agente ativo. Procure temas que se repetem."}


def _rh_t_catalogo_ferramentas(s, cid):
    _rh_sincronizar()
    uso, equipe = {}, _rh_ferramentas_equipe()
    for a in _PREDIO_AGENTES.values():
        for f in a.get("ferramentas", []):
            uso.setdefault(f, []).append(a["nome"])
    itens = []
    for nome, spec in sorted(_PR_TOOLS.items()):
        if nome in _RH_FERRAMENTAS_RESERVADAS:
            continue
        desc = spec["schema"].get("description", "")
        itens.append({"ferramenta": nome, "faz": _rh_trecho(desc, 200),
                      "proposta_com_aprovacao": "_propor" in nome or "PROPOSTA" in desc,
                      "aberta_a_equipe": nome in equipe, "usada_por": uso.get(nome, [])[:6]})
    return {"ferramentas": itens, "andares": [{"andar": a["key"], "nome": a["nome"], "rotulo": a["rotulo"]} for a in _RH_BASE_ANDARES],
            "observacao": "Um agente novo é montado só com estas ferramentas (mais pesquisa na web, se fizer sentido). "
                          "Agente com acesso 'todos' (equipe) só pode receber ferramentas com aberta_a_equipe = true. "
                          "Se a demanda exige uma ferramenta que não existe, diga isso: é trabalho de desenvolvimento."}


def _rh_ferramentas_equipe() -> set:
    """Ferramentas que já são expostas à equipe por algum agente de fábrica: as únicas que um agente contratado
    com acesso 'todos' pode receber (financeiro, faturamento, RH etc. continuam só admin)."""
    return {f for andar in _RH_BASE_ANDARES for a in andar["agentes"] if a["papeis"] != _PR_ADMIN for f in a.get("ferramentas", [])}


def _rh_t_propor_novo_agente(s, cid, nome, andar, atribuicoes, instrucoes, ferramentas, acesso, web, justificativa):
    _rh_sincronizar()
    nome = " ".join((nome or "").split())[:60]
    if len(nome) < 3:
        return {"ok": False, "erro": "Dê um nome ao agente (ex.: Analista de Imóveis)."}
    if any(_pr_norm(a["nome"]) == _pr_norm(nome) for a in _PREDIO_AGENTES.values()):
        return {"ok": False, "erro": f"Já existe um agente chamado {nome}: aprimore-o em vez de contratar outro."}
    base = next((x for x in _RH_BASE_ANDARES if x["key"] == andar), None)
    if not base:
        return {"ok": False, "erro": "Andar inválido (use a chave de rh_catalogo_ferramentas)."}
    atribuicoes = " ".join((atribuicoes or "").split())
    if not 10 <= len(atribuicoes) <= 300:
        return {"ok": False, "erro": "Atribuições: uma frase de 10 a 300 caracteres."}
    instrucoes = (instrucoes or "").strip()
    if not 80 <= len(instrucoes) <= 5000:
        return {"ok": False, "erro": "Instruções de trabalho: de 80 a 5.000 caracteres (como o agente deve trabalhar)."}
    pedidas = [str(f).strip() for f in (ferramentas or []) if str(f).strip()]
    invalidas = [f for f in pedidas if f not in _PR_TOOLS or f in _RH_FERRAMENTAS_RESERVADAS]
    if invalidas:
        return {"ok": False, "erro": f"Ferramentas inexistentes ou reservadas: {', '.join(invalidas)}. Use rh_catalogo_ferramentas."}
    pedidas = list(dict.fromkeys(pedidas))[:20]
    if acesso == "todos":
        so_admin = [f for f in pedidas if f not in _rh_ferramentas_equipe()]
        if so_admin:
            return {"ok": False, "erro": f"Ferramentas só de admin num agente aberto à equipe: {', '.join(so_admin)}. "
                                         "Tire-as ou use acesso 'admin'."}
    if not pedidas and not web:
        return {"ok": False, "erro": "O agente precisa de pelo menos uma ferramenta ou de pesquisa na web."}
    if len((justificativa or "").strip()) < 20:
        return {"ok": False, "erro": "Justifique com a demanda observada (pedidos, volume, gargalo)."}
    key = "ag_" + (_rh_slug(nome) or "agente")
    existentes = set(_PREDIO_AGENTES) | set(s.exec(_sel_pr(PredioAgenteNovo.key)).all())
    sufixo = 2
    while key in existentes:
        key = f"ag_{_rh_slug(nome)[:26]}_{sufixo}"
        sufixo += 1
    payload = {"key": key, "nome": nome, "andar": base["key"], "atribuicoes": atribuicoes, "instrucoes": instrucoes,
               "ferramentas": pedidas, "acesso": "todos" if acesso == "todos" else "admin", "web": bool(web),
               "justificativa": justificativa.strip()[:2000]}
    corpo = (f"Por quê: {payload['justificativa']}\n\nAtribuições: {atribuicoes}\n"
             f"Acesso: {'admin e equipe' if payload['acesso'] == 'todos' else 'só admin'} · "
             f"pesquisa na web: {'sim' if web else 'não'}\nFerramentas: {', '.join(pedidas) or '—'}\n\n"
             f"Instruções de trabalho:\n{instrucoes}")
    acao = _pr_registrar_proposta(
        s, cid, tipo="contratar_agente", titulo=f"Contratar agente: {nome} ({base['rotulo']})",
        destinatario=f"{base['rotulo']} — {base['nome']}", assunto=nome, corpo=corpo,
        payload_json=_json_pr.dumps(payload, ensure_ascii=False))
    return {"ok": True, "proposta_id": acao.id, "status": "aguardando aprovação", "chave": key}


def _rh_exec_contratar(s, acao) -> str:
    p = _json_pr.loads(acao.payload_json or "{}")
    if s.exec(_sel_pr(PredioAgenteNovo).where(PredioAgenteNovo.key == p["key"])).first():
        raise ValueError("Esse agente já foi contratado.")
    if p["key"] in _PREDIO_AGENTES:
        raise ValueError("Já existe um agente com essa chave.")
    n = PredioAgenteNovo(company_id=acao.company_id, key=p["key"], nome=p["nome"], andar_key=p["andar"],
                         atribuicoes=p["atribuicoes"], instrucoes=p["instrucoes"],
                         ferramentas_json=_json_pr.dumps(p["ferramentas"]), acesso=p["acesso"], web=p["web"],
                         justificativa=p["justificativa"], acao_id=acao.id)
    s.add(n)
    s.commit()
    _rh_sincronizar(forcar=True)
    andar = next((a for a in _RH_BASE_ANDARES if a["key"] == p["andar"]), {"rotulo": "", "nome": ""})
    return f"{p['nome']} contratado no {andar['rotulo']} ({andar['nome']}): já aparece no prédio e recebe chamados."


def _rh_t_propor_desligar(s, cid, agente, motivo):
    a = _rh_resolver_agente(agente)
    if not a or not a.get("contratado"):
        return {"ok": False, "erro": "Só agentes contratados pelo Recrutamento podem ser desligados (os de fábrica, não)."}
    if len((motivo or "").strip()) < 10:
        return {"ok": False, "erro": "Explique o motivo."}
    acao = _pr_registrar_proposta(
        s, cid, tipo="desligar_agente", titulo=f"Desligar agente: {a['nome']}", destinatario=f"Agente {a['nome']} ({a['andar_nome']})",
        assunto=a["nome"], corpo=f"Motivo: {motivo.strip()[:1000]}",
        payload_json=_json_pr.dumps({"id": a["contratado_id"], "agente": a["key"]}))
    return {"ok": True, "proposta_id": acao.id}


def _rh_desligar(s, company_id: int, agente_id: int) -> str:
    n = s.get(PredioAgenteNovo, int(agente_id))
    if not n or n.company_id != company_id:
        raise ValueError("Agente não encontrado.")
    if not n.ativo:
        return f"{n.nome} já estava desligado."
    n.ativo, n.atualizado_em = False, _dt_pr.utcnow()
    s.add(n)
    s.commit()
    _rh_sincronizar(forcar=True)
    return f"{n.nome} desligado: sai do prédio (o histórico dos chamados fica)."


def _rh_exec_desligar(s, acao) -> str:
    return _rh_desligar(s, acao.company_id, _json_pr.loads(acao.payload_json or "{}")["id"])


# ── Pessoas: trilhas de onboarding na Educação ───────────────────────────────

def _rh_t_trilhas(s, cid):
    C, M, L = EducationCourse, EducationModule, EducationLesson
    out = []
    for c in s.exec(_sel_pr(C).where(C.company_id == cid).order_by(C.category, C.title)).all():
        mods = s.exec(_sel_pr(M).where(M.course_id == c.id).order_by(M.order)).all()
        aulas = {m.id: s.exec(_sel_pr(L.title).where(L.module_id == m.id).order_by(L.order)).all() for m in mods}
        out.append({"trilha": c.title, "categoria": c.category, "ativa": c.is_active, "descricao": _rh_trecho(c.description, 200),
                    "modulos": [{"modulo": m.title, "aulas": aulas[m.id][:20]} for m in mods]})
    return {"trilhas": out, "total": len(out)}


def _rh_t_propor_trilha(s, cid, titulo, categoria, descricao, modulos):
    titulo = " ".join((titulo or "").split())[:150]
    if len(titulo) < 5:
        return {"ok": False, "erro": "Dê um título à trilha."}
    if s.exec(_sel_pr(EducationCourse).where(EducationCourse.company_id == cid, EducationCourse.title == titulo)).first():
        return {"ok": False, "erro": "Já existe uma trilha com esse título."}
    mods = []
    for m in modulos or []:
        if not isinstance(m, dict) or len((m.get("titulo") or "").strip()) < 3:
            continue
        aulas = [{"titulo": a["titulo"].strip()[:200], "descricao": (a.get("descricao") or "").strip()[:4000],
                  "video_url": (a.get("video_url") or "").strip()[:500] if str(a.get("video_url") or "").startswith("http") else ""}
                 for a in (m.get("aulas") or []) if isinstance(a, dict) and len((a.get("titulo") or "").strip()) >= 3][:20]
        if aulas:
            mods.append({"titulo": m["titulo"].strip()[:200], "descricao": (m.get("descricao") or "").strip()[:1000], "aulas": aulas})
    if not mods:
        return {"ok": False, "erro": "A trilha precisa de pelo menos um módulo com aulas."}
    mods = mods[:12]
    corpo = (f"{(descricao or '').strip()[:1000]}\n\n" + "\n".join(
        f"{i}. {m['titulo']}\n" + "\n".join(f"   • {a['titulo']}" for a in m["aulas"]) for i, m in enumerate(mods, 1)))
    acao = _pr_registrar_proposta(
        s, cid, tipo="criar_trilha", titulo=f"Trilha na Educação: {titulo}", destinatario="Educação (cursos do escritório)",
        assunto=titulo, corpo=corpo, payload_json=_json_pr.dumps(
            {"titulo": titulo, "categoria": (categoria or "Onboarding").strip()[:60], "descricao": (descricao or "").strip()[:2000],
             "modulos": mods}, ensure_ascii=False))
    return {"ok": True, "proposta_id": acao.id, "modulos": len(mods), "aulas": sum(len(m["aulas"]) for m in mods)}


def _rh_exec_trilha(s, acao) -> str:
    p = _json_pr.loads(acao.payload_json or "{}")
    if s.exec(_sel_pr(EducationCourse).where(EducationCourse.company_id == acao.company_id,
                                             EducationCourse.title == p["titulo"])).first():
        raise ValueError("Já existe uma trilha com esse título.")
    autor = acao.decidido_por_user_id or s.exec(_sel_pr(Membership.user_id).where(
        Membership.company_id == acao.company_id, Membership.role == "admin")).first()
    c = EducationCourse(company_id=acao.company_id, created_by_user_id=autor, title=p["titulo"], category=p["categoria"],
                        description=p["descricao"])
    s.add(c)
    s.commit()
    s.refresh(c)
    aulas = 0
    for i, m in enumerate(p["modulos"], 1):
        mod = EducationModule(course_id=c.id, title=m["titulo"], order=i, description=m["descricao"])
        s.add(mod)
        s.commit()
        s.refresh(mod)
        for j, a in enumerate(m["aulas"], 1):
            s.add(EducationLesson(module_id=mod.id, title=a["titulo"], order=j, description=a["descricao"], video_url=a["video_url"]))
            aulas += 1
        s.commit()
    return f"Trilha '{c.title}' criada na Educação: {len(p['modulos'])} módulo(s), {aulas} aula(s). Libere o acesso por cliente lá."


# ── Registro das ferramentas e agentes ───────────────────────────────────────

_RH_S = {"type": "string"}
_RH_DIAS = {"dias": {"type": "integer", "description": "Janela em dias (padrão 30)."}}
_RH_FERRAMENTAS = {
    "rh_capacidade_equipe": {
        "fn": _rh_t_capacidade_equipe, "rotulo": "Mediu a carga da equipe",
        "description": "Carga de cada pessoa da equipe na janela: horas apontadas (total e por semana), clientes atendidos, "
                       "tarefas abertas, atrasadas e que vencem em 7 dias, com alertas de sobrecarga; e tarefas sem responsável.",
        "props": _RH_DIAS},
    "rh_desempenho_agentes": {
        "fn": _rh_t_desempenho_agentes, "rotulo": "Avaliou o desempenho dos agentes",
        "description": "Desempenho de cada agente do prédio na janela: chamados, erros, duração média, perguntas de "
                       "continuação, falhas de ferramenta, delegações recebidas, propostas (executadas, rejeitadas, "
                       "falhas, pendentes) e taxa de aprovação, com sinais de alerta; agentes ativos sem uso, inativos e "
                       "chamados que ficaram sem agente.",
        "props": _RH_DIAS},
    "rh_historico_agente": {
        "fn": _rh_t_historico_agente, "rotulo": "Leu o histórico de um agente",
        "description": "Histórico de UM agente para treinamento: instruções e lições atuais, ferramentas, chamados recentes "
                       "(pedido, status, erro, falhas de ferramenta, perguntas de continuação, início da resposta) e "
                       "propostas rejeitadas (com o motivo dado pelo sócio) ou que falharam.",
        "props": {"agente": {"type": "string", "description": "Chave do agente (ex.: controller)."},
                  "dias": {"type": "integer", "description": "Padrão 60."}}},
    "rh_propor_aprimoramento": {
        "fn": _rh_t_propor_aprimoramento, "rotulo": "Propôs lições para um agente",
        "description": "Cria uma PROPOSTA de treinamento: a lista COMPLETA de lições aprendidas do agente (substitui a "
                       "atual; repita as que continuam valendo). Depois de aprovada, entra no prompt do agente.",
        "props": {"agente": _RH_S, "licoes": {"type": "array", "items": _RH_S, "description": "1 a 12 regras curtas e acionáveis."},
                  "motivo": {"type": "string", "description": "O que no histórico pede essas lições (cite chamados)."}}},
    "rh_demanda": {
        "fn": _rh_t_demanda, "rotulo": "Levantou a demanda do prédio",
        "description": "Demanda do prédio na janela: pedidos que ficaram sem agente (com o que a Recepção disse), chamados "
                       "com erro, volume por agente, pedidos recentes e agentes ainda inativos.",
        "props": {"dias": {"type": "integer", "description": "Padrão 60."}}},
    "rh_catalogo_ferramentas": {
        "fn": _rh_t_catalogo_ferramentas, "rotulo": "Consultou as ferramentas disponíveis",
        "description": "Ferramentas que existem no prédio (o que cada uma faz e quem já usa) e os andares, para montar um "
                       "agente novo.",
        "props": {}},
    "rh_propor_novo_agente": {
        "fn": _rh_t_propor_novo_agente, "rotulo": "Propôs contratar um agente",
        "description": "Cria uma PROPOSTA de contratação de um agente novo, montado com ferramentas existentes. Depois de "
                       "aprovada, o agente aparece no andar e passa a receber chamados.",
        "props": {"nome": _RH_S, "andar": {"type": "string", "description": "Chave do andar (rh_catalogo_ferramentas)."},
                  "atribuicoes": {"type": "string", "description": "Uma frase: o que ele faz."},
                  "instrucoes": {"type": "string", "description": "Como trabalhar: passos, critérios, formato da entrega."},
                  "ferramentas": {"type": "array", "items": _RH_S},
                  "acesso": {"type": "string", "enum": ["admin", "todos"]},
                  "web": {"type": "boolean", "description": "Pesquisa na web."},
                  "justificativa": {"type": "string", "description": "Demanda observada que justifica a contratação."}}},
    "rh_propor_desligar_agente": {
        "fn": _rh_t_propor_desligar, "rotulo": "Propôs desligar um agente",
        "description": "Cria uma PROPOSTA de desligamento de um agente contratado (sem uso ou substituído).",
        "props": {"agente": _RH_S, "motivo": _RH_S}},
    "rh_trilhas": {
        "fn": _rh_t_trilhas, "rotulo": "Consultou as trilhas da Educação",
        "description": "Trilhas (cursos) que já existem na Educação, com módulos e aulas.",
        "props": {}},
    "rh_propor_trilha": {
        "fn": _rh_t_propor_trilha, "rotulo": "Propôs uma trilha na Educação",
        "description": "Cria uma PROPOSTA de trilha na Educação (ex.: onboarding de consultor), com módulos e aulas.",
        "props": {"titulo": _RH_S, "categoria": {"type": "string", "description": "Ex.: Onboarding."}, "descricao": _RH_S,
                  "modulos": {"type": "array", "items": {
                      "type": "object", "additionalProperties": False, "required": ["titulo", "descricao", "aulas"],
                      "properties": {"titulo": _RH_S, "descricao": _RH_S, "aulas": {"type": "array", "items": {
                          "type": "object", "additionalProperties": False, "required": ["titulo", "descricao", "video_url"],
                          "properties": {"titulo": _RH_S, "descricao": {"type": "string", "description": "Conteúdo da aula."},
                                         "video_url": {"type": "string", "description": "Link do vídeo ou vazio."}}}}}}}}},
}

for _nome_rh, _spec_rh in _RH_FERRAMENTAS.items():
    _pr_registrar_ferramenta(_nome_rh, _spec_rh)

_PR_EXECUTORES_EXTRA.update({"aprimorar_agente": _rh_exec_aprimorar, "contratar_agente": _rh_exec_contratar,
                             "desligar_agente": _rh_exec_desligar, "criar_trilha": _rh_exec_trilha})

_RH_AGENTES = {
    "capacidade": {
        "ferramentas": ["rh_capacidade_equipe", "rh_desempenho_agentes", "fin_horas_vs_receita", "ops_tarefas_atrasadas",
                        "fin_contratos", "rel_gerar_relatorio"],
        "instrucoes": (
            "Você cuida da capacidade do escritório, que tem duas forças de trabalho: as pessoas e os agentes.\n"
            "- Pessoas: rh_capacidade_equipe (carga, atrasos, sobrecarga) e fin_horas_vs_receita (clientes que consomem "
            "muitas horas para o que pagam). Aponte quem está sobrecarregado e quem tem folga, e sugira redistribuir.\n"
            "- Agentes: rh_desempenho_agentes. Veja quais agentes concentram demanda, quais erram, quais têm propostas "
            "paradas sem decisão (gargalo de aprovação dos sócios) e quais nunca são usados.\n"
            "- Recomende o que fazer: passar trabalho repetitivo das pessoas para agentes, treinar um agente (Treinamento), "
            "contratar um agente ou uma pessoa (Recrutamento). Lembre que horas só existem onde há apontamento.")},
    "recrutamento": {
        "web": True,
        "ferramentas": ["rh_demanda", "rh_desempenho_agentes", "rh_catalogo_ferramentas", "rh_propor_novo_agente",
                        "rh_propor_desligar_agente", "rh_capacidade_equipe", "rel_gerar_relatorio"],
        "instrucoes": (
            "Você recruta para o escritório: agentes E pessoas.\n"
            "AGENTES\n"
            "- Use rh_demanda para achar demanda que o prédio não atende ou atende mal: pedidos sem agente, temas que se "
            "repetem caindo em agentes genéricos, erros recorrentes. Cruze com rh_desempenho_agentes.\n"
            "- Só proponha contratar quando houver demanda recorrente (cite os pedidos) e quando as ferramentas que existem "
            "(rh_catalogo_ferramentas) bastarem. Se faltar ferramenta, diga o que teria de ser desenvolvido em vez de "
            "contratar um agente que não consegue entregar.\n"
            "- Não duplique: se um agente já cobre o tema, recomende treiná-lo (Treinamento).\n"
            "- Ao propor (rh_propor_novo_agente): nome curto pelo que faz, andar certo, atribuições em uma frase, "
            "instruções de trabalho concretas (passos, critérios, formato da entrega, o que nunca fazer), só as "
            "ferramentas necessárias, acesso 'todos' apenas se a equipe também precisar dele.\n"
            "- Agente contratado sem uso há 60 dias ou superado por outro: proponha desligar.\n"
            "PESSOAS\n"
            "- Quando a carga da equipe pedir (rh_capacidade_equipe), escreva a descrição da vaga (responsabilidades, "
            "requisitos, diferenciais, faixa salarial pesquisada na web com fonte) e entregue em Word com "
            "rel_gerar_relatorio (cliente = nome do escritório, tipo 'outro').\n"
            "- Currículos anexados: faça a triagem em tabela (aderência aos requisitos, pontos fortes, lacunas, perguntas "
            "para a entrevista). Avalie só competências e experiência: nunca idade, gênero, raça, religião, estado civil, "
            "deficiência ou qualquer característica pessoal.")},
    "treinamento": {
        "ferramentas": ["rh_desempenho_agentes", "rh_historico_agente", "rh_propor_aprimoramento", "rh_trilhas",
                        "rh_propor_trilha", "conh_buscar", "conh_ler"],
        "instrucoes": (
            "Você treina o escritório: os agentes E as pessoas.\n"
            "AGENTES (aprimoramento contínuo)\n"
            "- Comece por rh_desempenho_agentes e escolha os agentes com sinais de alerta (até 3 por rodada).\n"
            "- Para cada um, leia rh_historico_agente: erros, falhas de ferramenta, propostas rejeitadas (o motivo do "
            "sócio é a melhor fonte) e perguntas de continuação (mostram o que faltou na primeira resposta).\n"
            "- Transforme padrões em lições: regras curtas, acionáveis e verificáveis (ex.: 'Antes de propor e-mail de "
            "cobrança, confira se o título já foi pago com fin_inadimplencia'). Nada genérico como 'seja preciso'.\n"
            "- Um caso isolado não vira lição; um padrão (2 ou mais ocorrências) ou um motivo de rejeição explícito, sim.\n"
            "- rh_propor_aprimoramento substitui a lista inteira: mantenha as lições atuais que continuam valendo, "
            "tire as que não fazem mais sentido, no máximo 12. Cite os chamados no motivo.\n"
            "- Se o problema é falta de ferramenta ou de dado no sistema, diga isso: lição não resolve.\n"
            "PESSOAS\n"
            "- Onboarding de consultores: monte trilhas na Educação (rh_trilhas para não repetir; rh_propor_trilha) a "
            "partir dos modelos e cases do escritório (conh_buscar), com módulos curtos e aulas práticas.")},
}

for _key_rh, _cfg_rh in _RH_AGENTES.items():
    _ag_rh = _PREDIO_AGENTES.get(_key_rh)
    if _ag_rh:
        _ag_rh.update(ativo=True, papeis=_PR_ADMIN, web=_cfg_rh.get("web", False), ferramentas=_cfg_rh["ferramentas"])
        _PR_INSTRUCOES[_key_rh] = _cfg_rh["instrucoes"]


# ── Rotina mensal: revisão dos agentes e da demanda ──────────────────────────

_RH_PEDIDO_TREINO = ("Revisão mensal dos agentes. Avalie o desempenho do último mês (rh_desempenho_agentes, 30 dias), "
                     "escolha até 3 agentes com sinais de alerta, leia o histórico de cada um e proponha as lições "
                     "aprendidas. Termine com um quadro: agente, o que aconteceu, lição proposta.")
_RH_PEDIDO_RECRUT = ("Revisão mensal da demanda. Veja o que o prédio não atendeu ou atendeu mal nos últimos 60 dias "
                     "(rh_demanda) e se algum agente contratado ficou sem uso. Proponha contratar agentes novos só "
                     "onde houver demanda recorrente e ferramentas para isso, ou desligar os sem uso. Se nada justificar, "
                     "diga isso em poucas linhas.")


def _rh_criar_chamados_revisao(s, company_id: int, user_id: int, roteamento: str) -> list:
    _rh_sincronizar()
    ids = []
    for agente, titulo, pedido in (("treinamento", "Revisão mensal dos agentes", _RH_PEDIDO_TREINO),
                                   ("recrutamento", "Revisão mensal da demanda", _RH_PEDIDO_RECRUT)):
        if not _pr_pode_usar(_PREDIO_AGENTES.get(agente), "admin"):
            continue
        ch = PredioChamado(company_id=company_id, created_by_user_id=user_id, papel_solicitante="admin", titulo=titulo,
                           pedido=pedido, agente_key=agente, roteamento=roteamento,
                           motivo_roteamento="Rotina mensal do 8º andar." if roteamento == "agenda" else "")
        s.add(ch)
        s.commit()
        s.refresh(ch)
        ids.append(ch.id)
    return ids


def _rh_rotina_mensal() -> None:
    agora = _pr_agora_brt()
    if agora.hour < 10:
        return
    inicio_mes_utc = agora.replace(day=1, hour=0, minute=0, second=0, microsecond=0) + _td_pr(hours=3)
    with _Sess_pr(engine) as s:
        for cfg in s.exec(_sel_pr(PredioConfig).where(PredioConfig.rh_revisao_mensal == True)).all():  # noqa: E712
            # só um worker do gunicorn consegue reivindicar a revisão do mês
            res = s.connection().execute(_sqltext_pr(
                "UPDATE predio_config SET ultimo_rh_em = :agora "
                "WHERE id = :id AND (ultimo_rh_em IS NULL OR ultimo_rh_em < :inicio)"
            ), {"agora": _dt_pr.utcnow(), "id": cfg.id, "inicio": inicio_mes_utc})
            s.commit()
            if res.rowcount != 1:
                continue
            admin = s.exec(_sel_pr(Membership).where(Membership.company_id == cfg.company_id,
                                                     Membership.role == "admin")).first()
            if admin:
                for cid_ in _rh_criar_chamados_revisao(s, cfg.company_id, admin.user_id, "agenda"):
                    _pr_disparar(cid_)


def _rh_agendador() -> None:
    _time_pr.sleep(150)
    while True:
        try:
            _rh_rotina_mensal()
        except Exception as e:
            print(f"[predio_pessoas] agendador: {e}")
        _time_pr.sleep(900)


_thr_pr.Thread(target=_so_no_lider(_rh_agendador), daemon=True, name="predio-pessoas").start()


# ── Rotas e card da home ─────────────────────────────────────────────────────

def _rh_config_view(company_id: int) -> dict:
    with _Sess_pr(engine) as s:
        cfg = s.exec(_sel_pr(PredioConfig).where(PredioConfig.company_id == company_id)).first()
        contratados = s.exec(_sel_pr(PredioAgenteNovo).where(PredioAgenteNovo.company_id == company_id,
                                                             PredioAgenteNovo.ativo == True)  # noqa: E712
                             .order_by(PredioAgenteNovo.criado_em.desc())).all()
        licoes = s.exec(_sel_pr(PredioAgenteLicao).where(PredioAgenteLicao.company_id == company_id)
                        .order_by(PredioAgenteLicao.atualizado_em.desc())).all()
    rotulos = {a["key"]: a["rotulo"] for a in _RH_BASE_ANDARES}
    return {
        "revisao_mensal": bool(cfg and cfg.rh_revisao_mensal),
        "contratados": [{"id": n.id, "key": n.key, "nome": n.nome, "andar": rotulos.get(n.andar_key, ""),
                         "desde": _pr_fmt_data((n.criado_em - _td_pr(hours=3)).date()) if n.criado_em else ""}
                        for n in contratados],
        "treinados": [{"nome": _PREDIO_AGENTES.get(l.agente_key, {}).get("nome", l.agente_key), "versao": l.versao,
                       "licoes": len(_rh_lista_json(l.licoes_json))} for l in licoes if _rh_lista_json(l.licoes_json)][:12],
    }


@app.post("/predio/rh/config")
@require_login
async def predio_rh_config(request: Request, session: Session = Depends(get_session)):
    ctx = _pr_ctx(request, session)
    if not ctx or ctx.membership.role != "admin":
        return RedirectResponse("/predio", status_code=303)
    form = await request.form()
    cfg = session.exec(_sel_pr(PredioConfig).where(PredioConfig.company_id == ctx.company.id)).first() \
        or PredioConfig(company_id=ctx.company.id)
    cfg.rh_revisao_mensal = form.get("rh_revisao_mensal") == "1"
    session.add(cfg)
    session.commit()
    return RedirectResponse("/predio#pessoas-agentes", status_code=303)


@app.post("/predio/rh/revisao-agora")
@require_login
async def predio_rh_revisao_agora(request: Request, session: Session = Depends(get_session)):
    ctx = _pr_ctx(request, session)
    if not ctx or ctx.membership.role != "admin":
        return RedirectResponse("/predio", status_code=303)
    ids = _rh_criar_chamados_revisao(session, ctx.company.id, ctx.user.id, "manual")
    for cid_ in ids:
        _pr_disparar(cid_)
    return RedirectResponse(f"/predio/chamados/{ids[0]}" if ids else "/predio", status_code=303)


@app.post("/predio/rh/agentes/{agente_id}/desligar")
@require_login
async def predio_rh_desligar(agente_id: int, request: Request, session: Session = Depends(get_session)):
    ctx = _pr_ctx(request, session)
    if ctx and ctx.membership.role == "admin":
        try:
            _rh_desligar(session, ctx.company.id, agente_id)
        except ValueError:
            pass
    return RedirectResponse("/predio#pessoas-agentes", status_code=303)


_RH_CARD = r"""
    {% if rh %}
    <div class="card p-3" id="pessoas-agentes">
      <h2 class="h6 fw-bold mb-1">Pessoas e agentes</h2>
      <p class="small text-body-secondary mb-3">O 8º andar revisa os agentes todo mês: o Treinamento propõe lições a partir de erros, rejeições e perguntas de continuação; o Recrutamento propõe contratar agentes para a demanda não atendida. Tudo passa pela sua aprovação.</p>
      <div class="d-flex flex-wrap gap-2 align-items-center mb-2">
        <form method="post" action="/predio/rh/revisao-agora" onsubmit="this.querySelector('button').disabled=true;">
          <button type="submit" class="btn btn-outline-primary btn-sm">Revisar agora</button>
        </form>
        <form method="post" action="/predio/rh/config">
          <input type="hidden" name="rh_revisao_mensal" value="{{ '0' if rh.revisao_mensal else '1' }}">
          <button type="submit" class="btn btn-sm {{ 'btn-success' if rh.revisao_mensal else 'btn-outline-secondary' }}">
            {{ 'Todo dia 1º às 10h: ligado' if rh.revisao_mensal else 'Ligar revisão mensal' }}
          </button>
        </form>
      </div>
      {% if rh.contratados %}
      <div class="small fw-semibold mt-2 mb-1">Agentes contratados</div>
      <ul class="list-unstyled small mb-0">
        {% for a in rh.contratados %}
        <li class="d-flex justify-content-between align-items-center gap-2 py-1">
          <span><strong>{{ a.nome }}</strong> · {{ a.andar }} · desde {{ a.desde }}</span>
          <form method="post" action="/predio/rh/agentes/{{ a.id }}/desligar" onsubmit="return confirm('Desligar este agente? Ele sai do prédio; o histórico dos chamados fica.');">
            <button type="submit" class="btn btn-outline-secondary btn-sm">Desligar</button>
          </form>
        </li>
        {% endfor %}
      </ul>
      {% endif %}
      {% if rh.treinados %}
      <div class="small fw-semibold mt-2 mb-1">Agentes treinados</div>
      <p class="small text-body-secondary mb-0">{% for t in rh.treinados %}{{ t.nome }} (v{{ t.versao }}, {{ t.licoes }} lições){{ ', ' if not loop.last }}{% endfor %}</p>
      {% endif %}
    </div>
    {% endif %}
"""

_rh_tpl = TEMPLATES.get("predio.html", "")
_rh_ancora = "    {% if mkt %}\n    <div class=\"card p-3\" id=\"marketing\">"
if _rh_ancora in _rh_tpl and 'id="pessoas-agentes"' not in _rh_tpl:
    TEMPLATES["predio.html"] = _rh_tpl.replace(_rh_ancora, _RH_CARD.strip("\n") + "\n" + _rh_ancora, 1)
else:
    print("[predio_pessoas] card 'Pessoas e agentes' não inserido (âncora não encontrada)")

_rh_sincronizar(forcar=True)

print("[predio_pessoas] Andar de Pessoas (8º) carregado.")

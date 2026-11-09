# ============================================================================
# ui_predio.py — Prédio de agentes de IA da gestão interna do escritório
# ============================================================================
# Exec'd no namespace do app.py (acessa engine, modelos, render, helpers).
#
# Cada andar é uma área do escritório; cada agente tem atribuições, papéis que
# podem acioná-lo e ferramentas SOMENTE LEITURA sobre os dados do sistema.
# Uma demanda vira um PredioChamado: a Recepção encaminha (ou o usuário escolhe
# o agente), o agente consulta as ferramentas e entrega o resultado.
#
# ROTAS (admin/equipe; clientes nunca acessam):
#   GET  /predio                          — o prédio + nova demanda + chamados
#   POST /predio/chamados                 — cria chamado
#   GET  /predio/chamados/{id}            — acompanha o chamado
#   GET  /predio/chamados/{id}/status     — JSON para polling
#   POST /predio/briefing/gerar           — briefing semanal sob demanda (admin)
#   POST /predio/config                   — liga/desliga briefing de segunda (admin)
# ============================================================================

import json as _json_pr
import threading as _thr_pr
import time as _time_pr
from datetime import datetime as _dt_pr, timedelta as _td_pr
from typing import Optional as _Opt_pr

from sqlmodel import Field as _F_pr, SQLModel as _SM_pr, Session as _Sess_pr, select as _sel_pr
from sqlalchemy import func as _func_pr, text as _sqltext_pr

_PR_MODEL = "claude-opus-5-5"
_PR_BETAS = ["server-side-fallback-2026-07-01"]


# ── Modelos ───────────────────────────────────────────────────────────────────

class PredioChamado(_SM_pr, table=True):
    __tablename__ = "predio_chamado"
    __table_args__ = {"extend_existing": True}
    id: _Opt_pr[int] = _F_pr(default=None, primary_key=True)
    company_id: int = _F_pr(index=True)
    created_by_user_id: int = _F_pr(index=True)
    papel_solicitante: str = _F_pr(default="equipe")
    titulo: str = _F_pr(default="")
    pedido: str = _F_pr(default="")
    agente_key: str = _F_pr(default="", index=True)
    roteamento: str = _F_pr(default="manual")  # manual | recepcao | agenda
    motivo_roteamento: str = _F_pr(default="")
    status: str = _F_pr(default="na_fila", index=True)
    resultado: str = _F_pr(default="")
    passos_json: str = _F_pr(default="[]")
    mensagens_json: str = _F_pr(default="[]")  # histórico completo enviado à API (append-only)
    conversa_json: str = _F_pr(default="[]")   # perguntas de continuação: [{pergunta, resposta, erro, em}]
    tipo: str = _F_pr(default="chamado")       # chamado | reuniao
    participantes_json: str = _F_pr(default="[]")
    contribuicoes_json: str = _F_pr(default="[]")  # reunião: [{autor, nome, texto, erro}]
    erro: str = _F_pr(default="")
    created_at: _dt_pr = _F_pr(default_factory=lambda: _dt_pr.utcnow(), index=True)
    updated_at: _dt_pr = _F_pr(default_factory=lambda: _dt_pr.utcnow())
    concluido_em: _Opt_pr[_dt_pr] = _F_pr(default=None)


class PredioConfig(_SM_pr, table=True):
    __tablename__ = "predio_config"
    __table_args__ = {"extend_existing": True}
    id: _Opt_pr[int] = _F_pr(default=None, primary_key=True)
    company_id: int = _F_pr(index=True, unique=True)
    briefing_semanal: bool = _F_pr(default=False)
    ultimo_briefing_em: _Opt_pr[_dt_pr] = _F_pr(default=None)


try:
    _SM_pr.metadata.create_all(
        engine, tables=[PredioChamado.__table__, PredioConfig.__table__], checkfirst=True
    )
except Exception as _e_pr_tab:
    print(f"[predio] create_all: {_e_pr_tab}")


def _pr_migrar_colunas() -> None:
    from sqlalchemy import inspect as _insp_pr
    try:
        existentes = {c["name"] for c in _insp_pr(engine).get_columns("predio_chamado")}
    except Exception as e:
        print(f"[predio] inspeção de colunas: {e}")
        return
    colunas = {"mensagens_json": "'[]'", "conversa_json": "'[]'", "tipo": "'chamado'",
               "participantes_json": "'[]'", "contribuicoes_json": "'[]'"}
    for nome, padrao in colunas.items():
        if nome in existentes:
            continue
        try:
            with engine.begin() as conn:
                conn.execute(_sqltext_pr(f"ALTER TABLE predio_chamado ADD COLUMN {nome} TEXT DEFAULT {padrao}"))
        except Exception as e:
            # outro worker do gunicorn pode ter criado a coluna ao mesmo tempo
            print(f"[predio] coluna {nome}: {e}")


_pr_migrar_colunas()


# ── Andares e agentes ─────────────────────────────────────────────────────────
# Ordem: do topo (cobertura) para baixo (subsolo).

_PR_ADMIN = {"admin"}
_PR_TODOS = {"admin", "equipe"}

_PREDIO_ANDARES = [
    {"key": "diretoria", "nome": "Diretoria", "rotulo": "Cobertura", "agentes": [
        {"key": "chief_of_staff", "nome": "Chief of Staff", "papeis": _PR_ADMIN, "ativo": True,
         "atribuicoes": "Briefing semanal dos sócios, prioridades e pendências entre andares.",
         "ferramentas": ["ops_tarefas_atrasadas", "ops_pendencias_abertas", "ops_agenda", "ops_clientes_sem_contato",
                         "com_pipeline", "fin_resumo_caixa", "fin_inadimplencia", "fin_contratos"]},
        {"key": "estrategia", "nome": "Estratégia", "papeis": _PR_ADMIN, "ativo": False,
         "atribuicoes": "Metas do escritório (receita, carteira, margem) e acompanhamento do BSC interno."},
    ]},
    {"key": "financeiro", "nome": "Financeiro interno", "rotulo": "9º andar", "agentes": [
        {"key": "controller", "nome": "Controller", "papeis": _PR_ADMIN, "ativo": True,
         "atribuicoes": "Caixa projetado, receita e despesas, inadimplência, contratos e receita por hora trabalhada.",
         "ferramentas": ["fin_resumo_caixa", "fin_receita_por_cliente", "fin_despesas_por_categoria",
                         "fin_inadimplencia", "fin_contratos", "fin_horas_vs_receita"]},
        {"key": "faturamento", "nome": "Faturamento", "papeis": _PR_ADMIN, "ativo": False,
         "atribuicoes": "Emissão de NFS-e conforme contrato e controle de recorrências."},
        {"key": "cobranca", "nome": "Cobrança", "papeis": _PR_ADMIN, "ativo": False,
         "atribuicoes": "Identifica inadimplentes e prepara a régua de cobrança."},
        {"key": "contas_pagar", "nome": "Contas a Pagar", "papeis": _PR_ADMIN, "ativo": False,
         "atribuicoes": "Agenda pagamentos e alerta vencimentos."},
    ]},
    {"key": "pessoas", "nome": "Pessoas", "rotulo": "8º andar", "agentes": [
        {"key": "capacidade", "nome": "Capacidade", "papeis": _PR_ADMIN, "ativo": False,
         "atribuicoes": "Horas por cliente x contrato e sobrecarga da equipe."},
        {"key": "recrutamento", "nome": "Recrutamento", "papeis": _PR_ADMIN, "ativo": False,
         "atribuicoes": "Descrição de vagas e triagem de currículos."},
        {"key": "treinamento", "nome": "Treinamento", "papeis": _PR_ADMIN, "ativo": False,
         "atribuicoes": "Onboarding de consultores e trilhas na Educação."},
    ]},
    {"key": "juridico", "nome": "Jurídico e Compliance", "rotulo": "7º andar", "agentes": [
        {"key": "contratos", "nome": "Contratos", "papeis": _PR_TODOS, "ativo": False,
         "atribuicoes": "Minutas a partir de modelos, prazos e renovações."},
        {"key": "compliance", "nome": "Compliance", "papeis": _PR_TODOS, "ativo": False,
         "atribuicoes": "KYC de cliente novo, PLD e conflitos de interesse."},
        {"key": "lgpd", "nome": "Privacidade (LGPD)", "papeis": _PR_TODOS, "ativo": False,
         "atribuicoes": "Consentimentos, pedidos de titulares e retenção de dados."},
    ]},
    {"key": "consultoria", "nome": "Consultoria e Entrega", "rotulo": "6º andar", "agentes": [
        {"key": "gestor_carteira", "nome": "Gestor de Carteira", "papeis": _PR_TODOS, "ativo": False,
         "atribuicoes": "Painel por cliente: prazos, pendências e saúde da conta."},
        {"key": "analista_financeiro", "nome": "Analista Financeiro", "papeis": _PR_TODOS, "ativo": False,
         "atribuicoes": "Diagnóstico, DRE, fluxo de caixa e indicadores do cliente."},
        {"key": "orcamento_bsc", "nome": "Orçamento e BSC", "papeis": _PR_TODOS, "ativo": False,
         "atribuicoes": "Monta e acompanha orçamento e KPIs, propõe ações corretivas."},
        {"key": "secretario_reunioes", "nome": "Secretário de Reuniões", "papeis": _PR_TODOS, "ativo": False,
         "atribuicoes": "Pauta antes, ata, ações e follow-up depois de cada reunião."},
        {"key": "relatorio_mensal", "nome": "Relatório Mensal", "papeis": _PR_TODOS, "ativo": False,
         "atribuicoes": "Consolida o mês de cada cliente num relatório executivo."},
    ]},
    {"key": "credito", "nome": "Crédito e Mercado de Capitais", "rotulo": "5º andar", "agentes": [
        {"key": "estruturador", "nome": "Estruturador", "papeis": _PR_TODOS, "ativo": False,
         "atribuicoes": "Desenha operações (CRI, CRA, debêntures, crédito bancário) e monta o book."},
        {"key": "analista_risco", "nome": "Analista de Risco", "papeis": _PR_TODOS, "ativo": False,
         "atribuicoes": "Consultas de risco, crédito do tomador e garantias."},
        {"key": "relacao_investidores", "nome": "Relação com Investidores", "papeis": _PR_TODOS, "ativo": False,
         "atribuicoes": "Securitizadoras, bancos e fundos; acompanhamento de cada operação."},
    ]},
    {"key": "imobiliario", "nome": "Imobiliário", "rotulo": "4º andar", "agentes": [
        {"key": "viabilidade", "nome": "Viabilidade", "papeis": _PR_TODOS, "ativo": False,
         "atribuicoes": "Monta e compara estudos de viabilidade a partir de um briefing."},
        {"key": "produto_vendas", "nome": "Produto e Vendas", "papeis": _PR_TODOS, "ativo": False,
         "atribuicoes": "Mapa de unidades, tabela de preços e ritmo de vendas."},
        {"key": "obras", "nome": "Acompanhamento de Obras", "papeis": _PR_TODOS, "ativo": False,
         "atribuicoes": "Físico x financeiro, medições e alertas de desvio."},
    ]},
    {"key": "ma", "nome": "M&A e Valuation", "rotulo": "3º andar", "agentes": [
        {"key": "valuation", "nome": "Valuation", "papeis": _PR_TODOS, "ativo": False,
         "atribuicoes": "DCF e múltiplos, laudo preliminar."},
        {"key": "data_room", "nome": "Data Room", "papeis": _PR_TODOS, "ativo": False,
         "atribuicoes": "Organiza documentos e checklist de due diligence."},
    ]},
    {"key": "comercial", "nome": "Comercial", "rotulo": "2º andar", "agentes": [
        {"key": "prospeccao", "nome": "Prospecção", "papeis": _PR_TODOS, "ativo": False,
         "atribuicoes": "Lista e qualifica leads, pesquisa a empresa antes do contato."},
        {"key": "propostas", "nome": "Propostas", "papeis": _PR_TODOS, "ativo": False,
         "atribuicoes": "Monta proposta e escopo a partir de modelos e do diagnóstico inicial."},
        {"key": "sucesso_cliente", "nome": "Sucesso do Cliente", "papeis": _PR_TODOS, "ativo": False,
         "atribuicoes": "Renovações, sinais de cancelamento e oportunidades de venda adicional."},
    ]},
    {"key": "marketing", "nome": "Marketing", "rotulo": "1º andar", "agentes": [
        {"key": "conteudo", "nome": "Conteúdo", "papeis": _PR_TODOS, "ativo": False,
         "atribuicoes": "Posts, newsletter e artigos a partir de cases anonimizados."},
        {"key": "inteligencia_mercado", "nome": "Inteligência de Mercado", "papeis": _PR_TODOS, "ativo": False,
         "atribuicoes": "Juros, crédito e mercado imobiliário: resumo semanal para a equipe."},
    ]},
    {"key": "recepcao", "nome": "Recepção", "rotulo": "Térreo", "agentes": [
        {"key": "recepcionista", "nome": "Recepcionista", "papeis": _PR_TODOS, "ativo": True,
         "atribuicoes": "Recebe cada demanda, decide o andar certo e explica por quê."},
        {"key": "atendimento", "nome": "Atendimento", "papeis": _PR_TODOS, "ativo": False,
         "atribuicoes": "Primeira resposta a e-mail e WhatsApp de clientes, agenda reuniões."},
    ]},
    {"key": "operacoes", "nome": "Operações e Conhecimento", "rotulo": "Subsolo", "agentes": [
        {"key": "revisor", "nome": "Revisor de Qualidade", "papeis": _PR_TODOS, "ativo": False,
         "atribuicoes": "Revisa toda entrega antes de ir ao cliente."},
        {"key": "conhecimento", "nome": "Gestor de Conhecimento", "papeis": _PR_TODOS, "ativo": False,
         "atribuicoes": "Alimenta o 2º Cérebro com modelos, cases e decisões."},
        {"key": "sistemas", "nome": "Sistemas", "papeis": _PR_TODOS, "ativo": False,
         "atribuicoes": "Backups, integrações e saúde do sistema."},
    ]},
]

_PREDIO_AGENTES = {}
for _andar_pr in _PREDIO_ANDARES:
    for _ag_pr in _andar_pr["agentes"]:
        _ag_pr.setdefault("ferramentas", [])
        _ag_pr["andar_key"] = _andar_pr["key"]
        _ag_pr["andar_nome"] = _andar_pr["nome"]
        _PREDIO_AGENTES[_ag_pr["key"]] = _ag_pr


def _pr_pode_usar(agente: dict, papel: str) -> bool:
    return bool(agente and agente.get("ativo") and papel in agente.get("papeis", set()))


def _pr_agentes_disponiveis(papel: str) -> list:
    return [a for a in _PREDIO_AGENTES.values()
            if a["key"] != "recepcionista" and _pr_pode_usar(a, papel)]


# ── Helpers de data e nomes ───────────────────────────────────────────────────

def _pr_agora_brt() -> _dt_pr:
    return _dt_pr.utcnow() - _td_pr(hours=3)


def _pr_hoje():
    return _pr_agora_brt().date()


def _pr_data(valor):
    s = (valor or "").strip()[:10]
    for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return _dt_pr.strptime(s, fmt).date()
        except ValueError:
            pass
    return None


def _pr_fmt_data(d) -> str:
    return d.strftime("%d/%m/%Y") if d else ""


def _pr_quando(dt) -> str:
    if not dt:
        return ""
    return (dt - _td_pr(hours=3)).strftime("%d/%m %H:%M")


def _pr_clientes(s, cid: int) -> dict:
    return {c.id: c.name for c in s.exec(_sel_pr(Client).where(Client.company_id == cid)).all()}


def _pr_usuarios(s, cid: int) -> dict:
    rows = s.exec(
        _sel_pr(User).join(Membership, Membership.user_id == User.id).where(Membership.company_id == cid)
    ).all()
    return {u.id: u.name for u in rows}


def _pr_valor_aberto(e) -> float:
    return max(0.0, float(e.amount_expected_brl or 0) - float(e.amount_realized_brl or 0))


def _pr_data_realizacao(e):
    return _pr_data(e.settlement_date) or _pr_data(e.due_date)


def _pr_contratos_ativos(s, cid: int) -> list:
    modelo = globals().get("ContratoCliente")
    if modelo is None:
        return []
    return s.exec(_sel_pr(modelo).where(modelo.company_id == cid, modelo.status == "ativo")).all()


# ── Ferramentas (somente leitura) ─────────────────────────────────────────────

def _pr_t_resumo_caixa(s, cid, dias_a_frente):
    dias = max(1, min(int(dias_a_frente or 30), 365))
    hoje = _pr_hoje()
    limite = hoje + _td_pr(days=dias)
    nomes = _pr_clientes(s, cid)
    previsto = {"receber": [], "pagar": []}
    vencido = {"receber": [], "pagar": []}
    realizado_30 = {"receber": 0.0, "pagar": 0.0}
    for e in s.exec(_sel_pr(OfficeFinancialEntry).where(OfficeFinancialEntry.company_id == cid)).all():
        if (e.status or "").lower() == "cancelado" or e.entry_kind not in ("receber", "pagar"):
            continue
        liq = _pr_data(e.settlement_date)
        if liq and 0 <= (hoje - liq).days <= 30 and float(e.amount_realized_brl or 0) > 0:
            realizado_30[e.entry_kind] += float(e.amount_realized_brl or 0)
        if not _office_is_open(e):
            continue
        venc = _pr_data(e.due_date)
        valor = _pr_valor_aberto(e)
        if not venc or valor <= 0:
            continue
        item = {"descricao": e.description, "cliente": nomes.get(e.client_id, ""),
                "vencimento": _pr_fmt_data(venc), "valor": round(valor, 2)}
        if venc < hoje:
            item["dias_atraso"] = (hoje - venc).days
            vencido[e.entry_kind].append(item)
        elif venc <= limite:
            previsto[e.entry_kind].append(item)

    def _bloco(itens):
        itens.sort(key=lambda x: -x["valor"])
        return {"total": round(sum(i["valor"] for i in itens), 2), "quantidade": len(itens), "maiores": itens[:15]}

    a_receber, a_pagar = _bloco(previsto["receber"]), _bloco(previsto["pagar"])
    return {
        "hoje": _pr_fmt_data(hoje),
        "janela": f"próximos {dias} dias (até {_pr_fmt_data(limite)})",
        "a_receber_na_janela": a_receber,
        "a_pagar_na_janela": a_pagar,
        "saldo_previsto_na_janela": round(a_receber["total"] - a_pagar["total"], 2),
        "recebiveis_vencidos": _bloco(vencido["receber"]),
        "contas_a_pagar_vencidas": _bloco(vencido["pagar"]),
        "realizado_ultimos_30_dias": {"recebido": round(realizado_30["receber"], 2),
                                      "pago": round(realizado_30["pagar"], 2)},
        "observacao": "Saldo bancário não é registrado no sistema; o saldo previsto considera só lançamentos.",
    }


def _pr_recebido_por_cliente(s, cid, inicio, hoje):
    por_cliente: dict = {}
    sem_cliente = 0.0
    for e in s.exec(_sel_pr(OfficeFinancialEntry).where(
            OfficeFinancialEntry.company_id == cid, OfficeFinancialEntry.entry_kind == "receber")).all():
        valor = float(e.amount_realized_brl or 0)
        quando = _pr_data_realizacao(e)
        if valor <= 0 or not quando or not (inicio <= quando <= hoje) or (e.status or "") == "cancelado":
            continue
        if e.client_id:
            por_cliente[e.client_id] = por_cliente.get(e.client_id, 0.0) + valor
        else:
            sem_cliente += valor
    return por_cliente, sem_cliente


def _pr_contrato_mensal_por_cliente(s, cid) -> dict:
    mensal: dict = {}
    for c in _pr_contratos_ativos(s, cid):
        if c.client_id:
            mensal[c.client_id] = mensal.get(c.client_id, 0.0) + (c.valor_cents or 0) / 100
    return mensal


def _pr_t_receita_por_cliente(s, cid, meses):
    meses = max(1, min(int(meses or 6), 24))
    hoje = _pr_hoje()
    inicio = hoje - _td_pr(days=30 * meses)
    nomes = _pr_clientes(s, cid)
    por_cliente, sem_cliente = _pr_recebido_por_cliente(s, cid, inicio, hoje)
    contrato_mensal = _pr_contrato_mensal_por_cliente(s, cid)
    total = sum(por_cliente.values()) + sem_cliente
    ids = set(por_cliente) | set(contrato_mensal)
    linhas = []
    for client_id in ids:
        rec = por_cliente.get(client_id, 0.0)
        linhas.append({
            "cliente": nomes.get(client_id, f"cliente #{client_id}"),
            "recebido_no_periodo": round(rec, 2),
            "participacao_pct": round(rec / total * 100, 1) if total else 0.0,
            "contrato_mensal_ativo": round(contrato_mensal.get(client_id, 0.0), 2),
        })
    linhas.sort(key=lambda x: -x["recebido_no_periodo"])
    return {
        "periodo": f"{_pr_fmt_data(inicio)} a {_pr_fmt_data(hoje)}",
        "total_recebido": round(total, 2),
        "recebido_sem_cliente_vinculado": round(sem_cliente, 2),
        "clientes": linhas[:30],
        "quantidade_clientes": len(linhas),
    }


def _pr_t_despesas_por_categoria(s, cid, meses):
    meses = max(1, min(int(meses or 3), 24))
    hoje = _pr_hoje()
    inicio = hoje - _td_pr(days=30 * meses)
    categorias = {c.id: c.name for c in s.exec(_sel_pr(OfficeCategory).where(OfficeCategory.company_id == cid)).all()}
    fornecedores = {f.id: f.name for f in s.exec(_sel_pr(OfficeSupplier).where(OfficeSupplier.company_id == cid)).all()}
    por_cat: dict = {}
    por_forn: dict = {}
    total = 0.0
    for e in s.exec(_sel_pr(OfficeFinancialEntry).where(
            OfficeFinancialEntry.company_id == cid, OfficeFinancialEntry.entry_kind == "pagar")).all():
        valor = float(e.amount_realized_brl or 0)
        quando = _pr_data_realizacao(e)
        if valor <= 0 or not quando or not (inicio <= quando <= hoje) or (e.status or "") == "cancelado":
            continue
        total += valor
        cat = categorias.get(e.category_id, "Sem categoria")
        por_cat[cat] = por_cat.get(cat, 0.0) + valor
        if e.supplier_id:
            forn = fornecedores.get(e.supplier_id, f"fornecedor #{e.supplier_id}")
            por_forn[forn] = por_forn.get(forn, 0.0) + valor
    return {
        "periodo": f"{_pr_fmt_data(inicio)} a {_pr_fmt_data(hoje)}",
        "total_pago": round(total, 2),
        "media_mensal": round(total / meses, 2),
        "por_categoria": [{"categoria": k, "valor": round(v, 2), "participacao_pct": round(v / total * 100, 1) if total else 0}
                          for k, v in sorted(por_cat.items(), key=lambda x: -x[1])],
        "maiores_fornecedores": [{"fornecedor": k, "valor": round(v, 2)}
                                 for k, v in sorted(por_forn.items(), key=lambda x: -x[1])[:10]],
    }


def _pr_t_inadimplencia(s, cid):
    hoje = _pr_hoje()
    nomes = _pr_clientes(s, cid)
    por_cliente: dict = {}
    for e in s.exec(_sel_pr(OfficeFinancialEntry).where(
            OfficeFinancialEntry.company_id == cid, OfficeFinancialEntry.entry_kind == "receber")).all():
        if not _office_is_open(e):
            continue
        venc = _pr_data(e.due_date)
        valor = _pr_valor_aberto(e)
        if not venc or venc >= hoje or valor <= 0:
            continue
        chave = nomes.get(e.client_id, "Sem cliente vinculado")
        reg = por_cliente.setdefault(chave, {"cliente": chave, "total_em_atraso": 0.0, "titulos": 0, "maior_atraso_dias": 0, "itens": []})
        atraso = (hoje - venc).days
        reg["total_em_atraso"] += valor
        reg["titulos"] += 1
        reg["maior_atraso_dias"] = max(reg["maior_atraso_dias"], atraso)
        reg["itens"].append({"descricao": e.description, "vencimento": _pr_fmt_data(venc),
                             "valor": round(valor, 2), "dias_atraso": atraso})
    linhas = sorted(por_cliente.values(), key=lambda x: -x["total_em_atraso"])
    for r in linhas:
        r["total_em_atraso"] = round(r["total_em_atraso"], 2)
        r["itens"] = sorted(r["itens"], key=lambda x: -x["dias_atraso"])[:5]
    return {
        "hoje": _pr_fmt_data(hoje),
        "total_em_atraso": round(sum(r["total_em_atraso"] for r in linhas), 2),
        "clientes_inadimplentes": len(linhas),
        "por_cliente": linhas[:20],
    }


def _pr_t_contratos(s, cid):
    hoje = _pr_hoje()
    nomes = _pr_clientes(s, cid)
    ativos = []
    for c in _pr_contratos_ativos(s, cid):
        fim = _pr_data(c.data_fim)
        ativos.append({
            "cliente": nomes.get(c.client_id, c.nome_cliente or ""),
            "contrato": c.nome_contrato,
            "servicos": c.servicos,
            "valor_mensal": round((c.valor_cents or 0) / 100, 2),
            "inicio": _pr_fmt_data(_pr_data(c.data_inicio)),
            "fim": _pr_fmt_data(fim),
            "dias_para_o_fim": (fim - hoje).days if fim else None,
        })
    ativos.sort(key=lambda x: -x["valor_mensal"])
    modelo = globals().get("ContratoCliente")
    pausados = 0
    if modelo is not None:
        pausados = len(s.exec(_sel_pr(modelo).where(modelo.company_id == cid, modelo.status == "pausado")).all())
    return {
        "receita_recorrente_mensal": round(sum(a["valor_mensal"] for a in ativos), 2),
        "contratos_ativos": len(ativos),
        "contratos_pausados": pausados,
        "encerrando_em_90_dias": [a for a in ativos if a["dias_para_o_fim"] is not None and 0 <= a["dias_para_o_fim"] <= 90],
        "lista": ativos[:40],
    }


def _pr_t_horas_vs_receita(s, cid, meses):
    meses = max(1, min(int(meses or 3), 12))
    hoje = _pr_hoje()
    inicio = hoje - _td_pr(days=30 * meses)
    inicio_dt = _dt_pr.combine(inicio, _dt_pr.min.time())
    nomes = _pr_clientes(s, cid)
    usuarios = _pr_usuarios(s, cid)
    minutos_cliente: dict = {}
    minutos_usuario: dict = {}
    for ws in s.exec(_sel_pr(TaskWorkSession).where(
            TaskWorkSession.company_id == cid, TaskWorkSession.started_at >= inicio_dt)).all():
        m = _task_work_minutes(ws)
        minutos_cliente[ws.client_id] = minutos_cliente.get(ws.client_id, 0) + m
        minutos_usuario[ws.user_id] = minutos_usuario.get(ws.user_id, 0) + m
    recebido_por_id, _ = _pr_recebido_por_cliente(s, cid, inicio, hoje)
    contrato_mensal = _pr_contrato_mensal_por_cliente(s, cid)
    linhas = []
    for client_id, minutos in minutos_cliente.items():
        horas = minutos / 60
        recebido = recebido_por_id.get(client_id, 0.0)
        linhas.append({
            "cliente": nomes.get(client_id, f"cliente #{client_id}"),
            "horas": round(horas, 1),
            "recebido_no_periodo": round(recebido, 2),
            "receita_por_hora": round(recebido / horas, 2) if horas >= 0.5 else None,
            "contrato_mensal_ativo": round(contrato_mensal.get(client_id, 0.0), 2),
        })
    linhas.sort(key=lambda x: -x["horas"])
    return {
        "periodo": f"{_pr_fmt_data(inicio)} a {_pr_fmt_data(hoje)}",
        "horas_totais": round(sum(minutos_cliente.values()) / 60, 1),
        "por_cliente": linhas[:30],
        "por_pessoa": [{"pessoa": usuarios.get(uid, f"usuário #{uid}"), "horas": round(m / 60, 1)}
                       for uid, m in sorted(minutos_usuario.items(), key=lambda x: -x[1])],
        "observacao": "Horas vêm do apontamento em tarefas. Clientes sem apontamento não aparecem. "
                      "O custo da hora da equipe não é registrado, então isto mede receita por hora, não margem.",
    }


def _pr_t_tarefas_atrasadas(s, cid):
    hoje = _pr_hoje()
    nomes = _pr_clientes(s, cid)
    usuarios = _pr_usuarios(s, cid)
    atrasadas, proximas = [], 0
    for t in s.exec(_sel_pr(Task).where(Task.company_id == cid, Task.status != "concluida")).all():
        venc = _pr_data(t.due_date)
        if not venc:
            continue
        if venc < hoje:
            atrasadas.append({"tarefa": t.title, "cliente": nomes.get(t.client_id, ""),
                              "responsavel": usuarios.get(t.assignee_user_id, "sem responsável"),
                              "prioridade": t.priority, "vencimento": _pr_fmt_data(venc),
                              "dias_atraso": (hoje - venc).days})
        elif (venc - hoje).days <= 7:
            proximas += 1
    atrasadas.sort(key=lambda x: -x["dias_atraso"])
    por_resp: dict = {}
    for a in atrasadas:
        por_resp[a["responsavel"]] = por_resp.get(a["responsavel"], 0) + 1
    return {
        "atrasadas": len(atrasadas),
        "vencendo_nos_proximos_7_dias": proximas,
        "atrasadas_por_responsavel": por_resp,
        "lista": atrasadas[:25],
    }


def _pr_t_pendencias_abertas(s, cid):
    hoje = _pr_hoje()
    nomes = _pr_clientes(s, cid)
    abertas = []
    for p in s.exec(_sel_pr(PendingItem).where(PendingItem.company_id == cid, PendingItem.status != "concluido")).all():
        criada = p.created_at.date() if p.created_at else hoje
        abertas.append({"pendencia": p.title, "cliente": nomes.get(p.client_id, ""), "status": p.status,
                        "aberta_ha_dias": (hoje - criada).days, "prazo": _pr_fmt_data(_pr_data(p.due_date))})
    abertas.sort(key=lambda x: -x["aberta_ha_dias"])
    por_status: dict = {}
    for a in abertas:
        por_status[a["status"]] = por_status.get(a["status"], 0) + 1
    return {"abertas": len(abertas), "por_status": por_status, "mais_antigas": abertas[:25]}


def _pr_t_agenda(s, cid, dias):
    dias = max(1, min(int(dias or 7), 60))
    hoje = _pr_hoje()
    limite = hoje + _td_pr(days=dias)
    nomes = _pr_clientes(s, cid)
    locais = globals().get("_LOCAL_LABELS", {})
    itens = []
    for b in s.exec(_sel_pr(AgendaBooking).where(AgendaBooking.company_id == cid, AgendaBooking.status != "cancelado")).all():
        d = _pr_data(b.data)
        if not d or not (hoje <= d <= limite):
            continue
        itens.append({"data": _pr_fmt_data(d), "hora": f"{b.hora_inicio}–{b.hora_fim}",
                      "cliente": nomes.get(b.client_id, "") or b.solicitante_nome,
                      "local": locais.get(b.local, b.local), "status": b.status, "_ord": (d, b.hora_inicio)})
    itens.sort(key=lambda x: x.pop("_ord"))
    return {"periodo": f"{_pr_fmt_data(hoje)} a {_pr_fmt_data(limite)}", "reunioes_agendadas": itens}


def _pr_t_clientes_sem_contato(s, cid, dias):
    dias = max(7, min(int(dias or 30), 365))
    hoje = _pr_hoje()
    ultimas = dict(s.exec(
        _sel_pr(Meeting.client_id, _func_pr.max(Meeting.created_at))
        .where(Meeting.company_id == cid).group_by(Meeting.client_id)
    ).all())
    com_contrato = {c.client_id for c in _pr_contratos_ativos(s, cid) if c.client_id}
    linhas = []
    for c in s.exec(_sel_pr(Client).where(Client.company_id == cid)).all():
        ultima = ultimas.get(c.id)
        sem_contato = (hoje - ultima.date()).days if ultima else None
        if sem_contato is None or sem_contato >= dias:
            linhas.append({"cliente": c.name, "contrato_ativo": c.id in com_contrato,
                           "ultima_reuniao": _pr_fmt_data(ultima.date()) if ultima else "nunca",
                           "dias_sem_reuniao": sem_contato})
    linhas.sort(key=lambda x: (not x["contrato_ativo"], -(x["dias_sem_reuniao"] if x["dias_sem_reuniao"] is not None else 99999)))
    return {"criterio": f"sem reunião registrada há {dias} dias ou mais",
            "quantidade": len(linhas),
            "com_contrato_ativo": sum(1 for x in linhas if x["contrato_ativo"]),
            "clientes": linhas[:30]}


def _pr_t_pipeline(s, cid):
    hoje = _pr_hoje()
    nomes = _pr_clientes(s, cid)
    rotulos = {st["key"]: st["label"] for st in globals().get("CRM_STAGES", [])}
    por_etapa: dict = {}
    atrasados = []
    for d in s.exec(_sel_pr(BusinessDeal).where(BusinessDeal.company_id == cid)).all():
        if d.stage in ("ganho", "perdido"):
            continue
        etapa = rotulos.get(d.stage, d.stage)
        reg = por_etapa.setdefault(etapa, {"etapa": etapa, "negocios": 0, "valor": 0.0, "valor_ponderado": 0.0})
        valor = float(d.value_estimate_brl or 0)
        reg["negocios"] += 1
        reg["valor"] += valor
        reg["valor_ponderado"] += valor * (d.probability_pct or 0) / 100
        prox = _pr_data(d.next_step_date)
        if prox and prox < hoje:
            atrasados.append({"negocio": d.title, "cliente": nomes.get(d.client_id, ""), "etapa": etapa,
                              "proximo_passo": d.next_step, "data_prevista": _pr_fmt_data(prox),
                              "dias_atraso": (hoje - prox).days, "valor": round(valor, 2)})
    for r in por_etapa.values():
        r["valor"] = round(r["valor"], 2)
        r["valor_ponderado"] = round(r["valor_ponderado"], 2)
    atrasados.sort(key=lambda x: -x["dias_atraso"])
    return {
        "em_aberto": sum(r["negocios"] for r in por_etapa.values()),
        "valor_total": round(sum(r["valor"] for r in por_etapa.values()), 2),
        "valor_ponderado": round(sum(r["valor_ponderado"] for r in por_etapa.values()), 2),
        "por_etapa": list(por_etapa.values()),
        "proximos_passos_atrasados": atrasados[:15],
    }


def _pr_schema(props: dict) -> dict:
    return {"type": "object", "properties": props, "required": list(props), "additionalProperties": False}


_PR_TOOLS = {
    "fin_resumo_caixa": {
        "fn": _pr_t_resumo_caixa, "rotulo": "Consultou o caixa previsto",
        "description": "Contas a receber e a pagar em aberto do escritório: o que vence na janela pedida, "
                       "o que já está vencido e o realizado nos últimos 30 dias.",
        "props": {"dias_a_frente": {"type": "integer", "description": "Tamanho da janela em dias (ex.: 30, 90)."}}},
    "fin_receita_por_cliente": {
        "fn": _pr_t_receita_por_cliente, "rotulo": "Levantou a receita por cliente",
        "description": "Quanto cada cliente pagou ao escritório no período, participação na receita e valor mensal de contrato ativo.",
        "props": {"meses": {"type": "integer", "description": "Quantos meses para trás (1 a 24)."}}},
    "fin_despesas_por_categoria": {
        "fn": _pr_t_despesas_por_categoria, "rotulo": "Levantou as despesas",
        "description": "Despesas pagas pelo escritório no período, por categoria e maiores fornecedores.",
        "props": {"meses": {"type": "integer", "description": "Quantos meses para trás (1 a 24)."}}},
    "fin_inadimplencia": {
        "fn": _pr_t_inadimplencia, "rotulo": "Verificou a inadimplência",
        "description": "Recebíveis vencidos e não pagos, agrupados por cliente, com dias de atraso.",
        "props": {}},
    "fin_contratos": {
        "fn": _pr_t_contratos, "rotulo": "Consultou os contratos",
        "description": "Contratos ativos com clientes: receita recorrente mensal, valores e contratos que terminam em até 90 dias.",
        "props": {}},
    "fin_horas_vs_receita": {
        "fn": _pr_t_horas_vs_receita, "rotulo": "Cruzou horas trabalhadas com receita",
        "description": "Horas apontadas pela equipe por cliente e por pessoa no período, cruzadas com o recebido "
                       "(receita por hora trabalhada).",
        "props": {"meses": {"type": "integer", "description": "Quantos meses para trás (1 a 12)."}}},
    "ops_tarefas_atrasadas": {
        "fn": _pr_t_tarefas_atrasadas, "rotulo": "Verificou tarefas atrasadas",
        "description": "Tarefas não concluídas com prazo vencido (com cliente e responsável) e quantas vencem nos próximos 7 dias.",
        "props": {}},
    "ops_pendencias_abertas": {
        "fn": _pr_t_pendencias_abertas, "rotulo": "Verificou pendências abertas",
        "description": "Pendências do checklist ainda abertas, incluindo as que aguardam o cliente, das mais antigas para as mais novas.",
        "props": {}},
    "ops_agenda": {
        "fn": _pr_t_agenda, "rotulo": "Consultou a agenda",
        "description": "Reuniões agendadas com clientes nos próximos dias.",
        "props": {"dias": {"type": "integer", "description": "Quantos dias à frente (ex.: 7)."}}},
    "ops_clientes_sem_contato": {
        "fn": _pr_t_clientes_sem_contato, "rotulo": "Procurou clientes sem contato",
        "description": "Clientes sem reunião registrada há X dias ou mais, priorizando quem tem contrato ativo.",
        "props": {"dias": {"type": "integer", "description": "Dias mínimos sem reunião (ex.: 30)."}}},
    "com_pipeline": {
        "fn": _pr_t_pipeline, "rotulo": "Consultou o pipeline comercial",
        "description": "Negócios em aberto no CRM por etapa, valor total e ponderado, e próximos passos atrasados.",
        "props": {}},
}

for _nome_pr, _spec_pr in _PR_TOOLS.items():
    _spec_pr["schema"] = {
        "name": _nome_pr,
        "description": _spec_pr["description"],
        "input_schema": _pr_schema(_spec_pr["props"]),
        "strict": True,
    }


# ── Prompts ───────────────────────────────────────────────────────────────────

_PR_PEDIDO_BRIEFING = (
    "Prepare o briefing semanal dos sócios. Comece pelos 3 pontos que exigem decisão ou ação esta semana. "
    "Depois cubra, em seções curtas: caixa (próximos 30 dias), inadimplência, contratos encerrando, "
    "tarefas e pendências atrasadas, agenda da semana, clientes com contrato sem contato há 30 dias ou mais "
    "e pipeline comercial. Seja direto; se uma seção não tiver nada relevante, diga em uma linha."
)

_PR_INSTRUCOES = {
    "chief_of_staff": (
        "Você é o braço direito dos sócios. Seu trabalho é olhar o escritório inteiro e dizer o que precisa de atenção, "
        "na ordem certa. Priorize o que tem dinheiro ou relacionamento com cliente em jogo. Quando citar um problema, "
        "diga quem deveria resolver (responsável da tarefa, quem cuida do cliente) e qual o próximo passo."
    ),
    "controller": (
        "Você é o controller do escritório. Explique os números e o que eles significam para o negócio: "
        "concentração de receita, inadimplência, vencimentos próximos, despesas que crescem e clientes que dão "
        "muito trabalho para pouca receita. Quando a pergunta envolver margem, deixe claro que o sistema mede "
        "receita por hora trabalhada, porque o custo da hora da equipe não está registrado."
    ),
}


def _pr_system_prompt(agente: dict, empresa: str) -> str:
    agora = _pr_agora_brt()
    return (
        f"Você é o agente {agente['nome']}, do andar {agente['andar_nome']}, no prédio de agentes da {empresa}, "
        f"uma boutique financeira. Hoje é {agora.strftime('%d/%m/%Y')} (horário de Brasília).\n\n"
        f"Suas atribuições: {agente['atribuicoes']}\n\n"
        f"{_PR_INSTRUCOES.get(agente['key'], '')}\n\n"
        "Regras:\n"
        "- Use as ferramentas para buscar os dados reais do sistema. Nunca invente números, nomes ou datas.\n"
        "- Se um dado não existir ou vier vazio, diga isso claramente em vez de supor.\n"
        "- Você só consulta dados: não envia mensagens, não altera registros e não promete ações em nome de ninguém.\n"
        "- Escreva em português do Brasil, em markdown, para um sócio com pouco tempo: conclusão primeiro, "
        "detalhes depois. Use tabelas quando comparar vários itens.\n"
        "- Valores em reais no formato R$ 12.345,67 e datas no formato dd/mm/aaaa."
    )


def _pr_catalogo_texto(papel: str) -> str:
    linhas = []
    for andar in _PREDIO_ANDARES:
        linhas.append(f"{andar['rotulo']} — {andar['nome']}:")
        for a in andar["agentes"]:
            if a["key"] == "recepcionista":
                continue
            disp = "DISPONÍVEL" if _pr_pode_usar(a, papel) else "indisponível"
            linhas.append(f"  - {a['key']} ({a['nome']}, {disp}): {a['atribuicoes']}")
    return "\n".join(linhas)


# ── Execução ──────────────────────────────────────────────────────────────────

_pr_client_cache: dict = {}
_PR_SEMAFORO = _thr_pr.Semaphore(3)


class _PrErro(Exception):
    pass


def _pr_client():
    if "c" not in _pr_client_cache:
        import anthropic as _anthropic_pr
        _pr_client_cache["c"] = _anthropic_pr.Anthropic(max_retries=3)
    return _pr_client_cache["c"]


def _pr_msg_erro(e: Exception) -> str:
    if isinstance(e, _PrErro):
        return str(e)
    try:
        import anthropic as _a
    except ImportError:
        return "A biblioteca anthropic não está instalada. Faça o deploy com o requirements.txt atualizado."
    if isinstance(e, _a.AuthenticationError):
        return "A chave da API do Claude (ANTHROPIC_API_KEY) está ausente ou inválida."
    if isinstance(e, _a.RateLimitError):
        return "O limite de uso da API do Claude foi atingido. Tente de novo em alguns minutos."
    if isinstance(e, _a.APIStatusError):
        return f"A API do Claude retornou erro {e.status_code}: {e.message}"
    if isinstance(e, _a.APIConnectionError):
        return "Não foi possível conectar à API do Claude. Tente de novo em instantes."
    return f"Erro inesperado: {e}"


def _pr_atualizar(chamado_id: int, **campos) -> None:
    with _Sess_pr(engine) as s:
        ch = s.get(PredioChamado, chamado_id)
        if not ch:
            return
        for k, v in campos.items():
            setattr(ch, k, v)
        ch.updated_at = _dt_pr.utcnow()
        s.add(ch)
        s.commit()


def _pr_add_passo(chamado_id: int, passo: dict) -> None:
    with _Sess_pr(engine) as s:
        ch = s.get(PredioChamado, chamado_id)
        if not ch:
            return
        try:
            passos = _json_pr.loads(ch.passos_json or "[]")
        except ValueError:
            passos = []
        passos.append(passo)
        ch.passos_json = _json_pr.dumps(passos, ensure_ascii=False, default=str)
        ch.updated_at = _dt_pr.utcnow()
        s.add(ch)
        s.commit()


def _pr_rotear(pedido: str, papel: str) -> dict:
    disponiveis = [a["key"] for a in _pr_agentes_disponiveis(papel)]
    todos = [k for k in _PREDIO_AGENTES if k != "recepcionista"]
    schema = {
        "type": "object",
        "properties": {
            "agente": {"type": "string", "enum": disponiveis + ["nenhum"]},
            "andar_ideal": {"type": "string", "enum": todos},
            "titulo": {"type": "string"},
            "motivo": {"type": "string"},
        },
        "required": ["agente", "andar_ideal", "titulo", "motivo"],
        "additionalProperties": False,
    }
    system = (
        "Você é a Recepcionista do prédio de agentes de uma boutique financeira. Leia a demanda e escolha o agente "
        "que deve atendê-la.\n\n"
        "- 'andar_ideal' é o agente mais adequado entre TODOS, mesmo que esteja indisponível.\n"
        "- 'agente' é quem vai atender agora: escolha entre os DISPONÍVEIS. Se nenhum disponível consegue atender "
        "bem, use 'nenhum'.\n"
        "- 'titulo': título curto da demanda (até 8 palavras).\n"
        "- 'motivo': uma frase explicando a escolha. Se usar 'nenhum', diga qual andar atenderia e que ele ainda "
        "não está ativo.\n\n"
        f"Agentes do prédio:\n{_pr_catalogo_texto(papel)}"
    )
    resp = _pr_client().beta.messages.create(
        model=_PR_MODEL,
        max_tokens=8000,
        system=system,
        messages=[{"role": "user", "content": pedido}],
        output_config={"effort": "low", "format": {"type": "json_schema", "schema": schema}},
        betas=_PR_BETAS,
        fallbacks="default",
    )
    if resp.stop_reason == "refusal":
        raise _PrErro("A Recepção não conseguiu processar esta demanda.")
    texto = next((b.text for b in resp.content if b.type == "text"), "")
    try:
        return _json_pr.loads(texto)
    except ValueError:
        raise _PrErro("A Recepção devolveu uma resposta inválida. Tente de novo.")


def _pr_rodar_agente(chamado_id: int, agente: dict, messages: list, company_id: int, empresa: str,
                     turno=0) -> tuple:
    """Roda o loop de ferramentas sobre `messages` (que termina numa pergunta do usuário).
    Retorna (texto_final, messages) com tudo o que foi trocado anexado, sem editar o histórico."""
    client = _pr_client()
    permitidas = set(agente["ferramentas"])
    tools = [_PR_TOOLS[n]["schema"] for n in agente["ferramentas"]]
    system = _pr_system_prompt(agente, empresa)
    messages = list(messages)
    for _ in range(15):
        resp = client.beta.messages.create(
            model=_PR_MODEL,
            max_tokens=16000,
            system=system,
            tools=tools,
            messages=messages,
            output_config={"effort": "high"},
            betas=_PR_BETAS,
            fallbacks="default",
        )
        if resp.stop_reason == "refusal":
            raise _PrErro("O modelo recusou esta demanda.")
        messages.append({"role": "assistant", "content": [b.to_dict() for b in resp.content]})
        if resp.stop_reason == "pause_turn":
            continue
        usos = [b for b in resp.content if b.type == "tool_use"]
        if not usos:
            texto = "\n\n".join(b.text for b in resp.content if b.type == "text").strip()
            if resp.stop_reason == "max_tokens":
                texto += "\n\n_(A resposta foi cortada por limite de tamanho.)_"
            return (texto or "O agente terminou sem uma resposta escrita."), messages
        resultados = []
        for uso in usos:
            spec = _PR_TOOLS.get(uso.name)
            entrada = dict(uso.input or {})
            ok = True
            if not spec or uso.name not in permitidas:
                conteudo, ok = f"Ferramenta {uso.name} não disponível para este agente.", False
            else:
                try:
                    with _Sess_pr(engine) as s:
                        dado = spec["fn"](s, company_id, **entrada)
                    conteudo = _json_pr.dumps(dado, ensure_ascii=False, default=str)
                except Exception as e_tool:
                    conteudo, ok = f"Erro ao consultar os dados: {e_tool}", False
            bloco = {"type": "tool_result", "tool_use_id": uso.id, "content": conteudo}
            if not ok:
                bloco["is_error"] = True
            resultados.append(bloco)
            _pr_add_passo(chamado_id, {
                "ferramenta": uso.name,
                "rotulo": spec["rotulo"] if spec else uso.name,
                "entrada": entrada,
                "ok": ok,
                "em": _pr_agora_brt().strftime("%H:%M:%S"),
                "turno": turno,
                "autor": agente["key"],
            })
        messages.append({"role": "user", "content": resultados})
    raise _PrErro("O agente atingiu o limite de etapas sem concluir. Tente reformular de forma mais específica.")


def _pr_notificar(chamado_id: int) -> None:
    with _Sess_pr(engine) as s:
        ch = s.get(PredioChamado, chamado_id)
        if not ch:
            return
        agente = _PREDIO_AGENTES.get(ch.agente_key, {})
        nome = agente.get("nome", "Recepção")
        ok = ch.status == "concluido"
        titulo = f"{nome} {'concluiu' if ok else 'não concluiu'}: {ch.titulo or 'sua demanda'}"
        href = f"/predio/chamados/{ch.id}"
        if ch.roteamento == "agenda":
            destinos = [m.user_id for m in s.exec(_sel_pr(Membership).where(
                Membership.company_id == ch.company_id, Membership.role == "admin")).all()]
        else:
            destinos = [ch.created_by_user_id]
        for uid in dict.fromkeys(destinos):
            try:
                create_user_notification(s, company_id=ch.company_id, user_id=uid, kind="predio",
                                         title=titulo[:200], href=href)
            except Exception as e_n:
                print(f"[predio] notificação: {e_n}")
        s.commit()
        if ch.roteamento == "agenda" and ok:
            base = PUBLIC_BASE_URL or "https://app.maffezzollicapital.com.br"
            for uid in dict.fromkeys(destinos):
                u = s.get(User, uid)
                if not u or not u.email:
                    continue
                try:
                    _smtp_send_email(
                        to_email=u.email,
                        subject=ch.titulo or "Briefing semanal",
                        html_body=(f"<p>O briefing semanal está pronto.</p>"
                                   f"<p><a href=\"{base}{href}\">Abrir o briefing no prédio</a></p>"),
                        text_body=f"O briefing semanal está pronto: {base}{href}",
                    )
                except Exception as e_m:
                    print(f"[predio] e-mail briefing: {e_m}")


def _pr_processar(chamado_id: int) -> None:
    with _PR_SEMAFORO:
        try:
            with _Sess_pr(engine) as s:
                ch = s.get(PredioChamado, chamado_id)
                if not ch:
                    return
                pedido, papel, cid = ch.pedido, ch.papel_solicitante, ch.company_id
                agente_key = ch.agente_key
                empresa_obj = s.get(Company, cid)
                empresa = empresa_obj.name if empresa_obj else "empresa"

            if not agente_key:
                _pr_atualizar(chamado_id, status="roteando")
                rota = _pr_rotear(pedido, papel)
                if rota.get("agente") == "nenhum" or rota.get("agente") not in _PREDIO_AGENTES:
                    ideal = _PREDIO_AGENTES.get(rota.get("andar_ideal", ""), {})
                    _pr_atualizar(chamado_id, status="sem_agente", titulo=rota.get("titulo", "")[:200],
                                  motivo_roteamento=rota.get("motivo", ""),
                                  resultado=(f"Esta demanda é do andar **{ideal.get('andar_nome', '?')}** "
                                             f"({ideal.get('nome', '?')}), que ainda não está ativo."),
                                  concluido_em=_dt_pr.utcnow())
                    return
                agente_key = rota["agente"]
                _pr_atualizar(chamado_id, agente_key=agente_key, titulo=rota.get("titulo", "")[:200],
                              motivo_roteamento=rota.get("motivo", ""))

            agente = _PREDIO_AGENTES.get(agente_key)
            if not _pr_pode_usar(agente, papel):
                raise _PrErro("Este agente não está disponível para o seu perfil.")
            _pr_atualizar(chamado_id, status="trabalhando")
            texto, mensagens = _pr_rodar_agente(chamado_id, agente, [{"role": "user", "content": pedido}], cid, empresa)
            _pr_atualizar(chamado_id, status="concluido", resultado=texto, concluido_em=_dt_pr.utcnow(),
                          mensagens_json=_json_pr.dumps(mensagens, ensure_ascii=False, default=str))
        except Exception as e:
            print(f"[predio] chamado {chamado_id}: {e}")
            _pr_atualizar(chamado_id, status="erro", erro=_pr_msg_erro(e)[:1000], concluido_em=_dt_pr.utcnow())
        try:
            _pr_notificar(chamado_id)
        except Exception as e_not:
            print(f"[predio] notificar {chamado_id}: {e_not}")


def _pr_json_lista(valor: str) -> list:
    try:
        dado = _json_pr.loads(valor or "[]")
        return dado if isinstance(dado, list) else []
    except ValueError:
        return []


def _pr_continuar(chamado_id: int) -> None:
    with _PR_SEMAFORO:
        turno = 0
        conversa: list = []
        try:
            with _Sess_pr(engine) as s:
                ch = s.get(PredioChamado, chamado_id)
                if not ch:
                    return
                conversa = _pr_json_lista(ch.conversa_json)
                mensagens = _pr_json_lista(ch.mensagens_json)
                if not mensagens:
                    # chamados anteriores ao histórico completo: retoma pelo texto da 1ª resposta
                    mensagens = [{"role": "user", "content": ch.pedido},
                                 {"role": "assistant", "content": ch.resultado or "(sem resposta)"}]
                agente = _PREDIO_AGENTES.get(ch.agente_key)
                papel, cid = ch.papel_solicitante, ch.company_id
                empresa_obj = s.get(Company, cid)
                empresa = empresa_obj.name if empresa_obj else "empresa"
            turno = len(conversa)
            pergunta = conversa[-1]["pergunta"]
            if not _pr_pode_usar(agente, papel):
                raise _PrErro("Este agente não está disponível para o seu perfil.")
            texto, mensagens = _pr_rodar_agente(
                chamado_id, agente, mensagens + [{"role": "user", "content": pergunta}], cid, empresa, turno)
            conversa[-1]["resposta"] = texto
            _pr_atualizar(chamado_id, status="concluido", concluido_em=_dt_pr.utcnow(), erro="",
                          conversa_json=_json_pr.dumps(conversa, ensure_ascii=False),
                          mensagens_json=_json_pr.dumps(mensagens, ensure_ascii=False, default=str))
        except Exception as e:
            print(f"[predio] continuação do chamado {chamado_id}: {e}")
            if conversa:
                conversa[-1]["erro"] = _pr_msg_erro(e)[:1000]
            _pr_atualizar(chamado_id, status="erro", erro=_pr_msg_erro(e)[:1000],
                          conversa_json=_json_pr.dumps(conversa, ensure_ascii=False))


def _pr_facilitador(participantes: list, papel: str) -> str:
    if _pr_pode_usar(_PREDIO_AGENTES.get("chief_of_staff"), papel):
        return "chief_of_staff"
    return participantes[0]


def _pr_processar_reuniao(chamado_id: int) -> None:
    with _PR_SEMAFORO:
        try:
            with _Sess_pr(engine) as s:
                ch = s.get(PredioChamado, chamado_id)
                if not ch:
                    return
                pauta, papel, cid = ch.pedido, ch.papel_solicitante, ch.company_id
                participantes = _pr_json_lista(ch.participantes_json)
                empresa_obj = s.get(Company, cid)
                empresa = empresa_obj.name if empresa_obj else "empresa"
            _pr_atualizar(chamado_id, status="trabalhando")
            nomes = ", ".join(_PREDIO_AGENTES[k]["nome"] for k in participantes if k in _PREDIO_AGENTES)
            contribuicoes = []
            for i, key in enumerate(participantes):
                agente = _PREDIO_AGENTES.get(key)
                item = {"autor": key, "nome": agente["nome"] if agente else key, "texto": "", "erro": ""}
                try:
                    if not _pr_pode_usar(agente, papel):
                        raise _PrErro("Agente indisponível para o seu perfil.")
                    convite = (
                        f"Você foi chamado para uma reunião do escritório com: {nomes}.\n\nPauta: {pauta}\n\n"
                        "Traga a sua contribuição a partir dos seus dados: os fatos que importam para a pauta, "
                        "riscos e a sua recomendação. Seja objetivo (até 200 palavras), em markdown."
                    )
                    item["texto"], _ = _pr_rodar_agente(
                        chamado_id, agente, [{"role": "user", "content": convite}], cid, empresa, turno=f"c{i}")
                except Exception as e_c:
                    item["erro"] = _pr_msg_erro(e_c)[:500]
                contribuicoes.append(item)
                _pr_atualizar(chamado_id, contribuicoes_json=_json_pr.dumps(contribuicoes, ensure_ascii=False))
            validas = [c for c in contribuicoes if c["texto"]]
            if not validas:
                raise _PrErro("Nenhum participante conseguiu contribuir. " + (contribuicoes[0]["erro"] if contribuicoes else ""))
            facilitador = _PREDIO_AGENTES[_pr_facilitador(participantes, papel)]
            pedido_ata = (
                f"Você conduziu uma reunião do escritório.\n\nPauta: {pauta}\n\nContribuições dos participantes:\n\n"
                + "\n\n".join(f"### {c['nome']}\n{c['texto']}" for c in validas)
                + "\n\nEscreva a ata: decisões sugeridas, pontos de divergência (se houver) e próximos passos com "
                  "responsável e prazo sugeridos. Use só o que os participantes trouxeram; consulte dados apenas "
                  "se precisar confirmar algo."
            )
            ata, mensagens = _pr_rodar_agente(
                chamado_id, facilitador, [{"role": "user", "content": pedido_ata}], cid, empresa, turno=0)
            _pr_atualizar(chamado_id, status="concluido", resultado=ata, concluido_em=_dt_pr.utcnow(),
                          agente_key=facilitador["key"],
                          mensagens_json=_json_pr.dumps(mensagens, ensure_ascii=False, default=str))
        except Exception as e:
            print(f"[predio] reunião {chamado_id}: {e}")
            _pr_atualizar(chamado_id, status="erro", erro=_pr_msg_erro(e)[:1000], concluido_em=_dt_pr.utcnow())
        try:
            _pr_notificar(chamado_id)
        except Exception as e_not:
            print(f"[predio] notificar {chamado_id}: {e_not}")


def _pr_disparar(chamado_id: int, continuar: bool = False, reuniao: bool = False) -> None:
    alvo = _pr_continuar if continuar else (_pr_processar_reuniao if reuniao else _pr_processar)
    _thr_pr.Thread(target=alvo, args=(chamado_id,), daemon=True, name=f"predio-{chamado_id}").start()


def _pr_criar_briefing(s, company_id: int, user_id: int, roteamento: str) -> PredioChamado:
    ch = PredioChamado(
        company_id=company_id, created_by_user_id=user_id, papel_solicitante="admin",
        titulo=f"Briefing semanal — {_pr_agora_brt().strftime('%d/%m/%Y')}",
        pedido=_PR_PEDIDO_BRIEFING, agente_key="chief_of_staff", roteamento=roteamento,
        motivo_roteamento="Briefing semanal dos sócios." if roteamento == "agenda" else "",
    )
    s.add(ch)
    s.commit()
    s.refresh(ch)
    return ch


# ── Agendador: briefing de segunda + chamados interrompidos ───────────────────

def _pr_resetar_travados() -> None:
    corte = _dt_pr.utcnow() - _td_pr(minutes=30)
    with _Sess_pr(engine) as s:
        travados = s.exec(_sel_pr(PredioChamado).where(
            PredioChamado.status.in_(["na_fila", "roteando", "trabalhando"]),
            PredioChamado.updated_at < corte,
        )).all()
        for ch in travados:
            ch.status = "erro"
            ch.erro = "O processamento foi interrompido (o servidor reiniciou). Envie a demanda de novo."
            ch.updated_at = _dt_pr.utcnow()
            s.add(ch)
        if travados:
            s.commit()


def _pr_briefings_semanais() -> None:
    agora = _pr_agora_brt()
    if agora.weekday() != 0 or agora.hour < 8:
        return
    corte = _dt_pr.utcnow() - _td_pr(days=5)
    with _Sess_pr(engine) as s:
        configs = s.exec(_sel_pr(PredioConfig).where(PredioConfig.briefing_semanal == True)).all()  # noqa: E712
        for cfg in configs:
            # UPDATE condicional: só um worker do gunicorn consegue reivindicar o briefing da semana
            res = s.connection().execute(_sqltext_pr(
                "UPDATE predio_config SET ultimo_briefing_em = :agora "
                "WHERE id = :id AND (ultimo_briefing_em IS NULL OR ultimo_briefing_em < :corte)"
            ), {"agora": _dt_pr.utcnow(), "id": cfg.id, "corte": corte})
            s.commit()
            if res.rowcount != 1:
                continue
            admin = s.exec(_sel_pr(Membership).where(
                Membership.company_id == cfg.company_id, Membership.role == "admin")).first()
            if not admin:
                continue
            ch = _pr_criar_briefing(s, cfg.company_id, admin.user_id, "agenda")
            _pr_disparar(ch.id)


def _pr_agendador() -> None:
    _time_pr.sleep(90)
    while True:
        try:
            _pr_resetar_travados()
            _pr_briefings_semanais()
        except Exception as e:
            print(f"[predio] agendador: {e}")
        _time_pr.sleep(600)


_thr_pr.Thread(target=_pr_agendador, daemon=True, name="predio-agendador").start()


# ── Rotas ─────────────────────────────────────────────────────────────────────

_PR_STATUS_LABEL = {
    "na_fila": "Na fila",
    "roteando": "Na recepção",
    "trabalhando": "Trabalhando",
    "concluido": "Concluído",
    "sem_agente": "Andar ainda não ativo",
    "erro": "Erro",
}


def _pr_ctx(request: Request, session: Session):
    ctx = get_tenant_context(request, session)
    if not ctx or ctx.membership.role not in ("admin", "equipe"):
        return None
    return ctx


def _pr_pode_ver(ctx, ch: PredioChamado) -> bool:
    if not ch or ch.company_id != ctx.company.id:
        return False
    if ctx.membership.role == "admin" or ch.created_by_user_id == ctx.user.id:
        return True
    ag = _PREDIO_AGENTES.get(ch.agente_key)
    return bool(ag and ctx.membership.role in ag["papeis"])


def _pr_pode_continuar(ctx, ch: PredioChamado) -> bool:
    return bool(
        ch.resultado
        and ch.status in ("concluido", "erro")
        and _pr_pode_usar(_PREDIO_AGENTES.get(ch.agente_key), ctx.membership.role)
    )


def _pr_turnos(ch: PredioChamado, passos: list) -> list:
    conversa = _pr_json_lista(ch.conversa_json)
    em_andamento = ch.status in ("na_fila", "roteando", "trabalhando")
    perguntas = [{"pergunta": ch.pedido, "resposta": ch.resultado,
                  "erro": ch.erro if (ch.status == "erro" and not conversa) else ""}]
    for t in conversa:
        perguntas.append({"pergunta": t.get("pergunta", ""), "resposta": t.get("resposta", ""),
                          "erro": t.get("erro", "")})
    ultimo = perguntas[-1]
    if not em_andamento and not ultimo["resposta"] and not ultimo["erro"] and ch.status == "erro":
        ultimo["erro"] = ch.erro
    for i, t in enumerate(perguntas):
        t["passos"] = [p for p in passos if str(p.get("turno", 0)) == str(i)]
        t["aguardando"] = em_andamento and i == len(perguntas) - 1
    if ch.tipo == "reuniao":
        feitas = {c.get("autor"): c for c in _pr_json_lista(ch.contribuicoes_json)}
        contribs = []
        for i, key in enumerate(_pr_json_lista(ch.participantes_json)):
            c = feitas.get(key, {})
            contribs.append({
                "nome": _PREDIO_AGENTES.get(key, {}).get("nome", key),
                "texto": c.get("texto", ""),
                "erro": c.get("erro", ""),
                "passos": [p for p in passos if str(p.get("turno", "")) == f"c{i}"],
                "aguardando": em_andamento and not c,
            })
        perguntas[0]["contribuicoes"] = contribs
    return perguntas


def _pr_chamado_view(ch: PredioChamado, ctx=None) -> dict:
    ag = _PREDIO_AGENTES.get(ch.agente_key, {})
    passos = _pr_json_lista(ch.passos_json)
    return {
        "turnos": _pr_turnos(ch, passos),
        "pode_continuar": bool(ctx) and _pr_pode_continuar(ctx, ch),
        "tipo": ch.tipo or "chamado",
        "participantes": [_PREDIO_AGENTES.get(k, {}).get("nome", k) for k in _pr_json_lista(ch.participantes_json)],
        "id": ch.id,
        "titulo": ch.titulo or (ch.pedido[:70] + ("…" if len(ch.pedido) > 70 else "")),
        "pedido": ch.pedido,
        "agente": ag.get("nome", "Recepção"),
        "andar": ag.get("andar_nome", "Recepção"),
        "roteamento": ch.roteamento,
        "motivo": ch.motivo_roteamento,
        "status": ch.status,
        "status_label": _PR_STATUS_LABEL.get(ch.status, ch.status),
        "em_andamento": ch.status in ("na_fila", "roteando", "trabalhando"),
        "resultado": ch.resultado,
        "erro": ch.erro,
        "passos": passos,
        "criado": _pr_quando(ch.created_at),
        "concluido": _pr_quando(ch.concluido_em),
    }


def _pr_base_ctx(request, session, ctx) -> dict:
    return {
        "current_user": ctx.user,
        "current_company": ctx.company,
        "role": ctx.membership.role,
        "current_client": get_client_or_none(session, ctx.company.id, get_active_client_id(request, session, ctx)),
    }


@app.get("/predio", response_class=HTMLResponse)
@require_login
async def predio_home(request: Request, session: Session = Depends(get_session)):
    ctx = _pr_ctx(request, session)
    if not ctx:
        return RedirectResponse("/", status_code=303)
    papel = ctx.membership.role
    q = _sel_pr(PredioChamado).where(PredioChamado.company_id == ctx.company.id)
    if papel != "admin":
        q = q.where(PredioChamado.created_by_user_id == ctx.user.id)
    recentes = session.exec(q.order_by(PredioChamado.created_at.desc()).limit(15)).all()
    ocupados: dict = {}
    em_reuniao: list = []
    for ch in session.exec(_sel_pr(PredioChamado).where(
            PredioChamado.company_id == ctx.company.id,
            PredioChamado.status.in_(["na_fila", "roteando", "trabalhando"]))).all():
        if ch.tipo == "reuniao":
            em_reuniao += [k for k in _pr_json_lista(ch.participantes_json) if k not in em_reuniao]
            continue
        ocupados[ch.agente_key or "recepcionista"] = ocupados.get(ch.agente_key or "recepcionista", 0) + 1
    andares = []
    for andar in _PREDIO_ANDARES:
        agentes = []
        for a in andar["agentes"]:
            agentes.append({
                "key": a["key"], "nome": a["nome"], "atribuicoes": a["atribuicoes"],
                "ativo": a["ativo"], "pode_usar": _pr_pode_usar(a, papel) and a["key"] != "recepcionista",
                "acesso": "Só admin" if a["papeis"] == _PR_ADMIN else "Admin e equipe",
                "ocupado": ocupados.get(a["key"], 0),
                "em_reuniao": a["key"] in em_reuniao,
            })
        curto = {"Cobertura": "Cob", "Térreo": "T", "Subsolo": "SS"}.get(andar["rotulo"], andar["rotulo"].split(" ")[0])
        andares.append({"key": andar["key"], "nome": andar["nome"], "rotulo": andar["rotulo"], "curto": curto,
                        "agentes": agentes, "ativos": sum(1 for a in agentes if a["ativo"])})
    cfg = session.exec(_sel_pr(PredioConfig).where(PredioConfig.company_id == ctx.company.id)).first()
    disponiveis = _pr_agentes_disponiveis(papel)
    return render("predio.html", request=request, context={
        **_pr_base_ctx(request, session, ctx),
        "andares": andares,
        "disponiveis": [{"key": a["key"], "nome": a["nome"], "andar": a["andar_nome"]} for a in disponiveis],
        "recentes": [_pr_chamado_view(c) for c in recentes],
        "briefing_semanal": bool(cfg and cfg.briefing_semanal),
        "total_agentes": len(_PREDIO_AGENTES),
        "total_ativos": sum(1 for a in _PREDIO_AGENTES.values() if a["ativo"]),
        "agente_pre": request.query_params.get("agente", "") if request.query_params.get("agente", "") in _PREDIO_AGENTES else "",
        "em_reuniao": em_reuniao,
    })


@app.post("/predio/chamados")
@require_login
async def predio_criar_chamado(request: Request, session: Session = Depends(get_session)):
    ctx = _pr_ctx(request, session)
    if not ctx:
        return RedirectResponse("/", status_code=303)
    form = await request.form()
    pedido = str(form.get("pedido") or "").strip()[:4000]
    agente_key = str(form.get("agente") or "auto").strip()
    if not pedido:
        return RedirectResponse("/predio", status_code=303)
    papel = ctx.membership.role
    if agente_key != "auto":
        if not _pr_pode_usar(_PREDIO_AGENTES.get(agente_key), papel) or agente_key == "recepcionista":
            return RedirectResponse("/predio", status_code=303)
    elif not _pr_agentes_disponiveis(papel):
        return RedirectResponse("/predio", status_code=303)
    ch = PredioChamado(
        company_id=ctx.company.id, created_by_user_id=ctx.user.id, papel_solicitante=papel,
        pedido=pedido,
        agente_key="" if agente_key == "auto" else agente_key,
        roteamento="recepcao" if agente_key == "auto" else "manual",
    )
    session.add(ch)
    session.commit()
    session.refresh(ch)
    _pr_disparar(ch.id)
    return RedirectResponse(f"/predio/chamados/{ch.id}", status_code=303)


@app.post("/predio/reunioes")
@require_login
async def predio_convocar_reuniao(request: Request, session: Session = Depends(get_session)):
    ctx = _pr_ctx(request, session)
    if not ctx:
        return RedirectResponse("/", status_code=303)
    form = await request.form()
    pauta = str(form.get("pauta") or "").strip()[:4000]
    papel = ctx.membership.role
    participantes = []
    for key in form.getlist("participantes"):
        key = str(key)
        if key not in participantes and key != "recepcionista" and _pr_pode_usar(_PREDIO_AGENTES.get(key), papel):
            participantes.append(key)
    if not pauta or not participantes:
        return RedirectResponse("/predio", status_code=303)
    ch = PredioChamado(
        company_id=ctx.company.id, created_by_user_id=ctx.user.id, papel_solicitante=papel,
        tipo="reuniao", pedido=pauta, titulo=f"Reunião: {pauta[:70]}{'…' if len(pauta) > 70 else ''}",
        agente_key=_pr_facilitador(participantes, papel), roteamento="manual",
        participantes_json=_json_pr.dumps(participantes),
    )
    session.add(ch)
    session.commit()
    session.refresh(ch)
    _pr_disparar(ch.id, reuniao=True)
    return RedirectResponse(f"/predio/chamados/{ch.id}", status_code=303)


@app.get("/predio/chamados/{chamado_id}", response_class=HTMLResponse)
@require_login
async def predio_ver_chamado(chamado_id: int, request: Request, session: Session = Depends(get_session)):
    ctx = _pr_ctx(request, session)
    if not ctx:
        return RedirectResponse("/", status_code=303)
    ch = session.get(PredioChamado, chamado_id)
    if not _pr_pode_ver(ctx, ch):
        return RedirectResponse("/predio", status_code=303)
    return render("predio_chamado.html", request=request, context={
        **_pr_base_ctx(request, session, ctx),
        "ch": _pr_chamado_view(ch, ctx),
    })


@app.post("/predio/chamados/{chamado_id}/mensagens")
@require_login
async def predio_continuar_chamado(chamado_id: int, request: Request, session: Session = Depends(get_session)):
    ctx = _pr_ctx(request, session)
    if not ctx:
        return RedirectResponse("/", status_code=303)
    ch = session.get(PredioChamado, chamado_id)
    if not _pr_pode_ver(ctx, ch):
        return RedirectResponse("/predio", status_code=303)
    form = await request.form()
    pergunta = str(form.get("mensagem") or "").strip()[:4000]
    if pergunta and _pr_pode_continuar(ctx, ch):
        conversa = _pr_json_lista(ch.conversa_json)
        conversa.append({"pergunta": pergunta, "resposta": "", "erro": "",
                         "em": _pr_agora_brt().strftime("%d/%m %H:%M"), "autor_id": ctx.user.id})
        ch.conversa_json = _json_pr.dumps(conversa, ensure_ascii=False)
        ch.status = "trabalhando"
        ch.erro = ""
        ch.updated_at = _dt_pr.utcnow()
        session.add(ch)
        session.commit()
        _pr_disparar(ch.id, continuar=True)
    return RedirectResponse(f"/predio/chamados/{chamado_id}#fim", status_code=303)


@app.get("/predio/chamados/{chamado_id}/status")
@require_login
async def predio_status_chamado(chamado_id: int, request: Request, session: Session = Depends(get_session)):
    ctx = _pr_ctx(request, session)
    if not ctx:
        return JSONResponse({"erro": "sem permissão"}, status_code=403)
    ch = session.get(PredioChamado, chamado_id)
    if not _pr_pode_ver(ctx, ch):
        return JSONResponse({"erro": "não encontrado"}, status_code=404)
    return JSONResponse(_pr_chamado_view(ch, ctx))


@app.post("/predio/briefing/gerar")
@require_login
async def predio_gerar_briefing(request: Request, session: Session = Depends(get_session)):
    ctx = _pr_ctx(request, session)
    if not ctx or ctx.membership.role != "admin":
        return RedirectResponse("/predio", status_code=303)
    ch = _pr_criar_briefing(session, ctx.company.id, ctx.user.id, "manual")
    _pr_disparar(ch.id)
    return RedirectResponse(f"/predio/chamados/{ch.id}", status_code=303)


@app.post("/predio/config")
@require_login
async def predio_salvar_config(request: Request, session: Session = Depends(get_session)):
    ctx = _pr_ctx(request, session)
    if not ctx or ctx.membership.role != "admin":
        return RedirectResponse("/predio", status_code=303)
    form = await request.form()
    cfg = session.exec(_sel_pr(PredioConfig).where(PredioConfig.company_id == ctx.company.id)).first()
    if not cfg:
        cfg = PredioConfig(company_id=ctx.company.id)
    cfg.briefing_semanal = form.get("briefing_semanal") == "1"
    session.add(cfg)
    session.commit()
    return RedirectResponse("/predio", status_code=303)


# ── Templates ─────────────────────────────────────────────────────────────────

TEMPLATES["predio.html"] = r"""
{% extends "base.html" %}
{% block content %}
<style>
  .pd-tower{background:#11161c;border-radius:18px;padding:1.1rem .9rem 0;color:#e7ecf2;
    box-shadow:0 18px 40px -24px rgba(0,0,0,.6);}
  .pd-roof{display:flex;justify-content:space-between;align-items:baseline;gap:.75rem;
    border-bottom:2px solid #2a323c;padding:0 .35rem .8rem;margin-bottom:.4rem;}
  .pd-roof h1{font-size:1.25rem;font-weight:800;margin:0;color:#fff;letter-spacing:-.01em;}
  .pd-roof small{color:#8a96a3;font-size:.78rem;font-variant-numeric:tabular-nums;}
  .pd-floor{border-bottom:1px solid #222a33;}
  .pd-floor:last-child{border-bottom:0;}
  .pd-floor summary{list-style:none;display:grid;grid-template-columns:5.2rem 1fr auto;gap:.75rem;
    align-items:center;padding:.7rem .35rem;cursor:pointer;border-radius:10px;}
  .pd-floor summary::-webkit-details-marker{display:none;}
  .pd-floor summary:hover{background:#18202a;}
  .pd-floor summary:focus-visible{outline:2px solid var(--mc-primary,#f97316);outline-offset:2px;}
  .pd-level{font-size:.68rem;text-transform:uppercase;letter-spacing:.08em;color:#8a96a3;font-weight:700;}
  .pd-name{font-weight:700;font-size:.95rem;color:#f1f4f8;}
  .pd-windows{display:flex;gap:.3rem;flex-wrap:wrap;justify-content:flex-end;max-width:11rem;}
  .pd-win{width:.9rem;height:1.15rem;border-radius:3px;background:#232c36;border:1px solid #2e3843;}
  .pd-win.on{background:var(--mc-primary,#f97316);border-color:var(--mc-primary,#f97316);
    box-shadow:0 0 10px -1px var(--mc-primary,#f97316);}
  .pd-win.busy{animation:pdpulse 1.2s ease-in-out infinite;}
  @keyframes pdpulse{50%{opacity:.35;}}
  @media (prefers-reduced-motion:reduce){.pd-win.busy{animation:none;}}
  .pd-agents{display:grid;gap:.5rem;padding:.2rem .35rem 1rem 5.95rem;}
  .pd-agent{display:flex;justify-content:space-between;gap:.75rem;align-items:flex-start;
    background:#18202a;border:1px solid #26303b;border-radius:12px;padding:.65rem .8rem;}
  .pd-agent h3{font-size:.9rem;font-weight:700;margin:0 0 .15rem;color:#fff;}
  .pd-agent p{font-size:.8rem;margin:0;color:#aab5c1;line-height:1.45;}
  .pd-tag{font-size:.66rem;font-weight:700;text-transform:uppercase;letter-spacing:.05em;
    border-radius:999px;padding:.15rem .5rem;white-space:nowrap;}
  .pd-tag.on{background:rgba(249,115,22,.16);color:#ffb37a;}
  .pd-tag.off{background:#232c36;color:#8a96a3;}
  .pd-agent .btn{font-size:.75rem;white-space:nowrap;}
  .pd-ground{height:.9rem;margin:0 -.9rem;border-radius:0 0 18px 18px;
    background:linear-gradient(90deg,transparent,var(--mc-primary,#f97316),transparent);opacity:.55;}
  .pd-side .card{border-radius:14px;}
  .pd-pill{font-size:.7rem;font-weight:700;border-radius:999px;padding:.15rem .55rem;white-space:nowrap;}
  .pd-pill.concluido{background:rgba(22,163,74,.14);color:#15803d;}
  .pd-pill.erro{background:rgba(220,38,38,.12);color:#b91c1c;}
  .pd-pill.sem_agente{background:rgba(100,116,139,.15);color:#475569;}
  .pd-pill.andamento{background:rgba(249,115,22,.14);color:#c2410c;}
  [data-bs-theme="dark"] .pd-pill.concluido{color:#4ade80;}
  [data-bs-theme="dark"] .pd-pill.erro{color:#f87171;}
  [data-bs-theme="dark"] .pd-pill.sem_agente{color:#94a3b8;}
  [data-bs-theme="dark"] .pd-pill.andamento{color:#fdba74;}
  .pd-recent a{display:flex;justify-content:space-between;gap:.75rem;align-items:center;padding:.55rem 0;
    border-bottom:1px solid var(--bs-border-color);text-decoration:none;color:inherit;}
  .pd-recent a:last-child{border-bottom:0;}
  .pd-recent .t{font-weight:600;font-size:.86rem;}
  .pd-recent .m{font-size:.75rem;color:var(--bs-secondary-color);}
  @media (max-width:575.98px){
    .pd-floor summary{grid-template-columns:4.2rem 1fr;}
    .pd-windows{grid-column:1 / -1;justify-content:flex-start;max-width:none;}
    .pd-agents{padding-left:.35rem;}
    .pd-agent{flex-direction:column;}
  }
  .pd-stage{position:relative;height:clamp(440px,74vh,780px);border-radius:18px;overflow:hidden;background:#0d1218;
    box-shadow:0 18px 40px -24px rgba(0,0,0,.6);}
  .pd-canvas,.pd-canvas canvas{position:absolute;inset:0;width:100%;height:100%;display:block;touch-action:none;cursor:grab;}
  .pd-hud-top{position:absolute;top:0;left:0;right:0;display:flex;justify-content:space-between;align-items:flex-start;gap:.75rem;
    padding:.9rem 1rem 2rem;pointer-events:none;background:linear-gradient(rgba(13,18,24,.85),rgba(13,18,24,0));}
  .pd-hud-top>*{pointer-events:auto;}
  .pd-hud-title{color:#fff;font-weight:800;font-size:1.15rem;letter-spacing:-.01em;}
  .pd-hud-sub{color:#8a96a3;font-size:.76rem;font-variant-numeric:tabular-nums;}
  .pd-btn-ghost{background:rgba(255,255,255,.08);color:#e7ecf2;border:1px solid rgba(255,255,255,.16);border-radius:999px;
    font-size:.76rem;font-weight:600;padding:.3rem .75rem;line-height:1.3;}
  .pd-btn-ghost:hover{background:rgba(255,255,255,.16);color:#fff;}
  .pd-btn-ghost:focus-visible,.pd-elev button:focus-visible,.pd-card-x:focus-visible{outline:2px solid var(--mc-primary,#f97316);outline-offset:2px;}
  .pd-elev{position:absolute;right:.75rem;top:50%;transform:translateY(-50%);display:flex;flex-direction:column;gap:.15rem;
    background:rgba(13,18,24,.72);border:1px solid rgba(255,255,255,.08);border-radius:14px;padding:.35rem;max-height:calc(100% - 7rem);overflow-y:auto;}
  .pd-elev button{display:flex;align-items:center;gap:.45rem;font-size:.7rem;font-weight:600;color:#aab5c1;background:transparent;
    border:0;border-radius:8px;padding:.26rem .55rem;text-align:left;white-space:nowrap;}
  .pd-elev button:hover{color:#fff;background:rgba(255,255,255,.06);}
  .pd-elev button[aria-pressed="true"]{background:rgba(249,115,22,.2);color:#fff;}
  .pd-elev .dot{width:.5rem;height:.5rem;border-radius:50%;background:var(--c,#94a3b8);flex:none;}
  .pd-elev .curto{display:none;}
  .pd-dica{position:absolute;left:1rem;bottom:.85rem;color:#7d8996;font-size:.74rem;transition:opacity .4s;pointer-events:none;}
  .pd-dica.some{opacity:0;}
  .pd-card{position:absolute;left:1rem;bottom:1rem;width:min(22rem,calc(100% - 2rem));background:rgba(17,22,28,.95);
    border:1px solid #2a3440;border-radius:16px;padding:1rem 1.1rem;color:#e7ecf2;box-shadow:0 16px 32px -16px rgba(0,0,0,.7);}
  .pd-card h3{font-size:1.05rem;font-weight:800;margin:.1rem 0 .35rem;color:#fff;}
  .pd-card p{font-size:.84rem;color:#aab5c1;line-height:1.5;margin:0 0 .6rem;}
  .pd-card-andar{font-size:.68rem;text-transform:uppercase;letter-spacing:.08em;color:#8a96a3;font-weight:700;}
  .pd-card-meta{display:flex;gap:.6rem;align-items:center;font-size:.74rem;color:#7d8996;}
  .pd-card-acoes{display:flex;gap:.5rem;flex-wrap:wrap;margin-top:1rem;}
  .pd-card-acoes[hidden]{display:none;}
  .pd-card-x{position:absolute;top:.5rem;right:.6rem;background:none;border:0;color:#8a96a3;font-size:1.3rem;line-height:1;padding:.2rem .4rem;border-radius:8px;}
  .pd-card-x:hover{color:#fff;}
  .pd-chips{display:flex;flex-wrap:wrap;gap:.4rem;}
  .pd-chip{position:relative;display:inline-flex;align-items:center;border:1px solid var(--bs-border-color);border-radius:999px;
    padding:.3rem .75rem;font-size:.8rem;cursor:pointer;user-select:none;margin:0;}
  .pd-chip input{position:absolute;opacity:0;pointer-events:none;}
  .pd-chip:has(input:checked){background:rgba(249,115,22,.14);border-color:var(--mc-primary,#f97316);font-weight:600;}
  .pd-chip:has(input:focus-visible){outline:2px solid var(--mc-primary,#f97316);outline-offset:2px;}
  @media (min-width:576px){.pd-elev .full{display:inline;}}
  @media (max-width:575.98px){
    .pd-elev .full{display:none;} .pd-elev .curto{display:inline;}
    .pd-elev{right:.45rem;} .pd-dica{display:none;}
    .pd-card{left:.5rem;right:.5rem;bottom:.5rem;width:auto;}
    .pd-hud-title{font-size:1rem;}
  }
  @media (prefers-reduced-motion:reduce){.pd-dica{transition:none;}}
</style>

<div class="row g-4">
  <div class="col-12 col-xl-8">
    <div class="pd-stage" id="pdStage" hidden>
      <div class="pd-canvas" id="pd3d"></div>
      <div class="pd-hud-top">
        <div>
          <div class="pd-hud-title">{{ current_company.name }}</div>
          <div class="pd-hud-sub">{{ total_ativos }} de {{ total_agentes }} agentes ativos</div>
        </div>
        <div class="d-flex gap-2 flex-wrap justify-content-end">
          <button type="button" class="pd-btn-ghost" id="pdVisao">Visão geral</button>
          <button type="button" class="pd-btn-ghost" id="pdVerLista">Ver em lista</button>
        </div>
      </div>
      <nav class="pd-elev" aria-label="Ir para o andar">
        {% for andar in andares %}
        <button type="button" data-andar="{{ loop.index0 }}" aria-pressed="false" title="{{ andar.rotulo }} — {{ andar.nome }}">
          <span class="dot" style="--c: var(--pd-c{{ loop.index0 }})"></span>
          <span class="curto">{{ andar.curto }}</span><span class="full">{{ andar.nome }}</span>
        </button>
        {% endfor %}
      </nav>
      <div class="pd-dica" id="pdDica">Arraste para girar · role ou pince para aproximar · clique num andar para entrar</div>
      <div class="pd-card" id="pdCard" hidden role="dialog" aria-labelledby="pdCardNome">
        <button type="button" class="pd-card-x" id="pdCardX" aria-label="Fechar">×</button>
        <div class="pd-card-andar" id="pdCardAndar"></div>
        <h3 id="pdCardNome"></h3>
        <p id="pdCardAtrib"></p>
        <div class="pd-card-meta"><span class="pd-tag" id="pdCardStatus"></span><span id="pdCardAcesso"></span></div>
        <div class="pd-card-acoes" id="pdCardAcoes">
          <button type="button" class="btn btn-sm btn-light" id="pdCardConversar">Conversar</button>
          <button type="button" class="btn btn-sm pd-btn-ghost" id="pdCardReuniao">Chamar para reunião</button>
        </div>
      </div>
    </div>

    <div class="pd-tower" id="pdLista">
      <div class="pd-roof">
        <h1>{{ current_company.name }}</h1>
        <div class="d-flex align-items-center gap-2">
          <small>{{ total_ativos }} de {{ total_agentes }} agentes ativos</small>
          <button type="button" class="pd-btn-ghost" id="pdVer3d" hidden>Ver em 3D</button>
        </div>
      </div>
      {% for andar in andares %}
      <details class="pd-floor" id="andar-{{ andar.key }}">
        <summary>
          <span class="pd-level">{{ andar.rotulo }}</span>
          <span class="pd-name">{{ andar.nome }}</span>
          <span class="pd-windows" aria-label="{{ andar.ativos }} de {{ andar.agentes|length }} agentes ativos">
            {% for a in andar.agentes %}
            <span class="pd-win {% if a.ativo %}on{% endif %} {% if a.ocupado or a.em_reuniao %}busy{% endif %}" title="{{ a.nome }}"></span>
            {% endfor %}
          </span>
        </summary>
        <div class="pd-agents">
          {% for a in andar.agentes %}
          <div class="pd-agent" data-agente="{{ a.key }}">
            <div>
              <h3>{{ a.nome }}</h3>
              <p>{{ a.atribuicoes }}</p>
              <p class="mt-1" style="font-size:.72rem;color:#7d8996;">{{ a.acesso }}{% if a.ocupado %} · trabalhando em {{ a.ocupado }}{% endif %}{% if a.em_reuniao %} · em reunião{% endif %}</p>
            </div>
            <div class="d-flex flex-column align-items-end gap-2">
              {% if a.ativo %}<span class="pd-tag on">Ativo</span>{% else %}<span class="pd-tag off">Em breve</span>{% endif %}
              {% if a.pode_usar %}
              <div class="d-flex gap-1">
                <button type="button" class="btn btn-sm btn-light" onclick="pdEscolher('{{ a.key }}')">Conversar</button>
                <button type="button" class="btn btn-sm pd-btn-ghost" onclick="pdToggleReuniao('{{ a.key }}')">Reunião</button>
              </div>
              {% endif %}
            </div>
          </div>
          {% endfor %}
        </div>
      </details>
      {% endfor %}
      <div class="pd-ground"></div>
    </div>
  </div>

  <div class="col-12 col-xl-4 pd-side d-flex flex-column gap-3">
    <div class="card p-3">
      <h2 class="h6 fw-bold mb-1">Nova demanda</h2>
      {% if disponiveis %}
      <p class="small text-body-secondary mb-3">Descreva o que você precisa. A Recepção encaminha ao agente certo, ou escolha você mesmo.</p>
      <form method="post" action="/predio/chamados" class="d-flex flex-column gap-2" onsubmit="this.querySelector('button').disabled=true;">
        <textarea class="form-control" name="pedido" id="pdPedido" rows="4" maxlength="4000" required
          placeholder="Ex.: Quais clientes concentram mais receita e quem está devendo?"></textarea>
        <select class="form-select" name="agente" id="pdAgente" aria-label="Agente">
          <option value="auto">Recepção decide o agente</option>
          {% for a in disponiveis %}
          <option value="{{ a.key }}" {% if agente_pre == a.key %}selected{% endif %}>{{ a.nome }} — {{ a.andar }}</option>
          {% endfor %}
        </select>
        <button type="submit" class="btn btn-primary">Enviar ao prédio</button>
      </form>
      {% else %}
      <p class="small text-body-secondary mb-0">Os agentes ativos nesta fase atendem só administradores. Os andares abertos à equipe chegam nas próximas fases.</p>
      {% endif %}
    </div>

    {% if disponiveis %}
    <div class="card p-3" id="pdReuniaoCard">
      <h2 class="h6 fw-bold mb-1">Sala de reunião</h2>
      <p class="small text-body-secondary mb-3">Chame agentes para discutir uma pauta. Cada um traz os próprios dados e o Chief of Staff fecha a ata.</p>
      <form method="post" action="/predio/reunioes" id="pdReuniaoForm" class="d-flex flex-column gap-2">
        <div class="pd-chips" role="group" aria-label="Participantes">
          {% for a in disponiveis %}
          <label class="pd-chip"><input type="checkbox" name="participantes" value="{{ a.key }}"><span>{{ a.nome }}</span></label>
          {% endfor %}
        </div>
        <textarea class="form-control" name="pauta" id="pdPauta" rows="3" maxlength="4000" required
          placeholder="Ex.: Como fechar o ano com caixa positivo sem perder clientes?"></textarea>
        <div class="d-flex justify-content-between align-items-center gap-2">
          <span class="small text-body-secondary" id="pdReuniaoAviso">Escolha pelo menos um agente.</span>
          <button type="submit" class="btn btn-outline-primary btn-sm" id="pdReuniaoBtn" disabled>Iniciar reunião</button>
        </div>
      </form>
    </div>
    {% endif %}

    {% if role == "admin" %}
    <div class="card p-3">
      <h2 class="h6 fw-bold mb-1">Briefing semanal</h2>
      <p class="small text-body-secondary mb-3">O Chief of Staff resume caixa, inadimplência, entregas atrasadas, agenda e clientes sem contato.</p>
      <div class="d-flex flex-wrap gap-2 align-items-center">
        <form method="post" action="/predio/briefing/gerar" onsubmit="this.querySelector('button').disabled=true;">
          <button type="submit" class="btn btn-outline-primary btn-sm">Gerar briefing agora</button>
        </form>
        <form method="post" action="/predio/config" class="d-flex align-items-center gap-2">
          <input type="hidden" name="briefing_semanal" value="{{ '0' if briefing_semanal else '1' }}">
          <button type="submit" class="btn btn-sm {{ 'btn-success' if briefing_semanal else 'btn-outline-secondary' }}">
            {{ 'Toda segunda às 8h: ligado' if briefing_semanal else 'Ligar toda segunda às 8h' }}
          </button>
        </form>
      </div>
      {% if briefing_semanal %}<p class="small text-body-secondary mt-2 mb-0">Os administradores recebem notificação e e-mail quando o briefing fica pronto.</p>{% endif %}
    </div>
    {% endif %}

    <div class="card p-3">
      <h2 class="h6 fw-bold mb-2">{{ 'Chamados recentes' if role == 'admin' else 'Seus chamados' }}</h2>
      {% if recentes %}
      <div class="pd-recent">
        {% for c in recentes %}
        <a href="/predio/chamados/{{ c.id }}">
          <span>
            <span class="t d-block">{{ c.titulo }}</span>
            <span class="m">{{ ('Reunião · ' ~ c.participantes|join(', ')) if c.tipo == 'reuniao' else c.agente }} · {{ c.criado }}</span>
          </span>
          <span class="pd-pill {{ 'andamento' if c.em_andamento else c.status }}">{{ c.status_label }}</span>
        </a>
        {% endfor %}
      </div>
      {% else %}
      <p class="small text-body-secondary mb-0">Nenhum chamado ainda.</p>
      {% endif %}
    </div>
  </div>
</div>

<script type="application/json" id="pdDados">{{ {'andares': andares, 'empresa': current_company.name, 'agente_pre': agente_pre}|tojson }}</script>
<script>
function pdEscolher(key){
  var sel=document.getElementById('pdAgente'); if(!sel) return;
  sel.value=key;
  var t=document.getElementById('pdPedido');
  if(t){ t.scrollIntoView({behavior:'smooth',block:'center'}); t.focus({preventScroll:true}); }
}
function pdToggleReuniao(key, ligar){
  var cb=document.querySelector('#pdReuniaoForm input[value="'+key+'"]'); if(!cb) return;
  cb.checked = (ligar===undefined) ? !cb.checked : ligar;
  cb.dispatchEvent(new Event('change',{bubbles:true}));
  if(cb.checked){ var p=document.getElementById('pdPauta'); if(p && window.innerWidth<1200) p.scrollIntoView({behavior:'smooth',block:'center'}); }
}
(function(){
  var form=document.getElementById('pdReuniaoForm');
  if(form){
    var btn=document.getElementById('pdReuniaoBtn'), aviso=document.getElementById('pdReuniaoAviso');
    function atualizar(){
      var n=form.querySelectorAll('input[name=participantes]:checked').length;
      btn.disabled=n===0;
      aviso.textContent = n===0 ? 'Escolha pelo menos um agente.' : (n===1 ? '1 agente chamado.' : n+' agentes chamados.');
    }
    form.addEventListener('change', atualizar); atualizar();
    form.addEventListener('submit', function(e){
      if(form.dataset.enviando) return;
      var keys=[].map.call(form.querySelectorAll('input[name=participantes]:checked'), function(i){return i.value;});
      if(!keys.length){ e.preventDefault(); return; }
      btn.disabled=true; btn.textContent='Chamando os agentes…';
      if(typeof window.pdAnimarReuniao==='function'){
        e.preventDefault();
        var enviar=function(){ if(form.dataset.enviando) return; form.dataset.enviando='1'; form.submit(); };
        setTimeout(enviar, 3500);
        window.pdAnimarReuniao(keys).then(enviar, enviar);
      }
    });
  }
  var pre=JSON.parse(document.getElementById('pdDados').textContent).agente_pre;
  if(pre){
    var card=document.querySelector('.pd-agent[data-agente="'+pre+'"]');
    var det=card && card.closest('details'); if(det) det.open=true;
  }
})();
</script>
<script type="importmap">{"imports":{"three":"https://cdn.jsdelivr.net/npm/three@0.160.0/build/three.module.js","three/addons/":"https://cdn.jsdelivr.net/npm/three@0.160.0/examples/jsm/"}}</script>
<script type="module">
import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';

const PD = JSON.parse(document.getElementById('pdDados').textContent);
const stage = document.getElementById('pdStage');
const host = document.getElementById('pd3d');
const lista = document.getElementById('pdLista');

function temWebGL(){
  try { const c = document.createElement('canvas'); return !!(c.getContext('webgl2') || c.getContext('webgl')); }
  catch (e) { return false; }
}

if (temWebGL()) iniciar();

function iniciar(){
  const reduz = matchMedia('(prefers-reduced-motion: reduce)').matches;
  const N = PD.andares.length, W = 14, D = 9, H = 2.4;
  const CORES = ['#f97316','#22c55e','#a78bfa','#60a5fa','#f472b6','#facc15','#2dd4bf','#fb7185','#38bdf8','#c084fc','#fdba74','#94a3b8'];
  const PELES = ['#f1c9a5','#d9a27a','#a8714f','#7a4b32'];
  CORES.forEach((c, i) => stage.style.setProperty('--pd-c' + i, c));

  const renderer = new THREE.WebGLRenderer({ antialias: true, powerPreference: 'low-power' });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.5));
  renderer.setClearColor(0x0d1218);
  host.appendChild(renderer.domElement);

  stage.hidden = false; lista.hidden = true;
  document.getElementById('pdVer3d').hidden = false;

  const scene = new THREE.Scene();
  scene.fog = new THREE.Fog(0x0d1218, 70, 150);
  const camera = new THREE.PerspectiveCamera(38, 1, 0.5, 300);
  const controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true; controls.enablePan = false;
  controls.minDistance = 7; controls.maxDistance = 115; controls.maxPolarAngle = Math.PI * 0.49;
  controls.autoRotateSpeed = 0.6;

  scene.add(new THREE.HemisphereLight(0xdfe8f5, 0x1a1f26, 1.6));
  const sol = new THREE.DirectionalLight(0xffffff, 1.8); sol.position.set(20, 45, 30); scene.add(sol);

  const chao = new THREE.Mesh(new THREE.CircleGeometry(45, 48), new THREE.MeshLambertMaterial({ color: 0x151c24 }));
  chao.rotation.x = -Math.PI / 2; chao.position.y = -0.12; scene.add(chao);
  const anel = new THREE.Mesh(new THREE.RingGeometry(9.2, 9.6, 64), new THREE.MeshBasicMaterial({ color: 0xf97316, transparent: true, opacity: 0.35 }));
  anel.rotation.x = -Math.PI / 2; anel.position.y = -0.1; scene.add(anel);

  const G = {
    laje: new THREE.BoxGeometry(W, 0.22, D), coluna: new THREE.BoxGeometry(0.28, H, 0.28),
    vidro: new THREE.BoxGeometry(W - 0.06, H - 0.22, D - 0.06), nucleo: new THREE.BoxGeometry(1.7, H - 0.22, 1.9),
    mesa: new THREE.BoxGeometry(1.3, 0.08, 0.65), painel: new THREE.BoxGeometry(1.2, 0.62, 0.06),
    monitor: new THREE.BoxGeometry(0.5, 0.32, 0.04), sala: new THREE.BoxGeometry(3.6, H - 0.35, 3.4),
    tampo: new THREE.CylinderGeometry(0.85, 0.85, 0.08, 24), pe: new THREE.CylinderGeometry(0.1, 0.14, 0.66, 8),
    cadeira: new THREE.BoxGeometry(0.4, 0.42, 0.4), corpo: new THREE.CapsuleGeometry(0.19, 0.42, 4, 10),
    cabeca: new THREE.SphereGeometry(0.17, 14, 12), marca: new THREE.RingGeometry(0.3, 0.38, 24),
    frisoX: new THREE.BoxGeometry(W + 0.08, 0.26, 0.08), frisoZ: new THREE.BoxGeometry(0.08, 0.26, D + 0.08),
    toque: new THREE.CylinderGeometry(0.55, 0.55, 1.6, 10), invisivel: new THREE.MeshBasicMaterial(),
  };
  const lambert = (cor, extra) => new THREE.MeshLambertMaterial(Object.assign({ color: cor, transparent: true }, extra || {}));

  const MESAS = [[-3.3, 2.2], [-0.9, 2.2], [1.5, 2.2], [-3.3, -1.3], [-0.9, -1.3], [1.5, -1.3]];
  const SALA = { x: 4.9, z: -2.6 };
  const NUCLEO_X = -5.7;
  const andares = [], agentes = {}, clicaveis = [];

  function rotulo(texto, tam, cor){
    const c = document.createElement('canvas'), ctx = c.getContext('2d');
    const fonte = `700 ${tam}px system-ui, -apple-system, "Segoe UI", sans-serif`;
    ctx.font = fonte;
    const w = Math.ceil(ctx.measureText(texto).width) + tam, h = Math.ceil(tam * 1.7);
    c.width = w; c.height = h;
    ctx.font = fonte; ctx.fillStyle = 'rgba(13,18,24,.78)';
    const r = h / 2; ctx.beginPath(); ctx.moveTo(r, 0); ctx.arcTo(w, 0, w, h, r); ctx.arcTo(w, h, 0, h, r); ctx.arcTo(0, h, 0, 0, r); ctx.arcTo(0, 0, w, 0, r); ctx.fill();
    ctx.fillStyle = cor || '#f1f4f8'; ctx.textBaseline = 'middle'; ctx.fillText(texto, tam / 2, h / 2 + 1);
    const tex = new THREE.CanvasTexture(c); tex.colorSpace = THREE.SRGBColorSpace;
    const s = new THREE.Sprite(new THREE.SpriteMaterial({ map: tex, transparent: true, depthTest: false }));
    s.renderOrder = 10;
    s.scale.set(w * 0.0105, h * 0.0105, 1);
    return s;
  }

  function criarAvatar(ag, cor, idx){
    const g = new THREE.Group();
    const ativo = ag.ativo;
    const mCorpo = lambert(ativo ? cor : 0x5b6573, { opacity: ativo ? 1 : 0.45 });
    const mCabeca = lambert(ativo ? PELES[idx % PELES.length] : 0x6b7583, { opacity: ativo ? 1 : 0.45 });
    const corpo = new THREE.Mesh(G.corpo, mCorpo); corpo.position.y = 0.52;
    const cabeca = new THREE.Mesh(G.cabeca, mCabeca); cabeca.position.y = 1.1;
    g.add(corpo, cabeca);
    const marca = new THREE.Mesh(G.marca, new THREE.MeshBasicMaterial({ color: 0xf97316, transparent: true, opacity: 0.95, side: THREE.DoubleSide }));
    marca.rotation.x = -Math.PI / 2; marca.position.y = 0.13; marca.visible = false; g.add(marca);
    const nome = rotulo(ag.nome, 26); nome.position.y = 1.55; nome.visible = false; g.add(nome);
    // área de toque invisível, maior que o personagem, para facilitar o clique (principalmente no celular)
    const toque = new THREE.Mesh(G.toque, G.invisivel); toque.position.y = 0.75; toque.visible = false; g.add(toque);
    [corpo, cabeca, toque].forEach(m => { m.userData.agente = ag.key; clicaveis.push(m); });
    g.userData = { key: ag.key, marca, nome, mats: [mCorpo, mCabeca], base: [mCorpo.opacity, mCabeca.opacity] };
    return g;
  }

  PD.andares.forEach((andar, i) => {
    const nivel = N - 1 - i, y = nivel * H, cor = CORES[i % CORES.length];
    const grupo = new THREE.Group(); grupo.position.y = y; scene.add(grupo);
    const mats = [];
    const reg = (m) => { mats.push({ m, base: m.opacity }); return m; };
    const laje = new THREE.Mesh(G.laje, reg(lambert(0x2a333e))); grupo.add(laje);
    const mCol = reg(lambert(0x3d4856));
    [[-1, -1], [1, -1], [-1, 1], [1, 1]].forEach(([sx, sz]) => {
      const c = new THREE.Mesh(G.coluna, mCol); c.position.set(sx * (W / 2 - 0.14), H / 2, sz * (D / 2 - 0.14)); grupo.add(c);
    });
    const vidro = new THREE.Mesh(G.vidro, reg(lambert(0x9fc3e6, { opacity: 0.1, depthWrite: false })));
    vidro.position.y = H / 2 + 0.05; grupo.add(vidro);
    const mFriso = reg(new THREE.MeshBasicMaterial({ color: cor, transparent: true, opacity: 0.9 }));
    [[0, D / 2, G.frisoX], [0, -D / 2, G.frisoX], [W / 2, 0, G.frisoZ], [-W / 2, 0, G.frisoZ]].forEach(([fx, fz, geo]) => {
      const f = new THREE.Mesh(geo, mFriso); f.position.set(fx, 0.02, fz); grupo.add(f);
    });
    const nucleo = new THREE.Mesh(G.nucleo, reg(lambert(0x1b232c))); nucleo.position.set(NUCLEO_X, H / 2, 0); grupo.add(nucleo);
    const sala = new THREE.Mesh(G.sala, reg(lambert(cor, { opacity: 0.13, depthWrite: false }))); sala.position.set(SALA.x, H / 2 - 0.05, SALA.z); grupo.add(sala);
    const tampo = new THREE.Mesh(G.tampo, reg(lambert(0x8b6b4e))); tampo.position.set(SALA.x, 0.74, SALA.z); grupo.add(tampo);
    const pe = new THREE.Mesh(G.pe, reg(lambert(0x5b4636))); pe.position.set(SALA.x, 0.42, SALA.z); grupo.add(pe);
    const mCad = reg(lambert(0x3d4652));
    const assentos = [];
    for (let k = 0; k < 6; k++) {
      const a = (k / 6) * Math.PI * 2 + Math.PI / 6;
      const cx = SALA.x + Math.cos(a) * 1.25, cz = SALA.z + Math.sin(a) * 1.25;
      const cad = new THREE.Mesh(G.cadeira, mCad); cad.position.set(cx, 0.32, cz); grupo.add(cad);
      assentos.push(new THREE.Vector3(cx, 0.1, cz));
    }
    [laje, vidro, nucleo, sala].forEach(m => { m.userData.andar = i; clicaveis.push(m); });

    const mMesa = reg(lambert(0x5d6878));
    andar.agentes.forEach((ag, j) => {
      const [mx, mz] = MESAS[j % MESAS.length];
      const mesa = new THREE.Mesh(G.mesa, mMesa); mesa.position.set(mx, 0.76, mz); grupo.add(mesa);
      const painel = new THREE.Mesh(G.painel, mMesa); painel.position.set(mx, 0.42, mz - 0.28); grupo.add(painel);
      const mMon = reg(ag.ativo ? new THREE.MeshBasicMaterial({ color: cor, transparent: true }) : lambert(0x222a33));
      const mon = new THREE.Mesh(G.monitor, mMon); mon.position.set(mx, 0.98, mz - 0.18); grupo.add(mon);
      const av = criarAvatar(ag, cor, i + j);
      av.position.set(mx, 0, mz + 0.62); av.rotation.y = Math.PI;
      grupo.add(av);
      agentes[ag.key] = { av, ag, andar: i, mesa: av.position.clone(), monitor: mMon, ocupado: ag.ocupado > 0, reuniao: false, fase: Math.random() * 6 };
    });

    const placa = rotulo(`${andar.rotulo} · ${andar.nome}`, 40, '#f1f4f8');
    placa.position.set(-W / 2 - 0.4 - placa.scale.x / 2, 0.45, D / 2); grupo.add(placa);
    andares.push({ grupo, mats, assentos, placa, y });
  });

  const topo = N * H;
  const cobertura = new THREE.Mesh(new THREE.BoxGeometry(W + 0.3, 0.3, D + 0.3), lambert(0x232b35)); cobertura.position.y = topo + 0.05; scene.add(cobertura);
  const letreiro = rotulo(PD.empresa, 64, '#ffffff'); letreiro.position.set(0, topo + 1.4, 0); scene.add(letreiro);

  const iCob = 0, salaCob = andares[iCob];
  let assentoLivre = 0;
  function sentarNaReuniao(key, animar){
    const a = agentes[key]; if (!a || a.reuniao) return Promise.resolve();
    a.reuniao = true;
    a.av.visible = true;
    a.av.userData.mats.forEach((m, n) => { m.opacity = a.av.userData.base[n]; });
    a.av.userData.nome.visible = foco !== null;
    const destino = salaCob.assentos[assentoLivre++ % salaCob.assentos.length].clone();
    destino.y += salaCob.y;
    scene.attach(a.av);
    const olhar = () => a.av.lookAt(SALA.x, a.av.position.y, SALA.z);
    if (!animar || reduz) { a.av.position.copy(destino); olhar(); return Promise.resolve(); }
    const p = a.av.position.clone();
    const porta = new THREE.Vector3(NUCLEO_X + 1.25, p.y, 0.4);
    const subida = new THREE.Vector3(NUCLEO_X + 1.25, destino.y, 0.4);
    return mover(a.av, [porta, subida, destino]).then(olhar);
  }

  const tweens = [];
  function mover(obj, pontos){
    return new Promise(res => {
      const etapas = []; let de = obj.position.clone();
      pontos.forEach(pt => { const dist = de.distanceTo(pt); etapas.push({ de, para: pt.clone(), dur: Math.max(0.2, dist / (Math.abs(pt.y - de.y) > 0.5 ? 14 : 5)) }); de = pt.clone(); });
      tweens.push({ obj, etapas, k: 0, t: 0, res });
    });
  }
  const suave = t => t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2;

  let cam = null;
  function voarCamera(pos, alvo, dur){
    if (reduz || !dur) { camera.position.copy(pos); controls.target.copy(alvo); controls.update(); return; }
    cam = { de: camera.position.clone(), dePara: controls.target.clone(), pos, alvo, t: 0, dur };
  }

  let foco = null;
  const visaoGeral = () => {
    const alvo = new THREE.Vector3(0, N * H * 0.5, 0);
    const longe = camera.aspect < 0.85 ? 1.3 : 1;
    return { pos: new THREE.Vector3(36 * longe, N * H * 0.72, 44 * longe), alvo };
  };
  function aplicarFoco(i){
    foco = i;
    andares.forEach((a, k) => {
      // ao entrar num andar, os de cima saem de cena (como tirar o telhado) e os de baixo ficam translúcidos
      a.grupo.visible = i === null || k >= i;
      const f = (i === null || k === i) ? 1 : 0.08;
      a.mats.forEach(({ m, base }) => { m.opacity = base * f; });
      // em tela estreita o painel do elevador já nomeia os andares; as placas laterais sairiam cortadas
      a.placa.visible = host.clientWidth >= 576 && (i === null || k === i);
    });
    cobertura.visible = letreiro.visible = i === null;
    Object.values(agentes).forEach(a => {
      const mostrar = (i === null) || a.andar === i || (a.reuniao && i === iCob);
      const f = mostrar ? 1 : 0.08;
      a.av.userData.mats.forEach((m, n) => { m.opacity = a.av.userData.base[n] * f; });
      a.av.userData.nome.visible = i !== null && mostrar;
      if (a.reuniao) a.av.visible = i === null || i === iCob;
    });
    document.querySelectorAll('.pd-elev button').forEach(b => b.setAttribute('aria-pressed', String(Number(b.dataset.andar) === i)));
    controls.autoRotate = i === null && !reduz && !interagiu;
  }
  function focar(i){
    if (i === null) { const v = visaoGeral(); voarCamera(v.pos, v.alvo, 0.9); aplicarFoco(null); return; }
    const y = andares[i].y;
    const alvo = new THREE.Vector3(0, y + 0.5, 0);
    const longe = camera.aspect < 0.85 ? 1.9 : (camera.aspect < 1.3 ? 1.3 : 1);
    voarCamera(new THREE.Vector3(9 * longe, y + 11 * longe, 16 * longe), alvo, 0.9);
    aplicarFoco(i);
  }

  const card = document.getElementById('pdCard');
  let cardKey = null;
  function abrirCard(key){
    const a = agentes[key]; if (!a) return;
    cardKey = key;
    const ag = a.ag, andar = PD.andares[a.andar];
    document.getElementById('pdCardAndar').textContent = `${andar.rotulo} · ${andar.nome}`;
    document.getElementById('pdCardNome').textContent = ag.nome;
    document.getElementById('pdCardAtrib').textContent = ag.atribuicoes;
    document.getElementById('pdCardAcesso').textContent = ag.acesso;
    const st = document.getElementById('pdCardStatus');
    const estado = a.reuniao ? 'Em reunião' : (a.ocupado ? 'Trabalhando' : (ag.ativo ? 'Ativo' : 'Em breve'));
    st.textContent = estado; st.className = 'pd-tag ' + (ag.ativo ? 'on' : 'off');
    document.getElementById('pdCardAcoes').hidden = !ag.pode_usar;
    atualizarBotaoReuniao();
    card.hidden = false;
  }
  function atualizarBotaoReuniao(){
    if (!cardKey) return;
    const cb = document.querySelector(`#pdReuniaoForm input[value="${cardKey}"]`);
    document.getElementById('pdCardReuniao').textContent = cb && cb.checked ? 'Tirar da reunião' : 'Chamar para reunião';
  }
  document.getElementById('pdCardX').onclick = () => { card.hidden = true; cardKey = null; };
  document.getElementById('pdCardConversar').onclick = () => { if (cardKey) pdEscolher(cardKey); };
  document.getElementById('pdCardReuniao').onclick = () => { if (cardKey) pdToggleReuniao(cardKey); };
  const formReuniao = document.getElementById('pdReuniaoForm');
  if (formReuniao) formReuniao.addEventListener('change', () => {
    formReuniao.querySelectorAll('input[name=participantes]').forEach(cb => {
      const a = agentes[cb.value]; if (a) a.av.userData.marca.visible = cb.checked;
    });
    atualizarBotaoReuniao();
  });

  window.pdAnimarReuniao = (keys) => {
    card.hidden = true; cardKey = null;
    focar(iCob);
    return Promise.all(keys.map((k, n) => new Promise(r => setTimeout(r, n * 250)).then(() => sentarNaReuniao(k, true))));
  };

  document.querySelectorAll('.pd-elev button').forEach(b => b.addEventListener('click', () => focar(Number(b.dataset.andar))));
  document.getElementById('pdVisao').onclick = () => { card.hidden = true; focar(null); };
  document.getElementById('pdVerLista').onclick = () => { stage.hidden = true; lista.hidden = false; };
  document.getElementById('pdVer3d').onclick = () => { lista.hidden = true; stage.hidden = false; redimensionar(); };

  let interagiu = false;
  controls.addEventListener('start', () => {
    interagiu = true; controls.autoRotate = false; cam = null;
    document.getElementById('pdDica').classList.add('some');
  });

  const ray = new THREE.Raycaster(), ptr = new THREE.Vector2();
  let toque = null;
  function acertar(ev){
    const r = renderer.domElement.getBoundingClientRect();
    ptr.set(((ev.clientX - r.left) / r.width) * 2 - 1, -((ev.clientY - r.top) / r.height) * 2 + 1);
    ray.setFromCamera(ptr, camera);
    const hits = ray.intersectObjects(clicaveis, false);
    for (const h of hits) {
      const key = h.object.userData.agente; if (!key) continue;
      const a = agentes[key];
      if (foco === null || a.andar === foco || (a.reuniao && foco === iCob)) return { agente: key };
    }
    for (const h of hits) {
      const i = h.object.userData.andar;
      if (i !== undefined && (foco === null || i === foco)) return { andar: i };
    }
    return null;
  }
  renderer.domElement.addEventListener('pointerdown', ev => { toque = { x: ev.clientX, y: ev.clientY }; });
  renderer.domElement.addEventListener('pointerup', ev => {
    if (!toque || Math.hypot(ev.clientX - toque.x, ev.clientY - toque.y) > 6) { toque = null; return; }
    toque = null;
    const alvo = acertar(ev);
    if (!alvo) return;
    if (alvo.agente) { const a = agentes[alvo.agente]; if (foco !== a.andar && !(a.reuniao && foco === iCob)) focar(a.andar); abrirCard(alvo.agente); }
    else if (alvo.andar !== foco) { card.hidden = true; focar(alvo.andar); }
  });
  let pendenteHover = false;
  renderer.domElement.addEventListener('pointermove', ev => {
    if (ev.pointerType !== 'mouse' || pendenteHover) return;
    pendenteHover = true;
    requestAnimationFrame(() => { pendenteHover = false; renderer.domElement.style.cursor = acertar(ev) ? 'pointer' : 'grab'; });
  });

  function redimensionar(){
    const w = host.clientWidth, h = host.clientHeight; if (!w || !h) return;
    renderer.setSize(w, h, false); camera.aspect = w / h;
    // desloca o enquadramento para a esquerda, para o painel do elevador não cobrir o prédio
    const elev = document.querySelector('.pd-elev');
    const desloc = elev ? Math.round(elev.offsetWidth / 2) : 0;
    if (desloc) camera.setViewOffset(w, h, desloc, 0, w, h); else camera.clearViewOffset();
    camera.updateProjectionMatrix();
  }
  new ResizeObserver(() => { redimensionar(); aplicarFoco(foco); }).observe(host);
  redimensionar();

  let visivel = true;
  new IntersectionObserver(es => { visivel = es[0].isIntersecting; }).observe(host);

  PD.andares.forEach(andar => andar.agentes.forEach(ag => { if (ag.em_reuniao) sentarNaReuniao(ag.key, false); }));
  const v0 = visaoGeral(); camera.position.copy(v0.pos); controls.target.copy(v0.alvo); controls.update();
  aplicarFoco(null);
  if (PD.agente_pre && agentes[PD.agente_pre]) { focar(agentes[PD.agente_pre].andar); abrirCard(PD.agente_pre); }

  const relogio = new THREE.Clock();
  renderer.setAnimationLoop(() => {
    if (!visivel || stage.hidden) return;
    const dt = Math.min(relogio.getDelta(), 0.05), t = relogio.elapsedTime;
    if (cam) {
      cam.t += dt / cam.dur; const k = suave(Math.min(cam.t, 1));
      camera.position.lerpVectors(cam.de, cam.pos, k); controls.target.lerpVectors(cam.dePara, cam.alvo, k);
      if (cam.t >= 1) cam = null;
    }
    for (let n = tweens.length - 1; n >= 0; n--) {
      const tw = tweens[n], e = tw.etapas[tw.k];
      tw.t += dt / e.dur; const k = suave(Math.min(tw.t, 1));
      tw.obj.position.lerpVectors(e.de, e.para, k);
      if (Math.abs(e.para.y - e.de.y) < 0.5) tw.obj.lookAt(e.para.x, tw.obj.position.y, e.para.z);
      if (tw.t >= 1) { tw.k++; tw.t = 0; if (tw.k >= tw.etapas.length) { tweens.splice(n, 1); tw.res(); } }
    }
    if (!reduz) {
      Object.values(agentes).forEach(a => {
        if (!(a.ocupado || a.reuniao) || tweens.some(tw => tw.obj === a.av)) return;
        a.av.children[0].position.y = 0.52 + Math.sin(t * 5 + a.fase) * 0.035;
        a.av.children[1].position.y = 1.1 + Math.sin(t * 5 + a.fase) * 0.035;
        if (a.ocupado && a.monitor.isMeshBasicMaterial) a.monitor.opacity = (foco === null || foco === a.andar ? 1 : 0.1) * (0.65 + 0.35 * Math.sin(t * 6 + a.fase));
      });
    }
    controls.update();
    renderer.render(scene, camera);
  });
}
</script>
{% endblock %}
"""

TEMPLATES["predio_chamado.html"] = r"""
{% extends "base.html" %}
{% block content %}
<style>
  .pc-wrap{max-width:52rem;}
  .pc-card{border-radius:14px;}
  .pc-meta{font-size:.8rem;color:var(--bs-secondary-color);}
  .pc-pill{font-size:.72rem;font-weight:700;border-radius:999px;padding:.2rem .6rem;white-space:nowrap;}
  .pc-pill.concluido{background:rgba(22,163,74,.14);color:#15803d;}
  .pc-pill.erro{background:rgba(220,38,38,.12);color:#b91c1c;}
  .pc-pill.sem_agente{background:rgba(100,116,139,.15);color:#475569;}
  .pc-pill.andamento{background:rgba(249,115,22,.14);color:#c2410c;}
  [data-bs-theme="dark"] .pc-pill.concluido{color:#4ade80;}
  [data-bs-theme="dark"] .pc-pill.erro{color:#f87171;}
  [data-bs-theme="dark"] .pc-pill.sem_agente{color:#94a3b8;}
  [data-bs-theme="dark"] .pc-pill.andamento{color:#fdba74;}
  .pc-pedido{white-space:pre-wrap;font-size:.92rem;background:var(--bs-tertiary-bg);border-radius:10px;padding:.8rem 1rem;}
  .pc-quem{font-size:.7rem;font-weight:700;text-transform:uppercase;letter-spacing:.06em;color:var(--bs-secondary-color);margin-bottom:.35rem;}
  .pc-contrib{border-left:3px solid var(--mc-primary,#f97316);padding:.1rem 0 .1rem 1rem;margin-bottom:1.1rem;}
  .pc-passos{list-style:none;padding:0;margin:0;font-size:.82rem;}
  .pc-passos li{display:flex;gap:.6rem;padding:.3rem 0;color:var(--bs-secondary-color);font-variant-numeric:tabular-nums;}
  .pc-passos li b{color:var(--bs-body-color);font-weight:600;}
  .pc-result{font-size:.93rem;line-height:1.6;}
  .pc-result h1,.pc-result h2,.pc-result h3{font-size:1.02rem;font-weight:700;margin:1.2rem 0 .5rem;text-wrap:balance;}
  .pc-result table{width:100%;font-size:.84rem;margin:.6rem 0 1rem;border-collapse:collapse;font-variant-numeric:tabular-nums;}
  .pc-result th,.pc-result td{border-bottom:1px solid var(--bs-border-color);padding:.35rem .5rem;text-align:left;vertical-align:top;}
  .pc-result th{font-weight:700;background:var(--bs-tertiary-bg);}
  .pc-table-scroll{overflow-x:auto;}
  .pc-spin{display:inline-block;width:.9rem;height:.9rem;border:2px solid currentColor;border-right-color:transparent;
    border-radius:50%;animation:pcspin .8s linear infinite;vertical-align:-.1rem;}
  @keyframes pcspin{to{transform:rotate(360deg);}}
  @media (prefers-reduced-motion:reduce){.pc-spin{animation:none;}}
</style>

<div class="pc-wrap">
  <a href="/predio" class="btn btn-outline-secondary btn-sm mb-3">← Voltar ao prédio</a>

  <div class="card pc-card p-3 p-md-4 mb-3">
    <div class="d-flex justify-content-between align-items-start gap-3 flex-wrap mb-2">
      <div>
        <h1 class="h5 fw-bold mb-1" id="pcTitulo">{{ ch.titulo }}</h1>
        <div class="pc-meta"><span id="pcAgente">{{ ch.agente }} · {{ ch.andar }}</span> · aberto em {{ ch.criado }}</div>
      </div>
      <span class="pc-pill {{ 'andamento' if ch.em_andamento else ch.status }}" id="pcStatus">
        {% if ch.em_andamento %}<span class="pc-spin" aria-hidden="true"></span> {% endif %}{{ ch.status_label }}
      </span>
    </div>
    <div class="pc-meta" id="pcMotivo">{% if ch.motivo %}Encaminhamento: {{ ch.motivo }}{% endif %}</div>
  </div>

  <div id="pcConversa" class="d-flex flex-column gap-3"></div>

  <div id="fim"></div>
  <form method="post" action="/predio/chamados/{{ ch.id }}/mensagens" id="pcForm"
        class="card pc-card p-3 mt-3" {% if not ch.pode_continuar %}hidden{% endif %}
        onsubmit="this.querySelector('button').disabled=true;">
    <label for="pcMensagem" class="form-label small fw-semibold mb-1">Continuar com {{ ch.agente }}</label>
    <textarea class="form-control mb-2" id="pcMensagem" name="mensagem" rows="3" maxlength="4000" required
      placeholder="Ex.: Cruze esses clientes com tarefas atrasadas e cobranças vencidas."></textarea>
    <div class="d-flex justify-content-between align-items-center gap-2 flex-wrap">
      <span class="pc-meta">O agente lembra de toda a conversa e do que já consultou.</span>
      <button type="submit" class="btn btn-primary btn-sm">Enviar</button>
    </div>
  </form>
</div>

<script src="https://cdn.jsdelivr.net/npm/marked@12.0.2/marked.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/dompurify@3.1.6/dist/purify.min.js"></script>
<script>
(function(){
  var dados = {{ ch|tojson }};
  var assinatura = '';
  function el(tag, cls, txt){ var e=document.createElement(tag); if(cls) e.className=cls; if(txt!=null) e.textContent=txt; return e; }
  function markdown(alvo, md){
    if(window.marked && window.DOMPurify){
      alvo.innerHTML=DOMPurify.sanitize(marked.parse(md));
      alvo.querySelectorAll('table').forEach(function(t){
        var w=el('div','pc-table-scroll'); t.parentNode.insertBefore(w,t); w.appendChild(t);
      });
    } else { alvo.style.whiteSpace='pre-wrap'; alvo.textContent=md; }
  }
  function listaPassos(passos){
    var ul=el('ul','pc-passos mb-3');
    passos.forEach(function(p){
      var li=el('li'); li.appendChild(el('span',null,p.em||''));
      li.appendChild(el('b',null,(p.ok?'':'⚠ ')+(p.rotulo||p.ferramenta))); ul.appendChild(li);
    });
    return ul;
  }
  function esperando(texto){
    var w=el('div','text-body-secondary small');
    w.innerHTML='<span class="pc-spin" aria-hidden="true"></span> ';
    w.appendChild(document.createTextNode(texto)); return w;
  }
  function turno(t, i, agente){
    var card=el('div','card pc-card p-3 p-md-4');
    var reuniao=!!t.contribuicoes;
    card.appendChild(el('div','pc-quem', reuniao ? 'Pauta' : (i===0 ? 'Pedido' : 'Você')));
    card.appendChild(el('div','pc-pedido mb-3', t.pergunta));
    if(reuniao){
      t.contribuicoes.forEach(function(c){
        var bloco=el('div','pc-contrib');
        bloco.appendChild(el('div','pc-quem',c.nome));
        if(c.passos.length) bloco.appendChild(listaPassos(c.passos));
        if(c.texto){ var r=el('div','pc-result'); markdown(r,c.texto); bloco.appendChild(r); }
        else if(c.erro){ bloco.appendChild(el('div','alert alert-warning mb-0 small',c.erro)); }
        else if(c.aguardando){ bloco.appendChild(esperando(c.nome+' está preparando a contribuição…')); }
        card.appendChild(bloco);
      });
      var todos=t.contribuicoes.every(function(c){ return c.texto||c.erro; });
      if(t.resposta){ card.appendChild(el('div','pc-quem mt-2','Ata · '+agente)); var ata=el('div','pc-result'); markdown(ata,t.resposta); card.appendChild(ata); }
      else if(t.erro){ card.appendChild(el('div','alert alert-danger mb-0',t.erro)); }
      else if(t.aguardando && todos){ card.appendChild(esperando(agente+' está escrevendo a ata…')); }
      return card;
    }
    if(t.passos.length) card.appendChild(listaPassos(t.passos));
    if(t.resposta){
      card.appendChild(el('div','pc-quem',agente));
      var r=el('div','pc-result'); markdown(r,t.resposta); card.appendChild(r);
    } else if(t.erro){
      card.appendChild(el('div','alert alert-danger mb-0',t.erro));
    } else if(t.aguardando){
      card.appendChild(esperando(agente+' está trabalhando. Esta página atualiza sozinha.'));
    }
    return card;
  }
  function aplicar(d){
    document.getElementById('pcTitulo').textContent=d.titulo;
    document.getElementById('pcAgente').textContent = d.tipo==='reuniao'
      ? 'Reunião com '+d.participantes.join(', ')
      : d.agente+' · '+d.andar;
    document.getElementById('pcMotivo').textContent=d.motivo?('Encaminhamento: '+d.motivo):'';
    var st=document.getElementById('pcStatus');
    st.className='pc-pill '+(d.em_andamento?'andamento':d.status);
    st.textContent=d.status_label;
    var nova=JSON.stringify([d.turnos,d.status]);
    if(nova!==assinatura){
      assinatura=nova;
      var c=document.getElementById('pcConversa'); c.innerHTML='';
      d.turnos.forEach(function(t,i){ c.appendChild(turno(t,i,d.agente)); });
    }
    document.getElementById('pcForm').hidden=!d.pode_continuar;
  }
  aplicar(dados);
  if(location.hash==='#fim' || dados.turnos.length>1){
    var ult=document.getElementById('pcConversa').lastElementChild;
    if(ult) ult.scrollIntoView({block:'start'});
  }
  if(dados.em_andamento){
    var t=setInterval(async function(){
      try{
        var r=await fetch('/predio/chamados/'+dados.id+'/status');
        if(!r.ok) return;
        var d=await r.json(); aplicar(d);
        if(!d.em_andamento) clearInterval(t);
      }catch(e){}
    },3000);
  }
})();
</script>
{% endblock %}
"""

if hasattr(templates_env.loader, "mapping"):
    templates_env.loader.mapping = TEMPLATES

print("[predio] Prédio de agentes carregado.")

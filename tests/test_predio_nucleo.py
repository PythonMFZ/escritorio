"""Núcleo do Prédio: integridade dos agentes, páginas, chamado com ferramentas, aprovação/rejeição, custo e
recuperação de ações interrompidas."""
import json
import os
import sys
import time
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _base import preparar, check, fim, criar_empresa, login, esperar_chamado, resposta_texto  # noqa: E402
import httpx2  # noqa: E402

REQS = []


def handler(req):
    b = json.loads(req.content)
    REQS.append(b)
    ultimo = b["messages"][-1]
    resultado = ultimo["role"] == "user" and isinstance(ultimo["content"], list) and ultimo["content"] \
        and ultimo["content"][0].get("type") == "tool_result"
    fmt = (b.get("output_config") or {}).get("format")
    if fmt:  # Recepção
        return resposta_texto(json.dumps({"agente": "controller", "andar_ideal": "controller", "titulo": "Inadimplência",
                                          "motivo": "Financeiro"}), b["model"])
    if not resultado and "agente Controller" in b.get("system", ""):
        return httpx2.Response(200, json={"id": "m", "type": "message", "role": "assistant", "model": b["model"],
                                          "content": [{"type": "tool_use", "id": "t1", "name": "fin_inadimplencia", "input": {}}],
                                          "stop_reason": "tool_use", "stop_sequence": None,
                                          "usage": {"input_tokens": 1000, "output_tokens": 200}})
    return resposta_texto("## Resumo\nGSW deve R$ 9.000,00.", b["model"])


A, c = preparar(handler)
from sqlmodel import Session, select  # noqa: E402
cid, us = criar_empresa(A)
with Session(A.engine) as s:
    g = A.Client(company_id=cid, name="GSW Imports"); s.add(g); s.commit(); s.refresh(g); GSW = g.id
    s.add(A.OfficeFinancialEntry(company_id=cid, created_by_user_id=us["admin"], entry_kind="receber", status="aberto", client_id=GSW,
                                 description="Honorários", due_date=(datetime.utcnow() - timedelta(days=20)).date().isoformat(),
                                 amount_expected_brl=9000))
    s.commit()

print("[1] Integridade")
A._pr_sincronizar_agentes(True)
ativos = [a for a in A._PREDIO_AGENTES.values() if a.get("ativo")]
faltando = [(a["key"], f) for a in ativos for f in a.get("ferramentas", []) if f not in A._PR_TOOLS]
check(not faltando, f"toda ferramenta de agente ativo existe {faltando[:3]}")
check(len(ativos) >= 35, f"agentes ativos ({len(ativos)})")
acima = []
for a in ativos:
    tools, _ = A._pr_montar_tools(a["ferramentas"])
    soma = sum(A._pr_campos(t["input_schema"]) for t in tools if t.get("strict"))
    if soma > A._PR_STRICT_ORCAMENTO:
        acima.append(a["key"])
check(not acima, f"ferramentas strict dentro do orçamento em todos os agentes {acima}")
equipe = [a for a in ativos if a["papeis"] != A._PR_ADMIN]
check(not [a["key"] for a in equipe if any(f.startswith(("fin_resumo", "fin_receita", "fin_despesas", "fin_contratos", "fin_inadimplencia"))
                                          for f in a["ferramentas"])], "agentes da equipe sem financeiro do escritório")

print("[2] Páginas")
login(c, "admin@t.com")
h = c.get("/predio")
check(h.status_code == 200 and all(x in h.text for x in ('id="automacoes"', 'id="custos-ia"', 'id="pessoas-agentes"')), "home do admin com os cards")
check(c.get("/predio/custos").status_code == 200, "página de custos")
login(c, "ana@t.com")
h = c.get("/predio")
check(h.status_code == 200 and 'id="automacoes"' not in h.text and 'id="custos-ia"' not in h.text, "home da equipe sem cards de admin")
check(c.get("/predio/custos", follow_redirects=False).status_code == 303, "equipe não vê custos")

print("[3] Chamado pela Recepção, com ferramenta")
login(c, "admin@t.com")
r = c.post("/predio/chamados", data={"pedido": "Quem está devendo?", "agente": "auto"}, follow_redirects=False)
chid = int(r.headers["location"].rsplit("/", 1)[-1])
d = esperar_chamado(c, chid)
check(d["status"] == "concluido" and d["agente"] == "Controller" and "9.000" in d["resultado"], "encaminhado ao Controller e concluído")
check(any(p["rotulo"] == "Verificou a inadimplência" and p["ok"] for p in d["passos"]), "passo da ferramenta registrado")
res = json.loads(REQS[-1]["messages"][-1]["content"][0]["content"])
check(res["por_cliente"][0]["cliente"] == "GSW Imports" and res["por_cliente"][0]["itens"][0].get("titulo_id"), "dados reais com titulo_id")
check(REQS[0]["model"] == "claude-haiku-5-5" and REQS[1]["model"] == "claude-opus-5-5", "Recepção no Haiku, Controller no Opus")
with Session(A.engine) as s:
    usos = s.exec(select(A.PredioUso).where(A.PredioUso.chamado_id == chid)).all()
    check(len(usos) == 3 and all(u.custo_usd > 0 for u in usos), "custo registrado por chamada à API")

print("[4] Aprovação e rejeição")
with Session(A.engine) as s:
    A._PR_EXEC.chamado_id, A._PR_EXEC.agente_key = chid, "atendimento"
    t1 = A._pr_t_propor_tarefa(s, cid, "GSW", "Revisar fluxo de caixa", "Conferir novembro", "", "", "alta")
    t2 = A._pr_t_propor_tarefa(s, cid, "GSW", "Ligar para o banco", "", "", "", "media")
check(t1.get("ok") and t2.get("ok"), "tarefas propostas")
login(c, "ana@t.com")
c.post(f"/predio/acoes/{t1['proposta_id']}/aprovar", data={"assunto": "Revisar fluxo de caixa — nov", "corpo": "Conferir novembro"})
c.post(f"/predio/acoes/{t2['proposta_id']}/rejeitar", data={"motivo": "Já ligamos ontem"})
with Session(A.engine) as s:
    a1, a2 = s.get(A.PredioAcao, t1["proposta_id"]), s.get(A.PredioAcao, t2["proposta_id"])
    tarefa = s.exec(select(A.Task).where(A.Task.client_id == GSW)).first()
    check(a1.status == "executada" and tarefa and tarefa.title == "Revisar fluxo de caixa — nov", "equipe aprova tarefa (com edição)")
    check(a2.status == "rejeitada" and "Já ligamos ontem" in a2.resultado, "rejeição guarda o motivo")

print("[5] Ação interrompida por reinício")
with Session(A.engine) as s:
    presa = A.PredioAcao(company_id=cid, tipo="emitir_faturamento", titulo="x", status="executando",
                         decidido_em=datetime.utcnow() - timedelta(minutes=20))
    s.add(presa); s.commit(); s.refresh(presa); PID = presa.id
A._pr_resetar_acoes_interrompidas()
with Session(A.engine) as s:
    check(s.get(A.PredioAcao, PID).status == "erro", "presa vira Falhou, liberando o Tentar de novo")
time.sleep(1)
fim()

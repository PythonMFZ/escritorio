"""Automações do prédio: pós-reunião, faturamento, cobrança, contas a pagar, briefing e relatório mensal."""
import json
import os
import sys
import time
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _base import preparar, check, fim, resposta_texto  # noqa: E402

REQS = []


def handler(req):
    b = json.loads(req.content)
    REQS.append(b)
    return resposta_texto(model=b["model"])


A, c = preparar(handler)
EMAILS = []
A._smtp_send_email = lambda **kw: EMAILS.append(kw)
from sqlmodel import Session, select  # noqa: E402
hoje = A._pr_hoje()
with Session(A.engine) as s:
    co = A.Company(name="M"); s.add(co); s.commit(); s.refresh(co); cid = co.id
    for k, e in (("admin", "admin@t.com"), ("equipe", "ana@t.com")):
        u = A.User(name=k, email=e, password_hash=A.hash_password("senha123")); s.add(u); s.commit(); s.refresh(u)
        s.add(A.Membership(user_id=u.id, company_id=cid, role=k))
    gsw = A.Client(company_id=cid, name="GSW", email="contato@gsw.com"); alfa = A.Client(company_id=cid, name="Alfa", email="fin@alfa.com")
    s.add(gsw); s.add(alfa); s.commit(); s.refresh(gsw); s.refresh(alfa)
    velha = A.Meeting(company_id=cid, client_id=gsw.id, created_by_user_id=1, title="Antiga", notion_status="notes_ready",
                      transcript_text="x", updated_at=datetime.utcnow() - timedelta(days=2))
    s.add(velha); s.commit(); s.refresh(velha)
    GSW, ALFA, VELHA = gsw.id, alfa.id, velha.id
c.post("/login", data={"email": "admin@t.com", "password": "senha123"})

def chamados(agente=None):
    with Session(A.engine) as s:
        q = select(A.PredioChamado).where(A.PredioChamado.roteamento == "agenda")
        if agente: q = q.where(A.PredioChamado.agente_key == agente)
        return s.exec(q.order_by(A.PredioChamado.id)).all()

def reg(chave):
    with Session(A.engine) as s:
        return A._au_reg(s, cid, chave)

print("[1] Painel")
home = c.get("/predio").text
check('id="automacoes"' in home and home.count("Rodar agora") >= 6 and "Depois de cada reunião" in home, "card com as automações")
for k in ("pos_reuniao", "faturamento_mensal", "cobranca_atrasos", "contas_pagar_semanal"):
    c.post(f"/predio/automacoes/{k}/alternar")
check(all(reg(k).ativo for k in ("pos_reuniao", "faturamento_mensal", "cobranca_atrasos", "contas_pagar_semanal")), "as 4 primeiras ligadas")
c.post("/login", data={"email": "ana@t.com", "password": "senha123"})
c.post("/predio/automacoes/pos_reuniao/alternar")
check(reg("pos_reuniao").ativo and 'id="automacoes"' not in c.get("/predio").text, "equipe não vê nem mexe")
c.post("/login", data={"email": "admin@t.com", "password": "senha123"})

print("[2] Depois de cada reunião")
with Session(A.engine) as s:
    nova = A.Meeting(company_id=cid, client_id=GSW, created_by_user_id=1, title="Comitê GSW", notion_status="notes_ready",
                     transcript_text="Decidimos renegociar o banco.")
    s.add(nova); s.commit(); s.refresh(nova); NOVA = nova.id
A._au_pos_reuniao(cid, reg("pos_reuniao"))
A._au_pos_reuniao(cid, reg("pos_reuniao"))
ch = chamados("secretario_reunioes")
check(len(ch) == 1 and f"#{NOVA}" in ch[0].pedido and "reu_propor_followup" in ch[0].pedido, "um chamado para a reunião nova (antiga e repetição ignoradas)")
check(A._au_reivindicar(cid, "pos_reuniao", "x") and not A._au_reivindicar(cid, "pos_reuniao", "x"), "evento só é reivindicado uma vez (2 workers)")
check("Comitê GSW" in ch[0].titulo and reg("pos_reuniao").ultimo_chamado_id == ch[0].id, "última execução registrada")
with Session(A.engine) as s:
    A._PR_EXEC.chamado_id, A._PR_EXEC.agente_key = ch[0].id, "secretario_reunioes"
    check("participantes" in A._au_t_propor_followup(s, cid, NOVA, "Resumo", "Olá, segue o resumo do que decidimos hoje e os próximos passos.")["erro"],
          "sem participantes cadastrados: não propõe")
    for nome, email in (("João (GSW)", "joao@gsw.com"), ("Maria (GSW)", "maria@gsw.com"), ("Sem email", "invalido")):
        u = A.User(name=nome, email=email, password_hash="x"); s.add(u); s.commit(); s.refresh(u)
        s.add(A.MeetingParticipante(meeting_id=NOVA, user_id=u.id, company_id=cid, client_id=GSW))
    s.commit()
    check("Assunto" in A._au_t_propor_followup(s, cid, NOVA, "", "curto")["erro"], "follow-up sem texto recusado")
    f = A._au_t_propor_followup(s, cid, NOVA, "Resumo do comitê", "Olá, segue o resumo do que decidimos hoje e os próximos passos de cada lado.")
    check(f["ok"] and s.get(A.PredioAcao, f["proposta_id"]).destinatario == "joao@gsw.com, maria@gsw.com"
          and "contato@gsw.com" not in s.get(A.PredioAcao, f["proposta_id"]).destinatario, "follow-up para os participantes (não o e-mail da empresa)")
    check("aguardando" in A._au_t_propor_followup(s, cid, NOVA, "x2", "Olá, segue o resumo do que decidimos hoje e os próximos passos.")["erro"], "não duplica")
c.post(f"/predio/acoes/{f['proposta_id']}/aprovar", data={"assunto": "Resumo do comitê — editado", "corpo": "Texto revisado pelo sócio com o resumo da reunião."})
check([e["to_email"] for e in EMAILS][-2:] == ["joao@gsw.com", "maria@gsw.com"] and "contato@gsw.com" not in [e["to_email"] for e in EMAILS] and EMAILS[-1]["subject"] == "Resumo do comitê — editado",
      "aprovado com edição e enviado um e-mail para cada participante")
check("reu_propor_followup" in A._PREDIO_AGENTES["secretario_reunioes"]["ferramentas"], "Secretário tem a ferramenta")
r = c.post("/predio/automacoes/pos_reuniao/rodar", follow_redirects=False)
check(len(chamados("secretario_reunioes")) == 2 and r.headers["location"].startswith("/predio/chamados/"), "rodar agora pega a reunião recente ainda não processada")

orig = A._pr_agora_brt
def em(dia, hora, dsem=None):
    base = datetime(2026, 12, dia, hora, 0)
    A._pr_agora_brt = lambda: base

print("[3] Faturamento do mês")
c.post("/predio/automacoes/faturamento_mensal/config", data={"dia": "5"})
em(3, 12); A._au_faturamento(cid, reg("faturamento_mensal"))
check(not chamados("faturamento"), "antes do dia escolhido não roda")
em(5, 8); A._au_faturamento(cid, reg("faturamento_mensal"))
check(not chamados("faturamento"), "no dia, antes das 9h, não roda")
em(5, 9); A._au_faturamento(cid, reg("faturamento_mensal")); A._au_faturamento(cid, reg("faturamento_mensal"))
fat = chamados("faturamento")
check(len(fat) == 1 and "2026-12" in fat[0].pedido and "fat_propor_emissao" in fat[0].pedido, "roda uma vez no mês")
em(20, 15); A._au_faturamento(cid, reg("faturamento_mensal"))
check(len(chamados("faturamento")) == 1, "não repete no mesmo mês")

print("[4] Cobrança de atrasos")
em(7, 11)  # segunda
A._au_cobranca(cid, reg("cobranca_atrasos"))
check(not chamados("cobranca") and reg("cobranca_atrasos").ultimo_resumo == "Nada a cobrar hoje.", "sem atraso: não abre chamado (sem custo)")
with Session(A.engine) as s:
    E = A.OfficeFinancialEntry
    for cl, dias in ((GSW, 20), (ALFA, 5)):
        s.add(E(company_id=cid, created_by_user_id=1, entry_kind="receber", status="aberto", client_id=cl, description="Honorários",
                due_date=(datetime(2026, 12, 7) - timedelta(days=dias)).date().isoformat(), amount_expected_brl=9000))
    s.add(E(company_id=cid, created_by_user_id=1, entry_kind="receber", status="aberto", client_id=ALFA, description="Recente",
            due_date="2026-12-06", amount_expected_brl=1000))
    s.add(A.PredioAcao(company_id=cid, client_id=ALFA, tipo="email_cobranca", titulo="x", status="executada"))
    s.commit()
A._pr_hoje = lambda: datetime(2026, 12, 8).date()
em(8, 9); A._au_cobranca(cid, reg("cobranca_atrasos"))
check(not chamados("cobranca"), "antes das 10h não roda")
em(8, 10); A._au_cobranca(cid, reg("cobranca_atrasos")); A._au_cobranca(cid, reg("cobranca_atrasos"))
cb = chamados("cobranca")
check(len(cb) == 1 and "GSW" in cb[0].pedido and "21 dias" in cb[0].pedido and "Alfa" not in cb[0].pedido,
      "só quem está em atraso e não foi cobrado nos últimos 7 dias; uma vez por dia")
em(12, 11)  # sábado
A._au_cobranca(cid, reg("cobranca_atrasos"))
check(len(chamados("cobranca")) == 1, "fim de semana não roda")

print("[5] Contas a pagar da semana")
em(8, 9)  # terça
A._au_contas_pagar(cid, reg("contas_pagar_semanal"))
check(not chamados("contas_pagar"), "terça não roda")
em(14, 8); A._au_contas_pagar(cid, reg("contas_pagar_semanal")); A._au_contas_pagar(cid, reg("contas_pagar_semanal"))
cp = chamados("contas_pagar")
check(len(cp) == 1 and "cp_agenda" in cp[0].pedido, "segunda 8h, uma vez por semana")
A._pr_agora_brt = orig

print("[6] Ciclo, desligar e custo")
for _ in range(80):
    if all(x.status not in ("na_fila", "roteando", "trabalhando") for x in chamados()): break
    time.sleep(0.2)
check(all(x.status == "concluido" for x in chamados()), "chamados das automações concluídos")
home = c.get("/predio").text
check("este mês:" in home and "US$" in home, "card mostra execuções e custo do mês")
c.post("/predio/automacoes/contas_pagar_semanal/alternar")
check(not reg("contas_pagar_semanal").ativo, "desligar")
n = len(chamados())
with Session(A.engine) as s:
    m3 = A.Meeting(company_id=cid, client_id=GSW, created_by_user_id=1, title="Outra", notion_status="notes_ready", transcript_text="y")
    s.add(m3); s.commit()
A._au_ciclo()
novos = chamados()[n:]
check(any(x.agente_key == "secretario_reunioes" and "Outra" in x.titulo for x in novos)
      and not any(x.agente_key == "contas_pagar" for x in novos), "o ciclo do agendador dispara as ligadas (e não a desligada)")
time.sleep(1.5)

print("[7] Briefing antes da reunião")
A._pr_agora_brt = lambda: datetime(2026, 12, 9, 18, 0)
A._pr_hoje = lambda: datetime(2026, 12, 9).date()
with Session(A.engine) as s:
    mem_u = A.User(name="Carla", email="carla@t.com", password_hash=A.hash_password("senha123")); s.add(mem_u); s.commit(); s.refresh(mem_u)
    s.add(A.Membership(user_id=mem_u.id, company_id=cid, role="equipe"))
    mb = A.AgendaMembro(company_id=cid, user_id=mem_u.id, nome="Carla"); s.add(mb); s.commit(); s.refresh(mb)
    b1 = A.AgendaBooking(company_id=cid, membro_id=mb.id, client_id=GSW, data="2026-12-10", hora_inicio="14:00", status="confirmado")
    b2 = A.AgendaBooking(company_id=cid, membro_id=mb.id, solicitante_nome="Lead Novo", data="2026-12-10", hora_inicio="16:00", status="pendente")
    b3 = A.AgendaBooking(company_id=cid, membro_id=mb.id, client_id=GSW, data="2026-12-10", hora_inicio="09:00", status="cancelado")
    b4 = A.AgendaBooking(company_id=cid, membro_id=mb.id, client_id=GSW, data="2026-12-12", hora_inicio="10:00", status="confirmado")
    for b in (b1, b2, b3, b4): s.add(b)
    s.commit(); MEM = mem_u.id
c.post("/predio/automacoes/briefing_reuniao/alternar")
A._pr_agora_brt = lambda: datetime(2026, 12, 9, 16, 0)
A._au_briefing(cid, reg("briefing_reuniao"))
check(not chamados("gestor_carteira"), "antes das 17h não roda")
A._pr_agora_brt = lambda: datetime(2026, 12, 9, 17, 5)
A._au_briefing(cid, reg("briefing_reuniao")); A._au_briefing(cid, reg("briefing_reuniao"))
br = chamados("gestor_carteira")
check(len(br) == 2 and all("10/12/2026" in x.pedido for x in br), "um briefing por reunião de amanhã (cancelada e outros dias fora)")
check(all(x.created_by_user_id == MEM and x.papel_solicitante == "equipe" for x in br), "aberto em nome de quem atende (recebe o aviso)")
check(any("GSW" in x.pedido and "cli_panorama" in x.pedido for x in br) and any("Lead Novo" in x.pedido and "lead" in x.pedido for x in br),
      "cliente: panorama e última reunião; contato sem cadastro: pauta de primeira conversa")

print("[8] Relatório mensal dos clientes")
with Session(A.engine) as s:
    for cl in (GSW, ALFA):
        s.add(A.ContratoCliente(company_id=cid, client_id=cl, nome_contrato="Assessoria", valor_cents=100000, status="ativo", data_inicio="2026-01-01"))
    s.add(A.ContratoCliente(company_id=cid, client_id=GSW, nome_contrato="Outro", valor_cents=1, status="ativo", data_inicio="2026-01-01"))
    s.commit()
c.post("/predio/automacoes/relatorio_mensal/alternar")
A._pr_agora_brt = lambda: datetime(2026, 12, 4, 12, 0)
A._au_relatorio(cid, reg("relatorio_mensal"))
check(not chamados("relatorio_mensal"), "antes do dia 5 não roda")
A._pr_agora_brt = lambda: datetime(2026, 12, 5, 9, 30)
A._au_relatorio(cid, reg("relatorio_mensal")); A._au_relatorio(cid, reg("relatorio_mensal"))
rel = chamados("relatorio_mensal")
check(len(rel) == 2 and all("11/2026" in x.pedido and "rel_gerar_relatorio" in x.pedido for x in rel),
      "um relatório por cliente com contrato ativo (mês anterior), sem repetir")
check(any("GSW" in x.titulo for x in rel) and any("Alfa" in x.titulo for x in rel), "GSW e Alfa")
r = c.post("/predio/automacoes/relatorio_mensal/rodar", follow_redirects=False)
check(len(chamados("relatorio_mensal")) == 2 and "Todos os clientes" in reg("relatorio_mensal").ultimo_resumo,
      "rodar agora não duplica quem já tem o relatório do mês")
c.post("/predio/automacoes/relatorio_mensal/config", data={"dia": "8"})
check(reg("relatorio_mensal").config_json and json.loads(reg("relatorio_mensal").config_json)["dia"] == 8, "dia configurável")
home = c.get("/predio").text
check("Briefing antes da reunião" in home and "Relatório mensal dos clientes" in home and home.count("Rodar agora") >= 6, "card com as 6 automações")

print("[9] Renovações e vendas adicionais")
A._pr_agora_brt = lambda: datetime(2026, 12, 2, 12, 0)
c.post("/predio/automacoes/renovacoes/alternar")
A._au_renovacoes(cid, reg("renovacoes"))
check(not chamados("sucesso_cliente"), "antes do dia 3 não roda")
with Session(A.engine) as s:
    s.add(A.ContratoCliente(company_id=cid, client_id=ALFA, nome_contrato="CFO externo", valor_cents=1500000, status="ativo",
                            data_inicio="2026-01-01", data_fim="2027-02-15"))
    s.add(A.ContratoCliente(company_id=cid, client_id=GSW, nome_contrato="Longo", valor_cents=1, status="ativo",
                            data_inicio="2026-01-01", data_fim="2027-12-31"))
    s.commit()
A._pr_agora_brt = lambda: datetime(2026, 12, 3, 9, 10)
A._au_renovacoes(cid, reg("renovacoes")); A._au_renovacoes(cid, reg("renovacoes"))
rn = chamados("sucesso_cliente")
check(len(rn) == 1 and "CFO externo" in rn[0].pedido and "15/02/2027" in rn[0].pedido and "Longo" not in rn[0].pedido,
      "uma vez no mês, com os contratos que vencem em 90 dias")

print("[10] Lead do site")
with Session(A.engine) as s:
    s.add(A.LeadCredito(nome="Velho", empresa="Antiga SA", criado_em="2026-11-01 10:00")); s.commit()
c.post("/predio/automacoes/lead_site/alternar")
check(json.loads(reg("lead_site").config_json).get("lead_credito", 0) >= 1, "marco inicial gravado ao ligar")
A._au_lead_site(cid, reg("lead_site"))
check(not chamados("chief_of_staff"), "lead anterior à ativação não é processado")
r = c.post("/api/lead/valuation", json={"nome": "Joana", "email": "joana@metal.com", "empresa": "Metalúrgica Sul",
                                        "setor": "Indústria", "faturamento_anual": 40000000, "ebitda": 6000000,
                                        "valuation_estimado": "R$ 30 mi"})
with Session(A.engine) as s:
    s.add(A.LeadCredito(nome="Pedro", empresa="Construtora Norte", cnpj="11222333000144", finalidade="Capital de giro",
                        valor=2000000, criado_em="2026-12-03 10:00"))
    s.commit()
check(r.status_code == 200, "lead de valuation agora é gravado")
A._au_lead_site(cid, reg("lead_site")); A._au_lead_site(cid, reg("lead_site"))
ld = chamados("chief_of_staff")
check(len(ld) == 2 and any("Metalúrgica Sul" in x.pedido and "valuation" in x.pedido.lower() for x in ld)
      and any("Construtora Norte" in x.pedido and "Capital de giro" in x.pedido for x in ld), "um chamado por lead novo, sem repetir")
check(all("cos_delegar" in x.pedido and "'prospeccao'" in x.pedido and "'propostas'" in x.pedido for x in ld),
      "Chief of Staff passa à Prospecção e à Propostas")
with Session(A.engine) as s:
    leads = A._cm_t_leads(s, cid, 30)["leads"]
check(any(l["origem"] == "Site — calculadora de valuation" for l in leads), "com_leads mostra os leads de valuation")

print("[11] Cliente novo")
c.post("/predio/automacoes/cliente_novo/alternar")
A._au_cliente_novo(cid, reg("cliente_novo"))
check(not chamados("compliance"), "clientes antigos não passam pelo KYC automático")
with Session(A.engine) as s:
    n1 = A.Client(company_id=cid, name="Nova Indústria Ltda", cnpj="99888777000166"); s.add(n1); s.commit()
A._au_cliente_novo(cid, reg("cliente_novo")); A._au_cliente_novo(cid, reg("cliente_novo"))
kyc = chamados("compliance")
check(len(kyc) == 1 and "Nova Indústria" in kyc[0].pedido and "99888777000166" in kyc[0].pedido and "comp_conflitos" in kyc[0].pedido,
      "KYC do cliente novo, uma vez")
print("[12] Marketing")
c.post("/predio/automacoes/boletim_mercado/alternar")
c.post("/predio/automacoes/calendario_bimestral/alternar")
A._pr_agora_brt = lambda: datetime(2026, 12, 15, 6, 30)  # terça
A._au_boletim(cid, reg("boletim_mercado"))
A._pr_agora_brt = lambda: datetime(2026, 12, 14, 6, 30)  # segunda, antes das 7h
A._au_boletim(cid, reg("boletim_mercado"))
check(not chamados("inteligencia_mercado"), "boletim: só segunda a partir das 7h")
A._pr_agora_brt = lambda: datetime(2026, 12, 14, 7, 5)
A._au_boletim(cid, reg("boletim_mercado")); A._au_boletim(cid, reg("boletim_mercado"))
bo = chamados("inteligencia_mercado")
check(len(bo) == 1 and "mkt_noticias" in bo[0].pedido, "boletim uma vez por semana")
A._pr_agora_brt = lambda: datetime(2026, 11, 20, 10, 0)  # novembro (ímpar): não é véspera de bimestre
A._au_calendario(cid, reg("calendario_bimestral"))
A._pr_agora_brt = lambda: datetime(2026, 12, 10, 10, 0)  # dezembro, antes do dia 15
A._au_calendario(cid, reg("calendario_bimestral"))
check(not chamados("agencia_redes"), "calendário: só no mês anterior ao bimestre, a partir do dia escolhido")
A._pr_agora_brt = lambda: datetime(2026, 12, 15, 9, 0)
A._au_calendario(cid, reg("calendario_bimestral")); A._au_calendario(cid, reg("calendario_bimestral"))
cal = chamados("agencia_redes")
check(len(cal) == 1 and "jan–fev/2027" in cal[0].titulo and "mkt_gerar_calendario" in cal[0].pedido
      and "mkt_propor_envio_agencia" in cal[0].pedido, "calendário de jan–fev/2027, uma vez")
A._pr_agora_brt = lambda: datetime(2027, 3, 5, 10, 0)  # março (ímpar): rodar agora prepara o próximo (mai–jun)
c.post("/predio/automacoes/calendario_bimestral/rodar")
check(any("mai–jun/2027" in x.titulo for x in chamados("agencia_redes")), "rodar agora em mês ímpar prepara o bimestre seguinte")
home = c.get("/predio").text
check(all(x in home for x in ("Renovações e vendas adicionais", "Lead do site", "Cliente novo", "Boletim de mercado",
                              "Calendário de posts")) and home.count("Rodar agora") >= 11, "card com as 11 automações")
time.sleep(1.5)
fim()

"""Gera o PDF de resumo da plataforma Maffezzolli Capital."""
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.lib import colors
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    HRFlowable, KeepTogether
)
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_JUSTIFY

OUT = "/home/user/escritorio/resumo_maffezzolli_plataforma.pdf"

doc = SimpleDocTemplate(
    OUT,
    pagesize=A4,
    leftMargin=2.2*cm, rightMargin=2.2*cm,
    topMargin=2.2*cm, bottomMargin=2.2*cm,
    title="Resumo da Plataforma Maffezzolli Capital",
    author="Maffezzolli Capital",
)

# ── Paleta ───────────────────────────────────────────────────────────────────
LARANJA  = colors.HexColor("#EA5820")
AZUL     = colors.HexColor("#1E3A5F")
CINZA    = colors.HexColor("#64748B")
CINZACLARO = colors.HexColor("#F1F5F9")
BRANCO   = colors.white

# ── Estilos ──────────────────────────────────────────────────────────────────
styles = getSampleStyleSheet()

titulo_doc = ParagraphStyle("titulo_doc", parent=styles["Normal"],
    fontSize=22, fontName="Helvetica-Bold", textColor=AZUL,
    spaceAfter=4, alignment=TA_LEFT)

subtitulo_doc = ParagraphStyle("subtitulo_doc", parent=styles["Normal"],
    fontSize=11, fontName="Helvetica", textColor=CINZA,
    spaceAfter=16, alignment=TA_LEFT)

h1 = ParagraphStyle("h1", parent=styles["Normal"],
    fontSize=13, fontName="Helvetica-Bold", textColor=BRANCO,
    spaceBefore=14, spaceAfter=6, backColor=AZUL,
    leftIndent=-8, rightIndent=-8, leading=18)

h2 = ParagraphStyle("h2", parent=styles["Normal"],
    fontSize=11, fontName="Helvetica-Bold", textColor=AZUL,
    spaceBefore=10, spaceAfter=4)

h3 = ParagraphStyle("h3", parent=styles["Normal"],
    fontSize=10, fontName="Helvetica-Bold", textColor=LARANJA,
    spaceBefore=6, spaceAfter=2)

body = ParagraphStyle("body", parent=styles["Normal"],
    fontSize=9.5, fontName="Helvetica", textColor=colors.HexColor("#1E293B"),
    spaceAfter=5, leading=14, alignment=TA_JUSTIFY)

bullet = ParagraphStyle("bullet", parent=styles["Normal"],
    fontSize=9.5, fontName="Helvetica", textColor=colors.HexColor("#1E293B"),
    spaceAfter=3, leading=13, leftIndent=14, bulletIndent=4)

label_tag = ParagraphStyle("label_tag", parent=styles["Normal"],
    fontSize=8, fontName="Helvetica-Bold", textColor=CINZA,
    spaceAfter=2, leading=11)

rodape_style = ParagraphStyle("rodape", parent=styles["Normal"],
    fontSize=8, fontName="Helvetica", textColor=CINZA,
    alignment=TA_CENTER)

def H1(text):
    return Paragraph(f"&nbsp;&nbsp;{text}", h1)

def H2(text):
    return Paragraph(text, h2)

def H3(text):
    return Paragraph(text, h3)

def P(text):
    return Paragraph(text, body)

def B(text, icon="•"):
    return Paragraph(f"{icon} &nbsp;{text}", bullet)

def Sp(h=6):
    return Spacer(1, h)

def HR():
    return HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#E2E8F0"), spaceAfter=8, spaceBefore=4)

# ── Conteúdo ─────────────────────────────────────────────────────────────────
story = []

# Cabeçalho
story += [
    Paragraph("MAFFEZZOLLI CAPITAL", ParagraphStyle("marca", parent=styles["Normal"],
        fontSize=9, fontName="Helvetica-Bold", textColor=LARANJA, spaceAfter=2)),
    Paragraph("Resumo da Plataforma & Módulo Augur", titulo_doc),
    Paragraph("Documento interno · Uso em apresentações e briefings · Maio 2026", subtitulo_doc),
    HR(),
    Sp(4),
]

# ── 1. Visão Geral ────────────────────────────────────────────────────────────
story += [
    H1("1. Visão Geral"),
    Sp(6),
    P("A plataforma <b>Escritório</b> é um sistema web proprietário da <b>Maffezzolli Capital</b> "
      "que centraliza ferramentas de análise financeira, CRM, inteligência artificial e gestão de "
      "projetos — usadas internamente pelos consultores e compartilhadas com clientes via link seguro. "
      "É construída em <b>Python (FastAPI + Jinja2)</b>, hospedada em "
      "<b>app.maffezzollicapital.com.br</b>."),
    Sp(4),
]

# Stack info table
stack_data = [
    ["Stack", "Python 3.11 · FastAPI · Jinja2 · SQLite/PostgreSQL"],
    ["Hospedagem", "app.maffezzollicapital.com.br"],
    ["IA", "Claude (Anthropic) · Whisper (OpenAI)"],
    ["Integrações", "Bacen/SCR · Notion · Conta Azul · Stripe"],
]
t = Table(stack_data, colWidths=[3.5*cm, 12.5*cm])
t.setStyle(TableStyle([
    ("FONTNAME", (0,0), (-1,-1), "Helvetica"),
    ("FONTNAME", (0,0), (0,-1), "Helvetica-Bold"),
    ("FONTSIZE", (0,0), (-1,-1), 9),
    ("TEXTCOLOR", (0,0), (0,-1), AZUL),
    ("TEXTCOLOR", (1,0), (1,-1), colors.HexColor("#1E293B")),
    ("BACKGROUND", (0,0), (-1,-1), CINZACLARO),
    ("ROWBACKGROUNDS", (0,0), (-1,-1), [CINZACLARO, BRANCO]),
    ("GRID", (0,0), (-1,-1), 0.3, colors.HexColor("#E2E8F0")),
    ("PADDING", (0,0), (-1,-1), 6),
    ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
    ("LEFTPADDING", (0,0), (-1,-1), 10),
]))
story += [t, Sp(12)]

# ── 2. AUGUR ─────────────────────────────────────────────────────────────────
story += [
    H1("2. Augur — Assistente IA Financeiro"),
    Sp(6),
    P("O <b>Augur</b> é o assistente de inteligência artificial da Maffezzolli Capital. "
      "Funciona como um chatbot especializado em finanças empresariais, capaz de responder "
      "perguntas sobre a situação de cada cliente com base em dados reais carregados no sistema."),
    Sp(6),
    H3("Como funciona"),
    B("Cada cliente tem uma <b>base de conhecimento privada e isolada</b> — documentos (PDF, Excel, CSV, "
      "imagens) carregados pelo consultor são indexados e injetados no contexto da conversa."),
    B("O Augur recebe automaticamente os <b>dados financeiros do cliente</b> (receita, caixa, dívida, "
      "score de crédito, EBITDA, histórico de consultas) antes de responder."),
    B("Usa o modelo <b>Claude (Anthropic)</b> para geração de respostas contextualizadas."),
    B("Cada usuário tem <b>sessões privadas com histórico de 21 dias</b>: pode criar novas conversas, "
      "renomear e retomar conversas anteriores por um painel lateral."),
    B("Suporta <b>anexos</b> em múltiplos formatos diretamente na conversa."),
    B("Usuários avaliam as respostas (👍👎) para feedback de qualidade."),
    B("Monetizado por pergunta via sistema interno de <b>créditos (CreditWallet)</b> — "
      "cada empresa tem saldo próprio."),
    Sp(6),
    H3("Quem usa"),
    P("Consultores e analistas da Maffezzolli e, em alguns casos, clientes finais com acesso "
      "concedido pela equipe."),
    Sp(12),
]

# ── 3. Ferramentas ────────────────────────────────────────────────────────────
story += [H1("3. Ferramentas Proprietárias"), Sp(6)]

# 3.1 Viabilidade
story += [
    H2("3.1 Ferramenta de Viabilidade Imobiliária v3"),
    P("Motor completo de análise econômica para projetos imobiliários — replica e supera a planilha "
      "MFZ II interna, com geração de fluxo de caixa, TIR, VPL e compartilhamento de resultados."),
    Sp(4),
    H3("Funcionalidades"),
    B("Tipologias multiuso: residencial, comercial, garagem — com diferencial por andar e mix de produtos."),
    B("Custos CUB/m² com coeficientes de equivalência + itens extras (elevadores, recreação)."),
    B("Distribuição mensal de custos de obra em curva S realista."),
    B("Comercialização em fases: lançamento → pós-lançamento com ajuste de preços e velocidade de vendas."),
    B("Fluxo de caixa mensal com correção monetária (INCC/CUB) e projeção de valor futuro (VF)."),
    B("Indicadores: TIR (VP e VF), VPL, exposição máxima de capital, margem VGV, margem s/ custo."),
    B("Análise de sensibilidade (cenários Realista / Otimista +15% / Pessimista −15%)."),
    B("Financiamento bancário (CCB) integrado: cálculo de TIR alavancada, DSCR, exposição com crédito."),
    B("Resultados salvos e compartilháveis via link público permanente."),
    Sp(12),
]

# 3.2 CRI
story += [
    H2("3.2 Simulação de CRI — Maffezzolli como originadora"),
    P("Módulo integrado à Ferramenta de Viabilidade que simula a emissão de um <b>CRI (Certificado "
      "de Recebíveis Imobiliários)</b> com a Maffezzolli Capital como estruturadora e distribuidora."),
    Sp(4),
    H3("Parâmetros de entrada"),
    B("Volume de emissão, indexador (IPCA+ ou CDI+), spread e prazo de carência."),
    B("Regime de amortização: <b>Bullet</b>, <b>SAC</b>, <b>Price</b> ou <b>Vinculado a Recebíveis</b>."),
    B("Retorno mínimo exigido pelo equity (hurdle rate) para cálculo de WACC."),
    Sp(4),
    H3("Indicadores gerados"),
    B("<b>CET real anual</b> — calculado via IRR do fluxo efetivo de caixa (não fórmula bullet)."),
    B("Schedule completo de amortização por regime com saldo devedor mês a mês."),
    B("<b>Receita da Maffezzolli</b> — breakdown de taxa de estruturação, originação e monitoramento."),
    B("<b>WACC</b> — custo médio ponderado com dívida CRI e equity."),
    B("<b>DSCR</b> — cobertura do serviço de dívida pelo fluxo de recebíveis."),
    B("<b>Semáforo de viabilidade</b>: verde / amarelo / vermelho com descrição da recomendação."),
    B("Comparativo visual: Banco (CCB) vs CRI — resultado, TIR, exposição."),
    B("DRE VP e VF recalculados com impacto CRI; fluxo de caixa atualizado por regime."),
    Sp(12),
]

# 3.3 ConstruRisk
story += [
    H2("3.3 ConstruRisk v2"),
    P("Due diligence automatizada de construtoras e incorporadoras, combinando consultas a bases "
      "regulatórias com análise IA dupla (crédito + PLD/compliance)."),
    B("Consultas integradas: SCR Bacen, OFAC, listas PEP e COAF."),
    B("Parecer de crédito: score, capacidade de pagamento, endividamento, histórico de inadimplência."),
    B("Parecer PLD: enquadramentos regulatórios, suspeita de lavagem, exposição política."),
    B("Exporta PDF com parecer completo e recomendação semáforo."),
    Sp(10),
]

# 3.4 Obras
story += [
    H2("3.4 Gestão de Obras"),
    P("Dashboard físico-financeiro de obras em construção com acompanhamento por fases e etapas."),
    B("Estrutura hierárquica: Obra → Fases → Etapas (concreto, aço, empreitada, INSS)."),
    B("Apontamentos mensais de realizado vs orçado (físico e financeiro)."),
    B("EVM (Earned Value Management): desvios de prazo e custo, previsão de término."),
    Sp(10),
]

# 3.5 Reuniões
story += [
    H2("3.5 Transcrição de Reuniões (Whisper)"),
    P("Transcrição automática de áudios de reuniões com resumo estruturado gerado por IA."),
    B("Upload de áudio (MP3, M4A, WAV, OGG até 500 MB)."),
    B("Transcrição assíncrona via <b>OpenAI Whisper</b> — não trava a interface."),
    B("Resumo: contexto, pontos principais, decisões, ações (quem / quando)."),
    B("Integrado ao Augur: o assistente lê as reuniões para responder perguntas."),
    Sp(12),
]

# ── 4. Catálogo de Serviços ───────────────────────────────────────────────────
story += [
    H1("4. Catálogo de Serviços (27+)"),
    Sp(6),
]

servicos = [
    ["Grupo", "Exemplos de Serviços"],
    ["Advisory",
     "Turnaround · Valuation · Estratégia Financeira · Recuperação Judicial"],
    ["Investment Banking",
     "Rodada Anjo/Seed · Roadshow PE · Debêntures · CRI/CRA · M&A Buy/Sell-side"],
    ["Special Situations",
     "M&A Distressed · DIP Financing · Precatórios · Venda de Créditos de RJ"],
    ["BaaS",
     "Capital de Giro · Desconto de Duplicatas · Home/Auto Equity · Câmbio · Trade Finance"],
    ["Análise de Crédito",
     "Relatório SCR Bacen · Score · Parecer PLD · ConstruRisk"],
]
ts = Table(servicos, colWidths=[4*cm, 12*cm])
ts.setStyle(TableStyle([
    ("FONTNAME", (0,0), (-1,0), "Helvetica-Bold"),
    ("FONTNAME", (0,1), (-1,-1), "Helvetica"),
    ("FONTSIZE", (0,0), (-1,-1), 9),
    ("BACKGROUND", (0,0), (-1,0), AZUL),
    ("TEXTCOLOR", (0,0), (-1,0), BRANCO),
    ("ROWBACKGROUNDS", (0,1), (-1,-1), [CINZACLARO, BRANCO]),
    ("GRID", (0,0), (-1,-1), 0.3, colors.HexColor("#E2E8F0")),
    ("PADDING", (0,0), (-1,-1), 7),
    ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
    ("LEFTPADDING", (0,0), (-1,-1), 10),
    ("FONTNAME", (0,1), (0,-1), "Helvetica-Bold"),
    ("TEXTCOLOR", (0,1), (0,-1), AZUL),
]))
story += [ts, Sp(12)]

# ── 5. Arquitetura ────────────────────────────────────────────────────────────
story += [
    H1("5. Arquitetura Técnica"),
    Sp(6),
    P("O <b>app.py</b> é o único ponto de entrada FastAPI, que carrega todos os módulos via "
      "<code>exec(open('ui_*.py').read())</code> em namespace compartilhado. Templates Jinja2 são "
      "registrados em um dicionário <b>TEMPLATES</b> em memória; alguns módulos (ex: CRI) injetam "
      "abas, colunas e blocos nesses templates dinamicamente em runtime, sem alterar arquivos em disco."),
    Sp(4),
    B("Multi-tenant: cada empresa tem dados, base Augur e histórico isolados."),
    B("Autenticação própria com JWT + sessão de cookie."),
    B("Sistema de créditos (CreditWallet) para monetização de features de IA."),
    B("Deploy contínuo via GitHub → branch de feature → produção."),
    Sp(20),
    HR(),
    Paragraph("Maffezzolli Capital · app.maffezzollicapital.com.br · Documento interno — Maio 2026",
              rodape_style),
]

# ── Build ─────────────────────────────────────────────────────────────────────
doc.build(story)
print(f"PDF gerado: {OUT}")

# =============================================================================
# Banco de Formulários — modelos reaproveitáveis enviados a clientes/leads
# sem precisar de login, com retorno automático das respostas dentro do CRM.
# =============================================================================

import json     as _json_fb
import secrets   as _sec_fb
import html      as _html_fb
from datetime import datetime as _dt_fb
from typing   import Optional as _Opt_fb
from sqlmodel import Field as _F_fb, SQLModel as _SM_fb, select as _sel_fb, Session as _Sess_fb


# ── Modelos ───────────────────────────────────────────────────────────────────

class FormTemplate(_SM_fb, table=True):
    __tablename__  = "formtemplate"
    __table_args__ = {"extend_existing": True}

    id:          _Opt_fb[int] = _F_fb(default=None, primary_key=True)
    company_id:  int          = _F_fb(index=True, foreign_key="company.id")
    nome:        str          = ""
    descricao:   str          = ""
    schema_json: str          = "[]"  # lista de campos: [{name,label,type,required,options,help}]
    created_by_user_id: int   = 0
    created_at:  datetime     = _F_fb(default_factory=utcnow)
    updated_at:  datetime     = _F_fb(default_factory=utcnow)


class FormSubmission(_SM_fb, table=True):
    __tablename__  = "formsubmission"
    __table_args__ = {"extend_existing": True}

    id:          _Opt_fb[int] = _F_fb(default=None, primary_key=True)
    company_id:  int          = _F_fb(index=True, foreign_key="company.id")
    template_id: int          = _F_fb(index=True, foreign_key="formtemplate.id")
    deal_id:     _Opt_fb[int] = _F_fb(default=None, index=True, foreign_key="businessdeal.id")
    client_id:   _Opt_fb[int] = _F_fb(default=None, index=True, foreign_key="client.id")

    token:       str = _F_fb(default_factory=lambda: _sec_fb.token_urlsafe(24), index=True, unique=True)
    status:      str = _F_fb(default="pendente", index=True)  # pendente | respondido
    enviado_para: str = ""  # e-mail/telefone informado no envio (apenas registro)

    answers_json: str = "{}"

    sent_by_user_id: int = 0
    sent_at:      datetime           = _F_fb(default_factory=utcnow)
    responded_at: _Opt_fb[datetime]  = None


try:
    _SM_fb.metadata.create_all(engine, tables=[FormTemplate.__table__, FormSubmission.__table__])
    print("[form_builder] ✅ Tabelas formtemplate/formsubmission OK")
except Exception as _e_fb_tbl:
    print(f"[form_builder] Tabela: {_e_fb_tbl}")


# ── Modelo padrão CRI (mesmos campos do formulário standalone enviado por e-mail) ──

_FB_MODELO_CRI = [
    {"name": "razao_social", "label": "Razão Social", "type": "text", "required": True},
    {"name": "cnpj", "label": "CNPJ", "type": "text", "required": True},
    {"name": "setor", "label": "Setor de Atividade", "type": "text", "required": False},
    {"name": "responsavel", "label": "Nome do responsável", "type": "text", "required": True},
    {"name": "email", "label": "E-mail", "type": "email", "required": True},
    {"name": "telefone", "label": "Telefone / WhatsApp", "type": "tel", "required": True},
    {"name": "nome_empreendimento", "label": "Nome / identificação do empreendimento", "type": "text", "required": False},
    {"name": "tipo_empreendimento", "label": "Tipo de empreendimento", "type": "select",
     "options": "Residencial,Comercial,Loteamento,Misto,Built to suit,Outro", "required": False},
    {"name": "fase_atual", "label": "Fase atual", "type": "select",
     "options": "Terreno / pré-lançamento,Lançamento,Em obras,Pronto / entregue", "required": False},
    {"name": "vgv_total", "label": "VGV total (Valor Geral de Vendas)", "type": "number", "required": False},
    {"name": "vso_pct", "label": "% já vendido (VSO)", "type": "number", "required": False},
    {"name": "valor_recebiveis", "label": "Valor dos recebíveis disponíveis para securitização", "type": "number", "required": False},
    {"name": "valor_pretendido", "label": "Valor pretendido da operação", "type": "number", "required": True},
    {"name": "prazo_meses", "label": "Prazo desejado (meses)", "type": "number", "required": False},
    {"name": "finalidade", "label": "Finalidade dos recursos", "type": "select",
     "options": "Capital de giro,Construção / obra,Aquisição de terreno,Refinanciamento de dívida,Outro", "required": False},
    {"name": "garantias", "label": "Garantias disponíveis", "type": "checkbox",
     "options": "Alienação fiduciária do imóvel/terreno,Cessão fiduciária de recebíveis,Aval / fiança dos sócios,Hipoteca,Outros imóveis em garantia", "required": False},
    {"name": "faturamento_mensal", "label": "Faturamento médio mensal", "type": "number", "required": False},
    {"name": "divida_total", "label": "Dívida total atual", "type": "number", "required": False},
    {"name": "observacoes", "label": "Observações", "type": "textarea", "required": False},
]


_FB_MODELO_PRE_DIAG_CONSTRUTORA = [
    # ── BLOCO 1: Identificação da empresa ──────────────────────────────────────
    {"name": "_sec1", "label": "1. IDENTIFICAÇÃO DA EMPRESA", "type": "section"},
    {"name": "razao_social",       "label": "Razão Social",                        "type": "text",   "required": True},
    {"name": "cnpj",               "label": "CNPJ",                                "type": "text",   "required": True},
    {"name": "nome_responsavel",   "label": "Nome do responsável / sócio",         "type": "text",   "required": True},
    {"name": "cargo_responsavel",  "label": "Cargo",                               "type": "text",   "required": False},
    {"name": "email",              "label": "E-mail",                              "type": "email",  "required": True},
    {"name": "whatsapp",           "label": "WhatsApp",                            "type": "tel",    "required": True},
    {"name": "cidade_uf",          "label": "Cidade / UF (sede)",                  "type": "text",   "required": True},
    {"name": "anos_mercado",       "label": "Há quantos anos a empresa atua no mercado?", "type": "select",
     "options": "Menos de 2 anos,2 a 5 anos,5 a 10 anos,10 a 20 anos,Mais de 20 anos", "required": True},
    {"name": "obras_concluidas",   "label": "Quantas obras já entregou (aproximadamente)?", "type": "select",
     "options": "Nenhuma (primeira obra),1 a 3,4 a 10,11 a 30,Mais de 30", "required": False},

    # ── BLOCO 2: Perfil do negócio ─────────────────────────────────────────────
    {"name": "_sec2", "label": "2. PERFIL DO NEGÓCIO", "type": "section"},
    {"name": "tipo_empresa",       "label": "Como você define sua empresa?", "type": "checkbox",
     "options": "Incorporadora,Construtora,Loteadora,Built to suit,Retrofit / revitalização,Outro", "required": True},
    {"name": "ticket_medio",       "label": "Ticket médio dos empreendimentos (VGV por projeto)", "type": "select",
     "options": "Até R$ 5 mi,R$ 5 mi a R$ 20 mi,R$ 20 mi a R$ 50 mi,R$ 50 mi a R$ 150 mi,Acima de R$ 150 mi", "required": False},
    {"name": "segmento_produto",   "label": "Segmento principal dos produtos", "type": "checkbox",
     "options": "Popular / MCMV,Econômico,Médio,Alto padrão,Comercial / Escritórios,Industrial / Galpão,Loteamento aberto,Loteamento fechado / Condomínio", "required": False},
    {"name": "estados_atuacao",    "label": "Estados onde opera",             "type": "text",   "required": False,
     "help": "Ex: SC, PR, SP"},
    {"name": "obras_em_andamento", "label": "Quantas obras estão em andamento hoje?", "type": "select",
     "options": "Nenhuma,1,2 a 3,4 a 6,Mais de 6", "required": False},

    # ── BLOCO 3: Situação financeira ───────────────────────────────────────────
    {"name": "_sec3", "label": "3. SITUAÇÃO FINANCEIRA", "type": "section"},
    {"name": "faturamento_anual",  "label": "Faturamento anual (último exercício, R$)", "type": "number", "required": True,
     "help": "Receita bruta reconhecida no ano. Caso não saiba o valor exato, coloque uma estimativa."},
    {"name": "margem_ebitda",      "label": "Margem EBITDA estimada (%)",      "type": "select",
     "options": "Negativa,0% a 5%,5% a 10%,10% a 15%,15% a 20%,Acima de 20%,Não sei", "required": False},
    {"name": "divida_total",       "label": "Dívida total atual (R$)",         "type": "number", "required": False,
     "help": "Soma de financiamentos bancários, CRI, debêntures, mútuo de sócios etc."},
    {"name": "principais_credores","label": "Principais credores / bancos",    "type": "text",   "required": False,
     "help": "Ex: Caixa Econômica, Bradesco, CRI via securitizadora X"},
    {"name": "custo_medio_divida", "label": "Custo médio da dívida atual (% a.a.)", "type": "select",
     "options": "Não sei,Até CDI + 2%,CDI + 2% a 4%,CDI + 4% a 6%,CDI + 6% a 8%,Acima de CDI + 8%,Prefixado - informarei nas observações", "required": False},
    {"name": "inadimplencia_divida","label": "Há parcelas em atraso ou renegociação com bancos?", "type": "radio",
     "options": "Não,Sim — em negociação,Sim — em atraso sem acordo", "required": False},
    {"name": "possui_spe",         "label": "Os empreendimentos estão em SPEs separadas?", "type": "radio",
     "options": "Sim, todas em SPE,Parcialmente,Não, tudo na holding/empresa principal", "required": False},

    # ── BLOCO 4: Empreendimento / projeto foco ─────────────────────────────────
    {"name": "_sec4", "label": "4. EMPREENDIMENTO / PROJETO EM FOCO", "type": "section",
     "help": "Preencha sobre o projeto para o qual busca capital. Se forem vários, foque no principal."},
    {"name": "nome_empreendimento","label": "Nome / identificação do empreendimento", "type": "text",   "required": False},
    {"name": "tipo_empreendimento","label": "Tipo",                             "type": "select",
     "options": "Residencial vertical,Residencial horizontal / loteamento,Comercial / Salas,Misto,Galpão / industrial,Built to suit,Retrofit,Outro", "required": False},
    {"name": "cidade_empreend",    "label": "Cidade / UF do empreendimento",   "type": "text",   "required": False},
    {"name": "vgv_total",          "label": "VGV total (R$)",                  "type": "number", "required": False},
    {"name": "vso_pct",            "label": "% do VGV já vendido (VSO)",       "type": "number", "required": False,
     "help": "Percentual de unidades vendidas sobre o total lançado. Ex: 65"},
    {"name": "fase_atual",         "label": "Fase atual do empreendimento",    "type": "select",
     "options": "Aquisição de terreno,Projeto / licenciamento,Lançamento comercial,Em obras (até 30%),Em obras (30% a 70%),Em obras (acima de 70%),Pronto / entregue,Habite-se obtido", "required": False},
    {"name": "prazo_entrega",      "label": "Previsão de entrega",             "type": "text",   "required": False,
     "help": "Mês/ano esperado para conclusão. Ex: 06/2027"},
    {"name": "valor_recebiveis",   "label": "Valor dos recebíveis disponíveis (R$)", "type": "number", "required": False,
     "help": "Contratos de compra e venda já assinados e cedíveis"},
    {"name": "custo_obra_restante","label": "Custo de obra restante (R$)",     "type": "number", "required": False,
     "help": "Quanto ainda precisa ser investido para concluir a obra"},

    # ── BLOCO 5: Necessidade de capital ────────────────────────────────────────
    {"name": "_sec5", "label": "5. NECESSIDADE DE CAPITAL", "type": "section"},
    {"name": "valor_pretendido",   "label": "Valor de captação desejado (R$)", "type": "number", "required": True},
    {"name": "prazo_meses",        "label": "Prazo desejado (meses)",          "type": "number", "required": False},
    {"name": "finalidade",         "label": "Finalidade principal dos recursos", "type": "checkbox",
     "options": "Custeio / andamento de obra,Aquisição de terreno,Capital de giro da empresa,Recomposição de caixa,Refinanciamento / troca de dívida cara,Lançamento comercial,Outro", "required": True},
    {"name": "estrutura_preferida","label": "Estrutura preferida (se já tiver ideia)", "type": "checkbox",
     "options": "CRI (Certificado de Recebíveis Imobiliários),Debêntures,CCB (Cédula de Crédito Bancário),Fundo de recebíveis (FIDC),Equity / sócio investidor,Capital de Giro bancário,Sem preferência — orientem-me", "required": False},
    {"name": "garantias",          "label": "Garantias disponíveis",           "type": "checkbox",
     "options": "Alienação fiduciária do terreno/imóvel,Cessão fiduciária de recebíveis (contratos assinados),Aval dos sócios,Outros imóveis da empresa / sócios,Penhor de cotas da SPE,Não tenho garantias formais — discutir", "required": False},
    {"name": "urgencia",           "label": "Urgência para a captação",        "type": "radio",
     "options": "Imediata (menos de 30 dias),Curto prazo (1 a 3 meses),Médio prazo (3 a 6 meses),Planejamento / sem pressa", "required": False},

    # ── BLOCO 6: Histórico e relacionamento bancário ───────────────────────────
    {"name": "_sec6", "label": "6. HISTÓRICO E RELACIONAMENTO", "type": "section"},
    {"name": "ja_fez_cri",         "label": "Já realizou operação de CRI ou securitização antes?", "type": "radio",
     "options": "Sim,Não,Está em processo", "required": False},
    {"name": "rating_empresa",     "label": "A empresa possui rating de crédito?", "type": "radio",
     "options": "Sim — informarei nas observações,Não,Não sei o que é", "required": False},
    {"name": "auditoria",          "label": "As demonstrações financeiras são auditadas?", "type": "radio",
     "options": "Sim, por firma de auditoria externa,Sim, internamente,Não,Somente ITR / ECF Receita Federal", "required": False},
    {"name": "sistema_gestao",     "label": "Utiliza algum ERP / sistema de gestão?", "type": "text", "required": False,
     "help": "Ex: Sienge, Totvs, SAP, Mega, Planilha própria"},
    {"name": "ja_tentou_captacao", "label": "Já buscou captação antes para este projeto ou empresa?", "type": "radio",
     "options": "Não,Sim — conseguiu,Sim — não conseguiu,Sim — em andamento", "required": False},
    {"name": "motivo_nao_conseguiu","label": "Se não conseguiu, qual foi o principal motivo?", "type": "textarea", "required": False},

    # ── BLOCO 7: Dor principal e expectativas ─────────────────────────────────
    {"name": "_sec7", "label": "7. DOR PRINCIPAL E EXPECTATIVAS", "type": "section"},
    {"name": "principal_desafio",  "label": "Qual é o seu maior desafio financeiro hoje?", "type": "checkbox",
     "options": "Falta de capital para iniciar / continuar a obra,Custo da dívida muito alto,Banco recusou crédito,Prazo curto demais das linhas atuais,Concentração de dívida vencendo em curto prazo,Sócio quer sair / recompra de participação,Estrutura societária precisa de reorganização,Outro", "required": True},
    {"name": "resultado_esperado", "label": "O que o sucesso desta operação representa para você?", "type": "textarea", "required": False,
     "help": "Ex: 'concluir a obra e entregar no prazo', 'liberar caixa para lançar o próximo projeto', 'refinanciar dívida cara e melhorar margem'"},
    {"name": "observacoes",        "label": "Informações adicionais / observações livres",  "type": "textarea", "required": False},
]


_FB_MODELO_PRE_DIAG_TURNAROUND = [
    # ── BLOCO 1: Identificação ────────────────────────────────────────────────
    {"name": "_sec1", "label": "1. IDENTIFICAÇÃO DA EMPRESA", "type": "section"},
    {"name": "razao_social",        "label": "Razão Social",                            "type": "text",    "required": True},
    {"name": "cnpj",                "label": "CNPJ",                                    "type": "text",    "required": True},
    {"name": "nome_responsavel",    "label": "Nome do responsável / sócio",             "type": "text",    "required": True},
    {"name": "cargo_responsavel",   "label": "Cargo",                                   "type": "text",    "required": False},
    {"name": "email",               "label": "E-mail",                                  "type": "email",   "required": True},
    {"name": "whatsapp",            "label": "WhatsApp",                                "type": "tel",     "required": True},
    {"name": "cidade_uf",           "label": "Cidade / UF (sede)",                      "type": "text",    "required": True},
    {"name": "setor",               "label": "Setor / Segmento da empresa",             "type": "text",    "required": True,
     "help": "Ex: Construção civil, Varejo, Indústria alimentícia, Serviços de saúde"},
    {"name": "anos_mercado",        "label": "Há quantos anos a empresa está no mercado?", "type": "select",
     "options": "Menos de 2 anos,2 a 5 anos,5 a 10 anos,10 a 20 anos,Mais de 20 anos", "required": True},
    {"name": "num_funcionarios",    "label": "Número de funcionários (aproximado)",     "type": "select",
     "options": "Até 10,11 a 50,51 a 200,201 a 500,Acima de 500", "required": False},

    # ── BLOCO 2: Situação atual ───────────────────────────────────────────────
    {"name": "_sec2", "label": "2. SITUAÇÃO ATUAL DA EMPRESA", "type": "section"},
    {"name": "faturamento_anual",   "label": "Faturamento anual (último exercício, R$)", "type": "number", "required": True,
     "help": "Receita bruta do último ano. Use estimativa se necessário."},
    {"name": "evolucao_faturamento","label": "Como o faturamento evoluiu nos últimos 3 anos?", "type": "radio",
     "options": "Cresceu significativamente,Cresceu levemente,Manteve estável,Caiu levemente,Caiu significativamente", "required": True},
    {"name": "resultado_operacional","label": "A empresa está gerando resultado operacional positivo?", "type": "radio",
     "options": "Sim, lucro operacional positivo,Estamos no zero a zero,Prejuízo operacional — mas controlável,Prejuízo operacional grave", "required": True},
    {"name": "margem_ebitda",       "label": "Margem EBITDA estimada (%)", "type": "select",
     "options": "Negativa,0% a 3%,3% a 8%,8% a 15%,Acima de 15%,Não sei calcular", "required": False},
    {"name": "caixa_atual",         "label": "Situação de caixa / liquidez hoje", "type": "radio",
     "options": "Caixa suficiente para 6+ meses,Caixa para 3 a 6 meses,Caixa para 1 a 3 meses,Caixa crítico (menos de 1 mês),Fluxo de caixa negativo — déficit recorrente", "required": True},
    {"name": "inadimplencia_clientes","label": "Nível de inadimplência dos clientes", "type": "radio",
     "options": "Baixo (abaixo de 3%),Moderado (3% a 8%),Alto (8% a 15%),Muito alto (acima de 15%),Não meço sistematicamente", "required": False},

    # ── BLOCO 3: Endividamento ────────────────────────────────────────────────
    {"name": "_sec3", "label": "3. ENDIVIDAMENTO E OBRIGAÇÕES FINANCEIRAS", "type": "section"},
    {"name": "divida_total",        "label": "Dívida financeira total (R$)",            "type": "number", "required": False,
     "help": "Soma de empréstimos, financiamentos, debêntures, mútuo de sócios, CRI/CRA etc."},
    {"name": "relacao_divida_fat",  "label": "Relação Dívida / Faturamento anual", "type": "radio",
     "options": "Até 0,5x (saudável),0,5x a 1x,1x a 2x,2x a 3x,Acima de 3x (muito alavancada),Não sei calcular", "required": False},
    {"name": "parcelas_atraso",     "label": "Há parcelas de dívida em atraso ou renegociação?", "type": "radio",
     "options": "Não,Sim — 1 a 2 credores em negociação,Sim — vários credores em atraso,Sim — com protestos ou ações judiciais em curso", "required": True},
    {"name": "principais_credores", "label": "Principais credores / tipos de dívida",  "type": "text",   "required": False,
     "help": "Ex: Banco do Brasil, Itaú, Caixa (BNDES), fornecedores, sócios"},
    {"name": "passivo_trabalhista", "label": "Há passivo trabalhista relevante?", "type": "radio",
     "options": "Não,Sim — valor estimado nas observações,Sim — em execução fiscal / penhora", "required": False},
    {"name": "passivo_fiscal",      "label": "Há passivo fiscal / tributário relevante?", "type": "radio",
     "options": "Não,Sim — em parcelamento (REFIS / PERT ou similar),Sim — em aberto sem acordo,Sim — com penhora ou execução", "required": False},
    {"name": "recuperacao_judicial","label": "A empresa está ou já esteve em recuperação judicial?", "type": "radio",
     "options": "Não,Estamos em RJ ativa,Já saímos da RJ,Estamos considerando pedir RJ,Não sei o que é — explicar", "required": True},

    # ── BLOCO 4: Causas da crise ──────────────────────────────────────────────
    {"name": "_sec4", "label": "4. CAUSAS E ORIGEM DA CRISE", "type": "section",
     "help": "Esta seção é fundamental para o diagnóstico. Seja o mais honesto possível — as informações são confidenciais."},
    {"name": "causas_principais",   "label": "Quais foram as principais causas da dificuldade atual?", "type": "checkbox",
     "options": "Queda de receita / perda de clientes relevantes,Custos operacionais fora de controle,Endividamento excessivo / alavancagem,Expansão mal planejada (unidades, regiões, produtos),Gestão financeira inadequada (falta de fluxo de caixa, DRE),Conflito societário,Perda de pessoal-chave,Mudança adversa de mercado / concorrência,Crise macroeconômica (juros, câmbio, inflação),Problema operacional grave (produção, logística, qualidade),Fraude ou desvio interno,Pandemia / evento externo extraordinário,Outro", "required": True},
    {"name": "tempo_crise",         "label": "Há quanto tempo a empresa está nessa situação crítica?", "type": "radio",
     "options": "Menos de 6 meses,6 meses a 1 ano,1 a 2 anos,2 a 4 anos,Mais de 4 anos", "required": True},
    {"name": "tentativas_anteriores","label": "Já tentou resolver a situação antes? Como?", "type": "textarea", "required": False,
     "help": "Ex: cortou custos, renegociou dívidas, buscou sócio, contratou consultoria"},

    # ── BLOCO 5: Estrutura de governança ─────────────────────────────────────
    {"name": "_sec5", "label": "5. GOVERNANÇA E ESTRUTURA SOCIETÁRIA", "type": "section"},
    {"name": "num_socios",          "label": "Número de sócios ativos",               "type": "select",
     "options": "1 (empresa individual),2,3 a 5,6 a 10,Mais de 10", "required": False},
    {"name": "alinhamento_socios",  "label": "Há alinhamento entre os sócios sobre o processo de reestruturação?", "type": "radio",
     "options": "Sim, todos alinhados,Parcialmente — há discordâncias,Não — conflito aberto entre sócios,Não se aplica (sócio único)", "required": True},
    {"name": "conselho",            "label": "A empresa possui conselho de administração ou consultivo?", "type": "radio",
     "options": "Sim, atuante,Sim, mas pouco ativo,Não", "required": False},
    {"name": "auditoria",           "label": "As demonstrações financeiras são auditadas?", "type": "radio",
     "options": "Sim, por firma de auditoria externa,Somente internamente,Não auditadas,Somente obrigações fiscais (ECF/SPED)", "required": False},
    {"name": "sistema_gestao",      "label": "Utiliza ERP / sistema de gestão?",      "type": "text",   "required": False,
     "help": "Ex: SAP, Totvs, Oracle, Conta Azul, Omie, Planilha própria"},
    {"name": "dfi_atualizado",      "label": "As informações financeiras (DRE, Balanço, Fluxo de Caixa) estão atualizadas?", "type": "radio",
     "options": "Sim, atualizadas mensalmente,Sim, mas com defasagem (trimestrais/anuais),Parcialmente,Não — gestão financeira precisa de estruturação", "required": True},

    # ── BLOCO 6: Ativos e potencial de recuperação ────────────────────────────
    {"name": "_sec6", "label": "6. ATIVOS E POTENCIAL DE RECUPERAÇÃO", "type": "section"},
    {"name": "ativos_relevantes",   "label": "A empresa possui ativos relevantes?", "type": "checkbox",
     "options": "Imóveis próprios,Equipamentos e maquinário,Carteira de clientes ativa,Marca reconhecida / propriedade intelectual,Contratos de longo prazo em vigor,Recebíveis a vencer (duplicatas, contratos),Participação em outras empresas / investimentos,Não possui ativos relevantes", "required": False},
    {"name": "unidades_negocio",    "label": "A empresa possui unidades ou divisões que são rentáveis?", "type": "radio",
     "options": "Sim — parte do negócio é saudável,Não — o problema é generalizado,Não sei avaliar por divisão", "required": False,
     "help": "Importante para avaliar possibilidade de desinvestimento ou foco em core business"},
    {"name": "capacidade_geração",  "label": "A operação tem capacidade de gerar caixa se a dívida for reestruturada?", "type": "radio",
     "options": "Sim, com certeza,Provavelmente sim,Incerto,Provavelmente não,Definitivamente não", "required": True},
    {"name": "clientes_concentracao","label": "Os 3 maiores clientes representam qual % da receita?", "type": "radio",
     "options": "Menos de 20%,20% a 40%,40% a 60%,60% a 80%,Mais de 80%", "required": False},

    # ── BLOCO 7: Objetivos e expectativas ─────────────────────────────────────
    {"name": "_sec7", "label": "7. OBJETIVOS E EXPECTATIVAS", "type": "section"},
    {"name": "objetivo_principal",  "label": "Qual é o principal objetivo que você busca com a consultoria de turnaround?", "type": "checkbox",
     "options": "Evitar falência ou liquidação,Reestruturar dívidas e melhorar fluxo de caixa,Reduzir custos e melhorar eficiência operacional,Reorganizar a estrutura societária,Atrair investidor ou novo sócio estratégico,Preparar empresa para venda,Obter novo crédito em melhores condições,Sair da recuperação judicial,Outro", "required": True},
    {"name": "prazo_esperado",      "label": "Em que prazo espera ver resultados concretos?", "type": "radio",
     "options": "Imediato — situação de emergência (menos de 60 dias),Curto prazo (3 a 6 meses),Médio prazo (6 a 18 meses),Longo prazo (acima de 18 meses)", "required": True},
    {"name": "disponibilidade_mudancas","label": "Há disposição para mudanças profundas na operação ou gestão, se necessário?", "type": "radio",
     "options": "Sim, estamos abertos a mudanças radicais se for preciso,Sim, com algumas restrições,Parcialmente — há resistência interna,Não — buscamos soluções conservadoras", "required": True},
    {"name": "budget_consultoria",  "label": "Há orçamento disponível para honorários de consultoria?", "type": "radio",
     "options": "Sim, orçamento definido,Sim, limitado — dependente do resultado,A definir conforme proposta,Não — necessitamos de modelo success fee", "required": False},
    {"name": "principal_desafio",   "label": "Em uma frase, qual é o maior problema da empresa hoje?", "type": "textarea", "required": True},
    {"name": "observacoes",         "label": "Informações adicionais ou contexto relevante",          "type": "textarea", "required": False},
]


def _fb_get_or_create_modelo_pre_diag_turnaround(session, company_id: int) -> "FormTemplate":
    tpl = session.exec(
        _sel_fb(FormTemplate).where(
            FormTemplate.company_id == company_id,
            FormTemplate.nome == "Pré-diagnóstico Turnaround",
        )
    ).first()
    if tpl:
        return tpl
    tpl = FormTemplate(
        company_id=company_id,
        nome="Pré-diagnóstico Turnaround",
        descricao="Levantamento completo para empresas em crise ou reestruturação: situação financeira, causas da crise, endividamento, governança, ativos e objetivos do processo de turnaround.",
        schema_json=_json_fb.dumps(_FB_MODELO_PRE_DIAG_TURNAROUND, ensure_ascii=False),
    )
    session.add(tpl)
    session.commit()
    session.refresh(tpl)
    return tpl


def _fb_get_or_create_modelo_pre_diag_construtora(session, company_id: int) -> "FormTemplate":
    tpl = session.exec(
        _sel_fb(FormTemplate).where(
            FormTemplate.company_id == company_id,
            FormTemplate.nome == "Pré-diagnóstico Construtora",
        )
    ).first()
    if tpl:
        return tpl
    tpl = FormTemplate(
        company_id=company_id,
        nome="Pré-diagnóstico Construtora",
        descricao="Levantamento completo de incorporadoras e construtoras: perfil, situação financeira, empreendimento em foco, necessidade de capital e expectativas.",
        schema_json=_json_fb.dumps(_FB_MODELO_PRE_DIAG_CONSTRUTORA, ensure_ascii=False),
    )
    session.add(tpl)
    session.commit()
    session.refresh(tpl)
    return tpl


def _fb_get_or_create_modelo_cri(session, company_id: int) -> "FormTemplate":
    tpl = session.exec(
        _sel_fb(FormTemplate).where(
            FormTemplate.company_id == company_id,
            FormTemplate.nome == "Interesse em CRI",
        )
    ).first()
    if tpl:
        return tpl
    tpl = FormTemplate(
        company_id=company_id,
        nome="Interesse em CRI",
        descricao="Levantamento inicial para avaliar viabilidade de Certificado de Recebíveis Imobiliários.",
        schema_json=_json_fb.dumps(_FB_MODELO_CRI, ensure_ascii=False),
    )
    session.add(tpl)
    session.commit()
    session.refresh(tpl)
    return tpl


# ── Helpers de schema/render ─────────────────────────────────────────────────

def _fb_parse_schema(tpl) -> list:
    try:
        return _json_fb.loads(tpl.schema_json or "[]")
    except Exception:
        return []


def _fb_field_input_html(field: dict, value) -> str:
    name  = _html_fb.escape(field.get("name", ""))
    ftype = field.get("type", "text")
    req   = "required" if field.get("required") else ""

    if ftype == "textarea":
        v = _html_fb.escape(str(value or ""))
        return f'<textarea class="fb-inp" name="{name}" {req}>{v}</textarea>'

    if ftype in ("select", "radio", "checkbox"):
        opts = [o.strip() for o in (field.get("options") or "").split(",") if o.strip()]
        if ftype == "select":
            html_opts = ['<option value="">— Selecione —</option>']
            for o in opts:
                sel = "selected" if str(value) == o else ""
                html_opts.append(f'<option value="{_html_fb.escape(o)}" {sel}>{_html_fb.escape(o)}</option>')
            return f'<select class="fb-inp" name="{name}" {req}>{"".join(html_opts)}</select>'
        else:
            vals = value if isinstance(value, list) else ([value] if value else [])
            vals = [str(v) for v in vals]
            itype = "radio" if ftype == "radio" else "checkbox"
            iname = name if ftype == "radio" else f"{name}[]"
            rows = []
            for o in opts:
                checked = "checked" if o in vals else ""
                rows.append(
                    f'<label class="fb-check"><input type="{itype}" name="{iname}" value="{_html_fb.escape(o)}" {checked}> {_html_fb.escape(o)}</label>'
                )
            return f'<div class="fb-group">{"".join(rows)}</div>'

    itype_map = {"email": "email", "tel": "tel", "number": "number", "text": "text", "date": "date"}
    itype = itype_map.get(ftype, "text")
    v = _html_fb.escape(str(value)) if value not in (None, "") else ""
    return f'<input class="fb-inp" type="{itype}" name="{name}" value="{v}" {req}>'


def _fb_render_public_form(tpl, submission, erro: str = "") -> str:
    campos_html = []
    answers = {}
    try:
        answers = _json_fb.loads(submission.answers_json or "{}")
    except Exception:
        pass

    for f in _fb_parse_schema(tpl):
        ftype = f.get("type", "text")
        label = _html_fb.escape(f.get("label", f.get("name", "")))
        help_txt = f.get("help") or ""
        help_html = f'<div class="fb-help">{_html_fb.escape(help_txt)}</div>' if help_txt else ""

        if ftype == "section":
            campos_html.append(
                f'<div class="fb-section"><span>{label}</span></div>{help_html}'
            )
            continue

        req_mark = ' <span style="color:#dc2626;">*</span>' if f.get("required") else ""
        input_html = _fb_field_input_html(f, answers.get(f.get("name", "")))
        campos_html.append(
            f'<div class="fb-campo"><label>{label}{req_mark}</label>{input_html}{help_html}</div>'
        )

    erro_html = f'<div class="fb-erro">{_html_fb.escape(erro)}</div>' if erro else ""

    return f"""<!DOCTYPE html>
<html lang="pt-BR"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{_html_fb.escape(tpl.nome)}</title>
<style>
  *{{box-sizing:border-box;}}
  body{{font-family:'Segoe UI',Arial,sans-serif;background:#f4f6f9;margin:0;color:#1f2937;}}
  .wrap{{max-width:680px;margin:0 auto;padding:32px 18px 80px;}}
  .header{{background:#0d3b66;color:#fff;padding:26px 26px;border-radius:14px 14px 0 0;}}
  .header h1{{margin:0 0 6px;font-size:1.3rem;}}
  .header p{{margin:0;opacity:.9;font-size:.88rem;}}
  .card{{background:#fff;border:1px solid #dbe3ec;border-top:none;border-radius:0 0 14px 14px;padding:26px;}}
  .fb-campo{{margin-bottom:18px;}}
  .fb-campo label{{display:block;font-size:.85rem;font-weight:600;margin-bottom:5px;color:#374151;}}
  .fb-inp{{width:100%;padding:9px 11px;border:1px solid #dbe3ec;border-radius:8px;font-size:.9rem;font-family:inherit;background:#fbfcfe;}}
  textarea.fb-inp{{min-height:80px;}}
  .fb-help{{font-size:.74rem;color:#64748b;margin-top:3px;}}
  .fb-group{{display:flex;flex-direction:column;gap:6px;margin-top:4px;}}
  .fb-check{{font-size:.86rem;font-weight:400;display:flex;align-items:center;gap:6px;}}
  .fb-section{{margin:28px 0 10px;padding-bottom:6px;border-bottom:2px solid #0d3b66;color:#0d3b66;font-size:.78rem;font-weight:700;letter-spacing:.08em;}}
  .fb-section span{{background:#fff;padding-right:10px;}}
  .fb-erro{{background:#fef2f2;color:#b91c1c;padding:10px 14px;border-radius:8px;font-size:.85rem;margin-bottom:16px;}}
  button{{background:#0d3b66;color:#fff;border:none;border-radius:8px;padding:12px 22px;font-size:.95rem;font-weight:600;cursor:pointer;}}
  button:hover{{background:#0a2c4e;}}
</style></head>
<body><div class="wrap">
  <div class="header"><h1>📋 {_html_fb.escape(tpl.nome)}</h1>
  <p>{_html_fb.escape(tpl.descricao or "Preencha as informações abaixo.")}</p></div>
  <form class="card" method="post">
    {erro_html}
    {''.join(campos_html)}
    <button type="submit">Enviar respostas</button>
  </form>
</div></body></html>"""


def _fb_render_obrigado() -> str:
    return """<!DOCTYPE html>
<html lang="pt-BR"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Obrigado</title>
<style>
  body{font-family:'Segoe UI',Arial,sans-serif;background:#f4f6f9;margin:0;display:flex;align-items:center;justify-content:center;height:100vh;color:#1f2937;}
  .box{background:#fff;border-radius:14px;padding:40px 36px;text-align:center;max-width:420px;box-shadow:0 4px 18px rgba(0,0,0,.06);}
  .box h1{font-size:1.3rem;margin:0 0 10px;}
  .box p{color:#64748b;font-size:.9rem;}
</style></head>
<body><div class="box"><h1>✅ Respostas recebidas</h1>
<p>Obrigado por preencher o formulário. Nossa equipe vai analisar as informações e retornar em breve.</p></div></body></html>"""


# ── Admin: banco de formulários ──────────────────────────────────────────────

@app.get("/admin/formularios", response_class=HTMLResponse)
@require_login
async def fb_admin_lista(request: Request, session: Session = Depends(get_session)):
    ctx = get_tenant_context(request, session)
    if not ctx or ctx.membership.role not in ("admin", "owner", "equipe"):
        return RedirectResponse("/", status_code=303)

    templates_list = session.exec(
        _sel_fb(FormTemplate).where(FormTemplate.company_id == ctx.company.id).order_by(FormTemplate.created_at.desc())
    ).all()

    linhas = []
    for t in templates_list:
        n_campos = len(_fb_parse_schema(t))
        n_envios = len(session.exec(
            _sel_fb(FormSubmission).where(FormSubmission.template_id == t.id)
        ).all())
        linhas.append(
            f'<tr><td>{_html_fb.escape(t.nome)}</td><td class="muted">{_html_fb.escape(t.descricao or "—")}</td>'
            f'<td>{n_campos}</td><td>{n_envios}</td>'
            f'<td class="text-end">'
            f'<a class="btn btn-outline-secondary btn-sm" href="/admin/formularios/{t.id}/editar">Editar</a> '
            f'<form method="post" action="/admin/formularios/{t.id}/excluir" style="display:inline" '
            f'onsubmit="return confirm(\'Excluir este formulário?\');">'
            f'<button class="btn btn-outline-danger btn-sm">Excluir</button></form>'
            f'</td></tr>'
        )

    corpo = f"""
{{% extends "base.html" %}}
{{% block content %}}
<div class="card p-4">
  <div class="d-flex justify-content-between align-items-start mb-3">
    <div>
      <h4 class="mb-1">Banco de Formulários</h4>
      <div class="muted small">Modelos reaproveitáveis para enviar a clientes/leads e receber as respostas direto no CRM.</div>
    </div>
    <div class="d-flex gap-2">
      <form method="post" action="/admin/formularios/seed-pre-diag-turnaround">
        <button class="btn btn-outline-warning">🔄 Pré-diagnóstico Turnaround</button>
      </form>
      <form method="post" action="/admin/formularios/seed-pre-diag-construtora">
        <button class="btn btn-outline-secondary">🏗 Pré-diagnóstico Construtora</button>
      </form>
      <form method="post" action="/admin/formularios/seed-cri">
        <button class="btn btn-outline-primary">+ Modelo CRI</button>
      </form>
      <a class="btn btn-primary" href="/admin/formularios/novo">+ Novo formulário</a>
    </div>
  </div>
  <table class="table">
    <thead><tr><th>Nome</th><th>Descrição</th><th>Campos</th><th>Envios</th><th></th></tr></thead>
    <tbody>
      {''.join(linhas) if linhas else '<tr><td colspan="5" class="muted">Nenhum formulário criado ainda.</td></tr>'}
    </tbody>
  </table>
</div>
{{% endblock %}}
"""
    TEMPLATES["fb_admin_lista.html"] = corpo
    return render("fb_admin_lista.html", request=request, context={
        "current_user": ctx.user, "current_company": ctx.company, "role": ctx.membership.role,
    })


@app.post("/admin/formularios/seed-pre-diag-turnaround")
@require_login
async def fb_admin_seed_pre_diag_turnaround(request: Request, session: Session = Depends(get_session)):
    ctx = get_tenant_context(request, session)
    if not ctx or ctx.membership.role not in ("admin", "owner", "equipe"):
        return RedirectResponse("/", status_code=303)
    _fb_get_or_create_modelo_pre_diag_turnaround(session, ctx.company.id)
    return RedirectResponse("/admin/formularios", status_code=303)


@app.post("/admin/formularios/seed-pre-diag-construtora")
@require_login
async def fb_admin_seed_pre_diag_construtora(request: Request, session: Session = Depends(get_session)):
    ctx = get_tenant_context(request, session)
    if not ctx or ctx.membership.role not in ("admin", "owner", "equipe"):
        return RedirectResponse("/", status_code=303)
    _fb_get_or_create_modelo_pre_diag_construtora(session, ctx.company.id)
    return RedirectResponse("/admin/formularios", status_code=303)


@app.post("/admin/formularios/seed-cri")
@require_login
async def fb_admin_seed_cri(request: Request, session: Session = Depends(get_session)):
    ctx = get_tenant_context(request, session)
    if not ctx or ctx.membership.role not in ("admin", "owner", "equipe"):
        return RedirectResponse("/", status_code=303)
    _fb_get_or_create_modelo_cri(session, ctx.company.id)
    return RedirectResponse("/admin/formularios", status_code=303)


_FB_TIPOS = [
    ("text", "Texto curto"), ("textarea", "Texto longo"), ("number", "Número"),
    ("email", "E-mail"), ("tel", "Telefone"), ("date", "Data"),
    ("select", "Lista (escolha única)"), ("radio", "Opções (escolha única)"), ("checkbox", "Opções (múltipla escolha)"),
]


def _fb_builder_page_html(tpl: "_Opt_fb[FormTemplate]" = None) -> str:
    nome = _html_fb.escape(tpl.nome) if tpl else ""
    descricao = _html_fb.escape(tpl.descricao) if tpl else ""
    schema = _fb_parse_schema(tpl) if tpl else []
    schema_json_escaped = _html_fb.escape(_json_fb.dumps(schema, ensure_ascii=False))
    action = f"/admin/formularios/{tpl.id}/editar" if tpl else "/admin/formularios/novo"
    titulo = "Editar formulário" if tpl else "Novo formulário"
    tipos_opts = "".join(f'<option value="{k}">{v}</option>' for k, v in _FB_TIPOS)

    return f"""
{{% extends "base.html" %}}
{{% block content %}}
<div class="card p-4">
  <h4 class="mb-3">{titulo}</h4>
  <form method="post" action="{action}" id="fbForm">
    <div class="mb-3">
      <label class="form-label">Nome do formulário</label>
      <input class="form-control" name="nome" value="{nome}" required>
    </div>
    <div class="mb-3">
      <label class="form-label">Descrição (aparece para o cliente)</label>
      <input class="form-control" name="descricao" value="{descricao}">
    </div>

    <hr>
    <h6 class="mb-2">Campos</h6>
    <div id="fbCampos"></div>
    <button type="button" class="btn btn-outline-secondary btn-sm mt-2" onclick="fbAddCampo()">+ Adicionar campo</button>

    <input type="hidden" name="schema_json" id="fbSchemaJson">
    <div class="mt-4">
      <button type="submit" class="btn btn-primary">Salvar formulário</button>
      <a class="btn btn-outline-secondary" href="/admin/formularios">Cancelar</a>
    </div>
  </form>
</div>

<template id="fbCampoTpl">
  <div class="card p-3 mb-2 fb-campo-row">
    <div class="row g-2 align-items-end">
      <div class="col-md-4">
        <label class="form-label small">Rótulo (label)</label>
        <input class="form-control form-control-sm fb-c-label" oninput="fbSyncName(this)">
      </div>
      <div class="col-md-3">
        <label class="form-label small">Tipo</label>
        <select class="form-select form-select-sm fb-c-type" onchange="fbToggleOpts(this)">{tipos_opts}</select>
      </div>
      <div class="col-md-3 fb-c-opts-wrap" style="display:none;">
        <label class="form-label small">Opções (separadas por vírgula)</label>
        <input class="form-control form-control-sm fb-c-opts">
      </div>
      <div class="col-md-1">
        <label class="form-label small d-block">Obrig.</label>
        <input type="checkbox" class="form-check-input fb-c-req">
      </div>
      <div class="col-md-1 text-end">
        <button type="button" class="btn btn-outline-danger btn-sm" onclick="this.closest('.fb-campo-row').remove()">✕</button>
      </div>
    </div>
  </div>
</template>

<script>
function fbSyncName(el) {{
  // nome interno é gerado a partir do rótulo (sem precisar o usuário digitar)
}}
function fbSlug(s) {{
  return (s || '').toLowerCase()
    .normalize('NFD').replace(/[\\u0300-\\u036f]/g, '')
    .replace(/[^a-z0-9]+/g, '_').replace(/^_+|_+$/g, '') || 'campo';
}}
function fbToggleOpts(sel) {{
  const row = sel.closest('.fb-campo-row');
  const wrap = row.querySelector('.fb-c-opts-wrap');
  wrap.style.display = ['select','radio','checkbox'].includes(sel.value) ? 'block' : 'none';
}}
function fbAddCampo(data) {{
  const tplNode = document.getElementById('fbCampoTpl').content.cloneNode(true);
  const row = tplNode.querySelector('.fb-campo-row');
  document.getElementById('fbCampos').appendChild(row);
  if (data) {{
    row.querySelector('.fb-c-label').value = data.label || '';
    row.querySelector('.fb-c-type').value  = data.type  || 'text';
    row.querySelector('.fb-c-opts').value  = data.options || '';
    row.querySelector('.fb-c-req').checked = !!data.required;
    fbToggleOpts(row.querySelector('.fb-c-type'));
  }}
}}
function fbColetar() {{
  const linhas = [...document.querySelectorAll('.fb-campo-row')];
  const usados = {{}};
  return linhas.map(row => {{
    const label = row.querySelector('.fb-c-label').value.trim();
    let base = fbSlug(label), name = base, i = 2;
    while (usados[name]) {{ name = base + '_' + i; i++; }}
    usados[name] = true;
    return {{
      name: name, label: label,
      type: row.querySelector('.fb-c-type').value,
      options: row.querySelector('.fb-c-opts').value.trim(),
      required: row.querySelector('.fb-c-req').checked,
    }};
  }}).filter(c => c.label);
}}
document.getElementById('fbForm').addEventListener('submit', function(e) {{
  document.getElementById('fbSchemaJson').value = JSON.stringify(fbColetar());
}});

const fbExistente = {schema_json_escaped};
if (fbExistente && fbExistente.length) {{
  fbExistente.forEach(c => fbAddCampo(c));
}} else {{
  fbAddCampo();
}}
</script>
{{% endblock %}}
"""


@app.get("/admin/formularios/novo", response_class=HTMLResponse)
@require_role({"admin", "equipe"})
async def fb_admin_novo_page(request: Request, session: Session = Depends(get_session)):
    ctx = get_tenant_context(request, session)
    TEMPLATES["fb_builder.html"] = _fb_builder_page_html(None)
    return render("fb_builder.html", request=request, context={
        "current_user": ctx.user, "current_company": ctx.company, "role": ctx.membership.role,
    })


@app.post("/admin/formularios/novo")
@require_role({"admin", "equipe"})
async def fb_admin_novo_action(request: Request, session: Session = Depends(get_session)):
    ctx = get_tenant_context(request, session)
    form = await request.form()
    nome = (form.get("nome") or "").strip()
    if not nome:
        return RedirectResponse("/admin/formularios/novo", status_code=303)
    tpl = FormTemplate(
        company_id=ctx.company.id,
        nome=nome,
        descricao=(form.get("descricao") or "").strip(),
        schema_json=(form.get("schema_json") or "[]"),
        created_by_user_id=ctx.user.id,
    )
    session.add(tpl)
    session.commit()
    return RedirectResponse("/admin/formularios", status_code=303)


@app.get("/admin/formularios/{template_id}/editar", response_class=HTMLResponse)
@require_role({"admin", "equipe"})
async def fb_admin_editar_page(request: Request, session: Session = Depends(get_session), template_id: int = 0):
    ctx = get_tenant_context(request, session)
    tpl = session.get(FormTemplate, int(template_id))
    if not tpl or tpl.company_id != ctx.company.id:
        return render("error.html", request=request, context={"message": "Formulário não encontrado."}, status_code=404)
    TEMPLATES["fb_builder.html"] = _fb_builder_page_html(tpl)
    return render("fb_builder.html", request=request, context={
        "current_user": ctx.user, "current_company": ctx.company, "role": ctx.membership.role,
    })


@app.post("/admin/formularios/{template_id}/editar")
@require_role({"admin", "equipe"})
async def fb_admin_editar_action(request: Request, session: Session = Depends(get_session), template_id: int = 0):
    ctx = get_tenant_context(request, session)
    tpl = session.get(FormTemplate, int(template_id))
    if not tpl or tpl.company_id != ctx.company.id:
        return render("error.html", request=request, context={"message": "Formulário não encontrado."}, status_code=404)
    form = await request.form()
    tpl.nome = (form.get("nome") or tpl.nome).strip()
    tpl.descricao = (form.get("descricao") or "").strip()
    tpl.schema_json = form.get("schema_json") or tpl.schema_json
    tpl.updated_at = utcnow()
    session.add(tpl)
    session.commit()
    return RedirectResponse("/admin/formularios", status_code=303)


@app.post("/admin/formularios/{template_id}/excluir")
@require_role({"admin", "equipe"})
async def fb_admin_excluir(request: Request, session: Session = Depends(get_session), template_id: int = 0):
    ctx = get_tenant_context(request, session)
    tpl = session.get(FormTemplate, int(template_id))
    if tpl and tpl.company_id == ctx.company.id:
        session.delete(tpl)
        session.commit()
    return RedirectResponse("/admin/formularios", status_code=303)


# ── Envio do formulário a partir do negócio (CRM) ────────────────────────────

@app.post("/negocios/{deal_id}/formularios/enviar")
@require_role({"admin", "equipe"})
async def fb_enviar_para_negocio(request: Request, session: Session = Depends(get_session), deal_id: int = 0):
    ctx = get_tenant_context(request, session)
    deal = session.get(BusinessDeal, int(deal_id))
    if not deal or deal.company_id != ctx.company.id:
        return render("error.html", request=request, context={"message": "Negócio não encontrado."}, status_code=404)

    form = await request.form()
    template_id = form.get("template_id")
    destino_email = (form.get("destino_email") or "").strip()

    tpl = session.get(FormTemplate, int(template_id)) if template_id else None
    if not tpl or tpl.company_id != ctx.company.id:
        set_flash(request, "Selecione um formulário válido.")
        return RedirectResponse(f"/negocios/{deal.id}", status_code=303)

    submissao = FormSubmission(
        company_id=ctx.company.id,
        template_id=tpl.id,
        deal_id=deal.id,
        client_id=deal.client_id,
        enviado_para=destino_email,
        sent_by_user_id=ctx.user.id,
    )
    session.add(submissao)
    session.commit()
    session.refresh(submissao)

    link = f"{_public_base_url(request)}/f/{submissao.token}"

    if destino_email:
        try:
            _smtp_send_email(
                to_email=destino_email,
                subject=f"{tpl.nome} — preencha por aqui",
                html_body=(
                    f"<p>Olá,</p><p>Por favor preencha o formulário <b>{_html_fb.escape(tpl.nome)}</b> "
                    f"através do link abaixo:</p><p><a href='{link}'>{link}</a></p>"
                ),
                text_body=f"Preencha o formulário {tpl.nome}: {link}",
            )
            set_flash(request, f"Formulário enviado por e-mail para {destino_email}. Link: {link}")
        except Exception as _e_send:
            set_flash(request, f"Não foi possível enviar por e-mail ({_e_send}). Link gerado: {link}")
    else:
        set_flash(request, f"Link do formulário gerado: {link}")

    return RedirectResponse(f"/negocios/{deal.id}", status_code=303)


# ── Página pública (sem login) ───────────────────────────────────────────────

@app.get("/f/{token}", response_class=HTMLResponse)
async def fb_public_get(token: str, session: Session = Depends(get_session)):
    sub = session.exec(_sel_fb(FormSubmission).where(FormSubmission.token == token)).first()
    if not sub:
        return HTMLResponse("<h3>Formulário não encontrado ou link inválido.</h3>", status_code=404)
    tpl = session.get(FormTemplate, sub.template_id)
    if not tpl:
        return HTMLResponse("<h3>Formulário não encontrado.</h3>", status_code=404)
    if sub.status == "respondido":
        return HTMLResponse(_fb_render_obrigado())
    return HTMLResponse(_fb_render_public_form(tpl, sub))


@app.post("/f/{token}", response_class=HTMLResponse)
async def fb_public_post(token: str, request: Request, session: Session = Depends(get_session)):
    sub = session.exec(_sel_fb(FormSubmission).where(FormSubmission.token == token)).first()
    if not sub:
        return HTMLResponse("<h3>Formulário não encontrado ou link inválido.</h3>", status_code=404)
    tpl = session.get(FormTemplate, sub.template_id)
    if not tpl:
        return HTMLResponse("<h3>Formulário não encontrado.</h3>", status_code=404)
    if sub.status == "respondido":
        return HTMLResponse(_fb_render_obrigado())

    form = await request.form()
    schema = _fb_parse_schema(tpl)
    answers = {}
    faltando = []
    for f in schema:
        if f.get("type") == "section":
            continue
        name = f.get("name", "")
        if f.get("type") == "checkbox":
            vals = form.getlist(f"{name}[]")
            answers[name] = vals
            if f.get("required") and not vals:
                faltando.append(f.get("label", name))
        else:
            val = (form.get(name) or "").strip()
            answers[name] = val
            if f.get("required") and not val:
                faltando.append(f.get("label", name))

    if faltando:
        sub.answers_json = _json_fb.dumps(answers, ensure_ascii=False)
        erro = "Preencha os campos obrigatórios: " + ", ".join(faltando)
        return HTMLResponse(_fb_render_public_form(tpl, sub, erro=erro))

    sub.answers_json = _json_fb.dumps(answers, ensure_ascii=False)
    sub.status = "respondido"
    sub.responded_at = utcnow()
    session.add(sub)
    session.commit()
    return HTMLResponse(_fb_render_obrigado())


# ── Patch da tela de negócio (CRM) — card de Formulários ─────────────────────

app.router.routes[:] = [
    r for r in app.router.routes
    if not (
        hasattr(r, "path") and r.path == "/negocios/{deal_id}"
        and hasattr(r, "methods") and r.methods and "GET" in r.methods
    )
]


@app.get("/negocios/{deal_id}", response_class=HTMLResponse)
@require_role({"admin", "equipe"})
async def crm_detail_com_formularios(request: Request, session: Session = Depends(get_session), deal_id: int = 0) -> HTMLResponse:
    ctx = get_tenant_context(request, session)
    assert ctx is not None

    if not ensure_credit_consent_table():
        set_flash(request, "Sistema de aceite não está configurado (migração pendente no banco).")
        return RedirectResponse("/credito", status_code=303)

    deal = session.get(BusinessDeal, int(deal_id))
    if not deal or deal.company_id != ctx.company.id:
        return render("error.html", request=request, context={"message": "Negócio não encontrado."}, status_code=404)

    client = session.get(Client, deal.client_id)
    owner = session.get(User, deal.owner_user_id) if deal.owner_user_id else None

    notes = session.exec(
        select(BusinessDealNote).where(BusinessDealNote.deal_id == deal.id).order_by(BusinessDealNote.created_at.desc())
    ).all()
    note_view = []
    for n in notes:
        au = session.get(User, n.author_user_id)
        note_view.append({"id": n.id, "message": n.message, "created_at": n.created_at, "author_name": au.name if au else "—"})

    active_client_id = get_active_client_id(request, session, ctx)
    current_client = get_client_or_none(session, ctx.company.id, active_client_id)

    form_templates = session.exec(
        _sel_fb(FormTemplate).where(FormTemplate.company_id == ctx.company.id).order_by(FormTemplate.nome)
    ).all()
    submissions = session.exec(
        _sel_fb(FormSubmission).where(FormSubmission.deal_id == deal.id).order_by(FormSubmission.sent_at.desc())
    ).all()
    sub_view = []
    for s in submissions:
        s_tpl = session.get(FormTemplate, s.template_id)
        respostas = []
        if s.status == "respondido":
            try:
                answers = _json_fb.loads(s.answers_json or "{}")
                schema_map = {f.get("name"): f.get("label", f.get("name")) for f in (_fb_parse_schema(s_tpl) if s_tpl else [])}
                for k, v in answers.items():
                    vv = ", ".join(v) if isinstance(v, list) else v
                    if vv:
                        respostas.append({"label": schema_map.get(k, k), "valor": vv})
            except Exception:
                pass
        sub_view.append({
            "id": s.id, "template_nome": s_tpl.nome if s_tpl else "—",
            "status": s.status, "sent_at": s.sent_at, "responded_at": s.responded_at,
            "link": f"{_public_base_url(request)}/f/{s.token}",
            "respostas": respostas,
        })

    return render(
        "crm_detail.html",
        request=request,
        context={
            "current_user": ctx.user,
            "current_company": ctx.company,
            "role": ctx.membership.role,
            "current_client": current_client,
            "deal": deal,
            "client": client,
            "owner_name": owner.name if owner else "",
            "stage_label": _crm_stage_label(deal.stage),
            "stages": CRM_STAGES,
            "notes": note_view,
            "form_templates": form_templates,
            "form_submissions": sub_view,
        },
    )


_FB_CARD_HTML = """
  <hr class="my-3"/>
  <div class="d-flex justify-content-between align-items-center mb-2">
    <h6 class="mb-0">Formulários</h6>
  </div>
  {% if role in ["admin","equipe"] %}
  <form method="post" action="/negocios/{{ deal.id }}/formularios/enviar" class="row g-2 mb-3">
    <div class="col-md-5">
      <select class="form-select" name="template_id" required>
        <option value="">Selecione um formulário…</option>
        {% for t in form_templates %}
          <option value="{{ t.id }}">{{ t.nome }}</option>
        {% endfor %}
      </select>
    </div>
    <div class="col-md-4">
      <input class="form-control" type="email" name="destino_email" placeholder="E-mail do cliente (opcional)">
    </div>
    <div class="col-md-3">
      <button class="btn btn-primary w-100">Enviar formulário</button>
    </div>
  </form>
  {% endif %}
  {% if form_submissions %}
    <div class="list-group">
      {% for s in form_submissions %}
        <div class="list-group-item">
          <div class="d-flex justify-content-between align-items-start">
            <div>
              <b>{{ s.template_nome }}</b>
              {% if s.status == "respondido" %}
                <span class="badge bg-success ms-1">Respondido</span>
              {% else %}
                <span class="badge bg-warning text-dark ms-1">Pendente</span>
              {% endif %}
              <div class="small muted">Enviado {{ s.sent_at|brdatetime }}{% if s.responded_at %} • Respondido {{ s.responded_at|brdatetime }}{% endif %}</div>
            </div>
            <a class="small" href="{{ s.link }}" target="_blank">Abrir link ↗</a>
          </div>
          {% if s.respostas %}
            <div class="mt-2 small">
              {% for r in s.respostas %}
                <div><b>{{ r.label }}:</b> {{ r.valor }}</div>
              {% endfor %}
            </div>
          {% endif %}
        </div>
      {% endfor %}
    </div>
  {% else %}
    <div class="muted">Nenhum formulário enviado para este negócio ainda.</div>
  {% endif %}

  <h6 class="mb-0">Histórico</h6>
  </div>
"""

try:
    _anchor_fb = '<h6 class="mb-0">Histórico</h6>\n  </div>'
    if _anchor_fb in TEMPLATES["crm_detail.html"]:
        TEMPLATES["crm_detail.html"] = TEMPLATES["crm_detail.html"].replace(_anchor_fb, _FB_CARD_HTML, 1)
        print("[form_builder] ✅ Card de Formulários injetado em crm_detail.html")
    else:
        print("[form_builder] ⚠️ Âncora não encontrada em crm_detail.html — card de Formulários não injetado")
except Exception as _e_fb_patch:
    print(f"[form_builder] ⚠️ Erro ao patchear crm_detail.html: {_e_fb_patch}")

# ── Override: exclusão de negócio precisa apagar FormSubmission primeiro ────
# (senão quebra por FK violation quando o negócio tem formulário enviado)

app.router.routes[:] = [
    r for r in app.router.routes
    if not (
        hasattr(r, "path") and r.path == "/negocios/{deal_id}/excluir"
        and hasattr(r, "methods") and r.methods and "POST" in r.methods
    )
]


@app.post("/negocios/{deal_id}/excluir")
@require_role({"admin", "equipe"})
async def crm_delete_com_formularios(request: Request, session: Session = Depends(get_session), deal_id: int = 0,
                                      confirm: str = Form("")) -> Response:
    ctx = get_tenant_context(request, session)
    assert ctx is not None

    if not ensure_credit_consent_table():
        set_flash(request, "Sistema de aceite não está configurado (migração pendente no banco).")
        return RedirectResponse("/credito", status_code=303)

    deal = session.get(BusinessDeal, int(deal_id))
    if not deal or deal.company_id != ctx.company.id:
        set_flash(request, "Negócio não encontrado.")
        return RedirectResponse("/negocios", status_code=303)

    if (confirm or "").strip().upper() != "EXCLUIR":
        set_flash(request, "Confirmação inválida. Digite EXCLUIR.")
        return RedirectResponse(f"/negocios/{deal.id}", status_code=303)

    session.exec(delete(BusinessDealNote).where(BusinessDealNote.deal_id == deal.id))
    session.exec(delete(FormSubmission).where(FormSubmission.deal_id == deal.id))
    session.exec(delete(BusinessDeal).where(BusinessDeal.id == deal.id))
    session.commit()

    set_flash(request, "Negócio excluído.")
    return RedirectResponse("/negocios", status_code=303)


# ── Card de acesso em Gestão Interna ────────────────────────────────────────
try:
    FEATURE_KEYS["formularios"] = {
        "title": "Banco de Formulários",
        "desc": "Modelos de formulário e respostas recebidas de clientes.",
        "href": "/admin/formularios",
    }
    for _grp_fb in FEATURE_GROUPS:
        if _grp_fb.get("key") == "gestao_interna" and "formularios" not in _grp_fb["features"]:
            _grp_fb["features"].append("formularios")
    ROLE_DEFAULT_FEATURES["admin"].add("formularios")
    ROLE_DEFAULT_FEATURES["equipe"].add("formularios")
    print("[form_builder] ✅ Card 'Banco de Formulários' registrado em Gestão Interna")
except Exception as _e_fb_card:
    print(f"[form_builder] ⚠️ Falha ao registrar card em Gestão Interna: {_e_fb_card}")

if hasattr(templates_env.loader, "mapping"):
    templates_env.loader.mapping = TEMPLATES

print("[form_builder] ✅ Módulo de Banco de Formulários carregado.")

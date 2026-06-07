# ui_orcamento.py — Ferramenta de Planejamento Orçamentário (cliente)
# Exec'd no namespace do app.py

import json as _json_orc

# ── Modelos ───────────────────────────────────────────────────────────────────

class BudgetPlan(SQLModel, table=True):
    __tablename__ = "budgetplan"
    __table_args__ = {"extend_existing": True}
    id:          Optional[int] = Field(default=None, primary_key=True)
    company_id:  int  = Field(index=True)
    client_id:   Optional[int] = Field(default=None, index=True)  # cliente ativo
    name:        str  = Field(default="")
    year:        int  = Field(default=2026)
    description: str  = Field(default="")
    is_active:   bool = Field(default=True)
    created_at:  datetime = Field(default_factory=utcnow)
    updated_at:  datetime = Field(default_factory=utcnow)


class BudgetAccount(SQLModel, table=True):
    __tablename__ = "budgetaccount"
    __table_args__ = {"extend_existing": True}
    id:           Optional[int] = Field(default=None, primary_key=True)
    company_id:   int  = Field(index=True)
    code:         str  = Field(default="")
    name:         str  = Field(default="")
    account_type: str  = Field(default="despesa")  # receita|despesa|resultado|ativo|passivo
    parent_id:    Optional[int] = Field(default=None, index=True)
    is_totalizer: bool = Field(default=False)
    sign:         int  = Field(default=1)      # +1 soma, -1 subtrai do pai
    sort_order:   int  = Field(default=0)
    is_active:    bool = Field(default=True)
    created_at:   datetime = Field(default_factory=utcnow)
    updated_at:   datetime = Field(default_factory=utcnow)


class BudgetEntry(SQLModel, table=True):
    __tablename__  = "budgetentry"
    __table_args__ = (
        UniqueConstraint("plan_id", "account_id", "month", name="uq_budget_entry"),
        {"extend_existing": True},
    )
    id:              Optional[int] = Field(default=None, primary_key=True)
    company_id:      int  = Field(index=True)
    plan_id:         int  = Field(index=True)
    account_id:      int  = Field(index=True)
    month:           int  = Field(default=1)
    value_budgeted:  float = Field(default=0.0)
    value_realized:  float = Field(default=0.0)
    notes:           str  = Field(default="")
    updated_at:      datetime = Field(default_factory=utcnow)


def _ensure_orcamento_tables():
    for tbl in (BudgetPlan.__table__, BudgetAccount.__table__, BudgetEntry.__table__):
        try:
            tbl.create(engine, checkfirst=True)
        except Exception:
            pass
    # migração: adiciona client_id se tabela já existia sem essa coluna
    try:
        from sqlalchemy import text as _t
        with engine.begin() as _c:
            _c.execute(_t("ALTER TABLE budgetplan ADD COLUMN IF NOT EXISTS client_id INTEGER"))
    except Exception:
        pass

try:
    _ensure_orcamento_tables()
except Exception:
    pass


# ── Modelo padrão de plano de contas ─────────────────────────────────────────
# Derivado do Excel Modelo_Plano_de_Contas.xlsx — estrutura DRE completa.
# parent_code=None → conta raiz; parent_code="XX" → filha daquela conta.

_ORC_MODELO_PADRAO = [
    {"code":"01",      "name":"Receitas Operacionais",                    "account_type":"receita",  "is_totalizer":False,"sign":1,  "parent_code":None},
    {"code":"01.1",    "name":"Geral/Varejo",                             "account_type":"receita",  "is_totalizer":False,"sign":1,  "parent_code":"01"},
    {"code":"01.2",    "name":"Saldo/Resíduo",                            "account_type":"receita",  "is_totalizer":False,"sign":1,  "parent_code":"01"},
    {"code":"01.3",    "name":"Magazine",                                 "account_type":"receita",  "is_totalizer":False,"sign":1,  "parent_code":"01"},
    {"code":"01.4",    "name":"Export",                                   "account_type":"receita",  "is_totalizer":False,"sign":1,  "parent_code":"01"},
    {"code":"01.5",    "name":"Ecommerce",                                "account_type":"receita",  "is_totalizer":False,"sign":1,  "parent_code":"01"},
    {"code":"01.6",    "name":"Stop Shop",                                "account_type":"receita",  "is_totalizer":False,"sign":1,  "parent_code":"01"},
    {"code":"01.7",    "name":"Loja Centro",                              "account_type":"receita",  "is_totalizer":False,"sign":1,  "parent_code":"01"},
    {"code":"01.8",    "name":"Loja Fábrica",                             "account_type":"receita",  "is_totalizer":False,"sign":1,  "parent_code":"01"},
    {"code":"02",      "name":"Devoluções",                               "account_type":"despesa",  "is_totalizer":False,"sign":-1, "parent_code":None},
    {"code":"02.1",    "name":"Devolução Varejo",                         "account_type":"despesa",  "is_totalizer":False,"sign":-1, "parent_code":"02"},
    {"code":"02.2",    "name":"Devolução Magazine",                       "account_type":"despesa",  "is_totalizer":False,"sign":-1, "parent_code":"02"},
    {"code":"02T",     "name":"Receita Bruta de Vendas",                  "account_type":"resultado","is_totalizer":True, "sign":1,  "parent_code":None},
    {"code":"03",      "name":"Custos Operacionais",                      "account_type":"despesa",  "is_totalizer":False,"sign":-1, "parent_code":None},
    {"code":"03.1",    "name":"Custos de Produção",                       "account_type":"despesa",  "is_totalizer":False,"sign":-1, "parent_code":"03"},
    {"code":"03.1.1",  "name":"Matéria Prima",                            "account_type":"despesa",  "is_totalizer":False,"sign":-1, "parent_code":"03.1"},
    {"code":"03.1.2",  "name":"(-) Devolução de Compras de MP",           "account_type":"despesa",  "is_totalizer":False,"sign":-1, "parent_code":"03.1"},
    {"code":"03.1.3",  "name":"Industrialização por Terceiros",           "account_type":"despesa",  "is_totalizer":False,"sign":-1, "parent_code":"03.1"},
    {"code":"03.1.4",  "name":"Fretes",                                   "account_type":"despesa",  "is_totalizer":False,"sign":-1, "parent_code":"03.1"},
    {"code":"03.1.5",  "name":"Manutenção de Equipamentos",               "account_type":"despesa",  "is_totalizer":False,"sign":-1, "parent_code":"03.1"},
    {"code":"03.1.6",  "name":"Combustível",                              "account_type":"despesa",  "is_totalizer":False,"sign":-1, "parent_code":"03.1"},
    {"code":"03.1.7",  "name":"Manutenção de Veículos",                   "account_type":"despesa",  "is_totalizer":False,"sign":-1, "parent_code":"03.1"},
    {"code":"03.1.8",  "name":"Insumos",                                  "account_type":"despesa",  "is_totalizer":False,"sign":-1, "parent_code":"03.1"},
    {"code":"03.1.9",  "name":"Estoque Inicial",                          "account_type":"despesa",  "is_totalizer":False,"sign":-1, "parent_code":"03.1"},
    {"code":"03.1.10", "name":"Estoque Final",                            "account_type":"despesa",  "is_totalizer":False,"sign":-1, "parent_code":"03.1"},
    {"code":"03.2",    "name":"MOD - Produção",                           "account_type":"despesa",  "is_totalizer":False,"sign":-1, "parent_code":"03"},
    {"code":"03.2.1",  "name":"Salários - Mão de Obra",                   "account_type":"despesa",  "is_totalizer":False,"sign":-1, "parent_code":"03.2"},
    {"code":"03.2.2",  "name":"Gratificações Produção",                   "account_type":"despesa",  "is_totalizer":False,"sign":-1, "parent_code":"03.2"},
    {"code":"03.2.3",  "name":"Comissões Produção",                       "account_type":"despesa",  "is_totalizer":False,"sign":-1, "parent_code":"03.2"},
    {"code":"03T",     "name":"Margem Bruta",                             "account_type":"resultado","is_totalizer":True, "sign":1,  "parent_code":None},
    {"code":"04",      "name":"Despesas Comerciais",                      "account_type":"despesa",  "is_totalizer":False,"sign":-1, "parent_code":None},
    {"code":"04.1",    "name":"Despesas Comerciais",                      "account_type":"despesa",  "is_totalizer":False,"sign":-1, "parent_code":"04"},
    {"code":"04.1.1",  "name":"Marketing e Publicidade",                  "account_type":"despesa",  "is_totalizer":False,"sign":-1, "parent_code":"04.1"},
    {"code":"04.1.2",  "name":"Comissão sobre Vendas",                    "account_type":"despesa",  "is_totalizer":False,"sign":-1, "parent_code":"04.1"},
    {"code":"04.1.3",  "name":"Viagens e Representações",                 "account_type":"despesa",  "is_totalizer":False,"sign":-1, "parent_code":"04.1"},
    {"code":"04.1.4",  "name":"Cartão de Crédito",                        "account_type":"despesa",  "is_totalizer":False,"sign":-1, "parent_code":"04.1"},
    {"code":"04.2",    "name":"Mão de Obra - Comercial",                  "account_type":"despesa",  "is_totalizer":False,"sign":-1, "parent_code":"04"},
    {"code":"04.2.1",  "name":"Salários Comercial",                       "account_type":"despesa",  "is_totalizer":False,"sign":-1, "parent_code":"04.2"},
    {"code":"04.2.2",  "name":"Salário Comercial PJ",                     "account_type":"despesa",  "is_totalizer":False,"sign":-1, "parent_code":"04.2"},
    {"code":"04.2.3",  "name":"Comissões do Comercial - Lojas",           "account_type":"despesa",  "is_totalizer":False,"sign":-1, "parent_code":"04.2"},
    {"code":"05T",     "name":"Margem Líquida",                           "account_type":"resultado","is_totalizer":True, "sign":1,  "parent_code":None},
    {"code":"06",      "name":"Despesas Administrativas",                 "account_type":"despesa",  "is_totalizer":False,"sign":-1, "parent_code":None},
    {"code":"06.1",    "name":"Mão de Obra - Administrativo",             "account_type":"despesa",  "is_totalizer":False,"sign":-1, "parent_code":"06"},
    {"code":"06.1.1",  "name":"Salário Administrativo",                   "account_type":"despesa",  "is_totalizer":False,"sign":-1, "parent_code":"06.1"},
    {"code":"06.2",    "name":"Despesas Mensais",                         "account_type":"despesa",  "is_totalizer":False,"sign":-1, "parent_code":"06"},
    {"code":"06.2.1",  "name":"Água e Saneamento",                        "account_type":"despesa",  "is_totalizer":False,"sign":-1, "parent_code":"06.2"},
    {"code":"06.2.2",  "name":"Energia Elétrica",                         "account_type":"despesa",  "is_totalizer":False,"sign":-1, "parent_code":"06.2"},
    {"code":"06.2.3",  "name":"Pedágios",                                 "account_type":"despesa",  "is_totalizer":False,"sign":-1, "parent_code":"06.2"},
    {"code":"06.2.4",  "name":"Honorários Advocatícios",                  "account_type":"despesa",  "is_totalizer":False,"sign":-1, "parent_code":"06.2"},
    {"code":"06.2.5",  "name":"Uso e Consumo",                            "account_type":"despesa",  "is_totalizer":False,"sign":-1, "parent_code":"06.2"},
    {"code":"06.2.6",  "name":"Correios",                                 "account_type":"despesa",  "is_totalizer":False,"sign":-1, "parent_code":"06.2"},
    {"code":"06.2.7",  "name":"Seguros Diversos",                         "account_type":"despesa",  "is_totalizer":False,"sign":-1, "parent_code":"06.2"},
    {"code":"06.2.8",  "name":"Serviços Profissionais",                   "account_type":"despesa",  "is_totalizer":False,"sign":-1, "parent_code":"06.2"},
    {"code":"06.2.9",  "name":"Segurança e Vigilância",                   "account_type":"despesa",  "is_totalizer":False,"sign":-1, "parent_code":"06.2"},
    {"code":"06.2.10", "name":"Entidades e Associações",                  "account_type":"despesa",  "is_totalizer":False,"sign":-1, "parent_code":"06.2"},
    {"code":"06.2.11", "name":"Aluguéis",                                 "account_type":"despesa",  "is_totalizer":False,"sign":-1, "parent_code":"06.2"},
    {"code":"06.2.12", "name":"Consultoria Financeira ADM",               "account_type":"despesa",  "is_totalizer":False,"sign":-1, "parent_code":"06.2"},
    {"code":"06.2.13", "name":"Sistemas e Software",                      "account_type":"despesa",  "is_totalizer":False,"sign":-1, "parent_code":"06.2"},
    {"code":"06.2.14", "name":"Notificação de Trânsito",                  "account_type":"despesa",  "is_totalizer":False,"sign":-1, "parent_code":"06.2"},
    {"code":"06.2.15", "name":"Telefonia e Internet",                     "account_type":"despesa",  "is_totalizer":False,"sign":-1, "parent_code":"06.2"},
    {"code":"06.2.16", "name":"Manutenção Predial",                       "account_type":"despesa",  "is_totalizer":False,"sign":-1, "parent_code":"06.2"},
    {"code":"06.2.17", "name":"Consórcio",                                "account_type":"despesa",  "is_totalizer":False,"sign":-1, "parent_code":"06.2"},
    {"code":"06.2.18", "name":"Manutenção de Veículos",                   "account_type":"despesa",  "is_totalizer":False,"sign":-1, "parent_code":"06.2"},
    {"code":"06.2.19", "name":"Lanches, Refeições, Copa e Cozinha",       "account_type":"despesa",  "is_totalizer":False,"sign":-1, "parent_code":"06.2"},
    {"code":"06.2.20", "name":"Assistência Médica",                       "account_type":"despesa",  "is_totalizer":False,"sign":-1, "parent_code":"06.2"},
    {"code":"06.2.21", "name":"Honorários Contábeis",                     "account_type":"despesa",  "is_totalizer":False,"sign":-1, "parent_code":"06.2"},
    {"code":"06.2.22", "name":"Mensalidade Sindical",                     "account_type":"despesa",  "is_totalizer":False,"sign":-1, "parent_code":"06.2"},
    {"code":"06.2.23", "name":"Mensalidade Sistemas e Software",          "account_type":"despesa",  "is_totalizer":False,"sign":-1, "parent_code":"06.2"},
    {"code":"06.2.24", "name":"Processos e Ações Judiciais",              "account_type":"despesa",  "is_totalizer":False,"sign":-1, "parent_code":"06.2"},
    {"code":"06.2.25", "name":"Material de Expediente",                   "account_type":"despesa",  "is_totalizer":False,"sign":-1, "parent_code":"06.2"},
    {"code":"07",      "name":"Despesas Tributárias Operacionais",        "account_type":"despesa",  "is_totalizer":False,"sign":-1, "parent_code":None},
    {"code":"07.1",    "name":"Impostos e Taxas",                         "account_type":"despesa",  "is_totalizer":False,"sign":-1, "parent_code":"07"},
    {"code":"07.1.1",  "name":"Impostos e Taxas Diversas",                "account_type":"despesa",  "is_totalizer":False,"sign":-1, "parent_code":"07.1"},
    {"code":"07.1.2",  "name":"IPTU",                                     "account_type":"despesa",  "is_totalizer":False,"sign":-1, "parent_code":"07.1"},
    {"code":"07.1.3",  "name":"IPVA",                                     "account_type":"despesa",  "is_totalizer":False,"sign":-1, "parent_code":"07.1"},
    {"code":"07.1.4",  "name":"Alvará",                                   "account_type":"despesa",  "is_totalizer":False,"sign":-1, "parent_code":"07.1"},
    {"code":"07T",     "name":"Lucro / Prejuízo Operacional",             "account_type":"resultado","is_totalizer":True, "sign":1,  "parent_code":None},
    {"code":"08",      "name":"Receitas e Despesas Financeiras",          "account_type":"resultado","is_totalizer":False,"sign":1,  "parent_code":None},
    {"code":"08.1",    "name":"Receitas e Rendimentos Financeiros",       "account_type":"receita",  "is_totalizer":False,"sign":1,  "parent_code":"08"},
    {"code":"08.1.1",  "name":"Descontos Financeiros Obtidos",            "account_type":"receita",  "is_totalizer":False,"sign":1,  "parent_code":"08.1"},
    {"code":"08.1.2",  "name":"Rendimentos de Aplicações",                "account_type":"receita",  "is_totalizer":False,"sign":1,  "parent_code":"08.1"},
    {"code":"08.2",    "name":"Despesas Financeiras",                     "account_type":"despesa",  "is_totalizer":False,"sign":-1, "parent_code":"08"},
    {"code":"08.2.1",  "name":"IOF",                                      "account_type":"despesa",  "is_totalizer":False,"sign":-1, "parent_code":"08.2"},
    {"code":"08.2.2",  "name":"Juros s/ Empréstimo",                      "account_type":"despesa",  "is_totalizer":False,"sign":-1, "parent_code":"08.2"},
    {"code":"08.2.3",  "name":"Tarifas Bancárias",                        "account_type":"despesa",  "is_totalizer":False,"sign":-1, "parent_code":"08.2"},
    {"code":"08.2.4",  "name":"Juros Antecipação",                        "account_type":"despesa",  "is_totalizer":False,"sign":-1, "parent_code":"08.2"},
    {"code":"08.2.5",  "name":"Verba MKT",                                "account_type":"despesa",  "is_totalizer":False,"sign":-1, "parent_code":"08.2"},
    {"code":"08.2.6",  "name":"Apropriação de Juros sobre Empréstimos",   "account_type":"despesa",  "is_totalizer":False,"sign":-1, "parent_code":"08.2"},
    {"code":"08.2.7",  "name":"Multas e Juros sobre Tributos",            "account_type":"despesa",  "is_totalizer":False,"sign":-1, "parent_code":"08.2"},
    {"code":"08T",     "name":"Resultado Antes de Outras Receitas e Despesas","account_type":"resultado","is_totalizer":True,"sign":1,"parent_code":None},
    {"code":"09",      "name":"Outras Receitas e Despesas Não Operacionais","account_type":"resultado","is_totalizer":False,"sign":1, "parent_code":None},
    {"code":"09.1",    "name":"Outras Receitas Não Operacionais",         "account_type":"receita",  "is_totalizer":False,"sign":1,  "parent_code":"09"},
    {"code":"09.1.1",  "name":"Bonificações",                             "account_type":"receita",  "is_totalizer":False,"sign":1,  "parent_code":"09.1"},
    {"code":"09.1.2",  "name":"Vendas do Ativo Imobilizado",              "account_type":"receita",  "is_totalizer":False,"sign":1,  "parent_code":"09.1"},
    {"code":"09.2",    "name":"Outras Despesas Não Operacionais",         "account_type":"despesa",  "is_totalizer":False,"sign":-1, "parent_code":"09"},
    {"code":"09.2.1",  "name":"Custo Vendas do Ativo Imobilizado",        "account_type":"despesa",  "is_totalizer":False,"sign":-1, "parent_code":"09.2"},
    {"code":"09.2.2",  "name":"Depreciações",                             "account_type":"despesa",  "is_totalizer":False,"sign":-1, "parent_code":"09.2"},
    {"code":"09T",     "name":"Resultado Antes de Impostos",              "account_type":"resultado","is_totalizer":True, "sign":1,  "parent_code":None},
    {"code":"10",      "name":"Impostos sobre o Faturamento",             "account_type":"despesa",  "is_totalizer":False,"sign":-1, "parent_code":None},
    {"code":"10.1",    "name":"Impostos sobre Faturamento",               "account_type":"despesa",  "is_totalizer":False,"sign":-1, "parent_code":"10"},
    {"code":"10.1.1",  "name":"FUMDES",                                   "account_type":"despesa",  "is_totalizer":False,"sign":-1, "parent_code":"10.1"},
    {"code":"10.1.2",  "name":"PIS",                                      "account_type":"despesa",  "is_totalizer":False,"sign":-1, "parent_code":"10.1"},
    {"code":"10.1.3",  "name":"DIFAL MG",                                 "account_type":"despesa",  "is_totalizer":False,"sign":-1, "parent_code":"10.1"},
    {"code":"10.1.4",  "name":"DIFAL ES",                                 "account_type":"despesa",  "is_totalizer":False,"sign":-1, "parent_code":"10.1"},
    {"code":"10.1.5",  "name":"DIFAL PR",                                 "account_type":"despesa",  "is_totalizer":False,"sign":-1, "parent_code":"10.1"},
    {"code":"10.1.6",  "name":"DIFAL RS",                                 "account_type":"despesa",  "is_totalizer":False,"sign":-1, "parent_code":"10.1"},
    {"code":"10.1.7",  "name":"DIFAL SP",                                 "account_type":"despesa",  "is_totalizer":False,"sign":-1, "parent_code":"10.1"},
    {"code":"10.1.8",  "name":"ISS",                                      "account_type":"despesa",  "is_totalizer":False,"sign":-1, "parent_code":"10.1"},
    {"code":"10.1.9",  "name":"IR PJ",                                    "account_type":"despesa",  "is_totalizer":False,"sign":-1, "parent_code":"10.1"},
    {"code":"10.1.10", "name":"CSLL",                                     "account_type":"despesa",  "is_totalizer":False,"sign":-1, "parent_code":"10.1"},
    {"code":"10.1.11", "name":"COFINS",                                   "account_type":"despesa",  "is_totalizer":False,"sign":-1, "parent_code":"10.1"},
    {"code":"10.1.12", "name":"ICMS",                                     "account_type":"despesa",  "is_totalizer":False,"sign":-1, "parent_code":"10.1"},
    {"code":"10.1.13", "name":"ICMS Fundo Social",                        "account_type":"despesa",  "is_totalizer":False,"sign":-1, "parent_code":"10.1"},
    {"code":"10T",     "name":"Resultado Líquido",                        "account_type":"resultado","is_totalizer":True, "sign":1,  "parent_code":None},
    {"code":"11",      "name":"Aportes e Distribuições a Sócios",         "account_type":"despesa",  "is_totalizer":False,"sign":-1, "parent_code":None},
    {"code":"11.1",    "name":"Distribuições de Lucros",                  "account_type":"despesa",  "is_totalizer":False,"sign":-1, "parent_code":"11"},
    {"code":"11.1.1",  "name":"Pro Labore",                               "account_type":"despesa",  "is_totalizer":False,"sign":-1, "parent_code":"11.1"},
    {"code":"11.1.2",  "name":"Retiradas",                                "account_type":"despesa",  "is_totalizer":False,"sign":-1, "parent_code":"11.1"},
    {"code":"11T",     "name":"Resultado Após Distribuições",             "account_type":"resultado","is_totalizer":True, "sign":1,  "parent_code":None},
    {"code":"12",      "name":"Principal de Empréstimos",                 "account_type":"despesa",  "is_totalizer":False,"sign":-1, "parent_code":None},
    {"code":"12T",     "name":"Resultado Após Pagamento de Empréstimos",  "account_type":"resultado","is_totalizer":True, "sign":1,  "parent_code":None},
]


# ── Helpers ───────────────────────────────────────────────────────────────────

_MONTHS_PT = ["Jan","Fev","Mar","Abr","Mai","Jun","Jul","Ago","Set","Out","Nov","Dez"]


def _build_account_tree(accounts: list) -> list:
    by_parent: dict = {}
    for a in accounts:
        by_parent.setdefault(a.parent_id, []).append(a)
    result = []
    def _walk(parent_id, depth):
        for a in sorted(by_parent.get(parent_id, []), key=lambda x: (x.sort_order, x.code)):
            result.append((a, depth))
            _walk(a.id, depth + 1)
    _walk(None, 0)
    return result


def _calc_totalizer(account_id: int, entries_by_account: dict, accounts_by_parent: dict) -> dict:
    totals: dict = {m: [0.0, 0.0] for m in range(1, 13)}
    for child in accounts_by_parent.get(account_id, []):
        if child.is_totalizer:
            sub = _calc_totalizer(child.id, entries_by_account, accounts_by_parent)
            for m in range(1, 13):
                totals[m][0] += sub[m][0] * child.sign
                totals[m][1] += sub[m][1] * child.sign
        else:
            for m in range(1, 13):
                e = entries_by_account.get((child.id, m))
                if e:
                    totals[m][0] += e.value_budgeted * child.sign
                    totals[m][1] += e.value_realized * child.sign
    return {m: (totals[m][0], totals[m][1]) for m in range(1, 13)}


def _load_grid(session, company_id: int, plan_id: int):
    accounts = session.exec(
        select(BudgetAccount)
        .where(BudgetAccount.company_id == company_id, BudgetAccount.is_active == True)
        .order_by(BudgetAccount.sort_order, BudgetAccount.code)
    ).all()
    entries = session.exec(
        select(BudgetEntry)
        .where(BudgetEntry.company_id == company_id, BudgetEntry.plan_id == plan_id)
    ).all()
    entries_by_account = {(e.account_id, e.month): e for e in entries}
    accounts_by_parent: dict = {}
    for a in accounts:
        accounts_by_parent.setdefault(a.parent_id, []).append(a)
    tree = _build_account_tree(accounts)
    rows = []
    for (acc, depth) in tree:
        if acc.is_totalizer:
            vals = _calc_totalizer(acc.id, entries_by_account, accounts_by_parent)
            months = {m: {"b": round(vals[m][0], 2), "r": round(vals[m][1], 2)} for m in range(1, 13)}
        else:
            months = {}
            for m in range(1, 13):
                e = entries_by_account.get((acc.id, m))
                months[m] = {"b": e.value_budgeted if e else 0.0,
                              "r": e.value_realized if e else 0.0}
        total_b = sum(months[m]["b"] for m in range(1, 13))
        total_r = sum(months[m]["r"] for m in range(1, 13))
        rows.append({
            "id": acc.id, "code": acc.code, "name": acc.name,
            "type": acc.account_type, "is_totalizer": acc.is_totalizer,
            "depth": depth, "months": months,
            "total_b": round(total_b, 2), "total_r": round(total_r, 2),
        })
    return rows


_ORC_ROLES = ("admin", "equipe", "cliente")


# ── Rotas ─────────────────────────────────────────────────────────────────────

@app.get("/ferramentas/orcamento", response_class=HTMLResponse)
@require_login
async def orcamento_index(request: Request, session: Session = Depends(get_session)):
    ctx = get_tenant_context(request, session)
    if not ctx or ctx.membership.role not in _ORC_ROLES:
        return RedirectResponse("/", status_code=303)
    cc = get_client_or_none(session, ctx.company.id, get_active_client_id(request, session, ctx))
    if not cc:
        return RedirectResponse("/ferramentas", status_code=303)

    plans = session.exec(
        select(BudgetPlan)
        .where(BudgetPlan.company_id == ctx.company.id, BudgetPlan.client_id == cc.id)
        .order_by(BudgetPlan.year.desc(), BudgetPlan.name)
    ).all()
    return render("orcamento_index.html", request=request, context={
        "current_user": ctx.user, "current_company": ctx.company,
        "role": ctx.membership.role, "current_client": cc,
        "plans": plans,
    })


@app.post("/ferramentas/orcamento/plano/criar")
@require_login
async def orcamento_criar_plano(request: Request, session: Session = Depends(get_session)):
    ctx = get_tenant_context(request, session)
    if not ctx or ctx.membership.role not in _ORC_ROLES:
        return JSONResponse({"ok": False}, status_code=403)
    cc = get_client_or_none(session, ctx.company.id, get_active_client_id(request, session, ctx))
    if not cc:
        return JSONResponse({"ok": False, "erro": "Selecione um cliente"}, status_code=400)
    body = await request.json()
    plan = BudgetPlan(
        company_id=ctx.company.id,
        client_id=cc.id,
        name=(body.get("name") or "").strip() or f"Orçamento {body.get('year', 2026)}",
        year=int(body.get("year") or 2026),
        description=(body.get("description") or "").strip(),
    )
    session.add(plan)
    session.commit()
    session.refresh(plan)
    return JSONResponse({"ok": True, "id": plan.id})


@app.post("/ferramentas/orcamento/plano/{plan_id}/deletar")
@require_login
async def orcamento_deletar_plano(plan_id: int, request: Request, session: Session = Depends(get_session)):
    ctx = get_tenant_context(request, session)
    if not ctx or ctx.membership.role not in _ORC_ROLES:
        return JSONResponse({"ok": False}, status_code=403)
    plan = session.get(BudgetPlan, plan_id)
    if plan and plan.company_id == ctx.company.id:
        for e in session.exec(select(BudgetEntry).where(BudgetEntry.plan_id == plan_id)).all():
            session.delete(e)
        session.delete(plan)
        session.commit()
    return JSONResponse({"ok": True})


# ATENÇÃO: /contas deve vir ANTES de /{plan_id} para não ser capturado como ID
@app.get("/ferramentas/orcamento/contas", response_class=HTMLResponse)
@require_login
async def orcamento_contas(request: Request, session: Session = Depends(get_session)):
    ctx = get_tenant_context(request, session)
    if not ctx or ctx.membership.role not in _ORC_ROLES:
        return RedirectResponse("/", status_code=303)
    cc = get_client_or_none(session, ctx.company.id, get_active_client_id(request, session, ctx))

    accounts = session.exec(
        select(BudgetAccount)
        .where(BudgetAccount.company_id == ctx.company.id, BudgetAccount.is_active == True)
        .order_by(BudgetAccount.sort_order, BudgetAccount.code)
    ).all()
    tree = _build_account_tree(accounts)
    return render("orcamento_contas.html", request=request, context={
        "current_user": ctx.user, "current_company": ctx.company,
        "role": ctx.membership.role, "current_client": cc,
        "tree": tree,
    })


@app.get("/ferramentas/orcamento/{plan_id}", response_class=HTMLResponse)
@require_login
async def orcamento_grid(plan_id: int, request: Request, session: Session = Depends(get_session)):
    ctx = get_tenant_context(request, session)
    if not ctx or ctx.membership.role not in _ORC_ROLES:
        return RedirectResponse("/", status_code=303)
    plan = session.get(BudgetPlan, plan_id)
    if not plan or plan.company_id != ctx.company.id:
        return RedirectResponse("/ferramentas/orcamento", status_code=303)
    cc = get_client_or_none(session, ctx.company.id, get_active_client_id(request, session, ctx))

    rows = _load_grid(session, ctx.company.id, plan_id)
    return render("orcamento_grid.html", request=request, context={
        "current_user": ctx.user, "current_company": ctx.company,
        "role": ctx.membership.role, "current_client": cc,
        "plan": plan, "rows": rows,
        "months": _MONTHS_PT,
        "rows_json": _json_orc.dumps(rows),
    })


# ── API endpoints ─────────────────────────────────────────────────────────────

@app.post("/api/orcamento/entry")
@require_login
async def orcamento_save_entry(request: Request, session: Session = Depends(get_session)):
    ctx = get_tenant_context(request, session)
    if not ctx or ctx.membership.role not in _ORC_ROLES:
        return JSONResponse({"ok": False}, status_code=403)
    body   = await request.json()
    plan_id    = int(body["plan_id"])
    account_id = int(body["account_id"])
    month      = int(body["month"])
    field      = body["field"]
    value      = float(body.get("value") or 0)

    plan = session.get(BudgetPlan, plan_id)
    if not plan or plan.company_id != ctx.company.id:
        return JSONResponse({"ok": False}, status_code=403)

    entry = session.exec(
        select(BudgetEntry).where(
            BudgetEntry.plan_id == plan_id,
            BudgetEntry.account_id == account_id,
            BudgetEntry.month == month,
        )
    ).first()
    if not entry:
        entry = BudgetEntry(company_id=ctx.company.id, plan_id=plan_id,
                            account_id=account_id, month=month)
    if field == "b":
        entry.value_budgeted = value
    else:
        entry.value_realized = value
    entry.updated_at = utcnow()
    session.add(entry)
    session.commit()
    return JSONResponse({"ok": True})


@app.post("/api/orcamento/conta/criar")
@require_login
async def orcamento_criar_conta(request: Request, session: Session = Depends(get_session)):
    ctx = get_tenant_context(request, session)
    if not ctx or ctx.membership.role not in _ORC_ROLES:
        return JSONResponse({"ok": False}, status_code=403)
    body = await request.json()
    _raw_pid = body.get("parent_id")
    _parent_id = int(_raw_pid) if _raw_pid not in (None, "", 0, "0") else None
    siblings = session.exec(
        select(BudgetAccount).where(
            BudgetAccount.company_id == ctx.company.id,
            BudgetAccount.parent_id == _parent_id,
        )
    ).all()
    max_order = max((a.sort_order for a in siblings), default=-1) + 1
    acc = BudgetAccount(
        company_id=ctx.company.id,
        code=(body.get("code") or "").strip(),
        name=(body.get("name") or "").strip(),
        account_type=(body.get("account_type") or "despesa"),
        parent_id=_parent_id,
        is_totalizer=bool(body.get("is_totalizer")),
        sign=int(body.get("sign") or 1),
        sort_order=max_order,
    )
    session.add(acc)
    session.commit()
    session.refresh(acc)
    return JSONResponse({"ok": True, "id": acc.id})


@app.post("/api/orcamento/conta/{acc_id}/editar")
@require_login
async def orcamento_editar_conta(acc_id: int, request: Request, session: Session = Depends(get_session)):
    ctx = get_tenant_context(request, session)
    if not ctx or ctx.membership.role not in _ORC_ROLES:
        return JSONResponse({"ok": False}, status_code=403)
    body = await request.json()
    acc = session.get(BudgetAccount, acc_id)
    if not acc or acc.company_id != ctx.company.id:
        return JSONResponse({"ok": False}, status_code=404)
    for k, v in [("code", body.get("code")), ("name", body.get("name")),
                  ("account_type", body.get("account_type")),
                  ("is_totalizer", body.get("is_totalizer")),
                  ("sign", body.get("sign")), ("parent_id", body.get("parent_id")),
                  ("sort_order", body.get("sort_order"))]:
        if k in body:
            if k == "is_totalizer": setattr(acc, k, bool(v))
            elif k in ("sign", "sort_order"): setattr(acc, k, int(v))
            elif k == "parent_id": acc.parent_id = int(v) if v not in (None, "", 0, "0") else None
            else: setattr(acc, k, v)
    acc.updated_at = utcnow()
    session.add(acc)
    session.commit()
    return JSONResponse({"ok": True})


@app.post("/api/orcamento/conta/{acc_id}/deletar")
@require_login
async def orcamento_deletar_conta(acc_id: int, request: Request, session: Session = Depends(get_session)):
    ctx = get_tenant_context(request, session)
    if not ctx or ctx.membership.role not in _ORC_ROLES:
        return JSONResponse({"ok": False}, status_code=403)
    acc = session.get(BudgetAccount, acc_id)
    if not acc or acc.company_id != ctx.company.id:
        return JSONResponse({"ok": False}, status_code=404)
    acc.is_active = False
    acc.updated_at = utcnow()
    session.add(acc)
    session.commit()
    return JSONResponse({"ok": True})


@app.post("/api/orcamento/conta/reordenar")
@require_login
async def orcamento_reordenar(request: Request, session: Session = Depends(get_session)):
    ctx = get_tenant_context(request, session)
    if not ctx or ctx.membership.role not in _ORC_ROLES:
        return JSONResponse({"ok": False}, status_code=403)
    body = await request.json()
    for item in body:
        acc = session.get(BudgetAccount, int(item["id"]))
        if acc and acc.company_id == ctx.company.id:
            acc.sort_order = int(item["sort_order"])
            _pid = item.get("parent_id"); acc.parent_id = int(_pid) if _pid not in (None, "", 0, "0") else None
            session.add(acc)
    session.commit()
    return JSONResponse({"ok": True})


@app.post("/api/orcamento/conta/importar-modelo")
@require_login
async def orcamento_importar_modelo(request: Request, session: Session = Depends(get_session)):
    ctx = get_tenant_context(request, session)
    if not ctx or ctx.membership.role not in ("admin", "equipe"):
        return JSONResponse({"ok": False, "msg": "Sem permissão"}, status_code=403)

    # Remove fisicamente todos os registros (ativos e soft-deleted) antes de reimportar
    from sqlalchemy import delete as _sa_delete
    session.exec(_sa_delete(BudgetAccount).where(BudgetAccount.company_id == ctx.company.id))
    session.flush()

    # Insere em ordem, mantendo mapa code → id para resolver parent_id
    code_to_id: dict = {}
    for i, item in enumerate(_ORC_MODELO_PADRAO):
        parent_id = code_to_id.get(item["parent_code"]) if item["parent_code"] else None
        acc = BudgetAccount(
            company_id=ctx.company.id,
            code=item["code"],
            name=item["name"],
            account_type=item["account_type"],
            parent_id=parent_id,
            is_totalizer=item["is_totalizer"],
            sign=item["sign"],
            sort_order=i,
        )
        session.add(acc)
        session.flush()
        code_to_id[item["code"]] = acc.id

    session.commit()
    return JSONResponse({"ok": True, "total": len(_ORC_MODELO_PADRAO)})


@app.get("/api/orcamento/{plan_id}/augur-contexto")
@require_login
async def orcamento_augur_contexto(plan_id: int, request: Request, session: Session = Depends(get_session)):
    ctx = get_tenant_context(request, session)
    if not ctx:
        return JSONResponse({"ok": False}, status_code=403)
    plan = session.get(BudgetPlan, plan_id)
    if not plan or plan.company_id != ctx.company.id:
        return JSONResponse({"ok": False}, status_code=404)
    rows = _load_grid(session, ctx.company.id, plan_id)
    return JSONResponse({"ok": True, "plan": plan.name, "year": plan.year, "rows": rows})


# ── Augur: injeção de contexto ─────────────────────────────────────────────────

def _orcamento_contexto_para_augur(session, company_id: int, client_id=None) -> str:
    try:
        q = select(BudgetPlan).where(
            BudgetPlan.company_id == company_id, BudgetPlan.is_active == True
        )
        if client_id:
            q = q.where(BudgetPlan.client_id == client_id)
        plan = session.exec(q.order_by(BudgetPlan.year.desc())).first()
        if not plan:
            return ""
        rows = _load_grid(session, company_id, plan.id)
        if not rows:
            return ""
        lines = [f"## Orçamento: {plan.name} ({plan.year})", ""]
        lines.append(f"{'Conta':<40} {'Orçado Anual':>14} {'Realizado':>14} {'Var%':>7}")
        lines.append("-" * 78)
        for row in rows:
            indent = "  " * row["depth"]
            tag    = "[ TOTAL ]" if row["is_totalizer"] else ""
            tb, tr = row["total_b"], row["total_r"]
            var    = f"{((tr-tb)/abs(tb)*100):+.1f}%" if tb else "—"
            lines.append(
                f"{indent}{row['code']} {row['name'][:35-len(indent)]:<35} {tag}"
                f" {tb:>14,.2f} {tr:>14,.2f} {var:>7}"
            )
        return "\n".join(lines)
    except Exception:
        return ""


try:
    _orig_enriquecer_orc = _enriquecer_client_data

    def _enriquecer_com_orcamento(session, company_id, client_id, client, client_data):
        data = _orig_enriquecer_orc(session, company_id, client_id, client, client_data)
        try:
            texto = _orcamento_contexto_para_augur(session, company_id, client_id)
            if texto:
                data["orcamento_resumo"] = texto
        except Exception:
            pass
        return data

    _enriquecer_client_data = _enriquecer_com_orcamento
except Exception:
    pass


# ── Templates ─────────────────────────────────────────────────────────────────

TEMPLATES["orcamento_index.html"] = r"""
{% extends "base.html" %}
{% block content %}
<div class="d-flex justify-content-between align-items-center mb-3">
  <div>
    <h4 class="mb-0">Planejamento Orçamentário</h4>
    <div class="muted small">
      {% if current_client %}Cliente: <strong>{{ current_client.name }}</strong>{% endif %}
    </div>
  </div>
  <div class="d-flex gap-2">
    <a href="/ferramentas/orcamento/contas" class="btn btn-outline-secondary btn-sm">
      <i class="bi bi-list-ul me-1"></i>Plano de Contas
    </a>
    <button class="btn btn-primary btn-sm" onclick="novoPlano()">
      <i class="bi bi-plus-lg me-1"></i>Novo Plano
    </button>
  </div>
</div>

{% if plans %}
<div class="row g-3">
  {% for p in plans %}
  <div class="col-md-4">
    <div class="card h-100">
      <div class="card-body">
        <div class="d-flex justify-content-between align-items-start mb-2">
          <div>
            <div class="fw-semibold">{{ p.name }}</div>
            <div class="muted small">{{ p.year }}</div>
          </div>
          <span class="badge {% if p.is_active %}bg-success{% else %}bg-secondary{% endif %}">
            {% if p.is_active %}Ativo{% else %}Inativo{% endif %}
          </span>
        </div>
        {% if p.description %}<div class="muted small mb-2">{{ p.description }}</div>{% endif %}
        <div class="d-flex gap-2 mt-3">
          <a href="/ferramentas/orcamento/{{ p.id }}" class="btn btn-primary btn-sm flex-grow-1">
            <i class="bi bi-table me-1"></i>Abrir
          </a>
          <button class="btn btn-outline-danger btn-sm" onclick="deletarPlano({{ p.id }}, '{{ p.name }}')">
            <i class="bi bi-trash"></i>
          </button>
        </div>
      </div>
    </div>
  </div>
  {% endfor %}
</div>
{% else %}
<div class="alert alert-info mt-3">
  Nenhum plano criado para este cliente ainda.<br>
  <strong>Dica:</strong> primeiro configure o <a href="/ferramentas/orcamento/contas">plano de contas</a> e depois crie um plano.
</div>
{% endif %}

<div class="modal fade" id="modalPlano" tabindex="-1">
  <div class="modal-dialog">
    <div class="modal-content">
      <div class="modal-header">
        <h5 class="modal-title">Novo Plano Orçamentário</h5>
        <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
      </div>
      <div class="modal-body">
        <div class="mb-3">
          <label class="form-label">Ano</label>
          <input type="number" id="pYear" class="form-control" value="2026">
        </div>
        <div class="mb-3">
          <label class="form-label">Nome</label>
          <input type="text" id="pName" class="form-control" placeholder="Ex: Orçamento 2026">
        </div>
        <div class="mb-3">
          <label class="form-label">Descrição (opcional)</label>
          <input type="text" id="pDesc" class="form-control">
        </div>
      </div>
      <div class="modal-footer">
        <button class="btn btn-secondary" data-bs-dismiss="modal">Cancelar</button>
        <button class="btn btn-primary" onclick="criarPlano()">Criar</button>
      </div>
    </div>
  </div>
</div>
<script>
function novoPlano() { new bootstrap.Modal(document.getElementById('modalPlano')).show(); }
async function criarPlano() {
  const r = await fetch('/ferramentas/orcamento/plano/criar', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({
      name: document.getElementById('pName').value,
      year: document.getElementById('pYear').value,
      description: document.getElementById('pDesc').value,
    })
  });
  const d = await r.json();
  if (d.ok) window.location = '/ferramentas/orcamento/' + d.id;
  else alert(d.erro || 'Erro ao criar plano.');
}
async function deletarPlano(id, name) {
  if (!confirm('Deletar plano "' + name + '"?')) return;
  await fetch('/ferramentas/orcamento/plano/' + id + '/deletar', {method:'POST'});
  location.reload();
}
</script>
{% endblock %}
"""

TEMPLATES["orcamento_contas.html"] = r"""
{% extends "base.html" %}
{% block content %}
<style>
.orc-totalizer{background:#f0f5ff;font-weight:600;}
.orc-indent-0{padding-left:4px!important;}
.orc-indent-1{padding-left:20px!important;}
.orc-indent-2{padding-left:40px!important;}
.orc-indent-3{padding-left:60px!important;}
.orc-indent-4{padding-left:80px!important;}
</style>
<div class="d-flex justify-content-between align-items-center mb-3">
  <div>
    <h4 class="mb-0">Plano de Contas</h4>
    <div class="muted small">Estrutura compartilhada entre todos os clientes da empresa.</div>
  </div>
  <div class="d-flex gap-2 flex-wrap">
    <a href="/ferramentas/orcamento" class="btn btn-outline-secondary btn-sm">← Voltar</a>
    {% if not tree %}
    <button class="btn btn-outline-primary btn-sm" onclick="importarModelo()" id="btnModelo">
      📥 Usar modelo padrão
    </button>
    {% endif %}
    <button class="btn btn-primary btn-sm" onclick="novaConta(null)">
      Nova Conta
    </button>
  </div>
</div>

<div class="card p-0 overflow-hidden">
  <table class="table table-hover mb-0">
    <thead class="table-light">
      <tr>
        <th style="width:80px">Código</th>
        <th>Nome</th>
        <th style="width:100px">Tipo</th>
        <th style="width:120px">Totalizadora</th>
        <th style="width:100px"></th>
      </tr>
    </thead>
    <tbody>
      {% for acc, depth in tree %}
      <tr class="{% if acc.is_totalizer %}orc-totalizer{% endif %}" data-id="{{ acc.id }}">
        <td class="orc-indent-{{ depth }} small font-monospace">{{ acc.code }}</td>
        <td class="orc-indent-{{ depth }}">
          {% if acc.is_totalizer %}<i class="bi bi-calculator me-1 text-primary"></i>{% endif %}
          {{ acc.name }}
        </td>
        <td><span class="badge bg-light text-dark border" style="font-size:.72rem;">{{ acc.account_type }}</span></td>
        <td>{% if acc.is_totalizer %}<span class="badge bg-primary">Sim</span>{% else %}<span class="muted small">—</span>{% endif %}</td>
        <td class="text-end" style="white-space:nowrap;">
          <button class="btn btn-outline-secondary btn-sm" onclick="novaConta({{ acc.id }})" title="Nova sub-conta" style="font-size:.75rem;padding:1px 6px;">+ Sub</button>
          <button class="btn btn-outline-secondary btn-sm" onclick="editarConta({{ acc.id }}, '{{ acc.code }}', '{{ acc.name|replace("'", "\\'") }}', '{{ acc.account_type }}', {{ acc.is_totalizer|lower }}, {{ acc.sign }})" title="Editar" style="font-size:.75rem;padding:1px 6px;">Editar</button>
          <button class="btn btn-outline-danger btn-sm" onclick="deletarConta({{ acc.id }}, '{{ acc.name|replace("'", "\\'") }}')" title="Excluir" style="font-size:.75rem;padding:1px 6px;">Remover</button>
        </td>
      </tr>
      {% endfor %}
      {% if not tree %}
      <tr><td colspan="5" class="text-center muted py-4">Nenhuma conta cadastrada. Clique em "Nova Conta" para começar.</td></tr>
      {% endif %}
    </tbody>
  </table>
</div>

<div class="modal fade" id="modalConta" tabindex="-1">
  <div class="modal-dialog">
    <div class="modal-content">
      <div class="modal-header">
        <h5 class="modal-title" id="modalContaTitulo">Nova Conta</h5>
        <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
      </div>
      <div class="modal-body">
        <input type="hidden" id="cId">
        <input type="hidden" id="cParentId">
        <div id="cParentInfo" class="alert alert-info py-2 small mb-3" style="display:none;"></div>
        <div class="row g-2">
          <div class="col-4">
            <label class="form-label">Código</label>
            <input type="text" id="cCode" class="form-control form-control-sm" placeholder="1.2.3">
          </div>
          <div class="col-8">
            <label class="form-label">Nome</label>
            <input type="text" id="cName" class="form-control form-control-sm">
          </div>
        </div>
        <div class="row g-2 mt-1">
          <div class="col-5">
            <label class="form-label">Tipo</label>
            <select id="cType" class="form-select form-select-sm">
              <option value="receita">Receita</option>
              <option value="despesa">Despesa</option>
              <option value="resultado">Resultado</option>
              <option value="ativo">Ativo</option>
              <option value="passivo">Passivo</option>
            </select>
          </div>
          <div class="col-4">
            <label class="form-label">Sinal</label>
            <select id="cSign" class="form-select form-select-sm">
              <option value="1">+ (soma)</option>
              <option value="-1">− (subtrai)</option>
            </select>
          </div>
          <div class="col-3">
            <label class="form-label">Totaliz.</label>
            <select id="cTot" class="form-select form-select-sm">
              <option value="false">Não</option>
              <option value="true">Sim</option>
            </select>
          </div>
        </div>
      </div>
      <div class="modal-footer">
        <button class="btn btn-secondary" data-bs-dismiss="modal">Cancelar</button>
        <button class="btn btn-primary" onclick="salvarConta()">Salvar</button>
      </div>
    </div>
  </div>
</div>
<script>
let _mc;
document.addEventListener('DOMContentLoaded', () => { _mc = new bootstrap.Modal(document.getElementById('modalConta')); });
function novaConta(pid) {
  document.getElementById('modalContaTitulo').textContent = pid ? 'Nova Sub-conta' : 'Nova Conta';
  document.getElementById('cId').value = '';
  document.getElementById('cParentId').value = pid || '';
  document.getElementById('cCode').value = '';
  document.getElementById('cName').value = '';
  document.getElementById('cType').value = 'despesa';
  document.getElementById('cSign').value = '1';
  document.getElementById('cTot').value = 'false';
  const info = document.getElementById('cParentInfo');
  if (pid) {
    const row = document.querySelector('[data-id="' + pid + '"]');
    info.textContent = 'Sub-conta de: ' + (row ? row.querySelector('td:nth-child(2)').textContent.trim() : '#' + pid);
    info.style.display = '';
  } else { info.style.display = 'none'; }
  _mc.show();
}
function editarConta(id, code, name, type, isTot, sign) {
  document.getElementById('modalContaTitulo').textContent = 'Editar Conta';
  document.getElementById('cId').value = id;
  document.getElementById('cParentId').value = '';
  document.getElementById('cCode').value = code;
  document.getElementById('cName').value = name;
  document.getElementById('cType').value = type;
  document.getElementById('cSign').value = String(sign);
  document.getElementById('cTot').value = isTot ? 'true' : 'false';
  document.getElementById('cParentInfo').style.display = 'none';
  _mc.show();
}
async function salvarConta() {
  const id = document.getElementById('cId').value;
  const payload = {
    code: document.getElementById('cCode').value,
    name: document.getElementById('cName').value,
    account_type: document.getElementById('cType').value,
    sign: parseInt(document.getElementById('cSign').value),
    is_totalizer: document.getElementById('cTot').value === 'true',
    parent_id: document.getElementById('cParentId').value || null,
  };
  const url = id ? '/api/orcamento/conta/' + id + '/editar' : '/api/orcamento/conta/criar';
  const r = await fetch(url, {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(payload)});
  const d = await r.json();
  if (d.ok) { _mc.hide(); location.reload(); } else alert('Erro ao salvar.');
}
async function deletarConta(id, name) {
  if (!confirm('Remover conta "' + name + '"?')) return;
  await fetch('/api/orcamento/conta/' + id + '/deletar', {method:'POST'});
  location.reload();
}
async function importarModelo() {
  if (!confirm('Importar o modelo padrão de plano de contas (DRE completo)?\n\nIsso só funciona com o plano vazio. Você poderá editar, renomear ou remover contas depois.')) return;
  var btn = document.getElementById('btnModelo');
  if (btn) { btn.disabled = true; btn.textContent = 'Importando...'; }
  var r = await fetch('/api/orcamento/conta/importar-modelo', {method:'POST'});
  var d = await r.json();
  if (d.ok) { location.reload(); }
  else { alert(d.msg || 'Erro ao importar.'); if (btn) { btn.disabled = false; btn.textContent = '📥 Usar modelo padrão'; } }
}
</script>
{% endblock %}
"""

TEMPLATES["orcamento_grid.html"] = r"""
{% extends "base.html" %}
{% block content %}
<style>
.orc-grid{font-size:.78rem;border-collapse:collapse;width:100%;min-width:1400px;}
.orc-grid th,.orc-grid td{border:1px solid #dee2e6;padding:2px 6px;white-space:nowrap;}
.orc-grid thead th{background:#f8f9fa;text-align:center;font-weight:600;}
.orc-grid .col-name{text-align:left!important;min-width:200px;}
.orc-totalizer{background:#e8f0fe!important;font-weight:700;}
.orc-totalizer td{background:#e8f0fe!important;}
.orc-depth-0 .col-name{padding-left:4px!important;font-weight:700;font-size:.8rem;}
.orc-depth-1 .col-name{padding-left:18px!important;}
.orc-depth-2 .col-name{padding-left:34px!important;}
.orc-depth-3 .col-name{padding-left:50px!important;}
.orc-val{text-align:right!important;min-width:76px;}
.orc-val input{width:72px;border:none;background:transparent;text-align:right;font-size:.78rem;padding:0;}
.orc-val input:focus{background:#fff3cd;outline:none;border-bottom:1px solid #ffc107;}
.orc-realizado{background:#f0fff0!important;}
.orc-var-neg{color:#dc3545;font-weight:600;}
.orc-var-pos{color:#198754;font-weight:600;}
.orc-total-col{background:#f0f5ff!important;font-weight:600;}
</style>

<div class="d-flex justify-content-between align-items-center mb-2 flex-wrap gap-2">
  <div>
    <h5 class="mb-0">{{ plan.name }}</h5>
    <div class="muted small">
      {% if current_client %}<strong>{{ current_client.name }}</strong> · {% endif %}
      Clique em qualquer célula para editar · <span style="color:#198754;">■</span> Realizado · <span style="color:#3b5bdb;">■</span> Totalizadora
    </div>
  </div>
  <div class="d-flex gap-2 flex-wrap">
    <a href="/ferramentas/orcamento" class="btn btn-outline-secondary btn-sm">← Planos</a>
    <a href="/ferramentas/orcamento/contas" class="btn btn-outline-secondary btn-sm">
      <i class="bi bi-list-ul me-1"></i>Plano de Contas
    </a>
    <a href="/ferramentas/orcamento/importar" class="btn btn-outline-success btn-sm">
      <i class="bi bi-file-earmark-arrow-up me-1"></i>Importar Realizado
    </a>
    <button class="btn btn-outline-primary btn-sm" onclick="augurAnalisar()">
      <i class="bi bi-robot me-1"></i>Augur Analisar
    </button>
  </div>
</div>

<div id="augurBox" class="card p-3 mb-2" style="display:none;">
  <div class="d-flex justify-content-between align-items-center mb-2">
    <div class="fw-semibold"><i class="bi bi-robot me-1"></i>Análise Augur</div>
    <button class="btn btn-sm btn-outline-secondary" onclick="document.getElementById('augurBox').style.display='none'">✕</button>
  </div>
  <div id="augurText" class="muted small" style="white-space:pre-wrap;"></div>
</div>

<div style="overflow-x:auto;">
<table class="orc-grid">
  <thead>
    <tr>
      <th class="col-name">Conta</th>
      {% for m in months %}
      <th colspan="3" style="min-width:220px;">{{ m }}</th>
      {% endfor %}
      <th colspan="3" class="orc-total-col" style="min-width:220px;">Total Ano</th>
    </tr>
    <tr>
      <th class="col-name"></th>
      {% for m in months %}
      <th class="orc-val">Orçado</th>
      <th class="orc-val orc-realizado">Realizado</th>
      <th class="orc-val">Var%</th>
      {% endfor %}
      <th class="orc-val orc-total-col">Orçado</th>
      <th class="orc-val orc-total-col orc-realizado">Realizado</th>
      <th class="orc-val orc-total-col">Var%</th>
    </tr>
  </thead>
  <tbody>
    {% for row in rows %}
    <tr class="{% if row.is_totalizer %}orc-totalizer{% endif %} orc-depth-{{ row.depth }}">
      <td class="col-name">
        {% if row.is_totalizer %}<i class="bi bi-calculator me-1 text-primary" style="font-size:.7rem;"></i>{% endif %}
        <span class="text-muted" style="font-size:.68rem;">{{ row.code }}</span> {{ row.name }}
      </td>
      {% for m in range(1, 13) %}
      {% set mv = row.months[m] %}
      <td class="orc-val">
        {% if row.is_totalizer %}<span>{{ "%.0f"|format(mv.b) }}</span>
        {% else %}<input type="number" step="0.01"
          data-plan="{{ plan.id }}" data-acc="{{ row.id }}"
          data-month="{{ m }}" data-field="b"
          value="{{ mv.b if mv.b != 0 else '' }}"
          onblur="saveEntry(this)" onkeydown="if(event.key==='Enter'||event.key==='Tab'){this.blur();}">
        {% endif %}
      </td>
      <td class="orc-val orc-realizado">
        {% if row.is_totalizer %}<span>{{ "%.0f"|format(mv.r) }}</span>
        {% else %}<input type="number" step="0.01"
          data-plan="{{ plan.id }}" data-acc="{{ row.id }}"
          data-month="{{ m }}" data-field="r"
          value="{{ mv.r if mv.r != 0 else '' }}"
          onblur="saveEntry(this)" onkeydown="if(event.key==='Enter'||event.key==='Tab'){this.blur();}">
        {% endif %}
      </td>
      <td class="orc-val {% if mv.b and mv.r < mv.b %}orc-var-neg{% elif mv.b and mv.r >= mv.b %}orc-var-pos{% endif %}">
        {% if mv.b %}{{ "%+.0f%%"|format((mv.r - mv.b) / mv.b * 100) }}{% else %}—{% endif %}
      </td>
      {% endfor %}
      <td class="orc-val orc-total-col">{{ "%.0f"|format(row.total_b) }}</td>
      <td class="orc-val orc-total-col orc-realizado">{{ "%.0f"|format(row.total_r) }}</td>
      <td class="orc-val orc-total-col {% if row.total_b and row.total_r < row.total_b %}orc-var-neg{% elif row.total_b and row.total_r >= row.total_b %}orc-var-pos{% endif %}">
        {% if row.total_b %}{{ "%+.0f%%"|format((row.total_r - row.total_b) / row.total_b * 100) }}{% else %}—{% endif %}
      </td>
    </tr>
    {% endfor %}
    {% if not rows %}
    <tr><td colspan="42" class="text-center muted py-4">
      Nenhuma conta no plano de contas.
      <a href="/ferramentas/orcamento/contas">Configurar plano de contas →</a>
    </td></tr>
    {% endif %}
  </tbody>
</table>
</div>

<script>
async function saveEntry(input) {
  const val = parseFloat(input.value) || 0;
  if (String(val) === String(input.dataset.prev)) return;
  input.dataset.prev = val;
  const r = await fetch('/api/orcamento/entry', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({
      plan_id: input.dataset.plan, account_id: input.dataset.acc,
      month: input.dataset.month, field: input.dataset.field, value: val,
    })
  });
  const d = await r.json();
  if (d.ok) { input.style.background='#d1fae5'; setTimeout(()=>input.style.background='transparent',800); }
}
document.querySelectorAll('.orc-val input').forEach(i => { i.dataset.prev = i.value; });

async function augurAnalisar() {
  const box = document.getElementById('augurBox');
  const txt = document.getElementById('augurText');
  box.style.display = ''; txt.textContent = 'Carregando dados...';
  const r = await fetch('/api/orcamento/{{ plan.id }}/augur-contexto');
  const d = await r.json();
  if (!d.ok) { txt.textContent = 'Erro ao carregar.'; return; }
  let resumo = `Orçamento: ${d.plan} (${d.year})\n\n`;
  for (const row of d.rows) {
    const tag = row.is_totalizer ? '[TOTAL] ' : '';
    const vp = row.total_b ? ((row.total_r - row.total_b)/row.total_b*100).toFixed(1)+'%' : '—';
    resumo += `${'  '.repeat(row.depth)}${tag}${row.code} ${row.name}: Orç R$${row.total_b.toFixed(0)} | Real R$${row.total_r.toFixed(0)} | Var ${vp}\n`;
  }
  txt.textContent = 'Enviando para o Augur...';
  try {
    const resp = await fetch('/api/augur/quick-analysis', {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({prompt:`Analise o orçamento e destaque:\n1. Contas com maior variação negativa\n2. Pontos de atenção\n3. Recomendações\n\n${resumo}`})
    });
    const rd = await resp.json();
    txt.textContent = rd.answer || rd.text || resumo;
  } catch(e) { txt.textContent = resumo; }
}
</script>
{% endblock %}
"""

if hasattr(templates_env.loader, "mapping"):
    for _tpl in ("orcamento_index.html", "orcamento_contas.html", "orcamento_grid.html"):
        templates_env.loader.mapping[_tpl] = TEMPLATES[_tpl]

# ── Feature registration ───────────────────────────────────────────────────────

FEATURE_KEYS["orcamento"] = {
    "title": "Orçamento",
    "desc":  "Planejamento orçamentário com plano de contas e acompanhamento mensal.",
    "href":  "/ferramentas/orcamento",
}
FEATURE_VISIBLE_ROLES["orcamento"] = {"admin", "equipe", "cliente"}

# Adiciona ao grupo "Ferramentas e Conteúdo"
try:
    _orc_group = next((g for g in FEATURE_GROUPS if g.get("key") == "ferramentas_conteudo"), None)
    if _orc_group and "orcamento" not in _orc_group.get("features", []):
        _orc_group["features"].append("orcamento")
except Exception:
    pass

for _role in ("admin", "equipe", "cliente"):
    ROLE_DEFAULT_FEATURES.setdefault(_role, set()).add("orcamento")

print("[orcamento] ✅ Ferramenta /ferramentas/orcamento carregada")

# ── Registra no catálogo de features (fonte do /api/features/status) ──────────
# _CF_CATALOGO é definido em ui_creditos_features.py e exec'd no mesmo namespace.
# Esse registro faz o card aparecer dinamicamente na página /ferramentas.
try:
    if "orcamento_mensal" not in _CF_CATALOGO:
        _CF_CATALOGO["orcamento_mensal"] = {
            "nome":      "Orçamento",
            "descricao": "Planejamento orçamentário com plano de contas, Orçado vs Realizado.",
            "nivel":     "empresa",
            "url":       "/ferramentas/orcamento",
            "icone":     "📋",
        }
        print("[orcamento] ✅ orcamento_mensal adicionado ao _CF_CATALOGO")
    else:
        print("[orcamento] ℹ️ orcamento_mensal já presente em _CF_CATALOGO")
except Exception as _e:
    print(f"[orcamento] ⚠️ Falha ao registrar em _CF_CATALOGO: {_e}")

exec(open('ui_orcamento_import.py').read())
exec(open('ui_ferramenta_bsc.py').read())

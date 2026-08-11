# ============================================================================
# ui_dashboard_gestao.py — Reorganiza dashboard: cards Gestão + Reuniões
# ============================================================================
# Adiciona ao FEATURE_GROUPS:
#   "gestao_cliente"  → BSC, Orçamento, Central de Ações, Segundo Cérebro
#   "reunioes_grupo"  → Reuniões (com href correto por role)
#
# Também:
#   - Atualiza desc da feature "reunioes" (remove menção ao Notion)
#   - Ajusta href das features para versão /cliente/ quando role==cliente
# ============================================================================

# ── 1. Atualiza features existentes ──────────────────────────────────────────

FEATURE_KEYS["reunioes"] = {
    "title": "📅 Reuniões",
    "desc": "Atas, gravações e ações corretivas das reuniões.",
    "href": "/reunioes",  # admin/equipe
}
FEATURE_KEYS["reunioes_cliente"] = {
    "title": "📅 Reuniões",
    "desc": "Atas e ações das reuniões em que você participa.",
    "href": "/cliente/reunioes",
}
FEATURE_VISIBLE_ROLES["reunioes_cliente"] = {"cliente"}
ROLE_DEFAULT_FEATURES.setdefault("cliente", set()).add("reunioes_cliente")

# BSC para o cliente
FEATURE_KEYS["bsc_cliente"] = {
    "title": "📊 BSC — Planejamento Estratégico",
    "desc": "Acompanhe os indicadores e objetivos estratégicos da empresa.",
    "href": "/cliente/bsc",
}
FEATURE_VISIBLE_ROLES["bsc_cliente"] = {"cliente"}
ROLE_DEFAULT_FEATURES.setdefault("cliente", set()).add("bsc_cliente")

# Orçamento — o href já existe via financeiro/orcamento; criamos alias para gestão
FEATURE_KEYS["orcamento_gestao"] = {
    "title": "💰 Orçamento / DRE",
    "desc": "Receitas, despesas e execução orçamentária da empresa.",
    "href": "/ferramentas/orcamento",
}
FEATURE_VISIBLE_ROLES["orcamento_gestao"] = {"admin", "equipe", "cliente"}
ROLE_DEFAULT_FEATURES.setdefault("admin", set()).add("orcamento_gestao")
ROLE_DEFAULT_FEATURES.setdefault("equipe", set()).add("orcamento_gestao")
ROLE_DEFAULT_FEATURES.setdefault("cliente", set()).add("orcamento_gestao")

# Central de Ações para cliente (gestor vê tudo, usuario vê as suas)
FEATURE_KEYS["acoes_cliente"] = {
    "title": "⚡ Central de Ações",
    "desc": "Ações corretivas abertas e em andamento.",
    "href": "/admin/acoes",   # gestor do cliente acessa a central filtrada
}
FEATURE_VISIBLE_ROLES["acoes_cliente"] = {"cliente"}
ROLE_DEFAULT_FEATURES.setdefault("cliente", set()).add("acoes_cliente")

# ── 2. Adiciona grupo "Gestão" e "Reuniões" ao FEATURE_GROUPS ────────────────

# Remove grupos antigos que serão substituídos para evitar duplicatas
FEATURE_GROUPS[:] = [
    g for g in FEATURE_GROUPS
    if g.get("key") not in ("gestao_cliente_grupo", "gestao_staff_grupo", "reunioes_grupo")
]

# Insere "Gestão" logo após "Meu Projeto" (ou no final se não existir)
_idx_meu_proj = next(
    (i for i, g in enumerate(FEATURE_GROUPS) if g.get("key") == "meu_projeto"),
    len(FEATURE_GROUPS),
)

# Grupo para staff (admin/equipe) — sem features exclusivas de cliente
FEATURE_GROUPS.insert(_idx_meu_proj + 1, {
    "key": "gestao_staff_grupo",
    "title": "Gestão",
    "features": ["bsc", "orcamento_gestao", "acoes_central", "grafo", "reunioes"],
})

# Grupo para cliente — sem features exclusivas de staff (sem duplicatas de título)
FEATURE_GROUPS.insert(_idx_meu_proj + 2, {
    "key": "gestao_cliente_grupo",
    "title": "Acesso Cliente",
    "features": ["bsc_cliente", "orcamento_gestao", "acoes_cliente", "reunioes_cliente"],
})

# ── 3. Garante visibilidade do BSC (admin/equipe) para o grupo ───────────────

FEATURE_VISIBLE_ROLES.setdefault("bsc", set()).update({"admin", "equipe"})
FEATURE_VISIBLE_ROLES.setdefault("grafo", set()).update({"admin", "equipe"})
FEATURE_VISIBLE_ROLES.setdefault("acoes_central", set()).update({"admin", "equipe"})
FEATURE_VISIBLE_ROLES.setdefault("orcamento_gestao", set()).update({"admin", "equipe", "cliente"})

# ── 4. Remove "reunioes" do grupo "Meu Projeto" para não duplicar ────────────

for _g in FEATURE_GROUPS:
    if _g.get("key") == "meu_projeto":
        _g["features"] = [f for f in _g.get("features", []) if f not in ("reunioes", "reunioes_cliente")]
        break

# ── 5. Remove "bsc" do grupo "ferramentas_conteudo" para não duplicar ────────

for _g in FEATURE_GROUPS:
    if _g.get("key") == "ferramentas_conteudo":
        _g["features"] = [f for f in _g.get("features", []) if f not in ("bsc", "bsc_cliente")]
        break

print("[dashboard_gestao] ✅ Cards 'Gestão' e 'Reuniões' registrados no dashboard.")

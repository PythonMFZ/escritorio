# ============================================================================
# PATCH — Simplifica abas do dashboard
# Remove abas que já estão na sidebar lateral (evita duplicação):
#   - "Compliance e Análise de Risco" → itens já acessíveis via /consultas
#   - "Meu Projeto"                   → Tarefas/Consultoria/Reuniões já na sidebar
#   - "Gestão" (staff)                → BSC/Orçamento/Ações já na sidebar
#   - "Acesso Cliente" (cliente)      → BSC/Reuniões já na sidebar do cliente
# Mantém: Minha Empresa, Diagnóstico, Soluções, Ferramentas e Conteúdo,
#          Gestão Interna (somente admin/equipe já filtrado por visibility)
# Adiciona "educacao" ao Acesso Rápido (FEATURE_STANDALONE)
# ============================================================================

_REMOVE_KEYS = {
    "compliance_risco",    # itens já na sidebar via /consultas
    "meu_projeto",         # Tarefas/Consultoria/Reuniões já na sidebar
    "gestao_staff_grupo",  # BSC/Orçamento/Ações já na sidebar (adicionado por ui_dashboard_gestao)
    "gestao_cliente_grupo",# BSC/Reuniões já na sidebar do cliente
}

FEATURE_GROUPS[:] = [g for g in FEATURE_GROUPS if g.get("key") not in _REMOVE_KEYS]

# Educação no Acesso Rápido
if "educacao" not in FEATURE_STANDALONE:
    FEATURE_STANDALONE.append("educacao")

# Ocultar barra de abas do dashboard (conteúdo migrado para a sidebar)
# Usa contagem de profundidade para encontrar o {% endif %} correto que
# fecha o bloco {% if tabs %}, ignorando {% if %} aninhados dentro dele.

def _remove_tabs_block(tpl: str) -> str:
    marker = "{% if tabs %}"
    start = tpl.find(marker)
    if start == -1:
        return tpl

    depth = 1
    pos = start + len(marker)
    while pos < len(tpl) and depth > 0:
        next_if    = tpl.find("{%", pos)
        if next_if == -1:
            break
        tag_end = tpl.find("%}", next_if)
        if tag_end == -1:
            break
        tag_body = tpl[next_if + 2 : tag_end].strip()
        if tag_body.startswith("if ") or tag_body == "if":
            depth += 1
        elif tag_body == "endif":
            depth -= 1
            if depth == 0:
                end = tag_end + 2  # after "%}"
                return tpl[:start] + tpl[end:]
        pos = tag_end + 2

    return tpl  # não encontrou o fechamento, não altera

_dash_tpl = TEMPLATES.get("dashboard.html", "")
if _dash_tpl and "{% if tabs %}" in _dash_tpl:
    _dash_tpl = _remove_tabs_block(_dash_tpl)
    TEMPLATES["dashboard.html"] = _dash_tpl
    if hasattr(templates_env.loader, "mapping"):
        templates_env.loader.mapping["dashboard.html"] = _dash_tpl
    print("[dashboard_simplify] ✅ Barra de abas removida do dashboard")

print(f"[dashboard_simplify] ✅ Abas mantidas (permissões): {[g['key'] for g in FEATURE_GROUPS]}")
print(f"[dashboard_simplify] ✅ Acesso rápido: {FEATURE_STANDALONE}")

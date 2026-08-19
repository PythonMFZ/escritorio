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
_TAB_OPEN  = "{% if tabs %}"
_TAB_CLOSE = "{% endif %}"

def _remove_tabs_block(tpl: str) -> str:
    start = tpl.find(_TAB_OPEN)
    if start == -1:
        return tpl
    end = tpl.find(_TAB_CLOSE, start)
    if end == -1:
        return tpl
    end += len(_TAB_CLOSE)
    return tpl[:start] + tpl[end:]

_dash_tpl = TEMPLATES.get("dashboard.html", "")
if _dash_tpl and _TAB_OPEN in _dash_tpl:
    _dash_tpl = _remove_tabs_block(_dash_tpl)
    TEMPLATES["dashboard.html"] = _dash_tpl
    if hasattr(templates_env.loader, "mapping"):
        templates_env.loader.mapping["dashboard.html"] = _dash_tpl
    print("[dashboard_simplify] ✅ Barra de abas removida do dashboard")

print(f"[dashboard_simplify] ✅ Abas mantidas (permissões): {[g['key'] for g in FEATURE_GROUPS]}")
print(f"[dashboard_simplify] ✅ Acesso rápido: {FEATURE_STANDALONE}")

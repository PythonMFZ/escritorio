# ============================================================================
# PATCH — Simplifica abas do dashboard
# Remove abas já presentes na sidebar lateral:
#   - "Compliance e Análise de Risco" → /consultas já na sidebar
#   - "Meu Projeto"                   → Tarefas/Consultoria já na sidebar
#   - "Minha Empresa"                 → já na sidebar
#   - "Diagnóstico Financeiro"        → já na sidebar
#   - "Soluções Financeiras"          → já na sidebar
#   - "Ferramentas e Conteúdo"        → já na sidebar
#   - "Gestão" (staff/cliente)        → BSC/Orçamento/Ações já na sidebar
# Mantém APENAS: "Gestão Interna" (cards de Produtos, Monetização, etc.)
# Adiciona "educacao" ao Acesso Rápido (FEATURE_STANDALONE)
# ============================================================================

_REMOVE_KEYS = {
    "minha_empresa",        # já na sidebar
    "diagnostico",          # já na sidebar
    "compliance_risco",     # já na sidebar via /consultas
    "solucoes",             # já na sidebar
    "ferramentas_conteudo", # já na sidebar
    "meu_projeto",          # Tarefas/Consultoria já na sidebar
    "gestao_staff_grupo",   # BSC/Orçamento/Ações já na sidebar
    "gestao_cliente_grupo", # BSC/Reuniões já na sidebar do cliente
}

FEATURE_GROUPS[:] = [g for g in FEATURE_GROUPS if g.get("key") not in _REMOVE_KEYS]

# Educação no Acesso Rápido
if "educacao" not in FEATURE_STANDALONE:
    FEATURE_STANDALONE.append("educacao")

print(f"[dashboard_simplify] ✅ Abas no dashboard: {[g['key'] for g in FEATURE_GROUPS]}")
print(f"[dashboard_simplify] ✅ Acesso rápido: {FEATURE_STANDALONE}")

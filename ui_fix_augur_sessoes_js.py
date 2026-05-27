# ============================================================================
# PATCH — Fix JS Augur v4: sessões não desaparecem
# ============================================================================
# Problema: augurCarregarSessoes() após envio de mensagem substituía
# o chat atual pela primeira sessão da lista (race condition).
# Solução: separar "atualizar lista" de "carregar sessão".
# DEPLOY: adicione ao final do app.py (após ui_augur_sessoes_base.py)
# ============================================================================

_AUGUR_JS_FIX = r"""
<!-- augur_fix: superseded by ui_fixes_batch6.py — no override needed -->
"""

# Injeta no dashboard
_dash_fix = TEMPLATES.get("dashboard.html", "")
if _dash_fix and "augur_fix" not in _dash_fix:
    if "{% endblock %}" in _dash_fix:
        _dash_fix = _dash_fix.replace("{% endblock %}", _AUGUR_JS_FIX + "\n{% endblock %}", 1)
        TEMPLATES["dashboard.html"] = _dash_fix
        print("[fix_augur_sessoes_js] ✅ Fix JS injetado no dashboard")

if hasattr(templates_env.loader, "mapping"):
    templates_env.loader.mapping = TEMPLATES

print("[fix_augur_sessoes_js] ✅ Patch completo")

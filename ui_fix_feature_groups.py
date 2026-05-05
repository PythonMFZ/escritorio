# ============================================================================
# PATCH — Fix FEATURE_GROUPS: adiciona obras_horas ao grupo ferramentas
# ============================================================================
# Problema: obras_horas e construrisk não estão no FEATURE_GROUPS correto,
# então não aparecem como checkbox na tela de permissões de membros/clientes.
#
# DEPLOY: adicione ao final do app.py (após ui_fix_obras_horas_access.py)
# ============================================================================

# ── Garante obras_horas no FEATURE_KEYS ──────────────────────────────────────
FEATURE_KEYS.setdefault("obras_horas", {
    "title": "Obras + Horas",
    "desc": "Controle de obras, funcionários e horas previstas x realizadas.",
    "href": "/obras-horas",
})
FEATURE_KEYS.setdefault("construrisk", {
    "title": "ConstruRisk",
    "desc": "Dossiê PF/PJ via DirectData.",
    "href": "/construrisk",
})
FEATURE_KEYS.setdefault("gestao_obras", {
    "title": "Gestão de Obras",
    "desc": "Cronograma físico-financeiro.",
    "href": "/ferramentas/obras",
})

# ── Adiciona obras_horas e gestao_obras ao grupo ferramentas_conteudo ────────
_fg_map = {g.get("key"): g for g in FEATURE_GROUPS}

# Grupo ferramentas_conteudo — adiciona obras_horas e gestao_obras
if "ferramentas_conteudo" in _fg_map:
    _feats = _fg_map["ferramentas_conteudo"]["features"]
    for _fk in ("ferramentas", "educacao", "construrisk", "gestao_obras", "obras_horas"):
        if _fk not in _feats:
            _feats.append(_fk)
else:
    FEATURE_GROUPS.append({
        "key": "ferramentas_conteudo",
        "title": "Ferramentas e Conteúdo",
        "features": ["ferramentas", "educacao", "construrisk", "gestao_obras", "obras_horas"],
    })

# ── Adiciona obras_horas ao ROLE_DEFAULT_FEATURES cliente ────────────────────
ROLE_DEFAULT_FEATURES.setdefault("cliente", set()).add("obras_horas")
ROLE_DEFAULT_FEATURES.setdefault("admin", set()).update({"obras_horas", "gestao_obras", "construrisk"})
ROLE_DEFAULT_FEATURES.setdefault("equipe", set()).update({"obras_horas", "gestao_obras", "construrisk"})

# ── FEATURE_VISIBLE_ROLES ────────────────────────────────────────────────────
FEATURE_VISIBLE_ROLES.setdefault("obras_horas", {"admin", "equipe", "cliente"})
FEATURE_VISIBLE_ROLES.setdefault("gestao_obras", {"admin", "equipe"})
FEATURE_VISIBLE_ROLES.setdefault("construrisk", {"admin", "equipe", "cliente"})

print(f"[fix_feature_groups] ✅ obras_horas adicionado ao grupo ferramentas_conteudo")
print(f"[fix_feature_groups] FEATURE_GROUPS: {[g['key'] for g in FEATURE_GROUPS]}")

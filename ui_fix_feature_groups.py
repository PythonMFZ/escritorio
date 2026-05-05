# ============================================================================
# PATCH — Fix FEATURE_GROUPS + Permissões Equipe
# ============================================================================
# Corrige dois problemas:
# 1. obras_horas/construrisk não apareciam como checkbox nas permissões
# 2. Equipe não conseguia acessar parceiros/servicos_internos/familias
#    mesmo após admin liberar — porque ROLE_DEFAULT_FEATURES os excluía
#    explicitamente, e get_membership_allowed_features usa o default quando
#    não há registro no banco, ignorando o que foi salvo.
#
# DEPLOY: adicione ao final do app.py (após ui_fix_obras_horas_access.py)
# ============================================================================

# ── 1. Garante features no FEATURE_KEYS ──────────────────────────────────────
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

# ── 2. Corrige FEATURE_GROUPS ─────────────────────────────────────────────────
_fg_map = {g.get("key"): g for g in FEATURE_GROUPS}

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

# Garante parceiros/servicos_internos/familias no grupo gestao_interna
_fg_map2 = {g.get("key"): g for g in FEATURE_GROUPS}
if "gestao_interna" in _fg_map2:
    _gi = _fg_map2["gestao_interna"]["features"]
    for _fk in ("familias", "servicos_internos", "parceiros"):
        if _fk not in _gi:
            _gi.append(_fk)

# ── 3. Corrige ROLE_DEFAULT_FEATURES ─────────────────────────────────────────
# Admin tem tudo
ROLE_DEFAULT_FEATURES.setdefault("admin", set()).update({
    "obras_horas", "gestao_obras", "construrisk",
    "familias", "servicos_internos", "parceiros",
})

# Equipe tem obras/construrisk mas NÃO familias/servicos/parceiros por padrão
# (admin pode liberar individualmente via tela de permissões)
ROLE_DEFAULT_FEATURES.setdefault("equipe", set()).update({
    "obras_horas", "gestao_obras", "construrisk",
})
# Remove exclusão explícita para que o registro salvo no banco seja respeitado
for _fk in ("familias", "servicos_internos", "parceiros"):
    ROLE_DEFAULT_FEATURES["equipe"].discard(_fk)

# Cliente tem obras_horas
ROLE_DEFAULT_FEATURES.setdefault("cliente", set()).add("obras_horas")

# ── 4. Corrige FEATURE_VISIBLE_ROLES ─────────────────────────────────────────
FEATURE_VISIBLE_ROLES.setdefault("obras_horas", {"admin", "equipe", "cliente"})
FEATURE_VISIBLE_ROLES.setdefault("gestao_obras", {"admin", "equipe"})
FEATURE_VISIBLE_ROLES.setdefault("construrisk", {"admin", "equipe", "cliente"})
FEATURE_VISIBLE_ROLES["familias"] = {"admin", "equipe"}
FEATURE_VISIBLE_ROLES["servicos_internos"] = {"admin", "equipe"}
FEATURE_VISIBLE_ROLES["parceiros"] = {"admin", "equipe"}

# ── 5. Corrige get_membership_allowed_features para respeitar banco ───────────
# Quando há registro salvo no banco, usa ele. Quando não há, usa o default.
# O problema era que o default da equipe excluía familias/servicos/parceiros
# mesmo quando o admin havia salvado explicitamente essas permissões.
# O fix acima no ROLE_DEFAULT_FEATURES + a lógica existente já resolve:
# se há features_json salvo, ele é usado integralmente (linha 12021-12023).

print("[fix_feature_groups] ✅ FEATURE_GROUPS corrigido com obras_horas/construrisk")
print("[fix_feature_groups] ✅ ROLE_DEFAULT_FEATURES equipe corrigido")
print(f"[fix_feature_groups] Grupos: {[g['key'] for g in FEATURE_GROUPS]}")
print(f"[fix_feature_groups] Equipe default: {sorted(ROLE_DEFAULT_FEATURES.get('equipe', set()))}")

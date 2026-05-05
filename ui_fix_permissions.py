# ============================================================================
# PATCH — Fix Permissões de Features
# ============================================================================
# Problema: features como obras_horas, parceiros, servicos_internos, familias
# são adicionadas ao FEATURE_KEYS DEPOIS das rotas que salvam permissões.
# Isso faz o filtro `if str(x) in FEATURE_KEYS` descartar essas features
# silenciosamente na hora de salvar.
#
# Solução: garante que todas as features conhecidas estão no FEATURE_KEYS
# e redefine as rotas de salvamento para usar uma versão expandida do filtro.
#
# DEPLOY: adicione ao final do app.py (após todos os outros patches)
# ============================================================================

import json as _json_fp
from fastapi import Request as _Request, Depends as _Depends
from fastapi.responses import RedirectResponse as _RedirectResponse
from sqlmodel import Session as _Session, select as _select

# ── Garante que todas as features estão registradas ──────────────────────────

_FEATURES_EXTRAS = {
    "obras_horas": {
        "title": "Obras + Horas",
        "desc": "Controle de obras, funcionários e horas.",
        "href": "/obras-horas",
    },
    "parceiros": {
        "title": "Parceiros",
        "desc": "Parceiros, produtos e campanhas.",
        "href": "/admin/parceiros",
    },
    "servicos_internos": {
        "title": "Produtos Internos",
        "desc": "Catálogo interno por área e família.",
        "href": "/admin/servicos-internos",
    },
    "familias": {
        "title": "Famílias",
        "desc": "Famílias canônicas de produto.",
        "href": "/admin/familias",
    },
    "gestao_obras": {
        "title": "Gestão de Obras",
        "desc": "Cronograma físico-financeiro.",
        "href": "/ferramentas/obras",
    },
    "motor_ofertas": {
        "title": "Motor de Ofertas",
        "desc": "Ranking de ofertas internas e de parceiros.",
        "href": "/motor-ofertas",
    },
    "ofertas": {
        "title": "Ofertas",
        "desc": "Produtos e serviços aderentes ao perfil.",
        "href": "/ofertas",
    },
    "openfinance": {
        "title": "Open Finance",
        "desc": "Contratos de crédito (Klavi).",
        "href": "/openfinance",
    },
}

for _fk, _fv in _FEATURES_EXTRAS.items():
    FEATURE_KEYS.setdefault(_fk, _fv)

# Garante roles padrão para as features extras
for _fk in ("obras_horas", "gestao_obras"):
    FEATURE_VISIBLE_ROLES.setdefault(_fk, {"admin", "equipe", "cliente"})
    for _r in ("admin", "equipe", "cliente"):
        ROLE_DEFAULT_FEATURES.setdefault(_r, set()).add(_fk)

for _fk in ("parceiros", "servicos_internos", "familias", "motor_ofertas"):
    FEATURE_VISIBLE_ROLES.setdefault(_fk, {"admin", "equipe"})
    for _r in ("admin", "equipe"):
        ROLE_DEFAULT_FEATURES.setdefault(_r, set()).add(_fk)

print(f"[fix_permissions] FEATURE_KEYS agora tem {len(FEATURE_KEYS)} features: {sorted(FEATURE_KEYS.keys())}")


# ── Redefine rota de salvamento de permissões de MEMBRO ──────────────────────

@app.post("/admin/members/{membership_id}/features")
@require_role({"admin", "equipe"})
async def member_features_save_fixed(
    membership_id: int,
    request: _Request,
    session: _Session = _Depends(get_session),
):
    ctx = get_tenant_context(request, session)
    assert ctx is not None

    m = session.get(Membership, membership_id)
    if not m or m.company_id != ctx.company.id:
        set_flash(request, "Membro não encontrado.")
        return _RedirectResponse("/admin/members", status_code=303)

    form = await request.form()
    # ← FIX: usa FEATURE_KEYS atualizado (inclui obras_horas, parceiros, etc)
    features = [str(x) for x in form.getlist("features") if str(x) in FEATURE_KEYS]

    row = session.exec(
        _select(MembershipFeatureAccess).where(
            MembershipFeatureAccess.company_id == ctx.company.id,
            MembershipFeatureAccess.membership_id == membership_id,
        )
    ).first()
    if not row:
        row = MembershipFeatureAccess(company_id=ctx.company.id, membership_id=membership_id)

    row.features_json = _json_fp.dumps(sorted(set(features)))
    row.updated_at = utcnow()
    session.add(row)
    session.commit()

    set_flash(request, "Permissões atualizadas.")
    return _RedirectResponse("/admin/members", status_code=303)


# ── Redefine rota de salvamento de permissões de CLIENTE ─────────────────────

@app.post("/admin/clients/{client_id}/access")
@require_role({"admin", "equipe"})
async def client_access_save_fixed(
    client_id: int,
    request: _Request,
    session: _Session = _Depends(get_session),
):
    ctx = get_tenant_context(request, session)
    assert ctx is not None

    c = session.get(Client, client_id)
    if not c or c.company_id != ctx.company.id:
        set_flash(request, "Cliente não encontrado.")
        return _RedirectResponse("/admin/gestao", status_code=303)

    form = await request.form()
    # ← FIX: usa FEATURE_KEYS atualizado
    features = [str(x) for x in form.getlist("features") if str(x) in FEATURE_KEYS]
    stored_features = set(features)

    # Lógica especial obras_horas — usa prefixo __disabled__ para desabilitar
    if "obras_horas" not in stored_features:
        stored_features.add(f"{CLIENT_FEATURE_DISABLE_PREFIX}obras_horas")
    else:
        stored_features.discard(f"{CLIENT_FEATURE_DISABLE_PREFIX}obras_horas")

    row = session.exec(
        _select(ClientFeatureAccess).where(
            ClientFeatureAccess.company_id == ctx.company.id,
            ClientFeatureAccess.client_id == client_id,
        )
    ).first()
    if not row:
        row = ClientFeatureAccess(company_id=ctx.company.id, client_id=client_id)

    row.features_json = _json_fp.dumps(sorted(stored_features))
    row.updated_at = utcnow()
    session.add(row)
    session.commit()

    set_flash(request, "Acesso do cliente atualizado.")
    return _RedirectResponse(f"/admin/clients/{client_id}", status_code=303)


print("[fix_permissions] ✅ Rotas de permissão redefinidas com FEATURE_KEYS completo")

# ============================================================================
# PATCH — Fix obras-horas bypass admin/equipe
# ============================================================================
# Problema: _require_obras_horas_context bloqueia admin/equipe com 403
# porque verifica apenas se o CLIENTE tem a feature, sem bypass de role.
#
# DEPLOY: adicione ao final do app.py (após ui_fix_permissions.py)
# ============================================================================

def _require_obras_horas_context_fixed(
    request,
    session,
):
    ctx = get_tenant_context(request, session)
    if not ctx:
        raise HTTPException(status_code=401, detail="Sessão inválida.")

    current_client = _client_current_client(request, session, ctx)
    if not current_client:
        raise HTTPException(status_code=400, detail="Selecione um cliente.")

    # ← FIX: admin e equipe sempre têm acesso, independente da config do cliente
    if ctx.membership.role in ("admin", "equipe"):
        return ctx, current_client

    # Para clientes, verifica a feature normalmente
    if not _obras_horas_feature_enabled_for_client(
        session,
        company_id=ctx.company.id,
        client_id=int(current_client.id),
    ):
        raise HTTPException(status_code=403, detail="Acesso não habilitado para este usuário/cliente.")

    return ctx, current_client


# Substitui a função original
import builtins as _builtins
_require_obras_horas_context = _require_obras_horas_context_fixed

# Atualiza no escopo global do app
import sys as _sys_ohf
_mod = _sys_ohf.modules[__name__] if __name__ in _sys_ohf.modules else None
globals()['_require_obras_horas_context'] = _require_obras_horas_context_fixed

print("[fix_obras_horas] ✅ Bypass admin/equipe aplicado para /obras-horas")

# ============================================================================
# PATCH — Fix visibility Augur + Remove sininho vermelho
# ============================================================================
# 1. Força ver_augur=True na API de visibility para admin/equipe
# 2. Remove sininho vermelho do navbar
# DEPLOY: adicione ao final do app.py
# ============================================================================

from fastapi import Request as _Req_av, Depends as _Dep_av
from fastapi.responses import JSONResponse as _JSON_av
from sqlmodel import Session as _Sess_av

# ── Fix 1: API visibility sempre retorna ver_augur=True ──────────────────────

@app.get("/api/member/visibility")
@require_login
async def api_member_visibility_fixed(
    request: _Req_av,
    session: _Sess_av = _Dep_av(get_session)
):
    ctx = get_tenant_context(request, session)
    if not ctx:
        return _JSON_av({"ver_score": True, "ver_diagnostico": True,
                         "ver_dre": True, "ver_augur": True})
    try:
        vis = get_member_visibility(session, ctx.membership.id)
    except Exception:
        vis = {"ver_score": True, "ver_diagnostico": True,
               "ver_dre": True, "ver_augur": True}

    # Sempre mostra Augur — não esconde mais
    vis["ver_augur"] = True
    return _JSON_av(vis)

print("[fix_augur_visibility] ✅ API visibility corrigida — ver_augur sempre True")

# ── Fix 2: Remove sininho vermelho do navbar ──────────────────────────────────

_base = TEMPLATES.get("base.html", "")
if _base:
    import re as _re_sin

    # Remove qualquer badge/contador vermelho no sininho
    _base = _re_sin.sub(
        r'<span[^>]*class="[^"]*badge[^"]*bg-danger[^"]*"[^>]*>.*?</span>',
        '',
        _base,
        flags=_re_sin.DOTALL
    )
    # Remove o sininho completamente se tiver href="/notificacoes"
    # mas mantém os outros botões do navbar
    _base = _re_sin.sub(
        r'<a[^>]*href="/notificacoes"[^>]*>.*?</a>\s*',
        '',
        _base,
        flags=_re_sin.DOTALL
    )

    TEMPLATES["base.html"] = _base
    print("[fix_augur_visibility] ✅ Sininho removido do navbar")

if hasattr(templates_env.loader, "mapping"):
    templates_env.loader.mapping = TEMPLATES

print("[fix_augur_visibility] ✅ Patch completo")

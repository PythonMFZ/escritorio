# ============================================================================
# PATCH — Fix rotas admin liberadas para equipe
# ============================================================================
# Problema: /admin/familias, /admin/servicos-internos e /admin/parceiros
# têm @require_role({"admin"}) hardcoded — equipe recebe 403 mesmo com
# permissão habilitada no painel.
#
# Solução: redefine as 7 rotas com require_role({"admin","equipe"})
# O FastAPI usa a última definição de rota registrada.
#
# DEPLOY: adicione ao final do app.py (após todos os outros patches)
# ============================================================================

import inspect as _inspect_re
from functools import wraps as _wraps_re
from fastapi import Depends as _Depends_re
from fastapi.responses import HTMLResponse as _HTML_re
from sqlmodel import Session as _Session_re
from fastapi import Request as _Request_re, Form as _Form_re

# ── Busca as funções originais no escopo global ───────────────────────────────
_orig_familias_get        = globals().get("admin_familias_page")
_orig_servicos_get        = globals().get("admin_servicos_internos_page")
_orig_servicos_add        = globals().get("admin_servicos_internos_add")
_orig_parceiros_get       = globals().get("admin_parceiros_page")
_orig_parceiros_add       = globals().get("admin_parceiros_add")
_orig_parceiros_prod_add  = globals().get("admin_parceiros_products_add")
_orig_parceiros_camp_add  = globals().get("admin_parceiros_campaigns_add")

_ADMIN_EQUIPE = {"admin", "equipe"}

# ── Redefine as rotas com admin+equipe ────────────────────────────────────────

if _orig_familias_get:
    @app.get("/admin/familias", response_class=_HTML_re)
    @require_role(_ADMIN_EQUIPE)
    async def admin_familias_page_fixed(request: _Request_re, session: _Session_re = _Depends_re(get_session)):
        return await _orig_familias_get(request=request, session=session)
    print("[fix_equipe_routes] ✅ /admin/familias liberado para equipe")
else:
    print("[fix_equipe_routes] ⚠️  admin_familias_page não encontrado")

if _orig_servicos_get:
    @app.get("/admin/servicos-internos", response_class=_HTML_re)
    @require_role(_ADMIN_EQUIPE)
    async def admin_servicos_internos_page_fixed(request: _Request_re, session: _Session_re = _Depends_re(get_session)):
        return await _orig_servicos_get(request=request, session=session)
    print("[fix_equipe_routes] ✅ /admin/servicos-internos GET liberado para equipe")

if _orig_servicos_add:
    @app.post("/admin/servicos-internos/add")
    @require_role(_ADMIN_EQUIPE)
    async def admin_servicos_internos_add_fixed(request: _Request_re, session: _Session_re = _Depends_re(get_session)):
        return await _orig_servicos_add(request=request, session=session)
    print("[fix_equipe_routes] ✅ /admin/servicos-internos/add liberado para equipe")

if _orig_parceiros_get:
    @app.get("/admin/parceiros", response_class=_HTML_re)
    @require_role(_ADMIN_EQUIPE)
    async def admin_parceiros_page_fixed(request: _Request_re, session: _Session_re = _Depends_re(get_session)):
        return await _orig_parceiros_get(request=request, session=session)
    print("[fix_equipe_routes] ✅ /admin/parceiros GET liberado para equipe")

if _orig_parceiros_add:
    @app.post("/admin/parceiros/add")
    @require_role(_ADMIN_EQUIPE)
    async def admin_parceiros_add_fixed(request: _Request_re, session: _Session_re = _Depends_re(get_session)):
        return await _orig_parceiros_add(request=request, session=session)
    print("[fix_equipe_routes] ✅ /admin/parceiros/add liberado para equipe")

if _orig_parceiros_prod_add:
    @app.post("/admin/parceiros/products/add")
    @require_role(_ADMIN_EQUIPE)
    async def admin_parceiros_products_add_fixed(request: _Request_re, session: _Session_re = _Depends_re(get_session)):
        return await _orig_parceiros_prod_add(request=request, session=session)
    print("[fix_equipe_routes] ✅ /admin/parceiros/products/add liberado para equipe")

if _orig_parceiros_camp_add:
    @app.post("/admin/parceiros/campaigns/add")
    @require_role(_ADMIN_EQUIPE)
    async def admin_parceiros_campaigns_add_fixed(request: _Request_re, session: _Session_re = _Depends_re(get_session)):
        return await _orig_parceiros_camp_add(request=request, session=session)
    print("[fix_equipe_routes] ✅ /admin/parceiros/campaigns/add liberado para equipe")

print("[fix_equipe_routes] ✅ Patch completo — rotas admin liberadas para equipe")

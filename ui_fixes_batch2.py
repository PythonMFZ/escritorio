# ============================================================================
# PATCH — Batch de fixes (batch2)
#
# 1. Notícias — debug endpoint + loader com SSL verify=False fallback
# 2. Compliance prices — remove rota original (first-match fix)
# 3. ConstruRisk — LGPD checkbox correto (targeting processarDossie)
# 4. Augur historico API — remove rota original (first-match fix)
# ============================================================================

import re as _re_b2
from datetime import datetime as _dt_b2, timedelta as _td_b2, timezone as _tz_b2
from typing import Optional as _OptB2

import httpx as _httpx_b2
from fastapi import Request as _ReqB2, Depends as _DepB2
from fastapi.responses import (
    JSONResponse as _JSONB2,
    HTMLResponse as _HTMLB2,
    RedirectResponse as _RedirB2,
)
from sqlmodel import Session as _SessB2, select as _selB2


# ─────────────────────────────────────────────────────────────────────────────
# 1. NOTÍCIAS — debug endpoint + loader com SSL verify=False fallback
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/api/ui/news/debug")
@require_login
async def _news_debug_b2(
    request: _ReqB2, session: _SessB2 = _DepB2(get_session)
) -> _JSONB2:
    ctx = get_tenant_context(request, session)
    if not ctx or ctx.membership.role not in ("admin", "equipe"):
        return _JSONB2({"error": "não autorizado"}, status_code=403)

    feeds = session.exec(
        _selB2(UiNewsFeed).where(UiNewsFeed.company_id == ctx.company.id)
    ).all()

    results = []
    for f in feeds:
        info: dict = {"name": f.name, "url": f.url, "active": f.is_active}
        for verify_ssl in (True, False):
            try:
                async with _httpx_b2.AsyncClient(
                    timeout=8, follow_redirects=True, verify=verify_ssl,
                    headers={"User-Agent": "Mozilla/5.0 (compatible; MCap/1.0)"},
                ) as cli:
                    r = await cli.get(f.url)
                    info.update({
                        "status": r.status_code,
                        "content_type": r.headers.get("content-type", ""),
                        "bytes": len(r.content),
                        "ok": 200 <= r.status_code < 300,
                        "ssl_verify": verify_ssl,
                        "sample": r.text[:300] if r.text else "",
                    })
                    break
            except Exception as e:
                info.update({"error": str(e), "ok": False, "ssl_verify": verify_ssl})
                if verify_ssl:
                    continue
        results.append(info)

    cache_k = (ctx.company.id, "news")
    cached = _UI_CACHE.get(cache_k)

    return _JSONB2({
        "feeds_db_count": len(results),
        "feeds": results,
        "cached_items": len(cached[1]) if cached else 0,
        "cache_age_s": round((_dt_b2.now().timestamp() - cached[0]), 1) if cached else None,
    })


async def _ui_load_news_b2(company_id: int, session, limit: int = 10) -> list:
    """Loader v2: SSL verify=False fallback, User-Agent melhorado, sem cache de falhas."""
    cached = _ui_cache_get(company_id, "news")
    if cached is not None:
        return cached

    ensure_ui_tables()

    try:
        feeds = session.exec(
            _selB2(UiNewsFeed)
            .where(UiNewsFeed.company_id == company_id, UiNewsFeed.is_active == True)
            .order_by(UiNewsFeed.sort_order, UiNewsFeed.id)
        ).all()
    except Exception:
        return []

    if not feeds:
        try:
            for f in _DEFAULT_NEWS_FEEDS:
                session.add(UiNewsFeed(
                    company_id=company_id,
                    name=f["name"],
                    url=f["url"],
                    sort_order=f["sort_order"],
                    is_active=True,
                ))
            session.commit()
            feeds = session.exec(
                _selB2(UiNewsFeed)
                .where(UiNewsFeed.company_id == company_id, UiNewsFeed.is_active == True)
                .order_by(UiNewsFeed.sort_order, UiNewsFeed.id)
            ).all()
        except Exception:
            return []

    all_items: list[dict] = []
    ok_count = 0

    for f in feeds:
        xml = b""
        for verify_ssl in (True, False):
            try:
                async with _httpx_b2.AsyncClient(
                    timeout=8,
                    headers={"User-Agent": "Mozilla/5.0 (compatible; MaffezzolliCapital/1.0; +rss)"},
                    follow_redirects=True,
                    verify=verify_ssl,
                ) as cli:
                    r = await cli.get(f.url)
                    if 200 <= r.status_code < 300:
                        xml = r.content
                        break
            except Exception:
                if not verify_ssl:
                    break
                continue

        if xml:
            parsed = _ui_parse_rss_atom(xml)
            for it in parsed[:25]:
                it["source"] = it.get("source") or f.name
                all_items.append(it)
            ok_count += 1
        else:
            print(f"[fixes_batch2] News: feed '{f.name}' não carregou ({f.url})")

    if not all_items:
        print(f"[fixes_batch2] News: nenhum item de {len(feeds)} feeds — sem cache")
        return []

    dedup: dict[str, dict] = {}
    for it in all_items:
        u = it.get("url") or ""
        if u and u not in dedup:
            dedup[u] = it

    epoch = _dt_b2(1970, 1, 1, tzinfo=_tz_b2.utc)
    items2 = sorted(
        dedup.values(),
        key=lambda x: x.get("published_dt") or epoch,
        reverse=True,
    )[:max(1, min(limit, 30))]

    sao_paulo = _tz_b2(_td_b2(hours=-3))
    out = []
    for it in items2:
        dt = it.get("published_dt")
        out.append({
            "title":     it.get("title") or "",
            "url":       it.get("url") or "",
            "source":    it.get("source") or "",
            "published": dt.astimezone(sao_paulo).strftime("%d/%m %H:%M")
                         if hasattr(dt, "astimezone") else "",
        })

    _ui_cache_set(company_id, "news", out)
    print(f"[fixes_batch2] News: {len(out)} itens de {ok_count}/{len(feeds)} feeds")
    return out


_ui_load_news = _ui_load_news_b2
print("[fixes_batch2] _ui_load_news atualizada (v2: SSL fallback + User-Agent melhorado)")


# ─────────────────────────────────────────────────────────────────────────────
# 2. COMPLIANCE PRICES — remove rota original para que batch1 fix seja first-match
# ─────────────────────────────────────────────────────────────────────────────
# FastAPI usa first-match. O app.py registra /consultas sem product_code/company_id.
# O batch1 re-registrou (corretamente) mas fica no final da lista, nunca chamado.
# Aqui removemos as rotas anteriores, deixando apenas o fix do batch1 (último).

def _b2_fix_route_order() -> None:
    routes = app.routes

    # /consultas GET
    _idx = [i for i, r in enumerate(routes)
            if getattr(r, "path", None) == "/consultas"
            and "GET" in (getattr(r, "methods", None) or set())]
    if len(_idx) > 1:
        for i in sorted(_idx[:-1], reverse=True):
            routes.pop(i)
        print(f"[fixes_batch2] /consultas: {len(_idx)-1} rota(s) original(is) removida(s) → batch1 fix ativo")
    else:
        print(f"[fixes_batch2] /consultas: {len(_idx)} rota(s) encontrada(s) (ok)")

    # /api/ai/historico GET
    _idx2 = [i for i, r in enumerate(routes)
             if getattr(r, "path", None) == "/api/ai/historico"
             and "GET" in (getattr(r, "methods", None) or set())]
    if len(_idx2) > 1:
        for i in sorted(_idx2[:-1], reverse=True):
            routes.pop(i)
        print(f"[fixes_batch2] /api/ai/historico: {len(_idx2)-1} rota(s) original(is) removida(s) → batch1 fix ativo")
    else:
        print(f"[fixes_batch2] /api/ai/historico: {len(_idx2)} rota(s) encontrada(s) (ok)")


_b2_fix_route_order()


# ─────────────────────────────────────────────────────────────────────────────
# 3. CONSTRURISK — LGPD checkbox + check em processarDossie
# ─────────────────────────────────────────────────────────────────────────────
# Batch1 buscou onclick="crProcessar()" que não existe no template.
# O template usa onclick="processarDossie('PF')" e processarDossie('PJ').
# Aqui injetamos: (a) checkbox LGPD antes das tabs, (b) verificação no JS.

def _b2_patch_construrisk_lgpd() -> None:
    tpl = TEMPLATES.get("construrisk.html", "")
    if not tpl:
        print("[fixes_batch2] ConstruRisk: template não encontrado")
        return

    changed = False

    # (a) Checkbox LGPD antes das tabs PF/PJ
    _OLD_TABS = '{# Tabs PF/PJ #}\n<div class="cr-tabs">'
    _NEW_TABS = (
        '<div class="form-check p-3 mb-3 rounded" '
        'style="background:#fffbeb;border:1px solid #f59e0b;">\n'
        '  <input class="form-check-input" type="checkbox" id="crLGPD">\n'
        '  <label class="form-check-label small" for="crLGPD">\n'
        '    <strong>Aceite LGPD obrigatório:</strong> Declaro que obtive o consentimento '
        'do titular conforme a <strong>LGPD (Lei 13.709/2018)</strong> e que esta consulta '
        'tem finalidade legítima de análise de crédito/risco imobiliário.\n'
        '  </label>\n'
        '</div>\n'
        '{# Tabs PF/PJ #}\n'
        '<div class="cr-tabs">'
    )
    if _OLD_TABS in tpl and "crLGPD" not in tpl:
        tpl = tpl.replace(_OLD_TABS, _NEW_TABS, 1)
        changed = True
        print("[fixes_batch2] ConstruRisk: checkbox LGPD adicionado antes das tabs")

    # (b) Verificação LGPD no início da função processarDossie
    # A função começa com: async function processarDossie(tipo) {\n  const doc
    _OLD_FN = "async function processarDossie(tipo) {\n  const doc"
    _NEW_FN = (
        "async function processarDossie(tipo) {\n"
        "  const lgpdCb = document.getElementById('crLGPD');\n"
        "  if (!lgpdCb || !lgpdCb.checked) {\n"
        "    alert('Você precisa marcar o aceite LGPD antes de gerar o dossiê.');\n"
        "    lgpdCb && lgpdCb.scrollIntoView({behavior: 'smooth', block: 'center'});\n"
        "    return;\n"
        "  }\n"
        "  const doc"
    )
    if _OLD_FN in tpl and "lgpdCb" not in tpl:
        tpl = tpl.replace(_OLD_FN, _NEW_FN, 1)
        changed = True
        print("[fixes_batch2] ConstruRisk: LGPD check adicionado em processarDossie")

    if changed:
        TEMPLATES["construrisk.html"] = tpl
    else:
        already_lgpd = "crLGPD" in tpl
        already_check = "lgpdCb" in tpl
        print(
            f"[fixes_batch2] ConstruRisk LGPD: sem alteração "
            f"(crLGPD={'sim' if already_lgpd else 'não'}, "
            f"lgpdCb={'sim' if already_check else 'não'})"
        )


def _b2_patch_construrisk_resultado() -> None:
    """Melhora exibição do parecer IA com seções Crédito/PLD (se batch1 não aplicou)."""
    tpl = TEMPLATES.get("construrisk_resultado.html", "")
    if not tpl or "parecerIA" in tpl:
        return

    _OLD = '<div class="cr-parecer">{{ dossie.parecer_ia }}</div>'
    _NEW = (
        '<div class="cr-parecer" id="parecerIA">'
        '{{ dossie.parecer_ia'
        ' | replace("## ANÁLISE DE CRÉDITO", \'<h6 class="mt-3 mb-1" style="color:#1d4ed8;">📊 ANÁLISE DE CRÉDITO</h6>\')'
        ' | replace("## ANÁLISE PLD (Prevenção à Lavagem de Dinheiro)", \'<h6 class="mt-3 mb-1" style="color:#b45309;">🔍 ANÁLISE PLD</h6>\')'
        ' | replace("## ANÁLISE PLD", \'<h6 class="mt-3 mb-1" style="color:#b45309;">🔍 ANÁLISE PLD</h6>\')'
        ' | replace("\\n- ", "<br>• ") | replace("\\n", "<br>") | safe }}'
        '</div>'
    )
    if _OLD in tpl:
        tpl = tpl.replace(_OLD, _NEW, 1)
        TEMPLATES["construrisk_resultado.html"] = tpl
        print("[fixes_batch2] ConstruRisk resultado: parecer IA formatado com seções")


_b2_patch_construrisk_lgpd()
_b2_patch_construrisk_resultado()


print("[fixes_batch2] ✅ Todos os fixes do batch2 aplicados.")

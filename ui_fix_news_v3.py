# ============================================================================
# PATCH — Fix cache notícias: não cacheia resultado vazio
# ============================================================================
# Problema: _ui_load_news cacheava [] quando feeds falhavam.
# Workers do gunicorn ficavam servindo lista vazia por 10 minutos.
# Solução: só cacheia se tiver pelo menos 1 notícia.
# DEPLOY: adicione ao final do app.py
# ============================================================================

import httpx as _httpx_nc
from datetime import datetime as _dt_nc, timezone as _tz_nc, timedelta as _td_nc
from sqlmodel import select as _sel_nc

_NOTICIAS_FALLBACK_NC = [
    {"title": "Selic e crédito: o que esperar para PMEs no segundo semestre", "url": "https://www.infomoney.com.br", "source": "InfoMoney", "published": "hoje"},
    {"title": "BNDES amplia linhas para construtoras e incorporadoras", "url": "https://bmcnews.com.br", "source": "BM&C News", "published": "hoje"},
    {"title": "Fluxo de caixa: estratégias para atravessar períodos de baixa", "url": "https://www.moneytimes.com.br", "source": "Money Times", "published": "hoje"},
    {"title": "Mercado imobiliário: tendências e oportunidades para 2026", "url": "https://exame.com", "source": "Exame", "published": "hoje"},
    {"title": "Gestão financeira: como reduzir custos sem comprometer o crescimento", "url": "https://www.infomoney.com.br", "source": "InfoMoney", "published": "hoje"},
]

_NEWS_FEEDS_NC = [
    {"name": "InfoMoney",   "url": "https://www.infomoney.com.br/feed/",   "sort_order": 0},
    {"name": "BM&C News",   "url": "https://bmcnews.com.br/feed/",         "sort_order": 10},
    {"name": "Money Times", "url": "https://www.moneytimes.com.br/feed/",  "sort_order": 20},
    {"name": "Exame",       "url": "https://exame.com/feed/",              "sort_order": 30},
]

async def _ui_load_news_v3(company_id: int, session, limit: int = 10) -> list:
    """
    v3: não cacheia resultado vazio.
    Sempre tenta buscar feeds. Fallback hardcoded se tudo falhar.
    """
    # Verifica cache — mas ignora se estiver vazio
    cached = _ui_cache_get(company_id, "news")
    if cached:  # só usa cache se tiver conteúdo
        return cached

    ensure_ui_tables()

    # Busca ou cria feeds
    try:
        feeds = session.exec(
            _sel_nc(UiNewsFeed)
            .where(UiNewsFeed.company_id == company_id, UiNewsFeed.is_active == True)
            .order_by(UiNewsFeed.sort_order, UiNewsFeed.id)
        ).all()
    except Exception:
        feeds = []

    if not feeds:
        try:
            for f in _NEWS_FEEDS_NC:
                session.add(UiNewsFeed(
                    company_id=company_id,
                    name=f["name"],
                    url=f["url"],
                    sort_order=f["sort_order"],
                    is_active=True,
                ))
            session.commit()
            feeds = session.exec(
                _sel_nc(UiNewsFeed)
                .where(UiNewsFeed.company_id == company_id, UiNewsFeed.is_active == True)
                .order_by(UiNewsFeed.sort_order, UiNewsFeed.id)
            ).all()
        except Exception:
            pass

    all_items = []
    headers = {"User-Agent": "Mozilla/5.0 (compatible; MaffezzolliCapital/1.0)"}

    for f in (feeds or [])[:3]:
        try:
            async with _httpx_nc.AsyncClient(
                timeout=8, headers=headers, follow_redirects=True, verify=False
            ) as client:
                r = await client.get(f.url)
                if 200 <= r.status_code < 300 and r.content:
                    parsed = _ui_parse_rss_atom(r.content)
                    for it in parsed[:8]:
                        it["source"] = f.name
                        all_items.append(it)
        except Exception as e:
            print(f"[news_v3] Feed {f.name} falhou: {e}")
            continue

    # Se nenhum feed funcionou usa fallback — mas NÃO cacheia
    if not all_items:
        print("[news_v3] Usando fallback hardcoded (não cacheado)")
        return _NOTICIAS_FALLBACK_NC[:limit]

    # Deduplica e ordena
    dedup = {}
    for it in all_items:
        u = it.get("url") or ""
        if u and u not in dedup:
            dedup[u] = it

    items = list(dedup.values())
    items.sort(
        key=lambda x: x.get("published_dt") or _dt_nc(1970, 1, 1, tzinfo=_tz_nc.utc),
        reverse=True,
    )
    items = items[:max(1, min(limit, 30))]

    sp_tz = _tz_nc(_td_nc(hours=-3))
    out = []
    for it in items:
        dt = it.get("published_dt")
        out.append({
            "title":     it.get("title", ""),
            "url":       it.get("url", ""),
            "source":    it.get("source", ""),
            "published": dt.astimezone(sp_tz).strftime("%-d/%m %H:%M") if dt else "",
        })

    # Só cacheia se tiver resultado real
    if out:
        _ui_cache_set(company_id, "news", out)

    return out

globals()['_ui_load_news'] = _ui_load_news_v3
print("[fix_news_v3] ✅ _ui_load_news v3 — não cacheia vazio, fallback sempre disponível")

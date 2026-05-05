# ============================================================================
# PATCH — Fix Notícias + Mudar Role Membro + Fix PDF ConstruRisk
# ============================================================================

import httpx as _httpx_fn
import json as _json_fn
import os as _os_fn
from datetime import datetime as _dt_fn, timezone as _tz_fn, timedelta as _td_fn
from fastapi import Request as _Req_fn, Depends as _Dep_fn
from fastapi.responses import HTMLResponse as _HTML_fn, JSONResponse as _JSON_fn, Response as _Resp_fn
from sqlmodel import Session as _Sess_fn, select as _sel_fn


# ── Fix 1: Notícias via feeds HTTPS + fallback hardcoded ─────────────────────

_NOTICIAS_FALLBACK = [
    {"title": "Selic mantida: o que muda para sua empresa?", "url": "https://www.infomoney.com.br", "source": "InfoMoney", "published": "hoje"},
    {"title": "Crédito para PMEs: novas linhas do BNDES em 2026", "url": "https://www.moneytimes.com.br", "source": "Money Times", "published": "hoje"},
    {"title": "Mercado imobiliário: tendências para o segundo semestre", "url": "https://bmcnews.com.br", "source": "BM&C News", "published": "hoje"},
    {"title": "Fluxo de caixa: como se preparar para períodos de baixa", "url": "https://www.infomoney.com.br", "source": "InfoMoney", "published": "hoje"},
    {"title": "Financiamento de obras: alternativas além dos bancos tradicionais", "url": "https://bmcnews.com.br", "source": "BM&C News", "published": "hoje"},
]

_NEWS_FEEDS_V2 = [
    {"name": "InfoMoney",   "url": "https://www.infomoney.com.br/feed/",   "sort_order": 0},
    {"name": "BM&C News",   "url": "https://bmcnews.com.br/feed/",         "sort_order": 10},
    {"name": "Money Times", "url": "https://www.moneytimes.com.br/feed/",  "sort_order": 20},
    {"name": "Exame",       "url": "https://exame.com/feed/",              "sort_order": 30},
]

async def _ui_load_news_v2(company_id: int, session, limit: int = 10) -> list:
    cached = _ui_cache_get(company_id, "news")
    if cached is not None:
        return cached

    ensure_ui_tables()

    try:
        feeds = session.exec(
            _sel_fn(UiNewsFeed)
            .where(UiNewsFeed.company_id == company_id, UiNewsFeed.is_active == True)
            .order_by(UiNewsFeed.sort_order, UiNewsFeed.id)
        ).all()
    except Exception:
        feeds = []

    if not feeds:
        try:
            for f in _NEWS_FEEDS_V2:
                session.add(UiNewsFeed(
                    company_id=company_id,
                    name=f["name"],
                    url=f["url"],
                    sort_order=f["sort_order"],
                    is_active=True,
                ))
            session.commit()
            feeds = session.exec(
                _sel_fn(UiNewsFeed)
                .where(UiNewsFeed.company_id == company_id, UiNewsFeed.is_active == True)
                .order_by(UiNewsFeed.sort_order, UiNewsFeed.id)
            ).all()
        except Exception:
            pass

    all_items = []
    headers = {"User-Agent": "Mozilla/5.0 (compatible; MaffezzolliCapital/1.0)"}

    for f in feeds[:3]:
        try:
            async with _httpx_fn.AsyncClient(timeout=8, headers=headers, follow_redirects=True, verify=False) as client:
                r = await client.get(f.url)
                if 200 <= r.status_code < 300 and r.content:
                    parsed = _ui_parse_rss_atom(r.content)
                    for it in parsed[:8]:
                        it["source"] = f.name
                        all_items.append(it)
        except Exception as e:
            print(f"[news] Feed {f.name} falhou: {e}")
            continue

    if not all_items:
        print("[news] Todos os feeds falharam, usando fallback")
        result = _NOTICIAS_FALLBACK[:limit]
        _ui_cache_set(company_id, "news", result)
        return result

    dedup = {}
    for it in all_items:
        u = it.get("url") or ""
        if u and u not in dedup:
            dedup[u] = it

    items = list(dedup.values())
    items.sort(key=lambda x: x.get("published_dt") or _dt_fn(1970, 1, 1, tzinfo=_tz_fn.utc), reverse=True)
    items = items[:max(1, min(limit, 30))]

    sp_tz = _tz_fn(_td_fn(hours=-3))
    out = []
    for it in items:
        dt = it.get("published_dt")
        out.append({
            "title":     it.get("title", ""),
            "url":       it.get("url", ""),
            "source":    it.get("source", ""),
            "published": dt.astimezone(sp_tz).strftime("%-d/%m %H:%M") if dt else "",
        })

    _ui_cache_set(company_id, "news", out)
    return out

globals()['_ui_load_news'] = _ui_load_news_v2
print("[fix_news] v2 carregada — feeds HTTPS + fallback")


# ── Fix 2: Rota para mudar role de membro ────────────────────────────────────

@app.post("/admin/members/{membership_id}/change-role")
@require_role({"admin"})
async def member_change_role(
    membership_id: int,
    request: _Req_fn,
    session: _Sess_fn = _Dep_fn(get_session),
):
    ctx = get_tenant_context(request, session)
    assert ctx is not None

    m = session.get(Membership, membership_id)
    if not m or m.company_id != ctx.company.id:
        return _JSON_fn({"ok": False, "erro": "Membro não encontrado."}, status_code=404)

    if m.id == ctx.membership.id:
        return _JSON_fn({"ok": False, "erro": "Não pode alterar própria role."}, status_code=400)

    form = await request.form()
    nova_role = str(form.get("role", "")).strip().lower()

    if nova_role not in {"admin", "equipe", "cliente"}:
        return _JSON_fn({"ok": False, "erro": f"Role inválida: {nova_role}"}, status_code=400)

    role_antiga = m.role
    m.role = nova_role
    m.updated_at = utcnow()
    session.add(m)
    session.commit()

    set_flash(request, f"Role alterada de '{role_antiga}' para '{nova_role}'.")
    return _JSON_fn({"ok": True, "role": nova_role})

print("[fix_news] Rota /admin/members/{id}/change-role criada")


# ── Fix 3: Botão mudar role na tela de membros ───────────────────────────────

_members_tpl = TEMPLATES.get("members.html", "")
if _members_tpl and "change-role" not in _members_tpl:
    _ROLE_SCRIPT = """
<script>
async function mudarRole(id, roleAtual) {
  const nova = prompt('Nova role (admin / equipe / cliente)\\nAtual: ' + roleAtual, roleAtual);
  if (!nova || nova.trim() === roleAtual) return;
  if (!['admin','equipe','cliente'].includes(nova.trim().toLowerCase())) {
    alert('Role inválida. Use: admin, equipe ou cliente');
    return;
  }
  const fd = new FormData();
  fd.append('role', nova.trim().toLowerCase());
  const r = await fetch('/admin/members/' + id + '/change-role', {method:'POST', body: fd});
  const d = await r.json();
  if (d.ok) { location.reload(); }
  else { alert('Erro: ' + (d.erro || 'Tente novamente')); }
}
</script>"""

    _role_badge = 'Role: <strong>{{ row.membership.role }}</strong>'
    _role_novo = 'Role: <strong>{{ row.membership.role }}</strong> <button class="btn btn-xs btn-outline-secondary ms-1" style="font-size:.65rem;padding:.1rem .4rem;" onclick="mudarRole({{ row.membership.id }}, \'{{ row.membership.role }}\')" title="Mudar role">✏️</button>'

    if _role_badge in _members_tpl:
        _members_tpl = _members_tpl.replace(_role_badge, _role_novo)

    if "{% endblock %}" in _members_tpl:
        _members_tpl = _members_tpl.replace("{% endblock %}", _ROLE_SCRIPT + "\n{% endblock %}", 1)

    TEMPLATES["members.html"] = _members_tpl
    print("[fix_news] Botão mudar role injetado na tela de membros")


# ── Fix 4: PDF ConstruRisk com fallback HTML ──────────────────────────────────

def _construrisk_pdf_html(d) -> str:
    try:
        resultado_dict = _json_cr.loads(d.resultado_json or "{}")
    except Exception:
        resultado_dict = {}

    summary = resultado_dict.get("summary", {})
    details = resultado_dict.get("details", [])
    parecer = d.parecer_ia or ""

    linhas_details = []
    for det in details:
        nome_api = det.get("nameAPI", "")
        alertas_html = ""
        for a in (det.get("alertList") or []):
            res = (a.get("resultType") or {}).get("result", "Regular")
            campo = a.get("fieldName", "")
            valor = a.get("value", "")
            alertas_html += f'<span class="alerta {res}">{campo}: {valor} &rarr; {res}</span> '
        linhas_details.append(f"<div class='section'><strong>{nome_api}</strong><br>{alertas_html}</div>")

    details_html = "\n".join(linhas_details)
    parecer_html = f"<h2>Parecer de Risco</h2><pre>{parecer}</pre>" if parecer else ""

    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<title>ConstruRisk - {d.nome or d.document}</title>
<style>
body{{font-family:Arial,sans-serif;font-size:12px;margin:2cm;color:#111;}}
h1{{font-size:18px;}} h2{{font-size:14px;margin-top:16px;border-bottom:1px solid #ccc;}}
.section{{margin-bottom:12px;}}
.alerta{{font-size:11px;padding:2px 6px;border-radius:4px;display:inline-block;margin:2px;}}
.Regular{{background:#dcfce7;color:#166534;}}
.Alerta{{background:#fee2e2;color:#991b1b;}}
pre{{white-space:pre-wrap;font-size:11px;}}
</style></head><body>
<h1>ConstruRisk — Dossiê de Análise de Risco</h1>
<div class="section">
<strong>{summary.get("name") or d.nome}</strong><br>
Documento: {summary.get("document") or d.document}<br>
Tipo: {d.person_type} | Data: {d.created_at[:10] if d.created_at else ""}<br>
Status: {summary.get("status", "")}
</div>
{parecer_html}
{"<h2>Detalhes por Módulo</h2>" + details_html if details_html else ""}
<script>window.onload=function(){{window.print();}}</script>
</body></html>"""


@app.get("/construrisk/{dossie_local_id}/pdf")
@require_login
async def construrisk_pdf_fixed(
    dossie_local_id: int,
    request: _Req_fn,
    session: _Sess_fn = _Dep_fn(get_session),
):
    ctx = get_tenant_context(request, session)
    if not ctx:
        return _JSON_fn({"ok": False}, status_code=401)

    d = session.get(ConstruRiskDossie, dossie_local_id)
    if not d or d.company_id != ctx.company.id:
        return _JSON_fn({"ok": False, "erro": "Não encontrado."}, status_code=404)

    if d.status != "done":
        return _JSON_fn({"ok": False, "erro": "Dossiê ainda não concluído."}, status_code=400)

    # Tenta PDF via DirectData
    try:
        resultado = _dd_generate_pdf(d.dossie_id)
        if isinstance(resultado, bytes) and len(resultado) > 100:
            return _Resp_fn(
                content=resultado,
                media_type="application/pdf",
                headers={"Content-Disposition": f'attachment; filename="construrisk_{d.document}.pdf"'},
            )
        elif isinstance(resultado, str) and resultado.startswith("http"):
            from fastapi.responses import RedirectResponse as _RR2
            return _RR2(resultado, status_code=302)
    except Exception as e:
        print(f"[construrisk_pdf] DirectData falhou: {e}")

    # Fallback: HTML imprimível
    html_content = _construrisk_pdf_html(d)
    return _Resp_fn(
        content=html_content.encode("utf-8"),
        media_type="text/html",
    )

print("[fix_news] PDF ConstruRisk corrigido com fallback HTML")

if hasattr(templates_env.loader, "mapping"):
    templates_env.loader.mapping = TEMPLATES

print("[fix_news] Patch completo carregado")

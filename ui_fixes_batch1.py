# ============================================================================
# PATCH — Batch de fixes (batch1)
#
# 1. Sininho navbar — remove badge de contagem (mantém só o ícone)
# 2. Notícias — não cacheia falhas, permitindo retry
# 3. Compliance prices — passa product_code e company_id corretamente
# 4. Planos duplicados — remove planos/minha_assinatura do grupo solucoes
# 5. ConstruRisk — LGPD checkbox + análise IA Crédito/PLD separados
# 6. Augur — páginas de Histórico Individual e Histórico de Conversas
# ============================================================================

import re as _re_b1
import math as _math_b1
from datetime import datetime as _dt_b1, timedelta as _td_b1
from typing import Optional as _OptB1

# ─────────────────────────────────────────────────────────────────────────────
# 1. SININHO — remove badge de contagem; mantém ícone simples
# ─────────────────────────────────────────────────────────────────────────────

def _b1_fix_sininho() -> None:
    tpl = TEMPLATES.get("base.html", "")
    if not tpl:
        return

    # Bloco condicional do sininho com badge (injetado por ui_sistema_saude.py)
    _OLD_BELL = (
        '{# ── Sininho de alertas ── #}\n'
        '            {% if smart_alerts_unread_count is defined and smart_alerts_unread_count > 0 %}\n'
        '            <a href="/#alertas" class="btn btn-outline-secondary btn-sm position-relative" title="Alertas não lidos">\n'
        '              <i class="bi bi-bell-fill text-warning"></i>\n'
        '              <span class="position-absolute top-0 start-100 translate-middle badge rounded-pill bg-danger" style="font-size:.6rem;">\n'
        '                {{ smart_alerts_unread_count }}\n'
        '              </span>\n'
        '            </a>\n'
        '            {% else %}\n'
        '            <a href="/#alertas" class="btn btn-outline-secondary btn-sm" title="Alertas">\n'
        '              <i class="bi bi-bell"></i>\n'
        '            </a>\n'
        '            {% endif %}'
    )
    _NEW_BELL = (
        '{# ── Sininho de alertas ── #}\n'
        '            <a href="/#alertas" class="btn btn-outline-secondary btn-sm" title="Alertas">\n'
        '              🔔\n'
        '            </a>'
    )

    if _OLD_BELL in tpl:
        TEMPLATES["base.html"] = tpl.replace(_OLD_BELL, _NEW_BELL, 1)
        print("[fixes_batch1] Sininho: badge de contagem removido")
    else:
        # Fallback: remove qualquer badge com smart_alerts_unread_count via regex
        tpl2 = _re_b1.sub(
            r'<span class="position-absolute[^"]*"[^>]*>\s*\{\{\s*smart_alerts_unread_count\s*\}\}\s*</span>',
            '',
            tpl,
        )
        if tpl2 != tpl:
            TEMPLATES["base.html"] = tpl2
            print("[fixes_batch1] Sininho: badge removido via regex")
        else:
            print("[fixes_batch1] Sininho: nenhum badge encontrado (já ok ou formato diferente)")

_b1_fix_sininho()


# ─────────────────────────────────────────────────────────────────────────────
# 2. NOTÍCIAS — não cacheia resultado vazio em caso de falha
# ─────────────────────────────────────────────────────────────────────────────
# Monkey-patch da função _ui_load_news para não persistir [] no cache
# quando ocorre erro (permite retry na próxima requisição).

import httpx as _httpx_b1

async def _ui_load_news_fixed(company_id: int, session, limit: int = 10) -> list:
    from sqlmodel import select as _sel_b1
    cached = _ui_cache_get(company_id, "news")
    if cached is not None:
        return cached

    ensure_ui_tables()

    try:
        feeds = session.exec(
            _sel_b1(UiNewsFeed)
            .where(UiNewsFeed.company_id == company_id, UiNewsFeed.is_active == True)
            .order_by(UiNewsFeed.sort_order, UiNewsFeed.id)
        ).all()
    except Exception:
        # Não cacheia falha — retry na próxima requisição
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
                _sel_b1(UiNewsFeed)
                .where(UiNewsFeed.company_id == company_id, UiNewsFeed.is_active == True)
                .order_by(UiNewsFeed.sort_order, UiNewsFeed.id)
            ).all()
        except Exception:
            return []  # não cacheia

    all_items: list[dict] = []
    ok_count = 0
    for f in feeds:
        try:
            async with _httpx_b1.AsyncClient(
                timeout=15,
                headers={"User-Agent": "MaffezzolliCapitalApp/1.0 (+rss)"},
                follow_redirects=True,
            ) as _cli:
                r = await _cli.get(f.url)
                xml = r.content if 200 <= r.status_code < 300 else b""
        except Exception:
            xml = b""
        if xml:
            parsed = _ui_parse_rss_atom(xml)
            for it in parsed[:25]:
                it["source"] = it.get("source") or f.name
                all_items.append(it)
            ok_count += 1

    if not all_items:
        # Não cacheia: tenta novamente na próxima requisição
        return []

    dedup: dict[str, dict] = {}
    for it in all_items:
        u = it.get("url") or ""
        if u and u not in dedup:
            dedup[u] = it

    from datetime import timezone as _tz_b1, timedelta as _tdz_b1, datetime as _dtz_b1
    items2 = sorted(
        dedup.values(),
        key=lambda x: x.get("published_dt") or _dtz_b1(1970, 1, 1, tzinfo=_tz_b1.utc),
        reverse=True,
    )[:max(1, min(limit, 30))]

    sao_paulo_tz = _tz_b1(timedelta(hours=-3))
    out = []
    for it in items2:
        dt = it.get("published_dt")
        out.append({
            "title":     it.get("title") or "",
            "url":       it.get("url") or "",
            "source":    it.get("source") or "",
            "published": dt.astimezone(sao_paulo_tz).strftime("%d/%m %H:%M")
                         if hasattr(dt, "astimezone") else "",
        })

    _ui_cache_set(company_id, "news", out)
    print(f"[fixes_batch1] News: {len(out)} itens de {ok_count}/{len(feeds)} feeds")
    return out

# Substitui função global
import builtins as _builtins_b1
import sys as _sys_b1
_sys_b1.modules[__name__]  # evita erro de nome
_ui_load_news = _ui_load_news_fixed
print("[fixes_batch1] _ui_load_news substituída (sem cache de falhas)")


# ─────────────────────────────────────────────────────────────────────────────
# 3. COMPLIANCE PRICES — product_code correto para _price_cents
# ─────────────────────────────────────────────────────────────────────────────
# A rota /consultas chama _price_cents(cost_cents, markup_pct) sem product_code
# nem company_id, fazendo sempre o cálculo por markup.
# Aqui sobrescrevemos a rota para passar os parâmetros corretos.

from fastapi import Request as _RequestB1, Depends as _DependsB1
from fastapi.responses import HTMLResponse as _HTMLB1, RedirectResponse as _RedirB1
from sqlmodel import Session as _SessB1, select as _selB1

@app.get("/consultas", response_class=_HTMLB1)
@require_login
async def consultas_home_fixed(
    request: _RequestB1, session: _SessB1 = _DependsB1(get_session)
) -> _HTMLB1:
    ctx = get_tenant_context(request, session)
    if not ctx:
        request.session.clear()
        return _RedirB1("/login", status_code=303)

    active_client_id = get_active_client_id(request, session, ctx)
    if not active_client_id and getattr(ctx.membership, "client_id", None):
        active_client_id = int(ctx.membership.client_id)

    if not active_client_id:
        set_flash(request, "Selecione um cliente para usar consultas.")
        return _RedirB1("/", status_code=303)

    client = get_client_or_none(session, ctx.company.id, int(active_client_id))
    if not client:
        set_flash(request, "Cliente inválido.")
        return _RedirB1("/", status_code=303)

    _seed_credit_products(session, ctx.company.id)
    _disable_unwanted_products(session, ctx.company.id)

    products = session.exec(
        _selB1(QueryProduct).where(
            QueryProduct.company_id == ctx.company.id,
            QueryProduct.enabled == True,
            QueryProduct.code != "directdata.cadastral_pf",
        ).order_by(QueryProduct.label)
    ).all()

    def _short_code(code: str) -> str:
        """directdata.scr_analitico → scr_analitico"""
        return code.split(".")[-1] if "." in code else code

    enriched = [{
        "code":        p.code,
        "label":       p.label,
        "price_cents": _price_cents(
            p.provider_cost_cents,
            p.markup_pct,
            product_code=_short_code(p.code),
            company_id=ctx.company.id,
        ),
    } for p in products]

    w = _get_or_create_wallet(session, company_id=ctx.company.id, client_id=client.id)
    return render("consultas.html", request=request, context={
        "title":          "Consultas",
        "wallet_balance": f"{w.balance_cents / 100:.2f}",
        "products":       enriched,
    })

print("[fixes_batch1] /consultas sobrescrita com product_code correto")


# ─────────────────────────────────────────────────────────────────────────────
# 4. PLANOS DUPLICADOS — remove planos/minha_assinatura do grupo solucoes
# ─────────────────────────────────────────────────────────────────────────────

_b1_keys_to_remove = {"planos", "minha_assinatura"}
for _b1_g in FEATURE_GROUPS:
    if _b1_g.get("key") == "solucoes":
        before = list(_b1_g["features"])
        _b1_g["features"] = [f for f in _b1_g["features"] if f not in _b1_keys_to_remove]
        removed = [f for f in before if f not in _b1_g["features"]]
        if removed:
            print(f"[fixes_batch1] Planos: removido {removed} do grupo 'solucoes'")
        break

# Garante que estão em minha_empresa (sem duplicata)
for _b1_g in FEATURE_GROUPS:
    if _b1_g.get("key") == "minha_empresa":
        for _b1_fk in ["planos", "minha_assinatura"]:
            if _b1_fk not in _b1_g["features"]:
                _b1_g["features"].append(_b1_fk)
        break

print("[fixes_batch1] Planos: planos/minha_assinatura apenas em 'minha_empresa'")


# ─────────────────────────────────────────────────────────────────────────────
# 5. CONSTRURISK — LGPD checkbox + análise IA Crédito/PLD separados
# ─────────────────────────────────────────────────────────────────────────────

# 5a. Melhora prompt da análise IA
def _gerar_parecer_ia_v2(resultado: dict, person_type: str) -> str:
    import requests as _req_b1cr
    api_key = _os_sh.getenv("ANTHROPIC_API_KEY", "")
    if not api_key:
        return ""

    summary = resultado.get("summary", {})
    doc     = summary.get("document", "")
    nome    = summary.get("name", "")
    status  = summary.get("status", "")
    template = summary.get("templateName", "")

    alertas: list[str] = []
    for detail in resultado.get("details", []):
        for item in detail.get("items", []):
            nivel = str(item.get("alertLevel") or item.get("nivel") or "").lower()
            if nivel in ("alto", "médio", "critico", "critical", "high", "medium"):
                descr = item.get("description") or item.get("name") or ""
                if descr:
                    alertas.append(f"  • [{nivel.upper()}] {descr}")

    # Campos relevantes do summary
    campos_extra: list[str] = []
    for k, v in summary.items():
        if k in ("document", "name", "status", "templateName"):
            continue
        if v and str(v).strip():
            campos_extra.append(f"  {k}: {v}")

    prompt = f"""Você é um analista especializado em risco financeiro e compliance.

DADOS DO DOSSIÊ ({person_type}):
- Nome: {nome or "(não informado)"}
- Documento: {doc}
- Status geral: {status}
- Template: {template}
{chr(10).join(campos_extra) if campos_extra else ""}

ALERTAS IDENTIFICADOS:
{chr(10).join(alertas) if alertas else "Nenhum alerta crítico identificado."}

Gere um PARECER ESTRUTURADO em duas seções obrigatórias:

## ANÁLISE DE CRÉDITO
- Classificação de risco: (Baixo / Médio / Alto / Crítico)
- Capacidade de pagamento e histórico financeiro
- Recomendação para concessão de crédito (aprovado / aprovado com ressalvas / reprovado)
- Condições sugeridas se aprovado (prazo, garantias, limites)

## ANÁLISE PLD (Prevenção à Lavagem de Dinheiro)
- Perfil de risco PLD: (Normal / Atenção / Alto Risco)
- Indicadores de risco identificados
- Recomendação de diligência (KYC simplificado / padrão / reforçado)
- Necessidade de comunicação ao COAF: (Sim / Não / Avaliar)

Seja objetivo. Máximo 400 palavras no total. Use apenas os dados fornecidos."""

    try:
        resp = _req_b1cr.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": "claude-sonnet-4-6",
                "max_tokens": 1000,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()["content"][0]["text"]
    except Exception as e:
        print(f"[fixes_batch1] ConstruRisk parecer IA erro: {e}")
        return ""

# Sobrescreve no escopo global
_gerar_parecer_ia = _gerar_parecer_ia_v2
print("[fixes_batch1] ConstruRisk: _gerar_parecer_ia_v2 ativada (Crédito + PLD)")


# 5b. Injeta LGPD checkbox e melhora exibição do parecer IA no template

def _b1_patch_construrisk_template() -> None:
    tpl = TEMPLATES.get("construrisk.html", "")
    if not tpl:
        print("[fixes_batch1] ConstruRisk template não encontrado")
        return

    # Adiciona checkbox LGPD antes do botão de submissão
    _OLD_BTN = '<button type="button" class="btn btn-primary w-100" onclick="crProcessar()">'
    _NEW_BTN = (
        '<div class="form-check mb-3">\n'
        '  <input class="form-check-input" type="checkbox" id="crLGPD" required>\n'
        '  <label class="form-check-label small" for="crLGPD">\n'
        '    Declaro que obtive o consentimento do titular conforme a <strong>LGPD (Lei 13.709/2018)</strong>'
        ' e que a consulta tem finalidade legítima de análise de crédito/risco.\n'
        '  </label>\n'
        '</div>\n'
        '<button type="button" class="btn btn-primary w-100" onclick="crProcessarComLGPD()">'
    )
    if _OLD_BTN in tpl and "crLGPD" not in tpl:
        tpl = tpl.replace(_OLD_BTN, _NEW_BTN, 1)
        print("[fixes_batch1] ConstruRisk: checkbox LGPD adicionado")

    # Injeta função JS crProcessarComLGPD antes do fechamento do script
    _OLD_FUNC = 'async function crProcessar() {'
    _NEW_FUNC = (
        'function crProcessarComLGPD() {\n'
        '  const cb = document.getElementById("crLGPD");\n'
        '  if (!cb || !cb.checked) {\n'
        '    alert("Você precisa confirmar o aceite LGPD antes de prosseguir.");\n'
        '    return;\n'
        '  }\n'
        '  crProcessar();\n'
        '}\n\n'
        'async function crProcessar() {'
    )
    if _OLD_FUNC in tpl and 'crProcessarComLGPD' not in tpl:
        tpl = tpl.replace(_OLD_FUNC, _NEW_FUNC, 1)
        print("[fixes_batch1] ConstruRisk: JS LGPD adicionado")

    TEMPLATES["construrisk.html"] = tpl


def _b1_patch_construrisk_resultado() -> None:
    tpl = TEMPLATES.get("construrisk_resultado.html", "")
    if not tpl:
        return

    # Melhora exibição do parecer IA: renderiza markdown mínimo (## como título)
    _OLD_PARECER = '{{ dossie.parecer_ia }}'
    _NEW_PARECER = (
        '<div id="parecerIA" class="p-2">'
        '{{ dossie.parecer_ia | replace("## ANÁLISE DE CRÉDITO", \'<h6 class="mt-3 text-primary">📊 ANÁLISE DE CRÉDITO</h6>\') '
        '| replace("## ANÁLISE PLD (Prevenção à Lavagem de Dinheiro)", \'<h6 class="mt-3 text-warning">🔍 ANÁLISE PLD</h6>\') '
        '| replace("\\n- ", "<br>• ") | replace("\\n", "<br>") | safe }}'
        '</div>'
    )
    if _OLD_PARECER in tpl and 'parecerIA' not in tpl:
        tpl = tpl.replace(_OLD_PARECER, _NEW_PARECER, 1)
        TEMPLATES["construrisk_resultado.html"] = tpl
        print("[fixes_batch1] ConstruRisk resultado: parecer IA com seções Crédito/PLD")

_b1_patch_construrisk_template()
_b1_patch_construrisk_resultado()


# ─────────────────────────────────────────────────────────────────────────────
# 6. AUGUR — Histórico Individual (/augur/historico) e
#            Histórico de Conversas (/augur/conversas)
# ─────────────────────────────────────────────────────────────────────────────

from fastapi.responses import JSONResponse as _JSONB1

# Template: Histórico Individual (usuário/empresa — lista de mensagens do cliente ativo)
TEMPLATES["augur_historico.html"] = r"""{% extends "base.html" %}
{% block title %}Augur — Histórico Individual{% endblock %}
{% block content %}
<div class="container py-4" style="max-width:860px;">
  <div class="d-flex align-items-center gap-2 mb-4">
    <div style="width:36px;height:36px;border-radius:10px;background:#1a1a1a;display:flex;align-items:center;justify-content:center;flex-shrink:0;">
      <img src="/static/augur_logo_v3.png" alt="Augur" style="width:24px;height:24px;object-fit:contain;">
    </div>
    <div>
      <h4 class="mb-0">Augur — Histórico Individual</h4>
      <div class="muted" style="font-size:.8rem;">
        {% if current_client %}{{ current_client.name }} · {% endif %}Últimas conversas (30 dias)
      </div>
    </div>
    <a href="/augur/conversas" class="btn btn-outline-secondary btn-sm ms-auto">📋 Histórico de Conversas</a>
  </div>

  {% if not current_client %}
  <div class="alert alert-warning">Selecione um cliente para ver o histórico.</div>
  {% else %}

  <div class="d-flex gap-2 mb-3 flex-wrap">
    <select id="filterRole" class="form-select form-select-sm" style="width:auto;" onchange="renderMsgs()">
      <option value="">Todas as mensagens</option>
      <option value="user">Perguntas (usuário)</option>
      <option value="assistant">Respostas (Augur)</option>
    </select>
    <input id="filterText" type="search" class="form-control form-control-sm" style="width:220px;"
           placeholder="Filtrar por texto…" oninput="renderMsgs()">
    <span class="badge bg-secondary align-self-center ms-auto" id="countBadge">—</span>
  </div>

  <div id="msgList" class="d-flex flex-column gap-2"></div>
  <div id="emptyMsg" class="text-center muted py-5" style="display:none!important;">
    Nenhuma mensagem encontrada.
  </div>
  {% endif %}
</div>

<style>
.aug-hist-item { border-radius:10px; padding:.75rem 1rem; font-size:.88rem; line-height:1.5; }
.aug-hist-user { background:#f0f4ff; border-left:3px solid #4f6ef7; }
.aug-hist-assistant { background:#fafafa; border-left:3px solid #1a1a1a; }
.aug-hist-meta { font-size:.72rem; color:#888; margin-bottom:.25rem; }
.aug-hist-content { white-space:pre-wrap; word-break:break-word; }
</style>

<script>
let _allMsgs = [];

async function loadHistorico() {
  const res = await fetch('/api/ai/historico?days=30');
  const d = await res.json();
  _allMsgs = d.mensagens || [];
  renderMsgs();
}

function renderMsgs() {
  const role = document.getElementById('filterRole')?.value || '';
  const txt  = (document.getElementById('filterText')?.value || '').toLowerCase();
  const list = document.getElementById('msgList');
  const empty = document.getElementById('emptyMsg');
  if (!list) return;

  const filtered = _allMsgs.filter(m => {
    if (role && m.role !== role) return false;
    if (txt && !m.content.toLowerCase().includes(txt)) return false;
    return true;
  });

  const badge = document.getElementById('countBadge');
  if (badge) badge.textContent = filtered.length + ' msg(s)';

  if (!filtered.length) {
    list.innerHTML = '';
    if (empty) empty.style.display = '';
    return;
  }
  if (empty) empty.style.display = 'none';

  list.innerHTML = filtered.map(m => `
    <div class="aug-hist-item aug-hist-${m.role}">
      <div class="aug-hist-meta">
        ${m.role === 'user' ? '👤 Usuário' : '🤖 Augur'} · ${m.hora || ''}
        ${m.feedback === 1 ? ' · 👍' : m.feedback === -1 ? ' · 👎' : ''}
      </div>
      <div class="aug-hist-content">${escHtml(m.content)}</div>
    </div>
  `).join('');
}

function escHtml(s) {
  return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

loadHistorico();
</script>
{% endblock %}
"""


# Template: Histórico de Conversas (visão empresa — por cliente, agrupado por dia)
TEMPLATES["augur_conversas.html"] = r"""{% extends "base.html" %}
{% block title %}Augur — Histórico de Conversas{% endblock %}
{% block content %}
<div class="container py-4" style="max-width:1000px;">
  <div class="d-flex align-items-center gap-2 mb-4">
    <div style="width:36px;height:36px;border-radius:10px;background:#1a1a1a;display:flex;align-items:center;justify-content:center;flex-shrink:0;">
      <img src="/static/augur_logo_v3.png" alt="Augur" style="width:24px;height:24px;object-fit:contain;">
    </div>
    <div>
      <h4 class="mb-0">Augur — Histórico de Conversas</h4>
      <div class="muted" style="font-size:.8rem;">Todos os clientes · Últimos 30 dias</div>
    </div>
    <a href="/augur/historico" class="btn btn-outline-secondary btn-sm ms-auto">👤 Histórico Individual</a>
  </div>

  <div class="d-flex gap-2 mb-3 flex-wrap">
    <input id="filterClient" type="search" class="form-control form-control-sm" style="width:220px;"
           placeholder="Filtrar por cliente…" oninput="renderConversas()">
    <input id="filterText" type="search" class="form-control form-control-sm" style="width:220px;"
           placeholder="Filtrar por texto…" oninput="renderConversas()">
    <span class="badge bg-secondary align-self-center ms-auto" id="countBadge">—</span>
  </div>

  <div id="convList"></div>
</div>

<style>
.conv-group { border:1px solid #e5e7eb; border-radius:12px; overflow:hidden; margin-bottom:1rem; }
.conv-group-header { background:#f8f9fa; padding:.6rem 1rem; font-size:.85rem; font-weight:600; cursor:pointer;
  display:flex; justify-content:space-between; align-items:center; }
.conv-group-body { padding:.75rem 1rem; display:flex; flex-direction:column; gap:.5rem; }
.conv-item { font-size:.84rem; padding:.5rem .75rem; border-radius:8px; }
.conv-item.user { background:#f0f4ff; }
.conv-item.assistant { background:#fafafa; }
.conv-meta { font-size:.7rem; color:#888; margin-bottom:.2rem; }
.conv-content { white-space:pre-wrap; word-break:break-word; max-height:120px; overflow:hidden; position:relative; }
.conv-content.expanded { max-height:none; }
.conv-expand { font-size:.72rem; color:#4f6ef7; cursor:pointer; }
</style>

<script>
let _convData = [];

async function loadConversas() {
  const res = await fetch('/api/ai/conversas');
  const d   = await res.json();
  _convData = d.grupos || [];
  renderConversas();
}

function renderConversas() {
  const fcli  = (document.getElementById('filterClient')?.value || '').toLowerCase();
  const ftxt  = (document.getElementById('filterText')?.value || '').toLowerCase();
  const list  = document.getElementById('convList');
  const badge = document.getElementById('countBadge');
  if (!list) return;

  const grupos = _convData.filter(g => {
    if (fcli && !g.client_name.toLowerCase().includes(fcli)) return false;
    if (ftxt && !g.msgs.some(m => m.content.toLowerCase().includes(ftxt))) return false;
    return true;
  });

  if (badge) badge.textContent = grupos.length + ' cliente(s)';

  if (!grupos.length) {
    list.innerHTML = '<div class="text-center muted py-5">Nenhuma conversa encontrada.</div>';
    return;
  }

  list.innerHTML = grupos.map((g, gi) => `
    <div class="conv-group">
      <div class="conv-group-header" onclick="toggleGrp(${gi})">
        <span>👤 ${escHtml(g.client_name)} <span class="fw-normal text-muted">(${g.msgs.length} msg(s))</span></span>
        <span id="arrow-${gi}">▼</span>
      </div>
      <div class="conv-group-body" id="grp-${gi}">
        ${g.msgs.map((m, mi) => `
          <div class="conv-item ${m.role}">
            <div class="conv-meta">${m.role === 'user' ? '👤' : '🤖'} ${m.hora || ''}</div>
            <div class="conv-content" id="cc-${gi}-${mi}">${escHtml(m.content)}</div>
            ${m.content.length > 200 ? `<span class="conv-expand" onclick="expandMsg('cc-${gi}-${mi}',this)">Ver mais ▼</span>` : ''}
          </div>
        `).join('')}
      </div>
    </div>
  `).join('');
}

function toggleGrp(gi) {
  const body  = document.getElementById(`grp-${gi}`);
  const arrow = document.getElementById(`arrow-${gi}`);
  const hidden = body.style.display === 'none';
  body.style.display = hidden ? '' : 'none';
  arrow.textContent  = hidden ? '▼' : '▶';
}

function expandMsg(id, el) {
  const el2 = document.getElementById(id);
  if (!el2) return;
  el2.classList.toggle('expanded');
  el.textContent = el2.classList.contains('expanded') ? 'Ver menos ▲' : 'Ver mais ▼';
}

function escHtml(s) {
  return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

loadConversas();
</script>
{% endblock %}
"""


# Rota: /augur/historico
@app.get("/augur/historico", response_class=_HTMLB1)
@require_login
async def augur_historico_page(
    request: _RequestB1, session: _SessB1 = _DependsB1(get_session)
) -> _HTMLB1:
    ctx = get_tenant_context(request, session)
    if not ctx:
        return _RedirB1("/login", status_code=303)
    cc = get_client_or_none(session, ctx.company.id,
                            get_active_client_id(request, session, ctx))
    return render("augur_historico.html", request=request, context={
        "current_user":    ctx.user,
        "current_company": ctx.company,
        "role":            ctx.membership.role,
        "current_client":  cc,
    })


# Rota: /augur/conversas (admin/equipe — visão empresa)
@app.get("/augur/conversas", response_class=_HTMLB1)
@require_login
async def augur_conversas_page(
    request: _RequestB1, session: _SessB1 = _DependsB1(get_session)
) -> _HTMLB1:
    ctx = get_tenant_context(request, session)
    if not ctx:
        return _RedirB1("/login", status_code=303)
    if ctx.membership.role not in ("admin", "equipe"):
        return _RedirB1("/augur/historico", status_code=303)
    return render("augur_conversas.html", request=request, context={
        "current_user":    ctx.user,
        "current_company": ctx.company,
        "role":            ctx.membership.role,
    })


# API: /api/ai/historico — estende para aceitar ?days=N
@app.get("/api/ai/historico")
@require_login
async def augur_historico_api_v2(
    request: _RequestB1,
    days: int = 15,
    session: _SessB1 = _DependsB1(get_session),
) -> _JSONB1:
    ctx = get_tenant_context(request, session)
    if not ctx:
        return _JSONB1({"mensagens": []})

    client_id = get_active_client_id(request, session, ctx)
    client    = get_client_or_none(session, ctx.company.id, client_id)
    if not client:
        return _JSONB1({"mensagens": []})

    cutoff = (_dt_b1.utcnow() - _td_b1(days=max(1, min(days, 90)))).isoformat()
    msgs = session.exec(
        _selB1(AugurMensagem)
        .where(
            AugurMensagem.company_id == ctx.company.id,
            AugurMensagem.client_id  == client.id,
            AugurMensagem.created_at >= cutoff,
        )
        .order_by(AugurMensagem.id.asc())
    ).all()

    return _JSONB1({
        "mensagens": [
            {
                "id":       m.id,
                "role":     m.role,
                "content":  m.content,
                "feedback": m.feedback,
                "hora":     m.created_at[11:16] if len(m.created_at) > 15 else "",
            }
            for m in msgs
        ]
    })


# API: /api/ai/conversas — visão empresa (todos clientes, agrupado)
@app.get("/api/ai/conversas")
@require_login
async def augur_conversas_api(
    request: _RequestB1,
    days: int = 30,
    session: _SessB1 = _DependsB1(get_session),
) -> _JSONB1:
    ctx = get_tenant_context(request, session)
    if not ctx:
        return _JSONB1({"grupos": []})
    if ctx.membership.role not in ("admin", "equipe"):
        return _JSONB1({"grupos": []}, status_code=403)

    cutoff = (_dt_b1.utcnow() - _td_b1(days=max(1, min(days, 90)))).isoformat()

    from sqlmodel import select as _sel2
    msgs = session.exec(
        _sel2(AugurMensagem)
        .where(
            AugurMensagem.company_id == ctx.company.id,
            AugurMensagem.created_at >= cutoff,
        )
        .order_by(AugurMensagem.client_id.asc(), AugurMensagem.id.asc())
    ).all()

    # Agrupa por client_id
    from collections import defaultdict as _dd_b1
    groups: dict[int, list] = _dd_b1(list)
    for m in msgs:
        groups[m.client_id].append(m)

    # Busca nomes dos clientes
    result = []
    for cid, cmsg in groups.items():
        client = get_client_or_none(session, ctx.company.id, cid)
        cname = client.name if client else f"Cliente #{cid}"
        result.append({
            "client_id":   cid,
            "client_name": cname,
            "msgs": [
                {
                    "id":       m.id,
                    "role":     m.role,
                    "content":  m.content,
                    "feedback": m.feedback,
                    "hora":     m.created_at[11:16] if len(m.created_at) > 15 else "",
                }
                for m in cmsg
            ],
        })

    result.sort(key=lambda x: x["client_name"])
    return _JSONB1({"grupos": result})


# Adiciona links no FEATURE_KEYS
if "augur_historico" not in FEATURE_KEYS:
    FEATURE_KEYS["augur_historico"] = {
        "title": "Histórico Augur", "desc": "Histórico de conversas com o Augur.", "href": "/augur/historico"
    }
    FEATURE_VISIBLE_ROLES["augur_historico"] = {"admin", "equipe", "cliente"}

print("[fixes_batch1] Augur: rotas /augur/historico e /augur/conversas criadas")
print("[fixes_batch1] ✅ Todos os fixes do batch1 aplicados.")

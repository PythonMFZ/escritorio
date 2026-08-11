# ============================================================================
# ui_limpar_notion.py — Remove referências ao Notion dos templates de reunião
#                       e garante propagação do template reunioes_acoes.html
# ============================================================================

import re as _re_ln

# ── 1. meetings_list.html ────────────────────────────────────────────────────

_tpl = TEMPLATES.get("meetings_list.html", "")
if _tpl:
    # Subtítulo "Sincronização com Notion..."
    _tpl = _tpl.replace(
        '<div class="muted">Sincronização com Notion AI Meeting Notes</div>',
        '<div class="muted">Registros de reuniões e ações corretivas</div>',
    )
    # Badge notion_status na lista
    _tpl = _tpl.replace(
        '<span class="badge text-bg-light border">{{ m.notion_status or "—" }}</span>',
        '',
    )
    TEMPLATES["meetings_list.html"] = _tpl
    if hasattr(templates_env.loader, "mapping"):
        templates_env.loader.mapping["meetings_list.html"] = _tpl
    print("[limpar_notion] ✅ meetings_list.html limpo.")

# ── 2. meetings_detail.html ──────────────────────────────────────────────────

_tpl = TEMPLATES.get("meetings_detail.html", "")
if _tpl:
    # Linha "Status Notion: ..."
    _tpl = _tpl.replace(
        'Status Notion: <b>{{ meeting.notion_status or "—" }}</b>',
        '',
    )
    # Bloco "Abrir no Notion"
    _tpl = _tpl.replace(
        '{% if meeting.notion_url %}\n        <div class="small mt-1"><a href="{{ meeting.notion_url }}" target="_blank" rel="noopener">Abrir no Notion</a></div>\n      {% endif %}',
        '',
    )
    # Botão Sincronizar (Notion)
    _tpl = _tpl.replace(
        '{% if role in ["admin","equipe"] %}\n        <form method="post" action="/reunioes/{{ meeting.id }}/sync">\n          <button class="btn btn-outline-primary" type="submit">Sincronizar</button>\n        </form>\n      {% endif %}',
        '',
    )
    TEMPLATES["meetings_detail.html"] = _tpl
    if hasattr(templates_env.loader, "mapping"):
        templates_env.loader.mapping["meetings_detail.html"] = _tpl
    print("[limpar_notion] ✅ meetings_detail.html limpo.")

# ── 3. meetings_new.html ─────────────────────────────────────────────────────

_tpl = TEMPLATES.get("meetings_new.html", "")
if _tpl:
    # Subtítulo com Notion
    _tpl = _tpl.replace(
        '<div class="muted">Você pode criar a reunião sem Notion e vincular o link (ou ID) depois, quando quiser sincronizar.</div>',
        '<div class="muted">Registre a reunião e grave a ata pelo microfone ou upload de arquivo.</div>',
    )
    # Alerta NOTION_TOKEN
    _tpl = _re_ln.sub(
        r'\{%\s*if not notion_enabled\s*%\}.*?\{%\s*endif\s*%\}',
        '',
        _tpl,
        flags=_re_ln.DOTALL,
    )
    # Campo "Link ou ID da página do Notion"
    _tpl = _re_ln.sub(
        r'<div class="col-12">\s*<label[^>]*>Link ou ID da página do Notion.*?</div>\s*</div>',
        '',
        _tpl,
        flags=_re_ln.DOTALL,
    )
    # Checkbox "Sincronizar agora"
    _tpl = _re_ln.sub(
        r'<div class="col-12 form-check">.*?</div>',
        '',
        _tpl,
        flags=_re_ln.DOTALL,
    )
    TEMPLATES["meetings_new.html"] = _tpl
    if hasattr(templates_env.loader, "mapping"):
        templates_env.loader.mapping["meetings_new.html"] = _tpl
    print("[limpar_notion] ✅ meetings_new.html limpo.")

# ── 4. Forçar propagação do reunioes_acoes.html (botão Participantes) ────────
# O template é definido em ui_reunioes_v2.py com o botão, mas pode ter sido
# sobrescrito pelo loader ao carregar do disco. Forçamos aqui a versão correta.

_acoes_tpl = TEMPLATES.get("reunioes_acoes.html", "")
if _acoes_tpl and hasattr(templates_env.loader, "mapping"):
    templates_env.loader.mapping["reunioes_acoes.html"] = _acoes_tpl
    print("[limpar_notion] ✅ reunioes_acoes.html propagado ao loader (botão Participantes).")
else:
    print("[limpar_notion] ⚠️ reunioes_acoes.html não encontrado em TEMPLATES.")

# ── 5. Remover "última sincronização" do detalhe (se ainda presente) ─────────
for _k in ("meetings_detail.html",):
    _t = TEMPLATES.get(_k, "")
    if "Última sincronização" in _t:
        _t = _re_ln.sub(
            r'\{%\s*if meeting\.last_synced_at\s*%\}.*?\{%\s*endif\s*%\}',
            '',
            _t,
            flags=_re_ln.DOTALL,
        )
        TEMPLATES[_k] = _t
        if hasattr(templates_env.loader, "mapping"):
            templates_env.loader.mapping[_k] = _t

print("[limpar_notion] ✅ Módulo de limpeza Notion carregado.")

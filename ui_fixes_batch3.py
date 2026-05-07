# No seu Mac, dentro do diretório do projeto:
git pull origin main

cat > ui_fixes_batch3.py << 'PYEOF'
# ============================================================================
# PATCH — Batch de fixes (batch3)
# ============================================================================

import re as _re_b3

# 1a. OBRAS — editarEtapa JS + salvarEtapa com edit mode
def _b3_patch_obras_editar() -> None:
    tpl = TEMPLATES.get("ferramenta_obras_cronograma.html", "")
    if not tpl or "editarEtapa" in tpl:
        print("[fixes_batch3] Obras editarEtapa: já existe ou template não encontrado")
        return
    changed = False
    _OLD_VAR = "let _aptEtapaId = null;\n"
    if _OLD_VAR in tpl:
        tpl = tpl.replace(_OLD_VAR, "let _aptEtapaId = null;\nlet _etapaEditId = null;\n", 1)
        changed = True
    _OLD_NOVA = "// ── Nova etapa ──\nfunction abrirNovaEtapa(faseId, faseNome) {\n  _etapaFaseId = faseId;"
    _NEW_NOVA = (
        "// ── Editar etapa ──\n"
        "function editarEtapa(id, descricao, insumo, orcado, inicio, fim) {\n"
        "  _etapaEditId = id;\n  _etapaFaseId = null;\n"
        "  const _h6 = document.querySelector('#modalEtapa h6');\n"
        "  const _btn = document.querySelector('#modalEtapa .btn-primary');\n"
        "  if (_h6) _h6.textContent = '✏️ Editar Etapa';\n"
        "  if (_btn) _btn.textContent = 'Salvar Edição';\n"
        "  document.getElementById('etapaFaseNome').textContent = 'Editando etapa';\n"
        "  document.getElementById('etapaDesc').value = descricao;\n"
        "  document.getElementById('etapaInsumo').value = insumo;\n"
        "  document.getElementById('etapaOrcado').value = orcado;\n"
        "  document.getElementById('etapaIni').value = inicio;\n"
        "  document.getElementById('etapaFim').value = fim;\n"
        "  abrirModal('modalEtapa');\n}\n\n"
        "// ── Nova etapa ──\nfunction abrirNovaEtapa(faseId, faseNome) {\n"
        "  _etapaEditId = null;\n"
        "  const _h6ne = document.querySelector('#modalEtapa h6');\n"
        "  const _bne = document.querySelector('#modalEtapa .btn-primary');\n"
        "  if (_h6ne) _h6ne.textContent = '➕ Nova Etapa';\n"
        "  if (_bne) _bne.textContent = 'Criar Etapa';\n"
        "  _etapaFaseId = faseId;"
    )
    if _OLD_NOVA in tpl:
        tpl = tpl.replace(_OLD_NOVA, _NEW_NOVA, 1)
        changed = True
        print("[fixes_batch3] Obras: editarEtapa adicionada")
    _OLD_SAVE = (
        "async function salvarEtapa() {\n"
        "  const r = await fetch('/ferramentas/obras/' + OBRA_ID + '/etapa/nova', {"
    )
    _NEW_SAVE = (
        "async function salvarEtapa() {\n"
        "  if (_etapaEditId) {\n"
        "    const _body = new URLSearchParams({\n"
        "      descricao: document.getElementById('etapaDesc').value,\n"
        "      insumo: document.getElementById('etapaInsumo').value,\n"
        "      orcado_rs: document.getElementById('etapaOrcado').value || '0',\n"
        "      data_inicio: document.getElementById('etapaIni').value,\n"
        "      data_fim: document.getElementById('etapaFim').value,\n"
        "      ordem: '0',\n    });\n"
        "    const _r = await fetch('/ferramentas/obras/etapa/' + _etapaEditId + '/editar-completo', {\n"
        "      method: 'POST',\n"
        "      headers: {'Content-Type': 'application/x-www-form-urlencoded'},\n"
        "      body: _body,\n    });\n"
        "    const _d = await _r.json();\n"
        "    _etapaEditId = null;\n"
        "    if (_d.ok) { fecharModal(); location.reload(); }\n"
        "    else { alert('Erro ao salvar edição.'); }\n"
        "    return;\n  }\n"
        "  const r = await fetch('/ferramentas/obras/' + OBRA_ID + '/etapa/nova', {"
    )
    if _OLD_SAVE in tpl:
        tpl = tpl.replace(_OLD_SAVE, _NEW_SAVE, 1)
        changed = True
        print("[fixes_batch3] Obras: salvarEtapa com edit mode")
    if changed:
        TEMPLATES["ferramenta_obras_cronograma.html"] = tpl

_b3_patch_obras_editar()

# 1b. OBRAS — info "i" popover on click
def _b3_patch_obras_info_popover() -> None:
    tpl = TEMPLATES.get("ferramenta_obras_cronograma.html", "")
    if not tpl or "_kpiInfoPopover" in tpl:
        return
    _OLD = (
        ".cr-kpi-info{display:inline-block;width:14px;height:14px;border-radius:50%;"
        "background:#e5e7eb;color:#6b7280;font-size:.62rem;font-weight:700;"
        "text-align:center;line-height:14px;cursor:help;margin-left:.3rem;vertical-align:middle;}\n"
        "</style>"
    )
    _NEW = (
        ".cr-kpi-info{display:inline-block;width:14px;height:14px;border-radius:50%;"
        "background:#e5e7eb;color:#6b7280;font-size:.62rem;font-weight:700;"
        "text-align:center;line-height:14px;cursor:pointer;margin-left:.3rem;vertical-align:middle;}\n"
        "#_kpiInfoPopover{position:fixed;z-index:9999;background:#1a1a1a;color:#fff;"
        "font-size:.78rem;line-height:1.5;padding:.6rem .85rem;border-radius:10px;"
        "max-width:280px;box-shadow:0 4px 16px rgba(0,0,0,.25);pointer-events:none;display:none;}\n"
        "</style>\n"
        "<div id='_kpiInfoPopover'></div>\n"
        "<script>\n(function(){\n"
        "  const pop = document.getElementById('_kpiInfoPopover');\n"
        "  document.querySelectorAll('.cr-kpi-info').forEach(function(el){\n"
        "    el.addEventListener('click', function(e){\n"
        "      e.stopPropagation();\n"
        "      pop.textContent = el.title;\n"
        "      const r = el.getBoundingClientRect();\n"
        "      pop.style.display = 'block';\n"
        "      let left = r.left + window.scrollX;\n"
        "      let top = r.bottom + window.scrollY + 6;\n"
        "      if (left + 288 > window.innerWidth) left = window.innerWidth - 296;\n"
        "      pop.style.left = left + 'px';\n"
        "      pop.style.top = top + 'px';\n"
        "    });\n  });\n"
        "  document.addEventListener('click', function(){ pop.style.display='none'; });\n"
        "})();\n</script>"
    )
    if _OLD in tpl:
        tpl = tpl.replace(_OLD, _NEW, 1)
        TEMPLATES["ferramenta_obras_cronograma.html"] = tpl
        print("[fixes_batch3] Obras: info 'i' popover adicionado")

_b3_patch_obras_info_popover()

# 2. NAVBAR — remove sininho extra
def _b3_fix_sininho() -> None:
    tpl = TEMPLATES.get("base.html", "")
    if not tpl:
        return
    tpl2 = _re_b3.sub(
        r'\n?\s*\{#\s*── Sininho de alertas ──\s*#\}.*?\{%[-\s]*endif[-\s]*%\}',
        '', tpl, count=1, flags=_re_b3.DOTALL)
    tpl2 = _re_b3.sub(
        r'\n?\s*\{#\s*── Sininho de alertas ──\s*#\}\s*\n\s*<a [^>]*>[\s\n]*🔔[\s\n]*</a>',
        '', tpl2, count=1)
    if tpl2 != tpl:
        TEMPLATES["base.html"] = tpl2
        print("[fixes_batch3] Sininho extra removido do navbar")
    else:
        print("[fixes_batch3] Sininho: nenhuma ocorrência encontrada")

_b3_fix_sininho()

# 3. AUGUR — reforce sessões e base de conhecimento após DOMContentLoaded
def _b3_patch_augur_sessoes() -> None:
    tpl = TEMPLATES.get("base.html", "")
    if not tpl or "_b3AugurReforce" in tpl:
        return
    _SCRIPT = (
        "\n<!-- _b3AugurReforce -->\n<script>\n"
        "document.addEventListener('DOMContentLoaded', function() {\n"
        "  setTimeout(function() {\n"
        "    if (typeof window.augurCarregarSessoes === 'function') window.augurCarregarSessoes();\n"
        "    if (typeof window.baseCarregar === 'function') window.baseCarregar();\n"
        "  }, 500);\n"
        "});\n</script>\n"
    )
    if "</body>" in tpl:
        tpl = tpl.replace("</body>", _SCRIPT + "</body>", 1)
        TEMPLATES["base.html"] = tpl
        print("[fixes_batch3] Augur: reforce sessoes/base injetado")

_b3_patch_augur_sessoes()

print("[fixes_batch3] Todos os fixes do batch3 aplicados.")
PYEOF

# Adiciona exec ao app.py se não existir


# ============================================================================
# PATCH — Batch de fixes (batch3)
#
# 1. Obras: editarEtapa JS (funcao faltando) + info "i" com popover on click
# 2. Navbar: remove sininho extra apos botao Sair
# 3. Augur: reload sessoes apos envio + base de conhecimento sem refresh
# ============================================================================

import re as _re_b3


# ─────────────────────────────────────────────────────────────────────────────
# 1a. OBRAS — adiciona editarEtapa e modifica salvarEtapa para edit mode
# ─────────────────────────────────────────────────────────────────────────────

def _b3_patch_obras_editar() -> None:
    tpl = TEMPLATES.get("ferramenta_obras_cronograma.html", "")
    if not tpl:
        print("[fixes_batch3] Obras cronograma: template nao encontrado")
        return
    if "editarEtapa" in tpl:
        print("[fixes_batch3] Obras editarEtapa: ja existe")
        return

    changed = False

    # (a) Declara _etapaEditId junto com _aptEtapaId
    _OLD_VAR = "let _aptEtapaId = null;\n"
    _NEW_VAR = "let _aptEtapaId = null;\nlet _etapaEditId = null;\n"
    if _OLD_VAR in tpl:
        tpl = tpl.replace(_OLD_VAR, _NEW_VAR, 1)
        changed = True

    # (b) Adiciona editarEtapa antes de abrirNovaEtapa
    _OLD_NOVA = "// ── Nova etapa ──\nfunction abrirNovaEtapa(faseId, faseNome) {\n  _etapaFaseId = faseId;"
    _NEW_NOVA = (
        "// -- Editar etapa --\n"
        "function editarEtapa(id, descricao, insumo, orcado, inicio, fim) {\n"
        "  _etapaEditId = id;\n"
        "  _etapaFaseId = null;\n"
        "  const _h6 = document.querySelector('#modalEtapa h6');\n"
        "  const _btn = document.querySelector('#modalEtapa .btn-primary');\n"
        "  if (_h6) _h6.textContent = '\u270f\ufe0f Editar Etapa';\n"
        "  if (_btn) _btn.textContent = 'Salvar Edi\u00e7\u00e3o';\n"
        "  document.getElementById('etapaFaseNome').textContent = 'Editando etapa';\n"
        "  document.getElementById('etapaDesc').value = descricao;\n"
        "  document.getElementById('etapaInsumo').value = insumo;\n"
        "  document.getElementById('etapaOrcado').value = orcado;\n"
        "  document.getElementById('etapaIni').value = inicio;\n"
        "  document.getElementById('etapaFim').value = fim;\n"
        "  abrirModal('modalEtapa');\n"
        "}\n\n"
        "// -- Nova etapa --\n"
        "function abrirNovaEtapa(faseId, faseNome) {\n"
        "  _etapaEditId = null;\n"
        "  const _h6ne = document.querySelector('#modalEtapa h6');\n"
        "  const _bne = document.querySelector('#modalEtapa .btn-primary');\n"
        "  if (_h6ne) _h6ne.textContent = '\u2795 Nova Etapa';\n"
        "  if (_bne) _bne.textContent = 'Criar Etapa';\n"
        "  _etapaFaseId = faseId;"
    )
    if _OLD_NOVA in tpl:
        tpl = tpl.replace(_OLD_NOVA, _NEW_NOVA, 1)
        changed = True
        print("[fixes_batch3] Obras: editarEtapa adicionada")

    # (c) Modifica salvarEtapa para lidar com edit mode
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
        "      ordem: '0',\n"
        "    });\n"
        "    const _r = await fetch('/ferramentas/obras/etapa/' + _etapaEditId + '/editar-completo', {\n"
        "      method: 'POST',\n"
        "      headers: {'Content-Type': 'application/x-www-form-urlencoded'},\n"
        "      body: _body,\n"
        "    });\n"
        "    const _d = await _r.json();\n"
        "    _etapaEditId = null;\n"
        "    if (_d.ok) { fecharModal(); location.reload(); }\n"
        "    else { alert('Erro ao salvar edi\u00e7\u00e3o.'); }\n"
        "    return;\n"
        "  }\n"
        "  const r = await fetch('/ferramentas/obras/' + OBRA_ID + '/etapa/nova', {"
    )
    if _OLD_SAVE in tpl:
        tpl = tpl.replace(_OLD_SAVE, _NEW_SAVE, 1)
        changed = True
        print("[fixes_batch3] Obras: salvarEtapa atualizada para edit mode")

    if changed:
        TEMPLATES["ferramenta_obras_cronograma.html"] = tpl
    else:
        print("[fixes_batch3] Obras editar: nenhuma alteracao (strings nao encontradas)")


_b3_patch_obras_editar()


# ─────────────────────────────────────────────────────────────────────────────
# 1b. OBRAS — info "i" com popover on click
# ─────────────────────────────────────────────────────────────────────────────

def _b3_patch_obras_info_popover() -> None:
    tpl = TEMPLATES.get("ferramenta_obras_cronograma.html", "")
    if not tpl or "_kpiInfoPopover" in tpl:
        return

    _OLD_STYLE = (
        ".cr-kpi-info{display:inline-block;width:14px;height:14px;border-radius:50%;"
        "background:#e5e7eb;color:#6b7280;font-size:.62rem;font-weight:700;"
        "text-align:center;line-height:14px;cursor:help;margin-left:.3rem;vertical-align:middle;}\n"
        "</style>"
    )
    _NEW_STYLE = (
        ".cr-kpi-info{display:inline-block;width:14px;height:14px;border-radius:50%;"
        "background:#e5e7eb;color:#6b7280;font-size:.62rem;font-weight:700;"
        "text-align:center;line-height:14px;cursor:pointer;margin-left:.3rem;vertical-align:middle;}\n"
        "#_kpiInfoPopover{position:fixed;z-index:9999;background:#1a1a1a;color:#fff;"
        "font-size:.78rem;line-height:1.5;padding:.6rem .85rem;border-radius:10px;"
        "max-width:280px;box-shadow:0 4px 16px rgba(0,0,0,.25);pointer-events:none;display:none;}\n"
        "</style>\n"
        "<div id='_kpiInfoPopover'></div>\n"
        "<script>\n"
        "(function(){\n"
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
        "    });\n"
        "  });\n"
        "  document.addEventListener('click', function(){ pop.style.display='none'; });\n"
        "})();\n"
        "</script>"
    )
    if _OLD_STYLE in tpl:
        tpl = tpl.replace(_OLD_STYLE, _NEW_STYLE, 1)
        TEMPLATES["ferramenta_obras_cronograma.html"] = tpl
        print("[fixes_batch3] Obras: info 'i' popover on click adicionado")
    else:
        print("[fixes_batch3] Obras info popover: string nao encontrada")


_b3_patch_obras_info_popover()


# ─────────────────────────────────────────────────────────────────────────────
# 2. NAVBAR — remove sininho extra apos botao Sair
# ─────────────────────────────────────────────────────────────────────────────

def _b3_fix_sininho() -> None:
    tpl = TEMPLATES.get("base.html", "")
    if not tpl:
        return

    tpl2 = tpl

    # Passo 1: restaura {% else %}/{% endif %} se batch3 anterior os removeu junto com o sininho
    _sair_pos = tpl2.find('href="/logout">Sair</a>')
    if _sair_pos != -1:
        _after = tpl2[_sair_pos:_sair_pos + 400]
        if not any(t in _after for t in ("{% else %}", "{%- else", "{% else -%}")):
            m = _re_b3.search(r'(<a [^>]*href="/logout"[^>]*>Sair</a>)([\s]*)(</div>)', tpl2)
            if m:
                tpl2 = tpl2.replace(
                    m.group(0),
                    m.group(1) + '\n          {% else %}\n'
                    '            <a class="btn btn-outline-primary btn-sm" href="/login">Entrar</a>\n'
                    '          {% endif %}\n'
                    '        ' + m.group(3), 1)
                print("[fixes_batch3] Sininho: else/endif restaurados apos dano anterior")

    # Passo 2a: remove bloco condicional completo do sininho
    # lookahead (?=...) garante que paramos no {% endif %} do sininho, nao no externo
    tpl2 = _re_b3.sub(
        r'\n?\s*\{#\s*── Sininho de alertas ──\s*#\}.*?\{%-?\s*endif\s*-?%\}(?=\s*\n\s*\{%-?\s*else)',
        '',
        tpl2,
        count=1,
        flags=_re_b3.DOTALL,
    )

    # Passo 2b: remove versao simplificada pelo batch1 (comentario + ancora sem if/endif proprios)
    tpl2 = _re_b3.sub(
        r'\n?\s*\{#\s*── Sininho de alertas ──\s*#\}\s*\n\s*<a [^>]*href="[^"]*alertas[^"]*"[^>]*>[\s\S]*?</a>',
        '',
        tpl2,
        count=1,
    )

    if tpl2 != tpl:
        TEMPLATES["base.html"] = tpl2
        print("[fixes_batch3] Sininho extra removido do navbar")
    else:
        print("[fixes_batch3] Sininho: nenhuma ocorrencia encontrada (ja ok)")


_b3_fix_sininho()


# ─────────────────────────────────────────────────────────────────────────────
# 3. AUGUR — garante augurCarregarSessoes e baseCarregar apos montar widget
# ─────────────────────────────────────────────────────────────────────────────

def _b3_patch_augur_reload() -> None:
    tpl = TEMPLATES.get("base.html", "")
    if not tpl or "_b3AugurReforce" in tpl:
        return

    _SCRIPT = (
        "\n<!-- _b3AugurReforce -->\n"
        "<script>\n"
        "document.addEventListener('DOMContentLoaded', function() {\n"
        "  setTimeout(function() {\n"
        "    if (typeof window.augurCarregarSessoes === 'function') {\n"
        "      window.augurCarregarSessoes();\n"
        "    }\n"
        "    if (typeof window.baseCarregar === 'function') {\n"
        "      window.baseCarregar();\n"
        "    }\n"
        "  }, 600);\n"
        "});\n"
        "</script>\n"
    )

    if "</body>" in tpl:
        tpl = tpl.replace("</body>", _SCRIPT + "</body>", 1)
        TEMPLATES["base.html"] = tpl
        print("[fixes_batch3] Augur: reforce de sessoes injetado no base.html")
    else:
        print("[fixes_batch3] Augur: </body> nao encontrado no base.html")


_b3_patch_augur_reload()

print("[fixes_batch3] Todos os fixes do batch3 aplicados.")

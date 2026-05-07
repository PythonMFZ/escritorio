# ============================================================================
# PATCH — Batch de fixes (batch5)
#
# 1. Obras editarEtapa: guard errado ("editarEtapa" always True) -> corrige
# 2. Info popover timing: IIFE rodava antes do DOM -> DOMContentLoaded
# 3. Augur sessoes: augurCarregarSessoes nao estava em window -> expoe
# 4. Base de conhecimento: _format_client_context nao incluia docs -> repatch
# ============================================================================

import re as _re_b5


def _b5_patch_obras_editar() -> None:
    tpl = TEMPLATES.get("ferramenta_obras_cronograma.html", "")
    if not tpl:
        print("[fixes_batch5] Obras cronograma: template nao encontrado")
        return
    if "function editarEtapa" in tpl:
        print("[fixes_batch5] editarEtapa: ja existe, nada a fazer")
        return

    changed = False

    _OLD_VAR = "let _aptEtapaId = null;\n"
    _NEW_VAR = "let _aptEtapaId = null;\nlet _etapaEditId = null;\n"
    if _OLD_VAR in tpl:
        tpl = tpl.replace(_OLD_VAR, _NEW_VAR, 1)
        changed = True

    _OLD_NOVA = "// ── Nova etapa ──\nfunction abrirNovaEtapa(faseId, faseNome) {\n  _etapaFaseId = faseId;"
    _NEW_NOVA = (
        "// -- Editar etapa --\n"
        "function editarEtapa(id, descricao, insumo, orcado, inicio, fim) {\n"
        "  _etapaEditId = id;\n"
        "  _etapaFaseId = null;\n"
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
        "  abrirModal('modalEtapa');\n"
        "}\n\n"
        "// -- Nova etapa --\n"
        "function abrirNovaEtapa(faseId, faseNome) {\n"
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
        print("[fixes_batch5] Obras: editarEtapa inserida")
    else:
        print("[fixes_batch5] Obras: string _OLD_NOVA nao encontrada")

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
        "    else { alert('Erro ao salvar edição.'); }\n"
        "    return;\n"
        "  }\n"
        "  const r = await fetch('/ferramentas/obras/' + OBRA_ID + '/etapa/nova', {"
    )
    if _OLD_SAVE in tpl:
        tpl = tpl.replace(_OLD_SAVE, _NEW_SAVE, 1)
        changed = True
        print("[fixes_batch5] Obras: salvarEtapa com edit mode")
    else:
        print("[fixes_batch5] Obras: string _OLD_SAVE nao encontrada")

    if changed:
        TEMPLATES["ferramenta_obras_cronograma.html"] = tpl
    else:
        print("[fixes_batch5] Obras editar: nenhuma alteracao aplicada")


_b5_patch_obras_editar()


def _b5_fix_popover_timing() -> None:
    tpl = TEMPLATES.get("ferramenta_obras_cronograma.html", "")
    if not tpl or "_kpiInfoPopover" not in tpl:
        print("[fixes_batch5] Popover: _kpiInfoPopover nao encontrado no template")
        return
    if "_b5PopoverDCL" in tpl:
        print("[fixes_batch5] Popover: timing ja corrigido")
        return

    _OLD_SCRIPT = (
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
    _NEW_SCRIPT = (
        "<!-- _b5PopoverDCL -->\n"
        "<script>\n"
        "document.addEventListener('DOMContentLoaded', function(){\n"
        "  const pop = document.getElementById('_kpiInfoPopover');\n"
        "  if (!pop) return;\n"
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
        "});\n"
        "</script>"
    )
    if _OLD_SCRIPT in tpl:
        tpl = tpl.replace(_OLD_SCRIPT, _NEW_SCRIPT, 1)
        TEMPLATES["ferramenta_obras_cronograma.html"] = tpl
        print("[fixes_batch5] Popover: IIFE substituido por DOMContentLoaded")
    else:
        print("[fixes_batch5] Popover: script IIFE nao encontrado (talvez ja corrigido)")


_b5_fix_popover_timing()


def _b5_expose_augur_sessoes() -> None:
    tpl = TEMPLATES.get("base.html", "")
    if not tpl or "_b5AugurWindow" in tpl:
        return

    _OLD_END = "  augurCarregarSessoes();\n})();\n</script>"
    _NEW_END = (
        "  augurCarregarSessoes();\n"
        "  window.augurCarregarSessoes = augurCarregarSessoes;\n"
        "  // _b5AugurWindow\n"
        "})();\n"
        "</script>"
    )
    if _OLD_END in tpl:
        tpl = tpl.replace(_OLD_END, _NEW_END, 1)
        TEMPLATES["base.html"] = tpl
        print("[fixes_batch5] Augur: augurCarregarSessoes exposta em window")
    else:
        print("[fixes_batch5] Augur: padrao IIFE nao encontrado em base.html")


_b5_expose_augur_sessoes()


def _b5_fix_base_conhecimento() -> None:
    try:
        import ai_assistant.assistant as _ast_b5
        if getattr(_ast_b5._format_client_context, '_b5kb', False):
            print("[fixes_batch5] Base de conhecimento: ja patcheado")
            return

        _orig_fmt_b5 = _ast_b5._format_client_context

        def _fmt_com_kb_b5(client_data: dict) -> str:
            ctx = _orig_fmt_b5(client_data)
            base = client_data.get("base_conhecimento", [])
            if base and "BASE DE CONHECIMENTO DO CLIENTE" not in ctx:
                ctx += "\n\n=== BASE DE CONHECIMENTO DO CLIENTE ===\n"
                ctx += "Documentos fornecidos. Consulte o conteudo abaixo para responder perguntas sobre eles.\n"
                for doc in base:
                    ctx += f"\n--- {doc.get('nome', 'Documento')} ({doc.get('data', '')}) ---\n"
                    if doc.get("descricao"):
                        ctx += f"Descricao: {doc['descricao']}\n"
                    ctx += f"{doc.get('conteudo', '')[:2500]}\n"
            return ctx

        _fmt_com_kb_b5._b5kb = True
        _ast_b5._format_client_context = _fmt_com_kb_b5
        print("[fixes_batch5] Base de conhecimento: _format_client_context patcheada com sucesso")
    except Exception as _e_b5:
        print(f"[fixes_batch5] Base de conhecimento: erro ao patchear: {_e_b5}")


def _b5_fix_buscar_base() -> None:
    import re as _re_b5bk

    def _buscar_base_conhecimento(session, company_id: int, client_id: int, pergunta: str) -> list:
        try:
            from sqlmodel import select as _sel_b5bk
            docs = session.exec(
                _sel_b5bk(BaseConhecimento)
                .where(
                    BaseConhecimento.company_id == company_id,
                    BaseConhecimento.client_id  == client_id,
                )
                .order_by(BaseConhecimento.id.desc())
                .limit(20)
            ).all()

            if not docs:
                return []

            if len(docs) <= 5:
                return list(docs)

            palavras = set(_re_b5bk.findall(r'\w{4,}', pergunta.lower()))
            relevantes = []
            for doc in docs:
                texto_busca = f"{doc.nome} {doc.descricao} {(doc.conteudo_texto or '')[:500]}".lower()
                score = sum(1 for p in palavras if p in texto_busca)
                if score > 0:
                    relevantes.append((score, doc))

            relevantes.sort(key=lambda x: x[0], reverse=True)
            return [r[1] for r in relevantes[:3]] if relevantes else list(docs[:3])
        except Exception as _eb5:
            print(f"[fixes_batch5] buscar_base: {_eb5}")
            return []

    globals()["_buscar_base_conhecimento"] = _buscar_base_conhecimento
    print("[fixes_batch5] _buscar_base_conhecimento atualizada")


_b5_fix_base_conhecimento()
_b5_fix_buscar_base()

print("[fixes_batch5] Todos os fixes do batch5 aplicados.")
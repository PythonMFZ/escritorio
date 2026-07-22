# =============================================================================
# Gestão de Obras — Reordenar etapas (drag-and-drop) + Aplicar Correção
# =============================================================================

from sqlalchemy import text as _sat
from fastapi.responses import Response as _Response

# ── Migração: orcado_original_rs ──────────────────────────────────────────────

try:
    with engine.begin() as _c:
        _c.execute(_sat(
            "ALTER TABLE obraetapa ADD COLUMN IF NOT EXISTS orcado_original_rs DOUBLE PRECISION DEFAULT 0"
        ))
        _c.execute(_sat(
            "ALTER TABLE obrasubetapa ADD COLUMN IF NOT EXISTS orcado_original_rs DOUBLE PRECISION DEFAULT 0"
        ))
    print("[obras_reorder] Migration orcado_original_rs OK")
except Exception as _e:
    print(f"[obras_reorder] Migration skip: {_e}")


# ── Rota: reordenar etapa ─────────────────────────────────────────────────────

@app.post("/ferramentas/obras/etapa/{etapa_id}/reordenar")
@require_login
async def obras_etapa_reordenar(etapa_id: int, request: Request,
                                 session: Session = Depends(get_session)):
    ctx = get_tenant_context(request, session)
    if not ctx:
        return JSONResponse({"ok": False}, status_code=401)
    body = await request.json()
    etapa = session.get(ObraEtapa, etapa_id)
    if not etapa or etapa.obra_id != body.get("obra_id"):
        return JSONResponse({"ok": False}, status_code=404)

    ids_ordenados = body.get("ids", [])
    for idx, eid in enumerate(ids_ordenados):
        e = session.get(ObraEtapa, int(eid))
        if e and e.fase_id == etapa.fase_id:
            e.ordem = idx
            session.add(e)
    session.commit()
    return JSONResponse({"ok": True})


# ── Rota: aplicar correção a etapas futuras ───────────────────────────────────

@app.post("/ferramentas/obras/{obra_id}/aplicar-correcao")
@require_login
async def obras_aplicar_correcao(obra_id: int, request: Request,
                                   session: Session = Depends(get_session)):
    ctx = get_tenant_context(request, session)
    if not ctx:
        return JSONResponse({"ok": False}, status_code=401)
    obra = _get_obra_or_404(session, obra_id, ctx.company.id)
    if not obra:
        return JSONResponse({"ok": False}, status_code=404)

    body = await request.json()
    tipo = body.get("tipo", "pct")
    valor = float(body.get("valor", 0))
    aplicar_subetapas = bool(body.get("aplicar_subetapas", True))

    fases = session.exec(select(ObraFase).where(ObraFase.obra_id == obra_id)).all()
    fase_ids = [f.id for f in fases]
    etapas = session.exec(select(ObraEtapa).where(ObraEtapa.fase_id.in_(fase_ids))).all()

    atualizadas = 0
    for etapa in etapas:
        apt = session.exec(
            select(ObraApontamento)
            .where(ObraApontamento.etapa_id == etapa.id)
            .order_by(ObraApontamento.created_at.desc())
            .limit(1)
        ).first()
        if apt and apt.fisico_pct > 0:
            continue

        orig = getattr(etapa, "orcado_original_rs", None)
        if not orig or orig == 0:
            try:
                etapa.orcado_original_rs = etapa.orcado_rs
            except Exception:
                pass

        base = etapa.orcado_original_rs if (getattr(etapa, "orcado_original_rs", 0) or 0) > 0 else etapa.orcado_rs
        etapa.orcado_rs = round(base * (1 + valor / 100), 2) if tipo == "pct" else round(base + valor, 2)
        session.add(etapa)
        atualizadas += 1

        if aplicar_subetapas:
            try:
                for se in session.exec(select(ObraSubEtapa).where(ObraSubEtapa.etapa_id == etapa.id)).all():
                    se_orig = getattr(se, "orcado_original_rs", None)
                    if not se_orig or se_orig == 0:
                        try:
                            se.orcado_original_rs = se.orcado_rs
                        except Exception:
                            pass
                    se_base = (getattr(se, "orcado_original_rs", 0) or 0)
                    se_base = se_base if se_base > 0 else se.orcado_rs
                    se.orcado_rs = round(se_base * (1 + valor / 100), 2) if tipo == "pct" else round(se_base + valor, 2)
                    session.add(se)
            except Exception:
                pass

    session.commit()
    return JSONResponse({"ok": True, "atualizadas": atualizadas})


# ── Rota: serve o JS de DnD + Expand/Colapsar + Reajuste ─────────────────────

# Todos os caracteres fora do ASCII usam \uXXXX para evitar problema de encoding
_OBRAS_REORDER_JS = (
    "/* obras-reorder: drag-and-drop + expand/colapsar sub-etapas + reajuste */\n"
    "(function() {\n"
    "\n"
    "  // Sub-etapas ficam dentro de div#se-body-{etapa_id}, nao como irmaos diretos\n"
    "  function _getWrapper(etapaEl) {\n"
    "    var id = etapaEl.id.replace('etapa-row-', '');\n"
    "    return document.getElementById('se-body-' + id);\n"
    "  }\n"
    "\n"
    "  /* ---------- Modal Reajuste ---------- */\n"
    "  if (!document.getElementById('modalCorrecao')) {\n"
    "    var _m = document.createElement('div');\n"
    "    _m.innerHTML = '<div class=\"modal fade\" id=\"modalCorrecao\" tabindex=\"-1\">'\n"
    "      + '<div class=\"modal-dialog modal-sm\"><div class=\"modal-content\">'\n"
    "      + '<div class=\"modal-header\" style=\"background:#f97316;color:#fff;\">'\n"
    "      + '<h5 class=\"modal-title\">\u{1F4D0} Reajuste de Orçamento</h5>'\n"
    "      + '<button type=\"button\" class=\"btn-close btn-close-white\" data-bs-dismiss=\"modal\"></button>'\n"
    "      + '</div><div class=\"modal-body\">'\n"
    "      + '<p style=\"font-size:.83rem;color:#64748b;\">Aplica reajuste a todas as etapas <b>ainda não executadas</b> (físico = 0%). O valor original fica salvo.</p>'\n"
    "      + '<div class=\"mb-3\"><label class=\"form-label fw-semibold\">Tipo</label>'\n"
    "      + '<select id=\"correcaoTipo\" class=\"form-select\">'\n"
    "      + '<option value=\"pct\">% sobre o orçamento original</option>'\n"
    "      + '<option value=\"rs\">R$ fixo sobre o orçamento original</option>'\n"
    "      + '</select></div>'\n"
    "      + '<div class=\"mb-3\"><label class=\"form-label fw-semibold\" id=\"correcaoLabel\">Percentual (%)</label>'\n"
    "      + '<input type=\"number\" id=\"correcaoValor\" class=\"form-control\" step=\"0.01\" placeholder=\"Ex: 5 para +5%\">'\n"
    "      + '<div class=\"form-text\">Negativo para reduzir.</div></div>'\n"
    "      + '<div class=\"form-check mb-2\"><input class=\"form-check-input\" type=\"checkbox\" id=\"correcaoSubetapas\" checked>'\n"
    "      + '<label class=\"form-check-label\" for=\"correcaoSubetapas\">Aplicar também às sub-etapas</label></div>'\n"
    "      + '</div><div class=\"modal-footer\">'\n"
    "      + '<button type=\"button\" class=\"btn btn-secondary\" data-bs-dismiss=\"modal\">Cancelar</button>'\n"
    "      + '<button type=\"button\" class=\"btn btn-warning\" onclick=\"salvarCorrecao()\">Aplicar</button>'\n"
    "      + '</div></div></div></div>';\n"
    "    document.body.appendChild(_m.firstChild);\n"
    "  }\n"
    "\n"
    "  var tipoSel = document.getElementById('correcaoTipo');\n"
    "  if (tipoSel) tipoSel.addEventListener('change', function() {\n"
    "    document.getElementById('correcaoLabel').textContent =\n"
    "      this.value === 'pct' ? 'Percentual (%)' : 'Valor em R$';\n"
    "  });\n"
    "\n"
    "  /* ---------- Botao Reajuste no cabecalho ---------- */\n"
    "  var novaFaseBtn = document.querySelector('[onclick*=\"abrirNovaFase\"]');\n"
    "  if (novaFaseBtn && !document.getElementById('btnCorrecaoObra')) {\n"
    "    var rbtn = document.createElement('button');\n"
    "    rbtn.id = 'btnCorrecaoObra';\n"
    "    rbtn.className = 'btn btn-warning btn-sm no-print';\n"
    "    rbtn.style.fontSize = '.8rem';\n"
    "    rbtn.title = 'Reajustar orçamento de etapas não executadas';\n"
    "    rbtn.onclick = function() { abrirModalCorrecao(); };\n"
    "    rbtn.innerHTML = '\u{1F4D0} Reajuste';\n"
    "    novaFaseBtn.parentNode.insertBefore(rbtn, novaFaseBtn);\n"
    "  }\n"
    "\n"
    "  /* ---------- Drag-and-drop ---------- */\n"
    "  var _dragEl = null, _dragOver = null, _dragWrapper = null;\n"
    "\n"
    "  function _dragStart(e) {\n"
    "    _dragEl = e.currentTarget;\n"
    "    _dragWrapper = _getWrapper(_dragEl);\n"
    "    e.dataTransfer.effectAllowed = 'move';\n"
    "    _dragEl.style.opacity = '0.4';\n"
    "    if (_dragWrapper) _dragWrapper.style.opacity = '0.4';\n"
    "  }\n"
    "  function _dragOver_(e) {\n"
    "    e.preventDefault();\n"
    "    e.dataTransfer.dropEffect = 'move';\n"
    "    var el = e.currentTarget;\n"
    "    if (el !== _dragEl) {\n"
    "      document.querySelectorAll('.cr-etapa').forEach(function(x) { x.style.borderTop = ''; });\n"
    "      el.style.borderTop = '2px solid #6366f1';\n"
    "      _dragOver = el;\n"
    "    }\n"
    "  }\n"
    "  function _dragEnd(e) {\n"
    "    if (_dragEl) _dragEl.style.opacity = '';\n"
    "    if (_dragWrapper) _dragWrapper.style.opacity = '';\n"
    "    document.querySelectorAll('.cr-etapa').forEach(function(el) { el.style.borderTop = ''; });\n"
    "  }\n"
    "  function _drop(e) {\n"
    "    e.preventDefault();\n"
    "    document.querySelectorAll('.cr-etapa').forEach(function(el) { el.style.borderTop = ''; });\n"
    "    if (!_dragEl || !_dragOver || _dragEl === _dragOver) return;\n"
    "    if (_dragEl.parentNode !== _dragOver.parentNode) {\n"
    "      alert('Mova etapas apenas dentro da mesma fase.'); return;\n"
    "    }\n"
    "    var parent = _dragOver.parentNode;\n"
    "    // Move a etapa antes do alvo\n"
    "    parent.insertBefore(_dragEl, _dragOver);\n"
    "    _dragEl.style.opacity = '';\n"
    "    // Move o wrapper de sub-etapas logo apos a etapa\n"
    "    if (_dragWrapper) {\n"
    "      parent.insertBefore(_dragWrapper, _dragEl.nextSibling);\n"
    "      _dragWrapper.style.opacity = '';\n"
    "    }\n"
    "    var etapaId = _dragEl.id.replace('etapa-row-', '');\n"
    "    var ids = Array.from(parent.querySelectorAll(':scope > .cr-etapa')).map(function(el) {\n"
    "      return parseInt(el.id.replace('etapa-row-', ''));\n"
    "    });\n"
    "    fetch('/ferramentas/obras/etapa/' + etapaId + '/reordenar', {\n"
    "      method: 'POST', headers: {'Content-Type': 'application/json'},\n"
    "      body: JSON.stringify({ obra_id: OBRA_ID, ids: ids })\n"
    "    }).catch(function(err) { console.error('Erro reordenar:', err); });\n"
    "    _dragEl = null; _dragOver = null; _dragWrapper = null;\n"
    "  }\n"
    "\n"
    "  /* ---------- Expand / Colapsar ---------- */\n"
    "  function _toggle(etapaEl, btn) {\n"
    "    var wrapper = _getWrapper(etapaEl);\n"
    "    if (!wrapper) return;\n"
    "    var collapsed = wrapper.style.display === 'none';\n"
    "    wrapper.style.display = collapsed ? '' : 'none';\n"
    "    btn.textContent = collapsed ? '▼' : '▶';\n"
    "    btn.title = collapsed ? 'Recolher sub-etapas' : 'Expandir sub-etapas';\n"
    "  }\n"
    "\n"
    "  /* ---------- Inicializa etapas ---------- */\n"
    "  document.querySelectorAll('.cr-etapa').forEach(function(el) {\n"
    "    el.draggable = true;\n"
    "    var firstDiv = el.querySelector(':scope > div');\n"
    "    if (firstDiv && !firstDiv.querySelector('.dnd-handle')) {\n"
    "      var wrapper = _getWrapper(el);\n"
    "      if (wrapper) {\n"
    "        var tb = document.createElement('span');\n"
    "        tb.className = 'sub-toggle';\n"
    "        tb.textContent = '▼';\n"
    "        tb.title = 'Recolher sub-etapas';\n"
    "        tb.style.cssText = 'cursor:pointer;color:#6366f1;font-size:.75rem;user-select:none;margin-right:.25rem;vertical-align:middle;';\n"
    "        (function(etapaEl, toggleBtn) {\n"
    "          toggleBtn.addEventListener('click', function(ev) {\n"
    "            ev.stopPropagation();\n"
    "            _toggle(etapaEl, toggleBtn);\n"
    "          });\n"
    "        })(el, tb);\n"
    "        firstDiv.insertBefore(tb, firstDiv.firstChild);\n"
    "      }\n"
    "      var h = document.createElement('span');\n"
    "      h.className = 'dnd-handle';\n"
    "      h.textContent = '⋮';\n"
    "      h.title = 'Arrastar para reordenar';\n"
    "      h.style.cssText = 'cursor:grab;color:#cbd5e1;font-size:1rem;user-select:none;margin-right:.3rem;vertical-align:middle;';\n"
    "      firstDiv.insertBefore(h, firstDiv.firstChild);\n"
    "    }\n"
    "    el.addEventListener('dragstart', _dragStart);\n"
    "    el.addEventListener('dragover', _dragOver_);\n"
    "    el.addEventListener('drop', _drop);\n"
    "    el.addEventListener('dragend', _dragEnd);\n"
    "  });\n"
    "\n"
    "})();\n"
    "\n"
    "function abrirModalCorrecao() {\n"
    "  new bootstrap.Modal(document.getElementById('modalCorrecao')).show();\n"
    "}\n"
    "async function salvarCorrecao() {\n"
    "  var tipo = document.getElementById('correcaoTipo').value;\n"
    "  var valor = parseFloat(document.getElementById('correcaoValor').value);\n"
    "  var subs = document.getElementById('correcaoSubetapas').checked;\n"
    "  if (isNaN(valor)) { alert('Informe o valor do reajuste.'); return; }\n"
    "  var r = await fetch('/ferramentas/obras/' + OBRA_ID + '/aplicar-correcao', {\n"
    "    method: 'POST', headers: {'Content-Type': 'application/json'},\n"
    "    body: JSON.stringify({ tipo: tipo, valor: valor, aplicar_subetapas: subs })\n"
    "  });\n"
    "  var d = await r.json();\n"
    "  if (d.ok) {\n"
    "    bootstrap.Modal.getInstance(document.getElementById('modalCorrecao')).hide();\n"
    "    alert(d.atualizadas + ' etapa(s) atualizadas. Recarregando...');\n"
    "    location.reload();\n"
    "  } else { alert('Erro ao aplicar reajuste.'); }\n"
    "}\n"
)

@app.get("/ferramentas/obras-reorder.js")
async def obras_reorder_js():
    return _Response(
        content=_OBRAS_REORDER_JS.encode("utf-8"),
        media_type="application/javascript; charset=utf-8"
    )


# ── Patch do template: injeta apenas <script src> usando anchor estável ───────

def _patch_obras_reorder_correcao():
    import re as _re
    tpl = TEMPLATES.get("ferramenta_obras_cronograma.html", "")
    if not tpl:
        return
    if "_reorderCorrecaoV8" in tpl:
        return

    # Limpa qualquer injeção anterior
    tpl = _re.sub(r'<!-- _obrasReorderStart -->.*?<!-- _obrasReorderEnd -->', '', tpl, flags=_re.DOTALL)
    tpl = _re.sub(r'<script>\s*// ── Reorder \+.*?</script>', '', tpl, flags=_re.DOTALL)
    tpl = _re.sub(r'<!-- Modal Corre[cç][aã]o -->.*?(?=\n\{[%#]|\Z)', '', tpl, flags=_re.DOTALL)
    tpl = _re.sub(r'<script src="/ferramentas/obras[-/]reorder\.js"[^>]*></script>\s*', '', tpl)
    for _sv in ['V1', 'V2', 'V3', 'V4', 'V5', 'V6', 'V7']:
        tpl = tpl.replace('{# _reorderCorrecao' + _sv + ' #}\n', '')
        tpl = tpl.replace('{# _reorderCorrecao' + _sv + ' #}', '')

    # Injeta <script src> antes do {% endblock %}
    _TAG = '\n<script src="/ferramentas/obras-reorder.js"></script>\n'
    tpl = tpl.replace("{% endblock %}", _TAG + "{# _reorderCorrecaoV8 #}\n{% endblock %}", 1)

    TEMPLATES["ferramenta_obras_cronograma.html"] = tpl
    if hasattr(templates_env.loader, "mapping"):
        templates_env.loader.mapping = TEMPLATES
    print("[obras_reorder_correcao] Template patcheado V8 OK (script src, sub-etapa fix)")


_patch_obras_reorder_correcao()

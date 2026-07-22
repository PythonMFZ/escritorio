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

_OBRAS_REORDER_JS = r"""
/* obras-reorder: drag-and-drop + expand/colapsar sub-etapas + reajuste */
(function() {

  function _getSubs(etapaEl) {
    var subs = [], next = etapaEl.nextElementSibling;
    while (next && next.classList.contains('cr-subetapa')) {
      subs.push(next); next = next.nextElementSibling;
    }
    return subs;
  }

  /* ---------- Modal Reajuste ---------- */
  if (!document.getElementById('modalCorrecao')) {
    var _m = document.createElement('div');
    _m.innerHTML = '<div class="modal fade" id="modalCorrecao" tabindex="-1">'
      + '<div class="modal-dialog modal-sm"><div class="modal-content">'
      + '<div class="modal-header" style="background:#f97316;color:#fff;">'
      + '<h5 class="modal-title">\u{1F4D0} Reajuste de Orçamento</h5>'
      + '<button type="button" class="btn-close btn-close-white" data-bs-dismiss="modal"></button>'
      + '</div><div class="modal-body">'
      + '<p style="font-size:.83rem;color:#64748b;">Aplica reajuste a todas as etapas <b>ainda não executadas</b> (físico = 0%). O valor original fica salvo.</p>'
      + '<div class="mb-3"><label class="form-label fw-semibold">Tipo</label>'
      + '<select id="correcaoTipo" class="form-select">'
      + '<option value="pct">% sobre o orçamento original</option>'
      + '<option value="rs">R$ fixo sobre o orçamento original</option>'
      + '</select></div>'
      + '<div class="mb-3"><label class="form-label fw-semibold" id="correcaoLabel">Percentual (%)</label>'
      + '<input type="number" id="correcaoValor" class="form-control" step="0.01" placeholder="Ex: 5 para +5%">'
      + '<div class="form-text">Negativo para reduzir.</div></div>'
      + '<div class="form-check mb-2"><input class="form-check-input" type="checkbox" id="correcaoSubetapas" checked>'
      + '<label class="form-check-label" for="correcaoSubetapas">Aplicar também às sub-etapas</label></div>'
      + '</div><div class="modal-footer">'
      + '<button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Cancelar</button>'
      + '<button type="button" class="btn btn-warning" onclick="salvarCorrecao()">Aplicar</button>'
      + '</div></div></div></div>';
    document.body.appendChild(_m.firstChild);
  }

  var tipoSel = document.getElementById('correcaoTipo');
  if (tipoSel) tipoSel.addEventListener('change', function() {
    document.getElementById('correcaoLabel').textContent =
      this.value === 'pct' ? 'Percentual (%)' : 'Valor em R$';
  });

  /* ---------- Botao Reajuste no cabecalho ---------- */
  var novaFaseBtn = document.querySelector('[onclick*="abrirNovaFase"]');
  if (novaFaseBtn && !document.getElementById('btnCorrecaoObra')) {
    var rbtn = document.createElement('button');
    rbtn.id = 'btnCorrecaoObra';
    rbtn.className = 'btn btn-warning btn-sm no-print';
    rbtn.style.fontSize = '.8rem';
    rbtn.title = 'Reajustar orçamento de etapas não executadas';
    rbtn.onclick = function() { abrirModalCorrecao(); };
    rbtn.innerHTML = '\u{1F4D0} Reajuste';
    novaFaseBtn.parentNode.insertBefore(rbtn, novaFaseBtn);
  }

  /* ---------- Drag-and-drop ---------- */
  var _dragEl = null, _dragOver = null, _dragSubs = [];

  function _dragStart(e) {
    _dragEl = e.currentTarget;
    _dragSubs = _getSubs(_dragEl);
    e.dataTransfer.effectAllowed = 'move';
    _dragEl.style.opacity = '0.4';
    _dragSubs.forEach(function(s) { s.style.opacity = '0.4'; });
  }
  function _dragOver_(e) {
    e.preventDefault();
    e.dataTransfer.dropEffect = 'move';
    var el = e.currentTarget;
    if (el !== _dragEl) {
      document.querySelectorAll('.cr-etapa').forEach(function(x) { x.style.borderTop = ''; });
      el.style.borderTop = '2px solid #6366f1';
      _dragOver = el;
    }
  }
  function _dragEnd(e) {
    if (_dragEl) _dragEl.style.opacity = '';
    _dragSubs.forEach(function(s) { s.style.opacity = ''; });
    document.querySelectorAll('.cr-etapa').forEach(function(el) { el.style.borderTop = ''; });
  }
  function _drop(e) {
    e.preventDefault();
    document.querySelectorAll('.cr-etapa').forEach(function(el) { el.style.borderTop = ''; });
    if (!_dragEl || !_dragOver || _dragEl === _dragOver) return;
    if (_dragEl.parentNode !== _dragOver.parentNode) {
      alert('Mova etapas apenas dentro da mesma fase.'); return;
    }
    var parent = _dragOver.parentNode;
    parent.insertBefore(_dragEl, _dragOver);
    _dragEl.style.opacity = '';
    var anchor = _dragEl;
    _dragSubs.forEach(function(sub) {
      anchor.parentNode.insertBefore(sub, anchor.nextSibling);
      sub.style.opacity = '';
      anchor = sub;
    });
    var etapaId = _dragEl.id.replace('etapa-row-', '');
    var ids = Array.from(parent.querySelectorAll(':scope > .cr-etapa')).map(function(el) {
      return parseInt(el.id.replace('etapa-row-', ''));
    });
    fetch('/ferramentas/obras/etapa/' + etapaId + '/reordenar', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ obra_id: OBRA_ID, ids: ids })
    }).catch(function(err) { console.error('Erro reordenar:', err); });
    _dragEl = null; _dragOver = null; _dragSubs = [];
  }

  /* ---------- Expand / Colapsar ---------- */
  function _toggle(etapaEl, btn) {
    var subs = _getSubs(etapaEl);
    if (!subs.length) return;
    var collapsed = subs[0].style.display === 'none';
    subs.forEach(function(s) { s.style.display = collapsed ? '' : 'none'; });
    btn.textContent = collapsed ? '▼' : '▶';
    btn.title = collapsed ? 'Recolher sub-etapas' : 'Expandir sub-etapas';
  }

  /* ---------- Inicializa etapas ---------- */
  document.querySelectorAll('.cr-etapa').forEach(function(el) {
    el.draggable = true;
    var firstDiv = el.querySelector(':scope > div');
    if (firstDiv && !firstDiv.querySelector('.dnd-handle')) {
      var subs = _getSubs(el);
      if (subs.length) {
        var tb = document.createElement('span');
        tb.className = 'sub-toggle';
        tb.textContent = '▼';
        tb.title = 'Recolher sub-etapas';
        tb.style.cssText = 'cursor:pointer;color:#6366f1;font-size:.75rem;user-select:none;margin-right:.25rem;vertical-align:middle;';
        (function(etapaEl, toggleBtn) {
          toggleBtn.addEventListener('click', function(ev) {
            ev.stopPropagation();
            _toggle(etapaEl, toggleBtn);
          });
        })(el, tb);
        firstDiv.insertBefore(tb, firstDiv.firstChild);
      }
      var h = document.createElement('span');
      h.className = 'dnd-handle';
      h.textContent = '⋮';
      h.title = 'Arrastar para reordenar';
      h.style.cssText = 'cursor:grab;color:#cbd5e1;font-size:1rem;user-select:none;margin-right:.3rem;vertical-align:middle;';
      firstDiv.insertBefore(h, firstDiv.firstChild);
    }
    el.addEventListener('dragstart', _dragStart);
    el.addEventListener('dragover', _dragOver_);
    el.addEventListener('drop', _drop);
    el.addEventListener('dragend', _dragEnd);
  });

})();

function abrirModalCorrecao() {
  new bootstrap.Modal(document.getElementById('modalCorrecao')).show();
}
async function salvarCorrecao() {
  var tipo = document.getElementById('correcaoTipo').value;
  var valor = parseFloat(document.getElementById('correcaoValor').value);
  var subs = document.getElementById('correcaoSubetapas').checked;
  if (isNaN(valor)) { alert('Informe o valor do reajuste.'); return; }
  var r = await fetch('/ferramentas/obras/' + OBRA_ID + '/aplicar-correcao', {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({ tipo: tipo, valor: valor, aplicar_subetapas: subs })
  });
  var d = await r.json();
  if (d.ok) {
    bootstrap.Modal.getInstance(document.getElementById('modalCorrecao')).hide();
    alert(d.atualizadas + ' etapa(s) atualizadas. Recarregando...');
    location.reload();
  } else { alert('Erro ao aplicar reajuste.'); }
}
"""

@app.get("/ferramentas/obras-reorder.js")
async def obras_reorder_js():
    return _Response(content=_OBRAS_REORDER_JS, media_type="application/javascript")


# ── Patch do template: injeta apenas <script src> usando anchor estável ───────

def _patch_obras_reorder_correcao():
    import re as _re
    tpl = TEMPLATES.get("ferramenta_obras_cronograma.html", "")
    if not tpl:
        return
    if "_reorderCorrecaoV7" in tpl:
        return

    # Limpa qualquer injeção anterior
    tpl = _re.sub(r'<!-- _obrasReorderStart -->.*?<!-- _obrasReorderEnd -->', '', tpl, flags=_re.DOTALL)
    tpl = _re.sub(r'<script>\s*// ── Reorder \+.*?</script>', '', tpl, flags=_re.DOTALL)
    tpl = _re.sub(r'<!-- Modal Corre[cç][aã]o -->.*?(?=\n\{[%#]|\Z)', '', tpl, flags=_re.DOTALL)
    tpl = _re.sub(r'<script src="/ferramentas/obras/reorder\.js"[^>]*></script>\s*', '', tpl)
    for _sv in ['V1', 'V2', 'V3', 'V4', 'V5', 'V6']:
        tpl = tpl.replace('{# _reorderCorrecao' + _sv + ' #}\n', '')
        tpl = tpl.replace('{# _reorderCorrecao' + _sv + ' #}', '')

    # Injeta <script src> antes do {% endblock %}
    _TAG = '\n<script src="/ferramentas/obras-reorder.js"></script>\n'
    tpl = tpl.replace("{% endblock %}", _TAG + "{# _reorderCorrecaoV7 #}\n{% endblock %}", 1)

    TEMPLATES["ferramenta_obras_cronograma.html"] = tpl
    if hasattr(templates_env.loader, "mapping"):
        templates_env.loader.mapping = TEMPLATES
    print("[obras_reorder_correcao] Template patcheado V7 OK (script src)")


_patch_obras_reorder_correcao()

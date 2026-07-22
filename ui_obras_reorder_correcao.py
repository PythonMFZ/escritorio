# =============================================================================
# Gestão de Obras — Reordenar etapas (drag-and-drop) + Aplicar Correção
# =============================================================================

from sqlalchemy import text as _sat

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
    tipo = body.get("tipo", "pct")        # "pct" | "rs"
    valor = float(body.get("valor", 0))
    aplicar_subetapas = bool(body.get("aplicar_subetapas", True))

    fases = session.exec(
        select(ObraFase).where(ObraFase.obra_id == obra_id)
    ).all()
    fase_ids = [f.id for f in fases]
    etapas = session.exec(
        select(ObraEtapa).where(ObraEtapa.fase_id.in_(fase_ids))
    ).all()

    atualizadas = 0
    for etapa in etapas:
        apt = session.exec(
            select(ObraApontamento)
            .where(ObraApontamento.etapa_id == etapa.id)
            .order_by(ObraApontamento.created_at.desc())
            .limit(1)
        ).first()
        fisico = apt.fisico_pct if apt else 0
        if fisico > 0:
            continue

        orig = getattr(etapa, "orcado_original_rs", None)
        if not orig or orig == 0:
            try:
                etapa.orcado_original_rs = etapa.orcado_rs
            except Exception:
                pass

        base = etapa.orcado_original_rs if (getattr(etapa, "orcado_original_rs", 0) or 0) > 0 else etapa.orcado_rs
        if tipo == "pct":
            etapa.orcado_rs = round(base * (1 + valor / 100), 2)
        else:
            etapa.orcado_rs = round(base + valor, 2)
        session.add(etapa)
        atualizadas += 1

        if aplicar_subetapas:
            try:
                subetapas = session.exec(
                    select(ObraSubEtapa).where(ObraSubEtapa.etapa_id == etapa.id)
                ).all()
                for se in subetapas:
                    se_orig = getattr(se, "orcado_original_rs", None)
                    if not se_orig or se_orig == 0:
                        try:
                            se.orcado_original_rs = se.orcado_rs
                        except Exception:
                            pass
                    se_base = (getattr(se, "orcado_original_rs", 0) or 0)
                    se_base = se_base if se_base > 0 else se.orcado_rs
                    if tipo == "pct":
                        se.orcado_rs = round(se_base * (1 + valor / 100), 2)
                    else:
                        se.orcado_rs = round(se_base + valor, 2)
                    session.add(se)
            except Exception:
                pass

    session.commit()
    return JSONResponse({"ok": True, "atualizadas": atualizadas})


# ── Patch do template ─────────────────────────────────────────────────────────
# V2: tudo injetado via JS para não depender de anchor HTML frágil

def _patch_obras_reorder_correcao():
    tpl = TEMPLATES.get("ferramenta_obras_cronograma.html", "")
    if not tpl or "_reorderCorrecaoV4" in tpl:
        return

    _INJECT = """
<script>
// ── Reorder + Expand/Colapsar + Reajuste V4 ───────────────────────────────
(function() {

  // ── Helpers ──────────────────────────────────────────────────────────────
  function _getSubEtapas(etapaEl) {
    // Retorna todos .cr-subetapa irmãos imediatos após a etapa (para quando acha outra .cr-etapa)
    const subs = [];
    let next = etapaEl.nextElementSibling;
    while (next && next.classList.contains('cr-subetapa')) {
      subs.push(next);
      next = next.nextElementSibling;
    }
    return subs;
  }

  // ── Modal Reajuste ────────────────────────────────────────────────────────
  if (!document.getElementById('modalCorrecao')) {
    document.body.insertAdjacentHTML('beforeend', `
<div class="modal fade" id="modalCorrecao" tabindex="-1">
  <div class="modal-dialog modal-sm">
    <div class="modal-content">
      <div class="modal-header" style="background:#f97316;color:#fff;">
        <h5 class="modal-title">&#128208; Reajuste de Or&#231;amento</h5>
        <button type="button" class="btn-close btn-close-white" data-bs-dismiss="modal"></button>
      </div>
      <div class="modal-body">
        <p style="font-size:.83rem;color:#64748b;">Aplica reajuste a todas as etapas <b>ainda n&#227;o executadas</b> (f&#237;sico = 0%). O valor original fica salvo para n&#227;o acumular em reaplicac&#807;&#245;es.</p>
        <div class="mb-3">
          <label class="form-label fw-semibold">Tipo</label>
          <select id="correcaoTipo" class="form-select">
            <option value="pct">% sobre o or&#231;amento original</option>
            <option value="rs">R$ fixo sobre o or&#231;amento original</option>
          </select>
        </div>
        <div class="mb-3">
          <label class="form-label fw-semibold" id="correcaoLabel">Percentual (%)</label>
          <input type="number" id="correcaoValor" class="form-control" step="0.01" placeholder="Ex: 5 para +5%">
          <div class="form-text">Negativo para reduzir. Ex: -3 para -3%.</div>
        </div>
        <div class="form-check mb-2">
          <input class="form-check-input" type="checkbox" id="correcaoSubetapas" checked>
          <label class="form-check-label" for="correcaoSubetapas">Aplicar tamb&#233;m &#224;s sub-etapas</label>
        </div>
      </div>
      <div class="modal-footer">
        <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Cancelar</button>
        <button type="button" class="btn btn-warning" onclick="salvarCorrecao()">Aplicar</button>
      </div>
    </div>
  </div>
</div>`);
  }

  const tipoSel = document.getElementById('correcaoTipo');
  if (tipoSel) tipoSel.addEventListener('change', function() {
    document.getElementById('correcaoLabel').textContent =
      this.value === 'pct' ? 'Percentual (%)' : 'Valor em R$';
  });

  // ── Botão Reajuste no cabeçalho ───────────────────────────────────────────
  const novaFaseBtn = document.querySelector('[onclick*="abrirNovaFase"]');
  if (novaFaseBtn && !document.getElementById('btnCorrecaoObra')) {
    const btn = document.createElement('button');
    btn.id = 'btnCorrecaoObra';
    btn.className = 'btn btn-warning btn-sm no-print';
    btn.style.fontSize = '.8rem';
    btn.title = 'Reajustar or\\u00e7amento de etapas n\\u00e3o executadas';
    btn.onclick = abrirModalCorrecao;
    btn.innerHTML = '&#128208; Reajuste';
    novaFaseBtn.parentNode.insertBefore(btn, novaFaseBtn);
  }

  // ── Drag-and-drop ─────────────────────────────────────────────────────────
  let _dragEtapa = null, _dragOverEtapa = null, _dragSubs = [];

  function obrasDragStart(e) {
    _dragEtapa = e.currentTarget;
    // Coleta sub-etapas mesmo se estiverem ocultas (expandir/colapsar)
    _dragSubs = _getSubEtapas(_dragEtapa);
    e.dataTransfer.effectAllowed = 'move';
    _dragEtapa.style.opacity = '0.4';
    _dragSubs.forEach(s => { s.style.opacity = '0.4'; });
  }
  function obrasDragOver(e) {
    e.preventDefault();
    e.dataTransfer.dropEffect = 'move';
    const el = e.currentTarget;
    if (el !== _dragEtapa) {
      document.querySelectorAll('.cr-etapa').forEach(x => x.style.borderTop = '');
      el.style.borderTop = '2px solid #6366f1';
      _dragOverEtapa = el;
    }
  }
  function obrasDragEnd(e) {
    _dragEtapa && (_dragEtapa.style.opacity = '');
    _dragSubs.forEach(s => s.style.opacity = '');
    document.querySelectorAll('.cr-etapa').forEach(el => el.style.borderTop = '');
  }
  async function obrasDrop(e) {
    e.preventDefault();
    document.querySelectorAll('.cr-etapa').forEach(el => el.style.borderTop = '');
    if (!_dragEtapa || !_dragOverEtapa || _dragEtapa === _dragOverEtapa) return;
    if (_dragEtapa.parentNode !== _dragOverEtapa.parentNode) {
      alert('Mova etapas apenas dentro da mesma fase.'); return;
    }
    const parent = _dragOverEtapa.parentNode;
    // Move a etapa pai
    parent.insertBefore(_dragEtapa, _dragOverEtapa);
    _dragEtapa.style.opacity = '';
    // Move sub-etapas filhas logo em seguida, na ordem original
    let anchor = _dragEtapa;
    _dragSubs.forEach(sub => {
      anchor.parentNode.insertBefore(sub, anchor.nextSibling);
      sub.style.opacity = '';
      anchor = sub;
    });
    const etapaId = _dragEtapa.id.replace('etapa-row-', '');
    const ids = [...parent.querySelectorAll(':scope > .cr-etapa')].map(el => parseInt(el.id.replace('etapa-row-', '')));
    try {
      await fetch('/ferramentas/obras/etapa/' + etapaId + '/reordenar', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ obra_id: OBRA_ID, ids })
      });
    } catch(err) { console.error('Erro ao reordenar etapa:', err); }
    _dragEtapa = null; _dragOverEtapa = null; _dragSubs = [];
  }

  // ── Expand / Colapsar sub-etapas ─────────────────────────────────────────
  function _toggleSubEtapas(etapaEl, btn) {
    const subs = _getSubEtapas(etapaEl);
    if (!subs.length) return;
    const collapsed = subs[0].style.display === 'none';
    subs.forEach(s => s.style.display = collapsed ? '' : 'none');
    btn.innerHTML = collapsed ? '&#9660;' : '&#9654;';
    btn.title = collapsed ? 'Recolher sub-etapas' : 'Expandir sub-etapas';
  }

  // ── Inicializa etapas ─────────────────────────────────────────────────────
  document.querySelectorAll('.cr-etapa').forEach(function(el) {
    el.draggable = true;
    const firstDiv = el.querySelector(':scope > div');
    if (firstDiv && !firstDiv.querySelector('.dnd-handle')) {
      const subs = _getSubEtapas(el);

      // Botão expand/colapsar (só se tiver sub-etapas)
      if (subs.length) {
        const toggleBtn = document.createElement('span');
        toggleBtn.className = 'sub-toggle';
        toggleBtn.innerHTML = '&#9660;';
        toggleBtn.title = 'Recolher sub-etapas';
        toggleBtn.style.cssText = 'cursor:pointer;color:#6366f1;font-size:.75rem;user-select:none;display:inline-block;margin-right:.2rem;vertical-align:middle;';
        toggleBtn.addEventListener('click', function(ev) {
          ev.stopPropagation();
          _toggleSubEtapas(el, toggleBtn);
        });
        firstDiv.insertBefore(toggleBtn, firstDiv.firstChild);
      }

      // Handle de arraste
      const h = document.createElement('span');
      h.className = 'dnd-handle';
      h.innerHTML = '&#8942;';
      h.title = 'Arrastar para reordenar';
      h.style.cssText = 'cursor:grab;color:#cbd5e1;font-size:1rem;user-select:none;display:inline-block;margin-right:.3rem;vertical-align:middle;';
      firstDiv.insertBefore(h, firstDiv.firstChild);
    }
    el.addEventListener('dragstart', obrasDragStart);
    el.addEventListener('dragover', obrasDragOver);
    el.addEventListener('drop', obrasDrop);
    el.addEventListener('dragend', obrasDragEnd);
  });

})();

function abrirModalCorrecao() {
  new bootstrap.Modal(document.getElementById('modalCorrecao')).show();
}
async function salvarCorrecao() {
  const tipo = document.getElementById('correcaoTipo').value;
  const valor = parseFloat(document.getElementById('correcaoValor').value);
  const subs = document.getElementById('correcaoSubetapas').checked;
  if (isNaN(valor)) { alert('Informe o valor da corre\\u00e7\\u00e3o.'); return; }
  const r = await fetch('/ferramentas/obras/' + OBRA_ID + '/aplicar-correcao', {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({ tipo, valor, aplicar_subetapas: subs })
  });
  const d = await r.json();
  if (d.ok) {
    bootstrap.Modal.getInstance(document.getElementById('modalCorrecao')).hide();
    alert(d.atualizadas + ' etapa(s) atualizadas. Recarregando...');
    location.reload();
  } else { alert('Erro ao aplicar reajuste.'); }
}
</script>
"""

    tpl = tpl.replace("{% endblock %}", _INJECT + "\n{# _reorderCorrecaoV4 #}\n{% endblock %}", 1)
    TEMPLATES["ferramenta_obras_cronograma.html"] = tpl
    if hasattr(templates_env.loader, "mapping"):
        templates_env.loader.mapping = TEMPLATES
    print("[obras_reorder_correcao] Template patcheado V4 OK")


_patch_obras_reorder_correcao()

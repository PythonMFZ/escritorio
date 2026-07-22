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

    # Recebe lista ordenada de ids da fase e reatribui ordem
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

    # Busca todas as etapas da obra que ainda não foram executadas (sem apontamento com fisico_pct > 0)
    fases = session.exec(
        select(ObraFase).where(ObraFase.obra_id == obra_id)
    ).all()
    fase_ids = [f.id for f in fases]
    etapas = session.exec(
        select(ObraEtapa).where(ObraEtapa.fase_id.in_(fase_ids))
    ).all()

    atualizadas = 0
    for etapa in etapas:
        # Verifica se tem apontamento com progresso > 0
        apt = session.exec(
            select(ObraApontamento)
            .where(ObraApontamento.etapa_id == etapa.id)
            .order_by(ObraApontamento.created_at.desc())
            .limit(1)
        ).first()
        fisico = apt.fisico_pct if apt else 0
        if fisico > 0:
            continue  # etapa já iniciada — não altera

        # Salva orçamento original na primeira correção
        orig = getattr(etapa, "orcado_original_rs", None)
        if not orig or orig == 0:
            try:
                etapa.orcado_original_rs = etapa.orcado_rs
            except Exception:
                pass

        # Aplica correção sobre o valor original (para permitir re-aplicações)
        base = etapa.orcado_original_rs if (getattr(etapa, "orcado_original_rs", 0) or 0) > 0 else etapa.orcado_rs
        if tipo == "pct":
            etapa.orcado_rs = round(base * (1 + valor / 100), 2)
        else:
            etapa.orcado_rs = round(base + valor, 2)
        session.add(etapa)
        atualizadas += 1

        # Sub-etapas
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

def _patch_obras_reorder_correcao():
    tpl = TEMPLATES.get("ferramenta_obras_cronograma.html", "")
    if not tpl or "_reorderCorrecaoV1" in tpl:
        return

    # 1. Adiciona draggable + handle à linha de etapa
    _OLD_ETAPA_DIV = '  <div class="cr-etapa" id="etapa-row-{{ e.id }}">\n    <div>'
    _NEW_ETAPA_DIV = (
        '  <div class="cr-etapa" id="etapa-row-{{ e.id }}" draggable="true"\n'
        '       data-etapa-id="{{ e.id }}" data-fase-id="{{ fase.id }}"\n'
        '       ondragstart="obrasDragStart(event)" ondragover="obrasDragOver(event)"\n'
        '       ondrop="obrasDrop(event)" ondragend="obrasDragEnd(event)">\n'
        '    <div style="display:flex;align-items:flex-start;gap:.4rem;">\n'
        '      <span class="drag-handle" title="Arrastar para reordenar" '
        'style="cursor:grab;color:#cbd5e1;font-size:1rem;padding-top:2px;user-select:none;">⠿</span>\n'
        '      <div>'
    )
    if _OLD_ETAPA_DIV in tpl:
        tpl = tpl.replace(_OLD_ETAPA_DIV, _NEW_ETAPA_DIV, 1)

    # Fecha o div extra que abrimos
    _OLD_CLOSE = (
        '      {% if e.data_inicio or e.data_fim %}<div style="font-size:.7rem;color:var(--mc-muted);">{{ e.data_inicio }} → {{ e.data_fim }}</div>{% endif %}\n'
        '      <div class="bar-sm"><div class="bar-sm-inner" style="width:{{ e.fisico_pct }}%;background:var(--mc-primary);"></div></div>\n'
        '    </div>'
    )
    _NEW_CLOSE = (
        '      {% if e.data_inicio or e.data_fim %}<div style="font-size:.7rem;color:var(--mc-muted);">{{ e.data_inicio }} → {{ e.data_fim }}</div>{% endif %}\n'
        '      <div class="bar-sm"><div class="bar-sm-inner" style="width:{{ e.fisico_pct }}%;background:var(--mc-primary);"></div></div>\n'
        '    </div></div>'
    )
    if _OLD_CLOSE in tpl:
        tpl = tpl.replace(_OLD_CLOSE, _NEW_CLOSE, 1)

    # 2. Adiciona botão "Correção" no cabeçalho da obra (próximo ao botão existente)
    _OLD_HDR_BTN = '<button class="btn btn-sm btn-outline-secondary no-print" onclick="abrirNovaFase()">'
    _NEW_HDR_BTN = (
        '<button class="btn btn-sm btn-warning no-print" onclick="abrirModalCorrecao()" '
        'style="font-size:.8rem;" title="Aplicar correção a todas as etapas futuras">\n'
        '  📐 Correção\n'
        '</button>\n'
        '<button class="btn btn-sm btn-outline-secondary no-print" onclick="abrirNovaFase()">'
    )
    if _OLD_HDR_BTN in tpl:
        tpl = tpl.replace(_OLD_HDR_BTN, _NEW_HDR_BTN, 1)

    # 3. Adiciona modal de correção antes do </body> / {% endblock %}
    _MODAL_CORRECAO = """
<!-- Modal Correção -->
<div class="modal fade" id="modalCorrecao" tabindex="-1">
  <div class="modal-dialog modal-sm">
    <div class="modal-content">
      <div class="modal-header" style="background:#f97316;color:#fff;">
        <h5 class="modal-title">📐 Aplicar Correção ao Orçamento</h5>
        <button type="button" class="btn-close btn-close-white" data-bs-dismiss="modal"></button>
      </div>
      <div class="modal-body">
        <p style="font-size:.83rem;color:#64748b;">Aplica correção a todas as etapas <b>ainda não executadas</b> (físico = 0%). O valor original do primeiro orçamento fica salvo.</p>
        <div class="mb-3">
          <label class="form-label fw-semibold">Tipo de correção</label>
          <select id="correcaoTipo" class="form-select">
            <option value="pct">% sobre o orçamento original</option>
            <option value="rs">R$ fixo sobre o orçamento original</option>
          </select>
        </div>
        <div class="mb-3">
          <label class="form-label fw-semibold" id="correcaoLabel">Percentual (%)</label>
          <input type="number" id="correcaoValor" class="form-control" step="0.01" placeholder="Ex: 5 para +5%">
          <div class="form-text">Use valor negativo para reduzir. Ex: -3 para -3%.</div>
        </div>
        <div class="form-check mb-2">
          <input class="form-check-input" type="checkbox" id="correcaoSubetapas" checked>
          <label class="form-check-label" for="correcaoSubetapas">Aplicar também às sub-etapas</label>
        </div>
      </div>
      <div class="modal-footer">
        <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Cancelar</button>
        <button type="button" class="btn btn-warning" onclick="salvarCorrecao()">Aplicar</button>
      </div>
    </div>
  </div>
</div>
"""
    _OLD_ENDBLOCK = "{% endblock %}"
    tpl = tpl.replace(_OLD_ENDBLOCK,
                      _MODAL_CORRECAO + "\n" + _OLD_ENDBLOCK, 1)

    # 4. Adiciona JS de drag-and-drop e modal correção antes de </script>
    _DND_JS = """
// ── Drag-and-drop etapas ──
let _dragEtapa = null, _dragOverEtapa = null;
function obrasDragStart(e) {
  _dragEtapa = e.currentTarget;
  e.dataTransfer.effectAllowed = 'move';
  e.currentTarget.style.opacity = '0.4';
}
function obrasDragOver(e) {
  e.preventDefault();
  e.dataTransfer.dropEffect = 'move';
  const el = e.currentTarget;
  if (el !== _dragEtapa && el.dataset.faseId === _dragEtapa?.dataset?.faseId) {
    el.style.borderTop = '2px solid #6366f1';
    _dragOverEtapa = el;
  }
}
function obrasDragEnd(e) {
  e.currentTarget.style.opacity = '';
  document.querySelectorAll('.cr-etapa').forEach(el => el.style.borderTop = '');
}
async function obrasDrop(e) {
  e.preventDefault();
  document.querySelectorAll('.cr-etapa').forEach(el => el.style.borderTop = '');
  if (!_dragEtapa || !_dragOverEtapa || _dragEtapa === _dragOverEtapa) return;
  if (_dragEtapa.dataset.faseId !== _dragOverEtapa.dataset.faseId) {
    alert('Mova etapas apenas dentro da mesma fase.'); return;
  }
  const parent = _dragOverEtapa.parentNode;
  parent.insertBefore(_dragEtapa, _dragOverEtapa);
  _dragEtapa.style.opacity = '';
  // Coleta nova ordem
  const ids = [...parent.querySelectorAll('.cr-etapa')].map(el => parseInt(el.dataset.etapaId));
  await fetch('/ferramentas/obras/etapa/' + _dragEtapa.dataset.etapaId + '/reordenar', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({ obra_id: OBRA_ID, ids: ids })
  });
  _dragEtapa = null; _dragOverEtapa = null;
}

// ── Modal Correção ──
document.getElementById('correcaoTipo')?.addEventListener('change', function() {
  document.getElementById('correcaoLabel').textContent =
    this.value === 'pct' ? 'Percentual (%)' : 'Valor em R$';
});
function abrirModalCorrecao() {
  new bootstrap.Modal(document.getElementById('modalCorrecao')).show();
}
async function salvarCorrecao() {
  const tipo = document.getElementById('correcaoTipo').value;
  const valor = parseFloat(document.getElementById('correcaoValor').value);
  const subs = document.getElementById('correcaoSubetapas').checked;
  if (isNaN(valor)) { alert('Informe o valor da correção.'); return; }
  const r = await fetch('/ferramentas/obras/' + OBRA_ID + '/aplicar-correcao', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({ tipo, valor, aplicar_subetapas: subs })
  });
  const d = await r.json();
  if (d.ok) {
    bootstrap.Modal.getInstance(document.getElementById('modalCorrecao')).hide();
    alert(d.atualizadas + ' etapa(s) atualizadas. Recarregando...');
    location.reload();
  } else { alert('Erro ao aplicar correção.'); }
}
"""
    _OLD_SCRIPT_END = "</script>\n{% endblock %}"
    if _OLD_SCRIPT_END in tpl:
        tpl = tpl.replace(_OLD_SCRIPT_END, _DND_JS + "\n</script>\n{% endblock %}", 1)

    # Sentinel
    tpl = tpl.replace("{% endblock %}", "{# _reorderCorrecaoV1 #}\n{% endblock %}", 1)
    TEMPLATES["ferramenta_obras_cronograma.html"] = tpl
    if hasattr(templates_env.loader, "mapping"):
        templates_env.loader.mapping = TEMPLATES
    print("[obras_reorder_correcao] Template patcheado OK")


_patch_obras_reorder_correcao()

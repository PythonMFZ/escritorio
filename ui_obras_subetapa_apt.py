# =============================================================================
# Gestão de Obras — Apontamento em Sub-etapa + Orçado rollup + Gantt completo
# Estritamente ADITIVO — não modifica tabelas ou dados existentes
# =============================================================================

import re as _re_seapt
from typing import Optional as _OptSA
from sqlmodel import Field as _FSA, SQLModel as _SMSA

# ── Modelo: apontamento de sub-etapa ─────────────────────────────────────────

class ObraSubEtapaApt(_SMSA, table=True):
    __tablename__  = "obrasubetapapt"
    __table_args__ = {"extend_existing": True}
    id:            _OptSA[int] = _FSA(default=None, primary_key=True)
    subetapa_id:   int         = _FSA(index=True)
    obra_id:       int         = _FSA(index=True)
    fisico_pct:    float       = _FSA(default=0.0)
    financeiro_rs: float       = _FSA(default=0.0)
    data:          str         = _FSA(default="")
    versao:        str         = _FSA(default="")
    obs:           str         = _FSA(default="")

try:
    _SMSA.metadata.create_all(engine, tables=[ObraSubEtapaApt.__table__])
except Exception:
    pass


# ── Override: _calcular_obra com apts de sub-etapa e rollup de orçado ────────

def _calcular_obra(session, obra):
    fases = session.exec(
        select(ObraFase).where(ObraFase.obra_id == obra.id).order_by(ObraFase.ordem)
    ).all()

    orcado_total = 0.0
    realizado_rs = 0.0
    n_etapas     = 0
    fases_data   = []

    for fase in fases:
        etapas = session.exec(
            select(ObraEtapa).where(ObraEtapa.fase_id == fase.id).order_by(ObraEtapa.ordem)
        ).all()

        fase_orcado  = 0.0
        fase_real_rs = 0.0
        etapas_data  = []

        for etapa in etapas:
            # ── Sub-etapas com último apontamento ──
            subetapas_raw = session.exec(
                select(ObraSubEtapa)
                .where(ObraSubEtapa.etapa_id == etapa.id)
                .order_by(ObraSubEtapa.ordem)
            ).all()

            subetapas_data = []
            se_orcado_sum  = 0.0
            se_fin_sum     = 0.0
            se_fisico_list = []
            se_has_apt     = False

            for se in subetapas_raw:
                se_apt = session.exec(
                    select(ObraSubEtapaApt)
                    .where(ObraSubEtapaApt.subetapa_id == se.id)
                    .order_by(ObraSubEtapaApt.id.desc())
                    .limit(1)
                ).first()

                se_fis = se_apt.fisico_pct    if se_apt else 0.0
                se_fin = se_apt.financeiro_rs if se_apt else 0.0
                if se_apt:
                    se_has_apt = True

                se_orcado_sum += se.orcado_rs
                se_fin_sum    += se_fin
                se_fisico_list.append((se_fis, se.orcado_rs))

                subetapas_data.append({
                    "id":           se.id,
                    "etapa_id":     se.etapa_id,
                    "descricao":    se.descricao,
                    "insumo":       se.insumo,
                    "orcado_rs":    se.orcado_rs,
                    "data_inicio":  se.data_inicio,
                    "data_fim":     se.data_fim,
                    "ordem":        se.ordem,
                    "fisico_pct":   round(se_fis, 1),
                    "financeiro_rs": round(se_fin, 2),
                })

            # ── Orçado efetivo: soma das sub-etapas se > 0, senão próprio ──
            effective_orcado = se_orcado_sum if se_orcado_sum > 0 else etapa.orcado_rs

            # ── Físico/financeiro: de sub-etapas se tiver apt, senão próprio apt ──
            if se_has_apt:
                # Média ponderada pelo orçado
                total_w = sum(orc for _, orc in se_fisico_list) or len(se_fisico_list)
                fisico_pct = round(
                    sum(f * (orc / total_w) for f, orc in se_fisico_list)
                    if total_w > 0 else 0.0, 1
                )
                financeiro_rs = round(se_fin_sum, 2)
                versao   = "—"
                data_apt = "—"
            else:
                apts = session.exec(
                    select(ObraApontamento)
                    .where(ObraApontamento.etapa_id == etapa.id)
                    .order_by(ObraApontamento.id.desc())
                    .limit(1)
                ).all()
                apt = apts[0] if apts else None
                fisico_pct    = apt.fisico_pct    if apt else 0.0
                financeiro_rs = apt.financeiro_rs if apt else 0.0
                versao        = apt.versao        if apt else "—"
                data_apt      = apt.data          if apt else "—"

            historico = session.exec(
                select(ObraApontamento)
                .where(ObraApontamento.etapa_id == etapa.id)
                .order_by(ObraApontamento.id.desc())
            ).all()

            esperado   = effective_orcado * (fisico_pct / 100) if fisico_pct > 0 else 0
            desvio_rs  = financeiro_rs - esperado
            desvio_pct = (desvio_rs / esperado * 100) if esperado > 0 else 0

            etapas_data.append({
                "id":            etapa.id,
                "fase_id":       fase.id,
                "descricao":     etapa.descricao,
                "insumo":        etapa.insumo,
                "orcado_rs":     effective_orcado,
                "data_inicio":   etapa.data_inicio,
                "data_fim":      etapa.data_fim,
                "fisico_pct":    fisico_pct,
                "financeiro_rs": financeiro_rs,
                "versao":        versao,
                "data_apt":      data_apt,
                "desvio_rs":     round(desvio_rs, 2),
                "desvio_pct":    round(desvio_pct, 1),
                "a_incorrer":    round(effective_orcado - financeiro_rs, 2),
                "historico":     [{"versao": h.versao, "data": h.data,
                                   "fisico": h.fisico_pct, "financeiro": h.financeiro_rs,
                                   "obs": h.obs} for h in historico],
                "subetapas":     subetapas_data,
            })

            fase_orcado  += effective_orcado
            fase_real_rs += financeiro_rs
            orcado_total += effective_orcado
            realizado_rs += financeiro_rs
            n_etapas     += 1

        fase_etapas = etapas_data
        fev = sum(e["orcado_rs"] * (e["fisico_pct"] / 100) for e in fase_etapas)
        fase_fisico = round(fev / fase_orcado * 100, 1) if fase_orcado > 0 else 0.0

        fases_data.append({
            "id":           fase.id,
            "nome":         fase.nome,
            "ordem":        fase.ordem,
            "orcado_rs":    fase_orcado,
            "realizado_rs": fase_real_rs,
            "fisico_pct":   fase_fisico,
            "desvio_rs":    round(
                sum(e["financeiro_rs"] - e["orcado_rs"] * (e["fisico_pct"] / 100)
                    for e in fase_etapas), 2
            ),
            "a_incorrer":   round(fase_orcado - fase_real_rs, 2),
            "etapas":       fase_etapas,
        })

    orcado_total_obra = obra.orcamento_total or orcado_total
    ev_total     = sum(e["orcado_rs"] * (e["fisico_pct"] / 100)
                       for f in fases_data for e in f["etapas"])
    fisico_geral = round(ev_total / orcado_total * 100, 1) if orcado_total > 0 else 0
    idc          = round(ev_total / realizado_rs, 3) if realizado_rs > 0 else 1.0
    projecao_final = round(orcado_total_obra / idc, 2) if idc > 0 else orcado_total_obra

    return {
        "fases":          fases_data,
        "orcado_total":   round(orcado_total_obra, 2),
        "realizado_rs":   round(realizado_rs, 2),
        "ev_total":       round(ev_total, 2),
        "a_incorrer":     round(orcado_total_obra - realizado_rs, 2),
        "fisico_geral":   fisico_geral,
        "desvio_geral":   round(realizado_rs - ev_total, 2),
        "idc":            idc,
        "projecao_final": projecao_final,
        "n_etapas":       n_etapas,
        "n_fases":        len(fases),
    }


# ── Rota: salvar apontamento de sub-etapa ─────────────────────────────────────

@app.post("/ferramentas/obras/subetapa/{se_id}/apt")
@require_login
async def obras_subetapa_apt_salvar(se_id: int, request: Request, session: Session = Depends(get_session)):
    ctx = get_tenant_context(request, session)
    if not ctx:
        return JSONResponse({"ok": False}, status_code=401)
    se = session.get(ObraSubEtapa, se_id)
    if not se:
        return JSONResponse({"ok": False}, status_code=404)
    obra = _get_obra_or_404(session, se.obra_id, ctx.company.id)
    if not obra:
        return JSONResponse({"ok": False}, status_code=403)

    body = await request.json()
    apt = ObraSubEtapaApt(
        subetapa_id=se_id,
        obra_id=se.obra_id,
        fisico_pct=float(body.get("fisico_pct", 0) or 0),
        financeiro_rs=float(body.get("financeiro_rs", 0) or 0),
        data=body.get("data", ""),
        obs=body.get("obs", ""),
    )
    session.add(apt); session.commit(); session.refresh(apt)
    return JSONResponse({"ok": True, "id": apt.id})


# ── Rota: histórico de apontamentos da sub-etapa ──────────────────────────────

@app.get("/ferramentas/obras/subetapa/{se_id}/apt/historico")
@require_login
async def obras_subetapa_apt_historico(se_id: int, request: Request, session: Session = Depends(get_session)):
    ctx = get_tenant_context(request, session)
    if not ctx:
        return JSONResponse({"ok": False}, status_code=401)
    se = session.get(ObraSubEtapa, se_id)
    if not se:
        return JSONResponse({"ok": False}, status_code=404)
    obra = _get_obra_or_404(session, se.obra_id, ctx.company.id)
    if not obra:
        return JSONResponse({"ok": False}, status_code=403)

    hist = session.exec(
        select(ObraSubEtapaApt)
        .where(ObraSubEtapaApt.subetapa_id == se_id)
        .order_by(ObraSubEtapaApt.id.desc())
    ).all()
    return JSONResponse({"ok": True, "historico": [
        {"data": h.data, "fisico_pct": h.fisico_pct,
         "financeiro_rs": h.financeiro_rs, "obs": h.obs}
        for h in hist
    ]})


# ── Patch do template cronograma ──────────────────────────────────────────────

def _patch_subetapa_apt():
    tpl = TEMPLATES.get("ferramenta_obras_cronograma.html", "")
    if not tpl or "_seAptV1" in tpl:
        print("[subetapa_apt] Ja aplicado")
        return

    changed = False

    # ── A: CSS — adiciona coluna físico/financeiro no grid da sub-etapa ──
    _OLD_SE_CSS = (
        "  .cr-subetapa{display:grid;grid-template-columns:2fr 1fr 1fr auto;gap:.4rem;"
    )
    _NEW_SE_CSS = (
        "  .cr-subetapa{display:grid;grid-template-columns:2fr 1fr 1fr 1fr auto;gap:.4rem;"
    )
    if _OLD_SE_CSS in tpl:
        tpl = tpl.replace(_OLD_SE_CSS, _NEW_SE_CSS, 1)
        changed = True
        print("[subetapa_apt] CSS grid atualizado")
    else:
        print("[subetapa_apt] CSS grid anchor nao encontrado")

    # ── B: Sub-etapa row — troca coluna data por físico/financeiro + btn Apt ──
    _OLD_SE_ROW = (
        '      <div>{% if se.orcado_rs %}{{ se.orcado_rs|brl }}{% else %}<span style="color:#cbd5e1;">—</span>{% endif %}</div>\n'
        '      <div>{% if se.data_inicio %}{{ se.data_inicio }}{% else %}<span style="color:#cbd5e1;">—</span>{% endif %}</div>\n'
        '      <div class="d-flex gap-1 no-print">\n'
        '        <button class="btn btn-outline-secondary" style="padding:.25rem .5rem;font-size:.75rem;"\n'
        "                onclick=\"editarSubEtapa({{ se.id }},'{{ se.descricao }}','{{ se.insumo }}',{{ se.orcado_rs }},'{{ se.data_inicio }}','{{ se.data_fim }}')\">\n"
        '          ✏️\n'
        '        </button>\n'
        '        <button class="btn btn-outline-danger" style="padding:.25rem .5rem;font-size:.75rem;"\n'
        "                onclick=\"apagarSubEtapa({{ se.id }},'{{ se.descricao }}')\">\n"
        '          🗑\n'
        '        </button>\n'
        '      </div>'
    )
    _NEW_SE_ROW = (
        '      <div>{% if se.orcado_rs %}{{ se.orcado_rs|brl }}{% else %}<span style="color:#cbd5e1;">—</span>{% endif %}</div>\n'
        '      <div>{% if se.fisico_pct %}<span style="color:#ea580c;font-weight:600;">{{ se.fisico_pct }}%</span>{% else %}<span style="color:#cbd5e1;">—</span>{% endif %}</div>\n'
        '      <div>{% if se.financeiro_rs %}<span style="color:#2563eb;">{{ se.financeiro_rs|brl }}</span>{% else %}<span style="color:#cbd5e1;">—</span>{% endif %}</div>\n'
        '      <div class="d-flex gap-1 no-print">\n'
        '        <button class="btn btn-outline-warning" style="padding:.25rem .5rem;font-size:.75rem;"\n'
        "                onclick=\"abrirAptSubEtapa({{ se.id }},'{{ se.descricao }}')\">\n"
        '          📊\n'
        '        </button>\n'
        '        <button class="btn btn-outline-secondary" style="padding:.25rem .5rem;font-size:.75rem;"\n'
        "                onclick=\"editarSubEtapa({{ se.id }},'{{ se.descricao }}','{{ se.insumo }}',{{ se.orcado_rs }},'{{ se.data_inicio }}','{{ se.data_fim }}')\">\n"
        '          ✏️\n'
        '        </button>\n'
        '        <button class="btn btn-outline-danger" style="padding:.25rem .5rem;font-size:.75rem;"\n'
        "                onclick=\"apagarSubEtapa({{ se.id }},'{{ se.descricao }}')\">\n"
        '          🗑\n'
        '        </button>\n'
        '      </div>'
    )
    if _OLD_SE_ROW in tpl:
        tpl = tpl.replace(_OLD_SE_ROW, _NEW_SE_ROW, 1)
        changed = True
        print("[subetapa_apt] Sub-etapa row atualizado")
    else:
        print("[subetapa_apt] Sub-etapa row anchor nao encontrado")

    # ── C: Modal modalSubEtapaApt antes do fechamento do overlay ─────────
    _OLD_OVERLAY_END = '  </div>\n\n</div>'
    _NEW_OVERLAY_END = (
        '  </div>\n\n'
        '  {# Modal: apontamento sub-etapa #}\n'
        '  <div class="modal-box" id="modalSubEtapaApt" style="display:none;">\n'
        '    <h6>📊 Apontamento — Sub-etapa</h6>\n'
        '    <div class="muted small mb-3" id="seAptNome" style="font-weight:500;"></div>\n'
        '    <div class="row g-2 mb-3">\n'
        '      <div class="col">\n'
        '        <label class="form-label fw-semibold small">Físico (%)</label>\n'
        '        <input type="number" class="form-control" id="seAptFisico" min="0" max="100" step="1" placeholder="0">\n'
        '      </div>\n'
        '      <div class="col">\n'
        '        <label class="form-label fw-semibold small">Financeiro (R$)</label>\n'
        '        <input type="number" class="form-control" id="seAptFinanceiro" min="0" step="100" placeholder="0">\n'
        '      </div>\n'
        '    </div>\n'
        '    <div class="mb-3">\n'
        '      <label class="form-label fw-semibold small">Data</label>\n'
        '      <input type="date" class="form-control" id="seAptData">\n'
        '    </div>\n'
        '    <div class="mb-3">\n'
        '      <label class="form-label fw-semibold small">Observação (opcional)</label>\n'
        '      <input type="text" class="form-control" id="seAptObs" placeholder="Notas...">\n'
        '    </div>\n'
        '    <div class="d-flex gap-2">\n'
        '      <button class="btn btn-primary flex-1" onclick="salvarAptSubEtapa()">Salvar Apontamento</button>\n'
        '      <button class="btn btn-outline-secondary" onclick="fecharModal()">Cancelar</button>\n'
        '    </div>\n'
        '  </div>\n\n'
        '</div>'
    )
    # Conta ocorrências para pegar a última (fechamento do overlay)
    count = tpl.count(_OLD_OVERLAY_END)
    if count >= 1:
        # Substitui a última ocorrência
        pos = tpl.rfind(_OLD_OVERLAY_END)
        tpl = tpl[:pos] + _NEW_OVERLAY_END + tpl[pos + len(_OLD_OVERLAY_END):]
        changed = True
        print("[subetapa_apt] Modal modalSubEtapaApt inserido")
    else:
        print("[subetapa_apt] Overlay end anchor nao encontrado")

    # ── D: fecharModal — inclui modalSubEtapaApt ─────────────────────────
    _OLD_FECHAR = (
        "  ['modalApt','modalFase','modalEtapa','modalHistorico','modalEditFase','modalSubEtapa'].forEach(id => {\n"
        "    const _el = document.getElementById(id); if (_el) _el.style.display = 'none';\n"
        "  });"
    )
    _NEW_FECHAR = (
        "  ['modalApt','modalFase','modalEtapa','modalHistorico','modalEditFase','modalSubEtapa','modalSubEtapaApt'].forEach(id => {\n"
        "    const _el = document.getElementById(id); if (_el) _el.style.display = 'none';\n"
        "  });"
    )
    if _OLD_FECHAR in tpl:
        tpl = tpl.replace(_OLD_FECHAR, _NEW_FECHAR, 1)
        changed = True

    # ── E: JS — abrirAptSubEtapa e salvarAptSubEtapa ─────────────────────
    _OLD_JS_ANCHOR = "async function apagarSubEtapa(id, nome) {"
    _NEW_JS_INSERT = (
        "// ── Apontamento sub-etapa ──\n"
        "let _seAptId = null;\n"
        "function abrirAptSubEtapa(seId, nome) {\n"
        "  _seAptId = seId;\n"
        "  document.getElementById('seAptNome').textContent = nome;\n"
        "  document.getElementById('seAptFisico').value = '';\n"
        "  document.getElementById('seAptFinanceiro').value = '';\n"
        "  document.getElementById('seAptData').value = new Date().toISOString().slice(0,10);\n"
        "  document.getElementById('seAptObs').value = '';\n"
        "  abrirModal('modalSubEtapaApt');\n"
        "}\n"
        "async function salvarAptSubEtapa() {\n"
        "  const payload = {\n"
        "    fisico_pct: parseFloat(document.getElementById('seAptFisico').value || 0),\n"
        "    financeiro_rs: parseFloat(document.getElementById('seAptFinanceiro').value || 0),\n"
        "    data: document.getElementById('seAptData').value,\n"
        "    obs: document.getElementById('seAptObs').value,\n"
        "  };\n"
        "  const r = await fetch('/ferramentas/obras/subetapa/' + _seAptId + '/apt', {\n"
        "    method: 'POST', headers: {'Content-Type': 'application/json'},\n"
        "    body: JSON.stringify(payload),\n"
        "  });\n"
        "  const d = await r.json();\n"
        "  if (d.ok) { fecharModal(); location.reload(); }\n"
        "  else { alert('Erro ao salvar apontamento.'); }\n"
        "}\n\n"
        "async function apagarSubEtapa(id, nome) {"
    )
    if _OLD_JS_ANCHOR in tpl:
        tpl = tpl.replace(_OLD_JS_ANCHOR, _NEW_JS_INSERT, 1)
        changed = True
        print("[subetapa_apt] JS apontamento sub-etapa inserido")
    else:
        print("[subetapa_apt] JS anchor apagarSubEtapa nao encontrado")

    # ── F: renderGantt — reescrita completa com timeline da obra ─────────
    _NEW_RENDER = (
        "function renderGantt() {\n"
        "  // Coleta todos os itens (com ou sem datas)\n"
        "  const allRows = [];\n"
        "  _GANTT_DATA.forEach(function(fase) {\n"
        "    allRows.push({label: fase.nome, start: null, end: null, type: 'fase', color: '#0f172a'});\n"
        "    fase.etapas.forEach(function(e) {\n"
        "      allRows.push({label: e.descricao, start: e.data_inicio||null, end: e.data_fim||null, type: 'etapa', color: '#ea580c'});\n"
        "      (e.subetapas||[]).forEach(function(se) {\n"
        "        allRows.push({label: se.descricao, start: se.data_inicio||null, end: se.data_fim||null, type: 'se', color: '#3b82f6'});\n"
        "      });\n"
        "    });\n"
        "  });\n"
        "  // Determina escala de tempo: usa datas da obra se disponíveis\n"
        "  let minDate = (_OBRA_INICIO && _OBRA_INICIO.length >= 7) ? _OBRA_INICIO : null;\n"
        "  let maxDate = (_OBRA_FIM    && _OBRA_FIM.length    >= 7) ? _OBRA_FIM    : null;\n"
        "  if (!minDate) {\n"
        "    const ss = allRows.filter(function(r){return r.start;}).map(function(r){return r.start;});\n"
        "    minDate = ss.length ? ss.reduce(function(a,b){return a<b?a:b;}) : null;\n"
        "  }\n"
        "  if (!maxDate) {\n"
        "    const ee = allRows.filter(function(r){return r.end;}).map(function(r){return r.end;});\n"
        "    maxDate = ee.length ? ee.reduce(function(a,b){return a>b?a:b;}) : null;\n"
        "  }\n"
        "  if (!minDate || !maxDate) {\n"
        "    document.getElementById('ganttGrid').innerHTML = '<p style=\"color:var(--mc-muted);font-size:.82rem;\">Defina as datas de início e fim da obra para visualizar o cronograma.</p>';\n"
        "    document.getElementById('ganttMonths').innerHTML = '';\n"
        "    return;\n"
        "  }\n"
        "  const t0 = new Date(minDate.length === 7 ? minDate + '-01' : minDate);\n"
        "  const t1 = new Date(maxDate.length  === 7 ? maxDate + '-28' : maxDate);\n"
        "  const totalMs = t1 - t0 || 1;\n"
        "  // Cabeçalho de meses\n"
        "  const months = []; let cur = new Date(t0);\n"
        "  while (cur <= t1) {\n"
        "    months.push(cur.toISOString().slice(0,7));\n"
        "    cur.setMonth(cur.getMonth()+1);\n"
        "  }\n"
        "  document.getElementById('ganttMonths').innerHTML = months.map(function(m){\n"
        "    return '<div class=\"gantt-month-tick\">' + m.slice(5) + '/' + m.slice(2,4) + '</div>';\n"
        "  }).join('');\n"
        "  // Linhas — mostra todos os itens, barra apenas se tiver datas\n"
        "  const rows = allRows.map(function(item) {\n"
        "    const cls = item.type==='fase' ? 'fase-row' : item.type==='etapa' ? 'etapa-row' : 'se-row';\n"
        "    let barHtml = '';\n"
        "    if (item.start && item.end) {\n"
        "      const s = new Date(item.start.length===7 ? item.start+'-01' : item.start);\n"
        "      const e = new Date(item.end.length===7   ? item.end+'-28'   : item.end);\n"
        "      const left  = Math.max(0, (s - t0) / totalMs * 100);\n"
        "      const width = Math.min(100 - left, Math.max(1, (e - s) / totalMs * 100));\n"
        "      barHtml = '<div class=\"gantt-bar\" style=\"left:' + left.toFixed(1) + '%;width:' + width.toFixed(1) + '%;background:' + item.color + ';\">' +\n"
        "                (item.label.length > 22 ? '' : item.label) + '</div>';\n"
        "    }\n"
        "    return '<div class=\"gantt-row ' + cls + '\">' +\n"
        "           '<div class=\"gantt-label\" title=\"' + item.label + '\">' + item.label + '</div>' +\n"
        "           '<div class=\"gantt-track\">' + barHtml + '</div>' +\n"
        "           '</div>';\n"
        "  }).join('');\n"
        "  document.getElementById('ganttGrid').innerHTML = rows;\n"
        "  // Linha de hoje\n"
        "  (function() {\n"
        "    const now = new Date();\n"
        "    if (now < t0 || now > t1) return;\n"
        "    const pct = ((now - t0) / totalMs * 100).toFixed(2);\n"
        "    document.querySelectorAll('.gantt-track').forEach(function(track) {\n"
        "      const ln = document.createElement('div');\n"
        "      ln.className = 'gantt-today-line';\n"
        "      ln.style.left = pct + '%';\n"
        "      ln.title = 'Hoje: ' + now.toLocaleDateString('pt-BR');\n"
        "      track.appendChild(ln);\n"
        "    });\n"
        "    const hdr = document.getElementById('ganttMonths');\n"
        "    if (hdr) {\n"
        "      hdr.style.position = 'relative';\n"
        "      const lbl = document.createElement('div');\n"
        "      lbl.className = 'gantt-today-lbl';\n"
        "      lbl.style.left = pct + '%';\n"
        "      lbl.textContent = '\\u25bc hoje';\n"
        "      hdr.appendChild(lbl);\n"
        "    }\n"
        "  })();\n"
        "}\n"
        "</script>\n"
        "{# _seGanttV1 #}\n"
        "{% endblock %}"
    )

    # Substitui toda a função renderGantt via regex
    _match = _re_seapt.search(r'function renderGantt\(\).*?</script>\s*\{#\s*_seGanttV1\s*#\}\s*\{%\s*endblock\s*%\}', tpl, _re_seapt.DOTALL)
    if _match:
        tpl = tpl[:_match.start()] + _NEW_RENDER
        changed = True
        print("[subetapa_apt] renderGantt reescrita com timeline completa")
    else:
        print("[subetapa_apt] renderGantt: padrao regex nao encontrado")

    # Sentinel
    if changed:
        tpl = tpl.replace("{# _seGanttV1 #}", "{# _seGanttV1 #}{# _seAptV1 #}", 1)
        TEMPLATES["ferramenta_obras_cronograma.html"] = tpl
        if hasattr(templates_env.loader, "mapping"):
            templates_env.loader.mapping = TEMPLATES
        print("[subetapa_apt] Template atualizado com sucesso")
    else:
        print("[subetapa_apt] Nenhuma alteracao aplicada")


_patch_subetapa_apt()
print("[subetapa_apt] Módulo carregado — apontamento sub-etapa, orçado rollup, Gantt completo")

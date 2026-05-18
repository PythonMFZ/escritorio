# =============================================================================
# Gestão de Obras — Duplicar Etapa
# Copia uma etapa inteira (+ sub-etapas) dentro da mesma fase com o nome "(cópia)"
# =============================================================================

# ── Rota: duplicar etapa ──────────────────────────────────────────────────────

@app.post("/ferramentas/obras/{obra_id}/etapa/{etapa_id}/duplicar")
@require_login
async def obras_etapa_duplicar(obra_id: int, etapa_id: int, request: Request,
                                session: Session = Depends(get_session)):
    ctx = get_tenant_context(request, session)
    if not ctx:
        return JSONResponse({"ok": False}, status_code=401)
    obra = _get_obra_or_404(session, obra_id, ctx.company.id)
    if not obra:
        return JSONResponse({"ok": False}, status_code=404)

    etapa_orig = session.get(ObraEtapa, etapa_id)
    if not etapa_orig or etapa_orig.obra_id != obra_id:
        return JSONResponse({"ok": False, "erro": "Etapa não encontrada"}, status_code=404)

    # Próxima ordem dentro da mesma fase
    etapas_fase = session.exec(
        select(ObraEtapa).where(ObraEtapa.fase_id == etapa_orig.fase_id)
    ).all()
    nova_ordem = max((e.ordem for e in etapas_fase), default=0) + 1

    # Clona a etapa
    nova_etapa = ObraEtapa(
        fase_id=etapa_orig.fase_id,
        obra_id=obra_id,
        descricao=etapa_orig.descricao + " (cópia)",
        insumo=etapa_orig.insumo,
        orcado_rs=etapa_orig.orcado_rs,
        data_inicio=etapa_orig.data_inicio,
        data_fim=etapa_orig.data_fim,
        ordem=nova_ordem,
    )
    session.add(nova_etapa)
    session.commit()
    session.refresh(nova_etapa)

    # Clona sub-etapas
    subetapas = session.exec(
        select(ObraSubEtapa).where(ObraSubEtapa.etapa_id == etapa_id)
        .order_by(ObraSubEtapa.ordem)
    ).all()
    for se in subetapas:
        nova_se = ObraSubEtapa(
            etapa_id=nova_etapa.id,
            obra_id=obra_id,
            descricao=se.descricao,
            insumo=se.insumo,
            orcado_rs=se.orcado_rs,
            data_inicio=se.data_inicio,
            data_fim=se.data_fim,
            ordem=se.ordem,
        )
        session.add(nova_se)
    session.commit()

    return JSONResponse({"ok": True, "nova_etapa_id": nova_etapa.id, "nome": nova_etapa.descricao})


# ── Patch do template ─────────────────────────────────────────────────────────

def _patch_obras_duplicar_etapa():
    tpl = TEMPLATES.get("ferramenta_obras_cronograma.html", "")
    if not tpl or "_dupEtapaV1" in tpl:
        return

    changed = False

    # Adiciona botão ⧉ Duplicar antes do botão "+ Sub" na linha de etapa
    _OLD_ETAPA_BTNS = (
        '      <button class="btn btn-sm btn-outline-secondary" onclick="abrirNovaSubEtapa({{ e.id }},\'{{ e.descricao }}\')" title="+ Sub-etapa" style="font-size:.75rem;">\n'
        "        + Sub\n"
        "      </button>\n"
        '      <button class="btn btn-sm btn-outline-danger" onclick="apagarEtapa({{ e.id }},\'{{ e.descricao }}\')" title="Apagar">\n'
        "        🗑\n"
        "      </button>\n"
    )
    _NEW_ETAPA_BTNS = (
        '      <button class="btn btn-sm btn-outline-primary" onclick="duplicarEtapa({{ e.id }},\'{{ e.descricao }}\')" title="Duplicar etapa" style="font-size:.75rem;">\n'
        "        ⧉\n"
        "      </button>\n"
        '      <button class="btn btn-sm btn-outline-secondary" onclick="abrirNovaSubEtapa({{ e.id }},\'{{ e.descricao }}\')" title="+ Sub-etapa" style="font-size:.75rem;">\n'
        "        + Sub\n"
        "      </button>\n"
        '      <button class="btn btn-sm btn-outline-danger" onclick="apagarEtapa({{ e.id }},\'{{ e.descricao }}\')" title="Apagar">\n'
        "        🗑\n"
        "      </button>\n"
    )
    if _OLD_ETAPA_BTNS in tpl:
        tpl = tpl.replace(_OLD_ETAPA_BTNS, _NEW_ETAPA_BTNS, 1)
        changed = True

    # Adiciona JS duplicarEtapa antes de apagarEtapa
    _OLD_APAGAR_ETAPA = (
        "async function apagarEtapa(id, nome) {\n"
        "  if (!confirm('Apagar etapa \"' + nome + '\" e todo seu histórico?')) return;\n"
        "  const r = await fetch('/ferramentas/obras/etapa/' + id + '/apagar', {method:'POST'});\n"
        "  const d = await r.json();\n"
        "  if (d.ok) { const el = document.getElementById('etapa-row-' + id); if(el) el.remove(); }\n"
        "}"
    )
    _NEW_APAGAR_ETAPA = (
        "async function duplicarEtapa(id, nome) {\n"
        "  if (!confirm('Duplicar etapa \"' + nome + '\"?\\nSerá criada uma cópia com todas as sub-etapas.')) return;\n"
        "  const btn = event.target.closest('button');\n"
        "  btn.disabled = true; btn.textContent = '...';\n"
        "  try {\n"
        "    const r = await fetch('/ferramentas/obras/' + OBRA_ID + '/etapa/' + id + '/duplicar', {method:'POST'});\n"
        "    const d = await r.json();\n"
        "    if (d.ok) { location.reload(); }\n"
        "    else { alert('Erro ao duplicar etapa: ' + (d.erro || 'desconhecido')); btn.disabled=false; btn.textContent='⧉'; }\n"
        "  } catch(e) { alert('Erro de rede ao duplicar etapa.'); btn.disabled=false; btn.textContent='⧉'; }\n"
        "}\n\n"
        "async function apagarEtapa(id, nome) {\n"
        "  if (!confirm('Apagar etapa \"' + nome + '\" e todo seu histórico?')) return;\n"
        "  const r = await fetch('/ferramentas/obras/etapa/' + id + '/apagar', {method:'POST'});\n"
        "  const d = await r.json();\n"
        "  if (d.ok) { const el = document.getElementById('etapa-row-' + id); if(el) el.remove(); }\n"
        "}"
    )
    if _OLD_APAGAR_ETAPA in tpl:
        tpl = tpl.replace(_OLD_APAGAR_ETAPA, _NEW_APAGAR_ETAPA, 1)
        changed = True

    # Sentinel
    tpl = tpl.replace("{% endblock %}", "{# _dupEtapaV1 #}\n{% endblock %}", 1)

    if changed:
        TEMPLATES["ferramenta_obras_cronograma.html"] = tpl
        print("[duplicar_etapa] Template patcheado com botão Duplicar na etapa")
    else:
        print("[duplicar_etapa] Aviso: algumas patches não foram aplicadas")

    if hasattr(templates_env.loader, "mapping"):
        templates_env.loader.mapping = TEMPLATES


_patch_obras_duplicar_etapa()
print("[duplicar_etapa] Módulo carregado — duplicar etapa ativo")

# =============================================================================
# Gestão de Obras — Duplicar Fase
# Copia uma fase inteira (etapas + sub-etapas) com o nome "(cópia)"
# =============================================================================

# ── Rota: duplicar fase ───────────────────────────────────────────────────────

@app.post("/ferramentas/obras/{obra_id}/fase/{fase_id}/duplicar")
@require_login
async def obras_fase_duplicar(obra_id: int, fase_id: int, request: Request,
                               session: Session = Depends(get_session)):
    ctx = get_tenant_context(request, session)
    if not ctx:
        return JSONResponse({"ok": False}, status_code=401)
    obra = _get_obra_or_404(session, obra_id, ctx.company.id)
    if not obra:
        return JSONResponse({"ok": False}, status_code=404)

    fase_orig = session.get(ObraFase, fase_id)
    if not fase_orig or fase_orig.obra_id != obra_id:
        return JSONResponse({"ok": False, "erro": "Fase não encontrada"}, status_code=404)

    # Próxima ordem
    todas_fases = session.exec(
        select(ObraFase).where(ObraFase.obra_id == obra_id)
    ).all()
    nova_ordem = max((f.ordem for f in todas_fases), default=0) + 1

    # Clona a fase
    nova_fase = ObraFase(
        obra_id=obra_id,
        nome=fase_orig.nome + " (cópia)",
        ordem=nova_ordem,
        orcado_rs=fase_orig.orcado_rs if hasattr(fase_orig, "orcado_rs") else 0.0,
    )
    session.add(nova_fase)
    session.commit()
    session.refresh(nova_fase)

    # Clona etapas
    etapas_orig = session.exec(
        select(ObraEtapa).where(ObraEtapa.fase_id == fase_id)
        .order_by(ObraEtapa.ordem)
    ).all()

    for etapa in etapas_orig:
        nova_etapa = ObraEtapa(
            fase_id=nova_fase.id,
            obra_id=obra_id,
            descricao=etapa.descricao,
            insumo=etapa.insumo,
            orcado_rs=etapa.orcado_rs,
            data_inicio=etapa.data_inicio,
            data_fim=etapa.data_fim,
            ordem=etapa.ordem,
        )
        session.add(nova_etapa)
        session.commit()
        session.refresh(nova_etapa)

        # Clona sub-etapas
        subetapas = session.exec(
            select(ObraSubEtapa).where(ObraSubEtapa.etapa_id == etapa.id)
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

    return JSONResponse({"ok": True, "nova_fase_id": nova_fase.id, "nome": nova_fase.nome})


# ── Patch do template ─────────────────────────────────────────────────────────

def _patch_obras_duplicar():
    tpl = TEMPLATES.get("ferramenta_obras_cronograma.html", "")
    if not tpl or "_dupFaseV1" in tpl:
        return

    changed = False

    # Adiciona botão Duplicar antes do botão ✏️ na header da fase
    _OLD_FASE_BTNS = (
        '    <button class="btn btn-xs btn-outline-secondary no-print" style="padding:.1rem .4rem;font-size:.7rem;"\n'
        "            onclick=\"event.stopPropagation();editarFase({{ fase.id }},'{{ fase.nome }}')\">\n"
        "      ✏️\n"
        "    </button>\n"
        '    <button class="btn btn-xs btn-outline-danger no-print" style="padding:.1rem .4rem;font-size:.7rem;"\n'
        "            onclick=\"event.stopPropagation();apagarFase({{ fase.id }},'{{ fase.nome }}')\">\n"
        "      🗑\n"
        "    </button>"
    )
    _NEW_FASE_BTNS = (
        '    <button class="btn btn-xs btn-outline-primary no-print" style="padding:.1rem .4rem;font-size:.7rem;"\n'
        "            onclick=\"event.stopPropagation();duplicarFase({{ fase.id }},'{{ fase.nome }}')\" title=\"Duplicar fase\">\n"
        "      ⧉\n"
        "    </button>\n"
        '    <button class="btn btn-xs btn-outline-secondary no-print" style="padding:.1rem .4rem;font-size:.7rem;"\n'
        "            onclick=\"event.stopPropagation();editarFase({{ fase.id }},'{{ fase.nome }}')\">\n"
        "      ✏️\n"
        "    </button>\n"
        '    <button class="btn btn-xs btn-outline-danger no-print" style="padding:.1rem .4rem;font-size:.7rem;"\n'
        "            onclick=\"event.stopPropagation();apagarFase({{ fase.id }},'{{ fase.nome }}')\">\n"
        "      🗑\n"
        "    </button>"
    )
    if _OLD_FASE_BTNS in tpl:
        tpl = tpl.replace(_OLD_FASE_BTNS, _NEW_FASE_BTNS, 1)
        changed = True

    # Adiciona JS duplicarFase + corrige salvarSubEtapa com feedback de erro
    _OLD_APAGAR_FASE = (
        "async function apagarFase(id, nome) {\n"
        "  if (!confirm('Apagar fase \"' + nome + '\" e todas suas etapas?')) return;\n"
        "  const r = await fetch('/ferramentas/obras/fase/' + id + '/apagar', {method:'POST'});\n"
        "  const d = await r.json();\n"
        "  if (d.ok) location.reload();\n"
        "}"
    )
    _NEW_APAGAR_FASE = (
        "async function apagarFase(id, nome) {\n"
        "  if (!confirm('Apagar fase \"' + nome + '\" e todas suas etapas?')) return;\n"
        "  const r = await fetch('/ferramentas/obras/fase/' + id + '/apagar', {method:'POST'});\n"
        "  const d = await r.json();\n"
        "  if (d.ok) location.reload();\n"
        "}\n\n"
        "async function duplicarFase(id, nome) {\n"
        "  if (!confirm('Duplicar fase \"' + nome + '\"?\\nSerá criada uma cópia com todas as etapas e sub-etapas.')) return;\n"
        "  const btn = event.target;\n"
        "  btn.disabled = true; btn.textContent = '...';\n"
        "  try {\n"
        "    const r = await fetch('/ferramentas/obras/' + OBRA_ID + '/fase/' + id + '/duplicar', {method:'POST'});\n"
        "    const d = await r.json();\n"
        "    if (d.ok) { location.reload(); }\n"
        "    else { alert('Erro ao duplicar fase: ' + (d.erro || 'desconhecido')); btn.disabled=false; btn.textContent='⧉'; }\n"
        "  } catch(e) { alert('Erro de rede ao duplicar fase.'); btn.disabled=false; btn.textContent='⧉'; }\n"
        "}"
    )
    if _OLD_APAGAR_FASE in tpl:
        tpl = tpl.replace(_OLD_APAGAR_FASE, _NEW_APAGAR_FASE, 1)
        changed = True

    # Corrige salvarSubEtapa: adiciona else com alert nos dois branches
    _OLD_SE_OK_NEW = (
        "  const d = await r.json();\n"
        "  if (d.ok) { fecharModal(); location.reload(); }\n"
        "}\n"
        "async function apagarSubEtapa"
    )
    _NEW_SE_OK_NEW = (
        "  const d = await r.json();\n"
        "  if (d.ok) { fecharModal(); location.reload(); }\n"
        "  else { alert('Erro ao criar sub-etapa: ' + (d.erro || JSON.stringify(d))); }\n"
        "}\n"
        "async function apagarSubEtapa"
    )
    if _OLD_SE_OK_NEW in tpl:
        tpl = tpl.replace(_OLD_SE_OK_NEW, _NEW_SE_OK_NEW, 1)
        changed = True

    # Sentinel
    tpl = tpl.replace("{% endblock %}", "{# _dupFaseV1 #}\n{% endblock %}", 1)

    if changed:
        TEMPLATES["ferramenta_obras_cronograma.html"] = tpl
        print("[duplicar_fase] Template patcheado com botão Duplicar")
    else:
        print("[duplicar_fase] Aviso: algumas patches não foram aplicadas")

    if hasattr(templates_env.loader, "mapping"):
        templates_env.loader.mapping = TEMPLATES


_patch_obras_duplicar()
print("[duplicar_fase] Módulo carregado — duplicar fase ativo")

# =============================================================================
# Gestão de Obras — Duplicar Obra Completa
# Copia toda a hierarquia: Obra → Fases → Etapas → Sub-etapas
# Admin pode duplicar para outro cliente da mesma empresa.
# =============================================================================

from fastapi import Request, Depends
from fastapi.responses import JSONResponse, RedirectResponse, HTMLResponse
from sqlmodel import Session, select


# ── Página de confirmação ─────────────────────────────────────────────────────

@app.get("/ferramentas/obras/{obra_id}/duplicar")
@require_login
async def obras_duplicar_form(obra_id: int, request: Request,
                               session: Session = Depends(get_session)):
    ctx = get_tenant_context(request, session)
    if not ctx:
        request.session.clear()
        return RedirectResponse("/login", status_code=303)

    obra = _get_obra_or_404(session, obra_id, ctx.company.id)
    if not obra:
        return RedirectResponse("/ferramentas/obras", status_code=303)

    # Lista de clientes (para admin poder duplicar para outro cliente)
    clientes = []
    if ctx.membership.role in ("admin", "owner"):
        clientes = session.exec(
            select(Client).where(Client.company_id == ctx.company.id)
            .order_by(Client.name)
        ).all()

    html = f"""<!DOCTYPE html>
<html lang="pt-BR"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Duplicar Obra</title>
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css">
</head><body class="bg-light p-4">
<div class="container" style="max-width:520px;">
  <h5 class="mb-1">Duplicar Obra</h5>
  <p class="text-muted small mb-4">Uma cópia de <strong>{obra.nome}</strong> será criada com todas as fases, etapas e sub-etapas. Apontamentos (medições) não são copiados.</p>
  <form method="POST" action="/ferramentas/obras/{obra_id}/duplicar">
    <div class="mb-3">
      <label class="form-label fw-semibold">Nome da nova obra</label>
      <input type="text" name="nome" class="form-control" value="{obra.nome} (cópia)" required>
    </div>"""

    if clientes:
        html += f"""
    <div class="mb-3">
      <label class="form-label fw-semibold">Destino — Cliente</label>
      <select name="target_client_id" class="form-select">
        <option value="{obra.client_id}" selected>Mesmo cliente atual</option>"""
        for c in clientes:
            if c.id != obra.client_id:
                html += f'<option value="{c.id}">{c.name}</option>'
        html += """
      </select>
      <div class="form-text">Como admin você pode copiar esta obra para outro cliente.</div>
    </div>"""

    html += f"""
    <div class="d-flex gap-2">
      <button type="submit" class="btn btn-primary">📋 Duplicar obra</button>
      <a href="/ferramentas/obras/{obra_id}" class="btn btn-outline-secondary">Cancelar</a>
    </div>
  </form>
</div>
</body></html>"""

    return HTMLResponse(html)


# ── Executa a duplicação ──────────────────────────────────────────────────────

@app.post("/ferramentas/obras/{obra_id}/duplicar")
@require_login
async def obras_duplicar_executar(obra_id: int, request: Request,
                                   session: Session = Depends(get_session)):
    ctx = get_tenant_context(request, session)
    if not ctx:
        return JSONResponse({"ok": False}, status_code=401)

    obra = _get_obra_or_404(session, obra_id, ctx.company.id)
    if not obra:
        return RedirectResponse("/ferramentas/obras", status_code=303)

    form = await request.form()
    novo_nome        = (form.get("nome") or f"{obra.nome} (cópia)").strip()
    target_client_id = int(form.get("target_client_id") or obra.client_id)

    # Admin pode copiar para qualquer cliente da empresa; outros só para o mesmo
    if target_client_id != obra.client_id:
        if ctx.membership.role not in ("admin", "owner"):
            return JSONResponse({"ok": False, "erro": "Sem permissão."}, status_code=403)
        # Valida que o cliente destino pertence à empresa
        dest_client = session.exec(
            select(Client).where(Client.id == target_client_id,
                                 Client.company_id == ctx.company.id)
        ).first()
        if not dest_client:
            return JSONResponse({"ok": False, "erro": "Cliente inválido."}, status_code=400)

    from datetime import datetime as _dt_dup
    agora = _dt_dup.now().strftime("%Y-%m-%d %H:%M:%S")

    # ── 1. Copia a Obra ───────────────────────────────────────────────────────
    nova_obra = Obra(
        company_id     = obra.company_id,
        client_id      = target_client_id,
        nome           = novo_nome,
        endereco       = obra.endereco,
        area_m2        = obra.area_m2,
        cub_m2         = obra.cub_m2,
        orcamento_total= obra.orcamento_total,
        data_inicio    = obra.data_inicio,
        data_fim       = obra.data_fim,
        status         = "em_andamento",
        obs            = obra.obs,
        created_at     = agora,
    )
    session.add(nova_obra)
    session.flush()  # garante nova_obra.id

    # ── 2. Copia Fases → Etapas → Sub-etapas ─────────────────────────────────
    fases_orig = session.exec(
        select(ObraFase).where(ObraFase.obra_id == obra_id).order_by(ObraFase.ordem)
    ).all()

    n_fases = n_etapas = n_subs = 0

    for fase_orig in fases_orig:
        nova_fase = ObraFase(
            obra_id    = nova_obra.id,
            nome       = fase_orig.nome,
            ordem      = fase_orig.ordem,
            created_at = agora,
        )
        session.add(nova_fase)
        session.flush()
        n_fases += 1

        etapas_orig = session.exec(
            select(ObraEtapa).where(ObraEtapa.fase_id == fase_orig.id).order_by(ObraEtapa.ordem)
        ).all()

        for etapa_orig in etapas_orig:
            nova_etapa = ObraEtapa(
                obra_id    = nova_obra.id,
                fase_id    = nova_fase.id,
                descricao  = etapa_orig.descricao,
                insumo     = etapa_orig.insumo,
                orcado_rs  = etapa_orig.orcado_rs,
                data_inicio= etapa_orig.data_inicio,
                data_fim   = etapa_orig.data_fim,
                ordem      = etapa_orig.ordem,
                created_at = agora,
            )
            session.add(nova_etapa)
            session.flush()
            n_etapas += 1

            # Sub-etapas
            try:
                subs = session.exec(
                    select(ObraSubEtapa).where(ObraSubEtapa.etapa_id == etapa_orig.id)
                ).all()
                for s in subs:
                    nova_sub = ObraSubEtapa(
                        etapa_id   = nova_etapa.id,
                        obra_id    = nova_obra.id,
                        descricao  = s.descricao,
                        insumo     = s.insumo,
                        orcado_rs  = s.orcado_rs,
                        data_inicio= s.data_inicio,
                        data_fim   = s.data_fim,
                        ordem      = s.ordem,
                    )
                    session.add(nova_sub)
                    n_subs += 1
            except Exception:
                pass  # ObraSubEtapa pode não existir em todos os ambientes

    session.commit()
    print(f"[duplicar_obra] '{novo_nome}' criada: {n_fases} fases, {n_etapas} etapas, {n_subs} sub-etapas → obra_id={nova_obra.id}")

    return RedirectResponse(f"/ferramentas/obras/{nova_obra.id}", status_code=303)


# ── Patch: adiciona botão "Duplicar" na lista e no detalhe ───────────────────

def _patch_duplicar_obra_templates():
    _dash = TEMPLATES.get("ferramenta_obras_lista.html") or TEMPLATES.get("dashboard.html", "")

    # Patch na lista de obras: botão após o ✏️
    if "_dup_obra_lista" not in str(TEMPLATES):
        for key in list(TEMPLATES.keys()):
            t = TEMPLATES[key]
            if 'btn btn-sm btn-outline-danger' in t and 'Apagar esta obra' in t and '_dup_obra_lista' not in t:
                TEMPLATES[key] = t.replace(
                    '<a href="/ferramentas/obras/{{ o.id }}/editar" class="btn btn-sm btn-outline-secondary">✏️</a>',
                    '<a href="/ferramentas/obras/{{ o.id }}/editar" class="btn btn-sm btn-outline-secondary">✏️</a>\n'
                    '        <a href="/ferramentas/obras/{{ o.id }}/duplicar" class="btn btn-sm btn-outline-secondary" title="Duplicar obra">📋</a><!-- _dup_obra_lista -->',
                    1
                )
                print(f"[duplicar_obra] ✅ botão duplicar injetado na lista ({key})")

    # Patch no detalhe: botão na barra de ações
    for key in list(TEMPLATES.keys()):
        t = TEMPLATES[key]
        if 'abrirNovaFase()' in t and '_dup_obra_detail' not in t:
            TEMPLATES[key] = t.replace(
                '<button onclick="abrirNovaFase()" class="btn btn-outline-secondary btn-sm">',
                '<a href="/ferramentas/obras/{{ obra.id }}/duplicar" class="btn btn-outline-secondary btn-sm" title="Duplicar obra completa">📋 Duplicar</a><!-- _dup_obra_detail -->\n'
                '    <button onclick="abrirNovaFase()" class="btn btn-outline-secondary btn-sm">',
                1
            )
            print(f"[duplicar_obra] ✅ botão duplicar injetado no detalhe ({key})")

    if hasattr(templates_env, "loader") and hasattr(templates_env.loader, "mapping"):
        templates_env.loader.mapping = TEMPLATES


_patch_duplicar_obra_templates()
print("[duplicar_obra] ✅ Duplicar Obra carregado")

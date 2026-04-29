# ============================================================================
# PATCH — Ferramenta: Gestão de Obras (Parte 1 — Modelos + Rotas)
# ============================================================================
# Salve como ui_ferramenta_obras.py e adicione ao final do app.py:
#   exec(open('ui_ferramenta_obras.py').read())
#
# MODELOS:
#   Obra, ObraFase, ObraEtapa, ObraApontamento
#
# ROTAS:
#   GET  /ferramentas/obras                    — lista obras do cliente
#   GET  /ferramentas/obras/nova               — form nova obra
#   POST /ferramentas/obras/nova               — salva nova obra
#   GET  /ferramentas/obras/{id}               — cronograma da obra
#   GET  /ferramentas/obras/{id}/editar        — edita obra
#   POST /ferramentas/obras/{id}/editar        — salva edição
#   POST /ferramentas/obras/{id}/fase/nova     — nova fase
#   POST /ferramentas/obras/{id}/etapa/nova    — nova etapa
#   POST /ferramentas/obras/etapa/{id}/apontar — apontamento físico+financeiro
#   POST /ferramentas/obras/etapa/{id}/editar  — edita orçado
#   POST /ferramentas/obras/etapa/{id}/apagar  — apaga etapa
#   POST /ferramentas/obras/fase/{id}/apagar   — apaga fase
#   GET  /ferramentas/obras/{id}/apagar        — apaga obra
# ============================================================================

import json as _json3
from typing import Optional as _Opt2
from datetime import date as _date
from sqlmodel import Field as _F2, SQLModel as _SM2, Relationship as _Rel


# ── Modelos ───────────────────────────────────────────────────────────────────

class Obra(_SM2, table=True):
    __tablename__  = "obra"
    __table_args__ = {"extend_existing": True}
    id:             _Opt2[int] = _F2(default=None, primary_key=True)
    company_id:     int        = _F2(index=True)
    client_id:      int        = _F2(index=True)
    nome:           str        = _F2(default="")
    endereco:       str        = _F2(default="")
    area_m2:        float      = _F2(default=0.0)
    cub_m2:         float      = _F2(default=3019.0)
    orcamento_total: float     = _F2(default=0.0)
    data_inicio:    str        = _F2(default="")
    data_fim:       str        = _F2(default="")
    status:         str        = _F2(default="em_andamento")  # em_andamento|concluida|paralisada
    obs:            str        = _F2(default="")
    created_at:     str        = _F2(default="")


class ObraFase(_SM2, table=True):
    __tablename__  = "obrafase"
    __table_args__ = {"extend_existing": True}
    id:          _Opt2[int] = _F2(default=None, primary_key=True)
    obra_id:     int        = _F2(index=True)
    nome:        str        = _F2(default="")
    ordem:       int        = _F2(default=0)
    orcado_rs:   float      = _F2(default=0.0)


class ObraEtapa(_SM2, table=True):
    __tablename__  = "obraetapa"
    __table_args__ = {"extend_existing": True}
    id:            _Opt2[int] = _F2(default=None, primary_key=True)
    fase_id:       int        = _F2(index=True)
    obra_id:       int        = _F2(index=True)
    descricao:     str        = _F2(default="")
    insumo:        str        = _F2(default="")   # Concreto/Aço/Empreitada/INSS/Diversos
    orcado_rs:     float      = _F2(default=0.0)
    data_inicio:   str        = _F2(default="")
    data_fim:      str        = _F2(default="")
    ordem:         int        = _F2(default=0)


class ObraApontamento(_SM2, table=True):
    __tablename__  = "obraapontamento"
    __table_args__ = {"extend_existing": True}
    id:               _Opt2[int] = _F2(default=None, primary_key=True)
    etapa_id:         int        = _F2(index=True)
    obra_id:          int        = _F2(index=True)
    versao:           str        = _F2(default="v1")
    data:             str        = _F2(default="")
    fisico_pct:       float      = _F2(default=0.0)   # 0-100
    financeiro_rs:    float      = _F2(default=0.0)
    obs:              str        = _F2(default="")
    created_at:       str        = _F2(default="")


# Cria tabelas
try:
    _SM2.metadata.create_all(engine, tables=[
        Obra.__table__, ObraFase.__table__,
        ObraEtapa.__table__, ObraApontamento.__table__,
    ])
except Exception:
    pass


# ── Modelo base de fases ──────────────────────────────────────────────────────

FASES_BASE = [
    {"nome": "Serviços Preliminares", "ordem": 1},
    {"nome": "Fundações",             "ordem": 2},
    {"nome": "Estrutura",             "ordem": 3},
    {"nome": "Alvenaria",             "ordem": 4},
    {"nome": "Cobertura",             "ordem": 5},
    {"nome": "Instalações Elétricas", "ordem": 6},
    {"nome": "Instalações Hidráulicas","ordem": 7},
    {"nome": "Reboco Interno",        "ordem": 8},
    {"nome": "Reboco Externo",        "ordem": 9},
    {"nome": "Gesso",                 "ordem": 10},
    {"nome": "Contrapiso",            "ordem": 11},
    {"nome": "Revestimentos",         "ordem": 12},
    {"nome": "Pintura",               "ordem": 13},
    {"nome": "Esquadrias",            "ordem": 14},
    {"nome": "Acabamentos",           "ordem": 15},
    {"nome": "Serviços Finais",       "ordem": 16},
]

INSUMOS = ["Concreto", "Aço", "Empreitada", "INSS", "Material", "Diversos", "Equipamentos", "Outros"]


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_obra_or_404(session, obra_id: int, company_id: int):
    obra = session.get(Obra, obra_id)
    if not obra or obra.company_id != company_id:
        return None
    return obra


def _calcular_obra(session, obra: Obra) -> dict:
    """Calcula indicadores consolidados de uma obra."""
    fases = session.exec(
        select(ObraFase).where(ObraFase.obra_id == obra.id).order_by(ObraFase.ordem)
    ).all()

    orcado_total  = 0.0
    realizado_rs  = 0.0
    fisico_total  = 0.0
    n_etapas      = 0
    fases_data    = []

    for fase in fases:
        etapas = session.exec(
            select(ObraEtapa).where(ObraEtapa.fase_id == fase.id).order_by(ObraEtapa.ordem)
        ).all()

        fase_orcado   = sum(e.orcado_rs for e in etapas)
        fase_real_rs  = 0.0
        fase_fisico   = 0.0
        etapas_data   = []

        for etapa in etapas:
            # Último apontamento
            apts = session.exec(
                select(ObraApontamento)
                .where(ObraApontamento.etapa_id == etapa.id)
                .order_by(ObraApontamento.id.desc())
                .limit(1)
            ).all()
            apt = apts[0] if apts else None

            fisico_pct   = apt.fisico_pct   if apt else 0.0
            financeiro_rs = apt.financeiro_rs if apt else 0.0
            versao       = apt.versao        if apt else "—"
            data_apt     = apt.data          if apt else "—"

            # Desvio: financeiro_real / (orcado × % fisico)
            esperado = etapa.orcado_rs * (fisico_pct / 100) if fisico_pct > 0 else 0
            desvio_rs = financeiro_rs - esperado
            desvio_pct = (desvio_rs / esperado * 100) if esperado > 0 else 0

            # Histórico de apontamentos
            historico = session.exec(
                select(ObraApontamento)
                .where(ObraApontamento.etapa_id == etapa.id)
                .order_by(ObraApontamento.id.desc())
            ).all()

            etapas_data.append({
                "id":           etapa.id,
                "fase_id":      fase.id,
                "descricao":    etapa.descricao,
                "insumo":       etapa.insumo,
                "orcado_rs":    etapa.orcado_rs,
                "data_inicio":  etapa.data_inicio,
                "data_fim":     etapa.data_fim,
                "fisico_pct":   fisico_pct,
                "financeiro_rs": financeiro_rs,
                "versao":       versao,
                "data_apt":     data_apt,
                "desvio_rs":    round(desvio_rs, 2),
                "desvio_pct":   round(desvio_pct, 1),
                "a_incorrer":   round(etapa.orcado_rs - financeiro_rs, 2),
                "historico":    [{"versao": h.versao, "data": h.data,
                                  "fisico": h.fisico_pct, "financeiro": h.financeiro_rs,
                                  "obs": h.obs} for h in historico],
            })

            fase_real_rs += financeiro_rs
            fase_fisico  += fisico_pct
            orcado_total += etapa.orcado_rs
            realizado_rs += financeiro_rs
            n_etapas     += 1

        fase_fisico_med = fase_fisico / len(etapas) if etapas else 0
        fase_desvio     = fase_real_rs - (fase_orcado * fase_fisico_med / 100) if fase_fisico_med > 0 else 0

        fases_data.append({
            "id":          fase.id,
            "nome":        fase.nome,
            "ordem":       fase.ordem,
            "orcado_rs":   fase_orcado,
            "realizado_rs": fase_real_rs,
            "fisico_pct":  round(fase_fisico_med, 1),
            "desvio_rs":   round(fase_desvio, 2),
            "a_incorrer":  round(fase_orcado - fase_real_rs, 2),
            "etapas":      etapas_data,
        })

        fisico_total += fase_fisico_med

    fisico_geral = fisico_total / len(fases) if fases else 0
    orcado_total_obra = obra.orcamento_total or orcado_total

    esperado_geral = orcado_total_obra * (fisico_geral / 100) if fisico_geral > 0 else 0
    desvio_geral   = realizado_rs - esperado_geral

    # Índice de Desempenho de Custo (IDC = esperado / realizado)
    idc = esperado_geral / realizado_rs if realizado_rs > 0 else 1.0

    # Projeção de custo final
    projecao_final = orcado_total_obra / idc if idc > 0 else orcado_total_obra

    return {
        "fases":          fases_data,
        "orcado_total":   round(orcado_total_obra, 2),
        "realizado_rs":   round(realizado_rs, 2),
        "a_incorrer":     round(orcado_total_obra - realizado_rs, 2),
        "fisico_geral":   round(fisico_geral, 1),
        "desvio_geral":   round(desvio_geral, 2),
        "idc":            round(idc, 3),
        "projecao_final": round(projecao_final, 2),
        "n_etapas":       n_etapas,
        "n_fases":        len(fases),
    }


# ── Rota: lista de obras ──────────────────────────────────────────────────────

@app.get("/ferramentas/obras", response_class=HTMLResponse)
@require_login
async def obras_lista(request: Request, session: Session = Depends(get_session)):
    ctx = get_tenant_context(request, session)
    if not ctx:
        request.session.clear(); return RedirectResponse("/login", status_code=303)
    cc = get_client_or_none(session, ctx.company.id, get_active_client_id(request, session, ctx))
    if not cc:
        return RedirectResponse("/ferramentas", status_code=303)

    obras_raw = session.exec(
        select(Obra).where(Obra.company_id == ctx.company.id, Obra.client_id == cc.id)
        .order_by(Obra.id.desc())
    ).all()

    obras = []
    for o in obras_raw:
        calc = _calcular_obra(session, o)
        obras.append({"obra": o, "calc": calc})

    return render("ferramenta_obras_lista.html", request=request, context={
        "current_user": ctx.user, "current_company": ctx.company,
        "role": ctx.membership.role, "current_client": cc,
        "obras": obras,
    })


# ── Rota: nova obra ───────────────────────────────────────────────────────────

@app.get("/ferramentas/obras/nova", response_class=HTMLResponse)
@require_login
async def obras_nova_get(request: Request, session: Session = Depends(get_session)):
    ctx = get_tenant_context(request, session)
    if not ctx:
        request.session.clear(); return RedirectResponse("/login", status_code=303)
    cc = get_client_or_none(session, ctx.company.id, get_active_client_id(request, session, ctx))
    return render("ferramenta_obras_form.html", request=request, context={
        "current_user": ctx.user, "current_company": ctx.company,
        "role": ctx.membership.role, "current_client": cc,
        "obra": None, "fases_base": FASES_BASE,
    })


@app.post("/ferramentas/obras/nova", response_class=HTMLResponse)
@require_login
async def obras_nova_post(request: Request, session: Session = Depends(get_session)):
    ctx = get_tenant_context(request, session)
    if not ctx:
        request.session.clear(); return RedirectResponse("/login", status_code=303)
    cc = get_client_or_none(session, ctx.company.id, get_active_client_id(request, session, ctx))
    if not cc:
        return RedirectResponse("/ferramentas", status_code=303)

    form = await request.form()
    usar_modelo = form.get("usar_modelo") == "1"

    obra = Obra(
        company_id=ctx.company.id,
        client_id=cc.id,
        nome=form.get("nome", ""),
        endereco=form.get("endereco", ""),
        area_m2=float(form.get("area_m2", 0) or 0),
        cub_m2=float(form.get("cub_m2", 3019) or 3019),
        orcamento_total=float(form.get("orcamento_total", 0) or 0),
        data_inicio=form.get("data_inicio", ""),
        data_fim=form.get("data_fim", ""),
        obs=form.get("obs", ""),
        created_at=str(utcnow()),
    )
    session.add(obra)
    session.commit()
    session.refresh(obra)

    # Cria fases do modelo base se solicitado
    if usar_modelo:
        for fb in FASES_BASE:
            fase = ObraFase(obra_id=obra.id, nome=fb["nome"], ordem=fb["ordem"])
            session.add(fase)
        session.commit()

    return RedirectResponse(f"/ferramentas/obras/{obra.id}", status_code=303)


# ── Rota: cronograma da obra ──────────────────────────────────────────────────

@app.get("/ferramentas/obras/{obra_id}", response_class=HTMLResponse)
@require_login
async def obras_cronograma(obra_id: int, request: Request, session: Session = Depends(get_session)):
    ctx = get_tenant_context(request, session)
    if not ctx:
        request.session.clear(); return RedirectResponse("/login", status_code=303)
    obra = _get_obra_or_404(session, obra_id, ctx.company.id)
    if not obra:
        return RedirectResponse("/ferramentas/obras", status_code=303)
    cc = get_client_or_none(session, ctx.company.id, obra.client_id)
    calc = _calcular_obra(session, obra)

    return render("ferramenta_obras_cronograma.html", request=request, context={
        "current_user": ctx.user, "current_company": ctx.company,
        "role": ctx.membership.role, "current_client": cc,
        "obra": obra, "calc": calc, "insumos": INSUMOS,
    })


# ── Rota: nova fase ───────────────────────────────────────────────────────────

@app.post("/ferramentas/obras/{obra_id}/fase/nova")
@require_login
async def obras_fase_nova(obra_id: int, request: Request, session: Session = Depends(get_session)):
    ctx = get_tenant_context(request, session)
    if not ctx:
        return JSONResponse({"ok": False}, status_code=401)
    obra = _get_obra_or_404(session, obra_id, ctx.company.id)
    if not obra:
        return JSONResponse({"ok": False}, status_code=404)

    body = await request.json()
    ultima = session.exec(
        select(ObraFase).where(ObraFase.obra_id == obra_id).order_by(ObraFase.ordem.desc()).limit(1)
    ).first()
    ordem = (ultima.ordem + 1) if ultima else 1

    fase = ObraFase(obra_id=obra_id, nome=body.get("nome", "Nova Fase"), ordem=ordem)
    session.add(fase); session.commit(); session.refresh(fase)
    return JSONResponse({"ok": True, "id": fase.id, "nome": fase.nome, "ordem": fase.ordem})


# ── Rota: nova etapa ──────────────────────────────────────────────────────────

@app.post("/ferramentas/obras/{obra_id}/etapa/nova")
@require_login
async def obras_etapa_nova(obra_id: int, request: Request, session: Session = Depends(get_session)):
    ctx = get_tenant_context(request, session)
    if not ctx:
        return JSONResponse({"ok": False}, status_code=401)
    obra = _get_obra_or_404(session, obra_id, ctx.company.id)
    if not obra:
        return JSONResponse({"ok": False}, status_code=404)

    body = await request.json()
    fase_id = int(body.get("fase_id", 0))
    fase = session.get(ObraFase, fase_id)
    if not fase or fase.obra_id != obra_id:
        return JSONResponse({"ok": False, "erro": "Fase não encontrada"}, status_code=404)

    ultima = session.exec(
        select(ObraEtapa).where(ObraEtapa.fase_id == fase_id).order_by(ObraEtapa.ordem.desc()).limit(1)
    ).first()
    ordem = (ultima.ordem + 1) if ultima else 1

    etapa = ObraEtapa(
        fase_id=fase_id, obra_id=obra_id,
        descricao=body.get("descricao", ""),
        insumo=body.get("insumo", ""),
        orcado_rs=float(body.get("orcado_rs", 0) or 0),
        data_inicio=body.get("data_inicio", ""),
        data_fim=body.get("data_fim", ""),
        ordem=ordem,
    )
    session.add(etapa); session.commit(); session.refresh(etapa)
    return JSONResponse({"ok": True, "id": etapa.id})


# ── Rota: apontamento ─────────────────────────────────────────────────────────

@app.post("/ferramentas/obras/etapa/{etapa_id}/apontar")
@require_login
async def obras_apontar(etapa_id: int, request: Request, session: Session = Depends(get_session)):
    ctx = get_tenant_context(request, session)
    if not ctx:
        return JSONResponse({"ok": False}, status_code=401)

    etapa = session.get(ObraEtapa, etapa_id)
    if not etapa:
        return JSONResponse({"ok": False}, status_code=404)
    obra = _get_obra_or_404(session, etapa.obra_id, ctx.company.id)
    if not obra:
        return JSONResponse({"ok": False}, status_code=403)

    body = await request.json()

    # Versão automática
    n = session.exec(
        select(ObraApontamento).where(ObraApontamento.etapa_id == etapa_id)
    ).all()
    versao = f"v{len(n) + 1}"

    apt = ObraApontamento(
        etapa_id=etapa_id,
        obra_id=etapa.obra_id,
        versao=versao,
        data=body.get("data", str(_date.today())),
        fisico_pct=float(body.get("fisico_pct", 0) or 0),
        financeiro_rs=float(body.get("financeiro_rs", 0) or 0),
        obs=body.get("obs", ""),
        created_at=str(utcnow()),
    )
    session.add(apt); session.commit()

    # Recalcula indicadores da obra para retornar ao frontend
    calc = _calcular_obra(session, obra)
    return JSONResponse({
        "ok": True, "versao": versao,
        "fisico_geral": calc["fisico_geral"],
        "realizado_rs": calc["realizado_rs"],
        "idc": calc["idc"],
    })


# ── Rota: editar etapa (orçado) ───────────────────────────────────────────────

@app.post("/ferramentas/obras/etapa/{etapa_id}/editar")
@require_login
async def obras_etapa_editar(etapa_id: int, request: Request, session: Session = Depends(get_session)):
    ctx = get_tenant_context(request, session)
    if not ctx:
        return JSONResponse({"ok": False}, status_code=401)
    etapa = session.get(ObraEtapa, etapa_id)
    if not etapa:
        return JSONResponse({"ok": False}, status_code=404)
    obra = _get_obra_or_404(session, etapa.obra_id, ctx.company.id)
    if not obra:
        return JSONResponse({"ok": False}, status_code=403)

    body = await request.json()
    if "descricao" in body:  etapa.descricao  = body["descricao"]
    if "insumo" in body:     etapa.insumo     = body["insumo"]
    if "orcado_rs" in body:  etapa.orcado_rs  = float(body["orcado_rs"] or 0)
    if "data_inicio" in body: etapa.data_inicio = body["data_inicio"]
    if "data_fim" in body:   etapa.data_fim   = body["data_fim"]
    session.add(etapa); session.commit()
    return JSONResponse({"ok": True})


# ── Rota: apagar etapa ────────────────────────────────────────────────────────

@app.post("/ferramentas/obras/etapa/{etapa_id}/apagar")
@require_login
async def obras_etapa_apagar(etapa_id: int, request: Request, session: Session = Depends(get_session)):
    ctx = get_tenant_context(request, session)
    if not ctx:
        return JSONResponse({"ok": False}, status_code=401)
    etapa = session.get(ObraEtapa, etapa_id)
    if not etapa:
        return JSONResponse({"ok": False}, status_code=404)
    obra = _get_obra_or_404(session, etapa.obra_id, ctx.company.id)
    if not obra:
        return JSONResponse({"ok": False}, status_code=403)

    # Remove apontamentos
    apts = session.exec(select(ObraApontamento).where(ObraApontamento.etapa_id == etapa_id)).all()
    for a in apts: session.delete(a)
    session.delete(etapa); session.commit()
    return JSONResponse({"ok": True})


# ── Rota: apagar fase ─────────────────────────────────────────────────────────

@app.post("/ferramentas/obras/fase/{fase_id}/apagar")
@require_login
async def obras_fase_apagar(fase_id: int, request: Request, session: Session = Depends(get_session)):
    ctx = get_tenant_context(request, session)
    if not ctx:
        return JSONResponse({"ok": False}, status_code=401)
    fase = session.get(ObraFase, fase_id)
    if not fase:
        return JSONResponse({"ok": False}, status_code=404)
    obra = _get_obra_or_404(session, fase.obra_id, ctx.company.id)
    if not obra:
        return JSONResponse({"ok": False}, status_code=403)

    etapas = session.exec(select(ObraEtapa).where(ObraEtapa.fase_id == fase_id)).all()
    for e in etapas:
        apts = session.exec(select(ObraApontamento).where(ObraApontamento.etapa_id == e.id)).all()
        for a in apts: session.delete(a)
        session.delete(e)
    session.delete(fase); session.commit()
    return JSONResponse({"ok": True})


# ── Rota: apagar obra ─────────────────────────────────────────────────────────

@app.get("/ferramentas/obras/{obra_id}/apagar")
@require_login
async def obras_apagar(obra_id: int, request: Request, session: Session = Depends(get_session)):
    ctx = get_tenant_context(request, session)
    if not ctx:
        request.session.clear(); return RedirectResponse("/login", status_code=303)
    obra = _get_obra_or_404(session, obra_id, ctx.company.id)
    if not obra:
        return RedirectResponse("/ferramentas/obras", status_code=303)

    fases = session.exec(select(ObraFase).where(ObraFase.obra_id == obra_id)).all()
    for f in fases:
        etapas = session.exec(select(ObraEtapa).where(ObraEtapa.fase_id == f.id)).all()
        for e in etapas:
            apts = session.exec(select(ObraApontamento).where(ObraApontamento.etapa_id == e.id)).all()
            for a in apts: session.delete(a)
            session.delete(e)
        session.delete(f)
    session.delete(obra); session.commit()
    return RedirectResponse("/ferramentas/obras", status_code=303)


# ── Rota: editar obra ─────────────────────────────────────────────────────────

@app.get("/ferramentas/obras/{obra_id}/editar", response_class=HTMLResponse)
@require_login
async def obras_editar_get(obra_id: int, request: Request, session: Session = Depends(get_session)):
    ctx = get_tenant_context(request, session)
    if not ctx:
        request.session.clear(); return RedirectResponse("/login", status_code=303)
    obra = _get_obra_or_404(session, obra_id, ctx.company.id)
    if not obra:
        return RedirectResponse("/ferramentas/obras", status_code=303)
    cc = get_client_or_none(session, ctx.company.id, obra.client_id)
    return render("ferramenta_obras_form.html", request=request, context={
        "current_user": ctx.user, "current_company": ctx.company,
        "role": ctx.membership.role, "current_client": cc,
        "obra": obra, "fases_base": FASES_BASE,
    })


@app.post("/ferramentas/obras/{obra_id}/editar", response_class=HTMLResponse)
@require_login
async def obras_editar_post(obra_id: int, request: Request, session: Session = Depends(get_session)):
    ctx = get_tenant_context(request, session)
    if not ctx:
        request.session.clear(); return RedirectResponse("/login", status_code=303)
    obra = _get_obra_or_404(session, obra_id, ctx.company.id)
    if not obra:
        return RedirectResponse("/ferramentas/obras", status_code=303)

    form = await request.form()
    obra.nome            = form.get("nome", obra.nome)
    obra.endereco        = form.get("endereco", obra.endereco)
    obra.area_m2         = float(form.get("area_m2", obra.area_m2) or obra.area_m2)
    obra.cub_m2          = float(form.get("cub_m2", obra.cub_m2) or obra.cub_m2)
    obra.orcamento_total = float(form.get("orcamento_total", obra.orcamento_total) or obra.orcamento_total)
    obra.data_inicio     = form.get("data_inicio", obra.data_inicio)
    obra.data_fim        = form.get("data_fim", obra.data_fim)
    obra.status          = form.get("status", obra.status)
    obra.obs             = form.get("obs", obra.obs)
    session.add(obra); session.commit()
    return RedirectResponse(f"/ferramentas/obras/{obra_id}", status_code=303)

if hasattr(templates_env.loader, "mapping"):
    templates_env.loader.mapping = TEMPLATES

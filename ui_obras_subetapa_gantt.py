# =============================================================================
# Gestão de Obras — Sub-etapa + Gantt + Modelo Base rico
# Estritamente ADITIVO — não modifica tabelas ou campos existentes
# =============================================================================

import json as _json_se
from typing import Optional as _OptSE
from sqlmodel import Field as _FSE, SQLModel as _SMSE

# ── Modelo SubEtapa ────────────────────────────────────────────────────────────

class ObraSubEtapa(_SMSE, table=True):
    __tablename__  = "obrasubetapa"
    __table_args__ = {"extend_existing": True}
    id:          _OptSE[int] = _FSE(default=None, primary_key=True)
    etapa_id:    int         = _FSE(index=True)
    obra_id:     int         = _FSE(index=True)
    descricao:   str         = _FSE(default="")
    insumo:      str         = _FSE(default="")
    orcado_rs:   float       = _FSE(default=0.0)
    data_inicio: str         = _FSE(default="")
    data_fim:    str         = _FSE(default="")
    ordem:       int         = _FSE(default=0)

try:
    _SMSE.metadata.create_all(engine, tables=[ObraSubEtapa.__table__])
except Exception:
    pass


# ── Modelo base rico (Fase → Etapa → Sub-etapa) ───────────────────────────────

FASES_BASE_MODELO = [
    # ── DESPESAS INDIRETAS ──────────────────────────────────────────────────
    {
        "nome": "Gerenciamento Técnico", "ordem": 1,
        "etapas": [
            {"descricao": "Segurança, Meio Ambiente, Saúde", "ordem": 1,
             "subetapas": ["Estudos", "Projetos", "Consultorias", "Ensaios e Laudos"]},
            {"descricao": "Taxas e Documentos", "ordem": 2,
             "subetapas": ["Seguros", "Licenciamentos, Taxas, Impostos", "Documentos"]},
        ],
    },
    {
        "nome": "Gerenciamento Administrativo", "ordem": 2,
        "etapas": [
            {"descricao": "Segurança, Meio Ambiente, Saúde", "ordem": 1,
             "subetapas": ["Segurança do trabalho", "Equipamentos de proteção", "Meio ambiente"]},
            {"descricao": "Administração e Canteiro de Obra", "ordem": 2,
             "subetapas": ["Equipe de Gestão e Apoio", "Operação Inicial do Canteiro",
                           "Instalações provisórias", "Despesas de Consumo e Manutenção"]},
            {"descricao": "Equipamentos", "ordem": 3,
             "subetapas": ["Equipamentos de carga e transporte", "Balancins e Andaimes"]},
        ],
    },
    # ── GERENCIAMENTO EXECUTIVO ─────────────────────────────────────────────
    {
        "nome": "Movimentação de Terra", "ordem": 3,
        "etapas": [
            {"descricao": "Movimentação de Terra", "ordem": 1,
             "subetapas": ["Movimentação de Terra"]},
        ],
    },
    {
        "nome": "Infraestrutura", "ordem": 4,
        "etapas": [
            {"descricao": "Fundação Profunda", "ordem": 1,
             "subetapas": ["Perfuração", "Mão de obra de apoio e arrasamento das estacas"]},
            {"descricao": "Fundação Rasa", "ordem": 2,
             "subetapas": ["Formas para blocos e baldrames", "Mão de obra infraestrutura"]},
        ],
    },
    {
        "nome": "Supraestrutura", "ordem": 5,
        "etapas": [
            {"descricao": "Supraestrutura", "ordem": 1,
             "subetapas": ["Formas", "Armadura", "Concreto", "Protensão",
                           "Complementares", "Mão de Obra"]},
        ],
    },
    {
        "nome": "Paredes e Painéis", "ordem": 6,
        "etapas": [
            {"descricao": "Paredes e Painéis", "ordem": 1,
             "subetapas": ["Alvenaria de vedação", "Serviços complementares", "Mão de obra"]},
        ],
    },
    {
        "nome": "Impermeabilização e Tratamentos", "ordem": 7,
        "etapas": [
            {"descricao": "Impermeabilização e Tratamentos", "ordem": 1,
             "subetapas": ["Regularização e Proteção Mecânica", "Impermeabilização"]},
        ],
    },
    {
        "nome": "Instalações Elétricas, Hidráulicas e GLP", "ordem": 8,
        "etapas": [
            {"descricao": "Instalações Hidrossanitárias e Drenagem", "ordem": 1,
             "subetapas": ["Sistemas Hidrossanitários e Drenagem", "Mão de Obra"]},
            {"descricao": "Instalações Elétricas", "ordem": 2,
             "subetapas": ["Sistemas Elétricos", "Mão de Obra"]},
            {"descricao": "Instalações Preventivas e GLP", "ordem": 3,
             "subetapas": ["Instalações Preventivas"]},
        ],
    },
    {
        "nome": "Equipamentos e Sistemas Especiais", "ordem": 9,
        "etapas": [
            {"descricao": "Climatização, Exaustão e Pressurização", "ordem": 1,
             "subetapas": ["Climatização, exaustão mecânica e pressurização"]},
            {"descricao": "Comunicação", "ordem": 2,
             "subetapas": ["Comunicação"]},
            {"descricao": "Equipamentos", "ordem": 3,
             "subetapas": ["Equipamentos"]},
            {"descricao": "Outros Sistemas Especiais", "ordem": 4,
             "subetapas": ["Outros sistemas"]},
        ],
    },
    {
        "nome": "Revestimentos Internos — Piso e Parede", "ordem": 10,
        "etapas": [
            {"descricao": "Revestimentos Internos em Piso e Parede", "ordem": 1,
             "subetapas": ["Revestimento de piso", "Revestimento de parede"]},
        ],
    },
    {
        "nome": "Revestimentos Internos — Teto", "ordem": 11,
        "etapas": [
            {"descricao": "Revestimentos e Acabamentos Internos em Teto", "ordem": 1,
             "subetapas": ["Chapisco e reboco", "Forro de gesso"]},
        ],
    },
    {
        "nome": "Acabamentos em Piso e Parede", "ordem": 12,
        "etapas": [
            {"descricao": "Acabamentos em Piso e Parede", "ordem": 1,
             "subetapas": ["Acabamentos de piso", "Acabamentos de parede"]},
        ],
    },
    {
        "nome": "Pintura Interna", "ordem": 13,
        "etapas": [
            {"descricao": "Sistemas de Pintura Interna", "ordem": 1,
             "subetapas": ["Pintura interna"]},
        ],
    },
    {
        "nome": "Esquadrias, Vidros e Ferragens", "ordem": 14,
        "etapas": [
            {"descricao": "Esquadrias, Vidros e Ferragens", "ordem": 1,
             "subetapas": ["Alumínio", "Esquadrias de madeira", "Esquadrias metálicas"]},
        ],
    },
    {
        "nome": "Revestimentos e Acabamentos em Fachada", "ordem": 15,
        "etapas": [
            {"descricao": "Revestimentos e Acabamentos em Fachada", "ordem": 1,
             "subetapas": ["Revestimento argamassado em fachada", "Acabamento externo"]},
        ],
    },
    {
        "nome": "Serviços Complementares e Finais", "ordem": 16,
        "etapas": [
            {"descricao": "Serviços Complementares e Finais", "ordem": 1,
             "subetapas": ["Móveis e decoração"]},
        ],
    },
    {
        "nome": "Imprevistos e Contingências", "ordem": 17,
        "etapas": [
            {"descricao": "Imprevistos e Contingências", "ordem": 1,
             "subetapas": ["Imprevistos e contingências"]},
        ],
    },
]

# Compatibilidade: mantém FASES_BASE simples para o form de criação
FASES_BASE = [{"nome": f["nome"], "ordem": f["ordem"]} for f in FASES_BASE_MODELO]


# ── Override: _calcular_obra com sub-etapas ────────────────────────────────────

def _calcular_obra(session, obra):
    fases = session.exec(
        select(ObraFase).where(ObraFase.obra_id == obra.id).order_by(ObraFase.ordem)
    ).all()

    orcado_total  = 0.0
    realizado_rs  = 0.0
    n_etapas      = 0
    fases_data    = []

    for fase in fases:
        etapas = session.exec(
            select(ObraEtapa).where(ObraEtapa.fase_id == fase.id).order_by(ObraEtapa.ordem)
        ).all()

        fase_orcado  = sum(e.orcado_rs for e in etapas)
        fase_real_rs = 0.0
        fase_fisico  = 0.0
        etapas_data  = []

        for etapa in etapas:
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

            esperado  = etapa.orcado_rs * (fisico_pct / 100) if fisico_pct > 0 else 0
            desvio_rs = financeiro_rs - esperado
            desvio_pct = (desvio_rs / esperado * 100) if esperado > 0 else 0

            historico = session.exec(
                select(ObraApontamento)
                .where(ObraApontamento.etapa_id == etapa.id)
                .order_by(ObraApontamento.id.desc())
            ).all()

            # Sub-etapas
            subetapas_raw = session.exec(
                select(ObraSubEtapa)
                .where(ObraSubEtapa.etapa_id == etapa.id)
                .order_by(ObraSubEtapa.ordem)
            ).all()
            subetapas_data = [
                {
                    "id":          se.id,
                    "etapa_id":    se.etapa_id,
                    "descricao":   se.descricao,
                    "insumo":      se.insumo,
                    "orcado_rs":   se.orcado_rs,
                    "data_inicio": se.data_inicio,
                    "data_fim":    se.data_fim,
                    "ordem":       se.ordem,
                }
                for se in subetapas_raw
            ]

            etapas_data.append({
                "id":            etapa.id,
                "fase_id":       fase.id,
                "descricao":     etapa.descricao,
                "insumo":        etapa.insumo,
                "orcado_rs":     etapa.orcado_rs,
                "data_inicio":   etapa.data_inicio,
                "data_fim":      etapa.data_fim,
                "fisico_pct":    fisico_pct,
                "financeiro_rs": financeiro_rs,
                "versao":        versao,
                "data_apt":      data_apt,
                "desvio_rs":     round(desvio_rs, 2),
                "desvio_pct":    round(desvio_pct, 1),
                "a_incorrer":    round(etapa.orcado_rs - financeiro_rs, 2),
                "historico":     [{"versao": h.versao, "data": h.data,
                                   "fisico": h.fisico_pct, "financeiro": h.financeiro_rs,
                                   "obs": h.obs} for h in historico],
                "subetapas":     subetapas_data,
            })

            fase_real_rs += financeiro_rs
            fase_fisico  += fisico_pct
            orcado_total += etapa.orcado_rs
            realizado_rs += financeiro_rs
            n_etapas     += 1

        fase_fisico_med = fase_fisico / len(etapas) if etapas else 0
        fases_data.append({
            "id":           fase.id,
            "nome":         fase.nome,
            "ordem":        fase.ordem,
            "orcado_rs":    fase_orcado,
            "realizado_rs": fase_real_rs,
            "fisico_pct":   round(fase_fisico_med, 1),
            "desvio_rs":    round(fase_real_rs - (fase_orcado * fase_fisico_med / 100) if fase_fisico_med > 0 else 0, 2),
            "a_incorrer":   round(fase_orcado - fase_real_rs, 2),
            "etapas":       etapas_data,
        })

    orcado_total_obra = obra.orcamento_total or orcado_total

    ev_total = sum(
        e["orcado_rs"] * (e["fisico_pct"] / 100)
        for fase in fases_data
        for e in fase["etapas"]
    )
    fisico_geral   = (ev_total / orcado_total * 100) if orcado_total > 0 else 0
    idc            = round(ev_total / realizado_rs, 3) if realizado_rs > 0 else 1.0
    desvio_geral   = realizado_rs - ev_total
    projecao_final = round(orcado_total_obra / idc, 2) if idc > 0 else orcado_total_obra

    for fase_d in fases_data:
        fo = fase_d["orcado_rs"]
        if fo > 0:
            fev = sum(e["orcado_rs"] * (e["fisico_pct"] / 100) for e in fase_d["etapas"])
            fase_d["fisico_pct"] = round(fev / fo * 100, 1)
        fase_d["desvio_rs"] = round(
            sum(e["financeiro_rs"] - e["orcado_rs"] * (e["fisico_pct"] / 100)
                for e in fase_d["etapas"]), 2
        )

    return {
        "fases":          fases_data,
        "orcado_total":   round(orcado_total_obra, 2),
        "realizado_rs":   round(realizado_rs, 2),
        "ev_total":       round(ev_total, 2),
        "a_incorrer":     round(orcado_total_obra - realizado_rs, 2),
        "fisico_geral":   round(fisico_geral, 1),
        "desvio_geral":   round(desvio_geral, 2),
        "idc":            round(idc, 3),
        "projecao_final": round(projecao_final, 2),
        "n_etapas":       n_etapas,
        "n_fases":        len(fases),
    }


# ── Override: obras_nova_post — cria fases + etapas + sub-etapas do modelo ────

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

    if usar_modelo:
        for fb in FASES_BASE_MODELO:
            fase = ObraFase(obra_id=obra.id, nome=fb["nome"], ordem=fb["ordem"])
            session.add(fase)
            session.commit()
            session.refresh(fase)
            for eb in fb.get("etapas", []):
                etapa = ObraEtapa(
                    fase_id=fase.id, obra_id=obra.id,
                    descricao=eb["descricao"],
                    insumo="", orcado_rs=0.0,
                    data_inicio="", data_fim="",
                    ordem=eb["ordem"],
                )
                session.add(etapa)
                session.commit()
                session.refresh(etapa)
                for i, sb in enumerate(eb.get("subetapas", []), 1):
                    subetapa = ObraSubEtapa(
                        etapa_id=etapa.id, obra_id=obra.id,
                        descricao=sb, insumo="", orcado_rs=0.0,
                        data_inicio="", data_fim="", ordem=i,
                    )
                    session.add(subetapa)
            session.commit()

    return RedirectResponse(f"/ferramentas/obras/{obra.id}", status_code=303)


# ── Rota: nova sub-etapa ──────────────────────────────────────────────────────

@app.post("/ferramentas/obras/{obra_id}/subetapa/nova")
@require_login
async def obras_subetapa_nova(obra_id: int, request: Request, session: Session = Depends(get_session)):
    ctx = get_tenant_context(request, session)
    if not ctx:
        return JSONResponse({"ok": False}, status_code=401)
    obra = _get_obra_or_404(session, obra_id, ctx.company.id)
    if not obra:
        return JSONResponse({"ok": False}, status_code=404)

    body = await request.json()
    etapa_id = int(body.get("etapa_id", 0))
    etapa = session.get(ObraEtapa, etapa_id)
    if not etapa or etapa.obra_id != obra_id:
        return JSONResponse({"ok": False, "erro": "Etapa não encontrada"}, status_code=404)

    ultima = session.exec(
        select(ObraSubEtapa).where(ObraSubEtapa.etapa_id == etapa_id)
        .order_by(ObraSubEtapa.ordem.desc()).limit(1)
    ).first()
    ordem = (ultima.ordem + 1) if ultima else 1

    se = ObraSubEtapa(
        etapa_id=etapa_id, obra_id=obra_id,
        descricao=body.get("descricao", ""),
        insumo=body.get("insumo", ""),
        orcado_rs=float(body.get("orcado_rs", 0) or 0),
        data_inicio=body.get("data_inicio", ""),
        data_fim=body.get("data_fim", ""),
        ordem=ordem,
    )
    session.add(se); session.commit(); session.refresh(se)
    return JSONResponse({"ok": True, "id": se.id})


# ── Rota: editar sub-etapa ────────────────────────────────────────────────────

@app.post("/ferramentas/obras/subetapa/{se_id}/editar")
@require_login
async def obras_subetapa_editar(se_id: int, request: Request, session: Session = Depends(get_session)):
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
    if "descricao"   in body: se.descricao   = body["descricao"]
    if "insumo"      in body: se.insumo      = body["insumo"]
    if "orcado_rs"   in body: se.orcado_rs   = float(body["orcado_rs"] or 0)
    if "data_inicio" in body: se.data_inicio = body["data_inicio"]
    if "data_fim"    in body: se.data_fim    = body["data_fim"]
    session.add(se); session.commit()
    return JSONResponse({"ok": True})


# ── Rota: apagar sub-etapa ────────────────────────────────────────────────────

@app.post("/ferramentas/obras/subetapa/{se_id}/apagar")
@require_login
async def obras_subetapa_apagar(se_id: int, request: Request, session: Session = Depends(get_session)):
    ctx = get_tenant_context(request, session)
    if not ctx:
        return JSONResponse({"ok": False}, status_code=401)
    se = session.get(ObraSubEtapa, se_id)
    if not se:
        return JSONResponse({"ok": False}, status_code=404)
    obra = _get_obra_or_404(session, se.obra_id, ctx.company.id)
    if not obra:
        return JSONResponse({"ok": False}, status_code=403)
    session.delete(se); session.commit()
    return JSONResponse({"ok": True})


# ── Patch do template cronograma ──────────────────────────────────────────────

def _patch_subetapa_gantt():
    tpl = TEMPLATES.get("ferramenta_obras_cronograma.html", "")
    if not tpl or "_seGanttV1" in tpl:
        return

    changed = False

    # ── A: CSS para sub-etapas ─────────────────────────────────────────────
    _OLD_CSS = "  @media print{.no-print{display:none!important;}}\n</style>"
    _NEW_CSS = (
        "  @media print{.no-print{display:none!important;}}\n"
        "  /* sub-etapas */\n"
        "  .cr-subetapa{display:grid;grid-template-columns:2fr 1fr 1fr auto;gap:.4rem;"
        "align-items:center;padding:.3rem .85rem .3rem 2.5rem;border-left:3px solid #e2e8f0;"
        "margin-left:.85rem;margin-bottom:.15rem;font-size:.78rem;background:#fafbfc;"
        "border-radius:0 6px 6px 0;}\n"
        "  .cr-subetapa:hover{background:#f1f5f9;}\n"
        "  .se-badge{font-size:.62rem;padding:.1rem .4rem;border-radius:999px;"
        "background:#f1f5f9;color:#64748b;border:1px solid #e2e8f0;}\n"
        "  /* Gantt */\n"
        "  .gantt-wrap{overflow-x:auto;margin-bottom:1rem;}\n"
        "  .gantt-grid{position:relative;min-width:600px;}\n"
        "  .gantt-row{display:flex;align-items:center;min-height:28px;margin-bottom:3px;"
        "font-size:.75rem;}\n"
        "  .gantt-label{width:220px;min-width:220px;overflow:hidden;white-space:nowrap;"
        "text-overflow:ellipsis;padding-right:.75rem;flex-shrink:0;}\n"
        "  .gantt-track{flex:1;position:relative;height:18px;background:#f3f4f6;"
        "border-radius:4px;overflow:visible;}\n"
        "  .gantt-bar{position:absolute;top:0;height:100%;border-radius:4px;"
        "opacity:.85;display:flex;align-items:center;padding:0 4px;"
        "font-size:.6rem;color:#fff;white-space:nowrap;overflow:hidden;}\n"
        "  .gantt-header{display:flex;margin-bottom:.4rem;}\n"
        "  .gantt-header-space{width:220px;min-width:220px;flex-shrink:0;}\n"
        "  .gantt-months{flex:1;display:flex;position:relative;}\n"
        "  .gantt-month-tick{flex:1;border-left:1px solid #e5e7eb;font-size:.62rem;"
        "color:#94a3b8;padding-left:3px;overflow:hidden;white-space:nowrap;}\n"
        "  .gantt-row.fase-row .gantt-label{font-weight:700;color:#1e293b;}\n"
        "  .gantt-row.etapa-row .gantt-label{padding-left:14px;color:#334155;}\n"
        "  .gantt-row.se-row .gantt-label{padding-left:28px;color:#64748b;font-size:.72rem;}\n"
        "</style>"
    )
    if _OLD_CSS in tpl:
        tpl = tpl.replace(_OLD_CSS, _NEW_CSS, 1)
        changed = True

    # ── B: Botão editar fase no header ────────────────────────────────────
    _OLD_FASE_DEL = (
        '    <button class="btn btn-xs btn-outline-danger no-print" style="padding:.1rem .4rem;font-size:.7rem;"\n'
        "            onclick=\"event.stopPropagation();apagarFase({{ fase.id }},'{{ fase.nome }}')\">\n"
        "      🗑\n"
        "    </button>"
    )
    _NEW_FASE_DEL = (
        '    <button class="btn btn-xs btn-outline-secondary no-print" style="padding:.1rem .4rem;font-size:.7rem;"\n'
        "            onclick=\"event.stopPropagation();editarFase({{ fase.id }},'{{ fase.nome }}')\">\n"
        "      ✏️\n"
        "    </button>\n"
        '    <button class="btn btn-xs btn-outline-danger no-print" style="padding:.1rem .4rem;font-size:.7rem;"\n'
        "            onclick=\"event.stopPropagation();apagarFase({{ fase.id }},'{{ fase.nome }}')\">\n"
        "      🗑\n"
        "    </button>"
    )
    if _OLD_FASE_DEL in tpl:
        tpl = tpl.replace(_OLD_FASE_DEL, _NEW_FASE_DEL, 1)
        changed = True

    # ── C: Botão + Sub na etapa + sub-etapas após cada etapa ─────────────
    _OLD_ETAPA_ACTIONS = (
        '      <button class="btn btn-sm btn-outline-danger" onclick="apagarEtapa({{ e.id }},\'{{ e.descricao }}\')" title="Apagar">\n'
        "        🗑\n"
        "      </button>\n"
        "    </div>\n"
        "  </div>\n"
        "  {% endfor %}"
    )
    _NEW_ETAPA_ACTIONS = (
        '      <button class="btn btn-sm btn-outline-secondary" onclick="abrirNovaSubEtapa({{ e.id }},\'{{ e.descricao }}\')" title="+ Sub-etapa" style="font-size:.75rem;">\n'
        "        + Sub\n"
        "      </button>\n"
        '      <button class="btn btn-sm btn-outline-danger" onclick="apagarEtapa({{ e.id }},\'{{ e.descricao }}\')" title="Apagar">\n'
        "        🗑\n"
        "      </button>\n"
        "    </div>\n"
        "  </div>\n"
        "  {# Sub-etapas #}\n"
        "  {% if e.subetapas %}\n"
        "  <div id=\"se-body-{{ e.id }}\">\n"
        "    {% for se in e.subetapas %}\n"
        "    <div class=\"cr-subetapa\" id=\"se-row-{{ se.id }}\">\n"
        "      <div>\n"
        "        <span style=\"font-weight:500;\">{{ se.descricao }}</span>\n"
        "        {% if se.insumo %}<span class=\"se-badge ms-1\">{{ se.insumo }}</span>{% endif %}\n"
        "        {% if se.data_inicio or se.data_fim %}\n"
        "        <span style=\"font-size:.68rem;color:var(--mc-muted);margin-left:.5rem;\">{{ se.data_inicio }} → {{ se.data_fim }}</span>\n"
        "        {% endif %}\n"
        "      </div>\n"
        "      <div>{% if se.orcado_rs %}{{ se.orcado_rs|brl }}{% else %}<span style=\"color:#cbd5e1;\">—</span>{% endif %}</div>\n"
        "      <div>{% if se.data_inicio %}{{ se.data_inicio }}{% else %}<span style=\"color:#cbd5e1;\">—</span>{% endif %}</div>\n"
        "      <div class=\"d-flex gap-1 no-print\">\n"
        "        <button class=\"btn btn-outline-secondary\" style=\"padding:.25rem .5rem;font-size:.75rem;\"\n"
        "                onclick=\"editarSubEtapa({{ se.id }},'{{ se.descricao }}','{{ se.insumo }}',{{ se.orcado_rs }},'{{ se.data_inicio }}','{{ se.data_fim }}')\">\n"
        "          ✏️\n"
        "        </button>\n"
        "        <button class=\"btn btn-outline-danger\" style=\"padding:.25rem .5rem;font-size:.75rem;\"\n"
        "                onclick=\"apagarSubEtapa({{ se.id }},'{{ se.descricao }}')\">\n"
        "          🗑\n"
        "        </button>\n"
        "      </div>\n"
        "    </div>\n"
        "    {% endfor %}\n"
        "  </div>\n"
        "  {% endif %}\n"
        "  {% endfor %}"
    )
    if _OLD_ETAPA_ACTIONS in tpl:
        tpl = tpl.replace(_OLD_ETAPA_ACTIONS, _NEW_ETAPA_ACTIONS, 1)
        changed = True

    # ── D: Gantt section antes dos modais ─────────────────────────────────
    _OLD_MODAIS = "{# Modais #}\n<div id=\"modalOverlay\""
    _NEW_MODAIS = (
        "{# Gantt #}\n"
        "<div class=\"card p-3 mb-3 no-print\" id=\"ganttCard\" style=\"display:none;\">\n"
        "  <div class=\"d-flex justify-content-between align-items-center mb-3\">\n"
        "    <h6 class=\"mb-0\"><i class=\"bi bi-bar-chart-steps me-2\"></i>Gantt — Cronograma</h6>\n"
        "    <button class=\"btn btn-sm btn-outline-secondary\" onclick=\"document.getElementById('ganttCard').style.display='none'\">✕ Fechar</button>\n"
        "  </div>\n"
        "  <div class=\"gantt-wrap\">\n"
        "    <div class=\"gantt-header\">\n"
        "      <div class=\"gantt-header-space\"></div>\n"
        "      <div class=\"gantt-months\" id=\"ganttMonths\"></div>\n"
        "    </div>\n"
        "    <div class=\"gantt-grid\" id=\"ganttGrid\"></div>\n"
        "  </div>\n"
        "  <div style=\"font-size:.72rem;color:var(--mc-muted);margin-top:.5rem;\">\n"
        "    Apenas itens com datas de início e fim são exibidos.\n"
        "  </div>\n"
        "</div>\n\n"
        "{# Modais #}\n"
        "<div id=\"modalOverlay\""
    )
    if _OLD_MODAIS in tpl:
        tpl = tpl.replace(_OLD_MODAIS, _NEW_MODAIS, 1)
        changed = True

    # ── E: Novos modais (editFase, subEtapa) antes do fechamento do overlay ─
    _OLD_MODAL_END = (
        '  {# Modal: histórico #}\n'
        '  <div class="modal-box" id="modalHistorico" style="display:none;">\n'
        '    <h6>📅 Histórico de Apontamentos</h6>\n'
        '    <div id="historicoContent"></div>\n'
        '    <button class="btn btn-outline-secondary w-100 mt-3" onclick="fecharModal()">Fechar</button>\n'
        '  </div>\n\n'
        '</div>'
    )
    _NEW_MODAL_END = (
        '  {# Modal: histórico #}\n'
        '  <div class="modal-box" id="modalHistorico" style="display:none;">\n'
        '    <h6>📅 Histórico de Apontamentos</h6>\n'
        '    <div id="historicoContent"></div>\n'
        '    <button class="btn btn-outline-secondary w-100 mt-3" onclick="fecharModal()">Fechar</button>\n'
        '  </div>\n\n'
        '  {# Modal: editar fase #}\n'
        '  <div class="modal-box" id="modalEditFase" style="display:none;">\n'
        '    <h6>✏️ Renomear Fase</h6>\n'
        '    <div class="mb-3">\n'
        '      <label class="form-label fw-semibold small">Nome da Fase</label>\n'
        '      <input type="text" class="form-control" id="editFaseNome" placeholder="Nome da fase">\n'
        '    </div>\n'
        '    <div class="d-flex gap-2">\n'
        '      <button class="btn btn-primary flex-1" onclick="salvarEditFase()">Salvar</button>\n'
        '      <button class="btn btn-outline-secondary" onclick="fecharModal()">Cancelar</button>\n'
        '    </div>\n'
        '  </div>\n\n'
        '  {# Modal: nova/editar sub-etapa #}\n'
        '  <div class="modal-box" id="modalSubEtapa" style="display:none;">\n'
        '    <h6 id="seModalTitulo">➕ Nova Sub-etapa</h6>\n'
        '    <div class="muted small mb-3" id="seEtapaNome"></div>\n'
        '    <div class="mb-3">\n'
        '      <label class="form-label fw-semibold small">Descrição</label>\n'
        '      <input type="text" class="form-control" id="seDesc" placeholder="Ex: Formas">\n'
        '    </div>\n'
        '    <div class="mb-3">\n'
        '      <label class="form-label fw-semibold small">Insumo / Categoria (opcional)</label>\n'
        '      <select class="form-select" id="seInsumo">\n'
        '        <option value="">— Selecione —</option>\n'
        '        {% for ins in insumos %}<option value="{{ ins }}">{{ ins }}</option>{% endfor %}\n'
        '      </select>\n'
        '    </div>\n'
        '    <div class="mb-3">\n'
        '      <label class="form-label fw-semibold small">Valor Orçado (R$)</label>\n'
        '      <input type="number" class="form-control" id="seOrcado" step="100" min="0" placeholder="0">\n'
        '    </div>\n'
        '    <div class="row g-2 mb-3">\n'
        '      <div class="col">\n'
        '        <label class="form-label fw-semibold small">Início</label>\n'
        '        <input type="date" class="form-control" id="seIni">\n'
        '      </div>\n'
        '      <div class="col">\n'
        '        <label class="form-label fw-semibold small">Término</label>\n'
        '        <input type="date" class="form-control" id="seFim">\n'
        '      </div>\n'
        '    </div>\n'
        '    <div class="d-flex gap-2">\n'
        '      <button class="btn btn-primary flex-1" id="seSubmitBtn" onclick="salvarSubEtapa()">Criar Sub-etapa</button>\n'
        '      <button class="btn btn-outline-secondary" onclick="fecharModal()">Cancelar</button>\n'
        '    </div>\n'
        '  </div>\n\n'
        '</div>'
    )
    if _OLD_MODAL_END in tpl:
        tpl = tpl.replace(_OLD_MODAL_END, _NEW_MODAL_END, 1)
        changed = True

    # ── F: Botão Gantt no header ──────────────────────────────────────────
    _OLD_HDR_BTNS = (
        '    <a href="/ferramentas/obras/{{ obra.id }}/evm" class="btn btn-outline-primary btn-sm">'
        '<i class="bi bi-graph-up me-1"></i> EVM</a>'
    )
    _NEW_HDR_BTNS = (
        '    <button onclick="abrirGantt()" class="btn btn-outline-secondary btn-sm">'
        '<i class="bi bi-bar-chart-steps me-1"></i> Gantt</button>\n'
        '    <a href="/ferramentas/obras/{{ obra.id }}/evm" class="btn btn-outline-primary btn-sm">'
        '<i class="bi bi-graph-up me-1"></i> EVM</a>'
    )
    if _OLD_HDR_BTNS in tpl:
        tpl = tpl.replace(_OLD_HDR_BTNS, _NEW_HDR_BTNS, 1)
        changed = True

    # ── G: Atualiza fecharModal para incluir novos modais ─────────────────
    _OLD_FECHAR = (
        "  ['modalApt','modalFase','modalEtapa','modalHistorico'].forEach(id => {\n"
        "    document.getElementById(id).style.display = 'none';\n"
        "  });"
    )
    _NEW_FECHAR = (
        "  ['modalApt','modalFase','modalEtapa','modalHistorico','modalEditFase','modalSubEtapa'].forEach(id => {\n"
        "    const _el = document.getElementById(id); if (_el) _el.style.display = 'none';\n"
        "  });"
    )
    if _OLD_FECHAR in tpl:
        tpl = tpl.replace(_OLD_FECHAR, _NEW_FECHAR, 1)
        changed = True

    # ── H: JS — novas funções antes do fechamento do script ───────────────
    _OLD_JS_END = (
        "async function apagarFase(id, nome) {\n"
        "  if (!confirm('Apagar fase \"' + nome + '\" e todas suas etapas?')) return;\n"
        "  const r = await fetch('/ferramentas/obras/fase/' + id + '/apagar', {method:'POST'});\n"
        "  const d = await r.json();\n"
        "  if (d.ok) location.reload();\n"
        "}\n"
        "</script>"
    )
    _NEW_JS_END = (
        "async function apagarFase(id, nome) {\n"
        "  if (!confirm('Apagar fase \"' + nome + '\" e todas suas etapas?')) return;\n"
        "  const r = await fetch('/ferramentas/obras/fase/' + id + '/apagar', {method:'POST'});\n"
        "  const d = await r.json();\n"
        "  if (d.ok) location.reload();\n"
        "}\n\n"
        "// ── Editar fase ──\n"
        "let _editFaseId = null;\n"
        "function editarFase(id, nome) {\n"
        "  _editFaseId = id;\n"
        "  document.getElementById('editFaseNome').value = nome;\n"
        "  abrirModal('modalEditFase');\n"
        "}\n"
        "async function salvarEditFase() {\n"
        "  const nome = document.getElementById('editFaseNome').value.trim();\n"
        "  if (!nome) return;\n"
        "  const body = new URLSearchParams({nome});\n"
        "  const r = await fetch('/ferramentas/obras/fase/' + _editFaseId + '/editar', {\n"
        "    method: 'POST', headers: {'Content-Type': 'application/x-www-form-urlencoded'},\n"
        "    body\n"
        "  });\n"
        "  const d = await r.json();\n"
        "  if (d.ok) { fecharModal(); location.reload(); }\n"
        "  else { alert('Erro ao salvar.'); }\n"
        "}\n\n"
        "// ── Sub-etapas ──\n"
        "let _seEtapaId = null, _seEditId = null;\n"
        "function abrirNovaSubEtapa(etapaId, etapaNome) {\n"
        "  _seEtapaId = etapaId; _seEditId = null;\n"
        "  document.getElementById('seModalTitulo').textContent = '➕ Nova Sub-etapa';\n"
        "  document.getElementById('seSubmitBtn').textContent = 'Criar Sub-etapa';\n"
        "  document.getElementById('seEtapaNome').textContent = 'Etapa: ' + etapaNome;\n"
        "  document.getElementById('seDesc').value = '';\n"
        "  document.getElementById('seInsumo').value = '';\n"
        "  document.getElementById('seOrcado').value = '';\n"
        "  document.getElementById('seIni').value = '';\n"
        "  document.getElementById('seFim').value = '';\n"
        "  abrirModal('modalSubEtapa');\n"
        "}\n"
        "function editarSubEtapa(id, descricao, insumo, orcado, inicio, fim) {\n"
        "  _seEditId = id; _seEtapaId = null;\n"
        "  document.getElementById('seModalTitulo').textContent = '✏️ Editar Sub-etapa';\n"
        "  document.getElementById('seSubmitBtn').textContent = 'Salvar Edição';\n"
        "  document.getElementById('seEtapaNome').textContent = 'Editando sub-etapa';\n"
        "  document.getElementById('seDesc').value = descricao;\n"
        "  document.getElementById('seInsumo').value = insumo;\n"
        "  document.getElementById('seOrcado').value = orcado;\n"
        "  document.getElementById('seIni').value = inicio;\n"
        "  document.getElementById('seFim').value = fim;\n"
        "  abrirModal('modalSubEtapa');\n"
        "}\n"
        "async function salvarSubEtapa() {\n"
        "  const payload = {\n"
        "    descricao: document.getElementById('seDesc').value,\n"
        "    insumo: document.getElementById('seInsumo').value,\n"
        "    orcado_rs: parseFloat(document.getElementById('seOrcado').value || 0),\n"
        "    data_inicio: document.getElementById('seIni').value,\n"
        "    data_fim: document.getElementById('seFim').value,\n"
        "  };\n"
        "  if (_seEditId) {\n"
        "    const r = await fetch('/ferramentas/obras/subetapa/' + _seEditId + '/editar', {\n"
        "      method: 'POST', headers: {'Content-Type': 'application/json'},\n"
        "      body: JSON.stringify(payload),\n"
        "    });\n"
        "    const d = await r.json();\n"
        "    if (d.ok) { fecharModal(); location.reload(); }\n"
        "    return;\n"
        "  }\n"
        "  payload.etapa_id = _seEtapaId;\n"
        "  const r = await fetch('/ferramentas/obras/' + OBRA_ID + '/subetapa/nova', {\n"
        "    method: 'POST', headers: {'Content-Type': 'application/json'},\n"
        "    body: JSON.stringify(payload),\n"
        "  });\n"
        "  const d = await r.json();\n"
        "  if (d.ok) { fecharModal(); location.reload(); }\n"
        "}\n"
        "async function apagarSubEtapa(id, nome) {\n"
        "  if (!confirm('Apagar sub-etapa \"' + nome + '\"?')) return;\n"
        "  const r = await fetch('/ferramentas/obras/subetapa/' + id + '/apagar', {method:'POST'});\n"
        "  const d = await r.json();\n"
        "  if (d.ok) { const el = document.getElementById('se-row-' + id); if(el) el.remove(); }\n"
        "}\n\n"
        "// ── Gantt ──\n"
        "const _GANTT_DATA = {{ calc.fases | tojson }};\n"
        "const _OBRA_INICIO = '{{ obra.data_inicio }}';\n"
        "const _OBRA_FIM = '{{ obra.data_fim }}';\n"
        "function abrirGantt() {\n"
        "  renderGantt();\n"
        "  document.getElementById('ganttCard').style.display = 'block';\n"
        "  document.getElementById('ganttCard').scrollIntoView({behavior:'smooth',block:'start'});\n"
        "}\n"
        "function renderGantt() {\n"
        "  const items = [];\n"
        "  _GANTT_DATA.forEach(fase => {\n"
        "    if (fase.data_inicio || fase.etapas.some(e => e.data_inicio)) {\n"
        "      // Calcula intervalo da fase a partir das etapas\n"
        "      const starts = fase.etapas.filter(e=>e.data_inicio).map(e=>e.data_inicio);\n"
        "      const ends = fase.etapas.filter(e=>e.data_fim).map(e=>e.data_fim);\n"
        "      if (starts.length)\n"
        "        items.push({label: fase.nome, start: starts.reduce((a,b)=>a<b?a:b),\n"
        "          end: ends.length?ends.reduce((a,b)=>a>b?a:b):null, type:'fase', color:'#0f172a'});\n"
        "    }\n"
        "    fase.etapas.forEach(e => {\n"
        "      if (e.data_inicio)\n"
        "        items.push({label: e.descricao, start: e.data_inicio, end: e.data_fim, type:'etapa', color:'#ea580c'});\n"
        "      (e.subetapas||[]).forEach(se => {\n"
        "        if (se.data_inicio)\n"
        "          items.push({label: se.descricao, start: se.data_inicio, end: se.data_fim, type:'se', color:'#3b82f6'});\n"
        "      });\n"
        "    });\n"
        "  });\n"
        "  if (!items.length) {\n"
        "    document.getElementById('ganttGrid').innerHTML = '<p style=\"color:var(--mc-muted);font-size:.82rem;\">Nenhum item com datas cadastradas. Adicione datas de início e fim nas etapas e sub-etapas.</p>';\n"
        "    document.getElementById('ganttMonths').innerHTML = '';\n"
        "    return;\n"
        "  }\n"
        "  // Escala de tempo\n"
        "  let minDate = _OBRA_INICIO || items.map(i=>i.start).reduce((a,b)=>a<b?a:b);\n"
        "  let maxDate = _OBRA_FIM || items.filter(i=>i.end).map(i=>i.end).reduce((a,b)=>a>b?a:b,'');\n"
        "  if (!minDate) minDate = items.map(i=>i.start).reduce((a,b)=>a<b?a:b);\n"
        "  if (!maxDate) maxDate = items.filter(i=>i.end).map(i=>i.end).reduce((a,b)=>a>b?a:b,'2099-01');\n"
        "  const t0 = new Date(minDate + '-01'); const t1 = new Date(maxDate + (maxDate.length===7?'-28':'')); \n"
        "  const totalMs = t1 - t0 || 1;\n"
        "  // Cabeçalho de meses\n"
        "  const months = []; let cur = new Date(t0);\n"
        "  while (cur <= t1) {\n"
        "    months.push(cur.toISOString().slice(0,7));\n"
        "    cur.setMonth(cur.getMonth()+1);\n"
        "  }\n"
        "  document.getElementById('ganttMonths').innerHTML = months.map(m=>\n"
        "    `<div class=\"gantt-month-tick\">${m.slice(5)+'/'+(m.slice(2,4))}</div>`).join('');\n"
        "  // Linhas\n"
        "  const rows = items.map(item => {\n"
        "    const s = new Date(item.start + (item.start.length===7?'-01':''));\n"
        "    const e = item.end ? new Date(item.end + (item.end.length===7?'-28':'')) : new Date(s.getTime()+30*864e5);\n"
        "    const left = Math.max(0, (s - t0) / totalMs * 100);\n"
        "    const width = Math.min(100 - left, (e - s) / totalMs * 100);\n"
        "    const cls = item.type==='fase'?'fase-row':item.type==='etapa'?'etapa-row':'se-row';\n"
        "    return `<div class=\"gantt-row ${cls}\">\n"
        "      <div class=\"gantt-label\" title=\"${item.label}\">${item.label}</div>\n"
        "      <div class=\"gantt-track\">\n"
        "        <div class=\"gantt-bar\" style=\"left:${left.toFixed(1)}%;width:${Math.max(width,1).toFixed(1)}%;background:${item.color};\">\n"
        "          ${item.label.length > 20 ? '' : item.label}\n"
        "        </div>\n"
        "      </div>\n"
        "    </div>`;\n"
        "  }).join('');\n"
        "  document.getElementById('ganttGrid').innerHTML = rows;\n"
        "}\n"
        "</script>"
    )
    if _OLD_JS_END in tpl:
        tpl = tpl.replace(_OLD_JS_END, _NEW_JS_END, 1)
        changed = True

    # Sentinel
    tpl = tpl.replace("{% endblock %}", "{# _seGanttV1 #}\n{% endblock %}", 1)

    if changed:
        TEMPLATES["ferramenta_obras_cronograma.html"] = tpl
        print("[subetapa_gantt] Template cronograma patcheado com sucesso")
    else:
        print("[subetapa_gantt] Aviso: algumas patches nao foram aplicadas (strings nao encontradas)")

    if hasattr(templates_env.loader, "mapping"):
        templates_env.loader.mapping = TEMPLATES


_patch_subetapa_gantt()
print("[subetapa_gantt] Módulo carregado — sub-etapas, edição de nomes e Gantt ativos")

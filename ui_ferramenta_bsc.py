# ui_ferramenta_bsc.py — Balanced Scorecard (BSC)
# Exec'd no namespace do app.py

import json as _json_bsc
from datetime import date as _date_bsc

_BSC_ROLES = ("admin", "equipe", "cliente")

_BSC_PERSPECTIVES = [
    {"key": "financeira",  "name": "Perspectiva Financeira",    "icon": "💰", "color": "#0d6efd"},
    {"key": "clientes",    "name": "Perspectiva de Clientes",   "icon": "👥", "color": "#198754"},
    {"key": "processos",   "name": "Processos Internos",         "icon": "⚙️", "color": "#fd7e14"},
    {"key": "aprendizado", "name": "Aprendizado & Crescimento", "icon": "🎓", "color": "#6f42c1"},
]

_BSC_STATUS_BADGE = {
    "pendente":     "secondary",
    "em_andamento": "primary",
    "concluido":    "success",
    "cancelado":    "danger",
}

_BSC_PRIORITY_BADGE = {
    "baixa":   "light text-dark border",
    "media":   "warning text-dark",
    "alta":    "danger",
    "critica": "dark",
}

# ── Modelos ────────────────────────────────────────────────────────────────────

class BSCPlan(SQLModel, table=True):
    __tablename__ = "bscplan"
    __table_args__ = {"extend_existing": True}
    id:          Optional[int] = Field(default=None, primary_key=True)
    company_id:  int  = Field(index=True)
    client_id:   Optional[int] = Field(default=None, index=True)
    name:        str  = Field(default="Planejamento Estratégico")
    year:        int  = Field(default=2026)
    description: str  = Field(default="")
    is_active:   bool = Field(default=True)
    created_at:  datetime = Field(default_factory=utcnow)
    updated_at:  datetime = Field(default_factory=utcnow)

class BSCObjective(SQLModel, table=True):
    __tablename__ = "bscobjective"
    __table_args__ = {"extend_existing": True}
    id:          Optional[int] = Field(default=None, primary_key=True)
    company_id:  int  = Field(index=True)
    plan_id:     int  = Field(index=True)
    perspective: str  = Field(default="financeira")
    title:       str  = Field(default="")
    description: str  = Field(default="")
    owner:       str  = Field(default="")
    sort_order:  int  = Field(default=0)
    is_active:   bool = Field(default=True)
    created_at:  datetime = Field(default_factory=utcnow)
    updated_at:  datetime = Field(default_factory=utcnow)

class BSCIndicator(SQLModel, table=True):
    __tablename__ = "bscindicator"
    __table_args__ = {"extend_existing": True}
    id:             Optional[int] = Field(default=None, primary_key=True)
    company_id:     int   = Field(index=True)
    objective_id:   int   = Field(index=True)
    name:           str   = Field(default="")
    unit:           str   = Field(default="%")
    frequency:      str   = Field(default="mensal")
    baseline_value: float = Field(default=0.0)
    target_value:   float = Field(default=0.0)
    source_module:  Optional[str] = Field(default=None)   # "orcamento" | None
    source_metric:  Optional[str] = Field(default=None)   # "realizado" | "orcado" | "execucao_pct"
    source_config:  str           = Field(default="{}")   # JSON: {"account_id": 123}
    aggregation:    str           = Field(default="soma") # "soma" | "ultimo"
    is_active:      bool  = Field(default=True)
    created_at:     datetime = Field(default_factory=utcnow)
    updated_at:     datetime = Field(default_factory=utcnow)

class BSCIndicatorValue(SQLModel, table=True):
    __tablename__ = "bscindicatorvalue"
    __table_args__ = {"extend_existing": True}
    id:           Optional[int] = Field(default=None, primary_key=True)
    indicator_id: int   = Field(index=True)
    company_id:   int   = Field(index=True)
    year:         int
    month:        int
    value:        float = Field(default=0.0)
    note:         str   = Field(default="")
    created_at:   datetime = Field(default_factory=utcnow)
    updated_at:   datetime = Field(default_factory=utcnow)

class BSCAction(SQLModel, table=True):
    __tablename__ = "bscaction"
    __table_args__ = {"extend_existing": True}
    id:           Optional[int] = Field(default=None, primary_key=True)
    company_id:   int  = Field(index=True)
    objective_id: int  = Field(index=True)
    task_id:      Optional[int] = Field(default=None)
    title:        str  = Field(default="")
    description:  str  = Field(default="")
    responsible:  str  = Field(default="")
    due_date:     str  = Field(default="")
    status:       str  = Field(default="pendente")
    priority:     str  = Field(default="media")
    progress:     int  = Field(default=0)
    is_active:    bool = Field(default=True)
    created_at:   datetime = Field(default_factory=utcnow)
    updated_at:   datetime = Field(default_factory=utcnow)

# ── Criação das tabelas ────────────────────────────────────────────────────────

def _ensure_bsc_tables():
    for tbl in (BSCPlan.__table__, BSCObjective.__table__, BSCIndicator.__table__,
                BSCIndicatorValue.__table__, BSCAction.__table__):
        try:
            tbl.create(engine, checkfirst=True)
        except Exception:
            pass
    try:
        from sqlalchemy import text as _t
        with engine.begin() as _c:
            _c.execute(_t("ALTER TABLE bscaction ADD COLUMN IF NOT EXISTS task_id INTEGER"))
            _c.execute(_t("ALTER TABLE bscindicator ADD COLUMN IF NOT EXISTS source_module VARCHAR"))
            _c.execute(_t("ALTER TABLE bscindicator ADD COLUMN IF NOT EXISTS source_metric VARCHAR"))
            _c.execute(_t("ALTER TABLE bscindicator ADD COLUMN IF NOT EXISTS source_config VARCHAR DEFAULT '{}'"))
            _c.execute(_t("ALTER TABLE bscplan ADD COLUMN IF NOT EXISTS client_id INTEGER"))
            _c.execute(_t("ALTER TABLE bscindicator ADD COLUMN IF NOT EXISTS aggregation VARCHAR DEFAULT 'soma'"))
    except Exception:
        pass

try:
    _ensure_bsc_tables()
except Exception:
    pass

# ── Helpers ────────────────────────────────────────────────────────────────────

_BSC_MONTHS_PT = ["Jan","Fev","Mar","Abr","Mai","Jun","Jul","Ago","Set","Out","Nov","Dez"]

def _bsc_current_value(indicator_id: int, values_by_ind: dict, aggregation: str = "soma") -> float:
    vals = values_by_ind.get(indicator_id, [])
    if not vals:
        return 0.0
    if aggregation == "soma":
        return sum(v["value"] for v in vals)
    # "ultimo" — valor do mês mais recente
    latest = sorted(vals, key=lambda v: (v["year"], v["month"]), reverse=True)
    return latest[0]["value"]

def _bsc_achievement(indicators_with_vals: list) -> float | None:
    if not indicators_with_vals:
        return None
    pcts = []
    for ind, cur in indicators_with_vals:
        if ind.target_value > 0:
            pcts.append(min(cur / ind.target_value * 100, 150.0))
    if not pcts:
        return None
    return sum(pcts) / len(pcts)

def _bsc_dot_color(achievement) -> str:
    if achievement is None:
        return "#adb5bd"
    if achievement >= 90:
        return "#198754"
    if achievement >= 70:
        return "#ffc107"
    return "#dc3545"

def _bsc_bar_color(pct: float) -> str:
    if pct >= 90: return "#198754"
    if pct >= 70: return "#ffc107"
    return "#dc3545"

def _bsc_resolve_source(session, company_id: int, ind) -> Optional[float]:
    """Resolve KPI value from linked source module. Returns None if unavailable."""
    if not ind.source_module or not ind.source_metric:
        return None
    try:
        cfg = _json_bsc.loads(ind.source_config or "{}")
        if ind.source_module == "orcamento":
            account_id = cfg.get("account_id")
            year       = cfg.get("year")
            month      = cfg.get("month")
            q = select(BudgetEntry).where(
                BudgetEntry.company_id == company_id,
            )
            if account_id:
                q = q.where(BudgetEntry.account_id == int(account_id))
            if year:
                q = q.where(BudgetEntry.year == int(year))
            if month:
                q = q.where(BudgetEntry.month == int(month))
            rows = session.exec(q).all()
            if not rows:
                return None
            if ind.source_metric == "realizado":
                return sum(r.value_realized for r in rows)
            elif ind.source_metric == "orcado":
                return sum(r.value_budgeted for r in rows)
            elif ind.source_metric == "execucao_pct":
                orc = sum(r.value_budgeted for r in rows)
                if orc == 0:
                    return None
                return round(sum(r.value_realized for r in rows) / orc * 100, 2)
    except Exception:
        pass
    return None


def _bsc_load_dashboard(session, company_id: int, plan_id: int):
    objectives = session.exec(
        select(BSCObjective)
        .where(BSCObjective.company_id == company_id,
               BSCObjective.plan_id == plan_id,
               BSCObjective.is_active == True)
        .order_by(BSCObjective.sort_order, BSCObjective.id)
    ).all()

    obj_ids = [o.id for o in objectives]
    indicators = session.exec(
        select(BSCIndicator)
        .where(BSCIndicator.company_id == company_id,
               BSCIndicator.objective_id.in_(obj_ids),
               BSCIndicator.is_active == True)
    ).all() if obj_ids else []

    ind_ids = [i.id for i in indicators]
    iv_rows = session.exec(
        select(BSCIndicatorValue)
        .where(BSCIndicatorValue.company_id == company_id,
               BSCIndicatorValue.indicator_id.in_(ind_ids))
        .order_by(BSCIndicatorValue.year, BSCIndicatorValue.month)
    ).all() if ind_ids else []

    actions = session.exec(
        select(BSCAction)
        .where(BSCAction.company_id == company_id,
               BSCAction.objective_id.in_(obj_ids),
               BSCAction.is_active == True)
        .order_by(BSCAction.created_at)
    ).all() if obj_ids else []

    # Build values dict: indicator_id → list of {year, month, value, note}
    values_by_ind: dict = {}
    for iv in iv_rows:
        values_by_ind.setdefault(iv.indicator_id, []).append(
            {"year": iv.year, "month": iv.month, "value": iv.value, "note": iv.note}
        )

    # Build per-objective data
    inds_by_obj: dict = {}
    for ind in indicators:
        agg = getattr(ind, "aggregation", None) or "soma"
        cur = _bsc_current_value(ind.id, values_by_ind, agg)
        # Override with live source value if linked
        resolved = _bsc_resolve_source(session, company_id, ind)
        if resolved is not None:
            cur = resolved
        inds_by_obj.setdefault(ind.objective_id, []).append((ind, cur))

    acts_by_obj: dict = {}
    for ac in actions:
        acts_by_obj.setdefault(ac.objective_id, []).append(ac)

    objs_by_persp: dict = {p["key"]: [] for p in _BSC_PERSPECTIVES}
    achievement_by_obj: dict = {}
    for obj in objectives:
        objs_by_persp[obj.perspective].append(obj)
        ach = _bsc_achievement(inds_by_obj.get(obj.id, []))
        achievement_by_obj[obj.id] = ach

    return objs_by_persp, inds_by_obj, acts_by_obj, values_by_ind, achievement_by_obj


# ── Rotas — índice de planos ───────────────────────────────────────────────────

@app.get("/ferramentas/bsc", response_class=HTMLResponse)
@require_login
async def bsc_index(request: Request, session: Session = Depends(get_session)):
    ctx = get_tenant_context(request, session)
    if not ctx or ctx.membership.role not in _BSC_ROLES:
        return RedirectResponse("/", status_code=303)
    cc = get_client_or_none(session, ctx.company.id, get_active_client_id(request, session, ctx))
    active_client_id = get_active_client_id(request, session, ctx)

    plans = session.exec(
        select(BSCPlan)
        .where(BSCPlan.company_id == ctx.company.id,
               BSCPlan.client_id == active_client_id,
               BSCPlan.is_active == True)
        .order_by(BSCPlan.year.desc(), BSCPlan.id.desc())
    ).all()

    # Count objectives per plan
    plan_obj_count = {}
    for p in plans:
        cnt = len(session.exec(
            select(BSCObjective)
            .where(BSCObjective.plan_id == p.id, BSCObjective.is_active == True)
        ).all())
        plan_obj_count[p.id] = cnt

    return render("bsc_index.html", request=request, context={
        "current_user": ctx.user, "current_company": ctx.company,
        "role": ctx.membership.role, "current_client": cc,
        "plans": plans, "plan_obj_count": plan_obj_count,
    })


@app.post("/api/bsc/plano/criar")
@require_login
async def bsc_criar_plano(request: Request, session: Session = Depends(get_session)):
    ctx = get_tenant_context(request, session)
    if not ctx or ctx.membership.role not in ("admin", "equipe", "cliente"):
        return JSONResponse({"ok": False}, status_code=403)
    body = await request.json()
    plan = BSCPlan(
        company_id=ctx.company.id,
        client_id=get_active_client_id(request, session, ctx),
        name=(body.get("name") or "Planejamento Estratégico").strip(),
        year=int(body.get("year") or _date_bsc.today().year),
        description=(body.get("description") or "").strip(),
    )
    session.add(plan); session.commit(); session.refresh(plan)
    return JSONResponse({"ok": True, "id": plan.id})


@app.post("/api/bsc/plano/{plan_id}/editar")
@require_login
async def bsc_editar_plano(plan_id: int, request: Request, session: Session = Depends(get_session)):
    ctx = get_tenant_context(request, session)
    if not ctx or ctx.membership.role not in ("admin", "equipe", "cliente"):
        return JSONResponse({"ok": False}, status_code=403)
    plan = session.get(BSCPlan, plan_id)
    if not plan or plan.company_id != ctx.company.id:
        return JSONResponse({"ok": False}, status_code=404)
    body = await request.json()
    if "name"        in body: plan.name        = (body["name"] or "").strip()
    if "year"        in body: plan.year        = int(body["year"] or plan.year)
    if "description" in body: plan.description = (body["description"] or "").strip()
    plan.updated_at = utcnow()
    session.add(plan); session.commit()
    return JSONResponse({"ok": True})


@app.post("/api/bsc/plano/{plan_id}/deletar")
@require_login
async def bsc_deletar_plano(plan_id: int, request: Request, session: Session = Depends(get_session)):
    ctx = get_tenant_context(request, session)
    if not ctx or ctx.membership.role not in ("admin", "equipe", "cliente"):
        return JSONResponse({"ok": False}, status_code=403)
    plan = session.get(BSCPlan, plan_id)
    if not plan or plan.company_id != ctx.company.id:
        return JSONResponse({"ok": False}, status_code=404)
    plan.is_active = False; plan.updated_at = utcnow()
    session.add(plan); session.commit()
    return JSONResponse({"ok": True})


# ── Rotas — dashboard BSC ─────────────────────────────────────────────────────

@app.get("/ferramentas/bsc/{plan_id}", response_class=HTMLResponse)
@require_login
async def bsc_dashboard(plan_id: int, request: Request, session: Session = Depends(get_session)):
    ctx = get_tenant_context(request, session)
    if not ctx or ctx.membership.role not in _BSC_ROLES:
        return RedirectResponse("/", status_code=303)
    plan = session.get(BSCPlan, plan_id)
    if not plan or plan.company_id != ctx.company.id:
        return RedirectResponse("/ferramentas/bsc", status_code=303)
    cc = get_client_or_none(session, ctx.company.id, get_active_client_id(request, session, ctx))

    objs_by_persp, inds_by_obj, acts_by_obj, values_by_ind, ach_by_obj = \
        _bsc_load_dashboard(session, ctx.company.id, plan_id)

    # Budget accounts for source linking selector
    try:
        budget_accounts = session.exec(
            select(BudgetAccount)
            .where(BudgetAccount.company_id == ctx.company.id,
                   BudgetAccount.is_active == True)
            .order_by(BudgetAccount.code)
        ).all()
    except Exception:
        budget_accounts = []

    # Serialize values_by_ind for JS
    values_json = _json_bsc.dumps(values_by_ind)

    return render("bsc_dashboard.html", request=request, context={
        "current_user": ctx.user, "current_company": ctx.company,
        "role": ctx.membership.role, "current_client": cc,
        "plan": plan,
        "perspectives": _BSC_PERSPECTIVES,
        "objs_by_persp": objs_by_persp,
        "inds_by_obj": inds_by_obj,
        "acts_by_obj": acts_by_obj,
        "ach_by_obj": ach_by_obj,
        "values_json": values_json,
        "months_pt": _BSC_MONTHS_PT,
        "cur_year": _date_bsc.today().year,
        "cur_month": _date_bsc.today().month,
        "dot_color": _bsc_dot_color,
        "bar_color": _bsc_bar_color,
        "budget_accounts": budget_accounts,
    })


# ── Rotas — objetivos ─────────────────────────────────────────────────────────

@app.post("/api/bsc/objetivo/criar")
@require_login
async def bsc_criar_objetivo(request: Request, session: Session = Depends(get_session)):
    ctx = get_tenant_context(request, session)
    if not ctx or ctx.membership.role not in ("admin", "equipe", "cliente"):
        return JSONResponse({"ok": False}, status_code=403)
    body = await request.json()
    plan_id = int(body.get("plan_id") or 0)
    plan = session.get(BSCPlan, plan_id)
    if not plan or plan.company_id != ctx.company.id:
        return JSONResponse({"ok": False}, status_code=404)
    count = len(session.exec(
        select(BSCObjective).where(BSCObjective.plan_id == plan_id,
                                   BSCObjective.perspective == body.get("perspective"),
                                   BSCObjective.is_active == True)
    ).all())
    obj = BSCObjective(
        company_id=ctx.company.id, plan_id=plan_id,
        perspective=(body.get("perspective") or "financeira"),
        title=(body.get("title") or "").strip(),
        description=(body.get("description") or "").strip(),
        owner=(body.get("owner") or "").strip(),
        sort_order=count,
    )
    session.add(obj); session.commit(); session.refresh(obj)
    return JSONResponse({"ok": True, "id": obj.id})


@app.post("/api/bsc/objetivo/{obj_id}/editar")
@require_login
async def bsc_editar_objetivo(obj_id: int, request: Request, session: Session = Depends(get_session)):
    ctx = get_tenant_context(request, session)
    if not ctx or ctx.membership.role not in ("admin", "equipe", "cliente"):
        return JSONResponse({"ok": False}, status_code=403)
    obj = session.get(BSCObjective, obj_id)
    if not obj or obj.company_id != ctx.company.id:
        return JSONResponse({"ok": False}, status_code=404)
    body = await request.json()
    for k in ("title", "description", "owner", "perspective"):
        if k in body: setattr(obj, k, (body[k] or "").strip())
    obj.updated_at = utcnow()
    session.add(obj); session.commit()
    return JSONResponse({"ok": True})


@app.post("/api/bsc/objetivo/{obj_id}/deletar")
@require_login
async def bsc_deletar_objetivo(obj_id: int, request: Request, session: Session = Depends(get_session)):
    ctx = get_tenant_context(request, session)
    if not ctx or ctx.membership.role not in ("admin", "equipe", "cliente"):
        return JSONResponse({"ok": False}, status_code=403)
    obj = session.get(BSCObjective, obj_id)
    if not obj or obj.company_id != ctx.company.id:
        return JSONResponse({"ok": False}, status_code=404)
    obj.is_active = False; obj.updated_at = utcnow()
    session.add(obj); session.commit()
    return JSONResponse({"ok": True})


# ── Rotas — indicadores ───────────────────────────────────────────────────────

@app.post("/api/bsc/indicador/criar")
@require_login
async def bsc_criar_indicador(request: Request, session: Session = Depends(get_session)):
    ctx = get_tenant_context(request, session)
    if not ctx or ctx.membership.role not in ("admin", "equipe", "cliente"):
        return JSONResponse({"ok": False}, status_code=403)
    body = await request.json()
    obj = session.get(BSCObjective, int(body.get("objective_id") or 0))
    if not obj or obj.company_id != ctx.company.id:
        return JSONResponse({"ok": False}, status_code=404)
    _src_cfg = body.get("source_config") or "{}"
    if isinstance(_src_cfg, dict):
        _src_cfg = _json_bsc.dumps(_src_cfg)
    ind = BSCIndicator(
        company_id=ctx.company.id, objective_id=obj.id,
        name=(body.get("name") or "").strip(),
        unit=(body.get("unit") or "%").strip(),
        frequency=(body.get("frequency") or "mensal"),
        baseline_value=float(body.get("baseline_value") or 0),
        target_value=float(body.get("target_value") or 0),
        aggregation=body.get("aggregation") or "soma",
        source_module=body.get("source_module") or None,
        source_metric=body.get("source_metric") or None,
        source_config=_src_cfg,
    )
    session.add(ind); session.commit(); session.refresh(ind)
    return JSONResponse({"ok": True, "id": ind.id})


@app.post("/api/bsc/indicador/{ind_id}/editar")
@require_login
async def bsc_editar_indicador(ind_id: int, request: Request, session: Session = Depends(get_session)):
    ctx = get_tenant_context(request, session)
    if not ctx or ctx.membership.role not in ("admin", "equipe", "cliente"):
        return JSONResponse({"ok": False}, status_code=403)
    ind = session.get(BSCIndicator, ind_id)
    if not ind or ind.company_id != ctx.company.id:
        return JSONResponse({"ok": False}, status_code=404)
    body = await request.json()
    if "name"           in body: ind.name           = (body["name"] or "").strip()
    if "unit"           in body: ind.unit           = (body["unit"] or "").strip()
    if "frequency"      in body: ind.frequency      = body["frequency"]
    if "target_value"   in body: ind.target_value   = float(body["target_value"] or 0)
    if "baseline_value" in body: ind.baseline_value = float(body["baseline_value"] or 0)
    if "aggregation"    in body: ind.aggregation    = body["aggregation"] or "soma"
    if "source_module"  in body: ind.source_module  = body["source_module"] or None
    if "source_metric"  in body: ind.source_metric  = body["source_metric"] or None
    if "source_config"  in body:
        _sc = body["source_config"]
        ind.source_config = _json_bsc.dumps(_sc) if isinstance(_sc, dict) else (_sc or "{}")
    ind.updated_at = utcnow()
    session.add(ind); session.commit()
    return JSONResponse({"ok": True})


@app.post("/api/bsc/indicador/{ind_id}/deletar")
@require_login
async def bsc_deletar_indicador(ind_id: int, request: Request, session: Session = Depends(get_session)):
    ctx = get_tenant_context(request, session)
    if not ctx or ctx.membership.role not in ("admin", "equipe", "cliente"):
        return JSONResponse({"ok": False}, status_code=403)
    ind = session.get(BSCIndicator, ind_id)
    if not ind or ind.company_id != ctx.company.id:
        return JSONResponse({"ok": False}, status_code=404)
    ind.is_active = False; ind.updated_at = utcnow()
    session.add(ind); session.commit()
    return JSONResponse({"ok": True})


@app.post("/api/bsc/indicador/{ind_id}/atualizar-valor")
@require_login
async def bsc_atualizar_valor(ind_id: int, request: Request, session: Session = Depends(get_session)):
    ctx = get_tenant_context(request, session)
    if not ctx or ctx.membership.role not in ("admin", "equipe", "cliente"):
        return JSONResponse({"ok": False}, status_code=403)
    ind = session.get(BSCIndicator, ind_id)
    if not ind or ind.company_id != ctx.company.id:
        return JSONResponse({"ok": False}, status_code=404)
    body = await request.json()
    year  = int(body.get("year")  or _date_bsc.today().year)
    month = int(body.get("month") or _date_bsc.today().month)
    value = float(body.get("value") or 0)
    note  = (body.get("note") or "").strip()

    # upsert via existing row
    existing = session.exec(
        select(BSCIndicatorValue).where(
            BSCIndicatorValue.indicator_id == ind_id,
            BSCIndicatorValue.year == year,
            BSCIndicatorValue.month == month,
        )
    ).first()
    if existing:
        existing.value = value; existing.note = note; existing.updated_at = utcnow()
        session.add(existing)
    else:
        session.add(BSCIndicatorValue(
            indicator_id=ind_id, company_id=ctx.company.id,
            year=year, month=month, value=value, note=note,
        ))
    session.commit()
    return JSONResponse({"ok": True})


# ── Rotas — ações ─────────────────────────────────────────────────────────────

@app.post("/api/bsc/acao/criar")
@require_login
async def bsc_criar_acao(request: Request, session: Session = Depends(get_session)):
    ctx = get_tenant_context(request, session)
    if not ctx or ctx.membership.role not in ("admin", "equipe", "cliente"):
        return JSONResponse({"ok": False}, status_code=403)
    body = await request.json()
    obj = session.get(BSCObjective, int(body.get("objective_id") or 0))
    if not obj or obj.company_id != ctx.company.id:
        return JSONResponse({"ok": False}, status_code=404)

    ac = BSCAction(
        company_id=ctx.company.id, objective_id=obj.id,
        title=(body.get("title") or "").strip(),
        description=(body.get("description") or "").strip(),
        responsible=(body.get("responsible") or "").strip(),
        due_date=(body.get("due_date") or "").strip(),
        status=(body.get("status") or "pendente"),
        priority=(body.get("priority") or "media"),
        progress=int(body.get("progress") or 0),
    )
    session.add(ac); session.flush()

    # Auto-create Task linked to active client
    task_id = None
    try:
        cid = get_active_client_id(request, session, ctx)
        if cid:
            task = Task(
                company_id=ctx.company.id,
                client_id=cid,
                created_by_user_id=ctx.user.id,
                title=f"[BSC] {ac.title}",
                description=(f"Objetivo BSC: {obj.title}\n\n{ac.description}").strip(),
                status={"pendente": "nao_iniciada", "em_andamento": "em_andamento",
                        "concluido": "concluida"}.get(ac.status, "nao_iniciada"),
                priority=ac.priority if ac.priority in ("baixa","media","alta") else "media",
                due_date=ac.due_date,
                visible_to_client=False,
            )
            session.add(task); session.flush()
            ac.task_id = task.id
            task_id = task.id
    except Exception:
        pass

    session.commit()
    return JSONResponse({"ok": True, "id": ac.id, "task_id": task_id})


@app.post("/api/bsc/acao/{ac_id}/editar")
@require_login
async def bsc_editar_acao(ac_id: int, request: Request, session: Session = Depends(get_session)):
    ctx = get_tenant_context(request, session)
    if not ctx or ctx.membership.role not in ("admin", "equipe", "cliente"):
        return JSONResponse({"ok": False}, status_code=403)
    ac = session.get(BSCAction, ac_id)
    if not ac or ac.company_id != ctx.company.id:
        return JSONResponse({"ok": False}, status_code=404)
    body = await request.json()
    for k in ("title","description","responsible","due_date","status","priority"):
        if k in body: setattr(ac, k, (body[k] or "").strip())
    if "progress" in body: ac.progress = max(0, min(100, int(body["progress"] or 0)))
    ac.updated_at = utcnow()
    session.add(ac)

    # Sync task status if linked
    if ac.task_id:
        try:
            task = session.get(Task, ac.task_id)
            if task:
                task.status = {"pendente":"nao_iniciada","em_andamento":"em_andamento",
                               "concluido":"concluida","cancelado":"concluida"}.get(ac.status,"nao_iniciada")
                task.updated_at = utcnow()
                session.add(task)
        except Exception:
            pass

    session.commit()
    return JSONResponse({"ok": True})


@app.post("/api/bsc/acao/{ac_id}/deletar")
@require_login
async def bsc_deletar_acao(ac_id: int, request: Request, session: Session = Depends(get_session)):
    ctx = get_tenant_context(request, session)
    if not ctx or ctx.membership.role not in ("admin", "equipe", "cliente"):
        return JSONResponse({"ok": False}, status_code=403)
    ac = session.get(BSCAction, ac_id)
    if not ac or ac.company_id != ctx.company.id:
        return JSONResponse({"ok": False}, status_code=404)
    ac.is_active = False; ac.updated_at = utcnow()
    session.add(ac); session.commit()
    return JSONResponse({"ok": True})


# ── Rota — contexto Augur ─────────────────────────────────────────────────────

@app.get("/api/bsc/{plan_id}/augur-contexto")
@require_login
async def bsc_augur_contexto(plan_id: int, request: Request, session: Session = Depends(get_session)):
    ctx = get_tenant_context(request, session)
    if not ctx:
        return JSONResponse({"ok": False}, status_code=403)
    plan = session.get(BSCPlan, plan_id)
    if not plan or plan.company_id != ctx.company.id:
        return JSONResponse({"ok": False}, status_code=404)

    objs_by_persp, inds_by_obj, acts_by_obj, _, ach_by_obj = \
        _bsc_load_dashboard(session, ctx.company.id, plan_id)

    lines = [f"# Balanced Scorecard — {plan.name} ({plan.year})"]
    for persp in _BSC_PERSPECTIVES:
        objs = objs_by_persp.get(persp["key"], [])
        if not objs:
            continue
        lines.append(f"\n## {persp['name']}")
        for obj in objs:
            ach = ach_by_obj.get(obj.id)
            status_txt = ("✅ Atingido" if ach and ach >= 90 else
                          "🟡 Em progresso" if ach and ach >= 70 else
                          "🔴 Crítico" if ach is not None else "⚪ Sem indicadores")
            lines.append(f"\n### {obj.title} [{status_txt}]")
            if obj.owner: lines.append(f"Responsável: {obj.owner}")
            if obj.description: lines.append(obj.description)
            inds = inds_by_obj.get(obj.id, [])
            if inds:
                lines.append("**Indicadores:**")
                for ind, cur in inds:
                    pct = round(cur / ind.target_value * 100, 1) if ind.target_value else 0
                    lines.append(f"- {ind.name}: atual={cur}{ind.unit} / meta={ind.target_value}{ind.unit} ({pct}%)")
            acts = acts_by_obj.get(obj.id, [])
            if acts:
                lines.append("**Ações:**")
                for ac in acts:
                    lines.append(f"- [{ac.status}] {ac.title} — {ac.responsible or '—'} | prazo: {ac.due_date or '—'} | {ac.progress}%")

    return JSONResponse({"contexto": "\n".join(lines)})


# ── Templates ─────────────────────────────────────────────────────────────────

TEMPLATES["bsc_index.html"] = r"""
{% extends "base.html" %}
{% block content %}
<div class="d-flex justify-content-between align-items-center mb-4 flex-wrap gap-2">
  <div>
    <h4 class="mb-0">Planejamento Estratégico (BSC)</h4>
    <div class="muted small">Balanced Scorecard — 4 perspectivas, objetivos, indicadores e ações</div>
  </div>
  {% if role in ("admin","equipe","cliente") %}
  <button class="btn btn-primary btn-sm" onclick="abrirModalPlano()">+ Novo Plano</button>
  {% endif %}
</div>

{% if plans %}
<div class="row g-3">
  {% for plan in plans %}
  <div class="col-md-6 col-lg-4">
    <div class="card h-100 p-3">
      <div class="d-flex justify-content-between align-items-start">
        <div>
          <h5 class="mb-1">{{ plan.name }}</h5>
          <span class="badge bg-light text-dark border">{{ plan.year }}</span>
        </div>
        <span class="badge bg-primary">{{ plan_obj_count[plan.id] }} obj.</span>
      </div>
      {% if plan.description %}
      <div class="muted small mt-2">{{ plan.description }}</div>
      {% endif %}
      <div class="mt-3 d-flex gap-2">
        <a href="/ferramentas/bsc/{{ plan.id }}" class="btn btn-primary btn-sm flex-grow-1">Abrir BSC</a>
        {% if role in ("admin","equipe","cliente") %}
        <button class="btn btn-outline-secondary btn-sm"
                onclick="editarPlano({{ plan.id }}, '{{ plan.name|replace("'","\\'") }}', {{ plan.year }}, '{{ plan.description|replace("'","\\'") }}')">Editar</button>
        <button class="btn btn-outline-danger btn-sm"
                onclick="deletarPlano({{ plan.id }}, '{{ plan.name|replace("'","\\'") }}')">✕</button>
        {% endif %}
      </div>
    </div>
  </div>
  {% endfor %}
</div>
{% else %}
<div class="text-center py-5">
  <div style="font-size:3rem;">🎯</div>
  <h5 class="mt-3">Nenhum plano criado ainda</h5>
  <div class="muted mb-3">Crie seu primeiro Balanced Scorecard com as 4 perspectivas estratégicas.</div>
  {% if role in ("admin","equipe","cliente") %}
  <button class="btn btn-primary" onclick="abrirModalPlano()">+ Criar Primeiro Plano</button>
  {% endif %}
</div>
{% endif %}

<!-- Modal plano -->
<div class="modal fade" id="modalPlano" tabindex="-1">
  <div class="modal-dialog">
    <div class="modal-content">
      <div class="modal-header">
        <h5 class="modal-title" id="modalPlanoTitulo">Novo Plano BSC</h5>
        <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
      </div>
      <div class="modal-body">
        <input type="hidden" id="pPlanoId" value="">
        <div class="mb-3">
          <label class="form-label fw-semibold">Nome do Plano</label>
          <input id="pNome" class="form-control" placeholder="Ex: Planejamento Estratégico 2026">
        </div>
        <div class="mb-3">
          <label class="form-label fw-semibold">Ano</label>
          <input id="pAno" type="number" class="form-control" value="2026" min="2020" max="2035">
        </div>
        <div class="mb-3">
          <label class="form-label fw-semibold">Descrição (opcional)</label>
          <textarea id="pDesc" class="form-control" rows="2" placeholder="Descrição ou contexto do plano"></textarea>
        </div>
      </div>
      <div class="modal-footer">
        <button class="btn btn-secondary" data-bs-dismiss="modal">Cancelar</button>
        <button class="btn btn-primary" onclick="salvarPlano()">Salvar</button>
      </div>
    </div>
  </div>
</div>

<script>
var _mp = null;
function _getMP() { if (!_mp) _mp = new bootstrap.Modal(document.getElementById('modalPlano')); return _mp; }
function abrirModalPlano() {
  document.getElementById('pPlanoId').value = '';
  document.getElementById('pNome').value = '';
  document.getElementById('pAno').value = new Date().getFullYear();
  document.getElementById('pDesc').value = '';
  document.getElementById('modalPlanoTitulo').textContent = 'Novo Plano BSC';
  _getMP().show();
}
function editarPlano(id, nome, ano, desc) {
  document.getElementById('pPlanoId').value = id;
  document.getElementById('pNome').value = nome;
  document.getElementById('pAno').value = ano;
  document.getElementById('pDesc').value = desc;
  document.getElementById('modalPlanoTitulo').textContent = 'Editar Plano';
  _getMP().show();
}
async function salvarPlano() {
  var id = document.getElementById('pPlanoId').value;
  var body = {
    name: document.getElementById('pNome').value,
    year: document.getElementById('pAno').value,
    description: document.getElementById('pDesc').value,
  };
  var url = id ? '/api/bsc/plano/' + id + '/editar' : '/api/bsc/plano/criar';
  var r = await fetch(url, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)});
  var d = await r.json();
  if (d.ok) {
    if (!id && d.id) { window.location.href = '/ferramentas/bsc/' + d.id; }
    else { _getMP().hide(); location.reload(); }
  } else alert('Erro ao salvar.');
}
async function deletarPlano(id, nome) {
  if (!confirm('Excluir o plano "' + nome + '"? Esta ação não pode ser desfeita.')) return;
  var r = await fetch('/api/bsc/plano/' + id + '/deletar', {method:'POST'});
  var d = await r.json();
  if (d.ok) location.reload(); else alert('Erro ao excluir.');
}
</script>
{% endblock %}
"""

TEMPLATES["bsc_dashboard.html"] = r"""
{% extends "base.html" %}
{% block content %}
<style>
.bsc-card { border-top: 4px solid var(--bsc-color,#0d6efd); }
.bsc-dot  { width:11px; height:11px; border-radius:50%; display:inline-block; flex-shrink:0; }
.bsc-bar  { height:5px; border-radius:3px; background:#e9ecef; margin-top:2px; }
.bsc-fill { height:5px; border-radius:3px; }
.bsc-obj-btn { font-size:.72rem; padding:1px 6px; }
.accordion-button { font-size:.85rem; }
.accordion-button:not(.collapsed) { background:#f8f9fa; color:inherit; box-shadow:none; }
</style>

<!-- Header -->
<div class="d-flex justify-content-between align-items-center mb-4 flex-wrap gap-2">
  <div>
    <a href="/ferramentas/bsc" class="muted small text-decoration-none">← Planos</a>
    <h4 class="mb-0">{{ plan.name }} <span class="badge bg-light text-dark border ms-1">{{ plan.year }}</span></h4>
    {% if plan.description %}<div class="muted small">{{ plan.description }}</div>{% endif %}
  </div>
  {% if role in ("admin","equipe","cliente") %}
  <button class="btn btn-outline-secondary btn-sm"
          onclick="editarPlano({{ plan.id }}, '{{ plan.name|replace("'","\\'") }}', {{ plan.year }}, '{{ plan.description|replace("'","\\'") }}')">
    Editar Plano
  </button>
  {% endif %}
</div>

<!-- 2×2 grid das perspectivas -->
<div class="row g-3">
{% for persp in perspectives %}
{% set objs = objs_by_persp[persp.key] %}
<div class="col-md-6">
  <div class="card bsc-card h-100" style="--bsc-color:{{ persp.color }}">
    <!-- Cabeçalho da perspectiva -->
    <div class="card-header py-2 px-3 d-flex justify-content-between align-items-center"
         style="background:{{ persp.color }}18;">
      <span class="fw-semibold">{{ persp.icon }} {{ persp.name }}</span>
      {% if role in ("admin","equipe","cliente") %}
      <button class="btn btn-sm bsc-obj-btn btn-outline-secondary"
              onclick="novoObjetivo('{{ persp.key }}', {{ plan.id }})">+ Objetivo</button>
      {% endif %}
    </div>

    <div class="card-body p-0">
      {% if objs %}
      <div class="accordion accordion-flush" id="acc_{{ persp.key }}">
        {% for obj in objs %}
        {% set inds = inds_by_obj.get(obj.id, []) %}
        {% set acts = acts_by_obj.get(obj.id, []) %}
        {% set ach  = ach_by_obj.get(obj.id) %}
        {% if ach is none %}
          {% set dot_col = "#adb5bd" %}
          {% set ach_txt = "—" %}
        {% elif ach >= 90 %}
          {% set dot_col = "#198754" %}
          {% set ach_txt = ach|round(0)|int|string + "%" %}
        {% elif ach >= 70 %}
          {% set dot_col = "#ffc107" %}
          {% set ach_txt = ach|round(0)|int|string + "%" %}
        {% else %}
          {% set dot_col = "#dc3545" %}
          {% set ach_txt = ach|round(0)|int|string + "%" %}
        {% endif %}

        <div class="accordion-item border-0 border-bottom">
          <div class="accordion-header">
            <button class="accordion-button collapsed px-3 py-2" type="button"
                    data-bs-toggle="collapse" data-bs-target="#obj_{{ obj.id }}">
              <span class="bsc-dot me-2" style="background:{{ dot_col }};"></span>
              <div class="flex-grow-1 text-start">
                <div class="fw-semibold" style="line-height:1.2;">{{ obj.title }}</div>
                {% if obj.owner %}<div class="muted" style="font-size:.72rem;">{{ obj.owner }}</div>{% endif %}
              </div>
              {% if ach is not none %}
              <span class="badge ms-2 text-white" style="background:{{ dot_col }};font-size:.7rem;white-space:nowrap;">{{ ach_txt }}</span>
              {% endif %}
            </button>
          </div>

          <div id="obj_{{ obj.id }}" class="accordion-collapse collapse">
            <div class="accordion-body px-3 py-2" style="background:#f8f9fa;">

              {% if obj.description %}
              <div class="muted small mb-2">{{ obj.description }}</div>
              {% endif %}

              <!-- Indicadores -->
              <div class="d-flex justify-content-between align-items-center mb-1">
                <div class="fw-semibold" style="font-size:.8rem;">📊 Indicadores</div>
                {% if role in ("admin","equipe","cliente") %}
                <button class="btn btn-sm bsc-obj-btn btn-outline-secondary"
                        onclick="novoIndicador({{ obj.id }})">+ KPI</button>
                {% endif %}
              </div>

              {% if inds %}
              <table class="table table-sm mb-3" style="font-size:.77rem;">
                <thead class="table-light">
                  <tr><th>Indicador</th><th>Un.</th><th>Base</th><th>Meta</th><th>Atual</th><th style="min-width:90px;">%</th><th></th></tr>
                </thead>
                <tbody>
                {% for ind, cur in inds %}
                {% set pct = (cur / ind.target_value * 100) if ind.target_value else 0 %}
                {% set pct_capped = [pct, 100]|min %}
                {% if pct >= 90 %}{% set bc = "#198754" %}
                {% elif pct >= 70 %}{% set bc = "#ffc107" %}
                {% else %}{% set bc = "#dc3545" %}{% endif %}
                <tr>
                  <td>{{ ind.name }}{% if ind.source_module %} <span class="badge bg-info text-dark" style="font-size:.62rem;">🔗 {{ ind.source_module }}</span>{% endif %}</td>
                  <td class="muted">{{ ind.unit }}</td>
                  <td class="muted">{{ ind.baseline_value }}</td>
                  <td>{{ ind.target_value }}</td>
                  <td class="fw-semibold">{{ cur }}</td>
                  <td>
                    <div class="bsc-bar"><div class="bsc-fill" style="background:{{ bc }};width:{{ pct_capped }}%;"></div></div>
                    <div style="font-size:.68rem;color:{{ bc }};">{{ pct|round(1) }}%</div>
                  </td>
                  <td class="text-end" style="white-space:nowrap;">
                    {% if role in ("admin","equipe","cliente") %}
                    <button class="btn btn-sm bsc-obj-btn btn-outline-secondary"
                            data-id="{{ ind.id }}"
                            data-nome="{{ ind.name }}"
                            data-unit="{{ ind.unit }}"
                            data-freq="{{ ind.frequency }}"
                            data-base="{{ ind.baseline_value }}"
                            data-meta="{{ ind.target_value }}"
                            data-src-module="{{ ind.source_module or '' }}"
                            data-src-metric="{{ ind.source_metric or '' }}"
                            data-src-config='{{ ind.source_config or "{}" }}'
                            data-aggregation="{{ ind.aggregation if ind.aggregation else 'soma' }}"
                            onclick="editarIndicador(this)">✏️</button>
                    <button class="btn btn-sm bsc-obj-btn btn-outline-primary"
                            onclick="atualizarValor({{ ind.id }}, '{{ ind.name|replace("'","\\'") }}', {{ ind.target_value }}, '{{ ind.unit }}')">↑</button>
                    <button class="btn btn-sm bsc-obj-btn btn-outline-danger"
                            onclick="deletarIndicador({{ ind.id }}, '{{ ind.name|replace("'","\\'") }}')">✕</button>
                    {% endif %}
                  </td>
                </tr>
                {% endfor %}
                </tbody>
              </table>
              {% else %}
              <div class="muted mb-3" style="font-size:.78rem;">Nenhum KPI. Adicione indicadores para medir este objetivo.</div>
              {% endif %}

              <!-- Ações -->
              <div class="d-flex justify-content-between align-items-center mb-1">
                <div class="fw-semibold" style="font-size:.8rem;">🎯 Plano de Ações</div>
                {% if role in ("admin","equipe","cliente") %}
                <button class="btn btn-sm bsc-obj-btn btn-outline-secondary"
                        onclick="novaAcao({{ obj.id }}, {{ plan.id }})">+ Ação</button>
                {% endif %}
              </div>

              {% if acts %}
              <table class="table table-sm mb-2" style="font-size:.77rem;">
                <thead class="table-light">
                  <tr><th>Ação</th><th>Resp.</th><th>Prazo</th><th>Status</th><th>%</th><th></th></tr>
                </thead>
                <tbody>
                {% for ac in acts %}
                {% set sbg = {"pendente":"secondary","em_andamento":"primary","concluido":"success","cancelado":"danger"}.get(ac.status,"secondary") %}
                {% set pbg = {"baixa":"light text-dark border","media":"warning text-dark","alta":"danger","critica":"dark"}.get(ac.priority,"secondary") %}
                <tr>
                  <td>
                    {{ ac.title }}
                    {% if ac.task_id %}
                    <a href="/tarefas?id={{ ac.task_id }}" class="muted" style="font-size:.65rem;" title="Ver tarefa">🔗</a>
                    {% endif %}
                  </td>
                  <td class="muted">{{ ac.responsible or "—" }}</td>
                  <td class="muted">{{ ac.due_date or "—" }}</td>
                  <td><span class="badge bg-{{ sbg }}" style="font-size:.68rem;">{{ ac.status.replace("_"," ") }}</span></td>
                  <td>
                    <div class="bsc-bar"><div class="bsc-fill" style="background:#0d6efd;width:{{ ac.progress }}%;"></div></div>
                    <div style="font-size:.68rem;color:#0d6efd;">{{ ac.progress }}%</div>
                  </td>
                  <td class="text-end" style="white-space:nowrap;">
                    {% if role in ("admin","equipe","cliente") %}
                    <button class="btn btn-sm bsc-obj-btn btn-outline-secondary"
                            onclick="editarAcao({{ ac.id }}, '{{ ac.title|replace("'","\\'") }}', '{{ ac.description|replace("'","\\'") }}', '{{ ac.responsible }}', '{{ ac.due_date }}', '{{ ac.status }}', '{{ ac.priority }}', {{ ac.progress }})">Ed</button>
                    <button class="btn btn-sm bsc-obj-btn btn-outline-danger"
                            onclick="deletarAcao({{ ac.id }})">✕</button>
                    {% endif %}
                  </td>
                </tr>
                {% endfor %}
                </tbody>
              </table>
              {% else %}
              <div class="muted mb-2" style="font-size:.78rem;">Nenhuma ação definida.</div>
              {% endif %}

              {% if role in ("admin","equipe","cliente") %}
              <div class="text-end mt-1">
                <button class="btn btn-sm bsc-obj-btn btn-outline-secondary"
                        onclick="editarObjetivo({{ obj.id }}, '{{ obj.title|replace("'","\\'") }}', '{{ obj.description|replace("'","\\'") }}', '{{ obj.owner }}', '{{ obj.perspective }}')">Editar objetivo</button>
                <button class="btn btn-sm bsc-obj-btn btn-outline-danger"
                        onclick="deletarObjetivo({{ obj.id }}, '{{ obj.title|replace("'","\\'") }}')">Remover</button>
              </div>
              {% endif %}

            </div><!-- accordion-body -->
          </div><!-- accordion-collapse -->
        </div><!-- accordion-item -->
        {% endfor %}
      </div><!-- accordion -->
      {% else %}
      <div class="text-center muted py-4" style="font-size:.85rem;">
        Nenhum objetivo nesta perspectiva.
      </div>
      {% endif %}
    </div><!-- card-body -->
  </div><!-- card -->
</div><!-- col -->
{% endfor %}
</div><!-- row -->

<!-- ── Modais ── -->

<!-- Modal: Editar Plano -->
<div class="modal fade" id="modalPlano" tabindex="-1">
  <div class="modal-dialog">
    <div class="modal-content">
      <div class="modal-header"><h5 class="modal-title">Editar Plano</h5>
        <button type="button" class="btn-close" data-bs-dismiss="modal"></button></div>
      <div class="modal-body">
        <input type="hidden" id="pPlanoId">
        <div class="mb-3"><label class="form-label fw-semibold">Nome</label>
          <input id="pNome" class="form-control"></div>
        <div class="mb-3"><label class="form-label fw-semibold">Ano</label>
          <input id="pAno" type="number" class="form-control" min="2020" max="2035"></div>
        <div class="mb-3"><label class="form-label fw-semibold">Descrição</label>
          <textarea id="pDesc" class="form-control" rows="2"></textarea></div>
      </div>
      <div class="modal-footer">
        <button class="btn btn-secondary" data-bs-dismiss="modal">Cancelar</button>
        <button class="btn btn-primary" onclick="salvarPlano()">Salvar</button>
      </div>
    </div>
  </div>
</div>

<!-- Modal: Objetivo -->
<div class="modal fade" id="modalObj" tabindex="-1">
  <div class="modal-dialog">
    <div class="modal-content">
      <div class="modal-header"><h5 class="modal-title" id="modalObjTitulo">Novo Objetivo</h5>
        <button type="button" class="btn-close" data-bs-dismiss="modal"></button></div>
      <div class="modal-body">
        <input type="hidden" id="oObjId">
        <input type="hidden" id="oPlanId">
        <div class="mb-3"><label class="form-label fw-semibold">Perspectiva</label>
          <select id="oPerspectiva" class="form-select">
            <option value="financeira">💰 Perspectiva Financeira</option>
            <option value="clientes">👥 Perspectiva de Clientes</option>
            <option value="processos">⚙️ Processos Internos</option>
            <option value="aprendizado">🎓 Aprendizado & Crescimento</option>
          </select></div>
        <div class="mb-3"><label class="form-label fw-semibold">Objetivo Estratégico</label>
          <input id="oTitulo" class="form-control" placeholder="Ex: Aumentar receita recorrente"></div>
        <div class="mb-3"><label class="form-label fw-semibold">Descrição</label>
          <textarea id="oDesc" class="form-control" rows="2" placeholder="Detalhe do objetivo"></textarea></div>
        <div class="mb-3"><label class="form-label fw-semibold">Responsável / Área</label>
          <input id="oOwner" class="form-control" placeholder="Ex: Diretoria Comercial"></div>
      </div>
      <div class="modal-footer">
        <button class="btn btn-secondary" data-bs-dismiss="modal">Cancelar</button>
        <button class="btn btn-primary" onclick="salvarObjetivo()">Salvar</button>
      </div>
    </div>
  </div>
</div>

<!-- Modal: Indicador -->
<div class="modal fade" id="modalInd" tabindex="-1">
  <div class="modal-dialog modal-lg">
    <div class="modal-content">
      <div class="modal-header"><h5 class="modal-title" id="modalIndTitulo">Novo Indicador (KPI)</h5>
        <button type="button" class="btn-close" data-bs-dismiss="modal"></button></div>
      <div class="modal-body">
        <input type="hidden" id="iIndId">
        <input type="hidden" id="iObjId">
        <div class="mb-3"><label class="form-label fw-semibold">Nome do Indicador</label>
          <input id="iNome" class="form-control" placeholder="Ex: Faturamento Bruto, NPS, Prazo Médio..."></div>
        <div class="row g-2 mb-3">
          <div class="col-6"><label class="form-label fw-semibold">Unidade</label>
            <input id="iUnidade" class="form-control" placeholder="%, R$, dias, un..."></div>
          <div class="col-6"><label class="form-label fw-semibold">Frequência</label>
            <select id="iFrequencia" class="form-select">
              <option value="mensal">Mensal</option>
              <option value="trimestral">Trimestral</option>
              <option value="anual">Anual</option>
            </select></div>
        </div>
        <div class="row g-2 mb-3">
          <div class="col-6"><label class="form-label fw-semibold">Valor Base (atual)</label>
            <input id="iBase" type="number" step="any" class="form-control" value="0"></div>
          <div class="col-6"><label class="form-label fw-semibold">Meta</label>
            <input id="iMeta" type="number" step="any" class="form-control" value="100"></div>
        </div>
        <div class="mb-3">
          <label class="form-label fw-semibold">Cálculo do Valor Atual</label>
          <select id="iAggregation" class="form-select">
            <option value="soma">&#8721; Soma de todos os meses (ex: Faturamento, Unidades vendidas)</option>
            <option value="ultimo">&#10148; Último valor registrado (ex: %, NPS, Prazo médio)</option>
          </select>
        </div>
        <!-- Fonte de dados automática -->
        <hr class="my-2">
        <div class="mb-2">
          <label class="form-label fw-semibold">🔗 Fonte de Dados Automática <span class="text-muted fw-normal">(opcional)</span></label>
          <select id="iSourceModule" class="form-select mb-2" onchange="_bscToggleSource()">
            <option value="">— Manual (sem fonte)</option>
            <option value="orcamento">📋 Orçamento</option>
          </select>
        </div>
        <div id="iSourceOrcamento" style="display:none;">
          <div class="row g-2 mb-2">
            <div class="col-6">
              <label class="form-label fw-semibold">Métrica</label>
              <select id="iSourceMetric" class="form-select">
                <option value="realizado">Valor Realizado</option>
                <option value="orcado">Valor Orçado</option>
                <option value="execucao_pct">% Execução (Realizado/Orçado)</option>
              </select>
            </div>
            <div class="col-6">
              <label class="form-label fw-semibold">Conta do Plano</label>
              <select id="iSourceAccountId" class="form-select">
                <option value="">— Todas as contas —</option>
                {% for acc in budget_accounts %}
                <option value="{{ acc.id }}">{{ acc.code }} — {{ acc.name }}</option>
                {% endfor %}
              </select>
            </div>
          </div>
          <div class="alert alert-info py-1 px-2" style="font-size:.8rem;">
            O valor atual do KPI será calculado automaticamente a partir do Orçamento. Você ainda pode definir a meta acima.
          </div>
        </div>
      </div>
      <div class="modal-footer">
        <button class="btn btn-secondary" data-bs-dismiss="modal">Cancelar</button>
        <button class="btn btn-primary" onclick="salvarIndicador()">Salvar</button>
      </div>
    </div>
  </div>
</div>

<!-- Modal: Atualizar Valor -->
<div class="modal fade" id="modalValor" tabindex="-1">
  <div class="modal-dialog">
    <div class="modal-content">
      <div class="modal-header">
        <h5 class="modal-title">Atualizar Valor — <span id="vIndNome"></span></h5>
        <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
      </div>
      <div class="modal-body">
        <input type="hidden" id="vIndId">
        <div class="row g-2 mb-3">
          <div class="col-5"><label class="form-label fw-semibold">Mês</label>
            <select id="vMes" class="form-select">
              {% for m in months_pt %}
              <option value="{{ loop.index }}" {% if loop.index==cur_month %}selected{% endif %}>{{ m }}</option>
              {% endfor %}
            </select></div>
          <div class="col-4"><label class="form-label fw-semibold">Ano</label>
            <input id="vAno" type="number" class="form-control" value="{{ cur_year }}"></div>
          <div class="col-3"><label class="form-label fw-semibold">Unid.</label>
            <input id="vUnid" class="form-control" readonly style="background:#f8f9fa;"></div>
        </div>
        <div class="mb-3">
          <label class="form-label fw-semibold">Valor realizado <span class="muted">(meta: <span id="vMeta"></span>)</span></label>
          <input id="vValor" type="number" step="any" class="form-control form-control-lg" placeholder="0">
        </div>
        <div class="mb-3">
          <label class="form-label fw-semibold">Observação</label>
          <input id="vNota" class="form-control" placeholder="Contexto desta atualização (opcional)">
        </div>
        <!-- Histórico -->
        <div class="fw-semibold small mb-1">Histórico registrado</div>
        <div id="vHistorico" style="max-height:150px;overflow-y:auto;font-size:.78rem;"></div>
      </div>
      <div class="modal-footer">
        <button class="btn btn-secondary" data-bs-dismiss="modal">Cancelar</button>
        <button class="btn btn-primary" onclick="salvarValor()">Salvar</button>
      </div>
    </div>
  </div>
</div>

<!-- Modal: Ação -->
<div class="modal fade" id="modalAcao" tabindex="-1">
  <div class="modal-dialog modal-lg">
    <div class="modal-content">
      <div class="modal-header"><h5 class="modal-title" id="modalAcaoTitulo">Nova Ação</h5>
        <button type="button" class="btn-close" data-bs-dismiss="modal"></button></div>
      <div class="modal-body">
        <input type="hidden" id="aAcaoId">
        <input type="hidden" id="aObjId">
        <div class="mb-3"><label class="form-label fw-semibold">Título da Ação</label>
          <input id="aTitulo" class="form-control" placeholder="Ex: Implementar CRM até Q2"></div>
        <div class="mb-3"><label class="form-label fw-semibold">Descrição</label>
          <textarea id="aDesc" class="form-control" rows="2" placeholder="Detalhe da ação"></textarea></div>
        <div class="row g-2 mb-3">
          <div class="col-md-4"><label class="form-label fw-semibold">Responsável</label>
            <input id="aResp" class="form-control" placeholder="Nome ou área"></div>
          <div class="col-md-4"><label class="form-label fw-semibold">Prazo</label>
            <input id="aPrazo" class="form-control" placeholder="DD/MM/AAAA"></div>
          <div class="col-md-4"><label class="form-label fw-semibold">Prioridade</label>
            <select id="aPrioridade" class="form-select">
              <option value="baixa">Baixa</option>
              <option value="media" selected>Média</option>
              <option value="alta">Alta</option>
              <option value="critica">Crítica</option>
            </select></div>
        </div>
        <div class="row g-2 mb-3">
          <div class="col-md-6"><label class="form-label fw-semibold">Status</label>
            <select id="aStatus" class="form-select">
              <option value="pendente">Pendente</option>
              <option value="em_andamento">Em andamento</option>
              <option value="concluido">Concluído</option>
              <option value="cancelado">Cancelado</option>
            </select></div>
          <div class="col-md-6"><label class="form-label fw-semibold">Progresso (<span id="aProgVal">0</span>%)</label>
            <input id="aProgresso" type="range" class="form-range" min="0" max="100" value="0"
                   oninput="document.getElementById('aProgVal').textContent=this.value"></div>
        </div>
        <div class="alert alert-info" style="font-size:.82rem;" id="aTaskInfo">
          💡 Ao criar esta ação, uma tarefa será gerada automaticamente e vinculada ao cliente ativo.
        </div>
      </div>
      <div class="modal-footer">
        <button class="btn btn-secondary" data-bs-dismiss="modal">Cancelar</button>
        <button class="btn btn-primary" onclick="salvarAcao()">Salvar</button>
      </div>
    </div>
  </div>
</div>

<script>
const ALL_VALUES = {{ values_json|safe }};
const MONTHS_PT  = {{ months_pt|tojson }};

// ── Bootstrap modals (lazy init) ──
var _mPlano, _mObj, _mInd, _mValor, _mAcao;
function _bscModals() {
  if (!_mPlano) _mPlano = new bootstrap.Modal(document.getElementById('modalPlano'));
  if (!_mObj)   _mObj   = new bootstrap.Modal(document.getElementById('modalObj'));
  if (!_mInd)   _mInd   = new bootstrap.Modal(document.getElementById('modalInd'));
  if (!_mValor) _mValor = new bootstrap.Modal(document.getElementById('modalValor'));
  if (!_mAcao)  _mAcao  = new bootstrap.Modal(document.getElementById('modalAcao'));
}

// ── Plano ──
function editarPlano(id, nome, ano, desc) {
  _bscModals();
  document.getElementById('pPlanoId').value = id;
  document.getElementById('pNome').value = nome;
  document.getElementById('pAno').value = ano;
  document.getElementById('pDesc').value = desc;
  _mPlano.show();
}
async function salvarPlano() {
  var id = document.getElementById('pPlanoId').value;
  var r = await fetch('/api/bsc/plano/' + id + '/editar', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({
      name: document.getElementById('pNome').value,
      year: document.getElementById('pAno').value,
      description: document.getElementById('pDesc').value,
    })
  });
  var d = await r.json();
  if (d.ok) { _mPlano.hide(); location.reload(); } else alert('Erro ao salvar.');
}

// ── Objetivos ──
function novoObjetivo(persp, planId) {
  _bscModals();
  document.getElementById('oObjId').value = '';
  document.getElementById('oPlanId').value = planId;
  document.getElementById('oPerspectiva').value = persp;
  document.getElementById('oTitulo').value = '';
  document.getElementById('oDesc').value = '';
  document.getElementById('oOwner').value = '';
  document.getElementById('modalObjTitulo').textContent = 'Novo Objetivo';
  _mObj.show();
}
function editarObjetivo(id, titulo, desc, owner, persp) {
  _bscModals();
  document.getElementById('oObjId').value = id;
  document.getElementById('oTitulo').value = titulo;
  document.getElementById('oDesc').value = desc;
  document.getElementById('oOwner').value = owner;
  document.getElementById('oPerspectiva').value = persp;
  document.getElementById('modalObjTitulo').textContent = 'Editar Objetivo';
  _mObj.show();
}
async function salvarObjetivo() {
  var id = document.getElementById('oObjId').value;
  var body = {
    plan_id: document.getElementById('oPlanId').value,
    perspective: document.getElementById('oPerspectiva').value,
    title: document.getElementById('oTitulo').value,
    description: document.getElementById('oDesc').value,
    owner: document.getElementById('oOwner').value,
  };
  var url = id ? '/api/bsc/objetivo/' + id + '/editar' : '/api/bsc/objetivo/criar';
  var r = await fetch(url, {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(body)});
  var d = await r.json();
  if (d.ok) { _mObj.hide(); location.reload(); } else alert('Erro ao salvar.');
}
async function deletarObjetivo(id, titulo) {
  if (!confirm('Remover objetivo "' + titulo + '"?')) return;
  var r = await fetch('/api/bsc/objetivo/' + id + '/deletar', {method:'POST'});
  var d = await r.json();
  if (d.ok) location.reload(); else alert('Erro.');
}

// ── Indicadores ──
function _bscToggleSource() {
  var mod = document.getElementById('iSourceModule').value;
  document.getElementById('iSourceOrcamento').style.display = (mod === 'orcamento') ? '' : 'none';
}
function novoIndicador(objId) {
  _bscModals();
  document.getElementById('iIndId').value = '';
  document.getElementById('iObjId').value = objId;
  document.getElementById('iNome').value = '';
  document.getElementById('iUnidade').value = '%';
  document.getElementById('iFrequencia').value = 'mensal';
  document.getElementById('iBase').value = '0';
  document.getElementById('iMeta').value = '100';
  document.getElementById('iAggregation').value = 'soma';
  document.getElementById('iSourceModule').value = '';
  document.getElementById('iSourceMetric').value = 'realizado';
  document.getElementById('iSourceAccountId').value = '';
  document.getElementById('iSourceOrcamento').style.display = 'none';
  document.getElementById('modalIndTitulo').textContent = 'Novo Indicador (KPI)';
  _mInd.show();
}
function editarIndicador(btn) {
  _bscModals();
  var d = btn.dataset;
  var cfg = {};
  try { cfg = JSON.parse(d.srcConfig || '{}'); } catch(e) {}
  document.getElementById('iIndId').value = d.id;
  document.getElementById('iObjId').value = '';
  document.getElementById('iNome').value = d.nome;
  document.getElementById('iUnidade').value = d.unit;
  document.getElementById('iFrequencia').value = d.freq;
  document.getElementById('iBase').value = d.base;
  document.getElementById('iMeta').value = d.meta;
  document.getElementById('iAggregation').value = d.aggregation || 'soma';
  document.getElementById('iSourceModule').value = d.srcModule || '';
  document.getElementById('iSourceMetric').value = d.srcMetric || 'realizado';
  document.getElementById('iSourceAccountId').value = cfg.account_id || '';
  _bscToggleSource();
  document.getElementById('modalIndTitulo').textContent = 'Editar Indicador';
  _mInd.show();
}
async function salvarIndicador() {
  var id = document.getElementById('iIndId').value;
  var srcModule = document.getElementById('iSourceModule').value;
  var srcCfg = {};
  if (srcModule === 'orcamento') {
    var accId = document.getElementById('iSourceAccountId').value;
    if (accId) srcCfg.account_id = parseInt(accId);
  }
  var body = {
    objective_id: document.getElementById('iObjId').value,
    name: document.getElementById('iNome').value,
    unit: document.getElementById('iUnidade').value,
    frequency: document.getElementById('iFrequencia').value,
    baseline_value: document.getElementById('iBase').value,
    target_value: document.getElementById('iMeta').value,
    aggregation: document.getElementById('iAggregation').value,
    source_module: srcModule || null,
    source_metric: srcModule ? document.getElementById('iSourceMetric').value : null,
    source_config: JSON.stringify(srcCfg),
  };
  var url = id ? '/api/bsc/indicador/' + id + '/editar' : '/api/bsc/indicador/criar';
  var r = await fetch(url, {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(body)});
  var d = await r.json();
  if (d.ok) { _mInd.hide(); location.reload(); } else alert('Erro ao salvar.');
}
async function deletarIndicador(id, nome) {
  if (!confirm('Remover indicador "' + nome + '"?')) return;
  await fetch('/api/bsc/indicador/' + id + '/deletar', {method:'POST'});
  location.reload();
}

// ── Valor do indicador ──
function atualizarValor(indId, nome, meta, unid) {
  _bscModals();
  document.getElementById('vIndId').value = indId;
  document.getElementById('vIndNome').textContent = nome;
  document.getElementById('vMeta').textContent = meta + ' ' + unid;
  document.getElementById('vUnid').value = unid;
  document.getElementById('vValor').value = '';
  document.getElementById('vNota').value = '';

  // Preenche valor do mês atual se existir
  var mes = document.getElementById('vMes').value;
  var ano = document.getElementById('vAno').value;
  var vals = ALL_VALUES[indId] || [];
  var existing = vals.find(function(v){ return v.year == ano && v.month == mes; });
  if (existing) { document.getElementById('vValor').value = existing.value; document.getElementById('vNota').value = existing.note || ''; }

  // Atualiza ao mudar mês/ano
  ['vMes','vAno'].forEach(function(fid){
    document.getElementById(fid).onchange = function(){
      var m = document.getElementById('vMes').value;
      var a = document.getElementById('vAno').value;
      var ex = vals.find(function(v){ return v.year == a && v.month == m; });
      document.getElementById('vValor').value = ex ? ex.value : '';
      document.getElementById('vNota').value = ex ? (ex.note || '') : '';
    };
  });

  // Histórico
  var hist = document.getElementById('vHistorico');
  if (vals.length) {
    var sorted = vals.slice().sort(function(a,b){ return b.year-a.year || b.month-a.month; });
    hist.innerHTML = '<table class="table table-sm"><thead class="table-light"><tr><th>Período</th><th>Valor</th><th>Obs.</th></tr></thead><tbody>' +
      sorted.map(function(v){
        return '<tr><td>' + MONTHS_PT[v.month-1] + '/' + v.year + '</td><td class="fw-semibold">' + v.value + ' ' + unid + '</td><td class="muted">' + (v.note||'') + '</td></tr>';
      }).join('') + '</tbody></table>';
  } else {
    hist.innerHTML = '<div class="muted">Nenhum valor registrado ainda.</div>';
  }

  _mValor.show();
}
async function salvarValor() {
  var r = await fetch('/api/bsc/indicador/' + document.getElementById('vIndId').value + '/atualizar-valor', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({
      year: document.getElementById('vAno').value,
      month: document.getElementById('vMes').value,
      value: document.getElementById('vValor').value,
      note: document.getElementById('vNota').value,
    })
  });
  var d = await r.json();
  if (d.ok) { _mValor.hide(); location.reload(); } else alert('Erro ao salvar.');
}

// ── Ações ──
function novaAcao(objId, planId) {
  _bscModals();
  document.getElementById('aAcaoId').value = '';
  document.getElementById('aObjId').value = objId;
  document.getElementById('aTitulo').value = '';
  document.getElementById('aDesc').value = '';
  document.getElementById('aResp').value = '';
  document.getElementById('aPrazo').value = '';
  document.getElementById('aPrioridade').value = 'media';
  document.getElementById('aStatus').value = 'pendente';
  document.getElementById('aProgresso').value = '0';
  document.getElementById('aProgVal').textContent = '0';
  document.getElementById('modalAcaoTitulo').textContent = 'Nova Ação';
  document.getElementById('aTaskInfo').style.display = '';
  _mAcao.show();
}
function editarAcao(id, titulo, desc, resp, prazo, status, prioridade, progresso) {
  _bscModals();
  document.getElementById('aAcaoId').value = id;
  document.getElementById('aTitulo').value = titulo;
  document.getElementById('aDesc').value = desc;
  document.getElementById('aResp').value = resp;
  document.getElementById('aPrazo').value = prazo;
  document.getElementById('aStatus').value = status;
  document.getElementById('aPrioridade').value = prioridade;
  document.getElementById('aProgresso').value = progresso;
  document.getElementById('aProgVal').textContent = progresso;
  document.getElementById('modalAcaoTitulo').textContent = 'Editar Ação';
  document.getElementById('aTaskInfo').style.display = 'none';
  _mAcao.show();
}
async function salvarAcao() {
  var id = document.getElementById('aAcaoId').value;
  var body = {
    objective_id: document.getElementById('aObjId').value,
    title: document.getElementById('aTitulo').value,
    description: document.getElementById('aDesc').value,
    responsible: document.getElementById('aResp').value,
    due_date: document.getElementById('aPrazo').value,
    status: document.getElementById('aStatus').value,
    priority: document.getElementById('aPrioridade').value,
    progress: document.getElementById('aProgresso').value,
  };
  var url = id ? '/api/bsc/acao/' + id + '/editar' : '/api/bsc/acao/criar';
  var r = await fetch(url, {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(body)});
  var d = await r.json();
  if (d.ok) {
    _mAcao.hide();
    if (!id && d.task_id) console.log('Tarefa criada:', d.task_id);
    location.reload();
  } else alert('Erro ao salvar.');
}
async function deletarAcao(id) {
  if (!confirm('Remover esta ação?')) return;
  await fetch('/api/bsc/acao/' + id + '/deletar', {method:'POST'});
  location.reload();
}
</script>
{% endblock %}
"""

# ── Registra templates ────────────────────────────────────────────────────────
if hasattr(templates_env.loader, "mapping"):
    for _t in ("bsc_index.html", "bsc_dashboard.html"):
        templates_env.loader.mapping[_t] = TEMPLATES[_t]

# ── Augur: injeta contexto BSC ────────────────────────────────────────────────
try:
    _orig_bsc_ctx = _enriquecer_client_data

    def _bsc_ctx_enriquecer(session, company_id: int, client_id: int, client, client_data: dict) -> dict:
        client_data = _orig_bsc_ctx(session, company_id, client_id, client, client_data)
        try:
            plans = session.exec(
                select(BSCPlan).where(BSCPlan.company_id == company_id,
                                      BSCPlan.client_id == client_id,
                                      BSCPlan.is_active == True)
                .order_by(BSCPlan.year.desc()).limit(1)
            ).first()
            if plans:
                objs_by_persp, inds_by_obj, acts_by_obj, _, ach_by_obj = \
                    _bsc_load_dashboard(session, company_id, plans.id)
                lines = [f"\n\n## Planejamento Estratégico BSC — {plans.name} ({plans.year})"]
                for persp in _BSC_PERSPECTIVES:
                    objs = objs_by_persp.get(persp["key"], [])
                    if not objs: continue
                    lines.append(f"\n### {persp['name']}")
                    for obj in objs:
                        ach = ach_by_obj.get(obj.id)
                        st = ("✅" if ach and ach >= 90 else "🟡" if ach and ach >= 70 else "🔴" if ach is not None else "⚪")
                        lines.append(f"**{st} {obj.title}**" + (f" ({obj.owner})" if obj.owner else ""))
                        for ind, cur in inds_by_obj.get(obj.id, []):
                            pct = round(cur / ind.target_value * 100, 1) if ind.target_value else 0
                            lines.append(f"  - KPI {ind.name}: {cur}{ind.unit} / meta {ind.target_value}{ind.unit} ({pct}%)")
                        for ac in acts_by_obj.get(obj.id, []):
                            lines.append(f"  - Ação [{ac.status}]: {ac.title} — {ac.responsible or '—'} | {ac.progress}%")
                existing = client_data.get("bsc_context", "")
                client_data["bsc_context"] = (existing + "\n".join(lines)).strip()
        except Exception:
            pass
        return client_data

    _enriquecer_client_data = _bsc_ctx_enriquecer
    print("[bsc] ✅ Contexto BSC injetado no Augur")
except Exception as _e:
    print(f"[bsc] ⚠️ Augur ctx: {_e}")

# ── Feature registration ──────────────────────────────────────────────────────
FEATURE_KEYS["bsc"] = {
    "title": "BSC — Planejamento Estratégico",
    "desc":  "Balanced Scorecard com 4 perspectivas, objetivos, KPIs e plano de ações.",
    "href":  "/ferramentas/bsc",
}
FEATURE_VISIBLE_ROLES["bsc"] = {"admin", "equipe", "cliente"}
for _role in ("admin", "equipe", "cliente"):
    ROLE_DEFAULT_FEATURES.setdefault(_role, set()).add("bsc")
try:
    _bsc_group = next((g for g in FEATURE_GROUPS if g.get("key") == "ferramentas_conteudo"), None)
    if _bsc_group and "bsc" not in _bsc_group.get("features", []):
        _bsc_group["features"].append("bsc")
except Exception:
    pass

# Registra no catálogo de features (aparece na página /ferramentas)
try:
    if "bsc_mensal" not in _CF_CATALOGO:
        _CF_CATALOGO["bsc_mensal"] = {
            "nome":      "BSC — Planejamento Estratégico",
            "descricao": "Balanced Scorecard com 4 perspectivas, objetivos, KPIs e plano de ações.",
            "nivel":     "empresa",
            "url":       "/ferramentas/bsc",
            "icone":     "🎯",
        }
        print("[bsc] ✅ bsc_mensal adicionado ao _CF_CATALOGO")
except Exception as _e:
    print(f"[bsc] ⚠️ Catálogo: {_e}")

print("[bsc] ✅ Ferramenta /ferramentas/bsc carregada")

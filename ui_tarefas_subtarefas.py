# =============================================================================
# Subtarefas — checklist dentro de cada tarefa, com progresso (X/Y concluídas).
# =============================================================================

from typing import Optional as _Opt_st


class TaskSubitem(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    company_id: int = Field(index=True, foreign_key="company.id")
    task_id: int = Field(index=True, foreign_key="task.id")

    title: str
    done: bool = Field(default=False, index=True)
    order_idx: int = Field(default=0, index=True)

    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


def ensure_task_subitem_table() -> bool:
    try:
        TaskSubitem.__table__.create(engine, checkfirst=True)
        return True
    except Exception:
        return False


def _task_subitems_for_task(session: Session, task_id: int) -> list:
    return session.exec(
        select(TaskSubitem)
        .where(TaskSubitem.task_id == task_id)
        .order_by(TaskSubitem.order_idx.asc(), TaskSubitem.created_at.asc())
    ).all()


def _task_subitems_progress(session: Session, task_id: int) -> tuple:
    items = _task_subitems_for_task(session, task_id)
    total = len(items)
    done = len([i for i in items if i.done])
    return done, total


# ── Rotas de gerenciamento de subtarefas ──

@app.post("/tarefas/{task_id}/subtarefas/nova")
@require_login
async def task_subitem_create(
        request: Request,
        session: Session = Depends(get_session),
        task_id: int = 0,
        title: str = "",
) -> RedirectResponse:
    ctx = get_tenant_context(request, session)
    if not ctx:
        request.session.clear()
        return RedirectResponse("/login", status_code=303)

    task = session.get(Task, int(task_id))
    if not task or not _task_can_view(ctx, task):
        return RedirectResponse("/tarefas", status_code=303)

    if ctx.membership.role not in ["admin", "equipe"]:
        set_flash(request, "Sem permissão para adicionar subtarefas.")
        return RedirectResponse(f"/tarefas/{task.id}", status_code=303)

    title = (title or "").strip()
    if not title:
        set_flash(request, "Informe um título para a subtarefa.")
        return RedirectResponse(f"/tarefas/{task.id}", status_code=303)

    if not ensure_task_subitem_table():
        set_flash(request, "Subtarefas não estão configuradas no banco.")
        return RedirectResponse(f"/tarefas/{task.id}", status_code=303)

    existing = _task_subitems_for_task(session, task.id)
    sub = TaskSubitem(
        company_id=ctx.company.id,
        task_id=task.id,
        title=title,
        order_idx=len(existing),
    )
    session.add(sub)
    session.commit()
    return RedirectResponse(f"/tarefas/{task.id}", status_code=303)


@app.post("/tarefas/{task_id}/subtarefas/{sub_id}/toggle")
@require_login
async def task_subitem_toggle(
        request: Request,
        session: Session = Depends(get_session),
        task_id: int = 0,
        sub_id: int = 0,
) -> RedirectResponse:
    ctx = get_tenant_context(request, session)
    if not ctx:
        request.session.clear()
        return RedirectResponse("/login", status_code=303)

    task = session.get(Task, int(task_id))
    if not task or not _task_can_view(ctx, task):
        return RedirectResponse("/tarefas", status_code=303)

    can_toggle = ctx.membership.role in ["admin", "equipe"] or (
        ctx.membership.role == "cliente" and task.client_action
    )
    if not can_toggle:
        set_flash(request, "Sem permissão para alterar esta subtarefa.")
        return RedirectResponse(f"/tarefas/{task.id}", status_code=303)

    sub = session.get(TaskSubitem, int(sub_id))
    if not sub or sub.task_id != task.id:
        return RedirectResponse(f"/tarefas/{task.id}", status_code=303)

    sub.done = not sub.done
    sub.updated_at = utcnow()
    session.add(sub)
    session.commit()
    return RedirectResponse(f"/tarefas/{task.id}", status_code=303)


@app.post("/tarefas/{task_id}/subtarefas/{sub_id}/excluir")
@require_login
async def task_subitem_delete(
        request: Request,
        session: Session = Depends(get_session),
        task_id: int = 0,
        sub_id: int = 0,
) -> RedirectResponse:
    ctx = get_tenant_context(request, session)
    if not ctx:
        request.session.clear()
        return RedirectResponse("/login", status_code=303)

    task = session.get(Task, int(task_id))
    if not task or not _task_can_view(ctx, task):
        return RedirectResponse("/tarefas", status_code=303)

    if ctx.membership.role not in ["admin", "equipe"]:
        set_flash(request, "Sem permissão para excluir subtarefas.")
        return RedirectResponse(f"/tarefas/{task.id}", status_code=303)

    sub = session.get(TaskSubitem, int(sub_id))
    if sub and sub.task_id == task.id:
        session.delete(sub)
        session.commit()
    return RedirectResponse(f"/tarefas/{task.id}", status_code=303)


@app.post("/tarefas/{task_id}/subtarefas/excluir-lote")
@require_login
async def task_subitem_bulk_delete(
        request: Request,
        session: Session = Depends(get_session),
        task_id: int = 0,
) -> RedirectResponse:
    ctx = get_tenant_context(request, session)
    if not ctx:
        request.session.clear()
        return RedirectResponse("/login", status_code=303)

    task = session.get(Task, int(task_id))
    if not task or not _task_can_view(ctx, task):
        return RedirectResponse("/tarefas", status_code=303)

    if ctx.membership.role not in ["admin", "equipe"]:
        set_flash(request, "Sem permissão para excluir subtarefas.")
        return RedirectResponse(f"/tarefas/{task.id}", status_code=303)

    form = await request.form()
    ids = [int(v) for v in form.getlist("ids") if str(v).strip().isdigit()]
    if ids:
        for sub in session.exec(
            select(TaskSubitem).where(TaskSubitem.task_id == task.id, TaskSubitem.id.in_(ids))
        ).all():
            session.delete(sub)
        session.commit()
    return RedirectResponse(f"/tarefas/{task.id}", status_code=303)


# ── Override de GET /tarefas/{task_id}: adiciona subtarefas + progresso ──

app.router.routes[:] = [
    r for r in app.router.routes
    if not (
        hasattr(r, "path") and r.path == "/tarefas/{task_id}"
        and hasattr(r, "methods") and r.methods and "GET" in r.methods
    )
]


@app.get("/tarefas/{task_id}", response_class=HTMLResponse)
@require_login
async def tasks_detail_v2(request: Request, session: Session = Depends(get_session), task_id: int = 0) -> HTMLResponse:
    ctx = get_tenant_context(request, session)
    if not ctx:
        request.session.clear()
        return RedirectResponse("/login", status_code=303)

    task = session.get(Task, int(task_id))
    if not task or not _task_can_view(ctx, task):
        return render(
            "error.html",
            request=request,
            context={"message": "Tarefa não encontrada ou sem permissão."},
            status_code=404,
        )

    if not ensure_task_work_session_table():
        return render(
            "error.html",
            request=request,
            context={"message": "Apontamento de horas não está configurado no banco."},
            status_code=500,
        )

    active_client_id = get_active_client_id(request, session, ctx)
    current_client = get_client_or_none(session, ctx.company.id, active_client_id)

    comments = session.exec(
        select(TaskComment)
        .where(TaskComment.task_id == task.id)
        .order_by(TaskComment.created_at.asc())
    ).all()
    out_comments = []
    for c in comments:
        u = session.get(User, c.author_user_id)
        out_comments.append(
            {
                "author_name": u.name if u else "—",
                "message": c.message,
                "created_at": c.created_at.strftime("%Y-%m-%d %H:%M"),
            }
        )

    attachments = session.exec(
        select(Attachment)
        .where(Attachment.task_id == task.id)
        .order_by(Attachment.created_at.asc())
    ).all()
    out_attachments = []
    for a in attachments:
        out_attachments.append(
            {
                "id": a.id,
                "original_filename": a.original_filename,
                "created_at": a.created_at.strftime("%Y-%m-%d %H:%M"),
            }
        )

    assignee_name = _task_assignee_label(session, task.assignee_user_id)
    task_minutes_total = _task_work_total_minutes_for_task(session, task_id=task.id)
    client_minutes_total = _task_work_total_minutes_for_client(session, company_id=ctx.company.id,
                                                               client_id=task.client_id)
    active_work_session = _task_work_active_for_task_user(session, task_id=task.id,
                                                          user_id=ctx.user.id) if ctx.membership.role in ["admin",
                                                                                                          "equipe"] else None
    work_sessions = [_task_work_row(session, ws) for ws in _task_work_sessions_for_task(session, task_id=task.id)]

    subitems = []
    sub_done, sub_total = 0, 0
    if ensure_task_subitem_table():
        for s in _task_subitems_for_task(session, task.id):
            subitems.append({"id": s.id, "title": s.title, "done": s.done})
        sub_done, sub_total = _task_subitems_progress(session, task.id)
    sub_pct = int(round((sub_done / sub_total) * 100)) if sub_total else 0
    can_manage_subitems = ctx.membership.role in ["admin", "equipe"]
    can_toggle_subitems = can_manage_subitems or (ctx.membership.role == "cliente" and task.client_action)

    return render(
        "tasks_detail.html",
        request=request,
        context={
            "current_user": ctx.user,
            "current_company": ctx.company,
            "role": ctx.membership.role,
            "current_client": current_client,
            "task": task,
            "assignee_name": assignee_name,
            "comments": out_comments,
            "attachments": out_attachments,
            "task_total_minutes": task_minutes_total,
            "task_total_hours_label": _task_work_hours_label(task_minutes_total),
            "client_total_minutes": client_minutes_total,
            "client_total_hours_label": _task_work_hours_label(client_minutes_total),
            "active_work_session": active_work_session,
            "active_work_started_at": _format_dt_br(active_work_session.started_at) if active_work_session else "",
            "work_sessions": work_sessions,
            "subitems": subitems,
            "sub_done": sub_done,
            "sub_total": sub_total,
            "sub_pct": sub_pct,
            "can_manage_subitems": can_manage_subitems,
            "can_toggle_subitems": can_toggle_subitems,
        },
    )


# ── Patch do template: card de "Subtarefas" com checklist e progresso ──
try:
    _anchor_st = '''  <hr class="my-3"/>
  <h5>Apontamento de tempo</h5>'''
    _replacement_st = '''  <hr class="my-3"/>
  <h5>Subtarefas</h5>
  <div class="card p-3 mb-3">
    {% if sub_total %}
      <div class="d-flex justify-content-between align-items-center mb-1">
        <div class="muted small">{{ sub_done }}/{{ sub_total }} concluídas</div>
        <div class="muted small">{{ sub_pct }}%</div>
      </div>
      <div class="progress mb-3" style="height: 8px;">
        <div class="progress-bar bg-success" role="progressbar" style="width: {{ sub_pct }}%;"></div>
      </div>
    {% else %}
      <div class="muted small mb-2">Nenhuma subtarefa cadastrada.</div>
    {% endif %}

    {% if can_manage_subitems and subitems %}
      <div class="d-flex justify-content-end mb-2">
        <button class="btn btn-sm btn-outline-danger" type="submit" form="form-sub-lote"
                onclick="return confirm('Excluir as subtarefas selecionadas?');">Excluir selecionadas</button>
      </div>
    {% endif %}

    {% for sub in subitems %}
      <div class="d-flex align-items-center gap-2 mb-1">
        {% if can_manage_subitems %}
          <input type="checkbox" class="form-check-input" name="ids" value="{{ sub.id }}" form="form-sub-lote">
        {% endif %}
        {% if can_toggle_subitems %}
          <form method="post" action="/tarefas/{{ task.id }}/subtarefas/{{ sub.id }}/toggle" class="d-flex align-items-center gap-2">
            <button class="btn btn-sm btn-outline-secondary" type="submit" style="width: 2rem;">{% if sub.done %}✓{% else %}{% endif %}</button>
            <span class="{% if sub.done %}text-decoration-line-through text-muted{% endif %}">{{ sub.title }}</span>
          </form>
        {% else %}
          <span style="width: 2rem;">{% if sub.done %}✓{% endif %}</span>
          <span class="{% if sub.done %}text-decoration-line-through text-muted{% endif %}">{{ sub.title }}</span>
        {% endif %}
        {% if can_manage_subitems %}
          <form method="post" action="/tarefas/{{ task.id }}/subtarefas/{{ sub.id }}/excluir" class="ms-auto">
            <button class="btn btn-sm btn-outline-danger" type="submit">remover</button>
          </form>
        {% endif %}
      </div>
    {% endfor %}

    {% if can_manage_subitems %}
      <form method="post" action="/tarefas/{{ task.id }}/subtarefas/nova" class="d-flex gap-2 mt-2">
        <input class="form-control form-control-sm" name="title" placeholder="Nova subtarefa" required />
        <button class="btn btn-sm btn-outline-primary" type="submit">Adicionar</button>
      </form>
      <form id="form-sub-lote" method="post" action="/tarefas/{{ task.id }}/subtarefas/excluir-lote"></form>
    {% endif %}
  </div>

  <hr class="my-3"/>
  <h5>Apontamento de tempo</h5>'''
    if _anchor_st in TEMPLATES["tasks_detail.html"]:
        TEMPLATES["tasks_detail.html"] = TEMPLATES["tasks_detail.html"].replace(_anchor_st, _replacement_st, 1)
        print("[tarefas_subtarefas] ✅ Card de Subtarefas injetado em tasks_detail.html")
    else:
        print("[tarefas_subtarefas] ⚠️ Âncora não encontrada em tasks_detail.html — card não injetado")
except Exception as _e_st_patch:
    print(f"[tarefas_subtarefas] ⚠️ Erro ao patchear tasks_detail.html: {_e_st_patch}")

# ── Patch do template: progresso de subtarefas no card do Kanban (tasks_list.html) ──
try:
    _anchor_st2 = '''                    {% if t.due_label %}
                      <span class="badge {% if t.due_state == 'danger' %}text-bg-danger{% else %}text-bg-warning{% endif %}">{{ t.due_label }}</span>
                    {% endif %}
                  </div>'''
    _replacement_st2 = '''                    {% if t.due_label %}
                      <span class="badge {% if t.due_state == 'danger' %}text-bg-danger{% else %}text-bg-warning{% endif %}">{{ t.due_label }}</span>
                    {% endif %}
                    {% if t.sub_total %}
                      <span class="badge text-bg-light border">subtarefas: {{ t.sub_done }}/{{ t.sub_total }}</span>
                    {% endif %}
                  </div>'''
    if _anchor_st2 in TEMPLATES["tasks_list.html"]:
        TEMPLATES["tasks_list.html"] = TEMPLATES["tasks_list.html"].replace(_anchor_st2, _replacement_st2, 1)
        print("[tarefas_subtarefas] ✅ Progresso de subtarefas injetado em tasks_list.html")
    else:
        print("[tarefas_subtarefas] ⚠️ Âncora não encontrada em tasks_list.html — progresso não injetado")
except Exception as _e_st_patch2:
    print(f"[tarefas_subtarefas] ⚠️ Erro ao patchear tasks_list.html: {_e_st_patch2}")

if hasattr(templates_env.loader, "mapping"):
    templates_env.loader.mapping = TEMPLATES

print("[tarefas_subtarefas] ✅ Módulo de Subtarefas carregado.")

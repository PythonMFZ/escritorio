# =============================================================================
# Tarefas — layout melhorado: ocultar concluídas, escolher ordenação e
# memorizar a última forma de visualização (por sessão do usuário).
# =============================================================================

from typing import Optional as _Opt_tk
from sqlalchemy import case as _case_tk

app.router.routes[:] = [
    r for r in app.router.routes
    if not (
        hasattr(r, "path") and r.path == "/tarefas"
        and hasattr(r, "methods") and r.methods and "GET" in r.methods
    )
]


@app.get("/tarefas", response_class=HTMLResponse)
@require_login
async def tasks_list_v2(
        request: Request,
        session: Session = Depends(get_session),
        client_id: int = 0,
        assignee_user_id: int = 0,
        status: str = "",
        priority: str = "",
        due: str = "",
        mine: int = 0,
        hide_done: _Opt_tk[int] = None,
        sort: _Opt_tk[str] = None,
) -> HTMLResponse:
    ctx = get_tenant_context(request, session)
    if not ctx:
        request.session.clear()
        return RedirectResponse("/login", status_code=303)

    # ── Lembrar a última forma de visualização (por sessão do navegador) ──
    prefs = request.session.get("tarefas_view_prefs") or {}
    if hide_done is None:
        hide_done = int(prefs.get("hide_done", 0))
    if sort is None:
        sort = prefs.get("sort", "atualizacao")
    if sort not in {"atualizacao", "criacao", "prazo", "prioridade", "titulo"}:
        sort = "atualizacao"
    request.session["tarefas_view_prefs"] = {"hide_done": int(hide_done), "sort": sort}

    active_client_id = get_active_client_id(request, session, ctx)
    current_client = get_client_or_none(session, ctx.company.id, active_client_id)

    if not ensure_task_work_session_table():
        set_flash(request, "Apontamento de horas não está configurado no banco.")
        return RedirectResponse("/", status_code=303)

    q = select(Task).where(Task.company_id == ctx.company.id)

    clients: list[Client] = []
    assignees: list[dict[str, Any]] = []
    filter_client_id = 0
    filter_assignee_user_id = 0
    filter_status = ""
    filter_priority = ""
    filter_due = ""
    filter_mine = 0

    if ctx.membership.role == "cliente":
        q = q.where(
            Task.client_id == (ctx.membership.client_id or -1),
            Task.visible_to_client.is_(True),
        )
    else:
        clients = session.exec(
            select(Client).where(Client.company_id == ctx.company.id).order_by(Client.created_at)
        ).all()

        memberships = session.exec(select(Membership).where(Membership.company_id == ctx.company.id)).all()
        for m in memberships:
            u = session.get(User, m.user_id)
            if not u:
                continue
            if m.role in {"admin", "equipe"}:
                assignees.append({"id": u.id, "name": u.name, "role": m.role})

        if mine == 1:
            filter_mine = 1
            filter_assignee_user_id = ctx.user.id
            q = q.where(Task.assignee_user_id == ctx.user.id)
        else:
            if assignee_user_id == -1:
                filter_assignee_user_id = -1
                q = q.where(Task.assignee_user_id.is_(None))
            elif assignee_user_id and assignee_user_id > 0:
                filter_assignee_user_id = int(assignee_user_id)
                q = q.where(Task.assignee_user_id == int(assignee_user_id))

        if client_id and client_id > 0:
            fc = get_client_or_none(session, ctx.company.id, int(client_id))
            if not fc:
                set_flash(request, "Cliente inválido para filtro.")
                return RedirectResponse("/tarefas", status_code=303)
            filter_client_id = fc.id
            q = q.where(Task.client_id == fc.id)

        status = (status or "").strip().lower()
        if status in TASK_STATUS:
            filter_status = status
            q = q.where(Task.status == status)

        priority = (priority or "").strip().lower()
        if priority in TASK_PRIORITY:
            filter_priority = priority
            q = q.where(Task.priority == priority)

        due = (due or "").strip().lower()
        today = _to_brasilia_dt(utcnow()).date()
        today_s = today.isoformat()
        end_s = (today + timedelta(days=7)).isoformat()

        if due in {"atrasadas", "hoje", "7dias", "sem_prazo"}:
            filter_due = due
            if due == "sem_prazo":
                q = q.where((Task.due_date == "") | (Task.due_date.is_(None)))
            elif due == "hoje":
                q = q.where(Task.due_date == today_s)
            elif due == "7dias":
                q = q.where(Task.due_date >= today_s, Task.due_date <= end_s)
            elif due == "atrasadas":
                q = q.where(Task.due_date != "", Task.due_date < today_s, Task.status != "concluida")

    if hide_done:
        q = q.where(Task.status != "concluida")

    if sort == "criacao":
        q = q.order_by(Task.created_at.desc())
    elif sort == "titulo":
        q = q.order_by(Task.title.asc())
    elif sort == "prazo":
        q = q.order_by(_case_tk((Task.due_date == "", 1), else_=0), Task.due_date.asc())
    elif sort == "prioridade":
        q = q.order_by(
            _case_tk((Task.priority == "alta", 0), (Task.priority == "media", 1), (Task.priority == "baixa", 2), else_=3)
        )
    else:
        q = q.order_by(Task.updated_at.desc())

    tasks = session.exec(q).all()

    current_list_path = str(request.url.path)
    if request.url.query:
        current_list_path = f"{current_list_path}?{request.url.query}"

    active_for_user = None
    if ctx.membership.role in ["admin", "equipe"]:
        active_for_user = _task_work_active_for_user(session, company_id=ctx.company.id, user_id=ctx.user.id)

    view = []
    today = _to_brasilia_dt(utcnow()).date()
    total_filtered_minutes = 0
    active_filtered_count = 0
    for t in tasks:
        due_state = ""
        due_label = ""
        try:
            if t.due_date:
                _d = str(t.due_date).strip()
                if "/" in _d:
                    _parts = _d.split("/")
                    due_dt = date(int(_parts[2]), int(_parts[1]), int(_parts[0]))
                else:
                    due_dt = date.fromisoformat(_d)
                days_left = (due_dt - today).days
                if t.status != "concluida" and days_left < 0:
                    due_state = "danger"
                    due_label = "atrasada"
                elif t.status != "concluida" and days_left <= 3:
                    due_state = "warning"
                    due_label = "prazo próximo"
        except Exception:
            due_state = ""
            due_label = ""

        tracked_minutes = _task_work_total_minutes_for_task(session, task_id=t.id)
        active_session = session.exec(
            select(TaskWorkSession)
            .where(TaskWorkSession.task_id == t.id, TaskWorkSession.ended_at.is_(None))
            .order_by(TaskWorkSession.started_at.desc())
        ).first()
        total_filtered_minutes += tracked_minutes
        if active_session:
            active_filtered_count += 1

        is_active_for_me = bool(active_for_user and active_for_user.task_id == t.id)
        view.append(
            {
                "id": t.id,
                "title": t.title,
                "status": t.status,
                "priority": t.priority,
                "due_date": _format_date_br(t.due_date),
                "visible_to_client": t.visible_to_client,
                "assignee_name": _task_assignee_label(session, t.assignee_user_id),
                "client_name": (session.get(Client, t.client_id).name if session.get(Client, t.client_id) else ""),
                "due_state": due_state,
                "due_label": due_label,
                "tracked_hours_label": _task_work_hours_label(tracked_minutes),
                "has_active_session": bool(active_session),
                "is_active_for_me": is_active_for_me,
                "can_start_work": ctx.membership.role in ["admin",
                                                          "equipe"] and t.status != "concluida" and not is_active_for_me,
            }
        )

    by_status = {"nao_iniciada": [], "em_andamento": [], "concluida": []}
    for t in view:
        by_status.setdefault(t["status"], by_status["nao_iniciada"]).append(t)

    columns = [
        {"key": "nao_iniciada", "label": "Não iniciada", "tasks": by_status.get("nao_iniciada", []),
         "count": len(by_status.get("nao_iniciada", []))},
        {"key": "em_andamento", "label": "Em andamento", "tasks": by_status.get("em_andamento", []),
         "count": len(by_status.get("em_andamento", []))},
    ]
    if not hide_done:
        columns.append(
            {"key": "concluida", "label": "Concluída", "tasks": by_status.get("concluida", []),
             "count": len(by_status.get("concluida", []))}
        )

    return render(
        "tasks_list.html",
        request=request,
        context={
            "current_user": ctx.user,
            "current_company": ctx.company,
            "role": ctx.membership.role,
            "current_client": current_client,
            "clients": clients,
            "assignees": assignees,
            "filter_client_id": filter_client_id,
            "filter_assignee_user_id": filter_assignee_user_id,
            "filter_status": filter_status,
            "filter_priority": filter_priority,
            "filter_due": filter_due,
            "filter_mine": filter_mine,
            "filter_hide_done": int(hide_done),
            "filter_sort": sort,
            "columns": columns,
            "filtered_total_tasks": len(view),
            "filtered_active_count": active_filtered_count,
            "filtered_total_hours_label": _task_work_hours_label(total_filtered_minutes),
            "current_list_path": current_list_path,
        },
    )


# ── Patch do template: controles de "ocultar concluídas" e "ordenar por" ──
try:
    _anchor_tk = '''      <div class="col-12 d-flex gap-2 align-items-center mt-1">
        <div class="form-check">
          <input class="form-check-input" type="checkbox" name="mine" value="1" id="mine" {% if filter_mine==1 %}checked{% endif %}>
          <label class="form-check-label" for="mine">Minhas</label>
        </div>
        <button class="btn btn-outline-primary" type="submit">Aplicar</button>
        <a class="btn btn-outline-secondary" href="/tarefas">Limpar</a>
      </div>
    </form>
  {% endif %}'''
    _replacement_tk = '''      <div class="col-md-2">
        <label class="form-label">Ordenar por</label>
        <select class="form-select" name="sort">
          <option value="atualizacao" {% if filter_sort=="atualizacao" %}selected{% endif %}>Última atualização</option>
          <option value="criacao" {% if filter_sort=="criacao" %}selected{% endif %}>Criação (mais recente)</option>
          <option value="prazo" {% if filter_sort=="prazo" %}selected{% endif %}>Prazo (mais próximo)</option>
          <option value="prioridade" {% if filter_sort=="prioridade" %}selected{% endif %}>Prioridade</option>
          <option value="titulo" {% if filter_sort=="titulo" %}selected{% endif %}>Título (A-Z)</option>
        </select>
      </div>

      <div class="col-12 d-flex gap-2 align-items-center mt-1">
        <div class="form-check">
          <input class="form-check-input" type="checkbox" name="mine" value="1" id="mine" {% if filter_mine==1 %}checked{% endif %}>
          <label class="form-check-label" for="mine">Minhas</label>
        </div>
        <div class="form-check">
          <input class="form-check-input" type="checkbox" name="hide_done" value="1" id="hide_done" {% if filter_hide_done==1 %}checked{% endif %}>
          <label class="form-check-label" for="hide_done">Ocultar concluídas</label>
        </div>
        <button class="btn btn-outline-primary" type="submit">Aplicar</button>
        <a class="btn btn-outline-secondary" href="/tarefas">Limpar</a>
      </div>
    </form>
  {% endif %}'''
    if _anchor_tk in TEMPLATES["tasks_list.html"]:
        TEMPLATES["tasks_list.html"] = TEMPLATES["tasks_list.html"].replace(_anchor_tk, _replacement_tk, 1)
        print("[tarefas_view] ✅ Controles de ocultar/ordenar injetados em tasks_list.html")
    else:
        print("[tarefas_view] ⚠️ Âncora não encontrada em tasks_list.html — controles não injetados")
except Exception as _e_tk_patch:
    print(f"[tarefas_view] ⚠️ Erro ao patchear tasks_list.html: {_e_tk_patch}")

if hasattr(templates_env.loader, "mapping"):
    templates_env.loader.mapping = TEMPLATES

print("[tarefas_view] ✅ Módulo de layout de Tarefas carregado.")

# ui_augur_commands.py — Augur command execution layer
# Exec'd in app.py namespace — has access to all models, engine, helpers.

import json as _json_cmd
import os as _os_cmd

import httpx as _httpx_cmd
from sqlmodel import Session as _SessCmd, select as _sel_cmd

_ANTHROPIC_KEY_CMD = _os_cmd.getenv("ANTHROPIC_API_KEY", "")
_HAIKU_CMD = "claude-haiku-4-5-20251001"


# ── Name matching ──────────────────────────────────────────────────────────────

def _cmd_find_user_by_name(session, company_id: int, name: str):
    """Return User whose name best matches `name` within company_id."""
    target = name.strip().lower()
    if not target:
        return None
    memberships = session.exec(
        _sel_cmd(Membership).where(Membership.company_id == company_id)
    ).all()
    best, best_score = None, 0
    for m in memberships:
        u = session.get(User, m.user_id)
        if not u:
            continue
        uname = u.name.lower()
        if target == uname:
            return u  # exact match
        # partial: target inside name or vice-versa
        score = 2 if target in uname else (1 if any(w in uname for w in target.split()) else 0)
        if score > best_score:
            best, best_score = u, score
    return best if best_score > 0 else None


# ── Claude call ────────────────────────────────────────────────────────────────

def _cmd_extract_task(message: str, members: list[str]) -> dict | None:
    """Ask Claude Haiku if `message` is a task-creation command. Returns dict or None."""
    if not _ANTHROPIC_KEY_CMD:
        return None
    members_str = ", ".join(f'"{m}"' for m in members) if members else "(nenhum)"
    prompt = (
        f"Membros disponíveis na empresa: {members_str}\n\n"
        f'Mensagem do usuário: "{message}"\n\n'
        "Se a mensagem é um pedido para criar uma tarefa ou lembrete, responda com JSON:\n"
        '{"eh_tarefa":true,"titulo":"...","descricao":"...","data_vencimento":"DD/MM/AAAA ou vazio","responsavel_nome":"nome ou vazio"}\n\n'
        'Se NÃO é criação de tarefa, responda apenas: {"eh_tarefa":false}\n\n'
        "Responda SOMENTE com o JSON, sem texto adicional."
    )
    try:
        r = _httpx_cmd.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": _ANTHROPIC_KEY_CMD,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": _HAIKU_CMD,
                "max_tokens": 300,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=12,
        )
        raw = r.json()["content"][0]["text"].strip()
        # Strip markdown fences if present
        if raw.startswith("```"):
            raw = raw.split("```")[1].lstrip("json").strip()
        return _json_cmd.loads(raw)
    except Exception as _e:
        print(f"[augur_cmd] erro ao analisar comando: {_e}")
        return None


# ── Main command handler ───────────────────────────────────────────────────────

def _augur_try_command(
    session,
    *,
    company_id: int,
    user_id: int,
    client_id: int,
    message: str,
) -> str | None:
    """
    Detect and execute a command from `message`.
    Returns a human-readable confirmation if a command was executed, else None.
    """
    if not message.strip():
        return None

    # Collect company member names for context
    memberships = session.exec(
        _sel_cmd(Membership).where(Membership.company_id == company_id)
    ).all()
    members = []
    for m in memberships:
        u = session.get(User, m.user_id)
        if u:
            members.append(u.name)

    parsed = _cmd_extract_task(message, members)
    if not parsed or not parsed.get("eh_tarefa"):
        return None

    # Resolve assignee
    assignee_user = None
    responsavel_nome = (parsed.get("responsavel_nome") or "").strip()
    if responsavel_nome:
        assignee_user = _cmd_find_user_by_name(session, company_id, responsavel_nome)

    # Create task
    task = Task(
        company_id=company_id,
        client_id=client_id,
        created_by_user_id=user_id,
        assignee_user_id=assignee_user.id if assignee_user else None,
        title=(parsed.get("titulo") or "Nova tarefa")[:200],
        description=(parsed.get("descricao") or "")[:1000],
        status="nao_iniciada",
        priority="media",
        due_date=(parsed.get("data_vencimento") or "")[:20],
        visible_to_client=True,
        client_action=False,
    )
    session.add(task)
    session.commit()
    session.refresh(task)
    print(f"[augur_cmd] tarefa {task.id} criada: '{task.title}' (company={company_id}, client={client_id})")

    # Notify assignee
    if assignee_user and assignee_user.id != user_id:
        try:
            create_user_notification(
                session,
                company_id=company_id,
                user_id=assignee_user.id,
                kind="tarefa",
                title="Nova tarefa atribuída pelo Augur",
                message=task.title,
                href=f"/tarefas/{task.id}",
                created_by_user_id=user_id,
                client_id=client_id,
            )
        except Exception as _ne:
            print(f"[augur_cmd] erro ao notificar: {_ne}")

    # Build confirmation
    parts = [f'Tarefa criada: "{task.title}"']
    if task.due_date:
        parts.append(f"para {task.due_date}")
    if assignee_user:
        parts.append(f"atribuída a {assignee_user.name}, que já foi notificado")
    elif responsavel_nome:
        parts.append(f'(não encontrei "{responsavel_nome}" na equipe — tarefa criada sem responsável)')

    return " — ".join(parts) + ". Pode ver em /tarefas."

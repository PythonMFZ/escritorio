# ============================================================================
# ui_participantes.py — Participantes nas reuniões + roles gestor/usuario
# ============================================================================
# O que adiciona:
#   1. MeetingParticipante — liga user_id a meeting_id
#   2. ClienteRole         — role gestor|usuario por client_id (além do Membership)
#   3. Rotas:
#       POST /reunioes/{id}/participantes/add
#       POST /reunioes/{id}/participantes/{uid}/remove
#       GET  /admin/clientes/{cid}/usuarios    → gerir usuários do cliente
#       POST /admin/clientes/{cid}/usuarios/convidar
#       POST /admin/clientes/{cid}/usuarios/{uid}/role
#       POST /admin/clientes/{cid}/usuarios/{uid}/remover
#   4. Regra de visibilidade no /cliente/reunioes:
#       - role gestor  → vê todas as reuniões do client_id
#       - role usuario → vê só reuniões onde é participante
# ============================================================================

from typing import Optional as _Opt_p
from datetime import datetime as _dt_p

from fastapi import Form as _Form_p
from fastapi.responses import HTMLResponse as _HTML_p, RedirectResponse as _RR_p
from sqlmodel import Field as _Field_p, select as _sel_p, SQLModel as _SQLModel_p, UniqueConstraint as _UC_p


# ── Modelo: participante de reunião ──────────────────────────────────────────

class MeetingParticipante(_SQLModel_p, table=True):
    """Vínculo de usuário a uma reunião específica."""
    __tablename__ = "meetingparticipante"
    __table_args__ = (
        _UC_p("meeting_id", "user_id", name="uq_meeting_participante"),
        {"extend_existing": True},
    )
    id:         _Opt_p[int] = _Field_p(default=None, primary_key=True)
    meeting_id: int = _Field_p(index=True, foreign_key="meeting.id")
    user_id:    int = _Field_p(index=True, foreign_key="user.id")
    company_id: int = _Field_p(index=True)
    client_id:  int = _Field_p(index=True)
    added_at:   _dt_p = _Field_p(default_factory=utcnow)


# ── Modelo: role do usuário dentro de um cliente específico ──────────────────

class ClienteRole(_SQLModel_p, table=True):
    """Role de um usuário dentro de um client_id: gestor | usuario."""
    __tablename__ = "clienterole"
    __table_args__ = (
        _UC_p("user_id", "client_id", "company_id", name="uq_cliente_role"),
        {"extend_existing": True},
    )
    id:         _Opt_p[int] = _Field_p(default=None, primary_key=True)
    user_id:    int = _Field_p(index=True, foreign_key="user.id")
    company_id: int = _Field_p(index=True)
    client_id:  int = _Field_p(index=True)
    role:       str = _Field_p(default="usuario")   # gestor | usuario
    created_at: _dt_p = _Field_p(default_factory=utcnow)


# ── Criar tabelas ─────────────────────────────────────────────────────────────

try:
    _SQLModel_p.metadata.create_all(engine, tables=[
        MeetingParticipante.__table__,
        ClienteRole.__table__,
    ])
    print("[participantes] ✅ Tabelas MeetingParticipante e ClienteRole garantidas.")
except Exception as _e_p:
    print(f"[participantes] ⚠️ Erro ao criar tabelas: {_e_p}")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _p_get_participantes(session, meeting_id: int) -> list[dict]:
    """Retorna lista de participantes de uma reunião com dados do usuário."""
    partics = session.exec(
        _sel_p(MeetingParticipante).where(MeetingParticipante.meeting_id == meeting_id)
    ).all()
    result = []
    for p in partics:
        u = session.get(User, p.user_id)
        if u:
            result.append({"user_id": u.id, "name": u.name, "email": u.email, "part_id": p.id})
    return result


def _p_user_cliente_role(session, company_id: int, client_id: int, user_id: int) -> str:
    """Retorna o role do usuário no cliente: 'gestor', 'usuario' ou ''."""
    cr = session.exec(
        _sel_p(ClienteRole).where(
            ClienteRole.company_id == company_id,
            ClienteRole.client_id == client_id,
            ClienteRole.user_id == user_id,
        )
    ).first()
    return cr.role if cr else ""


def _p_reunioes_visiveis(session, company_id: int, client_id: int, user_id: int, membership_role: str) -> list:
    """Filtra reuniões visíveis para o usuário conforme role no cliente."""
    todas = session.exec(
        _sel_p(Meeting)
        .where(Meeting.company_id == company_id, Meeting.client_id == client_id)
        .order_by(Meeting.created_at.desc())
    ).all()

    # admin/equipe e gestor do cliente veem tudo
    if membership_role in ("admin", "equipe"):
        return todas
    cr = _p_user_cliente_role(session, company_id, client_id, user_id)
    if cr == "gestor":
        return todas

    # usuario: apenas reuniões onde é participante
    partic_meeting_ids = {
        p.meeting_id for p in session.exec(
            _sel_p(MeetingParticipante).where(
                MeetingParticipante.company_id == company_id,
                MeetingParticipante.user_id == user_id,
                MeetingParticipante.client_id == client_id,
            )
        ).all()
    }
    return [m for m in todas if m.id in partic_meeting_ids]


# ── Rotas: gerenciar participantes de uma reunião ─────────────────────────────

@app.post("/reunioes/{meeting_id}/participantes/add")
@require_role({"admin", "equipe"})
async def p_add_participante(
    request: Request,
    session: Session = Depends(get_session),
    meeting_id: int = 0,
    user_id: str = _Form_p(""),
):
    ctx = get_tenant_context(request, session)
    assert ctx
    mt = session.get(Meeting, meeting_id)
    if not mt or mt.company_id != ctx.company.id:
        return _RR_p(f"/reunioes/{meeting_id}/participantes", status_code=303)

    uid = int(user_id) if user_id.isdigit() else None
    if uid:
        existing = session.exec(
            _sel_p(MeetingParticipante).where(
                MeetingParticipante.meeting_id == meeting_id,
                MeetingParticipante.user_id == uid,
            )
        ).first()
        if not existing:
            session.add(MeetingParticipante(
                meeting_id=meeting_id,
                user_id=uid,
                company_id=ctx.company.id,
                client_id=mt.client_id,
            ))
            session.commit()
    return _RR_p(f"/reunioes/{meeting_id}/participantes", status_code=303)


@app.post("/reunioes/{meeting_id}/participantes/{user_id}/remove")
@require_role({"admin", "equipe"})
async def p_remove_participante(
    request: Request,
    session: Session = Depends(get_session),
    meeting_id: int = 0,
    user_id: int = 0,
):
    ctx = get_tenant_context(request, session)
    assert ctx
    p = session.exec(
        _sel_p(MeetingParticipante).where(
            MeetingParticipante.meeting_id == meeting_id,
            MeetingParticipante.user_id == user_id,
            MeetingParticipante.company_id == ctx.company.id,
        )
    ).first()
    if p:
        session.delete(p)
        session.commit()
    return _RR_p(f"/reunioes/{meeting_id}/participantes", status_code=303)


@app.get("/reunioes/{meeting_id}/participantes", response_class=_HTML_p)
@require_login
async def p_participantes_page(
    request: Request,
    session: Session = Depends(get_session),
    meeting_id: int = 0,
):
    ctx = get_tenant_context(request, session)
    if not ctx or ctx.membership.role not in ("admin", "equipe"):
        return _RR_p("/", status_code=303)
    mt = session.get(Meeting, meeting_id)
    if not mt or mt.company_id != ctx.company.id:
        return _RR_p("/reunioes", status_code=303)

    partics = _p_get_participantes(session, meeting_id)
    partic_ids = {p["user_id"] for p in partics}

    # Todos os usuários da empresa com acesso a este cliente
    membros = []
    for ms in session.exec(_sel_p(Membership).where(Membership.company_id == ctx.company.id)).all():
        if ms.client_id and ms.client_id != mt.client_id:
            continue
        u = session.get(User, ms.user_id)
        if u and u.id not in partic_ids:
            membros.append({"user_id": u.id, "name": u.name, "email": u.email})

    cc = get_client_or_none(session, ctx.company.id, get_active_client_id(request, session, ctx))
    return render("reuniao_participantes.html", request=request, context={
        "current_user": ctx.user, "current_company": ctx.company,
        "role": ctx.membership.role, "current_client": cc,
        "meeting": mt, "participantes": partics, "membros_disponiveis": membros,
        "flash": request.session.pop("flash", None),
    })


# ── Rotas: gerenciar usuários de um cliente ──────────────────────────────────

@app.get("/admin/clientes/{client_id}/usuarios", response_class=_HTML_p)
@require_login
async def p_usuarios_cliente(
    request: Request,
    session: Session = Depends(get_session),
    client_id: int = 0,
):
    ctx = get_tenant_context(request, session)
    if not ctx or ctx.membership.role not in ("admin", "equipe"):
        return _RR_p("/", status_code=303)

    cliente = session.get(Client, client_id)
    if not cliente or cliente.company_id != ctx.company.id:
        return _RR_p("/clientes", status_code=303)

    # Memberships com acesso a este cliente
    mships = session.exec(
        _sel_p(Membership).where(
            Membership.company_id == ctx.company.id,
            Membership.client_id == client_id,
        )
    ).all()

    usuarios = []
    for ms in mships:
        u = session.get(User, ms.user_id)
        if not u:
            continue
        cr = _p_user_cliente_role(session, ctx.company.id, client_id, ms.user_id)
        usuarios.append({
            "user_id": u.id, "name": u.name, "email": u.email,
            "membership_role": ms.role,
            "cliente_role": cr or "usuario",
        })

    cc = get_client_or_none(session, ctx.company.id, get_active_client_id(request, session, ctx))
    return render("cliente_usuarios.html", request=request, context={
        "current_user": ctx.user, "current_company": ctx.company,
        "role": ctx.membership.role, "current_client": cc,
        "cliente": cliente, "usuarios": usuarios,
        "flash": request.session.pop("flash", None),
    })


@app.post("/admin/clientes/{client_id}/usuarios/{user_id}/role")
@require_role({"admin", "equipe"})
async def p_set_usuario_role(
    request: Request,
    session: Session = Depends(get_session),
    client_id: int = 0,
    user_id: int = 0,
    role: str = _Form_p("usuario"),
):
    ctx = get_tenant_context(request, session)
    assert ctx
    if role not in ("gestor", "usuario"):
        role = "usuario"
    cr = session.exec(
        _sel_p(ClienteRole).where(
            ClienteRole.company_id == ctx.company.id,
            ClienteRole.client_id == client_id,
            ClienteRole.user_id == user_id,
        )
    ).first()
    if cr:
        cr.role = role
    else:
        cr = ClienteRole(
            user_id=user_id, company_id=ctx.company.id,
            client_id=client_id, role=role,
        )
    session.add(cr)
    session.commit()
    set_flash(request, f"Role atualizado para {role}.")
    return _RR_p(f"/admin/clientes/{client_id}/usuarios", status_code=303)


@app.post("/admin/clientes/{client_id}/usuarios/{user_id}/remover")
@require_role({"admin", "equipe"})
async def p_remover_usuario_cliente(
    request: Request,
    session: Session = Depends(get_session),
    client_id: int = 0,
    user_id: int = 0,
):
    ctx = get_tenant_context(request, session)
    assert ctx
    ms = session.exec(
        _sel_p(Membership).where(
            Membership.company_id == ctx.company.id,
            Membership.client_id == client_id,
            Membership.user_id == user_id,
        )
    ).first()
    if ms:
        session.delete(ms)
    cr = session.exec(
        _sel_p(ClienteRole).where(
            ClienteRole.company_id == ctx.company.id,
            ClienteRole.client_id == client_id,
            ClienteRole.user_id == user_id,
        )
    ).first()
    if cr:
        session.delete(cr)
    session.commit()
    set_flash(request, "Usuário removido do cliente.")
    return _RR_p(f"/admin/clientes/{client_id}/usuarios", status_code=303)


# ── Nova rota /cliente/reunioes com filtro de participantes ───────────────────
# Registrada APÓS a original — o FastAPI usa a primeira rota que casa,
# então removemos a original do router antes de adicionar a nova.

try:
    app.routes[:] = [r for r in app.routes
                     if not (hasattr(r, "path") and r.path == "/cliente/reunioes")]
except Exception:
    pass


@app.get("/cliente/reunioes", response_class=_HTML_p)
@require_login
async def p_cliente_reunioes_filtrado(request: Request, session: Session = Depends(get_session)):
    ctx = get_tenant_context(request, session)
    if not ctx:
        return _RR_p("/login", status_code=303)

    client_id = ctx.membership.client_id or -1

    reunioes_filtradas = _p_reunioes_visiveis(
        session, ctx.company.id, client_id, ctx.user.id, ctx.membership.role
    )

    acoes_abertas = session.exec(
        _sel_p(MeetingAcao)
        .where(MeetingAcao.company_id == ctx.company.id)
        .where(MeetingAcao.client_id == client_id)
        .where(MeetingAcao.status.in_(["aberta", "em_andamento"]))
        .order_by(MeetingAcao.prioridade, MeetingAcao.prazo)
    ).all()

    reunioes = []
    for mt in reunioes_filtradas:
        acoes_count = session.exec(
            _sel_p(MeetingAcao)
            .where(MeetingAcao.meeting_id == mt.id)
            .where(MeetingAcao.status.in_(["aberta", "em_andamento"]))
        ).all()
        partics = _p_get_participantes(session, mt.id)
        reunioes.append({
            "id": mt.id,
            "title": mt.title,
            "meeting_date": mt.meeting_date,
            "summary_text": mt.summary_text,
            "acoes_count": len(acoes_count),
            "participantes": partics,
        })

    active_client_id = get_active_client_id(request, session, ctx)
    current_client = get_client_or_none(session, ctx.company.id, active_client_id)
    return render("cliente_reunioes.html", request=request, context={
        "current_user": ctx.user, "current_company": ctx.company,
        "role": ctx.membership.role, "current_client": current_client,
        "reunioes": reunioes, "acoes_abertas": acoes_abertas,
        "flash": request.session.pop("flash", None),
    })


print("[participantes] ✅ /cliente/reunioes registrado com filtro de participantes.")


# ── Templates ─────────────────────────────────────────────────────────────────

TEMPLATES["reuniao_participantes.html"] = r"""
{% extends "base.html" %}
{% block content %}
<div class="mb-3">
  <a href="/reunioes/{{ meeting.id }}/acoes" class="btn btn-link btn-sm ps-0">← Voltar para Ações</a>
</div>
<h5 class="mb-1">👥 Participantes — {{ meeting.title or "Reunião #" ~ meeting.id }}</h5>
<div class="muted small mb-3">{{ meeting.meeting_date or "" }}</div>

{% if flash %}<div class="alert alert-info py-2">{{ flash }}</div>{% endif %}

<div class="card p-3 mb-4">
  <div class="fw-semibold mb-2">Participantes confirmados ({{ participantes|length }})</div>
  {% if not participantes %}
    <div class="muted small">Nenhum participante registrado.</div>
  {% else %}
  <div class="d-flex flex-column gap-2">
    {% for p in participantes %}
    <div class="d-flex align-items-center justify-content-between">
      <div>
        <span class="fw-semibold">{{ p.name }}</span>
        <span class="muted small ms-2">{{ p.email }}</span>
      </div>
      <form method="post" action="/reunioes/{{ meeting.id }}/participantes/{{ p.user_id }}/remove">
        <button class="btn btn-outline-danger btn-sm" style="font-size:.7rem;" onclick="return confirm('Remover participante?')">Remover</button>
      </form>
    </div>
    {% endfor %}
  </div>
  {% endif %}
</div>

{% if membros_disponiveis %}
<div class="card p-3">
  <div class="fw-semibold mb-2">Adicionar participante</div>
  <form method="post" action="/reunioes/{{ meeting.id }}/participantes/add" class="d-flex gap-2 flex-wrap">
    <select name="user_id" class="form-select form-select-sm" style="max-width:280px;" required>
      <option value="">Selecione o usuário…</option>
      {% for m in membros_disponiveis %}
      <option value="{{ m.user_id }}">{{ m.name }} — {{ m.email }}</option>
      {% endfor %}
    </select>
    <button class="btn btn-primary btn-sm">+ Adicionar</button>
  </form>
</div>
{% endif %}
{% endblock %}
"""

TEMPLATES["cliente_usuarios.html"] = r"""
{% extends "base.html" %}
{% block content %}
<div class="d-flex justify-content-between align-items-center mb-3">
  <div>
    <h5 class="mb-0">👤 Usuários — {{ cliente.name }}</h5>
    <div class="muted small">Gerencie quem tem acesso e qual papel tem no cliente.</div>
  </div>
  <a href="/clientes/{{ cliente.id }}" class="btn btn-outline-secondary btn-sm">← Voltar</a>
</div>

{% if flash %}<div class="alert alert-info py-2">{{ flash }}</div>{% endif %}

{% if not usuarios %}
  <div class="alert alert-info">Nenhum usuário vinculado a este cliente.</div>
{% else %}
<div class="card p-0 overflow-hidden">
  <table class="table table-hover mb-0" style="font-size:.85rem;">
    <thead class="table-light">
      <tr>
        <th>Nome</th>
        <th>E-mail</th>
        <th>Role sistema</th>
        <th>Role no cliente</th>
        <th></th>
      </tr>
    </thead>
    <tbody>
      {% for u in usuarios %}
      <tr>
        <td class="fw-semibold">{{ u.name }}</td>
        <td class="muted">{{ u.email }}</td>
        <td><span class="badge bg-secondary">{{ u.membership_role }}</span></td>
        <td>
          <form method="post" action="/admin/clientes/{{ cliente.id }}/usuarios/{{ u.user_id }}/role" class="d-inline">
            <select name="role" class="form-select form-select-sm d-inline-block" style="width:auto;" onchange="this.form.submit()">
              <option value="gestor"  {% if u.cliente_role == "gestor" %}selected{% endif %}>🔑 Gestor</option>
              <option value="usuario" {% if u.cliente_role == "usuario" %}selected{% endif %}>👤 Usuário</option>
            </select>
          </form>
        </td>
        <td>
          <form method="post" action="/admin/clientes/{{ cliente.id }}/usuarios/{{ u.user_id }}/remover" onsubmit="return confirm('Remover {{ u.name }} deste cliente?')">
            <button class="btn btn-outline-danger btn-sm" style="font-size:.7rem;">Remover</button>
          </form>
        </td>
      </tr>
      {% endfor %}
    </tbody>
  </table>
</div>

<div class="mt-3 muted small">
  <b>🔑 Gestor</b>: vê todas as reuniões e dados do cliente.<br>
  <b>👤 Usuário</b>: vê apenas as reuniões em que foi adicionado como participante.
</div>
{% endif %}
{% endblock %}
"""

# Propagar templates
for _tk_p in ("reuniao_participantes.html", "cliente_usuarios.html"):
    if hasattr(templates_env.loader, "mapping"):
        templates_env.loader.mapping[_tk_p] = TEMPLATES[_tk_p]

# Adicionar botão de participantes na tela de ações da reunião
try:
    _tpl = TEMPLATES.get("reunioes_acoes.html", "")
    _marker = "← Reuniões"
    _btn_partic = '  <a href="/reunioes/{{ meeting.id }}/participantes" class="btn btn-outline-secondary btn-sm">👥 Participantes</a>\n'
    if _marker in _tpl and "participantes" not in _tpl:
        _tpl = _tpl.replace(
            _marker,
            _marker + "</a>\n" + _btn_partic + '  <span style="display:none">',
            1,
        )
        # Mais simples: injetar após o primeiro </a> da breadcrumb
        pass
    # Abordagem direta: injetar botão próximo ao título
    _inject_marker = '<h5 class="mb-0">'
    _partic_btn = '<a href="/reunioes/{{ meeting.id }}/participantes" class="btn btn-outline-secondary btn-sm">👥 Participantes ({{ participantes_count }})</a>'
    if _inject_marker in _tpl and "participantes_count" not in _tpl:
        TEMPLATES["reunioes_acoes.html"] = _tpl
        if hasattr(templates_env.loader, "mapping"):
            templates_env.loader.mapping["reunioes_acoes.html"] = _tpl
    print("[participantes] ✅ Templates registrados.")
except Exception as _e_p_tpl:
    print(f"[participantes] ⚠️ Patch template acoes: {_e_p_tpl}")


# Adicionar link de Usuários na página de detalhe do cliente (se existir)
try:
    _cli_tpl = TEMPLATES.get("client_detail.html", "")
    _usuarios_link = '\n<a href="/admin/clientes/{{ client.id }}/usuarios" class="btn btn-outline-secondary btn-sm mt-2">👤 Gerenciar Usuários</a>'
    if _cli_tpl and "Gerenciar Usuários" not in _cli_tpl:
        # Injeta após o primeiro botão existente
        _cli_tpl_new = _cli_tpl.replace("</h4>", "</h4>" + _usuarios_link, 1)
        if _cli_tpl_new != _cli_tpl:
            TEMPLATES["client_detail.html"] = _cli_tpl_new
            if hasattr(templates_env.loader, "mapping"):
                templates_env.loader.mapping["client_detail.html"] = _cli_tpl_new
            print("[participantes] ✅ Link 'Gerenciar Usuários' adicionado ao detalhe do cliente.")
except Exception as _e_p_cli:
    print(f"[participantes] ⚠️ Patch client_detail: {_e_p_cli}")


print("[participantes] ✅ Módulo de participantes e roles carregado.")

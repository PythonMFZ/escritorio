# ============================================================================
# ui_multitenancy.py — Multi-tenancy: gestor gerencia o próprio time
# ============================================================================
# Adiciona:
#   POST /admin/clientes/{cid}/usuarios/adicionar  → admin/equipe adiciona user
#   GET  /meu-time                                  → gestor vê/gerencia seu time
#   POST /meu-time/{uid}/role                       → gestor muda role de usuario
#   POST /meu-time/{uid}/remover                    → gestor remove usuario
#
# Melhora a UI de cliente_usuarios.html para incluir formulário de adição.
# ============================================================================

from fastapi.responses import HTMLResponse as _HTML_mt, RedirectResponse as _RR_mt
from fastapi import Request as _Req_mt, Depends as _Dep_mt, Form as _Form_mt
from sqlmodel import Session as _Sess_mt, select as _sel_mt

# ── Helpers ───────────────────────────────────────────────────────────────────

def _mt_get_cliente_role(session, company_id, client_id, user_id):
    try:
        cr = session.exec(
            _sel_mt(ClienteRole).where(
                ClienteRole.company_id == company_id,
                ClienteRole.client_id == client_id,
                ClienteRole.user_id == user_id,
            )
        ).first()
        return cr.role if cr else "usuario"
    except Exception:
        return "usuario"


def _mt_set_cliente_role(session, company_id, client_id, user_id, role):
    try:
        cr = session.exec(
            _sel_mt(ClienteRole).where(
                ClienteRole.company_id == company_id,
                ClienteRole.client_id == client_id,
                ClienteRole.user_id == user_id,
            )
        ).first()
        if cr:
            cr.role = role
        else:
            cr = ClienteRole(user_id=user_id, company_id=company_id,
                             client_id=client_id, role=role)
        session.add(cr)
        session.commit()
    except Exception as e:
        print(f"[mt] ⚠️ _mt_set_cliente_role: {e}")


def _mt_ensure_membership(session, company_id, client_id, user_id):
    """Garante que existe um Membership do user com o client_id correto."""
    try:
        ms = session.exec(
            _sel_mt(Membership).where(
                Membership.company_id == company_id,
                Membership.user_id == user_id,
                Membership.client_id == client_id,
            )
        ).first()
        if not ms:
            # Verifica se já tem membership sem client_id
            ms_any = session.exec(
                _sel_mt(Membership).where(
                    Membership.company_id == company_id,
                    Membership.user_id == user_id,
                )
            ).first()
            if ms_any:
                # Atualiza o client_id do membership existente
                ms_any.client_id = client_id
                session.add(ms_any)
                session.commit()
            else:
                # Cria novo membership como cliente
                ms_new = Membership(
                    user_id=user_id, company_id=company_id,
                    client_id=client_id, role="cliente",
                )
                session.add(ms_new)
                session.commit()
    except Exception as e:
        print(f"[mt] ⚠️ _mt_ensure_membership: {e}")


def _mt_users_do_cliente(session, company_id, client_id):
    """Retorna lista de dicts com users vinculados ao client_id."""
    try:
        mships = session.exec(
            _sel_mt(Membership).where(
                Membership.company_id == company_id,
                Membership.client_id == client_id,
            )
        ).all()
        result = []
        for ms in mships:
            u = session.get(User, ms.user_id)
            if not u:
                continue
            cr = _mt_get_cliente_role(session, company_id, client_id, ms.user_id)
            result.append({
                "user_id": u.id, "name": u.name, "email": u.email,
                "membership_role": ms.role, "cliente_role": cr,
            })
        return result
    except Exception as e:
        print(f"[mt] ⚠️ _mt_users_do_cliente: {e}")
        return []


def _mt_users_disponiveis(session, company_id, client_id):
    """Retorna users da company que NÃO estão ainda no client_id."""
    try:
        vinculados_ids = {
            ms.user_id for ms in session.exec(
                _sel_mt(Membership).where(
                    Membership.company_id == company_id,
                    Membership.client_id == client_id,
                )
            ).all()
        }
        todos = session.exec(
            _sel_mt(Membership).where(Membership.company_id == company_id)
        ).all()
        vistos = set()
        result = []
        for ms in todos:
            if ms.user_id in vinculados_ids or ms.user_id in vistos:
                continue
            vistos.add(ms.user_id)
            u = session.get(User, ms.user_id)
            if u:
                result.append({"user_id": u.id, "name": u.name, "email": u.email})
        return sorted(result, key=lambda x: x["name"].lower())
    except Exception as e:
        print(f"[mt] ⚠️ _mt_users_disponiveis: {e}")
        return []


def _mt_get_client_for_gestor(session, company_id, user_id):
    """Retorna o client_id do gestor logado (ou None)."""
    try:
        ms = session.exec(
            _sel_mt(Membership).where(
                Membership.company_id == company_id,
                Membership.user_id == user_id,
                Membership.role == "cliente",
            )
        ).first()
        if not ms or not ms.client_id:
            return None
        cr = session.exec(
            _sel_mt(ClienteRole).where(
                ClienteRole.company_id == company_id,
                ClienteRole.client_id == ms.client_id,
                ClienteRole.user_id == user_id,
                ClienteRole.role == "gestor",
            )
        ).first()
        return ms.client_id if cr else None
    except Exception:
        return None


# ── Rota: admin adiciona user existente a um cliente ─────────────────────────

@app.post("/admin/clientes/{client_id}/usuarios/adicionar")
@require_role({"admin", "equipe"})
async def mt_adicionar_usuario(
    request: _Req_mt,
    session: _Sess_mt = _Dep_mt(get_session),
    client_id: int = 0,
    user_id: int = _Form_mt(0),
    role: str = _Form_mt("usuario"),
):
    ctx = get_tenant_context(request, session)
    if not ctx:
        return _RR_mt("/login", status_code=303)

    cliente = session.get(Client, client_id)
    if not cliente or cliente.company_id != ctx.company.id:
        return _RR_mt("/admin/clientes", status_code=303)

    if role not in ("gestor", "usuario"):
        role = "usuario"

    _mt_ensure_membership(session, ctx.company.id, client_id, user_id)
    _mt_set_cliente_role(session, ctx.company.id, client_id, user_id, role)
    set_flash(request, "Usuário adicionado ao cliente.")
    return _RR_mt(f"/admin/clientes/{client_id}/usuarios", status_code=303)


# ── Rota: gestor vê e gerencia seu time ──────────────────────────────────────

@app.get("/meu-time", response_class=_HTML_mt)
@require_login
async def mt_meu_time(request: _Req_mt, session: _Sess_mt = _Dep_mt(get_session)):
    ctx = get_tenant_context(request, session)
    if not ctx:
        return _RR_mt("/login", status_code=303)

    # Só gestores de cliente podem acessar
    client_id = _mt_get_client_for_gestor(session, ctx.company.id, ctx.user.id)
    if not client_id:
        # Admin/equipe são redirecionados para a lista de clientes
        if ctx.membership.role in ("admin", "equipe"):
            return _RR_mt("/admin/clientes", status_code=303)
        return _RR_mt("/", status_code=303)

    cliente = session.get(Client, client_id)
    usuarios = _mt_users_do_cliente(session, ctx.company.id, client_id)
    # Remove o próprio gestor da lista gerenciável
    usuarios = [u for u in usuarios if u["user_id"] != ctx.user.id]
    disponiveis = _mt_users_disponiveis(session, ctx.company.id, client_id)

    cc = get_client_or_none(session, ctx.company.id, client_id)
    return render("meu_time.html", request=request, context={
        "current_user": ctx.user, "current_company": ctx.company,
        "role": ctx.membership.role, "current_client": cc,
        "cliente": cliente, "usuarios": usuarios,
        "disponiveis": disponiveis,
        "flash": request.session.pop("flash", None),
    })


@app.post("/meu-time/{user_id}/role")
@require_login
async def mt_meu_time_set_role(
    request: _Req_mt,
    session: _Sess_mt = _Dep_mt(get_session),
    user_id: int = 0,
    role: str = _Form_mt("usuario"),
):
    ctx = get_tenant_context(request, session)
    if not ctx:
        return _RR_mt("/login", status_code=303)

    client_id = _mt_get_client_for_gestor(session, ctx.company.id, ctx.user.id)
    if not client_id:
        return _RR_mt("/", status_code=303)

    if role not in ("gestor", "usuario"):
        role = "usuario"

    _mt_set_cliente_role(session, ctx.company.id, client_id, user_id, role)
    set_flash(request, f"Papel atualizado para {role}.")
    return _RR_mt("/meu-time", status_code=303)


@app.post("/meu-time/{user_id}/adicionar")
@require_login
async def mt_meu_time_adicionar(
    request: _Req_mt,
    session: _Sess_mt = _Dep_mt(get_session),
    user_id: int = 0,
    role: str = _Form_mt("usuario"),
):
    ctx = get_tenant_context(request, session)
    if not ctx:
        return _RR_mt("/login", status_code=303)

    client_id = _mt_get_client_for_gestor(session, ctx.company.id, ctx.user.id)
    if not client_id:
        return _RR_mt("/", status_code=303)

    if role not in ("gestor", "usuario"):
        role = "usuario"

    _mt_ensure_membership(session, ctx.company.id, client_id, user_id)
    _mt_set_cliente_role(session, ctx.company.id, client_id, user_id, role)
    set_flash(request, "Usuário adicionado ao seu time.")
    return _RR_mt("/meu-time", status_code=303)


@app.post("/meu-time/{user_id}/remover")
@require_login
async def mt_meu_time_remover(
    request: _Req_mt,
    session: _Sess_mt = _Dep_mt(get_session),
    user_id: int = 0,
):
    ctx = get_tenant_context(request, session)
    if not ctx:
        return _RR_mt("/login", status_code=303)

    client_id = _mt_get_client_for_gestor(session, ctx.company.id, ctx.user.id)
    if not client_id:
        return _RR_mt("/", status_code=303)

    try:
        cr = session.exec(
            _sel_mt(ClienteRole).where(
                ClienteRole.company_id == ctx.company.id,
                ClienteRole.client_id == client_id,
                ClienteRole.user_id == user_id,
            )
        ).first()
        if cr:
            session.delete(cr)
        # Limpa client_id do membership (não exclui o user da company)
        ms = session.exec(
            _sel_mt(Membership).where(
                Membership.company_id == ctx.company.id,
                Membership.client_id == client_id,
                Membership.user_id == user_id,
            )
        ).first()
        if ms:
            ms.client_id = None
            session.add(ms)
        session.commit()
    except Exception as e:
        print(f"[mt] ⚠️ remover: {e}")

    set_flash(request, "Usuário removido do time.")
    return _RR_mt("/meu-time", status_code=303)


# ── Templates ─────────────────────────────────────────────────────────────────

TEMPLATES["cliente_usuarios.html"] = r"""
{% extends "base.html" %}
{% block content %}
<div class="d-flex justify-content-between align-items-center mb-3 flex-wrap gap-2">
  <div>
    <h5 class="mb-0">👤 Usuários — {{ cliente.name }}</h5>
    <div class="muted small">Gerencie quem tem acesso e qual papel exerce neste cliente.</div>
  </div>
  <a href="/admin/clientes/{{ cliente.id }}" class="btn btn-outline-secondary btn-sm">← Voltar</a>
</div>

{% if flash %}<div class="alert alert-info py-2">{{ flash }}</div>{% endif %}

<!-- Adicionar usuário existente -->
{% if disponiveis %}
<div class="card p-3 mb-3">
  <div class="fw-semibold small mb-2">➕ Adicionar usuário existente</div>
  <form method="post" action="/admin/clientes/{{ cliente.id }}/usuarios/adicionar" class="d-flex gap-2 flex-wrap align-items-end">
    <div>
      <label class="form-label mb-1" style="font-size:.75rem;">Usuário</label>
      <select name="user_id" class="form-select form-select-sm" required style="min-width:200px;">
        <option value="">Selecione…</option>
        {% for u in disponiveis %}
        <option value="{{ u.user_id }}">{{ u.name }} ({{ u.email }})</option>
        {% endfor %}
      </select>
    </div>
    <div>
      <label class="form-label mb-1" style="font-size:.75rem;">Papel</label>
      <select name="role" class="form-select form-select-sm">
        <option value="usuario">👤 Usuário</option>
        <option value="gestor">🔑 Gestor</option>
      </select>
    </div>
    <button class="btn btn-primary btn-sm">Adicionar</button>
  </form>
</div>
{% endif %}

<!-- Lista de usuários vinculados -->
{% if not usuarios %}
  <div class="alert alert-light border">Nenhum usuário vinculado a este cliente.</div>
{% else %}
<div class="card overflow-hidden mb-3">
  <table class="table table-hover mb-0" style="font-size:.85rem;">
    <thead class="table-light">
      <tr>
        <th>Nome</th>
        <th>E-mail</th>
        <th>Papel no cliente</th>
        <th></th>
      </tr>
    </thead>
    <tbody>
      {% for u in usuarios %}
      <tr>
        <td class="fw-semibold">{{ u.name }}</td>
        <td class="muted">{{ u.email }}</td>
        <td>
          <form method="post" action="/admin/clientes/{{ cliente.id }}/usuarios/{{ u.user_id }}/role">
            <select name="role" class="form-select form-select-sm d-inline-block" style="width:auto;" onchange="this.form.submit()">
              <option value="gestor"  {% if u.cliente_role == "gestor" %}selected{% endif %}>🔑 Gestor</option>
              <option value="usuario" {% if u.cliente_role == "usuario" %}selected{% endif %}>👤 Usuário</option>
            </select>
          </form>
        </td>
        <td>
          <form method="post" action="/admin/clientes/{{ cliente.id }}/usuarios/{{ u.user_id }}/remover"
                onsubmit="return confirm('Remover {{ u.name }} deste cliente?')">
            <button class="btn btn-outline-danger btn-sm" style="font-size:.72rem;">Remover</button>
          </form>
        </td>
      </tr>
      {% endfor %}
    </tbody>
  </table>
</div>
<div class="muted small">
  <b>🔑 Gestor</b>: vê todas as reuniões e dados do cliente, pode gerenciar o próprio time.<br>
  <b>👤 Usuário</b>: vê apenas as reuniões em que foi adicionado como participante.
</div>
{% endif %}
{% endblock %}
"""


TEMPLATES["meu_time.html"] = r"""
{% extends "base.html" %}
{% block content %}
<div class="d-flex justify-content-between align-items-center mb-3 flex-wrap gap-2">
  <div>
    <h5 class="mb-0">👥 Meu Time — {{ cliente.name }}</h5>
    <div class="muted small">Gerencie os usuários da sua empresa na plataforma.</div>
  </div>
</div>

{% if flash %}<div class="alert alert-info py-2">{{ flash }}</div>{% endif %}

<!-- Adicionar usuário -->
{% if disponiveis %}
<div class="card p-3 mb-4">
  <div class="fw-semibold small mb-2">➕ Adicionar pessoa ao time</div>
  <form method="post" class="d-flex gap-2 flex-wrap align-items-end">
    <div>
      <label class="form-label mb-1" style="font-size:.75rem;">Pessoa</label>
      <select name="user_id" class="form-select form-select-sm" style="min-width:200px;" required>
        <option value="">Selecione…</option>
        {% for u in disponiveis %}
        <option value="{{ u.user_id }}">{{ u.name }} ({{ u.email }})</option>
        {% endfor %}
      </select>
    </div>
    <div>
      <label class="form-label mb-1" style="font-size:.75rem;">Papel</label>
      <select name="role" class="form-select form-select-sm">
        <option value="usuario">👤 Usuário</option>
        <option value="gestor">🔑 Gestor</option>
      </select>
    </div>
    <button formaction="/meu-time/{{ 0 }}/adicionar" class="btn btn-primary btn-sm">Adicionar</button>
  </form>
</div>
{% endif %}

<!-- Time atual -->
{% if not usuarios %}
  <div class="alert alert-light border">Você é o único no time por enquanto. Adicione pessoas acima.</div>
{% else %}
<div class="card overflow-hidden">
  <table class="table table-hover mb-0" style="font-size:.86rem;">
    <thead class="table-light">
      <tr><th>Nome</th><th>E-mail</th><th>Papel</th><th></th></tr>
    </thead>
    <tbody>
      {% for u in usuarios %}
      <tr>
        <td class="fw-semibold">{{ u.name }}</td>
        <td class="muted">{{ u.email }}</td>
        <td>
          <form method="post" action="/meu-time/{{ u.user_id }}/role">
            <select name="role" class="form-select form-select-sm d-inline-block" style="width:auto;" onchange="this.form.submit()">
              <option value="gestor"  {% if u.cliente_role == "gestor" %}selected{% endif %}>🔑 Gestor</option>
              <option value="usuario" {% if u.cliente_role == "usuario" %}selected{% endif %}>👤 Usuário</option>
            </select>
          </form>
        </td>
        <td>
          <form method="post" action="/meu-time/{{ u.user_id }}/remover"
                onsubmit="return confirm('Remover {{ u.name }} do time?')">
            <button class="btn btn-outline-danger btn-sm" style="font-size:.72rem;">Remover</button>
          </form>
        </td>
      </tr>
      {% endfor %}
    </tbody>
  </table>
</div>
<div class="muted small mt-2">
  <b>🔑 Gestor</b>: acesso completo, pode gerenciar o time.<br>
  <b>👤 Usuário</b>: vê apenas as reuniões em que participa.
</div>
{% endif %}
{% endblock %}
"""

# ── Propagação + UI: busca disponiveis para cliente_usuarios ─────────────────

# Patch rota GET /admin/clientes/{cid}/usuarios para incluir "disponiveis"
try:
    app.routes[:] = [r for r in app.routes
                     if not (hasattr(r, "path") and r.path == "/admin/clientes/{client_id}/usuarios")]

    @app.get("/admin/clientes/{client_id}/usuarios", response_class=_HTML_mt)
    @require_login
    async def mt_usuarios_cliente(
        request: _Req_mt,
        session: _Sess_mt = _Dep_mt(get_session),
        client_id: int = 0,
    ):
        ctx = get_tenant_context(request, session)
        if not ctx or ctx.membership.role not in ("admin", "equipe"):
            return _RR_mt("/", status_code=303)
        cliente = session.get(Client, client_id)
        if not cliente or cliente.company_id != ctx.company.id:
            return _RR_mt("/admin/clientes", status_code=303)

        usuarios = _mt_users_do_cliente(session, ctx.company.id, client_id)
        disponiveis = _mt_users_disponiveis(session, ctx.company.id, client_id)
        cc = get_client_or_none(session, ctx.company.id,
                                get_active_client_id(request, session, ctx))
        return render("cliente_usuarios.html", request=request, context={
            "current_user": ctx.user, "current_company": ctx.company,
            "role": ctx.membership.role, "current_client": cc,
            "cliente": cliente, "usuarios": usuarios, "disponiveis": disponiveis,
            "flash": request.session.pop("flash", None),
        })

    print("[mt] ✅ Rota /admin/clientes/{id}/usuarios atualizada.")
except Exception as _e_mt_rt:
    print(f"[mt] ⚠️ Rota: {_e_mt_rt}")

# Propaga templates
for _tk_mt in ("cliente_usuarios.html", "meu_time.html"):
    if hasattr(templates_env.loader, "mapping"):
        templates_env.loader.mapping[_tk_mt] = TEMPLATES[_tk_mt]

# Adiciona "Meu Time" na sidebar para gestores (via feature key)
try:
    FEATURE_KEYS["meu_time"] = {
        "title": "👥 Meu Time",
        "desc": "Gerencie os usuários do seu cliente.",
        "href": "/meu-time",
    }
    FEATURE_VISIBLE_ROLES["meu_time"] = {"cliente"}
    ROLE_DEFAULT_FEATURES.setdefault("cliente", set()).add("meu_time")
    print("[mt] ✅ Feature 'meu_time' registrada.")
except Exception as _e_mt_feat:
    print(f"[mt] ⚠️ Feature: {_e_mt_feat}")

print("[mt] ✅ Módulo multi-tenancy carregado.")

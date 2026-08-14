# ui_change_member_role.py — Permite alterar o role de um membro existente
# Exec'd no namespace do app.py

from fastapi import Request as _Req_cmr, Depends as _Dep_cmr, Form as _Form_cmr
from fastapi.responses import RedirectResponse as _RR_cmr
from sqlmodel import Session as _Sess_cmr

_VALID_ROLES = {"admin", "equipe", "cliente"}

try:
    @app.post("/admin/members/{membership_id}/change-role")  # type: ignore[name-defined]
    @require_login  # type: ignore[name-defined]
    async def cmr_change_role(
        request: _Req_cmr,
        session: _Sess_cmr = _Dep_cmr(get_session),  # type: ignore[name-defined]
        membership_id: int = 0,
        new_role: str = _Form_cmr(""),
    ):
        ctx = get_tenant_context(request, session)  # type: ignore[name-defined]
        if not ctx or ctx.membership.role != "admin":
            set_flash(request, "Apenas administradores podem alterar roles.")  # type: ignore[name-defined]
            return _RR_cmr("/admin/members", status_code=303)

        new_role = new_role.strip().lower()
        if new_role not in _VALID_ROLES:
            set_flash(request, "Role inválida.")  # type: ignore[name-defined]
            return _RR_cmr("/admin/members", status_code=303)

        m = session.get(Membership, membership_id)  # type: ignore[name-defined]
        if not m or m.company_id != ctx.company.id:
            set_flash(request, "Membro não encontrado.")  # type: ignore[name-defined]
            return _RR_cmr("/admin/members", status_code=303)

        # Impede admin de rebaixar a si mesmo
        if m.user_id == ctx.user.id:
            set_flash(request, "Você não pode alterar seu próprio role.")  # type: ignore[name-defined]
            return _RR_cmr("/admin/members", status_code=303)

        m.role = new_role
        if new_role != "cliente":
            m.client_id = None  # limpa vínculo de cliente ao promover para equipe/admin
        session.add(m)
        session.commit()

        set_flash(request, f"Role atualizado para '{new_role}'.")  # type: ignore[name-defined]
        return _RR_cmr("/admin/members", status_code=303)

    print("[change_role] ✅ POST /admin/members/{id}/change-role registrado")
except Exception as _e_cmr:
    print(f"[change_role] ⚠️ {_e_cmr}")


# ── Injeta seletor de role inline na tabela de membros ───────────────────────
_ROLE_CHANGE_SNIPPET = r"""
                <form class="d-inline-flex align-items-center gap-1 mt-1" method="post"
                      action="/admin/members/{{ row.membership.id }}/change-role">
                  <select name="new_role" class="form-select form-select-sm" style="width:auto;font-size:.75rem;">
                    <option value="admin"   {% if row.membership.role == "admin"   %}selected{% endif %}>👑 admin</option>
                    <option value="equipe"  {% if row.membership.role == "equipe"  %}selected{% endif %}>🧑‍💼 equipe</option>
                    <option value="cliente" {% if row.membership.role == "cliente" %}selected{% endif %}>👤 cliente</option>
                  </select>
                  <button class="btn btn-outline-secondary btn-sm" style="font-size:.72rem;padding:2px 7px;"
                          title="Alterar role">↻</button>
                </form>"""

try:
    _tpl_cmr = TEMPLATES.get("members.html", "")  # type: ignore[name-defined]
    _ANCHOR = "Role: <b>{{ row.membership.role }}</b>"
    if _tpl_cmr and "change-role" not in _tpl_cmr and _ANCHOR in _tpl_cmr:
        _tpl_cmr = _tpl_cmr.replace(
            _ANCHOR,
            _ANCHOR + "\n" + _ROLE_CHANGE_SNIPPET,
            1,
        )
        TEMPLATES["members.html"] = _tpl_cmr  # type: ignore[name-defined]
        if hasattr(templates_env.loader, "mapping"):  # type: ignore[name-defined]
            templates_env.loader.mapping["members.html"] = _tpl_cmr
        print("[change_role] ✅ Seletor de role injetado em members.html")
    elif "change-role" in _tpl_cmr:
        print("[change_role] ℹ️ Já injetado")
    else:
        print(f"[change_role] ⚠️ Marcador '{_ANCHOR}' não encontrado em members.html")
except Exception as _e_cmr2:
    print(f"[change_role] ⚠️ inject: {_e_cmr2}")

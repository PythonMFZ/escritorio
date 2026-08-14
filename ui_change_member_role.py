# ui_change_member_role.py — Permite alterar o role de um membro existente
# Exec'd no namespace do app.py

from fastapi import Request as _Req_cmr, Depends as _Dep_cmr, Form as _Form_cmr, Path as _Path_cmr
from fastapi.responses import RedirectResponse as _RR_cmr
from sqlmodel import Session as _Sess_cmr

_VALID_ROLES = {"admin", "equipe", "cliente"}

try:
    @app.post("/admin/members/{membership_id}/change-role")  # type: ignore[name-defined]
    @require_login  # type: ignore[name-defined]
    async def cmr_change_role(
        request: _Req_cmr,
        session: _Sess_cmr = _Dep_cmr(get_session),  # type: ignore[name-defined]
        membership_id: int = _Path_cmr(...),
        new_role: str = _Form_cmr(""),
    ):
        print(f"[change_role] POST membership_id={membership_id!r} new_role={new_role!r}")
        ctx = get_tenant_context(request, session)  # type: ignore[name-defined]
        if not ctx or ctx.membership.role != "admin":
            print(f"[change_role] BLOCKED: ctx={ctx is not None}, role={ctx.membership.role if ctx else 'N/A'}")
            set_flash(request, "Apenas administradores podem alterar roles.")  # type: ignore[name-defined]
            return _RR_cmr("/admin/members", status_code=303)

        new_role = new_role.strip().lower()
        if new_role not in _VALID_ROLES:
            print(f"[change_role] INVALID ROLE: {new_role!r}")
            set_flash(request, "Role inválida.")  # type: ignore[name-defined]
            return _RR_cmr("/admin/members", status_code=303)

        m = session.get(Membership, membership_id)  # type: ignore[name-defined]
        if not m or m.company_id != ctx.company.id:
            print(f"[change_role] NOT FOUND: m={m}, company={ctx.company.id if ctx else 'N/A'}")
            set_flash(request, "Membro não encontrado.")  # type: ignore[name-defined]
            return _RR_cmr("/admin/members", status_code=303)

        # Impede admin de rebaixar a si mesmo
        if m.user_id == ctx.user.id:
            print(f"[change_role] SELF CHANGE BLOCKED")
            set_flash(request, "Você não pode alterar seu próprio role.")  # type: ignore[name-defined]
            return _RR_cmr("/admin/members", status_code=303)

        print(f"[change_role] Updating m.id={m.id} from {m.role!r} to {new_role!r}")
        m.role = new_role
        if new_role != "cliente":
            m.client_id = None  # limpa vinculo de cliente ao promover para equipe/admin
        session.add(m)
        session.commit()
        session.refresh(m)
        print(f"[change_role] After commit: m.role={m.role!r}")

        set_flash(request, f"Role atualizado para '{new_role}'.")  # type: ignore[name-defined]
        return _RR_cmr("/admin/members", status_code=303)

    print("[change_role] OK POST /admin/members/{id}/change-role registrado")
except Exception as _e_cmr:
    print(f"[change_role] ERRO registro: {_e_cmr}")

# ============================================================================
# ui_acoes_cliente.py — Libera /admin/acoes para role=cliente
# ============================================================================
# Re-registra a rota /admin/acoes com suporte a role=cliente:
#   - Cliente vê apenas ações do próprio client_id (ignora query param)
#   - KPIs filtrados ao client_id do cliente (não exibe dados de outros)
#   - Filtro de cliente (dropdown) oculto para clientes
# ============================================================================

from fastapi.responses import HTMLResponse as _HTML_ac, RedirectResponse as _RR_ac
from fastapi import Request as _Req_ac, Depends as _Dep_ac
from sqlmodel import Session as _Sess_ac

try:
    app.routes[:] = [r for r in app.routes
                     if not (hasattr(r, "path") and r.path == "/admin/acoes"
                             and hasattr(r, "methods") and "GET" in (r.methods or set()))]

    @app.get("/admin/acoes", response_class=_HTML_ac)
    @require_login
    async def ac_admin_acoes(request: _Req_ac, session: _Sess_ac = _Dep_ac(get_session)):
        ctx = get_tenant_context(request, session)
        if not ctx:
            return _RR_ac("/login", status_code=303)

        role = ctx.membership.role
        if role not in ("admin", "equipe", "cliente"):
            return _RR_ac("/", status_code=303)

        is_cliente = (role == "cliente")

        # Clientes: forçar client_id do membership (ignorar query param)
        if is_cliente:
            fid = ctx.membership.client_id
            filtro_client = str(fid) if fid else ""
        else:
            filtro_client = request.query_params.get("client_id", "")
            fid = int(filtro_client) if filtro_client and filtro_client.isdigit() else None

        filtro_status = request.query_params.get("status", "")
        filtro_pri    = request.query_params.get("prioridade", "")
        filtro_fonte  = request.query_params.get("fonte", "")

        # ── MeetingAcao ──────────────────────────────────────────────────────
        from sqlmodel import select as _sel_ac
        q = _sel_ac(MeetingAcao).where(MeetingAcao.company_id == ctx.company.id)
        if filtro_status and filtro_fonte != "bsc":
            q = q.where(MeetingAcao.status == filtro_status)
        if filtro_pri:
            q = q.where(MeetingAcao.prioridade == filtro_pri)
        if fid:
            q = q.where(MeetingAcao.client_id == fid)
        q = q.order_by(MeetingAcao.created_at.desc())

        acoes = []
        if filtro_fonte != "bsc":
            for a in session.exec(q).all():
                c = session.get(Client, a.client_id)
                acoes.append({
                    "tipo": "reuniao",
                    "id": str(a.id),
                    "titulo": a.titulo or "—",
                    "descricao": a.descricao or "",
                    "prioridade": a.prioridade,
                    "status": a.status,
                    "status_label": a.status.replace("_", " ").capitalize(),
                    "responsavel": a.responsavel or "—",
                    "prazo": a.prazo or "—",
                    "origem_label": "Reunião",
                    "origem_url": f"/reunioes/{a.meeting_id}/acoes",
                    "_client_name": c.name if c else f"#{a.client_id}",
                    "client_id": a.client_id,
                    "_acao_id": a.id,
                })

        # ── Itens BSC ────────────────────────────────────────────────────────
        bsc_itens = []
        if filtro_fonte != "reuniao":
            bsc_itens = _bsc_itens_atencao(session, ctx.company.id, fid)
            if filtro_pri:
                bsc_itens = [i for i in bsc_itens if i["prioridade"] == filtro_pri]

        todos_itens = acoes + bsc_itens

        # ── KPIs — restritos ao client_id para clientes ───────────────────────
        kpi_q = _sel_ac(MeetingAcao).where(MeetingAcao.company_id == ctx.company.id)
        if fid:
            kpi_q = kpi_q.where(MeetingAcao.client_id == fid)
        todas_acoes = session.exec(kpi_q).all()
        todos_bsc   = _bsc_itens_atencao(session, ctx.company.id, fid)
        todos_bsc_kpis  = [i for i in todos_bsc if i["id"].startswith("bsckpi_")]
        todos_bsc_acoes = [i for i in todos_bsc if i["id"].startswith("bscac_")]
        kpis = [
            ("Ações abertas",   sum(1 for a in todas_acoes if a.status == "aberta") + sum(1 for i in todos_bsc_acoes if i["status"] in ("pendente", "em_andamento")), "#3b82f6"),
            ("Em andamento",    sum(1 for a in todas_acoes if a.status == "em_andamento") + sum(1 for i in todos_bsc_acoes if i["status"] == "em_andamento"), "#f59e0b"),
            ("Alta prioridade", sum(1 for a in todas_acoes if a.prioridade == "alta" and a.status not in ("concluida", "cancelada")) + sum(1 for i in todos_bsc_acoes if i["prioridade"] == "alta" and i["status"] not in ("concluida", "cancelada")), "#ef4444"),
            ("KPIs atenção",    len(todos_bsc_kpis), "#a855f7"),
            ("Concluídas",      sum(1 for a in todas_acoes if a.status == "concluida") + sum(1 for i in todos_bsc_acoes if i["status"] == "concluida"), "#22c55e"),
        ]

        # Clientes não veem o seletor de cliente (dropdown)
        clientes = [] if is_cliente else session.exec(
            _sel_ac(Client).where(Client.company_id == ctx.company.id)
        ).all()

        cc = get_client_or_none(session, ctx.company.id,
                                fid if is_cliente else get_active_client_id(request, session, ctx))
        return render("admin_acoes.html", request=request, context={
            "current_user": ctx.user, "current_company": ctx.company,
            "role": role, "current_client": cc,
            "acoes": todos_itens, "total": len(todos_itens),
            "filtro_status": filtro_status, "filtro_pri": filtro_pri,
            "filtro_client": filtro_client, "filtro_fonte": filtro_fonte,
            "clientes": clientes, "kpis": kpis,
        })

    print("[ac] ✅ /admin/acoes liberado para role=cliente com filtro por client_id.")

except Exception as _e_ac:
    print(f"[ac] ⚠️ Erro ao registrar rota: {_e_ac}")


# ── Patch do status de ação: liberar clientes ─────────────────────────────────
# POST /admin/acoes/{id}/status já existe — verificar se bloqueia clientes

try:
    from fastapi import Form as _Form_ac

    # Encontra e substitui a rota de status se tiver require_role restritivo
    _status_routes = [r for r in app.routes
                      if hasattr(r, "path") and r.path == "/admin/acoes/{acao_id}/status"
                      and hasattr(r, "methods") and "POST" in (r.methods or set())]

    if _status_routes:
        # A rota existe — verificar se aceita clientes (não podemos ler o decorator em runtime,
        # então re-registramos com lógica segura)
        app.routes[:] = [r for r in app.routes
                         if not (hasattr(r, "path") and r.path == "/admin/acoes/{acao_id}/status"
                                 and hasattr(r, "methods") and "POST" in (r.methods or set()))]

        @app.post("/admin/acoes/{acao_id}/status")
        @require_login
        async def ac_status_acao(
            request: _Req_ac,
            session: _Sess_ac = _Dep_ac(get_session),
            acao_id: int = 0,
            status: str = _Form_ac(""),
        ):
            ctx = get_tenant_context(request, session)
            if not ctx:
                return _RR_ac("/login", status_code=303)

            a = session.get(MeetingAcao, acao_id)
            if not a or a.company_id != ctx.company.id:
                set_flash(request, "Ação não encontrada.")
                return _RR_ac("/admin/acoes", status_code=303)

            # Clientes só podem alterar ações do próprio client_id
            if ctx.membership.role not in ("admin", "equipe"):
                if ctx.membership.role != "cliente" or ctx.membership.client_id != a.client_id:
                    set_flash(request, "Sem permissão.")
                    return _RR_ac("/admin/acoes", status_code=303)

            valid = ("aberta", "em_andamento", "concluida", "cancelada")
            if status in valid:
                a.status = status
                session.add(a)
                session.commit()
                set_flash(request, f"Status atualizado para '{status}'.")
            else:
                set_flash(request, "Status inválido.")

            return _RR_ac("/admin/acoes", status_code=303)

        print("[ac] ✅ POST /admin/acoes/{id}/status liberado para clientes.")

except Exception as _e_ac_st:
    print(f"[ac] ⚠️ status patch: {_e_ac_st}")

print("[ac] ✅ Módulo ações cliente carregado.")

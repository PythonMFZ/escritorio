# ============================================================================
# ui_grafo_client_filter.py — Corrige filtro de usuários no /api/grafo/data
# ============================================================================
# Quando filter_client_id está ativo, a versão original carregava TODOS os
# membros da empresa como nós "Pessoa" (amarelos), ignorando o filtro.
# Este patch re-registra a rota com filtro correto de usuários:
#   - Sem filtro: comportamento original (todos os membros visíveis)
#   - Com filtro: apenas usuários vinculados ao client_id OU referenciados
#     em reuniões/ações daquele cliente (criadores, responsáveis, participantes)
# ============================================================================

from fastapi.responses import JSONResponse as _JR_gf

try:
    # Remove rota original
    app.routes[:] = [r for r in app.routes
                     if not (hasattr(r, "path") and r.path == "/api/grafo/data"
                             and hasattr(r, "methods") and "GET" in (r.methods or set()))]

    @app.get("/api/grafo/data")
    @require_login
    async def api_grafo_data_filtered(request: Request, session: Session = Depends(get_session)):
        from sqlmodel import select as _sel_gf

        ctx = get_tenant_context(request, session)
        if not ctx or ctx.membership.role not in ("admin", "equipe"):
            return _JR_gf({"erro": "sem permissão"}, status_code=403)

        cid = ctx.company.id
        filter_client = request.query_params.get("client_id")
        filter_client_id = int(filter_client) if filter_client and filter_client.isdigit() else None

        nodes = []
        edges = []
        seen_edges = set()

        def add_node(id_, label, group, title="", url="", size=18):
            nodes.append({"id": id_, "label": label, "group": group,
                          "title": title, "url": url, "size": size})

        def add_edge(src, dst, label=""):
            key = f"{src}|{dst}"
            if key not in seen_edges:
                seen_edges.add(key)
                edges.append({"from": src, "to": dst, "label": label})

        # ── Clientes ─────────────────────────────────────────────────────────
        try:
            clientes = session.exec(_sel_gf(Client).where(Client.company_id == cid)).all()
            if filter_client_id:
                clientes = [c for c in clientes if c.id == filter_client_id]
            client_ids = {c.id for c in clientes}
            for c in clientes:
                add_node(f"client_{c.id}", (c.name or f"#{c.id}")[:20], "client",
                         title=f"Cliente: {c.name}", url=f"/client/switch?client_id={c.id}", size=26)
        except Exception:
            clientes = []; client_ids = set()

        # ── Reuniões ─────────────────────────────────────────────────────────
        # Carrega antes dos usuários para saber quais user_ids referenciar
        meetings_data = []
        referenced_user_ids = set()
        try:
            q = _sel_gf(Meeting).where(Meeting.company_id == cid)
            if filter_client_id:
                q = q.where(Meeting.client_id == filter_client_id)
            for mt in session.exec(q).all():
                if mt.client_id not in client_ids:
                    continue
                meetings_data.append(mt)
                if mt.created_by_user_id:
                    referenced_user_ids.add(mt.created_by_user_id)
        except Exception:
            pass

        # ── Ações corretivas ─────────────────────────────────────────────────
        acoes_data = []
        try:
            q = _sel_gf(MeetingAcao).where(MeetingAcao.company_id == cid)
            if filter_client_id:
                q = q.where(MeetingAcao.client_id == filter_client_id)
            for a in session.exec(q).all():
                acoes_data.append(a)
                if a.responsavel_user_id:
                    referenced_user_ids.add(a.responsavel_user_id)
        except Exception:
            pass

        # ── Membros ───────────────────────────────────────────────────────────
        # Com filtro: apenas usuários do cliente OU referenciados em dados filtrados
        # Sem filtro: todos os membros da empresa
        user_ids_seen = set()
        try:
            all_memberships = session.exec(
                _sel_gf(Membership).where(Membership.company_id == cid)
            ).all()

            for m in all_memberships:
                u = session.get(User, m.user_id)
                if not u or m.user_id in user_ids_seen:
                    continue

                if filter_client_id:
                    # Inclui: (1) usuários vinculados ao cliente, (2) referenciados em meetings/ações
                    is_client_user = (m.client_id == filter_client_id)
                    is_referenced = (m.user_id in referenced_user_ids)
                    if not (is_client_user or is_referenced):
                        continue

                user_ids_seen.add(m.user_id)
                add_node(f"user_{m.user_id}", (u.name or u.email or f"#{m.user_id}")[:18], "user",
                         title=f"{u.name or ''} ({m.role})\n{u.email or ''}", url="/admin/members")
        except Exception:
            pass

        # ── Adiciona nós de reuniões e arestas ───────────────────────────────
        for mt in meetings_data:
            add_node(f"meet_{mt.id}", (mt.title or "Reunião")[:20], "meeting",
                     title=f"Reunião: {mt.title}\nData: {mt.meeting_date or '—'}",
                     url=f"/reunioes/{mt.id}")
            add_edge(f"client_{mt.client_id}", f"meet_{mt.id}")
            if mt.created_by_user_id in user_ids_seen:
                add_edge(f"user_{mt.created_by_user_id}", f"meet_{mt.id}", "criou")

        # ── Adiciona nós de ações e arestas ──────────────────────────────────
        for a in acoes_data:
            grp = "acao_alta" if a.prioridade == "alta" else "acao"
            prazo = f"\nPrazo: {a.prazo}" if a.prazo else ""
            resp = f"\nResp: {a.responsavel}" if a.responsavel else ""
            add_node(f"acao_{a.id}", (a.titulo or "Ação")[:20], grp,
                     title=f"[{a.prioridade.upper()}] {a.titulo}\n{a.status}{prazo}{resp}",
                     url=f"/reunioes/{a.meeting_id}/acoes", size=14)
            add_edge(f"meet_{a.meeting_id}", f"acao_{a.id}", a.status)
            if a.responsavel_user_id and a.responsavel_user_id in user_ids_seen:
                add_edge(f"user_{a.responsavel_user_id}", f"acao_{a.id}", "resp.")

        # ── Planos orçamentários ──────────────────────────────────────────────
        try:
            q = _sel_gf(BudgetPlan).where(BudgetPlan.company_id == cid, BudgetPlan.is_active == True)
            if filter_client_id:
                q = q.where(BudgetPlan.client_id == filter_client_id)
            for p in session.exec(q).all():
                if p.client_id and p.client_id not in client_ids:
                    continue
                add_node(f"budget_{p.id}", f"Orç.{p.year}", "budget",
                         title=f"Orçamento: {p.name}\nAno: {p.year}",
                         url=f"/ferramentas/orcamento/{p.id}", size=20)
                if p.client_id:
                    add_edge(f"client_{p.client_id}", f"budget_{p.id}", "orçamento")
        except Exception:
            pass

        # ── Desvios ───────────────────────────────────────────────────────────
        try:
            for al in session.exec(_sel_gf(BudgetAlert).where(BudgetAlert.company_id == cid)).all():
                acc = session.get(BudgetAccount, al.account_id)
                if not acc:
                    continue
                if filter_client_id and acc.client_id != filter_client_id:
                    continue
                add_node(f"desvio_{al.id}", f"⚠ {acc.name[:16]}", "desvio",
                         title=f"Alerta: {acc.name}\nTol:{al.tolerance_pct}% Crit:{al.critical_pct}%",
                         url="#", size=14)
                if acc.client_id:
                    pl = session.exec(_sel_gf(BudgetPlan).where(
                        BudgetPlan.company_id == cid,
                        BudgetPlan.client_id == acc.client_id,
                        BudgetPlan.is_active == True,
                    )).first()
                    if pl:
                        add_edge(f"budget_{pl.id}", f"desvio_{al.id}", "desvio")
        except Exception:
            pass

        # ── Integrações de API / ERP ──────────────────────────────────────────
        try:
            from sqlmodel import or_ as _or_gf
            _ApiInteg = globals().get("ApiIntegration")  # type: ignore[name-defined]
            if _ApiInteg:
                q = _sel_gf(_ApiInteg).where(
                    _ApiInteg.company_id == cid,
                    _ApiInteg.is_active == True,
                )
                if filter_client_id:
                    q = q.where(_or_gf(
                        _ApiInteg.client_id == filter_client_id,
                        _ApiInteg.client_id == None,
                    ))
                for intg in session.exec(q).all():
                    label = (intg.data_label or intg.name or "API")[:20]
                    add_node(f"api_{intg.id}", label, "api_integ",
                             title=f"Integração: {intg.name}\nURL: {intg.url[:60]}\nSync: {intg.sync_interval_hours}h",
                             url="/integrations/api-connector", size=18)
                    # Liga ao cliente se houver vínculo
                    if intg.client_id and intg.client_id in client_ids:
                        add_edge(f"client_{intg.client_id}", f"api_{intg.id}", "ERP")
                    else:
                        # "Empresa toda" — liga a todos os clientes visíveis
                        for cid_ in client_ids:
                            add_edge(f"client_{cid_}", f"api_{intg.id}", "ERP")
        except Exception:
            pass

        # ── Arquivos do Drive (CloudStorageFile) ──────────────────────────────
        try:
            _CloudFile = globals().get("CloudStorageFile")  # type: ignore[name-defined]
            if _CloudFile:
                q = _sel_gf(_CloudFile).where(_CloudFile.company_id == cid)
                if filter_client_id:
                    q = q.where(_CloudFile.client_id == filter_client_id)
                files = session.exec(q).all()
                # Agrupa por extensão para não poluir com centenas de nós
                from collections import Counter as _Counter_gf
                ext_count: dict = {}
                file_nodes: list = []
                for f in files:
                    if f.client_id not in client_ids:
                        continue
                    name = f.file_name or "arquivo"
                    ext = name.rsplit(".", 1)[-1].lower() if "." in name else "file"
                    # Mostra arquivos individualmente se ≤ 15, caso contrário agrupa
                    file_nodes.append(f)
                    ext_count[ext] = ext_count.get(ext, 0) + 1

                if len(file_nodes) <= 15:
                    for f in file_nodes:
                        add_node(f"drive_{f.id}", (f.file_name or "arquivo")[:20], "drive_file",
                                 title=f"Arquivo: {f.file_name}\nIndexado: {f.indexed_at[:10] if f.indexed_at else '—'}",
                                 url="/integrations", size=13)
                        if f.client_id in client_ids:
                            add_edge(f"client_{f.client_id}", f"drive_{f.id}", "drive")
                else:
                    # Agrupa por tipo de arquivo
                    for ext, count in ext_count.items():
                        cid_list = {f.client_id for f in file_nodes if (f.file_name or "").endswith(f".{ext}")}
                        node_id = f"drive_ext_{ext}"
                        add_node(node_id, f"{ext.upper()} ({count})", "drive_file",
                                 title=f"{count} arquivos .{ext} no Drive",
                                 url="/integrations", size=14)
                        for cid_ in cid_list:
                            if cid_ in client_ids:
                                add_edge(f"client_{cid_}", node_id, "drive")
        except Exception:
            pass

        return _JR_gf({"nodes": nodes, "edges": edges})

    print("[grafo_filter] ✅ /api/grafo/data com filtro de usuários por client_id.")

except Exception as _e_gf:
    print(f"[grafo_filter] ⚠️ Erro: {_e_gf}")

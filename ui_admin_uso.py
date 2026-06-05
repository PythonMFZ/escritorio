# ui_admin_uso.py — Rota /especialista + painel /admin/uso
# Exec'd no namespace do app.py

from datetime import timedelta as _tdUso

# ── /especialista — redireciona ao WhatsApp do escritório ────────────────────

@app.get("/especialista")
@require_login
async def especialista_redirect(request: Request, session: Session = Depends(get_session)):
    """Redireciona para o WhatsApp do escritório. Usado em CTAs 'Falar com especialista'."""
    ctx = get_tenant_context(request, session)
    if not ctx:
        return RedirectResponse("/login", status_code=303)

    phone = ""
    try:
        canal = session.exec(
            select(WhatsAppChannelConfig)
            .where(WhatsAppChannelConfig.company_id == ctx.company.id)
        ).first()
        if canal and canal.business_phone:
            phone = "".join(c for c in canal.business_phone if c.isdigit())
    except Exception:
        pass

    if phone:
        # Remove leading 0 se houver, adiciona 55 (Brasil) se não tiver
        if not phone.startswith("55"):
            phone = "55" + phone
        return RedirectResponse(f"https://wa.me/{phone}", status_code=302)

    # fallback: página de contato interna
    return RedirectResponse("/consultoria", status_code=302)


# ── /admin/uso/debug — diagnóstico direto do tracking ────────────────────────

@app.get("/admin/uso/debug")
@require_login
async def admin_uso_debug(request: Request, session: Session = Depends(get_session)):
    ctx = get_tenant_context(request, session)
    if not ctx or ctx.membership.role not in ("admin", "equipe"):
        from fastapi.responses import JSONResponse as _JR
        return _JR({"erro": "sem permissão"}, status_code=403)

    from fastapi.responses import JSONResponse as _JR
    from sqlalchemy import text as _t

    resultado = {}

    # 1. Verifica se a tabela existe
    try:
        r = session.exec(select(UserActivity).limit(1)).first()
        resultado["tabela_existe"] = True
        resultado["amostra"] = str(r) if r else None
    except Exception as e:
        resultado["tabela_existe"] = False
        resultado["tabela_erro"] = str(e)

    # 2. Tenta INSERT direto via engine.begin() + text()
    try:
        from sqlalchemy import text as _sa_text
        _now = utcnow()
        with engine.begin() as _conn:
            _conn.execute(_sa_text("""
                INSERT INTO useractivity
                    (company_id, user_id, role, membership_role, last_client_id, last_path,
                     last_method, request_count, last_seen_at, created_at, updated_at)
                VALUES
                    (:cid, :uid, :role, :role, :lcid, :lpath,
                     :lmeth, 1, :now, :now, :now)
                ON CONFLICT (company_id, user_id)
                DO UPDATE SET
                    role            = EXCLUDED.role,
                    membership_role = EXCLUDED.membership_role,
                    last_path       = EXCLUDED.last_path,
                    request_count   = useractivity.request_count + 1,
                    last_seen_at    = EXCLUDED.last_seen_at,
                    updated_at      = EXCLUDED.updated_at
            """), {
                "cid": int(ctx.company.id), "uid": int(ctx.user.id),
                "role": ctx.membership.role or "", "lcid": None,
                "lpath": "/admin/uso/debug", "lmeth": "GET", "now": _now,
            })
        resultado["insert_ok"] = True
    except Exception as e:
        resultado["insert_ok"] = False
        resultado["insert_erro"] = str(e)

    # 3. Conta registros na tabela
    try:
        cnt = session.exec(
            select(UserActivity).where(UserActivity.company_id == ctx.company.id)
        ).all()
        resultado["total_registros"] = len(cnt)
        resultado["registros"] = [
            {"user_id": r.user_id, "request_count": r.request_count, "last_path": r.last_path}
            for r in cnt
        ]
    except Exception as e:
        resultado["count_erro"] = str(e)

    # 4. Info do contexto atual
    resultado["ctx"] = {
        "user_id": ctx.user.id,
        "company_id": ctx.company.id,
        "role": ctx.membership.role,
        "session_user_id": session_user_id(request),
        "session_company_id": session_company_id(request),
    }

    return _JR(resultado)


# ── /admin/uso — painel de uso da plataforma ─────────────────────────────────

@app.get("/admin/uso", response_class=HTMLResponse)
@require_login
async def admin_uso_page(request: Request, session: Session = Depends(get_session)):
    ctx = get_tenant_context(request, session)
    if not ctx or ctx.membership.role not in ("admin", "equipe"):
        return RedirectResponse("/", status_code=303)

    filtro = request.query_params.get("periodo", "hoje")  # hoje | 7d | 30d | todos
    agora  = utcnow()
    desde  = {
        "1h":    agora - _tdUso(hours=1),
        "hoje":  agora - _tdUso(hours=24),
        "7d":    agora - _tdUso(days=7),
        "30d":   agora - _tdUso(days=30),
        "todos": None,
    }.get(filtro, agora - _tdUso(hours=24))

    try:
        q = select(UserActivity).where(UserActivity.company_id == ctx.company.id)
        if desde:
            q = q.where(UserActivity.last_seen_at >= desde)
        q = q.order_by(UserActivity.last_seen_at.desc())
        registros = session.exec(q).all()
    except Exception:
        registros = []

    # Enriquece com nome do usuário e cliente
    tracked_user_ids = set()
    dados = []
    for r in registros:
        user = session.get(User, r.user_id) if r.user_id else None
        client = session.get(Client, r.last_client_id) if r.last_client_id else None
        tracked_user_ids.add(r.user_id)
        dados.append({
            "user_name":    user.name if user else f"user#{r.user_id}",
            "user_email":   getattr(user, "email", ""),
            "role":         r.role or "—",
            "client_name":  client.name if client else "—",
            "last_path":    r.last_path or "—",
            "request_count": r.request_count or 0,
            "last_seen_at": r.last_seen_at,
        })

    # Membros que NUNCA tiveram atividade (sem row na tabela, independente do período)
    todos_com_atividade = {
        r.user_id for r in session.exec(
            select(UserActivity).where(UserActivity.company_id == ctx.company.id)
        ).all()
    }
    todos_membros = session.exec(
        select(Membership).where(Membership.company_id == ctx.company.id)
    ).all()
    sem_atividade = []
    for m in todos_membros:
        if m.user_id in todos_com_atividade:
            continue
        u = session.get(User, m.user_id)
        if not u:
            continue
        sem_atividade.append({
            "user_name":  u.name or f"user#{u.id}",
            "user_email": u.email or "",
            "role":       m.role or "—",
        })

    # Top rotas
    from collections import Counter as _Ctr
    path_counts = _Ctr(d["last_path"] for d in dados if d["last_path"] not in ("—", ""))
    top_paths   = path_counts.most_common(10)

    cc = get_client_or_none(session, ctx.company.id, get_active_client_id(request, session, ctx))
    return render("admin_uso.html", request=request, context={
        "current_user": ctx.user, "current_company": ctx.company,
        "role": ctx.membership.role, "current_client": cc,
        "dados": dados, "filtro": filtro, "top_paths": top_paths,
        "total": len(dados),
        "sem_atividade": sem_atividade,
    })


TEMPLATES["admin_uso.html"] = r"""
{% extends "base.html" %}
{% block content %}
<style>
  .uso-table td,.uso-table th{vertical-align:middle;font-size:.82rem;}
  .uso-path{font-family:monospace;font-size:.75rem;color:var(--mc-muted);}
</style>

<div class="d-flex justify-content-between align-items-center mb-3 flex-wrap gap-2">
  <div>
    <h4 class="mb-0">Uso da Plataforma</h4>
    <div class="muted small">Última atividade registrada por usuário — {{ total }} registro(s)</div>
  </div>
  <div class="d-flex gap-1 flex-wrap">
    {% for p,lbl in [("1h","Última hora"),("hoje","24h"),("7d","7 dias"),("30d","30 dias"),("todos","Todos")] %}
      <a href="?periodo={{ p }}" class="btn btn-sm {% if filtro==p %}btn-primary{% else %}btn-outline-secondary{% endif %}">{{ lbl }}</a>
    {% endfor %}
  </div>
</div>

{% if top_paths %}
<div class="card p-3 mb-3">
  <div class="fw-semibold small mb-2">🔝 Páginas mais acessadas (período)</div>
  <div class="d-flex flex-wrap gap-2">
    {% for path, cnt in top_paths %}
      <span class="badge bg-light text-dark border" style="font-size:.75rem;">{{ path }} <b>×{{ cnt }}</b></span>
    {% endfor %}
  </div>
</div>
{% endif %}

{% if dados %}
<div class="card p-0 overflow-hidden">
  <table class="table table-hover mb-0 uso-table">
    <thead class="table-light">
      <tr>
        <th>Usuário</th>
        <th>Perfil</th>
        <th>Cliente ativo</th>
        <th>Última página</th>
        <th class="text-end">Req.</th>
        <th>Último acesso</th>
      </tr>
    </thead>
    <tbody>
      {% for d in dados %}
      <tr>
        <td>
          <div class="fw-semibold">{{ d.user_name }}</div>
          <div class="muted" style="font-size:.72rem;">{{ d.user_email }}</div>
        </td>
        <td><span class="badge bg-light text-dark border">{{ d.role }}</span></td>
        <td>{{ d.client_name }}</td>
        <td class="uso-path">{{ d.last_path }}</td>
        <td class="text-end fw-semibold">{{ d.request_count }}</td>
        <td class="muted" style="font-size:.78rem;">
          {% if d.last_seen_at %}
            {{ d.last_seen_at.strftime("%d/%m %H:%M") if d.last_seen_at else "—" }}
          {% endif %}
        </td>
      </tr>
      {% endfor %}
    </tbody>
  </table>
</div>
{% else %}
  <div class="alert alert-info">Nenhuma atividade registrada no período selecionado.</div>
{% endif %}

{% if sem_atividade %}
<div class="card p-3 mt-3" style="border-color:#ffc10744;">
  <div class="fw-semibold mb-2 text-warning">⚠️ Membros sem atividade registrada ({{ sem_atividade|length }})</div>
  <div class="muted small mb-2">Esses usuários têm conta mas nenhum acesso foi registrado ainda — seja porque nunca entraram, ou porque a coleta de dados foi recentemente ativada.</div>
  <table class="table table-sm mb-0">
    <thead class="table-light"><tr><th>Usuário</th><th>E-mail</th><th>Perfil</th></tr></thead>
    <tbody>
      {% for u in sem_atividade %}
      <tr>
        <td class="fw-semibold" style="font-size:.82rem;">{{ u.user_name }}</td>
        <td class="muted" style="font-size:.78rem;">{{ u.user_email }}</td>
        <td><span class="badge bg-light text-dark border" style="font-size:.72rem;">{{ u.role }}</span></td>
      </tr>
      {% endfor %}
    </tbody>
  </table>
</div>
{% endif %}
{% endblock %}
"""

if hasattr(templates_env.loader, "mapping"):
    templates_env.loader.mapping["admin_uso.html"] = TEMPLATES["admin_uso.html"]

print("[admin_uso] ✅ Rotas /especialista e /admin/uso carregadas")

# Garante que as novas features aparecem no menu para admin/equipe
_new_features = {"assinaturas", "pesquisas", "checkin_semanal", "uso_plataforma"}
for _role in ("admin", "equipe"):
    ROLE_DEFAULT_FEATURES.setdefault(_role, set()).update(_new_features)
for _fk in _new_features:
    FEATURE_VISIBLE_ROLES.setdefault(_fk, {"admin", "equipe"})

print(f"[admin_uso] ROLE_DEFAULT_FEATURES admin inclui: {sorted(_new_features & ROLE_DEFAULT_FEATURES.get('admin', set()))}")

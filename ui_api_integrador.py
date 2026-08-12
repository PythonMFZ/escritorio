# ui_api_integrador.py — Generic API Integrator
# exec()'d into the app namespace; globals available: app, engine, get_session,
# get_tenant_context, require_login, render, set_flash, TEMPLATES, templates_env

from __future__ import annotations

import asyncio as _asyncio_ai
import base64  as _b64_ai
from datetime  import datetime, timezone, timedelta
from typing    import Optional
from sqlmodel  import Field as _F_ai, SQLModel as _SM_ai, select as _sel_ai, Session as _Ses_ai
from fastapi   import Depends as _Dep_ai, Form as _Form_ai

# ── Models ────────────────────────────────────────────────────────────────────

class ApiIntegration(_SM_ai, table=True):
    __tablename__  = "apiintegration"
    __table_args__ = {"extend_existing": True}
    id:                  Optional[int] = _F_ai(default=None, primary_key=True)
    company_id:          int
    client_id:           Optional[int] = _F_ai(default=None)
    name:                str
    url:                 str
    method:              str           = _F_ai(default="GET")
    auth_type:           str           = _F_ai(default="api_key_header")
    auth_key:            Optional[str] = _F_ai(default=None)
    auth_value:          Optional[str] = _F_ai(default=None)
    body_json:           Optional[str] = _F_ai(default=None)
    extra_headers_json:  Optional[str] = _F_ai(default=None)  # JSON dict de headers extras
    data_label:          Optional[str] = _F_ai(default=None)
    sync_interval_hours: int           = _F_ai(default=24)
    is_active:           bool          = _F_ai(default=True)
    created_at:          Optional[str] = _F_ai(default=None)


class ApiIntegrationSnapshot(_SM_ai, table=True):
    __tablename__  = "apiintegrationsnapshot"
    __table_args__ = {"extend_existing": True}
    id:             Optional[int] = _F_ai(default=None, primary_key=True)
    integration_id: int
    company_id:     int
    client_id:      Optional[int] = _F_ai(default=None)
    synced_at:      str
    data_json:      str
    status:         str           = _F_ai(default="ok")
    error_msg:      Optional[str] = _F_ai(default=None)


_SM_ai.metadata.create_all(engine)  # type: ignore[name-defined]

# Migration: add extra_headers_json if missing (existing tables not altered by create_all)
try:
    with engine.connect() as _conn_migr_ai:  # type: ignore[name-defined]
        _conn_migr_ai.exec_driver_sql(
            "ALTER TABLE apiintegration ADD COLUMN IF NOT EXISTS extra_headers_json TEXT"
        )
        _conn_migr_ai.commit()
except Exception as _e_migr_ai:
    pass  # already exists or unsupported


# ── HTTP helper ───────────────────────────────────────────────────────────────

def _ai_do_request(intg: ApiIntegration) -> tuple:
    import json as _json_ai
    headers: dict = {}
    auth = None
    if intg.auth_type == "api_key_header" and intg.auth_key:
        headers[intg.auth_key] = intg.auth_value or ""
    elif intg.auth_type == "basic_auth":
        auth = (intg.auth_key or "", intg.auth_value or "")
    # Headers extras (ex: Content-Type: application/json)
    if intg.extra_headers_json:
        try:
            for k, v in _json_ai.loads(intg.extra_headers_json).items():
                headers[k] = str(v)
        except Exception:
            pass

    try:
        import httpx as _hx
        if intg.method == "POST":
            content = intg.body_json.encode() if intg.body_json else b""
            resp = _hx.post(intg.url, headers=headers, auth=auth, content=content, timeout=30)
        else:
            resp = _hx.get(intg.url, headers=headers, auth=auth, timeout=30)
        resp.raise_for_status()
        return True, resp.text[:50000]
    except ImportError:
        pass
    except Exception as e:
        return False, str(e)

    import urllib.request as _ur
    import urllib.error   as _ue
    req = _ur.Request(intg.url, method=intg.method)
    for k, v in headers.items():
        req.add_header(k, v)
    if auth:
        creds = _b64_ai.b64encode(f"{auth[0]}:{auth[1]}".encode()).decode()
        req.add_header("Authorization", f"Basic {creds}")
    if intg.method == "POST" and intg.body_json:
        req.add_header("Content-Type", "application/json")
        req.data = intg.body_json.encode()
    try:
        with _ur.urlopen(req, timeout=30) as resp:
            return True, resp.read().decode("utf-8", errors="replace")[:50000]
    except _ue.HTTPError as e:
        return False, f"HTTP {e.code}: {e.reason}"
    except Exception as e:
        return False, str(e)


def _ai_sync_integration(session, intg: ApiIntegration) -> ApiIntegrationSnapshot:
    ok, result = _ai_do_request(intg)
    now = datetime.now(timezone.utc).isoformat()
    snap = ApiIntegrationSnapshot(
        integration_id=intg.id,
        company_id=intg.company_id,
        client_id=intg.client_id,
        synced_at=now,
        data_json=result if ok else "",
        status="ok" if ok else "error",
        error_msg=None if ok else result[:1000],
    )
    session.add(snap)
    session.commit()
    session.refresh(snap)
    return snap


def _ai_last_snapshot(session, integration_id: int) -> Optional[ApiIntegrationSnapshot]:
    return session.exec(
        _sel_ai(ApiIntegrationSnapshot)
        .where(ApiIntegrationSnapshot.integration_id == integration_id)
        .order_by(ApiIntegrationSnapshot.id.desc())
    ).first()


def _ai_build_clients(session, company_id: int) -> list:
    try:
        return session.exec(
            _sel_ai(Client)  # type: ignore[name-defined]
            .where(Client.company_id == company_id, Client.is_active == True)  # type: ignore[name-defined]
            .order_by(Client.name)  # type: ignore[name-defined]
        ).all()
    except Exception:
        return []


# ── Background sync loop ──────────────────────────────────────────────────────

async def _api_sync_loop():
    await _asyncio_ai.sleep(60)
    while True:
        try:
            from sqlmodel import Session as _SyncSes
            with _SyncSes(engine) as _sess:  # type: ignore[name-defined]
                integrations = _sess.exec(
                    _sel_ai(ApiIntegration).where(
                        ApiIntegration.is_active == True,
                        ApiIntegration.sync_interval_hours > 0,
                    )
                ).all()
                now = datetime.now(timezone.utc)
                for intg in integrations:
                    try:
                        snap = _ai_last_snapshot(_sess, intg.id)
                        if snap:
                            synced = datetime.fromisoformat(snap.synced_at.replace("Z", "+00:00"))
                            if synced.tzinfo is None:
                                synced = synced.replace(tzinfo=timezone.utc)
                            if synced > now - timedelta(hours=intg.sync_interval_hours):
                                continue
                        _ai_sync_integration(_sess, intg)
                    except Exception as e:
                        print(f"[api_integrador] auto-sync intg={intg.id}: {e}")
        except Exception as e:
            print(f"[api_integrador] sync loop error: {e}")
        await _asyncio_ai.sleep(1800)


@app.on_event("startup")  # type: ignore[name-defined]
async def _start_api_sync_loop():
    _asyncio_ai.create_task(_api_sync_loop())


# ── Templates ─────────────────────────────────────────────────────────────────

TEMPLATES["api_connector_list.html"] = r"""
{% extends "base.html" %}
{% block content %}
<div class="container-fluid py-4">
  <div class="d-flex justify-content-between align-items-center mb-3">
    <div>
      <h2 class="mb-0">Integrações de API</h2>
      {% if current_client %}
      <div class="text-muted small mt-1">
        <i class="bi bi-building me-1"></i>Mostrando integrações de <strong>{{ current_client.name }}</strong>
        — <a href="/integrations/api-connector" onclick="sessionStorage.clear()">ver todas</a>
      </div>
      {% else %}
      <div class="text-muted small mt-1">Todas as integrações da empresa · Selecione um cliente no menu para filtrar</div>
      {% endif %}
    </div>
    <a href="/integrations/api-connector/novo" class="btn btn-primary">
      <i class="bi bi-plus-lg me-1"></i>Nova integração
    </a>
  </div>

  <div class="card shadow-sm">
    <div class="card-body p-0">
      <div class="table-responsive">
        <table class="table table-hover align-middle mb-0">
          <thead class="table-light">
            <tr>
              <th>Nome</th>
              <th>Cliente</th>
              <th>URL</th>
              <th>Método</th>
              <th>Auth</th>
              <th>Última sync</th>
              <th>Próxima sync</th>
              <th>Status</th>
              <th class="text-end">Ações</th>
            </tr>
          </thead>
          <tbody>
            {% for row in rows %}
            <tr>
              <td><strong>{{ row.intg.name }}</strong></td>
              <td>{{ row.client_name }}</td>
              <td class="text-truncate" style="max-width:180px" title="{{ row.intg.url }}">{{ row.intg.url }}</td>
              <td><span class="badge bg-secondary">{{ row.intg.method }}</span></td>
              <td>
                {% if row.intg.auth_type == 'api_key_header' %}API Key
                {% elif row.intg.auth_type == 'basic_auth' %}Basic Auth
                {% else %}Nenhuma{% endif %}
              </td>
              <td>{{ row.last_snap.synced_at[:16].replace('T',' ') if row.last_snap else '—' }}</td>
              <td>
                {% if row.intg.sync_interval_hours == 0 %}
                  <span class="text-muted">Manual</span>
                {% elif row.next_sync %}
                  {{ row.next_sync }}
                {% else %}—{% endif %}
              </td>
              <td>
                {% if row.last_snap %}
                  {% if row.last_snap.status == 'ok' %}
                    <span class="badge bg-success">OK</span>
                  {% else %}
                    <span class="badge bg-danger" title="{{ row.last_snap.error_msg or '' }}">Erro</span>
                  {% endif %}
                {% else %}
                  <span class="badge bg-light text-dark border">—</span>
                {% endif %}
              </td>
              <td class="text-end">
                <div class="btn-group btn-group-sm">
                  <form method="post" action="/integrations/api-connector/{{ row.intg.id }}/sync" class="d-inline">
                    <button class="btn btn-outline-primary" title="Sincronizar agora">
                      <i class="bi bi-arrow-repeat"></i>
                    </button>
                  </form>
                  <a href="/integrations/api-connector/{{ row.intg.id }}/editar" class="btn btn-outline-secondary" title="Editar">
                    <i class="bi bi-pencil"></i>
                  </a>
                  <form method="post" action="/integrations/api-connector/{{ row.intg.id }}/excluir"
                        onsubmit="return confirm('Excluir esta integração?')" class="d-inline">
                    <button class="btn btn-outline-danger" title="Excluir">
                      <i class="bi bi-trash"></i>
                    </button>
                  </form>
                </div>
              </td>
            </tr>
            {% else %}
            <tr>
              <td colspan="9" class="text-center text-muted py-5">
                Nenhuma integração cadastrada. <a href="/integrations/api-connector/novo">Criar agora</a>.
              </td>
            </tr>
            {% endfor %}
          </tbody>
        </table>
      </div>
    </div>
  </div>
</div>
{% endblock %}
"""  # type: ignore[name-defined]

TEMPLATES["api_connector_form.html"] = r"""
{% extends "base.html" %}
{% block content %}
<div class="container py-4" style="max-width:720px">
  <div class="d-flex align-items-center mb-4 gap-3">
    <a href="/integrations/api-connector" class="btn btn-sm btn-outline-secondary">
      <i class="bi bi-arrow-left"></i>
    </a>
    <h2 class="mb-0">{{ 'Editar' if intg else 'Nova' }} integração de API</h2>
  </div>

  {% if flash %}
  <div class="alert alert-danger alert-dismissible fade show">
    {{ flash }}<button type="button" class="btn-close" data-bs-dismiss="alert"></button>
  </div>
  {% endif %}

  <form method="post" class="card shadow-sm p-4">
    <div class="mb-3">
      <label class="form-label fw-semibold">Nome <span class="text-danger">*</span></label>
      <input type="text" name="name" class="form-control" required
             value="{{ intg.name if intg else '' }}" placeholder="ex: ERP Omie – Contas a Receber">
    </div>

    <div class="mb-3">
      <label class="form-label fw-semibold">Cliente</label>
      <select name="client_id" class="form-select">
        <option value="">Empresa toda</option>
        {% for c in clients %}
          <option value="{{ c.id }}"
            {% if intg and intg.client_id == c.id %}selected
            {% elif not intg and preselect_client_id and preselect_client_id == c.id %}selected
            {% endif %}>{{ c.name }}</option>
        {% endfor %}
      </select>
      {% if current_client and not intg %}
      <div class="form-text"><i class="bi bi-info-circle me-1"></i>Pré-selecionado: <strong>{{ current_client.name }}</strong> (cliente ativo)</div>
      {% endif %}
    </div>

    <div class="mb-3">
      <label class="form-label fw-semibold">URL <span class="text-danger">*</span></label>
      <input type="url" name="url" class="form-control" required
             value="{{ intg.url if intg else '' }}" placeholder="https://api.exemplo.com/endpoint">
    </div>

    <div class="row g-3 mb-3">
      <div class="col-md-4">
        <label class="form-label fw-semibold">Método</label>
        <select name="method" id="ai_method" class="form-select">
          <option value="GET"  {% if not intg or intg.method == 'GET'  %}selected{% endif %}>GET</option>
          <option value="POST" {% if intg and intg.method == 'POST' %}selected{% endif %}>POST</option>
        </select>
      </div>
      <div class="col-md-8">
        <label class="form-label fw-semibold">Tipo de autenticação</label>
        <select name="auth_type" id="ai_auth_type" class="form-select">
          <option value="api_key_header" {% if not intg or intg.auth_type == 'api_key_header' %}selected{% endif %}>API Key (Header)</option>
          <option value="basic_auth"     {% if intg and intg.auth_type == 'basic_auth'     %}selected{% endif %}>Basic Auth</option>
          <option value="none"           {% if intg and intg.auth_type == 'none'           %}selected{% endif %}>Nenhuma</option>
        </select>
      </div>
    </div>

    <div id="ai_auth_fields" class="row g-3 mb-3">
      <div class="col-md-6">
        <label class="form-label fw-semibold" id="ai_auth_key_label">Nome do Header</label>
        <input type="text" name="auth_key" id="ai_auth_key" class="form-control"
               value="{{ intg.auth_key if intg else '' }}" placeholder="X-Api-Key">
      </div>
      <div class="col-md-6">
        <label class="form-label fw-semibold" id="ai_auth_val_label">Valor / Senha</label>
        <input type="password" name="auth_value" class="form-control"
               value="{{ intg.auth_value if intg else '' }}" autocomplete="new-password">
      </div>
    </div>

    <div id="ai_body_field" class="mb-3" style="display:none">
      <label class="form-label fw-semibold">Body JSON (POST)</label>
      <textarea name="body_json" class="form-control font-monospace" rows="5"
                placeholder='{"key": "value"}'>{{ intg.body_json if intg else '' }}</textarea>
    </div>

    <div class="mb-3">
      <label class="form-label fw-semibold">Headers adicionais <span class="text-muted fw-normal">(opcional)</span></label>
      <textarea name="extra_headers_json" class="form-control font-monospace" rows="3"
                placeholder='{"Content-Type": "application/json"}'>{{ intg.extra_headers_json if intg else '' }}</textarea>
      <div class="form-text">JSON com headers extras enviados em toda requisição. Ex: <code>{"Content-Type": "application/json"}</code></div>
    </div>

    <div class="mb-3">
      <label class="form-label fw-semibold">Label no Augur</label>
      <input type="text" name="data_label" class="form-control"
             value="{{ intg.data_label if intg else '' }}"
             placeholder="ex: Contas a Receber (opcional)">
      <div class="form-text">Rótulo exibido ao Augur como contexto do cliente.</div>
    </div>

    <div class="mb-4">
      <label class="form-label fw-semibold">Intervalo de sincronização automática</label>
      <select name="sync_interval_hours" class="form-select">
        <option value="0"  {% if intg and intg.sync_interval_hours == 0  %}selected{% endif %}>Manual (desativado)</option>
        <option value="1"  {% if intg and intg.sync_interval_hours == 1  %}selected{% endif %}>A cada 1 hora</option>
        <option value="6"  {% if intg and intg.sync_interval_hours == 6  %}selected{% endif %}>A cada 6 horas</option>
        <option value="12" {% if intg and intg.sync_interval_hours == 12 %}selected{% endif %}>A cada 12 horas</option>
        <option value="24" {% if not intg or intg.sync_interval_hours == 24 %}selected{% endif %}>A cada 24 horas</option>
        <option value="48" {% if intg and intg.sync_interval_hours == 48 %}selected{% endif %}>A cada 48 horas</option>
      </select>
    </div>

    <div class="d-flex gap-2">
      <button type="submit" class="btn btn-primary">
        <i class="bi bi-check-lg me-1"></i>Salvar
      </button>
      <a href="/integrations/api-connector" class="btn btn-outline-secondary">Cancelar</a>
    </div>
  </form>
</div>

<script>
(function(){
  var method   = document.getElementById('ai_method');
  var authType = document.getElementById('ai_auth_type');
  var authFlds = document.getElementById('ai_auth_fields');
  var bodyFld  = document.getElementById('ai_body_field');
  var keyLabel = document.getElementById('ai_auth_key_label');
  var valLabel = document.getElementById('ai_auth_val_label');
  function update(){
    var m = method.value, a = authType.value;
    bodyFld.style.display  = m === 'POST' ? '' : 'none';
    authFlds.style.display = a === 'none'  ? 'none' : '';
    keyLabel.textContent   = a === 'basic_auth' ? 'Usuário'         : 'Nome do Header';
    valLabel.textContent   = a === 'basic_auth' ? 'Senha'           : 'Valor da chave';
  }
  method.addEventListener('change', update);
  authType.addEventListener('change', update);
  update();
})();
</script>
{% endblock %}
"""  # type: ignore[name-defined]


# ── Routes ────────────────────────────────────────────────────────────────────

def _ai_sess_dep():
    return _Dep_ai(get_session)  # type: ignore[name-defined]


@app.get("/integrations/api-connector")  # type: ignore[name-defined]
@require_login  # type: ignore[name-defined]
async def _ai_list(request: Request, session: _Ses_ai = _ai_sess_dep()):  # type: ignore[name-defined]
    ctx = get_tenant_context(request, session)  # type: ignore[name-defined]
    if not ctx:
        return RedirectResponse("/login", status_code=303)  # type: ignore[name-defined]
    if ctx.membership.role not in ("admin",):
        return render("error.html", request=request,  # type: ignore[name-defined]
                      context={"current_user": ctx.user, "current_company": ctx.company,
                               "current_client": None, "message": "Acesso restrito a administradores."},
                      status_code=403)
    flash = request.session.pop("flash", None)

    # Filtra pelo cliente ativo selecionado no navbar
    active_client_id = get_active_client_id(request, session, ctx)  # type: ignore[name-defined]
    cc = get_client_or_none(session, ctx.company.id, active_client_id)  # type: ignore[name-defined]

    from sqlmodel import or_ as _or_ai
    q = _sel_ai(ApiIntegration).where(
        ApiIntegration.company_id == ctx.company.id,
        ApiIntegration.is_active == True,
    )
    if active_client_id:
        # Mostra integrações do cliente específico OU as de "Empresa toda" (client_id=None)
        q = q.where(_or_ai(
            ApiIntegration.client_id == active_client_id,
            ApiIntegration.client_id == None,
        ))
    integrations = session.exec(q.order_by(ApiIntegration.id)).all()

    clients_map = {c.id: c.name for c in _ai_build_clients(session, ctx.company.id)}
    rows = []
    for intg in integrations:
        client_name = clients_map.get(intg.client_id, "Empresa toda") if intg.client_id else "Empresa toda"
        last_snap = _ai_last_snapshot(session, intg.id)
        next_sync = None
        if last_snap and intg.sync_interval_hours > 0:
            try:
                synced = datetime.fromisoformat(last_snap.synced_at.replace("Z", "+00:00"))
                nxt = synced + timedelta(hours=intg.sync_interval_hours)
                next_sync = nxt.strftime("%d/%m %H:%M")
            except Exception:
                pass
        rows.append({"intg": intg, "client_name": client_name, "last_snap": last_snap, "next_sync": next_sync})
    return render("api_connector_list.html", request=request,  # type: ignore[name-defined]
                  context={"current_user": ctx.user, "current_company": ctx.company,
                           "current_client": cc, "rows": rows, "flash": flash,
                           "active_client_id": active_client_id})


@app.get("/integrations/api-connector/novo")  # type: ignore[name-defined]
@require_login  # type: ignore[name-defined]
async def _ai_novo_get(request: Request, session: _Ses_ai = _ai_sess_dep()):  # type: ignore[name-defined]
    ctx = get_tenant_context(request, session)  # type: ignore[name-defined]
    if not ctx or ctx.membership.role not in ("admin",):
        return RedirectResponse("/login", status_code=303)  # type: ignore[name-defined]
    flash = request.session.pop("flash", None)
    clients = _ai_build_clients(session, ctx.company.id)
    active_client_id = get_active_client_id(request, session, ctx)  # type: ignore[name-defined]
    cc = get_client_or_none(session, ctx.company.id, active_client_id)  # type: ignore[name-defined]
    return render("api_connector_form.html", request=request,  # type: ignore[name-defined]
                  context={"current_user": ctx.user, "current_company": ctx.company,
                           "current_client": cc, "intg": None, "clients": clients,
                           "flash": flash, "preselect_client_id": active_client_id})


@app.post("/integrations/api-connector/novo")  # type: ignore[name-defined]
@require_login  # type: ignore[name-defined]
async def _ai_novo_post(
    request: Request,  # type: ignore[name-defined]
    session: _Ses_ai = _ai_sess_dep(),
    name:                 str = _Form_ai(...),
    url:                  str = _Form_ai(...),
    method:               str = _Form_ai("GET"),
    auth_type:            str = _Form_ai("api_key_header"),
    auth_key:             str = _Form_ai(""),
    auth_value:           str = _Form_ai(""),
    body_json:            str = _Form_ai(""),
    extra_headers_json:   str = _Form_ai(""),
    data_label:           str = _Form_ai(""),
    sync_interval_hours:  int = _Form_ai(24),
    client_id:            str = _Form_ai(""),
):
    ctx = get_tenant_context(request, session)  # type: ignore[name-defined]
    if not ctx or ctx.membership.role not in ("admin",):
        return RedirectResponse("/login", status_code=303)  # type: ignore[name-defined]
    try:
        intg = ApiIntegration(
            company_id=ctx.company.id,
            client_id=int(client_id) if client_id.strip() else None,
            name=name.strip(),
            url=url.strip(),
            method=method.upper(),
            auth_type=auth_type,
            auth_key=auth_key.strip() or None,
            auth_value=auth_value or None,
            body_json=body_json.strip() or None,
            extra_headers_json=extra_headers_json.strip() or None,
            data_label=data_label.strip() or None,
            sync_interval_hours=sync_interval_hours,
            is_active=True,
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        session.add(intg)
        session.commit()
        set_flash(request, "Integração criada com sucesso.")  # type: ignore[name-defined]
    except Exception as e:
        set_flash(request, f"Erro ao salvar: {e}")  # type: ignore[name-defined]
    return RedirectResponse("/integrations/api-connector", status_code=303)  # type: ignore[name-defined]


@app.get("/integrations/api-connector/{intg_id}/editar")  # type: ignore[name-defined]
@require_login  # type: ignore[name-defined]
async def _ai_editar_get(request: Request, intg_id: int, session: _Ses_ai = _ai_sess_dep()):  # type: ignore[name-defined]
    ctx = get_tenant_context(request, session)  # type: ignore[name-defined]
    if not ctx or ctx.membership.role not in ("admin",):
        return RedirectResponse("/login", status_code=303)  # type: ignore[name-defined]
    intg = session.get(ApiIntegration, intg_id)
    if not intg or intg.company_id != ctx.company.id:
        set_flash(request, "Integração não encontrada.")  # type: ignore[name-defined]
        return RedirectResponse("/integrations/api-connector", status_code=303)  # type: ignore[name-defined]
    flash = request.session.pop("flash", None)
    clients = _ai_build_clients(session, ctx.company.id)
    return render("api_connector_form.html", request=request,  # type: ignore[name-defined]
                  context={"current_user": ctx.user, "current_company": ctx.company,
                           "current_client": None, "intg": intg, "clients": clients, "flash": flash})


@app.post("/integrations/api-connector/{intg_id}/editar")  # type: ignore[name-defined]
@require_login  # type: ignore[name-defined]
async def _ai_editar_post(
    request: Request,  # type: ignore[name-defined]
    intg_id: int,
    session: _Ses_ai = _ai_sess_dep(),
    name:                str = _Form_ai(...),
    url:                 str = _Form_ai(...),
    method:              str = _Form_ai("GET"),
    auth_type:           str = _Form_ai("api_key_header"),
    auth_key:            str = _Form_ai(""),
    auth_value:          str = _Form_ai(""),
    body_json:           str = _Form_ai(""),
    extra_headers_json:  str = _Form_ai(""),
    data_label:          str = _Form_ai(""),
    sync_interval_hours: int = _Form_ai(24),
    client_id:           str = _Form_ai(""),
):
    ctx = get_tenant_context(request, session)  # type: ignore[name-defined]
    if not ctx or ctx.membership.role not in ("admin",):
        return RedirectResponse("/login", status_code=303)  # type: ignore[name-defined]
    intg = session.get(ApiIntegration, intg_id)
    if not intg or intg.company_id != ctx.company.id:
        set_flash(request, "Integração não encontrada.")  # type: ignore[name-defined]
        return RedirectResponse("/integrations/api-connector", status_code=303)  # type: ignore[name-defined]
    try:
        intg.name = name.strip()
        intg.url = url.strip()
        intg.method = method.upper()
        intg.auth_type = auth_type
        intg.auth_key = auth_key.strip() or None
        if auth_value:
            intg.auth_value = auth_value
        intg.body_json = body_json.strip() or None
        intg.extra_headers_json = extra_headers_json.strip() or None
        intg.data_label = data_label.strip() or None
        intg.sync_interval_hours = sync_interval_hours
        intg.client_id = int(client_id) if client_id.strip() else None
        session.add(intg)
        session.commit()
        set_flash(request, "Integração atualizada com sucesso.")  # type: ignore[name-defined]
    except Exception as e:
        set_flash(request, f"Erro ao salvar: {e}")  # type: ignore[name-defined]
    return RedirectResponse("/integrations/api-connector", status_code=303)  # type: ignore[name-defined]


@app.post("/integrations/api-connector/{intg_id}/sync")  # type: ignore[name-defined]
@require_login  # type: ignore[name-defined]
async def _ai_sync(request: Request, intg_id: int, session: _Ses_ai = _ai_sess_dep()):  # type: ignore[name-defined]
    ctx = get_tenant_context(request, session)  # type: ignore[name-defined]
    if not ctx or ctx.membership.role not in ("admin", "equipe"):
        return RedirectResponse("/login", status_code=303)  # type: ignore[name-defined]
    intg = session.get(ApiIntegration, intg_id)
    if not intg or intg.company_id != ctx.company.id:
        set_flash(request, "Integração não encontrada.")  # type: ignore[name-defined]
        return RedirectResponse("/integrations/api-connector", status_code=303)  # type: ignore[name-defined]
    try:
        snap = _ai_sync_integration(session, intg)
        if snap.status == "ok":
            set_flash(request, "Sincronizado com sucesso.")  # type: ignore[name-defined]
        else:
            set_flash(request, f"Erro na sincronização: {snap.error_msg}")  # type: ignore[name-defined]
    except Exception as e:
        set_flash(request, f"Erro inesperado: {e}")  # type: ignore[name-defined]
    return RedirectResponse("/integrations/api-connector", status_code=303)  # type: ignore[name-defined]


@app.post("/integrations/api-connector/{intg_id}/excluir")  # type: ignore[name-defined]
@require_login  # type: ignore[name-defined]
async def _ai_excluir(request: Request, intg_id: int, session: _Ses_ai = _ai_sess_dep()):  # type: ignore[name-defined]
    ctx = get_tenant_context(request, session)  # type: ignore[name-defined]
    if not ctx or ctx.membership.role not in ("admin",):
        return RedirectResponse("/login", status_code=303)  # type: ignore[name-defined]
    intg = session.get(ApiIntegration, intg_id)
    if not intg or intg.company_id != ctx.company.id:
        set_flash(request, "Integração não encontrada.")  # type: ignore[name-defined]
        return RedirectResponse("/integrations/api-connector", status_code=303)  # type: ignore[name-defined]
    try:
        intg.is_active = False
        session.add(intg)
        session.commit()
        set_flash(request, "Integração removida.")  # type: ignore[name-defined]
    except Exception as e:
        set_flash(request, f"Erro: {e}")  # type: ignore[name-defined]
    return RedirectResponse("/integrations/api-connector", status_code=303)  # type: ignore[name-defined]


# ── Augur enrichment chain ────────────────────────────────────────────────────

_prev_enr_api = _enriquecer_client_data  # type: ignore[name-defined]


def _enriquecer_com_api_data(session, company_id, client_id, client, client_data):
    data = _prev_enr_api(session, company_id, client_id, client, client_data)
    try:
        integrations = session.exec(
            _sel_ai(ApiIntegration).where(
                ApiIntegration.company_id == company_id,
                ApiIntegration.is_active == True,
            ).where(
                (ApiIntegration.client_id == client_id) | (ApiIntegration.client_id == None)
            )
        ).all()
        snippets = []
        for intg in integrations:
            snap = session.exec(
                _sel_ai(ApiIntegrationSnapshot).where(
                    ApiIntegrationSnapshot.integration_id == intg.id,
                    ApiIntegrationSnapshot.status == "ok",
                ).order_by(ApiIntegrationSnapshot.id.desc())
            ).first()
            if snap:
                label = intg.data_label or intg.name
                snippets.append(f"[{label} — {snap.synced_at[:10]}]\n{snap.data_json[:2000]}")
        if snippets:
            data["api_integrations"] = "\n\n".join(snippets)
    except Exception as e:
        print(f"[api_integrador] enrich error: {e}")
    return data


_enriquecer_client_data = _enriquecer_com_api_data  # type: ignore[name-defined]

# ── Re-registra /integrations com card de Conectores de API ──────────────────
try:
    from fastapi import Request as _Req_ai2
    from fastapi.responses import HTMLResponse as _HTML_ai2

    app.routes[:] = [r for r in app.routes  # type: ignore[name-defined]
                     if not (hasattr(r, "path") and r.path == "/integrations"
                             and hasattr(r, "methods") and "GET" in (r.methods or set()))]

    _AI_EXTRA_CARD = r"""
  <hr class="my-4">
  <h6 class="mb-3 text-muted small text-uppercase fw-semibold">Conectores de API</h6>
  <a href="/integrations/api-connector" class="drive-btn">
    <span style="font-size:2rem;line-height:1;flex-shrink:0;">🔌</span>
    <div>
      <div class="fw-semibold">Conectores de API Genéricos</div>
      <div class="text-muted small">Integre qualquer ERP ou sistema via REST API</div>
    </div>
    <i class="bi bi-chevron-right ms-auto text-muted"></i>
  </a>
"""

    @app.get("/integrations", response_class=_HTML_ai2)  # type: ignore[name-defined]
    @require_login  # type: ignore[name-defined]
    async def integrations_page_patched(request: _Req_ai2, session=_Dep_ai(get_session)):  # type: ignore[name-defined]
        ctx = get_tenant_context(request, session)  # type: ignore[name-defined]
        if not ctx:
            from fastapi.responses import RedirectResponse as _RR2
            return _RR2("/login", status_code=303)

        flash = request.session.pop("flash", None)
        role = ctx.membership.role if ctx.membership else "cliente"

        q = _sel_ai(CloudStorageConnection).where(  # type: ignore[name-defined]
            CloudStorageConnection.company_id == ctx.company.id,  # type: ignore[name-defined]
            CloudStorageConnection.is_active == True,
        )
        if role == "cliente":
            q = q.where(CloudStorageConnection.created_by_user_id == ctx.user.id)  # type: ignore[name-defined]
        conns = session.exec(q).all()
        sel_counts = {c.id: len(_cs_parse_selections(c)) for c in conns}  # type: ignore[name-defined]

        from jinja2 import Environment as _JEnv2
        page = _CS_PAGE  # type: ignore[name-defined]
        if "api-connector" not in page:
            page = page.replace("{% if conns %}", _AI_EXTRA_CARD + "\n  {% if conns %}", 1)

        env2 = _JEnv2()
        html = env2.from_string(page).render(
            flash=flash, conns=conns, sel_counts=sel_counts,
            gdrive_ok=bool(_GDRIVE_CLIENT_ID),  # type: ignore[name-defined]
            onedrive_ok=bool(_ONEDRIVE_CLIENT_ID),  # type: ignore[name-defined]
        )
        return _HTML_ai2(html)

    print("[api_integrador] ✅ /integrations re-registrada com card Conectores de API.")
except Exception as _e_cs_patch:
    print(f"[api_integrador] ⚠️ patch /integrations: {_e_cs_patch}")

print("[api_integrador] ✅ Integrador de APIs carregado.")

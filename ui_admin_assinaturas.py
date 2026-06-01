# ui_admin_assinaturas.py — Painel admin de assinaturas
# Exec'd no namespace do app.py
#
# Rota: GET  /admin/assinaturas        — painel consolidado
#       POST /admin/assinaturas/{id}/ativar   — ativa plano manualmente
#       POST /admin/assinaturas/{id}/bloquear — bloqueia plano

from datetime import datetime as _dt_as, timezone as _tz_as, timedelta as _td_as
from sqlmodel import select as _sel_as, Session as _Ses_as
import json as _json_as

# ── HTML do painel ────────────────────────────────────────────────────────────

_ASSIN_HTML = r"""
<!doctype html><html lang="pt-br"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Assinaturas — Admin</title>
<link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css" rel="stylesheet">
<style>
body{background:#f6f7fb;font-family:system-ui,sans-serif;}
.card{border:0;box-shadow:0 4px 16px rgba(0,0,0,.07);border-radius:14px;}
.badge{border-radius:999px;}
.btn{border-radius:10px;}
.stat-val{font-size:1.7rem;font-weight:700;line-height:1.1;}
.stat-lbl{font-size:.78rem;color:#6c757d;margin-top:.15rem;}
.tbl-client td{vertical-align:middle;font-size:.88rem;}
.tbl-client th{font-size:.78rem;color:#6c757d;font-weight:600;border-bottom:2px solid #eee;}
.plan-badge{font-size:.75rem;padding:.25rem .6rem;}
</style></head><body>
<nav class="navbar bg-white border-bottom px-4 py-2 d-flex align-items-center gap-3">
  <a href="/" class="text-decoration-none fw-bold" style="color:#0B1E1E;">← App</a>
  <span class="fw-semibold">Assinaturas</span>
  <a href="/admin/monetizacao" class="ms-auto btn btn-sm btn-outline-secondary">Planos & Campanhas</a>
</nav>

<div class="container-fluid py-4 px-4">

  <!-- Stats -->
  <div class="row g-3 mb-4">
    <div class="col-6 col-md-3">
      <div class="card p-3">
        <div class="stat-val text-success">R$ {{ mrr_fmt }}</div>
        <div class="stat-lbl">MRR (recorrência mensal)</div>
      </div>
    </div>
    <div class="col-6 col-md-3">
      <div class="card p-3">
        <div class="stat-val">{{ total_ativos }}</div>
        <div class="stat-lbl">Assinaturas ativas</div>
      </div>
    </div>
    <div class="col-6 col-md-3">
      <div class="card p-3">
        <div class="stat-val text-warning">{{ total_trial }}</div>
        <div class="stat-lbl">Em trial (ferramentas)</div>
      </div>
    </div>
    <div class="col-6 col-md-3">
      <div class="card p-3">
        <div class="stat-val text-danger">{{ total_sem_plano }}</div>
        <div class="stat-lbl">Clientes sem plano</div>
      </div>
    </div>
  </div>

  <!-- Tabela de clientes -->
  <div class="card p-3 mb-4">
    <div class="d-flex align-items-center justify-content-between mb-3">
      <h6 class="mb-0 fw-bold">Clientes e assinaturas</h6>
      <input type="search" id="filterInput" placeholder="Buscar cliente…"
        class="form-control form-control-sm" style="max-width:220px;"
        oninput="filterTable(this.value)">
    </div>
    <div class="table-responsive">
    <table class="table tbl-client mb-0" id="clientTable">
      <thead>
        <tr>
          <th>Cliente</th>
          <th>Plano recorrente</th>
          <th>Preço/mês</th>
          <th>Próx. ciclo</th>
          <th>Stripe Sub</th>
          <th>Ferramentas</th>
          <th>Status</th>
          <th></th>
        </tr>
      </thead>
      <tbody>
      {% for row in rows %}
        <tr data-name="{{ row.client_name | lower }}">
          <td><span class="fw-semibold">{{ row.client_name }}</span></td>
          <td>
            {% if row.plano_nome %}
              <span class="badge bg-primary plan-badge">{{ row.plano_nome }}</span>
            {% else %}
              <span class="text-muted small">—</span>
            {% endif %}
          </td>
          <td>
            {% if row.preco_reais %}
              R$ {{ row.preco_reais }}
            {% else %}—{% endif %}
          </td>
          <td class="text-muted">{{ row.proximo_ciclo or '—' }}</td>
          <td>
            {% if row.stripe_sub_id %}
              <code style="font-size:.72rem;">{{ row.stripe_sub_id[:20] }}…</code>
            {% else %}<span class="text-muted small">—</span>{% endif %}
          </td>
          <td>
            {% for t in row.tools %}
              <span class="badge {% if t.status == 'active' %}bg-success{% elif t.status == 'trial' %}bg-warning text-dark{% else %}bg-secondary{% endif %} plan-badge me-1">
                {{ t.tool_code }}: {{ t.status }}
              </span>
            {% endfor %}
            {% if not row.tools %}<span class="text-muted small">—</span>{% endif %}
          </td>
          <td>
            {% if row.plano_ativo %}
              <span class="badge bg-success">✅ Ativo</span>
            {% elif row.plano_nome %}
              <span class="badge bg-danger">🔴 Bloqueado</span>
            {% else %}
              <span class="badge bg-light text-muted border">Sem plano</span>
            {% endif %}
          </td>
          <td class="text-end">
            {% if row.plano_ativo %}
              <form method="post" action="/admin/assinaturas/{{ row.client_id }}/bloquear"
                    onsubmit="return confirm('Bloquear {{ row.client_name }}?')" class="d-inline">
                <button class="btn btn-sm btn-outline-danger">Bloquear</button>
              </form>
            {% else %}
              <button class="btn btn-sm btn-outline-success" data-bs-toggle="modal"
                data-bs-target="#modalAtivar" data-client-id="{{ row.client_id }}"
                data-client-name="{{ row.client_name }}">Ativar</button>
            {% endif %}
          </td>
        </tr>
      {% endfor %}
      </tbody>
    </table>
    </div>
  </div>

</div>

<!-- Modal ativar plano manualmente -->
<div class="modal fade" id="modalAtivar" tabindex="-1">
  <div class="modal-dialog modal-sm">
    <div class="modal-content">
      <div class="modal-header">
        <h6 class="modal-title">Ativar plano manualmente</h6>
        <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
      </div>
      <form method="post" id="formAtivar">
        <div class="modal-body">
          <p class="small mb-2">Cliente: <strong id="modalClientName"></strong></p>
          <label class="form-label small">Plano</label>
          <select name="plano_id" class="form-select form-select-sm mb-2" required>
            {% for p in planos %}
              <option value="{{ p.id }}">{{ p.nome }} — R$ {{ "%.0f"|format(p.preco_cents/100) }}/mês</option>
            {% endfor %}
          </select>
          <label class="form-label small">Próximo ciclo</label>
          <input type="date" name="proximo_ciclo" class="form-control form-control-sm"
                 value="{{ hoje_plus30 }}" required>
          <label class="form-label small mt-2">Stripe Sub ID (opcional)</label>
          <input type="text" name="stripe_sub_id" class="form-control form-control-sm"
                 placeholder="sub_xxx (deixe vazio se manual)">
        </div>
        <div class="modal-footer">
          <button type="button" class="btn btn-sm btn-outline-secondary" data-bs-dismiss="modal">Cancelar</button>
          <button type="submit" class="btn btn-sm btn-success">Ativar</button>
        </div>
      </form>
    </div>
  </div>
</div>

<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/js/bootstrap.bundle.min.js"></script>
<script>
const modalAtivar = document.getElementById('modalAtivar');
modalAtivar.addEventListener('show.bs.modal', function(e) {
  const btn = e.relatedTarget;
  document.getElementById('modalClientName').textContent = btn.dataset.clientName;
  document.getElementById('formAtivar').action = '/admin/assinaturas/' + btn.dataset.clientId + '/ativar';
});

function filterTable(q) {
  q = q.toLowerCase();
  document.querySelectorAll('#clientTable tbody tr').forEach(tr => {
    tr.style.display = tr.dataset.name.includes(q) ? '' : 'none';
  });
}
</script>
</body></html>
"""


# ── Rota GET /admin/assinaturas ───────────────────────────────────────────────

@app.get("/admin/assinaturas", response_class=HTMLResponse)
@require_login
async def admin_assinaturas_get(request: Request, session: Session = Depends(get_session)):
    ctx = get_tenant_context(request, session)
    if not ctx or ctx.membership.role not in ("admin", "owner"):
        return RedirectResponse("/", status_code=303)

    company_id = ctx.company.id

    # Todos os clientes da empresa
    clientes = session.exec(
        select(Client).where(Client.company_id == company_id).order_by(Client.name)
    ).all()

    # Planos disponíveis
    planos = session.exec(
        select(PlanoCredito)
        .where(PlanoCredito.company_id == company_id, PlanoCredito.ativo == True)
        .order_by(PlanoCredito.preco_cents)
    ).all()
    planos_map = {p.id: p for p in planos}

    # Assinaturas ativas (ClientePlano)
    assinaturas = session.exec(
        select(ClientePlano).where(ClientePlano.company_id == company_id)
    ).all()
    assin_map = {a.client_id: a for a in assinaturas}  # última por cliente

    # Tool subscriptions
    tool_subs = session.exec(
        select(ClientToolSubscription)
        .where(ClientToolSubscription.company_id == company_id)
    ).all()
    tools_map: dict = {}
    for t in tool_subs:
        tools_map.setdefault(t.client_id, []).append(t)

    # Monta linhas
    rows = []
    mrr_cents = 0
    total_ativos = 0
    total_trial = 0
    total_sem_plano = 0

    for c in clientes:
        assin = assin_map.get(c.id)
        plano = planos_map.get(assin.plano_id) if assin else None
        tools = tools_map.get(c.id, [])

        plano_ativo = bool(assin and assin.ativo)
        if plano_ativo and plano:
            mrr_cents += plano.preco_cents
            total_ativos += 1
        elif not assin:
            total_sem_plano += 1

        trial_tools = [t for t in tools if t.status == "trial"]
        total_trial += len(trial_tools)

        rows.append({
            "client_id":    c.id,
            "client_name":  c.name,
            "plano_nome":   plano.nome if plano else "",
            "preco_reais":  f"{plano.preco_cents/100:,.0f}".replace(",", ".") if plano else "",
            "proximo_ciclo": assin.proximo_ciclo if assin else "",
            "stripe_sub_id": assin.stripe_sub_id if assin else "",
            "plano_ativo":  plano_ativo,
            "tools":        [{"tool_code": t.tool_code, "status": t.status} for t in tools],
        })

    mrr_fmt = f"{mrr_cents/100:,.0f}".replace(",", ".")
    hoje_plus30 = (_dt_as.now(_tz_as.utc) + _td_as(days=30)).strftime("%Y-%m-%d")

    from jinja2 import Environment as _JE, BaseLoader as _JBL
    _env = _JE(loader=_JBL(), autoescape=True)
    html = _env.from_string(_ASSIN_HTML).render(
        rows=rows,
        planos=planos,
        mrr_fmt=mrr_fmt,
        total_ativos=total_ativos,
        total_trial=total_trial,
        total_sem_plano=total_sem_plano,
        hoje_plus30=hoje_plus30,
    )
    return HTMLResponse(html)


# ── POST /admin/assinaturas/{id}/ativar ──────────────────────────────────────

@app.post("/admin/assinaturas/{client_id}/ativar")
@require_login
async def admin_assinaturas_ativar(
    client_id: int,
    request: Request,
    session: Session = Depends(get_session),
):
    ctx = get_tenant_context(request, session)
    if not ctx or ctx.membership.role not in ("admin", "owner"):
        return RedirectResponse("/admin/assinaturas", status_code=303)

    form = await request.form()
    plano_id      = int(form.get("plano_id", 0) or 0)
    proximo_ciclo = str(form.get("proximo_ciclo", "") or "")
    stripe_sub_id = str(form.get("stripe_sub_id", "") or "").strip()

    # Verifica plano pertence à empresa
    plano = session.get(PlanoCredito, plano_id)
    if not plano or plano.company_id != ctx.company.id:
        return RedirectResponse("/admin/assinaturas", status_code=303)

    # Atualiza ou cria ClientePlano
    existente = session.exec(
        select(ClientePlano)
        .where(ClientePlano.company_id == ctx.company.id,
               ClientePlano.client_id  == client_id)
    ).first()

    if existente:
        existente.plano_id      = plano_id
        existente.ativo         = True
        existente.proximo_ciclo = proximo_ciclo
        if stripe_sub_id:
            existente.stripe_sub_id = stripe_sub_id
        session.add(existente)
    else:
        novo = ClientePlano(
            company_id=ctx.company.id,
            client_id=client_id,
            plano_id=plano_id,
            stripe_sub_id=stripe_sub_id,
            proximo_ciclo=proximo_ciclo,
            ativo=True,
            created_at=str(_dt_as.now(_tz_as.utc))[:19],
        )
        session.add(novo)

    session.commit()
    print(f"[assinaturas] Plano {plano.nome} ativado manualmente para client {client_id}")
    return RedirectResponse("/admin/assinaturas", status_code=303)


# ── POST /admin/assinaturas/{id}/bloquear ────────────────────────────────────

@app.post("/admin/assinaturas/{client_id}/bloquear")
@require_login
async def admin_assinaturas_bloquear(
    client_id: int,
    request: Request,
    session: Session = Depends(get_session),
):
    ctx = get_tenant_context(request, session)
    if not ctx or ctx.membership.role not in ("admin", "owner"):
        return RedirectResponse("/admin/assinaturas", status_code=303)

    assin = session.exec(
        select(ClientePlano)
        .where(ClientePlano.company_id == ctx.company.id,
               ClientePlano.client_id  == client_id)
    ).first()

    if assin:
        assin.ativo = False
        session.add(assin)
        session.commit()
        print(f"[assinaturas] Plano bloqueado manualmente para client {client_id}")

    return RedirectResponse("/admin/assinaturas", status_code=303)


print("[assinaturas] Painel admin de assinaturas carregado → /admin/assinaturas")

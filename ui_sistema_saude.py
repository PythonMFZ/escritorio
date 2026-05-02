# ============================================================================
# PATCH — Sininho Navbar + Pop-up Bônus + Painel de Saúde Admin
# ============================================================================
# Salve como ui_sistema_saude.py e adicione ao final do app.py:
#   exec(open('ui_sistema_saude.py').read())
# ============================================================================

import os as _os_sh
import json as _json_sh
import requests as _req_sh
from datetime import datetime as _dt_sh, timedelta as _td_sh
from typing import Optional as _OptSH
from sqlmodel import Field as _FSH, SQLModel as _SMSH


# ── Modelo: NotificacaoBonus ──────────────────────────────────────────────────

class NotificacaoBonus(_SMSH, table=True):
    __tablename__  = "notificacaobonus"
    __table_args__ = {"extend_existing": True}
    id:          _OptSH[int] = _FSH(default=None, primary_key=True)
    company_id:  int         = _FSH(index=True)
    client_id:   int         = _FSH(index=True)
    creditos:    int         = _FSH(default=0)
    motivo:      str         = _FSH(default="")
    lida:        bool        = _FSH(default=False)
    created_at:  str         = _FSH(default="")

try:
    _SMSH.metadata.create_all(engine, tables=[NotificacaoBonus.__table__])
except Exception:
    pass


# ── Sininho: injeta no navbar ─────────────────────────────────────────────────

_NAVBAR_OLD = '''            <a class="btn btn-outline-secondary btn-sm" href="/logout">Sair</a>
          {% else %}'''

_NAVBAR_NEW = '''            <a class="btn btn-outline-secondary btn-sm" href="/logout">Sair</a>
            {# ── Sininho de alertas ── #}
            {% if smart_alerts_unread_count is defined and smart_alerts_unread_count > 0 %}
            <a href="/#alertas" class="btn btn-outline-secondary btn-sm position-relative" title="Alertas não lidos">
              <i class="bi bi-bell-fill text-warning"></i>
              <span class="position-absolute top-0 start-100 translate-middle badge rounded-pill bg-danger" style="font-size:.6rem;">
                {{ smart_alerts_unread_count }}
              </span>
            </a>
            {% else %}
            <a href="/#alertas" class="btn btn-outline-secondary btn-sm" title="Alertas">
              <i class="bi bi-bell"></i>
            </a>
            {% endif %}
          {% else %}'''

_base = TEMPLATES.get("base.html", "")
if _base and "bi-bell" not in _base:
    if _NAVBAR_OLD in _base:
        _base = _base.replace(_NAVBAR_OLD, _NAVBAR_NEW, 1)
        TEMPLATES["base.html"] = _base
        print("[saude] Sininho adicionado ao navbar")

# Alternativa: injeta direto no app.py via patch do navbar
try:
    _tenv = templates_env
    _base2 = _tenv.get_template("base.html").render if hasattr(_tenv, 'get_template') else None
except Exception:
    pass


# ── Rota GET /api/notificacoes/bonus ─────────────────────────────────────────

@app.get("/api/notificacoes/bonus")
@require_login
async def api_notificacoes_bonus(request: Request, session: Session = Depends(get_session)):
    ctx = get_tenant_context(request, session)
    if not ctx:
        return JSONResponse({"notificacoes": []})

    cc = get_client_or_none(session, ctx.company.id,
                            get_active_client_id(request, session, ctx))
    if not cc:
        return JSONResponse({"notificacoes": []})

    notifs = session.exec(
        select(NotificacaoBonus)
        .where(NotificacaoBonus.company_id == ctx.company.id,
               NotificacaoBonus.client_id  == cc.id,
               NotificacaoBonus.lida == False)
        .order_by(NotificacaoBonus.id.desc())
        .limit(5)
    ).all()

    return JSONResponse({
        "notificacoes": [
            {"id": n.id, "creditos": n.creditos, "motivo": n.motivo,
             "created_at": n.created_at[:10] if n.created_at else ""}
            for n in notifs
        ]
    })


# ── Rota POST /api/notificacoes/bonus/{id}/ler ────────────────────────────────

@app.post("/api/notificacoes/bonus/{notif_id}/ler")
@require_login
async def notificacao_bonus_ler(
    notif_id: int, request: Request, session: Session = Depends(get_session)
):
    ctx = get_tenant_context(request, session)
    if not ctx:
        return JSONResponse({"ok": False})
    n = session.get(NotificacaoBonus, notif_id)
    if n and n.company_id == ctx.company.id:
        n.lida = True
        session.add(n)
        session.commit()
    return JSONResponse({"ok": True})


# ── Patch na rota de créditos bônus para criar notificação ───────────────────

_orig_bonus = None
for _r in app.routes:
    if hasattr(_r, 'path') and _r.path == '/admin/creditos-bonus' and \
       hasattr(_r, 'methods') and 'POST' in (_r.methods or set()):
        break

@app.post("/admin/creditos-bonus-notify")
@require_login
async def creditos_bonus_notify(request: Request, session: Session = Depends(get_session)):
    """Versão de bônus que cria notificação para o cliente."""
    ctx = get_tenant_context(request, session)
    if not ctx or ctx.membership.role not in ("admin", "equipe"):
        return JSONResponse({"ok": False}, status_code=403)

    body = await request.json()
    client_id = int(body.get("client_id", 0) or 0)
    creditos  = int(body.get("amount", 0) or 0)
    motivo    = body.get("motivo", "Bônus")

    if creditos <= 0:
        return JSONResponse({"ok": False, "erro": "Valor inválido."})

    client = get_client_or_none(session, ctx.company.id, client_id)
    if not client:
        return JSONResponse({"ok": False, "erro": "Cliente não encontrado."})

    cents = creditos * 100
    try:
        w = session.exec(
            select(CreditWallet)
            .where(CreditWallet.company_id == ctx.company.id,
                   CreditWallet.client_id  == client_id)
        ).first()
        if not w:
            w = CreditWallet(company_id=ctx.company.id, client_id=client_id,
                             balance_cents=0, updated_at=utcnow())
            session.add(w); session.commit(); session.refresh(w)

        w.balance_cents += cents
        w.updated_at = utcnow()
        session.add(w)
        session.add(CreditLedger(
            company_id=ctx.company.id, client_id=client_id,
            kind="ADJUSTMENT", amount_cents=cents,
            ref_type="bonus", ref_id="",
            note=f"Bônus: {motivo}",
        ))
        # Cria notificação
        session.add(NotificacaoBonus(
            company_id=ctx.company.id, client_id=client_id,
            creditos=creditos, motivo=motivo, lida=False,
            created_at=str(_dt_sh.utcnow()),
        ))
        session.commit()
        return JSONResponse({"ok": True, "novo_saldo": w.balance_cents / 100})
    except Exception as e:
        return JSONResponse({"ok": False, "erro": str(e)})


# ── Pop-up bônus: script injetado no dashboard ────────────────────────────────

_BONUS_POPUP_SCRIPT = r"""
<script>
// Pop-up de bônus
(function() {
  fetch('/api/notificacoes/bonus')
    .then(r => r.json())
    .then(d => {
      const notifs = d.notificacoes || [];
      if (!notifs.length) return;

      // Cria modal
      const total = notifs.reduce((s, n) => s + n.creditos, 0);
      const motivos = notifs.map(n => n.motivo).filter(Boolean).join(', ');
      const ids = notifs.map(n => n.id);

      const modal = document.createElement('div');
      modal.innerHTML = `
        <div class="modal fade" id="bonusModal" tabindex="-1">
          <div class="modal-dialog modal-dialog-centered">
            <div class="modal-content border-0 shadow-lg" style="border-radius:18px;overflow:hidden;">
              <div class="modal-header border-0 pb-0" style="background:linear-gradient(135deg,#E07020,#f59540);color:#fff;">
                <div class="w-100 text-center pt-2">
                  <div style="font-size:2.5rem;">🎁</div>
                  <h5 class="fw-bold mb-0">Você recebeu um bônus!</h5>
                </div>
              </div>
              <div class="modal-body text-center py-4">
                <div style="font-size:2.5rem;font-weight:800;color:#E07020;">${total} créditos</div>
                <div class="text-muted mt-1">foram adicionados à sua carteira</div>
                ${motivos ? `<div class="badge text-bg-light border mt-2" style="font-size:.85rem;">${motivos}</div>` : ''}
                <div class="mt-3" style="font-size:.85rem;color:#6b7280;">
                  Use seus créditos para acessar consultas de crédito, análises de risco e muito mais.
                </div>
              </div>
              <div class="modal-footer border-0 justify-content-center pb-4">
                <button type="button" class="btn btn-primary px-4" data-bs-dismiss="modal"
                        onclick="marcarBonusLido(${JSON.stringify(ids)})">
                  Entendido! 🚀
                </button>
              </div>
            </div>
          </div>
        </div>`;
      document.body.appendChild(modal);

      const bsModal = new bootstrap.Modal(document.getElementById('bonusModal'));
      bsModal.show();
    })
    .catch(() => {});
})();

async function marcarBonusLido(ids) {
  for (const id of ids) {
    await fetch('/api/notificacoes/bonus/' + id + '/ler', {method: 'POST'})
      .catch(() => {});
  }
}
</script>
"""

_dash = TEMPLATES.get("dashboard.html", "")
if _dash and "bonusModal" not in _dash:
    if "{% endblock %}" in _dash:
        _dash = _dash.replace("{% endblock %}", _BONUS_POPUP_SCRIPT + "\n{% endblock %}", 1)
        TEMPLATES["dashboard.html"] = _dash
        print("[saude] Pop-up bônus adicionado ao dashboard")


# ── Painel de Saúde Admin ─────────────────────────────────────────────────────

def _check_anthropic() -> dict:
    """Verifica se a API da Anthropic está respondendo."""
    try:
        api_key = _os_sh.environ.get("ANTHROPIC_API_KEY", "")
        if not api_key:
            return {"ok": False, "status": "Sem API key", "latency_ms": 0}
        t0 = _dt_sh.utcnow()
        r = _req_sh.post(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": api_key, "anthropic-version": "2023-06-01",
                     "content-type": "application/json"},
            json={"model": "claude-haiku-4-5-20251001", "max_tokens": 10,
                  "messages": [{"role": "user", "content": "ok"}]},
            timeout=10,
        )
        ms = int((_dt_sh.utcnow() - t0).total_seconds() * 1000)
        return {"ok": r.status_code == 200, "status": "Operacional" if r.status_code == 200 else f"HTTP {r.status_code}", "latency_ms": ms}
    except Exception as e:
        return {"ok": False, "status": str(e)[:50], "latency_ms": 0}


def _check_directdata() -> dict:
    """Verifica se a API DirectData está respondendo."""
    try:
        token = _os_sh.environ.get("DIRECTDATA_TOKEN", "")
        if not token:
            return {"ok": False, "status": "Sem token", "latency_ms": 0}
        t0 = _dt_sh.utcnow()
        r = _req_sh.get(
            "https://api.app.directd.com.br/api/Dossier/Templates",
            headers={"Token": token, "Content-Type": "application/json"},
            timeout=10,
        )
        ms = int((_dt_sh.utcnow() - t0).total_seconds() * 1000)
        return {"ok": r.status_code == 200, "status": "Operacional" if r.status_code == 200 else f"HTTP {r.status_code}", "latency_ms": ms}
    except Exception as e:
        return {"ok": False, "status": str(e)[:50], "latency_ms": 0}


def _check_notion() -> dict:
    """Verifica se o Notion está configurado."""
    try:
        token = _os_sh.environ.get("NOTION_TOKEN", "")
        db_id = _os_sh.environ.get("NOTION_MEETINGS_DB_ID", "")
        if not token or not db_id:
            return {"ok": False, "status": "Não configurado", "latency_ms": 0}
        t0 = _dt_sh.utcnow()
        r = _req_sh.post(
            f"https://api.notion.com/v1/databases/{db_id}/query",
            headers={"Authorization": f"Bearer {token}", "Notion-Version": "2022-06-28",
                     "Content-Type": "application/json"},
            json={"page_size": 1},
            timeout=10,
        )
        ms = int((_dt_sh.utcnow() - t0).total_seconds() * 1000)
        return {"ok": r.status_code == 200, "status": "Operacional" if r.status_code == 200 else f"HTTP {r.status_code}", "latency_ms": ms}
    except Exception as e:
        return {"ok": False, "status": str(e)[:50], "latency_ms": 0}


def _get_uso_banco(session) -> dict:
    """Estatísticas de uso do banco."""
    try:
        from sqlmodel import Session as _SB, select as _selB, func as _funcB
        total_clients   = session.exec(select(func.count(Client.id))).one()
        total_snapshots = session.exec(select(func.count(ClientSnapshot.id))).one()
        total_augur     = session.exec(select(func.count(AugurMensagem.id))).one()
        total_reunioes  = session.exec(select(func.count(Meeting.id))).one()
        total_dossies   = session.exec(select(func.count(ConstruRiskDossie.id))).one()

        # Uso de créditos
        total_debitos = session.exec(
            select(func.sum(CreditLedger.amount_cents))
            .where(CreditLedger.amount_cents < 0)
        ).one() or 0

        return {
            "clientes":   total_clients,
            "snapshots":  total_snapshots,
            "msgs_augur": total_augur,
            "reunioes":   total_reunioes,
            "dossies":    total_dossies,
            "debitos_rs": abs(total_debitos) / 100,
        }
    except Exception as e:
        return {"erro": str(e)}


def _estimar_custos_mes(session) -> dict:
    """Estima custos do mês atual."""
    try:
        inicio_mes = _dt_sh.utcnow().replace(day=1, hour=0, minute=0, second=0).isoformat()

        # ConstruRisk: conta dossiês do mês
        dossies_mes = session.exec(
            select(func.count(ConstruRiskDossie.id))
            .where(ConstruRiskDossie.created_at >= inicio_mes)
        ).one() or 0

        # Estimativa de custo médio por dossiê (R$ 24 médio)
        custo_directdata = dossies_mes * 24.0

        # Augur: conta mensagens do mês (estimativa ~R$ 0,03/mensagem)
        msgs_mes = session.exec(
            select(func.count(AugurMensagem.id))
            .where(AugurMensagem.created_at >= inicio_mes,
                   AugurMensagem.role == "assistant")
        ).one() or 0
        custo_claude = msgs_mes * 0.03

        # Render: fixo mensal (aproximado)
        custo_render = 85.0  # ~$17/mês convertido

        return {
            "directdata": round(custo_directdata, 2),
            "claude":     round(custo_claude, 2),
            "render":     custo_render,
            "total":      round(custo_directdata + custo_claude + custo_render, 2),
            "dossies_mes": dossies_mes,
            "msgs_mes":    msgs_mes,
        }
    except Exception as e:
        return {"erro": str(e)}


# ── Rota GET /admin/saude ─────────────────────────────────────────────────────

@app.get("/admin/saude", response_class=HTMLResponse)
@require_login
async def admin_saude(request: Request, session: Session = Depends(get_session)):
    ctx = get_tenant_context(request, session)
    if not ctx or ctx.membership.role != "admin":
        return RedirectResponse("/", status_code=303)

    # Verifica serviços em paralelo
    import concurrent.futures as _cf_sh
    with _cf_sh.ThreadPoolExecutor(max_workers=3) as ex:
        f_anthropic   = ex.submit(_check_anthropic)
        f_directdata  = ex.submit(_check_directdata)
        f_notion      = ex.submit(_check_notion)
        status_anthropic  = f_anthropic.result(timeout=15)
        status_directdata = f_directdata.result(timeout=15)
        status_notion     = f_notion.result(timeout=15)

    uso    = _get_uso_banco(session)
    custos = _estimar_custos_mes(session)

    cc = get_client_or_none(session, ctx.company.id,
                            get_active_client_id(request, session, ctx))

    return render("admin_saude.html", request=request, context={
        "current_user":       ctx.user,
        "current_company":    ctx.company,
        "role":               ctx.membership.role,
        "current_client":     cc,
        "status_anthropic":   status_anthropic,
        "status_directdata":  status_directdata,
        "status_notion":      status_notion,
        "uso":                uso,
        "custos":             custos,
        "render_url":         "https://dashboard.render.com",
        "checked_at":         _dt_sh.utcnow().strftime("%d/%m/%Y %H:%M:%S UTC"),
    })


# ── Template ──────────────────────────────────────────────────────────────────

TEMPLATES["admin_saude.html"] = r"""
{% extends "base.html" %}
{% block content %}
<style>
  .sh-card{border:1px solid var(--mc-border);border-radius:14px;padding:1.25rem;background:#fff;margin-bottom:1rem;}
  .sh-service{display:flex;justify-content:space-between;align-items:center;padding:.65rem 0;border-bottom:1px solid var(--mc-border);}
  .sh-service:last-child{border-bottom:0;}
  .sh-dot{width:10px;height:10px;border-radius:50%;flex-shrink:0;}
  .sh-dot.ok{background:#16a34a;}
  .sh-dot.err{background:#dc2626;}
  .sh-stat{text-align:center;padding:.75rem 1rem;border:1px solid var(--mc-border);border-radius:10px;background:#fafafa;}
  .sh-stat-val{font-size:1.5rem;font-weight:800;color:var(--mc-primary);}
  .sh-stat-lbl{font-size:.72rem;color:var(--mc-muted);text-transform:uppercase;letter-spacing:.05em;}
  .sh-cost{display:flex;justify-content:space-between;padding:.5rem 0;border-bottom:1px solid var(--mc-border);font-size:.88rem;}
  .sh-cost:last-child{border-bottom:0;font-weight:700;}
</style>

<div class="d-flex justify-content-between align-items-center mb-3 flex-wrap gap-2">
  <div>
    <h4 class="mb-1">🩺 Painel de Saúde do Sistema</h4>
    <div class="muted small">Verificado em {{ checked_at }}</div>
  </div>
  <a href="/admin/saude" class="btn btn-outline-secondary btn-sm">
    <i class="bi bi-arrow-clockwise me-1"></i>Atualizar
  </a>
</div>

<div class="row g-3">

  {# Status dos Serviços #}
  <div class="col-md-6">
    <div class="sh-card">
      <h6 class="mb-3">🔌 Status dos Serviços</h6>

      <div class="sh-service">
        <div class="d-flex align-items-center gap-2">
          <div class="sh-dot {{ 'ok' if status_anthropic.ok else 'err' }}"></div>
          <div>
            <div class="fw-semibold small">Anthropic Claude</div>
            <div class="muted" style="font-size:.72rem;">API de IA — Augur e resumos</div>
          </div>
        </div>
        <div class="text-end">
          <div class="small {{ 'text-success' if status_anthropic.ok else 'text-danger' }}">
            {{ status_anthropic.status }}
          </div>
          {% if status_anthropic.latency_ms %}
          <div class="muted" style="font-size:.7rem;">{{ status_anthropic.latency_ms }}ms</div>
          {% endif %}
        </div>
      </div>

      <div class="sh-service">
        <div class="d-flex align-items-center gap-2">
          <div class="sh-dot {{ 'ok' if status_directdata.ok else 'err' }}"></div>
          <div>
            <div class="fw-semibold small">DirectData</div>
            <div class="muted" style="font-size:.72rem;">ConstruRisk e consultas de crédito</div>
          </div>
        </div>
        <div class="text-end">
          <div class="small {{ 'text-success' if status_directdata.ok else 'text-danger' }}">
            {{ status_directdata.status }}
          </div>
          {% if status_directdata.latency_ms %}
          <div class="muted" style="font-size:.7rem;">{{ status_directdata.latency_ms }}ms</div>
          {% endif %}
        </div>
      </div>

      <div class="sh-service">
        <div class="d-flex align-items-center gap-2">
          <div class="sh-dot {{ 'ok' if status_notion.ok else 'err' }}"></div>
          <div>
            <div class="fw-semibold small">Notion</div>
            <div class="muted" style="font-size:.72rem;">Reuniões e notas</div>
          </div>
        </div>
        <div class="text-end">
          <div class="small {{ 'text-success' if status_notion.ok else 'text-danger' }}">
            {{ status_notion.status }}
          </div>
          {% if status_notion.latency_ms %}
          <div class="muted" style="font-size:.7rem;">{{ status_notion.latency_ms }}ms</div>
          {% endif %}
        </div>
      </div>

      <div class="sh-service">
        <div class="d-flex align-items-center gap-2">
          <div class="sh-dot ok"></div>
          <div>
            <div class="fw-semibold small">Render</div>
            <div class="muted" style="font-size:.72rem;">Servidor da aplicação</div>
          </div>
        </div>
        <div class="text-end">
          <div class="small text-success">Operacional</div>
          <a href="{{ render_url }}" target="_blank" class="muted" style="font-size:.7rem;">Dashboard →</a>
        </div>
      </div>

      <div class="sh-service">
        <div class="d-flex align-items-center gap-2">
          <div class="sh-dot {{ 'ok' if 'STRIPE_SECRET_KEY' in env_keys else 'err' }}"></div>
          <div>
            <div class="fw-semibold small">Stripe</div>
            <div class="muted" style="font-size:.72rem;">Pagamentos e assinaturas</div>
          </div>
        </div>
        <div class="text-end">
          <div class="small {{ 'text-success' if stripe_ok else 'text-danger' }}">
            {{ 'Configurado' if stripe_ok else 'Sem chave' }}
          </div>
        </div>
      </div>

    </div>
  </div>

  {# Custos estimados do mês #}
  <div class="col-md-6">
    <div class="sh-card">
      <h6 class="mb-3">💰 Custos Estimados — Mês Atual</h6>
      {% if custos.erro is defined %}
      <div class="muted small">Erro ao calcular: {{ custos.erro }}</div>
      {% else %}
      <div class="sh-cost">
        <span>Render (fixo)</span>
        <span>R$ {{ "%.2f"|format(custos.render) }}</span>
      </div>
      <div class="sh-cost">
        <div>
          <div>DirectData</div>
          <div class="muted" style="font-size:.7rem;">{{ custos.dossies_mes }} dossiês × R$ 24 médio</div>
        </div>
        <span>R$ {{ "%.2f"|format(custos.directdata) }}</span>
      </div>
      <div class="sh-cost">
        <div>
          <div>Anthropic Claude</div>
          <div class="muted" style="font-size:.7rem;">{{ custos.msgs_mes }} respostas Augur × R$ 0,03</div>
        </div>
        <span>R$ {{ "%.2f"|format(custos.claude) }}</span>
      </div>
      <div class="sh-cost" style="font-size:.95rem;padding-top:.75rem;margin-top:.25rem;">
        <span>Total estimado</span>
        <span style="color:var(--mc-primary);">R$ {{ "%.2f"|format(custos.total) }}</span>
      </div>
      {% endif %}
    </div>
  </div>

  {# Uso da plataforma #}
  <div class="col-12">
    <div class="sh-card">
      <h6 class="mb-3">📊 Uso da Plataforma</h6>
      {% if uso.erro is defined %}
      <div class="muted small">{{ uso.erro }}</div>
      {% else %}
      <div class="row g-2">
        <div class="col-6 col-md-2">
          <div class="sh-stat">
            <div class="sh-stat-val">{{ uso.clientes }}</div>
            <div class="sh-stat-lbl">Clientes</div>
          </div>
        </div>
        <div class="col-6 col-md-2">
          <div class="sh-stat">
            <div class="sh-stat-val">{{ uso.snapshots }}</div>
            <div class="sh-stat-lbl">Avaliações</div>
          </div>
        </div>
        <div class="col-6 col-md-2">
          <div class="sh-stat">
            <div class="sh-stat-val">{{ uso.msgs_augur }}</div>
            <div class="sh-stat-lbl">Msgs Augur</div>
          </div>
        </div>
        <div class="col-6 col-md-2">
          <div class="sh-stat">
            <div class="sh-stat-val">{{ uso.reunioes }}</div>
            <div class="sh-stat-lbl">Reuniões</div>
          </div>
        </div>
        <div class="col-6 col-md-2">
          <div class="sh-stat">
            <div class="sh-stat-val">{{ uso.dossies }}</div>
            <div class="sh-stat-lbl">Dossiês</div>
          </div>
        </div>
        <div class="col-6 col-md-2">
          <div class="sh-stat">
            <div class="sh-stat-val">R$ {{ "%.0f"|format(uso.debitos_rs) }}</div>
            <div class="sh-stat-lbl">Debitado total</div>
          </div>
        </div>
      </div>
      {% endif %}
    </div>
  </div>

</div>
{% endblock %}
"""

# ── Adiciona ao menu de Gestão Interna ───────────────────────────────────────
if "saude" not in FEATURE_KEYS:
    FEATURE_KEYS["saude"] = {
        "title": "Saúde do Sistema",
        "desc":  "Monitor de serviços e custos.",
        "href":  "/admin/saude",
    }
    FEATURE_VISIBLE_ROLES["saude"] = {"admin"}
    for _g in FEATURE_GROUPS:
        if _g.get("key") == "gestao_interna":
            if "saude" not in _g["features"]:
                _g["features"].append("saude")
            break

# Adiciona stripe_ok ao contexto do template
_stripe_ok = bool(_os_sh.environ.get("STRIPE_SECRET_KEY"))

if hasattr(templates_env.loader, "mapping"):
    templates_env.loader.mapping = TEMPLATES

print("[saude] Patch carregado — sininho, popup bonus e painel de saude.")

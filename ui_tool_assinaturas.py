# ============================================================================
# ui_tool_assinaturas.py — Stripe Subscription System for Tools
# ============================================================================
# Exec'd in app.py namespace.
# Provides per-tool (and per-user for Augur) Stripe subscriptions.
# ============================================================================

from typing import Optional as _OptTA
from datetime import datetime as _dtTA, timezone as _tzTA, timedelta as _tdTA
from sqlmodel import Field as _FTA, SQLModel as _SMTA, UniqueConstraint as _UCTA
import os as _osTA

import stripe as _stripe_ta  # type: ignore

# ── 1. Model ──────────────────────────────────────────────────────────────────

class ToolAssinatura(_SMTA, table=True):
    __tablename__  = "toolassinatura"
    __table_args__ = (
        _UCTA("company_id", "user_id", "tool_code",
              name="uq_toolassinatura_company_user_tool"),
        {"extend_existing": True},
    )

    id:                  _OptTA[int]       = _FTA(default=None, primary_key=True)
    company_id:          int               = _FTA(index=True)
    user_id:             _OptTA[int]       = _FTA(default=None, index=True)
    tool_code:           str               = _FTA(index=True)
    stripe_sub_id:       str               = _FTA(default="")
    stripe_customer_id:  str               = _FTA(default="")
    status:              str               = _FTA(default="active")
    current_period_end:  _OptTA[_dtTA]     = _FTA(default=None)
    created_at:          _dtTA             = _FTA(default_factory=utcnow)
    updated_at:          _dtTA             = _FTA(default_factory=utcnow)


try:
    _SMTA.metadata.create_all(engine, tables=[ToolAssinatura.__table__])
except Exception as _e_ta_create:
    print(f"[tool_assinaturas] create_all warning: {_e_ta_create}")


# ── 2. DB migrations ──────────────────────────────────────────────────────────

try:
    with engine.connect() as _ta_conn:
        try:
            _ta_conn.execute(
                __import__("sqlalchemy").text(
                    "ALTER TABLE produtopreco ADD COLUMN preco_mensal_cents INTEGER DEFAULT 0"
                )
            )
            _ta_conn.commit()
        except Exception:
            _ta_conn.rollback()
        try:
            _ta_conn.execute(
                __import__("sqlalchemy").text(
                    "ALTER TABLE produtopreco ADD COLUMN stripe_price_id VARCHAR DEFAULT ''"
                )
            )
            _ta_conn.commit()
        except Exception:
            _ta_conn.rollback()
except Exception as _e_ta_mig:
    print(f"[tool_assinaturas] migration warning: {_e_ta_mig}")


# ── 3. Tool metadata ──────────────────────────────────────────────────────────

_TOOL_META = {
    "financeiro_gerencial": {
        "nome": "Financeiro Gerencial",
        "produto_codigo": "financeiro_gerencial_mensal",
        "nivel": "empresa",
    },
    "obras": {
        "nome": "Obras + Horas",
        "produto_codigo": "obras_horas_mensal",
        "nivel": "empresa",
    },
    "viabilidade": {
        "nome": "Viabilidade Imobiliária",
        "produto_codigo": "viabilidade_mensal",
        "nivel": "empresa",
    },
    "gestao_obras": {
        "nome": "Gestão de Obras",
        "produto_codigo": "gestao_obras_mensal",
        "nivel": "empresa",
    },
    "augur": {
        "nome": "Augur — Consultor IA",
        "produto_codigo": "augur_mensal",
        "nivel": "usuario",
    },
}

# Upsert new products for viabilidade_mensal and gestao_obras_mensal
try:
    with Session(engine) as _ta_sess_init:
        # We need at least one company to upsert — iterate all companies
        from sqlmodel import select as _sel_ta_init
        try:
            _companies_ta = _ta_sess_init.exec(
                _sel_ta_init(__import__("sqlmodel").SQLModel).limit(0)  # just a no-op
            )
        except Exception:
            pass
        # Try to upsert using _upsert_produto if available
        if "_upsert_produto" in dir() or "_upsert_produto" in globals():
            pass  # Will do per-company upsert on first request
except Exception:
    pass


# ── 4. Helper functions ───────────────────────────────────────────────────────

def _tool_assinatura_ativa(session, company_id: int, tool_code: str) -> bool:
    """Company-level tool subscription check."""
    from datetime import datetime, timezone
    try:
        sub = session.exec(
            select(ToolAssinatura)
            .where(
                ToolAssinatura.company_id == company_id,
                ToolAssinatura.tool_code  == tool_code,
                ToolAssinatura.user_id    == None,
                ToolAssinatura.status     == "active",
            )
        ).first()
        if not sub:
            return False
        if sub.current_period_end and sub.current_period_end < datetime.now(timezone.utc):
            return False
        return True
    except Exception:
        return False


def _augur_assinatura_ativa(session, company_id: int, user_id: int) -> bool:
    """User-level Augur subscription check."""
    from datetime import datetime, timezone
    try:
        sub = session.exec(
            select(ToolAssinatura)
            .where(
                ToolAssinatura.company_id == company_id,
                ToolAssinatura.user_id    == user_id,
                ToolAssinatura.tool_code  == "augur",
                ToolAssinatura.status     == "active",
            )
        ).first()
        if not sub:
            return False
        if sub.current_period_end and sub.current_period_end < datetime.now(timezone.utc):
            return False
        return True
    except Exception:
        return False


def _get_produto_preco_ta(session, company_id: int, codigo: str):
    """Get ProdutoPreco row for given company and codigo."""
    try:
        return session.exec(
            select(ProdutoPreco)
            .where(
                ProdutoPreco.company_id == company_id,
                ProdutoPreco.codigo     == codigo,
                ProdutoPreco.ativo      == True,
            )
        ).first()
    except Exception:
        return None


def _ensure_tool_products(session, company_id: int):
    """Upsert viabilidade_mensal and gestao_obras_mensal products if missing."""
    try:
        _extra_prods = [
            {
                "codigo": "viabilidade_mensal",
                "nome": "Viabilidade Imobiliária",
                "descricao": "Acesso mensal à análise de viabilidade imobiliária",
                "categoria": "ferramenta",
                "modelo": "assinatura",
                "creditos": 0,
            },
            {
                "codigo": "gestao_obras_mensal",
                "nome": "Gestão de Obras",
                "descricao": "Acesso mensal à gestão de obras",
                "categoria": "ferramenta",
                "modelo": "assinatura",
                "creditos": 0,
            },
        ]
        changed = False
        for _p in _extra_prods:
            if callable(globals().get("_upsert_produto")):
                if _upsert_produto(session, company_id, _p["codigo"], _p["nome"],
                                   _p["descricao"], _p["categoria"], _p["modelo"], _p["creditos"]):
                    changed = True
        if changed:
            session.commit()
    except Exception as _e:
        print(f"[tool_assinaturas] _ensure_tool_products warning: {_e}")


# ── 5. GET /api/tools/status ──────────────────────────────────────────────────

@app.get("/api/tools/status")
@require_login
async def api_tools_status(request: Request, session: Session = Depends(get_session)):
    ctx = get_tenant_context(request, session)
    if not ctx:
        return JSONResponse({"error": "Não autenticado"}, status_code=401)

    company_id = ctx.company.id
    user_id    = ctx.user.id

    # Ensure products exist
    _ensure_tool_products(session, company_id)

    tools_result = {}
    for _tc, _meta in _TOOL_META.items():
        if _meta["nivel"] == "usuario":
            continue  # augur handled separately below

        _ativo = _tool_assinatura_ativa(session, company_id, _tc)

        # Get subscription details for periodo_fim
        _periodo_fim = None
        try:
            _sub = session.exec(
                select(ToolAssinatura)
                .where(
                    ToolAssinatura.company_id == company_id,
                    ToolAssinatura.tool_code  == _tc,
                    ToolAssinatura.user_id    == None,
                )
            ).first()
            if _sub and _sub.current_period_end:
                _periodo_fim = _sub.current_period_end.strftime("%Y-%m-%d")
        except Exception:
            pass

        # Get pricing info
        _stripe_price_id   = ""
        _preco_mensal_reais = ""
        try:
            _pp = _get_produto_preco_ta(session, company_id, _meta["produto_codigo"])
            if _pp:
                _stripe_price_id    = getattr(_pp, "stripe_price_id", "") or ""
                _pmcents            = getattr(_pp, "preco_mensal_cents", 0) or 0
                if _pmcents:
                    _preco_mensal_reais = str(_pmcents // 100)
        except Exception:
            pass

        tools_result[_tc] = {
            "ativo":             _ativo,
            "periodo_fim":       _periodo_fim,
            "stripe_price_id":   _stripe_price_id,
            "preco_mensal_reais": _preco_mensal_reais,
        }

    # Augur (user-level)
    _augur_ativo = _augur_assinatura_ativa(session, company_id, user_id)
    _augur_fim   = None
    try:
        _augur_sub = session.exec(
            select(ToolAssinatura)
            .where(
                ToolAssinatura.company_id == company_id,
                ToolAssinatura.user_id    == user_id,
                ToolAssinatura.tool_code  == "augur",
            )
        ).first()
        if _augur_sub and _augur_sub.current_period_end:
            _augur_fim = _augur_sub.current_period_end.strftime("%Y-%m-%d")
    except Exception:
        pass

    return JSONResponse({
        "tools": tools_result,
        "augur": {
            "ativo":       _augur_ativo,
            "periodo_fim": _augur_fim,
        },
    })


# ── 6. POST /ferramentas/{tool_code}/assinar ──────────────────────────────────

@app.post("/ferramentas/{tool_code}/assinar")
@require_login
async def ferramenta_assinar(
    tool_code: str,
    request: Request,
    session: Session = Depends(get_session),
):
    ctx = get_tenant_context(request, session)
    if not ctx:
        return RedirectResponse("/login", status_code=303)

    if tool_code not in _TOOL_META:
        return JSONResponse({"error": "Ferramenta inválida"}, status_code=400)

    _meta       = _TOOL_META[tool_code]
    _produto_cd = _meta["produto_codigo"]
    _nivel      = _meta["nivel"]

    # Ensure product exists
    _ensure_tool_products(session, ctx.company.id)

    _pp = _get_produto_preco_ta(session, ctx.company.id, _produto_cd)
    if not _pp:
        return JSONResponse({"error": "Produto não configurado. Configure o preço em /admin/precificacao."}, status_code=400)

    _stripe_price_id = getattr(_pp, "stripe_price_id", "") or ""
    if not _stripe_price_id:
        return JSONResponse(
            {"error": "Stripe Price ID não configurado para este produto. Acesse /admin/precificacao para configurar."},
            status_code=400,
        )

    try:
        _stripe_ta.api_key = _osTA.environ.get("STRIPE_SECRET_KEY", "")

        _base_url = str(request.base_url).rstrip("/")

        _metadata = {
            "tipo":       "tool_assinatura",
            "company_id": str(ctx.company.id),
            "tool_code":  tool_code,
            "user_id":    str(ctx.user.id) if _nivel == "usuario" else "",
        }

        _checkout = _stripe_ta.checkout.Session.create(
            mode="subscription",
            line_items=[{
                "price":    _stripe_price_id,
                "quantity": 1,
            }],
            metadata=_metadata,
            success_url=f"{_base_url}/ferramentas?assinatura=ok&tool={tool_code}",
            cancel_url=f"{_base_url}/ferramentas?assinatura=cancelada",
            customer_email=getattr(ctx.user, "email", None) or None,
        )

        return RedirectResponse(_checkout.url, status_code=303)

    except Exception as _e:
        print(f"[tool_assinaturas] Erro ao criar Checkout: {_e}")
        return JSONResponse({"error": f"Erro Stripe: {_e}"}, status_code=500)


# ── 7. POST /ferramentas/{tool_code}/cancelar ─────────────────────────────────

@app.post("/ferramentas/{tool_code}/cancelar")
@require_login
async def ferramenta_cancelar(
    tool_code: str,
    request: Request,
    session: Session = Depends(get_session),
):
    ctx = get_tenant_context(request, session)
    if not ctx:
        return RedirectResponse("/login", status_code=303)

    if tool_code not in _TOOL_META:
        return RedirectResponse("/ferramentas", status_code=303)

    _nivel = _TOOL_META[tool_code]["nivel"]

    try:
        if _nivel == "usuario":
            _sub = session.exec(
                select(ToolAssinatura)
                .where(
                    ToolAssinatura.company_id == ctx.company.id,
                    ToolAssinatura.user_id    == ctx.user.id,
                    ToolAssinatura.tool_code  == tool_code,
                )
            ).first()
        else:
            _sub = session.exec(
                select(ToolAssinatura)
                .where(
                    ToolAssinatura.company_id == ctx.company.id,
                    ToolAssinatura.user_id    == None,
                    ToolAssinatura.tool_code  == tool_code,
                )
            ).first()

        if _sub:
            if _sub.stripe_sub_id:
                try:
                    _stripe_ta.api_key = _osTA.environ.get("STRIPE_SECRET_KEY", "")
                    _stripe_ta.Subscription.cancel(_sub.stripe_sub_id)
                except Exception as _e_stripe:
                    print(f"[tool_assinaturas] Stripe cancel warning: {_e_stripe}")
            _sub.status     = "cancelled"
            _sub.updated_at = utcnow()
            session.add(_sub)
            session.commit()
    except Exception as _e_cancel:
        print(f"[tool_assinaturas] cancelar error: {_e_cancel}")

    return RedirectResponse("/ferramentas", status_code=303)


# ── 8. POST /stripe/webhook/tools ────────────────────────────────────────────

@app.post("/stripe/webhook/tools")
async def stripe_webhook_tools(request: Request, session: Session = Depends(get_session)) -> Response:
    _secret = _osTA.getenv("STRIPE_WEBHOOK_SECRET", "")
    if not _secret:
        return Response(status_code=400)

    _payload = await request.body()
    _sig     = request.headers.get("stripe-signature", "")

    try:
        _stripe_ta.api_key = _osTA.environ.get("STRIPE_SECRET_KEY", "")
        _event = _stripe_ta.Webhook.construct_event(_payload, _sig, _secret)
    except Exception as _e_wh:
        print(f"[tool_assinaturas] Webhook signature error: {_e_wh}")
        return Response(status_code=400)

    def _safe(o, k, default=None):
        try:
            if hasattr(o, "__getitem__"):
                return o[k]
            return getattr(o, k, default)
        except Exception:
            return default

    _etype    = _safe(_event, "type", "")
    _edata    = _safe(_event, "data")
    _eobj     = _safe(_edata, "object") if _edata else {}
    _eobj     = _eobj or {}

    # ── checkout.session.completed ────────────────────────────────────────────
    if _etype == "checkout.session.completed":
        _meta_obj = _safe(_eobj, "metadata") or {}
        _tipo     = _safe(_meta_obj, "tipo") or ""
        if _tipo != "tool_assinatura":
            return Response(status_code=200)

        _company_id = int(_safe(_meta_obj, "company_id") or 0)
        _tool_code  = str(_safe(_meta_obj, "tool_code") or "")
        _user_id_s  = _safe(_meta_obj, "user_id") or ""
        _user_id    = int(_user_id_s) if _user_id_s and _user_id_s.strip() else None

        _sub_id     = str(_safe(_eobj, "subscription") or "")
        _cust_id    = str(_safe(_eobj, "customer") or "")

        if not _company_id or not _tool_code:
            return Response(status_code=200)

        try:
            _now = utcnow()
            _period_end = _now + _tdTA(days=30)

            _existing = session.exec(
                select(ToolAssinatura)
                .where(
                    ToolAssinatura.company_id == _company_id,
                    ToolAssinatura.user_id    == _user_id,
                    ToolAssinatura.tool_code  == _tool_code,
                )
            ).first()

            if _existing:
                _existing.stripe_sub_id      = _sub_id
                _existing.stripe_customer_id = _cust_id
                _existing.status             = "active"
                _existing.current_period_end = _period_end
                _existing.updated_at         = _now
                session.add(_existing)
            else:
                session.add(ToolAssinatura(
                    company_id         = _company_id,
                    user_id            = _user_id,
                    tool_code          = _tool_code,
                    stripe_sub_id      = _sub_id,
                    stripe_customer_id = _cust_id,
                    status             = "active",
                    current_period_end = _period_end,
                    created_at         = _now,
                    updated_at         = _now,
                ))
            session.commit()
        except Exception as _e_cs:
            print(f"[tool_assinaturas] checkout.session.completed error: {_e_cs}")

    # ── customer.subscription.updated ─────────────────────────────────────────
    elif _etype == "customer.subscription.updated":
        _sub_id = str(_safe(_eobj, "id") or "")
        if not _sub_id:
            return Response(status_code=200)

        _stripe_status = str(_safe(_eobj, "status") or "")
        _cpe_unix      = _safe(_eobj, "current_period_end")

        # Map Stripe status to our status
        _our_status = "active"
        if _stripe_status == "canceled":
            _our_status = "cancelled"
        elif _stripe_status == "past_due":
            _our_status = "past_due"
        elif _stripe_status == "active":
            _our_status = "active"
        else:
            _our_status = _stripe_status  # pass-through

        _period_end = None
        if _cpe_unix:
            try:
                _period_end = _dtTA.fromtimestamp(int(_cpe_unix), tz=_tzTA.utc).replace(tzinfo=None)
            except Exception:
                pass

        try:
            _sub = session.exec(
                select(ToolAssinatura)
                .where(ToolAssinatura.stripe_sub_id == _sub_id)
            ).first()
            if _sub:
                _sub.status     = _our_status
                if _period_end:
                    _sub.current_period_end = _period_end
                _sub.updated_at = utcnow()
                session.add(_sub)
                session.commit()
        except Exception as _e_su:
            print(f"[tool_assinaturas] subscription.updated error: {_e_su}")

    # ── customer.subscription.deleted ─────────────────────────────────────────
    elif _etype == "customer.subscription.deleted":
        _sub_id = str(_safe(_eobj, "id") or "")
        if not _sub_id:
            return Response(status_code=200)

        try:
            _sub = session.exec(
                select(ToolAssinatura)
                .where(ToolAssinatura.stripe_sub_id == _sub_id)
            ).first()
            if _sub:
                _sub.status     = "cancelled"
                _sub.updated_at = utcnow()
                session.add(_sub)
                session.commit()
        except Exception as _e_sd:
            print(f"[tool_assinaturas] subscription.deleted error: {_e_sd}")

    return Response(status_code=200)


# ── 9. Patch ferramentas.html — inject subscription UI ───────────────────────

_TOOL_SUBS_OVERLAY = r"""
<div id="tool-subs-overlay" style="display:none;"></div>

<script>
(function() {
  // Map tool codes to card selectors (data-tool attribute)
  const TOOL_CODES = ["financeiro_gerencial", "obras", "viabilidade", "gestao_obras"];

  function _fmtDate(iso) {
    if (!iso) return "";
    const d = new Date(iso + "T00:00:00");
    return d.toLocaleDateString("pt-BR", {day:"2-digit", month:"2-digit"});
  }

  function _injectToolUI(toolCode, info) {
    const card = document.querySelector(`[data-tool="${toolCode}"]`);
    if (!card) return;
    let cont = card.querySelector(".tool-sub-actions");
    if (!cont) {
      cont = document.createElement("div");
      cont.className = "tool-sub-actions mt-2";
      const btnArea = card.querySelector(".d-flex.gap-2.flex-wrap");
      if (btnArea) {
        btnArea.parentNode.insertBefore(cont, btnArea.nextSibling);
      } else {
        card.appendChild(cont);
      }
    }
    if (info.ativo) {
      const fim = info.periodo_fim ? ` até ${_fmtDate(info.periodo_fim)}` : "";
      cont.innerHTML = `
        <div class="d-flex align-items-center gap-2 flex-wrap mt-1">
          <span class="badge bg-success" style="font-size:.8rem;">&#x2705; Assinado${fim}</span>
          <button onclick="cancelarFerramenta('${toolCode}')"
            class="btn btn-link btn-sm text-danger p-0"
            style="font-size:.75rem;text-decoration:underline;">cancelar</button>
        </div>`;
    } else {
      const preco = info.preco_mensal_reais ? `R$${info.preco_mensal_reais}/mês` : "Assinar";
      if (info.stripe_price_id) {
        cont.innerHTML = `
          <button onclick="assinarFerramenta('${toolCode}')"
            class="btn btn-outline-primary btn-sm mt-1">
            ${preco}
          </button>`;
      } else {
        cont.innerHTML = `<span class="text-muted small mt-1" style="font-size:.75rem;">Preço não configurado</span>`;
      }
    }
  }

  function _injectAugurUI(info) {
    const card = document.querySelector('[data-tool="augur"]');
    if (!card) return;
    let cont = card.querySelector(".tool-sub-actions");
    if (!cont) {
      cont = document.createElement("div");
      cont.className = "tool-sub-actions mt-2";
      const btnArea = card.querySelector(".d-flex.gap-2.flex-wrap");
      if (btnArea) {
        btnArea.parentNode.insertBefore(cont, btnArea.nextSibling);
      } else {
        card.appendChild(cont);
      }
    }
    if (info.ativo) {
      const fim = info.periodo_fim ? ` até ${_fmtDate(info.periodo_fim)}` : "";
      cont.innerHTML = `
        <div class="d-flex align-items-center gap-2 flex-wrap mt-1">
          <span class="badge bg-success" style="font-size:.8rem;">&#x2705; Assinado${fim}</span>
          <button onclick="cancelarFerramenta('augur')"
            class="btn btn-link btn-sm text-danger p-0"
            style="font-size:.75rem;text-decoration:underline;">cancelar</button>
        </div>`;
    }
  }

  async function loadToolStatus() {
    try {
      const resp = await fetch("/api/tools/status");
      if (!resp.ok) return;
      const data = await resp.json();
      const tools = data.tools || {};
      for (const code of TOOL_CODES) {
        if (tools[code] !== undefined) {
          _injectToolUI(code, tools[code]);
        }
      }
      if (data.augur !== undefined) {
        _injectAugurUI(data.augur);
      }
    } catch(e) {
      console.warn("[tool_assinaturas] Failed to load tool status:", e);
    }
  }

  window.assinarFerramenta = async function(code) {
    try {
      const form = document.createElement("form");
      form.method = "POST";
      form.action = `/ferramentas/${code}/assinar`;
      document.body.appendChild(form);
      form.submit();
    } catch(e) {
      alert("Erro ao iniciar assinatura: " + e);
    }
  };

  window.cancelarFerramenta = async function(code) {
    if (!confirm(`Cancelar assinatura de ${code.replace(/_/g," ")}?`)) return;
    try {
      const resp = await fetch(`/ferramentas/${code}/cancelar`, {method: "POST"});
      window.location.reload();
    } catch(e) {
      alert("Erro ao cancelar: " + e);
    }
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", loadToolStatus);
  } else {
    loadToolStatus();
  }
})();
</script>
"""

# Add data-tool attributes and inject overlay into ferramentas.html

def _patch_ferramentas_html():
    _tpl = TEMPLATES.get("ferramentas.html", "")
    if not _tpl:
        return

    # Add data-tool="financeiro_gerencial" to Financeiro card
    _tpl = _tpl.replace(
        '<div class="col-lg-6">\n      <div class="card p-4 h-100">\n        <div class="d-flex justify-content-between align-items-start gap-3 flex-wrap">\n          <div>\n            <h5 class="mb-1">Financeiro Gerencial</h5>',
        '<div class="col-lg-6" data-tool="financeiro_gerencial">\n      <div class="card p-4 h-100">\n        <div class="d-flex justify-content-between align-items-start gap-3 flex-wrap">\n          <div>\n            <h5 class="mb-1">Financeiro Gerencial</h5>',
    )

    # Add data-tool="obras" to Obras card
    _tpl = _tpl.replace(
        '<div class="col-lg-6">\n      <div class="card p-4 h-100">\n        <div class="d-flex justify-content-between align-items-start gap-3 flex-wrap">\n          <div>\n            <h5 class="mb-1">Obras + Horas</h5>',
        '<div class="col-lg-6" data-tool="obras">\n      <div class="card p-4 h-100">\n        <div class="d-flex justify-content-between align-items-start gap-3 flex-wrap">\n          <div>\n            <h5 class="mb-1">Obras + Horas</h5>',
    )

    # Add data-tool="viabilidade" to Viabilidade card
    _tpl = _tpl.replace(
        '<div class="col-lg-6">\n      <div class="card p-4 h-100">\n        <div class="d-flex justify-content-between align-items-start gap-3 flex-wrap">\n          <div>\n            <h5 class="mb-1">Viabilidade Imobiliária</h5>',
        '<div class="col-lg-6" data-tool="viabilidade">\n      <div class="card p-4 h-100">\n        <div class="d-flex justify-content-between align-items-start gap-3 flex-wrap">\n          <div>\n            <h5 class="mb-1">Viabilidade Imobiliária</h5>',
    )

    # Add data-tool="gestao_obras" to Gestão de Obras card
    _tpl = _tpl.replace(
        '<div class="col-lg-6">\n      <div class="card p-4 h-100">\n        <div class="d-flex justify-content-between align-items-start gap-3 flex-wrap">\n          <div>\n            <h5 class="mb-1">Gestão de Obras</h5>',
        '<div class="col-lg-6" data-tool="gestao_obras">\n      <div class="card p-4 h-100">\n        <div class="d-flex justify-content-between align-items-start gap-3 flex-wrap">\n          <div>\n            <h5 class="mb-1">Gestão de Obras</h5>',
    )

    # Inject overlay before endblock
    _end_marker = "\n{% endif %}\n{% endblock %}"
    if _TOOL_SUBS_OVERLAY not in _tpl and _end_marker in _tpl:
        _tpl = _tpl.replace(_end_marker, _TOOL_SUBS_OVERLAY + _end_marker)

    TEMPLATES["ferramentas.html"] = _tpl


_patch_ferramentas_html()


# ── 10. Patch precificacao.html — add preco_mensal_cents + stripe_price_id columns ──

def _patch_precificacao_html():
    _tpl = TEMPLATES.get("precificacao.html", "")
    if not _tpl:
        return

    # Patch header row: add two columns
    _old_hdr = '<div class="pc-hdr-row"><span>Produto</span><span>Descrição</span><span>Modelo</span><span>Créditos</span><span style="text-align:center">Ativo</span></div>'
    _new_hdr = '<div class="pc-hdr-row" style="grid-template-columns:2.5fr 1.5fr 1.3fr 90px 100px 110px 50px;"><span>Produto</span><span>Descrição</span><span>Modelo</span><span>Créditos</span><span>Preço R$/mês</span><span>Stripe Price ID</span><span style="text-align:center">Ativo</span></div>'

    if _old_hdr in _tpl:
        _tpl = _tpl.replace(_old_hdr, _new_hdr)

    # Patch row grid and inject two new input cells before the active checkbox
    _old_row_grid = 'display:grid;grid-template-columns:2.5fr 1.5fr 1.3fr 90px 50px;'
    _new_row_grid = 'display:grid;grid-template-columns:2.5fr 1.5fr 1.3fr 90px 100px 110px 50px;'
    if _old_row_grid in _tpl:
        _tpl = _tpl.replace(_old_row_grid, _new_row_grid, 1)  # only the CSS rule

    # Also replace inline style on .pc-row divs
    _old_pcrow_class = '  .pc-row{display:grid;grid-template-columns:2.5fr 1.5fr 1.3fr 90px 50px;'
    _new_pcrow_class = '  .pc-row{display:grid;grid-template-columns:2.5fr 1.5fr 1.3fr 90px 100px 110px 50px;'
    if _old_pcrow_class in _tpl:
        _tpl = _tpl.replace(_old_pcrow_class, _new_pcrow_class)

    # Inject two new cells in each row before the active checkbox cell
    _old_cell_end = (
        '      <div><input type="number" name="creditos_{{ p.codigo }}" value="{{ p.creditos }}" min="0" step="1" class="pc-inp" placeholder="0"></div>\n'
        '      <div style="text-align:center"><input type="checkbox" name="ativo_{{ p.codigo }}" value="1" {% if p.ativo %}checked{% endif %} class="form-check-input"></div>'
    )
    _new_cell_end = (
        '      <div><input type="number" name="creditos_{{ p.codigo }}" value="{{ p.creditos }}" min="0" step="1" class="pc-inp" placeholder="0"></div>\n'
        '      <div><input type="number" name="preco_mensal_cents_{{ p.codigo }}" value="{{ (p.preco_mensal_cents // 100) if p.preco_mensal_cents else 0 }}" min="0" step="1" class="pc-inp" placeholder="0" title="Preço em R$ (inteiro)"></div>\n'
        '      <div>{% if p.modelo == "assinatura" %}<input type="text" name="stripe_price_id_{{ p.codigo }}" value="{{ p.stripe_price_id or \'\' }}" class="pc-inp" style="text-align:left;font-size:.72rem;font-family:monospace;" placeholder="price_...">{% else %}<span class="text-muted small">—</span>{% endif %}</div>\n'
        '      <div style="text-align:center"><input type="checkbox" name="ativo_{{ p.codigo }}" value="1" {% if p.ativo %}checked{% endif %} class="form-check-input"></div>'
    )
    if _old_cell_end in _tpl:
        _tpl = _tpl.replace(_old_cell_end, _new_cell_end)

    # Responsive fallback: keep cols working on mobile for 2-col grid
    _old_responsive = '@media(max-width:640px){.pc-row,.pc-hdr-row{grid-template-columns:1fr 1fr;}.pc-row>*:nth-child(2){display:none;}}'
    _new_responsive = '@media(max-width:768px){.pc-row,.pc-hdr-row{grid-template-columns:1fr 1fr;}.pc-row>*:nth-child(n+3){display:none;}}'
    if _old_responsive in _tpl:
        _tpl = _tpl.replace(_old_responsive, _new_responsive)

    TEMPLATES["precificacao.html"] = _tpl


_patch_precificacao_html()


# ── 11. Patch /admin/precificacao/salvar to also save new fields ──────────────

# Wrap the existing route by replacing it with one that also handles
# preco_mensal_cents_* and stripe_price_id_*

_orig_precificacao_salvar = None
for _r in app.routes:
    if hasattr(_r, "path") and _r.path == "/admin/precificacao/salvar" and "POST" in getattr(_r, "methods", set()):
        _orig_precificacao_salvar = getattr(_r, "endpoint", None)
        break

if _orig_precificacao_salvar is not None:
    # Remove old route
    app.routes = [_r for _r in app.routes
                  if not (hasattr(_r, "path") and _r.path == "/admin/precificacao/salvar"
                          and "POST" in getattr(_r, "methods", set()))]

    @app.post("/admin/precificacao/salvar")
    @require_login
    async def precificacao_salvar_ta(request: Request, session: Session = Depends(get_session)):
        ctx = get_tenant_context(request, session)
        if not ctx or ctx.membership.role not in ("admin", "equipe"):
            return RedirectResponse("/admin/precificacao", status_code=303)

        form = await request.form()

        # Save creditos + modelo + ativo (original logic)
        for _key, _val in form.items():
            if not _key.startswith("creditos_"):
                continue
            _codigo = _key[len("creditos_"):]
            try:
                _creditos = int(_val or 0)
            except ValueError:
                continue
            _pp = session.exec(
                select(ProdutoPreco)
                .where(
                    ProdutoPreco.company_id == ctx.company.id,
                    ProdutoPreco.codigo     == _codigo,
                )
            ).first()
            if _pp:
                _pp.creditos   = _creditos
                _pp.ativo      = f"ativo_{_codigo}" in form
                _pp.modelo     = form.get(f"modelo_{_codigo}", _pp.modelo)
                _pp.updated_at = str(utcnow())
                session.add(_pp)

        # Save new fields: preco_mensal_cents and stripe_price_id
        for _key, _val in form.items():
            if not _key.startswith("preco_mensal_cents_"):
                continue
            _codigo = _key[len("preco_mensal_cents_"):]
            try:
                _reais = int(_val or 0)
                _cents = _reais * 100
            except ValueError:
                continue
            _pp = session.exec(
                select(ProdutoPreco)
                .where(
                    ProdutoPreco.company_id == ctx.company.id,
                    ProdutoPreco.codigo     == _codigo,
                )
            ).first()
            if _pp:
                try:
                    _pp.preco_mensal_cents = _cents
                    _pp.updated_at         = str(utcnow())
                    session.add(_pp)
                except Exception:
                    pass

        for _key, _val in form.items():
            if not _key.startswith("stripe_price_id_"):
                continue
            _codigo = _key[len("stripe_price_id_"):]
            _sp_id  = str(_val or "").strip()
            _pp = session.exec(
                select(ProdutoPreco)
                .where(
                    ProdutoPreco.company_id == ctx.company.id,
                    ProdutoPreco.codigo     == _codigo,
                )
            ).first()
            if _pp:
                try:
                    _pp.stripe_price_id = _sp_id
                    _pp.updated_at      = str(utcnow())
                    session.add(_pp)
                except Exception:
                    pass

        try:
            session.commit()
        except Exception as _e_commit:
            print(f"[tool_assinaturas] precificacao_salvar commit error: {_e_commit}")

        if callable(globals().get("set_flash")):
            set_flash(request, "Preços atualizados com sucesso.")

        return RedirectResponse("/admin/precificacao", status_code=303)

else:
    # Original route not found — define standalone version
    @app.post("/admin/precificacao/salvar")
    @require_login
    async def precificacao_salvar_ta_fallback(request: Request, session: Session = Depends(get_session)):
        ctx = get_tenant_context(request, session)
        if not ctx or ctx.membership.role not in ("admin", "equipe"):
            return RedirectResponse("/admin/precificacao", status_code=303)

        form = await request.form()

        for _key, _val in form.items():
            if not _key.startswith("creditos_"):
                continue
            _codigo = _key[len("creditos_"):]
            try:
                _creditos = int(_val or 0)
            except ValueError:
                continue
            _pp = session.exec(
                select(ProdutoPreco)
                .where(
                    ProdutoPreco.company_id == ctx.company.id,
                    ProdutoPreco.codigo     == _codigo,
                )
            ).first()
            if _pp:
                _pp.creditos   = _creditos
                _pp.ativo      = f"ativo_{_codigo}" in form
                _pp.modelo     = form.get(f"modelo_{_codigo}", _pp.modelo)
                _pp.updated_at = str(utcnow())
                session.add(_pp)

        for _key, _val in form.items():
            if not _key.startswith("preco_mensal_cents_"):
                continue
            _codigo = _key[len("preco_mensal_cents_"):]
            try:
                _cents = int(_val or 0) * 100
            except ValueError:
                continue
            _pp = session.exec(
                select(ProdutoPreco)
                .where(
                    ProdutoPreco.company_id == ctx.company.id,
                    ProdutoPreco.codigo     == _codigo,
                )
            ).first()
            if _pp:
                try:
                    _pp.preco_mensal_cents = _cents
                    _pp.updated_at         = str(utcnow())
                    session.add(_pp)
                except Exception:
                    pass

        for _key, _val in form.items():
            if not _key.startswith("stripe_price_id_"):
                continue
            _codigo = _key[len("stripe_price_id_"):]
            _pp = session.exec(
                select(ProdutoPreco)
                .where(
                    ProdutoPreco.company_id == ctx.company.id,
                    ProdutoPreco.codigo     == _codigo,
                )
            ).first()
            if _pp:
                try:
                    _pp.stripe_price_id = str(_val or "").strip()
                    _pp.updated_at      = str(utcnow())
                    session.add(_pp)
                except Exception:
                    pass

        try:
            session.commit()
        except Exception as _e_commit2:
            print(f"[tool_assinaturas] precificacao_salvar commit error: {_e_commit2}")

        if callable(globals().get("set_flash")):
            set_flash(request, "Preços atualizados com sucesso.")

        return RedirectResponse("/admin/precificacao", status_code=303)


# ── 12. Reload template env ────────────────────────────────────────────────────

try:
    if hasattr(templates_env.loader, "mapping"):
        templates_env.loader.mapping = TEMPLATES
except Exception as _e_tpl_reload:
    print(f"[tool_assinaturas] template env reload warning: {_e_tpl_reload}")


# ── Done ──────────────────────────────────────────────────────────────────────

print("[tool_assinaturas] ✓ Stripe tool subscription system loaded.")
print("  Routes: GET /api/tools/status")
print("          POST /ferramentas/{tool_code}/assinar")
print("          POST /ferramentas/{tool_code}/cancelar")
print("          POST /stripe/webhook/tools")
print("  Patches: ferramentas.html, precificacao.html, /admin/precificacao/salvar")

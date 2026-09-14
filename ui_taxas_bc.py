# ============================================================================
# ui_taxas_bc.py — Taxas de Juros do Banco Central do Brasil
# ============================================================================

import threading as _threading_bc
import json as _json_bc
import logging as _logging_bc
from datetime import datetime as _datetime_bc, timezone as _timezone_bc, timedelta as _timedelta_bc
from typing import Optional as _Optional_bc

from fastapi import Request as _Request_bc
from fastapi.responses import HTMLResponse as _HTMLResponse_bc, JSONResponse as _JSONResponse_bc, Response as _Response_bc
from sqlmodel import Field as _Field_bc, Session as _Session_bc, SQLModel as _SQLModel_bc, select as _select_bc

try:
    import httpx as _httpx_bc
    _HAS_HTTPX_BC = True
except ImportError:
    _HAS_HTTPX_BC = False
    import urllib.request as _urllib_request_bc
    import urllib.error as _urllib_error_bc

_logger_bc = _logging_bc.getLogger("ui_taxas_bc")

# ── Model ────────────────────────────────────────────────────────────────────

class TaxaBC(_SQLModel_bc, table=True):
    id: _Optional_bc[int] = _Field_bc(default=None, primary_key=True)
    modalidade: str = _Field_bc(default="")
    taxa_am: float = _Field_bc(default=0.0)
    taxa_aa: float = _Field_bc(default=0.0)
    mes_ref: str = _Field_bc(default="")
    atualizado_em: str = _Field_bc(default="")

_SQLModel_bc.metadata.create_all(engine)

# ── Modalidade mapping ───────────────────────────────────────────────────────

_BC_MODALIDADE_MAP = [
    ("Capital de Giro",             lambda m: "Capital de Giro" in m),
    ("Antecipação de Recebíveis",   lambda m: "Desconto" in m or "Recebív" in m or "Recebiv" in m),
    ("Home Equity",                 lambda m: "Imóvel" in m or "Imovel" in m or "Home" in m or "hipotec" in m),
    ("BNDES",                       lambda m: "BNDES" in m),
    ("Financiamento",               lambda m: "Financiamento" in m),
]

# ── Fetch function ───────────────────────────────────────────────────────────

def _bc_fetch_rates():
    try:
        now = _datetime_bc.now(_timezone_bc.utc)
        # Use previous month
        first_of_month = now.replace(day=1)
        prev_month = first_of_month - _timedelta_bc(days=1)
        mes_ref = prev_month.strftime("%Y-%m")

        url = (
            f"https://olinda.bcb.gov.br/olinda/servico/taxaJuros/versao/v2/odata/"
            f"TaxasJurosMensalPorMes(Mes=@Mes)?@Mes='{mes_ref}'"
            f"&$top=200&$format=json"
        )

        _logger_bc.info(f"[TaxasBC] Buscando taxas para {mes_ref}: {url}")

        if _HAS_HTTPX_BC:
            resp = _httpx_bc.get(url, timeout=30)
            resp.raise_for_status()
            data = resp.json()
        else:
            req = _urllib_request_bc.Request(url, headers={"Accept": "application/json"})
            with _urllib_request_bc.urlopen(req, timeout=30) as r:
                data = _json_bc.loads(r.read().decode())

        values = data.get("value", [])
        if not values:
            _logger_bc.warning(f"[TaxasBC] Nenhum dado retornado para {mes_ref}")
            return {"ok": False, "error": "Sem dados para o período"}

        # Group by our labels
        buckets: dict[str, list[dict]] = {label: [] for label, _ in _BC_MODALIDADE_MAP}
        for item in values:
            nome = item.get("Modalidade", "")
            for label, matcher in _BC_MODALIDADE_MAP:
                if matcher(nome):
                    buckets[label].append(item)
                    break

        atualizado_em = _datetime_bc.now(_timezone_bc.utc).isoformat()

        with _Session_bc(engine) as s:
            # Delete existing rows for this mes_ref
            existing = s.exec(_select_bc(TaxaBC).where(TaxaBC.mes_ref == mes_ref)).all()
            for row in existing:
                s.delete(row)
            s.commit()

            inserted = []
            for label, rows in buckets.items():
                if not rows:
                    continue
                am_vals = [r.get("TaxaJurosMesPercentual", 0) or 0 for r in rows]
                aa_vals = [r.get("TaxaJurosAnoPercentual", 0) or 0 for r in rows]
                taxa_am = sum(am_vals) / len(am_vals)
                taxa_aa = sum(aa_vals) / len(aa_vals)

                t = TaxaBC(
                    modalidade=label,
                    taxa_am=round(taxa_am, 4),
                    taxa_aa=round(taxa_aa, 4),
                    mes_ref=mes_ref,
                    atualizado_em=atualizado_em,
                )
                s.add(t)
                inserted.append(label)
            s.commit()

        _logger_bc.info(f"[TaxasBC] Inseridas {len(inserted)} modalidades para {mes_ref}")
        return {"ok": True, "mes_ref": mes_ref, "modalidades": inserted}

    except Exception as exc:
        _logger_bc.error(f"[TaxasBC] Erro ao buscar taxas: {exc}", exc_info=True)
        return {"ok": False, "error": str(exc)}


# ── Startup background fetch ─────────────────────────────────────────────────

def _bc_startup_fetch():
    try:
        now = _datetime_bc.now(_timezone_bc.utc)
        first_of_month = now.replace(day=1)
        prev_month = first_of_month - _timedelta_bc(days=1)
        mes_ref = prev_month.strftime("%Y-%m")
        cur_ref = now.strftime("%Y-%m")

        with _Session_bc(engine) as s:
            existing = s.exec(
                _select_bc(TaxaBC).where(
                    (TaxaBC.mes_ref == mes_ref) | (TaxaBC.mes_ref == cur_ref)
                )
            ).first()

        if existing:
            _logger_bc.info(f"[TaxasBC] Dados já existem para {mes_ref}, pulando fetch inicial")
            return

        _logger_bc.info("[TaxasBC] Iniciando fetch de taxas em background...")
        _bc_fetch_rates()
    except Exception as exc:
        _logger_bc.error(f"[TaxasBC] Erro no startup fetch: {exc}", exc_info=True)


try:
    _threading_bc.Thread(target=_bc_startup_fetch, daemon=True).start()
except Exception as _e:
    _logger_bc.error(f"[TaxasBC] Não foi possível iniciar thread: {_e}")

# ── Templates ────────────────────────────────────────────────────────────────

TEMPLATES["admin_taxas_bc.html"] = r"""{% extends "base.html" %}
{% block title %}Taxas Banco Central{% endblock %}
{% block content %}
<div class="container py-4">
  <div class="d-flex align-items-center justify-content-between mb-4">
    <h4 class="mb-0">📊 Taxas Banco Central do Brasil</h4>
    <button id="btnAtualizar" class="btn btn-primary btn-sm" onclick="atualizarTaxas()">
      🔄 Atualizar Agora
    </button>
  </div>

  {% if taxas %}
  <p class="text-muted mb-1">Referência: <strong>{{ mes_ref }}</strong> — Atualizado em: {{ atualizado_em }}</p>
  <div class="table-responsive mt-3">
    <table class="table table-bordered table-hover align-middle">
      <thead class="table-dark">
        <tr>
          <th>Modalidade</th>
          <th class="text-end">Taxa a.m. (%)</th>
          <th class="text-end">Taxa a.a. (%)</th>
        </tr>
      </thead>
      <tbody>
        {% for t in taxas %}
        <tr>
          <td>{{ t.modalidade }}</td>
          <td class="text-end">{{ "%.4f"|format(t.taxa_am) }}</td>
          <td class="text-end">{{ "%.4f"|format(t.taxa_aa) }}</td>
        </tr>
        {% endfor %}
      </tbody>
    </table>
  </div>
  {% else %}
  <div class="alert alert-warning">Nenhuma taxa disponível. Clique em "Atualizar Agora" para buscar.</div>
  {% endif %}

  <div id="msg-result" class="mt-3"></div>
</div>

<script>
async function atualizarTaxas() {
  const btn = document.getElementById('btnAtualizar');
  btn.disabled = true;
  btn.textContent = '⏳ Aguarde...';
  const res = document.getElementById('msg-result');
  res.innerHTML = '';
  try {
    const r = await fetch('/admin/taxas-bc/atualizar', { method: 'POST' });
    const d = await r.json();
    if (d.ok) {
      res.innerHTML = '<div class="alert alert-success">✅ Taxas atualizadas para ' + d.mes_ref + ' (' + (d.modalidades||[]).length + ' modalidades)</div>';
      setTimeout(() => location.reload(), 1500);
    } else {
      res.innerHTML = '<div class="alert alert-danger">❌ Erro: ' + (d.error || 'Falha desconhecida') + '</div>';
    }
  } catch(e) {
    res.innerHTML = '<div class="alert alert-danger">❌ Erro de rede: ' + e.message + '</div>';
  } finally {
    btn.disabled = false;
    btn.textContent = '🔄 Atualizar Agora';
  }
}
</script>
{% endblock %}
"""

templates_env.loader.mapping["admin_taxas_bc.html"] = TEMPLATES["admin_taxas_bc.html"]

# ── Routes ───────────────────────────────────────────────────────────────────

@app.options("/api/taxas-bc")
async def _taxas_bc_options():
    return _Response_bc(
        status_code=204,
        headers={
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "GET, OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type",
        },
    )


@app.get("/api/taxas-bc")
async def _taxas_bc_get():
    with _Session_bc(engine) as s:
        # Get most recent mes_ref
        all_rows = s.exec(_select_bc(TaxaBC).order_by(TaxaBC.mes_ref.desc())).all()

    if not all_rows:
        return _JSONResponse_bc(
            content={"mes_ref": None, "atualizado_em": None, "taxas": {}},
            headers={"Access-Control-Allow-Origin": "*"},
        )

    mes_ref = all_rows[0].mes_ref
    atualizado_em = all_rows[0].atualizado_em
    rows_for_mes = [r for r in all_rows if r.mes_ref == mes_ref]

    taxas = {}
    for r in rows_for_mes:
        taxas[r.modalidade] = {"am": r.taxa_am, "aa": r.taxa_aa}

    return _JSONResponse_bc(
        content={"mes_ref": mes_ref, "atualizado_em": atualizado_em, "taxas": taxas},
        headers={"Access-Control-Allow-Origin": "*"},
    )


@app.post("/admin/taxas-bc/atualizar")
async def _taxas_bc_atualizar(request: _Request_bc):
    token = request.session.get("token")
    if not token:
        return _JSONResponse_bc({"ok": False, "error": "Não autorizado"}, status_code=401)
    result = _bc_fetch_rates()
    return _JSONResponse_bc(result)


@app.get("/admin/taxas-bc")
async def _taxas_bc_admin_page(request: _Request_bc):
    token = request.session.get("token")
    if not token:
        from fastapi.responses import RedirectResponse
        return RedirectResponse("/login")

    with _Session_bc(engine) as s:
        all_rows = s.exec(_select_bc(TaxaBC).order_by(TaxaBC.mes_ref.desc())).all()

    mes_ref = all_rows[0].mes_ref if all_rows else ""
    atualizado_em = all_rows[0].atualizado_em if all_rows else ""
    rows_for_mes = [r for r in all_rows if r.mes_ref == mes_ref] if all_rows else []

    ctx = dict(request=request, taxas=rows_for_mes, mes_ref=mes_ref, atualizado_em=atualizado_em)
    return _HTMLResponse_bc(templates_env.get_template("admin_taxas_bc.html").render(**ctx))

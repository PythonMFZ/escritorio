# ui_leads_site.py — Recebe leads do site público (calculadora de valuation e simulação de crédito)
# Exec'd no namespace do app.py

import json as _json_ls
from datetime import datetime as _dt_ls
from fastapi import Request as _Req_ls
from fastapi.responses import JSONResponse as _JR_ls, Response as _Resp_ls

# ── Modelo de lead ─────────────────────────────────────────────────────────────

def _ls_cors(resp):
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Methods"] = "POST, OPTIONS"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
    return resp


def _ls_notify_email(subject: str, body_html: str):
    try:
        _smtp_send_email(
            to_email="rafael@maffezzollicapital.com.br",
            subject=subject,
            html_body=body_html,
            text_body=body_html.replace("<br>", "\n").replace("<b>", "").replace("</b>", ""),
        )
    except Exception as _e:
        print(f"[leads_site] Erro ao notificar: {_e}")


def _ls_format_brl(v):
    try:
        return f"R$ {float(v):,.0f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except Exception:
        return str(v)


# ── CORS OPTIONS ──────────────────────────────────────────────────────────────

@app.options("/api/lead/valuation")
async def lead_valuation_options(request: _Req_ls):
    return _ls_cors(_Resp_ls(status_code=200))


@app.options("/api/lead/credito")
async def lead_credito_options(request: _Req_ls):
    return _ls_cors(_Resp_ls(status_code=200))


# ── POST /api/lead/valuation ──────────────────────────────────────────────────

@app.post("/api/lead/valuation")
async def lead_valuation(request: _Req_ls):
    try:
        body = await request.json()
    except Exception:
        return _ls_cors(_JR_ls({"ok": False}, status_code=400))

    nome       = str(body.get("nome", "")).strip()
    email      = str(body.get("email", "")).strip()
    whatsapp   = str(body.get("whatsapp", "")).strip()
    empresa    = str(body.get("empresa", "")).strip()
    faturamento = body.get("faturamento_anual", 0)
    ebitda     = body.get("ebitda", 0)
    setor      = str(body.get("setor", "")).strip()
    funcionarios = str(body.get("funcionarios", "")).strip()
    valuation  = str(body.get("valuation_estimado", "")).strip()
    ip         = request.headers.get("X-Forwarded-For", "")
    ts         = _dt_ls.utcnow().strftime("%d/%m/%Y %H:%M UTC")

    print(f"[leads_site] Valuation lead: {nome} <{email}> — {empresa} — {setor} — {valuation}")

    html = f"""
    <h2>📊 Novo Lead — Calculadora de Valuation</h2>
    <p><b>Data:</b> {ts}</p>
    <table border="0" cellpadding="6">
      <tr><td><b>Nome:</b></td><td>{nome}</td></tr>
      <tr><td><b>E-mail:</b></td><td>{email}</td></tr>
      <tr><td><b>WhatsApp:</b></td><td>{whatsapp}</td></tr>
      <tr><td><b>Empresa:</b></td><td>{empresa}</td></tr>
      <tr><td><b>Setor:</b></td><td>{setor}</td></tr>
      <tr><td><b>Faturamento Anual:</b></td><td>{_ls_format_brl(faturamento)}</td></tr>
      <tr><td><b>EBITDA:</b></td><td>{_ls_format_brl(ebitda)}</td></tr>
      <tr><td><b>Funcionários:</b></td><td>{funcionarios}</td></tr>
      <tr><td><b>Valuation estimado:</b></td><td><b>{valuation}</b></td></tr>
      <tr><td><b>IP:</b></td><td>{ip}</td></tr>
    </table>
    """
    _ls_notify_email(f"[Lead Valuation] {empresa} — {nome}", html)

    resp = _JR_ls({"ok": True})
    return _ls_cors(resp)


# ── POST /api/lead/credito ─────────────────────────────────────────────────────

@app.post("/api/lead/credito")
async def lead_credito(request: _Req_ls):
    try:
        body = await request.json()
    except Exception:
        return _ls_cors(_JR_ls({"ok": False}, status_code=400))

    nome       = str(body.get("nome", "")).strip()
    email      = str(body.get("email", "")).strip()
    whatsapp   = str(body.get("whatsapp", "")).strip()
    empresa    = str(body.get("empresa", "")).strip()
    cnpj       = str(body.get("cnpj", "")).strip()
    finalidade = str(body.get("finalidade", "")).strip()
    valor      = body.get("valor", 0)
    prazo      = body.get("prazo", 0)
    faturamento = body.get("faturamento", 0)
    garantias  = body.get("garantias", [])
    taxa_est   = str(body.get("taxa_estimada", "")).strip()
    parcela_est = str(body.get("parcela_estimada", "")).strip()
    ip         = request.headers.get("X-Forwarded-For", "")
    ts         = _dt_ls.utcnow().strftime("%d/%m/%Y %H:%M UTC")

    if isinstance(garantias, list):
        garantias_str = ", ".join(garantias) or "Não informado"
    else:
        garantias_str = str(garantias)

    print(f"[leads_site] Crédito lead: {nome} <{email}> — {empresa} — {_ls_format_brl(valor)} — {finalidade}")

    html = f"""
    <h2>💰 Novo Lead — Simulação de Crédito</h2>
    <p><b>Data:</b> {ts}</p>
    <table border="0" cellpadding="6">
      <tr><td><b>Nome:</b></td><td>{nome}</td></tr>
      <tr><td><b>E-mail:</b></td><td>{email}</td></tr>
      <tr><td><b>WhatsApp:</b></td><td>{whatsapp}</td></tr>
      <tr><td><b>Empresa:</b></td><td>{empresa}</td></tr>
      <tr><td><b>CNPJ:</b></td><td>{cnpj or '—'}</td></tr>
      <tr><td><b>Finalidade:</b></td><td>{finalidade}</td></tr>
      <tr><td><b>Valor desejado:</b></td><td>{_ls_format_brl(valor)}</td></tr>
      <tr><td><b>Prazo:</b></td><td>{prazo} meses</td></tr>
      <tr><td><b>Faturamento anual:</b></td><td>{_ls_format_brl(faturamento)}</td></tr>
      <tr><td><b>Garantias:</b></td><td>{garantias_str}</td></tr>
      <tr><td><b>Taxa estimada:</b></td><td>{taxa_est}</td></tr>
      <tr><td><b>Parcela estimada:</b></td><td>{parcela_est}</td></tr>
      <tr><td><b>IP:</b></td><td>{ip}</td></tr>
    </table>
    """
    _ls_notify_email(f"[Lead Crédito] {empresa} — {_ls_format_brl(valor)} — {finalidade}", html)

    resp = _JR_ls({"ok": True})
    return _ls_cors(resp)


print("[leads_site] ✅ Rotas de lead do site público registradas.")

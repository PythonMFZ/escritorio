# ============================================================================
# MÓDULO — Contratos de Clientes e Cobranças Mensais
# /admin/financeiro/contratos  (Fase 1+2 — com boleto Mercado Pago)
# ============================================================================

import json         as _json_ct
import os           as _os_ct
import uuid         as _uuid_ct
import httpx        as _httpx_ct
from datetime       import date as _date_ct, datetime as _dt_ct, timedelta as _td_ct
from typing         import Optional as _Opt_ct
from sqlmodel       import Field as _F_ct, SQLModel as _SM_ct, select as _sel_ct
from fastapi        import Request as _Req_ct, Depends as _Dep_ct
from fastapi.responses import HTMLResponse as _HTML_ct, RedirectResponse as _RR_ct, JSONResponse as _JR_ct

# Access token lido do env (configurado no Render)
_MP_TOKEN = _os_ct.environ.get("MP_ACCESS_TOKEN", "APP_USR-6791500683764067-061116-2946ba11cbd0edc3f5101358057daa09-3296655851")
_MP_BASE  = "https://api.mercadopago.com"


# ── Modelos ───────────────────────────────────────────────────────────────────

class ContratoCliente(_SM_ct, table=True):
    __tablename__  = "contrato_cliente"
    __table_args__ = {"extend_existing": True}
    id:               _Opt_ct[int] = _F_ct(default=None, primary_key=True)
    company_id:       int          = _F_ct(index=True)
    client_id:        _Opt_ct[int] = _F_ct(default=None, index=True)
    nome_cliente:     str          = _F_ct(default="")
    nome_contrato:    str          = _F_ct(default="")
    servicos:         str          = _F_ct(default="")
    valor_cents:      int          = _F_ct(default=0)
    dia_vencimento:   int          = _F_ct(default=10)
    data_inicio:      str          = _F_ct(default="")
    data_fim:         str          = _F_ct(default="")
    status:           str          = _F_ct(default="ativo")
    observacao:       str          = _F_ct(default="")
    email_cliente:    str          = _F_ct(default="")   # fallback se cliente não tiver email
    documento_cliente:str          = _F_ct(default="")   # fallback se cliente não tiver CNPJ/CPF
    created_at:       _dt_ct       = _F_ct(default_factory=lambda: _dt_ct.utcnow())
    updated_at:       _dt_ct       = _F_ct(default_factory=lambda: _dt_ct.utcnow())


class CobrancaMensal(_SM_ct, table=True):
    __tablename__  = "cobranca_mensal"
    __table_args__ = {"extend_existing": True}
    id:               _Opt_ct[int] = _F_ct(default=None, primary_key=True)
    company_id:       int          = _F_ct(index=True)
    contrato_id:      int          = _F_ct(index=True)
    client_id:        _Opt_ct[int] = _F_ct(default=None, index=True)
    nome_cliente:     str          = _F_ct(default="")
    nome_contrato:    str          = _F_ct(default="")
    competencia:      str          = _F_ct(default="")
    data_vencimento:  str          = _F_ct(default="")
    valor_cents:      int          = _F_ct(default=0)
    status:           str          = _F_ct(default="pendente")
    data_pagamento:   str          = _F_ct(default="")
    valor_pago_cents: _Opt_ct[int] = _F_ct(default=None)
    forma_pagamento:  str          = _F_ct(default="")
    observacao:       str          = _F_ct(default="")
    nf_numero:        str          = _F_ct(default="")
    boleto_url:       str          = _F_ct(default="")
    boleto_codigo:    str          = _F_ct(default="")   # linha digitável
    mp_payment_id:    str          = _F_ct(default="")   # ID do pagamento no MP
    created_at:       _dt_ct       = _F_ct(default_factory=lambda: _dt_ct.utcnow())
    updated_at:       _dt_ct       = _F_ct(default_factory=lambda: _dt_ct.utcnow())


# ── Criação/migração de tabelas ───────────────────────────────────────────────

try:
    for _tbl_ct in (ContratoCliente.__table__, CobrancaMensal.__table__):
        _tbl_ct.create(engine, checkfirst=True)
    print("[contratos] ✅ Tabelas OK")
except Exception as _e_ct:
    print(f"[contratos] Tabelas: {_e_ct}")

# Migrations: adiciona colunas novas sem recriar tabela
try:
    _is_pg_ct = DATABASE_URL.startswith("postgres")
    if _is_pg_ct:
        from sqlalchemy import text as _txt_ct
        with engine.begin() as _c_ct:
            for _col, _typ in [
                ("email_cliente",     "VARCHAR DEFAULT ''"),
                ("documento_cliente", "VARCHAR DEFAULT ''"),
                ("boleto_codigo",     "VARCHAR DEFAULT ''"),
                ("mp_payment_id",     "VARCHAR DEFAULT ''"),
            ]:
                try:
                    _c_ct.execute(_txt_ct(f"ALTER TABLE contrato_cliente ADD COLUMN IF NOT EXISTS {_col} {_typ}"))
                except Exception:
                    pass
                try:
                    _c_ct.execute(_txt_ct(f"ALTER TABLE cobranca_mensal ADD COLUMN IF NOT EXISTS {_col} {_typ}"))
                except Exception:
                    pass
        print("[contratos] ✅ Migrations OK")
except Exception as _e_mg_ct:
    print(f"[contratos] migration: {_e_mg_ct}")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _ct_brl(cents: int) -> str:
    v = abs(cents) / 100
    return f"R$ {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

def _ct_hoje() -> str:
    return _date_ct.today().isoformat()

def _ct_competencia_atual() -> str:
    return _date_ct.today().strftime("%Y-%m")

def _ct_vencimento(contrato: ContratoCliente, competencia: str) -> str:
    ano, mes = int(competencia[:4]), int(competencia[5:7])
    dia = min(contrato.dia_vencimento, 28)
    return f"{ano:04d}-{mes:02d}-{dia:02d}"

def _ct_atualizar_vencidos(session):
    hoje = _ct_hoje()
    vencidas = session.exec(
        _sel_ct(CobrancaMensal).where(
            CobrancaMensal.status == "pendente",
            CobrancaMensal.data_vencimento < hoje,
        )
    ).all()
    for c in vencidas:
        c.status = "vencido"
        c.updated_at = _dt_ct.utcnow()
        session.add(c)
    if vencidas:
        session.commit()


def _ct_gerar_cobrancas_mes(session, company_id: int, competencia: str = None):
    if not competencia:
        competencia = _ct_competencia_atual()
    contratos = session.exec(
        _sel_ct(ContratoCliente).where(
            ContratoCliente.company_id == company_id,
            ContratoCliente.status     == "ativo",
        )
    ).all()
    geradas = 0
    for contrato in contratos:
        if contrato.data_inicio and contrato.data_inicio[:7] > competencia:
            continue
        if contrato.data_fim and contrato.data_fim[:7] < competencia:
            continue
        ja = session.exec(
            _sel_ct(CobrancaMensal).where(
                CobrancaMensal.contrato_id == contrato.id,
                CobrancaMensal.competencia == competencia,
            )
        ).first()
        if ja:
            continue
        cobranca = CobrancaMensal(
            company_id      = company_id,
            contrato_id     = contrato.id,
            client_id       = contrato.client_id,
            nome_cliente    = contrato.nome_cliente,
            nome_contrato   = contrato.nome_contrato,
            competencia     = competencia,
            data_vencimento = _ct_vencimento(contrato, competencia),
            valor_cents     = contrato.valor_cents,
            status          = "pendente",
        )
        session.add(cobranca)
        geradas += 1
    if geradas:
        session.commit()
        # Sincroniza com OfficeFinancialEntry para o dashboard
        for _c in session.exec(
            _sel_ct(CobrancaMensal).where(
                CobrancaMensal.company_id  == company_id,
                CobrancaMensal.competencia == competencia,
                CobrancaMensal.status      == "pendente",
            )
        ).all():
            try:
                _ct_sync_entry(session, _c)
            except Exception:
                pass
    return geradas


# ── Mercado Pago — boleto ─────────────────────────────────────────────────────

def _mp_request(method: str, path: str, body: dict = None) -> dict:
    url     = f"{_MP_BASE}{path}"
    headers = {
        "Authorization":    f"Bearer {_MP_TOKEN}",
        "Content-Type":     "application/json",
        "X-Idempotency-Key": str(_uuid_ct.uuid4()),
    }
    with _httpx_ct.Client(timeout=20) as client:
        if method == "GET":
            resp = client.get(url, headers=headers)
        else:
            resp = client.post(url, headers=headers, json=body)

    if not resp.is_success:
        try:
            err = resp.json()
            msg = err.get("message") or err.get("error") or resp.text
        except Exception:
            msg = resp.text
        print(f"[mp] erro {resp.status_code}: {msg}")
        raise ValueError(f"MP {resp.status_code}: {msg}")

    return resp.json()


def _ct_mp_gerar_boleto(cobranca: CobrancaMensal, contrato: ContratoCliente, session=None) -> dict:
    """Cria boleto no Mercado Pago. Puxa dados do cadastro do cliente quando disponível."""

    # Tenta carregar o cliente da plataforma para puxar dados cadastrais
    cliente_obj = None
    if contrato.client_id and session:
        try:
            cliente_obj = session.get(Client, contrato.client_id)
        except Exception:
            pass

    # E-mail: cliente > contrato
    email = (cliente_obj.email if cliente_obj and cliente_obj.email else "") or contrato.email_cliente
    if not email:
        raise ValueError("Preencha o e-mail no cadastro do cliente (ou no campo E-mail do contrato) para gerar boleto.")

    # Documento (CPF/CNPJ): cliente > contrato
    doc_raw = (cliente_obj.cnpj if cliente_obj and cliente_obj.cnpj else "") or contrato.documento_cliente
    doc = doc_raw.replace(".", "").replace("-", "").replace("/", "").replace(" ", "").strip()
    if not doc:
        raise ValueError("Preencha o CNPJ/CPF no cadastro do cliente para gerar boleto.")
    doc_type = "CPF" if len(doc) == 11 else "CNPJ"

    # Endereço: cliente
    zip_code = (cliente_obj.zip_code if cliente_obj else "").replace("-", "").strip()
    city     = (cliente_obj.city  if cliente_obj else "").strip()
    uf       = (cliente_obj.state if cliente_obj else "").strip().upper()
    street   = (cliente_obj.address if cliente_obj else "").strip() or "Endereço não informado"

    if not zip_code or not city or not uf:
        raise ValueError(
            "Preencha CEP, Cidade e Estado no cadastro do cliente para gerar boleto. "
            f"Atual: CEP='{zip_code}' Cidade='{city}' UF='{uf}'"
        )

    nome_parts = (contrato.nome_cliente or "Cliente").split(" ", 1)
    primeiro   = nome_parts[0]
    sobrenome  = nome_parts[1] if len(nome_parts) > 1 else "."

    venc_iso = f"{cobranca.data_vencimento}T23:59:00.000-03:00"

    payload = {
        "transaction_amount": round(cobranca.valor_cents / 100, 2),
        "description":        f"{cobranca.nome_contrato} — {cobranca.competencia}",
        "payment_method_id":  "bolbradesco",
        "date_of_expiration": venc_iso,
        "payer": {
            "email":      email,
            "first_name": primeiro,
            "last_name":  sobrenome,
            "identification": {"type": doc_type, "number": doc},
            "address": {
                "zip_code":      zip_code,
                "street_name":   street,
                "street_number": "S/N",
                "neighborhood":  city,
                "city":          city,
                "federal_unit":  uf,
            },
        },
    }
    result = _mp_request("POST", "/v1/payments", payload)
    barcode = (result.get("barcode") or {})
    return {
        "mp_payment_id": str(result.get("id", "")),
        "boleto_url":    result.get("transaction_details", {}).get("external_resource_url", ""),
        "boleto_codigo": barcode.get("content", ""),
    }


# ── Email boleto ─────────────────────────────────────────────────────────────

_ADMIN_EMAIL = "maffezzolli.eng@gmail.com"

def _ct_enviar_email_boleto(cobranca: CobrancaMensal, contrato: ContratoCliente, session=None):
    """Envia boleto por e-mail para o cliente e cópia para o escritório."""
    cliente_obj = None
    if contrato.client_id and session:
        try:
            cliente_obj = session.get(Client, contrato.client_id)
        except Exception:
            pass

    email_cliente = (cliente_obj.email if cliente_obj and cliente_obj.email else "") or contrato.email_cliente
    if not email_cliente:
        raise RuntimeError("Cliente sem e-mail cadastrado.")

    valor_fmt = _ct_brl(cobranca.valor_cents)
    html = f"""
<div style="font-family:sans-serif;max-width:600px;margin:0 auto">
  <h2 style="color:#1a1a2e">Boleto disponível — {cobranca.nome_contrato}</h2>
  <p>Olá, <strong>{cobranca.nome_cliente}</strong>!</p>
  <p>Segue o boleto referente à competência <strong>{cobranca.competencia}</strong>:</p>
  <table style="width:100%;border-collapse:collapse;margin:16px 0">
    <tr><td style="padding:8px;background:#f5f5f5;font-weight:bold">Valor</td>
        <td style="padding:8px">{valor_fmt}</td></tr>
    <tr><td style="padding:8px;background:#f5f5f5;font-weight:bold">Vencimento</td>
        <td style="padding:8px">{cobranca.data_vencimento}</td></tr>
    <tr><td style="padding:8px;background:#f5f5f5;font-weight:bold">Serviço</td>
        <td style="padding:8px">{cobranca.nome_contrato}</td></tr>
  </table>
  {"<p><strong>Linha digitável:</strong><br><code style='font-size:13px'>" + cobranca.boleto_codigo + "</code></p>" if cobranca.boleto_codigo else ""}
  <p style="margin-top:24px">
    <a href="{cobranca.boleto_url}" style="background:#e65c00;color:#fff;padding:12px 24px;border-radius:6px;text-decoration:none;font-weight:bold">
      📄 Abrir boleto
    </a>
  </p>
  <p style="color:#888;font-size:12px;margin-top:32px">Maffezzolli Capital — Consultoria Financeira</p>
</div>"""

    _smtp_send_email(
        to_email=email_cliente,
        subject=f"Boleto {cobranca.nome_contrato} — {cobranca.competencia} — {valor_fmt}",
        html_body=html,
        text_body=f"Boleto {cobranca.nome_contrato} venc. {cobranca.data_vencimento}: {cobranca.boleto_url}",
    )
    # Cópia para o escritório
    try:
        _smtp_send_email(
            to_email=_ADMIN_EMAIL,
            subject=f"[Cópia] Boleto enviado — {cobranca.nome_cliente} — {cobranca.competencia}",
            html_body=html,
            text_body=f"Boleto {cobranca.nome_cliente} {cobranca.competencia}: {cobranca.boleto_url}",
        )
    except Exception:
        pass
    print(f"[boleto] 📧 email enviado para {email_cliente}")


# ── Integração com OfficeFinancialEntry (dashboard) ───────────────────────────

def _ct_sync_entry(session, cobranca: CobrancaMensal, user_id: int = 1):
    """Cria ou atualiza OfficeFinancialEntry correspondente à CobrancaMensal."""
    try:
        ref = f"contrato-{cobranca.contrato_id}-{cobranca.competencia}"
        entry = session.exec(
            _sel_ct(OfficeFinancialEntry).where(
                OfficeFinancialEntry.company_id    == cobranca.company_id,
                OfficeFinancialEntry.document_number == ref,
            )
        ).first()

        status_map = {
            "pendente":  "aberto",
            "vencido":   "aberto",
            "pago":      "recebido",
            "cancelado": "cancelado",
        }
        novo_status = status_map.get(cobranca.status, "aberto")

        if entry is None:
            entry = OfficeFinancialEntry(
                company_id            = cobranca.company_id,
                created_by_user_id    = user_id,
                entry_kind            = "receber",
                status                = novo_status,
                client_id             = cobranca.client_id,
                description           = f"{cobranca.nome_contrato} — {cobranca.competencia}",
                document_number       = ref,
                competence_date       = cobranca.competencia + "-01",
                due_date              = cobranca.data_vencimento,
                settlement_date       = cobranca.data_pagamento or "",
                amount_expected_brl   = cobranca.valor_cents / 100,
                amount_realized_brl   = (cobranca.valor_pago_cents or cobranca.valor_cents) / 100 if cobranca.status == "pago" else 0.0,
            )
        else:
            entry.status              = novo_status
            entry.settlement_date     = cobranca.data_pagamento or ""
            entry.amount_realized_brl = (cobranca.valor_pago_cents or cobranca.valor_cents) / 100 if cobranca.status == "pago" else 0.0
            entry.updated_by_user_id  = user_id

        session.add(entry)
        session.commit()
    except Exception as _e:
        print(f"[contratos] sync_entry cobranca {cobranca.id}: {_e}")


# ── Rotas ─────────────────────────────────────────────────────────────────────

@app.get("/admin/financeiro/contratos", response_class=_HTML_ct)
@require_role({"admin", "equipe"})
async def financeiro_contratos_lista(request: _Req_ct, session=_Dep_ct(get_session)):
    ctx = get_tenant_context(request, session)
    if not ctx:
        return _RR_ct("/login", status_code=303)
    try:
        _ct_gerar_cobrancas_mes(session, ctx.company.id)
        _ct_atualizar_vencidos(session)
        # Garante que cobranças existentes estejam no dashboard
        for _c in session.exec(
            _sel_ct(CobrancaMensal).where(CobrancaMensal.company_id == ctx.company.id)
        ).all():
            _ct_sync_entry(session, _c, user_id=ctx.user.id)
    except Exception as _e:
        print(f"[contratos] auto-gerar: {_e}")

    contratos = session.exec(
        _sel_ct(ContratoCliente).where(ContratoCliente.company_id == ctx.company.id)
        .order_by(ContratoCliente.status, ContratoCliente.nome_cliente)
    ).all()

    cobrancas_mes = session.exec(
        _sel_ct(CobrancaMensal).where(
            CobrancaMensal.company_id == ctx.company.id,
            CobrancaMensal.competencia == _ct_competencia_atual(),
        )
    ).all()
    total_mensal = sum(c.valor_cents for c in contratos if c.status == "ativo")
    pendente_mes = sum(c.valor_cents for c in cobrancas_mes if c.status in ("pendente", "vencido"))
    recebido_mes = sum(c.valor_pago_cents or c.valor_cents for c in cobrancas_mes if c.status == "pago")
    vencido_mes  = sum(c.valor_cents for c in cobrancas_mes if c.status == "vencido")

    html = f"""
{{% extends "base.html" %}}
{{% block content %}}
<div class="d-flex justify-content-between align-items-start flex-wrap gap-2 mb-3">
  <div>
    <h4 class="mb-0">Contratos e Cobranças</h4>
    <div class="text-muted small">Gestão de contratos recorrentes e inadimplência</div>
  </div>
  <div class="d-flex gap-2 flex-wrap">
    <a class="btn btn-outline-secondary" href="/admin/financeiro">← Financeiro</a>
    <a class="btn btn-outline-primary" href="/admin/financeiro/cobrancas">Ver Cobranças</a>
    <a class="btn btn-primary" href="/admin/financeiro/contratos/novo">+ Novo Contrato</a>
  </div>
</div>

<div class="row g-3 mb-4">
  <div class="col-md-3"><div class="card p-3 text-center">
    <div class="text-muted small mb-1">Receita Mensal Ativa</div>
    <div class="fw-bold fs-5 text-success">{_ct_brl(total_mensal)}</div>
    <div class="text-muted" style="font-size:.75rem;">{sum(1 for c in contratos if c.status=='ativo')} contratos</div>
  </div></div>
  <div class="col-md-3"><div class="card p-3 text-center">
    <div class="text-muted small mb-1">Recebido este mês</div>
    <div class="fw-bold fs-5 text-success">{_ct_brl(recebido_mes)}</div>
  </div></div>
  <div class="col-md-3"><div class="card p-3 text-center">
    <div class="text-muted small mb-1">Pendente este mês</div>
    <div class="fw-bold fs-5 text-warning">{_ct_brl(pendente_mes - vencido_mes)}</div>
  </div></div>
  <div class="col-md-3"><div class="card p-3 text-center">
    <div class="text-muted small mb-1">Em atraso</div>
    <div class="fw-bold fs-5 text-danger">{_ct_brl(vencido_mes)}</div>
  </div></div>
</div>

<div class="card">
  <div class="card-body p-0">
    <table class="table table-hover mb-0">
      <thead class="table-light">
        <tr>
          <th>Cliente</th>
          <th>Contrato</th>
          <th class="text-end">Valor/mês</th>
          <th class="text-center">Vencimento</th>
          <th class="text-center">Início</th>
          <th class="text-center">Status</th>
          <th></th>
        </tr>
      </thead>
      <tbody>
"""
    for c in contratos:
        badge = {"ativo": "bg-success", "pausado": "bg-warning text-dark", "encerrado": "bg-secondary"}.get(c.status, "bg-secondary")
        email_warn = ' <span title="Sem e-mail — boleto não disponível" style="color:#dc3545;font-size:.8rem;">⚠</span>' if not c.email_cliente or not c.documento_cliente else ""
        html += f"""
        <tr>
          <td class="fw-semibold">{c.nome_cliente or '—'}{email_warn}</td>
          <td>{c.nome_contrato}</td>
          <td class="text-end">{_ct_brl(c.valor_cents)}</td>
          <td class="text-center">Dia {c.dia_vencimento}</td>
          <td class="text-center">{c.data_inicio or '—'}</td>
          <td class="text-center"><span class="badge {badge}">{c.status.capitalize()}</span></td>
          <td class="text-end">
            <a class="btn btn-sm btn-outline-secondary" href="/admin/financeiro/contratos/{c.id}/editar">Editar</a>
            <a class="btn btn-sm btn-outline-primary" href="/admin/financeiro/contratos/{c.id}/cobrancas">Cobranças</a>
          </td>
        </tr>"""
    if not contratos:
        html += '<tr><td colspan="7" class="text-center text-muted py-4">Nenhum contrato cadastrado. <a href="/admin/financeiro/contratos/novo">Criar o primeiro</a></td></tr>'

    html += """
      </tbody>
    </table>
  </div>
</div>
<div class="text-muted small mt-2">⚠ = cliente sem e-mail/CPF cadastrado (necessário para boleto)</div>
{% endblock %}"""

    TEMPLATES["_contratos_lista.html"] = html
    return render("_contratos_lista.html", request=request, context={
        "current_user": ctx.user, "current_company": ctx.company, "role": ctx.membership.role,
    })


@app.get("/admin/financeiro/contratos/novo", response_class=_HTML_ct)
@require_role({"admin", "equipe"})
async def financeiro_contratos_novo_get(request: _Req_ct, session=_Dep_ct(get_session)):
    ctx = get_tenant_context(request, session)
    if not ctx:
        return _RR_ct("/login", status_code=303)
    clientes = session.exec(
        _sel_ct(Client).where(Client.company_id == ctx.company.id).order_by(Client.name)
    ).all()
    html = _ct_form_html(clientes=clientes, contrato=None, erro=None)
    TEMPLATES["_contratos_form.html"] = html
    return render("_contratos_form.html", request=request, context={
        "current_user": ctx.user, "current_company": ctx.company, "role": ctx.membership.role,
    })


@app.post("/admin/financeiro/contratos/novo")
@require_role({"admin", "equipe"})
async def financeiro_contratos_novo_post(request: _Req_ct, session=_Dep_ct(get_session)):
    ctx = get_tenant_context(request, session)
    if not ctx:
        return _RR_ct("/login", status_code=303)
    form = dict(await request.form())
    try:
        valor_str = str(form.get("valor", "0")).replace("R$","").replace(".","").replace(",",".").strip()
        contrato = ContratoCliente(
            company_id        = ctx.company.id,
            client_id         = int(form["client_id"]) if form.get("client_id") and form["client_id"] != "0" else None,
            nome_cliente      = form.get("nome_cliente","").strip(),
            nome_contrato     = form.get("nome_contrato","").strip(),
            servicos          = form.get("servicos","").strip(),
            valor_cents       = int(float(valor_str) * 100),
            dia_vencimento    = int(form.get("dia_vencimento", 10)),
            data_inicio       = form.get("data_inicio",""),
            data_fim          = form.get("data_fim",""),
            status            = "ativo",
            observacao        = form.get("observacao","").strip(),
            email_cliente     = form.get("email_cliente","").strip(),
            documento_cliente = form.get("documento_cliente","").strip().replace(".","").replace("-","").replace("/",""),
        )
        if contrato.client_id:
            cl = session.get(Client, contrato.client_id)
            if cl:
                contrato.nome_cliente = cl.name
        session.add(contrato)
        session.commit()
        set_flash(request, "Contrato criado com sucesso!")
    except Exception as _e:
        set_flash(request, f"Erro: {_e}")
    return _RR_ct("/admin/financeiro/contratos", status_code=303)


@app.get("/admin/financeiro/contratos/{contrato_id}/editar", response_class=_HTML_ct)
@require_role({"admin", "equipe"})
async def financeiro_contratos_editar_get(contrato_id: int, request: _Req_ct, session=_Dep_ct(get_session)):
    ctx = get_tenant_context(request, session)
    if not ctx:
        return _RR_ct("/login", status_code=303)
    contrato = session.get(ContratoCliente, contrato_id)
    if not contrato or contrato.company_id != ctx.company.id:
        return _RR_ct("/admin/financeiro/contratos", status_code=303)
    clientes = session.exec(
        _sel_ct(Client).where(Client.company_id == ctx.company.id).order_by(Client.name)
    ).all()
    html = _ct_form_html(clientes=clientes, contrato=contrato, erro=None)
    TEMPLATES["_contratos_form.html"] = html
    return render("_contratos_form.html", request=request, context={
        "current_user": ctx.user, "current_company": ctx.company, "role": ctx.membership.role,
    })


@app.post("/admin/financeiro/contratos/{contrato_id}/editar")
@require_role({"admin", "equipe"})
async def financeiro_contratos_editar_post(contrato_id: int, request: _Req_ct, session=_Dep_ct(get_session)):
    ctx = get_tenant_context(request, session)
    if not ctx:
        return _RR_ct("/login", status_code=303)
    contrato = session.get(ContratoCliente, contrato_id)
    if not contrato or contrato.company_id != ctx.company.id:
        return _RR_ct("/admin/financeiro/contratos", status_code=303)
    form = dict(await request.form())
    try:
        valor_str = str(form.get("valor","0")).replace("R$","").replace(".","").replace(",",".").strip()
        contrato.client_id         = int(form["client_id"]) if form.get("client_id") and form["client_id"] != "0" else None
        contrato.nome_cliente      = form.get("nome_cliente","").strip()
        contrato.nome_contrato     = form.get("nome_contrato","").strip()
        contrato.servicos          = form.get("servicos","").strip()
        contrato.valor_cents       = int(float(valor_str) * 100)
        contrato.dia_vencimento    = int(form.get("dia_vencimento", 10))
        contrato.data_inicio       = form.get("data_inicio","")
        contrato.data_fim          = form.get("data_fim","")
        contrato.status            = form.get("status","ativo")
        contrato.observacao        = form.get("observacao","").strip()
        contrato.email_cliente     = form.get("email_cliente","").strip()
        contrato.documento_cliente = form.get("documento_cliente","").strip().replace(".","").replace("-","").replace("/","")
        contrato.updated_at        = _dt_ct.utcnow()
        if contrato.client_id:
            cl = session.get(Client, contrato.client_id)
            if cl:
                contrato.nome_cliente = cl.name
        session.add(contrato)
        session.commit()
        set_flash(request, "Contrato atualizado!")
    except Exception as _e:
        set_flash(request, f"Erro: {_e}")
    return _RR_ct("/admin/financeiro/contratos", status_code=303)


@app.get("/admin/financeiro/contratos/{contrato_id}/cobrancas", response_class=_HTML_ct)
@require_role({"admin", "equipe"})
async def financeiro_contrato_cobrancas(contrato_id: int, request: _Req_ct, session=_Dep_ct(get_session)):
    ctx = get_tenant_context(request, session)
    if not ctx:
        return _RR_ct("/login", status_code=303)
    contrato = session.get(ContratoCliente, contrato_id)
    if not contrato or contrato.company_id != ctx.company.id:
        return _RR_ct("/admin/financeiro/contratos", status_code=303)
    cobrancas = session.exec(
        _sel_ct(CobrancaMensal)
        .where(CobrancaMensal.contrato_id == contrato_id)
        .order_by(CobrancaMensal.competencia.desc())
    ).all()
    html = _ct_cobrancas_html(contrato=contrato, cobrancas=cobrancas)
    TEMPLATES["_contrato_cobrancas.html"] = html
    return render("_contrato_cobrancas.html", request=request, context={
        "current_user": ctx.user, "current_company": ctx.company, "role": ctx.membership.role,
    })


@app.get("/admin/financeiro/cobrancas", response_class=_HTML_ct)
@require_role({"admin", "equipe"})
async def financeiro_cobrancas_painel(request: _Req_ct, session=_Dep_ct(get_session)):
    ctx = get_tenant_context(request, session)
    if not ctx:
        return _RR_ct("/login", status_code=303)
    try:
        _ct_atualizar_vencidos(session)
    except Exception:
        pass

    mes           = request.query_params.get("mes", _ct_competencia_atual())
    status_filtro = request.query_params.get("status", "")

    q = _sel_ct(CobrancaMensal).where(CobrancaMensal.company_id == ctx.company.id)
    if mes:
        q = q.where(CobrancaMensal.competencia == mes)
    if status_filtro:
        q = q.where(CobrancaMensal.status == status_filtro)
    cobrancas = session.exec(q.order_by(CobrancaMensal.status, CobrancaMensal.nome_cliente)).all()

    total    = sum(c.valor_cents for c in cobrancas)
    recebido = sum(c.valor_pago_cents or c.valor_cents for c in cobrancas if c.status == "pago")
    pendente = sum(c.valor_cents for c in cobrancas if c.status == "pendente")
    vencido  = sum(c.valor_cents for c in cobrancas if c.status == "vencido")

    rows = ""
    for c in cobrancas:
        badge    = {"pendente":"bg-warning text-dark","pago":"bg-success","vencido":"bg-danger","cancelado":"bg-secondary"}.get(c.status,"bg-secondary")
        pago_str = _ct_brl(c.valor_pago_cents or c.valor_cents) if c.status == "pago" else "—"

        # Botão boleto: se já tem URL, exibe link; senão exibe botão gerar
        if c.boleto_url:
            boleto_btn = f'<a class="btn btn-sm btn-outline-info ms-1" href="{c.boleto_url}" target="_blank">📄 Boleto</a>'
        elif c.status in ("pendente", "vencido"):
            boleto_btn = f'<a href="/admin/financeiro/cobrancas/{c.id}/boleto-gerar" class="btn btn-sm btn-outline-info ms-1">Gerar boleto</a>'
        else:
            boleto_btn = ""

        acoes_pagar   = '' if c.status == 'pago' else f'<button class="btn btn-sm btn-success" onclick="marcarPago({c.id}, {c.valor_cents})">✓ Pago</button>'
        acoes_cancelar= '' if c.status == 'cancelado' else f'<button class="btn btn-sm btn-outline-secondary ms-1" onclick="cancelar({c.id})">✕</button>'

        rows += f"""
        <tr>
          <td>{c.competencia}</td>
          <td class="fw-semibold">{c.nome_cliente}</td>
          <td>{c.nome_contrato}</td>
          <td class="text-end">{_ct_brl(c.valor_cents)}</td>
          <td class="text-center">{c.data_vencimento}</td>
          <td class="text-center"><span class="badge {badge}">{c.status.capitalize()}</span></td>
          <td class="text-end text-success">{pago_str}</td>
          <td class="text-center text-nowrap">{acoes_pagar}{boleto_btn}{acoes_cancelar}</td>
        </tr>"""

    html = f"""{{% extends "base.html" %}}
{{% block content %}}
<div class="d-flex justify-content-between align-items-start flex-wrap gap-2 mb-3">
  <div>
    <h4 class="mb-0">Cobranças Mensais</h4>
    <div class="text-muted small">Inadimplência e controle de recebimentos</div>
  </div>
  <div class="d-flex gap-2 flex-wrap">
    <a class="btn btn-outline-secondary" href="/admin/financeiro/contratos">← Contratos</a>
    <button class="btn btn-outline-primary" onclick="gerarMes()">⚡ Gerar cobranças do mês</button>
  </div>
</div>

<div class="row g-3 mb-4">
  <div class="col-md-3"><div class="card p-3 text-center">
    <div class="text-muted small mb-1">Total do período</div>
    <div class="fw-bold fs-5">{_ct_brl(total)}</div>
  </div></div>
  <div class="col-md-3"><div class="card p-3 text-center">
    <div class="text-muted small mb-1">Recebido</div>
    <div class="fw-bold fs-5 text-success">{_ct_brl(recebido)}</div>
  </div></div>
  <div class="col-md-3"><div class="card p-3 text-center">
    <div class="text-muted small mb-1">Pendente</div>
    <div class="fw-bold fs-5 text-warning">{_ct_brl(pendente)}</div>
  </div></div>
  <div class="col-md-3"><div class="card p-3 text-center">
    <div class="text-muted small mb-1">Em atraso</div>
    <div class="fw-bold fs-5 text-danger">{_ct_brl(vencido)}</div>
  </div></div>
</div>

<div class="card mb-3">
  <div class="card-body">
    <form class="row g-2" method="get">
      <div class="col-md-3">
        <input type="month" name="mes" class="form-control" value="{mes}">
      </div>
      <div class="col-md-3">
        <select name="status" class="form-select">
          <option value="">Todos os status</option>
          <option value="pendente" {"selected" if status_filtro=="pendente" else ""}>Pendente</option>
          <option value="vencido"  {"selected" if status_filtro=="vencido"  else ""}>Vencido</option>
          <option value="pago"     {"selected" if status_filtro=="pago"     else ""}>Pago</option>
          <option value="cancelado"{"selected" if status_filtro=="cancelado" else ""}>Cancelado</option>
        </select>
      </div>
      <div class="col-auto">
        <button class="btn btn-outline-primary" type="submit">Filtrar</button>
      </div>
    </form>
  </div>
</div>

<div class="card">
  <div class="card-body p-0">
    <table class="table table-hover mb-0">
      <thead class="table-light">
        <tr>
          <th>Competência</th>
          <th>Cliente</th>
          <th>Contrato</th>
          <th class="text-end">Valor</th>
          <th class="text-center">Vencimento</th>
          <th class="text-center">Status</th>
          <th class="text-end">Pago</th>
          <th class="text-center">Ações</th>
        </tr>
      </thead>
      <tbody>{rows if rows else '<tr><td colspan="8" class="text-center text-muted py-4">Nenhuma cobrança encontrada</td></tr>'}</tbody>
    </table>
  </div>
</div>

<!-- Modal Marcar Pago -->
<div class="modal fade" id="modalPago" tabindex="-1">
  <div class="modal-dialog">
    <div class="modal-content">
      <div class="modal-header"><h5 class="modal-title">Registrar Pagamento</h5>
        <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
      </div>
      <div class="modal-body">
        <div class="mb-3">
          <label class="form-label">Valor recebido (R$)</label>
          <input type="number" id="valorPago" class="form-control" step="0.01">
        </div>
        <div class="mb-3">
          <label class="form-label">Data do pagamento</label>
          <input type="date" id="dataPagamento" class="form-control" value="{_ct_hoje()}">
        </div>
        <div class="mb-3">
          <label class="form-label">Forma de pagamento</label>
          <select id="formaPagamento" class="form-select">
            <option value="boleto">Boleto</option>
            <option value="pix">PIX</option>
            <option value="transferencia">Transferência</option>
            <option value="cartao">Cartão</option>
          </select>
        </div>
        <div class="mb-3">
          <label class="form-label">Observação</label>
          <input type="text" id="obsPagamento" class="form-control" placeholder="Opcional">
        </div>
      </div>
      <div class="modal-footer">
        <button class="btn btn-secondary" data-bs-dismiss="modal">Cancelar</button>
        <button class="btn btn-success" onclick="confirmarPago()">Confirmar Pagamento</button>
      </div>
    </div>
  </div>
</div>

<script>
let _cobrancaId = null;
function marcarPago(id, valorCents) {{
  _cobrancaId = id;
  document.getElementById('valorPago').value = (valorCents / 100).toFixed(2);
  new bootstrap.Modal(document.getElementById('modalPago')).show();
}}
async function confirmarPago() {{
  if (!_cobrancaId) return;
  const body = {{
    valor_pago: parseFloat(document.getElementById('valorPago').value),
    data_pagamento: document.getElementById('dataPagamento').value,
    forma_pagamento: document.getElementById('formaPagamento').value,
    observacao: document.getElementById('obsPagamento').value,
  }};
  const r = await fetch('/admin/financeiro/cobrancas/' + _cobrancaId + '/pagar', {{
    method: 'POST', headers: {{'Content-Type':'application/json'}}, body: JSON.stringify(body)
  }});
  if (r.ok) location.reload();
  else alert('Erro ao registrar pagamento');
}}
async function cancelar(id) {{
  if (!confirm('Cancelar esta cobrança?')) return;
  const r = await fetch('/admin/financeiro/cobrancas/' + id + '/cancelar', {{method: 'POST'}});
  if (r.ok) location.reload();
}}
async function gerarMes() {{
  const r = await fetch('/admin/financeiro/cobrancas/gerar', {{method: 'POST'}});
  const d = await r.json();
  alert(d.message || 'Gerado!');
  location.reload();
}}
async function gerarBoleto(btn, id) {{
  btn.disabled = true;
  btn.textContent = 'Gerando...';
  try {{
    const r = await fetch('/admin/financeiro/cobrancas/' + id + '/boleto', {{method: 'POST'}});
    let d = {{}};
    try {{ d = await r.json(); }} catch(e) {{ d = {{error: 'Resposta inválida do servidor'}}; }}
    if (d.boleto_url) {{
      window.open(d.boleto_url, '_blank');
      location.reload();
    }} else {{
      alert('Erro ao gerar boleto:\n' + (d.error || 'Tente novamente'));
      btn.disabled = false;
      btn.textContent = 'Gerar boleto';
    }}
  }} catch(e) {{
    alert('Erro de comunicação: ' + e.message);
    btn.disabled = false;
    btn.textContent = 'Gerar boleto';
  }}
}}
</script>
{{% endblock %}}"""

    TEMPLATES["_cobrancas_painel.html"] = html
    return render("_cobrancas_painel.html", request=request, context={
        "current_user": ctx.user, "current_company": ctx.company, "role": ctx.membership.role,
    })


@app.post("/admin/financeiro/cobrancas/{cobranca_id}/pagar")
@require_role({"admin", "equipe"})
async def financeiro_cobranca_pagar(cobranca_id: int, request: _Req_ct, session=_Dep_ct(get_session)):
    ctx = get_tenant_context(request, session)
    if not ctx:
        return _JR_ct({"error": "não autenticado"}, status_code=401)
    cobranca = session.get(CobrancaMensal, cobranca_id)
    if not cobranca or cobranca.company_id != ctx.company.id:
        return _JR_ct({"error": "não encontrado"}, status_code=404)
    try:
        body = await request.json()
        cobranca.status           = "pago"
        cobranca.valor_pago_cents = int(float(body.get("valor_pago", cobranca.valor_cents / 100)) * 100)
        cobranca.data_pagamento   = body.get("data_pagamento", _ct_hoje())
        cobranca.forma_pagamento  = body.get("forma_pagamento", "")
        cobranca.observacao       = body.get("observacao", "")
        cobranca.updated_at       = _dt_ct.utcnow()
        session.add(cobranca)
        session.commit()
        _ct_sync_entry(session, cobranca, user_id=ctx.user.id)
        return _JR_ct({"ok": True})
    except Exception as _e:
        return _JR_ct({"error": str(_e)}, status_code=500)


@app.post("/admin/financeiro/cobrancas/{cobranca_id}/cancelar")
@require_role({"admin", "equipe"})
async def financeiro_cobranca_cancelar(cobranca_id: int, request: _Req_ct, session=_Dep_ct(get_session)):
    ctx = get_tenant_context(request, session)
    if not ctx:
        return _JR_ct({"error": "não autenticado"}, status_code=401)
    cobranca = session.get(CobrancaMensal, cobranca_id)
    if not cobranca or cobranca.company_id != ctx.company.id:
        return _JR_ct({"error": "não encontrado"}, status_code=404)
    cobranca.status     = "cancelado"
    cobranca.updated_at = _dt_ct.utcnow()
    session.add(cobranca)
    session.commit()
    return _JR_ct({"ok": True})


@app.post("/admin/financeiro/cobrancas/gerar")
@require_role({"admin", "equipe"})
async def financeiro_cobrancas_gerar(request: _Req_ct, session=_Dep_ct(get_session)):
    ctx = get_tenant_context(request, session)
    if not ctx:
        return _JR_ct({"error": "não autenticado"}, status_code=401)
    try:
        n = _ct_gerar_cobrancas_mes(session, ctx.company.id)
        return _JR_ct({"ok": True, "message": f"{n} cobrança(s) gerada(s) para {_ct_competencia_atual()}"})
    except Exception as _e:
        return _JR_ct({"error": str(_e)}, status_code=500)


@app.post("/admin/financeiro/cobrancas/{cobranca_id}/boleto")
@require_role({"admin", "equipe"})
async def financeiro_cobranca_gerar_boleto_json(cobranca_id: int, request: _Req_ct, session=_Dep_ct(get_session)):
    """API JSON — mantida para compatibilidade."""
    ctx = get_tenant_context(request, session)
    if not ctx:
        return _JR_ct({"error": "não autenticado"}, status_code=401)
    cobranca = session.get(CobrancaMensal, cobranca_id)
    if not cobranca or cobranca.company_id != ctx.company.id:
        return _JR_ct({"error": "não encontrado"}, status_code=404)
    if cobranca.boleto_url:
        return _JR_ct({"ok": True, "boleto_url": cobranca.boleto_url})
    contrato = session.get(ContratoCliente, cobranca.contrato_id)
    if not contrato:
        return _JR_ct({"error": "Contrato não encontrado"}, status_code=404)
    try:
        dados = _ct_mp_gerar_boleto(cobranca, contrato, session)
        cobranca.mp_payment_id = dados["mp_payment_id"]
        cobranca.boleto_url    = dados["boleto_url"]
        cobranca.boleto_codigo = dados["boleto_codigo"]
        cobranca.updated_at    = _dt_ct.utcnow()
        session.add(cobranca)
        session.commit()
        return _JR_ct({"ok": True, "boleto_url": cobranca.boleto_url})
    except Exception as _e:
        print(f"[boleto] erro cobranca {cobranca_id}: {_e}")
        return _JR_ct({"error": str(_e)}, status_code=422)


@app.get("/admin/financeiro/cobrancas/{cobranca_id}/boleto-gerar")
@require_role({"admin", "equipe"})
async def financeiro_cobranca_gerar_boleto_form(cobranca_id: int, request: _Req_ct, session=_Dep_ct(get_session)):
    """Form POST — gera boleto e redireciona para o PDF ou volta com erro."""
    ctx = get_tenant_context(request, session)
    if not ctx:
        return _RR_ct("/login", status_code=303)
    cobranca = session.get(CobrancaMensal, cobranca_id)
    if not cobranca or cobranca.company_id != ctx.company.id:
        set_flash(request, "Cobrança não encontrada.")
        return _RR_ct("/admin/financeiro/cobrancas", status_code=303)
    if cobranca.boleto_url:
        return _RR_ct(cobranca.boleto_url, status_code=303)
    contrato = session.get(ContratoCliente, cobranca.contrato_id)
    if not contrato:
        set_flash(request, "Contrato não encontrado.")
        return _RR_ct("/admin/financeiro/cobrancas", status_code=303)
    try:
        dados = _ct_mp_gerar_boleto(cobranca, contrato, session)
        cobranca.mp_payment_id = dados["mp_payment_id"]
        cobranca.boleto_url    = dados["boleto_url"]
        cobranca.boleto_codigo = dados["boleto_codigo"]
        cobranca.updated_at    = _dt_ct.utcnow()
        session.add(cobranca)
        session.commit()
        print(f"[boleto] ✅ cobranca {cobranca_id} — {cobranca.boleto_url}")

        # Envia boleto por e-mail para o cliente + cópia para o escritório
        try:
            _ct_enviar_email_boleto(cobranca, contrato, session)
        except Exception as _em:
            print(f"[boleto] email não enviado: {_em}")

        return _RR_ct(cobranca.boleto_url, status_code=303)
    except Exception as _e:
        print(f"[boleto] erro cobranca {cobranca_id}: {_e}")
        set_flash(request, f"Erro ao gerar boleto: {_e}")
        return _RR_ct("/admin/financeiro/cobrancas", status_code=303)


# ── Webhook Mercado Pago — confirmação automática ─────────────────────────────

@app.post("/webhooks/mercadopago")
async def webhook_mercadopago(request: _Req_ct, session=_Dep_ct(get_session)):
    """
    Recebe notificações do MP. Quando pagamento é aprovado,
    marca a CobrancaMensal correspondente como paga automaticamente.
    Configurar URL no MP: https://app.maffezzollicapital.com.br/webhooks/mercadopago
    """
    try:
        body  = await request.json()
        topic = body.get("type") or request.query_params.get("topic", "")
        mp_id = str(body.get("data", {}).get("id") or request.query_params.get("id", ""))

        if topic not in ("payment", "merchant_order") or not mp_id:
            return _JR_ct({"ok": True})

        # Busca detalhes do pagamento no MP
        try:
            payment = _mp_request("GET", f"/v1/payments/{mp_id}")
        except Exception as _e:
            print(f"[webhook_mp] erro ao buscar pagamento {mp_id}: {_e}")
            return _JR_ct({"ok": True})

        status_mp = payment.get("status", "")
        if status_mp != "approved":
            return _JR_ct({"ok": True})

        # Localiza a cobrança pelo mp_payment_id
        cobranca = session.exec(
            _sel_ct(CobrancaMensal).where(CobrancaMensal.mp_payment_id == mp_id)
        ).first()

        if cobranca and cobranca.status != "pago":
            valor_pago = int(round(payment.get("transaction_amount", 0) * 100))
            cobranca.status           = "pago"
            cobranca.valor_pago_cents = valor_pago or cobranca.valor_cents
            cobranca.data_pagamento   = _ct_hoje()
            cobranca.forma_pagamento  = "boleto"
            cobranca.observacao       = f"Confirmado automaticamente via webhook MP (id={mp_id})"
            cobranca.updated_at       = _dt_ct.utcnow()
            session.add(cobranca)
            session.commit()
            _ct_sync_entry(session, cobranca)
            print(f"[webhook_mp] ✅ Cobrança {cobranca.id} marcada como paga via MP {mp_id}")

        return _JR_ct({"ok": True})
    except Exception as _e:
        print(f"[webhook_mp] erro: {_e}")
        return _JR_ct({"ok": True})  # sempre retorna 200 para o MP não retentar


# ── Templates HTML auxiliares ─────────────────────────────────────────────────

def _ct_form_html(clientes, contrato, erro):
    titulo = "Editar Contrato" if contrato else "Novo Contrato"
    action = f"/admin/financeiro/contratos/{contrato.id}/editar" if contrato else "/admin/financeiro/contratos/novo"
    c = contrato

    opts_clientes = '<option value="0">— Nenhum (cliente externo) —</option>'
    for cl in clientes:
        sel = "selected" if c and c.client_id == cl.id else ""
        opts_clientes += f'<option value="{cl.id}" {sel}>{cl.name}</option>'

    opts_status = ""
    for s in ["ativo", "pausado", "encerrado"]:
        sel = "selected" if c and c.status == s else ("selected" if not c and s == "ativo" else "")
        opts_status += f'<option value="{s}" {sel}>{s.capitalize()}</option>'

    opts_dia = ""
    for d in range(1, 29):
        sel = "selected" if c and c.dia_vencimento == d else ("selected" if not c and d == 10 else "")
        opts_dia += f'<option value="{d}" {sel}>{d}</option>'

    valor_fmt  = f"{(c.valor_cents/100):.2f}".replace(".", ",") if c else ""
    email_val  = (c.email_cliente  or "") if c else ""
    doc_val    = (c.documento_cliente or "") if c else ""

    return f"""{{% extends "base.html" %}}
{{% block content %}}
<div class="d-flex justify-content-between align-items-center mb-3">
  <h4 class="mb-0">{titulo}</h4>
  <a class="btn btn-outline-secondary" href="/admin/financeiro/contratos">← Voltar</a>
</div>
{"" if not erro else f'<div class="alert alert-danger">{erro}</div>'}
<div class="card p-4">
  <form method="post" action="{action}">
    <div class="row g-3">
      <div class="col-md-6">
        <label class="form-label fw-semibold">Cliente da plataforma</label>
        <select name="client_id" class="form-select" onchange="preencherNome(this)">
          {opts_clientes}
        </select>
        <div class="form-text">Deixe em branco para clientes externos</div>
      </div>
      <div class="col-md-6">
        <label class="form-label fw-semibold">Nome do cliente <span class="text-danger">*</span></label>
        <input type="text" name="nome_cliente" class="form-control" required
               value="{c.nome_cliente if c else ''}" id="nomeClienteInput">
      </div>
      <div class="col-md-8">
        <label class="form-label fw-semibold">Nome do contrato <span class="text-danger">*</span></label>
        <input type="text" name="nome_contrato" class="form-control" required
               placeholder="Ex: Consultoria Financeira Mensal"
               value="{c.nome_contrato if c else ''}">
      </div>
      <div class="col-md-4">
        <label class="form-label fw-semibold">Status</label>
        <select name="status" class="form-select">{opts_status}</select>
      </div>
      <div class="col-12">
        <label class="form-label fw-semibold">Descrição dos serviços</label>
        <textarea name="servicos" class="form-control" rows="2"
                  placeholder="Descreva os serviços incluídos no contrato">{c.servicos if c else ''}</textarea>
      </div>
      <div class="col-md-4">
        <label class="form-label fw-semibold">Valor mensal (R$) <span class="text-danger">*</span></label>
        <input type="text" name="valor" class="form-control" required
               placeholder="1.500,00" value="{valor_fmt}">
      </div>
      <div class="col-md-4">
        <label class="form-label fw-semibold">Dia de vencimento</label>
        <select name="dia_vencimento" class="form-select">{opts_dia}</select>
      </div>
      <div class="col-md-4">
        <label class="form-label fw-semibold">Data de início</label>
        <input type="date" name="data_inicio" class="form-control"
               value="{c.data_inicio if c else ''}">
      </div>
      <div class="col-md-4">
        <label class="form-label fw-semibold">Data de encerramento</label>
        <input type="date" name="data_fim" class="form-control"
               value="{c.data_fim if c else ''}">
        <div class="form-text">Vazio = prazo indeterminado</div>
      </div>

      <div class="col-12"><hr class="my-1"><div class="fw-semibold small text-muted mb-1">Dados para emissão de boleto (Mercado Pago)</div></div>
      <div class="col-md-6">
        <label class="form-label fw-semibold">E-mail do cliente</label>
        <input type="email" name="email_cliente" class="form-control"
               placeholder="cliente@email.com" value="{email_val}">
      </div>
      <div class="col-md-6">
        <label class="form-label fw-semibold">CPF / CNPJ (só números)</label>
        <input type="text" name="documento_cliente" class="form-control"
               placeholder="00000000000" value="{doc_val}" maxlength="18">
      </div>

      <div class="col-12">
        <label class="form-label fw-semibold">Observações</label>
        <textarea name="observacao" class="form-control" rows="2">{c.observacao if c else ''}</textarea>
      </div>
      <div class="col-12 d-flex justify-content-end gap-2">
        <a class="btn btn-outline-secondary" href="/admin/financeiro/contratos">Cancelar</a>
        <button type="submit" class="btn btn-primary">{"Salvar alterações" if contrato else "Criar contrato"}</button>
      </div>
    </div>
  </form>
</div>
<script>
const _clienteNomes = {{{",".join(f'"{cl.id}":"{cl.name}"' for cl in clientes)}}};
function preencherNome(sel) {{
  const nome = _clienteNomes[sel.value] || '';
  if (nome) document.getElementById('nomeClienteInput').value = nome;
}}
</script>
{{% endblock %}}"""


def _ct_cobrancas_html(contrato, cobrancas):
    rows = ""
    for c in cobrancas:
        badge    = {"pendente":"bg-warning text-dark","pago":"bg-success","vencido":"bg-danger","cancelado":"bg-secondary"}.get(c.status,"bg-secondary")
        pago_str = _ct_brl(c.valor_pago_cents or c.valor_cents) if c.status == "pago" else "—"
        boleto_cell = ""
        if c.boleto_url:
            boleto_cell = f'<a href="{c.boleto_url}" target="_blank" class="btn btn-sm btn-outline-info">📄 Ver</a>'
        rows += f"""
        <tr>
          <td>{c.competencia}</td>
          <td class="text-end">{_ct_brl(c.valor_cents)}</td>
          <td class="text-center">{c.data_vencimento}</td>
          <td class="text-center"><span class="badge {badge}">{c.status.capitalize()}</span></td>
          <td class="text-end text-success">{pago_str}</td>
          <td class="text-center">{c.data_pagamento or '—'}</td>
          <td>{c.forma_pagamento or '—'}</td>
          <td class="text-center">{boleto_cell}</td>
        </tr>"""

    total_pago = sum(c.valor_pago_cents or c.valor_cents for c in cobrancas if c.status == "pago")
    return f"""{{% extends "base.html" %}}
{{% block content %}}
<div class="d-flex justify-content-between align-items-center mb-3">
  <div>
    <h4 class="mb-0">{contrato.nome_cliente} — {contrato.nome_contrato}</h4>
    <div class="text-muted small">{_ct_brl(contrato.valor_cents)}/mês · Vence dia {contrato.dia_vencimento}</div>
  </div>
  <a class="btn btn-outline-secondary" href="/admin/financeiro/contratos">← Contratos</a>
</div>
<div class="card mb-3 p-3">
  <div class="text-muted small mb-1">Total recebido</div>
  <div class="fw-bold fs-5 text-success">{_ct_brl(total_pago)}</div>
</div>
<div class="card">
  <div class="card-body p-0">
    <table class="table table-hover mb-0">
      <thead class="table-light">
        <tr>
          <th>Competência</th>
          <th class="text-end">Valor</th>
          <th class="text-center">Vencimento</th>
          <th class="text-center">Status</th>
          <th class="text-end">Pago</th>
          <th class="text-center">Data pag.</th>
          <th>Forma</th>
          <th class="text-center">Boleto</th>
        </tr>
      </thead>
      <tbody>{rows if rows else '<tr><td colspan="8" class="text-center text-muted py-4">Nenhuma cobrança gerada ainda</td></tr>'}</tbody>
    </table>
  </div>
</div>
{{% endblock %}}"""

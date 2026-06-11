# ============================================================================
# MÓDULO — Contratos de Clientes e Cobranças Mensais
# /admin/financeiro/contratos  (Fase 1 — sem boleto/NF)
# ============================================================================

import json         as _json_ct
from datetime       import date as _date_ct, datetime as _dt_ct, timedelta as _td_ct
from typing         import Optional as _Opt_ct
from sqlmodel       import Field as _F_ct, SQLModel as _SM_ct, select as _sel_ct
from fastapi        import Request as _Req_ct, Depends as _Dep_ct
from fastapi.responses import HTMLResponse as _HTML_ct, RedirectResponse as _RR_ct


# ── Modelos ───────────────────────────────────────────────────────────────────

class ContratoCliente(_SM_ct, table=True):
    __tablename__  = "contrato_cliente"
    __table_args__ = {"extend_existing": True}
    id:              _Opt_ct[int] = _F_ct(default=None, primary_key=True)
    company_id:      int          = _F_ct(index=True)
    client_id:       _Opt_ct[int] = _F_ct(default=None, index=True)  # None = contrato avulso
    nome_cliente:    str          = _F_ct(default="")     # nome livre (pode ser pessoa física)
    nome_contrato:   str          = _F_ct(default="")     # ex: "Consultoria Financeira Mensal"
    servicos:        str          = _F_ct(default="")     # descrição dos serviços
    valor_cents:     int          = _F_ct(default=0)      # valor mensal em centavos
    dia_vencimento:  int          = _F_ct(default=10)     # dia do mês (1-28)
    data_inicio:     str          = _F_ct(default="")     # YYYY-MM-DD
    data_fim:        str          = _F_ct(default="")     # YYYY-MM-DD ou vazio = indefinido
    status:          str          = _F_ct(default="ativo")# ativo | pausado | encerrado
    observacao:      str          = _F_ct(default="")
    created_at:      _dt_ct       = _F_ct(default_factory=lambda: _dt_ct.utcnow())
    updated_at:      _dt_ct       = _F_ct(default_factory=lambda: _dt_ct.utcnow())


class CobrancaMensal(_SM_ct, table=True):
    __tablename__  = "cobranca_mensal"
    __table_args__ = {"extend_existing": True}
    id:              _Opt_ct[int] = _F_ct(default=None, primary_key=True)
    company_id:      int          = _F_ct(index=True)
    contrato_id:     int          = _F_ct(index=True)
    client_id:       _Opt_ct[int] = _F_ct(default=None, index=True)
    nome_cliente:    str          = _F_ct(default="")
    nome_contrato:   str          = _F_ct(default="")
    competencia:     str          = _F_ct(default="")     # "2026-06"
    data_vencimento: str          = _F_ct(default="")     # YYYY-MM-DD
    valor_cents:     int          = _F_ct(default=0)
    status:          str          = _F_ct(default="pendente") # pendente | pago | vencido | cancelado
    data_pagamento:  str          = _F_ct(default="")
    valor_pago_cents:_Opt_ct[int] = _F_ct(default=None)
    forma_pagamento: str          = _F_ct(default="")     # pix | boleto | transferencia | cartao
    observacao:      str          = _F_ct(default="")
    nf_numero:       str          = _F_ct(default="")     # preenchido na Fase 3
    boleto_url:      str          = _F_ct(default="")     # preenchido na Fase 2
    created_at:      _dt_ct       = _F_ct(default_factory=lambda: _dt_ct.utcnow())
    updated_at:      _dt_ct       = _F_ct(default_factory=lambda: _dt_ct.utcnow())


# ── Criação de tabelas ────────────────────────────────────────────────────────

try:
    for _tbl_ct in (ContratoCliente.__table__, CobrancaMensal.__table__):
        _tbl_ct.create(engine, checkfirst=True)
    print("[contratos] ✅ Tabelas OK")
except Exception as _e_ct:
    print(f"[contratos] Tabelas: {_e_ct}")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _ct_brl(cents: int) -> str:
    v = abs(cents) / 100
    return f"R$ {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

def _ct_hoje() -> str:
    return _date_ct.today().isoformat()

def _ct_competencia_atual() -> str:
    return _date_ct.today().strftime("%Y-%m")

def _ct_vencimento(contrato: ContratoCliente, competencia: str) -> str:
    """Calcula a data de vencimento para uma competência YYYY-MM."""
    ano, mes = int(competencia[:4]), int(competencia[5:7])
    dia = min(contrato.dia_vencimento, 28)
    return f"{ano:04d}-{mes:02d}-{dia:02d}"

def _ct_atualizar_vencidos(session):
    """Marca como vencido cobranças pendentes com data passada."""
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
    """
    Gera CobrancaMensal para todos os contratos ativos que ainda não
    têm cobrança para a competência informada.
    Chamado automaticamente no acesso ao painel e no início de cada mês.
    """
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
        # Verifica se contrato já iniciou
        if contrato.data_inicio and contrato.data_inicio[:7] > competencia:
            continue
        # Verifica se contrato já encerrou
        if contrato.data_fim and contrato.data_fim[:7] < competencia:
            continue
        # Verifica se já existe cobrança para esta competência
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
    return geradas


# ── Rotas ─────────────────────────────────────────────────────────────────────

@app.get("/admin/financeiro/contratos", response_class=_HTML_ct)
@require_admin
async def financeiro_contratos_lista(request: _Req_ct, session=_Dep_ct(get_session)):
    ctx = get_tenant_context(request, session)
    if not ctx:
        return _RR_ct("/login", status_code=303)

    # Gera cobranças do mês atual automaticamente
    try:
        _ct_gerar_cobrancas_mes(session, ctx.company.id)
        _ct_atualizar_vencidos(session)
    except Exception as _e:
        print(f"[contratos] auto-gerar: {_e}")

    contratos = session.exec(
        _sel_ct(ContratoCliente).where(ContratoCliente.company_id == ctx.company.id)
        .order_by(ContratoCliente.status, ContratoCliente.nome_cliente)
    ).all()

    # KPIs
    cobrancas_mes = session.exec(
        _sel_ct(CobrancaMensal).where(
            CobrancaMensal.company_id == ctx.company.id,
            CobrancaMensal.competencia == _ct_competencia_atual(),
        )
    ).all()
    total_mensal   = sum(c.valor_cents for c in contratos if c.status == "ativo")
    pendente_mes   = sum(c.valor_cents for c in cobrancas_mes if c.status in ("pendente", "vencido"))
    recebido_mes   = sum(c.valor_pago_cents or c.valor_cents for c in cobrancas_mes if c.status == "pago")
    vencido_mes    = sum(c.valor_cents for c in cobrancas_mes if c.status == "vencido")

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
        html += f"""
        <tr>
          <td class="fw-semibold">{c.nome_cliente or '—'}</td>
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
{% endblock %}"""

    TEMPLATES["_contratos_lista.html"] = html
    return render("_contratos_lista.html", request=request, context={
        "current_user": ctx.user, "current_company": ctx.company, "role": ctx.membership.role,
    })


@app.get("/admin/financeiro/contratos/novo", response_class=_HTML_ct)
@require_admin
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
@require_admin
async def financeiro_contratos_novo_post(request: _Req_ct, session=_Dep_ct(get_session)):
    ctx = get_tenant_context(request, session)
    if not ctx:
        return _RR_ct("/login", status_code=303)
    form = dict(await request.form())
    try:
        valor_str = str(form.get("valor", "0")).replace("R$","").replace(".","").replace(",",".").strip()
        contrato = ContratoCliente(
            company_id     = ctx.company.id,
            client_id      = int(form["client_id"]) if form.get("client_id") and form["client_id"] != "0" else None,
            nome_cliente   = form.get("nome_cliente","").strip(),
            nome_contrato  = form.get("nome_contrato","").strip(),
            servicos       = form.get("servicos","").strip(),
            valor_cents    = int(float(valor_str) * 100),
            dia_vencimento = int(form.get("dia_vencimento", 10)),
            data_inicio    = form.get("data_inicio",""),
            data_fim       = form.get("data_fim",""),
            status         = "ativo",
            observacao     = form.get("observacao","").strip(),
        )
        # Se selecionou cliente da plataforma, preenche nome automaticamente
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
@require_admin
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
@require_admin
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
        contrato.client_id      = int(form["client_id"]) if form.get("client_id") and form["client_id"] != "0" else None
        contrato.nome_cliente   = form.get("nome_cliente","").strip()
        contrato.nome_contrato  = form.get("nome_contrato","").strip()
        contrato.servicos       = form.get("servicos","").strip()
        contrato.valor_cents    = int(float(valor_str) * 100)
        contrato.dia_vencimento = int(form.get("dia_vencimento", 10))
        contrato.data_inicio    = form.get("data_inicio","")
        contrato.data_fim       = form.get("data_fim","")
        contrato.status         = form.get("status","ativo")
        contrato.observacao     = form.get("observacao","").strip()
        contrato.updated_at     = _dt_ct.utcnow()
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
@require_admin
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
@require_admin
async def financeiro_cobrancas_painel(request: _Req_ct, session=_Dep_ct(get_session)):
    ctx = get_tenant_context(request, session)
    if not ctx:
        return _RR_ct("/login", status_code=303)

    try:
        _ct_atualizar_vencidos(session)
    except Exception:
        pass

    mes  = request.query_params.get("mes", _ct_competencia_atual())
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
        badge = {"pendente":"bg-warning text-dark","pago":"bg-success","vencido":"bg-danger","cancelado":"bg-secondary"}.get(c.status,"bg-secondary")
        pago_str = _ct_brl(c.valor_pago_cents or c.valor_cents) if c.status == "pago" else "—"
        rows += f"""
        <tr>
          <td>{c.competencia}</td>
          <td class="fw-semibold">{c.nome_cliente}</td>
          <td>{c.nome_contrato}</td>
          <td class="text-end">{_ct_brl(c.valor_cents)}</td>
          <td class="text-center">{c.data_vencimento}</td>
          <td class="text-center"><span class="badge {badge}">{c.status.capitalize()}</span></td>
          <td class="text-end text-success">{pago_str}</td>
          <td class="text-center">
            {"" if c.status == "pago" else f'<button class="btn btn-sm btn-success" onclick="marcarPago({c.id}, {c.valor_cents})">✓ Pago</button>'}
            {"" if c.status == "cancelado" else f'<button class="btn btn-sm btn-outline-secondary ms-1" onclick="cancelar({c.id})">✕</button>'}
          </td>
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
            <option value="pix">PIX</option>
            <option value="boleto">Boleto</option>
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
</script>
{{% endblock %}}"""

    TEMPLATES["_cobrancas_painel.html"] = html
    return render("_cobrancas_painel.html", request=request, context={
        "current_user": ctx.user, "current_company": ctx.company, "role": ctx.membership.role,
    })


@app.post("/admin/financeiro/cobrancas/{cobranca_id}/pagar")
@require_admin
async def financeiro_cobranca_pagar(cobranca_id: int, request: _Req_ct, session=_Dep_ct(get_session)):
    from fastapi.responses import JSONResponse as _JR
    ctx = get_tenant_context(request, session)
    if not ctx:
        return _JR({"error": "não autenticado"}, status_code=401)
    cobranca = session.get(CobrancaMensal, cobranca_id)
    if not cobranca or cobranca.company_id != ctx.company.id:
        return _JR({"error": "não encontrado"}, status_code=404)
    try:
        body = await request.json()
        cobranca.status          = "pago"
        cobranca.valor_pago_cents = int(float(body.get("valor_pago", cobranca.valor_cents / 100)) * 100)
        cobranca.data_pagamento  = body.get("data_pagamento", _ct_hoje())
        cobranca.forma_pagamento = body.get("forma_pagamento", "")
        cobranca.observacao      = body.get("observacao", "")
        cobranca.updated_at      = _dt_ct.utcnow()
        session.add(cobranca)
        session.commit()
        return _JR({"ok": True})
    except Exception as _e:
        return _JR({"error": str(_e)}, status_code=500)


@app.post("/admin/financeiro/cobrancas/{cobranca_id}/cancelar")
@require_admin
async def financeiro_cobranca_cancelar(cobranca_id: int, request: _Req_ct, session=_Dep_ct(get_session)):
    from fastapi.responses import JSONResponse as _JR
    ctx = get_tenant_context(request, session)
    if not ctx:
        return _JR({"error": "não autenticado"}, status_code=401)
    cobranca = session.get(CobrancaMensal, cobranca_id)
    if not cobranca or cobranca.company_id != ctx.company.id:
        return _JR({"error": "não encontrado"}, status_code=404)
    cobranca.status     = "cancelado"
    cobranca.updated_at = _dt_ct.utcnow()
    session.add(cobranca)
    session.commit()
    return _JR({"ok": True})


@app.post("/admin/financeiro/cobrancas/gerar")
@require_admin
async def financeiro_cobrancas_gerar(request: _Req_ct, session=_Dep_ct(get_session)):
    from fastapi.responses import JSONResponse as _JR
    ctx = get_tenant_context(request, session)
    if not ctx:
        return _JR({"error": "não autenticado"}, status_code=401)
    try:
        n = _ct_gerar_cobrancas_mes(session, ctx.company.id)
        return _JR({"ok": True, "message": f"{n} cobrança(s) gerada(s) para {_ct_competencia_atual()}"})
    except Exception as _e:
        return _JR({"error": str(_e)}, status_code=500)


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

    valor_fmt = f"{(c.valor_cents/100):.2f}".replace(".", ",") if c else ""

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
               placeholder="1.500,00" value="{valor_fmt}" id="valorInput">
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
        <div class="form-text">Deixe vazio para contrato por prazo indeterminado</div>
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
        badge = {"pendente":"bg-warning text-dark","pago":"bg-success","vencido":"bg-danger","cancelado":"bg-secondary"}.get(c.status,"bg-secondary")
        pago_str = _ct_brl(c.valor_pago_cents or c.valor_cents) if c.status == "pago" else "—"
        rows += f"""
        <tr>
          <td>{c.competencia}</td>
          <td class="text-end">{_ct_brl(c.valor_cents)}</td>
          <td class="text-center">{c.data_vencimento}</td>
          <td class="text-center"><span class="badge {badge}">{c.status.capitalize()}</span></td>
          <td class="text-end text-success">{pago_str}</td>
          <td class="text-center">{c.data_pagamento or '—'}</td>
          <td>{c.forma_pagamento or '—'}</td>
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
        </tr>
      </thead>
      <tbody>{rows if rows else '<tr><td colspan="7" class="text-center text-muted py-4">Nenhuma cobrança gerada ainda</td></tr>'}</tbody>
    </table>
  </div>
</div>
{{% endblock %}}"""

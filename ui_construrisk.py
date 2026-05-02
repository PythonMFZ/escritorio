# ============================================================================
# PATCH — ConstruRisk: Dossiê de Análise de Compradores PF/PJ
# ============================================================================
# Salve como ui_construrisk.py e adicione ao final do app.py:
#   exec(open('ui_construrisk.py').read())
#
# PRÉ-REQUISITOS:
#   - DIRECTDATA_TOKEN no Render (token do portal DirectData)
#   - Templates PF e PJ criados em app.directd.com.br/dossie/novo
#
# FLUXO:
#   1. Usuário informa CPF (PF) ou CNPJ (PJ) + seleciona template
#   2. Sistema chama POST /api/Dossier/Process
#   3. Polling via GET /api/Dossier/Status até concluir
#   4. Resultado exibido na tela + opção de PDF
#   5. Augur gera parecer de risco com base no resultado
#   6. Créditos debitados ao concluir (configurável na precificação)
# ============================================================================

import os as _os_cr
import re as _re_cr
import json as _json_cr
import asyncio as _asyncio_cr
import requests as _req_cr
from typing import Optional as _OptCR
from sqlmodel import Field as _FCR, SQLModel as _SMCR
from datetime import datetime as _dtCR

# ── Configuração ──────────────────────────────────────────────────────────────

_DD_BASE    = "https://api.app.directd.com.br"
_DD_TOKEN   = lambda: _os_cr.environ.get("DIRECTDATA_TOKEN", "")
_DD_HEADERS = lambda: {"Content-Type": "application/json"}
_DD_PARAMS  = lambda extra=None: dict({"TOKEN": _DD_TOKEN()}, **(extra or {}))

_CR_PRODUCT_PF = "construrisk_pf"
_CR_PRODUCT_PJ = "construrisk_pj"


# ── Modelo ────────────────────────────────────────────────────────────────────

class ConstruRiskDossie(_SMCR, table=True):
    __tablename__  = "construriskdossie"
    __table_args__ = {"extend_existing": True}
    id:           _OptCR[int] = _FCR(default=None, primary_key=True)
    company_id:   int         = _FCR(index=True)
    client_id:    int         = _FCR(index=True)
    user_id:      int         = _FCR(index=True)
    person_type:  str         = _FCR(default="PF")   # PF | PJ
    document:     str         = _FCR(default="")      # CPF ou CNPJ (só dígitos)
    nome:         str         = _FCR(default="")
    dossie_id:    str         = _FCR(default="", index=True)  # ID retornado pela DirectData
    template_id:  str         = _FCR(default="")
    status:       str         = _FCR(default="processing")  # processing | done | error
    resultado_json: str       = _FCR(default="{}")
    parecer_ia:   str         = _FCR(default="")
    creditos_cobrados: int    = _FCR(default=0)
    created_at:   str         = _FCR(default="")
    updated_at:   str         = _FCR(default="")

try:
    _SMCR.metadata.create_all(engine, tables=[ConstruRiskDossie.__table__])
except Exception:
    pass


# ── Helpers DirectData ────────────────────────────────────────────────────────

def _dd_get_templates(person_type: int = 0) -> list:
    """Lista templates disponíveis (1=PF, 2=PJ, 0=ambos)."""
    try:
        params = _DD_PARAMS({"personType": person_type} if person_type else {})
        r = _req_cr.get(
            f"{_DD_BASE}/api/Dossier/Templates",
            headers=_DD_HEADERS(),
            params=params,
            timeout=15,
        )
        r.raise_for_status()
        data = r.json()
        if isinstance(data, list):
            return data
        return data.get("templates", data.get("data", []))
    except Exception as e:
        print(f"[construrisk] Erro ao listar templates: {e}")
        return []


def _dd_process(template_id: str, documents: list) -> tuple[bool, str, str]:
    """
    Inicia processamento do dossiê.
    Retorna (ok, dossie_id, erro).
    documents: lista de strings CPF/CNPJ
    """
    try:
        r = _req_cr.post(
            f"{_DD_BASE}/api/Dossier/Process",
            headers=_DD_HEADERS(),
            params=_DD_PARAMS(),
            json={"templateID": template_id, "documents": documents},
            timeout=30,
        )
        r.raise_for_status()
        data = r.json()
        # Tenta extrair o dossieID da resposta
        dossie_id = (
            data.get("dossieID") or
            data.get("id") or
            data.get("dossierID") or
            (data.get("data") or {}).get("dossieID") or
            ""
        )
        if not dossie_id and isinstance(data, list) and data:
            dossie_id = data[0].get("dossieID") or data[0].get("id") or ""
        return bool(dossie_id), str(dossie_id), ""
    except Exception as e:
        return False, "", str(e)


def _dd_status(dossie_id: str) -> dict:
    """Consulta status do dossiê."""
    try:
        r = _req_cr.get(
            f"{_DD_BASE}/api/Dossier/Status",
            headers=_DD_HEADERS(),
            params=_DD_PARAMS({"dossieID": dossie_id}),
            timeout=15,
        )
        r.raise_for_status()
        return r.json()
    except Exception as e:
        return {"error": str(e)}


def _dd_full_details(dossie_id: str) -> dict:
    """Busca resultado completo do dossiê."""
    try:
        r = _req_cr.get(
            f"{_DD_BASE}/api/Dossier/Full-Details",
            headers=_DD_HEADERS(),
            params=_DD_PARAMS({"dossieID": dossie_id}),
            timeout=30,
        )
        r.raise_for_status()
        return r.json()
    except Exception as e:
        return {"error": str(e)}


def _dd_generate_pdf(dossie_id: str) -> bytes | None:
    """Gera e retorna o PDF do dossiê."""
    try:
        r = _req_cr.post(
            f"{_DD_BASE}/api/Dossier/GeneratePDF",
            headers=_DD_HEADERS(),
            params=_DD_PARAMS({"dossieID": dossie_id}),
            timeout=60,
        )
        r.raise_for_status()
        # Retorna bytes do PDF ou URL
        if r.headers.get("content-type", "").startswith("application/pdf"):
            return r.content
        data = r.json()
        return data.get("url") or data.get("pdfUrl") or None
    except Exception as e:
        print(f"[construrisk] Erro PDF: {e}")
        return None


def _gerar_parecer_ia(resultado: dict, person_type: str) -> str:
    """Gera parecer de risco com Claude baseado no resultado do dossiê."""
    api_key = _os_cr.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        return ""

    summary = resultado.get("summary", {})
    details = resultado.get("details", [])

    # Extrai alertas
    alertas = []
    for d in details:
        for a in (d.get("alertList") or []):
            rt = a.get("resultType", {})
            if rt.get("result") not in ("Regular", None):
                alertas.append(f"• [{d.get('nameAPI','')}] {a.get('fieldName','')}: {a.get('value','')} → {rt.get('result','')}")

    nome     = summary.get("name", "")
    doc      = summary.get("document", "")
    status   = summary.get("status", "")
    template = summary.get("templateName", "")

    prompt = f"""Você é um especialista em análise de risco imobiliário.

Analise o dossiê ConstruRisk de {person_type} e emita um parecer de risco para venda de imóvel.

DADOS DO DOSSIÊ:
- Nome: {nome}
- Documento: {doc}
- Status geral: {status}
- Template: {template}

ALERTAS IDENTIFICADOS:
{chr(10).join(alertas) if alertas else "Nenhum alerta crítico identificado."}

Emita um parecer estruturado com:
1. CLASSIFICAÇÃO DE RISCO: (Baixo / Médio / Alto / Crítico)
2. RESUMO: 2-3 linhas sobre o perfil
3. PONTOS DE ATENÇÃO: lista dos alertas relevantes
4. RECOMENDAÇÃO: aprovado / aprovado com ressalvas / reprovado para a transação

Seja objetivo e direto. Máximo 300 palavras."""

    try:
        resp = _req_cr.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": "claude-sonnet-4-6",
                "max_tokens": 800,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()["content"][0]["text"]
    except Exception as e:
        print(f"[construrisk] Erro parecer IA: {e}")
        return ""


# ── Rota GET /construrisk ─────────────────────────────────────────────────────

@app.get("/construrisk", response_class=HTMLResponse)
@require_login
async def construrisk_index(request: Request, session: Session = Depends(get_session)):
    ctx = get_tenant_context(request, session)
    if not ctx:
        request.session.clear()
        return RedirectResponse("/login", status_code=303)

    cc = get_client_or_none(session, ctx.company.id,
                            get_active_client_id(request, session, ctx))

    # Busca templates disponíveis
    templates_pf = _dd_get_templates(1)
    templates_pj = _dd_get_templates(2)

    # Histórico de dossiês do cliente
    historico = []
    if cc:
        historico = session.exec(
            select(ConstruRiskDossie)
            .where(ConstruRiskDossie.company_id == ctx.company.id,
                   ConstruRiskDossie.client_id  == cc.id)
            .order_by(ConstruRiskDossie.id.desc())
            .limit(10)
        ).all()

    # Preço configurado
    preco_pf = _get_preco(session, ctx.company.id, _CR_PRODUCT_PF, 50)
    preco_pj = _get_preco(session, ctx.company.id, _CR_PRODUCT_PJ, 50)

    # Saldo
    saldo = 0.0
    if cc:
        try:
            w = session.exec(
                select(CreditWallet)
                .where(CreditWallet.company_id == ctx.company.id,
                       CreditWallet.client_id  == cc.id)
            ).first()
            saldo = (w.balance_cents / 100) if w else 0.0
        except Exception:
            pass

    return render("construrisk.html", request=request, context={
        "current_user":    ctx.user,
        "current_company": ctx.company,
        "role":            ctx.membership.role,
        "current_client":  cc,
        "templates_pf":    templates_pf,
        "templates_pj":    templates_pj,
        "historico":       historico,
        "preco_pf":        preco_pf,
        "preco_pj":        preco_pj,
        "saldo":           saldo,
    })


# ── Rota POST /construrisk/processar ─────────────────────────────────────────

@app.post("/construrisk/processar")
@require_login
async def construrisk_processar(request: Request, session: Session = Depends(get_session)):
    ctx = get_tenant_context(request, session)
    if not ctx:
        return JSONResponse({"ok": False, "erro": "Não autenticado."}, status_code=401)

    cc = get_client_or_none(session, ctx.company.id,
                            get_active_client_id(request, session, ctx))
    if not cc:
        return JSONResponse({"ok": False, "erro": "Nenhum cliente selecionado."})

    body = await request.json()
    document    = _re_cr.sub(r'\D', '', body.get("document", ""))
    person_type = body.get("person_type", "PF")
    template_id = body.get("template_id", "")
    nome        = body.get("nome", "")

    if not document or not template_id:
        return JSONResponse({"ok": False, "erro": "Documento e template são obrigatórios."})

    # Valida documento
    if person_type == "PF" and len(document) != 11:
        return JSONResponse({"ok": False, "erro": "CPF inválido (deve ter 11 dígitos)."})
    if person_type == "PJ" and len(document) != 14:
        return JSONResponse({"ok": False, "erro": "CNPJ inválido (deve ter 14 dígitos)."})

    # Verifica créditos
    produto_code = _CR_PRODUCT_PF if person_type == "PF" else _CR_PRODUCT_PJ
    preco = _get_preco(session, ctx.company.id, produto_code, 50)

    if preco > 0:
        try:
            w = session.exec(
                select(CreditWallet)
                .where(CreditWallet.company_id == ctx.company.id,
                       CreditWallet.client_id  == cc.id)
            ).first()
            saldo = (w.balance_cents / 100) if w else 0.0
            if saldo < preco:
                return JSONResponse({
                    "ok": False,
                    "erro": f"Saldo insuficiente. Necessário: {preco} créditos. Disponível: {saldo:.0f}.",
                    "precisa_creditos": True,
                })
        except Exception:
            pass

    # Inicia processamento na DirectData
    ok, dossie_id, erro = _dd_process(template_id, [document])
    if not ok:
        return JSONResponse({"ok": False, "erro": f"Erro ao processar: {erro}"})

    # Debita créditos
    if preco > 0:
        try:
            w = session.exec(
                select(CreditWallet)
                .where(CreditWallet.company_id == ctx.company.id,
                       CreditWallet.client_id  == cc.id)
            ).first()
            if w:
                w.balance_cents -= int(preco * 100)
                w.updated_at = utcnow()
                session.add(w)
                session.add(CreditLedger(
                    company_id=ctx.company.id,
                    client_id=cc.id,
                    kind="CONSULT_CAPTURED",
                    amount_cents=-int(preco * 100),
                    ref_type="construrisk",
                    ref_id=dossie_id,
                    note=f"ConstruRisk {person_type}: {document}",
                ))
        except Exception as e:
            print(f"[construrisk] Erro débito: {e}")

    # Salva registro
    dossie = ConstruRiskDossie(
        company_id=ctx.company.id,
        client_id=cc.id,
        user_id=ctx.user.id,
        person_type=person_type,
        document=document,
        nome=nome,
        dossie_id=dossie_id,
        template_id=template_id,
        status="processing",
        creditos_cobrados=preco,
        created_at=str(_dtCR.utcnow()),
        updated_at=str(_dtCR.utcnow()),
    )
    session.add(dossie)
    session.commit()
    session.refresh(dossie)

    return JSONResponse({"ok": True, "id": dossie.id, "dossie_id": dossie_id})


# ── Rota GET /construrisk/{id}/status ─────────────────────────────────────────

@app.get("/construrisk/{dossie_local_id}/status")
@require_login
async def construrisk_status(
    dossie_local_id: int, request: Request, session: Session = Depends(get_session)
):
    ctx = get_tenant_context(request, session)
    if not ctx:
        return JSONResponse({"status": "error"})

    d = session.get(ConstruRiskDossie, dossie_local_id)
    if not d or d.company_id != ctx.company.id:
        return JSONResponse({"status": "not_found"})

    if d.status == "done":
        return JSONResponse({"status": "done", "dossie_id": d.dossie_id})

    if d.status == "error":
        return JSONResponse({"status": "error"})

    # Consulta status na DirectData
    st = _dd_status(d.dossie_id)
    situation = st.get("situation") or st.get("situationType") or 0

    # situation 3 = Concluído, 4 = Concluído com erros
    if situation in (3, 4, "3", "4", "Concluído", "Concluído com erros"):
        # Busca resultado completo
        resultado = _dd_full_details(d.dossie_id)
        parecer   = _gerar_parecer_ia(resultado, d.person_type)

        d.status         = "done"
        d.resultado_json = _json_cr.dumps(resultado, ensure_ascii=False)
        d.parecer_ia     = parecer
        d.updated_at     = str(_dtCR.utcnow())
        session.add(d)
        session.commit()
        return JSONResponse({"status": "done", "dossie_id": d.dossie_id})

    if situation in (6, 7, "6", "7", "Cancelado"):
        d.status = "error"
        session.add(d); session.commit()
        return JSONResponse({"status": "error"})

    return JSONResponse({"status": "processing", "situation": situation})


# ── Rota GET /construrisk/{id}/resultado ──────────────────────────────────────

@app.get("/construrisk/{dossie_local_id}/resultado", response_class=HTMLResponse)
@require_login
async def construrisk_resultado(
    dossie_local_id: int, request: Request, session: Session = Depends(get_session)
):
    ctx = get_tenant_context(request, session)
    if not ctx:
        return RedirectResponse("/login", status_code=303)

    d = session.get(ConstruRiskDossie, dossie_local_id)
    if not d or d.company_id != ctx.company.id:
        return RedirectResponse("/construrisk", status_code=303)

    resultado = {}
    try:
        resultado = _json_cr.loads(d.resultado_json)
    except Exception:
        pass

    cc = get_client_or_none(session, ctx.company.id,
                            get_active_client_id(request, session, ctx))

    return render("construrisk_resultado.html", request=request, context={
        "current_user":    ctx.user,
        "current_company": ctx.company,
        "role":            ctx.membership.role,
        "current_client":  cc,
        "dossie":          d,
        "resultado":       resultado,
        "summary":         resultado.get("summary", {}),
        "details":         resultado.get("details", []),
    })


# ── Rota GET /construrisk/{id}/pdf ────────────────────────────────────────────

@app.get("/construrisk/{dossie_local_id}/pdf")
@require_login
async def construrisk_pdf(
    dossie_local_id: int, request: Request, session: Session = Depends(get_session)
):
    ctx = get_tenant_context(request, session)
    if not ctx:
        return RedirectResponse("/login", status_code=303)

    d = session.get(ConstruRiskDossie, dossie_local_id)
    if not d or d.company_id != ctx.company.id:
        return JSONResponse({"ok": False}, status_code=404)

    resultado = _dd_generate_pdf(d.dossie_id)

    if isinstance(resultado, bytes):
        from fastapi.responses import Response as _Resp
        return _Resp(
            content=resultado,
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="construrisk_{d.document}.pdf"'},
        )
    elif isinstance(resultado, str) and resultado.startswith("http"):
        return RedirectResponse(resultado, status_code=302)

    return JSONResponse({"ok": False, "erro": "PDF não disponível."})


# ── Templates ─────────────────────────────────────────────────────────────────

TEMPLATES["construrisk.html"] = r"""
{% extends "base.html" %}
{% block content %}
<style>
  .cr-tabs{display:flex;gap:.5rem;margin-bottom:1rem;}
  .cr-tab{padding:.5rem 1.25rem;border-radius:10px;border:1.5px solid var(--mc-border);cursor:pointer;font-weight:600;font-size:.88rem;background:#fff;}
  .cr-tab.active{background:var(--mc-primary);color:#fff;border-color:var(--mc-primary);}
  .cr-form{border:1px solid var(--mc-border);border-radius:14px;padding:1.5rem;background:#fff;margin-bottom:1.5rem;}
  .cr-hist{border:1px solid var(--mc-border);border-radius:10px;padding:.65rem 1rem;margin-bottom:.5rem;display:flex;justify-content:space-between;align-items:center;background:#fff;font-size:.85rem;}
  .cr-status{font-size:.7rem;font-weight:700;padding:.2rem .6rem;border-radius:999px;}
  .cr-status.processing{background:rgba(202,138,4,.12);color:#854d0e;}
  .cr-status.done{background:rgba(22,163,74,.12);color:#166534;}
  .cr-status.error{background:rgba(220,38,38,.12);color:#991b1b;}
  .cr-risk-low{color:#16a34a;font-weight:700;}
  .cr-risk-med{color:#ca8a04;font-weight:700;}
  .cr-risk-high{color:#dc2626;font-weight:700;}
</style>

<div class="d-flex justify-content-between align-items-start flex-wrap gap-3 mb-3">
  <div>
    <h4 class="mb-1">ConstruRisk</h4>
    <div class="muted small">Análise de risco de compradores PF e PJ para transações imobiliárias.</div>
  </div>
  {% if current_client %}
  <div class="text-end">
    <div class="muted small">Saldo disponível</div>
    <div class="fw-bold" style="font-size:1.1rem;">{{ "%.0f"|format(saldo) }} créditos</div>
  </div>
  {% endif %}
</div>

{% if not current_client %}
<div class="alert alert-warning">Selecione um cliente para gerar um dossiê.</div>
{% else %}

{# Tabs PF/PJ #}
<div class="cr-tabs">
  <div class="cr-tab active" id="tabPF" onclick="switchTab('PF')">👤 Pessoa Física</div>
  <div class="cr-tab" id="tabPJ" onclick="switchTab('PJ')">🏢 Pessoa Jurídica</div>
</div>

{# Formulário PF #}
<div id="formPF" class="cr-form">
  <h6 class="mb-3">Análise PF — {{ preco_pf }} créditos</h6>
  <div class="row g-3">
    <div class="col-md-4">
      <label class="form-label fw-semibold small">CPF</label>
      <input type="text" id="pfDoc" class="form-control" placeholder="000.000.000-00"
             oninput="mascaraCPF(this)">
    </div>
    <div class="col-md-4">
      <label class="form-label fw-semibold small">Nome (opcional)</label>
      <input type="text" id="pfNome" class="form-control" placeholder="Nome do comprador">
    </div>
    <div class="col-md-4">
      <label class="form-label fw-semibold small">Template</label>
      <select id="pfTemplate" class="form-select">
        <option value="">— Selecione —</option>
        {% for t in templates_pf %}
        <option value="{{ t.id or t.templateID or t.TemplateID }}">{{ t.name or t.templateName or t.Name }}</option>
        {% endfor %}
      </select>
    </div>
  </div>
  <div class="mt-3 d-flex gap-2">
    <button class="btn btn-primary" onclick="processarDossie('PF')">
      <i class="bi bi-search me-1"></i>Gerar Dossiê PF
    </button>
    <span class="muted small align-self-center">{{ preco_pf }} créditos serão debitados</span>
  </div>
</div>

{# Formulário PJ #}
<div id="formPJ" class="cr-form" style="display:none;">
  <h6 class="mb-3">Análise PJ — {{ preco_pj }} créditos</h6>
  <div class="row g-3">
    <div class="col-md-4">
      <label class="form-label fw-semibold small">CNPJ</label>
      <input type="text" id="pjDoc" class="form-control" placeholder="00.000.000/0000-00"
             oninput="mascaraCNPJ(this)">
    </div>
    <div class="col-md-4">
      <label class="form-label fw-semibold small">Razão Social (opcional)</label>
      <input type="text" id="pjNome" class="form-control" placeholder="Razão social">
    </div>
    <div class="col-md-4">
      <label class="form-label fw-semibold small">Template</label>
      <select id="pjTemplate" class="form-select">
        <option value="">— Selecione —</option>
        {% for t in templates_pj %}
        <option value="{{ t.id or t.templateID or t.TemplateID }}">{{ t.name or t.templateName or t.Name }}</option>
        {% endfor %}
      </select>
    </div>
  </div>
  <div class="mt-3 d-flex gap-2">
    <button class="btn btn-primary" onclick="processarDossie('PJ')">
      <i class="bi bi-search me-1"></i>Gerar Dossiê PJ
    </button>
    <span class="muted small align-self-center">{{ preco_pj }} créditos serão debitados</span>
  </div>
</div>

<div id="crFeedback" class="mb-3" style="display:none;"></div>

{# Histórico #}
{% if historico %}
<h6 class="mb-2">Histórico de dossiês</h6>
{% for d in historico %}
<div class="cr-hist" id="cr-hist-{{ d.id }}">
  <div>
    <div class="fw-semibold">
      {{ d.nome or d.document }}
      <span class="badge text-bg-light border ms-1">{{ d.person_type }}</span>
    </div>
    <div class="muted" style="font-size:.72rem;">{{ d.created_at[:10] if d.created_at else '' }}</div>
  </div>
  <div class="d-flex gap-2 align-items-center">
    <span class="cr-status {{ d.status }}">
      {{ 'Concluído' if d.status == 'done' else ('Processando' if d.status == 'processing' else 'Erro') }}
    </span>
    {% if d.status == 'done' %}
    <a href="/construrisk/{{ d.id }}/resultado" class="btn btn-sm btn-outline-primary">Ver resultado</a>
    <a href="/construrisk/{{ d.id }}/pdf" class="btn btn-sm btn-outline-secondary" target="_blank">PDF</a>
    {% elif d.status == 'processing' %}
    <button class="btn btn-sm btn-outline-secondary" onclick="verificarStatus({{ d.id }}, this)">
      Verificar
    </button>
    {% endif %}
  </div>
</div>
{% endfor %}
{% endif %}

{% endif %}

<script>
let _tabAtual = 'PF';

function switchTab(tab) {
  _tabAtual = tab;
  document.getElementById('tabPF').classList.toggle('active', tab === 'PF');
  document.getElementById('tabPJ').classList.toggle('active', tab === 'PJ');
  document.getElementById('formPF').style.display = tab === 'PF' ? 'block' : 'none';
  document.getElementById('formPJ').style.display = tab === 'PJ' ? 'block' : 'none';
}

function mascaraCPF(el) {
  let v = el.value.replace(/\D/g,'').slice(0,11);
  v = v.replace(/(\d{3})(\d)/,'$1.$2')
        .replace(/(\d{3})(\d)/,'$1.$2')
        .replace(/(\d{3})(\d{1,2})$/,'$1-$2');
  el.value = v;
}

function mascaraCNPJ(el) {
  let v = el.value.replace(/\D/g,'').slice(0,14);
  v = v.replace(/(\d{2})(\d)/,'$1.$2')
        .replace(/(\d{3})(\d)/,'$1.$2')
        .replace(/(\d{3})(\d)/,'$1/$2')
        .replace(/(\d{4})(\d{1,2})$/,'$1-$2');
  el.value = v;
}

async function processarDossie(tipo) {
  const doc      = document.getElementById(tipo === 'PF' ? 'pfDoc' : 'pjDoc').value;
  const nome     = document.getElementById(tipo === 'PF' ? 'pfNome' : 'pjNome').value;
  const template = document.getElementById(tipo === 'PF' ? 'pfTemplate' : 'pjTemplate').value;
  const fb       = document.getElementById('crFeedback');

  if (!doc || !template) {
    fb.style.display = 'block';
    fb.innerHTML = '<div class="alert alert-warning">Preencha o documento e selecione o template.</div>';
    return;
  }

  fb.style.display = 'block';
  fb.innerHTML = '<div class="alert alert-info"><div class="spinner-border spinner-border-sm me-2"></div>Iniciando processamento...</div>';

  const r = await fetch('/construrisk/processar', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({document: doc, person_type: tipo, template_id: template, nome}),
  });
  const d = await r.json();

  if (d.ok) {
    fb.innerHTML = '<div class="alert alert-success">✅ Dossiê enviado para processamento! Aguarde o resultado.<br><small>O processamento pode levar alguns minutos. Clique em "Verificar" no histórico.</small></div>';
    setTimeout(() => location.reload(), 3000);
  } else if (d.precisa_creditos) {
    fb.innerHTML = `<div class="alert alert-warning">⚠️ ${d.erro} <a href="/creditos" class="alert-link">Adquirir créditos →</a></div>`;
  } else {
    fb.innerHTML = `<div class="alert alert-danger">❌ ${d.erro || 'Erro ao processar.'}</div>`;
  }
}

async function verificarStatus(id, btn) {
  btn.disabled = true; btn.textContent = 'Verificando...';
  const r = await fetch('/construrisk/' + id + '/status');
  const d = await r.json();
  if (d.status === 'done') { location.reload(); }
  else if (d.status === 'error') {
    btn.disabled = false; btn.textContent = 'Erro';
    btn.className = 'btn btn-sm btn-outline-danger';
  } else {
    btn.disabled = false; btn.textContent = 'Ainda processando...';
    setTimeout(() => { btn.textContent = 'Verificar'; }, 3000);
  }
}
</script>
{% endblock %}
"""

TEMPLATES["construrisk_resultado.html"] = r"""
{% extends "base.html" %}
{% block content %}
<style>
  .cr-section{border:1px solid var(--mc-border);border-radius:12px;padding:1rem 1.25rem;background:#fff;margin-bottom:1rem;}
  .cr-badge-regular{background:rgba(22,163,74,.12);color:#166534;padding:.25rem .65rem;border-radius:999px;font-size:.75rem;font-weight:700;}
  .cr-badge-atencao{background:rgba(202,138,4,.12);color:#854d0e;padding:.25rem .65rem;border-radius:999px;font-size:.75rem;font-weight:700;}
  .cr-badge-alerta{background:rgba(220,38,38,.12);color:#991b1b;padding:.25rem .65rem;border-radius:999px;font-size:.75rem;font-weight:700;}
  .cr-badge-inconclusiva{background:#f3f4f6;color:#6b7280;padding:.25rem .65rem;border-radius:999px;font-size:.75rem;font-weight:700;}
  .cr-api{border:1px solid var(--mc-border);border-radius:10px;padding:.75rem 1rem;margin-bottom:.5rem;}
  .cr-api-nome{font-weight:600;font-size:.88rem;margin-bottom:.3rem;}
  .cr-alerta{font-size:.78rem;padding:.2rem .5rem;border-radius:6px;margin:.2rem 0;display:inline-block;}
  .cr-alerta.Regular{background:rgba(22,163,74,.08);color:#166534;}
  .cr-alerta.Atenção,.cr-alerta.Atencao{background:rgba(202,138,4,.08);color:#854d0e;}
  .cr-alerta.Alerta{background:rgba(220,38,38,.08);color:#991b1b;}
  .cr-parecer{background:#f0f9ff;border:1px solid #bae6fd;border-radius:12px;padding:1rem 1.25rem;white-space:pre-wrap;font-size:.85rem;line-height:1.6;}
  @media print{.no-print{display:none!important;}}
</style>

<div class="d-flex justify-content-between align-items-start flex-wrap gap-3 mb-3 no-print">
  <div>
    <a href="/construrisk" class="btn btn-outline-secondary btn-sm mb-2">← Voltar</a>
    <h4 class="mb-0">Resultado ConstruRisk</h4>
    <div class="muted small">{{ dossie.person_type }} · {{ dossie.document }} · {{ dossie.created_at[:10] if dossie.created_at else '' }}</div>
  </div>
  <div class="d-flex gap-2 no-print">
    <a href="/construrisk/{{ dossie.id }}/pdf" class="btn btn-outline-secondary btn-sm" target="_blank">
      <i class="bi bi-file-pdf me-1"></i>Baixar PDF
    </a>
    <button class="btn btn-outline-secondary btn-sm" onclick="window.print()">
      <i class="bi bi-printer me-1"></i>Imprimir
    </button>
  </div>
</div>

{# Resumo #}
{% if summary %}
<div class="cr-section">
  <div class="d-flex justify-content-between align-items-start flex-wrap gap-2">
    <div>
      <div class="fw-bold fs-5">{{ summary.name or dossie.nome }}</div>
      <div class="muted small">{{ summary.document or dossie.document }}</div>
      {% if summary.templateName %}
      <div class="muted small">Template: {{ summary.templateName }}</div>
      {% endif %}
    </div>
    <div>
      {% set st = summary.status or '' %}
      <span class="cr-badge-{{ st.lower().replace('atenção','atencao').replace('ã','a') }}">
        {{ st or 'Processando' }}
      </span>
    </div>
  </div>
</div>
{% endif %}

{# Parecer IA #}
{% if dossie.parecer_ia %}
<div class="cr-section">
  <h6 class="mb-2">🤖 Parecer de Risco — Augur</h6>
  <div class="cr-parecer">{{ dossie.parecer_ia }}</div>
</div>
{% endif %}

{# APIs / Módulos #}
{% if details %}
<h6 class="mb-2">Detalhes por módulo</h6>
{% for d in details %}
<div class="cr-api">
  <div class="cr-api-nome">{{ d.nameAPI or d.moduleName }}</div>
  {% if d.alertList %}
  <div class="d-flex flex-wrap gap-1">
    {% for a in d.alertList %}
    {% set res = a.resultType.result if a.resultType else 'Regular' %}
    <span class="cr-alerta {{ res }}">
      {{ a.fieldName }}: {{ a.value }} → {{ res }}
    </span>
    {% endfor %}
  </div>
  {% else %}
  <div class="muted small">Sem alertas</div>
  {% endif %}
</div>
{% endfor %}
{% endif %}

{% endblock %}
"""

# ── Adiciona ConstruRisk ao FEATURE_KEYS ──────────────────────────────────────
if "construrisk" not in FEATURE_KEYS:
    FEATURE_KEYS["construrisk"] = {
        "title": "ConstruRisk",
        "desc":  "Análise de risco de compradores PF/PJ para imóveis.",
        "href":  "/construrisk",
    }
    FEATURE_VISIBLE_ROLES["construrisk"] = {"admin", "equipe", "cliente"}
    ROLE_DEFAULT_FEATURES.setdefault("admin", set()).add("construrisk")
    ROLE_DEFAULT_FEATURES.setdefault("equipe", set()).add("construrisk")
    ROLE_DEFAULT_FEATURES.setdefault("cliente", set()).add("construrisk")

    # Adiciona ao grupo ferramentas_conteudo
    for _g in FEATURE_GROUPS:
        if _g.get("key") == "ferramentas_conteudo":
            if "construrisk" not in _g["features"]:
                _g["features"].append("construrisk")
            break

# ── Adiciona produtos na precificação ─────────────────────────────────────────
try:
    from sqlmodel import Session as _SessCR
    with _SessCR(engine) as _scr:
        for _cod, _nom, _desc in [
            (_CR_PRODUCT_PF, "ConstruRisk PF", "Dossiê de análise de risco — Pessoa Física"),
            (_CR_PRODUCT_PJ, "ConstruRisk PJ", "Dossiê de análise de risco — Pessoa Jurídica"),
        ]:
            _exists = _scr.exec(
                select(ProdutoPreco)
                .where(ProdutoPreco.codigo == _cod)
            ).first()
            if not _exists:
                _scr.add(ProdutoPreco(
                    company_id=1,  # será criado para company 1; outros via _sincronizar_produtos
                    codigo=_cod, nome=_nom, descricao=_desc,
                    categoria="compliance", modelo="uso", creditos=50,
                    ativo=True, updated_at=str(_dtCR.utcnow()),
                ))
        _scr.commit()
except Exception as _e_cr:
    print(f"[construrisk] Produtos precificacao: {_e_cr}")

if hasattr(templates_env.loader, "mapping"):
    templates_env.loader.mapping = TEMPLATES

print("[construrisk] Patch carregado.")

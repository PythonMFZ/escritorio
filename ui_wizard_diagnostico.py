# ============================================================================
# PATCH — Wizard de Diagnóstico em 5 Etapas
# ============================================================================
# Salve como ui_wizard_diagnostico.py e adicione ao final do app.py:
#   exec(open('ui_wizard_diagnostico.py').read())
#
# ETAPAS:
#   1. Empresa       — dados cadastrais básicos
#   2. Receitas      — faturamento, ticket médio, sazonalidade
#   3. Custos        — CMV, folha, despesas fixas/variáveis
#   4. Balanço       — caixa, recebíveis, estoque, dívidas
#   5. Processos     — as 15 perguntas + governança
#
# Cada etapa salva automaticamente. Cliente pode sair e continuar depois.
# Score calculado somente ao concluir a etapa 5.
# ============================================================================

import json as _json_wiz
from typing import Optional as _OptWiz
from sqlmodel import Field as _FWiz, SQLModel as _SMWiz
from datetime import datetime as _dtWiz


# ── Modelo: WizardRascunho ────────────────────────────────────────────────────

class WizardRascunho(_SMWiz, table=True):
    """Salva progresso parcial do wizard antes de gerar o snapshot final."""
    __tablename__  = "wizardrascunho"
    __table_args__ = {"extend_existing": True}
    id:          _OptWiz[int] = _FWiz(default=None, primary_key=True)
    company_id:  int          = _FWiz(index=True)
    client_id:   int          = _FWiz(index=True)
    etapa_atual: int          = _FWiz(default=1)   # 1-5
    dados_json:  str          = _FWiz(default="{}")
    created_at:  str          = _FWiz(default="")
    updated_at:  str          = _FWiz(default="")

try:
    _SMWiz.metadata.create_all(engine, tables=[WizardRascunho.__table__])
except Exception:
    pass


# ── Helpers ───────────────────────────────────────────────────────────────────

def _wiz_get_rascunho(session, company_id: int, client_id: int) -> WizardRascunho:
    r = session.exec(
        select(WizardRascunho)
        .where(WizardRascunho.company_id == company_id,
               WizardRascunho.client_id  == client_id)
    ).first()
    if not r:
        r = WizardRascunho(
            company_id=company_id, client_id=client_id,
            etapa_atual=1, dados_json="{}",
            created_at=str(_dtWiz.utcnow()),
            updated_at=str(_dtWiz.utcnow()),
        )
        session.add(r)
        session.commit()
        session.refresh(r)
    return r


def _wiz_salvar_etapa(session, rascunho: WizardRascunho, etapa: int, dados: dict):
    try:
        existente = _json_wiz.loads(rascunho.dados_json or "{}")
    except Exception:
        existente = {}
    existente[f"etapa_{etapa}"] = dados
    rascunho.dados_json  = _json_wiz.dumps(existente, ensure_ascii=False)
    rascunho.etapa_atual = max(rascunho.etapa_atual, etapa + 1)
    rascunho.updated_at  = str(_dtWiz.utcnow())
    session.add(rascunho)
    session.commit()


def _wiz_get_dados(rascunho: WizardRascunho) -> dict:
    try:
        return _json_wiz.loads(rascunho.dados_json or "{}")
    except Exception:
        return {}


def _wiz_calcular_score_financeiro(dados: dict) -> float:
    """Calcula score financeiro com base nos dados coletados."""
    e2 = dados.get("etapa_2", {})
    e3 = dados.get("etapa_3", {})
    e4 = dados.get("etapa_4", {})

    fat    = float(e2.get("faturamento_bruto_mensal", 0) or 0)
    cmv    = float(e3.get("cmv_mensal", 0) or 0)
    folha  = float(e3.get("folha_mensal", 0) or 0)
    desp_f = float(e3.get("despesas_fixas", 0) or 0)
    caixa  = float(e4.get("caixa_disponivel", 0) or 0)
    div_cp = float(e4.get("dividas_cp", 0) or 0)
    div_lp = float(e4.get("dividas_lp", 0) or 0)
    rec    = float(e4.get("contas_receber_total", 0) or 0)

    if fat <= 0:
        return 40.0

    margem_bruta = (fat - cmv) / fat if fat > 0 else 0
    custo_total  = cmv + folha + desp_f
    ebitda       = fat - custo_total
    div_total    = div_cp + div_lp

    score = 50.0

    # Margem bruta
    if margem_bruta >= 0.40:   score += 15
    elif margem_bruta >= 0.25: score += 8
    elif margem_bruta >= 0.10: score += 3
    else:                      score -= 10

    # Endividamento
    if fat > 0:
        div_fat = div_total / fat
        if div_fat <= 2:   score += 15
        elif div_fat <= 4: score += 5
        elif div_fat <= 8: score -= 5
        else:              score -= 15

    # Caixa
    if fat > 0:
        caixa_meses = caixa / fat
        if caixa_meses >= 3:   score += 15
        elif caixa_meses >= 1: score += 8
        elif caixa_meses >= 0.5: score += 2
        else:                  score -= 10

    # EBITDA positivo
    if ebitda > 0:  score += 5
    else:           score -= 10

    return max(0.0, min(100.0, score))


def _wiz_calcular_score_processos(dados: dict) -> float:
    """Calcula score de processos com base nas respostas sim/não."""
    e5 = dados.get("etapa_5", {})
    if not e5:
        return 50.0

    try:
        return score_process_from_answers(e5)
    except Exception:
        # Fallback manual
        pesos = {
            "dre_mensal": 10, "fluxo_90d": 12, "contas_pagar_receber": 10,
            "conciliacao_bancaria": 8, "inadimplencia": 8, "dividas_mapa": 10,
            "orcamento": 10, "kpis": 10, "precificacao": 8,
            "tributario_ok": 10, "contratos_ok": 6, "centro_custo": 8,
            "governanca": 8, "erp": 8, "demonstracoes_auditadas": 6,
        }
        total_peso = sum(pesos.values())
        score_ok   = sum(p for k, p in pesos.items() if e5.get(k))
        return round((score_ok / total_peso) * 100, 1) if total_peso > 0 else 50.0


# ── Rota GET /perfil/wizard ───────────────────────────────────────────────────

@app.get("/perfil/wizard", response_class=HTMLResponse)
@require_login
async def wizard_get(request: Request, session: Session = Depends(get_session)):
    ctx = get_tenant_context(request, session)
    if not ctx:
        request.session.clear()
        return RedirectResponse("/login", status_code=303)

    cc = get_client_or_none(session, ctx.company.id,
                            get_active_client_id(request, session, ctx))
    if not cc:
        set_flash(request, "Selecione um cliente para iniciar o diagnóstico.")
        return RedirectResponse("/perfil", status_code=303)

    etapa = int(request.query_params.get("etapa", 1))
    etapa = max(1, min(5, etapa))

    rascunho = _wiz_get_rascunho(session, ctx.company.id, cc.id)
    dados    = _wiz_get_dados(rascunho)

    return render("wizard_diagnostico.html", request=request, context={
        "current_user":    ctx.user,
        "current_company": ctx.company,
        "role":            ctx.membership.role,
        "current_client":  cc,
        "etapa":           etapa,
        "etapa_atual_salva": rascunho.etapa_atual,
        "dados":           dados,
        "etapa_dados":     dados.get(f"etapa_{etapa}", {}),
        "survey":          PROFILE_SURVEY_V2,
    })


# ── Rota POST /perfil/wizard/salvar ──────────────────────────────────────────

@app.post("/perfil/wizard/salvar")
@require_login
async def wizard_salvar(request: Request, session: Session = Depends(get_session)):
    ctx = get_tenant_context(request, session)
    if not ctx:
        return RedirectResponse("/login", status_code=303)

    cc = get_client_or_none(session, ctx.company.id,
                            get_active_client_id(request, session, ctx))
    if not cc:
        return RedirectResponse("/perfil", status_code=303)

    form  = await request.form()
    etapa = int(form.get("etapa", 1))

    rascunho = _wiz_get_rascunho(session, ctx.company.id, cc.id)
    dados_etapa = {}

    if etapa == 1:
        dados_etapa = {
            "razao_social":      form.get("razao_social", ""),
            "cnpj":              form.get("cnpj", ""),
            "segmento":          form.get("segmento", ""),
            "porte":             form.get("porte", ""),
            "cidade":            form.get("cidade", ""),
            "uf":                form.get("uf", ""),
            "anos_operacao":     form.get("anos_operacao", ""),
            "socios":            form.get("socios", ""),
            "regime_tributario": form.get("regime_tributario", ""),
            "cnae":              form.get("cnae", ""),
        }

    elif etapa == 2:
        dados_etapa = {
            "faturamento_bruto_mensal":   _f(form.get("faturamento_bruto_mensal")),
            "faturamento_medio_12m":      _f(form.get("faturamento_medio_12m")),
            "ticket_medio":               _f(form.get("ticket_medio")),
            "inadimplencia_pct":          _f(form.get("inadimplencia_pct")),
            "receita_recorrente_pct":     _f(form.get("receita_recorrente_pct")),
            "sazonalidade":               form.get("sazonalidade", ""),
            "principais_produtos":        form.get("principais_produtos", ""),
            "clientes_ativos":            int(form.get("clientes_ativos") or 0),
            "maior_cliente_pct":          _f(form.get("maior_cliente_pct")),
        }

    elif etapa == 3:
        dados_etapa = {
            "cmv_mensal":          _f(form.get("cmv_mensal")),
            "margem_bruta_pct":    _f(form.get("margem_bruta_pct")),
            "folha_mensal":        _f(form.get("folha_mensal")),
            "pro_labore":          _f(form.get("pro_labore")),
            "despesas_fixas":      _f(form.get("despesas_fixas")),
            "despesas_variaveis":  _f(form.get("despesas_variaveis")),
            "impostos_mensais":    _f(form.get("impostos_mensais")),
            "aluguel":             _f(form.get("aluguel")),
            "funcionarios":        int(form.get("funcionarios") or 0),
        }

    elif etapa == 4:
        dados_etapa = {
            "caixa_disponivel":        _f(form.get("caixa_disponivel")),
            "contas_receber_30d":      _f(form.get("contas_receber_30d")),
            "contas_receber_60d":      _f(form.get("contas_receber_60d")),
            "contas_receber_90d":      _f(form.get("contas_receber_90d")),
            "contas_receber_total":    _f(form.get("contas_receber_total")),
            "estoque":                 _f(form.get("estoque")),
            "contas_pagar_cp":         _f(form.get("contas_pagar_cp")),
            "contas_pagar_lp":         _f(form.get("contas_pagar_lp")),
            "dividas_cp":              _f(form.get("dividas_cp")),
            "dividas_lp":              _f(form.get("dividas_lp")),
            "garantias":               _f(form.get("garantias")),
            "patrimonio_liquido":      _f(form.get("patrimonio_liquido")),
        }

    elif etapa == 5:
        # Perguntas sim/não
        for q in PROFILE_SURVEY_V2:
            dados_etapa[q["id"]] = form.get(q["id"]) == "1"
        # Novas perguntas de governança
        for k in ["planejamento_estrategico", "reuniao_diretoria", "auditoria_interna",
                  "compliance_fiscal", "seguro_empresarial", "sucessao_definida"]:
            dados_etapa[k] = form.get(k) == "1"

    _wiz_salvar_etapa(session, rascunho, etapa, dados_etapa)

    # Se etapa 5 concluída — gera snapshot final
    if etapa == 5:
        return RedirectResponse("/perfil/wizard/finalizar", status_code=303)

    proxima = etapa + 1
    return RedirectResponse(f"/perfil/wizard?etapa={proxima}", status_code=303)


def _f(v) -> float:
    """Converte valor de formulário para float, removendo formatação."""
    try:
        if v is None or v == "":
            return 0.0
        return float(str(v).replace(".", "").replace(",", ".").replace("R$", "").strip())
    except Exception:
        return 0.0


# ── Rota GET /perfil/wizard/finalizar ────────────────────────────────────────

@app.get("/perfil/wizard/finalizar")
@require_login
async def wizard_finalizar(request: Request, session: Session = Depends(get_session)):
    ctx = get_tenant_context(request, session)
    if not ctx:
        return RedirectResponse("/login", status_code=303)

    cc = get_client_or_none(session, ctx.company.id,
                            get_active_client_id(request, session, ctx))
    if not cc:
        return RedirectResponse("/perfil", status_code=303)

    rascunho = _wiz_get_rascunho(session, ctx.company.id, cc.id)
    dados    = _wiz_get_dados(rascunho)

    e1 = dados.get("etapa_1", {})
    e2 = dados.get("etapa_2", {})
    e3 = dados.get("etapa_3", {})
    e4 = dados.get("etapa_4", {})
    e5 = dados.get("etapa_5", {})

    # Calcula scores
    score_fin  = _wiz_calcular_score_financeiro(dados)
    score_proc = _wiz_calcular_score_processos(dados)
    score_tot  = round((score_fin * 0.6) + (score_proc * 0.4), 1)

    fat   = float(e2.get("faturamento_bruto_mensal", 0) or 0)
    caixa = float(e4.get("caixa_disponivel", 0) or 0)
    div   = float(e4.get("dividas_cp", 0) or 0) + float(e4.get("dividas_lp", 0) or 0)

    # Cria snapshot
    answers = {**e5}
    snap = ClientSnapshot(
        company_id=ctx.company.id,
        client_id=cc.id,
        created_by_user_id=ctx.user.id,
        revenue_monthly_brl=fat,
        debt_total_brl=div,
        cash_balance_brl=caixa,
        employees_count=int(e3.get("funcionarios", 0) or 0),
        nps_score=0,
        notes=f"Diagnóstico completo via wizard — {e1.get('razao_social', cc.name)}",
        answers_json=_json_wiz.dumps({**answers, "_wizard_dados": dados}, ensure_ascii=False),
        score_process=score_proc,
        score_financial=score_fin,
        score_total=score_tot,
    )
    session.add(snap)

    # Atualiza cliente
    cc.revenue_monthly_brl = fat
    cc.debt_total_brl      = div
    cc.cash_balance_brl    = caixa
    cc.employees_count     = int(e3.get("funcionarios", 0) or 0)
    cc.updated_at          = utcnow()
    session.add(cc)

    # Atualiza perfil
    try:
        profile = get_or_create_business_profile(session, company_id=ctx.company.id, client_id=cc.id)
        profile.segment     = e1.get("segmento", profile.segment or "")
        profile.cnae        = e1.get("cnae", profile.cnae or "")
        profile.tax_regime  = e1.get("regime_tributario", profile.tax_regime or "")
        profile.company_size = e1.get("porte", profile.company_size or "")
        session.add(profile)
    except Exception:
        pass

    # Limpa rascunho
    rascunho.dados_json  = "{}"
    rascunho.etapa_atual = 1
    rascunho.updated_at  = str(_dtWiz.utcnow())
    session.add(rascunho)
    session.commit()

    set_flash(request, f"✅ Diagnóstico concluído! Score: {score_tot:.0f}/100")
    return RedirectResponse("/perfil", status_code=303)


# ── Template ──────────────────────────────────────────────────────────────────

TEMPLATES["wizard_diagnostico.html"] = r"""
{% extends "base.html" %}
{% block content %}
<style>
  .wiz-steps{display:flex;gap:0;margin-bottom:2rem;background:#f3f4f6;border-radius:12px;padding:.3rem;overflow:hidden;}
  .wiz-step{flex:1;text-align:center;padding:.5rem .25rem;border-radius:8px;font-size:.75rem;font-weight:600;color:var(--mc-muted);cursor:pointer;transition:all .2s;}
  .wiz-step.ativa{background:#fff;color:var(--mc-primary);box-shadow:0 1px 4px rgba(0,0,0,.08);}
  .wiz-step.concluida{color:#16a34a;}
  .wiz-step.bloqueada{opacity:.4;cursor:not-allowed;}
  .wiz-card{border:1px solid var(--mc-border);border-radius:14px;padding:1.5rem;background:#fff;margin-bottom:1rem;}
  .wiz-field{margin-bottom:1.25rem;}
  .wiz-field label{display:block;font-weight:600;font-size:.85rem;margin-bottom:.35rem;}
  .wiz-field input,.wiz-field select,.wiz-field textarea{width:100%;border:1.5px solid var(--mc-border);border-radius:8px;padding:.5rem .75rem;font-size:.88rem;outline:none;}
  .wiz-field input:focus,.wiz-field select:focus{border-color:var(--mc-primary);}
  .wiz-field .hint{font-size:.72rem;color:var(--mc-muted);margin-top:.25rem;}
  .wiz-bool{display:flex;gap:.75rem;align-items:center;padding:.6rem .85rem;border:1.5px solid var(--mc-border);border-radius:10px;margin-bottom:.5rem;cursor:pointer;}
  .wiz-bool:hover{border-color:var(--mc-primary);background:#fef9f5;}
  .wiz-bool input{width:18px;height:18px;cursor:pointer;}
  .wiz-bool label{font-size:.85rem;cursor:pointer;margin:0;font-weight:500;}
  .wiz-secao{font-size:.72rem;font-weight:700;text-transform:uppercase;letter-spacing:.08em;color:var(--mc-muted);margin:1.25rem 0 .5rem;padding-bottom:.3rem;border-bottom:1px solid var(--mc-border);}
  .wiz-moeda::before{content:"R$ ";color:var(--mc-muted);position:absolute;left:.75rem;top:50%;transform:translateY(-50%);font-size:.85rem;pointer-events:none;}
  .wiz-moeda-wrap{position:relative;}
  .wiz-moeda-wrap input{padding-left:2.5rem;}
  .wiz-nav{display:flex;justify-content:space-between;align-items:center;margin-top:1.5rem;}
  .wiz-progress{height:4px;background:#f3f4f6;border-radius:999px;margin-bottom:1.5rem;overflow:hidden;}
  .wiz-progress-bar{height:100%;background:var(--mc-primary);border-radius:999px;transition:width .3s;}
</style>

{% set etapas = [
  (1, "🏢 Empresa"),
  (2, "📈 Receitas"),
  (3, "💸 Custos"),
  (4, "⚖️ Balanço"),
  (5, "⚙️ Processos"),
] %}

<div class="d-flex justify-content-between align-items-start flex-wrap gap-2 mb-3">
  <div>
    <h4 class="mb-1">Diagnóstico Financeiro</h4>
    <div class="muted small">{{ current_client.name }} — preencha por etapas, salve e continue quando quiser.</div>
  </div>
  <a href="/perfil" class="btn btn-outline-secondary btn-sm">← Voltar</a>
</div>

{# Progress bar #}
<div class="wiz-progress">
  <div class="wiz-progress-bar" style="width:{{ (etapa / 5 * 100)|int }}%"></div>
</div>

{# Steps #}
<div class="wiz-steps">
  {% for n, label in etapas %}
  <a href="/perfil/wizard?etapa={{ n }}"
     class="wiz-step {% if n == etapa %}ativa{% elif n < etapa_atual_salva %}concluida{% elif n > etapa_atual_salva %}bloqueada{% endif %}"
     {% if n > etapa_atual_salva %}onclick="return false"{% endif %}>
    {% if n < etapa_atual_salva %}✅ {% endif %}{{ label }}
  </a>
  {% endfor %}
</div>

<form method="post" action="/perfil/wizard/salvar">
  <input type="hidden" name="etapa" value="{{ etapa }}">

  {# ── ETAPA 1: Empresa ── #}
  {% if etapa == 1 %}
  <div class="wiz-card">
    <h5 class="mb-3">🏢 Dados da Empresa</h5>
    <div class="row g-3">
      <div class="col-md-6">
        <div class="wiz-field">
          <label>Razão Social</label>
          <input type="text" name="razao_social" value="{{ etapa_dados.razao_social or current_client.name }}" placeholder="Nome da empresa">
        </div>
      </div>
      <div class="col-md-6">
        <div class="wiz-field">
          <label>CNPJ</label>
          <input type="text" name="cnpj" value="{{ etapa_dados.cnpj or '' }}" placeholder="00.000.000/0001-00">
        </div>
      </div>
      <div class="col-md-4">
        <div class="wiz-field">
          <label>Segmento</label>
          <select name="segmento">
            <option value="">— Selecione —</option>
            {% for s in ["Comércio", "Indústria", "Serviços", "Construção Civil", "Agronegócio", "Saúde", "Tecnologia", "Educação", "Imobiliário", "Outro"] %}
            <option value="{{ s }}" {% if etapa_dados.segmento == s %}selected{% endif %}>{{ s }}</option>
            {% endfor %}
          </select>
        </div>
      </div>
      <div class="col-md-4">
        <div class="wiz-field">
          <label>Porte</label>
          <select name="porte">
            <option value="">— Selecione —</option>
            {% for p in ["MEI", "Microempresa (ME)", "Pequena empresa (EPP)", "Média empresa", "Grande empresa"] %}
            <option value="{{ p }}" {% if etapa_dados.porte == p %}selected{% endif %}>{{ p }}</option>
            {% endfor %}
          </select>
        </div>
      </div>
      <div class="col-md-4">
        <div class="wiz-field">
          <label>Regime tributário</label>
          <select name="regime_tributario">
            <option value="">— Selecione —</option>
            {% for r in ["Simples Nacional", "Lucro Presumido", "Lucro Real", "MEI"] %}
            <option value="{{ r }}" {% if etapa_dados.regime_tributario == r %}selected{% endif %}>{{ r }}</option>
            {% endfor %}
          </select>
        </div>
      </div>
      <div class="col-md-4">
        <div class="wiz-field">
          <label>Cidade</label>
          <input type="text" name="cidade" value="{{ etapa_dados.cidade or '' }}" placeholder="Ex: Brusque">
        </div>
      </div>
      <div class="col-md-2">
        <div class="wiz-field">
          <label>UF</label>
          <input type="text" name="uf" value="{{ etapa_dados.uf or '' }}" placeholder="SC" maxlength="2">
        </div>
      </div>
      <div class="col-md-3">
        <div class="wiz-field">
          <label>Anos de operação</label>
          <input type="number" name="anos_operacao" value="{{ etapa_dados.anos_operacao or '' }}" min="0" placeholder="5">
        </div>
      </div>
      <div class="col-md-3">
        <div class="wiz-field">
          <label>Nº de sócios</label>
          <input type="text" name="socios" value="{{ etapa_dados.socios or '' }}" placeholder="2">
        </div>
      </div>
      <div class="col-12">
        <div class="wiz-field">
          <label>CNAE principal <span class="muted">(opcional)</span></label>
          <input type="text" name="cnae" value="{{ etapa_dados.cnae or '' }}" placeholder="Ex: 4711-3/02 — Comércio varejista">
        </div>
      </div>
    </div>
  </div>

  {# ── ETAPA 2: Receitas ── #}
  {% elif etapa == 2 %}
  <div class="wiz-card">
    <h5 class="mb-3">📈 Receitas e Vendas</h5>
    <div class="row g-3">
      <div class="col-md-6">
        <div class="wiz-field">
          <label>Faturamento bruto mensal <span class="text-danger">*</span></label>
          <div class="wiz-moeda-wrap"><span class="wiz-moeda"></span>
          <input type="text" name="faturamento_bruto_mensal" value="{{ etapa_dados.faturamento_bruto_mensal or '' }}" placeholder="500.000" class="moeda-input"></div>
          <div class="hint">Média dos últimos 3 meses</div>
        </div>
      </div>
      <div class="col-md-6">
        <div class="wiz-field">
          <label>Faturamento médio últimos 12 meses</label>
          <div class="wiz-moeda-wrap"><span class="wiz-moeda"></span>
          <input type="text" name="faturamento_medio_12m" value="{{ etapa_dados.faturamento_medio_12m or '' }}" placeholder="480.000" class="moeda-input"></div>
        </div>
      </div>
      <div class="col-md-4">
        <div class="wiz-field">
          <label>Ticket médio por venda</label>
          <div class="wiz-moeda-wrap"><span class="wiz-moeda"></span>
          <input type="text" name="ticket_medio" value="{{ etapa_dados.ticket_medio or '' }}" placeholder="2.500" class="moeda-input"></div>
        </div>
      </div>
      <div class="col-md-4">
        <div class="wiz-field">
          <label>Inadimplência atual (%)</label>
          <input type="number" name="inadimplencia_pct" value="{{ etapa_dados.inadimplencia_pct or '' }}" min="0" max="100" step="0.1" placeholder="3.5">
          <div class="hint">% do faturamento não recebido</div>
        </div>
      </div>
      <div class="col-md-4">
        <div class="wiz-field">
          <label>Receita recorrente (%)</label>
          <input type="number" name="receita_recorrente_pct" value="{{ etapa_dados.receita_recorrente_pct or '' }}" min="0" max="100" step="1" placeholder="40">
          <div class="hint">% que se repete todo mês</div>
        </div>
      </div>
      <div class="col-md-4">
        <div class="wiz-field">
          <label>Clientes ativos</label>
          <input type="number" name="clientes_ativos" value="{{ etapa_dados.clientes_ativos or '' }}" min="0" placeholder="85">
        </div>
      </div>
      <div class="col-md-4">
        <div class="wiz-field">
          <label>Maior cliente = % do faturamento</label>
          <input type="number" name="maior_cliente_pct" value="{{ etapa_dados.maior_cliente_pct or '' }}" min="0" max="100" step="1" placeholder="25">
          <div class="hint">Concentração de receita</div>
        </div>
      </div>
      <div class="col-md-4">
        <div class="wiz-field">
          <label>Sazonalidade</label>
          <select name="sazonalidade">
            <option value="">— Selecione —</option>
            {% for s in ["Sem sazonalidade", "Leve (±10%)", "Moderada (±30%)", "Alta (±50%)", "Muito alta (>50%)"] %}
            <option value="{{ s }}" {% if etapa_dados.sazonalidade == s %}selected{% endif %}>{{ s }}</option>
            {% endfor %}
          </select>
        </div>
      </div>
      <div class="col-12">
        <div class="wiz-field">
          <label>Principais produtos/serviços</label>
          <textarea name="principais_produtos" rows="2" placeholder="Ex: Venda de confecções, prestação de serviços de costura...">{{ etapa_dados.principais_produtos or '' }}</textarea>
        </div>
      </div>
    </div>
  </div>

  {# ── ETAPA 3: Custos ── #}
  {% elif etapa == 3 %}
  <div class="wiz-card">
    <h5 class="mb-3">💸 Custos e Despesas Mensais</h5>
    <div class="row g-3">
      <div class="col-md-6">
        <div class="wiz-field">
          <label>CMV — Custo da Mercadoria Vendida <span class="text-danger">*</span></label>
          <div class="wiz-moeda-wrap"><span class="wiz-moeda"></span>
          <input type="text" name="cmv_mensal" value="{{ etapa_dados.cmv_mensal or '' }}" placeholder="200.000" class="moeda-input"></div>
          <div class="hint">Custo direto dos produtos/serviços vendidos</div>
        </div>
      </div>
      <div class="col-md-6">
        <div class="wiz-field">
          <label>Margem bruta (%)</label>
          <input type="number" name="margem_bruta_pct" value="{{ etapa_dados.margem_bruta_pct or '' }}" min="0" max="100" step="0.1" placeholder="40">
          <div class="hint">Se souber, preencha direto. Senão calcularemos.</div>
        </div>
      </div>
      <div class="col-md-4">
        <div class="wiz-field">
          <label>Folha de pagamento total</label>
          <div class="wiz-moeda-wrap"><span class="wiz-moeda"></span>
          <input type="text" name="folha_mensal" value="{{ etapa_dados.folha_mensal or '' }}" placeholder="80.000" class="moeda-input"></div>
          <div class="hint">Inclui encargos (FGTS, INSS)</div>
        </div>
      </div>
      <div class="col-md-4">
        <div class="wiz-field">
          <label>Pró-labore dos sócios</label>
          <div class="wiz-moeda-wrap"><span class="wiz-moeda"></span>
          <input type="text" name="pro_labore" value="{{ etapa_dados.pro_labore or '' }}" placeholder="15.000" class="moeda-input"></div>
        </div>
      </div>
      <div class="col-md-4">
        <div class="wiz-field">
          <label>Número de funcionários</label>
          <input type="number" name="funcionarios" value="{{ etapa_dados.funcionarios or '' }}" min="0" placeholder="12">
        </div>
      </div>
      <div class="col-md-4">
        <div class="wiz-field">
          <label>Despesas fixas mensais</label>
          <div class="wiz-moeda-wrap"><span class="wiz-moeda"></span>
          <input type="text" name="despesas_fixas" value="{{ etapa_dados.despesas_fixas or '' }}" placeholder="35.000" class="moeda-input"></div>
          <div class="hint">Aluguel, energia, internet, seguros...</div>
        </div>
      </div>
      <div class="col-md-4">
        <div class="wiz-field">
          <label>Aluguel mensal</label>
          <div class="wiz-moeda-wrap"><span class="wiz-moeda"></span>
          <input type="text" name="aluguel" value="{{ etapa_dados.aluguel or '' }}" placeholder="8.000" class="moeda-input"></div>
        </div>
      </div>
      <div class="col-md-4">
        <div class="wiz-field">
          <label>Despesas variáveis mensais</label>
          <div class="wiz-moeda-wrap"><span class="wiz-moeda"></span>
          <input type="text" name="despesas_variaveis" value="{{ etapa_dados.despesas_variaveis or '' }}" placeholder="20.000" class="moeda-input"></div>
          <div class="hint">Comissões, fretes, embalagens...</div>
        </div>
      </div>
      <div class="col-md-4">
        <div class="wiz-field">
          <label>Impostos médios mensais</label>
          <div class="wiz-moeda-wrap"><span class="wiz-moeda"></span>
          <input type="text" name="impostos_mensais" value="{{ etapa_dados.impostos_mensais or '' }}" placeholder="25.000" class="moeda-input"></div>
          <div class="hint">DAS, IRPJ, CSLL, PIS, COFINS...</div>
        </div>
      </div>
    </div>
  </div>

  {# ── ETAPA 4: Balanço ── #}
  {% elif etapa == 4 %}
  <div class="wiz-card">
    <h5 class="mb-3">⚖️ Balanço — Ativos e Passivos</h5>
    <div class="wiz-secao">Ativo Circulante</div>
    <div class="row g-3">
      <div class="col-md-4">
        <div class="wiz-field">
          <label>Caixa e banco disponível <span class="text-danger">*</span></label>
          <div class="wiz-moeda-wrap"><span class="wiz-moeda"></span>
          <input type="text" name="caixa_disponivel" value="{{ etapa_dados.caixa_disponivel or '' }}" placeholder="150.000" class="moeda-input"></div>
          <div class="hint">Saldo em conta + caixa físico</div>
        </div>
      </div>
      <div class="col-md-4">
        <div class="wiz-field">
          <label>Contas a receber — até 30 dias</label>
          <div class="wiz-moeda-wrap"><span class="wiz-moeda"></span>
          <input type="text" name="contas_receber_30d" value="{{ etapa_dados.contas_receber_30d or '' }}" placeholder="80.000" class="moeda-input"></div>
        </div>
      </div>
      <div class="col-md-4">
        <div class="wiz-field">
          <label>Contas a receber — 31 a 60 dias</label>
          <div class="wiz-moeda-wrap"><span class="wiz-moeda"></span>
          <input type="text" name="contas_receber_60d" value="{{ etapa_dados.contas_receber_60d or '' }}" placeholder="60.000" class="moeda-input"></div>
        </div>
      </div>
      <div class="col-md-4">
        <div class="wiz-field">
          <label>Contas a receber — 61 a 90 dias</label>
          <div class="wiz-moeda-wrap"><span class="wiz-moeda"></span>
          <input type="text" name="contas_receber_90d" value="{{ etapa_dados.contas_receber_90d or '' }}" placeholder="40.000" class="moeda-input"></div>
        </div>
      </div>
      <div class="col-md-4">
        <div class="wiz-field">
          <label>Total a receber (acima de 90d + total)</label>
          <div class="wiz-moeda-wrap"><span class="wiz-moeda"></span>
          <input type="text" name="contas_receber_total" value="{{ etapa_dados.contas_receber_total or '' }}" placeholder="200.000" class="moeda-input"></div>
          <div class="hint">Inclui tudo, mesmo vencido</div>
        </div>
      </div>
      <div class="col-md-4">
        <div class="wiz-field">
          <label>Estoque</label>
          <div class="wiz-moeda-wrap"><span class="wiz-moeda"></span>
          <input type="text" name="estoque" value="{{ etapa_dados.estoque or '' }}" placeholder="120.000" class="moeda-input"></div>
          <div class="hint">Valor a custo</div>
        </div>
      </div>
    </div>
    <div class="wiz-secao mt-3">Passivo — Obrigações</div>
    <div class="row g-3">
      <div class="col-md-4">
        <div class="wiz-field">
          <label>Contas a pagar — curto prazo</label>
          <div class="wiz-moeda-wrap"><span class="wiz-moeda"></span>
          <input type="text" name="contas_pagar_cp" value="{{ etapa_dados.contas_pagar_cp or '' }}" placeholder="90.000" class="moeda-input"></div>
          <div class="hint">Fornecedores, impostos, salários a pagar</div>
        </div>
      </div>
      <div class="col-md-4">
        <div class="wiz-field">
          <label>Contas a pagar — longo prazo</label>
          <div class="wiz-moeda-wrap"><span class="wiz-moeda"></span>
          <input type="text" name="contas_pagar_lp" value="{{ etapa_dados.contas_pagar_lp or '' }}" placeholder="30.000" class="moeda-input"></div>
        </div>
      </div>
      <div class="col-md-4">
        <div class="wiz-field">
          <label>Dívidas bancárias — curto prazo</label>
          <div class="wiz-moeda-wrap"><span class="wiz-moeda"></span>
          <input type="text" name="dividas_cp" value="{{ etapa_dados.dividas_cp or '' }}" placeholder="200.000" class="moeda-input"></div>
          <div class="hint">Parcelas vencendo em até 12 meses</div>
        </div>
      </div>
      <div class="col-md-4">
        <div class="wiz-field">
          <label>Dívidas bancárias — longo prazo</label>
          <div class="wiz-moeda-wrap"><span class="wiz-moeda"></span>
          <input type="text" name="dividas_lp" value="{{ etapa_dados.dividas_lp or '' }}" placeholder="500.000" class="moeda-input"></div>
          <div class="hint">Saldo devedor acima de 12 meses</div>
        </div>
      </div>
      <div class="col-md-4">
        <div class="wiz-field">
          <label>Garantias disponíveis</label>
          <div class="wiz-moeda-wrap"><span class="wiz-moeda"></span>
          <input type="text" name="garantias" value="{{ etapa_dados.garantias or '' }}" placeholder="800.000" class="moeda-input"></div>
          <div class="hint">Imóveis, veículos, recebíveis alienados</div>
        </div>
      </div>
      <div class="col-md-4">
        <div class="wiz-field">
          <label>Patrimônio líquido estimado</label>
          <div class="wiz-moeda-wrap"><span class="wiz-moeda"></span>
          <input type="text" name="patrimonio_liquido" value="{{ etapa_dados.patrimonio_liquido or '' }}" placeholder="400.000" class="moeda-input"></div>
          <div class="hint">Ativo total menos passivo total</div>
        </div>
      </div>
    </div>
  </div>

  {# ── ETAPA 5: Processos ── #}
  {% elif etapa == 5 %}
  <div class="wiz-card">
    <h5 class="mb-3">⚙️ Processos e Governança</h5>
    <div class="muted small mb-3">Responda com base na realidade atual da empresa — não no ideal.</div>

    {% set secoes_vistas = [] %}
    {% for q in survey %}
      {% if q.section not in secoes_vistas %}
        {% set _ = secoes_vistas.append(q.section) %}
        <div class="wiz-secao">{{ q.section }}</div>
      {% endif %}
      <div class="wiz-bool" onclick="toggleBool('{{ q.id }}')">
        <input type="checkbox" name="{{ q.id }}" value="1" id="q_{{ q.id }}"
               {% if etapa_dados.get(q.id) %}checked{% endif %}>
        <label for="q_{{ q.id }}">{{ q.q }}</label>
      </div>
    {% endfor %}

    <div class="wiz-secao">Governança Avançada</div>
    {% for k, label in [
      ("planejamento_estrategico", "A empresa tem planejamento estratégico formal (anual/plurianual)?"),
      ("reuniao_diretoria", "Existe reunião de diretoria ou conselho com ata e frequência definida?"),
      ("auditoria_interna", "Há auditoria interna ou controle interno estruturado?"),
      ("compliance_fiscal", "A empresa possui área ou responsável por compliance fiscal?"),
      ("seguro_empresarial", "Possui seguro empresarial (patrimonial, responsabilidade civil)?"),
      ("sucessao_definida", "O plano de sucessão da empresa está definido e documentado?"),
    ] %}
    <div class="wiz-bool" onclick="toggleBool('{{ k }}')">
      <input type="checkbox" name="{{ k }}" value="1" id="q_{{ k }}"
             {% if etapa_dados.get(k) %}checked{% endif %}>
      <label for="q_{{ k }}">{{ label }}</label>
    </div>
    {% endfor %}
  </div>
  {% endif %}

  <div class="wiz-nav">
    {% if etapa > 1 %}
    <a href="/perfil/wizard?etapa={{ etapa - 1 }}" class="btn btn-outline-secondary">
      ← Anterior
    </a>
    {% else %}
    <a href="/perfil" class="btn btn-outline-secondary">Cancelar</a>
    {% endif %}

    <div class="d-flex gap-2">
      <span class="muted small align-self-center">Etapa {{ etapa }} de 5</span>
      <button type="submit" class="btn btn-primary">
        {% if etapa == 5 %}✅ Concluir diagnóstico{% else %}Salvar e continuar →{% endif %}
      </button>
    </div>
  </div>
</form>

<script>
function toggleBool(id) {
  const cb = document.getElementById('q_' + id);
  if (cb) cb.checked = !cb.checked;
}

// Máscara monetária simples
document.querySelectorAll('.moeda-input').forEach(function(el) {
  el.addEventListener('input', function() {
    let v = this.value.replace(/\D/g, '');
    if (!v) { this.value = ''; return; }
    v = (parseInt(v) / 100).toFixed(2);
    this.value = parseFloat(v).toLocaleString('pt-BR', {minimumFractionDigits: 2});
  });
});
</script>
{% endblock %}
"""

# ── Adiciona link no /perfil para o wizard ────────────────────────────────────
_pfb = TEMPLATES.get("perfil_snapshot_new.html", "")
if not _pfb:
    TEMPLATES["perfil_redirect.html"] = ""

# Adiciona ao FEATURE_KEYS
if "wizard_diagnostico" not in FEATURE_KEYS:
    FEATURE_KEYS["wizard_diagnostico"] = {
        "title": "Diagnóstico",
        "desc":  "Wizard completo de diagnóstico financeiro.",
        "href":  "/perfil/wizard",
    }

if hasattr(templates_env.loader, "mapping"):
    templates_env.loader.mapping = TEMPLATES

print("[wizard] Patch de diagnóstico carregado.")

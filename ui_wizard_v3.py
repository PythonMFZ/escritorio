# ============================================================================
# ui_wizard_v3.py — Wizard de Diagnóstico v3
# Adapta labels e campos por setor preservando 100% dos indicadores do v2.
# Setores: Construção Civil | Indústria | Comércio | Serviços (e genérico)
# Novos campos capturados (etapa 2, construtora): backlog_carteira, vgv_total,
#   vso_pct, pct_executado.
# ============================================================================

import json as _json_wiz3

# ── Remove apenas GET e POST do wizard (finalizar e snapshot_detail mantidos) ─

_wiz3_paths = {"/perfil/wizard", "/perfil/wizard/salvar"}
app.routes[:] = [
    r for r in app.routes
    if not (hasattr(r, "path") and r.path in _wiz3_paths)
]


def _fv3(v) -> float:
    try:
        if v is None or v == "":
            return 0.0
        s = str(v).replace("R$", "").replace(" ", "").strip()
        if "," in s:
            s = s.replace(".", "").replace(",", ".")
        return float(s)
    except Exception:
        return 0.0


# ── GET /perfil/wizard ────────────────────────────────────────────────────────

@app.get("/perfil/wizard", response_class=HTMLResponse)
@require_login
async def wizard_get_v3(request: Request, session: Session = Depends(get_session)):
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

    # Segmento salvo na etapa 1 — usado para adaptar etapas 2-4
    segmento = dados.get("etapa_1", {}).get("segmento", "")

    try:
        profile = get_or_create_business_profile(session,
                                                  company_id=ctx.company.id,
                                                  client_id=cc.id)
    except Exception:
        profile = None

    return render("wizard_diagnostico.html", request=request, context={
        "current_user":      ctx.user,
        "current_company":   ctx.company,
        "role":              ctx.membership.role,
        "current_client":    cc,
        "etapa":             etapa,
        "etapa_atual_salva": rascunho.etapa_atual,
        "dados":             dados,
        "etapa_dados":       dados.get(f"etapa_{etapa}", {}),
        "survey":            PROFILE_SURVEY_V2,
        "profile":           profile,
        "segmento":          segmento,
    })


# ── POST /perfil/wizard/salvar ────────────────────────────────────────────────

@app.post("/perfil/wizard/salvar")
@require_login
async def wizard_salvar_v3(request: Request, session: Session = Depends(get_session)):
    ctx = get_tenant_context(request, session)
    if not ctx:
        return RedirectResponse("/login", status_code=303)

    cc = get_client_or_none(session, ctx.company.id,
                            get_active_client_id(request, session, ctx))
    if not cc:
        return RedirectResponse("/perfil", status_code=303)

    form  = await request.form()
    etapa = int(form.get("etapa", 1))

    rascunho    = _wiz_get_rascunho(session, ctx.company.id, cc.id)
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
            "funcionarios":      int(form.get("funcionarios") or 0),
        }

    elif etapa == 2:
        dados_etapa = {
            # Campos base — todos os setores
            "faturamento_bruto_mensal":  _fv3(form.get("faturamento_bruto_mensal")),
            "faturamento_medio_12m":     _fv3(form.get("faturamento_medio_12m")),
            "ticket_medio":              _fv3(form.get("ticket_medio")),
            "inadimplencia_pct":         _fv3(form.get("inadimplencia_pct")),
            "receita_recorrente_pct":    _fv3(form.get("receita_recorrente_pct")),
            "sazonalidade":              form.get("sazonalidade", ""),
            "principais_produtos":       form.get("principais_produtos", ""),
            "clientes_ativos":           int(form.get("clientes_ativos") or 0),
            "maior_cliente_pct":         _fv3(form.get("maior_cliente_pct")),
            # Campos extras — Construção Civil / Imobiliário
            "backlog_carteira":          _fv3(form.get("backlog_carteira")),
            "vgv_total":                 _fv3(form.get("vgv_total")),
            "vso_pct":                   _fv3(form.get("vso_pct")),
            "pct_executado":             _fv3(form.get("pct_executado")),
        }

    elif etapa == 3:
        dados_etapa = {
            # Deduções
            "impostos_mensais":      _fv3(form.get("impostos_mensais")),
            "comissoes_mensal":      _fv3(form.get("comissoes_mensal")),
            "fretes_mensal":         _fv3(form.get("fretes_mensal")),
            "outras_deducoes":       _fv3(form.get("outras_deducoes")),
            # Custos Operacionais
            "mao_obra_direta":       _fv3(form.get("mao_obra_direta")),
            "produtos_insumos":      _fv3(form.get("produtos_insumos")),
            "custos_fabris":         _fv3(form.get("custos_fabris")),
            # Despesas Fixas
            "mao_obra_admin":        _fv3(form.get("mao_obra_admin")),
            "pro_labore":            _fv3(form.get("pro_labore")),
            "aluguel":               _fv3(form.get("aluguel")),
            "outras_despesas_fixas": _fv3(form.get("outras_despesas_fixas")),
            # Empréstimos e Investimentos
            "parcelas_maquinas":     _fv3(form.get("parcelas_maquinas")),
            "parcelas_imobilizados": _fv3(form.get("parcelas_imobilizados")),
            "parcelas_emprestimos":  _fv3(form.get("parcelas_emprestimos")),
        }

    elif etapa == 4:
        def _e4(k): return _fv3(form.get(k))
        dados_etapa = {
            # Ativo Circulante
            "caixa_disponivel": _e4("caixa_disponivel"),
            "ac_cr_30d":        _e4("ac_cr_30d"),
            "ac_cr_60d":        _e4("ac_cr_60d"),
            "ac_cr_90d":        _e4("ac_cr_90d"),
            "ac_cr_360d":       _e4("ac_cr_360d"),
            "ac_est_mp":        _e4("ac_est_mp"),
            "ac_est_wip":       _e4("ac_est_wip"),
            "ac_est_acab":      _e4("ac_est_acab"),
            "ac_outros":        _e4("ac_outros"),
            # Ativo Não-circulante
            "anc_cr_361d":      _e4("anc_cr_361d"),
            "anc_est_dificil":  _e4("anc_est_dificil"),
            "anc_veiculos":     _e4("anc_veiculos"),
            "anc_bens_moveis":  _e4("anc_bens_moveis"),
            "anc_imoveis":      _e4("anc_imoveis"),
            "anc_intangiveis":  _e4("anc_intangiveis"),
            "anc_outros":       _e4("anc_outros"),
            # Passivo Circulante — aging
            "pc_forn_venc": _e4("pc_forn_venc"), "pc_forn_30d": _e4("pc_forn_30d"),
            "pc_forn_60d":  _e4("pc_forn_60d"),  "pc_forn_90d": _e4("pc_forn_90d"),
            "pc_forn_360d": _e4("pc_forn_360d"),
            "pc_emp_venc":  _e4("pc_emp_venc"),  "pc_emp_30d":  _e4("pc_emp_30d"),
            "pc_emp_60d":   _e4("pc_emp_60d"),   "pc_emp_90d":  _e4("pc_emp_90d"),
            "pc_emp_360d":  _e4("pc_emp_360d"),
            "pc_trib_venc": _e4("pc_trib_venc"), "pc_trib_30d": _e4("pc_trib_30d"),
            "pc_trib_60d":  _e4("pc_trib_60d"),  "pc_trib_90d": _e4("pc_trib_90d"),
            "pc_trib_360d": _e4("pc_trib_360d"),
            "pc_trab_venc": _e4("pc_trab_venc"), "pc_trab_30d": _e4("pc_trab_30d"),
            "pc_trab_60d":  _e4("pc_trab_60d"),  "pc_trab_90d": _e4("pc_trab_90d"),
            "pc_trab_360d": _e4("pc_trab_360d"),
            "pc_out_venc":  _e4("pc_out_venc"),  "pc_out_30d":  _e4("pc_out_30d"),
            "pc_out_60d":   _e4("pc_out_60d"),   "pc_out_90d":  _e4("pc_out_90d"),
            "pc_out_360d":  _e4("pc_out_360d"),
            # Passivo Não-circulante
            "pnc_forn": _e4("pnc_forn"), "pnc_emp":  _e4("pnc_emp"),
            "pnc_trib": _e4("pnc_trib"), "pnc_trab": _e4("pnc_trab"),
            "pnc_out":  _e4("pnc_out"),
            # Outros
            "garantias":          _e4("garantias"),
            "patrimonio_liquido": _e4("patrimonio_liquido"),
        }

    elif etapa == 5:
        for q in PROFILE_SURVEY_V2:
            dados_etapa[q["id"]] = form.get(q["id"]) == "1"
        for k in ["planejamento_estrategico", "reuniao_diretoria", "auditoria_interna",
                  "compliance_fiscal", "seguro_empresarial", "sucessao_definida"]:
            dados_etapa[k] = form.get(k) == "1"

    _wiz_salvar_etapa(session, rascunho, etapa, dados_etapa)

    if etapa == 5:
        return RedirectResponse("/perfil/wizard/finalizar", status_code=303)

    return RedirectResponse(f"/perfil/wizard?etapa={etapa + 1}", status_code=303)


# ── Template: wizard_diagnostico.html (v3 — setor-aware) ─────────────────────

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
  .wiz-autofill{background:#f0fdf4;border:1px solid #bbf7d0;border-radius:8px;padding:.4rem .75rem;font-size:.75rem;color:#166534;margin-bottom:.75rem;}
  .wiz-setor-badge{background:#eff6ff;border:1px solid #bfdbfe;border-radius:8px;padding:.4rem .85rem;font-size:.75rem;color:#1e40af;margin-bottom:.75rem;display:flex;align-items:center;gap:.5rem;}
  .aging-table{width:100%;border-collapse:collapse;font-size:.8rem;margin-top:.5rem;}
  .aging-table th{background:#f8f9fa;padding:.4rem .5rem;text-align:center;border:1px solid var(--mc-border);font-weight:600;white-space:nowrap;}
  .aging-table th.row-label{text-align:left;min-width:140px;}
  .aging-table td{padding:.35rem .4rem;border:1px solid var(--mc-border);}
  .aging-table input{border:none;width:100%;min-width:90px;font-size:.8rem;text-align:right;background:transparent;outline:none;padding:.15rem .25rem;}
  .aging-table input:focus{background:#fffbeb;}
  .aging-table tr:hover td{background:#fafafa;}
</style>

{# ── Flags de setor ── #}
{% set is_cc   = segmento in ["Construção Civil", "Imobiliário"] %}
{% set is_ind  = segmento == "Indústria" %}
{% set is_com  = segmento == "Comércio" %}
{% set is_serv = segmento in ["Serviços", "Saúde", "Tecnologia", "Educação", "Agronegócio"] %}

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

<div class="wiz-progress">
  <div class="wiz-progress-bar" style="width:{{ (etapa / 5 * 100)|int }}%"></div>
</div>

<div class="wiz-steps">
  {% for n, label in etapas %}
  <a href="/perfil/wizard?etapa={{ n }}"
     class="wiz-step {% if n == etapa %}ativa{% elif n < etapa_atual_salva %}concluida{% elif n > etapa_atual_salva %}bloqueada{% endif %}"
     {% if n > etapa_atual_salva %}onclick="return false"{% endif %}>
    {% if n < etapa_atual_salva %}✅ {% endif %}{{ label }}
  </a>
  {% endfor %}
</div>

{# Badge de setor (etapas 2-4) #}
{% if etapa > 1 and etapa < 5 and segmento %}
<div class="wiz-setor-badge">
  📌 Formulário adaptado para <strong>{{ segmento }}</strong>
  &nbsp;·&nbsp;
  <a href="/perfil/wizard?etapa=1" style="color:#1e40af;font-weight:600;">alterar setor</a>
</div>
{% endif %}

<form method="post" action="/perfil/wizard/salvar">
  <input type="hidden" name="etapa" value="{{ etapa }}">

  {# ═══════════════════════════════════════════════════════════════════════════
     ETAPA 1: Empresa
  ═══════════════════════════════════════════════════════════════════════════ #}
  {% if etapa == 1 %}
  {% set p = profile %}
  <div class="wiz-autofill">
    ✅ Campos marcados foram preenchidos automaticamente com os dados cadastrados — confira e ajuste se necessário.
  </div>
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
          <input type="text" name="cnpj" value="{{ etapa_dados.cnpj or current_client.cnpj or '' }}" placeholder="00.000.000/0001-00">
        </div>
      </div>
      <div class="col-md-4">
        <div class="wiz-field">
          <label>Setor de Atividade <span class="text-danger">*</span></label>
          <select name="segmento">
            <option value="">— Selecione —</option>
            {% for s in ["Construção Civil", "Imobiliário", "Indústria", "Comércio", "Serviços", "Agronegócio", "Saúde", "Tecnologia", "Educação", "Outro"] %}
            {% set sel = etapa_dados.segmento or (p.segment if p else "") %}
            <option value="{{ s }}" {% if sel == s %}selected{% endif %}>{{ s }}</option>
            {% endfor %}
          </select>
          <div class="hint">O formulário das próximas etapas será adaptado ao setor selecionado</div>
        </div>
      </div>
      <div class="col-md-4">
        <div class="wiz-field">
          <label>Porte</label>
          <select name="porte">
            <option value="">— Selecione —</option>
            {% for pp2 in ["MEI", "Microempresa (ME)", "Pequena empresa (EPP)", "Média empresa", "Grande empresa"] %}
            {% set sel = etapa_dados.porte or (p.company_size if p else "") %}
            <option value="{{ pp2 }}" {% if sel == pp2 %}selected{% endif %}>{{ pp2 }}</option>
            {% endfor %}
          </select>
        </div>
      </div>
      <div class="col-md-4">
        <div class="wiz-field">
          <label>Regime Tributário</label>
          <select name="regime_tributario">
            <option value="">— Selecione —</option>
            {% for r in ["Simples Nacional", "Lucro Presumido", "Lucro Real", "MEI"] %}
            {% set sel = etapa_dados.regime_tributario or (p.tax_regime if p else "") %}
            <option value="{{ r }}" {% if sel == r %}selected{% endif %}>{{ r }}</option>
            {% endfor %}
          </select>
        </div>
      </div>
      <div class="col-md-4">
        <div class="wiz-field">
          <label>Cidade</label>
          <input type="text" name="cidade" value="{{ etapa_dados.cidade or current_client.city or '' }}" placeholder="Ex: Brusque">
        </div>
      </div>
      <div class="col-md-2">
        <div class="wiz-field">
          <label>UF</label>
          <input type="text" name="uf" value="{{ etapa_dados.uf or current_client.state or '' }}" placeholder="SC" maxlength="2">
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
      <div class="col-md-3">
        <div class="wiz-field">
          <label>Funcionários</label>
          <input type="number" name="funcionarios" value="{{ etapa_dados.funcionarios or current_client.employees_count or '' }}" min="0" placeholder="12">
        </div>
      </div>
      <div class="col-12">
        <div class="wiz-field">
          <label>CNAE principal <span class="muted">(opcional)</span></label>
          <input type="text" name="cnae" value="{{ etapa_dados.cnae or (p.cnae if p else '') }}" placeholder="Ex: 4711-3/02 — Comércio varejista">
        </div>
      </div>
    </div>
  </div>

  {# ═══════════════════════════════════════════════════════════════════════════
     ETAPA 2: Receitas — adaptada por setor
  ═══════════════════════════════════════════════════════════════════════════ #}
  {% elif etapa == 2 %}
  <div class="wiz-card">
    <h5 class="mb-3">📈 Receitas e Vendas</h5>
    <div class="row g-3">
      <div class="col-md-6">
        <div class="wiz-field">
          <label>Faturamento bruto mensal <span class="text-danger">*</span></label>
          <div class="wiz-moeda-wrap"><span class="wiz-moeda"></span>
          <input type="text" name="faturamento_bruto_mensal" value="{{ etapa_dados.faturamento_bruto_mensal or '' }}" placeholder="500.000" class="moeda-input"></div>
          <div class="hint">Média dos últimos 3 meses — base para todos os cálculos</div>
        </div>
      </div>
      <div class="col-md-6">
        <div class="wiz-field">
          <label>Faturamento médio últimos 12 meses</label>
          <div class="wiz-moeda-wrap"><span class="wiz-moeda"></span>
          <input type="text" name="faturamento_medio_12m" value="{{ etapa_dados.faturamento_medio_12m or '' }}" placeholder="480.000" class="moeda-input"></div>
          <div class="hint">Revela tendência: se menor que o mensal = crescimento; se maior = queda</div>
        </div>
      </div>

      {# Ticket médio — renomeado para construtora, oculto para serviços puros #}
      {% if not is_serv %}
      <div class="col-md-4">
        <div class="wiz-field">
          <label>{{ 'Valor médio por contrato / obra' if is_cc else 'Ticket médio por venda' }}</label>
          <div class="wiz-moeda-wrap"><span class="wiz-moeda"></span>
          <input type="text" name="ticket_medio" value="{{ etapa_dados.ticket_medio or '' }}" placeholder="{{ '250.000' if is_cc else '2.500' }}" class="moeda-input"></div>
        </div>
      </div>
      {% endif %}

      <div class="col-md-4">
        <div class="wiz-field">
          <label>Inadimplência atual (%)</label>
          <input type="number" name="inadimplencia_pct" value="{{ etapa_dados.inadimplencia_pct or '' }}" min="0" max="100" step="0.1" placeholder="3.5">
          <div class="hint">% do faturamento não recebido</div>
        </div>
      </div>

      {# Receita recorrente — oculta para construtora (não se aplica), adaptada para serviços #}
      {% if not is_cc %}
      <div class="col-md-4">
        <div class="wiz-field">
          <label>{{ 'Contratos / mensalidades fixas (%)' if is_serv else 'Receita recorrente (%)' }}</label>
          <input type="number" name="receita_recorrente_pct" value="{{ etapa_dados.receita_recorrente_pct or '' }}" min="0" max="100" step="1" placeholder="40">
          <div class="hint">% que se repete todo mês</div>
        </div>
      </div>
      {% endif %}

      <div class="col-md-4">
        <div class="wiz-field">
          <label>{{ 'Obras / contratos ativos' if is_cc else ('Contratos ativos' if is_serv else 'Clientes ativos') }}</label>
          <input type="number" name="clientes_ativos" value="{{ etapa_dados.clientes_ativos or '' }}" min="0" placeholder="{{ '8' if is_cc else '85' }}">
        </div>
      </div>

      <div class="col-md-4">
        <div class="wiz-field">
          <label>{{ 'Maior contrato = % do faturamento' if is_cc else 'Maior cliente = % do faturamento' }}</label>
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

      {# Campos exclusivos Construção Civil / Imobiliário #}
      {% if is_cc %}
      <div class="col-12"><div class="wiz-secao">Indicadores de Obra / Incorporação</div></div>
      <div class="col-md-6">
        <div class="wiz-field">
          <label>Backlog em carteira</label>
          <div class="wiz-moeda-wrap"><span class="wiz-moeda"></span>
          <input type="text" name="backlog_carteira" value="{{ etapa_dados.backlog_carteira or '' }}" placeholder="2.500.000" class="moeda-input"></div>
          <div class="hint">Contratos assinados ainda não faturados</div>
        </div>
      </div>
      <div class="col-md-6">
        <div class="wiz-field">
          <label>VGV total em andamento</label>
          <div class="wiz-moeda-wrap"><span class="wiz-moeda"></span>
          <input type="text" name="vgv_total" value="{{ etapa_dados.vgv_total or '' }}" placeholder="8.000.000" class="moeda-input"></div>
          <div class="hint">Valor Geral de Vendas dos empreendimentos ativos</div>
        </div>
      </div>
      <div class="col-md-4">
        <div class="wiz-field">
          <label>VSO — % do VGV já vendido</label>
          <input type="number" name="vso_pct" value="{{ etapa_dados.vso_pct or '' }}" min="0" max="100" step="0.1" placeholder="65">
          <div class="hint">Velocidade de Vendas sobre Oferta</div>
        </div>
      </div>
      <div class="col-md-4">
        <div class="wiz-field">
          <label>% do VGV já executado (físico)</label>
          <input type="number" name="pct_executado" value="{{ etapa_dados.pct_executado or '' }}" min="0" max="100" step="0.1" placeholder="40">
          <div class="hint">Avanço físico médio das obras</div>
        </div>
      </div>
      {% endif %}

      <div class="col-12">
        <div class="wiz-field">
          <label>Principais {{ 'obras / serviços' if is_cc else ('produtos / serviços' if is_serv else 'produtos') }}</label>
          <textarea name="principais_produtos" rows="2" placeholder="{{ 'Ex: Construção residencial, incorporação de apartamentos...' if is_cc else ('Ex: Personal training, aulas em grupo, fisioterapia...' if is_serv else 'Ex: Confecção de camisetas, jeans, moda feminina...') }}">{{ etapa_dados.principais_produtos or '' }}</textarea>
        </div>
      </div>
    </div>
  </div>

  {# ═══════════════════════════════════════════════════════════════════════════
     ETAPA 3: Custos — grupos e labels adaptados por setor
  ═══════════════════════════════════════════════════════════════════════════ #}
  {% elif etapa == 3 %}
  <div class="wiz-card">
    <h5 class="mb-3">💸 Custos e Despesas Mensais</h5>

    {# ── 1. Deduções ── #}
    <div class="wiz-secao">1 · Deduções da Receita</div>
    <div class="row g-3">
      <div class="col-md-3">
        <div class="wiz-field">
          <label>Impostos <span class="text-danger">*</span></label>
          <div class="wiz-moeda-wrap"><span class="wiz-moeda"></span>
          <input type="text" name="impostos_mensais" value="{{ etapa_dados.impostos_mensais or '' }}" placeholder="45.000" class="moeda-input"></div>
          <div class="hint">DAS, IRPJ, CSLL, PIS, COFINS</div>
        </div>
      </div>
      <div class="col-md-3">
        <div class="wiz-field">
          <label>{{ 'Comissões de vendas' if is_cc else 'Comissões' }}</label>
          <div class="wiz-moeda-wrap"><span class="wiz-moeda"></span>
          <input type="text" name="comissoes_mensal" value="{{ etapa_dados.comissoes_mensal or '' }}" placeholder="{{ '15.000' if is_cc else '8.000' }}" class="moeda-input"></div>
          <div class="hint">{{ 'Corretoras, agentes imobiliários' if is_cc else 'Vendedores, representantes' }}</div>
        </div>
      </div>
      {% if not is_serv %}
      <div class="col-md-3">
        <div class="wiz-field">
          <label>{{ 'Fretes e logística de obra' if is_cc else 'Fretes' }}</label>
          <div class="wiz-moeda-wrap"><span class="wiz-moeda"></span>
          <input type="text" name="fretes_mensal" value="{{ etapa_dados.fretes_mensal or '' }}" placeholder="5.000" class="moeda-input"></div>
          <div class="hint">{{ 'Transporte de materiais' if is_cc else ('Fretes de entrega' if is_com else 'CIF, transporte') }}</div>
        </div>
      </div>
      {% endif %}
      <div class="col-md-3">
        <div class="wiz-field">
          <label>Outras deduções</label>
          <div class="wiz-moeda-wrap"><span class="wiz-moeda"></span>
          <input type="text" name="outras_deducoes" value="{{ etapa_dados.outras_deducoes or '' }}" placeholder="2.000" class="moeda-input"></div>
          <div class="hint">Devoluções, abatimentos</div>
        </div>
      </div>
    </div>

    {# ── 2. Custos Operacionais ── #}
    <div class="wiz-secao">2 · Custos Operacionais (CPV / CPP)</div>
    <div class="row g-3">
      <div class="col-md-4">
        <div class="wiz-field">
          <label>
            {% if is_cc %}Mão de Obra de Obra (execução)
            {% elif is_serv %}Equipe Operacional
            {% else %}Mão de Obra Direta{% endif %}
            <span class="text-danger">*</span>
          </label>
          <div class="wiz-moeda-wrap"><span class="wiz-moeda"></span>
          <input type="text" name="mao_obra_direta" value="{{ etapa_dados.mao_obra_direta or '' }}" placeholder="60.000" class="moeda-input"></div>
          <div class="hint">
            {% if is_cc %}Folha + encargos da equipe de obra
            {% elif is_serv %}Folha + encargos de quem presta o serviço
            {% else %}Folha + encargos dos que produzem/vendem{% endif %}
          </div>
        </div>
      </div>
      <div class="col-md-4">
        <div class="wiz-field">
          <label>
            {% if is_cc %}Materiais de Construção
            {% elif is_com %}CMV — Custo das Mercadorias
            {% elif is_serv %}Insumos do Serviço
            {% else %}Matérias-primas e Insumos{% endif %}
            <span class="text-danger">*</span>
          </label>
          <div class="wiz-moeda-wrap"><span class="wiz-moeda"></span>
          <input type="text" name="produtos_insumos" value="{{ etapa_dados.produtos_insumos or '' }}" placeholder="120.000" class="moeda-input"></div>
          <div class="hint">
            {% if is_cc %}Materiais, concreto, aço, acabamentos
            {% elif is_com %}Custo de aquisição das mercadorias revendidas
            {% elif is_serv %}Materiais e insumos consumidos na prestação
            {% else %}Matéria-prima, embalagens, componentes{% endif %}
          </div>
        </div>
      </div>
      <div class="col-md-4">
        <div class="wiz-field">
          <label>
            {% if is_cc %}BDI e custos indiretos de obra
            {% elif is_ind %}Custos Fabris / Produção
            {% else %}Outros custos operacionais{% endif %}
          </label>
          <div class="wiz-moeda-wrap"><span class="wiz-moeda"></span>
          <input type="text" name="custos_fabris" value="{{ etapa_dados.custos_fabris or '' }}" placeholder="15.000" class="moeda-input"></div>
          <div class="hint">
            {% if is_cc %}Administração de obra, seguros, ART, taxas
            {% elif is_ind %}Energia, manutenção, depreciação produtiva
            {% elif is_com %}Energia, embalagens, perdas
            {% else %}Outros custos diretos{% endif %}
          </div>
        </div>
      </div>
    </div>

    {# ── 3. Despesas Fixas ── #}
    <div class="wiz-secao">3 · Despesas Fixas (SG&amp;A)</div>
    <div class="row g-3">
      <div class="col-md-3">
        <div class="wiz-field">
          <label>Mão de Obra Administrativa</label>
          <div class="wiz-moeda-wrap"><span class="wiz-moeda"></span>
          <input type="text" name="mao_obra_admin" value="{{ etapa_dados.mao_obra_admin or '' }}" placeholder="25.000" class="moeda-input"></div>
          <div class="hint">Backoffice, financeiro, RH</div>
        </div>
      </div>
      <div class="col-md-3">
        <div class="wiz-field">
          <label>Pró-labore dos Sócios</label>
          <div class="wiz-moeda-wrap"><span class="wiz-moeda"></span>
          <input type="text" name="pro_labore" value="{{ etapa_dados.pro_labore or '' }}" placeholder="15.000" class="moeda-input"></div>
        </div>
      </div>
      <div class="col-md-3">
        <div class="wiz-field">
          <label>Aluguel</label>
          <div class="wiz-moeda-wrap"><span class="wiz-moeda"></span>
          <input type="text" name="aluguel" value="{{ etapa_dados.aluguel or '' }}" placeholder="8.000" class="moeda-input"></div>
        </div>
      </div>
      <div class="col-md-3">
        <div class="wiz-field">
          <label>Outras Despesas Fixas</label>
          <div class="wiz-moeda-wrap"><span class="wiz-moeda"></span>
          <input type="text" name="outras_despesas_fixas" value="{{ etapa_dados.outras_despesas_fixas or '' }}" placeholder="12.000" class="moeda-input"></div>
          <div class="hint">Internet, seguros, contabilidade</div>
        </div>
      </div>
    </div>

    {# ── 4. Empréstimos e Investimentos ── #}
    <div class="wiz-secao">4 · Parcelas Mensais (Empréstimos e Investimentos)</div>
    <div class="row g-3">
      <div class="col-md-4">
        <div class="wiz-field">
          <label>{{ 'Parcelas de Equipamentos de Obra' if is_cc else 'Parcelas de Máquinas' }}</label>
          <div class="wiz-moeda-wrap"><span class="wiz-moeda"></span>
          <input type="text" name="parcelas_maquinas" value="{{ etapa_dados.parcelas_maquinas or '' }}" placeholder="5.000" class="moeda-input"></div>
          <div class="hint">Leasing / financiamento de equipamentos</div>
        </div>
      </div>
      <div class="col-md-4">
        <div class="wiz-field">
          <label>{{ 'Parcelas de Terrenos / Imóveis' if is_cc else 'Parcelas de Imobilizados' }}</label>
          <div class="wiz-moeda-wrap"><span class="wiz-moeda"></span>
          <input type="text" name="parcelas_imobilizados" value="{{ etapa_dados.parcelas_imobilizados or '' }}" placeholder="3.000" class="moeda-input"></div>
          <div class="hint">{{ 'Financiamento de terrenos' if is_cc else 'Veículos, móveis, imóveis' }}</div>
        </div>
      </div>
      <div class="col-md-4">
        <div class="wiz-field">
          <label>Parcelas de Empréstimos</label>
          <div class="wiz-moeda-wrap"><span class="wiz-moeda"></span>
          <input type="text" name="parcelas_emprestimos" value="{{ etapa_dados.parcelas_emprestimos or '' }}" placeholder="18.000" class="moeda-input"></div>
          <div class="hint">Capital de giro, BNDES, banco</div>
        </div>
      </div>
    </div>
  </div>

  {# ═══════════════════════════════════════════════════════════════════════════
     ETAPA 4: Balanço — labels adaptados por setor
  ═══════════════════════════════════════════════════════════════════════════ #}
  {% elif etapa == 4 %}
  <div class="wiz-card">
    <h5 class="mb-3">⚖️ Balanço Patrimonial</h5>

    {# ── Ativo Circulante ── #}
    <div class="wiz-secao">1 · Ativo Circulante</div>
    <div class="row g-3">
      <div class="col-md-4">
        <div class="wiz-field">
          <label>Caixa e Disponibilidades <span class="text-danger">*</span></label>
          <div class="wiz-moeda-wrap"><span class="wiz-moeda"></span>
          <input type="text" name="caixa_disponivel" value="{{ etapa_dados.caixa_disponivel or '' }}" placeholder="80.000" class="moeda-input"></div>
          <div class="hint">Conta corrente + poupança + caixa físico</div>
        </div>
      </div>
    </div>

    {# Contas a Receber — aging (igual para todos os setores) #}
    <div class="row g-3 mt-0">
      <div class="col-12"><div class="hint" style="margin-top:.5rem;">
        {{ 'Medições / recebíveis de obra — por vencimento' if is_cc else 'Contas a Receber (clientes) — por vencimento' }}
      </div></div>
      <div class="col-md-3">
        <div class="wiz-field">
          <label>CR até 30 dias</label>
          <div class="wiz-moeda-wrap"><span class="wiz-moeda"></span>
          <input type="text" name="ac_cr_30d" value="{{ etapa_dados.ac_cr_30d or '' }}" placeholder="90.000" class="moeda-input"></div>
        </div>
      </div>
      <div class="col-md-3">
        <div class="wiz-field">
          <label>CR 31–60 dias</label>
          <div class="wiz-moeda-wrap"><span class="wiz-moeda"></span>
          <input type="text" name="ac_cr_60d" value="{{ etapa_dados.ac_cr_60d or '' }}" placeholder="60.000" class="moeda-input"></div>
        </div>
      </div>
      <div class="col-md-3">
        <div class="wiz-field">
          <label>CR 61–90 dias</label>
          <div class="wiz-moeda-wrap"><span class="wiz-moeda"></span>
          <input type="text" name="ac_cr_90d" value="{{ etapa_dados.ac_cr_90d or '' }}" placeholder="40.000" class="moeda-input"></div>
        </div>
      </div>
      <div class="col-md-3">
        <div class="wiz-field">
          <label>CR 91–360 dias</label>
          <div class="wiz-moeda-wrap"><span class="wiz-moeda"></span>
          <input type="text" name="ac_cr_360d" value="{{ etapa_dados.ac_cr_360d or '' }}" placeholder="20.000" class="moeda-input"></div>
        </div>
      </div>
    </div>

    {# Estoques — labels e visibilidade por setor #}
    {% if not is_serv %}
    <div class="row g-3 mt-0">
      <div class="col-12"><div class="hint">
        {% if is_cc %}Ativos de Obra / Estoque Imobiliário
        {% elif is_com %}Estoque de Mercadorias
        {% else %}Estoques — por tipo{% endif %}
      </div></div>

      {# MP / Terrenos #}
      {% if not is_com %}
      <div class="col-md-4">
        <div class="wiz-field">
          <label>{{ 'Terrenos / Lotes' if is_cc else 'Matéria-prima' }}</label>
          <div class="wiz-moeda-wrap"><span class="wiz-moeda"></span>
          <input type="text" name="ac_est_mp" value="{{ etapa_dados.ac_est_mp or '' }}" placeholder="{{ '1.500.000' if is_cc else '50.000' }}" class="moeda-input"></div>
          {% if is_cc %}<div class="hint">Valor contábil dos terrenos em estoque</div>{% endif %}
        </div>
      </div>
      {% endif %}

      {# WIP / Obras em andamento #}
      {% if not is_com %}
      <div class="col-md-4">
        <div class="wiz-field">
          <label>{{ 'Obras em andamento (CPA)' if is_cc else 'Em processo (WIP)' }}</label>
          <div class="wiz-moeda-wrap"><span class="wiz-moeda"></span>
          <input type="text" name="ac_est_wip" value="{{ etapa_dados.ac_est_wip or '' }}" placeholder="{{ '3.200.000' if is_cc else '20.000' }}" class="moeda-input"></div>
          {% if is_cc %}<div class="hint">Custo acumulado das obras em execução</div>{% endif %}
        </div>
      </div>
      {% endif %}

      {# Produtos acabados / Unidades prontas / Estoque mercadorias #}
      <div class="col-md-4">
        <div class="wiz-field">
          <label>{{ 'Unidades prontas para venda' if is_cc else ('Estoque de mercadorias' if is_com else 'Produtos acabados') }}</label>
          <div class="wiz-moeda-wrap"><span class="wiz-moeda"></span>
          <input type="text" name="ac_est_acab" value="{{ etapa_dados.ac_est_acab or '' }}" placeholder="{{ '2.000.000' if is_cc else '70.000' }}" class="moeda-input"></div>
          {% if is_cc %}<div class="hint">Imóveis concluídos ainda não vendidos / transferidos</div>{% endif %}
        </div>
      </div>
    </div>
    {% endif %}

    <div class="row g-3 mt-0">
      <div class="col-md-4">
        <div class="wiz-field">
          <label>Outros ativos circulantes</label>
          <div class="wiz-moeda-wrap"><span class="wiz-moeda"></span>
          <input type="text" name="ac_outros" value="{{ etapa_dados.ac_outros or '' }}" placeholder="10.000" class="moeda-input"></div>
          <div class="hint">Adiantamentos, impostos a recuperar</div>
        </div>
      </div>
    </div>

    {# ── Ativo Não-circulante ── #}
    <div class="wiz-secao">2 · Ativo Não-circulante</div>
    <div class="row g-3">
      <div class="col-md-4">
        <div class="wiz-field">
          <label>CR acima de 361 dias</label>
          <div class="wiz-moeda-wrap"><span class="wiz-moeda"></span>
          <input type="text" name="anc_cr_361d" value="{{ etapa_dados.anc_cr_361d or '' }}" placeholder="0" class="moeda-input"></div>
        </div>
      </div>
      {% if not (is_com or is_serv) %}
      <div class="col-md-4">
        <div class="wiz-field">
          <label>{{ 'Obras paralisadas / distrato' if is_cc else 'Estoques de difícil saída' }}</label>
          <div class="wiz-moeda-wrap"><span class="wiz-moeda"></span>
          <input type="text" name="anc_est_dificil" value="{{ etapa_dados.anc_est_dificil or '' }}" placeholder="0" class="moeda-input"></div>
        </div>
      </div>
      {% endif %}
    </div>
    <div class="row g-3 mt-0">
      <div class="col-12"><div class="hint">Imobilizado</div></div>
      <div class="col-md-4">
        <div class="wiz-field">
          <label>Veículos</label>
          <div class="wiz-moeda-wrap"><span class="wiz-moeda"></span>
          <input type="text" name="anc_veiculos" value="{{ etapa_dados.anc_veiculos or '' }}" placeholder="120.000" class="moeda-input"></div>
        </div>
      </div>
      <div class="col-md-4">
        <div class="wiz-field">
          <label>{{ 'Máquinas e Equipamentos de Obra' if is_cc else ('Máquinas e Equipamentos' if is_ind else 'Bens Móveis') }}</label>
          <div class="wiz-moeda-wrap"><span class="wiz-moeda"></span>
          <input type="text" name="anc_bens_moveis" value="{{ etapa_dados.anc_bens_moveis or '' }}" placeholder="80.000" class="moeda-input"></div>
        </div>
      </div>
      <div class="col-md-4">
        <div class="wiz-field">
          <label>{{ 'Imóveis (sede / escritório)' if is_cc else 'Imóveis' }}</label>
          <div class="wiz-moeda-wrap"><span class="wiz-moeda"></span>
          <input type="text" name="anc_imoveis" value="{{ etapa_dados.anc_imoveis or '' }}" placeholder="500.000" class="moeda-input"></div>
          {% if is_cc %}<div class="hint">Não incluir terrenos/obras — esses vão no Ativo Circulante</div>{% endif %}
        </div>
      </div>
      <div class="col-md-4">
        <div class="wiz-field">
          <label>Intangíveis</label>
          <div class="wiz-moeda-wrap"><span class="wiz-moeda"></span>
          <input type="text" name="anc_intangiveis" value="{{ etapa_dados.anc_intangiveis or '' }}" placeholder="0" class="moeda-input"></div>
          <div class="hint">Marcas, patentes, software, alvará</div>
        </div>
      </div>
      <div class="col-md-4">
        <div class="wiz-field">
          <label>Outros Ativo NC</label>
          <div class="wiz-moeda-wrap"><span class="wiz-moeda"></span>
          <input type="text" name="anc_outros" value="{{ etapa_dados.anc_outros or '' }}" placeholder="0" class="moeda-input"></div>
        </div>
      </div>
    </div>

    {# ── Passivo Circulante — aging (igual para todos os setores) ── #}
    <div class="wiz-secao">3 · Passivo Circulante — aging por grupo</div>
    <div class="hint mb-2">Preencha os valores em aberto por vencimento. Deixe em branco se não houver.</div>
    <div style="overflow-x:auto;">
    <table class="aging-table">
      <thead>
        <tr>
          <th class="row-label">Grupo</th>
          <th>Vencidas</th>
          <th>até 30d</th>
          <th>31–60d</th>
          <th>61–90d</th>
          <th>91–360d</th>
        </tr>
      </thead>
      <tbody>
        {% set pc_grupos = [
          ("forn", "Fornecedores" if not is_cc else "Fornecedores / Subempreiteiros"),
          ("emp",  "Empréstimos / Financ."),
          ("trib", "Obrig. Tributárias"),
          ("trab", "Obrig. Trabalhistas"),
          ("out",  "Outros"),
        ] %}
        {% set pc_buckets = ["venc","30d","60d","90d","360d"] %}
        {% for gk, glabel in pc_grupos %}
        <tr>
          <td style="font-weight:600;font-size:.8rem;">{{ glabel }}</td>
          {% for bk in pc_buckets %}
          {% set fname = "pc_" ~ gk ~ "_" ~ bk %}
          <td><input type="text" name="{{ fname }}"
              value="{{ etapa_dados[fname] if etapa_dados[fname] else '' }}"
              placeholder="0" class="moeda-input"></td>
          {% endfor %}
        </tr>
        {% endfor %}
      </tbody>
    </table>
    </div>

    {# ── Passivo Não-circulante ── #}
    <div class="wiz-secao mt-3">4 · Passivo Não-circulante (acima de 361 dias)</div>
    <div class="row g-3">
      {% set pnc_grupos = [
        ("pnc_forn", "Fornecedores LP" if not is_cc else "Fornecedores / Subempreit. LP"),
        ("pnc_emp",  "Empréstimos LP"),
        ("pnc_trib", "Obrig. Tributárias LP"),
        ("pnc_trab", "Obrig. Trabalhistas LP"),
        ("pnc_out",  "Outros LP"),
      ] %}
      {% for fname, flabel in pnc_grupos %}
      <div class="col-md-4">
        <div class="wiz-field">
          <label>{{ flabel }}</label>
          <div class="wiz-moeda-wrap"><span class="wiz-moeda"></span>
          <input type="text" name="{{ fname }}" value="{{ etapa_dados[fname] if etapa_dados[fname] else '' }}" placeholder="0" class="moeda-input"></div>
        </div>
      </div>
      {% endfor %}
    </div>

    {# ── Outros ── #}
    <div class="wiz-secao">Outros</div>
    <div class="row g-3">
      <div class="col-md-6">
        <div class="wiz-field">
          <label>Garantias disponíveis</label>
          <div class="wiz-moeda-wrap"><span class="wiz-moeda"></span>
          <input type="text" name="garantias" value="{{ etapa_dados.garantias or '' }}" placeholder="800.000" class="moeda-input"></div>
          <div class="hint">{{ 'Imóveis, recebíveis alienados, CRI' if is_cc else 'Imóveis, veículos, recebíveis alienados' }}</div>
        </div>
      </div>
      <div class="col-md-6">
        <div class="wiz-field">
          <label>Patrimônio Líquido estimado</label>
          <div class="wiz-moeda-wrap"><span class="wiz-moeda"></span>
          <input type="text" name="patrimonio_liquido" value="{{ etapa_dados.patrimonio_liquido or '' }}" placeholder="400.000" class="moeda-input"></div>
          <div class="hint">Ativo total menos passivo total</div>
        </div>
      </div>
    </div>
  </div>

  {# ═══════════════════════════════════════════════════════════════════════════
     ETAPA 5: Processos e Governança (igual para todos os setores)
  ═══════════════════════════════════════════════════════════════════════════ #}
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
      <label class="wiz-bool" for="q_{{ q.id }}">
        <input type="checkbox" name="{{ q.id }}" value="1" id="q_{{ q.id }}"
               {% if etapa_dados.get(q.id) %}checked{% endif %}>
        <span>{{ q.q }}</span>
      </label>
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
    <label class="wiz-bool" for="q_{{ k }}">
      <input type="checkbox" name="{{ k }}" value="1" id="q_{{ k }}"
             {% if etapa_dados.get(k) %}checked{% endif %}>
      <span>{{ label }}</span>
    </label>
    {% endfor %}
  </div>
  {% endif %}

  <div class="wiz-nav">
    {% if etapa > 1 %}
    <a href="/perfil/wizard?etapa={{ etapa - 1 }}" class="btn btn-outline-secondary">← Anterior</a>
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
document.querySelectorAll('.moeda-input').forEach(function(el) {
  var raw = parseFloat(el.value);
  if (!isNaN(raw) && raw > 0) {
    el.value = raw.toLocaleString('pt-BR', {minimumFractionDigits: 2, maximumFractionDigits: 2});
  } else {
    el.value = '';
  }
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

if hasattr(templates_env.loader, "mapping"):
    templates_env.loader.mapping = TEMPLATES

print("[wizard_v3] Wizard de diagnóstico v3 (setor-aware) carregado.")

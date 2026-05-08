# ============================================================================
# ui_wizard_v2.py — Wizard de Diagnóstico v2
# ============================================================================
# Redesign completo:
#   Etapa 1: auto-fill a partir dos dados já cadastrados (Client + BusinessProfile)
#   Etapa 2: sem alterações (mantém ambos os faturamentos)
#   Etapa 3: custos estruturados em 4 grupos:
#              Deduções / Custos Operacionais / Despesas Fixas / Empréstimos
#   Etapa 4: balanço completo com aging:
#              Ativo Circulante | Ativo Não-circulante
#              Passivo Circulante (5 grupos × 5 buckets) | Passivo NC
#   Análise:  indicadores completos (DRE, Liquidez, NCG/T/CCL, Dívida)
# ============================================================================

import json as _json_wiz2

# ── Helper local ─────────────────────────────────────────────────────────────

def _fv2(v) -> float:
    try:
        if v is None or v == "":
            return 0.0
        return float(str(v).replace(".", "").replace(",", ".").replace("R$", "").strip())
    except Exception:
        return 0.0


# ── Override score financeiro com novos campos ────────────────────────────────

def _wiz_calcular_score_financeiro(dados: dict) -> float:
    e2 = dados.get("etapa_2", {})
    e3 = dados.get("etapa_3", {})
    e4 = dados.get("etapa_4", {})

    fat = float(e2.get("faturamento_bruto_mensal", 0) or 0)

    # Deduções (novos campos, fallback zero)
    deducoes = (float(e3.get("impostos_mensais", 0) or 0)
              + float(e3.get("comissoes_mensal", 0) or 0)
              + float(e3.get("fretes_mensal", 0) or 0)
              + float(e3.get("outras_deducoes", 0) or 0))

    # Custos Operacionais (novos campos)
    custos_op = (float(e3.get("mao_obra_direta", 0) or 0)
               + float(e3.get("produtos_insumos", 0) or 0)
               + float(e3.get("custos_fabris", 0) or 0))

    # Fallback para campos antigos se novos zerados
    if custos_op == 0:
        custos_op = float(e3.get("cmv_mensal", 0) or 0)

    # Despesas Fixas (novos campos)
    desp_fixas = (float(e3.get("mao_obra_admin", 0) or 0)
                + float(e3.get("pro_labore", 0) or 0)
                + float(e3.get("aluguel", 0) or 0)
                + float(e3.get("outras_despesas_fixas", 0) or 0))

    if desp_fixas == 0:
        desp_fixas = (float(e3.get("folha_mensal", 0) or 0)
                    + float(e3.get("despesas_fixas", 0) or 0))

    caixa = float(e4.get("caixa_disponivel", 0) or 0)

    # Passivo Circulante total (novos campos)
    _pc_keys = [
        "pc_forn_venc","pc_forn_30d","pc_forn_60d","pc_forn_90d","pc_forn_360d",
        "pc_emp_venc","pc_emp_30d","pc_emp_60d","pc_emp_90d","pc_emp_360d",
        "pc_trib_venc","pc_trib_30d","pc_trib_60d","pc_trib_90d","pc_trib_360d",
        "pc_trab_venc","pc_trab_30d","pc_trab_60d","pc_trab_90d","pc_trab_360d",
        "pc_out_venc","pc_out_30d","pc_out_60d","pc_out_90d","pc_out_360d",
    ]
    pc_total = sum(float(e4.get(k, 0) or 0) for k in _pc_keys)

    _pnc_keys = ["pnc_forn", "pnc_emp", "pnc_trib", "pnc_trab", "pnc_out"]
    pnc_total = sum(float(e4.get(k, 0) or 0) for k in _pnc_keys)

    # Fallback para campos antigos de dívida
    div_total = pc_total + pnc_total
    if div_total == 0:
        div_total = (float(e4.get("dividas_cp", 0) or 0)
                   + float(e4.get("dividas_lp", 0) or 0))

    if fat <= 0:
        return 40.0

    rol = max(fat - deducoes, 0.0)
    margem_bruta_pct = (rol - custos_op) / rol if rol > 0 else 0.0
    ebit = rol - custos_op - desp_fixas

    score = 50.0

    if margem_bruta_pct >= 0.40:   score += 15
    elif margem_bruta_pct >= 0.25: score += 8
    elif margem_bruta_pct >= 0.10: score += 3
    else:                          score -= 10

    div_fat = div_total / fat
    if div_fat <= 2:   score += 15
    elif div_fat <= 4: score += 5
    elif div_fat <= 8: score -= 5
    else:              score -= 15

    caixa_meses = caixa / fat
    if caixa_meses >= 3:     score += 15
    elif caixa_meses >= 1:   score += 8
    elif caixa_meses >= 0.5: score += 2
    else:                    score -= 10

    if ebit > 0: score += 5
    else:        score -= 10

    return max(0.0, min(100.0, score))


# ── Remove rotas antigas e registra novas ─────────────────────────────────────

_wiz_paths = {"/perfil/wizard", "/perfil/wizard/salvar", "/perfil/wizard/finalizar"}
app.routes[:] = [
    r for r in app.routes
    if not (hasattr(r, "path") and r.path in _wiz_paths)
]

# Remove também rota de detalhe do snapshot (vamos adicionar com wizard_dados)
app.routes[:] = [
    r for r in app.routes
    if not (
        hasattr(r, "path") and r.path == "/perfil/avaliacao/{snapshot_id}"
        and hasattr(r, "methods") and "GET" in (r.methods or set())
    )
]


# ── Rota GET /perfil/wizard ───────────────────────────────────────────────────

@app.get("/perfil/wizard", response_class=HTMLResponse)
@require_login
async def wizard_get_v2(request: Request, session: Session = Depends(get_session)):
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

    # Auto-fill: carrega perfil para preencher etapa 1
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
    })


# ── Rota POST /perfil/wizard/salvar ──────────────────────────────────────────

@app.post("/perfil/wizard/salvar")
@require_login
async def wizard_salvar_v2(request: Request, session: Session = Depends(get_session)):
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
            "faturamento_bruto_mensal":  _fv2(form.get("faturamento_bruto_mensal")),
            "faturamento_medio_12m":     _fv2(form.get("faturamento_medio_12m")),
            "ticket_medio":              _fv2(form.get("ticket_medio")),
            "inadimplencia_pct":         _fv2(form.get("inadimplencia_pct")),
            "receita_recorrente_pct":    _fv2(form.get("receita_recorrente_pct")),
            "sazonalidade":              form.get("sazonalidade", ""),
            "principais_produtos":       form.get("principais_produtos", ""),
            "clientes_ativos":           int(form.get("clientes_ativos") or 0),
            "maior_cliente_pct":         _fv2(form.get("maior_cliente_pct")),
        }

    elif etapa == 3:
        dados_etapa = {
            # Deduções
            "impostos_mensais":     _fv2(form.get("impostos_mensais")),
            "comissoes_mensal":     _fv2(form.get("comissoes_mensal")),
            "fretes_mensal":        _fv2(form.get("fretes_mensal")),
            "outras_deducoes":      _fv2(form.get("outras_deducoes")),
            # Custos Operacionais
            "mao_obra_direta":      _fv2(form.get("mao_obra_direta")),
            "produtos_insumos":     _fv2(form.get("produtos_insumos")),
            "custos_fabris":        _fv2(form.get("custos_fabris")),
            # Despesas Fixas
            "mao_obra_admin":       _fv2(form.get("mao_obra_admin")),
            "pro_labore":           _fv2(form.get("pro_labore")),
            "aluguel":              _fv2(form.get("aluguel")),
            "outras_despesas_fixas":_fv2(form.get("outras_despesas_fixas")),
            # Empréstimos e Investimentos
            "parcelas_maquinas":    _fv2(form.get("parcelas_maquinas")),
            "parcelas_imobilizados":_fv2(form.get("parcelas_imobilizados")),
            "parcelas_emprestimos": _fv2(form.get("parcelas_emprestimos")),
        }

    elif etapa == 4:
        def _fv2_e4(k): return _fv2(form.get(k))
        dados_etapa = {
            # Ativo Circulante
            "caixa_disponivel": _fv2_e4("caixa_disponivel"),
            "ac_cr_30d":        _fv2_e4("ac_cr_30d"),
            "ac_cr_60d":        _fv2_e4("ac_cr_60d"),
            "ac_cr_90d":        _fv2_e4("ac_cr_90d"),
            "ac_cr_360d":       _fv2_e4("ac_cr_360d"),
            "ac_est_mp":        _fv2_e4("ac_est_mp"),
            "ac_est_wip":       _fv2_e4("ac_est_wip"),
            "ac_est_acab":      _fv2_e4("ac_est_acab"),
            "ac_outros":        _fv2_e4("ac_outros"),
            # Ativo Não-circulante
            "anc_cr_361d":      _fv2_e4("anc_cr_361d"),
            "anc_est_dificil":  _fv2_e4("anc_est_dificil"),
            "anc_veiculos":     _fv2_e4("anc_veiculos"),
            "anc_bens_moveis":  _fv2_e4("anc_bens_moveis"),
            "anc_imoveis":      _fv2_e4("anc_imoveis"),
            "anc_intangiveis":  _fv2_e4("anc_intangiveis"),
            "anc_outros":       _fv2_e4("anc_outros"),
            # Passivo Circulante — Fornecedores
            "pc_forn_venc": _fv2_e4("pc_forn_venc"), "pc_forn_30d": _fv2_e4("pc_forn_30d"),
            "pc_forn_60d":  _fv2_e4("pc_forn_60d"),  "pc_forn_90d": _fv2_e4("pc_forn_90d"),
            "pc_forn_360d": _fv2_e4("pc_forn_360d"),
            # Passivo Circulante — Empréstimos/Financiamentos
            "pc_emp_venc": _fv2_e4("pc_emp_venc"), "pc_emp_30d": _fv2_e4("pc_emp_30d"),
            "pc_emp_60d":  _fv2_e4("pc_emp_60d"),  "pc_emp_90d": _fv2_e4("pc_emp_90d"),
            "pc_emp_360d": _fv2_e4("pc_emp_360d"),
            # Passivo Circulante — Obrigações Tributárias
            "pc_trib_venc": _fv2_e4("pc_trib_venc"), "pc_trib_30d": _fv2_e4("pc_trib_30d"),
            "pc_trib_60d":  _fv2_e4("pc_trib_60d"),  "pc_trib_90d": _fv2_e4("pc_trib_90d"),
            "pc_trib_360d": _fv2_e4("pc_trib_360d"),
            # Passivo Circulante — Obrigações Trabalhistas
            "pc_trab_venc": _fv2_e4("pc_trab_venc"), "pc_trab_30d": _fv2_e4("pc_trab_30d"),
            "pc_trab_60d":  _fv2_e4("pc_trab_60d"),  "pc_trab_90d": _fv2_e4("pc_trab_90d"),
            "pc_trab_360d": _fv2_e4("pc_trab_360d"),
            # Passivo Circulante — Outros
            "pc_out_venc": _fv2_e4("pc_out_venc"), "pc_out_30d": _fv2_e4("pc_out_30d"),
            "pc_out_60d":  _fv2_e4("pc_out_60d"),  "pc_out_90d": _fv2_e4("pc_out_90d"),
            "pc_out_360d": _fv2_e4("pc_out_360d"),
            # Passivo Não-circulante (>361 dias)
            "pnc_forn": _fv2_e4("pnc_forn"), "pnc_emp":  _fv2_e4("pnc_emp"),
            "pnc_trib": _fv2_e4("pnc_trib"), "pnc_trab": _fv2_e4("pnc_trab"),
            "pnc_out":  _fv2_e4("pnc_out"),
            # Outros
            "garantias":          _fv2_e4("garantias"),
            "patrimonio_liquido": _fv2_e4("patrimonio_liquido"),
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


# ── Rota GET /perfil/wizard/finalizar ────────────────────────────────────────

@app.get("/perfil/wizard/finalizar")
@require_login
async def wizard_finalizar_v2(request: Request, session: Session = Depends(get_session)):
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

    score_fin  = _wiz_calcular_score_financeiro(dados)
    score_proc = _wiz_calcular_score_processos(dados)
    score_tot  = round((score_fin * 0.6) + (score_proc * 0.4), 1)

    fat   = float(e2.get("faturamento_bruto_mensal", 0) or 0)
    caixa = float(e4.get("caixa_disponivel", 0) or 0)

    _pc_keys = [
        "pc_forn_venc","pc_forn_30d","pc_forn_60d","pc_forn_90d","pc_forn_360d",
        "pc_emp_venc","pc_emp_30d","pc_emp_60d","pc_emp_90d","pc_emp_360d",
        "pc_trib_venc","pc_trib_30d","pc_trib_60d","pc_trib_90d","pc_trib_360d",
        "pc_trab_venc","pc_trab_30d","pc_trab_60d","pc_trab_90d","pc_trab_360d",
        "pc_out_venc","pc_out_30d","pc_out_60d","pc_out_90d","pc_out_360d",
    ]
    _pnc_keys = ["pnc_forn","pnc_emp","pnc_trib","pnc_trab","pnc_out"]
    div = (sum(float(e4.get(k, 0) or 0) for k in _pc_keys)
         + sum(float(e4.get(k, 0) or 0) for k in _pnc_keys))

    snap = ClientSnapshot(
        company_id=ctx.company.id,
        client_id=cc.id,
        created_by_user_id=ctx.user.id,
        revenue_monthly_brl=fat,
        debt_total_brl=div,
        cash_balance_brl=caixa,
        employees_count=int(e1.get("funcionarios", 0) or 0),
        nps_score=0,
        notes=f"Diagnóstico v2 — {e1.get('razao_social', cc.name)}",
        answers_json=_json_wiz2.dumps({**e5, "_wizard_dados": dados}, ensure_ascii=False),
        score_process=score_proc,
        score_financial=score_fin,
        score_total=score_tot,
    )
    session.add(snap)

    cc.revenue_monthly_brl = fat
    cc.debt_total_brl      = div
    cc.cash_balance_brl    = caixa
    cc.employees_count     = int(e1.get("funcionarios", 0) or 0)
    cc.updated_at          = utcnow()
    session.add(cc)

    try:
        profile = get_or_create_business_profile(session,
                                                  company_id=ctx.company.id,
                                                  client_id=cc.id)
        profile.segment      = e1.get("segmento", profile.segment or "")
        profile.cnae         = e1.get("cnae", profile.cnae or "")
        profile.tax_regime   = e1.get("regime_tributario", profile.tax_regime or "")
        profile.company_size = e1.get("porte", profile.company_size or "")
        session.add(profile)
    except Exception:
        pass

    rascunho.dados_json  = "{}"
    rascunho.etapa_atual = 1
    rascunho.updated_at  = str(_dtWiz.utcnow())
    session.add(rascunho)
    session.commit()

    set_flash(request, f"✅ Diagnóstico concluído! Score: {score_tot:.0f}/100")
    return RedirectResponse("/perfil", status_code=303)


# ── Rota GET /perfil/avaliacao/{snapshot_id} — com wizard_dados ──────────────

@app.get("/perfil/avaliacao/{snapshot_id}", response_class=HTMLResponse)
@require_login
async def perfil_snapshot_detail_v2(request: Request, session: Session = Depends(get_session),
                                     snapshot_id: int = 0) -> HTMLResponse:
    ctx = get_tenant_context(request, session)
    if not ctx:
        request.session.clear()
        return RedirectResponse("/login", status_code=303)

    snap = session.get(ClientSnapshot, int(snapshot_id))
    if not snap or snap.company_id != ctx.company.id:
        return render("error.html", request=request,
                      context={"current_user": ctx.user, "current_company": ctx.company,
                               "role": ctx.membership.role, "current_client": None,
                               "message": "Avaliação não encontrada."}, status_code=404)

    if not ensure_can_access_client(ctx, snap.client_id):
        return render("error.html", request=request,
                      context={"current_user": ctx.user, "current_company": ctx.company,
                               "role": ctx.membership.role, "current_client": None,
                               "message": "Sem permissão."}, status_code=403)

    client = session.get(Client, snap.client_id)
    answers = {}
    try:
        answers = json.loads(snap.answers_json or "{}")
    except Exception:
        pass

    wizard_dados = answers.get("_wizard_dados", {})
    current_client = get_client_or_none(session, ctx.company.id,
                                         get_active_client_id(request, session, ctx))

    return render("perfil_snapshot_detail.html", request=request, context={
        "current_user":    ctx.user,
        "current_company": ctx.company,
        "role":            ctx.membership.role,
        "current_client":  current_client,
        "client":          client,
        "snap":            snap,
        "survey":          PROFILE_SURVEY_V1,
        "answers":         answers,
        "wizard_dados":    wizard_dados,
    })


# ── Template: wizard_diagnostico.html ────────────────────────────────────────

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
  /* Tabela de passivo aging */
  .aging-table{width:100%;border-collapse:collapse;font-size:.8rem;margin-top:.5rem;}
  .aging-table th{background:#f8f9fa;padding:.4rem .5rem;text-align:center;border:1px solid var(--mc-border);font-weight:600;white-space:nowrap;}
  .aging-table th.row-label{text-align:left;min-width:140px;}
  .aging-table td{padding:.35rem .4rem;border:1px solid var(--mc-border);}
  .aging-table input{border:none;width:100%;min-width:90px;font-size:.8rem;text-align:right;background:transparent;outline:none;padding:.15rem .25rem;}
  .aging-table input:focus{background:#fffbeb;}
  .aging-table tr:hover td{background:#fafafa;}
  .aging-table .total-row td{background:#f3f4f6;font-weight:600;}
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

<form method="post" action="/perfil/wizard/salvar">
  <input type="hidden" name="etapa" value="{{ etapa }}">

  {# ═══════════════════════════════════════════════════════════════════════════
     ETAPA 1: Empresa — auto-fill a partir do cadastro
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
          <input type="text" name="razao_social"
            value="{{ etapa_dados.razao_social or current_client.name }}"
            placeholder="Nome da empresa">
        </div>
      </div>
      <div class="col-md-6">
        <div class="wiz-field">
          <label>CNPJ</label>
          <input type="text" name="cnpj"
            value="{{ etapa_dados.cnpj or current_client.cnpj or '' }}"
            placeholder="00.000.000/0001-00">
        </div>
      </div>
      <div class="col-md-4">
        <div class="wiz-field">
          <label>Segmento</label>
          <select name="segmento">
            <option value="">— Selecione —</option>
            {% for s in ["Comércio", "Indústria", "Serviços", "Construção Civil", "Agronegócio", "Saúde", "Tecnologia", "Educação", "Imobiliário", "Outro"] %}
            {% set sel = etapa_dados.segmento or (p.segment if p else "") %}
            <option value="{{ s }}" {% if sel == s %}selected{% endif %}>{{ s }}</option>
            {% endfor %}
          </select>
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
          <input type="text" name="cidade"
            value="{{ etapa_dados.cidade or current_client.city or '' }}"
            placeholder="Ex: Brusque">
        </div>
      </div>
      <div class="col-md-2">
        <div class="wiz-field">
          <label>UF</label>
          <input type="text" name="uf"
            value="{{ etapa_dados.uf or current_client.state or '' }}"
            placeholder="SC" maxlength="2">
        </div>
      </div>
      <div class="col-md-3">
        <div class="wiz-field">
          <label>Anos de operação</label>
          <input type="number" name="anos_operacao"
            value="{{ etapa_dados.anos_operacao or '' }}" min="0" placeholder="5">
        </div>
      </div>
      <div class="col-md-3">
        <div class="wiz-field">
          <label>Nº de sócios</label>
          <input type="text" name="socios"
            value="{{ etapa_dados.socios or '' }}" placeholder="2">
        </div>
      </div>
      <div class="col-md-3">
        <div class="wiz-field">
          <label>Funcionários</label>
          <input type="number" name="funcionarios"
            value="{{ etapa_dados.funcionarios or current_client.employees_count or '' }}"
            min="0" placeholder="12">
        </div>
      </div>
      <div class="col-12">
        <div class="wiz-field">
          <label>CNAE principal <span class="muted">(opcional)</span></label>
          <input type="text" name="cnae"
            value="{{ etapa_dados.cnae or (p.cnae if p else '') }}"
            placeholder="Ex: 4711-3/02 — Comércio varejista">
        </div>
      </div>
    </div>
  </div>

  {# ═══════════════════════════════════════════════════════════════════════════
     ETAPA 2: Receitas
  ═══════════════════════════════════════════════════════════════════════════ #}
  {% elif etapa == 2 %}
  <div class="wiz-card">
    <h5 class="mb-3">📈 Receitas e Vendas</h5>
    <div class="row g-3">
      <div class="col-md-6">
        <div class="wiz-field">
          <label>Faturamento bruto mensal <span class="text-danger">*</span></label>
          <div class="wiz-moeda-wrap"><span class="wiz-moeda"></span>
          <input type="text" name="faturamento_bruto_mensal"
            value="{{ etapa_dados.faturamento_bruto_mensal or '' }}"
            placeholder="500.000" class="moeda-input"></div>
          <div class="hint">Média dos últimos 3 meses — base para todos os cálculos</div>
        </div>
      </div>
      <div class="col-md-6">
        <div class="wiz-field">
          <label>Faturamento médio últimos 12 meses</label>
          <div class="wiz-moeda-wrap"><span class="wiz-moeda"></span>
          <input type="text" name="faturamento_medio_12m"
            value="{{ etapa_dados.faturamento_medio_12m or '' }}"
            placeholder="480.000" class="moeda-input"></div>
          <div class="hint">Revela tendência: se menor que o mensal = crescimento; se maior = queda</div>
        </div>
      </div>
      <div class="col-md-4">
        <div class="wiz-field">
          <label>Ticket médio por venda</label>
          <div class="wiz-moeda-wrap"><span class="wiz-moeda"></span>
          <input type="text" name="ticket_medio"
            value="{{ etapa_dados.ticket_medio or '' }}"
            placeholder="2.500" class="moeda-input"></div>
        </div>
      </div>
      <div class="col-md-4">
        <div class="wiz-field">
          <label>Inadimplência atual (%)</label>
          <input type="number" name="inadimplencia_pct"
            value="{{ etapa_dados.inadimplencia_pct or '' }}"
            min="0" max="100" step="0.1" placeholder="3.5">
          <div class="hint">% do faturamento não recebido</div>
        </div>
      </div>
      <div class="col-md-4">
        <div class="wiz-field">
          <label>Receita recorrente (%)</label>
          <input type="number" name="receita_recorrente_pct"
            value="{{ etapa_dados.receita_recorrente_pct or '' }}"
            min="0" max="100" step="1" placeholder="40">
          <div class="hint">% que se repete todo mês</div>
        </div>
      </div>
      <div class="col-md-4">
        <div class="wiz-field">
          <label>Clientes ativos</label>
          <input type="number" name="clientes_ativos"
            value="{{ etapa_dados.clientes_ativos or '' }}" min="0" placeholder="85">
        </div>
      </div>
      <div class="col-md-4">
        <div class="wiz-field">
          <label>Maior cliente = % do faturamento</label>
          <input type="number" name="maior_cliente_pct"
            value="{{ etapa_dados.maior_cliente_pct or '' }}"
            min="0" max="100" step="1" placeholder="25">
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
          <textarea name="principais_produtos" rows="2"
            placeholder="Ex: Venda de confecções, prestação de serviços de costura...">{{ etapa_dados.principais_produtos or '' }}</textarea>
        </div>
      </div>
    </div>
  </div>

  {# ═══════════════════════════════════════════════════════════════════════════
     ETAPA 3: Custos — 4 grupos ordenados
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
          <input type="text" name="impostos_mensais"
            value="{{ etapa_dados.impostos_mensais or '' }}"
            placeholder="45.000" class="moeda-input"></div>
          <div class="hint">DAS, IRPJ, CSLL, PIS, COFINS</div>
        </div>
      </div>
      <div class="col-md-3">
        <div class="wiz-field">
          <label>Comissões</label>
          <div class="wiz-moeda-wrap"><span class="wiz-moeda"></span>
          <input type="text" name="comissoes_mensal"
            value="{{ etapa_dados.comissoes_mensal or '' }}"
            placeholder="8.000" class="moeda-input"></div>
          <div class="hint">Vendedores, representantes</div>
        </div>
      </div>
      <div class="col-md-3">
        <div class="wiz-field">
          <label>Fretes</label>
          <div class="wiz-moeda-wrap"><span class="wiz-moeda"></span>
          <input type="text" name="fretes_mensal"
            value="{{ etapa_dados.fretes_mensal or '' }}"
            placeholder="5.000" class="moeda-input"></div>
          <div class="hint">CIF, transporte de vendas</div>
        </div>
      </div>
      <div class="col-md-3">
        <div class="wiz-field">
          <label>Outras deduções</label>
          <div class="wiz-moeda-wrap"><span class="wiz-moeda"></span>
          <input type="text" name="outras_deducoes"
            value="{{ etapa_dados.outras_deducoes or '' }}"
            placeholder="2.000" class="moeda-input"></div>
          <div class="hint">Devoluções, abatimentos</div>
        </div>
      </div>
    </div>

    {# ── 2. Custos Operacionais ── #}
    <div class="wiz-secao">2 · Custos Operacionais (sobre a receita líquida)</div>
    <div class="row g-3">
      <div class="col-md-4">
        <div class="wiz-field">
          <label>Mão de Obra Direta <span class="text-danger">*</span></label>
          <div class="wiz-moeda-wrap"><span class="wiz-moeda"></span>
          <input type="text" name="mao_obra_direta"
            value="{{ etapa_dados.mao_obra_direta or '' }}"
            placeholder="60.000" class="moeda-input"></div>
          <div class="hint">Folha + encargos dos que produzem/vendem</div>
        </div>
      </div>
      <div class="col-md-4">
        <div class="wiz-field">
          <label>Produtos e Insumos <span class="text-danger">*</span></label>
          <div class="wiz-moeda-wrap"><span class="wiz-moeda"></span>
          <input type="text" name="produtos_insumos"
            value="{{ etapa_dados.produtos_insumos or '' }}"
            placeholder="120.000" class="moeda-input"></div>
          <div class="hint">Mercadorias, matéria-prima, embalagens</div>
        </div>
      </div>
      <div class="col-md-4">
        <div class="wiz-field">
          <label>Custos Fabris / Produção</label>
          <div class="wiz-moeda-wrap"><span class="wiz-moeda"></span>
          <input type="text" name="custos_fabris"
            value="{{ etapa_dados.custos_fabris or '' }}"
            placeholder="15.000" class="moeda-input"></div>
          <div class="hint">Energia, manutenção, depreciação produtiva</div>
        </div>
      </div>
    </div>

    {# ── 3. Despesas Fixas ── #}
    <div class="wiz-secao">3 · Despesas Fixas</div>
    <div class="row g-3">
      <div class="col-md-3">
        <div class="wiz-field">
          <label>Mão de Obra Administrativa</label>
          <div class="wiz-moeda-wrap"><span class="wiz-moeda"></span>
          <input type="text" name="mao_obra_admin"
            value="{{ etapa_dados.mao_obra_admin or '' }}"
            placeholder="25.000" class="moeda-input"></div>
          <div class="hint">Backoffice, financeiro, RH</div>
        </div>
      </div>
      <div class="col-md-3">
        <div class="wiz-field">
          <label>Pró-labore dos Sócios</label>
          <div class="wiz-moeda-wrap"><span class="wiz-moeda"></span>
          <input type="text" name="pro_labore"
            value="{{ etapa_dados.pro_labore or '' }}"
            placeholder="15.000" class="moeda-input"></div>
        </div>
      </div>
      <div class="col-md-3">
        <div class="wiz-field">
          <label>Aluguel</label>
          <div class="wiz-moeda-wrap"><span class="wiz-moeda"></span>
          <input type="text" name="aluguel"
            value="{{ etapa_dados.aluguel or '' }}"
            placeholder="8.000" class="moeda-input"></div>
        </div>
      </div>
      <div class="col-md-3">
        <div class="wiz-field">
          <label>Outras Despesas Fixas</label>
          <div class="wiz-moeda-wrap"><span class="wiz-moeda"></span>
          <input type="text" name="outras_despesas_fixas"
            value="{{ etapa_dados.outras_despesas_fixas or '' }}"
            placeholder="12.000" class="moeda-input"></div>
          <div class="hint">Internet, seguros, contabilidade, serviços</div>
        </div>
      </div>
    </div>

    {# ── 4. Empréstimos e Investimentos ── #}
    <div class="wiz-secao">4 · Empréstimos e Investimentos Mensais</div>
    <div class="row g-3">
      <div class="col-md-4">
        <div class="wiz-field">
          <label>Parcelas de Máquinas</label>
          <div class="wiz-moeda-wrap"><span class="wiz-moeda"></span>
          <input type="text" name="parcelas_maquinas"
            value="{{ etapa_dados.parcelas_maquinas or '' }}"
            placeholder="5.000" class="moeda-input"></div>
          <div class="hint">Leasing/financiamento de equipamentos</div>
        </div>
      </div>
      <div class="col-md-4">
        <div class="wiz-field">
          <label>Parcelas de Imobilizados</label>
          <div class="wiz-moeda-wrap"><span class="wiz-moeda"></span>
          <input type="text" name="parcelas_imobilizados"
            value="{{ etapa_dados.parcelas_imobilizados or '' }}"
            placeholder="3.000" class="moeda-input"></div>
          <div class="hint">Veículos, móveis, imóveis</div>
        </div>
      </div>
      <div class="col-md-4">
        <div class="wiz-field">
          <label>Parcelas de Empréstimos</label>
          <div class="wiz-moeda-wrap"><span class="wiz-moeda"></span>
          <input type="text" name="parcelas_emprestimos"
            value="{{ etapa_dados.parcelas_emprestimos or '' }}"
            placeholder="18.000" class="moeda-input"></div>
          <div class="hint">Capital de giro, BNDES, banco</div>
        </div>
      </div>
    </div>
  </div>

  {# ═══════════════════════════════════════════════════════════════════════════
     ETAPA 4: Balanço — 4 partes claras
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
          <input type="text" name="caixa_disponivel"
            value="{{ etapa_dados.caixa_disponivel or '' }}"
            placeholder="80.000" class="moeda-input"></div>
          <div class="hint">Conta corrente + poupança + caixa físico</div>
        </div>
      </div>
    </div>
    <div class="row g-3 mt-0">
      <div class="col-12"><div class="hint" style="margin-top:0;">Contas a Receber (clientes) — por vencimento</div></div>
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
    <div class="row g-3 mt-0">
      <div class="col-12"><div class="hint">Estoques — por tipo</div></div>
      <div class="col-md-4">
        <div class="wiz-field">
          <label>Matéria-prima</label>
          <div class="wiz-moeda-wrap"><span class="wiz-moeda"></span>
          <input type="text" name="ac_est_mp" value="{{ etapa_dados.ac_est_mp or '' }}" placeholder="50.000" class="moeda-input"></div>
        </div>
      </div>
      <div class="col-md-4">
        <div class="wiz-field">
          <label>Em processo (WIP)</label>
          <div class="wiz-moeda-wrap"><span class="wiz-moeda"></span>
          <input type="text" name="ac_est_wip" value="{{ etapa_dados.ac_est_wip or '' }}" placeholder="20.000" class="moeda-input"></div>
        </div>
      </div>
      <div class="col-md-4">
        <div class="wiz-field">
          <label>Produtos acabados</label>
          <div class="wiz-moeda-wrap"><span class="wiz-moeda"></span>
          <input type="text" name="ac_est_acab" value="{{ etapa_dados.ac_est_acab or '' }}" placeholder="70.000" class="moeda-input"></div>
        </div>
      </div>
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
      <div class="col-md-4">
        <div class="wiz-field">
          <label>Estoques difícil saída</label>
          <div class="wiz-moeda-wrap"><span class="wiz-moeda"></span>
          <input type="text" name="anc_est_dificil" value="{{ etapa_dados.anc_est_dificil or '' }}" placeholder="0" class="moeda-input"></div>
        </div>
      </div>
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
          <label>Bens Móveis</label>
          <div class="wiz-moeda-wrap"><span class="wiz-moeda"></span>
          <input type="text" name="anc_bens_moveis" value="{{ etapa_dados.anc_bens_moveis or '' }}" placeholder="80.000" class="moeda-input"></div>
        </div>
      </div>
      <div class="col-md-4">
        <div class="wiz-field">
          <label>Imóveis</label>
          <div class="wiz-moeda-wrap"><span class="wiz-moeda"></span>
          <input type="text" name="anc_imoveis" value="{{ etapa_dados.anc_imoveis or '' }}" placeholder="500.000" class="moeda-input"></div>
        </div>
      </div>
      <div class="col-md-4">
        <div class="wiz-field">
          <label>Intangíveis</label>
          <div class="wiz-moeda-wrap"><span class="wiz-moeda"></span>
          <input type="text" name="anc_intangiveis" value="{{ etapa_dados.anc_intangiveis or '' }}" placeholder="0" class="moeda-input"></div>
          <div class="hint">Marcas, patentes, software</div>
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

    {# ── Passivo Circulante ── #}
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
          ("forn", "Fornecedores"),
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
        ("pnc_forn", "Fornecedores LP"),
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
          <input type="text" name="{{ fname }}"
            value="{{ etapa_dados[fname] if etapa_dados[fname] else '' }}"
            placeholder="0" class="moeda-input"></div>
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
          <input type="text" name="garantias"
            value="{{ etapa_dados.garantias or '' }}"
            placeholder="800.000" class="moeda-input"></div>
          <div class="hint">Imóveis, veículos, recebíveis alienados</div>
        </div>
      </div>
      <div class="col-md-6">
        <div class="wiz-field">
          <label>Patrimônio Líquido estimado</label>
          <div class="wiz-moeda-wrap"><span class="wiz-moeda"></span>
          <input type="text" name="patrimonio_liquido"
            value="{{ etapa_dados.patrimonio_liquido or '' }}"
            placeholder="400.000" class="moeda-input"></div>
          <div class="hint">Ativo total menos passivo total</div>
        </div>
      </div>
    </div>
  </div>

  {# ═══════════════════════════════════════════════════════════════════════════
     ETAPA 5: Processos e Governança
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
function toggleBool(id) {
  const cb = document.getElementById('q_' + id);
  if (cb) cb.checked = !cb.checked;
}
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


# ── Template: perfil_snapshot_detail.html ────────────────────────────────────

TEMPLATES["perfil_snapshot_detail.html"] = r"""
{% extends "base.html" %}
{% block content %}

{# ── Extrai dados do wizard ── #}
{% set wd = wizard_dados %}
{% set e1 = wd.get("etapa_1", {}) if wd else {} %}
{% set e2 = wd.get("etapa_2", {}) if wd else {} %}
{% set e3 = wd.get("etapa_3", {}) if wd else {} %}
{% set e4 = wd.get("etapa_4", {}) if wd else {} %}

{# ── DRE ── #}
{% set rob = (e2.get("faturamento_bruto_mensal") or snap.revenue_monthly_brl or 0)|float %}
{% set imp   = (e3.get("impostos_mensais") or 0)|float %}
{% set com   = (e3.get("comissoes_mensal") or 0)|float %}
{% set fret  = (e3.get("fretes_mensal") or 0)|float %}
{% set odeduc= (e3.get("outras_deducoes") or 0)|float %}
{% set deducoes = imp + com + fret + odeduc %}
{% set rol = rob - deducoes %}
{% set mod  = (e3.get("mao_obra_direta") or 0)|float %}
{% set pi   = (e3.get("produtos_insumos") or 0)|float %}
{% set cf   = (e3.get("custos_fabris") or 0)|float %}
{% set custos_op = mod + pi + cf %}
{% set margem_bruta = rol - custos_op %}
{% set moa  = (e3.get("mao_obra_admin") or 0)|float %}
{% set plor = (e3.get("pro_labore") or 0)|float %}
{% set alug = (e3.get("aluguel") or 0)|float %}
{% set odf  = (e3.get("outras_despesas_fixas") or 0)|float %}
{% set desp_fixas = moa + plor + alug + odf %}
{% set ebit = margem_bruta - desp_fixas %}
{% set pmaq = (e3.get("parcelas_maquinas") or 0)|float %}
{% set pimo = (e3.get("parcelas_imobilizados") or 0)|float %}
{% set pemp = (e3.get("parcelas_emprestimos") or 0)|float %}
{% set desp_fin = pmaq + pimo + pemp %}
{% set resultado = ebit - desp_fin %}
{% set pl = (e4.get("patrimonio_liquido") or 0)|float %}

{# ── Ativo Circulante ── #}
{% set caixa    = (e4.get("caixa_disponivel") or 0)|float %}
{% set ac_cr30  = (e4.get("ac_cr_30d") or 0)|float %}
{% set ac_cr60  = (e4.get("ac_cr_60d") or 0)|float %}
{% set ac_cr90  = (e4.get("ac_cr_90d") or 0)|float %}
{% set ac_cr360 = (e4.get("ac_cr_360d") or 0)|float %}
{% set ac_cr    = ac_cr30 + ac_cr60 + ac_cr90 + ac_cr360 %}
{% set ac_mp    = (e4.get("ac_est_mp") or 0)|float %}
{% set ac_wip   = (e4.get("ac_est_wip") or 0)|float %}
{% set ac_acab  = (e4.get("ac_est_acab") or 0)|float %}
{% set ac_est   = ac_mp + ac_wip + ac_acab %}
{% set ac_outros= (e4.get("ac_outros") or 0)|float %}
{% set ac_total = caixa + ac_cr + ac_est + ac_outros %}

{# ── Ativo Não-circulante ── #}
{% set anc_cr361 = (e4.get("anc_cr_361d") or 0)|float %}
{% set anc_edif  = (e4.get("anc_est_dificil") or 0)|float %}
{% set anc_veic  = (e4.get("anc_veiculos") or 0)|float %}
{% set anc_bm    = (e4.get("anc_bens_moveis") or 0)|float %}
{% set anc_imo   = (e4.get("anc_imoveis") or 0)|float %}
{% set anc_int   = (e4.get("anc_intangiveis") or 0)|float %}
{% set anc_out   = (e4.get("anc_outros") or 0)|float %}
{% set anc_total = anc_cr361 + anc_edif + anc_veic + anc_bm + anc_imo + anc_int + anc_out %}
{% set ativo_total = ac_total + anc_total %}

{# ── Passivo Circulante por grupo ── #}
{% set pc_forn = (e4.get("pc_forn_venc")|float(0)) + (e4.get("pc_forn_30d")|float(0)) + (e4.get("pc_forn_60d")|float(0)) + (e4.get("pc_forn_90d")|float(0)) + (e4.get("pc_forn_360d")|float(0)) %}
{% set pc_emp  = (e4.get("pc_emp_venc")|float(0))  + (e4.get("pc_emp_30d")|float(0))  + (e4.get("pc_emp_60d")|float(0))  + (e4.get("pc_emp_90d")|float(0))  + (e4.get("pc_emp_360d")|float(0))  %}
{% set pc_trib = (e4.get("pc_trib_venc")|float(0)) + (e4.get("pc_trib_30d")|float(0)) + (e4.get("pc_trib_60d")|float(0)) + (e4.get("pc_trib_90d")|float(0)) + (e4.get("pc_trib_360d")|float(0)) %}
{% set pc_trab = (e4.get("pc_trab_venc")|float(0)) + (e4.get("pc_trab_30d")|float(0)) + (e4.get("pc_trab_60d")|float(0)) + (e4.get("pc_trab_90d")|float(0)) + (e4.get("pc_trab_360d")|float(0)) %}
{% set pc_out  = (e4.get("pc_out_venc")|float(0))  + (e4.get("pc_out_30d")|float(0))  + (e4.get("pc_out_60d")|float(0))  + (e4.get("pc_out_90d")|float(0))  + (e4.get("pc_out_360d")|float(0))  %}
{% set pc_total = pc_forn + pc_emp + pc_trib + pc_trab + pc_out %}

{# ── Passivo circulante por aging bucket (liquidez dinâmica) ── #}
{% set pc_venc_30  = (e4.get("pc_forn_venc")|float(0)) + (e4.get("pc_emp_venc")|float(0)) + (e4.get("pc_trib_venc")|float(0)) + (e4.get("pc_trab_venc")|float(0)) + (e4.get("pc_out_venc")|float(0)) + (e4.get("pc_forn_30d")|float(0)) + (e4.get("pc_emp_30d")|float(0)) + (e4.get("pc_trib_30d")|float(0)) + (e4.get("pc_trab_30d")|float(0)) + (e4.get("pc_out_30d")|float(0)) %}
{% set pc_ate_60   = pc_venc_30 + (e4.get("pc_forn_60d")|float(0)) + (e4.get("pc_emp_60d")|float(0)) + (e4.get("pc_trib_60d")|float(0)) + (e4.get("pc_trab_60d")|float(0)) + (e4.get("pc_out_60d")|float(0)) %}
{% set pc_ate_90   = pc_ate_60  + (e4.get("pc_forn_90d")|float(0)) + (e4.get("pc_emp_90d")|float(0)) + (e4.get("pc_trib_90d")|float(0)) + (e4.get("pc_trab_90d")|float(0)) + (e4.get("pc_out_90d")|float(0)) %}

{# ── Passivo Não-circulante ── #}
{% set pnc_total = (e4.get("pnc_forn")|float(0)) + (e4.get("pnc_emp")|float(0)) + (e4.get("pnc_trib")|float(0)) + (e4.get("pnc_trab")|float(0)) + (e4.get("pnc_out")|float(0)) %}
{% set passivo_total = pc_total + pnc_total %}

{# ── Indicadores de Liquidez ── #}
{% set liq_imediata = (caixa / pc_total) if pc_total > 0 else 0 %}
{% set liq_seca     = ((caixa + ac_cr30 + ac_cr60) / pc_total) if pc_total > 0 else 0 %}
{% set liq_corrente = (ac_total / pc_total) if pc_total > 0 else 0 %}
{% set liq_geral    = ((ac_total + anc_total) / (pc_total + pnc_total)) if (pc_total + pnc_total) > 0 else 0 %}

{# Liquidez dinâmica por horizonte #}
{% set liq_30d = (caixa / pc_venc_30) if pc_venc_30 > 0 else 0 %}
{% set liq_60d = ((caixa + ac_cr30) / pc_ate_60) if pc_ate_60 > 0 else 0 %}
{% set liq_90d = ((caixa + ac_cr30 + ac_cr60) / pc_ate_90) if pc_ate_90 > 0 else 0 %}

{# ── Capital de Giro ── #}
{% set ccl = ac_total - pc_total %}
{# NCG = Ativo Operacional - Passivo Operacional (excluindo financeiro) #}
{% set ativo_op  = ac_cr + ac_est %}
{% set passivo_op = pc_forn + pc_trib + pc_trab %}
{% set ncg = ativo_op - passivo_op %}
{% set t   = ccl - ncg %}  {# Saldo de Tesouraria = CCL - NCG #}
{% set solvencia = ((ac_total + anc_total) / (pc_total + pnc_total)) if (pc_total + pnc_total) > 0 else 0 %}

{# ── Dívida ── #}
{% set div_onerosa = pc_emp + (e4.get("pnc_emp")|float(0)) %}
{% set div_liquida = div_onerosa - caixa %}
{% set capital_terceiros = pc_total + pnc_total %}

{# ── DRE % ── #}
{% set rob_pct        = 100.0 %}
{% set rol_pct        = (rol / rob * 100) if rob > 0 else 0 %}
{% set mb_pct         = (margem_bruta / rob * 100) if rob > 0 else 0 %}
{% set mb_rol_pct     = (margem_bruta / rol * 100) if rol > 0 else 0 %}
{% set df_rol_pct     = (desp_fixas / rol * 100) if rol > 0 else 0 %}
{% set ebit_pct       = (ebit / rob * 100) if rob > 0 else 0 %}
{% set ebit_mg_pct    = (ebit / rol * 100) if rol > 0 else 0 %}
{% set res_pct        = (resultado / rob * 100) if rob > 0 else 0 %}
{% set mg_liq_pct     = (resultado / rol * 100) if rol > 0 else 0 %}
{% set custos_rol_pct = (custos_op / rol * 100) if rol > 0 else 0 %}
{% set roe            = (resultado * 12 / pl * 100) if pl > 0 else 0 %}
{% set ebit_cover     = (ebit / desp_fin) if desp_fin > 0 else 0 %}
{% set div_onerosa_pl = (div_onerosa / pl) if pl > 0 else 0 %}
{% set div_liq_pl     = (div_liquida / pl) if pl > 0 else 0 %}
{% set div_liq_ebit   = (div_liquida / (ebit * 12)) if ebit > 0 else 0 %}

<div class="card p-4">
  <div class="d-flex justify-content-between align-items-start flex-wrap gap-2 mb-3">
    <div>
      <h4 class="mb-1">Avaliação Financeira</h4>
      <div class="muted small">{{ client.name }} · <span class="mono">{{ snap.created_at }}</span></div>
    </div>
    <a class="btn btn-outline-secondary btn-sm" href="/perfil">← Voltar</a>
  </div>

  {# ── Scores ── #}
  <div class="row g-3 mb-3">
    <div class="col-md-4">
      <div class="card p-3 text-center">
        <div class="muted small">Score Total</div>
        <div class="fs-3 fw-bold {% if snap.score_total >= 70 %}text-success{% elif snap.score_total >= 50 %}text-warning{% else %}text-danger{% endif %}">{{ "%.0f"|format(snap.score_total) }}</div>
        <div class="muted small">/ 100</div>
      </div>
    </div>
    <div class="col-md-4">
      <div class="card p-3 text-center">
        <div class="muted small">Financeiro</div>
        <div class="fs-3 fw-bold {% if snap.score_financial >= 70 %}text-success{% elif snap.score_financial >= 50 %}text-warning{% else %}text-danger{% endif %}">{{ "%.0f"|format(snap.score_financial) }}</div>
        <div class="muted small">peso 60%</div>
      </div>
    </div>
    <div class="col-md-4">
      <div class="card p-3 text-center">
        <div class="muted small">Processos</div>
        <div class="fs-3 fw-bold {% if snap.score_process >= 70 %}text-success{% elif snap.score_process >= 50 %}text-warning{% else %}text-danger{% endif %}">{{ "%.0f"|format(snap.score_process) }}</div>
        <div class="muted small">peso 40%</div>
      </div>
    </div>
  </div>

  {% if rob > 0 %}
  {# ═══════════════════════════════════════════════════════════════════════════
     DRE MENSAL
  ═══════════════════════════════════════════════════════════════════════════ #}
  <div class="card p-3 mb-3">
    <h6 class="mb-3">📊 DRE Mensal (Gerencial)</h6>
    <div class="table-responsive">
    <table class="table table-sm table-hover mb-0" style="font-size:.85rem;">
      <thead class="table-light">
        <tr><th>Indicador</th><th class="text-end">Valor (R$)</th><th class="text-end">% ROB</th><th class="text-end">% ROL</th></tr>
      </thead>
      <tbody>
        <tr class="fw-semibold">
          <td>Receita Operacional Bruta (ROB)</td>
          <td class="text-end">{{ rob|brl }}</td>
          <td class="text-end">100,0%</td>
          <td class="text-end">—</td>
        </tr>
        {% if deducoes > 0 %}
        <tr class="text-muted">
          <td>&nbsp;&nbsp;(-) Deduções <span class="badge text-bg-light border ms-1" style="font-size:.7rem;">Impostos · Comissões · Fretes</span></td>
          <td class="text-end text-danger">({{ deducoes|brl }})</td>
          <td class="text-end text-danger">{{ "%.1f"|format(deducoes / rob * 100) }}%</td>
          <td class="text-end">—</td>
        </tr>
        {% endif %}
        <tr class="fw-semibold">
          <td>Receita Operacional Líquida (ROL)</td>
          <td class="text-end">{{ rol|brl }}</td>
          <td class="text-end">{{ "%.1f"|format(rol_pct) }}%</td>
          <td class="text-end">100,0%</td>
        </tr>
        <tr class="text-muted">
          <td>&nbsp;&nbsp;(-) Custos Operacionais <span class="badge text-bg-light border ms-1" style="font-size:.7rem;">MO Direta · Insumos · Fabril</span></td>
          <td class="text-end text-danger">({{ custos_op|brl }})</td>
          <td class="text-end">—</td>
          <td class="text-end text-danger">{{ "%.1f"|format(custos_rol_pct) }}%</td>
        </tr>
        <tr class="fw-semibold {% if margem_bruta >= 0 %}text-success{% else %}text-danger{% endif %}">
          <td>Margem Bruta</td>
          <td class="text-end">{{ margem_bruta|brl }}</td>
          <td class="text-end">{{ "%.1f"|format(mb_pct) }}%</td>
          <td class="text-end">{{ "%.1f"|format(mb_rol_pct) }}%</td>
        </tr>
        <tr class="text-muted">
          <td>&nbsp;&nbsp;(-) SG&amp;A / Despesas Operacionais <span class="badge text-bg-light border ms-1" style="font-size:.7rem;">MO Admin · Aluguel · Outros</span></td>
          <td class="text-end text-danger">({{ desp_fixas|brl }})</td>
          <td class="text-end">—</td>
          <td class="text-end text-danger">{{ "%.1f"|format(df_rol_pct) }}%</td>
        </tr>
        <tr class="fw-semibold {% if ebit >= 0 %}text-success{% else %}text-danger{% endif %}">
          <td>EBIT (Resultado Operacional)</td>
          <td class="text-end">{{ ebit|brl }}</td>
          <td class="text-end">{{ "%.1f"|format(ebit_pct) }}%</td>
          <td class="text-end">{{ "%.1f"|format(ebit_mg_pct) }}%</td>
        </tr>
        {% if desp_fin > 0 %}
        <tr class="text-muted">
          <td>&nbsp;&nbsp;(-) Despesas Financeiras / Parcelas</td>
          <td class="text-end text-danger">({{ desp_fin|brl }})</td>
          <td class="text-end">—</td>
          <td class="text-end">—</td>
        </tr>
        {% endif %}
        <tr class="fw-bold {% if resultado >= 0 %}text-success{% else %}text-danger{% endif %}" style="border-top:2px solid #dee2e6;">
          <td>Resultado Líquido</td>
          <td class="text-end">{{ resultado|brl }}</td>
          <td class="text-end">{{ "%.1f"|format(res_pct) }}%</td>
          <td class="text-end">{{ "%.1f"|format(mg_liq_pct) }}%</td>
        </tr>
      </tbody>
    </table>
    </div>
  </div>

  {# ═══════════════════════════════════════════════════════════════════════════
     LIQUIDEZ
  ═══════════════════════════════════════════════════════════════════════════ #}
  {% if pc_total > 0 %}
  <div class="row g-3 mb-3">
    <div class="col-12"><h6 class="mb-0">💧 Indicadores de Liquidez</h6></div>

    {# Liquidez estática #}
    {% for label, val, hint in [
      ("Imediata", liq_imediata, "Caixa / PC"),
      ("Seca",     liq_seca,     "(Caixa + CR 60d) / PC"),
      ("Corrente", liq_corrente, "AC / PC"),
      ("Geral",    liq_geral,    "(AC + ANC) / (PC + PNC)"),
    ] %}
    <div class="col-md-3 col-6">
      <div class="card p-3 text-center">
        <div class="muted small">Liquidez {{ label }}</div>
        <div class="fs-4 fw-bold {% if val >= 1 %}text-success{% elif val >= 0.7 %}text-warning{% else %}text-danger{% endif %}">
          {{ "%.2f"|format(val) }}x
        </div>
        <div class="muted small">{{ hint }}</div>
      </div>
    </div>
    {% endfor %}

    {# Liquidez dinâmica por horizonte #}
    {% if pc_venc_30 > 0 or pc_ate_60 > 0 or pc_ate_90 > 0 %}
    <div class="col-12 mt-1"><div class="muted small fw-semibold">Cobertura de Caixa por Horizonte</div></div>
    {% for label, val, hint in [
      ("a 30 dias",   liq_30d, "Caixa vs obrigações vencidas + 30d"),
      ("a 60 dias",   liq_60d, "(Caixa + CR 30d) vs obrigações até 60d"),
      ("a 90 dias",   liq_90d, "(Caixa + CR 60d) vs obrigações até 90d"),
    ] %}
    <div class="col-md-4">
      <div class="card p-3 text-center">
        <div class="muted small">Liquidez {{ label }}</div>
        <div class="fs-4 fw-bold {% if val >= 1 %}text-success{% elif val >= 0.7 %}text-warning{% else %}text-danger{% endif %}">
          {{ "%.2f"|format(val) }}x
        </div>
        <div class="muted small">{{ hint }}</div>
      </div>
    </div>
    {% endfor %}
    {% endif %}
  </div>
  {% endif %}

  {# ═══════════════════════════════════════════════════════════════════════════
     CAPITAL DE GIRO
  ═══════════════════════════════════════════════════════════════════════════ #}
  <div class="row g-3 mb-3">
    <div class="col-12"><h6 class="mb-0">🔄 Capital de Giro</h6></div>
    {% for label, val, hint in [
      ("CCL", ccl, "Ativo Circ. − Passivo Circ."),
      ("NCG", ncg, "Ativo Op. − Passivo Op. (excl. financeiro)"),
      ("T — Saldo de Tesouraria", t, "CCL − NCG"),
    ] %}
    <div class="col-md-4">
      <div class="card p-3">
        <div class="muted small">{{ label }}</div>
        <div class="fs-5 fw-bold {% if val >= 0 %}text-success{% else %}text-danger{% endif %}">
          {{ val|brl }}
        </div>
        <div class="muted small">{{ hint }}</div>
      </div>
    </div>
    {% endfor %}
    <div class="col-md-4">
      <div class="card p-3">
        <div class="muted small">Grau de Solvência</div>
        <div class="fs-5 fw-bold {% if solvencia >= 1 %}text-success{% elif solvencia >= 0.8 %}text-warning{% else %}text-danger{% endif %}">
          {{ "%.2f"|format(solvencia) }}x
        </div>
        <div class="muted small">(AC + ANC) / (PC + PNC)</div>
      </div>
    </div>
    {% if rob > 0 %}
    <div class="col-md-4">
      <div class="card p-3">
        <div class="muted small">NCG / ROB</div>
        <div class="fs-5 fw-bold">{{ "%.1f"|format(ncg / rob * 100) }}%</div>
        <div class="muted small">Capital de giro em meses: {{ "%.1f"|format(ncg / rob) }}x</div>
      </div>
    </div>
    {% endif %}
  </div>

  {# ═══════════════════════════════════════════════════════════════════════════
     DÍVIDA E ESTRUTURA DE CAPITAL
  ═══════════════════════════════════════════════════════════════════════════ #}
  <div class="row g-3 mb-3">
    <div class="col-12"><h6 class="mb-0">🏦 Dívida e Estrutura de Capital</h6></div>
    <div class="col-md-6">
      <table class="table table-sm table-hover mb-0" style="font-size:.85rem;">
        <tbody>
          <tr><td>Patrimônio Líquido (PL)</td><td class="text-end fw-semibold">{{ pl|brl }}</td></tr>
          <tr><td>Capital de Terceiros (PC + PNC)</td><td class="text-end">{{ capital_terceiros|brl }}</td></tr>
          <tr><td>Dívida Onerosa (Empréstimos CP + LP)</td><td class="text-end">{{ div_onerosa|brl }}</td></tr>
          {% if pl > 0 %}
          <tr><td>Dívida Onerosa / PL</td><td class="text-end {% if div_onerosa_pl <= 1 %}text-success{% elif div_onerosa_pl <= 2 %}text-warning{% else %}text-danger{% endif %}">{{ "%.2f"|format(div_onerosa_pl) }}x</td></tr>
          {% endif %}
        </tbody>
      </table>
    </div>
    <div class="col-md-6">
      <table class="table table-sm table-hover mb-0" style="font-size:.85rem;">
        <tbody>
          <tr><td>Dívida Líquida (Div. Onerosa − Caixa)</td><td class="text-end {% if div_liquida <= 0 %}text-success{% else %}fw-semibold{% endif %}">{{ div_liquida|brl }}</td></tr>
          {% if pl > 0 %}
          <tr><td>Dívida Líquida / PL</td><td class="text-end {% if div_liq_pl <= 1 %}text-success{% elif div_liq_pl <= 2 %}text-warning{% else %}text-danger{% endif %}">{{ "%.2f"|format(div_liq_pl) }}x</td></tr>
          {% endif %}
          {% if ebit > 0 %}
          <tr><td>Dívida Líquida / EBIT (anualizado)</td><td class="text-end {% if div_liq_ebit <= 2 %}text-success{% elif div_liq_ebit <= 4 %}text-warning{% else %}text-danger{% endif %}">{{ "%.1f"|format(div_liq_ebit) }}x</td></tr>
          <tr><td>EBIT / Despesas Financeiras (cobertura)</td><td class="text-end {% if ebit_cover >= 2 %}text-success{% elif ebit_cover >= 1 %}text-warning{% else %}text-danger{% endif %}">{{ "%.1f"|format(ebit_cover) }}x</td></tr>
          {% endif %}
          {% if pl > 0 and resultado != 0 %}
          <tr><td>ROE (Retorno sobre PL — anual)</td><td class="text-end {% if roe >= 15 %}text-success{% elif roe >= 8 %}text-warning{% else %}text-danger{% endif %}">{{ "%.1f"|format(roe) }}%</td></tr>
          {% endif %}
        </tbody>
      </table>
    </div>
  </div>

  {% endif %} {# fim if rob > 0 #}

  {# ═══════════════════════════════════════════════════════════════════════════
     BALANÇO RESUMIDO
  ═══════════════════════════════════════════════════════════════════════════ #}
  {% if ac_total > 0 or anc_total > 0 or pc_total > 0 or pnc_total > 0 %}
  <div class="card p-3 mb-3">
    <h6 class="mb-3">📋 Balanço Resumido</h6>
    <div class="row g-3">
      <div class="col-md-6">
        <div class="fw-semibold mb-1 small text-success">ATIVO</div>
        <table class="table table-sm mb-0" style="font-size:.82rem;">
          <tbody>
            <tr class="fw-semibold"><td>Ativo Circulante</td><td class="text-end">{{ ac_total|brl }}</td></tr>
            <tr class="text-muted"><td>&nbsp; Caixa</td><td class="text-end">{{ caixa|brl }}</td></tr>
            <tr class="text-muted"><td>&nbsp; Contas a Receber</td><td class="text-end">{{ ac_cr|brl }}</td></tr>
            <tr class="text-muted"><td>&nbsp; Estoques</td><td class="text-end">{{ ac_est|brl }}</td></tr>
            <tr class="fw-semibold mt-1"><td>Ativo Não-circulante</td><td class="text-end">{{ anc_total|brl }}</td></tr>
            <tr class="fw-bold" style="border-top:2px solid #dee2e6;"><td>TOTAL ATIVO</td><td class="text-end">{{ ativo_total|brl }}</td></tr>
          </tbody>
        </table>
      </div>
      <div class="col-md-6">
        <div class="fw-semibold mb-1 small text-danger">PASSIVO + PL</div>
        <table class="table table-sm mb-0" style="font-size:.82rem;">
          <tbody>
            <tr class="fw-semibold"><td>Passivo Circulante</td><td class="text-end">{{ pc_total|brl }}</td></tr>
            {% if pc_forn > 0 %}<tr class="text-muted"><td>&nbsp; Fornecedores</td><td class="text-end">{{ pc_forn|brl }}</td></tr>{% endif %}
            {% if pc_emp > 0 %}<tr class="text-muted"><td>&nbsp; Empréstimos CP</td><td class="text-end">{{ pc_emp|brl }}</td></tr>{% endif %}
            {% if pc_trib > 0 %}<tr class="text-muted"><td>&nbsp; Tributário</td><td class="text-end">{{ pc_trib|brl }}</td></tr>{% endif %}
            {% if pc_trab > 0 %}<tr class="text-muted"><td>&nbsp; Trabalhista</td><td class="text-end">{{ pc_trab|brl }}</td></tr>{% endif %}
            <tr class="fw-semibold"><td>Passivo Não-circulante</td><td class="text-end">{{ pnc_total|brl }}</td></tr>
            {% if pl > 0 %}<tr class="fw-semibold"><td>Patrimônio Líquido</td><td class="text-end text-success">{{ pl|brl }}</td></tr>{% endif %}
            <tr class="fw-bold" style="border-top:2px solid #dee2e6;"><td>TOTAL PASSIVO + PL</td><td class="text-end">{{ (passivo_total + pl)|brl }}</td></tr>
          </tbody>
        </table>
      </div>
    </div>
  </div>
  {% endif %}

  {# ═══════════════════════════════════════════════════════════════════════════
     CHECKLIST PROCESSOS
  ═══════════════════════════════════════════════════════════════════════════ #}
  <div class="card p-3 mb-3">
    <h6 class="mb-3">⚙️ Checklist de Processos</h6>
    {% set secoes_vis = [] %}
    <ul class="mb-0 list-unstyled" style="column-count:2;column-gap:2rem;">
    {% for q in survey %}
      {% if q.section not in secoes_vis %}
        {% set _ = secoes_vis.append(q.section) %}
        <li class="mt-2"><span style="font-size:.7rem;font-weight:700;text-transform:uppercase;color:var(--mc-muted);">{{ q.section }}</span></li>
      {% endif %}
      <li class="d-flex align-items-start gap-1" style="font-size:.82rem;">
        <span>{% if answers.get(q.id) %}✅{% else %}⬜{% endif %}</span>
        <span>{{ q.q }}</span>
      </li>
    {% endfor %}
    </ul>
  </div>

  {% if snap.notes %}
  <div class="muted small"><b>Observações:</b> {{ snap.notes }}</div>
  {% endif %}
</div>
{% endblock %}
"""

if hasattr(templates_env.loader, "mapping"):
    templates_env.loader.mapping = TEMPLATES

print("[wizard_v2] Wizard redesign v2 carregado.")

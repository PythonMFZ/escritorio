# =============================================================================
# Formador de Preço de Venda — calculadora de precificação adaptável a
# Indústria, Serviço, Comércio e Importação.
# =============================================================================

TEMPLATES["formador_preco.html"] = r"""{% extends "base.html" %}
{% block content %}
<style>
  .fp-wrap{max-width:980px;margin:0 auto;}
  .fp-card{background:#fff;border:1px solid #dbe3ec;border-radius:12px;padding:22px 24px;margin-bottom:18px;}
  .fp-card h2{font-size:1.02rem;color:#0d3b66;margin:0 0 4px;}
  .fp-card .desc{font-size:.82rem;color:#64748b;margin:0 0 16px;}
  .fp-perfis{display:flex;gap:10px;flex-wrap:wrap;margin-bottom:18px;}
  .fp-perfil-btn{border:1px solid #dbe3ec;background:#f4f6f9;border-radius:10px;padding:10px 16px;
    font-size:.86rem;font-weight:600;color:#374151;cursor:pointer;transition:.15s;}
  .fp-perfil-btn.ativo{background:#0d3b66;color:#fff;border-color:#0d3b66;}
  .fp-grid{display:grid;grid-template-columns:1fr 1fr;gap:14px;}
  .fp-grid.full{grid-template-columns:1fr;}
  .fp-campo label{display:block;font-size:.8rem;font-weight:600;color:#374151;margin-bottom:4px;}
  .fp-campo input, .fp-campo select{width:100%;padding:8px 10px;border:1px solid #dbe3ec;border-radius:8px;
    font-size:.88rem;background:#fbfcfe;}
  .fp-campo input:focus, .fp-campo select:focus{outline:none;border-color:#0d3b66;background:#fff;}
  .fp-bloco{display:none;}
  .fp-bloco.ativo{display:block;}
  .fp-resultado{background:#0d3b66;color:#fff;border-radius:12px;padding:22px 24px;}
  .fp-resultado .num{font-size:1.9rem;font-weight:700;}
  .fp-resultado .lbl{font-size:.78rem;opacity:.85;}
  .fp-resultado-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:16px;margin-top:14px;}
  .fp-resultado-grid .item{background:rgba(255,255,255,.08);border-radius:8px;padding:12px 14px;}
  .fp-resultado-grid .item .num{font-size:1.15rem;}
  @media (max-width:760px){.fp-grid,.fp-resultado-grid{grid-template-columns:1fr;}}
  .fp-alerta{font-size:.78rem;background:#fff5f5;color:#dc3545;border:1px solid #f1c0c0;border-radius:8px;
    padding:8px 12px;margin-top:10px;display:none;}
</style>

<div class="fp-wrap">
  <div class="fp-card">
    <h2>💰 Formador de Preço de Venda</h2>
    <p class="desc">Calcule o preço de venda sugerido considerando custos, despesas, impostos e a margem desejada — adapte ao perfil do cliente.</p>
    <div class="fp-perfis">
      <button type="button" class="fp-perfil-btn ativo" data-perfil="industria" onclick="fpSetPerfil('industria')">🏭 Indústria</button>
      <button type="button" class="fp-perfil-btn" data-perfil="servico" onclick="fpSetPerfil('servico')">🛎️ Serviço</button>
      <button type="button" class="fp-perfil-btn" data-perfil="comercio" onclick="fpSetPerfil('comercio')">🛒 Comércio</button>
      <button type="button" class="fp-perfil-btn" data-perfil="importacao" onclick="fpSetPerfil('importacao')">🚢 Importação</button>
    </div>
  </div>

  <div class="fp-card">
    <h2>📦 Composição de Custo</h2>
    <p class="desc">Os campos abaixo mudam conforme o perfil selecionado.</p>

    <div class="fp-bloco ativo" data-bloco="industria">
      <div class="fp-grid">
        <div class="fp-campo"><label>Matéria-prima (R$/unid.)</label><input type="number" step="0.01" id="ind_materia_prima" oninput="fpCalcular()" value="0"></div>
        <div class="fp-campo"><label>Mão de obra direta (R$/unid.)</label><input type="number" step="0.01" id="ind_mao_obra" oninput="fpCalcular()" value="0"></div>
        <div class="fp-campo"><label>Custos indiretos de fabricação — CIF (R$/unid.)</label><input type="number" step="0.01" id="ind_cif" oninput="fpCalcular()" value="0"></div>
        <div class="fp-campo"><label>Embalagem / acabamento (R$/unid.)</label><input type="number" step="0.01" id="ind_embalagem" oninput="fpCalcular()" value="0"></div>
      </div>
    </div>

    <div class="fp-bloco" data-bloco="servico">
      <div class="fp-grid">
        <div class="fp-campo"><label>Custo da equipe alocada (R$/unid. ou hora)</label><input type="number" step="0.01" id="srv_equipe" oninput="fpCalcular()" value="0"></div>
        <div class="fp-campo"><label>Custos diretos do serviço (materiais, deslocamento etc.)</label><input type="number" step="0.01" id="srv_diretos" oninput="fpCalcular()" value="0"></div>
        <div class="fp-campo"><label>Overhead / estrutura rateada (R$/unid.)</label><input type="number" step="0.01" id="srv_overhead" oninput="fpCalcular()" value="0"></div>
      </div>
    </div>

    <div class="fp-bloco" data-bloco="comercio">
      <div class="fp-grid">
        <div class="fp-campo"><label>Custo de aquisição (valor da NF, R$/unid.)</label><input type="number" step="0.01" id="com_aquisicao" oninput="fpCalcular()" value="0"></div>
        <div class="fp-campo"><label>Frete de compra (R$/unid.)</label><input type="number" step="0.01" id="com_frete" oninput="fpCalcular()" value="0"></div>
        <div class="fp-campo"><label>Outras despesas de aquisição (R$/unid.)</label><input type="number" step="0.01" id="com_outras" oninput="fpCalcular()" value="0"></div>
      </div>
    </div>

    <div class="fp-bloco" data-bloco="importacao">
      <div class="fp-grid">
        <div class="fp-campo"><label>Valor FOB (moeda estrangeira, por unid.)</label><input type="number" step="0.01" id="imp_fob" oninput="fpCalcular()" value="0"></div>
        <div class="fp-campo"><label>Cotação do câmbio (R$ por unidade da moeda)</label><input type="number" step="0.0001" id="imp_cambio" oninput="fpCalcular()" value="0"></div>
        <div class="fp-campo"><label>Frete internacional + seguro (R$/unid.)</label><input type="number" step="0.01" id="imp_frete_seguro" oninput="fpCalcular()" value="0"></div>
        <div class="fp-campo"><label>Imposto de Importação — II (%)</label><input type="number" step="0.01" id="imp_ii_pct" oninput="fpCalcular()" value="0"></div>
        <div class="fp-campo"><label>IPI (%)</label><input type="number" step="0.01" id="imp_ipi_pct" oninput="fpCalcular()" value="0"></div>
        <div class="fp-campo"><label>PIS/COFINS-Importação (%)</label><input type="number" step="0.01" id="imp_piscofins_pct" oninput="fpCalcular()" value="0"></div>
        <div class="fp-campo"><label>ICMS-Importação (%)</label><input type="number" step="0.01" id="imp_icms_pct" oninput="fpCalcular()" value="0"></div>
        <div class="fp-campo"><label>Despesas aduaneiras / desembaraço (R$/unid.)</label><input type="number" step="0.01" id="imp_despachante" oninput="fpCalcular()" value="0"></div>
      </div>
    </div>
  </div>

  <div class="fp-card">
    <h2>📊 Despesas, Impostos e Margem sobre a Venda</h2>
    <p class="desc">Esses percentuais incidem sobre o preço de venda final (markup divisor).</p>
    <div class="fp-grid">
      <div class="fp-campo"><label>Comissão de vendas (%)</label><input type="number" step="0.01" id="ger_comissao" oninput="fpCalcular()" value="0"></div>
      <div class="fp-campo"><label>Taxa de cartão / financeira (%)</label><input type="number" step="0.01" id="ger_cartao" oninput="fpCalcular()" value="0"></div>
      <div class="fp-campo"><label>Frete de venda (%)</label><input type="number" step="0.01" id="ger_frete_venda" oninput="fpCalcular()" value="0"></div>
      <div class="fp-campo">
        <label>Regime tributário</label>
        <select id="ger_regime" onchange="fpRegimePreset()">
          <option value="manual">Informar manualmente</option>
          <option value="simples">Simples Nacional (estimado)</option>
          <option value="presumido">Lucro Presumido (estimado)</option>
          <option value="real">Lucro Real (estimado)</option>
        </select>
      </div>
      <div class="fp-campo"><label>Impostos sobre a venda (%)</label><input type="number" step="0.01" id="ger_impostos" oninput="fpCalcular()" value="0"></div>
      <div class="fp-campo"><label>Margem de lucro desejada (%)</label><input type="number" step="0.01" id="ger_margem" oninput="fpCalcular()" value="20"></div>
    </div>
    <div class="fp-alerta" id="fpAlerta">⚠️ A soma de despesas variáveis + impostos + margem não pode atingir 100% — ajuste os percentuais.</div>
  </div>

  <div class="fp-resultado">
    <div class="lbl">Preço de venda sugerido</div>
    <div class="num" id="fpPrecoSugerido">R$ 0,00</div>
    <div class="fp-resultado-grid">
      <div class="item"><div class="lbl">Custo base (R$/unid.)</div><div class="num" id="fpCustoBase">R$ 0,00</div></div>
      <div class="item"><div class="lbl">Markup multiplicador</div><div class="num" id="fpMarkup">0,00x</div></div>
      <div class="item"><div class="lbl">Margem de contribuição (R$)</div><div class="num" id="fpMargemRs">R$ 0,00</div></div>
    </div>
  </div>
</div>

<script>
function fpFmt(v){ return 'R$ ' + (v||0).toLocaleString('pt-BR', {minimumFractionDigits:2, maximumFractionDigits:2}); }

function fpSetPerfil(p){
  document.querySelectorAll('.fp-perfil-btn').forEach(b => b.classList.toggle('ativo', b.dataset.perfil === p));
  document.querySelectorAll('.fp-bloco').forEach(b => b.classList.toggle('ativo', b.dataset.bloco === p));
  fpCalcular();
}

function fpRegimePreset(){
  const presets = { manual: null, simples: 8, presumido: 14, real: 18 };
  const regime = document.getElementById('ger_regime').value;
  const v = presets[regime];
  if (v !== null) document.getElementById('ger_impostos').value = v;
  fpCalcular();
}

function fpCustoBaseAtual(){
  const perfil = document.querySelector('.fp-perfil-btn.ativo').dataset.perfil;
  const num = id => parseFloat(document.getElementById(id).value) || 0;
  if (perfil === 'industria'){
    return num('ind_materia_prima') + num('ind_mao_obra') + num('ind_cif') + num('ind_embalagem');
  }
  if (perfil === 'servico'){
    return num('srv_equipe') + num('srv_diretos') + num('srv_overhead');
  }
  if (perfil === 'comercio'){
    return num('com_aquisicao') + num('com_frete') + num('com_outras');
  }
  if (perfil === 'importacao'){
    const baseFob = num('imp_fob') * num('imp_cambio');
    const impostosPct = (num('imp_ii_pct') + num('imp_ipi_pct') + num('imp_piscofins_pct') + num('imp_icms_pct')) / 100;
    const impostosRs = baseFob * impostosPct;
    return baseFob + impostosRs + num('imp_frete_seguro') + num('imp_despachante');
  }
  return 0;
}

function fpCalcular(){
  const num = id => parseFloat(document.getElementById(id).value) || 0;
  const custoBase = fpCustoBaseAtual();
  const pctVariaveis = (num('ger_comissao') + num('ger_cartao') + num('ger_frete_venda') + num('ger_impostos') + num('ger_margem')) / 100;

  const alerta = document.getElementById('fpAlerta');
  let precoSugerido = 0, markup = 0, margemRs = 0;
  if (pctVariaveis >= 1){
    alerta.style.display = 'block';
  } else {
    alerta.style.display = 'none';
    const divisor = 1 - pctVariaveis;
    precoSugerido = custoBase / divisor;
    markup = divisor > 0 ? precoSugerido / (custoBase || 1) : 0;
    margemRs = precoSugerido * (num('ger_margem') / 100);
  }

  document.getElementById('fpCustoBase').textContent = fpFmt(custoBase);
  document.getElementById('fpPrecoSugerido').textContent = fpFmt(precoSugerido);
  document.getElementById('fpMarkup').textContent = markup.toLocaleString('pt-BR', {minimumFractionDigits:2, maximumFractionDigits:2}) + 'x';
  document.getElementById('fpMargemRs').textContent = fpFmt(margemRs);
}

fpCalcular();
</script>
{% endblock %}
"""


@app.get("/admin/formador-preco", response_class=HTMLResponse)
@require_role({"admin", "equipe"})
async def formador_preco_page(request: Request, session: Session = Depends(get_session)) -> HTMLResponse:
    ctx = get_tenant_context(request, session)
    cc = get_client_or_none(session, ctx.company.id, get_active_client_id(request, session, ctx))
    return render(
        "formador_preco.html",
        request=request,
        context={
            "title": "Formador de Preço de Venda",
            "current_user": ctx.user,
            "current_company": ctx.company,
            "role": ctx.membership.role,
            "current_client": cc,
        },
    )


try:
    FEATURE_KEYS["formador_preco"] = {
        "title": "Formador de Preço de Venda",
        "desc": "Calculadora de precificação por perfil: indústria, serviço, comércio e importação.",
        "href": "/admin/formador-preco",
    }
    for _grp_fp in FEATURE_GROUPS:
        if _grp_fp.get("key") == "gestao_interna" and "formador_preco" not in _grp_fp["features"]:
            _grp_fp["features"].append("formador_preco")
    ROLE_DEFAULT_FEATURES["admin"].add("formador_preco")
    ROLE_DEFAULT_FEATURES["equipe"].add("formador_preco")
    print("[formador_preco] ✅ Card 'Formador de Preço de Venda' registrado em Gestão Interna")
except Exception as _e_fp_card:
    print(f"[formador_preco] ⚠️ Falha ao registrar card em Gestão Interna: {_e_fp_card}")

if hasattr(templates_env.loader, "mapping"):
    templates_env.loader.mapping = TEMPLATES

print("[formador_preco] ✅ Módulo Formador de Preço de Venda carregado.")

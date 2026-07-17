# =============================================================================
# Viabilidade — Produto v2: Entrada por Pavimento com Dif. por Unidade
# Substitui a aba "Produto & VGV" por UI hierárquica: Pavimento → Unidades
# =============================================================================

# Remove a rota POST registrada por ui_viabilidade_v3.py para que a nossa
# (com parsing de pavimentos) seja a única ativa no path.
app.router.routes[:] = [
    r for r in app.router.routes
    if not (
        hasattr(r, "path") and r.path == "/ferramentas/viabilidade/calcular"
        and hasattr(r, "methods") and r.methods and "POST" in r.methods
    )
]

# ── Override: POST route ──────────────────────────────────────────────────────

@app.post("/ferramentas/viabilidade/calcular", response_class=HTMLResponse)
@require_login
async def ferramenta_viabilidade_post_prodv2(
    request: Request, session: Session = Depends(get_session),
) -> HTMLResponse:
    ctx = get_tenant_context(request, session)
    if not ctx:
        request.session.clear()
        return RedirectResponse("/login", status_code=303)
    cc = get_client_or_none(session, ctx.company.id, get_active_client_id(request, session, ctx))
    form  = await request.form()
    dados: dict = dict(form)

    preco_m2_base_f = float(dados.get("preco_m2_base", 12500) or 12500)

    # ── Parse pavimentos → tipologias (novo formato) ──────────────────────
    tipologias = []
    pavimentos = []   # para re-renderização do form

    # Coleta todos os índices de pavimento e unidade presentes no form
    # (varredura por chaves reais para tolerar gaps causados por deleções no JS)
    import re as _re_vb
    pav_indices = sorted({
        int(m.group(1))
        for k in dados
        for m in [_re_vb.match(r"pav_nome_(\d+)", k) or _re_vb.match(r"pav_andar_(\d+)", k)]
        if m
    })
    un_indices = {}  # {pav_idx: [un_idx, ...]}
    for k in dados:
        m = _re_vb.match(r"un_met_(\d+)_(\d+)", k)
        if m:
            pi, ui = int(m.group(1)), int(m.group(2))
            un_indices.setdefault(pi, [])
            if ui not in un_indices[pi]:
                un_indices[pi].append(ui)
    for pi in un_indices:
        un_indices[pi].sort()

    for p in pav_indices:
        pav_nome  = dados.get(f"pav_nome_{p}", f"Pavimento {p+1}")
        pav_andar = int(dados.get(f"pav_andar_{p}", p + 1) or p + 1)

        pav_unidades = []
        for u in un_indices.get(p, []):
            met = float(dados.get(f"un_met_{p}_{u}", 0) or 0)
            if met > 0:
                preco_proprio = float(dados.get(f"un_preco_{p}_{u}", 0) or 0)
                dif_prop = float(dados.get(f"un_dif_{p}_{u}", 0) or 0)
                permuta  = dados.get(f"un_perm_{p}_{u}") == "1"
                nome_un  = dados.get(f"un_nome_{p}_{u}", "")
                tipo_un  = dados.get(f"un_tipo_{p}_{u}", "Residencial")

                tipologias.append({
                    "nome":         nome_un,
                    "tipo":         tipo_un,
                    "metragem":     met,
                    "quantidade":   1,
                    "preco_m2":     preco_proprio or preco_m2_base_f,
                    "andar_inicio": pav_andar,
                    "dif_proprio":  dif_prop,
                    "permuta":      permuta,
                    "pavimento":    pav_nome,
                })
                pav_unidades.append({
                    "nome":         nome_un,
                    "tipo":         tipo_un,
                    "metragem":     met,
                    "preco_proprio": preco_proprio or None,
                    "dif_proprio":  dif_prop,
                    "permuta":      permuta,
                })
        pavimentos.append({"nome": pav_nome, "andar": pav_andar, "unidades": pav_unidades})

    # Backward compat: se não há pavimentos no form, tenta ler formato antigo tip_nome_*
    if not tipologias:
        i = 0
        while f"tip_nome_{i}" in dados or f"tip_metragem_{i}" in dados:
            met = float(dados.get(f"tip_metragem_{i}", 0) or 0)
            qtd = int(dados.get(f"tip_qtd_{i}", 1) or 1)
            if met > 0:
                tipologias.append({
                    "nome":         dados.get(f"tip_nome_{i}", ""),
                    "tipo":         dados.get(f"tip_tipo_{i}", "Residencial"),
                    "metragem":     met,
                    "quantidade":   qtd,
                    "preco_m2":     float(dados.get(f"tip_preco_{i}", 0) or 0) or preco_m2_base_f,
                    "andar_inicio": int(dados.get(f"tip_andar_{i}", 1) or 1),
                    "dif_proprio":  0.0,
                    "permuta":      dados.get(f"tip_permuta_{i}") == "1",
                    "pavimento":    "",
                })
            i += 1

    dados["tipologias"] = tipologias
    dados["pavimentos"] = pavimentos

    # ── Fases de venda ────────────────────────────────────────────────────
    fases = []
    j = 0
    while f"fase_nome_{j}" in dados:
        fases.append({
            "nome":         dados.get(f"fase_nome_{j}", ""),
            "meta":         float(dados.get(f"fase_meta_{j}", 0) or 0),
            "reajuste":     float(dados.get(f"fase_reajuste_{j}", 0) or 0),
            "duracao":      int(dados.get(f"fase_duracao_{j}", 12) or 12),
            "entrada_pct":  float(dados.get(f"fase_entrada_{j}", 10) or 10),
            "n_entrada":    int(dados.get(f"fase_nentrada_{j}", 1) or 1),
            "parcelas_pct": float(dados.get(f"fase_parcelas_{j}", 80) or 80),
            "n_parcelas":   int(dados.get(f"fase_nparcelas_{j}", 24) or 24),
            "reforco_pct":  float(dados.get(f"fase_reforco_{j}", 0) or 0),
            "n_reforcos":   int(dados.get(f"fase_nreforcos_{j}", 0) or 0),
        })
        j += 1
    if fases:
        dados["fases"] = fases

    # ── Cenário ───────────────────────────────────────────────────────────
    cenario = dados.get("cenario", "realista")
    mult = {"otimista": 1.15, "realista": 1.00, "pessimista": 0.85}.get(cenario, 1.00)
    if mult != 1.00:
        dados["preco_m2_base"] = preco_m2_base_f * mult
        for t in dados["tipologias"]:
            t["preco_m2"] = float(t.get("preco_m2", 0) or 0) * mult
    dados["cenario"] = cenario

    resultado = _calcular_v3(dados)
    return render("ferramenta_viabilidade.html", request=request, context={
        "current_user":    ctx.user,
        "current_company": ctx.company,
        "role":            ctx.membership.role,
        "current_client":  cc,
        "resultado":       resultado,
        "dados":           dados,
    })


# ── Patch do template ─────────────────────────────────────────────────────────

def _patch_produto_v2():
    tpl = TEMPLATES.get("ferramenta_viabilidade.html", "")
    if not tpl or "_prodV3" in tpl:
        return

    changed = False

    # ── A: CSS — adiciona .pav-* e esconde .tip-* ─────────────────────────
    _OLD_CSS = (
        "  .tip-hdr{display:grid;grid-template-columns:1.5fr .7fr 1fr 1fr .7fr .5fr .5fr auto;"
        "gap:.5rem;font-size:.68rem;font-weight:700;text-transform:uppercase;color:var(--mc-muted);margin-bottom:.4rem;}\n"
        "  .tip-row{display:grid;grid-template-columns:1.5fr .7fr 1fr 1fr .7fr .5fr .5fr auto;"
        "gap:.5rem;margin-bottom:.5rem;align-items:center;}"
    )
    _NEW_CSS = (
        "  .tip-hdr,.tip-row{display:none;}\n"
        "  .pav-card{border:1.5px solid var(--mc-border);border-radius:14px;padding:1rem 1.1rem;"
        "margin-bottom:.85rem;background:#fff;}\n"
        "  .pav-hdr{display:flex;justify-content:space-between;align-items:center;margin-bottom:.75rem;"
        "gap:.5rem;flex-wrap:wrap;}\n"
        "  .pav-un-hdr{display:grid;grid-template-columns:1fr .7fr .8fr 1fr .9fr .6fr auto;"
        "gap:.4rem;font-size:.67rem;font-weight:700;text-transform:uppercase;color:var(--mc-muted);"
        "margin-bottom:.3rem;padding:0 .1rem;}\n"
        "  .pav-un-row{display:grid;grid-template-columns:1fr .7fr .8fr 1fr .9fr .6fr auto;"
        "gap:.4rem;margin-bottom:.4rem;align-items:center;}\n"
        "  .pav-un-body{border-left:3px solid #f1f5f9;margin-left:.3rem;padding-left:.6rem;"
        "margin-top:.3rem;}"
    )
    if _OLD_CSS in tpl:
        tpl = tpl.replace(_OLD_CSS, _NEW_CSS, 1)
        changed = True

    # ── B: Substituição da aba Produto ────────────────────────────────────
    _OLD_PROD = (
        '{# ── ABA 2: PRODUTO ── #}\n'
        '<div class="vb-sec card p-4 mb-3" id="tab-produto">\n'
        '  <h5 class="mb-3">Produto &amp; VGV</h5>\n'
        '  <div class="vb-row">\n'
        '    <div><div class="vb-lbl">Preço base (R$/m²)</div><div class="pw"><span class="pre">R$</span>'
        '<input class="vb-inp pl" type="number" name="preco_m2_base" step="100" min="0" placeholder="12.500" '
        'value="{{ dados.preco_m2_base or \'12500\' }}"></div></div>\n'
        '    <div><div class="vb-lbl">Diferencial por andar (%)</div><div class="pw"><span class="suf">%</span>'
        '<input class="vb-inp pr" type="number" name="diferencial_andar" step="0.1" min="0" max="5" '
        'placeholder="0.5" value="{{ dados.diferencial_andar or \'0.5\' }}"></div>'
        '<div class="vb-hint">Incremento no preço/m² a cada andar</div></div>\n'
        '  </div>\n'
        '  <div class="vb-sep">Tipologias</div>\n'
        '  <div class="tip-hdr">\n'
        '    <span>Nome / Descrição</span><span>Tipo</span><span>Metragem (m²)</span>'
        '<span>Qtd</span><span>Preço/m²</span><span>Andar ini.</span><span>Permuta</span><span></span>\n'
        '  </div>\n'
        '  <div id="tipCont">\n'
        '    {% set tips = dados.tipologias if dados.tipologias else [] %}\n'
        '    {% if not tips %}\n'
        '    <div class="tip-row" id="tip-0">\n'
        '      <div><input class="vb-inp" type="text" name="tip_nome_0" placeholder="Apart. 101"></div>\n'
        '      <div><select class="vb-sel" name="tip_tipo_0"><option>Residencial</option><option>Comercial</option></select></div>\n'
        '      <div><input class="vb-inp" type="number" name="tip_metragem_0" step="0.5" min="0" placeholder="102"></div>\n'
        '      <div><input class="vb-inp" type="number" name="tip_qtd_0" step="1" min="0" placeholder="1"></div>\n'
        '      <div><div class="pw"><span class="pre">R$</span><input class="vb-inp pl" type="number" name="tip_preco_0" step="100" placeholder="12.500"></div></div>\n'
        '      <div><input class="vb-inp" type="number" name="tip_andar_0" step="1" min="1" placeholder="1"></div>\n'
        '      <div style="display:flex;align-items:center;gap:.3rem;"><input type="checkbox" name="tip_permuta_0" value="1" id="perm0"><label for="perm0" style="font-size:.8rem;">Sim</label></div>\n'
        '      <div></div>\n'
        '    </div>\n'
        '    {% else %}\n'
        '    {% for t in tips %}\n'
        '    <div class="tip-row" id="tip-{{ loop.index0 }}">\n'
        '      <div><input class="vb-inp" type="text" name="tip_nome_{{ loop.index0 }}" value="{{ t.nome or \'\' }}" placeholder="Nome"></div>\n'
        '      <div><select class="vb-sel" name="tip_tipo_{{ loop.index0 }}"><option {% if t.tipo==\'Residencial\' %}selected{% endif %}>Residencial</option><option {% if t.tipo==\'Comercial\' %}selected{% endif %}>Comercial</option></select></div>\n'
        '      <div><input class="vb-inp" type="number" name="tip_metragem_{{ loop.index0 }}" step="0.5" value="{{ t.metragem }}"></div>\n'
        '      <div><input class="vb-inp" type="number" name="tip_qtd_{{ loop.index0 }}" step="1" value="{{ t.quantidade }}"></div>\n'
        '      <div><div class="pw"><span class="pre">R$</span><input class="vb-inp pl" type="number" name="tip_preco_{{ loop.index0 }}" step="100" value="{{ t.preco_m2 }}"></div></div>\n'
        '      <div><input class="vb-inp" type="number" name="tip_andar_{{ loop.index0 }}" step="1" value="{{ t.andar_inicio }}"></div>\n'
        '      <div style="display:flex;align-items:center;gap:.3rem;"><input type="checkbox" name="tip_permuta_{{ loop.index0 }}" value="1" id="perm{{ loop.index0 }}" {% if t.permuta %}checked{% endif %}><label for="perm{{ loop.index0 }}" style="font-size:.8rem;">Sim</label></div>\n'
        '      <div><button type="button" class="btn btn-sm btn-outline-danger" onclick="rmTip({{ loop.index0 }})">×</button></div>\n'
        '    </div>\n'
        '    {% endfor %}\n'
        '    {% endif %}\n'
        '  </div>\n'
        '  <button type="button" class="btn btn-outline-secondary btn-sm mt-2" onclick="addTip()">'
        '<i class="bi bi-plus-circle me-1"></i> Adicionar tipologia</button>\n'
        '  <div class="d-flex justify-content-between mt-3">\n'
        '    <button type="button" class="btn btn-outline-secondary" onclick="vbTab(\'premissas\',document.querySelector(\'[onclick*=premissas]\'))">'
        '<i class="bi bi-arrow-left me-1"></i> Voltar</button>\n'
        '    <button type="button" class="btn btn-primary" onclick="vbTab(\'custos\',document.querySelector(\'[onclick*=custos]\'))">'
        'Custos <i class="bi bi-arrow-right ms-1"></i></button>\n'
        '  </div>\n'
        '</div>'
    )
    _NEW_PROD = (
        '{# ── ABA 2: PRODUTO ── #}\n'
        '<div class="vb-sec card p-4 mb-3" id="tab-produto">\n'
        '  <h5 class="mb-3">Produto &amp; VGV</h5>\n'
        '  <div class="vb-row">\n'
        '    <div><div class="vb-lbl">Preço base (R$/m²)</div><div class="pw"><span class="pre">R$</span>'
        '<input class="vb-inp pl" type="number" name="preco_m2_base" step="100" min="0" placeholder="12.500" '
        'value="{{ dados.preco_m2_base or \'12500\' }}"></div></div>\n'
        '    <div><div class="vb-lbl">Diferencial por andar (%)</div><div class="pw"><span class="suf">%</span>'
        '<input class="vb-inp pr" type="number" name="diferencial_andar" step="0.1" min="0" max="5" '
        'placeholder="0.5" value="{{ dados.diferencial_andar or \'0.5\' }}"></div>'
        '<div class="vb-hint">Incremento automático no preço/m² a cada andar</div></div>\n'
        '  </div>\n'
        '  <div class="vb-sep">Pavimentos e Unidades</div>\n'
        '  <div id="pavCont">\n'
        '    {% set pav_list = dados.pavimentos if dados.pavimentos else [] %}\n'
        '    {% if not pav_list %}\n'
        '    <div class="pav-card" id="pav-0">\n'
        '      <div class="pav-hdr">\n'
        '        <div style="display:flex;align-items:center;gap:.75rem;flex:1;flex-wrap:wrap;">\n'
        '          <input class="vb-inp" type="text" name="pav_nome_0" placeholder="Ex: 4º Pavimento" style="max-width:220px;">\n'
        '          <div style="display:flex;align-items:center;gap:.4rem;">'
        '<span style="font-size:.75rem;color:var(--mc-muted);font-weight:600;">Andar</span>'
        '<input class="vb-inp" type="number" name="pav_andar_0" step="1" min="1" placeholder="4" style="width:70px;"></div>\n'
        '        </div>\n'
        '        <div style="display:flex;gap:.4rem;">\n'
        '          <button type="button" class="btn btn-sm btn-outline-primary" onclick="duplicarPav(0)" title="Duplicar pavimento">⧉ Duplicar</button>\n'
        '          <button type="button" class="btn btn-sm btn-outline-danger" onclick="rmPav(0)">✕</button>\n'
        '        </div>\n'
        '      </div>\n'
        '      <div class="pav-un-hdr"><span>Unidade</span><span>Tipo</span><span>m²</span>'
        '<span>Preço/m²</span><span>Dif. próprio</span><span>Permuta</span><span></span></div>\n'
        '      <div class="pav-un-body" id="pav-0-uns">\n'
        '        <div class="pav-un-row" id="pav-0-un-0">\n'
        '          <div><input class="vb-inp" type="text" name="un_nome_0_0" placeholder="401"></div>\n'
        '          <div><select class="vb-sel" name="un_tipo_0_0"><option>Residencial</option><option>Comercial</option></select></div>\n'
        '          <div><input class="vb-inp" type="number" name="un_met_0_0" step="0.5" min="0" placeholder="66,1"></div>\n'
        '          <div><div class="pw"><span class="pre">R$</span><input class="vb-inp pl" type="number" name="un_preco_0_0" step="100" placeholder="base"></div></div>\n'
        '          <div><div class="pw"><span class="suf">%</span><input class="vb-inp pr" type="number" name="un_dif_0_0" step="0.5" min="-20" max="20" placeholder="0" value="0"></div></div>\n'
        '          <div style="display:flex;align-items:center;gap:.3rem;">'
        '<input type="checkbox" name="un_perm_0_0" value="1" id="uperm_0_0">'
        '<label for="uperm_0_0" style="font-size:.8rem;">Sim</label></div>\n'
        '          <div><button type="button" class="btn btn-sm btn-outline-danger" onclick="rmUn(0,0)">✕</button></div>\n'
        '        </div>\n'
        '      </div>\n'
        '      <button type="button" class="btn btn-outline-secondary btn-sm mt-2" onclick="addUn(0)">'
        '<i class="bi bi-plus me-1"></i>Unidade</button>\n'
        '    </div>\n'
        '    {% else %}\n'
        '    {% for pav in pav_list %}{% set p = loop.index0 %}\n'
        '    <div class="pav-card" id="pav-{{ p }}">\n'
        '      <div class="pav-hdr">\n'
        '        <div style="display:flex;align-items:center;gap:.75rem;flex:1;flex-wrap:wrap;">\n'
        '          <input class="vb-inp" type="text" name="pav_nome_{{ p }}" value="{{ pav.nome }}" placeholder="Ex: 4º Pavimento" style="max-width:220px;">\n'
        '          <div style="display:flex;align-items:center;gap:.4rem;">'
        '<span style="font-size:.75rem;color:var(--mc-muted);font-weight:600;">Andar</span>'
        '<input class="vb-inp" type="number" name="pav_andar_{{ p }}" step="1" min="1" value="{{ pav.andar }}" style="width:70px;"></div>\n'
        '        </div>\n'
        '        <div style="display:flex;gap:.4rem;">\n'
        '          <button type="button" class="btn btn-sm btn-outline-primary" onclick="duplicarPav({{ p }})" title="Duplicar pavimento">⧉ Duplicar</button>\n'
        '          <button type="button" class="btn btn-sm btn-outline-danger" onclick="rmPav({{ p }})">✕</button>\n'
        '        </div>\n'
        '      </div>\n'
        '      <div class="pav-un-hdr"><span>Unidade</span><span>Tipo</span><span>m²</span>'
        '<span>Preço/m²</span><span>Dif. próprio</span><span>Permuta</span><span></span></div>\n'
        '      <div class="pav-un-body" id="pav-{{ p }}-uns">\n'
        '        {% for un in pav.unidades %}{% set u = loop.index0 %}\n'
        '        <div class="pav-un-row" id="pav-{{ p }}-un-{{ u }}">\n'
        '          <div><input class="vb-inp" type="text" name="un_nome_{{ p }}_{{ u }}" value="{{ un.nome }}" placeholder="Unidade"></div>\n'
        '          <div><select class="vb-sel" name="un_tipo_{{ p }}_{{ u }}">'
        '<option {% if un.tipo != \'Comercial\' %}selected{% endif %}>Residencial</option>'
        '<option {% if un.tipo == \'Comercial\' %}selected{% endif %}>Comercial</option></select></div>\n'
        '          <div><input class="vb-inp" type="number" name="un_met_{{ p }}_{{ u }}" step="0.5" value="{{ un.metragem }}"></div>\n'
        '          <div><div class="pw"><span class="pre">R$</span>'
        '<input class="vb-inp pl" type="number" name="un_preco_{{ p }}_{{ u }}" step="100" placeholder="base" '
        'value="{{ un.preco_proprio or \'\' }}"></div></div>\n'
        '          <div><div class="pw"><span class="suf">%</span>'
        '<input class="vb-inp pr" type="number" name="un_dif_{{ p }}_{{ u }}" step="0.5" min="-20" max="20" '
        'value="{{ un.dif_proprio or 0 }}"></div></div>\n'
        '          <div style="display:flex;align-items:center;gap:.3rem;">'
        '<input type="checkbox" name="un_perm_{{ p }}_{{ u }}" value="1" id="uperm_{{ p }}_{{ u }}" '
        '{% if un.permuta %}checked{% endif %}>'
        '<label for="uperm_{{ p }}_{{ u }}" style="font-size:.8rem;">Sim</label></div>\n'
        '          <div><button type="button" class="btn btn-sm btn-outline-danger" onclick="rmUn({{ p }},{{ u }})">✕</button></div>\n'
        '        </div>\n'
        '        {% endfor %}\n'
        '      </div>\n'
        '      <button type="button" class="btn btn-outline-secondary btn-sm mt-2" onclick="addUn({{ p }})">'
        '<i class="bi bi-plus me-1"></i>Unidade</button>\n'
        '    </div>\n'
        '    {% endfor %}\n'
        '    {% endif %}\n'
        '  </div>\n'
        '  <button type="button" class="btn btn-outline-secondary btn-sm mt-3" onclick="addPav()">'
        '<i class="bi bi-plus-circle me-1"></i>Adicionar Pavimento</button>\n'
        '  <div class="d-flex justify-content-between mt-3">\n'
        '    <button type="button" class="btn btn-outline-secondary" onclick="vbTab(\'premissas\',document.querySelector(\'[onclick*=premissas]\'))">'
        '<i class="bi bi-arrow-left me-1"></i> Voltar</button>\n'
        '    <button type="button" class="btn btn-primary" onclick="vbTab(\'custos\',document.querySelector(\'[onclick*=custos]\'))">'
        'Custos <i class="bi bi-arrow-right ms-1"></i></button>\n'
        '  </div>\n'
        '</div>'
    )
    if _OLD_PROD in tpl:
        tpl = tpl.replace(_OLD_PROD, _NEW_PROD, 1)
        changed = True
    else:
        print("[produto_v2] AVISO: patch B (aba produto) não encontrou string alvo")

    # ── C: Tabela de resultado — substituir tipologias por unidades ───────
    _OLD_RES_TIPS = (
        '    {% if dados and dados.tipologias %}\n'
        '    <h6 class="mb-2" style="color:#f97316;"><i class="bi bi-grid me-1"></i>Tipologias</h6>\n'
        '    <div style="overflow-x:auto;border:1px solid var(--mc-border);border-radius:12px;margin-bottom:1.25rem;">\n'
        '      <table style="width:100%;border-collapse:collapse;font-size:.84rem;">\n'
        '        <thead><tr style="background:#f97316;color:#fff;">\n'
        '          <th style="padding:.45rem .75rem;text-align:left;">Tipologia</th>\n'
        '          <th style="padding:.45rem .75rem;text-align:center;">Tipo</th>\n'
        '          <th style="padding:.45rem .75rem;text-align:right;">Metragem</th>\n'
        '          <th style="padding:.45rem .75rem;text-align:right;">Qtd</th>\n'
        '          <th style="padding:.45rem .75rem;text-align:right;">Preço/m²</th>\n'
        '          <th style="padding:.45rem .75rem;text-align:right;">VGV Tipologia</th>\n'
        '          <th style="padding:.45rem .75rem;text-align:center;">Permuta</th>\n'
        '        </tr></thead>\n'
        '        <tbody>\n'
        '          {% for t in dados.tipologias %}\n'
        '          <tr style="border-bottom:1px solid #f1f5f9;">\n'
        '            <td style="padding:.4rem .75rem;font-weight:600;">{{ t.nome or \'—\' }}</td>\n'
        '            <td style="padding:.4rem .75rem;text-align:center;"><span style="font-size:.75rem;padding:.15rem .5rem;border-radius:999px;background:#fff7ed;color:#f97316;font-weight:600;">{{ t.tipo }}</span></td>\n'
        '            <td style="padding:.4rem .75rem;text-align:right;">{{ t.metragem }} m²</td>\n'
        '            <td style="padding:.4rem .75rem;text-align:right;">{{ t.quantidade }}</td>\n'
        '            <td style="padding:.4rem .75rem;text-align:right;">{{ t.preco_m2|brl }}</td>\n'
        '            <td style="padding:.4rem .75rem;text-align:right;font-weight:600;color:#f97316;">{{ (t.metragem * t.quantidade * t.preco_m2)|brl }}</td>\n'
        '            <td style="padding:.4rem .75rem;text-align:center;">{% if t.permuta %}<span style="color:#dc2626;font-weight:600;">Sim</span>{% else %}—{% endif %}</td>\n'
        '          </tr>\n'
        '          {% endfor %}\n'
        '        </tbody>\n'
        '      </table>\n'
        '    </div>\n'
        '    {% endif %}'
    )
    _NEW_RES_TIPS = (
        '    {% if r.unidades %}\n'
        '    <div class="d-flex align-items-center justify-content-between mb-2">\n'
        '      <h6 class="mb-0" style="color:#f97316;"><i class="bi bi-building me-1"></i>Unidades por Pavimento</h6>\n'
        '      <button type="button" class="btn btn-sm btn-outline-success" onclick="exportarUnidadesExcel()" title="Exportar tabela para Excel"><i class="bi bi-file-earmark-excel me-1"></i>Excel</button>\n'
        '    </div>\n'
        '    <div style="overflow-x:auto;border:1px solid var(--mc-border);border-radius:12px;margin-bottom:1.25rem;">\n'
        '      <table id="tabelaUnidadesPav" style="width:100%;border-collapse:collapse;font-size:.84rem;">\n'
        '        <thead><tr style="background:#f97316;color:#fff;">\n'
        '          <th style="padding:.45rem .75rem;text-align:left;">Pavimento</th>\n'
        '          <th style="padding:.45rem .75rem;text-align:left;">Unidade</th>\n'
        '          <th style="padding:.45rem .75rem;text-align:center;">Tipo</th>\n'
        '          <th style="padding:.45rem .75rem;text-align:right;">m²</th>\n'
        '          <th style="padding:.45rem .75rem;text-align:right;">Dif. próprio</th>\n'
        '          <th style="padding:.45rem .75rem;text-align:right;">Preço/m² efetivo</th>\n'
        '          <th style="padding:.45rem .75rem;text-align:right;">Valor</th>\n'
        '          <th style="padding:.45rem .75rem;text-align:center;">Permuta</th>\n'
        '        </tr></thead>\n'
        '        <tbody>\n'
        '          {% set ns = namespace(last_pav=\'\') %}\n'
        '          {% for u in r.unidades %}\n'
        '          {% set row_pav = u.pavimento or (\'Andar \' + u.andar|string) %}\n'
        '          <tr style="border-bottom:1px solid #f1f5f9;{% if row_pav != ns.last_pav %}border-top:2px solid #fed7aa;{% endif %}">\n'
        '            <td style="padding:.4rem .75rem;font-size:.8rem;color:#94a3b8;font-weight:600;">'
        '{% if row_pav != ns.last_pav %}{{ row_pav }}{% set ns.last_pav = row_pav %}{% endif %}</td>\n'
        '            <td style="padding:.4rem .75rem;font-weight:600;">{{ u.nome }}</td>\n'
        '            <td style="padding:.4rem .75rem;text-align:center;">'
        '<span style="font-size:.75rem;padding:.15rem .5rem;border-radius:999px;background:#fff7ed;color:#f97316;font-weight:600;">{{ u.tipo }}</span></td>\n'
        '            <td style="padding:.4rem .75rem;text-align:right;">{{ u.metragem }} m²</td>\n'
        '            <td style="padding:.4rem .75rem;text-align:right;'
        'color:{% if u.dif_proprio > 0 %}#16a34a{% elif u.dif_proprio < 0 %}#dc2626{% else %}#94a3b8{% endif %};">'
        '{% if u.dif_proprio %}{{ \'+\' if u.dif_proprio > 0 else \'\' }}{{ u.dif_proprio }}%{% else %}—{% endif %}</td>\n'
        '            <td style="padding:.4rem .75rem;text-align:right;">{{ u.preco_m2|brl }}</td>\n'
        '            <td style="padding:.4rem .75rem;text-align:right;font-weight:600;color:#f97316;">{{ u.valor|brl }}</td>\n'
        '            <td style="padding:.4rem .75rem;text-align:center;">'
        '{% if u.permuta %}<span style="color:#dc2626;font-weight:600;">Sim</span>{% else %}—{% endif %}</td>\n'
        '          </tr>\n'
        '          {% endfor %}\n'
        '        </tbody>\n'
        '      </table>\n'
        '    </div>\n'
        '    {% endif %}'
    )
    if _OLD_RES_TIPS in tpl:
        tpl = tpl.replace(_OLD_RES_TIPS, _NEW_RES_TIPS, 1)
        changed = True
    else:
        print("[produto_v2] AVISO: patch C (tabela resultado) não encontrou string alvo")

    # ── D: JS — substituir addTip/rmTip por funções de pavimento ─────────
    _OLD_JS = (
        "let tipN=document.querySelectorAll('[id^=\"tip-\"]').length||1;\n"
        "function addTip(){\n"
        "  const c=document.getElementById('tipCont'),i=tipN++;\n"
        "  const d=document.createElement('div');d.className='tip-row';d.id='tip-'+i;\n"
        "  d.innerHTML=`<div><input class=\"vb-inp\" type=\"text\" name=\"tip_nome_${i}\" placeholder=\"Nome\"></div>"
        "<div><select class=\"vb-sel\" name=\"tip_tipo_${i}\"><option>Residencial</option><option>Comercial</option></select></div>"
        "<div><input class=\"vb-inp\" type=\"number\" name=\"tip_metragem_${i}\" step=\"0.5\" min=\"0\" placeholder=\"102\"></div>"
        "<div><input class=\"vb-inp\" type=\"number\" name=\"tip_qtd_${i}\" step=\"1\" min=\"0\" placeholder=\"1\"></div>"
        "<div><div class=\"pw\"><span class=\"pre\">R$</span><input class=\"vb-inp pl\" type=\"number\" name=\"tip_preco_${i}\" step=\"100\"></div></div>"
        "<div><input class=\"vb-inp\" type=\"number\" name=\"tip_andar_${i}\" step=\"1\" min=\"1\" placeholder=\"1\"></div>"
        "<div style=\"display:flex;align-items:center;gap:.3rem;\"><input type=\"checkbox\" name=\"tip_permuta_${i}\" value=\"1\" id=\"perm${i}\">"
        "<label for=\"perm${i}\" style=\"font-size:.8rem;\">Sim</label></div>"
        "<div><button type=\"button\" class=\"btn btn-sm btn-outline-danger\" onclick=\"rmTip(${i})\">x</button></div>`;\n"
        "  c.appendChild(d);\n"
        "}\n"
        "function rmTip(i){const el=document.getElementById('tip-'+i);if(el)el.remove();}"
    )
    _NEW_JS = (
        "// ── Pavimentos & Unidades ──\n"
        "let pavN=document.querySelectorAll('.pav-card').length||1;\n"
        "const unN={};\n"
        "document.querySelectorAll('.pav-card').forEach(el=>{\n"
        "  const p=parseInt(el.id.replace('pav-',''));\n"
        "  unN[p]=el.querySelectorAll('.pav-un-row').length||1;\n"
        "});\n"
        "function _mkUnRow(p,u,d){\n"
        "  d=d||{};\n"
        "  const div=document.createElement('div');\n"
        "  div.className='pav-un-row';div.id=`pav-${p}-un-${u}`;\n"
        "  div.innerHTML=`<div><input class=\"vb-inp\" type=\"text\" name=\"un_nome_${p}_${u}\" value=\"${d.nome||''}\" placeholder=\"Unidade\"></div>"
        "<div><select class=\"vb-sel\" name=\"un_tipo_${p}_${u}\"><option ${d.tipo!='Comercial'?'selected':''}>Residencial</option><option ${d.tipo=='Comercial'?'selected':''}>Comercial</option></select></div>"
        "<div><input class=\"vb-inp\" type=\"number\" name=\"un_met_${p}_${u}\" step=\"0.5\" min=\"0\" value=\"${d.met||''}\" placeholder=\"m²\"></div>"
        "<div><div class=\"pw\"><span class=\"pre\">R$</span><input class=\"vb-inp pl\" type=\"number\" name=\"un_preco_${p}_${u}\" step=\"100\" value=\"${d.preco||''}\" placeholder=\"base\"></div></div>"
        "<div><div class=\"pw\"><span class=\"suf\">%</span><input class=\"vb-inp pr\" type=\"number\" name=\"un_dif_${p}_${u}\" step=\"0.5\" min=\"-20\" max=\"20\" value=\"${d.dif!=null?d.dif:0}\" placeholder=\"0\"></div></div>"
        "<div style=\"display:flex;align-items:center;gap:.3rem;\"><input type=\"checkbox\" name=\"un_perm_${p}_${u}\" value=\"1\" id=\"uperm_${p}_${u}\" ${d.perm?'checked':''}><label for=\"uperm_${p}_${u}\" style=\"font-size:.8rem;\">Sim</label></div>"
        "<div><button type=\"button\" class=\"btn btn-sm btn-outline-danger\" onclick=\"rmUn(${p},${u})\">✕</button></div>`;\n"
        "  return div;\n"
        "}\n"
        "function addUn(p){\n"
        "  if(unN[p]==null)unN[p]=document.getElementById(`pav-${p}-uns`)?.querySelectorAll('.pav-un-row').length||0;\n"
        "  const u=unN[p]++;\n"
        "  document.getElementById(`pav-${p}-uns`)?.appendChild(_mkUnRow(p,u));\n"
        "}\n"
        "function rmUn(p,u){document.getElementById(`pav-${p}-un-${u}`)?.remove();}\n"
        "function _mkPavCard(p,andar,nome){\n"
        "  const div=document.createElement('div');\n"
        "  div.className='pav-card';div.id=`pav-${p}`;\n"
        "  div.innerHTML=`<div class=\"pav-hdr\"><div style=\"display:flex;align-items:center;gap:.75rem;flex:1;flex-wrap:wrap;\">"
        "<input class=\"vb-inp\" type=\"text\" name=\"pav_nome_${p}\" placeholder=\"Ex: ${andar}º Pavimento\" style=\"max-width:220px;\" value=\"${nome||''}\">"
        "<div style=\"display:flex;align-items:center;gap:.4rem;\"><span style=\"font-size:.75rem;color:var(--mc-muted);font-weight:600;\">Andar</span>"
        "<input class=\"vb-inp\" type=\"number\" name=\"pav_andar_${p}\" step=\"1\" min=\"1\" value=\"${andar}\" style=\"width:70px;\"></div></div>"
        "<div style=\"display:flex;gap:.4rem;\"><button type=\"button\" class=\"btn btn-sm btn-outline-primary\" onclick=\"duplicarPav(${p})\" title=\"Duplicar pavimento\">⧉ Duplicar</button>"
        "<button type=\"button\" class=\"btn btn-sm btn-outline-danger\" onclick=\"rmPav(${p})\">✕</button></div></div>"
        "<div class=\"pav-un-hdr\"><span>Unidade</span><span>Tipo</span><span>m²</span><span>Preço/m²</span><span>Dif. próprio</span><span>Permuta</span><span></span></div>"
        "<div class=\"pav-un-body\" id=\"pav-${p}-uns\"></div>"
        "<button type=\"button\" class=\"btn btn-outline-secondary btn-sm mt-2\" onclick=\"addUn(${p})\"><i class=\"bi bi-plus me-1\"></i>Unidade</button>`;\n"
        "  unN[p]=0;\n"
        "  return div;\n"
        "}\n"
        "function addPav(){\n"
        "  const p=pavN++;\n"
        "  const allAndares=Array.from(document.querySelectorAll('[name^=\"pav_andar_\"]')).map(el=>parseInt(el.value||0)).filter(n=>n>0);\n"
        "  const nextAndar=allAndares.length?Math.max(...allAndares)+1:4;\n"
        "  const card=_mkPavCard(p,nextAndar,'');\n"
        "  document.getElementById('pavCont').appendChild(card);\n"
        "  card.querySelector(`#pav-${p}-uns`).appendChild(_mkUnRow(p,unN[p]++));\n"
        "}\n"
        "function rmPav(p){document.getElementById(`pav-${p}`)?.remove();}\n"
        "function duplicarPav(srcP){\n"
        "  const srcAndarEl=document.querySelector(`[name=\"pav_andar_${srcP}\"]`);\n"
        "  const srcNomeEl=document.querySelector(`[name=\"pav_nome_${srcP}\"]`);\n"
        "  const srcAndar=parseInt(srcAndarEl?.value||1);\n"
        "  const srcNome=srcNomeEl?.value||'';\n"
        "  const newAndar=srcAndar+1;\n"
        "  let newNome=srcNome.replace(/\\d+/,n=>String(parseInt(n)+1));\n"
        "  if(!newNome||newNome===srcNome)newNome=`${newAndar}º Pavimento`;\n"
        "  const newP=pavN++;\n"
        "  const card=_mkPavCard(newP,newAndar,newNome);\n"
        "  document.getElementById('pavCont').appendChild(card);\n"
        "  document.querySelectorAll(`#pav-${srcP}-uns .pav-un-row`).forEach(row=>{\n"
        "    const u=unN[newP]++;\n"
        "    const nome=row.querySelector('[name^=\"un_nome_\"]')?.value||'';\n"
        "    const tipo=row.querySelector('[name^=\"un_tipo_\"]')?.value||'Residencial';\n"
        "    const met=row.querySelector('[name^=\"un_met_\"]')?.value||'';\n"
        "    const preco=row.querySelector('[name^=\"un_preco_\"]')?.value||'';\n"
        "    const dif=parseFloat(row.querySelector('[name^=\"un_dif_\"]')?.value||0);\n"
        "    const perm=row.querySelector('[name^=\"un_perm_\"]')?.checked||false;\n"
        "    const srcStr=String(srcAndar);\n"
        "    let newNomeUn=nome.startsWith(srcStr)?String(newAndar)+nome.slice(srcStr.length):nome;\n"
        "    document.getElementById(`pav-${newP}-uns`).appendChild(_mkUnRow(newP,u,{nome:newNomeUn,tipo,met,preco,dif,perm}));\n"
        "  });\n"
        "  if(unN[newP]===0){document.getElementById(`pav-${newP}-uns`).appendChild(_mkUnRow(newP,unN[newP]++));}\n"
        "}"
    )
    if _OLD_JS in tpl:
        tpl = tpl.replace(_OLD_JS, _NEW_JS, 1)
        changed = True
    else:
        print("[produto_v2] AVISO: patch D (JS) não encontrou string alvo")

    # ── E: JS — exportar tabela de unidades para Excel (CSV download) ────
    _EXPORT_JS = (
        "\n// ── Exportar Unidades por Pavimento ──\n"
        "function exportarUnidadesExcel(){\n"
        "  const tbl=document.getElementById('tabelaUnidadesPav');\n"
        "  if(!tbl){alert('Tabela não encontrada');return;}\n"
        "  const rows=Array.from(tbl.querySelectorAll('tr'));\n"
        "  const csv=rows.map(r=>Array.from(r.querySelectorAll('th,td')).map(c=>{\n"
        "    let v=c.innerText.trim().replace(/\\n/g,' ');\n"
        "    if(v.includes(',')||v.includes('\"'))v='\"'+v.replace(/\"/g,'\"\"')+'\"';\n"
        "    return v;\n"
        "  }).join(',')).join('\\n');\n"
        "  const bom='\\uFEFF';\n"
        "  const blob=new Blob([bom+csv],{type:'text/csv;charset=utf-8;'});\n"
        "  const a=document.createElement('a');\n"
        "  a.href=URL.createObjectURL(blob);\n"
        "  a.download='unidades_por_pavimento.csv';\n"
        "  a.click();\n"
        "}\n"
    )
    if _EXPORT_JS not in tpl:
        tpl = tpl.replace("</script>", _EXPORT_JS + "\n</script>", 1)
        changed = True

    # Sentinel
    tpl = tpl.replace("{% endblock %}", "{# _prodV3 #}\n{% endblock %}", 1)

    if changed:
        TEMPLATES["ferramenta_viabilidade.html"] = tpl
        print("[produto_v2] Template patcheado com UI de pavimentos")
    else:
        print("[produto_v2] Aviso: nenhuma patch aplicada")

    if hasattr(templates_env.loader, "mapping"):
        templates_env.loader.mapping = TEMPLATES


_patch_produto_v2()
print("[produto_v2] Módulo carregado — entrada por pavimento ativa")

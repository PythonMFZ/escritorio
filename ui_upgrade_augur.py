# ============================================================================
# PATCH — Augur: rota /api/ai/ask + widget no dashboard
# ============================================================================
# Cole ao final do app.py ou salve como ui_upgrade_augur.py e adicione:
#   exec(open('ui_upgrade_augur.py').read())
#
# PRÉ-REQUISITOS:
#   1. ai_assistant/ no diretório raiz do projeto
#   2. ai_assistant/chroma_db/ populado (via setup_ai.py)
#   3. ANTHROPIC_API_KEY no ambiente (Render + local)
#
# O QUE FAZ:
#   - Rota POST /api/ai/ask  — recebe pergunta, retorna resposta do Augur
#   - Injeta widget "Augur" no dashboard.html
# ============================================================================

import sys as _sys
import os as _os

# Garante que o diretório raiz está no path para importar ai_assistant
_project_root = _os.path.dirname(_os.path.abspath(__file__))
if _project_root not in _sys.path:
    _sys.path.insert(0, _project_root)


# ── Rota POST /api/ai/ask ────────────────────────────────────────────────────

@app.post("/api/ai/ask")
@require_login
async def augur_ask(request: Request, session: Session = Depends(get_session)):
    """
    Recebe pergunta do cliente e retorna resposta do Augur.

    Body JSON:
    {
        "question": "Meu caixa está apertado. O que faço?",
        "client_id": 123  (opcional — usa current_client se omitido)
    }
    """
    ctx = get_tenant_context(request, session)
    if not ctx:
        return JSONResponse({"error": "Não autenticado."}, status_code=401)

    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "JSON inválido."}, status_code=400)

    question = (body.get("question") or "").strip()
    if not question:
        return JSONResponse({"error": "Pergunta vazia."}, status_code=400)

    if len(question) > 1000:
        return JSONResponse({"error": "Pergunta muito longa (máx. 1000 caracteres)."}, status_code=400)

    # Busca dados do cliente
    client_id = body.get("client_id") or get_active_client_id(request, session, ctx)
    client    = get_client_or_none(session, ctx.company.id, client_id)

    if not client or not ensure_can_access_client(ctx, client.id):
        return JSONResponse({"error": "Cliente não encontrado."}, status_code=404)

    # Monta client_data com tudo que o Augur precisa
    client_data: dict = {
        "name":                client.name,
        "segment":             getattr(client, "segment", None),
        "revenue_monthly_brl": float(client.revenue_monthly_brl or 0),
        "cash_balance_brl":    float(client.cash_balance_brl or 0),
        "debt_total_brl":      float(client.debt_total_brl or 0),
        "employees_count":     getattr(client, "employees_count", None),
    }

    # Tenta enriquecer com o último snapshot
    try:
        snap = session.exec(
            select(ClientSnapshot)
            .where(
                ClientSnapshot.company_id == ctx.company.id,
                ClientSnapshot.client_id  == client.id,
            )
            .order_by(ClientSnapshot.created_at.desc())
            .limit(1)
        ).first()

        if snap:
            client_data.update({
                "score_total":    float(snap.score_total or 0),
                "score_financial": float(snap.score_financial or 0),
                "score_process":  float(snap.score_process or 0),
            })
    except Exception:
        pass

    # Tenta enriquecer com o business profile (balanço + DRE)
    try:
        profile = get_or_create_business_profile(
            session, company_id=ctx.company.id, client_id=client.id
        )
        if profile:
            for field in [
                "cash_and_investments_brl", "receivables_brl", "inventory_brl",
                "immobilized_brl", "payables_360_brl", "short_term_debt_brl",
                "long_term_debt_brl", "collateral_brl", "delinquency_brl",
                "monthly_fixed_cost_brl", "payroll_monthly_brl", "average_ticket_brl",
            ]:
                val = getattr(profile, field, None)
                if val:
                    client_data[field] = float(val)

            # Calcula indicadores DRE se tiver dados
            rev    = client_data.get("revenue_monthly_brl", 0)
            cmv    = client_data.get("monthly_fixed_cost_brl", 0)
            payroll = client_data.get("payroll_monthly_brl", 0)
            opex   = client_data.get("average_ticket_brl", 0)
            if rev > 0:
                mb = rev - cmv
                client_data["cmv"]     = cmv
                client_data["mb"]      = mb
                client_data["mb_pct"]  = round((mb / rev) * 100, 1)
                client_data["payroll"] = payroll
                client_data["opex"]    = opex
                client_data["ebitda"]  = mb - payroll - opex

            # Liquidez e capital de giro
            ac = (
                client_data.get("cash_and_investments_brl", 0) +
                client_data.get("receivables_brl", 0) +
                client_data.get("inventory_brl", 0)
            )
            pc = (
                client_data.get("payables_360_brl", 0) +
                client_data.get("short_term_debt_brl", 0)
            )
            client_data["ccl"] = ac - pc
            if pc > 0:
                client_data["liq_corrente"] = round(ac / pc, 2)

            # Estrutura de capital G4
            anc = client_data.get("immobilized_brl", 0)
            pnc = client_data.get("long_term_debt_brl", 0)
            at  = ac + anc
            pt  = pc + pnc
            pl  = at - pt
            if at > 0:
                if pl >= anc:
                    client_data["estrutura_label"] = "Saudável"
                elif (pl + pnc) >= anc:
                    client_data["estrutura_label"] = "Alerta"
                else:
                    client_data["estrutura_label"] = "Deficiente"
    except Exception:
        pass

    # Chama o Augur
    try:
        from ai_assistant.assistant import ask as augur_ask_fn
        result = augur_ask_fn(question=question, client_data=client_data)
    except ImportError:
        return JSONResponse({
            "error": "Augur não instalado. Execute setup_ai.py primeiro.",
            "response": None,
        }, status_code=503)
    except Exception as e:
        return JSONResponse({"error": str(e), "response": None}, status_code=500)

    # Salva no banco para histórico (opcional — tabela AIFeedback se existir)
    try:
        if hasattr(AIFeedback, "__tablename__"):
            fb = AIFeedback(
                company_id=ctx.company.id,
                client_id=client.id,
                question=question,
                ai_response=result.get("response", ""),
            )
            session.add(fb)
            session.commit()
    except Exception:
        pass

    return JSONResponse({
        "response":   result.get("response", ""),
        "confidence": result.get("confidence", 0),
        "error":      result.get("error", False),
    })


# ── Widget Augur no dashboard ─────────────────────────────────────────────────

_AUGUR_WIDGET = r"""
{# ── AUGUR WIDGET ── #}
{% if current_client %}
<div class="card mb-3" id="augurCard" style="border:1px solid var(--mc-border);">
  <div class="card-body p-3">
    <div class="d-flex align-items-center gap-2 mb-3">
      <div style="width:36px;height:36px;border-radius:10px;background:#1a1a1a;display:flex;align-items:center;justify-content:center;flex-shrink:0;overflow:hidden;">
        <img src="/static/augur_logo_v3.png" alt="Augur" style="width:26px;height:26px;object-fit:contain;">
      </div>
      <div>
        <div class="fw-bold" style="font-size:.95rem;">Augur</div>
        <div class="muted" style="font-size:.72rem;">Consultor financeiro inteligente · Maffezzolli Capital</div>
      </div>
    </div>

    {# Sugestões rápidas #}
    <div class="d-flex gap-2 flex-wrap mb-2" id="augurSuggestions">
      <button class="btn btn-outline-secondary btn-sm" style="font-size:.75rem;" onclick="augurSetQ('Meu caixa está apertado. O que faço?')">💸 Caixa apertado</button>
      <button class="btn btn-outline-secondary btn-sm" style="font-size:.75rem;" onclick="augurSetQ('Como posso melhorar meu score?')">📈 Melhorar score</button>
      <button class="btn btn-outline-secondary btn-sm" style="font-size:.75rem;" onclick="augurSetQ('Qual crédito faz sentido para minha situação?')">🏦 Crédito certo</button>
      <button class="btn btn-outline-secondary btn-sm" style="font-size:.75rem;" onclick="augurSetQ('O que está pesando no meu resultado?')">🔍 Analisar resultado</button>
    </div>

    {# Input #}
    <div class="d-flex gap-2">
      <textarea id="augurInput" class="form-control" rows="2"
        placeholder="Pergunte sobre sua situação financeira..."
        style="font-size:.88rem;resize:none;border-radius:10px;"
        onkeydown="if(event.key==='Enter'&&!event.shiftKey){event.preventDefault();augurSend();}"></textarea>
      <button class="btn btn-primary px-3" onclick="augurSend()" id="augurBtn"
        style="border-radius:10px;align-self:flex-end;">
        <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" fill="currentColor" viewBox="0 0 16 16">
          <path d="M15.964.686a.5.5 0 0 0-.65-.65L.767 5.855H.766l-.452.18a.5.5 0 0 0-.082.887l.41.26.001.002 4.995 3.178 3.178 4.995.002.002.26.41a.5.5 0 0 0 .886-.083zm-1.833 1.89L6.637 10.07l-.215-.338a.5.5 0 0 0-.154-.154l-.338-.215 7.494-7.494 1.178-.471z"/>
        </svg>
      </button>
    </div>

    {# Resposta #}
    <div id="augurResponse" style="display:none;margin-top:1rem;">
      <div id="augurLoading" style="display:none;color:var(--mc-muted);font-size:.85rem;padding:.5rem 0;">
        <div class="spinner-border spinner-border-sm me-2" role="status"></div>
        Augur está analisando seus dados...
      </div>
      <div id="augurAnswer" style="display:none;">
        <div style="background:#f9fafb;border-radius:12px;padding:1rem;font-size:.88rem;line-height:1.6;white-space:pre-wrap;border:1px solid var(--mc-border);" id="augurText"></div>
        <div class="d-flex justify-content-between align-items-center mt-2">
          <div style="font-size:.72rem;color:var(--mc-muted);" id="augurMeta"></div>
          <div class="d-flex gap-2">
            <button class="btn btn-sm btn-outline-secondary" onclick="augurFeedback(true)" title="Útil">👍</button>
            <button class="btn btn-sm btn-outline-secondary" onclick="augurFeedback(false)" title="Não útil">👎</button>
            <button class="btn btn-sm btn-outline-secondary" onclick="augurClear()">Nova pergunta</button>
          </div>
        </div>
      </div>
      <div id="augurError" style="display:none;color:var(--mc-danger);font-size:.85rem;padding:.5rem 0;"></div>
    </div>
  </div>
</div>

<script>
(function(){
  window.augurSetQ = function(q) {
    document.getElementById('augurInput').value = q;
    document.getElementById('augurInput').focus();
  };

  window.augurClear = function() {
    document.getElementById('augurInput').value = '';
    document.getElementById('augurResponse').style.display = 'none';
    document.getElementById('augurAnswer').style.display = 'none';
    document.getElementById('augurError').style.display = 'none';
    document.getElementById('augurSuggestions').style.display = 'flex';
    document.getElementById('augurInput').focus();
  };

  window.augurSend = async function() {
    const input = document.getElementById('augurInput');
    const q = (input.value || '').trim();
    if (!q) return;

    const btn = document.getElementById('augurBtn');
    const resp = document.getElementById('augurResponse');
    const loading = document.getElementById('augurLoading');
    const answer = document.getElementById('augurAnswer');
    const error = document.getElementById('augurError');
    const suggestions = document.getElementById('augurSuggestions');

    btn.disabled = true;
    resp.style.display = 'block';
    loading.style.display = 'block';
    answer.style.display = 'none';
    error.style.display = 'none';
    suggestions.style.display = 'none';

    try {
      const r = await fetch('/api/ai/ask', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({question: q}),
      });
      const data = await r.json();

      loading.style.display = 'none';

      if (data.error || !data.response) {
        error.style.display = 'block';
        error.textContent = data.error || 'Erro ao processar. Tente novamente.';
      } else {
        answer.style.display = 'block';
        document.getElementById('augurText').textContent = data.response;
        const conf = data.confidence ? Math.round(data.confidence * 100) : null;
        document.getElementById('augurMeta').textContent =
          conf ? `Confiança: ${conf}% · Augur by Maffezzolli Capital` : 'Augur by Maffezzolli Capital';
      }
    } catch(e) {
      loading.style.display = 'none';
      error.style.display = 'block';
      error.textContent = 'Erro de conexão. Tente novamente.';
    } finally {
      btn.disabled = false;
    }
  };

  window.augurFeedback = function(positive) {
    const btn = positive
      ? document.querySelector('[onclick="augurFeedback(true)"]')
      : document.querySelector('[onclick="augurFeedback(false)"]');
    if (btn) { btn.textContent = positive ? '✅' : '❌'; btn.disabled = true; }
  };
})();
</script>
{% endif %}
{# ── /AUGUR WIDGET ── #}
"""

# Injeta o widget no dashboard.html antes da seção de KPIs
_dash = TEMPLATES.get("dashboard.html", "")
_AUGUR_ANCHOR = "Painel de Saúde Financeira"
if _dash and _AUGUR_ANCHOR in _dash and "augurCard" not in _dash:
    # Insere o widget antes do primeiro h2/h3/div que contém "Painel de Saúde"
    _dash = _dash.replace(
        _AUGUR_ANCHOR,
        "AUGUR_WIDGET_PLACEHOLDER\n" + _AUGUR_ANCHOR,
        1,
    )
    # Substitui o placeholder pelo widget real
    _dash = _dash.replace("AUGUR_WIDGET_PLACEHOLDER", _AUGUR_WIDGET.strip())
    TEMPLATES["dashboard.html"] = _dash

# Atualiza loader
if hasattr(templates_env.loader, "mapping"):
    templates_env.loader.mapping = TEMPLATES

# ============================================================================
# FIM DO PATCH — Augur
# ============================================================================

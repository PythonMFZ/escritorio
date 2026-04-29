# ============================================================================
# PATCH — Augur v2: Histórico de conversa + Multi-turn
# ============================================================================
# Substitui ui_upgrade_augur.py
# Salve como ui_upgrade_augur.py (sobrescreve o anterior)
#
# NOVIDADES:
#   - Tabela AugurMensagem (histórico 15 dias por cliente)
#   - Multi-turn real: contexto das últimas 10 trocas enviado ao Claude
#   - Interface de chat com histórico visível
#   - Feedback 👍/👎 salvo por mensagem
#   - Rota GET /api/ai/historico
#   - Rota POST /api/ai/feedback/{msg_id}
# ============================================================================

import sys as _sys
import os as _os
import json as _json_augur
from datetime import datetime as _dt_augur, timedelta as _td_augur
from typing import Optional as _OptA
from sqlmodel import Field as _FA, SQLModel as _SMA

_project_root = _os.path.dirname(_os.path.abspath(__file__))
if _project_root not in _sys.path:
    _sys.path.insert(0, _project_root)


# ── Modelo ────────────────────────────────────────────────────────────────────

class AugurMensagem(_SMA, table=True):
    __tablename__  = "augurmensagem"
    __table_args__ = {"extend_existing": True}
    id:          _OptA[int] = _FA(default=None, primary_key=True)
    company_id:  int        = _FA(index=True)
    client_id:   int        = _FA(index=True)
    role:        str        = _FA(default="user")      # user | assistant
    content:     str        = _FA(default="")
    feedback:    _OptA[int] = _FA(default=None)        # 1=positivo, -1=negativo, None=sem feedback
    created_at:  str        = _FA(default="")

try:
    _SMA.metadata.create_all(engine, tables=[AugurMensagem.__table__])
except Exception:
    pass


# ── Rota POST /api/ai/ask (v2 com histórico) ─────────────────────────────────

@app.post("/api/ai/ask")
@require_login
async def augur_ask_v2(request: Request, session: Session = Depends(get_session)):
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
    if len(question) > 1500:
        return JSONResponse({"error": "Pergunta muito longa (máx. 1500 caracteres)."}, status_code=400)

    client_id = body.get("client_id") or get_active_client_id(request, session, ctx)
    client    = get_client_or_none(session, ctx.company.id, client_id)
    if not client:
        return JSONResponse({"error": "Cliente não encontrado."}, status_code=404)

    # Monta client_data
    client_data: dict = {
        "name":                client.name,
        "segment":             getattr(client, "segment", None),
        "revenue_monthly_brl": float(client.revenue_monthly_brl or 0),
        "cash_balance_brl":    float(client.cash_balance_brl or 0),
        "debt_total_brl":      float(client.debt_total_brl or 0),
    }
    try:
        snap = session.exec(
            select(ClientSnapshot)
            .where(ClientSnapshot.company_id == ctx.company.id,
                   ClientSnapshot.client_id  == client.id)
            .order_by(ClientSnapshot.created_at.desc()).limit(1)
        ).first()
        if snap:
            client_data.update({
                "score_total":     float(snap.score_total or 0),
                "score_financial": float(snap.score_financial or 0),
                "score_process":   float(snap.score_process or 0),
            })
    except Exception:
        pass

    # Busca histórico dos últimos 15 dias (máx 20 mensagens para contexto)
    cutoff = (_dt_augur.utcnow() - _td_augur(days=15)).isoformat()
    historico = session.exec(
        select(AugurMensagem)
        .where(
            AugurMensagem.company_id == ctx.company.id,
            AugurMensagem.client_id  == client.id,
            AugurMensagem.created_at >= cutoff,
        )
        .order_by(AugurMensagem.id.desc())
        .limit(20)
    ).all()
    historico = list(reversed(historico))  # ordem cronológica

    # Monta conversation_history para o Claude (últimas 10 trocas = 20 mensagens)
    conversation_history = [
        {"role": m.role, "content": m.content}
        for m in historico[-20:]
    ]

    # Salva a pergunta do usuário
    msg_user = AugurMensagem(
        company_id=ctx.company.id,
        client_id=client.id,
        role="user",
        content=question,
        created_at=_dt_augur.utcnow().isoformat(),
    )
    session.add(msg_user)
    session.commit()
    session.refresh(msg_user)

    # Chama o Augur
    try:
        from ai_assistant.assistant import ask as augur_ask_fn
        result = augur_ask_fn(
            question=question,
            client_data=client_data,
            conversation_history=conversation_history,
        )
    except ImportError:
        return JSONResponse({"error": "Augur não instalado.", "response": None}, status_code=503)
    except Exception as e:
        return JSONResponse({"error": str(e), "response": None}, status_code=500)

    # Salva a resposta do assistente
    msg_assistant = AugurMensagem(
        company_id=ctx.company.id,
        client_id=client.id,
        role="assistant",
        content=result.get("response", ""),
        created_at=_dt_augur.utcnow().isoformat(),
    )
    session.add(msg_assistant)
    session.commit()
    session.refresh(msg_assistant)

    return JSONResponse({
        "response":    result.get("response", ""),
        "confidence":  result.get("confidence", 0),
        "error":       result.get("error", False),
        "msg_id":      msg_assistant.id,
    })


# ── Rota GET /api/ai/historico ────────────────────────────────────────────────

@app.get("/api/ai/historico")
@require_login
async def augur_historico(request: Request, session: Session = Depends(get_session)):
    ctx = get_tenant_context(request, session)
    if not ctx:
        return JSONResponse({"error": "Não autenticado."}, status_code=401)

    client_id = get_active_client_id(request, session, ctx)
    client    = get_client_or_none(session, ctx.company.id, client_id)
    if not client:
        return JSONResponse({"mensagens": []})

    cutoff = (_dt_augur.utcnow() - _td_augur(days=15)).isoformat()
    msgs = session.exec(
        select(AugurMensagem)
        .where(
            AugurMensagem.company_id == ctx.company.id,
            AugurMensagem.client_id  == client.id,
            AugurMensagem.created_at >= cutoff,
        )
        .order_by(AugurMensagem.id.asc())
    ).all()

    return JSONResponse({
        "mensagens": [
            {
                "id":       m.id,
                "role":     m.role,
                "content":  m.content,
                "feedback": m.feedback,
                "data":     m.created_at[:10] if m.created_at else "",
                "hora":     m.created_at[11:16] if len(m.created_at) > 15 else "",
            }
            for m in msgs
        ]
    })


# ── Rota POST /api/ai/feedback/{msg_id} ──────────────────────────────────────

@app.post("/api/ai/feedback/{msg_id}")
@require_login
async def augur_feedback(msg_id: int, request: Request, session: Session = Depends(get_session)):
    ctx = get_tenant_context(request, session)
    if not ctx:
        return JSONResponse({"ok": False}, status_code=401)

    msg = session.get(AugurMensagem, msg_id)
    if not msg or msg.company_id != ctx.company.id:
        return JSONResponse({"ok": False}, status_code=404)

    body = await request.json()
    msg.feedback = 1 if body.get("positive") else -1
    session.add(msg)
    session.commit()
    return JSONResponse({"ok": True})


# ── Widget Augur v2 (chat com histórico) ─────────────────────────────────────

_AUGUR_WIDGET_V2 = r"""
{# ── AUGUR WIDGET v2 ── #}
{% if current_client %}
<div class="card mb-3" id="augurCard" style="border:1px solid var(--mc-border);">
  <div class="card-body p-0">

    {# Header #}
    <div class="d-flex align-items-center gap-2 p-3" style="border-bottom:1px solid var(--mc-border);">
      <div style="width:34px;height:34px;border-radius:10px;background:#1a1a1a;display:flex;align-items:center;justify-content:center;flex-shrink:0;overflow:hidden;">
        <img src="/static/augur_logo_v3.png" alt="Augur" style="width:24px;height:24px;object-fit:contain;">
      </div>
      <div style="flex:1;">
        <div class="fw-bold" style="font-size:.92rem;">Augur</div>
        <div class="muted" style="font-size:.7rem;">Consultor financeiro inteligente · 15 dias de histórico</div>
      </div>
      <button class="btn btn-sm btn-outline-secondary" onclick="augurLimparChat()" title="Nova conversa" style="font-size:.75rem;">
        <i class="bi bi-plus-circle me-1"></i>Nova conversa
      </button>
    </div>

    {# Área de chat #}
    <div id="augurChatArea" style="height:340px;overflow-y:auto;padding:1rem;display:flex;flex-direction:column;gap:.75rem;background:#fafafa;">
      {# Mensagens carregadas via JS #}
      <div id="augurLoading" style="text-align:center;color:var(--mc-muted);font-size:.82rem;padding:2rem 0;">
        <div class="spinner-border spinner-border-sm me-2" role="status"></div>
        Carregando histórico...
      </div>
    </div>

    {# Sugestões rápidas #}
    <div id="augurSuggestions" class="d-flex gap-2 flex-wrap px-3 py-2" style="border-top:1px solid var(--mc-border);background:#fff;">
      <button class="btn btn-outline-secondary btn-sm" style="font-size:.73rem;" onclick="augurSetQ('Meu caixa está apertado. O que faço?')">💸 Caixa apertado</button>
      <button class="btn btn-outline-secondary btn-sm" style="font-size:.73rem;" onclick="augurSetQ('Como posso melhorar meu score?')">📈 Melhorar score</button>
      <button class="btn btn-outline-secondary btn-sm" style="font-size:.73rem;" onclick="augurSetQ('Qual crédito faz sentido para minha situação?')">🏦 Crédito certo</button>
      <button class="btn btn-outline-secondary btn-sm" style="font-size:.73rem;" onclick="augurSetQ('O que está pesando no meu resultado?')">🔍 Analisar resultado</button>
    </div>

    {# Input #}
    <div class="d-flex gap-2 p-3" style="border-top:1px solid var(--mc-border);background:#fff;">
      <textarea id="augurInput" class="form-control" rows="2"
        placeholder="Pergunte ao Augur sobre sua situação financeira..."
        style="font-size:.86rem;resize:none;border-radius:10px;"
        onkeydown="if(event.key==='Enter'&&!event.shiftKey){event.preventDefault();augurSend();}"></textarea>
      <button class="btn btn-primary px-3" onclick="augurSend()" id="augurBtn" style="border-radius:10px;align-self:flex-end;">
        <i class="bi bi-send"></i>
      </button>
    </div>

  </div>
</div>

<style>
  .aug-msg { display:flex; gap:.5rem; max-width:100%; }
  .aug-msg.user { flex-direction:row-reverse; }
  .aug-bubble {
    max-width:82%; padding:.6rem .9rem; border-radius:14px;
    font-size:.84rem; line-height:1.55; white-space:pre-wrap; word-break:break-word;
  }
  .aug-bubble.user {
    background:var(--mc-primary); color:#fff; border-radius:14px 14px 4px 14px;
  }
  .aug-bubble.assistant {
    background:#fff; border:1px solid var(--mc-border); border-radius:14px 14px 14px 4px;
    color:var(--mc-text);
  }
  .aug-avatar {
    width:28px; height:28px; border-radius:50%; flex-shrink:0;
    display:flex; align-items:center; justify-content:center; font-size:.7rem; font-weight:700;
    align-self:flex-end;
  }
  .aug-avatar.user { background:var(--mc-primary); color:#fff; }
  .aug-avatar.assistant { background:#1a1a1a; overflow:hidden; }
  .aug-meta { font-size:.68rem; color:var(--mc-muted); margin-top:.25rem; }
  .aug-feedback { display:flex; gap:.3rem; margin-top:.35rem; }
  .aug-typing { display:flex; gap:4px; align-items:center; padding:.5rem .8rem; }
  .aug-typing span {
    width:7px; height:7px; border-radius:50%; background:var(--mc-muted);
    animation:augBounce 1.2s infinite;
  }
  .aug-typing span:nth-child(2) { animation-delay:.2s; }
  .aug-typing span:nth-child(3) { animation-delay:.4s; }
  @keyframes augBounce { 0%,60%,100%{transform:translateY(0)} 30%{transform:translateY(-6px)} }
</style>

<script>
(function(){
  let _augurMsgId = null;

  // ── Carrega histórico ao iniciar ──
  async function augurCarregarHistorico() {
    try {
      const r = await fetch('/api/ai/historico');
      const d = await r.json();
      const area = document.getElementById('augurChatArea');
      area.innerHTML = '';

      if (!d.mensagens || d.mensagens.length === 0) {
        area.innerHTML = '<div style="text-align:center;color:var(--mc-muted);font-size:.82rem;padding:2rem 0;">Nenhuma conversa nos últimos 15 dias.<br>Faça sua primeira pergunta!</div>';
        return;
      }

      d.mensagens.forEach(m => _augurRenderMsg(m.role, m.content, m.id, m.hora, false));
      _augurScrollBottom();
    } catch(e) {
      document.getElementById('augurChatArea').innerHTML =
        '<div style="text-align:center;color:var(--mc-muted);font-size:.82rem;padding:2rem 0;">Erro ao carregar histórico.</div>';
    }
  }

  // ── Renderiza uma mensagem no chat ──
  function _augurRenderMsg(role, content, msgId, hora, animate) {
    const area = document.getElementById('augurChatArea');

    // Remove placeholder se existir
    const placeholder = area.querySelector('[data-placeholder]');
    if (placeholder) placeholder.remove();

    const wrap = document.createElement('div');
    wrap.className = 'aug-msg ' + role;
    wrap.id = 'aug-msg-' + (msgId || Date.now());

    const avatarHtml = role === 'user'
      ? '<div class="aug-avatar user">EU</div>'
      : '<div class="aug-avatar assistant"><img src="/static/augur_logo_v3.png" style="width:20px;height:20px;object-fit:contain;"></div>';

    const feedbackHtml = role === 'assistant' && msgId ? `
      <div class="aug-feedback">
        <button class="btn btn-xs btn-outline-secondary" style="padding:.1rem .4rem;font-size:.7rem;"
                onclick="augurFeedback(${msgId}, true, this)">👍</button>
        <button class="btn btn-xs btn-outline-secondary" style="padding:.1rem .4rem;font-size:.7rem;"
                onclick="augurFeedback(${msgId}, false, this)">👎</button>
      </div>` : '';

    const horaHtml = hora ? `<div class="aug-meta">${hora}</div>` : '';

    wrap.innerHTML = avatarHtml + `
      <div>
        <div class="aug-bubble ${role}">${_escapeHtml(content)}</div>
        ${horaHtml}
        ${feedbackHtml}
      </div>`;

    if (animate) wrap.style.opacity = '0';
    area.appendChild(wrap);
    if (animate) setTimeout(() => { wrap.style.transition = 'opacity .3s'; wrap.style.opacity = '1'; }, 10);
    _augurScrollBottom();
    return wrap;
  }

  // ── Typing indicator ──
  function _augurShowTyping() {
    const area = document.getElementById('augurChatArea');
    const el = document.createElement('div');
    el.className = 'aug-msg assistant';
    el.id = 'aug-typing';
    el.innerHTML = '<div class="aug-avatar assistant"><img src="/static/augur_logo_v3.png" style="width:20px;height:20px;object-fit:contain;"></div>' +
      '<div class="aug-bubble assistant"><div class="aug-typing"><span></span><span></span><span></span></div></div>';
    area.appendChild(el);
    _augurScrollBottom();
  }

  function _augurHideTyping() {
    const el = document.getElementById('aug-typing');
    if (el) el.remove();
  }

  function _augurScrollBottom() {
    const area = document.getElementById('augurChatArea');
    area.scrollTop = area.scrollHeight;
  }

  function _escapeHtml(t) {
    return t.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
  }

  // ── Envia pergunta ──
  window.augurSend = async function() {
    const input = document.getElementById('augurInput');
    const q = (input.value || '').trim();
    if (!q) return;

    const btn = document.getElementById('augurBtn');
    btn.disabled = true;
    input.value = '';
    document.getElementById('augurSuggestions').style.display = 'none';

    // Renderiza pergunta do usuário imediatamente
    const hora = new Date().toTimeString().slice(0,5);
    _augurRenderMsg('user', q, null, hora, true);
    _augurShowTyping();

    try {
      const r = await fetch('/api/ai/ask', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({question: q}),
      });
      const d = await r.json();
      _augurHideTyping();

      if (d.error || !d.response) {
        _augurRenderMsg('assistant', '⚠️ ' + (d.error || 'Erro ao processar. Tente novamente.'), null, hora, true);
      } else {
        _augurMsgId = d.msg_id;
        _augurRenderMsg('assistant', d.response, d.msg_id, hora, true);
      }
    } catch(e) {
      _augurHideTyping();
      _augurRenderMsg('assistant', '⚠️ Erro de conexão. Tente novamente.', null, null, true);
    } finally {
      btn.disabled = false;
      input.focus();
    }
  };

  // ── Feedback ──
  window.augurFeedback = async function(msgId, positive, btn) {
    try {
      await fetch('/api/ai/feedback/' + msgId, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({positive}),
      });
      const wrap = btn.closest('.aug-feedback');
      if (wrap) wrap.innerHTML = positive
        ? '<span style="font-size:.75rem;color:#16a34a;">✅ Obrigado pelo feedback!</span>'
        : '<span style="font-size:.75rem;color:#dc2626;">Vamos melhorar. Obrigado!</span>';
    } catch(e) {}
  };

  // ── Sugestão rápida ──
  window.augurSetQ = function(q) {
    document.getElementById('augurInput').value = q;
    document.getElementById('augurInput').focus();
  };

  // ── Nova conversa (limpa visualmente, não apaga o banco) ──
  window.augurLimparChat = function() {
    const area = document.getElementById('augurChatArea');
    area.innerHTML = '<div data-placeholder style="text-align:center;color:var(--mc-muted);font-size:.82rem;padding:2rem 0;">Nova conversa iniciada. Faça sua pergunta!</div>';
    document.getElementById('augurSuggestions').style.display = 'flex';
    document.getElementById('augurInput').value = '';
    document.getElementById('augurInput').focus();
  };

  // Carrega ao iniciar
  augurCarregarHistorico();
})();
</script>
{% endif %}
{# ── /AUGUR WIDGET v2 ── #}
"""

# Injeta widget no dashboard
_dash = TEMPLATES.get("dashboard.html", "")
_AUGUR_ANCHOR = "Painel de Saúde Financeira"
if _dash and _AUGUR_ANCHOR in _dash and "augurCard" not in _dash:
    _dash = _dash.replace(
        _AUGUR_ANCHOR,
        "AUGUR_WIDGET_PLACEHOLDER\n" + _AUGUR_ANCHOR,
        1,
    )
    _dash = _dash.replace("AUGUR_WIDGET_PLACEHOLDER", _AUGUR_WIDGET_V2.strip())
    TEMPLATES["dashboard.html"] = _dash
elif _dash and "augurCard" in _dash:
    # Atualiza widget existente - substitui pelo v2
    import re as _re
    _dash = _re.sub(
        r'\{#\s*── AUGUR WIDGET.*?── /AUGUR WIDGET.*?#\}',
        _AUGUR_WIDGET_V2.strip(),
        _dash,
        flags=_re.DOTALL
    )
    TEMPLATES["dashboard.html"] = _dash

if hasattr(templates_env.loader, "mapping"):
    templates_env.loader.mapping = TEMPLATES

# ============================================================================
# FIM DO PATCH — Augur v2
# ============================================================================

# ============================================================================
# PATCH — Augur v3: Contexto Total + Anexos
# ============================================================================
# Substitui ui_upgrade_augur.py
#
# NOVIDADES vs v2:
#   - client_data enriquecido: histórico diagnósticos, reuniões Notion,
#     viabilidades, obras ativas
#   - Suporte a anexos: PDF, imagem, CSV/Excel
#   - Widget atualizado com botão de anexo
# ============================================================================

import sys as _sys
import os as _os
import json as _json_a3
import base64 as _b64
from datetime import datetime as _dt_a3, timedelta as _td_a3
from typing import Optional as _OptA3
from sqlmodel import Field as _FA3, SQLModel as _SMA3


# ── Modelo AugurMensagem ──────────────────────────────────────────────────────

class AugurMensagem(_SMA3, table=True):
    __tablename__  = "augurmensagem"
    __table_args__ = {"extend_existing": True}
    id:          _OptA3[int] = _FA3(default=None, primary_key=True)
    company_id:  int         = _FA3(index=True)
    client_id:   int         = _FA3(index=True)
    role:        str         = _FA3(default="user")
    content:     str         = _FA3(default="")
    feedback:    _OptA3[int] = _FA3(default=None)
    created_at:  str         = _FA3(default="")

try:
    _SMA3.metadata.create_all(engine, tables=[AugurMensagem.__table__])
except Exception:
    pass


# ── Helper: enriquece client_data com contexto completo ──────────────────────

def _enriquecer_client_data(session, company_id: int, client_id: int, client, client_data: dict) -> dict:
    """Adiciona histórico de diagnósticos, reuniões, viabilidades e obras ao client_data."""

    # 1. Histórico de diagnósticos (snapshots)
    try:
        snaps = session.exec(
            select(ClientSnapshot)
            .where(ClientSnapshot.company_id == company_id,
                   ClientSnapshot.client_id  == client_id)
            .order_by(ClientSnapshot.created_at.desc())
            .limit(10)
        ).all()
        client_data["snapshots_historico"] = [
            {
                "data":            str(s.created_at)[:10] if s.created_at else "",
                "score_total":     float(s.score_total or 0),
                "score_financial": float(s.score_financial or 0),
                "score_process":   float(s.score_process or 0),
            }
            for s in snaps
        ]
    except Exception:
        client_data["snapshots_historico"] = []

    # 2. Reuniões recentes do Notion (via AugurMensagem de contexto ou direto)
    try:
        from ai_assistant.assistant import _get_reunioes_cliente as _grc
        client_data["reunioes_recentes"] = _grc(client.name) or []
    except Exception:
        client_data["reunioes_recentes"] = []

    # 3. Viabilidades recentes
    try:
        viabs = session.exec(
            select(ViabilidadeAnalise)
            .where(ViabilidadeAnalise.company_id == company_id,
                   ViabilidadeAnalise.client_id  == client_id)
            .order_by(ViabilidadeAnalise.id.desc())
            .limit(3)
        ).all()
        client_data["viabilidades_recentes"] = []
        for v in viabs:
            try:
                resultado = _json_a3.loads(v.resultado_json)
                client_data["viabilidades_recentes"].append({
                    "nome":      v.nome,
                    "resultado": resultado,
                })
            except Exception:
                pass
    except Exception:
        client_data["viabilidades_recentes"] = []

    # 4. Obras ativas
    try:
        obras_raw = session.exec(
            select(Obra)
            .where(Obra.company_id == company_id,
                   Obra.client_id  == client_id,
                   Obra.status     == "em_andamento")
            .limit(3)
        ).all()
        client_data["obras_ativas"] = []
        for o in obras_raw:
            try:
                calc = _calcular_obra(session, o)
                client_data["obras_ativas"].append({
                    "nome": o.nome,
                    "calc": {
                        "fisico_geral":  calc.get("fisico_geral", 0),
                        "realizado_rs":  calc.get("realizado_rs", 0),
                        "orcado_total":  calc.get("orcado_total", 0),
                        "idc":           calc.get("idc", 1),
                    },
                })
            except Exception:
                pass
    except Exception:
        client_data["obras_ativas"] = []

    return client_data


# ── Rota POST /api/ai/ask (v3) ────────────────────────────────────────────────

@app.post("/api/ai/ask")
@require_login
async def augur_ask_v3(request: Request, session: Session = Depends(get_session)):
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
    if len(question) > 2000:
        return JSONResponse({"error": "Pergunta muito longa (máx. 2000 caracteres)."}, status_code=400)

    client_id = body.get("client_id") or get_active_client_id(request, session, ctx)
    client    = get_client_or_none(session, ctx.company.id, client_id)
    if not client:
        return JSONResponse({"error": "Cliente não encontrado."}, status_code=404)

    # Monta client_data base
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
            # Dados do balanço
            try:
                answers = _json_a3.loads(snap.answers_json or "{}")
                for k in ["receivables_brl","inventory_brl","payables_360_brl",
                           "short_term_debt_brl","long_term_debt_brl","collateral_brl",
                           "delinquency_brl","cmv","payroll","opex","mb","mb_pct",
                           "ebitda","liq_corrente","ccl","pe_mensal","margem_seg"]:
                    if k in answers:
                        client_data[k] = answers[k]
            except Exception:
                pass
    except Exception:
        pass

    # Enriquece com contexto completo
    client_data = _enriquecer_client_data(session, ctx.company.id, client.id, client, client_data)

    # Busca histórico da conversa (15 dias)
    cutoff = (_dt_a3.utcnow() - _td_a3(days=15)).isoformat()
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
    conversation_history = [
        {"role": m.role, "content": m.content}
        for m in reversed(historico)
    ]

    # Processa anexos
    attachments = []
    for att in (body.get("attachments") or []):
        att_type = att.get("type", "")
        att_data = att.get("data", "")
        att_name = att.get("name", "arquivo")
        if att_data:
            attachments.append({"type": att_type, "data": att_data, "name": att_name})

    # Salva pergunta
    msg_user = AugurMensagem(
        company_id=ctx.company.id, client_id=client.id,
        role="user", content=question,
        created_at=_dt_a3.utcnow().isoformat(),
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
            attachments=attachments if attachments else None,
        )
    except ImportError:
        return JSONResponse({"error": "Augur não instalado.", "response": None}, status_code=503)
    except Exception as e:
        return JSONResponse({"error": str(e), "response": None}, status_code=500)

    # Salva resposta
    msg_assistant = AugurMensagem(
        company_id=ctx.company.id, client_id=client.id,
        role="assistant", content=result.get("response", ""),
        created_at=_dt_a3.utcnow().isoformat(),
    )
    session.add(msg_assistant)
    session.commit()
    session.refresh(msg_assistant)

    return JSONResponse({
        "response":   result.get("response", ""),
        "confidence": result.get("confidence", 0),
        "error":      result.get("error", False),
        "msg_id":     msg_assistant.id,
    })


# ── Rota GET /api/ai/historico ────────────────────────────────────────────────

@app.get("/api/ai/historico")
@require_login
async def augur_historico_v3(request: Request, session: Session = Depends(get_session)):
    ctx = get_tenant_context(request, session)
    if not ctx:
        return JSONResponse({"mensagens": []})

    client_id = get_active_client_id(request, session, ctx)
    client    = get_client_or_none(session, ctx.company.id, client_id)
    if not client:
        return JSONResponse({"mensagens": []})

    cutoff = (_dt_a3.utcnow() - _td_a3(days=15)).isoformat()
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
                "hora":     m.created_at[11:16] if len(m.created_at) > 15 else "",
            }
            for m in msgs
        ]
    })


# ── Rota POST /api/ai/feedback/{msg_id} ──────────────────────────────────────

@app.post("/api/ai/feedback/{msg_id}")
@require_login
async def augur_feedback_v3(msg_id: int, request: Request, session: Session = Depends(get_session)):
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


# ── Widget Augur v3 (chat + anexos) ──────────────────────────────────────────

_AUGUR_WIDGET_V3 = r"""
{# ── AUGUR WIDGET v3 ── #}
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
        <div class="muted" style="font-size:.7rem;">Consultor financeiro inteligente · Vê reuniões, diagnósticos, obras e viabilidades</div>
      </div>
      <button class="btn btn-sm btn-outline-secondary" onclick="augurLimparChat()" style="font-size:.75rem;">
        <i class="bi bi-plus-circle me-1"></i>Nova conversa
      </button>
    </div>

    {# Área de chat #}
    <div id="augurChatArea" style="height:340px;overflow-y:auto;padding:1rem;display:flex;flex-direction:column;gap:.75rem;background:#fafafa;">
      <div id="augurLoading" style="text-align:center;color:var(--mc-muted);font-size:.82rem;padding:2rem 0;">
        <div class="spinner-border spinner-border-sm me-2" role="status"></div>
        Carregando histórico...
      </div>
    </div>

    {# Preview de anexo #}
    <div id="augurAnexoPreview" style="display:none;padding:.5rem 1rem;background:#f0f9ff;border-top:1px solid #bae6fd;font-size:.78rem;">
      <div class="d-flex align-items-center gap-2">
        <i class="bi bi-paperclip text-primary"></i>
        <span id="augurAnexoNome" style="flex:1;"></span>
        <button class="btn btn-sm btn-outline-danger" style="padding:.1rem .4rem;font-size:.7rem;" onclick="removerAnexo()">✕</button>
      </div>
    </div>

    {# Sugestões #}
    <div id="augurSuggestions" class="d-flex gap-2 flex-wrap px-3 py-2" style="border-top:1px solid var(--mc-border);background:#fff;">
      <button class="btn btn-outline-secondary btn-sm" style="font-size:.73rem;" onclick="augurSetQ('Meu caixa está apertado. O que faço?')">💸 Caixa apertado</button>
      <button class="btn btn-outline-secondary btn-sm" style="font-size:.73rem;" onclick="augurSetQ('Como posso melhorar meu score?')">📈 Melhorar score</button>
      <button class="btn btn-outline-secondary btn-sm" style="font-size:.73rem;" onclick="augurSetQ('Qual crédito faz sentido para minha situação?')">🏦 Crédito certo</button>
      <button class="btn btn-outline-secondary btn-sm" style="font-size:.73rem;" onclick="augurSetQ('O que está pesando no meu resultado?')">🔍 Analisar resultado</button>
    </div>

    {# Input + Anexo #}
    <div class="d-flex gap-2 p-3 align-items-end" style="border-top:1px solid var(--mc-border);background:#fff;">
      <div style="position:relative;">
        <input type="file" id="augurFileInput" style="display:none;"
               accept=".pdf,.png,.jpg,.jpeg,.gif,.webp,.csv,.xlsx,.xls"
               onchange="selecionarAnexo(this)">
        <button class="btn btn-outline-secondary" style="border-radius:10px;padding:.45rem .65rem;font-size:.8rem;white-space:nowrap;"
                onclick="document.getElementById('augurFileInput').click()" title="Anexar arquivo">
          <i class="bi bi-paperclip me-1"></i><span style="font-size:.78rem;">Anexar</span>
        </button>
      </div>
      <textarea id="augurInput" class="form-control" rows="2"
        placeholder="Pergunte ao Augur — ele vê seus dados, reuniões e projetos..."
        style="font-size:.86rem;resize:none;border-radius:10px;"
        onkeydown="if(event.key==='Enter'&&!event.shiftKey){event.preventDefault();augurSend();}"></textarea>
      <button class="btn btn-primary" onclick="augurSend()" id="augurBtn"
              style="border-radius:10px;align-self:flex-end;min-width:90px;font-size:.8rem;padding:.45rem .8rem;white-space:nowrap;">
        <i class="bi bi-send-fill me-1"></i>Enviar
      </button>
    </div>

  </div>
</div>

<style>
  .aug-msg{display:flex;gap:.5rem;max-width:100%;}
  .aug-msg.user{flex-direction:row-reverse;}
  .aug-bubble{max-width:82%;padding:.6rem .9rem;border-radius:14px;font-size:.84rem;line-height:1.55;white-space:pre-wrap;word-break:break-word;}
  .aug-bubble.user{background:var(--mc-primary);color:#fff;border-radius:14px 14px 4px 14px;}
  .aug-bubble.assistant{background:#fff;border:1px solid var(--mc-border);border-radius:14px 14px 14px 4px;color:var(--mc-text);}
  .aug-avatar{width:28px;height:28px;border-radius:50%;flex-shrink:0;display:flex;align-items:center;justify-content:center;font-size:.7rem;font-weight:700;align-self:flex-end;}
  .aug-avatar.user{background:var(--mc-primary);color:#fff;}
  .aug-avatar.assistant{background:#1a1a1a;overflow:hidden;}
  .aug-meta{font-size:.68rem;color:var(--mc-muted);margin-top:.25rem;}
  .aug-feedback{display:flex;gap:.3rem;margin-top:.35rem;}
  .aug-typing{display:flex;gap:4px;align-items:center;padding:.5rem .8rem;}
  .aug-typing span{width:7px;height:7px;border-radius:50%;background:var(--mc-muted);animation:augBounce 1.2s infinite;}
  .aug-typing span:nth-child(2){animation-delay:.2s;}
  .aug-typing span:nth-child(3){animation-delay:.4s;}
  @keyframes augBounce{0%,60%,100%{transform:translateY(0)}30%{transform:translateY(-6px)}}
  .aug-anexo-badge{background:#dbeafe;color:#1e40af;border-radius:6px;padding:.15rem .5rem;font-size:.7rem;font-weight:600;}
</style>

<script>
(function(){
  let _augurAnexo = null;

  // ── Carrega histórico ──
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

  // ── Renderiza mensagem ──
  function _augurRenderMsg(role, content, msgId, hora, animate) {
    const area = document.getElementById('augurChatArea');
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
                onclick="augurFeedback(${msgId},true,this)">👍</button>
        <button class="btn btn-xs btn-outline-secondary" style="padding:.1rem .4rem;font-size:.7rem;"
                onclick="augurFeedback(${msgId},false,this)">👎</button>
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
    if (animate) setTimeout(() => { wrap.style.transition='opacity .3s'; wrap.style.opacity='1'; }, 10);
    _augurScrollBottom();
  }

  function _augurShowTyping() {
    const area = document.getElementById('augurChatArea');
    const el = document.createElement('div');
    el.className = 'aug-msg assistant'; el.id = 'aug-typing';
    el.innerHTML = '<div class="aug-avatar assistant"><img src="/static/augur_logo_v3.png" style="width:20px;height:20px;object-fit:contain;"></div>' +
      '<div class="aug-bubble assistant"><div class="aug-typing"><span></span><span></span><span></span></div></div>';
    area.appendChild(el); _augurScrollBottom();
  }
  function _augurHideTyping() { const el=document.getElementById('aug-typing'); if(el) el.remove(); }
  function _augurScrollBottom() { const a=document.getElementById('augurChatArea'); a.scrollTop=a.scrollHeight; }
  function _escapeHtml(t) { return t.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }

  // ── Seleção de anexo ──
  window.selecionarAnexo = async function(input) {
    const file = input.files[0];
    if (!file) return;
    if (file.size > 10 * 1024 * 1024) { alert('Arquivo muito grande. Máximo 10MB.'); return; }

    const ext = file.name.split('.').pop().toLowerCase();
    let tipo = '';

    if (ext === 'pdf') tipo = 'pdf';
    else if (['png','jpg','jpeg','gif','webp'].includes(ext)) tipo = 'image/' + (ext === 'jpg' ? 'jpeg' : ext);
    else if (['csv','xlsx','xls'].includes(ext)) {
      // CSV/Excel: lê como texto
      try {
        const txt = await file.text();
        _augurAnexo = { type: 'csv', data: txt.slice(0, 50000), name: file.name };
      } catch(e) { alert('Erro ao ler planilha.'); return; }
      _mostrarAnexoPreview(file.name); return;
    } else { alert('Tipo de arquivo não suportado.'); return; }

    // PDF e imagens: converte para base64
    const reader = new FileReader();
    reader.onload = function(e) {
      const base64 = e.target.result.split(',')[1];
      _augurAnexo = { type: tipo, data: base64, name: file.name };
      _mostrarAnexoPreview(file.name);
    };
    reader.readAsDataURL(file);
    input.value = '';
  };

  function _mostrarAnexoPreview(nome) {
    document.getElementById('augurAnexoNome').textContent = '📎 ' + nome;
    document.getElementById('augurAnexoPreview').style.display = 'block';
  }

  window.removerAnexo = function() {
    _augurAnexo = null;
    document.getElementById('augurAnexoPreview').style.display = 'none';
    document.getElementById('augurFileInput').value = '';
  };

  // ── Envia pergunta ──
  window.augurSend = async function() {
    const input = document.getElementById('augurInput');
    const q = (input.value || '').trim();
    if (!q && !_augurAnexo) return;

    const btn = document.getElementById('augurBtn');
    btn.disabled = true;
    btn.innerHTML = '<i class="bi bi-hourglass-split me-1"></i>Pensando...';
    input.value = '';
    document.getElementById('augurSuggestions').style.display = 'none';

    const hora = new Date().toTimeString().slice(0,5);
    const displayQ = q + (_augurAnexo ? ` [📎 ${_augurAnexo.name}]` : '');
    _augurRenderMsg('user', displayQ, null, hora, true);
    _augurShowTyping();

    const payload = { question: q || '(Analise o arquivo anexado)' };
    if (_augurAnexo) payload.attachments = [_augurAnexo];

    const anexoAtual = _augurAnexo;
    _augurAnexo = null;
    document.getElementById('augurAnexoPreview').style.display = 'none';

    try {
      const r = await fetch('/api/ai/ask', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(payload),
      });
      const d = await r.json();
      _augurHideTyping();
      if (d.error || !d.response) {
        _augurRenderMsg('assistant', '⚠️ ' + (d.error || 'Erro ao processar. Tente novamente.'), null, hora, true);
      } else {
        _augurRenderMsg('assistant', d.response, d.msg_id, hora, true);
      }
    } catch(e) {
      _augurHideTyping();
      _augurRenderMsg('assistant', '⚠️ Erro de conexão. Tente novamente.', null, null, true);
    } finally {
      btn.disabled = false;
      btn.innerHTML = '<i class="bi bi-send-fill me-1"></i>Enviar';
      input.focus();
    }
  };

  window.augurFeedback = async function(msgId, positive, btn) {
    try {
      await fetch('/api/ai/feedback/' + msgId, {
        method: 'POST', headers: {'Content-Type':'application/json'},
        body: JSON.stringify({positive}),
      });
      const wrap = btn.closest('.aug-feedback');
      if (wrap) wrap.innerHTML = positive
        ? '<span style="font-size:.75rem;color:#16a34a;">✅ Obrigado!</span>'
        : '<span style="font-size:.75rem;color:#dc2626;">Vamos melhorar!</span>';
    } catch(e) {}
  };

  window.augurSetQ = function(q) {
    document.getElementById('augurInput').value = q;
    document.getElementById('augurInput').focus();
  };

  window.augurLimparChat = function() {
    const area = document.getElementById('augurChatArea');
    area.innerHTML = '<div data-placeholder style="text-align:center;color:var(--mc-muted);font-size:.82rem;padding:2rem 0;">Nova conversa iniciada.</div>';
    document.getElementById('augurSuggestions').style.display = 'flex';
    document.getElementById('augurInput').value = '';
    document.getElementById('augurInput').focus();
    _augurAnexo = null;
    document.getElementById('augurAnexoPreview').style.display = 'none';
  };

  augurCarregarHistorico();
})();
</script>
{% endif %}
{# ── /AUGUR WIDGET v3 ── #}
"""

# ── Injeta widget no dashboard ────────────────────────────────────────────────
_dash = TEMPLATES.get("dashboard.html", "")
if _dash:
    import re as _re_a3
    _dash = _re_a3.sub(
        r'\{#\s*── AUGUR WIDGET.*?── /AUGUR WIDGET.*?#\}',
        _AUGUR_WIDGET_V3.strip(),
        _dash,
        flags=_re_a3.DOTALL,
    )
    if "augurCard" not in _dash:
        # Widget ainda não foi injetado — injeta na âncora
        _AUGUR_ANCHOR = "Painel de Saúde Financeira"
        if _AUGUR_ANCHOR in _dash:
            _dash = _dash.replace(_AUGUR_ANCHOR,
                                   _AUGUR_WIDGET_V3.strip() + "\n" + _AUGUR_ANCHOR, 1)
    TEMPLATES["dashboard.html"] = _dash

if hasattr(templates_env.loader, "mapping"):
    templates_env.loader.mapping = TEMPLATES

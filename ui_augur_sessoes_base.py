# ============================================================================
# PATCH — Augur v4: Sessões por Usuário + Base de Conhecimento
# ============================================================================
# Novidades:
# 1. AugurSessao — sessões privadas por user_id (21 dias)
# 2. AugurMensagem ganha user_id e session_id
# 3. Widget Augur com histórico lateral de sessões
# 4. BaseConhecimento — upload de documentos por cliente
# 5. Augur injeta documentos relevantes da base no contexto
#
# DEPLOY: adicione ao final do app.py
# ============================================================================

import json as _json_av4
import os as _os_av4
import re as _re_av4
from datetime import datetime as _dt_av4, timedelta as _td_av4
from typing import Optional as _Opt_av4
from sqlmodel import Field as _F_av4, SQLModel as _SM_av4, select as _sel_av4
from fastapi import Request as _Req_av4, Depends as _Dep_av4, UploadFile as _Upload_av4, File as _File_av4, Form as _Form_av4
from fastapi.responses import JSONResponse as _JSON_av4, RedirectResponse as _RR_av4, HTMLResponse as _HTML_av4


# ── Modelos ───────────────────────────────────────────────────────────────────

class AugurSessao(_SM_av4, table=True):
    __tablename__  = "augursessao"
    __table_args__ = {"extend_existing": True}
    id:          _Opt_av4[int] = _F_av4(default=None, primary_key=True)
    company_id:  int           = _F_av4(index=True)
    client_id:   int           = _F_av4(index=True)
    user_id:     int           = _F_av4(index=True)
    titulo:      str           = _F_av4(default="Nova conversa")
    created_at:  str           = _F_av4(default="")
    updated_at:  str           = _F_av4(default="")

class BaseConhecimento(_SM_av4, table=True):
    __tablename__  = "baseconhecimento"
    __table_args__ = {"extend_existing": True}
    id:              _Opt_av4[int] = _F_av4(default=None, primary_key=True)
    company_id:      int           = _F_av4(index=True)
    client_id:       int           = _F_av4(index=True)
    user_id:         int           = _F_av4(index=True)
    nome:            str           = _F_av4(default="")
    descricao:       str           = _F_av4(default="")
    tipo:            str           = _F_av4(default="")
    conteudo_texto:  str           = _F_av4(default="")
    created_at:      str           = _F_av4(default="")

try:
    _SM_av4.metadata.create_all(engine, tables=[
        AugurSessao.__table__,
        BaseConhecimento.__table__,
    ])
except Exception as _e_av4:
    print(f"[augur_v4] Tabelas: {_e_av4}")

# Adiciona user_id e session_id na AugurMensagem se não existir
try:
    with engine.connect() as _conn_av4:
        try:
            _conn_av4.execute(__import__('sqlalchemy').text("ALTER TABLE augurmensagem ADD COLUMN user_id INTEGER DEFAULT 0"))
            _conn_av4.commit()
            print("[augur_v4] Coluna user_id adicionada em augurmensagem")
        except Exception:
            pass
        try:
            _conn_av4.execute(__import__('sqlalchemy').text("ALTER TABLE augurmensagem ADD COLUMN session_id INTEGER DEFAULT 0"))
            _conn_av4.commit()
            print("[augur_v4] Coluna session_id adicionada em augurmensagem")
        except Exception:
            pass
except Exception as _e2_av4:
    print(f"[augur_v4] Alter table: {_e2_av4}")


# ── Helper: busca documentos relevantes da base ───────────────────────────────

def _buscar_base_conhecimento(session, company_id: int, client_id: int, pergunta: str) -> list[dict]:
    """Busca documentos relevantes da base de conhecimento por palavras-chave."""
    try:
        docs = session.exec(
            _sel_av4(BaseConhecimento)
            .where(
                BaseConhecimento.company_id == company_id,
                BaseConhecimento.client_id  == client_id,
            )
            .order_by(BaseConhecimento.id.desc())
            .limit(20)
        ).all()

        if not docs:
            return []

        # Busca simples por relevância — palavras da pergunta vs descrição+nome
        palavras = set(_re_av4.findall(r'\w{4,}', pergunta.lower()))
        relevantes = []
        for doc in docs:
            texto_busca = f"{doc.nome} {doc.descricao}".lower()
            score = sum(1 for p in palavras if p in texto_busca)
            if score > 0 or len(docs) <= 3:  # sempre inclui se poucos docs
                relevantes.append({"doc": doc, "score": score})

        relevantes.sort(key=lambda x: x["score"], reverse=True)
        return [r["doc"] for r in relevantes[:3]]
    except Exception as e:
        print(f"[augur_v4] Erro busca base: {e}")
        return []


# ── Rota POST /api/ai/ask (v4 — com sessões e base de conhecimento) ───────────

@app.post("/api/ai/ask")
@require_login
async def augur_ask_v4(request: _Req_av4, session=_Dep_av4(get_session)):
    ctx = get_tenant_context(request, session)
    if not ctx:
        return _JSON_av4({"error": "Não autenticado."}, status_code=401)

    try:
        body = await request.json()
    except Exception:
        return _JSON_av4({"error": "JSON inválido."}, status_code=400)

    question   = (body.get("question") or "").strip()
    session_id = body.get("session_id") or 0
    client_id  = body.get("client_id") or get_active_client_id(request, session, ctx)
    client     = get_client_or_none(session, ctx.company.id, client_id)

    if not question:
        return _JSON_av4({"error": "Pergunta vazia."}, status_code=400)
    if not client:
        return _JSON_av4({"error": "Cliente não encontrado."}, status_code=404)

    # Verifica/cria sessão
    sessao = None
    if session_id:
        sessao = session.get(AugurSessao, int(session_id))
        if sessao and (sessao.company_id != ctx.company.id or sessao.user_id != ctx.user.id):
            sessao = None

    if not sessao:
        sessao = AugurSessao(
            company_id=ctx.company.id,
            client_id=client.id,
            user_id=ctx.user.id,
            titulo="Nova conversa",
            created_at=_dt_av4.utcnow().isoformat(),
            updated_at=_dt_av4.utcnow().isoformat(),
        )
        session.add(sessao)
        session.commit()
        session.refresh(sessao)

    # Verifica créditos
    try:
        _preco_augur = _get_preco(session, ctx.company.id, "augur_mensal", default=0)
        if _preco_augur > 0:
            _wallet = session.exec(
                _sel_av4(CreditWallet)
                .where(CreditWallet.company_id == ctx.company.id, CreditWallet.client_id == client.id)
            ).first()
            _saldo = (_wallet.balance_cents / 100) if _wallet else 0.0
            if _saldo < _preco_augur:
                return _JSON_av4({"error": f"Saldo insuficiente.", "precisa_creditos": True}, status_code=402)
            if _wallet:
                _wallet.balance_cents -= int(_preco_augur * 100)
                _wallet.updated_at = utcnow()
                session.add(_wallet)
                session.commit()
    except Exception:
        pass

    # Monta client_data
    client_data = {
        "name":                client.name,
        "segment":             getattr(client, "segment", None),
        "revenue_monthly_brl": float(client.revenue_monthly_brl or 0),
        "cash_balance_brl":    float(client.cash_balance_brl or 0),
        "debt_total_brl":      float(client.debt_total_brl or 0),
    }
    try:
        snap = session.exec(
            _sel_av4(ClientSnapshot)
            .where(ClientSnapshot.company_id == ctx.company.id, ClientSnapshot.client_id == client.id)
            .order_by(ClientSnapshot.created_at.desc()).limit(1)
        ).first()
        if snap:
            client_data.update({
                "score_total":     float(snap.score_total or 0),
                "score_financial": float(snap.score_financial or 0),
                "score_process":   float(snap.score_process or 0),
            })
            try:
                answers = _json_av4.loads(snap.answers_json or "{}")
                for k in ["receivables_brl","inventory_brl","payables_360_brl","short_term_debt_brl",
                           "long_term_debt_brl","collateral_brl","delinquency_brl","cmv","payroll",
                           "opex","mb","mb_pct","ebitda","liq_corrente","ccl","pe_mensal","margem_seg"]:
                    if k in answers:
                        client_data[k] = answers[k]
            except Exception:
                pass
    except Exception:
        pass

    client_data = _enriquecer_client_data(session, ctx.company.id, client.id, client, client_data)

    # Injeta base de conhecimento no contexto
    docs_base = _buscar_base_conhecimento(session, ctx.company.id, client.id, question)
    if docs_base:
        client_data["base_conhecimento"] = [
            {
                "nome":      d.nome,
                "descricao": d.descricao,
                "conteudo":  d.conteudo_texto[:2000],
                "data":      d.created_at[:10] if d.created_at else "",
            }
            for d in docs_base
        ]

    # Histórico da sessão (21 dias, só do user_id)
    cutoff = (_dt_av4.utcnow() - _td_av4(days=21)).isoformat()
    historico = session.exec(
        _sel_av4(AugurMensagem)
        .where(
            AugurMensagem.company_id == ctx.company.id,
            AugurMensagem.client_id  == client.id,
            AugurMensagem.session_id == sessao.id,
            AugurMensagem.created_at >= cutoff,
        )
        .order_by(AugurMensagem.id.desc())
        .limit(20)
    ).all()
    conversation_history = [{"role": m.role, "content": m.content} for m in reversed(historico)]

    # Processa anexos
    attachments = []
    for att in (body.get("attachments") or []):
        if att.get("data"):
            attachments.append(att)

    # Salva pergunta
    msg_user = AugurMensagem(
        company_id=ctx.company.id,
        client_id=client.id,
        user_id=ctx.user.id,
        session_id=sessao.id,
        role="user",
        content=question,
        created_at=_dt_av4.utcnow().isoformat(),
    )
    session.add(msg_user)

    # Atualiza sessão
    sessao.updated_at = _dt_av4.utcnow().isoformat()
    if sessao.titulo == "Nova conversa" and len(question) > 10:
        sessao.titulo = question[:50]
    session.add(sessao)
    session.commit()

    # Chama Augur
    try:
        from ai_assistant.assistant import ask as augur_ask_fn
        result = augur_ask_fn(
            question=question,
            client_data=client_data,
            conversation_history=conversation_history,
            attachments=attachments if attachments else None,
        )
    except ImportError:
        return _JSON_av4({"error": "Augur não instalado.", "response": None}, status_code=503)
    except Exception as e:
        return _JSON_av4({"error": str(e), "response": None}, status_code=500)

    # Salva resposta
    msg_assistant = AugurMensagem(
        company_id=ctx.company.id,
        client_id=client.id,
        user_id=ctx.user.id,
        session_id=sessao.id,
        role="assistant",
        content=result.get("response", ""),
        created_at=_dt_av4.utcnow().isoformat(),
    )
    session.add(msg_assistant)
    session.commit()
    session.refresh(msg_assistant)

    return _JSON_av4({
        "response":    result.get("response", ""),
        "confidence":  result.get("confidence", 0),
        "error":       result.get("error", False),
        "msg_id":      msg_assistant.id,
        "session_id":  sessao.id,
        "session_titulo": sessao.titulo,
    })


# ── Rota GET /api/ai/sessoes ──────────────────────────────────────────────────

@app.get("/api/ai/sessoes")
@require_login
async def augur_sessoes(request: _Req_av4, session=_Dep_av4(get_session)):
    ctx = get_tenant_context(request, session)
    if not ctx:
        return _JSON_av4({"sessoes": []})

    client_id = get_active_client_id(request, session, ctx)
    client    = get_client_or_none(session, ctx.company.id, client_id)
    if not client:
        return _JSON_av4({"sessoes": []})

    cutoff = (_dt_av4.utcnow() - _td_av4(days=21)).isoformat()
    sessoes = session.exec(
        _sel_av4(AugurSessao)
        .where(
            AugurSessao.company_id == ctx.company.id,
            AugurSessao.client_id  == client.id,
            AugurSessao.user_id    == ctx.user.id,
            AugurSessao.created_at >= cutoff,
        )
        .order_by(AugurSessao.updated_at.desc())
        .limit(20)
    ).all()

    return _JSON_av4({
        "sessoes": [
            {"id": s.id, "titulo": s.titulo, "updated_at": s.updated_at[:10] if s.updated_at else ""}
            for s in sessoes
        ]
    })


# ── Rota GET /api/ai/sessoes/{id}/mensagens ───────────────────────────────────

@app.get("/api/ai/sessoes/{sessao_id}/mensagens")
@require_login
async def augur_sessao_mensagens(sessao_id: int, request: _Req_av4, session=_Dep_av4(get_session)):
    ctx = get_tenant_context(request, session)
    if not ctx:
        return _JSON_av4({"mensagens": []})

    sessao = session.get(AugurSessao, sessao_id)
    if not sessao or sessao.company_id != ctx.company.id or sessao.user_id != ctx.user.id:
        return _JSON_av4({"mensagens": []}, status_code=403)

    msgs = session.exec(
        _sel_av4(AugurMensagem)
        .where(
            AugurMensagem.company_id == ctx.company.id,
            AugurMensagem.session_id == sessao_id,
        )
        .order_by(AugurMensagem.id.asc())
    ).all()

    return _JSON_av4({
        "mensagens": [
            {"id": m.id, "role": m.role, "content": m.content,
             "hora": m.created_at[11:16] if len(m.created_at) > 15 else ""}
            for m in msgs
        ]
    })


# ── Rota POST /api/ai/sessoes/{id}/renomear ───────────────────────────────────

@app.post("/api/ai/sessoes/{sessao_id}/renomear")
@require_login
async def augur_sessao_renomear(sessao_id: int, request: _Req_av4, session=_Dep_av4(get_session)):
    ctx = get_tenant_context(request, session)
    if not ctx:
        return _JSON_av4({"ok": False}, status_code=401)

    sessao = session.get(AugurSessao, sessao_id)
    if not sessao or sessao.company_id != ctx.company.id or sessao.user_id != ctx.user.id:
        return _JSON_av4({"ok": False}, status_code=403)

    body = await request.json()
    titulo = (body.get("titulo") or "").strip()[:80]
    if titulo:
        sessao.titulo = titulo
        session.add(sessao)
        session.commit()

    return _JSON_av4({"ok": True, "titulo": sessao.titulo})


# ── Rotas Base de Conhecimento ────────────────────────────────────────────────

@app.post("/api/base-conhecimento/upload")
@require_login
async def base_conhecimento_upload(
    request: _Req_av4,
    session=_Dep_av4(get_session),
):
    ctx = get_tenant_context(request, session)
    if not ctx:
        return _JSON_av4({"ok": False, "erro": "Não autenticado."}, status_code=401)

    client_id = get_active_client_id(request, session, ctx)
    client    = get_client_or_none(session, ctx.company.id, client_id)
    if not client:
        return _JSON_av4({"ok": False, "erro": "Nenhum cliente selecionado."})

    try:
        body = await request.json()
    except Exception:
        return _JSON_av4({"ok": False, "erro": "JSON inválido."})

    nome      = (body.get("nome") or "").strip()[:200]
    descricao = (body.get("descricao") or "").strip()[:500]
    tipo      = (body.get("tipo") or "texto").strip()
    conteudo  = (body.get("conteudo") or "").strip()[:50000]

    if not nome or not conteudo:
        return _JSON_av4({"ok": False, "erro": "Nome e conteúdo são obrigatórios."})

    doc = BaseConhecimento(
        company_id=ctx.company.id,
        client_id=client.id,
        user_id=ctx.user.id,
        nome=nome,
        descricao=descricao,
        tipo=tipo,
        conteudo_texto=conteudo,
        created_at=_dt_av4.utcnow().isoformat(),
    )
    session.add(doc)
    session.commit()
    session.refresh(doc)

    return _JSON_av4({"ok": True, "id": doc.id, "nome": doc.nome})


@app.get("/api/base-conhecimento")
@require_login
async def base_conhecimento_listar(request: _Req_av4, session=_Dep_av4(get_session)):
    ctx = get_tenant_context(request, session)
    if not ctx:
        return _JSON_av4({"docs": []})

    client_id = get_active_client_id(request, session, ctx)
    client    = get_client_or_none(session, ctx.company.id, client_id)
    if not client:
        return _JSON_av4({"docs": []})

    docs = session.exec(
        _sel_av4(BaseConhecimento)
        .where(
            BaseConhecimento.company_id == ctx.company.id,
            BaseConhecimento.client_id  == client.id,
        )
        .order_by(BaseConhecimento.id.desc())
        .limit(50)
    ).all()

    return _JSON_av4({
        "docs": [
            {"id": d.id, "nome": d.nome, "descricao": d.descricao,
             "tipo": d.tipo, "created_at": d.created_at[:10] if d.created_at else ""}
            for d in docs
        ]
    })


@app.delete("/api/base-conhecimento/{doc_id}")
@require_login
async def base_conhecimento_deletar(doc_id: int, request: _Req_av4, session=_Dep_av4(get_session)):
    ctx = get_tenant_context(request, session)
    if not ctx:
        return _JSON_av4({"ok": False}, status_code=401)

    doc = session.get(BaseConhecimento, doc_id)
    if not doc or doc.company_id != ctx.company.id:
        return _JSON_av4({"ok": False}, status_code=404)

    session.delete(doc)
    session.commit()
    return _JSON_av4({"ok": True})


# ── Injeta context base_conhecimento no assistant ─────────────────────────────

try:
    import ai_assistant.assistant as _augur_ast_v4
    _fmt_orig_v4 = _augur_ast_v4._format_client_context

    def _format_client_context_v4(client_data: dict) -> str:
        ctx_str = _fmt_orig_v4(client_data)
        base = client_data.get("base_conhecimento", [])
        if base:
            ctx_str += "\n\n=== BASE DE CONHECIMENTO DO CLIENTE ==="
            ctx_str += "\nDocumentos fornecidos pelo cliente. Use quando relevante para a pergunta."
            for doc in base:
                ctx_str += f"\n\n--- {doc['nome']} ({doc.get('data','')}) ---"
                if doc.get('descricao'):
                    ctx_str += f"\nDescrição: {doc['descricao']}"
                ctx_str += f"\n{doc['conteudo'][:1500]}"
        return ctx_str

    _augur_ast_v4._format_client_context = _format_client_context_v4
    print("[augur_v4] ✅ Base de conhecimento injetada no contexto do Augur")
except Exception as _e_ast_v4:
    print(f"[augur_v4] ⚠️ Erro ao injetar base: {_e_ast_v4}")


# ── Widget Augur v4 (sessões + base de conhecimento) ─────────────────────────

_AUGUR_WIDGET_V4 = r"""
{# ── AUGUR WIDGET v4 ── #}
{% if current_client %}
<div class="card mb-3" id="augurCard" style="border:1px solid var(--mc-border);">
  <div class="card-body p-0">

    {# Header #}
    <div class="d-flex align-items-center gap-2 p-3" style="border-bottom:1px solid var(--mc-border);">
      <div style="width:34px;height:34px;border-radius:10px;background:#1a1a1a;display:flex;align-items:center;justify-content:center;flex-shrink:0;overflow:hidden;">
        <img src="/static/augur_logo_v3.png" alt="Augur" style="width:24px;height:24px;object-fit:contain;">
      </div>
      <div style="flex:1;">
        <div class="fw-bold" style="font-size:.92rem;">Augur <span id="augurSessaoTitulo" style="font-weight:400;font-size:.78rem;color:var(--mc-muted);margin-left:.5rem;"></span></div>
        <div class="muted" style="font-size:.7rem;">Consultor financeiro inteligente</div>
      </div>
      <button class="btn btn-sm btn-outline-secondary" onclick="augurNovaConversa()" style="font-size:.75rem;">
        ✏️ Nova conversa
      </button>
    </div>

    {# Layout: chat + sidebar sessões #}
    <div style="display:flex;height:460px;">

      {# Sidebar sessões #}
      <div id="augurSidebar" style="width:220px;border-right:1px solid var(--mc-border);overflow-y:auto;padding:.5rem;background:#f8f9fa;flex-shrink:0;">
        <div style="font-size:.7rem;font-weight:600;color:var(--mc-muted);padding:.25rem .5rem;margin-bottom:.25rem;letter-spacing:.05em;">CONVERSAS</div>
        <div id="augurSessaoLista"></div>
      </div>

      {# Área de chat #}
      <div style="flex:1;display:flex;flex-direction:column;min-width:0;max-width:calc(100% - 220px);">
        <div id="augurChatArea" style="flex:1;overflow-y:auto;padding:1rem 1.25rem;display:flex;flex-direction:column;gap:.75rem;background:#fafafa;">
          <div id="augurLoading" style="text-align:center;color:var(--mc-muted);font-size:.82rem;padding:2rem 0;">
            <div class="spinner-border spinner-border-sm me-2" role="status"></div>
            Carregando...
          </div>
        </div>

        {# Preview de anexo #}
        <div id="augurAnexoPreview" style="display:none;padding:.5rem 1rem;background:#f0f9ff;border-top:1px solid #bae6fd;font-size:.78rem;">
          <div class="d-flex align-items-center gap-2">
            <span id="augurAnexoNome" style="flex:1;"></span>
            <button class="btn btn-sm btn-outline-danger" style="padding:.1rem .4rem;font-size:.7rem;" onclick="removerAnexo()">✕</button>
          </div>
        </div>

        {# Sugestões #}
        <div id="augurSuggestions" class="d-flex gap-2 flex-wrap px-3 py-2" style="border-top:1px solid var(--mc-border);background:#fff;">
          <button class="btn btn-outline-secondary btn-sm" style="font-size:.73rem;" onclick="augurSetQ('Meu caixa está apertado. O que faço?')">💸 Caixa apertado</button>
          <button class="btn btn-outline-secondary btn-sm" style="font-size:.73rem;" onclick="augurSetQ('Como posso melhorar meu score?')">📈 Melhorar score</button>
          <button class="btn btn-outline-secondary btn-sm" style="font-size:.73rem;" onclick="augurSetQ('Qual crédito faz sentido para minha situação?')">🏦 Crédito certo</button>
        </div>

        {# Input #}
        <div class="d-flex gap-2 p-3 align-items-end" style="border-top:1px solid var(--mc-border);background:#fff;">
          <div>
            <input type="file" id="augurFileInput" style="display:none;"
                   accept=".pdf,.png,.jpg,.jpeg,.gif,.webp,.csv,.xlsx,.xls"
                   onchange="selecionarAnexo(this)">
            <button class="btn btn-outline-secondary" style="border-radius:10px;padding:.45rem .65rem;font-size:.8rem;"
                    onclick="document.getElementById('augurFileInput').click()" title="Anexar">📎</button>
          </div>
          <textarea id="augurInput" class="form-control" rows="2"
            placeholder="Pergunte ao Augur..."
            style="font-size:.86rem;resize:none;border-radius:10px;"
            onkeydown="if(event.key==='Enter'&&!event.shiftKey){event.preventDefault();augurSend();}"></textarea>
          <button class="btn btn-primary" onclick="augurSend()" id="augurBtn"
                  style="border-radius:10px;align-self:flex-end;min-width:80px;font-size:.8rem;padding:.45rem .8rem;">
            Enviar
          </button>
        </div>
      </div>
    </div>
  </div>
</div>

<style>
  .aug-msg{display:flex;gap:.5rem;max-width:100%;}
  .aug-msg.user{flex-direction:row-reverse;}
  .aug-bubble{max-width:85%;padding:.6rem .9rem;border-radius:14px;font-size:.84rem;line-height:1.55;white-space:pre-wrap;word-break:break-word;}
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
  .aug-sessao-item{padding:.35rem .5rem;border-radius:8px;cursor:pointer;font-size:.75rem;color:var(--mc-text);margin-bottom:.2rem;line-height:1.3;word-break:break-word;}
  .aug-sessao-item:hover{background:var(--mc-border);}
  .aug-sessao-item.ativa{background:var(--mc-primary);color:#fff;}
</style>

<script>
(function(){
  let _sessaoAtual = null;
  let _augurAnexo = null;

  // ── Carrega sessões do usuário ──
  async function augurCarregarSessoes() {
    try {
      const r = await fetch('/api/ai/sessoes');
      const d = await r.json();
      const lista = document.getElementById('augurSessaoLista');
      lista.innerHTML = '';
      if (!d.sessoes || d.sessoes.length === 0) {
        lista.innerHTML = '<div style="font-size:.7rem;color:var(--mc-muted);padding:.5rem;">Nenhuma conversa</div>';
        augurNovaConversa();
        return;
      }
      d.sessoes.forEach(s => {
        const el = document.createElement('div');
        el.className = 'aug-sessao-item' + (_sessaoAtual === s.id ? ' ativa' : '');
        el.dataset.id = s.id;
        el.innerHTML = `<div style="font-weight:500;">${_escapeHtml(s.titulo)}</div><div style="font-size:.65rem;opacity:.7;">${s.updated_at}</div>`;
        el.onclick = () => augurCarregarSessao(s.id, s.titulo);
        el.ondblclick = () => augurRenomearSessao(s.id, s.titulo, el);
        lista.appendChild(el);
      });
      // Carrega a primeira sessão automaticamente
      if (!_sessaoAtual && d.sessoes.length > 0) {
        augurCarregarSessao(d.sessoes[0].id, d.sessoes[0].titulo);
      }
    } catch(e) {
      console.error('[augur] Erro ao carregar sessões:', e);
      augurNovaConversa();
    }
  }

  // ── Carrega mensagens de uma sessão ──
  async function augurCarregarSessao(id, titulo) {
    _sessaoAtual = id;
    document.getElementById('augurSessaoTitulo').textContent = titulo || '';
    document.querySelectorAll('.aug-sessao-item').forEach(el => {
      el.classList.toggle('ativa', parseInt(el.dataset.id) === id);
    });
    const area = document.getElementById('augurChatArea');
    area.innerHTML = '<div style="text-align:center;color:var(--mc-muted);font-size:.82rem;padding:1rem 0;"><div class="spinner-border spinner-border-sm"></div></div>';
    try {
      const r = await fetch('/api/ai/sessoes/' + id + '/mensagens');
      const d = await r.json();
      area.innerHTML = '';
      if (!d.mensagens || d.mensagens.length === 0) {
        area.innerHTML = '<div style="text-align:center;color:var(--mc-muted);font-size:.82rem;padding:2rem 0;">Nenhuma mensagem ainda.</div>';
        document.getElementById('augurSuggestions').style.display = 'flex';
        return;
      }
      document.getElementById('augurSuggestions').style.display = 'none';
      d.mensagens.forEach(m => _augurRenderMsg(m.role, m.content, m.id, m.hora, false));
      _augurScrollBottom();
    } catch(e) {
      area.innerHTML = '<div style="text-align:center;color:var(--mc-muted);font-size:.82rem;padding:2rem 0;">Erro ao carregar.</div>';
    }
  }

  // ── Nova conversa ──
  window.augurNovaConversa = function() {
    _sessaoAtual = null;
    document.getElementById('augurSessaoTitulo').textContent = '';
    document.getElementById('augurChatArea').innerHTML =
      '<div style="text-align:center;color:var(--mc-muted);font-size:.82rem;padding:2rem 0;">Nova conversa iniciada.</div>';
    document.getElementById('augurSuggestions').style.display = 'flex';
    document.getElementById('augurInput').value = '';
    document.getElementById('augurInput').focus();
    _augurAnexo = null;
    document.getElementById('augurAnexoPreview').style.display = 'none';
    document.querySelectorAll('.aug-sessao-item').forEach(el => el.classList.remove('ativa'));
  };

  // ── Renomear sessão ──
  async function augurRenomearSessao(id, tituloAtual, el) {
    const novo = prompt('Renomear conversa:', tituloAtual);
    if (!novo || novo.trim() === tituloAtual) return;
    try {
      const r = await fetch('/api/ai/sessoes/' + id + '/renomear', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({titulo: novo.trim()}),
      });
      const d = await r.json();
      if (d.ok) {
        el.querySelector('div').textContent = d.titulo;
        if (_sessaoAtual === id) {
          document.getElementById('augurSessaoTitulo').textContent = d.titulo;
        }
      }
    } catch(e) {}
  }

  // ── Envia mensagem ──
  window.augurSend = async function() {
    const input = document.getElementById('augurInput');
    const q = (input.value || '').trim();
    if (!q && !_augurAnexo) return;

    const btn = document.getElementById('augurBtn');
    btn.disabled = true;
    btn.textContent = '...';
    input.value = '';
    document.getElementById('augurSuggestions').style.display = 'none';

    const hora = new Date().toTimeString().slice(0,5);
    const displayQ = q + (_augurAnexo ? ` [📎 ${_augurAnexo.name}]` : '');
    _augurRenderMsg('user', displayQ, null, hora, true);
    _augurShowTyping();

    const payload = {
      question: q || '(Analise o arquivo anexado)',
      session_id: _sessaoAtual || 0,
    };
    if (_augurAnexo) payload.attachments = [_augurAnexo];

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

      if (d.session_id && !_sessaoAtual) {
        _sessaoAtual = d.session_id;
        document.getElementById('augurSessaoTitulo').textContent = d.session_titulo || '';
        augurCarregarSessoes(); // atualiza lista
      }

      if (d.precisa_creditos) {
        _augurRenderMsg('assistant', '💳 Saldo insuficiente. Adquira créditos em /planos.', null, hora, true);
      } else if (d.error || !d.response) {
        _augurRenderMsg('assistant', '⚠️ ' + (d.error || 'Erro ao processar.'), null, hora, true);
      } else {
        _augurRenderMsg('assistant', d.response, d.msg_id, hora, true);
      }
    } catch(e) {
      _augurHideTyping();
      _augurRenderMsg('assistant', '⚠️ Erro de conexão.', null, null, true);
    } finally {
      btn.disabled = false;
      btn.textContent = 'Enviar';
      input.focus();
    }
  };

  function _augurRenderMsg(role, content, msgId, hora, animate) {
    const area = document.getElementById('augurChatArea');
    const placeholder = area.querySelector('[data-placeholder]');
    if (placeholder) placeholder.remove();
    const wrap = document.createElement('div');
    wrap.className = 'aug-msg ' + role;
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
    wrap.innerHTML = avatarHtml + `<div><div class="aug-bubble ${role}">${_escapeHtml(content)}</div>${hora ? `<div class="aug-meta">${hora}</div>` : ''}${feedbackHtml}</div>`;
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
  function _escapeHtml(t) { return String(t).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }

  window.selecionarAnexo = async function(input) {
    const file = input.files[0];
    if (!file) return;
    if (file.size > 10*1024*1024) { alert('Arquivo muito grande. Máximo 10MB.'); return; }
    const ext = file.name.split('.').pop().toLowerCase();
    let tipo = '';
    if (ext==='pdf') tipo='pdf';
    else if (['png','jpg','jpeg','gif','webp'].includes(ext)) tipo='image/'+(ext==='jpg'?'jpeg':ext);
    else if (['csv','xlsx','xls'].includes(ext)) {
      const txt = await file.text();
      _augurAnexo = {type:'csv', data:txt.slice(0,50000), name:file.name};
      document.getElementById('augurAnexoNome').textContent = '📎 '+file.name;
      document.getElementById('augurAnexoPreview').style.display='block';
      return;
    } else { alert('Tipo não suportado.'); return; }
    const reader = new FileReader();
    reader.onload = function(e) {
      _augurAnexo = {type:tipo, data:e.target.result.split(',')[1], name:file.name};
      document.getElementById('augurAnexoNome').textContent = '📎 '+file.name;
      document.getElementById('augurAnexoPreview').style.display='block';
    };
    reader.readAsDataURL(file);
    input.value='';
  };

  window.removerAnexo = function() {
    _augurAnexo=null;
    document.getElementById('augurAnexoPreview').style.display='none';
    document.getElementById('augurFileInput').value='';
  };

  window.augurSetQ = function(q) {
    document.getElementById('augurInput').value=q;
    document.getElementById('augurInput').focus();
  };

  window.augurFeedback = async function(msgId, positive, btn) {
    try {
      await fetch('/api/ai/feedback/'+msgId, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({positive})});
      const wrap = btn.closest('.aug-feedback');
      if (wrap) wrap.innerHTML = positive
        ? '<span style="font-size:.75rem;color:#16a34a;">✅ Obrigado!</span>'
        : '<span style="font-size:.75rem;color:#dc2626;">Vamos melhorar!</span>';
    } catch(e) {}
  };

  augurCarregarSessoes();
})();
</script>

{# ── BASE DE CONHECIMENTO ── #}
<div class="card mb-3" id="baseConhecimentoCard" style="border:1px solid var(--mc-border);">
  <div class="card-body p-0">
    <div class="d-flex align-items-center gap-2 p-3" style="border-bottom:1px solid var(--mc-border);">
      <div style="font-size:1.1rem;">📚</div>
      <div style="flex:1;">
        <div class="fw-bold" style="font-size:.92rem;">Base de Conhecimento</div>
        <div class="muted" style="font-size:.7rem;">Documentos que o Augur usa para responder suas perguntas</div>
      </div>
      <button class="btn btn-sm btn-outline-primary" onclick="baseToggleForm()" style="font-size:.75rem;">
        + Adicionar
      </button>
    </div>

    {# Formulário de upload #}
    <div id="baseForm" style="display:none;padding:1rem;border-bottom:1px solid var(--mc-border);background:#f8fafc;">
      <div class="row g-2">
        <div class="col-md-6">
          <label class="form-label small fw-semibold">Nome do documento</label>
          <input type="text" id="baseNome" class="form-control form-control-sm" placeholder="Ex: Fluxo de Caixa Janeiro 2026">
        </div>
        <div class="col-md-6">
          <label class="form-label small fw-semibold">Descrição (opcional)</label>
          <input type="text" id="baseDescricao" class="form-control form-control-sm" placeholder="Ex: Planilha de entradas e saídas de janeiro">
        </div>
        <div class="col-12">
          <label class="form-label small fw-semibold">Arquivo (PDF, Excel, CSV, imagem)</label>
          <input type="file" id="baseArquivo" class="form-control form-control-sm"
                 accept=".pdf,.csv,.xlsx,.xls,.txt,.png,.jpg,.jpeg">
        </div>
        <div class="col-12 d-flex gap-2">
          <button class="btn btn-primary btn-sm" onclick="baseSalvar()">Salvar</button>
          <button class="btn btn-outline-secondary btn-sm" onclick="baseToggleForm()">Cancelar</button>
        </div>
        <div id="baseFeedback" class="col-12" style="display:none;"></div>
      </div>
    </div>

    {# Lista de documentos #}
    <div id="baseDocLista" style="padding:.75rem 1rem;max-height:200px;overflow-y:auto;">
      <div class="muted small">Carregando...</div>
    </div>
  </div>
</div>

<script>
(function(){
  async function baseCarregar() {
    try {
      const r = await fetch('/api/base-conhecimento');
      const d = await r.json();
      const lista = document.getElementById('baseDocLista');
      if (!d.docs || d.docs.length === 0) {
        lista.innerHTML = '<div class="muted small">Nenhum documento ainda. Adicione arquivos para o Augur usar.</div>';
        return;
      }
      lista.innerHTML = d.docs.map(doc => `
        <div class="d-flex align-items-center gap-2 py-2" style="border-bottom:1px solid var(--mc-border);">
          <div style="flex:1;">
            <div class="fw-semibold" style="font-size:.83rem;">${doc.nome}</div>
            ${doc.descricao ? `<div class="muted" style="font-size:.72rem;">${doc.descricao}</div>` : ''}
            <div class="muted" style="font-size:.68rem;">${doc.tipo} · ${doc.created_at}</div>
          </div>
          <button class="btn btn-sm btn-outline-danger" style="padding:.1rem .4rem;font-size:.7rem;"
                  onclick="baseDeletar(${doc.id}, this)">🗑️</button>
        </div>`).join('');
    } catch(e) {
      document.getElementById('baseDocLista').innerHTML = '<div class="muted small">Erro ao carregar.</div>';
    }
  }

  window.baseToggleForm = function() {
    const f = document.getElementById('baseForm');
    f.style.display = f.style.display === 'none' ? 'block' : 'none';
  };

  window.baseSalvar = async function() {
    const nome     = document.getElementById('baseNome').value.trim();
    const descricao = document.getElementById('baseDescricao').value.trim();
    const arquivo  = document.getElementById('baseArquivo').files[0];
    const fb       = document.getElementById('baseFeedback');

    if (!nome || !arquivo) {
      fb.style.display='block';
      fb.innerHTML='<div class="alert alert-warning alert-sm py-1 mb-0">Nome e arquivo são obrigatórios.</div>';
      return;
    }

    fb.style.display='block';
    fb.innerHTML='<div class="alert alert-info py-1 mb-0">Processando...</div>';

    try {
      let conteudo = '';
      let tipo = arquivo.name.split('.').pop().toLowerCase();

      if (['csv','txt'].includes(tipo)) {
        conteudo = await arquivo.text();
      } else if (['xlsx','xls'].includes(tipo)) {
        conteudo = await arquivo.text();
        tipo = 'excel';
      } else if (tipo === 'pdf') {
        const reader = new FileReader();
        conteudo = await new Promise(res => {
          reader.onload = e => res(e.target.result.split(',')[1]);
          reader.readAsDataURL(arquivo);
        });
        tipo = 'pdf_base64';
      } else {
        const reader = new FileReader();
        conteudo = await new Promise(res => {
          reader.onload = e => res(e.target.result.split(',')[1]);
          reader.readAsDataURL(arquivo);
        });
        tipo = 'imagem_base64';
      }

      const r = await fetch('/api/base-conhecimento/upload', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({nome, descricao, tipo, conteudo}),
      });
      const d = await r.json();

      if (d.ok) {
        fb.innerHTML='<div class="alert alert-success py-1 mb-0">✅ Documento salvo!</div>';
        document.getElementById('baseNome').value='';
        document.getElementById('baseDescricao').value='';
        document.getElementById('baseArquivo').value='';
        baseCarregar();
        setTimeout(() => { baseToggleForm(); fb.style.display='none'; }, 1500);
      } else {
        fb.innerHTML=`<div class="alert alert-danger py-1 mb-0">${d.erro || 'Erro ao salvar.'}</div>`;
      }
    } catch(e) {
      fb.innerHTML='<div class="alert alert-danger py-1 mb-0">Erro ao processar arquivo.</div>';
    }
  };

  window.baseDeletar = async function(id, btn) {
    if (!confirm('Remover este documento?')) return;
    try {
      await fetch('/api/base-conhecimento/' + id, {method:'DELETE'});
      baseCarregar();
    } catch(e) {}
  };

  baseCarregar();
})();
</script>
{% endif %}
{# ── /AUGUR WIDGET v4 ── #}
"""

# ── Substitui widget no dashboard ────────────────────────────────────────────
_dash_v4 = TEMPLATES.get("dashboard.html", "")
if _dash_v4:
    import re as _re_dashv4
    # Remove widget v3 e substitui por v4
    _dash_v4 = _re_dashv4.sub(
        r'\{#\s*── AUGUR WIDGET.*?── /AUGUR WIDGET.*?#\}',
        _AUGUR_WIDGET_V4.strip(),
        _dash_v4,
        flags=_re_dashv4.DOTALL,
    )
    if "augurCard" not in _dash_v4:
        if "Painel de Saúde Financeira" in _dash_v4:
            _dash_v4 = _dash_v4.replace(
                "Painel de Saúde Financeira",
                _AUGUR_WIDGET_V4.strip() + "\nPainel de Saúde Financeira", 1
            )
    TEMPLATES["dashboard.html"] = _dash_v4

if hasattr(templates_env.loader, "mapping"):
    templates_env.loader.mapping = TEMPLATES

print("[augur_v4] ✅ Sessões por usuário + Base de Conhecimento carregados")

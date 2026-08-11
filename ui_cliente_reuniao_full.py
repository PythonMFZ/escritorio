# ============================================================================
# ui_cliente_reuniao_full.py — Libera gravação, ações e atas para role=cliente
# ============================================================================
# Patches:
#   /api/reunioes/recentes         → inclui clientes (filtrando pelo client_id)
#   /reunioes/{id}/upload-audio    → libera clientes (verificando client_id)
#   /reunioes/{id}/acoes POST      → libera clientes (verificando client_id)
#   base.html                      → exibe gravador flutuante para clientes
#   meetings_detail.html           → adiciona bloco de notas + ações para clientes
# ============================================================================

from fastapi.responses import JSONResponse as _JSON_crf, RedirectResponse as _RR_crf
from fastapi import Request as _Req_crf, Depends as _Dep_crf, Form as _Form_crf, BackgroundTasks as _BG_crf
from sqlmodel import Session as _Sess_crf, select as _sel_crf

# ── 1. /api/reunioes/recentes — incluir clientes ─────────────────────────────

app.routes[:] = [r for r in app.routes
                 if not (hasattr(r, "path") and r.path == "/api/reunioes/recentes")]

@app.get("/api/reunioes/recentes")
@require_login
async def crf_reunioes_recentes(request: _Req_crf, session: _Sess_crf = _Dep_crf(get_session)):
    ctx = get_tenant_context(request, session)
    if not ctx:
        return _JSON_crf({"reunioes": []})

    if ctx.membership.role in ("admin", "equipe"):
        reunioes = session.exec(
            _sel_crf(Meeting)
            .where(Meeting.company_id == ctx.company.id)
            .order_by(Meeting.created_at.desc())
            .limit(30)
        ).all()
    elif ctx.membership.role == "cliente" and ctx.membership.client_id:
        reunioes = session.exec(
            _sel_crf(Meeting)
            .where(
                Meeting.company_id == ctx.company.id,
                Meeting.client_id == ctx.membership.client_id,
            )
            .order_by(Meeting.created_at.desc())
            .limit(20)
        ).all()
    else:
        return _JSON_crf({"reunioes": []})

    data = [
        {"id": m.id, "title": m.title or "", "meeting_date": m.meeting_date or ""}
        for m in reunioes
    ]
    return _JSON_crf({"reunioes": data})

print("[crf] ✅ /api/reunioes/recentes atualizado para clientes.")


# ── 2. /reunioes/{id}/upload-audio — liberar para clientes ──────────────────

try:
    import os as _os_crf
    import tempfile as _tmp_crf
    from pathlib import Path as _Path_crf

    _AUDIO_DIR_CRF = _Path_crf(
        _os_crf.environ.get("AUDIO_UPLOAD_DIR", "/tmp/reunioes")
    )
    try:
        _AUDIO_DIR_CRF.mkdir(parents=True, exist_ok=True)
    except Exception:
        _AUDIO_DIR_CRF = _Path_crf(_tmp_crf.mkdtemp(prefix="reunioes_"))

    app.routes[:] = [r for r in app.routes
                     if not (hasattr(r, "path") and r.path == "/reunioes/{meeting_id}/upload-audio")]

    @app.post("/reunioes/{meeting_id}/upload-audio")
    @require_login
    async def crf_upload_audio(
        meeting_id: int,
        request: _Req_crf,
        background_tasks: _BG_crf,
        session: _Sess_crf = _Dep_crf(get_session),
    ):
        from fastapi.responses import JSONResponse as _JR
        ctx = get_tenant_context(request, session)
        if not ctx:
            return _JR({"ok": False, "erro": "Não autenticado."}, status_code=401)

        mt = session.get(Meeting, meeting_id)
        if not mt or mt.company_id != ctx.company.id:
            return _JR({"ok": False, "erro": "Reunião não encontrada."}, status_code=404)

        # Verifica permissão: admin/equipe podem tudo; cliente só no próprio client_id
        if ctx.membership.role not in ("admin", "equipe"):
            if ctx.membership.role != "cliente" or ctx.membership.client_id != mt.client_id:
                return _JR({"ok": False, "erro": "Sem permissão para esta reunião."}, status_code=403)

        form = await request.form()
        audio_file = form.get("audio")
        if not audio_file or not hasattr(audio_file, "filename"):
            return _JR({"ok": False, "erro": "Nenhum arquivo enviado."})

        filename = audio_file.filename or "audio"
        ext = filename.rsplit(".", 1)[-1].lower()
        if ext not in ("mp3", "m4a", "wav", "ogg", "webm", "mp4"):
            return _JR({"ok": False, "erro": f"Formato .{ext} não suportado."})

        # Salva temporariamente
        save_path = _AUDIO_DIR_CRF / f"meeting_{meeting_id}_{ctx.user.id}.{ext}"
        try:
            content = await audio_file.read()
            with open(save_path, "wb") as f:
                f.write(content)
        except Exception as e:
            return _JR({"ok": False, "erro": f"Erro ao salvar arquivo: {e}"})

        # Dispara transcrição em background (reutiliza função do whisper module)
        try:
            background_tasks.add_task(
                _processar_audio_background,
                meeting_id=meeting_id,
                audio_path=str(save_path),
                company_id=ctx.company.id,
            )
            return _JR({"ok": True, "msg": "Áudio recebido. Transcrevendo em segundo plano — atualize a página em alguns minutos."})
        except Exception as e:
            return _JR({"ok": False, "erro": f"Erro ao enfileirar transcrição: {e}"})

    print("[crf] ✅ /reunioes/{id}/upload-audio liberado para clientes.")

except Exception as _e_crf_upload:
    print(f"[crf] ⚠️ upload-audio: {_e_crf_upload}")


# ── 3. POST /reunioes/{id}/acoes — liberar para clientes ────────────────────

try:
    app.routes[:] = [r for r in app.routes
                     if not (hasattr(r, "path") and r.path == "/reunioes/{meeting_id}/acoes"
                             and hasattr(r, "methods") and "POST" in (r.methods or set()))]

    @app.post("/reunioes/{meeting_id}/acoes")
    @require_login
    async def crf_acoes_post(
        request: _Req_crf,
        session: _Sess_crf = _Dep_crf(get_session),
        meeting_id: int = 0,
        titulo: str = _Form_crf(""),
        descricao: str = _Form_crf(""),
        responsavel: str = _Form_crf(""),
        prazo: str = _Form_crf(""),
        prioridade: str = _Form_crf("media"),
    ):
        ctx = get_tenant_context(request, session)
        if not ctx:
            return _RR_crf("/login", status_code=303)

        mt = session.get(Meeting, meeting_id)
        if not mt or mt.company_id != ctx.company.id:
            set_flash(request, "Reunião não encontrada.")
            return _RR_crf("/cliente/reunioes", status_code=303)

        # Clientes só podem criar ações nas reuniões do próprio client_id
        if ctx.membership.role not in ("admin", "equipe"):
            if ctx.membership.role != "cliente" or ctx.membership.client_id != mt.client_id:
                set_flash(request, "Sem permissão.")
                return _RR_crf("/cliente/reunioes", status_code=303)

        if not titulo.strip():
            set_flash(request, "Informe um título para a ação.")
            return _RR_crf(f"/reunioes/{meeting_id}/acoes", status_code=303)

        try:
            acao = MeetingAcao(
                company_id=ctx.company.id,
                client_id=mt.client_id,
                meeting_id=meeting_id,
                titulo=titulo.strip(),
                descricao=descricao.strip(),
                responsavel=responsavel.strip(),
                prazo=prazo.strip() or None,
                prazo_previsto=prazo.strip() or None,
                prioridade=prioridade if prioridade in ("alta", "media", "baixa") else "media",
                status="aberta",
                created_by_user_id=ctx.user.id,
            )
            session.add(acao)
            session.commit()
            set_flash(request, f"✅ Ação '{titulo}' criada.")
        except Exception as e:
            print(f"[crf] ⚠️ criar ação: {e}")
            set_flash(request, "Erro ao criar ação.")

        return _RR_crf(f"/reunioes/{meeting_id}/acoes", status_code=303)

    print("[crf] ✅ POST /reunioes/{id}/acoes liberado para clientes.")

except Exception as _e_crf_acao:
    print(f"[crf] ⚠️ acoes post: {_e_crf_acao}")


# ── 4. Gravador flutuante: exibir para clientes no base.html ─────────────────

try:
    _base_crf = TEMPLATES.get("base.html", "")
    # O bloco injetado pelo floating_recorder usa: {% if role in ['admin','equipe'] %}
    if "role in ['admin','equipe']" in _base_crf and "frec-btn" in _base_crf:
        _base_crf = _base_crf.replace(
            "{% if role in ['admin','equipe'] %}\n",
            "{% if role in ['admin','equipe','cliente'] %}\n",
            1,
        )
        TEMPLATES["base.html"] = _base_crf
        if hasattr(templates_env.loader, "mapping"):
            templates_env.loader.mapping["base.html"] = _base_crf
        print("[crf] ✅ Gravador flutuante estendido para role=cliente.")
    else:
        print("[crf] ℹ️ Condição do gravador já correta ou base não encontrado.")
except Exception as _e_crf_rec:
    print(f"[crf] ⚠️ gravador: {_e_crf_rec}")


# ── 5. meetings_detail.html: adicionar bloco de notas e ações para clientes ──

_CLIENTE_BLOCK = r"""
  {# ── Bloco exclusivo do cliente (notas + acoes) ── #}
  {% if role == "cliente" %}
  <div class="card p-3 mb-3">
    <h6 class="mb-2">📝 Minhas Anotações</h6>
    <form method="post" action="/reunioes/{{ meeting.id }}/notas-cliente">
      <textarea class="form-control" name="notes_text" rows="4"
                placeholder="Anote aqui suas observações sobre esta reunião…">{{ meeting.notes_text or "" }}</textarea>
      <div class="mt-2">
        <button class="btn btn-primary btn-sm">Salvar Anotações</button>
      </div>
    </form>
  </div>

  <div class="d-flex gap-2 flex-wrap mb-3">
    <a class="btn btn-outline-warning btn-sm" href="/reunioes/{{ meeting.id }}/acoes">
      ⚡ Ações desta Reunião
    </a>
    <a class="btn btn-outline-info btn-sm" href="/reunioes/{{ meeting.id }}/pauta">
      📋 Pauta
    </a>
    <a class="btn btn-outline-secondary btn-sm" href="/cliente/reunioes">
      ← Voltar
    </a>
  </div>
  {% endif %}
"""

try:
    _det = TEMPLATES.get("meetings_detail.html", "")
    if _det and "notas-cliente" not in _det:
        # Injeta antes do bloco de resumo/action items
        _marker_det = '<div class="row g-3">\n    <div class="col-lg-6">\n      <div class="card p-3 h-100">\n        <h6>Resumo</h6>'
        if _marker_det in _det:
            _det = _det.replace(_marker_det, _CLIENTE_BLOCK + "\n  " + _marker_det, 1)

            # Também garante que o botão "Voltar" para clientes vai para /cliente/reunioes
            _det = _det.replace(
                '<a class="btn btn-outline-secondary" href="/reunioes">Voltar</a>',
                '{% if role == "cliente" %}<a class="btn btn-outline-secondary" href="/cliente/reunioes">Voltar</a>{% else %}<a class="btn btn-outline-secondary" href="/reunioes">Voltar</a>{% endif %}',
                1,
            )

            TEMPLATES["meetings_detail.html"] = _det
            if hasattr(templates_env.loader, "mapping"):
                templates_env.loader.mapping["meetings_detail.html"] = _det
            print("[crf] ✅ Bloco de cliente injetado em meetings_detail.html.")
        else:
            print("[crf] ⚠️ Marcador de resumo não encontrado em meetings_detail.html.")
    elif "notas-cliente" in _det:
        print("[crf] ℹ️ Bloco do cliente já presente.")
    else:
        print("[crf] ⚠️ meetings_detail.html não encontrado.")
except Exception as _e_crf_det:
    print(f"[crf] ⚠️ detail patch: {_e_crf_det}")


# ── 6. POST /reunioes/{id}/notas-cliente — salvar notas do cliente ────────────

from fastapi.responses import RedirectResponse as _RR2_crf

@app.post("/reunioes/{meeting_id}/notas-cliente")
@require_login
async def crf_notas_cliente(
    request: _Req_crf,
    session: _Sess_crf = _Dep_crf(get_session),
    meeting_id: int = 0,
    notes_text: str = _Form_crf(""),
):
    ctx = get_tenant_context(request, session)
    if not ctx:
        return _RR2_crf("/login", status_code=303)

    mt = session.get(Meeting, meeting_id)
    if not mt or mt.company_id != ctx.company.id:
        return _RR2_crf("/cliente/reunioes", status_code=303)

    # Clientes só editam notas de reuniões do próprio client_id
    if ctx.membership.role not in ("admin", "equipe"):
        if ctx.membership.role != "cliente" or ctx.membership.client_id != mt.client_id:
            set_flash(request, "Sem permissão.")
            return _RR2_crf("/cliente/reunioes", status_code=303)

    try:
        mt.notes_text = notes_text.strip()
        session.add(mt)
        session.commit()
        set_flash(request, "✅ Anotações salvas.")
    except Exception as e:
        print(f"[crf] ⚠️ notas-cliente: {e}")
        set_flash(request, "Erro ao salvar anotações.")

    return _RR2_crf(f"/reunioes/{meeting_id}", status_code=303)


# ── 7. Exibir transcrição e resumo para clientes em meetings_detail ───────────

try:
    _det2 = TEMPLATES.get("meetings_detail.html", "")
    # Torna o bloco de resumo/ata visível para clientes (atualmente pode estar
    # sem restrição — verificamos se o conteúdo já aparece para clientes)
    # O template existente tem <div class="row g-3"> com resumo e action items
    # sem restrição de role — então já aparece para todos. Nada a fazer aqui.
    if _det2:
        print("[crf] ℹ️ Resumo/ata já visível para todos os roles (sem patch necessário).")
except Exception:
    pass

print("[crf] ✅ Módulo cliente reunião full carregado.")

# ============================================================================
# PATCH — Transcrição de Áudio com Whisper + Resumo IA nas Reuniões
# ============================================================================
# Salve como ui_reunioes_whisper.py e adicione ao final do app.py:
#   exec(open('ui_reunioes_whisper.py').read())
#
# PRÉ-REQUISITOS:
#   pip install openai-whisper
#   Render Disk montado em /var/data (ou /opt/render/project/src/uploads)
#
# O QUE FAZ:
#   1. Upload de áudio na tela da reunião (MP3/M4A/WAV/OGG até 500MB)
#   2. Whisper "small" transcreve em background (não trava a interface)
#   3. Claude gera resumo estruturado: contexto, pontos, decisões, ações
#   4. Transcrição + resumo salvos nos campos existentes do Meeting
#   5. Áudio deletado após transcrição (economiza disco)
#   6. Augur lê reuniões nativas em vez do Notion
# ============================================================================

import os as _os2
import json as _json_w
import shutil as _shutil
import tempfile as _tmpfile
from pathlib import Path as _Path
from datetime import datetime as _dt_w
from fastapi import BackgroundTasks as _BG

# ── Configuração de paths ─────────────────────────────────────────────────────

# Render Disk monta em /var/data por padrão
# Se não existir, usa pasta local
_AUDIO_DIR = _Path(
    _os2.environ.get("AUDIO_UPLOAD_DIR", "/var/data/reunioes")
)
try:
    _AUDIO_DIR.mkdir(parents=True, exist_ok=True)
except Exception:
    _AUDIO_DIR = _Path("uploads/reunioes")
    _AUDIO_DIR.mkdir(parents=True, exist_ok=True)

_WHISPER_MODEL_NAME = _os2.environ.get("WHISPER_MODEL", "tiny")
_whisper_model_cache = {}  # cache do modelo carregado


def _get_whisper_model():
    """Carrega o modelo Whisper uma vez e reutiliza."""
    if _WHISPER_MODEL_NAME not in _whisper_model_cache:
        try:
            import whisper as _whisper
            print(f"[whisper] Carregando modelo '{_WHISPER_MODEL_NAME}'...")
            _whisper_model_cache[_WHISPER_MODEL_NAME] = _whisper.load_model(_WHISPER_MODEL_NAME)
            print(f"[whisper] Modelo '{_WHISPER_MODEL_NAME}' carregado.")
        except ImportError:
            print("[whisper] openai-whisper não instalado. Adicione ao requirements.txt")
            return None
    return _whisper_model_cache.get(_WHISPER_MODEL_NAME)


def _gerar_resumo_ia(transcricao: str, titulo: str) -> dict:
    """Usa Claude para gerar resumo estruturado da transcrição."""
    import requests as _req_w
    api_key = _os2.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key or not transcricao:
        return {"summary": "", "action_items": "", "notes": ""}

    prompt = f"""Você é um assistente especializado em reuniões de consultoria financeira.

Analise a transcrição da reunião "{titulo}" e gere um relatório estruturado.

IMPORTANTE: Responda APENAS com JSON válido, sem texto antes ou depois. Todos os valores devem ser strings simples (não listas nem objetos aninhados).

Transcrição:
{transcricao[:8000]}

Responda exatamente neste formato JSON:
{{
  "summary": "Resumo executivo em 3-5 parágrafos sobre o que foi discutido, contexto da empresa e principais pontos.",
  "action_items": "Lista de próximas ações em texto simples, uma por linha, com responsável quando mencionado.",
  "notes": "Decisões tomadas e pontos de atenção em texto simples."
}}"""

    try:
        resp = _req_w.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": "claude-sonnet-4-6",
                "max_tokens": 2000,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=60,
        )
        resp.raise_for_status()
        texto = resp.json()["content"][0]["text"]

        # Tenta parsear JSON
        import re as _re_w
        json_match = _re_w.search(r'\{.*\}', texto, _re_w.DOTALL)
        if json_match:
            dados = _json_w.loads(json_match.group())
            return {
                "summary":          dados.get("summary", ""),
                "action_items":     dados.get("action_items", ""),
                "notes":            f"Decisões: {dados.get('decisions','')}\n\nAtenção: {dados.get('attention_points','')}",
            }
    except Exception as e:
        print(f"[whisper] Erro ao gerar resumo IA: {e}")

    return {"summary": "", "action_items": "", "notes": ""}


def _processar_audio_background(
    meeting_id: int,
    audio_path: str,
    company_id: int,
):
    """
    Background task: roda o Whisper em subprocess separado para não
    consumir RAM/CPU do processo principal do Gunicorn.
    """
    import subprocess as _sp
    import sys as _sys_w

    print(f"[whisper] Iniciando transcrição da reunião {meeting_id} em subprocess...")

    from sqlmodel import Session as _SessW
    with _SessW(engine) as _sess:
        mt = _sess.get(Meeting, meeting_id)
        if not mt:
            return

        mt.notion_status = "transcription_in_progress"
        mt.updated_at = _dt_w.utcnow()
        _sess.add(mt); _sess.commit()

    # Script Python que roda em processo separado
    script = f"""
import sys, os, json
sys.path.insert(0, '{_os2.path.dirname(_os2.path.abspath(__file__))}')
os.environ.update(dict(os.environ))

try:
    import whisper
    model = whisper.load_model('{_WHISPER_MODEL_NAME}')
    result = model.transcribe('{audio_path}', language='pt', verbose=False)
    transcricao = result.get('text', '').strip()
    print(json.dumps({{'ok': True, 'text': transcricao}}))
except Exception as e:
    print(json.dumps({{'ok': False, 'error': str(e)}}))
"""

    try:
        # Roda Whisper em processo filho com limite de memória
        proc = _sp.run(
            [_sys_w.executable, '-c', script],
            capture_output=True,
            text=True,
            timeout=5400,  # 90 minutos máximo para reuniões longas
        )

        resultado = {}
        for line in proc.stdout.strip().splitlines():
            line = line.strip()
            if line.startswith('{'):
                try:
                    resultado = __import__('json').loads(line)
                    break
                except Exception:
                    pass

        transcricao = resultado.get('text', '') if resultado.get('ok') else ''

        if proc.returncode != 0 and not transcricao:
            erro = proc.stderr[:300] if proc.stderr else 'Erro desconhecido'
            print(f"[whisper] Erro subprocess: {erro}")
            with _SessW(engine) as _s:
                _mt = _s.get(Meeting, meeting_id)
                if _mt:
                    _mt.notion_status = "error"
                    _mt.notes_text = f"Erro na transcrição: {erro[:200]}"
                    _s.add(_mt); _s.commit()
            return

        print(f"[whisper] Transcrição concluída: {len(transcricao)} chars")

        # Atualiza banco com transcrição
        with _SessW(engine) as _s:
            _mt = _s.get(Meeting, meeting_id)
            if _mt:
                _mt.transcript_text = transcricao
                _mt.notion_status = "summary_in_progress"
                _s.add(_mt); _s.commit()

        # Gera resumo com Claude (no processo principal — leve)
        if transcricao:
            with _SessW(engine) as _s:
                _mt = _s.get(Meeting, meeting_id)
                if _mt:
                    resumo = _gerar_resumo_ia(transcricao, _mt.title)
                    # Garante que todos os campos são strings
                    def _to_str(v):
                        if isinstance(v, (list, dict)):
                            return _json_w.dumps(v, ensure_ascii=False, indent=2)
                        return str(v or "")
                    _mt.summary_text      = _to_str(resumo.get("summary", ""))
                    _mt.action_items_text = _to_str(resumo.get("action_items", ""))
                    _mt.notes_text        = _to_str(resumo.get("notes", ""))
                    _mt.notion_status     = "notes_ready"
                    _mt.last_synced_at    = _dt_w.utcnow()
                    _mt.updated_at        = _dt_w.utcnow()
                    _s.add(_mt); _s.commit()
                    print(f"[whisper] Reunião {meeting_id} processada com sucesso.")

    except _sp.TimeoutExpired:
        print(f"[whisper] Timeout na transcrição da reunião {meeting_id}")
        with _SessW(engine) as _s:
            _mt = _s.get(Meeting, meeting_id)
            if _mt:
                _mt.notion_status = "error"
                _mt.notes_text = "Tempo limite excedido. Tente um arquivo menor."
                _s.add(_mt); _s.commit()
    except Exception as e:
        print(f"[whisper] Erro inesperado: {e}")
        with _SessW(engine) as _s:
            _mt = _s.get(Meeting, meeting_id)
            if _mt:
                _mt.notion_status = "error"
                _mt.notes_text = f"Erro: {str(e)[:200]}"
                _s.add(_mt); _s.commit()
    finally:
        try:
            _Path(audio_path).unlink(missing_ok=True)
            print(f"[whisper] Áudio deletado: {audio_path}")
        except Exception:
            pass


# ── Rota POST /reunioes/{id}/upload-audio ─────────────────────────────────────

@app.post("/reunioes/{meeting_id}/upload-audio")
@require_login
async def reuniao_upload_audio(
    meeting_id: int,
    request: Request,
    background_tasks: _BG,
    session: Session = Depends(get_session),
):
    ctx = get_tenant_context(request, session)
    if not ctx or ctx.membership.role not in ("admin", "equipe"):
        return JSONResponse({"ok": False, "erro": "Sem permissão."}, status_code=403)

    mt = session.get(Meeting, meeting_id)
    if not mt or mt.company_id != ctx.company.id:
        return JSONResponse({"ok": False, "erro": "Reunião não encontrada."}, status_code=404)

    # Lê o arquivo do form
    form = await request.form()
    audio_file = form.get("audio")
    if not audio_file or not hasattr(audio_file, "filename"):
        return JSONResponse({"ok": False, "erro": "Nenhum arquivo enviado."})

    filename = audio_file.filename or "audio"
    ext = filename.rsplit(".", 1)[-1].lower()
    if ext not in ("mp3", "m4a", "wav", "ogg", "webm", "mp4"):
        return JSONResponse({"ok": False, "erro": f"Formato .{ext} não suportado. Use MP3, M4A, WAV ou OGG."})

    # Salva em disco
    audio_path = _AUDIO_DIR / f"meeting_{meeting_id}_{_dt_w.utcnow().strftime('%Y%m%d_%H%M%S')}.{ext}"
    try:
        content = await audio_file.read()
        if len(content) > 500 * 1024 * 1024:  # 500MB
            return JSONResponse({"ok": False, "erro": "Arquivo muito grande (máx. 500MB)."})
        with open(audio_path, "wb") as f:
            f.write(content)
    except Exception as e:
        return JSONResponse({"ok": False, "erro": f"Erro ao salvar arquivo: {e}"})

    # Atualiza status
    mt.notion_status = "transcription_not_started"
    mt.source = "whisper"
    mt.updated_at = _dt_w.utcnow()
    session.add(mt)
    session.commit()

    # Inicia processamento em background
    background_tasks.add_task(
        _processar_audio_background,
        meeting_id=meeting_id,
        audio_path=str(audio_path),
        company_id=ctx.company.id,
    )

    return JSONResponse({
        "ok": True,
        "msg": f"Áudio recebido ({len(content)/1024/1024:.1f}MB). Transcrição iniciada em background — atualize a página em alguns minutos.",
    })


# ── Rota GET /reunioes/{id}/status ────────────────────────────────────────────

@app.get("/reunioes/{meeting_id}/status")
@require_login
async def reuniao_status(
    meeting_id: int,
    request: Request,
    session: Session = Depends(get_session),
):
    ctx = get_tenant_context(request, session)
    if not ctx:
        return JSONResponse({"status": "error"})

    mt = session.get(Meeting, meeting_id)
    if not mt or mt.company_id != ctx.company.id:
        return JSONResponse({"status": "not_found"})

    status_labels = {
        "transcription_not_started": "Na fila...",
        "transcription_in_progress": "Transcrevendo áudio...",
        "summary_in_progress":       "Gerando resumo com IA...",
        "notes_ready":               "Pronto!",
        "error":                     "Erro no processamento",
        "":                          "Aguardando",
    }

    return JSONResponse({
        "status":        mt.notion_status,
        "label":         status_labels.get(mt.notion_status, mt.notion_status),
        "has_summary":   bool(mt.summary_text),
        "has_transcript": bool(mt.transcript_text),
        "summary":       mt.summary_text[:500] if mt.summary_text else "",
        "action_items":  mt.action_items_text[:300] if mt.action_items_text else "",
    })


# ── Rota POST /reunioes/{id}/resumo-manual ────────────────────────────────────

@app.post("/reunioes/{meeting_id}/resumo-manual")
@require_login
async def reuniao_resumo_manual(
    meeting_id: int,
    request: Request,
    background_tasks: _BG,
    session: Session = Depends(get_session),
):
    """Gera resumo IA a partir de transcrição já existente."""
    ctx = get_tenant_context(request, session)
    if not ctx or ctx.membership.role not in ("admin", "equipe"):
        return JSONResponse({"ok": False}, status_code=403)

    mt = session.get(Meeting, meeting_id)
    if not mt or mt.company_id != ctx.company.id:
        return JSONResponse({"ok": False}, status_code=404)

    if not mt.transcript_text:
        return JSONResponse({"ok": False, "erro": "Sem transcrição para resumir."})

    def _gerar_bg():
        from sqlmodel import Session as _SW2
        with _SW2(engine) as _s:
            _mt = _s.get(Meeting, meeting_id)
            if _mt:
                _mt.notion_status = "summary_in_progress"
                _s.add(_mt); _s.commit()
                resumo = _gerar_resumo_ia(_mt.transcript_text, _mt.title)
                _mt.summary_text      = resumo.get("summary", "")
                _mt.action_items_text = resumo.get("action_items", "")
                _mt.notes_text        = resumo.get("notes", "")
                _mt.notion_status     = "notes_ready"
                _mt.updated_at        = _dt_w.utcnow()
                _s.add(_mt); _s.commit()

    background_tasks.add_task(_gerar_bg)
    return JSONResponse({"ok": True, "msg": "Resumo sendo gerado..."})


# ── Atualiza Augur para ler reuniões nativas ──────────────────────────────────

def _get_reunioes_nativas(session, company_id: int, client_id: int, limit: int = 5) -> list:
    """Busca reuniões do banco (nativas) para o Augur."""
    try:
        reunioes = session.exec(
            select(Meeting)
            .where(
                Meeting.company_id == company_id,
                Meeting.client_id  == client_id,
                Meeting.notion_status == "notes_ready",
            )
            .order_by(Meeting.created_at.desc())
            .limit(limit)
        ).all()

        return [
            {
                "titulo":  mt.title,
                "data":    mt.meeting_date or str(mt.created_at)[:10],
                "resumo":  mt.summary_text[:600] if mt.summary_text else mt.notes_text[:600],
                "acoes":   mt.action_items_text[:300] if mt.action_items_text else "",
            }
            for mt in reunioes
            if mt.summary_text or mt.notes_text
        ]
    except Exception as e:
        print(f"[reunioes] Erro ao buscar reuniões nativas: {e}")
        return []


# Injeta no contexto do Augur — sobrescreve a busca do Notion
# O patch do Augur já chama _get_reunioes_cliente — registramos uma versão
# que combina nativas + Notion como fallback

_orig_enriquecer = None
try:
    _orig_enriquecer = _enriquecer_client_data
except NameError:
    pass

def _enriquecer_client_data_v2(session, company_id, client_id, client, client_data):
    """Versão estendida: adiciona reuniões nativas ao contexto do Augur."""
    # Chama a original se existir
    if _orig_enriquecer:
        client_data = _orig_enriquecer(session, company_id, client_id, client, client_data)
    
    # Substitui/complementa reuniões com as nativas
    reunioes_nativas = _get_reunioes_nativas(session, company_id, client_id)
    
    if reunioes_nativas:
        # Prioriza nativas, depois mantém as do Notion como complemento
        reunioes_notion = client_data.get("reunioes_recentes", [])
        client_data["reunioes_recentes"] = (reunioes_nativas + reunioes_notion)[:5]
    
    return client_data

# Substitui a função no escopo global
_enriquecer_client_data = _enriquecer_client_data_v2


# ── Injeta botão de upload na tela de detalhe da reunião ─────────────────────

_WHISPER_PANEL = r"""
<div class="card p-3 mb-3" id="whisperPanel">
  <div class="d-flex justify-content-between align-items-center flex-wrap gap-2 mb-2">
    <div>
      <h6 class="mb-0">🎙️ Transcrição de Áudio</h6>
      <div class="muted small">Grave a reunião diretamente ou faça upload de um arquivo.</div>
    </div>
    {% if meeting.notion_status %}
    <div id="whisperStatus" class="badge
      {% if meeting.notion_status == 'notes_ready' %}text-bg-success
      {% elif meeting.notion_status == 'error' %}text-bg-danger
      {% elif meeting.notion_status %}text-bg-warning
      {% endif %}">
      {% if meeting.notion_status == 'notes_ready' %}✅ Transcrição pronta
      {% elif meeting.notion_status == 'transcription_in_progress' %}⏳ Transcrevendo...
      {% elif meeting.notion_status == 'summary_in_progress' %}🤖 Gerando resumo...
      {% elif meeting.notion_status == 'error' %}❌ Erro
      {% else %}⏳ Processando...
      {% endif %}
    </div>
    {% endif %}
  </div>

  {% if meeting.notion_status not in ['notes_ready', 'transcription_in_progress', 'summary_in_progress'] %}
  <div class="d-flex gap-2 align-items-center flex-wrap mb-2">

    {# Botão de gravação nativa #}
    <button id="btnGravar" class="btn btn-danger btn-sm" onclick="iniciarGravacao()">
      <i class="bi bi-record-circle me-1"></i>Iniciar Gravação
    </button>
    <button id="btnParar" class="btn btn-warning btn-sm" onclick="pararGravacao()" style="display:none;">
      <i class="bi bi-stop-circle me-1"></i>Parar e Transcrever
    </button>

    {# Divisor #}
    <span class="text-muted small">ou</span>

    {# Upload de arquivo #}
    <input type="file" id="audioFileInput" accept=".mp3,.m4a,.wav,.ogg,.webm,.mp4" style="display:none;"
           onchange="uploadAudio(this)">
    <button class="btn btn-outline-secondary btn-sm" onclick="document.getElementById('audioFileInput').click()">
      <i class="bi bi-upload me-1"></i>Upload de arquivo
    </button>
    <span class="muted small">MP3, M4A, WAV · Máx. 500MB</span>
  </div>

  {# Timer de gravação #}
  <div id="gravarInfo" style="display:none;" class="alert alert-danger mb-2 py-2" style="font-size:.85rem;">
    <div class="d-flex align-items-center gap-2">
      <span class="text-danger" style="font-size:1rem;">●</span>
      <span>Gravando: <strong id="gravarTimer">00:00</strong></span>
      <span class="muted small ms-2" id="gravarStatus">Microfone ativo...</span>
    </div>
  </div>
  {% endif %}

  {% if meeting.notion_status in ['transcription_in_progress', 'summary_in_progress', 'transcription_not_started'] %}
  <div class="alert alert-info mb-0" style="font-size:.85rem;">
    <div class="spinner-border spinner-border-sm me-2" role="status"></div>
    Processando em background — atualizando automaticamente...
  </div>
  {% endif %}

  {% if meeting.summary_text %}
  <hr class="my-2">
  <div class="mb-2">
    <div class="fw-semibold small mb-1">📋 Resumo</div>
    <div style="font-size:.85rem;white-space:pre-wrap;">{{ meeting.summary_text }}</div>
  </div>
  {% endif %}

  {% if meeting.action_items_text %}
  <div class="mb-2">
    <div class="fw-semibold small mb-1">✅ Ações</div>
    <div style="font-size:.85rem;white-space:pre-wrap;">{{ meeting.action_items_text }}</div>
  </div>
  {% endif %}

  {% if meeting.transcript_text %}
  <details class="mt-2">
    <summary class="muted small" style="cursor:pointer;">Ver transcrição completa</summary>
    <div style="font-size:.78rem;white-space:pre-wrap;max-height:300px;overflow-y:auto;margin-top:.5rem;background:#f9fafb;padding:.75rem;border-radius:8px;">{{ meeting.transcript_text }}</div>
    {% if not meeting.summary_text %}
    <button class="btn btn-sm btn-outline-primary mt-2" onclick="gerarResumo()">
      🤖 Gerar resumo com IA
    </button>
    {% endif %}
  </details>
  {% endif %}

  <div id="uploadFeedback" class="mt-2" style="display:none;"></div>
</div>

<script>
// ── Gravação nativa via MediaRecorder ────────────────────────────────────────
let _mediaRecorder = null;
let _audioChunks   = [];
let _timerInterval = null;
let _segundos      = 0;

async function iniciarGravacao() {
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    _audioChunks = [];
    _segundos = 0;

    // Tenta webm primeiro, fallback para outros formatos
    const mimeType = MediaRecorder.isTypeSupported('audio/webm;codecs=opus')
      ? 'audio/webm;codecs=opus'
      : MediaRecorder.isTypeSupported('audio/webm')
        ? 'audio/webm'
        : 'audio/ogg';

    _mediaRecorder = new MediaRecorder(stream, { mimeType });
    _mediaRecorder.ondataavailable = e => { if (e.data.size > 0) _audioChunks.push(e.data); };
    _mediaRecorder.onstop = () => enviarGravacao(mimeType);
    _mediaRecorder.start(1000); // coleta chunks a cada 1s

    // UI
    document.getElementById('btnGravar').style.display = 'none';
    document.getElementById('btnParar').style.display  = 'inline-flex';
    document.getElementById('gravarInfo').style.display = 'block';

    // Timer
    _timerInterval = setInterval(() => {
      _segundos++;
      const m = String(Math.floor(_segundos/60)).padStart(2,'0');
      const s = String(_segundos%60).padStart(2,'0');
      document.getElementById('gravarTimer').textContent = m+':'+s;
    }, 1000);

  } catch(e) {
    alert('Não foi possível acessar o microfone: ' + e.message + '\n\nVerifique as permissões do navegador.');
  }
}

function pararGravacao() {
  if (_mediaRecorder && _mediaRecorder.state !== 'inactive') {
    _mediaRecorder.stop();
    _mediaRecorder.stream.getTracks().forEach(t => t.stop());
  }
  clearInterval(_timerInterval);
  document.getElementById('btnParar').style.display  = 'none';
  document.getElementById('gravarInfo').style.display = 'none';
  document.getElementById('gravarStatus').textContent = 'Enviando...';
}

async function enviarGravacao(mimeType) {
  const ext = mimeType.includes('ogg') ? 'ogg' : 'webm';
  const blob = new Blob(_audioChunks, { type: mimeType });
  const fb   = document.getElementById('uploadFeedback');
  fb.style.display = 'block';
  fb.innerHTML = '<div class="alert alert-info"><div class="spinner-border spinner-border-sm me-2"></div>Enviando gravação (' + (blob.size/1024/1024).toFixed(1) + 'MB)...</div>';

  const fd = new FormData();
  fd.append('audio', blob, 'gravacao.' + ext);

  try {
    const r = await fetch('/reunioes/{{ meeting.id }}/upload-audio', { method:'POST', body: fd });
    const d = await r.json();
    if (d.ok) {
      fb.innerHTML = '<div class="alert alert-success">✅ ' + d.msg + '</div>';
      setTimeout(() => location.reload(), 3000);
    } else {
      fb.innerHTML = '<div class="alert alert-danger">❌ ' + (d.erro || 'Erro ao enviar.') + '</div>';
      document.getElementById('btnGravar').style.display = 'inline-flex';
    }
  } catch(e) {
    fb.innerHTML = '<div class="alert alert-danger">❌ Erro de conexão. Tente novamente.</div>';
    document.getElementById('btnGravar').style.display = 'inline-flex';
  }
}

// ── Upload de arquivo ────────────────────────────────────────────────────────
async function uploadAudio(input) {
  const file = input.files[0];
  if (!file) return;
  const fb = document.getElementById('uploadFeedback');
  fb.style.display = 'block';
  fb.innerHTML = '<div class="alert alert-info"><div class="spinner-border spinner-border-sm me-2"></div>Enviando ' + file.name + ' (' + (file.size/1024/1024).toFixed(1) + 'MB)...</div>';
  const fd = new FormData();
  fd.append('audio', file);
  const r = await fetch('/reunioes/{{ meeting.id }}/upload-audio', {method:'POST', body: fd});
  const d = await r.json();
  if (d.ok) {
    fb.innerHTML = '<div class="alert alert-success">✅ ' + d.msg + '</div>';
    setTimeout(() => location.reload(), 3000);
  } else {
    fb.innerHTML = '<div class="alert alert-danger">❌ ' + (d.erro || 'Erro ao enviar.') + '</div>';
  }
  input.value = '';
}

async function gerarResumo() {
  const r = await fetch('/reunioes/{{ meeting.id }}/resumo-manual', {method:'POST'});
  const d = await r.json();
  if (d.ok) { location.reload(); }
  else { alert(d.erro || 'Erro ao gerar resumo.'); }
}

// Auto-refresh enquanto processando
{% if meeting.notion_status in ['transcription_in_progress', 'summary_in_progress', 'transcription_not_started'] %}
(function checkStatus() {
  setTimeout(async function() {
    const r = await fetch('/reunioes/{{ meeting.id }}/status');
    const d = await r.json();
    if (d.status === 'notes_ready' || d.status === 'error') {
      location.reload();
    } else { checkStatus(); }
  }, 15000);
})();
{% endif %}
</script>
"""

# Injeta o painel no template meetings_detail.html
_mt_tmpl = TEMPLATES.get("meetings_detail.html", "")
if _mt_tmpl and "whisperPanel" not in _mt_tmpl:
    # Insere antes do primeiro </div> após o card de info da reunião
    for _anchor in ['<div class="card p-3 mb-3">', '<div class="card p-4">', '{% block content %}']:
        if _anchor in _mt_tmpl:
            _mt_tmpl = _mt_tmpl.replace(_anchor, _WHISPER_PANEL + "\n" + _anchor, 1)
            TEMPLATES["meetings_detail.html"] = _mt_tmpl
            break

if hasattr(templates_env.loader, "mapping"):
    templates_env.loader.mapping = TEMPLATES

print("[whisper] Patch de transcrição carregado.")

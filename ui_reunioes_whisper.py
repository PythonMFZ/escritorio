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
import sys
import json as _json_w
import shutil as _shutil
import tempfile as _tmpfile
from pathlib import Path as _Path
from datetime import datetime as _dt_w, timedelta as _td_w
from fastapi import BackgroundTasks as _BG

# ── Configuração de paths ─────────────────────────────────────────────────────

# Usa /tmp/reunioes por padrão — efêmero, não consome disco persistente do Render.
# Sobrescreva com AUDIO_UPLOAD_DIR se quiser persistência (Render Disk).
_AUDIO_DIR = _Path(
    _os2.environ.get("AUDIO_UPLOAD_DIR", "/tmp/reunioes")
)
try:
    _AUDIO_DIR.mkdir(parents=True, exist_ok=True)
except Exception:
    _AUDIO_DIR = _Path(_tmpfile.mkdtemp(prefix="reunioes_"))
    _AUDIO_DIR.mkdir(parents=True, exist_ok=True)

_WHISPER_MODEL_NAME = _os2.environ.get("WHISPER_MODEL", "tiny")
_whisper_model_cache = {}  # cache do modelo carregado

# Limpeza de WAVs temporários órfãos e MP3s antigos (> 7 dias) no startup
def _cleanup_orphan_wavs():
    import time as _time_cl
    try:
        removed = 0
        freed = 0
        cutoff = _time_cl.time() - 1 * 86400  # 1 dia (eram 7, reduzido para economizar espaço)
        for f in list(_AUDIO_DIR.glob("*")):
            try:
                if f.stat().st_mtime < cutoff:
                    size = f.stat().st_size
                    f.unlink()
                    removed += 1
                    freed += size
            except Exception:
                pass
        if removed:
            print(f"[whisper] 🧹 Limpeza startup: {removed} arquivo(s) removidos ({freed // 1024 // 1024} MB liberados)")
    except Exception as _e_clean:
        print(f"[whisper] Aviso: falha na limpeza de áudios antigos: {_e_clean}")

_cleanup_orphan_wavs()


def _get_whisper_model():
    """Carrega o modelo faster-whisper uma vez (CPU) e reutiliza entre transcrições."""
    if _WHISPER_MODEL_NAME not in _whisper_model_cache:
        try:
            from faster_whisper import WhisperModel as _WhisperModel
            print(f"[whisper] Carregando modelo local '{_WHISPER_MODEL_NAME}' (faster-whisper, CPU)...")
            _whisper_model_cache[_WHISPER_MODEL_NAME] = _WhisperModel(
                _WHISPER_MODEL_NAME, device="cpu", compute_type="int8"
            )
            print(f"[whisper] Modelo local '{_WHISPER_MODEL_NAME}' carregado.")
        except ImportError:
            print("[whisper] faster-whisper não instalado. Adicione ao requirements.txt")
            return None
        except Exception as _e_load:
            print(f"[whisper] Falha ao carregar modelo local: {_e_load}")
            return None
    return _whisper_model_cache.get(_WHISPER_MODEL_NAME)


def _to_wav_for_local_whisper(audio_path: str) -> str:
    """
    Reconverte o áudio para WAV PCM 16kHz mono via ffmpeg antes de passar ao
    faster-whisper. Formatos vindos do navegador (WebM/Opus do MediaRecorder)
    às vezes são mal interpretados pelo decodificador interno (PyAV) e geram
    transcrição vazia sem erro — um WAV puro elimina essa fonte de falha.
    Retorna o caminho do WAV (pode ser o próprio audio_path se a conversão falhar).
    """
    ffmpeg_bin = _ffmpeg_bin()
    if not ffmpeg_bin:
        return audio_path
    import subprocess as _sp_w
    wav_path = audio_path + ".local16k.wav"
    cmd = [ffmpeg_bin, "-y", "-i", audio_path, "-vn", "-ac", "1", "-ar", "16000", wav_path]
    try:
        proc = _sp_w.run(cmd, capture_output=True, timeout=900)
        wav_exists = _Path(wav_path).exists() and _Path(wav_path).stat().st_size > 0
        if proc.returncode != 0:
            if wav_exists:
                # ffmpeg gerou o arquivo mas retornou warning como erro — usa mesmo assim
                print(f"[whisper] ffmpeg retornou código {proc.returncode} mas WAV foi criado — usando o arquivo")
                return wav_path
            print(f"[whisper] ffmpeg conversão p/ WAV falhou: {proc.stderr.decode(errors='ignore')[:400]}")
            # apaga WAV parcial se existir
            try:
                _Path(wav_path).unlink(missing_ok=True)
            except Exception:
                pass
            return audio_path
        if not wav_exists:
            print("[whisper] ffmpeg não gerou WAV válido")
            return audio_path
        return wav_path
    except Exception as _e_wav:
        print(f"[whisper] ffmpeg conversão p/ WAV exceção: {_e_wav}")
        try:
            _Path(wav_path).unlink(missing_ok=True)
        except Exception:
            pass
        return audio_path


def _transcrever_local_faster_whisper(audio_path: str) -> str:
    """
    Transcreve via faster-whisper em subprocesso separado.
    Passa o áudio direto ao worker (faster-whisper suporta MP3/M4A via ffmpeg interno),
    evitando criação de WAV intermediário no processo principal.
    """
    import subprocess as _sp_wk
    import tempfile as _tf_wk
    import json as _json_wk

    out_file = None
    try:
        fd, out_file = _tf_wk.mkstemp(suffix=".json", prefix="whisper_out_")
        _os2.close(fd)

        # Localiza o worker
        try:
            worker = _Path(__file__).parent / "whisper_worker.py"
        except Exception:
            worker = _Path("whisper_worker.py")
        if not worker.exists():
            worker = _Path("whisper_worker.py")

        print(f"[whisper] Subprocesso iniciado para {_Path(audio_path).name} ...")
        proc = _sp_wk.run(
            [sys.executable, str(worker), audio_path, _WHISPER_MODEL_NAME, out_file],
            timeout=1800,  # 30 min máximo
            capture_output=True,
        )

        stdout = proc.stdout.decode(errors="replace").strip()
        stderr = proc.stderr.decode(errors="replace").strip()
        if stdout:
            print(f"[whisper-worker] {stdout[:600]}")
        if proc.returncode != 0 and stderr:
            print(f"[whisper] Worker código {proc.returncode}: {stderr[:400]}")

        if not _Path(out_file).exists() or _Path(out_file).stat().st_size == 0:
            print("[whisper] Worker não gerou saída — possivelmente OOM ou crash")
            return ""

        result = _json_wk.loads(_Path(out_file).read_text())
        if result.get("ok"):
            texto = result.get("text", "")
            print(f"[whisper] ✅ Subprocesso OK: {len(texto)} chars")
            return texto
        else:
            print(f"[whisper] Worker erro: {result.get('error')}")
            return ""
    except _sp_wk.TimeoutExpired:
        print("[whisper] Worker excedeu timeout de 30 min — abortado")
        return ""
    except Exception as _e_wk:
        print(f"[whisper] Erro ao invocar worker: {_e_wk}")
        return ""
    finally:
        if out_file:
            try:
                _Path(out_file).unlink(missing_ok=True)
            except Exception:
                pass


# ── Compressão/Divisão de áudio para respeitar o limite de 25MB da OpenAI ────

_OPENAI_MAX_BYTES = 24 * 1024 * 1024  # margem de segurança abaixo dos 25MB da API


def _ffmpeg_bin():
    sys_ffmpeg = _shutil.which("ffmpeg")
    if sys_ffmpeg:
        return sys_ffmpeg
    try:
        import imageio_ffmpeg as _iio_ff
        return _iio_ff.get_ffmpeg_exe()
    except Exception:
        return None


def _compress_audio_for_whisper(src_path: str, dst_path: str) -> bool:
    """Reencoda para mono/Opus 32kbps — reduz bastante o tamanho mantendo a voz inteligível."""
    ffmpeg_bin = _ffmpeg_bin()
    if not ffmpeg_bin:
        return False
    import subprocess as _sp_w
    cmd = [
        ffmpeg_bin, "-y", "-i", src_path,
        "-vn", "-ac", "1", "-ar", "16000",
        "-c:a", "libopus", "-b:a", "32k",
        "-f", "ogg", dst_path,
    ]
    try:
        proc = _sp_w.run(cmd, capture_output=True, timeout=900)
        if proc.returncode != 0:
            print(f"[whisper] ffmpeg compressão falhou: {proc.stderr.decode(errors='ignore')[:400]}")
            return False
        return _Path(dst_path).exists()
    except Exception as _e_comp:
        print(f"[whisper] ffmpeg compressão exceção: {_e_comp}")
        return False


def _split_audio_for_whisper(src_path: str, out_dir: str, segment_seconds: int = 1200) -> list:
    """Divide o áudio (já comprimido) em pedaços de N segundos sem recodificar."""
    ffmpeg_bin = _ffmpeg_bin()
    if not ffmpeg_bin:
        return []
    import subprocess as _sp_w
    pattern = str(_Path(out_dir) / "chunk_%03d.ogg")
    cmd = [
        ffmpeg_bin, "-y", "-i", src_path,
        "-c", "copy", "-f", "segment",
        "-segment_time", str(segment_seconds),
        "-reset_timestamps", "1",
        pattern,
    ]
    try:
        proc = _sp_w.run(cmd, capture_output=True, timeout=1200)
        if proc.returncode != 0:
            print(f"[whisper] ffmpeg split falhou: {proc.stderr.decode(errors='ignore')[:400]}")
            return []
    except Exception as _e_split:
        print(f"[whisper] ffmpeg split exceção: {_e_split}")
        return []
    return sorted(str(p) for p in _Path(out_dir).glob("chunk_*.ogg"))


def _prepare_audio_for_whisper(audio_path: str):
    """
    Garante que cada arquivo enviado à API da OpenAI fique abaixo do limite de 25MB.
    Comprime para Opus mono 32kbps e, se ainda assim exceder, divide em pedaços.
    Retorna (lista_de_caminhos_em_ordem, tmp_dir_ou_None) — tmp_dir deve ser
    removido pelo chamador após o uso.
    """
    try:
        size = _Path(audio_path).stat().st_size
    except Exception:
        return [audio_path], None

    if size <= _OPENAI_MAX_BYTES:
        return [audio_path], None

    print(f"[whisper] Arquivo de {size/1024/1024:.1f}MB excede 25MB — comprimindo...")
    tmp_dir = _tmpfile.mkdtemp(prefix="whisper_")
    compressed_path = str(_Path(tmp_dir) / "compressed.ogg")

    if not _compress_audio_for_whisper(audio_path, compressed_path):
        print("[whisper] Compressão indisponível (FFmpeg ausente no servidor?) — tentando enviar arquivo original.")
        _shutil.rmtree(tmp_dir, ignore_errors=True)
        return [audio_path], None

    comp_size = _Path(compressed_path).stat().st_size
    print(f"[whisper] Comprimido para {comp_size/1024/1024:.1f}MB")

    if comp_size <= _OPENAI_MAX_BYTES:
        return [compressed_path], tmp_dir

    print("[whisper] Ainda acima de 25MB após compressão — dividindo em pedaços...")
    chunks = _split_audio_for_whisper(compressed_path, tmp_dir, segment_seconds=1200)
    return (chunks if chunks else [compressed_path]), tmp_dir


def _gerar_resumo_ia(transcricao: str, titulo: str) -> dict:
    """Usa Claude para gerar resumo estruturado da transcrição."""
    import requests as _req_w
    api_key = _os2.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key or not transcricao:
        return {"summary": "", "action_items": "", "notes": ""}

    # Limita a ~120k chars (~30k tokens) para reuniões longas; o corte de 8k antes perdia 90% do conteúdo
    transcricao_truncada = transcricao[:120000]
    if len(transcricao) > 120000:
        transcricao_truncada += "\n\n[TRANSCRIÇÃO TRUNCADA — fim do limite de processamento]"

    prompt = f"""Você é um assistente especializado em reuniões de empresas do setor de construção civil e incorporação imobiliária.

Analise a transcrição completa da reunião "{titulo}" e gere um relatório estruturado e completo.

Contexto: As reuniões costumam envolver discussões sobre:
- Obras e empreendimentos imobiliários (lançamentos, velocidade de vendas, fluxo de caixa de obra)
- Financeiro da empresa (fluxo de caixa semanal, contas a pagar/receber, aplicações, inadimplência)
- Equipe comercial e corretores
- Sistema de gestão interno (Augur) — integração com Sienge, importação de dados, demos de funcionalidades
- Estratégia de negócios e mercado imobiliário

IMPORTANTE:
- Capture TODOS os temas discutidos, mesmo que brevemente
- Inclua dados numéricos, nomes de empreendimentos e valores quando mencionados
- Não omita temas por serem técnicos ou por parecerem secundários (demos de sistema, análises de planilha, etc.)
- Responda APENAS com JSON válido, sem texto antes ou depois
- Todos os valores devem ser strings simples (não listas nem objetos aninhados)

Transcrição:
{transcricao_truncada}

Responda exatamente neste formato JSON:
{{
  "summary": "Resumo detalhado cobrindo TODOS os temas da reunião, organizado por assunto com títulos em negrito. Mínimo 5 parágrafos. Inclua dados numéricos, nomes de projetos e pessoas relevantes.",
  "action_items": "Lista de próximas ações, uma por linha, com responsável entre parênteses quando mencionado. Inclua TODAS as ações, tarefas e follow-ups mencionados.",
  "decisions": "Decisões tomadas e pontos de atenção relevantes, um por linha."
}}"""

    try:
        print(f"[whisper] Chamando Claude para resumo ({len(transcricao_truncada)} chars)...")
        resp = _req_w.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": "claude-sonnet-4-6",
                "max_tokens": 4000,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=600,
        )
        resp.raise_for_status()
        texto = resp.json()["content"][0]["text"]
        print(f"[whisper] Claude respondeu: {len(texto)} chars")

        # Tenta parsear JSON
        import re as _re_w
        json_match = _re_w.search(r'\{.*\}', texto, _re_w.DOTALL)
        if json_match:
            dados = _json_w.loads(json_match.group())
            return {
                "summary":          dados.get("summary", ""),
                "action_items":     dados.get("action_items", ""),
                "notes":            dados.get("decisions", ""),
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
    Background task: transcreve via OpenAI Whisper API (primário, sem download
    de modelo); se não configurada, tenta faster-whisper local (fallback).
    """
    print(f"[whisper] Iniciando transcrição da reunião {meeting_id}...")

    from sqlmodel import Session as _SessW
    with _SessW(engine) as _sess:
        mt = _sess.get(Meeting, meeting_id)
        if not mt:
            return
        mt.notion_status = "transcription_in_progress"
        mt.updated_at = _dt_w.utcnow()
        _sess.add(mt); _sess.commit()

    transcricao = ""
    _erro_real = ""

    # ── Primário: Groq Whisper API (grátis, rápido, sem limite prático) ──────
    groq_key = _os2.environ.get("GROQ_API_KEY", "")
    if groq_key and _Path(audio_path).exists():
        _tmp_dir_groq = None
        try:
            import httpx as _hx_groq
            partes, _tmp_dir_groq = _prepare_audio_for_whisper(audio_path)
            print(f"[whisper] Usando Groq Whisper API ({len(partes)} parte(s))...")
            textos = []
            for _i_parte, parte in enumerate(partes, start=1):
                print(f"[whisper] Groq: parte {_i_parte}/{len(partes)}...")
                with open(parte, "rb") as _af:
                    resp = _hx_groq.post(
                        "https://api.groq.com/openai/v1/audio/transcriptions",
                        headers={"Authorization": f"Bearer {groq_key}"},
                        data={"model": "whisper-large-v3-turbo", "language": "pt", "response_format": "text"},
                        files={"file": (_Path(parte).name, _af, "audio/ogg")},
                        timeout=300,
                    )
                resp.raise_for_status()
                textos.append(resp.text.strip())
            transcricao = "\n\n".join(t for t in textos if t)
            print(f"[whisper] Groq OK: {len(transcricao)} chars")
        except Exception as _ge:
            _erro_real = str(_ge)
            print(f"[whisper] Groq API falhou: {_ge}")
        finally:
            if _tmp_dir_groq:
                _shutil.rmtree(_tmp_dir_groq, ignore_errors=True)

    # ── Secundário: OpenAI Whisper API ───────────────────────────────────────
    openai_key = _os2.environ.get("OPENAI_API_KEY", "")
    if not transcricao and openai_key and _Path(audio_path).exists():
        _tmp_dir_whisper = None
        try:
            import openai as _oai
            _oai_client = _oai.OpenAI(api_key=openai_key)
            partes, _tmp_dir_whisper = _prepare_audio_for_whisper(audio_path)
            print(f"[whisper] Usando OpenAI Whisper API ({len(partes)} parte(s))...")
            textos = []
            for _i_parte, parte in enumerate(partes, start=1):
                print(f"[whisper] Transcrevendo parte {_i_parte}/{len(partes)}...")
                with open(parte, "rb") as _af:
                    result = _oai_client.audio.transcriptions.create(
                        model="whisper-1",
                        file=_af,
                        language="pt",
                    )
                textos.append(result.text.strip())
            transcricao = "\n\n".join(t for t in textos if t)
            print(f"[whisper] OpenAI API OK: {len(transcricao)} chars")
        except Exception as _oe:
            _erro_real = str(_oe)
            print(f"[whisper] OpenAI API falhou: {_oe}")
        finally:
            if _tmp_dir_whisper:
                _shutil.rmtree(_tmp_dir_whisper, ignore_errors=True)

    # ── Fallback: faster-whisper local (apenas se sem API keys) ─────────────
    if not transcricao and not openai_key and not groq_key and _Path(audio_path).exists():
        try:
            transcricao = _transcrever_local_faster_whisper(audio_path)
            if transcricao:
                print(f"[whisper] Transcrição local OK: {len(transcricao)} chars")
        except Exception as _le:
            _erro_real = str(_le)
            print(f"[whisper] Transcrição local falhou: {_le}")

    # ── Arquivo não encontrado ───────────────────────────────────────────────
    if not _Path(audio_path).exists() and not transcricao:
        print(f"[whisper] ❌ Arquivo não encontrado: {audio_path}")
        with _SessW(engine) as _s:
            _mt = _s.get(Meeting, meeting_id)
            if _mt:
                _mt.notion_status = "error"
                _mt.notes_text = "Arquivo de áudio não encontrado. O servidor pode ter reiniciado durante o upload. Por favor, faça upload novamente."
                _s.add(_mt); _s.commit()
        return

    if not transcricao:
        print(f"[whisper] ❌ Transcrição vazia após todas as tentativas.")
        with _SessW(engine) as _s:
            _mt = _s.get(Meeting, meeting_id)
            if _mt:
                _mt.notion_status = "error"
                _detalhe = f" Detalhe: {_erro_real}" if _erro_real else ""
                _mt.notes_text = (
                    "Não foi possível transcrever o áudio (modelo local indisponível e "
                    "nenhum fallback configurado). Tente um arquivo MP3/M4A." + _detalhe
                )
                _s.add(_mt); _s.commit()
        try:
            _Path(audio_path).unlink(missing_ok=True)
        except Exception:
            pass
        return

    print(f"[whisper] ✅ Transcrição OK: {len(transcricao)} chars")

    # Atualiza banco com transcrição
    with _SessW(engine) as _s:
        _mt = _s.get(Meeting, meeting_id)
        if _mt:
            _mt.transcript_text = transcricao
            _mt.notion_status = "summary_in_progress"
            _s.add(_mt); _s.commit()

    # Gera resumo com Claude
    with _SessW(engine) as _s:
        _mt = _s.get(Meeting, meeting_id)
        if _mt:
            resumo = _gerar_resumo_ia(transcricao, _mt.title)
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

    try:
        _Path(audio_path).unlink(missing_ok=True)
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

    # Salva em disco (sempre como .mp3 comprimido para economizar espaço)
    raw_path  = _AUDIO_DIR / f"meeting_{meeting_id}_{_dt_w.utcnow().strftime('%Y%m%d_%H%M%S')}_raw.{ext}"
    audio_path = _AUDIO_DIR / f"meeting_{meeting_id}_{_dt_w.utcnow().strftime('%Y%m%d_%H%M%S')}.mp3"
    try:
        # Salva em chunks para não carregar tudo na RAM
        import shutil as _shu
        _MAX_UPLOAD = 1024 * 1024 * 1024  # 1 GB
        _written = 0
        with open(raw_path, "wb") as _f:
            while True:
                chunk = await audio_file.read(1024 * 1024)  # 1MB por vez
                if not chunk:
                    break
                _written += len(chunk)
                if _written > _MAX_UPLOAD:
                    _f.close()
                    raw_path.unlink(missing_ok=True)
                    return JSONResponse({"ok": False, "erro": "Arquivo muito grande (máx. 1GB). Comprime o áudio antes de enviar."})
                _f.write(chunk)
        # verifica espaço disponível para compressão (MP3 32kbps ocupa ~5% do original)
        free = _shu.disk_usage(str(_AUDIO_DIR)).free
        if _written * 1.2 > free:
            raw_path.unlink(missing_ok=True)
            return JSONResponse({"ok": False, "erro": f"Espaço insuficiente no servidor ({free // 1024 // 1024} MB livres). Contate o suporte."})
    except Exception as e:
        return JSONResponse({"ok": False, "erro": f"Erro ao salvar arquivo: {e}"})

    # Comprime sempre para MP3 mono 32kbps via ffmpeg (reduz 90% do tamanho)
    ffmpeg_bin = _ffmpeg_bin()
    if ffmpeg_bin:
        import subprocess as _sp_up
        try:
            proc = _sp_up.run(
                [ffmpeg_bin, "-y", "-i", str(raw_path),
                 "-vn", "-ac", "1", "-ar", "16000", "-ab", "32k",
                 str(audio_path)],
                capture_output=True, timeout=300,
            )
            raw_path.unlink(missing_ok=True)
            if proc.returncode != 0 or not audio_path.exists():
                # fallback: usa o arquivo original
                raw_path.rename(audio_path) if raw_path.exists() else None
        except Exception:
            if raw_path.exists():
                raw_path.rename(audio_path)
    else:
        # já é mp3 ou sem ffmpeg: usa direto
        try:
            raw_path.rename(audio_path)
        except Exception:
            audio_path = raw_path

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
        "msg": f"Áudio recebido ({_written/1024/1024:.1f}MB). Transcrição iniciada em background — atualize a página em alguns minutos.",
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
        try:
            with _SW2(engine) as _s:
                _mt = _s.get(Meeting, meeting_id)
                if _mt:
                    _mt.notion_status = "summary_in_progress"
                    _s.add(_mt); _s.commit()
            resumo = {}
            with _SW2(engine) as _s:
                _mt = _s.get(Meeting, meeting_id)
                if _mt:
                    resumo = _gerar_resumo_ia(_mt.transcript_text, _mt.title)
            with _SW2(engine) as _s:
                _mt = _s.get(Meeting, meeting_id)
                if _mt:
                    _mt.summary_text      = resumo.get("summary", "")
                    _mt.action_items_text = resumo.get("action_items", "")
                    _mt.notes_text        = resumo.get("notes", "")
                    _mt.notion_status     = "notes_ready"
                    _mt.updated_at        = _dt_w.utcnow()
                    _s.add(_mt); _s.commit()
                    print(f"[whisper] Resumo salvo para reunião {meeting_id}.")
        except Exception as _e_bg:
            print(f"[whisper] Erro no background resumo reunião {meeting_id}: {_e_bg}")
            try:
                with _SW2(engine) as _s:
                    _mt = _s.get(Meeting, meeting_id)
                    if _mt and _mt.notion_status == "summary_in_progress":
                        _mt.notion_status = "notes_ready"
                        _s.add(_mt); _s.commit()
            except Exception:
                pass

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
    {% if meeting.notion_status in ['notes_ready', 'error', 'transcription_in_progress', 'summary_in_progress'] %}
    <div id="whisperStatus" class="badge
      {% if meeting.notion_status == 'notes_ready' %}text-bg-success
      {% elif meeting.notion_status == 'error' %}text-bg-danger
      {% else %}text-bg-warning
      {% endif %}">
      {% if meeting.notion_status == 'notes_ready' %}✅ Transcrição pronta
      {% elif meeting.notion_status == 'transcription_in_progress' %}⏳ Transcrevendo...
      {% elif meeting.notion_status == 'summary_in_progress' %}🤖 Gerando resumo...
      {% elif meeting.notion_status == 'error' %}❌ Erro
      {% endif %}
    </div>
    {% endif %}
  </div>

  {% if meeting.notion_status in ['transcription_in_progress', 'summary_in_progress'] %}
  <div class="d-flex gap-2 align-items-center mb-2">
    <form method="post" action="/reunioes/{{ meeting.id }}/reset-transcricao" class="d-inline">
      <button type="submit" class="btn btn-outline-warning btn-sm">
        🔄 Tentar novamente
      </button>
    </form>
    <span class="text-muted small">Preso? Clique para reiniciar a transcrição.</span>
  </div>
  {% endif %}

  {% if meeting.notion_status not in ['notes_ready', 'transcription_in_progress', 'summary_in_progress'] %}
  <div class="d-flex gap-2 align-items-center flex-wrap mb-2">

    {# Botão de gravação nativa (microfone) #}
    <button id="btnGravar" class="btn btn-danger btn-sm" onclick="iniciarGravacao()">
      <i class="bi bi-record-circle me-1"></i>Gravar microfone
    </button>

    {# Botão de gravação de call (áudio da aba/tela + microfone) #}
    <button id="btnGravarCall" class="btn btn-outline-danger btn-sm" onclick="iniciarGravacaoCall()" title="Capture o áudio de uma aba ou tela compartilhada (ex.: Google Meet) junto com seu microfone">
      <i class="bi bi-camera-video me-1"></i>Gravar call (aba/tela)
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
  <div class="muted small mb-2" style="max-width:520px;">
    "Gravar call" pede para você escolher uma aba/tela para compartilhar — marque
    a opção <strong>"Compartilhar áudio"</strong> na janela do navegador para capturar
    a voz dos outros participantes junto com seu microfone (funciona no Chrome/Edge;
    no Mac, só captura áudio se você compartilhar uma aba, não a tela inteira).
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

  {% if meeting.notion_status in ['transcription_in_progress', 'summary_in_progress'] %}
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
let _mediaRecorder   = null;
let _audioChunks     = [];
let _timerInterval   = null;
let _segundos        = 0;
let _micStreamRef    = null;
let _displayStreamRef = null;
let _audioCtxRef     = null;

function _iniciarTimerEUi(statusMsg) {
  document.getElementById('btnGravar').style.display = 'none';
  document.getElementById('btnGravarCall').style.display = 'none';
  document.getElementById('btnParar').style.display  = 'inline-flex';
  document.getElementById('gravarInfo').style.display = 'block';
  document.getElementById('gravarStatus').textContent = statusMsg;
  _timerInterval = setInterval(() => {
    _segundos++;
    const m = String(Math.floor(_segundos/60)).padStart(2,'0');
    const s = String(_segundos%60).padStart(2,'0');
    document.getElementById('gravarTimer').textContent = m+':'+s;
  }, 1000);
}

function _melhorMimeType() {
  return MediaRecorder.isTypeSupported('audio/webm;codecs=opus')
    ? 'audio/webm;codecs=opus'
    : MediaRecorder.isTypeSupported('audio/webm')
      ? 'audio/webm'
      : 'audio/ogg';
}

async function iniciarGravacao() {
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    _micStreamRef = stream;
    _audioChunks = [];
    _segundos = 0;

    const mimeType = _melhorMimeType();
    _mediaRecorder = new MediaRecorder(stream, { mimeType });
    _mediaRecorder.ondataavailable = e => { if (e.data.size > 0) _audioChunks.push(e.data); };
    _mediaRecorder.onstop = () => enviarGravacao(mimeType);
    _mediaRecorder.start(1000); // coleta chunks a cada 1s

    _iniciarTimerEUi('Microfone ativo...');
  } catch(e) {
    alert('Não foi possível acessar o microfone: ' + e.message + '\n\nVerifique as permissões do navegador.');
  }
}

// Captura o áudio de uma aba/tela compartilhada (ex.: Google Meet, Zoom web)
// e mixa com o microfone, para gravar a call inteira (todos os participantes).
async function iniciarGravacaoCall() {
  try {
    const displayStream = await navigator.mediaDevices.getDisplayMedia({ video: true, audio: true });
    _displayStreamRef = displayStream;

    let micStream = null;
    try {
      micStream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch (e) {
      // Segue sem microfone se o usuário negar — ainda grava o áudio da call.
    }
    _micStreamRef = micStream;

    const displayAudioTracks = displayStream.getAudioTracks();
    if (displayAudioTracks.length === 0) {
      alert('A aba/tela compartilhada não enviou áudio. Ao escolher o que compartilhar, marque a opção "Compartilhar áudio da aba/sistema".');
    }

    const audioCtx = new (window.AudioContext || window.webkitAudioContext)();
    _audioCtxRef = audioCtx;
    const destination = audioCtx.createMediaStreamDestination();

    if (displayAudioTracks.length > 0) {
      audioCtx.createMediaStreamSource(new MediaStream(displayAudioTracks)).connect(destination);
    }
    if (micStream) {
      audioCtx.createMediaStreamSource(micStream).connect(destination);
    }

    _audioChunks = [];
    _segundos = 0;
    const mimeType = _melhorMimeType();
    _mediaRecorder = new MediaRecorder(destination.stream, { mimeType });
    _mediaRecorder.ondataavailable = e => { if (e.data.size > 0) _audioChunks.push(e.data); };
    _mediaRecorder.onstop = () => enviarGravacao(mimeType);
    _mediaRecorder.start(1000);

    // Se o usuário clicar em "Parar de compartilhar" na barra do navegador.
    const videoTrack = displayStream.getVideoTracks()[0];
    if (videoTrack) videoTrack.addEventListener('ended', pararGravacao);

    _iniciarTimerEUi('Capturando áudio da call' + (micStream ? ' + microfone' : '') + '...');
  } catch(e) {
    alert('Não foi possível capturar a aba/tela: ' + e.message);
  }
}

function pararGravacao() {
  if (_mediaRecorder && _mediaRecorder.state !== 'inactive') {
    _mediaRecorder.stop();
  }
  if (_micStreamRef) {
    _micStreamRef.getTracks().forEach(t => t.stop());
    _micStreamRef = null;
  }
  if (_displayStreamRef) {
    _displayStreamRef.getTracks().forEach(t => t.stop());
    _displayStreamRef = null;
  }
  if (_audioCtxRef) {
    _audioCtxRef.close();
    _audioCtxRef = null;
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
      document.getElementById('btnGravarCall').style.display = 'inline-flex';
    }
  } catch(e) {
    fb.innerHTML = '<div class="alert alert-danger">❌ Erro de conexão. Tente novamente.</div>';
    document.getElementById('btnGravar').style.display = 'inline-flex';
    document.getElementById('btnGravarCall').style.display = 'inline-flex';
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
{% if meeting.notion_status in ['transcription_in_progress', 'summary_in_progress'] %}
(function checkStatus() {
  setTimeout(async function() {
    const r = await fetch('/reunioes/{{ meeting.id }}/status');
    const d = await r.json();
    if (d.status === 'notes_ready' || d.status === 'error' || d.status === 'transcription_not_started') {
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


# ── Rota POST /reunioes/{id}/reset-transcricao ────────────────────────────────

@app.post("/reunioes/{meeting_id}/reset-transcricao")
@require_login
async def reuniao_reset_transcricao(
    meeting_id: int,
    request: Request,
    session: Session = Depends(get_session),
):
    """Reseta reunião presa em transcription_in_progress/summary_in_progress."""
    ctx = get_tenant_context(request, session)
    if not ctx or ctx.membership.role not in ("admin", "equipe"):
        return RedirectResponse(f"/reunioes/{meeting_id}", status_code=303)

    mt = session.get(Meeting, meeting_id)
    if mt and mt.company_id == ctx.company.id:
        mt.notion_status = "transcription_not_started"
        mt.updated_at = _dt_w.utcnow()
        session.add(mt)
        session.commit()
        print(f"[whisper] Reunião {meeting_id} resetada manualmente para transcription_not_started")

    return RedirectResponse(f"/reunioes/{meeting_id}", status_code=303)


# ── Reset de reuniões presas no startup ───────────────────────────────────────
# Quando o app reinicia (deploy, crash), qualquer reunião presa em
# transcription_in_progress ou summary_in_progress nunca vai terminar.
# Resetamos para transcription_not_started para que o usuário possa tentar novamente.

try:
    from sqlmodel import Session as _SessWS
    with _SessWS(engine) as _sess_startup:
        _presas = _sess_startup.exec(
            select(Meeting).where(
                Meeting.notion_status.in_(["transcription_in_progress", "summary_in_progress"])
            )
        ).all()
        for _mp in _presas:
            _mp.notion_status = "transcription_not_started"
            _sess_startup.add(_mp)
        if _presas:
            _sess_startup.commit()
            print(f"[whisper] ⚠️  {len(_presas)} reunião(ões) presa(s) resetada(s) no startup.")
except Exception as _ew:
    print(f"[whisper] Startup reset: {_ew}")


print("[whisper] Patch de transcrição carregado.")

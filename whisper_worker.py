"""
Whisper transcription worker — runs as a child process so OOM kills only
this process and not the web server.

Usage:
    python whisper_worker.py <audio_path> <model_name> <output_json_path>

Writes {"ok": true, "text": "..."} or {"ok": false, "error": "..."} to output_json_path.
"""
import sys
import json
import os
import subprocess
from pathlib import Path


def _find_ffmpeg():
    for candidate in ("ffmpeg", "/usr/bin/ffmpeg", "/usr/local/bin/ffmpeg"):
        try:
            subprocess.run([candidate, "-version"], capture_output=True, timeout=5)
            return candidate
        except Exception:
            continue
    return None


def _to_wav(audio_path: str) -> str:
    """Convert to 16kHz mono WAV for best whisper compatibility. Returns wav path or original."""
    ffmpeg = _find_ffmpeg()
    if not ffmpeg:
        return audio_path
    wav_path = audio_path + ".worker16k.wav"
    try:
        proc = subprocess.run(
            [ffmpeg, "-y", "-i", audio_path, "-vn", "-ac", "1", "-ar", "16000", wav_path],
            capture_output=True, timeout=600,
        )
        if Path(wav_path).exists() and Path(wav_path).stat().st_size > 0:
            return wav_path
    except Exception as e:
        print(f"[worker] ffmpeg falhou: {e}", file=sys.stderr)
    # cleanup partial
    try:
        Path(wav_path).unlink(missing_ok=True)
    except Exception:
        pass
    return audio_path


def main():
    if len(sys.argv) < 4:
        print(json.dumps({"ok": False, "error": "usage: whisper_worker.py <audio> <model> <out.json>"}))
        sys.exit(1)

    audio_path = sys.argv[1]
    model_name = sys.argv[2]
    out_path   = sys.argv[3]

    def write(payload):
        with open(out_path, "w") as f:
            json.dump(payload, f)

    if not os.path.exists(audio_path):
        write({"ok": False, "error": f"audio not found: {audio_path}"})
        sys.exit(1)

    wav_path = audio_path
    try:
        from faster_whisper import WhisperModel
        print(f"[worker] Carregando modelo '{model_name}'...", file=sys.stderr)
        model = WhisperModel(model_name, device="cpu", compute_type="int8")
        print(f"[worker] Modelo carregado. Convertendo áudio...", file=sys.stderr)

        wav_path = _to_wav(audio_path)
        print(f"[worker] Transcrevendo {Path(wav_path).name} ...", file=sys.stderr)

        segments, info = model.transcribe(wav_path, language="pt", vad_filter=True)
        segments = list(segments)
        dur = getattr(info, "duration", "?")
        print(f"[worker] Duração: {dur}s — segmentos: {len(segments)}", file=sys.stderr)
        text = " ".join(s.text.strip() for s in segments).strip()

        if not text:
            print("[worker] VAD filtrou tudo — tentando sem VAD...", file=sys.stderr)
            segments2, _ = model.transcribe(wav_path, language="pt", vad_filter=False)
            text = " ".join(s.text.strip() for s in list(segments2)).strip()

        print(f"[worker] ✅ {len(text)} chars transcritos", file=sys.stderr)
        write({"ok": True, "text": text})
    except Exception as e:
        write({"ok": False, "error": str(e)})
        sys.exit(1)
    finally:
        if wav_path != audio_path:
            try:
                Path(wav_path).unlink(missing_ok=True)
            except Exception:
                pass


if __name__ == "__main__":
    main()

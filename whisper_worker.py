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

    try:
        from faster_whisper import WhisperModel
        model = WhisperModel(model_name, device="cpu", compute_type="int8")

        segments, info = model.transcribe(audio_path, language="pt", vad_filter=True)
        segments = list(segments)
        text = " ".join(s.text.strip() for s in segments).strip()

        if not text:
            segments2, _ = model.transcribe(audio_path, language="pt", vad_filter=False)
            text = " ".join(s.text.strip() for s in list(segments2)).strip()

        write({"ok": True, "text": text})
    except Exception as e:
        write({"ok": False, "error": str(e)})
        sys.exit(1)

if __name__ == "__main__":
    main()

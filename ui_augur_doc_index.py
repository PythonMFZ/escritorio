# ── Augur Document Indexer ────────────────────────────────────────────────────
# Indexa automaticamente todos os Attachment da plataforma na BaseConhecimento.
# Roda em background thread, processa em lotes, isolamento por client_id.
#
# Formatos suportados: PDF, imagens (JPEG/PNG/GIF/WEBP), TXT/CSV, DOCX
# Usa Claude Haiku para extração (barato, rápido).
# ─────────────────────────────────────────────────────────────────────────────

import base64
import os
import threading
import time
from pathlib import Path
from typing import Optional

import httpx
from sqlmodel import Field as _FDI, SQLModel as _SMDI, Session as _SessDI, select as _selDI

_ANTHROPIC_KEY   = os.getenv("ANTHROPIC_API_KEY", "")
_UPLOAD_DIR      = Path(os.getenv("UPLOAD_DIR") or "./uploads").resolve()
_INDEX_INTERVAL  = int(os.getenv("AUGUR_INDEX_INTERVAL_S", "60"))
_BATCH_SIZE      = int(os.getenv("AUGUR_INDEX_BATCH", "5"))
_MAX_TOKENS      = int(os.getenv("AUGUR_INDEX_MAX_TOKENS", "1024"))
_MAX_FILE_BYTES  = int(os.getenv("AUGUR_INDEX_MAX_FILE_MB", "10")) * 1024 * 1024

_SUPPORTED_MIME = {
    "application/pdf",
    "image/jpeg", "image/png", "image/gif", "image/webp",
    "text/plain", "text/csv",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}

_EXTRACT_PROMPT = (
    "Você é um assistente especializado em documentos financeiros e empresariais. "
    "Leia o documento e extraia as informações relevantes em texto estruturado. "
    "Inclua: valores, datas, partes envolvidas, obrigações, condições, vencimentos e indicadores. "
    "Seja conciso mas completo. Responda em português."
)

# ── Adiciona attachment_id na BaseConhecimento (migration inline) ─────────────
try:
    import sqlalchemy as _sa_di
    with engine.connect() as _c:
        _c.execute(_sa_di.text(
            "ALTER TABLE baseconhecimento ADD COLUMN attachment_id INTEGER DEFAULT NULL"
        ))
        _c.commit()
        print("[augur_index] ✅ Coluna attachment_id adicionada em baseconhecimento")
except Exception:
    pass  # já existe — normal


# ── Extração de texto DOCX ────────────────────────────────────────────────────
def _extract_docx(path: Path) -> str:
    try:
        import docx  # python-docx
        doc = docx.Document(str(path))
        return "\n".join(p.text for p in doc.paragraphs if p.text.strip())
    except Exception as e:
        print(f"[augur_index] docx erro: {e}")
        return ""


# ── Chamada Claude Haiku via httpx (evita dependência do SDK) ─────────────────
def _claude_extract(file_bytes: bytes, mime_type: str) -> str:
    if not _ANTHROPIC_KEY:
        return ""
    if len(file_bytes) > _MAX_FILE_BYTES:
        return "[arquivo muito grande para indexar]"

    b64 = base64.standard_b64encode(file_bytes).decode()

    if mime_type == "application/pdf":
        content = [
            {"type": "document", "source": {"type": "base64", "media_type": "application/pdf", "data": b64}},
            {"type": "text", "text": _EXTRACT_PROMPT},
        ]
    elif mime_type.startswith("image/"):
        content = [
            {"type": "image", "source": {"type": "base64", "media_type": mime_type, "data": b64}},
            {"type": "text", "text": _EXTRACT_PROMPT},
        ]
    else:
        text = file_bytes.decode("utf-8", errors="replace")[:40000]
        content = [{"type": "text", "text": f"{_EXTRACT_PROMPT}\n\nConteúdo:\n{text}"}]

    try:
        r = httpx.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": _ANTHROPIC_KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": "claude-haiku-4-5-20251001",
                "max_tokens": _MAX_TOKENS,
                "messages": [{"role": "user", "content": content}],
            },
            timeout=60.0,
        )
        r.raise_for_status()
        data = r.json()
        return (data.get("content") or [{}])[0].get("text", "")
    except Exception as e:
        print(f"[augur_index] Claude API erro: {e}")
        return ""


# ── Processa um único Attachment ──────────────────────────────────────────────
def _process(att_id: int) -> bool:
    with _SessDI(engine) as ses:
        att = ses.get(Attachment, att_id)
        if not att:
            return False

        # Verifica se já indexado
        already = ses.exec(
            _selDI(BaseConhecimento).where(
                BaseConhecimento.attachment_id == att_id  # type: ignore[attr-defined]
            )
        ).first()
        if already:
            return True

        file_path = _UPLOAD_DIR / att.stored_filename
        if not file_path.exists():
            print(f"[augur_index] arquivo não encontrado: {file_path}")
            return False

        mime = att.mime_type or ""

        # DOCX: extrai texto localmente
        if "wordprocessingml" in mime:
            text = _extract_docx(file_path)
            file_bytes = text.encode("utf-8") if text else b""
            mime = "text/plain"
        else:
            file_bytes = file_path.read_bytes()

        if not file_bytes:
            return False

        conteudo = _claude_extract(file_bytes, mime)

        bc = BaseConhecimento(  # type: ignore[call-arg]
            company_id=att.company_id,
            client_id=att.client_id or 0,
            user_id=0,
            nome=att.original_filename or "Anexo",
            descricao="Extraído automaticamente de anexo da plataforma",
            tipo="anexo_plataforma",
            conteudo_texto=conteudo,
            attachment_id=att_id,
            created_at=str(utcnow().isoformat()),
        )
        ses.add(bc)
        ses.commit()
        print(f"[augur_index] ✅ Indexado: {att.original_filename} (id={att_id}, client={att.client_id})")
        return True


# ── Loop em background ────────────────────────────────────────────────────────
def _index_loop():
    time.sleep(20)  # aguarda app inicializar completamente
    print("[augur_index] Loop iniciado.")
    while True:
        try:
            with _SessDI(engine) as ses:
                # IDs já indexados
                indexed_ids = set(
                    row[0] for row in ses.exec(
                        _selDI(BaseConhecimento.attachment_id)  # type: ignore[attr-defined]
                        .where(BaseConhecimento.attachment_id.isnot(None))  # type: ignore[attr-defined]
                    ).all()
                    if row[0] is not None
                )

                # Anexos ainda não indexados, tipos suportados, mais recentes primeiro
                pending = ses.exec(
                    _selDI(Attachment)
                    .where(Attachment.mime_type.in_(list(_SUPPORTED_MIME)))
                    .order_by(Attachment.id.desc())
                ).all()
                to_do = [a for a in pending if a.id not in indexed_ids][:_BATCH_SIZE]

            for att in to_do:
                _process(att.id)
                time.sleep(2)  # throttle para não sobrecarregar a API
        except Exception as e:
            print(f"[augur_index] Erro no loop: {e}")

        time.sleep(_INDEX_INTERVAL)


threading.Thread(target=_index_loop, daemon=True, name="augur-doc-indexer").start()
print("[augur_index] ✅ Indexador de documentos Augur iniciado (intervalo: {}s)".format(_INDEX_INTERVAL))

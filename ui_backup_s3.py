# ui_backup_s3.py — Backup automático do PostgreSQL para AWS S3
# Exec'd no namespace do app.py
#
# O QUE FAZ:
#   1. Roda pg_dump diariamente às 03:00 UTC
#   2. Comprime com gzip
#   3. Envia para s3://maffezzolli-escritorio-db-backups/db-backups/
#   4. Mantém 30 dias de histórico (deleta os mais antigos)
#   5. Expõe GET /admin/backup/status para verificar último backup
#
# VARIÁVEIS DE AMBIENTE (já configuradas no Render):
#   DATABASE_URL, AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_REGION
#   APP_S3_BUCKET_NAME (maffezzolli-escritorio-db-backups)

import os       as _os_bk
import fcntl    as _fcntl_bk
import zlib     as _zlib_bk
import tempfile as _tmp_bk
import threading as _thread_bk
import time     as _time_bk
import subprocess as _sp_bk
from datetime  import datetime as _dt_bk, timezone as _tz_bk
from pathlib   import Path as _Path_bk

# ── Config ────────────────────────────────────────────────────────────────────

_BK_BUCKET    = _os_bk.environ.get("APP_S3_BUCKET_NAME", "maffezzolli-escritorio-db-backups")
_BK_REGION    = _os_bk.environ.get("AWS_REGION", "us-east-2")
_BK_PREFIX    = "db-backups"
_BK_KEEP_DAYS = 30
_BK_HOUR_UTC  = 3   # 03:00 UTC = meia-noite horário Brasília


# ── Estado em memória ─────────────────────────────────────────────────────────

_bk_state = {
    "last_run":    None,   # datetime
    "last_status": "never",  # "ok" | "error" | "never"
    "last_file":   "",
    "last_size_mb": 0.0,
    "last_error":  "",
}


_BK_LOCK = _Path_bk(_tmp_bk.gettempdir()) / "backup_s3.lock"


class _GzipDoPipe:
    """Arquivo somente-leitura que entrega o stdout do pg_dump já em gzip, em pedaços."""

    def __init__(self, fonte):
        self.fonte = fonte
        self.z = _zlib_bk.compressobj(6, _zlib_bk.DEFLATED, 31)  # wbits=31 → formato gzip
        self.buf = bytearray()
        self.fim = False
        self.bytes_saida = 0

    def read(self, n=-1):
        if n is None or n < 0:
            n = 16 * 1024 * 1024
        while len(self.buf) < n and not self.fim:
            bloco = self.fonte.read(1024 * 1024)
            if bloco:
                self.buf += self.z.compress(bloco)
            else:
                self.buf += self.z.flush()
                self.fim = True
        saida = bytes(self.buf[:n])
        del self.buf[:n]
        self.bytes_saida += len(saida)
        return saida


# ── Funções de backup ─────────────────────────────────────────────────────────

def _get_s3_client():
    try:
        import boto3 as _boto3
        return _boto3.client(
            "s3",
            region_name          = _BK_REGION,
            aws_access_key_id    = _os_bk.environ.get("AWS_ACCESS_KEY_ID"),
            aws_secret_access_key= _os_bk.environ.get("AWS_SECRET_ACCESS_KEY"),
        )
    except ImportError:
        print("[backup_s3] ❌ boto3 não instalado. Adicione ao requirements.txt.")
        return None


def _run_backup() -> bool:
    """Executa pg_dump, comprime e envia para S3. Retorna True se OK."""
    db_url = _os_bk.environ.get("DATABASE_URL", "")
    if not db_url.startswith("postgres"):
        print("[backup_s3] DATABASE_URL não é PostgreSQL — backup ignorado.")
        _bk_state["last_status"] = "skipped"
        return False

    # Parseia a URL para extrair componentes individuais
    # formato: postgres://user:password@host:port/dbname
    try:
        from urllib.parse import urlparse as _urlparse
        _parsed = _urlparse(db_url)
        _pg_host = _parsed.hostname or "localhost"
        _pg_port = str(_parsed.port or 5432)
        _pg_user = _parsed.username or "postgres"
        _pg_pass = _parsed.password or ""
        _pg_db   = (_parsed.path or "/postgres").lstrip("/")
        print(f"[backup_s3] Conectando em {_pg_host}:{_pg_port}/{_pg_db} como {_pg_user}")
    except Exception as _pu:
        print(f"[backup_s3] Erro ao parsear DATABASE_URL: {_pu}")
        _bk_state.update({"last_status": "error", "last_error": str(_pu)})
        return False

    s3 = _get_s3_client()
    if not s3:
        return False

    # Só um backup por vez na instância: o gunicorn roda vários workers e cada um
    # tem o próprio agendador. Quem não conseguir a trava simplesmente desiste.
    trava = open(_BK_LOCK, "w")
    try:
        _fcntl_bk.flock(trava, _fcntl_bk.LOCK_EX | _fcntl_bk.LOCK_NB)
    except BlockingIOError:
        trava.close()
        print("[backup_s3] Outro processo já está fazendo o backup — ignorando.")
        return False

    now       = _dt_bk.now(_tz_bk.utc)
    timestamp = now.strftime("%Y%m%d_%H%M%S")
    filename  = f"backup_{timestamp}.sql.gz"
    s3_key    = f"{_BK_PREFIX}/{filename}"

    print(f"[backup_s3] Iniciando backup → s3://{_BK_BUCKET}/{s3_key}")

    try:
        # ── pg_dump → gzip → S3 em streaming (sem arquivo temporário) ─────────
        # Em container, /tmp pode contar como memória; um dump inteiro ali (vezes
        # o número de workers) derrubava a instância por falta de memória.
        from boto3.s3.transfer import TransferConfig as _TransferConfig_bk
        with _tmp_bk.TemporaryFile() as _stderr_f:
            with _sp_bk.Popen(
                [
                    "pg_dump",
                    "--format=plain",
                    "--encoding=UTF8",
                    "--no-password",
                    f"--host={_pg_host}",
                    f"--port={_pg_port}",
                    f"--username={_pg_user}",
                    f"--dbname={_pg_db}",
                ],
                stdout=_sp_bk.PIPE,
                stderr=_stderr_f,
                env={**_os_bk.environ, "PGPASSWORD": _pg_pass},
            ) as _proc:
                fluxo = _GzipDoPipe(_proc.stdout)
                s3.upload_fileobj(
                    fluxo, _BK_BUCKET, s3_key,
                    ExtraArgs={"StorageClass": "STANDARD_IA"},
                    Config=_TransferConfig_bk(multipart_chunksize=16 * 1024 * 1024,
                                              max_concurrency=1, use_threads=False),
                )
                _proc.wait(timeout=600)
            if _proc.returncode != 0:
                _stderr_f.seek(0)
                err = _stderr_f.read(300).decode(errors="replace")
                try:
                    s3.delete_object(Bucket=_BK_BUCKET, Key=s3_key)  # não deixa backup incompleto no bucket
                except Exception:
                    pass
                raise RuntimeError(f"pg_dump falhou (code {_proc.returncode}): {err}")

        size_mb = fluxo.bytes_saida / 1024 / 1024
        print(f"[backup_s3] ✅ Upload OK: s3://{_BK_BUCKET}/{s3_key} ({size_mb:.1f}MB comprimido)")

        _bk_state.update({
            "last_run":     now,
            "last_status":  "ok",
            "last_file":    filename,
            "last_size_mb": round(size_mb, 2),
            "last_error":   "",
        })

        # ── Limpa backups antigos ─────────────────────────────────────────────
        _cleanup_old_backups(s3, now)
        return True

    except Exception as _e:
        err_msg = f"{type(_e).__name__}: {_e}"
        print(f"[backup_s3] ❌ Erro: {err_msg}")
        _bk_state.update({
            "last_run":    now,
            "last_status": "error",
            "last_error":  err_msg[:500],
        })
        return False

    finally:
        _fcntl_bk.flock(trava, _fcntl_bk.LOCK_UN)
        trava.close()


def _cleanup_old_backups(s3, now: _dt_bk):
    """Remove backups com mais de _BK_KEEP_DAYS dias."""
    try:
        paginator = s3.get_paginator("list_objects_v2")
        pages = paginator.paginate(Bucket=_BK_BUCKET, Prefix=_BK_PREFIX + "/")
        deleted = 0
        for page in pages:
            for obj in page.get("Contents", []):
                age_days = (now - obj["LastModified"].replace(tzinfo=_tz_bk.utc)).days
                if age_days > _BK_KEEP_DAYS:
                    s3.delete_object(Bucket=_BK_BUCKET, Key=obj["Key"])
                    deleted += 1
        if deleted:
            print(f"[backup_s3] 🗑️  {deleted} backup(s) antigo(s) removido(s).")
    except Exception as _ec:
        print(f"[backup_s3] Limpeza: {_ec}")


# ── Loop de agendamento ───────────────────────────────────────────────────────

def _backup_loop():
    """Aguarda 03:00 UTC e dispara o backup diariamente."""
    print("[backup_s3] Scheduler iniciado — backup diário às 03:00 UTC.")

    # Sem backup no boot: cada deploy/reinício disparava um dump completo em cada
    # worker, o que esgotava a memória e reiniciava a instância em ciclo.
    # Para testar, use POST /admin/backup/rodar-agora.
    while True:
        try:
            now = _dt_bk.now(_tz_bk.utc)
            # Próximo 03:00 UTC
            next_run = now.replace(hour=_BK_HOUR_UTC, minute=0, second=0, microsecond=0)
            if next_run <= now:
                from datetime import timedelta as _td_bk2
                next_run = next_run + _td_bk2(days=1)
            wait_s = (next_run - now).total_seconds()
            print(f"[backup_s3] Próximo backup em {wait_s/3600:.1f}h ({next_run.strftime('%Y-%m-%d %H:%M UTC')})")
            _time_bk.sleep(wait_s)
            _run_backup()
        except Exception as _e:
            print(f"[backup_s3] Loop erro: {_e}")
            _time_bk.sleep(3600)


_thread_bk.Thread(target=_backup_loop, daemon=True, name="backup-s3").start()


# ── Rota de status (admin) ────────────────────────────────────────────────────

@app.get("/admin/backup/status")
@require_login
async def backup_status(request: Request, session: Session = Depends(get_session)):
    ctx = get_tenant_context(request, session)
    if not ctx or ctx.membership.role not in ("admin", "owner"):
        return JSONResponse({"erro": "Sem permissão."}, status_code=403)

    state = _bk_state.copy()
    if state["last_run"]:
        state["last_run"] = state["last_run"].strftime("%Y-%m-%d %H:%M UTC")

    return JSONResponse({
        "bucket":      _BK_BUCKET,
        "regiao":      _BK_REGION,
        "historico":   f"{_BK_KEEP_DAYS} dias",
        "horario":     f"03:00 UTC (meia-noite Brasília)",
        **state,
    })


# ── Rota para forçar backup manual (admin) ────────────────────────────────────

@app.post("/admin/backup/rodar-agora")
@require_login
async def backup_rodar_agora(
    request: Request,
    session: Session = Depends(get_session),
):
    ctx = get_tenant_context(request, session)
    if not ctx or ctx.membership.role not in ("admin", "owner"):
        return JSONResponse({"ok": False, "erro": "Sem permissão."}, status_code=403)

    _thread_bk.Thread(target=_run_backup, daemon=True).start()
    return JSONResponse({"ok": True, "msg": "Backup iniciado. Verifique /admin/backup/status em 1-2 minutos."})


print("[backup_s3] ✅ Módulo de backup S3 carregado.")

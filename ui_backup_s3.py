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
import gzip     as _gzip_bk
import shutil   as _shutil_bk
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

    # pg_dump exige postgresql:// não postgres://
    if db_url.startswith("postgres://"):
        db_url = "postgresql://" + db_url[len("postgres://"):]

    s3 = _get_s3_client()
    if not s3:
        return False

    now       = _dt_bk.now(_tz_bk.utc)
    timestamp = now.strftime("%Y%m%d_%H%M%S")
    filename  = f"backup_{timestamp}.sql.gz"
    s3_key    = f"{_BK_PREFIX}/{filename}"

    print(f"[backup_s3] Iniciando backup → s3://{_BK_BUCKET}/{s3_key}")

    tmp_sql = _Path_bk(_tmp_bk.gettempdir()) / f"backup_{timestamp}.sql"
    tmp_gz  = _Path_bk(_tmp_bk.gettempdir()) / filename

    try:
        # ── pg_dump ──────────────────────────────────────────────────────────
        result = _sp_bk.run(
            ["pg_dump", "--no-password", "--format=plain", "--encoding=UTF8",
             "--dbname", db_url],
            capture_output=True,
            timeout=300,
            env={**_os_bk.environ, "PGPASSWORD": _os_bk.environ.get("PGPASSWORD", "")},
        )
        if result.returncode != 0:
            err = result.stderr.decode()[:300]
            raise RuntimeError(f"pg_dump falhou (code {result.returncode}): {err}")

        tmp_sql.write_bytes(result.stdout)
        print(f"[backup_s3] pg_dump OK: {len(result.stdout)/1024/1024:.1f}MB")

        # ── Comprime ─────────────────────────────────────────────────────────
        with open(tmp_sql, "rb") as f_in, _gzip_bk.open(tmp_gz, "wb") as f_out:
            _shutil_bk.copyfileobj(f_in, f_out)

        size_mb = tmp_gz.stat().st_size / 1024 / 1024
        print(f"[backup_s3] Comprimido: {size_mb:.1f}MB → {filename}")

        # ── Upload S3 ─────────────────────────────────────────────────────────
        s3.upload_file(
            str(tmp_gz),
            _BK_BUCKET,
            s3_key,
            ExtraArgs={"StorageClass": "STANDARD_IA"},
        )
        print(f"[backup_s3] ✅ Upload OK: s3://{_BK_BUCKET}/{s3_key}")

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
        tmp_sql.unlink(missing_ok=True)
        tmp_gz.unlink(missing_ok=True)


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

    # Roda um backup imediato na primeira inicialização se nunca rodou
    _time_bk.sleep(30)  # aguarda o app estabilizar
    print("[backup_s3] Rodando backup inicial de verificação...")
    _run_backup()

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

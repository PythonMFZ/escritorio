# ui_cloud_storage.py — Google Drive + OneDrive connectors
# Exec'd in app.py namespace — access to engine, models, helpers.
#
# Flow:
#   Admin connects their Drive/OneDrive → selects a folder per client →
#   background job syncs files every 30 min → extracted text lands in BaseConhecimento
# ─────────────────────────────────────────────────────────────────────────────

import hashlib as _hash_cs
import json as _json_cs
import os as _os_cs
import threading as _thread_cs
import time as _time_cs
from datetime import datetime as _dt_cs
from typing import Optional as _Opt_cs
from urllib.parse import urlencode as _urlencode_cs, quote as _quote_cs

import httpx as _httpx_cs
from fastapi import Request as _Req_cs, Depends as _Dep_cs, Form as _Form_cs
from fastapi.responses import JSONResponse as _JSON_cs, RedirectResponse as _RR_cs, HTMLResponse as _HTML_cs
from sqlmodel import Field as _F_cs, SQLModel as _SM_cs, select as _sel_cs, Session as _Sess_cs

# ── Env vars ──────────────────────────────────────────────────────────────────
_GDRIVE_CLIENT_ID     = _os_cs.getenv("GDRIVE_CLIENT_ID", "")
_GDRIVE_CLIENT_SECRET = _os_cs.getenv("GDRIVE_CLIENT_SECRET", "")
_ONEDRIVE_CLIENT_ID     = _os_cs.getenv("ONEDRIVE_CLIENT_ID", "")
_ONEDRIVE_CLIENT_SECRET = _os_cs.getenv("ONEDRIVE_CLIENT_SECRET", "")
_APP_BASE_URL = _os_cs.getenv("APP_BASE_URL", "https://app.maffezzollicapital.com.br")
_SYNC_INTERVAL_S = int(_os_cs.getenv("CLOUD_SYNC_INTERVAL_S", "1800"))  # 30 min


# ── Model ─────────────────────────────────────────────────────────────────────

class CloudStorageConnection(_SM_cs, table=True):
    __tablename__  = "cloudstorage_connection"
    __table_args__ = {"extend_existing": True}

    id:               _Opt_cs[int] = _F_cs(default=None, primary_key=True)
    company_id:       int          = _F_cs(index=True)
    created_by_user_id: int        = _F_cs(index=True)

    provider:         str = _F_cs(default="")          # "gdrive" | "onedrive"
    display_name:     str = _F_cs(default="")          # "Rafael - Google Drive"
    access_token:     str = _F_cs(default="")
    refresh_token:    str = _F_cs(default="")
    token_expires_at: str = _F_cs(default="")          # ISO datetime

    # Which folder to watch (root by default)
    folder_id:   str = _F_cs(default="root")
    folder_name: str = _F_cs(default="/")

    # Per-client folder mapping — JSON: {"client_id": "folder_id", ...}
    client_folders_json: str = _F_cs(default="{}")

    is_active:      bool = _F_cs(default=True, index=True)
    last_synced_at: str  = _F_cs(default="")
    created_at:     str  = _F_cs(default="")
    updated_at:     str  = _F_cs(default="")


class CloudStorageFile(_SM_cs, table=True):
    """Tracks files already indexed to avoid re-processing unchanged files."""
    __tablename__  = "cloudstorage_file"
    __table_args__ = {"extend_existing": True}

    id:            _Opt_cs[int] = _F_cs(default=None, primary_key=True)
    connection_id: int          = _F_cs(index=True)
    company_id:    int          = _F_cs(index=True)
    client_id:     int          = _F_cs(index=True)
    file_id:       str          = _F_cs(index=True, default="")   # drive file id
    file_name:     str          = _F_cs(default="")
    file_hash:     str          = _F_cs(default="")               # md5/sha1
    modified_at:   str          = _F_cs(default="")
    doc_id:        _Opt_cs[int] = _F_cs(default=None)             # BaseConhecimento.id
    indexed_at:    str          = _F_cs(default="")


def _ensure_cs_tables():
    for tbl in (CloudStorageConnection.__table__, CloudStorageFile.__table__):
        try:
            tbl.create(engine, checkfirst=True)
        except Exception:
            pass


# ── OAuth helpers ─────────────────────────────────────────────────────────────

def _gdrive_auth_url(state: str) -> str:
    params = {
        "client_id":     _GDRIVE_CLIENT_ID,
        "redirect_uri":  f"{_APP_BASE_URL}/integrations/gdrive/callback",
        "response_type": "code",
        "scope":         "https://www.googleapis.com/auth/drive.readonly",
        "access_type":   "offline",
        "prompt":        "consent",
        "state":         state,
    }
    return "https://accounts.google.com/o/oauth2/v2/auth?" + _urlencode_cs(params)


def _gdrive_exchange_code(code: str) -> dict:
    r = _httpx_cs.post("https://oauth2.googleapis.com/token", data={
        "code":          code,
        "client_id":     _GDRIVE_CLIENT_ID,
        "client_secret": _GDRIVE_CLIENT_SECRET,
        "redirect_uri":  f"{_APP_BASE_URL}/integrations/gdrive/callback",
        "grant_type":    "authorization_code",
    }, timeout=15)
    return r.json()


def _gdrive_refresh(refresh_token: str) -> dict:
    r = _httpx_cs.post("https://oauth2.googleapis.com/token", data={
        "refresh_token": refresh_token,
        "client_id":     _GDRIVE_CLIENT_ID,
        "client_secret": _GDRIVE_CLIENT_SECRET,
        "grant_type":    "refresh_token",
    }, timeout=15)
    return r.json()


def _onedrive_auth_url(state: str) -> str:
    params = {
        "client_id":     _ONEDRIVE_CLIENT_ID,
        "redirect_uri":  f"{_APP_BASE_URL}/integrations/onedrive/callback",
        "response_type": "code",
        "scope":         "Files.Read offline_access",
        "state":         state,
    }
    return "https://login.microsoftonline.com/common/oauth2/v2.0/authorize?" + _urlencode_cs(params)


def _onedrive_exchange_code(code: str) -> dict:
    r = _httpx_cs.post(
        "https://login.microsoftonline.com/common/oauth2/v2.0/token",
        data={
            "code":          code,
            "client_id":     _ONEDRIVE_CLIENT_ID,
            "client_secret": _ONEDRIVE_CLIENT_SECRET,
            "redirect_uri":  f"{_APP_BASE_URL}/integrations/onedrive/callback",
            "grant_type":    "authorization_code",
        }, timeout=15)
    return r.json()


def _onedrive_refresh(refresh_token: str) -> dict:
    r = _httpx_cs.post(
        "https://login.microsoftonline.com/common/oauth2/v2.0/token",
        data={
            "refresh_token": refresh_token,
            "client_id":     _ONEDRIVE_CLIENT_ID,
            "client_secret": _ONEDRIVE_CLIENT_SECRET,
            "grant_type":    "refresh_token",
        }, timeout=15)
    return r.json()


def _cs_get_valid_token(session, conn: CloudStorageConnection) -> str:
    """Return a valid access token, refreshing if needed."""
    expires = conn.token_expires_at
    needs_refresh = True
    if expires:
        try:
            exp = _dt_cs.fromisoformat(expires)
            needs_refresh = (_dt_cs.utcnow() - exp).total_seconds() > -120
        except Exception:
            pass

    if not needs_refresh:
        return conn.access_token

    try:
        if conn.provider == "gdrive":
            data = _gdrive_refresh(conn.refresh_token)
        else:
            data = _onedrive_refresh(conn.refresh_token)

        if "access_token" in data:
            conn.access_token = data["access_token"]
            expires_in = int(data.get("expires_in", 3600))
            from datetime import timedelta as _td
            conn.token_expires_at = (_dt_cs.utcnow() + _td(seconds=expires_in)).isoformat()
            if data.get("refresh_token"):
                conn.refresh_token = data["refresh_token"]
            conn.updated_at = _dt_cs.utcnow().isoformat()
            session.add(conn)
            session.commit()
            return conn.access_token
    except Exception as _e:
        print(f"[cs] token refresh erro ({conn.provider}): {_e}")

    return conn.access_token


# ── Drive API calls ───────────────────────────────────────────────────────────

def _gdrive_list_files(token: str, folder_id: str) -> list[dict]:
    """List files in a Google Drive folder (non-recursive, supported types only)."""
    supported_mime = (
        "application/pdf",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/vnd.ms-excel",
        "text/csv",
        "text/plain",
        "image/jpeg", "image/png",
    )
    q = f"'{folder_id}' in parents and trashed=false and ("
    q += " or ".join(f"mimeType='{m}'" for m in supported_mime)
    q += ")"
    r = _httpx_cs.get(
        "https://www.googleapis.com/drive/v3/files",
        params={"q": q, "fields": "files(id,name,mimeType,modifiedTime,md5Checksum)", "pageSize": 100},
        headers={"Authorization": f"Bearer {token}"},
        timeout=20,
    )
    return r.json().get("files", [])


def _gdrive_list_folders(token: str, folder_id: str = "root") -> list[dict]:
    q = f"'{folder_id}' in parents and trashed=false and mimeType='application/vnd.google-apps.folder'"
    r = _httpx_cs.get(
        "https://www.googleapis.com/drive/v3/files",
        params={"q": q, "fields": "files(id,name)", "pageSize": 50},
        headers={"Authorization": f"Bearer {token}"},
        timeout=15,
    )
    return r.json().get("files", [])


def _gdrive_download(token: str, file_id: str) -> bytes:
    r = _httpx_cs.get(
        f"https://www.googleapis.com/drive/v3/files/{file_id}?alt=media",
        headers={"Authorization": f"Bearer {token}"},
        timeout=60,
    )
    return r.content


def _onedrive_list_files(token: str, folder_id: str) -> list[dict]:
    if folder_id in ("root", ""):
        url = "https://graph.microsoft.com/v1.0/me/drive/root/children"
    else:
        url = f"https://graph.microsoft.com/v1.0/me/drive/items/{folder_id}/children"
    r = _httpx_cs.get(
        url,
        params={"$select": "id,name,file,lastModifiedDateTime,@microsoft.graph.downloadUrl", "$top": 100},
        headers={"Authorization": f"Bearer {token}"},
        timeout=20,
    )
    items = r.json().get("value", [])
    supported_ext = {".pdf", ".xlsx", ".xls", ".csv", ".txt", ".jpg", ".jpeg", ".png"}
    return [
        {
            "id": i["id"],
            "name": i["name"],
            "mimeType": i.get("file", {}).get("mimeType", ""),
            "modifiedTime": i.get("lastModifiedDateTime", ""),
            "downloadUrl": i.get("@microsoft.graph.downloadUrl", ""),
        }
        for i in items
        if "file" in i and any(i["name"].lower().endswith(ext) for ext in supported_ext)
    ]


def _onedrive_list_folders(token: str, folder_id: str = "root") -> list[dict]:
    if folder_id in ("root", ""):
        url = "https://graph.microsoft.com/v1.0/me/drive/root/children"
    else:
        url = f"https://graph.microsoft.com/v1.0/me/drive/items/{folder_id}/children"
    r = _httpx_cs.get(
        url,
        params={"$select": "id,name,folder", "$filter": "folder ne null", "$top": 50},
        headers={"Authorization": f"Bearer {token}"},
        timeout=15,
    )
    return [
        {"id": i["id"], "name": i["name"]}
        for i in r.json().get("value", [])
        if "folder" in i
    ]


def _onedrive_download(token: str, file_id: str, download_url: str = "") -> bytes:
    if download_url:
        r = _httpx_cs.get(download_url, timeout=60)
    else:
        r = _httpx_cs.get(
            f"https://graph.microsoft.com/v1.0/me/drive/items/{file_id}/content",
            headers={"Authorization": f"Bearer {token}"},
            follow_redirects=True,
            timeout=60,
        )
    return r.content


# ── Extraction (reuse knowledge base helpers) ─────────────────────────────────

def _cs_extract_content(file_bytes: bytes, filename: str, mime_type: str) -> str:
    """Extract text from a file using existing KB extraction functions."""
    fname = filename.lower()
    if fname.endswith((".xlsx", ".xls")) or "spreadsheet" in mime_type or "excel" in mime_type:
        return _bc_extract_excel(file_bytes, fname)
    elif fname.endswith(".csv") or mime_type in ("text/csv", "text/plain"):
        return file_bytes.decode("utf-8", errors="replace")
    elif fname.endswith(".txt"):
        return file_bytes.decode("utf-8", errors="replace")
    elif fname.endswith(".pdf") or mime_type == "application/pdf":
        return _bc_extract_claude(file_bytes, "application/pdf")
    elif any(fname.endswith(ext) for ext in (".jpg", ".jpeg", ".png")):
        img_mime = mime_type if mime_type.startswith("image/") else "image/jpeg"
        return _bc_extract_claude(file_bytes, img_mime)
    return ""


# ── Sync logic ────────────────────────────────────────────────────────────────

def _cs_sync_connection(session, conn: CloudStorageConnection) -> int:
    """Sync one connection. Returns count of files indexed."""
    token = _cs_get_valid_token(session, conn)
    if not token:
        print(f"[cs] sem token para conexão {conn.id}")
        return 0

    # Load per-client folder map
    try:
        client_folders = _json_cs.loads(conn.client_folders_json or "{}")
    except Exception:
        client_folders = {}

    indexed = 0

    # Build list of (client_id, folder_id) pairs to sync
    pairs = []
    if client_folders:
        for cid_str, fid in client_folders.items():
            pairs.append((int(cid_str), fid))
    else:
        # No per-client mapping — sync root folder, no client association
        print(f"[cs] conexão {conn.id} sem mapeamento de clientes — configure em /integrations")
        return 0

    for client_id, folder_id in pairs:
        try:
            if conn.provider == "gdrive":
                files = _gdrive_list_files(token, folder_id)
            else:
                files = _onedrive_list_files(token, folder_id)
        except Exception as _e:
            print(f"[cs] erro ao listar arquivos ({conn.provider}, folder {folder_id}): {_e}")
            continue

        for f in files:
            file_id   = f["id"]
            file_name = f["name"]
            mod_time  = f.get("modifiedTime", "")
            file_hash = f.get("md5Checksum", "")

            # Check if already indexed with same hash/mod time
            existing = session.exec(
                _sel_cs(CloudStorageFile).where(
                    CloudStorageFile.connection_id == conn.id,
                    CloudStorageFile.file_id == file_id,
                )
            ).first()

            fingerprint = file_hash or mod_time
            if existing and existing.file_hash == fingerprint:
                continue  # unchanged, skip

            # Download
            try:
                if conn.provider == "gdrive":
                    file_bytes = _gdrive_download(token, file_id)
                else:
                    file_bytes = _onedrive_download(token, file_id, f.get("downloadUrl", ""))
            except Exception as _e:
                print(f"[cs] erro ao baixar {file_name}: {_e}")
                continue

            if not file_bytes:
                continue

            # Extract
            mime = f.get("mimeType", "")
            content = _cs_extract_content(file_bytes, file_name, mime)
            if not content:
                print(f"[cs] sem conteúdo extraído de {file_name}")
                continue

            # Save/update in BaseConhecimento
            try:
                if existing and existing.doc_id:
                    from sqlmodel import Session as _S2
                    doc = session.get(BaseConhecimento, existing.doc_id)
                    if doc:
                        doc.conteudo_texto = content[:200_000]
                        doc.nome = file_name
                        session.add(doc)
                        session.commit()
                        doc_id = doc.id
                    else:
                        existing = None

                if not existing or not existing.doc_id:
                    doc = BaseConhecimento(
                        company_id=conn.company_id,
                        client_id=client_id,
                        user_id=conn.created_by_user_id,
                        nome=file_name,
                        descricao=f"Sincronizado do {conn.provider} — {conn.display_name}",
                        tipo=conn.provider,
                        conteudo_texto=content[:200_000],
                        created_at=_dt_cs.utcnow().isoformat(),
                    )
                    session.add(doc)
                    session.commit()
                    session.refresh(doc)
                    doc_id = doc.id

                # Track file
                if existing:
                    existing.file_hash  = fingerprint
                    existing.modified_at = mod_time
                    existing.indexed_at = _dt_cs.utcnow().isoformat()
                    session.add(existing)
                else:
                    session.add(CloudStorageFile(
                        connection_id=conn.id,
                        company_id=conn.company_id,
                        client_id=client_id,
                        file_id=file_id,
                        file_name=file_name,
                        file_hash=fingerprint,
                        modified_at=mod_time,
                        doc_id=doc_id,
                        indexed_at=_dt_cs.utcnow().isoformat(),
                    ))
                session.commit()
                indexed += 1
                print(f"[cs] indexado: {file_name} (cliente {client_id})")

            except Exception as _e:
                print(f"[cs] erro ao salvar {file_name}: {_e}")
                session.rollback()

    conn.last_synced_at = _dt_cs.utcnow().isoformat()
    session.add(conn)
    session.commit()
    return indexed


def _cs_sync_all():
    """Sync all active connections. Runs in background thread."""
    with _Sess_cs(engine) as session:
        conns = session.exec(
            _sel_cs(CloudStorageConnection).where(CloudStorageConnection.is_active == True)
        ).all()
        for conn in conns:
            try:
                n = _cs_sync_connection(session, conn)
                if n:
                    print(f"[cs] sync {conn.provider}/{conn.display_name}: {n} arquivo(s) indexado(s)")
            except Exception as _e:
                print(f"[cs] sync erro conexão {conn.id}: {_e}")


def _cs_background_loop():
    _time_cs.sleep(30)  # startup delay
    while True:
        try:
            _cs_sync_all()
        except Exception as _e:
            print(f"[cs] background loop erro: {_e}")
        _time_cs.sleep(_SYNC_INTERVAL_S)


# ── Routes ────────────────────────────────────────────────────────────────────

# ── Google Drive OAuth ────────────────────────────────────────────────────────

@app.get("/integrations/gdrive/connect")
@require_role({"admin", "equipe"})
async def gdrive_connect(request: _Req_cs):
    if not _GDRIVE_CLIENT_ID:
        set_flash(request, "GDRIVE_CLIENT_ID não configurado. Adicione nas variáveis de ambiente do Render.")
        return _RR_cs("/integrations", status_code=303)
    state = request.session.get("user_id", "0")
    return _RR_cs(_gdrive_auth_url(str(state)), status_code=302)


@app.get("/integrations/gdrive/callback")
@require_role({"admin", "equipe"})
async def gdrive_callback(
    request: _Req_cs,
    session=_Dep_cs(get_session),
    code: str = "",
    error: str = "",
):
    ctx = get_tenant_context(request, session)
    if not ctx:
        return _RR_cs("/login", status_code=303)
    if error or not code:
        set_flash(request, f"Google Drive: autorização negada ({error or 'sem código'}).")
        return _RR_cs("/integrations", status_code=303)
    try:
        data = _gdrive_exchange_code(code)
        if "error" in data:
            set_flash(request, f"Google Drive erro: {data['error_description']}")
            return _RR_cs("/integrations", status_code=303)
        from datetime import timedelta as _td2
        expires_at = (_dt_cs.utcnow() + _td2(seconds=int(data.get("expires_in", 3600)))).isoformat()
        conn = CloudStorageConnection(
            company_id=ctx.company.id,
            created_by_user_id=ctx.user.id,
            provider="gdrive",
            display_name=f"Google Drive — {ctx.user.name}",
            access_token=data.get("access_token", ""),
            refresh_token=data.get("refresh_token", ""),
            token_expires_at=expires_at,
            folder_id="root",
            folder_name="/",
            is_active=True,
            created_at=_dt_cs.utcnow().isoformat(),
            updated_at=_dt_cs.utcnow().isoformat(),
        )
        session.add(conn)
        session.commit()
        set_flash(request, "Google Drive conectado! Agora configure as pastas por cliente.")
    except Exception as _e:
        set_flash(request, f"Erro ao conectar Google Drive: {_e}")
    return _RR_cs("/integrations", status_code=303)


# ── OneDrive OAuth ────────────────────────────────────────────────────────────

@app.get("/integrations/onedrive/connect")
@require_role({"admin", "equipe"})
async def onedrive_connect(request: _Req_cs):
    if not _ONEDRIVE_CLIENT_ID:
        set_flash(request, "ONEDRIVE_CLIENT_ID não configurado. Adicione nas variáveis de ambiente do Render.")
        return _RR_cs("/integrations", status_code=303)
    state = request.session.get("user_id", "0")
    return _RR_cs(_onedrive_auth_url(str(state)), status_code=302)


@app.get("/integrations/onedrive/callback")
@require_role({"admin", "equipe"})
async def onedrive_callback(
    request: _Req_cs,
    session=_Dep_cs(get_session),
    code: str = "",
    error: str = "",
):
    ctx = get_tenant_context(request, session)
    if not ctx:
        return _RR_cs("/login", status_code=303)
    if error or not code:
        set_flash(request, f"OneDrive: autorização negada ({error or 'sem código'}).")
        return _RR_cs("/integrations", status_code=303)
    try:
        data = _onedrive_exchange_code(code)
        if "error" in data:
            set_flash(request, f"OneDrive erro: {data.get('error_description', data.get('error'))}")
            return _RR_cs("/integrations", status_code=303)
        from datetime import timedelta as _td3
        expires_at = (_dt_cs.utcnow() + _td3(seconds=int(data.get("expires_in", 3600)))).isoformat()
        conn = CloudStorageConnection(
            company_id=ctx.company.id,
            created_by_user_id=ctx.user.id,
            provider="onedrive",
            display_name=f"OneDrive — {ctx.user.name}",
            access_token=data.get("access_token", ""),
            refresh_token=data.get("refresh_token", ""),
            token_expires_at=expires_at,
            folder_id="root",
            folder_name="/",
            is_active=True,
            created_at=_dt_cs.utcnow().isoformat(),
            updated_at=_dt_cs.utcnow().isoformat(),
        )
        session.add(conn)
        session.commit()
        set_flash(request, "OneDrive conectado! Agora configure as pastas por cliente.")
    except Exception as _e:
        set_flash(request, f"Erro ao conectar OneDrive: {_e}")
    return _RR_cs("/integrations", status_code=303)


# ── API: list folders ─────────────────────────────────────────────────────────

@app.get("/api/integrations/{conn_id}/folders")
@require_role({"admin", "equipe"})
async def cs_list_folders(conn_id: int, request: _Req_cs, session=_Dep_cs(get_session), parent: str = "root"):
    ctx = get_tenant_context(request, session)
    if not ctx:
        return _JSON_cs({"folders": []})
    conn = session.get(CloudStorageConnection, conn_id)
    if not conn or conn.company_id != ctx.company.id:
        return _JSON_cs({"folders": [], "erro": "Conexão não encontrada."})
    token = _cs_get_valid_token(session, conn)
    try:
        if conn.provider == "gdrive":
            folders = _gdrive_list_folders(token, parent)
        else:
            folders = _onedrive_list_folders(token, parent)
        return _JSON_cs({"folders": folders})
    except Exception as _e:
        return _JSON_cs({"folders": [], "erro": str(_e)})


# ── API: set client→folder mapping ───────────────────────────────────────────

@app.post("/api/integrations/{conn_id}/map-client")
@require_role({"admin", "equipe"})
async def cs_map_client(
    conn_id: int,
    request: _Req_cs,
    session=_Dep_cs(get_session),
    client_id: int = _Form_cs(...),
    folder_id: str = _Form_cs(...),
    folder_name: str = _Form_cs(""),
):
    ctx = get_tenant_context(request, session)
    if not ctx:
        return _JSON_cs({"ok": False})
    conn = session.get(CloudStorageConnection, conn_id)
    if not conn or conn.company_id != ctx.company.id:
        return _JSON_cs({"ok": False, "erro": "Conexão não encontrada."})
    try:
        mapping = _json_cs.loads(conn.client_folders_json or "{}")
    except Exception:
        mapping = {}
    mapping[str(client_id)] = folder_id
    conn.client_folders_json = _json_cs.dumps(mapping)
    conn.updated_at = _dt_cs.utcnow().isoformat()
    session.add(conn)
    session.commit()
    return _JSON_cs({"ok": True, "mapping": mapping})


# ── API: sync now ─────────────────────────────────────────────────────────────

@app.post("/api/integrations/{conn_id}/sync")
@require_role({"admin", "equipe"})
async def cs_sync_now(conn_id: int, request: _Req_cs, session=_Dep_cs(get_session)):
    ctx = get_tenant_context(request, session)
    if not ctx:
        return _JSON_cs({"ok": False})
    conn = session.get(CloudStorageConnection, conn_id)
    if not conn or conn.company_id != ctx.company.id:
        return _JSON_cs({"ok": False, "erro": "Conexão não encontrada."})
    try:
        n = _cs_sync_connection(session, conn)
        return _JSON_cs({"ok": True, "indexed": n})
    except Exception as _e:
        return _JSON_cs({"ok": False, "erro": str(_e)})


# ── API: disconnect ───────────────────────────────────────────────────────────

@app.post("/api/integrations/{conn_id}/disconnect")
@require_role({"admin", "equipe"})
async def cs_disconnect(conn_id: int, request: _Req_cs, session=_Dep_cs(get_session)):
    ctx = get_tenant_context(request, session)
    if not ctx:
        return _JSON_cs({"ok": False})
    conn = session.get(CloudStorageConnection, conn_id)
    if not conn or conn.company_id != ctx.company.id:
        return _JSON_cs({"ok": False})
    conn.is_active = False
    conn.access_token = ""
    conn.refresh_token = ""
    session.add(conn)
    session.commit()
    set_flash(request, f"{conn.display_name} desconectado.")
    return _RR_cs("/integrations", status_code=303)


# ── Page: /integrations ───────────────────────────────────────────────────────

_CS_PAGE = r"""
<!doctype html><html lang="pt-BR"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Integrações — Maffezzolli</title>
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css">
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.3/font/bootstrap-icons.min.css">
</head><body class="bg-light">
<div class="container py-4" style="max-width:820px">
  <div class="d-flex align-items-center gap-3 mb-4">
    <a href="/" class="btn btn-sm btn-outline-secondary"><i class="bi bi-arrow-left"></i></a>
    <div>
      <h4 class="mb-0">Integrações de Armazenamento</h4>
      <p class="text-muted small mb-0">Conecte seus drives para o Augur ler arquivos dos clientes automaticamente.</p>
    </div>
  </div>

  {% if flash %}<div class="alert alert-info alert-dismissible fade show">
    <button type="button" class="btn-close" data-bs-dismiss="alert"></button>{{ flash }}</div>{% endif %}

  <!-- Connect buttons -->
  <div class="row g-3 mb-4">
    <div class="col-md-6">
      <div class="card h-100">
        <div class="card-body d-flex flex-column">
          <div class="d-flex align-items-center gap-2 mb-2">
            <img src="https://www.gstatic.com/images/branding/product/1x/drive_2020q4_48dp.png" width="32" height="32" alt="">
            <h6 class="mb-0">Google Drive</h6>
          </div>
          <p class="text-muted small flex-grow-1">Lê PDFs, planilhas e imagens das pastas que você autorizar.</p>
          {% if gdrive_ok %}
            <span class="badge text-bg-success mb-2"><i class="bi bi-check-circle me-1"></i>Credenciais configuradas</span>
          {% else %}
            <span class="badge text-bg-warning mb-2"><i class="bi bi-exclamation-triangle me-1"></i>Configure GDRIVE_CLIENT_ID no Render</span>
          {% endif %}
          <a href="/integrations/gdrive/connect" class="btn btn-outline-primary btn-sm {% if not gdrive_ok %}disabled{% endif %}">
            <i class="bi bi-plus-circle me-1"></i>Conectar conta Google
          </a>
        </div>
      </div>
    </div>
    <div class="col-md-6">
      <div class="card h-100">
        <div class="card-body d-flex flex-column">
          <div class="d-flex align-items-center gap-2 mb-2">
            <img src="https://upload.wikimedia.org/wikipedia/commons/thumb/3/3c/Microsoft_Office_OneDrive_%282019%E2%80%93present%29.svg/2048px-Microsoft_Office_OneDrive_%282019%E2%80%93present%29.svg.png" width="32" height="32" alt="">
            <h6 class="mb-0">OneDrive</h6>
          </div>
          <p class="text-muted small flex-grow-1">Lê arquivos do seu OneDrive pessoal ou corporativo.</p>
          {% if onedrive_ok %}
            <span class="badge text-bg-success mb-2"><i class="bi bi-check-circle me-1"></i>Credenciais configuradas</span>
          {% else %}
            <span class="badge text-bg-warning mb-2"><i class="bi bi-exclamation-triangle me-1"></i>Configure ONEDRIVE_CLIENT_ID no Render</span>
          {% endif %}
          <a href="/integrations/onedrive/connect" class="btn btn-outline-primary btn-sm {% if not onedrive_ok %}disabled{% endif %}">
            <i class="bi bi-plus-circle me-1"></i>Conectar conta Microsoft
          </a>
        </div>
      </div>
    </div>
  </div>

  <!-- Active connections -->
  <h6 class="mb-3">Contas conectadas</h6>
  {% if not conns %}
    <div class="text-muted small">Nenhuma conta conectada ainda.</div>
  {% endif %}
  {% for conn in conns %}
  <div class="card mb-3">
    <div class="card-body">
      <div class="d-flex justify-content-between align-items-start">
        <div>
          <div class="fw-semibold">
            {% if conn.provider == 'gdrive' %}<i class="bi bi-google text-danger me-1"></i>{% else %}<i class="bi bi-microsoft text-primary me-1"></i>{% endif %}
            {{ conn.display_name }}
          </div>
          <div class="text-muted small mt-1">
            Última sync: {{ conn.last_synced_at[:16] if conn.last_synced_at else 'Nunca' }}
            &nbsp;·&nbsp; Pasta raiz: {{ conn.folder_name }}
          </div>
        </div>
        <div class="d-flex gap-2">
          <button class="btn btn-sm btn-outline-success" onclick="syncNow({{ conn.id }}, this)">
            <i class="bi bi-arrow-clockwise me-1"></i>Sync agora
          </button>
          <form method="post" action="/api/integrations/{{ conn.id }}/disconnect"
                onsubmit="return confirm('Desconectar {{ conn.display_name }}?')">
            <button class="btn btn-sm btn-outline-danger"><i class="bi bi-x-circle me-1"></i>Desconectar</button>
          </form>
        </div>
      </div>

      <!-- Client folder mapping -->
      <hr class="my-3">
      <div class="fw-semibold small mb-2">Pastas por cliente</div>
      <div class="text-muted small mb-2">Associe cada cliente a uma pasta do drive. O Augur lerá os arquivos dessa pasta para responder sobre aquele cliente.</div>

      <div id="mapping-{{ conn.id }}" class="row g-2 mb-3">
        {% for client in clients %}
        {% set fid = conn_mappings[conn.id|string].get(client.id|string, '') %}
        <div class="col-12">
          <div class="d-flex align-items-center gap-2">
            <span class="small fw-semibold" style="min-width:160px">{{ client.name[:25] }}</span>
            <select class="form-select form-select-sm" id="sel-{{ conn.id }}-{{ client.id }}"
                    style="max-width:240px" onchange="saveMapping({{ conn.id }}, {{ client.id }}, this.value, this.options[this.selectedIndex].text)">
              <option value="">(sem pasta)</option>
              {% for folder in conn_folders.get(conn.id|string, []) %}
              <option value="{{ folder.id }}" {% if folder.id == fid %}selected{% endif %}>📁 {{ folder.name }}</option>
              {% endfor %}
            </select>
            {% if fid %}<span class="badge text-bg-success small">✓ mapeado</span>{% endif %}
          </div>
        </div>
        {% endfor %}
      </div>
    </div>
  </div>
  {% endfor %}
</div>

<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/js/bootstrap.bundle.min.js"></script>
<script>
async function syncNow(connId, btn) {
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>Sincronizando…';
  try {
    const r = await fetch(`/api/integrations/${connId}/sync`, {method:'POST', credentials:'same-origin'});
    const d = await r.json();
    btn.innerHTML = d.ok ? `<i class="bi bi-check me-1"></i>${d.indexed} arquivo(s)` : '⚠️ Erro';
    setTimeout(() => { btn.innerHTML='<i class="bi bi-arrow-clockwise me-1"></i>Sync agora'; btn.disabled=false; }, 3000);
  } catch(e) {
    btn.innerHTML = '⚠️ Erro'; btn.disabled=false;
  }
}

async function saveMapping(connId, clientId, folderId, folderName) {
  const fd = new FormData();
  fd.append('client_id', clientId);
  fd.append('folder_id', folderId);
  fd.append('folder_name', folderName || '/');
  await fetch(`/api/integrations/${connId}/map-client`, {method:'POST', credentials:'same-origin', body:fd});
}
</script>
</body></html>
"""


@app.get("/integrations", response_class=_HTML_cs)
@require_role({"admin", "equipe"})
async def integrations_page(request: _Req_cs, session=_Dep_cs(get_session)):
    ctx = get_tenant_context(request, session)
    if not ctx:
        return _RR_cs("/login", status_code=303)

    flash = request.session.pop("flash", None)

    conns = session.exec(
        _sel_cs(CloudStorageConnection).where(
            CloudStorageConnection.company_id == ctx.company.id,
            CloudStorageConnection.is_active == True,
        )
    ).all()

    clients = session.exec(
        _sel_cs(Client).where(Client.company_id == ctx.company.id)
    ).all()

    # Per-connection: parse mapping + prefetch folder list
    conn_mappings = {}
    conn_folders  = {}
    for conn in conns:
        try:
            conn_mappings[str(conn.id)] = _json_cs.loads(conn.client_folders_json or "{}")
        except Exception:
            conn_mappings[str(conn.id)] = {}
        try:
            token = _cs_get_valid_token(session, conn)
            if conn.provider == "gdrive":
                folders = _gdrive_list_folders(token, "root")
            else:
                folders = _onedrive_list_folders(token, "root")
            conn_folders[str(conn.id)] = folders
        except Exception:
            conn_folders[str(conn.id)] = []

    from jinja2 import Environment as _JEnv
    env = _JEnv()
    tmpl = env.from_string(_CS_PAGE)
    html = tmpl.render(
        flash=flash,
        conns=conns,
        clients=clients,
        conn_mappings=conn_mappings,
        conn_folders=conn_folders,
        gdrive_ok=bool(_GDRIVE_CLIENT_ID),
        onedrive_ok=bool(_ONEDRIVE_CLIENT_ID),
    )
    return _HTML_cs(html)


# ── Startup ───────────────────────────────────────────────────────────────────

@app.on_event("startup")
def _startup_cloud_storage():
    _ensure_cs_tables()
    t = _thread_cs.Thread(target=_cs_background_loop, daemon=True)
    t.start()
    print("[cs] conector de armazenamento em nuvem iniciado")

# ui_cloud_storage.py — Google Drive + OneDrive connectors
# Exec'd in app.py namespace — access to engine, models, helpers.
#
# After OAuth the user lands on a file/folder browser to pick exactly
# which folders or files to sync into the knowledge base, and for which client.
# ─────────────────────────────────────────────────────────────────────────────

import hashlib as _hash_cs
import json as _json_cs
import os as _os_cs
import threading as _thread_cs
import time as _time_cs
from datetime import datetime as _dt_cs
from typing import Optional as _Opt_cs
from urllib.parse import urlencode as _urlencode_cs

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


# ── Models ────────────────────────────────────────────────────────────────────

class CloudStorageConnection(_SM_cs, table=True):
    __tablename__  = "cloudstorage_connection"
    __table_args__ = {"extend_existing": True}

    id:               _Opt_cs[int] = _F_cs(default=None, primary_key=True)
    company_id:       int          = _F_cs(index=True)
    created_by_user_id: int        = _F_cs(index=True)

    provider:         str = _F_cs(default="")          # "gdrive" | "onedrive"
    display_name:     str = _F_cs(default="")
    access_token:     str = _F_cs(default="")
    refresh_token:    str = _F_cs(default="")
    token_expires_at: str = _F_cs(default="")

    folder_id:   str = _F_cs(default="root")
    folder_name: str = _F_cs(default="/")

    # Selections JSON — array of {type, id, name, path, client_id}
    client_folders_json: str = _F_cs(default="[]")

    is_active:      bool = _F_cs(default=True, index=True)
    last_synced_at: str  = _F_cs(default="")
    created_at:     str  = _F_cs(default="")
    updated_at:     str  = _F_cs(default="")


class CloudStorageFile(_SM_cs, table=True):
    __tablename__  = "cloudstorage_file"
    __table_args__ = {"extend_existing": True}

    id:            _Opt_cs[int] = _F_cs(default=None, primary_key=True)
    connection_id: int          = _F_cs(index=True)
    company_id:    int          = _F_cs(index=True)
    client_id:     int          = _F_cs(index=True)
    file_id:       str          = _F_cs(index=True, default="")
    file_name:     str          = _F_cs(default="")
    file_hash:     str          = _F_cs(default="")
    modified_at:   str          = _F_cs(default="")
    doc_id:        _Opt_cs[int] = _F_cs(default=None)
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

_GDRIVE_SUPPORTED_MIME = (
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/msword",
    "text/csv",
    "text/plain",
    "image/jpeg", "image/png",
)

_ONEDRIVE_SUPPORTED_EXT = {".pdf", ".xlsx", ".xls", ".doc", ".docx", ".csv", ".txt", ".jpg", ".jpeg", ".png"}


def _gdrive_list_items(token: str, folder_id: str = "root") -> list[dict]:
    """List folders + supported files inside a Google Drive folder."""
    supported = list(_GDRIVE_SUPPORTED_MIME) + ["application/vnd.google-apps.folder"]
    q = f"'{folder_id}' in parents and trashed=false and ("
    q += " or ".join(f"mimeType='{m}'" for m in supported)
    q += ")"
    r = _httpx_cs.get(
        "https://www.googleapis.com/drive/v3/files",
        params={"q": q, "fields": "files(id,name,mimeType,modifiedTime,md5Checksum)",
                "pageSize": 50, "orderBy": "folder,name"},
        headers={"Authorization": f"Bearer {token}"},
        timeout=20,
    )
    result = []
    for item in r.json().get("files", []):
        is_folder = item["mimeType"] == "application/vnd.google-apps.folder"
        result.append({
            "id": item["id"],
            "name": item["name"],
            "type": "folder" if is_folder else "file",
            "mimeType": item.get("mimeType", ""),
            "modifiedTime": item.get("modifiedTime", ""),
            "md5Checksum": item.get("md5Checksum", ""),
        })
    return result


def _gdrive_search_items(token: str, query: str) -> list[dict]:
    """Search Google Drive by name across all folders."""
    supported = list(_GDRIVE_SUPPORTED_MIME) + ["application/vnd.google-apps.folder"]
    q = f"name contains '{query.replace(chr(39), '')}' and trashed=false and ("
    q += " or ".join(f"mimeType='{m}'" for m in supported)
    q += ")"
    r = _httpx_cs.get(
        "https://www.googleapis.com/drive/v3/files",
        params={"q": q, "fields": "files(id,name,mimeType,modifiedTime,md5Checksum)",
                "pageSize": 30, "orderBy": "folder,name"},
        headers={"Authorization": f"Bearer {token}"},
        timeout=20,
    )
    result = []
    for item in r.json().get("files", []):
        is_folder = item["mimeType"] == "application/vnd.google-apps.folder"
        result.append({
            "id": item["id"],
            "name": item["name"],
            "type": "folder" if is_folder else "file",
            "mimeType": item.get("mimeType", ""),
            "modifiedTime": item.get("modifiedTime", ""),
            "md5Checksum": item.get("md5Checksum", ""),
        })
    return result


def _gdrive_list_files(token: str, folder_id: str) -> list[dict]:
    """List only supported files in a Google Drive folder (for sync)."""
    q = f"'{folder_id}' in parents and trashed=false and ("
    q += " or ".join(f"mimeType='{m}'" for m in _GDRIVE_SUPPORTED_MIME)
    q += ")"
    r = _httpx_cs.get(
        "https://www.googleapis.com/drive/v3/files",
        params={"q": q, "fields": "files(id,name,mimeType,modifiedTime,md5Checksum)", "pageSize": 200},
        headers={"Authorization": f"Bearer {token}"},
        timeout=20,
    )
    files = r.json().get("files", [])
    return [{"id": f["id"], "name": f["name"], "mimeType": f.get("mimeType",""),
             "modifiedTime": f.get("modifiedTime",""), "md5Checksum": f.get("md5Checksum","")}
            for f in files]


def _gdrive_download(token: str, file_id: str) -> bytes:
    r = _httpx_cs.get(
        f"https://www.googleapis.com/drive/v3/files/{file_id}?alt=media",
        headers={"Authorization": f"Bearer {token}"},
        timeout=60,
    )
    return r.content


def _onedrive_list_items(token: str, folder_id: str = "root") -> list[dict]:
    """List folders + supported files inside a OneDrive folder."""
    if folder_id in ("root", ""):
        url = "https://graph.microsoft.com/v1.0/me/drive/root/children"
    else:
        url = f"https://graph.microsoft.com/v1.0/me/drive/items/{folder_id}/children"
    r = _httpx_cs.get(
        url,
        params={"$select": "id,name,file,folder,lastModifiedDateTime", "$top": 50, "$orderby": "name"},
        headers={"Authorization": f"Bearer {token}"},
        timeout=20,
    )
    result = []
    for item in r.json().get("value", []):
        if "folder" in item:
            result.append({"id": item["id"], "name": item["name"], "type": "folder",
                           "mimeType": "", "modifiedTime": item.get("lastModifiedDateTime","")})
        elif "file" in item and any(item["name"].lower().endswith(ext) for ext in _ONEDRIVE_SUPPORTED_EXT):
            result.append({"id": item["id"], "name": item["name"], "type": "file",
                           "mimeType": item.get("file",{}).get("mimeType",""),
                           "modifiedTime": item.get("lastModifiedDateTime","")})
    return result


def _onedrive_search_items(token: str, query: str) -> list[dict]:
    """Search OneDrive by name across all folders."""
    r = _httpx_cs.get(
        f"https://graph.microsoft.com/v1.0/me/drive/search(q='{query.replace(chr(39), '')}')",
        params={"$select": "id,name,file,folder,lastModifiedDateTime", "$top": 30},
        headers={"Authorization": f"Bearer {token}"},
        timeout=20,
    )
    result = []
    for item in r.json().get("value", []):
        if "folder" in item:
            result.append({"id": item["id"], "name": item["name"], "type": "folder",
                           "mimeType": "", "modifiedTime": item.get("lastModifiedDateTime","")})
        elif "file" in item and any(item["name"].lower().endswith(ext) for ext in _ONEDRIVE_SUPPORTED_EXT):
            result.append({"id": item["id"], "name": item["name"], "type": "file",
                           "mimeType": item.get("file",{}).get("mimeType",""),
                           "modifiedTime": item.get("lastModifiedDateTime","")})
    return result


def _onedrive_list_files(token: str, folder_id: str) -> list[dict]:
    """List only supported files in a OneDrive folder (for sync)."""
    if folder_id in ("root", ""):
        url = "https://graph.microsoft.com/v1.0/me/drive/root/children"
    else:
        url = f"https://graph.microsoft.com/v1.0/me/drive/items/{folder_id}/children"
    r = _httpx_cs.get(
        url,
        params={"$select": "id,name,file,lastModifiedDateTime,@microsoft.graph.downloadUrl", "$top": 200},
        headers={"Authorization": f"Bearer {token}"},
        timeout=20,
    )
    return [
        {"id": i["id"], "name": i["name"], "mimeType": i.get("file",{}).get("mimeType",""),
         "modifiedTime": i.get("lastModifiedDateTime",""),
         "downloadUrl": i.get("@microsoft.graph.downloadUrl","")}
        for i in r.json().get("value", [])
        if "file" in i and any(i["name"].lower().endswith(ext) for ext in _ONEDRIVE_SUPPORTED_EXT)
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


# ── Extraction ────────────────────────────────────────────────────────────────

def _cs_extract_content(file_bytes: bytes, filename: str, mime_type: str) -> str:
    fname = filename.lower()
    if fname.endswith((".xlsx", ".xls")) or "spreadsheet" in mime_type or "excel" in mime_type:
        return _bc_extract_excel(file_bytes, fname)
    elif fname.endswith((".doc", ".docx")) or "wordprocessing" in mime_type or "msword" in mime_type:
        try:
            import docx as _docx_cs2
            import io as _io_cs2
            _doc = _docx_cs2.Document(_io_cs2.BytesIO(file_bytes))
            return "\n".join(p.text for p in _doc.paragraphs if p.text.strip())
        except Exception:
            return _bc_extract_claude(file_bytes, "application/pdf")
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


# ── Selections helpers ────────────────────────────────────────────────────────

def _cs_parse_selections(conn: CloudStorageConnection) -> list:
    """Parse selections list from conn.client_folders_json.
    Format: [{type, id, name, path, client_id}, ...]
    """
    try:
        data = _json_cs.loads(conn.client_folders_json or "[]")
        if isinstance(data, list):
            return data
        # Old dict format {client_id: folder_id} → convert
        return [{"type": "folder", "id": fid, "name": fid, "path": fid, "client_id": int(cid)}
                for cid, fid in data.items()]
    except Exception:
        return []


def _cs_save_selections(session, conn: CloudStorageConnection, selections: list):
    conn.client_folders_json = _json_cs.dumps(selections)
    conn.updated_at = _dt_cs.utcnow().isoformat()
    session.add(conn)
    session.commit()


# ── Sync logic ────────────────────────────────────────────────────────────────

def _cs_sync_one_file(session, conn, token, file_info: dict, client_id: int) -> bool:
    """Download, extract and store one file. Returns True if indexed."""
    file_id   = file_info["id"]
    file_name = file_info["name"]
    mod_time  = file_info.get("modifiedTime", "")
    file_hash = file_info.get("md5Checksum", "")
    fingerprint = file_hash or mod_time

    existing = session.exec(
        _sel_cs(CloudStorageFile).where(
            CloudStorageFile.connection_id == conn.id,
            CloudStorageFile.file_id == file_id,
        )
    ).first()

    if existing and existing.file_hash == fingerprint:
        return False  # unchanged

    try:
        if conn.provider == "gdrive":
            file_bytes = _gdrive_download(token, file_id)
        else:
            dl_url = file_info.get("downloadUrl", "")
            file_bytes = _onedrive_download(token, file_id, dl_url)
    except Exception as _e:
        print(f"[cs] erro ao baixar {file_name}: {_e}")
        return False

    if not file_bytes:
        return False

    mime = file_info.get("mimeType", "")
    content = _cs_extract_content(file_bytes, file_name, mime)
    if not content:
        print(f"[cs] sem conteúdo extraído de {file_name}")
        return False

    try:
        doc_id = None
        if existing and existing.doc_id:
            doc = session.get(BaseConhecimento, existing.doc_id)
            if doc:
                doc.conteudo_texto = content[:200_000]
                doc.nome = file_name
                session.add(doc)
                session.commit()
                doc_id = doc.id

        if not doc_id:
            doc = BaseConhecimento(
                company_id=conn.company_id,
                client_id=client_id,
                user_id=conn.created_by_user_id,
                nome=file_name,
                descricao=f"Sincronizado de {conn.display_name}",
                tipo=conn.provider,
                conteudo_texto=content[:200_000],
                created_at=_dt_cs.utcnow().isoformat(),
            )
            session.add(doc)
            session.commit()
            session.refresh(doc)
            doc_id = doc.id

        if existing:
            existing.file_hash   = fingerprint
            existing.modified_at = mod_time
            existing.indexed_at  = _dt_cs.utcnow().isoformat()
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
        print(f"[cs] indexado: {file_name} (cliente {client_id})")
        return True

    except Exception as _e:
        print(f"[cs] erro ao salvar {file_name}: {_e}")
        session.rollback()
        return False


def _cs_sync_connection(session, conn: CloudStorageConnection) -> int:
    """Sync one connection based on its selections. Returns count of files indexed."""
    token = _cs_get_valid_token(session, conn)
    if not token:
        print(f"[cs] sem token para conexão {conn.id}")
        return 0

    selections = _cs_parse_selections(conn)
    if not selections:
        print(f"[cs] conexão {conn.id} sem seleções configuradas")
        conn.last_synced_at = _dt_cs.utcnow().isoformat()
        session.add(conn)
        session.commit()
        return 0

    indexed = 0
    for sel in selections:
        client_id = sel.get("client_id", 0)
        if not client_id:
            continue
        sel_type = sel.get("type", "folder")
        sel_id   = sel.get("id", "")

        try:
            if sel_type == "folder":
                if conn.provider == "gdrive":
                    files = _gdrive_list_files(token, sel_id)
                else:
                    files = _onedrive_list_files(token, sel_id)
                for f in files:
                    if _cs_sync_one_file(session, conn, token, f, client_id):
                        indexed += 1
            else:
                # individual file
                file_info = {"id": sel_id, "name": sel.get("name", sel_id),
                             "mimeType": sel.get("mimeType", ""),
                             "modifiedTime": sel.get("modifiedTime", ""),
                             "md5Checksum": sel.get("md5Checksum", "")}
                if _cs_sync_one_file(session, conn, token, file_info, client_id):
                    indexed += 1
        except Exception as _e:
            print(f"[cs] erro sincronizando seleção {sel_id}: {_e}")

    conn.last_synced_at = _dt_cs.utcnow().isoformat()
    session.add(conn)
    session.commit()
    return indexed


def _cs_sync_all():
    with _Sess_cs(engine) as session:
        conns = session.exec(
            _sel_cs(CloudStorageConnection).where(CloudStorageConnection.is_active == True)
        ).all()
        for conn in conns:
            try:
                n = _cs_sync_connection(session, conn)
                if n:
                    print(f"[cs] sync {conn.provider}/{conn.display_name}: {n} arquivo(s)")
            except Exception as _e:
                print(f"[cs] sync erro conexão {conn.id}: {_e}")


def _cs_background_loop():
    _time_cs.sleep(30)
    while True:
        try:
            _cs_sync_all()
        except Exception as _e:
            print(f"[cs] background loop erro: {_e}")
        _time_cs.sleep(_SYNC_INTERVAL_S)


# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/integrations/gdrive/connect")
@require_login
async def gdrive_connect(request: _Req_cs):
    if not _GDRIVE_CLIENT_ID:
        set_flash(request, "GDRIVE_CLIENT_ID não configurado.")
        return _RR_cs("/integrations", status_code=303)
    state = request.session.get("user_id", "0")
    return _RR_cs(_gdrive_auth_url(str(state)), status_code=302)


@app.get("/integrations/gdrive/callback")
@require_login
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
            set_flash(request, f"Google Drive erro: {data.get('error_description', data['error'])}")
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
            client_folders_json="[]",
            is_active=True,
            created_at=_dt_cs.utcnow().isoformat(),
            updated_at=_dt_cs.utcnow().isoformat(),
        )
        session.add(conn)
        session.commit()
        session.refresh(conn)
        return _RR_cs(f"/integrations/{conn.id}/browser", status_code=303)
    except Exception as _e:
        set_flash(request, f"Erro ao conectar Google Drive: {_e}")
    return _RR_cs("/integrations", status_code=303)


@app.get("/integrations/onedrive/connect")
@require_login
async def onedrive_connect(request: _Req_cs):
    if not _ONEDRIVE_CLIENT_ID:
        set_flash(request, "ONEDRIVE_CLIENT_ID não configurado.")
        return _RR_cs("/integrations", status_code=303)
    state = request.session.get("user_id", "0")
    return _RR_cs(_onedrive_auth_url(str(state)), status_code=302)


@app.get("/integrations/onedrive/callback")
@require_login
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
            client_folders_json="[]",
            is_active=True,
            created_at=_dt_cs.utcnow().isoformat(),
            updated_at=_dt_cs.utcnow().isoformat(),
        )
        session.add(conn)
        session.commit()
        session.refresh(conn)
        return _RR_cs(f"/integrations/{conn.id}/browser", status_code=303)
    except Exception as _e:
        set_flash(request, f"Erro ao conectar OneDrive: {_e}")
    return _RR_cs("/integrations", status_code=303)


# ── API: list items (folders + files) ─────────────────────────────────────────

@app.get("/api/integrations/{conn_id}/items")
@require_login
async def cs_list_items(
    conn_id: int,
    request: _Req_cs,
    session=_Dep_cs(get_session),
    parent: str = "root",
):
    ctx = get_tenant_context(request, session)
    if not ctx:
        return _JSON_cs({"items": [], "erro": "Não autenticado."})
    conn = session.get(CloudStorageConnection, conn_id)
    if not conn or conn.company_id != ctx.company.id:
        return _JSON_cs({"items": [], "erro": "Conexão não encontrada."})
    token = _cs_get_valid_token(session, conn)
    try:
        if conn.provider == "gdrive":
            items = _gdrive_list_items(token, parent)
        else:
            items = _onedrive_list_items(token, parent)
        return _JSON_cs({"items": items})
    except Exception as _e:
        return _JSON_cs({"items": [], "erro": str(_e)})


# ── API: search items ─────────────────────────────────────────────────────────

@app.get("/api/integrations/{conn_id}/search-items")
@require_login
async def cs_search_items(
    conn_id: int,
    request: _Req_cs,
    session=_Dep_cs(get_session),
    q: str = "",
):
    ctx = get_tenant_context(request, session)
    if not ctx:
        return _JSON_cs({"items": [], "erro": "Não autenticado."})
    conn = session.get(CloudStorageConnection, conn_id)
    if not conn or conn.company_id != ctx.company.id:
        return _JSON_cs({"items": [], "erro": "Conexão não encontrada."})
    if not q or len(q) < 2:
        return _JSON_cs({"items": []})
    token = _cs_get_valid_token(session, conn)
    try:
        if conn.provider == "gdrive":
            items = _gdrive_search_items(token, q)
        else:
            items = _onedrive_search_items(token, q)
        return _JSON_cs({"items": items})
    except Exception as _e:
        return _JSON_cs({"items": [], "erro": str(_e)})


# ── API: add selection ─────────────────────────────────────────────────────────

@app.post("/api/integrations/{conn_id}/add-selection")
@require_login
async def cs_add_selection(
    conn_id: int,
    request: _Req_cs,
    session=_Dep_cs(get_session),
):
    ctx = get_tenant_context(request, session)
    if not ctx:
        return _JSON_cs({"ok": False, "erro": "Não autenticado."})
    conn = session.get(CloudStorageConnection, conn_id)
    if not conn or conn.company_id != ctx.company.id:
        return _JSON_cs({"ok": False, "erro": "Conexão não encontrada."})

    body = await request.json()
    item_type  = body.get("type", "folder")
    item_id    = body.get("id", "")
    item_name  = body.get("name", "")
    item_path  = body.get("path", item_name)
    item_mime  = body.get("mimeType", "")
    client_id  = int(body.get("client_id", 0))

    if not item_id or not client_id:
        return _JSON_cs({"ok": False, "erro": "item_id e client_id são obrigatórios."})

    selections = _cs_parse_selections(conn)
    # Remove duplicate (same id + client)
    selections = [s for s in selections if not (s.get("id") == item_id and s.get("client_id") == client_id)]
    selections.append({
        "type": item_type,
        "id": item_id,
        "name": item_name,
        "path": item_path,
        "mimeType": item_mime,
        "client_id": client_id,
    })
    _cs_save_selections(session, conn, selections)
    return _JSON_cs({"ok": True, "total": len(selections)})


# ── API: remove selection ──────────────────────────────────────────────────────

@app.post("/api/integrations/{conn_id}/remove-selection")
@require_login
async def cs_remove_selection(
    conn_id: int,
    request: _Req_cs,
    session=_Dep_cs(get_session),
):
    ctx = get_tenant_context(request, session)
    if not ctx:
        return _JSON_cs({"ok": False})
    conn = session.get(CloudStorageConnection, conn_id)
    if not conn or conn.company_id != ctx.company.id:
        return _JSON_cs({"ok": False})

    body = await request.json()
    item_id   = body.get("id", "")
    client_id = int(body.get("client_id", 0))

    selections = _cs_parse_selections(conn)
    selections = [s for s in selections if not (s.get("id") == item_id and s.get("client_id") == client_id)]
    _cs_save_selections(session, conn, selections)
    return _JSON_cs({"ok": True, "total": len(selections)})


# ── API: sync now ─────────────────────────────────────────────────────────────

@app.post("/api/integrations/{conn_id}/sync")
@require_login
async def cs_sync_now(conn_id: int, request: _Req_cs, session=_Dep_cs(get_session)):
    ctx = get_tenant_context(request, session)
    if not ctx:
        return _JSON_cs({"ok": False})
    conn = session.get(CloudStorageConnection, conn_id)
    if not conn or conn.company_id != ctx.company.id:
        return _JSON_cs({"ok": False, "erro": "Conexão não encontrada."})
    try:
        import asyncio as _aio_cs
        loop = _aio_cs.get_event_loop()
        n = await loop.run_in_executor(None, lambda: _cs_sync_connection(session, conn))
        return _JSON_cs({"ok": True, "indexed": n})
    except Exception as _e:
        return _JSON_cs({"ok": False, "erro": str(_e)})


# ── API: disconnect ────────────────────────────────────────────────────────────

@app.post("/api/integrations/{conn_id}/disconnect")
@require_login
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


# ── Page: /integrations/{id}/browser ─────────────────────────────────────────

_CS_BROWSER_PAGE = r"""
<!doctype html><html lang="pt-BR"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Selecionar arquivos — {{ conn_name }}</title>
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css">
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.3/font/bootstrap-icons.min.css">
<style>
body{background:#f8f9fa}
.item-row{display:flex;align-items:center;gap:10px;padding:10px 12px;border:1px solid #e5e7eb;border-radius:10px;background:#fff;margin-bottom:6px;cursor:default}
.item-row:hover{border-color:#f97316;background:#fffbf7}
.item-row.is-folder{cursor:pointer}
.item-icon{font-size:1.3rem;flex-shrink:0;width:28px;text-align:center}
.item-name{flex:1;font-size:.93rem;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.sel-row{display:flex;align-items:center;gap:8px;padding:8px 10px;border:1px solid #e5e7eb;border-radius:8px;background:#fff;margin-bottom:5px;font-size:.85rem}
.sel-row .sel-name{flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.breadcrumb-item{cursor:pointer;color:#f97316}
.breadcrumb-item.active{color:#666;cursor:default}
</style>
</head><body>
<div class="container-fluid py-3" style="max-width:1000px">

  <!-- Header -->
  <div class="d-flex align-items-center gap-3 mb-3">
    <a href="/integrations" class="btn btn-sm btn-outline-secondary"><i class="bi bi-arrow-left"></i></a>
    <div>
      <h5 class="mb-0">Selecionar arquivos — {{ conn_name }}</h5>
      <p class="text-muted small mb-0">Navegue e escolha quais pastas ou arquivos o Augur deve ler para cada cliente.</p>
    </div>
  </div>

  <div class="row g-3">
    <!-- Left: file browser -->
    <div class="col-12 col-lg-7">
      <div class="card p-3">

        <!-- Search -->
        <div class="input-group mb-3">
          <input type="text" class="form-control" id="search-input"
                 placeholder="Buscar por nome (ex: Finanças, Clientes...)"
                 onkeydown="if(event.key==='Enter') doSearch()">
          <button class="btn btn-primary" onclick="doSearch()" id="search-btn">
            <i class="bi bi-search"></i> Buscar
          </button>
        </div>

        <!-- Breadcrumb (only visible when browsing) -->
        <nav aria-label="breadcrumb" class="mb-2 d-none" id="breadcrumb-nav">
          <ol class="breadcrumb mb-0" id="breadcrumb">
            <li class="breadcrumb-item" onclick="navigateTo(0)" style="cursor:pointer;color:#f97316">Raiz</li>
          </ol>
        </nav>

        <div id="items-hint" class="text-muted small py-4 text-center">
          <i class="bi bi-search fs-3 d-block mb-2 opacity-50"></i>
          Digite acima para buscar por nome, ou clique em <b>Raiz</b> para navegar pelas pastas.
        </div>
        <div id="items-loading" class="text-center py-4 text-muted d-none">
          <div class="spinner-border spinner-border-sm"></div> Buscando...
        </div>
        <div id="items-list" class="d-none"></div>
        <div id="items-empty" class="text-muted small py-3 d-none text-center">Nenhum resultado encontrado.</div>
        <div id="items-error" class="alert alert-danger d-none"></div>
        <div class="d-none mt-2" id="browse-root-btn-wrap">
          <button class="btn btn-sm btn-outline-secondary w-100" onclick="browseRoot()">
            <i class="bi bi-folder2-open me-1"></i>Navegar pela raiz
          </button>
        </div>
      </div>
    </div>

    <!-- Right: selections -->
    <div class="col-12 col-lg-5">
      <div class="card p-3">
        <h6 class="mb-2">Seleções <span class="badge bg-secondary" id="sel-count">{{ selections|length }}</span></h6>
        <div id="sel-list">
          {% for s in selections %}
          <div class="sel-row" id="sel-{{ s.id }}-{{ s.client_id }}">
            <i class="bi bi-{{ 'folder-fill text-warning' if s.type == 'folder' else 'file-earmark text-secondary' }}"></i>
            <div class="sel-name" title="{{ s.path }}">{{ s.name }}</div>
            <div class="text-muted" style="font-size:.78rem;flex-shrink:0">→ {{ clients_by_id.get(s.client_id, '?') }}</div>
            <button class="btn btn-sm btn-outline-danger py-0 px-1" onclick="removeSelection('{{ s.id }}', {{ s.client_id }})">
              <i class="bi bi-x"></i>
            </button>
          </div>
          {% else %}
          <p class="text-muted small" id="sel-empty">Nenhuma seleção ainda. Navegue à esquerda e adicione pastas ou arquivos.</p>
          {% endfor %}
        </div>

        <hr class="my-2">
        <button class="btn btn-primary w-100" onclick="syncAndFinish()" id="sync-btn">
          <i class="bi bi-arrow-clockwise me-1"></i>Sincronizar agora e voltar
        </button>
        <a href="/integrations" class="btn btn-outline-secondary w-100 mt-2">Voltar sem sincronizar</a>
      </div>
    </div>
  </div>
</div>

<!-- Modal: choose client -->
<div class="modal fade" id="clientModal" tabindex="-1">
  <div class="modal-dialog modal-sm">
    <div class="modal-content">
      <div class="modal-header py-2">
        <h6 class="modal-title mb-0">Associar ao cliente</h6>
        <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
      </div>
      <div class="modal-body py-2">
        <p class="small text-muted mb-2" id="modal-item-name"></p>
        <select class="form-select form-select-sm" id="modal-client-select">
          {% for c in clients %}
          <option value="{{ c.id }}">{{ c.name }}</option>
          {% endfor %}
        </select>
      </div>
      <div class="modal-footer py-2">
        <button class="btn btn-primary btn-sm" onclick="confirmAdd()">Adicionar</button>
      </div>
    </div>
  </div>
</div>

<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/js/bootstrap.bundle.min.js"></script>
<script>
const CONN_ID = {{ conn_id }};
const CLIENTS = {{ clients_json }};
const clientsById = Object.fromEntries(CLIENTS.map(c => [c.id, c.name]));

let breadcrumb = [{id: 'root', name: 'Raiz'}];
let pendingItem = null;
let isSearchMode = false;
const _itemStore = {};
const modal = new bootstrap.Modal(document.getElementById('clientModal'));

function esc(s){ return String(s||'').replace(/[&<>"']/g, c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])); }

function fileIcon(item){
  if(item.type==='folder') return 'folder-fill text-warning';
  const n = item.name.toLowerCase();
  if(n.endsWith('.pdf')) return 'file-earmark-pdf text-danger';
  if(n.match(/\.(xlsx?|csv)$/)) return 'file-earmark-spreadsheet text-success';
  if(n.match(/\.(docx?)$/)) return 'file-earmark-word text-primary';
  if(n.match(/\.(jpe?g|png)$/)) return 'file-earmark-image text-info';
  return 'file-earmark text-secondary';
}

function showLoading(msg){
  document.getElementById('items-hint').classList.add('d-none');
  document.getElementById('items-loading').classList.remove('d-none');
  document.getElementById('items-loading').innerHTML = `<div class="spinner-border spinner-border-sm"></div> ${msg||'Carregando...'}`;
  document.getElementById('items-list').classList.add('d-none');
  document.getElementById('items-empty').classList.add('d-none');
  document.getElementById('items-error').classList.add('d-none');
}

function showItems(items){
  document.getElementById('items-loading').classList.add('d-none');
  if(!items.length){ document.getElementById('items-empty').classList.remove('d-none'); return; }
  // Store items by id so onclick can reference safely (avoids JSON-in-HTML-attr bugs)
  items.forEach(item => { _itemStore[item.id] = item; });
  const list = document.getElementById('items-list');
  list.innerHTML = items.map(item => {
    const isFolder = item.type === 'folder';
    const canNavigate = isFolder && !isSearchMode;
    return `<div class="item-row ${isFolder?'is-folder':''}" data-id="${esc(item.id)}">
      <span class="item-icon"><i class="bi bi-${fileIcon(item)}"></i></span>
      <span class="item-name" title="${esc(item.name)}">${esc(item.name)}</span>
      ${canNavigate?`<span class="text-muted small me-1"><i class="bi bi-chevron-right"></i></span>`:''}
      <button class="btn btn-sm btn-outline-primary py-0 px-2 flex-shrink-0 btn-add"
              data-item-id="${esc(item.id)}"
              title="Adicionar à base">+ Adicionar</button>
    </div>`;
  }).join('');
  // Folder click → navigate
  list.querySelectorAll('.item-row.is-folder').forEach(row => {
    row.addEventListener('click', e => {
      if(e.target.closest('.btn-add')) return;
      const item = _itemStore[row.dataset.id];
      if(item && !isSearchMode) navigateInto(item.id, item.name);
    });
  });
  // Add button click
  list.querySelectorAll('.btn-add').forEach(btn => {
    btn.addEventListener('click', e => {
      e.stopPropagation();
      openClientModal(_itemStore[btn.dataset.itemId]);
    });
  });
  list.classList.remove('d-none');
}

async function doSearch(){
  const q = document.getElementById('search-input').value.trim();
  if(q.length < 2){ alert('Digite pelo menos 2 caracteres para buscar.'); return; }
  isSearchMode = true;
  document.getElementById('breadcrumb-nav').classList.add('d-none');
  document.getElementById('browse-root-btn-wrap').classList.remove('d-none');
  showLoading('Buscando "'+q+'"...');
  try{
    const r = await fetch(`/api/integrations/${CONN_ID}/search-items?q=${encodeURIComponent(q)}`, {credentials:'same-origin'});
    const d = await r.json();
    if(d.erro){ document.getElementById('items-loading').classList.add('d-none'); document.getElementById('items-error').textContent=d.erro; document.getElementById('items-error').classList.remove('d-none'); return; }
    showItems(d.items||[]);
  }catch(e){
    document.getElementById('items-loading').classList.add('d-none');
    document.getElementById('items-error').textContent='Erro: '+e.message;
    document.getElementById('items-error').classList.remove('d-none');
  }
}

async function browseRoot(){
  isSearchMode = false;
  breadcrumb = [{id:'root', name:'Raiz'}];
  renderBreadcrumb();
  document.getElementById('breadcrumb-nav').classList.remove('d-none');
  document.getElementById('browse-root-btn-wrap').classList.add('d-none');
  await loadFolder('root');
}

async function loadFolder(folderId){
  showLoading('Carregando pasta...');
  try{
    const r = await fetch(`/api/integrations/${CONN_ID}/items?parent=${encodeURIComponent(folderId)}`, {credentials:'same-origin'});
    const d = await r.json();
    if(d.erro){ document.getElementById('items-loading').classList.add('d-none'); document.getElementById('items-error').textContent=d.erro; document.getElementById('items-error').classList.remove('d-none'); return; }
    showItems(d.items||[]);
  }catch(e){
    document.getElementById('items-loading').classList.add('d-none');
    document.getElementById('items-error').textContent='Erro: '+e.message;
    document.getElementById('items-error').classList.remove('d-none');
  }
}

function navigateInto(folderId, folderName){
  breadcrumb.push({id: folderId, name: folderName});
  renderBreadcrumb();
  loadFolder(folderId);
}

function navigateTo(idx){
  breadcrumb = breadcrumb.slice(0, idx+1);
  renderBreadcrumb();
  loadFolder(breadcrumb[breadcrumb.length-1].id);
}

function renderBreadcrumb(){
  const ol = document.getElementById('breadcrumb');
  ol.innerHTML = breadcrumb.map((b,i) => {
    const isLast = i === breadcrumb.length-1;
    return `<li class="breadcrumb-item ${isLast?'active':''}" ${isLast?'':` onclick="navigateTo(${i})" style="cursor:pointer;color:#f97316"`}>${esc(b.name)}</li>`;
  }).join('');
}

function currentPath(){
  return '/' + breadcrumb.slice(1).map(b=>b.name).join('/');
}

function openClientModal(item){
  pendingItem = item;
  document.getElementById('modal-item-name').textContent =
    (item.type==='folder'?'📁 ':'📄 ') + item.name + (item.type==='folder'?' (pasta inteira)':'');
  modal.show();
}

async function confirmAdd(){
  if(!pendingItem) return;
  const clientId = parseInt(document.getElementById('modal-client-select').value);
  const path = currentPath() + (pendingItem.type==='folder'?'/'+pendingItem.name:'');
  modal.hide();
  try{
    const r = await fetch(`/api/integrations/${CONN_ID}/add-selection`, {
      method:'POST', credentials:'same-origin',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify({...pendingItem, path, client_id: clientId})
    });
    const d = await r.json();
    if(d.ok) renderSelectionAdd(pendingItem, clientId, path);
  }catch(e){ alert('Erro ao adicionar: '+e.message); }
  pendingItem = null;
}

function renderSelectionAdd(item, clientId, path){
  document.getElementById('sel-empty') && document.getElementById('sel-empty').remove();
  const existing = document.getElementById(`sel-${item.id}-${clientId}`);
  if(existing) return; // already there
  const div = document.createElement('div');
  div.className = 'sel-row';
  div.id = `sel-${item.id}-${clientId}`;
  div.innerHTML = `
    <i class="bi bi-${item.type==='folder'?'folder-fill text-warning':'file-earmark text-secondary'}"></i>
    <div class="sel-name" title="${esc(path)}">${esc(item.name)}</div>
    <div class="text-muted" style="font-size:.78rem;flex-shrink:0">→ ${esc(clientsById[clientId]||'?')}</div>
    <button class="btn btn-sm btn-outline-danger py-0 px-1" onclick="removeSelection('${item.id}', ${clientId})">
      <i class="bi bi-x"></i>
    </button>`;
  document.getElementById('sel-list').appendChild(div);
  const cnt = document.getElementById('sel-count');
  cnt.textContent = parseInt(cnt.textContent||0)+1;
}

async function removeSelection(itemId, clientId){
  try{
    const r = await fetch(`/api/integrations/${CONN_ID}/remove-selection`, {
      method:'POST', credentials:'same-origin',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify({id: itemId, client_id: clientId})
    });
    const d = await r.json();
    if(d.ok){
      document.getElementById(`sel-${itemId}-${clientId}`)?.remove();
      const cnt = document.getElementById('sel-count');
      cnt.textContent = Math.max(0, parseInt(cnt.textContent||0)-1);
    }
  }catch(e){}
}

async function syncAndFinish(){
  const btn = document.getElementById('sync-btn');
  btn.disabled=true;
  btn.innerHTML='<span class="spinner-border spinner-border-sm"></span> Sincronizando...';
  try{
    const r = await fetch(`/api/integrations/${CONN_ID}/sync`, {method:'POST',credentials:'same-origin'});
    const d = await r.json();
    if(d.ok){
      btn.innerHTML=`<i class="bi bi-check"></i> ${d.indexed} arquivo(s) indexado(s)!`;
    } else {
      btn.innerHTML='<i class="bi bi-exclamation"></i> Erro ao sincronizar';
      btn.disabled=false;
    }
  }catch(e){
    btn.innerHTML='Erro'; btn.disabled=false;
  }
  setTimeout(()=>{ window.location='/integrations'; }, 1500);
}

// focus search on load
document.getElementById('search-input').focus();
</script>
</body></html>
"""


@app.get("/integrations/{conn_id}/browser", response_class=_HTML_cs)
@require_login
async def cs_browser(conn_id: int, request: _Req_cs, session=_Dep_cs(get_session)):
    ctx = get_tenant_context(request, session)
    if not ctx:
        return _RR_cs("/login", status_code=303)
    conn = session.get(CloudStorageConnection, conn_id)
    if not conn or conn.company_id != ctx.company.id:
        set_flash(request, "Conexão não encontrada.")
        return _RR_cs("/integrations", status_code=303)

    role = ctx.membership.role if ctx.membership else "cliente"
    # Clients can only manage their own connections
    if role == "cliente" and conn.created_by_user_id != ctx.user.id:
        set_flash(request, "Acesso não permitido.")
        return _RR_cs("/integrations", status_code=303)

    # For admin/equipe: all company clients. For cliente: only their own.
    if role == "cliente":
        membership = session.exec(
            _sel_cs(Membership).where(
                Membership.company_id == ctx.company.id,
                Membership.user_id == ctx.user.id,
            )
        ).first()
        own_client_id = membership.client_id if membership else None
        clients = []
        if own_client_id:
            own_client = session.get(Client, own_client_id)
            if own_client:
                clients = [own_client]
    else:
        clients = session.exec(
            _sel_cs(Client).where(Client.company_id == ctx.company.id)
        ).all()

    clients_by_id = {c.id: c.name for c in clients}
    selections = _cs_parse_selections(conn)

    from jinja2 import Environment as _JEnv2
    import json as _j2
    env = _JEnv2()
    tmpl = env.from_string(_CS_BROWSER_PAGE)
    html = tmpl.render(
        conn_id=conn.id,
        conn_name=conn.display_name,
        selections=selections,
        clients=clients,
        clients_by_id=clients_by_id,
        clients_json=_j2.dumps([{"id": c.id, "name": c.name} for c in clients]),
    )
    return _HTML_cs(html)


# ── Page: /integrations ───────────────────────────────────────────────────────

_CS_PAGE = r"""
<!doctype html><html lang="pt-BR"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Conectar Drive — Maffezzolli</title>
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css">
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.3/font/bootstrap-icons.min.css">
<style>
.drive-btn{display:flex;align-items:center;gap:14px;padding:16px 20px;border:1.5px solid #e5e7eb;border-radius:14px;background:#fff;cursor:pointer;text-decoration:none;color:#111;transition:border-color .15s,box-shadow .15s;width:100%}
.drive-btn:hover{border-color:#f97316;box-shadow:0 2px 12px rgba(249,115,22,.15);color:#111}
.drive-btn img{width:36px;height:36px;flex-shrink:0}
.conn-card{border:1px solid #e5e7eb;border-radius:12px;padding:14px 16px;background:#fff;margin-bottom:10px}
</style>
</head><body class="bg-light">
<div class="container py-4" style="max-width:640px">
  <div class="d-flex align-items-center gap-3 mb-4">
    <a href="/" class="btn btn-sm btn-outline-secondary"><i class="bi bi-arrow-left"></i></a>
    <div>
      <h5 class="mb-0">Conectar Drive ao Augur</h5>
      <p class="text-muted small mb-0">Escolha quais pastas ou arquivos o Augur pode ler para cada cliente.</p>
    </div>
  </div>

  {% if flash %}<div class="alert alert-info alert-dismissible fade show mb-3">
    <button type="button" class="btn-close" data-bs-dismiss="alert"></button>{{ flash }}</div>{% endif %}

  <div class="d-flex flex-column gap-3 mb-4">
    <a href="/integrations/gdrive/connect" class="drive-btn {% if not gdrive_ok %}opacity-50 pe-none{% endif %}">
      <img src="https://www.gstatic.com/images/branding/product/1x/drive_2020q4_48dp.png" alt="Google Drive">
      <div>
        <div class="fw-semibold">Google Drive</div>
        <div class="text-muted small">Conectar minha conta Google</div>
      </div>
      <i class="bi bi-chevron-right ms-auto text-muted"></i>
    </a>
    <a href="/integrations/onedrive/connect" class="drive-btn {% if not onedrive_ok %}opacity-50 pe-none{% endif %}">
      <img src="https://upload.wikimedia.org/wikipedia/commons/thumb/3/3c/Microsoft_Office_OneDrive_%282019%E2%80%93present%29.svg/512px-Microsoft_Office_OneDrive_%282019%E2%80%93present%29.svg.png" alt="OneDrive">
      <div>
        <div class="fw-semibold">OneDrive</div>
        <div class="text-muted small">Conectar minha conta Microsoft</div>
      </div>
      <i class="bi bi-chevron-right ms-auto text-muted"></i>
    </a>
  </div>

  {% if conns %}
  <h6 class="mb-3 text-muted small text-uppercase fw-semibold">Drives conectados</h6>
  {% for conn in conns %}
  <div class="conn-card">
    <div class="d-flex justify-content-between align-items-center flex-wrap gap-2">
      <div class="d-flex align-items-center gap-2">
        {% if conn.provider == 'gdrive' %}
          <img src="https://www.gstatic.com/images/branding/product/1x/drive_2020q4_48dp.png" width="22" height="22">
        {% else %}
          <img src="https://upload.wikimedia.org/wikipedia/commons/thumb/3/3c/Microsoft_Office_OneDrive_%282019%E2%80%93present%29.svg/512px-Microsoft_Office_OneDrive_%282019%E2%80%93present%29.svg.png" width="22" height="22">
        {% endif %}
        <div>
          <div class="fw-semibold small">{{ conn.display_name }}</div>
          <div class="text-muted" style="font-size:11px">
            Sync: {{ conn.last_synced_at[:16].replace('T',' ') if conn.last_synced_at else 'Aguardando' }}
            • {{ sel_counts.get(conn.id, 0) }} seleção(ões)
          </div>
        </div>
      </div>
      <div class="d-flex gap-2">
        <a class="btn btn-sm btn-outline-secondary" href="/integrations/{{ conn.id }}/browser" title="Configurar pastas">
          <i class="bi bi-folder2-open"></i>
        </a>
        <button class="btn btn-sm btn-outline-success" onclick="syncNow({{ conn.id }}, this)" title="Sincronizar agora">
          <i class="bi bi-arrow-clockwise"></i>
        </button>
        <form method="post" action="/api/integrations/{{ conn.id }}/disconnect" style="display:inline"
              onsubmit="return confirm('Desconectar?')">
          <button class="btn btn-sm btn-outline-danger" title="Desconectar"><i class="bi bi-x-lg"></i></button>
        </form>
      </div>
    </div>
  </div>
  {% endfor %}
  {% endif %}

  <p class="text-muted small mt-3">
    <i class="bi bi-info-circle me-1"></i>
    Após conectar, clique em <i class="bi bi-folder2-open"></i> para escolher as pastas ou arquivos de cada cliente.
    A sincronização automática ocorre a cada 30 minutos.
  </p>
</div>
<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/js/bootstrap.bundle.min.js"></script>
<script>
async function syncNow(connId, btn) {
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner-border spinner-border-sm"></span>';
  try {
    const r = await fetch(`/api/integrations/${connId}/sync`, {method:'POST', credentials:'same-origin'});
    const d = await r.json();
    btn.innerHTML = d.ok ? `<i class="bi bi-check"></i>${d.indexed}` : '<i class="bi bi-exclamation"></i>';
    setTimeout(() => { btn.innerHTML='<i class="bi bi-arrow-clockwise"></i>'; btn.disabled=false; }, 2500);
  } catch(e) { btn.innerHTML='<i class="bi bi-exclamation"></i>'; btn.disabled=false; }
}
</script>
</body></html>
"""


@app.get("/integrations", response_class=_HTML_cs)
@require_login
async def integrations_page(request: _Req_cs, session=_Dep_cs(get_session)):
    ctx = get_tenant_context(request, session)
    if not ctx:
        return _RR_cs("/login", status_code=303)

    flash = request.session.pop("flash", None)
    role = ctx.membership.role if ctx.membership else "cliente"

    q = _sel_cs(CloudStorageConnection).where(
        CloudStorageConnection.company_id == ctx.company.id,
        CloudStorageConnection.is_active == True,
    )
    # Clients see only their own connections
    if role == "cliente":
        q = q.where(CloudStorageConnection.created_by_user_id == ctx.user.id)
    conns = session.exec(q).all()

    sel_counts = {c.id: len(_cs_parse_selections(c)) for c in conns}

    from jinja2 import Environment as _JEnv
    env = _JEnv()
    tmpl = env.from_string(_CS_PAGE)
    html = tmpl.render(
        flash=flash,
        conns=conns,
        sel_counts=sel_counts,
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

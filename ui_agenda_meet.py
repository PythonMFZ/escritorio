# ============================================================================
# ui_agenda_meet.py — link de videochamada nas reuniões online da agenda
# ============================================================================
# Exec'd no namespace do app.py, depois dos módulos do prédio.
#
# Reunião com local "online" ganha um link:
#   1. Google Meet — quando um admin conectou o Google Agenda do escritório
#      (Prédio → Reuniões online). O evento é criado no Google Agenda dessa conta
#      com sala do Meet; os convidados entram na lista do evento sem e-mail do
#      Google (o convite continua saindo pela plataforma).
#   2. Jitsi Meet — se o Google não estiver conectado ou falhar: sala gratuita,
#      sem conta, para nunca sair convite de reunião online sem link.
# Remarcar/cancelar pelo prédio atualiza/remove o evento do Google.
#
# Configuração: GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET (ou os do Google Drive,
# GDRIVE_CLIENT_ID / GDRIVE_CLIENT_SECRET), com a Google Calendar API ativa e o
# redirect https://<app>/agenda/google/callback cadastrado no Google Cloud.
# ============================================================================

import os as _os_gm
import secrets as _sec_gm
from datetime import datetime as _dt_gm, timedelta as _td_gm
from typing import Optional as _Opt_gm

from sqlmodel import Field as _F_gm, SQLModel as _SM_gm, Session as _Sess_gm, select as _sel_gm

_GM_ESCOPO = "https://www.googleapis.com/auth/calendar.events openid email"


class AgendaGoogle(_SM_gm, table=True):
    __tablename__ = "agenda_google"
    __table_args__ = {"extend_existing": True}
    id: _Opt_gm[int] = _F_gm(default=None, primary_key=True)
    company_id: int = _F_gm(index=True, unique=True)
    email: str = _F_gm(default="")
    refresh_token: str = _F_gm(default="")
    access_token: str = _F_gm(default="")
    expira_em: _Opt_gm[_dt_gm] = _F_gm(default=None)
    conectado_por_user_id: int = _F_gm(default=0)
    conectado_em: _dt_gm = _F_gm(default_factory=lambda: _dt_gm.utcnow())


try:
    _SM_gm.metadata.create_all(engine, tables=[AgendaGoogle.__table__], checkfirst=True)
except Exception as _e_gm:
    print(f"[agenda_meet] tabela: {_e_gm}")


def _gm_migrar() -> None:
    from sqlalchemy import inspect as _insp_gm, text as _txt_gm
    try:
        cols = {c["name"] for c in _insp_gm(engine).get_columns("agendabooking")}
    except Exception as e:
        print(f"[agenda_meet] inspeção: {e}")
        return
    for nome in ("link_online", "google_event_id"):
        if nome not in cols:
            try:
                with engine.begin() as conn:
                    conn.execute(_txt_gm(f"ALTER TABLE agendabooking ADD COLUMN {nome} TEXT DEFAULT ''"))
            except Exception as e:
                print(f"[agenda_meet] coluna {nome}: {e}")


_gm_migrar()


def _gm_cliente_oauth() -> tuple:
    return (_os_gm.environ.get("GOOGLE_CLIENT_ID") or _os_gm.environ.get("GDRIVE_CLIENT_ID") or "",
            _os_gm.environ.get("GOOGLE_CLIENT_SECRET") or _os_gm.environ.get("GDRIVE_CLIENT_SECRET") or "")


def _gm_redirect() -> str:
    base = (PUBLIC_BASE_URL or "https://app.maffezzollicapital.com.br").rstrip("/")
    return f"{base}/agenda/google/callback"


def _gm_http(metodo: str, url: str, **kw):
    import httpx as _httpx_gm
    return _httpx_gm.request(metodo, url, timeout=20, **kw)


def _gm_token(s, conta: AgendaGoogle) -> str:
    """Access token válido (renova com o refresh token quando precisa)."""
    if conta.access_token and conta.expira_em and conta.expira_em > _dt_gm.utcnow() + _td_gm(minutes=2):
        return conta.access_token
    cid, segredo = _gm_cliente_oauth()
    r = _gm_http("POST", "https://oauth2.googleapis.com/token",
                 data={"client_id": cid, "client_secret": segredo, "refresh_token": conta.refresh_token,
                       "grant_type": "refresh_token"})
    if r.status_code != 200:
        raise RuntimeError(f"Google recusou a renovação do acesso ({r.status_code}): reconecte o Google Agenda no Prédio.")
    dado = r.json()
    conta.access_token = dado.get("access_token", "")
    conta.expira_em = _dt_gm.utcnow() + _td_gm(seconds=int(dado.get("expires_in", 3600)))
    s.add(conta)
    s.commit()
    return conta.access_token


def _gm_conta(s, company_id: int) -> _Opt_gm[AgendaGoogle]:
    conta = s.exec(_sel_gm(AgendaGoogle).where(AgendaGoogle.company_id == company_id)).first()
    return conta if conta and conta.refresh_token else None


def _gm_evento(booking, titulo: str, descricao: str, convidados: list) -> dict:
    fim = booking.hora_fim or booking.hora_inicio
    return {"summary": titulo, "description": descricao,
            "start": {"dateTime": f"{booking.data}T{booking.hora_inicio}:00", "timeZone": "America/Sao_Paulo"},
            "end": {"dateTime": f"{booking.data}T{fim}:00", "timeZone": "America/Sao_Paulo"},
            "attendees": [{"email": e} for e in convidados if e and "@" in e]}


def _gm_jitsi(booking) -> str:
    return f"https://meet.jit.si/MaffezzolliCapital-{(booking.token or _sec_gm.token_urlsafe(12))[:14].replace('_', 'x').replace('-', 'y')}"


def _meet_garantir_link(s, booking, company) -> str:
    """Garante o link de uma reunião online (Google Meet; Jitsi como reserva). Grava no booking."""
    if (booking.local or "") != "online" or (booking.link_online or ""):
        return booking.link_online or ""
    conta = _gm_conta(s, booking.company_id)
    link, evento_id = "", ""
    if conta:
        try:
            membro = s.get(AgendaMembro, booking.membro_id) if booking.membro_id else None
            servico = s.get(AgendaServico, booking.servico_id) if booking.servico_id else None
            titulo = f"{servico.nome if servico else 'Reunião'} — {booking.solicitante_nome or company.name}"
            corpo = _gm_evento(booking, titulo, (booking.notas or "") + "\n\nAgendado pela plataforma Maffezzolli.",
                               [booking.solicitante_email, membro.email if membro else ""])
            corpo["conferenceData"] = {"createRequest": {"requestId": booking.ics_uid or _sec_gm.token_hex(8),
                                                         "conferenceSolutionKey": {"type": "hangoutsMeet"}}}
            r = _gm_http("POST", "https://www.googleapis.com/calendar/v3/calendars/primary/events",
                         params={"conferenceDataVersion": 1, "sendUpdates": "none"},
                         headers={"Authorization": f"Bearer {_gm_token(s, conta)}"}, json=corpo)
            if r.status_code in (200, 201):
                dado = r.json()
                link = dado.get("hangoutLink") or next(
                    (e.get("uri") for e in (dado.get("conferenceData") or {}).get("entryPoints", [])
                     if e.get("entryPointType") == "video"), "")
                evento_id = dado.get("id", "")
            else:
                print(f"[agenda_meet] Google Agenda respondeu {r.status_code}: {r.text[:200]}")
        except Exception as e:
            print(f"[agenda_meet] Google Meet indisponível: {e}")
    booking.link_online = link or _gm_jitsi(booking)
    booking.google_event_id = evento_id
    s.add(booking)
    s.commit()
    s.refresh(booking)
    return booking.link_online


def _meet_ao_remarcar(s, booking) -> None:
    """Atualiza data/hora do evento no Google (o link do Meet continua o mesmo)."""
    if not (booking.google_event_id or ""):
        if (booking.local or "") == "online" and not (booking.link_online or ""):
            empresa = s.get(Company, booking.company_id)
            _meet_garantir_link(s, booking, empresa)
        return
    conta = _gm_conta(s, booking.company_id)
    if not conta:
        return
    fim = booking.hora_fim or booking.hora_inicio
    try:
        r = _gm_http("PATCH", f"https://www.googleapis.com/calendar/v3/calendars/primary/events/{booking.google_event_id}",
                     params={"sendUpdates": "none"}, headers={"Authorization": f"Bearer {_gm_token(s, conta)}"},
                     json={"start": {"dateTime": f"{booking.data}T{booking.hora_inicio}:00", "timeZone": "America/Sao_Paulo"},
                           "end": {"dateTime": f"{booking.data}T{fim}:00", "timeZone": "America/Sao_Paulo"}})
        if r.status_code >= 400:
            print(f"[agenda_meet] remarcar no Google: {r.status_code} {r.text[:200]}")
    except Exception as e:
        print(f"[agenda_meet] remarcar no Google: {e}")


def _meet_ao_cancelar(s, booking) -> None:
    if not (booking.google_event_id or ""):
        return
    conta = _gm_conta(s, booking.company_id)
    if not conta:
        return
    try:
        r = _gm_http("DELETE", f"https://www.googleapis.com/calendar/v3/calendars/primary/events/{booking.google_event_id}",
                     params={"sendUpdates": "none"}, headers={"Authorization": f"Bearer {_gm_token(s, conta)}"})
        if r.status_code not in (200, 204, 404, 410):
            print(f"[agenda_meet] cancelar no Google: {r.status_code} {r.text[:200]}")
    except Exception as e:
        print(f"[agenda_meet] cancelar no Google: {e}")


# ── Conexão do Google Agenda (admin) ──────────────────────────────────────────

def _meet_config_view(company_id: int) -> dict:
    cid, segredo = _gm_cliente_oauth()
    with _Sess_gm(engine) as s:
        conta = _gm_conta(s, company_id)
        return {"configurado": bool(cid and segredo), "conectado": bool(conta), "email": conta.email if conta else "",
                "redirect": _gm_redirect()}


@app.get("/agenda/google/conectar")
@require_login
async def agenda_google_conectar(request: Request, session: Session = Depends(get_session)):
    ctx = get_tenant_context(request, session)
    if not ctx or ctx.membership.role != "admin":
        return RedirectResponse("/predio", status_code=303)
    cid, segredo = _gm_cliente_oauth()
    if not (cid and segredo):
        set_flash(request, "Configure GOOGLE_CLIENT_ID e GOOGLE_CLIENT_SECRET no Render para conectar o Google Agenda.")
        return RedirectResponse("/predio#reunioes-online", status_code=303)
    estado = _sec_gm.token_urlsafe(24)
    request.session["gm_estado"] = estado
    from urllib.parse import urlencode as _urlenc_gm
    url = "https://accounts.google.com/o/oauth2/v2/auth?" + _urlenc_gm({
        "client_id": cid, "redirect_uri": _gm_redirect(), "response_type": "code", "scope": _GM_ESCOPO,
        "access_type": "offline", "prompt": "consent", "include_granted_scopes": "true", "state": estado})
    return RedirectResponse(url, status_code=302)


@app.get("/agenda/google/callback")
@require_login
async def agenda_google_callback(request: Request, session: Session = Depends(get_session), code: str = "",
                                 state: str = "", error: str = ""):
    ctx = get_tenant_context(request, session)
    if not ctx or ctx.membership.role != "admin":
        return RedirectResponse("/predio", status_code=303)
    esperado = request.session.pop("gm_estado", "")
    if error or not code or not esperado or state != esperado:
        set_flash(request, f"Google Agenda não conectado ({error or 'autorização inválida'}).")
        return RedirectResponse("/predio#reunioes-online", status_code=303)
    cid, segredo = _gm_cliente_oauth()
    from starlette.concurrency import run_in_threadpool as _rtp_gm
    r = await _rtp_gm(_gm_http, "POST", "https://oauth2.googleapis.com/token",
                      data={"code": code, "client_id": cid, "client_secret": segredo, "redirect_uri": _gm_redirect(),
                            "grant_type": "authorization_code"})
    if r.status_code != 200 or not r.json().get("refresh_token"):
        set_flash(request, f"O Google não devolveu o acesso permanente ({r.status_code}). Tente conectar de novo.")
        return RedirectResponse("/predio#reunioes-online", status_code=303)
    dado = r.json()
    email = ""
    try:
        import base64 as _b64_gm
        import json as _json_gm
        carga = dado.get("id_token", "").split(".")[1]
        email = _json_gm.loads(_b64_gm.urlsafe_b64decode(carga + "=" * (-len(carga) % 4))).get("email", "")
    except Exception:
        pass
    conta = session.exec(_sel_gm(AgendaGoogle).where(AgendaGoogle.company_id == ctx.company.id)).first() \
        or AgendaGoogle(company_id=ctx.company.id)
    conta.email, conta.refresh_token = email, dado["refresh_token"]
    conta.access_token = dado.get("access_token", "")
    conta.expira_em = _dt_gm.utcnow() + _td_gm(seconds=int(dado.get("expires_in", 3600)))
    conta.conectado_por_user_id, conta.conectado_em = ctx.user.id, _dt_gm.utcnow()
    session.add(conta)
    session.commit()
    set_flash(request, f"Google Agenda conectado ({email or 'conta Google'}): reuniões online terão link do Google Meet.")
    return RedirectResponse("/predio#reunioes-online", status_code=303)


@app.post("/agenda/google/desconectar")
@require_login
async def agenda_google_desconectar(request: Request, session: Session = Depends(get_session)):
    ctx = get_tenant_context(request, session)
    if ctx and ctx.membership.role == "admin":
        conta = session.exec(_sel_gm(AgendaGoogle).where(AgendaGoogle.company_id == ctx.company.id)).first()
        if conta:
            session.delete(conta)
            session.commit()
    return RedirectResponse("/predio#reunioes-online", status_code=303)


print("[agenda_meet] Link de videochamada para reuniões online carregado.")

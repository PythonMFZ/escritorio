# ui_checkin_semanal.py — Check-in semanal automático via WhatsApp
# Exec'd no namespace do app.py — acessa engine, modelos e WHATSAPP_ACCESS_TOKEN.
#
# FUNCIONAMENTO:
#   1. Toda segunda às 09:00 Brasília → mensagem conversacional para cada cliente
#      com thread WhatsApp vinculada.
#   2. Às 14:00 Brasília → lembrete para quem não respondeu.
#   3. Quando responde → Claude extrai dados financeiros e atualiza o cliente.
#   4. Augur gera resposta personalizada.
#
# ROTAS:
#   GET  /admin/checkin/status              — situação da semana atual + diagnóstico
#   POST /admin/checkin/disparar-agora      — disparo síncrono com resultado detalhado
#   POST /admin/checkin/disparar-lembretes  — lembrete manual
#
# CORREÇÕES v2:
#   - httpx síncrono em vez de asyncio.run() em thread (causava crash no Python 3.14+)
#   - disparar-agora aguarda resultado e retorna log detalhado
#   - parâmetro ?force=1 permite reenviar mesmo já enviado esta semana (testes)

import json      as _json_ck
import os        as _os_ck
import threading as _thread_ck
import time      as _time_ck
from datetime import datetime as _dt_ck, timezone as _tz_ck, timedelta as _td_ck
from typing   import Optional as _Opt_ck
from sqlmodel import Field as _F_ck, SQLModel as _SM_ck, select as _sel_ck, Session as _Ses_ck


# ── Modelo ────────────────────────────────────────────────────────────────────

class CheckinSemanal(_SM_ck, table=True):
    __tablename__  = "checkinsemanal"
    __table_args__ = {"extend_existing": True}
    id:              _Opt_ck[int]     = _F_ck(default=None, primary_key=True)
    company_id:      int              = _F_ck(index=True)
    client_id:       int              = _F_ck(index=True)
    thread_id:       int              = _F_ck(index=True)
    semana:          str              = _F_ck(index=True)   # "2026-05-25" (segunda da semana)
    contact_phone:   str              = _F_ck(default="")
    enviado_at:      _Opt_ck[_dt_ck] = _F_ck(default=None)
    lembrete_at:     _Opt_ck[_dt_ck] = _F_ck(default=None)
    respondido:      bool             = _F_ck(default=False)
    resposta_raw:    str              = _F_ck(default="")
    dados_extraidos: str              = _F_ck(default="")   # JSON
    created_at:      _dt_ck          = _F_ck(default_factory=lambda: _dt_ck.now(_tz_ck.utc))


try:
    _SM_ck.metadata.create_all(engine, tables=[CheckinSemanal.__table__], checkfirst=True)
    print("[checkin] ✅ Tabela checkinsemanal OK")
except Exception as _e_ck_tbl:
    print(f"[checkin] Tabela: {_e_ck_tbl}")


# ── Helpers de data ───────────────────────────────────────────────────────────

def _ck_semana_key(dt: _dt_ck = None) -> str:
    """Retorna a segunda-feira da semana como 'YYYY-MM-DD'."""
    if dt is None:
        dt = _dt_ck.now(_tz_ck.utc)
    return (dt - _td_ck(days=dt.weekday())).strftime("%Y-%m-%d")


# ── Mensagens ─────────────────────────────────────────────────────────────────

_CK_MSG_CHECKIN = (
    "Olá, {nome}! 👋 Vamos conversar um pouquinho sobre como foi sua última semana "
    "para eu poder te ajudar a tomar as melhores decisões. "
    "Me conta como foi: se vendeu bem, se entrou receitas, quanto tem em caixa… "
    "o que você achar relevante. Estou aqui para ouvir!"
)

_CK_MSG_LEMBRETE = (
    "Oi, {nome}! 😊 Ainda não recebi seu check-in desta semana. "
    "Esse acompanhamento é importante para que o Augur possa te dar orientações "
    "cada vez mais precisas e personalizadas. "
    "Quando puder, me conta rapidinho como foi a semana: vendas, caixa, "
    "o que aconteceu de importante. Pode ser bem resumido mesmo! 🙏"
)


# ── Envio síncrono via httpx (sem asyncio.run em thread) ─────────────────────

def _ck_enviar_sync(contact_phone: str, meta_phone_id: str, mensagem: str) -> tuple[bool, str]:
    """
    Envia mensagem WhatsApp via httpx síncrono.
    Não usa asyncio.run() — seguro para chamar em qualquer thread.
    """
    try:
        import httpx as _hx_ck
    except ImportError:
        return False, "httpx não instalado"

    token   = _os_ck.environ.get("WHATSAPP_ACCESS_TOKEN", "")
    version = _os_ck.environ.get("WHATSAPP_GRAPH_VERSION", "v18.0")

    if not token:
        return False, "WHATSAPP_ACCESS_TOKEN não configurado"
    if not meta_phone_id:
        return False, "meta_phone_number_id vazio na config do canal"

    digits = "".join(c for c in (contact_phone or "") if c.isdigit())
    if not digits:
        return False, f"Número inválido: {contact_phone!r}"

    url = f"https://graph.facebook.com/{version}/{meta_phone_id}/messages"
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type":    "individual",
        "to":                digits,
        "type":              "text",
        "text":              {"preview_url": False, "body": mensagem[:4096]},
    }
    try:
        resp = _hx_ck.post(
            url,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type":  "application/json",
            },
            json=payload,
            timeout=20.0,
        )
        if 200 <= resp.status_code < 300:
            return True, ""
        return False, f"HTTP {resp.status_code}: {resp.text[:400]}"
    except Exception as _e_send:
        return False, str(_e_send)


# ── Extração de dados financeiros com Claude ──────────────────────────────────

def _ck_extrair_dados(texto: str, client_name: str) -> dict:
    """Usa Claude Haiku para extrair dados financeiros do texto livre do check-in."""
    api_key = _os_ck.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        return {}
    try:
        import requests as _req_ck
        prompt = (
            f'O cliente "{client_name}" enviou o seguinte check-in semanal via WhatsApp:\n\n'
            f'"{texto}"\n\n'
            "Extraia os dados financeiros mencionados. Retorne APENAS um JSON com os campos abaixo.\n"
            "Use null para campos não mencionados ou incertos.\n"
            '{\n'
            '  "cash_balance_brl": <número ou null>,\n'
            '  "revenue_monthly_brl": <número ou null>,\n'
            '  "receita_semanal_brl": <número ou null>,\n'
            '  "delinquency_brl": <número ou null>,\n'
            '  "resumo": "<frase curta descrevendo a semana do cliente>"\n'
            '}\n'
            "Retorne APENAS o JSON, sem texto antes ou depois."
        )
        resp = _req_ck.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model":      "claude-haiku-4-5-20251001",
                "max_tokens": 300,
                "messages":   [{"role": "user", "content": prompt}],
            },
            timeout=30,
        )
        resp.raise_for_status()
        raw = resp.json()["content"][0]["text"].strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        return _json_ck.loads(raw.strip())
    except Exception as _e:
        print(f"[checkin] Extração de dados: {_e}")
        return {}


def _ck_atualizar_cliente(session, client_id: int, dados: dict):
    """Atualiza campos do Client com os dados extraídos do check-in."""
    try:
        cliente = session.get(Client, client_id)
        if not cliente:
            return
        changed = False
        if dados.get("cash_balance_brl") is not None:
            cliente.cash_balance_brl = float(dados["cash_balance_brl"])
            changed = True
        if dados.get("revenue_monthly_brl") is not None:
            cliente.revenue_monthly_brl = float(dados["revenue_monthly_brl"])
            changed = True
        if dados.get("delinquency_brl") is not None:
            cliente.delinquency_brl = float(dados["delinquency_brl"])
            changed = True
        if changed:
            session.add(cliente)
            session.commit()
            print(f"[checkin] Cliente {client_id} atualizado: {dados}")
    except Exception as _e:
        print(f"[checkin] Atualizar cliente {client_id}: {_e}")


# ── Resposta do Augur ao check-in ─────────────────────────────────────────────

def _ck_gerar_resposta_augur(client_data: dict, resposta_cliente: str) -> str:
    try:
        from ai_assistant.assistant import ask as _augur_ask
        pergunta = (
            f"O cliente acabou de enviar o check-in semanal: \"{resposta_cliente[:800]}\". "
            "Responda em até 3 parágrafos curtos: reconheça o que ele compartilhou, "
            "destaque 1 ponto de atenção ou oportunidade, e termine com uma pergunta "
            "que aprofunde o diagnóstico desta semana."
        )
        result = _augur_ask(question=pergunta, client_data=client_data, n_similar_cases=2)
        return (result.get("response") or "").strip()
    except Exception as _e:
        print(f"[checkin] Gerar resposta Augur: {_e}")
        return ""


# ── Processamento de resposta — chamado pelo webhook ─────────────────────────

def checkin_processar_resposta(
    session,
    company_id:   int,
    client_id:    int,
    thread_id:    int,
    message_body: str,
) -> _Opt_ck[str]:
    """
    Verifica se há check-in aberto para este cliente nesta semana.
    Se sim: marca respondido, extrai dados, atualiza cliente, retorna resposta Augur.
    Se não: retorna None (segue fluxo normal do Augur).
    """
    try:
        semana = _ck_semana_key()
        ck = session.exec(
            _sel_ck(CheckinSemanal)
            .where(
                CheckinSemanal.company_id == company_id,
                CheckinSemanal.client_id  == client_id,
                CheckinSemanal.semana     == semana,
                CheckinSemanal.respondido == False,
            )
        ).first()

        if not ck:
            return None

        print(f"[checkin] Resposta recebida — cliente {client_id}, semana {semana}")
        ck.respondido   = True
        ck.resposta_raw = message_body[:2000]
        session.add(ck)
        session.flush()

        client      = session.get(Client, client_id)
        client_name = client.name if client else "cliente"

        dados = _ck_extrair_dados(message_body, client_name)
        if dados:
            ck.dados_extraidos = _json_ck.dumps(dados, ensure_ascii=False)
            session.add(ck)
            _ck_atualizar_cliente(session, client_id, dados)

        session.commit()

        try:
            client_data = _waz_build_client_data(session, company_id, client)
        except Exception:
            client_data = {"name": client_name}

        return _ck_gerar_resposta_augur(client_data, message_body) or None

    except Exception as _e:
        print(f"[checkin] processar_resposta: {_e}")
        return None


# ── Disparo de check-ins (síncrono, retorna log) ──────────────────────────────

def _ck_disparar_checkins(semana: str, force: bool = False) -> dict:
    """
    Envia check-in para todos os clientes ativos com thread WhatsApp.
    force=True: reenvia mesmo que já tenha sido enviado nesta semana (para testes).
    Retorna dict com resumo e log detalhado.
    """
    print(f"[checkin] Disparando check-ins — semana {semana} (force={force})")
    log      = []
    enviados = 0
    pulados  = 0
    erros    = 0

    with _Ses_ck(engine) as db:
        configs = db.exec(
            _sel_ck(WhatsAppChannelConfig)
            .where(WhatsAppChannelConfig.is_enabled == True)
        ).all()

        if not configs:
            log.append("⚠️  Nenhum canal WhatsApp habilitado (WhatsAppChannelConfig.is_enabled=True).")
            return {"enviados": 0, "pulados": 0, "erros": 0, "log": log}

        for config in configs:
            log.append(f"Canal: empresa {config.company_id} | phone_id={config.meta_phone_number_id or '(vazio)'}")
            try:
                threads = db.exec(
                    _sel_ck(WhatsAppThread)
                    .where(
                        WhatsAppThread.company_id == config.company_id,
                        WhatsAppThread.client_id  != None,
                        WhatsAppThread.is_group   == False,
                    )
                    .order_by(WhatsAppThread.id.desc())
                ).all()

                if not threads:
                    log.append("  ⚠️  Sem threads vinculadas a clientes.")
                    continue

                # Thread mais recente por cliente
                visto: set = set()
                for thread in threads:
                    if thread.client_id in visto:
                        continue
                    visto.add(thread.client_id)

                    if not force:
                        ja = db.exec(
                            _sel_ck(CheckinSemanal)
                            .where(
                                CheckinSemanal.company_id == config.company_id,
                                CheckinSemanal.client_id  == thread.client_id,
                                CheckinSemanal.semana     == semana,
                            )
                        ).first()
                        if ja:
                            pulados += 1
                            log.append(f"  ⏭  Pulado (já enviado): client_id={thread.client_id}")
                            continue

                    client = db.get(Client, thread.client_id)
                    if not client:
                        log.append(f"  ⚠️  Client {thread.client_id} não encontrado.")
                        continue

                    nome = (client.name or "cliente").split()[0]
                    msg  = _CK_MSG_CHECKIN.format(nome=nome)

                    ok, err = _ck_enviar_sync(
                        thread.contact_phone,
                        config.meta_phone_number_id,
                        msg,
                    )

                    if ok:
                        # Remove registro antigo se force=True, cria novo
                        if force:
                            antigo = db.exec(
                                _sel_ck(CheckinSemanal)
                                .where(
                                    CheckinSemanal.company_id == config.company_id,
                                    CheckinSemanal.client_id  == thread.client_id,
                                    CheckinSemanal.semana     == semana,
                                )
                            ).first()
                            if antigo:
                                db.delete(antigo)
                                db.flush()

                        db.add(CheckinSemanal(
                            company_id=config.company_id,
                            client_id=thread.client_id,
                            thread_id=thread.id,
                            semana=semana,
                            contact_phone=thread.contact_phone,
                            enviado_at=_dt_ck.now(_tz_ck.utc),
                        ))
                        db.commit()
                        enviados += 1
                        log.append(f"  ✅ Enviado: {client.name} → {thread.contact_phone}")
                    else:
                        erros += 1
                        log.append(f"  ❌ Falhou: {client.name} ({thread.contact_phone}): {err}")

            except Exception as _e:
                erros += 1
                log.append(f"  ❌ Erro empresa {config.company_id}: {_e}")
                print(f"[checkin] Empresa {config.company_id}: {_e}")

    msg_final = f"Total: {enviados} enviados, {pulados} pulados, {erros} erros."
    log.append(msg_final)
    print(f"[checkin] {msg_final}")
    return {"enviados": enviados, "pulados": pulados, "erros": erros, "log": log}


def _ck_disparar_lembretes(semana: str) -> dict:
    """Envia lembrete para quem não respondeu ao check-in."""
    print(f"[checkin] Disparando lembretes — semana {semana}")
    log      = []
    enviados = 0
    erros    = 0

    with _Ses_ck(engine) as db:
        pendentes = db.exec(
            _sel_ck(CheckinSemanal)
            .where(
                CheckinSemanal.semana      == semana,
                CheckinSemanal.respondido  == False,
                CheckinSemanal.lembrete_at == None,
            )
        ).all()

        if not pendentes:
            log.append("Nenhum check-in pendente de lembrete.")
            return {"enviados": 0, "erros": 0, "log": log}

        for ck in pendentes:
            try:
                client = db.get(Client, ck.client_id)
                if not client:
                    continue

                config = db.exec(
                    _sel_ck(WhatsAppChannelConfig)
                    .where(
                        WhatsAppChannelConfig.company_id == ck.company_id,
                        WhatsAppChannelConfig.is_enabled == True,
                    )
                ).first()
                if not config:
                    log.append(f"  ⚠️  Sem canal ativo para empresa {ck.company_id}")
                    continue

                nome = (client.name or "cliente").split()[0]
                msg  = _CK_MSG_LEMBRETE.format(nome=nome)

                ok, err = _ck_enviar_sync(ck.contact_phone, config.meta_phone_number_id, msg)

                if ok:
                    ck.lembrete_at = _dt_ck.now(_tz_ck.utc)
                    db.add(ck)
                    db.commit()
                    enviados += 1
                    log.append(f"  ✅ Lembrete: {client.name}")
                else:
                    erros += 1
                    log.append(f"  ❌ Falhou: {client.name}: {err}")

            except Exception as _e:
                erros += 1
                log.append(f"  ❌ Erro: {_e}")

    log.append(f"Total: {enviados} lembretes enviados, {erros} erros.")
    return {"enviados": enviados, "erros": erros, "log": log}


# ── Scheduler ─────────────────────────────────────────────────────────────────

def _ck_scheduler_loop():
    """Daemon thread: verifica a cada 60s se é hora de disparar."""
    print("[checkin] Scheduler iniciado — check-ins toda segunda às 09:00 BRT.")
    _time_ck.sleep(30)   # aguarda app inicializar completamente

    _ultimo_checkin  = None
    _ultimo_lembrete = None

    while True:
        try:
            now_br = _dt_ck.now(_tz_ck.utc) - _td_ck(hours=3)
            semana = _ck_semana_key(now_br)

            if now_br.weekday() == 0:   # segunda-feira
                hora = now_br.hour

                if hora == 9 and _ultimo_checkin != semana:
                    _ultimo_checkin = semana
                    # Roda em thread separada para não bloquear o scheduler
                    _thread_ck.Thread(
                        target=_ck_disparar_checkins,
                        args=(semana, False),
                        daemon=True,
                        name="checkin-disparo",
                    ).start()

                if hora == 14 and _ultimo_lembrete != semana:
                    _ultimo_lembrete = semana
                    _thread_ck.Thread(
                        target=_ck_disparar_lembretes,
                        args=(semana,),
                        daemon=True,
                        name="checkin-lembrete",
                    ).start()

        except Exception as _e:
            print(f"[checkin] Scheduler erro: {_e}")

        _time_ck.sleep(60)


_thread_ck.Thread(target=_ck_scheduler_loop, daemon=True, name="checkin-semanal").start()


# ── Rotas admin ───────────────────────────────────────────────────────────────

@app.get("/admin/checkin/status")
@require_login
async def checkin_status(request: Request, session: Session = Depends(get_session)):
    ctx = get_tenant_context(request, session)
    if not ctx or ctx.membership.role not in ("admin", "owner"):
        return JSONResponse({"erro": "Sem permissão."}, status_code=403)

    semana = _ck_semana_key()

    # Diagnóstico
    diag = {}

    token = _os_ck.environ.get("WHATSAPP_ACCESS_TOKEN", "")
    diag["whatsapp_token"] = "✅ configurado" if token else "❌ WHATSAPP_ACCESS_TOKEN ausente"

    canal = session.exec(
        _sel_ck(WhatsAppChannelConfig)
        .where(WhatsAppChannelConfig.company_id == ctx.company.id)
    ).first()
    if canal:
        diag["canal"] = {
            "is_enabled":         canal.is_enabled,
            "meta_phone_number_id": canal.meta_phone_number_id or "(vazio)",
            "status": "✅ habilitado" if canal.is_enabled else "❌ desabilitado",
        }
    else:
        diag["canal"] = "❌ Nenhum canal WhatsApp cadastrado"

    threads_com_cliente = session.exec(
        _sel_ck(WhatsAppThread)
        .where(
            WhatsAppThread.company_id == ctx.company.id,
            WhatsAppThread.client_id  != None,
            WhatsAppThread.is_group   == False,
        )
    ).all()
    diag["threads_com_cliente"] = len(threads_com_cliente)

    # Hora atual BRT
    now_br = _dt_ck.now(_tz_ck.utc) - _td_ck(hours=3)
    diag["hora_brt"] = now_br.strftime("%A %d/%m %H:%M")
    diag["e_segunda"] = now_br.weekday() == 0

    # Check-ins desta semana
    checkins = session.exec(
        _sel_ck(CheckinSemanal)
        .where(
            CheckinSemanal.company_id == ctx.company.id,
            CheckinSemanal.semana     == semana,
        )
    ).all()

    return JSONResponse({
        "semana":      semana,
        "diagnostico": diag,
        "total":       len(checkins),
        "respondidos": sum(1 for c in checkins if c.respondido),
        "aguardando":  sum(1 for c in checkins if not c.respondido),
        "detalhes": [
            {
                "client_id":    c.client_id,
                "phone":        c.contact_phone,
                "enviado_at":   str(c.enviado_at)[:16] if c.enviado_at else None,
                "respondido":   c.respondido,
                "lembrete_at":  str(c.lembrete_at)[:16] if c.lembrete_at else None,
                "resumo": (
                    _json_ck.loads(c.dados_extraidos).get("resumo", "")
                    if c.dados_extraidos else ""
                ),
            }
            for c in checkins
        ],
    })


@app.post("/admin/checkin/disparar-agora")
@require_login
async def checkin_disparar_agora(request: Request, session: Session = Depends(get_session)):
    """
    Dispara check-ins imediatamente e aguarda resultado.
    Aceita ?force=1 para reenviar mesmo que já tenha sido enviado nesta semana.
    """
    ctx = get_tenant_context(request, session)
    if not ctx or ctx.membership.role not in ("admin", "owner"):
        return JSONResponse({"ok": False, "erro": "Sem permissão."}, status_code=403)

    force  = request.query_params.get("force", "0") == "1"
    semana = _ck_semana_key()

    import asyncio as _aio_ck
    loop     = _aio_ck.get_event_loop()
    resultado = await loop.run_in_executor(None, _ck_disparar_checkins, semana, force)

    return JSONResponse({
        "ok":     resultado["erros"] == 0,
        "semana": semana,
        "force":  force,
        **resultado,
    })


@app.post("/admin/checkin/disparar-lembretes")
@require_login
async def checkin_disparar_lembretes_agora(
    request: Request,
    session: Session = Depends(get_session),
):
    ctx = get_tenant_context(request, session)
    if not ctx or ctx.membership.role not in ("admin", "owner"):
        return JSONResponse({"ok": False, "erro": "Sem permissão."}, status_code=403)

    semana = _ck_semana_key()

    import asyncio as _aio_ck
    loop      = _aio_ck.get_event_loop()
    resultado = await loop.run_in_executor(None, _ck_disparar_lembretes, semana)

    return JSONResponse({"ok": True, "semana": semana, **resultado})


print("[checkin] ✅ Módulo de check-in semanal carregado (v2 — httpx síncrono).")

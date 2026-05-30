# ui_checkin_semanal.py — Check-in semanal automático via WhatsApp
# Exec'd no namespace do app.py — acessa engine, modelos e _try_send_whatsapp_text.
#
# FUNCIONAMENTO:
#   1. Toda segunda às 09:00 Brasília → envia mensagem conversacional para cada
#      cliente ativo com thread WhatsApp vinculada.
#   2. Às 14:00 Brasília → lembrete para quem não respondeu.
#   3. Quando o cliente responde → Claude extrai dados financeiros do texto livre
#      e atualiza o registro do cliente automaticamente.
#   4. Augur gera resposta personalizada ao check-in.
#
# ROTAS:
#   GET  /admin/checkin/status          — situação da semana atual
#   POST /admin/checkin/disparar-agora  — disparo manual (testes)

import asyncio   as _asyncio_ck
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
    id:              _Opt_ck[int]       = _F_ck(default=None, primary_key=True)
    company_id:      int                = _F_ck(index=True)
    client_id:       int                = _F_ck(index=True)
    thread_id:       int                = _F_ck(index=True)
    semana:          str                = _F_ck(index=True)   # "2026-05-25" (segunda da semana)
    contact_phone:   str                = _F_ck(default="")
    enviado_at:      _Opt_ck[_dt_ck]   = _F_ck(default=None)
    lembrete_at:     _Opt_ck[_dt_ck]   = _F_ck(default=None)
    respondido:      bool               = _F_ck(default=False)
    resposta_raw:    str                = _F_ck(default="")
    dados_extraidos: str                = _F_ck(default="")   # JSON
    created_at:      _dt_ck            = _F_ck(default_factory=lambda: _dt_ck.now(_tz_ck.utc))


try:
    _SM_ck.metadata.create_all(engine, tables=[CheckinSemanal.__table__])
    print("[checkin] Tabela checkinsemanal OK")
except Exception as _e_ck_tbl:
    print(f"[checkin] Tabela: {_e_ck_tbl}")


# ── Helpers de data ───────────────────────────────────────────────────────────

def _ck_semana_key(dt: _dt_ck = None) -> str:
    """Retorna a segunda-feira da semana como 'YYYY-MM-DD'."""
    if not dt:
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
            "Só preencha cash_balance_brl se o cliente citou explicitamente o saldo atual em caixa.\n"
            "Só preencha revenue_monthly_brl se mencionou faturamento mensal (não semanal).\n\n"
            "{\n"
            '  "cash_balance_brl": <número ou null>,\n'
            '  "revenue_monthly_brl": <número ou null>,\n'
            '  "receita_semanal_brl": <número ou null — entradas desta semana>,\n'
            '  "delinquency_brl": <número ou null — inadimplência mencionada>,\n'
            '  "resumo": "<frase curta descrevendo a semana do cliente>"\n'
            "}\n\n"
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
                "model": "claude-haiku-4-5-20251001",
                "max_tokens": 300,
                "messages": [{"role": "user", "content": prompt}],
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
            print(f"[checkin] Cliente {client_id} atualizado com dados do check-in: {dados}")
    except Exception as _e:
        print(f"[checkin] Atualizar cliente {client_id}: {_e}")


# ── Resposta do Augur ao check-in ─────────────────────────────────────────────

def _ck_gerar_resposta_augur(client_data: dict, resposta_cliente: str) -> str:
    """Gera resposta personalizada do Augur reconhecendo o check-in."""
    try:
        from ai_assistant.assistant import ask as _augur_ask
        pergunta = (
            f"O cliente acabou de enviar o check-in semanal: \"{resposta_cliente[:800]}\". "
            "Responda em até 3 parágrafos curtos: reconheça o que ele compartilhou, "
            "destaque 1 ponto de atenção ou oportunidade com base nos dados dele, "
            "e termine com uma pergunta que aprofunde o diagnóstico desta semana."
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
    - Se sim: marca respondido, extrai dados, atualiza cliente, retorna resposta do Augur.
    - Se não: retorna None (segue fluxo normal do Augur).
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
            return None  # não é resposta a check-in → fluxo normal

        print(f"[checkin] Resposta recebida — cliente {client_id}, semana {semana}")

        ck.respondido  = True
        ck.resposta_raw = message_body[:2000]
        session.add(ck)
        session.flush()

        client = session.get(Client, client_id)
        client_name = client.name if client else "cliente"

        dados = _ck_extrair_dados(message_body, client_name)
        if dados:
            ck.dados_extraidos = _json_ck.dumps(dados, ensure_ascii=False)
            session.add(ck)
            _ck_atualizar_cliente(session, client_id, dados)

        session.commit()

        # Reconstrói client_data com dados atualizados para gerar resposta
        try:
            client_data = _waz_build_client_data(session, company_id, client)
        except Exception:
            client_data = {"name": client_name}

        return _ck_gerar_resposta_augur(client_data, message_body) or None

    except Exception as _e:
        print(f"[checkin] processar_resposta: {_e}")
        return None


# ── Envio via WhatsApp (async) ────────────────────────────────────────────────

async def _ck_enviar_msg(contact_phone: str, meta_phone_id: str, mensagem: str):
    class _MinCfg:
        is_enabled           = True
        meta_phone_number_id = meta_phone_id

    ok, err, _ = await _try_send_whatsapp_text(
        config=_MinCfg(),
        recipient_id=contact_phone,
        recipient_type="individual",
        body=mensagem,
    )
    return ok, err


# ── Disparo de check-ins ──────────────────────────────────────────────────────

def _ck_disparar_checkins(semana: str):
    """Envia mensagem de check-in para todos os clientes ativos com WhatsApp."""
    print(f"[checkin] Disparando check-ins — semana {semana}")
    enviados = 0

    with _Ses_ck(engine) as db:
        configs = db.exec(
            _sel_ck(WhatsAppChannelConfig)
            .where(WhatsAppChannelConfig.is_enabled == True)
        ).all()

        for config in configs:
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

                # Pega só a thread mais recente por cliente
                visto: set = set()
                for thread in threads:
                    if thread.client_id in visto:
                        continue
                    visto.add(thread.client_id)

                    # Já enviou esta semana?
                    ja_enviado = db.exec(
                        _sel_ck(CheckinSemanal)
                        .where(
                            CheckinSemanal.company_id == config.company_id,
                            CheckinSemanal.client_id  == thread.client_id,
                            CheckinSemanal.semana     == semana,
                        )
                    ).first()
                    if ja_enviado:
                        continue

                    client = db.get(Client, thread.client_id)
                    if not client:
                        continue

                    nome = client.name.split()[0]
                    msg  = _CK_MSG_CHECKIN.format(nome=nome)

                    ok, err = _asyncio_ck.run(_ck_enviar_msg(
                        thread.contact_phone,
                        config.meta_phone_number_id,
                        msg,
                    ))

                    if ok:
                        ck = CheckinSemanal(
                            company_id=config.company_id,
                            client_id=thread.client_id,
                            thread_id=thread.id,
                            semana=semana,
                            contact_phone=thread.contact_phone,
                            enviado_at=_dt_ck.now(_tz_ck.utc),
                        )
                        db.add(ck)
                        db.commit()
                        enviados += 1
                        print(f"[checkin] Enviado para {client.name} ({thread.contact_phone})")
                    else:
                        print(f"[checkin] Falha {client.name}: {err}")

            except Exception as _e:
                print(f"[checkin] Empresa {config.company_id}: {_e}")

    print(f"[checkin] Total enviados: {enviados}")


def _ck_disparar_lembretes(semana: str):
    """Envia lembrete para quem não respondeu ao check-in."""
    print(f"[checkin] Disparando lembretes — semana {semana}")
    enviados = 0

    with _Ses_ck(engine) as db:
        pendentes = db.exec(
            _sel_ck(CheckinSemanal)
            .where(
                CheckinSemanal.semana      == semana,
                CheckinSemanal.respondido  == False,
                CheckinSemanal.lembrete_at == None,
            )
        ).all()

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
                    continue

                nome = client.name.split()[0]
                msg  = _CK_MSG_LEMBRETE.format(nome=nome)

                ok, err = _asyncio_ck.run(_ck_enviar_msg(
                    ck.contact_phone,
                    config.meta_phone_number_id,
                    msg,
                ))

                if ok:
                    ck.lembrete_at = _dt_ck.now(_tz_ck.utc)
                    db.add(ck)
                    db.commit()
                    enviados += 1
                    print(f"[checkin] Lembrete para {client.name}")
                else:
                    print(f"[checkin] Lembrete falhou {client.name}: {err}")

            except Exception as _e:
                print(f"[checkin] Lembrete erro: {_e}")

    print(f"[checkin] Lembretes enviados: {enviados}")


# ── Scheduler ─────────────────────────────────────────────────────────────────

def _ck_scheduler_loop():
    """Daemon thread: verifica a cada 60s se é hora de disparar check-ins/lembretes."""
    print("[checkin] Scheduler iniciado — check-ins toda segunda às 09:00 Brasília.")
    _time_ck.sleep(60)

    _ultimo_checkin  = None
    _ultimo_lembrete = None

    while True:
        try:
            # Converte para horário Brasília (UTC-3)
            now_br = _dt_ck.now(_tz_ck.utc) - _td_ck(hours=3)
            semana = _ck_semana_key(now_br)

            if now_br.weekday() == 0:   # segunda-feira
                hora = now_br.hour

                if hora == 9 and _ultimo_checkin != semana:
                    _ultimo_checkin = semana
                    _thread_ck.Thread(
                        target=_ck_disparar_checkins,
                        args=(semana,),
                        daemon=True,
                    ).start()

                if hora == 14 and _ultimo_lembrete != semana:
                    _ultimo_lembrete = semana
                    _thread_ck.Thread(
                        target=_ck_disparar_lembretes,
                        args=(semana,),
                        daemon=True,
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
    checkins = session.exec(
        _sel_ck(CheckinSemanal)
        .where(
            CheckinSemanal.company_id == ctx.company.id,
            CheckinSemanal.semana     == semana,
        )
    ).all()

    return JSONResponse({
        "semana":      semana,
        "total":       len(checkins),
        "respondidos": sum(1 for c in checkins if c.respondido),
        "aguardando":  sum(1 for c in checkins if not c.respondido),
        "detalhes": [
            {
                "client_id":   c.client_id,
                "enviado_at":  str(c.enviado_at)[:16] if c.enviado_at else None,
                "respondido":  c.respondido,
                "lembrete_at": str(c.lembrete_at)[:16] if c.lembrete_at else None,
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
    ctx = get_tenant_context(request, session)
    if not ctx or ctx.membership.role not in ("admin", "owner"):
        return JSONResponse({"ok": False, "erro": "Sem permissão."}, status_code=403)

    semana = _ck_semana_key()
    _thread_ck.Thread(
        target=_ck_disparar_checkins,
        args=(semana,),
        daemon=True,
    ).start()
    return JSONResponse({
        "ok":  True,
        "msg": f"Check-ins disparados para semana {semana}. Verifique /admin/checkin/status em instantes.",
    })


print("[checkin] Modulo de check-in semanal carregado.")

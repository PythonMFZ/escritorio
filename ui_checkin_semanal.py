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

    # Normaliza para número internacional brasileiro se necessário.
    # WhatsApp exige código de país: 5511999999999 (13 dígitos) ou 55119999-9999 (12 dígitos).
    # Números de 10-11 dígitos provavelmente são brasileiros sem o +55.
    if len(digits) in (10, 11) and not digits.startswith("55"):
        digits = "55" + digits
    elif len(digits) == 9 and not digits.startswith("55"):
        # só o número sem DDD — não conseguimos normalizar
        pass

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
            return True, digits  # retorna número normalizado para log
        return False, f"HTTP {resp.status_code}: {resp.text[:400]}"
    except Exception as _e_send:
        return False, str(_e_send)


def _ck_enviar_template_sync(
    contact_phone: str,
    meta_phone_id: str,
    template_name: str,
    language_code: str,
    body_params: list[str],
) -> tuple[bool, str]:
    """Envia template WhatsApp aprovado — funciona fora da janela de 24h."""
    try:
        import httpx as _hx_ck
    except ImportError:
        return False, "httpx não instalado"

    token   = _os_ck.environ.get("WHATSAPP_ACCESS_TOKEN", "")
    version = _os_ck.environ.get("WHATSAPP_GRAPH_VERSION", "v18.0")

    if not token:
        return False, "WHATSAPP_ACCESS_TOKEN não configurado"

    digits = "".join(c for c in (contact_phone or "") if c.isdigit())
    if not digits:
        return False, f"Número inválido: {contact_phone!r}"
    if len(digits) in (10, 11) and not digits.startswith("55"):
        digits = "55" + digits

    components = []
    if body_params:
        components.append({
            "type": "body",
            "parameters": [{"type": "text", "text": p} for p in body_params],
        })

    payload = {
        "messaging_product": "whatsapp",
        "recipient_type":    "individual",
        "to":                digits,
        "type":              "template",
        "template": {
            "name":     template_name,
            "language": {"code": language_code},
            "components": components,
        },
    }
    try:
        resp = _hx_ck.post(
            f"https://graph.facebook.com/{version}/{meta_phone_id}/messages",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json=payload,
            timeout=20.0,
        )
        if 200 <= resp.status_code < 300:
            return True, digits
        return False, f"HTTP {resp.status_code}: {resp.text[:400]}"
    except Exception as _e:
        return False, str(_e)


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

                    # Prefere o whatsapp_phone do usuário vinculado ao cliente
                    phone_destino = thread.contact_phone
                    try:
                        membro = db.exec(
                            select(Membership).where(
                                Membership.company_id == config.company_id,
                                Membership.client_id  == client.id,
                                Membership.role       == "cliente",
                            )
                        ).first()
                        if membro:
                            usuario = db.get(User, membro.user_id)
                            if usuario and usuario.whatsapp_phone:
                                phone_destino = usuario.whatsapp_phone
                    except Exception:
                        pass

                    nome = (client.name or "cliente").split()[0]
                    msg  = _CK_MSG_CHECKIN.format(nome=nome)

                    ok, err = _ck_enviar_sync(
                        phone_destino,
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
                            contact_phone=phone_destino,
                            enviado_at=_dt_ck.now(_tz_ck.utc),
                        ))
                        db.commit()
                        enviados += 1
                        log.append(f"  ✅ Enviado: {client.name} → {phone_destino}")
                    else:
                        erros += 1
                        log.append(f"  ❌ Falhou: {client.name} ({phone_destino}): {err}")

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

@app.get("/admin/checkin", response_class=HTMLResponse)
@require_login
async def checkin_admin_page(request: Request, session: Session = Depends(get_session)):
    ctx = get_tenant_context(request, session)
    if not ctx or ctx.membership.role not in ("admin", "owner", "equipe"):
        return RedirectResponse("/", status_code=303)
    cc = get_client_or_none(session, ctx.company.id, get_active_client_id(request, session, ctx))
    return render("checkin_admin.html", request=request, context={
        "current_user": ctx.user, "current_company": ctx.company,
        "role": ctx.membership.role, "current_client": cc,
    })


TEMPLATES["checkin_admin.html"] = r"""
{% extends "base.html" %}
{% block content %}
<style>
  .ck-card{border:1px solid var(--mc-border);border-radius:14px;padding:1.25rem;background:#fff;margin-bottom:1rem;}
  .ck-log{font-family:monospace;font-size:.78rem;background:#f8f8f8;border-radius:8px;padding:1rem;max-height:340px;overflow-y:auto;white-space:pre-wrap;word-break:break-all;}
  .ck-stat{font-size:1.6rem;font-weight:700;}
  .ck-label{font-size:.72rem;color:var(--mc-muted);text-transform:uppercase;letter-spacing:.05em;}
</style>

<div class="d-flex justify-content-between align-items-center mb-3">
  <div>
    <h4 class="mb-0">Check-in Semanal</h4>
    <div class="muted small">Disparo e monitoramento dos check-ins WhatsApp às segundas-feiras.</div>
  </div>
  <a href="/admin/whatsapp" class="btn btn-outline-secondary btn-sm">← WhatsApp</a>
</div>

{# ── Status atual ── #}
<div class="ck-card" id="cardStatus">
  <div class="fw-semibold mb-2">📊 Status da semana</div>
  <div class="row g-3 text-center" id="statsRow">
    <div class="col"><div class="ck-stat" id="stTotal">—</div><div class="ck-label">Enviados</div></div>
    <div class="col"><div class="ck-stat text-success" id="stResp">—</div><div class="ck-label">Respondidos</div></div>
    <div class="col"><div class="ck-stat text-warning" id="stAg">—</div><div class="ck-label">Aguardando</div></div>
    <div class="col"><div class="ck-stat text-muted" id="stSemana">—</div><div class="ck-label">Semana</div></div>
  </div>
  <div id="diagBox" class="mt-3" style="display:none;">
    <div class="fw-semibold small mb-1">🔍 Diagnóstico</div>
    <div class="ck-log" id="diagText"></div>
  </div>
  <div class="d-flex gap-2 mt-3">
    <button class="btn btn-outline-secondary btn-sm" onclick="carregarStatus()">🔄 Atualizar status</button>
    <button class="btn btn-outline-secondary btn-sm" onclick="toggleDiag()">🔍 Diagnóstico</button>
  </div>
</div>

{# ── Ações ── #}
<div class="ck-card">
  <div class="fw-semibold mb-2">⚡ Ações manuais</div>
  <div class="row g-3">
    <div class="col-md-6">
      <div class="border rounded p-3">
        <div class="fw-semibold mb-1">Disparar check-ins agora</div>
        <div class="muted small mb-2">Envia para todos os clientes que ainda não receberam nesta semana.</div>
        <div class="form-check mb-2">
          <input class="form-check-input" type="checkbox" id="forceCheck">
          <label class="form-check-label small" for="forceCheck">Forçar reenvio (mesmo que já enviado esta semana)</label>
        </div>
        <button class="btn btn-primary btn-sm" onclick="disparar()"><i class="bi bi-send me-1"></i>Disparar agora</button>
      </div>
    </div>
    <div class="col-md-6">
      <div class="border rounded p-3">
        <div class="fw-semibold mb-1">Enviar lembretes</div>
        <div class="muted small mb-2">Reenvia para quem não respondeu nos últimos 2 dias.</div>
        <button class="btn btn-outline-warning btn-sm" onclick="lembretes()"><i class="bi bi-bell me-1"></i>Enviar lembretes</button>
      </div>
    </div>
  </div>
</div>

{# ── Template aprovado (comunicado_augur) ── #}
<div class="ck-card" style="border-color:#0d6efd33;background:#f0f5ff;">
  <div class="fw-semibold mb-1">📨 Comunicado Augur <span class="badge bg-success ms-1" style="font-size:.65rem;">Template aprovado</span></div>
  <div class="muted small mb-3">Envia o template <strong>comunicado_augur</strong> para todos os usuários com WhatsApp cadastrado.<br>
  Funciona mesmo fora da janela de 24h — o nome do usuário é inserido automaticamente como cumprimento.</div>
  <button class="btn btn-primary btn-sm" onclick="enviarTemplate('comunicado_augur','pt_BR')">
    <i class="bi bi-megaphone me-1"></i>Enviar Comunicado Augur para todos
  </button>
</div>

{# ── Mensagem personalizada ── #}
<div class="ck-card">
  <div class="fw-semibold mb-2">📢 Mensagem livre para todos <span class="badge bg-warning text-dark ms-1" style="font-size:.65rem;">Só para janela 24h</span></div>
  <div class="muted small mb-2">Envia texto livre para usuários que interagiram via WhatsApp nas últimas 24h.</div>
  <textarea id="msgPersonalizada" class="form-control mb-2" rows="4" placeholder="Digite sua mensagem aqui..."></textarea>
  <button class="btn btn-outline-primary btn-sm" onclick="enviarMsgPersonalizada()">
    <i class="bi bi-broadcast me-1"></i>Enviar para todos
  </button>
</div>

{# ── Log de resultado ── #}
<div class="ck-card" id="logCard" style="display:none;">
  <div class="d-flex justify-content-between align-items-center mb-2">
    <div class="fw-semibold">📋 Log da operação</div>
    <span id="logBadge" class="badge bg-secondary">—</span>
  </div>
  <div class="ck-log" id="logBox"></div>
</div>

<script>
let _diagVisible = false;

async function carregarStatus() {
  try {
    const r = await fetch('/admin/checkin/status');
    const d = await r.json();
    document.getElementById('stTotal').textContent  = d.total ?? '—';
    document.getElementById('stResp').textContent   = d.respondidos ?? '—';
    document.getElementById('stAg').textContent     = d.aguardando ?? '—';
    document.getElementById('stSemana').textContent = d.semana ?? '—';
    // Diagnóstico
    const diag = d.diagnostico || {};
    let txt = '';
    txt += 'Token WhatsApp : ' + (diag.whatsapp_token || '?') + '\n';
    if (typeof diag.canal === 'object' && diag.canal) {
      txt += 'Canal          : ' + (diag.canal.status || '?') + '\n';
      txt += 'Phone ID       : ' + (diag.canal.meta_phone_number_id || '?') + '\n';
    } else {
      txt += 'Canal          : ' + (diag.canal || '?') + '\n';
    }
    txt += 'Threads c/ cliente: ' + (diag.threads_com_cliente ?? '?') + '\n';
    txt += 'Hora BRT       : ' + (diag.hora_brt || '?') + '\n';
    txt += 'É segunda-feira: ' + (diag.e_segunda ? '✅ Sim' : '❌ Não') + '\n';
    document.getElementById('diagText').textContent = txt;
  } catch(e) {
    document.getElementById('stSemana').textContent = 'Erro';
  }
}

function toggleDiag() {
  _diagVisible = !_diagVisible;
  document.getElementById('diagBox').style.display = _diagVisible ? 'block' : 'none';
}

async function disparar() {
  const force = document.getElementById('forceCheck').checked ? '1' : '0';
  mostrarLog('Disparando check-ins…');
  try {
    const r = await fetch('/admin/checkin/disparar-agora?force=' + force, {method:'POST'});
    const d = await r.json();
    const badge = document.getElementById('logBadge');
    badge.textContent = d.ok ? '✅ OK' : '⚠️ Com erros';
    badge.className = 'badge ' + (d.ok ? 'bg-success' : 'bg-warning text-dark');
    let resumo = `Semana: ${d.semana}  |  Enviados: ${d.enviados}  Pulados: ${d.pulados}  Erros: ${d.erros}\n\n`;
    resumo += (d.log || []).join('\n');
    document.getElementById('logBox').textContent = resumo;
    carregarStatus();
  } catch(e) {
    document.getElementById('logBox').textContent = 'Erro de comunicação: ' + e;
  }
}

async function lembretes() {
  mostrarLog('Enviando lembretes…');
  try {
    const r = await fetch('/admin/checkin/disparar-lembretes', {method:'POST'});
    const d = await r.json();
    document.getElementById('logBadge').textContent = '✅ OK';
    document.getElementById('logBadge').className = 'badge bg-success';
    let resumo = `Semana: ${d.semana}  |  Enviados: ${d.enviados}  Pulados: ${d.pulados}  Erros: ${d.erros}\n\n`;
    resumo += (d.log || []).join('\n');
    document.getElementById('logBox').textContent = resumo;
  } catch(e) {
    document.getElementById('logBox').textContent = 'Erro: ' + e;
  }
}

async function enviarTemplate(templateName, langCode) {
  if (!confirm(`Enviar o template "${templateName}" para TODOS os usuários com WhatsApp cadastrado?\n\nO nome de cada usuário será inserido automaticamente.`)) return;
  mostrarLog(`Enviando template "${templateName}"…`);
  try {
    const r = await fetch('/admin/checkin/broadcast-template', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({template_name: templateName, language_code: langCode}),
    });
    const d = await r.json();
    const badge = document.getElementById('logBadge');
    badge.textContent = d.ok ? '✅ OK' : '⚠️ Com erros';
    badge.className = 'badge ' + (d.ok ? 'bg-success' : 'bg-warning text-dark');
    document.getElementById('logBox').textContent = (d.log || []).join('\n');
  } catch(e) {
    document.getElementById('logBox').textContent = 'Erro: ' + e;
  }
}

async function enviarMsgPersonalizada() {
  const msg = document.getElementById('msgPersonalizada').value.trim();
  if (!msg) { alert('Digite uma mensagem antes de enviar.'); return; }
  if (!confirm(`Enviar para TODOS os usuários com WhatsApp cadastrado?\n\nMensagem:\n${msg}`)) return;
  mostrarLog('Enviando mensagem personalizada…');
  try {
    const r = await fetch('/admin/checkin/mensagem-broadcast', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({mensagem: msg}),
    });
    const d = await r.json();
    const badge = document.getElementById('logBadge');
    badge.textContent = d.ok ? '✅ OK' : '⚠️ Com erros';
    badge.className = 'badge ' + (d.ok ? 'bg-success' : 'bg-warning text-dark');
    document.getElementById('logBox').textContent = (d.log || []).join('\n');
  } catch(e) {
    document.getElementById('logBox').textContent = 'Erro: ' + e;
  }
}

function mostrarLog(msg) {
  document.getElementById('logCard').style.display = 'block';
  document.getElementById('logBox').textContent = msg;
  document.getElementById('logBadge').textContent = '…';
  document.getElementById('logBadge').className = 'badge bg-secondary';
}

carregarStatus();
</script>
{% endblock %}
"""

if hasattr(templates_env.loader, "mapping"):
    templates_env.loader.mapping = TEMPLATES


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


@app.post("/admin/checkin/mensagem-broadcast")
@require_login
async def checkin_mensagem_broadcast(request: Request, session: Session = Depends(get_session)):
    """Envia mensagem livre para todos os usuários com whatsapp_phone cadastrado na empresa."""
    ctx = get_tenant_context(request, session)
    if not ctx or ctx.membership.role not in ("admin", "owner", "equipe"):
        return JSONResponse({"ok": False, "erro": "Sem permissão."}, status_code=403)

    body = await request.json()
    mensagem = (body.get("mensagem") or "").strip()
    if not mensagem:
        return JSONResponse({"ok": False, "erro": "Mensagem vazia."}, status_code=400)

    canal = session.exec(
        _sel_ck(WhatsAppChannelConfig)
        .where(WhatsAppChannelConfig.company_id == ctx.company.id)
    ).first()
    if not canal or not canal.meta_phone_number_id:
        return JSONResponse({"ok": False, "erro": "Canal WhatsApp não configurado."}, status_code=400)

    # Busca todos os membros com whatsapp_phone definido
    membros = session.exec(
        _sel_ck(Membership)
        .where(Membership.company_id == ctx.company.id)
    ).all()

    log = []
    enviados = erros = 0
    for m in membros:
        try:
            user = session.get(User, m.user_id)
            if not user or not user.whatsapp_phone:
                continue
            ok, detalhe = _ck_enviar_sync(user.whatsapp_phone, canal.meta_phone_number_id, mensagem)
            # detalhe = número normalizado (ok=True) ou mensagem de erro (ok=False)
            nome_display = f"{user.name or user.email} ({user.whatsapp_phone})"
            if ok:
                enviados += 1
                num_enviado = detalhe or user.whatsapp_phone
                log.append(f"✅ {nome_display} → +{num_enviado}")
            else:
                erros += 1
                log.append(f"❌ {nome_display}: {detalhe}")
        except Exception as _e:
            erros += 1
            log.append(f"❌ user#{m.user_id}: {_e}")

    log.append(f"\nTotal: {enviados} enviados, {erros} erros.")
    return JSONResponse({"ok": erros == 0, "enviados": enviados, "erros": erros, "log": log})


@app.post("/admin/checkin/broadcast-template")
@require_login
async def checkin_broadcast_template(request: Request, session: Session = Depends(get_session)):
    """Envia template WhatsApp aprovado para todos os usuários com whatsapp_phone."""
    ctx = get_tenant_context(request, session)
    if not ctx or ctx.membership.role not in ("admin", "owner", "equipe"):
        return JSONResponse({"ok": False, "erro": "Sem permissão."}, status_code=403)

    body          = await request.json()
    template_name = (body.get("template_name") or "").strip()
    language_code = (body.get("language_code") or "pt_BR").strip()
    body_params   = body.get("body_params") or []  # lista de strings para {{1}}, {{2}}...

    if not template_name:
        return JSONResponse({"ok": False, "erro": "template_name obrigatório."}, status_code=400)

    canal = session.exec(
        _sel_ck(WhatsAppChannelConfig)
        .where(WhatsAppChannelConfig.company_id == ctx.company.id)
    ).first()
    if not canal or not canal.meta_phone_number_id:
        return JSONResponse({"ok": False, "erro": "Canal WhatsApp não configurado."}, status_code=400)

    membros = session.exec(
        _sel_ck(Membership).where(Membership.company_id == ctx.company.id)
    ).all()

    log = []
    enviados = erros = 0
    for m in membros:
        try:
            user = session.get(User, m.user_id)
            if not user or not user.whatsapp_phone:
                continue
            # Substitui {{1}} pelo primeiro nome do usuário se body_params não vier preenchido
            params = body_params if body_params else [(user.name or user.email or "").split()[0] or "cliente"]
            ok, detalhe = _ck_enviar_template_sync(
                user.whatsapp_phone, canal.meta_phone_number_id,
                template_name, language_code, params,
            )
            nome_display = f"{user.name or user.email} ({user.whatsapp_phone})"
            if ok:
                enviados += 1
                log.append(f"✅ {nome_display} → +{detalhe}")
            else:
                erros += 1
                log.append(f"❌ {nome_display}: {detalhe}")
        except Exception as _e:
            erros += 1
            log.append(f"❌ user#{m.user_id}: {_e}")

    log.append(f"\nTotal: {enviados} enviados, {erros} erros.")
    return JSONResponse({"ok": erros == 0, "enviados": enviados, "erros": erros, "log": log})


print("[checkin] ✅ Módulo de check-in semanal carregado (v2 — httpx síncrono).")

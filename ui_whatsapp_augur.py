# ui_whatsapp_augur.py — Integração Augur ↔ WhatsApp
# Responde automaticamente clientes cadastrados via WhatsApp
# Exec'd no namespace do app.py, então tem acesso a engine, Client,
# ClientSnapshot, WhatsAppThread, WhatsAppThreadMessage, etc.

import asyncio
import json as _json_waz
from sqlmodel import Session as _WazSession, select as _waz_select


def _waz_build_client_data(session, company_id: int, client) -> dict:
    """Monta client_data para o Augur a partir do banco — mesma lógica do augur_ask_v4."""
    client_data = {
        "name":                client.name,
        "segment":             getattr(client, "segment", None),
        "revenue_monthly_brl": float(client.revenue_monthly_brl or 0),
        "cash_balance_brl":    float(client.cash_balance_brl or 0),
        "debt_total_brl":      float(client.debt_total_brl or 0),
    }
    try:
        snap = session.exec(
            _waz_select(ClientSnapshot)
            .where(
                ClientSnapshot.company_id == company_id,
                ClientSnapshot.client_id == client.id,
            )
            .order_by(ClientSnapshot.created_at.desc())
            .limit(1)
        ).first()
        if snap:
            client_data.update({
                "score_total":     float(snap.score_total or 0),
                "score_financial": float(snap.score_financial or 0),
                "score_process":   float(snap.score_process or 0),
            })
            try:
                answers = _json_waz.loads(snap.answers_json or "{}")
                for k in [
                    "receivables_brl","inventory_brl","payables_360_brl",
                    "short_term_debt_brl","long_term_debt_brl","collateral_brl",
                    "delinquency_brl","cmv","payroll","opex","mb","mb_pct",
                    "ebitda","liq_corrente","ccl","pe_mensal","margem_seg",
                ]:
                    if k in answers:
                        client_data[k] = answers[k]
            except Exception:
                pass
    except Exception:
        pass

    try:
        client_data = _enriquecer_client_data(session, company_id, client.id, client, client_data)
    except Exception:
        pass

    return client_data


def _waz_thread_history(session, thread_id: int, limit: int = 10) -> list:
    """Últimas mensagens da thread como histórico de conversa para o Augur."""
    msgs = session.exec(
        _waz_select(WhatsAppThreadMessage)
        .where(
            WhatsAppThreadMessage.thread_id == thread_id,
            WhatsAppThreadMessage.direction.in_(["inbound", "outbound"]),
            WhatsAppThreadMessage.body != "",
        )
        .order_by(WhatsAppThreadMessage.created_at.desc())
        .limit(limit)
    ).all()

    history = []
    for m in reversed(msgs):
        role = "user" if m.direction == "inbound" else "assistant"
        history.append({"role": role, "content": m.body})
    return history


async def _augur_whatsapp_reply(
    *,
    company_id: int,
    thread_id: int,
    client_id: int,
    message_body: str,
    config,
) -> None:
    """Gera resposta do Augur para mensagem recebida via WhatsApp e envia de volta."""
    try:
        # Abre sessão própria (a do request já fechou)
        with _WazSession(engine) as db:
            client = db.get(Client, client_id)
            if not client:
                return

            thread = db.get(WhatsAppThread, thread_id)
            if not thread:
                return

            contact_phone = thread.contact_phone
            client_data   = _waz_build_client_data(db, company_id, client)
            history       = _waz_thread_history(db, thread_id, limit=10)

        # Remove a última mensagem do histórico se for a pergunta atual
        # (já foi salva antes desta função ser chamada)
        if history and history[-1]["role"] == "user" and history[-1]["content"] == message_body:
            history = history[:-1]

        # Chama o Augur em thread separada (é síncrono/bloqueante)
        from ai_assistant.assistant import ask as _augur_ask
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            lambda: _augur_ask(
                question=message_body,
                client_data=client_data,
                conversation_history=history,
            ),
        )

        reply = (result.get("response") or "").strip()
        if not reply or result.get("error"):
            return

        # Limita ao máximo do WhatsApp (4096 chars)
        if len(reply) > 4000:
            reply = reply[:3990] + "…"

        # Envia pelo WhatsApp
        ok, _err, ext_id = await _try_send_whatsapp_text(
            config=config,
            recipient_id=contact_phone,
            recipient_kind="individual",
            body=reply,
        )
        if not ok:
            return

        # Salva como mensagem de saída na thread
        with _WazSession(engine) as db:
            thread = db.get(WhatsAppThread, thread_id)
            if thread:
                _whatsapp_add_message(
                    db,
                    thread=thread,
                    direction="outbound",
                    body=reply,
                    sender_name="Augur",
                    created_by_user_id=None,
                    delivery_status="sent",
                    external_message_id=ext_id or "",
                )

    except Exception as _e:
        print(f"[augur_whatsapp] Erro ao gerar resposta: {_e}")

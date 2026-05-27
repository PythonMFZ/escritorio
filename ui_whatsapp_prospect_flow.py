# =============================================================================
# WhatsApp Prospect Onboarding Flow
# =============================================================================
# Máquina de estados para números desconhecidos que mandam mensagem no WA.
#
# Estados:
#   ask_nome   → pergunta nome + empresa (juntos)
#   ask_cnpj   → pergunta CNPJ
#   diag       → 5 turnos de diagnóstico via Augur (Claude)
#   paywall    → enviou score + link Stripe/cadastro
#   done       → conversa encerrada, aguarda assinatura
# =============================================================================

import re    as _re_pf
import json  as _json_pf
import os    as _os_pf
from datetime import datetime as _dt_pf, timedelta as _td_pf
from typing   import Optional as _Opt_pf
from sqlmodel import Field as _F_pf, SQLModel as _SM_pf, select as _sel_pf, Session as _Sess_pf

_DIAG_LIMIT    = 5   # perguntas do diagnóstico
_ADMIN_EMAIL_P = "maffezzolli.eng@gmail.com"


# ── Modelo de sessão do prospect ──────────────────────────────────────────────

class WhatsAppProspectSession(_SM_pf, table=True):
    __tablename__  = "whatsappprospectsession"
    __table_args__ = {"extend_existing": True}

    id:           _Opt_pf[int] = _F_pf(default=None, primary_key=True)
    phone:        str          = _F_pf(default="", index=True, unique=True)
    state:        str          = _F_pf(default="ask_nome")  # ask_nome|ask_cnpj|diag|paywall|done
    nome:         str          = _F_pf(default="")
    empresa:      str          = _F_pf(default="")
    cnpj:         str          = _F_pf(default="")
    trial_token:  str          = _F_pf(default="")
    msgs_used:    int          = _F_pf(default=0)
    history_json: str          = _F_pf(default="[]")
    created_at:   str          = _F_pf(default="")
    updated_at:   str          = _F_pf(default="")


try:
    _SM_pf.metadata.create_all(engine, tables=[WhatsAppProspectSession.__table__])
    print("[prospect_flow] ✅ Tabela whatsappprospectsession OK")
except Exception as _ep:
    print(f"[prospect_flow] Tabela: {_ep}")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _agora_pf() -> str:
    return _dt_pf.now().strftime("%Y-%m-%d %H:%M:%S")

def _limpar_cnpj_pf(v: str) -> str:
    return _re_pf.sub(r"\D", "", v or "")

def _cnpj_valido(v: str) -> bool:
    return len(_limpar_cnpj_pf(v)) == 14

def _parse_nome_empresa(texto: str) -> tuple[str, str]:
    """Tenta separar 'nome / empresa' ou 'nome, empresa'. Retorna (nome, empresa)."""
    for sep in [" / ", " - ", " | ", ", "]:
        if sep in texto:
            parts = texto.split(sep, 1)
            return parts[0].strip(), parts[1].strip()
    # Se não tem separador, usa tudo como empresa e nome vazio
    return "", texto.strip()

def _criar_trial_lead_pf(session, sess: WhatsAppProspectSession) -> str:
    """Cria TrialLead e retorna o access_token."""
    import uuid as _uu
    token = str(_uu.uuid4())
    lead = TrialLead(
        nome           = sess.nome,
        email          = "",
        empresa        = sess.empresa,
        cnpj           = _limpar_cnpj_pf(sess.cnpj),
        whatsapp       = sess.phone,
        access_token   = token,
        messages_used  = 0,
        messages_limit = _DIAG_LIMIT,
        created_at     = _agora_pf(),
        expires_at     = (_dt_pf.now() + _td_pf(days=30)).strftime("%Y-%m-%d %H:%M:%S"),
    )
    session.add(lead)
    session.flush()

    # CRM automático
    try:
        admin = session.exec(_sel_pf(User).where(User.email == _ADMIN_EMAIL_P)).first()
        if admin:
            m = session.exec(
                _sel_pf(Membership).where(
                    Membership.user_id == admin.id,
                    Membership.role.in_(["admin", "owner"]),
                )
            ).first()
            if m:
                ph = session.exec(
                    _sel_pf(Client).where(
                        Client.company_id == m.company_id,
                        Client.name == "Leads Augur PME",
                    )
                ).first()
                if not ph:
                    ph = Client(company_id=m.company_id, name="Leads Augur PME", cnpj="00000000000000")
                    session.add(ph)
                    session.flush()
                deal = BusinessDeal(
                    company_id         = m.company_id,
                    client_id          = ph.id,
                    created_by_user_id = admin.id,
                    owner_user_id      = admin.id,
                    title              = f"[Trial WA] {sess.empresa}",
                    demand             = f"Nome: {sess.nome}\nEmpresa: {sess.empresa}\nCNPJ: {sess.cnpj}\nWhatsApp: {sess.phone}",
                    stage              = "qualificacao",
                    source             = "whatsapp_trial",
                    notes              = f"Trial via WhatsApp iniciado em {_agora_pf()}",
                )
                session.add(deal)
                lead.crm_deal_id = deal.id if hasattr(lead, "crm_deal_id") else None
    except Exception as _ec:
        print(f"[prospect_flow] CRM: {_ec}")

    session.commit()
    return token


def _gerar_checkout_url_pf(token: str, phone: str) -> str:
    """Gera URL do Stripe checkout ou WhatsApp fallback."""
    stripe_key = _os_pf.environ.get("STRIPE_SECRET_KEY", "")
    if stripe_key:
        try:
            import stripe as _st  # type: ignore
            _st.api_key = stripe_key
            base = "https://app.maffezzollicapital.com.br"
            ch = _st.checkout.Session.create(
                mode="subscription",
                success_url=base + f"/trial/assinado?token={token}",
                cancel_url=base + f"/trial?token={token}",
                line_items=[{"price": "price_1TSj9eDqHWO7wr", "quantity": 1}],
                metadata={"trial_token": token, "source": "whatsapp"},
            )
            return ch.url
        except Exception as _se:
            print(f"[prospect_flow] Stripe: {_se}")
    return "https://wa.me/5547991359091?text=Quero+assinar+o+Augur+PME"


def _augur_resposta(question: str, nome: str, empresa: str, history: list) -> str:
    """Chama o Augur para responder no contexto do diagnóstico."""
    _SYSTEM = """Você é o Augur, assistente financeiro inteligente da Maffezzolli Capital.

Está fazendo um diagnóstico financeiro rápido via WhatsApp para uma PME.
Faça UMA pergunta objetiva por vez para entender:
- Faturamento mensal
- Principais dívidas / endividamento
- Fluxo de caixa (sobra ou falta?)
- Margem de lucro aproximada
- Maior desafio financeiro hoje

Após 5 trocas de mensagem, apresente um Score de Saúde Financeira (0-100) com:
- Nota e justificativa em 2 linhas
- Top 3 ações prioritárias numeradas

Estilo: direto, empático, linguagem de WhatsApp (sem markdown complexo, use *negrito* só ocasionalmente)."""

    try:
        from ai_assistant.assistant import ask as _ask
        result = _ask(
            question=question,
            client_data={"nome": nome, "empresa": empresa, "segment": "pme", "_trial_system_override": _SYSTEM},
            conversation_history=history[-16:] if history else None,
        )
        return result.get("response") or "Desculpe, tive um problema. Pode repetir?"
    except Exception as _e:
        print(f"[prospect_flow] Augur erro: {_e}")
        return "Desculpe, tive um problema técnico. Tente novamente em instantes."


# ── Função principal: processa mensagem do prospect ───────────────────────────

def processar_mensagem_prospect(
    phone: str,
    body: str,
    thread_id: int,
    company_id: int,
    config_phone_number_id: str,
) -> _Opt_pf[str]:
    """
    Processa a mensagem de um número desconhecido e retorna a resposta a enviar.
    Retorna None se não houver resposta para enviar.
    """
    with _Sess_pf(engine) as session:
        sess = session.exec(
            _sel_pf(WhatsAppProspectSession).where(WhatsAppProspectSession.phone == phone)
        ).first()

        if not sess:
            sess = WhatsAppProspectSession(
                phone      = phone,
                state      = "ask_nome",
                created_at = _agora_pf(),
                updated_at = _agora_pf(),
            )
            session.add(sess)
            session.commit()
            session.refresh(sess)
            return (
                "Olá! 👋 Sou o *Augur*, consultor financeiro da Maffezzolli Capital.\n\n"
                "Vou fazer um diagnóstico rápido da sua empresa — leva cerca de 5 minutos e você sai sabendo exatamente onde estão os pontos críticos do seu negócio. 📊\n\n"
                "Para começar: qual é o seu *nome* e o nome da sua *empresa*?\n"
                "_(Ex: João Silva / Construtora ABC)_"
            )

        sess.updated_at = _agora_pf()

        # ── Estado: ask_nome ─────────────────────────────────────────────────
        if sess.state == "ask_nome":
            nome, empresa = _parse_nome_empresa(body)
            if not empresa:
                empresa = body.strip()
            if not nome:
                nome = body.split()[0].strip() if body.strip() else "Empresário"

            sess.nome    = nome[:100]
            sess.empresa = empresa[:200]
            sess.state   = "ask_cnpj"
            session.add(sess)
            session.commit()
            return (
                f"Prazer, *{sess.nome}*! 😊\n\n"
                f"Para identificar a *{sess.empresa}* no diagnóstico, qual é o *CNPJ* da empresa?\n"
                "_(Pode digitar só os números)_"
            )

        # ── Estado: ask_cnpj ─────────────────────────────────────────────────
        if sess.state == "ask_cnpj":
            cnpj_limpo = _limpar_cnpj_pf(body)
            if not _cnpj_valido(body):
                return (
                    "Hmm, esse CNPJ parece incompleto. 🤔\n"
                    "Por favor, informe os 14 dígitos do CNPJ:\n"
                    "_(Ex: 12.345.678/0001-90 ou 12345678000190)_"
                )

            # Verifica CNPJ duplicado
            existente = session.exec(
                _sel_pf(TrialLead).where(TrialLead.cnpj == cnpj_limpo)
            ).first()
            if existente and existente.whatsapp != phone:
                sess.state = "done"
                session.add(sess)
                session.commit()
                return (
                    "Este CNPJ já realizou um diagnóstico anteriormente. 📋\n\n"
                    "Para acessar a plataforma completa:\n"
                    "👉 https://wa.me/5547991359091?text=Quero+assinar+o+Augur+PME"
                )

            sess.cnpj  = cnpj_limpo
            sess.state = "diag"
            session.add(sess)
            session.flush()

            # Cria TrialLead e CRM deal
            token = _criar_trial_lead_pf(session, sess)
            sess.trial_token = token
            sess.msgs_used   = 0
            sess.history_json = "[]"
            session.add(sess)
            session.commit()

            # Primeira pergunta do Augur
            history = []
            resposta = _augur_resposta(
                "Olá, pode começar o diagnóstico. Faça a primeira pergunta.",
                sess.nome, sess.empresa, history,
            )
            history.append({"role": "assistant", "content": resposta})
            sess.history_json = _json_pf.dumps(history, ensure_ascii=False)
            sess.msgs_used    = 1
            session.add(sess)
            session.commit()
            return (
                f"Perfeito! ✅ Diagnóstico iniciado para *{sess.empresa}*.\n\n"
                + resposta
            )

        # ── Estado: diag ─────────────────────────────────────────────────────
        if sess.state == "diag":
            try:
                history = _json_pf.loads(sess.history_json or "[]")
            except Exception:
                history = []

            history.append({"role": "user", "content": body})
            resposta = _augur_resposta(body, sess.nome, sess.empresa, history)
            history.append({"role": "assistant", "content": resposta})

            sess.msgs_used    += 1
            sess.history_json  = _json_pf.dumps(history[-20:], ensure_ascii=False)

            # Após _DIAG_LIMIT turnos → paywall
            if sess.msgs_used >= _DIAG_LIMIT:
                sess.state = "paywall"
                session.add(sess)
                session.commit()

                checkout_url = _gerar_checkout_url_pf(sess.trial_token, phone)
                return (
                    resposta + "\n\n"
                    "─────────────────────\n"
                    "🔓 *Quer continuar com o Augur completo?*\n\n"
                    "Com a assinatura você tem:\n"
                    "✅ Diagnósticos ilimitados\n"
                    "✅ Histórico e alertas automáticos\n"
                    "✅ Acesso à plataforma completa\n\n"
                    f"📲 *Assine agora por R$299/mês:*\n{checkout_url}\n\n"
                    "Ou fale com um consultor: https://wa.me/5547991359091"
                )
            else:
                session.add(sess)
                session.commit()
                return resposta

        # ── Estado: paywall / done ────────────────────────────────────────────
        if sess.state in ("paywall", "done"):
            checkout_url = _gerar_checkout_url_pf(sess.trial_token, phone) if sess.trial_token else "https://wa.me/5547991359091"
            return (
                "Seu diagnóstico gratuito foi concluído. 😊\n\n"
                f"Para assinar e acessar a plataforma:\n{checkout_url}\n\n"
                "Dúvidas? Fale com a equipe: https://wa.me/5547991359091"
            )

    return None


print("[prospect_flow] ✅ WhatsApp Prospect Flow carregado")

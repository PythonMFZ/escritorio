# ui_augur_financeiro.py — Lançamento financeiro via WhatsApp / Augur
# Exec'd in app.py namespace — has access to all models, engine, helpers.

import json as _json_fin
import os   as _os_fin
from datetime import datetime as _dt_fin, timezone as _tz_fin
import httpx as _httpx_fin
from sqlmodel import Session as _SessFin, select as _sel_fin

_ANTHROPIC_KEY_FIN = _os_fin.getenv("ANTHROPIC_API_KEY", "")
_HAIKU_FIN = "claude-haiku-4-5-20251001"

# Palavras-gatilho que indicam intenção financeira (sem chamar LLM)
_FIN_TRIGGERS = [
    "lançar", "lancar", "lançamento", "lancamento",
    "registrar", "registrei", "registrou",
    "paguei", "pagar", "pagamento", "pago",
    "recebi", "receber", "recebimento", "recebeu",
    "despesa", "receita", "gasto", "gaste",
    "conta a pagar", "conta a receber",
]


def _fin_is_financial_message(message: str) -> bool:
    """Verifica rapidamente (sem LLM) se a mensagem parece uma intenção financeira."""
    low = message.lower().strip()
    return any(t in low for t in _FIN_TRIGGERS)


def _fin_extract_entry(message: str, categories: list[dict]) -> dict | None:
    """
    Chama Claude Haiku para extrair os campos do lançamento.
    Retorna dict ou None se não for intenção financeira.
    """
    if not _ANTHROPIC_KEY_FIN:
        return None

    today = _dt_fin.now(_tz_fin.utc).strftime("%d/%m/%Y")
    cats_str = (
        "\n".join(f'  - id={c["id"]} | "{c["name"]}" ({c["kind"]})' for c in categories)
        if categories else "  (nenhuma categoria cadastrada)"
    )

    prompt = (
        f"Hoje é {today}.\n\n"
        f"Categorias disponíveis:\n{cats_str}\n\n"
        f'Mensagem do usuário: "{message}"\n\n'
        "Se a mensagem é um lançamento financeiro (despesa ou receita), responda com JSON:\n"
        '{"eh_lancamento":true,'
        '"entry_kind":"pagar ou receber",'
        '"description":"descrição limpa do lançamento",'
        '"amount":123.45,'
        '"due_date":"DD/MM/AAAA — use hoje se não informado",'
        '"status":"pago se já foi efetuado, senão aberto",'
        '"category_id":null_ou_id_da_categoria,'
        '"category_name":"nome sugerido se não achou nas categorias"}\n\n'
        'Se NÃO é lançamento financeiro, responda apenas: {"eh_lancamento":false}\n\n'
        "Regras:\n"
        "- entry_kind='pagar' para despesas/gastos/pagamentos\n"
        "- entry_kind='receber' para receitas/recebimentos\n"
        "- status='pago' se a mensagem usa passado ('paguei','recebi','pago')\n"
        "- status='aberto' se é a pagar/receber ainda\n"
        "- category_id: escolha a categoria mais adequada da lista acima, ou null\n"
        "Responda SOMENTE com o JSON, sem texto adicional."
    )

    try:
        r = _httpx_fin.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": _ANTHROPIC_KEY_FIN,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": _HAIKU_FIN,
                "max_tokens": 400,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=15,
        )
        raw = r.json()["content"][0]["text"].strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1].lstrip("json").strip()
        return _json_fin.loads(raw)
    except Exception as _e:
        print(f"[augur_fin] erro extração LLM: {_e}")
        return None


def _fin_parse_date(date_str: str) -> str:
    """Converte DD/MM/AAAA para YYYY-MM-DD. Retorna hoje se falhar."""
    today_iso = _dt_fin.now(_tz_fin.utc).strftime("%Y-%m-%d")
    if not date_str:
        return today_iso
    for fmt in ("%d/%m/%Y", "%Y-%m-%d"):
        try:
            return _dt_fin.strptime(date_str.strip(), fmt).strftime("%Y-%m-%d")
        except Exception:
            pass
    return today_iso


def augur_financeiro_handle(session, company_id: int, client_id: int, message: str) -> str | None:
    """
    Tenta interpretar `message` como um lançamento financeiro do CLIENTE
    (usa ClientFinancialEntry — o Financeiro Gerencial da ferramenta /ferramentas/financeiro).

    Retorna mensagem de confirmação ou None se não for intenção financeira.
    """
    if not _fin_is_financial_message(message):
        return None

    # ── Sempre usa ClientFinancialEntry quando há client_id ──────────────────
    # (Financeiro Gerencial em /ferramentas/financeiro — visível pelo cliente)
    # Só cai em OfficeFinancialEntry se não houver client_id na thread
    use_client_model = bool(client_id)

    # ── Resolve sys_user_id (created_by_user_id obrigatório) ─────────────────
    memberships = session.exec(
        _sel_fin(Membership).where(
            Membership.company_id == company_id,
            Membership.role.in_(["owner", "admin"]),
        ).limit(1)
    ).all()
    sys_user_id = memberships[0].user_id if memberships else 1

    # ── Garante tabelas e carrega categorias ──────────────────────────────────
    if use_client_model:
        try:
            ensure_client_finance_tables()
            seed_client_finance_defaults(session, company_id=company_id, client_id=client_id)
        except Exception:
            pass
        cats_raw = session.exec(
            _sel_fin(ClientFinanceCategory).where(
                ClientFinanceCategory.company_id == company_id,
                ClientFinanceCategory.client_id == client_id,
                ClientFinanceCategory.is_active == True,
            ).order_by(ClientFinanceCategory.name)
        ).all()
    else:
        cats_raw = session.exec(
            _sel_fin(OfficeCategory).where(
                OfficeCategory.company_id == company_id,
                OfficeCategory.is_active == True,
            ).order_by(OfficeCategory.name)
        ).all()

    categories = [{"id": c.id, "name": c.name, "kind": c.category_kind} for c in cats_raw]

    extracted = _fin_extract_entry(message, categories)
    if not extracted or not extracted.get("eh_lancamento"):
        return None

    # ── Campos comuns ─────────────────────────────────────────────────────────
    entry_kind  = extracted.get("entry_kind", "pagar")
    description = (extracted.get("description") or message.strip())[:500]
    amount      = float(extracted.get("amount") or 0.0)
    status      = extracted.get("status") or "aberto"
    due_date    = _fin_parse_date(extracted.get("due_date") or "")
    category_id = extracted.get("category_id")

    valid_cat_ids = {c["id"] for c in categories}
    if category_id and int(category_id) not in valid_cat_ids:
        category_id = None

    today_iso       = _dt_fin.now(_tz_fin.utc).strftime("%Y-%m-%d")
    settlement_date = due_date if status == "pago" else ""
    amount_realized = amount if status == "pago" else 0.0
    note_text       = f"Lançado via WhatsApp: {message[:200]}"

    # ── Cria o lançamento ─────────────────────────────────────────────────────
    if use_client_model:
        entry = ClientFinancialEntry(
            company_id=company_id,
            client_id=client_id,
            created_by_user_id=sys_user_id,
            entry_kind=entry_kind,
            status=status,
            description=description,
            amount_expected_brl=amount,
            amount_realized_brl=amount_realized,
            category_id=int(category_id) if category_id else None,
            due_date=due_date,
            competence_date=today_iso,
            settlement_date=settlement_date,
            notes=note_text,
            created_at=_dt_fin.now(_tz_fin.utc),
            updated_at=_dt_fin.now(_tz_fin.utc),
        )
        destino_log = f"ClientFinancialEntry client={client_id}"
        destino_msg = "Acesse Ferramentas → Financeiro para ver e editar."
    else:
        entry = OfficeFinancialEntry(
            company_id=company_id,
            created_by_user_id=sys_user_id,
            entry_kind=entry_kind,
            status=status,
            description=description,
            amount_expected_brl=amount,
            amount_realized_brl=amount_realized,
            category_id=int(category_id) if category_id else None,
            due_date=due_date,
            competence_date=today_iso,
            settlement_date=settlement_date,
            notes=note_text,
            created_at=_dt_fin.now(_tz_fin.utc),
            updated_at=_dt_fin.now(_tz_fin.utc),
        )
        destino_log = "OfficeFinancialEntry (admin)"
        destino_msg = "Acesse Admin → Financeiro para ver e editar."

    session.add(entry)
    session.commit()
    session.refresh(entry)

    print(f"[augur_fin] lançamento criado id={entry.id} kind={entry_kind} valor={amount} destino={destino_log} empresa={company_id}")

    # ── Monta resposta ────────────────────────────────────────────────────────
    tipo_emoji = "💸" if entry_kind == "pagar" else "💰"
    tipo_label = "Despesa" if entry_kind == "pagar" else "Receita"
    status_label = "Pago" if status == "pago" else "Em aberto"

    cat_name = ""
    if category_id:
        cat = next((c for c in categories if c["id"] == int(category_id)), None)
        if cat:
            cat_name = f"\n📂 Categoria: {cat['name']}"
    elif extracted.get("category_name"):
        cat_name = f"\n📂 Categoria sugerida: {extracted['category_name']} _(ainda não cadastrada)_"

    valor_fmt = f"R$ {amount:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    try:
        venc_fmt = _dt_fin.strptime(due_date, "%Y-%m-%d").strftime("%d/%m/%Y")
    except Exception:
        venc_fmt = "-"

    return (
        f"{tipo_emoji} *{tipo_label} lançada com sucesso!*\n\n"
        f"📝 {description}\n"
        f"💵 Valor: {valor_fmt}\n"
        f"📅 Vencimento: {venc_fmt}\n"
        f"✅ Status: {status_label}"
        f"{cat_name}\n\n"
        f"_{destino_msg}_"
    )


print("[augur_fin] ✅ Módulo financeiro WhatsApp carregado.")

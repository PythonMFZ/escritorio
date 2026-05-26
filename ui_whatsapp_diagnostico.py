# ui_whatsapp_diagnostico.py
# WhatsApp diagnostic flow: guided Q&A + document extraction → ClientBusinessProfile
# Exec'd in app.py namespace.
# ─────────────────────────────────────────────────────────────────────────────

import json as _json_wd
import os as _os_wd
import re as _re_wd
from datetime import datetime as _dt_wd
from typing import Optional as _Opt_wd
from sqlmodel import Field as _F_wd, SQLModel as _SM_wd, select as _sel_wd

import httpx as _httpx_wd

# ── Model: diagnostic session state ──────────────────────────────────────────

class WaDiagSession(_SM_wd, table=True):
    """Tracks an in-progress WhatsApp diagnostic Q&A session."""
    __tablename__  = "wa_diag_session"
    __table_args__ = {"extend_existing": True}

    id:          _Opt_wd[int] = _F_wd(default=None, primary_key=True)
    company_id:  int          = _F_wd(index=True)
    client_id:   int          = _F_wd(index=True)
    phone:       str          = _F_wd(index=True, default="")  # sender phone

    question_idx:    int = _F_wd(default=0)
    answers_json:    str = _F_wd(default="{}")  # {field: value}
    is_complete:     bool = _F_wd(default=False)
    created_at:  str = _F_wd(default="")
    updated_at:  str = _F_wd(default="")


def _ensure_wad_tables():
    try:
        WaDiagSession.__table__.create(engine, checkfirst=True)
    except Exception:
        pass


# ── Question sequence ─────────────────────────────────────────────────────────
# Each entry: (field_key, question_text, group_label)
# field_key maps to ClientBusinessProfile field or a temp key for receivables aging

_WA_DIAG_QUESTIONS = [
    # ── Faturamento
    ("monthly_revenue",
     "💰 *Faturamento*\n\nQual o faturamento mensal médio nos últimos 12 meses?\nResponda em R$ (ex: 150000 ou 150.000).",
     "Faturamento"),

    # ── Caixa
    ("cash_and_investments_brl",
     "🏦 *Caixa e Aplicações*\n\nQual o saldo atual em caixa, conta corrente e aplicações financeiras?\nResponda em R$.",
     "Caixa"),

    # ── Recebíveis aging
    ("recv_30",
     "📋 *Recebíveis — Vencimento em 30 dias*\n\nQual o valor total de recebíveis com vencimento em até 30 dias?\nResponda em R$ (ou 0 se não houver).",
     "Recebíveis"),
    ("recv_60",
     "📋 *Recebíveis — 31 a 60 dias*\n\nQual o valor de recebíveis com vencimento entre 31 e 60 dias?\nResponda em R$ (ou 0).",
     "Recebíveis"),
    ("recv_90",
     "📋 *Recebíveis — 61 a 90 dias*\n\nQual o valor de recebíveis com vencimento entre 61 e 90 dias?\nResponda em R$ (ou 0).",
     "Recebíveis"),
    ("recv_1ano",
     "📋 *Recebíveis — 91 dias a 1 ano*\n\nQual o valor de recebíveis com vencimento entre 91 dias e 1 ano?\nResponda em R$ (ou 0).",
     "Recebíveis"),
    ("recv_lp",
     "📋 *Recebíveis — Acima de 1 ano*\n\nQual o valor de recebíveis com vencimento acima de 1 ano?\nResponda em R$ (ou 0).",
     "Recebíveis"),

    # ── Estoque / outros ativos
    ("inventory_brl",
     "📦 *Estoque*\n\nQual o valor atual do estoque?\nResponda em R$ (ou 0 se não tiver estoque).",
     "Ativos"),
    ("immobilized_brl",
     "🏗️ *Imobilizado*\n\nQual o valor de imóveis, equipamentos e outros ativos fixos da empresa?\nResponda em R$ (ou 0).",
     "Ativos"),

    # ── Passivo — contas a pagar
    ("payables_360_brl",
     "🧾 *Fornecedores / Contas a Pagar (até 1 ano)*\n\nQual o total de contas a pagar a fornecedores com vencimento em até 1 ano?\nResponda em R$.",
     "Passivo"),
    ("labor_liabilities_brl",
     "👷 *Passivo Trabalhista*\n\nQual o total de obrigações trabalhistas (salários a pagar, FGTS, férias provisionadas)?\nResponda em R$ (ou 0).",
     "Passivo"),
    ("tax_liabilities_brl",
     "🏛️ *Passivo Tributário*\n\nQual o total de impostos e tributos a pagar (parcelamentos incluídos)?\nResponda em R$ (ou 0).",
     "Passivo"),
    ("short_term_debt_brl",
     "💳 *Dívida de Curto Prazo*\n\nQual o total de empréstimos e financiamentos com vencimento em até 1 ano?\nResponda em R$ (ou 0).",
     "Passivo"),
    ("long_term_debt_brl",
     "📅 *Dívida de Longo Prazo*\n\nQual o total de empréstimos e financiamentos com vencimento acima de 1 ano?\nResponda em R$ (ou 0).",
     "Passivo"),

    # ── Patrimônio
    ("equity_brl",
     "📊 *Patrimônio Líquido*\n\nQual o Patrimônio Líquido estimado da empresa (Ativos Totais − Passivos Totais)?\nResponda em R$ (pode ser negativo, ex: -50000).",
     "Patrimônio"),
]

_WA_DIAG_TOTAL = len(_WA_DIAG_QUESTIONS)

_WA_DIAG_TRIGGERS = {
    "diagnóstico", "diagnostico", "avaliação", "avaliacao",
    "nova avaliação", "nova avaliacao", "fazer diagnóstico", "fazer diagnostico",
    "iniciar diagnóstico", "iniciar diagnostico", "diagnóstico financeiro",
    "quero fazer avaliação", "quero fazer avaliacao",
}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _wd_parse_brl(text: str) -> _Opt_wd[float]:
    """Parse a BRL amount from user reply. Returns None if unparseable."""
    t = text.strip().lower()
    t = t.replace("r$", "").replace("reais", "").strip()

    # handle negatives
    neg = t.startswith("-")
    t = t.lstrip("-").strip()

    # multipliers: "mil", "k", "milhão", "mi", "bilhão"
    multiplier = 1.0
    for word, mult in [
        ("bilhão", 1_000_000_000), ("bilhoes", 1_000_000_000), ("bilhao", 1_000_000_000),
        ("milhão", 1_000_000), ("milhoes", 1_000_000), ("milhao", 1_000_000),
        ("mil", 1_000), ("k", 1_000),
        ("mi", 1_000_000),  # after "mil" to avoid "mil" → "mi" match
    ]:
        if word in t:
            multiplier = mult
            t = t.replace(word, "").strip()
            break

    # strip any remaining non-numeric chars except , and .
    t = _re_wd.sub(r"[^\d,\.]", "", t).strip()

    if not t:
        return None

    if "," in t and "." in t:
        # both separators present
        # determine which is decimal: last one wins
        if t.rindex(",") > t.rindex("."):
            # Brazilian: 1.234,56
            t = t.replace(".", "").replace(",", ".")
        else:
            # US: 1,234.56
            t = t.replace(",", "")
    elif "," in t:
        parts = t.split(",")
        if len(parts) == 2 and len(parts[1]) == 3:
            # "27,000" → thousands separator
            t = t.replace(",", "")
        else:
            # "27,50" → decimal comma
            t = t.replace(",", ".")
    elif "." in t:
        parts = t.split(".")
        if len(parts) == 2 and len(parts[1]) == 3:
            # "27.000" → thousands separator, NOT decimal
            t = t.replace(".", "")
        # else "27.5" → keep as decimal point

    try:
        val = float(t) * multiplier
        return -val if neg else val
    except ValueError:
        return None


def _wd_fmt_brl(v: float) -> str:
    if v is None:
        return "R$ —"
    return f"R$ {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _wd_is_trigger(text: str) -> bool:
    t = text.strip().lower()
    return t in _WA_DIAG_TRIGGERS or any(trig in t for trig in _WA_DIAG_TRIGGERS)


def _wd_get_session(db, company_id: int, phone: str) -> _Opt_wd[WaDiagSession]:
    return db.exec(
        _sel_wd(WaDiagSession).where(
            WaDiagSession.company_id == company_id,
            WaDiagSession.phone == phone,
            WaDiagSession.is_complete == False,
        )
    ).first()


def _wd_save_profile(db, company_id: int, client_id: int, answers: dict):
    """Persist answers into ClientBusinessProfile."""
    from sqlmodel import select as _sel2
    profile = db.exec(
        _sel2(ClientBusinessProfile).where(
            ClientBusinessProfile.company_id == company_id,
            ClientBusinessProfile.client_id == client_id,
        )
    ).first()
    if not profile:
        profile = ClientBusinessProfile(
            company_id=company_id,
            client_id=client_id,
            updated_at=_dt_wd.utcnow(),
        )

    # Receivables: sum aging buckets
    recv_keys = ["recv_30", "recv_60", "recv_90", "recv_1ano", "recv_lp"]
    recv_vals = [answers.get(k) for k in recv_keys if answers.get(k) is not None]
    if recv_vals:
        profile.receivables_brl = sum(recv_vals)

    # Monthly revenue → annual
    if answers.get("monthly_revenue") is not None:
        profile.annual_revenue_brl = answers["monthly_revenue"] * 12

    # Direct field mapping
    direct = [
        "cash_and_investments_brl", "inventory_brl", "immobilized_brl",
        "payables_360_brl", "labor_liabilities_brl", "tax_liabilities_brl",
        "short_term_debt_brl", "long_term_debt_brl", "equity_brl",
    ]
    for f in direct:
        if answers.get(f) is not None:
            setattr(profile, f, answers[f])

    # Recompute aggregates
    profile.current_assets_brl = (
        (profile.cash_and_investments_brl or 0)
        + (profile.receivables_brl or 0)
        + (profile.inventory_brl or 0)
        + (profile.other_current_assets_brl or 0)
    )
    profile.non_current_assets_brl = (
        (profile.immobilized_brl or 0)
        + (profile.other_non_current_assets_brl or 0)
    )
    profile.current_liabilities_brl = (
        (profile.payables_360_brl or 0)
        + (profile.labor_liabilities_brl or 0)
        + (profile.tax_liabilities_brl or 0)
        + (profile.short_term_debt_brl or 0)
        + (profile.other_current_liabilities_brl or 0)
    )
    profile.non_current_liabilities_brl = (
        (profile.long_term_debt_brl or 0)
        + (profile.other_non_current_liabilities_brl or 0)
    )
    profile.updated_at = _dt_wd.utcnow()
    db.add(profile)
    db.commit()


def _wd_summary(answers: dict) -> str:
    """Build a summary of what was collected."""
    lines = ["✅ *Diagnóstico concluído! Aqui está o resumo:*\n"]

    monthly = answers.get("monthly_revenue")
    if monthly is not None:
        lines.append(f"💰 Faturamento mensal: {_wd_fmt_brl(monthly)}")

    cash = answers.get("cash_and_investments_brl")
    if cash is not None:
        lines.append(f"🏦 Caixa e aplicações: {_wd_fmt_brl(cash)}")

    recv_keys = ["recv_30", "recv_60", "recv_90", "recv_1ano", "recv_lp"]
    recv_labels = ["30d", "60d", "90d", "até 1 ano", "> 1 ano"]
    recv_lines = []
    recv_total = 0.0
    for k, lbl in zip(recv_keys, recv_labels):
        v = answers.get(k)
        if v is not None and v > 0:
            recv_lines.append(f"  • {lbl}: {_wd_fmt_brl(v)}")
            recv_total += v
    if recv_lines:
        lines.append(f"📋 Recebíveis: {_wd_fmt_brl(recv_total)}")
        lines.extend(recv_lines)

    for fld, lbl, icon in [
        ("inventory_brl", "Estoque", "📦"),
        ("immobilized_brl", "Imobilizado", "🏗️"),
        ("payables_360_brl", "Fornecedores / CP", "🧾"),
        ("labor_liabilities_brl", "Passivo trabalhista", "👷"),
        ("tax_liabilities_brl", "Passivo tributário", "🏛️"),
        ("short_term_debt_brl", "Dívida CP", "💳"),
        ("long_term_debt_brl", "Dívida LP", "📅"),
        ("equity_brl", "Patrimônio Líquido", "📊"),
    ]:
        v = answers.get(fld)
        if v is not None:
            lines.append(f"{icon} {lbl}: {_wd_fmt_brl(v)}")

    lines.append("\nOs dados foram salvos no perfil financeiro do cliente. Seu consultor já pode ver o diagnóstico atualizado. 🎯")
    return "\n".join(lines)


# ── Document download from WhatsApp ──────────────────────────────────────────

def _wd_download_wa_media(media_id: str) -> _Opt_wd[bytes]:
    """Download media file from WhatsApp Business API."""
    token = _os_wd.getenv("WHATSAPP_TOKEN", "")
    if not token:
        return None
    try:
        # Step 1: get URL
        r = _httpx_wd.get(
            f"https://graph.facebook.com/v23.0/{media_id}",
            headers={"Authorization": f"Bearer {token}"},
            timeout=15,
        )
        url = r.json().get("url", "")
        if not url:
            return None
        # Step 2: download
        r2 = _httpx_wd.get(
            url,
            headers={"Authorization": f"Bearer {token}"},
            timeout=60,
            follow_redirects=True,
        )
        return r2.content
    except Exception as _e:
        print(f"[wad] erro ao baixar mídia {media_id}: {_e}")
        return None


# ── AI field extraction from document text ────────────────────────────────────

_WD_EXTRACT_PROMPT = """Você é um especialista em análise de documentos financeiros empresariais.

Analise o texto abaixo e extraia os valores financeiros nos campos indicados.
Retorne APENAS um JSON válido, sem explicações, com os campos que conseguir identificar.
Use null para campos não encontrados. Valores devem ser numéricos em reais (sem R$, sem pontos de milhar).

Campos a extrair:
- monthly_revenue: faturamento/receita mensal média
- cash_and_investments_brl: caixa + bancos + aplicações financeiras
- recv_30: recebíveis vencendo em até 30 dias
- recv_60: recebíveis de 31 a 60 dias
- recv_90: recebíveis de 61 a 90 dias
- recv_1ano: recebíveis de 91 dias a 1 ano
- recv_lp: recebíveis acima de 1 ano
- receivables_total: total de recebíveis (se não tiver aging)
- inventory_brl: estoque
- immobilized_brl: imobilizado / ativo fixo / patrimônio físico
- payables_360_brl: fornecedores / contas a pagar (até 1 ano)
- labor_liabilities_brl: passivo trabalhista / salários / FGTS / férias
- tax_liabilities_brl: impostos a pagar / passivo tributário / parcelamentos fiscais
- short_term_debt_brl: empréstimos e financiamentos de curto prazo (até 1 ano)
- long_term_debt_brl: empréstimos e financiamentos de longo prazo (acima de 1 ano)
- equity_brl: patrimônio líquido / PL

Texto do documento:
{content}

Retorne apenas o JSON."""


def _wd_extract_fields_from_text(content_text: str) -> dict:
    """Use Claude to extract financial fields from document text."""
    key = _os_wd.getenv("ANTHROPIC_API_KEY", "")
    if not key or not content_text:
        return {}
    try:
        prompt = _WD_EXTRACT_PROMPT.format(content=content_text[:8000])
        r = _httpx_wd.post(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
            json={
                "model": "claude-haiku-4-5-20251001",
                "max_tokens": 1024,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=30,
        )
        text = r.json()["content"][0]["text"].strip()
        # Extract JSON from response (strip markdown fences if present)
        m = _re_wd.search(r"\{[\s\S]+\}", text)
        if m:
            return _json_wd.loads(m.group())
        return {}
    except Exception as _e:
        print(f"[wad] extract_fields erro: {_e}")
        return {}


def _wd_fields_to_summary(fields: dict, fname: str) -> str:
    """Build a WhatsApp confirmation message from extracted fields."""
    if not fields or all(v is None for v in fields.values()):
        return (
            f"📄 Recebi o arquivo *{fname}*, mas não consegui identificar dados financeiros estruturados nele. "
            "Você pode me enviar um extrato de contas a receber, contas a pagar, DRE ou balanço patrimonial."
        )

    lines = [f"📊 *Dados extraídos de {fname}:*\n"]
    field_labels = {
        "monthly_revenue":      ("💰", "Faturamento mensal"),
        "cash_and_investments_brl": ("🏦", "Caixa e aplicações"),
        "recv_30":              ("📋", "Recebíveis 30d"),
        "recv_60":              ("📋", "Recebíveis 60d"),
        "recv_90":              ("📋", "Recebíveis 90d"),
        "recv_1ano":            ("📋", "Recebíveis até 1 ano"),
        "recv_lp":              ("📋", "Recebíveis > 1 ano"),
        "receivables_total":    ("📋", "Recebíveis (total)"),
        "inventory_brl":        ("📦", "Estoque"),
        "immobilized_brl":      ("🏗️", "Imobilizado"),
        "payables_360_brl":     ("🧾", "Fornecedores / CP"),
        "labor_liabilities_brl":("👷", "Passivo trabalhista"),
        "tax_liabilities_brl":  ("🏛️", "Passivo tributário"),
        "short_term_debt_brl":  ("💳", "Dívida CP"),
        "long_term_debt_brl":   ("📅", "Dívida LP"),
        "equity_brl":           ("📊", "Patrimônio Líquido"),
    }
    for fld, (icon, lbl) in field_labels.items():
        v = fields.get(fld)
        if v is not None:
            lines.append(f"{icon} {lbl}: {_wd_fmt_brl(float(v))}")

    lines.append("\n✅ Dados salvos no perfil financeiro. Responda *confirmar* para aceitar ou *cancelar* para descartar.")
    return "\n".join(lines)


# ── Main entry points (called from WhatsApp webhook) ─────────────────────────

def _wad_handle_document(db, company_id: int, client_id: int, phone: str,
                          media_id: str, filename: str, mime_type: str) -> str:
    """Download a WhatsApp document, extract financial fields, save to profile."""
    file_bytes = _wd_download_wa_media(media_id)
    if not file_bytes:
        return "❌ Não consegui baixar o arquivo. Tente novamente ou envie o conteúdo como texto."

    fname = filename or "documento"
    fname_lower = fname.lower()

    # Extract text content
    if fname_lower.endswith((".xlsx", ".xls")) or "spreadsheet" in mime_type or "excel" in mime_type:
        content_text = _bc_extract_excel(file_bytes, fname_lower)
    elif fname_lower.endswith(".pdf") or mime_type == "application/pdf":
        content_text = _bc_extract_claude(file_bytes, "application/pdf")
    elif fname_lower.endswith(".csv") or mime_type == "text/csv":
        content_text = file_bytes.decode("utf-8", errors="replace")
    elif fname_lower.endswith((".doc", ".docx")) or "word" in mime_type:
        try:
            import docx as _docx_wd2, io as _io_wd2
            _doc = _docx_wd2.Document(_io_wd2.BytesIO(file_bytes))
            content_text = "\n".join(p.text for p in _doc.paragraphs if p.text.strip())
        except Exception:
            content_text = ""
    else:
        try:
            content_text = file_bytes.decode("utf-8", errors="replace")
        except Exception:
            content_text = ""

    if not content_text:
        return (
            f"📄 Recebi *{fname}* mas não consegui extrair o conteúdo. "
            "Verifique se o arquivo não está protegido por senha ou corrompido."
        )

    # Extract financial fields using Claude
    fields = _wd_extract_fields_from_text(content_text)

    # Handle receivables_total → distribute to recv_30 if no aging breakdown
    if fields.get("receivables_total") and not any(fields.get(k) for k in ["recv_30","recv_60","recv_90","recv_1ano","recv_lp"]):
        fields["recv_30"] = fields.pop("receivables_total")

    # Save to profile
    _wd_save_profile(db, company_id, client_id, fields)

    return _wd_fields_to_summary(fields, fname)


def _wad_handle_message(db, company_id: int, client_id: int, phone: str,
                         message_text: str) -> _Opt_wd[str]:
    """
    Handle a WhatsApp text message for the diagnostic flow.
    Returns a reply string if this message was handled, None otherwise.
    """
    text = (message_text or "").strip()

    # Check for active session first
    session = _wd_get_session(db, company_id, phone)

    if session:
        t_lower = text.lower()

        # Cancel command
        if t_lower in ("cancelar", "sair", "parar", "cancel"):
            session.is_complete = True
            session.updated_at = _dt_wd.utcnow().isoformat()
            db.add(session)
            db.commit()
            return "❌ Diagnóstico cancelado. Os dados parciais foram descartados. Quando quiser reiniciar, é só digitar *diagnóstico*."

        # Skip command
        if t_lower in ("pular", "não sei", "nao sei", "skip", "-"):
            answers = _json_wd.loads(session.answers_json or "{}")
            field_key = _WA_DIAG_QUESTIONS[session.question_idx][0]
            answers[field_key] = None
            session.answers_json = _json_wd.dumps(answers)
            session.question_idx += 1
            session.updated_at = _dt_wd.utcnow().isoformat()
            db.add(session)
            db.commit()

            if session.question_idx >= _WA_DIAG_TOTAL:
                return _wad_complete_session(db, session, answers, company_id, client_id)
            _, q, _ = _WA_DIAG_QUESTIONS[session.question_idx]
            return f"⏭️ Pulado.\n\n{q}\n\n_(Responda com o valor em R$, ou *pular* para esta pergunta)_"

        # Try to parse a number
        val = _wd_parse_brl(text)
        if val is None:
            _, q, _ = _WA_DIAG_QUESTIONS[session.question_idx]
            return (
                f"❓ Não entendi o valor. Por favor responda com um número em R$ (ex: *150000* ou *150.000*).\n\n"
                f"Ou responda *pular* para pular esta pergunta.\n\n"
                f"Pergunta atual: {q}"
            )

        # Store answer and advance
        answers = _json_wd.loads(session.answers_json or "{}")
        field_key = _WA_DIAG_QUESTIONS[session.question_idx][0]
        answers[field_key] = val
        session.answers_json = _json_wd.dumps(answers)
        session.question_idx += 1
        session.updated_at = _dt_wd.utcnow().isoformat()
        db.add(session)
        db.commit()

        if session.question_idx >= _WA_DIAG_TOTAL:
            return _wad_complete_session(db, session, answers, company_id, client_id)

        _, q, _ = _WA_DIAG_QUESTIONS[session.question_idx]
        progress = f"({session.question_idx}/{_WA_DIAG_TOTAL})"
        return f"✓ Anotado: {_wd_fmt_brl(val)}\n\n{progress} {q}\n\n_(Digite o valor ou *pular*)_"

    # No active session — check if this is a trigger
    if _wd_is_trigger(text):
        # Create new session
        new_sess = WaDiagSession(
            company_id=company_id,
            client_id=client_id,
            phone=phone,
            question_idx=0,
            answers_json="{}",
            is_complete=False,
            created_at=_dt_wd.utcnow().isoformat(),
            updated_at=_dt_wd.utcnow().isoformat(),
        )
        db.add(new_sess)
        db.commit()

        _, first_q, _ = _WA_DIAG_QUESTIONS[0]
        return (
            "📊 *Vamos iniciar o diagnóstico financeiro!*\n\n"
            f"Vou fazer {_WA_DIAG_TOTAL} perguntas sobre os números da empresa. "
            "Responda cada uma com o valor em R$.\n\n"
            "Digite *pular* para pular uma pergunta, ou *cancelar* para sair a qualquer momento.\n\n"
            f"(1/{_WA_DIAG_TOTAL}) {first_q}"
        )

    return None  # not handled here


def _wad_complete_session(db, session: WaDiagSession, answers: dict,
                           company_id: int, client_id: int) -> str:
    """Finalize session, save profile, return summary."""
    session.is_complete = True
    session.updated_at = _dt_wd.utcnow().isoformat()
    db.add(session)
    db.commit()

    _wd_save_profile(db, company_id, client_id, answers)
    return _wd_summary(answers)


# ── Startup ───────────────────────────────────────────────────────────────────

try:
    _ensure_wad_tables()
except Exception as _e_wad:
    print(f"[wad] tabela erro: {_e_wad}")

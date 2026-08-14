# ui_conciliacao_extrato.py
# Importa extrato bancário CSV e exibe tela de conciliação estilo ContaAzul
# Exec'd no namespace do app.py

import io as _io_ce
import csv as _csv_ce
import re as _re_ce
from datetime import date as _date_ce, timedelta as _td_ce
from typing import Optional as _Opt_ce, List as _List_ce
from fastapi import Request as _Req_ce, Depends as _Dep_ce, Form as _Form_ce, UploadFile as _Upload_ce, File as _File_ce
from fastapi.responses import HTMLResponse as _HTML_ce, RedirectResponse as _RR_ce, JSONResponse as _JSON_ce
from sqlmodel import Session as _Sess_ce, Field as _Field_ce, select as _sel_ce, SQLModel as _SM_ce
from sqlalchemy import text as _txt_ce

# ─── Modelo ──────────────────────────────────────────────────────────────────

class BankStatementLine(_SM_ce, table=True):  # type: ignore[name-defined]
    __tablename__ = "bank_statement_line"
    id: _Opt_ce[int] = _Field_ce(default=None, primary_key=True)
    company_id: int = _Field_ce(index=True)
    import_batch: str = _Field_ce(default="", index=True)   # YYYY-MM-DD-timestamp
    release_date: str = _Field_ce(default="")               # YYYY-MM-DD
    transaction_type: str = _Field_ce(default="")
    reference_id: str = _Field_ce(default="")
    amount_cents: int = _Field_ce(default=0)                # negativo = débito
    partial_balance_cents: int = _Field_ce(default=0)
    status: str = _Field_ce(default="pendente", index=True) # pendente | conciliado | ignorado
    matched_entry_id: _Opt_ce[int] = _Field_ce(default=None)
    created_at: str = _Field_ce(default="")

# ─── Migração ─────────────────────────────────────────────────────────────────

def _ce_ensure_table():
    try:
        BankStatementLine.metadata.create_all(engine)  # type: ignore[name-defined]
        return True
    except Exception as _e:
        print(f"[ce] tabela bank_statement_line: {_e}")
        return False

_ce_ensure_table()

# ─── Helpers ─────────────────────────────────────────────────────────────────

def _ce_parse_brl(s: str) -> int:
    """'1.234,56' → 123456 cents  |  '-98,00' → -9800"""
    s = s.strip()
    neg = s.startswith("-")
    s = s.lstrip("-").replace(".", "").replace(",", ".")
    try:
        return int(round(float(s) * 100)) * (-1 if neg else 1)
    except Exception:
        return 0

def _ce_parse_date(s: str) -> str:
    """'01-08-2026' → '2026-08-01'"""
    parts = s.strip().split("-")
    if len(parts) == 3 and len(parts[2]) == 4:
        return f"{parts[2]}-{parts[1]}-{parts[0]}"
    return s

def _ce_cents_brl(c: int) -> str:
    v = abs(c) / 100
    formatted = f"R$ {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"-{formatted}" if c < 0 else formatted

def _ce_parse_csv(content: bytes) -> list:
    """Parseia extrato CSV no formato do Nubank/Inter (ponto-e-vírgula)."""
    text = content.decode("utf-8-sig", errors="replace")
    lines = [l.strip() for l in text.splitlines()]

    # Pula cabeçalho sumário e acha a linha de colunas das transações
    header_idx = None
    for i, line in enumerate(lines):
        if "RELEASE_DATE" in line or "Data" in line.upper():
            header_idx = i
            break
    if header_idx is None:
        return []

    # Detecta separador
    sample = lines[header_idx]
    sep = ";" if ";" in sample else ","

    reader = _csv_ce.DictReader(lines[header_idx:], delimiter=sep)
    rows = []
    for row in reader:
        # Normaliza chaves
        r = {k.strip().upper().replace(" ", "_"): v.strip() for k, v in row.items() if k}
        date_raw  = r.get("RELEASE_DATE") or r.get("DATA") or ""
        tipo_raw  = r.get("TRANSACTION_TYPE") or r.get("DESCRICAO") or r.get("HISTÓRICO") or ""
        ref_raw   = r.get("REFERENCE_ID") or r.get("DOCUMENTO") or ""
        amt_raw   = r.get("TRANSACTION_NET_AMOUNT") or r.get("VALOR") or "0"
        bal_raw   = r.get("PARTIAL_BALANCE") or r.get("SALDO") or "0"
        if not date_raw or not tipo_raw:
            continue
        rows.append({
            "release_date":        _ce_parse_date(date_raw),
            "transaction_type":    tipo_raw,
            "reference_id":        ref_raw,
            "amount_cents":        _ce_parse_brl(amt_raw),
            "partial_balance_cents": _ce_parse_brl(bal_raw),
        })
    return rows


def _ce_auto_match(session, company_id: int, amount_cents: int, release_date: str):
    """Tenta encontrar um OfficeFinancialEntry com valor e data compatíveis."""
    try:
        amount_brl = abs(amount_cents) / 100
        entry_kind = "receber" if amount_cents > 0 else "pagar"
        # Janela de ±5 dias
        try:
            dt = _date_ce.fromisoformat(release_date)
            d_min = (dt - _td_ce(days=5)).isoformat()
            d_max = (dt + _td_ce(days=5)).isoformat()
        except Exception:
            d_min = d_max = release_date

        rows = session.exec(
            _sel_ce(OfficeFinancialEntry).where(  # type: ignore[name-defined]
                OfficeFinancialEntry.company_id == company_id,  # type: ignore[name-defined]
                OfficeFinancialEntry.entry_kind == entry_kind,
                OfficeFinancialEntry.status.in_(["aberto", "vencido"]),
                OfficeFinancialEntry.due_date >= d_min,
                OfficeFinancialEntry.due_date <= d_max,
            )
        ).all()
        for e in rows:
            if abs(float(e.amount_expected_brl or 0) - amount_brl) < 0.02:
                return e
    except Exception as _ex:
        print(f"[ce] auto_match: {_ex}")
    return None


# ─── Endpoints ───────────────────────────────────────────────────────────────

try:
    @app.post("/admin/financeiro/conciliacao/importar-extrato")  # type: ignore[name-defined]
    @require_role({"admin", "equipe"})  # type: ignore[name-defined]
    async def ce_importar_extrato(
        request: _Req_ce,
        session: _Sess_ce = _Dep_ce(get_session),  # type: ignore[name-defined]
        arquivo: _Upload_ce = _File_ce(...),
    ):
        ctx = get_tenant_context(request, session)  # type: ignore[name-defined]
        assert ctx is not None
        if not _ce_ensure_table():
            set_flash(request, "Erro ao inicializar tabela de extrato.")  # type: ignore[name-defined]
            return _RR_ce("/admin/financeiro/conciliacao", status_code=303)

        content = await arquivo.read()
        parsed = _ce_parse_csv(content)
        if not parsed:
            set_flash(request, "Nenhuma transação encontrada no arquivo. Verifique o formato.")  # type: ignore[name-defined]
            return _RR_ce("/admin/financeiro/conciliacao", status_code=303)

        from datetime import datetime as _dt_ce
        batch = _dt_ce.now().strftime("%Y%m%d%H%M%S")

        for p in parsed:
            match = _ce_auto_match(session, ctx.company.id, p["amount_cents"], p["release_date"])
            line = BankStatementLine(
                company_id=ctx.company.id,
                import_batch=batch,
                release_date=p["release_date"],
                transaction_type=p["transaction_type"],
                reference_id=p["reference_id"],
                amount_cents=p["amount_cents"],
                partial_balance_cents=p["partial_balance_cents"],
                status="pendente",
                matched_entry_id=match.id if match else None,
                created_at=_dt_ce.now().isoformat(),
            )
            session.add(line)
        session.commit()

        set_flash(request, f"{len(parsed)} transações importadas. Lote: {batch}.")  # type: ignore[name-defined]
        return _RR_ce(f"/admin/financeiro/conciliacao?tab=extrato&batch={batch}", status_code=303)

    print("[ce] POST /admin/financeiro/conciliacao/importar-extrato registrado")
except Exception as _e1:
    print(f"[ce] importar-extrato: {_e1}")


try:
    @app.post("/admin/financeiro/conciliacao/linha/{line_id}/conciliar")  # type: ignore[name-defined]
    @require_role({"admin", "equipe"})  # type: ignore[name-defined]
    async def ce_conciliar_linha(
        request: _Req_ce,
        session: _Sess_ce = _Dep_ce(get_session),  # type: ignore[name-defined]
        line_id: int = 0,
        entry_id: str = _Form_ce(""),
        settlement_date: str = _Form_ce(""),
        category_id: str = _Form_ce(""),
        supplier_id: str = _Form_ce(""),
        cost_center_id: str = _Form_ce(""),
        notes: str = _Form_ce(""),
        batch: str = _Form_ce(""),
    ):
        ctx = get_tenant_context(request, session)  # type: ignore[name-defined]
        assert ctx is not None
        line = session.get(BankStatementLine, line_id)
        if not line or line.company_id != ctx.company.id:
            set_flash(request, "Linha não encontrada.")  # type: ignore[name-defined]
            return _RR_ce(f"/admin/financeiro/conciliacao?tab=extrato&batch={batch}", status_code=303)

        eid = int(entry_id) if entry_id.strip().isdigit() else None
        if eid:
            # Concilia com lançamento existente
            entry = session.get(OfficeFinancialEntry, eid)  # type: ignore[name-defined]
            if entry and entry.company_id == ctx.company.id:
                entry.amount_realized_brl = abs(line.amount_cents) / 100
                entry.settlement_date = settlement_date or line.release_date
                entry.status = "recebido" if entry.entry_kind == "receber" else "pago"
                entry.notes = (entry.notes or "") + ("\n" + notes if notes else "")
                session.add(entry)
                line.matched_entry_id = eid
        else:
            # Cria novo lançamento a partir do extrato
            entry_kind = "receber" if line.amount_cents > 0 else "pagar"
            new_entry = OfficeFinancialEntry(  # type: ignore[name-defined]
                company_id=ctx.company.id,
                created_by_user_id=ctx.user.id,
                entry_kind=entry_kind,
                status="recebido" if entry_kind == "receber" else "pago",
                description=line.transaction_type,
                document_number=line.reference_id,
                due_date=line.release_date,
                settlement_date=settlement_date or line.release_date,
                amount_expected_brl=abs(line.amount_cents) / 100,
                amount_realized_brl=abs(line.amount_cents) / 100,
                category_id=int(category_id) if category_id.strip().isdigit() else None,
                supplier_id=int(supplier_id) if supplier_id.strip().isdigit() else None,
                cost_center_id=int(cost_center_id) if cost_center_id.strip().isdigit() else None,
                notes=notes,
            )
            session.add(new_entry)
            session.flush()
            line.matched_entry_id = new_entry.id

        line.status = "conciliado"
        session.add(line)
        session.commit()
        return _RR_ce(f"/admin/financeiro/conciliacao?tab=extrato&batch={batch}", status_code=303)

    print("[ce] POST /admin/financeiro/conciliacao/linha/{id}/conciliar registrado")
except Exception as _e2:
    print(f"[ce] conciliar_linha: {_e2}")


try:
    @app.post("/admin/financeiro/conciliacao/linha/{line_id}/ignorar")  # type: ignore[name-defined]
    @require_role({"admin", "equipe"})  # type: ignore[name-defined]
    async def ce_ignorar_linha(
        request: _Req_ce,
        session: _Sess_ce = _Dep_ce(get_session),  # type: ignore[name-defined]
        line_id: int = 0,
        batch: str = _Form_ce(""),
    ):
        ctx = get_tenant_context(request, session)  # type: ignore[name-defined]
        assert ctx is not None
        line = session.get(BankStatementLine, line_id)
        if line and line.company_id == ctx.company.id:
            line.status = "ignorado"
            session.add(line)
            session.commit()
        return _RR_ce(f"/admin/financeiro/conciliacao?tab=extrato&batch={batch}", status_code=303)

    print("[ce] POST /admin/financeiro/conciliacao/linha/{id}/ignorar registrado")
except Exception as _e3:
    print(f"[ce] ignorar_linha: {_e3}")


try:
    @app.get("/admin/financeiro/conciliacao/lotes")  # type: ignore[name-defined]
    @require_role({"admin", "equipe"})  # type: ignore[name-defined]
    async def ce_listar_lotes(request: _Req_ce, session: _Sess_ce = _Dep_ce(get_session)):  # type: ignore[name-defined]
        ctx = get_tenant_context(request, session)  # type: ignore[name-defined]
        assert ctx is not None
        try:
            rows = session.exec(
                _sel_ce(BankStatementLine.import_batch, BankStatementLine.release_date).where(
                    BankStatementLine.company_id == ctx.company.id
                ).distinct().order_by(BankStatementLine.import_batch.desc())
            ).all()
            batches = list(dict.fromkeys(r[0] for r in rows))
            return _JSON_ce([{"batch": b} for b in batches[:20]])
        except Exception:
            return _JSON_ce([])

    print("[ce] GET /admin/financeiro/conciliacao/lotes registrado")
except Exception as _e4:
    print(f"[ce] lotes: {_e4}")

print("[ce] Modulo ui_conciliacao_extrato carregado")

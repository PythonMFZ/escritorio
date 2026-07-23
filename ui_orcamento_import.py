# ui_orcamento_import.py — Importação de Realizado via planilha (de:para)
# Exec'd no namespace do app.py via ui_orcamento.py

import uuid     as _uimp_uuid
import csv      as _uimp_csv
import io       as _uimp_io
import re       as _uimp_re
import json     as _uimp_json
from datetime   import datetime as _uimp_dt, timedelta as _uimp_td

# ── Cache de uploads em memória (TTL 2h) ──────────────────────────────────────
_ORC_UPLOAD_CACHE: dict = {}

# ── Modelos ────────────────────────────────────────────────────────────────────

class BudgetImportConfig(SQLModel, table=True):
    __tablename__ = "budgetimportconfig"
    __table_args__ = {"extend_existing": True}
    id:          Optional[int] = Field(default=None, primary_key=True)
    company_id:  int           = Field(index=True)
    account_col: int           = Field(default=8)
    date_col:    int           = Field(default=14)
    value_col:   int           = Field(default=7)
    header_row:  int           = Field(default=1)
    updated_at:  datetime      = Field(default_factory=utcnow)

class BudgetAccountMapping(SQLModel, table=True):
    __tablename__ = "budgetaccountmapping"
    __table_args__ = (
        UniqueConstraint("company_id", "external_key", name="uq_bam_key"),
        {"extend_existing": True},
    )
    id:                Optional[int] = Field(default=None, primary_key=True)
    company_id:        int           = Field(index=True)
    external_key:      str           = Field(default="")
    budget_account_id: Optional[int] = Field(default=None)
    updated_at:        datetime      = Field(default_factory=utcnow)

# ── Criação das tabelas ────────────────────────────────────────────────────────
try:
    for _tbl in (BudgetImportConfig.__table__, BudgetAccountMapping.__table__):
        _tbl.create(engine, checkfirst=True)
except Exception as _e:
    print(f"[orc-import] tabelas: {_e}")

# ── Helpers de parsing ─────────────────────────────────────────────────────────

def _uimp_normalize(s) -> str:
    s = str(s or "").strip().upper()
    return _uimp_re.sub(r"[.\-\s/]", "", s).lstrip("0")

def _uimp_auto_match(ext_key: str, accounts) -> "Optional[int]":
    norm  = _uimp_normalize(ext_key)
    lower = str(ext_key).strip().lower()
    for acc in accounts:
        if norm and _uimp_normalize(acc.code) == norm:
            return acc.id
    for acc in accounts:
        if acc.name.strip().lower() == lower:
            return acc.id
    for acc in accounts:
        an = acc.name.strip().lower()
        if lower and len(lower) > 4 and (lower in an or an in lower):
            return acc.id
    return None

def _uimp_parse_date(val) -> tuple:
    """Returns (year, month). Raises ValueError on failure."""
    from datetime import date as _d
    if isinstance(val, _uimp_dt):
        return val.year, val.month
    if isinstance(val, _d):
        return val.year, val.month
    s = str(val or "").strip()
    m = _uimp_re.match(r"(\d{1,2})/(\d{1,2})/(\d{4})", s)
    if m: return int(m.group(3)), int(m.group(2))
    m = _uimp_re.match(r"(\d{4})-(\d{2})-(\d{2})", s)
    if m: return int(m.group(1)), int(m.group(2))
    m = _uimp_re.match(r"(\d{1,2})/(\d{4})", s)
    if m: return int(m.group(2)), int(m.group(1))
    raise ValueError(f"Data inválida: {val!r}")

def _uimp_parse_value(val) -> float:
    if isinstance(val, (int, float)):
        return float(val)
    s = str(val or "").strip().replace("R$", "").strip()
    # Handle Brazilian format: 1.234,56 → 1234.56
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".")
    elif "," in s:
        s = s.replace(",", ".")
    try:
        return float(s)
    except Exception:
        return 0.0

def _uimp_parse_file(file_bytes: bytes, filename: str) -> list:
    """Returns list of rows (each row = list of raw values)."""
    fn = filename.lower()
    if fn.endswith(".xlsx") or fn.endswith(".xls"):
        try:
            import openpyxl as _opxl
        except ImportError:
            raise ImportError("Instale openpyxl: pip install openpyxl")
        wb = _opxl.load_workbook(_uimp_io.BytesIO(file_bytes), data_only=True)
        ws = wb.active
        return [list(row) for row in ws.iter_rows(values_only=True)]
    else:
        text = file_bytes.decode("utf-8-sig", errors="replace")
        sample = text[:2000]
        delim  = ";" if sample.count(";") > sample.count(",") else ","
        reader = _uimp_csv.reader(_uimp_io.StringIO(text), delimiter=delim)
        return [list(row) for row in reader]

def _uimp_clean_cache():
    now = _uimp_dt.utcnow()
    for k in [k for k, v in _ORC_UPLOAD_CACHE.items() if v["expires"] < now]:
        _ORC_UPLOAD_CACHE.pop(k, None)

# ── Rotas ─────────────────────────────────────────────────────────────────────

@app.get("/ferramentas/orcamento/importar", response_class=HTMLResponse)
@require_login
async def orc_import_page(request: Request, session: Session = Depends(get_session)):
    ctx = get_tenant_context(request, session)
    if not ctx or ctx.membership.role not in ("admin", "equipe"):
        return RedirectResponse("/", status_code=303)
    cc  = get_client_or_none(session, ctx.company.id, get_active_client_id(request, session, ctx))
    plans = session.exec(
        select(BudgetPlan).where(BudgetPlan.company_id == ctx.company.id, BudgetPlan.is_active == True)
        .order_by(BudgetPlan.year.desc())
    ).all()
    cfg = session.exec(
        select(BudgetImportConfig).where(BudgetImportConfig.company_id == ctx.company.id)
    ).first()
    return render("orc_importar.html", request=request, context={
        "current_user": ctx.user, "current_company": ctx.company,
        "role": ctx.membership.role, "current_client": cc,
        "plans": plans, "cfg": cfg,
    })


@app.post("/api/orcamento/importar/upload")
@require_login
async def orc_import_upload(request: Request, session: Session = Depends(get_session)):
    """Step 1: parse file, store in cache, return column info."""
    ctx = get_tenant_context(request, session)
    if not ctx or ctx.membership.role not in ("admin", "equipe"):
        return JSONResponse({"ok": False}, status_code=403)
    try:
        form     = await request.form()
        file_obj = form.get("file")
        if not file_obj or not hasattr(file_obj, "read"):
            return JSONResponse({"ok": False, "error": "Arquivo não enviado."})
        file_bytes = await file_obj.read()
        filename   = getattr(file_obj, "filename", None) or "upload.xlsx"

        rows = _uimp_parse_file(file_bytes, filename)

        # Detect header row (first non-empty row)
        header_row_idx = 0
        for i, row in enumerate(rows[:10]):
            if any(c is not None and str(c).strip() for c in row):
                header_row_idx = i
                break

        raw_headers = rows[header_row_idx] if rows else []
        headers = [str(c) if c is not None else f"Col {i}" for i, c in enumerate(raw_headers)]
        data_rows = [r for r in rows[header_row_idx + 1:] if any(c is not None for c in r)]

        # Sample: first 4 data rows (display only)
        sample = [[str(c) if c is not None else "" for c in r] for r in data_rows[:4]]

        cfg = session.exec(
            select(BudgetImportConfig).where(BudgetImportConfig.company_id == ctx.company.id)
        ).first()

        upload_key = str(_uimp_uuid.uuid4())
        _uimp_clean_cache()
        _ORC_UPLOAD_CACHE[upload_key] = {
            "rows": rows,
            "filename": filename,
            "header_row_idx": header_row_idx,
            "expires": _uimp_dt.utcnow() + _uimp_td(hours=2),
            "company_id": ctx.company.id,
        }

        return JSONResponse({
            "ok": True,
            "upload_key": upload_key,
            "filename": filename,
            "total_rows": len(data_rows),
            "total_cols": len(headers),
            "headers": headers,
            "sample": sample,
            "header_row_idx": header_row_idx,
            "saved_config": {
                "account_col": cfg.account_col,
                "date_col":    cfg.date_col,
                "value_col":   cfg.value_col,
            } if cfg else None,
        })
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)})


@app.post("/api/orcamento/importar/analisar")
@require_login
async def orc_import_analisar(request: Request, session: Session = Depends(get_session)):
    """Step 2: given column choices, return unique accounts + auto-match."""
    ctx = get_tenant_context(request, session)
    if not ctx or ctx.membership.role not in ("admin", "equipe"):
        return JSONResponse({"ok": False}, status_code=403)

    body           = await request.json()
    upload_key     = body.get("upload_key")
    account_col    = int(body.get("account_col") or 0)
    date_col       = int(body.get("date_col") or 1)
    value_col      = int(body.get("value_col") or 2)
    header_row_idx = int(body.get("header_row_idx") or 0)
    plan_id        = int(body.get("plan_id") or 0)

    cached = _ORC_UPLOAD_CACHE.get(upload_key)
    if not cached or cached["company_id"] != ctx.company.id:
        return JSONResponse({"ok": False, "error": "Upload expirado. Faça o upload novamente."})

    # Resolve client_id do plano selecionado para filtrar contas corretamente
    plan_client_id = None
    if plan_id:
        plan = session.get(BudgetPlan, plan_id)
        if plan and plan.company_id == ctx.company.id:
            plan_client_id = plan.client_id

    rows      = cached["rows"]
    data_rows = [r for r in rows[header_row_idx + 1:] if any(c is not None for c in r)]

    # Aggregate per external account key
    unique: dict = {}   # ext_key → {count, total, months: set}
    years_seen   = set()
    date_errors  = 0

    for row in data_rows:
        try:
            ext_key = str(row[account_col] if account_col < len(row) else "").strip()
            if not ext_key or ext_key.lower() == "none":
                continue
            val = _uimp_parse_value(row[value_col] if value_col < len(row) else 0)
            try:
                year, month = _uimp_parse_date(row[date_col] if date_col < len(row) else None)
                years_seen.add(year)
                month_label = f"{year}/{month:02d}"
            except Exception:
                date_errors += 1
                month_label = "?"

            if ext_key not in unique:
                unique[ext_key] = {"count": 0, "total": 0.0, "months": set()}
            unique[ext_key]["count"] += 1
            unique[ext_key]["total"] += val
            unique[ext_key]["months"].add(month_label)
        except Exception:
            pass

    # Carrega contas do plano de contas do cliente específico
    acc_query = select(BudgetAccount).where(
        BudgetAccount.company_id   == ctx.company.id,
        BudgetAccount.is_active    == True,
        BudgetAccount.is_totalizer == False,
    )
    if plan_client_id is not None:
        acc_query = acc_query.where(BudgetAccount.client_id == plan_client_id)

    accounts = session.exec(acc_query).all()

    # Mapeamentos salvos — filtrados pelo client_id do plano
    map_query = select(BudgetAccountMapping).where(
        BudgetAccountMapping.company_id == ctx.company.id
    )
    if plan_client_id is not None:
        # Filtra mapeamentos cujo budget_account_id pertence ao cliente correto
        valid_acc_ids = {a.id for a in accounts}
        saved_maps = {
            m.external_key: m.budget_account_id
            for m in session.exec(map_query).all()
            if m.budget_account_id in valid_acc_ids
        }
    else:
        saved_maps = {
            m.external_key: m.budget_account_id
            for m in session.exec(map_query).all()
        }

    result_accounts = []
    for ext_key, stats in sorted(unique.items(), key=lambda x: -x[1]["count"]):
        if ext_key in saved_maps:
            matched_id  = saved_maps[ext_key]
            match_source = "salvo"
        else:
            matched_id  = _uimp_auto_match(ext_key, accounts)
            match_source = "auto" if matched_id else "sem_match"

        result_accounts.append({
            "external_key": ext_key,
            "count":        stats["count"],
            "total":        round(stats["total"], 2),
            "months":       sorted(stats["months"]),
            "matched_id":   matched_id,
            "match_source": match_source,
        })

    acc_options = [
        {"id": a.id, "code": a.code, "name": a.name}
        for a in sorted(accounts, key=lambda x: x.code)
    ]

    return JSONResponse({
        "ok": True,
        "unique_accounts": result_accounts,
        "acc_options": acc_options,
        "years_seen": sorted(years_seen),
        "total_rows": len(data_rows),
        "date_errors": date_errors,
    })


@app.post("/api/orcamento/importar/mapeamento/salvar")
@require_login
async def orc_import_salvar_mapeamento(request: Request, session: Session = Depends(get_session)):
    """Persist column config + account mappings for reuse."""
    ctx = get_tenant_context(request, session)
    if not ctx or ctx.membership.role not in ("admin", "equipe"):
        return JSONResponse({"ok": False}, status_code=403)

    body        = await request.json()
    mappings    = body.get("mappings", {})
    account_col = int(body.get("account_col") or 0)
    date_col    = int(body.get("date_col") or 1)
    value_col   = int(body.get("value_col") or 2)
    header_row  = int(body.get("header_row_idx") or 0)

    cfg = session.exec(
        select(BudgetImportConfig).where(BudgetImportConfig.company_id == ctx.company.id)
    ).first()
    if not cfg:
        cfg = BudgetImportConfig(company_id=ctx.company.id)
    cfg.account_col = account_col
    cfg.date_col    = date_col
    cfg.value_col   = value_col
    cfg.header_row  = header_row
    cfg.updated_at  = utcnow()
    session.add(cfg)

    for ext_key, acc_id in mappings.items():
        existing = session.exec(
            select(BudgetAccountMapping).where(
                BudgetAccountMapping.company_id   == ctx.company.id,
                BudgetAccountMapping.external_key == ext_key,
            )
        ).first()
        _aid = int(acc_id) if acc_id else None
        if existing:
            existing.budget_account_id = _aid
            existing.updated_at = utcnow()
            session.add(existing)
        else:
            session.add(BudgetAccountMapping(
                company_id=ctx.company.id,
                external_key=ext_key,
                budget_account_id=_aid,
            ))

    session.commit()
    return JSONResponse({"ok": True, "saved": len(mappings)})


@app.post("/api/orcamento/importar/executar")
@require_login
async def orc_import_executar(request: Request, session: Session = Depends(get_session)):
    """Step 4: aggregate rows by (account_id, month) and upsert value_realized."""
    ctx = get_tenant_context(request, session)
    if not ctx or ctx.membership.role not in ("admin", "equipe"):
        return JSONResponse({"ok": False}, status_code=403)

    body           = await request.json()
    upload_key     = body.get("upload_key")
    plan_id        = int(body.get("plan_id") or 0)
    account_col    = int(body.get("account_col") or 0)
    date_col       = int(body.get("date_col") or 1)
    value_col      = int(body.get("value_col") or 2)
    header_row_idx = int(body.get("header_row_idx") or 0)
    mappings       = body.get("mappings", {})  # {external_key: account_id or null}

    cached = _ORC_UPLOAD_CACHE.get(upload_key)
    if not cached or cached["company_id"] != ctx.company.id:
        return JSONResponse({"ok": False, "error": "Upload expirado. Faça o upload novamente."})

    plan = session.get(BudgetPlan, plan_id)
    if not plan or plan.company_id != ctx.company.id:
        return JSONResponse({"ok": False, "error": "Plano não encontrado."})

    rows      = cached["rows"]
    data_rows = [r for r in rows[header_row_idx + 1:] if any(c is not None for c in r)]

    # Also load DB mappings as fallback
    db_maps = {
        m.external_key: m.budget_account_id
        for m in session.exec(
            select(BudgetAccountMapping).where(BudgetAccountMapping.company_id == ctx.company.id)
        ).all()
    }

    # Aggregate: (account_id, month) → sum of values
    aggregated: dict = {}
    skipped_no_map  = 0
    skipped_no_date = 0
    processed       = 0

    for row in data_rows:
        if not any(c is not None for c in row):
            continue
        try:
            ext_key = str(row[account_col] if account_col < len(row) else "").strip()
            if not ext_key or ext_key.lower() == "none":
                continue

            # Resolve account_id: request payload → DB mapping
            acc_id = mappings.get(ext_key)
            if acc_id is None:
                acc_id = db_maps.get(ext_key)
            if not acc_id:
                skipped_no_map += 1
                continue

            try:
                year, month = _uimp_parse_date(row[date_col] if date_col < len(row) else None)
            except Exception:
                skipped_no_date += 1
                continue

            val = _uimp_parse_value(row[value_col] if value_col < len(row) else 0)
            key = (int(acc_id), month)
            aggregated[key] = aggregated.get(key, 0.0) + val
            processed += 1
        except Exception:
            pass

    # Upsert BudgetEntry.value_realized
    upserted = 0
    for (acc_id, month), total in aggregated.items():
        existing = session.exec(
            select(BudgetEntry).where(
                BudgetEntry.plan_id    == plan_id,
                BudgetEntry.account_id == acc_id,
                BudgetEntry.month      == month,
            )
        ).first()
        if existing:
            existing.value_realized = round(total, 2)
            existing.updated_at     = utcnow()
            session.add(existing)
        else:
            session.add(BudgetEntry(
                company_id    = ctx.company.id,
                plan_id       = plan_id,
                account_id    = acc_id,
                month         = month,
                value_budgeted = 0.0,
                value_realized = round(total, 2),
            ))
        upserted += 1

    session.commit()
    _ORC_UPLOAD_CACHE.pop(upload_key, None)

    return JSONResponse({
        "ok": True,
        "upserted":       upserted,
        "processed_rows": processed,
        "skipped_no_map": skipped_no_map,
        "skipped_no_date": skipped_no_date,
        "total_value":    round(sum(aggregated.values()), 2),
    })


# ── Template ────────────────────────────────────────────────────────────────────

TEMPLATES["orc_importar.html"] = r"""
{% extends "base.html" %}
{% block content %}
<div class="container-lg py-4" style="max-width:960px;">

  <!-- Cabeçalho -->
  <div class="d-flex align-items-center gap-2 mb-3">
    <a href="/ferramentas/orcamento" class="btn btn-sm btn-outline-secondary">← Orçamento</a>
    <h5 class="mb-0">📥 Importar Realizado — Planilha de Lançamentos</h5>
  </div>

  <!-- Steps indicator -->
  <div class="d-flex gap-0 mb-4" id="stepBar">
    {% for label in ["1. Upload","2. Colunas","3. De:Para","4. Confirmar"] %}
    <div class="px-3 py-1 border step-pill" id="pill{{ loop.index }}"
         style="font-size:.8rem;border-radius:{% if loop.first %}8px 0 0 8px{% elif loop.last %}0 8px 8px 0{% else %}0{% endif %};background:{% if loop.first %}#0d6efd;color:#fff{% else %}#f8f9fa;color:#6c757d{% endif %};">
      {{ label }}
    </div>
    {% endfor %}
  </div>

  <!-- ── PASSO 1: Selecionar plano + upload ───────────────────────────── -->
  <div id="passo1">
    <div class="card shadow-sm mb-3">
      <div class="card-body">
        <div class="mb-3">
          <label class="form-label fw-semibold">Plano Orçamentário</label>
          <select id="selPlano" class="form-select" style="max-width:360px;">
            <option value="">— Selecione o plano —</option>
            {% for p in plans %}
            <option value="{{ p.id }}">{{ p.name }} ({{ p.year }})</option>
            {% endfor %}
          </select>
        </div>
        <div class="mb-3">
          <label class="form-label fw-semibold">Planilha de Lançamentos <span class="text-muted fw-normal">(XLSX ou CSV)</span></label>
          <input type="file" id="fileInput" class="form-control" accept=".xlsx,.xls,.csv" style="max-width:480px;">
          <div class="form-text">Exportação do Sisplan, Omie, Conta Azul, Sienge, etc.</div>
        </div>
        <button class="btn btn-primary" onclick="uploadArquivo()">Analisar Arquivo →</button>
        <span id="uploadStatus" class="ms-2 text-muted small"></span>
      </div>
    </div>
  </div>

  <!-- ── PASSO 2: Configurar colunas ──────────────────────────────────── -->
  <div id="passo2" style="display:none;">
    <div class="card shadow-sm mb-3">
      <div class="card-body">
        <div class="d-flex justify-content-between align-items-start mb-3">
          <div>
            <div class="fw-semibold">✅ Arquivo carregado: <span id="p2Filename"></span></div>
            <div class="text-muted small"><span id="p2Rows"></span> linhas × <span id="p2Cols"></span> colunas</div>
          </div>
          <button class="btn btn-sm btn-outline-secondary" onclick="voltarPasso(1)">← Trocar arquivo</button>
        </div>

        <!-- Sample preview -->
        <div class="mb-3" style="overflow-x:auto;">
          <div class="fw-semibold mb-1" style="font-size:.82rem;">Prévia (primeiras linhas):</div>
          <table class="table table-sm table-bordered" style="font-size:.72rem;" id="sampleTable"></table>
        </div>

        <!-- Column selectors -->
        <div class="row g-3 mb-3">
          <div class="col-md-4">
            <label class="form-label fw-semibold">Coluna de Conta</label>
            <select id="selAccCol" class="form-select form-select-sm"></select>
            <div class="form-text">Nome ou código da conta (ex: Desc_Classe, Classe)</div>
          </div>
          <div class="col-md-4">
            <label class="form-label fw-semibold">Coluna de Data</label>
            <select id="selDateCol" class="form-select form-select-sm"></select>
            <div class="form-text">Data de competência do lançamento</div>
          </div>
          <div class="col-md-4">
            <label class="form-label fw-semibold">Coluna de Valor</label>
            <select id="selValCol" class="form-select form-select-sm"></select>
            <div class="form-text">Valor a importar como Realizado</div>
          </div>
        </div>

        <button class="btn btn-primary" onclick="analisarColunas()">Próximo → Mapeamento de Contas</button>
        <span id="analisarStatus" class="ms-2 text-muted small"></span>
      </div>
    </div>
  </div>

  <!-- ── PASSO 3: De:Para ──────────────────────────────────────────────── -->
  <div id="passo3" style="display:none;">
    <div class="card shadow-sm mb-3">
      <div class="card-body">
        <div class="d-flex justify-content-between align-items-start mb-2">
          <div>
            <div class="fw-semibold">🔗 Mapeamento de Contas</div>
            <div class="text-muted small">
              <span id="p3Stats"></span>
              &nbsp;· <span class="badge bg-success">auto</span> = match automático
              &nbsp;· <span class="badge bg-primary">salvo</span> = mapeamento salvo
              &nbsp;· <span class="badge bg-warning text-dark">sem match</span> = defina abaixo
            </div>
          </div>
          <button class="btn btn-sm btn-outline-secondary" onclick="voltarPasso(2)">← Voltar</button>
        </div>

        <div style="overflow-x:auto;max-height:420px;overflow-y:auto;">
          <table class="table table-sm table-hover" style="font-size:.78rem;" id="mapTable">
            <thead class="table-light sticky-top">
              <tr>
                <th style="min-width:220px;">Conta Externa (Planilha)</th>
                <th class="text-end">Linhas</th>
                <th class="text-end">Total R$</th>
                <th style="min-width:260px;">→ Conta do Plano</th>
                <th></th>
              </tr>
            </thead>
            <tbody id="mapBody"></tbody>
          </table>
        </div>

        <div class="mt-3 d-flex gap-2">
          <button class="btn btn-outline-secondary btn-sm" onclick="salvarMapeamentos()">💾 Salvar mapeamentos para reutilizar</button>
          <button class="btn btn-primary" onclick="irParaConfirmacao()">Próximo → Confirmar →</button>
        </div>
        <span id="mapStatus" class="d-block mt-1 text-muted small"></span>
      </div>
    </div>
  </div>

  <!-- ── PASSO 4: Preview + Confirmar ─────────────────────────────────── -->
  <div id="passo4" style="display:none;">
    <div class="card shadow-sm mb-3">
      <div class="card-body">
        <div class="d-flex justify-content-between align-items-start mb-3">
          <div class="fw-semibold">✅ Confirmar Importação</div>
          <button class="btn btn-sm btn-outline-secondary" onclick="voltarPasso(3)">← Voltar</button>
        </div>

        <div class="row g-2 mb-3" id="p4Summary"></div>

        <div id="p4Alert" class="alert alert-warning py-2" style="display:none;font-size:.82rem;"></div>

        <div style="overflow-x:auto;max-height:380px;overflow-y:auto;">
          <table class="table table-sm" style="font-size:.78rem;" id="p4Table">
            <thead class="table-light sticky-top">
              <tr><th>Conta (plano)</th><th class="text-end">Meses</th><th class="text-end">Total R$</th></tr>
            </thead>
            <tbody id="p4Body"></tbody>
          </table>
        </div>

        <div class="mt-3 d-flex align-items-center gap-3">
          <button class="btn btn-success" onclick="executarImport()" id="btnExecutar">
            ✅ Confirmar e Importar Realizado
          </button>
          <span id="execStatus" class="text-muted small"></span>
        </div>
      </div>
    </div>
  </div>

  <!-- ── RESULTADO ─────────────────────────────────────────────────────── -->
  <div id="resultado" style="display:none;" class="card border-success shadow-sm">
    <div class="card-body">
      <h6 class="text-success fw-semibold">🎉 Importação concluída!</h6>
      <div id="resultadoBody"></div>
      <div class="mt-3 d-flex gap-2">
        <a id="btnVerOrc" href="#" class="btn btn-primary btn-sm">Ver Orçamento →</a>
        <button class="btn btn-outline-secondary btn-sm" onclick="location.reload()">Nova Importação</button>
      </div>
    </div>
  </div>

</div>

<script>
// ── Estado global ──────────────────────────────────────────────────────────
var _imp = {
  upload_key:     null,
  plan_id:        null,
  filename:       null,
  total_rows:     0,
  total_cols:     0,
  headers:        [],
  sample:         [],
  header_row_idx: 0,
  account_col:    0,
  date_col:       1,
  value_col:      2,
  unique_accounts: [],
  acc_options:    [],
  mappings:       {},   // ext_key → account_id or null
  years_seen:     [],
};

var _MONTHS_PT = ["","Jan","Fev","Mar","Abr","Mai","Jun","Jul","Ago","Set","Out","Nov","Dez"];

// ── Step navigation ─────────────────────────────────────────────────────────
function _setStep(n) {
  [1,2,3,4].forEach(function(i) {
    document.getElementById('passo'+i).style.display = (i===n) ? '' : 'none';
    var pill = document.getElementById('pill'+i);
    pill.style.background = i===n ? '#0d6efd' : (i<n ? '#198754' : '#f8f9fa');
    pill.style.color = i<=n ? '#fff' : '#6c757d';
  });
}
function voltarPasso(n) { _setStep(n); }

// ── PASSO 1: Upload ─────────────────────────────────────────────────────────
async function uploadArquivo() {
  var planId = document.getElementById('selPlano').value;
  if (!planId) { alert('Selecione o plano orçamentário.'); return; }
  var fileInput = document.getElementById('fileInput');
  if (!fileInput.files.length) { alert('Selecione um arquivo.'); return; }

  _imp.plan_id = planId;
  document.getElementById('uploadStatus').textContent = 'Analisando...';

  var fd = new FormData();
  fd.append('file', fileInput.files[0]);

  try {
    var r = await fetch('/api/orcamento/importar/upload', {method:'POST', body:fd});
    var d = await r.json();
    if (!d.ok) { alert('Erro: ' + (d.error||'falha no upload')); document.getElementById('uploadStatus').textContent=''; return; }

    _imp.upload_key     = d.upload_key;
    _imp.filename       = d.filename;
    _imp.total_rows     = d.total_rows;
    _imp.total_cols     = d.total_cols;
    _imp.headers        = d.headers;
    _imp.sample         = d.sample;
    _imp.header_row_idx = d.header_row_idx;

    _renderPasso2(d);
    _setStep(2);
    document.getElementById('uploadStatus').textContent = '';
  } catch(e) {
    alert('Erro de rede: ' + e);
    document.getElementById('uploadStatus').textContent = '';
  }
}

function _renderPasso2(d) {
  document.getElementById('p2Filename').textContent = d.filename;
  document.getElementById('p2Rows').textContent = d.total_rows.toLocaleString();
  document.getElementById('p2Cols').textContent = d.total_cols;

  // Sample table
  var t = document.getElementById('sampleTable');
  var thead = '<thead><tr>' + d.headers.map(function(h,i) {
    return '<th style="white-space:nowrap;font-size:.7rem;" title="Col '+i+'">'+_esc(h.substring(0,20))+'</th>';
  }).join('') + '</tr></thead>';
  var tbody = '<tbody>' + d.sample.map(function(row) {
    return '<tr>' + row.map(function(c) {
      return '<td style="white-space:nowrap;max-width:120px;overflow:hidden;text-overflow:ellipsis;" title="'+_esc(c)+'">'+_esc(String(c).substring(0,18))+'</td>';
    }).join('') + '</tr>';
  }).join('') + '</tbody>';
  t.innerHTML = thead + tbody;

  // Column selectors
  var opts = d.headers.map(function(h,i) {
    return '<option value="'+i+'">Col '+i+': '+_esc(h.substring(0,40))+'</option>';
  }).join('');
  ['selAccCol','selDateCol','selValCol'].forEach(function(id) {
    document.getElementById(id).innerHTML = opts;
  });

  // Pre-select from saved config or smart defaults
  var cfg = d.saved_config;
  if (cfg) {
    document.getElementById('selAccCol').value  = cfg.account_col;
    document.getElementById('selDateCol').value = cfg.date_col;
    document.getElementById('selValCol').value  = cfg.value_col;
  } else {
    // Guess smart defaults by header name
    d.headers.forEach(function(h, i) {
      var hl = h.toLowerCase();
      if (/classe|conta|descri|categ/.test(hl)) document.getElementById('selAccCol').value = i;
      if (/compet|data|date|venc/.test(hl))     document.getElementById('selDateCol').value = i;
      if (/valor$|value|amount|pago/.test(hl))  document.getElementById('selValCol').value = i;
    });
  }
}

// ── PASSO 2→3: Analisar colunas ────────────────────────────────────────────
async function analisarColunas() {
  _imp.account_col = parseInt(document.getElementById('selAccCol').value);
  _imp.date_col    = parseInt(document.getElementById('selDateCol').value);
  _imp.value_col   = parseInt(document.getElementById('selValCol').value);

  document.getElementById('analisarStatus').textContent = 'Processando...';

  try {
    var r = await fetch('/api/orcamento/importar/analisar', {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify({
        upload_key:     _imp.upload_key,
        account_col:    _imp.account_col,
        date_col:       _imp.date_col,
        value_col:      _imp.value_col,
        header_row_idx: _imp.header_row_idx,
        plan_id:        _imp.plan_id,
      }),
    });
    var d = await r.json();
    if (!d.ok) { alert('Erro: '+(d.error||'falha')); document.getElementById('analisarStatus').textContent=''; return; }

    _imp.unique_accounts = d.unique_accounts;
    _imp.acc_options     = d.acc_options;
    _imp.years_seen      = d.years_seen;

    // Init mappings from analysis
    _imp.mappings = {};
    d.unique_accounts.forEach(function(ua) {
      _imp.mappings[ua.external_key] = ua.matched_id || null;
    });

    _renderPasso3(d);
    _setStep(3);
    document.getElementById('analisarStatus').textContent = '';
  } catch(e) {
    alert('Erro: ' + e);
    document.getElementById('analisarStatus').textContent = '';
  }
}

function _renderPasso3(d) {
  var auto    = d.unique_accounts.filter(function(u){ return u.match_source==='auto'; }).length;
  var saved   = d.unique_accounts.filter(function(u){ return u.match_source==='salvo'; }).length;
  var nomatch = d.unique_accounts.filter(function(u){ return !u.matched_id; }).length;
  document.getElementById('p3Stats').innerHTML =
    d.unique_accounts.length + ' contas · ' +
    (auto+saved) + ' mapeadas automaticamente · ' +
    '<strong class="text-'+(nomatch>0?'warning':'success')+'">' + nomatch + ' sem match</strong>';

  var accOpts = '<option value="">— Ignorar —</option>' +
    _imp.acc_options.map(function(a) {
      return '<option value="'+a.id+'">'+_esc(a.code+' — '+a.name)+'</option>';
    }).join('');

  var rows = d.unique_accounts.map(function(ua) {
    var badge = ua.match_source==='salvo'
      ? '<span class="badge bg-primary">salvo</span>'
      : ua.match_source==='auto'
        ? '<span class="badge bg-success">auto</span>'
        : '<span class="badge bg-warning text-dark">sem match</span>';

    var sel = '<select class="form-select form-select-sm" style="min-width:230px;" ' +
      'data-key="'+_esc(ua.external_key)+'" onchange="_mapChange(this)">' +
      accOpts + '</select>';

    return '<tr>' +
      '<td>'+_esc(ua.external_key)+' '+badge+'</td>' +
      '<td class="text-end">'+ua.count+'</td>' +
      '<td class="text-end">'+_fmt(ua.total)+'</td>' +
      '<td>'+sel+'</td>' +
      '<td><button class="btn btn-xs btn-link text-danger p-0" onclick="_ignoreMap(\''+_esc(ua.external_key)+'\',this)">ignorar</button></td>' +
      '</tr>';
  }).join('');

  document.getElementById('mapBody').innerHTML = rows;

  // Set selected values
  document.querySelectorAll('#mapBody select').forEach(function(sel) {
    var key = sel.dataset.key;
    sel.value = _imp.mappings[key] || '';
  });
}

function _mapChange(sel) {
  _imp.mappings[sel.dataset.key] = sel.value ? parseInt(sel.value) : null;
}
function _ignoreMap(key, btn) {
  _imp.mappings[key] = null;
  var sel = document.querySelector('#mapBody select[data-key="'+_esc(key)+'"]');
  if (sel) sel.value = '';
}

// ── Salvar mapeamentos ───────────────────────────────────────────────────────
async function salvarMapeamentos() {
  document.getElementById('mapStatus').textContent = 'Salvando...';
  try {
    var r = await fetch('/api/orcamento/importar/mapeamento/salvar', {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify({
        mappings:       _imp.mappings,
        account_col:    _imp.account_col,
        date_col:       _imp.date_col,
        value_col:      _imp.value_col,
        header_row_idx: _imp.header_row_idx,
      }),
    });
    var d = await r.json();
    document.getElementById('mapStatus').textContent = d.ok ? '✅ Mapeamentos salvos!' : '❌ Erro ao salvar.';
  } catch(e) {
    document.getElementById('mapStatus').textContent = 'Erro: ' + e;
  }
}

// ── PASSO 3→4: Preview ──────────────────────────────────────────────────────
function irParaConfirmacao() {
  // Build preview from _imp data
  var mapped   = 0;
  var ignored  = 0;
  var totalVal = 0;
  var byAcc    = {};  // acc_name → {months: Set, total}

  var accById = {};
  _imp.acc_options.forEach(function(a) { accById[a.id] = a; });

  _imp.unique_accounts.forEach(function(ua) {
    var aid = _imp.mappings[ua.external_key];
    if (!aid) { ignored++; return; }
    mapped++;
    totalVal += ua.total;
    var acc = accById[aid];
    var name = acc ? (acc.code + ' — ' + acc.name) : 'Conta #'+aid;
    if (!byAcc[name]) byAcc[name] = {months: new Set(), total: 0};
    ua.months.forEach(function(m) { byAcc[name].months.add(m); });
    byAcc[name].total += ua.total;
  });

  // Summary cards
  document.getElementById('p4Summary').innerHTML =
    _statCard('Contas mapeadas', mapped, 'primary') +
    _statCard('Ignoradas', ignored, 'secondary') +
    _statCard('Valor total', 'R$ '+_fmt(totalVal), 'success') +
    _statCard('Período', _imp.years_seen.join(', ') || '?', 'info');

  // Year warning
  var alertEl = document.getElementById('p4Alert');
  if (_imp.years_seen.length > 1) {
    alertEl.textContent = '⚠️ A planilha contém lançamentos de múltiplos anos (' +
      _imp.years_seen.join(', ') + '). Certifique-se de que o plano selecionado corresponde ao período desejado.';
    alertEl.style.display = '';
  } else {
    alertEl.style.display = 'none';
  }

  // Table by account
  var rows = Object.entries(byAcc).sort(function(a,b){ return b[1].total-a[1].total; }).map(function(e) {
    return '<tr><td>'+_esc(e[0])+'</td><td class="text-end">'+e[1].months.size+'</td><td class="text-end fw-semibold">'+_fmt(e[1].total)+'</td></tr>';
  }).join('');
  document.getElementById('p4Body').innerHTML = rows || '<tr><td colspan="3" class="text-muted text-center">Nenhuma conta mapeada.</td></tr>';

  _setStep(4);
}

function _statCard(label, val, color) {
  return '<div class="col-6 col-md-3"><div class="card border-'+color+' text-center p-2">'+
    '<div style="font-size:.75rem;color:#6c757d;">'+label+'</div>'+
    '<div class="fw-bold text-'+color+'" style="font-size:1rem;">'+val+'</div>'+
    '</div></div>';
}

// ── PASSO 4: Executar ────────────────────────────────────────────────────────
async function executarImport() {
  var btn = document.getElementById('btnExecutar');
  btn.disabled = true;
  document.getElementById('execStatus').textContent = 'Importando...';

  try {
    var r = await fetch('/api/orcamento/importar/executar', {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify({
        upload_key:     _imp.upload_key,
        plan_id:        _imp.plan_id,
        account_col:    _imp.account_col,
        date_col:       _imp.date_col,
        value_col:      _imp.value_col,
        header_row_idx: _imp.header_row_idx,
        mappings:       _imp.mappings,
      }),
    });
    var d = await r.json();
    if (!d.ok) {
      alert('Erro: ' + (d.error||'falha'));
      btn.disabled = false;
      document.getElementById('execStatus').textContent = '';
      return;
    }

    // Show result
    [1,2,3,4].forEach(function(i){document.getElementById('passo'+i).style.display='none';});
    var res = document.getElementById('resultado');
    res.style.display = '';
    document.getElementById('resultadoBody').innerHTML =
      '<div class="row g-2 mt-1">' +
      _statCard('Contas atualizadas', d.upserted, 'success') +
      _statCard('Linhas processadas', d.processed_rows, 'primary') +
      _statCard('Ignoradas', d.skipped_no_map + d.skipped_no_date, 'secondary') +
      _statCard('Valor importado', 'R$ '+_fmt(d.total_value), 'success') +
      '</div>';
    document.getElementById('btnVerOrc').href = '/ferramentas/orcamento/' + _imp.plan_id;

  } catch(e) {
    alert('Erro: ' + e);
    btn.disabled = false;
    document.getElementById('execStatus').textContent = '';
  }
}

// ── Utilitários ─────────────────────────────────────────────────────────────
function _esc(s) {
  return String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;');
}
function _fmt(n) {
  return Number(n||0).toLocaleString('pt-BR',{minimumFractionDigits:2,maximumFractionDigits:2});
}
</script>
{% endblock %}
"""

try:
    templates_env.loader.mapping["orc_importar.html"] = TEMPLATES["orc_importar.html"]
    print("[orc-import] ✅ Template orc_importar.html registrado")
except Exception as _e:
    print(f"[orc-import] ⚠️ Template: {_e}")

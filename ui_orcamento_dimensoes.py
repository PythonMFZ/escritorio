# ui_orcamento_dimensoes.py — Dimensões customizáveis para o Plano Orçamentário
# Exec'd no namespace do app.py (após ui_orcamento.py e ui_orcamento_import.py)
#
# MODELOS:
#   BudgetDimension       — tipo de dimensão (ex: "Centro de Custo", "Departamento")
#   BudgetDimensionValue  — valores de cada dimensão (ex: "Empresa A", "Financeiro")
#   BudgetEntryDimension  — vínculo N:N entre BudgetEntry e BudgetDimensionValue
#
# ROTAS:
#   GET  /ferramentas/orcamento/dimensoes         — gerenciar dimensões e valores
#   POST /api/orcamento/dimensoes                 — criar dimensão
#   PUT  /api/orcamento/dimensoes/{id}            — editar dimensão
#   DEL  /api/orcamento/dimensoes/{id}            — excluir dimensão
#   POST /api/orcamento/dimensoes/{id}/valores    — criar valor
#   PUT  /api/orcamento/dimensoes/valores/{id}    — editar valor
#   DEL  /api/orcamento/dimensoes/valores/{id}    — excluir valor
#   GET  /api/orcamento/dimensoes/lista           — JSON para select2 / filtros

import json as _json_dim

# ── Modelos ───────────────────────────────────────────────────────────────────

class BudgetDimension(SQLModel, table=True):
    __tablename__  = "budgetdimension"
    __table_args__ = {"extend_existing": True}
    id:          Optional[int] = Field(default=None, primary_key=True)
    company_id:  int           = Field(index=True)
    client_id:   Optional[int] = Field(default=None, index=True)
    name:        str           = Field(default="")   # ex: "Centro de Custo"
    icon:        str           = Field(default="🏷️")
    sort_order:  int           = Field(default=0)
    is_active:   bool          = Field(default=True)
    created_at:  datetime      = Field(default_factory=utcnow)


class BudgetDimensionValue(SQLModel, table=True):
    __tablename__  = "budgetdimensionvalue"
    __table_args__ = {"extend_existing": True}
    id:           Optional[int] = Field(default=None, primary_key=True)
    dimension_id: int           = Field(index=True)
    company_id:   int           = Field(index=True)
    code:         str           = Field(default="")   # código curto opcional
    name:         str           = Field(default="")   # ex: "Empresa A"
    color:        str           = Field(default="#6c757d")
    sort_order:   int           = Field(default=0)
    is_active:    bool          = Field(default=True)
    created_at:   datetime      = Field(default_factory=utcnow)


class BudgetEntryDimension(SQLModel, table=True):
    """Vincula um BudgetEntry a um ou mais valores de dimensão."""
    __tablename__  = "budgetentrydimension"
    __table_args__ = {"extend_existing": True}
    id:                    Optional[int] = Field(default=None, primary_key=True)
    entry_id:              int           = Field(index=True)
    dimension_value_id:    int           = Field(index=True)
    company_id:            int           = Field(index=True)


class BudgetImportDimMapping(SQLModel, table=True):
    """Salva o mapeamento de colunas→dimensão feito na importação para reusar."""
    __tablename__  = "budgetimportdimmapping"
    __table_args__ = {"extend_existing": True}
    id:            Optional[int] = Field(default=None, primary_key=True)
    company_id:    int           = Field(index=True)
    dimension_id:  int           = Field(index=True)
    col_index:     Optional[int] = Field(default=None)   # None = valor fixo
    fixed_value_id: Optional[int] = Field(default=None)  # dimension_value_id fixo
    updated_at:    datetime      = Field(default_factory=utcnow)


# ── Criação de tabelas ────────────────────────────────────────────────────────

def _ensure_dim_tables():
    for tbl in (BudgetDimension.__table__, BudgetDimensionValue.__table__,
                BudgetEntryDimension.__table__, BudgetImportDimMapping.__table__):
        try:
            tbl.create(engine, checkfirst=True)
        except Exception as _e:
            print(f"[dim] tabela {tbl.name}: {_e}")

try:
    _ensure_dim_tables()
except Exception as _e:
    print(f"[dim] _ensure_dim_tables: {_e}")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _dim_get_all(session, company_id: int, client_id=None) -> list:
    """Retorna dimensões ativas com seus valores."""
    dims = session.exec(
        select(BudgetDimension).where(
            BudgetDimension.company_id == company_id,
            BudgetDimension.is_active  == True,
        ).order_by(BudgetDimension.sort_order, BudgetDimension.id)
    ).all()
    result = []
    for d in dims:
        values = session.exec(
            select(BudgetDimensionValue).where(
                BudgetDimensionValue.dimension_id == d.id,
                BudgetDimensionValue.is_active    == True,
            ).order_by(BudgetDimensionValue.sort_order, BudgetDimensionValue.name)
        ).all()
        result.append({"dim": d, "vals": values})
    return result


def _dim_entry_map(session, company_id: int, plan_id: int) -> dict:
    """Retorna {entry_id: [dimension_value_id, ...]} para um plano."""
    from sqlalchemy import text as _t
    rows = session.exec(
        select(BudgetEntryDimension).where(
            BudgetEntryDimension.company_id == company_id,
        )
    ).all()
    result: dict = {}
    for r in rows:
        result.setdefault(r.entry_id, []).append(r.dimension_value_id)
    return result


# ── Template: Gerenciar Dimensões ─────────────────────────────────────────────

TEMPLATES["orc_dimensoes.html"] = r"""
{% extends "base.html" %}
{% block content %}
<style>
  .dim-card{border:1px solid var(--mc-border);border-radius:12px;background:#fff;margin-bottom:1rem;overflow:hidden;}
  .dim-hdr{display:flex;align-items:center;gap:.6rem;padding:.75rem 1rem;background:#f8f9fa;
           border-bottom:1px solid var(--mc-border);font-weight:600;}
  .dim-body{padding:.75rem 1rem;}
  .val-chip{display:inline-flex;align-items:center;gap:.35rem;padding:.25rem .65rem;border-radius:20px;
            font-size:.78rem;font-weight:500;margin:.2rem;border:1px solid rgba(0,0,0,.1);}
  .val-chip .rm{cursor:pointer;opacity:.5;font-size:.7rem;}
  .val-chip .rm:hover{opacity:1;}
  .btn-dim{padding:.3rem .75rem;font-size:.8rem;}
</style>

<div class="d-flex align-items-center gap-2 mb-4">
  <a href="/ferramentas/orcamento" class="btn btn-sm btn-outline-secondary">← Orçamento</a>
  <h5 class="mb-0">🏷️ Dimensões do Orçamento</h5>
  <button class="btn btn-primary btn-sm ms-auto" onclick="novasDimensao()">+ Nova Dimensão</button>
</div>

<div class="text-muted small mb-3">
  Dimensões são filtros customizáveis que você aplica aos lançamentos do orçamento.<br>
  Exemplos: <strong>Centro de Custo</strong> (Empresa A, Empresa B), <strong>Departamento</strong> (Financeiro, Comercial), <strong>Setor</strong> (Matriz, Filial).
</div>

{% if not dimensoes %}
<div class="text-center py-5 text-muted">
  <div style="font-size:3rem;">🏷️</div>
  <div class="fw-semibold mt-2">Nenhuma dimensão criada</div>
  <div class="small mt-1">Crie dimensões para categorizar seus lançamentos além do Plano de Contas.</div>
  <button class="btn btn-primary mt-3" onclick="novasDimensao()">+ Criar primeira dimensão</button>
</div>
{% else %}
{% for item in dimensoes %}
<div class="dim-card" id="dim-card-{{ item.dim.id }}">
  <div class="dim-hdr">
    <span>{{ item.dim.icon }}</span>
    <span id="dim-name-{{ item.dim.id }}">{{ item.dim.name }}</span>
    <span class="badge bg-secondary ms-1" style="font-size:.65rem;">{{ item.vals|length }} valores</span>
    <div class="ms-auto d-flex gap-1">
      <button class="btn btn-outline-secondary btn-dim" onclick="editarDimensao({{ item.dim.id }}, '{{ item.dim.name }}', '{{ item.dim.icon }}')">✏️ Editar</button>
      <button class="btn btn-outline-danger btn-dim" onclick="excluirDimensao({{ item.dim.id }})">🗑</button>
    </div>
  </div>
  <div class="dim-body">
    <div id="vals-{{ item.dim.id }}" class="mb-2">
      {% for v in item.vals %}
      <span class="val-chip" id="val-{{ v.id }}" style="background:{{ v.color }}22;border-color:{{ v.color }}55;color:{{ v.color }};">
        {% if v.code %}<code style="font-size:.7rem;opacity:.7;">{{ v.code }}</code>{% endif %}
        {{ v.name }}
        <span class="rm" onclick="excluirValor({{ v.id }}, {{ item.dim.id }})">✕</span>
      </span>
      {% endfor %}
      {% if not item.vals %}
      <span class="text-muted small" id="empty-{{ item.dim.id }}">Nenhum valor. Adicione abaixo.</span>
      {% endif %}
    </div>
    <div class="d-flex gap-2 align-items-center flex-wrap">
      <input type="text" class="form-control form-control-sm" style="max-width:160px;"
             id="nv-nome-{{ item.dim.id }}" placeholder="Nome (ex: Empresa A)">
      <input type="text" class="form-control form-control-sm" style="max-width:90px;"
             id="nv-code-{{ item.dim.id }}" placeholder="Código">
      <input type="color" class="form-control form-control-color form-control-sm"
             id="nv-cor-{{ item.dim.id }}" value="#0d6efd" title="Cor">
      <button class="btn btn-outline-primary btn-dim" onclick="adicionarValor({{ item.dim.id }})">+ Adicionar</button>
    </div>
  </div>
</div>
{% endfor %}
{% endif %}

<!-- Modal nova/editar dimensão -->
<div class="modal fade" id="modalDim" tabindex="-1">
  <div class="modal-dialog modal-sm">
    <div class="modal-content">
      <div class="modal-header"><h6 class="modal-title">Dimensão</h6><button class="btn-close" data-bs-dismiss="modal"></button></div>
      <div class="modal-body">
        <input type="hidden" id="mdDimId">
        <div class="mb-2">
          <label class="form-label small fw-semibold">Nome da Dimensão</label>
          <input type="text" id="mdDimNome" class="form-control" placeholder="ex: Centro de Custo">
        </div>
        <div class="mb-2">
          <label class="form-label small fw-semibold">Ícone</label>
          <div class="d-flex gap-2 flex-wrap" id="iconePicker">
            {% for ico in ["🏷️","🏢","🏭","👥","📊","🗂️","🌍","💼","🔖","🎯"] %}
            <span class="border rounded p-1" style="cursor:pointer;font-size:1.2rem;" onclick="selecionarIco('{{ ico }}')">{{ ico }}</span>
            {% endfor %}
          </div>
          <input type="text" id="mdDimIco" class="form-control form-control-sm mt-1" value="🏷️" maxlength="4">
        </div>
      </div>
      <div class="modal-footer">
        <button class="btn btn-secondary btn-sm" data-bs-dismiss="modal">Cancelar</button>
        <button class="btn btn-primary btn-sm" onclick="salvarDimensao()">Salvar</button>
      </div>
    </div>
  </div>
</div>

<script>
function novasDimensao() {
  document.getElementById('mdDimId').value = '';
  document.getElementById('mdDimNome').value = '';
  document.getElementById('mdDimIco').value = '🏷️';
  new bootstrap.Modal(document.getElementById('modalDim')).show();
}
function editarDimensao(id, nome, ico) {
  document.getElementById('mdDimId').value = id;
  document.getElementById('mdDimNome').value = nome;
  document.getElementById('mdDimIco').value = ico;
  new bootstrap.Modal(document.getElementById('modalDim')).show();
}
function selecionarIco(ico) {
  document.getElementById('mdDimIco').value = ico;
}

async function salvarDimensao() {
  const id   = document.getElementById('mdDimId').value;
  const nome = document.getElementById('mdDimNome').value.trim();
  const ico  = document.getElementById('mdDimIco').value.trim() || '🏷️';
  if (!nome) { alert('Nome obrigatório'); return; }
  const url    = id ? `/api/orcamento/dimensoes/${id}` : '/api/orcamento/dimensoes';
  const method = id ? 'PUT' : 'POST';
  const r = await fetch(url, {method, headers:{'Content-Type':'application/json'},
                               body: JSON.stringify({name: nome, icon: ico})});
  const d = await r.json();
  if (d.ok) location.reload();
  else alert(d.error || 'Erro');
}

async function excluirDimensao(id) {
  if (!confirm('Excluir esta dimensão e todos os seus valores?')) return;
  const r = await fetch(`/api/orcamento/dimensoes/${id}`, {method:'DELETE'});
  const d = await r.json();
  if (d.ok) document.getElementById(`dim-card-${id}`).remove();
  else alert(d.error || 'Erro');
}

async function adicionarValor(dimId) {
  const nome = document.getElementById(`nv-nome-${dimId}`).value.trim();
  const code = document.getElementById(`nv-code-${dimId}`).value.trim();
  const cor  = document.getElementById(`nv-cor-${dimId}`).value;
  if (!nome) { alert('Informe o nome do valor'); return; }
  const r = await fetch(`/api/orcamento/dimensoes/${dimId}/valores`, {
    method: 'POST',
    headers: {'Content-Type':'application/json'},
    body: JSON.stringify({name: nome, code, color: cor})
  });
  const d = await r.json();
  if (d.ok) {
    document.getElementById(`nv-nome-${dimId}`).value = '';
    document.getElementById(`nv-code-${dimId}`).value = '';
    const emp = document.getElementById(`empty-${dimId}`);
    if (emp) emp.remove();
    const chip = document.createElement('span');
    chip.className = 'val-chip';
    chip.id = `val-${d.id}`;
    chip.style = `background:${cor}22;border-color:${cor}55;color:${cor};`;
    chip.innerHTML = `${code ? `<code style="font-size:.7rem;opacity:.7;">${code}</code>` : ''} ${nome} <span class="rm" onclick="excluirValor(${d.id},${dimId})">✕</span>`;
    document.getElementById(`vals-${dimId}`).appendChild(chip);
  } else alert(d.error || 'Erro');
}

async function excluirValor(valId, dimId) {
  if (!confirm('Remover este valor?')) return;
  const r = await fetch(`/api/orcamento/dimensoes/valores/${valId}`, {method:'DELETE'});
  const d = await r.json();
  if (d.ok) document.getElementById(`val-${valId}`)?.remove();
  else alert(d.error || 'Erro');
}
</script>
{% endblock %}
"""


# ── Rotas CRUD ────────────────────────────────────────────────────────────────

@app.get("/ferramentas/orcamento/dimensoes", response_class=HTMLResponse)
@require_login
async def orc_dimensoes_page(request: Request, session: Session = Depends(get_session)):
    ctx = get_tenant_context(request, session)
    if not ctx or ctx.membership.role not in ("admin", "equipe", "owner"):
        return RedirectResponse("/", status_code=303)
    dimensoes = _dim_get_all(session, ctx.company.id)
    return render("orc_dimensoes.html", request=request, context={
        "current_user": ctx.user, "current_company": ctx.company,
        "role": ctx.membership.role, "dimensoes": dimensoes,
    })


@app.post("/api/orcamento/dimensoes")
@require_login
async def orc_dim_criar(request: Request, session: Session = Depends(get_session)):
    ctx = get_tenant_context(request, session)
    if not ctx or ctx.membership.role not in ("admin", "owner"):
        return JSONResponse({"ok": False}, status_code=403)
    body = await request.json()
    name = (body.get("name") or "").strip()
    if not name:
        return JSONResponse({"ok": False, "error": "Nome obrigatório"})
    # sort_order = próximo disponível
    existing = session.exec(
        select(BudgetDimension).where(BudgetDimension.company_id == ctx.company.id)
    ).all()
    sort = max((d.sort_order for d in existing), default=0) + 1
    dim = BudgetDimension(
        company_id=ctx.company.id,
        name=name,
        icon=body.get("icon", "🏷️"),
        sort_order=sort,
    )
    session.add(dim)
    session.commit()
    session.refresh(dim)
    return JSONResponse({"ok": True, "id": dim.id})


@app.put("/api/orcamento/dimensoes/{dim_id}")
@require_login
async def orc_dim_editar(dim_id: int, request: Request, session: Session = Depends(get_session)):
    ctx = get_tenant_context(request, session)
    if not ctx or ctx.membership.role not in ("admin", "owner"):
        return JSONResponse({"ok": False}, status_code=403)
    dim = session.get(BudgetDimension, dim_id)
    if not dim or dim.company_id != ctx.company.id:
        return JSONResponse({"ok": False, "error": "Não encontrada"}, status_code=404)
    body = await request.json()
    if "name" in body: dim.name = body["name"].strip()
    if "icon" in body: dim.icon = body["icon"]
    session.add(dim)
    session.commit()
    return JSONResponse({"ok": True})


@app.delete("/api/orcamento/dimensoes/{dim_id}")
@require_login
async def orc_dim_excluir(dim_id: int, request: Request, session: Session = Depends(get_session)):
    ctx = get_tenant_context(request, session)
    if not ctx or ctx.membership.role not in ("admin", "owner"):
        return JSONResponse({"ok": False}, status_code=403)
    dim = session.get(BudgetDimension, dim_id)
    if not dim or dim.company_id != ctx.company.id:
        return JSONResponse({"ok": False}, status_code=404)
    # Apaga valores + vínculos
    values = session.exec(
        select(BudgetDimensionValue).where(BudgetDimensionValue.dimension_id == dim_id)
    ).all()
    for v in values:
        links = session.exec(
            select(BudgetEntryDimension).where(BudgetEntryDimension.dimension_value_id == v.id)
        ).all()
        for lk in links:
            session.delete(lk)
        session.delete(v)
    session.delete(dim)
    session.commit()
    return JSONResponse({"ok": True})


@app.post("/api/orcamento/dimensoes/{dim_id}/valores")
@require_login
async def orc_dim_valor_criar(dim_id: int, request: Request, session: Session = Depends(get_session)):
    ctx = get_tenant_context(request, session)
    if not ctx or ctx.membership.role not in ("admin", "owner", "equipe"):
        return JSONResponse({"ok": False}, status_code=403)
    dim = session.get(BudgetDimension, dim_id)
    if not dim or dim.company_id != ctx.company.id:
        return JSONResponse({"ok": False}, status_code=404)
    body = await request.json()
    name = (body.get("name") or "").strip()
    if not name:
        return JSONResponse({"ok": False, "error": "Nome obrigatório"})
    existing = session.exec(
        select(BudgetDimensionValue).where(BudgetDimensionValue.dimension_id == dim_id)
    ).all()
    sort = max((v.sort_order for v in existing), default=0) + 1
    val = BudgetDimensionValue(
        dimension_id=dim_id,
        company_id=ctx.company.id,
        name=name,
        code=body.get("code", "").strip(),
        color=body.get("color", "#6c757d"),
        sort_order=sort,
    )
    session.add(val)
    session.commit()
    session.refresh(val)
    return JSONResponse({"ok": True, "id": val.id})


@app.delete("/api/orcamento/dimensoes/valores/{val_id}")
@require_login
async def orc_dim_valor_excluir(val_id: int, request: Request, session: Session = Depends(get_session)):
    ctx = get_tenant_context(request, session)
    if not ctx or ctx.membership.role not in ("admin", "owner", "equipe"):
        return JSONResponse({"ok": False}, status_code=403)
    val = session.get(BudgetDimensionValue, val_id)
    if not val or val.company_id != ctx.company.id:
        return JSONResponse({"ok": False}, status_code=404)
    links = session.exec(
        select(BudgetEntryDimension).where(BudgetEntryDimension.dimension_value_id == val_id)
    ).all()
    for lk in links:
        session.delete(lk)
    session.delete(val)
    session.commit()
    return JSONResponse({"ok": True})


@app.get("/api/orcamento/dimensoes/lista")
@require_login
async def orc_dim_lista(request: Request, session: Session = Depends(get_session)):
    """JSON com todas as dimensões + valores — para filtros e importação."""
    ctx = get_tenant_context(request, session)
    if not ctx:
        return JSONResponse({"ok": False}, status_code=401)
    dims = _dim_get_all(session, ctx.company.id)
    return JSONResponse({"ok": True, "dimensoes": [
        {
            "id": item["dim"].id,
            "name": item["dim"].name,
            "icon": item["dim"].icon,
            "values": [
                {"id": v.id, "name": v.name, "code": v.code, "color": v.color}
                for v in item["vals"]
            ],
        }
        for item in dims
    ]})


# ── Rota: salvar mapeamento dimensão→coluna da importação ────────────────────

@app.post("/api/orcamento/importar/dimensoes/salvar")
@require_login
async def orc_dim_import_salvar(request: Request, session: Session = Depends(get_session)):
    """Salva quais colunas do Excel mapeiam para quais dimensões."""
    ctx = get_tenant_context(request, session)
    if not ctx or ctx.membership.role not in ("admin", "owner", "equipe"):
        return JSONResponse({"ok": False}, status_code=403)
    body = await request.json()
    # body = [{dim_id, col_index (ou null), fixed_value_id (ou null)}]
    mappings = body.get("mappings", [])
    # Apaga mapeamentos antigos
    old = session.exec(
        select(BudgetImportDimMapping).where(BudgetImportDimMapping.company_id == ctx.company.id)
    ).all()
    for o in old:
        session.delete(o)
    for m in mappings:
        dim_id = int(m.get("dim_id") or 0)
        if not dim_id:
            continue
        session.add(BudgetImportDimMapping(
            company_id=ctx.company.id,
            dimension_id=dim_id,
            col_index=int(m["col_index"]) if m.get("col_index") is not None else None,
            fixed_value_id=int(m["fixed_value_id"]) if m.get("fixed_value_id") else None,
        ))
    session.commit()
    return JSONResponse({"ok": True})


@app.get("/api/orcamento/importar/dimensoes/config")
@require_login
async def orc_dim_import_config(request: Request, session: Session = Depends(get_session)):
    """Retorna mapeamentos salvos para pré-preencher a UI de importação."""
    ctx = get_tenant_context(request, session)
    if not ctx:
        return JSONResponse({"ok": False}, status_code=401)
    maps = session.exec(
        select(BudgetImportDimMapping).where(BudgetImportDimMapping.company_id == ctx.company.id)
    ).all()
    return JSONResponse({"ok": True, "mappings": [
        {"dim_id": m.dimension_id, "col_index": m.col_index, "fixed_value_id": m.fixed_value_id}
        for m in maps
    ]})


# ── Rota: aplicar dimensões durante execução da importação ───────────────────

@app.post("/api/orcamento/importar/executar-com-dimensoes")
@require_login
async def orc_import_executar_com_dimensoes(request: Request, session: Session = Depends(get_session)):
    """
    Versão estendida do /executar que também vincula dimensões a cada BudgetEntry.
    Body extra:
      dim_mappings: [{dim_id, col_index (ou null), fixed_value_id (ou null), col_values: {val_str: dim_value_id}}]
    """
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
    mappings       = body.get("mappings", {})
    dim_mappings   = body.get("dim_mappings", [])  # [{dim_id, col_index, fixed_value_id, col_values}]

    cached = _uimp_cache_get(session, upload_key, ctx.company.id)
    if not cached:
        return JSONResponse({"ok": False, "error": "Upload expirado. Faça o upload novamente."})

    plan = session.get(BudgetPlan, plan_id)
    if not plan or plan.company_id != ctx.company.id:
        return JSONResponse({"ok": False, "error": "Plano não encontrado."})

    rows      = cached["rows"]
    data_rows = [r for r in rows[header_row_idx + 1:] if any(c is not None for c in r)]

    db_maps = {
        m.external_key: m.budget_account_id
        for m in session.exec(
            select(BudgetAccountMapping).where(BudgetAccountMapping.company_id == ctx.company.id)
        ).all()
    }

    # Agrega por (account_id, month) → {sum, rows_info para dimensões}
    aggregated: dict = {}   # (acc_id, month) → {"total": float, "rows": [row]}
    skipped_no_map   = 0
    skipped_no_date  = 0

    for row in data_rows:
        if not any(c is not None for c in row):
            continue
        try:
            ext_key = str(row[account_col] if account_col < len(row) else "").strip()
            if not ext_key or ext_key.lower() == "none":
                continue
            acc_id = mappings.get(ext_key) or db_maps.get(ext_key)
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
            if key not in aggregated:
                aggregated[key] = {"total": 0.0, "rows": []}
            aggregated[key]["total"] += val
            aggregated[key]["rows"].append(row)
        except Exception:
            pass

    upserted = 0
    dim_links = 0
    for (acc_id, month), info in aggregated.items():
        existing = session.exec(
            select(BudgetEntry).where(
                BudgetEntry.plan_id    == plan_id,
                BudgetEntry.account_id == acc_id,
                BudgetEntry.month      == month,
            )
        ).first()
        if existing:
            existing.value_realized = round(info["total"], 2)
            existing.updated_at     = utcnow()
            session.add(existing)
            entry = existing
        else:
            entry = BudgetEntry(
                company_id     = ctx.company.id,
                plan_id        = plan_id,
                account_id     = acc_id,
                month          = month,
                value_budgeted = 0.0,
                value_realized = round(info["total"], 2),
            )
            session.add(entry)
            session.flush()  # gera entry.id
        upserted += 1

        # Dimensões: apaga vínculos antigos deste entry e recria
        if dim_mappings and entry.id:
            old_links = session.exec(
                select(BudgetEntryDimension).where(BudgetEntryDimension.entry_id == entry.id)
            ).all()
            for lk in old_links:
                session.delete(lk)

            # Determina valor de dimensão por linha — usa a primeira linha do grupo
            first_row = info["rows"][0] if info["rows"] else []
            for dm in dim_mappings:
                dim_id = int(dm.get("dim_id") or 0)
                if not dim_id:
                    continue
                dv_id = None
                if dm.get("fixed_value_id"):
                    dv_id = int(dm["fixed_value_id"])
                elif dm.get("col_index") is not None:
                    col_idx = int(dm["col_index"])
                    cell_val = str(first_row[col_idx] if col_idx < len(first_row) else "").strip()
                    col_values = dm.get("col_values", {})
                    dv_id = col_values.get(cell_val) or col_values.get(cell_val.lower())
                    if dv_id:
                        dv_id = int(dv_id)
                if dv_id:
                    session.add(BudgetEntryDimension(
                        entry_id=entry.id,
                        dimension_value_id=dv_id,
                        company_id=ctx.company.id,
                    ))
                    dim_links += 1

    session.commit()

    entry_cache = session.exec(
        select(BudgetUploadCache).where(BudgetUploadCache.upload_key == upload_key)
    ).first()
    if entry_cache:
        session.delete(entry_cache)
        session.commit()

    return JSONResponse({
        "ok": True,
        "upserted":       upserted,
        "skipped_no_map": skipped_no_map,
        "skipped_no_date": skipped_no_date,
        "dim_links":      dim_links,
        "total_value":    round(sum(i["total"] for i in aggregated.values()), 2),
    })

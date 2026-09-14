# ui_negocios_venda.py — Gerenciamento de negócios à venda + API pública
# Exec'd no namespace do app.py

import json as _json_nv
from datetime import datetime as _dt_nv
from typing import Optional as _Opt_nv, List as _List_nv
from fastapi import Request as _Req_nv, Form as _Form_nv
from fastapi.responses import JSONResponse as _JR_nv, RedirectResponse as _RR_nv, Response as _Resp_nv
from sqlmodel import SQLModel as _SM_nv, Field as _Field_nv, Session as _Sess_nv, select as _sel_nv

# ── Modelo ─────────────────────────────────────────────────────────────────────

class NegocioVenda(_SM_nv, table=True):
    __table_args__ = {"extend_existing": True}
    id:          _Opt_nv[int] = _Field_nv(default=None, primary_key=True)
    nome:        str          = _Field_nv(default="")
    setor:       str          = _Field_nv(default="")
    descricao:   str          = _Field_nv(default="")
    faturamento: float        = _Field_nv(default=0.0)   # R$ anual
    ebitda:      float        = _Field_nv(default=0.0)   # R$ anual
    localizacao: str          = _Field_nv(default="")
    whatsapp:    str          = _Field_nv(default="5547991359091")
    status:      str          = _Field_nv(default="disponivel")  # disponivel | reservado | vendido
    ordem:       int          = _Field_nv(default=0)
    criado_em:   str          = _Field_nv(default="")


def _nv_ensure_tables():
    with _Sess_nv(engine) as _s:
        _SM_nv.metadata.create_all(engine, tables=[NegocioVenda.__table__])
        try:
            _s.exec(_sel_nv(NegocioVenda).limit(1))
        except Exception:
            pass

_nv_ensure_tables()


# ── Helpers ────────────────────────────────────────────────────────────────────

def _nv_fmt_brl(v: float) -> str:
    try:
        return f"R$ {v:,.0f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except Exception:
        return str(v)


STATUS_LABELS = {
    "disponivel": ("Disponível", "success"),
    "reservado":  ("Reservado",  "warning"),
    "vendido":    ("Vendido",    "secondary"),
}

SETORES = [
    "Agronegócio", "Alimentação", "Comércio / Varejo", "Construção Civil",
    "Educação", "Indústria", "Logística", "Saúde", "Serviços", "Tecnologia", "Outro",
]


# ── Template ───────────────────────────────────────────────────────────────────

_NV_TEMPLATE = r"""
{% extends "base.html" %}
{% block content %}
<div class="container-fluid py-4">

  <div class="d-flex justify-content-between align-items-center mb-4">
    <h2 class="mb-0">🏢 Negócios à Venda</h2>
    <button class="btn btn-primary" data-bs-toggle="modal" data-bs-target="#modalNegocio"
            onclick="openNew()">+ Novo Negócio</button>
  </div>

  {% if negocios %}
  <div class="table-responsive">
    <table class="table table-hover align-middle">
      <thead class="table-light">
        <tr>
          <th>#</th>
          <th>Nome</th>
          <th>Setor</th>
          <th>Faturamento</th>
          <th>EBITDA</th>
          <th>Localização</th>
          <th>Status</th>
          <th>Ações</th>
        </tr>
      </thead>
      <tbody>
        {% for n in negocios %}
        {% if n.status == "disponivel" %}{% set _sc = "success" %}{% elif n.status == "reservado" %}{% set _sc = "warning" %}{% else %}{% set _sc = "secondary" %}{% endif %}
        {% if n.status == "disponivel" %}{% set _sl = "Disponível" %}{% elif n.status == "reservado" %}{% set _sl = "Reservado" %}{% else %}{% set _sl = "Vendido" %}{% endif %}
        <tr>
          <td class="text-muted small">{{ n.id }}</td>
          <td><strong>{{ n.nome }}</strong></td>
          <td><span class="badge bg-light text-dark border">{{ n.setor }}</span></td>
          <td>{{ n.faturamento | int }}</td>
          <td>{{ n.ebitda | int }}</td>
          <td>{{ n.localizacao }}</td>
          <td><span class="badge bg-{{ _sc }}">{{ _sl }}</span></td>
          <td>
            <button class="btn btn-sm btn-outline-primary me-1" onclick="openEdit(this)"
                    data-id="{{ n.id }}"
                    data-nome="{{ n.nome | e }}"
                    data-setor="{{ n.setor | e }}"
                    data-desc="{{ n.descricao | e }}"
                    data-fat="{{ n.faturamento }}"
                    data-ebt="{{ n.ebitda }}"
                    data-loc="{{ n.localizacao | e }}"
                    data-wpp="{{ n.whatsapp | e }}"
                    data-status="{{ n.status }}"
                    data-ordem="{{ n.ordem }}">✏ Editar</button>
            <form method="post" action="/admin/negocios-venda/{{ n.id }}/excluir" class="d-inline"
                  onsubmit="return confirm('Excluir este negócio?')">
              <button class="btn btn-sm btn-outline-danger">🗑</button>
            </form>
          </td>
        </tr>
        {% endfor %}
      </tbody>
    </table>
  </div>
  {% else %}
  <div class="alert alert-info">Nenhum negócio cadastrado ainda. Clique em "+ Novo Negócio" para começar.</div>
  {% endif %}

  <div class="mt-3">
    <a href="https://maffezzollicapital.com.br/empresas-a-venda.html" target="_blank"
       class="btn btn-outline-secondary btn-sm">🔗 Ver página do site</a>
  </div>
</div>

<!-- Modal ----------------------------------------------------------------- -->
<div class="modal fade" id="modalNegocio" tabindex="-1">
  <div class="modal-dialog modal-lg">
    <form id="frmNegocio" method="post">
      <div class="modal-content">
        <div class="modal-header">
          <h5 class="modal-title" id="modalTitle">Novo Negócio</h5>
          <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
        </div>
        <div class="modal-body row g-3">

          <div class="col-md-8">
            <label class="form-label">Nome da empresa *</label>
            <input type="text" name="nome" id="iNome" class="form-control" required>
          </div>
          <div class="col-md-4">
            <label class="form-label">Setor *</label>
            <select name="setor" id="iSetor" class="form-select" required>
              <option value="">Selecione…</option>
              {% for s in setores %}
              <option value="{{ s }}">{{ s }}</option>
              {% endfor %}
            </select>
          </div>

          <div class="col-12">
            <label class="form-label">Descrição (aparece no card do site)</label>
            <textarea name="descricao" id="iDesc" class="form-control" rows="3"></textarea>
          </div>

          <div class="col-md-4">
            <label class="form-label">Faturamento Anual (R$) *</label>
            <input type="number" name="faturamento" id="iFat" class="form-control" min="0" step="1000" required>
          </div>
          <div class="col-md-4">
            <label class="form-label">EBITDA Anual (R$) *</label>
            <input type="number" name="ebitda" id="iEbt" class="form-control" min="0" step="1000" required>
          </div>
          <div class="col-md-4">
            <label class="form-label">Localização *</label>
            <input type="text" name="localizacao" id="iLoc" class="form-control" required placeholder="Joinville, SC">
          </div>

          <div class="col-md-6">
            <label class="form-label">WhatsApp (com DDI, sem +)</label>
            <input type="text" name="whatsapp" id="iWpp" class="form-control" placeholder="5547991359091">
          </div>
          <div class="col-md-3">
            <label class="form-label">Status</label>
            <select name="status" id="iStatus" class="form-select">
              <option value="disponivel">Disponível</option>
              <option value="reservado">Reservado</option>
              <option value="vendido">Vendido</option>
            </select>
          </div>
          <div class="col-md-3">
            <label class="form-label">Ordem de exibição</label>
            <input type="number" name="ordem" id="iOrdem" class="form-control" value="0" min="0">
          </div>

        </div>
        <div class="modal-footer">
          <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Cancelar</button>
          <button type="submit" class="btn btn-primary">Salvar</button>
        </div>
      </div>
    </form>
  </div>
</div>

<script>
function openNew() {
  document.getElementById('modalTitle').textContent = 'Novo Negócio';
  document.getElementById('frmNegocio').action = '/admin/negocios-venda/novo';
  document.getElementById('iNome').value = '';
  document.getElementById('iSetor').value = '';
  document.getElementById('iDesc').value = '';
  document.getElementById('iFat').value = '';
  document.getElementById('iEbt').value = '';
  document.getElementById('iLoc').value = '';
  document.getElementById('iWpp').value = '5547991359091';
  document.getElementById('iStatus').value = 'disponivel';
  document.getElementById('iOrdem').value = '0';
}

function openEdit(btn) {
  var d = btn.dataset;
  document.getElementById('modalTitle').textContent = 'Editar Negócio';
  document.getElementById('frmNegocio').action = '/admin/negocios-venda/' + d.id + '/editar';
  document.getElementById('iNome').value = d.nome;
  document.getElementById('iSetor').value = d.setor;
  document.getElementById('iDesc').value = d.desc;
  document.getElementById('iFat').value = d.fat;
  document.getElementById('iEbt').value = d.ebt;
  document.getElementById('iLoc').value = d.loc;
  document.getElementById('iWpp').value = d.wpp;
  document.getElementById('iStatus').value = d.status;
  document.getElementById('iOrdem').value = d.ordem;
  new bootstrap.Modal(document.getElementById('modalNegocio')).show();
}
</script>
{% endblock %}
"""

TEMPLATES["admin_negocios_venda"] = _NV_TEMPLATE
templates_env.loader.mapping["admin_negocios_venda"] = _NV_TEMPLATE


# ── Rotas Admin ────────────────────────────────────────────────────────────────

@app.get("/admin/negocios-venda")
async def admin_negocios_lista(request: _Req_nv):
    with _Sess_nv(engine) as s:
        negocios = s.exec(_sel_nv(NegocioVenda).order_by(NegocioVenda.ordem, NegocioVenda.id)).all()
    return templates_env.TemplateResponse("admin_negocios_venda", {
        "request": request, "negocios": negocios, "setores": SETORES,
    })


@app.post("/admin/negocios-venda/novo")
async def admin_negocios_novo(
    request: _Req_nv,
    nome:        str   = _Form_nv(""),
    setor:       str   = _Form_nv(""),
    descricao:   str   = _Form_nv(""),
    faturamento: float = _Form_nv(0),
    ebitda:      float = _Form_nv(0),
    localizacao: str   = _Form_nv(""),
    whatsapp:    str   = _Form_nv("5547991359091"),
    status:      str   = _Form_nv("disponivel"),
    ordem:       int   = _Form_nv(0),
):
    with _Sess_nv(engine) as s:
        n = NegocioVenda(
            nome=nome.strip(), setor=setor.strip(), descricao=descricao.strip(),
            faturamento=faturamento, ebitda=ebitda, localizacao=localizacao.strip(),
            whatsapp=whatsapp.strip(), status=status, ordem=ordem,
            criado_em=_dt_nv.utcnow().strftime("%Y-%m-%d"),
        )
        s.add(n)
        s.commit()
    return _RR_nv("/admin/negocios-venda", status_code=303)


@app.post("/admin/negocios-venda/{nv_id}/editar")
async def admin_negocios_editar(
    nv_id: int,
    request: _Req_nv,
    nome:        str   = _Form_nv(""),
    setor:       str   = _Form_nv(""),
    descricao:   str   = _Form_nv(""),
    faturamento: float = _Form_nv(0),
    ebitda:      float = _Form_nv(0),
    localizacao: str   = _Form_nv(""),
    whatsapp:    str   = _Form_nv("5547991359091"),
    status:      str   = _Form_nv("disponivel"),
    ordem:       int   = _Form_nv(0),
):
    with _Sess_nv(engine) as s:
        n = s.get(NegocioVenda, nv_id)
        if n:
            n.nome = nome.strip(); n.setor = setor.strip()
            n.descricao = descricao.strip(); n.faturamento = faturamento
            n.ebitda = ebitda; n.localizacao = localizacao.strip()
            n.whatsapp = whatsapp.strip(); n.status = status; n.ordem = ordem
            s.add(n); s.commit()
    return _RR_nv("/admin/negocios-venda", status_code=303)


@app.post("/admin/negocios-venda/{nv_id}/excluir")
async def admin_negocios_excluir(nv_id: int, request: _Req_nv):
    with _Sess_nv(engine) as s:
        n = s.get(NegocioVenda, nv_id)
        if n:
            s.delete(n); s.commit()
    return _RR_nv("/admin/negocios-venda", status_code=303)


# ── API Pública com CORS ───────────────────────────────────────────────────────

def _nv_cors(resp):
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Methods"] = "GET, OPTIONS"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
    return resp


@app.options("/api/negocios")
async def api_negocios_options(request: _Req_nv):
    return _nv_cors(_Resp_nv(status_code=200))


@app.get("/api/negocios")
async def api_negocios(request: _Req_nv):
    with _Sess_nv(engine) as s:
        negocios = s.exec(
            _sel_nv(NegocioVenda)
            .where(NegocioVenda.status != "vendido")
            .order_by(NegocioVenda.ordem, NegocioVenda.id)
        ).all()
    data = [
        {
            "id":          n.id,
            "nome":        n.nome,
            "setor":       n.setor,
            "descricao":   n.descricao,
            "faturamento": n.faturamento,
            "ebitda":      n.ebitda,
            "localizacao": n.localizacao,
            "whatsapp":    n.whatsapp,
            "status":      n.status,
        }
        for n in negocios
    ]
    return _nv_cors(_JR_nv(data))


print("[negocios_venda] ✅ Rotas de negócios à venda registradas.")

# ui_fluxo_caixa.py — Ferramenta de Fluxo de Caixa
# Exec'd no namespace do app.py — acessa engine, modelos e helpers globais.
#
# ROTAS:
#   GET/POST /ferramentas/fluxo-caixa              — dashboard principal
#   GET      /ferramentas/fluxo-caixa/lancamentos  — lista lançamentos
#   GET/POST /ferramentas/fluxo-caixa/novo         — novo lançamento manual
#   GET/POST /ferramentas/fluxo-caixa/{id}/editar  — editar lançamento
#   POST     /ferramentas/fluxo-caixa/{id}/realizar— marcar como realizado
#   POST     /ferramentas/fluxo-caixa/{id}/excluir — soft delete (cancelado)
#   GET/POST /ferramentas/fluxo-caixa/config       — configurações
#   GET      /ferramentas/fluxo-caixa/importar     — página de importação Excel
#   POST     /api/fluxo-caixa/upload               — preview da importação
#   POST     /api/fluxo-caixa/importar-confirmar   — confirma importação

import json      as _json_fc
import re        as _re_fc
import uuid      as _uuid_fc
import io        as _io_fc
from datetime   import date as _date_fc, timedelta as _td_fc
from typing     import Optional as _Opt_fc, List as _List_fc
from sqlalchemy import text as _t_fc

# ── Modelos ───────────────────────────────────────────────────────────────────

class CashFlowConfig(SQLModel, table=True):
    __tablename__  = "cashflowconfig"
    __table_args__ = {"extend_existing": True}
    id:                   Optional[int]      = Field(default=None, primary_key=True)
    company_id:           int                = Field(index=True)
    client_id:            Optional[int]      = Field(default=None, index=True)
    saldo_inicial_cents:  int                = Field(default=0)
    limite_cc_cents:      int                = Field(default=0)
    limite_alerta_cents:  int                = Field(default=0)
    updated_at:           datetime           = Field(default_factory=utcnow)


class CashFlowEntry(SQLModel, table=True):
    __tablename__  = "cashflowentry"
    __table_args__ = {"extend_existing": True}
    id:              Optional[int]      = Field(default=None, primary_key=True)
    company_id:      int                = Field(index=True)
    client_id:       Optional[int]      = Field(default=None, index=True)
    data_vencimento: str                = Field(default="")   # ISO date str YYYY-MM-DD
    data_pagamento:  Optional[str]      = Field(default=None) # ISO date str quando realizado
    descricao:       str                = Field(default="")
    centro_custo:    str                = Field(default="Geral")
    categoria:       str                = Field(default="Outros")
    tipo:            str                = Field(default="saida")   # "entrada" | "saida"
    valor_cents:     int                = Field(default=0)         # sempre positivo
    status:          str                = Field(default="previsto")# "previsto"|"realizado"|"cancelado"
    observacao:      str                = Field(default="")
    import_batch:    Optional[str]      = Field(default=None)
    created_at:      datetime           = Field(default_factory=utcnow)
    updated_at:      datetime           = Field(default_factory=utcnow)


# ── Criação de tabelas e migrações ────────────────────────────────────────────

def _ensure_fc_tables():
    for tbl in (CashFlowConfig.__table__, CashFlowEntry.__table__):
        try:
            tbl.create(engine, checkfirst=True)
        except Exception:
            pass
    _is_pg = DATABASE_URL.startswith("postgres")
    _migrations = [
        ("cashflowconfig", "limite_cc_cents",     "INTEGER DEFAULT 0"),
        ("cashflowconfig", "limite_alerta_cents",  "INTEGER DEFAULT 0"),
        ("cashflowentry",  "import_batch",          "VARCHAR DEFAULT NULL"),
        ("cashflowentry",  "observacao",            "VARCHAR DEFAULT ''"),
        ("cashflowentry",  "centro_custo",          "VARCHAR DEFAULT 'Geral'"),
        ("cashflowentry",  "categoria",             "VARCHAR DEFAULT 'Outros'"),
        ("cashflowentry",  "data_pagamento",        "VARCHAR DEFAULT NULL"),
    ]
    for _tbl, _col, _ddl in _migrations:
        try:
            with engine.begin() as _c:
                if _is_pg:
                    _c.execute(_t_fc(f"ALTER TABLE {_tbl} ADD COLUMN IF NOT EXISTS {_col} {_ddl}"))
                else:
                    _c.exec_driver_sql(f"ALTER TABLE {_tbl} ADD COLUMN {_col} {_ddl}")
        except Exception as _e:
            if "duplicate" not in str(_e).lower() and "already exists" not in str(_e).lower():
                print(f"[fluxo_caixa] migração {_tbl}.{_col}: {_e}")

try:
    _ensure_fc_tables()
except Exception as _e_fc_tbl:
    print(f"[fluxo_caixa] _ensure_fc_tables: {_e_fc_tbl}")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _cents_to_brl(cents: int) -> str:
    """Converte centavos para string R$ x.xxx,xx"""
    neg = cents < 0
    v = abs(cents) / 100
    s = f"R$ {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"-{s}" if neg else s


def _brl_to_cents(s: str) -> int:
    """Converte string monetária para centavos."""
    s = str(s).strip()
    s = _re_fc.sub(r"[R$\s]", "", s)
    # remove pontos de milhar, troca vírgula decimal por ponto
    s = s.replace(".", "").replace(",", ".")
    try:
        return int(round(float(s) * 100))
    except Exception:
        return 0


def _fc_get_config(session, company_id: int, client_id: _Opt_fc[int]) -> CashFlowConfig:
    cfg = session.exec(
        select(CashFlowConfig).where(
            CashFlowConfig.company_id == company_id,
            CashFlowConfig.client_id == client_id,
        )
    ).first()
    if not cfg:
        cfg = CashFlowConfig(company_id=company_id, client_id=client_id)
        session.add(cfg)
        session.commit()
        session.refresh(cfg)
    return cfg


def _fc_get_entries(session, company_id: int, client_id: _Opt_fc[int],
                    data_inicio: _Opt_fc[str] = None, data_fim: _Opt_fc[str] = None,
                    centros: _Opt_fc[_List_fc[str]] = None) -> list:
    q = select(CashFlowEntry).where(
        CashFlowEntry.company_id == company_id,
        CashFlowEntry.client_id == client_id,
        CashFlowEntry.status != "cancelado",
    )
    if data_inicio:
        q = q.where(CashFlowEntry.data_vencimento >= data_inicio)
    if data_fim:
        q = q.where(CashFlowEntry.data_vencimento <= data_fim)
    if centros:
        q = q.where(CashFlowEntry.centro_custo.in_(centros))
    return list(session.exec(q.order_by(CashFlowEntry.data_vencimento)).all())


def _fc_periodo_key(data_str: str, group_by: str) -> str:
    """Retorna chave de período para agrupamento."""
    try:
        d = _date_fc.fromisoformat(data_str)
    except Exception:
        return data_str
    if group_by == "dia":
        return d.isoformat()
    elif group_by == "semana":
        # Segunda-feira da semana
        return (d - _td_fc(days=d.weekday())).isoformat()
    else:  # mês
        return f"{d.year}-{d.month:02d}"


def _fc_periodo_label(key: str, group_by: str) -> str:
    """Formata label do período para exibição."""
    try:
        if group_by == "dia":
            d = _date_fc.fromisoformat(key)
            return d.strftime("%d/%m/%Y")
        elif group_by == "semana":
            d = _date_fc.fromisoformat(key)
            fim = d + _td_fc(days=6)
            return f"{d.strftime('%d/%m')} – {fim.strftime('%d/%m/%Y')}"
        else:  # mês
            partes = key.split("-")
            meses = ["Jan","Fev","Mar","Abr","Mai","Jun","Jul","Ago","Set","Out","Nov","Dez"]
            return f"{meses[int(partes[1])-1]}/{partes[0]}"
    except Exception:
        return key


def _calc_fluxo(entries: list, config: CashFlowConfig, group_by: str = "semana") -> list:
    """
    Agrupa lançamentos por período e calcula saldos acumulados.
    Retorna lista de dicts com dados de cada período.
    """
    from collections import OrderedDict
    periodos: dict = OrderedDict()

    for e in entries:
        key = _fc_periodo_key(e.data_vencimento, group_by)
        if key not in periodos:
            periodos[key] = {
                "key": key,
                "label": _fc_periodo_label(key, group_by),
                "entradas_previstas": 0,
                "saidas_previstas":   0,
                "entradas_realizadas":0,
                "saidas_realizadas":  0,
            }
        p = periodos[key]
        if e.status == "realizado":
            if e.tipo == "entrada":
                p["entradas_realizadas"] += e.valor_cents
                p["entradas_previstas"]  += e.valor_cents
            else:
                p["saidas_realizadas"]   += e.valor_cents
                p["saidas_previstas"]    += e.valor_cents
        else:  # previsto
            if e.tipo == "entrada":
                p["entradas_previstas"]  += e.valor_cents
            else:
                p["saidas_previstas"]    += e.valor_cents

    saldo_inicial = config.saldo_inicial_cents if config else 0
    limite_alerta = config.limite_alerta_cents if config else 0
    acum_previsto  = saldo_inicial
    acum_realizado = saldo_inicial

    resultado = []
    for key in sorted(periodos.keys()):
        p = periodos[key]
        acum_previsto  += p["entradas_previstas"]  - p["saidas_previstas"]
        acum_realizado += p["entradas_realizadas"] - p["saidas_realizadas"]
        p["saldo_previsto"]           = p["entradas_previstas"]  - p["saidas_previstas"]
        p["saldo_realizado"]          = p["entradas_realizadas"] - p["saidas_realizadas"]
        p["saldo_acumulado_previsto"]  = acum_previsto
        p["saldo_acumulado_realizado"] = acum_realizado
        p["critico"] = acum_previsto < limite_alerta
        resultado.append(p)

    return resultado


def _build_fc_context(session, company_id: int, client_id: _Opt_fc[int]) -> dict:
    """Resumo do fluxo de caixa para contexto do Augur (próximos 30 dias)."""
    hoje = _date_fc.today()
    fim  = hoje + _td_fc(days=30)
    cfg  = _fc_get_config(session, company_id, client_id)
    entries = _fc_get_entries(session, company_id, client_id,
                              data_inicio=hoje.isoformat(), data_fim=fim.isoformat())
    periodos = _calc_fluxo(entries, cfg, group_by="semana")
    total_entrada_prev = sum(e.valor_cents for e in entries if e.tipo=="entrada" and e.status=="previsto")
    total_saida_prev   = sum(e.valor_cents for e in entries if e.tipo=="saida"   and e.status=="previsto")
    total_entrada_real = sum(e.valor_cents for e in entries if e.tipo=="entrada" and e.status=="realizado")
    total_saida_real   = sum(e.valor_cents for e in entries if e.tipo=="saida"   and e.status=="realizado")
    alertas = [p["label"] for p in periodos if p["critico"]]
    return {
        "saldo_inicial_brl":       _cents_to_brl(cfg.saldo_inicial_cents),
        "limite_alerta_brl":       _cents_to_brl(cfg.limite_alerta_cents),
        "entradas_previstas_brl":  _cents_to_brl(total_entrada_prev),
        "saidas_previstas_brl":    _cents_to_brl(total_saida_prev),
        "entradas_realizadas_brl": _cents_to_brl(total_entrada_real),
        "saidas_realizadas_brl":   _cents_to_brl(total_saida_real),
        "saldo_projetado_brl":     _cents_to_brl(cfg.saldo_inicial_cents + total_entrada_prev - total_saida_prev),
        "periodos_criticos":       alertas,
        "total_lancamentos":       len(entries),
    }


# ── Templates ─────────────────────────────────────────────────────────────────

TEMPLATES["fluxo_caixa_dashboard.html"] = r"""
{% extends "base.html" %}
{% block content %}
<div class="container-fluid px-4 py-3">
  <div class="d-flex align-items-center justify-content-between mb-3">
    <h4 class="mb-0">💰 Fluxo de Caixa</h4>
    <div class="d-flex gap-2">
      <a href="/ferramentas/fluxo-caixa/novo" class="btn btn-primary btn-sm">+ Lançamento</a>
      <a href="/ferramentas/fluxo-caixa/importar" class="btn btn-outline-secondary btn-sm">Importar Excel</a>
      <a href="/ferramentas/fluxo-caixa/config" class="btn btn-outline-secondary btn-sm">⚙ Configurar</a>
    </div>
  </div>

  {# Cards de resumo #}
  <div class="row g-3 mb-4">
    <div class="col-6 col-md-3">
      <div class="card p-4 mb-0">
        <div class="text-muted small mb-1">Saldo Atual</div>
        <div class="fs-5 fw-bold" style="color:{{ 'var(--color-success,#198754)' if saldo_atual_cents >= 0 else '#dc3545' }}">
          {{ saldo_atual_brl }}
        </div>
      </div>
    </div>
    <div class="col-6 col-md-3">
      <div class="card p-4 mb-0">
        <div class="text-muted small mb-1">Entradas Previstas</div>
        <div class="fs-5 fw-bold" style="color:#198754">{{ entradas_prev_brl }}</div>
      </div>
    </div>
    <div class="col-6 col-md-3">
      <div class="card p-4 mb-0">
        <div class="text-muted small mb-1">Saídas Previstas</div>
        <div class="fs-5 fw-bold" style="color:#dc3545">{{ saidas_prev_brl }}</div>
      </div>
    </div>
    <div class="col-6 col-md-3">
      <div class="card p-4 mb-0">
        <div class="text-muted small mb-1">Saldo Projetado</div>
        <div class="fs-5 fw-bold" style="color:{{ 'var(--color-success,#198754)' if saldo_proj_cents >= 0 else '#dc3545' }}">
          {{ saldo_proj_brl }}
        </div>
      </div>
    </div>
  </div>

  {# Filtros #}
  <div class="card p-4 mb-3">
    <form method="GET" action="/ferramentas/fluxo-caixa" class="row g-2 align-items-end">
      <div class="col-auto">
        <label class="form-label small mb-1">De</label>
        <input type="date" name="data_inicio" value="{{ data_inicio }}" class="form-control form-control-sm">
      </div>
      <div class="col-auto">
        <label class="form-label small mb-1">Até</label>
        <input type="date" name="data_fim" value="{{ data_fim }}" class="form-control form-control-sm">
      </div>
      <div class="col-auto">
        <label class="form-label small mb-1">Centro de Custo</label>
        <select name="centros" multiple class="form-select form-select-sm" style="min-width:160px;height:auto">
          {% for cc in centros_disponiveis %}
          <option value="{{ cc }}" {% if cc in centros_selecionados %}selected{% endif %}>{{ cc }}</option>
          {% endfor %}
        </select>
      </div>
      <div class="col-auto">
        <label class="form-label small mb-1">Agrupar por</label>
        <select name="group_by" class="form-select form-select-sm">
          <option value="dia"    {% if group_by=='dia'    %}selected{% endif %}>Dia</option>
          <option value="semana" {% if group_by=='semana' %}selected{% endif %}>Semana</option>
          <option value="mes"    {% if group_by=='mes'    %}selected{% endif %}>Mês</option>
        </select>
      </div>
      <div class="col-auto">
        <button type="submit" class="btn btn-primary btn-sm">Filtrar</button>
        <a href="/ferramentas/fluxo-caixa" class="btn btn-outline-secondary btn-sm ms-1">Limpar</a>
      </div>
    </form>
  </div>

  {# Tabela de fluxo #}
  <div class="card p-4 mb-3">
    <div class="table-responsive">
      <table class="table table-sm align-middle mb-0">
        <thead class="table-light">
          <tr>
            <th>Período</th>
            <th class="text-end">Ent. Previstas</th>
            <th class="text-end">Saí. Previstas</th>
            <th class="text-end">Saldo Previsto</th>
            <th class="text-end">Ent. Realizadas</th>
            <th class="text-end">Saí. Realizadas</th>
            <th class="text-end">Saldo Realizado</th>
            <th class="text-end">Saldo Acumulado</th>
          </tr>
        </thead>
        <tbody>
          {% for p in periodos %}
          <tr {% if p.critico %}style="background:rgba(220,53,69,0.08)"{% endif %}>
            <td>
              {{ p.label }}
              {% if p.critico %}<span class="badge ms-1" style="background:#dc3545;font-size:0.65rem">ALERTA</span>{% endif %}
            </td>
            <td class="text-end" style="color:#198754">{{ p.entradas_previstas_brl }}</td>
            <td class="text-end" style="color:#dc3545">{{ p.saidas_previstas_brl }}</td>
            <td class="text-end fw-semibold" style="color:{{ '#198754' if p.saldo_previsto >= 0 else '#dc3545' }}">
              {{ p.saldo_previsto_brl }}
            </td>
            <td class="text-end" style="color:#198754">{{ p.entradas_realizadas_brl }}</td>
            <td class="text-end" style="color:#dc3545">{{ p.saidas_realizadas_brl }}</td>
            <td class="text-end fw-semibold" style="color:{{ '#198754' if p.saldo_realizado >= 0 else '#dc3545' }}">
              {{ p.saldo_realizado_brl }}
            </td>
            <td class="text-end fw-bold" style="color:{{ '#198754' if p.saldo_acumulado_previsto >= 0 else '#dc3545' }}">
              {{ p.saldo_acumulado_previsto_brl }}
            </td>
          </tr>
          {% else %}
          <tr><td colspan="8" class="text-center text-muted py-4">Nenhum lançamento encontrado para o período.</td></tr>
          {% endfor %}
        </tbody>
      </table>
    </div>
    <div class="mt-2 d-flex justify-content-end">
      <a href="/ferramentas/fluxo-caixa/lancamentos?data_inicio={{ data_inicio }}&data_fim={{ data_fim }}" class="btn btn-outline-secondary btn-sm">
        Ver todos os lançamentos →
      </a>
    </div>
  </div>
</div>
{% endblock %}
"""

TEMPLATES["fluxo_caixa_lancamentos.html"] = r"""
{% extends "base.html" %}
{% block content %}
<div class="container-fluid px-4 py-3">
  <div class="d-flex align-items-center justify-content-between mb-3">
    <h4 class="mb-0">Lançamentos — Fluxo de Caixa</h4>
    <div class="d-flex gap-2">
      <a href="/ferramentas/fluxo-caixa/novo" class="btn btn-primary btn-sm">+ Novo</a>
      <a href="/ferramentas/fluxo-caixa" class="btn btn-outline-secondary btn-sm">← Dashboard</a>
    </div>
  </div>

  <div class="card p-3 mb-3">
    <form method="GET" class="row g-2 align-items-end">
      <div class="col-auto">
        <input type="date" name="data_inicio" value="{{ data_inicio }}" class="form-control form-control-sm" placeholder="De">
      </div>
      <div class="col-auto">
        <input type="date" name="data_fim" value="{{ data_fim }}" class="form-control form-control-sm" placeholder="Até">
      </div>
      <div class="col-auto">
        <select name="status" class="form-select form-select-sm">
          <option value="">Todos</option>
          <option value="previsto"  {% if status_filtro=='previsto'  %}selected{% endif %}>Previsto</option>
          <option value="realizado" {% if status_filtro=='realizado' %}selected{% endif %}>Realizado</option>
          <option value="cancelado" {% if status_filtro=='cancelado' %}selected{% endif %}>Cancelado</option>
        </select>
      </div>
      <div class="col-auto">
        <select name="tipo" class="form-select form-select-sm">
          <option value="">Entrada/Saída</option>
          <option value="entrada" {% if tipo_filtro=='entrada' %}selected{% endif %}>Entrada</option>
          <option value="saida"   {% if tipo_filtro=='saida'   %}selected{% endif %}>Saída</option>
        </select>
      </div>
      <div class="col-auto">
        <input type="text" name="q" value="{{ q }}" class="form-control form-control-sm" placeholder="Buscar descrição…">
      </div>
      <div class="col-auto">
        <button class="btn btn-primary btn-sm">Filtrar</button>
        <a href="/ferramentas/fluxo-caixa/lancamentos" class="btn btn-outline-secondary btn-sm ms-1">Limpar</a>
      </div>
    </form>
  </div>

  <div class="card p-4">
    <div class="table-responsive">
      <table class="table table-sm align-middle">
        <thead class="table-light">
          <tr>
            <th>Vencimento</th>
            <th>Descrição</th>
            <th>Centro de Custo</th>
            <th>Categoria</th>
            <th>Tipo</th>
            <th class="text-end">Valor</th>
            <th>Status</th>
            <th>Pagamento</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {% for e in entries %}
          <tr>
            <td class="text-nowrap">{{ e.data_vencimento_fmt }}</td>
            <td>{{ e.descricao }}</td>
            <td><span class="badge bg-secondary">{{ e.centro_custo }}</span></td>
            <td class="text-muted small">{{ e.categoria }}</td>
            <td>
              {% if e.tipo == 'entrada' %}
              <span class="badge" style="background:#198754">Entrada</span>
              {% else %}
              <span class="badge" style="background:#dc3545">Saída</span>
              {% endif %}
            </td>
            <td class="text-end fw-semibold" style="color:{{ '#198754' if e.tipo=='entrada' else '#dc3545' }}">
              {{ e.valor_brl }}
            </td>
            <td>
              {% if e.status == 'realizado' %}
              <span class="badge" style="background:#198754">Realizado</span>
              {% elif e.status == 'cancelado' %}
              <span class="badge bg-secondary">Cancelado</span>
              {% else %}
              <span class="badge bg-warning text-dark">Previsto</span>
              {% endif %}
            </td>
            <td class="text-muted small text-nowrap">{{ e.data_pagamento_fmt or '—' }}</td>
            <td class="text-nowrap">
              <a href="/ferramentas/fluxo-caixa/{{ e.id }}/editar" class="btn btn-outline-secondary btn-sm py-0 px-1">✏</a>
              {% if e.status == 'previsto' %}
              <form method="POST" action="/ferramentas/fluxo-caixa/{{ e.id }}/realizar" style="display:inline">
                <button class="btn btn-outline-success btn-sm py-0 px-1" title="Marcar como realizado">✓</button>
              </form>
              {% endif %}
              {% if e.status != 'cancelado' %}
              <form method="POST" action="/ferramentas/fluxo-caixa/{{ e.id }}/excluir" style="display:inline"
                    onsubmit="return confirm('Cancelar este lançamento?')">
                <button class="btn btn-outline-danger btn-sm py-0 px-1">✕</button>
              </form>
              {% endif %}
            </td>
          </tr>
          {% else %}
          <tr><td colspan="9" class="text-center text-muted py-4">Nenhum lançamento encontrado.</td></tr>
          {% endfor %}
        </tbody>
      </table>
    </div>
    {% if total > len(entries) %}
    <div class="text-muted small mt-2">Exibindo {{ entries|length }} de {{ total }} lançamentos.</div>
    {% endif %}
  </div>
</div>
{% endblock %}
"""

TEMPLATES["fluxo_caixa_form.html"] = r"""
{% extends "base.html" %}
{% block content %}
<div class="container px-4 py-3" style="max-width:640px">
  <div class="d-flex align-items-center gap-2 mb-3">
    <a href="/ferramentas/fluxo-caixa/lancamentos" class="btn btn-outline-secondary btn-sm">←</a>
    <h4 class="mb-0">{{ titulo }}</h4>
  </div>

  <div class="card p-4">
    <form method="POST">
      <div class="row g-3">
        <div class="col-12 col-sm-6">
          <label class="form-label">Data de Vencimento *</label>
          <input type="date" name="data_vencimento" value="{{ entry.data_vencimento }}"
                 class="form-control" required>
        </div>
        <div class="col-12 col-sm-6">
          <label class="form-label">Tipo *</label>
          <select name="tipo" class="form-select" required>
            <option value="entrada" {% if entry.tipo=='entrada' %}selected{% endif %}>Entrada</option>
            <option value="saida"   {% if entry.tipo=='saida'   %}selected{% endif %}>Saída</option>
          </select>
        </div>
        <div class="col-12">
          <label class="form-label">Descrição *</label>
          <input type="text" name="descricao" value="{{ entry.descricao }}"
                 class="form-control" required placeholder="Ex: Recebimento Passione Bloco A">
        </div>
        <div class="col-12 col-sm-6">
          <label class="form-label">Valor (R$) *</label>
          <input type="text" name="valor" value="{{ entry.valor_str }}"
                 class="form-control" required placeholder="0,00">
        </div>
        <div class="col-12 col-sm-6">
          <label class="form-label">Status</label>
          <select name="status" class="form-select">
            <option value="previsto"  {% if entry.status=='previsto'  %}selected{% endif %}>Previsto</option>
            <option value="realizado" {% if entry.status=='realizado' %}selected{% endif %}>Realizado</option>
          </select>
        </div>
        <div class="col-12 col-sm-6">
          <label class="form-label">Centro de Custo</label>
          <input type="text" name="centro_custo" value="{{ entry.centro_custo }}"
                 class="form-control" list="cc-list" placeholder="Ex: Passione, Administrativo">
          <datalist id="cc-list">
            {% for cc in centros_disponiveis %}
            <option value="{{ cc }}">
            {% endfor %}
          </datalist>
        </div>
        <div class="col-12 col-sm-6">
          <label class="form-label">Categoria</label>
          <input type="text" name="categoria" value="{{ entry.categoria }}"
                 class="form-control" list="cat-list" placeholder="Ex: Receita de Venda, Custo Direto">
          <datalist id="cat-list">
            <option value="Receita de Venda">
            <option value="Receita de Serviço">
            <option value="Comissão">
            <option value="Custo Direto">
            <option value="Despesa Administrativa">
            <option value="Imposto">
            <option value="Outros">
          </datalist>
        </div>
        <div class="col-12">
          <label class="form-label">Data de Pagamento</label>
          <input type="date" name="data_pagamento" value="{{ entry.data_pagamento or '' }}"
                 class="form-control">
          <div class="form-text">Preencha apenas se já foi pago/recebido.</div>
        </div>
        <div class="col-12">
          <label class="form-label">Observação</label>
          <textarea name="observacao" class="form-control" rows="2"
                    placeholder="Informações adicionais…">{{ entry.observacao }}</textarea>
        </div>
      </div>
      <div class="mt-4 d-flex gap-2">
        <button type="submit" class="btn btn-primary">Salvar</button>
        <a href="/ferramentas/fluxo-caixa/lancamentos" class="btn btn-outline-secondary">Cancelar</a>
      </div>
    </form>
  </div>
</div>
{% endblock %}
"""

TEMPLATES["fluxo_caixa_config.html"] = r"""
{% extends "base.html" %}
{% block content %}
<div class="container px-4 py-3" style="max-width:520px">
  <div class="d-flex align-items-center gap-2 mb-3">
    <a href="/ferramentas/fluxo-caixa" class="btn btn-outline-secondary btn-sm">←</a>
    <h4 class="mb-0">Configurações — Fluxo de Caixa</h4>
  </div>
  <div class="card p-4">
    <form method="POST">
      <div class="mb-3">
        <label class="form-label">Saldo Inicial em Caixa (R$)</label>
        <input type="text" name="saldo_inicial" value="{{ saldo_inicial_str }}"
               class="form-control" placeholder="0,00">
        <div class="form-text">Saldo de partida para cálculo do saldo acumulado.</div>
      </div>
      <div class="mb-3">
        <label class="form-label">Limite Conta Garantida (R$)</label>
        <input type="text" name="limite_cc" value="{{ limite_cc_str }}"
               class="form-control" placeholder="0,00">
        <div class="form-text">Crédito disponível na conta garantida (informativo).</div>
      </div>
      <div class="mb-3">
        <label class="form-label">Limite de Alerta (R$)</label>
        <input type="text" name="limite_alerta" value="{{ limite_alerta_str }}"
               class="form-control" placeholder="0,00">
        <div class="form-text">Períodos com saldo acumulado abaixo deste valor serão destacados em vermelho.</div>
      </div>
      <div class="mt-3 d-flex gap-2">
        <button type="submit" class="btn btn-primary">Salvar</button>
        <a href="/ferramentas/fluxo-caixa" class="btn btn-outline-secondary">Cancelar</a>
      </div>
    </form>
  </div>
</div>
{% endblock %}
"""

TEMPLATES["fluxo_caixa_importar.html"] = r"""
{% extends "base.html" %}
{% block content %}
<div class="container px-4 py-3" style="max-width:860px">
  <div class="d-flex align-items-center gap-2 mb-3">
    <a href="/ferramentas/fluxo-caixa" class="btn btn-outline-secondary btn-sm">←</a>
    <h4 class="mb-0">Importar Lançamentos — Excel</h4>
  </div>

  <div class="card p-4 mb-3">
    <h6 class="mb-3">1. Selecione o arquivo</h6>
    <input type="file" id="file-input" accept=".xlsx,.xls,.csv" class="form-control mb-3">
    <button onclick="uploadFile()" class="btn btn-primary">Carregar e pré-visualizar</button>
  </div>

  <div id="preview-area" style="display:none">
    <div class="card p-4 mb-3">
      <h6 class="mb-3">2. Mapeamento de colunas</h6>
      <div id="mapping-form" class="row g-3"></div>
    </div>
    <div class="card p-4 mb-3">
      <h6 class="mb-3">3. Pré-visualização (primeiras 10 linhas)</h6>
      <div class="table-responsive">
        <table class="table table-sm" id="preview-table"></table>
      </div>
    </div>
    <button onclick="confirmarImportacao()" class="btn btn-primary">Confirmar Importação</button>
    <div id="import-result" class="mt-3"></div>
  </div>
</div>

<script>
let _uploadPayload = null;

async function uploadFile() {
  const file = document.getElementById('file-input').files[0];
  if (!file) { alert('Selecione um arquivo primeiro.'); return; }
  const fd = new FormData();
  fd.append('file', file);
  const resp = await fetch('/api/fluxo-caixa/upload', { method: 'POST', body: fd });
  const data = await resp.json();
  if (data.erro) { alert('Erro: ' + data.erro); return; }
  _uploadPayload = data;
  renderPreview(data);
}

function renderPreview(data) {
  document.getElementById('preview-area').style.display = '';
  // Mapeamento
  const campos = [
    {key:'col_data',        label:'Coluna de Data'},
    {key:'col_valor',       label:'Coluna de Valor'},
    {key:'col_descricao',   label:'Coluna de Descrição'},
    {key:'col_tipo',        label:'Coluna de Tipo (Entrada/Saída)'},
    {key:'col_centro_custo',label:'Coluna de Centro de Custo'},
    {key:'col_categoria',   label:'Coluna de Categoria'},
  ];
  let html = '';
  for (const c of campos) {
    html += `<div class="col-12 col-md-4">
      <label class="form-label small">${c.label}</label>
      <select id="map_${c.key}" class="form-select form-select-sm">
        <option value="">(não mapear)</option>
        ${data.colunas.map(col => `<option value="${col}" ${data.sugestoes[c.key]==col?'selected':''}>${col}</option>`).join('')}
      </select>
    </div>`;
  }
  document.getElementById('mapping-form').innerHTML = html;

  // Tabela preview
  const cols = data.colunas;
  let th = cols.map(c => `<th>${c}</th>`).join('');
  let rows = data.preview.map(row =>
    '<tr>' + cols.map(c => `<td class="small">${row[c]??''}</td>`).join('') + '</tr>'
  ).join('');
  document.getElementById('preview-table').innerHTML =
    `<thead class="table-light"><tr>${th}</tr></thead><tbody>${rows}</tbody>`;
}

async function confirmarImportacao() {
  if (!_uploadPayload) return;
  const mapeamento = {};
  ['col_data','col_valor','col_descricao','col_tipo','col_centro_custo','col_categoria'].forEach(k => {
    mapeamento[k] = document.getElementById('map_'+k)?.value || '';
  });
  const body = { mapeamento, dados: _uploadPayload.dados_completos };
  const resp = await fetch('/api/fluxo-caixa/importar-confirmar', {
    method: 'POST',
    headers: {'Content-Type':'application/json'},
    body: JSON.stringify(body)
  });
  const data = await resp.json();
  document.getElementById('import-result').innerHTML = data.erro
    ? `<div class="alert alert-danger">${data.erro}</div>`
    : `<div class="alert alert-success">✅ ${data.importados} lançamentos importados com sucesso! <a href="/ferramentas/fluxo-caixa/lancamentos">Ver lançamentos →</a></div>`;
}
</script>
{% endblock %}
"""

# ── Rotas ─────────────────────────────────────────────────────────────────────

@app.get("/ferramentas/fluxo-caixa", response_class=HTMLResponse)
@require_login
async def fc_dashboard(
    request: Request,
    session: Session = Depends(get_session),
    data_inicio: str = "",
    data_fim: str = "",
    group_by: str = "semana",
    centros: _List_fc[str] = None,
):
    ctx        = get_tenant_context(request, session)
    client_id  = get_active_client_id(request, session, ctx)
    hoje       = _date_fc.today()
    _di        = data_inicio or (hoje - _td_fc(days=30)).isoformat()
    _df        = data_fim    or (hoje + _td_fc(days=60)).isoformat()
    centros    = centros or []
    cfg        = _fc_get_config(session, ctx.company.id, client_id)
    entries_all = _fc_get_entries(session, ctx.company.id, client_id, _di, _df,
                                  centros if centros else None)

    # Centros disponíveis (todos os lançamentos, sem filtro de período)
    todos = _fc_get_entries(session, ctx.company.id, client_id)
    centros_disp = sorted(set(e.centro_custo for e in todos if e.centro_custo))

    periodos_raw = _calc_fluxo(entries_all, cfg, group_by)

    # Enriquece periodos com strings formatadas
    for p in periodos_raw:
        p["entradas_previstas_brl"]       = _cents_to_brl(p["entradas_previstas"])
        p["saidas_previstas_brl"]         = _cents_to_brl(p["saidas_previstas"])
        p["saldo_previsto_brl"]           = _cents_to_brl(p["saldo_previsto"])
        p["entradas_realizadas_brl"]      = _cents_to_brl(p["entradas_realizadas"])
        p["saidas_realizadas_brl"]        = _cents_to_brl(p["saidas_realizadas"])
        p["saldo_realizado_brl"]          = _cents_to_brl(p["saldo_realizado"])
        p["saldo_acumulado_previsto_brl"] = _cents_to_brl(p["saldo_acumulado_previsto"])

    # Cards resumo (baseado no período filtrado)
    ent_prev_c  = sum(e.valor_cents for e in entries_all if e.tipo=="entrada")
    sai_prev_c  = sum(e.valor_cents for e in entries_all if e.tipo=="saida")
    saldo_proj  = cfg.saldo_inicial_cents + ent_prev_c - sai_prev_c

    return render("fluxo_caixa_dashboard.html", request=request, context={
        "saldo_atual_cents":  cfg.saldo_inicial_cents,
        "saldo_atual_brl":    _cents_to_brl(cfg.saldo_inicial_cents),
        "entradas_prev_brl":  _cents_to_brl(ent_prev_c),
        "saidas_prev_brl":    _cents_to_brl(sai_prev_c),
        "saldo_proj_cents":   saldo_proj,
        "saldo_proj_brl":     _cents_to_brl(saldo_proj),
        "periodos":           periodos_raw,
        "group_by":           group_by,
        "data_inicio":        _di,
        "data_fim":           _df,
        "centros_disponiveis":centros_disp,
        "centros_selecionados":centros,
        "page_title":         "Fluxo de Caixa",
    })


@app.get("/ferramentas/fluxo-caixa/lancamentos", response_class=HTMLResponse)
@require_login
async def fc_lista(
    request: Request,
    session: Session = Depends(get_session),
    data_inicio: str = "",
    data_fim: str = "",
    status: str = "",
    tipo: str = "",
    q: str = "",
):
    ctx        = get_tenant_context(request, session)
    client_id  = get_active_client_id(request, session, ctx)
    query      = select(CashFlowEntry).where(
        CashFlowEntry.company_id == ctx.company.id,
        CashFlowEntry.client_id  == client_id,
    )
    if data_inicio:
        query = query.where(CashFlowEntry.data_vencimento >= data_inicio)
    if data_fim:
        query = query.where(CashFlowEntry.data_vencimento <= data_fim)
    if status:
        query = query.where(CashFlowEntry.status == status)
    else:
        query = query.where(CashFlowEntry.status != "cancelado")
    if tipo:
        query = query.where(CashFlowEntry.tipo == tipo)
    entries = list(session.exec(query.order_by(CashFlowEntry.data_vencimento.desc())).all())
    if q:
        entries = [e for e in entries if q.lower() in e.descricao.lower()]

    def _fmt_date(s):
        if not s:
            return ""
        try:
            return _date_fc.fromisoformat(s).strftime("%d/%m/%Y")
        except Exception:
            return s

    rows = []
    for e in entries:
        d = {
            "id": e.id,
            "data_vencimento": e.data_vencimento,
            "data_vencimento_fmt": _fmt_date(e.data_vencimento),
            "data_pagamento": e.data_pagamento,
            "data_pagamento_fmt": _fmt_date(e.data_pagamento),
            "descricao": e.descricao,
            "centro_custo": e.centro_custo,
            "categoria": e.categoria,
            "tipo": e.tipo,
            "valor_brl": _cents_to_brl(e.valor_cents),
            "status": e.status,
            "observacao": e.observacao,
        }
        rows.append(d)

    return render("fluxo_caixa_lancamentos.html", request=request, context={
        "entries":      rows,
        "total":        len(rows),
        "data_inicio":  data_inicio,
        "data_fim":     data_fim,
        "status_filtro":status,
        "tipo_filtro":  tipo,
        "q":            q,
        "page_title":   "Lançamentos — Fluxo de Caixa",
    })


def _fc_entry_dict(e: CashFlowEntry) -> dict:
    return {
        "id":              e.id if e.id else 0,
        "data_vencimento": e.data_vencimento,
        "data_pagamento":  e.data_pagamento or "",
        "descricao":       e.descricao,
        "centro_custo":    e.centro_custo,
        "categoria":       e.categoria,
        "tipo":            e.tipo,
        "status":          e.status,
        "observacao":      e.observacao,
        "valor_str":       f"{e.valor_cents/100:.2f}".replace(".", ","),
    }


def _fc_centros(session, company_id, client_id):
    todos = _fc_get_entries(session, company_id, client_id)
    return sorted(set(e.centro_custo for e in todos if e.centro_custo)) or [
        "Geral", "Administrativo", "Comercial"
    ]


@app.get("/ferramentas/fluxo-caixa/novo", response_class=HTMLResponse)
@require_login
async def fc_novo_get(request: Request, session: Session = Depends(get_session)):
    ctx       = get_tenant_context(request, session)
    client_id = get_active_client_id(request, session, ctx)
    hoje      = _date_fc.today().isoformat()
    empty     = CashFlowEntry(
        company_id=ctx.company.id, client_id=client_id,
        data_vencimento=hoje, tipo="saida", status="previsto",
        centro_custo="Geral", categoria="Outros",
    )
    return render("fluxo_caixa_form.html", request=request, context={
        "titulo":             "Novo Lançamento",
        "entry":              _fc_entry_dict(empty),
        "centros_disponiveis":_fc_centros(session, ctx.company.id, client_id),
        "page_title":         "Novo Lançamento",
    })


@app.post("/ferramentas/fluxo-caixa/novo", response_class=HTMLResponse)
@require_login
async def fc_novo_post(request: Request, session: Session = Depends(get_session)):
    ctx       = get_tenant_context(request, session)
    client_id = get_active_client_id(request, session, ctx)
    form      = await request.form()
    entry     = CashFlowEntry(
        company_id=ctx.company.id,
        client_id=client_id,
        data_vencimento=form.get("data_vencimento", ""),
        data_pagamento=form.get("data_pagamento") or None,
        descricao=form.get("descricao", "").strip(),
        centro_custo=form.get("centro_custo", "Geral").strip() or "Geral",
        categoria=form.get("categoria", "Outros").strip() or "Outros",
        tipo=form.get("tipo", "saida"),
        valor_cents=_brl_to_cents(form.get("valor", "0")),
        status=form.get("status", "previsto"),
        observacao=form.get("observacao", "").strip(),
        created_at=utcnow(),
        updated_at=utcnow(),
    )
    session.add(entry)
    session.commit()
    set_flash(request, "Lançamento criado com sucesso.")
    from fastapi.responses import RedirectResponse
    return RedirectResponse("/ferramentas/fluxo-caixa/lancamentos", status_code=303)


@app.get("/ferramentas/fluxo-caixa/{entry_id}/editar", response_class=HTMLResponse)
@require_login
async def fc_editar_get(entry_id: int, request: Request, session: Session = Depends(get_session)):
    ctx       = get_tenant_context(request, session)
    client_id = get_active_client_id(request, session, ctx)
    e         = session.get(CashFlowEntry, entry_id)
    if not e or e.company_id != ctx.company.id:
        set_flash(request, "Lançamento não encontrado.")
        from fastapi.responses import RedirectResponse
        return RedirectResponse("/ferramentas/fluxo-caixa/lancamentos", status_code=303)
    return render("fluxo_caixa_form.html", request=request, context={
        "titulo":             "Editar Lançamento",
        "entry":              _fc_entry_dict(e),
        "centros_disponiveis":_fc_centros(session, ctx.company.id, client_id),
        "page_title":         "Editar Lançamento",
    })


@app.post("/ferramentas/fluxo-caixa/{entry_id}/editar", response_class=HTMLResponse)
@require_login
async def fc_editar_post(entry_id: int, request: Request, session: Session = Depends(get_session)):
    ctx  = get_tenant_context(request, session)
    e    = session.get(CashFlowEntry, entry_id)
    if not e or e.company_id != ctx.company.id:
        set_flash(request, "Lançamento não encontrado.")
        from fastapi.responses import RedirectResponse
        return RedirectResponse("/ferramentas/fluxo-caixa/lancamentos", status_code=303)
    form = await request.form()
    e.data_vencimento = form.get("data_vencimento", e.data_vencimento)
    e.data_pagamento  = form.get("data_pagamento") or None
    e.descricao       = form.get("descricao", e.descricao).strip()
    e.centro_custo    = form.get("centro_custo", e.centro_custo).strip() or "Geral"
    e.categoria       = form.get("categoria", e.categoria).strip() or "Outros"
    e.tipo            = form.get("tipo", e.tipo)
    e.valor_cents     = _brl_to_cents(form.get("valor", "0"))
    e.status          = form.get("status", e.status)
    e.observacao      = form.get("observacao", "").strip()
    e.updated_at      = utcnow()
    session.add(e)
    session.commit()
    set_flash(request, "Lançamento atualizado.")
    from fastapi.responses import RedirectResponse
    return RedirectResponse("/ferramentas/fluxo-caixa/lancamentos", status_code=303)


@app.post("/ferramentas/fluxo-caixa/{entry_id}/realizar", response_class=HTMLResponse)
@require_login
async def fc_realizar(entry_id: int, request: Request, session: Session = Depends(get_session)):
    ctx = get_tenant_context(request, session)
    e   = session.get(CashFlowEntry, entry_id)
    if e and e.company_id == ctx.company.id:
        e.status         = "realizado"
        e.data_pagamento = _date_fc.today().isoformat()
        e.updated_at     = utcnow()
        session.add(e)
        session.commit()
        set_flash(request, "Lançamento marcado como realizado.")
    from fastapi.responses import RedirectResponse
    return RedirectResponse("/ferramentas/fluxo-caixa/lancamentos", status_code=303)


@app.post("/ferramentas/fluxo-caixa/{entry_id}/excluir", response_class=HTMLResponse)
@require_login
async def fc_excluir(entry_id: int, request: Request, session: Session = Depends(get_session)):
    ctx = get_tenant_context(request, session)
    e   = session.get(CashFlowEntry, entry_id)
    if e and e.company_id == ctx.company.id:
        e.status     = "cancelado"
        e.updated_at = utcnow()
        session.add(e)
        session.commit()
        set_flash(request, "Lançamento cancelado.")
    from fastapi.responses import RedirectResponse
    return RedirectResponse("/ferramentas/fluxo-caixa/lancamentos", status_code=303)


@app.get("/ferramentas/fluxo-caixa/config", response_class=HTMLResponse)
@require_login
async def fc_config_get(request: Request, session: Session = Depends(get_session)):
    ctx       = get_tenant_context(request, session)
    client_id = get_active_client_id(request, session, ctx)
    cfg       = _fc_get_config(session, ctx.company.id, client_id)

    def _fmt(c):
        return f"{c/100:.2f}".replace(".", ",")

    return render("fluxo_caixa_config.html", request=request, context={
        "saldo_inicial_str":  _fmt(cfg.saldo_inicial_cents),
        "limite_cc_str":      _fmt(cfg.limite_cc_cents),
        "limite_alerta_str":  _fmt(cfg.limite_alerta_cents),
        "page_title":         "Configurações — Fluxo de Caixa",
    })


@app.post("/ferramentas/fluxo-caixa/config", response_class=HTMLResponse)
@require_login
async def fc_config_post(request: Request, session: Session = Depends(get_session)):
    ctx       = get_tenant_context(request, session)
    client_id = get_active_client_id(request, session, ctx)
    cfg       = _fc_get_config(session, ctx.company.id, client_id)
    form      = await request.form()
    cfg.saldo_inicial_cents = _brl_to_cents(form.get("saldo_inicial", "0"))
    cfg.limite_cc_cents     = _brl_to_cents(form.get("limite_cc", "0"))
    cfg.limite_alerta_cents = _brl_to_cents(form.get("limite_alerta", "0"))
    cfg.updated_at          = utcnow()
    session.add(cfg)
    session.commit()
    set_flash(request, "Configurações salvas com sucesso.")
    from fastapi.responses import RedirectResponse
    return RedirectResponse("/ferramentas/fluxo-caixa", status_code=303)


@app.get("/ferramentas/fluxo-caixa/importar", response_class=HTMLResponse)
@require_login
async def fc_importar_page(request: Request, session: Session = Depends(get_session)):
    get_tenant_context(request, session)
    return render("fluxo_caixa_importar.html", request=request, context={
        "page_title": "Importar Excel — Fluxo de Caixa",
    })


# ── API de importação ─────────────────────────────────────────────────────────

def _fc_detect_col(cols: list, keywords: _List_fc[str]) -> str:
    """Detecta coluna por palavras-chave no nome (case insensitive)."""
    for col in cols:
        col_lower = col.lower()
        if any(kw in col_lower for kw in keywords):
            return col
    return ""


def _fc_parse_date(val) -> str:
    """Tenta converter valor para ISO date string."""
    if val is None:
        return ""
    s = str(val).strip()
    # tenta formatos comuns
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y", "%m/%d/%Y", "%Y/%m/%d"):
        try:
            return _date_fc.strptime(s[:10], fmt).isoformat()
        except Exception:
            pass
    # pode ser datetime do pandas/excel
    try:
        import pandas as _pd_fc2
        if hasattr(val, 'date'):
            return val.date().isoformat()
        ts = _pd_fc2.Timestamp(val)
        return ts.date().isoformat()
    except Exception:
        pass
    return s


def _fc_parse_valor(val) -> tuple:
    """Retorna (valor_cents, tipo_sugerido)."""
    if val is None:
        return 0, "saida"
    try:
        v = float(str(val).replace(",", ".").replace(" ", ""))
    except Exception:
        return 0, "saida"
    return abs(int(round(v * 100))), ("entrada" if v >= 0 else "saida")


def _fc_parse_tipo(val: str, tipo_por_valor: str) -> str:
    if not val:
        return tipo_por_valor
    v = str(val).strip().lower()
    if v in ("entrada", "e", "c", "crédito", "credito", "credit"):
        return "entrada"
    if v in ("saida", "saída", "s", "d", "débito", "debito", "debit"):
        return "saida"
    return tipo_por_valor


@app.post("/api/fluxo-caixa/upload")
@require_login
async def fc_upload(request: Request, session: Session = Depends(get_session)):
    from fastapi import UploadFile
    from fastapi.responses import JSONResponse
    try:
        import pandas as _pd_fc
    except ImportError:
        return JSONResponse({"erro": "Biblioteca pandas não instalada. Execute: pip install pandas openpyxl"})

    get_tenant_context(request, session)
    form  = await request.form()
    file  = form.get("file")
    if not file:
        return JSONResponse({"erro": "Nenhum arquivo enviado."})

    content = await file.read()
    nome    = getattr(file, "filename", "arquivo")

    try:
        if nome.lower().endswith(".csv"):
            df = _pd_fc.read_csv(_io_fc.BytesIO(content), dtype=str)
        else:
            df = _pd_fc.read_excel(_io_fc.BytesIO(content), dtype=str)
    except Exception as ex:
        return JSONResponse({"erro": f"Erro ao ler arquivo: {ex}"})

    df = df.dropna(how="all")
    if df.empty:
        return JSONResponse({"erro": "Arquivo vazio ou sem dados reconhecíveis."})

    cols = list(df.columns)
    sugestoes = {
        "col_data":         _fc_detect_col(cols, ["data", "venc", "dt", "date"]),
        "col_valor":        _fc_detect_col(cols, ["valor", "vl", "total", "amount"]),
        "col_descricao":    _fc_detect_col(cols, ["desc", "historico", "obs", "memo", "histórico", "históric"]),
        "col_tipo":         _fc_detect_col(cols, ["tipo", "natureza", "nature"]),
        "col_centro_custo": _fc_detect_col(cols, ["centro", "cc", "obra", "projeto", "project"]),
        "col_categoria":    _fc_detect_col(cols, ["categoria", "grupo", "group", "class"]),
    }

    preview = _json_fc.loads(df.head(10).fillna("").to_json(orient="records", force_ascii=False))
    dados   = _json_fc.loads(df.fillna("").to_json(orient="records", force_ascii=False))

    return JSONResponse({
        "colunas":       cols,
        "sugestoes":     sugestoes,
        "preview":       preview,
        "dados_completos": dados,
    })


@app.post("/api/fluxo-caixa/importar-confirmar")
@require_login
async def fc_importar_confirmar(request: Request, session: Session = Depends(get_session)):
    from fastapi.responses import JSONResponse
    ctx       = get_tenant_context(request, session)
    client_id = get_active_client_id(request, session, ctx)
    body      = await request.json()
    mapeamento = body.get("mapeamento", {})
    dados      = body.get("dados", [])

    if not dados:
        return JSONResponse({"erro": "Nenhum dado recebido."})

    col_data  = mapeamento.get("col_data", "")
    col_valor = mapeamento.get("col_valor", "")
    col_desc  = mapeamento.get("col_descricao", "")
    col_tipo  = mapeamento.get("col_tipo", "")
    col_cc    = mapeamento.get("col_centro_custo", "")
    col_cat   = mapeamento.get("col_categoria", "")

    if not col_data or not col_valor:
        return JSONResponse({"erro": "As colunas de Data e Valor são obrigatórias."})

    batch_id   = str(_uuid_fc.uuid4())[:8]
    importados = 0
    erros      = []

    for i, row in enumerate(dados):
        try:
            data_str      = _fc_parse_date(row.get(col_data, ""))
            valor_c, tipo_v = _fc_parse_valor(row.get(col_valor, 0))
            tipo_col       = _fc_parse_tipo(str(row.get(col_tipo, "")), tipo_v)
            descricao      = str(row.get(col_desc, f"Importado linha {i+2}")).strip() or f"Importado linha {i+2}"
            centro_custo   = str(row.get(col_cc, "Importado")).strip() or "Importado"
            categoria      = str(row.get(col_cat, "Importado")).strip() or "Importado"

            if not data_str or valor_c == 0:
                erros.append(f"Linha {i+2}: data ou valor inválido — ignorado.")
                continue

            entry = CashFlowEntry(
                company_id=ctx.company.id,
                client_id=client_id,
                data_vencimento=data_str,
                descricao=descricao,
                centro_custo=centro_custo,
                categoria=categoria,
                tipo=tipo_col,
                valor_cents=valor_c,
                status="previsto",
                import_batch=batch_id,
                created_at=utcnow(),
                updated_at=utcnow(),
            )
            session.add(entry)
            importados += 1
        except Exception as ex:
            erros.append(f"Linha {i+2}: {ex}")

    session.commit()
    return JSONResponse({
        "importados": importados,
        "erros":      erros[:20],
        "batch_id":   batch_id,
    })


# ── Integração Augur — sobrescreve _enriquecer_client_data ───────────────────

_orig_fc_enriquecer = _enriquecer_client_data

def _fc_enriquecer(session, company_id, client_id, client, client_data):
    client_data = _orig_fc_enriquecer(session, company_id, client_id, client, client_data)
    try:
        client_data["fluxo_caixa_resumo"] = _build_fc_context(session, company_id, client_id)
    except Exception as _e_aug_fc:
        client_data["fluxo_caixa_resumo"] = {"erro": str(_e_aug_fc)}
    return client_data

_enriquecer_client_data = _fc_enriquecer


# ── Produto no catálogo de precificação ───────────────────────────────────────

def _fc_registrar_produto():
    try:
        with Session(engine) as _s:
            # Para cada company, não registramos aqui sem company_id definido.
            # O produto é registrado via _sincronizar_produtos() chamado sob demanda.
            # Aqui apenas garantimos que o produto base está em _PRODUTOS_BASE.
            pass
    except Exception as _ep:
        print(f"[fluxo_caixa] produto: {_ep}")

# Adiciona produto ao catálogo base se ainda não estiver
_FC_PRODUTO = {
    "codigo":    "fluxo_caixa_mensal",
    "nome":      "Fluxo de Caixa",
    "descricao": "Gestão de fluxo de caixa previsto e realizado",
    "categoria": "ferramenta",
    "modelo":    "assinatura",
    "creditos":  50,
}

try:
    if not any(p["codigo"] == "fluxo_caixa_mensal" for p in _PRODUTOS_BASE):
        _PRODUTOS_BASE.append(_FC_PRODUTO)
except Exception as _e_prod_fc:
    print(f"[fluxo_caixa] _PRODUTOS_BASE: {_e_prod_fc}")

print("[fluxo_caixa] ✅ Módulo carregado — rotas /ferramentas/fluxo-caixa registradas.")

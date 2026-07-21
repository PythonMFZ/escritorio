# Módulo: Controle de Produção (Kanban + PCP)
# Ordens de Produção, Roteiro, Materiais, Planejamento x Controle

import json
import secrets
from datetime import date, datetime
from typing import List, Optional

from fastapi import Depends, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlmodel import Field, Session, SQLModel, select
from sqlalchemy import case as _sa_case

try:
    import qrcode as _qrlib
    import io as _qrio
    import base64 as _qrb64
    _QR_OK = True
except ImportError:
    _QR_OK = False


# ── Modelos ───────────────────────────────────────────────────────────────────

class ProducaoProcesso(SQLModel, table=True):
    """Etapa/coluna do Kanban — personalizável por cliente."""
    id: Optional[int] = Field(default=None, primary_key=True)
    company_id: int = Field(index=True)
    client_id: Optional[int] = Field(default=None, index=True)
    nome: str
    ordem: int = Field(default=0)
    cor: str = Field(default="#6366f1")
    created_at: datetime = Field(default_factory=datetime.utcnow)


class OrdemProducao(SQLModel, table=True):
    """Ordem de Produção (OP)."""
    id: Optional[int] = Field(default=None, primary_key=True)
    company_id: int = Field(index=True)
    client_id: Optional[int] = Field(default=None, index=True)
    codigo: str
    produto: str
    descricao: str = Field(default="")
    quantidade_planejada: float = Field(default=0)
    quantidade_produzida: float = Field(default=0)
    data_inicio_plan: Optional[date] = Field(default=None)
    data_fim_plan: Optional[date] = Field(default=None)
    data_inicio_real: Optional[date] = Field(default=None)
    data_fim_real: Optional[date] = Field(default=None)
    processo_id: Optional[int] = Field(default=None, foreign_key="producaoprocesso.id")
    prioridade: str = Field(default="normal")
    status: str = Field(default="aberta")
    responsavel: str = Field(default="")
    observacoes: str = Field(default="")
    cor: str = Field(default="")
    pedido: str = Field(default="")
    token: str = Field(default_factory=lambda: secrets.token_urlsafe(16))
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class ProducaoRoteiroPasso(SQLModel, table=True):
    """Um passo do roteiro de produção de uma OP."""
    id: Optional[int] = Field(default=None, primary_key=True)
    op_id: int = Field(index=True, foreign_key="ordemproducao.id")
    processo_id: int = Field(foreign_key="producaoprocesso.id")
    ordem: int = Field(default=0)
    tempo_estimado_h: float = Field(default=0)
    tempo_realizado_h: float = Field(default=0)
    data_entrada: Optional[datetime] = Field(default=None)
    data_saida: Optional[datetime] = Field(default=None)
    status: str = Field(default="pendente")


class ProducaoMaterial(SQLModel, table=True):
    """Material/insumo vinculado a uma OP."""
    id: Optional[int] = Field(default=None, primary_key=True)
    op_id: int = Field(index=True, foreign_key="ordemproducao.id")
    company_id: int = Field(index=True)
    nome: str
    unidade: str = Field(default="un")
    quantidade_planejada: float = Field(default=0)
    quantidade_consumida: float = Field(default=0)
    custo_unitario: float = Field(default=0)
    created_at: datetime = Field(default_factory=datetime.utcnow)


class ProducaoMaterialCatalogo(SQLModel, table=True):
    """Catálogo mestre de materiais por cliente."""
    id: Optional[int] = Field(default=None, primary_key=True)
    company_id: int = Field(index=True)
    client_id: Optional[int] = Field(default=None, index=True)
    nome: str
    unidade: str = Field(default="un")
    custo_unitario_padrao: float = Field(default=0)
    created_at: datetime = Field(default_factory=datetime.utcnow)


# Cria tabelas (idempotente — só cria se não existir)
SQLModel.metadata.create_all(engine, tables=[
    ProducaoProcesso.__table__,
    OrdemProducao.__table__,
    ProducaoRoteiroPasso.__table__,
    ProducaoMaterial.__table__,
    ProducaoMaterialCatalogo.__table__,
])

# Migração: adiciona client_id às tabelas existentes (ALTER TABLE seguro)
def _prod_migration():
    _sa_text = __import__("sqlalchemy").text
    for _tbl, _col in [
        ("producaoprocesso",        "client_id INTEGER"),
        ("ordemproducao",           "client_id INTEGER"),
        ("producaomaterialcatalogo","client_id INTEGER"),
        ("ordemproducao",           "cor TEXT DEFAULT ''"),
        ("ordemproducao",           "pedido TEXT DEFAULT ''"),
        ("ordemproducao",           "token TEXT DEFAULT ''"),
    ]:
        try:
            with engine.connect() as _conn:
                _conn.execute(_sa_text(f"ALTER TABLE {_tbl} ADD COLUMN {_col}"))
                _conn.commit()
        except Exception:
            pass  # coluna já existe — fresh connection evita estado abortado

_prod_migration()


def _qr_png_b64(data: str) -> str:
    """Gera QR Code como PNG base64. Retorna '' se lib não disponível."""
    if not _QR_OK:
        return ""
    try:
        qr = _qrlib.QRCode(version=1, box_size=8, border=3)
        qr.add_data(data)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        buf = _qrio.BytesIO()
        img.save(buf, format="PNG")
        return _qrb64.b64encode(buf.getvalue()).decode()
    except Exception:
        return ""


# ── Helpers ───────────────────────────────────────────────────────────────────

_PRIORIDADE_COR = {
    "baixa": "#94a3b8", "normal": "#6366f1", "alta": "#f97316", "urgente": "#dc2626",
}

def _ctx_base(ctx, current_client=None):
    return {"current_user": ctx.user, "current_company": ctx.company,
            "role": ctx.membership.role, "current_client": current_client}

def _resolve_client(request, session, ctx):
    """Retorna o cliente ativo, igual às outras ferramentas."""
    try:
        return _client_current_client(request, session, ctx)
    except Exception:
        return None

def _processos(session, company_id, client_id=None):
    q = select(ProducaoProcesso).where(ProducaoProcesso.company_id == company_id)
    if client_id:
        q = q.where(ProducaoProcesso.client_id == client_id)
    return session.exec(q.order_by(ProducaoProcesso.ordem)).all()

def _ops(session, company_id, client_id=None):
    pri = _sa_case({"urgente": 0, "alta": 1, "normal": 2, "baixa": 3},
                   value=OrdemProducao.prioridade, else_=99)
    q = select(OrdemProducao).where(OrdemProducao.company_id == company_id)
    if client_id:
        q = q.where(OrdemProducao.client_id == client_id)
    return session.exec(q.order_by(pri, OrdemProducao.data_fim_plan)).all()

def _roteiro(session, op_id):
    return session.exec(
        select(ProducaoRoteiroPasso)
        .where(ProducaoRoteiroPasso.op_id == op_id)
        .order_by(ProducaoRoteiroPasso.ordem)
    ).all()

def _roteiro_processo_ids(session, op_id) -> set:
    passos = _roteiro(session, op_id)
    return {p.processo_id for p in passos}

def _prioridade_cor(p):
    return _PRIORIDADE_COR.get(p, "#6366f1")

templates_env.filters["_prioridade_cor"] = _prioridade_cor


# ── Template principal ────────────────────────────────────────────────────────

_TPL_PRODUCAO = r"""
{% extends "base.html" %}
{% block title %}Controle de Produção{% endblock %}
{% block content %}
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.3/font/bootstrap-icons.min.css">
<div style="max-width:1400px;margin:0 auto;padding:1.5rem 1rem;">

  <div class="d-flex align-items-center justify-content-between flex-wrap gap-2 mb-3">
    <div>
      <h4 class="mb-0" style="font-weight:700;"><i class="bi bi-kanban me-2" style="color:#6366f1;"></i>Controle de Produção</h4>
      <small class="text-muted">Ordens de Produção · Kanban · PCP</small>
    </div>
    <div class="d-flex gap-2 flex-wrap">
      <button class="btn btn-sm btn-outline-secondary" onclick="showTab('kanban')">&#9783; Kanban</button>
      <button class="btn btn-sm btn-outline-secondary" onclick="showTab('ops')">&#9776; Ordens de Produção</button>
      <button class="btn btn-sm btn-outline-secondary" onclick="showTab('pcp')">&#9650; PCP</button>
      <button class="btn btn-sm btn-outline-secondary" onclick="showTab('materiais_cat')">&#9744; Materiais</button>
      <button class="btn btn-sm btn-outline-secondary" onclick="showTab('processos')">&#9881; Processos</button>
      <button class="btn btn-sm btn-primary" onclick="abrirModalOP(null)" style="background:#6366f1;border-color:#6366f1;">+ Nova OP</button>
    </div>
  </div>

  <!-- KPIs -->
  <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:.75rem;margin-bottom:1.5rem;">
    <div class="kpi-prod" style="border-left:4px solid #6366f1;"><div class="kpi-prod-v">{{ ops|length }}</div><div class="kpi-prod-l">Total de OPs</div></div>
    <div class="kpi-prod" style="border-left:4px solid #f97316;"><div class="kpi-prod-v">{{ ops|selectattr('status','eq','em_andamento')|list|length }}</div><div class="kpi-prod-l">Em Andamento</div></div>
    <div class="kpi-prod" style="border-left:4px solid #16a34a;"><div class="kpi-prod-v">{{ ops|selectattr('status','eq','concluida')|list|length }}</div><div class="kpi-prod-l">Concluídas</div></div>
    <div class="kpi-prod" style="border-left:4px solid #dc2626;"><div class="kpi-prod-v">{{ ops|selectattr('prioridade','eq','urgente')|list|length }}</div><div class="kpi-prod-l">Urgentes</div></div>
  </div>

  <!-- ═══════════════ KANBAN ═══════════════ -->
  <div id="tab-kanban">
    {% if not processos %}
    <div class="alert alert-info"><i class="bi bi-info-circle me-2"></i>Nenhum processo cadastrado. Acesse <b>Processos</b> para configurar as etapas.</div>
    {% else %}
    <div id="kanbanBoard" style="display:flex;gap:1rem;overflow-x:auto;padding-bottom:1rem;align-items:flex-start;">
      {% for proc in processos %}
      {% set proc_ops = ops|selectattr('processo_id','eq',proc.id)|list %}
      <div class="kanban-col" id="col-{{ proc.id }}"
           ondragover="dragOver(event,{{ proc.id }})"
           ondragleave="dragLeave(event)"
           ondrop="dropOP(event,{{ proc.id }})">
        <div class="kanban-col-hdr" style="border-top:3px solid {{ proc.cor }};">
          <span style="font-weight:700;font-size:.9rem;">{{ proc.nome }}</span>
          <span class="badge rounded-pill" style="background:{{ proc.cor }}20;color:{{ proc.cor }};font-size:.75rem;">{{ proc_ops|length }}</span>
        </div>
        {% for op in proc_ops %}
        {% set rids = roteiros.get(op.id, []) %}
        <div class="kanban-card"
             draggable="true"
             ondragstart="dragOP(event,{{ op.id }},{{ rids|tojson }})"
             onclick="abrirModalOP({{ op.id }})">
          <div class="d-flex justify-content-between align-items-start mb-1">
            <span style="font-size:.72rem;color:#94a3b8;font-family:monospace;">{{ op.codigo }}</span>
            <span class="badge" style="font-size:.65rem;background:{{ op.prioridade|_prioridade_cor }}20;color:{{ op.prioridade|_prioridade_cor }};">{{ op.prioridade|upper }}</span>
          </div>
          <div style="font-weight:600;font-size:.85rem;margin-bottom:.25rem;">{{ op.produto }}</div>
          {% if op.descricao %}<div style="font-size:.75rem;color:#64748b;margin-bottom:.3rem;">{{ op.descricao[:55] }}{% if op.descricao|length>55 %}…{% endif %}</div>{% endif %}
          {% if rids %}
          <div style="font-size:.7rem;color:#94a3b8;margin-bottom:.3rem;">
            <i class="bi bi-diagram-3 me-1"></i>
            {% for pid in rids %}{% set pnome = processos_dict.get(pid,'?') %}<span style="margin-right:.25rem;">{{ pnome }}</span>{% if not loop.last %}→{% endif %}{% endfor %}
          </div>
          {% endif %}
          {% if op.quantidade_planejada > 0 %}
          {% set pct = [(op.quantidade_produzida / op.quantidade_planejada * 100)|round|int, 100]|min %}
          <div style="margin:.3rem 0;">
            <div style="display:flex;justify-content:space-between;font-size:.7rem;color:#94a3b8;margin-bottom:2px;">
              <span>{{ op.quantidade_produzida|int }}/{{ op.quantidade_planejada|int }}</span><span>{{ pct }}%</span>
            </div>
            <div style="height:4px;background:#e2e8f0;border-radius:2px;">
              <div style="height:4px;border-radius:2px;width:{{ pct }}%;background:{% if pct>=100 %}#16a34a{% elif pct>=50 %}#f97316{% else %}#6366f1{% endif %};"></div>
            </div>
          </div>
          {% endif %}
          <div class="d-flex gap-2 mt-1" style="font-size:.7rem;color:#94a3b8;">
            {% if op.data_fim_plan %}<span><i class="bi bi-calendar2 me-1"></i>{{ op.data_fim_plan.strftime('%d/%m') }}</span>{% endif %}
            {% if op.responsavel %}<span><i class="bi bi-person me-1"></i>{{ op.responsavel }}</span>{% endif %}
          </div>
        </div>
        {% endfor %}
        {% if proc_ops|length == 0 %}
        <div class="kanban-empty-drop">Arraste OPs aqui</div>
        {% endif %}
      </div>
      {% endfor %}
      <!-- Sem processo -->
      {% set sem_proc = [] %}
      {% for op in ops %}{% if op.processo_id is none %}{% set _ = sem_proc.append(op) %}{% endif %}{% endfor %}
      {% if sem_proc %}
      <div class="kanban-col" id="col-0"
           ondragover="dragOver(event,0)"
           ondragleave="dragLeave(event)"
           ondrop="dropOP(event,null)">
        <div class="kanban-col-hdr" style="border-top:3px solid #94a3b8;">
          <span style="font-weight:700;font-size:.9rem;">Sem etapa</span>
          <span class="badge rounded-pill" style="background:#94a3b820;color:#94a3b8;font-size:.75rem;">{{ sem_proc|length }}</span>
        </div>
        {% for op in sem_proc %}
        {% set rids = roteiros.get(op.id, []) %}
        <div class="kanban-card" draggable="true"
             ondragstart="dragOP(event,{{ op.id }},{{ rids|tojson }})"
             onclick="abrirModalOP({{ op.id }})">
          <div class="d-flex justify-content-between mb-1">
            <span style="font-size:.72rem;color:#94a3b8;font-family:monospace;">{{ op.codigo }}</span>
            <span class="badge" style="font-size:.65rem;background:{{ op.prioridade|_prioridade_cor }}20;color:{{ op.prioridade|_prioridade_cor }};">{{ op.prioridade|upper }}</span>
          </div>
          <div style="font-weight:600;font-size:.85rem;">{{ op.produto }}</div>
        </div>
        {% endfor %}
      </div>
      {% endif %}
    </div>
    {% endif %}
  </div>

  <!-- ═══════════════ LISTA OPs ═══════════════ -->
  <div id="tab-ops" style="display:none;">
    <div class="d-flex gap-2 mb-3 flex-wrap">
      <input type="text" id="filtroOP" class="form-control form-control-sm" placeholder="Buscar OP, produto..." oninput="filtrarOPs()" style="max-width:260px;">
      <input type="text" id="filtroPedido" class="form-control form-control-sm" placeholder="Filtrar por Pedido Nº..." oninput="filtrarOPs()" style="max-width:200px;">
      <select id="filtroStatus" class="form-select form-select-sm" onchange="filtrarOPs()" style="max-width:160px;">
        <option value="">Todos status</option>
        <option value="aberta">Aberta</option>
        <option value="em_andamento">Em andamento</option>
        <option value="concluida">Concluída</option>
        <option value="cancelada">Cancelada</option>
      </select>
    </div>
    <div style="overflow-x:auto;border:1px solid var(--mc-border);border-radius:12px;">
      <table style="width:100%;border-collapse:collapse;font-size:.84rem;" id="tabelaOPs">
        <thead><tr style="background:#6366f1;color:#fff;">
          <th style="padding:.5rem .75rem;">Código</th>
          <th style="padding:.5rem .75rem;">Produto</th>
          <th style="padding:.5rem .75rem;text-align:center;">Etapa atual</th>
          <th style="padding:.5rem .75rem;">Roteiro</th>
          <th style="padding:.5rem .75rem;">Pedido</th>
          <th style="padding:.5rem .75rem;">Cor</th>
          <th style="padding:.5rem .75rem;text-align:center;">Prioridade</th>
          <th style="padding:.5rem .75rem;text-align:right;">Qtd Plan.</th>
          <th style="padding:.5rem .75rem;text-align:right;">Qtd Prod.</th>
          <th style="padding:.5rem .75rem;text-align:center;">Progresso</th>
          <th style="padding:.5rem .75rem;text-align:center;">Fim Plan.</th>
          <th style="padding:.5rem .75rem;text-align:center;">Status</th>
          <th style="padding:.5rem .75rem;text-align:center;">Ações</th>
        </tr></thead>
        <tbody>
          {% for op in ops %}
          {% set proc_nome = processos_dict.get(op.processo_id, '—') %}
          {% set pct = [(op.quantidade_produzida / op.quantidade_planejada * 100)|round|int, 100]|min if op.quantidade_planejada > 0 else 0 %}
          {% set rids = roteiros.get(op.id, []) %}
          <tr class="op-row" data-busca="{{ op.codigo }} {{ op.produto }} {{ op.responsavel }}" data-status="{{ op.status }}" data-pedido="{{ op.pedido|lower }}" style="border-bottom:1px solid #f1f5f9;">
            <td style="padding:.45rem .75rem;font-family:monospace;font-weight:600;color:#6366f1;">{{ op.codigo }}</td>
            <td style="padding:.45rem .75rem;font-weight:600;">{{ op.produto }}<br><small class="text-muted">{{ op.descricao[:40] if op.descricao else '' }}</small></td>
            <td style="padding:.45rem .75rem;text-align:center;"><span style="font-size:.75rem;padding:.15rem .5rem;border-radius:999px;background:#f1f5f9;">{{ proc_nome }}</span></td>
            <td style="padding:.45rem .75rem;">
              {% if rids %}
              <div style="font-size:.75rem;display:flex;flex-wrap:wrap;gap:.2rem;align-items:center;">
                {% for pid in rids %}<span style="background:#eff6ff;color:#6366f1;padding:.1rem .4rem;border-radius:4px;">{{ processos_dict.get(pid,'?') }}</span>{% if not loop.last %}<span style="color:#94a3b8;">→</span>{% endif %}{% endfor %}
              </div>
              {% else %}<span style="color:#94a3b8;font-size:.75rem;">—</span>{% endif %}
            </td>
            <td style="padding:.45rem .75rem;font-size:.8rem;">{{ op.pedido or '—' }}</td>
            <td style="padding:.45rem .75rem;font-size:.8rem;">{{ op.cor or '—' }}</td>
            <td style="padding:.45rem .75rem;text-align:center;"><span class="badge" style="background:{{ op.prioridade|_prioridade_cor }}20;color:{{ op.prioridade|_prioridade_cor }};">{{ op.prioridade|capitalize }}</span></td>
            <td style="padding:.45rem .75rem;text-align:right;">{{ op.quantidade_planejada|int }}</td>
            <td style="padding:.45rem .75rem;text-align:right;">{{ op.quantidade_produzida|int }}</td>
            <td style="padding:.45rem .75rem;text-align:center;min-width:80px;">
              <div style="height:6px;background:#e2e8f0;border-radius:3px;"><div style="height:6px;border-radius:3px;width:{{ pct }}%;background:{% if pct>=100 %}#16a34a{% elif pct>=50 %}#f97316{% else %}#6366f1{% endif %};"></div></div>
              <small style="color:#94a3b8;">{{ pct }}%</small>
            </td>
            <td style="padding:.45rem .75rem;text-align:center;">{{ op.data_fim_plan.strftime('%d/%m/%Y') if op.data_fim_plan else '—' }}</td>
            <td style="padding:.45rem .75rem;text-align:center;"><span class="badge" style="background:{% if op.status=='concluida' %}#dcfce7;color:#16a34a{% elif op.status=='em_andamento' %}#eff6ff;color:#6366f1{% elif op.status=='cancelada' %}#fef2f2;color:#dc2626{% else %}#f8fafc;color:#64748b{% endif %};">{{ op.status|replace('_',' ')|title }}</span></td>
            <td style="padding:.45rem .75rem;text-align:center;">
              <button class="btn btn-sm btn-outline-primary" onclick="abrirModalOP({{ op.id }})" title="Editar" style="font-size:.75rem;padding:.2rem .5rem;">&#9998; Editar</button>
              <button class="btn btn-sm btn-outline-info" onclick="abrirMateriais({{ op.id }},'{{ op.codigo }}')" title="Materiais" style="font-size:.75rem;padding:.2rem .5rem;">&#9744; Mat.</button>
              <a href="/ferramentas/producao/op/{{ op.id }}/imprimir" target="_blank" class="btn btn-sm btn-outline-secondary" title="Imprimir OP" style="font-size:.75rem;padding:.2rem .5rem;">&#128438; PDF</a>
              <button class="btn btn-sm btn-outline-danger" onclick="confirmarExcluirOP({{ op.id }},'{{ op.codigo }}')" title="Excluir" style="font-size:.75rem;padding:.2rem .5rem;">&#128465;</button>
            </td>
          </tr>
          {% else %}
          <tr><td colspan="13" style="padding:2rem;text-align:center;color:#94a3b8;">Nenhuma OP cadastrada.</td></tr>
          {% endfor %}
        </tbody>
      </table>
    </div>
  </div>

  <!-- ═══════════════ PCP ═══════════════ -->
  <div id="tab-pcp" style="display:none;">
    <h6 style="color:#6366f1;font-weight:700;margin-bottom:1rem;"><i class="bi bi-graph-up me-2"></i>Planejamento × Controle da Produção</h6>
    {% set total_plan = ops|sum(attribute='quantidade_planejada') %}
    {% set total_prod = ops|sum(attribute='quantidade_produzida') %}
    {% set pct_geral = [(total_prod / total_plan * 100)|round|int, 100]|min if total_plan > 0 else 0 %}
    <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:.75rem;margin-bottom:1.5rem;">
      <div class="kpi-prod" style="border-left:4px solid #6366f1;"><div class="kpi-prod-v">{{ total_plan|int }}</div><div class="kpi-prod-l">Qtd Total Planejada</div></div>
      <div class="kpi-prod" style="border-left:4px solid #16a34a;"><div class="kpi-prod-v">{{ total_prod|int }}</div><div class="kpi-prod-l">Qtd Total Produzida</div></div>
      <div class="kpi-prod" style="border-left:4px solid #f97316;"><div class="kpi-prod-v">{{ pct_geral }}%</div><div class="kpi-prod-l">Eficiência Geral</div></div>
      {% set n_atrasadas = [] %}{% for op in ops %}{% if op.data_fim_plan and op.status not in ['concluida','cancelada'] and op.data_fim_plan < hoje %}{% set _ = n_atrasadas.append(1) %}{% endif %}{% endfor %}
      <div class="kpi-prod" style="border-left:4px solid #dc2626;"><div class="kpi-prod-v" style="color:#dc2626;">{{ n_atrasadas|length }}</div><div class="kpi-prod-l">OPs Atrasadas</div></div>
    </div>

    <!-- PCP por OP com detalhamento de roteiro -->
    {% for op in ops %}
    {% set rpassos = roteiro_detalhado.get(op.id, []) %}
    {% set pct = [(op.quantidade_produzida / op.quantidade_planejada * 100)|round|int, 100]|min if op.quantidade_planejada > 0 else 0 %}
    {% set desvio = none %}
    {% if op.data_fim_plan and op.data_fim_real %}{% set desvio = (op.data_fim_real - op.data_fim_plan).days %}
    {% elif op.data_fim_plan and op.status not in ['concluida','cancelada'] and op.data_fim_plan < hoje %}{% set desvio = (hoje - op.data_fim_plan).days %}{% endif %}
    <div style="border:1px solid var(--mc-border);border-radius:12px;margin-bottom:1rem;overflow:hidden;">
      <!-- cabeçalho da OP -->
      <div style="background:#1e293b;color:#fff;padding:.6rem 1rem;display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:.5rem;">
        <div>
          <span style="font-family:monospace;font-size:.8rem;color:#94a3b8;">{{ op.codigo }}</span>
          <span style="font-weight:700;margin-left:.75rem;">{{ op.produto }}</span>
        </div>
        <div class="d-flex gap-3" style="font-size:.8rem;">
          <span>Qtd: <b style="color:{% if pct>=100 %}#4ade80{% else %}#fb923c{% endif %};">{{ op.quantidade_produzida|int }}/{{ op.quantidade_planejada|int }} ({{ pct }}%)</b></span>
          {% if desvio is not none %}<span>Prazo: <b style="color:{% if desvio<=0 %}#4ade80{% else %}#f87171{% endif %};">{% if desvio<=0 %}No prazo{% else %}+{{ desvio }}d atraso{% endif %}</b></span>{% endif %}
          <span class="badge" style="background:{% if op.status=='concluida' %}#166534;color:#dcfce7{% elif op.status=='em_andamento' %}#1e3a5f;color:#93c5fd{% else %}#334155;color:#94a3b8{% endif %};">{{ op.status|replace('_',' ')|title }}</span>
        </div>
      </div>
      {% if rpassos %}
      <!-- tabela de roteiro -->
      <div style="overflow-x:auto;">
        <table style="width:100%;border-collapse:collapse;font-size:.82rem;">
          <thead><tr style="background:#f8fafc;border-bottom:1px solid var(--mc-border);">
            <th style="padding:.4rem .75rem;text-align:left;">Etapa</th>
            <th style="padding:.4rem .75rem;text-align:center;">Status</th>
            <th style="padding:.4rem .75rem;text-align:right;background:#6366f110;">Tempo Est. (h)</th>
            <th style="padding:.4rem .75rem;text-align:right;background:#16a34a10;">Tempo Real (h)</th>
            <th style="padding:.4rem .75rem;text-align:center;">Desvio</th>
            <th style="padding:.4rem .75rem;text-align:center;background:#16a34a10;">Entrada Real</th>
            <th style="padding:.4rem .75rem;text-align:center;background:#16a34a10;">Saída Real</th>
            <th style="padding:.4rem .75rem;text-align:center;">Apontar</th>
          </tr></thead>
          <tbody>
            {% for p in rpassos %}
            {% set dh = p.tempo_realizado_h - p.tempo_estimado_h if p.tempo_estimado_h > 0 else none %}
            <tr style="border-bottom:1px solid #f1f5f9;">
              <td style="padding:.4rem .75rem;font-weight:600;">{{ p.proc_nome }}</td>
              <td style="padding:.4rem .75rem;text-align:center;">
                <span class="badge" style="background:{% if p.status=='concluido' %}#dcfce7;color:#16a34a{% elif p.status=='em_andamento' %}#eff6ff;color:#6366f1{% else %}#f8fafc;color:#64748b{% endif %};">
                  {{ p.status|title }}
                </span>
              </td>
              <td style="padding:.4rem .75rem;text-align:right;background:#6366f108;">{{ '%.1f'|format(p.tempo_estimado_h) if p.tempo_estimado_h else '—' }}</td>
              <td style="padding:.4rem .75rem;text-align:right;background:#16a34a08;font-weight:600;">{{ '%.1f'|format(p.tempo_realizado_h) if p.tempo_realizado_h else '—' }}</td>
              <td style="padding:.4rem .75rem;text-align:center;">
                {% if dh is not none and p.tempo_realizado_h > 0 %}
                <span style="font-weight:700;color:{% if dh<=0 %}#16a34a{% elif dh<=2 %}#f97316{% else %}#dc2626{% endif %};">
                  {% if dh<=0 %}{{ '%.1f'|format(dh) }}h{% else %}+{{ '%.1f'|format(dh) }}h{% endif %}
                </span>
                {% else %}—{% endif %}
              </td>
              <td style="padding:.4rem .75rem;text-align:center;background:#16a34a08;">{{ p.data_entrada.strftime('%d/%m %H:%M') if p.data_entrada else '—' }}</td>
              <td style="padding:.4rem .75rem;text-align:center;background:#16a34a08;">{{ p.data_saida.strftime('%d/%m %H:%M') if p.data_saida else '—' }}</td>
              <td style="padding:.4rem .75rem;text-align:center;">
                <button class="btn btn-sm btn-outline-secondary" style="font-size:.7rem;padding:.15rem .4rem;" onclick="apontarPasso({{ p.id }})">
                  <i class="bi bi-pencil-square"></i>
                </button>
              </td>
            </tr>
            {% endfor %}
            <!-- totais -->
            {% set tot_est = rpassos|sum(attribute='tempo_estimado_h') %}
            {% set tot_real = rpassos|sum(attribute='tempo_realizado_h') %}
            <tr style="background:#f8fafc;font-weight:700;border-top:2px solid var(--mc-border);">
              <td style="padding:.4rem .75rem;" colspan="2">Total</td>
              <td style="padding:.4rem .75rem;text-align:right;background:#6366f108;">{{ '%.1f'|format(tot_est) }}h</td>
              <td style="padding:.4rem .75rem;text-align:right;background:#16a34a08;">{{ '%.1f'|format(tot_real) }}h</td>
              <td style="padding:.4rem .75rem;text-align:center;">
                {% set dh_tot = tot_real - tot_est %}
                <span style="color:{% if dh_tot<=0 %}#16a34a{% else %}#dc2626{% endif %};">{% if dh_tot<=0 %}{{ '%.1f'|format(dh_tot) }}h{% else %}+{{ '%.1f'|format(dh_tot) }}h{% endif %}</span>
              </td>
              <td colspan="3"></td>
            </tr>
          </tbody>
        </table>
      </div>
      {% else %}
      <div style="padding:.75rem 1rem;color:#94a3b8;font-size:.83rem;"><i class="bi bi-info-circle me-1"></i>Sem roteiro definido para esta OP.</div>
      {% endif %}
    </div>
    {% else %}
    <p class="text-muted text-center py-4">Nenhuma OP cadastrada.</p>
    {% endfor %}
  </div>

  <!-- ═══════════════ CATÁLOGO DE MATERIAIS ═══════════════ -->
  <div id="tab-materiais_cat" style="display:none;">
    <div class="d-flex align-items-center justify-content-between mb-3">
      <h6 class="mb-0" style="color:#0891b2;font-weight:700;">&#9744; Catálogo de Materiais</h6>
      <button class="btn btn-sm btn-primary" onclick="abrirModalMatCat()" style="background:#0891b2;border-color:#0891b2;">+ Novo Material</button>
    </div>
    {% if mat_catalogo %}
    <div style="overflow-x:auto;border:1px solid var(--mc-border);border-radius:12px;">
      <table style="width:100%;border-collapse:collapse;font-size:.84rem;">
        <thead><tr style="background:#0891b2;color:#fff;">
          <th style="padding:.5rem .75rem;">Material</th>
          <th style="padding:.5rem .75rem;text-align:center;">Unidade</th>
          <th style="padding:.5rem .75rem;text-align:right;">Custo Unit. Padrão (R$)</th>
          <th style="padding:.5rem .75rem;text-align:center;">Ações</th>
        </tr></thead>
        <tbody>
          {% for mc in mat_catalogo %}
          <tr style="border-bottom:1px solid #f1f5f9;">
            <td style="padding:.45rem .75rem;font-weight:600;">{{ mc.nome }}</td>
            <td style="padding:.45rem .75rem;text-align:center;">{{ mc.unidade }}</td>
            <td style="padding:.45rem .75rem;text-align:right;">R$ {{ '%.2f'|format(mc.custo_unitario_padrao) }}</td>
            <td style="padding:.45rem .75rem;text-align:center;">
              <button class="btn btn-sm btn-outline-primary" onclick="abrirModalMatCat({{ mc.id }},'{{ mc.nome|replace("'","\\'")|e }}','{{ mc.unidade }}',{{ mc.custo_unitario_padrao }})" style="font-size:.75rem;padding:.2rem .5rem;">&#9998; Editar</button>
              <button class="btn btn-sm btn-outline-danger" onclick="confirmarExcluirMatCat({{ mc.id }},'{{ mc.nome|e }}')" style="font-size:.75rem;padding:.2rem .5rem;">&#128465;</button>
            </td>
          </tr>
          {% endfor %}
        </tbody>
      </table>
    </div>
    {% else %}
    <div class="alert alert-info">Nenhum material cadastrado no catálogo. Clique em <b>+ Novo Material</b> para começar.</div>
    {% endif %}
  </div>

  <!-- ═══════════════ PROCESSOS ═══════════════ -->
  <div id="tab-processos" style="display:none;">
    <div class="d-flex align-items-center justify-content-between mb-3">
      <h6 class="mb-0" style="color:#6366f1;font-weight:700;"><i class="bi bi-gear me-2"></i>Configurar Etapas do Kanban</h6>
      <button class="btn btn-sm btn-primary" onclick="abrirModalProcesso()" style="background:#6366f1;border-color:#6366f1;">+ Nova Etapa</button>
    </div>
    {% if processos %}
    <div style="display:flex;flex-direction:column;gap:.5rem;max-width:600px;">
      {% for proc in processos %}
      <div style="display:flex;align-items:center;gap:.75rem;padding:.75rem 1rem;border:1px solid var(--mc-border);border-radius:10px;border-left:4px solid {{ proc.cor }};">
        <span style="font-weight:700;min-width:1.5rem;color:#94a3b8;">{{ proc.ordem }}</span>
        <span style="width:14px;height:14px;border-radius:50%;background:{{ proc.cor }};flex-shrink:0;"></span>
        <span style="flex:1;font-weight:600;">{{ proc.nome }}</span>
        <button class="btn btn-sm btn-outline-primary" onclick="abrirModalProcesso({{ proc.id }},'{{ proc.nome }}','{{ proc.cor }}',{{ proc.ordem }})" style="font-size:.75rem;padding:.2rem .5rem;">&#9998; Editar</button>
        <button class="btn btn-sm btn-outline-danger" onclick="confirmarExcluirProcesso({{ proc.id }},'{{ proc.nome }}')" style="font-size:.75rem;padding:.2rem .5rem;">&#128465; Excluir</button>
      </div>
      {% endfor %}
    </div>
    {% else %}
    <div class="alert alert-info"><i class="bi bi-info-circle me-2"></i>Nenhuma etapa cadastrada. Crie etapas para usar o Kanban.</div>
    {% endif %}
  </div>

</div><!-- /container -->

<!-- ═══ MODAL OP ═══ -->
<div class="modal fade" id="modalOP" tabindex="-1">
  <div class="modal-dialog modal-xl">
    <div class="modal-content">
      <div class="modal-header" style="background:#6366f1;color:#fff;">
        <h5 class="modal-title" id="modalOPTitulo"><i class="bi bi-kanban me-2"></i>Nova Ordem de Produção</h5>
        <button type="button" class="btn-close btn-close-white" data-bs-dismiss="modal"></button>
      </div>
      <form id="formOP" method="post">
        <div class="modal-body">
          <div class="row g-3">
            <!-- dados gerais -->
            <div class="col-md-3"><label class="form-label fw-semibold">Código OP *</label>
              <input type="text" name="codigo" id="op_codigo" class="form-control" placeholder="OP-001" required></div>
            <div class="col-md-5"><label class="form-label fw-semibold">Produto *</label>
              <input type="text" name="produto" id="op_produto" class="form-control" placeholder="Nome do produto" required></div>
            <div class="col-md-4"><label class="form-label fw-semibold">Responsável</label>
              <input type="text" name="responsavel" id="op_responsavel" class="form-control"></div>
            <div class="col-md-4"><label class="form-label fw-semibold">Pedido Nº</label>
              <input type="text" name="pedido" id="op_pedido" class="form-control" placeholder="Ex: PED-001"></div>
            <div class="col-md-4"><label class="form-label fw-semibold">Cor</label>
              <input type="text" name="cor" id="op_cor" class="form-control" placeholder="Ex: Preto fosco"></div>
            <div class="col-12"><label class="form-label fw-semibold">Descrição</label>
              <textarea name="descricao" id="op_descricao" class="form-control" rows="2"></textarea></div>
            <div class="col-md-3"><label class="form-label fw-semibold">Prioridade</label>
              <select name="prioridade" id="op_prioridade" class="form-select">
                <option value="baixa">Baixa</option><option value="normal" selected>Normal</option>
                <option value="alta">Alta</option><option value="urgente">Urgente</option>
              </select></div>
            <div class="col-md-3"><label class="form-label fw-semibold">Status</label>
              <select name="status" id="op_status" class="form-select">
                <option value="aberta">Aberta</option><option value="em_andamento">Em andamento</option>
                <option value="concluida">Concluída</option><option value="cancelada">Cancelada</option>
              </select></div>
            <div class="col-md-3"><label class="form-label fw-semibold">Qtd Planejada</label>
              <input type="number" name="quantidade_planejada" id="op_qtd_plan" class="form-control" min="0" step="0.01" value="0"></div>
            <div class="col-md-3"><label class="form-label fw-semibold">Qtd Produzida</label>
              <input type="number" name="quantidade_produzida" id="op_qtd_prod" class="form-control" min="0" step="0.01" value="0"></div>
            <div class="col-md-3"><label class="form-label fw-semibold">Início Planejado</label>
              <input type="date" name="data_inicio_plan" id="op_dt_ini_plan" class="form-control"></div>
            <div class="col-md-3"><label class="form-label fw-semibold">Fim Planejado</label>
              <input type="date" name="data_fim_plan" id="op_dt_fim_plan" class="form-control"></div>
            <div class="col-md-3"><label class="form-label fw-semibold">Início Real</label>
              <input type="date" name="data_inicio_real" id="op_dt_ini_real" class="form-control"></div>
            <div class="col-md-3"><label class="form-label fw-semibold">Fim Real</label>
              <input type="date" name="data_fim_real" id="op_dt_fim_real" class="form-control"></div>
            <div class="col-12"><label class="form-label fw-semibold">Observações</label>
              <textarea name="observacoes" id="op_observacoes" class="form-control" rows="2"></textarea></div>

            <!-- ══ ROTEIRO DE PRODUÇÃO ══ -->
            <div class="col-12">
              <hr>
              <h6 style="color:#6366f1;font-weight:700;margin-bottom:.75rem;"><i class="bi bi-diagram-3 me-2"></i>Roteiro de Produção</h6>
              <p class="text-muted" style="font-size:.83rem;">Selecione as etapas que esta OP vai percorrer e informe o tempo estimado em horas. A OP só poderá ser movida no Kanban para as etapas marcadas aqui.</p>
              <div id="roteiroContainer">
                {% for proc in processos %}
                <div class="roteiro-row d-flex align-items-center gap-3 mb-2 p-2" style="border:1px solid var(--mc-border);border-radius:8px;" id="rot-row-{{ proc.id }}">
                  <div class="form-check mb-0" style="min-width:180px;">
                    <input class="form-check-input rot-check" type="checkbox"
                           name="rot_proc[]" value="{{ proc.id }}"
                           id="rot_check_{{ proc.id }}"
                           onchange="toggleRoteiro({{ proc.id }})">
                    <label class="form-check-label fw-semibold" for="rot_check_{{ proc.id }}">
                      <span style="display:inline-block;width:10px;height:10px;border-radius:50%;background:{{ proc.cor }};margin-right:.4rem;"></span>
                      {{ proc.nome }}
                    </label>
                  </div>
                  <div id="rot-fields-{{ proc.id }}" style="display:none;flex:1;" class="d-flex gap-3 align-items-center flex-wrap">
                    <div>
                      <label style="font-size:.75rem;color:#64748b;">Ordem</label>
                      <input type="number" name="rot_ordem_{{ proc.id }}" id="rot_ordem_{{ proc.id }}"
                             class="form-control form-control-sm" style="width:70px;" min="1" value="{{ loop.index }}">
                    </div>
                    <div>
                      <label style="font-size:.75rem;color:#64748b;">Tempo estimado (h)</label>
                      <input type="number" name="rot_tempo_{{ proc.id }}" id="rot_tempo_{{ proc.id }}"
                             class="form-control form-control-sm" style="width:100px;" min="0" step="0.5" value="0" placeholder="0.0">
                    </div>
                  </div>
                  <div id="rot-fields-disabled-{{ proc.id }}" style="flex:1;">
                    <small class="text-muted">Não inclusa no roteiro desta OP</small>
                  </div>
                </div>
                {% endfor %}
              </div>
            </div>
          </div>
        </div>
        <div class="modal-footer d-flex justify-content-between align-items-center flex-wrap gap-2">
          <div id="op_modal_links" style="display:none;gap:.5rem;" class="d-flex flex-wrap gap-2">
            <a id="op_btn_imprimir" href="#" target="_blank" class="btn btn-sm btn-outline-secondary">&#128438; Imprimir / PDF</a>
            <a id="op_btn_operador" href="#" target="_blank" class="btn btn-sm btn-outline-success">&#128241; Página do Operador</a>
          </div>
          <div class="d-flex gap-2">
            <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Cancelar</button>
            <button type="submit" class="btn btn-primary" style="background:#6366f1;border-color:#6366f1;"><i class="bi bi-check me-1"></i>Salvar</button>
          </div>
        </div>
      </form>
    </div>
  </div>
</div>

<!-- ═══ MODAL PROCESSO ═══ -->
<div class="modal fade" id="modalProcesso" tabindex="-1">
  <div class="modal-dialog modal-sm">
    <div class="modal-content">
      <div class="modal-header" style="background:#6366f1;color:#fff;">
        <h5 class="modal-title" id="modalProcTitulo"><i class="bi bi-gear me-2"></i>Etapa Kanban</h5>
        <button type="button" class="btn-close btn-close-white" data-bs-dismiss="modal"></button>
      </div>
      <form id="formProcesso" method="post" action="/ferramentas/producao/processo/salvar">
        <input type="hidden" name="processo_id" id="proc_id" value="">
        <div class="modal-body">
          <div class="mb-3"><label class="form-label fw-semibold">Nome da etapa *</label>
            <input type="text" name="nome" id="proc_nome" class="form-control" required></div>
          <div class="mb-3"><label class="form-label fw-semibold">Cor</label>
            <input type="color" name="cor" id="proc_cor" class="form-control form-control-color w-100" value="#6366f1"></div>
          <div class="mb-3"><label class="form-label fw-semibold">Ordem</label>
            <input type="number" name="ordem" id="proc_ordem" class="form-control" min="0" value="0"></div>
        </div>
        <div class="modal-footer">
          <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Cancelar</button>
          <button type="submit" class="btn btn-primary" style="background:#6366f1;border-color:#6366f1;"><i class="bi bi-check me-1"></i>Salvar</button>
        </div>
      </form>
    </div>
  </div>
</div>

<!-- ═══ MODAL MATERIAIS ═══ -->
<div class="modal fade" id="modalMateriais" tabindex="-1">
  <div class="modal-dialog modal-lg">
    <div class="modal-content">
      <div class="modal-header" style="background:#0891b2;color:#fff;">
        <h5 class="modal-title"><i class="bi bi-box-seam me-2"></i>Materiais — <span id="matOpNome"></span></h5>
        <button type="button" class="btn-close btn-close-white" data-bs-dismiss="modal"></button>
      </div>
      <div class="modal-body" id="matBody"></div>
    </div>
  </div>
</div>

<!-- ═══ MODAL CATÁLOGO MATERIAL ═══ -->
<div class="modal fade" id="modalMatCat" tabindex="-1">
  <div class="modal-dialog modal-sm">
    <div class="modal-content">
      <div class="modal-header" style="background:#0891b2;color:#fff;">
        <h5 class="modal-title" id="matCatTitulo">+ Novo Material</h5>
        <button type="button" class="btn-close btn-close-white" data-bs-dismiss="modal"></button>
      </div>
      <form id="formMatCat" method="post">
        <input type="hidden" name="mat_cat_id" id="mat_cat_id" value="">
        <div class="modal-body">
          <div class="mb-3"><label class="form-label fw-semibold">Nome do material *</label>
            <input type="text" name="nome" id="mat_cat_nome" class="form-control" required placeholder="Ex: Chapa de aço"></div>
          <div class="mb-3"><label class="form-label fw-semibold">Unidade</label>
            <input type="text" name="unidade" id="mat_cat_unidade" class="form-control" value="un" placeholder="un, kg, m, m²..."></div>
          <div class="mb-3"><label class="form-label fw-semibold">Custo unitário padrão (R$)</label>
            <input type="number" name="custo_unitario_padrao" id="mat_cat_custo" class="form-control" min="0" step="0.01" value="0"></div>
        </div>
        <div class="modal-footer">
          <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Cancelar</button>
          <button type="submit" class="btn btn-primary" style="background:#0891b2;border-color:#0891b2;">Salvar</button>
        </div>
      </form>
    </div>
  </div>
</div>

<!-- ═══ MODAL APONTAR PASSO ═══ -->
<div class="modal fade" id="modalApontar" tabindex="-1">
  <div class="modal-dialog modal-sm">
    <div class="modal-content">
      <div class="modal-header" style="background:#059669;color:#fff;">
        <h5 class="modal-title"><i class="bi bi-clock me-2"></i>Apontar Tempo Real</h5>
        <button type="button" class="btn-close btn-close-white" data-bs-dismiss="modal"></button>
      </div>
      <div class="modal-body">
        <input type="hidden" id="ap_passo_id">
        <div class="mb-3"><label class="form-label fw-semibold">Tempo realizado (horas)</label>
          <input type="number" id="ap_tempo" class="form-control" min="0" step="0.5" placeholder="0.0"></div>
        <div class="mb-3"><label class="form-label fw-semibold">Data/hora entrada</label>
          <input type="datetime-local" id="ap_entrada" class="form-control"></div>
        <div class="mb-3"><label class="form-label fw-semibold">Data/hora saída</label>
          <input type="datetime-local" id="ap_saida" class="form-control"></div>
        <div class="mb-3"><label class="form-label fw-semibold">Status da etapa</label>
          <select id="ap_status" class="form-select">
            <option value="pendente">Pendente</option>
            <option value="em_andamento">Em andamento</option>
            <option value="concluido">Concluído</option>
          </select></div>
      </div>
      <div class="modal-footer">
        <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Cancelar</button>
        <button type="button" class="btn btn-success" onclick="salvarApontamento()"><i class="bi bi-check me-1"></i>Salvar</button>
      </div>
    </div>
  </div>
</div>

<style>
.kpi-prod{background:var(--mc-card);border:1px solid var(--mc-border);border-radius:10px;padding:.85rem 1rem;}
.kpi-prod-v{font-size:1.5rem;font-weight:800;line-height:1;}
.kpi-prod-l{font-size:.75rem;color:#94a3b8;margin-top:.2rem;}
.kanban-col{min-width:260px;max-width:280px;background:var(--mc-bg2,#f8fafc);border:1px solid var(--mc-border);border-radius:12px;padding:.75rem;display:flex;flex-direction:column;gap:.5rem;transition:background .15s;}
.kanban-col.drag-over-ok{background:#eff6ff;border-color:#6366f1;}
.kanban-col.drag-over-no{background:#fef2f2;border-color:#dc2626;}
.kanban-col-hdr{display:flex;justify-content:space-between;align-items:center;padding:.3rem .1rem .6rem;border-bottom:1px solid var(--mc-border);margin-bottom:.25rem;}
.kanban-card{background:var(--mc-card);border:1px solid var(--mc-border);border-radius:8px;padding:.65rem .75rem;cursor:pointer;transition:box-shadow .15s,transform .1s;}
.kanban-card:hover{box-shadow:0 4px 12px rgba(0,0,0,.12);transform:translateY(-1px);}
.kanban-empty-drop{text-align:center;padding:2rem 1rem;color:#cbd5e1;font-size:.8rem;border:2px dashed #e2e8f0;border-radius:8px;}
.btn-icon{padding:.2rem .45rem;font-size:.8rem;}
.roteiro-row{transition:background .1s;}
.roteiro-row.rot-ativa{background:#eff6ff;border-color:#6366f1!important;}
</style>

<script>
// dados dos roteiros por OP vindos do servidor
const _roteirosData = {{ roteiros_json|safe }};

// ── Tabs ──
function showTab(t){
  ['kanban','ops','pcp','materiais_cat','processos'].forEach(id=>document.getElementById('tab-'+id).style.display=id===t?'':'none');
  localStorage.setItem('prodTab',t);
}
(function(){
  const urlTab=new URLSearchParams(location.search).get('tab');
  showTab(urlTab||localStorage.getItem('prodTab')||'kanban');
})();

// ── Drag & Drop com restrição de roteiro ──
let _dragOpId=null, _dragRoteiroIds=[];

function dragOP(e, id, roteiroIds){
  _dragOpId=id;
  _dragRoteiroIds=roteiroIds||[];
  e.dataTransfer.effectAllowed='move';
  // Destaca colunas válidas/inválidas
  document.querySelectorAll('.kanban-col').forEach(col=>{
    const pid=parseInt(col.id.replace('col-',''))||null;
    if(_dragRoteiroIds.length===0){
      // sem roteiro: qualquer coluna ok
      col.classList.remove('drag-over-no');
    } else if(pid && _dragRoteiroIds.includes(pid)){
      col.classList.remove('drag-over-no');
    } else if(pid){
      col.classList.add('drag-over-no');
    }
  });
}

function dragOver(e, processoId){
  if(_dragRoteiroIds.length>0 && processoId && !_dragRoteiroIds.includes(processoId)){
    e.dataTransfer.dropEffect='none';
    return; // não aceita drop
  }
  e.preventDefault();
  document.getElementById('col-'+(processoId||0))?.classList.add('drag-over-ok');
}

function dragLeave(e){
  e.currentTarget.classList.remove('drag-over-ok','drag-over-no');
}

function dropOP(e, processoId){
  e.preventDefault();
  document.querySelectorAll('.kanban-col').forEach(c=>c.classList.remove('drag-over-ok','drag-over-no'));
  if(!_dragOpId) return;
  // Bloqueia drop em etapas fora do roteiro
  if(_dragRoteiroIds.length>0 && processoId && !_dragRoteiroIds.includes(processoId)){
    alert('Esta etapa não faz parte do roteiro desta OP.');
    return;
  }
  fetch('/ferramentas/producao/op/'+_dragOpId+'/mover',{
    method:'POST',
    headers:{'Content-Type':'application/json'},
    body:JSON.stringify({processo_id:processoId})
  }).then(r=>{ if(r.ok) location.reload(); });
}

// ── Roteiro no Modal ──
function toggleRoteiro(procId){
  const chk=document.getElementById('rot_check_'+procId);
  const fields=document.getElementById('rot-fields-'+procId);
  const disabled=document.getElementById('rot-fields-disabled-'+procId);
  const row=document.getElementById('rot-row-'+procId);
  if(chk.checked){
    fields.style.display='flex';
    disabled.style.display='none';
    row.classList.add('rot-ativa');
  } else {
    fields.style.display='none';
    disabled.style.display='';
    row.classList.remove('rot-ativa');
  }
}

function _resetRoteiro(){
  document.querySelectorAll('.rot-check').forEach(c=>{
    c.checked=false;
    toggleRoteiro(parseInt(c.value));
  });
}

function _carregarRoteiro(roteiroPassos){
  _resetRoteiro();
  (roteiroPassos||[]).forEach(p=>{
    const chk=document.getElementById('rot_check_'+p.processo_id);
    if(chk){ chk.checked=true; toggleRoteiro(p.processo_id); }
    const ord=document.getElementById('rot_ordem_'+p.processo_id);
    if(ord) ord.value=p.ordem;
    const tmp=document.getElementById('rot_tempo_'+p.processo_id);
    if(tmp) tmp.value=p.tempo_estimado_h||0;
  });
}

// ── Modal OP ──
function abrirModalOP(id){
  const form=document.getElementById('formOP');
  if(!id){
    document.getElementById('modalOPTitulo').innerHTML='<i class="bi bi-kanban me-2"></i>Nova Ordem de Produção';
    form.action='/ferramentas/producao/op/salvar';
    form.reset();
    _resetRoteiro();
    document.getElementById('op_modal_links').style.display='none';
    return new bootstrap.Modal(document.getElementById('modalOP')).show();
  }
  fetch('/ferramentas/producao/op/'+id+'/json').then(r=>r.json()).then(d=>{
    document.getElementById('modalOPTitulo').innerHTML='<i class="bi bi-pencil me-2"></i>Editar OP — '+d.codigo;
    form.action='/ferramentas/producao/op/'+id+'/salvar';
    ['codigo','produto','descricao','prioridade','status','responsavel','observacoes','pedido','cor'].forEach(f=>{
      const el=document.getElementById('op_'+f); if(el) el.value=d[f]||'';
    });
    document.getElementById('op_qtd_plan').value=d.quantidade_planejada||0;
    document.getElementById('op_qtd_prod').value=d.quantidade_produzida||0;
    ['dt_ini_plan','dt_fim_plan','dt_ini_real','dt_fim_real'].forEach(f=>{
      const map={dt_ini_plan:'data_inicio_plan',dt_fim_plan:'data_fim_plan',dt_ini_real:'data_inicio_real',dt_fim_real:'data_fim_real'};
      const el=document.getElementById('op_'+f); if(el) el.value=d[map[f]]||'';
    });
    // atalhos de impressão e operador
    document.getElementById('op_btn_imprimir').href='/ferramentas/producao/op/'+id+'/imprimir';
    if(d.token){
      document.getElementById('op_btn_operador').href='/op/'+d.token;
      document.getElementById('op_modal_links').style.display='flex';
    }
    _carregarRoteiro(d.roteiro||[]);
    new bootstrap.Modal(document.getElementById('modalOP')).show();
  });
}

// ── Modal Processo ──
function abrirModalProcesso(id,nome,cor,ordem){
  document.getElementById('proc_id').value=id||'';
  document.getElementById('proc_nome').value=nome||'';
  document.getElementById('proc_cor').value=cor||'#6366f1';
  document.getElementById('proc_ordem').value=ordem||0;
  document.getElementById('modalProcTitulo').innerHTML=id?'<i class="bi bi-pencil me-2"></i>Editar Etapa':'<i class="bi bi-plus me-2"></i>Nova Etapa';
  new bootstrap.Modal(document.getElementById('modalProcesso')).show();
}

// ── Materiais ──
function abrirMateriais(opId,nome){
  document.getElementById('matOpNome').textContent=nome;
  document.getElementById('matBody').innerHTML='<div class="text-center py-4"><div class="spinner-border" style="color:#0891b2;"></div></div>';
  new bootstrap.Modal(document.getElementById('modalMateriais')).show();
  fetch('/ferramentas/producao/op/'+opId+'/materiais').then(r=>r.text()).then(html=>{
    document.getElementById('matBody').innerHTML=html;
  });
}

// ── Apontamento de tempo por passo ──
function apontarPasso(passoId){
  document.getElementById('ap_passo_id').value=passoId;
  document.getElementById('ap_tempo').value='';
  document.getElementById('ap_entrada').value='';
  document.getElementById('ap_saida').value='';
  document.getElementById('ap_status').value='em_andamento';
  new bootstrap.Modal(document.getElementById('modalApontar')).show();
}
function salvarApontamento(){
  const pid=document.getElementById('ap_passo_id').value;
  fetch('/ferramentas/producao/passo/'+pid+'/apontar',{
    method:'POST',
    headers:{'Content-Type':'application/json'},
    body:JSON.stringify({
      tempo_realizado_h:parseFloat(document.getElementById('ap_tempo').value)||0,
      data_entrada:document.getElementById('ap_entrada').value||null,
      data_saida:document.getElementById('ap_saida').value||null,
      status:document.getElementById('ap_status').value,
    })
  }).then(r=>{ if(r.ok){ bootstrap.Modal.getInstance(document.getElementById('modalApontar')).hide(); location.reload(); }});
}

// ── Confirmações ──
function confirmarExcluirOP(id,cod){
  if(confirm('Excluir OP '+cod+'?'))
    fetch('/ferramentas/producao/op/'+id+'/excluir',{method:'POST'}).then(r=>{ if(r.ok) location.reload(); });
}
function confirmarExcluirProcesso(id,nome){
  if(confirm('Excluir etapa "'+nome+'"?'))
    fetch('/ferramentas/producao/processo/'+id+'/excluir',{method:'POST'}).then(r=>{ if(r.ok) location.reload(); });
}

// ── Catálogo de Materiais ──
function abrirModalMatCat(id,nome,unidade,custo){
  document.getElementById('mat_cat_id').value=id||'';
  document.getElementById('mat_cat_nome').value=nome||'';
  document.getElementById('mat_cat_unidade').value=unidade||'un';
  document.getElementById('mat_cat_custo').value=custo||0;
  document.getElementById('matCatTitulo').textContent=id?'Editar Material':'+ Novo Material';
  const form=document.getElementById('formMatCat');
  form.action=id?'/ferramentas/producao/material_cat/'+id+'/salvar':'/ferramentas/producao/material_cat/salvar';
  new bootstrap.Modal(document.getElementById('modalMatCat')).show();
}
function confirmarExcluirMatCat(id,nome){
  if(confirm('Excluir "'+nome+'" do catálogo?'))
    fetch('/ferramentas/producao/material_cat/'+id+'/excluir',{method:'POST'}).then(r=>{ if(r.ok) location.reload(); });
}

// ── Filtro OPs ──
function filtrarOPs(){
  const txt=(document.getElementById('filtroOP').value||'').toLowerCase();
  const st=document.getElementById('filtroStatus').value;
  const ped=(document.getElementById('filtroPedido').value||'').toLowerCase();
  document.querySelectorAll('.op-row').forEach(tr=>{
    const ok=((!txt||(tr.dataset.busca||'').toLowerCase().includes(txt))
             &&(!st||tr.dataset.status===st)
             &&(!ped||(tr.dataset.pedido||'').includes(ped)));
    tr.style.display=ok?'':'none';
  });
}
</script>
{% endblock %}
"""


# ── Template Materiais (partial) ──────────────────────────────────────────────

_TPL_MATERIAIS = r"""
<div style="font-size:.85rem;">
  {% if materiais %}
  <div style="overflow-x:auto;margin-bottom:1rem;">
    <table style="width:100%;border-collapse:collapse;font-size:.83rem;">
      <thead><tr style="background:#0891b2;color:#fff;">
        <th style="padding:.4rem .65rem;">Material</th>
        <th style="padding:.4rem .65rem;text-align:center;">Unid.</th>
        <th style="padding:.4rem .65rem;text-align:right;">Qtd Plan.</th>
        <th style="padding:.4rem .65rem;text-align:right;">Qtd Consumida</th>
        <th style="padding:.4rem .65rem;text-align:right;">Custo Unit.</th>
        <th style="padding:.4rem .65rem;text-align:right;">Custo Total</th>
        <th style="padding:.4rem .65rem;text-align:center;">Ações</th>
      </tr></thead>
      <tbody>
        {% for m in materiais %}
        <tr style="border-bottom:1px solid #f1f5f9;">
          <td style="padding:.4rem .65rem;font-weight:600;">{{ m.nome }}</td>
          <td style="padding:.4rem .65rem;text-align:center;">{{ m.unidade }}</td>
          <td style="padding:.4rem .65rem;text-align:right;">{{ m.quantidade_planejada }}</td>
          <td style="padding:.4rem .65rem;text-align:right;font-weight:600;">{{ m.quantidade_consumida }}</td>
          <td style="padding:.4rem .65rem;text-align:right;">R$ {{ '%.2f'|format(m.custo_unitario) }}</td>
          <td style="padding:.4rem .65rem;text-align:right;color:#0891b2;font-weight:700;">R$ {{ '%.2f'|format(m.quantidade_consumida * m.custo_unitario) }}</td>
          <td style="padding:.4rem .65rem;text-align:center;">
            <button class="btn btn-sm btn-outline-danger" onclick="excluirMaterial({{ m.id }},{{ op_id }})" style="font-size:.75rem;padding:.2rem .45rem;">&#128465;</button>
          </td>
        </tr>
        {% endfor %}
        <tr style="background:#f8fafc;font-weight:700;border-top:2px solid #e2e8f0;">
          <td colspan="5" style="padding:.4rem .65rem;">Total Consumido</td>
          <td style="padding:.4rem .65rem;text-align:right;color:#0891b2;">R$ {{ '%.2f'|format(materiais|sum(attribute='quantidade_consumida') * 0 + materiais|map(attribute='quantidade_consumida')|list|sum) }}</td>
          <td></td>
        </tr>
      </tbody>
    </table>
  </div>
  {% else %}
  <p class="text-muted text-center py-3">Nenhum material cadastrado para esta OP.</p>
  {% endif %}
  <hr>
  <h6 style="color:#0891b2;font-weight:700;">+ Adicionar Material</h6>
  {% if catalogo %}
  <div style="margin-bottom:.75rem;">
    <label style="font-size:.8rem;color:#64748b;font-weight:600;">Selecionar do catálogo (opcional):</label>
    <select id="mat_cat_sel" class="form-select form-select-sm" onchange="preencherDoCatalogo()" style="max-width:320px;">
      <option value="">— digitar manualmente —</option>
      {% for c in catalogo %}<option value="{{ c.id }}" data-nome="{{ c.nome }}" data-un="{{ c.unidade }}" data-custo="{{ c.custo_unitario_padrao }}">{{ c.nome }} ({{ c.unidade }})</option>{% endfor %}
    </select>
  </div>
  {% endif %}
  <form onsubmit="salvarMaterial(event,{{ op_id }})">
    <div class="row g-2 align-items-end">
      <div class="col-md-4">
        <label class="form-label form-label-sm fw-semibold mb-1" style="font-size:.78rem;">Material *</label>
        <input type="text" id="mat_nome" class="form-control form-control-sm" placeholder="Nome do material" required>
      </div>
      <div class="col-md-2">
        <label class="form-label form-label-sm fw-semibold mb-1" style="font-size:.78rem;">Unidade</label>
        <input type="text" id="mat_unidade" class="form-control form-control-sm" placeholder="un" value="un">
      </div>
      <div class="col-md-2">
        <label class="form-label form-label-sm fw-semibold mb-1" style="font-size:.78rem;">Qtd Planejada</label>
        <input type="number" id="mat_qtd_plan" class="form-control form-control-sm" min="0" step="0.001" value="0">
      </div>
      <div class="col-md-2">
        <label class="form-label form-label-sm fw-semibold mb-1" style="font-size:.78rem;">Qtd Consumida</label>
        <input type="number" id="mat_qtd_cons" class="form-control form-control-sm" min="0" step="0.001" value="0">
      </div>
      <div class="col-md-2">
        <label class="form-label form-label-sm fw-semibold mb-1" style="font-size:.78rem;">Custo Unit. R$</label>
        <input type="number" id="mat_custo" class="form-control form-control-sm" min="0" step="0.01" value="0">
      </div>
      <div class="col-12">
        <button type="submit" class="btn btn-sm btn-primary" style="background:#0891b2;border-color:#0891b2;">+ Adicionar</button>
      </div>
    </div>
  </form>
</div>
<script>
function preencherDoCatalogo(){
  const sel=document.getElementById('mat_cat_sel');
  const opt=sel.options[sel.selectedIndex];
  if(!opt.value) return;
  document.getElementById('mat_nome').value=opt.dataset.nome||'';
  document.getElementById('mat_unidade').value=opt.dataset.un||'un';
  document.getElementById('mat_custo').value=opt.dataset.custo||0;
}
function salvarMaterial(e,opId){
  e.preventDefault();
  fetch('/ferramentas/producao/op/'+opId+'/material/salvar',{
    method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({nome:document.getElementById('mat_nome').value,unidade:document.getElementById('mat_unidade').value,
      quantidade_planejada:parseFloat(document.getElementById('mat_qtd_plan').value)||0,
      quantidade_consumida:parseFloat(document.getElementById('mat_qtd_cons').value)||0,
      custo_unitario:parseFloat(document.getElementById('mat_custo').value)||0})
  }).then(r=>{ if(r.ok) location.reload(); });
}
function excluirMaterial(mid,opId){
  if(confirm('Excluir material?'))
    fetch('/ferramentas/producao/material/'+mid+'/excluir',{method:'POST'}).then(r=>{ if(r.ok) location.reload(); });
}
</script>
"""

_TPL_IMPRIMIR = r"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>OP {{ op.codigo }}</title>
<style>
*{box-sizing:border-box;margin:0;padding:0;}
body{font-family:Arial,sans-serif;font-size:13px;color:#111;background:#fff;padding:24px;}
h1{font-size:18px;font-weight:700;margin-bottom:4px;}
.sub{color:#555;font-size:12px;margin-bottom:16px;}
table{width:100%;border-collapse:collapse;margin-bottom:16px;}
th,td{border:1px solid #ccc;padding:5px 8px;text-align:left;}
th{background:#f0f0f0;font-weight:700;}
.badge{display:inline-block;padding:2px 8px;border-radius:99px;font-size:11px;font-weight:700;}
.qr-wrap{text-align:right;float:right;margin-left:16px;}
.qr-wrap img{width:120px;height:120px;}
.qr-label{font-size:10px;color:#666;text-align:center;margin-top:4px;}
.op-link{font-size:11px;color:#555;word-break:break-all;}
@media print{body{padding:10px;} .no-print{display:none;}}
</style>
</head>
<body>
<div class="no-print" style="margin-bottom:12px;">
  <button onclick="window.print()" style="padding:6px 16px;background:#6366f1;color:#fff;border:none;border-radius:6px;cursor:pointer;font-size:13px;">&#128438; Imprimir / Salvar PDF</button>
</div>
{% if qr_b64 %}
<div class="qr-wrap">
  <img src="data:image/png;base64,{{ qr_b64 }}" alt="QR Code OP">
  <div class="qr-label">Digitalizar para operar</div>
  <div class="op-link">{{ op_url }}</div>
</div>
{% endif %}
<h1>Ordem de Produção — {{ op.codigo }}</h1>
<div class="sub">Emitido em {{ hoje }}</div>
<table>
  <tr><th style="width:120px;">Produto</th><td colspan="3">{{ op.produto }}</td></tr>
  {% if op.descricao %}<tr><th>Descrição</th><td colspan="3">{{ op.descricao }}</td></tr>{% endif %}
  {% if op.pedido %}<tr><th>Pedido Nº</th><td>{{ op.pedido }}</td><th>Cor</th><td>{{ op.cor or '—' }}</td></tr>{% endif %}
  <tr>
    <th>Prioridade</th><td>{{ op.prioridade|capitalize }}</td>
    <th>Status</th><td>{{ op.status|replace('_',' ')|title }}</td>
  </tr>
  <tr>
    <th>Qtd Planejada</th><td>{{ op.quantidade_planejada|int }}</td>
    <th>Qtd Produzida</th><td>{{ op.quantidade_produzida|int }}</td>
  </tr>
  <tr>
    <th>Início Plan.</th><td>{{ op.data_inicio_plan.strftime('%d/%m/%Y') if op.data_inicio_plan else '—' }}</td>
    <th>Fim Plan.</th><td>{{ op.data_fim_plan.strftime('%d/%m/%Y') if op.data_fim_plan else '—' }}</td>
  </tr>
  {% if op.responsavel %}<tr><th>Responsável</th><td colspan="3">{{ op.responsavel }}</td></tr>{% endif %}
  {% if op.observacoes %}<tr><th>Observações</th><td colspan="3">{{ op.observacoes }}</td></tr>{% endif %}
</table>
{% if roteiro %}
<h2 style="font-size:14px;font-weight:700;margin-bottom:8px;">Roteiro de Produção</h2>
<table>
  <thead><tr><th>#</th><th>Etapa</th><th>Tempo Est. (h)</th><th>Tempo Real (h)</th><th>Status</th></tr></thead>
  <tbody>
  {% for p in roteiro %}
  <tr>
    <td>{{ p.ordem }}</td>
    <td>{{ p.proc_nome }}</td>
    <td style="text-align:right;">{{ '%.1f'|format(p.tempo_estimado_h) if p.tempo_estimado_h else '—' }}</td>
    <td style="text-align:right;">{{ '%.1f'|format(p.tempo_realizado_h) if p.tempo_realizado_h else '—' }}</td>
    <td>{{ p.status|title }}</td>
  </tr>
  {% endfor %}
  </tbody>
</table>
{% endif %}
{% if materiais %}
<h2 style="font-size:14px;font-weight:700;margin-bottom:8px;">Materiais</h2>
<table>
  <thead><tr><th>Material</th><th>Unid.</th><th style="text-align:right;">Qtd Plan.</th><th style="text-align:right;">Qtd Cons.</th><th style="text-align:right;">Custo Unit.</th><th style="text-align:right;">Total</th></tr></thead>
  <tbody>
  {% for m in materiais %}
  <tr>
    <td>{{ m.nome }}</td><td>{{ m.unidade }}</td>
    <td style="text-align:right;">{{ m.quantidade_planejada }}</td>
    <td style="text-align:right;">{{ m.quantidade_consumida }}</td>
    <td style="text-align:right;">R$ {{ '%.2f'|format(m.custo_unitario) }}</td>
    <td style="text-align:right;">R$ {{ '%.2f'|format(m.quantidade_consumida * m.custo_unitario) }}</td>
  </tr>
  {% endfor %}
  </tbody>
</table>
{% endif %}
</body>
</html>
"""

_TPL_OPERADOR = r"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1">
<title>OP {{ op.codigo }} — Operador</title>
<style>
*{box-sizing:border-box;margin:0;padding:0;}
body{font-family:Arial,sans-serif;background:#0f172a;color:#f1f5f9;min-height:100vh;padding:16px;}
h1{font-size:20px;font-weight:700;margin-bottom:4px;}
.sub{color:#94a3b8;font-size:13px;margin-bottom:20px;}
.card{background:#1e293b;border-radius:12px;padding:16px;margin-bottom:12px;}
.card h2{font-size:15px;font-weight:700;margin-bottom:4px;}
.badge{display:inline-block;padding:3px 10px;border-radius:99px;font-size:12px;font-weight:700;}
.badge-pend{background:#334155;color:#94a3b8;}
.badge-and{background:#1e3a5f;color:#93c5fd;}
.badge-ok{background:#166534;color:#4ade80;}
.btn{display:block;width:100%;padding:14px;border:none;border-radius:10px;font-size:16px;font-weight:700;cursor:pointer;margin-top:10px;letter-spacing:.3px;}
.btn-start{background:#6366f1;color:#fff;}
.btn-stop{background:#dc2626;color:#fff;}
.btn:disabled{opacity:.4;cursor:not-allowed;}
.info-row{display:flex;justify-content:space-between;font-size:13px;color:#94a3b8;margin-bottom:6px;}
.info-val{color:#f1f5f9;font-weight:600;}
</style>
</head>
<body>
<div style="max-width:480px;margin:0 auto;">
  <h1>OP {{ op.codigo }}</h1>
  <div class="sub">{{ op.produto }}{% if op.pedido %} · Pedido: {{ op.pedido }}{% endif %}{% if op.cor %} · Cor: {{ op.cor }}{% endif %}</div>
  <div class="card">
    <div class="info-row"><span>Prioridade</span><span class="info-val">{{ op.prioridade|capitalize }}</span></div>
    <div class="info-row"><span>Qtd Plan.</span><span class="info-val">{{ op.quantidade_planejada|int }}</span></div>
    <div class="info-row"><span>Qtd Prod.</span><span class="info-val">{{ op.quantidade_produzida|int }}</span></div>
    {% if op.data_fim_plan %}<div class="info-row"><span>Prazo</span><span class="info-val">{{ op.data_fim_plan.strftime('%d/%m/%Y') }}</span></div>{% endif %}
  </div>
  {% for p in roteiro %}
  <div class="card" id="card-{{ p.id }}">
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;">
      <h2>{{ loop.index }}. {{ p.proc_nome }}</h2>
      <span class="badge {% if p.status=='concluido' %}badge-ok{% elif p.status=='em_andamento' %}badge-and{% else %}badge-pend{% endif %}" id="badge-{{ p.id }}">
        {{ p.status|title }}
      </span>
    </div>
    {% if p.tempo_estimado_h %}<div class="info-row"><span>Tempo estimado</span><span class="info-val">{{ '%.1f'|format(p.tempo_estimado_h) }}h</span></div>{% endif %}
    {% if p.data_entrada %}<div class="info-row"><span>Entrada</span><span class="info-val" id="entrada-{{ p.id }}">{{ p.data_entrada.strftime('%d/%m %H:%M') }}</span></div>{% endif %}
    {% if p.status == 'pendente' %}
    <button class="btn btn-start" onclick="iniciar({{ p.id }})">&#9654; Iniciar etapa</button>
    {% elif p.status == 'em_andamento' %}
    <button class="btn btn-stop" onclick="finalizar({{ p.id }})">&#9632; Finalizar etapa</button>
    {% else %}
    <button class="btn btn-start" disabled>&#10003; Concluído</button>
    {% endif %}
  </div>
  {% else %}
  <div class="card"><p style="color:#94a3b8;text-align:center;">Sem roteiro definido para esta OP.</p></div>
  {% endfor %}
</div>
<script>
const _tok='{{ op.token }}';
function iniciar(pid){
  fetch('/op/'+_tok+'/passo/'+pid+'/iniciar',{method:'POST'}).then(r=>r.json()).then(d=>{
    if(d.ok) location.reload();
    else alert(d.error||'Erro');
  });
}
function finalizar(pid){
  fetch('/op/'+_tok+'/passo/'+pid+'/finalizar',{method:'POST'}).then(r=>r.json()).then(d=>{
    if(d.ok) location.reload();
    else alert(d.error||'Erro');
  });
}
</script>
</body>
</html>
"""

TEMPLATES["producao.html"] = _TPL_PRODUCAO
TEMPLATES["producao_materiais.html"] = _TPL_MATERIAIS
TEMPLATES["producao_imprimir.html"] = _TPL_IMPRIMIR
TEMPLATES["producao_operador.html"] = _TPL_OPERADOR


# ── Acesso ────────────────────────────────────────────────────────────────────

def _producao_permitida(ctx, session) -> bool:
    if ctx.membership.role in ("admin", "equipe"):
        return True
    try:
        client_id = getattr(ctx.membership, "client_id", None)
        if not client_id:
            return False
        # Usa o mesmo sistema de AssinaturaFeature dos outros módulos
        try:
            return _feature_ativa(session, ctx.company.id, client_id, "producao_kanban")
        except NameError:
            pass
        # Fallback: verifica lista antiga de permissões
        allowed = get_client_allowed_features(session, company_id=ctx.company.id, client_id=client_id)
        return bool(allowed and "producao_kanban" in allowed)
    except Exception:
        return False


# ── Rota principal ────────────────────────────────────────────────────────────

@app.get("/ferramentas/producao", response_class=HTMLResponse)
@require_login
async def producao_index(request: Request, session: Session = Depends(get_session)):
    ctx = get_tenant_context(request, session)
    if not ctx:
        return RedirectResponse("/login", status_code=303)
    if not _producao_permitida(ctx, session):
        return RedirectResponse("/ferramentas", status_code=303)

    current_client = _resolve_client(request, session, ctx)
    cid = ctx.company.id
    clid = current_client.id if current_client else None

    procs = _processos(session, cid, clid)
    all_ops = _ops(session, cid, clid)
    procs_dict = {p.id: p.nome for p in procs}

    roteiros = {}
    roteiro_detalhado = {}
    for op in all_ops:
        passos = _roteiro(session, op.id)
        roteiros[op.id] = [p.processo_id for p in passos]
        det = []
        for p in passos:
            proc = session.get(ProducaoProcesso, p.processo_id)
            det.append({
                "id": p.id,
                "processo_id": p.processo_id,
                "proc_nome": proc.nome if proc else "?",
                "ordem": p.ordem,
                "tempo_estimado_h": p.tempo_estimado_h,
                "tempo_realizado_h": p.tempo_realizado_h,
                "data_entrada": p.data_entrada,
                "data_saida": p.data_saida,
                "status": p.status,
            })
        roteiro_detalhado[op.id] = det

    import json as _json
    roteiros_json = _json.dumps({str(k): v for k, v in roteiros.items()})

    mat_q = select(ProducaoMaterialCatalogo).where(ProducaoMaterialCatalogo.company_id == cid)
    if clid:
        mat_q = mat_q.where(ProducaoMaterialCatalogo.client_id == clid)
    mat_catalogo = session.exec(mat_q.order_by(ProducaoMaterialCatalogo.nome)).all()

    return render("producao.html", request=request, context={
        **_ctx_base(ctx, current_client),
        "processos": procs,
        "processos_dict": procs_dict,
        "ops": all_ops,
        "roteiros": roteiros,
        "roteiro_detalhado": roteiro_detalhado,
        "roteiros_json": roteiros_json,
        "mat_catalogo": mat_catalogo,
        "hoje": date.today(),
        "_prioridade_cor": _prioridade_cor,
    })


# ── OP: helpers de parse ──────────────────────────────────────────────────────

def _parse_date(s):
    try: return date.fromisoformat(s) if s else None
    except: return None

def _salvar_roteiro(session, op_id, form):
    """Lê rot_proc[], rot_ordem_X, rot_tempo_X do form e salva os passos."""
    # Remove passos anteriores
    old = session.exec(select(ProducaoRoteiroPasso).where(ProducaoRoteiroPasso.op_id == op_id)).all()
    for p in old:
        session.delete(p)
    session.flush()

    proc_ids = form.getlist("rot_proc[]")
    for pid_str in proc_ids:
        try:
            pid = int(pid_str)
        except ValueError:
            continue
        ordem = int(form.get(f"rot_ordem_{pid}", 0) or 0)
        tempo = float(form.get(f"rot_tempo_{pid}", 0) or 0)
        passo = ProducaoRoteiroPasso(
            op_id=op_id, processo_id=pid, ordem=ordem, tempo_estimado_h=tempo
        )
        session.add(passo)
    session.commit()


# ── OP: salvar novo ───────────────────────────────────────────────────────────

@app.post("/ferramentas/producao/op/salvar", response_class=HTMLResponse)
@require_login
async def producao_op_salvar(request: Request, session: Session = Depends(get_session)):
    ctx = get_tenant_context(request, session)
    if not ctx:
        return RedirectResponse("/login", status_code=303)
    current_client = _resolve_client(request, session, ctx)
    form = await request.form()
    op = OrdemProducao(
        company_id=ctx.company.id,
        client_id=current_client.id if current_client else None,
        codigo=(form.get("codigo") or "").strip(),
        produto=(form.get("produto") or "").strip(),
        descricao=(form.get("descricao") or "").strip(),
        processo_id=int(form["processo_id"]) if form.get("processo_id") else None,
        prioridade=form.get("prioridade", "normal"),
        status=form.get("status", "aberta"),
        quantidade_planejada=float(form.get("quantidade_planejada") or 0),
        quantidade_produzida=float(form.get("quantidade_produzida") or 0),
        data_inicio_plan=_parse_date(form.get("data_inicio_plan")),
        data_fim_plan=_parse_date(form.get("data_fim_plan")),
        data_inicio_real=_parse_date(form.get("data_inicio_real")),
        data_fim_real=_parse_date(form.get("data_fim_real")),
        responsavel=(form.get("responsavel") or "").strip(),
        observacoes=(form.get("observacoes") or "").strip(),
        cor=(form.get("cor") or "").strip(),
        pedido=(form.get("pedido") or "").strip(),
        updated_at=datetime.utcnow(),
    )
    session.add(op); session.commit(); session.refresh(op)
    _salvar_roteiro(session, op.id, form)
    return RedirectResponse("/ferramentas/producao", status_code=303)


# ── OP: editar ────────────────────────────────────────────────────────────────

@app.post("/ferramentas/producao/op/{op_id}/salvar", response_class=HTMLResponse)
@require_login
async def producao_op_editar(op_id: int, request: Request, session: Session = Depends(get_session)):
    ctx = get_tenant_context(request, session)
    if not ctx:
        return RedirectResponse("/login", status_code=303)
    op = session.get(OrdemProducao, op_id)
    if not op or op.company_id != ctx.company.id:
        return RedirectResponse("/ferramentas/producao", status_code=303)
    form = await request.form()
    op.codigo = (form.get("codigo") or "").strip()
    op.produto = (form.get("produto") or "").strip()
    op.descricao = (form.get("descricao") or "").strip()
    op.processo_id = int(form["processo_id"]) if form.get("processo_id") else None
    op.prioridade = form.get("prioridade", "normal")
    op.status = form.get("status", "aberta")
    op.quantidade_planejada = float(form.get("quantidade_planejada") or 0)
    op.quantidade_produzida = float(form.get("quantidade_produzida") or 0)
    op.data_inicio_plan = _parse_date(form.get("data_inicio_plan"))
    op.data_fim_plan = _parse_date(form.get("data_fim_plan"))
    op.data_inicio_real = _parse_date(form.get("data_inicio_real"))
    op.data_fim_real = _parse_date(form.get("data_fim_real"))
    op.responsavel = (form.get("responsavel") or "").strip()
    op.observacoes = (form.get("observacoes") or "").strip()
    op.cor = (form.get("cor") or "").strip()
    op.pedido = (form.get("pedido") or "").strip()
    op.updated_at = datetime.utcnow()
    session.add(op); session.commit()
    _salvar_roteiro(session, op_id, form)
    return RedirectResponse("/ferramentas/producao", status_code=303)


# ── OP: JSON ──────────────────────────────────────────────────────────────────

@app.get("/ferramentas/producao/op/{op_id}/json")
@require_login
async def producao_op_json(op_id: int, request: Request, session: Session = Depends(get_session)):
    ctx = get_tenant_context(request, session)
    if not ctx:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    op = session.get(OrdemProducao, op_id)
    if not op or op.company_id != ctx.company.id:
        return JSONResponse({"error": "not found"}, status_code=404)
    passos = _roteiro(session, op_id)
    return JSONResponse({
        "id": op.id, "codigo": op.codigo, "produto": op.produto,
        "descricao": op.descricao, "processo_id": op.processo_id,
        "prioridade": op.prioridade, "status": op.status,
        "quantidade_planejada": op.quantidade_planejada,
        "quantidade_produzida": op.quantidade_produzida,
        "data_inicio_plan": op.data_inicio_plan.isoformat() if op.data_inicio_plan else "",
        "data_fim_plan": op.data_fim_plan.isoformat() if op.data_fim_plan else "",
        "data_inicio_real": op.data_inicio_real.isoformat() if op.data_inicio_real else "",
        "data_fim_real": op.data_fim_real.isoformat() if op.data_fim_real else "",
        "responsavel": op.responsavel, "observacoes": op.observacoes,
        "cor": op.cor, "pedido": op.pedido, "token": op.token,
        "roteiro": [{"processo_id": p.processo_id, "ordem": p.ordem,
                     "tempo_estimado_h": p.tempo_estimado_h} for p in passos],
    })


# ── OP: mover no Kanban ───────────────────────────────────────────────────────

@app.post("/ferramentas/producao/op/{op_id}/mover")
@require_login
async def producao_op_mover(op_id: int, request: Request, session: Session = Depends(get_session)):
    ctx = get_tenant_context(request, session)
    if not ctx:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    body = await request.json()
    op = session.get(OrdemProducao, op_id)
    if not op or op.company_id != ctx.company.id:
        return JSONResponse({"error": "not found"}, status_code=404)
    pid = body.get("processo_id")
    # Valida roteiro no servidor também
    if pid:
        rids = _roteiro_processo_ids(session, op_id)
        if rids and int(pid) not in rids:
            return JSONResponse({"error": "not in roteiro"}, status_code=400)
    op.processo_id = int(pid) if pid else None
    if pid and op.status == "aberta":
        op.status = "em_andamento"
        # Marca entrada no passo do roteiro
        passo = session.exec(
            select(ProducaoRoteiroPasso)
            .where(ProducaoRoteiroPasso.op_id == op_id, ProducaoRoteiroPasso.processo_id == int(pid))
        ).first()
        if passo and not passo.data_entrada:
            passo.data_entrada = datetime.utcnow()
            passo.status = "em_andamento"
            session.add(passo)
    op.updated_at = datetime.utcnow()
    session.add(op); session.commit()
    return JSONResponse({"ok": True})


# ── OP: excluir ──────────────────────────────────────────────────────────────

@app.post("/ferramentas/producao/op/{op_id}/excluir")
@require_login
async def producao_op_excluir(op_id: int, request: Request, session: Session = Depends(get_session)):
    ctx = get_tenant_context(request, session)
    if not ctx:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    op = session.get(OrdemProducao, op_id)
    if not op or op.company_id != ctx.company.id:
        return JSONResponse({"error": "not found"}, status_code=404)
    for m in session.exec(select(ProducaoMaterial).where(ProducaoMaterial.op_id == op_id)).all():
        session.delete(m)
    for p in session.exec(select(ProducaoRoteiroPasso).where(ProducaoRoteiroPasso.op_id == op_id)).all():
        session.delete(p)
    session.delete(op); session.commit()
    return JSONResponse({"ok": True})


# ── Passo: apontar tempo real ─────────────────────────────────────────────────

@app.post("/ferramentas/producao/passo/{passo_id}/apontar")
@require_login
async def producao_passo_apontar(passo_id: int, request: Request, session: Session = Depends(get_session)):
    ctx = get_tenant_context(request, session)
    if not ctx:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    passo = session.get(ProducaoRoteiroPasso, passo_id)
    if not passo:
        return JSONResponse({"error": "not found"}, status_code=404)
    # Verifica que a OP pertence à empresa
    op = session.get(OrdemProducao, passo.op_id)
    if not op or op.company_id != ctx.company.id:
        return JSONResponse({"error": "forbidden"}, status_code=403)
    body = await request.json()
    passo.tempo_realizado_h = float(body.get("tempo_realizado_h") or 0)
    passo.status = body.get("status", passo.status)
    if body.get("data_entrada"):
        try: passo.data_entrada = datetime.fromisoformat(body["data_entrada"])
        except: pass
    if body.get("data_saida"):
        try: passo.data_saida = datetime.fromisoformat(body["data_saida"])
        except: pass
    session.add(passo); session.commit()
    return JSONResponse({"ok": True})


# ── Processo: salvar ──────────────────────────────────────────────────────────

@app.post("/ferramentas/producao/processo/salvar", response_class=HTMLResponse)
@require_login
async def producao_processo_salvar(request: Request, session: Session = Depends(get_session),
    processo_id: str = Form(""), nome: str = Form(...), cor: str = Form("#6366f1"), ordem: int = Form(0)):
    ctx = get_tenant_context(request, session)
    if not ctx:
        return RedirectResponse("/login", status_code=303)
    if processo_id:
        proc = session.get(ProducaoProcesso, int(processo_id))
        if proc and proc.company_id == ctx.company.id:
            proc.nome = nome.strip(); proc.cor = cor; proc.ordem = ordem
            session.add(proc)
    else:
        current_client = _resolve_client(request, session, ctx)
        session.add(ProducaoProcesso(
            company_id=ctx.company.id,
            client_id=current_client.id if current_client else None,
            nome=nome.strip(), cor=cor, ordem=ordem,
        ))
    session.commit()
    return RedirectResponse("/ferramentas/producao", status_code=303)


# ── Processo: excluir ─────────────────────────────────────────────────────────

@app.post("/ferramentas/producao/processo/{proc_id}/excluir")
@require_login
async def producao_processo_excluir(proc_id: int, request: Request, session: Session = Depends(get_session)):
    ctx = get_tenant_context(request, session)
    if not ctx:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    proc = session.get(ProducaoProcesso, proc_id)
    if not proc or proc.company_id != ctx.company.id:
        return JSONResponse({"error": "not found"}, status_code=404)
    for op in session.exec(select(OrdemProducao).where(OrdemProducao.processo_id == proc_id)).all():
        op.processo_id = None; session.add(op)
    for p in session.exec(select(ProducaoRoteiroPasso).where(ProducaoRoteiroPasso.processo_id == proc_id)).all():
        session.delete(p)
    session.delete(proc); session.commit()
    return JSONResponse({"ok": True})


# ── Materiais ─────────────────────────────────────────────────────────────────

@app.get("/ferramentas/producao/op/{op_id}/materiais", response_class=HTMLResponse)
@require_login
async def producao_materiais_lista(op_id: int, request: Request, session: Session = Depends(get_session)):
    ctx = get_tenant_context(request, session)
    if not ctx:
        return HTMLResponse("", status_code=401)
    op = session.get(OrdemProducao, op_id)
    if not op or op.company_id != ctx.company.id:
        return HTMLResponse("", status_code=404)
    current_client = _resolve_client(request, session, ctx)
    clid = op.client_id or (current_client.id if current_client else None)
    mats = session.exec(select(ProducaoMaterial).where(ProducaoMaterial.op_id == op_id)).all()
    cat_q = select(ProducaoMaterialCatalogo).where(ProducaoMaterialCatalogo.company_id == ctx.company.id)
    if clid:
        cat_q = cat_q.where(ProducaoMaterialCatalogo.client_id == clid)
    catalogo = session.exec(cat_q.order_by(ProducaoMaterialCatalogo.nome)).all()
    return render("producao_materiais.html", request=request, context={
        **_ctx_base(ctx, current_client), "materiais": mats, "op_id": op_id, "catalogo": catalogo,
    })

@app.post("/ferramentas/producao/op/{op_id}/material/salvar")
@require_login
async def producao_material_salvar(op_id: int, request: Request, session: Session = Depends(get_session)):
    ctx = get_tenant_context(request, session)
    if not ctx:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    op = session.get(OrdemProducao, op_id)
    if not op or op.company_id != ctx.company.id:
        return JSONResponse({"error": "not found"}, status_code=404)
    body = await request.json()
    session.add(ProducaoMaterial(
        op_id=op_id, company_id=ctx.company.id,
        nome=body.get("nome", ""), unidade=body.get("unidade", "un"),
        quantidade_planejada=float(body.get("quantidade_planejada", 0)),
        quantidade_consumida=float(body.get("quantidade_consumida", 0)),
        custo_unitario=float(body.get("custo_unitario", 0)),
    ))
    session.commit()
    return JSONResponse({"ok": True})

@app.post("/ferramentas/producao/material/{mat_id}/excluir")
@require_login
async def producao_material_excluir(mat_id: int, request: Request, session: Session = Depends(get_session)):
    ctx = get_tenant_context(request, session)
    if not ctx:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    mat = session.get(ProducaoMaterial, mat_id)
    if not mat or mat.company_id != ctx.company.id:
        return JSONResponse({"error": "not found"}, status_code=404)
    session.delete(mat); session.commit()
    return JSONResponse({"ok": True})


# ── Catálogo de Materiais ─────────────────────────────────────────────────────

@app.post("/ferramentas/producao/material_cat/salvar", response_class=HTMLResponse)
@require_login
async def producao_mat_cat_salvar(request: Request, session: Session = Depends(get_session)):
    ctx = get_tenant_context(request, session)
    if not ctx:
        return RedirectResponse("/login", status_code=303)
    current_client = _resolve_client(request, session, ctx)
    form = await request.form()
    session.add(ProducaoMaterialCatalogo(
        company_id=ctx.company.id,
        client_id=current_client.id if current_client else None,
        nome=(form.get("nome") or "").strip(),
        unidade=(form.get("unidade") or "un").strip(),
        custo_unitario_padrao=float(form.get("custo_unitario_padrao") or 0),
    ))
    session.commit()
    return RedirectResponse("/ferramentas/producao?tab=materiais_cat", status_code=303)

@app.post("/ferramentas/producao/material_cat/{mc_id}/salvar", response_class=HTMLResponse)
@require_login
async def producao_mat_cat_editar(mc_id: int, request: Request, session: Session = Depends(get_session)):
    ctx = get_tenant_context(request, session)
    if not ctx:
        return RedirectResponse("/login", status_code=303)
    mc = session.get(ProducaoMaterialCatalogo, mc_id)
    if mc and mc.company_id == ctx.company.id:
        form = await request.form()
        mc.nome = (form.get("nome") or "").strip()
        mc.unidade = (form.get("unidade") or "un").strip()
        mc.custo_unitario_padrao = float(form.get("custo_unitario_padrao") or 0)
        session.add(mc); session.commit()
    return RedirectResponse("/ferramentas/producao?tab=materiais_cat", status_code=303)

@app.post("/ferramentas/producao/material_cat/{mc_id}/excluir")
@require_login
async def producao_mat_cat_excluir(mc_id: int, request: Request, session: Session = Depends(get_session)):
    ctx = get_tenant_context(request, session)
    if not ctx:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    mc = session.get(ProducaoMaterialCatalogo, mc_id)
    if not mc or mc.company_id != ctx.company.id:
        return JSONResponse({"error": "not found"}, status_code=404)
    session.delete(mc); session.commit()
    return JSONResponse({"ok": True})


# ── Imprimir OP ──────────────────────────────────────────────────────────────

@app.get("/ferramentas/producao/op/{op_id}/imprimir", response_class=HTMLResponse)
@require_login
async def producao_op_imprimir(op_id: int, request: Request, session: Session = Depends(get_session)):
    ctx = get_tenant_context(request, session)
    if not ctx:
        return RedirectResponse("/login", status_code=303)
    op = session.get(OrdemProducao, op_id)
    if not op or op.company_id != ctx.company.id:
        return RedirectResponse("/ferramentas/producao", status_code=303)

    passos = _roteiro(session, op_id)
    roteiro = []
    for p in passos:
        proc = session.get(ProducaoProcesso, p.processo_id)
        roteiro.append({
            "id": p.id, "processo_id": p.processo_id,
            "proc_nome": proc.nome if proc else "?",
            "ordem": p.ordem,
            "tempo_estimado_h": p.tempo_estimado_h,
            "tempo_realizado_h": p.tempo_realizado_h,
            "data_entrada": p.data_entrada,
            "data_saida": p.data_saida,
            "status": p.status,
        })
    materiais = session.exec(select(ProducaoMaterial).where(ProducaoMaterial.op_id == op_id)).all()

    base_url = str(request.base_url).rstrip("/")
    op_url = f"{base_url}/op/{op.token}"
    qr_b64 = _qr_png_b64(op_url)

    return render("producao_imprimir.html", request=request, context={
        "op": op, "roteiro": roteiro, "materiais": materiais,
        "qr_b64": qr_b64, "op_url": op_url,
        "hoje": date.today().strftime("%d/%m/%Y"),
    })


# ── Página do Operador (sem login) ────────────────────────────────────────────

@app.get("/op/{token}", response_class=HTMLResponse)
async def operador_index(token: str, request: Request, session: Session = Depends(get_session)):
    op = session.exec(select(OrdemProducao).where(OrdemProducao.token == token)).first()
    if not op:
        return HTMLResponse("<h2 style='font-family:sans-serif;padding:2rem;'>OP não encontrada ou link inválido.</h2>", status_code=404)

    passos = _roteiro(session, op.id)
    roteiro = []
    for p in passos:
        proc = session.get(ProducaoProcesso, p.processo_id)
        roteiro.append({
            "id": p.id, "processo_id": p.processo_id,
            "proc_nome": proc.nome if proc else "?",
            "ordem": p.ordem,
            "tempo_estimado_h": p.tempo_estimado_h,
            "tempo_realizado_h": p.tempo_realizado_h,
            "data_entrada": p.data_entrada,
            "data_saida": p.data_saida,
            "status": p.status,
        })

    return render("producao_operador.html", request=request, context={
        "op": op, "roteiro": roteiro,
    })


@app.post("/op/{token}/passo/{passo_id}/iniciar")
async def operador_iniciar(token: str, passo_id: int, session: Session = Depends(get_session)):
    op = session.exec(select(OrdemProducao).where(OrdemProducao.token == token)).first()
    if not op:
        return JSONResponse({"error": "OP não encontrada"}, status_code=404)
    passo = session.get(ProducaoRoteiroPasso, passo_id)
    if not passo or passo.op_id != op.id:
        return JSONResponse({"error": "Passo não encontrado"}, status_code=404)
    passo.status = "em_andamento"
    if not passo.data_entrada:
        passo.data_entrada = datetime.utcnow()
    session.add(passo)
    if op.status == "aberta":
        op.status = "em_andamento"
        session.add(op)
    session.commit()
    return JSONResponse({"ok": True})


@app.post("/op/{token}/passo/{passo_id}/finalizar")
async def operador_finalizar(token: str, passo_id: int, session: Session = Depends(get_session)):
    op = session.exec(select(OrdemProducao).where(OrdemProducao.token == token)).first()
    if not op:
        return JSONResponse({"error": "OP não encontrada"}, status_code=404)
    passo = session.get(ProducaoRoteiroPasso, passo_id)
    if not passo or passo.op_id != op.id:
        return JSONResponse({"error": "Passo não encontrado"}, status_code=404)
    passo.status = "concluido"
    passo.data_saida = datetime.utcnow()
    if passo.data_entrada:
        delta = (passo.data_saida - passo.data_entrada).total_seconds() / 3600
        passo.tempo_realizado_h = round(delta, 2)
    session.add(passo)
    session.commit()
    return JSONResponse({"ok": True})


print("[producao] Módulo Controle de Produção carregado — /ferramentas/producao")

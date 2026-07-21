# Módulo: Controle de Produção (Kanban + PCP)
# Ordens de Produção, Processos personalizáveis, Materiais, Planejamento x Controle

import json
import os
from datetime import date, datetime
from typing import Optional

from fastapi import Depends, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlmodel import Field, Session, SQLModel, select

# ── Modelos ───────────────────────────────────────────────────────────────────

class ProducaoProcesso(SQLModel, table=True):
    """Etapa/coluna do Kanban — personalizável por empresa."""
    id: Optional[int] = Field(default=None, primary_key=True)
    company_id: int = Field(index=True)
    nome: str
    ordem: int = Field(default=0)
    cor: str = Field(default="#6366f1")
    created_at: datetime = Field(default_factory=datetime.utcnow)


class OrdemProducao(SQLModel, table=True):
    """Ordem de Produção (OP)."""
    id: Optional[int] = Field(default=None, primary_key=True)
    company_id: int = Field(index=True)
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
    prioridade: str = Field(default="normal")   # baixa / normal / alta / urgente
    status: str = Field(default="aberta")       # aberta / em_andamento / concluida / cancelada
    responsavel: str = Field(default="")
    observacoes: str = Field(default="")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


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


# Cria tabelas
SQLModel.metadata.create_all(engine, tables=[
    ProducaoProcesso.__table__,
    OrdemProducao.__table__,
    ProducaoMaterial.__table__,
])


# ── Helpers ───────────────────────────────────────────────────────────────────

_PRIORIDADE_COR = {
    "baixa":   "#94a3b8",
    "normal":  "#6366f1",
    "alta":    "#f97316",
    "urgente": "#dc2626",
}

_PRIORIDADE_LABEL = {
    "baixa": "Baixa", "normal": "Normal", "alta": "Alta", "urgente": "Urgente"
}

def _ctx_base(ctx):
    return {
        "current_user": ctx.user,
        "current_company": ctx.company,
        "role": ctx.membership.role,
        "current_client": None,
    }

def _processos(session, company_id):
    return session.exec(
        select(ProducaoProcesso)
        .where(ProducaoProcesso.company_id == company_id)
        .order_by(ProducaoProcesso.ordem)
    ).all()

def _ops(session, company_id, processo_id=None):
    q = select(OrdemProducao).where(OrdemProducao.company_id == company_id)
    if processo_id is not None:
        q = q.where(OrdemProducao.processo_id == processo_id)
    return session.exec(q.order_by(OrdemProducao.updated_at.desc())).all()


# ── Template principal ────────────────────────────────────────────────────────

_TPL_PRODUCAO = r"""
{% extends "base.html" %}
{% block title %}Controle de Produção{% endblock %}
{% block content %}
<div style="max-width:1400px;margin:0 auto;padding:1.5rem 1rem;">

  <!-- Header -->
  <div class="d-flex align-items-center justify-content-between flex-wrap gap-2 mb-3">
    <div>
      <h4 class="mb-0" style="font-weight:700;"><i class="bi bi-kanban me-2" style="color:#6366f1;"></i>Controle de Produção</h4>
      <small class="text-muted">Ordens de Produção · Kanban · PCP</small>
    </div>
    <div class="d-flex gap-2 flex-wrap">
      <button class="btn btn-sm btn-outline-secondary" onclick="showTab('kanban')"><i class="bi bi-kanban me-1"></i>Kanban</button>
      <button class="btn btn-sm btn-outline-secondary" onclick="showTab('ops')"><i class="bi bi-list-task me-1"></i>Ordens de Produção</button>
      <button class="btn btn-sm btn-outline-secondary" onclick="showTab('pcp')"><i class="bi bi-graph-up me-1"></i>PCP</button>
      <button class="btn btn-sm btn-outline-secondary" onclick="showTab('processos')"><i class="bi bi-gear me-1"></i>Processos</button>
      <button class="btn btn-sm btn-primary" onclick="abrirModalOP()" style="background:#6366f1;border-color:#6366f1;"><i class="bi bi-plus me-1"></i>Nova OP</button>
    </div>
  </div>

  <!-- KPIs -->
  <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:.75rem;margin-bottom:1.5rem;">
    <div class="kpi-prod" style="border-left:4px solid #6366f1;">
      <div class="kpi-prod-v">{{ ops|length }}</div>
      <div class="kpi-prod-l">Total de OPs</div>
    </div>
    <div class="kpi-prod" style="border-left:4px solid #f97316;">
      <div class="kpi-prod-v">{{ ops|selectattr('status','eq','em_andamento')|list|length }}</div>
      <div class="kpi-prod-l">Em Andamento</div>
    </div>
    <div class="kpi-prod" style="border-left:4px solid #16a34a;">
      <div class="kpi-prod-v">{{ ops|selectattr('status','eq','concluida')|list|length }}</div>
      <div class="kpi-prod-l">Concluídas</div>
    </div>
    <div class="kpi-prod" style="border-left:4px solid #dc2626;">
      <div class="kpi-prod-v">{{ ops|selectattr('prioridade','eq','urgente')|list|length }}</div>
      <div class="kpi-prod-l">Urgentes</div>
    </div>
  </div>

  <!-- ═══════════════════════════ KANBAN ═══════════════════════════ -->
  <div id="tab-kanban">
    {% if not processos %}
    <div class="alert alert-info">
      <i class="bi bi-info-circle me-2"></i>Nenhum processo cadastrado. Acesse <b>Processos</b> para configurar as etapas do seu Kanban.
    </div>
    {% else %}
    <div style="display:flex;gap:1rem;overflow-x:auto;padding-bottom:1rem;align-items:flex-start;">
      {% for proc in processos %}
      {% set proc_ops = ops|selectattr('processo_id','eq',proc.id)|list %}
      <div class="kanban-col" id="col-{{ proc.id }}" ondragover="event.preventDefault()" ondrop="dropOP(event,{{ proc.id }})">
        <div class="kanban-col-hdr" style="border-top:3px solid {{ proc.cor }};">
          <span style="font-weight:700;font-size:.9rem;">{{ proc.nome }}</span>
          <span class="badge rounded-pill" style="background:{{ proc.cor }}20;color:{{ proc.cor }};font-size:.75rem;">{{ proc_ops|length }}</span>
        </div>
        {% for op in proc_ops %}
        <div class="kanban-card" draggable="true" ondragstart="dragOP(event,{{ op.id }})" onclick="abrirModalOP({{ op.id }})">
          <div class="d-flex justify-content-between align-items-start mb-1">
            <span style="font-size:.72rem;color:#94a3b8;font-family:monospace;">{{ op.codigo }}</span>
            <span class="badge" style="font-size:.65rem;background:{{ _prioridade_cor(op.prioridade) }}20;color:{{ _prioridade_cor(op.prioridade) }};">{{ op.prioridade|upper }}</span>
          </div>
          <div style="font-weight:600;font-size:.85rem;margin-bottom:.25rem;">{{ op.produto }}</div>
          {% if op.descricao %}<div style="font-size:.75rem;color:#64748b;margin-bottom:.35rem;">{{ op.descricao[:60] }}{% if op.descricao|length > 60 %}…{% endif %}</div>{% endif %}
          <!-- progresso quantidade -->
          {% if op.quantidade_planejada > 0 %}
          {% set pct = [(op.quantidade_produzida / op.quantidade_planejada * 100)|round|int, 100]|min %}
          <div style="margin:.35rem 0;">
            <div style="display:flex;justify-content:space-between;font-size:.7rem;color:#94a3b8;margin-bottom:2px;">
              <span>{{ op.quantidade_produzida|int }}/{{ op.quantidade_planejada|int }}</span>
              <span>{{ pct }}%</span>
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
        <!-- OP sem processo nesta coluna -->
        {% if proc_ops|length == 0 %}
        <div style="text-align:center;padding:2rem 1rem;color:#cbd5e1;font-size:.8rem;border:2px dashed #e2e8f0;border-radius:8px;">Arraste OPs aqui</div>
        {% endif %}
      </div>
      {% endfor %}
      <!-- Coluna "Sem processo" -->
      {% set sem_proc = ops|selectattr('processo_id','none')|list %}
      {% if sem_proc %}
      <div class="kanban-col" id="col-null" ondragover="event.preventDefault()" ondrop="dropOP(event,null)">
        <div class="kanban-col-hdr" style="border-top:3px solid #94a3b8;">
          <span style="font-weight:700;font-size:.9rem;">Sem etapa</span>
          <span class="badge rounded-pill" style="background:#94a3b820;color:#94a3b8;font-size:.75rem;">{{ sem_proc|length }}</span>
        </div>
        {% for op in sem_proc %}
        <div class="kanban-card" draggable="true" ondragstart="dragOP(event,{{ op.id }})" onclick="abrirModalOP({{ op.id }})">
          <div class="d-flex justify-content-between mb-1">
            <span style="font-size:.72rem;color:#94a3b8;font-family:monospace;">{{ op.codigo }}</span>
            <span class="badge" style="font-size:.65rem;background:{{ _prioridade_cor(op.prioridade) }}20;color:{{ _prioridade_cor(op.prioridade) }};">{{ op.prioridade|upper }}</span>
          </div>
          <div style="font-weight:600;font-size:.85rem;">{{ op.produto }}</div>
        </div>
        {% endfor %}
      </div>
      {% endif %}
    </div>
    {% endif %}
  </div>

  <!-- ═══════════════════════════ LISTA OPs ═══════════════════════════ -->
  <div id="tab-ops" style="display:none;">
    <div class="d-flex gap-2 mb-3">
      <input type="text" id="filtroOP" class="form-control form-control-sm" placeholder="Buscar OP, produto..." oninput="filtrarOPs()" style="max-width:300px;">
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
          <th style="padding:.5rem .75rem;text-align:left;">Código</th>
          <th style="padding:.5rem .75rem;text-align:left;">Produto</th>
          <th style="padding:.5rem .75rem;text-align:center;">Etapa</th>
          <th style="padding:.5rem .75rem;text-align:center;">Prioridade</th>
          <th style="padding:.5rem .75rem;text-align:right;">Qtd Plan.</th>
          <th style="padding:.5rem .75rem;text-align:right;">Qtd Prod.</th>
          <th style="padding:.5rem .75rem;text-align:center;">Progresso</th>
          <th style="padding:.5rem .75rem;text-align:center;">Início Plan.</th>
          <th style="padding:.5rem .75rem;text-align:center;">Fim Plan.</th>
          <th style="padding:.5rem .75rem;text-align:center;">Status</th>
          <th style="padding:.5rem .75rem;text-align:center;">Ações</th>
        </tr></thead>
        <tbody>
          {% for op in ops %}
          {% set proc_nome = processos_dict.get(op.processo_id, '—') %}
          {% set pct = [(op.quantidade_produzida / op.quantidade_planejada * 100)|round|int, 100]|min if op.quantidade_planejada > 0 else 0 %}
          <tr class="op-row" data-busca="{{ op.codigo }} {{ op.produto }} {{ op.responsavel }}" data-status="{{ op.status }}" style="border-bottom:1px solid #f1f5f9;">
            <td style="padding:.45rem .75rem;font-family:monospace;font-weight:600;color:#6366f1;">{{ op.codigo }}</td>
            <td style="padding:.45rem .75rem;font-weight:600;">{{ op.produto }}<br><small class="text-muted">{{ op.descricao[:40] if op.descricao else '' }}</small></td>
            <td style="padding:.45rem .75rem;text-align:center;"><span style="font-size:.75rem;padding:.15rem .5rem;border-radius:999px;background:#f1f5f9;">{{ proc_nome }}</span></td>
            <td style="padding:.45rem .75rem;text-align:center;"><span class="badge" style="background:{{ _prioridade_cor(op.prioridade) }}20;color:{{ _prioridade_cor(op.prioridade) }};">{{ op.prioridade|capitalize }}</span></td>
            <td style="padding:.45rem .75rem;text-align:right;">{{ op.quantidade_planejada|int }}</td>
            <td style="padding:.45rem .75rem;text-align:right;">{{ op.quantidade_produzida|int }}</td>
            <td style="padding:.45rem .75rem;text-align:center;min-width:80px;">
              <div style="height:6px;background:#e2e8f0;border-radius:3px;">
                <div style="height:6px;border-radius:3px;width:{{ pct }}%;background:{% if pct>=100 %}#16a34a{% elif pct>=50 %}#f97316{% else %}#6366f1{% endif %};"></div>
              </div>
              <small style="color:#94a3b8;">{{ pct }}%</small>
            </td>
            <td style="padding:.45rem .75rem;text-align:center;">{{ op.data_inicio_plan.strftime('%d/%m/%Y') if op.data_inicio_plan else '—' }}</td>
            <td style="padding:.45rem .75rem;text-align:center;">{{ op.data_fim_plan.strftime('%d/%m/%Y') if op.data_fim_plan else '—' }}</td>
            <td style="padding:.45rem .75rem;text-align:center;"><span class="badge" style="background:{% if op.status=='concluida' %}#dcfce7;color:#16a34a{% elif op.status=='em_andamento' %}#eff6ff;color:#6366f1{% elif op.status=='cancelada' %}#fef2f2;color:#dc2626{% else %}#f8fafc;color:#64748b{% endif %};">{{ op.status|replace('_',' ')|title }}</span></td>
            <td style="padding:.45rem .75rem;text-align:center;">
              <button class="btn btn-sm btn-outline-primary btn-icon" onclick="abrirModalOP({{ op.id }})" title="Editar"><i class="bi bi-pencil"></i></button>
              <button class="btn btn-sm btn-outline-info btn-icon" onclick="abrirMateriais({{ op.id }},'{{ op.codigo }} - {{ op.produto }}')" title="Materiais"><i class="bi bi-box-seam"></i></button>
              <button class="btn btn-sm btn-outline-danger btn-icon" onclick="confirmarExcluirOP({{ op.id }},'{{ op.codigo }}')" title="Excluir"><i class="bi bi-trash"></i></button>
            </td>
          </tr>
          {% else %}
          <tr><td colspan="11" style="padding:2rem;text-align:center;color:#94a3b8;">Nenhuma OP cadastrada. Clique em <b>Nova OP</b> para começar.</td></tr>
          {% endfor %}
        </tbody>
      </table>
    </div>
  </div>

  <!-- ═══════════════════════════ PCP ═══════════════════════════ -->
  <div id="tab-pcp" style="display:none;">
    <h6 style="color:#6366f1;font-weight:700;margin-bottom:1rem;"><i class="bi bi-graph-up me-2"></i>Planejamento × Controle da Produção</h6>

    <!-- Resumo geral -->
    <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:.75rem;margin-bottom:1.5rem;">
      {% set total_plan = ops|sum(attribute='quantidade_planejada') %}
      {% set total_prod = ops|sum(attribute='quantidade_produzida') %}
      {% set pct_geral = [(total_prod / total_plan * 100)|round|int, 100]|min if total_plan > 0 else 0 %}
      <div class="kpi-prod" style="border-left:4px solid #6366f1;">
        <div class="kpi-prod-v">{{ total_plan|int }}</div>
        <div class="kpi-prod-l">Qtd Total Planejada</div>
      </div>
      <div class="kpi-prod" style="border-left:4px solid #16a34a;">
        <div class="kpi-prod-v">{{ total_prod|int }}</div>
        <div class="kpi-prod-l">Qtd Total Produzida</div>
      </div>
      <div class="kpi-prod" style="border-left:4px solid #f97316;">
        <div class="kpi-prod-v">{{ pct_geral }}%</div>
        <div class="kpi-prod-l">Eficiência Geral</div>
      </div>
      {% set atrasadas = [] %}
      {% for op in ops %}
        {% if op.data_fim_plan and op.status not in ['concluida','cancelada'] and op.data_fim_plan < hoje %}
          {% set _ = atrasadas.append(op) %}
        {% endif %}
      {% endfor %}
      <div class="kpi-prod" style="border-left:4px solid #dc2626;">
        <div class="kpi-prod-v" style="color:#dc2626;">{{ atrasadas|length }}</div>
        <div class="kpi-prod-l">OPs Atrasadas</div>
      </div>
    </div>

    <!-- Tabela PCP -->
    <div style="overflow-x:auto;border:1px solid var(--mc-border);border-radius:12px;">
      <table style="width:100%;border-collapse:collapse;font-size:.83rem;">
        <thead><tr style="background:#1e293b;color:#fff;">
          <th style="padding:.5rem .75rem;text-align:left;">OP</th>
          <th style="padding:.5rem .75rem;text-align:left;">Produto</th>
          <th style="padding:.5rem .75rem;text-align:center;">Etapa</th>
          <th style="padding:.5rem .75rem;text-align:center;background:#6366f130;">Início Plan.</th>
          <th style="padding:.5rem .75rem;text-align:center;background:#6366f130;">Fim Plan.</th>
          <th style="padding:.5rem .75rem;text-align:center;background:#16a34a30;">Início Real</th>
          <th style="padding:.5rem .75rem;text-align:center;background:#16a34a30;">Fim Real</th>
          <th style="padding:.5rem .75rem;text-align:center;">Desvio (dias)</th>
          <th style="padding:.5rem .75rem;text-align:right;background:#6366f130;">Qtd Plan.</th>
          <th style="padding:.5rem .75rem;text-align:right;background:#16a34a30;">Qtd Real</th>
          <th style="padding:.5rem .75rem;text-align:center;">Eficiência</th>
          <th style="padding:.5rem .75rem;text-align:center;">Status</th>
        </tr></thead>
        <tbody>
          {% for op in ops %}
          {% set proc_nome = processos_dict.get(op.processo_id, '—') %}
          {% set pct = [(op.quantidade_produzida / op.quantidade_planejada * 100)|round|int, 100]|min if op.quantidade_planejada > 0 else 0 %}
          {% set desvio = none %}
          {% if op.data_fim_plan and op.data_fim_real %}
            {% set desvio = (op.data_fim_real - op.data_fim_plan).days %}
          {% elif op.data_fim_plan and op.status not in ['concluida','cancelada'] and op.data_fim_plan < hoje %}
            {% set desvio = (hoje - op.data_fim_plan).days %}
          {% endif %}
          <tr style="border-bottom:1px solid #f1f5f9;">
            <td style="padding:.45rem .75rem;font-family:monospace;font-weight:600;color:#6366f1;">{{ op.codigo }}</td>
            <td style="padding:.45rem .75rem;font-weight:600;">{{ op.produto }}</td>
            <td style="padding:.45rem .75rem;text-align:center;"><small>{{ proc_nome }}</small></td>
            <td style="padding:.45rem .75rem;text-align:center;background:#6366f108;">{{ op.data_inicio_plan.strftime('%d/%m/%y') if op.data_inicio_plan else '—' }}</td>
            <td style="padding:.45rem .75rem;text-align:center;background:#6366f108;">{{ op.data_fim_plan.strftime('%d/%m/%y') if op.data_fim_plan else '—' }}</td>
            <td style="padding:.45rem .75rem;text-align:center;background:#16a34a08;">{{ op.data_inicio_real.strftime('%d/%m/%y') if op.data_inicio_real else '—' }}</td>
            <td style="padding:.45rem .75rem;text-align:center;background:#16a34a08;">{{ op.data_fim_real.strftime('%d/%m/%y') if op.data_fim_real else '—' }}</td>
            <td style="padding:.45rem .75rem;text-align:center;">
              {% if desvio is not none %}
                <span style="font-weight:700;color:{% if desvio<=0 %}#16a34a{% elif desvio<=3 %}#f97316{% else %}#dc2626{% endif %};">
                  {% if desvio<=0 %}{{ desvio }}d{% else %}+{{ desvio }}d{% endif %}
                </span>
              {% else %}—{% endif %}
            </td>
            <td style="padding:.45rem .75rem;text-align:right;background:#6366f108;">{{ op.quantidade_planejada|int }}</td>
            <td style="padding:.45rem .75rem;text-align:right;background:#16a34a08;font-weight:600;">{{ op.quantidade_produzida|int }}</td>
            <td style="padding:.45rem .75rem;text-align:center;">
              <div style="display:flex;align-items:center;gap:.4rem;">
                <div style="height:6px;width:60px;background:#e2e8f0;border-radius:3px;">
                  <div style="height:6px;border-radius:3px;width:{{ pct }}%;background:{% if pct>=100 %}#16a34a{% elif pct>=60 %}#f97316{% else %}#dc2626{% endif %};"></div>
                </div>
                <small style="font-weight:700;color:{% if pct>=100 %}#16a34a{% elif pct>=60 %}#f97316{% else %}#dc2626{% endif %};">{{ pct }}%</small>
              </div>
            </td>
            <td style="padding:.45rem .75rem;text-align:center;"><span class="badge" style="background:{% if op.status=='concluida' %}#dcfce7;color:#16a34a{% elif op.status=='em_andamento' %}#eff6ff;color:#6366f1{% elif op.status=='cancelada' %}#fef2f2;color:#dc2626{% else %}#f8fafc;color:#64748b{% endif %};">{{ op.status|replace('_',' ')|title }}</span></td>
          </tr>
          {% else %}
          <tr><td colspan="12" style="padding:2rem;text-align:center;color:#94a3b8;">Nenhuma OP cadastrada.</td></tr>
          {% endfor %}
        </tbody>
      </table>
    </div>
  </div>

  <!-- ═══════════════════════════ PROCESSOS ═══════════════════════════ -->
  <div id="tab-processos" style="display:none;">
    <div class="d-flex align-items-center justify-content-between mb-3">
      <h6 class="mb-0" style="color:#6366f1;font-weight:700;"><i class="bi bi-gear me-2"></i>Configurar Etapas do Kanban</h6>
      <button class="btn btn-sm btn-primary" onclick="abrirModalProcesso()" style="background:#6366f1;border-color:#6366f1;"><i class="bi bi-plus me-1"></i>Nova Etapa</button>
    </div>
    {% if processos %}
    <div style="display:flex;flex-direction:column;gap:.5rem;max-width:600px;">
      {% for proc in processos %}
      <div style="display:flex;align-items:center;gap:.75rem;padding:.75rem 1rem;border:1px solid var(--mc-border);border-radius:10px;border-left:4px solid {{ proc.cor }};">
        <span style="font-weight:700;min-width:1.5rem;color:#94a3b8;">{{ proc.ordem }}</span>
        <span style="width:14px;height:14px;border-radius:50%;background:{{ proc.cor }};flex-shrink:0;"></span>
        <span style="flex:1;font-weight:600;">{{ proc.nome }}</span>
        <button class="btn btn-sm btn-outline-primary btn-icon" onclick="abrirModalProcesso({{ proc.id }},'{{ proc.nome }}','{{ proc.cor }}',{{ proc.ordem }})"><i class="bi bi-pencil"></i></button>
        <button class="btn btn-sm btn-outline-danger btn-icon" onclick="confirmarExcluirProcesso({{ proc.id }},'{{ proc.nome }}')"><i class="bi bi-trash"></i></button>
      </div>
      {% endfor %}
    </div>
    {% else %}
    <div class="alert alert-info"><i class="bi bi-info-circle me-2"></i>Nenhuma etapa cadastrada. Crie etapas para usar o Kanban (ex: A Fazer, Em Produção, Controle de Qualidade, Concluído).</div>
    {% endif %}
  </div>

</div><!-- /container -->

<!-- ═══ MODAL OP ═══ -->
<div class="modal fade" id="modalOP" tabindex="-1">
  <div class="modal-dialog modal-lg">
    <div class="modal-content">
      <div class="modal-header" style="background:#6366f1;color:#fff;">
        <h5 class="modal-title" id="modalOPTitulo"><i class="bi bi-kanban me-2"></i>Nova Ordem de Produção</h5>
        <button type="button" class="btn-close btn-close-white" data-bs-dismiss="modal"></button>
      </div>
      <form id="formOP" method="post">
        <div class="modal-body">
          <div class="row g-3">
            <div class="col-md-4">
              <label class="form-label fw-semibold">Código OP *</label>
              <input type="text" name="codigo" id="op_codigo" class="form-control" placeholder="OP-001" required>
            </div>
            <div class="col-md-8">
              <label class="form-label fw-semibold">Produto *</label>
              <input type="text" name="produto" id="op_produto" class="form-control" placeholder="Nome do produto" required>
            </div>
            <div class="col-12">
              <label class="form-label fw-semibold">Descrição</label>
              <textarea name="descricao" id="op_descricao" class="form-control" rows="2" placeholder="Detalhes da OP..."></textarea>
            </div>
            <div class="col-md-4">
              <label class="form-label fw-semibold">Etapa (Kanban)</label>
              <select name="processo_id" id="op_processo_id" class="form-select">
                <option value="">— Sem etapa —</option>
                {% for proc in processos %}
                <option value="{{ proc.id }}">{{ proc.nome }}</option>
                {% endfor %}
              </select>
            </div>
            <div class="col-md-4">
              <label class="form-label fw-semibold">Prioridade</label>
              <select name="prioridade" id="op_prioridade" class="form-select">
                <option value="baixa">Baixa</option>
                <option value="normal" selected>Normal</option>
                <option value="alta">Alta</option>
                <option value="urgente">Urgente</option>
              </select>
            </div>
            <div class="col-md-4">
              <label class="form-label fw-semibold">Status</label>
              <select name="status" id="op_status" class="form-select">
                <option value="aberta">Aberta</option>
                <option value="em_andamento">Em andamento</option>
                <option value="concluida">Concluída</option>
                <option value="cancelada">Cancelada</option>
              </select>
            </div>
            <div class="col-md-6">
              <label class="form-label fw-semibold">Qtd Planejada</label>
              <input type="number" name="quantidade_planejada" id="op_qtd_plan" class="form-control" min="0" step="0.01" value="0">
            </div>
            <div class="col-md-6">
              <label class="form-label fw-semibold">Qtd Produzida</label>
              <input type="number" name="quantidade_produzida" id="op_qtd_prod" class="form-control" min="0" step="0.01" value="0">
            </div>
            <div class="col-md-3">
              <label class="form-label fw-semibold">Início Planejado</label>
              <input type="date" name="data_inicio_plan" id="op_dt_ini_plan" class="form-control">
            </div>
            <div class="col-md-3">
              <label class="form-label fw-semibold">Fim Planejado</label>
              <input type="date" name="data_fim_plan" id="op_dt_fim_plan" class="form-control">
            </div>
            <div class="col-md-3">
              <label class="form-label fw-semibold">Início Real</label>
              <input type="date" name="data_inicio_real" id="op_dt_ini_real" class="form-control">
            </div>
            <div class="col-md-3">
              <label class="form-label fw-semibold">Fim Real</label>
              <input type="date" name="data_fim_real" id="op_dt_fim_real" class="form-control">
            </div>
            <div class="col-12">
              <label class="form-label fw-semibold">Responsável</label>
              <input type="text" name="responsavel" id="op_responsavel" class="form-control" placeholder="Nome do responsável">
            </div>
            <div class="col-12">
              <label class="form-label fw-semibold">Observações</label>
              <textarea name="observacoes" id="op_observacoes" class="form-control" rows="2"></textarea>
            </div>
          </div>
        </div>
        <div class="modal-footer">
          <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Cancelar</button>
          <button type="submit" class="btn btn-primary" style="background:#6366f1;border-color:#6366f1;"><i class="bi bi-check me-1"></i>Salvar</button>
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
          <div class="mb-3">
            <label class="form-label fw-semibold">Nome da etapa *</label>
            <input type="text" name="nome" id="proc_nome" class="form-control" placeholder="Ex: Em Produção" required>
          </div>
          <div class="mb-3">
            <label class="form-label fw-semibold">Cor</label>
            <input type="color" name="cor" id="proc_cor" class="form-control form-control-color w-100" value="#6366f1">
          </div>
          <div class="mb-3">
            <label class="form-label fw-semibold">Ordem</label>
            <input type="number" name="ordem" id="proc_ordem" class="form-control" min="0" value="0">
          </div>
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
      <div class="modal-body" id="matBody">
        <div class="text-center py-4"><div class="spinner-border" style="color:#0891b2;"></div></div>
      </div>
    </div>
  </div>
</div>

<style>
.kpi-prod{background:var(--mc-card);border:1px solid var(--mc-border);border-radius:10px;padding:.85rem 1rem;}
.kpi-prod-v{font-size:1.5rem;font-weight:800;line-height:1;}
.kpi-prod-l{font-size:.75rem;color:#94a3b8;margin-top:.2rem;}
.kanban-col{min-width:260px;max-width:280px;background:var(--mc-bg2,#f8fafc);border:1px solid var(--mc-border);border-radius:12px;padding:.75rem;display:flex;flex-direction:column;gap:.5rem;}
.kanban-col-hdr{display:flex;justify-content:space-between;align-items:center;padding:.3rem .1rem .6rem;border-bottom:1px solid var(--mc-border);margin-bottom:.25rem;}
.kanban-card{background:var(--mc-card);border:1px solid var(--mc-border);border-radius:8px;padding:.65rem .75rem;cursor:pointer;transition:box-shadow .15s,transform .1s;}
.kanban-card:hover{box-shadow:0 4px 12px rgba(0,0,0,.12);transform:translateY(-1px);}
.btn-icon{padding:.2rem .45rem;font-size:.8rem;}
</style>

<script>
// ── Tabs ──
function showTab(t){
  ['kanban','ops','pcp','processos'].forEach(id=>{
    document.getElementById('tab-'+id).style.display=id===t?'':'none';
  });
  localStorage.setItem('prodTab',t);
}
(function(){ showTab(localStorage.getItem('prodTab')||'kanban'); })();

// ── Drag & Drop Kanban ──
let _dragOpId=null;
function dragOP(e,id){ _dragOpId=id; e.dataTransfer.effectAllowed='move'; }
function dropOP(e,processoId){
  e.preventDefault();
  if(!_dragOpId) return;
  fetch('/ferramentas/producao/op/'+_dragOpId+'/mover', {
    method:'POST',
    headers:{'Content-Type':'application/json'},
    body:JSON.stringify({processo_id:processoId})
  }).then(r=>{ if(r.ok) location.reload(); });
}

// ── Modal OP ──
function abrirModalOP(id){
  const form=document.getElementById('formOP');
  if(!id){
    document.getElementById('modalOPTitulo').innerHTML='<i class="bi bi-kanban me-2"></i>Nova Ordem de Produção';
    form.action='/ferramentas/producao/op/salvar';
    form.reset();
    return new bootstrap.Modal(document.getElementById('modalOP')).show();
  }
  fetch('/ferramentas/producao/op/'+id+'/json').then(r=>r.json()).then(d=>{
    document.getElementById('modalOPTitulo').innerHTML='<i class="bi bi-pencil me-2"></i>Editar OP — '+d.codigo;
    form.action='/ferramentas/producao/op/'+id+'/salvar';
    ['codigo','produto','descricao','prioridade','status','responsavel','observacoes'].forEach(f=>{
      const el=document.getElementById('op_'+f);
      if(el) el.value=d[f]||'';
    });
    document.getElementById('op_processo_id').value=d.processo_id||'';
    document.getElementById('op_qtd_plan').value=d.quantidade_planejada||0;
    document.getElementById('op_qtd_prod').value=d.quantidade_produzida||0;
    ['dt_ini_plan','dt_fim_plan','dt_ini_real','dt_fim_real'].forEach(f=>{
      const key=f.replace('dt_ini_plan','data_inicio_plan').replace('dt_fim_plan','data_fim_plan').replace('dt_ini_real','data_inicio_real').replace('dt_fim_real','data_fim_real');
      const el=document.getElementById('op_'+f);
      if(el) el.value=d[key]||'';
    });
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

// ── Confirmações ──
function confirmarExcluirOP(id,cod){
  if(confirm('Excluir OP '+cod+'? Esta ação não pode ser desfeita.'))
    fetch('/ferramentas/producao/op/'+id+'/excluir',{method:'POST'}).then(r=>{ if(r.ok) location.reload(); });
}
function confirmarExcluirProcesso(id,nome){
  if(confirm('Excluir etapa "'+nome+'"? As OPs vinculadas ficam sem etapa.'))
    fetch('/ferramentas/producao/processo/'+id+'/excluir',{method:'POST'}).then(r=>{ if(r.ok) location.reload(); });
}

// ── Filtro OPs ──
function filtrarOPs(){
  const txt=(document.getElementById('filtroOP').value||'').toLowerCase();
  const st=document.getElementById('filtroStatus').value;
  document.querySelectorAll('.op-row').forEach(tr=>{
    const busca=(tr.dataset.busca||'').toLowerCase();
    const status=tr.dataset.status||'';
    tr.style.display=((!txt||busca.includes(txt))&&(!st||status===st))?'':'none';
  });
}
</script>
{% endblock %}
"""


# ── Template Materiais (partial HTML) ────────────────────────────────────────

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
            <button class="btn btn-sm btn-outline-danger" onclick="excluirMaterial({{ m.id }},{{ op_id }})"><i class="bi bi-trash"></i></button>
          </td>
        </tr>
        {% endfor %}
        <tr style="background:#f8fafc;font-weight:700;">
          <td colspan="5" style="padding:.4rem .65rem;text-align:right;">Total Consumido:</td>
          <td style="padding:.4rem .65rem;text-align:right;color:#0891b2;">R$ {{ '%.2f'|format(materiais|sum(attribute='custo_consumido')) }}</td>
          <td></td>
        </tr>
      </tbody>
    </table>
  </div>
  {% else %}
  <p class="text-muted text-center py-3">Nenhum material cadastrado para esta OP.</p>
  {% endif %}

  <hr>
  <h6 style="color:#0891b2;font-weight:700;"><i class="bi bi-plus me-1"></i>Adicionar Material</h6>
  <form onsubmit="salvarMaterial(event,{{ op_id }})">
    <div class="row g-2">
      <div class="col-md-4"><input type="text" id="mat_nome" class="form-control form-control-sm" placeholder="Nome do material" required></div>
      <div class="col-md-2"><input type="text" id="mat_unidade" class="form-control form-control-sm" placeholder="Unid. (kg, m, un)" value="un"></div>
      <div class="col-md-2"><input type="number" id="mat_qtd_plan" class="form-control form-control-sm" placeholder="Qtd plan." min="0" step="0.001" value="0"></div>
      <div class="col-md-2"><input type="number" id="mat_qtd_cons" class="form-control form-control-sm" placeholder="Qtd consumida" min="0" step="0.001" value="0"></div>
      <div class="col-md-2"><input type="number" id="mat_custo" class="form-control form-control-sm" placeholder="Custo unit. R$" min="0" step="0.01" value="0"></div>
      <div class="col-12"><button type="submit" class="btn btn-sm btn-primary" style="background:#0891b2;border-color:#0891b2;"><i class="bi bi-plus me-1"></i>Adicionar</button></div>
    </div>
  </form>
</div>
<script>
function salvarMaterial(e,opId){
  e.preventDefault();
  fetch('/ferramentas/producao/op/'+opId+'/material/salvar',{
    method:'POST',
    headers:{'Content-Type':'application/json'},
    body:JSON.stringify({
      nome:document.getElementById('mat_nome').value,
      unidade:document.getElementById('mat_unidade').value,
      quantidade_planejada:parseFloat(document.getElementById('mat_qtd_plan').value)||0,
      quantidade_consumida:parseFloat(document.getElementById('mat_qtd_cons').value)||0,
      custo_unitario:parseFloat(document.getElementById('mat_custo').value)||0,
    })
  }).then(r=>{ if(r.ok) abrirMateriais(opId,''); });
}
function excluirMaterial(mid,opId){
  if(confirm('Excluir este material?'))
    fetch('/ferramentas/producao/material/'+mid+'/excluir',{method:'POST'}).then(r=>{ if(r.ok) abrirMateriais(opId,''); });
}
</script>
"""

# Registra templates
TEMPLATES["producao.html"] = _TPL_PRODUCAO
TEMPLATES["producao_materiais.html"] = _TPL_MATERIAIS


# ── Filtro Jinja ──────────────────────────────────────────────────────────────

def _prioridade_cor(p):
    return _PRIORIDADE_COR.get(p, "#6366f1")

templates_env.filters["_prioridade_cor"] = _prioridade_cor


# ── Rotas ─────────────────────────────────────────────────────────────────────

def _producao_permitida(ctx, session) -> bool:
    if ctx.membership.role in ("admin", "equipe"):
        return True
    try:
        from sqlmodel import select as _sel
        client_id = ctx.membership.client_id
        if not client_id:
            return False
        allowed = get_client_allowed_features(session, company_id=ctx.company.id, client_id=client_id)
        return bool(allowed and "producao_kanban" in allowed)
    except Exception:
        return False


@app.get("/ferramentas/producao", response_class=HTMLResponse)
@require_login
async def producao_index(request: Request, session: Session = Depends(get_session)):
    ctx = get_tenant_context(request, session)
    if not ctx:
        return RedirectResponse("/login", status_code=303)
    if not _producao_permitida(ctx, session):
        return RedirectResponse("/ferramentas", status_code=303)
    cid = ctx.company.id
    procs = _processos(session, cid)
    all_ops = _ops(session, cid)
    procs_dict = {p.id: p.nome for p in procs}
    return render("producao.html", request=request, context={
        **_ctx_base(ctx),
        "processos": procs,
        "processos_dict": procs_dict,
        "ops": all_ops,
        "hoje": date.today(),
        "_prioridade_cor": _prioridade_cor,
    })


# ── OP: salvar (novo) ─────────────────────────────────────────────────────────

@app.post("/ferramentas/producao/op/salvar", response_class=HTMLResponse)
@require_login
async def producao_op_salvar(
    request: Request,
    session: Session = Depends(get_session),
    codigo: str = Form(...),
    produto: str = Form(...),
    descricao: str = Form(""),
    processo_id: str = Form(""),
    prioridade: str = Form("normal"),
    status: str = Form("aberta"),
    quantidade_planejada: float = Form(0),
    quantidade_produzida: float = Form(0),
    data_inicio_plan: str = Form(""),
    data_fim_plan: str = Form(""),
    data_inicio_real: str = Form(""),
    data_fim_real: str = Form(""),
    responsavel: str = Form(""),
    observacoes: str = Form(""),
):
    ctx = get_tenant_context(request, session)
    if not ctx:
        return RedirectResponse("/login", status_code=303)

    def _parse_date(s):
        try: return date.fromisoformat(s) if s else None
        except: return None

    op = OrdemProducao(
        company_id=ctx.company.id,
        codigo=codigo.strip(),
        produto=produto.strip(),
        descricao=descricao.strip(),
        processo_id=int(processo_id) if processo_id else None,
        prioridade=prioridade,
        status=status,
        quantidade_planejada=quantidade_planejada,
        quantidade_produzida=quantidade_produzida,
        data_inicio_plan=_parse_date(data_inicio_plan),
        data_fim_plan=_parse_date(data_fim_plan),
        data_inicio_real=_parse_date(data_inicio_real),
        data_fim_real=_parse_date(data_fim_real),
        responsavel=responsavel.strip(),
        observacoes=observacoes.strip(),
        updated_at=datetime.utcnow(),
    )
    session.add(op)
    session.commit()
    return RedirectResponse("/ferramentas/producao", status_code=303)


# ── OP: editar ────────────────────────────────────────────────────────────────

@app.post("/ferramentas/producao/op/{op_id}/salvar", response_class=HTMLResponse)
@require_login
async def producao_op_editar(
    op_id: int,
    request: Request,
    session: Session = Depends(get_session),
    codigo: str = Form(...),
    produto: str = Form(...),
    descricao: str = Form(""),
    processo_id: str = Form(""),
    prioridade: str = Form("normal"),
    status: str = Form("aberta"),
    quantidade_planejada: float = Form(0),
    quantidade_produzida: float = Form(0),
    data_inicio_plan: str = Form(""),
    data_fim_plan: str = Form(""),
    data_inicio_real: str = Form(""),
    data_fim_real: str = Form(""),
    responsavel: str = Form(""),
    observacoes: str = Form(""),
):
    ctx = get_tenant_context(request, session)
    if not ctx:
        return RedirectResponse("/login", status_code=303)

    def _parse_date(s):
        try: return date.fromisoformat(s) if s else None
        except: return None

    op = session.get(OrdemProducao, op_id)
    if not op or op.company_id != ctx.company.id:
        return RedirectResponse("/ferramentas/producao", status_code=303)

    op.codigo = codigo.strip()
    op.produto = produto.strip()
    op.descricao = descricao.strip()
    op.processo_id = int(processo_id) if processo_id else None
    op.prioridade = prioridade
    op.status = status
    op.quantidade_planejada = quantidade_planejada
    op.quantidade_produzida = quantidade_produzida
    op.data_inicio_plan = _parse_date(data_inicio_plan)
    op.data_fim_plan = _parse_date(data_fim_plan)
    op.data_inicio_real = _parse_date(data_inicio_real)
    op.data_fim_real = _parse_date(data_fim_real)
    op.responsavel = responsavel.strip()
    op.observacoes = observacoes.strip()
    op.updated_at = datetime.utcnow()
    session.add(op)
    session.commit()
    return RedirectResponse("/ferramentas/producao", status_code=303)


# ── OP: JSON (para modal) ─────────────────────────────────────────────────────

@app.get("/ferramentas/producao/op/{op_id}/json")
@require_login
async def producao_op_json(op_id: int, request: Request, session: Session = Depends(get_session)):
    ctx = get_tenant_context(request, session)
    if not ctx:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    op = session.get(OrdemProducao, op_id)
    if not op or op.company_id != ctx.company.id:
        return JSONResponse({"error": "not found"}, status_code=404)
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
    op.processo_id = int(pid) if pid else None
    if pid and op.status == "aberta":
        op.status = "em_andamento"
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
    # Remove materiais vinculados
    mats = session.exec(select(ProducaoMaterial).where(ProducaoMaterial.op_id == op_id)).all()
    for m in mats:
        session.delete(m)
    session.delete(op)
    session.commit()
    return JSONResponse({"ok": True})


# ── Processo: salvar ──────────────────────────────────────────────────────────

@app.post("/ferramentas/producao/processo/salvar", response_class=HTMLResponse)
@require_login
async def producao_processo_salvar(
    request: Request,
    session: Session = Depends(get_session),
    processo_id: str = Form(""),
    nome: str = Form(...),
    cor: str = Form("#6366f1"),
    ordem: int = Form(0),
):
    ctx = get_tenant_context(request, session)
    if not ctx:
        return RedirectResponse("/login", status_code=303)

    if processo_id:
        proc = session.get(ProducaoProcesso, int(processo_id))
        if proc and proc.company_id == ctx.company.id:
            proc.nome = nome.strip()
            proc.cor = cor
            proc.ordem = ordem
            session.add(proc)
    else:
        proc = ProducaoProcesso(
            company_id=ctx.company.id,
            nome=nome.strip(), cor=cor, ordem=ordem
        )
        session.add(proc)
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
    # Desvincula OPs desta etapa
    ops_vinc = session.exec(select(OrdemProducao).where(OrdemProducao.processo_id == proc_id)).all()
    for op in ops_vinc:
        op.processo_id = None
        session.add(op)
    session.delete(proc)
    session.commit()
    return JSONResponse({"ok": True})


# ── Materiais: listar (partial HTML) ─────────────────────────────────────────

@app.get("/ferramentas/producao/op/{op_id}/materiais", response_class=HTMLResponse)
@require_login
async def producao_materiais_lista(op_id: int, request: Request, session: Session = Depends(get_session)):
    ctx = get_tenant_context(request, session)
    if not ctx:
        return HTMLResponse("", status_code=401)
    op = session.get(OrdemProducao, op_id)
    if not op or op.company_id != ctx.company.id:
        return HTMLResponse("", status_code=404)
    mats = session.exec(select(ProducaoMaterial).where(ProducaoMaterial.op_id == op_id)).all()
    for m in mats:
        m.custo_consumido = m.quantidade_consumida * m.custo_unitario
    return render("producao_materiais.html", request=request, context={
        **_ctx_base(ctx),
        "materiais": mats,
        "op_id": op_id,
    })


# ── Materiais: salvar ─────────────────────────────────────────────────────────

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
    mat = ProducaoMaterial(
        op_id=op_id,
        company_id=ctx.company.id,
        nome=body.get("nome", ""),
        unidade=body.get("unidade", "un"),
        quantidade_planejada=float(body.get("quantidade_planejada", 0)),
        quantidade_consumida=float(body.get("quantidade_consumida", 0)),
        custo_unitario=float(body.get("custo_unitario", 0)),
    )
    session.add(mat); session.commit()
    return JSONResponse({"ok": True})


# ── Materiais: excluir ────────────────────────────────────────────────────────

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


print("[producao] Módulo Controle de Produção carregado — /ferramentas/producao")

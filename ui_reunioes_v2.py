# ============================================================================
# ui_reunioes_v2.py — Módulo de Reuniões aprimorado
# ============================================================================
# O que adiciona:
#   1. MeetingPauta  — itens de pauta estruturados (pré-reunião)
#   2. MeetingAcao   — ações corretivas com owner, prazo, status, prioridade
#   3. Isolamento empresa — todas as queries filtradas por company_id
#   4. Acesso do cliente — role "cliente" vê suas próprias reuniões + ações
#   5. Augur IA      — contexto completo: ata + ações abertas injetados
#   6. Rotas:
#       GET  /reunioes/{id}/pauta          → gerenciar pauta
#       POST /reunioes/{id}/pauta          → adicionar item
#       POST /reunioes/{id}/pauta/{pid}/delete
#       POST /reunioes/{id}/pauta/{pid}/toggle  → marcar como discutido
#       GET  /reunioes/{id}/acoes          → listar ações da reunião
#       POST /reunioes/{id}/acoes          → criar ação
#       POST /acoes/{aid}/status           → atualizar status
#       POST /acoes/{aid}/delete
#       GET  /cliente/reunioes             → área do cliente (lista + ações)
# ============================================================================

import json as _json_rv2
from datetime import datetime as _dt_rv2, date as _date_rv2
from typing import Optional as _Opt_rv2, List as _List_rv2

from fastapi import Form as _Form_rv2
from fastapi.responses import HTMLResponse as _HTML_rv2, RedirectResponse as _RR_rv2
from sqlmodel import Field as _Field_rv2, select as _select_rv2, SQLModel as _SQLModel_rv2


# ── Novos modelos ─────────────────────────────────────────────────────────────

class MeetingPauta(_SQLModel_rv2, table=True):
    """Item de pauta pré-reunião."""
    __tablename__ = "meetingpauta"
    id: _Opt_rv2[int] = _Field_rv2(default=None, primary_key=True)
    meeting_id: int = _Field_rv2(index=True, foreign_key="meeting.id")
    company_id: int = _Field_rv2(index=True)
    order_idx: int = _Field_rv2(default=0)
    texto: str = ""
    discutido: bool = False
    created_at: _dt_rv2 = _Field_rv2(default_factory=utcnow)


class MeetingAcao(_SQLModel_rv2, table=True):
    """Ação corretiva estruturada gerada em reunião."""
    __tablename__ = "meetingacao"
    id: _Opt_rv2[int] = _Field_rv2(default=None, primary_key=True)
    meeting_id: int = _Field_rv2(index=True, foreign_key="meeting.id")
    company_id: int = _Field_rv2(index=True)
    client_id: int = _Field_rv2(index=True)

    titulo: str = ""
    descricao: str = ""
    responsavel: str = ""          # nome livre ou user_id serializado
    responsavel_user_id: _Opt_rv2[int] = _Field_rv2(default=None, foreign_key="user.id")
    prazo: str = ""                # DD/MM/AAAA
    prioridade: str = "media"      # alta | media | baixa
    status: str = "aberta"         # aberta | em_andamento | concluida | cancelada

    created_at: _dt_rv2 = _Field_rv2(default_factory=utcnow)
    updated_at: _dt_rv2 = _Field_rv2(default_factory=utcnow)


# Criar tabelas se não existirem
try:
    _SQLModel_rv2.metadata.create_all(engine, tables=[
        MeetingPauta.__table__,
        MeetingAcao.__table__,
    ])
    print("[reunioes_v2] ✅ Tabelas MeetingPauta e MeetingAcao garantidas.")
except Exception as _e_rv2_create:
    print(f"[reunioes_v2] ⚠️ Erro ao criar tabelas: {_e_rv2_create}")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _rv2_get_meeting(session, company_id: int, meeting_id: int):
    """Retorna meeting se pertencer à empresa, senão None."""
    mt = session.get(Meeting, int(meeting_id))
    if not mt or mt.company_id != company_id:
        return None
    return mt


def _rv2_acoes_context(acoes: list) -> str:
    """Formata ações para injetar no contexto do Augur."""
    if not acoes:
        return ""
    lines = []
    for a in acoes:
        status_label = {
            "aberta": "Aberta",
            "em_andamento": "Em andamento",
            "concluida": "Concluída",
            "cancelada": "Cancelada",
        }.get(a.status, a.status)
        prazo_txt = f" | Prazo: {a.prazo}" if a.prazo else ""
        resp_txt = f" | Resp: {a.responsavel}" if a.responsavel else ""
        lines.append(
            f"  [{a.prioridade.upper()}] {a.titulo} — {status_label}{prazo_txt}{resp_txt}"
        )
    return "\n".join(lines)


# ── Templates ─────────────────────────────────────────────────────────────────

TEMPLATES["reunioes_pauta.html"] = r"""
{% extends "base.html" %}
{% block content %}
<div class="container py-4" style="max-width:760px">
  <div class="d-flex align-items-center gap-2 mb-3">
    <a href="/reunioes/{{ meeting.id }}" class="btn btn-sm btn-outline-secondary">← Voltar</a>
    <h5 class="mb-0">Pauta — {{ meeting.title or 'Reunião' }}</h5>
    {% if meeting.meeting_date %}<span class="badge bg-secondary">{{ meeting.meeting_date }}</span>{% endif %}
  </div>

  {% if flash %}<div class="alert alert-info py-2">{{ flash }}</div>{% endif %}

  {% if role in ['admin','equipe'] %}
  <form method="post" action="/reunioes/{{ meeting.id }}/pauta" class="mb-4">
    <div class="input-group">
      <input type="text" name="texto" class="form-control" placeholder="Novo item de pauta..." required maxlength="300">
      <button class="btn btn-primary">Adicionar</button>
    </div>
  </form>
  {% endif %}

  {% if not itens %}
    <div class="text-muted small">Nenhum item de pauta cadastrado.</div>
  {% else %}
  <ul class="list-group">
    {% for item in itens %}
    <li class="list-group-item d-flex justify-content-between align-items-center gap-2
      {% if item.discutido %}list-group-item-success{% endif %}">
      <span {% if item.discutido %}style="text-decoration:line-through;opacity:.6"{% endif %}>
        {{ item.texto }}
      </span>
      {% if role in ['admin','equipe'] %}
      <div class="d-flex gap-1 flex-shrink-0">
        <form method="post" action="/reunioes/{{ meeting.id }}/pauta/{{ item.id }}/toggle">
          <button class="btn btn-sm {% if item.discutido %}btn-outline-secondary{% else %}btn-outline-success{% endif %}" title="{% if item.discutido %}Marcar como pendente{% else %}Marcar como discutido{% endif %}">
            {% if item.discutido %}↩{% else %}✓{% endif %}
          </button>
        </form>
        <form method="post" action="/reunioes/{{ meeting.id }}/pauta/{{ item.id }}/delete" onsubmit="return confirm('Remover item?')">
          <button class="btn btn-sm btn-outline-danger">✕</button>
        </form>
      </div>
      {% endif %}
    </li>
    {% endfor %}
  </ul>
  {% endif %}
</div>
{% endblock %}
"""

TEMPLATES["reunioes_acoes.html"] = r"""
{% extends "base.html" %}
{% block content %}
<div class="container py-4" style="max-width:900px">
  <div class="d-flex align-items-center gap-2 mb-3">
    <a href="/reunioes/{{ meeting.id }}" class="btn btn-sm btn-outline-secondary">← Reunião</a>
    <h5 class="mb-0">Ações — {{ meeting.title or 'Reunião' }}</h5>
    {% if meeting.meeting_date %}<span class="badge bg-secondary">{{ meeting.meeting_date }}</span>{% endif %}
  </div>

  {% if flash %}<div class="alert alert-info py-2">{{ flash }}</div>{% endif %}

  {% if role in ['admin','equipe'] %}
  <div class="card mb-4 p-3">
    <h6 class="mb-3">Nova ação corretiva</h6>
    <form method="post" action="/reunioes/{{ meeting.id }}/acoes">
      <div class="row g-2">
        <div class="col-12">
          <input type="text" name="titulo" class="form-control" placeholder="Título da ação *" required maxlength="200">
        </div>
        <div class="col-12">
          <textarea name="descricao" class="form-control" rows="2" placeholder="Descrição (opcional)" maxlength="1000"></textarea>
        </div>
        <div class="col-md-4">
          <select name="responsavel_user_id" class="form-select">
            <option value="">Responsável (opcional)</option>
            {% for m in membros %}
            <option value="{{ m.user_id }}">{{ m.name }}</option>
            {% endfor %}
          </select>
        </div>
        <div class="col-md-3">
          <input type="text" name="responsavel" class="form-control" placeholder="Ou nome livre" maxlength="100">
        </div>
        <div class="col-md-2">
          <input type="text" name="prazo" class="form-control" placeholder="DD/MM/AAAA" maxlength="10">
        </div>
        <div class="col-md-3">
          <select name="prioridade" class="form-select">
            <option value="alta">Alta prioridade</option>
            <option value="media" selected>Média prioridade</option>
            <option value="baixa">Baixa prioridade</option>
          </select>
        </div>
        <div class="col-12">
          <button class="btn btn-primary">Criar ação</button>
        </div>
      </div>
    </form>
  </div>
  {% endif %}

  {% set status_order = ['aberta','em_andamento','concluida','cancelada'] %}
  {% set status_labels = {'aberta':'Aberta','em_andamento':'Em andamento','concluida':'Concluída','cancelada':'Cancelada'} %}
  {% set prioridade_colors = {'alta':'danger','media':'warning','baixa':'secondary'} %}

  {% if not acoes %}
    <div class="text-muted small">Nenhuma ação registrada para esta reunião.</div>
  {% else %}
  <div class="d-flex flex-column gap-2">
    {% for a in acoes %}
    <div class="card p-3 {% if a.status == 'concluida' %}opacity-75{% endif %}">
      <div class="d-flex justify-content-between align-items-start gap-2 flex-wrap">
        <div>
          <span class="badge text-bg-{{ prioridade_colors.get(a.prioridade,'secondary') }} me-1">{{ a.prioridade|upper }}</span>
          <strong {% if a.status == 'concluida' %}style="text-decoration:line-through"{% endif %}>{{ a.titulo }}</strong>
          {% if a.descricao %}<div class="text-muted small mt-1">{{ a.descricao }}</div>{% endif %}
          <div class="small mt-1 text-muted">
            {% if a.responsavel %}Resp: <b>{{ a.responsavel }}</b>{% endif %}
            {% if a.prazo %} · Prazo: <b>{{ a.prazo }}</b>{% endif %}
          </div>
        </div>
        <div class="d-flex gap-1 align-items-start flex-shrink-0">
          {% if role in ['admin','equipe'] %}
          <form method="post" action="/acoes/{{ a.id }}/status" class="d-flex gap-1">
            <select name="status" class="form-select form-select-sm" style="width:auto" onchange="this.form.submit()">
              {% for s in ['aberta','em_andamento','concluida','cancelada'] %}
              <option value="{{ s }}" {% if a.status == s %}selected{% endif %}>
                {{ {'aberta':'Aberta','em_andamento':'Em andamento','concluida':'Concluída','cancelada':'Cancelada'}[s] }}
              </option>
              {% endfor %}
            </select>
          </form>
          <form method="post" action="/acoes/{{ a.id }}/delete" onsubmit="return confirm('Excluir ação?')">
            <button class="btn btn-sm btn-outline-danger">✕</button>
          </form>
          {% else %}
          <span class="badge text-bg-{{ {'aberta':'warning','em_andamento':'info','concluida':'success','cancelada':'secondary'}.get(a.status,'secondary') }}">
            {{ status_labels.get(a.status, a.status) }}
          </span>
          {% endif %}
        </div>
      </div>
    </div>
    {% endfor %}
  </div>
  {% endif %}
</div>
{% endblock %}
"""

TEMPLATES["cliente_reunioes.html"] = r"""
{% extends "base.html" %}
{% block content %}
<div class="container py-4" style="max-width:900px">
  <h4 class="mb-1">Minhas Reuniões</h4>
  <p class="text-muted small mb-4">Histórico de reuniões e ações corretivas em aberto.</p>

  {% if flash %}<div class="alert alert-info py-2">{{ flash }}</div>{% endif %}

  {# ── Ações abertas ── #}
  {% if acoes_abertas %}
  <div class="card mb-4 border-warning">
    <div class="card-header bg-warning bg-opacity-10 fw-semibold">
      ⚡ Ações em aberto ({{ acoes_abertas|length }})
    </div>
    <ul class="list-group list-group-flush">
      {% for a in acoes_abertas %}
      <li class="list-group-item d-flex justify-content-between align-items-center gap-2">
        <div>
          <span class="badge text-bg-{{ {'alta':'danger','media':'warning','baixa':'secondary'}.get(a.prioridade,'secondary') }} me-1">{{ a.prioridade }}</span>
          <strong>{{ a.titulo }}</strong>
          {% if a.prazo %}<span class="text-muted small ms-2">Prazo: {{ a.prazo }}</span>{% endif %}
          {% if a.responsavel %}<span class="text-muted small ms-2">· {{ a.responsavel }}</span>{% endif %}
        </div>
        <span class="badge text-bg-{{ {'aberta':'warning','em_andamento':'info'}.get(a.status,'secondary') }}">
          {{ {'aberta':'Aberta','em_andamento':'Em andamento'}.get(a.status, a.status) }}
        </span>
      </li>
      {% endfor %}
    </ul>
  </div>
  {% endif %}

  {# ── Lista de reuniões ── #}
  {% if not reunioes %}
    <div class="text-muted">Nenhuma reunião registrada.</div>
  {% else %}
  <div class="d-flex flex-column gap-3">
    {% for r in reunioes %}
    <div class="card p-3">
      <div class="d-flex justify-content-between align-items-start gap-2 flex-wrap">
        <div>
          <div class="fw-semibold">{{ r.title or 'Reunião' }}</div>
          {% if r.meeting_date %}<div class="text-muted small">{{ r.meeting_date }}</div>{% endif %}
        </div>
        <a href="/reunioes/{{ r.id }}" class="btn btn-sm btn-outline-primary">Ver detalhes</a>
      </div>
      {% if r.summary_text %}
      <div class="mt-2 text-muted small" style="border-left:3px solid #dee2e6;padding-left:.75rem">
        {{ r.summary_text[:300] }}{% if r.summary_text|length > 300 %}…{% endif %}
      </div>
      {% endif %}
      {% if r.acoes_count %}
      <div class="mt-2">
        <span class="badge text-bg-warning">{{ r.acoes_count }} ação(ões) em aberto</span>
      </div>
      {% endif %}
    </div>
    {% endfor %}
  </div>
  {% endif %}
</div>
{% endblock %}
"""


# ── Rotas — Pauta ─────────────────────────────────────────────────────────────

@app.get("/reunioes/{meeting_id}/pauta", response_class=_HTML_rv2)
@require_login
async def rv2_pauta_get(request: Request, session: Session = Depends(get_session), meeting_id: int = 0):
    ctx = get_tenant_context(request, session)
    if not ctx:
        return _RR_rv2("/login", status_code=303)
    mt = _rv2_get_meeting(session, ctx.company.id, meeting_id)
    if not mt:
        return render("error.html", request=request, context={"message": "Reunião não encontrada."}, status_code=404)
    if not ensure_can_access_client(ctx, mt.client_id):
        return render("error.html", request=request, context={"message": "Sem permissão."}, status_code=403)

    itens = session.exec(
        _select_rv2(MeetingPauta)
        .where(MeetingPauta.meeting_id == mt.id)
        .order_by(MeetingPauta.order_idx, MeetingPauta.id)
    ).all()

    active_client_id = get_active_client_id(request, session, ctx)
    current_client = get_client_or_none(session, ctx.company.id, active_client_id)
    return render("reunioes_pauta.html", request=request, context={
        "current_user": ctx.user, "current_company": ctx.company,
        "role": ctx.membership.role, "current_client": current_client,
        "meeting": mt, "itens": itens, "flash": request.session.pop("flash", None),
    })


@app.post("/reunioes/{meeting_id}/pauta")
@require_role({"admin", "equipe"})
async def rv2_pauta_post(request: Request, session: Session = Depends(get_session),
                         meeting_id: int = 0, texto: str = _Form_rv2("")):
    ctx = get_tenant_context(request, session)
    assert ctx
    mt = _rv2_get_meeting(session, ctx.company.id, meeting_id)
    if not mt:
        return _RR_rv2("/reunioes", status_code=303)
    texto = texto.strip()
    if texto:
        max_idx = session.exec(
            _select_rv2(MeetingPauta.order_idx)
            .where(MeetingPauta.meeting_id == mt.id)
            .order_by(MeetingPauta.order_idx.desc())
        ).first() or 0
        item = MeetingPauta(meeting_id=mt.id, company_id=ctx.company.id,
                             texto=texto, order_idx=max_idx + 1)
        session.add(item)
        session.commit()
    return _RR_rv2(f"/reunioes/{mt.id}/pauta", status_code=303)


@app.post("/reunioes/{meeting_id}/pauta/{pauta_id}/toggle")
@require_role({"admin", "equipe"})
async def rv2_pauta_toggle(request: Request, session: Session = Depends(get_session),
                            meeting_id: int = 0, pauta_id: int = 0):
    ctx = get_tenant_context(request, session)
    assert ctx
    mt = _rv2_get_meeting(session, ctx.company.id, meeting_id)
    if not mt:
        return _RR_rv2("/reunioes", status_code=303)
    item = session.get(MeetingPauta, int(pauta_id))
    if item and item.meeting_id == mt.id:
        item.discutido = not item.discutido
        session.add(item)
        session.commit()
    return _RR_rv2(f"/reunioes/{mt.id}/pauta", status_code=303)


@app.post("/reunioes/{meeting_id}/pauta/{pauta_id}/delete")
@require_role({"admin", "equipe"})
async def rv2_pauta_delete(request: Request, session: Session = Depends(get_session),
                            meeting_id: int = 0, pauta_id: int = 0):
    ctx = get_tenant_context(request, session)
    assert ctx
    mt = _rv2_get_meeting(session, ctx.company.id, meeting_id)
    if not mt:
        return _RR_rv2("/reunioes", status_code=303)
    item = session.get(MeetingPauta, int(pauta_id))
    if item and item.meeting_id == mt.id:
        session.delete(item)
        session.commit()
    return _RR_rv2(f"/reunioes/{mt.id}/pauta", status_code=303)


# ── Rotas — Ações ─────────────────────────────────────────────────────────────

@app.get("/reunioes/{meeting_id}/acoes", response_class=_HTML_rv2)
@require_login
async def rv2_acoes_get(request: Request, session: Session = Depends(get_session), meeting_id: int = 0):
    ctx = get_tenant_context(request, session)
    if not ctx:
        return _RR_rv2("/login", status_code=303)
    mt = _rv2_get_meeting(session, ctx.company.id, meeting_id)
    if not mt:
        return render("error.html", request=request, context={"message": "Reunião não encontrada."}, status_code=404)
    if not ensure_can_access_client(ctx, mt.client_id):
        return render("error.html", request=request, context={"message": "Sem permissão."}, status_code=403)

    acoes = session.exec(
        _select_rv2(MeetingAcao)
        .where(MeetingAcao.meeting_id == mt.id)
        .order_by(MeetingAcao.created_at.desc())
    ).all()

    # Membros da empresa para dropdown de responsável
    membros = []
    if ctx.membership.role in {"admin", "equipe"}:
        mships = session.exec(_select_rv2(Membership).where(Membership.company_id == ctx.company.id)).all()
        for ms in mships:
            u = session.get(User, ms.user_id)
            if u:
                membros.append({"user_id": u.id, "name": u.name})

    active_client_id = get_active_client_id(request, session, ctx)
    current_client = get_client_or_none(session, ctx.company.id, active_client_id)
    return render("reunioes_acoes.html", request=request, context={
        "current_user": ctx.user, "current_company": ctx.company,
        "role": ctx.membership.role, "current_client": current_client,
        "meeting": mt, "acoes": acoes, "membros": membros,
        "flash": request.session.pop("flash", None),
    })


@app.post("/reunioes/{meeting_id}/acoes")
@require_role({"admin", "equipe"})
async def rv2_acoes_post(
    request: Request,
    session: Session = Depends(get_session),
    meeting_id: int = 0,
    titulo: str = _Form_rv2(""),
    descricao: str = _Form_rv2(""),
    responsavel: str = _Form_rv2(""),
    responsavel_user_id: str = _Form_rv2(""),
    prazo: str = _Form_rv2(""),
    prioridade: str = _Form_rv2("media"),
):
    ctx = get_tenant_context(request, session)
    assert ctx
    mt = _rv2_get_meeting(session, ctx.company.id, meeting_id)
    if not mt:
        return _RR_rv2("/reunioes", status_code=303)

    titulo = titulo.strip()
    if not titulo:
        set_flash(request, "Título obrigatório.")
        return _RR_rv2(f"/reunioes/{mt.id}/acoes", status_code=303)

    # Se selecionou usuário do dropdown, usa o nome dele como responsável
    resp_uid = int(responsavel_user_id) if responsavel_user_id.isdigit() else None
    resp_nome = responsavel.strip()
    if resp_uid and not resp_nome:
        u = session.get(User, resp_uid)
        if u:
            resp_nome = u.name

    acao = MeetingAcao(
        meeting_id=mt.id,
        company_id=ctx.company.id,
        client_id=mt.client_id,
        titulo=titulo,
        descricao=descricao.strip(),
        responsavel=resp_nome,
        responsavel_user_id=resp_uid,
        prazo=_normalize_date_input(prazo),
        prioridade=prioridade if prioridade in ("alta", "media", "baixa") else "media",
        status="aberta",
    )
    session.add(acao)
    session.commit()
    set_flash(request, "Ação criada.")
    return _RR_rv2(f"/reunioes/{mt.id}/acoes", status_code=303)


@app.post("/acoes/{acao_id}/status")
@require_role({"admin", "equipe"})
async def rv2_acao_status(
    request: Request,
    session: Session = Depends(get_session),
    acao_id: int = 0,
    status: str = _Form_rv2("aberta"),
):
    ctx = get_tenant_context(request, session)
    assert ctx
    acao = session.get(MeetingAcao, int(acao_id))
    if acao and acao.company_id == ctx.company.id:
        if status in ("aberta", "em_andamento", "concluida", "cancelada"):
            acao.status = status
            acao.updated_at = utcnow()
            session.add(acao)
            session.commit()
    # Volta para a página de ações da reunião
    if acao:
        return _RR_rv2(f"/reunioes/{acao.meeting_id}/acoes", status_code=303)
    return _RR_rv2("/reunioes", status_code=303)


@app.post("/acoes/{acao_id}/delete")
@require_role({"admin", "equipe"})
async def rv2_acao_delete(request: Request, session: Session = Depends(get_session), acao_id: int = 0):
    ctx = get_tenant_context(request, session)
    assert ctx
    acao = session.get(MeetingAcao, int(acao_id))
    if acao and acao.company_id == ctx.company.id:
        meeting_id = acao.meeting_id
        session.delete(acao)
        session.commit()
        return _RR_rv2(f"/reunioes/{meeting_id}/acoes", status_code=303)
    return _RR_rv2("/reunioes", status_code=303)


# ── Rota do cliente — /cliente/reunioes ───────────────────────────────────────

@app.get("/cliente/reunioes", response_class=_HTML_rv2)
@require_login
async def rv2_cliente_reunioes(request: Request, session: Session = Depends(get_session)):
    ctx = get_tenant_context(request, session)
    if not ctx:
        return _RR_rv2("/login", status_code=303)

    client_id = ctx.membership.client_id or -1

    # Reuniões do cliente (isolado por company_id + client_id)
    meetings_raw = session.exec(
        _select_rv2(Meeting)
        .where(Meeting.company_id == ctx.company.id)
        .where(Meeting.client_id == client_id)
        .order_by(Meeting.created_at.desc())
    ).all()

    # Ações abertas do cliente
    acoes_abertas = session.exec(
        _select_rv2(MeetingAcao)
        .where(MeetingAcao.company_id == ctx.company.id)
        .where(MeetingAcao.client_id == client_id)
        .where(MeetingAcao.status.in_(["aberta", "em_andamento"]))
        .order_by(MeetingAcao.prioridade, MeetingAcao.prazo)
    ).all()

    # Enriquecer reuniões com contagem de ações abertas
    reunioes = []
    for mt in meetings_raw:
        acoes_count = session.exec(
            _select_rv2(MeetingAcao)
            .where(MeetingAcao.meeting_id == mt.id)
            .where(MeetingAcao.status.in_(["aberta", "em_andamento"]))
        ).all()
        reunioes.append({
            "id": mt.id,
            "title": mt.title,
            "meeting_date": mt.meeting_date,
            "summary_text": mt.summary_text,
            "acoes_count": len(acoes_count),
        })

    active_client_id = get_active_client_id(request, session, ctx)
    current_client = get_client_or_none(session, ctx.company.id, active_client_id)
    return render("cliente_reunioes.html", request=request, context={
        "current_user": ctx.user, "current_company": ctx.company,
        "role": ctx.membership.role, "current_client": current_client,
        "reunioes": reunioes, "acoes_abertas": acoes_abertas,
        "flash": request.session.pop("flash", None),
    })


# ── Patch no Augur — injetar atas + ações abertas ────────────────────────────

def _rv2_get_reunioes_nativas_full(session, company_id: int, client_id: int) -> list[dict]:
    """Versão enriquecida: inclui ata completa + ações abertas de cada reunião."""
    try:
        meetings = session.exec(
            _select_rv2(Meeting)
            .where(Meeting.company_id == company_id)
            .where(Meeting.client_id == client_id)
            .order_by(Meeting.created_at.desc())
        ).all()

        result = []
        for mt in meetings[:6]:
            acoes = session.exec(
                _select_rv2(MeetingAcao)
                .where(MeetingAcao.meeting_id == mt.id)
                .where(MeetingAcao.status.in_(["aberta", "em_andamento"]))
            ).all()

            result.append({
                "titulo": mt.title or "Reunião",
                "data": mt.meeting_date or (mt.created_at.strftime("%Y-%m-%d") if mt.created_at else ""),
                "resumo": mt.summary_text or "",
                "ata": mt.notes_text or "",
                "action_items_texto": mt.action_items_text or "",
                "acoes_abertas": _rv2_acoes_context(acoes),
                "source": "nativa",
            })
        return result
    except Exception as _e:
        print(f"[reunioes_v2] Erro ao buscar reuniões nativas full: {_e}")
        return []


# Substitui _get_reunioes_nativas (usada pelo whisper patch) pela versão enriquecida
_get_reunioes_nativas = _rv2_get_reunioes_nativas_full


# Patch no _format_client_context do assistant para incluir ata e ações
_rv2_orig_format = None
try:
    import ai_assistant.assistant as _rv2_asst
    _rv2_orig_format = _rv2_asst._format_client_context

    def _rv2_format_client_context(client_data: dict) -> str:
        base = _rv2_orig_format(client_data)
        # Enriquecer bloco de reuniões com ata e ações abertas
        reunioes = client_data.get("reunioes_recentes", [])
        extra_lines = []
        for r in reunioes[:5]:
            if r.get("ata"):
                extra_lines.append(f"\n  [Ata completa — {r.get('titulo','')}]\n  {r['ata'][:800]}")
            if r.get("acoes_abertas"):
                extra_lines.append(f"\n  [Ações em aberto — {r.get('titulo','')}]\n{r['acoes_abertas']}")
        if extra_lines:
            base += "\n\n=== DETALHES DAS REUNIÕES ===\n" + "\n".join(extra_lines)
        return base

    _rv2_asst._format_client_context = _rv2_format_client_context
    print("[reunioes_v2] ✅ Patch no _format_client_context do Augur aplicado.")
except Exception as _e_rv2_patch:
    print(f"[reunioes_v2] ⚠️ Patch Augur não aplicado: {_e_rv2_patch}")


print("[reunioes_v2] ✅ Módulo de Reuniões v2 carregado.")

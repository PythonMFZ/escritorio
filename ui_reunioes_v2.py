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


# ── Patch dashboard: widget de ações abertas para admin/equipe ────────────────

_RV2_WIDGET = r"""
  {%- if role in ["admin","equipe"] and acoes_abertas_total is defined %}
  <div class="col-12">
    <div class="card p-3" style="border-left:4px solid #f0ad4e;">
      <div class="d-flex justify-content-between align-items-center">
        <div>
          <div class="fw-semibold">⚡ Ações Corretivas em Aberto</div>
          <div class="muted small">
            {% if acoes_abertas_total == 0 %}
              Nenhuma ação em aberto no momento.
            {% else %}
              <b>{{ acoes_abertas_total }}</b> ação(ões) em aberto
              {%- if acoes_alta_prioridade > 0 %} — <span class="text-danger fw-semibold">{{ acoes_alta_prioridade }} alta prioridade</span>{% endif %}.
            {% endif %}
          </div>
        </div>
        <a class="btn btn-outline-warning btn-sm" href="/reunioes">Ver reuniões</a>
      </div>
      {% if acoes_abertas_lista %}
      <div class="mt-2 d-flex flex-column gap-1">
        {% for a in acoes_abertas_lista[:5] %}
        <div class="d-flex align-items-center gap-2 small">
          <span class="badge {% if a.prioridade == 'alta' %}bg-danger{% elif a.prioridade == 'media' %}bg-warning text-dark{% else %}bg-secondary{% endif %}" style="min-width:52px;">{{ a.prioridade }}</span>
          <span class="flex-grow-1">{{ a.titulo }}</span>
          {% if a.prazo %}<span class="muted">{{ a.prazo }}</span>{% endif %}
        </div>
        {% endfor %}
        {% if acoes_abertas_total > 5 %}<div class="muted small">… e mais {{ acoes_abertas_total - 5 }} ação(ões).</div>{% endif %}
      </div>
      {% endif %}
    </div>
  </div>
  {%- endif %}
"""

try:
    _rv2_dash = TEMPLATES.get("dashboard.html", "")
    _rv2_inject_after = '<div class="row g-3">'
    if _rv2_inject_after in _rv2_dash and "acoes_abertas_total" not in _rv2_dash:
        _rv2_dash = _rv2_dash.replace(
            _rv2_inject_after,
            _rv2_inject_after + "\n" + _RV2_WIDGET,
            1,
        )
        TEMPLATES["dashboard.html"] = _rv2_dash
        if hasattr(templates_env.loader, "mapping"):
            templates_env.loader.mapping["dashboard.html"] = _rv2_dash
        print("[reunioes_v2] ✅ Widget de ações abertas injetado no dashboard.")
    else:
        print("[reunioes_v2] ℹ️ Widget dashboard já presente ou template não encontrado.")
except Exception as _e_rv2_dash:
    print(f"[reunioes_v2] ⚠️ Erro ao injetar widget no dashboard: {_e_rv2_dash}")


# ── Patch na rota do dashboard para passar acoes_abertas ─────────────────────

_rv2_orig_dashboard = None
try:
    _rv2_orig_dashboard = app.routes
    # Wrap the dashboard render via middleware-style approach:
    # Instead of patching the route, we patch the render function for dashboard
    _rv2_orig_render = render

    def _rv2_render_with_acoes(template_name, request, context=None, **kwargs):
        ctx_arg = context or {}
        if template_name == "dashboard.html" and ctx_arg.get("role") in ("admin", "equipe"):
            try:
                from sqlmodel import Session as _SRV2
                with _SRV2(engine) as _s_rv2:
                    company_id = ctx_arg.get("current_company") and ctx_arg["current_company"].id
                    if company_id:
                        _acoes = _s_rv2.exec(
                            _select_rv2(MeetingAcao).where(
                                MeetingAcao.company_id == company_id,
                                MeetingAcao.status.in_(["aberta", "em_andamento"])
                            ).order_by(MeetingAcao.created_at.desc())
                        ).all()
                        ctx_arg["acoes_abertas_total"] = len(_acoes)
                        ctx_arg["acoes_alta_prioridade"] = sum(1 for a in _acoes if a.prioridade == "alta")
                        ctx_arg["acoes_abertas_lista"] = _acoes[:10]
            except Exception as _e_rv2_acoes:
                ctx_arg.setdefault("acoes_abertas_total", 0)
                ctx_arg.setdefault("acoes_alta_prioridade", 0)
                ctx_arg.setdefault("acoes_abertas_lista", [])
        return _rv2_orig_render(template_name, request=request, context=ctx_arg, **kwargs)

    render = _rv2_render_with_acoes
    print("[reunioes_v2] ✅ Render do dashboard com ações abertas ativo.")
except Exception as _e_rv2_render:
    print(f"[reunioes_v2] ⚠️ Patch render dashboard não aplicado: {_e_rv2_render}")


# ── /admin/acoes — Central de Ações da empresa ────────────────────────────────

TEMPLATES["admin_acoes.html"] = r"""
{% extends "base.html" %}
{% block content %}
<style>
  .acao-row td { vertical-align:middle; font-size:.83rem; }
  .pri-alta  { color:#ef4444; font-weight:600; }
  .pri-media { color:#f59e0b; }
  .pri-baixa { color:#6b7280; }
  .st-badge  { font-size:.7rem; padding:2px 7px; border-radius:999px; border:1px solid; }
  .st-aberta      { border-color:#60a5fa; color:#3b82f6; background:#eff6ff; }
  .st-em_andamento{ border-color:#f59e0b; color:#d97706; background:#fffbeb; }
  .st-concluida   { border-color:#22c55e; color:#16a34a; background:#f0fdf4; }
  .st-cancelada   { border-color:#d1d5db; color:#6b7280; background:#f9fafb; }
</style>

<div class="d-flex justify-content-between align-items-center mb-3 flex-wrap gap-2">
  <div>
    <h4 class="mb-0">⚡ Central de Ações</h4>
    <div class="muted small">Todas as ações corretivas da empresa — {{ total }} no total</div>
  </div>
  <div class="d-flex gap-2 flex-wrap align-items-center">
    <form method="get" class="d-flex gap-2 flex-wrap">
      <select name="status" class="form-select form-select-sm" onchange="this.form.submit()">
        <option value="" {% if not filtro_status %}selected{% endif %}>Todos os status</option>
        <option value="aberta"       {% if filtro_status=="aberta" %}selected{% endif %}>Abertas</option>
        <option value="em_andamento" {% if filtro_status=="em_andamento" %}selected{% endif %}>Em andamento</option>
        <option value="concluida"    {% if filtro_status=="concluida" %}selected{% endif %}>Concluídas</option>
        <option value="cancelada"    {% if filtro_status=="cancelada" %}selected{% endif %}>Canceladas</option>
      </select>
      <select name="prioridade" class="form-select form-select-sm" onchange="this.form.submit()">
        <option value="" {% if not filtro_pri %}selected{% endif %}>Todas as prioridades</option>
        <option value="alta"  {% if filtro_pri=="alta" %}selected{% endif %}>Alta</option>
        <option value="media" {% if filtro_pri=="media" %}selected{% endif %}>Média</option>
        <option value="baixa" {% if filtro_pri=="baixa" %}selected{% endif %}>Baixa</option>
      </select>
      <select name="client_id" class="form-select form-select-sm" onchange="this.form.submit()">
        <option value="">Todos os clientes</option>
        {% for c in clientes %}
          <option value="{{ c.id }}" {% if filtro_client == c.id|string %}selected{% endif %}>{{ c.name }}</option>
        {% endfor %}
      </select>
    </form>
  </div>
</div>

<!-- KPIs rápidos -->
<div class="d-flex gap-3 mb-3 flex-wrap">
  {% for lbl, val, cor in kpis %}
  <div class="card p-2 px-3" style="border-left:3px solid {{ cor }}; min-width:120px;">
    <div class="fw-bold" style="color:{{ cor }};">{{ val }}</div>
    <div class="muted" style="font-size:.72rem;">{{ lbl }}</div>
  </div>
  {% endfor %}
</div>

{% if not acoes %}
  <div class="alert alert-info">Nenhuma ação encontrada com os filtros selecionados.</div>
{% else %}
<div class="card p-0 overflow-hidden">
  <div class="table-responsive">
  <table class="table table-hover mb-0">
    <thead class="table-light">
      <tr>
        <th>Ação</th>
        <th>Cliente</th>
        <th>Prioridade</th>
        <th>Status</th>
        <th>Responsável</th>
        <th>Prazo</th>
        <th>Reunião</th>
        <th></th>
      </tr>
    </thead>
    <tbody>
      {% for a in acoes %}
      <tr class="acao-row">
        <td>
          <div class="fw-semibold">{{ a.titulo or "—" }}</div>
          {% if a.descricao %}<div class="muted" style="font-size:.72rem;">{{ a.descricao[:60] }}{% if a.descricao|length > 60 %}…{% endif %}</div>{% endif %}
        </td>
        <td class="muted">{{ a._client_name }}</td>
        <td class="pri-{{ a.prioridade }}">{{ a.prioridade|capitalize }}</td>
        <td><span class="st-badge st-{{ a.status }}">{{ a.status|replace("_"," ")|capitalize }}</span></td>
        <td class="muted">{{ a.responsavel or "—" }}</td>
        <td class="muted">{{ a.prazo or "—" }}</td>
        <td><a href="/reunioes/{{ a.meeting_id }}" class="muted small">ver reunião</a></td>
        <td>
          <form method="post" action="/acoes/{{ a.id }}/status" class="d-inline">
            <select name="status" class="form-select form-select-sm" style="font-size:.7rem;padding:2px 4px;" onchange="this.form.submit()">
              {% for s in ["aberta","em_andamento","concluida","cancelada"] %}
              <option value="{{ s }}" {% if s==a.status %}selected{% endif %}>{{ s|replace("_"," ")|capitalize }}</option>
              {% endfor %}
            </select>
          </form>
        </td>
      </tr>
      {% endfor %}
    </tbody>
  </table>
  </div>
</div>
{% endif %}
{% endblock %}
"""

if hasattr(templates_env.loader, "mapping"):
    templates_env.loader.mapping["admin_acoes.html"] = TEMPLATES["admin_acoes.html"]


@app.get("/admin/acoes", response_class=_HTML_rv2)
@require_login
async def admin_acoes_central(request: Request, session: Session = Depends(get_session)):
    ctx = get_tenant_context(request, session)
    if not ctx or ctx.membership.role not in ("admin", "equipe"):
        return _RR_rv2("/", status_code=303)

    filtro_status  = request.query_params.get("status", "")
    filtro_pri     = request.query_params.get("prioridade", "")
    filtro_client  = request.query_params.get("client_id", "")

    q = _select_rv2(MeetingAcao).where(MeetingAcao.company_id == ctx.company.id)
    if filtro_status:
        q = q.where(MeetingAcao.status == filtro_status)
    if filtro_pri:
        q = q.where(MeetingAcao.prioridade == filtro_pri)
    if filtro_client and filtro_client.isdigit():
        q = q.where(MeetingAcao.client_id == int(filtro_client))
    q = q.order_by(MeetingAcao.created_at.desc())
    acoes_raw = session.exec(q).all()

    # Enriquecer com nome do cliente
    acoes = []
    for a in acoes_raw:
        c = session.get(Client, a.client_id)
        a._client_name = c.name if c else f"#{a.client_id}"
        acoes.append(a)

    clientes = session.exec(_select_rv2(Client).where(Client.company_id == ctx.company.id)).all()

    # KPIs
    todas = session.exec(_select_rv2(MeetingAcao).where(MeetingAcao.company_id == ctx.company.id)).all()
    kpis = [
        ("Total",        len(todas),                                                        "#6366f1"),
        ("Abertas",      sum(1 for a in todas if a.status == "aberta"),                    "#3b82f6"),
        ("Em andamento", sum(1 for a in todas if a.status == "em_andamento"),              "#f59e0b"),
        ("Alta prioridade", sum(1 for a in todas if a.prioridade == "alta" and a.status not in ("concluida","cancelada")), "#ef4444"),
        ("Concluídas",   sum(1 for a in todas if a.status == "concluida"),                 "#22c55e"),
    ]

    cc = get_client_or_none(session, ctx.company.id, get_active_client_id(request, session, ctx))
    return render("admin_acoes.html", request=request, context={
        "current_user": ctx.user, "current_company": ctx.company,
        "role": ctx.membership.role, "current_client": cc,
        "acoes": acoes, "total": len(acoes_raw),
        "filtro_status": filtro_status, "filtro_pri": filtro_pri, "filtro_client": filtro_client,
        "clientes": clientes, "kpis": kpis,
    })


# Registra no menu
try:
    FEATURE_KEYS["acoes_central"] = {
        "title": "⚡ Central de Ações",
        "desc": "Todas as ações corretivas da empresa em um lugar.",
        "href": "/admin/acoes",
    }
    FEATURE_VISIBLE_ROLES["acoes_central"] = {"admin", "equipe"}
    ROLE_DEFAULT_FEATURES.setdefault("admin", set()).add("acoes_central")
    ROLE_DEFAULT_FEATURES.setdefault("equipe", set()).add("acoes_central")
    for _grp in FEATURE_GROUPS:
        if _grp.get("key") == "gestao_interna":
            if "acoes_central" not in _grp.get("features", []):
                _grp["features"].append("acoes_central")
            break
    print("[reunioes_v2] ✅ Central de Ações registrada no menu.")
except Exception as _e_ac:
    print(f"[reunioes_v2] ⚠️ Erro ao registrar central de ações: {_e_ac}")


print("[reunioes_v2] ✅ Módulo de Reuniões v2 carregado.")

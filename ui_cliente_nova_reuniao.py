# ============================================================================
# ui_cliente_nova_reuniao.py — Permite que clientes (gestor/usuario) criem
#                              reuniões no seu próprio client_id
# ============================================================================
# Adiciona:
#   POST /cliente/reunioes/nova   → cria reunião vinculada ao client_id do user
# Atualiza:
#   cliente_reunioes.html         → botão "Nova Reunião" + modal inline
# ============================================================================

from fastapi.responses import HTMLResponse as _HTML_cnr, RedirectResponse as _RR_cnr
from fastapi import Request as _Req_cnr, Depends as _Dep_cnr, Form as _Form_cnr
from sqlmodel import Session as _Sess_cnr

# ── Rota: criar reunião pelo cliente ─────────────────────────────────────────

@app.post("/cliente/reunioes/nova")
@require_login
async def cnr_nova_reuniao(
    request: _Req_cnr,
    session: _Sess_cnr = _Dep_cnr(get_session),
    title: str = _Form_cnr(""),
    meeting_date: str = _Form_cnr(""),
):
    ctx = get_tenant_context(request, session)
    if not ctx:
        return _RR_cnr("/login", status_code=303)

    client_id = ctx.membership.client_id
    if not client_id:
        set_flash(request, "❌ Você não está vinculado a nenhum cliente.")
        return _RR_cnr("/cliente/reunioes", status_code=303)

    title = title.strip()
    if not title:
        set_flash(request, "❌ Informe um título para a reunião.")
        return _RR_cnr("/cliente/reunioes", status_code=303)

    # Normaliza data dd/mm/aaaa
    date_str = meeting_date.strip()
    if date_str and "-" in date_str:
        # HTML date input retorna yyyy-mm-dd; converte para dd/mm/aaaa
        try:
            parts = date_str.split("-")
            date_str = f"{parts[2]}/{parts[1]}/{parts[0]}"
        except Exception:
            date_str = date_str

    try:
        mt = Meeting(
            company_id=ctx.company.id,
            client_id=client_id,
            created_by_user_id=ctx.user.id,
            title=title,
            meeting_date=date_str,
            source="manual",
            updated_at=utcnow(),
        )
        session.add(mt)
        session.commit()
        session.refresh(mt)
        set_flash(request, f"✅ Reunião '{title}' criada.")
        return _RR_cnr(f"/reunioes/{mt.id}", status_code=303)
    except Exception as e:
        print(f"[cnr] ⚠️ criar reunião: {e}")
        set_flash(request, "❌ Erro ao criar reunião.")
        return _RR_cnr("/cliente/reunioes", status_code=303)


# ── Atualiza cliente_reunioes.html para incluir botão Nova Reunião ────────────

_CNR_HEADER_NEW = r"""
<div class="d-flex justify-content-between align-items-center mb-1 flex-wrap gap-2">
  <div>
    <h4 class="mb-0">Minhas Reuniões</h4>
    <p class="text-muted small mb-0">Histórico de reuniões e ações corretivas em aberto.</p>
  </div>
  <button class="btn btn-primary btn-sm" data-bs-toggle="modal" data-bs-target="#modalNovaReuniao">
    ➕ Nova Reunião
  </button>
</div>

<!-- Modal Nova Reunião -->
<div class="modal fade" id="modalNovaReuniao" tabindex="-1" aria-labelledby="modalNovaReuniaoLabel" aria-hidden="true">
  <div class="modal-dialog modal-dialog-centered">
    <div class="modal-content">
      <div class="modal-header">
        <h5 class="modal-title" id="modalNovaReuniaoLabel">➕ Nova Reunião</h5>
        <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Fechar"></button>
      </div>
      <form method="post" action="/cliente/reunioes/nova">
        <div class="modal-body">
          <div class="mb-3">
            <label class="form-label fw-semibold">Título <span class="text-danger">*</span></label>
            <input type="text" name="title" class="form-control" placeholder="Ex: Reunião de Acompanhamento" required autofocus>
          </div>
          <div class="mb-3">
            <label class="form-label fw-semibold">Data da Reunião</label>
            <input type="date" name="meeting_date" class="form-control">
          </div>
        </div>
        <div class="modal-footer">
          <button type="button" class="btn btn-outline-secondary btn-sm" data-bs-dismiss="modal">Cancelar</button>
          <button type="submit" class="btn btn-primary btn-sm">Criar Reunião</button>
        </div>
      </form>
    </div>
  </div>
</div>
"""

_CNR_OLD_HEADER = '<div class="container py-4" style="max-width:900px">\n  <h4 class="mb-1">Minhas Reuniões</h4>\n  <p class="text-muted small mb-4">Histórico de reuniões e ações corretivas em aberto.</p>'
_CNR_NEW_HEADER = '<div class="container py-4" style="max-width:900px">\n' + _CNR_HEADER_NEW + '\n'

try:
    _tpl_cnr = TEMPLATES.get("cliente_reunioes.html", "")
    if _tpl_cnr and "modalNovaReuniao" not in _tpl_cnr:
        _tpl_cnr = _tpl_cnr.replace(_CNR_OLD_HEADER, _CNR_NEW_HEADER, 1)
        TEMPLATES["cliente_reunioes.html"] = _tpl_cnr
        if hasattr(templates_env.loader, "mapping"):
            templates_env.loader.mapping["cliente_reunioes.html"] = _tpl_cnr
        print("[cnr] ✅ Botão 'Nova Reunião' injetado em cliente_reunioes.html.")
    elif "modalNovaReuniao" in _tpl_cnr:
        print("[cnr] ℹ️ Modal já presente.")
    else:
        print("[cnr] ⚠️ Template cliente_reunioes.html não encontrado — registrando do zero.")

        TEMPLATES["cliente_reunioes.html"] = r"""
{% extends "base.html" %}
{% block content %}
<div class="container py-4" style="max-width:900px">
""" + _CNR_HEADER_NEW + r"""
  {% if flash %}<div class="alert alert-info py-2 mt-3">{{ flash }}</div>{% endif %}

  {% if acoes_abertas %}
  <div class="card mb-4 border-warning mt-3">
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

  {% if not reunioes %}
    <div class="text-muted mt-3">Nenhuma reunião registrada.</div>
  {% else %}
  <div class="d-flex flex-column gap-3 mt-3">
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
        if hasattr(templates_env.loader, "mapping"):
            templates_env.loader.mapping["cliente_reunioes.html"] = TEMPLATES["cliente_reunioes.html"]
        print("[cnr] ✅ cliente_reunioes.html registrado do zero com modal.")

except Exception as _e_cnr:
    print(f"[cnr] ⚠️ Erro: {_e_cnr}")

print("[cnr] ✅ Módulo cliente nova reunião carregado.")

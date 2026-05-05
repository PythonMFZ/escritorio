# ============================================================================
# PATCH — Cadastro + Convite de Membros + Fix URL
# ============================================================================
# 1. /cadastro — tela de auto-cadastro (nova empresa + admin)
# 2. /admin/members/convidar — admin convida novo membro para a empresa
# 3. /convite-membro/{token} — aceite do convite de membro
# 4. Fix URL convite: força app.maffezzollicapital.com.br
# ============================================================================

import hmac as _hmac_cc
import hashlib as _hashlib_cc
import json as _json_cc
import os as _os_cc
from datetime import datetime as _dt_cc, timedelta as _td_cc
from typing import Optional as _Opt_cc
from sqlmodel import Field as _F_cc, SQLModel as _SM_cc, select as _sel_cc
from fastapi import Request as _Req_cc, Depends as _Dep_cc, Form as _Form_cc
from fastapi.responses import HTMLResponse as _HTML_cc, RedirectResponse as _RR_cc, JSONResponse as _JSON_cc


# ── Fix 1: URL de convite sempre usa domínio de produção ─────────────────────

_PROD_URL = "https://app.maffezzollicapital.com.br"

def _build_invite_url_fixed(request, *, token: str) -> str:
    """Sempre usa o domínio de produção para links de convite."""
    force_url = _os_cc.environ.get("PUBLIC_BASE_URL", "").rstrip("/")
    base = force_url if force_url else _PROD_URL
    return f"{base}/convite/{token}"

globals()['_build_invite_url'] = _build_invite_url_fixed
print("[cadastro_convite] ✅ _build_invite_url corrigido para produção")


# ── Modelo: ConviteMembro ─────────────────────────────────────────────────────

class ConviteMembro(_SM_cc, table=True):
    __tablename__  = "convitemembro"
    __table_args__ = {"extend_existing": True}
    id:             _Opt_cc[int] = _F_cc(default=None, primary_key=True)
    company_id:     int          = _F_cc(index=True)
    created_by_id:  int          = _F_cc(index=True)
    email:          str          = _F_cc(default="", index=True)
    role:           str          = _F_cc(default="equipe")
    token:          str          = _F_cc(default="", index=True)
    status:         str          = _F_cc(default="pendente")
    expires_at:     str          = _F_cc(default="")
    created_at:     str          = _F_cc(default="")

try:
    _SM_cc.metadata.create_all(engine, tables=[ConviteMembro.__table__])
except Exception as _e_cc:
    print(f"[cadastro_convite] Tabela convitemembro: {_e_cc}")


def _gerar_token_cc() -> str:
    import secrets
    return secrets.token_urlsafe(32)


# ── Templates ─────────────────────────────────────────────────────────────────

TEMPLATES["cadastro.html"] = """
{% extends "base.html" %}
{% block content %}
<div class="row justify-content-center mt-5">
  <div class="col-md-6 col-lg-5">
    <div class="card p-4">
      <div class="text-center mb-4">
        <img src="/static/logo.png" alt="Maffezzolli Capital" style="height:40px;">
        <h4 class="mt-3 mb-1">Criar sua conta</h4>
        <div class="muted small">Cadastre sua empresa e comece a usar o sistema</div>
      </div>

      {% if error %}
      <div class="alert alert-danger">{{ error }}</div>
      {% endif %}

      <form method="post" action="/cadastro">
        <div class="mb-3">
          <label class="form-label fw-semibold small">Nome da empresa</label>
          <input type="text" name="company_name" class="form-control" required
                 placeholder="Ex: Construtora ABC Ltda" value="{{ form.company_name or '' }}">
        </div>
        <div class="mb-3">
          <label class="form-label fw-semibold small">CNPJ</label>
          <input type="text" name="cnpj" class="form-control"
                 placeholder="00.000.000/0000-00" value="{{ form.cnpj or '' }}">
        </div>
        <hr>
        <div class="mb-3">
          <label class="form-label fw-semibold small">Seu nome completo</label>
          <input type="text" name="name" class="form-control" required
                 placeholder="Nome do responsável" value="{{ form.name or '' }}">
        </div>
        <div class="mb-3">
          <label class="form-label fw-semibold small">E-mail</label>
          <input type="email" name="email" class="form-control" required
                 placeholder="seu@email.com" value="{{ form.email or '' }}">
        </div>
        <div class="mb-3">
          <label class="form-label fw-semibold small">Senha</label>
          <input type="password" name="password" class="form-control" required minlength="6">
        </div>
        <div class="mb-4">
          <label class="form-label fw-semibold small">Confirmar senha</label>
          <input type="password" name="password2" class="form-control" required minlength="6">
        </div>
        <button type="submit" class="btn btn-primary w-100">Criar conta</button>
      </form>

      <div class="text-center mt-3">
        <a href="/login" class="small">Já tenho conta → Entrar</a>
      </div>
    </div>
  </div>
</div>
{% endblock %}
"""

TEMPLATES["convite_membro.html"] = """
{% extends "base.html" %}
{% block content %}
<div class="row justify-content-center mt-5">
  <div class="col-md-6 col-lg-5">
    <div class="card p-4">
      <div class="text-center mb-4">
        <img src="/static/logo.png" alt="Maffezzolli Capital" style="height:40px;">
        <h4 class="mt-3 mb-1">Você foi convidado!</h4>
        <div class="muted small">{{ company.name }} convidou você para usar o sistema</div>
      </div>

      {% if error %}
      <div class="alert alert-danger">{{ error }}</div>
      {% endif %}

      <form method="post" action="/convite-membro/{{ token }}">
        <div class="mb-3">
          <label class="form-label fw-semibold small">Seu nome completo</label>
          <input type="text" name="name" class="form-control" required
                 placeholder="Nome completo" value="{{ form.name or '' }}">
        </div>
        <div class="mb-3">
          <label class="form-label fw-semibold small">E-mail</label>
          <input type="email" name="email" class="form-control" required
                 value="{{ invited_email or '' }}" {% if invited_email %}readonly{% endif %}>
        </div>
        <div class="mb-3">
          <label class="form-label fw-semibold small">Senha</label>
          <input type="password" name="password" class="form-control" required minlength="6">
        </div>
        <div class="mb-4">
          <label class="form-label fw-semibold small">Confirmar senha</label>
          <input type="password" name="password2" class="form-control" required minlength="6">
        </div>
        <button type="submit" class="btn btn-primary w-100">Aceitar convite e entrar</button>
      </form>
    </div>
  </div>
</div>
{% endblock %}
"""

if hasattr(templates_env.loader, "mapping"):
    templates_env.loader.mapping = TEMPLATES


# ── Rota GET /cadastro ────────────────────────────────────────────────────────

@app.get("/cadastro", response_class=_HTML_cc)
async def cadastro_page(request: _Req_cc):
    return render("cadastro.html", request=request, context={
        "current_user": None, "current_company": None, "role": None,
        "current_client": None, "error": "", "form": {},
    })


# ── Rota POST /cadastro ───────────────────────────────────────────────────────

@app.post("/cadastro", response_class=_HTML_cc)
async def cadastro_action(
    request: _Req_cc,
    session=_Dep_cc(get_session),
    company_name: str = _Form_cc(""),
    cnpj: str = _Form_cc(""),
    name: str = _Form_cc(""),
    email: str = _Form_cc(""),
    password: str = _Form_cc(""),
    password2: str = _Form_cc(""),
):
    def _err(msg):
        return render("cadastro.html", request=request, context={
            "current_user": None, "current_company": None, "role": None,
            "current_client": None, "error": msg,
            "form": {"company_name": company_name, "cnpj": cnpj, "name": name, "email": email},
        })

    company_name = company_name.strip()
    name         = name.strip()
    email        = email.strip().lower()
    cnpj         = cnpj.strip()

    if not company_name:
        return _err("Nome da empresa é obrigatório.")
    if not name:
        return _err("Seu nome é obrigatório.")
    if not email or "@" not in email:
        return _err("E-mail inválido.")
    if not password or len(password) < 6:
        return _err("Senha deve ter pelo menos 6 caracteres.")
    if password != password2:
        return _err("Senhas não conferem.")

    # Verifica se e-mail já existe
    existing_user = session.exec(_sel_cc(User).where(User.email == email)).first()
    if existing_user:
        return _err("Este e-mail já está cadastrado. Tente fazer login.")

    # Cria empresa
    import re as _re_cad
    slug = _re_cad.sub(r'[^a-z0-9]', '-', company_name.lower())[:40].strip('-')
    company = Company(
        name=company_name,
        slug=slug,
        cnpj=_re_cad.sub(r'\D', '', cnpj)[:18],
        created_at=utcnow(),
        updated_at=utcnow(),
    )
    session.add(company)
    session.commit()
    session.refresh(company)

    # Cria usuário admin
    from passlib.context import CryptContext as _CryptCtx
    _pwd_ctx = _CryptCtx(schemes=["bcrypt"], deprecated="auto")
    hashed = _pwd_ctx.hash(password)

    user = User(
        name=name,
        email=email,
        hashed_password=hashed,
        created_at=utcnow(),
        updated_at=utcnow(),
    )
    session.add(user)
    session.commit()
    session.refresh(user)

    # Cria membership admin
    membership = Membership(
        company_id=company.id,
        user_id=user.id,
        role="admin",
        created_at=utcnow(),
        updated_at=utcnow(),
    )
    session.add(membership)
    session.commit()

    # Faz login automático
    request.session["user_id"] = user.id
    request.session["company_id"] = company.id

    set_flash(request, f"Bem-vindo, {name}! Sua conta foi criada com sucesso.")
    return _RR_cc("/", status_code=303)


# ── Rota POST /admin/members/convidar ─────────────────────────────────────────

@app.post("/admin/members/convidar")
@require_role({"admin", "equipe"})
async def membro_convidar(
    request: _Req_cc,
    session=_Dep_cc(get_session),
    email: str = _Form_cc(""),
    role: str = _Form_cc("equipe"),
):
    ctx = get_tenant_context(request, session)
    assert ctx is not None

    email = email.strip().lower()
    if not email or "@" not in email:
        set_flash(request, "E-mail inválido.")
        return _RR_cc("/admin/members", status_code=303)

    if role not in ("admin", "equipe", "cliente"):
        role = "equipe"

    # Verifica se já é membro
    existing = session.exec(
        _sel_cc(User).where(User.email == email)
    ).first()
    if existing:
        mem = session.exec(
            _sel_cc(Membership).where(
                Membership.company_id == ctx.company.id,
                Membership.user_id == existing.id,
            )
        ).first()
        if mem:
            set_flash(request, f"{email} já é membro desta empresa.")
            return _RR_cc("/admin/members", status_code=303)

    # Cria convite
    token = _gerar_token_cc()
    expires_at = (_dt_cc.utcnow() + _td_cc(days=7)).isoformat()

    convite = ConviteMembro(
        company_id=ctx.company.id,
        created_by_id=ctx.user.id,
        email=email,
        role=role,
        token=token,
        status="pendente",
        expires_at=expires_at,
        created_at=_dt_cc.utcnow().isoformat(),
    )
    session.add(convite)
    session.commit()

    base_url = _os_cc.environ.get("PUBLIC_BASE_URL", _PROD_URL).rstrip("/")
    url = f"{base_url}/convite-membro/{token}"

    set_flash(request, f"Convite gerado! Link: {url}")
    request.session["last_invite_url"] = url
    return _RR_cc("/admin/members", status_code=303)


# ── Rota GET /convite-membro/{token} ─────────────────────────────────────────

@app.get("/convite-membro/{token}", response_class=_HTML_cc)
async def convite_membro_page(token: str, request: _Req_cc, session=_Dep_cc(get_session)):
    convite = session.exec(_sel_cc(ConviteMembro).where(ConviteMembro.token == token)).first()

    if not convite:
        return render("success.html", request=request, context={
            "current_user": None, "message": "Convite inválido ou expirado."
        }, status_code=400)

    if convite.status != "pendente":
        return render("success.html", request=request, context={
            "current_user": None, "message": "Este convite já foi utilizado."
        })

    if _dt_cc.utcnow().isoformat() > convite.expires_at:
        convite.status = "expirado"
        session.add(convite)
        session.commit()
        return render("success.html", request=request, context={
            "current_user": None, "message": "Convite expirado."
        })

    company = session.get(Company, convite.company_id)
    return render("convite_membro.html", request=request, context={
        "current_user": None, "current_company": None, "role": None,
        "current_client": None, "company": company, "token": token,
        "invited_email": convite.email, "error": "", "form": {},
    })


# ── Rota POST /convite-membro/{token} ────────────────────────────────────────

@app.post("/convite-membro/{token}", response_class=_HTML_cc)
async def convite_membro_action(
    token: str,
    request: _Req_cc,
    session=_Dep_cc(get_session),
    name: str = _Form_cc(""),
    email: str = _Form_cc(""),
    password: str = _Form_cc(""),
    password2: str = _Form_cc(""),
):
    convite = session.exec(_sel_cc(ConviteMembro).where(ConviteMembro.token == token)).first()
    company = session.get(Company, convite.company_id) if convite else None

    def _err(msg):
        return render("convite_membro.html", request=request, context={
            "current_user": None, "current_company": None, "role": None,
            "current_client": None, "company": company, "token": token,
            "invited_email": convite.email if convite else "", "error": msg,
            "form": {"name": name},
        })

    if not convite or convite.status != "pendente":
        return _err("Convite inválido ou já utilizado.")

    if _dt_cc.utcnow().isoformat() > convite.expires_at:
        return _err("Convite expirado.")

    name  = name.strip()
    email = email.strip().lower()

    if convite.email and email != convite.email:
        return _err(f"Use o e-mail para o qual o convite foi enviado: {convite.email}")

    if not name:
        return _err("Nome é obrigatório.")
    if not password or len(password) < 6:
        return _err("Senha deve ter pelo menos 6 caracteres.")
    if password != password2:
        return _err("Senhas não conferem.")

    # Verifica se usuário já existe
    user = session.exec(_sel_cc(User).where(User.email == email)).first()

    if not user:
        from passlib.context import CryptContext as _CryptCtx2
        _pwd_ctx2 = _CryptCtx2(schemes=["bcrypt"], deprecated="auto")
        user = User(
            name=name,
            email=email,
            hashed_password=_pwd_ctx2.hash(password),
            created_at=utcnow(),
            updated_at=utcnow(),
        )
        session.add(user)
        session.commit()
        session.refresh(user)

    # Cria membership
    mem_exists = session.exec(
        _sel_cc(Membership).where(
            Membership.company_id == convite.company_id,
            Membership.user_id == user.id,
        )
    ).first()

    if not mem_exists:
        membership = Membership(
            company_id=convite.company_id,
            user_id=user.id,
            role=convite.role,
            created_at=utcnow(),
            updated_at=utcnow(),
        )
        session.add(membership)

    # Marca convite como aceito
    convite.status = "aceito"
    session.add(convite)
    session.commit()

    # Login automático
    request.session["user_id"] = user.id
    request.session["company_id"] = convite.company_id

    set_flash(request, f"Bem-vindo, {name}! Você agora faz parte de {company.name}.")
    return _RR_cc("/", status_code=303)


# ── Injeta botão "Convidar" e link de cadastro na tela de membros ─────────────

_members_tpl = TEMPLATES.get("members.html", "")
if _members_tpl and "convidar" not in _members_tpl:
    _btn_convidar = """
<div class="card p-3 mb-3">
  <h6 class="mb-3">Convidar novo membro</h6>
  <form method="post" action="/admin/members/convidar" class="row g-2 align-items-end">
    <div class="col-md-5">
      <label class="form-label small fw-semibold">E-mail</label>
      <input type="email" name="email" class="form-control form-control-sm" required placeholder="email@exemplo.com">
    </div>
    <div class="col-md-3">
      <label class="form-label small fw-semibold">Role</label>
      <select name="role" class="form-select form-select-sm">
        <option value="equipe">Equipe</option>
        <option value="admin">Admin</option>
        <option value="cliente">Cliente</option>
      </select>
    </div>
    <div class="col-md-4">
      <button type="submit" class="btn btn-primary btn-sm w-100">✉️ Enviar convite</button>
    </div>
  </form>
  {% if request.session.get('last_invite_url') %}
  <div class="alert alert-success mt-2 py-2 small">
    Link gerado: <a href="{{ request.session.get('last_invite_url') }}" target="_blank">{{ request.session.get('last_invite_url') }}</a>
  </div>
  {% endif %}
</div>
"""
    # Injeta antes da tabela de membros
    if "<h4" in _members_tpl:
        _members_tpl = _members_tpl.replace("<h4", _btn_convidar + "\n<h4", 1)
    elif "{% for row in rows %}" in _members_tpl:
        _members_tpl = _members_tpl.replace("{% for row in rows %}", _btn_convidar + "\n{% for row in rows %}", 1)

    TEMPLATES["members.html"] = _members_tpl
    print("[cadastro_convite] ✅ Botão convidar adicionado na tela de membros")

# Adiciona link de cadastro na tela de login
_login_tpl = TEMPLATES.get("login.html", "")
if _login_tpl and "/cadastro" not in _login_tpl:
    _login_tpl = _login_tpl.replace(
        "</form>",
        '</form>\n<div class="text-center mt-3"><a href="/cadastro" class="small">Não tem conta? Cadastre-se</a></div>'
    )
    TEMPLATES["login.html"] = _login_tpl
    print("[cadastro_convite] ✅ Link de cadastro adicionado na tela de login")

if hasattr(templates_env.loader, "mapping"):
    templates_env.loader.mapping = TEMPLATES

print("[cadastro_convite] ✅ Patch completo carregado")

# ============================================================================
# PATCH — Reset de Senha
# ============================================================================
# Salve como ui_reset_senha.py e adicione ao final do app.py:
#   exec(open('ui_reset_senha.py').read())
#
# ROTAS:
#   GET  /esqueci-senha          — formulário de email
#   POST /esqueci-senha          — envia email com link
#   GET  /resetar-senha/{token}  — formulário de nova senha
#   POST /resetar-senha/{token}  — salva nova senha
#
# REQUER: SMTP configurado no Render (SMTP_HOST, SMTP_USERNAME, etc.)
# ============================================================================

import secrets as _secrets
from datetime import datetime as _datetime, timedelta as _timedelta
from typing import Optional as _Opt3
from sqlmodel import Field as _F3, SQLModel as _SM3


# ── Modelo de token ───────────────────────────────────────────────────────────

class PasswordResetToken(_SM3, table=True):
    __tablename__  = "passwordresettoken"
    __table_args__ = {"extend_existing": True}
    id:         _Opt3[int] = _F3(default=None, primary_key=True)
    user_id:    int        = _F3(index=True)
    token:      str        = _F3(unique=True, index=True)
    expires_at: str        = _F3(default="")
    used:       bool       = _F3(default=False)
    created_at: str        = _F3(default="")

try:
    _SM3.metadata.create_all(engine, tables=[PasswordResetToken.__table__])
except Exception:
    pass


# ── Helpers ───────────────────────────────────────────────────────────────────

def _reset_token_create(session, user_id: int) -> str:
    """Cria um token de reset válido por 2 horas."""
    # Invalida tokens anteriores do mesmo usuário
    old_tokens = session.exec(
        select(PasswordResetToken)
        .where(PasswordResetToken.user_id == user_id, PasswordResetToken.used == False)
    ).all()
    for t in old_tokens:
        t.used = True
        session.add(t)

    token = _secrets.token_urlsafe(32)
    expires = (_datetime.utcnow() + _timedelta(hours=2)).isoformat()

    prt = PasswordResetToken(
        user_id=user_id,
        token=token,
        expires_at=expires,
        used=False,
        created_at=_datetime.utcnow().isoformat(),
    )
    session.add(prt)
    session.commit()
    return token


def _reset_token_validate(session, token: str):
    """Valida o token. Retorna (PasswordResetToken, User) ou (None, None)."""
    prt = session.exec(
        select(PasswordResetToken)
        .where(PasswordResetToken.token == token, PasswordResetToken.used == False)
    ).first()

    if not prt:
        return None, None

    # Verifica expiração
    try:
        expires = _datetime.fromisoformat(prt.expires_at)
        if _datetime.utcnow() > expires:
            return None, None
    except Exception:
        return None, None

    user = session.get(User, prt.user_id)
    if not user:
        return None, None

    return prt, user


def _send_reset_email(to_email: str, reset_url: str, user_name: str) -> None:
    """Envia o email de reset de senha."""
    html = f"""
<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"></head>
<body style="font-family:Arial,sans-serif;background:#f8f9fa;margin:0;padding:2rem;">
  <div style="max-width:560px;margin:0 auto;background:#fff;border-radius:16px;overflow:hidden;box-shadow:0 2px 16px rgba(0,0,0,.08);">
    <div style="background:#E07020;padding:1.5rem 2rem;">
      <div style="color:#fff;font-size:1.3rem;font-weight:700;">Maffezzolli Capital</div>
    </div>
    <div style="padding:2rem;">
      <h2 style="color:#2D2D2D;margin-top:0;">Redefinição de senha</h2>
      <p style="color:#555;line-height:1.6;">Olá, <strong>{user_name}</strong>.</p>
      <p style="color:#555;line-height:1.6;">
        Recebemos uma solicitação para redefinir a senha da sua conta no App Maffezzolli Capital.
        Clique no botão abaixo para criar uma nova senha:
      </p>
      <div style="text-align:center;margin:2rem 0;">
        <a href="{reset_url}"
           style="background:#E07020;color:#fff;padding:.85rem 2rem;border-radius:10px;
                  text-decoration:none;font-weight:700;font-size:1rem;display:inline-block;">
          Redefinir minha senha
        </a>
      </div>
      <p style="color:#888;font-size:.85rem;line-height:1.5;">
        Este link é válido por <strong>2 horas</strong>. Se você não solicitou a redefinição,
        ignore este email — sua senha não será alterada.
      </p>
      <hr style="border:none;border-top:1px solid #e5e7eb;margin:1.5rem 0;">
      <p style="color:#aaa;font-size:.75rem;text-align:center;">
        App Maffezzolli Capital · app.maffezzollicapital.com.br
      </p>
    </div>
  </div>
</body>
</html>
"""
    text = f"Olá {user_name},\n\nClique no link abaixo para redefinir sua senha:\n{reset_url}\n\nLink válido por 2 horas."
    _smtp_send_email(
        to_email=to_email,
        subject="Redefinição de senha — Maffezzolli Capital",
        html_body=html,
        text_body=text,
    )


# ── Rota GET /esqueci-senha ───────────────────────────────────────────────────

@app.get("/esqueci-senha", response_class=HTMLResponse)
async def esqueci_senha_get(request: Request):
    return HTMLResponse(TEMPLATES.get("esqueci_senha.html", "").replace(
        "{{ erro }}", "").replace("{{ sucesso }}", ""))


# ── Rota POST /esqueci-senha ──────────────────────────────────────────────────

@app.post("/esqueci-senha", response_class=HTMLResponse)
async def esqueci_senha_post(request: Request, session: Session = Depends(get_session)):
    form = await request.form()
    email = (form.get("email") or "").strip().lower()

    if not email:
        return HTMLResponse(_render_esqueci(erro="Informe seu e-mail."))

    user = session.exec(select(User).where(User.email == email)).first()

    # Sempre mostra sucesso para não revelar se o email existe
    if user:
        try:
            token = _reset_token_create(session, user.id)
            base_url = str(request.base_url).rstrip("/")
            reset_url = f"{base_url}/resetar-senha/{token}"
            _send_reset_email(
                to_email=user.email,
                reset_url=reset_url,
                user_name=user.name or user.email,
            )
        except Exception as e:
            return HTMLResponse(_render_esqueci(
                erro="Erro ao enviar email. Tente novamente ou contate o suporte."
            ))

    return HTMLResponse(_render_esqueci(
        sucesso=f"Se o e-mail <strong>{email}</strong> estiver cadastrado, você receberá as instruções em breve."
    ))


# ── Rota GET /resetar-senha/{token} ──────────────────────────────────────────

@app.get("/resetar-senha/{token}", response_class=HTMLResponse)
async def resetar_senha_get(token: str, request: Request, session: Session = Depends(get_session)):
    prt, user = _reset_token_validate(session, token)
    if not prt:
        return HTMLResponse(_render_resetar(token=token, erro="Link inválido ou expirado. Solicite um novo."))
    return HTMLResponse(_render_resetar(token=token))


# ── Rota POST /resetar-senha/{token} ─────────────────────────────────────────

@app.post("/resetar-senha/{token}", response_class=HTMLResponse)
async def resetar_senha_post(token: str, request: Request, session: Session = Depends(get_session)):
    prt, user = _reset_token_validate(session, token)
    if not prt:
        return HTMLResponse(_render_resetar(token=token, erro="Link inválido ou expirado. Solicite um novo."))

    form = await request.form()
    nova_senha  = form.get("nova_senha", "")
    confirma    = form.get("confirma_senha", "")

    if len(nova_senha) < 8:
        return HTMLResponse(_render_resetar(token=token, erro="A senha deve ter pelo menos 8 caracteres."))

    if nova_senha != confirma:
        return HTMLResponse(_render_resetar(token=token, erro="As senhas não conferem."))

    # Atualiza senha
    user.password_hash = hash_password(nova_senha)
    session.add(user)

    # Invalida o token
    prt.used = True
    session.add(prt)
    session.commit()

    return HTMLResponse(_render_resetar(token=token, sucesso=True))


# ── Funções de render inline (sem depender do sistema de templates) ───────────

def _render_esqueci(erro: str = "", sucesso: str = "") -> str:
    return f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Esqueci minha senha — Maffezzolli Capital</title>
  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
  <style>
    body{{background:#f8f9fa;display:flex;align-items:center;justify-content:center;min-height:100vh;}}
    .card{{border-radius:16px;border:none;box-shadow:0 4px 24px rgba(0,0,0,.08);max-width:440px;width:100%;}}
    .logo{{background:#E07020;color:#fff;font-weight:800;font-size:1.1rem;padding:1.25rem 1.5rem;border-radius:16px 16px 0 0;}}
    .btn-primary{{background:#E07020;border-color:#E07020;}}
    .btn-primary:hover{{background:#c96018;border-color:#c96018;}}
    .form-control:focus{{border-color:#E07020;box-shadow:0 0 0 .2rem rgba(224,112,32,.25);}}
  </style>
</head>
<body>
  <div class="card">
    <div class="logo">Maffezzolli Capital</div>
    <div class="card-body p-4">
      <h5 class="mb-1">Esqueci minha senha</h5>
      <p class="text-muted small mb-3">Informe seu e-mail e enviaremos um link para redefinir sua senha.</p>
      {'<div class="alert alert-danger">' + erro + '</div>' if erro else ''}
      {'<div class="alert alert-success">' + sucesso + '</div>' if sucesso else ''}
      {'<form method="post" action="/esqueci-senha">' if not sucesso else ''}
        {'<div class="mb-3"><label class="form-label fw-semibold small">E-mail</label><input type="email" name="email" class="form-control" required autofocus placeholder="seu@email.com"></div><button type="submit" class="btn btn-primary w-100">Enviar link de redefinição</button></form>' if not sucesso else ''}
      <div class="text-center mt-3">
        <a href="/login" class="text-muted small">← Voltar para o login</a>
      </div>
    </div>
  </div>
</body>
</html>"""


def _render_resetar(token: str, erro: str = "", sucesso: bool = False) -> str:
    if sucesso:
        corpo = """
        <div class="alert alert-success">
          <strong>✅ Senha redefinida com sucesso!</strong><br>
          Você já pode fazer login com sua nova senha.
        </div>
        <a href="/login" class="btn btn-primary w-100">Ir para o login</a>"""
    else:
        corpo = f"""
        {'<div class="alert alert-danger">' + erro + '</div>' if erro else ''}
        {'<form method="post" action="/resetar-senha/' + token + '">' if not erro or 'expirado' not in erro else ''}
          {'<div class="mb-3"><label class="form-label fw-semibold small">Nova senha</label><input type="password" name="nova_senha" class="form-control" required minlength="8" placeholder="Mínimo 8 caracteres"></div><div class="mb-3"><label class="form-label fw-semibold small">Confirmar nova senha</label><input type="password" name="confirma_senha" class="form-control" required></div><button type="submit" class="btn btn-primary w-100">Salvar nova senha</button></form>' if not erro or 'expirado' not in erro else '<a href="/esqueci-senha" class="btn btn-primary w-100">Solicitar novo link</a>'}"""

    return f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Redefinir senha — Maffezzolli Capital</title>
  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
  <style>
    body{{background:#f8f9fa;display:flex;align-items:center;justify-content:center;min-height:100vh;}}
    .card{{border-radius:16px;border:none;box-shadow:0 4px 24px rgba(0,0,0,.08);max-width:440px;width:100%;}}
    .logo{{background:#E07020;color:#fff;font-weight:800;font-size:1.1rem;padding:1.25rem 1.5rem;border-radius:16px 16px 0 0;}}
    .btn-primary{{background:#E07020;border-color:#E07020;}}
    .btn-primary:hover{{background:#c96018;border-color:#c96018;}}
    .form-control:focus{{border-color:#E07020;box-shadow:0 0 0 .2rem rgba(224,112,32,.25);}}
  </style>
</head>
<body>
  <div class="card">
    <div class="logo">Maffezzolli Capital</div>
    <div class="card-body p-4">
      <h5 class="mb-1">Redefinir senha</h5>
      <p class="text-muted small mb-3">Escolha uma nova senha para sua conta.</p>
      {corpo}
      <div class="text-center mt-3">
        <a href="/login" class="text-muted small">← Voltar para o login</a>
      </div>
    </div>
  </div>
</body>
</html>"""


# ── Injeta link "Esqueci minha senha" na tela de login ────────────────────────

_login_tmpl = TEMPLATES.get("login.html", "")
if _login_tmpl and "esqueci-senha" not in _login_tmpl:
    # Tenta inserir após o botão de submit do login
    for anchor in ['type="submit"', "Entrar", "/login"]:
        idx = _login_tmpl.rfind(anchor)
        if idx > 0:
            # Encontra o fim da linha
            fim = _login_tmpl.find("\n", idx)
            if fim > 0:
                _login_tmpl = (
                    _login_tmpl[:fim] +
                    '\n      <div class="text-center mt-2"><a href="/esqueci-senha" '
                    'style="font-size:.82rem;color:var(--mc-muted);">Esqueci minha senha</a></div>' +
                    _login_tmpl[fim:]
                )
                TEMPLATES["login.html"] = _login_tmpl
                break

if hasattr(templates_env.loader, "mapping"):
    templates_env.loader.mapping = TEMPLATES

# ============================================================================
# FIM DO PATCH — Reset de Senha
# ============================================================================

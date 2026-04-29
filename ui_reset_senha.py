# ============================================================================
# PATCH — Reset de Senha
# ============================================================================

import secrets as _secrets
from datetime import datetime as _datetime, timedelta as _timedelta
from typing import Optional as _Opt3
from sqlmodel import Field as _F3, SQLModel as _SM3

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

def _reset_token_create(session, user_id):
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
        user_id=user_id, token=token, expires_at=expires,
        used=False, created_at=_datetime.utcnow().isoformat(),
    )
    session.add(prt)
    session.commit()
    return token

def _reset_token_validate(session, token):
    prt = session.exec(
        select(PasswordResetToken)
        .where(PasswordResetToken.token == token, PasswordResetToken.used == False)
    ).first()
    if not prt:
        return None, None
    try:
        if _datetime.utcnow() > _datetime.fromisoformat(prt.expires_at):
            return None, None
    except Exception:
        return None, None
    user = session.get(User, prt.user_id)
    if not user:
        return None, None
    return prt, user

def _send_reset_email(to_email, reset_url, user_name):
    html = (
        '<!DOCTYPE html><html><head><meta charset="UTF-8"></head>'
        '<body style="font-family:Arial,sans-serif;background:#f8f9fa;margin:0;padding:2rem;">'
        '<div style="max-width:560px;margin:0 auto;background:#fff;border-radius:16px;overflow:hidden;box-shadow:0 2px 16px rgba(0,0,0,.08);">'
        '<div style="background:#E07020;padding:1.5rem 2rem;"><div style="color:#fff;font-size:1.3rem;font-weight:700;">Maffezzolli Capital</div></div>'
        '<div style="padding:2rem;">'
        '<h2 style="color:#2D2D2D;margin-top:0;">Redefinição de senha</h2>'
        '<p style="color:#555;line-height:1.6;">Olá, <strong>' + user_name + '</strong>.</p>'
        '<p style="color:#555;line-height:1.6;">Recebemos uma solicitação para redefinir a senha da sua conta. Clique no botão abaixo:</p>'
        '<div style="text-align:center;margin:2rem 0;">'
        '<a href="' + reset_url + '" style="background:#E07020;color:#fff;padding:.85rem 2rem;border-radius:10px;text-decoration:none;font-weight:700;font-size:1rem;display:inline-block;">Redefinir minha senha</a>'
        '</div>'
        '<p style="color:#888;font-size:.85rem;">Este link é válido por <strong>2 horas</strong>. Se você não solicitou, ignore este email.</p>'
        '<hr style="border:none;border-top:1px solid #e5e7eb;margin:1.5rem 0;">'
        '<p style="color:#aaa;font-size:.75rem;text-align:center;">App Maffezzolli Capital · app.maffezzollicapital.com.br</p>'
        '</div></div></body></html>'
    )
    text = 'Ola ' + user_name + ',\n\nClique no link abaixo para redefinir sua senha:\n' + reset_url + '\n\nLink valido por 2 horas.'
    _smtp_send_email(to_email=to_email, subject='Redefinição de senha — Maffezzolli Capital', html_body=html, text_body=text)

_CSS_LOGIN = (
    '<style>'
    'body{background:#f8f9fa;display:flex;align-items:center;justify-content:center;min-height:100vh;}'
    '.mfc-card{border-radius:16px;border:none;box-shadow:0 4px 24px rgba(0,0,0,.08);max-width:440px;width:100%;background:#fff;}'
    '.mfc-logo{background:#E07020;color:#fff;font-weight:800;font-size:1.1rem;padding:1.25rem 1.5rem;border-radius:16px 16px 0 0;}'
    '.btn-mc{background:#E07020;border:none;color:#fff;padding:.7rem 1.5rem;border-radius:8px;width:100%;font-weight:700;cursor:pointer;}'
    '.btn-mc:hover{background:#c96018;}'
    '.form-control{width:100%;border:1.5px solid #e5e7eb;border-radius:8px;padding:.58rem .85rem;font-size:.9rem;outline:none;box-sizing:border-box;}'
    '.form-control:focus{border-color:#E07020;}'
    '.alert-danger{background:#fef2f2;color:#991b1b;border:1px solid #fecaca;border-radius:8px;padding:.65rem .9rem;margin-bottom:1rem;font-size:.88rem;}'
    '.alert-success{background:#f0fdf4;color:#166534;border:1px solid #bbf7d0;border-radius:8px;padding:.65rem .9rem;margin-bottom:1rem;font-size:.88rem;}'
    '.lbl{font-size:.78rem;font-weight:700;color:#374151;margin-bottom:.3rem;display:block;}'
    '.mb3{margin-bottom:1rem;}'
    '</style>'
)

def _page_wrap(titulo, conteudo):
    return (
        '<!DOCTYPE html><html lang="pt-BR"><head>'
        '<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
        '<title>' + titulo + ' — Maffezzolli Capital</title>'
        '<link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">'
        + _CSS_LOGIN +
        '</head><body>'
        '<div class="mfc-card">'
        '<div class="mfc-logo">Maffezzolli Capital</div>'
        '<div style="padding:1.75rem;">'
        + conteudo +
        '<div style="text-align:center;margin-top:1rem;">'
        '<a href="/login" style="font-size:.82rem;color:#6b7280;">← Voltar para o login</a>'
        '</div></div></div></body></html>'
    )

def _render_esqueci(erro='', sucesso=''):
    conteudo = '<h5 style="margin:0 0 .25rem;">Esqueci minha senha</h5>'
    conteudo += '<p style="color:#6b7280;font-size:.85rem;margin-bottom:1rem;">Informe seu e-mail para receber o link de redefinição.</p>'
    if erro:
        conteudo += '<div class="alert-danger">' + erro + '</div>'
    if sucesso:
        conteudo += '<div class="alert-success">' + sucesso + '</div>'
    else:
        conteudo += (
            '<form method="post" action="/esqueci-senha">'
            '<div class="mb3"><label class="lbl">E-mail</label>'
            '<input type="email" name="email" class="form-control" required autofocus placeholder="seu@email.com">'
            '</div>'
            '<button type="submit" class="btn-mc">Enviar link de redefinição</button>'
            '</form>'
        )
    return _page_wrap('Esqueci minha senha', conteudo)

def _render_resetar(token, erro='', sucesso=False):
    conteudo = '<h5 style="margin:0 0 .25rem;">Redefinir senha</h5>'
    conteudo += '<p style="color:#6b7280;font-size:.85rem;margin-bottom:1rem;">Escolha uma nova senha para sua conta.</p>'
    if sucesso:
        conteudo += (
            '<div class="alert-success"><strong>Senha redefinida com sucesso!</strong><br>Você já pode fazer login com sua nova senha.</div>'
            '<a href="/login" class="btn-mc" style="display:block;text-align:center;text-decoration:none;padding:.7rem;">Ir para o login</a>'
        )
    else:
        if erro:
            conteudo += '<div class="alert-danger">' + erro + '</div>'
        if not erro or 'expirado' not in erro:
            conteudo += (
                '<form method="post" action="/resetar-senha/' + token + '">'
                '<div class="mb3"><label class="lbl">Nova senha</label>'
                '<input type="password" name="nova_senha" class="form-control" required minlength="8" placeholder="Mínimo 8 caracteres">'
                '</div>'
                '<div class="mb3"><label class="lbl">Confirmar nova senha</label>'
                '<input type="password" name="confirma_senha" class="form-control" required>'
                '</div>'
                '<button type="submit" class="btn-mc">Salvar nova senha</button>'
                '</form>'
            )
        else:
            conteudo += '<a href="/esqueci-senha" class="btn-mc" style="display:block;text-align:center;text-decoration:none;padding:.7rem;">Solicitar novo link</a>'
    return _page_wrap('Redefinir senha', conteudo)

@app.get("/esqueci-senha", response_class=HTMLResponse)
async def esqueci_senha_get(request: Request):
    return HTMLResponse(_render_esqueci())

@app.post("/esqueci-senha", response_class=HTMLResponse)
async def esqueci_senha_post(request: Request, session: Session = Depends(get_session)):
    form = await request.form()
    email = (form.get("email") or "").strip().lower()
    if not email:
        return HTMLResponse(_render_esqueci(erro="Informe seu e-mail."))
    user = session.exec(select(User).where(User.email == email)).first()
    if user:
        try:
            token = _reset_token_create(session, user.id)
            base_url = str(request.base_url).rstrip("/")
            reset_url = base_url + "/resetar-senha/" + token
            _send_reset_email(to_email=user.email, reset_url=reset_url, user_name=user.name or user.email)
        except Exception as e:
            return HTMLResponse(_render_esqueci(erro="Erro ao enviar email. Tente novamente ou contate o suporte."))
    return HTMLResponse(_render_esqueci(
        sucesso="Se o e-mail <strong>" + email + "</strong> estiver cadastrado, você receberá as instruções em breve."
    ))

@app.get("/resetar-senha/{token}", response_class=HTMLResponse)
async def resetar_senha_get(token: str, request: Request, session: Session = Depends(get_session)):
    prt, user = _reset_token_validate(session, token)
    if not prt:
        return HTMLResponse(_render_resetar(token=token, erro="Link inválido ou expirado. Solicite um novo."))
    return HTMLResponse(_render_resetar(token=token))

@app.post("/resetar-senha/{token}", response_class=HTMLResponse)
async def resetar_senha_post(token: str, request: Request, session: Session = Depends(get_session)):
    prt, user = _reset_token_validate(session, token)
    if not prt:
        return HTMLResponse(_render_resetar(token=token, erro="Link inválido ou expirado. Solicite um novo."))
    form = await request.form()
    nova_senha = form.get("nova_senha", "")
    confirma   = form.get("confirma_senha", "")
    if len(nova_senha) < 8:
        return HTMLResponse(_render_resetar(token=token, erro="A senha deve ter pelo menos 8 caracteres."))
    if nova_senha != confirma:
        return HTMLResponse(_render_resetar(token=token, erro="As senhas não conferem."))
    user.password_hash = hash_password(nova_senha)
    session.add(user)
    prt.used = True
    session.add(prt)
    session.commit()
    return HTMLResponse(_render_resetar(token=token, sucesso=True))

# Injeta link na tela de login
_login_tmpl = TEMPLATES.get("login.html", "")
if _login_tmpl and "esqueci-senha" not in _login_tmpl:
    for anchor in ['type="submit"', "btn-primary", "Entrar"]:
        idx = _login_tmpl.rfind(anchor)
        if idx > 0:
            fim = _login_tmpl.find("\n", idx)
            if fim > 0:
                _login_tmpl = (
                    _login_tmpl[:fim] +
                    '\n      <div class="text-center mt-2"><a href="/esqueci-senha" style="font-size:.82rem;color:var(--mc-muted);">Esqueci minha senha</a></div>' +
                    _login_tmpl[fim:]
                )
                TEMPLATES["login.html"] = _login_tmpl
                break

if hasattr(templates_env.loader, "mapping"):
    templates_env.loader.mapping = TEMPLATES

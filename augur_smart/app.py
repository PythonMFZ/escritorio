# =============================================================================
# Augur Smart — chat isolado de IA consultiva para qualquer empresa.
# Projeto independente: app, banco e deploy próprios. Não depende do
# app.py principal (Escritório). Serve como isca de baixo custo para o
# produto completo.
# =============================================================================

import os
import secrets
from datetime import datetime, timedelta
from typing import Optional

import requests
from fastapi import FastAPI, Request, Form, Depends, Response
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from starlette.middleware.sessions import SessionMiddleware
from passlib.hash import bcrypt
from sqlmodel import SQLModel, Field, Session, create_engine, select

try:
    import stripe
except ImportError:
    stripe = None

# ── Configuração ─────────────────────────────────────────────────────────────

DATABASE_URL = os.environ.get("DATABASE_URL_AUGUR_SMART") or "sqlite:///./augur_smart.db"
engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {},
)

SECRET_KEY = os.environ.get("SECRET_KEY_AUGUR_SMART", secrets.token_hex(32))
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
STRIPE_SECRET_KEY = os.environ.get("STRIPE_SECRET_KEY", "")
STRIPE_WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET", "")
ADMIN_EMAILS = {e.strip().lower() for e in os.environ.get("AUGUR_SMART_ADMIN_EMAILS", "").split(",") if e.strip()}

MAX_MESSAGES_PER_REQUEST_CONTEXT = 12  # janela de histórico enviada ao modelo

AUGUR_SYSTEM_PROMPT = """Você é o Augur Smart, um consultor de negócios sênior especializado em
pequenas e médias empresas brasileiras (gestão financeira, fluxo de caixa, precificação,
obras/incorporação, processos e estratégia). Dê respostas práticas, diretas e específicas para
a realidade do empreendedor brasileiro, sem jargão acadêmico. Quando faltar contexto sobre a
empresa do usuário, pergunte antes de generalizar. Você não tem acesso aos dados financeiros
reais da empresa do usuário — baseie-se apenas no que ele contar na conversa."""


def utcnow() -> datetime:
    return datetime.utcnow()


# ── Modelos ───────────────────────────────────────────────────────────────────

class SmartUser(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    email: str = Field(index=True, unique=True)
    password_hash: str
    company_name: str = ""
    created_at: datetime = Field(default_factory=utcnow)


class SmartPlan(SQLModel, table=True):
    """Plano configurável pelo admin (preço em centavos de R$)."""
    id: Optional[int] = Field(default=None, primary_key=True)
    code: str = Field(index=True, unique=True)
    name: str
    price_cents: int
    message_limit_month: int = 0  # 0 = ilimitado
    stripe_price_id: str = ""
    active: bool = Field(default=True)
    order_idx: int = Field(default=0)


class SmartSubscription(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(index=True, foreign_key="smartuser.id")
    plan_code: str = ""
    status: str = Field(default="inactive", index=True)  # inactive | active | canceled
    stripe_customer_id: str = ""
    stripe_subscription_id: str = ""
    messages_used_this_cycle: int = Field(default=0)
    cycle_started_at: datetime = Field(default_factory=utcnow)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class SmartChatMessage(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(index=True, foreign_key="smartuser.id")
    role: str  # user | assistant
    content: str
    created_at: datetime = Field(default_factory=utcnow)


SQLModel.metadata.create_all(engine)


def get_session():
    with Session(engine) as session:
        yield session


def seed_default_plans():
    with Session(engine) as session:
        if session.exec(select(SmartPlan)).first():
            return
        session.add_all([
            SmartPlan(code="basico", name="Augur Smart — Básico", price_cents=2900,
                       message_limit_month=100, order_idx=1),
            SmartPlan(code="pro", name="Augur Smart — Pro", price_cents=5900,
                       message_limit_month=0, order_idx=2),
        ])
        session.commit()


seed_default_plans()

app = FastAPI(title="Augur Smart")
app.add_middleware(SessionMiddleware, secret_key=SECRET_KEY, https_only=True, same_site="lax")


# ── Helpers de auth ───────────────────────────────────────────────────────────

def current_user(request: Request, session: Session) -> Optional[SmartUser]:
    user_id = request.session.get("user_id")
    if not user_id:
        return None
    return session.get(SmartUser, user_id)


def is_admin(user: SmartUser) -> bool:
    return user.email.lower() in ADMIN_EMAILS


def get_or_create_subscription(session: Session, user: SmartUser) -> SmartSubscription:
    sub = session.exec(select(SmartSubscription).where(SmartSubscription.user_id == user.id)).first()
    if not sub:
        sub = SmartSubscription(user_id=user.id)
        session.add(sub)
        session.commit()
        session.refresh(sub)
    return sub


def subscription_is_usable(session: Session, sub: SmartSubscription) -> tuple:
    """Retorna (ok, motivo)."""
    if sub.status != "active":
        return False, "Sua assinatura não está ativa. Assine um plano para conversar com o Augur Smart."
    plan = session.exec(select(SmartPlan).where(SmartPlan.code == sub.plan_code)).first()
    if plan and plan.message_limit_month and sub.messages_used_this_cycle >= plan.message_limit_month:
        return False, "Você atingiu o limite de mensagens do seu plano neste mês."
    return True, ""


# ── Layout HTML (inline, sem dependência de templates externos) ─────────────

def layout(title: str, body: str, user: Optional[SmartUser] = None) -> str:
    nav_links = ""
    if user:
        nav_links = (
            '<a href="/chat" class="nav-link">Chat</a>'
            '<a href="/conta" class="nav-link">Minha conta</a>'
            + ('<a href="/admin/precos" class="nav-link">Admin</a>' if is_admin(user) else '')
            + '<a href="/logout" class="nav-link">Saída</a>'
        )
    else:
        nav_links = '<a href="/login" class="nav-link">Entrar</a><a href="/cadastro" class="nav-link">Criar conta</a>'

    return f"""<!doctype html>
<html lang="pt-br">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title} — Augur Smart</title>
<style>
  :root {{ --primary: #ea580c; --primary-dark: #c2410c; --bg: #f8fafc; }}
  * {{ box-sizing: border-box; }}
  body {{ margin: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background: var(--bg); color: #1e293b; }}
  header {{ background: #0f172a; color: #fff; padding: 14px 24px; display: flex; justify-content: space-between; align-items: center; }}
  header .brand {{ font-weight: 700; font-size: 1.1rem; }}
  header .brand span {{ color: var(--primary); }}
  .nav-link {{ color: #e2e8f0; text-decoration: none; margin-left: 18px; font-size: .9rem; }}
  .nav-link:hover {{ color: #fff; }}
  main {{ max-width: 880px; margin: 0 auto; padding: 32px 20px; }}
  .card {{ background: #fff; border-radius: 12px; padding: 24px; box-shadow: 0 1px 3px rgba(0,0,0,.08); }}
  h1 {{ font-size: 1.5rem; margin-top: 0; }}
  label {{ display: block; font-size: .85rem; font-weight: 600; margin-bottom: 4px; margin-top: 14px; color: #334155; }}
  input, textarea, select {{ width: 100%; padding: 10px 12px; border: 1px solid #cbd5e1; border-radius: 8px; font-size: .95rem; }}
  button, .btn {{ background: var(--primary); color: #fff; border: none; padding: 10px 18px; border-radius: 8px; font-weight: 600; cursor: pointer; font-size: .9rem; text-decoration: none; display: inline-block; }}
  button:hover, .btn:hover {{ background: var(--primary-dark); }}
  .btn-outline {{ background: transparent; color: var(--primary); border: 1px solid var(--primary); }}
  .btn-outline:hover {{ background: #fff7ed; }}
  .muted {{ color: #64748b; font-size: .88rem; }}
  .flash {{ background: #fef3c7; border: 1px solid #fbbf24; padding: 10px 14px; border-radius: 8px; margin-bottom: 16px; font-size: .9rem; }}
  .plans {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 16px; margin-top: 16px; }}
  .plan {{ border: 1px solid #e2e8f0; border-radius: 12px; padding: 20px; text-align: center; }}
  .plan .price {{ font-size: 1.8rem; font-weight: 700; color: var(--primary); margin: 8px 0; }}
  table {{ width: 100%; border-collapse: collapse; margin-top: 12px; }}
  th, td {{ text-align: left; padding: 8px 10px; border-bottom: 1px solid #e2e8f0; font-size: .88rem; }}
  #chat-box {{ height: 420px; overflow-y: auto; border: 1px solid #e2e8f0; border-radius: 10px; padding: 14px; background: #fafafa; margin-bottom: 12px; }}
  .msg {{ margin-bottom: 12px; max-width: 85%; padding: 10px 14px; border-radius: 10px; font-size: .92rem; white-space: pre-wrap; }}
  .msg.user {{ background: var(--primary); color: #fff; margin-left: auto; }}
  .msg.assistant {{ background: #e2e8f0; color: #1e293b; }}
  form.chat-form {{ display: flex; gap: 8px; }}
  form.chat-form textarea {{ flex: 1; resize: none; height: 48px; }}
</style>
</head>
<body>
<header>
  <div class="brand">Augur <span>Smart</span></div>
  <nav>{nav_links}</nav>
</header>
<main>
{body}
</main>
</body>
</html>"""


def flash_html(request: Request) -> str:
    msg = request.session.pop("flash", "") if hasattr(request.session, "pop") else request.session.get("flash", "")
    if "flash" in request.session:
        del request.session["flash"]
    return f'<div class="flash">{msg}</div>' if msg else ""


def set_flash(request: Request, msg: str) -> None:
    request.session["flash"] = msg


# ── Páginas públicas ──────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def home(request: Request, session: Session = Depends(get_session)) -> HTMLResponse:
    user = current_user(request, session)
    plans = session.exec(select(SmartPlan).where(SmartPlan.active == True).order_by(SmartPlan.order_idx)).all()  # noqa: E712
    plans_html = ""
    for p in plans:
        price = p.price_cents / 100
        limit_label = "ilimitadas" if not p.message_limit_month else f"{p.message_limit_month}/mês"
        plans_html += f"""
        <div class="plan">
          <div style="font-weight:600;">{p.name}</div>
          <div class="price">R$ {price:,.2f}</div>
          <div class="muted">mensagens {limit_label}</div>
          <div style="margin-top:14px;"><a class="btn" href="/cadastro?plano={p.code}">Assinar</a></div>
        </div>"""

    body = f"""
    <div class="card">
      <h1>A IA do empreendedor 💡</h1>
      <p>O Augur Smart é um chat de consultoria com inteligência artificial, focado em ajudar
      pequenas e médias empresas com finanças, precificação, fluxo de caixa, gestão e estratégia —
      sem precisar instalar nenhum sistema. Só conversar.</p>
      <p class="muted">Quer o pacote completo de gestão (financeiro, obras, CRM e muito mais)?
      <a href="https://app.maffezzollicapital.com.br" target="_blank">Conheça o Escritório</a>.</p>
      <div class="plans">{plans_html or '<p class="muted">Nenhum plano ativo no momento.</p>'}</div>
    </div>
    """
    return HTMLResponse(layout("Início", body, user))


@app.get("/cadastro", response_class=HTMLResponse)
async def signup_page(request: Request, session: Session = Depends(get_session)) -> HTMLResponse:
    user = current_user(request, session)
    plano = request.query_params.get("plano", "")
    body = f"""
    <div class="card" style="max-width:420px;margin:0 auto;">
      <h1>Criar conta</h1>
      {flash_html(request)}
      <form method="post" action="/cadastro">
        <input type="hidden" name="plano" value="{plano}">
        <label>Nome</label>
        <input name="name" required>
        <label>Empresa</label>
        <input name="company_name">
        <label>E-mail</label>
        <input type="email" name="email" required>
        <label>Senha</label>
        <input type="password" name="password" minlength="6" required>
        <div style="margin-top:18px;"><button type="submit">Criar conta</button></div>
      </form>
      <p class="muted" style="margin-top:14px;">Já tem conta? <a href="/login">Entrar</a></p>
    </div>
    """
    return HTMLResponse(layout("Criar conta", body, user))


@app.post("/cadastro")
async def signup_action(
        request: Request,
        session: Session = Depends(get_session),
        name: str = Form(...),
        company_name: str = Form(""),
        email: str = Form(...),
        password: str = Form(...),
        plano: str = Form(""),
) -> Response:
    email = email.strip().lower()
    if session.exec(select(SmartUser).where(SmartUser.email == email)).first():
        set_flash(request, "Já existe uma conta com esse e-mail.")
        return RedirectResponse(f"/cadastro?plano={plano}", status_code=303)

    user = SmartUser(
        name=name.strip(),
        company_name=company_name.strip(),
        email=email,
        password_hash=bcrypt.hash(password),
    )
    session.add(user)
    session.commit()
    session.refresh(user)
    get_or_create_subscription(session, user)

    request.session["user_id"] = user.id

    if plano:
        return RedirectResponse(f"/assinar/{plano}", status_code=303)
    return RedirectResponse("/conta", status_code=303)


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, session: Session = Depends(get_session)) -> HTMLResponse:
    user = current_user(request, session)
    body = f"""
    <div class="card" style="max-width:420px;margin:0 auto;">
      <h1>Entrar</h1>
      {flash_html(request)}
      <form method="post" action="/login">
        <label>E-mail</label>
        <input type="email" name="email" required>
        <label>Senha</label>
        <input type="password" name="password" required>
        <div style="margin-top:18px;"><button type="submit">Entrar</button></div>
      </form>
      <p class="muted" style="margin-top:14px;">Não tem conta? <a href="/cadastro">Criar conta</a></p>
    </div>
    """
    return HTMLResponse(layout("Entrar", body, user))


@app.post("/login")
async def login_action(
        request: Request,
        session: Session = Depends(get_session),
        email: str = Form(...),
        password: str = Form(...),
) -> Response:
    user = session.exec(select(SmartUser).where(SmartUser.email == email.strip().lower())).first()
    if not user or not bcrypt.verify(password, user.password_hash):
        set_flash(request, "E-mail ou senha incorretos.")
        return RedirectResponse("/login", status_code=303)
    request.session["user_id"] = user.id
    return RedirectResponse("/chat", status_code=303)


@app.get("/logout")
async def logout(request: Request) -> Response:
    request.session.clear()
    return RedirectResponse("/", status_code=303)


# ── Conta e assinatura ────────────────────────────────────────────────────────

@app.get("/conta", response_class=HTMLResponse)
async def conta_page(request: Request, session: Session = Depends(get_session)) -> HTMLResponse:
    user = current_user(request, session)
    if not user:
        return RedirectResponse("/login", status_code=303)

    sub = get_or_create_subscription(session, user)
    plan = session.exec(select(SmartPlan).where(SmartPlan.code == sub.plan_code)).first()
    status_label = {"active": "Ativa", "inactive": "Inativa", "canceled": "Cancelada"}.get(sub.status, sub.status)

    plans = session.exec(select(SmartPlan).where(SmartPlan.active == True).order_by(SmartPlan.order_idx)).all()  # noqa: E712
    plans_html = ""
    for p in plans:
        price = p.price_cents / 100
        action = "Plano atual" if p.code == sub.plan_code and sub.status == "active" else "Assinar"
        disabled = "disabled" if action == "Plano atual" else ""
        plans_html += f"""
        <div class="plan">
          <div style="font-weight:600;">{p.name}</div>
          <div class="price">R$ {price:,.2f}</div>
          <form method="get" action="/assinar/{p.code}">
            <button type="submit" {disabled}>{action}</button>
          </form>
        </div>"""

    body = f"""
    <div class="card">
      <h1>Minha conta</h1>
      {flash_html(request)}
      <p><strong>{user.name}</strong> — {user.email}</p>
      <p>Empresa: {user.company_name or "—"}</p>
      <p>Assinatura: <strong>{status_label}</strong>{f" ({plan.name})" if plan else ""}</p>
      {f'<p class="muted">Mensagens usadas neste ciclo: {sub.messages_used_this_cycle}' + (f"/{plan.message_limit_month}" if plan and plan.message_limit_month else " (ilimitado)") + "</p>" if sub.status == "active" else ""}
      <div class="plans">{plans_html}</div>
      <p style="margin-top:20px;"><a class="btn" href="/chat">Ir para o chat</a></p>
    </div>
    """
    return HTMLResponse(layout("Minha conta", body, user))


@app.get("/assinar/{plano_code}")
async def assinar(plano_code: str, request: Request, session: Session = Depends(get_session)) -> Response:
    user = current_user(request, session)
    if not user:
        return RedirectResponse(f"/cadastro?plano={plano_code}", status_code=303)

    plan = session.exec(select(SmartPlan).where(SmartPlan.code == plano_code, SmartPlan.active == True)).first()  # noqa: E712
    if not plan:
        set_flash(request, "Plano inválido.")
        return RedirectResponse("/conta", status_code=303)

    if stripe is None or not STRIPE_SECRET_KEY:
        set_flash(request, "Pagamento não está configurado ainda. Fale com o suporte para ativar manualmente.")
        return RedirectResponse("/conta", status_code=303)

    stripe.api_key = STRIPE_SECRET_KEY
    base_url = str(request.base_url).rstrip("/")

    if plan.stripe_price_id:
        line_item = {"price": plan.stripe_price_id, "quantity": 1}
    else:
        line_item = {
            "price_data": {
                "currency": "brl",
                "product_data": {"name": plan.name},
                "unit_amount": plan.price_cents,
                "recurring": {"interval": "month"},
            },
            "quantity": 1,
        }

    checkout = stripe.checkout.Session.create(
        mode="subscription",
        success_url=f"{base_url}/conta?sucesso=1",
        cancel_url=f"{base_url}/conta?cancelado=1",
        customer_email=user.email,
        line_items=[line_item],
        metadata={"smart_user_id": str(user.id), "plan_code": plan.code},
        subscription_data={"metadata": {"smart_user_id": str(user.id), "plan_code": plan.code}},
    )
    return RedirectResponse(checkout.url, status_code=303)


@app.post("/stripe/webhook")
async def stripe_webhook(request: Request, session: Session = Depends(get_session)) -> Response:
    if stripe is None or not STRIPE_WEBHOOK_SECRET:
        return Response(status_code=400)

    payload = await request.body()
    sig = request.headers.get("stripe-signature", "")
    stripe.api_key = STRIPE_SECRET_KEY

    try:
        event = stripe.Webhook.construct_event(payload, sig, STRIPE_WEBHOOK_SECRET)
    except Exception:
        return Response(status_code=400)

    data = event["data"]["object"]
    event_type = event["type"]

    if event_type in ("checkout.session.completed",):
        user_id = int(data.get("metadata", {}).get("smart_user_id", 0) or 0)
        plan_code = data.get("metadata", {}).get("plan_code", "")
        if user_id:
            user = session.get(SmartUser, user_id)
            if user:
                sub = get_or_create_subscription(session, user)
                sub.status = "active"
                sub.plan_code = plan_code
                sub.stripe_customer_id = data.get("customer", "") or sub.stripe_customer_id
                sub.stripe_subscription_id = data.get("subscription", "") or sub.stripe_subscription_id
                sub.messages_used_this_cycle = 0
                sub.cycle_started_at = utcnow()
                sub.updated_at = utcnow()
                session.add(sub)
                session.commit()

    elif event_type in ("customer.subscription.deleted",):
        stripe_sub_id = data.get("id", "")
        sub = session.exec(
            select(SmartSubscription).where(SmartSubscription.stripe_subscription_id == stripe_sub_id)
        ).first()
        if sub:
            sub.status = "canceled"
            sub.updated_at = utcnow()
            session.add(sub)
            session.commit()

    elif event_type in ("invoice.paid",):
        stripe_sub_id = data.get("subscription", "")
        sub = session.exec(
            select(SmartSubscription).where(SmartSubscription.stripe_subscription_id == stripe_sub_id)
        ).first()
        if sub:
            sub.status = "active"
            sub.messages_used_this_cycle = 0
            sub.cycle_started_at = utcnow()
            sub.updated_at = utcnow()
            session.add(sub)
            session.commit()

    return Response(status_code=200)


# ── Chat ──────────────────────────────────────────────────────────────────────

@app.get("/chat", response_class=HTMLResponse)
async def chat_page(request: Request, session: Session = Depends(get_session)) -> HTMLResponse:
    user = current_user(request, session)
    if not user:
        return RedirectResponse("/login", status_code=303)

    sub = get_or_create_subscription(session, user)
    ok, motivo = subscription_is_usable(session, sub)

    history = session.exec(
        select(SmartChatMessage).where(SmartChatMessage.user_id == user.id).order_by(SmartChatMessage.created_at)
    ).all()
    history_html = "".join(
        f'<div class="msg {m.role}">{m.content}</div>' for m in history
    )

    blocked_banner = "" if ok else f'<div class="flash">{motivo} <a href="/conta">Ver planos</a></div>'
    input_disabled = "disabled" if not ok else ""

    body = f"""
    <div class="card">
      <h1>Chat com o Augur Smart</h1>
      {blocked_banner}
      <div id="chat-box">{history_html or '<p class="muted">Comece perguntando algo sobre sua empresa — finanças, precificação, fluxo de caixa, gestão...</p>'}</div>
      <form class="chat-form" id="chat-form">
        <textarea id="chat-input" placeholder="Digite sua pergunta..." {input_disabled}></textarea>
        <button type="submit" {input_disabled}>Enviar</button>
      </form>
    </div>
    <script>
      const box = document.getElementById('chat-box');
      const form = document.getElementById('chat-form');
      const input = document.getElementById('chat-input');
      box.scrollTop = box.scrollHeight;

      form.addEventListener('submit', async (e) => {{
        e.preventDefault();
        const text = input.value.trim();
        if (!text) return;
        box.insertAdjacentHTML('beforeend', '<div class="msg user"></div>');
        box.lastElementChild.textContent = text;
        input.value = '';
        box.scrollTop = box.scrollHeight;

        const thinking = document.createElement('div');
        thinking.className = 'msg assistant';
        thinking.textContent = 'Pensando...';
        box.appendChild(thinking);
        box.scrollTop = box.scrollHeight;

        try {{
          const r = await fetch('/api/chat', {{
            method: 'POST',
            headers: {{'Content-Type': 'application/json'}},
            body: JSON.stringify({{message: text}}),
          }});
          const d = await r.json();
          thinking.textContent = d.reply || d.erro || 'Erro ao responder.';
        }} catch (err) {{
          thinking.textContent = 'Erro de conexão. Tente novamente.';
        }}
        box.scrollTop = box.scrollHeight;
      }});
    </script>
    """
    return HTMLResponse(layout("Chat", body, user))


@app.post("/api/chat")
async def api_chat(request: Request, session: Session = Depends(get_session)) -> JSONResponse:
    user = current_user(request, session)
    if not user:
        return JSONResponse({"erro": "Não autenticado."}, status_code=401)

    sub = get_or_create_subscription(session, user)
    ok, motivo = subscription_is_usable(session, sub)
    if not ok:
        return JSONResponse({"erro": motivo}, status_code=403)

    payload = await request.json()
    user_text = (payload.get("message") or "").strip()
    if not user_text:
        return JSONResponse({"erro": "Mensagem vazia."}, status_code=400)

    if not ANTHROPIC_API_KEY:
        return JSONResponse({"erro": "IA não configurada (ANTHROPIC_API_KEY ausente)."}, status_code=503)

    session.add(SmartChatMessage(user_id=user.id, role="user", content=user_text))
    session.commit()

    history = session.exec(
        select(SmartChatMessage)
        .where(SmartChatMessage.user_id == user.id)
        .order_by(SmartChatMessage.created_at.desc())
        .limit(MAX_MESSAGES_PER_REQUEST_CONTEXT)
    ).all()
    history = list(reversed(history))
    messages = [{"role": m.role, "content": m.content} for m in history]

    try:
        resp = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": "claude-sonnet-4-6",
                "max_tokens": 1024,
                "system": AUGUR_SYSTEM_PROMPT,
                "messages": messages,
            },
            timeout=60,
        )
        resp.raise_for_status()
        reply = resp.json()["content"][0]["text"]
    except Exception as e:
        return JSONResponse({"erro": f"Erro ao consultar a IA: {e}"}, status_code=502)

    session.add(SmartChatMessage(user_id=user.id, role="assistant", content=reply))
    sub.messages_used_this_cycle += 1
    sub.updated_at = utcnow()
    session.add(sub)
    session.commit()

    return JSONResponse({"reply": reply})


# ── Admin de precificação ─────────────────────────────────────────────────────

@app.get("/admin/precos", response_class=HTMLResponse)
async def admin_precos(request: Request, session: Session = Depends(get_session)) -> HTMLResponse:
    user = current_user(request, session)
    if not user or not is_admin(user):
        return RedirectResponse("/", status_code=303)

    plans = session.exec(select(SmartPlan).order_by(SmartPlan.order_idx)).all()
    rows = ""
    for p in plans:
        rows += f"""
        <tr>
          <form method="post" action="/admin/precos/{p.id}">
          <td>{p.code}</td>
          <td><input name="name" value="{p.name}"></td>
          <td><input name="price_cents" type="number" value="{p.price_cents}" style="width:100px;"></td>
          <td><input name="message_limit_month" type="number" value="{p.message_limit_month}" style="width:90px;"></td>
          <td><input name="stripe_price_id" value="{p.stripe_price_id}" placeholder="price_..."></td>
          <td><input type="checkbox" name="active" {"checked" if p.active else ""}></td>
          <td><button type="submit">Salvar</button></td>
          </form>
        </tr>"""

    body = f"""
    <div class="card">
      <h1>Precificação — Admin</h1>
      {flash_html(request)}
      <table>
        <tr><th>Código</th><th>Nome</th><th>Preço (centavos)</th><th>Limite msgs/mês</th><th>Stripe price ID</th><th>Ativo</th><th></th></tr>
        {rows}
      </table>
      <h2 style="margin-top:30px;font-size:1.1rem;">Novo plano</h2>
      <form method="post" action="/admin/precos/novo">
        <label>Código (único, sem espaço)</label>
        <input name="code" required>
        <label>Nome</label>
        <input name="name" required>
        <label>Preço (R$)</label>
        <input name="price_reais" type="number" step="0.01" required>
        <label>Limite de mensagens/mês (0 = ilimitado)</label>
        <input name="message_limit_month" type="number" value="0">
        <label>Stripe price ID (opcional)</label>
        <input name="stripe_price_id" placeholder="price_...">
        <div style="margin-top:14px;"><button type="submit">Criar plano</button></div>
      </form>
    </div>
    """
    return HTMLResponse(layout("Admin · Preços", body, user))


@app.post("/admin/precos/novo")
async def admin_precos_novo(
        request: Request,
        session: Session = Depends(get_session),
        code: str = Form(...),
        name: str = Form(...),
        price_reais: float = Form(...),
        message_limit_month: int = Form(0),
        stripe_price_id: str = Form(""),
) -> Response:
    user = current_user(request, session)
    if not user or not is_admin(user):
        return RedirectResponse("/", status_code=303)

    code = code.strip().lower().replace(" ", "_")
    if session.exec(select(SmartPlan).where(SmartPlan.code == code)).first():
        set_flash(request, "Já existe um plano com esse código.")
        return RedirectResponse("/admin/precos", status_code=303)

    max_order = session.exec(select(SmartPlan)).all()
    plan = SmartPlan(
        code=code,
        name=name.strip(),
        price_cents=int(round(price_reais * 100)),
        message_limit_month=int(message_limit_month),
        stripe_price_id=stripe_price_id.strip(),
        order_idx=len(max_order) + 1,
    )
    session.add(plan)
    session.commit()
    set_flash(request, "Plano criado.")
    return RedirectResponse("/admin/precos", status_code=303)


@app.post("/admin/precos/{plan_id}")
async def admin_precos_editar(
        plan_id: int,
        request: Request,
        session: Session = Depends(get_session),
        name: str = Form(...),
        price_cents: int = Form(...),
        message_limit_month: int = Form(0),
        stripe_price_id: str = Form(""),
        active: Optional[str] = Form(None),
) -> Response:
    user = current_user(request, session)
    if not user or not is_admin(user):
        return RedirectResponse("/", status_code=303)

    plan = session.get(SmartPlan, plan_id)
    if plan:
        plan.name = name.strip()
        plan.price_cents = int(price_cents)
        plan.message_limit_month = int(message_limit_month)
        plan.stripe_price_id = stripe_price_id.strip()
        plan.active = bool(active)
        session.add(plan)
        session.commit()
        set_flash(request, "Plano atualizado.")
    return RedirectResponse("/admin/precos", status_code=303)


@app.get("/healthz")
async def healthz() -> dict:
    return {"ok": True}

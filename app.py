# /app.py
from __future__ import annotations
from sqlalchemy import func
from sqlalchemy.exc import OperationalError
import base64
import hashlib
import inspect
import json
import os
import re
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path
from typing import Any, Callable, Optional

import httpx
from fastapi import Depends, FastAPI, File, Form, Request, Response, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from jinja2 import Environment
from jinja2.loaders import DictLoader
from passlib.context import CryptContext
from sqlalchemy import UniqueConstraint
from sqlalchemy.exc import IntegrityError
from sqlmodel import Field, Session, SQLModel, create_engine, select
from starlette.middleware.sessions import SessionMiddleware
from starlette.responses import FileResponse
from fastapi.staticfiles import StaticFiles

# ----------------------------
# Config
# ----------------------------

APP_SECRET_KEY = os.getenv("APP_SECRET_KEY") or secrets.token_urlsafe(32)
DATABASE_URL = os.getenv("DATABASE_URL") or "sqlite:///./app.db"

NOTION_TOKEN = os.getenv("NOTION_TOKEN")
NOTION_DB_NEGOCIOS_ID = os.getenv("NOTION_DB_NEGOCIOS_ID")

UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR") or "./uploads").resolve()
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

engine = create_engine(
    DATABASE_URL,
    echo=False,
    connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {},
)

_MAX_PASSWORD_BYTES = 1024
_MAX_UPLOAD_BYTES = 20 * 1024 * 1024  # 20MB (ajuste se quiser)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _normalize_password(password: str) -> str:
    pw_bytes = password.encode("utf-8")
    if len(pw_bytes) <= 72:
        return password
    if len(pw_bytes) > _MAX_PASSWORD_BYTES:
        pw_bytes = pw_bytes[:_MAX_PASSWORD_BYTES]
    digest = hashlib.sha256(pw_bytes).digest()
    b64 = base64.urlsafe_b64encode(digest).decode("ascii")
    return f"sha256${b64}"


def hash_password(password: str) -> str:
    return pwd_context.hash(_normalize_password(password))


def verify_password(password: str, password_hash: str) -> bool:
    return pwd_context.verify(_normalize_password(password), password_hash)


# ----------------------------
# Models
# ----------------------------


class User(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    email: str = Field(index=True, unique=True)
    password_hash: str
    created_at: datetime = Field(default_factory=utcnow)


class Company(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    created_at: datetime = Field(default_factory=utcnow)


class Client(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    company_id: int = Field(index=True, foreign_key="company.id")

    # Dados completos
    name: str
    cnpj: str = ""
    email: str = ""
    phone: str = ""
    finance_email: str = ""
    address: str = ""
    city: str = ""
    state: str = ""
    zip_code: str = ""
    notes: str = ""

    # Indicadores
    revenue_monthly_brl: float = 0.0
    debt_total_brl: float = 0.0
    cash_balance_brl: float = 0.0
    employees_count: int = 0

    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class Membership(SQLModel, table=True):
    __table_args__ = (UniqueConstraint("user_id", "company_id", name="uq_membership_user_company"),)

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(index=True, foreign_key="user.id")
    company_id: int = Field(index=True, foreign_key="company.id")
    role: str = Field(default="cliente", index=True)  # admin | equipe | cliente
    client_id: Optional[int] = Field(default=None, index=True, foreign_key="client.id")
    created_at: datetime = Field(default_factory=utcnow)


class OnboardingDiagnostic(SQLModel, table=True):
    __table_args__ = (UniqueConstraint("user_id", "company_id", name="uq_diag_user_company"),)

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(index=True, foreign_key="user.id")
    company_id: int = Field(index=True, foreign_key="company.id")
    answers_json: str
    created_at: datetime = Field(default_factory=utcnow)


# ----------------------------
# Documentos (contratos, termos etc.)
# ----------------------------

DOC_STATUSES = {"rascunho", "aguardando_cliente", "cliente_enviou", "concluido"}


CONSULT_PROJECT_STATUS = {"ativo", "pausado", "concluido"}


class ConsultingProject(SQLModel, table=True):
    """
    Projeto de consultoria por cliente.
    """
    id: Optional[int] = Field(default=None, primary_key=True)

    company_id: int = Field(index=True, foreign_key="company.id")
    client_id: int = Field(index=True, foreign_key="client.id")
    created_by_user_id: int = Field(index=True, foreign_key="user.id")

    name: str
    description: str = ""
    status: str = Field(default="ativo", index=True)  # ativo|pausado|concluido

    start_date: str = ""  # AAAA-MM-DD (MVP simples)
    due_date: str = ""    # AAAA-MM-DD (MVP simples)

    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class ConsultingStage(SQLModel, table=True):
    """
    Etapa do projeto (ordenada).
    """
    id: Optional[int] = Field(default=None, primary_key=True)

    project_id: int = Field(index=True, foreign_key="consultingproject.id")

    name: str
    order: int = Field(default=1, index=True)
    due_date: str = ""  # AAAA-MM-DD

    created_at: datetime = Field(default_factory=utcnow)


class ConsultingStep(SQLModel, table=True):
    """
    Sub-etapa / item de entrega.
    Progress (%) é calculado pelo total de steps concluídos (ponderado por weight).
    """
    id: Optional[int] = Field(default=None, primary_key=True)

    stage_id: int = Field(index=True, foreign_key="consultingstage.id")

    title: str
    description: str = ""
    due_date: str = ""  # AAAA-MM-DD
    weight: float = Field(default=1.0)  # peso para cálculo do %
    done: bool = Field(default=False, index=True)

    # Se True, o CLIENTE pode marcar como feito (útil para “aguardando cliente”)
    client_action: bool = Field(default=False, index=True)

    done_at: Optional[datetime] = None
    updated_at: datetime = Field(default_factory=utcnow)
class Document(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    company_id: int = Field(index=True, foreign_key="company.id")
    client_id: int = Field(index=True, foreign_key="client.id")
    created_by_user_id: int = Field(index=True, foreign_key="user.id")
    title: str
    content: str
    status: str = Field(default="rascunho", index=True)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class DocumentMessage(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    document_id: int = Field(index=True, foreign_key="document.id")
    author_user_id: int = Field(index=True, foreign_key="user.id")
    message: str = ""
    created_at: datetime = Field(default_factory=utcnow)


# ----------------------------
# Propostas (proposta do escritório) + Solicitação do cliente
# ----------------------------

PROPOSAL_KINDS = {"proposta", "solicitacao"}
PROPOSAL_STATUSES = {
    # proposta (escritório)
    "rascunho",
    "enviada",
    "aprovada",
    "rejeitada",
    # solicitacao (cliente)
    "aberta",
    "em_analise",
    "respondida",
    "encerrada",
}


class Proposal(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    company_id: int = Field(index=True, foreign_key="company.id")
    client_id: int = Field(index=True, foreign_key="client.id")
    created_by_user_id: int = Field(index=True, foreign_key="user.id")

    kind: str = Field(default="proposta", index=True)  # proposta | solicitacao
    title: str
    description: str = ""  # solicitação do cliente ou notas da proposta
    value_brl: float = 0.0  # usado normalmente para "proposta"
    status: str = Field(default="rascunho", index=True)

    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class ProposalMessage(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    proposal_id: int = Field(index=True, foreign_key="proposal.id")
    author_user_id: int = Field(index=True, foreign_key="user.id")
    message: str = ""
    created_at: datetime = Field(default_factory=utcnow)


# ----------------------------
# Financeiro (Notas/Boletos/Honorários)
# ----------------------------

FIN_STATUSES = {"emitido", "pago", "atrasado", "cancelado"}


class FinanceInvoice(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    company_id: int = Field(index=True, foreign_key="company.id")
    client_id: int = Field(index=True, foreign_key="client.id")
    created_by_user_id: int = Field(index=True, foreign_key="user.id")

    title: str  # ex: "Honorários - Março/2026"
    amount_brl: float = 0.0
    due_date: str = ""  # AAAA-MM-DD (MVP simples)
    status: str = Field(default="emitido", index=True)
    notes: str = ""

    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


# ----------------------------
# Pendências (Checklist)
# ----------------------------

PENDING_STATUSES = {"aberto", "aguardando_cliente", "cliente_enviou", "concluido"}


class PendingItem(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    company_id: int = Field(index=True, foreign_key="company.id")
    client_id: int = Field(index=True, foreign_key="client.id")
    created_by_user_id: int = Field(index=True, foreign_key="user.id")

    title: str
    description: str = ""
    status: str = Field(default="aberto", index=True)
    due_date: str = ""  # AAAA-MM-DD
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class PendingMessage(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    pending_item_id: int = Field(index=True, foreign_key="pendingitem.id")
    author_user_id: int = Field(index=True, foreign_key="user.id")
    message: str = ""
    created_at: datetime = Field(default_factory=utcnow)


# ----------------------------
# Attachments (um lugar único pra anexos)
# ----------------------------


class Attachment(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)

    company_id: int = Field(index=True, foreign_key="company.id")
    client_id: int = Field(index=True, foreign_key="client.id")
    uploaded_by_user_id: int = Field(index=True, foreign_key="user.id")

    document_id: Optional[int] = Field(default=None, index=True, foreign_key="document.id")
    proposal_id: Optional[int] = Field(default=None, index=True, foreign_key="proposal.id")
    finance_invoice_id: Optional[int] = Field(default=None, index=True, foreign_key="financeinvoice.id")
    pending_item_id: Optional[int] = Field(default=None, index=True, foreign_key="pendingitem.id")

    original_filename: str
    stored_filename: str
    mime_type: str = "application/octet-stream"
    size_bytes: int = 0
    created_at: datetime = Field(default_factory=utcnow)


# ----------------------------
# DB
# ----------------------------


def init_db() -> None:
    # Em produção (Postgres), quem cria/alterar tabelas é o Alembic.
    # Em dev local (SQLite), criamos automaticamente.
    if engine.url.get_backend_name().startswith("sqlite"):
        SQLModel.metadata.create_all(engine)


def get_session() -> Session:
    with Session(engine) as session:
        yield session


# ----------------------------
# Notion sync (optional)
# ----------------------------


async def sync_to_notion_negocios(*, user: User, company: Company, diagnostic: dict[str, Any]) -> None:
    if not (NOTION_TOKEN and NOTION_DB_NEGOCIOS_ID):
        return

    headers = {
        "Authorization": f"Bearer {NOTION_TOKEN}",
        "Notion-Version": "2022-06-28",
        "Content-Type": "application/json",
    }

    def rt(text: str) -> list[dict[str, Any]]:
        return [{"type": "text", "text": {"content": text}}]

    payload = {
        "parent": {"database_id": NOTION_DB_NEGOCIOS_ID},
        "properties": {
            "Nome": {"title": rt(user.name)},
            "Email": {"rich_text": rt(user.email)},
            "Empresa": {"rich_text": rt(company.name)},
            "Diagnóstico": {"rich_text": rt(json.dumps(diagnostic, ensure_ascii=False))},
            "Origem": {"rich_text": rt("App Escritório (Multi-tenant)")},
        },
    }

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post("https://api.notion.com/v1/pages", headers=headers, json=payload)
            resp.raise_for_status()
    except Exception:
        return


# ----------------------------
# Tenant / Auth helpers
# ----------------------------


def session_user_id(request: Request) -> Optional[int]:
    raw = request.session.get("user_id")
    return int(raw) if raw is not None else None


def session_company_id(request: Request) -> Optional[int]:
    raw = request.session.get("company_id")
    return int(raw) if raw is not None else None


def set_flash(request: Request, message: str) -> None:
    request.session["flash"] = message


@dataclass(frozen=True)
class TenantContext:
    user: User
    company: Company
    membership: Membership


def get_current_user(request: Request, session: Session) -> Optional[User]:
    uid = session_user_id(request)
    return session.get(User, uid) if uid else None


def get_membership(session: Session, user_id: int, company_id: int) -> Optional[Membership]:
    return session.exec(
        select(Membership).where(Membership.user_id == user_id, Membership.company_id == company_id)
    ).first()


def ensure_company_in_session(request: Request, session: Session, user: User) -> Optional[int]:
    cid = session_company_id(request)
    if cid and get_membership(session, user.id, cid):
        return cid

    first_membership = session.exec(select(Membership).where(Membership.user_id == user.id)).first()
    if not first_membership:
        return None

    request.session["company_id"] = first_membership.company_id
    return first_membership.company_id

def _clamp01(x: float) -> float:
    return 0.0 if x < 0 else 1.0 if x > 1 else x


def compute_project_progress(session: Session, project_id: int) -> float:
    """
    Retorna progresso 0..1 somando pesos concluídos / pesos totais.
    """
    stage_ids = session.exec(
        select(ConsultingStage.id).where(ConsultingStage.project_id == project_id)
    ).all()
    if not stage_ids:
        return 0.0

    total = session.exec(
        select(func.coalesce(func.sum(ConsultingStep.weight), 0.0)).where(ConsultingStep.stage_id.in_(stage_ids))
    ).one()
    done = session.exec(
        select(func.coalesce(func.sum(ConsultingStep.weight), 0.0)).where(
            ConsultingStep.stage_id.in_(stage_ids),
            ConsultingStep.done.is_(True),
        )
    ).one()

    total_val = float(total or 0.0)
    if total_val <= 0.0:
        return 0.0
    return _clamp01(float(done or 0.0) / total_val)


def _next_stage_order(session: Session, project_id: int) -> int:
    max_order = session.exec(
        select(func.max(ConsultingStage.order)).where(ConsultingStage.project_id == project_id)
    ).one()
    return int(max_order or 0) + 1
def get_tenant_context(request: Request, session: Session) -> Optional[TenantContext]:
    user = get_current_user(request, session)
    if not user:
        return None

    cid = ensure_company_in_session(request, session, user)
    if not cid:
        return None

    membership = get_membership(session, user.id, cid)
    if not membership:
        return None

    company = session.get(Company, cid)
    if not company:
        return None

    return TenantContext(user=user, company=company, membership=membership)


def require_login(handler: Callable[..., Any]) -> Callable[..., Any]:
    @wraps(handler)
    async def wrapper(*args: Any, **kwargs: Any) -> Any:
        request: Request = kwargs.get("request") or (args[0] if args else None)
        if request is None:
            raise RuntimeError("Request não encontrado no handler.")
        if session_user_id(request) is None:
            return RedirectResponse("/login", status_code=303)
        return await handler(*args, **kwargs)

    wrapper.__signature__ = inspect.signature(handler)
    return wrapper


def require_role(allowed: set[str]) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    def decorator(handler: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(handler)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            request: Request = kwargs.get("request") or (args[0] if args else None)
            session: Session = kwargs.get("session")
            if request is None or session is None:
                raise RuntimeError("Request/Session não encontrados no handler.")

            ctx = get_tenant_context(request, session)
            if not ctx:
                request.session.clear()
                return RedirectResponse("/login", status_code=303)

            if ctx.membership.role not in allowed:
                return render(
                    "error.html",
                    request=request,
                    context={
                        "current_user": ctx.user,
                        "current_company": ctx.company,
                        "role": ctx.membership.role,
                        "current_client": None,
                        "message": "Você não tem permissão para acessar esta área.",
                    },
                    status_code=403,
                )

            return await handler(*args, **kwargs)

        wrapper.__signature__ = inspect.signature(handler)
        return wrapper

    return decorator


def _is_staff(role: str) -> bool:
    return role in {"admin", "equipe"}


def _safe_int(value: Any) -> Optional[int]:
    try:
        return int(value)
    except Exception:
        return None


def _get_selected_client_for_staff(request: Request, session: Session, company_id: int) -> Optional[int]:
    cid = _safe_int(request.session.get("selected_client_id"))
    if cid:
        c = session.get(Client, cid)
        if c and c.company_id == company_id:
            return cid

    first_client = session.exec(
        select(Client).where(Client.company_id == company_id).order_by(Client.created_at)
    ).first()
    if not first_client:
        return None

    request.session["selected_client_id"] = first_client.id
    return first_client.id


def get_active_client_id(request: Request, session: Session, ctx: TenantContext) -> Optional[int]:
    if ctx.membership.role == "cliente":
        return ctx.membership.client_id
    return _get_selected_client_for_staff(request, session, ctx.company.id)


def get_client_or_none(session: Session, company_id: int, client_id: Optional[int]) -> Optional[Client]:
    if not client_id:
        return None
    c = session.get(Client, int(client_id))
    if not c or c.company_id != company_id:
        return None
    return c


def ensure_can_access_client(ctx: TenantContext, client_id: int) -> bool:
    if _is_staff(ctx.membership.role):
        return True
    return ctx.membership.client_id == client_id


# ----------------------------
# Uploads
# ----------------------------

_FILENAME_RE = re.compile(r"[^A-Za-z0-9._-]+")


def safe_filename(name: str) -> str:
    name = name.strip().replace(" ", "_")
    name = _FILENAME_RE.sub("_", name)
    return name[:180] if len(name) > 180 else name


async def save_upload(upload: UploadFile) -> tuple[str, str, int]:
    original = upload.filename or "arquivo"
    stored = f"{uuid.uuid4().hex}_{safe_filename(original)}"
    path = UPLOAD_DIR / stored

    size = 0
    with path.open("wb") as f:
        while True:
            chunk = await upload.read(1024 * 1024)
            if not chunk:
                break
            size += len(chunk)
            if size > _MAX_UPLOAD_BYTES:
                try:
                    f.close()
                finally:
                    if path.exists():
                        path.unlink(missing_ok=True)
                raise ValueError("Arquivo excede o limite de tamanho.")
            f.write(chunk)

    mime = upload.content_type or "application/octet-stream"
    return stored, mime, size


# ----------------------------
# Templates
# ----------------------------

TEMPLATES: dict[str, str] = {
    "base.html": r"""
<!doctype html>
<html lang="pt-br">
  <head>
    <meta charset="utf-8"/>
    <meta name="viewport" content="width=device-width, initial-scale=1"/>
    <title>{{ title or "App Escritório" }}</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css" rel="stylesheet">
    <style>
      body { background: #f6f7fb; }
      .card { border: 0; box-shadow: 0 6px 18px rgba(0,0,0,.06); border-radius: 16px; }
      .brand { font-weight: 700; letter-spacing: .3px; }
      .muted { color: #6c757d; }
      a { text-decoration: none; }
      .btn { border-radius: 12px; }
      .form-control, .form-select { border-radius: 12px; }
      .badge { border-radius: 999px; }
      .mono { font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace;}
      pre { white-space: pre-wrap; margin: 0; }
      /* PRIMARY = LARANJA (marca) */
.btn-primary{
  background-color:#E07020 !important;
  border-color:#E07020 !important;
  color:#ffffff !important;
  font-weight:600;
}
.btn-primary:hover{
  background-color:#C85F1B !important;
  border-color:#C85F1B !important;
}

/* OUTLINE PRIMARY = LARANJA */
.btn-outline-primary{
  border-color:#E07020 !important;
  color:#E07020 !important;
}
.btn-outline-primary:hover{
  background-color:#E07020 !important;
  border-color:#E07020 !important;
  color:#ffffff !important;
}

/* Links com teal (opcional) */
a:hover{ color:#00BFBF; }
    </style>
  </head>
  <body>
    <nav class="navbar navbar-expand-lg bg-white border-bottom">
      <div class="container py-2">
        <a class="navbar-brand d-flex align-items-center gap-2" href="/">
  <img src="/static/logo.png" alt="Maffezzolli Capital" style="height:32px; width:auto;">
  <span class="fw-bold" style="color:#0B1E1E;">Maffezzolli Capital</span>
</a>
        <div class="ms-auto d-flex gap-2 align-items-center">
          {% if current_user %}
            <span class="badge text-bg-light border">🏢 {{ current_company.name }}</span>

            {% if role in ["admin","equipe"] and current_client %}
              <span class="badge text-bg-light border">🧑‍💼 Cliente: {{ current_client.name }}</span>
              <a class="btn btn-outline-secondary btn-sm" href="/client/switch">Trocar cliente</a>
            {% endif %}

            <span class="badge text-bg-light border">👤 {{ current_user.name }} • {{ role }}</span>
            <a class="btn btn-outline-secondary btn-sm" href="/logout">Sair</a>
          {% else %}
            <a class="btn btn-outline-primary btn-sm" href="/login">Entrar</a>
          {% endif %}
        </div>
      </div>
    </nav>

    <main class="container my-4">
      {% if flash %}
        <div class="alert alert-info">{{ flash }}</div>
      {% endif %}
      {% block content %}{% endblock %}
      <div class="mt-5 muted small">
        <div>Uploads protegidos por login (download via rota).</div>
      </div>
    </main>
  </body>
</html>
""",
    "login.html": r"""
{% extends "base.html" %}
{% block content %}
<div class="row justify-content-center">
  <div class="col-md-6 col-lg-5">
    <div class="card p-4">
      <h4 class="mb-1">Login</h4>
      <div class="muted mb-3">Acesse sua conta</div>
      <form method="post" action="/login">
        <div class="mb-3">
          <label class="form-label">E-mail</label>
          <input class="form-control" name="email" type="email" required />
        </div>
        <div class="mb-3">
          <label class="form-label">Senha</label>
          <input class="form-control" name="password" type="password" required />
        </div>
        <button class="btn btn-primary w-100">Entrar</button>
      </form>
      <hr class="my-4"/>
      <div class="d-flex justify-content-between align-items-center">
        <div class="muted">Primeiro acesso?</div>
        <a class="btn btn-outline-primary" href="/signup">Criar escritório</a>
      </div>
    </div>
  </div>
</div>
{% endblock %}
""",
    "signup.html": r"""
{% extends "base.html" %}
{% block content %}
<div class="row justify-content-center">
  <div class="col-lg-8">
    <div class="card p-4">
      <h4 class="mb-1">Criar escritório + Admin + Diagnóstico</h4>
      <div class="muted mb-4">Você vira ADMIN do seu escritório.</div>

      <form method="post" action="/signup">
        <div class="row g-3">
          <div class="col-md-6">
            <label class="form-label">Seu nome</label>
            <input class="form-control" name="name" required />
          </div>
          <div class="col-md-6">
            <label class="form-label">Nome do escritório</label>
            <input class="form-control" name="company_name" required />
          </div>
          <div class="col-md-7">
            <label class="form-label">E-mail</label>
            <input class="form-control" name="email" type="email" required />
          </div>
          <div class="col-md-5">
            <label class="form-label">Senha</label>
            <input class="form-control" name="password" type="password" minlength="8" required />
          </div>
        </div>

        <hr class="my-4"/>

        <h6 class="mb-3">Diagnóstico (MVP)</h6>
        <div class="row g-3">
          <div class="col-md-6">
            <label class="form-label">Objetivo principal</label>
            <select class="form-select" name="goal" required>
              <option value="crescer">Crescer</option>
              <option value="organizar">Organizar processos</option>
              <option value="captar">Captação / vendas</option>
              <option value="financeiro">Melhorar financeiro</option>
            </select>
          </div>
          <div class="col-md-6">
            <label class="form-label">Faixa de faturamento</label>
            <select class="form-select" name="revenue" required>
              <option value="0-20k">R$ 0–20k</option>
              <option value="20k-100k">R$ 20k–100k</option>
              <option value="100k-500k">R$ 100k–500k</option>
              <option value="500k+">R$ 500k+</option>
            </select>
          </div>
          <div class="col-md-6">
            <label class="form-label">Funcionários</label>
            <input class="form-control" name="employees" type="number" min="0" value="0" required />
          </div>
          <div class="col-md-6">
            <label class="form-label">Maior dor hoje</label>
            <input class="form-control" name="pain" required />
          </div>
          <div class="col-12">
            <label class="form-label">Observações</label>
            <textarea class="form-control" name="notes" rows="3"></textarea>
          </div>
        </div>

        <div class="d-flex gap-2 mt-4">
          <button class="btn btn-primary">Criar</button>
          <a class="btn btn-outline-secondary" href="/login">Voltar</a>
        </div>
      </form>
    </div>
  </div>
</div>
{% endblock %}
""",
    "dashboard.html": r"""
{% extends "base.html" %}
{% block content %}
<div class="row g-3">
  <div class="col-12">
    <div class="card p-4">
      <h4 class="mb-1">Painel</h4>
      <div class="muted">
        {% if role in ["admin","equipe"] %}
          Escritório: <b>{{ current_company.name }}</b>.
          {% if current_client %} Cliente selecionado: <b>{{ current_client.name }}</b>.{% endif %}
        {% else %}
          Bem-vindo(a)! Você vê apenas seus dados e arquivos.
        {% endif %}
      </div>
      {% if role in ["admin","equipe"] %}
        <div class="mt-3 d-flex gap-2">
          <a class="btn btn-outline-primary btn-sm" href="/admin/members">Gerenciar membros</a>
          <a class="btn btn-outline-secondary btn-sm" href="/client/switch">Trocar cliente</a>
        </div>
      {% endif %}
    </div>
  </div>

  {% for item in items %}
    <div class="col-md-6 col-lg-4">
      <a href="{{ item.href }}">
        <div class="card p-4 h-100">
          <div class="d-flex justify-content-between align-items-start">
            <div>
              <div class="fw-semibold">{{ item.title }}</div>
              <div class="muted small mt-1">{{ item.desc }}</div>
            </div>
            <span class="badge text-bg-light border">→</span>
          </div>
        </div>
      </a>
    </div>
  {% endfor %}
</div>
{% endblock %}
""",
    "client_switch.html": r"""
{% extends "base.html" %}
{% block content %}
<div class="card p-4">
  <h4 class="mb-1">Trocar cliente</h4>
  <div class="muted mb-3">Selecione o cliente para trabalhar.</div>

  {% if not clients %}
    <div class="alert alert-warning">Nenhum cliente cadastrado. Vá em “Gerenciar membros” e crie um cliente.</div>
    <a class="btn btn-outline-secondary" href="/">Voltar</a>
  {% else %}
    <form method="post" action="/client/switch">
      <div class="mb-3">
        <label class="form-label">Cliente</label>
        <select class="form-select" name="client_id">
          {% for c in clients %}
            <option value="{{ c.id }}" {% if current_client and c.id==current_client.id %}selected{% endif %}>{{ c.name }}</option>
          {% endfor %}
        </select>
      </div>
      <button class="btn btn-primary">Selecionar</button>
      <a class="btn btn-outline-secondary" href="/">Cancelar</a>
    </form>
  {% endif %}
</div>
{% endblock %}
""",
    "members.html": r"""
{% extends "base.html" %}
{% block content %}
<div class="card p-4">
  <div class="d-flex justify-content-between align-items-center">
    <div>
      <h4 class="mb-0">Membros</h4>
      <div class="muted">Crie equipe e clientes (cada cliente vincula um “Client”).</div>
    </div>
    <a class="btn btn-outline-secondary" href="/">Voltar</a>
  </div>

  <hr class="my-3"/>

  <div class="row g-4">
    <div class="col-lg-7">
      <h6>Lista</h6>
      <div class="list-group">
        {% for row in rows %}
          <div class="list-group-item">
            <div class="d-flex justify-content-between">
              <div class="fw-semibold">{{ row.user.name }} <span class="muted">({{ row.user.email }})</span></div>
              <span class="badge text-bg-light border">{{ row.membership.role }}</span>
            </div>
            {% if row.membership.role == "cliente" %}
              <div class="muted small mt-1">Cliente vinculado: {{ row.client_name or "—" }}</div>
            {% endif %}
          </div>
        {% endfor %}
      </div>
    </div>

    <div class="col-lg-5">
      <h6>Adicionar</h6>
      <form method="post" action="/admin/members">
        <div class="mb-2">
          <label class="form-label">Nome</label>
          <input class="form-control" name="name" required />
        </div>
        <div class="mb-2">
          <label class="form-label">E-mail</label>
          <input class="form-control" name="email" type="email" required />
        </div>
        <div class="mb-2">
          <label class="form-label">Senha inicial</label>
          <input class="form-control" name="password" type="password" minlength="8" required />
        </div>
        <div class="mb-2">
          <label class="form-label">Role</label>
          <select class="form-select" name="role" required>
            <option value="cliente">cliente</option>
            <option value="equipe">equipe</option>
            <option value="admin">admin</option>
          </select>
        </div>
        <div class="mb-3">
          <label class="form-label">Nome do cliente (empresa atendida) — se role=cliente</label>
          <input class="form-control" name="client_name" placeholder="Ex: ACME LTDA" />
        </div>
        <button class="btn btn-primary w-100">Adicionar</button>
      </form>
    </div>
  </div>
</div>
{% endblock %}
""",
    "empresa.html": r"""
{% extends "base.html" %}
{% block content %}
<div class="card p-4">
  <div class="d-flex justify-content-between align-items-start">
    <div>
      <h4 class="mb-1">Empresa do Cliente</h4>
      <div class="muted">CNPJ, endereço, e-mails, telefone etc.</div>
    </div>
    <a class="btn btn-outline-secondary" href="/">Voltar</a>
  </div>
  <hr class="my-3"/>

  {% if not current_client %}
    <div class="alert alert-warning">
      Nenhum cliente selecionado/vinculado.
      {% if role in ["admin","equipe"] %}Use “Trocar cliente” ou crie um cliente em “Membros”.{% else %}Peça ao escritório para vincular seu acesso.{% endif %}
    </div>
  {% else %}
    <form method="post" action="/empresa">
      <div class="row g-3">
        <div class="col-md-8">
          <label class="form-label">Razão Social</label>
          <input class="form-control" name="name" value="{{ current_client.name }}" required />
        </div>
        <div class="col-md-4">
          <label class="form-label">CNPJ</label>
          <input class="form-control mono" name="cnpj" value="{{ current_client.cnpj }}" />
        </div>

        <div class="col-md-6">
          <label class="form-label">E-mail</label>
          <input class="form-control" name="email" type="email" value="{{ current_client.email }}" />
        </div>
        <div class="col-md-6">
          <label class="form-label">Telefone</label>
          <input class="form-control" name="phone" value="{{ current_client.phone }}" />
        </div>

        <div class="col-md-6">
          <label class="form-label">E-mail do financeiro</label>
          <input class="form-control" name="finance_email" type="email" value="{{ current_client.finance_email }}" />
        </div>
        <div class="col-md-6">
          <label class="form-label">Endereço</label>
          <input class="form-control" name="address" value="{{ current_client.address }}" />
        </div>

        <div class="col-md-4">
          <label class="form-label">Cidade</label>
          <input class="form-control" name="city" value="{{ current_client.city }}" />
        </div>
        <div class="col-md-4">
          <label class="form-label">Estado</label>
          <input class="form-control" name="state" value="{{ current_client.state }}" />
        </div>
        <div class="col-md-4">
          <label class="form-label">CEP</label>
          <input class="form-control mono" name="zip_code" value="{{ current_client.zip_code }}" />
        </div>

        <div class="col-12">
          <label class="form-label">Observações</label>
          <textarea class="form-control" name="notes" rows="3">{{ current_client.notes }}</textarea>
        </div>
      </div>

      <div class="d-flex gap-2 mt-4">
        <button class="btn btn-primary">Salvar</button>
        <a class="btn btn-outline-secondary" href="/perfil">Ver Perfil</a>
      </div>
    </form>
  {% endif %}
</div>
{% endblock %}
""",
    "perfil.html": r"""
{% extends "base.html" %}
{% block content %}
<div class="row g-3">
  <div class="col-lg-5">
    <div class="card p-4">
      <h4 class="mb-1">Meu Perfil</h4>
      <div class="muted mb-3">Dados do usuário</div>
      <div><span class="muted">Nome:</span> <b>{{ current_user.name }}</b></div>
      <div><span class="muted">E-mail:</span> <span class="mono">{{ current_user.email }}</span></div>
      <div><span class="muted">Role:</span> <b>{{ role }}</b></div>
    </div>
  </div>

  <div class="col-lg-7">
    <div class="card p-4">
      <h4 class="mb-1">Indicadores do Cliente</h4>
      <div class="muted mb-3">Faturamento, endividamento, caixa etc.</div>

      {% if not current_client %}
        <div class="alert alert-warning">Nenhum cliente selecionado/vinculado.</div>
      {% else %}
        <div class="mb-2"><span class="muted">Cliente:</span> <b>{{ current_client.name }}</b></div>

        <form method="post" action="/perfil">
          <div class="row g-3">
            <div class="col-md-6">
              <label class="form-label">Faturamento mensal (R$)</label>
              <input class="form-control" name="revenue_monthly_brl" type="number" step="0.01" min="0"
                     value="{{ current_client.revenue_monthly_brl }}" />
            </div>
            <div class="col-md-6">
              <label class="form-label">Endividamento total (R$)</label>
              <input class="form-control" name="debt_total_brl" type="number" step="0.01" min="0"
                     value="{{ current_client.debt_total_brl }}" />
            </div>
            <div class="col-md-6">
              <label class="form-label">Saldo em caixa (R$)</label>
              <input class="form-control" name="cash_balance_brl" type="number" step="0.01" min="0"
                     value="{{ current_client.cash_balance_brl }}" />
            </div>
            <div class="col-md-6">
              <label class="form-label">Funcionários</label>
              <input class="form-control" name="employees_count" type="number" min="0"
                     value="{{ current_client.employees_count }}" />
            </div>
          </div>
          <div class="mt-4">
            <button class="btn btn-primary">Salvar</button>
            <a class="btn btn-outline-secondary" href="/empresa">Editar dados da empresa</a>
          </div>
        </form>
      {% endif %}
    </div>
  </div>
</div>
{% endblock %}
""",
    "error.html": r"""
{% extends "base.html" %}
{% block content %}
<div class="card p-4">
  <h4 class="mb-1">Erro</h4>
  <div class="muted">{{ message }}</div>
  <div class="mt-3"><a class="btn btn-outline-secondary" href="/">Voltar</a></div>
</div>
{% endblock %}
""",
    # ---------------- Pendências ----------------
    "pending_list.html": r"""
{% extends "base.html" %}
{% block content %}
<div class="card p-4">
  <div class="d-flex justify-content-between align-items-center">
    <div>
      <h4 class="mb-0">Pendências</h4>
      <div class="muted">Checklist / solicitações de informação.</div>
    </div>
    {% if role in ["admin","equipe"] %}
      <a class="btn btn-primary" href="/pendencias/novo">Nova</a>
    {% endif %}
  </div>
  <hr class="my-3"/>
  {% if items %}
    <div class="list-group">
      {% for it in items %}
        <a class="list-group-item list-group-item-action" href="/pendencias/{{ it.id }}">
          <div class="d-flex justify-content-between">
            <div class="fw-semibold">{{ it.title }}</div>
            <span class="badge text-bg-light border">{{ it.status }}</span>
          </div>
          <div class="muted small">
            {% if role in ["admin","equipe"] %}Cliente: {{ it.client_name }} • {% endif %}
            {% if it.due_date %}Prazo: {{ it.due_date }} • {% endif %}
            {{ it.created_at }}
          </div>
        </a>
      {% endfor %}
    </div>
  {% else %}
    <div class="muted">Sem pendências.</div>
  {% endif %}
</div>
{% endblock %}
""",
    "pending_new.html": r"""
{% extends "base.html" %}
{% block content %}
<div class="card p-4">
  <h4>Nova Pendência</h4>
  <div class="muted">Direcione para um cliente.</div>
  {% if not clients %}
    <div class="alert alert-warning mt-3">Nenhum cliente cadastrado. Vá em “Membros”.</div>
    <a class="btn btn-outline-secondary" href="/pendencias">Voltar</a>
  {% else %}
    <form method="post" action="/pendencias/novo" enctype="multipart/form-data" class="mt-3">
      <div class="row g-3">
        <div class="col-12">
          <label class="form-label">Cliente</label>
          <select class="form-select" name="client_id" required>
            {% for c in clients %}
              <option value="{{ c.id }}" {% if current_client and c.id==current_client.id %}selected{% endif %}>{{ c.name }}</option>
            {% endfor %}
          </select>
        </div>
        <div class="col-md-8">
          <label class="form-label">Título</label>
          <input class="form-control" name="title" required />
        </div>
        <div class="col-md-4">
          <label class="form-label">Status</label>
          <select class="form-select" name="status">
            <option value="aberto">aberto</option>
            <option value="aguardando_cliente">aguardando_cliente</option>
            <option value="concluido">concluido</option>
          </select>
        </div>
        <div class="col-md-4">
          <label class="form-label">Prazo (AAAA-MM-DD)</label>
          <input class="form-control mono" name="due_date" placeholder="2026-03-31"/>
        </div>
        <div class="col-12">
          <label class="form-label">Descrição</label>
          <textarea class="form-control" name="description" rows="5"></textarea>
        </div>
        <div class="col-12">
          <label class="form-label">Anexo (opcional)</label>
          <input class="form-control" type="file" name="file" />
        </div>
      </div>
      <div class="mt-4 d-flex gap-2">
        <button class="btn btn-primary">Salvar</button>
        <a class="btn btn-outline-secondary" href="/pendencias">Cancelar</a>
      </div>
    </form>
  {% endif %}
</div>
{% endblock %}
""",
    "pending_detail.html": r"""
{% extends "base.html" %}
{% block content %}
<div class="card p-4">
  <div class="d-flex justify-content-between">
    <div>
      <h4 class="mb-1">{{ item.title }}</h4>
      <div class="muted">
        Status: <b>{{ item.status }}</b>
        {% if item.due_date %} • Prazo: <b>{{ item.due_date }}</b>{% endif %}
        {% if role in ["admin","equipe"] %} • Cliente: <b>{{ client.name }}</b>{% endif %}
      </div>
    </div>
    <a class="btn btn-outline-secondary" href="/pendencias">Voltar</a>
  </div>
  <hr class="my-3"/>
  <pre>{{ item.description }}</pre>

  <hr class="my-3"/>
  <h6>Anexos</h6>
  {% if attachments %}
    <ul>
      {% for a in attachments %}
        <li><a href="/download/{{ a.id }}">{{ a.original_filename }}</a></li>
      {% endfor %}
    </ul>
  {% else %}
    <div class="muted">Sem anexos.</div>
  {% endif %}

  <hr class="my-3"/>
  <h6>Mensagens</h6>
  {% if messages %}
    <div class="list-group mb-3">
      {% for m in messages %}
        <div class="list-group-item">
          <div class="d-flex justify-content-between">
            <div class="fw-semibold">{{ m.author_name }}</div>
            <div class="muted small">{{ m.created_at }}</div>
          </div>
          <pre class="mt-2">{{ m.message }}</pre>
        </div>
      {% endfor %}
    </div>
  {% else %}
    <div class="muted">Sem mensagens.</div>
  {% endif %}

  {% if role in ["admin","equipe"] %}
    <hr class="my-3"/>
    <form method="post" action="/pendencias/{{ item.id }}/status" class="row g-2 align-items-end">
      <div class="col-md-6">
        <label class="form-label">Alterar status</label>
        <select class="form-select" name="status">
          <option value="aberto" {% if item.status=="aberto" %}selected{% endif %}>aberto</option>
          <option value="aguardando_cliente" {% if item.status=="aguardando_cliente" %}selected{% endif %}>aguardando_cliente</option>
          <option value="cliente_enviou" {% if item.status=="cliente_enviou" %}selected{% endif %}>cliente_enviou</option>
          <option value="concluido" {% if item.status=="concluido" %}selected{% endif %}>concluido</option>
        </select>
      </div>
      <div class="col-md-3">
        <button class="btn btn-outline-primary w-100">Atualizar</button>
      </div>
    </form>

    <form method="post" action="/pendencias/{{ item.id }}/anexar" enctype="multipart/form-data" class="mt-3">
      <div class="mb-2">
        <label class="form-label">Mensagem (opcional)</label>
        <textarea class="form-control" name="message" rows="2"></textarea>
      </div>
      <div class="mb-2">
        <label class="form-label">Anexar arquivo</label>
        <input class="form-control" type="file" name="file" required />
      </div>
      <button class="btn btn-primary">Enviar</button>
    </form>
  {% else %}
    <hr class="my-3"/>
    {% if item.status == "aguardando_cliente" %}
      <div class="alert alert-warning">O escritório está aguardando seu envio.</div>
    {% endif %}
    <form method="post" action="/pendencias/{{ item.id }}/cliente-upload" enctype="multipart/form-data">
      <div class="mb-2">
        <label class="form-label">Mensagem (opcional)</label>
        <textarea class="form-control" name="message" rows="3"></textarea>
      </div>
      <div class="mb-2">
        <label class="form-label">Anexo (opcional)</label>
        <input class="form-control" type="file" name="file" />
      </div>
      <div class="form-check mb-3">
        <input class="form-check-input" type="checkbox" name="mark_done" value="1" id="doneCheck">
        <label class="form-check-label" for="doneCheck">Marcar como concluído</label>
      </div>
      <button class="btn btn-primary">Enviar</button>
    </form>
  {% endif %}
</div>
{% endblock %}
""",
    # ---------------- Documentos ----------------
    "docs_list.html": r"""
{% extends "base.html" %}
{% block content %}
<div class="card p-4">
  <div class="d-flex justify-content-between align-items-center">
    <div>
      <h4 class="mb-0">Documentos</h4>
      <div class="muted">Contratos, termos e documentos importantes.</div>
    </div>
    {% if role in ["admin","equipe"] %}
      <a class="btn btn-primary" href="/documentos/novo">Novo</a>
    {% endif %}
  </div>
  <hr class="my-3"/>
  {% if items %}
    <div class="list-group">
      {% for d in items %}
        <a class="list-group-item list-group-item-action" href="/documentos/{{ d.id }}">
          <div class="d-flex justify-content-between">
            <div class="fw-semibold">{{ d.title }}</div>
            <span class="badge text-bg-light border">{{ d.status }}</span>
          </div>
          <div class="muted small">
            {% if role in ["admin","equipe"] %}Cliente: {{ d.client_name }} • {% endif %}
            {{ d.created_at }}
          </div>
        </a>
      {% endfor %}
    </div>
  {% else %}
    <div class="muted">Sem documentos.</div>
  {% endif %}
</div>
{% endblock %}
""",
    "docs_new.html": r"""
{% extends "base.html" %}
{% block content %}
<div class="card p-4">
  <h4>Novo Documento</h4>
  <div class="muted">Direcione para um cliente e (se quiser) coloque “aguardando_cliente”.</div>
  {% if not clients %}
    <div class="alert alert-warning mt-3">Nenhum cliente cadastrado. Vá em “Membros”.</div>
    <a class="btn btn-outline-secondary" href="/documentos">Voltar</a>
  {% else %}
    <form method="post" action="/documentos/novo" enctype="multipart/form-data" class="mt-3">
      <div class="row g-3">
        <div class="col-12">
          <label class="form-label">Cliente</label>
          <select class="form-select" name="client_id" required>
            {% for c in clients %}
              <option value="{{ c.id }}" {% if current_client and c.id==current_client.id %}selected{% endif %}>{{ c.name }}</option>
            {% endfor %}
          </select>
        </div>
        <div class="col-md-8">
          <label class="form-label">Título</label>
          <input class="form-control" name="title" required />
        </div>
        <div class="col-md-4">
          <label class="form-label">Status</label>
          <select class="form-select" name="status">
            <option value="rascunho">rascunho</option>
            <option value="aguardando_cliente">aguardando_cliente</option>
            <option value="concluido">concluido</option>
          </select>
        </div>
        <div class="col-12">
          <label class="form-label">Conteúdo</label>
          <textarea class="form-control" name="content" rows="6" required></textarea>
        </div>
        <div class="col-12">
          <label class="form-label">Anexo (opcional)</label>
          <input class="form-control" type="file" name="file" />
        </div>
      </div>
      <div class="mt-4 d-flex gap-2">
        <button class="btn btn-primary">Salvar</button>
        <a class="btn btn-outline-secondary" href="/documentos">Cancelar</a>
      </div>
    </form>
  {% endif %}
</div>
{% endblock %}
""",
    "docs_detail.html": r"""
{% extends "base.html" %}
{% block content %}
<div class="card p-4">
  <div class="d-flex justify-content-between">
    <div>
      <h4 class="mb-1">{{ doc.title }}</h4>
      <div class="muted">
        Status: <b>{{ doc.status }}</b>
        {% if role in ["admin","equipe"] %} • Cliente: <b>{{ client.name }}</b>{% endif %}
      </div>
    </div>
    <a class="btn btn-outline-secondary" href="/documentos">Voltar</a>
  </div>

  <hr class="my-3"/>
  <pre>{{ doc.content }}</pre>

  <hr class="my-3"/>
  <h6>Anexos</h6>
  {% if attachments %}
    <ul>
      {% for a in attachments %}
        <li><a href="/download/{{ a.id }}">{{ a.original_filename }}</a></li>
      {% endfor %}
    </ul>
  {% else %}
    <div class="muted">Sem anexos.</div>
  {% endif %}

  <hr class="my-3"/>
  <h6>Mensagens</h6>
  {% if messages %}
    <div class="list-group mb-3">
      {% for m in messages %}
        <div class="list-group-item">
          <div class="d-flex justify-content-between">
            <div class="fw-semibold">{{ m.author_name }}</div>
            <div class="muted small">{{ m.created_at }}</div>
          </div>
          <pre class="mt-2">{{ m.message }}</pre>
        </div>
      {% endfor %}
    </div>
  {% else %}
    <div class="muted">Sem mensagens.</div>
  {% endif %}

  {% if role in ["admin","equipe"] %}
    <hr class="my-3"/>
    <form method="post" action="/documentos/{{ doc.id }}/status" class="row g-2 align-items-end">
      <div class="col-md-6">
        <label class="form-label">Alterar status</label>
        <select class="form-select" name="status">
          <option value="rascunho" {% if doc.status=="rascunho" %}selected{% endif %}>rascunho</option>
          <option value="aguardando_cliente" {% if doc.status=="aguardando_cliente" %}selected{% endif %}>aguardando_cliente</option>
          <option value="cliente_enviou" {% if doc.status=="cliente_enviou" %}selected{% endif %}>cliente_enviou</option>
          <option value="concluido" {% if doc.status=="concluido" %}selected{% endif %}>concluido</option>
        </select>
      </div>
      <div class="col-md-3">
        <button class="btn btn-outline-primary w-100">Atualizar</button>
      </div>
    </form>

    <form method="post" action="/documentos/{{ doc.id }}/anexar" enctype="multipart/form-data" class="mt-3">
      <div class="mb-2">
        <label class="form-label">Mensagem (opcional)</label>
        <textarea class="form-control" name="message" rows="2"></textarea>
      </div>
      <div class="mb-2">
        <label class="form-label">Anexar arquivo</label>
        <input class="form-control" type="file" name="file" required />
      </div>
      <button class="btn btn-primary">Enviar</button>
    </form>
  {% else %}
    <hr class="my-3"/>
    {% if doc.status == "aguardando_cliente" %}
      <div class="alert alert-warning">O escritório está aguardando seu anexo/resposta.</div>
    {% endif %}
    <form method="post" action="/documentos/{{ doc.id }}/cliente-upload" enctype="multipart/form-data">
      <div class="mb-2">
        <label class="form-label">Mensagem (opcional)</label>
        <textarea class="form-control" name="message" rows="3"></textarea>
      </div>
      <div class="mb-2">
        <label class="form-label">Anexo</label>
        <input class="form-control" type="file" name="file" required />
      </div>
      <button class="btn btn-primary">Enviar</button>
    </form>
  {% endif %}
</div>
{% endblock %}
""",
    # ---------------- Propostas ----------------
    "props_list.html": r"""
{% extends "base.html" %}
{% block content %}
<div class="card p-4">
  <div class="d-flex justify-content-between align-items-center">
    <div>
      <h4 class="mb-0">Propostas</h4>
      <div class="muted">Propostas do escritório e solicitações do cliente.</div>
    </div>

    {% if role in ["admin","equipe"] %}
      <a class="btn btn-primary" href="/propostas/nova">Nova Proposta</a>
    {% else %}
      <a class="btn btn-primary" href="/propostas/solicitacao">Nova Solicitação</a>
    {% endif %}
  </div>

  <hr class="my-3"/>
  {% if items %}
    <div class="list-group">
      {% for p in items %}
        <a class="list-group-item list-group-item-action" href="/propostas/{{ p.id }}">
          <div class="d-flex justify-content-between">
            <div class="fw-semibold">{{ p.title }}</div>
            <span class="badge text-bg-light border">{{ p.kind }} • {{ p.status }}</span>
          </div>
          <div class="muted small">
            {% if role in ["admin","equipe"] %}Cliente: {{ p.client_name }} • {% endif %}
            {% if p.kind == "proposta" %}Valor: R$ {{ "%.2f"|format(p.value_brl) }} • {% endif %}
            {{ p.created_at }}
          </div>
        </a>
      {% endfor %}
    </div>
  {% else %}
    <div class="muted">Sem itens.</div>
  {% endif %}
</div>
{% endblock %}
""",
    "props_new_staff.html": r"""
{% extends "base.html" %}
{% block content %}
<div class="card p-4">
  <h4>Nova Proposta (Escritório)</h4>
  <div class="muted">Crie uma proposta e direcione para um cliente.</div>

  {% if not clients %}
    <div class="alert alert-warning mt-3">Nenhum cliente cadastrado. Vá em “Membros”.</div>
    <a class="btn btn-outline-secondary" href="/propostas">Voltar</a>
  {% else %}
    <form method="post" action="/propostas/nova" enctype="multipart/form-data" class="mt-3">
      <div class="row g-3">
        <div class="col-12">
          <label class="form-label">Cliente</label>
          <select class="form-select" name="client_id" required>
            {% for c in clients %}
              <option value="{{ c.id }}" {% if current_client and c.id==current_client.id %}selected{% endif %}>{{ c.name }}</option>
            {% endfor %}
          </select>
        </div>
        <div class="col-md-8">
          <label class="form-label">Título</label>
          <input class="form-control" name="title" required />
        </div>
        <div class="col-md-4">
          <label class="form-label">Status</label>
          <select class="form-select" name="status">
            <option value="rascunho">rascunho</option>
            <option value="enviada">enviada</option>
          </select>
        </div>
        <div class="col-md-6">
          <label class="form-label">Valor (R$)</label>
          <input class="form-control" name="value_brl" type="number" step="0.01" min="0" value="0" required />
        </div>
        <div class="col-12">
          <label class="form-label">Descrição/Notas</label>
          <textarea class="form-control" name="description" rows="5"></textarea>
        </div>
        <div class="col-12">
          <label class="form-label">Anexo (opcional)</label>
          <input class="form-control" type="file" name="file" />
        </div>
      </div>
      <div class="mt-4 d-flex gap-2">
        <button class="btn btn-primary">Salvar</button>
        <a class="btn btn-outline-secondary" href="/propostas">Cancelar</a>
      </div>
    </form>
  {% endif %}
</div>
{% endblock %}
""",
    "props_new_client.html": r"""
{% extends "base.html" %}
{% block content %}
<div class="card p-4">
  <h4>Nova Solicitação (Cliente)</h4>
  <div class="muted">Peça um serviço/produto ao escritório. Você pode anexar arquivos.</div>

  <form method="post" action="/propostas/solicitacao" enctype="multipart/form-data" class="mt-3">
    <div class="row g-3">
      <div class="col-12">
        <label class="form-label">Título</label>
        <input class="form-control" name="title" required placeholder="Ex: Preciso de consultoria tributária..." />
      </div>
      <div class="col-12">
        <label class="form-label">Detalhes</label>
        <textarea class="form-control" name="description" rows="6" required></textarea>
      </div>
      <div class="col-12">
        <label class="form-label">Anexo (opcional)</label>
        <input class="form-control" type="file" name="file" />
      </div>
    </div>
    <div class="mt-4 d-flex gap-2">
      <button class="btn btn-primary">Enviar solicitação</button>
      <a class="btn btn-outline-secondary" href="/propostas">Cancelar</a>
    </div>
  </form>
</div>
{% endblock %}
""",
    "props_detail.html": r"""
{% extends "base.html" %}
{% block content %}
<div class="card p-4">
  <div class="d-flex justify-content-between">
    <div>
      <h4 class="mb-1">{{ prop.title }}</h4>
      <div class="muted">
        Tipo: <b>{{ prop.kind }}</b> • Status: <b>{{ prop.status }}</b>
        {% if prop.kind == "proposta" %} • Valor: <b>R$ {{ "%.2f"|format(prop.value_brl) }}</b>{% endif %}
        {% if role in ["admin","equipe"] %} • Cliente: <b>{{ client.name }}</b>{% endif %}
      </div>
    </div>
    <a class="btn btn-outline-secondary" href="/propostas">Voltar</a>
  </div>

  <hr class="my-3"/>
  <pre>{{ prop.description }}</pre>

  <hr class="my-3"/>
  <h6>Anexos</h6>
  {% if attachments %}
    <ul>
      {% for a in attachments %}
        <li><a href="/download/{{ a.id }}">{{ a.original_filename }}</a></li>
      {% endfor %}
    </ul>
  {% else %}
    <div class="muted">Sem anexos.</div>
  {% endif %}

  <hr class="my-3"/>
  <h6>Mensagens</h6>
  {% if messages %}
    <div class="list-group mb-3">
      {% for m in messages %}
        <div class="list-group-item">
          <div class="d-flex justify-content-between">
            <div class="fw-semibold">{{ m.author_name }}</div>
            <div class="muted small">{{ m.created_at }}</div>
          </div>
          <pre class="mt-2">{{ m.message }}</pre>
        </div>
      {% endfor %}
    </div>
  {% else %}
    <div class="muted">Sem mensagens.</div>
  {% endif %}

  {% if role in ["admin","equipe"] %}
    <hr class="my-3"/>
    <h6>Ações do escritório</h6>

    <form method="post" action="/propostas/{{ prop.id }}/atualizar" class="row g-2 align-items-end">
      <div class="col-md-4">
        <label class="form-label">Tipo</label>
        <select class="form-select" name="kind">
          <option value="proposta" {% if prop.kind=="proposta" %}selected{% endif %}>proposta</option>
          <option value="solicitacao" {% if prop.kind=="solicitacao" %}selected{% endif %}>solicitacao</option>
        </select>
      </div>
      <div class="col-md-4">
        <label class="form-label">Status</label>
        <select class="form-select" name="status">
          {% for s in allowed_statuses %}
            <option value="{{ s }}" {% if prop.status==s %}selected{% endif %}>{{ s }}</option>
          {% endfor %}
        </select>
      </div>
      <div class="col-md-4">
        <label class="form-label">Valor (R$)</label>
        <input class="form-control" name="value_brl" type="number" step="0.01" min="0" value="{{ prop.value_brl }}" />
      </div>
      <div class="col-12">
        <label class="form-label">Mensagem (opcional)</label>
        <textarea class="form-control" name="message" rows="2"></textarea>
      </div>
      <div class="col-md-3">
        <button class="btn btn-outline-primary w-100">Salvar</button>
      </div>
    </form>

    <form method="post" action="/propostas/{{ prop.id }}/anexar" enctype="multipart/form-data" class="mt-3">
      <div class="mb-2">
        <label class="form-label">Anexar arquivo</label>
        <input class="form-control" type="file" name="file" required />
      </div>
      <button class="btn btn-primary">Enviar anexo</button>
    </form>

  {% else %}
    <hr class="my-3"/>
    <h6>Enviar mais informações</h6>
    <form method="post" action="/propostas/{{ prop.id }}/cliente-upload" enctype="multipart/form-data">
      <div class="mb-2">
        <label class="form-label">Mensagem (opcional)</label>
        <textarea class="form-control" name="message" rows="3"></textarea>
      </div>
      <div class="mb-2">
        <label class="form-label">Anexo (opcional)</label>
        <input class="form-control" type="file" name="file" />
      </div>
      <button class="btn btn-primary">Enviar</button>
    </form>
  {% endif %}
</div>
{% endblock %}
""",
    # ---------------- Financeiro ----------------
    "fin_list.html": r"""
{% extends "base.html" %}
{% block content %}
<div class="card p-4">
  <div class="d-flex justify-content-between align-items-center">
    <div>
      <h4 class="mb-0">Financeiro</h4>
      <div class="muted">Notas/Boletos de honorários (download pelo cliente).</div>
    </div>
    {% if role in ["admin","equipe"] %}
      <a class="btn btn-primary" href="/financeiro/novo">Nova cobrança</a>
    {% endif %}
  </div>

  <hr class="my-3"/>
  {% if items %}
    <div class="list-group">
      {% for it in items %}
        <a class="list-group-item list-group-item-action" href="/financeiro/{{ it.id }}">
          <div class="d-flex justify-content-between">
            <div class="fw-semibold">{{ it.title }}</div>
            <span class="badge text-bg-light border">{{ it.status }}</span>
          </div>
          <div class="muted small">
            {% if role in ["admin","equipe"] %}Cliente: {{ it.client_name }} • {% endif %}
            Valor: R$ {{ "%.2f"|format(it.amount_brl) }} •
            {% if it.due_date %}Venc: {{ it.due_date }} • {% endif %}
            {{ it.created_at }}
          </div>
        </a>
      {% endfor %}
    </div>
  {% else %}
    <div class="muted">Sem cobranças.</div>
  {% endif %}
</div>
{% endblock %}
""",
    "fin_new.html": r"""
{% extends "base.html" %}
{% block content %}
<div class="card p-4">
  <h4>Nova cobrança (nota/boleto)</h4>
  <div class="muted">Só admin/equipe cria e anexa PDF/arquivo para o cliente baixar.</div>

  {% if not clients %}
    <div class="alert alert-warning mt-3">Nenhum cliente cadastrado. Vá em “Membros”.</div>
    <a class="btn btn-outline-secondary" href="/financeiro">Voltar</a>
  {% else %}
    <form method="post" action="/financeiro/novo" enctype="multipart/form-data" class="mt-3">
      <div class="row g-3">
        <div class="col-12">
          <label class="form-label">Cliente</label>
          <select class="form-select" name="client_id" required>
            {% for c in clients %}
              <option value="{{ c.id }}" {% if current_client and c.id==current_client.id %}selected{% endif %}>{{ c.name }}</option>
            {% endfor %}
          </select>
        </div>
        <div class="col-md-8">
          <label class="form-label">Título</label>
          <input class="form-control" name="title" required placeholder="Honorários - Março/2026" />
        </div>
        <div class="col-md-4">
          <label class="form-label">Status</label>
          <select class="form-select" name="status">
            <option value="emitido">emitido</option>
            <option value="pago">pago</option>
            <option value="atrasado">atrasado</option>
            <option value="cancelado">cancelado</option>
          </select>
        </div>
        <div class="col-md-6">
          <label class="form-label">Valor (R$)</label>
          <input class="form-control" name="amount_brl" type="number" step="0.01" min="0" value="0" required />
        </div>
        <div class="col-md-6">
          <label class="form-label">Vencimento (AAAA-MM-DD)</label>
          <input class="form-control mono" name="due_date" placeholder="2026-03-20" />
        </div>
        <div class="col-12">
          <label class="form-label">Observações</label>
          <textarea class="form-control" name="notes" rows="3"></textarea>
        </div>
        <div class="col-12">
          <label class="form-label">Anexo (PDF/arquivo)</label>
          <input class="form-control" type="file" name="file" required />
        </div>
      </div>
      <div class="mt-4 d-flex gap-2">
        <button class="btn btn-primary">Salvar</button>
        <a class="btn btn-outline-secondary" href="/financeiro">Cancelar</a>
      </div>
    </form>
  {% endif %}
</div>
{% endblock %}
""",
    "fin_detail.html": r"""
{% extends "base.html" %}
{% block content %}
<div class="card p-4">
  <div class="d-flex justify-content-between">
    <div>
      <h4 class="mb-1">{{ inv.title }}</h4>
      <div class="muted">
        Status: <b>{{ inv.status }}</b> • Valor: <b>R$ {{ "%.2f"|format(inv.amount_brl) }}</b>
        {% if inv.due_date %} • Venc: <b>{{ inv.due_date }}</b>{% endif %}
        {% if role in ["admin","equipe"] %} • Cliente: <b>{{ client.name }}</b>{% endif %}
      </div>
    </div>
    <a class="btn btn-outline-secondary" href="/financeiro">Voltar</a>
  </div>

  <hr class="my-3"/>
  <pre>{{ inv.notes }}</pre>

  <hr class="my-3"/>
  <h6>Anexos (download)</h6>
  {% if attachments %}
    <ul>
      {% for a in attachments %}
        <li><a href="/download/{{ a.id }}">{{ a.original_filename }}</a></li>
      {% endfor %}
    </ul>
  {% else %}
    <div class="muted">Sem anexos.</div>
  {% endif %}

  {% if role in ["admin","equipe"] %}
    <hr class="my-3"/>
    <form method="post" action="/financeiro/{{ inv.id }}/anexar" enctype="multipart/form-data">
      <div class="mb-2">
        <label class="form-label">Anexar novo arquivo</label>
        <input class="form-control" type="file" name="file" required />
      </div>
      <button class="btn btn-primary">Enviar</button>
    </form>
  {% endif %}
</div>
{% endblock %}
""",
}
TEMPLATES.update({
"consult_list.html": r"""
{% extends "base.html" %}
{% block content %}
<div class="card p-4">
  <div class="d-flex justify-content-between align-items-center">
    <div>
      <h4 class="mb-0">Consultoria</h4>
      <div class="muted">Projetos → Etapas → Sub-etapas → % concluído</div>
    </div>
    {% if role in ["admin","equipe"] %}
      <a class="btn btn-primary" href="/consultoria/novo">Novo projeto</a>
    {% endif %}
  </div>

  <hr class="my-3"/>

  {% if projects %}
    <div class="list-group">
      {% for p in projects %}
        <a class="list-group-item list-group-item-action" href="/consultoria/{{ p.id }}">
          <div class="d-flex justify-content-between">
            <div class="fw-semibold">{{ p.name }}</div>
            <span class="badge text-bg-light border">{{ p.status }}</span>
          </div>

          <div class="muted small mt-1">
            {% if role in ["admin","equipe"] %}Cliente: {{ p.client_name }} • {% endif %}
            {% if p.due_date %}Prazo: {{ p.due_date }} • {% endif %}
            Progresso: {{ p.progress_pct }}%
          </div>

          <div class="progress mt-2" style="height: 8px;">
            <div class="progress-bar" role="progressbar" style="width: {{ p.progress_pct }}%;"></div>
          </div>
        </a>
      {% endfor %}
    </div>
  {% else %}
    <div class="muted">Sem projetos ainda.</div>
  {% endif %}
</div>
{% endblock %}
""",

"consult_new.html": r"""
{% extends "base.html" %}
{% block content %}
<div class="card p-4">
  <h4>Novo Projeto de Consultoria</h4>
  <div class="muted">Direcione para um cliente e defina prazos.</div>

  {% if not clients %}
    <div class="alert alert-warning mt-3">Nenhum cliente cadastrado. Vá em “Membros” e crie um cliente.</div>
    <a class="btn btn-outline-secondary" href="/consultoria">Voltar</a>
  {% else %}
    <form method="post" action="/consultoria/novo" class="mt-3">
      <div class="row g-3">
        <div class="col-12">
          <label class="form-label">Cliente</label>
          <select class="form-select" name="client_id" required>
            {% for c in clients %}
              <option value="{{ c.id }}" {% if current_client and c.id==current_client.id %}selected{% endif %}>{{ c.name }}</option>
            {% endfor %}
          </select>
        </div>

        <div class="col-md-8">
          <label class="form-label">Nome do projeto</label>
          <input class="form-control" name="name" required placeholder="Ex: Reestruturação Financeira 2026" />
        </div>

        <div class="col-md-4">
          <label class="form-label">Status</label>
          <select class="form-select" name="status">
            <option value="ativo">ativo</option>
            <option value="pausado">pausado</option>
            <option value="concluido">concluido</option>
          </select>
        </div>

        <div class="col-md-6">
          <label class="form-label">Início (AAAA-MM-DD)</label>
          <input class="form-control mono" name="start_date" placeholder="2026-03-10" />
        </div>

        <div class="col-md-6">
          <label class="form-label">Prazo final (AAAA-MM-DD)</label>
          <input class="form-control mono" name="due_date" placeholder="2026-06-30" />
        </div>

        <div class="col-12">
          <label class="form-label">Descrição</label>
          <textarea class="form-control" name="description" rows="4"></textarea>
        </div>
      </div>

      <div class="mt-4 d-flex gap-2">
        <button class="btn btn-primary">Criar</button>
        <a class="btn btn-outline-secondary" href="/consultoria">Cancelar</a>
      </div>
    </form>
  {% endif %}
</div>
{% endblock %}
""",

"consult_detail.html": r"""
{% extends "base.html" %}
{% block content %}
<div class="card p-4">
  <div class="d-flex justify-content-between align-items-start">
    <div>
      <h4 class="mb-1">{{ project.name }}</h4>
      <div class="muted">
        Status: <b>{{ project.status }}</b>
        {% if project.due_date %} • Prazo final: <b>{{ project.due_date }}</b>{% endif %}
        {% if role in ["admin","equipe"] %} • Cliente: <b>{{ client.name }}</b>{% endif %}
      </div>

      <div class="mt-2">
        <div class="muted small">Progresso: <b>{{ progress_pct }}%</b></div>
        <div class="progress" style="height: 10px;">
          <div class="progress-bar" role="progressbar" style="width: {{ progress_pct }}%;"></div>
        </div>
      </div>
    </div>

    <a class="btn btn-outline-secondary" href="/consultoria">Voltar</a>
  </div>

  {% if project.description %}
    <hr class="my-3"/>
    <pre>{{ project.description }}</pre>
  {% endif %}

  <hr class="my-3"/>
  <h5 class="mb-3">Etapas</h5>

  {% if stages %}
    <div class="accordion" id="stagesAcc">
      {% for s in stages %}
        <div class="accordion-item">
          <h2 class="accordion-header" id="h{{ s.id }}">
            <button class="accordion-button collapsed" type="button" data-bs-toggle="collapse" data-bs-target="#c{{ s.id }}">
              {{ s.order }}. {{ s.name }}
              {% if s.due_date %}<span class="ms-2 muted small">• prazo: {{ s.due_date }}</span>{% endif %}
            </button>
          </h2>
          <div id="c{{ s.id }}" class="accordion-collapse collapse" data-bs-parent="#stagesAcc">
            <div class="accordion-body">

              {% if s.steps %}
                <div class="list-group mb-3">
                  {% for st in s.steps %}
                    <div class="list-group-item">
                      <div class="d-flex justify-content-between align-items-start">
                        <div>
                          <div class="fw-semibold">
                            {% if st.done %}✅{% else %}⬜{% endif %}
                            {{ st.title }}
                            {% if st.client_action %}<span class="badge text-bg-light border ms-2">cliente</span>{% endif %}
                          </div>
                          {% if st.description %}<div class="muted small mt-1">{{ st.description }}</div>{% endif %}
                          <div class="muted small">
                            {% if st.due_date %}Prazo: {{ st.due_date }} • {% endif %}
                            Peso: {{ st.weight }}
                          </div>
                        </div>

                        <div class="d-flex gap-2">
                          {% if role in ["admin","equipe"] or (role=="cliente" and st.client_action) %}
                            <form method="post" action="/consultoria/steps/{{ st.id }}/toggle">
                              <button class="btn btn-outline-primary btn-sm">{% if st.done %}Desmarcar{% else %}Concluir{% endif %}</button>
                            </form>
                          {% endif %}
                        </div>
                      </div>
                    </div>
                  {% endfor %}
                </div>
              {% else %}
                <div class="muted mb-3">Sem sub-etapas.</div>
              {% endif %}

              {% if role in ["admin","equipe"] %}
                <form method="post" action="/consultoria/stages/{{ s.id }}/steps" class="card p-3">
                  <div class="fw-semibold mb-2">Adicionar sub-etapa</div>
                  <div class="row g-2">
                    <div class="col-md-6">
                      <input class="form-control" name="title" required placeholder="Título" />
                    </div>
                    <div class="col-md-6">
                      <input class="form-control mono" name="due_date" placeholder="Prazo AAAA-MM-DD" />
                    </div>
                    <div class="col-12">
                      <input class="form-control" name="description" placeholder="Descrição (opcional)" />
                    </div>
                    <div class="col-md-4">
                      <input class="form-control" name="weight" type="number" step="0.1" min="0.1" value="1.0" />
                      <div class="form-text">Peso para cálculo do %.</div>
                    </div>
                    <div class="col-md-4">
                      <div class="form-check mt-2">
                        <input class="form-check-input" type="checkbox" name="client_action" value="1" id="ca{{ s.id }}">
                        <label class="form-check-label" for="ca{{ s.id }}">Ação do cliente</label>
                      </div>
                    </div>
                    <div class="col-md-4">
                      <button class="btn btn-primary w-100">Adicionar</button>
                    </div>
                  </div>
                </form>
              {% endif %}

            </div>
          </div>
        </div>
      {% endfor %}
    </div>
  {% else %}
    <div class="muted">Sem etapas ainda.</div>
  {% endif %}

  {% if role in ["admin","equipe"] %}
    <hr class="my-3"/>
    <form method="post" action="/consultoria/{{ project.id }}/stages" class="card p-3">
      <div class="fw-semibold mb-2">Adicionar etapa</div>
      <div class="row g-2">
        <div class="col-md-8">
          <input class="form-control" name="name" required placeholder="Nome da etapa" />
        </div>
        <div class="col-md-4">
          <input class="form-control mono" name="due_date" placeholder="Prazo AAAA-MM-DD" />
        </div>
        <div class="col-12">
          <button class="btn btn-primary">Adicionar etapa</button>
        </div>
      </div>
    </form>
  {% endif %}
</div>

<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/js/bootstrap.bundle.min.js"></script>
{% endblock %}
""",
})
templates_env = Environment(loader=DictLoader(TEMPLATES), autoescape=True)


def render(
    template_name: str,
    *,
    request: Request,
    context: Optional[dict[str, Any]] = None,
    status_code: int = 200,
) -> HTMLResponse:
    ctx = context or {}
    ctx.setdefault("title", "App Escritório")
    ctx.setdefault("flash", request.session.pop("flash", None) if hasattr(request, "session") else None)
    return HTMLResponse(templates_env.get_template(template_name).render(**ctx), status_code=status_code)


# ----------------------------
# App
# ----------------------------

app = FastAPI()
https_only = os.getenv("SESSION_HTTPS_ONLY", "0") == "1"
app.add_middleware(SessionMiddleware, secret_key=APP_SECRET_KEY, https_only=https_only, same_site="lax")

STATIC_DIR = Path(__file__).with_name("static").resolve()
STATIC_DIR.mkdir(parents=True, exist_ok=True)

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
@app.on_event("startup")
def _startup() -> None:
    init_db()
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


# ----------------------------
# Auth routes
# ----------------------------


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, session: Session = Depends(get_session)) -> HTMLResponse:
    if get_current_user(request, session):
        return RedirectResponse("/", status_code=303)
    return render("login.html", request=request, context={"current_user": None})

@app.get("/consultoria", response_class=HTMLResponse)
@require_login
async def consultoria_list(request: Request, session: Session = Depends(get_session)) -> HTMLResponse:
    ctx = get_tenant_context(request, session)
    if not ctx:
        request.session.clear()
        return RedirectResponse("/login", status_code=303)

    active_client_id = get_active_client_id(request, session, ctx)
    current_client = get_client_or_none(session, ctx.company.id, active_client_id)

    q = select(ConsultingProject).where(ConsultingProject.company_id == ctx.company.id).order_by(ConsultingProject.created_at.desc())

    if ctx.membership.role == "cliente":
        q = q.where(ConsultingProject.client_id == (ctx.membership.client_id or -1))
    else:
        if current_client:
            q = q.where(ConsultingProject.client_id == current_client.id)

    projects = session.exec(q).all()

    out = []
    for p in projects:
        c = session.get(Client, p.client_id)
        progress = compute_project_progress(session, p.id)
        out.append(
            {
                "id": p.id,
                "name": p.name,
                "status": p.status,
                "due_date": p.due_date,
                "client_name": c.name if c else "—",
                "progress_pct": int(round(progress * 100)),
            }
        )

    return render(
        "consult_list.html",
        request=request,
        context={
            "current_user": ctx.user,
            "current_company": ctx.company,
            "role": ctx.membership.role,
            "current_client": current_client,
            "projects": out,
        },
    )


@app.get("/consultoria/novo", response_class=HTMLResponse)
@require_role({"admin", "equipe"})
async def consultoria_new_page(request: Request, session: Session = Depends(get_session)) -> HTMLResponse:
    ctx = get_tenant_context(request, session)
    assert ctx is not None

    clients = session.exec(select(Client).where(Client.company_id == ctx.company.id).order_by(Client.created_at)).all()
    active_client_id = get_active_client_id(request, session, ctx)
    current_client = get_client_or_none(session, ctx.company.id, active_client_id)

    return render(
        "consult_new.html",
        request=request,
        context={
            "current_user": ctx.user,
            "current_company": ctx.company,
            "role": ctx.membership.role,
            "current_client": current_client,
            "clients": clients,
        },
    )


@app.post("/consultoria/novo")
@require_role({"admin", "equipe"})
async def consultoria_new_action(
    request: Request,
    session: Session = Depends(get_session),
    client_id: int = Form(...),
    name: str = Form(...),
    description: str = Form(""),
    status: str = Form("ativo"),
    start_date: str = Form(""),
    due_date: str = Form(""),
) -> Response:
    ctx = get_tenant_context(request, session)
    assert ctx is not None

    client = get_client_or_none(session, ctx.company.id, int(client_id))
    if not client:
        set_flash(request, "Cliente inválido.")
        return RedirectResponse("/consultoria/novo", status_code=303)

    status = status.strip().lower()
    if status not in CONSULT_PROJECT_STATUS:
        status = "ativo"

    proj = ConsultingProject(
        company_id=ctx.company.id,
        client_id=client.id,
        created_by_user_id=ctx.user.id,
        name=name.strip(),
        description=description.strip(),
        status=status,
        start_date=start_date.strip(),
        due_date=due_date.strip(),
        updated_at=utcnow(),
    )
    session.add(proj)
    session.commit()
    session.refresh(proj)

    set_flash(request, "Projeto criado.")
    return RedirectResponse(f"/consultoria/{proj.id}", status_code=303)


@app.get("/consultoria/{project_id}", response_class=HTMLResponse)
@require_login
async def consultoria_detail(request: Request, session: Session = Depends(get_session), project_id: int = 0) -> HTMLResponse:
    ctx = get_tenant_context(request, session)
    if not ctx:
        request.session.clear()
        return RedirectResponse("/login", status_code=303)

    project = session.get(ConsultingProject, int(project_id))
    if not project or project.company_id != ctx.company.id:
        return render("error.html", request=request, context={"message": "Projeto não encontrado."}, status_code=404)

    if not ensure_can_access_client(ctx, project.client_id):
        return render("error.html", request=request, context={"message": "Sem permissão."}, status_code=403)

    client = session.get(Client, project.client_id)
    stages = session.exec(
        select(ConsultingStage).where(ConsultingStage.project_id == project.id).order_by(ConsultingStage.order.asc())
    ).all()

    stage_ids = [s.id for s in stages]
    steps = []
    if stage_ids:
        steps = session.exec(
            select(ConsultingStep).where(ConsultingStep.stage_id.in_(stage_ids)).order_by(ConsultingStep.id.asc())
        ).all()

    steps_by_stage: dict[int, list[ConsultingStep]] = {}
    for st in steps:
        steps_by_stage.setdefault(st.stage_id, []).append(st)

    stage_view = []
    for s in stages:
        stage_view.append({"id": s.id, "name": s.name, "order": s.order, "due_date": s.due_date, "steps": steps_by_stage.get(s.id, [])})

    progress_pct = int(round(compute_project_progress(session, project.id) * 100))

    active_client_id = get_active_client_id(request, session, ctx)
    current_client = get_client_or_none(session, ctx.company.id, active_client_id)

    return render(
        "consult_detail.html",
        request=request,
        context={
            "current_user": ctx.user,
            "current_company": ctx.company,
            "role": ctx.membership.role,
            "current_client": current_client,
            "project": project,
            "client": client,
            "stages": stage_view,
            "progress_pct": progress_pct,
        },
    )


@app.post("/consultoria/{project_id}/stages")
@require_role({"admin", "equipe"})
async def consultoria_add_stage(
    request: Request,
    session: Session = Depends(get_session),
    project_id: int = 0,
    name: str = Form(...),
    due_date: str = Form(""),
) -> Response:
    ctx = get_tenant_context(request, session)
    assert ctx is not None

    project = session.get(ConsultingProject, int(project_id))
    if not project or project.company_id != ctx.company.id:
        set_flash(request, "Projeto não encontrado.")
        return RedirectResponse("/consultoria", status_code=303)

    stage = ConsultingStage(
        project_id=project.id,
        name=name.strip(),
        order=_next_stage_order(session, project.id),
        due_date=due_date.strip(),
    )
    session.add(stage)
    session.commit()

    set_flash(request, "Etapa adicionada.")
    return RedirectResponse(f"/consultoria/{project.id}", status_code=303)


@app.post("/consultoria/stages/{stage_id}/steps")
@require_role({"admin", "equipe"})
async def consultoria_add_step(
    request: Request,
    session: Session = Depends(get_session),
    stage_id: int = 0,
    title: str = Form(...),
    description: str = Form(""),
    due_date: str = Form(""),
    weight: float = Form(1.0),
    client_action: str = Form(""),
) -> Response:
    ctx = get_tenant_context(request, session)
    assert ctx is not None

    stage = session.get(ConsultingStage, int(stage_id))
    if not stage:
        set_flash(request, "Etapa não encontrada.")
        return RedirectResponse("/consultoria", status_code=303)

    project = session.exec(select(ConsultingProject).where(ConsultingProject.id == stage.project_id)).first()
    if not project or project.company_id != ctx.company.id:
        set_flash(request, "Projeto inválido.")
        return RedirectResponse("/consultoria", status_code=303)

    step = ConsultingStep(
        stage_id=stage.id,
        title=title.strip(),
        description=description.strip(),
        due_date=due_date.strip(),
        weight=max(0.1, float(weight)),
        client_action=(client_action == "1"),
        updated_at=utcnow(),
    )
    session.add(step)
    session.commit()

    set_flash(request, "Sub-etapa adicionada.")
    return RedirectResponse(f"/consultoria/{project.id}", status_code=303)


@app.post("/consultoria/steps/{step_id}/toggle")
@require_login
async def consultoria_toggle_step(
    request: Request,
    session: Session = Depends(get_session),
    step_id: int = 0,
) -> Response:
    ctx = get_tenant_context(request, session)
    if not ctx:
        request.session.clear()
        return RedirectResponse("/login", status_code=303)

    step = session.get(ConsultingStep, int(step_id))
    if not step:
        set_flash(request, "Sub-etapa não encontrada.")
        return RedirectResponse("/consultoria", status_code=303)

    stage = session.get(ConsultingStage, step.stage_id)
    if not stage:
        set_flash(request, "Etapa não encontrada.")
        return RedirectResponse("/consultoria", status_code=303)

    project = session.get(ConsultingProject, stage.project_id)
    if not project or project.company_id != ctx.company.id:
        set_flash(request, "Projeto inválido.")
        return RedirectResponse("/consultoria", status_code=303)

    if not ensure_can_access_client(ctx, project.client_id):
        set_flash(request, "Sem permissão.")
        return RedirectResponse("/consultoria", status_code=303)

    # Cliente só pode mexer se for item marcado como "client_action"
    if ctx.membership.role == "cliente" and not step.client_action:
        set_flash(request, "Você não pode concluir este item.")
        return RedirectResponse(f"/consultoria/{project.id}", status_code=303)

    step.done = not step.done
    step.done_at = utcnow() if step.done else None
    step.updated_at = utcnow()

    session.add(step)
    session.commit()

    return RedirectResponse(f"/consultoria/{project.id}", status_code=303)
@app.post("/login")
async def login_action(
    request: Request,
    session: Session = Depends(get_session),
    email: str = Form(...),
    password: str = Form(...),
) -> Response:
    user = session.exec(select(User).where(User.email == email.strip().lower())).first()
    if not user or not verify_password(password, user.password_hash):
        set_flash(request, "E-mail ou senha inválidos.")
        return RedirectResponse("/login", status_code=303)

    request.session["user_id"] = user.id
    request.session.pop("company_id", None)
    request.session.pop("selected_client_id", None)

    _ = ensure_company_in_session(request, session, user)
    set_flash(request, "Bem-vindo(a)!")
    return RedirectResponse("/", status_code=303)


@app.get("/signup", response_class=HTMLResponse)
async def signup_page(request: Request, session: Session = Depends(get_session)) -> HTMLResponse:
    if get_current_user(request, session):
        return RedirectResponse("/", status_code=303)
    return render("signup.html", request=request, context={"current_user": None})


@app.post("/signup")
async def signup_action(
    request: Request,
    session: Session = Depends(get_session),
    name: str = Form(...),
    company_name: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    goal: str = Form(...),
    revenue: str = Form(...),
    employees: int = Form(...),
    pain: str = Form(...),
    notes: str = Form(""),
) -> Response:
    if len(password) < 8:
        set_flash(request, "Senha muito curta (mínimo 8).")
        return RedirectResponse("/signup", status_code=303)

    user = User(name=name.strip(), email=email.strip().lower(), password_hash=hash_password(password))
    session.add(user)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        set_flash(request, "Este e-mail já está cadastrado.")
        return RedirectResponse("/signup", status_code=303)
    session.refresh(user)

    company = Company(name=company_name.strip())
    session.add(company)
    session.commit()
    session.refresh(company)

    session.add(Membership(user_id=user.id, company_id=company.id, role="admin"))
    session.commit()

    diagnostic = {
        "goal": goal,
        "revenue": revenue,
        "employees": employees,
        "pain": pain.strip(),
        "notes": notes.strip(),
        "submitted_at": utcnow().isoformat(),
    }
    session.add(
        OnboardingDiagnostic(
            user_id=user.id,
            company_id=company.id,
            answers_json=json.dumps(diagnostic, ensure_ascii=False),
        )
    )
    session.commit()

    await sync_to_notion_negocios(user=user, company=company, diagnostic=diagnostic)

    request.session["user_id"] = user.id
    request.session["company_id"] = company.id
    request.session.pop("selected_client_id", None)

    set_flash(request, "Escritório criado. Você é ADMIN.")
    return RedirectResponse("/", status_code=303)


@app.get("/logout")
async def logout(request: Request) -> Response:
    request.session.clear()
    return RedirectResponse("/login", status_code=303)


# ----------------------------
# Dashboard
# ----------------------------


@app.get("/", response_class=HTMLResponse)
@require_login
async def dashboard(request: Request, session: Session = Depends(get_session)) -> HTMLResponse:
    ctx = get_tenant_context(request, session)
    if not ctx:
        request.session.clear()
        return RedirectResponse("/login", status_code=303)

    active_client_id = get_active_client_id(request, session, ctx)
    current_client = get_client_or_none(session, ctx.company.id, active_client_id)

    items = [
        {"title": "Pendências", "desc": "Checklist / pedidos de documentos.", "href": "/pendencias"},
        {"title": "Documentos", "desc": "Contratos e docs importantes.", "href": "/documentos"},
        {"title": "Propostas", "desc": "Propostas e solicitações.", "href": "/propostas"},
        {"title": "Financeiro", "desc": "Notas/boletos de honorários.", "href": "/financeiro"},
        {"title": "Empresa", "desc": "Dados completos do cliente.", "href": "/empresa"},
        {"title": "Perfil", "desc": "Indicadores do cliente.", "href": "/perfil"},
        {"title": "Consultoria", "desc": "Projetos, etapas e progresso.", "href": "/consultoria"},
    ]

    return render(
        "dashboard.html",
        request=request,
        context={
            "current_user": ctx.user,
            "current_company": ctx.company,
            "role": ctx.membership.role,
            "current_client": current_client,
            "items": items,
        },
    )


# ----------------------------
# Staff: trocar cliente
# ----------------------------


@app.get("/client/switch", response_class=HTMLResponse)
@require_role({"admin", "equipe"})
async def client_switch_page(request: Request, session: Session = Depends(get_session)) -> HTMLResponse:
    ctx = get_tenant_context(request, session)
    assert ctx is not None

    clients = session.exec(select(Client).where(Client.company_id == ctx.company.id).order_by(Client.created_at)).all()
    active_client_id = get_active_client_id(request, session, ctx)
    current_client = get_client_or_none(session, ctx.company.id, active_client_id)

    return render(
        "client_switch.html",
        request=request,
        context={
            "current_user": ctx.user,
            "current_company": ctx.company,
            "role": ctx.membership.role,
            "current_client": current_client,
            "clients": clients,
        },
    )


@app.post("/client/switch")
@require_role({"admin", "equipe"})
async def client_switch_action(
    request: Request,
    session: Session = Depends(get_session),
    client_id: int = Form(...),
) -> Response:
    ctx = get_tenant_context(request, session)
    assert ctx is not None

    client = get_client_or_none(session, ctx.company.id, int(client_id))
    if not client:
        set_flash(request, "Cliente inválido.")
        return RedirectResponse("/client/switch", status_code=303)

    request.session["selected_client_id"] = client.id
    set_flash(request, f"Cliente selecionado: {client.name}")
    return RedirectResponse("/", status_code=303)


# ----------------------------
# Admin: Members
# ----------------------------


@app.get("/admin/members", response_class=HTMLResponse)
@require_role({"admin", "equipe"})
async def members_page(request: Request, session: Session = Depends(get_session)) -> HTMLResponse:
    ctx = get_tenant_context(request, session)
    assert ctx is not None

    mems = session.exec(select(Membership).where(Membership.company_id == ctx.company.id)).all()
    rows = []
    for m in mems:
        u = session.get(User, m.user_id)
        if not u:
            continue
        client_name = None
        if m.client_id:
            c = session.get(Client, m.client_id)
            if c and c.company_id == ctx.company.id:
                client_name = c.name
        rows.append({"membership": m, "user": u, "client_name": client_name})

    rows.sort(key=lambda x: (x["membership"].role, x["user"].name.lower()))

    active_client_id = get_active_client_id(request, session, ctx)
    current_client = get_client_or_none(session, ctx.company.id, active_client_id)

    return render(
        "members.html",
        request=request,
        context={
            "current_user": ctx.user,
            "current_company": ctx.company,
            "role": ctx.membership.role,
            "current_client": current_client,
            "rows": rows,
        },
    )


@app.post("/admin/members")
@require_role({"admin", "equipe"})
async def members_add_action(
    request: Request,
    session: Session = Depends(get_session),
    name: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    role: str = Form(...),
    client_name: str = Form(""),
) -> Response:
    ctx = get_tenant_context(request, session)
    assert ctx is not None

    role = role.strip().lower()
    if role not in {"admin", "equipe", "cliente"}:
        set_flash(request, "Role inválida.")
        return RedirectResponse("/admin/members", status_code=303)

    if len(password) < 8:
        set_flash(request, "Senha muito curta (mínimo 8).")
        return RedirectResponse("/admin/members", status_code=303)

    email_norm = email.strip().lower()
    user = session.exec(select(User).where(User.email == email_norm)).first()

    if not user:
        user = User(name=name.strip(), email=email_norm, password_hash=hash_password(password))
        session.add(user)
        try:
            session.commit()
        except IntegrityError:
            session.rollback()
            set_flash(request, "Não foi possível criar usuário (e-mail pode já existir).")
            return RedirectResponse("/admin/members", status_code=303)
        session.refresh(user)

    membership = Membership(user_id=user.id, company_id=ctx.company.id, role=role)

    if role == "cliente":
        cn = client_name.strip()
        if cn:
            client = Client(company_id=ctx.company.id, name=cn)
            session.add(client)
            session.commit()
            session.refresh(client)
            membership.client_id = client.id
            request.session["selected_client_id"] = client.id

    session.add(membership)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        set_flash(request, "Este usuário já está vinculado a este escritório.")
        return RedirectResponse("/admin/members", status_code=303)

    set_flash(request, f"Membro adicionado: {email_norm} ({role}).")
    return RedirectResponse("/admin/members", status_code=303)


# ----------------------------
# Empresa / Perfil
# ----------------------------


@app.get("/empresa", response_class=HTMLResponse)
@require_login
async def empresa_page(request: Request, session: Session = Depends(get_session)) -> HTMLResponse:
    ctx = get_tenant_context(request, session)
    if not ctx:
        request.session.clear()
        return RedirectResponse("/login", status_code=303)

    current_client = get_client_or_none(session, ctx.company.id, get_active_client_id(request, session, ctx))
    return render(
        "empresa.html",
        request=request,
        context={
            "current_user": ctx.user,
            "current_company": ctx.company,
            "role": ctx.membership.role,
            "current_client": current_client,
        },
    )


@app.post("/empresa")
@require_login
async def empresa_save(
    request: Request,
    session: Session = Depends(get_session),
    name: str = Form(...),
    cnpj: str = Form(""),
    email: str = Form(""),
    phone: str = Form(""),
    finance_email: str = Form(""),
    address: str = Form(""),
    city: str = Form(""),
    state: str = Form(""),
    zip_code: str = Form(""),
    notes: str = Form(""),
) -> Response:
    ctx = get_tenant_context(request, session)
    if not ctx:
        request.session.clear()
        return RedirectResponse("/login", status_code=303)

    current_client = get_client_or_none(session, ctx.company.id, get_active_client_id(request, session, ctx))
    if not current_client:
        set_flash(request, "Nenhum cliente selecionado/vinculado.")
        return RedirectResponse("/empresa", status_code=303)

    if not ensure_can_access_client(ctx, current_client.id):
        set_flash(request, "Sem permissão.")
        return RedirectResponse("/empresa", status_code=303)

    current_client.name = name.strip()
    current_client.cnpj = cnpj.strip()
    current_client.email = email.strip()
    current_client.phone = phone.strip()
    current_client.finance_email = finance_email.strip()
    current_client.address = address.strip()
    current_client.city = city.strip()
    current_client.state = state.strip()
    current_client.zip_code = zip_code.strip()
    current_client.notes = notes.strip()
    current_client.updated_at = utcnow()

    session.add(current_client)
    session.commit()

    set_flash(request, "Dados da empresa atualizados.")
    return RedirectResponse("/empresa", status_code=303)


@app.get("/perfil", response_class=HTMLResponse)
@require_login
async def perfil_page(request: Request, session: Session = Depends(get_session)) -> HTMLResponse:
    ctx = get_tenant_context(request, session)
    if not ctx:
        request.session.clear()
        return RedirectResponse("/login", status_code=303)

    current_client = get_client_or_none(session, ctx.company.id, get_active_client_id(request, session, ctx))
    return render(
        "perfil.html",
        request=request,
        context={
            "current_user": ctx.user,
            "current_company": ctx.company,
            "role": ctx.membership.role,
            "current_client": current_client,
        },
    )


@app.post("/perfil")
@require_login
async def perfil_save(
    request: Request,
    session: Session = Depends(get_session),
    revenue_monthly_brl: float = Form(0.0),
    debt_total_brl: float = Form(0.0),
    cash_balance_brl: float = Form(0.0),
    employees_count: int = Form(0),
) -> Response:
    ctx = get_tenant_context(request, session)
    if not ctx:
        request.session.clear()
        return RedirectResponse("/login", status_code=303)

    current_client = get_client_or_none(session, ctx.company.id, get_active_client_id(request, session, ctx))
    if not current_client:
        set_flash(request, "Nenhum cliente selecionado/vinculado.")
        return RedirectResponse("/perfil", status_code=303)

    if not ensure_can_access_client(ctx, current_client.id):
        set_flash(request, "Sem permissão.")
        return RedirectResponse("/perfil", status_code=303)

    current_client.revenue_monthly_brl = max(0.0, float(revenue_monthly_brl))
    current_client.debt_total_brl = max(0.0, float(debt_total_brl))
    current_client.cash_balance_brl = max(0.0, float(cash_balance_brl))
    current_client.employees_count = max(0, int(employees_count))
    current_client.updated_at = utcnow()

    session.add(current_client)
    session.commit()

    set_flash(request, "Indicadores atualizados.")
    return RedirectResponse("/perfil", status_code=303)


# ----------------------------
# Pendências
# ----------------------------


@app.get("/pendencias", response_class=HTMLResponse)
@require_login
async def pending_list(request: Request, session: Session = Depends(get_session)) -> HTMLResponse:
    ctx = get_tenant_context(request, session)
    if not ctx:
        request.session.clear()
        return RedirectResponse("/login", status_code=303)

    current_client = get_client_or_none(session, ctx.company.id, get_active_client_id(request, session, ctx))

    q = select(PendingItem).where(PendingItem.company_id == ctx.company.id).order_by(PendingItem.created_at.desc())
    if ctx.membership.role == "cliente":
        items = session.exec(q.where(PendingItem.client_id == (ctx.membership.client_id or -1))).all()
    else:
        if current_client:
            q = q.where(PendingItem.client_id == current_client.id)
        items = session.exec(q).all()

    out = []
    for it in items:
        c = session.get(Client, it.client_id)
        out.append(
            {
                "id": it.id,
                "title": it.title,
                "status": it.status,
                "due_date": it.due_date,
                "created_at": it.created_at,
                "client_name": c.name if c else "—",
            }
        )

    return render(
        "pending_list.html",
        request=request,
        context={
            "current_user": ctx.user,
            "current_company": ctx.company,
            "role": ctx.membership.role,
            "current_client": current_client,
            "items": out,
        },
    )


@app.get("/pendencias/novo", response_class=HTMLResponse)
@require_role({"admin", "equipe"})
async def pending_new_page(request: Request, session: Session = Depends(get_session)) -> HTMLResponse:
    ctx = get_tenant_context(request, session)
    assert ctx is not None
    clients = session.exec(select(Client).where(Client.company_id == ctx.company.id).order_by(Client.created_at)).all()
    current_client = get_client_or_none(session, ctx.company.id, get_active_client_id(request, session, ctx))
    return render(
        "pending_new.html",
        request=request,
        context={
            "current_user": ctx.user,
            "current_company": ctx.company,
            "role": ctx.membership.role,
            "current_client": current_client,
            "clients": clients,
        },
    )


@app.post("/pendencias/novo")
@require_role({"admin", "equipe"})
async def pending_new_action(
    request: Request,
    session: Session = Depends(get_session),
    client_id: int = Form(...),
    title: str = Form(...),
    description: str = Form(""),
    status: str = Form("aberto"),
    due_date: str = Form(""),
    file: UploadFile | None = File(default=None),
) -> Response:
    ctx = get_tenant_context(request, session)
    assert ctx is not None

    client = get_client_or_none(session, ctx.company.id, int(client_id))
    if not client:
        set_flash(request, "Cliente inválido.")
        return RedirectResponse("/pendencias/novo", status_code=303)

    status = status.strip().lower()
    if status not in PENDING_STATUSES:
        status = "aberto"

    item = PendingItem(
        company_id=ctx.company.id,
        client_id=client.id,
        created_by_user_id=ctx.user.id,
        title=title.strip(),
        description=description.strip(),
        status=status,
        due_date=due_date.strip(),
        updated_at=utcnow(),
    )
    session.add(item)
    session.commit()
    session.refresh(item)

    if file and file.filename:
        try:
            stored, mime, size = await save_upload(file)
        except ValueError:
            set_flash(request, "Arquivo muito grande.")
            return RedirectResponse("/pendencias/novo", status_code=303)

        session.add(
            Attachment(
                company_id=ctx.company.id,
                client_id=client.id,
                uploaded_by_user_id=ctx.user.id,
                pending_item_id=item.id,
                original_filename=file.filename,
                stored_filename=stored,
                mime_type=mime,
                size_bytes=size,
            )
        )
        session.commit()

    set_flash(request, "Pendência criada.")
    return RedirectResponse("/pendencias", status_code=303)


@app.get("/pendencias/{item_id}", response_class=HTMLResponse)
@require_login
async def pending_detail(request: Request, session: Session = Depends(get_session), item_id: int = 0) -> HTMLResponse:
    ctx = get_tenant_context(request, session)
    if not ctx:
        request.session.clear()
        return RedirectResponse("/login", status_code=303)

    item = session.get(PendingItem, int(item_id))
    if not item or item.company_id != ctx.company.id:
        return render("error.html", request=request, context={"message": "Pendência não encontrada."}, status_code=404)

    if not ensure_can_access_client(ctx, item.client_id):
        return render("error.html", request=request, context={"message": "Sem permissão."}, status_code=403)

    client = session.get(Client, item.client_id)
    attachments = session.exec(
        select(Attachment).where(Attachment.pending_item_id == item.id).order_by(Attachment.created_at.desc())
    ).all()

    msgs = session.exec(
        select(PendingMessage).where(PendingMessage.pending_item_id == item.id).order_by(PendingMessage.created_at.desc())
    ).all()
    messages = []
    for m in msgs:
        u = session.get(User, m.author_user_id)
        messages.append({"author_name": u.name if u else "Usuário", "message": m.message, "created_at": m.created_at})

    current_client = get_client_or_none(session, ctx.company.id, get_active_client_id(request, session, ctx))
    return render(
        "pending_detail.html",
        request=request,
        context={
            "current_user": ctx.user,
            "current_company": ctx.company,
            "role": ctx.membership.role,
            "current_client": current_client,
            "item": item,
            "client": client,
            "attachments": attachments,
            "messages": messages,
        },
    )


@app.post("/pendencias/{item_id}/status")
@require_role({"admin", "equipe"})
async def pending_update_status(
    request: Request,
    session: Session = Depends(get_session),
    item_id: int = 0,
    status: str = Form(...),
) -> Response:
    ctx = get_tenant_context(request, session)
    assert ctx is not None

    item = session.get(PendingItem, int(item_id))
    if not item or item.company_id != ctx.company.id:
        set_flash(request, "Pendência não encontrada.")
        return RedirectResponse("/pendencias", status_code=303)

    status = status.strip().lower()
    if status not in PENDING_STATUSES:
        set_flash(request, "Status inválido.")
        return RedirectResponse(f"/pendencias/{item.id}", status_code=303)

    item.status = status
    item.updated_at = utcnow()
    session.add(item)
    session.commit()
    set_flash(request, "Status atualizado.")
    return RedirectResponse(f"/pendencias/{item.id}", status_code=303)


@app.post("/pendencias/{item_id}/anexar")
@require_role({"admin", "equipe"})
async def pending_attach_admin(
    request: Request,
    session: Session = Depends(get_session),
    item_id: int = 0,
    message: str = Form(""),
    file: UploadFile = File(...),
) -> Response:
    ctx = get_tenant_context(request, session)
    assert ctx is not None

    item = session.get(PendingItem, int(item_id))
    if not item or item.company_id != ctx.company.id:
        set_flash(request, "Pendência não encontrada.")
        return RedirectResponse("/pendencias", status_code=303)

    try:
        stored, mime, size = await save_upload(file)
    except ValueError:
        set_flash(request, "Arquivo muito grande.")
        return RedirectResponse(f"/pendencias/{item.id}", status_code=303)

    session.add(
        Attachment(
            company_id=ctx.company.id,
            client_id=item.client_id,
            uploaded_by_user_id=ctx.user.id,
            pending_item_id=item.id,
            original_filename=file.filename or "arquivo",
            stored_filename=stored,
            mime_type=mime,
            size_bytes=size,
        )
    )
    if message.strip():
        session.add(PendingMessage(pending_item_id=item.id, author_user_id=ctx.user.id, message=message.strip()))

    item.updated_at = utcnow()
    session.add(item)
    session.commit()

    set_flash(request, "Enviado.")
    return RedirectResponse(f"/pendencias/{item.id}", status_code=303)


@app.post("/pendencias/{item_id}/cliente-upload")
@require_role({"cliente"})
async def pending_attach_client(
    request: Request,
    session: Session = Depends(get_session),
    item_id: int = 0,
    message: str = Form(""),
    mark_done: str = Form(""),
    file: UploadFile | None = File(default=None),
) -> Response:
    ctx = get_tenant_context(request, session)
    assert ctx is not None

    item = session.get(PendingItem, int(item_id))
    if not item or item.company_id != ctx.company.id:
        set_flash(request, "Pendência não encontrada.")
        return RedirectResponse("/pendencias", status_code=303)

    if (ctx.membership.client_id or -1) != item.client_id:
        set_flash(request, "Sem permissão.")
        return RedirectResponse("/pendencias", status_code=303)

    if file and file.filename:
        try:
            stored, mime, size = await save_upload(file)
        except ValueError:
            set_flash(request, "Arquivo muito grande.")
            return RedirectResponse(f"/pendencias/{item.id}", status_code=303)

        session.add(
            Attachment(
                company_id=ctx.company.id,
                client_id=item.client_id,
                uploaded_by_user_id=ctx.user.id,
                pending_item_id=item.id,
                original_filename=file.filename,
                stored_filename=stored,
                mime_type=mime,
                size_bytes=size,
            )
        )

    if message.strip():
        session.add(PendingMessage(pending_item_id=item.id, author_user_id=ctx.user.id, message=message.strip()))

    if mark_done == "1":
        item.status = "concluido"
    else:
        if item.status == "aguardando_cliente":
            item.status = "cliente_enviou"

    item.updated_at = utcnow()
    session.add(item)
    session.commit()

    set_flash(request, "Enviado.")
    return RedirectResponse(f"/pendencias/{item.id}", status_code=303)


# ----------------------------
# Documentos
# ----------------------------


@app.get("/documentos", response_class=HTMLResponse)
@require_login
async def docs_list(request: Request, session: Session = Depends(get_session)) -> HTMLResponse:
    ctx = get_tenant_context(request, session)
    if not ctx:
        request.session.clear()
        return RedirectResponse("/login", status_code=303)

    current_client = get_client_or_none(session, ctx.company.id, get_active_client_id(request, session, ctx))

    q = select(Document).where(Document.company_id == ctx.company.id).order_by(Document.created_at.desc())
    if ctx.membership.role == "cliente":
        docs = session.exec(q.where(Document.client_id == (ctx.membership.client_id or -1))).all()
    else:
        if current_client:
            q = q.where(Document.client_id == current_client.id)
        docs = session.exec(q).all()

    out = []
    for d in docs:
        c = session.get(Client, d.client_id)
        out.append(
            {"id": d.id, "title": d.title, "status": d.status, "created_at": d.created_at, "client_name": c.name if c else "—"}
        )

    return render(
        "docs_list.html",
        request=request,
        context={
            "current_user": ctx.user,
            "current_company": ctx.company,
            "role": ctx.membership.role,
            "current_client": current_client,
            "items": out,
        },
    )


@app.get("/documentos/novo", response_class=HTMLResponse)
@require_role({"admin", "equipe"})
async def docs_new_page(request: Request, session: Session = Depends(get_session)) -> HTMLResponse:
    ctx = get_tenant_context(request, session)
    assert ctx is not None
    clients = session.exec(select(Client).where(Client.company_id == ctx.company.id).order_by(Client.created_at)).all()
    current_client = get_client_or_none(session, ctx.company.id, get_active_client_id(request, session, ctx))
    return render(
        "docs_new.html",
        request=request,
        context={
            "current_user": ctx.user,
            "current_company": ctx.company,
            "role": ctx.membership.role,
            "current_client": current_client,
            "clients": clients,
        },
    )


@app.post("/documentos/novo")
@require_role({"admin", "equipe"})
async def docs_new_action(
    request: Request,
    session: Session = Depends(get_session),
    client_id: int = Form(...),
    title: str = Form(...),
    content: str = Form(...),
    status: str = Form("rascunho"),
    file: UploadFile | None = File(default=None),
) -> Response:
    ctx = get_tenant_context(request, session)
    assert ctx is not None

    client = get_client_or_none(session, ctx.company.id, int(client_id))
    if not client:
        set_flash(request, "Cliente inválido.")
        return RedirectResponse("/documentos/novo", status_code=303)

    status = status.strip().lower()
    if status not in DOC_STATUSES:
        status = "rascunho"

    doc = Document(
        company_id=ctx.company.id,
        client_id=client.id,
        created_by_user_id=ctx.user.id,
        title=title.strip(),
        content=content.strip(),
        status=status,
        updated_at=utcnow(),
    )
    session.add(doc)
    session.commit()
    session.refresh(doc)

    if file and file.filename:
        try:
            stored, mime, size = await save_upload(file)
        except ValueError:
            set_flash(request, "Arquivo muito grande.")
            return RedirectResponse("/documentos/novo", status_code=303)

        session.add(
            Attachment(
                company_id=ctx.company.id,
                client_id=client.id,
                uploaded_by_user_id=ctx.user.id,
                document_id=doc.id,
                original_filename=file.filename,
                stored_filename=stored,
                mime_type=mime,
                size_bytes=size,
            )
        )
        session.commit()

    set_flash(request, "Documento criado.")
    return RedirectResponse("/documentos", status_code=303)


@app.get("/documentos/{doc_id}", response_class=HTMLResponse)
@require_login
async def docs_detail(request: Request, session: Session = Depends(get_session), doc_id: int = 0) -> HTMLResponse:
    ctx = get_tenant_context(request, session)
    if not ctx:
        request.session.clear()
        return RedirectResponse("/login", status_code=303)

    doc = session.get(Document, int(doc_id))
    if not doc or doc.company_id != ctx.company.id:
        return render("error.html", request=request, context={"message": "Documento não encontrado."}, status_code=404)

    if not ensure_can_access_client(ctx, doc.client_id):
        return render("error.html", request=request, context={"message": "Sem permissão."}, status_code=403)

    client = session.get(Client, doc.client_id)
    attachments = session.exec(
        select(Attachment).where(Attachment.document_id == doc.id).order_by(Attachment.created_at.desc())
    ).all()

    msgs = session.exec(
        select(DocumentMessage).where(DocumentMessage.document_id == doc.id).order_by(DocumentMessage.created_at.desc())
    ).all()
    messages = []
    for m in msgs:
        u = session.get(User, m.author_user_id)
        messages.append({"author_name": u.name if u else "Usuário", "message": m.message, "created_at": m.created_at})

    current_client = get_client_or_none(session, ctx.company.id, get_active_client_id(request, session, ctx))

    return render(
        "docs_detail.html",
        request=request,
        context={
            "current_user": ctx.user,
            "current_company": ctx.company,
            "role": ctx.membership.role,
            "current_client": current_client,
            "doc": doc,
            "client": client,
            "attachments": attachments,
            "messages": messages,
        },
    )


@app.post("/documentos/{doc_id}/status")
@require_role({"admin", "equipe"})
async def docs_update_status(
    request: Request, session: Session = Depends(get_session), doc_id: int = 0, status: str = Form(...)
) -> Response:
    ctx = get_tenant_context(request, session)
    assert ctx is not None

    doc = session.get(Document, int(doc_id))
    if not doc or doc.company_id != ctx.company.id:
        set_flash(request, "Documento não encontrado.")
        return RedirectResponse("/documentos", status_code=303)

    status = status.strip().lower()
    if status not in DOC_STATUSES:
        set_flash(request, "Status inválido.")
        return RedirectResponse(f"/documentos/{doc.id}", status_code=303)

    doc.status = status
    doc.updated_at = utcnow()
    session.add(doc)
    session.commit()

    set_flash(request, "Status atualizado.")
    return RedirectResponse(f"/documentos/{doc.id}", status_code=303)


@app.post("/documentos/{doc_id}/anexar")
@require_role({"admin", "equipe"})
async def docs_attach_admin(
    request: Request,
    session: Session = Depends(get_session),
    doc_id: int = 0,
    message: str = Form(""),
    file: UploadFile = File(...),
) -> Response:
    ctx = get_tenant_context(request, session)
    assert ctx is not None

    doc = session.get(Document, int(doc_id))
    if not doc or doc.company_id != ctx.company.id:
        set_flash(request, "Documento não encontrado.")
        return RedirectResponse("/documentos", status_code=303)

    try:
        stored, mime, size = await save_upload(file)
    except ValueError:
        set_flash(request, "Arquivo muito grande.")
        return RedirectResponse(f"/documentos/{doc.id}", status_code=303)

    session.add(
        Attachment(
            company_id=ctx.company.id,
            client_id=doc.client_id,
            uploaded_by_user_id=ctx.user.id,
            document_id=doc.id,
            original_filename=file.filename or "arquivo",
            stored_filename=stored,
            mime_type=mime,
            size_bytes=size,
        )
    )
    if message.strip():
        session.add(DocumentMessage(document_id=doc.id, author_user_id=ctx.user.id, message=message.strip()))

    doc.updated_at = utcnow()
    session.add(doc)
    session.commit()

    set_flash(request, "Enviado.")
    return RedirectResponse(f"/documentos/{doc.id}", status_code=303)


@app.post("/documentos/{doc_id}/cliente-upload")
@require_role({"cliente"})
async def docs_attach_client(
    request: Request,
    session: Session = Depends(get_session),
    doc_id: int = 0,
    message: str = Form(""),
    file: UploadFile = File(...),
) -> Response:
    ctx = get_tenant_context(request, session)
    assert ctx is not None

    doc = session.get(Document, int(doc_id))
    if not doc or doc.company_id != ctx.company.id:
        set_flash(request, "Documento não encontrado.")
        return RedirectResponse("/documentos", status_code=303)

    if (ctx.membership.client_id or -1) != doc.client_id:
        set_flash(request, "Sem permissão.")
        return RedirectResponse("/documentos", status_code=303)

    try:
        stored, mime, size = await save_upload(file)
    except ValueError:
        set_flash(request, "Arquivo muito grande.")
        return RedirectResponse(f"/documentos/{doc.id}", status_code=303)

    session.add(
        Attachment(
            company_id=ctx.company.id,
            client_id=doc.client_id,
            uploaded_by_user_id=ctx.user.id,
            document_id=doc.id,
            original_filename=file.filename or "arquivo",
            stored_filename=stored,
            mime_type=mime,
            size_bytes=size,
        )
    )
    if message.strip():
        session.add(DocumentMessage(document_id=doc.id, author_user_id=ctx.user.id, message=message.strip()))

    if doc.status == "aguardando_cliente":
        doc.status = "cliente_enviou"

    doc.updated_at = utcnow()
    session.add(doc)
    session.commit()

    set_flash(request, "Enviado.")
    return RedirectResponse(f"/documentos/{doc.id}", status_code=303)


# ----------------------------
# Propostas / Solicitações
# ----------------------------


def _proposal_allowed_statuses(kind: str) -> list[str]:
    if kind == "solicitacao":
        return ["aberta", "em_analise", "respondida", "encerrada"]
    return ["rascunho", "enviada", "aprovada", "rejeitada"]


@app.get("/propostas", response_class=HTMLResponse)
@require_login
async def props_list(request: Request, session: Session = Depends(get_session)) -> HTMLResponse:
    ctx = get_tenant_context(request, session)
    if not ctx:
        request.session.clear()
        return RedirectResponse("/login", status_code=303)

    current_client = get_client_or_none(session, ctx.company.id, get_active_client_id(request, session, ctx))

    q = select(Proposal).where(Proposal.company_id == ctx.company.id).order_by(Proposal.created_at.desc())
    if ctx.membership.role == "cliente":
        items = session.exec(q.where(Proposal.client_id == (ctx.membership.client_id or -1))).all()
    else:
        if current_client:
            q = q.where(Proposal.client_id == current_client.id)
        items = session.exec(q).all()

    out = []
    for p in items:
        c = session.get(Client, p.client_id)
        out.append(
            {
                "id": p.id,
                "kind": p.kind,
                "title": p.title,
                "status": p.status,
                "value_brl": p.value_brl,
                "created_at": p.created_at,
                "client_name": c.name if c else "—",
            }
        )

    return render(
        "props_list.html",
        request=request,
        context={
            "current_user": ctx.user,
            "current_company": ctx.company,
            "role": ctx.membership.role,
            "current_client": current_client,
            "items": out,
        },
    )


@app.get("/propostas/nova", response_class=HTMLResponse)
@require_role({"admin", "equipe"})
async def props_new_staff_page(request: Request, session: Session = Depends(get_session)) -> HTMLResponse:
    ctx = get_tenant_context(request, session)
    assert ctx is not None
    clients = session.exec(select(Client).where(Client.company_id == ctx.company.id).order_by(Client.created_at)).all()
    current_client = get_client_or_none(session, ctx.company.id, get_active_client_id(request, session, ctx))
    return render(
        "props_new_staff.html",
        request=request,
        context={
            "current_user": ctx.user,
            "current_company": ctx.company,
            "role": ctx.membership.role,
            "current_client": current_client,
            "clients": clients,
        },
    )


@app.post("/propostas/nova")
@require_role({"admin", "equipe"})
async def props_new_staff_action(
    request: Request,
    session: Session = Depends(get_session),
    client_id: int = Form(...),
    title: str = Form(...),
    description: str = Form(""),
    value_brl: float = Form(0.0),
    status: str = Form("rascunho"),
    file: UploadFile | None = File(default=None),
) -> Response:
    ctx = get_tenant_context(request, session)
    assert ctx is not None

    client = get_client_or_none(session, ctx.company.id, int(client_id))
    if not client:
        set_flash(request, "Cliente inválido.")
        return RedirectResponse("/propostas/nova", status_code=303)

    status = status.strip().lower()
    if status not in _proposal_allowed_statuses("proposta"):
        status = "rascunho"

    prop = Proposal(
        company_id=ctx.company.id,
        client_id=client.id,
        created_by_user_id=ctx.user.id,
        kind="proposta",
        title=title.strip(),
        description=description.strip(),
        value_brl=max(0.0, float(value_brl)),
        status=status,
        updated_at=utcnow(),
    )
    session.add(prop)
    session.commit()
    session.refresh(prop)

    if file and file.filename:
        try:
            stored, mime, size = await save_upload(file)
        except ValueError:
            set_flash(request, "Arquivo muito grande.")
            return RedirectResponse("/propostas/nova", status_code=303)

        session.add(
            Attachment(
                company_id=ctx.company.id,
                client_id=client.id,
                uploaded_by_user_id=ctx.user.id,
                proposal_id=prop.id,
                original_filename=file.filename,
                stored_filename=stored,
                mime_type=mime,
                size_bytes=size,
            )
        )
        session.commit()

    set_flash(request, "Proposta criada.")
    return RedirectResponse("/propostas", status_code=303)


@app.get("/propostas/solicitacao", response_class=HTMLResponse)
@require_role({"cliente"})
async def props_new_client_page(request: Request, session: Session = Depends(get_session)) -> HTMLResponse:
    ctx = get_tenant_context(request, session)
    assert ctx is not None
    current_client = get_client_or_none(session, ctx.company.id, get_active_client_id(request, session, ctx))
    return render(
        "props_new_client.html",
        request=request,
        context={
            "current_user": ctx.user,
            "current_company": ctx.company,
            "role": ctx.membership.role,
            "current_client": current_client,
        },
    )


@app.post("/propostas/solicitacao")
@require_role({"cliente"})
async def props_new_client_action(
    request: Request,
    session: Session = Depends(get_session),
    title: str = Form(...),
    description: str = Form(...),
    file: UploadFile | None = File(default=None),
) -> Response:
    ctx = get_tenant_context(request, session)
    assert ctx is not None

    client_id = ctx.membership.client_id
    if not client_id:
        set_flash(request, "Seu usuário não está vinculado a um cliente.")
        return RedirectResponse("/propostas", status_code=303)

    prop = Proposal(
        company_id=ctx.company.id,
        client_id=client_id,
        created_by_user_id=ctx.user.id,
        kind="solicitacao",
        title=title.strip(),
        description=description.strip(),
        value_brl=0.0,
        status="aberta",
        updated_at=utcnow(),
    )
    session.add(prop)
    session.commit()
    session.refresh(prop)

    if file and file.filename:
        try:
            stored, mime, size = await save_upload(file)
        except ValueError:
            set_flash(request, "Arquivo muito grande.")
            return RedirectResponse("/propostas/solicitacao", status_code=303)

        session.add(
            Attachment(
                company_id=ctx.company.id,
                client_id=client_id,
                uploaded_by_user_id=ctx.user.id,
                proposal_id=prop.id,
                original_filename=file.filename,
                stored_filename=stored,
                mime_type=mime,
                size_bytes=size,
            )
        )

    session.add(ProposalMessage(proposal_id=prop.id, author_user_id=ctx.user.id, message="Solicitação criada."))
    session.commit()

    set_flash(request, "Solicitação enviada.")
    return RedirectResponse(f"/propostas/{prop.id}", status_code=303)


@app.get("/propostas/{prop_id}", response_class=HTMLResponse)
@require_login
async def props_detail(request: Request, session: Session = Depends(get_session), prop_id: int = 0) -> HTMLResponse:
    ctx = get_tenant_context(request, session)
    if not ctx:
        request.session.clear()
        return RedirectResponse("/login", status_code=303)

    prop = session.get(Proposal, int(prop_id))
    if not prop or prop.company_id != ctx.company.id:
        return render("error.html", request=request, context={"message": "Item não encontrado."}, status_code=404)

    if not ensure_can_access_client(ctx, prop.client_id):
        return render("error.html", request=request, context={"message": "Sem permissão."}, status_code=403)

    client = session.get(Client, prop.client_id)
    attachments = session.exec(
        select(Attachment).where(Attachment.proposal_id == prop.id).order_by(Attachment.created_at.desc())
    ).all()

    msgs = session.exec(
        select(ProposalMessage).where(ProposalMessage.proposal_id == prop.id).order_by(ProposalMessage.created_at.desc())
    ).all()
    messages = []
    for m in msgs:
        u = session.get(User, m.author_user_id)
        messages.append({"author_name": u.name if u else "Usuário", "message": m.message, "created_at": m.created_at})

    current_client = get_client_or_none(session, ctx.company.id, get_active_client_id(request, session, ctx))

    return render(
        "props_detail.html",
        request=request,
        context={
            "current_user": ctx.user,
            "current_company": ctx.company,
            "role": ctx.membership.role,
            "current_client": current_client,
            "prop": prop,
            "client": client,
            "attachments": attachments,
            "messages": messages,
            "allowed_statuses": _proposal_allowed_statuses(prop.kind),
        },
    )


@app.post("/propostas/{prop_id}/atualizar")
@require_role({"admin", "equipe"})
async def props_update_staff(
    request: Request,
    session: Session = Depends(get_session),
    prop_id: int = 0,
    kind: str = Form(...),
    status: str = Form(...),
    value_brl: float = Form(0.0),
    message: str = Form(""),
) -> Response:
    ctx = get_tenant_context(request, session)
    assert ctx is not None

    prop = session.get(Proposal, int(prop_id))
    if not prop or prop.company_id != ctx.company.id:
        set_flash(request, "Item não encontrado.")
        return RedirectResponse("/propostas", status_code=303)

    kind = kind.strip().lower()
    if kind not in PROPOSAL_KINDS:
        kind = prop.kind

    status = status.strip().lower()
    if status not in _proposal_allowed_statuses(kind):
        set_flash(request, "Status inválido.")
        return RedirectResponse(f"/propostas/{prop.id}", status_code=303)

    prop.kind = kind
    prop.status = status
    prop.value_brl = max(0.0, float(value_brl))
    prop.updated_at = utcnow()
    session.add(prop)

    if message.strip():
        session.add(ProposalMessage(proposal_id=prop.id, author_user_id=ctx.user.id, message=message.strip()))

    session.commit()
    set_flash(request, "Atualizado.")
    return RedirectResponse(f"/propostas/{prop.id}", status_code=303)


@app.post("/propostas/{prop_id}/anexar")
@require_role({"admin", "equipe"})
async def props_attach_staff(
    request: Request,
    session: Session = Depends(get_session),
    prop_id: int = 0,
    file: UploadFile = File(...),
) -> Response:
    ctx = get_tenant_context(request, session)
    assert ctx is not None

    prop = session.get(Proposal, int(prop_id))
    if not prop or prop.company_id != ctx.company.id:
        set_flash(request, "Item não encontrado.")
        return RedirectResponse("/propostas", status_code=303)

    try:
        stored, mime, size = await save_upload(file)
    except ValueError:
        set_flash(request, "Arquivo muito grande.")
        return RedirectResponse(f"/propostas/{prop.id}", status_code=303)

    session.add(
        Attachment(
            company_id=ctx.company.id,
            client_id=prop.client_id,
            uploaded_by_user_id=ctx.user.id,
            proposal_id=prop.id,
            original_filename=file.filename or "arquivo",
            stored_filename=stored,
            mime_type=mime,
            size_bytes=size,
        )
    )
    session.commit()
    set_flash(request, "Anexo enviado.")
    return RedirectResponse(f"/propostas/{prop.id}", status_code=303)


@app.post("/propostas/{prop_id}/cliente-upload")
@require_role({"cliente"})
async def props_client_upload(
    request: Request,
    session: Session = Depends(get_session),
    prop_id: int = 0,
    message: str = Form(""),
    file: UploadFile | None = File(default=None),
) -> Response:
    ctx = get_tenant_context(request, session)
    assert ctx is not None

    prop = session.get(Proposal, int(prop_id))
    if not prop or prop.company_id != ctx.company.id:
        set_flash(request, "Item não encontrado.")
        return RedirectResponse("/propostas", status_code=303)

    if (ctx.membership.client_id or -1) != prop.client_id:
        set_flash(request, "Sem permissão.")
        return RedirectResponse("/propostas", status_code=303)

    if file and file.filename:
        try:
            stored, mime, size = await save_upload(file)
        except ValueError:
            set_flash(request, "Arquivo muito grande.")
            return RedirectResponse(f"/propostas/{prop.id}", status_code=303)

        session.add(
            Attachment(
                company_id=ctx.company.id,
                client_id=prop.client_id,
                uploaded_by_user_id=ctx.user.id,
                proposal_id=prop.id,
                original_filename=file.filename,
                stored_filename=stored,
                mime_type=mime,
                size_bytes=size,
            )
        )

    if message.strip():
        session.add(ProposalMessage(proposal_id=prop.id, author_user_id=ctx.user.id, message=message.strip()))

    prop.updated_at = utcnow()
    session.add(prop)
    session.commit()
    set_flash(request, "Enviado.")
    return RedirectResponse(f"/propostas/{prop.id}", status_code=303)


# ----------------------------
# Financeiro (Notas/Boletos)
# ----------------------------


@app.get("/financeiro", response_class=HTMLResponse)
@require_login
async def fin_list(request: Request, session: Session = Depends(get_session)) -> HTMLResponse:
    ctx = get_tenant_context(request, session)
    if not ctx:
        request.session.clear()
        return RedirectResponse("/login", status_code=303)

    current_client = get_client_or_none(session, ctx.company.id, get_active_client_id(request, session, ctx))

    q = select(FinanceInvoice).where(FinanceInvoice.company_id == ctx.company.id).order_by(FinanceInvoice.created_at.desc())
    if ctx.membership.role == "cliente":
        invoices = session.exec(q.where(FinanceInvoice.client_id == (ctx.membership.client_id or -1))).all()
    else:
        if current_client:
            q = q.where(FinanceInvoice.client_id == current_client.id)
        invoices = session.exec(q).all()

    out = []
    for it in invoices:
        c = session.get(Client, it.client_id)
        out.append(
            {
                "id": it.id,
                "title": it.title,
                "amount_brl": it.amount_brl,
                "due_date": it.due_date,
                "status": it.status,
                "created_at": it.created_at,
                "client_name": c.name if c else "—",
            }
        )

    return render(
        "fin_list.html",
        request=request,
        context={
            "current_user": ctx.user,
            "current_company": ctx.company,
            "role": ctx.membership.role,
            "current_client": current_client,
            "items": out,
        },
    )


@app.get("/financeiro/novo", response_class=HTMLResponse)
@require_role({"admin", "equipe"})
async def fin_new_page(request: Request, session: Session = Depends(get_session)) -> HTMLResponse:
    ctx = get_tenant_context(request, session)
    assert ctx is not None
    clients = session.exec(select(Client).where(Client.company_id == ctx.company.id).order_by(Client.created_at)).all()
    current_client = get_client_or_none(session, ctx.company.id, get_active_client_id(request, session, ctx))
    return render(
        "fin_new.html",
        request=request,
        context={
            "current_user": ctx.user,
            "current_company": ctx.company,
            "role": ctx.membership.role,
            "current_client": current_client,
            "clients": clients,
        },
    )


@app.post("/financeiro/novo")
@require_role({"admin", "equipe"})
async def fin_new_action(
    request: Request,
    session: Session = Depends(get_session),
    client_id: int = Form(...),
    title: str = Form(...),
    amount_brl: float = Form(...),
    due_date: str = Form(""),
    status: str = Form("emitido"),
    notes: str = Form(""),
    file: UploadFile = File(...),
) -> Response:
    ctx = get_tenant_context(request, session)
    assert ctx is not None

    client = get_client_or_none(session, ctx.company.id, int(client_id))
    if not client:
        set_flash(request, "Cliente inválido.")
        return RedirectResponse("/financeiro/novo", status_code=303)

    status = status.strip().lower()
    if status not in FIN_STATUSES:
        status = "emitido"

    inv = FinanceInvoice(
        company_id=ctx.company.id,
        client_id=client.id,
        created_by_user_id=ctx.user.id,
        title=title.strip(),
        amount_brl=max(0.0, float(amount_brl)),
        due_date=due_date.strip(),
        status=status,
        notes=notes.strip(),
        updated_at=utcnow(),
    )
    session.add(inv)
    session.commit()
    session.refresh(inv)

    try:
        stored, mime, size = await save_upload(file)
    except ValueError:
        set_flash(request, "Arquivo muito grande.")
        return RedirectResponse("/financeiro/novo", status_code=303)

    session.add(
        Attachment(
            company_id=ctx.company.id,
            client_id=client.id,
            uploaded_by_user_id=ctx.user.id,
            finance_invoice_id=inv.id,
            original_filename=file.filename or "arquivo",
            stored_filename=stored,
            mime_type=mime,
            size_bytes=size,
        )
    )
    session.commit()

    set_flash(request, "Cobrança criada.")
    return RedirectResponse("/financeiro", status_code=303)


@app.get("/financeiro/{inv_id}", response_class=HTMLResponse)
@require_login
async def fin_detail(request: Request, session: Session = Depends(get_session), inv_id: int = 0) -> HTMLResponse:
    ctx = get_tenant_context(request, session)
    if not ctx:
        request.session.clear()
        return RedirectResponse("/login", status_code=303)

    inv = session.get(FinanceInvoice, int(inv_id))
    if not inv or inv.company_id != ctx.company.id:
        return render("error.html", request=request, context={"message": "Cobrança não encontrada."}, status_code=404)

    if not ensure_can_access_client(ctx, inv.client_id):
        return render("error.html", request=request, context={"message": "Sem permissão."}, status_code=403)

    client = session.get(Client, inv.client_id)
    attachments = session.exec(
        select(Attachment).where(Attachment.finance_invoice_id == inv.id).order_by(Attachment.created_at.desc())
    ).all()

    current_client = get_client_or_none(session, ctx.company.id, get_active_client_id(request, session, ctx))

    return render(
        "fin_detail.html",
        request=request,
        context={
            "current_user": ctx.user,
            "current_company": ctx.company,
            "role": ctx.membership.role,
            "current_client": current_client,
            "inv": inv,
            "client": client,
            "attachments": attachments,
        },
    )


@app.post("/financeiro/{inv_id}/anexar")
@require_role({"admin", "equipe"})
async def fin_attach(
    request: Request,
    session: Session = Depends(get_session),
    inv_id: int = 0,
    file: UploadFile = File(...),
) -> Response:
    ctx = get_tenant_context(request, session)
    assert ctx is not None

    inv = session.get(FinanceInvoice, int(inv_id))
    if not inv or inv.company_id != ctx.company.id:
        set_flash(request, "Cobrança não encontrada.")
        return RedirectResponse("/financeiro", status_code=303)

    try:
        stored, mime, size = await save_upload(file)
    except ValueError:
        set_flash(request, "Arquivo muito grande.")
        return RedirectResponse(f"/financeiro/{inv.id}", status_code=303)

    session.add(
        Attachment(
            company_id=ctx.company.id,
            client_id=inv.client_id,
            uploaded_by_user_id=ctx.user.id,
            finance_invoice_id=inv.id,
            original_filename=file.filename or "arquivo",
            stored_filename=stored,
            mime_type=mime,
            size_bytes=size,
        )
    )
    inv.updated_at = utcnow()
    session.add(inv)
    session.commit()

    set_flash(request, "Anexo enviado.")
    return RedirectResponse(f"/financeiro/{inv.id}", status_code=303)


# ----------------------------
# Download (protected)
# ----------------------------


@app.get("/download/{attachment_id}")
@require_login
async def download_attachment(request: Request, session: Session = Depends(get_session), attachment_id: int = 0) -> Response:
    ctx = get_tenant_context(request, session)
    if not ctx:
        request.session.clear()
        return RedirectResponse("/login", status_code=303)

    att = session.get(Attachment, int(attachment_id))
    if not att or att.company_id != ctx.company.id:
        return render("error.html", request=request, context={"message": "Arquivo não encontrado."}, status_code=404)

    if not ensure_can_access_client(ctx, att.client_id):
        return render("error.html", request=request, context={"message": "Sem permissão."}, status_code=403)

    path = UPLOAD_DIR / att.stored_filename
    if not path.exists():
        return render("error.html", request=request, context={"message": "Arquivo não está mais no servidor."}, status_code=404)

    return FileResponse(path=str(path), media_type=att.mime_type, filename=att.original_filename)


# ----------------------------
# Aliases (se você tinha URLs antigas)
# ----------------------------

@app.get("/documents")
async def _alias_docs() -> Response:
    return RedirectResponse("/documentos", status_code=307)

@app.get("/proposals")
async def _alias_props() -> Response:
    return RedirectResponse("/propostas", status_code=307)

@app.get("/finance")
async def _alias_fin() -> Response:
    return RedirectResponse("/financeiro", status_code=307)
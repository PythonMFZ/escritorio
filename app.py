from __future__ import annotations
from sqlalchemy import func, delete
from sqlalchemy.exc import OperationalError

import base64
import hashlib
import hmac
import inspect
import json
import html
import os
import asyncio
import re
import secrets
import uuid
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from functools import wraps
from pathlib import Path
from typing import Any, Callable, Optional
from urllib.parse import urlparse

import httpx
from fastapi import BackgroundTasks, Depends, FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from jinja2 import Environment
from jinja2.loaders import DictLoader
from passlib.context import CryptContext
from sqlalchemy import UniqueConstraint, func
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
ALLOW_COMPANY_SIGNUP = os.getenv("ALLOW_COMPANY_SIGNUP", "0") == "1"

CLIENT_INVITE_TTL_HOURS = int(os.getenv("CLIENT_INVITE_TTL_HOURS", "168"))  # 7 dias
CLIENT_INVITE_REQUIRE_LAST4 = os.getenv("CLIENT_INVITE_REQUIRE_LAST4",
                                        "1") == "1"  # valida últimos 4 dígitos do CNPJ/CPF quando disponível

BOOKINGS_URL = os.getenv(
    "BOOKINGS_URL") or "https://outlook.office.com/book/ReservasMaffezzolliConsultorRafael@mfzcapital.onmicrosoft.com/?ismsaljsauthenabled"

SERVICE_CATALOG = [
    {
        "name": "Advisory - Consultoria Turnaround",
        "description": "Consultoria em reestruturação de empresas"
    },
    {
        "name": "Advisory - Consultoria Valuation",
        "description": "Avaliação de empresas"
    },
    {
        "name": "Advisory - Consultoria Estratégica Financeira",
        "description": "Consultoria em finanças empresariais"
    },
    {
        "name": "IB - Assessoria em Rodada Anjo/Seed/Série A (ECM)",
        "description": "Conectar startups e empresas em crescimento com investidores de Venture Capital."
    },
    {
        "name": "IB - Roadshow para Captação de Equity (ECM)",
        "description": "Apresentar a empresa a múltiplos fundos de Private Equity para captações maiores."
    },
    {
        "name": "IB - Estruturação de Debênture (DCM)",
        "description": "Criar e assessorar a emissão de títulos de dívida da empresa no mercado."
    },
    {
        "name": "IB - Estruturação de CRI/CRA (DCM)",
        "description": "Títulos de dívida lastreados em recebíveis imobiliários ou do agronegócio."
    },
    {
        "name": "IB - Mandato de Venda (M&A Sell-side)",
        "description": "Assessorar o dono de uma empresa a vendê-la total ou parcialmente."
    },
    {
        "name": "IB - Mandato de Compra (M&A Buy-side)",
        "description": "Assessorar uma empresa a comprar outra."
    },
    {
        "name": "Advisory - Plano de Recuperação Judicial",
        "description": "Foco em preparar o plano, os documentos e a estratégia para a aprovação judicial."
    },
    {
        "name": "Special Sits - Assessoria em M&A de Ativos Estressados (Distressed M&A)",
        "description": "Conduzimos processos de fusão e aquisição para empresas em situações de crise, focando na agilidade da transação e na maximização de valor para os stakeholders."
    },
    {
        "name": "Special Sits - Intermediação de Créditos de RJ (Recuperação Judicial)",
        "description": "Conectamos credores que desejam liquidar seus recebíveis com investidores especializados na compra de créditos de empresas em Recuperação Judicial, gerando liquidez imediata."
    },
    {
        "name": "Special Sits - Venda de Créditos Tributários (Precatórios,etc.)",
        "description": "Estruturamos a venda de ativos tributários (como precatórios e saldos credores de impostos) para monetizar recursos não-líquidos e gerar caixa para a sua empresa."
    },
    {
        "name": "Special Sits - Captação de Financiamento DIP (Debtor-in-Possession)",
        "description": "Assessoramos empresas em Recuperação Judicial na captação de financiamentos emergenciais (DIP Financing), essenciais para financiar a operação e o plano de reestruturação."
    },
    {
        "name": "BaaS - Capital de Giro",
        "description": "Intermediamos linhas de capital de giro para financiar as operações do dia a dia da sua empresa e otimizar seu fluxo de caixa."
    },
    {
        "name": "BaaS - Conta Garantida",
        "description": "Estruturamos o acesso a linhas de crédito rotativo (conta garantida), oferecendo flexibilidade de caixa para as necessidades imediatas do seu negócio."
    },
    {
        "name": "BaaS - Desconto de Duplicatas / Antecipação de Títulos",
        "description": "Transforme suas vendas a prazo em caixa imediato através da antecipação de recebíveis, como duplicatas e cheques."
    },
    {
        "name": "BaaS - Antecipação de Cartões",
        "description": "Adiantamos os valores de suas vendas no cartão de crédito, melhorando o fluxo de caixa e o capital de giro da sua empresa."
    },
    {
        "name": "BaaS - Câmbio Pronto (PF e PJ)",
        "description": "Viabilizamos operações de compra e venda de moeda estrangeira para pessoas físicas e jurídicas com agilidade e taxas competitivas."
    },
    {
        "name": "BaaS - Trade Finance",
        "description": "Assessoramos na estruturação de operações de Trade Finance (ACC/ACE) para financiar e otimizar suas atividades de comércio exterior."
    },
    {
        "name": "BaaS - Financiamento de Veículos",
        "description": "Intermediamos as melhores linhas de financiamento para a aquisição de veículos, renovação de frota."
    },
    {
        "name": "BaaS - Consórcio",
        "description": "Oferecemos acesso a grupos de consórcio para a aquisição planejada de imóveis e veículos como uma alternativa de crédito sem juros."
    },
    {
        "name": "BaaS - Cessão de Crédito",
        "description": "Coordenamos a venda (cessão) de carteiras de crédito ou recebíveis, transformando ativos de baixa liquidez em caixa para a empresa."
    },
    {
        "name": "BaaS - Auto Equity",
        "description": "Estruturamos operações de crédito utilizando seus veículos como garantia para obter maiores volumes e taxas mais competitivas."
    },
    {
        "name": "BaaS - Crédito Corporativo Estruturado",
        "description": "É uma operação de crédito (empréstimo/financiamento) desenhada sob medida para uma necessidade específica de uma empresa, geralmente para valores mais altos ou situações mais complexas que não se encaixam nas linhas de crédito padrão."
    },
    {
        "name": "BaaS - Home Equity (Empréstimo com Garantia de Imóvel)",
        "description": "É uma modalidade de crédito onde o cliente (Pessoa Física ou Jurídica) utiliza um imóvel que já possui e está quitado (ou parcialmente quitado) como garantia para obter um empréstimo."
    },
    {
        "name": "BaaS - Crédito Habitacional",
        "description": "Esta é a modalidade mais comum, onde o banco financia a pessoa física que está comprando o imóvel da sua construtora."
    },
    {
        "name": "BaaS - Financiamento à Produção (Plano Empresário)",
        "description": "Este é um produto específico com um objetivo claro: financiar a construção de um empreendimento imobiliário."
    },
    {
        "name": "BaaS - Analise de Crédito",
        "description": "Contrate nossa Análise de Crédito e receba um relatório completo  sobre o perfil de risco da sua empresa ou cliente."
    }
]

SERVICE_NAME_SET = {x["name"] for x in SERVICE_CATALOG}


def sanitize_service_name(name: str) -> str:
    s = (name or "").strip()
    return s if s in SERVICE_NAME_SET else ""


NOTION_TOKEN = os.getenv("NOTION_TOKEN")
NOTION_DB_NEGOCIOS_ID = os.getenv("NOTION_DB_NEGOCIOS_ID")
DIRECTDATA_TOKEN = os.getenv("DIRECTDATA_TOKEN")
DIRECTDATA_SCR_URL = os.getenv("DIRECTDATA_SCR_URL") or "https://apiv3.directd.com.br/api/SCRBacenDetalhada"
DIRECTDATA_ASYNC = os.getenv("DIRECTDATA_ASYNC", "1") == "1"
DIRECTDATA_TIMEOUT_S = float(os.getenv("DIRECTDATA_TIMEOUT_S", "30"))
CREDIT_CONSENT_MAX_DAYS = int(os.getenv("CREDIT_CONSENT_MAX_DAYS", "180"))

CONTA_AZUL_CLIENT_ID = os.getenv("CONTA_AZUL_CLIENT_ID") or ""
CONTA_AZUL_CLIENT_SECRET = os.getenv("CONTA_AZUL_CLIENT_SECRET") or ""
CONTA_AZUL_SCOPE = os.getenv("CONTA_AZUL_SCOPE") or "openid profile aws.cognito.signin.user.admin"
CONTA_AZUL_AUTH_URL = os.getenv("CONTA_AZUL_AUTH_URL") or "https://auth.contaazul.com/login"
CONTA_AZUL_TOKEN_URL = os.getenv("CONTA_AZUL_TOKEN_URL") or "https://auth.contaazul.com/oauth2/token"
CONTA_AZUL_API_BASE = os.getenv("CONTA_AZUL_API_BASE") or "https://api-v2.contaazul.com"
CONTA_AZUL_SYNC_DAYS_BACK = int(os.getenv("CONTA_AZUL_SYNC_DAYS_BACK", "180"))
CONTA_AZUL_SYNC_DAYS_FORWARD = int(os.getenv("CONTA_AZUL_SYNC_DAYS_FORWARD", "30"))
CONTA_AZUL_SYNC_MAX_ITEMS = int(os.getenv("CONTA_AZUL_SYNC_MAX_ITEMS", "200"))

CONTA_AZUL_DEBUG = os.getenv("CONTA_AZUL_DEBUG", "0") == "1"
CONTA_AZUL_HTTP_TIMEOUT_S = float(os.getenv("CONTA_AZUL_HTTP_TIMEOUT_S", "20"))
PUBLIC_BASE_URL = (os.getenv("PUBLIC_BASE_URL") or "").rstrip("/")
PUBLIC_BASE_URL_FORCE = os.getenv("PUBLIC_BASE_URL_FORCE", "0") == "1"
CREDIT_CONSENT_LINK_TTL_HOURS = int(os.getenv("CREDIT_CONSENT_LINK_TTL_HOURS", "168"))  # 7 dias
CREDIT_CONSENT_TERM_VERSION = os.getenv("CREDIT_CONSENT_TERM_VERSION", "2026-03-14")
DIRECTDATA_ASYNC_RESULT_URL = os.getenv(
    "DIRECTDATA_ASYNC_RESULT_URL") or "https://apiv3.directd.com.br/api/Historico/ObterRetornoConsultaAsync"
DIRECTDATA_POLL_MIN_INTERVAL_S = float(os.getenv("DIRECTDATA_POLL_MIN_INTERVAL_S", "6"))

NOTION_VERSION = os.getenv("NOTION_VERSION", "2026-03-11")
NOTION_API_BASE = "https://api.notion.com/v1"

UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR") or "./uploads").resolve()
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

engine = create_engine(
    DATABASE_URL,
    echo=False,
    pool_pre_ping=True,
    pool_recycle=300,
    connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {"connect_timeout": 5},
)

_MAX_PASSWORD_BYTES = 1024
_MAX_UPLOAD_BYTES = 20 * 1024 * 1024  # 20MB (ajuste se quiser)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("utf-8").rstrip("=")


def _b64url_decode(data: str) -> bytes:
    s = (data or "").strip()
    if not s:
        return b""
    pad = "=" * ((4 - (len(s) % 4)) % 4)
    return base64.urlsafe_b64decode((s + pad).encode("utf-8"))


def _hmac_sha256_hex(key: str, msg: bytes) -> str:
    return hmac.new(key.encode("utf-8"), msg, hashlib.sha256).hexdigest()


def _sign_consent_token(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    b64 = _b64url_encode(raw)
    sig = _hmac_sha256_hex(APP_SECRET_KEY, raw)
    return f"{b64}.{sig}"


def _verify_consent_token(token: str) -> dict[str, Any]:
    tok = (token or "").strip()
    if "." not in tok:
        raise ValueError("token inválido")
    b64, sig = tok.split(".", 1)
    raw = _b64url_decode(b64)
    expected = _hmac_sha256_hex(APP_SECRET_KEY, raw)
    if not hmac.compare_digest(expected, sig):
        raise ValueError("assinatura inválida")
    payload = json.loads(raw.decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("payload inválido")
    exp = int(payload.get("exp") or 0)
    if exp and utcnow().timestamp() > exp:
        raise ValueError("token expirado")
    return payload


def _request_origin(request: Request) -> str:
    """Origem pública do request.

    Preferimos o header Host (mais fiel em custom domains). Só caímos em
    x-forwarded-host quando Host estiver ausente.
    """
    proto = (request.headers.get("x-forwarded-proto") or request.url.scheme or "https").split(",")[0].strip()
    host = (request.headers.get("host") or request.headers.get("x-forwarded-host") or request.url.netloc).split(",")[
        0].strip()
    return f"{proto}://{host}".rstrip("/")


def _request_path_prefix(request: Request) -> str:
    """Prefixo público do caminho (ex.: /staging).

    Alguns proxies publicam o app em subpath e informam isso via X-Forwarded-Prefix.
    Se não houver header, usamos root_path.
    """
    raw = (request.headers.get("x-forwarded-prefix") or "").split(",")[0].strip()
    if not raw:
        raw = str(request.scope.get("root_path") or "").strip()
    raw = raw.strip()
    if not raw or raw == "/":
        return ""
    return "/" + raw.strip("/")


def _public_base_url(request: Request) -> str:
    """Base público para links.

    Regras:
    - Usa o host efetivo do request (X-Forwarded-Proto/Host) + prefixo (X-Forwarded-Prefix/root_path).
    - Se PUBLIC_BASE_URL estiver definido:
        - PUBLIC_BASE_URL_FORCE=1 => sempre usa PUBLIC_BASE_URL
        - caso contrário, usa PUBLIC_BASE_URL somente quando o host bater com o host atual.
    """
    origin = _request_origin(request)
    prefix = _request_path_prefix(request).rstrip("/")
    request_base = (origin + prefix).rstrip("/")

    if not PUBLIC_BASE_URL:
        return request_base

    public = PUBLIC_BASE_URL.rstrip("/")
    if PUBLIC_BASE_URL_FORCE:
        return public

    try:
        if urlparse(public).netloc == urlparse(request_base).netloc:
            return public
    except Exception:
        pass

    return request_base


CONSENT_LINK_NOTE_PREFIX = "CONSENT_LINK_JSON:"


# ----------------------------
# E-mail (SMTP) - usado para links de aceite SCR nas Consultas
# ----------------------------

SMTP_HOST = os.getenv("SMTP_HOST", "").strip()
SMTP_PORT = int(os.getenv("SMTP_PORT", "587") or "587")
SMTP_USERNAME = os.getenv("SMTP_USERNAME", "").strip()
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "").strip()
SMTP_FROM = os.getenv("SMTP_FROM", "").strip() or SMTP_USERNAME
SMTP_USE_SSL = (os.getenv("SMTP_USE_SSL", "").strip() == "1") or (SMTP_PORT == 465)


def _smtp_send_email(*, to_email: str, subject: str, html_body: str, text_body: str = "") -> None:
    """Envia e-mail via SMTP.

    Requer variáveis de ambiente:
      - SMTP_HOST, SMTP_PORT
      - SMTP_USERNAME, SMTP_PASSWORD (se necessário)
      - SMTP_FROM (opcional; padrão SMTP_USERNAME)
    """
    if not SMTP_HOST or not SMTP_FROM:
        raise RuntimeError("SMTP não configurado (SMTP_HOST/SMTP_FROM ausentes).")

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = SMTP_FROM
    msg["To"] = to_email

    if text_body:
        msg.attach(MIMEText(text_body, "plain", "utf-8"))
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    if SMTP_USE_SSL:
        with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=20) as s:
            if SMTP_USERNAME and SMTP_PASSWORD:
                s.login(SMTP_USERNAME, SMTP_PASSWORD)
            s.sendmail(SMTP_FROM, [to_email], msg.as_string())
        return

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=20) as s:
        s.ehlo()
        try:
            s.starttls()
            s.ehlo()
        except Exception:
            pass
        if SMTP_USERNAME and SMTP_PASSWORD:
            s.login(SMTP_USERNAME, SMTP_PASSWORD)
        s.sendmail(SMTP_FROM, [to_email], msg.as_string())


def _pack_consent_link_note(*, token: str, created_by_user_id: int, expires_at: datetime) -> str:
    obj = {
        "token": token,
        "created_by_user_id": int(created_by_user_id or 0),
        "expires_at": expires_at.isoformat(),
        "term_version": CREDIT_CONSENT_TERM_VERSION,
    }
    return CONSENT_LINK_NOTE_PREFIX + json.dumps(obj, ensure_ascii=False)


def _unpack_consent_link_note(notes: str) -> Optional[dict[str, Any]]:
    s = (notes or "").strip()
    if not s.startswith(CONSENT_LINK_NOTE_PREFIX):
        return None
    raw = s[len(CONSENT_LINK_NOTE_PREFIX):].strip()
    try:
        obj = json.loads(raw)
        return obj if isinstance(obj, dict) else None
    except Exception:
        return None


INVITE_LINK_NOTE_PREFIX = "INVITE_LINK_JSON:"


def _sign_invite_token(payload: dict[str, Any]) -> str:
    """Assina token de convite (HMAC-SHA256) com APP_SECRET_KEY."""
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    b64 = _b64url_encode(raw)
    sig = _hmac_sha256_hex(APP_SECRET_KEY, raw)
    return f"{b64}.{sig}"


def _verify_invite_token(token: str) -> dict[str, Any]:
    """Valida token de convite e retorna payload (dict)."""
    tok = (token or "").strip()
    if "." not in tok:
        raise ValueError("token inválido")
    b64, sig = tok.split(".", 1)
    raw = _b64url_decode(b64)
    expected = _hmac_sha256_hex(APP_SECRET_KEY, raw)
    if not hmac.compare_digest(expected, sig):
        raise ValueError("assinatura inválida")
    payload = json.loads(raw.decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("payload inválido")
    exp = int(payload.get("exp") or 0)
    if exp and utcnow().timestamp() > exp:
        raise ValueError("token expirado")
    return payload


def _pack_invite_link_note(*, token: str, created_by_user_id: int, expires_at: datetime) -> str:
    obj = {
        "token": token,
        "created_by_user_id": int(created_by_user_id or 0),
        "expires_at": expires_at.isoformat(),
    }
    return INVITE_LINK_NOTE_PREFIX + json.dumps(obj, ensure_ascii=False)


def _unpack_invite_link_note(notes: str) -> Optional[dict[str, Any]]:
    s = (notes or "").strip()
    if not s.startswith(INVITE_LINK_NOTE_PREFIX):
        return None
    try:
        return json.loads(s[len(INVITE_LINK_NOTE_PREFIX):])
    except Exception:
        return None


def _build_invite_url(request: Request, *, token: str) -> str:
    base = _public_base_url(request)
    return f"{base}/convite/{token}".rstrip("/")


def _request_ip(request: Request) -> str:
    xf = request.headers.get("x-forwarded-for")
    if xf:
        return xf.split(",")[0].strip()
    if request.client:
        return request.client.host or ""
    return ""


def _terms_sha256() -> str:
    raw = f"{CREDIT_CONSENT_TERM_VERSION}|{CREDIT_CONSENT_TERMS_HTML}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


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

class UiBannerSlide(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    company_id: int = Field(index=True, foreign_key="company.id")
    title: str = Field(default="")
    image_url: str = Field(index=False)  # /static/banners/.. or external
    link_path: str = Field(default="/")
    sort_order: int = Field(default=0, index=True)
    is_active: bool = Field(default=True, index=True)
    created_at: datetime = Field(default_factory=utcnow)


class UiNewsFeed(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    company_id: int = Field(index=True, foreign_key="company.id")
    name: str
    url: str
    sort_order: int = Field(default=0, index=True)
    is_active: bool = Field(default=True, index=True)
    created_at: datetime = Field(default_factory=utcnow)

class AdminEntityState(SQLModel, table=True):
    """Admin-managed state for entities (soft deactivate/delete) without altering core tables.

    We avoid schema migrations by storing state in a separate table and treating missing rows as active.
    """
    __table_args__ = (UniqueConstraint("entity_type", "entity_id", name="uq_admin_entity_state"),)

    id: Optional[int] = Field(default=None, primary_key=True)
    entity_type: str = Field(index=True)  # company | client | membership | user
    entity_id: int = Field(index=True)
    company_id: Optional[int] = Field(default=None, index=True)

    is_active: bool = Field(default=True, index=True)
    is_deleted: bool = Field(default=False, index=True)

    updated_at: datetime = Field(default_factory=utcnow, index=True)
    updated_by_user_id: Optional[int] = Field(default=None, index=True)
    deleted_at: Optional[datetime] = Field(default=None, index=True)

class MembershipFeatureAccess(SQLModel, table=True):
    """Per-member feature visibility/access controls (JSON list of feature keys).

    Missing row or empty list => defaults by role.
    """
    __table_args__ = (UniqueConstraint("company_id", "membership_id", name="uq_member_feature_access"),)

    id: Optional[int] = Field(default=None, primary_key=True)
    company_id: int = Field(index=True)
    membership_id: int = Field(index=True)
    features_json: str = Field(default="")
    updated_at: datetime = Field(default_factory=utcnow, index=True)


class ClientFeatureAccess(SQLModel, table=True):
    """Per-client feature visibility/access controls (JSON list of feature keys).

    Applied only to role=cliente (and to memberships linked to this client).
    Missing row or empty list => defaults for client role.
    """
    __table_args__ = (UniqueConstraint("company_id", "client_id", name="uq_client_feature_access"),)

    id: Optional[int] = Field(default=None, primary_key=True)
    company_id: int = Field(index=True)
    client_id: int = Field(index=True)
    features_json: str = Field(default="")
    updated_at: datetime = Field(default_factory=utcnow, index=True)


class OnboardingDiagnostic(SQLModel, table=True):
    __table_args__ = (UniqueConstraint("user_id", "company_id", name="uq_diag_user_company"),)

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(index=True, foreign_key="user.id")
    company_id: int = Field(index=True, foreign_key="company.id")
    answers_json: str
    created_at: datetime = Field(default_factory=utcnow)


# ----------------------------
# Perfil: Snapshots (evolução)
# ----------------------------

class ClientSnapshot(SQLModel, table=True):
    """
    "Foto do momento" do cliente + score (evolução).
    Cada submissão vira um registro para compararmos ao longo do tempo.
    """
    id: Optional[int] = Field(default=None, primary_key=True)

    company_id: int = Field(index=True, foreign_key="company.id")
    client_id: int = Field(index=True, foreign_key="client.id")
    created_by_user_id: int = Field(index=True, foreign_key="user.id")

    # KPIs (foto do momento)
    revenue_monthly_brl: float = 0.0
    debt_total_brl: float = 0.0
    cash_balance_brl: float = 0.0
    employees_count: int = 0

    # Pesquisa
    nps_score: int = 0  # 0..10
    notes: str = ""

    # Respostas do checklist (JSON)
    answers_json: str = Field(default="{}")

    # Scores 0..100
    score_process: float = 0.0
    score_financial: float = 0.0
    score_total: float = 0.0

    created_at: datetime = Field(default_factory=utcnow)


PROFILE_SURVEY_V1 = [
    {"id": "dre_mensal", "section": "Processos", "q": "Você fecha DRE mensalmente?", "type": "bool", "w": 10},
    {"id": "fluxo_90d", "section": "Processos", "q": "Você tem fluxo de caixa projetado (90 dias)?", "type": "bool",
     "w": 12},
    {"id": "contas_pagar_receber", "section": "Processos", "q": "Contas a pagar/receber controladas diariamente?",
     "type": "bool", "w": 10},
    {"id": "conciliacao_bancaria", "section": "Processos", "q": "Você faz conciliação bancária (mínimo semanal)?",
     "type": "bool", "w": 8},
    {"id": "inadimplencia", "section": "Processos", "q": "Você mede inadimplência e tem rotina de cobrança?",
     "type": "bool", "w": 8},
    {"id": "dividas_mapa", "section": "Processos", "q": "Você tem mapa de dívidas (saldo, taxa, prazo)?",
     "type": "bool", "w": 10},
    {"id": "orcamento", "section": "Processos", "q": "Existe orçamento anual e acompanhamento mensal?", "type": "bool",
     "w": 10},
    {"id": "kpis", "section": "Processos", "q": "Você acompanha KPIs (margem, caixa, giro) com frequência?",
     "type": "bool", "w": 10},
    {"id": "precificacao", "section": "Processos", "q": "Você revisa precificação/margem periodicamente?",
     "type": "bool", "w": 8},
    {"id": "tributario_ok", "section": "Risco", "q": "Obrigações fiscais estão em dia?", "type": "bool", "w": 10},
    {"id": "contratos_ok", "section": "Risco", "q": "Contratos principais estão organizados e acessíveis?",
     "type": "bool", "w": 6},
    {"id": "centro_custo", "section": "Risco", "q": "Existe centro de custos / plano de contas estruturado?",
     "type": "bool", "w": 8},
]


def _clamp_0_100(x: float) -> float:
    return 0.0 if x < 0 else 100.0 if x > 100 else x


def _parse_bool(val: Any) -> bool:
    return str(val) in {"1", "true", "True", "on", "yes", "sim"}


def score_process_from_answers(answers: dict[str, Any]) -> float:
    total_w = sum(q["w"] for q in PROFILE_SURVEY_V1)
    if total_w <= 0:
        return 0.0
    got = 0.0
    for q in PROFILE_SURVEY_V1:
        if bool(answers.get(q["id"])):
            got += q["w"]
    return round((got / total_w) * 100.0, 2)


def score_financial_simple(revenue_monthly: float, debt_total: float, cash_balance: float) -> float:
    """
    Score financeiro simples (0..100) baseado em:
      - dívida / faturamento mensal (menor melhor)
      - caixa / faturamento mensal (maior melhor)
    """
    rev = max(0.0, float(revenue_monthly))
    if rev <= 0:
        return 0.0
    debt = max(0.0, float(debt_total))
    cash = max(0.0, float(cash_balance))

    debt_ratio = debt / max(1.0, rev)
    cash_ratio = cash / max(1.0, rev)

    debt_score = 100.0 * max(0.0, min(1.0, 1.0 / (1.0 + debt_ratio)))  # 0 => 100, 1 => 50
    cash_score = 100.0 * max(0.0, min(1.0, cash_ratio))  # 1 => 100

    return round((0.6 * debt_score + 0.4 * cash_score), 2)


def score_total(process_score: float, financial_score: float, nps_score: int) -> float:
    nps01 = max(0, min(10, int(nps_score))) / 10.0  # 0..1
    nps100 = nps01 * 100.0
    return round(_clamp_0_100(0.5 * float(process_score) + 0.4 * float(financial_score) + 0.1 * float(nps100)), 2)


# ----------------------------
# Documentos (contratos, termos etc.)
# ----------------------------

DOC_STATUSES = {"rascunho", "aguardando_cliente", "cliente_enviou", "concluido"}

CONSULT_PROJECT_STATUS = {"ativo", "pausado", "concluido"}

# ----------------------------
# Crédito (Direct Data - SCR Detalhada) + Autorização LGPD
# ----------------------------

CREDIT_CONSENT_KIND_SCR = "scr_directdata"
CREDIT_CONSENT_STATUSES = {"pendente", "valida", "expirada", "revogada"}
CREDIT_REPORT_STATUSES = {"processing", "done", "error"}

CREDIT_CONSENT_TERMS_HTML = r"""
<div class="small">
  <p><b>TERMO DE AUTORIZAÇÃO E CIÊNCIA (LGPD / SCR)</b></p>
  <p>
    Eu, titular dos dados, <b>autorizo</b> a realização de consulta e obtenção de informações em bases de crédito,
    incluindo o <b>Sistema de Informações de Crédito (SCR)</b> do Banco Central do Brasil, por meio de provedor
    contratado (ex.: Direct Data), para fins de análise de crédito e/ou formalização de operações.
  </p>
  <p>
    Declaro estar ciente de que meus dados pessoais poderão ser tratados para: (i) análise e proteção do crédito;
    (ii) prevenção a fraudes; (iii) cumprimento de obrigações legais/regulatórias; e (iv) registro e guarda de
    evidências desta autorização em meio eletrônico.
  </p>
  <p>
    Esta autorização é <b>específica</b> para consultas relacionadas ao meu cadastro, podendo ser revogada a qualquer momento,
    observado que consultas já realizadas e obrigações legais de guarda poderão permanecer.
  </p>
  <p class="muted">
    Versão do termo: {{ term_version }} • Data/hora do aceite (UTC) será registrada.
  </p>
</div>
"""


class CreditConsent(SQLModel, table=True):
    """
    Consentimento/LGPD para consulta de crédito (ex.: SCR via Direct Data).

    - O cliente pode enviar a autorização assinada (upload).
    - Admin/Equipe pode consultar SCR apenas quando houver consentimento válido.
    """
    id: Optional[int] = Field(default=None, primary_key=True)

    company_id: int = Field(index=True, foreign_key="company.id")
    client_id: int = Field(index=True, foreign_key="client.id")
    created_by_user_id: int = Field(index=True, foreign_key="user.id")

    kind: str = Field(default=CREDIT_CONSENT_KIND_SCR, index=True)
    status: str = Field(default="valida", index=True)

    signed_by_name: str = ""
    signed_by_document: str = ""  # CPF/CNPJ do signatário (opcional)
    signed_at: datetime = Field(default_factory=utcnow)
    expires_at: datetime = Field(default_factory=utcnow)

    notes: str = ""
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)




# ----------------------------
# Consultas (SCR) - Aceite por CPF/CNPJ (e-mail + clickwrap)
# ----------------------------

CONSULTA_CONSENT_KIND_SCR = "consultas_scr_directdata"
CONSULTA_CONSENT_STATUSES = {"pendente", "valida", "expirada", "revogada"}

# Produtos de SCR que exigem aceite do titular do CPF/CNPJ consultado.
SCR_CONSULTA_PRODUCT_CODES = {
    "directdata.scr_resumido",
    "directdata.scr_analitico",  # alias legado -> resumido
    "directdata.scr_detalhada",
}


class ConsultaScrConsent(SQLModel, table=True):
    """Aceite (LGPD/SCR) por CPF/CNPJ para liberar consultas SCR no módulo de Consultas.

    Fluxo:
      1) gerar link + enviar por e-mail
      2) titular acessa link -> clickwrap
      3) consulta liberada enquanto o aceite estiver válido

    Escopo: company_id + subject_doc (CPF/CNPJ consultado).
    """

    id: Optional[int] = Field(default=None, primary_key=True)

    company_id: int = Field(index=True, foreign_key="company.id")
    requested_by_client_id: int = Field(index=True, foreign_key="client.id")
    created_by_user_id: int = Field(index=True, foreign_key="user.id")

    subject_doc: str = Field(default="", index=True)  # CPF/CNPJ (somente dígitos)
    invited_email: str = Field(default="", index=True)

    status: str = Field(default="pendente", index=True)  # pendente|valida|expirada|revogada
    token_nonce: str = Field(default_factory=lambda: secrets.token_urlsafe(16), index=True)

    signed_by_name: str = ""
    signed_at: Optional[datetime] = None

    expires_at: datetime = Field(default_factory=utcnow)
    accepted_at: Optional[datetime] = None

    notes: str = ""
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class CreditReport(SQLModel, table=True):
    """
    Resultado (ou processamento) de uma consulta SCR.

    - status=processing: aguardando término (async)
    - status=done: JSON final armazenado
    - status=error: falha ao consultar
    """
    id: Optional[int] = Field(default=None, primary_key=True)

    company_id: int = Field(index=True, foreign_key="company.id")
    client_id: int = Field(index=True, foreign_key="client.id")
    created_by_user_id: int = Field(index=True, foreign_key="user.id")

    provider: str = Field(default="directdata", index=True)
    document_type: str = Field(default="cnpj", index=True)  # cnpj | cpf
    document_value: str = Field(default="", index=True)  # sem formatação

    async_enabled: bool = True

    status: str = Field(default="processing", index=True)
    http_status: int = 0
    message: str = ""

    consulta_uid: str = Field(default="", index=True)
    resultado_id: int = 0

    # Campos resumidos para UI
    score: str = ""
    faixa_risco: str = ""
    risco_total_brl: float = 0.0

    carteira_total_brl: float = 0.0
    carteira_vencer_brl: float = 0.0
    carteira_vencido_brl: float = 0.0
    carteira_prejuizo_brl: float = 0.0

    quantidade_instituicoes: int = 0
    quantidade_operacoes: int = 0

    obrigacao_assumida: str = ""
    obrigacao_resumida: str = ""

    potential_score: float = 0.0
    potential_label: str = Field(default="baixo", index=True)  # baixo|medio|alto

    raw_json: str = Field(default="")  # JSON completo (texto)

    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


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
    due_date: str = ""  # AAAA-MM-DD (MVP simples)

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


TASK_STATUS = {"nao_iniciada", "em_andamento", "concluida"}
TASK_PRIORITY = {"baixa", "media", "alta"}


class Task(SQLModel, table=True):
    """
    Tarefa vinculada a um cliente (e opcionalmente atribuída a um usuário).
    """
    id: Optional[int] = Field(default=None, primary_key=True)

    company_id: int = Field(index=True, foreign_key="company.id")
    client_id: int = Field(index=True, foreign_key="client.id")
    created_by_user_id: int = Field(index=True, foreign_key="user.id")
    assignee_user_id: Optional[int] = Field(default=None, index=True, foreign_key="user.id")

    title: str
    description: str = ""

    status: str = Field(default="nao_iniciada", index=True)  # nao_iniciada | em_andamento | concluida
    priority: str = Field(default="media", index=True)  # baixa | media | alta
    due_date: str = ""  # AAAA-MM-DD

    visible_to_client: bool = Field(default=False, index=True)
    client_action: bool = Field(default=False, index=True)  # cliente pode marcar como concluído?

    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class TaskComment(SQLModel, table=True):
    """
    Comentário de tarefa (timeline simples).
    """
    id: Optional[int] = Field(default=None, primary_key=True)

    task_id: int = Field(index=True, foreign_key="task.id")
    author_user_id: int = Field(index=True, foreign_key="user.id")
    message: str

    created_at: datetime = Field(default_factory=utcnow)


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
    service_name: str = Field(default="", index=True)  # produto/serviço
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

# ----------------------------
# CRM (Negócios / Funil)
# ----------------------------

CRM_STAGES = [
    {"key": "qualificacao", "label": "Qualificação", "order": 1},
    {"key": "criar_proposta", "label": "Criar Proposta", "order": 2},
    {"key": "proposta_enviada", "label": "Proposta Enviada", "order": 3},
    {"key": "negociacao", "label": "Em Negociação", "order": 4},
    {"key": "pausado", "label": "Pausado", "order": 5},
    {"key": "ganho", "label": "Fechado (Ganho)", "order": 6},
    {"key": "perdido", "label": "Fechado (Perdido)", "order": 7},
]

CRM_STAGE_KEYS = {s["key"] for s in CRM_STAGES}


class BusinessDeal(SQLModel, table=True):
    """Negócio (oportunidade) do CRM."""

    id: Optional[int] = Field(default=None, primary_key=True)

    company_id: int = Field(index=True, foreign_key="company.id")
    client_id: int = Field(index=True, foreign_key="client.id")
    created_by_user_id: int = Field(index=True, foreign_key="user.id")

    owner_user_id: Optional[int] = Field(default=None, index=True, foreign_key="user.id")

    title: str
    demand: str = ""  # demanda inicial
    notes: str = ""

    stage: str = Field(default="qualificacao", index=True)

    service_name: str = Field(default="", index=True)

    value_estimate_brl: float = 0.0
    probability_pct: int = 0  # 0..100

    next_step: str = ""
    next_step_date: str = ""  # AAAA-MM-DD

    source: str = ""  # origem

    # Ligações (opcionais)
    proposal_id: Optional[int] = Field(default=None, index=True, foreign_key="proposal.id")
    consulting_project_id: Optional[int] = Field(default=None, index=True, foreign_key="consultingproject.id")

    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class BusinessDealNote(SQLModel, table=True):
    """Notas/comentários do negócio."""

    id: Optional[int] = Field(default=None, primary_key=True)
    deal_id: int = Field(index=True, foreign_key="businessdeal.id")
    author_user_id: int = Field(index=True, foreign_key="user.id")

    message: str
    created_at: datetime = Field(default_factory=utcnow)


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

    task_id: Optional[int] = Field(default=None, index=True, foreign_key="task.id")
    education_lesson_id: Optional[int] = Field(default=None, index=True, foreign_key="educationlesson.id")
    credit_consent_id: Optional[int] = Field(default=None, index=True, foreign_key="creditconsent.id")
    credit_report_id: Optional[int] = Field(default=None, index=True, foreign_key="creditreport.id")

    original_filename: str
    stored_filename: str
    mime_type: str = "application/octet-stream"
    size_bytes: int = 0
    created_at: datetime = Field(default_factory=utcnow)


# ----------------------------
# DB
# ----------------------------


def ensure_ui_tables() -> None:
    """Create UI tables (banner/news) if missing.

    Safe to call on Postgres too (checkfirst=True) to avoid missing-table 500s when
    Alembic migrations were not applied.
    """
    try:
        SQLModel.metadata.create_all(
            engine,
            tables=[UiBannerSlide.__table__, UiNewsFeed.__table__, AdminEntityState.__table__],
            checkfirst=True,
        )
    except Exception:
        pass


def init_db() -> None:
    # Em produção (Postgres), quem cria/alterar tabelas é o Alembic.
    # Porém, para features novas sem migration (ex.: UI banner/notícias), garantimos as tabelas.
    ensure_ui_tables()
    # Em dev local (SQLite), criamos automaticamente tudo.
    if engine.url.get_backend_name().startswith("sqlite"):
        SQLModel.metadata.create_all(engine)


class ClientInvite(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    company_id: int = Field(index=True, foreign_key="company.id")
    client_id: int = Field(index=True, foreign_key="client.id")
    created_by_user_id: int = Field(index=True, foreign_key="user.id")

    invited_email: str = ""
    status: str = Field(default="pendente", index=True)  # pendente | aceito | revogado | expirado
    token_nonce: str = Field(default_factory=lambda: secrets.token_urlsafe(16), index=True)

    expires_at: datetime
    accepted_at: Optional[datetime] = None
    accepted_user_id: Optional[int] = Field(default=None, index=True, foreign_key="user.id")

    notes: str = ""
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


def ensure_client_invite_table() -> bool:
    """Garante que a tabela ClientInvite existe.

    Em produção (Postgres) o app pode rodar sem Alembic. Criar só esta tabela é
    idempotente (checkfirst=True). Se falhar (permissão), retornamos False e o
    deploy precisa de migração manual.
    """
    try:
        ClientInvite.__table__.create(engine, checkfirst=True)
        return True
    except Exception as e:
        try:
            print(f"[invite] failed to ensure ClientInvite table: {e}")
        except Exception:
            pass
        return False


def ensure_credit_consent_table() -> bool:
    """Garante que a tabela CreditConsent existe.

    Em produção (Postgres) o app pode rodar sem Alembic. Criar só esta tabela é
    idempotente (checkfirst=True). Se falhar (permissão), retornamos False e o
    deploy precisa de migração manual.
    """
    try:
        CreditConsent.__table__.create(engine, checkfirst=True)
        return True
    except Exception as e:
        try:
            print(f"[consent] failed to ensure CreditConsent table: {e}")
        except Exception:
            pass
        return False




def ensure_consulta_scr_consent_table() -> bool:
    """Garante que a tabela ConsultaScrConsent existe (ambientes sem Alembic)."""
    try:
        ConsultaScrConsent.__table__.create(engine, checkfirst=True)
        return True
    except Exception as e:
        try:
            print(f"[consulta-consent] failed to ensure ConsultaScrConsent table: {e}")
        except Exception:
            pass
        return False


def _refresh_consulta_scr_consent_status(consent: ConsultaScrConsent) -> None:
    try:
        now = utcnow()
        if consent.status in {"pendente", "valida"} and _as_aware_utc(consent.expires_at) < now:
            consent.status = "expirada"
    except Exception:
        pass


def _get_latest_consulta_scr_consent(session: Session, *, company_id: int, subject_doc: str) -> Optional[ConsultaScrConsent]:
    d = _digits_only(subject_doc)
    if not d:
        return None
    return session.exec(
        select(ConsultaScrConsent)
        .where(ConsultaScrConsent.company_id == int(company_id), ConsultaScrConsent.subject_doc == d)
        .order_by(ConsultaScrConsent.created_at.desc())
    ).first()


def _has_valid_consulta_scr_consent(session: Session, *, company_id: int, subject_doc: str) -> bool:
    c = _get_latest_consulta_scr_consent(session, company_id=int(company_id), subject_doc=subject_doc)
    if not c:
        return False
    _refresh_consulta_scr_consent_status(c)
    return c.status == "valida"


def _is_scr_consulta_product(code: str) -> bool:
    return (code or "").strip() in SCR_CONSULTA_PRODUCT_CODES
# ----------------------------
# Integração: Conta Azul (OAuth + Sync)
# ----------------------------

class ContaAzulAuth(SQLModel, table=True):
    __table_args__ = (UniqueConstraint("company_id", name="uq_contaazul_company"),)

    id: Optional[int] = Field(default=None, primary_key=True)
    company_id: int = Field(index=True, foreign_key="company.id")

    access_token: str = ""
    refresh_token: str = ""
    token_type: str = "Bearer"
    expires_at: datetime = Field(default_factory=utcnow)

    last_sync_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class ContaAzulPersonMap(SQLModel, table=True):
    __table_args__ = (UniqueConstraint("company_id", "client_id", name="uq_contaazul_personmap"),)

    id: Optional[int] = Field(default=None, primary_key=True)
    company_id: int = Field(index=True, foreign_key="company.id")
    client_id: int = Field(index=True, foreign_key="client.id")

    contaazul_person_id: str = Field(default="", index=True)
    documento: str = ""
    email: str = ""

    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class ContaAzulInvoice(SQLModel, table=True):
    __table_args__ = (UniqueConstraint("company_id", "invoice_type", "external_id", name="uq_contaazul_invoice"),)

    id: Optional[int] = Field(default=None, primary_key=True)
    company_id: int = Field(index=True, foreign_key="company.id")
    client_id: int = Field(index=True, foreign_key="client.id")

    invoice_type: str = Field(index=True)  # NFE | NFSE
    external_id: str = Field(index=True)  # chave_acesso (NFE) ou uuid (NFSE)
    number: str = ""
    issue_date: str = ""  # ISO string
    status: str = Field(default="", index=True)
    amount: float = 0.0

    raw_json: str = ""
    updated_at: datetime = Field(default_factory=utcnow)


class ContaAzulReceivable(SQLModel, table=True):
    __table_args__ = (UniqueConstraint("company_id", "installment_id", name="uq_contaazul_receivable"),)

    id: Optional[int] = Field(default=None, primary_key=True)
    company_id: int = Field(index=True, foreign_key="company.id")
    client_id: int = Field(index=True, foreign_key="client.id")

    installment_id: str = Field(index=True)  # uuid
    description: str = ""
    due_date: str = ""
    status: str = Field(default="", index=True)

    amount_total: float = 0.0
    amount_open: float = 0.0
    amount_paid: float = 0.0

    payment_method: str = ""
    invoice_type: str = ""  # NFE | NFSE | ...
    invoice_number: str = ""

    boleto_status: str = ""
    payment_url: str = ""

    raw_json: str = ""
    updated_at: datetime = Field(default_factory=utcnow)


def ensure_contaazul_tables() -> bool:
    try:
        ContaAzulAuth.__table__.create(engine, checkfirst=True)
        ContaAzulPersonMap.__table__.create(engine, checkfirst=True)
        ContaAzulInvoice.__table__.create(engine, checkfirst=True)
        ContaAzulReceivable.__table__.create(engine, checkfirst=True)
        return True
    except Exception as e:
        try:
            print(f"[contaazul] failed to ensure tables: {e}")
        except Exception:
            pass
        return False


def _contaazul_configured() -> bool:
    return bool(CONTA_AZUL_CLIENT_ID and CONTA_AZUL_CLIENT_SECRET)


def _ca_log(msg: str) -> None:
    if CONTA_AZUL_DEBUG:
        try:
            print(f"[contaazul] {msg}")
        except Exception:
            pass


def _ca_trunc(text: str, max_len: int = 700) -> str:
    s = (text or "").strip().replace("\n", " ").replace("\r", " ")
    return s if len(s) <= max_len else (s[:max_len] + "…")


def _contaazul_basic_auth_value() -> str:
    raw = f"{CONTA_AZUL_CLIENT_ID}:{CONTA_AZUL_CLIENT_SECRET}".encode("utf-8")
    return base64.b64encode(raw).decode("utf-8")


def _contaazul_redirect_uri(request: Request) -> str:
    return _public_base_url(request).rstrip("/") + "/integrations/contaazul/callback"


def _extract_first_url(text: str) -> str:
    if not text:
        return ""
    m = re.search(r"(https?://\S+)", text)
    return (m.group(1).rstrip(").,;") if m else "")


def _contaazul_get_auth(session: Session, company_id: int) -> Optional[ContaAzulAuth]:
    return session.exec(select(ContaAzulAuth).where(ContaAzulAuth.company_id == company_id)).first()


def _contaazul_save_auth(session: Session, auth: ContaAzulAuth) -> None:
    auth.updated_at = utcnow()
    session.add(auth)
    session.commit()


def _contaazul_refresh(session: Session, auth: ContaAzulAuth) -> ContaAzulAuth:
    headers = {
        "Authorization": f"Basic {_contaazul_basic_auth_value()}",
        "Content-Type": "application/x-www-form-urlencoded",
    }
    data = {"grant_type": "refresh_token", "refresh_token": auth.refresh_token}
    with httpx.Client(timeout=30.0, follow_redirects=True) as client:
        resp = client.post(CONTA_AZUL_TOKEN_URL, headers=headers, data=data)
    if resp.status_code >= 400:
        raise RuntimeError(f"Conta Azul refresh failed: HTTP {resp.status_code} {resp.text[:400]}")
    payload = resp.json()
    auth.access_token = str(payload.get("access_token") or "")
    auth.refresh_token = str(payload.get("refresh_token") or auth.refresh_token)
    auth.token_type = str(payload.get("token_type") or "Bearer")
    exp = int(payload.get("expires_in") or 3600)
    auth.expires_at = utcnow() + timedelta(seconds=max(60, exp))
    _contaazul_save_auth(session, auth)
    return auth


def _contaazul_bearer_headers(session: Session, company_id: int) -> dict[str, str]:
    auth = _contaazul_get_auth(session, company_id)
    if not auth or not auth.access_token or not auth.refresh_token:
        raise RuntimeError("Conta Azul não conectada.")

    exp_at = _as_aware_utc(auth.expires_at) or utcnow()
    if utcnow() >= (exp_at - timedelta(seconds=60)):
        auth = _contaazul_refresh(session, auth)
    return {"Authorization": f"Bearer {auth.access_token}"}


def _contaazul_get_json(session: Session, company_id: int, path: str, params: Any = None) -> Any:
    base = CONTA_AZUL_API_BASE.rstrip("/")
    url = base + path
    headers = _contaazul_bearer_headers(session, company_id)
    with httpx.Client(timeout=30.0, follow_redirects=True) as client:
        resp = client.get(url, headers=headers, params=params)
        if resp.status_code == 401:
            auth = _contaazul_get_auth(session, company_id)
            if auth:
                _contaazul_refresh(session, auth)
            headers = _contaazul_bearer_headers(session, company_id)
            resp = client.get(url, headers=headers, params=params)
    if resp.status_code >= 400:
        raise RuntimeError(f"Conta Azul API error: GET {path} HTTP {resp.status_code} {resp.text[:400]}")
    return resp.json()


def _contaazul_get_mapped_person_id(session: Session, *, company_id: int, client_id: int) -> str:
    pm = session.exec(
        select(ContaAzulPersonMap).where(
            ContaAzulPersonMap.company_id == company_id, ContaAzulPersonMap.client_id == client_id
        )
    ).first()
    return str((pm.contaazul_person_id or "") if pm else "").strip()


def _contaazul_find_person_id(session: Session, *, company_id: int, client: Client) -> str:
    doc = _digits_only(client.cnpj)
    if doc:
        payload = _contaazul_get_json(
            session,
            company_id,
            "/v1/pessoas",
            params={"documentos": doc, "tamanho_pagina": 10, "pagina": 1, "tipo_perfil": "Cliente"},
        )
        items = (payload.get("items") or []) if isinstance(payload, dict) else []
        if items:
            return str(items[0].get("id") or "")
    email = (client.finance_email or client.email or "").strip()
    if email:
        payload = _contaazul_get_json(
            session,
            company_id,
            "/v1/pessoas",
            params={"emails": email, "tamanho_pagina": 10, "pagina": 1, "tipo_perfil": "Cliente"},
        )
        items = (payload.get("items") or []) if isinstance(payload, dict) else []
        if items:
            return str(items[0].get("id") or "")
    return ""


def _contaazul_upsert_person_map(session: Session, *, company_id: int, client: Client, person_id: str) -> None:
    pm = session.exec(
        select(ContaAzulPersonMap).where(
            ContaAzulPersonMap.company_id == company_id, ContaAzulPersonMap.client_id == client.id
        )
    ).first()
    if not pm:
        pm = ContaAzulPersonMap(company_id=company_id, client_id=client.id, contaazul_person_id=person_id)
    pm.contaazul_person_id = person_id
    pm.documento = _digits_only(client.cnpj)
    pm.email = (client.finance_email or client.email or "").strip()
    pm.updated_at = utcnow()
    session.add(pm)
    session.commit()


def contaazul_sync_client_job(company_id: int, client_id: int) -> None:
    """Sincroniza boletos/receitas e notas do Conta Azul para o Financeiro do cliente.

    Observação importante: o mapeamento do "cliente" no Conta Azul (Pessoa) pode falhar se o
    documento/e-mail estiver diferente. Neste caso, fazemos fallback por documento (quando possível)
    para NFS-e e registramos logs (quando CONTA_AZUL_DEBUG=1)."""

    if not _contaazul_configured():
        return

    with Session(engine) as session:
        if not ensure_contaazul_tables():
            _ca_log("tables missing; abort")
            return

        auth = _contaazul_get_auth(session, company_id)
        if not auth or not auth.refresh_token:
            _ca_log("not connected; abort")
            return

        client = session.get(Client, client_id)
        if not client or client.company_id != company_id:
            _ca_log(f"client not found or not in company: client_id={client_id}")
            return

        doc = _digits_only(client.cnpj)
        email = (client.finance_email or client.email or "").strip()

        person_id = (
                _contaazul_get_mapped_person_id(session, company_id=company_id, client_id=client.id)
                or _contaazul_find_person_id(session, company_id=company_id, client=client)
        )
        if not person_id:
            _ca_log(f"person not found for client_id={client_id} doc={doc or '—'} email={email or '—'}")
        else:
            _contaazul_upsert_person_map(session, company_id=company_id, client=client, person_id=person_id)

        today = utcnow().date()
        start_venc = today - timedelta(days=max(1, int(CONTA_AZUL_SYNC_DAYS_BACK)))
        end_venc = today + timedelta(days=max(0, int(CONTA_AZUL_SYNC_DAYS_FORWARD)))

        # ----------------------------
        # Contas a receber / Parcelas
        # ----------------------------
        if person_id:
            installment_ids: list[str] = []
            page = 1
            page_size = 100
            while len(installment_ids) < CONTA_AZUL_SYNC_MAX_ITEMS:
                params = [
                    ("pagina", page),
                    ("tamanho_pagina", page_size),
                    ("data_vencimento_de", start_venc.isoformat()),
                    ("data_vencimento_ate", end_venc.isoformat()),
                    ("ids_clientes", person_id),
                ]
                try:
                    payload = _contaazul_get_json(
                        session,
                        company_id,
                        "/v1/financeiro/eventos-financeiros/contas-a-receber/buscar",
                        params=params,
                    )
                except Exception as e:
                    _ca_log(f"receivables search failed: {e}")
                    break

                itens = (payload.get("itens") or []) if isinstance(payload, dict) else []
                if not itens:
                    break

                for it in itens:
                    iid = str((it or {}).get("id") or "").strip()
                    if iid:
                        installment_ids.append(iid)
                    if len(installment_ids) >= CONTA_AZUL_SYNC_MAX_ITEMS:
                        break
                page += 1

            _ca_log(f"receivables: found {len(installment_ids)} parcelas for person_id={person_id}")

            for iid in installment_ids:
                try:
                    det = _contaazul_get_json(session, company_id, f"/v1/financeiro/eventos-financeiros/parcelas/{iid}")
                except Exception as e:
                    _ca_log(f"failed installment {iid}: {e}")
                    continue

                if not isinstance(det, dict):
                    continue

                fatura = det.get("fatura") or {}
                invoice_type = str(fatura.get("tipo_fatura") or "")
                invoice_number = str(fatura.get("numero") or "")

                boleto_status = ""
                payment_url = ""
                solicitacoes = det.get("solicitacoes_cobrancas") or []
                if isinstance(solicitacoes, list) and solicitacoes:
                    last = solicitacoes[-1] if isinstance(solicitacoes[-1], dict) else {}
                    boleto_status = str(last.get("status_solicitacao_cobranca") or "")
                    notif = last.get("notificacao_cobranca") or {}
                    body = str(notif.get("corpo") or "")
                    payment_url = _extract_first_url(body)

                rec = session.exec(
                    select(ContaAzulReceivable).where(
                        ContaAzulReceivable.company_id == company_id, ContaAzulReceivable.installment_id == iid
                    )
                ).first()
                if not rec:
                    rec = ContaAzulReceivable(company_id=company_id, client_id=client_id, installment_id=iid)

                rec.client_id = client_id
                rec.description = str(det.get("descricao") or "")
                rec.due_date = str(det.get("data_vencimento") or "")
                rec.status = str(det.get("status") or "")
                rec.amount_total = float(det.get("valor_total_liquido") or 0.0)
                rec.amount_open = float(det.get("nao_pago") or 0.0)
                rec.amount_paid = float(det.get("valor_pago") or 0.0)
                rec.payment_method = str(det.get("metodo_pagamento") or "")
                rec.invoice_type = invoice_type
                rec.invoice_number = invoice_number
                rec.boleto_status = boleto_status
                rec.payment_url = payment_url
                rec.raw_json = json.dumps(det, ensure_ascii=False)
                rec.updated_at = utcnow()
                session.add(rec)
                session.commit()

        # ----------------------------
        # Notas fiscais de serviço (NFS-e)
        # ----------------------------
        nfse_saved = 0
        nfse_days = max(1, int(CONTA_AZUL_SYNC_DAYS_BACK))
        cursor = today - timedelta(days=nfse_days)
        while cursor <= today and nfse_saved < CONTA_AZUL_SYNC_MAX_ITEMS:
            w_start = cursor
            w_end = min(today, cursor + timedelta(days=14))  # docs: range máximo 15 dias
            base_params = [
                ("tamanho_pagina", 100),
                ("data_competencia_de", w_start.isoformat()),
                ("data_competencia_ate", w_end.isoformat()),
            ]

            def _fetch_nfse_page(page_no: int, *, use_person: bool) -> list[dict[str, Any]]:
                params = [("pagina", page_no)] + base_params
                if use_person and person_id:
                    params.append(("id_cliente", person_id))
                payload = _contaazul_get_json(session, company_id, "/v1/notas-fiscais-servico", params=params)
                return (payload.get("itens") or []) if isinstance(payload, dict) else []

            page = 1
            window_items: list[dict[str, Any]] = []
            # primeiro tenta com person_id (se houver)
            if person_id:
                while nfse_saved < CONTA_AZUL_SYNC_MAX_ITEMS:
                    try:
                        itens = _fetch_nfse_page(page, use_person=True)
                    except Exception as e:
                        _ca_log(f"nfse fetch (person) failed {w_start}..{w_end}: {e}")
                        itens = []
                    if not itens:
                        break
                    window_items.extend([it for it in itens if isinstance(it, dict)])
                    if len(itens) < 100:
                        break
                    page += 1

            # por CNPJ/CPF (doc): o endpoint NÃO filtra por documento, então buscamos no período e filtramos localmente.
            # (garante que o vínculo seja sempre o documento, mesmo que person_id esteja errado/desatualizado)
            if doc:
                seen_ids = {str(it.get("id") or "") for it in window_items if isinstance(it, dict)}
                page = 1
                while nfse_saved < CONTA_AZUL_SYNC_MAX_ITEMS:
                    try:
                        itens = _fetch_nfse_page(page, use_person=False)
                    except Exception as e:
                        _ca_log(f"nfse fetch (doc filter) failed {w_start}..{w_end}: {e}")
                        break
                    if not itens:
                        break
                    for it in itens:
                        if not isinstance(it, dict):
                            continue
                        if _digits_only(str(it.get("documento_cliente") or "")) != doc:
                            continue
                        ext = str(it.get("id") or "")
                        if not ext or ext in seen_ids:
                            continue
                        window_items.append(it)
                        seen_ids.add(ext)
                    if len(itens) < 100:
                        break
                    page += 1

            if window_items:
                _ca_log(f"nfse window {w_start}..{w_end}: {len(window_items)} itens")
            for it in window_items:
                ext_id = str(it.get("id") or "")
                if not ext_id:
                    continue
                inv = session.exec(
                    select(ContaAzulInvoice).where(
                        ContaAzulInvoice.company_id == company_id,
                        ContaAzulInvoice.invoice_type == "NFSE",
                        ContaAzulInvoice.external_id == ext_id,
                    )
                ).first()
                if not inv:
                    inv = ContaAzulInvoice(company_id=company_id, client_id=client_id, invoice_type="NFSE",
                                           external_id=ext_id)

                inv.client_id = client_id
                inv.number = str(it.get("numero_nfse") or "")
                inv.issue_date = str(it.get("data_competencia") or "")
                inv.status = str(it.get("status") or "")
                inv.amount = float(it.get("valor_total_nfse") or 0.0)
                inv.raw_json = json.dumps(it, ensure_ascii=False)
                inv.updated_at = utcnow()
                session.add(inv)
                session.commit()
                nfse_saved += 1
                if nfse_saved >= CONTA_AZUL_SYNC_MAX_ITEMS:
                    break

            cursor = w_end + timedelta(days=1)

        # ----------------------------
        # Notas fiscais de produto (NF-e)
        # ----------------------------
        nfe_saved = 0
        if doc:
            cursor = today - timedelta(days=max(1, int(CONTA_AZUL_SYNC_DAYS_BACK)))
            while cursor <= today and (nfse_saved + nfe_saved) < CONTA_AZUL_SYNC_MAX_ITEMS:
                w_start = cursor
                w_end = min(today, cursor + timedelta(days=29))
                page = 1
                while (nfse_saved + nfe_saved) < CONTA_AZUL_SYNC_MAX_ITEMS:
                    params = {
                        "data_inicial": w_start.isoformat(),
                        "data_final": w_end.isoformat(),
                        "documento_tomador": doc,
                        "pagina": page,
                        "tamanho_pagina": 100,
                    }
                    try:
                        payload = _contaazul_get_json(session, company_id, "/v1/notas-fiscais", params=params)
                    except Exception as e:
                        _ca_log(f"nfe fetch failed {w_start}..{w_end}: {e}")
                        break

                    itens = (payload.get("itens") or []) if isinstance(payload, dict) else []
                    if not itens:
                        break

                    for it in itens:
                        if not isinstance(it, dict):
                            continue
                        chave = str(it.get("chave_acesso") or it.get("chave") or "").strip()
                        if not chave:
                            continue
                        inv = session.exec(
                            select(ContaAzulInvoice).where(
                                ContaAzulInvoice.company_id == company_id,
                                ContaAzulInvoice.invoice_type == "NFE",
                                ContaAzulInvoice.external_id == chave,
                            )
                        ).first()
                        if not inv:
                            inv = ContaAzulInvoice(company_id=company_id, client_id=client_id, invoice_type="NFE",
                                                   external_id=chave)
                        inv.client_id = client_id
                        inv.number = str(it.get("numero_nota") or it.get("numero") or "")
                        inv.issue_date = str(it.get("data_emissao") or "")
                        inv.status = str(it.get("status") or "")
                        inv.amount = 0.0
                        inv.raw_json = json.dumps(it, ensure_ascii=False)
                        inv.updated_at = utcnow()
                        session.add(inv)
                        session.commit()
                        nfe_saved += 1
                        if (nfse_saved + nfe_saved) >= CONTA_AZUL_SYNC_MAX_ITEMS:
                            break

                    if len(itens) < 100:
                        break
                    page += 1

                cursor = w_end + timedelta(days=1)

        _ca_log(f"sync done client_id={client_id}: nfse={nfse_saved} nfe={nfe_saved}")

        auth.last_sync_at = utcnow()
        _contaazul_save_auth(session, auth)


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


def _move_stage_to_order(session: Session, stage: "ConsultingStage", new_order: int) -> None:
    """Move stage within its project to `new_order` (1-based), normalizing all orders."""
    new_order = int(new_order or stage.order or 1)

    stages = session.exec(
        select(ConsultingStage)
        .where(ConsultingStage.project_id == stage.project_id)
        .order_by(ConsultingStage.order.asc(), ConsultingStage.id.asc())
    ).all()

    ids = [s.id for s in stages if s.id != stage.id]
    if not ids:
        stage.order = 1
        session.add(stage)
        session.commit()
        return

    new_order = max(1, min(new_order, len(ids) + 1))
    ids.insert(new_order - 1, stage.id)

    desired = {sid: idx + 1 for idx, sid in enumerate(ids)}
    for s in stages:
        s.order = desired.get(s.id, s.order)
        session.add(s)

    session.commit()




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

    if not entity_is_allowed(session, entity_type="user", entity_id=user.id):
        return None
    if not entity_is_allowed(session, entity_type="company", entity_id=company.id):
        return None
    if membership.id is not None and not entity_is_allowed(session, entity_type="membership", entity_id=membership.id):
        return None

    if membership.role == "cliente" and membership.client_id and not entity_is_allowed(session, entity_type="client", entity_id=membership.client_id):
        return None

    return TenantContext(user=user, company=company, membership=membership)

SUPERADMIN_EMAILS: set[str] = {
    e.strip().lower() for e in (os.getenv("SUPERADMIN_EMAILS", "") or "").split(",") if e.strip()
}


def is_superadmin(user: User) -> bool:
    """Global superadmin (optional). Set SUPERADMIN_EMAILS='a@b.com,c@d.com'."""
    return (user.email or "").strip().lower() in SUPERADMIN_EMAILS if SUPERADMIN_EMAILS else False


def _get_state(session: Session, *, entity_type: str, entity_id: int) -> Optional[AdminEntityState]:
    return session.exec(
        select(AdminEntityState).where(
            AdminEntityState.entity_type == entity_type,
            AdminEntityState.entity_id == int(entity_id),
        )
    ).first()


def entity_is_allowed(session: Session, *, entity_type: str, entity_id: int) -> bool:
    """Missing row => allowed."""
    st = _get_state(session, entity_type=entity_type, entity_id=entity_id)
    if not st:
        return True
    if st.is_deleted:
        return False
    return bool(st.is_active)


def set_entity_state(
    session: Session,
    *,
    entity_type: str,
    entity_id: int,
    company_id: Optional[int],
    is_active: Optional[bool] = None,
    is_deleted: Optional[bool] = None,
    updated_by_user_id: Optional[int] = None,
) -> AdminEntityState:
    st = _get_state(session, entity_type=entity_type, entity_id=entity_id)
    if not st:
        st = AdminEntityState(entity_type=entity_type, entity_id=int(entity_id), company_id=company_id)
    if is_active is not None:
        st.is_active = bool(is_active)
    if is_deleted is not None:
        st.is_deleted = bool(is_deleted)
        if st.is_deleted:
            st.deleted_at = utcnow()
            st.is_active = False
        else:
            st.deleted_at = None
    st.updated_at = utcnow()
    st.updated_by_user_id = updated_by_user_id
    session.add(st)
    session.commit()
    session.refresh(st)
    return st


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


FEATURE_KEYS: dict[str, dict[str, str]] = {
    "ui": {"title": "UI", "desc": "Banner e notícias (admin).", "href": "/admin/ui"},
    "gestao": {"title": "Gestão", "desc": "Ativar/inativar/excluir clientes/membros.", "href": "/admin/gestao"},
    "crm": {"title": "CRM", "desc": "Negócios e funil comercial.", "href": "/negocios"},
    "credito": {"title": "Crédito", "desc": "SCR (Direct Data).", "href": "/credito"},
    "consultas": {"title": "Consultas", "desc": "Consultas de crédito (créditos).", "href": "/consultas"},
    "creditos": {"title": "Créditos", "desc": "Saldo e recargas para consultas.", "href": "/creditos"},
    "empresa": {"title": "Empresa", "desc": "Dados completos do cliente.", "href": "/empresa"},
    "perfil": {"title": "Perfil", "desc": "Indicadores do cliente.", "href": "/perfil"},
    "financeiro": {"title": "Financeiro", "desc": "Notas/boletos de honorários.", "href": "/financeiro"},
    "documentos": {"title": "Documentos", "desc": "Contratos e docs importantes.", "href": "/documentos"},
    "consultoria": {"title": "Consultoria", "desc": "Projetos, etapas e progresso.", "href": "/consultoria"},
    "reunioes": {"title": "Reuniões", "desc": "Atas e notas (Notion).", "href": "/reunioes"},
    "tarefas": {"title": "Tarefas", "desc": "Kanban e prazos.", "href": "/tarefas"},
    "simulador": {"title": "Simulador", "desc": "Simulação de empréstimos (PDF).", "href": "/simulador"},
    "propostas": {"title": "Propostas", "desc": "Propostas e solicitações.", "href": "/propostas"},
    "pendencias": {"title": "Pendências", "desc": "Checklist / pedidos de documentos.", "href": "/pendencias"},
    "agenda": {"title": "Agenda", "desc": "Agendamentos (Bookings).", "href": "/agenda"},
    "educacao": {"title": "Educação", "desc": "Cursos e materiais.", "href": "/educacao"},
}

# Open Finance (Pluggy)
FEATURE_KEYS.setdefault(
    "openfinance",
    {
        "title": "Open Finance",
        "desc": "Contratos de crédito (Klavi / Open Finance).",
        "href": "/openfinance",
    },
)


FEATURE_GROUPS: list[dict[str, Any]] = [
    {"key": "admin", "title": "Admin", "features": ["ui", "gestao", "parceiros", "credito", "crm"]},
    {"key": "minha_empresa", "title": "Minha Empresa", "features": ["empresa", "perfil", "financeiro", "documentos", "consultas", "openfinance", "creditos"]},
    {"key": "meu_projeto", "title": "Meu Projeto", "features": ["consultoria", "reunioes", "tarefas"]},
    {"key": "minhas_propostas", "title": "Minhas Propostas", "features": ["simulador", "propostas"]},
]

FEATURE_STANDALONE: list[str] = ["pendencias", "agenda", "educacao"]

FEATURE_VISIBLE_ROLES: dict[str, set[str]] = {
    "ui": {"admin"},
    "gestao": {"admin"},
    "crm": {"admin", "equipe"},
}

ROLE_DEFAULT_FEATURES: dict[str, set[str]] = {
    "admin": set(FEATURE_KEYS.keys()),
    "equipe": set(FEATURE_KEYS.keys()),
    "cliente": set(FEATURE_KEYS.keys()) - {"ui", "gestao", "crm"},
}

ROLE_DEFAULT_FEATURES["admin"].add("openfinance")
ROLE_DEFAULT_FEATURES["equipe"].add("openfinance")

FEATURE_KEYS.setdefault(
    "parceiros",
    {
        "title": "Parceiros / Produtos",
        "desc": "Cadastro de parceiros, produtos, regras e defaults do simulador.",
        "href": "/admin/parceiros",
    },
)
FEATURE_VISIBLE_ROLES.setdefault("parceiros", {"admin"})
ROLE_DEFAULT_FEATURES["admin"].add("parceiros")

FEATURE_KEYS.setdefault(
    "servicos_internos",
    {
        "title": "Produtos Internos",
        "desc": "Catálogo de Advisory, IB, BaaS e Special Sits.",
        "href": "/admin/servicos-internos",
    },
)
FEATURE_KEYS.setdefault(
    "motor_ofertas",
    {
        "title": "Motor de Ofertas",
        "desc": "Ranking de produtos e parceiros por cliente.",
        "href": "/motor-ofertas",
    },
)
FEATURE_KEYS.setdefault(
    "ofertas",
    {
        "title": "Ofertas",
        "desc": "Ofertas recomendadas para o cliente.",
        "href": "/ofertas",
    },
)
FEATURE_VISIBLE_ROLES.setdefault("servicos_internos", {"admin"})
FEATURE_VISIBLE_ROLES.setdefault("motor_ofertas", {"admin", "equipe"})
FEATURE_VISIBLE_ROLES.setdefault("ofertas", {"admin", "equipe", "cliente"})
ROLE_DEFAULT_FEATURES["admin"].update({"servicos_internos", "motor_ofertas", "ofertas"})
ROLE_DEFAULT_FEATURES["equipe"].update({"motor_ofertas", "ofertas"})
ROLE_DEFAULT_FEATURES["cliente"].add("ofertas")

# Open Finance (Pluggy) - Loans module
# ----------------------------

PLUGGY_API_BASE = (os.getenv("PLUGGY_API_BASE") or "https://api.pluggy.ai").rstrip("/")
PLUGGY_CLIENT_ID = (os.getenv("PLUGGY_CLIENT_ID") or "").strip()
PLUGGY_CLIENT_SECRET = (os.getenv("PLUGGY_CLIENT_SECRET") or "").strip()
PLUGGY_INCLUDE_SANDBOX = os.getenv("PLUGGY_INCLUDE_SANDBOX", "0") == "1"
PLUGGY_CONNECT_JS_URL = (os.getenv("PLUGGY_CONNECT_JS_URL") or "https://cdn.pluggy.ai/pluggy-connect/v2.8.2/pluggy-connect.js").strip()
PLUGGY_HTTP_TIMEOUT_S = float(os.getenv("PLUGGY_HTTP_TIMEOUT_S", "20") or "20")
# ----------------------------
# Open Finance (Klavi) - Link/Consents + Loans report
# ----------------------------

KLAVI_ENV = (os.getenv("KLAVI_ENV") or "sandbox").strip().lower()
KLAVI_API_BASE = (os.getenv("KLAVI_API_BASE") or ("https://api-sandbox.klavi.ai" if KLAVI_ENV == "sandbox" else "https://api.klavi.ai")).rstrip("/")
KLAVI_ACCESS_KEY = (os.getenv("KLAVI_ACCESS_KEY") or "").strip()
KLAVI_SECRET_KEY = (os.getenv("KLAVI_SECRET_KEY") or "").strip()
KLAVI_HTTP_TIMEOUT_S = float(os.getenv("KLAVI_HTTP_TIMEOUT_S", "25") or "25")

def _klavi_normalize_phone(phone: str) -> str:
    """Normaliza telefone para E.164 no padrão BR (+55...).

    A API do Klavi pode retornar HTTP 400 "Invalid phone" quando o campo `phone`
    está fora do padrão. Como o campo é opcional, em caso de falha o caller deve
    omitir `phone` do payload.
    """
    raw = (phone or "").strip()
    if not raw:
        return ""

    digits = _digits(raw).lstrip("0")
    if not digits:
        raise ValueError("Invalid phone")

    # Open Finance Brasil: +55 + DDD + número (10 ou 11 dígitos após 55)
    if digits.startswith("55"):
        rest = digits[2:]
        if len(rest) not in (10, 11):
            raise ValueError("Invalid phone")
        digits = "55" + rest
    else:
        if len(digits) in (10, 11):
            digits = "55" + digits
        else:
            raise ValueError("Invalid phone")

    e164 = "+" + digits
    if not re.fullmatch(r"\+55\d{10,11}", e164):
        raise ValueError("Invalid phone")
    return e164

PLUGGY_WEBHOOK_KEY = (os.getenv("PLUGGY_WEBHOOK_KEY") or "").strip()
PLUGGY_WEBHOOK_TRUSTED_IPS = {
    ip.strip() for ip in (os.getenv("PLUGGY_WEBHOOK_TRUSTED_IPS") or "177.71.238.212").split(",") if ip.strip()
}


def _get_request_ip(request: Request) -> str:
    xff = request.headers.get("x-forwarded-for") or ""
    if xff:
        return xff.split(",")[0].strip()
    return (request.client.host if request.client else "") or ""


FEATURE_KEYS.setdefault(
    "openfinance",
    {"title": "Open Finance", "desc": "Contratos/Empréstimos (Klavi).", "href": "/openfinance"},
)
FEATURE_VISIBLE_ROLES.setdefault("openfinance", {"admin", "equipe", "cliente"})
for _r in ("admin", "equipe", "cliente"):
    ROLE_DEFAULT_FEATURES.setdefault(_r, set()).add("openfinance")


class PluggyConnectInvite(SQLModel, table=True):
    """Convite para o titular conectar sua conta via Pluggy Connect (Open Finance)."""
    __table_args__ = (UniqueConstraint("company_id", "token_nonce", name="uq_pluggy_invite_company_nonce"),)

    id: Optional[int] = Field(default=None, primary_key=True)

    company_id: int = Field(index=True, foreign_key="company.id")
    requested_by_client_id: Optional[int] = Field(default=None, index=True, foreign_key="client.id")
    created_by_user_id: Optional[int] = Field(default=None, index=True, foreign_key="user.id")

    subject_doc: str = Field(default="", index=True)  # CPF/CNPJ (somente dígitos)
    invited_email: str = Field(default="", index=True)

    status: str = Field(default="pendente", index=True)  # pendente|conectando|valida|expirada|revogada
    token_nonce: str = Field(default_factory=lambda: secrets.token_urlsafe(16), index=True)

    signed_by_name: str = ""
    accepted_at: Optional[datetime] = None
    expires_at: datetime = Field(default_factory=utcnow)

    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class PluggyConnection(SQLModel, table=True):
    """Associação Company+Documento -> Item Pluggy (Open Finance)."""
    __table_args__ = (
        UniqueConstraint("company_id", "subject_doc", name="uq_pluggy_conn_company_doc"),
        UniqueConstraint("pluggy_item_id", name="uq_pluggy_conn_item_id"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    company_id: int = Field(index=True, foreign_key="company.id")
    requested_by_client_id: Optional[int] = Field(default=None, index=True, foreign_key="client.id")

    subject_doc: str = Field(default="", index=True)  # CPF/CNPJ digits
    client_user_id: str = Field(default="", index=True)

    pluggy_item_id: str = Field(default="", index=True)
    connector_id: Optional[int] = Field(default=None, index=True)
    status: str = Field(default="unknown", index=True)  # connected|updating|error|unknown
    last_event: str = ""
    last_error: str = ""

    consent_expires_at: Optional[datetime] = None
    last_synced_at: Optional[datetime] = None

    raw_item_json: str = ""

    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class PluggyLoan(SQLModel, table=True):
    """Snapshot do empréstimo/contrato obtido do Pluggy (Loans)."""
    __table_args__ = (
        UniqueConstraint("company_id", "pluggy_loan_id", name="uq_pluggy_loan_company_loanid"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    company_id: int = Field(index=True, foreign_key="company.id")

    subject_doc: str = Field(default="", index=True)
    pluggy_item_id: str = Field(default="", index=True)
    pluggy_loan_id: str = Field(default="", index=True)

    contract_number: str = ""
    ipoc_code: str = ""

    lender_name: str = ""
    product_type: str = ""
    amortization_type: str = ""  # PRICE|SAC|...

    principal_brl: float = 0.0
    outstanding_brl: float = 0.0
    installment_brl: float = 0.0

    term_total_months: int = 0
    term_remaining_months: int = 0

    cet_aa: float = 0.0
    interest_aa: float = 0.0

    fetched_at: datetime = Field(default_factory=utcnow)
    raw_json: str = ""


class PluggyOffer(SQLModel, table=True):
    """Catálogo manual de ofertas (para comparar portabilidade/refin)."""
    id: Optional[int] = Field(default=None, primary_key=True)
    company_id: int = Field(index=True, foreign_key="company.id")

    label: str
    lender_name: str = ""
    product_type: str = ""  # opcional: filtra tipo
    cet_aa: float = 0.0  # ex: 0.35 == 35% a.a.
    term_min_months: int = 0
    term_max_months: int = 0

    is_active: bool = True
    notes: str = ""

    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class PluggyOpportunity(SQLModel, table=True):
    """Resultado de comparação (Loan x Offer)."""
    __table_args__ = (UniqueConstraint("company_id", "subject_doc", "pluggy_loan_id", "offer_id", name="uq_pluggy_opp_unique"),)

    id: Optional[int] = Field(default=None, primary_key=True)
    company_id: int = Field(index=True, foreign_key="company.id")
    subject_doc: str = Field(default="", index=True)

    pluggy_loan_id: str = Field(default="", index=True)
    offer_id: int = Field(index=True, foreign_key="pluggyoffer.id")

    term_months: int = 0
    old_payment_brl: float = 0.0
    new_payment_brl: float = 0.0
    monthly_savings_brl: float = 0.0
    total_savings_brl: float = 0.0

    method: str = ""  # PRICE|SAC_AVG|...
    created_at: datetime = Field(default_factory=utcnow)



class Partner(SQLModel, table=True):
    """Parceiro comercial/financeiro."""
    id: Optional[int] = Field(default=None, primary_key=True)
    company_id: int = Field(index=True, foreign_key="company.id")

    name: str
    kind: str = Field(default="banco", index=True)  # banco|fidc|fintech|securitizadora|consultoria|outro
    contact_name: str = ""
    contact_email: str = ""
    contact_phone: str = ""
    is_active: bool = Field(default=True, index=True)
    priority: int = Field(default=100, index=True)
    notes: str = ""

    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class PartnerProduct(SQLModel, table=True):
    """Produto cadastrado por parceiro, com regras e defaults do simulador."""
    id: Optional[int] = Field(default=None, primary_key=True)
    company_id: int = Field(index=True, foreign_key="company.id")
    partner_id: int = Field(index=True, foreign_key="partner.id")

    name: str
    category: str = Field(default="credito", index=True)  # credito|consultoria|ferramenta|outro
    product_type: str = Field(default="", index=True)
    is_active: bool = Field(default=True, index=True)
    visible_in_simulator: bool = Field(default=True, index=True)
    priority: int = Field(default=100, index=True)

    # Elegibilidade
    min_revenue_monthly_brl: float = 0.0
    max_debt_ratio: float = 0.0  # 0 => não valida; senão dívida/faturamento mensal
    min_score_total: float = 0.0
    min_score_financial: float = 0.0
    requires_collateral: bool = False
    min_ticket_brl: float = 0.0
    max_ticket_brl: float = 0.0
    allowed_states_json: str = ""
    notes: str = ""

    # Defaults do simulador
    default_loan_type: str = ""
    default_amortization: str = Field(default="price")
    default_rate_pct: float = 0.0
    default_rate_base: str = Field(default="am")  # am|aa
    default_term_months: int = 0
    term_min_months: int = 0
    term_max_months: int = 0
    default_grace_months: int = 0
    default_io_months: int = 0
    default_fee_amount_brl: float = 0.0
    default_monthly_insurance_brl: float = 0.0
    default_monthly_admin_fee_brl: float = 0.0
    default_ltv_pct: float = 0.0

    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)



class InternalService(SQLModel, table=True):
    """Catálogo interno Maffezzolli: Advisory, IB, BaaS e Special Sits."""
    id: Optional[int] = Field(default=None, primary_key=True)
    company_id: int = Field(index=True, foreign_key="company.id")
    area: str = Field(default="baas", index=True)  # advisory|ib|baas|special_sits
    family_slug: str = Field(default="", index=True)
    name: str
    description: str = ""
    priority_weight: int = Field(default=100, index=True)
    is_active: bool = Field(default=True, index=True)
    notes: str = ""
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class PartnerCampaign(SQLModel, table=True):
    """Campanhas temporárias por parceiro/produto."""
    id: Optional[int] = Field(default=None, primary_key=True)
    company_id: int = Field(index=True, foreign_key="company.id")
    partner_product_id: int = Field(index=True, foreign_key="partnerproduct.id")
    title: str
    starts_at: Optional[datetime] = None
    ends_at: Optional[datetime] = None
    bonus_pct: float = 0.0
    rule_summary: str = ""
    is_active: bool = Field(default=True, index=True)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class OfferMatch(SQLModel, table=True):
    """Resultado persistido do motor de ofertas por cliente."""
    id: Optional[int] = Field(default=None, primary_key=True)
    company_id: int = Field(index=True, foreign_key="company.id")
    client_id: int = Field(index=True, foreign_key="client.id")
    subject_doc: str = Field(default="", index=True)
    source_kind: str = Field(default="partner", index=True)  # internal|partner
    internal_service_id: Optional[int] = Field(default=None, index=True, foreign_key="internalservice.id")
    partner_product_id: Optional[int] = Field(default=None, index=True, foreign_key="partnerproduct.id")
    area: str = Field(default="", index=True)
    product_name: str = ""
    partner_name: str = ""
    score_fit: float = 0.0
    priority_level: str = Field(default="media", index=True)
    reason_summary: str = ""
    estimated_commission_text: str = ""
    created_at: datetime = Field(default_factory=utcnow)

class KlaviFlow(SQLModel, table=True):
    """Estado do fluxo Klavi (Link/Consent) por CPF/CNPJ."""

    __table_args__ = (UniqueConstraint("company_id", "subject_doc", name="uq_klavi_flow_company_doc"),)

    id: Optional[int] = Field(default=None, primary_key=True)
    company_id: int = Field(index=True, foreign_key="company.id")
    subject_doc: str = Field(default="", index=True)

    email: str = ""
    phone: str = ""

    link_id: str = Field(default="", index=True)
    link_token: str = ""
    link_expires_at: datetime = Field(default_factory=utcnow)

    institution_code: str = ""
    institution_name: str = ""

    consent_id: str = Field(default="", index=True)
    consent_status: str = ""
    last_request_id: str = ""
    last_error: str = ""

    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class KlaviReport(SQLModel, table=True):
    """Armazena relatórios recebidos via webhook (debug + histórico)."""

    id: Optional[int] = Field(default=None, primary_key=True)
    company_id: int = Field(index=True, foreign_key="company.id")
    subject_doc: str = Field(default="", index=True)

    product: str = Field(default="", index=True)
    request_id: str = Field(default="", index=True)
    received_at: datetime = Field(default_factory=utcnow)

    raw_json: str = ""


def ensure_pluggy_tables() -> bool:
    """Garante tabelas do módulo Pluggy (ambientes sem Alembic)."""
    ok = True
    for tbl in (
        PluggyConnectInvite.__table__,
        PluggyConnection.__table__,
        PluggyLoan.__table__,
        PluggyOffer.__table__,
        PluggyOpportunity.__table__,
        KlaviFlow.__table__,
        KlaviReport.__table__,
    ):
        try:
            tbl.create(engine, checkfirst=True)
        except Exception as e:
            ok = False
            try:
                print(f"[pluggy] failed to ensure table {tbl.name}: {e}")
            except Exception:
                pass
    return ok


@dataclass
class _KlaviAccessTokenCache:
    access_token: str = ""
    exp_ts: float = 0.0


_KLAVI_TOKEN_CACHE = _KlaviAccessTokenCache()


def _klavi_is_configured() -> bool:
    return bool(KLAVI_ACCESS_KEY and KLAVI_SECRET_KEY and KLAVI_API_BASE)


async def _klavi_get_access_token() -> str:
    """Retorna accessToken (cache ~30 min) para chamadas server-side."""
    now = utcnow().timestamp()
    if _KLAVI_TOKEN_CACHE.access_token and now < (_KLAVI_TOKEN_CACHE.exp_ts - 60):
        return _KLAVI_TOKEN_CACHE.access_token

    if not _klavi_is_configured():
        raise RuntimeError("KLAVI_ACCESS_KEY/KLAVI_SECRET_KEY não configurados.")

    url = f"{KLAVI_API_BASE}/data/v1/auth"
    payload = {"accessKey": KLAVI_ACCESS_KEY, "secretKey": KLAVI_SECRET_KEY}

    async with httpx.AsyncClient(timeout=KLAVI_HTTP_TIMEOUT_S) as client:
        r = await client.post(url, json=payload, headers={"accept": "application/json"})
        r.raise_for_status()
        data = r.json() if r.content else {}

    token = str(data.get("accessToken") or data.get("accesstoken") or "").strip()
    exp_in = int(data.get("expireIn") or data.get("expirein") or 1800)

    if not token:
        raise RuntimeError("Resposta inesperada do Klavi /auth (accessToken ausente).")

    _KLAVI_TOKEN_CACHE.access_token = token
    _KLAVI_TOKEN_CACHE.exp_ts = now + max(60, exp_in)
    return token


def _klavi_auth_header(token: str) -> dict[str, str]:
    return {"authorization": f"Bearer {token}", "accept": "application/json"}


async def _klavi_post_json(*, path: str, bearer: str, payload: dict[str, Any]) -> dict[str, Any]:
    url = f"{KLAVI_API_BASE}{path}"
    async with httpx.AsyncClient(timeout=KLAVI_HTTP_TIMEOUT_S) as client:
        r = await client.post(url, json=payload, headers={**_klavi_auth_header(bearer), "content-type": "application/json"})
        r.raise_for_status()
        return r.json() if r.content else {}


async def _klavi_get_json(*, path: str, bearer: str) -> Any:
    url = f"{KLAVI_API_BASE}{path}"
    async with httpx.AsyncClient(timeout=KLAVI_HTTP_TIMEOUT_S) as client:
        r = await client.get(url, headers=_klavi_auth_header(bearer))
        r.raise_for_status()
        return r.json() if r.content else {}


def _deep_iter_dicts(obj: Any) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    stack = [obj]
    while stack:
        cur = stack.pop()
        if isinstance(cur, dict):
            out.append(cur)
            for v in cur.values():
                stack.append(v)
        elif isinstance(cur, list):
            for v in cur:
                stack.append(v)
    return out


def _klavi_pick_float(d: dict[str, Any], *keys: str) -> float:
    for k in keys:
        v = d.get(k)
        if v is None:
            continue
        try:
            if isinstance(v, str):
                v = v.replace(",", ".")
            return float(v)
        except Exception:
            continue
    return 0.0


def _klavi_pick_int(d: dict[str, Any], *keys: str) -> int:
    for k in keys:
        v = d.get(k)
        if v is None:
            continue
        try:
            return int(float(v))
        except Exception:
            continue
    return 0


def _klavi_pick_str(d: dict[str, Any], *keys: str) -> str:
    for k in keys:
        v = d.get(k)
        if v is None:
            continue
        s = str(v).strip()
        if s:
            return s
    return ""


def _klavi_extract_contract_dicts(payload: Any) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for d in _deep_iter_dicts(payload):
        has_id = any(k in d for k in ("contractNumber", "contractId", "ipocCode", "loanId", "id"))
        has_money = any(k in d for k in ("contractAmount", "contractedAmount", "principalAmount", "outstandingBalance", "installmentAmount", "cet", "CET"))
        if has_id and has_money:
            candidates.append(d)
    # dedup by repr hash
    seen = set()
    uniq = []
    for d in candidates:
        h = hash(json.dumps(d, sort_keys=True, default=str))
        if h in seen:
            continue
        seen.add(h)
        uniq.append(d)
    return uniq[:200]


def _klavi_contract_to_loan(*, company_id: int, subject_doc: str, link_id: str, contract: dict[str, Any], raw_payload: Any) -> PluggyLoan:
    contract_number = _klavi_pick_str(contract, "contractNumber", "contractId", "number")
    ipoc_code = _klavi_pick_str(contract, "ipocCode", "ipoc", "ipoc_code")

    lender = _klavi_pick_str(contract, "brandName", "institutionName", "lenderName", "companyName", "bankName")
    product_type = _klavi_pick_str(contract, "type", "productType", "product", "subType")
    amort = _klavi_pick_str(contract, "amortizationType", "amortizationScheduled", "amortization", "amortization_type")

    principal = _klavi_pick_float(contract, "contractAmount", "contractedAmount", "principalAmount", "amount")
    outstanding = _klavi_pick_float(contract, "outstandingBalance", "contractOutstandingBalance", "balance", "outstanding_brl")
    installment = _klavi_pick_float(contract, "installmentAmount", "instalmentAmount", "scheduledInstalmentAmount", "installment_brl")

    term_total = _klavi_pick_int(contract, "installmentQuantity", "instalmentQuantity", "termTotalMonths", "term")
    term_rem = _klavi_pick_int(contract, "remainingInstallments", "remainingInstalments", "termRemainingMonths")

    cet = _klavi_pick_float(contract, "CET", "cet", "cetAnnual", "cet_aa")
    interest = _klavi_pick_float(contract, "interestRate", "interestRates", "interestAnnual", "interest_aa")

    pluggy_loan_id = f"klavi:{contract_number or ipoc_code or _klavi_pick_str(contract,'id','loanId') or secrets.token_hex(6)}"
    return PluggyLoan(
        company_id=company_id,
        subject_doc=subject_doc,
        pluggy_item_id=f"klavi:{link_id}",
        pluggy_loan_id=pluggy_loan_id,
        contract_number=contract_number,
        ipoc_code=ipoc_code,
        lender_name=lender,
        product_type=product_type or "loans",
        amortization_type=amort,
        principal_brl=principal,
        outstanding_brl=outstanding,
        installment_brl=installment,
        term_total_months=term_total,
        term_remaining_months=term_rem,
        cet_aa=cet,
        interest_aa=interest,
        fetched_at=utcnow(),
        raw_json=json.dumps(raw_payload, ensure_ascii=False, default=str),
    )


async def klavi_request_loans_report(*, doc_digits: str, flow: KlaviFlow) -> str:
    """Dispara request de relatório 'loans' (PF/PJ) e retorna requestId."""
    access_token = await _klavi_get_access_token()

    # Klavi endpoints variam entre camelCase e lowercase em diferentes versões da API.
    callback_url = f"{PUBLIC_BASE_URL}/webhooks/klavi/products" if PUBLIC_BASE_URL else ""

    base_payload: dict[str, Any] = {
        # camelCase
        "taxId": doc_digits,
        "institutionId": flow.institution_code,
        "linkId": flow.link_id,
        "consentId": [flow.consent_id] if flow.consent_id else [],
        # lowercase (compat)
        "taxid": doc_digits,
        "institutioncode": flow.institution_code,
        "linkid": flow.link_id,
        "consentids": [flow.consent_id] if flow.consent_id else [],
        # additional aliases seen in docs
        "institutionCode": flow.institution_code,
        "consentIds": [flow.consent_id] if flow.consent_id else [],
        "products": ["loans"],
    }

    if callback_url:
        # Klavi doc examples for product callback use key "all" (send all selected reports to this endpoint).
        # See: /connect/institutional-level-report
        base_payload["productsCallbackUrl"] = {"all": callback_url}
        base_payload["productscallbackurl"] = {"all": callback_url}

    # Prefer API Reference v1 path; fallback to legacy paths.
    if len(doc_digits) == 11:
        candidate_paths = (
            "/data/v1/personal/institution-data",
            "/data/v1/personal/institution_data",
            "/data/personal/institution-data",
            "/data/personal/institution_data",
        )
    else:
        candidate_paths = (
            "/data/v1/business/institution-data",
            "/data/v1/business/institution_data",
            "/data/business/institution-data",
            "/data/business/institution_data",
        )

    data: dict[str, Any] | None = None
    last_404: Exception | None = None
    for path in candidate_paths:
        try:
            data = await _klavi_post_json(path=path, bearer=access_token, payload=base_payload)
            break
        except httpx.HTTPStatusError as e:
            if e.response is not None and e.response.status_code == 404:
                last_404 = e
                continue

            # Klavi uses HTTP 416 for business processing errors, with `statusCode` in the JSON body.
            # See: /connect/open-finance-codes-and-errors
            if e.response is not None and e.response.status_code == 416:
                try:
                    err_payload = e.response.json()
                except Exception:
                    err_payload = {"message": (e.response.text or "").strip()}
                status_code = err_payload.get("statusCode") or err_payload.get("statuscode")
                message = err_payload.get("message") or err_payload.get("error") or str(err_payload)

                # Common fallback: if product list is not accepted, retry requesting all allowed products.
                if status_code in {4002, 4005} and base_payload.get("products") != ["all"]:
                    base_payload["products"] = ["all"]
                    continue

                raise RuntimeError(f"Klavi: erro de negócio (HTTP 416). statusCode={status_code}. {message}") from e

            raise

    if data is None:
        raise last_404 or RuntimeError("Klavi: endpoint de report não encontrado")

    request_id = str(data.get("requestId") or data.get("requestid") or "").strip()
    if not request_id:
        request_id = secrets.token_hex(8)
    return request_id


@dataclass
class _PluggyApiKeyCache:
    api_key: str = ""
    exp_ts: float = 0.0


_PLUGGY_KEY_CACHE = _PluggyApiKeyCache()



def ensure_partner_tables() -> bool:
    """Garante tabelas do módulo Parceiros/Produtos (ambientes sem Alembic)."""
    ok = True
    for tbl in (
        Partner.__table__,
        PartnerProduct.__table__,
        InternalService.__table__,
        PartnerCampaign.__table__,
        OfferMatch.__table__,
    ):
        try:
            tbl.create(engine, checkfirst=True)
        except Exception as e:
            ok = False
            try:
                print(f"[partners] failed to ensure table {tbl.name}: {e}")
            except Exception:
                pass
    return ok


def _partner_kind_options() -> list[str]:
    return ["banco", "fidc", "fintech", "securitizadora", "consultoria", "outro"]


def _partner_product_category_options() -> list[str]:
    return ["credito", "consultoria", "ferramenta", "outro"]


def _partner_product_type_options() -> list[str]:
    return [
        "",
        "capital_giro",
        "recebiveis",
        "home_equity",
        "auto_equity",
        "consignado",
        "portabilidade",
        "reperfilamento",
        "credito_estruturado",
        "consultoria_financeira",
        "turnaround",
        "bpo_financeiro",
        "bi_financeiro",
    ]



def _offer_area_options() -> list[tuple[str, str]]:
    return [
        ("advisory", "Advisory"),
        ("ib", "Investment Banking"),
        ("baas", "BaaS"),
        ("special_sits", "Special Sits"),
    ]


def _internal_service_defaults() -> list[tuple[str, str, str, str]]:
    return [
        ("advisory", "turnaround", "Advisory - Consultoria Turnaround", "Consultoria em reestruturação de empresas."),
        ("advisory", "valuation", "Advisory - Consultoria Valuation", "Avaliação de empresas."),
        ("advisory", "estrategia_financeira", "Advisory - Consultoria Estratégica Financeira", "Consultoria em finanças empresariais."),
        ("advisory", "plano_rj", "Advisory - Plano de Recuperação Judicial", "Plano, documentos e estratégia para recuperação judicial."),
        ("ib", "rodada_seed", "IB - Assessoria em Rodada Anjo/Seed/Série A (ECM)", "Conectar startups e empresas em crescimento com investidores."),
        ("ib", "roadshow_equity", "IB - Roadshow para Captação de Equity (ECM)", "Apresentar a empresa a múltiplos fundos para captação."),
        ("ib", "debenture", "IB - Estruturação de Debênture (DCM)", "Estruturar emissão de títulos de dívida."),
        ("ib", "cri_cra", "IB - Estruturação de CRI/CRA (DCM)", "Estruturação de títulos lastreados em recebíveis."),
        ("ib", "ma_sell_side", "IB - Mandato de Venda (M&A Sell-side)", "Venda total ou parcial da empresa."),
        ("ib", "ma_buy_side", "IB - Mandato de Compra (M&A Buy-side)", "Assessoria em aquisições."),
        ("special_sits", "distressed_ma", "Special Sits - Assessoria em M&A de Ativos Estressados (Distressed M&A)", "Fusões e aquisições em situações de crise."),
        ("special_sits", "creditos_rj", "Special Sits - Intermediação de Créditos de RJ (Recuperação Judicial)", "Liquidez para créditos de empresas em RJ."),
        ("special_sits", "creditos_tributarios", "Special Sits - Venda de Créditos Tributários (Precatórios,etc.)", "Monetização de créditos tributários."),
        ("special_sits", "dip_financing", "Special Sits - Captação de Financiamento DIP (Debtor-in-Possession)", "Financiamento emergencial em RJ."),
        ("baas", "capital_giro", "BaaS - Capital de Giro", "Linhas de capital de giro para financiar operações."),
        ("baas", "conta_garantida", "BaaS - Conta Garantida", "Crédito rotativo para flexibilidade de caixa."),
        ("baas", "desconto_duplicatas", "BaaS - Desconto de Duplicatas / Antecipação de Títulos", "Transforme vendas a prazo em caixa imediato."),
        ("baas", "antecipacao_cartoes", "BaaS - Antecipação de Cartões", "Adiantamento de vendas em cartão."),
        ("baas", "cambio", "BaaS - Câmbio Pronto (PF e PJ)", "Compra e venda de moeda estrangeira."),
        ("baas", "trade_finance", "BaaS - Trade Finance", "Operações de ACC/ACE e comércio exterior."),
        ("baas", "financiamento_veiculos", "BaaS - Financiamento de Veículos", "Linhas para aquisição de veículos."),
        ("baas", "consorcio", "BaaS - Consórcio", "Consórcio para imóveis e veículos."),
        ("baas", "cessao_credito", "BaaS - Cessão de Crédito", "Venda de carteiras de crédito e recebíveis."),
        ("baas", "auto_equity", "BaaS - Auto Equity", "Crédito com veículo em garantia."),
        ("baas", "credito_estruturado", "BaaS - Crédito Corporativo Estruturado", "Operações sob medida para necessidades específicas."),
        ("baas", "home_equity", "BaaS - Home Equity (Empréstimo com Garantia de Imóvel)", "Crédito com imóvel em garantia."),
        ("baas", "credito_habitacional", "BaaS - Crédito Habitacional", "Financiamento imobiliário."),
        ("baas", "plano_empresario", "BaaS - Financiamento à Produção (Plano Empresário)", "Financiamento à produção imobiliária."),
        ("baas", "analise_credito", "BaaS - Analise de Crédito", "Relatório completo sobre perfil de risco."),
    ]


def _seed_internal_services(session: Session, company_id: int) -> None:
    try:
        existing = session.exec(
            select(InternalService).where(InternalService.company_id == int(company_id))
        ).first()
        if existing:
            return
        rows = []
        for area, family_slug, name, desc in _internal_service_defaults():
            rows.append(
                InternalService(
                    company_id=int(company_id),
                    area=area,
                    family_slug=family_slug,
                    name=name,
                    description=desc,
                    priority_weight=100,
                    is_active=True,
                )
            )
        session.add_all(rows)
        session.commit()
    except Exception:
        session.rollback()


def _latest_client_snapshot(session: Session, company_id: int, client_id: int) -> Optional[ClientSnapshot]:
    return session.exec(
        select(ClientSnapshot)
        .where(ClientSnapshot.company_id == int(company_id), ClientSnapshot.client_id == int(client_id))
        .order_by(ClientSnapshot.created_at.desc())
    ).first()


def _parse_states_csv(raw: str) -> set[str]:
    return {p.strip().upper() for p in (raw or "").split(",") if p.strip()}


def _current_campaigns_for_product(session: Session, company_id: int, partner_product_id: int) -> list[PartnerCampaign]:
    now = utcnow()
    rows = session.exec(
        select(PartnerCampaign)
        .where(
            PartnerCampaign.company_id == int(company_id),
            PartnerCampaign.partner_product_id == int(partner_product_id),
            PartnerCampaign.is_active == True,
        )
        .order_by(PartnerCampaign.created_at.desc())
    ).all()
    out = []
    for row in rows:
        if row.starts_at and row.starts_at > now:
            continue
        if row.ends_at and row.ends_at < now:
            continue
        out.append(row)
    return out


def _estimate_partner_commission_text(product: PartnerProduct, campaigns: list[PartnerCampaign]) -> str:
    base = ""
    if float(product.default_rate_pct or 0) > 0:
        base = f"Taxa base sug.: {round(float(product.default_rate_pct or 0), 2)}% {str(product.default_rate_base or 'am')}"
    if campaigns:
        extra = " | ".join(
            [f"{c.title} (+{round(float(c.bonus_pct or 0), 2)}%)" if float(c.bonus_pct or 0) > 0 else c.title for c in campaigns]
        )
        return (base + " • " if base else "") + extra
    return base


def _priority_label(score_fit: float) -> str:
    if score_fit >= 85:
        return "alta"
    if score_fit >= 65:
        return "media"
    return "baixa"


def _score_internal_service(service: InternalService, client: Client, snap: Optional[ClientSnapshot]) -> tuple[float, list[str]]:
    reasons: list[str] = []
    score = 40.0
    debt = float(getattr(client, "debt_total_brl", 0.0) or 0.0)
    revenue = float(getattr(client, "revenue_monthly_brl", 0.0) or 0.0)
    cash = float(getattr(client, "cash_balance_brl", 0.0) or 0.0)
    total_score = float(getattr(snap, "score_total", 0.0) or 0.0) if snap else 0.0
    process_score = float(getattr(snap, "score_process", 0.0) or 0.0) if snap else 0.0

    if service.area == "advisory":
        if process_score < 60:
            score += 22
            reasons.append("baixa maturidade operacional")
        if debt > revenue * 4:
            score += 18
            reasons.append("alavancagem elevada")
    elif service.area == "ib":
        if revenue >= 300000:
            score += 18
            reasons.append("escala de receita compatível")
        if total_score >= 65:
            score += 16
            reasons.append("empresa com maturidade para agenda estratégica")
    elif service.area == "special_sits":
        if debt > revenue * 6:
            score += 26
            reasons.append("estrutura de passivo relevante")
        if cash < revenue * 0.3:
            score += 10
            reasons.append("caixa pressionado")
    elif service.area == "baas":
        if revenue > 0:
            score += 10
            reasons.append("empresa com demanda financeira potencial")
        if debt > 0:
            score += 10
            reasons.append("passivo passível de estruturação")
        if cash < revenue * 0.5:
            score += 10
            reasons.append("necessidade de caixa / liquidez")

    score += max(min(total_score / 10.0, 10.0), 0.0)
    return round(min(score, 99.0), 2), reasons


def _score_partner_product(session: Session, company_id: int, product: PartnerProduct, partner: Partner, client: Client, snap: Optional[ClientSnapshot]) -> dict[str, Any]:
    reasons: list[str] = []
    blockers: list[str] = []
    score = 45.0 + max(0.0, 20.0 - float(product.priority or 100) / 10.0)

    revenue = float(getattr(client, "revenue_monthly_brl", 0.0) or 0.0)
    debt = float(getattr(client, "debt_total_brl", 0.0) or 0.0)
    total_score = float(getattr(snap, "score_total", 0.0) or 0.0) if snap else 0.0
    fin_score = float(getattr(snap, "score_financial", 0.0) or 0.0) if snap else 0.0
    ticket_brl = min(max(revenue * 3, float(product.min_ticket_brl or 0.0) or 0.0), float(product.max_ticket_brl or 0.0) or max(revenue * 3, 0.0))

    eligible = True
    if float(product.min_revenue_monthly_brl or 0.0) > 0 and revenue < float(product.min_revenue_monthly_brl or 0.0):
        eligible = False
        blockers.append("faturamento abaixo do mínimo")
    else:
        if revenue > 0 and float(product.min_revenue_monthly_brl or 0.0) > 0:
            reasons.append("faturamento compatível")

    if float(product.min_score_total or 0.0) > 0 and total_score < float(product.min_score_total or 0.0):
        eligible = False
        blockers.append("score total abaixo do mínimo")
    elif float(product.min_score_total or 0.0) > 0:
        reasons.append("score total compatível")
        score += 8

    if float(product.min_score_financial or 0.0) > 0 and fin_score < float(product.min_score_financial or 0.0):
        eligible = False
        blockers.append("score financeiro abaixo do mínimo")
    elif float(product.min_score_financial or 0.0) > 0:
        reasons.append("score financeiro compatível")
        score += 8

    max_debt_ratio = float(product.max_debt_ratio or 0.0)
    if max_debt_ratio > 0 and revenue > 0:
        actual_ratio = debt / max(revenue, 1.0)
        if actual_ratio > max_debt_ratio:
            eligible = False
            blockers.append("alavancagem acima da regra")
        else:
            reasons.append("alavancagem dentro da regra")
            score += 6

    states = _parse_states_csv(product.allowed_states_json)
    client_state = (getattr(client, "state", "") or "").strip().upper()
    if states:
        if client_state and client_state in states:
            reasons.append("UF atendida")
            score += 4
        else:
            blockers.append("UF fora da cobertura")
            eligible = False

    if bool(product.requires_collateral):
        if "home" in str(product.product_type or "") or "equity" in str(product.product_type or ""):
            reasons.append("produto orientado a garantia")
        score += 4

    if float(product.min_ticket_brl or 0.0) > 0 and ticket_brl < float(product.min_ticket_brl or 0.0):
        eligible = False
        blockers.append("ticket sugerido abaixo do mínimo")
    if float(product.max_ticket_brl or 0.0) > 0 and ticket_brl > float(product.max_ticket_brl or 0.0):
        ticket_brl = float(product.max_ticket_brl or 0.0)

    campaigns = _current_campaigns_for_product(session, company_id, int(product.id or 0))
    if campaigns:
        score += 5
        reasons.append("campanha vigente")

    return {
        "partner": partner,
        "product": product,
        "score": round(min(score, 99.0), 2),
        "eligible": eligible,
        "reasons": reasons,
        "blockers": blockers,
        "ticket_brl": round(ticket_brl or 0.0, 2),
        "campaigns": campaigns,
        "commission_text": _estimate_partner_commission_text(product, campaigns),
    }


def _generate_offer_matches(session: Session, company_id: int, client: Client) -> list[OfferMatch]:
    _seed_internal_services(session, company_id)
    snap = _latest_client_snapshot(session, company_id, int(client.id or 0))

    old_rows = session.exec(
        select(OfferMatch).where(OfferMatch.company_id == int(company_id), OfferMatch.client_id == int(client.id or 0))
    ).all()
    for row in old_rows:
        session.delete(row)
    session.commit()

    created: list[OfferMatch] = []

    services = session.exec(
        select(InternalService)
        .where(InternalService.company_id == int(company_id), InternalService.is_active == True)
        .order_by(InternalService.priority_weight.asc(), InternalService.name.asc())
    ).all()
    for service in services:
        score_fit, reasons = _score_internal_service(service, client, snap)
        row = OfferMatch(
            company_id=int(company_id),
            client_id=int(client.id or 0),
            subject_doc=_digits(str(getattr(client, "cnpj", "") or getattr(client, "email", ""))),
            source_kind="internal",
            internal_service_id=int(service.id or 0),
            area=service.area,
            product_name=service.name,
            partner_name="Maffezzolli Capital",
            score_fit=score_fit,
            priority_level=_priority_label(score_fit),
            reason_summary="; ".join(reasons) or "aderência calculada pelo perfil do cliente",
        )
        session.add(row)
        created.append(row)

    partners = session.exec(
        select(Partner).where(Partner.company_id == int(company_id), Partner.is_active == True).order_by(Partner.priority.asc(), Partner.name.asc())
    ).all()
    products = session.exec(
        select(PartnerProduct)
        .where(PartnerProduct.company_id == int(company_id), PartnerProduct.is_active == True)
        .order_by(PartnerProduct.priority.asc(), PartnerProduct.created_at.desc())
    ).all()
    partner_by_id = {int(p.id or 0): p for p in partners}
    for product in products:
        partner = partner_by_id.get(int(product.partner_id or 0))
        if not partner:
            continue
        result = _score_partner_product(session, company_id, product, partner, client, snap)
        row = OfferMatch(
            company_id=int(company_id),
            client_id=int(client.id or 0),
            subject_doc=_digits(str(getattr(client, "cnpj", "") or getattr(client, "email", ""))),
            source_kind="partner",
            partner_product_id=int(product.id or 0),
            area="baas" if product.category == "credito" else product.category,
            product_name=product.name,
            partner_name=partner.name,
            score_fit=float(result["score"]),
            priority_level=_priority_label(float(result["score"])),
            reason_summary="Motivos: " + "; ".join(result["reasons"]) + ((" | Atenção: " + "; ".join(result["blockers"])) if result["blockers"] else ""),
            estimated_commission_text=result["commission_text"],
        )
        session.add(row)
        created.append(row)

    session.commit()
    return session.exec(
        select(OfferMatch)
        .where(OfferMatch.company_id == int(company_id), OfferMatch.client_id == int(client.id or 0))
        .order_by(OfferMatch.score_fit.desc(), OfferMatch.created_at.desc())
    ).all()

def _digits(value: str) -> str:
    return re.sub(r"\\D+", "", (value or "")).strip()


def _pluggy_client_user_id(*, company_id: int, subject_doc: str) -> str:
    # Fácil de reverter no webhook.
    return f"mc:{company_id}:{subject_doc}"


async def _pluggy_get_api_key() -> str:
    """Retorna API Key Pluggy (cache ~2h)."""
    now = utcnow().timestamp()
    if _PLUGGY_KEY_CACHE.api_key and now < (_PLUGGY_KEY_CACHE.exp_ts - 60):
        return _PLUGGY_KEY_CACHE.api_key

    if not PLUGGY_CLIENT_ID or not PLUGGY_CLIENT_SECRET:
        raise RuntimeError("PLUGGY_CLIENT_ID/PLUGGY_CLIENT_SECRET não configurados.")

    url = f"{PLUGGY_API_BASE}/auth"
    payload = {"clientId": PLUGGY_CLIENT_ID, "clientSecret": PLUGGY_CLIENT_SECRET}
    async with httpx.AsyncClient(timeout=PLUGGY_HTTP_TIMEOUT_S) as client:
        r = await client.post(url, json=payload, headers={"accept": "application/json"})
        r.raise_for_status()
        data = r.json() if r.content else {}
    api_key = str(data.get("apiKey") or data.get("api_key") or data.get("token") or "").strip()
    if not api_key:
        raise RuntimeError("Resposta inesperada do Pluggy /auth (apiKey ausente).")
    _PLUGGY_KEY_CACHE.api_key = api_key
    _PLUGGY_KEY_CACHE.exp_ts = now + 2 * 60 * 60
    return api_key


async def _pluggy_create_connect_token(*, request: Request, company_id: int, subject_doc: str, update_item_id: str | None) -> str:
    api_key = await _pluggy_get_api_key()
    url = f"{PLUGGY_API_BASE}/connect_token"

    webhook_url = ""
    try:
        base = _public_base_url(request)
        if base and PLUGGY_WEBHOOK_KEY:
            webhook_url = f"{base}/webhooks/pluggy?k={PLUGGY_WEBHOOK_KEY}"
    except Exception:
        webhook_url = ""

    options: dict[str, Any] = {
        "clientUserId": _pluggy_client_user_id(company_id=company_id, subject_doc=subject_doc),
        "avoidDuplicates": True,
    }
    if webhook_url:
        options["webhookUrl"] = webhook_url
    if update_item_id:
        options["itemId"] = update_item_id  # update mode (docs: create connect token with itemId)

    payload = {"options": options}

    async with httpx.AsyncClient(timeout=PLUGGY_HTTP_TIMEOUT_S) as client:
        r = await client.post(
            url,
            json=payload,
            headers={
                "accept": "application/json",
                "content-type": "application/json",
                "X-API-KEY": api_key,
            },
        )
        r.raise_for_status()
        data = r.json() if r.content else {}

    access_token = str(data.get("accessToken") or data.get("access_token") or data.get("token") or "").strip()
    if not access_token:
        raise RuntimeError("Resposta inesperada do Pluggy /connect_token (accessToken ausente).")
    return access_token


async def _pluggy_fetch_loans(*, item_id: str) -> list[dict[str, Any]]:
    api_key = await _pluggy_get_api_key()
    url = f"{PLUGGY_API_BASE}/loans"
    async with httpx.AsyncClient(timeout=PLUGGY_HTTP_TIMEOUT_S) as client:
        r = await client.get(url, params={"itemId": item_id}, headers={"accept": "application/json", "X-API-KEY": api_key})
        r.raise_for_status()
        data = r.json() if r.content else {}
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        v = data.get("results") or data.get("data") or data.get("loans")
        if isinstance(v, list):
            return v
    return []


def _to_float_rate(v: Any) -> float:
    try:
        x = float(v)
    except Exception:
        return 0.0
    # CET/juros podem vir como 35.2 (percent) ou 0.352 (decimal)
    if x > 1.5:
        return x / 100.0
    return x


def _pmt_price(principal: float, annual_rate: float, n: int) -> float:
    import math
    if principal <= 0 or n <= 0:
        return 0.0
    r = (1.0 + max(0.0, annual_rate)) ** (1.0 / 12.0) - 1.0
    if abs(r) < 1e-9:
        return principal / n
    return principal * r / (1.0 - (1.0 + r) ** (-n))


def _pmt_sac_avg(principal: float, annual_rate: float, n: int) -> float:
    """Pagamento médio aproximado em SAC (principal amortização fixa)."""
    import math
    if principal <= 0 or n <= 0:
        return 0.0
    r = (1.0 + max(0.0, annual_rate)) ** (1.0 / 12.0) - 1.0
    # Total de juros no SAC: P*r*(n+1)/2
    total = principal + (principal * r * (n + 1) / 2.0)
    return total / n


def _extract_loan_fields(raw: dict[str, Any]) -> dict[str, Any]:
    """Extrai campos essenciais do Loan (best-effort)."""
    loan_id = str(raw.get("id") or raw.get("loanId") or "").strip()
    contract_number = str(raw.get("contractNumber") or raw.get("contract_number") or "").strip()
    ipoc = str(raw.get("ipocCode") or raw.get("ipoc") or "").strip()

    lender = str(raw.get("lenderName") or raw.get("institutionName") or raw.get("providerName") or "").strip()
    product_type = str(raw.get("type") or raw.get("productType") or raw.get("modality") or "").strip()

    amort = str(
        (raw.get("amortizationScheduled") or {}).get("type")
        if isinstance(raw.get("amortizationScheduled"), dict)
        else (raw.get("amortizationType") or raw.get("amortization") or "")
    ).strip()

    principal = float(raw.get("contractAmount") or raw.get("principal") or 0.0) if str(raw.get("contractAmount") or raw.get("principal") or "").strip() else 0.0

    # outstanding balance pode aparecer em payments.contractOutstandingBalance
    outstanding = 0.0
    pay = raw.get("payments") or {}
    if isinstance(pay, dict):
        ob = pay.get("contractOutstandingBalance") or pay.get("outstandingBalance") or pay.get("balance")
        try:
            outstanding = float(ob or 0.0)
        except Exception:
            outstanding = 0.0

    inst = raw.get("installments") or {}
    term_total = 0
    term_remaining = 0
    inst_amount = 0.0
    if isinstance(inst, dict):
        for k in ("totalNumber", "total", "numberOfInstallments"):
            if inst.get(k) is not None:
                try:
                    term_total = int(inst.get(k))
                except Exception:
                    pass
        for k in ("remainingNumber", "remaining", "remainingInstallments"):
            if inst.get(k) is not None:
                try:
                    term_remaining = int(inst.get(k))
                except Exception:
                    pass
        for k in ("amount", "installmentAmount", "value"):
            if inst.get(k) is not None:
                try:
                    inst_amount = float(inst.get(k))
                except Exception:
                    pass

    cet = _to_float_rate(raw.get("CET") or raw.get("cet") or raw.get("cetAnnual") or 0.0)

    interest_aa = 0.0
    ir = raw.get("interestRates") or raw.get("interestRate") or {}
    if isinstance(ir, dict):
        interest_aa = _to_float_rate(ir.get("annual") or ir.get("value") or ir.get("rate") or 0.0)
    else:
        interest_aa = _to_float_rate(ir)

    return {
        "loan_id": loan_id,
        "contract_number": contract_number,
        "ipoc_code": ipoc,
        "lender_name": lender,
        "product_type": product_type,
        "amortization_type": amort,
        "principal_brl": principal,
        "outstanding_brl": outstanding,
        "installment_brl": inst_amount,
        "term_total": term_total,
        "term_remaining": term_remaining,
        "cet_aa": cet,
        "interest_aa": interest_aa,
    }


async def pluggy_sync_loans(*, session: Session, company_id: int, subject_doc: str, item_id: str) -> int:
    """Baixa loans do Pluggy e faz upsert de snapshots."""
    loans = await _pluggy_fetch_loans(item_id=item_id)
    now = utcnow()
    updated = 0

    for raw in loans:
        if not isinstance(raw, dict):
            continue
        f = _extract_loan_fields(raw)
        loan_id = f["loan_id"]
        if not loan_id:
            continue

        row = session.exec(
            select(PluggyLoan).where(
                PluggyLoan.company_id == company_id,
                PluggyLoan.pluggy_loan_id == loan_id,
            )
        ).first()
        if not row:
            row = PluggyLoan(company_id=company_id, pluggy_loan_id=loan_id)

        row.subject_doc = subject_doc
        row.pluggy_item_id = item_id
        row.contract_number = f["contract_number"]
        row.ipoc_code = f["ipoc_code"]
        row.lender_name = f["lender_name"]
        row.product_type = f["product_type"]
        row.amortization_type = f["amortization_type"]
        row.principal_brl = float(f["principal_brl"] or 0.0)
        row.outstanding_brl = float(f["outstanding_brl"] or 0.0)
        row.installment_brl = float(f["installment_brl"] or 0.0)
        row.term_total_months = int(f["term_total"] or 0)
        row.term_remaining_months = int(f["term_remaining"] or 0)
        row.cet_aa = float(f["cet_aa"] or 0.0)
        row.interest_aa = float(f["interest_aa"] or 0.0)
        row.fetched_at = now
        try:
            row.raw_json = json.dumps(raw, ensure_ascii=False)
        except Exception:
            row.raw_json = ""

        session.add(row)
        updated += 1

    # atualiza conexão
    conn = session.exec(
        select(PluggyConnection).where(
            PluggyConnection.company_id == company_id,
            PluggyConnection.subject_doc == subject_doc,
            PluggyConnection.pluggy_item_id == item_id,
        )
    ).first()
    if conn:
        conn.last_synced_at = now
        conn.updated_at = now
        session.add(conn)

    session.commit()
    return updated


def _compute_opportunities_for_doc(*, session: Session, company_id: int, subject_doc: str) -> int:
    """Gera oportunidades (Loan x Offer) e faz upsert."""
    loans = session.exec(
        select(PluggyLoan).where(PluggyLoan.company_id == company_id, PluggyLoan.subject_doc == subject_doc)
    ).all()
    offers = session.exec(
        select(PluggyOffer).where(PluggyOffer.company_id == company_id, PluggyOffer.is_active == True)
    ).all()
    if not loans or not offers:
        return 0

    inserted = 0
    for loan in loans:
        n = int(loan.term_remaining_months or loan.term_total_months or 0)
        if n <= 0:
            continue

        principal = float(loan.outstanding_brl or loan.principal_brl or 0.0)
        if principal <= 0:
            continue

        old_rate = float(loan.cet_aa or loan.interest_aa or 0.0)
        amort = (loan.amortization_type or "").upper().strip()

        if "SAC" in amort:
            old_pmt = _pmt_sac_avg(principal, old_rate, n)
            method = "SAC_AVG"
        else:
            old_pmt = _pmt_price(principal, old_rate, n)
            method = "PRICE"

        if old_pmt <= 0 and loan.installment_brl > 0:
            old_pmt = float(loan.installment_brl)
            method = (method + "+OBS") if method else "OBS"

        for offer in offers:
            if offer.product_type and loan.product_type and offer.product_type.strip().lower() not in loan.product_type.strip().lower():
                continue
            if offer.term_min_months and n < int(offer.term_min_months):
                continue
            if offer.term_max_months and n > int(offer.term_max_months):
                continue

            new_pmt = _pmt_price(principal, float(offer.cet_aa or 0.0), n)
            if new_pmt <= 0:
                continue

            monthly_sav = old_pmt - new_pmt
            total_sav = monthly_sav * n

            row = session.exec(
                select(PluggyOpportunity).where(
                    PluggyOpportunity.company_id == company_id,
                    PluggyOpportunity.subject_doc == subject_doc,
                    PluggyOpportunity.pluggy_loan_id == loan.pluggy_loan_id,
                    PluggyOpportunity.offer_id == int(offer.id or 0),
                )
            ).first()
            if not row:
                row = PluggyOpportunity(
                    company_id=company_id,
                    subject_doc=subject_doc,
                    pluggy_loan_id=loan.pluggy_loan_id,
                    offer_id=int(offer.id or 0),
                )
                inserted += 1

            row.term_months = n
            row.old_payment_brl = float(old_pmt)
            row.new_payment_brl = float(new_pmt)
            row.monthly_savings_brl = float(monthly_sav)
            row.total_savings_brl = float(total_sav)
            row.method = method
            row.created_at = utcnow()
            session.add(row)

    session.commit()
    return inserted







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
  <img src="/static/logo.png" alt="Maffezzolli Capital" style="height:44px; width:auto;">
  <span class="fw-semibold" style="color:#0B1E1E; font-size:0.95rem; letter-spacing:0.2px; opacity:0.9;">Bem-vindo</span>
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

  <!-- Banner (carrossel) -->
  <div id="mc-banner" class="mb-3"></div>

  <div class="row g-3">
    <div class="col-12 col-lg-9">
      {% block content %}{% endblock %}
      <div class="mt-5 muted small">
        <div>Uploads protegidos por login (download via rota).</div>
      </div>
    </div>

    <div class="col-12 col-lg-3">
      <div class="card p-3">
        <div class="d-flex align-items-center justify-content-between">
          <div class="fw-semibold">📰 Notícias (economia)</div>
          {% if role == "admin" %}
            <a class="small" href="/admin/ui">Configurar</a>
          {% endif %}
        </div>
        <div class="muted small mt-1">Atualiza automaticamente.</div>
        <div id="mc-news" class="mt-2"></div>
      </div>
    </div>
  </div>
</main>
  <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/js/bootstrap.bundle.min.js"></script>
<script>
(function(){
  const esc = (s) => String(s || "").replace(/[&<>"']/g, (c) => ({
    "&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"
  }[c]));

  async function loadBanner(){
    const holder = document.getElementById("mc-banner");
    if (!holder) return;
    try{
      const res = await fetch("/api/ui/banner", { headers: { "Accept": "application/json" }, credentials: "same-origin" });
      if (!res.ok) return;
      const slides = await res.json();
      if (!Array.isArray(slides) || slides.length === 0) { holder.innerHTML = ""; return; }

      const cid = "mcCarousel";
      const indicators = slides.map((_,i)=>`<button type="button" data-bs-target="#${cid}" data-bs-slide-to="${i}" ${i===0?'class="active" aria-current="true"':''} aria-label="Slide ${i+1}"></button>`).join("");
      const items = slides.map((s,i)=>{
        const img = esc(s.image_url);
        const link = esc(s.link_path || "/");
        const title = esc(s.title || "");
        return `
          <div class="carousel-item ${i===0?'active':''}">
            <a href="${link}" style="display:block;">
              <img src="${img}" class="d-block w-100" alt="${title}" style="border-radius:16px; max-height:240px; object-fit:cover;">
            </a>
            ${title ? `<div class="carousel-caption d-none d-md-block"><h6 class="bg-dark bg-opacity-50 d-inline-block px-2 py-1 rounded">${title}</h6></div>` : ``}
          </div>`;
      }).join("");

      holder.innerHTML = `
        <div id="${cid}" class="carousel slide" data-bs-ride="carousel">
          <div class="carousel-indicators">${indicators}</div>
          <div class="carousel-inner">${items}</div>
          <button class="carousel-control-prev" type="button" data-bs-target="#${cid}" data-bs-slide="prev">
            <span class="carousel-control-prev-icon" aria-hidden="true"></span>
            <span class="visually-hidden">Anterior</span>
          </button>
          <button class="carousel-control-next" type="button" data-bs-target="#${cid}" data-bs-slide="next">
            <span class="carousel-control-next-icon" aria-hidden="true"></span>
            <span class="visually-hidden">Próximo</span>
          </button>
        </div>`;
    }catch(e){
    }
  }

  async function loadNews(){
    const holder = document.getElementById("mc-news");
    if (!holder) return;
    holder.innerHTML = '<div class="muted small">Carregando…</div>';
    try{
      const res = await fetch("/api/ui/news?limit=10", { headers: { "Accept": "application/json" }, credentials: "same-origin" });
      if (!res.ok) { holder.innerHTML = '<div class="muted small">Sem notícias no momento.</div>'; return; }
      const items = await res.json();
      if (!Array.isArray(items) || items.length === 0) { holder.innerHTML = '<div class="muted small">Sem notícias no momento.</div>'; return; }
      holder.innerHTML = `
        <div class="list-group list-group-flush">
          ${items.map(it => `
            <a class="list-group-item list-group-item-action small" href="${esc(it.url)}" target="_blank" rel="noopener">
              <div class="fw-semibold">${esc(it.title)}</div>
              <div class="muted" style="font-size:.8rem;">${esc(it.source || "")}${it.published ? " • " + esc(it.published) : ""}</div>
            </a>`).join("")}
        </div>`;
    }catch(e){
      holder.innerHTML = '<div class="muted small">Sem notícias no momento.</div>';
    }
  }

  window.addEventListener("DOMContentLoaded", function(){
    loadBanner();
    loadNews();
  });
})();
</script>
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

{% if allow_company_signup %}
  <div class="d-flex justify-content-between align-items-center">
    <div class="muted">Primeiro acesso?</div>
    <a class="btn btn-outline-primary" href="/signup">Criar escritório</a>
  </div>
{% else %}
  <div class="muted small">
    Cadastro de escritório desativado. Peça ao administrador para criar seu acesso.
  </div>
{% endif %}
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

  {% if tabs %}
  <div class="col-12">
    <ul class="nav nav-pills gap-2" id="dashTabs" role="tablist">
      {% for t in tabs %}
        <li class="nav-item" role="presentation">
          <button class="nav-link {% if loop.first %}active{% endif %}" id="tab-{{ t.key }}" data-bs-toggle="pill"
                  data-bs-target="#pane-{{ t.key }}" type="button" role="tab">
            {{ t.title }}
          </button>
        </li>
      {% endfor %}
    </ul>

    <div class="tab-content mt-3">
      {% for t in tabs %}
        <div class="tab-pane fade {% if loop.first %}show active{% endif %}" id="pane-{{ t.key }}" role="tabpanel">
          <div class="row g-3">
            {% for item in t["items"] %}
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
        </div>
      {% endfor %}
    </div>
  </div>
  {% endif %}

  {% if standalone %}
  <div class="col-12 mt-2">
    <div class="d-flex align-items-center justify-content-between">
      <div class="fw-semibold">Acesso rápido</div>
      <div class="muted small">Pendências / Agenda / Educação</div>
    </div>
  </div>

  {% for item in standalone %}
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
  {% endif %}
</div>

<script>
(function(){
  const tabs = document.getElementById("dashTabs");
  if (!tabs) return;

  const key = "dash_active_tab";
  const saved = localStorage.getItem(key);
  if (saved) {
    const btn = document.getElementById("tab-" + saved);
    if (btn) btn.click();
  }
  tabs.addEventListener("click", (e) => {
    const btn = e.target.closest("button[id^='tab-']");
    if (!btn) return;
    localStorage.setItem(key, btn.id.replace("tab-",""));
  });
})();
</script>
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

    {% if current_client and role in ["admin","equipe"] %}
      <hr class="my-4"/>
      <h5 class="mb-1">Convite para o Portal do Cliente</h5>
      <div class="muted mb-3">Gere um link para o cliente criar usuário (sem OTP).</div>

      <form method="post" action="/client/invite" class="row g-2 align-items-end">
        <input type="hidden" name="client_id" value="{{ current_client.id }}"/>
        <div class="col-md-7">
          <label class="form-label">E-mail do cliente (opcional)</label>
          <input class="form-control" name="invited_email" placeholder="financeiro@cliente.com.br" value=""/>
        </div>
        <div class="col-md-3">
          <button class="btn btn-primary w-100">Gerar link</button>
        </div>
      </form>

      {% if invite_link_url %}
        <div class="mt-3">
          <label class="form-label">Link do convite</label>
          <div class="input-group">
            <input class="form-control" value="{{ invite_link_url }}" readonly/>
            <button class="btn btn-outline-secondary" type="button"
              onclick="navigator.clipboard && navigator.clipboard.writeText('{{ invite_link_url }}')">
              Copiar
            </button>
          </div>
          <div class="muted small mt-1">Envie este link ao cliente. Ele expira automaticamente.</div>
        </div>
      {% endif %}

      {% if recent_invites %}
        <div class="mt-3">
          <div class="fw-semibold mb-2">Convites recentes</div>
          <div class="table-responsive">
            <table class="table table-sm">
              <thead>
                <tr>
                  <th>Criado</th>
                  <th>Status</th>
                  <th>E-mail</th>
                  <th>Expira</th>
                  <th>Link</th>
                </tr>
              </thead>
              <tbody>
                {% for inv in recent_invites %}
                  <tr>
                    <td class="small">{{ inv.created_at }}</td>
                    <td><span class="badge text-bg-light border">{{ inv.status }}</span></td>
                    <td class="small">{{ inv.invited_email or "-" }}</td>
                    <td class="small">{{ inv.expires_at }}</td>
                    <td class="small">
                      {% if inv.link_url %}
                        <a href="{{ inv.link_url }}" target="_blank">Abrir</a>
                      {% else %}
                        -
                      {% endif %}
                    </td>
                  </tr>
                {% endfor %}
              </tbody>
            </table>
          </div>
        </div>
      {% endif %}
    {% endif %}
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
      <div class="muted">Crie equipe e clientes. Vários membros podem estar vinculados ao mesmo cliente.</div>
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
            <div class="d-flex justify-content-between align-items-start gap-3">
              <div style="min-width: 0;">
                <div class="fw-semibold">{{ row.user.name }} <span class="muted">({{ row.user.email }})</span></div>
                <div class="muted small mt-1">
                  Role: <b>{{ row.membership.role }}</b>
                  {% if row.membership.role == "cliente" %}
                    · Cliente: <b>{{ row.client_name or "—" }}</b>
                  {% endif %}
                  · Status: {% if row.is_active %}<span class="badge text-bg-success">ativo</span>{% else %}<span class="badge text-bg-secondary">inativo</span>{% endif %}
                </div>
              </div>

              <div class="text-end">
                {% if row.membership.role == "cliente" %}
                <form class="d-inline" method="post" action="/admin/members/{{ row.membership.id }}/link-client">
                  <select class="form-select form-select-sm" name="client_id" style="min-width: 220px;">
                    <option value="">(sem cliente)</option>
                    {% for c in clients %}
                      <option value="{{ c.id }}" {% if row.membership.client_id==c.id %}selected{% endif %}>{{ c.name }}</option>
                    {% endfor %}
                  </select>
                  <button class="btn btn-sm btn-outline-primary mt-2 w-100">Vincular</button>
                </form>
                {% endif %}
              </div>
            </div>

            <details class="mt-3">
              <summary class="muted small">Permissões (abas)</summary>
              <form method="post" action="/admin/members/{{ row.membership.id }}/features" class="mt-2">
                <div class="row g-2">
                  {% for g in feature_groups %}
                    <div class="col-12">
                      <div class="fw-semibold small">{{ g.title }}</div>
                      <div class="d-flex flex-wrap gap-2 mt-1">
                        {% for fk in g.features %}
                          {% set f = feature_keys[fk] %}
                          <label class="form-check form-check-inline">
                            <input class="form-check-input" type="checkbox" name="features" value="{{ fk }}"
                              {% if fk in row.allowed_features %}checked{% endif %}>
                            <span class="form-check-label">{{ f.title }}</span>
                          </label>
                        {% endfor %}
                      </div>
                    </div>
                  {% endfor %}

                  <div class="col-12 mt-2">
                    <div class="fw-semibold small">Acesso rápido</div>
                    <div class="d-flex flex-wrap gap-2 mt-1">
                      {% for fk in feature_standalone %}
                        {% set f = feature_keys[fk] %}
                        <label class="form-check form-check-inline">
                          <input class="form-check-input" type="checkbox" name="features" value="{{ fk }}"
                            {% if fk in row.allowed_features %}checked{% endif %}>
                          <span class="form-check-label">{{ f.title }}</span>
                        </label>
                      {% endfor %}
                    </div>
                  </div>

                  <div class="col-12 mt-2">
                    <button class="btn btn-sm btn-primary">Salvar permissões</button>
                  </div>
                </div>
              </form>
            </details>
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

        <div class="mb-2">
          <label class="form-label">Vincular ao cliente (opcional)</label>
          <select class="form-select" name="client_id">
            <option value="">(não vincular)</option>
            {% for c in clients %}
              <option value="{{ c.id }}">{{ c.name }}</option>
            {% endfor %}
          </select>
          <div class="form-text">Útil para ter múltiplos usuários do mesmo cliente.</div>
        </div>

        <div class="mb-3">
          <label class="form-label">Criar novo cliente (se não selecionou acima)</label>
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
      <a class="btn btn-primary" href="/pendencias/cliente/novo">Nova</a>
    {% elif role == "cliente" %}
      <a class="btn btn-primary" href="/pendencias/cliente/nova">Nova</a>
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
    <form method="post" action="/pendencias/cliente/novo" enctype="multipart/form-data" class="mt-3">
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
    <div class="d-flex gap-2">
      <a class="btn btn-outline-secondary" href="/pendencias">Voltar</a>
      {% if role in ["admin","equipe"] %}
        <a class="btn btn-outline-primary" href="/pendencias/{{ item.id }}/editar">Editar</a>
        <form method="post" action="/pendencias/{{ item.id }}/excluir" onsubmit="return confirm('Excluir pendência? Remova anexos antes.');">
          <button class="btn btn-outline-danger" type="submit">Excluir</button>
        </form>
      {% endif %}
    </div>
  </div>
  <hr class="my-3"/>
  <pre>{{ item.description }}</pre>

  <hr class="my-3"/>
  <h6>Anexos</h6>
  {% if attachments %}
    <ul>
      {% for a in attachments %}
        <li class="d-flex justify-content-between align-items-center">
          <a href="/download/{{ a.id }}">{{ a.original_filename }}</a>
          {% if role in ["admin","equipe"] %}
            <form method="post" action="/attachments/{{ a.id }}/delete" class="ms-2">
              <input type="hidden" name="next" value="/pendencias/{{ item.id }}">
              <button class="btn btn-outline-danger btn-sm" type="submit">Excluir</button>
            </form>
          {% endif %}
        </li>
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
    {% elif role == "cliente" %}
      <a class="btn btn-primary" href="/documentos/cliente/enviar">Enviar</a>
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
    <div class="d-flex gap-2">
      <a class="btn btn-outline-secondary" href="/documentos">Voltar</a>
      {% if role in ["admin","equipe"] %}
        <a class="btn btn-outline-primary" href="/documentos/{{ doc.id }}/editar">Editar</a>
        <form method="post" action="/documentos/{{ doc.id }}/excluir" onsubmit="return confirm('Excluir documento? Remova anexos antes.');">
          <button class="btn btn-outline-danger" type="submit">Excluir</button>
        </form>
      {% endif %}
    </div>
  </div>

  <hr class="my-3"/>
  <pre>{{ doc.content }}</pre>

  <hr class="my-3"/>
  <h6>Anexos</h6>
  {% if attachments %}
    <ul>
      {% for a in attachments %}
        <li class="d-flex justify-content-between align-items-center">
          <a href="/download/{{ a.id }}">{{ a.original_filename }}</a>
          {% if role in ["admin","equipe"] %}
            <form method="post" action="/attachments/{{ a.id }}/delete" class="ms-2">
              <input type="hidden" name="next" value="/documentos/{{ doc.id }}">
              <button class="btn btn-outline-danger btn-sm" type="submit">Excluir</button>
            </form>
          {% endif %}
        </li>
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
        <div class="col-12">
          <label class="form-label">Serviço/Produto</label>
          <select class="form-select" name="service_name" required>
            <option value="">Selecione...</option>
            {% for s in service_catalog %}
              <option value="{{ s.name }}">{{ s.name }}</option>
            {% endfor %}
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
        <label class="form-label">Serviço/Produto</label>
        <select class="form-select" name="service_name" required>
          <option value="">Selecione...</option>
          {% for s in service_catalog %}
            <option value="{{ s.name }}">{{ s.name }}</option>
          {% endfor %}
        </select>
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
        {% if prop.service_name %} • Serviço: <b>{{ prop.service_name }}</b>{% endif %}
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
        <li class="d-flex justify-content-between align-items-center">
          <a href="/download/{{ a.id }}">{{ a.original_filename }}</a>
          {% if role in ["admin","equipe"] %}
            <form method="post" action="/attachments/{{ a.id }}/delete" class="ms-2">
              <input type="hidden" name="next" value="/financeiro/{{ inv.id }}">
              <button class="btn btn-outline-danger btn-sm" type="submit">Excluir</button>
            </form>
          {% endif %}
        </li>
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
      <div class="col-12">
        <label class="form-label">Serviço/Produto</label>
        <select class="form-select" name="service_name" required>
          <option value="">Selecione...</option>
          {% for s in service_catalog %}
            <option value="{{ s.name }}" {% if prop.service_name==s.name %}selected{% endif %}>{{ s.name }}</option>
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
      <div class="muted">Notas/Boletos de honorários (manual) + sincronizado do Conta Azul.</div>
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
    <div class="muted">Sem cobranças manuais.</div>
  {% endif %}
</div>

<div class="card p-4 mt-3">
  <div class="d-flex justify-content-between align-items-center">
    <div>
      <h5 class="mb-0">Conta Azul</h5>
      <div class="muted small">Sincroniza notas fiscais e contas a receber do ERP (filtrado pelo cliente selecionado).</div>
    </div>
    {% if role in ["admin","equipe"] %}
      <a class="btn btn-outline-secondary" href="/integrations/contaazul">Configurar</a>
    {% endif %}
  </div>

  <hr class="my-3"/>

  {% if not ca_configured %}
    <div class="alert alert-warning">
      Configure <code>CONTA_AZUL_CLIENT_ID</code> e <code>CONTA_AZUL_CLIENT_SECRET</code> no Render.
    </div>
  {% elif not ca_connected %}
    <div class="alert alert-info">
      Conta Azul não conectada. <a href="/integrations/contaazul">Clique aqui para conectar</a>.
    </div>
  {% else %}
    <div class="d-flex flex-wrap align-items-center gap-2">
      <span class="badge text-bg-light border">Conectado</span>
      {% if ca_last_sync %}<span class="muted small">Última sync: {{ ca_last_sync }}</span>{% endif %}
      {% if role in ["admin","equipe"] %}
        <form method="post" action="/financeiro/contaazul/sync">
          <button class="btn btn-sm btn-outline-primary">Sincronizar agora</button>
        </form>
      {% endif %}
    </div>

    {% if role in ["admin","equipe"] and current_client %}
      <div class="border rounded p-3 mt-3">
        <div class="fw-semibold mb-1">Vínculo do cliente (Conta Azul)</div>
        <div class="muted small">
          Cliente: <b>{{ current_client.name }}</b> • Doc: {{ ca_client_doc or "—" }} • E-mail: {{ ca_client_email or "—" }}
        </div>
        <div class="mono small mt-1">person_id: {{ ca_person_id or "—" }}</div>

        <div class="d-flex flex-wrap gap-2 mt-2">
          <form method="post" action="/financeiro/contaazul/auto_vincular">
            <button class="btn btn-sm btn-outline-secondary">Auto-vincular</button>
          </form>

          <form method="post" action="/financeiro/contaazul/vincular" class="d-flex gap-2">
            <input name="person_id" class="form-control form-control-sm" placeholder="UUID do cliente no Conta Azul (Pessoa)" style="min-width: 280px;" />
            <button class="btn btn-sm btn-outline-primary">Salvar vínculo</button>
          </form>
        </div>

        <div class="muted small mt-2">
          Se não aparecer nada após sincronizar, geralmente o documento/e-mail do cliente no Conta Azul está diferente. Nesse caso, cole o UUID da pessoa (Cliente) do Conta Azul aqui.
        </div>
      </div>
    {% endif %}

    <div class="mt-4">
      <h6 class="mb-2">Contas a receber / Boletos</h6>
      {% if ca_receivables %}
        <div class="table-responsive">
          <table class="table table-sm align-middle">
            <thead>
              <tr>
                <th>Venc.</th>
                <th>Descrição</th>
                <th>Status</th>
                <th>Download</th>
                <th>Aberto</th>
                <th>Pago</th>
                <th>Fatura</th>
                <th>Link</th>
                <th>Download</th>
              </tr>
            </thead>
            <tbody>
              {% for r in ca_receivables %}
                <tr>
                  <td class="mono small">{{ r.due_date }}</td>
                  <td>{{ r.description }}</td>
                  <td><span class="badge text-bg-light border">{{ r.status }}</span></td>
                  <td>R$ {{ "%.2f"|format(r.amount_open) }}</td>
                  <td>R$ {{ "%.2f"|format(r.amount_paid) }}</td>
                  <td class="mono small">{% if r.invoice_number %}{{ r.invoice_type }} #{{ r.invoice_number }}{% else %}—{% endif %}</td>
                  <td>
                    {% if r.payment_url %}
                      <a class="btn btn-sm btn-outline-primary" href="{{ r.payment_url }}" target="_blank" rel="noopener">Abrir</a>
                    {% else %}
                      —
                    {% endif %}
                  </td>
                  <td>
                    <a class="btn btn-sm btn-outline-secondary" href="/financeiro/contaazul/receivable/{{ r.id }}/fatura.pdf" target="_blank" rel="noopener">PDF</a>
                  </td>
                </tr>
              {% endfor %}
            </tbody>
          </table>
        </div>
      {% else %}
        <div class="muted small">Nenhuma parcela encontrada. Clique em “Sincronizar agora”.</div>
      {% endif %}
    </div>

    <div class="mt-4">
      <h6 class="mb-2">Notas fiscais</h6>
      {% if ca_invoices %}
        <div class="table-responsive">
          <table class="table table-sm align-middle">
            <thead>
              <tr>
                <th>Data</th>
                <th>Número</th>
                <th>Tipo</th>
                <th>Status</th>
                <th>Download</th>
              </tr>
            </thead>
            <tbody>
              {% for n in ca_invoices %}
                <tr>
                  <td class="mono small">{{ n.issue_date }}</td>
                  <td class="mono small">{{ n.number or "—" }}</td>
                  <td class="mono small">{{ n.invoice_type }}</td>
                  <td><span class="badge text-bg-light border">{{ n.status }}</span></td>
                  <td>
                    {% if n.invoice_type.upper() == "NFSE" %}
                      <a class="btn btn-sm btn-outline-secondary" href="/financeiro/contaazul/invoice/{{ n.id }}/pdf" target="_blank" rel="noopener">PDF</a>
                    {% elif n.invoice_type.upper() == "NFE" %}
                      <a class="btn btn-sm btn-outline-secondary" href="/financeiro/contaazul/invoice/{{ n.id }}/xml" target="_blank" rel="noopener">XML</a>
                    {% else %}
                      —
                    {% endif %}
                  </td>
                </tr>
              {% endfor %}
            </tbody>
          </table>
        </div>
      {% else %}
        <div class="muted small">Nenhuma nota encontrada. Clique em “Sincronizar agora”.</div>
      {% endif %}
    </div>
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
    <div class="d-flex gap-2">
      <a class="btn btn-outline-secondary" href="/financeiro">Voltar</a>
      {% if role in ["admin","equipe"] %}
        <a class="btn btn-outline-primary" href="/financeiro/{{ inv.id }}/editar">Editar</a>
      {% endif %}
    </div>
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
    <div class="d-flex gap-2">
      <a class="btn btn-outline-secondary" href="/financeiro">Voltar</a>
      {% if role in ["admin","equipe"] %}
        <a class="btn btn-outline-primary" href="/financeiro/{{ inv.id }}/editar">Editar</a>
        <form method="post" action="/financeiro/{{ inv.id }}/excluir" onsubmit="return confirm('Excluir lançamento? Remova anexos antes.');">
          <button class="btn btn-outline-danger" type="submit">Excluir</button>
        </form>
      {% endif %}
    </div>
  </div>

  <hr class="my-3"/>
  <pre>{{ inv.notes }}</pre>

  <hr class="my-3"/>
  <h6>Anexos (download)</h6>
  {% if attachments %}
    <ul>
      {% for a in attachments %}
        <li class="d-flex justify-content-between align-items-center">
          <a href="/download/{{ a.id }}">{{ a.original_filename }}</a>
          {% if role in ["admin","equipe"] %}
            <form method="post" action="/attachments/{{ a.id }}/delete" class="ms-2">
              <input type="hidden" name="next" value="/financeiro/{{ inv.id }}">
              <button class="btn btn-outline-danger btn-sm" type="submit">Excluir</button>
            </form>
          {% endif %}
        </li>
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
    "contaazul_settings.html": r"""
{% extends "base.html" %}
{% block content %}
<div class="card p-4">
  <div class="d-flex justify-content-between align-items-start">
    <div>
      <h4 class="mb-1">Integração: Conta Azul</h4>
      <div class="muted">Sincroniza notas e cobranças (boletos) para aparecerem no Financeiro.</div>
    </div>
    <a class="btn btn-outline-secondary" href="/financeiro">Voltar</a>
  </div>

  <hr class="my-3"/>

  {% if not configured %}
    <div class="alert alert-warning">
      Configure as variáveis no Render: <code>CONTA_AZUL_CLIENT_ID</code> e <code>CONTA_AZUL_CLIENT_SECRET</code>.
    </div>
  {% endif %}

  <div class="mb-2">
    <div class="muted small">Redirect URI (cadastre no Portal do Desenvolvedor Conta Azul):</div>
    <div class="mono">{{ redirect_uri }}</div>
  </div>

  {% if connected %}
    <div class="alert alert-success">Conectado{% if last_sync %} • Última sync: {{ last_sync }}{% endif %}</div>
    <form method="post" action="/integrations/contaazul/disconnect" onsubmit="return confirm('Desconectar Conta Azul?');">
      <button class="btn btn-outline-danger">Desconectar</button>
    </form>
  {% else %}
    <div class="alert alert-info">Ainda não conectado.</div>
    <a class="btn btn-primary" href="/integrations/contaazul/connect">Conectar Conta Azul</a>
  {% endif %}
</div>
{% endblock %}
""",
    "fin_list.html": r"""
{% extends "base.html" %}
{% block content %}
<div class="card p-4">
  <div class="d-flex justify-content-between align-items-center">
    <div>
      <h4 class="mb-0">Financeiro</h4>
      <div class="muted">Notas/Boletos de honorários (manual) + sincronizado do Conta Azul.</div>
    </div>
    <div class="d-flex gap-2">
      {% if role in ["admin","equipe"] %}
        <a class="btn btn-outline-secondary" href="/integrations/contaazul">Conta Azul</a>
        {% if ca_connected %}
          <form method="post" action="/financeiro/contaazul/sync">
            <button class="btn btn-outline-primary" type="submit">Sincronizar</button>
          </form>
        {% endif %}
        <a class="btn btn-primary" href="/financeiro/novo">Nova cobrança</a>
      {% endif %}
    </div>
  </div>

  {% if ca_configured and role in ["admin","equipe"] and not ca_connected %}
    <div class="alert alert-warning mt-3">
      Conta Azul não conectado. Vá em <a href="/integrations/contaazul">Integrações → Conta Azul</a>.
    </div>
  {% endif %}

  {% if ca_last_sync %}
    <div class="muted small mt-2">Conta Azul: última sync em {{ ca_last_sync }}</div>
  {% endif %}

  <hr class="my-3"/>
  <h6 class="mb-2">Cobranças (manual)</h6>
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
    <div class="muted">Sem cobranças manuais.</div>
  {% endif %}

  <hr class="my-4"/>
  <h6 class="mb-2">Conta Azul: Boletos / Contas a receber</h6>
  {% if ca_receivables %}
    <div class="list-group">
      {% for r in ca_receivables %}
        <div class="list-group-item">
          <div class="d-flex justify-content-between">
            <div class="fw-semibold">{{ r.description }}</div>
            <span class="badge text-bg-light border">{{ r.status }}</span>
          </div>
          <div class="muted small mt-1">
            Valor: R$ {{ "%.2f"|format(r.amount_total) }} • Aberto: R$ {{ "%.2f"|format(r.amount_open) }}
            {% if r.due_date %} • Venc: {{ r.due_date }}{% endif %}
            {% if r.invoice_type or r.invoice_number %} • {{ r.invoice_type }} {{ r.invoice_number }}{% endif %}
            {% if r.boleto_status %} • Boleto: {{ r.boleto_status }}{% endif %}
          </div>
          {% if r.payment_url %}
            <div class="mt-2">
              <a class="btn btn-sm btn-outline-primary" href="{{ r.payment_url }}" target="_blank" rel="noopener">Abrir link de pagamento</a>
            </div>
          {% endif %}
        </div>
      {% endfor %}
    </div>
  {% else %}
    <div class="muted">Sem itens sincronizados.</div>
  {% endif %}

  <hr class="my-4"/>
  <h6 class="mb-2">Conta Azul: Notas fiscais</h6>
  {% if ca_invoices %}
    <div class="list-group">
      {% for n in ca_invoices %}
        <div class="list-group-item">
          <div class="d-flex justify-content-between">
            <div class="fw-semibold">{{ n.invoice_type }} {{ n.number }}</div>
            <span class="badge text-bg-light border">{{ n.status }}</span>
          </div>
          <div class="muted small mt-1">
            {% if n.issue_date %}Emissão/Competência: {{ n.issue_date }} • {% endif %}
            {% if n.amount %}Valor: R$ {{ "%.2f"|format(n.amount) }} • {% endif %}
            ID: {{ n.external_id }}
          </div>
        </div>
      {% endfor %}
    </div>
  {% else %}
    <div class="muted">Sem notas sincronizadas.</div>
  {% endif %}
</div>
{% endblock %}
""",
})

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


              {% if role in ["admin","equipe"] %}
                <div class="d-flex justify-content-end gap-2 mb-3">
                  <a class="btn btn-outline-secondary btn-sm" href="/consultoria/stages/{{ s.id }}/editar">Editar etapa</a>
                  <form method="post" action="/consultoria/stages/{{ s.id }}/excluir" onsubmit="return confirm('Excluir esta etapa e suas sub-etapas?');">
                    <button class="btn btn-outline-danger btn-sm">Excluir etapa</button>
                  </form>
                </div>
              {% endif %}

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

                          {% if role in ["admin","equipe"] %}
                            <a class="btn btn-outline-secondary btn-sm" href="/consultoria/steps/{{ st.id }}/editar">Editar</a>
                            <form method="post" action="/consultoria/steps/{{ st.id }}/excluir" onsubmit="return confirm('Excluir esta sub-etapa?');">
                              <button class="btn btn-outline-danger btn-sm">Excluir</button>
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

TEMPLATES.update({
    "agenda.html": r"""
{% extends "base.html" %}
{% block content %}
<div class="card p-4">
  <div class="d-flex justify-content-between align-items-center">
    <div>
      <h4 class="mb-0">Agenda</h4>
      <div class="muted">Agendamentos (Outlook Bookings)</div>
    </div>
    <a class="btn btn-outline-primary" href="{{ bookings_url }}" target="_blank" rel="noopener">Abrir em nova aba</a>
  </div>
  <hr class="my-3"/>
  <div class="ratio ratio-16x9">
    <iframe src="{{ bookings_url }}" title="Agenda" loading="lazy" referrerpolicy="no-referrer"></iframe>
  </div>
  <div class="muted small mt-3">Se o iframe não carregar, clique em “Abrir em nova aba”.</div>
</div>
{% endblock %}
""",

    "pending_new_client.html": r"""
{% extends "base.html" %}
{% block content %}
<div class="card p-4">
  <h4>Nova Pendência (Cliente)</h4>
  <div class="muted">Crie um pedido/pendência e envie anexos ao escritório.</div>
  <form method="post" action="/pendencias/cliente/nova" enctype="multipart/form-data" class="mt-3">
    <div class="row g-3">
      <div class="col-12">
        <label class="form-label">Título</label>
        <input class="form-control" name="title" required />
      </div>
      <div class="col-12">
        <label class="form-label">Descrição</label>
        <textarea class="form-control" name="description" rows="4"></textarea>
      </div>
      <div class="col-md-6">
        <label class="form-label">Prazo (opcional)</label>
        <input class="form-control mono" name="due_date" placeholder="2026-03-31" />
      </div>
      <div class="col-12">
        <label class="form-label">Anexar arquivo (opcional)</label>
        <input class="form-control" type="file" name="file" />
      </div>
    </div>
    <div class="mt-4 d-flex gap-2">
      <button class="btn btn-primary" type="submit">Criar</button>
      <a class="btn btn-outline-secondary" href="/pendencias">Cancelar</a>
    </div>
  </form>
</div>
{% endblock %}
""",

    "docs_send_client.html": r"""
{% extends "base.html" %}
{% block content %}
<div class="card p-4">
  <h4>Enviar Documento (Cliente)</h4>
  <div class="muted">Envie um documento ao escritório e acompanhe o status.</div>
  <form method="post" action="/documentos/cliente/enviar" enctype="multipart/form-data" class="mt-3">
    <div class="row g-3">
      <div class="col-12">
        <label class="form-label">Título</label>
        <input class="form-control" name="title" required />
      </div>
      <div class="col-12">
        <label class="form-label">Mensagem (opcional)</label>
        <textarea class="form-control" name="message" rows="3"></textarea>
      </div>
      <div class="col-12">
        <label class="form-label">Arquivo</label>
        <input class="form-control" type="file" name="file" required />
      </div>
    </div>
    <div class="mt-4 d-flex gap-2">
      <button class="btn btn-primary" type="submit">Enviar</button>
      <a class="btn btn-outline-secondary" href="/documentos">Cancelar</a>
    </div>
  </form>
</div>
{% endblock %}
""",

    "docs_edit.html": r"""
{% extends "base.html" %}
{% block content %}
<div class="card p-4">
  <div class="d-flex justify-content-between align-items-center">
    <div>
      <h4 class="mb-0">Editar Documento</h4>
      <div class="muted">{{ doc.title }}</div>
    </div>
    <a class="btn btn-outline-secondary" href="/documentos/{{ doc.id }}">Voltar</a>
  </div>
  <hr class="my-3"/>
  <form method="post" action="/documentos/{{ doc.id }}/editar">
    <div class="row g-3">
      <div class="col-md-8">
        <label class="form-label">Título</label>
        <input class="form-control" name="title" value="{{ doc.title }}" required />
      </div>
      <div class="col-md-4">
        <label class="form-label">Status</label>
        <select class="form-select" name="status">
          <option value="rascunho" {% if doc.status=="rascunho" %}selected{% endif %}>rascunho</option>
          <option value="aguardando_cliente" {% if doc.status=="aguardando_cliente" %}selected{% endif %}>aguardando_cliente</option>
          <option value="cliente_enviou" {% if doc.status=="cliente_enviou" %}selected{% endif %}>cliente_enviou</option>
          <option value="concluido" {% if doc.status=="concluido" %}selected{% endif %}>concluido</option>
        </select>
      </div>
      <div class="col-12">
        <label class="form-label">Conteúdo</label>
        <textarea class="form-control" name="content" rows="6" required>{{ doc.content }}</textarea>
      </div>
    </div>
    <div class="mt-4 d-flex gap-2">
      <button class="btn btn-primary" type="submit">Salvar</button>
      <a class="btn btn-outline-secondary" href="/documentos/{{ doc.id }}">Cancelar</a>
    </div>
  </form>
  <hr class="my-4"/>
  <form method="post" action="/documentos/{{ doc.id }}/excluir" onsubmit="return confirm('Excluir documento? Remova anexos antes.');">
    <button class="btn btn-outline-danger" type="submit">Excluir documento</button>
  </form>
</div>
{% endblock %}
""",

    "pending_edit.html": r"""
{% extends "base.html" %}
{% block content %}
<div class="card p-4">
  <div class="d-flex justify-content-between align-items-center">
    <div>
      <h4 class="mb-0">Editar Pendência</h4>
      <div class="muted">{{ item.title }}</div>
    </div>
    <a class="btn btn-outline-secondary" href="/pendencias/{{ item.id }}">Voltar</a>
  </div>
  <hr class="my-3"/>
  <form method="post" action="/pendencias/{{ item.id }}/editar">
    <div class="row g-3">
      <div class="col-md-8">
        <label class="form-label">Título</label>
        <input class="form-control" name="title" value="{{ item.title }}" required />
      </div>
      <div class="col-md-4">
        <label class="form-label">Status</label>
        <select class="form-select" name="status">
          <option value="aberto" {% if item.status=="aberto" %}selected{% endif %}>aberto</option>
          <option value="aguardando_cliente" {% if item.status=="aguardando_cliente" %}selected{% endif %}>aguardando_cliente</option>
          <option value="cliente_enviou" {% if item.status=="cliente_enviou" %}selected{% endif %}>cliente_enviou</option>
          <option value="concluido" {% if item.status=="concluido" %}selected{% endif %}>concluido</option>
        </select>
      </div>
      <div class="col-md-6">
        <label class="form-label">Prazo (AAAA-MM-DD)</label>
        <input class="form-control mono" name="due_date" value="{{ item.due_date }}" />
      </div>
      <div class="col-12">
        <label class="form-label">Descrição</label>
        <textarea class="form-control" name="description" rows="5">{{ item.description }}</textarea>
      </div>
    </div>
    <div class="mt-4 d-flex gap-2">
      <button class="btn btn-primary" type="submit">Salvar</button>
      <a class="btn btn-outline-secondary" href="/pendencias/{{ item.id }}">Cancelar</a>
    </div>
  </form>
  <hr class="my-4"/>
  <form method="post" action="/pendencias/{{ item.id }}/excluir" onsubmit="return confirm('Excluir pendência? Remova anexos antes.');">
    <button class="btn btn-outline-danger" type="submit">Excluir pendência</button>
  </form>
</div>
{% endblock %}
""",

    "fin_edit.html": r"""
{% extends "base.html" %}
{% block content %}
<div class="card p-4">
  <div class="d-flex justify-content-between align-items-center">
    <div>
      <h4 class="mb-0">Editar Financeiro</h4>
      <div class="muted">{{ inv.title }}</div>
    </div>
    <a class="btn btn-outline-secondary" href="/financeiro/{{ inv.id }}">Voltar</a>
  </div>
  <hr class="my-3"/>
  <form method="post" action="/financeiro/{{ inv.id }}/editar">
    <div class="row g-3">
      <div class="col-md-8">
        <label class="form-label">Título</label>
        <input class="form-control" name="title" value="{{ inv.title }}" required />
      </div>
      <div class="col-md-4">
        <label class="form-label">Status</label>
        <select class="form-select" name="status">
          <option value="emitido" {% if inv.status=="emitido" %}selected{% endif %}>emitido</option>
          <option value="pago" {% if inv.status=="pago" %}selected{% endif %}>pago</option>
          <option value="atrasado" {% if inv.status=="atrasado" %}selected{% endif %}>atrasado</option>
          <option value="cancelado" {% if inv.status=="cancelado" %}selected{% endif %}>cancelado</option>
        </select>
      </div>
      <div class="col-md-4">
        <label class="form-label">Valor (R$)</label>
        <input class="form-control" name="amount_brl" type="number" step="0.01" min="0" value="{{ inv.amount_brl }}" />
      </div>
      <div class="col-md-4">
        <label class="form-label">Vencimento (AAAA-MM-DD)</label>
        <input class="form-control mono" name="due_date" value="{{ inv.due_date }}" />
      </div>
      <div class="col-12">
        <label class="form-label">Notas</label>
        <textarea class="form-control" name="notes" rows="4">{{ inv.notes }}</textarea>
      </div>
    </div>
    <div class="mt-4 d-flex gap-2">
      <button class="btn btn-primary" type="submit">Salvar</button>
      <a class="btn btn-outline-secondary" href="/financeiro/{{ inv.id }}">Cancelar</a>
    </div>
  </form>
  <hr class="my-4"/>
  <form method="post" action="/financeiro/{{ inv.id }}/excluir" onsubmit="return confirm('Excluir lançamento? Remova anexos antes.');">
    <button class="btn btn-outline-danger" type="submit">Excluir lançamento</button>
  </form>
</div>
{% endblock %}
""",
})

TEMPLATES.update({
    "tasks_list.html": r"""
{% extends "base.html" %}
{% block content %}
<div class="card p-4">
  <div class="d-flex justify-content-between align-items-center">
    <div>
      <h4 class="mb-0">Tarefas</h4>
      <div class="muted">Kanban por status • filtros • prazos • prioridade</div>
    </div>
    {% if role in ["admin","equipe"] %}
      <a class="btn btn-primary" href="/tarefas/nova{% if filter_client_id %}?client_id={{ filter_client_id }}{% endif %}">Nova tarefa</a>
    {% endif %}
  </div>

  <hr class="my-3"/>

  {% if role in ["admin","equipe"] %}
    <form method="get" action="/tarefas" class="row g-2 align-items-end mb-3">
      <div class="col-md-3">
        <label class="form-label">Cliente</label>
        <select class="form-select" name="client_id">
          <option value="0" {% if filter_client_id==0 %}selected{% endif %}>Todos</option>
          {% for c in clients %}
            <option value="{{ c.id }}" {% if filter_client_id==c.id %}selected{% endif %}>{{ c.name }}</option>
          {% endfor %}
        </select>
      </div>

      <div class="col-md-3">
        <label class="form-label">Responsável</label>
        <select class="form-select" name="assignee_user_id">
          <option value="0" {% if filter_assignee_user_id==0 %}selected{% endif %}>Todos</option>
          <option value="-1" {% if filter_assignee_user_id==-1 %}selected{% endif %}>Sem responsável</option>
          {% for u in assignees %}
            <option value="{{ u.id }}" {% if filter_assignee_user_id==u.id %}selected{% endif %}>{{ u.name }}</option>
          {% endfor %}
        </select>
      </div>

      <div class="col-md-2">
        <label class="form-label">Status</label>
        <select class="form-select" name="status">
          <option value="" {% if not filter_status %}selected{% endif %}>Todos</option>
          <option value="nao_iniciada" {% if filter_status=="nao_iniciada" %}selected{% endif %}>nao_iniciada</option>
          <option value="em_andamento" {% if filter_status=="em_andamento" %}selected{% endif %}>em_andamento</option>
          <option value="concluida" {% if filter_status=="concluida" %}selected{% endif %}>concluida</option>
        </select>
      </div>

      <div class="col-md-2">
        <label class="form-label">Prioridade</label>
        <select class="form-select" name="priority">
          <option value="" {% if not filter_priority %}selected{% endif %}>Todas</option>
          <option value="baixa" {% if filter_priority=="baixa" %}selected{% endif %}>baixa</option>
          <option value="media" {% if filter_priority=="media" %}selected{% endif %}>media</option>
          <option value="alta" {% if filter_priority=="alta" %}selected{% endif %}>alta</option>
        </select>
      </div>

      <div class="col-md-2">
        <label class="form-label">Prazo</label>
        <select class="form-select" name="due">
          <option value="" {% if not filter_due %}selected{% endif %}>Todos</option>
          <option value="atrasadas" {% if filter_due=="atrasadas" %}selected{% endif %}>atrasadas</option>
          <option value="hoje" {% if filter_due=="hoje" %}selected{% endif %}>hoje</option>
          <option value="7dias" {% if filter_due=="7dias" %}selected{% endif %}>7 dias</option>
          <option value="sem_prazo" {% if filter_due=="sem_prazo" %}selected{% endif %}>sem prazo</option>
        </select>
      </div>

      <div class="col-12 d-flex gap-2 align-items-center mt-1">
        <div class="form-check">
          <input class="form-check-input" type="checkbox" name="mine" value="1" id="mine" {% if filter_mine==1 %}checked{% endif %}>
          <label class="form-check-label" for="mine">Minhas</label>
        </div>
        <button class="btn btn-outline-primary" type="submit">Aplicar</button>
        <a class="btn btn-outline-secondary" href="/tarefas">Limpar</a>
      </div>
    </form>
  {% endif %}

  <div class="row g-3">
    {% for col in columns %}
      <div class="col-12 col-lg-4">
        <div class="card p-3 h-100">
          <div class="fw-semibold mb-2">{{ col.label }} <span class="muted">({{ col.count }})</span></div>
          {% if col.tasks %}
            <div class="vstack gap-2">
              {% for t in col.tasks %}
                <a class="card p-3" href="/tarefas/{{ t.id }}">
                  <div class="d-flex justify-content-between align-items-start">
                    <div class="fw-semibold">{{ t.title }}</div>
                    <span class="badge text-bg-light border">{{ t.priority }}</span>
                  </div>
                  <div class="muted small mt-1">
                    {% if role in ["admin","equipe"] and filter_client_id==0 and t.client_name %}
                      Cliente: {{ t.client_name }} •
                    {% endif %}
                    {% if t.due_date %}Prazo: {{ t.due_date }} • {% endif %}
                    {% if t.assignee_name %}Resp: {{ t.assignee_name }}{% endif %}
                  </div>
                  {% if t.visible_to_client %}
                    <div class="mt-2"><span class="badge text-bg-light border">visível ao cliente</span></div>
                  {% endif %}
                </a>
              {% endfor %}
            </div>
          {% else %}
            <div class="muted small">Sem tarefas.</div>
          {% endif %}
        </div>
      </div>
    {% endfor %}
  </div>
</div>
{% endblock %}
""",

    "tasks_new.html": r"""
{% extends "base.html" %}
{% block content %}
<div class="card p-4">
  <h4>Nova tarefa</h4>
  <div class="muted">Crie uma tarefa para um cliente, defina prazo, prioridade e visibilidade.</div>

  {% if not clients %}
    <div class="alert alert-warning mt-3">Nenhum cliente cadastrado.</div>
    <a class="btn btn-outline-secondary" href="/tarefas">Voltar</a>
  {% else %}
    <form method="post" action="/tarefas/nova" class="mt-3">
      <div class="row g-3">
        <div class="col-md-6">
          <label class="form-label">Cliente</label>
          <select class="form-select" name="client_id" required>
            {% for c in clients %}
              <option value="{{ c.id }}" {% if prefill_client and c.id==prefill_client.id %}selected{% endif %}>{{ c.name }}</option>
            {% endfor %}
          </select>
        </div>

        <div class="col-md-6">
          <label class="form-label">Responsável (opcional)</label>
          <select class="form-select" name="assignee_user_id">
            <option value="">—</option>
            {% for u in assignees %}
              <option value="{{ u.id }}">{{ u.name }} ({{ u.role }})</option>
            {% endfor %}
          </select>
        </div>

        <div class="col-12">
          <label class="form-label">Título</label>
          <input class="form-control" name="title" required />
        </div>

        <div class="col-12">
          <label class="form-label">Descrição</label>
          <textarea class="form-control" name="description" rows="4"></textarea>
        </div>

        <div class="col-md-4">
          <label class="form-label">Status</label>
          <select class="form-select" name="status">
            <option value="nao_iniciada">nao_iniciada</option>
            <option value="em_andamento">em_andamento</option>
            <option value="concluida">concluida</option>
          </select>
        </div>

        <div class="col-md-4">
          <label class="form-label">Prioridade</label>
          <select class="form-select" name="priority">
            <option value="baixa">baixa</option>
            <option value="media" selected>media</option>
            <option value="alta">alta</option>
          </select>
        </div>

        <div class="col-md-4">
          <label class="form-label">Prazo (AAAA-MM-DD)</label>
          <input class="form-control mono" name="due_date" />
        </div>

        <div class="col-md-6">
          <div class="form-check mt-4">
            <input class="form-check-input" type="checkbox" name="visible_to_client" value="1" id="vis">
            <label class="form-check-label" for="vis">Visível ao cliente</label>
          </div>
        </div>

        <div class="col-md-6">
          <div class="form-check mt-4">
            <input class="form-check-input" type="checkbox" name="client_action" value="1" id="ca">
            <label class="form-check-label" for="ca">Cliente pode concluir</label>
          </div>
        </div>
      </div>

      <div class="mt-4 d-flex gap-2">
        <button class="btn btn-primary" type="submit">Criar</button>
        <a class="btn btn-outline-secondary" href="/tarefas">Cancelar</a>
      </div>
    </form>
  {% endif %}
</div>
{% endblock %}
""",

    "tasks_detail.html": r"""
{% extends "base.html" %}
{% block content %}
<div class="card p-4">
  <div class="d-flex justify-content-between align-items-start">
    <div>
      <h4 class="mb-1">{{ task.title }}</h4>
      <div class="muted">
        Status: <b>{{ task.status }}</b> • Prioridade: <b>{{ task.priority }}</b>
        {% if task.due_date %} • Prazo: <b>{{ task.due_date }}</b>{% endif %}
        {% if assignee_name %} • Resp: <b>{{ assignee_name }}</b>{% endif %}
      </div>
      {% if task.visible_to_client %}<div class="mt-2"><span class="badge text-bg-light border">visível ao cliente</span></div>{% endif %}
    </div>
    <div class="d-flex gap-2">
      <a class="btn btn-outline-secondary" href="/tarefas">Voltar</a>
      {% if role in ["admin","equipe"] %}
        <a class="btn btn-outline-primary" href="/tarefas/{{ task.id }}/editar">Editar</a>
      {% endif %}
    </div>
  </div>

  {% if task.description %}
    <hr class="my-3"/>
    <pre>{{ task.description }}</pre>
  {% endif %}

  <hr class="my-3"/>
  <div class="d-flex gap-2 flex-wrap">
    {% if role in ["admin","equipe"] %}
      <form method="post" action="/tarefas/{{ task.id }}/status">
        <input type="hidden" name="status" value="nao_iniciada"/>
        <button class="btn btn-outline-secondary btn-sm" type="submit">Não iniciada</button>
      </form>
      <form method="post" action="/tarefas/{{ task.id }}/status">
        <input type="hidden" name="status" value="em_andamento"/>
        <button class="btn btn-outline-secondary btn-sm" type="submit">Em andamento</button>
      </form>
      <form method="post" action="/tarefas/{{ task.id }}/status">
        <input type="hidden" name="status" value="concluida"/>
        <button class="btn btn-outline-secondary btn-sm" type="submit">Concluída</button>
      </form>
    {% endif %}

    {% if role=="cliente" and task.client_action %}
      <form method="post" action="/tarefas/{{ task.id }}/toggle">
        <button class="btn btn-outline-primary btn-sm" type="submit">
          {% if task.status=="concluida" %}Desmarcar conclusão{% else %}Marcar como concluída{% endif %}
        </button>
      </form>
    {% endif %}
  </div>

  {% if role in ["admin","equipe"] %}
    <hr class="my-3"/>
    <form method="post" action="/tarefas/{{ task.id }}/excluir" class="card p-3">
      <div class="fw-semibold">Excluir (seguro)</div>
      <div class="muted small">Para excluir, digite <b>EXCLUIR</b> e confirme.</div>
      <div class="row g-2 align-items-end mt-2">
        <div class="col-md-6">
          <input class="form-control" name="confirm" placeholder="EXCLUIR" required />
        </div>
        <div class="col-md-3">
          <button class="btn btn-outline-danger w-100" type="submit">Excluir</button>
        </div>
      </div>
    </form>
  {% endif %}

  <hr class="my-3"/>
  <h5>Comentários</h5>

  {% if comments %}
    <div class="list-group mb-3">
      {% for c in comments %}
        <div class="list-group-item">
          <div class="d-flex justify-content-between">
            <div class="fw-semibold">{{ c.author_name }}</div>
            <div class="muted small">{{ c.created_at }}</div>
          </div>
          <div class="mt-1">{{ c.message }}</div>
        </div>
      {% endfor %}
    </div>
  {% else %}
    <div class="muted mb-3">Sem comentários.</div>
  {% endif %}

  <form method="post" action="/tarefas/{{ task.id }}/comentario" class="card p-3">
    <label class="form-label fw-semibold">Adicionar comentário</label>
    <textarea class="form-control" name="message" rows="3" required></textarea>
    <div class="mt-2">
      <button class="btn btn-primary" type="submit">Enviar</button>
    </div>
  </form>
</div>
{% endblock %}
""",

    "tasks_edit.html": r"""
{% extends "base.html" %}
{% block content %}
<div class="card p-4">
  <div class="d-flex justify-content-between align-items-start">
    <div>
      <h4 class="mb-1">Editar tarefa</h4>
      <div class="muted">{{ task.title }}</div>
    </div>
    <a class="btn btn-outline-secondary" href="/tarefas/{{ task.id }}">Voltar</a>
  </div>

  <hr class="my-3"/>

  <form method="post" action="/tarefas/{{ task.id }}/editar">
    <div class="row g-3">
      <div class="col-md-6">
        <label class="form-label">Cliente</label>
        <select class="form-select" name="client_id" required>
          {% for c in clients %}
            <option value="{{ c.id }}" {% if c.id==task.client_id %}selected{% endif %}>{{ c.name }}</option>
          {% endfor %}
        </select>
      </div>

      <div class="col-md-6">
        <label class="form-label">Responsável (opcional)</label>
        <select class="form-select" name="assignee_user_id">
          <option value="">—</option>
          {% for u in assignees %}
            <option value="{{ u.id }}" {% if task.assignee_user_id==u.id %}selected{% endif %}>{{ u.name }} ({{ u.role }})</option>
          {% endfor %}
        </select>
      </div>

      <div class="col-12">
        <label class="form-label">Título</label>
        <input class="form-control" name="title" value="{{ task.title }}" required />
      </div>

      <div class="col-12">
        <label class="form-label">Descrição</label>
        <textarea class="form-control" name="description" rows="4">{{ task.description }}</textarea>
      </div>

      <div class="col-md-4">
        <label class="form-label">Status</label>
        <select class="form-select" name="status">
          <option value="nao_iniciada" {% if task.status=="nao_iniciada" %}selected{% endif %}>nao_iniciada</option>
          <option value="em_andamento" {% if task.status=="em_andamento" %}selected{% endif %}>em_andamento</option>
          <option value="concluida" {% if task.status=="concluida" %}selected{% endif %}>concluida</option>
        </select>
      </div>

      <div class="col-md-4">
        <label class="form-label">Prioridade</label>
        <select class="form-select" name="priority">
          <option value="baixa" {% if task.priority=="baixa" %}selected{% endif %}>baixa</option>
          <option value="media" {% if task.priority=="media" %}selected{% endif %}>media</option>
          <option value="alta" {% if task.priority=="alta" %}selected{% endif %}>alta</option>
        </select>
      </div>

      <div class="col-md-4">
        <label class="form-label">Prazo (AAAA-MM-DD)</label>
        <input class="form-control mono" name="due_date" value="{{ task.due_date }}" />
      </div>

      <div class="col-md-6">
        <div class="form-check mt-4">
          <input class="form-check-input" type="checkbox" name="visible_to_client" value="1" id="vis" {% if task.visible_to_client %}checked{% endif %}>
          <label class="form-check-label" for="vis">Visível ao cliente</label>
        </div>
      </div>

      <div class="col-md-6">
        <div class="form-check mt-4">
          <input class="form-check-input" type="checkbox" name="client_action" value="1" id="ca" {% if task.client_action %}checked{% endif %}>
          <label class="form-check-label" for="ca">Cliente pode concluir</label>
        </div>
      </div>
    </div>

    <div class="mt-4 d-flex gap-2">
      <button class="btn btn-primary" type="submit">Salvar</button>
      <a class="btn btn-outline-secondary" href="/tarefas/{{ task.id }}">Cancelar</a>
    </div>
  </form>
</div>
{% endblock %}
""",
})

# ----------------------------
# Perfil: templates (override + novos)
# ----------------------------
TEMPLATES.update({
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

    {% if current_client %}
      <div class="card p-4 mt-3">
        <div class="d-flex justify-content-between align-items-start">
          <div>
            <h5 class="mb-1">Evolução</h5>
            <div class="muted">Score 0–100 (processos + financeiro + NPS)</div>
          </div>
          <a class="btn btn-primary btn-sm" href="/perfil/avaliacao/nova">Nova avaliação</a>
        </div>

        {% if latest_score is not none %}
          <div class="mt-3">
            <div class="d-flex justify-content-between">
              <div class="fw-semibold">Score atual</div>
              <div class="fw-semibold">{{ "%.1f"|format(latest_score) }}</div>
            </div>
            {% if delta is not none %}
              <div class="muted small">Variação vs. anterior: <b>{{ delta }}</b></div>
            {% else %}
              <div class="muted small">Ainda sem comparação (precisa de 2 avaliações).</div>
            {% endif %}
          </div>
        {% else %}
          <div class="alert alert-info mt-3">Nenhuma avaliação registrada ainda.</div>
        {% endif %}
      </div>
    {% endif %}
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
            <a class="btn btn-outline-primary" href="/perfil/avaliacao/nova">Nova avaliação</a>
          </div>
        </form>

        <hr class="my-4"/>
        <h6 class="mb-2">Histórico de avaliações</h6>

        {% if snapshots %}
          <div class="table-responsive">
            <table class="table table-sm align-middle">
              <thead>
                <tr>
                  <th>Data</th>
                  <th>Total</th>
                  <th>Processos</th>
                  <th>Financeiro</th>
                  <th>NPS</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {% for s in snapshots %}
                  <tr>
                    <td class="mono">{{ s.created_at }}</td>
                    <td><b>{{ "%.1f"|format(s.score_total) }}</b></td>
                    <td>{{ "%.1f"|format(s.score_process) }}</td>
                    <td>{{ "%.1f"|format(s.score_financial) }}</td>
                    <td>{{ s.nps_score }}</td>
                    <td><a class="btn btn-outline-secondary btn-sm" href="/perfil/avaliacao/{{ s.id }}">Ver</a></td>
                  </tr>
                {% endfor %}
              </tbody>
            </table>
          </div>
        {% else %}
          <div class="muted">Sem avaliações ainda.</div>
        {% endif %}
      {% endif %}
    </div>
  </div>
</div>
{% endblock %}
""",

    "perfil_snapshot_new.html": r"""
{% extends "base.html" %}
{% block content %}
<div class="card p-4">
  <div class="d-flex justify-content-between align-items-center">
    <div>
      <h4 class="mb-0">Nova Avaliação do Cliente</h4>
      <div class="muted">“Foto do momento” + score de evolução</div>
    </div>
    <a class="btn btn-outline-secondary" href="/perfil">Voltar</a>
  </div>

  <hr class="my-3"/>

  {% if not current_client %}
    <div class="alert alert-warning">Nenhum cliente selecionado.</div>
  {% else %}
    <div class="mb-2"><span class="muted">Cliente:</span> <b>{{ current_client.name }}</b></div>

    <form method="post" action="/perfil/avaliacao/nova">
      <h5 class="mt-3">Números (do momento)</h5>
      <div class="row g-3">
        <div class="col-md-6">
          <label class="form-label">Faturamento mensal (R$)</label>
          <input class="form-control" name="revenue_monthly_brl" type="number" step="0.01" min="0" value="{{ current_client.revenue_monthly_brl }}" />
        </div>
        <div class="col-md-6">
          <label class="form-label">Dívida total (R$)</label>
          <input class="form-control" name="debt_total_brl" type="number" step="0.01" min="0" value="{{ current_client.debt_total_brl }}" />
        </div>
        <div class="col-md-6">
          <label class="form-label">Caixa (R$)</label>
          <input class="form-control" name="cash_balance_brl" type="number" step="0.01" min="0" value="{{ current_client.cash_balance_brl }}" />
        </div>
        <div class="col-md-6">
          <label class="form-label">Funcionários</label>
          <input class="form-control" name="employees_count" type="number" min="0" value="{{ current_client.employees_count }}" />
        </div>
        <div class="col-md-6">
          <label class="form-label">NPS (0 a 10)</label>
          <input class="form-control" name="nps_score" type="number" min="0" max="10" value="0" />
          <div class="form-text">0 = nada provável recomendar / 10 = muito provável.</div>
        </div>
        <div class="col-12">
          <label class="form-label">Observações (opcional)</label>
          <textarea class="form-control" name="notes" rows="3" placeholder="Contexto, mudanças recentes, dor principal..."></textarea>
        </div>
      </div>

      <hr class="my-4"/>

      <h5>Processos (checklist)</h5>
      <div class="muted mb-2">Marque o que já está implementado hoje.</div>

      <div class="row g-2">
        {% for q in survey %}
          <div class="col-12">
            <div class="form-check">
              <input class="form-check-input" type="checkbox" name="{{ q.id }}" value="1" id="{{ q.id }}">
              <label class="form-check-label" for="{{ q.id }}">{{ q.q }}</label>
            </div>
          </div>
        {% endfor %}
      </div>

      <div class="mt-4 d-flex gap-2">
        <button class="btn btn-primary" type="submit">Salvar avaliação</button>
        <a class="btn btn-outline-secondary" href="/perfil">Cancelar</a>
      </div>
    </form>
  {% endif %}
</div>
{% endblock %}
""",

    "perfil_snapshot_detail.html": r"""
{% extends "base.html" %}
{% block content %}
<div class="card p-4">
  <div class="d-flex justify-content-between align-items-start">
    <div>
      <h4 class="mb-1">Avaliação</h4>
      <div class="muted">Cliente: <b>{{ client.name }}</b> • <span class="mono">{{ snap.created_at }}</span></div>
    </div>
    <a class="btn btn-outline-secondary" href="/perfil">Voltar</a>
  </div>

  <hr class="my-3"/>

  <div class="row g-3">
    <div class="col-md-4">
      <div class="card p-3">
        <div class="muted small">Score total</div>
        <div class="fs-4 fw-bold">{{ "%.1f"|format(snap.score_total) }}</div>
      </div>
    </div>
    <div class="col-md-4">
      <div class="card p-3">
        <div class="muted small">Processos</div>
        <div class="fs-4 fw-bold">{{ "%.1f"|format(snap.score_process) }}</div>
      </div>
    </div>
    <div class="col-md-4">
      <div class="card p-3">
        <div class="muted small">Financeiro</div>
        <div class="fs-4 fw-bold">{{ "%.1f"|format(snap.score_financial) }}</div>
      </div>
    </div>
  </div>

  <hr class="my-3"/>

  <h6>Números</h6>
  <div class="row g-2">
    <div class="col-md-3"><span class="muted">Faturamento:</span> R$ {{ "%.2f"|format(snap.revenue_monthly_brl) }}</div>
    <div class="col-md-3"><span class="muted">Dívida:</span> R$ {{ "%.2f"|format(snap.debt_total_brl) }}</div>
    <div class="col-md-3"><span class="muted">Caixa:</span> R$ {{ "%.2f"|format(snap.cash_balance_brl) }}</div>
    <div class="col-md-3"><span class="muted">Funcionários:</span> {{ snap.employees_count }}</div>
    <div class="col-md-3"><span class="muted">NPS:</span> {{ snap.nps_score }}</div>
  </div>

  {% if snap.notes %}
    <hr class="my-3"/>
    <h6>Observações</h6>
    <pre>{{ snap.notes }}</pre>
  {% endif %}

  <hr class="my-3"/>
  <h6>Checklist</h6>
  <ul class="mb-0">
    {% for q in survey %}
      <li>
        {% if answers.get(q.id) %}✅{% else %}⬜{% endif %}
        {{ q.q }}
      </li>
    {% endfor %}
  </ul>
</div>
{% endblock %}
""",
})

TEMPLATES.update({
    "crm_list.html": r"""
{% extends "base.html" %}
{% block content %}
<div class="card p-4">
  <div class="d-flex justify-content-between align-items-center">
    <div>
      <h4 class="mb-0">CRM (Negócios)</h4>
      <div class="muted">Funil comercial</div>
    </div>
    {% if role in ["admin","equipe"] %}
      <a class="btn btn-primary" href="/negocios/novo">Novo negócio</a>
    {% endif %}
  </div>

  <hr class="my-3"/>

  <form method="get" action="/negocios" class="row g-2 align-items-end mb-3">
    <div class="col-md-4">
      <label class="form-label">Cliente</label>
      <select class="form-select" name="client_id">
        <option value="0" {% if filter_client_id==0 %}selected{% endif %}>Todos</option>
        {% for c in clients %}
          <option value="{{ c.id }}" {% if filter_client_id==c.id %}selected{% endif %}>{{ c.name }}</option>
        {% endfor %}
      </select>
    </div>
    <div class="col-md-4">
      <label class="form-label">Responsável</label>
      <select class="form-select" name="owner_user_id">
        <option value="0" {% if filter_owner_user_id==0 %}selected{% endif %}>Todos</option>
        <option value="-1" {% if filter_owner_user_id==-1 %}selected{% endif %}>Sem responsável</option>
        {% for u in owners %}
          <option value="{{ u.id }}" {% if filter_owner_user_id==u.id %}selected{% endif %}>{{ u.name }}</option>
        {% endfor %}
      </select>
    </div>
    <div class="col-md-4">
      <label class="form-label">Etapa</label>
      <select class="form-select" name="stage">
        <option value="" {% if not filter_stage %}selected{% endif %}>Todas</option>
        {% for s in stages %}
          <option value="{{ s.key }}" {% if filter_stage==s.key %}selected{% endif %}>{{ s.label }}</option>
        {% endfor %}
      </select>
    </div>
    <div class="col-12 d-flex gap-2">
      <button class="btn btn-outline-primary" type="submit">Filtrar</button>
      <a class="btn btn-outline-secondary" href="/negocios">Limpar</a>
    </div>
  </form>

  <div class="row g-3">
    {% for col in columns %}
      <div class="col-lg-4">
        <div class="card p-3">
          <div class="d-flex justify-content-between align-items-center">
            <div class="fw-semibold">{{ col.label }}</div>
            <span class="badge text-bg-light border">{{ col.count }}</span>
          </div>
          <hr class="my-2"/>
          {% if col.deals %}
            <div class="d-flex flex-column gap-2">
              {% for d in col.deals %}
                <a class="card p-3" href="/negocios/{{ d.id }}" style="border:1px solid rgba(0,0,0,.08); border-radius:14px;">
                  <div class="fw-semibold">{{ d.title }}</div>
                  <div class="muted small">{{ d.client_name }}{% if d.service_name %} • {{ d.service_name }}{% endif %}</div>
                  <div class="muted small">
                    {% if d.next_step_date %}Próx: {{ d.next_step_date }} • {% endif %}
                    {% if d.owner_name %}Resp: {{ d.owner_name }}{% endif %}
                  </div>
                  {% if d.value_estimate_brl and d.value_estimate_brl>0 %}
                    <div class="muted small">R$ {{ "%.2f"|format(d.value_estimate_brl) }}</div>
                  {% endif %}
                </a>
              {% endfor %}
            </div>
          {% else %}
            <div class="muted small">Sem negócios.</div>
          {% endif %}
        </div>
      </div>
    {% endfor %}
  </div>
</div>
{% endblock %}
""",

    "crm_new.html": r"""
{% extends "base.html" %}
{% block content %}
<div class="card p-4">
  <h4>Novo Negócio</h4>
  <div class="muted">Cadastre a oportunidade e acompanhe no funil.</div>

  <form method="post" action="/negocios/novo" class="mt-3">
    <div class="row g-3">
      <div class="col-md-6">
        <label class="form-label">Cliente (existente)</label>
        <select class="form-select" name="client_id">
          <option value="0">Selecionar (opcional)</option>
          {% for c in clients %}
            <option value="{{ c.id }}">{{ c.name }}</option>
          {% endfor %}
        </select>

        <details class="mt-3">
          <summary class="small">+ Criar cliente rápido (Lead)</summary>
          <div class="row g-2 mt-2">
            <div class="col-12">
              <label class="form-label">Nome da empresa (Lead)</label>
              <input class="form-control" name="new_client_name" placeholder="Ex: Empresa ABC Ltda" />
              <div class="form-text">Se preencher aqui, o sistema cria o lead automaticamente.</div>
            </div>
            <div class="col-md-6">
              <label class="form-label">CNPJ (opcional)</label>
              <input class="form-control" name="new_client_cnpj" placeholder="00.000.000/0000-00" />
            </div>
            <div class="col-md-6">
              <label class="form-label">E-mail (opcional)</label>
              <input class="form-control" name="new_client_email" type="email" placeholder="contato@empresa.com" />
            </div>
            <div class="col-md-6">
              <label class="form-label">Telefone (opcional)</label>
              <input class="form-control" name="new_client_phone" placeholder="(xx) xxxxx-xxxx" />
            </div>
            <div class="col-md-6">
              <label class="form-label">Observações (opcional)</label>
              <input class="form-control" name="new_client_notes" placeholder="Origem do lead, contexto..." />
            </div>
          </div>
        </details>
      </div>
      <div class="col-md-6">
        <label class="form-label">Responsável</label>
        <select class="form-select" name="owner_user_id">
          <option value="0">Sem responsável</option>
          {% for u in owners %}
            <option value="{{ u.id }}">{{ u.name }}</option>
          {% endfor %}
        </select>
      </div>

      <div class="col-12">
        <label class="form-label">Título</label>
        <input class="form-control" name="title" required placeholder="Ex: Captação / Valuation / Turnaround..." />
      </div>

      <div class="col-md-6">
        <label class="form-label">Serviço/Produto</label>
        <select class="form-select" name="service_name" required>
          <option value="">Selecione...</option>
          {% for s in service_catalog %}
            <option value="{{ s.name }}">{{ s.name }}</option>
          {% endfor %}
        </select>
      </div>

      <div class="col-md-6">
        <label class="form-label">Etapa</label>
        <select class="form-select" name="stage">
          {% for s in stages %}
            <option value="{{ s.key }}">{{ s.label }}</option>
          {% endfor %}
        </select>
      </div>

      <div class="col-12">
        <label class="form-label">Demanda inicial</label>
        <textarea class="form-control" name="demand" rows="3"></textarea>
      </div>

      <div class="col-md-4">
        <label class="form-label">Valor estimado (R$)</label>
        <input class="form-control" type="number" step="0.01" min="0" name="value_estimate_brl" value="0" />
      </div>
      <div class="col-md-4">
        <label class="form-label">Probabilidade (%)</label>
        <input class="form-control" type="number" min="0" max="100" name="probability_pct" value="0" />
      </div>
      <div class="col-md-4">
        <label class="form-label">Origem</label>
        <input class="form-control" name="source" placeholder="Indicação, inbound, etc." />
      </div>

      <div class="col-md-8">
        <label class="form-label">Próximo passo</label>
        <input class="form-control" name="next_step" />
      </div>
      <div class="col-md-4">
        <label class="form-label">Data do próximo passo</label>
        <input class="form-control mono" name="next_step_date" placeholder="AAAA-MM-DD" />
      </div>

      <div class="col-12">
        <label class="form-label">Notas internas</label>
        <textarea class="form-control" name="notes" rows="3"></textarea>
      </div>
    </div>

    <div class="mt-4 d-flex gap-2">
      <button class="btn btn-primary" type="submit">Criar</button>
      <a class="btn btn-outline-secondary" href="/negocios">Cancelar</a>
    </div>
  </form>
</div>
{% endblock %}
""",

    "crm_detail.html": r"""
{% extends "base.html" %}
{% block content %}
<div class="card p-4">
  <div class="d-flex justify-content-between align-items-start">
    <div>
      <h4 class="mb-1">{{ deal.title }}</h4>
      <div class="muted">
        Cliente: <b>{{ client.name }}</b>
        {% if deal.service_name %} • Serviço: <b>{{ deal.service_name }}</b>{% endif %}
      </div>
      <div class="muted small mt-1">
        Etapa: <b>{{ stage_label }}</b>
        {% if owner_name %} • Responsável: <b>{{ owner_name }}</b>{% endif %}
        {% if deal.next_step_date %} • Próx: <b>{{ deal.next_step_date }}</b>{% endif %}
      </div>
      {% if deal.value_estimate_brl and deal.value_estimate_brl>0 %}
        <div class="muted small mt-1">Valor estimado: <b>R$ {{ "%.2f"|format(deal.value_estimate_brl) }}</b> • Prob.: <b>{{ deal.probability_pct }}%</b></div>
      {% endif %}
    </div>
    <div class="d-flex gap-2">
      <a class="btn btn-outline-secondary" href="/negocios">Voltar</a>
      <a class="btn btn-outline-primary" href="/negocios/{{ deal.id }}/editar">Editar</a>
    </div>
  </div>

  <hr class="my-3"/>

  <div class="row g-3">
    <div class="col-md-8">
      <h6 class="mb-2">Demanda</h6>
      <pre>{{ deal.demand or "—" }}</pre>

      <h6 class="mt-4 mb-2">Notas internas</h6>
      <pre>{{ deal.notes or "—" }}</pre>

      <hr class="my-3"/>

      <h6 class="mb-2">Timeline</h6>
      {% if notes %}
        <div class="list-group">
          {% for n in notes %}
            <div class="list-group-item">
              <div class="small muted">{{ n.created_at }} • {{ n.author_name }}</div>
              <div>{{ n.message }}</div>
            </div>
          {% endfor %}
        </div>
      {% else %}
        <div class="muted">Sem notas.</div>
      {% endif %}

      <form method="post" action="/negocios/{{ deal.id }}/nota" class="mt-3">
        <label class="form-label">Adicionar nota</label>
        <textarea class="form-control" name="message" rows="3" required></textarea>
        <button class="btn btn-primary mt-2" type="submit">Adicionar</button>
      </form>
    </div>

    <div class="col-md-4">
      <div class="card p-3">
        <div class="fw-semibold mb-2">Ações</div>

        <form method="post" action="/negocios/{{ deal.id }}/stage" class="mb-3">
          <label class="form-label">Mover etapa</label>
          <select class="form-select" name="stage">
            {% for s in stages %}
              <option value="{{ s.key }}" {% if deal.stage==s.key %}selected{% endif %}>{{ s.label }}</option>
            {% endfor %}
          </select>
          <button class="btn btn-outline-primary w-100 mt-2">Atualizar</button>
        </form>

        <form method="post" action="/negocios/{{ deal.id }}/next" class="mb-3">
          <label class="form-label">Próximo passo</label>
          <input class="form-control mb-2" name="next_step" value="{{ deal.next_step }}" />
          <input class="form-control mono" name="next_step_date" value="{{ deal.next_step_date }}" placeholder="AAAA-MM-DD" />
          <button class="btn btn-outline-primary w-100 mt-2">Salvar</button>
        </form>

        {% if deal.proposal_id %}
          <a class="btn btn-outline-secondary w-100 mb-2" href="/propostas/{{ deal.proposal_id }}">Abrir proposta</a>
        {% else %}
          <form method="post" action="/negocios/{{ deal.id }}/criar-proposta" class="mb-2">
            <button class="btn btn-outline-secondary w-100">Criar proposta</button>
          </form>
        {% endif %}

        {% if deal.consulting_project_id %}
          <a class="btn btn-outline-secondary w-100 mb-2" href="/consultoria/{{ deal.consulting_project_id }}">Abrir projeto</a>
        {% else %}
          <form method="post" action="/negocios/{{ deal.id }}/criar-projeto" class="mb-2">
            <button class="btn btn-outline-secondary w-100">Criar projeto (consultoria)</button>
          </form>
        {% endif %}

        <hr class="my-2"/>

        <form method="post" action="/negocios/{{ deal.id }}/excluir" onsubmit="return confirm('Excluir negócio?');">
          <label class="form-label">Para excluir, digite EXCLUIR</label>
          <input class="form-control" name="confirm" placeholder="EXCLUIR" />
          <button class="btn btn-outline-danger w-100 mt-2" type="submit">Excluir</button>
        </form>
      </div>
    </div>
  </div>
</div>
{% endblock %}
""",

    "crm_edit.html": r"""
{% extends "base.html" %}
{% block content %}
<div class="card p-4">
  <div class="d-flex justify-content-between align-items-start">
    <div>
      <h4 class="mb-1">Editar Negócio</h4>
      <div class="muted">{{ deal.title }}</div>
    </div>
    <a class="btn btn-outline-secondary" href="/negocios/{{ deal.id }}">Voltar</a>
  </div>

  <hr class="my-3"/>

  <form method="post" action="/negocios/{{ deal.id }}/editar">
    <div class="row g-3">
      <div class="col-md-6">
        <label class="form-label">Cliente</label>
        <select class="form-select" name="client_id" required>
          {% for c in clients %}
            <option value="{{ c.id }}" {% if c.id==deal.client_id %}selected{% endif %}>{{ c.name }}</option>
          {% endfor %}
        </select>
      </div>
      <div class="col-md-6">
        <label class="form-label">Responsável</label>
        <select class="form-select" name="owner_user_id">
          <option value="0" {% if not deal.owner_user_id %}selected{% endif %}>Sem responsável</option>
          {% for u in owners %}
            <option value="{{ u.id }}" {% if deal.owner_user_id==u.id %}selected{% endif %}>{{ u.name }}</option>
          {% endfor %}
        </select>
      </div>

      <div class="col-12">
        <label class="form-label">Título</label>
        <input class="form-control" name="title" value="{{ deal.title }}" required />
      </div>

      <div class="col-md-6">
        <label class="form-label">Serviço/Produto</label>
        <select class="form-select" name="service_name" required>
          <option value="">Selecione...</option>
          {% for s in service_catalog %}
            <option value="{{ s.name }}" {% if deal.service_name==s.name %}selected{% endif %}>{{ s.name }}</option>
          {% endfor %}
        </select>
      </div>

      <div class="col-md-6">
        <label class="form-label">Etapa</label>
        <select class="form-select" name="stage">
          {% for s in stages %}
            <option value="{{ s.key }}" {% if deal.stage==s.key %}selected{% endif %}>{{ s.label }}</option>
          {% endfor %}
        </select>
      </div>

      <div class="col-12">
        <label class="form-label">Demanda</label>
        <textarea class="form-control" name="demand" rows="3">{{ deal.demand }}</textarea>
      </div>

      <div class="col-md-4">
        <label class="form-label">Valor estimado (R$)</label>
        <input class="form-control" type="number" step="0.01" min="0" name="value_estimate_brl" value="{{ deal.value_estimate_brl }}" />
      </div>
      <div class="col-md-4">
        <label class="form-label">Probabilidade (%)</label>
        <input class="form-control" type="number" min="0" max="100" name="probability_pct" value="{{ deal.probability_pct }}" />
      </div>
      <div class="col-md-4">
        <label class="form-label">Origem</label>
        <input class="form-control" name="source" value="{{ deal.source }}" />
      </div>

      <div class="col-md-8">
        <label class="form-label">Próximo passo</label>
        <input class="form-control" name="next_step" value="{{ deal.next_step }}" />
      </div>
      <div class="col-md-4">
        <label class="form-label">Data do próximo passo</label>
        <input class="form-control mono" name="next_step_date" value="{{ deal.next_step_date }}" placeholder="AAAA-MM-DD" />
      </div>

      <div class="col-12">
        <label class="form-label">Notas internas</label>
        <textarea class="form-control" name="notes" rows="3">{{ deal.notes }}</textarea>
      </div>
    </div>

    <div class="mt-4 d-flex gap-2">
      <button class="btn btn-primary" type="submit">Salvar</button>
      <a class="btn btn-outline-secondary" href="/negocios/{{ deal.id }}">Cancelar</a>
    </div>
  </form>
</div>
{% endblock %}
""",
})

# Extra templates: Meetings
TEMPLATES.update({
    "meetings_list.html": r"""
{% extends "base.html" %}
{% block content %}
<div class="card p-4">
  <div class="d-flex justify-content-between align-items-center">
    <div>
      <h4 class="mb-0">Reuniões</h4>
      <div class="muted">Sincronização com Notion AI Meeting Notes</div>
    </div>
    {% if role in ["admin","equipe"] %}
      <a class="btn btn-primary" href="/reunioes/nova">Nova reunião</a>
    {% endif %}
  </div>

  <hr class="my-3"/>

  {% if role in ["admin","equipe"] %}
  <form method="get" action="/reunioes" class="row g-2 align-items-end mb-3">
    <div class="col-md-6">
      <label class="form-label">Cliente (filtro)</label>
      <select class="form-select" name="client_id" onchange="this.form.submit()">
        <option value="0" {% if filter_client_id==0 %}selected{% endif %}>Todos</option>
        {% for c in clients %}
          <option value="{{ c.id }}" {% if filter_client_id==c.id %}selected{% endif %}>{{ c.name }}</option>
        {% endfor %}
      </select>
    </div>
    <div class="col-md-6 d-flex gap-2">
      {% if filter_client_id %}
        <a class="btn btn-outline-secondary" href="/reunioes">Limpar filtro</a>
      {% endif %}
    </div>
  </form>
  {% endif %}

  {% if meetings %}
    <div class="list-group">
      {% for m in meetings %}
        <a class="list-group-item list-group-item-action" href="/reunioes/{{ m.id }}">
          <div class="d-flex justify-content-between">
            <div class="fw-semibold">{{ m.title or "Reunião" }}</div>
            <span class="badge text-bg-light border">{{ m.notion_status or "—" }}</span>
          </div>
          <div class="muted small mt-1">
            {% if role in ["admin","equipe"] %}Cliente: {{ m.client_name }} • {% endif %}
            {% if m.meeting_date %}Data: {{ m.meeting_date }} • {% endif %}
            {% if m.last_synced_at %}Sync: {{ m.last_synced_at }}{% endif %}
          </div>
        </a>
      {% endfor %}
    </div>
  {% else %}
    <div class="muted">Nenhuma reunião cadastrada.</div>
  {% endif %}
</div>
{% endblock %}
""",

    "meetings_new.html": r"""
{% extends "base.html" %}
{% block content %}
<div class="card p-4">
  <div class="d-flex justify-content-between align-items-center">
    <div>
      <h4 class="mb-0">Nova Reunião</h4>
      <div class="muted">Cole o link (ou ID) da página do Notion que contém AI Meeting Notes.</div>
    </div>
    <a class="btn btn-outline-secondary" href="/reunioes">Voltar</a>
  </div>

  <hr class="my-3"/>

  {% if not notion_enabled %}
    <div class="alert alert-warning">
      NOTION_TOKEN não configurado. Configure no Render/ambiente para usar sync.
    </div>
  {% endif %}

  <form method="post" action="/reunioes/nova">
    <div class="row g-3">
      <div class="col-md-6">
        <label class="form-label">Cliente</label>
        <select class="form-select" name="client_id" required>
          {% for c in clients %}
            <option value="{{ c.id }}" {% if current_client and c.id==current_client.id %}selected{% endif %}>{{ c.name }}</option>
          {% endfor %}
        </select>
      </div>

      <div class="col-md-6">
        <label class="form-label">Data (AAAA-MM-DD)</label>
        <input class="form-control mono" name="meeting_date" placeholder="2026-03-12" />
      </div>

      <div class="col-12">
        <label class="form-label">Link ou ID da página do Notion</label>
        <input class="form-control" name="notion_page" required placeholder="https://www.notion.so/... ou 32-hex" />
        <div class="form-text">A integração precisa ter acesso à página (Compartilhar → Conexões → sua integração).</div>
      </div>

      <div class="col-12">
        <label class="form-label">Título (opcional)</label>
        <input class="form-control" name="title" placeholder="Ex: Reunião de alinhamento" />
      </div>

      <div class="col-12 form-check">
        <input class="form-check-input" type="checkbox" value="1" id="sync_now" name="sync_now" checked>
        <label class="form-check-label" for="sync_now">Sincronizar agora</label>
      </div>
    </div>

    <div class="mt-4 d-flex gap-2">
      <button class="btn btn-primary" type="submit">Criar</button>
      <a class="btn btn-outline-secondary" href="/reunioes">Cancelar</a>
    </div>
  </form>
</div>
{% endblock %}
""",

    "meetings_detail.html": r"""
{% extends "base.html" %}
{% block content %}
<div class="card p-4">
  <div class="d-flex justify-content-between align-items-start">
    <div>
      <h4 class="mb-1">{{ meeting.title or "Reunião" }}</h4>
      <div class="muted">
        {% if role in ["admin","equipe"] %}Cliente: <b>{{ client.name }}</b> • {% endif %}
        {% if meeting.meeting_date %}Data: <b>{{ meeting.meeting_date }}</b> • {% endif %}
        Status Notion: <b>{{ meeting.notion_status or "—" }}</b>
      </div>
      {% if meeting.notion_url %}
        <div class="small mt-1"><a href="{{ meeting.notion_url }}" target="_blank" rel="noopener">Abrir no Notion</a></div>
      {% endif %}
      {% if meeting.last_synced_at %}
        <div class="muted small mt-1">Última sincronização: {{ meeting.last_synced_at }}</div>
      {% endif %}
    </div>

    <div class="d-flex gap-2">
      <a class="btn btn-outline-secondary" href="/reunioes">Voltar</a>
      {% if role in ["admin","equipe"] %}
        <form method="post" action="/reunioes/{{ meeting.id }}/sync">
          <button class="btn btn-outline-primary" type="submit">Sincronizar</button>
        </form>
      {% endif %}
    </div>
  </div>

  {% if role in ["admin","equipe"] and meeting.action_items_text %}
    <hr class="my-3"/>
    <form method="post" action="/reunioes/{{ meeting.id }}/gerar_tarefas" class="card p-3">
      <div class="fw-semibold mb-2">Gerar tarefas a partir de Action Items</div>
      <div class="row g-2">
        <div class="col-md-6">
          <label class="form-label">Responsável (opcional)</label>
          <select class="form-select" name="assignee_user_id">
            <option value="0">Sem responsável</option>
            {% for a in assignees %}
              <option value="{{ a.id }}">{{ a.name }} ({{ a.role }})</option>
            {% endfor %}
          </select>
        </div>
        <div class="col-md-6">
          <label class="form-label">Visibilidade</label>
          <select class="form-select" name="visible_to_client">
            <option value="0">Interno</option>
            <option value="1">Visível ao cliente</option>
          </select>
        </div>
        <div class="col-12">
          <button class="btn btn-primary" type="submit">Gerar tarefas</button>
        </div>
      </div>
    </form>
  {% endif %}

  <hr class="my-3"/>

  <div class="accordion" id="accM">
    <div class="accordion-item">
      <h2 class="accordion-header" id="hSum">
        <button class="accordion-button" type="button" data-bs-toggle="collapse" data-bs-target="#cSum">Resumo</button>
      </h2>
      <div id="cSum" class="accordion-collapse collapse show" data-bs-parent="#accM">
        <div class="accordion-body"><pre>{{ meeting.summary_text or "—" }}</pre></div>
      </div>
    </div>

    <div class="accordion-item">
      <h2 class="accordion-header" id="hAct">
        <button class="accordion-button collapsed" type="button" data-bs-toggle="collapse" data-bs-target="#cAct">Action Items</button>
      </h2>
      <div id="cAct" class="accordion-collapse collapse" data-bs-parent="#accM">
        <div class="accordion-body"><pre>{{ meeting.action_items_text or "—" }}</pre></div>
      </div>
    </div>

    <div class="accordion-item">
      <h2 class="accordion-header" id="hNotes">
        <button class="accordion-button collapsed" type="button" data-bs-toggle="collapse" data-bs-target="#cNotes">Notas</button>
      </h2>
      <div id="cNotes" class="accordion-collapse collapse" data-bs-parent="#accM">
        <div class="accordion-body"><pre>{{ meeting.notes_text or "—" }}</pre></div>
      </div>
    </div>

    <div class="accordion-item">
      <h2 class="accordion-header" id="hTr">
        <button class="accordion-button collapsed" type="button" data-bs-toggle="collapse" data-bs-target="#cTr">Transcrição</button>
      </h2>
      <div id="cTr" class="accordion-collapse collapse" data-bs-parent="#accM">
        <div class="accordion-body"><pre>{{ meeting.transcript_text or "—" }}</pre></div>
      </div>
    </div>
  </div>

</div>

<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/js/bootstrap.bundle.min.js"></script>
{% endblock %}
""",
})

TEMPLATES.update({
    "credit_list.html": r"""
{% extends "base.html" %}
{% block content %}
<div class="card p-4">
  <div class="d-flex justify-content-between align-items-center">
    <div>
      <h4 class="mb-0">Crédito (SCR)</h4>
      <div class="muted">Consulta SCR Detalhada (Direct Data) + autorização LGPD</div>
    </div>
  </div>

  <hr class="my-3"/>

  {% if not current_client %}
    <div class="alert alert-warning mb-0">
      Selecione um cliente para usar o módulo de crédito.
    </div>
  {% else %}
    <div class="mb-3">
      <span class="muted">Cliente:</span> <b>{{ current_client.name }}</b>
      {% if current_client.cnpj %}<span class="muted ms-2">CNPJ:</span> <span class="mono">{{ current_client.cnpj }}</span>{% endif %}
    </div>

    <div class="card p-3 mb-4">
      <div class="fw-semibold mb-1">Autorização (LGPD)</div>
      <div class="muted mb-2">Anexe o termo/autorização do cliente antes de consultar o SCR.</div>
<div class="mt-2">
  <div class="d-flex flex-wrap gap-2 align-items-center">
    {% if role in ["admin","equipe"] %}
      <form method="post" action="/credito/consent_link">
        <button class="btn btn-outline-primary btn-sm">Gerar link de aceite (sem OTP)</button>
      </form>
    {% endif %}
    {% if consent_link_url %}
      <div class="small">
        <div class="muted">Link de aceite:</div>
        <div class="d-flex gap-2 align-items-center">
          <input class="form-control form-control-sm mono" style="min-width: 320px;" readonly value="{{ consent_link_url }}"/>
          <button class="btn btn-outline-secondary btn-sm" type="button" onclick="navigator.clipboard.writeText('{{ consent_link_url }}')">Copiar</button>
        </div>
      </div>
    {% endif %}
  </div>
</div>


      {% if consent and consent.status == "valida" %}
        <div class="small">
          <div><span class="muted">Assinado por:</span> {{ consent.signed_by_name or "—" }}</div>
          <div><span class="muted">Data:</span> {{ consent.signed_at }}</div>
          <div><span class="muted">Válido até:</span> {{ consent.expires_at }}</div>
        </div>
        {% if consent_file %}
          <div class="mt-2">
            <a class="btn btn-outline-primary btn-sm" href="/download/{{ consent_file.id }}">Baixar autorização</a>
          </div>
        {% endif %}
      {% elif consent and consent.status == "pendente" %}
        <div class="alert alert-info mb-0">Aguardando aceite eletrônico do cliente. Você pode reenviar o link acima.</div>
      {% else %}
        <form method="post" action="/credito/consent" enctype="multipart/form-data" class="mt-2">
          <div class="row g-2">
            <div class="col-md-6">
              <label class="form-label">Nome do signatário</label>
              <input class="form-control" name="signed_by_name" required />
            </div>
            <div class="col-md-6">
              <label class="form-label">Documento do signatário (CPF/CNPJ)</label>
              <input class="form-control mono" name="signed_by_document" />
            </div>
            <div class="col-md-6">
              <label class="form-label">Data da assinatura</label>
              <input class="form-control mono" name="signed_at" placeholder="AAAA-MM-DD" />
            </div>
            <div class="col-md-6">
              <label class="form-label">Arquivo (PDF/Imagem)</label>
              <input class="form-control" type="file" name="file" required />
            </div>
            <div class="col-12">
              <label class="form-label">Observações</label>
              <input class="form-control" name="notes" placeholder="Origem, contexto, etc." />
            </div>
          </div>
          <div class="mt-3">
            <button class="btn btn-primary">Enviar autorização</button>
          </div>
        </form>
      {% endif %}
    </div>

    {% if role in ["admin","equipe"] %}
      <div class="card p-3 mb-4">
        <div class="fw-semibold mb-2">Consulta SCR</div>

        {% if not consent or consent.status != "valida" %}
          <div class="alert alert-warning mb-0">Envie uma autorização válida (PDF) ou obtenha o aceite eletrônico para habilitar a consulta.</div>
        {% else %}
          <form method="post" action="/credito/consultar" class="row g-2 align-items-end">
            <div class="col-md-3">
              <label class="form-label">Tipo</label>
              <select class="form-select" name="document_type">
                <option value="cnpj" selected>CNPJ</option>
                <option value="cpf">CPF</option>
              </select>
            </div>
            <div class="col-md-6">
              <label class="form-label">Documento (sem formatação)</label>
              <input class="form-control mono" name="document_value" value="{{ current_client.cnpj }}" placeholder="CNPJ/CPF" />
            </div>
            <div class="col-md-3">
              <button class="btn btn-primary w-100">Consultar</button>
            </div>
          </form>
          <div class="muted small mt-2">A consulta usa modo assíncrono (poll) para evitar timeouts.</div>
        {% endif %}
      </div>
    {% endif %}

    <div class="fw-semibold mb-2">Histórico</div>
    {% if reports|length == 0 %}
      <div class="muted">Nenhuma consulta ainda.</div>
    {% else %}
      <div class="table-responsive">
        <table class="table align-middle">
          <thead>
            <tr>
              <th>Data</th>
              <th>Status</th>
              <th>Potencial</th>
              <th>Total (R$)</th>
              <th>Vencido (R$)</th>
              <th>Inst.</th>
              <th>Score</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
          {% for r in reports %}
            <tr>
              <td class="small mono">{{ r.created_at }}</td>
              <td><span class="badge text-bg-secondary">{{ r.status }}</span></td>
              <td><span class="badge text-bg-{% if r.potential_label=='alto' %}danger{% elif r.potential_label=='medio' %}warning{% else %}success{% endif %}">{{ r.potential_label }}</span></td>
              <td class="mono">{{ '%.2f'|format(r.carteira_total_brl) }}</td>
              <td class="mono">{{ '%.2f'|format(r.carteira_vencido_brl) }}</td>
              <td class="mono">{{ r.quantidade_instituicoes }}</td>
              <td>{{ r.score }}</td>
              <td class="text-end">
                <a class="btn btn-outline-primary btn-sm" href="/credito/{{ r.id }}">Abrir</a>
                {% if role in ["admin","equipe"] and r.status == "processing" %}
                  <form method="post" action="/credito/{{ r.id }}/atualizar" class="d-inline">
                    <button class="btn btn-outline-secondary btn-sm">Atualizar</button>
                  </form>
                {% endif %}
              </td>
            </tr>
          {% endfor %}
          </tbody>
        </table>
      </div>
    {% endif %}

  {% endif %}
</div>
{% endblock %}
""",
    "credit_report_detail.html": r"""
{% extends "base.html" %}
{% block content %}
<div class="card p-4">
  <div class="d-flex justify-content-between align-items-start">
    <div>
      <h4 class="mb-1">Relatório SCR</h4>
      <div class="muted">Consulta #{{ report.id }} • {{ report.provider }}</div>
    </div>
    <a class="btn btn-outline-secondary" href="/credito">Voltar</a>
  </div>

  <hr class="my-3"/>

  <div class="row g-3">
    <div class="col-md-3">
      <div class="muted small">Status</div>
      <div><span class="badge text-bg-secondary">{{ report.status }}</span></div>
    </div>
    <div class="col-md-3">
      <div class="muted small">Potencial</div>
      <div><span class="badge text-bg-{% if report.potential_label=='alto' %}danger{% elif report.potential_label=='medio' %}warning{% else %}success{% endif %}">{{ report.potential_label }}</span> <span class="muted">({{ report.potential_score }})</span></div>
    </div>
    <div class="col-md-3">
      <div class="muted small">Score / Risco</div>
      <div>{{ report.score }} • {{ report.faixa_risco }}</div>
    </div>
    <div class="col-md-3">
      <div class="muted small">Instituições / Operações</div>
      <div>{{ report.quantidade_instituicoes }} / {{ report.quantidade_operacoes }}</div>
    </div>

    <div class="col-md-3">
      <div class="muted small">Carteira total (R$)</div>
      <div class="mono">{{ '%.2f'|format(report.carteira_total_brl) }}</div>
    </div>
    <div class="col-md-3">
      <div class="muted small">A vencer (R$)</div>
      <div class="mono">{{ '%.2f'|format(report.carteira_vencer_brl) }}</div>
    </div>
    <div class="col-md-3">
      <div class="muted small">Vencido (R$)</div>
      <div class="mono">{{ '%.2f'|format(report.carteira_vencido_brl) }}</div>
    </div>
    <div class="col-md-3">
      <div class="muted small">Prejuízo (R$)</div>
      <div class="mono">{{ '%.2f'|format(report.carteira_prejuizo_brl) }}</div>
    </div>

    {% if report.message %}
    <div class="col-12">
      <div class="alert alert-info mb-0">{{ report.message }}</div>
    </div>
    {% endif %}
  </div>

  {% if role in ["admin","equipe"] %}
    <div class="mt-4 d-flex gap-2 flex-wrap">
      {% if report.status == "processing" %}
        <form method="post" action="/credito/{{ report.id }}/atualizar">
          <button class="btn btn-outline-secondary">Atualizar</button>
        </form>
      {% endif %}
      {% if report.status == "done" %}
        <form method="post" action="/credito/{{ report.id }}/criar_negocio">
          <button class="btn btn-primary">Criar negócio no CRM</button>
        </form>
        <form method="post" action="/credito/{{ report.id }}/gerar_tarefas">
          <button class="btn btn-outline-primary">Gerar tarefas</button>
        </form>
      {% endif %}
    </div>
  {% endif %}

  {% if report.raw_json %}
    <hr class="my-4"/>
    <details>
      <summary class="small">Ver JSON completo</summary>
      <pre class="mt-2" style="max-height: 420px; overflow:auto;"><code>{{ report.raw_json }}</code></pre>
    </details>
  {% endif %}
</div>
{% endblock %}
""",
})

TEMPLATES.update({
    "consent_accept.html": r"""
{% extends "base.html" %}
{% block content %}
<div class="card p-4">
  <h4 class="mb-1">Autorização (LGPD / SCR)</h4>
  <div class="muted">Aceite eletrônico para consulta de crédito (SCR) e tratamento de dados.</div>

  <hr class="my-3"/>

  <div class="mb-3">
    <div><span class="muted">Empresa:</span> <b>{{ company.name }}</b></div>
    <div><span class="muted">Cliente:</span> <b>{{ client.name }}</b></div>
    {% if client.cnpj %}<div><span class="muted">Documento:</span> <span class="mono">{{ client.cnpj }}</span></div>{% endif %}
  </div>

  <div class="border rounded p-3 bg-light">
    {{ terms_html|safe }}
  </div>

  <form method="post" class="mt-3">
    <div class="form-check">
      <input class="form-check-input" type="checkbox" value="1" id="agree" name="agree" required>
      <label class="form-check-label" for="agree">
        Li e concordo com o termo acima e autorizo a consulta.
      </label>
    </div>

    <div class="row g-2 mt-2">
      <div class="col-md-6">
        <label class="form-label">Confirme seu nome (opcional)</label>
        <input class="form-control" name="signed_by_name" value="{{ client.name }}" />
      </div>
      <div class="col-md-6">
        <label class="form-label">Confirme os 4 últimos dígitos do documento (opcional)</label>
        <input class="form-control mono" name="doc_last4" maxlength="4" placeholder="0000" />
      </div>
    </div>

    <div class="mt-3 d-flex gap-2">
      <button class="btn btn-primary">Aceitar</button>
    </div>

    <div class="muted small mt-3">
      Ao aceitar, registraremos evidências do aceite (data/hora, IP, navegador) e manteremos a autorização pelo prazo aplicável.
    </div>
  </form>
</div>
{% endblock %}
""",

    "invite_signup.html": r"""
{% extends "base.html" %}
{% block content %}
<div class="container py-4">
  <div class="card p-4">
    <h4 class="mb-1">Criar acesso do cliente</h4>
    <div class="muted mb-3">
      Você foi convidado(a) para acessar a plataforma.
      <div class="small mt-1">Empresa: <b>{{ company.name }}</b> • Cliente: <b>{{ client.name }}</b></div>
    </div>

    {% if error %}
      <div class="alert alert-danger">{{ error }}</div>
    {% endif %}

    <form method="post" action="/convite/{{ token }}">
      <div class="row g-2">
        <div class="col-md-6">
          <label class="form-label">Seu nome</label>
          <input class="form-control" name="name" value="{{ form.name or '' }}" required/>
        </div>
        <div class="col-md-6">
          <label class="form-label">E-mail</label>
          <input class="form-control" name="email" type="email" value="{{ form.email or invited_email or '' }}" required/>
        </div>

        <div class="col-md-6">
          <label class="form-label">Senha</label>
          <input class="form-control" name="password" type="password" minlength="8" required/>
          <div class="muted small mt-1">Mínimo 8 caracteres.</div>
        </div>
        <div class="col-md-6">
          <label class="form-label">Confirmar senha</label>
          <input class="form-control" name="password2" type="password" minlength="8" required/>
        </div>

        {% if require_last4 %}
          <div class="col-md-6">
            <label class="form-label">Últimos 4 dígitos do CNPJ/CPF</label>
            <input class="form-control" name="doc_last4" inputmode="numeric" maxlength="4" placeholder="0000" required/>
            <div class="muted small mt-1">Usamos isso para reduzir fraudes (sem OTP).</div>
          </div>
        {% endif %}

        <div class="col-12 mt-2">
          <div class="form-check">
            <input class="form-check-input" type="checkbox" name="accept" id="accept" required/>
            <label class="form-check-label" for="accept">
              Li e aceito os termos de uso e a política de privacidade.
            </label>
          </div>
        </div>
        <div class="col-12 mt-3">
          <hr class="my-3"/>
          <h6 class="mb-2">Autorização para consulta ao SCR (Bacen)</h6>
          <div class="muted small mb-2">
            Para concluir o cadastro, precisamos do seu aceite eletrônico para consulta de crédito e tratamento de dados conforme termo abaixo.
          </div>

          <div class="border rounded p-3 bg-light" style="max-height: 260px; overflow: auto;">
            {{ consent_terms_html|safe }}
          </div>

          <div class="form-check mt-2">
            <input class="form-check-input" type="checkbox" name="scr_accept" id="scr_accept" required/>
            <label class="form-check-label" for="scr_accept">
              Li o termo acima e autorizo a consulta ao SCR (Bacen) e o tratamento de dados para análise de crédito.
            </label>
          </div>

          <div class="muted small mt-2">
            Registraremos evidências do aceite (data/hora, IP e navegador) para fins de auditoria.
          </div>
        </div>
      </div>

      <button class="btn btn-primary mt-3">Criar acesso</button>
    </form>

    <div class="muted small mt-3">
      Se este convite não foi solicitado por você, feche esta página.
    </div>
  </div>
</div>
{% endblock %}
""",

    "success.html": r"""{% extends "base.html" %}
{% block content %}
<div class="container py-4">
  <div class="card p-4">
    <div class="d-flex align-items-center gap-2 mb-2">
      <span class="badge bg-success">OK</span>
      <div class="fw-semibold">Confirmação</div>
    </div>
    <div class="muted">{{ message or "Operação concluída." }}</div>
    <div class="muted small mt-3">Você pode fechar esta página.</div>
  </div>
</div>
{% endblock %}
""",

    "admin_internal_services.html": r"""
{% extends "base.html" %}
{% block content %}
<div class="row g-3">
  <div class="col-lg-5">
    <div class="card p-4">
      <h4 class="mb-1">Produtos internos</h4>
      <div class="muted mb-3">Catálogo próprio da Maffezzolli Capital: Advisory, IB, BaaS e Special Sits.</div>
      <form method="post" action="/admin/servicos-internos/add" class="row g-2">
        <div class="col-md-6">
          <label class="form-label">Área</label>
          <select class="form-select" name="area">
            {% for value,label in area_options %}
              <option value="{{ value }}">{{ label }}</option>
            {% endfor %}
          </select>
        </div>
        <div class="col-md-6">
          <label class="form-label">Família</label>
          <input class="form-control" name="family_slug" placeholder="home_equity, turnaround...">
        </div>
        <div class="col-12">
          <label class="form-label">Nome do produto</label>
          <input class="form-control" name="name" required>
        </div>
        <div class="col-12">
          <label class="form-label">Descrição</label>
          <textarea class="form-control" name="description" rows="3"></textarea>
        </div>
        <div class="col-md-4">
          <label class="form-label">Prioridade</label>
          <input class="form-control" name="priority_weight" value="100">
        </div>
        <div class="col-12">
          <label class="form-label">Observações</label>
          <textarea class="form-control" name="notes" rows="2"></textarea>
        </div>
        <div class="col-12 d-flex gap-2">
          <button class="btn btn-primary">Salvar produto</button>
          <a class="btn btn-outline-secondary" href="/admin/parceiros">Ir para parceiros</a>
        </div>
      </form>
    </div>
  </div>
  <div class="col-lg-7">
    <div class="card p-4">
      <div class="d-flex justify-content-between align-items-center mb-3">
        <div>
          <h5 class="mb-1">Catálogo interno</h5>
          <div class="muted">Produtos próprios usados pelo motor de ofertas.</div>
        </div>
        <form method="post" action="/admin/servicos-internos/seed">
          <button class="btn btn-outline-primary btn-sm">Semear catálogo padrão</button>
        </form>
      </div>
      {% if rows %}
        <div class="table-responsive">
          <table class="table align-middle">
            <thead><tr><th>Área</th><th>Produto</th><th>Família</th><th>Prioridade</th></tr></thead>
            <tbody>
              {% for row in rows %}
                <tr>
                  <td><span class="badge text-bg-light border">{{ row.area }}</span></td>
                  <td>
                    <div class="fw-semibold">{{ row.name }}</div>
                    <div class="muted small">{{ row.description }}</div>
                  </td>
                  <td>{{ row.family_slug or "-" }}</td>
                  <td>{{ row.priority_weight }}</td>
                </tr>
              {% endfor %}
            </tbody>
          </table>
        </div>
      {% else %}
        <div class="muted">Nenhum produto interno cadastrado.</div>
      {% endif %}
    </div>
  </div>
</div>
{% endblock %}
""",
    "motor_ofertas.html": r"""
{% extends "base.html" %}
{% block content %}
<div class="card p-4 mb-3">
  <div class="d-flex justify-content-between align-items-start gap-2">
    <div>
      <h4 class="mb-1">Motor de Ofertas</h4>
      <div class="muted">Área, produto e parceiro recomendados com base no perfil do cliente.</div>
    </div>
    <form method="post" action="/motor-ofertas/gerar">
      <button class="btn btn-primary">Gerar / atualizar ofertas</button>
    </form>
  </div>
  {% if current_client %}
    <div class="mt-3 small">
      Cliente atual: <b>{{ current_client.name }}</b>
      {% if current_client.cnpj %} · {{ current_client.cnpj }}{% endif %}
    </div>
  {% endif %}
</div>

{% if not current_client %}
  <div class="alert alert-warning">Selecione um cliente para gerar as ofertas.</div>
{% endif %}

{% if matches %}
  <div class="row g-3">
    {% for row in matches %}
      <div class="col-lg-6">
        <div class="card p-3 h-100">
          <div class="d-flex justify-content-between gap-2">
            <div>
              <div class="small muted">{{ row.area or "-" }} · {{ row.source_kind }}</div>
              <div class="fw-semibold">{{ row.product_name }}</div>
              <div class="muted">{{ row.partner_name or "Maffezzolli Capital" }}</div>
            </div>
            <div class="text-end">
              <div class="badge text-bg-light border">{{ row.priority_level|upper }}</div>
              <div class="mt-2 fw-semibold">{{ "%.1f"|format(row.score_fit) }}</div>
            </div>
          </div>
          <div class="small mt-3">{{ row.reason_summary }}</div>
          {% if row.estimated_commission_text %}
            <div class="small mt-2"><b>Comissão / campanha:</b> {{ row.estimated_commission_text }}</div>
          {% endif %}
          <div class="mt-3 d-flex gap-2">
            {% if row.partner_product_id %}
              <a class="btn btn-outline-primary btn-sm" href="/simulador?partner_product_id={{ row.partner_product_id }}">Simular</a>
            {% endif %}
            <a class="btn btn-outline-secondary btn-sm" href="/propostas">Criar proposta</a>
          </div>
        </div>
      </div>
    {% endfor %}
  </div>
{% else %}
  <div class="card p-4"><div class="muted">Nenhuma oferta gerada ainda.</div></div>
{% endif %}
{% endblock %}
""",
    "client_offers.html": r"""
{% extends "base.html" %}
{% block content %}
<div class="card p-4 mb-3">
  <h4 class="mb-1">Ofertas para sua empresa</h4>
  <div class="muted">Recomendações personalizadas a partir do seu perfil e dos dados compartilhados.</div>
</div>
{% if rows %}
  <div class="row g-3">
    {% for row in rows %}
      <div class="col-lg-6">
        <div class="card p-3 h-100">
          <div class="small muted">{{ row.area or "-" }}</div>
          <div class="fw-semibold">{{ row.product_name }}</div>
          <div class="muted">{{ row.partner_name }}</div>
          <div class="small mt-2">{{ row.reason_summary }}</div>
          <div class="mt-3 d-flex gap-2">
            {% if row.partner_product_id %}
              <a class="btn btn-outline-primary btn-sm" href="/simulador?partner_product_id={{ row.partner_product_id }}">Ver simulação</a>
            {% endif %}
            <a class="btn btn-outline-secondary btn-sm" href="/propostas">Solicitar proposta</a>
          </div>
        </div>
      </div>
    {% endfor %}
  </div>
{% else %}
  <div class="card p-4"><div class="muted">Ainda não há ofertas personalizadas. Complete seu perfil e peça uma análise.</div></div>
{% endif %}
{% endblock %}
""",

})

templates_env = Environment(loader=DictLoader(TEMPLATES), autoescape=True)


# ----------------------------
# Templates (Open Finance)
# ----------------------------

TEMPLATES.setdefault("openfinance.html", r"""{% extends "base.html" %}
{% block content %}
<div class="d-flex align-items-center justify-content-between mb-3">
  <div>
    <div class="h4 mb-0">🌐 Open Finance — Contratos</div>
    <div class="muted">Conecte a conta do titular e importe contratos (Loans) para comparar ofertas.</div>
  </div>
  <a class="btn btn-outline-secondary" href="/">Voltar</a>
</div>


<div class="alert alert-info d-flex justify-content-between align-items-center">
  <div><strong>Klavi:</strong> se o Pluggy estiver instável, use a conexão via Klavi (Sandbox/Produção).</div>
  <a class="btn btn-outline-primary btn-sm" href="/openfinance/klavi?doc={{ doc or '' }}&email={{ email_default or '' }}">Abrir Klavi</a>
</div>

<div class="card p-3 mb-3">
  <form method="get" action="/openfinance" class="row g-2 align-items-end">
    <div class="col-md-4">
      <label class="form-label">CPF/CNPJ</label>
      <input class="form-control mono" name="doc" value="{{ doc or '' }}" placeholder="Somente números ou com máscara" required>
    </div>
    <div class="col-md-4">
      <label class="form-label">E-mail do titular (para enviar link)</label>
      <input class="form-control" name="email" value="{{ email_default or '' }}" placeholder="email@exemplo.com">
      <div class="form-text">Opcional se o próprio titular estiver logado.</div>
    </div>
    <div class="col-md-4 d-flex gap-2">
      <button class="btn btn-primary w-100" type="submit">Abrir</button>
      {% if doc %}
        <button class="btn btn-outline-primary" type="submit" formmethod="post" formaction="/openfinance/sync">Sincronizar</button>
      {% endif %}
    </div>
  </form>
</div>

{% if doc %}
  <div class="row g-3">
    <div class="col-12 col-lg-5">
      <div class="card p-3">
        <div class="fw-semibold mb-1">Status da conexão</div>
        {% if conn %}
          <div class="muted small">Item:</div>
          <div class="mono">{{ conn.pluggy_item_id }}</div>
          <div class="muted small mt-2">Status:</div>
          <div><span class="badge text-bg-light border">{{ conn.status }}</span></div>
          <div class="muted small mt-2">Última sincronização:</div>
          <div>{{ conn.last_synced_at or "-" }}</div>
          {% if conn.last_error %}
            <div class="alert alert-warning mt-3 mb-0">{{ conn.last_error }}</div>
          {% endif %}
        {% else %}
          <div class="muted">Nenhuma conexão ainda para este documento.</div>
        {% endif %}

        <hr>

        {% if role in ["admin","equipe"] %}
          <div class="fw-semibold">Enviar link de conexão ao titular</div>
          <form method="post" action="/openfinance/invite" class="row g-2 mt-1">
            <input type="hidden" name="doc" value="{{ doc }}">
            <div class="col-12">
              <label class="form-label">E-mail</label>
              <input class="form-control" name="email" value="{{ email_default or '' }}" required>
            </div>
            <div class="col-12 d-flex gap-2">
              <button class="btn btn-primary" type="submit">Enviar link</button>
              {% if invite_link %}
                <button class="btn btn-outline-secondary" type="button" onclick="navigator.clipboard.writeText('{{ invite_link }}'); alert('Link copiado!');">Copiar link</button>
              {% endif %}
            </div>
          </form>
          {% if invite_link %}
            <div class="mt-2 small muted">Link: <span class="mono">{{ invite_link }}</span></div>
          {% endif %}
        {% else %}
          <div class="fw-semibold">Conectar agora</div>
          {% if self_connect_link %}
            <a class="btn btn-primary mt-2" href="{{ self_connect_link }}">Abrir Pluggy Connect</a>
          {% else %}
            <div class="muted small">Peça para o administrador/equipe gerar um link.</div>
          {% endif %}
        {% endif %}
      </div>

      <div class="card p-3 mt-3">
        <div class="fw-semibold mb-2">Catálogo de ofertas</div>
        {% if role in ["admin","equipe"] %}
          <form method="post" action="/openfinance/offers/add" class="row g-2">
            <div class="col-12">
              <label class="form-label">Nome da oferta</label>
              <input class="form-control" name="label" placeholder="Ex.: Refinanciamento Banco X" required>
            </div>
            <div class="col-md-6">
              <label class="form-label">CET a.a. (%)</label>
              <input class="form-control" name="cet_aa_pct" inputmode="decimal" placeholder="Ex.: 28.5" required>
            </div>
            <div class="col-md-6">
              <label class="form-label">Tipo (opcional)</label>
              <input class="form-control" name="product_type" placeholder="Ex.: PERSONAL_LOAN">
            </div>
            <div class="col-md-6">
              <label class="form-label">Prazo mín (meses)</label>
              <input class="form-control" name="term_min" inputmode="numeric" placeholder="0">
            </div>
            <div class="col-md-6">
              <label class="form-label">Prazo máx (meses)</label>
              <input class="form-control" name="term_max" inputmode="numeric" placeholder="0">
            </div>
            <div class="col-12">
              <button class="btn btn-outline-primary w-100" type="submit">Adicionar oferta</button>
            </div>
          </form>
        {% endif %}

        <div class="mt-2">
          {% if offers %}
            <ul class="list-group">
              {% for o in offers %}
                <li class="list-group-item d-flex justify-content-between align-items-center">
                  <div>
                    <div class="fw-semibold">{{ o.label }}</div>
                    <div class="muted small">CET a.a.: {{ (o.cet_aa * 100) | round(2) }}% {% if o.product_type %}• {{ o.product_type }}{% endif %}</div>
                  </div>
                  <span class="badge text-bg-light border">{% if o.is_active %}ativa{% else %}inativa{% endif %}</span>
                </li>
              {% endfor %}
            </ul>
          {% else %}
            <div class="muted small">Nenhuma oferta cadastrada ainda.</div>
          {% endif %}
        </div>
      </div>
    </div>

    <div class="col-12 col-lg-7">
      <div class="card p-3">
        <div class="d-flex justify-content-between align-items-center">
          <div class="fw-semibold">Contratos (Loans)</div>
          <form method="post" action="/openfinance/opportunities/generate">
            <input type="hidden" name="doc" value="{{ doc }}">
            <button class="btn btn-outline-success btn-sm" type="submit">Gerar oportunidades</button>
          </form>
        </div>

        {% if loans %}
          <div class="table-responsive mt-2">
            <table class="table table-sm align-middle">
              <thead>
                <tr>
                  <th>Contrato</th>
                  <th>CET a.a.</th>
                  <th>Saldo</th>
                  <th>Parcela</th>
                  <th>Prazo (rem/total)</th>
                </tr>
              </thead>
              <tbody>
                {% for l in loans %}
                  <tr>
                    <td class="mono">{{ l.contract_number or l.pluggy_loan_id }}</td>
                    <td>{{ (l.cet_aa * 100) | round(2) }}%</td>
                    <td>R$ {{ l.outstanding_brl | round(2) }}</td>
                    <td>R$ {{ l.installment_brl | round(2) }}</td>
                    <td>{{ l.term_remaining_months }}/{{ l.term_total_months }}</td>
                  </tr>
                {% endfor %}
              </tbody>
            </table>
          </div>
        {% else %}
          <div class="muted small mt-2">Sem contratos importados ainda. Conecte e sincronize.</div>
        {% endif %}
      </div>

      <div class="card p-3 mt-3">
        <div class="fw-semibold mb-2">Oportunidades (comparação)</div>
        {% if opportunities %}
          <div class="table-responsive">
            <table class="table table-sm align-middle">
              <thead>
                <tr>
                  <th>Contrato</th>
                  <th>Oferta</th>
                  <th>Parcela atual</th>
                  <th>Nova parcela</th>
                  <th>Economia/mês</th>
                  <th>Economia total</th>
                </tr>
              </thead>
              <tbody>
                {% for o in opportunities %}
                  <tr>
                    <td class="mono">{{ o.pluggy_loan_id }}</td>
                    <td>{{ o.offer_label }}</td>
                    <td>R$ {{ o.old_payment_brl | round(2) }}</td>
                    <td>R$ {{ o.new_payment_brl | round(2) }}</td>
                    <td>R$ {{ o.monthly_savings_brl | round(2) }}</td>
                    <td>R$ {{ o.total_savings_brl | round(2) }}</td>
                  </tr>
                {% endfor %}
              </tbody>
            </table>
          </div>
          <div class="muted small">Cálculo aproximado (PRICE/SAC médio) usando CET anual informado.</div>
        {% else %}
          <div class="muted small">Sem oportunidades ainda (adicione ofertas e clique em “Gerar oportunidades”).</div>
        {% endif %}
      </div>
    </div>
  </div>
{% endif %}
{% endblock %}
""")

TEMPLATES.setdefault("openfinance_klavi.html", r"""{% extends "base.html" %}
{% block content %}
<div class="d-flex align-items-center justify-content-between mb-3">
  <div>
    <div class="h4 mb-0">🌐 Open Finance (Klavi) — Contratos</div>
    <div class="muted">Fluxo Link → Consent → Report (pf loans) via Klavi. Use sandbox para testes.</div>
  </div>
  <div class="d-flex gap-2">
    <a class="btn btn-outline-secondary" href="/openfinance?doc={{ doc or '' }}">Voltar</a>
  </div>
</div>

<div class="card p-3 mb-3">
  <form method="post" action="/openfinance/klavi/start" class="row g-2 align-items-end">
    <input type="hidden" name="doc" value="{{ doc or '' }}"/>
    <div class="col-md-4">
      <label class="form-label">CPF/CNPJ</label>
      <input class="form-control mono" name="doc_input" value="{{ doc or '' }}" required>
    </div>
    <div class="col-md-4">
      <label class="form-label">E-mail do titular</label>
      <input class="form-control" name="email" value="{{ email_default or '' }}" placeholder="email@exemplo.com" required>
    </div>
    <div class="col-md-4">
      <label class="form-label">Telefone do titular</label>
      <input class="form-control" name="phone" value="{{ phone_default or '' }}" placeholder="+55DD9XXXXYYYY" required>
    </div>
    <div class="col-12 d-flex gap-2 mt-2">
      <button class="btn btn-primary">Iniciar (criar Link + listar instituições)</button>
      <a class="btn btn-outline-secondary" href="/openfinance?doc={{ doc or '' }}">Ver contratos/importados</a>
    </div>
    <div class="form-text">A Klavi usa Link/Consent do Open Finance. Após autorizar, solicitaremos o relatório <strong>pf loans</strong>.</div>
  </form>
</div>

{% if flow %}
<div class="card p-3 mb-3">
  <div class="d-flex justify-content-between align-items-center">
    <div>
      <div><strong>Status:</strong> {{ flow.consent_status or "—" }}</div>
      <div class="muted mono">link_id={{ flow.link_id }} | consent_id={{ flow.consent_id }}</div>
      {% if flow.institution_name %}
        <div class="muted">Instituição: {{ flow.institution_name }} ({{ flow.institution_code }})</div>
      {% endif %}
      {% if flow.last_error %}
        <div class="text-danger mt-2"><strong>Erro:</strong> {{ flow.last_error }}</div>
      {% endif %}
    </div>

    <div class="d-flex gap-2">
      {% if flow.consent_id %}
        <form method="post" action="/openfinance/klavi/request">
          <input type="hidden" name="doc" value="{{ doc or '' }}"/>
          <button class="btn btn-outline-primary">Solicitar relatório (Loans)</button>
        </form>
      {% endif %}
    </div>
  </div>
</div>
{% endif %}

{% if reports %}
<div class="card p-3">
  <h6 class="mb-3">Últimos relatórios recebidos</h6>
  <div class="table-responsive">
    <table class="table table-sm align-middle">
      <thead><tr><th>Quando</th><th>Produto</th><th>Request</th></tr></thead>
      <tbody>
        {% for r in reports %}
          <tr>
            <td class="mono">{{ r.received_at }}</td>
            <td>{{ r.product }}</td>
            <td class="mono">{{ r.request_id }}</td>
          </tr>
        {% endfor %}
      </tbody>
    </table>
  </div>
  <div class="form-text">Quando o relatório <code>loans</code> chegar, os contratos aparecerão em <a href="/openfinance?doc={{ doc or '' }}">Open Finance</a>.</div>
</div>
{% endif %}
{% endblock %}
""")

TEMPLATES.setdefault("openfinance_klavi_institutions.html", r"""{% extends "base.html" %}
{% block content %}
<div class="d-flex align-items-center justify-content-between mb-3">
  <div>
    <div class="h4 mb-0">Escolha a instituição (Klavi)</div>
    <div class="muted">Documento: <span class="mono">{{ doc }}</span></div>
  </div>
  <a class="btn btn-outline-secondary" href="/openfinance/klavi?doc={{ doc }}">Voltar</a>
</div>

<div class="card p-3">
  <div class="mb-2 form-text">Selecione a instituição para autorizar no Open Finance. Itens com “outage” podem falhar.</div>

  <div class="list-group">
    {% for it in institutions %}
      <div class="list-group-item">
        <div class="d-flex justify-content-between align-items-center gap-2">
          <div class="d-flex align-items-center gap-3">
            {% if it.avatar %}
              <img src="{{ it.avatar }}" alt="logo" style="width:28px;height:28px;border-radius:6px;object-fit:contain;background:#fff;border:1px solid #eee">
            {% endif %}
            <div>
              <div><strong>{{ it.name }}</strong> <span class="muted mono">({{ it.institutionCode }})</span></div>
              <div class="muted" style="font-size:12px">
                {% if it.isOutage %}<span class="text-warning">outage</span>{% else %}ok{% endif %}
                {% if it.availableResources %} • recursos: {{ it.availableResources|join(", ") }}{% endif %}
              </div>
            </div>
          </div>

          <form method="post" action="/openfinance/klavi/consent">
            <input type="hidden" name="doc" value="{{ doc }}"/>
            <input type="hidden" name="institution_code" value="{{ it.institutionCode }}"/>
            <input type="hidden" name="institution_name" value="{{ it.name }}"/>
            <button class="btn btn-primary btn-sm">Autorizar</button>
          </form>
        </div>
      </div>
    {% endfor %}
  </div>
</div>
{% endblock %}
""")

TEMPLATES.setdefault("openfinance_klavi_return.html", r"""{% extends "base.html" %}
{% block content %}
<div class="card p-4">
  <div class="d-flex justify-content-between align-items-start">
    <div>
      <h4 class="mb-1">Autorização recebida</h4>
      <div class="muted mono">{{ doc }}</div>
      {% if message %}
        <div class="mt-2">{{ message }}</div>
      {% endif %}
      {% if error %}
        <div class="text-danger mt-2"><strong>Erro:</strong> {{ error }}</div>
      {% endif %}
    </div>
    <a class="btn btn-outline-secondary" href="/openfinance/klavi?doc={{ doc }}">Voltar</a>
  </div>

  <hr class="my-3"/>

  <form method="post" action="/openfinance/klavi/request" class="d-flex gap-2">
    <input type="hidden" name="doc" value="{{ doc }}"/>
    <button class="btn btn-primary">Solicitar relatório (Loans)</button>
    <a class="btn btn-outline-secondary" href="/openfinance?doc={{ doc }}">Ver contratos/importados</a>
  </form>

  <div class="form-text mt-2">Após solicitar, aguarde o webhook de produto chegar. A página “Open Finance” mostrará os contratos importados.</div>
</div>
{% endblock %}
""")


TEMPLATES.setdefault("openfinance_connect.html", r"""{% extends "base.html" %}
{% block content %}
<div class="container py-4" style="max-width: 920px;">
  <div class="d-flex justify-content-between align-items-start">
    <div>
      <div class="h4 mb-0">🌐 Conectar Open Finance</div>
      <div class="muted">Conecte sua instituição para importar seus contratos (Loans).</div>
    </div>
    <a class="btn btn-outline-secondary" href="/">Fechar</a>
  </div>

  <div class="card p-3 mt-3">
    <div class="row g-3">
      <div class="col-md-6">
        <div class="muted small">Documento</div>
        <div class="mono fw-semibold">{{ doc_masked }}</div>
      </div>
      <div class="col-md-6">
        <div class="muted small">E-mail</div>
        <div class="fw-semibold">{{ invited_email }}</div>
      </div>
    </div>

    {% if error %}
      <div class="alert alert-danger mt-3 mb-0">{{ error }}</div>
    {% endif %}

    <hr>

    <div class="row g-2">
      <div class="col-md-8">
        <label class="form-label">Seu nome (para registro)</label>
        <input class="form-control" id="signed_by_name" placeholder="Nome completo" required>
      </div>
      <div class="col-md-4">
        <label class="form-label">4 últimos dígitos</label>
        <input class="form-control mono" id="doc_last4" maxlength="4" inputmode="numeric" placeholder="XXXX">
      </div>
      <div class="col-12">
        <div class="form-check mt-1">
          <input class="form-check-input" type="checkbox" value="1" id="chk">
          <label class="form-check-label" for="chk">
            Confirmo que sou o titular e autorizo a conexão para análise de melhores ofertas de crédito.
          </label>
        </div>
      </div>
      <div class="col-12 d-flex gap-2">
        <button class="btn btn-primary" id="btnConnect" type="button">Conectar instituição</button>
        <span class="muted small align-self-center" id="status"></span>
      </div>
    </div>
  </div>

  <div class="mt-3 muted small">
    Após concluir a conexão, você pode fechar esta página.
  </div>
</div>

<script src="{{ pluggy_js_url }}"></script>
<script>
(function(){
  const token = {{ token|tojson }};
  const statusEl = document.getElementById("status");
  const btn = document.getElementById("btnConnect");

  function setStatus(msg){ statusEl.textContent = msg || ""; }

  async function postJSON(url, payload){
    const r = await fetch(url, {
      method: "POST",
      headers: {"Content-Type":"application/json", "Accept":"application/json"},
      body: JSON.stringify(payload || {})
    });
    const t = await r.text();
    let j = {};
    try { j = JSON.parse(t); } catch(e) {}
    if(!r.ok){
      const err = (j && (j.detail || j.error)) ? (j.detail || j.error) : t;
      throw new Error(err || ("HTTP "+r.status));
    }
    return j;
  }

  btn.addEventListener("click", async function(){
    try{
      const name = (document.getElementById("signed_by_name").value || "").trim();
      const last4 = (document.getElementById("doc_last4").value || "").trim();
      const chk = document.getElementById("chk").checked;

      if(!name){ alert("Informe seu nome."); return; }
      if(!chk){ alert("Marque a autorização para continuar."); return; }

      btn.disabled = true;
      setStatus("Gerando token de conexão...");

      const tk = await postJSON("/api/pluggy/connect_token", { token, signed_by_name: name, doc_last4: last4 });
      const accessToken = tk.accessToken;

      setStatus("Abrindo Pluggy Connect...");

      const pc = new PluggyConnect({
        connectToken: accessToken,
        includeSandbox: !!tk.includeSandbox,
        onSuccess: async (itemData) => {
          try{
            setStatus("Salvando conexão e importando contratos...");
            await postJSON("/api/pluggy/item_success", { token, itemData });
            setStatus("Concluído! Você pode fechar esta página.");
          }catch(e){
            console.error(e);
            setStatus("Conectou, mas falhou ao registrar no sistema: " + (e.message || e));
          }
        },
        onError: (error) => {
          console.error(error);
          setStatus("Erro no Pluggy Connect: " + (error && (error.message || JSON.stringify(error))) );
          btn.disabled = false;
        }
      });

      pc.init();
    }catch(e){
      console.error(e);
      alert(e.message || String(e));
      btn.disabled = false;
      setStatus("");
    }
  });
})();
</script>
{% endblock %}
""")


# ----------------------------
# Routes (Open Finance)
# ----------------------------

def _mask_doc(doc_digits: str) -> str:
    d = _digits(doc_digits)
    if len(d) == 11:
        return f"{d[0:3]}.{d[3:6]}.{d[6:9]}-{d[9:11]}"
    if len(d) == 14:
        return f"{d[0:2]}.{d[2:5]}.{d[5:8]}/{d[8:12]}-{d[12:14]}"
    return d


def _openfinance_require_client(request: Request, session: Session, ctx: TenantContext) -> Optional[Client]:
    active_client_id = get_active_client_id(request, session, ctx)
    if not active_client_id and getattr(ctx.membership, "client_id", None):
        active_client_id = int(ctx.membership.client_id)
    if not active_client_id:
        return None
    return get_client_or_none(session, ctx.company.id, int(active_client_id))



def ensure_feature_access_tables() -> None:
    try:
        SQLModel.metadata.create_all(
            engine,
            tables=[MembershipFeatureAccess.__table__, ClientFeatureAccess.__table__],
            checkfirst=True,
        )
    except Exception:
        pass


def _parse_json_list(raw: str) -> list[str]:
    raw = (raw or "").strip()
    if not raw:
        return []
    try:
        v = json.loads(raw)
        if isinstance(v, list):
            return [str(x) for x in v]
    except Exception:
        pass
    return []


def get_membership_allowed_features(session: Session, *, company_id: int, membership: Membership) -> set[str]:
    base = set(ROLE_DEFAULT_FEATURES.get(membership.role, set()))
    if not membership.id:
        return base

    try:
        row = session.exec(
            select(MembershipFeatureAccess).where(
                MembershipFeatureAccess.company_id == company_id,
                MembershipFeatureAccess.membership_id == membership.id,
            )
        ).first()
    except Exception:
        try:
            ensure_feature_access_tables()
        except Exception:
            pass
        return base

    if row:
        lst = _parse_json_list(row.features_json)
        if lst:
            return set(lst)
    return base

def get_client_allowed_features(session: Session, *, company_id: int, client_id: int) -> Optional[set[str]]:
    try:
        row = session.exec(
            select(ClientFeatureAccess).where(
                ClientFeatureAccess.company_id == company_id,
                ClientFeatureAccess.client_id == client_id,
            )
        ).first()
    except Exception:
        try:
            ensure_feature_access_tables()
        except Exception:
            pass
        return None

    if not row:
        return None
    lst = _parse_json_list(row.features_json)
    return set(lst) if lst else None

def effective_allowed_features(session: Session, *, ctx: TenantContext, current_client: Optional[Client]) -> set[str]:
    try:
        allowed = get_membership_allowed_features(session, company_id=ctx.company.id, membership=ctx.membership)

        if ctx.membership.role == "cliente" and current_client and current_client.id:
            client_allowed = get_client_allowed_features(session, company_id=ctx.company.id, client_id=current_client.id)
            if client_allowed is not None:
                allowed = allowed.intersection(client_allowed)

        return {k for k in allowed if k in FEATURE_KEYS}
    except Exception:
        base = set(ROLE_DEFAULT_FEATURES.get(ctx.membership.role, set()))
        return {k for k in base if k in FEATURE_KEYS}

def resolve_feature_key(path: str) -> Optional[str]:
    if path.startswith("/static/") or path.startswith("/login") or path.startswith("/logout"):
        return None
    if path.startswith("/api/"):
        return None
    if path in {"/", "/health"}:
        return None

    mapping = [
        ("/admin/ui", "ui"),
        ("/admin/gestao", "gestao"),
        ("/admin/parceiros", "parceiros"),
        ("/admin/servicos-internos", "servicos_internos"),
        ("/motor-ofertas", "motor_ofertas"),
        ("/ofertas", "ofertas"),
        ("/admin/members", "gestao"),
        ("/admin/clients", "gestao"),
        ("/negocios", "crm"),
        ("/credito", "credito"),
        ("/empresa", "empresa"),
        ("/perfil", "perfil"),
        ("/financeiro", "financeiro"),
        ("/documentos", "documentos"),
        ("/consultoria", "consultoria"),
        ("/reunioes", "reunioes"),
        ("/tarefas", "tarefas"),
        ("/simulador", "simulador"),
        ("/propostas", "propostas"),
        ("/pendencias", "pendencias"),
        ("/agenda", "agenda"),
        ("/educacao", "educacao"),
    ]
    for prefix, key in mapping:
        if path == prefix or path.startswith(prefix + "/"):
            return key
    return None

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
        if c and c.company_id == company_id and entity_is_allowed(session, entity_type="client", entity_id=c.id):
            return cid

    clients = session.exec(
        select(Client).where(Client.company_id == company_id).order_by(Client.created_at)
    ).all()
    first_client = next((c for c in clients if c.id and entity_is_allowed(session, entity_type="client", entity_id=c.id)), None)
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


# =========================
# Meetings (Notion AI Meeting Notes sync)
# =========================

class Meeting(SQLModel, table=True):
    """Meeting record linked to a client; can be synced from a Notion AI Meeting Notes page."""
    id: Optional[int] = Field(default=None, primary_key=True)

    company_id: int = Field(index=True, foreign_key="company.id")
    client_id: int = Field(index=True, foreign_key="client.id")
    created_by_user_id: int = Field(index=True, foreign_key="user.id")

    title: str = ""
    meeting_date: str = ""  # AAAA-MM-DD (simple)
    source: str = Field(default="notion", index=True)

    notion_page_id: str = Field(default="", index=True)  # normalized UUID (with hyphens)
    notion_url: str = ""
    notion_meeting_block_id: str = Field(default="", index=True)
    notion_status: str = Field(default="", index=True)

    summary_text: str = ""
    notes_text: str = ""
    transcript_text: str = ""
    action_items_text: str = ""

    raw_json: str = Field(default="{}")
    last_synced_at: Optional[datetime] = None

    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class MeetingMessage(SQLModel, table=True):
    """Thread messages about a meeting (internal + client)."""
    id: Optional[int] = Field(default=None, primary_key=True)

    meeting_id: int = Field(index=True, foreign_key="meeting.id")
    author_user_id: int = Field(index=True, foreign_key="user.id")

    message: str
    created_at: datetime = Field(default_factory=utcnow)


_MEETING_NOTION_STATUSES = {
    "transcription_not_started",
    "transcription_paused",
    "transcription_in_progress",
    "summary_in_progress",
    "notes_ready",
}


def _normalize_uuid(raw: str) -> str:
    s = (raw or "").strip()
    # Extract 32 hex chars if URL-like
    m = re.search(r"([0-9a-fA-F]{32})", s)
    if m:
        s = m.group(1)
    s = s.replace("-", "").lower()
    if len(s) != 32 or not re.fullmatch(r"[0-9a-f]{32}", s):
        return ""
    return f"{s[0:8]}-{s[8:12]}-{s[12:16]}-{s[16:20]}-{s[20:32]}"


def _notion_headers() -> dict[str, str]:
    if not NOTION_TOKEN:
        raise RuntimeError("NOTION_TOKEN não está configurado.")
    return {
        "Authorization": f"Bearer {NOTION_TOKEN}",
        "Notion-Version": NOTION_VERSION,
    }


async def _notion_get_json(path: str, *, params: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    url = f"{NOTION_API_BASE}{path}"
    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.get(url, headers=_notion_headers(), params=params or {})
        r.raise_for_status()
        data = r.json()
        return data if isinstance(data, dict) else {}


async def _notion_list_block_children_all(block_id: str) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    cursor: Optional[str] = None
    while True:
        params = {"page_size": 100}
        if cursor:
            params["start_cursor"] = cursor
        data = await _notion_get_json(f"/blocks/{block_id}/children", params=params)
        chunk = data.get("results") or []
        if isinstance(chunk, list):
            results.extend([x for x in chunk if isinstance(x, dict)])
        if not data.get("has_more"):
            break
        cursor = data.get("next_cursor")
        if not cursor:
            break
    return results


def _rt_plain(rich_text: Any) -> str:
    if not isinstance(rich_text, list):
        return ""
    parts: list[str] = []
    for rt in rich_text:
        if not isinstance(rt, dict):
            continue
        pt = rt.get("plain_text")
        if isinstance(pt, str):
            parts.append(pt)
        else:
            t = rt.get("text", {})
            if isinstance(t, dict) and isinstance(t.get("content"), str):
                parts.append(t["content"])
    return "".join(parts).strip()


async def _notion_blocks_to_lines(block_id: str, *, depth: int = 0, max_depth: int = 4) -> list[str]:
    if depth > max_depth:
        return []
    blocks = await _notion_list_block_children_all(block_id)
    out: list[str] = []
    for b in blocks:
        btype = b.get("type")
        if not isinstance(btype, str):
            continue
        data = b.get(btype, {}) if isinstance(b.get(btype), dict) else {}

        line = ""
        if btype in {"paragraph", "quote", "callout"}:
            line = _rt_plain(data.get("rich_text") or data.get("text"))
            if btype == "quote" and line:
                line = f"> {line}"
            if btype == "callout" and line:
                line = f"💬 {line}"
        elif btype in {"heading_1", "heading_2", "heading_3"}:
            h = _rt_plain(data.get("rich_text") or data.get("text"))
            if h:
                prefix = "#" if btype == "heading_1" else "##" if btype == "heading_2" else "###"
                line = f"{prefix} {h}"
        elif btype in {"bulleted_list_item", "numbered_list_item"}:
            t = _rt_plain(data.get("rich_text") or data.get("text"))
            if t:
                bullet = "-" if btype == "bulleted_list_item" else "1."
                line = f"{bullet} {t}"
        elif btype == "to_do":
            t = _rt_plain(data.get("rich_text") or data.get("text"))
            checked = bool(data.get("checked"))
            box = "☑" if checked else "☐"
            if t:
                line = f"{box} {t}"
        elif btype == "toggle":
            t = _rt_plain(data.get("rich_text") or data.get("text"))
            if t:
                line = f"▸ {t}"
        elif btype == "code":
            t = _rt_plain(data.get("rich_text") or data.get("text"))
            lang = data.get("language") if isinstance(data.get("language"), str) else ""
            if t:
                line = f"```{lang}\n{t}\n```"
        else:
            # Fallback for other blocks that have rich_text
            if isinstance(data, dict):
                t = _rt_plain(data.get("rich_text") or data.get("text"))
                if t:
                    line = t

        if line:
            out.append(("  " * depth) + line)

        if b.get("has_children") and isinstance(b.get("id"), str):
            child_lines = await _notion_blocks_to_lines(b["id"], depth=depth + 1, max_depth=max_depth)
            out.extend(child_lines)

    return [x for x in out if isinstance(x, str) and x.strip()]


def _extract_action_items_from_lines(lines: list[str]) -> str:
    if not lines:
        return ""
    actions: list[str] = []
    in_actions = False
    for ln in lines:
        low = ln.lower()
        if low.startswith("#") and ("action" in low or "ação" in low or "acoes" in low or "ações" in low):
            in_actions = True
            continue
        if low.startswith("#") and in_actions:
            # next heading ends action section
            in_actions = False
        if in_actions:
            if ln.strip().startswith(("-", "☐", "☑", "1.")):
                actions.append(ln.strip())
        else:
            # also accept to-do items anywhere
            if ln.strip().startswith(("☐", "☑")):
                actions.append(ln.strip())
    return "\n".join(actions).strip()


async def _notion_find_meeting_notes_block(page_id: str) -> Optional[dict[str, Any]]:
    # BFS up to a small depth: page children -> nested children
    queue = [(page_id, 0)]
    seen: set[str] = set()
    while queue:
        bid, depth = queue.pop(0)
        if bid in seen:
            continue
        seen.add(bid)
        blocks = await _notion_list_block_children_all(bid)
        for b in blocks:
            btype = b.get("type")
            if btype in {"meeting_notes", "transcription"}:
                return b
        if depth < 3:
            for b in blocks:
                if b.get("has_children") and isinstance(b.get("id"), str):
                    queue.append((b["id"], depth + 1))
    return None


async def notion_sync_meeting_from_page(page_id_or_url: str) -> dict[str, Any]:
    page_id = _normalize_uuid(page_id_or_url)
    if not page_id:
        raise ValueError("Não foi possível extrair o ID da página do Notion.")
    meeting_block = await _notion_find_meeting_notes_block(page_id)
    if not meeting_block:
        raise ValueError("Não encontrei um bloco de AI Meeting Notes nessa página (meeting_notes/transcription).")

    block_id = meeting_block.get("id", "")
    prop = meeting_block.get("meeting_notes") or meeting_block.get("transcription") or {}
    title = _rt_plain(prop.get("title")) if isinstance(prop, dict) else ""
    status = prop.get("status") if isinstance(prop, dict) and isinstance(prop.get("status"), str) else ""
    children = prop.get("children") if isinstance(prop, dict) else {}
    if not isinstance(children, dict):
        children = {}

    summary_block_id = children.get("summary_block_id") if isinstance(children.get("summary_block_id"), str) else ""
    notes_block_id = children.get("notes_block_id") if isinstance(children.get("notes_block_id"), str) else ""
    transcript_block_id = children.get("transcript_block_id") if isinstance(children.get("transcript_block_id"),
                                                                            str) else ""

    summary_lines = await _notion_blocks_to_lines(summary_block_id) if summary_block_id else []
    notes_lines = await _notion_blocks_to_lines(notes_block_id) if notes_block_id else []
    transcript_lines = await _notion_blocks_to_lines(transcript_block_id) if transcript_block_id else []

    action_items = _extract_action_items_from_lines(summary_lines + notes_lines)

    return {
        "page_id": page_id,
        "meeting_block_id": block_id,
        "title": title,
        "status": status,
        "summary_text": "\n".join(summary_lines).strip(),
        "notes_text": "\n".join(notes_lines).strip(),
        "transcript_text": "\n".join(transcript_lines).strip(),
        "action_items_text": action_items,
        "raw": meeting_block,
    }



TEMPLATES.setdefault("consulta_consent_accept.html", r"""{% extends "base.html" %}
{% block content %}
<div class="container py-4" style="max-width: 900px;">
  <div class="card p-4">
    <div class="d-flex align-items-center justify-content-between">
      <div>
        <div class="fw-semibold">Aceite para consulta ao SCR (Bacen)</div>
        <div class="muted small">{{ company.name }}</div>
      </div>
      <span class="badge bg-secondary">Público</span>
    </div>

    <hr class="my-3"/>

    <div class="mb-2">
      <div class="muted small">Documento (CPF/CNPJ) consultado:</div>
      <div class="fw-semibold mono">{{ doc_masked }}</div>
    </div>

    <div class="border rounded p-3 bg-light" style="max-height: 260px; overflow:auto;">
      {{ terms_html|safe }}
    </div>

    {% if error %}
      <div class="alert alert-danger mt-3 mb-0">{{ error }}</div>
    {% endif %}

    <form method="post" action="/consultas/consent/aceite/{{ token }}" class="mt-3">
      <div class="row g-2">
        <div class="col-md-8">
          <label class="form-label">Seu nome</label>
          <input class="form-control" name="signed_by_name" value="{{ form.name }}" required>
        </div>
        <div class="col-md-4">
          <label class="form-label">4 últimos dígitos</label>
          <input class="form-control" name="doc_last4" placeholder="XXXX" maxlength="4" inputmode="numeric">
          <div class="form-text">Para confirmar que você é o titular do documento.</div>
        </div>
        <div class="col-12">
          <div class="form-check mt-1">
            <input class="form-check-input" type="checkbox" name="agree" id="agree" required>
            <label class="form-check-label" for="agree">Li o termo e autorizo a consulta ao SCR.</label>
          </div>
          <div class="muted small mt-2">
            Registraremos evidências do aceite (data/hora, IP e navegador) para auditoria.
          </div>
        </div>
        <div class="col-12">
          <button class="btn btn-primary" type="submit">Confirmar aceite</button>
        </div>
      </div>
    </form>

    <div class="muted small mt-3">Você pode fechar esta página após confirmar.</div>
  </div>
</div>
{% endblock %}
""")

TEMPLATES.update({"admin_ui.html": r"""{% extends "base.html" %}
{% block content %}
<div class="d-flex align-items-center justify-content-between">
  <div>
    <h4 class="mb-0">Configurações de UI</h4>
    <div class="muted small">Banner do topo e feeds de notícias.</div>
  </div>
</div>

<div class="row g-3 mt-2">

  <div class="col-12">
    <div class="card p-3">
      <div class="fw-semibold mb-2">Banner (carrossel)</div>

      <form method="post" action="/admin/ui/banner/add" enctype="multipart/form-data" class="row g-2">
        <div class="col-md-3">
          <label class="form-label small muted">Título</label>
          <input class="form-control" name="title" placeholder="Ex.: Simule seu crédito">
        </div>
        <div class="col-md-3">
          <label class="form-label small muted">Link interno</label>
          <input class="form-control" name="link_path" placeholder="/simulador" value="/simulador">
        </div>
        <div class="col-md-3">
          <label class="form-label small muted">Imagem (URL)</label>
          <input class="form-control" name="image_url" placeholder="https://...">
          <div class="form-text">Ou envie um arquivo.</div>
        </div>
        <div class="col-md-3">
          <label class="form-label small muted">Upload</label>
          <input class="form-control" type="file" name="image_file" accept="image/*">
        </div>
        <div class="col-md-2">
          <label class="form-label small muted">Ordem</label>
          <input class="form-control" name="sort_order" value="0">
        </div>
        <div class="col-md-2 d-flex align-items-end">
          <div class="form-check">
            <input class="form-check-input" type="checkbox" name="is_active" checked>
            <label class="form-check-label small">Ativo</label>
          </div>
        </div>
        <div class="col-md-8 d-flex align-items-end gap-2">
          <button class="btn btn-primary" type="submit">Adicionar</button>
          <a class="btn btn-outline-secondary" href="/">Voltar</a>
        </div>
      </form>

      <hr class="my-3"/>

      {% if slides %}
        <div class="table-responsive">
          <table class="table table-sm align-middle">
            <thead>
              <tr class="muted small">
                <th>#</th><th>Preview</th><th>Título</th><th>Link</th><th>Ordem</th><th>Status</th><th></th>
              </tr>
            </thead>
            <tbody>
              {% for s in slides %}
              <tr>
                <td class="mono">{{ s.id }}</td>
                <td style="width:140px;">
                  <img src="{{ s.image_url }}" style="height:44px; width:120px; object-fit:cover; border-radius:10px;" />
                </td>
                <td>{{ s.title }}</td>
                <td class="mono">{{ s.link_path }}</td>
                <td>{{ s.sort_order }}</td>
                <td>
                  {% if s.is_active %}
                    <span class="badge text-bg-success">Ativo</span>
                  {% else %}
                    <span class="badge text-bg-secondary">Inativo</span>
                  {% endif %}
                </td>
                <td class="text-end">
                  <form method="post" action="/admin/ui/banner/{{ s.id }}/toggle" style="display:inline;">
                    <button class="btn btn-sm btn-outline-primary" type="submit">Alternar</button>
                  </form>
                  <form method="post" action="/admin/ui/banner/{{ s.id }}/delete" style="display:inline;" onsubmit="return confirm('Remover slide?');">
                    <button class="btn btn-sm btn-outline-danger" type="submit">Excluir</button>
                  </form>
                </td>
              </tr>
              {% endfor %}
            </tbody>
          </table>
        </div>
      {% else %}
        <div class="muted small">Nenhum slide cadastrado.</div>
      {% endif %}
    </div>
  </div>

  <div class="col-12">
    <div class="card p-3">
      <div class="fw-semibold mb-2">Feeds de notícias</div>

      <form method="post" action="/admin/ui/feed/add" class="row g-2">
        <div class="col-md-3">
          <label class="form-label small muted">Nome</label>
          <input class="form-control" name="name" placeholder="Ex.: Money Times" required>
        </div>
        <div class="col-md-7">
          <label class="form-label small muted">URL do RSS/Atom</label>
          <input class="form-control" name="url" placeholder="https://..." required>
        </div>
        <div class="col-md-2">
          <label class="form-label small muted">Ordem</label>
          <input class="form-control" name="sort_order" value="0">
        </div>
        <div class="col-md-2 d-flex align-items-end">
          <div class="form-check">
            <input class="form-check-input" type="checkbox" name="is_active" checked>
            <label class="form-check-label small">Ativo</label>
          </div>
        </div>
        <div class="col-md-10 d-flex align-items-end">
          <button class="btn btn-primary" type="submit">Adicionar feed</button>
        </div>
      </form>

      <hr class="my-3"/>

      {% if feeds %}
        <div class="table-responsive">
          <table class="table table-sm align-middle">
            <thead>
              <tr class="muted small">
                <th>#</th><th>Nome</th><th>URL</th><th>Ordem</th><th>Status</th><th></th>
              </tr>
            </thead>
            <tbody>
              {% for f in feeds %}
              <tr>
                <td class="mono">{{ f.id }}</td>
                <td>{{ f.name }}</td>
                <td class="mono">{{ f.url }}</td>
                <td>{{ f.sort_order }}</td>
                <td>
                  {% if f.is_active %}
                    <span class="badge text-bg-success">Ativo</span>
                  {% else %}
                    <span class="badge text-bg-secondary">Inativo</span>
                  {% endif %}
                </td>
                <td class="text-end">
                  <form method="post" action="/admin/ui/feed/{{ f.id }}/toggle" style="display:inline;">
                    <button class="btn btn-sm btn-outline-primary" type="submit">Alternar</button>
                  </form>
                  <form method="post" action="/admin/ui/feed/{{ f.id }}/delete" style="display:inline;" onsubmit="return confirm('Remover feed?');">
                    <button class="btn btn-sm btn-outline-danger" type="submit">Excluir</button>
                  </form>
                </td>
              </tr>
              {% endfor %}
            </tbody>
          </table>
        </div>
      {% else %}
        <div class="muted small">Nenhum feed cadastrado.</div>
      {% endif %}
      <div class="muted small mt-2">
        Dica: use feeds RSS/Atom oficiais sempre que possível.
      </div>
    </div>
  </div>

</div>
{% endblock %}""",})



def render(
        template_name: str,
        *,
        request: Request,
        context: Optional[dict[str, Any]] = None,
        status_code: int = 200,
) -> HTMLResponse:
    ctx = context or {}
    ctx["request"] = request
    ctx.setdefault("title", "App Escritório")
    ctx.setdefault("flash", request.session.pop("flash", None) if hasattr(request, "session") else None)
    ctx.setdefault("allow_company_signup", ALLOW_COMPANY_SIGNUP)
    ctx.setdefault("service_catalog", SERVICE_CATALOG)
    ctx.setdefault("bookings_url", BOOKINGS_URL)

    # Inject tenant context defaults for templates that expect them.
    try:
        with Session(engine) as _db:
            _t = get_tenant_context(request, _db)
            if _t:
                ctx.setdefault("current_user", _t.user)
                ctx.setdefault("current_company", _t.company)
                active_client_id = get_active_client_id(request, _db, _t)
                ctx.setdefault("current_client", get_client_or_none(_db, _t.company.id, active_client_id))
                ctx.setdefault("role", _t.membership.role)
    except Exception:
        pass
    return HTMLResponse(templates_env.get_template(template_name).render(**ctx), status_code=status_code)


# ----------------------------
# App
# ----------------------------

app = FastAPI()


def _pluggy_schedule_sync_loans(*, company_id: int, subject_doc: str, item_id: str) -> None:
    async def _runner() -> None:
        with Session(engine) as s:
            await pluggy_sync_loans(session=s, company_id=company_id, subject_doc=subject_doc, item_id=item_id)

    asyncio.create_task(_runner())


@app.get("/__routes", include_in_schema=False)
async def __routes() -> list[str]:
    return sorted({getattr(r, "path", "") for r in app.router.routes})

@app.get("/__build", include_in_schema=False)
async def __build() -> dict:
    return {"build": "stable_debug_v2"}

https_only = os.getenv("SESSION_HTTPS_ONLY", "0") == "1"
# NOTE: SessionMiddleware must wrap feature_access_middleware, installed later.

STATIC_DIR = Path(__file__).with_name("static").resolve()
STATIC_DIR.mkdir(parents=True, exist_ok=True)

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

@app.middleware("http")
async def feature_access_middleware(request: Request, call_next: Callable[..., Any]) -> Response:
    path = request.url.path
    if (
        path.startswith("/__")
        or path.startswith("/health")
        or path.startswith("/healthz")
        or path.startswith("/static")
        or path.startswith("/api/ui/")
        or path.startswith("/stripe/webhook")
    ):
        return await call_next(request)

    key = resolve_feature_key(request.url.path)
    if key is None:
        return await call_next(request)

    if session_user_id(request) is None:
        return await call_next(request)

    session = Session(engine)
    try:
        ctx = get_tenant_context(request, session)
        if not ctx:
            return await call_next(request)

        active_client_id = get_active_client_id(request, session, ctx)
        current_client = get_client_or_none(session, ctx.company.id, active_client_id)

        try:
            allowed = effective_allowed_features(session, ctx=ctx, current_client=current_client)
        except Exception:
            allowed = set(ROLE_DEFAULT_FEATURES.get(ctx.membership.role, set()))

        roles = FEATURE_VISIBLE_ROLES.get(key)
        if roles and ctx.membership.role not in roles:
            return render(
                "error.html",
                request=request,
                context={
                    "current_user": ctx.user,
                    "current_company": ctx.company,
                    "role": ctx.membership.role,
                    "current_client": current_client,
                    "message": "Você não tem permissão para acessar esta área.",
                },
                status_code=403,
            )

        if key not in allowed:
            return render(
                "error.html",
                request=request,
                context={
                    "current_user": ctx.user,
                    "current_company": ctx.company,
                    "role": ctx.membership.role,
                    "current_client": current_client,
                    "message": "Acesso não habilitado para este usuário/cliente.",
                },
                status_code=403,
            )

        return await call_next(request)
    finally:
        session.close()




# Install SessionMiddleware last so request.session is available inside BaseHTTPMiddleware.
app.add_middleware(SessionMiddleware, secret_key=APP_SECRET_KEY, https_only=https_only, same_site="lax")


@app.on_event("startup")
def _startup() -> None:
    init_db()
    ensure_ui_tables()
    ensure_feature_access_tables()
    ensure_credit_consent_table()
    ensure_partner_tables()
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

    q = select(ConsultingProject).where(ConsultingProject.company_id == ctx.company.id).order_by(
        ConsultingProject.created_at.desc())

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

    # Garante tabelas em ambientes sem Alembic
    if not ensure_credit_consent_table():
        set_flash(request, "Sistema de aceite não está configurado (migração pendente no banco).")
        return RedirectResponse("/credito", status_code=303)

    if not ensure_client_invite_table():
        set_flash(request, "Sistema de convites não está configurado (migração pendente no banco).")
        return RedirectResponse("/client/switch", status_code=303)

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


@app.get("/consultoria/{project_id}/editar", response_class=HTMLResponse)
@require_role({"admin", "equipe"})
async def consultoria_edit_project_page(request: Request, session: Session = Depends(get_session),
                                        project_id: int = 0) -> HTMLResponse:
    ctx = get_tenant_context(request, session)
    assert ctx is not None

    # Garante tabela em ambientes sem Alembic
    if not ensure_credit_consent_table():
        set_flash(request, "Sistema de aceite não está configurado (migração pendente no banco).")
        return RedirectResponse("/credito", status_code=303)

    project = session.get(ConsultingProject, int(project_id))
    if not project or project.company_id != ctx.company.id:
        return render("error.html", request=request, context={"message": "Projeto não encontrado."}, status_code=404)

    client = session.get(Client, project.client_id)
    active_client_id = get_active_client_id(request, session, ctx)
    current_client = get_client_or_none(session, ctx.company.id, active_client_id)

    return render(
        "consult_edit_project.html",
        request=request,
        context={"current_user": ctx.user, "current_company": ctx.company, "role": ctx.membership.role,
                 "current_client": current_client, "project": project, "client": client},
    )


@app.post("/consultoria/{project_id}/editar")
@require_role({"admin", "equipe"})
async def consultoria_edit_project_action(
        request: Request,
        session: Session = Depends(get_session),
        project_id: int = 0,
        name: str = Form(...),
        status: str = Form("ativo"),
        start_date: str = Form(""),
        due_date: str = Form(""),
        description: str = Form(""),
) -> Response:
    ctx = get_tenant_context(request, session)
    assert ctx is not None

    # Garante tabela em ambientes sem Alembic
    if not ensure_credit_consent_table():
        set_flash(request, "Sistema de aceite não está configurado (migração pendente no banco).")
        return RedirectResponse("/credito", status_code=303)

    project = session.get(ConsultingProject, int(project_id))
    if not project or project.company_id != ctx.company.id:
        set_flash(request, "Projeto não encontrado.")
        return RedirectResponse("/consultoria", status_code=303)

    status = status.strip().lower()
    if status not in {"ativo", "pausado", "concluido"}:
        status = "ativo"

    project.name = name.strip()
    project.status = status
    project.start_date = start_date.strip()
    project.due_date = due_date.strip()
    project.description = description.strip()
    project.updated_at = utcnow()

    session.add(project)
    session.commit()

    set_flash(request, "Projeto atualizado.")
    return RedirectResponse(f"/consultoria/{project.id}", status_code=303)


@app.post("/consultoria/{project_id}/excluir")
@require_role({"admin", "equipe"})
async def consultoria_delete_project(request: Request, session: Session = Depends(get_session),
                                     project_id: int = 0) -> Response:
    ctx = get_tenant_context(request, session)
    assert ctx is not None

    # Garante tabela em ambientes sem Alembic
    if not ensure_credit_consent_table():
        set_flash(request, "Sistema de aceite não está configurado (migração pendente no banco).")
        return RedirectResponse("/credito", status_code=303)

    project = session.get(ConsultingProject, int(project_id))
    if not project or project.company_id != ctx.company.id:
        set_flash(request, "Projeto não encontrado.")
        return RedirectResponse("/consultoria", status_code=303)

    stages = session.exec(select(ConsultingStage).where(ConsultingStage.project_id == project.id)).all()
    stage_ids = [s.id for s in stages]
    if stage_ids:
        steps = session.exec(select(ConsultingStep).where(ConsultingStep.stage_id.in_(stage_ids))).all()
        for st in steps:
            session.delete(st)
    for s in stages:
        session.delete(s)

    session.delete(project)
    session.commit()

    set_flash(request, "Projeto excluído.")
    return RedirectResponse("/consultoria", status_code=303)


@app.get("/consultoria/stages/{stage_id}/editar", response_class=HTMLResponse)
@require_role({"admin", "equipe"})
async def consultoria_edit_stage_page(request: Request, session: Session = Depends(get_session),
                                      stage_id: int = 0) -> HTMLResponse:
    ctx = get_tenant_context(request, session)
    assert ctx is not None

    # Garante tabela em ambientes sem Alembic
    if not ensure_credit_consent_table():
        set_flash(request, "Sistema de aceite não está configurado (migração pendente no banco).")
        return RedirectResponse("/credito", status_code=303)

    stage = session.get(ConsultingStage, int(stage_id))
    if not stage:
        return render("error.html", request=request, context={"message": "Etapa não encontrada."}, status_code=404)

    project = session.get(ConsultingProject, stage.project_id)
    if not project or project.company_id != ctx.company.id:
        return render("error.html", request=request, context={"message": "Projeto inválido."}, status_code=403)

    active_client_id = get_active_client_id(request, session, ctx)
    current_client = get_client_or_none(session, ctx.company.id, active_client_id)

    return render(
        "consult_edit_stage.html",
        request=request,
        context={"current_user": ctx.user, "current_company": ctx.company, "role": ctx.membership.role,
                 "current_client": current_client, "stage": stage, "project": project},
    )


@app.post("/consultoria/stages/{stage_id}/editar")
@require_role({"admin", "equipe"})
async def consultoria_edit_stage_action(
        request: Request,
        session: Session = Depends(get_session),
        stage_id: int = 0,
        name: str = Form(...),
        due_date: str = Form(""),
        order: int = Form(1),
) -> Response:
    ctx = get_tenant_context(request, session)
    assert ctx is not None

    # Garante tabela em ambientes sem Alembic
    if not ensure_credit_consent_table():
        set_flash(request, "Sistema de aceite não está configurado (migração pendente no banco).")
        return RedirectResponse("/credito", status_code=303)

    stage = session.get(ConsultingStage, int(stage_id))
    if not stage:
        set_flash(request, "Etapa não encontrada.")
        return RedirectResponse("/consultoria", status_code=303)

    project = session.get(ConsultingProject, stage.project_id)
    if not project or project.company_id != ctx.company.id:
        set_flash(request, "Projeto inválido.")
        return RedirectResponse("/consultoria", status_code=303)

    stage.name = name.strip()
    stage.due_date = due_date.strip()

    try:
        desired_order = int(order)
    except Exception:
        desired_order = stage.order

    if desired_order != stage.order:
        stage.order = max(1, desired_order)
        _move_stage_to_order(session, stage, stage.order)
    else:
        session.add(stage)
        session.commit()

    set_flash(request, "Etapa atualizada.")
    return RedirectResponse(f"/consultoria/{project.id}", status_code=303)


@app.post("/consultoria/stages/{stage_id}/excluir")
@require_role({"admin", "equipe"})
async def consultoria_delete_stage(request: Request, session: Session = Depends(get_session),
                                   stage_id: int = 0) -> Response:
    ctx = get_tenant_context(request, session)
    assert ctx is not None

    # Garante tabela em ambientes sem Alembic
    if not ensure_credit_consent_table():
        set_flash(request, "Sistema de aceite não está configurado (migração pendente no banco).")
        return RedirectResponse("/credito", status_code=303)

    stage = session.get(ConsultingStage, int(stage_id))
    if not stage:
        set_flash(request, "Etapa não encontrada.")
        return RedirectResponse("/consultoria", status_code=303)

    project = session.get(ConsultingProject, stage.project_id)
    if not project or project.company_id != ctx.company.id:
        set_flash(request, "Projeto inválido.")
        return RedirectResponse("/consultoria", status_code=303)

    steps = session.exec(select(ConsultingStep).where(ConsultingStep.stage_id == stage.id)).all()
    for st in steps:
        session.delete(st)
    session.delete(stage)
    session.commit()

    set_flash(request, "Etapa excluída.")
    return RedirectResponse(f"/consultoria/{project.id}", status_code=303)


@app.get("/consultoria/steps/{step_id}/editar", response_class=HTMLResponse)
@require_role({"admin", "equipe"})
async def consultoria_edit_step_page(request: Request, session: Session = Depends(get_session),
                                     step_id: int = 0) -> HTMLResponse:
    ctx = get_tenant_context(request, session)
    assert ctx is not None

    # Garante tabela em ambientes sem Alembic
    if not ensure_credit_consent_table():
        set_flash(request, "Sistema de aceite não está configurado (migração pendente no banco).")
        return RedirectResponse("/credito", status_code=303)

    step = session.get(ConsultingStep, int(step_id))
    if not step:
        return render("error.html", request=request, context={"message": "Sub-etapa não encontrada."}, status_code=404)

    stage = session.get(ConsultingStage, step.stage_id)
    project = session.get(ConsultingProject, stage.project_id) if stage else None
    if not project or project.company_id != ctx.company.id:
        return render("error.html", request=request, context={"message": "Projeto inválido."}, status_code=403)

    active_client_id = get_active_client_id(request, session, ctx)
    current_client = get_client_or_none(session, ctx.company.id, active_client_id)

    return render(
        "consult_edit_step.html",
        request=request,
        context={"current_user": ctx.user, "current_company": ctx.company, "role": ctx.membership.role,
                 "current_client": current_client, "step": step, "project": project},
    )


@app.post("/consultoria/steps/{step_id}/editar")
@require_role({"admin", "equipe"})
async def consultoria_edit_step_action(
        request: Request,
        session: Session = Depends(get_session),
        step_id: int = 0,
        title: str = Form(...),
        description: str = Form(""),
        due_date: str = Form(""),
        weight: float = Form(1.0),
        client_action: str = Form(""),
) -> Response:
    ctx = get_tenant_context(request, session)
    assert ctx is not None

    # Garante tabela em ambientes sem Alembic
    if not ensure_credit_consent_table():
        set_flash(request, "Sistema de aceite não está configurado (migração pendente no banco).")
        return RedirectResponse("/credito", status_code=303)

    step = session.get(ConsultingStep, int(step_id))
    if not step:
        set_flash(request, "Sub-etapa não encontrada.")
        return RedirectResponse("/consultoria", status_code=303)

    stage = session.get(ConsultingStage, step.stage_id)
    project = session.get(ConsultingProject, stage.project_id) if stage else None
    if not project or project.company_id != ctx.company.id:
        set_flash(request, "Projeto inválido.")
        return RedirectResponse("/consultoria", status_code=303)

    step.title = title.strip()
    step.description = description.strip()
    step.due_date = due_date.strip()
    step.weight = max(0.1, float(weight))
    step.client_action = (client_action == "1")
    step.updated_at = utcnow()

    session.add(step)
    session.commit()

    set_flash(request, "Sub-etapa atualizada.")
    return RedirectResponse(f"/consultoria/{project.id}", status_code=303)


@app.post("/consultoria/steps/{step_id}/excluir")
@require_role({"admin", "equipe"})
async def consultoria_delete_step(request: Request, session: Session = Depends(get_session),
                                  step_id: int = 0) -> Response:
    ctx = get_tenant_context(request, session)
    assert ctx is not None

    # Garante tabela em ambientes sem Alembic
    if not ensure_credit_consent_table():
        set_flash(request, "Sistema de aceite não está configurado (migração pendente no banco).")
        return RedirectResponse("/credito", status_code=303)

    step = session.get(ConsultingStep, int(step_id))
    if not step:
        set_flash(request, "Sub-etapa não encontrada.")
        return RedirectResponse("/consultoria", status_code=303)

    stage = session.get(ConsultingStage, step.stage_id)
    project = session.get(ConsultingProject, stage.project_id) if stage else None
    if not project or project.company_id != ctx.company.id:
        set_flash(request, "Projeto inválido.")
        return RedirectResponse("/consultoria", status_code=303)

    session.delete(step)
    session.commit()

    set_flash(request, "Sub-etapa excluída.")
    return RedirectResponse(f"/consultoria/{project.id}", status_code=303)


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

    # Garante tabela em ambientes sem Alembic
    if not ensure_credit_consent_table():
        set_flash(request, "Sistema de aceite não está configurado (migração pendente no banco).")
        return RedirectResponse("/credito", status_code=303)

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
async def consultoria_detail(request: Request, session: Session = Depends(get_session),
                             project_id: int = 0) -> HTMLResponse:
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
        stage_view.append({"id": s.id, "name": s.name, "order": s.order, "due_date": s.due_date,
                           "steps": steps_by_stage.get(s.id, [])})

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

    # Garante tabela em ambientes sem Alembic
    if not ensure_credit_consent_table():
        set_flash(request, "Sistema de aceite não está configurado (migração pendente no banco).")
        return RedirectResponse("/credito", status_code=303)

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

    # Garante tabela em ambientes sem Alembic
    if not ensure_credit_consent_table():
        set_flash(request, "Sistema de aceite não está configurado (migração pendente no banco).")
        return RedirectResponse("/credito", status_code=303)

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
# Health
# ----------------------------

@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


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

    allowed = effective_allowed_features(session, ctx=ctx, current_client=current_client)

    def _is_visible(feature_key: str) -> bool:
        roles = FEATURE_VISIBLE_ROLES.get(feature_key)
        if roles and ctx.membership.role not in roles:
            return False
        return feature_key in allowed

    tabs = []
    for g in FEATURE_GROUPS:
        feats = [fk for fk in g["features"] if _is_visible(fk)]
        if not feats:
            continue
        tabs.append(
            {
                "key": g["key"],
                "title": g["title"],
                "items": [dict(FEATURE_KEYS[fk], key=fk) for fk in feats],
            }
        )

    standalone = [dict(FEATURE_KEYS[fk], key=fk) for fk in FEATURE_STANDALONE if _is_visible(fk)]

    return render(
        "dashboard.html",
        request=request,
        context={
            "current_user": ctx.user,
            "current_company": ctx.company,
            "role": ctx.membership.role,
            "current_client": current_client,
            "tabs": tabs,
            "standalone": standalone,
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

    # Garante tabela de convites em ambientes sem Alembic
    if not ensure_client_invite_table():
        set_flash(request, "Sistema de convites não está configurado (migração pendente no banco).")
        return RedirectResponse("/", status_code=303)

    clients = session.exec(select(Client).where(Client.company_id == ctx.company.id).order_by(Client.created_at)).all()
    active_client_id = get_active_client_id(request, session, ctx)
    current_client = get_client_or_none(session, ctx.company.id, active_client_id)

    invite_link_url = (request.session.get("last_invite_url") or "").strip()

    recent_invites: list[dict[str, Any]] = []
    if current_client:
        invs = session.exec(
            select(ClientInvite)
            .where(
                (ClientInvite.company_id == ctx.company.id)
                & (ClientInvite.client_id == current_client.id)
            )
            .order_by(ClientInvite.created_at.desc())
            .limit(5)
        ).all()
        for inv in invs:
            note = _unpack_invite_link_note(inv.notes)
            tok = (note or {}).get("token") if isinstance(note, dict) else None
            link_url = _build_invite_url(request, token=str(tok)) if tok else ""
            recent_invites.append(
                {
                    "id": inv.id,
                    "created_at": inv.created_at.isoformat(),
                    "expires_at": inv.expires_at.isoformat(),
                    "status": inv.status,
                    "invited_email": inv.invited_email,
                    "link_url": link_url,
                }
            )

    return render(
        "client_switch.html",
        request=request,
        context={
            "current_user": ctx.user,
            "current_company": ctx.company,
            "role": ctx.membership.role,
            "current_client": current_client,
            "clients": clients,
            "invite_link_url": invite_link_url,
            "recent_invites": recent_invites,
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

    # Garante tabela em ambientes sem Alembic
    if not ensure_credit_consent_table():
        set_flash(request, "Sistema de aceite não está configurado (migração pendente no banco).")
        return RedirectResponse("/credito", status_code=303)

    client = get_client_or_none(session, ctx.company.id, int(client_id))
    if not client:
        set_flash(request, "Cliente inválido.")
        return RedirectResponse("/client/switch", status_code=303)

    request.session["selected_client_id"] = client.id
    set_flash(request, f"Cliente selecionado: {client.name}")
    return RedirectResponse("/", status_code=303)


# ----------------------------
# Convites: clientes criarem acesso (sem OTP)
# ----------------------------


def _invite_is_expired(inv: ClientInvite) -> bool:
    try:
        exp_at = _as_aware_utc(inv.expires_at)
        return bool(exp_at and utcnow() > exp_at)
    except Exception:
        return False


def _expire_invite_if_needed(session: Session, inv: ClientInvite) -> None:
    if inv.status == "pendente" and _invite_is_expired(inv):
        inv.status = "expirado"
        inv.updated_at = utcnow()
        session.add(inv)
        session.commit()


@app.post("/client/invite")
@require_role({"admin", "equipe"})
async def client_invite_create(
        request: Request,
        session: Session = Depends(get_session),
        client_id: int = Form(...),
        invited_email: str = Form(""),
) -> Response:
    ctx = get_tenant_context(request, session)
    assert ctx is not None

    if not ensure_client_invite_table():
        set_flash(request, "Sistema de convites não está configurado (migração pendente no banco).")
        return RedirectResponse("/client/switch", status_code=303)

    client = get_client_or_none(session, ctx.company.id, int(client_id))
    if not client:
        set_flash(request, "Cliente inválido.")
        return RedirectResponse("/client/switch", status_code=303)

    expires_at = utcnow() + timedelta(hours=CLIENT_INVITE_TTL_HOURS)
    email = invited_email.strip().lower()

    inv = ClientInvite(
        company_id=ctx.company.id,
        client_id=client.id,
        created_by_user_id=ctx.user.id,
        invited_email=email,
        status="pendente",
        expires_at=expires_at,
        created_at=utcnow(),
        updated_at=utcnow(),
    )
    session.add(inv)
    session.commit()
    session.refresh(inv)

    payload = {
        "invite_id": inv.id,
        "nonce": inv.token_nonce,
        "iat": int(utcnow().timestamp()),
        "exp": int(expires_at.timestamp()),
    }
    token = _sign_invite_token(payload)
    inv.notes = _pack_invite_link_note(token=token, created_by_user_id=ctx.user.id, expires_at=expires_at)
    inv.updated_at = utcnow()
    session.add(inv)
    session.commit()

    url = _build_invite_url(request, token=token)
    request.session["last_invite_url"] = url

    set_flash(request, f"Link de convite: {url}")
    return RedirectResponse("/client/switch", status_code=303)


def _digits_last4(value: str) -> str:
    s = _digits_only(value)
    return s[-4:] if len(s) >= 4 else ""


@app.get("/convite/{token}", response_class=HTMLResponse)
async def invite_signup_page(
        request: Request,
        token: str,
        session: Session = Depends(get_session),
) -> HTMLResponse:
    if not ensure_client_invite_table():
        return render(
            "success.html",
            request=request,
            context={"current_user": None, "message": "Cadastro indisponível (migração pendente no banco)."},
            status_code=503,
        )

    try:
        payload = _verify_invite_token(token)
        invite_id = int(payload.get("invite_id") or 0)
        nonce = str(payload.get("nonce") or "")
    except Exception:
        return render(
            "success.html",
            request=request,
            context={"current_user": None, "message": "Convite inválido ou expirado."},
            status_code=400,
        )

    inv = session.get(ClientInvite, invite_id) if invite_id else None
    if not inv or inv.token_nonce != nonce:
        return render(
            "success.html",
            request=request,
            context={"current_user": None, "message": "Convite inválido."},
            status_code=400,
        )

    _expire_invite_if_needed(session, inv)
    if inv.status != "pendente":
        msg = "Convite já utilizado." if inv.status == "aceito" else "Convite expirado."
        return render("success.html", request=request, context={"current_user": None, "message": msg})

    company = session.get(Company, inv.company_id)
    client = session.get(Client, inv.client_id)
    if not company or not client:
        return render(
            "success.html",
            request=request,
            context={"current_user": None, "message": "Convite inválido (cadastros não encontrados)."},
            status_code=400,
        )

    require_last4 = bool(CLIENT_INVITE_REQUIRE_LAST4 and _digits_last4(client.cnpj))

    consent_terms_html = templates_env.from_string(CREDIT_CONSENT_TERMS_HTML).render(
        term_version=CREDIT_CONSENT_TERM_VERSION)

    return render(
        "invite_signup.html",
        request=request,
        context={
            "current_user": None,
            "company": company,
            "client": client,
            "consent_terms_html": consent_terms_html,
            "consent_term_version": CREDIT_CONSENT_TERM_VERSION,
            "token": token,
            "invited_email": inv.invited_email,
            "require_last4": bool(require_last4),
            "error": "",
            "form": {"name": "", "email": inv.invited_email},
        },
    )


@app.post("/convite/{token}")
async def invite_signup_action(
        request: Request,
        token: str,
        session: Session = Depends(get_session),
        name: str = Form(...),
        email: str = Form(...),
        password: str = Form(...),
        password2: str = Form(...),
        doc_last4: str = Form(""),
        accept: Optional[str] = Form(None),
        scr_accept: Optional[str] = Form(None),
) -> Response:
    if not ensure_client_invite_table():
        return render(
            "success.html",
            request=request,
            context={"current_user": None, "message": "Cadastro indisponível (migração pendente no banco)."},
            status_code=503,
        )

    def render_form(company: Company, client: Client, inv: ClientInvite, msg: str) -> HTMLResponse:
        require_last4 = bool(CLIENT_INVITE_REQUIRE_LAST4 and _digits_last4(client.cnpj))
        consent_terms_html = templates_env.from_string(CREDIT_CONSENT_TERMS_HTML).render(
            term_version=CREDIT_CONSENT_TERM_VERSION)
        return render(
            "invite_signup.html",
            request=request,
            context={
                "current_user": None,
                "company": company,
                "client": client,
                "consent_terms_html": consent_terms_html,
                "consent_term_version": CREDIT_CONSENT_TERM_VERSION,
                "token": token,
                "invited_email": inv.invited_email,
                "require_last4": bool(require_last4),
                "error": msg,
                "form": {"name": name, "email": email},
            },
            status_code=400,
        )

    try:
        payload = _verify_invite_token(token)
        invite_id = int(payload.get("invite_id") or 0)
        nonce = str(payload.get("nonce") or "")
    except Exception:
        return render(
            "success.html",
            request=request,
            context={"current_user": None, "message": "Convite inválido ou expirado."},
            status_code=400,
        )

    inv = session.get(ClientInvite, invite_id) if invite_id else None
    if not inv or inv.token_nonce != nonce:
        return render(
            "success.html",
            request=request,
            context={"current_user": None, "message": "Convite inválido."},
            status_code=400,
        )

    _expire_invite_if_needed(session, inv)
    if inv.status != "pendente":
        msg = "Convite já utilizado." if inv.status == "aceito" else "Convite expirado."
        return render("success.html", request=request, context={"current_user": None, "message": msg})

    company = session.get(Company, inv.company_id)
    client = session.get(Client, inv.client_id)
    if not company or not client:
        return render(
            "success.html",
            request=request,
            context={"current_user": None, "message": "Convite inválido (cadastros não encontrados)."},
            status_code=400,
        )

    if not accept:
        return render_form(company, client, inv, "Você precisa aceitar os termos para continuar.")

    if not scr_accept:
        return render_form(company, client, inv,
                           "Você precisa autorizar a consulta ao SCR (Bacen) para concluir o cadastro.")

    if password != password2:
        return render_form(company, client, inv, "As senhas não conferem.")

    if len(password) < 8:
        return render_form(company, client, inv, "Senha muito curta (mínimo 8).")

    if inv.invited_email and email.strip().lower() != inv.invited_email.strip().lower():
        return render_form(company, client, inv, "Este convite é válido apenas para o e-mail convidado.")

    require_last4 = bool(CLIENT_INVITE_REQUIRE_LAST4 and _digits_last4(client.cnpj))
    if require_last4:
        expected = _digits_last4(client.cnpj)
        provided = _digits_only(doc_last4)[-4:]
        if not provided or provided != expected:
            return render_form(company, client, inv, "Últimos 4 dígitos do documento não conferem.")

    em = email.strip().lower()
    nm = name.strip()
    if not nm or not em:
        return render_form(company, client, inv, "Nome e e-mail são obrigatórios.")

    user = session.exec(select(User).where(User.email == em)).first()
    if user:
        if not verify_password(password, user.password_hash):
            return render_form(company, client, inv,
                               "E-mail já cadastrado. Informe a senha correta para associar este convite.")
    else:
        user = User(name=nm, email=em, password_hash=hash_password(password))
        session.add(user)
        try:
            session.commit()
        except IntegrityError:
            session.rollback()
            return render_form(company, client, inv, "Este e-mail já está cadastrado.")
        session.refresh(user)

    membership = get_membership(session, user.id, company.id)
    if membership:
        membership.role = "cliente"
        membership.client_id = client.id
    else:
        membership = Membership(user_id=user.id, company_id=company.id, role="cliente", client_id=client.id)
        session.add(membership)

    inv.status = "aceito"
    inv.accepted_user_id = user.id

    # Registra a autorização SCR/Bacen junto do cadastro (clickwrap, sem OTP)
    if not ensure_credit_consent_table():
        session.rollback()
        return render_form(company, client, inv, "Sistema de aceite indisponível (migração pendente no banco).")

    now = utcnow()
    expires_at_consent = now + timedelta(days=int(CREDIT_CONSENT_MAX_DAYS))

    evidence = {
        "method": "invite-clickwrap",
        "term_version": CREDIT_CONSENT_TERM_VERSION,
        "term_sha256": _terms_sha256(),
        "ip": _request_ip(request),
        "user_agent": request.headers.get("user-agent") or "",
        "accepted_at_utc": now.isoformat(),
        "invite_id": int(inv.id or 0),
        "accepted_user_id": int(user.id or 0),
        "invited_email": (inv.invited_email or "").strip().lower(),
    }

    latest = _get_latest_consent(session, company_id=company.id, client_id=client.id)
    if latest:
        _refresh_consent_status(latest)
        if latest.status != "valida":
            latest.kind = CREDIT_CONSENT_KIND_SCR
            latest.status = "valida"
            latest.signed_by_name = nm
            latest.signed_by_document = _digits_only(client.cnpj or "")
            latest.signed_at = now
            latest.expires_at = expires_at_consent
            latest.updated_at = now
            latest.notes = "[aceite-eletronico]\n" + json.dumps(evidence, ensure_ascii=False)
            session.add(latest)
    else:
        consent = CreditConsent(
            company_id=company.id,
            client_id=client.id,
            created_by_user_id=int(inv.created_by_user_id or user.id or 0),
            kind=CREDIT_CONSENT_KIND_SCR,
            status="valida",
            signed_by_name=nm,
            signed_by_document=_digits_only(client.cnpj or ""),
            signed_at=now,
            expires_at=expires_at_consent,
            notes="[aceite-eletronico]\n" + json.dumps(evidence, ensure_ascii=False),
            created_at=now,
            updated_at=now,
        )
        session.add(consent)

    inv.accepted_at = now
    inv.updated_at = now
    session.add(inv)

    try:
        session.commit()
    except Exception:
        session.rollback()
        return render_form(company, client, inv, "Erro ao concluir cadastro. Tente novamente.")

    request.session["user_id"] = user.id
    request.session["company_id"] = company.id
    request.session["selected_client_id"] = client.id
    set_flash(request, "Cadastro concluído. Bem-vindo(a)!")
    return RedirectResponse("/", status_code=303)


# ----------------------------
# Admin: Members
# ----------------------------


@app.get("/admin/members", response_class=HTMLResponse)
@require_role({"admin", "equipe"})
async def members_page(request: Request, session: Session = Depends(get_session)) -> HTMLResponse:
    ctx = get_tenant_context(request, session)
    assert ctx is not None

    # Garante tabela em ambientes sem Alembic
    if not ensure_credit_consent_table():
        set_flash(request, "Sistema de aceite não está configurado (migração pendente no banco).")
        return RedirectResponse("/credito", status_code=303)

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


    clients = session.exec(select(Client).where(Client.company_id == ctx.company.id).order_by(Client.created_at)).all()

    for row in rows:
        m = row["membership"]
        row["is_active"] = entity_is_allowed(session, entity_type="membership", entity_id=m.id) if m.id else True
        row["allowed_features"] = sorted(get_membership_allowed_features(session, company_id=ctx.company.id, membership=m))

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
            "clients": clients,
            "feature_groups": FEATURE_GROUPS,
            "feature_standalone": FEATURE_STANDALONE,
            "feature_keys": FEATURE_KEYS,

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
        client_id: str = Form(""),
        client_name: str = Form(""),
) -> Response:
    ctx = get_tenant_context(request, session)
    assert ctx is not None

    # Garante tabela em ambientes sem Alembic
    if not ensure_credit_consent_table():
        set_flash(request, "Sistema de aceite não está configurado (migração pendente no banco).")
        return RedirectResponse("/credito", status_code=303)

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
        cid = _safe_int(client_id)
        if cid:
            c = session.get(Client, cid)
            if not c or c.company_id != ctx.company.id:
                set_flash(request, "Cliente inválido.")
                return RedirectResponse("/admin/members", status_code=303)
            membership.client_id = c.id
            request.session["selected_client_id"] = c.id
        else:
            cn = client_name.strip()
            if cn:
                existing = session.exec(
                    select(Client).where(Client.company_id == ctx.company.id, func.lower(Client.name) == cn.lower())
                ).first()
                if existing:
                    membership.client_id = existing.id
                    request.session["selected_client_id"] = existing.id
                else:
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


@app.post("/admin/members/{membership_id}/features")
@require_role({"admin", "equipe"})
async def member_features_update(
    request: Request,
    membership_id: int,
    session: Session = Depends(get_session),
) -> Response:
    ctx = get_tenant_context(request, session)
    assert ctx is not None

    m = session.get(Membership, membership_id)
    if not m or m.company_id != ctx.company.id:
        set_flash(request, "Membro não encontrado.")
        return RedirectResponse("/admin/members", status_code=303)

    form = await request.form()
    features = [str(x) for x in form.getlist("features") if str(x) in FEATURE_KEYS]

    row = session.exec(
        select(MembershipFeatureAccess).where(
            MembershipFeatureAccess.company_id == ctx.company.id,
            MembershipFeatureAccess.membership_id == membership_id,
        )
    ).first()
    if not row:
        row = MembershipFeatureAccess(company_id=ctx.company.id, membership_id=membership_id)

    row.features_json = json.dumps(sorted(set(features)))
    row.updated_at = utcnow()
    session.add(row)
    session.commit()

    set_flash(request, "Permissões atualizadas.")
    return RedirectResponse("/admin/members", status_code=303)


@app.post("/admin/members/{membership_id}/link-client")
@require_role({"admin", "equipe"})
async def member_link_client(
    request: Request,
    membership_id: int,
    session: Session = Depends(get_session),
    client_id: str = Form(""),
) -> Response:
    ctx = get_tenant_context(request, session)
    assert ctx is not None

    m = session.get(Membership, membership_id)
    if not m or m.company_id != ctx.company.id:
        set_flash(request, "Membro não encontrado.")
        return RedirectResponse("/admin/members", status_code=303)

    if m.role != "cliente":
        set_flash(request, "Apenas membros role=cliente podem ser vinculados a um cliente.")
        return RedirectResponse("/admin/members", status_code=303)

    cid = _safe_int(client_id)
    if cid:
        c = session.get(Client, cid)
        if not c or c.company_id != ctx.company.id:
            set_flash(request, "Cliente inválido.")
            return RedirectResponse("/admin/members", status_code=303)
        m.client_id = c.id
        request.session["selected_client_id"] = c.id
    else:
        m.client_id = None

    session.add(m)
    session.commit()
    set_flash(request, "Vínculo atualizado.")
    return RedirectResponse("/admin/members", status_code=303)


@app.get("/admin/clients/{client_id}/access", response_class=HTMLResponse)
@require_role({"admin", "equipe"})
async def client_access_page(
    request: Request,
    client_id: int,
    session: Session = Depends(get_session),
) -> HTMLResponse:
    ctx = get_tenant_context(request, session)
    assert ctx is not None

    c = session.get(Client, client_id)
    if not c or c.company_id != ctx.company.id:
        return render(
            "error.html",
            request=request,
            context={
                "current_user": ctx.user,
                "current_company": ctx.company,
                "role": ctx.membership.role,
                "current_client": None,
                "message": "Cliente não encontrado.",
            },
            status_code=404,
        )

    row = session.exec(
        select(ClientFeatureAccess).where(
            ClientFeatureAccess.company_id == ctx.company.id,
            ClientFeatureAccess.client_id == client_id,
        )
    ).first()
    allowed = set(_parse_json_list(row.features_json)) if row else ROLE_DEFAULT_FEATURES["cliente"]

    mems = session.exec(
        select(Membership).where(Membership.company_id == ctx.company.id, Membership.client_id == client_id)
    ).all()
    users = []
    for m in mems:
        u = session.get(User, m.user_id)
        if u:
            users.append({"user": u, "membership": m})

    return render(
        "client_access.html",
        request=request,
        context={
            "current_user": ctx.user,
            "current_company": ctx.company,
            "role": ctx.membership.role,
            "current_client": c,
            "client": c,
            "allowed": sorted(allowed),
            "feature_groups": FEATURE_GROUPS,
            "feature_standalone": FEATURE_STANDALONE,
            "feature_keys": FEATURE_KEYS,
            "linked_users": users,
        },
    )


@app.post("/admin/clients/{client_id}/access")
@require_role({"admin", "equipe"})
async def client_access_save(
    request: Request,
    client_id: int,
    session: Session = Depends(get_session),
) -> Response:
    ctx = get_tenant_context(request, session)
    assert ctx is not None

    c = session.get(Client, client_id)
    if not c or c.company_id != ctx.company.id:
        set_flash(request, "Cliente não encontrado.")
        return RedirectResponse("/admin/gestao", status_code=303)

    form = await request.form()
    features = [str(x) for x in form.getlist("features") if str(x) in FEATURE_KEYS]

    row = session.exec(
        select(ClientFeatureAccess).where(
            ClientFeatureAccess.company_id == ctx.company.id,
            ClientFeatureAccess.client_id == client_id,
        )
    ).first()
    if not row:
        row = ClientFeatureAccess(company_id=ctx.company.id, client_id=client_id)

    row.features_json = json.dumps(sorted(set(features)))
    row.updated_at = utcnow()
    session.add(row)
    session.commit()

    set_flash(request, "Permissões do cliente atualizadas.")
    return RedirectResponse(f"/admin/clients/{client_id}/access", status_code=303)

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

    snapshots: list[ClientSnapshot] = []
    latest_score: Optional[float] = None
    delta: Optional[float] = None

    if current_client and ensure_can_access_client(ctx, current_client.id):
        snaps = session.exec(
            select(ClientSnapshot)
            .where(ClientSnapshot.company_id == ctx.company.id, ClientSnapshot.client_id == current_client.id)
            .order_by(ClientSnapshot.created_at.desc())
            .limit(12)
        ).all()
        snapshots = list(snaps)
        if snapshots:
            latest_score = float(snapshots[0].score_total)
        if len(snapshots) >= 2:
            delta = round(float(snapshots[0].score_total) - float(snapshots[1].score_total), 2)

    return render(
        "perfil.html",
        request=request,
        context={
            "current_user": ctx.user,
            "current_company": ctx.company,
            "role": ctx.membership.role,
            "current_client": current_client,
            "snapshots": snapshots,
            "latest_score": latest_score,
            "delta": delta,
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
# Perfil: Avaliação / Snapshot
# ----------------------------

@app.get("/perfil/avaliacao/nova", response_class=HTMLResponse)
@require_login
async def perfil_snapshot_new_page(request: Request, session: Session = Depends(get_session)) -> HTMLResponse:
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

    return render(
        "perfil_snapshot_new.html",
        request=request,
        context={
            "current_user": ctx.user,
            "current_company": ctx.company,
            "role": ctx.membership.role,
            "current_client": current_client,
            "survey": PROFILE_SURVEY_V1,
        },
    )


@app.post("/perfil/avaliacao/nova")
@require_login
async def perfil_snapshot_new_action(
        request: Request,
        session: Session = Depends(get_session),
        revenue_monthly_brl: float = Form(0.0),
        debt_total_brl: float = Form(0.0),
        cash_balance_brl: float = Form(0.0),
        employees_count: int = Form(0),
        nps_score: int = Form(0),
        notes: str = Form(""),
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

    form = await request.form()
    answers: dict[str, Any] = {}
    for q in PROFILE_SURVEY_V1:
        key = q["id"]
        answers[key] = _parse_bool(form.get(key))

    proc = score_process_from_answers(answers)
    fin = score_financial_simple(revenue_monthly_brl, debt_total_brl, cash_balance_brl)
    tot = score_total(proc, fin, nps_score)

    snap = ClientSnapshot(
        company_id=ctx.company.id,
        client_id=current_client.id,
        created_by_user_id=ctx.user.id,
        revenue_monthly_brl=max(0.0, float(revenue_monthly_brl)),
        debt_total_brl=max(0.0, float(debt_total_brl)),
        cash_balance_brl=max(0.0, float(cash_balance_brl)),
        employees_count=max(0, int(employees_count)),
        nps_score=max(0, min(10, int(nps_score))),
        notes=(notes or "").strip(),
        answers_json=json.dumps(answers, ensure_ascii=False),
        score_process=proc,
        score_financial=fin,
        score_total=tot,
    )
    session.add(snap)

    # Atualiza os indicadores atuais do cliente (mantém a tela antiga consistente)
    current_client.revenue_monthly_brl = snap.revenue_monthly_brl
    current_client.debt_total_brl = snap.debt_total_brl
    current_client.cash_balance_brl = snap.cash_balance_brl
    current_client.employees_count = snap.employees_count
    current_client.updated_at = utcnow()
    session.add(current_client)

    session.commit()
    set_flash(request, "Avaliação registrada.")
    return RedirectResponse("/perfil", status_code=303)


@app.get("/perfil/avaliacao/{snapshot_id}", response_class=HTMLResponse)
@require_login
async def perfil_snapshot_detail(request: Request, session: Session = Depends(get_session),
                                 snapshot_id: int = 0) -> HTMLResponse:
    ctx = get_tenant_context(request, session)
    if not ctx:
        request.session.clear()
        return RedirectResponse("/login", status_code=303)

    snap = session.get(ClientSnapshot, int(snapshot_id))
    if not snap or snap.company_id != ctx.company.id:
        return render(
            "error.html",
            request=request,
            context={"current_user": ctx.user, "current_company": ctx.company, "role": ctx.membership.role,
                     "current_client": None, "message": "Avaliação não encontrada."},
            status_code=404,
        )

    if not ensure_can_access_client(ctx, snap.client_id):
        return render(
            "error.html",
            request=request,
            context={"current_user": ctx.user, "current_company": ctx.company, "role": ctx.membership.role,
                     "current_client": None, "message": "Sem permissão."},
            status_code=403,
        )

    client = session.get(Client, snap.client_id)
    answers = {}
    try:
        answers = json.loads(snap.answers_json or "{}")
    except Exception:
        answers = {}

    current_client = get_client_or_none(session, ctx.company.id, get_active_client_id(request, session, ctx))

    return render(
        "perfil_snapshot_detail.html",
        request=request,
        context={
            "current_user": ctx.user,
            "current_company": ctx.company,
            "role": ctx.membership.role,
            "current_client": current_client,
            "client": client,
            "snap": snap,
            "survey": PROFILE_SURVEY_V1,
            "answers": answers,
        },
    )


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


@app.get("/pendencias/cliente/novo", response_class=HTMLResponse)
@require_role({"admin", "equipe"})
async def pending_new_page(request: Request, session: Session = Depends(get_session)) -> HTMLResponse:
    ctx = get_tenant_context(request, session)
    assert ctx is not None

    # Garante tabela em ambientes sem Alembic
    if not ensure_credit_consent_table():
        set_flash(request, "Sistema de aceite não está configurado (migração pendente no banco).")
        return RedirectResponse("/credito", status_code=303)

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


@app.post("/pendencias/cliente/novo")
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

    # Garante tabela em ambientes sem Alembic
    if not ensure_credit_consent_table():
        set_flash(request, "Sistema de aceite não está configurado (migração pendente no banco).")
        return RedirectResponse("/credito", status_code=303)

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
        select(PendingMessage).where(PendingMessage.pending_item_id == item.id).order_by(
            PendingMessage.created_at.desc())
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

    # Garante tabela em ambientes sem Alembic
    if not ensure_credit_consent_table():
        set_flash(request, "Sistema de aceite não está configurado (migração pendente no banco).")
        return RedirectResponse("/credito", status_code=303)

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

    # Garante tabela em ambientes sem Alembic
    if not ensure_credit_consent_table():
        set_flash(request, "Sistema de aceite não está configurado (migração pendente no banco).")
        return RedirectResponse("/credito", status_code=303)

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

    # Garante tabela em ambientes sem Alembic
    if not ensure_credit_consent_table():
        set_flash(request, "Sistema de aceite não está configurado (migração pendente no banco).")
        return RedirectResponse("/credito", status_code=303)

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
            {"id": d.id, "title": d.title, "status": d.status, "created_at": d.created_at,
             "client_name": c.name if c else "—"}
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

    # Garante tabela em ambientes sem Alembic
    if not ensure_credit_consent_table():
        set_flash(request, "Sistema de aceite não está configurado (migração pendente no banco).")
        return RedirectResponse("/credito", status_code=303)

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

    # Garante tabela em ambientes sem Alembic
    if not ensure_credit_consent_table():
        set_flash(request, "Sistema de aceite não está configurado (migração pendente no banco).")
        return RedirectResponse("/credito", status_code=303)

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

    # Garante tabela em ambientes sem Alembic
    if not ensure_credit_consent_table():
        set_flash(request, "Sistema de aceite não está configurado (migração pendente no banco).")
        return RedirectResponse("/credito", status_code=303)

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

    # Garante tabela em ambientes sem Alembic
    if not ensure_credit_consent_table():
        set_flash(request, "Sistema de aceite não está configurado (migração pendente no banco).")
        return RedirectResponse("/credito", status_code=303)

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

    # Garante tabela em ambientes sem Alembic
    if not ensure_credit_consent_table():
        set_flash(request, "Sistema de aceite não está configurado (migração pendente no banco).")
        return RedirectResponse("/credito", status_code=303)

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

    # Garante tabela em ambientes sem Alembic
    if not ensure_credit_consent_table():
        set_flash(request, "Sistema de aceite não está configurado (migração pendente no banco).")
        return RedirectResponse("/credito", status_code=303)

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
        service_name: str = Form(""),
        value_brl: float = Form(0.0),
        status: str = Form("rascunho"),
        file: UploadFile | None = File(default=None),
) -> Response:
    ctx = get_tenant_context(request, session)
    assert ctx is not None

    # Garante tabela em ambientes sem Alembic
    if not ensure_credit_consent_table():
        set_flash(request, "Sistema de aceite não está configurado (migração pendente no banco).")
        return RedirectResponse("/credito", status_code=303)

    client = get_client_or_none(session, ctx.company.id, int(client_id))
    if not client:
        set_flash(request, "Cliente inválido.")
        return RedirectResponse("/propostas/nova", status_code=303)

    status = status.strip().lower()
    if status not in _proposal_allowed_statuses("proposta"):
        status = "rascunho"

    service_name = sanitize_service_name(service_name)
    if not service_name:
        set_flash(request, "Selecione um serviço/produto.")
        return RedirectResponse("/propostas/nova", status_code=303)

    prop = Proposal(
        company_id=ctx.company.id,
        client_id=client.id,
        created_by_user_id=ctx.user.id,
        kind="proposta",
        title=title.strip(),
        description=description.strip(),
        service_name=service_name,
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

    # Garante tabela em ambientes sem Alembic
    if not ensure_credit_consent_table():
        set_flash(request, "Sistema de aceite não está configurado (migração pendente no banco).")
        return RedirectResponse("/credito", status_code=303)

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
        service_name: str = Form(""),
        description: str = Form(...),
        file: UploadFile | None = File(default=None),
) -> Response:
    ctx = get_tenant_context(request, session)
    assert ctx is not None

    # Garante tabela em ambientes sem Alembic
    if not ensure_credit_consent_table():
        set_flash(request, "Sistema de aceite não está configurado (migração pendente no banco).")
        return RedirectResponse("/credito", status_code=303)

    client_id = ctx.membership.client_id
    if not client_id:
        set_flash(request, "Seu usuário não está vinculado a um cliente.")
        return RedirectResponse("/propostas", status_code=303)

    service_name = sanitize_service_name(service_name)
    if not service_name:
        set_flash(request, "Selecione um serviço/produto.")
        return RedirectResponse("/propostas/solicitacao", status_code=303)

    prop = Proposal(
        company_id=ctx.company.id,
        client_id=client_id,
        created_by_user_id=ctx.user.id,
        kind="solicitacao",
        title=title.strip(),
        description=description.strip(),
        service_name=service_name,
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
        select(ProposalMessage).where(ProposalMessage.proposal_id == prop.id).order_by(
            ProposalMessage.created_at.desc())
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
        service_name: str = Form(""),
        value_brl: float = Form(0.0),
        message: str = Form(""),
) -> Response:
    ctx = get_tenant_context(request, session)
    assert ctx is not None

    # Garante tabela em ambientes sem Alembic
    if not ensure_credit_consent_table():
        set_flash(request, "Sistema de aceite não está configurado (migração pendente no banco).")
        return RedirectResponse("/credito", status_code=303)

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
    prop.service_name = sanitize_service_name(service_name)
    prop.value_brl = max(0.0, float(value_brl))
    prop.updated_at = utcnow()
    session.add(prop)

    if message.strip():
        session.add(ProposalMessage(proposal_id=prop.id, author_user_id=ctx.user.id, message=message.strip()))

    session.commit()
    set_flash(request, "Atualizado.")
    return RedirectResponse(f"/propostas/{prop.id}", status_code=303)


@app.post("/propostas/{prop_id}/excluir")
@require_role({"admin", "equipe"})
async def props_delete_staff(request: Request, session: Session = Depends(get_session), prop_id: int = 0) -> Response:
    ctx = get_tenant_context(request, session)
    assert ctx is not None

    # Garante tabela em ambientes sem Alembic
    if not ensure_credit_consent_table():
        set_flash(request, "Sistema de aceite não está configurado (migração pendente no banco).")
        return RedirectResponse("/credito", status_code=303)

    prop = session.get(Proposal, int(prop_id))
    if not prop or prop.company_id != ctx.company.id:
        set_flash(request, "Proposta não encontrada.")
        return RedirectResponse("/propostas", status_code=303)

    atts = session.exec(select(Attachment).where(Attachment.proposal_id == prop.id)).all()
    if atts:
        set_flash(request, "Remova os anexos antes de excluir a proposta.")
        return RedirectResponse(f"/propostas/{prop.id}", status_code=303)

    msgs = session.exec(select(ProposalMessage).where(ProposalMessage.proposal_id == prop.id)).all()
    for m in msgs:
        session.delete(m)

    session.delete(prop)
    session.commit()
    set_flash(request, "Proposta excluída.")
    return RedirectResponse("/propostas", status_code=303)


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

    # Garante tabela em ambientes sem Alembic
    if not ensure_credit_consent_table():
        set_flash(request, "Sistema de aceite não está configurado (migração pendente no banco).")
        return RedirectResponse("/credito", status_code=303)

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

    # Garante tabela em ambientes sem Alembic
    if not ensure_credit_consent_table():
        set_flash(request, "Sistema de aceite não está configurado (migração pendente no banco).")
        return RedirectResponse("/credito", status_code=303)

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
# Integrações: Conta Azul
# ----------------------------

@app.get("/integrations/contaazul", response_class=HTMLResponse)
@require_role({"admin", "equipe"})
async def contaazul_settings(request: Request, session: Session = Depends(get_session)) -> HTMLResponse:
    ctx = get_tenant_context(request, session)
    assert ctx is not None

    configured = _contaazul_configured()
    connected = False
    last_sync = None
    if ensure_contaazul_tables():
        auth = _contaazul_get_auth(session, ctx.company.id)
        connected = bool(auth and auth.refresh_token)
        last_sync = auth.last_sync_at if auth else None

    return render(
        "contaazul_settings.html",
        request=request,
        context={
            "current_user": ctx.user,
            "current_company": ctx.company,
            "role": ctx.membership.role,
            "current_client": get_client_or_none(session, ctx.company.id, get_active_client_id(request, session, ctx)),
            "configured": configured,
            "connected": connected,
            "last_sync": last_sync,
            "redirect_uri": _contaazul_redirect_uri(request),
        },
    )


@app.get("/integrations/contaazul/diag")
@require_role({"admin", "equipe"})
async def contaazul_diag(request: Request, session: Session = Depends(get_session)) -> JSONResponse:
    """Diagnóstico rápido da integração Conta Azul (sem tocar em dados financeiros)."""
    ctx = get_tenant_context(request, session)
    assert ctx is not None

    table_ok = bool(ensure_contaazul_tables())
    configured = bool(_contaazul_configured())
    redirect_uri = _contaazul_redirect_uri(request)

    auth = _contaazul_get_auth(session, ctx.company.id) if table_ok else None

    # Ping simples (opcional) para verificar reachability do auth server
    ping = {"ok": False, "status": None}
    try:
        async with httpx.AsyncClient(timeout=min(6.0, CONTA_AZUL_HTTP_TIMEOUT_S), follow_redirects=True) as client:
            r = await client.get(CONTA_AZUL_AUTH_URL)
        ping = {"ok": r.status_code < 500, "status": int(r.status_code)}
    except Exception as e:
        ping = {"ok": False, "status": None, "error": str(e)}

    return JSONResponse(
        {
            "configured": configured,
            "client_id_set": bool(CONTA_AZUL_CLIENT_ID),
            "client_secret_set": bool(CONTA_AZUL_CLIENT_SECRET),
            "redirect_uri": redirect_uri,
            "auth_url": CONTA_AZUL_AUTH_URL,
            "token_url": CONTA_AZUL_TOKEN_URL,
            "api_base": CONTA_AZUL_API_BASE,
            "tables_ok": table_ok,
            "connected": bool(auth and auth.refresh_token),
            "token_expires_at": ((_as_aware_utc(auth.expires_at).isoformat()) if auth and auth.expires_at else None),
            "ping_auth": ping,
        }
    )


@app.get("/integrations/contaazul/connect")
@require_role({"admin", "equipe"})
async def contaazul_connect(request: Request, session: Session = Depends(get_session)) -> Response:
    ctx = get_tenant_context(request, session)
    assert ctx is not None

    if not ensure_contaazul_tables():
        set_flash(request, "Banco sem migração para Conta Azul (crie as tabelas no Postgres).")
        return RedirectResponse("/integrations/contaazul", status_code=303)

    if not _contaazul_configured():
        set_flash(request, "Configure CONTA_AZUL_CLIENT_ID e CONTA_AZUL_CLIENT_SECRET no Render.")
        return RedirectResponse("/integrations/contaazul", status_code=303)

    state = secrets.token_urlsafe(16)
    request.session["contaazul_oauth_state"] = state

    redirect_uri = _contaazul_redirect_uri(request)
    params = {
        "response_type": "code",
        "client_id": CONTA_AZUL_CLIENT_ID,
        "redirect_uri": redirect_uri,
        "state": state,
        "scope": CONTA_AZUL_SCOPE,
    }
    url = httpx.URL(CONTA_AZUL_AUTH_URL).copy_merge_params(params)
    _ca_log(f"redirecting to auth url redirect_uri={redirect_uri} scope={CONTA_AZUL_SCOPE}")
    return RedirectResponse(str(url), status_code=302)


@app.get("/integrations/contaazul/callback")
@require_role({"admin", "equipe"})
async def contaazul_callback(request: Request, session: Session = Depends(get_session)) -> Response:
    ctx = get_tenant_context(request, session)
    assert ctx is not None

    code = (request.query_params.get("code") or "").strip()
    state = (request.query_params.get("state") or "").strip()
    expected = (request.session.get("contaazul_oauth_state") or "").strip()
    request.session.pop("contaazul_oauth_state", None)

    if not code or not expected or state != expected:
        set_flash(request, "Callback inválido (state/code).")
        return RedirectResponse("/integrations/contaazul", status_code=303)

    redirect_uri = _contaazul_redirect_uri(request)
    headers = {"Authorization": f"Basic {_contaazul_basic_auth_value()}",
               "Content-Type": "application/x-www-form-urlencoded"}
    data = {"code": code, "grant_type": "authorization_code", "redirect_uri": redirect_uri}

    try:
        async with httpx.AsyncClient(timeout=CONTA_AZUL_HTTP_TIMEOUT_S, follow_redirects=True) as client:
            resp = await client.post(CONTA_AZUL_TOKEN_URL, headers=headers, data=data)
        if resp.status_code >= 400:
            _ca_log(f"token exchange failed status={resp.status_code} body={_ca_trunc(resp.text)}")
            set_flash(request, f"Falha ao conectar Conta Azul (HTTP {resp.status_code}): {_ca_trunc(resp.text, 180)}")
            return RedirectResponse("/integrations/contaazul", status_code=303)
        payload = resp.json()
    except Exception as e:
        _ca_log(f"token exchange exception: {e}")
        set_flash(request, f"Falha ao conectar Conta Azul: {e}")
        return RedirectResponse("/integrations/contaazul", status_code=303)

    auth = _contaazul_get_auth(session, ctx.company.id) or ContaAzulAuth(company_id=ctx.company.id)
    auth.access_token = str(payload.get("access_token") or "")
    auth.refresh_token = str(payload.get("refresh_token") or "")
    auth.token_type = str(payload.get("token_type") or "Bearer")
    exp = int(payload.get("expires_in") or 3600)
    auth.expires_at = utcnow() + timedelta(seconds=max(60, exp))
    auth.updated_at = utcnow()
    session.add(auth)
    session.commit()

    set_flash(request, "Conta Azul conectada.")
    return RedirectResponse("/integrations/contaazul", status_code=303)


@app.post("/integrations/contaazul/disconnect")
@require_role({"admin", "equipe"})
async def contaazul_disconnect(request: Request, session: Session = Depends(get_session)) -> Response:
    ctx = get_tenant_context(request, session)
    assert ctx is not None
    auth = _contaazul_get_auth(session, ctx.company.id)
    if auth:
        session.delete(auth)
        session.commit()
    set_flash(request, "Conta Azul desconectada.")
    return RedirectResponse("/integrations/contaazul", status_code=303)


@app.post("/financeiro/contaazul/sync")
@require_role({"admin", "equipe"})
async def contaazul_sync_now(request: Request, background_tasks: BackgroundTasks,
                             session: Session = Depends(get_session)) -> Response:
    ctx = get_tenant_context(request, session)
    assert ctx is not None

    if not ensure_contaazul_tables():
        set_flash(request, "Banco sem migração para Conta Azul (crie as tabelas no Postgres).")
        return RedirectResponse("/financeiro", status_code=303)

    if not _contaazul_configured():
        set_flash(request, "Configure CONTA_AZUL_CLIENT_ID e CONTA_AZUL_CLIENT_SECRET no Render.")
        return RedirectResponse("/financeiro", status_code=303)

    auth = _contaazul_get_auth(session, ctx.company.id)
    if not auth or not auth.refresh_token:
        set_flash(request, "Conecte a Conta Azul antes de sincronizar.")
        return RedirectResponse("/integrations/contaazul", status_code=303)

    current_client = get_client_or_none(session, ctx.company.id, get_active_client_id(request, session, ctx))
    if not current_client:
        set_flash(request, "Selecione um cliente antes de sincronizar.")
        return RedirectResponse("/financeiro", status_code=303)

    # Pré-checagem: se não houver doc/e-mail e não houver vínculo salvo, o sync sempre retornará vazio.
    pid_saved = _contaazul_get_mapped_person_id(session, company_id=ctx.company.id, client_id=current_client.id)
    doc = _digits_only(current_client.cnpj)
    email = (current_client.finance_email or current_client.email or "").strip()
    if not pid_saved and not doc and not email:
        set_flash(request,
                  "Este cliente não tem CNPJ/CPF nem e-mail no cadastro. Preencha isso ou cole o UUID (person_id) manualmente antes de sincronizar.")
        return RedirectResponse("/financeiro", status_code=303)

    background_tasks.add_task(contaazul_sync_client_job, ctx.company.id, current_client.id)
    set_flash(request, "Sincronização Conta Azul iniciada. Recarregue em instantes.")

    return RedirectResponse("/financeiro", status_code=303)


@app.post("/financeiro/contaazul/auto_vincular")
@require_role({"admin", "equipe"})
async def contaazul_auto_vincular(request: Request, session: Session = Depends(get_session)) -> Response:
    ctx = get_tenant_context(request, session)
    assert ctx is not None

    if not ensure_contaazul_tables():
        set_flash(request, "Banco sem migração para Conta Azul (crie as tabelas no Postgres).")
        return RedirectResponse("/financeiro", status_code=303)

    if not _contaazul_configured():
        set_flash(request, "Configure CONTA_AZUL_CLIENT_ID e CONTA_AZUL_CLIENT_SECRET no Render.")
        return RedirectResponse("/financeiro", status_code=303)

    auth = _contaazul_get_auth(session, ctx.company.id)
    if not auth or not auth.refresh_token:
        set_flash(request, "Conecte a Conta Azul antes de vincular.")
        return RedirectResponse("/integrations/contaazul", status_code=303)

    current_client = get_client_or_none(session, ctx.company.id, get_active_client_id(request, session, ctx))
    if not current_client:
        set_flash(request, "Selecione um cliente antes de vincular.")
        return RedirectResponse("/financeiro", status_code=303)

    person_id = _contaazul_find_person_id(session, company_id=ctx.company.id, client=current_client)
    if not person_id:
        set_flash(request, "Não encontrei este cliente na Conta Azul por CNPJ/CPF ou e-mail. Cole o UUID manualmente.")
        return RedirectResponse("/financeiro", status_code=303)

    _contaazul_upsert_person_map(session, company_id=ctx.company.id, client=current_client, person_id=person_id)
    set_flash(request, f"Vínculo atualizado. person_id={person_id}")
    return RedirectResponse("/financeiro", status_code=303)


@app.post("/financeiro/contaazul/vincular")
@require_role({"admin", "equipe"})
async def contaazul_vincular_manual(
        request: Request,
        session: Session = Depends(get_session),
        person_id: str = Form(""),
) -> Response:
    ctx = get_tenant_context(request, session)
    assert ctx is not None

    pid = (person_id or "").strip()
    if not pid or not re.fullmatch(r"[0-9a-fA-F-]{32,36}", pid):
        set_flash(request, "UUID inválido. Cole o ID (UUID) do cliente (Pessoa) no Conta Azul.")
        return RedirectResponse("/financeiro", status_code=303)

    if not ensure_contaazul_tables():
        set_flash(request, "Banco sem migração para Conta Azul (crie as tabelas no Postgres).")
        return RedirectResponse("/financeiro", status_code=303)

    current_client = get_client_or_none(session, ctx.company.id, get_active_client_id(request, session, ctx))
    if not current_client:
        set_flash(request, "Selecione um cliente antes de vincular.")
        return RedirectResponse("/financeiro", status_code=303)

    _contaazul_upsert_person_map(session, company_id=ctx.company.id, client=current_client, person_id=pid)
    set_flash(request, f"Vínculo salvo. person_id={pid}")
    return RedirectResponse("/financeiro", status_code=303)


# ----------------------------
# Financeiro (Notas/Boletos)
# ----------------------------


@app.get("/financeiro/contaazul/test", response_class=JSONResponse)
@require_role({"admin", "equipe"})
async def contaazul_test_mapping(request: Request, session: Session = Depends(get_session)) -> JSONResponse:
    """Diagnóstico rápido do mapeamento e filtros do Conta Azul para o cliente selecionado.

    Este endpoint nunca deve "estourar" 500 sem corpo; ele retorna JSON com o erro.
    """
    try:
        ctx = get_tenant_context(request, session)
        if not ctx:
            return JSONResponse({"ok": False, "error": "no_context"}, status_code=401)

        if not ensure_contaazul_tables():
            return JSONResponse({"ok": False, "error": "contaazul_tables_missing"}, status_code=500)

        if not _contaazul_configured():
            return JSONResponse({"ok": False, "error": "contaazul_not_configured"}, status_code=400)

        auth = _contaazul_get_auth(session, ctx.company.id)
        if not auth or not auth.refresh_token:
            return JSONResponse({"ok": False, "error": "contaazul_not_connected"}, status_code=400)

        current_client = get_client_or_none(session, ctx.company.id, get_active_client_id(request, session, ctx))
        if not current_client:
            return JSONResponse({"ok": False, "error": "no_selected_client"}, status_code=400)

        doc = _digits_only(current_client.cnpj)
        email = (current_client.finance_email or current_client.email or "").strip()
        mapped = _contaazul_get_mapped_person_id(session, company_id=ctx.company.id, client_id=current_client.id)
        found = mapped or _contaazul_find_person_id(session, company_id=ctx.company.id, client=current_client)

        today = utcnow().date()
        d = (request.query_params.get("d") or "").strip()
        if d:
            try:
                dd = datetime.strptime(d, "%Y-%m-%d").date()
                w_start = dd.isoformat()
                w_end = dd.isoformat()
            except Exception:
                w_start = (today - timedelta(days=14)).isoformat()
                w_end = today.isoformat()
        else:
            w_start = (today - timedelta(days=14)).isoformat()
            w_end = today.isoformat()

        out: dict[str, Any] = {
            "ok": True,
            "client": {"id": current_client.id, "name": current_client.name, "doc": doc, "email": email},
            "person_id": {"mapped": mapped, "found": found},
            "range_nfse": {"de": w_start, "ate": w_end},
            "counts": {},
            "samples": {},
        }

        # NFS-e com person_id
        if found:
            try:
                payload = _contaazul_get_json(
                    session,
                    ctx.company.id,
                    "/v1/notas-fiscais-servico",
                    params=[
                        ("pagina", 1),
                        ("tamanho_pagina", 10),
                        ("data_competencia_de", w_start),
                        ("data_competencia_ate", w_end),
                        ("id_cliente", found),
                    ],
                )
                itens = (payload.get("itens") or []) if isinstance(payload, dict) else []
                out["counts"]["nfse_by_person"] = len(itens)
                out["samples"]["nfse_by_person"] = itens[:1]
            except Exception as e:
                out["counts"]["nfse_by_person_error"] = str(e)[:500]

        # NFS-e sem filtro (só pra validar se existem notas no período)
        try:
            payload = _contaazul_get_json(
                session,
                ctx.company.id,
                "/v1/notas-fiscais-servico",
                params=[
                    ("pagina", 1),
                    ("tamanho_pagina", 10),
                    ("data_competencia_de", w_start),
                    ("data_competencia_ate", w_end),
                ],
            )
            itens = (payload.get("itens") or []) if isinstance(payload, dict) else []
            out["counts"]["nfse_any"] = len(itens)
            out["samples"]["nfse_any"] = itens[:1]
        except Exception as e:
            out["counts"]["nfse_any_error"] = str(e)[:500]

        # NFS-e filtrada por documento (varre páginas) — vínculo por CNPJ
        if doc:
            try:
                page = 1
                count_total = 0
                first_match: dict[str, Any] | None = None
                while page <= 10:
                    payload = _contaazul_get_json(
                        session,
                        ctx.company.id,
                        "/v1/notas-fiscais-servico",
                        params=[
                            ("pagina", page),
                            ("tamanho_pagina", 100),
                            ("data_competencia_de", w_start),
                            ("data_competencia_ate", w_end),
                        ],
                    )
                    itens = (payload.get("itens") or []) if isinstance(payload, dict) else []
                    if not itens:
                        break
                    for it in itens:
                        if not isinstance(it, dict):
                            continue
                        if _digits_only(str(it.get("documento_cliente") or "")) == doc:
                            count_total += 1
                            if first_match is None:
                                first_match = it
                    if len(itens) < 100:
                        break
                    page += 1
                out["counts"]["nfse_doc_matches"] = count_total
                out["samples"]["nfse_doc_matches"] = [first_match] if first_match else []
            except Exception as e:
                out["counts"]["nfse_doc_matches_error"] = str(e)[:500]

        # NF-e por documento
        if doc:
            try:
                payload = _contaazul_get_json(
                    session,
                    ctx.company.id,
                    "/v1/notas-fiscais",
                    params={"data_inicial": w_start, "data_final": w_end, "pagina": 1, "tamanho_pagina": 10,
                            "documento_tomador": doc},
                )
                itens = (payload.get("itens") or []) if isinstance(payload, dict) else []
                out["counts"]["nfe_by_doc"] = len(itens)
                out["samples"]["nfe_by_doc"] = itens[:1]
            except Exception as e:
                out["counts"]["nfe_by_doc_error"] = str(e)[:500]

        return JSONResponse(out)
    except Exception as e:
        _ca_log(f"test endpoint failed: {e}")
        return JSONResponse({"ok": False, "error": str(e)[:500]}, status_code=500)


# ---------------------------
# Conta Azul: downloads
# ---------------------------

async def _contaazul_get_bytes(
        session: Session,
        company_id: int,
        path: str,
        *,
        params: Any = None,
        accept: str | None = None,
        timeout_s: float = 60.0,
) -> tuple[bytes, str]:
    """Fetch raw bytes from Conta Azul API (PDF/XML).

    Uses the same bearer + refresh logic used by JSON calls, but returns bytes and content-type.
    """
    base = CONTA_AZUL_API_BASE.rstrip("/")
    url = base + path
    headers = _contaazul_bearer_headers(session, company_id)
    if accept:
        headers["Accept"] = accept

    async with httpx.AsyncClient(timeout=timeout_s, follow_redirects=True) as client:
        resp = await client.get(url, headers=headers, params=params)
        if resp.status_code == 401:
            auth = _contaazul_get_auth(session, company_id)
            if auth:
                _contaazul_refresh(session, auth)
            headers = _contaazul_bearer_headers(session, company_id)
            if accept:
                headers["Accept"] = accept
            resp = await client.get(url, headers=headers, params=params)

    if resp.status_code >= 400:
        raise HTTPException(
            status_code=502,
            detail=f"Conta Azul API error: GET {path} HTTP {resp.status_code}",
        )
    ctype = (resp.headers.get("content-type") or "application/octet-stream").split(";")[0].strip()
    return resp.content, ctype


def _pdf_fatura_bytes(*, company_name: str, client_name: str, receivable: ContaAzulReceivable) -> bytes:
    """Gera um PDF simples (fatura) localmente.

    Observação: a API aberta do Conta Azul não expõe um endpoint documentado para baixar o PDF do boleto.
    Este PDF é um comprovante/fatura com os dados + link de pagamento (quando existir).
    """
    from io import BytesIO
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    w, h = A4

    y = h - 60
    c.setFont("Helvetica-Bold", 14)
    c.drawString(40, y, "Fatura / Cobrança")
    y -= 22

    c.setFont("Helvetica", 10)
    c.drawString(40, y, f"Empresa: {company_name}")
    y -= 14
    c.drawString(40, y, f"Cliente: {client_name}")
    y -= 14
    c.drawString(40, y, f"Descrição: {receivable.description or '—'}")
    y -= 14
    c.drawString(40, y, f"Vencimento: {receivable.due_date or '—'}   Status: {receivable.status or '—'}")
    y -= 14
    c.drawString(40, y, f"Valor em aberto: R$ {receivable.amount_open:.2f}   Pago: R$ {receivable.amount_paid:.2f}")
    y -= 14
    if receivable.invoice_number:
        c.drawString(40, y, f"Referência: {receivable.invoice_type} #{receivable.invoice_number}")
        y -= 14

    if receivable.payment_url:
        y -= 6
        c.setFont("Helvetica-Bold", 10)
        c.drawString(40, y, "Link de pagamento:")
        y -= 12
        c.setFont("Helvetica", 9)
        # quebra simples em linhas
        url = receivable.payment_url.strip()
        chunk = 90
        for i in range(0, len(url), chunk):
            c.drawString(40, y, url[i: i + chunk])
            y -= 11

    c.showPage()
    c.save()
    return buf.getvalue()


@app.get("/financeiro/contaazul/invoice/{invoice_id}/xml")
@require_login
async def contaazul_invoice_xml(
        invoice_id: int, request: Request, session: Session = Depends(get_session)
) -> Response:
    ctx = get_tenant_context(request, session)
    if not ctx:
        request.session.clear()
        return RedirectResponse("/login", status_code=303)

    inv = session.get(ContaAzulInvoice, invoice_id)
    if not inv or inv.company_id != ctx["company_id"]:
        raise HTTPException(status_code=404, detail="Nota não encontrada.")

    if ctx["role"] == "cliente" and inv.client_id != ctx["client_id"]:
        raise HTTPException(status_code=403, detail="Sem permissão.")

    if (inv.invoice_type or "").upper() != "NFE":
        raise HTTPException(status_code=400, detail="Esta nota não é NF-e.")

    # OpenAPI: GET /v1/notas-fiscais/{chave} retorna XML.
    chave = (inv.external_id or "").strip()
    if not chave:
        raise HTTPException(status_code=400, detail="Chave de acesso ausente.")

    content, ctype = await _contaazul_get_bytes(session, ctx["company_id"], f"/v1/notas-fiscais/{chave}",
                                                accept="application/xml")
    filename = f"nfe_{(inv.number or chave)}.xml"
    return Response(
        content=content,
        media_type=ctype or "application/xml",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/financeiro/contaazul/invoice/{invoice_id}/pdf")
@require_login
async def contaazul_invoice_pdf(
        invoice_id: int, request: Request, session: Session = Depends(get_session)
) -> Response:
    ctx = get_tenant_context(request, session)
    if not ctx:
        request.session.clear()
        return RedirectResponse("/login", status_code=303)

    inv = session.get(ContaAzulInvoice, invoice_id)
    if not inv or inv.company_id != ctx["company_id"]:
        raise HTTPException(status_code=404, detail="Nota não encontrada.")

    if ctx["role"] == "cliente" and inv.client_id != ctx["client_id"]:
        raise HTTPException(status_code=403, detail="Sem permissão.")

    if (inv.invoice_type or "").upper() != "NFSE":
        raise HTTPException(status_code=400, detail="Esta nota não é NFS-e.")

    # A API aberta de notas fiscais não expõe download do DANFSE; alternativa: PDF da venda.
    # Endpoint: GET /v1/venda/{id}/imprimir.
    try:
        payload = json.loads(inv.raw_json or "{}")
    except Exception:
        payload = {}
    sale_id = (payload.get("id_venda") or "").strip()
    if not sale_id:
        raise HTTPException(status_code=404, detail="Sem id_venda para gerar PDF.")

    content, ctype = await _contaazul_get_bytes(session, ctx["company_id"], f"/v1/venda/{sale_id}/imprimir",
                                                accept="application/pdf")
    filename = f"nfse_{(inv.number or inv.external_id)}.pdf"
    return Response(
        content=content,
        media_type=ctype or "application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/financeiro/contaazul/receivable/{rid}/fatura.pdf")
@require_login
async def contaazul_receivable_fatura_pdf(
        rid: int, request: Request, session: Session = Depends(get_session)
) -> Response:
    ctx = get_tenant_context(request, session)
    if not ctx:
        request.session.clear()
        return RedirectResponse("/login", status_code=303)

    r = session.get(ContaAzulReceivable, rid)
    if not r or r.company_id != ctx["company_id"]:
        raise HTTPException(status_code=404, detail="Cobrança não encontrada.")

    if ctx["role"] == "cliente" and r.client_id != ctx["client_id"]:
        raise HTTPException(status_code=403, detail="Sem permissão.")

    company = session.get(Company, ctx["company_id"])
    client = session.get(Client, r.client_id)
    pdf = _pdf_fatura_bytes(
        company_name=(company.name if company else "Empresa"),
        client_name=(client.name if client else "Cliente"),
        receivable=r,
    )
    filename = f"fatura_{r.installment_id}.pdf"
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/financeiro", response_class=HTMLResponse)
@require_login
async def fin_list(request: Request, session: Session = Depends(get_session)) -> HTMLResponse:
    ctx = get_tenant_context(request, session)
    if not ctx:
        request.session.clear()
        return RedirectResponse("/login", status_code=303)

    role = ctx.membership.role

    current_client = get_client_or_none(session, ctx.company.id, get_active_client_id(request, session, ctx))
    if role == "cliente":
        current_client = session.get(Client, ctx.membership.client_id) if ctx.membership.client_id else None

    # ----------------------------
    # Cobranças manuais
    # ----------------------------
    q = select(FinanceInvoice).where(FinanceInvoice.company_id == ctx.company.id)

    if current_client:
        q = q.where(FinanceInvoice.client_id == current_client.id)
    elif role == "cliente":
        # Cliente sem vínculo → não deve ver nada
        q = q.where(FinanceInvoice.client_id == -1)

    q = q.order_by(FinanceInvoice.created_at.desc()).limit(200)
    invs = session.exec(q).all()

    client_name_by_id: dict[int, str] = {}
    if role in ["admin", "equipe"] and invs:
        ids = sorted({int(i.client_id) for i in invs})
        if ids:
            for c in session.exec(select(Client).where(Client.id.in_(ids))).all():
                client_name_by_id[int(c.id)] = c.name

    items: list[dict[str, Any]] = []
    for inv in invs:
        created_at = inv.created_at.strftime("%Y-%m-%d %H:%M") if isinstance(inv.created_at, datetime) else str(
            inv.created_at)
        items.append(
            {
                "id": inv.id,
                "title": inv.title,
                "status": inv.status,
                "amount_brl": float(inv.amount_brl or 0.0),
                "due_date": (inv.due_date or "").strip(),
                "created_at": created_at,
                "client_name": client_name_by_id.get(int(inv.client_id), ""),
            }
        )

    # ----------------------------
    # Conta Azul
    # ----------------------------
    ca_configured = _contaazul_configured()
    ca_connected = False
    ca_last_sync = ""
    ca_person_id = ""
    ca_client_doc = _digits_only(current_client.cnpj) if current_client else ""
    ca_client_email = ((current_client.finance_email or current_client.email or "").strip() if current_client else "")

    ca_invoices: list[ContaAzulInvoice] = []
    ca_receivables: list[ContaAzulReceivable] = []

    if ca_configured and ensure_contaazul_tables():
        auth = _contaazul_get_auth(session, ctx.company.id)
        ca_connected = bool(auth and auth.refresh_token)
        if auth and auth.last_sync_at:
            ca_last_sync = _as_aware_utc(auth.last_sync_at).strftime("%Y-%m-%d %H:%M")

        if current_client:
            ca_person_id = _contaazul_get_mapped_person_id(session, company_id=ctx.company.id,
                                                           client_id=current_client.id)

            ca_invoices = session.exec(
                select(ContaAzulInvoice)
                .where(ContaAzulInvoice.company_id == ctx.company.id, ContaAzulInvoice.client_id == current_client.id)
                .order_by(ContaAzulInvoice.issue_date.desc())
                .limit(200)
            ).all()

            ca_receivables = session.exec(
                select(ContaAzulReceivable)
                .where(ContaAzulReceivable.company_id == ctx.company.id,
                       ContaAzulReceivable.client_id == current_client.id)
                .order_by(ContaAzulReceivable.due_date.asc())
                .limit(200)
            ).all()

    return render(
        "fin_list.html",
        request=request,
        context={
            "current_user": ctx.user,
            "current_company": ctx.company,
            "role": role,
            "current_client": current_client,
            "items": items,
            "ca_configured": ca_configured,
            "ca_connected": ca_connected,
            "ca_last_sync": ca_last_sync,
            "ca_person_id": ca_person_id,
            "ca_client_doc": ca_client_doc,
            "ca_client_email": ca_client_email,
            "ca_invoices": ca_invoices,
            "ca_receivables": ca_receivables,
        },
    )


@app.get("/financeiro/contaazul/debug", response_class=HTMLResponse)
@require_role({"admin", "equipe"})
async def contaazul_debug_page(request: Request, session: Session = Depends(get_session)) -> HTMLResponse:
    """Página HTML simples para depurar NFS-e/NF-e sem depender do JSON na UI."""
    try:
        ctx = get_tenant_context(request, session)
        if not ctx:
            return RedirectResponse("/login", status_code=303)

        if not ensure_contaazul_tables():
            return HTMLResponse("<h3>Conta Azul</h3><p>Banco sem tabelas da integração.</p>", status_code=500)

        if not _contaazul_configured():
            return HTMLResponse("<h3>Conta Azul</h3><p>Faltam env vars CONTA_AZUL_CLIENT_ID/SECRET.</p>",
                                status_code=400)

        auth = _contaazul_get_auth(session, ctx.company.id)
        if not auth or not auth.refresh_token:
            return HTMLResponse("<h3>Conta Azul</h3><p>Integração não conectada (sem refresh_token).</p>",
                                status_code=400)

        current_client = get_client_or_none(session, ctx.company.id, get_active_client_id(request, session, ctx))
        if not current_client:
            return HTMLResponse("<h3>Conta Azul</h3><p>Selecione um cliente (Trocar cliente) e volte aqui.</p>",
                                status_code=400)

        doc = _digits_only(current_client.cnpj)
        d = (request.query_params.get("d") or "").strip() or utcnow().date().isoformat()

        # Chamada "crua" (sem filtro por cliente) para verificar se o Conta Azul está retornando NFS-e no dia.
        payload_any = _contaazul_get_json(
            session,
            ctx.company.id,
            "/v1/notas-fiscais-servico",
            params=[("pagina", 1), ("tamanho_pagina", 100), ("data_competencia_de", d), ("data_competencia_ate", d)],
        )
        itens_any = (payload_any.get("itens") or []) if isinstance(payload_any, dict) else []
        matches = []
        if doc:
            for it in itens_any:
                if isinstance(it, dict) and _digits_only(str(it.get("documento_cliente") or "")) == doc:
                    matches.append(it)

        out = {
            "date": d,
            "client": {"id": current_client.id, "name": current_client.name, "doc": doc},
            "nfse_any_count": len(itens_any),
            "nfse_doc_matches_count": len(matches),
            "nfse_doc_first": matches[:1],
            "nfse_any_first": itens_any[:1],
        }

        pre = html.escape(json.dumps(out, ensure_ascii=False, indent=2))
        form = f"""
            <h2>Conta Azul • Debug NFS-e</h2>
            <p><b>Cliente:</b> {html.escape(current_client.name)} • <b>CNPJ:</b> {html.escape(doc or '—')}</p>
            <form method="get">
              <label>Data competência (YYYY-MM-DD):</label>
              <input name="d" value="{html.escape(d)}" style="padding:6px; width:180px;" />
              <button style="padding:6px 10px;">Testar</button>
              <a href="/financeiro" style="margin-left:10px;">Voltar</a>
            </form>
            <pre style="margin-top:16px; padding:12px; background:#0b1220; color:#e5e7eb; border-radius:10px; overflow:auto;">{pre}</pre>
        """
        return HTMLResponse(form)
    except Exception as e:
        _ca_log(f"debug page failed: {e}")
        return HTMLResponse(f"<h3>Erro</h3><pre>{html.escape(str(e))}</pre>", status_code=500)

    current_client = get_client_or_none(session, ctx.company.id, get_active_client_id(request, session, ctx))

    q = select(FinanceInvoice).where(FinanceInvoice.company_id == ctx.company.id).order_by(
        FinanceInvoice.created_at.desc())
    if ctx.membership.role == "cliente":
        invoices = session.exec(q.where(FinanceInvoice.client_id == (ctx.membership.client_id or -1))).all()
        target_client_id = int(ctx.membership.client_id or 0)
    else:
        if current_client:
            q = q.where(FinanceInvoice.client_id == current_client.id)
        invoices = session.exec(q).all()
        target_client_id = int(current_client.id if current_client else 0)

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

    ca_connected = False
    ca_last_sync = None
    ca_receivables = []
    ca_invoices = []
    if ensure_contaazul_tables():
        auth = _contaazul_get_auth(session, ctx.company.id)
        ca_connected = bool(auth and auth.refresh_token)
        ca_last_sync = auth.last_sync_at if auth else None

        if ca_connected and target_client_id:
            recs = session.exec(
                select(ContaAzulReceivable)
                .where(ContaAzulReceivable.company_id == ctx.company.id,
                       ContaAzulReceivable.client_id == target_client_id)
                .order_by(ContaAzulReceivable.due_date.desc())
                .limit(200)
            ).all()
            for r in recs:
                ca_receivables.append(
                    {
                        "installment_id": r.installment_id,
                        "description": r.description or "—",
                        "due_date": r.due_date,
                        "status": r.status,
                        "amount_total": r.amount_total,
                        "amount_open": r.amount_open,
                        "payment_method": r.payment_method,
                        "invoice_type": r.invoice_type,
                        "invoice_number": r.invoice_number,
                        "boleto_status": r.boleto_status,
                        "payment_url": r.payment_url,
                        "updated_at": r.updated_at,
                    }
                )

            invs = session.exec(
                select(ContaAzulInvoice)
                .where(ContaAzulInvoice.company_id == ctx.company.id, ContaAzulInvoice.client_id == target_client_id)
                .order_by(ContaAzulInvoice.issue_date.desc())
                .limit(200)
            ).all()
            for inv in invs:
                ca_invoices.append(
                    {
                        "invoice_type": inv.invoice_type,
                        "external_id": inv.external_id,
                        "number": inv.number,
                        "issue_date": inv.issue_date,
                        "status": inv.status,
                        "amount": inv.amount,
                        "updated_at": inv.updated_at,
                    }
                )

    ca_person_id = ""
    ca_client_doc = ""
    ca_client_email = ""
    if ensure_contaazul_tables() and target_client_id:
        tc = session.get(Client, int(target_client_id))
        if tc and tc.company_id == ctx.company.id:
            ca_client_doc = _digits_only(tc.cnpj)
            ca_client_email = (tc.finance_email or tc.email or "").strip()
            ca_person_id = _contaazul_get_mapped_person_id(session, company_id=ctx.company.id, client_id=tc.id)

    return render(
        "fin_list.html",
        request=request,
        context={
            "current_user": ctx.user,
            "current_company": ctx.company,
            "role": ctx.membership.role,
            "current_client": current_client,
            "items": out,
            "ca_configured": _contaazul_configured(),
            "ca_connected": ca_connected,
            "ca_last_sync": ca_last_sync,
            "ca_receivables": ca_receivables,
            "ca_invoices": ca_invoices,
            "ca_person_id": ca_person_id,
            "ca_client_doc": ca_client_doc,
            "ca_client_email": ca_client_email,
        },
    )


@app.get("/financeiro/novo", response_class=HTMLResponse)
@require_role({"admin", "equipe"})
async def fin_new_page(request: Request, session: Session = Depends(get_session)) -> HTMLResponse:
    ctx = get_tenant_context(request, session)
    assert ctx is not None

    # Garante tabela em ambientes sem Alembic
    if not ensure_credit_consent_table():
        set_flash(request, "Sistema de aceite não está configurado (migração pendente no banco).")
        return RedirectResponse("/credito", status_code=303)

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

    # Garante tabela em ambientes sem Alembic
    if not ensure_credit_consent_table():
        set_flash(request, "Sistema de aceite não está configurado (migração pendente no banco).")
        return RedirectResponse("/credito", status_code=303)

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

    # Garante tabela em ambientes sem Alembic
    if not ensure_credit_consent_table():
        set_flash(request, "Sistema de aceite não está configurado (migração pendente no banco).")
        return RedirectResponse("/credito", status_code=303)

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
async def download_attachment(request: Request, session: Session = Depends(get_session),
                              attachment_id: int = 0) -> Response:
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
        return render("error.html", request=request, context={"message": "Arquivo não está mais no servidor."},
                      status_code=404)

    return FileResponse(path=str(path), media_type=att.mime_type, filename=att.original_filename)


# ----------------------------
# Extras: Agenda + Attachments + Edit/Delete + Client create
# ----------------------------

def _delete_attachment_file(att: Attachment) -> None:
    path = UPLOAD_DIR / att.stored_filename
    try:
        if path.exists():
            path.unlink()
    except Exception:
        pass


@app.get("/agenda", response_class=HTMLResponse)
@require_login
async def agenda_page(request: Request, session: Session = Depends(get_session)) -> HTMLResponse:
    ctx = get_tenant_context(request, session)
    if not ctx:
        request.session.clear()
        return RedirectResponse("/login", status_code=303)

    active_client_id = get_active_client_id(request, session, ctx)
    current_client = get_client_or_none(session, ctx.company.id, active_client_id)

    return render(
        "agenda.html",
        request=request,
        context={
            "current_user": ctx.user,
            "current_company": ctx.company,
            "role": ctx.membership.role,
            "current_client": current_client,
        },
    )


# ----------------------------
# Tarefas (Kanban)
# ----------------------------

def _task_can_view(ctx: TenantContext, task: Task) -> bool:
    if task.company_id != ctx.company.id:
        return False
    if ctx.membership.role in ["admin", "equipe"]:
        return True
    # cliente
    return bool(ctx.membership.client_id) and task.client_id == ctx.membership.client_id and task.visible_to_client


def _task_assignee_label(session: Session, user_id: Optional[int]) -> str:
    if not user_id:
        return ""
    u = session.get(User, int(user_id))
    return u.name if u else ""


@app.get("/tarefas", response_class=HTMLResponse)
@require_login
async def tasks_list(
        request: Request,
        session: Session = Depends(get_session),
        client_id: int = 0,  # 0=todos (staff)
        assignee_user_id: int = 0,  # 0=todos, -1=sem responsável (staff)
        status: str = "",  # "", nao_iniciada, em_andamento, concluida
        priority: str = "",  # "", baixa, media, alta
        due: str = "",  # "", atrasadas, hoje, 7dias, sem_prazo
        mine: int = 0,  # 1=apenas minhas (staff)
) -> HTMLResponse:
    ctx = get_tenant_context(request, session)
    if not ctx:
        request.session.clear()
        return RedirectResponse("/login", status_code=303)

    active_client_id = get_active_client_id(request, session, ctx)
    current_client = get_client_or_none(session, ctx.company.id, active_client_id)

    q = select(Task).where(Task.company_id == ctx.company.id)

    clients: list[Client] = []
    assignees: list[dict[str, Any]] = []
    filter_client_id = 0
    filter_assignee_user_id = 0
    filter_status = ""
    filter_priority = ""
    filter_due = ""
    filter_mine = 0

    if ctx.membership.role == "cliente":
        q = q.where(
            Task.client_id == (ctx.membership.client_id or -1),
            Task.visible_to_client.is_(True),
        ).order_by(Task.updated_at.desc())
    else:
        # listas de filtro
        clients = session.exec(
            select(Client).where(Client.company_id == ctx.company.id).order_by(Client.created_at)
        ).all()

        memberships = session.exec(select(Membership).where(Membership.company_id == ctx.company.id)).all()
        for m in memberships:
            u = session.get(User, m.user_id)
            if not u:
                continue
            if m.role in {"admin", "equipe"}:
                assignees.append({"id": u.id, "name": u.name, "role": m.role})

        # aplicar filtros
        if mine == 1:
            filter_mine = 1
            filter_assignee_user_id = ctx.user.id
            q = q.where(Task.assignee_user_id == ctx.user.id)
        else:
            if assignee_user_id == -1:
                filter_assignee_user_id = -1
                q = q.where(Task.assignee_user_id.is_(None))
            elif assignee_user_id and assignee_user_id > 0:
                filter_assignee_user_id = int(assignee_user_id)
                q = q.where(Task.assignee_user_id == int(assignee_user_id))

        if client_id and client_id > 0:
            fc = get_client_or_none(session, ctx.company.id, int(client_id))
            if not fc:
                set_flash(request, "Cliente inválido para filtro.")
                return RedirectResponse("/tarefas", status_code=303)
            filter_client_id = fc.id
            q = q.where(Task.client_id == fc.id)

        status = (status or "").strip().lower()
        if status in TASK_STATUS:
            filter_status = status
            q = q.where(Task.status == status)

        priority = (priority or "").strip().lower()
        if priority in TASK_PRIORITY:
            filter_priority = priority
            q = q.where(Task.priority == priority)

        due = (due or "").strip().lower()
        today = datetime.now(timezone.utc).date()
        today_s = today.isoformat()
        end_s = (today + timedelta(days=7)).isoformat()

        if due in {"atrasadas", "hoje", "7dias", "sem_prazo"}:
            filter_due = due
            if due == "sem_prazo":
                q = q.where((Task.due_date == "") | (Task.due_date.is_(None)))
            elif due == "hoje":
                q = q.where(Task.due_date == today_s)
            elif due == "7dias":
                q = q.where(Task.due_date >= today_s, Task.due_date <= end_s)
            elif due == "atrasadas":
                q = q.where(Task.due_date != "", Task.due_date < today_s, Task.status != "concluida")

        q = q.order_by(Task.updated_at.desc())

    tasks = session.exec(q).all()

    view = []
    for t in tasks:
        view.append(
            {
                "id": t.id,
                "title": t.title,
                "status": t.status,
                "priority": t.priority,
                "due_date": t.due_date,
                "visible_to_client": t.visible_to_client,
                "assignee_name": _task_assignee_label(session, t.assignee_user_id),
                "client_name": (session.get(Client, t.client_id).name if session.get(Client, t.client_id) else ""),
            }
        )

    by_status = {"nao_iniciada": [], "em_andamento": [], "concluida": []}
    for t in view:
        by_status.setdefault(t["status"], by_status["nao_iniciada"]).append(t)

    columns = [
        {"key": "nao_iniciada", "label": "Não iniciada", "tasks": by_status.get("nao_iniciada", []),
         "count": len(by_status.get("nao_iniciada", []))},
        {"key": "em_andamento", "label": "Em andamento", "tasks": by_status.get("em_andamento", []),
         "count": len(by_status.get("em_andamento", []))},
        {"key": "concluida", "label": "Concluída", "tasks": by_status.get("concluida", []),
         "count": len(by_status.get("concluida", []))},
    ]

    return render(
        "tasks_list.html",
        request=request,
        context={
            "current_user": ctx.user,
            "current_company": ctx.company,
            "role": ctx.membership.role,
            "current_client": current_client,
            "clients": clients,
            "assignees": assignees,
            "filter_client_id": filter_client_id,
            "filter_assignee_user_id": filter_assignee_user_id,
            "filter_status": filter_status,
            "filter_priority": filter_priority,
            "filter_due": filter_due,
            "filter_mine": filter_mine,
            "columns": columns,
        },
    )


@app.get("/tarefas/nova", response_class=HTMLResponse)
@require_role({"admin", "equipe"})
async def tasks_new_page(
        request: Request,
        session: Session = Depends(get_session),
        client_id: int = 0,  # <-- ADICIONE ISTO (vem da querystring ?client_id=)
) -> HTMLResponse:
    ctx = get_tenant_context(request, session)
    assert ctx is not None

    # Garante tabela em ambientes sem Alembic
    if not ensure_credit_consent_table():
        set_flash(request, "Sistema de aceite não está configurado (migração pendente no banco).")
        return RedirectResponse("/credito", status_code=303)

    clients = session.exec(select(Client).where(Client.company_id == ctx.company.id).order_by(Client.created_at)).all()

    # staff assignees (admin/equipe) + current user always
    memberships = session.exec(select(Membership).where(Membership.company_id == ctx.company.id)).all()
    assignees = []
    for m in memberships:
        u = session.get(User, m.user_id)
        if not u:
            continue
        assignees.append({"id": u.id, "name": u.name, "role": m.role})

    active_client_id = get_active_client_id(request, session, ctx)
    current_client = get_client_or_none(session, ctx.company.id, active_client_id)

    prefill_client = current_client
    if client_id and client_id > 0:
        fc = get_client_or_none(session, ctx.company.id, int(client_id))
        if fc:
            prefill_client = fc

    return render(
        "tasks_new.html",
        request=request,
        context={
            "current_user": ctx.user,
            "current_company": ctx.company,
            "role": ctx.membership.role,
            "current_client": current_client,
            "prefill_client": prefill_client,
            "clients": clients,
            "assignees": assignees,
        },
    )


@app.post("/tarefas/nova")
@require_role({"admin", "equipe"})
async def tasks_new_action(
        request: Request,
        session: Session = Depends(get_session),
        client_id: int = Form(...),
        assignee_user_id: str = Form(""),
        title: str = Form(...),
        description: str = Form(""),
        status: str = Form("nao_iniciada"),
        priority: str = Form("media"),
        due_date: str = Form(""),
        visible_to_client: str = Form(""),
        client_action: str = Form(""),
) -> Response:
    ctx = get_tenant_context(request, session)
    assert ctx is not None

    # Garante tabela em ambientes sem Alembic
    if not ensure_credit_consent_table():
        set_flash(request, "Sistema de aceite não está configurado (migração pendente no banco).")
        return RedirectResponse("/credito", status_code=303)

    client = get_client_or_none(session, ctx.company.id, int(client_id))
    if not client:
        set_flash(request, "Cliente inválido.")
        return RedirectResponse("/tarefas/nova", status_code=303)

    status = status.strip().lower()
    if status not in TASK_STATUS:
        status = "nao_iniciada"

    priority = priority.strip().lower()
    if priority not in TASK_PRIORITY:
        priority = "media"

    assignee = int(assignee_user_id) if assignee_user_id.strip().isdigit() else None

    task = Task(
        company_id=ctx.company.id,
        client_id=client.id,
        created_by_user_id=ctx.user.id,
        assignee_user_id=assignee,
        title=title.strip(),
        description=description.strip(),
        status=status,
        priority=priority,
        due_date=due_date.strip(),
        visible_to_client=(visible_to_client == "1"),
        client_action=(client_action == "1"),
        created_at=utcnow(),
        updated_at=utcnow(),
    )
    session.add(task)
    session.commit()
    session.refresh(task)

    set_flash(request, "Tarefa criada.")
    return RedirectResponse(f"/tarefas/{task.id}", status_code=303)


@app.get("/tarefas/{task_id}", response_class=HTMLResponse)
@require_login
async def tasks_detail(request: Request, session: Session = Depends(get_session), task_id: int = 0) -> HTMLResponse:
    ctx = get_tenant_context(request, session)
    if not ctx:
        request.session.clear()
        return RedirectResponse("/login", status_code=303)

    task = session.get(Task, int(task_id))
    if not task or not _task_can_view(ctx, task):
        return render(
            "error.html",
            request=request,
            context={"message": "Tarefa não encontrada ou sem permissão."},
            status_code=404,
        )

    active_client_id = get_active_client_id(request, session, ctx)
    current_client = get_client_or_none(session, ctx.company.id, active_client_id)

    comments = session.exec(
        select(TaskComment)
        .where(TaskComment.task_id == task.id)
        .order_by(TaskComment.created_at.asc())
    ).all()
    out_comments = []
    for c in comments:
        u = session.get(User, c.author_user_id)
        out_comments.append(
            {
                "author_name": u.name if u else "—",
                "message": c.message,
                "created_at": c.created_at.strftime("%Y-%m-%d %H:%M"),
            }
        )

    attachments = session.exec(
        select(Attachment)
        .where(Attachment.task_id == task.id)
        .order_by(Attachment.created_at.asc())
    ).all()
    out_attachments = []
    for a in attachments:
        out_attachments.append(
            {
                "id": a.id,
                "original_filename": a.original_filename,
                "created_at": a.created_at.strftime("%Y-%m-%d %H:%M"),
            }
        )

    assignee_name = _task_assignee_label(session, task.assignee_user_id)

    return render(
        "tasks_detail.html",
        request=request,
        context={
            "current_user": ctx.user,
            "current_company": ctx.company,
            "role": ctx.membership.role,
            "current_client": current_client,
            "task": task,
            "assignee_name": assignee_name,
            "comments": out_comments,
            "attachments": out_attachments,
        },
    )


@app.post("/tarefas/{task_id}/comentario")
@require_login
async def tasks_add_comment(
        request: Request,
        session: Session = Depends(get_session),
        task_id: int = 0,
        message: str = Form(...),
) -> Response:
    ctx = get_tenant_context(request, session)
    if not ctx:
        request.session.clear()
        return RedirectResponse("/login", status_code=303)

    task = session.get(Task, int(task_id))
    if not task or not _task_can_view(ctx, task):
        set_flash(request, "Sem permissão.")
        return RedirectResponse("/tarefas", status_code=303)

    msg = message.strip()
    if not msg:
        return RedirectResponse(f"/tarefas/{task.id}", status_code=303)

    session.add(TaskComment(task_id=task.id, author_user_id=ctx.user.id, message=msg))
    session.commit()

    return RedirectResponse(f"/tarefas/{task.id}", status_code=303)


@app.post("/tarefas/{task_id}/anexar")
@require_login
async def tasks_attach_file(
        request: Request,
        session: Session = Depends(get_session),
        task_id: int = 0,
        file: UploadFile = File(...),
) -> Response:
    ctx = get_tenant_context(request, session)
    if not ctx:
        request.session.clear()
        return RedirectResponse("/login", status_code=303)

    task = session.get(Task, int(task_id))
    if not task or not _task_can_view(ctx, task):
        set_flash(request, "Tarefa não encontrada ou sem permissão.")
        return RedirectResponse("/tarefas", status_code=303)

    # Cliente só anexa se a tarefa for visível a ele
    if ctx.membership.role == "cliente" and not task.visible_to_client:
        set_flash(request, "Sem permissão.")
        return RedirectResponse("/tarefas", status_code=303)

    if not file or not file.filename:
        set_flash(request, "Selecione um arquivo.")
        return RedirectResponse(f"/tarefas/{task.id}", status_code=303)

    try:
        stored, mime, size = await save_upload(file)
    except ValueError:
        set_flash(request, "Arquivo muito grande.")
        return RedirectResponse(f"/tarefas/{task.id}", status_code=303)

    session.add(
        Attachment(
            company_id=ctx.company.id,
            client_id=task.client_id,
            uploaded_by_user_id=ctx.user.id,
            task_id=task.id,
            original_filename=file.filename or "arquivo",
            stored_filename=stored,
            mime_type=mime,
            size_bytes=size,
        )
    )
    session.commit()

    set_flash(request, "Anexo enviado.")
    return RedirectResponse(f"/tarefas/{task.id}", status_code=303)


@app.post("/tarefas/{task_id}/toggle")
@require_role({"cliente"})
async def tasks_toggle_client(request: Request, session: Session = Depends(get_session), task_id: int = 0) -> Response:
    ctx = get_tenant_context(request, session)
    assert ctx is not None

    # Garante tabela em ambientes sem Alembic
    if not ensure_credit_consent_table():
        set_flash(request, "Sistema de aceite não está configurado (migração pendente no banco).")
        return RedirectResponse("/credito", status_code=303)

    task = session.get(Task, int(task_id))
    if not task or not _task_can_view(ctx, task):
        set_flash(request, "Sem permissão.")
        return RedirectResponse("/tarefas", status_code=303)

    if not task.client_action:
        set_flash(request, "Você não pode concluir esta tarefa.")
        return RedirectResponse(f"/tarefas/{task.id}", status_code=303)

    task.status = "nao_iniciada" if task.status == "concluida" else "concluida"
    task.updated_at = utcnow()
    session.add(task)
    session.commit()

    return RedirectResponse(f"/tarefas/{task.id}", status_code=303)


@app.post("/tarefas/{task_id}/status")
@require_role({"admin", "equipe"})
async def tasks_set_status(request: Request, session: Session = Depends(get_session), task_id: int = 0,
                           status: str = Form(...)) -> Response:
    ctx = get_tenant_context(request, session)
    assert ctx is not None

    # Garante tabela em ambientes sem Alembic
    if not ensure_credit_consent_table():
        set_flash(request, "Sistema de aceite não está configurado (migração pendente no banco).")
        return RedirectResponse("/credito", status_code=303)

    task = session.get(Task, int(task_id))
    if not task or task.company_id != ctx.company.id:
        set_flash(request, "Tarefa não encontrada.")
        return RedirectResponse("/tarefas", status_code=303)

    status = status.strip().lower()
    if status not in TASK_STATUS:
        status = "nao_iniciada"

    task.status = status
    task.updated_at = utcnow()
    session.add(task)
    session.commit()

    return RedirectResponse(f"/tarefas/{task.id}", status_code=303)


@app.get("/tarefas/{task_id}/editar", response_class=HTMLResponse)
@require_role({"admin", "equipe"})
async def tasks_edit_page(request: Request, session: Session = Depends(get_session), task_id: int = 0) -> HTMLResponse:
    ctx = get_tenant_context(request, session)
    assert ctx is not None

    # Garante tabela em ambientes sem Alembic
    if not ensure_credit_consent_table():
        set_flash(request, "Sistema de aceite não está configurado (migração pendente no banco).")
        return RedirectResponse("/credito", status_code=303)

    task = session.get(Task, int(task_id))
    if not task or task.company_id != ctx.company.id:
        return render("error.html", request=request, context={"message": "Tarefa não encontrada."}, status_code=404)

    clients = session.exec(select(Client).where(Client.company_id == ctx.company.id).order_by(Client.created_at)).all()
    memberships = session.exec(select(Membership).where(Membership.company_id == ctx.company.id)).all()
    assignees = []
    for m in memberships:
        u = session.get(User, m.user_id)
        if not u:
            continue
        assignees.append({"id": u.id, "name": u.name, "role": m.role})

    active_client_id = get_active_client_id(request, session, ctx)
    current_client = get_client_or_none(session, ctx.company.id, active_client_id)

    return render(
        "tasks_edit.html",
        request=request,
        context={
            "current_user": ctx.user,
            "current_company": ctx.company,
            "role": ctx.membership.role,
            "current_client": current_client,
            "task": task,
            "clients": clients,
            "assignees": assignees,
        },
    )


@app.post("/tarefas/{task_id}/editar")
@require_role({"admin", "equipe"})
async def tasks_edit_action(
        request: Request,
        session: Session = Depends(get_session),
        task_id: int = 0,
        client_id: int = Form(...),
        assignee_user_id: str = Form(""),
        title: str = Form(...),
        description: str = Form(""),
        status: str = Form("nao_iniciada"),
        priority: str = Form("media"),
        due_date: str = Form(""),
        visible_to_client: str = Form(""),
        client_action: str = Form(""),
) -> Response:
    ctx = get_tenant_context(request, session)
    assert ctx is not None

    # Garante tabela em ambientes sem Alembic
    if not ensure_credit_consent_table():
        set_flash(request, "Sistema de aceite não está configurado (migração pendente no banco).")
        return RedirectResponse("/credito", status_code=303)

    task = session.get(Task, int(task_id))
    if not task or task.company_id != ctx.company.id:
        set_flash(request, "Tarefa não encontrada.")
        return RedirectResponse("/tarefas", status_code=303)

    client = get_client_or_none(session, ctx.company.id, int(client_id))
    if not client:
        set_flash(request, "Cliente inválido.")
        return RedirectResponse(f"/tarefas/{task.id}/editar", status_code=303)

    status = status.strip().lower()
    if status not in TASK_STATUS:
        status = "nao_iniciada"

    priority = priority.strip().lower()
    if priority not in TASK_PRIORITY:
        priority = "media"

    assignee = int(assignee_user_id) if assignee_user_id.strip().isdigit() else None

    task.client_id = client.id
    task.assignee_user_id = assignee
    task.title = title.strip()
    task.description = description.strip()
    task.status = status
    task.priority = priority
    task.due_date = due_date.strip()
    task.visible_to_client = (visible_to_client == "1")
    task.client_action = (client_action == "1")
    task.updated_at = utcnow()

    session.add(task)
    session.commit()

    set_flash(request, "Tarefa atualizada.")
    return RedirectResponse(f"/tarefas/{task.id}", status_code=303)


@app.post("/tarefas/{task_id}/excluir")
@require_role({"admin", "equipe"})
async def tasks_delete_action(
        request: Request,
        session: Session = Depends(get_session),
        task_id: int = 0,
        confirm: str = Form(""),
) -> Response:
    ctx = get_tenant_context(request, session)
    assert ctx is not None

    # Garante tabela em ambientes sem Alembic
    if not ensure_credit_consent_table():
        set_flash(request, "Sistema de aceite não está configurado (migração pendente no banco).")
        return RedirectResponse("/credito", status_code=303)

    task = session.get(Task, int(task_id))
    if not task or task.company_id != ctx.company.id:
        set_flash(request, "Tarefa não encontrada.")
        return RedirectResponse("/tarefas", status_code=303)

    if confirm.strip().upper() != "EXCLUIR":
        set_flash(request, "Confirmação inválida. Digite EXCLUIR.")
        return RedirectResponse(f"/tarefas/{task.id}", status_code=303)

    # Segurança: não excluir se ainda houver anexos
    has_att = session.exec(select(Attachment.id).where(Attachment.task_id == task.id)).first()
    if has_att:
        set_flash(request, "Remova os anexos antes de excluir a tarefa.")
        return RedirectResponse(f"/tarefas/{task.id}", status_code=303)

    # delete comments first
    session.exec(delete(TaskComment).where(TaskComment.task_id == task.id))
    session.exec(delete(Task).where(Task.id == task.id))
    session.commit()

    set_flash(request, "Tarefa excluída.")
    return RedirectResponse("/tarefas", status_code=303)


@app.post("/attachments/{attachment_id}/delete")
@require_role({"admin", "equipe"})
async def delete_attachment(
        request: Request,
        session: Session = Depends(get_session),
        attachment_id: int = 0,
        next: str = Form("/"),
) -> Response:
    ctx = get_tenant_context(request, session)
    assert ctx is not None

    # Garante tabela em ambientes sem Alembic
    if not ensure_credit_consent_table():
        set_flash(request, "Sistema de aceite não está configurado (migração pendente no banco).")
        return RedirectResponse("/credito", status_code=303)

    att = session.get(Attachment, int(attachment_id))
    if not att or att.company_id != ctx.company.id:
        set_flash(request, "Anexo não encontrado.")
        return RedirectResponse(next, status_code=303)

    _delete_attachment_file(att)
    session.delete(att)
    session.commit()

    set_flash(request, "Anexo excluído.")
    return RedirectResponse(next, status_code=303)


@app.get("/pendencias/cliente/nova", response_class=HTMLResponse)
@require_role({"cliente"})
async def pending_new_client_page(request: Request, session: Session = Depends(get_session)) -> HTMLResponse:
    ctx = get_tenant_context(request, session)
    assert ctx is not None

    # Garante tabela em ambientes sem Alembic
    if not ensure_credit_consent_table():
        set_flash(request, "Sistema de aceite não está configurado (migração pendente no banco).")
        return RedirectResponse("/credito", status_code=303)

    active_client_id = get_active_client_id(request, session, ctx)
    current_client = get_client_or_none(session, ctx.company.id, active_client_id)

    return render(
        "pending_new_client.html",
        request=request,
        context={
            "current_user": ctx.user,
            "current_company": ctx.company,
            "role": ctx.membership.role,
            "current_client": current_client,
        },
    )


@app.post("/pendencias/cliente/nova")
@require_role({"cliente"})
async def pending_new_client_action(
        request: Request,
        session: Session = Depends(get_session),
        title: str = Form(...),
        description: str = Form(""),
        due_date: str = Form(""),
        file: UploadFile | None = File(default=None),
) -> Response:
    ctx = get_tenant_context(request, session)
    assert ctx is not None

    # Garante tabela em ambientes sem Alembic
    if not ensure_credit_consent_table():
        set_flash(request, "Sistema de aceite não está configurado (migração pendente no banco).")
        return RedirectResponse("/credito", status_code=303)

    client_id = ctx.membership.client_id or 0
    client = get_client_or_none(session, ctx.company.id, client_id)
    if not client:
        set_flash(request, "Seu usuário não está vinculado a um cliente.")
        return RedirectResponse("/pendencias", status_code=303)

    item = PendingItem(
        company_id=ctx.company.id,
        client_id=client.id,
        created_by_user_id=ctx.user.id,
        title=title.strip(),
        description=description.strip(),
        status="cliente_enviou",
        due_date=due_date.strip(),
        created_at=utcnow(),
        updated_at=utcnow(),
    )
    session.add(item)
    session.commit()
    session.refresh(item)

    if description.strip():
        session.add(PendingMessage(pending_item_id=item.id, author_user_id=ctx.user.id, message=description.strip()))
        session.commit()

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
                original_filename=file.filename or "arquivo",
                stored_filename=stored,
                mime_type=mime,
                size_bytes=size,
            )
        )
        session.commit()

    set_flash(request, "Pendência criada.")
    return RedirectResponse(f"/pendencias/{item.id}", status_code=303)


@app.get("/documentos/cliente/enviar", response_class=HTMLResponse)
@require_role({"cliente"})
async def docs_send_client_page(request: Request, session: Session = Depends(get_session)) -> HTMLResponse:
    ctx = get_tenant_context(request, session)
    assert ctx is not None

    # Garante tabela em ambientes sem Alembic
    if not ensure_credit_consent_table():
        set_flash(request, "Sistema de aceite não está configurado (migração pendente no banco).")
        return RedirectResponse("/credito", status_code=303)

    active_client_id = get_active_client_id(request, session, ctx)
    current_client = get_client_or_none(session, ctx.company.id, active_client_id)

    return render(
        "docs_send_client.html",
        request=request,
        context={
            "current_user": ctx.user,
            "current_company": ctx.company,
            "role": ctx.membership.role,
            "current_client": current_client,
        },
    )


@app.post("/documentos/cliente/enviar")
@require_role({"cliente"})
async def docs_send_client_action(
        request: Request,
        session: Session = Depends(get_session),
        title: str = Form(...),
        message: str = Form(""),
        file: UploadFile = File(...),
) -> Response:
    ctx = get_tenant_context(request, session)
    assert ctx is not None

    # Garante tabela em ambientes sem Alembic
    if not ensure_credit_consent_table():
        set_flash(request, "Sistema de aceite não está configurado (migração pendente no banco).")
        return RedirectResponse("/credito", status_code=303)

    client_id = ctx.membership.client_id or 0
    client = get_client_or_none(session, ctx.company.id, client_id)
    if not client:
        set_flash(request, "Seu usuário não está vinculado a um cliente.")
        return RedirectResponse("/documentos", status_code=303)

    content = message.strip() or "Enviado pelo cliente."
    doc = Document(
        company_id=ctx.company.id,
        client_id=client.id,
        created_by_user_id=ctx.user.id,
        title=title.strip(),
        content=content,
        status="cliente_enviou",
        created_at=utcnow(),
        updated_at=utcnow(),
    )
    session.add(doc)
    session.commit()
    session.refresh(doc)

    if message.strip():
        session.add(DocumentMessage(document_id=doc.id, author_user_id=ctx.user.id, message=message.strip()))
        session.commit()

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
    session.commit()

    set_flash(request, "Documento enviado.")
    return RedirectResponse(f"/documentos/{doc.id}", status_code=303)


@app.get("/documentos/{doc_id}/editar", response_class=HTMLResponse)
@require_role({"admin", "equipe"})
async def docs_edit_page(request: Request, session: Session = Depends(get_session), doc_id: int = 0) -> HTMLResponse:
    ctx = get_tenant_context(request, session)
    assert ctx is not None

    # Garante tabela em ambientes sem Alembic
    if not ensure_credit_consent_table():
        set_flash(request, "Sistema de aceite não está configurado (migração pendente no banco).")
        return RedirectResponse("/credito", status_code=303)

    doc = session.get(Document, int(doc_id))
    if not doc or doc.company_id != ctx.company.id:
        return render("error.html", request=request, context={"message": "Documento não encontrado."}, status_code=404)

    active_client_id = get_active_client_id(request, session, ctx)
    current_client = get_client_or_none(session, ctx.company.id, active_client_id)

    return render(
        "docs_edit.html",
        request=request,
        context={
            "current_user": ctx.user,
            "current_company": ctx.company,
            "role": ctx.membership.role,
            "current_client": current_client,
            "doc": doc,
        },
    )


@app.post("/documentos/{doc_id}/editar")
@require_role({"admin", "equipe"})
async def docs_edit_action(
        request: Request,
        session: Session = Depends(get_session),
        doc_id: int = 0,
        title: str = Form(...),
        content: str = Form(...),
        status: str = Form("rascunho"),
) -> Response:
    ctx = get_tenant_context(request, session)
    assert ctx is not None

    # Garante tabela em ambientes sem Alembic
    if not ensure_credit_consent_table():
        set_flash(request, "Sistema de aceite não está configurado (migração pendente no banco).")
        return RedirectResponse("/credito", status_code=303)

    doc = session.get(Document, int(doc_id))
    if not doc or doc.company_id != ctx.company.id:
        set_flash(request, "Documento não encontrado.")
        return RedirectResponse("/documentos", status_code=303)

    doc.title = title.strip()
    doc.content = content.strip()
    doc.status = status.strip().lower()
    doc.updated_at = utcnow()
    session.add(doc)
    session.commit()

    set_flash(request, "Documento atualizado.")
    return RedirectResponse(f"/documentos/{doc.id}", status_code=303)


@app.post("/documentos/{doc_id}/excluir")
@require_role({"admin", "equipe"})
async def docs_delete_action(request: Request, session: Session = Depends(get_session), doc_id: int = 0) -> Response:
    ctx = get_tenant_context(request, session)
    assert ctx is not None

    # Garante tabela em ambientes sem Alembic
    if not ensure_credit_consent_table():
        set_flash(request, "Sistema de aceite não está configurado (migração pendente no banco).")
        return RedirectResponse("/credito", status_code=303)

    doc = session.get(Document, int(doc_id))
    if not doc or doc.company_id != ctx.company.id:
        set_flash(request, "Documento não encontrado.")
        return RedirectResponse("/documentos", status_code=303)

    atts = session.exec(select(Attachment).where(Attachment.document_id == doc.id)).all()
    if atts:
        set_flash(request, "Remova os anexos antes de excluir o documento.")
        return RedirectResponse(f"/documentos/{doc.id}", status_code=303)

    msgs = session.exec(select(DocumentMessage).where(DocumentMessage.document_id == doc.id)).all()
    for m in msgs:
        session.delete(m)

    session.delete(doc)
    session.commit()

    set_flash(request, "Documento excluído.")
    return RedirectResponse("/documentos", status_code=303)


@app.get("/pendencias/{item_id}/editar", response_class=HTMLResponse)
@require_role({"admin", "equipe"})
async def pending_edit_page(request: Request, session: Session = Depends(get_session),
                            item_id: int = 0) -> HTMLResponse:
    ctx = get_tenant_context(request, session)
    assert ctx is not None

    # Garante tabela em ambientes sem Alembic
    if not ensure_credit_consent_table():
        set_flash(request, "Sistema de aceite não está configurado (migração pendente no banco).")
        return RedirectResponse("/credito", status_code=303)

    item = session.get(PendingItem, int(item_id))
    if not item or item.company_id != ctx.company.id:
        return render("error.html", request=request, context={"message": "Pendência não encontrada."}, status_code=404)

    active_client_id = get_active_client_id(request, session, ctx)
    current_client = get_client_or_none(session, ctx.company.id, active_client_id)

    return render(
        "pending_edit.html",
        request=request,
        context={
            "current_user": ctx.user,
            "current_company": ctx.company,
            "role": ctx.membership.role,
            "current_client": current_client,
            "item": item,
        },
    )


@app.post("/pendencias/{item_id}/editar")
@require_role({"admin", "equipe"})
async def pending_edit_action(
        request: Request,
        session: Session = Depends(get_session),
        item_id: int = 0,
        title: str = Form(...),
        description: str = Form(""),
        due_date: str = Form(""),
        status: str = Form("aberto"),
) -> Response:
    ctx = get_tenant_context(request, session)
    assert ctx is not None

    # Garante tabela em ambientes sem Alembic
    if not ensure_credit_consent_table():
        set_flash(request, "Sistema de aceite não está configurado (migração pendente no banco).")
        return RedirectResponse("/credito", status_code=303)

    item = session.get(PendingItem, int(item_id))
    if not item or item.company_id != ctx.company.id:
        set_flash(request, "Pendência não encontrada.")
        return RedirectResponse("/pendencias", status_code=303)

    item.title = title.strip()
    item.description = description.strip()
    item.due_date = due_date.strip()
    item.status = status.strip().lower()
    item.updated_at = utcnow()
    session.add(item)
    session.commit()

    set_flash(request, "Pendência atualizada.")
    return RedirectResponse(f"/pendencias/{item.id}", status_code=303)


@app.post("/pendencias/{item_id}/excluir")
@require_role({"admin", "equipe"})
async def pending_delete_action(request: Request, session: Session = Depends(get_session),
                                item_id: int = 0) -> Response:
    ctx = get_tenant_context(request, session)
    assert ctx is not None

    # Garante tabela em ambientes sem Alembic
    if not ensure_credit_consent_table():
        set_flash(request, "Sistema de aceite não está configurado (migração pendente no banco).")
        return RedirectResponse("/credito", status_code=303)

    item = session.get(PendingItem, int(item_id))
    if not item or item.company_id != ctx.company.id:
        set_flash(request, "Pendência não encontrada.")
        return RedirectResponse("/pendencias", status_code=303)

    atts = session.exec(select(Attachment).where(Attachment.pending_item_id == item.id)).all()
    if atts:
        set_flash(request, "Remova os anexos antes de excluir a pendência.")
        return RedirectResponse(f"/pendencias/{item.id}", status_code=303)

    msgs = session.exec(select(PendingMessage).where(PendingMessage.pending_item_id == item.id)).all()
    for m in msgs:
        session.delete(m)

    session.delete(item)
    session.commit()

    set_flash(request, "Pendência excluída.")
    return RedirectResponse("/pendencias", status_code=303)


@app.get("/financeiro/{inv_id}/editar", response_class=HTMLResponse)
@require_role({"admin", "equipe"})
async def fin_edit_page(request: Request, session: Session = Depends(get_session), inv_id: int = 0) -> HTMLResponse:
    ctx = get_tenant_context(request, session)
    assert ctx is not None

    # Garante tabela em ambientes sem Alembic
    if not ensure_credit_consent_table():
        set_flash(request, "Sistema de aceite não está configurado (migração pendente no banco).")
        return RedirectResponse("/credito", status_code=303)

    inv = session.get(FinanceInvoice, int(inv_id))
    if not inv or inv.company_id != ctx.company.id:
        return render("error.html", request=request, context={"message": "Lançamento não encontrado."}, status_code=404)

    active_client_id = get_active_client_id(request, session, ctx)
    current_client = get_client_or_none(session, ctx.company.id, active_client_id)

    return render(
        "fin_edit.html",
        request=request,
        context={
            "current_user": ctx.user,
            "current_company": ctx.company,
            "role": ctx.membership.role,
            "current_client": current_client,
            "inv": inv,
        },
    )


@app.post("/financeiro/{inv_id}/editar")
@require_role({"admin", "equipe"})
async def fin_edit_action(
        request: Request,
        session: Session = Depends(get_session),
        inv_id: int = 0,
        title: str = Form(...),
        status: str = Form("emitido"),
        amount_brl: float = Form(0.0),
        due_date: str = Form(""),
        notes: str = Form(""),
) -> Response:
    ctx = get_tenant_context(request, session)
    assert ctx is not None

    # Garante tabela em ambientes sem Alembic
    if not ensure_credit_consent_table():
        set_flash(request, "Sistema de aceite não está configurado (migração pendente no banco).")
        return RedirectResponse("/credito", status_code=303)

    inv = session.get(FinanceInvoice, int(inv_id))
    if not inv or inv.company_id != ctx.company.id:
        set_flash(request, "Lançamento não encontrado.")
        return RedirectResponse("/financeiro", status_code=303)

    inv.title = title.strip()
    inv.status = status.strip().lower()
    inv.amount_brl = max(0.0, float(amount_brl))
    inv.due_date = due_date.strip()
    inv.notes = notes.strip()
    inv.updated_at = utcnow()
    session.add(inv)
    session.commit()

    set_flash(request, "Financeiro atualizado.")
    return RedirectResponse(f"/financeiro/{inv.id}", status_code=303)


@app.post("/financeiro/{inv_id}/excluir")
@require_role({"admin", "equipe"})
async def fin_delete_action(request: Request, session: Session = Depends(get_session), inv_id: int = 0) -> Response:
    ctx = get_tenant_context(request, session)
    assert ctx is not None

    # Garante tabela em ambientes sem Alembic
    if not ensure_credit_consent_table():
        set_flash(request, "Sistema de aceite não está configurado (migração pendente no banco).")
        return RedirectResponse("/credito", status_code=303)

    inv = session.get(FinanceInvoice, int(inv_id))
    if not inv or inv.company_id != ctx.company.id:
        set_flash(request, "Lançamento não encontrado.")
        return RedirectResponse("/financeiro", status_code=303)

    atts = session.exec(select(Attachment).where(Attachment.finance_invoice_id == inv.id)).all()
    if atts:
        set_flash(request, "Remova os anexos antes de excluir o lançamento.")
        return RedirectResponse(f"/financeiro/{inv.id}", status_code=303)

    session.delete(inv)
    session.commit()

    set_flash(request, "Lançamento excluído.")
    return RedirectResponse("/financeiro", status_code=303)


# ----------------------------
# CRM routes (Negócios)
# ----------------------------

def _crm_stage_label(stage_key: str) -> str:
    for s in CRM_STAGES:
        if s["key"] == stage_key:
            return s["label"]
    return stage_key or "—"


def _crm_stage_key_or_default(stage_key: str) -> str:
    k = (stage_key or "").strip().lower()
    return k if k in CRM_STAGE_KEYS else "qualificacao"


def _owner_users_for_company(session: Session, company_id: int) -> list[dict[str, Any]]:
    members = session.exec(select(Membership).where(Membership.company_id == company_id)).all()
    out = []
    seen = set()
    for m in members:
        if m.user_id in seen:
            continue
        u = session.get(User, m.user_id)
        if u:
            out.append({"id": u.id, "name": u.name})
            seen.add(u.id)
    out.sort(key=lambda x: x["name"].lower())
    return out


@app.get("/crm")
@require_role({"admin", "equipe"})
async def crm_alias() -> Response:
    return RedirectResponse("/negocios", status_code=303)


@app.get("/negocios", response_class=HTMLResponse)
@require_role({"admin", "equipe"})
async def crm_list(
        request: Request,
        session: Session = Depends(get_session),
        client_id: int = 0,
        owner_user_id: int = 0,
        stage: str = "",
) -> HTMLResponse:
    ctx = get_tenant_context(request, session)
    assert ctx is not None

    # Garante tabela em ambientes sem Alembic
    if not ensure_credit_consent_table():
        set_flash(request, "Sistema de aceite não está configurado (migração pendente no banco).")
        return RedirectResponse("/credito", status_code=303)

    clients = session.exec(select(Client).where(Client.company_id == ctx.company.id).order_by(Client.created_at)).all()
    owners = _owner_users_for_company(session, ctx.company.id)

    q = select(BusinessDeal).where(BusinessDeal.company_id == ctx.company.id).order_by(BusinessDeal.updated_at.desc())

    filter_client_id = int(client_id or 0)
    if filter_client_id > 0:
        c = get_client_or_none(session, ctx.company.id, filter_client_id)
        if not c:
            set_flash(request, "Cliente inválido para filtro.")
            return RedirectResponse("/negocios", status_code=303)
        q = q.where(BusinessDeal.client_id == c.id)

    filter_owner_user_id = int(owner_user_id or 0)
    if filter_owner_user_id == -1:
        q = q.where(BusinessDeal.owner_user_id.is_(None))
    elif filter_owner_user_id > 0:
        q = q.where(BusinessDeal.owner_user_id == filter_owner_user_id)

    filter_stage = (stage or "").strip().lower()
    if filter_stage:
        if filter_stage not in CRM_STAGE_KEYS:
            set_flash(request, "Etapa inválida para filtro.")
            return RedirectResponse("/negocios", status_code=303)
        q = q.where(BusinessDeal.stage == filter_stage)

    deals = session.exec(q).all()

    client_name_by_id = {c.id: c.name for c in clients}
    owner_name_by_id = {o["id"]: o["name"] for o in owners}

    by_stage: dict[str, list[dict[str, Any]]] = {s["key"]: [] for s in CRM_STAGES}
    for d in deals:
        by_stage.setdefault(d.stage, [])
        by_stage[d.stage].append(
            {
                "id": d.id,
                "title": d.title,
                "client_name": client_name_by_id.get(d.client_id, "—"),
                "owner_name": owner_name_by_id.get(d.owner_user_id or 0, ""),
                "service_name": d.service_name,
                "next_step_date": d.next_step_date,
                "value_estimate_brl": d.value_estimate_brl,
            }
        )

    columns = []
    for s in CRM_STAGES:
        lst = by_stage.get(s["key"], [])
        columns.append({"key": s["key"], "label": s["label"], "deals": lst, "count": len(lst)})

    active_client_id = get_active_client_id(request, session, ctx)
    current_client = get_client_or_none(session, ctx.company.id, active_client_id)

    return render(
        "crm_list.html",
        request=request,
        context={
            "current_user": ctx.user,
            "current_company": ctx.company,
            "role": ctx.membership.role,
            "current_client": current_client,
            "clients": clients,
            "owners": owners,
            "stages": CRM_STAGES,
            "columns": columns,
            "filter_client_id": filter_client_id,
            "filter_owner_user_id": filter_owner_user_id,
            "filter_stage": filter_stage,
        },
    )


@app.get("/negocios/novo", response_class=HTMLResponse)
@require_role({"admin", "equipe"})
async def crm_new_page(request: Request, session: Session = Depends(get_session)) -> HTMLResponse:
    ctx = get_tenant_context(request, session)
    assert ctx is not None

    # Garante tabela em ambientes sem Alembic
    if not ensure_credit_consent_table():
        set_flash(request, "Sistema de aceite não está configurado (migração pendente no banco).")
        return RedirectResponse("/credito", status_code=303)

    clients = session.exec(select(Client).where(Client.company_id == ctx.company.id).order_by(Client.created_at)).all()
    owners = _owner_users_for_company(session, ctx.company.id)

    # Permite abrir a tela mesmo sem clientes cadastrados (para criar Lead no CRM).

    active_client_id = get_active_client_id(request, session, ctx)
    current_client = get_client_or_none(session, ctx.company.id, active_client_id)

    return render(
        "crm_new.html",
        request=request,
        context={
            "current_user": ctx.user,
            "current_company": ctx.company,
            "role": ctx.membership.role,
            "current_client": current_client,
            "clients": clients,
            "owners": owners,
            "stages": CRM_STAGES,
        },
    )


@app.post("/negocios/novo")
@require_role({"admin", "equipe"})
async def crm_new_action(
        request: Request,
        session: Session = Depends(get_session),

        client_id: int = Form(0),
        new_client_name: str = Form(""),
        new_client_cnpj: str = Form(""),
        new_client_email: str = Form(""),
        new_client_phone: str = Form(""),
        new_client_notes: str = Form(""),

        owner_user_id: int = Form(0),
        title: str = Form(...),
        service_name: str = Form(""),
        stage: str = Form("qualificacao"),
        demand: str = Form(""),
        notes: str = Form(""),
        value_estimate_brl: float = Form(0.0),
        probability_pct: int = Form(0),
        source: str = Form(""),
        next_step: str = Form(""),
        next_step_date: str = Form(""),
) -> Response:
    ctx = get_tenant_context(request, session)
    assert ctx is not None

    # Garante tabela em ambientes sem Alembic
    if not ensure_credit_consent_table():
        set_flash(request, "Sistema de aceite não está configurado (migração pendente no banco).")
        return RedirectResponse("/credito", status_code=303)

    new_client_name = (new_client_name or "").strip()
    new_client_email = (new_client_email or "").strip()
    new_client_phone = (new_client_phone or "").strip()
    new_client_notes = (new_client_notes or "").strip()
    new_client_cnpj_norm = re.sub(r"\D+", "", (new_client_cnpj or "")).strip()

    if new_client_name:
        lead_notes = f"[LEAD CRM] {new_client_notes}".strip()
        client = Client(
            company_id=ctx.company.id,
            name=new_client_name,
            cnpj=new_client_cnpj_norm,
            email=new_client_email,
            phone=new_client_phone,
            notes=lead_notes,
            updated_at=utcnow(),
        )
        session.add(client)
        session.commit()
        session.refresh(client)
    else:
        if int(client_id or 0) <= 0:
            set_flash(request, "Selecione um cliente existente OU crie um lead.")
            return RedirectResponse("/negocios/novo", status_code=303)

        client = get_client_or_none(session, ctx.company.id, int(client_id))
        if not client:
            set_flash(request, "Cliente inválido.")
            return RedirectResponse("/negocios/novo", status_code=303)

    service_name = sanitize_service_name(service_name)
    if not service_name:
        set_flash(request, "Selecione um serviço/produto.")
        return RedirectResponse("/negocios/novo", status_code=303)

    stage = _crm_stage_key_or_default(stage)

    ouid = int(owner_user_id or 0)
    owner = None
    if ouid > 0:
        owner = session.get(User, ouid)
        if not owner:
            set_flash(request, "Responsável inválido.")
            return RedirectResponse("/negocios/novo", status_code=303)

    prob = max(0, min(100, int(probability_pct or 0)))

    deal = BusinessDeal(
        company_id=ctx.company.id,
        client_id=client.id,
        created_by_user_id=ctx.user.id,
        owner_user_id=(owner.id if owner else None),
        title=title.strip(),
        demand=demand.strip(),
        notes=notes.strip(),
        stage=stage,
        service_name=service_name,
        value_estimate_brl=max(0.0, float(value_estimate_brl)),
        probability_pct=prob,
        next_step=next_step.strip(),
        next_step_date=next_step_date.strip(),
        source=source.strip(),
        updated_at=utcnow(),
    )
    session.add(deal)
    session.commit()
    session.refresh(deal)

    session.add(BusinessDealNote(deal_id=deal.id, author_user_id=ctx.user.id, message="Negócio criado."))
    session.commit()

    set_flash(request, "Negócio criado.")
    return RedirectResponse(f"/negocios/{deal.id}", status_code=303)


@app.get("/negocios/{deal_id}", response_class=HTMLResponse)
@require_role({"admin", "equipe"})
async def crm_detail(request: Request, session: Session = Depends(get_session), deal_id: int = 0) -> HTMLResponse:
    ctx = get_tenant_context(request, session)
    assert ctx is not None

    # Garante tabela em ambientes sem Alembic
    if not ensure_credit_consent_table():
        set_flash(request, "Sistema de aceite não está configurado (migração pendente no banco).")
        return RedirectResponse("/credito", status_code=303)

    deal = session.get(BusinessDeal, int(deal_id))
    if not deal or deal.company_id != ctx.company.id:
        return render("error.html", request=request, context={"message": "Negócio não encontrado."}, status_code=404)

    client = session.get(Client, deal.client_id)
    owner = session.get(User, deal.owner_user_id) if deal.owner_user_id else None

    notes = session.exec(
        select(BusinessDealNote).where(BusinessDealNote.deal_id == deal.id).order_by(BusinessDealNote.created_at.desc())
    ).all()

    note_view = []
    for n in notes:
        au = session.get(User, n.author_user_id)
        note_view.append(
            {"id": n.id, "message": n.message, "created_at": n.created_at, "author_name": au.name if au else "—"})

    active_client_id = get_active_client_id(request, session, ctx)
    current_client = get_client_or_none(session, ctx.company.id, active_client_id)

    return render(
        "crm_detail.html",
        request=request,
        context={
            "current_user": ctx.user,
            "current_company": ctx.company,
            "role": ctx.membership.role,
            "current_client": current_client,
            "deal": deal,
            "client": client,
            "owner_name": owner.name if owner else "",
            "stage_label": _crm_stage_label(deal.stage),
            "stages": CRM_STAGES,
            "notes": note_view,
        },
    )


@app.get("/negocios/{deal_id}/editar", response_class=HTMLResponse)
@require_role({"admin", "equipe"})
async def crm_edit_page(request: Request, session: Session = Depends(get_session), deal_id: int = 0) -> HTMLResponse:
    ctx = get_tenant_context(request, session)
    assert ctx is not None

    # Garante tabela em ambientes sem Alembic
    if not ensure_credit_consent_table():
        set_flash(request, "Sistema de aceite não está configurado (migração pendente no banco).")
        return RedirectResponse("/credito", status_code=303)

    deal = session.get(BusinessDeal, int(deal_id))
    if not deal or deal.company_id != ctx.company.id:
        return render("error.html", request=request, context={"message": "Negócio não encontrado."}, status_code=404)

    clients = session.exec(select(Client).where(Client.company_id == ctx.company.id).order_by(Client.created_at)).all()
    owners = _owner_users_for_company(session, ctx.company.id)

    active_client_id = get_active_client_id(request, session, ctx)
    current_client = get_client_or_none(session, ctx.company.id, active_client_id)

    return render(
        "crm_edit.html",
        request=request,
        context={
            "current_user": ctx.user,
            "current_company": ctx.company,
            "role": ctx.membership.role,
            "current_client": current_client,
            "deal": deal,
            "clients": clients,
            "owners": owners,
            "stages": CRM_STAGES,
        },
    )


@app.post("/negocios/{deal_id}/editar")
@require_role({"admin", "equipe"})
async def crm_edit_action(
        request: Request,
        session: Session = Depends(get_session),
        deal_id: int = 0,
        client_id: int = Form(...),
        owner_user_id: int = Form(0),
        title: str = Form(...),
        service_name: str = Form(""),
        stage: str = Form("qualificacao"),
        demand: str = Form(""),
        notes: str = Form(""),
        value_estimate_brl: float = Form(0.0),
        probability_pct: int = Form(0),
        source: str = Form(""),
        next_step: str = Form(""),
        next_step_date: str = Form(""),
) -> Response:
    ctx = get_tenant_context(request, session)
    assert ctx is not None

    # Garante tabela em ambientes sem Alembic
    if not ensure_credit_consent_table():
        set_flash(request, "Sistema de aceite não está configurado (migração pendente no banco).")
        return RedirectResponse("/credito", status_code=303)

    deal = session.get(BusinessDeal, int(deal_id))
    if not deal or deal.company_id != ctx.company.id:
        set_flash(request, "Negócio não encontrado.")
        return RedirectResponse("/negocios", status_code=303)

    client = get_client_or_none(session, ctx.company.id, int(client_id))
    if not client:
        set_flash(request, "Cliente inválido.")
        return RedirectResponse(f"/negocios/{deal.id}/editar", status_code=303)

    service_name = sanitize_service_name(service_name)
    if not service_name:
        set_flash(request, "Selecione um serviço/produto.")
        return RedirectResponse(f"/negocios/{deal.id}/editar", status_code=303)

    stage = _crm_stage_key_or_default(stage)

    ouid = int(owner_user_id or 0)
    owner_id = None
    if ouid > 0:
        ou = session.get(User, ouid)
        if not ou:
            set_flash(request, "Responsável inválido.")
            return RedirectResponse(f"/negocios/{deal.id}/editar", status_code=303)
        owner_id = ou.id

    deal.client_id = client.id
    deal.owner_user_id = owner_id
    deal.title = title.strip()
    deal.service_name = service_name
    deal.stage = stage
    deal.demand = demand.strip()
    deal.notes = notes.strip()
    deal.value_estimate_brl = max(0.0, float(value_estimate_brl))
    deal.probability_pct = max(0, min(100, int(probability_pct or 0)))
    deal.source = source.strip()
    deal.next_step = next_step.strip()
    deal.next_step_date = next_step_date.strip()
    deal.updated_at = utcnow()
    session.add(deal)
    session.commit()

    session.add(BusinessDealNote(deal_id=deal.id, author_user_id=ctx.user.id, message="Negócio atualizado."))
    session.commit()

    set_flash(request, "Negócio atualizado.")
    return RedirectResponse(f"/negocios/{deal.id}", status_code=303)


@app.post("/negocios/{deal_id}/stage")
@require_role({"admin", "equipe"})
async def crm_update_stage(
        request: Request,
        session: Session = Depends(get_session),
        deal_id: int = 0,
        stage: str = Form(""),
) -> Response:
    ctx = get_tenant_context(request, session)
    assert ctx is not None

    # Garante tabela em ambientes sem Alembic
    if not ensure_credit_consent_table():
        set_flash(request, "Sistema de aceite não está configurado (migração pendente no banco).")
        return RedirectResponse("/credito", status_code=303)

    deal = session.get(BusinessDeal, int(deal_id))
    if not deal or deal.company_id != ctx.company.id:
        set_flash(request, "Negócio não encontrado.")
        return RedirectResponse("/negocios", status_code=303)

    deal.stage = _crm_stage_key_or_default(stage)
    deal.updated_at = utcnow()
    session.add(deal)
    session.commit()

    session.add(BusinessDealNote(deal_id=deal.id, author_user_id=ctx.user.id,
                                 message=f"Etapa alterada para: {_crm_stage_label(deal.stage)}."))
    session.commit()

    return RedirectResponse(f"/negocios/{deal.id}", status_code=303)


@app.post("/negocios/{deal_id}/next")
@require_role({"admin", "equipe"})
async def crm_update_next(
        request: Request,
        session: Session = Depends(get_session),
        deal_id: int = 0,
        next_step: str = Form(""),
        next_step_date: str = Form(""),
) -> Response:
    ctx = get_tenant_context(request, session)
    assert ctx is not None

    # Garante tabela em ambientes sem Alembic
    if not ensure_credit_consent_table():
        set_flash(request, "Sistema de aceite não está configurado (migração pendente no banco).")
        return RedirectResponse("/credito", status_code=303)

    deal = session.get(BusinessDeal, int(deal_id))
    if not deal or deal.company_id != ctx.company.id:
        set_flash(request, "Negócio não encontrado.")
        return RedirectResponse("/negocios", status_code=303)

    deal.next_step = (next_step or "").strip()
    deal.next_step_date = (next_step_date or "").strip()
    deal.updated_at = utcnow()
    session.add(deal)
    session.commit()

    session.add(BusinessDealNote(deal_id=deal.id, author_user_id=ctx.user.id, message="Próximo passo atualizado."))
    session.commit()

    return RedirectResponse(f"/negocios/{deal.id}", status_code=303)


@app.post("/negocios/{deal_id}/nota")
@require_role({"admin", "equipe"})
async def crm_add_note(
        request: Request,
        session: Session = Depends(get_session),
        deal_id: int = 0,
        message: str = Form(...),
) -> Response:
    ctx = get_tenant_context(request, session)
    assert ctx is not None

    # Garante tabela em ambientes sem Alembic
    if not ensure_credit_consent_table():
        set_flash(request, "Sistema de aceite não está configurado (migração pendente no banco).")
        return RedirectResponse("/credito", status_code=303)

    deal = session.get(BusinessDeal, int(deal_id))
    if not deal or deal.company_id != ctx.company.id:
        set_flash(request, "Negócio não encontrado.")
        return RedirectResponse("/negocios", status_code=303)

    msg = (message or "").strip()
    if not msg:
        return RedirectResponse(f"/negocios/{deal.id}", status_code=303)

    session.add(BusinessDealNote(deal_id=deal.id, author_user_id=ctx.user.id, message=msg))
    deal.updated_at = utcnow()
    session.add(deal)
    session.commit()

    return RedirectResponse(f"/negocios/{deal.id}", status_code=303)


@app.post("/negocios/{deal_id}/criar-proposta")
@require_role({"admin", "equipe"})
async def crm_create_proposal(request: Request, session: Session = Depends(get_session), deal_id: int = 0) -> Response:
    ctx = get_tenant_context(request, session)
    assert ctx is not None

    # Garante tabela em ambientes sem Alembic
    if not ensure_credit_consent_table():
        set_flash(request, "Sistema de aceite não está configurado (migração pendente no banco).")
        return RedirectResponse("/credito", status_code=303)

    deal = session.get(BusinessDeal, int(deal_id))
    if not deal or deal.company_id != ctx.company.id:
        set_flash(request, "Negócio não encontrado.")
        return RedirectResponse("/negocios", status_code=303)

    if deal.proposal_id:
        return RedirectResponse(f"/propostas/{deal.proposal_id}", status_code=303)

    prop = Proposal(
        company_id=ctx.company.id,
        client_id=deal.client_id,
        created_by_user_id=ctx.user.id,
        kind="proposta",
        title=deal.title,
        description=deal.demand or deal.notes,
        service_name=deal.service_name,
        value_brl=max(0.0, float(deal.value_estimate_brl)),
        status="rascunho",
        created_at=utcnow(),
        updated_at=utcnow(),
    )
    session.add(prop)
    session.commit()
    session.refresh(prop)

    deal.proposal_id = prop.id
    deal.updated_at = utcnow()
    session.add(deal)
    session.add(BusinessDealNote(deal_id=deal.id, author_user_id=ctx.user.id, message=f"Proposta criada (#{prop.id})."))
    session.commit()

    set_flash(request, "Proposta criada.")
    return RedirectResponse(f"/propostas/{prop.id}", status_code=303)


@app.post("/negocios/{deal_id}/criar-projeto")
@require_role({"admin", "equipe"})
async def crm_create_project(request: Request, session: Session = Depends(get_session), deal_id: int = 0) -> Response:
    ctx = get_tenant_context(request, session)
    assert ctx is not None

    # Garante tabela em ambientes sem Alembic
    if not ensure_credit_consent_table():
        set_flash(request, "Sistema de aceite não está configurado (migração pendente no banco).")
        return RedirectResponse("/credito", status_code=303)

    deal = session.get(BusinessDeal, int(deal_id))
    if not deal or deal.company_id != ctx.company.id:
        set_flash(request, "Negócio não encontrado.")
        return RedirectResponse("/negocios", status_code=303)

    if deal.consulting_project_id:
        return RedirectResponse(f"/consultoria/{deal.consulting_project_id}", status_code=303)

    proj = ConsultingProject(
        company_id=ctx.company.id,
        client_id=deal.client_id,
        created_by_user_id=ctx.user.id,
        name=deal.title,
        description=deal.demand or deal.notes,
        status="ativo",
        start_date="",
        due_date="",
        updated_at=utcnow(),
    )
    session.add(proj)
    session.commit()
    session.refresh(proj)

    deal.consulting_project_id = proj.id
    deal.updated_at = utcnow()
    session.add(deal)
    session.add(BusinessDealNote(deal_id=deal.id, author_user_id=ctx.user.id, message=f"Projeto criado (#{proj.id})."))
    session.commit()

    set_flash(request, "Projeto criado.")
    return RedirectResponse(f"/consultoria/{proj.id}", status_code=303)


@app.post("/negocios/{deal_id}/excluir")
@require_role({"admin", "equipe"})
async def crm_delete(request: Request, session: Session = Depends(get_session), deal_id: int = 0,
                     confirm: str = Form("")) -> Response:
    ctx = get_tenant_context(request, session)
    assert ctx is not None

    # Garante tabela em ambientes sem Alembic
    if not ensure_credit_consent_table():
        set_flash(request, "Sistema de aceite não está configurado (migração pendente no banco).")
        return RedirectResponse("/credito", status_code=303)

    deal = session.get(BusinessDeal, int(deal_id))
    if not deal or deal.company_id != ctx.company.id:
        set_flash(request, "Negócio não encontrado.")
        return RedirectResponse("/negocios", status_code=303)

    if (confirm or "").strip().upper() != "EXCLUIR":
        set_flash(request, "Confirmação inválida. Digite EXCLUIR.")
        return RedirectResponse(f"/negocios/{deal.id}", status_code=303)

    session.exec(delete(BusinessDealNote).where(BusinessDealNote.deal_id == deal.id))
    session.exec(delete(BusinessDeal).where(BusinessDeal.id == deal.id))
    session.commit()

    set_flash(request, "Negócio excluído.")
    return RedirectResponse("/negocios", status_code=303)


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


# =========================
# Meetings routes
# =========================

@app.get("/reunioes", response_class=HTMLResponse)
@require_login
async def meetings_list(
        request: Request,
        session: Session = Depends(get_session),
        client_id: int = 0,
) -> HTMLResponse:
    ctx = get_tenant_context(request, session)
    if not ctx:
        request.session.clear()
        return RedirectResponse("/login", status_code=303)

    active_client_id = get_active_client_id(request, session, ctx)
    current_client = get_client_or_none(session, ctx.company.id, active_client_id)

    q = select(Meeting).where(Meeting.company_id == ctx.company.id).order_by(Meeting.created_at.desc())

    clients: list[Client] = []
    filter_client_id = 0

    if ctx.membership.role == "cliente":
        q = q.where(Meeting.client_id == (ctx.membership.client_id or -1))
    else:
        clients = session.exec(
            select(Client).where(Client.company_id == ctx.company.id).order_by(Client.created_at)).all()
        if client_id and client_id > 0:
            fc = get_client_or_none(session, ctx.company.id, int(client_id))
            if not fc:
                set_flash(request, "Cliente inválido.")
                return RedirectResponse("/reunioes", status_code=303)
            filter_client_id = fc.id
            q = q.where(Meeting.client_id == fc.id)

    meetings = session.exec(q).all()
    out = []
    for m in meetings:
        c = session.get(Client, m.client_id)
        out.append(
            {
                "id": m.id,
                "title": m.title,
                "meeting_date": m.meeting_date,
                "notion_status": m.notion_status,
                "last_synced_at": m.last_synced_at.isoformat(timespec="minutes") if m.last_synced_at else "",
                "client_name": c.name if c else "—",
            }
        )

    return render(
        "meetings_list.html",
        request=request,
        context={
            "current_user": ctx.user,
            "current_company": ctx.company,
            "role": ctx.membership.role,
            "current_client": current_client,
            "clients": clients,
            "filter_client_id": filter_client_id,
            "meetings": out,
        },
    )


@app.get("/reunioes/nova", response_class=HTMLResponse)
@require_role({"admin", "equipe"})
async def meetings_new_page(request: Request, session: Session = Depends(get_session)) -> HTMLResponse:
    ctx = get_tenant_context(request, session)
    assert ctx is not None

    # Garante tabela em ambientes sem Alembic
    if not ensure_credit_consent_table():
        set_flash(request, "Sistema de aceite não está configurado (migração pendente no banco).")
        return RedirectResponse("/credito", status_code=303)

    clients = session.exec(select(Client).where(Client.company_id == ctx.company.id).order_by(Client.created_at)).all()
    active_client_id = get_active_client_id(request, session, ctx)
    current_client = get_client_or_none(session, ctx.company.id, active_client_id)

    return render(
        "meetings_new.html",
        request=request,
        context={
            "current_user": ctx.user,
            "current_company": ctx.company,
            "role": ctx.membership.role,
            "current_client": current_client,
            "clients": clients,
            "notion_enabled": bool(NOTION_TOKEN),
        },
    )


@app.post("/reunioes/nova")
@require_role({"admin", "equipe"})
async def meetings_new_action(
        request: Request,
        session: Session = Depends(get_session),
        client_id: int = Form(...),
        meeting_date: str = Form(""),
        notion_page: str = Form(...),
        title: str = Form(""),
        sync_now: str = Form(""),
) -> Response:
    ctx = get_tenant_context(request, session)
    assert ctx is not None

    # Garante tabela em ambientes sem Alembic
    if not ensure_credit_consent_table():
        set_flash(request, "Sistema de aceite não está configurado (migração pendente no banco).")
        return RedirectResponse("/credito", status_code=303)

    client = get_client_or_none(session, ctx.company.id, int(client_id))
    if not client:
        set_flash(request, "Cliente inválido.")
        return RedirectResponse("/reunioes/nova", status_code=303)

    page_id = _normalize_uuid(notion_page)
    if not page_id:
        set_flash(request, "Link/ID do Notion inválido.")
        return RedirectResponse("/reunioes/nova", status_code=303)

    mt = Meeting(
        company_id=ctx.company.id,
        client_id=client.id,
        created_by_user_id=ctx.user.id,
        title=title.strip(),
        meeting_date=meeting_date.strip(),
        notion_page_id=page_id,
        notion_url=notion_page.strip(),
        updated_at=utcnow(),
    )
    session.add(mt)
    session.commit()
    session.refresh(mt)

    if sync_now == "1":
        try:
            data = await notion_sync_meeting_from_page(page_id)
            mt.title = mt.title or data.get("title", "") or "Reunião"
            mt.notion_meeting_block_id = data.get("meeting_block_id", "") or ""
            mt.notion_status = data.get("status", "") or ""
            mt.summary_text = data.get("summary_text", "") or ""
            mt.notes_text = data.get("notes_text", "") or ""
            mt.transcript_text = data.get("transcript_text", "") or ""
            mt.action_items_text = data.get("action_items_text", "") or ""
            mt.raw_json = json.dumps(data.get("raw", {}), ensure_ascii=False)
            mt.last_synced_at = utcnow()
            mt.updated_at = utcnow()
            session.add(mt)
            session.commit()
            set_flash(request, "Reunião criada e sincronizada.")
        except Exception as e:
            set_flash(request, f"Reunião criada, mas falhou ao sincronizar: {e}")

    return RedirectResponse(f"/reunioes/{mt.id}", status_code=303)


@app.get("/reunioes/{meeting_id}", response_class=HTMLResponse)
@require_login
async def meetings_detail(request: Request, session: Session = Depends(get_session),
                          meeting_id: int = 0) -> HTMLResponse:
    ctx = get_tenant_context(request, session)
    if not ctx:
        request.session.clear()
        return RedirectResponse("/login", status_code=303)

    mt = session.get(Meeting, int(meeting_id))
    if not mt or mt.company_id != ctx.company.id:
        return render("error.html", request=request, context={"message": "Reunião não encontrada."}, status_code=404)

    if not ensure_can_access_client(ctx, mt.client_id):
        return render("error.html", request=request, context={"message": "Sem permissão."}, status_code=403)

    client = session.get(Client, mt.client_id)

    # assignees for task generation
    assignees = []
    if ctx.membership.role in {"admin", "equipe"}:
        memberships = session.exec(select(Membership).where(Membership.company_id == ctx.company.id)).all()
        for m in memberships:
            u = session.get(User, m.user_id)
            if u:
                assignees.append({"id": u.id, "name": u.name, "role": m.role})

    active_client_id = get_active_client_id(request, session, ctx)
    current_client = get_client_or_none(session, ctx.company.id, active_client_id)

    return render(
        "meetings_detail.html",
        request=request,
        context={
            "current_user": ctx.user,
            "current_company": ctx.company,
            "role": ctx.membership.role,
            "current_client": current_client,
            "meeting": mt,
            "client": client,
            "assignees": assignees,
        },
    )


@app.post("/reunioes/{meeting_id}/sync")
@require_role({"admin", "equipe"})
async def meetings_sync(request: Request, session: Session = Depends(get_session), meeting_id: int = 0) -> Response:
    ctx = get_tenant_context(request, session)
    assert ctx is not None

    # Garante tabela em ambientes sem Alembic
    if not ensure_credit_consent_table():
        set_flash(request, "Sistema de aceite não está configurado (migração pendente no banco).")
        return RedirectResponse("/credito", status_code=303)

    mt = session.get(Meeting, int(meeting_id))
    if not mt or mt.company_id != ctx.company.id:
        set_flash(request, "Reunião não encontrada.")
        return RedirectResponse("/reunioes", status_code=303)

    try:
        data = await notion_sync_meeting_from_page(mt.notion_page_id or mt.notion_url)
        mt.title = mt.title or data.get("title", "") or "Reunião"
        mt.notion_meeting_block_id = data.get("meeting_block_id", "") or ""
        mt.notion_status = data.get("status", "") or ""
        mt.summary_text = data.get("summary_text", "") or ""
        mt.notes_text = data.get("notes_text", "") or ""
        mt.transcript_text = data.get("transcript_text", "") or ""
        mt.action_items_text = data.get("action_items_text", "") or ""
        mt.raw_json = json.dumps(data.get("raw", {}), ensure_ascii=False)
        mt.last_synced_at = utcnow()
        mt.updated_at = utcnow()
        session.add(mt)
        session.commit()
        set_flash(request, "Sincronização concluída.")
    except Exception as e:
        set_flash(request, f"Falha ao sincronizar: {e}")

    return RedirectResponse(f"/reunioes/{mt.id}", status_code=303)


@app.post("/reunioes/{meeting_id}/gerar_tarefas")
@require_role({"admin", "equipe"})
async def meetings_generate_tasks(
        request: Request,
        session: Session = Depends(get_session),
        meeting_id: int = 0,
        assignee_user_id: int = Form(0),
        visible_to_client: int = Form(0),
) -> Response:
    ctx = get_tenant_context(request, session)
    assert ctx is not None

    # Garante tabela em ambientes sem Alembic
    if not ensure_credit_consent_table():
        set_flash(request, "Sistema de aceite não está configurado (migração pendente no banco).")
        return RedirectResponse("/credito", status_code=303)

    mt = session.get(Meeting, int(meeting_id))
    if not mt or mt.company_id != ctx.company.id:
        set_flash(request, "Reunião não encontrada.")
        return RedirectResponse("/reunioes", status_code=303)

    lines = [ln.strip() for ln in (mt.action_items_text or "").splitlines() if ln.strip()]
    # remove heading markers/bullets
    cleaned: list[str] = []
    for ln in lines:
        ln = re.sub(r"^(\-|\d+\.|☐|☑)\s*", "", ln).strip()
        if ln:
            cleaned.append(ln)

    if not cleaned:
        set_flash(request, "Sem Action Items para gerar tarefas.")
        return RedirectResponse(f"/reunioes/{mt.id}", status_code=303)

    assignee = int(assignee_user_id) if assignee_user_id else 0
    vis = bool(int(visible_to_client)) if visible_to_client is not None else False

    created = 0
    for title in cleaned[:30]:
        t = Task(
            company_id=ctx.company.id,
            client_id=mt.client_id,
            created_by_user_id=ctx.user.id,
            assignee_user_id=assignee if assignee > 0 else None,
            title=title,
            description=f"Gerado da reunião #{mt.id}",
            status="nao_iniciada",
            priority="media",
            due_date="",
            visible_to_client=vis,
            client_action=vis,  # se visível, cliente pode marcar (ajuste se quiser)
            updated_at=utcnow(),
        )
        session.add(t)
        created += 1

    session.commit()
    set_flash(request, f"{created} tarefa(s) criada(s).")
    return RedirectResponse("/tarefas", status_code=303)


# ----------------------------
# Educação (Sprint 1)
# ----------------------------

class EducationCourse(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)

    company_id: int = Field(index=True, foreign_key="company.id")
    created_by_user_id: int = Field(index=True, foreign_key="user.id")

    title: str
    category: str = ""  # ex: "Onboarding", "Caixa", "Precificação"
    description: str = ""
    is_active: bool = Field(default=True, index=True)

    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)

    __table_args__ = (
        UniqueConstraint("company_id", "title", name="uq_education_course_company_title"),
    )


class EducationCourseAccess(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)

    company_id: int = Field(index=True, foreign_key="company.id")
    course_id: int = Field(index=True, foreign_key="educationcourse.id")
    client_id: int = Field(index=True, foreign_key="client.id")

    created_at: datetime = Field(default_factory=utcnow)

    __table_args__ = (
        UniqueConstraint("course_id", "client_id", name="uq_education_course_client"),
    )


class EducationModule(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)

    course_id: int = Field(index=True, foreign_key="educationcourse.id")
    title: str
    order: int = Field(default=1, index=True)
    description: str = ""

    created_at: datetime = Field(default_factory=utcnow)

    __table_args__ = (
        UniqueConstraint("course_id", "order", name="uq_education_module_order"),
    )


class EducationLesson(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)

    module_id: int = Field(index=True, foreign_key="educationmodule.id")
    title: str
    order: int = Field(default=1, index=True)

    video_url: str = ""
    description: str = ""

    created_at: datetime = Field(default_factory=utcnow)

    __table_args__ = (
        UniqueConstraint("module_id", "order", name="uq_education_lesson_order"),
    )


class EducationLessonProgress(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)

    company_id: int = Field(index=True, foreign_key="company.id")
    client_id: int = Field(index=True, foreign_key="client.id")
    lesson_id: int = Field(index=True, foreign_key="educationlesson.id")
    user_id: int = Field(index=True, foreign_key="user.id")

    completed: bool = Field(default=True, index=True)
    completed_at: datetime = Field(default_factory=utcnow)

    __table_args__ = (
        UniqueConstraint("lesson_id", "user_id", name="uq_education_lesson_user"),
    )


def _youtube_embed_url(url: str) -> str:
    u = (url or "").strip()
    if not u:
        return ""
    m = re.search(r"(?:youtube\.com/watch\?v=|youtu\.be/)([A-Za-z0-9_-]{6,})", u)
    if not m:
        return ""
    vid = m.group(1)
    return f"https://www.youtube-nocookie.com/embed/{vid}"


def _education_course_can_access(ctx: TenantContext, session: Session, course: EducationCourse) -> bool:
    if ctx.membership.role in {"admin", "equipe"}:
        return True
    if ctx.membership.role != "cliente":
        return False
    cid = ctx.membership.client_id or 0
    if not cid:
        return False
    access = session.exec(
        select(EducationCourseAccess).where(
            EducationCourseAccess.company_id == ctx.company.id,
            EducationCourseAccess.course_id == course.id,
            EducationCourseAccess.client_id == cid,
        )
    ).first()
    return bool(access)


def _education_course_assigned_clients(session: Session, course: EducationCourse) -> list[Client]:
    accesses = session.exec(
        select(EducationCourseAccess).where(EducationCourseAccess.course_id == course.id)
    ).all()
    client_ids = [a.client_id for a in accesses]
    if not client_ids:
        return []
    return session.exec(select(Client).where(Client.id.in_(client_ids))).all()


def _education_course_progress_pct(session: Session, company_id: int, client_id: int, user_id: int,
                                   course_id: int) -> int:
    module_ids = session.exec(
        select(EducationModule.id).where(EducationModule.course_id == course_id)
    ).all()
    if not module_ids:
        return 0
    lesson_ids = session.exec(
        select(EducationLesson.id).where(EducationLesson.module_id.in_(module_ids))
    ).all()
    if not lesson_ids:
        return 0
    total = len(lesson_ids)
    done = session.exec(
        select(func.count(EducationLessonProgress.id)).where(
            EducationLessonProgress.company_id == company_id,
            EducationLessonProgress.client_id == client_id,
            EducationLessonProgress.user_id == user_id,
            EducationLessonProgress.lesson_id.in_(lesson_ids),
        )
    ).one()
    done_n = int(done or 0)
    return int(round((done_n / total) * 100))


TEMPLATES.update({
    "edu_courses.html": r"""
{% extends "base.html" %}
{% block content %}
<div class="card p-4">
  <div class="d-flex justify-content-between align-items-center">
    <div>
      <h4 class="mb-0">Educação</h4>
      <div class="muted">Cursos, vídeos e materiais por cliente/necessidade.</div>
    </div>
    {% if role in ["admin","equipe"] %}
      <a class="btn btn-primary" href="/educacao/cursos/novo">Novo curso</a>
    {% endif %}
  </div>

  <hr class="my-3"/>

  {% if role in ["admin","equipe"] %}
    <form method="get" action="/educacao" class="row g-2 align-items-end mb-3">
      <div class="col-md-6">
        <label class="form-label">Filtro por cliente (opcional)</label>
        <select class="form-select" name="client_id" onchange="this.form.submit()">
          <option value="0" {% if filter_client_id==0 %}selected{% endif %}>Todos</option>
          {% for c in clients %}
            <option value="{{ c.id }}" {% if filter_client_id==c.id %}selected{% endif %}>{{ c.name }}</option>
          {% endfor %}
        </select>
      </div>
      <div class="col-md-6">
        {% if filter_client_id %}
          <a class="btn btn-outline-secondary" href="/educacao">Limpar</a>
        {% endif %}
      </div>
    </form>
  {% endif %}

  {% if courses %}
    <div class="list-group">
      {% for c in courses %}
        <a class="list-group-item list-group-item-action" href="/educacao/cursos/{{ c.id }}">
          <div class="d-flex justify-content-between">
            <div class="fw-semibold">{{ c.title }}</div>
            <span class="badge text-bg-light border">{{ c.category or "curso" }}</span>
          </div>
          <div class="muted small mt-1">
            {% if c.assigned_count is not none %}Clientes: {{ c.assigned_count }} • {% endif %}
            {% if c.progress_pct is not none %}Progresso: {{ c.progress_pct }}% • {% endif %}
            {% if not c.is_active %}Inativo{% else %}Ativo{% endif %}
          </div>
        </a>
      {% endfor %}
    </div>
  {% else %}
    <div class="muted">Nenhum curso disponível.</div>
  {% endif %}
</div>
{% endblock %}
""",

    "edu_course_new.html": r"""
{% extends "base.html" %}
{% block content %}
<div class="card p-4">
  <div class="d-flex justify-content-between align-items-center">
    <div>
      <h4 class="mb-0">Novo Curso</h4>
      <div class="muted">Crie um curso e libere para clientes específicos.</div>
    </div>
    <a class="btn btn-outline-secondary" href="/educacao">Voltar</a>
  </div>

  <hr class="my-3"/>

  <form method="post" action="/educacao/cursos/novo">
    <div class="row g-3">
      <div class="col-md-8">
        <label class="form-label">Título</label>
        <input class="form-control" name="title" required />
      </div>
      <div class="col-md-4">
        <label class="form-label">Categoria</label>
        <input class="form-control" name="category" placeholder="Onboarding, Caixa..." />
      </div>
      <div class="col-12">
        <label class="form-label">Descrição</label>
        <textarea class="form-control" name="description" rows="4"></textarea>
      </div>
      <div class="col-12">
        <div class="form-check">
          <input class="form-check-input" type="checkbox" name="is_active" value="1" checked id="active">
          <label class="form-check-label" for="active">Curso ativo</label>
        </div>
      </div>
    </div>

    <hr class="my-4"/>
    <h5>Liberar para clientes</h5>
    <div class="muted mb-2">Marque os clientes que poderão acessar este curso.</div>
    <div class="row g-2">
      {% for c in clients %}
        <div class="col-md-6">
          <div class="form-check">
            <input class="form-check-input" type="checkbox" name="client_ids" value="{{ c.id }}" id="c{{ c.id }}">
            <label class="form-check-label" for="c{{ c.id }}">{{ c.name }}</label>
          </div>
        </div>
      {% endfor %}
    </div>

    <div class="mt-4 d-flex gap-2">
      <button class="btn btn-primary" type="submit">Criar</button>
      <a class="btn btn-outline-secondary" href="/educacao">Cancelar</a>
    </div>
  </form>

  <hr class="my-4"/>
  <div class="alert alert-info mb-0">
    <b>Vídeos do YouTube:</b> para tocar dentro do app, o vídeo precisa estar <b>Público</b> ou <b>Não listado</b>.
    Vídeos <b>Privados</b> normalmente não embutem; nesse caso, o app abrirá o link em nova aba.
  </div>
</div>
{% endblock %}
""",

    "edu_course_detail.html": r"""
{% extends "base.html" %}
{% block content %}
<div class="card p-4">
  <div class="d-flex justify-content-between align-items-start">
    <div>
      <h4 class="mb-1">{{ course.title }}</h4>
      <div class="muted">
        Categoria: <b>{{ course.category or "—" }}</b> •
        Status: <b>{% if course.is_active %}ativo{% else %}inativo{% endif %}</b>
        {% if progress_pct is not none %} • Progresso: <b>{{ progress_pct }}%</b>{% endif %}
      </div>
    </div>
    <div class="d-flex gap-2">
      <a class="btn btn-outline-secondary" href="/educacao">Voltar</a>
      {% if role in ["admin","equipe"] %}
        <a class="btn btn-outline-primary" href="/educacao/cursos/{{ course.id }}/editar">Editar</a>
      {% endif %}
    </div>
  </div>

  {% if course.description %}
    <hr class="my-3"/>
    <pre>{{ course.description }}</pre>
  {% endif %}

  {% if role in ["admin","equipe"] %}
    <hr class="my-3"/>
    <div class="muted mb-2"><b>Clientes liberados:</b> {{ assigned_names or "—" }}</div>

    <form method="post" action="/educacao/cursos/{{ course.id }}/modulos" class="card p-3">
      <div class="fw-semibold mb-2">Adicionar módulo</div>
      <div class="row g-2">
        <div class="col-md-8">
          <input class="form-control" name="title" required placeholder="Ex: Módulo 1 - Caixa" />
        </div>
        <div class="col-md-4">
          <button class="btn btn-primary w-100" type="submit">Adicionar</button>
        </div>
        <div class="col-12">
          <input class="form-control" name="description" placeholder="Descrição (opcional)" />
        </div>
      </div>
    </form>
  {% endif %}

  <hr class="my-3"/>
  <h5 class="mb-2">Módulos</h5>

  {% if modules %}
    <div class="list-group">
      {% for m in modules %}
        <a class="list-group-item list-group-item-action" href="/educacao/modulos/{{ m.id }}">
          <div class="fw-semibold">{{ m.order }}. {{ m.title }}</div>
          <div class="muted small">{{ m.description }}</div>
        </a>
      {% endfor %}
    </div>
  {% else %}
    <div class="muted">Sem módulos ainda.</div>
  {% endif %}

  {% if role in ["admin","equipe"] %}
    <hr class="my-4"/>
    <form method="post" action="/educacao/cursos/{{ course.id }}/excluir"
          onsubmit="return confirm('Excluir curso? Remova módulos/aulas antes.');">
      <button class="btn btn-outline-danger" type="submit">Excluir curso</button>
    </form>
  {% endif %}
</div>
{% endblock %}
""",

    "edu_course_edit.html": r"""
{% extends "base.html" %}
{% block content %}
<div class="card p-4">
  <div class="d-flex justify-content-between align-items-start">
    <div>
      <h4 class="mb-1">Editar Curso</h4>
      <div class="muted">{{ course.title }}</div>
    </div>
    <a class="btn btn-outline-secondary" href="/educacao/cursos/{{ course.id }}">Voltar</a>
  </div>

  <hr class="my-3"/>

  <form method="post" action="/educacao/cursos/{{ course.id }}/editar">
    <div class="row g-3">
      <div class="col-md-8">
        <label class="form-label">Título</label>
        <input class="form-control" name="title" value="{{ course.title }}" required />
      </div>
      <div class="col-md-4">
        <label class="form-label">Categoria</label>
        <input class="form-control" name="category" value="{{ course.category }}" />
      </div>
      <div class="col-12">
        <label class="form-label">Descrição</label>
        <textarea class="form-control" name="description" rows="4">{{ course.description }}</textarea>
      </div>
      <div class="col-12">
        <div class="form-check">
          <input class="form-check-input" type="checkbox" name="is_active" value="1" id="active" {% if course.is_active %}checked{% endif %}>
          <label class="form-check-label" for="active">Curso ativo</label>
        </div>
      </div>
    </div>

    <hr class="my-4"/>
    <h5>Clientes liberados</h5>
    <div class="row g-2">
      {% for c in clients %}
        <div class="col-md-6">
          <div class="form-check">
            <input class="form-check-input" type="checkbox" name="client_ids" value="{{ c.id }}" id="c{{ c.id }}"
                   {% if c.id in assigned_ids %}checked{% endif %}>
            <label class="form-check-label" for="c{{ c.id }}">{{ c.name }}</label>
          </div>
        </div>
      {% endfor %}
    </div>

    <div class="mt-4 d-flex gap-2">
      <button class="btn btn-primary" type="submit">Salvar</button>
      <a class="btn btn-outline-secondary" href="/educacao/cursos/{{ course.id }}">Cancelar</a>
    </div>
  </form>
</div>
{% endblock %}
""",

    "edu_module_detail.html": r"""
{% extends "base.html" %}
{% block content %}
<div class="card p-4">
  <div class="d-flex justify-content-between align-items-start">
    <div>
      <h4 class="mb-1">{{ module.title }}</h4>
      <div class="muted">Curso: <a href="/educacao/cursos/{{ course.id }}">{{ course.title }}</a></div>
    </div>
    <a class="btn btn-outline-secondary" href="/educacao/cursos/{{ course.id }}">Voltar</a>
  </div>

  {% if module.description %}
    <hr class="my-3"/>
    <pre>{{ module.description }}</pre>
  {% endif %}

  {% if role in ["admin","equipe"] %}
    <hr class="my-3"/>
    <form method="post" action="/educacao/modulos/{{ module.id }}/aulas" class="card p-3">
      <div class="fw-semibold mb-2">Adicionar aula</div>
      <div class="row g-2">
        <div class="col-md-6">
          <input class="form-control" name="title" required placeholder="Título da aula" />
        </div>
        <div class="col-md-6">
          <input class="form-control" name="video_url" placeholder="URL do vídeo (YouTube / outro)" />
        </div>
        <div class="col-12">
          <textarea class="form-control" name="description" rows="3" placeholder="Descrição (opcional)"></textarea>
        </div>
        <div class="col-12">
          <button class="btn btn-primary" type="submit">Adicionar</button>
        </div>
      </div>
    </form>
  {% endif %}

  <hr class="my-3"/>
  <h5 class="mb-2">Aulas</h5>
  {% if lessons %}
    <div class="list-group">
      {% for l in lessons %}
        <a class="list-group-item list-group-item-action" href="/educacao/aulas/{{ l.id }}">
          <div class="fw-semibold">{{ l.order }}. {{ l.title }}</div>
          <div class="muted small">{% if l.video_url %}Vídeo configurado{% else %}Sem vídeo{% endif %}</div>
        </a>
      {% endfor %}
    </div>
  {% else %}
    <div class="muted">Sem aulas ainda.</div>
  {% endif %}

  {% if role in ["admin","equipe"] %}
    <hr class="my-4"/>
    <form method="post" action="/educacao/modulos/{{ module.id }}/editar" class="card p-3 mb-3">
      <div class="fw-semibold mb-2">Editar módulo</div>
      <div class="row g-2">
        <div class="col-md-8">
          <input class="form-control" name="title" value="{{ module.title }}" required />
        </div>
        <div class="col-md-4">
          <button class="btn btn-primary w-100" type="submit">Salvar</button>
        </div>
        <div class="col-12">
          <input class="form-control" name="description" value="{{ module.description }}" />
        </div>
      </div>
    </form>

    <form method="post" action="/educacao/modulos/{{ module.id }}/excluir"
          onsubmit="return confirm('Excluir módulo? Remova aulas antes.');">
      <button class="btn btn-outline-danger" type="submit">Excluir módulo</button>
    </form>
  {% endif %}
</div>
{% endblock %}
""",

    "edu_lesson_detail.html": r"""
{% extends "base.html" %}
{% block content %}
<div class="card p-4">
  <div class="d-flex justify-content-between align-items-start">
    <div>
      <h4 class="mb-1">{{ lesson.title }}</h4>
      <div class="muted">
        Curso: <a href="/educacao/cursos/{{ course.id }}">{{ course.title }}</a>
        • Módulo: <a href="/educacao/modulos/{{ module.id }}">{{ module.title }}</a>
        {% if progress_done %} • <span class="badge text-bg-light border">Concluída</span>{% endif %}
      </div>
    </div>
    <a class="btn btn-outline-secondary" href="/educacao/modulos/{{ module.id }}">Voltar</a>
  </div>

  <hr class="my-3"/>

  {% if embed_url %}
    <div class="ratio ratio-16x9 mb-3">
      <iframe src="{{ embed_url }}" title="Video" loading="lazy" referrerpolicy="origin-when-cross-origin" allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share" allowfullscreen></iframe>
    </div>
    <a class="btn btn-outline-primary btn-sm" href="{{ lesson.video_url }}" target="_blank" rel="noopener">Abrir no YouTube</a>
  {% elif lesson.video_url %}
    <div class="alert alert-warning">
      Este vídeo não pôde ser embutido. Se estiver <b>Privado</b>, o YouTube não permite player embutido.
      Use o botão abaixo para abrir.
    </div>
    <a class="btn btn-outline-primary" href="{{ lesson.video_url }}" target="_blank" rel="noopener">Abrir vídeo</a>
  {% else %}
    <div class="muted">Sem vídeo configurado.</div>
  {% endif %}

  {% if lesson.description %}
    <hr class="my-3"/>
    <pre>{{ lesson.description }}</pre>
  {% endif %}

  <hr class="my-3"/>
  <h5>Materiais</h5>
  {% if attachments %}
    <ul class="mb-2">
      {% for a in attachments %}
        <li class="d-flex justify-content-between align-items-center">
          <a href="/download/{{ a.id }}">{{ a.original_filename }}</a>
          {% if role in ["admin","equipe"] %}
            <form method="post" action="/attachments/{{ a.id }}/delete" class="ms-2">
              <input type="hidden" name="next" value="/educacao/aulas/{{ lesson.id }}">
              <button class="btn btn-outline-danger btn-sm" type="submit">Excluir</button>
            </form>
          {% endif %}
        </li>
      {% endfor %}
    </ul>
  {% else %}
    <div class="muted mb-2">Sem materiais.</div>
  {% endif %}

  {% if role in ["admin","equipe"] %}
    <form method="post" action="/educacao/aulas/{{ lesson.id }}/anexar" enctype="multipart/form-data" class="mt-2">
      <div class="row g-2">
        <div class="col-md-8">
          <input class="form-control" type="file" name="file" required />
        </div>
        <div class="col-md-4">
          <button class="btn btn-primary w-100" type="submit">Anexar</button>
        </div>
      </div>
    </form>
  {% endif %}

  <hr class="my-3"/>
  <form method="post" action="/educacao/aulas/{{ lesson.id }}/concluir">
    <button class="btn btn-primary" type="submit">{% if progress_done %}Marcar como não concluída{% else %}Marcar como concluída{% endif %}</button>
  </form>

  {% if role in ["admin","equipe"] %}
    <hr class="my-4"/>
    <form method="post" action="/educacao/aulas/{{ lesson.id }}/editar" class="card p-3 mb-3">
      <div class="fw-semibold mb-2">Editar aula</div>
      <div class="row g-2">
        <div class="col-md-6">
          <input class="form-control" name="title" value="{{ lesson.title }}" required />
        </div>
        <div class="col-md-6">
          <input class="form-control" name="video_url" value="{{ lesson.video_url }}" />
        </div>
        <div class="col-12">
          <textarea class="form-control" name="description" rows="3">{{ lesson.description }}</textarea>
        </div>
        <div class="col-12">
          <button class="btn btn-primary" type="submit">Salvar</button>
        </div>
      </div>
    </form>

    <form method="post" action="/educacao/aulas/{{ lesson.id }}/excluir"
          onsubmit="return confirm('Excluir aula? Remova materiais antes.');">
      <button class="btn btn-outline-danger" type="submit">Excluir aula</button>
    </form>
  {% endif %}
</div>
{% endblock %}
""",
})


@app.get("/educacao", response_class=HTMLResponse)
@require_login
async def edu_courses(request: Request, session: Session = Depends(get_session), client_id: int = 0) -> HTMLResponse:
    ctx = get_tenant_context(request, session)
    if not ctx:
        request.session.clear()
        return RedirectResponse("/login", status_code=303)

    active_client_id = get_active_client_id(request, session, ctx)
    current_client = get_client_or_none(session, ctx.company.id, active_client_id)

    courses_q = select(EducationCourse).where(EducationCourse.company_id == ctx.company.id).order_by(
        EducationCourse.updated_at.desc())

    clients: list[Client] = []
    filter_client_id = 0
    if ctx.membership.role == "cliente":
        cid = ctx.membership.client_id or 0
        access_course_ids = session.exec(
            select(EducationCourseAccess.course_id).where(
                EducationCourseAccess.company_id == ctx.company.id,
                EducationCourseAccess.client_id == cid,
            )
        ).all()
        if access_course_ids:
            courses_q = courses_q.where(EducationCourse.id.in_(access_course_ids))
        else:
            courses_q = courses_q.where(EducationCourse.id == -1)
    else:
        clients = session.exec(
            select(Client).where(Client.company_id == ctx.company.id).order_by(Client.created_at)).all()
        if client_id and client_id > 0:
            fc = get_client_or_none(session, ctx.company.id, int(client_id))
            if fc:
                filter_client_id = fc.id
                access_course_ids = session.exec(
                    select(EducationCourseAccess.course_id).where(
                        EducationCourseAccess.company_id == ctx.company.id,
                        EducationCourseAccess.client_id == fc.id,
                    )
                ).all()
                if access_course_ids:
                    courses_q = courses_q.where(EducationCourse.id.in_(access_course_ids))
                else:
                    courses_q = courses_q.where(EducationCourse.id == -1)

    courses = session.exec(courses_q).all()

    out = []
    for c in courses:
        assigned_count = None
        progress_pct = None
        if ctx.membership.role in {"admin", "equipe"}:
            assigned_count = int(session.exec(
                select(func.count(EducationCourseAccess.id)).where(EducationCourseAccess.course_id == c.id)).one() or 0)
        if ctx.membership.role == "cliente":
            progress_pct = _education_course_progress_pct(session, ctx.company.id, ctx.membership.client_id or 0,
                                                          ctx.user.id, c.id)
        out.append({"id": c.id, "title": c.title, "category": c.category, "is_active": c.is_active,
                    "assigned_count": assigned_count, "progress_pct": progress_pct})

    return render(
        "edu_courses.html",
        request=request,
        context={
            "current_user": ctx.user,
            "current_company": ctx.company,
            "role": ctx.membership.role,
            "current_client": current_client,
            "courses": out,
            "clients": clients,
            "filter_client_id": filter_client_id,
        },
    )


@app.get("/educacao/cursos/novo", response_class=HTMLResponse)
@require_role({"admin", "equipe"})
async def edu_course_new_page(request: Request, session: Session = Depends(get_session)) -> HTMLResponse:
    ctx = get_tenant_context(request, session)
    assert ctx is not None

    # Garante tabela em ambientes sem Alembic
    if not ensure_credit_consent_table():
        set_flash(request, "Sistema de aceite não está configurado (migração pendente no banco).")
        return RedirectResponse("/credito", status_code=303)

    clients = session.exec(select(Client).where(Client.company_id == ctx.company.id).order_by(Client.created_at)).all()
    current_client = get_client_or_none(session, ctx.company.id, get_active_client_id(request, session, ctx))
    return render("edu_course_new.html", request=request,
                  context={"current_user": ctx.user, "current_company": ctx.company, "role": ctx.membership.role,
                           "current_client": current_client, "clients": clients})


@app.post("/educacao/cursos/novo")
@require_role({"admin", "equipe"})
async def edu_course_new_action(
        request: Request,
        session: Session = Depends(get_session),
        title: str = Form(...),
        category: str = Form(""),
        description: str = Form(""),
        is_active: str = Form(""),
) -> Response:
    ctx = get_tenant_context(request, session)
    assert ctx is not None

    # Garante tabela em ambientes sem Alembic
    if not ensure_credit_consent_table():
        set_flash(request, "Sistema de aceite não está configurado (migração pendente no banco).")
        return RedirectResponse("/credito", status_code=303)

    form = await request.form()
    client_ids = [int(x) for x in form.getlist("client_ids") if str(x).isdigit()]

    course = EducationCourse(company_id=ctx.company.id, created_by_user_id=ctx.user.id, title=title.strip(),
                             category=category.strip(), description=description.strip(), is_active=(is_active == "1"),
                             updated_at=utcnow())
    session.add(course)
    session.commit()
    session.refresh(course)

    for cid in client_ids:
        if get_client_or_none(session, ctx.company.id, cid):
            session.add(EducationCourseAccess(company_id=ctx.company.id, course_id=course.id, client_id=cid))
    session.commit()

    set_flash(request, "Curso criado.")
    return RedirectResponse(f"/educacao/cursos/{course.id}", status_code=303)


@app.get("/educacao/cursos/{course_id}", response_class=HTMLResponse)
@require_login
async def edu_course_detail(request: Request, session: Session = Depends(get_session),
                            course_id: int = 0) -> HTMLResponse:
    ctx = get_tenant_context(request, session)
    if not ctx:
        request.session.clear()
        return RedirectResponse("/login", status_code=303)

    course = session.get(EducationCourse, int(course_id))
    if not course or course.company_id != ctx.company.id:
        return render("error.html", request=request, context={"message": "Curso não encontrado."}, status_code=404)

    if not _education_course_can_access(ctx, session, course):
        return render("error.html", request=request, context={"message": "Sem permissão."}, status_code=403)

    modules = session.exec(select(EducationModule).where(EducationModule.course_id == course.id).order_by(
        EducationModule.order.asc())).all()
    assigned = _education_course_assigned_clients(session, course)
    assigned_names = ", ".join(sorted({c.name for c in assigned})) if assigned else ""
    progress_pct = None
    if ctx.membership.role == "cliente":
        progress_pct = _education_course_progress_pct(session, ctx.company.id, ctx.membership.client_id or 0,
                                                      ctx.user.id, course.id)

    current_client = get_client_or_none(session, ctx.company.id, get_active_client_id(request, session, ctx))

    return render("edu_course_detail.html", request=request,
                  context={"current_user": ctx.user, "current_company": ctx.company, "role": ctx.membership.role,
                           "current_client": current_client, "course": course, "modules": modules,
                           "assigned_names": assigned_names, "progress_pct": progress_pct})


@app.post("/educacao/cursos/{course_id}/modulos")
@require_role({"admin", "equipe"})
async def edu_course_add_module(request: Request, session: Session = Depends(get_session), course_id: int = 0,
                                title: str = Form(...), description: str = Form("")) -> Response:
    ctx = get_tenant_context(request, session)
    assert ctx is not None

    # Garante tabela em ambientes sem Alembic
    if not ensure_credit_consent_table():
        set_flash(request, "Sistema de aceite não está configurado (migração pendente no banco).")
        return RedirectResponse("/credito", status_code=303)

    course = session.get(EducationCourse, int(course_id))
    if not course or course.company_id != ctx.company.id:
        set_flash(request, "Curso inválido.")
        return RedirectResponse("/educacao", status_code=303)

    max_order = session.exec(
        select(func.max(EducationModule.order)).where(EducationModule.course_id == course.id)).one()
    order = int(max_order or 0) + 1
    mod = EducationModule(course_id=course.id, title=title.strip(), order=order, description=description.strip())
    session.add(mod)
    session.commit()

    set_flash(request, "Módulo adicionado.")
    return RedirectResponse(f"/educacao/cursos/{course.id}", status_code=303)


@app.get("/educacao/cursos/{course_id}/editar", response_class=HTMLResponse)
@require_role({"admin", "equipe"})
async def edu_course_edit_page(request: Request, session: Session = Depends(get_session),
                               course_id: int = 0) -> HTMLResponse:
    ctx = get_tenant_context(request, session)
    assert ctx is not None

    # Garante tabela em ambientes sem Alembic
    if not ensure_credit_consent_table():
        set_flash(request, "Sistema de aceite não está configurado (migração pendente no banco).")
        return RedirectResponse("/credito", status_code=303)

    course = session.get(EducationCourse, int(course_id))
    if not course or course.company_id != ctx.company.id:
        return render("error.html", request=request, context={"message": "Curso não encontrado."}, status_code=404)

    clients = session.exec(select(Client).where(Client.company_id == ctx.company.id).order_by(Client.created_at)).all()
    assigned = session.exec(select(EducationCourseAccess).where(EducationCourseAccess.course_id == course.id)).all()
    assigned_ids = {a.client_id for a in assigned}
    current_client = get_client_or_none(session, ctx.company.id, get_active_client_id(request, session, ctx))

    return render("edu_course_edit.html", request=request,
                  context={"current_user": ctx.user, "current_company": ctx.company, "role": ctx.membership.role,
                           "current_client": current_client, "course": course, "clients": clients,
                           "assigned_ids": assigned_ids})


@app.post("/educacao/cursos/{course_id}/editar")
@require_role({"admin", "equipe"})
async def edu_course_edit_action(request: Request, session: Session = Depends(get_session), course_id: int = 0,
                                 title: str = Form(...), category: str = Form(""), description: str = Form(""),
                                 is_active: str = Form("")) -> Response:
    ctx = get_tenant_context(request, session)
    assert ctx is not None

    # Garante tabela em ambientes sem Alembic
    if not ensure_credit_consent_table():
        set_flash(request, "Sistema de aceite não está configurado (migração pendente no banco).")
        return RedirectResponse("/credito", status_code=303)

    course = session.get(EducationCourse, int(course_id))
    if not course or course.company_id != ctx.company.id:
        set_flash(request, "Curso não encontrado.")
        return RedirectResponse("/educacao", status_code=303)

    form = await request.form()
    client_ids = {int(x) for x in form.getlist("client_ids") if str(x).isdigit()}

    course.title = title.strip()
    course.category = category.strip()
    course.description = description.strip()
    course.is_active = (is_active == "1")
    course.updated_at = utcnow()
    session.add(course)

    existing = session.exec(select(EducationCourseAccess).where(EducationCourseAccess.course_id == course.id)).all()
    existing_ids = {a.client_id for a in existing}
    for a in existing:
        if a.client_id not in client_ids:
            session.delete(a)
    for cid in client_ids - existing_ids:
        if get_client_or_none(session, ctx.company.id, cid):
            session.add(EducationCourseAccess(company_id=ctx.company.id, course_id=course.id, client_id=cid))

    session.commit()
    set_flash(request, "Curso atualizado.")
    return RedirectResponse(f"/educacao/cursos/{course.id}", status_code=303)


@app.post("/educacao/cursos/{course_id}/excluir")
@require_role({"admin", "equipe"})
async def edu_course_delete(request: Request, session: Session = Depends(get_session), course_id: int = 0) -> Response:
    ctx = get_tenant_context(request, session)
    assert ctx is not None

    # Garante tabela em ambientes sem Alembic
    if not ensure_credit_consent_table():
        set_flash(request, "Sistema de aceite não está configurado (migração pendente no banco).")
        return RedirectResponse("/credito", status_code=303)

    course = session.get(EducationCourse, int(course_id))
    if not course or course.company_id != ctx.company.id:
        set_flash(request, "Curso não encontrado.")
        return RedirectResponse("/educacao", status_code=303)

    mods = session.exec(select(EducationModule).where(EducationModule.course_id == course.id)).all()
    if mods:
        set_flash(request, "Remova módulos/aulas antes de excluir o curso.")
        return RedirectResponse(f"/educacao/cursos/{course.id}", status_code=303)

    accesses = session.exec(select(EducationCourseAccess).where(EducationCourseAccess.course_id == course.id)).all()
    for a in accesses:
        session.delete(a)

    session.delete(course)
    session.commit()
    set_flash(request, "Curso excluído.")
    return RedirectResponse("/educacao", status_code=303)


@app.get("/educacao/modulos/{module_id}", response_class=HTMLResponse)
@require_login
async def edu_module_detail(request: Request, session: Session = Depends(get_session),
                            module_id: int = 0) -> HTMLResponse:
    ctx = get_tenant_context(request, session)
    if not ctx:
        request.session.clear()
        return RedirectResponse("/login", status_code=303)

    module = session.get(EducationModule, int(module_id))
    if not module:
        return render("error.html", request=request, context={"message": "Módulo não encontrado."}, status_code=404)

    course = session.exec(select(EducationCourse).where(EducationCourse.id == module.course_id)).first()
    if not course or course.company_id != ctx.company.id:
        return render("error.html", request=request, context={"message": "Curso inválido."}, status_code=403)

    if not _education_course_can_access(ctx, session, course):
        return render("error.html", request=request, context={"message": "Sem permissão."}, status_code=403)

    lessons = session.exec(select(EducationLesson).where(EducationLesson.module_id == module.id).order_by(
        EducationLesson.order.asc())).all()
    current_client = get_client_or_none(session, ctx.company.id, get_active_client_id(request, session, ctx))

    return render("edu_module_detail.html", request=request,
                  context={"current_user": ctx.user, "current_company": ctx.company, "role": ctx.membership.role,
                           "current_client": current_client, "module": module, "course": course, "lessons": lessons})


@app.post("/educacao/modulos/{module_id}/aulas")
@require_role({"admin", "equipe"})
async def edu_module_add_lesson(request: Request, session: Session = Depends(get_session), module_id: int = 0,
                                title: str = Form(...), video_url: str = Form(""),
                                description: str = Form("")) -> Response:
    ctx = get_tenant_context(request, session)
    assert ctx is not None

    # Garante tabela em ambientes sem Alembic
    if not ensure_credit_consent_table():
        set_flash(request, "Sistema de aceite não está configurado (migração pendente no banco).")
        return RedirectResponse("/credito", status_code=303)

    module = session.get(EducationModule, int(module_id))
    if not module:
        set_flash(request, "Módulo inválido.")
        return RedirectResponse("/educacao", status_code=303)

    course = session.exec(select(EducationCourse).where(EducationCourse.id == module.course_id)).first()
    if not course or course.company_id != ctx.company.id:
        set_flash(request, "Curso inválido.")
        return RedirectResponse("/educacao", status_code=303)

    max_order = session.exec(
        select(func.max(EducationLesson.order)).where(EducationLesson.module_id == module.id)).one()
    order = int(max_order or 0) + 1

    lesson = EducationLesson(module_id=module.id, title=title.strip(), order=order, video_url=video_url.strip(),
                             description=description.strip())
    session.add(lesson)
    session.commit()

    set_flash(request, "Aula adicionada.")
    return RedirectResponse(f"/educacao/modulos/{module.id}", status_code=303)


@app.post("/educacao/modulos/{module_id}/editar")
@require_role({"admin", "equipe"})
async def edu_module_edit(request: Request, session: Session = Depends(get_session), module_id: int = 0,
                          title: str = Form(...), description: str = Form("")) -> Response:
    ctx = get_tenant_context(request, session)
    assert ctx is not None

    # Garante tabela em ambientes sem Alembic
    if not ensure_credit_consent_table():
        set_flash(request, "Sistema de aceite não está configurado (migração pendente no banco).")
        return RedirectResponse("/credito", status_code=303)

    module = session.get(EducationModule, int(module_id))
    if not module:
        set_flash(request, "Módulo não encontrado.")
        return RedirectResponse("/educacao", status_code=303)

    module.title = title.strip()
    module.description = description.strip()
    session.add(module)
    session.commit()

    set_flash(request, "Módulo atualizado.")
    return RedirectResponse(f"/educacao/modulos/{module.id}", status_code=303)


@app.post("/educacao/modulos/{module_id}/excluir")
@require_role({"admin", "equipe"})
async def edu_module_delete(request: Request, session: Session = Depends(get_session), module_id: int = 0) -> Response:
    ctx = get_tenant_context(request, session)
    assert ctx is not None

    # Garante tabela em ambientes sem Alembic
    if not ensure_credit_consent_table():
        set_flash(request, "Sistema de aceite não está configurado (migração pendente no banco).")
        return RedirectResponse("/credito", status_code=303)

    module = session.get(EducationModule, int(module_id))
    if not module:
        set_flash(request, "Módulo não encontrado.")
        return RedirectResponse("/educacao", status_code=303)

    lessons = session.exec(select(EducationLesson).where(EducationLesson.module_id == module.id)).all()
    if lessons:
        set_flash(request, "Remova aulas antes de excluir o módulo.")
        return RedirectResponse(f"/educacao/modulos/{module.id}", status_code=303)

    course = session.exec(select(EducationCourse).where(EducationCourse.id == module.course_id)).first()
    session.delete(module)
    session.commit()

    set_flash(request, "Módulo excluído.")
    return RedirectResponse(f"/educacao/cursos/{course.id if course else ''}", status_code=303)


@app.get("/educacao/aulas/{lesson_id}", response_class=HTMLResponse)
@require_login
async def edu_lesson_detail(request: Request, session: Session = Depends(get_session),
                            lesson_id: int = 0) -> HTMLResponse:
    ctx = get_tenant_context(request, session)
    if not ctx:
        request.session.clear()
        return RedirectResponse("/login", status_code=303)

    lesson = session.get(EducationLesson, int(lesson_id))
    if not lesson:
        return render("error.html", request=request, context={"message": "Aula não encontrada."}, status_code=404)

    module = session.get(EducationModule, lesson.module_id)
    course = session.exec(
        select(EducationCourse).where(EducationCourse.id == module.course_id)).first() if module else None
    if not module or not course or course.company_id != ctx.company.id:
        return render("error.html", request=request, context={"message": "Curso inválido."}, status_code=403)

    if not _education_course_can_access(ctx, session, course):
        return render("error.html", request=request, context={"message": "Sem permissão."}, status_code=403)

    embed_url = _youtube_embed_url(lesson.video_url)

    attachments_client_id = 0
    if ctx.membership.role == "cliente":
        attachments_client_id = ctx.membership.client_id or 0
    else:
        attachments_client_id = get_active_client_id(request, session, ctx) or 0

    att_where = [Attachment.company_id == ctx.company.id, Attachment.education_lesson_id == lesson.id]
    if attachments_client_id:
        att_where.append(Attachment.client_id == attachments_client_id)

    attachments = session.exec(
        select(Attachment).where(*att_where).order_by(Attachment.created_at.desc())
    ).all()

    progress = session.exec(
        select(EducationLessonProgress).where(
            EducationLessonProgress.lesson_id == lesson.id,
            EducationLessonProgress.user_id == ctx.user.id,
        )
    ).first()
    progress_done = bool(progress)

    current_client = get_client_or_none(session, ctx.company.id, get_active_client_id(request, session, ctx))

    return render("edu_lesson_detail.html", request=request,
                  context={"current_user": ctx.user, "current_company": ctx.company, "role": ctx.membership.role,
                           "current_client": current_client, "course": course, "module": module, "lesson": lesson,
                           "embed_url": embed_url, "attachments": attachments, "progress_done": progress_done})


@app.post("/educacao/aulas/{lesson_id}/concluir")
@require_login
async def edu_lesson_toggle_complete(request: Request, session: Session = Depends(get_session),
                                     lesson_id: int = 0) -> Response:
    ctx = get_tenant_context(request, session)
    if not ctx:
        request.session.clear()
        return RedirectResponse("/login", status_code=303)

    lesson = session.get(EducationLesson, int(lesson_id))
    if not lesson:
        set_flash(request, "Aula não encontrada.")
        return RedirectResponse("/educacao", status_code=303)

    module = session.get(EducationModule, lesson.module_id)
    course = session.exec(
        select(EducationCourse).where(EducationCourse.id == module.course_id)).first() if module else None
    if not module or not course or course.company_id != ctx.company.id:
        set_flash(request, "Curso inválido.")
        return RedirectResponse("/educacao", status_code=303)

    if not _education_course_can_access(ctx, session, course):
        set_flash(request, "Sem permissão.")
        return RedirectResponse("/educacao", status_code=303)

    client_id = (ctx.membership.client_id or 0) if ctx.membership.role == "cliente" else (
            get_active_client_id(request, session, ctx) or 0)
    if not client_id:
        set_flash(request, "Selecione um cliente.")
        return RedirectResponse(f"/educacao/aulas/{lesson.id}", status_code=303)

    existing = session.exec(select(EducationLessonProgress).where(EducationLessonProgress.lesson_id == lesson.id,
                                                                  EducationLessonProgress.user_id == ctx.user.id)).first()
    if existing:
        session.delete(existing)
        session.commit()
        set_flash(request, "Marcada como não concluída.")
    else:
        session.add(EducationLessonProgress(company_id=ctx.company.id, client_id=client_id, lesson_id=lesson.id,
                                            user_id=ctx.user.id, completed=True, completed_at=utcnow()))
        session.commit()
        set_flash(request, "Aula concluída.")

    return RedirectResponse(f"/educacao/aulas/{lesson.id}", status_code=303)


@app.post("/educacao/aulas/{lesson_id}/anexar")
@require_role({"admin", "equipe"})
async def edu_lesson_attach(request: Request, session: Session = Depends(get_session), lesson_id: int = 0,
                            file: UploadFile = File(...)) -> Response:
    ctx = get_tenant_context(request, session)
    assert ctx is not None

    # Garante tabela em ambientes sem Alembic
    if not ensure_credit_consent_table():
        set_flash(request, "Sistema de aceite não está configurado (migração pendente no banco).")
        return RedirectResponse("/credito", status_code=303)

    lesson = session.get(EducationLesson, int(lesson_id))
    if not lesson:
        set_flash(request, "Aula não encontrada.")
        return RedirectResponse("/educacao", status_code=303)

    try:
        stored, mime, size = await save_upload(file)
    except ValueError:
        set_flash(request, "Arquivo muito grande.")
        return RedirectResponse(f"/educacao/aulas/{lesson.id}", status_code=303)

    active_client_id = get_active_client_id(request, session, ctx) or 0
    if not active_client_id:
        # choose first assigned client if any
        module = session.get(EducationModule, lesson.module_id)
        course = session.exec(
            select(EducationCourse).where(EducationCourse.id == module.course_id)).first() if module else None
        if course:
            assigned = _education_course_assigned_clients(session, course)
            active_client_id = assigned[0].id if assigned else 0

    if not active_client_id:
        set_flash(request, "Selecione um cliente para anexar material.")
        return RedirectResponse(f"/educacao/aulas/{lesson.id}", status_code=303)

    session.add(Attachment(company_id=ctx.company.id, client_id=active_client_id, uploaded_by_user_id=ctx.user.id,
                           education_lesson_id=lesson.id, original_filename=file.filename or "arquivo",
                           stored_filename=stored, mime_type=mime, size_bytes=size))
    session.commit()

    set_flash(request, "Material anexado.")
    return RedirectResponse(f"/educacao/aulas/{lesson.id}", status_code=303)


@app.post("/educacao/aulas/{lesson_id}/editar")
@require_role({"admin", "equipe"})
async def edu_lesson_edit(request: Request, session: Session = Depends(get_session), lesson_id: int = 0,
                          title: str = Form(...), video_url: str = Form(""), description: str = Form("")) -> Response:
    ctx = get_tenant_context(request, session)
    assert ctx is not None

    # Garante tabela em ambientes sem Alembic
    if not ensure_credit_consent_table():
        set_flash(request, "Sistema de aceite não está configurado (migração pendente no banco).")
        return RedirectResponse("/credito", status_code=303)

    lesson = session.get(EducationLesson, int(lesson_id))
    if not lesson:
        set_flash(request, "Aula não encontrada.")
        return RedirectResponse("/educacao", status_code=303)

    lesson.title = title.strip()
    lesson.video_url = video_url.strip()
    lesson.description = description.strip()
    session.add(lesson)
    session.commit()

    set_flash(request, "Aula atualizada.")
    return RedirectResponse(f"/educacao/aulas/{lesson.id}", status_code=303)


@app.post("/educacao/aulas/{lesson_id}/excluir")
@require_role({"admin", "equipe"})
async def edu_lesson_delete(request: Request, session: Session = Depends(get_session), lesson_id: int = 0) -> Response:
    ctx = get_tenant_context(request, session)
    assert ctx is not None

    # Garante tabela em ambientes sem Alembic
    if not ensure_credit_consent_table():
        set_flash(request, "Sistema de aceite não está configurado (migração pendente no banco).")
        return RedirectResponse("/credito", status_code=303)

    lesson = session.get(EducationLesson, int(lesson_id))
    if not lesson:
        set_flash(request, "Aula não encontrada.")
        return RedirectResponse("/educacao", status_code=303)

    atts = session.exec(select(Attachment).where(Attachment.education_lesson_id == lesson.id)).all()
    if atts:
        set_flash(request, "Remova materiais antes de excluir a aula.")
        return RedirectResponse(f"/educacao/aulas/{lesson.id}", status_code=303)

    module = session.get(EducationModule, lesson.module_id)
    session.delete(lesson)
    session.commit()

    set_flash(request, "Aula excluída.")
    return RedirectResponse(f"/educacao/modulos/{module.id if module else ''}", status_code=303)


# ----------------------------
# Crédito (SCR Direct Data)
# ----------------------------


def _digits_only(value: str) -> str:
    return re.sub(r"\D+", "", value or "").strip()


def _parse_brl_amount(value: Any) -> float:
    """
    Converte strings de valor (ex.: "1.234,56", "1234.56", "R$ 1.234", "1.234.567") para float.

    Regras:
      - Se tiver '.' e ',' -> '.' é milhar, ',' é decimal.
      - Se tiver só ',' -> ',' é decimal, '.' (se existir) é milhar.
      - Se tiver só '.' e MAIS DE UM '.' -> assume milhar (remove todos os '.').
      - Caso contrário tenta float direto após limpar caracteres.
    """
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        try:
            return float(value)
        except Exception:
            return 0.0

    s = str(value).strip()
    if not s:
        return 0.0

    s = s.replace("R$", "").replace(" ", "")
    # Se tiver ambos '.' e ',', assume '.' milhar e ',' decimal
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".")
    else:
        # Se só tiver ',', assume decimal
        if "," in s:
            s = s.replace(".", "").replace(",", ".")
        else:
            # Só '.' (ou nenhum): se houver mais de um '.', assume milhar e remove todos
            if s.count(".") > 1:
                s = s.replace(".", "")

    # Remove qualquer coisa que não seja número/ponto/sinal
    s = re.sub(r"[^0-9.\-]+", "", s)
    if not s or s == "-" or s == ".":
        return 0.0

    try:
        return float(s)
    except Exception:
        # Último fallback: remove todos os pontos e tenta novamente
        try:
            return float(s.replace(".", ""))
        except Exception:
            return 0.0


def _calc_potential(report: CreditReport) -> tuple[float, str]:
    score = 0.0

    total = report.carteira_total_brl
    vencido = report.carteira_vencido_brl
    preju = report.carteira_prejuizo_brl
    inst = report.quantidade_instituicoes

    if total >= 1_000_000:
        score += 35
    elif total >= 500_000:
        score += 25
    elif total >= 200_000:
        score += 15
    elif total >= 50_000:
        score += 8

    if inst >= 8:
        score += 18
    elif inst >= 5:
        score += 12
    elif inst >= 3:
        score += 7

    if vencido >= 100_000:
        score += 25
    elif vencido >= 20_000:
        score += 15
    elif vencido > 0:
        score += 8

    if preju > 0:
        score += 8

    # Clamps
    score = max(0.0, min(100.0, round(score, 1)))

    if score >= 70:
        label = "alto"
    elif score >= 40:
        label = "medio"
    else:
        label = "baixo"

    return score, label


async def _directdata_scr_poll_request(*, consulta_uid: str) -> tuple[int, dict[str, Any] | None, str]:
    """Obtém o retorno de uma consulta assíncrona já iniciada na Direct Data.

    Quando usamos `async=habilitar`, a primeira chamada pode retornar somente `metaDados`
    com `consultaUid`. Para evitar nova cobrança, este poll busca o resultado final usando
    o endpoint de histórico (ObterRetornoConsultaAsync).
    """
    if not DIRECTDATA_TOKEN:
        return 0, None, "DIRECTDATA_TOKEN não configurado."
    uid = (consulta_uid or "").strip()
    if not uid:
        return 0, None, "consultaUid ausente."

    params: dict[str, Any] = {"TOKEN": DIRECTDATA_TOKEN, "consultaUid": uid}
    timeout = httpx.Timeout(DIRECTDATA_TIMEOUT_S, connect=min(5.0, float(DIRECTDATA_TIMEOUT_S)))
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            resp = await client.get(DIRECTDATA_ASYNC_RESULT_URL, params=params)
    except Exception as e:
        return 0, None, f"Falha ao consultar Direct Data (poll): {e}"

    try:
        data = resp.json()
    except Exception:
        data = None

    msg = ""
    if isinstance(data, dict):
        meta = data.get("metaDados") or {}
        msg = str(meta.get("mensagem") or meta.get("resultado") or "")[:500]

    return int(resp.status_code or 0), data if isinstance(data, dict) else None, msg


def _directdata_meta_is_processing(meta: dict[str, Any]) -> bool:
    """Heurística: identifica respostas ainda em processamento via metaDados."""
    txt = f"{meta.get('mensagem', '')} {meta.get('resultado', '')}".lower()
    if not txt.strip():
        return False
    return any(k in txt for k in ("process", "aguard", "fila", "assíncr", "assincr", "gerando"))


async def _directdata_scr_request(*, document_type: str, document_value: str, consulta_uid: str = "", url_override: str | None = None) -> tuple[
    int, dict[str, Any] | None, str]:
    """Consulta Direct Data (SCR) via HTTP (assíncrono).

    Usamos AsyncClient para não travar o worker (Render).
    """
    if consulta_uid:
        return await _directdata_scr_poll_request(consulta_uid=consulta_uid)

    if not DIRECTDATA_TOKEN:
        return 0, None, "DIRECTDATA_TOKEN não configurado."
    doc = _digits_only(document_value)
    if not doc:
        return 0, None, "Documento inválido."

    params: dict[str, Any] = {"TOKEN": DIRECTDATA_TOKEN}
    if document_type == "cpf":
        params["CPF"] = doc
    else:
        params["CNPJ"] = doc

    if DIRECTDATA_ASYNC:
        params["async"] = "habilitar"

    timeout = httpx.Timeout(DIRECTDATA_TIMEOUT_S, connect=min(5.0, float(DIRECTDATA_TIMEOUT_S)))
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            target_url = url_override or DIRECTDATA_SCR_URL
            resp = await client.get(target_url, params=params)
    except Exception as e:
        return 0, None, f"Falha ao consultar Direct Data: {e}"

    try:
        data = resp.json()
    except Exception:
        data = None

    msg = ""
    if isinstance(data, dict):
        meta = data.get("metaDados") or {}
        msg = str(meta.get("mensagem") or meta.get("resultado") or "")[:500]

    return resp.status_code, data if isinstance(data, dict) else None, msg


def _apply_directdata_response_to_report(report: "CreditReport", *, code: int, data: dict[str, Any] | None,
                                         msg: str) -> None:
    """Atualiza o CreditReport com a resposta Direct Data (sem commit)."""
    report.http_status = int(code or 0)
    report.message = (msg or "")[:500]

    if not data:
        report.status = "error"
        report.message = report.message or "Sem resposta JSON."
        report.updated_at = utcnow()
        return

    meta = data.get("metaDados") or {}
    ret = data.get("retorno") or {}

    report.consulta_uid = str(meta.get("consultaUid") or report.consulta_uid)
    try:
        report.resultado_id = int(meta.get("resultadoId") or report.resultado_id)
    except Exception:
        pass

    report.raw_json = json.dumps(data, ensure_ascii=False, indent=2)

    processing_hint = False
    if isinstance(meta, dict):
        processing_hint = _directdata_meta_is_processing(meta)

    if code == 200 and not processing_hint:
        report.status = "done"
    elif code in (201, 202) or processing_hint:
        report.status = "processing"
    else:
        report.status = "error"

    if isinstance(ret, dict) and ret:
        report.score = str(ret.get("score") or report.score)
        report.faixa_risco = str(ret.get("faixaRisco") or report.faixa_risco)
        report.obrigacao_assumida = str(ret.get("obrigacaoAssumida") or report.obrigacao_assumida)
        report.obrigacao_resumida = str(ret.get("obrigacaoResumida") or report.obrigacao_resumida)

        try:
            report.quantidade_instituicoes = int(ret.get("quantidadeInstituicoes") or report.quantidade_instituicoes)
        except Exception:
            pass
        try:
            report.quantidade_operacoes = int(ret.get("quantidadeOperacoes") or report.quantidade_operacoes)
        except Exception:
            pass

        report.risco_total_brl = _parse_brl_amount(ret.get("riscoTotal"))

        carteira = ret.get("carteiraCredito") or {}
        if isinstance(carteira, dict):
            report.carteira_total_brl = _parse_brl_amount(carteira.get("total"))
            report.carteira_vencer_brl = _parse_brl_amount(carteira.get("vencer"))
            report.carteira_vencido_brl = _parse_brl_amount(carteira.get("vencido"))
            report.carteira_prejuizo_brl = _parse_brl_amount(carteira.get("prejuizo"))

        pscore, plabel = _calc_potential(report)
        report.potential_score = pscore
        report.potential_label = plabel

    report.updated_at = utcnow()


async def _credit_run_scr_and_update(report_id: int) -> None:
    """Roda a consulta SCR e persiste o resultado sem travar a requisição."""
    try:
        with Session(engine) as s:
            report = s.get(CreditReport, int(report_id))
            if not report:
                return
            consulta_uid = report.consulta_uid if report.status == "processing" else ""
            code, data, msg = await _directdata_scr_request(document_type=report.document_type,
                                                            document_value=report.document_value,
                                                            consulta_uid=consulta_uid)
            _apply_directdata_response_to_report(report, code=int(code or 0), data=data, msg=msg)
            s.add(report)
            s.commit()
    except Exception as e:
        print(f"[credit] background update failed report_id={report_id}: {e}")


def _get_client_for_credit(ctx: TenantContext, request: Request, session: Session) -> Client | None:
    if ctx.membership.role == "cliente":
        if not ctx.membership.client_id:
            return None
        return get_client_or_none(session, ctx.company.id, int(ctx.membership.client_id))
    active_client_id = get_active_client_id(request, session, ctx)
    if not active_client_id:
        return None
    return get_client_or_none(session, ctx.company.id, int(active_client_id))


def _get_latest_consent(session: Session, *, company_id: int, client_id: int) -> CreditConsent | None:
    try:
        return session.exec(
            select(CreditConsent)
            .where(
                CreditConsent.company_id == company_id,
                CreditConsent.client_id == client_id,
                CreditConsent.kind == CREDIT_CONSENT_KIND_SCR,
            )
            .order_by(CreditConsent.created_at.desc())
        ).first()
    except Exception as e:
        # Tabela ausente / permissão / migração pendente: não derruba o fluxo público.
        try:
            print(f"[consent] failed to query latest consent: {e}")
        except Exception:
            pass
        return None


def _as_aware_utc(dt: Optional[datetime]) -> Optional[datetime]:
    """Garante datetime timezone-aware em UTC.

    Muitos bancos/ORMs podem retornar datetimes "naive" (sem tzinfo). Para evitar
    TypeError ao comparar com utcnow() (aware), assumimos UTC quando tzinfo=None.
    """
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    try:
        return dt.astimezone(timezone.utc)
    except Exception:
        return dt


def _refresh_consent_status(consent: CreditConsent) -> None:
    """Atualiza status apenas quando fizer sentido (não promove 'pendente' para 'valida').

    Regras:
    - pendente: vira expirada se passou do expires_at; caso contrário permanece pendente.
    - valida: vira expirada se passou do expires_at.
    - revogada: permanece revogada.
    - expirada: permanece expirada.
    """
    now = utcnow()
    status = (consent.status or "").strip().lower() or "pendente"

    if status == "revogada":
        consent.status = "revogada"
        return

    expires_at = _as_aware_utc(consent.expires_at)
    if expires_at and now > expires_at:
        consent.status = "expirada"
        return

    if status in ("valida",):
        consent.status = "valida"
        return

    # Default: não aceito ainda
    consent.status = "pendente"


def _coerce_credit_report_nullable_fields(r: "CreditReport") -> None:
    """Normaliza campos potencialmente nulos/strings para evitar 500 na UI.

    Na prática, podem existir registros antigos com campos numéricos salvos como string
    (ex.: '1.234,56'). Este helper garante que o template não quebre.
    """

    def _safe_int(v: Any, default: int = 0) -> int:
        if v is None:
            return default
        if isinstance(v, bool):
            return int(v)
        if isinstance(v, int):
            return v
        try:
            return int(v)
        except Exception:
            try:
                s = str(v).strip()
                if not s:
                    return default
                s = re.sub(r"[^0-9\-]+", "", s)
                if not s or s == "-":
                    return default
                return int(s)
            except Exception:
                return default

    # Inteiros
    r.quantidade_instituicoes = _safe_int(getattr(r, "quantidade_instituicoes", 0), 0)
    r.quantidade_operacoes = _safe_int(getattr(r, "quantidade_operacoes", 0), 0)
    r.http_status = _safe_int(getattr(r, "http_status", 0), 0)
    r.resultado_id = _safe_int(getattr(r, "resultado_id", 0), 0)

    # Floats (aceita strings BR)
    r.risco_total_brl = _parse_brl_amount(getattr(r, "risco_total_brl", 0.0))
    r.carteira_total_brl = _parse_brl_amount(getattr(r, "carteira_total_brl", 0.0))
    r.carteira_vencer_brl = _parse_brl_amount(getattr(r, "carteira_vencer_brl", 0.0))
    r.carteira_vencido_brl = _parse_brl_amount(getattr(r, "carteira_vencido_brl", 0.0))
    r.carteira_prejuizo_brl = _parse_brl_amount(getattr(r, "carteira_prejuizo_brl", 0.0))
    r.potential_score = _parse_brl_amount(getattr(r, "potential_score", 0.0))

    # Strings
    r.score = (getattr(r, "score", "") or "")
    r.faixa_risco = (getattr(r, "faixa_risco", "") or "")
    r.obrigacao_assumida = (getattr(r, "obrigacao_assumida", "") or "")
    r.obrigacao_resumida = (getattr(r, "obrigacao_resumida", "") or "")
    r.message = (getattr(r, "message", "") or "")
    r.status = (getattr(r, "status", "") or "processing")
    r.potential_label = (getattr(r, "potential_label", "") or "baixo")


@app.get("/credito", response_class=HTMLResponse)
@require_login
async def credit_home(request: Request, session: Session = Depends(get_session)) -> HTMLResponse:
    ctx = get_tenant_context(request, session)
    if not ctx:
        request.session.clear()
        return RedirectResponse("/login", status_code=303)

    current_client = _get_client_for_credit(ctx, request, session)

    consent = None
    consent_file = None
    reports: list[CreditReport] = []

    if current_client and ensure_can_access_client(ctx, current_client.id):
        try:
            consent = _get_latest_consent(session, company_id=ctx.company.id, client_id=current_client.id)
            if consent:
                prev_status = consent.status
                _refresh_consent_status(consent)
                # Só persiste se mudar status (evita commits desnecessários a cada page load)
                if consent.status != prev_status:
                    consent.updated_at = utcnow()
                    session.add(consent)
                    session.commit()
                consent_file = session.exec(
                    select(Attachment)
                    .where(
                        Attachment.company_id == ctx.company.id,
                        Attachment.client_id == current_client.id,
                        Attachment.credit_consent_id == consent.id,
                    )
                    .order_by(Attachment.created_at.desc())
                ).first()

            reports = session.exec(
                select(CreditReport)
                .where(CreditReport.company_id == ctx.company.id, CreditReport.client_id == current_client.id)
                .order_by(CreditReport.created_at.desc())
                .limit(30)
            ).all()
        except Exception as e:
            # Evita 500 silencioso no Render: mostra mensagem amigável e mantém log
            print(f"[credit] erro ao carregar tela /credito: {type(e).__name__}: {e}")
            return render(
                "error.html",
                request=request,
                context={
                    "current_user": ctx.user,
                    "current_company": ctx.company,
                    "role": ctx.membership.role,
                    "current_client": current_client,
                    "message": f"Erro no módulo de crédito: {type(e).__name__}: {e}",
                },
                status_code=500,
            )
    else:
        if ctx.membership.role != "cliente":
            set_flash(request, "Selecione um cliente para acessar Crédito.")

    consent_link_url = str(request.session.get("consent_link_url") or "")
    base = _public_base_url(request)
    # Se o link em sessão está com host antigo (ex.: domínio errado), recalcula.
    if consent_link_url and not consent_link_url.startswith(base + "/consent/aceite/"):
        consent_link_url = ""
    if (not consent_link_url) and consent and consent.status == "pendente":
        meta = _unpack_consent_link_note(consent.notes)
        if meta and meta.get("token"):
            try:
                _verify_consent_token(str(meta["token"]))
                consent_link_url = f"{_public_base_url(request)}/consent/aceite/{str(meta['token'])}"
            except Exception:
                consent_link_url = ""

    for r in reports:
        _coerce_credit_report_nullable_fields(r)

    return render(
        "credit_list.html",
        request=request,
        context={
            "current_user": ctx.user,
            "current_company": ctx.company,
            "role": ctx.membership.role,
            "current_client": current_client,
            "consent": consent,
            "consent_file": consent_file,
            "consent_link_url": consent_link_url,
            "reports": reports,
        },
    )


@app.post("/credito/consent")
@require_login
async def credit_upload_consent(
        request: Request,
        session: Session = Depends(get_session),
        signed_by_name: str = Form(...),
        signed_by_document: str = Form(""),
        signed_at: str = Form(""),
        notes: str = Form(""),
        file: UploadFile = File(...),
) -> Response:
    ctx = get_tenant_context(request, session)
    if not ctx:
        request.session.clear()
        return RedirectResponse("/login", status_code=303)

    current_client = _get_client_for_credit(ctx, request, session)
    if not current_client or not ensure_can_access_client(ctx, current_client.id):
        set_flash(request, "Cliente inválido.")
        return RedirectResponse("/credito", status_code=303)

    signed_at_dt = utcnow()
    if signed_at.strip():
        try:
            signed_at_dt = datetime.fromisoformat(signed_at.strip()).replace(tzinfo=timezone.utc)
        except Exception:
            pass

    expires_at = signed_at_dt + timedelta(days=CREDIT_CONSENT_MAX_DAYS)

    consent = CreditConsent(
        company_id=ctx.company.id,
        client_id=current_client.id,
        created_by_user_id=ctx.user.id,
        kind=CREDIT_CONSENT_KIND_SCR,
        status="valida",
        signed_by_name=signed_by_name.strip(),
        signed_by_document=_digits_only(signed_by_document),
        signed_at=signed_at_dt,
        expires_at=expires_at,
        notes=notes.strip(),
        created_at=utcnow(),
        updated_at=utcnow(),
    )
    session.add(consent)
    session.commit()
    session.refresh(consent)

    try:
        stored, mime, size = await save_upload(file)
    except ValueError:
        set_flash(request, "Arquivo muito grande.")
        return RedirectResponse("/credito", status_code=303)

    att = Attachment(
        company_id=ctx.company.id,
        client_id=current_client.id,
        uploaded_by_user_id=ctx.user.id,
        credit_consent_id=consent.id,
        original_filename=file.filename or "autorizacao",
        stored_filename=stored,
        mime_type=mime,
        size_bytes=size,
    )
    session.add(att)
    session.commit()

    set_flash(request, "Autorização enviada.")
    return RedirectResponse("/credito", status_code=303)


@app.post("/credito/consent_link")
@require_role({"admin", "equipe"})
async def credit_generate_consent_link(
        request: Request,
        session: Session = Depends(get_session),
) -> Response:
    """Gera (ou reutiliza) um link público de aceite eletrônico (sem OTP)."""
    ctx = get_tenant_context(request, session)
    assert ctx is not None

    # Garante tabela em ambientes sem Alembic
    if not ensure_credit_consent_table():
        set_flash(request, "Sistema de aceite não está configurado (migração pendente no banco).")
        return RedirectResponse("/credito", status_code=303)

    current_client = _get_client_for_credit(ctx, request, session)
    if not current_client:
        set_flash(request, "Selecione um cliente.")
        return RedirectResponse("/credito", status_code=303)

    try:
        latest = _get_latest_consent(session, company_id=ctx.company.id, client_id=current_client.id)
    except OperationalError:
        ensure_credit_consent_table()
        latest = None
    if latest:
        _refresh_consent_status(latest)
        if latest.status == "pendente":
            meta = _unpack_consent_link_note(latest.notes)
            if meta and meta.get("token"):
                try:
                    _verify_consent_token(str(meta["token"]))
                    token = str(meta["token"])
                    url = f"{_public_base_url(request)}/consent/aceite/{token}"
                    request.session["consent_link_url"] = url
                    set_flash(request, f"Link de aceite: {url}")
                    return RedirectResponse("/credito", status_code=303)
                except Exception:
                    pass

    now = utcnow()
    exp_dt = now + timedelta(hours=int(CREDIT_CONSENT_LINK_TTL_HOURS))
    payload = {
        "company_id": ctx.company.id,
        "client_id": current_client.id,
        "created_by_user_id": ctx.user.id,
        "kind": CREDIT_CONSENT_KIND_SCR,
        "iat": int(now.timestamp()),
        "exp": int(exp_dt.timestamp()),
        "nonce": secrets.token_urlsafe(12),
        "term_version": CREDIT_CONSENT_TERM_VERSION,
    }
    token = _sign_consent_token(payload)

    consent = CreditConsent(
        company_id=ctx.company.id,
        client_id=current_client.id,
        created_by_user_id=ctx.user.id,
        kind=CREDIT_CONSENT_KIND_SCR,
        status="pendente",
        signed_by_name="",
        signed_by_document="",
        signed_at=now,
        expires_at=exp_dt,
        notes=_pack_consent_link_note(token=token, created_by_user_id=ctx.user.id, expires_at=exp_dt),
        created_at=now,
        updated_at=now,
    )
    try:
        session.add(consent)
        session.commit()
    except OperationalError as e:
        ensure_credit_consent_table()
        try:
            session.add(consent)
            session.commit()
        except OperationalError:
            set_flash(request,
                      "Erro ao gravar autorização (tabela não criada no banco). Verifique migrations/permissões do DB.")
            return RedirectResponse("/credito", status_code=303)

    url = f"{_public_base_url(request)}/consent/aceite/{token}"
    request.session["consent_link_url"] = url
    set_flash(request, f"Link de aceite: {url}")
    return RedirectResponse("/credito", status_code=303)


@app.get("/consent/aceite/{token}", response_class=HTMLResponse)
async def consent_accept_page(
        request: Request,
        session: Session = Depends(get_session),
        token: str = "",
) -> HTMLResponse:
    """Página pública para aceite eletrônico (sem login)."""
    try:
        payload = _verify_consent_token(token)
    except Exception as e:
        return render(
            "error.html",
            request=request,
            context={
                "current_user": None,
                "current_company": None,
                "role": "public",
                "message": f"Link inválido/expirado: {e}",
            },
            status_code=400,
        )

    company = session.get(Company, int(payload.get("company_id") or 0))
    client = session.get(Client, int(payload.get("client_id") or 0))
    if not company or not client:
        return render(
            "error.html",
            request=request,
            context={
                "current_user": None,
                "current_company": None,
                "role": "public",
                "message": "Link inválido: cliente/empresa não encontrados.",
            },
            status_code=404,
        )

    if not ensure_credit_consent_table():
        return render(
            "error.html",
            request=request,
            context={
                "current_user": None,
                "current_company": company,
                "role": "public",
                "message": "Sistema de aceite ainda não está configurado (tabela ausente). Avise a empresa responsável.",
            },
            status_code=500,
        )

    latest = _get_latest_consent(session, company_id=company.id, client_id=client.id)
    if latest:
        _refresh_consent_status(latest)
        if latest.status == "valida":
            return render(
                "success.html",
                request=request,
                context={
                    "current_user": None,
                    "current_company": company,
                    "role": "public",
                    "message": "Autorização já registrada. Obrigado!",
                },
            )

    terms_html = templates_env.from_string(CREDIT_CONSENT_TERMS_HTML).render(term_version=CREDIT_CONSENT_TERM_VERSION)

    return render(
        "consent_accept.html",
        request=request,
        context={
            "current_user": None,
            "current_company": company,
            "role": "public",
            "company": company,
            "client": client,
            "terms_html": terms_html,
            "term_version": CREDIT_CONSENT_TERM_VERSION,
        },
    )


@app.post("/consent/aceite/{token}")
async def consent_accept_submit(
        request: Request,
        session: Session = Depends(get_session),
        token: str = "",
        agree: str = Form(""),
        signed_by_name: str = Form(""),
        doc_last4: str = Form(""),
) -> Response:
    """Registra o aceite eletrônico como um CreditConsent válido."""
    try:
        payload = _verify_consent_token(token)
    except Exception as e:
        set_flash(request, f"Link inválido/expirado: {e}")
        return RedirectResponse(f"/consent/aceite/{token}", status_code=303)

    if not str(agree).strip():
        set_flash(request, "É necessário marcar o aceite.")
        return RedirectResponse(f"/consent/aceite/{token}", status_code=303)

    company_id = int(payload.get("company_id") or 0)
    client_id = int(payload.get("client_id") or 0)
    created_by_user_id = int(payload.get("created_by_user_id") or 0)

    company = session.get(Company, company_id)
    client = session.get(Client, client_id)
    if not company or not client:
        set_flash(request, "Link inválido: cliente/empresa não encontrados.")
        return RedirectResponse(f"/consent/aceite/{token}", status_code=303)

    dl4 = _digits_only(doc_last4)[-4:]
    if dl4:
        doc = _digits_only(client.cnpj or "")
        if doc and not doc.endswith(dl4):
            set_flash(request, "Os 4 últimos dígitos não conferem.")
            return RedirectResponse(f"/consent/aceite/{token}", status_code=303)

    now = utcnow()
    expires_at = now + timedelta(days=CREDIT_CONSENT_MAX_DAYS)

    evidence = {
        "method": "clickwrap",
        "term_version": CREDIT_CONSENT_TERM_VERSION,
        "term_sha256": _terms_sha256(),
        "token_iat": int(payload.get("iat") or 0),
        "token_exp": int(payload.get("exp") or 0),
        "ip": _request_ip(request),
        "user_agent": request.headers.get("user-agent") or "",
        "accepted_at_utc": now.isoformat(),
    }

    if not ensure_credit_consent_table():
        set_flash(request, "Sistema de aceite não está configurado (tabela ausente).")
        return RedirectResponse(f"/consent/aceite/{token}", status_code=303)

    latest = _get_latest_consent(session, company_id=company_id, client_id=client_id)
    if latest:
        _refresh_consent_status(latest)
        if latest.status == "pendente":
            latest.status = "valida"
            latest.signed_by_name = (signed_by_name or client.name or "").strip()
            latest.signed_by_document = _digits_only(client.cnpj or "")
            latest.signed_at = now
            latest.expires_at = expires_at
            latest.updated_at = now
            latest.notes = "[aceite-eletronico]\n" + json.dumps(evidence, ensure_ascii=False)
            session.add(latest)
            session.commit()
        elif latest.status != "valida":
            consent = CreditConsent(
                company_id=company_id,
                client_id=client_id,
                created_by_user_id=created_by_user_id or 0,
                kind=CREDIT_CONSENT_KIND_SCR,
                status="valida",
                signed_by_name=(signed_by_name or client.name or "").strip(),
                signed_by_document=_digits_only(client.cnpj or ""),
                signed_at=now,
                expires_at=expires_at,
                notes="[aceite-eletronico]\n" + json.dumps(evidence, ensure_ascii=False),
                created_at=now,
                updated_at=now,
            )
            session.add(consent)
            session.commit()
    else:
        consent = CreditConsent(
            company_id=company_id,
            client_id=client_id,
            created_by_user_id=created_by_user_id or 0,
            kind=CREDIT_CONSENT_KIND_SCR,
            status="valida",
            signed_by_name=(signed_by_name or client.name or "").strip(),
            signed_by_document=_digits_only(client.cnpj or ""),
            signed_at=now,
            expires_at=expires_at,
            notes="[aceite-eletronico]\n" + json.dumps(evidence, ensure_ascii=False),
            created_at=now,
            updated_at=now,
        )
        session.add(consent)
        session.commit()

    return render(
        "success.html",
        request=request,
        context={
            "current_user": None,
            "current_company": company,
            "role": "public",
            "message": "Autorização registrada com sucesso. Você já pode fechar esta página.",
        },
    )


@app.post("/credito/consultar")
@require_role({"admin", "equipe"})
async def credit_consult(
        request: Request,
        background_tasks: BackgroundTasks,
        session: Session = Depends(get_session),
        document_type: str = Form("cnpj"),
        document_value: str = Form(""),
) -> Response:
    ctx = get_tenant_context(request, session)
    assert ctx is not None

    # Garante tabela em ambientes sem Alembic
    if not ensure_credit_consent_table():
        set_flash(request, "Sistema de aceite não está configurado (migração pendente no banco).")
        return RedirectResponse("/credito", status_code=303)

    current_client = _get_client_for_credit(ctx, request, session)
    if not current_client:
        set_flash(request, "Selecione um cliente.")
        return RedirectResponse("/credito", status_code=303)

    consent = _get_latest_consent(session, company_id=ctx.company.id, client_id=current_client.id)
    if not consent:
        set_flash(request, "Envie uma autorização (PDF) ou gere um link de aceite eletrônico antes de consultar.")
        return RedirectResponse("/credito", status_code=303)
    _refresh_consent_status(consent)
    if consent.status != "valida":
        set_flash(request, "Autorização expirada/revogada. Envie uma nova.")
        return RedirectResponse("/credito", status_code=303)

    doc_val = document_value.strip() or (current_client.cnpj if document_type == "cnpj" else "")
    doc_val = _digits_only(doc_val)

    report = CreditReport(
        company_id=ctx.company.id,
        client_id=current_client.id,
        created_by_user_id=ctx.user.id,
        provider="directdata",
        document_type=("cpf" if document_type == "cpf" else "cnpj"),
        document_value=doc_val,
        async_enabled=DIRECTDATA_ASYNC,
        status="processing",
        created_at=utcnow(),
        updated_at=utcnow(),
    )
    session.add(report)
    session.commit()
    session.refresh(report)
    # Dispara em background para não travar o request (Render).
    background_tasks.add_task(_credit_run_scr_and_update, report.id)

    set_flash(request, "Consulta iniciada. Aguarde e clique em Atualizar em instantes.")
    return RedirectResponse(f"/credito/{report.id}", status_code=303)


@app.get("/credito/{report_id}", response_class=HTMLResponse)
@require_login
async def credit_report_detail(request: Request, session: Session = Depends(get_session),
                               report_id: int = 0) -> HTMLResponse:
    ctx = get_tenant_context(request, session)
    if not ctx:
        request.session.clear()
        return RedirectResponse("/login", status_code=303)

    report = session.get(CreditReport, int(report_id))
    if not report or report.company_id != ctx.company.id:
        set_flash(request, "Relatório não encontrado.")
        return RedirectResponse("/credito", status_code=303)

    if not ensure_can_access_client(ctx, report.client_id):
        set_flash(request, "Sem permissão.")
        return RedirectResponse("/credito", status_code=303)
    _coerce_credit_report_nullable_fields(report)

    _coerce_credit_report_nullable_fields(report)

    return render(
        "credit_report_detail.html",
        request=request,
        context={
            "current_user": ctx.user,
            "current_company": ctx.company,
            "role": ctx.membership.role,
            "current_client": get_client_or_none(session, ctx.company.id, report.client_id),
            "report": report,
        },
    )


@app.post("/credito/{report_id}/atualizar")
@require_role({"admin", "equipe"})
async def credit_report_refresh(request: Request, background_tasks: BackgroundTasks,
                                session: Session = Depends(get_session), report_id: int = 0) -> Response:
    ctx = get_tenant_context(request, session)
    assert ctx is not None

    # Garante tabela em ambientes sem Alembic
    if not ensure_credit_consent_table():
        set_flash(request, "Sistema de aceite não está configurado (migração pendente no banco).")
        return RedirectResponse("/credito", status_code=303)

    report = session.get(CreditReport, int(report_id))
    if not report or report.company_id != ctx.company.id:
        set_flash(request, "Relatório não encontrado.")
        return RedirectResponse("/credito", status_code=303)

    now = utcnow()
    force = (request.query_params.get("force") or "").strip() == "1"

    # Por padrão, "Atualizar" só consulta o status (poll) e NÃO inicia nova cobrança.
    if report.status != "processing" and not force:
        set_flash(request, "Relatório já finalizado. Para nova consulta, use 'Consultar' novamente.")
        return RedirectResponse(f"/credito/{report.id}", status_code=303)

    # Evita storm de cliques / refresh em sequência (reduz consumo)
    try:
        if (now - _as_aware_utc(report.updated_at)).total_seconds() < DIRECTDATA_POLL_MIN_INTERVAL_S:
            set_flash(request, "Aguarde alguns segundos antes de atualizar novamente.")
            return RedirectResponse(f"/credito/{report.id}", status_code=303)
    except Exception:
        pass

    if force:
        # Reconsulta do zero (pode gerar nova cobrança)
        report.status = "processing"
        report.consulta_uid = ""
        report.resultado_id = 0
        report.http_status = 0
        report.message = ""
        report.raw_json = ""
        report.updated_at = now
        session.add(report)
        session.commit()
        background_tasks.add_task(_credit_run_scr_and_update, report.id)
        set_flash(request, "Reconsulta iniciada (nova chamada). Recarregue em instantes.")
        return RedirectResponse(f"/credito/{report.id}", status_code=303)

    # Se ainda não temos consultaUid, não dispare uma nova chamada (evita cobrar de novo)
    if not (report.consulta_uid or "").strip():
        report.updated_at = now
        session.add(report)
        session.commit()
        set_flash(request, "Consulta ainda iniciando (sem consultaUid). Aguarde alguns segundos e atualize novamente.")
        return RedirectResponse(f"/credito/{report.id}", status_code=303)

    report.updated_at = now
    session.add(report)
    session.commit()

    background_tasks.add_task(_credit_run_scr_and_update, report.id)
    set_flash(request, "Verificando processamento (sem nova cobrança). Recarregue em instantes.")
    return RedirectResponse(f"/credito/{report.id}", status_code=303)


@app.post("/credito/{report_id}/criar_negocio")
@require_role({"admin", "equipe"})
async def credit_report_create_deal(request: Request, session: Session = Depends(get_session),
                                    report_id: int = 0) -> Response:
    ctx = get_tenant_context(request, session)
    assert ctx is not None

    # Garante tabela em ambientes sem Alembic
    if not ensure_credit_consent_table():
        set_flash(request, "Sistema de aceite não está configurado (migração pendente no banco).")
        return RedirectResponse("/credito", status_code=303)

    report = session.get(CreditReport, int(report_id))
    if not report or report.company_id != ctx.company.id:
        set_flash(request, "Relatório não encontrado.")
        return RedirectResponse("/credito", status_code=303)

    _coerce_credit_report_nullable_fields(report)

    if report.status != "done":
        set_flash(request, "Finalize a consulta antes de criar negócio.")
        return RedirectResponse(f"/credito/{report.id}", status_code=303)

    client = get_client_or_none(session, ctx.company.id, report.client_id)
    if not client:
        set_flash(request, "Cliente inválido.")
        return RedirectResponse(f"/credito/{report.id}", status_code=303)

    title = f"Reperfilamento de crédito — {client.name}"
    demand = "Avaliar SCR e oportunidades de reperfilamento/melhoria de custo de dívida."
    notes = (
        f"[SCR] Total: R$ {report.carteira_total_brl:.2f} | Vencido: R$ {report.carteira_vencido_brl:.2f} | "
        f"Instituições: {report.quantidade_instituicoes} | Score: {report.score} | Potencial: {report.potential_label}"
    )

    deal = BusinessDeal(
        company_id=ctx.company.id,
        client_id=client.id,
        created_by_user_id=ctx.user.id,
        owner_user_id=ctx.user.id,
        title=title,
        demand=demand,
        notes=notes,
        stage="qualificacao",
        service_name="BaaS - Analise de Crédito",
        value_estimate_brl=max(0.0, report.carteira_total_brl * 0.01),
        probability_pct=30 if report.potential_label == "alto" else 15,
        next_step="Agendar call e solicitar contratos/CCBs.",
        next_step_date="",
        source="SCR/Direct Data",
        created_at=utcnow(),
        updated_at=utcnow(),
    )
    session.add(deal)
    session.commit()
    session.refresh(deal)

    set_flash(request, "Negócio criado no CRM.")
    return RedirectResponse(f"/negocios/{deal.id}", status_code=303)


@app.post("/credito/{report_id}/gerar_tarefas")
@require_role({"admin", "equipe"})
async def credit_report_generate_tasks(request: Request, session: Session = Depends(get_session),
                                       report_id: int = 0) -> Response:
    ctx = get_tenant_context(request, session)
    assert ctx is not None

    # Garante tabela em ambientes sem Alembic
    if not ensure_credit_consent_table():
        set_flash(request, "Sistema de aceite não está configurado (migração pendente no banco).")
        return RedirectResponse("/credito", status_code=303)

    report = session.get(CreditReport, int(report_id))
    if not report or report.company_id != ctx.company.id:
        set_flash(request, "Relatório não encontrado.")
        return RedirectResponse("/credito", status_code=303)

    _coerce_credit_report_nullable_fields(report)

    if report.status != "done":
        set_flash(request, "Finalize a consulta antes de gerar tarefas.")
        return RedirectResponse(f"/credito/{report.id}", status_code=303)

    client = get_client_or_none(session, ctx.company.id, report.client_id)
    if not client:
        set_flash(request, "Cliente inválido.")
        return RedirectResponse(f"/credito/{report.id}", status_code=303)

    defaults = [
        ("Solicitar contratos/CCBs das operações", "Pedir ao cliente os contratos/CCBs e condições atuais."),
        ("Agendar reunião de diagnóstico", "Reunião para entender estrutura de dívida e objetivos."),
        ("Montar mapa de dívidas (saldo/taxa/prazo/garantias)", "Consolidar dados para simulações."),
        ("Simular alternativas de reperfilamento", "Comparar cenários e preparar proposta."),
    ]

    created = 0
    for title, desc in defaults:
        t = Task(
            company_id=ctx.company.id,
            client_id=client.id,
            created_by_user_id=ctx.user.id,
            assignee_user_id=ctx.user.id,
            title=title,
            description=desc,
            status="nao_iniciada",
            priority="media",
            due_date="",
            visible_to_client=(title.startswith("Solicitar") or title.startswith("Agendar")),
            client_action=(title.startswith("Solicitar")),
            created_at=utcnow(),
            updated_at=utcnow(),
        )
        session.add(t)
        created += 1

    session.commit()
    set_flash(request, f"{created} tarefas criadas.")
    return RedirectResponse("/tarefas", status_code=303)


TEMPLATES.setdefault("admin_partners.html", r"""{% extends "base.html" %}
{% block content %}
<div class="d-flex justify-content-between align-items-start flex-wrap gap-2 mb-3">
  <div>
    <div class="h4 mb-0">Parceiros / Produtos</div>
    <div class="muted">Cadastre parceiros, produtos, regras de elegibilidade e defaults do simulador.</div>
  </div>
  <div class="d-flex gap-2">
    <a class="btn btn-outline-secondary" href="/simulador">Abrir simulador</a>
  </div>
</div>

<div class="row g-3">
  <div class="col-lg-4">
    <div class="card p-3">
      <div class="fw-semibold mb-2">Novo parceiro</div>
      <form method="post" action="/admin/parceiros/add" class="row g-2">
        <div class="col-12">
          <label class="form-label">Nome</label>
          <input class="form-control" name="name" required>
        </div>
        <div class="col-md-6">
          <label class="form-label">Tipo</label>
          <select class="form-select" name="kind">
            {% for k in partner_kind_options %}
              <option value="{{ k }}">{{ k }}</option>
            {% endfor %}
          </select>
        </div>
        <div class="col-md-6">
          <label class="form-label">Prioridade</label>
          <input class="form-control" name="priority" value="100">
        </div>
        <div class="col-md-6">
          <label class="form-label">Contato</label>
          <input class="form-control" name="contact_name">
        </div>
        <div class="col-md-6">
          <label class="form-label">E-mail</label>
          <input class="form-control" name="contact_email">
        </div>
        <div class="col-12">
          <label class="form-label">Observações</label>
          <textarea class="form-control" name="notes" rows="3"></textarea>
        </div>
        <div class="col-12">
          <button class="btn btn-primary w-100">Salvar parceiro</button>
        </div>
      </form>
    </div>
  </div>

  <div class="col-lg-8">
    <div class="card p-3">
      <div class="fw-semibold mb-2">Novo produto por parceiro</div>
      <form method="post" action="/admin/parceiros/products/add" class="row g-2">
        <div class="col-md-4">
          <label class="form-label">Parceiro</label>
          <select class="form-select" name="partner_id" required>
            <option value="">-- selecione --</option>
            {% for p in partners %}
              <option value="{{ p.id }}">{{ p.name }}</option>
            {% endfor %}
          </select>
        </div>
        <div class="col-md-4">
          <label class="form-label">Nome do produto</label>
          <input class="form-control" name="name" required>
        </div>
        <div class="col-md-4">
          <label class="form-label">Categoria</label>
          <select class="form-select" name="category">
            {% for c in category_options %}
              <option value="{{ c }}">{{ c }}</option>
            {% endfor %}
          </select>
        </div>

        <div class="col-md-4">
          <label class="form-label">Tipo</label>
          <select class="form-select" name="product_type">
            {% for c in product_type_options %}
              <option value="{{ c }}">{{ c or "(vazio)" }}</option>
            {% endfor %}
          </select>
        </div>
        <div class="col-md-2">
          <label class="form-label">Prioridade</label>
          <input class="form-control" name="priority" value="100">
        </div>
        <div class="col-md-3">
          <label class="form-label">Visível simulador</label>
          <select class="form-select" name="visible_in_simulator">
            <option value="1">sim</option>
            <option value="0">não</option>
          </select>
        </div>
        <div class="col-md-3">
          <label class="form-label">Exige garantia</label>
          <select class="form-select" name="requires_collateral">
            <option value="0">não</option>
            <option value="1">sim</option>
          </select>
        </div>

        <div class="col-md-3">
          <label class="form-label">Fat. mín mensal</label>
          <input class="form-control" name="min_revenue_monthly_brl" placeholder="0">
        </div>
        <div class="col-md-3">
          <label class="form-label">Score total mín</label>
          <input class="form-control" name="min_score_total" placeholder="0">
        </div>
        <div class="col-md-3">
          <label class="form-label">Score financeiro mín</label>
          <input class="form-control" name="min_score_financial" placeholder="0">
        </div>
        <div class="col-md-3">
          <label class="form-label">Alavancagem máx (x)</label>
          <input class="form-control" name="max_debt_ratio" placeholder="0">
        </div>

        <div class="col-md-3">
          <label class="form-label">Ticket mín</label>
          <input class="form-control" name="min_ticket_brl" placeholder="0">
        </div>
        <div class="col-md-3">
          <label class="form-label">Ticket máx</label>
          <input class="form-control" name="max_ticket_brl" placeholder="0">
        </div>
        <div class="col-md-3">
          <label class="form-label">UFs permitidas (JSON)</label>
          <input class="form-control" name="allowed_states_json" placeholder='["SP","PR"]'>
        </div>
        <div class="col-md-3">
          <label class="form-label">LTV padrão (%)</label>
          <input class="form-control" name="default_ltv_pct" placeholder="0">
        </div>

        <div class="col-md-3">
          <label class="form-label">Tipo empréstimo</label>
          <input class="form-control" name="default_loan_type" placeholder="Capital de giro">
        </div>
        <div class="col-md-3">
          <label class="form-label">Amortização</label>
          <select class="form-select" name="default_amortization">
            <option value="price">price</option>
            <option value="sac">sac</option>
            <option value="americano">americano</option>
          </select>
        </div>
        <div class="col-md-2">
          <label class="form-label">Taxa %</label>
          <input class="form-control" name="default_rate_pct" placeholder="1,79">
        </div>
        <div class="col-md-2">
          <label class="form-label">Base</label>
          <select class="form-select" name="default_rate_base">
            <option value="am">am</option>
            <option value="aa">aa</option>
          </select>
        </div>
        <div class="col-md-2">
          <label class="form-label">Prazo padr.</label>
          <input class="form-control" name="default_term_months" placeholder="24">
        </div>

        <div class="col-md-2">
          <label class="form-label">Prazo mín</label>
          <input class="form-control" name="term_min_months" placeholder="0">
        </div>
        <div class="col-md-2">
          <label class="form-label">Prazo máx</label>
          <input class="form-control" name="term_max_months" placeholder="0">
        </div>
        <div class="col-md-2">
          <label class="form-label">Carência</label>
          <input class="form-control" name="default_grace_months" placeholder="0">
        </div>
        <div class="col-md-2">
          <label class="form-label">IO extra</label>
          <input class="form-control" name="default_io_months" placeholder="0">
        </div>
        <div class="col-md-2">
          <label class="form-label">Tarifa</label>
          <input class="form-control" name="default_fee_amount_brl" placeholder="0">
        </div>
        <div class="col-md-2">
          <label class="form-label">Seguro</label>
          <input class="form-control" name="default_monthly_insurance_brl" placeholder="0">
        </div>
        <div class="col-md-2">
          <label class="form-label">Taxa admin</label>
          <input class="form-control" name="default_monthly_admin_fee_brl" placeholder="0">
        </div>

        <div class="col-12">
          <label class="form-label">Diretrizes / observações</label>
          <textarea class="form-control" name="notes" rows="3" placeholder="Ex.: aceita operação com garantia, foco em portabilidade, exige faturamento recorrente..."></textarea>
        </div>

        <div class="col-12">
          <button class="btn btn-primary w-100">Salvar produto</button>
        </div>
      </form>
    </div>
  </div>

  <div class="col-12">
    <div class="card p-3">
      <div class="fw-semibold mb-2">Catálogo atual</div>
      {% if partner_rows %}
        <div class="accordion" id="partnersAcc">
          {% for row in partner_rows %}
            <div class="accordion-item">
              <h2 class="accordion-header">
                <button class="accordion-button {% if not loop.first %}collapsed{% endif %}" type="button" data-bs-toggle="collapse" data-bs-target="#p{{ row.partner.id }}">
                  {{ row.partner.name }} · {{ row.partner.kind }} · {{ row.products|length }} produto(s)
                </button>
              </h2>
              <div id="p{{ row.partner.id }}" class="accordion-collapse collapse {% if loop.first %}show{% endif %}" data-bs-parent="#partnersAcc">
                <div class="accordion-body">
                  <div class="muted small mb-3">{{ row.partner.notes or "Sem observações." }}</div>
                  {% if row.products %}
                    <div class="table-responsive">
                      <table class="table table-sm align-middle">
                        <thead>
                          <tr>
                            <th>Produto</th>
                            <th>Categoria</th>
                            <th>Taxa padrão</th>
                            <th>Prazo</th>
                            <th>Regras</th>
                            <th></th>
                          </tr>
                        </thead>
                        <tbody>
                          {% for p in row.products %}
                            <tr>
                              <td>
                                <div class="fw-semibold">{{ p.name }}</div>
                                <div class="muted small">{{ p.product_type or "-" }}</div>
                              </td>
                              <td>{{ p.category }}</td>
                              <td>{{ p.default_rate_pct }}% {{ p.default_rate_base }}</td>
                              <td>{{ p.default_term_months or "-" }}m</td>
                              <td class="small">
                                fat mín {{ p.min_revenue_monthly_brl or 0 }} ·
                                score mín {{ p.min_score_total or 0 }} ·
                                ticket {{ p.min_ticket_brl or 0 }}-{{ p.max_ticket_brl or 0 }}
                              </td>
                              <td class="text-end">
                                <form method="post" action="/admin/parceiros/products/{{ p.id }}/toggle">
                                  <button class="btn btn-outline-secondary btn-sm">{% if p.is_active %}Inativar{% else %}Ativar{% endif %}</button>
                                </form>
                              </td>
                            </tr>
                          {% endfor %}
                        </tbody>
                      </table>
                    </div>
                  {% else %}
                    <div class="muted small">Nenhum produto cadastrado.</div>
                  {% endif %}
                </div>
              </div>
            </div>
          {% endfor %}
        </div>
      {% else %}
        <div class="muted">Nenhum parceiro cadastrado ainda.</div>
      {% endif %}
    </div>
  </div>
</div>
{% endblock %}
""")


@app.get("/admin/parceiros", response_class=HTMLResponse)
@require_role({"admin"})
async def admin_partners_page(request: Request, session: Session = Depends(get_session)) -> HTMLResponse:
    ctx = get_tenant_context(request, session)
    assert ctx is not None
    ensure_partner_tables()

    partners = session.exec(
        select(Partner).where(Partner.company_id == ctx.company.id).order_by(Partner.priority.asc(), Partner.name.asc())
    ).all()
    products = session.exec(
        select(PartnerProduct).where(PartnerProduct.company_id == ctx.company.id).order_by(PartnerProduct.priority.asc(), PartnerProduct.created_at.desc())
    ).all()
    grouped: list[dict[str, Any]] = []
    for partner in partners:
        grouped.append(
            {
                "partner": partner,
                "products": [p for p in products if int(p.partner_id or 0) == int(partner.id or 0)],
            }
        )
    return render(
        "admin_partners.html",
        request=request,
        context={
            "current_user": ctx.user,
            "current_company": ctx.company,
            "role": ctx.membership.role,
            "current_client": get_client_or_none(session, ctx.company.id, get_active_client_id(request, session, ctx)),
            "partners": partners,
            "partner_rows": grouped,
            "partner_kind_options": _partner_kind_options(),
            "category_options": _partner_product_category_options(),
            "product_type_options": _partner_product_type_options(),
        },
    )


@app.post("/admin/parceiros/add")
@require_role({"admin"})
async def admin_partners_add(
    request: Request,
    name: str = Form(...),
    kind: str = Form("banco"),
    contact_name: str = Form(""),
    contact_email: str = Form(""),
    contact_phone: str = Form(""),
    priority: str = Form("100"),
    notes: str = Form(""),
    session: Session = Depends(get_session),
) -> Response:
    ctx = get_tenant_context(request, session)
    assert ctx is not None
    ensure_partner_tables()

    partner = Partner(
        company_id=ctx.company.id,
        name=(name or "").strip(),
        kind=(kind or "").strip() or "banco",
        contact_name=(contact_name or "").strip(),
        contact_email=(contact_email or "").strip(),
        contact_phone=(contact_phone or "").strip(),
        priority=int(priority or 100) if str(priority or "").strip().isdigit() else 100,
        notes=(notes or "").strip(),
        updated_at=utcnow(),
    )
    session.add(partner)
    session.commit()
    set_flash(request, "Parceiro salvo.")
    return RedirectResponse("/admin/parceiros", status_code=303)


@app.post("/admin/parceiros/products/add")
@require_role({"admin"})
async def admin_partner_products_add(
    request: Request,
    partner_id: int = Form(...),
    name: str = Form(...),
    category: str = Form("credito"),
    product_type: str = Form(""),
    priority: str = Form("100"),
    visible_in_simulator: str = Form("1"),
    requires_collateral: str = Form("0"),
    min_revenue_monthly_brl: str = Form("0"),
    max_debt_ratio: str = Form("0"),
    min_score_total: str = Form("0"),
    min_score_financial: str = Form("0"),
    min_ticket_brl: str = Form("0"),
    max_ticket_brl: str = Form("0"),
    allowed_states_json: str = Form(""),
    default_ltv_pct: str = Form("0"),
    default_loan_type: str = Form(""),
    default_amortization: str = Form("price"),
    default_rate_pct: str = Form("0"),
    default_rate_base: str = Form("am"),
    default_term_months: str = Form("0"),
    term_min_months: str = Form("0"),
    term_max_months: str = Form("0"),
    default_grace_months: str = Form("0"),
    default_io_months: str = Form("0"),
    default_fee_amount_brl: str = Form("0"),
    default_monthly_insurance_brl: str = Form("0"),
    default_monthly_admin_fee_brl: str = Form("0"),
    notes: str = Form(""),
    session: Session = Depends(get_session),
) -> Response:
    ctx = get_tenant_context(request, session)
    assert ctx is not None
    ensure_partner_tables()

    partner = session.get(Partner, partner_id)
    if not partner or int(partner.company_id or 0) != int(ctx.company.id or 0):
        set_flash(request, "Parceiro inválido.")
        return RedirectResponse("/admin/parceiros", status_code=303)

    row = PartnerProduct(
        company_id=ctx.company.id,
        partner_id=int(partner_id),
        name=(name or "").strip(),
        category=(category or "").strip() or "credito",
        product_type=(product_type or "").strip(),
        priority=int(priority or 100) if str(priority or "").strip().isdigit() else 100,
        visible_in_simulator=str(visible_in_simulator) == "1",
        requires_collateral=str(requires_collateral) == "1",
        min_revenue_monthly_brl=float(str(min_revenue_monthly_brl or "0").replace(",", ".")),
        max_debt_ratio=float(str(max_debt_ratio or "0").replace(",", ".")),
        min_score_total=float(str(min_score_total or "0").replace(",", ".")),
        min_score_financial=float(str(min_score_financial or "0").replace(",", ".")),
        min_ticket_brl=float(str(min_ticket_brl or "0").replace(",", ".")),
        max_ticket_brl=float(str(max_ticket_brl or "0").replace(",", ".")),
        allowed_states_json=(allowed_states_json or "").strip(),
        default_ltv_pct=float(str(default_ltv_pct or "0").replace(",", ".")),
        default_loan_type=(default_loan_type or "").strip(),
        default_amortization=(default_amortization or "price").strip(),
        default_rate_pct=float(str(default_rate_pct or "0").replace(",", ".")),
        default_rate_base=(default_rate_base or "am").strip(),
        default_term_months=int(default_term_months or 0) if str(default_term_months or "").strip().isdigit() else 0,
        term_min_months=int(term_min_months or 0) if str(term_min_months or "").strip().isdigit() else 0,
        term_max_months=int(term_max_months or 0) if str(term_max_months or "").strip().isdigit() else 0,
        default_grace_months=int(default_grace_months or 0) if str(default_grace_months or "").strip().isdigit() else 0,
        default_io_months=int(default_io_months or 0) if str(default_io_months or "").strip().isdigit() else 0,
        default_fee_amount_brl=float(str(default_fee_amount_brl or "0").replace(",", ".")),
        default_monthly_insurance_brl=float(str(default_monthly_insurance_brl or "0").replace(",", ".")),
        default_monthly_admin_fee_brl=float(str(default_monthly_admin_fee_brl or "0").replace(",", ".")),
        notes=(notes or "").strip(),
        updated_at=utcnow(),
    )
    session.add(row)
    session.commit()
    set_flash(request, "Produto salvo.")
    return RedirectResponse("/admin/parceiros", status_code=303)


@app.post("/admin/parceiros/products/{product_id}/toggle")
@require_role({"admin"})
async def admin_partner_products_toggle(request: Request, product_id: int, session: Session = Depends(get_session)) -> Response:
    ctx = get_tenant_context(request, session)
    assert ctx is not None
    row = session.get(PartnerProduct, product_id)
    if not row or int(row.company_id or 0) != int(ctx.company.id or 0):
        set_flash(request, "Produto não encontrado.")
        return RedirectResponse("/admin/parceiros", status_code=303)

    row.is_active = not bool(row.is_active)
    row.updated_at = utcnow()
    session.add(row)
    session.commit()
    set_flash(request, "Status do produto atualizado.")
    return RedirectResponse("/admin/parceiros", status_code=303)



# ==============================
# SIMULADOR DE EMPRÉSTIMOS + PDF
# ==============================
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
from enum import Enum
import calendar
import io
from typing import Any, Optional, TypedDict

from fastapi import Form
from fastapi.responses import StreamingResponse

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas as rl_canvas
from reportlab.lib.utils import ImageReader
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_LEFT, TA_RIGHT


class LoanAmortization(str, Enum):
    PRICE = "price"          # parcela fixa (Sistema Francês)
    SAC = "sac"              # amortização constante
    AMERICANO = "americano"  # juros + balloon


class LoanRateBase(str, Enum):
    AM = "am"  # ao mês
    AA = "aa"  # ao ano


def _to_decimal(v: str) -> Decimal:
    """Compat alias for older simulator code."""
    return _dec(v)

def _dec(x: Any) -> Decimal:
    if x is None:
        return Decimal("0")
    if isinstance(x, Decimal):
        return x
    s = str(x).strip()
    if not s:
        return Decimal("0")
    # "1.234,56" -> "1234.56"
    s = s.replace(".", "").replace(",", ".")
    return Decimal(s)


def _d2(x: Decimal) -> Decimal:
    return x.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _normalize_pct_to_rate(pct_str: str) -> Decimal:
    """
    Entrada esperada em %:
      - "1,79" => 0.0179
      - "12"   => 0.12
    """
    pct = _dec(pct_str)
    return pct / Decimal("100")


def _annual_to_monthly_rate(rate_aa: Decimal) -> Decimal:
    # (1+i_a)^(1/12)-1
    return Decimal(str((1.0 + float(rate_aa)) ** (1.0 / 12.0) - 1.0))


def _month_add(dt: date, months: int) -> date:
    y = dt.year + (dt.month - 1 + months) // 12
    m = (dt.month - 1 + months) % 12 + 1
    last = calendar.monthrange(y, m)[1]
    d = min(dt.day, last)
    return date(y, m, d)


def _brl(x: Decimal) -> str:
    s = f"{x:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"R$ {s}"


@dataclass(frozen=True)
class LoanInput:
    loan_type: str
    amortization: LoanAmortization
    rate: Decimal
    rate_base: LoanRateBase
    term_months: int

    principal: Decimal
    collateral_value: Decimal
    ltv_pct: Decimal

    start_date: date
    grace_months: int
    io_months: int

    fee_amount: Decimal
    monthly_insurance: Decimal
    monthly_admin_fee: Decimal

    borrower_name: str
    notes: str


@dataclass(frozen=True)
class LoanRow:
    n: int
    due_date: date
    payment: Decimal
    interest: Decimal
    amort: Decimal
    fees: Decimal
    insurance: Decimal
    balance: Decimal


@dataclass(frozen=True)
class LoanSimResult:
    inp: LoanInput
    schedule: list[LoanRow]
    monthly_rate: Decimal
    total_payment: Decimal
    total_interest: Decimal
    total_amort: Decimal
    total_fees: Decimal
    total_insurance: Decimal
    first_payment: Decimal


def build_loan_input(
    *,
    loan_type: str,
    amortization: str,
    rate_pct: str,
    rate_base: str,
    term_months: int,
    principal: str,
    collateral_value: str,
    ltv_pct: str,
    start_date: date,
    grace_months: int,
    io_months: int,
    fee_amount: str,
    monthly_insurance: str,
    monthly_admin_fee: str,
    borrower_name: str,
    notes: str,
) -> LoanInput:
    amort = LoanAmortization(amortization)
    rb = LoanRateBase(rate_base)

    principal_d = _d2(_dec(principal))
    collateral_d = _d2(_dec(collateral_value))
    ltv_d = _d2(_dec(ltv_pct))

    if principal_d <= 0 and collateral_d > 0 and ltv_d > 0:
        principal_d = _d2(collateral_d * (ltv_d / Decimal("100")))

    if ltv_d <= 0 and principal_d > 0 and collateral_d > 0:
        ltv_d = _d2((principal_d / collateral_d) * Decimal("100"))

    if term_months <= 0:
        raise ValueError("Prazo inválido.")
    if principal_d <= 0:
        raise ValueError("Informe valor do empréstimo (ou valor do bem + LTV).")

    return LoanInput(
        loan_type=(loan_type or "").strip() or "Empréstimo",
        amortization=amort,
        rate=_normalize_pct_to_rate(rate_pct),
        rate_base=rb,
        term_months=int(term_months),
        principal=principal_d,
        collateral_value=collateral_d,
        ltv_pct=ltv_d,
        start_date=start_date,
        grace_months=max(0, int(grace_months or 0)),
        io_months=max(0, int(io_months or 0)),
        fee_amount=_d2(_dec(fee_amount)),
        monthly_insurance=_d2(_dec(monthly_insurance)),
        monthly_admin_fee=_d2(_dec(monthly_admin_fee)),
        borrower_name=(borrower_name or "").strip(),
        notes=(notes or "").strip(),
    )


# --- Adapter: compatibilidade com /simulador/proposta ---
class LoanSimInputs:
    """Compat layer: rotas antigas chamam LoanSimInputs.from_form(...)."""

    @classmethod
    def from_form(cls, **form) -> "LoanInput":
        # build_loan_input espera taxa em percentual (string), ex: "1,79" -> 1.79%
        return build_loan_input(
            loan_type=form.get("loan_type", "Empréstimo"),
            amortization=form.get("amortization", "price"),
            rate_pct=str(form.get("rate", "1,79") or "1,79"),
            rate_base=form.get("rate_base", "am"),
            term_months=int(form.get("term_months", 24) or 24),
            principal=str(form.get("principal", "") or ""),
            collateral_value=str(form.get("collateral_value", "") or ""),
            ltv_pct=str(form.get("ltv_pct", "") or ""),
            start_date=date.today(),
            grace_months=int(form.get("grace_months", 0) or 0),
            io_months=int(form.get("io_months", 0) or 0),
            fee_amount=str(form.get("fee_amount", "0") or "0"),
            monthly_insurance=str(form.get("monthly_insurance", "0") or "0"),
            monthly_admin_fee=str(form.get("monthly_admin_fee", "0") or "0"),
            borrower_name=str(form.get("borrower_name", "") or ""),
            notes=str(form.get("notes", "") or ""),
        )

def simulate_loan(inp: LoanInput) -> LoanSimResult:
    if inp.rate_base == LoanRateBase.AM:
        i = inp.rate
    else:
        i = _annual_to_monthly_rate(inp.rate)

    i = Decimal(str(float(i)))
    principal = inp.principal
    bal = principal

    grace = inp.grace_months
    io_only = inp.io_months
    amort_months = max(1, inp.term_months - grace - io_only)

    price_pmt = Decimal("0")
    if inp.amortization == LoanAmortization.PRICE:
        if i == 0:
            price_pmt = _d2(principal / Decimal(amort_months))
        else:
            denom = Decimal("1") - Decimal(str((1.0 + float(i)) ** (-amort_months)))
            price_pmt = _d2(principal * i / denom)

    sac_amort = Decimal("0")
    if inp.amortization == LoanAmortization.SAC:
        sac_amort = _d2(principal / Decimal(amort_months))

    schedule: list[LoanRow] = []
    total_interest = Decimal("0")
    total_payment = Decimal("0")
    total_amort = Decimal("0")
    total_fees = Decimal("0")
    total_ins = Decimal("0")

    for n in range(1, inp.term_months + 1):
        due = _month_add(inp.start_date, n)
        fees = inp.monthly_admin_fee
        ins = inp.monthly_insurance

        if n <= grace + io_only:
            interest = _d2(bal * i)
            amort = Decimal("0")
            base_pmt = _d2(interest)
        else:
            if inp.amortization == LoanAmortization.AMERICANO:
                interest = _d2(bal * i)
                amort = _d2(bal) if n == inp.term_months else Decimal("0")
                base_pmt = _d2(interest + amort)
            elif inp.amortization == LoanAmortization.SAC:
                interest = _d2(bal * i)
                amort = sac_amort if sac_amort <= bal else _d2(bal)
                base_pmt = _d2(interest + amort)
            else:
                interest = _d2(bal * i)
                amort = _d2(price_pmt - interest)
                if amort > bal:
                    amort = _d2(bal)
                if amort < 0:
                    amort = Decimal("0")
                base_pmt = _d2(interest + amort)

        bal = _d2(bal - amort)
        if bal < 0:
            bal = Decimal("0")

        payment = _d2(base_pmt + fees + ins)

        schedule.append(
            LoanRow(
                n=n,
                due_date=due,
                payment=payment,
                interest=interest,
                amort=amort,
                fees=fees,
                insurance=ins,
                balance=bal,
            )
        )

        total_interest += interest
        total_amort += amort
        total_fees += fees
        total_ins += ins
        total_payment += payment

    total_fees += inp.fee_amount
    total_payment += inp.fee_amount

    first_payment = schedule[0].payment if schedule else Decimal("0")

    return LoanSimResult(
        inp=inp,
        schedule=schedule,
        monthly_rate=_d2(i),
        total_payment=_d2(total_payment),
        total_interest=_d2(total_interest),
        total_amort=_d2(total_amort),
        total_fees=_d2(total_fees),
        total_insurance=_d2(total_ins),
        first_payment=_d2(first_payment),
    )


def render_loan_pdf(res: LoanSimResult) -> bytes:
    buf = io.BytesIO()
    c = rl_canvas.Canvas(buf, pagesize=A4)
    w, h = A4

    # Logo
    logo_path = (STATIC_DIR / "logo.png") if "STATIC_DIR" in globals() else None
    if logo_path and logo_path.exists():
        try:
            img = ImageReader(str(logo_path))
            c.drawImage(img, 20 * mm, h - 32 * mm, width=45 * mm, height=16 * mm, mask="auto")
        except Exception:
            pass

    c.setFont("Helvetica-Bold", 14)
    c.drawString(70 * mm, h - 24 * mm, "Simulação de Empréstimo")
    c.setFont("Helvetica", 9)
    c.drawRightString(w - 20 * mm, h - 24 * mm, datetime.now().strftime("%d/%m/%Y %H:%M"))

    y = h - 38 * mm

    def kv(key: str, val: str) -> None:
        nonlocal y
        c.setFont("Helvetica-Bold", 9)
        c.drawString(20 * mm, y, key)
        c.setFont("Helvetica", 9)
        c.drawString(58 * mm, y, val)
        y -= 5 * mm

    inp = res.inp
    kv("Cliente:", inp.borrower_name or "-")
    kv("Tipo:", inp.loan_type)
    kv("Amortização:", inp.amortization.value.upper())
    kv("Prazo:", f"{inp.term_months} meses")
    kv("Taxa:", f"{(inp.rate * Decimal("100")):.2f} {'a.m.' if inp.rate_base==LoanRateBase.AM else 'a.a.'}")
    kv("Taxa mensal (calc):", f"{(res.monthly_rate * Decimal("100")):.2f} a.m.")
    kv("Valor empréstimo:", _brl(inp.principal))
    if inp.collateral_value > 0:
        kv("Valor do bem:", _brl(inp.collateral_value))
        kv("LTV:", f"{inp.ltv_pct:.2f}%")
    kv("Carência (juros):", f"{inp.grace_months} meses")
    kv("Juros-only extra:", f"{inp.io_months} meses")
    kv("Parcela inicial:", _brl(res.first_payment))
    y -= 2 * mm

    c.setFont("Helvetica-Bold", 10)
    c.drawString(20 * mm, y, "Totais")
    y -= 6 * mm
    kv("Total pago:", _brl(res.total_payment))
    kv("Total juros:", _brl(res.total_interest))
    kv("Total amortização:", _brl(res.total_amort))
    kv("Tarifas/Taxas:", _brl(res.total_fees))
    kv("Seguros:", _brl(res.total_insurance))

    # Disclaimer obrigatório
    y -= 2 * mm
    c.setFont("Helvetica-Bold", 9)
    c.drawString(20 * mm, y, "Aviso:")
    y -= 5 * mm
    c.setFont("Helvetica", 8)
    disclaimer = (
        "Esta é apenas uma SIMULAÇÃO e não constitui proposta de crédito. "
        "A concessão está sujeita à análise de crédito, políticas internas, "
        "condições de mercado e aprovação final."
    )
    # wrap lines
    max_w = w - 40 * mm
    words = disclaimer.split()
    line = ""
    lines = []
    for wd in words:
        test = (line + " " + wd).strip()
        if c.stringWidth(test, "Helvetica", 8) <= max_w:
            line = test
        else:
            lines.append(line)
            line = wd
    if line:
        lines.append(line)
    for ln in lines:
        c.drawString(20 * mm, y, ln)
        y -= 4.2 * mm

    if inp.notes:
        y -= 2 * mm
        c.setFont("Helvetica-Bold", 9)
        c.drawString(20 * mm, y, "Observações:")
        y -= 5 * mm
        c.setFont("Helvetica", 8)
        # simple wrap
        words = inp.notes.split()
        line = ""
        for wd in words:
            test = (line + " " + wd).strip()
            if c.stringWidth(test, "Helvetica", 8) <= max_w:
                line = test
            else:
                c.drawString(20 * mm, y, line)
                y -= 4.2 * mm
                line = wd
        if line:
            c.drawString(20 * mm, y, line)

    # Table pages
    c.showPage()

    def table_header(title: str) -> float:
        # logo on every page
        if logo_path and logo_path.exists():
            try:
                img = ImageReader(str(logo_path))
                c.drawImage(img, 20 * mm, h - 28 * mm, width=40 * mm, height=14 * mm, mask="auto")
            except Exception:
                pass
        c.setFont("Helvetica-Bold", 12)
        c.drawString(65 * mm, h - 22 * mm, title)
        c.setFont("Helvetica", 8)
        c.drawRightString(w - 20 * mm, h - 22 * mm, datetime.now().strftime("%d/%m/%Y %H:%M"))
        y0 = h - 34 * mm
        c.setFont("Helvetica-Bold", 8)
        cols = [("#", 20*mm), ("Venc.", 30*mm), ("Parcela", 55*mm), ("Juros", 85*mm), ("Amort.", 110*mm), ("Encargos", 135*mm), ("Saldo", 165*mm)]
        for name, x in cols:
            c.drawString(x, y0, name)
        c.line(20*mm, y0-2*mm, w-20*mm, y0-2*mm)
        return y0 - 7*mm

    y = table_header("Cronograma de Pagamentos")
    c.setFont("Helvetica", 8)
    rows_per_page = 34

    for idx, row in enumerate(res.schedule, start=1):
        if (idx - 1) % rows_per_page == 0 and idx != 1:
            # footer disclaimer on page
            c.setFont("Helvetica-Oblique", 7)
            c.drawString(20*mm, 12*mm, "Simulação – não constitui proposta de crédito. Sujeito à análise e aprovação.")
            c.showPage()
            y = table_header("Cronograma (cont.)")
            c.setFont("Helvetica", 8)

        encargos = _d2(row.fees + row.insurance)
        c.drawString(20*mm, y, str(row.n))
        c.drawString(30*mm, y, row.due_date.strftime("%d/%m/%Y"))
        c.drawRightString(77*mm, y, _brl(row.payment))
        c.drawRightString(107*mm, y, _brl(row.interest))
        c.drawRightString(132*mm, y, _brl(row.amort))
        c.drawRightString(157*mm, y, _brl(encargos))
        c.drawRightString(w-20*mm, y, _brl(row.balance))
        y -= 5 * mm

    c.setFont("Helvetica-Oblique", 7)
    c.drawString(20*mm, 12*mm, "Simulação – não constitui proposta de crédito. Sujeito à análise e aprovação.")
    c.save()
    return buf.getvalue()



def _json_list_load(value: str) -> list[str]:
    try:
        raw = json.loads((value or "").strip() or "[]")
        return [str(x).strip() for x in raw if str(x).strip()]
    except Exception:
        return []


def _latest_client_snapshot(session: Session, *, company_id: int, client_id: int) -> Optional[ClientSnapshot]:
    return session.exec(
        select(ClientSnapshot)
        .where(ClientSnapshot.company_id == company_id, ClientSnapshot.client_id == client_id)
        .order_by(ClientSnapshot.created_at.desc())
    ).first()


def _estimate_partner_product_ticket(client: Client, snapshot: Optional[ClientSnapshot], product: PartnerProduct) -> float:
    revenue = float((snapshot.revenue_monthly_brl if snapshot else 0.0) or client.revenue_monthly_brl or 0.0)
    debt = float((snapshot.debt_total_brl if snapshot else 0.0) or client.debt_total_brl or 0.0)

    base = 0.0
    if revenue > 0:
        base = revenue * 0.35
    if debt > 0:
        base = max(base, debt * 0.70)

    if product.min_ticket_brl > 0:
        base = max(base, float(product.min_ticket_brl))
    if product.max_ticket_brl > 0:
        base = min(base or float(product.max_ticket_brl), float(product.max_ticket_brl))

    return round(max(base, 0.0), 2)


def _match_partner_product_for_client(
    *,
    client: Client,
    snapshot: Optional[ClientSnapshot],
    product: PartnerProduct,
    partner: Partner,
) -> dict[str, Any]:
    revenue = float((snapshot.revenue_monthly_brl if snapshot else 0.0) or client.revenue_monthly_brl or 0.0)
    debt = float((snapshot.debt_total_brl if snapshot else 0.0) or client.debt_total_brl or 0.0)
    cash = float((snapshot.cash_balance_brl if snapshot else 0.0) or client.cash_balance_brl or 0.0)
    score_total_val = float(snapshot.score_total if snapshot else 0.0)
    score_fin_val = float(snapshot.score_financial if snapshot else score_financial_simple(revenue, debt, cash))
    debt_ratio = (debt / revenue) if revenue > 0 else 0.0

    score = 50.0
    reasons: list[str] = []
    blockers: list[str] = []

    if product.min_revenue_monthly_brl > 0:
        if revenue >= float(product.min_revenue_monthly_brl):
            score += 12
            reasons.append(f"faturamento atende mínimo de R$ {product.min_revenue_monthly_brl:,.0f}")
        else:
            blockers.append(f"faturamento abaixo do mínimo de R$ {product.min_revenue_monthly_brl:,.0f}")

    if product.min_score_total > 0:
        if score_total_val >= float(product.min_score_total):
            score += 10
            reasons.append(f"score total {score_total_val:.1f} atende mínimo")
        else:
            blockers.append(f"score total abaixo do mínimo ({product.min_score_total:.1f})")

    if product.min_score_financial > 0:
        if score_fin_val >= float(product.min_score_financial):
            score += 10
            reasons.append(f"score financeiro {score_fin_val:.1f} atende mínimo")
        else:
            blockers.append(f"score financeiro abaixo do mínimo ({product.min_score_financial:.1f})")

    if product.max_debt_ratio > 0:
        if debt_ratio <= float(product.max_debt_ratio):
            score += 8
            reasons.append(f"alavancagem dentro do limite ({debt_ratio:.2f}x)")
        else:
            blockers.append(f"alavancagem acima do limite ({product.max_debt_ratio:.2f}x)")

    allowed_states = {s.upper() for s in _json_list_load(product.allowed_states_json)}
    state = (client.state or "").strip().upper()
    if allowed_states:
        if state and state in allowed_states:
            score += 5
            reasons.append(f"UF {state} coberta pelo produto")
        else:
            blockers.append("UF do cliente fora da cobertura do produto")

    if product.requires_collateral:
        score -= 4
        reasons.append("produto normalmente exige garantia real ou recebíveis")

    if product.category == "consultoria":
        if score_total_val < 65 or score_fin_val < 60:
            score += 12
            reasons.append("perfil sugere espaço para consultoria financeira")
    elif product.category == "ferramenta":
        if score_total_val < 75:
            score += 8
            reasons.append("ferramenta pode apoiar maturidade operacional")
    else:
        if revenue > 0 and debt > 0:
            score += 6
            reasons.append("há base para comparação de crédito/reestruturação")

    eligible = len(blockers) == 0
    ticket = _estimate_partner_product_ticket(client, snapshot, product)

    return {
        "eligible": eligible,
        "score": round(max(0.0, min(score, 100.0)), 2),
        "reasons": reasons,
        "blockers": blockers,
        "ticket_brl": ticket,
        "partner": partner,
        "product": product,
    }


def _collect_partner_product_matches(
    *,
    session: Session,
    company_id: int,
    client: Optional[Client],
) -> list[dict[str, Any]]:
    if not client:
        return []
    snapshot = _latest_client_snapshot(session, company_id=company_id, client_id=int(client.id or 0))
    products = session.exec(
        select(PartnerProduct).where(
            PartnerProduct.company_id == company_id,
            PartnerProduct.is_active == True,
        ).order_by(PartnerProduct.priority.asc(), PartnerProduct.created_at.desc())
    ).all()
    partners = session.exec(
        select(Partner).where(
            Partner.company_id == company_id,
            Partner.is_active == True,
        )
    ).all()
    partner_by_id = {int(p.id or 0): p for p in partners}
    rows: list[dict[str, Any]] = []
    for product in products:
        partner = partner_by_id.get(int(product.partner_id or 0))
        if not partner:
            continue
        rows.append(_match_partner_product_for_client(client=client, snapshot=snapshot, product=product, partner=partner))
    rows.sort(key=lambda x: (0 if x["eligible"] else 1, -float(x["score"]), int(x["product"].priority or 100), x["partner"].name.lower()))
    return rows

SIMULADOR_TEMPLATE = r"""
{% extends "base.html" %}
{% block content %}
<div class="container" style="max-width: 1160px;">
  <div class="d-flex justify-content-between align-items-start flex-wrap gap-2 mt-3">
    <div>
      <h3 class="mb-1">Simulador de Empréstimo</h3>
      <div class="muted">Pré-simulação usando os parâmetros padrão dos produtos cadastrados por parceiro.</div>
    </div>
    {% if current_client %}
      <span class="badge text-bg-light border">Cliente ativo: {{ current_client.name }}</span>
    {% endif %}
  </div>

  {% if recommended_products %}
    <div class="card p-3 mt-3">
      <div class="d-flex justify-content-between align-items-center mb-2">
        <div class="fw-semibold">Motor de ofertas — produtos sugeridos</div>
        <div class="muted small">Ordenado por aderência e regras do produto.</div>
      </div>
      <div class="table-responsive">
        <table class="table table-sm align-middle">
          <thead>
            <tr>
              <th>Parceiro</th>
              <th>Produto</th>
              <th>Categoria</th>
              <th>Status</th>
              <th>Score</th>
              <th>Ticket sug.</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {% for row in recommended_products[:12] %}
              <tr>
                <td>{{ row.partner.name }}</td>
                <td>
                  <div class="fw-semibold">{{ row.product.name }}</div>
                  <div class="muted small">{{ row.product.product_type or row.product.category }}</div>
                </td>
                <td>{{ row.product.category }}</td>
                <td>
                  {% if row.eligible %}
                    <span class="badge text-bg-success">Elegível</span>
                  {% else %}
                    <span class="badge text-bg-warning">Revisar</span>
                  {% endif %}
                </td>
                <td>{{ row.score }}</td>
                <td>R$ {{ row.ticket_brl | round(2) }}</td>
                <td class="text-end">
                  <a class="btn btn-outline-primary btn-sm" href="/simulador?partner_product_id={{ row.product.id }}">Simular</a>
                </td>
              </tr>
              {% if row.reasons or row.blockers %}
              <tr>
                <td colspan="7" class="pt-0">
                  <div class="small muted">
                    {% if row.reasons %}<b>Motivos:</b> {{ row.reasons | join("; ") }}.{% endif %}
                    {% if row.blockers %} <b>Pontos de atenção:</b> {{ row.blockers | join("; ") }}.{% endif %}
                  </div>
                </td>
              </tr>
              {% endif %}
            {% endfor %}
          </tbody>
        </table>
      </div>
    </div>
  {% endif %}

  <form method="post" action="/simulador/pdf" class="card p-3 mt-3">
    <div class="row g-2">
      <div class="col-md-4">
        <label class="form-label">Produto / parceiro</label>
        <select class="form-select" name="partner_product_id" id="sim_partner_product_id">
          <option value="">-- Escolher manualmente --</option>
          {% for p in partner_products %}
            <option value="{{ p.id }}" {% if selected_product and selected_product.id == p.id %}selected{% endif %}>
              {{ p.partner_name }} — {{ p.name }}
            </option>
          {% endfor %}
        </select>
        <div class="form-text">Ao selecionar, o formulário é pré-preenchido com taxa, prazo, amortização e tarifas do produto.</div>
      </div>

      <div class="col-md-4">
        <label class="form-label">Cliente (nome)</label>
        <input class="form-control" name="borrower_name" id="sim_borrower_name" placeholder="Nome do cliente" value="{{ current_client.name if current_client else '' }}">
      </div>

      <div class="col-md-4">
        <label class="form-label">Cliente (opcional)</label>
        <select class="form-select" name="client_id" id="sim_client_id">
          <option value="">-- (sem cliente) --</option>
          {% for c in clients %}
            <option value="{{ c.id }}" {% if current_client and current_client.id == c.id %}selected{% endif %}>{{ c.name }}</option>
          {% endfor %}
        </select>
        <div class="form-text">Selecione para habilitar “Gerar Proposta” e puxar o cliente ativo para o motor.</div>
      </div>

      <div class="col-md-6">
        <label class="form-label">Tipo de empréstimo</label>
        <input class="form-control" name="loan_type" id="sim_loan_type" placeholder="Ex.: Crédito com garantia, Capital de giro" value="{{ selected_defaults.loan_type }}">
      </div>

      <div class="col-md-3">
        <label class="form-label">Amortização</label>
        <select class="form-select" name="amortization" id="sim_amortization">
          <option value="price" {% if selected_defaults.amortization == "price" %}selected{% endif %}>PRICE (parcela fixa)</option>
          <option value="sac" {% if selected_defaults.amortization == "sac" %}selected{% endif %}>SAC (amortização constante)</option>
          <option value="americano" {% if selected_defaults.amortization == "americano" %}selected{% endif %}>Americano (juros + quitação final)</option>
        </select>
      </div>

      <div class="col-md-3">
        <label class="form-label">Taxa (%)</label>
        <input class="form-control" name="rate_pct" id="sim_rate_pct" placeholder="Ex.: 1,79" value="{{ selected_defaults.rate_pct }}">
      </div>

      <div class="col-md-3">
        <label class="form-label">Base</label>
        <select class="form-select" name="rate_base" id="sim_rate_base">
          <option value="am" {% if selected_defaults.rate_base == "am" %}selected{% endif %}>ao mês</option>
          <option value="aa" {% if selected_defaults.rate_base == "aa" %}selected{% endif %}>ao ano</option>
        </select>
      </div>

      <div class="col-md-3">
        <label class="form-label">Prazo (meses)</label>
        <input class="form-control" name="term_months" id="sim_term_months" value="{{ selected_defaults.term_months }}">
      </div>

      <div class="col-md-3">
        <label class="form-label">Carência (meses – juros only)</label>
        <input class="form-control" name="grace_months" id="sim_grace_months" value="{{ selected_defaults.grace_months }}">
      </div>

      <div class="col-md-3">
        <label class="form-label">Juros-only extra (meses)</label>
        <input class="form-control" name="io_months" id="sim_io_months" value="{{ selected_defaults.io_months }}">
      </div>

      <div class="col-md-4">
        <label class="form-label">Valor do empréstimo (R$)</label>
        <input class="form-control" name="principal" id="sim_principal" placeholder="Ex.: 100000" value="{{ selected_defaults.principal }}">
        <div class="form-text">Se preencher valor do bem + LTV, pode deixar em branco.</div>
      </div>

      <div class="col-md-4">
        <label class="form-label">Valor do bem (garantia) (R$)</label>
        <input class="form-control" name="collateral_value" id="sim_collateral_value" placeholder="Ex.: 200000" value="{{ selected_defaults.collateral_value }}">
      </div>

      <div class="col-md-4">
        <label class="form-label">LTV (%)</label>
        <input class="form-control" name="ltv_pct" id="sim_ltv_pct" placeholder="Ex.: 50" value="{{ selected_defaults.ltv_pct }}">
      </div>

      <div class="col-md-4">
        <label class="form-label">Tarifa de abertura (R$)</label>
        <input class="form-control" name="fee_amount" id="sim_fee_amount" value="{{ selected_defaults.fee_amount }}">
      </div>

      <div class="col-md-4">
        <label class="form-label">Seguro mensal (R$)</label>
        <input class="form-control" name="monthly_insurance" id="sim_monthly_insurance" value="{{ selected_defaults.monthly_insurance }}">
      </div>

      <div class="col-md-4">
        <label class="form-label">Taxa admin mensal (R$)</label>
        <input class="form-control" name="monthly_admin_fee" id="sim_monthly_admin_fee" value="{{ selected_defaults.monthly_admin_fee }}">
      </div>

      <div class="col-12">
        <label class="form-label">Observações</label>
        <textarea class="form-control" name="notes" id="sim_notes" rows="3" placeholder="Condições, garantias, CET, etc.">{{ selected_defaults.notes }}</textarea>
      </div>

      <div class="col-12 d-flex gap-2 mt-2">
        <button class="btn btn-primary" type="submit">Gerar PDF</button>
        <button class="btn btn-outline-secondary" formaction="/simulador/json" formmethod="post" type="submit">Ver JSON</button>
      </div>
    </div>
  </form>
</div>

<script>
(function(){
  const catalog = {{ product_defaults_json | safe }};
  const sel = document.getElementById("sim_partner_product_id");
  if (!sel) return;

  const apply = () => {
    const item = catalog[String(sel.value || "")];
    if (!item) return;

    const setValue = (id, value) => {
      const el = document.getElementById(id);
      if (!el || value === null || value === undefined) return;
      el.value = value;
    };

    setValue("sim_loan_type", item.loan_type || "");
    setValue("sim_rate_pct", item.rate_pct || "");
    setValue("sim_rate_base", item.rate_base || "am");
    setValue("sim_term_months", item.term_months || "");
    setValue("sim_grace_months", item.grace_months || 0);
    setValue("sim_io_months", item.io_months || 0);
    setValue("sim_principal", item.principal || "");
    setValue("sim_ltv_pct", item.ltv_pct || "");
    setValue("sim_fee_amount", item.fee_amount || 0);
    setValue("sim_monthly_insurance", item.monthly_insurance || 0);
    setValue("sim_monthly_admin_fee", item.monthly_admin_fee || 0);

    const amort = document.getElementById("sim_amortization");
    if (amort && item.amortization) amort.value = item.amortization;

    const notes = document.getElementById("sim_notes");
    if (notes && item.notes !== undefined) notes.value = item.notes;
  };

  sel.addEventListener("change", apply);
  apply();
})();
</script>
{% endblock %}
"""



@app.get("/simulador", response_class=HTMLResponse)
@require_login
async def simulador_page(request: Request, partner_product_id: int = 0, session: Session = Depends(get_session)) -> HTMLResponse:
    if "simulador.html" not in TEMPLATES:
        TEMPLATES["simulador.html"] = SIMULADOR_TEMPLATE

    ctx = get_tenant_context(request, session)
    if not ctx:
        request.session.clear()
        return RedirectResponse("/login", status_code=303)

    clients = session.exec(select(Client).where(Client.company_id == ctx.company.id).order_by(Client.name)).all()
    current_client = get_client_or_none(session, ctx.company.id, get_active_client_id(request, session, ctx))

    partner_products_rows = []
    product_defaults: dict[str, Any] = {}
    selected_product = None
    recommended = _collect_partner_product_matches(session=session, company_id=ctx.company.id, client=current_client)

    partner_products = session.exec(
        select(PartnerProduct, Partner)
        .join(Partner, Partner.id == PartnerProduct.partner_id)
        .where(
            PartnerProduct.company_id == ctx.company.id,
            PartnerProduct.is_active == True,
            Partner.is_active == True,
            PartnerProduct.visible_in_simulator == True,
        )
        .order_by(Partner.priority.asc(), PartnerProduct.priority.asc(), Partner.name.asc(), PartnerProduct.name.asc())
    ).all()

    selected_match = None
    if partner_product_id:
        selected_match = next((row for row in recommended if int(row["product"].id or 0) == int(partner_product_id)), None)

    for product, partner in partner_products:
        partner_products_rows.append(
            {
                "id": product.id,
                "name": product.name,
                "partner_name": partner.name,
                "category": product.category,
            }
        )
        est_principal = 0.0
        row_match = next((row for row in recommended if int(row["product"].id or 0) == int(product.id or 0)), None)
        if row_match:
            est_principal = float(row_match.get("ticket_brl") or 0.0)
        product_defaults[str(product.id)] = {
            "loan_type": (product.default_loan_type or product.name or "").strip(),
            "amortization": (product.default_amortization or "price").strip(),
            "rate_pct": (str(round(float(product.default_rate_pct or 0.0), 4)).replace(".", ",")) if product.default_rate_pct else "",
            "rate_base": (product.default_rate_base or "am").strip(),
            "term_months": int(product.default_term_months or product.term_max_months or product.term_min_months or 24),
            "grace_months": int(product.default_grace_months or 0),
            "io_months": int(product.default_io_months or 0),
            "principal": est_principal or "",
            "ltv_pct": float(product.default_ltv_pct or 0.0) or "",
            "fee_amount": float(product.default_fee_amount_brl or 0.0),
            "monthly_insurance": float(product.default_monthly_insurance_brl or 0.0),
            "monthly_admin_fee": float(product.default_monthly_admin_fee_brl or 0.0),
            "notes": f"Parceiro: {partner.name}\nProduto: {product.name}\n{(product.notes or '').strip()}".strip(),
        }
        if partner_product_id and int(product.id or 0) == int(partner_product_id):
            selected_product = product

    selected_defaults = {
        "loan_type": "",
        "amortization": "price",
        "rate_pct": "1,79",
        "rate_base": "am",
        "term_months": 24,
        "grace_months": 0,
        "io_months": 0,
        "principal": "",
        "collateral_value": "",
        "ltv_pct": "",
        "fee_amount": "0",
        "monthly_insurance": "0",
        "monthly_admin_fee": "0",
        "notes": "",
    }
    if selected_product:
        selected_defaults.update(product_defaults.get(str(selected_product.id), {}))
    return render(
        "simulador.html",
        request=request,
        context={
            "title": "Simulador",
            "clients": clients,
            "current_client": current_client,
            "partner_products": partner_products_rows,
            "recommended_products": recommended,
            "selected_product": selected_product,
            "selected_defaults": selected_defaults,
            "product_defaults_json": json.dumps(product_defaults, ensure_ascii=False),
        },
    )



@app.post("/simulador/json", response_class=JSONResponse)
@require_login
async def simulador_json(
    request: Request,
    loan_type: str = Form("Empréstimo"),
    amortization: str = Form("price"),
    rate_pct: str = Form("1,79"),
    rate_base: str = Form("am"),
    term_months: int = Form(24),
    principal: str = Form(""),
    collateral_value: str = Form(""),
    ltv_pct: str = Form(""),
    grace_months: int = Form(0),
    io_months: int = Form(0),
    fee_amount: str = Form("0"),
    monthly_insurance: str = Form("0"),
    monthly_admin_fee: str = Form("0"),
    borrower_name: str = Form(""),
    notes: str = Form(""),
    partner_product_id: str = Form(""),
    session: Session = Depends(get_session),
) -> JSONResponse:
    _ = get_tenant_context(request, session)
    inp = build_loan_input(
        loan_type=loan_type,
        amortization=amortization,
        rate_pct=rate_pct,
        rate_base=rate_base,
        term_months=term_months,
        principal=principal,
        collateral_value=collateral_value,
        ltv_pct=ltv_pct,
        start_date=date.today(),
        grace_months=grace_months,
        io_months=io_months,
        fee_amount=fee_amount,
        monthly_insurance=monthly_insurance,
        monthly_admin_fee=monthly_admin_fee,
        borrower_name=borrower_name,
        notes=(f"[Produto #{partner_product_id}] " + notes.strip()) if str(partner_product_id or "").strip() else notes,
    )
    res = simulate_loan(inp)
    return JSONResponse({
        "inputs": {
            "loan_type": inp.loan_type,
            "amortization": inp.amortization.value,
            "rate": float(inp.rate),
            "rate_base": inp.rate_base.value,
            "term_months": inp.term_months,
            "principal": float(inp.principal),
            "collateral_value": float(inp.collateral_value),
            "ltv_pct": float(inp.ltv_pct),
            "grace_months": inp.grace_months,
            "io_months": inp.io_months,
            "fee_amount": float(inp.fee_amount),
            "monthly_insurance": float(inp.monthly_insurance),
            "monthly_admin_fee": float(inp.monthly_admin_fee),
            "borrower_name": inp.borrower_name,
            "notes": inp.notes,
        },
        "totals": {
            "monthly_rate": float(res.monthly_rate),
            "first_payment": float(res.first_payment),
            "total_payment": float(res.total_payment),
            "total_interest": float(res.total_interest),
            "total_amort": float(res.total_amort),
            "total_fees": float(res.total_fees),
            "total_insurance": float(res.total_insurance),
        },
        "schedule": [
            {
                "n": r.n,
                "due_date": r.due_date.isoformat(),
                "payment": float(r.payment),
                "interest": float(r.interest),
                "amort": float(r.amort),
                "fees": float(r.fees),
                "insurance": float(r.insurance),
                "balance": float(r.balance),
            }
            for r in res.schedule
        ]
    })


@app.post("/simulador/pdf")
@require_login
async def simulador_pdf(
    request: Request,
    loan_type: str = Form("Empréstimo"),
    amortization: str = Form("price"),
    rate_pct: str = Form("1,79"),
    rate_base: str = Form("am"),
    term_months: int = Form(24),
    principal: str = Form(""),
    collateral_value: str = Form(""),
    ltv_pct: str = Form(""),
    grace_months: int = Form(0),
    io_months: int = Form(0),
    fee_amount: str = Form("0"),
    monthly_insurance: str = Form("0"),
    monthly_admin_fee: str = Form("0"),
    borrower_name: str = Form(""),
    notes: str = Form(""),
    partner_product_id: str = Form(""),
    session: Session = Depends(get_session),
):
    _ = get_tenant_context(request, session)

    inp = build_loan_input(
        loan_type=loan_type,
        amortization=amortization,
        rate_pct=rate_pct,
        rate_base=rate_base,
        term_months=term_months,
        principal=principal,
        collateral_value=collateral_value,
        ltv_pct=ltv_pct,
        start_date=date.today(),
        grace_months=grace_months,
        io_months=io_months,
        fee_amount=fee_amount,
        monthly_insurance=monthly_insurance,
        monthly_admin_fee=monthly_admin_fee,
        borrower_name=borrower_name,
        notes=(f"[Produto #{partner_product_id}] " + notes.strip()) if str(partner_product_id or "").strip() else notes,
    )
    res = simulate_loan(inp)
    pdf_bytes = render_loan_pdf(res)
    headers = {"Content-Disposition": 'inline; filename="simulacao_emprestimo_maffezzolli.pdf"'}
    return StreamingResponse(io.BytesIO(pdf_bytes), media_type="application/pdf", headers=headers)


# ----------------------------
# UI Banner + News (v1)
# ----------------------------

import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime

_UI_CACHE: dict[tuple[int, str], tuple[float, Any]] = {}
_UI_CACHE_TTL_BANNER_SEC = 60
_UI_CACHE_TTL_NEWS_SEC = 600

BANNERS_DIR = STATIC_DIR / "banners"
BANNERS_DIR.mkdir(parents=True, exist_ok=True)

_DEFAULT_NEWS_FEEDS = [
    {"name": "UOL Economia", "url": "http://www3.uol.com.br/xml/midiaindoor/economia.xml", "sort_order": 0},
    {"name": "Money Times", "url": "https://www.moneytimes.com.br/feed/", "sort_order": 10},
    {"name": "BM&C News", "url": "https://bmcnews.com.br/feed/", "sort_order": 20},
    {"name": "InfoMoney", "url": "https://www.infomoney.com.br/feed/", "sort_order": 30},
]


def _ui_cache_get(company_id: int, key: str) -> Any:
    now = datetime.now(timezone.utc).timestamp()
    k = (company_id, key)
    item = _UI_CACHE.get(k)
    if not item:
        return None
    ts, data = item
    ttl = _UI_CACHE_TTL_BANNER_SEC if key == "banner" else _UI_CACHE_TTL_NEWS_SEC
    if (now - ts) > ttl:
        _UI_CACHE.pop(k, None)
        return None
    return data


def _ui_cache_set(company_id: int, key: str, data: Any) -> None:
    now = datetime.now(timezone.utc).timestamp()
    _UI_CACHE[(company_id, key)] = (now, data)


def _ui_cache_bust(company_id: int) -> None:
    for k in list(_UI_CACHE.keys()):
        if k[0] == company_id:
            _UI_CACHE.pop(k, None)


def _ui_safe_int(v: Any, default: int = 0) -> int:
    try:
        return int(str(v).strip())
    except Exception:
        return default


def _ui_parse_date(s: str) -> Optional[datetime]:
    s = (s or "").strip()
    if not s:
        return None
    try:
        dt = parsedate_to_datetime(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def _ui_parse_rss_atom(xml_bytes: bytes) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    if not xml_bytes:
        return items

    try:
        root = ET.fromstring(xml_bytes)
    except Exception:
        return items

    channel = root.find("channel")
    if channel is not None:
        source = (channel.findtext("title") or "").strip()
        for it in channel.findall("item"):
            title = (it.findtext("title") or "").strip()
            link = (it.findtext("link") or "").strip()
            pub = _ui_parse_date(it.findtext("pubDate") or "")
            if title and link:
                items.append({"title": title, "url": link, "published_dt": pub, "source": source})
        return items

    ns = {"atom": "http://www.w3.org/2005/Atom"}
    entries = root.findall("entry") or root.findall("atom:entry", ns)
    source = (root.findtext("title") or root.findtext("atom:title", default="", namespaces=ns) or "").strip()
    for e in entries:
        title = (e.findtext("title") or e.findtext("atom:title", default="", namespaces=ns) or "").strip()
        link_el = e.find("link") or e.find("atom:link", ns)
        link = (link_el.attrib.get("href") if link_el is not None else "") or ""
        pub = _ui_parse_date((e.findtext("updated") or e.findtext("atom:updated", default="", namespaces=ns) or "").strip())
        if title and link:
            items.append({"title": title, "url": link.strip(), "published_dt": pub, "source": source})
    return items


async def _ui_fetch_bytes(url: str) -> bytes:
    url = (url or "").strip()
    if not url:
        return b""
    headers = {"User-Agent": "MaffezzolliCapitalApp/1.0 (+rss)"}
    try:
        async with httpx.AsyncClient(timeout=12, headers=headers, follow_redirects=True) as client:
            r = await client.get(url)
            if 200 <= r.status_code < 300:
                return r.content or b""
    except Exception:
        return b""
    return b""


async def _ui_load_news(company_id: int, session: Session, limit: int = 10) -> list[dict[str, Any]]:
    cached = _ui_cache_get(company_id, "news")
    if cached is not None:
        return cached

    ensure_ui_tables()

    try:
        feeds = session.exec(
            select(UiNewsFeed)
            .where(UiNewsFeed.company_id == company_id, UiNewsFeed.is_active == True)
            .order_by(UiNewsFeed.sort_order, UiNewsFeed.id)
        ).all()
    except Exception:
        _ui_cache_set(company_id, "news", [])
        return []

    if not feeds:
        try:
            for f in _DEFAULT_NEWS_FEEDS:
                session.add(
                    UiNewsFeed(
                        company_id=company_id,
                        name=f["name"],
                        url=f["url"],
                        sort_order=f["sort_order"],
                        is_active=True,
                    )
                )
            session.commit()
            feeds = session.exec(
                select(UiNewsFeed)
                .where(UiNewsFeed.company_id == company_id, UiNewsFeed.is_active == True)
                .order_by(UiNewsFeed.sort_order, UiNewsFeed.id)
            ).all()
        except Exception:
            _ui_cache_set(company_id, "news", [])
            return []

    all_items: list[dict[str, Any]] = []
    for f in feeds:
        xml = await _ui_fetch_bytes(f.url)
        parsed = _ui_parse_rss_atom(xml)
        for it in parsed[:25]:
            it["source"] = it.get("source") or f.name
            all_items.append(it)

    dedup: dict[str, dict[str, Any]] = {}
    for it in all_items:
        u = it.get("url") or ""
        if u and u not in dedup:
            dedup[u] = it

    items2 = list(dedup.values())
    items2.sort(
        key=lambda x: x.get("published_dt") or datetime(1970, 1, 1, tzinfo=timezone.utc),
        reverse=True,
    )
    items2 = items2[: max(1, min(limit, 30))]

    out = []
    sao_paulo_tz = timezone(timedelta(hours=-3))
    for it in items2:
        dt = it.get("published_dt")
        out.append(
            {
                "title": it.get("title") or "",
                "url": it.get("url") or "",
                "source": it.get("source") or "",
                "published": dt.astimezone(sao_paulo_tz).strftime("%d/%m %H:%M") if isinstance(dt, datetime) else "",
            }
        )

    _ui_cache_set(company_id, "news", out)
    return out

def _ui_load_banner(company_id: int, session: Session) -> list[dict[str, Any]]:
    cached = _ui_cache_get(company_id, "banner")
    if cached is not None:
        return cached

    ensure_ui_tables()

    try:
        slides = session.exec(
            select(UiBannerSlide)
            .where(UiBannerSlide.company_id == company_id, UiBannerSlide.is_active == True)
            .order_by(UiBannerSlide.sort_order, UiBannerSlide.id)
        ).all()
    except Exception:
        _ui_cache_set(company_id, "banner", [])
        return []

    out = [{"title": s.title, "image_url": s.image_url, "link_path": s.link_path} for s in slides]
    _ui_cache_set(company_id, "banner", out)
    return out



@app.post("/simulador/proposta")
@require_login
async def simulador_criar_proposta(
    request: Request,
    session: Session = Depends(get_session),
    # client selection
    client_id: str = Form(""),
    # simulation params (same as simulador/pdf)
    loan_type: str = Form("Empréstimo"),
    amortization: str = Form("price"),
    rate: str = Form("1,79"),
    rate_base: str = Form("am"),
    term_months: int = Form(24),
    principal: str = Form(""),
    collateral_value: str = Form(""),
    ltv_pct: str = Form(""),
    grace_months: int = Form(0),
    io_months: int = Form(0),
    fee_amount: str = Form("0"),
    monthly_insurance: str = Form("0"),
    monthly_admin_fee: str = Form("0"),
    borrower_name: str = Form(""),
    notes: str = Form(""),
) -> Response:
    ctx = get_tenant_context(request, session)
    assert ctx is not None

    # valida client_id
    cid = (client_id or "").strip()
    if not cid:
        set_flash(request, "Selecione um cliente para gerar proposta.")
        return RedirectResponse("/simulador", status_code=303)

    try:
        cid_int = int(cid)
    except Exception:
        set_flash(request, "Cliente inválido.")
        return RedirectResponse("/simulador", status_code=303)

    client = session.get(Client, cid_int)
    if not client or client.company_id != ctx.company.id:
        set_flash(request, "Cliente não encontrado.")
        return RedirectResponse("/simulador", status_code=303)

    # Portal: cliente só pode gerar proposta para si mesmo
    if ctx.membership.role == "cliente" and (ctx.membership.client_id or 0) != client.id:
        raise HTTPException(status_code=403, detail="Sem permissão para este cliente.")

    # Constrói inputs + simula (para preencher descrição/valor)
    inp = LoanSimInputs.from_form(
        loan_type=loan_type,
        amortization=amortization,
        rate=rate,
        rate_base=rate_base,
        term_months=term_months,
        principal=principal,
        collateral_value=collateral_value,
        ltv_pct=ltv_pct,
        grace_months=grace_months,
        io_months=io_months,
        fee_amount=fee_amount,
        monthly_insurance=monthly_insurance,
        monthly_admin_fee=monthly_admin_fee,
        borrower_name=borrower_name,
        notes=notes,
    )
    sim = simulate_loan(inp)

    # Cria proposta (SEM depender do CRM)
    title = f"Proposta - {client.name} - {inp.loan_type}"
    desc = (
        f"Simulação de crédito ({inp.amortization.value.upper()}):\n"
        f"Valor: {float(inp.principal):.2f} | Prazo: {inp.term_months} meses | "
        f"Taxa base: {inp.rate_base.value} | Taxa: {float(inp.rate)*100:.2f}%\n"
        f"LTV: {float(inp.ltv_pct):.2f}% | Carência: {inp.grace_months}m | IO-only: {inp.io_months}m\n"
    )
    if inp.notes:
        desc += "\nObservações:\n" + inp.notes.strip()

    prop = Proposal(
        company_id=ctx.company.id,
        client_id=client.id,
        created_by_user_id=ctx.user.id,
        kind="proposta",
        title=title,
        description=desc,
        service_name=inp.loan_type,
        value_brl=max(0.0, float(inp.principal)),
        status="rascunho",
        created_at=utcnow(),
        updated_at=utcnow(),
    )
    session.add(prop)
    session.commit()
    session.refresh(prop)

    # Regra: tudo que nasce em Propostas (via simulador) cria também um card no CRM.
    deal = BusinessDeal(
        company_id=ctx.company.id,
        client_id=client.id,
        created_by_user_id=ctx.user.id,
        owner_user_id=ctx.user.id,
        title=f"Simulação/Proposta: {inp.loan_type}",
        demand="Crédito",
        notes=desc,
        stage="qualificacao",
        service_name=inp.loan_type,
        value_estimate_brl=max(0.0, float(inp.principal)),
        probability_pct=30,
        source="simulador",
        proposal_id=prop.id,
        created_at=utcnow(),
        updated_at=utcnow(),
    )
    session.add(deal)
    session.commit()
    session.refresh(deal)
    session.add(BusinessDealNote(deal_id=deal.id, author_user_id=ctx.user.id, message=f"Proposta criada (#{prop.id}) via Simulador."))
    session.commit()

    set_flash(request, "Proposta criada e card gerado no CRM.")
    return RedirectResponse(f"/propostas/{prop.id}", status_code=303)

@app.get("/api/ui/banner", response_class=JSONResponse)
@require_login
async def api_ui_banner(request: Request, session: Session = Depends(get_session)) -> JSONResponse:
    ctx = get_tenant_context(request, session)
    return JSONResponse(_ui_load_banner(ctx.company.id, session))


@app.get("/api/ui/news", response_class=JSONResponse)
@require_login
async def api_ui_news(request: Request, limit: int = 10, session: Session = Depends(get_session)) -> JSONResponse:
    ctx = get_tenant_context(request, session)
    items = await _ui_load_news(ctx.company.id, session, limit=limit)
    return JSONResponse(items)


@app.get("/admin/ui", response_class=HTMLResponse)
@require_role({"admin"})
async def admin_ui_page(request: Request, session: Session = Depends(get_session)) -> HTMLResponse:
    ctx = get_tenant_context(request, session)
    company_id = ctx.company.id
    active_client_id = get_active_client_id(request, session, ctx)
    current_client = get_client_or_none(session, company_id, active_client_id)

    ensure_ui_tables()
    try:
        slides = session.exec(
            select(UiBannerSlide)
            .where(UiBannerSlide.company_id == company_id)
            .order_by(UiBannerSlide.sort_order, UiBannerSlide.id)
        ).all()
        feeds = session.exec(
            select(UiNewsFeed)
            .where(UiNewsFeed.company_id == company_id)
            .order_by(UiNewsFeed.sort_order, UiNewsFeed.id)
        ).all()
    except Exception:
        request.session["flash"] = {"kind": "danger", "msg": "Não foi possível carregar/salvar UI (tabelas ausentes ou banco sem permissão)."}
        slides = []
        feeds = []
    return render("admin_ui.html", request=request, context={
        "title": "Configurações de UI",
        "slides": slides,
        "feeds": feeds,
        "current_user": ctx.user,
        "current_company": ctx.company,
        "role": ctx.membership.role,
        "current_client": current_client,
    })


@app.post("/admin/ui/banner/add")
@require_role({"admin"})
async def admin_ui_banner_add(
    request: Request,
    title: str = Form(""),
    link_path: str = Form("/"),
    image_url: str = Form(""),
    sort_order: int = Form(0),
    is_active: Optional[str] = Form(None),
    image_file: Optional[UploadFile] = File(None),
    session: Session = Depends(get_session),
):
    ctx = get_tenant_context(request, session)
    company_id = ctx.company.id

    img = (image_url or "").strip()
    if (not img) and image_file and image_file.filename:
        content = await image_file.read()
        if len(content) > 3 * 1024 * 1024:
            raise HTTPException(status_code=400, detail="Imagem muito grande (max 3MB).")
        ext = (Path(image_file.filename).suffix or ".png").lower()
        fname = f"{uuid.uuid4().hex}{ext}"
        fpath = BANNERS_DIR / fname
        fpath.write_bytes(content)
        img = f"/static/banners/{fname}"

    if not img:
        raise HTTPException(status_code=400, detail="Informe a URL da imagem ou envie um arquivo.")

    slide = UiBannerSlide(
        company_id=company_id,
        title=(title or "").strip(),
        image_url=img,
        link_path=(link_path or "/").strip() or "/",
        sort_order=_ui_safe_int(sort_order, 0),
        is_active=bool(is_active),
    )
    session.add(slide)
    session.commit()
    _ui_cache_bust(company_id)
    request.session["flash"] = "Slide adicionado."
    return RedirectResponse("/admin/ui", status_code=303)


@app.post("/admin/ui/banner/{slide_id}/toggle")
@require_role({"admin"})
async def admin_ui_banner_toggle(slide_id: int, request: Request, session: Session = Depends(get_session)):
    ctx = get_tenant_context(request, session)
    company_id = ctx.company.id
    s = session.get(UiBannerSlide, slide_id)
    if not s or s.company_id != company_id:
        raise HTTPException(status_code=404, detail="Slide não encontrado.")
    s.is_active = not s.is_active
    session.add(s)
    session.commit()
    _ui_cache_bust(company_id)
    return RedirectResponse("/admin/ui", status_code=303)


@app.post("/admin/ui/banner/{slide_id}/delete")
@require_role({"admin"})
async def admin_ui_banner_delete(slide_id: int, request: Request, session: Session = Depends(get_session)):
    ctx = get_tenant_context(request, session)
    company_id = ctx.company.id
    s = session.get(UiBannerSlide, slide_id)
    if not s or s.company_id != company_id:
        raise HTTPException(status_code=404, detail="Slide não encontrado.")
    session.delete(s)
    session.commit()
    _ui_cache_bust(company_id)
    return RedirectResponse("/admin/ui", status_code=303)


@app.post("/admin/ui/feed/add")
@require_role({"admin"})
async def admin_ui_feed_add(
    request: Request,
    name: str = Form(...),
    url: str = Form(...),
    sort_order: int = Form(0),
    is_active: Optional[str] = Form(None),
    session: Session = Depends(get_session),
):
    ctx = get_tenant_context(request, session)
    company_id = ctx.company.id
    feed = UiNewsFeed(
        company_id=company_id,
        name=(name or "").strip(),
        url=(url or "").strip(),
        sort_order=_ui_safe_int(sort_order, 0),
        is_active=bool(is_active),
    )
    session.add(feed)
    session.commit()
    _ui_cache_bust(company_id)
    request.session["flash"] = "Feed adicionado."
    return RedirectResponse("/admin/ui", status_code=303)


@app.post("/admin/ui/feed/{feed_id}/toggle")
@require_role({"admin"})
async def admin_ui_feed_toggle(feed_id: int, request: Request, session: Session = Depends(get_session)):
    ctx = get_tenant_context(request, session)
    company_id = ctx.company.id
    f = session.get(UiNewsFeed, feed_id)
    if not f or f.company_id != company_id:
        raise HTTPException(status_code=404, detail="Feed não encontrado.")
    f.is_active = not f.is_active
    session.add(f)
    session.commit()
    _ui_cache_bust(company_id)
    return RedirectResponse("/admin/ui", status_code=303)


@app.post("/admin/ui/feed/{feed_id}/delete")
@require_role({"admin"})
async def admin_ui_feed_delete(feed_id: int, request: Request, session: Session = Depends(get_session)):
    ctx = get_tenant_context(request, session)
    company_id = ctx.company.id
    f = session.get(UiNewsFeed, feed_id)
    if not f or f.company_id != company_id:
        raise HTTPException(status_code=404, detail="Feed não encontrado.")
    session.delete(f)
    session.commit()
    _ui_cache_bust(company_id)
    return RedirectResponse("/admin/ui", status_code=303)


TEMPLATES.update({
    "admin_registry.html": r"""
{% extends "base.html" %}
{% block content %}
<div class="container" style="max-width: 1200px;">
  <div class="d-flex align-items-center justify-content-between mt-3">
    <h3>Admin - Gestão</h3>
    <div class="d-flex gap-2">
      <a class="btn btn-sm btn-outline-secondary" href="/admin/members">Membros</a>
      <a class="btn btn-sm btn-outline-secondary" href="/admin/ui">UI (Banner/Notícias)</a>
    </div>
  </div>

  <p class="text-muted" style="font-size: .95rem;">
    Aqui você pode <b>inativar</b> ou <b>excluir</b> (soft delete) empresas, clientes e membros.
  </p>

  <ul class="nav nav-tabs mt-3" role="tablist">
    <li class="nav-item" role="presentation">
      <button class="nav-link active" data-bs-toggle="tab" data-bs-target="#tab-companies" type="button" role="tab">Empresas</button>
    </li>
    <li class="nav-item" role="presentation">
      <button class="nav-link" data-bs-toggle="tab" data-bs-target="#tab-clients" type="button" role="tab">Clientes</button>
    </li>
    <li class="nav-item" role="presentation">
      <button class="nav-link" data-bs-toggle="tab" data-bs-target="#tab-members" type="button" role="tab">Membros</button>
    </li>
  </ul>

  <div class="tab-content border border-top-0 p-3 bg-white">
    <div class="tab-pane fade show active" id="tab-companies" role="tabpanel">
      {% if not is_superadmin %}
        <div class="alert alert-info">Mostrando apenas sua empresa (superadmin pode ver todas).</div>
      {% endif %}
      <div class="table-responsive">
        <table class="table table-sm align-middle">
          <thead><tr><th>ID</th><th>Nome</th><th>Criada</th><th>Status</th><th style="width: 260px;">Ações</th></tr></thead>
          <tbody>
          {% for c in companies %}
            <tr>
              <td>{{ c.id }}</td>
              <td>{{ c.name }}</td>
              <td>{{ c.created_at.strftime("%d/%m/%Y") if c.created_at else "" }}</td>
              <td>
                {% set st = company_states.get(c.id) %}
                {% if st and st.is_deleted %}<span class="badge bg-danger">Excluída</span>
                {% elif st and not st.is_active %}<span class="badge bg-warning text-dark">Inativa</span>
                {% else %}<span class="badge bg-success">Ativa</span>{% endif %}
              </td>
              <td class="d-flex gap-2">
                <form method="post" action="/admin/entity/company/{{ c.id }}/toggle">
                  <button class="btn btn-sm btn-outline-primary" type="submit">Ativar/Inativar</button>
                </form>
                <form method="post" action="/admin/entity/company/{{ c.id }}/delete" onsubmit="return confirm('Excluir empresa (soft)?');">
                  <button class="btn btn-sm btn-outline-danger" type="submit">Excluir</button>
                </form>
                {% if is_superadmin %}
                <form method="post" action="/admin/entity/company/{{ c.id }}/hard_delete" onsubmit="return confirm('Excluir DEFINITIVO? Pode falhar se houver dependências.');">
                  <button class="btn btn-sm btn-danger" type="submit">Excluir definitivo</button>
                </form>
                {% endif %}
              </td>
            </tr>
          {% endfor %}
          </tbody>
        </table>
      </div>
    </div>

    <div class="tab-pane fade" id="tab-clients" role="tabpanel">
      <div class="table-responsive">
        <table class="table table-sm align-middle">
          <thead><tr><th>ID</th><th>Empresa</th><th>Nome</th><th>CNPJ</th><th>Email</th><th>Status</th><th style="width: 240px;">Ações</th></tr></thead>
          <tbody>
          {% for cl in clients %}
            <tr>
              <td>{{ cl.id }}</td>
              <td>{{ company_by_id.get(cl.company_id, '-') }}</td>
              <td>{{ cl.name }}</td>
              <td>{{ cl.cnpj }}</td>
              <td>{{ cl.email }}</td>
              <td>
                {% set st = client_states.get(cl.id) %}
                {% if st and st.is_deleted %}<span class="badge bg-danger">Excluído</span>
                {% elif st and not st.is_active %}<span class="badge bg-warning text-dark">Inativo</span>
                {% else %}<span class="badge bg-success">Ativo</span>{% endif %}
              </td>
              <td class="d-flex gap-2">
                <form method="post" action="/admin/entity/client/{{ cl.id }}/toggle">
                  <button class="btn btn-sm btn-outline-primary" type="submit">Ativar/Inativar</button>
                </form>
                <form method="post" action="/admin/entity/client/{{ cl.id }}/delete" onsubmit="return confirm('Excluir cliente (soft)?');">
                  <button class="btn btn-sm btn-outline-danger" type="submit">Excluir</button>
                </form>
                {% if is_superadmin %}
                <form method="post" action="/admin/entity/client/{{ cl.id }}/hard_delete" onsubmit="return confirm('Excluir DEFINITIVO? Pode falhar se houver dependências.');">
                  <button class="btn btn-sm btn-danger" type="submit">Excluir definitivo</button>
                </form>
                {% endif %}
              </td>
            </tr>
          {% endfor %}
          </tbody>
        </table>
      </div>
    </div>

    <div class="tab-pane fade" id="tab-members" role="tabpanel">
      <div class="table-responsive">
        <table class="table table-sm align-middle">
          <thead><tr><th>ID</th><th>Empresa</th><th>Usuário</th><th>Email</th><th>Role</th><th>Cliente</th><th>Status</th><th style="width: 220px;">Ações</th></tr></thead>
          <tbody>
          {% for m in members %}
            <tr>
              <td>{{ m.id }}</td>
              <td>{{ company_by_id.get(m.company_id, '-') }}</td>
              <td>{{ user_by_id.get(m.user_id, {}).get("name", "-") }}</td>
              <td>{{ user_by_id.get(m.user_id, {}).get("email", "-") }}</td>
              <td>{{ m.role }}</td>
              <td>{{ client_by_id.get(m.client_id, "-") }}</td>
              <td>
                {% set st = membership_states.get(m.id) %}
                {% if st and st.is_deleted %}<span class="badge bg-danger">Excluído</span>
                {% elif st and not st.is_active %}<span class="badge bg-warning text-dark">Inativo</span>
                {% else %}<span class="badge bg-success">Ativo</span>{% endif %}
              </td>
              <td class="d-flex gap-2">
                <form method="post" action="/admin/entity/membership/{{ m.id }}/toggle">
                  <button class="btn btn-sm btn-outline-primary" type="submit">Ativar/Inativar</button>
                </form>
                <form method="post" action="/admin/entity/membership/{{ m.id }}/delete" onsubmit="return confirm('Excluir membro (soft)?');">
                  <button class="btn btn-sm btn-outline-danger" type="submit">Excluir</button>
                </form>
              </td>
            </tr>
          {% endfor %}
          </tbody>
        </table>
      </div>
      <div class="alert alert-secondary mt-2" style="font-size:.9rem;">
        Inativar/excluir membro bloqueia acesso (require_role não permite entrar).
      </div>
    </div>
  </div>
</div>
{% endblock %}
""",
})

@app.get("/admin/gestao", response_class=HTMLResponse)
@require_role({"admin"})
async def admin_gestao(request: Request, session: Session = Depends(get_session)) -> HTMLResponse:
    ctx = get_tenant_context(request, session)
    if not ctx:
        request.session.clear()
        return RedirectResponse("/login", status_code=303)

    superadmin = is_superadmin(ctx.user)

    if superadmin:
        companies = session.exec(select(Company).order_by(Company.created_at)).all()
        clients = session.exec(select(Client).order_by(Client.created_at)).all()
        members = session.exec(select(Membership).order_by(Membership.created_at)).all()
    else:
        companies = [ctx.company]
        clients = session.exec(select(Client).where(Client.company_id == ctx.company.id).order_by(Client.created_at)).all()
        members = session.exec(select(Membership).where(Membership.company_id == ctx.company.id).order_by(Membership.created_at)).all()

    company_ids = [c.id for c in companies if c.id]
    client_ids = [c.id for c in clients if c.id]
    member_ids = [m.id for m in members if m.id]
    user_ids = sorted({m.user_id for m in members if m.user_id})

    def fetch_states(entity_type: str, ids: list[int]) -> dict[int, AdminEntityState]:
        if not ids:
            return {}
        rows = session.exec(
            select(AdminEntityState).where(
                AdminEntityState.entity_type == entity_type,
                AdminEntityState.entity_id.in_(ids),
            )
        ).all()
        return {r.entity_id: r for r in rows}

    company_states = fetch_states("company", company_ids)
    client_states = fetch_states("client", client_ids)
    membership_states = fetch_states("membership", member_ids)
    user_states = fetch_states("user", user_ids)

    users = session.exec(select(User).where(User.id.in_(user_ids))).all() if user_ids else []
    user_by_id = {u.id: {"name": u.name, "email": u.email, "state": user_states.get(u.id)} for u in users if u.id}

    client_by_id = {c.id: c.name for c in clients if c.id}
    company_by_id = {c.id: c.name for c in companies if c.id}

    return render(
        "admin_registry.html",
        request=request,
        context={
            "current_user": ctx.user,
            "current_company": ctx.company,
            "role": ctx.membership.role,
            "current_client": None,
            "companies": companies,
            "clients": clients,
            "members": members,
            "company_states": company_states,
            "client_states": client_states,
            "membership_states": membership_states,
            "user_by_id": user_by_id,
            "client_by_id": client_by_id,
            "company_by_id": company_by_id,
            "is_superadmin": superadmin,
        },
    )


def _admin_check_scope(ctx: TenantContext, session: Session, entity_type: str, entity_id: int) -> Optional[str]:
    if is_superadmin(ctx.user):
        return None
    if entity_type == "company":
        return "Apenas superadmin pode alterar empresa."
    if entity_type == "client":
        obj = session.get(Client, entity_id)
        if not obj or obj.company_id != ctx.company.id:
            return "Cliente fora do escopo."
        return None
    if entity_type == "membership":
        obj = session.get(Membership, entity_id)
        if not obj or obj.company_id != ctx.company.id:
            return "Membro fora do escopo."
        return None
    if entity_type == "user":
        return "Apenas superadmin pode alterar usuários."
    return "Tipo inválido."


def _derive_company_id_for_state(session: Session, entity_type: str, entity_id: int, fallback_company_id: int) -> Optional[int]:
    if entity_type == "company":
        return int(entity_id)
    if entity_type == "client":
        cl = session.get(Client, entity_id)
        return cl.company_id if cl else fallback_company_id
    if entity_type == "membership":
        m = session.get(Membership, entity_id)
        return m.company_id if m else fallback_company_id
    return None


@app.post("/admin/entity/{entity_type}/{entity_id}/toggle")
@require_role({"admin"})
async def admin_entity_toggle(request: Request, entity_type: str, entity_id: int, session: Session = Depends(get_session)):
    ctx = get_tenant_context(request, session)
    if not ctx:
        request.session.clear()
        return RedirectResponse("/login", status_code=303)

    et = (entity_type or "").strip().lower()
    if et not in {"company", "client", "membership", "user"}:
        request.session["flash"] = {"kind": "danger", "message": "Tipo inválido."}
        return RedirectResponse("/admin/gestao", status_code=303)

    err = _admin_check_scope(ctx, session, et, int(entity_id))
    if err:
        request.session["flash"] = {"kind": "danger", "message": err}
        return RedirectResponse("/admin/gestao", status_code=303)

    current = _get_state(session, entity_type=et, entity_id=int(entity_id))
    new_active = True if (not current) else (not bool(current.is_active))
    set_entity_state(
        session,
        entity_type=et,
        entity_id=int(entity_id),
        company_id=_derive_company_id_for_state(session, et, int(entity_id), ctx.company.id),
        is_active=new_active,
        is_deleted=False,
        updated_by_user_id=ctx.user.id,
    )
    request.session["flash"] = {"kind": "success", "message": f"{et} atualizado."}
    return RedirectResponse("/admin/gestao", status_code=303)


@app.post("/admin/entity/{entity_type}/{entity_id}/delete")
@require_role({"admin"})
async def admin_entity_delete(request: Request, entity_type: str, entity_id: int, session: Session = Depends(get_session)):
    ctx = get_tenant_context(request, session)
    if not ctx:
        request.session.clear()
        return RedirectResponse("/login", status_code=303)

    et = (entity_type or "").strip().lower()
    if et not in {"company", "client", "membership", "user"}:
        request.session["flash"] = {"kind": "danger", "message": "Tipo inválido."}
        return RedirectResponse("/admin/gestao", status_code=303)

    err = _admin_check_scope(ctx, session, et, int(entity_id))
    if err:
        request.session["flash"] = {"kind": "danger", "message": err}
        return RedirectResponse("/admin/gestao", status_code=303)

    set_entity_state(
        session,
        entity_type=et,
        entity_id=int(entity_id),
        company_id=_derive_company_id_for_state(session, et, int(entity_id), ctx.company.id),
        is_deleted=True,
        updated_by_user_id=ctx.user.id,
    )
    request.session["flash"] = {"kind": "success", "message": f"{et} excluído (soft)."}
    return RedirectResponse("/admin/gestao", status_code=303)


@app.post("/admin/entity/{entity_type}/{entity_id}/hard_delete")
@require_role({"admin"})
async def admin_entity_hard_delete(request: Request, entity_type: str, entity_id: int, session: Session = Depends(get_session)):
    ctx = get_tenant_context(request, session)
    if not ctx or not is_superadmin(ctx.user):
        request.session["flash"] = {"kind": "danger", "message": "Apenas superadmin."}
        return RedirectResponse("/admin/gestao", status_code=303)

    et = (entity_type or "").strip().lower()
    try:
        if et == "client":
            obj = session.get(Client, entity_id)
            if obj:
                session.delete(obj)
                session.commit()
        elif et == "company":
            obj = session.get(Company, entity_id)
            if obj:
                session.delete(obj)
                session.commit()
        else:
            request.session["flash"] = {"kind": "warning", "message": "Hard delete disponível apenas para company/client."}
            return RedirectResponse("/admin/gestao", status_code=303)
    except Exception as e:
        request.session["flash"] = {"kind": "danger", "message": f"Falha hard delete: {e}"}
        return RedirectResponse("/admin/gestao", status_code=303)

    request.session["flash"] = {"kind": "success", "message": f"{et} excluído definitivamente."}
    return RedirectResponse("/admin/gestao", status_code=303)

# === CREDIT_WALLET_MODULE_V1 ===
# Créditos (1 crédito = R$1,00) + Consultas (catálogo) + Stripe Checkout (opcional)
import math

try:
    import stripe  # type: ignore
except Exception:
    stripe = None


class CreditWallet(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    company_id: int = Field(index=True, foreign_key="company.id")
    client_id: int = Field(index=True, foreign_key="client.id", unique=True)
    balance_cents: int = Field(default=0, index=True)
    updated_at: datetime = Field(default_factory=utcnow)


class CreditLedger(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    company_id: int = Field(index=True, foreign_key="company.id")
    client_id: int = Field(index=True, foreign_key="client.id")

    kind: str = Field(index=True)  # TOPUP_CONFIRMED / CONSULT_CAPTURED / ADJUSTMENT
    amount_cents: int  # + / -
    ref_type: str = Field(default="", index=True)  # stripe_session / query_run
    ref_id: str = Field(default="", index=True)
    note: str = ""
    created_at: datetime = Field(default_factory=utcnow)


class QueryProduct(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    company_id: int = Field(index=True, foreign_key="company.id")
    code: str = Field(index=True)  # directdata.scr_analitico
    label: str
    category: str = Field(default="credito", index=True)
    provider: str = Field(default="directdata", index=True)
    provider_cost_cents: int = 0
    markup_pct: int = 50  # mínimo 50
    enabled: bool = Field(default=True, index=True)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class QueryRun(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    company_id: int = Field(index=True, foreign_key="company.id")
    client_id: int = Field(index=True, foreign_key="client.id")
    created_by_user_id: int = Field(index=True, foreign_key="user.id")

    product_code: str = Field(index=True)
    subject_doc: str = Field(default="", index=True)
    status: str = Field(default="PENDING", index=True)  # PENDING/READY/FAILED

    price_cents: int = 0
    provider_cost_cents: int = 0

    provider_uid: str = Field(default="", index=True)
    result_json: str = ""
    error: str = ""

    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


def ensure_credit_wallet_tables() -> None:
    try:
        SQLModel.metadata.create_all(
            engine,
            tables=[
                CreditWallet.__table__,
                CreditLedger.__table__,
                QueryProduct.__table__,
                QueryRun.__table__,
            ],
            checkfirst=True,
        )
    except Exception:
        return


@app.on_event("startup")
def _startup_credit_wallet_tables() -> None:
    ensure_credit_wallet_tables()


def _stripe_enabled() -> bool:
    return bool(os.getenv("STRIPE_SECRET_KEY")) and bool(os.getenv("STRIPE_WEBHOOK_SECRET")) and stripe is not None


def _price_cents(cost_cents: int, markup_pct: int) -> int:
    markup = max(50, int(markup_pct or 50))
    return int(math.ceil(cost_cents * (1.0 + markup / 100.0)))


def _get_or_create_wallet(session: Session, *, company_id: int, client_id: int) -> CreditWallet:
    w = session.exec(
        select(CreditWallet).where(CreditWallet.company_id == company_id, CreditWallet.client_id == client_id)
    ).first()
    if w:
        return w
    w = CreditWallet(company_id=company_id, client_id=client_id, balance_cents=0, updated_at=utcnow())
    session.add(w)
    session.commit()
    session.refresh(w)
    return w


def _wallet_add_ledger(
    session: Session,
    *,
    company_id: int,
    client_id: int,
    kind: str,
    amount_cents: int,
    ref_type: str = "",
    ref_id: str = "",
    note: str = "",
) -> None:
    session.add(
        CreditLedger(
            company_id=company_id,
            client_id=client_id,
            kind=kind,
            amount_cents=int(amount_cents),
            ref_type=ref_type,
            ref_id=ref_id,
            note=note,
            created_at=utcnow(),
        )
    )
    session.commit()


def _wallet_credit(session: Session, *, company_id: int, client_id: int, amount_cents: int, stripe_session_id: str) -> None:
    w = _get_or_create_wallet(session, company_id=company_id, client_id=client_id)
    w.balance_cents += int(amount_cents)
    w.updated_at = utcnow()
    session.add(w)
    session.commit()
    _wallet_add_ledger(
        session,
        company_id=company_id,
        client_id=client_id,
        kind="TOPUP_CONFIRMED",
        amount_cents=int(amount_cents),
        ref_type="stripe_session",
        ref_id=stripe_session_id,
        note=f"Recarga Stripe (+{amount_cents/100:.2f} créditos)",
    )


def _wallet_debit_or_402(session: Session, *, company_id: int, client_id: int, amount_cents: int, run_id: int, note: str) -> None:
    w = _get_or_create_wallet(session, company_id=company_id, client_id=client_id)
    if w.balance_cents < int(amount_cents):
        raise HTTPException(status_code=402, detail="Saldo insuficiente de créditos.")
    w.balance_cents -= int(amount_cents)
    w.updated_at = utcnow()
    session.add(w)
    session.commit()
    _wallet_add_ledger(
        session,
        company_id=company_id,
        client_id=client_id,
        kind="CONSULT_CAPTURED",
        amount_cents=-int(amount_cents),
        ref_type="query_run",
        ref_id=str(run_id),
        note=note,
    )

def _wallet_refund(session: Session, *, company_id: int, client_id: int, amount_cents: int, run_id: int, note: str) -> None:
    """Estorna créditos quando a consulta falha após débito."""
    w = _get_or_create_wallet(session, company_id=company_id, client_id=client_id)
    w.balance_cents += int(amount_cents)
    w.updated_at = utcnow()
    session.add(w)
    session.commit()
    _wallet_add_ledger(
        session,
        company_id=company_id,
        client_id=client_id,
        kind="CONSULT_RELEASED",
        amount_cents=int(amount_cents),
        ref_type="query_run",
        ref_id=str(run_id),
        note=note,
    )


def _seed_credit_products(session: Session, company_id: int) -> None:
    if session.exec(select(QueryProduct).where(QueryProduct.company_id == company_id)).first():
        return
    defaults = [
        ("directdata.scr_analitico", "SCR Analítico", 390),
        ("directdata.scr_detalhada", "SCR Detalhada", 490),
        ("directdata.score_quod", "Score (QUOD)", 198),
    ]
    for code, label, cost in defaults:
        session.add(
            QueryProduct(
                company_id=company_id,
                code=code,
                label=label,
                category="credito",
                provider="directdata",
                provider_cost_cents=int(cost),
                markup_pct=50,
                enabled=True,
                created_at=utcnow(),
                updated_at=utcnow(),
            )
        )
    session.commit()


def _disable_unwanted_products(session: Session, company_id: int) -> None:
    """
    Desativa produtos que não devem aparecer no cardápio público de Consultas.

    - Idempotente: pode ser chamado em toda visita ao /consultas.
    - Mantém o produto no Admin (/admin/consultas), mas evita aparecer/rodar no menu do cliente.
    """
    try:
        p = session.exec(
            select(QueryProduct).where(
                QueryProduct.company_id == company_id,
                QueryProduct.code == "directdata.cadastral_pf",
            )
        ).first()
        if p and p.enabled:
            p.enabled = False
            p.updated_at = utcnow()
            session.add(p)
            session.commit()
    except Exception:
        return



def _directdata_url_for(path: str, fallback: str = "") -> str:
    """
    Resolve URL de uma consulta Direct Data.
    Prioridade: env específica -> DIRECTDATA_BASE_URL + path -> fallback.
    """
    base = (os.getenv("DIRECTDATA_BASE_URL") or "").rstrip("/")
    if base and path.startswith("/"):
        return f"{base}{path}"
    if base:
        return f"{base}/{path.lstrip('/')}"
    return fallback


def _dd_is_processing(data: dict) -> bool:
    md = (data or {}).get("metaDados") or {}
    resultado = (md.get("resultado") or "").lower()
    return (data.get("retorno") is None) or ("process" in resultado)

async def _directdata_generic_request(*, url: str, params: dict[str, str], timeout_s: int = 30) -> tuple[int, dict[str, Any] | None, str]:
    """
    Request GET genérico para Direct Data.
    - Inclui TOKEN via query param.
    - Suporta async/poll quando retorno traz metaDados.consultaUid e/ou resultado 'Em Processamento'.
    """
    token = os.getenv("DIRECTDATA_TOKEN") or ""
    if not token:
        return 0, None, "DIRECTDATA_TOKEN não configurado."
    if not url:
        return 0, None, "URL Direct Data não configurada."

    q = {"TOKEN": token, **{k: v for k, v in (params or {}).items() if v is not None}}
    try:
        async with httpx.AsyncClient(timeout=timeout_s) as client:
            r = await client.get(url, params=q)
        if r.status_code != 200:
            return r.status_code, None, f"HTTP {r.status_code}"
        data = r.json()
        if not isinstance(data, dict):
            return r.status_code, None, "Resposta inválida (não é JSON objeto)."

        md = (data.get("metaDados") or {})
        uid = md.get("consultaUid")
        if uid and (_dd_is_processing(data) or (str(md.get("resultado") or "").lower().find("process") != -1)):
            ok, final_data, msg = await _directdata_wait_result(str(uid), timeout_s=60)
            if ok and final_data is not None:
                return 200, final_data, "OK"
            return 200, data, msg or "Em Processamento"
        return 200, data, "OK"
    except Exception as e:
        return 0, None, str(e)

async def _directdata_call_real(*, product_code: str, doc_digits: str) -> tuple[int, dict[str, Any] | None, str]:
    """Chama Direct Data para produtos do catálogo (SCR + Score)."""
    doc = _digits_only(doc_digits)
    if not doc:
        return 0, None, "Documento inválido."

    doc_type = "cpf" if len(doc) == 11 else "cnpj"

    # SCR Resumido
    if product_code in {"directdata.scr_resumido", "directdata.scr_analitico"}:
        url = os.getenv("DIRECTDATA_SCR_RESUMIDO_URL") or _directdata_url_for("/api/SCRBacen")
        if not url:
            return 0, None, "DIRECTDATA_SCR_RESUMIDO_URL/DIRECTDATA_BASE_URL não configurado."
        # Usa mesmo formato do SCR
        return await _directdata_scr_request(document_type=doc_type, document_value=doc, url_override=url)

    # SCR Detalhada
    if product_code == "directdata.scr_detalhada":
        url = os.getenv("DIRECTDATA_SCR_URL") or _directdata_url_for("/api/SCRBacenDetalhada")
        if not url:
            return 0, None, "DIRECTDATA_SCR_URL/DIRECTDATA_BASE_URL não configurado."
        return await _directdata_scr_request(document_type=doc_type, document_value=doc, url_override=url)

    # Score
    if product_code in {"directdata.score", "directdata.score_quod"}:
        url = os.getenv("DIRECTDATA_SCORE_URL") or _directdata_url_for("/api/Score")
        if not url:
            return 0, None, "DIRECTDATA_SCORE_URL/DIRECTDATA_BASE_URL não configurado."
        # Direct Data Score: normalmente aceita CPF/CNPJ no mesmo padrão (CPF/CNPJ)
        key = "CPF" if doc_type == "cpf" else "CNPJ"
        return await _directdata_generic_request(url=url, params={key: doc})

    return 0, None, f"Produto não mapeado para Direct Data: {product_code}"


async def _directdata_wait_result(consulta_uid: str, *, timeout_s: int = 60) -> tuple[bool, dict | None, str]:
    """
    Poll Direct Data async result endpoint until retorno != None or timeout.
    Uses env DIRECTDATA_ASYNC_RESULT_URL and DIRECTDATA_POLL_MIN_INTERVAL_S.
    """
    url = os.getenv("DIRECTDATA_ASYNC_RESULT_URL") or ""
    token = os.getenv("DIRECTDATA_TOKEN") or ""
    if not url or not token:
        return False, None, "Direct Data async result URL/token não configurado."

    interval = int(os.getenv("DIRECTDATA_POLL_MIN_INTERVAL_S") or 6)
    start = utcnow()
    deadline = start.timestamp() + float(timeout_s)

    last_msg = ""
    while utcnow().timestamp() < deadline:
        try:
            # Direct Data uses TOKEN query param; attempt both consultaUid and ConsultaUid
            params = {"TOKEN": token, "consultaUid": consulta_uid}
            async with httpx.AsyncClient(timeout=20) as client:
                r = await client.get(url, params=params)
                if r.status_code != 200:
                    last_msg = f"HTTP {r.status_code}"
                else:
                    data = r.json()
                    if isinstance(data, dict) and not _dd_is_processing(data):
                        return True, data, "OK"
                    last_msg = ((data or {}).get("metaDados") or {}).get("resultado") or "Em Processamento"
        except Exception as e:
            last_msg = str(e)

        await asyncio.sleep(max(2, interval))

    return False, None, f"Timeout aguardando processamento ({last_msg})"

def _pdf_draw_wrapped(c: canvas.Canvas, text: str, x: float, y: float, max_width: float, line_h: float, max_lines: int = 999) -> float:
    styles = getSampleStyleSheet()
    # simple wrapping without heavy platypus table
    words = (text or "").split()
    line = ""
    lines = []
    for w in words:
        test = (line + " " + w).strip()
        if c.stringWidth(test, "Helvetica", 9) <= max_width:
            line = test
        else:
            lines.append(line)
            line = w
    if line:
        lines.append(line)
    for ln in lines[:max_lines]:
        c.drawString(x, y, ln)
        y -= line_h
    return y

def _mask_doc(doc: str) -> str:
    """Mascara CPF/CNPJ para exibição em relatórios."""
    d = re.sub(r"\D+", "", doc or "")
    if len(d) == 11:
        return f"{d[:3]}.***.***-{d[-2:]}"
    if len(d) == 14:
        return f"{d[:2]}.***.***/****-{d[-2:]}"
    return d

def _as_str(v: object) -> str:
    if v is None:
        return "-"
    s = str(v).strip()
    return s if s else "-"


def _money(v: object) -> str:
    if v is None:
        return "-"
    s = str(v).strip()
    return s if s else "-"


def _num(v: object) -> str:
    if v is None:
        return "-"
    return str(v)


def _draw_logo_on_canvas(c: canvas.Canvas, logo_path: str) -> None:
    try:
        if logo_path and os.path.exists(logo_path):
            c.drawImage(ImageReader(logo_path), 18 * mm, (A4[1] - 18 * mm), width=38 * mm, height=12 * mm, mask="auto")
    except Exception:
        pass


def _build_scr_pdf(
    *,
    company_name: str,
    client_name: str,
    product_label: str,
    product_code: str,
    subject_doc: str,
    data: dict,
) -> bytes:
    """
    Relatório PDF tratado (sem "print de JSON").

    - Traz resumo executivo e tabelas (SCR Detalhada/Analítica).
    - Mantém disclaimer de consulta.
    - Não exibe JSON cru ao cliente.
    """
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=16 * mm,
        bottomMargin=16 * mm,
        title="Relatório de Consulta",
        author=company_name,
    )

    styles = getSampleStyleSheet()
    h1 = ParagraphStyle("h1", parent=styles["Heading1"], fontName="Helvetica-Bold", fontSize=14, spaceAfter=6)
    h2 = ParagraphStyle("h2", parent=styles["Heading2"], fontName="Helvetica-Bold", fontSize=11, spaceBefore=10, spaceAfter=6)
    p = ParagraphStyle("p", parent=styles["BodyText"], fontName="Helvetica", fontSize=9, leading=12)
    small = ParagraphStyle("small", parent=styles["BodyText"], fontName="Helvetica-Oblique", fontSize=8, leading=10)

    story: list = []

    logo_path = os.path.join(STATIC_DIR, "logo.png") if "STATIC_DIR" in globals() else "static/logo.png"

    story.append(Paragraph("Relatório de Consulta (Direct Data)", h1))
    story.append(Spacer(1, 4))

    story.append(Paragraph(f"<b>Empresa:</b> {company_name}", p))
    story.append(Paragraph(f"<b>Cliente:</b> {client_name}", p))
    story.append(Paragraph(f"<b>Consulta:</b> {product_label} <font size=8 color='#666'>({product_code})</font>", p))
    story.append(Paragraph(f"<b>Documento:</b> {_mask_doc(subject_doc)}", p))
    story.append(Spacer(1, 6))

    disclaimer = (
        "Este relatório é gerado automaticamente a partir de bases de terceiros (Direct Data) "
        "e constitui apenas uma consulta/levantamento de informações. "
        "Não é uma proposta de crédito, não representa aprovação e está sujeito à análise interna, "
        "políticas e validações adicionais."
    )
    story.append(Paragraph(disclaimer, small))
    story.append(Spacer(1, 10))

    md = (data or {}).get("metaDados") or {}
    retorno = (data or {}).get("retorno") or {}

    story.append(Paragraph("Resumo da execução", h2))
    exec_rows = [
        ["Consulta", _as_str(md.get("consultaNome"))],
        ["UID", _as_str(md.get("consultaUid"))],
        ["Resultado", _as_str(md.get("resultado"))],
        ["Data", _as_str(md.get("data"))],
        ["Tempo (ms)", _num(md.get("tempoExecucaoMs"))],
    ]
    t = Table(exec_rows, colWidths=[35 * mm, 140 * mm])
    t.setStyle(
        TableStyle(
            [
                ("FONT", (0, 0), (-1, -1), "Helvetica", 9),
                ("FONT", (0, 0), (0, -1), "Helvetica-Bold", 9),
                ("ROWBACKGROUNDS", (0, 0), (-1, -1), [colors.whitesmoke, colors.white]),
                ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.lightgrey),
                ("BOX", (0, 0), (-1, -1), 0.25, colors.lightgrey),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    story.append(t)

    if not retorno:
        story.append(Spacer(1, 10))
        story.append(Paragraph("A consulta ainda não retornou dados.", p))
        doc.build(story, onFirstPage=lambda c, d: _draw_logo_on_canvas(c, logo_path))
        return buf.getvalue()

    story.append(Paragraph("Resumo executivo (SCR)", h2))
    score = _as_str(retorno.get("score"))
    faixa = _as_str(retorno.get("faixaRisco"))
    risco_total = _money(retorno.get("riscoTotal"))
    qtd_inst = _num(retorno.get("quantidadeInstituicoes"))
    qtd_ops = _num(retorno.get("quantidadeOperacoes"))
    rel_ini = _as_str(retorno.get("dataInicioRelacionamento"))

    exec2_rows = [
        ["Score", score],
        ["Faixa de risco", faixa],
        ["Risco total", risco_total],
        ["Instituições / Operações", f"{qtd_inst} / {qtd_ops}"],
        ["Início relacionamento", rel_ini],
    ]
    t2 = Table(exec2_rows, colWidths=[55 * mm, 120 * mm])
    t2.setStyle(
        TableStyle(
            [
                ("FONT", (0, 0), (-1, -1), "Helvetica", 9),
                ("FONT", (0, 0), (0, -1), "Helvetica-Bold", 9),
                ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.lightgrey),
                ("BOX", (0, 0), (-1, -1), 0.25, colors.lightgrey),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    story.append(t2)

    carteira = retorno.get("carteiraCredito") or {}
    story.append(Paragraph("Carteira de crédito", h2))
    cart_rows = [
        ["Total", _money(carteira.get("total"))],
        ["A vencer", _money(carteira.get("vencer"))],
        ["Vencido", _money(carteira.get("vencido"))],
        ["Limite", _money(carteira.get("limite"))],
        ["Prejuízo", _money(carteira.get("prejuizo"))],
    ]
    t3 = Table(cart_rows, colWidths=[55 * mm, 120 * mm])
    t3.setStyle(
        TableStyle(
            [
                ("FONT", (0, 0), (-1, -1), "Helvetica", 9),
                ("FONT", (0, 0), (0, -1), "Helvetica-Bold", 9),
                ("ROWBACKGROUNDS", (0, 0), (-1, -1), [colors.white, colors.whitesmoke]),
                ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.lightgrey),
                ("BOX", (0, 0), (-1, -1), 0.25, colors.lightgrey),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    story.append(t3)

    modalidades = retorno.get("modalidades") or []
    story.append(Paragraph("Modalidades (resumo)", h2))
    mod_rows = [["Código", "Modalidade", "A vencer", "Vencido", "Cambial"]]
    for m in modalidades:
        av = (m.get("aVencer") or {}).get("total")
        vc = (m.get("vencido") or {}).get("total")
        mod_rows.append(
            [
                _as_str(m.get("codigoModalidade")),
                _as_str(m.get("descricaoModalidade")),
                _money(av),
                _money(vc),
                _as_str(m.get("variacaoCambial")),
            ]
        )
    t4 = Table(mod_rows, colWidths=[20 * mm, 85 * mm, 30 * mm, 30 * mm, 20 * mm])
    t4.setStyle(
        TableStyle(
            [
                ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 9),
                ("FONT", (0, 1), (-1, -1), "Helvetica", 8.5),
                ("BACKGROUND", (0, 0), (-1, 0), colors.whitesmoke),
                ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.lightgrey),
                ("BOX", (0, 0), (-1, -1), 0.25, colors.lightgrey),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 5),
                ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]
        )
    )
    story.append(t4)

    story.append(Paragraph("Notas e interpretação", h2))
    for line in [
        "• O score e a faixa de risco são indicadores auxiliares; a decisão final depende de análise interna.",
        "• Valores “a vencer” e “vencido” ajudam a identificar comportamento de pagamento e concentração de risco.",
        "• Recomenda-se validar com documentos e informações fornecidas pelo cliente e políticas internas.",
    ]:
        story.append(Paragraph(line, p))

    doc.build(story, onFirstPage=lambda c, d: _draw_logo_on_canvas(c, logo_path))
    return buf.getvalue()

# === /CONSULTAS_PDF_REPORT_V1 ===

def _extract_score_fields(data: Any) -> dict[str, str]:
    """Extrai campos do Score (QUOD) do retorno da Direct Data.

    A resposta mais comum segue a documentação oficial:
    retorno.pessoaFisica|pessoaJuridica.{score, faixaScore, capacidadePagamento, perfil, ...}
    """
    root: dict[str, Any] = data if isinstance(data, dict) else {}

    def _get_ci(obj: Any, key: str) -> Any:
        if not isinstance(obj, dict):
            return None
        if key in obj:
            return obj.get(key)
        lk = key.lower()
        for k, v in obj.items():
            if isinstance(k, str) and k.lower() == lk:
                return v
        return None

    def _as_text(v: Any) -> str:
        if v is None:
            return "-"
        if isinstance(v, (int, float)):
            return str(v)
        s = str(v).strip()
        return s if s else "-"

    def _pick(obj: Any, *keys: str) -> str:
        if not isinstance(obj, dict):
            return "-"
        for k in keys:
            v = _get_ci(obj, k)
            if v is None:
                continue
            if isinstance(v, dict):
                vv = _get_ci(v, "valor") or _get_ci(v, "value")
                if vv is not None:
                    return _as_text(vv)
            if isinstance(v, list):
                if v:
                    return _as_text(v[0])
                continue
            txt = _as_text(v)
            if txt != "-":
                return txt
        return "-"

    md = _get_ci(root, "metaDados")
    md = md if isinstance(md, dict) else {}
    retorno = _get_ci(root, "retorno")
    if isinstance(retorno, list) and retorno:
        retorno = retorno[0] if isinstance(retorno[0], dict) else {}
    retorno = retorno if isinstance(retorno, dict) else {}

    pf = _get_ci(retorno, "pessoaFisica")
    pj = _get_ci(retorno, "pessoaJuridica")
    pf = pf if isinstance(pf, dict) else {}
    pj = pj if isinstance(pj, dict) else {}

    # Escolhe o bloco mais informativo (PF/PJ)
    entity: dict[str, Any] = pf if _pick(pf, "score", "pontuacao", "nota") != "-" else pj
    if entity is None:
        entity = {}

    score = _pick(entity, "score", "pontuacao", "pontuacaoScore", "scoreValor", "valorScore", "nota")
    faixa = _pick(entity, "faixaScore", "faixaRisco", "faixa", "rating", "classificacao", "faixaScore")
    capacidade = _pick(entity, "capacidadePagamento", "capacidadeDePagamento")
    perfil = _pick(entity, "perfil")
    observacao = _pick(retorno, "observacao")

    motivos = _get_ci(entity, "motivos")
    if isinstance(motivos, list):
        motivos_txt = "\n".join([f"• {str(x).strip()}" for x in motivos if str(x).strip()]) or "-"
    else:
        motivos_txt = _as_text(motivos)

    # Indicadores de negócio (quando PJ)
    indicadores = _get_ci(entity, "indicadoresNegocio") or _get_ci(entity, "indicadores")
    indicadores_txt = "-"
    if isinstance(indicadores, list) and indicadores:
        lines: list[str] = []
        for it in indicadores[:10]:
            if not isinstance(it, dict):
                continue
            ind = _pick(it, "indicador", "titulo", "nome")
            risco = _pick(it, "risco")
            status = _pick(it, "status")
            obs = _pick(it, "observacao")
            parts = [x for x in [ind, f"risco={risco}" if risco != "-" else "-", f"status={status}" if status != "-" else "-", obs] if x and x != "-"]
            if parts:
                lines.append(" - ".join(parts))
        indicadores_txt = "\n".join([f"• {l}" for l in lines]) if lines else "-"

    # Campos que podem existir em variações/versões de APIs
    pd = _pick(root, "probabilidadeInadimplencia", "probDefault", "inadimplencia", "pd", "prob_inadimplencia")
    modelo = _pick(root, "modelo", "versaoModelo", "modeloScore", "nomeModelo")
    fonte = _pick(root, "fonte", "bureau", "origem", "provider")

    return {
        "score": score,
        "faixa": faixa,
        "prob_default": pd,
        "modelo": modelo,
        "fonte": fonte,
        "uid": _pick(md, "consultaUid"),
        "consulta_nome": _pick(md, "consultaNome"),
        "resultado": _pick(md, "resultado"),
        "data_exec": _pick(md, "data"),
        "tempo_ms": _pick(md, "tempoExecucaoMs"),
        "capacidade_pagamento": capacidade,
        "perfil": perfil,
        "observacao": observacao,
        "motivos": motivos_txt,
        "indicadores": indicadores_txt,
    }



def _build_score_pdf(
    *,
    company_name: str,
    client_name: str,
    product_label: str,
    product_code: str,
    subject_doc: str,
    data: dict,
) -> bytes:
    """PDF específico para Score (não usa layout SCR)."""
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=16 * mm,
        bottomMargin=16 * mm,
        title="Relatório de Score",
        author=company_name,
    )

    styles = getSampleStyleSheet()
    h1 = ParagraphStyle("h1", parent=styles["Heading1"], fontName="Helvetica-Bold", fontSize=14, spaceAfter=6)
    h2 = ParagraphStyle("h2", parent=styles["Heading2"], fontName="Helvetica-Bold", fontSize=11, spaceBefore=10, spaceAfter=6)
    p = ParagraphStyle("p", parent=styles["BodyText"], fontName="Helvetica", fontSize=9, leading=12)
    small = ParagraphStyle("small", parent=styles["BodyText"], fontName="Helvetica-Oblique", fontSize=8, leading=10)

    story: list = []
    logo_path = os.path.join(STATIC_DIR, "logo.png") if "STATIC_DIR" in globals() else "static/logo.png"

    fields = _extract_score_fields(data)

    story.append(Paragraph("Relatório de Consulta (Direct Data)", h1))
    story.append(Paragraph(f"Empresa: {html.escape(company_name)}", p))
    story.append(Paragraph(f"Cliente: {html.escape(client_name)}", p))
    story.append(Paragraph(f"Consulta: {html.escape(product_label)} ({html.escape(product_code)})", p))
    story.append(Paragraph(f"Documento: {_mask_doc(subject_doc)}", p))
    story.append(Spacer(1, 8))

    story.append(
        Paragraph(
            "Este relatório é gerado automaticamente a partir de bases de terceiros (Direct Data) e constitui apenas "
            "uma consulta/levantamento de informações. Não é uma proposta de crédito, não representa aprovação e está "
            "sujeito à análise interna, políticas e validações adicionais.",
            small,
        )
    )

    story.append(Spacer(1, 10))
    story.append(Paragraph("Resumo da execução", h2))

    exec_rows = [
        ["Consulta", fields["consulta_nome"] if fields["consulta_nome"] != "-" else product_label],
        ["UID", fields["uid"]],
        ["Resultado", fields["resultado"]],
        ["Data", fields["data_exec"]],
        ["Tempo (ms)", fields["tempo_ms"]],
    ]
    t_exec = Table(exec_rows, colWidths=[35 * mm, 140 * mm])
    t_exec.setStyle(
        TableStyle(
            [
                ("FONT", (0, 0), (-1, -1), "Helvetica", 9),
                ("FONT", (0, 0), (0, -1), "Helvetica-Bold", 9),
                ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.lightgrey),
                ("BOX", (0, 0), (-1, -1), 0.25, colors.lightgrey),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    story.append(t_exec)

    story.append(Spacer(1, 10))
    story.append(Paragraph("Resumo executivo (Score)", h2))

    score_rows = [
        ["Score", fields["score"]],
        ["Faixa de risco", fields["faixa"]],
        ["Prob. inadimplência (PD)", fields["prob_default"]],
        ["Modelo", fields["modelo"]],
        ["Fonte", fields["fonte"]],
    ]
    t_score = Table(score_rows, colWidths=[55 * mm, 120 * mm])
    t_score.setStyle(
        TableStyle(
            [
                ("FONT", (0, 0), (-1, -1), "Helvetica", 9),
                ("FONT", (0, 0), (0, -1), "Helvetica-Bold", 9),
                ("BACKGROUND", (0, 0), (-1, 0), colors.whitesmoke),
                ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.lightgrey),
                ("BOX", (0, 0), (-1, -1), 0.25, colors.lightgrey),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    story.append(t_score)

    # Detalhes (quando retornados pela Direct Data)
    details_rows: list[list[str]] = []
    if fields.get("capacidade_pagamento", "-") != "-":
        details_rows.append(["Capacidade de pagamento", fields["capacidade_pagamento"]])
    if fields.get("perfil", "-") != "-":
        details_rows.append(["Perfil", fields["perfil"]])
    if fields.get("observacao", "-") != "-":
        details_rows.append(["Observação", fields["observacao"]])

    if details_rows:
        story.append(Spacer(1, 10))
        story.append(Paragraph("Detalhes retornados", h2))
        t_det = Table(details_rows, colWidths=[55 * mm, 120 * mm])
        t_det.setStyle(
            TableStyle(
                [
                    ("FONT", (0, 0), (-1, -1), "Helvetica", 9),
                    ("FONT", (0, 0), (0, -1), "Helvetica-Bold", 9),
                    ("BACKGROUND", (0, 0), (-1, 0), colors.whitesmoke),
                    ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.lightgrey),
                    ("BOX", (0, 0), (-1, -1), 0.25, colors.lightgrey),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 6),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                    ("TOPPADDING", (0, 0), (-1, -1), 4),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ]
            )
        )
        story.append(t_det)

    if fields.get("motivos", "-") != "-" and fields.get("motivos"):
        story.append(Spacer(1, 10))
        story.append(Paragraph("Motivos", h2))
        story.append(Paragraph(html.escape(fields["motivos"]).replace("\n", "<br/>"), p))

    if fields.get("indicadores", "-") != "-" and fields.get("indicadores"):
        story.append(Spacer(1, 10))
        story.append(Paragraph("Indicadores de negócio", h2))
        story.append(Paragraph(html.escape(fields["indicadores"]).replace("\n", "<br/>"), p))

    story.append(Spacer(1, 10))
    story.append(Paragraph("Notas e interpretação", h2))
    for line in [
        "• O score e a faixa de risco são indicadores auxiliares; a decisão final depende de análise interna.",
        "• Recomenda-se validar com documentos e informações fornecidas pelo cliente e políticas internas.",
    ]:
        story.append(Paragraph(line, p))

    doc.build(story, onFirstPage=lambda c, d: _draw_logo_on_canvas(c, logo_path))
    return buf.getvalue()


def build_consulta_pdf(
    *,
    company_name: str,
    client_name: str,
    product_label: str,
    product_code: str,
    subject_doc: str,
    data: dict,
) -> bytes:
    """Wrapper: escolhe layout correto (Score vs SCR)."""
    if "score" in (product_code or ""):
        return _build_score_pdf(
            company_name=company_name,
            client_name=client_name,
            product_label=product_label,
            product_code=product_code,
            subject_doc=subject_doc,
            data=data,
        )
    return _build_scr_pdf(
        company_name=company_name,
        client_name=client_name,
        product_label=product_label,
        product_code=product_code,
        subject_doc=subject_doc,
        data=data,
    )





    return 0, None, f"Produto não mapeado para Direct Data: {product_code}"


TEMPLATES.setdefault("creditos.html", r"""
{% extends "base.html" %}
{% block content %}
<div class="container" style="max-width: 1100px;">
  <div class="d-flex align-items-center justify-content-between mt-3">
    <h3>Créditos</h3>
    <a class="btn btn-outline-secondary btn-sm" href="/consultas">Ir para Consultas</a>
  </div>

  {% if request.query_params.get("success") %}
    <div class="alert alert-success mt-2">Pagamento confirmado. Créditos adicionados.</div>
  {% endif %}
  {% if request.query_params.get("canceled") %}
    <div class="alert alert-warning mt-2">Pagamento cancelado.</div>
  {% endif %}

  <div class="card p-3 mt-3">
    <div class="row g-2">
      <div class="col-md-4">
        <div class="text-muted">Saldo</div>
        <div style="font-size: 1.8rem;"><strong>{{ wallet_balance }}</strong> créditos</div>
      </div>
      <div class="col-md-8">
        <div class="text-muted">Recarregar (Stripe)</div>
        <form method="post" action="/creditos/checkout" class="d-flex gap-2 flex-wrap">
          <select class="form-select" name="pack" style="max-width: 220px;">
            <option value="50">50 créditos (R$ 50)</option>
            <option value="100">100 créditos (R$ 100)</option>
            <option value="250">250 créditos (R$ 250)</option>
            <option value="500">500 créditos (R$ 500)</option>
          </select>
          <button class="btn btn-primary" type="submit" {% if not stripe_enabled %}disabled{% endif %}>
            Comprar créditos
          </button>
          {% if not stripe_enabled %}
            <span class="text-muted" style="font-size: .9rem;">Stripe não configurado.</span>
          {% endif %}
        </form>
      </div>
    </div>
  </div>

  <div class="card p-3 mt-3">
    <h5 class="mb-2">Extrato</h5>
    <div class="table-responsive">
      <table class="table table-sm">
        <thead>
          <tr>
            <th>Data</th>
            <th>Tipo</th>
            <th class="text-end">Valor</th>
            <th>Ref</th>
            <th>Obs</th>
          </tr>
        </thead>
        <tbody>
          {% for e in ledger %}
          <tr>
            <td>{{ e.created_at.strftime("%d/%m/%Y %H:%M") }}</td>
            <td>{{ e.kind }}</td>
            <td class="text-end">{{ "%.2f"|format(e.amount_cents/100) }}</td>
            <td>{{ e.ref_type }} {{ e.ref_id }}</td>
            <td>{{ e.note }}</td>
          </tr>
          {% endfor %}
          {% if not ledger %}
          <tr><td colspan="5" class="text-muted">Sem movimentações.</td></tr>
          {% endif %}
        </tbody>
      </table>
    </div>
  </div>
</div>
{% endblock %}
""")

TEMPLATES.setdefault("consultas.html", r"""
{% extends "base.html" %}
{% block content %}
<div class="container" style="max-width: 1100px;">
  <div class="d-flex align-items-center justify-content-between mt-3">
    <h3>Consultas</h3>
    <div class="d-flex gap-2">
      <a class="btn btn-outline-secondary btn-sm" href="/creditos">Créditos</a>
      {% if role in ["admin","equipe"] %}
        <a class="btn btn-outline-primary btn-sm" href="/admin/consultas">Admin Consultas</a>
      {% endif %}
    </div>
  </div>

  <div class="alert alert-info mt-2">
    Saldo atual: <strong>{{ wallet_balance }}</strong> créditos.
  </div>

  <div class="row g-3 mt-1">
    {% for p in products %}
      <div class="col-md-6">
        <div class="card p-3 h-100">
          <div class="d-flex justify-content-between align-items-start">
            <div>
              <div style="font-size:1.1rem;"><strong>{{ p.label }}</strong></div>
              <div class="text-muted" style="font-size:.9rem;">Código: {{ p.code }}</div>
            </div>
            <div class="text-end">
              <div class="text-muted" style="font-size:.85rem;">Preço</div>
              <div style="font-size:1.2rem;"><strong>{{ "%.2f"|format(p.price_cents/100) }}</strong> créditos</div>
            </div>
          </div>
          <div class="mt-3">
            <a class="btn btn-primary" href="/consultas/{{ p.code }}">Fazer consulta</a>
          </div>
        </div>
      </div>
    {% endfor %}
  </div>
</div>
{% endblock %}
""")

TEMPLATES.setdefault("consulta_run.html", r"""
{% extends "base.html" %}
{% block content %}
<div class="container" style="max-width: 900px;">
  <div class="d-flex align-items-center justify-content-between mt-3">
    <h3>{{ product.label }}</h3>
    <a class="btn btn-outline-secondary btn-sm" href="/consultas">Voltar</a>
  </div>

  <div class="card p-3 mt-3">
    <div class="text-muted">Saldo: <strong>{{ wallet_balance }}</strong> créditos</div>
    <div class="text-muted">Preço desta consulta: <strong>{{ "%.2f"|format(product.price_cents/100) }}</strong> créditos</div>

    <form method="post" action="/consultas/{{ product.code }}/run" class="mt-3">
      <div class="row g-2">
        <div class="col-md-6">
          <label class="form-label">CPF/CNPJ</label>
          <input class="form-control" name="doc" placeholder="Digite CPF/CNPJ" value="{{ doc_value|default('') }}" required>
          {% if product_is_scr %}
            <div class="form-text">
              Para SCR, é obrigatório o aceite do titular do CPF/CNPJ antes da consulta.
            </div>
          {% endif %}
        </div>

        {% if product_is_scr %}
          <div class="col-md-6">
            <label class="form-label">Aceite SCR (e-mail)</label>

            {% if doc_value %}
              {% if scr_consent_status == "valida" %}
                <div class="alert alert-success py-2 mb-0">
                  <div class="d-flex align-items-center justify-content-between">
                    <div>
                      <strong>Aceite válido</strong>
                      {% if scr_consent_expires_at %}
                        <span class="muted small">até {{ scr_consent_expires_at.strftime("%d/%m/%Y") }}</span>
                      {% endif %}
                    </div>
                    <span class="badge bg-success">OK</span>
                  </div>
                </div>
              {% elif scr_consent_status == "pendente" %}
                <div class="alert alert-warning py-2 mb-0">
                  <div class="d-flex align-items-center justify-content-between">
                    <div><strong>Aguardando aceite</strong></div>
                    <span class="badge bg-warning text-dark">Pendente</span>
                  </div>
                  <div class="muted small mt-1">Envie o link ao titular e aguarde confirmar.</div>
                </div>
              {% else %}
                <div class="alert alert-warning py-2 mb-0">
                  <div class="d-flex align-items-center justify-content-between">
                    <div><strong>Aceite não registrado</strong></div>
                    <span class="badge bg-secondary">Necessário</span>
                  </div>
                  <div class="muted small mt-1">Gere e envie o link de aceite por e-mail.</div>
                </div>
              {% endif %}
            {% else %}
              <div class="alert alert-light py-2 mb-0">
                <div class="muted small">Digite um CPF/CNPJ acima para solicitar o aceite.</div>
              </div>
            {% endif %}
          </div>

          {% if doc_value and scr_consent_status != "valida" %}
            <div class="col-12">
              <div class="card p-3 bg-light border">
                <div class="fw-semibold">Enviar e-mail de aceite</div>
                <div class="row g-2 mt-1">
                  <input type="hidden" name="code" value="{{ product.code }}">
                                    <div class="col-md-6">
                    <input class="form-control" name="email" placeholder="E-mail do titular">
                    <div class="form-text">Este e-mail receberá o link público de aceite.</div>
                  </div>
                  <div class="col-md-6 d-flex align-items-start gap-2">
                    <button class="btn btn-outline-primary" type="submit" formaction="/consultas/consent_link" formmethod="post">Enviar link</button>
                    {% if consulta_consent_link_url %}
                      <button class="btn btn-outline-secondary" type="button"
                              onclick="navigator.clipboard.writeText('{{ consulta_consent_link_url }}');">
                        Copiar link
                      </button>
                    {% endif %}
                  </div>

                  {% if consulta_consent_link_url %}
                    <div class="col-12">
                      <label class="form-label small muted mb-1">Link (manual)</label>
                      <input class="form-control form-control-sm mono" readonly value="{{ consulta_consent_link_url }}">
                    </div>
                  {% endif %}
                </div>
              </div>
            </div>
          {% endif %}
        {% endif %}

        <div class="col-12">
          {% set disable_run = (product_is_scr and doc_value and scr_consent_status != "valida") %}
          <button class="btn btn-primary" type="submit" {% if disable_run %}disabled{% endif %}>Executar</button>
          <a class="btn btn-outline-secondary" href="/creditos">Recarregar</a>
          <a class="btn btn-outline-secondary" href="/consultas/historico">Histórico</a>
          {% if disable_run %}
            <div class="muted small mt-2">A consulta SCR será liberada automaticamente após o aceite.</div>
          {% endif %}
        </div>
      </div>
    </form>
  </div>

  {% if run %}
  <div class="card p-3 mt-3">
    <div class="d-flex justify-content-between align-items-start flex-wrap gap-2">
      <div>
        <div class="text-muted">Status</div>
        <div><strong>{{ run.status }}</strong></div>

        {% if run.status == "PENDING" %}
          <div class="text-muted" style="font-size:.9rem;">Consulta em processamento. Você pode atualizar o resultado.</div>
          <div class="mt-2">
            <a class="btn btn-sm btn-outline-primary" href="/consultas/run/{{ run.id }}">Atualizar resultado</a>
          </div>
        {% endif %}

        {% if run.status == "READY" %}
          <div class="mt-2 d-flex gap-2 flex-wrap">
            <a class="btn btn-sm btn-primary" href="/consultas/run/{{ run.id }}/pdf" target="_blank" rel="noopener">Baixar PDF</a>
          </div>
        {% endif %}
      </div>

      <div class="text-end">
        <div class="text-muted">Documento</div>
        <div><strong>{{ run.subject_doc|default("") }}</strong></div>
      </div>
    </div>

    <hr>

    {% if run.status == "READY" %}
      <div class="alert alert-success mb-0">Consulta finalizada. Use o botão <strong>Baixar PDF</strong> para gerar o relatório.</div>
    {% elif run.status == "PENDING" %}
      <div class="alert alert-warning mb-0">Em processamento (Direct Data). Aguarde alguns segundos e clique em <strong>Atualizar resultado</strong>.</div>
    {% else %}
      <div class="alert alert-danger mb-0">{{ run.error }}</div>
    {% endif %}
  </div>
  {% endif %}
</div>
{% endblock %}
""")


TEMPLATES.setdefault("consultas_historico.html", r"""
{% extends "base.html" %}
{% block content %}
<div class="container" style="max-width: 1100px;">
  <div class="d-flex align-items-center justify-content-between mt-3">
    <h3>Histórico de Consultas</h3>
    <a class="btn btn-outline-secondary btn-sm" href="/consultas">Voltar</a>
  </div>

  <div class="card p-3 mt-3">
    <div class="table-responsive">
      <table class="table table-sm align-middle">
        <thead>
          <tr>
            <th>ID</th>
            <th>Data</th>
            <th>Consulta</th>
            <th>Doc</th>
            <th>Status</th>
            <th class="text-end">Preço</th>
            <th class="text-end"></th>
          </tr>
        </thead>
        <tbody>
          {% for r in runs %}
          <tr>
            <td>{{ r.id }}</td>
            <td>{{ r.created_at.strftime("%d/%m/%Y %H:%M") }}</td>
            <td>{{ r.label }}</td>
            <td>{{ r.doc_masked }}</td>
            <td><strong>{{ r.status }}</strong></td>
            <td class="text-end">{{ "%.2f"|format(r.price_cents/100) }}</td>
            <td class="text-end">
              <a class="btn btn-sm btn-outline-primary" href="/consultas/run/{{ r.id }}">Abrir</a>
              {% if r.status == "READY" %}
                <a class="btn btn-sm btn-primary" href="/consultas/run/{{ r.id }}/pdf" target="_blank" rel="noopener">PDF</a>
              {% endif %}
            </td>
          </tr>
          {% endfor %}
          {% if not runs %}
            <tr><td colspan="7" class="text-muted">Sem consultas.</td></tr>
          {% endif %}
        </tbody>
      </table>
    </div>
  </div>
</div>
{% endblock %}
""")

@app.get("/creditos", response_class=HTMLResponse)
@require_login
async def creditos_page(request: Request, session: Session = Depends(get_session)) -> HTMLResponse:
    ctx = get_tenant_context(request, session)
    if not ctx:
        request.session.clear()
        return RedirectResponse("/login", status_code=303)

    active_client_id = get_active_client_id(request, session, ctx)
    if not active_client_id and getattr(ctx.membership, "client_id", None):
        active_client_id = int(ctx.membership.client_id)

    if not active_client_id:
        set_flash(request, "Selecione um cliente (no topo) para ver créditos.")
        return RedirectResponse("/", status_code=303)

    client = get_client_or_none(session, ctx.company.id, int(active_client_id))
    if not client:
        set_flash(request, "Cliente inválido.")
        return RedirectResponse("/", status_code=303)

    w = _get_or_create_wallet(session, company_id=ctx.company.id, client_id=client.id)
    ledger = session.exec(
        select(CreditLedger)
        .where(CreditLedger.company_id == ctx.company.id, CreditLedger.client_id == client.id)
        .order_by(CreditLedger.id.desc())
        .limit(50)
    ).all()

    return render("creditos.html", request=request, context={
        "title": "Créditos",
        "wallet_balance": f"{w.balance_cents/100:.2f}",
        "ledger": ledger,
        "stripe_enabled": _stripe_enabled(),
    })


@app.post("/creditos/checkout")
@require_login
async def creditos_checkout(request: Request, session: Session = Depends(get_session), pack: str = Form("50")) -> Response:
    ctx = get_tenant_context(request, session)
    if not ctx:
        request.session.clear()
        return RedirectResponse("/login", status_code=303)

    if not _stripe_enabled():
        set_flash(request, "Stripe não configurado.")
        return RedirectResponse("/creditos", status_code=303)

    active_client_id = get_active_client_id(request, session, ctx)
    if not active_client_id and getattr(ctx.membership, "client_id", None):
        active_client_id = int(ctx.membership.client_id)
    if not active_client_id:
        set_flash(request, "Selecione um cliente para recarregar.")
        return RedirectResponse("/creditos", status_code=303)

    client = get_client_or_none(session, ctx.company.id, int(active_client_id))
    if not client:
        set_flash(request, "Cliente inválido.")
        return RedirectResponse("/creditos", status_code=303)

    packs = {"50": 5000, "100": 10000, "250": 25000, "500": 50000}
    amount_cents = packs.get(str(pack), 5000)
    credits = int(amount_cents / 100)

    stripe.api_key = os.environ["STRIPE_SECRET_KEY"]
    success_url = os.getenv("STRIPE_SUCCESS_URL", str(request.base_url).rstrip("/") + "/creditos?success=1")
    cancel_url = os.getenv("STRIPE_CANCEL_URL", str(request.base_url).rstrip("/") + "/creditos?canceled=1")

    checkout = stripe.checkout.Session.create(
        mode="payment",
        success_url=success_url,
        cancel_url=cancel_url,
        line_items=[{
            "price_data": {
                "currency": "brl",
                "product_data": {"name": f"{credits} créditos"},
                "unit_amount": int(amount_cents),
            },
            "quantity": 1,
        }],
        metadata={
            "company_id": str(ctx.company.id),
            "client_id": str(client.id),
            "credits": str(credits),
        },
    )
    return RedirectResponse(checkout.url, status_code=303)


@app.post("/stripe/webhook")
async def stripe_webhook(request: Request, session: Session = Depends(get_session)) -> Response:
    if stripe is None or not os.getenv("STRIPE_WEBHOOK_SECRET"):
        return Response(status_code=400)

    payload = await request.body()
    sig = request.headers.get("stripe-signature", "")
    stripe.api_key = os.getenv("STRIPE_SECRET_KEY", "")

    try:
        event = stripe.Webhook.construct_event(payload, sig, os.environ["STRIPE_WEBHOOK_SECRET"])
    except Exception:
        return Response(status_code=400)

    if event.get("type") == "checkout.session.completed":
        obj = (event.get("data") or {}).get("object") or {}
        meta = obj.get("metadata") or {}
        company_id = int(meta.get("company_id") or 0)
        client_id = int(meta.get("client_id") or 0)
        credits = int(meta.get("credits") or 0)
        session_id = str(obj.get("id") or "")
        if company_id and client_id and credits and session_id:
            already = session.exec(select(CreditLedger).where(
                CreditLedger.ref_type == "stripe_session",
                CreditLedger.ref_id == session_id,
                CreditLedger.kind == "TOPUP_CONFIRMED",
            )).first()
            if not already:
                _wallet_credit(session, company_id=company_id, client_id=client_id, amount_cents=credits * 100, stripe_session_id=session_id)

    return Response(status_code=200)




# ----------------------------
# Consultas: Aceite SCR por CPF/CNPJ (link + e-mail)
# ----------------------------

def _build_consulta_consent_url(request: Request, *, token: str) -> str:
    return f"{_public_base_url(request)}/consultas/consent/aceite/{token}"


@app.post("/consultas/consent_link")
@require_login
async def consultas_generate_consent_link(
        request: Request,
        session: Session = Depends(get_session),
        code: str = Form(...),
        doc: str = Form(""),
        email: str = Form(""),
) -> Response:
    ctx = get_tenant_context(request, session)
    assert ctx is not None

    active_client_id = get_active_client_id(request, session, ctx)
    if not active_client_id and getattr(ctx.membership, "client_id", None):
        active_client_id = int(ctx.membership.client_id)
    if not active_client_id:
        set_flash(request, "Selecione um cliente.")
        return RedirectResponse("/consultas", status_code=303)

    norm_doc = _digits_only(doc or "")
    if not norm_doc:
        set_flash(request, "Informe um CPF/CNPJ válido para solicitar o aceite.")
        return RedirectResponse(f"/consultas/{code}", status_code=303)

    if not _is_scr_consulta_product(code):
        set_flash(request, "Este produto não exige aceite SCR.")
        return RedirectResponse(f"/consultas/{code}?doc={norm_doc}", status_code=303)

    if not ensure_consulta_scr_consent_table():
        set_flash(request, "Sistema de aceite SCR não está configurado (migração pendente no banco).")
        return RedirectResponse(f"/consultas/{code}?doc={norm_doc}", status_code=303)

    # Reutiliza link pendente, se existir
    latest = _get_latest_consulta_scr_consent(session, company_id=ctx.company.id, subject_doc=norm_doc)
    link_url = ""
    if latest:
        _refresh_consulta_scr_consent_status(latest)
        if latest.status == "valida":
            set_flash(request, "Aceite já está válido para este CPF/CNPJ.")
            return RedirectResponse(f"/consultas/{code}?doc={norm_doc}", status_code=303)
        if latest.status == "pendente":
            meta = _unpack_consent_link_note(latest.notes)
            if meta and meta.get("token"):
                try:
                    _verify_consent_token(str(meta["token"]))
                    link_url = _build_consulta_consent_url(request, token=str(meta["token"]))
                except Exception:
                    link_url = ""

    now = utcnow()
    exp_dt = now + timedelta(hours=int(CREDIT_CONSENT_LINK_TTL_HOURS))

    if not link_url:
        nonce = secrets.token_urlsafe(12)
        payload = {
            "scope": "consultas_scr",
            "company_id": int(ctx.company.id),
            "requested_by_client_id": int(active_client_id),
            "created_by_user_id": int(ctx.user.id),
            "subject_doc": norm_doc,
            "iat": int(now.timestamp()),
            "exp": int(exp_dt.timestamp()),
            "nonce": nonce,
            "term_version": CREDIT_CONSENT_TERM_VERSION,
        }
        token = _sign_consent_token(payload)

        consent = ConsultaScrConsent(
            company_id=ctx.company.id,
            requested_by_client_id=int(active_client_id),
            created_by_user_id=ctx.user.id,
            subject_doc=norm_doc,
            invited_email=(email or "").strip().lower(),
            status="pendente",
            token_nonce=nonce,
            signed_by_name="",
            signed_at=None,
            expires_at=exp_dt,
            accepted_at=None,
            notes=_pack_consent_link_note(token=token, created_by_user_id=ctx.user.id, expires_at=exp_dt),
            created_at=now,
            updated_at=now,
        )
        session.add(consent)
        try:
            session.commit()
        except OperationalError:
            ensure_consulta_scr_consent_table()
            session.add(consent)
            session.commit()

        link_url = _build_consulta_consent_url(request, token=token)

    # tenta enviar e-mail (se configurado)
    to_email = (email or "").strip().lower()
    if to_email and "@" in to_email:
        try:
            subj = f"Aceite para consulta ao SCR (Bacen) - {ctx.company.name}"
            html_body = f"""
            <p>Olá,</p>
            <p>Para liberar a consulta ao <b>SCR (Bacen)</b> do CPF/CNPJ <b>{_mask_doc(norm_doc)}</b>,
            pedimos que você registre seu aceite no link abaixo:</p>
            <p><a href="{link_url}">{link_url}</a></p>
            <p>Se você não reconhece esta solicitação, ignore este e-mail.</p>
            """
            text_body = f"Para liberar a consulta ao SCR do documento {_mask_doc(norm_doc)}, acesse:\n{link_url}\n"
            _smtp_send_email(to_email=to_email, subject=subj, html_body=html_body, text_body=text_body)
            set_flash(request, f"E-mail de aceite enviado para {to_email}.")
        except Exception as e:
            set_flash(request, f"Não foi possível enviar e-mail (SMTP). Copie o link manualmente. Erro: {e}")
    else:
        set_flash(request, "E-mail inválido. Copie o link manualmente.")

    request.session["consulta_consent_link_url"] = link_url
    return RedirectResponse(f"/consultas/{code}?doc={norm_doc}", status_code=303)


@app.get("/consultas/consent/aceite/{token}", response_class=HTMLResponse)
async def consultas_consent_accept_page(
        request: Request,
        token: str,
        session: Session = Depends(get_session),
) -> HTMLResponse:
    try:
        payload = _verify_consent_token(token)
    except Exception as e:
        return render("error.html", request=request, context={"current_user": None, "current_company": None, "role": "public",
                                                            "message": f"Link inválido/expirado: {e}"}, status_code=400)

    if str(payload.get("scope") or "") != "consultas_scr":
        return render("error.html", request=request, context={"current_user": None, "current_company": None, "role": "public",
                                                            "message": "Link inválido para este fluxo."}, status_code=400)

    company_id = int(payload.get("company_id") or 0)
    subject_doc = _digits_only(str(payload.get("subject_doc") or ""))
    nonce = str(payload.get("nonce") or "")

    company = session.get(Company, company_id) if company_id else None
    if not company or not subject_doc:
        return render("error.html", request=request, context={"current_user": None, "current_company": None, "role": "public",
                                                            "message": "Link inválido: empresa/documento não encontrados."}, status_code=404)

    if not ensure_consulta_scr_consent_table():
        return render("error.html", request=request, context={"current_user": None, "current_company": company, "role": "public",
                                                            "message": "Sistema de aceite ainda não está configurado (tabela ausente)."}, status_code=500)

    consent = session.exec(
        select(ConsultaScrConsent)
        .where(
            ConsultaScrConsent.company_id == company_id,
            ConsultaScrConsent.subject_doc == subject_doc,
            ConsultaScrConsent.token_nonce == nonce,
        )
        .order_by(ConsultaScrConsent.created_at.desc())
    ).first()

    if not consent:
        return render("error.html", request=request, context={"current_user": None, "current_company": company, "role": "public",
                                                            "message": "Solicitação de aceite não encontrada."}, status_code=404)

    _refresh_consulta_scr_consent_status(consent)
    if consent.status == "valida":
        return render("success.html", request=request, context={"current_user": None, "current_company": company, "role": "public",
                                                               "message": "Autorização já registrada. Obrigado!"})

    terms_html = templates_env.from_string(CREDIT_CONSENT_TERMS_HTML).render(term_version=CREDIT_CONSENT_TERM_VERSION)

    return render(
        "consulta_consent_accept.html",
        request=request,
        context={
            "current_user": None,
            "current_company": company,
            "role": "public",
            "company": company,
            "doc_masked": _mask_doc(subject_doc),
            "terms_html": terms_html,
            "token": token,
            "error": "",
            "form": {"name": ""},
        },
    )


@app.post("/consultas/consent/aceite/{token}")
async def consultas_consent_accept_submit(
        request: Request,
        token: str,
        session: Session = Depends(get_session),
        agree: str = Form(""),
        signed_by_name: str = Form(""),
        doc_last4: str = Form(""),
) -> Response:
    def render_form(company: Company, subject_doc: str, msg: str) -> HTMLResponse:
        terms_html = templates_env.from_string(CREDIT_CONSENT_TERMS_HTML).render(term_version=CREDIT_CONSENT_TERM_VERSION)
        return render(
            "consulta_consent_accept.html",
            request=request,
            context={
                "current_user": None,
                "current_company": company,
                "role": "public",
                "company": company,
                "doc_masked": _mask_doc(subject_doc),
                "terms_html": terms_html,
                "token": token,
                "error": msg,
                "form": {"name": signed_by_name or ""},
            },
            status_code=400,
        )

    try:
        payload = _verify_consent_token(token)
    except Exception as e:
        return render("error.html", request=request, context={"current_user": None, "current_company": None, "role": "public",
                                                            "message": f"Link inválido/expirado: {e}"}, status_code=400)

    if str(payload.get("scope") or "") != "consultas_scr":
        return render("error.html", request=request, context={"current_user": None, "current_company": None, "role": "public",
                                                            "message": "Link inválido para este fluxo."}, status_code=400)

    company_id = int(payload.get("company_id") or 0)
    subject_doc = _digits_only(str(payload.get("subject_doc") or ""))
    nonce = str(payload.get("nonce") or "")

    company = session.get(Company, company_id) if company_id else None
    if not company or not subject_doc:
        return render("error.html", request=request, context={"current_user": None, "current_company": None, "role": "public",
                                                            "message": "Link inválido: empresa/documento não encontrados."}, status_code=404)

    if not str(agree).strip():
        return render_form(company, subject_doc, "É necessário marcar o aceite.")

    dl4 = _digits_only(doc_last4)[-4:]
    if dl4 and not subject_doc.endswith(dl4):
        return render_form(company, subject_doc, "Os 4 últimos dígitos não conferem.")

    if not ensure_consulta_scr_consent_table():
        return render("error.html", request=request, context={"current_user": None, "current_company": company, "role": "public",
                                                            "message": "Sistema de aceite não está configurado (tabela ausente)."}, status_code=500)

    consent = session.exec(
        select(ConsultaScrConsent)
        .where(
            ConsultaScrConsent.company_id == company_id,
            ConsultaScrConsent.subject_doc == subject_doc,
            ConsultaScrConsent.token_nonce == nonce,
        )
        .order_by(ConsultaScrConsent.created_at.desc())
    ).first()
    if not consent:
        return render("error.html", request=request, context={"current_user": None, "current_company": company, "role": "public",
                                                            "message": "Solicitação de aceite não encontrada."}, status_code=404)

    now = utcnow()
    expires_at = now + timedelta(days=int(CREDIT_CONSENT_MAX_DAYS))

    evidence = {
        "method": "clickwrap",
        "scope": "consultas_scr",
        "term_version": CREDIT_CONSENT_TERM_VERSION,
        "term_sha256": _terms_sha256(),
        "token_iat": int(payload.get("iat") or 0),
        "token_exp": int(payload.get("exp") or 0),
        "ip": _request_ip(request),
        "user_agent": request.headers.get("user-agent") or "",
        "accepted_at_utc": now.isoformat(),
        "subject_doc_masked": _mask_doc(subject_doc),
    }

    consent.status = "valida"
    consent.signed_by_name = (signed_by_name or "").strip() or "Titular"
    consent.signed_at = now
    consent.expires_at = expires_at
    consent.accepted_at = now
    consent.updated_at = now
    consent.notes = "[aceite-eletronico]\n" + json.dumps(evidence, ensure_ascii=False)
    session.add(consent)
    session.commit()

    return render(
        "success.html",
        request=request,
        context={
            "current_user": None,
            "current_company": company,
            "role": "public",
            "message": "Autorização registrada com sucesso. Você já pode fechar esta página.",
        },
    )
@app.get("/consultas", response_class=HTMLResponse)
@require_login
async def consultas_home(request: Request, session: Session = Depends(get_session)) -> HTMLResponse:
    ctx = get_tenant_context(request, session)
    if not ctx:
        request.session.clear()
        return RedirectResponse("/login", status_code=303)

    active_client_id = get_active_client_id(request, session, ctx)
    if not active_client_id and getattr(ctx.membership, "client_id", None):
        active_client_id = int(ctx.membership.client_id)

    if not active_client_id:
        set_flash(request, "Selecione um cliente para usar consultas.")
        return RedirectResponse("/", status_code=303)

    client = get_client_or_none(session, ctx.company.id, int(active_client_id))
    if not client:
        set_flash(request, "Cliente inválido.")
        return RedirectResponse("/", status_code=303)

    _seed_credit_products(session, ctx.company.id)

    _disable_unwanted_products(session, ctx.company.id)

    products = session.exec(select(QueryProduct).where(
        QueryProduct.company_id == ctx.company.id,
        QueryProduct.enabled == True,  # noqa
        QueryProduct.code != "directdata.cadastral_pf",
    ).order_by(QueryProduct.label)).all()

    enriched = [{
        "code": p.code,
        "label": p.label,
        "price_cents": _price_cents(p.provider_cost_cents, p.markup_pct),
    } for p in products]

    w = _get_or_create_wallet(session, company_id=ctx.company.id, client_id=client.id)
    return render("consultas.html", request=request, context={
        "title": "Consultas",
        "wallet_balance": f"{w.balance_cents/100:.2f}",
        "products": enriched,
    })


@app.get("/consultas/historico", response_class=HTMLResponse)
@app.get("/consultas/historico/", response_class=HTMLResponse)
@require_login
async def consultas_historico(request: Request, session: Session = Depends(get_session)) -> HTMLResponse:
    ctx = get_tenant_context(request, session)
    assert ctx is not None

    active_client_id = get_active_client_id(request, session, ctx)
    member_client_id = getattr(ctx.membership, "client_id", None)

    runs = []
    info_msg = ""

    try:
        if ctx.membership.role == "cliente":
            if not member_client_id:
                info_msg = "Seu usuário não está vinculado a um cliente."
                runs = []
            else:
                cid = int(member_client_id)
                runs = session.exec(
                    select(QueryRun)
                    .where(QueryRun.company_id == ctx.company.id, QueryRun.client_id == cid)
                    .order_by(QueryRun.id.desc())
                    .limit(500)
                ).all()
        else:
            if active_client_id:
                cid = int(active_client_id)
                runs = session.exec(
                    select(QueryRun)
                    .where(QueryRun.company_id == ctx.company.id, QueryRun.client_id == cid)
                    .order_by(QueryRun.id.desc())
                    .limit(500)
                ).all()
            else:
                runs = session.exec(
                    select(QueryRun)
                    .where(QueryRun.company_id == ctx.company.id)
                    .order_by(QueryRun.id.desc())
                    .limit(500)
                ).all()
                info_msg = "Exibindo consultas da empresa (nenhum cliente selecionado)."
    except Exception as e:
        info_msg = f"Erro ao carregar histórico: {e}"
        runs = []

    products = {p.code: p.label for p in session.exec(select(QueryProduct).where(QueryProduct.company_id == ctx.company.id)).all()}
    view = []
    for r in runs:
        view.append({
            "id": r.id,
            "created_at": r.created_at,
            "label": products.get(r.product_code, r.product_code),
            "doc_masked": _mask_doc(r.subject_doc),
            "status": r.status,
            "price_cents": r.price_cents,
        })

    return render("consultas_historico.html", request=request, context={"title": "Histórico de Consultas", "runs": view, "info_msg": info_msg})

@app.get("/consultas/{code}", response_class=HTMLResponse)
@require_login
async def consultas_product(request: Request, session: Session = Depends(get_session), code: str = "") -> HTMLResponse:
    ctx = get_tenant_context(request, session)
    if not ctx:
        request.session.clear()
        return RedirectResponse("/login", status_code=303)

    active_client_id = get_active_client_id(request, session, ctx)
    if not active_client_id and getattr(ctx.membership, "client_id", None):
        active_client_id = int(ctx.membership.client_id)
    if not active_client_id:
        return RedirectResponse("/", status_code=303)

    client = get_client_or_none(session, ctx.company.id, int(active_client_id))
    if not client:
        return RedirectResponse("/", status_code=303)

    p = session.exec(select(QueryProduct).where(
        QueryProduct.company_id == ctx.company.id,
        QueryProduct.code == code,
        QueryProduct.enabled == True,  # noqa
        QueryProduct.code != "directdata.cadastral_pf",
    )).first()
    if not p:
        raise HTTPException(status_code=404, detail="Consulta não encontrada.")

    doc_value = _digits_only(str(request.query_params.get("doc") or ""))
    product_is_scr = _is_scr_consulta_product(p.code)

    scr_consent_status = ""
    scr_consent_expires_at = None
    consent_link_url = ""

    if product_is_scr and doc_value and ensure_consulta_scr_consent_table():
        try:
            cst = _get_latest_consulta_scr_consent(session, company_id=ctx.company.id, subject_doc=doc_value)
            if cst:
                prev = cst.status
                _refresh_consulta_scr_consent_status(cst)
                if cst.status != prev:
                    cst.updated_at = utcnow()
                    session.add(cst)
                    session.commit()
                scr_consent_status = cst.status
                if cst.status == "valida":
                    scr_consent_expires_at = cst.expires_at
                elif cst.status == "pendente":
                    meta = _unpack_consent_link_note(cst.notes)
                    if meta and meta.get("token"):
                        try:
                            _verify_consent_token(str(meta["token"]))
                            consent_link_url = _build_consulta_consent_url(request, token=str(meta["token"]))
                        except Exception:
                            consent_link_url = ""
        except Exception:
            pass

    # fallback: mostra o último link gerado (se houver)
    if not consent_link_url:
        consent_link_url = str(request.session.get("consulta_consent_link_url") or "")

    w = _get_or_create_wallet(session, company_id=ctx.company.id, client_id=client.id)
    pv = {"code": p.code, "label": p.label, "price_cents": _price_cents(p.provider_cost_cents, p.markup_pct)}
    return render("consulta_run.html", request=request, context={
        "title": p.label,
        "product": pv,
        "wallet_balance": f"{w.balance_cents/100:.2f}",
        "run": None,
        "doc_value": doc_value,
        "product_is_scr": bool(product_is_scr),
        "scr_consent_status": scr_consent_status,
        "scr_consent_expires_at": scr_consent_expires_at,
        "consulta_consent_link_url": consent_link_url,
    })

@app.post("/consultas/{code}/run", response_class=HTMLResponse)
@require_login
async def consultas_run(request: Request, session: Session = Depends(get_session), code: str = "", doc: str = Form("")) -> HTMLResponse:
    ctx = get_tenant_context(request, session)
    if not ctx:
        request.session.clear()
        return RedirectResponse("/login", status_code=303)

    active_client_id = get_active_client_id(request, session, ctx)
    if not active_client_id and getattr(ctx.membership, "client_id", None):
        active_client_id = int(ctx.membership.client_id)
    if not active_client_id:
        return RedirectResponse("/", status_code=303)

    client = get_client_or_none(session, ctx.company.id, int(active_client_id))
    if not client:
        return RedirectResponse("/", status_code=303)

    p = session.exec(select(QueryProduct).where(
        QueryProduct.company_id == ctx.company.id,
        QueryProduct.code == code,
        QueryProduct.enabled == True,  # noqa
        QueryProduct.code != "directdata.cadastral_pf",
    )).first()
    if not p:
        raise HTTPException(status_code=404, detail="Consulta não encontrada.")

    norm_doc = re.sub(r"\D+", "", doc or "")
    if not norm_doc:
        set_flash(request, "Documento inválido.")
        return RedirectResponse(f"/consultas/{code}", status_code=303)


    # SCR exige aceite do titular do CPF/CNPJ consultado (link + e-mail)
    if _is_scr_consulta_product(p.code):
        if not ensure_consulta_scr_consent_table():
            set_flash(request, "Sistema de aceite SCR não está configurado (migração pendente no banco).")
            return RedirectResponse(f"/consultas/{code}?doc={norm_doc}", status_code=303)
        if not _has_valid_consulta_scr_consent(session, company_id=ctx.company.id, subject_doc=norm_doc):
            set_flash(request, "Antes de consultar SCR, envie o e-mail de aceite e aguarde o titular confirmar.")
            return RedirectResponse(f"/consultas/{code}?doc={norm_doc}", status_code=303)

    price = _price_cents(p.provider_cost_cents, p.markup_pct)

    run = QueryRun(
        company_id=ctx.company.id,
        client_id=client.id,
        created_by_user_id=ctx.user.id,
        product_code=p.code,
        subject_doc=norm_doc,
        status="PENDING",
        price_cents=price,
        provider_cost_cents=p.provider_cost_cents,
        created_at=utcnow(),
        updated_at=utcnow(),
    )
    session.add(run)
    session.commit()
    session.refresh(run)

    _wallet_debit_or_402(
        session,
        company_id=ctx.company.id,
        client_id=client.id,
        amount_cents=price,
        run_id=run.id,
        note=f"Consulta: {p.label} ({p.code}) doc={norm_doc}",
    )

    try:
        status, data, msg = await _directdata_call_real(product_code=p.code, doc_digits=norm_doc)
        if not status or data is None:
            raise RuntimeError(msg or f"Falha Direct Data status={status}")

        # Se veio "Em Processamento", aguarda e atualiza com resultado final
        md = (data.get("metaDados") or {})
        run.provider_uid = md.get("consultaUid") or run.provider_uid

        if (_dd_is_processing(data) or ((data.get("metaDados") or {}).get("resultado","").lower().find("process")!=-1)) and run.provider_uid:
            ok, final_data, _ = await _directdata_wait_result(run.provider_uid, timeout_s=60)
            if ok and final_data is not None:
                data = final_data
            else:
                # mantém pendente; usuário pode atualizar depois
                run.status = "PENDING"
                run.result_json = json.dumps(data, ensure_ascii=False, indent=2)
                run.updated_at = utcnow()
                session.add(run)
                session.commit()
                # render pendente
                w = _get_or_create_wallet(session, company_id=ctx.company.id, client_id=client.id)
                product_view = {"code": p.code, "label": p.label, "category": p.category, "price_cents": int(run.price_cents)}
                return render("consulta_run.html", request=request, context={
                    "title": p.label,
                    "product": product_view,
                    "wallet_balance": f"{w.balance_cents/100:.2f}",
                    "run": run,

"doc_value": norm_doc,
"product_is_scr": bool(_is_scr_consulta_product(p.code)),
"scr_consent_status": ("valida" if _is_scr_consulta_product(p.code) else ""),
"scr_consent_expires_at": None,
"consulta_consent_link_url": str(request.session.get("consulta_consent_link_url") or ""),
                    "client": client,
                })

        # pronto
        run.result_json = json.dumps(data, ensure_ascii=False, indent=2)
        run.status = "READY"
        run.updated_at = utcnow()
        session.add(run)
        session.commit()
    except Exception as e:
        _wallet_refund(session, company_id=ctx.company.id, client_id=client.id, amount_cents=run.price_cents, run_id=run.id, note=f"Estorno por falha Direct Data: {p.code}")
        run.status = "FAILED"
        run.error = str(e)
        run.updated_at = utcnow()
        session.add(run)
        session.commit()

    w = _get_or_create_wallet(session, company_id=ctx.company.id, client_id=client.id)
    pv = {"code": p.code, "label": p.label, "price_cents": price}
    return render("consulta_run.html", request=request, context={
        "title": p.label,
        "product": pv,
        "wallet_balance": f"{w.balance_cents/100:.2f}",
        "run": run,

"doc_value": norm_doc,
"product_is_scr": bool(_is_scr_consulta_product(p.code)),
"scr_consent_status": ("valida" if _is_scr_consulta_product(p.code) else ""),
"scr_consent_expires_at": None,
"consulta_consent_link_url": str(request.session.get("consulta_consent_link_url") or ""),
    })




@app.get("/consultas/run/{run_id}", response_class=HTMLResponse)
@require_login
async def consultas_run_view(request: Request, session: Session = Depends(get_session), run_id: int = 0) -> HTMLResponse:
    ctx = get_tenant_context(request, session)
    assert ctx is not None
    run = session.get(QueryRun, int(run_id))
    if not run or run.company_id != ctx.company.id:
        raise HTTPException(status_code=404, detail="Consulta não encontrada.")

    client = session.get(Client, int(run.client_id))
    if not client or client.company_id != ctx.company.id:
        raise HTTPException(status_code=404, detail="Cliente inválido.")

    # Atualiza se pendente e tem provider_uid
    if run.status == "PENDING" and run.provider_uid:
        ok, final_data, msg = await _directdata_wait_result(run.provider_uid, timeout_s=30)
        if ok and final_data is not None:
            run.result_json = json.dumps(final_data, ensure_ascii=False, indent=2)
            run.status = "READY"
            run.updated_at = utcnow()
            session.add(run)
            session.commit()
        else:
            # mantém pendente; não estorna aqui
            pass

    # recuperar product
    p = session.exec(select(QueryProduct).where(QueryProduct.company_id == ctx.company.id, QueryProduct.code == run.product_code)).first()
    label = p.label if p else run.product_code
    price_cents = run.price_cents

    w = _get_or_create_wallet(session, company_id=ctx.company.id, client_id=client.id)
    product_view = {"code": run.product_code, "label": label, "category": (p.category if p else "credito"), "price_cents": int(run.price_cents)}
    return render("consulta_run.html", request=request, context={
        "title": label,
        "product": product_view,
        "wallet_balance": f"{w.balance_cents/100:.2f}",
        "run": run,
        "client": client,
    })


@app.get("/consultas/run/{run_id}/pdf")
@require_login
async def consultas_run_pdf(request: Request, session: Session = Depends(get_session), run_id: int = 0) -> Response:
    ctx = get_tenant_context(request, session)
    assert ctx is not None
    run = session.get(QueryRun, int(run_id))
    if not run or run.company_id != ctx.company.id:
        raise HTTPException(status_code=404, detail="Consulta não encontrada.")

    client = session.get(Client, int(run.client_id))
    if not client or client.company_id != ctx.company.id:
        raise HTTPException(status_code=404, detail="Cliente inválido.")

    if run.status != "READY":
        raise HTTPException(status_code=409, detail="Consulta ainda não finalizada.")

    p = session.exec(select(QueryProduct).where(QueryProduct.company_id == ctx.company.id, QueryProduct.code == run.product_code)).first()
    label = p.label if p else run.product_code

    data = {}
    try:
        data = json.loads(run.result_json or "{}")
    except Exception:
        data = {}

    pdf_bytes = build_consulta_pdf(
        company_name=ctx.company.name,
        client_name=client.name,
        product_label=label,
        product_code=run.product_code,
        subject_doc=run.subject_doc,
        data=data,
    )
    filename = f"relatorio_{run.product_code}_{run.id}.pdf".replace("/", "_")
    return StreamingResponse(io.BytesIO(pdf_bytes), media_type="application/pdf", headers={
        "Content-Disposition": f'attachment; filename="{filename}"'
    })


@app.get("/admin/consultas", response_class=HTMLResponse)
@require_role({"admin", "equipe"})
async def admin_consultas(request: Request, session: Session = Depends(get_session)) -> HTMLResponse:
    ctx = get_tenant_context(request, session)
    if not ctx:
        request.session.clear()
        return RedirectResponse("/login", status_code=303)

    _seed_credit_products(session, ctx.company.id)
    products = session.exec(select(QueryProduct).where(QueryProduct.company_id == ctx.company.id).order_by(QueryProduct.label)).all()
    enriched = [{
        "code": p.code,
        "label": p.label,
        "provider_cost_cents": p.provider_cost_cents,
        "markup_pct": p.markup_pct,
        "enabled": p.enabled,
        "price_cents": _price_cents(p.provider_cost_cents, p.markup_pct),
    } for p in products]

    return render("admin_consultas.html", request=request, context={"title": "Admin Consultas", "products": enriched})


@app.post("/admin/consultas/save")
@require_role({"admin"})
async def admin_consultas_save(
    request: Request,
    session: Session = Depends(get_session),
    code: str = Form(...),
    label: str = Form(...),
    provider_cost: str = Form("0"),
    markup_pct: int = Form(50),
) -> Response:
    ctx = get_tenant_context(request, session)
    if not ctx:
        request.session.clear()
        return RedirectResponse("/login", status_code=303)

    cost_cents = int(_dec(provider_cost) * Decimal("100"))
    markup = max(50, int(markup_pct or 50))

    p = session.exec(select(QueryProduct).where(QueryProduct.company_id == ctx.company.id, QueryProduct.code == code)).first()
    if p:
        p.label = label
        p.provider_cost_cents = cost_cents
        p.markup_pct = markup
        p.updated_at = utcnow()
        session.add(p)
    else:
        session.add(
            QueryProduct(
                company_id=ctx.company.id,
                code=code,
                label=label,
                category="credito",
                provider="directdata",
                provider_cost_cents=cost_cents,
                markup_pct=markup,
                enabled=True,
                created_at=utcnow(),
                updated_at=utcnow(),
            )
        )
    session.commit()
    set_flash(request, "Produto salvo.")
    return RedirectResponse("/admin/consultas", status_code=303)


@app.post("/admin/consultas/toggle")
@require_role({"admin"})
async def admin_consultas_toggle(request: Request, session: Session = Depends(get_session), code: str = Form(...)) -> Response:
    ctx = get_tenant_context(request, session)
    if not ctx:
        request.session.clear()
        return RedirectResponse("/login", status_code=303)

    p = session.exec(select(QueryProduct).where(QueryProduct.company_id == ctx.company.id, QueryProduct.code == code)).first()
    if not p:
        return RedirectResponse("/admin/consultas", status_code=303)

    p.enabled = not bool(p.enabled)
    p.updated_at = utcnow()
    session.add(p)
    session.commit()
    return RedirectResponse("/admin/consultas", status_code=303)



@app.get("/openfinance", response_class=HTMLResponse)
@require_login
async def openfinance_home(request: Request, doc: str = "", email: str = "", session: Session = Depends(get_session)) -> HTMLResponse:
    ctx = get_tenant_context(request, session)
    if not ctx:
        request.session.clear()
        return RedirectResponse("/login", status_code=303)

    client = _openfinance_require_client(request, session, ctx)
    if not client:
        set_flash(request, "Selecione um cliente para usar Open Finance.")
        return RedirectResponse("/", status_code=303)

    doc_digits = _digits(doc)
    email_default = (email or "").strip() or (client.finance_email or client.email or "").strip()

    provider = (os.getenv("OPENFINANCE_PROVIDER_DEFAULT") or "klavi").strip().lower()
    if provider == "klavi":
        from urllib.parse import urlencode
        q: dict[str, str] = {}
        if doc:
            q["doc"] = doc
        if email:
            q["email"] = email
        qs = ("?" + urlencode(q)) if q else ""
        return RedirectResponse(f"/openfinance/klavi{qs}", status_code=303)

    conn = None
    loans: list[PluggyLoan] = []
    offers = session.exec(select(PluggyOffer).where(PluggyOffer.company_id == ctx.company.id).order_by(PluggyOffer.created_at.desc())).all()
    opp_rows = []
    invite_link = ""
    self_connect_link = ""

    try:
        if (request.session.get("of_invite_doc") or "") == doc_digits:
            exp_ts = int(request.session.get("of_invite_exp") or 0)
            if not exp_ts or utcnow().timestamp() <= exp_ts:
                invite_link = str(request.session.get("of_invite_link") or "")
    except Exception:
        pass

    if doc_digits:
        conn = session.exec(
            select(PluggyConnection).where(
                PluggyConnection.company_id == ctx.company.id,
                PluggyConnection.subject_doc == doc_digits,
            )
        ).first()
        loans = session.exec(
            select(PluggyLoan).where(
                PluggyLoan.company_id == ctx.company.id,
                PluggyLoan.subject_doc == doc_digits,
            ).order_by(PluggyLoan.fetched_at.desc())
        ).all()

        # oportunidades + label oferta
        opps = session.exec(
            select(PluggyOpportunity).where(
                PluggyOpportunity.company_id == ctx.company.id,
                PluggyOpportunity.subject_doc == doc_digits,
            ).order_by(PluggyOpportunity.total_savings_brl.desc())
        ).all()
        offer_by_id = {int(o.id or 0): o for o in offers}
        for o in opps:
            off = offer_by_id.get(int(o.offer_id or 0))
            opp_rows.append(
                {
                    "pluggy_loan_id": o.pluggy_loan_id,
                    "offer_label": off.label if off else f"Oferta #{o.offer_id}",
                    "old_payment_brl": o.old_payment_brl,
                    "new_payment_brl": o.new_payment_brl,
                    "monthly_savings_brl": o.monthly_savings_brl,
                    "total_savings_brl": o.total_savings_brl,
                }
            )

        # link auto para cliente (se o próprio cliente estiver logado)
        payload = {"t": "pluggy_invite", "company_id": ctx.company.id, "doc": doc_digits, "exp": int((utcnow() + timedelta(hours=24)).timestamp())}
        token = _sign_consent_token(payload)
        self_connect_link = f"/openfinance/connect/{token}"

    return render(
        "openfinance.html",
        request=request,
        context={
            "title": "Open Finance",
            "current_user": ctx.user,
            "current_company": ctx.company,
            "role": ctx.membership.role,
            "current_client": client,
            "doc": doc_digits,
            "email_default": email_default,
            "conn": conn,
            "loans": loans,
            "offers": offers,
            "opportunities": opp_rows,
            "invite_link": invite_link,
            "self_connect_link": self_connect_link,
        },
    )


@app.post("/openfinance/invite")
@require_role({"admin", "equipe"})
async def openfinance_invite(
    request: Request,
    doc: str = Form(...),
    email: str = Form(...),
    session: Session = Depends(get_session),
) -> Response:
    ctx = get_tenant_context(request, session)
    if not ctx:
        request.session.clear()
        return RedirectResponse("/login", status_code=303)

    client = _openfinance_require_client(request, session, ctx)
    if not client:
        set_flash(request, "Selecione um cliente.")
        return RedirectResponse("/", status_code=303)

    doc_digits = _digits(doc)
    if len(doc_digits) not in (11, 14):
        set_flash(request, "Documento inválido (use CPF ou CNPJ).")
        return RedirectResponse(f"/openfinance?doc={doc_digits}", status_code=303)

    invited_email = (email or "").strip().lower()
    if "@" not in invited_email:
        set_flash(request, "E-mail inválido.")
        return RedirectResponse(f"/openfinance?doc={doc_digits}", status_code=303)

    expires_at = utcnow() + timedelta(hours=24)
    inv = PluggyConnectInvite(
        company_id=ctx.company.id,
        requested_by_client_id=int(client.id or 0),
        created_by_user_id=int(ctx.user.id or 0),
        subject_doc=doc_digits,
        invited_email=invited_email,
        status="pendente",
        expires_at=expires_at,
        updated_at=utcnow(),
    )
    session.add(inv)
    session.commit()
    session.refresh(inv)

    payload = {"t": "pluggy_invite", "invite_id": int(inv.id or 0), "company_id": ctx.company.id, "doc": doc_digits, "exp": int(expires_at.timestamp())}
    token = _sign_consent_token(payload)
    link = f"{_public_base_url(request)}/openfinance/connect/{token}"

    try:
        request.session["of_invite_doc"] = doc_digits
        request.session["of_invite_link"] = link
        request.session["of_invite_exp"] = int(expires_at.timestamp())
    except Exception:
        pass

    html_body = f"""
      <div style="font-family:Arial,sans-serif; line-height:1.4">
        <h2>Autorização Open Finance (Pluggy)</h2>
        <p>Para analisarmos seus contratos e buscar melhores ofertas de crédito, conecte sua instituição via link abaixo:</p>
        <p><a href="{html.escape(link)}">{html.escape(link)}</a></p>
        <p style="color:#666; font-size:12px">Este link expira em 24 horas.</p>
      </div>
    """

    try:
        _smtp_send_email(to_email=invited_email, subject="Conexão Open Finance (Pluggy) — autorização", html_body=html_body)
        set_flash(request, f"E-mail de conexão enviado para {invited_email}.")
    except Exception as e:
        set_flash(request, f"Não foi possível enviar e-mail (SMTP). Copie o link manualmente. Erro: {e}")

    return RedirectResponse(f"/openfinance?doc={doc_digits}&email={invited_email}", status_code=303)


@app.get("/openfinance/klavi", response_class=HTMLResponse)
@require_login
async def openfinance_klavi_home(request: Request, doc: str = "", email: str = "", session: Session = Depends(get_session)) -> HTMLResponse:
    ctx = get_tenant_context(request, session)
    if not ctx:
        request.session.clear()
        return RedirectResponse("/login", status_code=303)

    client = _openfinance_require_client(request, session, ctx)
    if not client:
        set_flash(request, "Selecione um cliente para usar Open Finance.")
        return RedirectResponse("/", status_code=303)

    if not _klavi_is_configured():
        set_flash(request, "Klavi não configurado (KLAVI_ACCESS_KEY/KLAVI_SECRET_KEY).")
        return RedirectResponse("/openfinance", status_code=303)

    doc_digits = _digits(doc)
    email_default = (email or "").strip() or (client.finance_email or client.email or "").strip()
    phone_default = (getattr(client, "phone", "") or "").strip()

    flow = None
    reports: list[KlaviReport] = []
    if doc_digits:
        flow = session.exec(
            select(KlaviFlow).where(KlaviFlow.company_id == ctx.company.id, KlaviFlow.subject_doc == doc_digits)
        ).first()
        reports = session.exec(
            select(KlaviReport)
            .where(KlaviReport.company_id == ctx.company.id, KlaviReport.subject_doc == doc_digits)
            .order_by(KlaviReport.received_at.desc())
            .limit(10)
        ).all()

    return render(
        "openfinance_klavi.html",
        request=request,
        context={
            "title": "Open Finance (Klavi)",
            "current_user": ctx.user,
            "current_company": ctx.company,
            "role": ctx.membership.role,
            "current_client": client,
            "doc": doc_digits,
            "email_default": email_default,
            "phone_default": phone_default,
            "flow": flow,
            "reports": reports,
        },
    )


@app.post("/openfinance/klavi/start")
@require_login
async def openfinance_klavi_start(
    request: Request,
    doc_input: str = Form(...),
    email: str = Form(...),
    phone: str = Form(...),
    session: Session = Depends(get_session),
) -> HTMLResponse:
    ctx = get_tenant_context(request, session)
    if not ctx:
        request.session.clear()
        return RedirectResponse("/login", status_code=303)

    client = _openfinance_require_client(request, session, ctx)
    if not client:
        set_flash(request, "Selecione um cliente para usar Open Finance.")
        return RedirectResponse("/", status_code=303)

    doc_digits = _digits(doc_input)
    if len(doc_digits) not in (11, 14):
        set_flash(request, "Documento inválido (use CPF ou CNPJ).")
        return RedirectResponse("/openfinance/klavi", status_code=303)

    email_v = (email or "").strip()
    phone_v = (phone or "").strip()
    if "@" not in email_v:
        set_flash(request, "E-mail inválido.")
        return RedirectResponse(f"/openfinance/klavi?doc={doc_digits}", status_code=303)
    base = _public_base_url(request)
    access_token = await _klavi_get_access_token()

    # Create Link (requires Authorization bearer access token)
    link_payload: dict[str, Any] = {
        "email": email_v,
        "redirecturl": f"{base}/openfinance/klavi/retorno?doc={doc_digits}",
        "productscallbackurl": {"all": f"{base}/webhooks/klavi/products"},
        "externalinfo": {"company_id": int(ctx.company.id or 0), "doc": doc_digits, "client_id": int(client.id or 0)},
    }

    if (phone_v or "").strip():
        try:
            phone_norm = _klavi_normalize_phone(phone_v)
            if phone_norm:
                link_payload["phone"] = phone_norm
        except ValueError:
            set_flash(request, "Klavi: telefone inválido. Use DDD+numero (ex: 11999999999). Prosseguindo sem telefone.")

    if len(doc_digits) == 11:
        link_payload["personaltaxid"] = doc_digits
    else:
        link_payload["businesstaxid"] = doc_digits


    # Klavi compatibility: some endpoints validate camelCase fields.
    link_payload.setdefault("redirectUrl", link_payload.get("redirecturl"))
    link_payload.setdefault("redirectURL", link_payload.get("redirecturl"))
    link_payload.setdefault("productsCallbackUrl", link_payload.get("productscallbackurl"))
    link_payload.setdefault("externalInfo", link_payload.get("externalinfo"))
    if "personaltaxid" in link_payload:
        link_payload.setdefault("personalTaxId", link_payload["personaltaxid"])
    if "businesstaxid" in link_payload:
        link_payload.setdefault("businessTaxId", link_payload["businesstaxid"])

    try:
        link_data = await _klavi_post_json(path="/data/v1/links", bearer=access_token, payload=link_payload)
    except httpx.HTTPStatusError as e:
        body = (e.response.text or "").strip()
        set_flash(request, f"Klavi: erro ao criar Link (HTTP {e.response.status_code}). {body[:300]}")
        return RedirectResponse(f"/openfinance/klavi?doc={doc_digits}&email={email_v}", status_code=303)
    except Exception as e:
        set_flash(request, f"Klavi: erro ao criar Link. {type(e).__name__}: {str(e)[:300]}")
        return RedirectResponse(f"/openfinance/klavi?doc={doc_digits}&email={email_v}", status_code=303)

    link_id = str(link_data.get("linkid") or link_data.get("linkId") or "").strip()
    link_token = str(link_data.get("linktoken") or link_data.get("linkToken") or "").strip()
    exp_in = int(link_data.get("expirein") or link_data.get("expireIn") or 1800)

    if not link_id or not link_token:
        raise HTTPException(status_code=502, detail="Klavi: linkId/linkToken ausente.")

    expires_at = utcnow() + timedelta(seconds=max(60, exp_in))

    flow = session.exec(select(KlaviFlow).where(KlaviFlow.company_id == ctx.company.id, KlaviFlow.subject_doc == doc_digits)).first()
    if not flow:
        flow = KlaviFlow(company_id=ctx.company.id, subject_doc=doc_digits, created_at=utcnow())
    flow.email = email_v
    flow.phone = phone_v
    flow.link_id = link_id
    flow.link_token = link_token
    flow.link_expires_at = expires_at
    flow.consent_status = "link_created"
    flow.last_error = ""
    flow.updated_at = utcnow()
    session.add(flow)
    session.commit()

    # Institutions list uses linkToken
    institutions = await _klavi_get_json(path="/data/v1/links/institutions", bearer=link_token)
    if not isinstance(institutions, list):
        institutions = []

    return render(
        "openfinance_klavi_institutions.html",
        request=request,
        context={
            "title": "Open Finance (Klavi) — Instituições",
            "current_user": ctx.user,
            "current_company": ctx.company,
            "role": ctx.membership.role,
            "current_client": client,
            "doc": doc_digits,
            "institutions": institutions,
        },
    )


@app.post("/openfinance/klavi/consent")
@require_login
async def openfinance_klavi_consent(
    request: Request,
    doc: str = Form(...),
    institution_code: str = Form(...),
    institution_name: str = Form(""),
    session: Session = Depends(get_session),
) -> Response:
    ctx = get_tenant_context(request, session)
    if not ctx:
        request.session.clear()
        return RedirectResponse("/login", status_code=303)

    client = _openfinance_require_client(request, session, ctx)
    if not client:
        set_flash(request, "Selecione um cliente para usar Open Finance.")
        return RedirectResponse("/", status_code=303)

    doc_digits = _digits(doc)
    flow = session.exec(select(KlaviFlow).where(KlaviFlow.company_id == ctx.company.id, KlaviFlow.subject_doc == doc_digits)).first()
    if not flow or not flow.link_token:
        set_flash(request, "Fluxo Klavi não iniciado. Refaça o passo 1.")
        return RedirectResponse(f"/openfinance/klavi?doc={doc_digits}", status_code=303)

    exp_at = _as_aware_utc(getattr(flow, 'link_expires_at', None)) or utcnow()
    if utcnow() > exp_at:
        set_flash(request, "LinkToken expirou. Refaça o passo 1.")
        return RedirectResponse(f"/openfinance/klavi?doc={doc_digits}", status_code=303)

    base = _public_base_url(request)
    consent_payload: dict[str, Any] = {
        "externaltrackid": f"mc:{int(ctx.company.id or 0)}:{doc_digits}:{int(utcnow().timestamp())}",
        "institutioncode": str(institution_code or "").strip(),
        "validityperiod": 12,
        "redirecturl": f"{base}/openfinance/klavi/retorno?doc={doc_digits}",
        "email": (flow.email or "").strip(),
    }

    if (flow.phone or "").strip():
        try:
            phone_norm = _klavi_normalize_phone(flow.phone or "")
            if phone_norm:
                consent_payload["phone"] = phone_norm
        except ValueError:
            set_flash(request, "Klavi: telefone inválido. Prosseguindo sem telefone.")

    if len(doc_digits) == 11:
        consent_payload["personaltaxid"] = doc_digits
    else:
        consent_payload["businesstaxid"] = doc_digits


    # Klavi compatibility: some endpoints validate camelCase fields.
    consent_payload.setdefault("externalTrackId", consent_payload.get("externaltrackid"))
    consent_payload.setdefault("institutionCode", consent_payload.get("institutioncode"))
    consent_payload.setdefault("validityPeriod", consent_payload.get("validityperiod"))
    consent_payload.setdefault("redirectUrl", consent_payload.get("redirecturl"))
    consent_payload.setdefault("redirectURL", consent_payload.get("redirecturl"))
    if "personaltaxid" in consent_payload:
        consent_payload.setdefault("personalTaxId", consent_payload["personaltaxid"])
    if "businesstaxid" in consent_payload:
        consent_payload.setdefault("businessTaxId", consent_payload["businesstaxid"])


    try:
        consent_data = await _klavi_post_json(path="/data/v1/consents", bearer=flow.link_token, payload=consent_payload)
    except httpx.HTTPStatusError as e:
        body = (e.response.text or "").strip()
        set_flash(request, f"Klavi: erro ao criar Consent (HTTP {e.response.status_code}). {body[:300]}")
        flow.last_error = body[:900]
        flow.consent_status = "consent_error"
        flow.updated_at = utcnow()
        session.add(flow)
        session.commit()
        return RedirectResponse(f"/openfinance/klavi?doc={doc_digits}", status_code=303)
    except Exception as e:
        set_flash(request, f"Klavi: erro ao criar Consent. {type(e).__name__}: {str(e)[:300]}")
        flow.last_error = f"{type(e).__name__}: {str(e)[:900]}"
        flow.consent_status = "consent_error"
        flow.updated_at = utcnow()
        session.add(flow)
        session.commit()
        return RedirectResponse(f"/openfinance/klavi?doc={doc_digits}", status_code=303)

    consent_id = str(consent_data.get("consentid") or consent_data.get("consentId") or "").strip()
    consent_redirect_url = str(consent_data.get("consentredirecturl") or consent_data.get("consentRedirectUrl") or "").strip()

    if not consent_id or not consent_redirect_url:
        raise HTTPException(status_code=502, detail="Klavi: consentId/consentRedirectUrl ausente.")

    flow.institution_code = str(institution_code or "").strip()
    flow.institution_name = (institution_name or "").strip()
    flow.consent_id = consent_id
    flow.consent_status = "consent_created"
    flow.updated_at = utcnow()
    session.add(flow)
    session.commit()

    return RedirectResponse(consent_redirect_url, status_code=302)


@app.get("/openfinance/klavi/retorno", response_class=HTMLResponse)
async def openfinance_klavi_return(
    request: Request,
    doc: str = "",
    error: str = "",
    error_description: str = "",
    session: Session = Depends(get_session),
) -> HTMLResponse:
    # Retorno do LGDP/Instituição (não exige login; pode ser usado pelo titular)
    doc_digits = _digits(doc)
    message = "Se a autorização foi concluída, solicite o relatório de contratos (Loans)."

    return render(
        "openfinance_klavi_return.html",
        request=request,
        context={
            "title": "Open Finance (Klavi) — Retorno",
            "current_user": None,
            "current_company": None,
            "role": "",
            "current_client": None,
            "doc": doc_digits,
            "message": message,
            "error": error_description or error,
        },
    )


@app.post("/openfinance/klavi/request")
@require_login
async def openfinance_klavi_request_report(
    request: Request,
    doc: str = Form(...),
    session: Session = Depends(get_session),
) -> Response:
    ctx = get_tenant_context(request, session)
    if not ctx:
        request.session.clear()
        return RedirectResponse("/login", status_code=303)

    client = _openfinance_require_client(request, session, ctx)
    if not client:
        set_flash(request, "Selecione um cliente para usar Open Finance.")
        return RedirectResponse("/", status_code=303)

    doc_digits = _digits(doc)
    flow = session.exec(select(KlaviFlow).where(KlaviFlow.company_id == ctx.company.id, KlaviFlow.subject_doc == doc_digits)).first()
    if not flow or not flow.consent_id:
        set_flash(request, "Consentimento não encontrado. Faça a autorização primeiro.")
        return RedirectResponse(f"/openfinance/klavi?doc={doc_digits}", status_code=303)

    try:
        req_id = await klavi_request_loans_report(doc_digits=doc_digits, flow=flow)
        flow.last_request_id = req_id
        flow.consent_status = "report_requested"
        flow.updated_at = utcnow()
        session.add(flow)
        session.commit()
        set_flash(request, f"Relatório solicitado (requestId={req_id}). Aguarde o webhook.")
    except Exception as e:
        flow.last_error = str(e)
        flow.updated_at = utcnow()
        session.add(flow)
        session.commit()
        set_flash(request, f"Falha ao solicitar relatório: {e}")

    return RedirectResponse(f"/openfinance/klavi?doc={doc_digits}", status_code=303)



@app.post("/openfinance/sync")
@require_login
async def openfinance_sync(request: Request, doc: str = Form(...), session: Session = Depends(get_session)) -> Response:
    ctx = get_tenant_context(request, session)
    if not ctx:
        request.session.clear()
        return RedirectResponse("/login", status_code=303)
    doc_digits = _digits(doc)

    conn = session.exec(select(PluggyConnection).where(PluggyConnection.company_id == ctx.company.id, PluggyConnection.subject_doc == doc_digits)).first()
    if not conn or not conn.pluggy_item_id:
        set_flash(request, "Sem conexão Pluggy para este documento.")
        return RedirectResponse(f"/openfinance?doc={doc_digits}", status_code=303)

    try:
        await pluggy_sync_loans(session=session, company_id=ctx.company.id, subject_doc=doc_digits, item_id=conn.pluggy_item_id)
        set_flash(request, "Sincronização concluída.")
    except Exception as e:
        set_flash(request, f"Falha ao sincronizar: {e}")

    return RedirectResponse(f"/openfinance?doc={doc_digits}", status_code=303)


@app.post("/openfinance/offers/add")
@require_role({"admin", "equipe"})
async def openfinance_add_offer(
    request: Request,
    label: str = Form(...),
    cet_aa_pct: str = Form(...),
    product_type: str = Form(""),
    term_min: str = Form("0"),
    term_max: str = Form("0"),
    session: Session = Depends(get_session),
) -> Response:
    ctx = get_tenant_context(request, session)
    if not ctx:
        request.session.clear()
        return RedirectResponse("/login", status_code=303)

    try:
        cet = float(str(cet_aa_pct).replace(",", "."))
    except Exception:
        cet = 0.0

    o = PluggyOffer(
        company_id=ctx.company.id,
        label=(label or "").strip(),
        product_type=(product_type or "").strip(),
        cet_aa=_to_float_rate(cet),
        term_min_months=int(term_min or 0) if str(term_min or "").strip().isdigit() else 0,
        term_max_months=int(term_max or 0) if str(term_max or "").strip().isdigit() else 0,
        updated_at=utcnow(),
    )
    session.add(o)
    session.commit()

    set_flash(request, "Oferta adicionada.")
    return RedirectResponse("/openfinance", status_code=303)


@app.post("/openfinance/opportunities/generate")
@require_login
async def openfinance_generate_opportunities(request: Request, doc: str = Form(...), session: Session = Depends(get_session)) -> Response:
    ctx = get_tenant_context(request, session)
    if not ctx:
        request.session.clear()
        return RedirectResponse("/login", status_code=303)

    doc_digits = _digits(doc)
    try:
        n = _compute_opportunities_for_doc(session=session, company_id=ctx.company.id, subject_doc=doc_digits)
        set_flash(request, f"Oportunidades geradas/atualizadas: {n}.")
    except Exception as e:
        set_flash(request, f"Falha ao gerar oportunidades: {e}")

    return RedirectResponse(f"/openfinance?doc={doc_digits}", status_code=303)


@app.get("/openfinance/connect/{token}", response_class=HTMLResponse)
async def openfinance_connect_page(token: str, request: Request, session: Session = Depends(get_session)) -> HTMLResponse:
    try:
        payload = _verify_consent_token(token)
        if payload.get("t") != "pluggy_invite":
            raise ValueError("tipo inválido")
        company_id = int(payload.get("company_id") or 0)
        doc_digits = _digits(str(payload.get("doc") or ""))
        invite_id = int(payload.get("invite_id") or 0)
    except Exception as e:
        return render("error.html", request=request, context={"current_user": None, "current_company": None, "role": "", "current_client": None, "message": f"Link inválido: {e}"})

    invited_email = ""
    inv = None
    if invite_id:
        inv = session.get(PluggyConnectInvite, invite_id)
        if not inv or int(inv.company_id or 0) != company_id:
            return render("error.html", request=request, context={"current_user": None, "current_company": None, "role": "", "current_client": None, "message": "Convite não encontrado."})
        if inv.status in ("revogada", "expirada"):
            return render("error.html", request=request, context={"current_user": None, "current_company": None, "role": "", "current_client": None, "message": f"Convite {inv.status}."})
        if inv.expires_at and utcnow() > inv.expires_at:
            inv.status = "expirada"
            inv.updated_at = utcnow()
            session.add(inv)
            session.commit()
            return render("error.html", request=request, context={"current_user": None, "current_company": None, "role": "", "current_client": None, "message": "Convite expirado."})
        invited_email = inv.invited_email

    return render(
        "openfinance_connect.html",
        request=request,
        context={
            "title": "Conectar Open Finance",
            "current_user": None,
            "current_company": None,
            "role": "",
            "current_client": None,
            "token": token,
            "doc_masked": _mask_doc(doc_digits),
            "invited_email": invited_email or "(não informado)",
            "pluggy_js_url": PLUGGY_CONNECT_JS_URL,
            "error": "",
        },
    )


@app.post("/api/pluggy/connect_token")
async def pluggy_api_connect_token(request: Request, payload: dict[str, Any], session: Session = Depends(get_session)) -> JSONResponse:
    token = str(payload.get("token") or "").strip()
    signed_by_name = str(payload.get("signed_by_name") or "").strip()
    doc_last4 = str(payload.get("doc_last4") or "").strip()

    try:
        pl = _verify_consent_token(token)
        if pl.get("t") != "pluggy_invite":
            raise ValueError("tipo inválido")
        company_id = int(pl.get("company_id") or 0)
        doc_digits = _digits(str(pl.get("doc") or ""))
        invite_id = int(pl.get("invite_id") or 0)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Token inválido: {e}")

    if not signed_by_name:
        raise HTTPException(status_code=400, detail="Informe o nome.")

    if doc_last4 and doc_digits and doc_last4 != doc_digits[-4:]:
        raise HTTPException(status_code=400, detail="Os 4 últimos dígitos não conferem.")

    # valida convite (se existir)
    if invite_id:
        inv = session.get(PluggyConnectInvite, invite_id)
        if not inv or int(inv.company_id or 0) != company_id or inv.subject_doc != doc_digits:
            raise HTTPException(status_code=400, detail="Convite inválido.")
        if inv.expires_at and utcnow() > inv.expires_at:
            inv.status = "expirada"
            inv.updated_at = utcnow()
            session.add(inv)
            session.commit()
            raise HTTPException(status_code=400, detail="Convite expirado.")
        inv.signed_by_name = signed_by_name
        inv.accepted_at = utcnow()
        inv.status = "conectando"
        inv.updated_at = utcnow()
        session.add(inv)
        session.commit()

    existing = session.exec(
        select(PluggyConnection).where(PluggyConnection.company_id == company_id, PluggyConnection.subject_doc == doc_digits)
    ).first()
    update_item_id = existing.pluggy_item_id if (existing and existing.pluggy_item_id) else None

    try:
        access_token = await _pluggy_create_connect_token(request=request, company_id=company_id, subject_doc=doc_digits, update_item_id=update_item_id)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Falha ao gerar connect token: {e}")

    return JSONResponse(
        {
            "accessToken": access_token,
            "includeSandbox": PLUGGY_INCLUDE_SANDBOX,
            "updateItem": update_item_id or None,
        }
    )


@app.post("/api/pluggy/item_success")
async def pluggy_api_item_success(request: Request, payload: dict[str, Any], session: Session = Depends(get_session)) -> JSONResponse:
    token = str(payload.get("token") or "").strip()
    item_data = payload.get("itemData") or {}
    try:
        pl = _verify_consent_token(token)
        if pl.get("t") != "pluggy_invite":
            raise ValueError("tipo inválido")
        company_id = int(pl.get("company_id") or 0)
        doc_digits = _digits(str(pl.get("doc") or ""))
        invite_id = int(pl.get("invite_id") or 0)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Token inválido: {e}")

    # extrai itemId
    item_id = ""
    connector_id = None
    try:
        if isinstance(item_data, dict):
            item_id = str(item_data.get("id") or item_data.get("itemId") or "").strip()
            if not item_id and isinstance(item_data.get("item"), dict):
                item_id = str(item_data["item"].get("id") or "").strip()
            connector_id = item_data.get("connectorId") or (item_data.get("connector") or {}).get("id") if isinstance(item_data.get("connector"), dict) else None
    except Exception:
        item_id = ""

    if not item_id:
        raise HTTPException(status_code=400, detail="ItemID ausente no retorno do Pluggy Connect.")

    # upsert connection
    conn = session.exec(select(PluggyConnection).where(PluggyConnection.company_id == company_id, PluggyConnection.subject_doc == doc_digits)).first()
    if not conn:
        conn = PluggyConnection(company_id=company_id, subject_doc=doc_digits)

    conn.client_user_id = _pluggy_client_user_id(company_id=company_id, subject_doc=doc_digits)
    conn.pluggy_item_id = item_id
    try:
        conn.connector_id = int(connector_id) if connector_id is not None else conn.connector_id
    except Exception:
        pass
    conn.status = "connected"
    conn.last_event = "connect_success"
    conn.last_error = ""
    conn.updated_at = utcnow()
    try:
        conn.raw_item_json = json.dumps(item_data, ensure_ascii=False)
    except Exception:
        conn.raw_item_json = ""

    session.add(conn)

    # marca convite como válido (se existir)
    if invite_id:
        inv = session.get(PluggyConnectInvite, invite_id)
        if inv:
            inv.status = "valida"
            inv.updated_at = utcnow()
            session.add(inv)

    session.commit()

    # tenta sincronizar loans já
    try:
        await pluggy_sync_loans(session=session, company_id=company_id, subject_doc=doc_digits, item_id=item_id)
    except Exception as e:
        # não falha o fluxo do usuário; apenas grava erro para diagnosticar
        conn.last_error = f"Conectou, mas falhou ao sincronizar loans: {e}"
        conn.updated_at = utcnow()
        session.add(conn)
        session.commit()

    return JSONResponse({"ok": True, "itemId": item_id})


@app.api_route("/webhooks/pluggy", methods=["POST", "GET", "HEAD"])
@app.api_route("/api/webhooks/pluggy", methods=["POST", "GET", "HEAD"])
async def pluggy_webhook(request: Request, k: str = "", session: Session = Depends(get_session)) -> JSONResponse:
    if request.method != "POST":
        return JSONResponse({"ok": True})

    req_ip = _get_request_ip(request)
    if PLUGGY_WEBHOOK_KEY and (k or "") != PLUGGY_WEBHOOK_KEY:
        if req_ip not in PLUGGY_WEBHOOK_TRUSTED_IPS:
            raise HTTPException(status_code=401, detail="unauthorized")

    body = await request.json()
    event = str(body.get("event") or "").strip()
    item_id = str(body.get("itemId") or "").strip()
    client_user_id = str(body.get("clientUserId") or "").strip()

    if not item_id:
        return JSONResponse({"ok": True})

    # tenta derivar company+doc do clientUserId (mc:company:doc)
    company_id = 0
    doc_digits = ""
    if client_user_id.startswith("mc:"):
        parts = client_user_id.split(":")
        if len(parts) >= 3:
            try:
                company_id = int(parts[1])
            except Exception:
                company_id = 0
            doc_digits = _digits(parts[2])

    if not company_id or not doc_digits:
        # fallback: procura pelo itemId
        conn = session.exec(select(PluggyConnection).where(PluggyConnection.pluggy_item_id == item_id)).first()
        if conn:
            company_id = int(conn.company_id or 0)
            doc_digits = conn.subject_doc

    if not company_id or not doc_digits:
        return JSONResponse({"ok": True})

    conn = session.exec(select(PluggyConnection).where(PluggyConnection.company_id == company_id, PluggyConnection.subject_doc == doc_digits)).first()
    if conn:
        conn.last_event = event
        if event in ("item/updated", "item/created", "item/login_succeeded"):
            conn.status = "updating"
        if event == "item/error":
            conn.status = "error"
            err = body.get("error") or {}
            if isinstance(err, dict):
                conn.last_error = f"{err.get('code')}: {err.get('message')}"
        conn.updated_at = utcnow()
        session.add(conn)
        session.commit()

    if event in ("item/created", "item/updated"):
        try:
            _pluggy_schedule_sync_loans(company_id=company_id, subject_doc=doc_digits, item_id=item_id)
        except Exception as e:
            if conn:
                conn.last_error = f"Webhook schedule falhou: {e}"
                conn.updated_at = utcnow()
                session.add(conn)
                session.commit()

    return JSONResponse({"ok": True})


def _klavi_extract_meta(payload: Any) -> tuple[int, str, str]:
    """Retorna (company_id, doc_digits, link_id) best-effort."""
    company_id = 0
    doc_digits = ""
    link_id = ""

    if isinstance(payload, dict):
        ext = payload.get("externalInfo") or payload.get("externalInfo") or {}
        if isinstance(ext, dict):
            try:
                company_id = int(ext.get("company_id") or ext.get("companyId") or 0)
            except Exception:
                company_id = 0
            doc_digits = _digits(str(ext.get("doc") or ""))
        link_id = str(payload.get("linkid") or payload.get("linkId") or "").strip()

        for k in ("personalTaxId", "personalTaxId", "businessTaxId", "businessTaxId", "taxid", "taxId"):
            if not doc_digits:
                doc_digits = _digits(str(payload.get(k) or ""))

    if not doc_digits:
        for d in _deep_iter_dicts(payload):
            for k in ("personalTaxId", "personalTaxId", "businessTaxId", "businessTaxId", "taxid", "taxId"):
                if k in d:
                    doc_digits = _digits(str(d.get(k) or ""))
                    if doc_digits:
                        break
            if doc_digits:
                break

    return company_id, doc_digits, link_id


def _klavi_process_products_webhook(payload: Any) -> None:
    try:
        with Session(engine) as session:
            company_id, doc_digits, link_id = _klavi_extract_meta(payload)

            flow = None
            if doc_digits:
                flow = session.exec(select(KlaviFlow).where(KlaviFlow.subject_doc == doc_digits).order_by(KlaviFlow.updated_at.desc())).first()
                if flow and not company_id:
                    company_id = int(flow.company_id or 0)
                if flow and not link_id:
                    link_id = flow.link_id

            if not company_id:
                return

            product = "loans"
            if isinstance(payload, dict):
                product = str(payload.get("product") or payload.get("productName") or payload.get("report") or "loans")

            request_id = ""
            if isinstance(payload, dict):
                request_id = str(payload.get("requestid") or payload.get("requestId") or "").strip()

            rep = KlaviReport(
                company_id=company_id,
                subject_doc=doc_digits,
                product=product,
                request_id=request_id,
                received_at=utcnow(),
                raw_json=json.dumps(payload, ensure_ascii=False, default=str),
            )
            session.add(rep)

            # Importar contratos para PluggyLoan (normalizado)
            if doc_digits:
                for contract in _klavi_extract_contract_dicts(payload):
                    loan = _klavi_contract_to_loan(company_id=company_id, subject_doc=doc_digits, link_id=link_id or "unknown", contract=contract, raw_payload=payload)
                    existing = session.exec(
                        select(PluggyLoan).where(PluggyLoan.company_id == company_id, PluggyLoan.pluggy_loan_id == loan.pluggy_loan_id)
                    ).first()
                    if existing:
                        for k in (
                            "subject_doc",
                            "pluggy_item_id",
                            "pluggy_loan_id",
                            "contract_number",
                            "ipoc_code",
                            "lender_name",
                            "product_type",
                            "amortization_type",
                            "principal_brl",
                            "outstanding_brl",
                            "installment_brl",
                            "term_total_months",
                            "term_remaining_months",
                            "cet_aa",
                            "interest_aa",
                            "fetched_at",
                            "raw_json",
                        ):
                            setattr(existing, k, getattr(loan, k))
                        session.add(existing)
                    else:
                        session.add(loan)

            if flow:
                flow.consent_status = "report_received"
                flow.updated_at = utcnow()
                session.add(flow)

            session.commit()
    except Exception as e:
        try:
            print(f"[klavi] products webhook failed: {e}")
        except Exception:
            pass


def _klavi_process_events_webhook(payload: Any) -> None:
    try:
        with Session(engine) as session:
            company_id, doc_digits, _ = _klavi_extract_meta(payload)
            if not doc_digits:
                return
            flow = session.exec(select(KlaviFlow).where(KlaviFlow.subject_doc == doc_digits).order_by(KlaviFlow.updated_at.desc())).first()
            if not flow:
                return
            if company_id and int(flow.company_id or 0) != int(company_id):
                # ignora evento de outro tenant
                return

            if isinstance(payload, dict):
                status = str(payload.get("status") or payload.get("event") or payload.get("type") or "").strip().lower()
                if status:
                    flow.consent_status = status
                err = payload.get("error") or payload.get("message") or ""
                if err and "error" in status:
                    flow.last_error = str(err)
            flow.updated_at = utcnow()
            session.add(flow)
            session.commit()
    except Exception as e:
        try:
            print(f"[klavi] events webhook failed: {e}")
        except Exception:
            pass


@app.api_route("/webhooks/klavi/products", methods=["POST", "GET", "HEAD"])
@app.api_route("/api/webhooks/klavi/products", methods=["POST", "GET", "HEAD"])
async def klavi_products_webhook(request: Request) -> JSONResponse:
    if request.method != "POST":
        return JSONResponse({"ok": True})
    body = await request.json()
    _klavi_process_products_webhook(body)
    return JSONResponse({"ok": True})


@app.api_route("/webhooks/klavi/events", methods=["POST", "GET", "HEAD"])
@app.api_route("/api/webhooks/klavi/events", methods=["POST", "GET", "HEAD"])
async def klavi_events_webhook(request: Request) -> JSONResponse:
    if request.method != "POST":
        return JSONResponse({"ok": True})
    body = await request.json()
    _klavi_process_events_webhook(body)
    return JSONResponse({"ok": True})



@app.on_event("startup")
def _startup() -> None:
    init_db()
    ensure_ui_tables()
    ensure_feature_access_tables()
    ensure_credit_consent_table()
    ensure_pluggy_tables()
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


# ----------------------------
# Auth routes
# ----------------------------


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, session: Session = Depends(get_session)) -> HTMLResponse:
    if get_current_user(request, session):
        return RedirectResponse("/", status_code=303)
    return render("login.html", request=request, context={"current_user": None})

# === /CREDIT_WALLET_MODULE_V1 ===
# ----------------------------
# Entrypoint (local / platforms that run `python app.py`)
# ----------------------------
if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app:app",
        host="0.0.0.0",
        port=int(os.getenv("PORT", "8000")),
        log_level=os.getenv("LOG_LEVEL", "info").lower(),
    )

# /app.py
from __future__ import annotations
from sqlalchemy import func, delete
from sqlalchemy.exc import OperationalError

import base64
import hashlib
import hmac
import inspect
import json
import os
import re
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from functools import wraps
from pathlib import Path
from typing import Any, Callable, Optional
from urllib.parse import urlparse

import httpx
from fastapi import BackgroundTasks, Depends, FastAPI, File, Form, Request, Response, UploadFile
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


def init_db() -> None:
    # Em produção (Postgres), quem cria/alterar tabelas é o Alembic.
    # Em dev local (SQLite), criamos automaticamente.
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


pass


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
              <input type="hidden" name="next" value="/propostas/{{ prop.id }}">
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
              <input type="hidden" name="next" value="/propostas/{{ prop.id }}">
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
    ctx.setdefault("allow_company_signup", ALLOW_COMPANY_SIGNUP)
    ctx.setdefault("service_catalog", SERVICE_CATALOG)
    ctx.setdefault("bookings_url", BOOKINGS_URL)
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
    ensure_credit_consent_table()
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

    items = [
        {"title": "Pendências", "desc": "Checklist / pedidos de documentos.", "href": "/pendencias"},
        {"title": "Documentos", "desc": "Contratos e docs importantes.", "href": "/documentos"},
        {"title": "Propostas", "desc": "Propostas e solicitações.", "href": "/propostas"},
        {"title": "CRM", "desc": "Negócios e funil comercial.", "href": "/negocios"},
        {"title": "Crédito", "desc": "SCR (Direct Data).", "href": "/credito"},
        {"title": "Financeiro", "desc": "Notas/boletos de honorários.", "href": "/financeiro"},
        {"title": "Empresa", "desc": "Dados completos do cliente.", "href": "/empresa"},
        {"title": "Perfil", "desc": "Indicadores do cliente.", "href": "/perfil"},
        {"title": "Consultoria", "desc": "Projetos, etapas e progresso.", "href": "/consultoria"},
        {"title": "Tarefas", "desc": "Kanban e prazos.", "href": "/tarefas"},
        {"title": "Reuniões", "desc": "Atas e notas (Notion).", "href": "/reunioes"},
        {"title": "Educação", "desc": "Cursos e materiais.", "href": "/educacao"},
        {"title": "Agenda", "desc": "Agendamentos (Bookings).", "href": "/agenda"},
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
        return bool(inv.expires_at and utcnow() > inv.expires_at)
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

    q = select(FinanceInvoice).where(FinanceInvoice.company_id == ctx.company.id).order_by(
        FinanceInvoice.created_at.desc())
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


async def _directdata_scr_request(*, document_type: str, document_value: str, consulta_uid: str = "") -> tuple[
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
            resp = await client.get(DIRECTDATA_SCR_URL, params=params)
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


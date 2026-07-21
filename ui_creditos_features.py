# ui_creditos_features.py — Ativação de features via créditos do plano
# Exec'd no namespace do app.py (substitui ui_tool_assinaturas.py)
#
# Modelo:
#   1. Cliente contrata 1 plano Stripe → recebe N créditos/mês
#   2. Dentro da plataforma, admin ativa features (obras, augur, financeiro…)
#      debitando créditos da carteira do cliente — SEM Stripe por ferramenta
#   3. Na renovação mensal: créditos velhos EXPIRAM (reset para teto do plano),
#      features ativas são debitadas automaticamente
#   4. Créditos restantes ficam livres para consultas ad-hoc (ConstruRisk etc.)
#
# Compatibilidade:
#   - Redefine _renovar_plano_cliente() (exec'd depois de ui_monetizacao.py)
#   - Exporta _feature_ativa(), _tool_assinatura_ativa(), _augur_assinatura_ativa()

from typing import Optional as _OptCF
from datetime import datetime as _dtCF, timedelta as _tdCF, timezone as _tzCF
from sqlmodel import Field as _FCF, SQLModel as _SMCF, UniqueConstraint as _UCCF
import threading as _thCF

# ── Modelo ─────────────────────────────────────────────────────────────────────

class AssinaturaFeature(_SMCF, table=True):
    """Feature ativa para um cliente — paga em créditos/mês."""
    __tablename__  = "assinaturafeature"
    __table_args__ = (
        _UCCF("company_id", "client_id", "feature_codigo", "user_id",
              name="uq_assinaturafeature"),
        {"extend_existing": True},
    )
    id:              _OptCF[int] = _FCF(default=None, primary_key=True)
    company_id:      int         = _FCF(index=True)
    client_id:       int         = _FCF(index=True)
    user_id:         _OptCF[int] = _FCF(default=None, index=True)  # None = empresa; set = usuário (Augur)
    feature_codigo:  str         = _FCF(index=True)   # matches ProdutoPreco.codigo
    creditos_mes:    int         = _FCF(default=0)    # snapshot do custo na ativação
    ativo:           bool        = _FCF(default=True)
    ativado_em:      str         = _FCF(default="")
    renovacao_em:    str         = _FCF(default="")   # proximo_ciclo do ClientePlano

# Cria tabela
try:
    _SMCF.metadata.create_all(engine, tables=[AssinaturaFeature.__table__], checkfirst=True)
    print("[creditos_features] ✅ Tabela assinaturafeature OK")
except Exception as _e_cf_tb:
    print(f"[creditos_features] tabela: {_e_cf_tb}")

# ── Helpers internos ───────────────────────────────────────────────────────────

def _cf_utcnow() -> str:
    return _dtCF.now(_tzCF.utc).strftime("%Y-%m-%d %H:%M:%S")

def _cf_hoje() -> str:
    return _dtCF.now(_tzCF.utc).strftime("%Y-%m-%d")

def _cf_preco(session, company_id: int, feature_codigo: str) -> int:
    """Retorna custo em créditos/mês do produto (ProdutoPreco.creditos)."""
    try:
        pp = session.exec(
            select(ProdutoPreco)
            .where(ProdutoPreco.company_id == company_id,
                   ProdutoPreco.codigo == feature_codigo,
                   ProdutoPreco.ativo == True)
        ).first()
        if pp:
            return int(pp.creditos or 0)
    except Exception:
        pass
    # fallback para _PRODUTOS_BASE
    try:
        for p in _PRODUTOS_BASE:
            if p["codigo"] == feature_codigo:
                return int(p.get("creditos", 0))
    except Exception:
        pass
    return 0

def _cf_wallet(session, company_id: int, client_id: int):
    """Retorna (ou cria) a carteira do cliente."""
    return _get_or_create_wallet(session, company_id=company_id, client_id=client_id)

def _cf_saldo_creditos(session, company_id: int, client_id: int) -> float:
    """Saldo atual em créditos (1 crédito = 100 cents)."""
    try:
        w = _cf_wallet(session, company_id, client_id)
        return w.balance_cents / 100
    except Exception:
        return 0.0

def _cf_debitar(session, company_id: int, client_id: int,
                creditos: int, motivo: str, ref_tipo: str = "feature", ref_id: str = "") -> bool:
    """Debita créditos da carteira. Retorna False se saldo insuficiente."""
    try:
        cents = int(creditos) * 100
        w = _cf_wallet(session, company_id, client_id)
        if w.balance_cents < cents:
            return False
        w.balance_cents -= cents
        w.updated_at = _dtCF.now(_tzCF.utc)
        session.add(w)
        session.add(CreditLedger(
            company_id=company_id,
            client_id=client_id,
            kind="FEATURE_CHARGE",
            amount_cents=-cents,
            ref_type=ref_tipo,
            ref_id=ref_id,
            note=motivo,
        ))
        return True
    except Exception as _e:
        print(f"[creditos_features] debitar: {_e}")
        return False

def _cf_plano_ativo(session, company_id: int, client_id: int):
    """Retorna ClientePlano + PlanoCredito ativos para o cliente."""
    try:
        cp = session.exec(
            select(ClientePlano)
            .where(ClientePlano.company_id == company_id,
                   ClientePlano.client_id  == client_id,
                   ClientePlano.ativo      == True)
        ).first()
        if not cp:
            return None, None
        plano = session.get(PlanoCredito, cp.plano_id)
        return cp, plano
    except Exception:
        return None, None

# ── Funções públicas ───────────────────────────────────────────────────────────

def _feature_ativa(session, company_id: int, client_id: int,
                   feature_codigo: str, user_id: _OptCF[int] = None) -> bool:
    """Verifica se uma feature está ativa para o cliente (ou usuário)."""
    try:
        af = session.exec(
            select(AssinaturaFeature)
            .where(AssinaturaFeature.company_id     == company_id,
                   AssinaturaFeature.client_id      == client_id,
                   AssinaturaFeature.feature_codigo == feature_codigo,
                   AssinaturaFeature.user_id        == user_id,
                   AssinaturaFeature.ativo          == True)
        ).first()
        return bool(af)
    except Exception:
        return False

def _feature_ativar(session, company_id: int, client_id: int,
                    feature_codigo: str, user_id: _OptCF[int] = None) -> tuple[bool, str]:
    """
    Ativa uma feature debitando créditos.
    Retorna (sucesso, mensagem).
    """
    cp, plano = _cf_plano_ativo(session, company_id, client_id)
    if not cp or not plano:
        return False, "Cliente sem plano ativo. Contrate um plano para ativar features."

    custo = _cf_preco(session, company_id, feature_codigo)
    saldo = _cf_saldo_creditos(session, company_id, client_id)

    if custo > 0 and saldo < custo:
        return False, f"Saldo insuficiente. Necessário: {custo} créditos, disponível: {saldo:.0f}."

    # Upsert AssinaturaFeature
    try:
        af = session.exec(
            select(AssinaturaFeature)
            .where(AssinaturaFeature.company_id     == company_id,
                   AssinaturaFeature.client_id      == client_id,
                   AssinaturaFeature.feature_codigo == feature_codigo,
                   AssinaturaFeature.user_id        == user_id)
        ).first()
        if af:
            if af.ativo:
                return True, "Feature já está ativa."
            af.ativo = True
            af.creditos_mes = custo
            af.ativado_em   = _cf_utcnow()
            af.renovacao_em = cp.proximo_ciclo
        else:
            af = AssinaturaFeature(
                company_id=company_id,
                client_id=client_id,
                user_id=user_id,
                feature_codigo=feature_codigo,
                creditos_mes=custo,
                ativo=True,
                ativado_em=_cf_utcnow(),
                renovacao_em=cp.proximo_ciclo,
            )
        session.add(af)

        # Debita créditos (primeira mensalidade)
        if custo > 0:
            ok = _cf_debitar(session, company_id, client_id,
                             custo, f"Ativação: {feature_codigo}", ref_id=feature_codigo)
            if not ok:
                session.rollback()
                return False, "Erro ao debitar créditos."

        session.commit()

        # Sincroniza sistema legado (ClientToolSubscription) para financeiro_gerencial
        if feature_codigo == "financeiro_gerencial_mensal":
            try:
                sub_leg = session.exec(
                    select(ClientToolSubscription)
                    .where(ClientToolSubscription.company_id == company_id,
                           ClientToolSubscription.client_id  == client_id,
                           ClientToolSubscription.tool_code  == "financeiro_gerencial")
                ).first()
                if not sub_leg:
                    sub_leg = ClientToolSubscription(
                        company_id=company_id, client_id=client_id,
                        tool_code="financeiro_gerencial",
                    )
                sub_leg.is_active             = True
                sub_leg.status                = "active"
                sub_leg.monthly_price_credits = 0   # créditos já debitados pelo novo sistema
                sub_leg.trial_ends_at         = None
                sub_leg.updated_at            = _dtCF.now(_tzCF.utc)
                session.add(sub_leg)
                session.commit()
            except Exception as _e_leg:
                print(f"[creditos_features] sync legado financeiro: {_e_leg}")

        return True, f"Feature '{feature_codigo}' ativada com sucesso."

    except Exception as _e_at:
        session.rollback()
        print(f"[creditos_features] ativar: {_e_at}")
        return False, f"Erro interno: {_e_at}"

def _feature_desativar(session, company_id: int, client_id: int,
                       feature_codigo: str, user_id: _OptCF[int] = None) -> bool:
    """Desativa uma feature (sem reembolso de créditos)."""
    try:
        af = session.exec(
            select(AssinaturaFeature)
            .where(AssinaturaFeature.company_id     == company_id,
                   AssinaturaFeature.client_id      == client_id,
                   AssinaturaFeature.feature_codigo == feature_codigo,
                   AssinaturaFeature.user_id        == user_id,
                   AssinaturaFeature.ativo          == True)
        ).first()
        if not af:
            return False
        af.ativo = False
        session.add(af)
        session.commit()

        # Sincroniza sistema legado na desativação
        if feature_codigo == "financeiro_gerencial_mensal":
            try:
                sub_leg = session.exec(
                    select(ClientToolSubscription)
                    .where(ClientToolSubscription.company_id == company_id,
                           ClientToolSubscription.client_id  == client_id,
                           ClientToolSubscription.tool_code  == "financeiro_gerencial")
                ).first()
                if sub_leg:
                    sub_leg.is_active  = False
                    sub_leg.status     = "blocked"
                    sub_leg.updated_at = _dtCF.now(_tzCF.utc)
                    session.add(sub_leg)
                    session.commit()
            except Exception:
                pass

        return True
    except Exception as _e_da:
        session.rollback()
        print(f"[creditos_features] desativar: {_e_da}")
        return False

def _features_ativas(session, company_id: int, client_id: int) -> list:
    """Retorna lista de feature_codigo ativos para o cliente."""
    try:
        afs = session.exec(
            select(AssinaturaFeature)
            .where(AssinaturaFeature.company_id == company_id,
                   AssinaturaFeature.client_id  == client_id,
                   AssinaturaFeature.ativo       == True)
        ).all()
        return [af.feature_codigo for af in afs]
    except Exception:
        return []

# ── Compatibilidade com módulos antigos ───────────────────────────────────────

def _tool_assinatura_ativa(session, company_id: int, tool_code: str,
                           client_id: int = 0) -> bool:
    if not client_id:
        return False
    return _feature_ativa(session, company_id, client_id, tool_code)

def _augur_assinatura_ativa(session, company_id: int, user_id: int,
                             client_id: int = 0) -> bool:
    if not client_id:
        return False
    return _feature_ativa(session, company_id, client_id, "augur_mensal", user_id=user_id)

# ── Renovação mensal (OVERRIDE de _renovar_plano_cliente) ─────────────────────
# Esta função substitui a versão de ui_monetizacao.py.
# Nova semântica: RESET (créditos velhos expiram) + débito automático de features.

def _renovar_plano_cliente(session, company_id: int, client_id: int) -> bool:
    """
    Renovação mensal do plano:
      1. Créditos do cliente são ZERADOS e resetados para o teto do plano
         (créditos não usados expiram — não acumulam)
      2. Features ativas são debitadas automaticamente
      3. Features sem créditos suficientes são desativadas
      4. proximo_ciclo avança 30 dias
    """
    cp, plano = _cf_plano_ativo(session, company_id, client_id)
    if not cp or not plano:
        return False

    teto_cents = plano.creditos_mes * 100

    # 1. RESET: define saldo = teto (créditos velhos expiram)
    try:
        wallet = _cf_wallet(session, company_id, client_id)
        saldo_anterior = wallet.balance_cents
        wallet.balance_cents = teto_cents
        wallet.updated_at = _dtCF.now(_tzCF.utc)
        session.add(wallet)
        session.add(CreditLedger(
            company_id=company_id,
            client_id=client_id,
            kind="TOPUP_CONFIRMED",
            amount_cents=teto_cents,
            ref_type="plano_reset",
            ref_id=str(cp.plano_id),
            note=(f"Reset mensal → {plano.creditos_mes} cr "
                  f"(saldo anterior: {saldo_anterior // 100} cr expirou)"),
        ))
    except Exception as _e_reset:
        print(f"[creditos_features] reset wallet: {_e_reset}")
        return False

    # 2. DÉBITO automático de features ativas
    try:
        features_ativas = session.exec(
            select(AssinaturaFeature)
            .where(AssinaturaFeature.company_id == company_id,
                   AssinaturaFeature.client_id  == client_id,
                   AssinaturaFeature.ativo       == True)
        ).all()

        for af in features_ativas:
            custo_cents = af.creditos_mes * 100
            if custo_cents <= 0:
                # feature gratuita — apenas atualiza renovação
                af.renovacao_em = (_dtCF.now(_tzCF.utc) + _tdCF(days=30)).strftime("%Y-%m-%d")
                session.add(af)
                continue

            if wallet.balance_cents >= custo_cents:
                wallet.balance_cents -= custo_cents
                wallet.updated_at = _dtCF.now(_tzCF.utc)
                session.add(wallet)
                session.add(CreditLedger(
                    company_id=company_id,
                    client_id=client_id,
                    kind="FEATURE_RENEWAL",
                    amount_cents=-custo_cents,
                    ref_type="feature",
                    ref_id=af.feature_codigo,
                    note=f"Renovação automática: {af.feature_codigo} ({af.creditos_mes} cr/mês)",
                ))
                af.renovacao_em = (_dtCF.now(_tzCF.utc) + _tdCF(days=30)).strftime("%Y-%m-%d")
                session.add(af)
            else:
                # Sem créditos → desativa feature
                af.ativo = False
                session.add(af)
                session.add(CreditLedger(
                    company_id=company_id,
                    client_id=client_id,
                    kind="FEATURE_EXPIRED",
                    amount_cents=0,
                    ref_type="feature",
                    ref_id=af.feature_codigo,
                    note=f"Feature expirada: créditos insuficientes para {af.feature_codigo}",
                ))
                print(f"[creditos_features] Feature {af.feature_codigo} expirada (client {client_id})")
    except Exception as _e_feat:
        print(f"[creditos_features] débito features: {_e_feat}")

    # 3. Avança proximo_ciclo
    try:
        cp.proximo_ciclo = (_dtCF.now(_tzCF.utc) + _tdCF(days=30)).strftime("%Y-%m-%d")
        session.add(cp)
        session.commit()
    except Exception as _e_pc:
        print(f"[creditos_features] proximo_ciclo: {_e_pc}")
        session.rollback()
        return False

    print(f"[creditos_features] Renovação OK client {client_id}: {plano.creditos_mes} cr, "
          f"saldo após features: {wallet.balance_cents // 100} cr")
    return True

# ── Scheduler: verifica renovações diariamente ────────────────────────────────

def _cf_verificar_renovacoes():
    """Chamada diariamente: renova clientes com proximo_ciclo = hoje."""
    hoje = _cf_hoje()
    try:
        with Session(engine) as _s:
            vencidos = _s.exec(
                select(ClientePlano)
                .where(ClientePlano.ativo == True,
                       ClientePlano.proximo_ciclo == hoje)
            ).all()
            for cp in vencidos:
                try:
                    _renovar_plano_cliente(_s, cp.company_id, cp.client_id)
                except Exception as _e_rv:
                    print(f"[creditos_features] Erro renovar client {cp.client_id}: {_e_rv}")
    except Exception as _e_sched:
        print(f"[creditos_features] scheduler: {_e_sched}")

def _cf_scheduler_loop():
    import time as _tm
    _ultima_execucao = ""
    while True:
        _tm.sleep(60)
        _hora_utc = _dtCF.now(_tzCF.utc).strftime("%Y-%m-%d %H:00")
        if _hora_utc != _ultima_execucao and _dtCF.now(_tzCF.utc).hour == 6:
            # 06:00 UTC = 03:00 BRT — sem impacto para usuários
            _ultima_execucao = _hora_utc
            try:
                _cf_verificar_renovacoes()
            except Exception as _e_sl:
                print(f"[creditos_features] loop: {_e_sl}")

_thCF.Thread(target=_cf_scheduler_loop, daemon=True, name="cf_renovacao").start()

# ── Catálogo de features ───────────────────────────────────────────────────────
# Mapeamento de feature_codigo → metadados para exibição na UI

_CF_CATALOGO = {
    "financeiro_gerencial_mensal": {
        "nome": "Financeiro Gerencial",
        "descricao": "Lançamentos, DRE, fluxo de caixa e conciliação bancária do cliente.",
        "nivel": "empresa",   # empresa = todos os usuários; usuario = só quem ativou
        "url": "/ferramentas/financeiro",
        "icone": "💰",
    },
    "obras_horas_mensal": {
        "nome": "Gestão de Obras",
        "descricao": "Cronograma físico-financeiro, fases, etapas, Gantt e EVM.",
        "nivel": "empresa",
        "url": "/ferramentas/obras",
        "icone": "🏗️",
    },
    "viabilidade_analise": {
        "nome": "Viabilidade Imobiliária",
        "descricao": "VGV, margem, TIR e fluxo de caixa por empreendimento. Pago por estudo.",
        "nivel": "empresa",
        "url": "/ferramentas/viabilidade",
        "icone": "📊",
        # tipo lido dinamicamente do ProdutoPreco para refletir config do admin
    },
    "augur_mensal": {
        "nome": "Augur — IA Consultiva",
        "descricao": "Consultor de IA com contexto completo do cliente. Acesso individual por usuário.",
        "nivel": "usuario",
        "url": "/",
        "icone": "🤖",
    },
    "mapa_unidades_mensal": {
        "nome": "Mapa de Unidades",
        "descricao": "Gestão de empreendimentos e unidades imobiliárias com status de venda.",
        "nivel": "empresa",
        "url": "/ferramentas/mapa-unidades",
        "icone": "🗺️",
    },
    "fluxo_caixa_mensal": {
        "nome": "Fluxo de Caixa",
        "descricao": "Importe lançamentos via Excel, acompanhe entradas e saídas por dia, semana ou mês e visualize projeções com saldo inicial e limites de alerta.",
        "nivel": "empresa",
        "url": "/ferramentas/fluxo-caixa",
        "icone": "💵",
    },
    "producao_kanban": {
        "nome": "Controle de Produção",
        "descricao": "Ordens de Produção (OP), Kanban personalizado com etapas e roteiro, materiais por OP e PCP — Planejamento × Controle da Produção.",
        "nivel": "empresa",
        "url": "/ferramentas/producao",
        "icone": "🏭",
    },
}

# ── API: status de features ────────────────────────────────────────────────────

@app.get("/api/features/status")
@require_login
async def api_features_status(
    request: Request,
    client_id: _OptCF[int] = None,
    session: Session = Depends(get_session),
):
    ctx = get_tenant_context(request, session)
    if not ctx:
        return JSONResponse({"error": "not authenticated"}, status_code=401)

    # Resolve client_id: parâmetro > sessão > primeiro cliente da empresa
    cid = client_id
    if not cid:
        cid = request.session.get("current_client_id")
    if not cid:
        try:
            primeiro = session.exec(
                select(Client)
                .where(Client.company_id == ctx.company.id)
                .limit(1)
            ).first()
            if primeiro:
                cid = primeiro.id
        except Exception:
            pass
    if not cid:
        return JSONResponse({"saldo": 0, "features": {}, "proximo_ciclo": None})

    saldo = _cf_saldo_creditos(session, ctx.company.id, cid)
    cp, plano = _cf_plano_ativo(session, ctx.company.id, cid)

    resultado = {
        "saldo":          round(saldo, 2),
        "plano_nome":     plano.nome if plano else None,
        "creditos_mes":   plano.creditos_mes if plano else 0,
        "proximo_ciclo":  cp.proximo_ciclo if cp else None,
        "features":       {},
    }

    for codigo, meta in _CF_CATALOGO.items():
        uid = ctx.user.id if meta.get("nivel") == "usuario" else None
        custo = _cf_preco(session, ctx.company.id, codigo)
        ativo = _feature_ativa(session, ctx.company.id, cid, codigo, user_id=uid)
        # Lê modelo do banco (admin pode alterar entre uso/assinatura/gratuito)
        _tipo_catalog = meta.get("tipo", "assinatura")
        try:
            _pp = session.exec(
                select(ProdutoPreco)
                .where(ProdutoPreco.company_id == ctx.company.id,
                       ProdutoPreco.codigo == codigo,
                       ProdutoPreco.ativo == True)
            ).first()
            _tipo_db = _pp.modelo if _pp and _pp.modelo else _tipo_catalog
        except Exception:
            _tipo_db = _tipo_catalog
        resultado["features"][codigo] = {
            "nome":        meta["nome"],
            "descricao":   meta["descricao"],
            "nivel":       meta["nivel"],
            "icone":       meta["icone"],
            "url":         meta["url"],
            "tipo":        _tipo_db,
            "custo":       custo,
            "ativo":       ativo,
        }

    return JSONResponse(resultado)

# ── API: ativar feature ────────────────────────────────────────────────────────

@app.post("/api/features/{feature_codigo}/ativar")
@require_login
async def api_feature_ativar(
    feature_codigo: str,
    request: Request,
    session: Session = Depends(get_session),
):
    ctx = get_tenant_context(request, session)
    if not ctx:
        return JSONResponse({"ok": False, "msg": "Não autenticado"}, status_code=401)

    form = await request.form()
    cid = int(form.get("client_id") or request.session.get("current_client_id") or 0)
    if not cid:
        return JSONResponse({"ok": False, "msg": "client_id não informado"}, status_code=400)

    meta = _CF_CATALOGO.get(feature_codigo)
    if not meta:
        return JSONResponse({"ok": False, "msg": "Feature desconhecida"}, status_code=404)

    uid = ctx.user.id if meta.get("nivel") == "usuario" else None
    ok, msg = _feature_ativar(session, ctx.company.id, cid, feature_codigo, user_id=uid)
    return JSONResponse({"ok": ok, "msg": msg})

# ── API: desativar feature ─────────────────────────────────────────────────────

@app.post("/api/features/{feature_codigo}/desativar")
@require_login
async def api_feature_desativar(
    feature_codigo: str,
    request: Request,
    session: Session = Depends(get_session),
):
    ctx = get_tenant_context(request, session)
    if not ctx:
        return JSONResponse({"ok": False, "msg": "Não autenticado"}, status_code=401)

    form = await request.form()
    cid = int(form.get("client_id") or request.session.get("current_client_id") or 0)
    if not cid:
        return JSONResponse({"ok": False, "msg": "client_id não informado"}, status_code=400)

    meta = _CF_CATALOGO.get(feature_codigo)
    uid = ctx.user.id if (meta and meta.get("nivel") == "usuario") else None
    ok = _feature_desativar(session, ctx.company.id, cid, feature_codigo, user_id=uid)
    return JSONResponse({"ok": ok, "msg": "Desativada." if ok else "Feature não encontrada."})

# ── Nova página /ferramentas ───────────────────────────────────────────────────

_CF_FERRAMENTAS_HTML = r"""
{% extends "base.html" %}
{% block content %}

<div class="card p-4 mb-3">
  <div class="d-flex justify-content-between align-items-center flex-wrap gap-3">
    <div>
      <h4 class="mb-1">Ferramentas</h4>
      <div class="muted">Ative as ferramentas que você quer usar. Os créditos são descontados automaticamente do seu plano.</div>
    </div>
    {% if current_client %}
      <div class="text-end">
        <div class="muted small">Cliente ativo</div>
        <div class="fw-semibold">{{ current_client.name }}</div>
      </div>
    {% endif %}
  </div>
</div>

{% if not current_client %}
  <div class="alert alert-warning">Selecione um cliente para acessar as ferramentas.</div>
{% else %}

<!-- Carteira do cliente -->
<div class="row g-3 mb-4" id="walletRow">
  <div class="col-6 col-md-3">
    <div class="card p-3 h-100 text-center">
      <div class="muted small">Saldo disponível</div>
      <div class="fw-bold fs-4 text-success" id="wSaldo">—</div>
      <div class="muted small">créditos</div>
    </div>
  </div>
  <div class="col-6 col-md-3">
    <div class="card p-3 h-100 text-center">
      <div class="muted small">Plano</div>
      <div class="fw-semibold" id="wPlano">—</div>
      <div class="muted small" id="wCredMes">—</div>
    </div>
  </div>
  <div class="col-6 col-md-3">
    <div class="card p-3 h-100 text-center">
      <div class="muted small">Próxima renovação</div>
      <div class="fw-semibold" id="wRenovacao">—</div>
      <div class="muted small">créditos resetam</div>
    </div>
  </div>
  <div class="col-6 col-md-3">
    <div class="card p-3 h-100 text-center">
      <div class="muted small">Créditos após features</div>
      <div class="fw-bold" id="wAposFeatures">—</div>
      <div class="muted small">disponíveis para consultas</div>
    </div>
  </div>
</div>

<!-- Cards de features -->
<div class="row g-3 mb-4" id="featuresRow">
  <div class="col-12 text-center py-5 text-muted" id="featuresLoading">
    Carregando ferramentas…
  </div>
</div>

{% endif %}

<script>
(function(){
  var CLIENT_ID = "{{ current_client.id if current_client else '' }}";
  if (!CLIENT_ID) return;

  var ICONS = {
    "financeiro_gerencial_mensal": "💰",
    "obras_horas_mensal":          "🏗️",
    "viabilidade_analise":         "📊",
    "augur_mensal":                "🤖",
    "mapa_unidades_mensal":        "🗺️",
  };

  async function loadFeatures() {
    try {
      var r = await fetch('/api/features/status?client_id=' + CLIENT_ID);
      var d = await r.json();

      // Wallet cards
      document.getElementById('wSaldo').textContent     = (d.saldo || 0).toFixed(0);
      document.getElementById('wPlano').textContent     = d.plano_nome || '—';
      document.getElementById('wCredMes').textContent   = d.creditos_mes ? d.creditos_mes + ' cr/mês' : '—';
      document.getElementById('wRenovacao').textContent = d.proximo_ciclo || '—';

      // Calcula créditos após features ativas
      var totalDeducao = 0;
      Object.values(d.features || {}).forEach(function(f) {
        if (f.ativo && f.tipo !== 'uso') totalDeducao += (f.custo || 0);
      });
      var apos = (d.saldo || 0) - totalDeducao;  // saldo já descontado
      document.getElementById('wAposFeatures').textContent = Math.max(0, d.saldo || 0).toFixed(0);

      // Monta cards
      var container = document.getElementById('featuresRow');
      container.innerHTML = '';

      var features = d.features || {};
      var codigos = Object.keys(features);
      if (!codigos.length) {
        container.innerHTML = '<div class="col-12"><div class="alert alert-info">Nenhuma ferramenta disponível.</div></div>';
        return;
      }

      codigos.forEach(function(codigo) {
        var f = features[codigo];
        var ativo = f.ativo;
        var custo = f.custo || 0;
        var isPorUso = f.tipo === 'uso';
        var isEmpresa = f.nivel === 'empresa';

        var badgeClass = ativo ? 'bg-success' : (isPorUso ? 'bg-info text-dark' : 'bg-secondary');
        var badgeText  = ativo ? '✓ Ativa' : (isPorUso ? 'Por uso' : 'Inativa');

        var custoHtml = isPorUso
          ? '<span class="text-muted">' + custo + ' cr/estudo</span>'
          : (custo > 0
              ? '<span class="' + (ativo ? 'text-success fw-semibold' : 'text-muted') + '">' + custo + ' cr/mês</span>'
              : '<span class="text-success fw-semibold">Gratuito</span>');

        var nivelHtml = isEmpresa
          ? '<span class="badge bg-light text-dark border" style="font-size:.72rem;">👥 Empresa toda</span>'
          : '<span class="badge bg-light text-dark border" style="font-size:.72rem;">👤 Por usuário</span>';

        var btnHtml = '';
        if (isPorUso) {
          btnHtml = '<a href="' + f.url + '" class="btn btn-outline-primary btn-sm">Abrir</a>';
        } else if (ativo) {
          btnHtml = '<a href="' + f.url + '" class="btn btn-success btn-sm me-2">Abrir</a>'
                  + '<button class="btn btn-outline-danger btn-sm" onclick="desativar(\'' + codigo + '\')" id="btn_' + codigo + '">Desativar</button>';
        } else {
          btnHtml = '<button class="btn btn-primary btn-sm" onclick="ativar(\'' + codigo + '\')" id="btn_' + codigo + '">'
                  + (custo > 0 ? 'Ativar — ' + custo + ' cr/mês' : 'Ativar gratuitamente') + '</button>';
        }

        var cardHtml =
          '<div class="col-lg-6">' +
          '  <div class="card p-4 h-100" id="card_' + codigo + '">' +
          '    <div class="d-flex justify-content-between align-items-start gap-2 mb-2">' +
          '      <div class="d-flex align-items-center gap-2">' +
          '        <span style="font-size:1.5rem;">' + (f.icone || '🔧') + '</span>' +
          '        <div>' +
          '          <h5 class="mb-0">' + f.nome + '</h5>' +
          '          ' + nivelHtml +
          '        </div>' +
          '      </div>' +
          '      <span class="badge ' + badgeClass + ' align-self-start">' + badgeText + '</span>' +
          '    </div>' +
          '    <p class="muted small mb-3">' + f.descricao + '</p>' +
          '    <div class="d-flex align-items-center justify-content-between flex-wrap gap-2">' +
          '      <div class="muted small">Custo: ' + custoHtml + '</div>' +
          '      <div class="d-flex gap-2">' + btnHtml + '</div>' +
          '    </div>' +
          '  </div>' +
          '</div>';

        container.insertAdjacentHTML('beforeend', cardHtml);
      });

      document.getElementById('featuresLoading') && document.getElementById('featuresLoading').remove();

    } catch(e) {
      document.getElementById('featuresLoading').textContent = 'Erro ao carregar ferramentas.';
      console.error(e);
    }
  }

  window.ativar = async function(codigo) {
    var btn = document.getElementById('btn_' + codigo);
    if (btn) { btn.disabled = true; btn.textContent = '...'; }
    try {
      var fd = new FormData(); fd.append('client_id', CLIENT_ID);
      var r = await fetch('/api/features/' + codigo + '/ativar', {method:'POST', body:fd});
      var d = await r.json();
      if (d.ok) {
        loadFeatures();
      } else {
        alert(d.msg || 'Erro ao ativar.');
        if (btn) { btn.disabled = false; btn.textContent = 'Ativar'; }
      }
    } catch(e) {
      if (btn) { btn.disabled = false; btn.textContent = 'Ativar'; }
    }
  };

  window.desativar = async function(codigo) {
    if (!confirm('Desativar esta feature? O acesso será removido imediatamente sem reembolso.')) return;
    var btn = document.getElementById('btn_' + codigo);
    if (btn) { btn.disabled = true; btn.textContent = '...'; }
    try {
      var fd = new FormData(); fd.append('client_id', CLIENT_ID);
      var r = await fetch('/api/features/' + codigo + '/desativar', {method:'POST', body:fd});
      var d = await r.json();
      loadFeatures();
    } catch(e) {
      if (btn) { btn.disabled = false; btn.textContent = 'Desativar'; }
    }
  };

  loadFeatures();
})();
</script>
{% endblock %}
"""

# Registra nova versão do template
TEMPLATES["ferramentas.html"] = _CF_FERRAMENTAS_HTML
if hasattr(templates_env, "loader") and hasattr(templates_env.loader, "mapping"):
    templates_env.loader.mapping["ferramentas.html"] = _CF_FERRAMENTAS_HTML

# ── Nova rota GET /ferramentas (substitui a original) ─────────────────────────
# Remove a rota antiga e registra a nova

_cf_rotas_remover = [
    r for r in app.router.routes
    if getattr(r, "path", None) == "/ferramentas" and "GET" in getattr(r, "methods", set())
]
for _r_rem in _cf_rotas_remover:
    app.router.routes.remove(_r_rem)

@app.get("/ferramentas", response_class=HTMLResponse)
@require_login
async def ferramentas_page_cf(request: Request, session: Session = Depends(get_session)):
    ctx = get_tenant_context(request, session)
    if not ctx:
        request.session.clear()
        return RedirectResponse("/login", status_code=303)

    current_client = _client_current_client(request, session, ctx)

    return render(
        "ferramentas.html",
        request=request,
        context={
            "title": "Ferramentas",
            "current_user": ctx.user,
            "current_company": ctx.company,
            "role": ctx.membership.role,
            "current_client": current_client,
        },
    )

# ── Remove rotas antigas do ui_tool_assinaturas (se existirem) ────────────────
for _r_old in list(app.router.routes):
    _p = getattr(_r_old, "path", "")
    if _p in ("/api/tools/status", "/stripe/webhook/tools") or \
       (_p.startswith("/ferramentas/") and _p.endswith("/assinar")) or \
       (_p.startswith("/ferramentas/") and _p.endswith("/cancelar")):
        try:
            app.router.routes.remove(_r_old)
        except Exception:
            pass

# ── Widget de créditos no dashboard ───────────────────────────────────────────
# Injeta um banner de saldo + plano no topo do dashboard, logo após o hero

_CF_CREDITS_WIDGET = """
{%- if wallet_saldo_total is defined %}
<div class="d-flex align-items-center gap-3 flex-wrap px-1 mb-3" style="font-size:.88rem;">
  <a href="/creditos" class="d-flex align-items-center gap-2 text-decoration-none"
     style="background:var(--mc-primary-soft,#e8f0fe);border-radius:8px;padding:.45rem .85rem;">
    <span style="font-size:1.1rem;">💳</span>
    <span>
      <span class="fw-semibold" style="color:var(--mc-primary,#1a56db)">{{ wallet_saldo_total }} créditos</span>
      <span class="text-muted"> disponíveis</span>
      {%- if plano_nome %}
        &nbsp;·&nbsp;<span class="text-muted">Plano <strong>{{ plano_nome }}</strong></span>
      {%- endif %}
    </span>
  </a>
  <a href="/creditos" class="btn btn-sm btn-outline-primary" style="font-size:.8rem;">Recarregar</a>
</div>
{%- endif %}
"""

try:
    _dash_tpl = TEMPLATES.get("dashboard.html", "")
    if _dash_tpl and "wallet_saldo_total" not in _dash_tpl:
        # Injeta logo após {% block content %} ou após o primeiro <div
        _anchor = "{% block content %}"
        if _anchor in _dash_tpl:
            TEMPLATES["dashboard.html"] = _dash_tpl.replace(
                _anchor, _anchor + "\n" + _CF_CREDITS_WIDGET, 1
            )
            if hasattr(templates_env, "loader") and hasattr(templates_env.loader, "mapping"):
                templates_env.loader.mapping["dashboard.html"] = TEMPLATES["dashboard.html"]
except Exception as _e_cw:
    print(f"[creditos_features] wallet widget: {_e_cw}")

print("[creditos_features] ✅ Sistema de ativação por créditos carregado")
print("[creditos_features]    Rotas: GET /api/features/status")
print("[creditos_features]           POST /api/features/{codigo}/ativar")
print("[creditos_features]           POST /api/features/{codigo}/desativar")
print("[creditos_features]    _renovar_plano_cliente() override: RESET + débito automático")

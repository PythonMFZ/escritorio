# ============================================================================
# ui_predio_custos.py — custo da IA do prédio: medição, modelo e esforço por agente
# ============================================================================
# Exec'd no namespace do app.py, DEPOIS de todos os módulos do prédio.
#
# - Cada chamada à API (agente, Recepção, extração do WhatsApp) grava tokens e custo
#   estimado em PredioUso (preços oficiais da Anthropic, em US$ por milhão de tokens).
# - Cada agente roda num modelo e esforço próprios: agentes de rotina no Sonnet, a
#   classificação no Haiku, os analíticos no Opus. O admin troca em /predio/custos.
# - Se um modelo mais barato recusar um pedido (erro 400), _pr_api refaz no Opus.
#
# ROTAS (admin)
#   GET  /predio/custos              — custo do mês por agente, modelo e chamado
#   POST /predio/custos/modelos      — modelo e esforço de cada agente
# ============================================================================

import os as _os_cu

# US$ por milhão de tokens: (entrada, escrita de cache 5 min, leitura de cache, saída) — tabela oficial, nov/2026
_CU_PRECOS = {
    "claude-opus-5-5": (4.0, 5.0, 0.20, 20.0),
    "claude-sonnet-5-5": (2.0, 2.5, 0.10, 10.0),
    "claude-haiku-5-5": (0.10, 0.125, 0.01, 0.50),
}
_CU_HAIKU_LONGO = (0.50, 0.625, 0.05, 2.50)  # Haiku com prompt acima de 100 mil tokens
_CU_BUSCA_WEB = 10.0 / 1000                  # US$ por busca na web (a leitura de páginas só cobra os tokens)
_CU_MODELOS = {"opus": "claude-opus-5-5", "sonnet": "claude-sonnet-5-5", "haiku": "claude-haiku-5-5"}
_CU_NOMES = {"opus": "Opus 5.5", "sonnet": "Sonnet 5.5", "haiku": "Haiku 5.5"}
_CU_ESFORCOS = {"high": "Alto", "medium": "Médio", "low": "Baixo"}


def _cu_dolar() -> float:
    try:
        return float(_os_cu.environ.get("PREDIO_DOLAR", "5.50").replace(",", "."))
    except ValueError:
        return 5.50


class PredioUso(_SM_pr, table=True):
    __tablename__ = "predio_uso"
    __table_args__ = {"extend_existing": True}
    id: _Opt_pr[int] = _F_pr(default=None, primary_key=True)
    company_id: _Opt_pr[int] = _F_pr(default=None, index=True)
    chamado_id: _Opt_pr[int] = _F_pr(default=None, index=True)
    agente_key: str = _F_pr(default="", index=True)
    tipo: str = _F_pr(default="agente")  # agente | recepcao | extracao
    modelo: str = _F_pr(default="")
    input_tokens: int = _F_pr(default=0)
    output_tokens: int = _F_pr(default=0)
    cache_leitura: int = _F_pr(default=0)
    cache_escrita: int = _F_pr(default=0)
    buscas_web: int = _F_pr(default=0)
    custo_usd: float = _F_pr(default=0.0)
    criado_em: _dt_pr = _F_pr(default_factory=lambda: _dt_pr.utcnow(), index=True)


try:
    _SM_pr.metadata.create_all(engine, tables=[PredioUso.__table__], checkfirst=True)
except Exception as _e_cu_tab:
    print(f"[predio_custos] create_all: {_e_cu_tab}")


# ── Perfil (modelo e esforço) de cada agente ─────────────────────────────────

_CU_PADRAO_ROTINA = ("sonnet", "medium")
_CU_PADRAO = {
    # classificação e extração: Haiku
    "recepcionista": ("haiku", "low"), "extracao": ("haiku", "low"),
    # rotina: Sonnet
    **{k: ("sonnet", "medium") for k in (
        "atendimento", "secretario_reunioes", "gestor_carteira", "cobranca", "contas_pagar", "faturamento", "sistemas",
        "conhecimento", "agencia_redes", "sucesso_cliente", "data_room", "capacidade", "editor_site")},
    **{k: ("sonnet", "high") for k in ("inteligencia_mercado", "conteudo", "prospeccao")},
    # analíticos e de risco: Opus com esforço alto
    **{k: ("opus", "high") for k in (
        "valuation", "analista_financeiro", "estruturador", "analista_risco", "contratos", "propostas", "estrategia",
        "compliance")},
}
_CU_PADRAO_DEMAIS = ("opus", "medium")  # o restante (Chief of Staff, Controller, Relatório Mensal...)
_CU_CFG: dict = {}                       # company_id -> (lido_em, overrides)


def _cu_padrao(agente_key: str) -> tuple:
    if agente_key in _CU_PADRAO:
        return _CU_PADRAO[agente_key]
    if agente_key.startswith("ag_"):
        return _CU_PADRAO_ROTINA
    return _CU_PADRAO_DEMAIS


def _cu_overrides(company_id) -> dict:
    if not company_id:
        return {}
    item = _CU_CFG.get(company_id)
    if item and _time_pr.time() - item[0] < 15:
        return item[1]
    try:
        with _Sess_pr(engine) as s:
            cfg = s.exec(_sel_pr(PredioConfig.modelos_json).where(PredioConfig.company_id == company_id)).first()
        dados = _json_pr.loads(cfg or "{}")
        dados = dados if isinstance(dados, dict) else {}
    except Exception:
        dados = {}
    _CU_CFG[company_id] = (_time_pr.time(), dados)
    return dados


def _cu_perfil(agente_key: str, company_id=None) -> tuple:
    modelo, esforco = _cu_padrao(agente_key)
    o = _cu_overrides(company_id).get(agente_key) or {}
    if o.get("modelo") in _CU_MODELOS:
        modelo = o["modelo"]
    if o.get("esforco") in _CU_ESFORCOS:
        esforco = o["esforco"]
    return _CU_MODELOS[modelo], esforco


# ── Medição ──────────────────────────────────────────────────────────────────

def _cu_custo(modelo: str, inp: int, out: int, cr: int, cw: int, buscas: int) -> float:
    precos = _CU_PRECOS.get(modelo) or _CU_PRECOS["claude-opus-5-5"]
    if modelo == "claude-haiku-5-5" and inp + cr + cw > 100_000:
        precos = _CU_HAIKU_LONGO
    pe, pw, pr, ps = precos
    return (inp * pe + cw * pw + cr * pr + out * ps) / 1_000_000 + buscas * _CU_BUSCA_WEB


def _cu_registrar_uso(company_id, chamado_id, agente_key, tipo, modelo, resp) -> None:
    u = getattr(resp, "usage", None)
    if u is None:
        return
    g = lambda k: int(getattr(u, k, 0) or 0)
    stu = getattr(u, "server_tool_use", None)
    buscas = int(getattr(stu, "web_search_requests", 0) or 0) if stu is not None else 0
    modelo = str(modelo or "")
    inp, out, cr, cw = g("input_tokens"), g("output_tokens"), g("cache_read_input_tokens"), g("cache_creation_input_tokens")
    with _Sess_pr(engine) as s:
        s.add(PredioUso(company_id=company_id, chamado_id=chamado_id, agente_key=agente_key or "", tipo=tipo, modelo=modelo,
                        input_tokens=inp, output_tokens=out, cache_leitura=cr, cache_escrita=cw, buscas_web=buscas,
                        custo_usd=round(_cu_custo(modelo, inp, out, cr, cw, buscas), 6)))
        s.commit()


_pr_perfil = _cu_perfil
_pr_registrar_uso = _cu_registrar_uso


# ── Consultas ────────────────────────────────────────────────────────────────

def _cu_mes(valor: str):
    hoje = _pr_agora_brt().date()
    try:
        ano, mes = int(valor[:4]), int(valor[5:7])
        _dt_pr(ano, mes, 1)
    except (TypeError, ValueError):
        ano, mes = hoje.year, hoje.month
    ini = _dt_pr(ano, mes, 1) + _td_pr(hours=3)  # meia-noite de Brasília em UTC
    fim = _dt_pr(ano + (mes == 12), mes % 12 + 1, 1) + _td_pr(hours=3)
    return f"{ano:04d}-{mes:02d}", ini, fim


def _cu_resumo(s, cid, mes: str) -> dict:
    chave, ini, fim = _cu_mes(mes)
    U = PredioUso
    base = (U.company_id == cid, U.criado_em >= ini, U.criado_em < fim)
    soma = lambda: (_func_pr.count(U.id), _func_pr.coalesce(_func_pr.sum(U.custo_usd), 0), _func_pr.coalesce(_func_pr.sum(U.input_tokens), 0),
                    _func_pr.coalesce(_func_pr.sum(U.output_tokens), 0), _func_pr.coalesce(_func_pr.sum(U.cache_leitura), 0),
                    _func_pr.coalesce(_func_pr.sum(U.cache_escrita), 0), _func_pr.coalesce(_func_pr.sum(U.buscas_web), 0))
    tot = s.exec(_sel_pr(*soma()).where(*base)).one()
    por_agente = s.exec(_sel_pr(U.agente_key, _func_pr.count(_func_pr.distinct(U.chamado_id)), *soma()).where(*base)
                        .group_by(U.agente_key).order_by(_func_pr.sum(U.custo_usd).desc())).all()
    por_modelo = s.exec(_sel_pr(U.modelo, *soma()).where(*base).group_by(U.modelo).order_by(_func_pr.sum(U.custo_usd).desc())).all()
    top = s.exec(_sel_pr(U.chamado_id, _func_pr.sum(U.custo_usd)).where(*base, U.chamado_id != None)  # noqa: E711
                 .group_by(U.chamado_id).order_by(_func_pr.sum(U.custo_usd).desc()).limit(10)).all()
    titulos = {c.id: (c.titulo or c.pedido[:70], c.agente_key, c.tipo) for c in s.exec(
        _sel_pr(PredioChamado).options(*_PR_LEVE).where(PredioChamado.id.in_([t[0] for t in top] or [0]))).all()}
    dolar = _cu_dolar()
    nome = lambda k: _PREDIO_AGENTES.get(k, {}).get("nome") or {"recepcionista": "Recepção", "atendimento": "Atendimento"}.get(k, k or "—")

    def linha(r, off=0):
        return {"chamadas": r[off], "custo_usd": float(r[off + 1] or 0), "custo_brl": float(r[off + 1] or 0) * dolar,
                "entrada": int(r[off + 2] or 0), "saida": int(r[off + 3] or 0), "cache_leitura": int(r[off + 4] or 0),
                "cache_escrita": int(r[off + 5] or 0), "buscas": int(r[off + 6] or 0)}
    total = linha(tot)
    total_usd = total["custo_usd"] or 1e-9
    agentes = [{"key": r[0], "nome": nome(r[0]), "chamados": r[1], **linha(r, 2)} for r in por_agente]
    for a in agentes:
        a["pct"] = round(a["custo_usd"] / total_usd * 100, 1)
    ent = total["entrada"] + total["cache_leitura"] + total["cache_escrita"]
    return {
        "mes": chave, "dolar": dolar, "total": total, "agentes": agentes,
        "modelos": [{"modelo": r[0], **linha(r, 1)} for r in por_modelo],
        "cache_pct": round(total["cache_leitura"] / ent * 100, 1) if ent else 0.0,
        "caros": [{"id": t[0], "custo_usd": float(t[1] or 0), "custo_brl": float(t[1] or 0) * dolar,
                   "titulo": titulos.get(t[0], ("", "", ""))[0], "agente": nome(titulos.get(t[0], ("", "", ""))[1]),
                   "reuniao": titulos.get(t[0], ("", "", ""))[2] == "reuniao"} for t in top],
    }


def _cu_resumo_home(company_id: int) -> dict:
    with _Sess_pr(engine) as s:
        r = _cu_resumo(s, company_id, "")
    return {"usd": r["total"]["custo_usd"], "brl": r["total"]["custo_brl"], "chamadas": r["total"]["chamadas"],
            "top": r["agentes"][0]["nome"] if r["agentes"] else ""}


def _cu_tabela_perfis(company_id: int) -> list:
    _pr_sincronizar_agentes()
    ov = _cu_overrides(company_id)
    linhas = []
    for andar in _PREDIO_ANDARES:
        for a in andar["agentes"]:
            if not a.get("ativo"):
                continue
            pm, pe = _cu_padrao(a["key"])
            o = ov.get(a["key"]) or {}
            linhas.append({"key": a["key"], "nome": a["nome"] if a["key"] != "recepcionista" else "Recepção (encaminhamento)",
                           "andar": andar["rotulo"], "padrao": f"{_CU_NOMES[pm]} · {_CU_ESFORCOS[pe]}",
                           "modelo": o.get("modelo", ""), "esforco": o.get("esforco", ""), "web": bool(a.get("web"))})
    pm, pe = _cu_padrao("extracao")
    o = ov.get("extracao") or {}
    linhas.append({"key": "extracao", "nome": "Leitura de respostas no WhatsApp", "andar": "Térreo",
                   "padrao": f"{_CU_NOMES[pm]} · {_CU_ESFORCOS[pe]}", "modelo": o.get("modelo", ""),
                   "esforco": o.get("esforco", ""), "web": False})
    return linhas


# ── Rotas ────────────────────────────────────────────────────────────────────

@app.get("/predio/custos", response_class=HTMLResponse)
@require_login
async def predio_custos(request: Request, session: Session = Depends(get_session)):
    ctx = _pr_ctx(request, session)
    if not ctx or ctx.membership.role != "admin":
        return RedirectResponse("/predio", status_code=303)
    r = _cu_resumo(session, ctx.company.id, request.query_params.get("mes", ""))
    a, m = int(r["mes"][:4]), int(r["mes"][5:7])
    ant = f"{a - (m == 1):04d}-{(m - 2) % 12 + 1:02d}"
    prox = f"{a + (m == 12):04d}-{m % 12 + 1:02d}"
    return render("predio_custos.html", request=request, context={
        **_pr_base_ctx(request, session, ctx), "r": r, "ant": ant, "prox": prox,
        "perfis": _cu_tabela_perfis(ctx.company.id), "modelos_opc": _CU_NOMES, "esforcos_opc": _CU_ESFORCOS,
        "salvo": request.query_params.get("salvo") == "1",
    })


@app.post("/predio/custos/modelos")
@require_login
async def predio_custos_modelos(request: Request, session: Session = Depends(get_session)):
    ctx = _pr_ctx(request, session)
    if not ctx or ctx.membership.role != "admin":
        return RedirectResponse("/predio", status_code=303)
    form = await request.form()
    validas = {p["key"] for p in _cu_tabela_perfis(ctx.company.id)}
    novo = {}
    for key in validas:
        mod, esf = str(form.get(f"modelo_{key}") or ""), str(form.get(f"esforco_{key}") or "")
        item = {}
        if mod in _CU_MODELOS:
            item["modelo"] = mod
        if esf in _CU_ESFORCOS:
            item["esforco"] = esf
        if item:
            novo[key] = item
    cfg = session.exec(_sel_pr(PredioConfig).where(PredioConfig.company_id == ctx.company.id)).first() \
        or PredioConfig(company_id=ctx.company.id)
    cfg.modelos_json = _json_pr.dumps(novo)
    session.add(cfg)
    session.commit()
    _CU_CFG.pop(ctx.company.id, None)
    return RedirectResponse("/predio/custos?salvo=1#modelos", status_code=303)


TEMPLATES["predio_custos.html"] = r"""
{% extends "base.html" %}
{% block content %}
<style>
  .cu-wrap{display:grid;gap:1rem;max-width:1100px;}
  .cu-kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:.75rem;}
  .cu-kpi{border:1px solid var(--bs-border-color);border-radius:12px;padding:.8rem 1rem;background:var(--bs-body-bg);}
  .cu-kpi b{display:block;font-size:1.35rem;font-variant-numeric:tabular-nums;}
  .cu-kpi span{font-size:.75rem;text-transform:uppercase;letter-spacing:.06em;color:var(--bs-secondary-color);}
  .cu-table{overflow-x:auto;}
  .cu-table table{font-size:.86rem;font-variant-numeric:tabular-nums;min-width:640px;}
  .cu-bar{height:.45rem;border-radius:4px;background:var(--mc-primary,#f97316);min-width:2px;}
  .cu-num{text-align:right;white-space:nowrap;}
  .cu-perfil select{min-width:8.5rem;}
</style>
<div class="cu-wrap">
  <div class="d-flex flex-wrap justify-content-between align-items-center gap-2">
    <div>
      <a href="/predio" class="small text-decoration-none">← Prédio</a>
      <h1 class="h4 fw-bold mb-0">Custo da IA</h1>
      <p class="small text-body-secondary mb-0">Estimativa pelos preços oficiais da Anthropic, em US$. Conversão a R$ {{ ('%.2f'|format(r.dolar))|replace('.', ',') }} por dólar (variável PREDIO_DOLAR no Render).</p>
    </div>
    <div class="btn-group btn-group-sm" role="group" aria-label="Mês">
      <a class="btn btn-outline-secondary" href="/predio/custos?mes={{ ant }}">← {{ ant[5:] }}/{{ ant[:4] }}</a>
      <span class="btn btn-secondary disabled">{{ r.mes[5:] }}/{{ r.mes[:4] }}</span>
      <a class="btn btn-outline-secondary" href="/predio/custos?mes={{ prox }}">{{ prox[5:] }}/{{ prox[:4] }} →</a>
    </div>
  </div>

  <div class="cu-kpis">
    <div class="cu-kpi"><span>Total do mês</span><b>US$ {{ ('%.2f'|format(r.total.custo_usd))|replace('.', ',') }}</b><small class="text-body-secondary">≈ R$ {{ ('%.2f'|format(r.total.custo_brl))|replace('.', ',') }}</small></div>
    <div class="cu-kpi"><span>Chamadas à API</span><b>{{ r.total.chamadas }}</b><small class="text-body-secondary">{{ r.total.buscas }} buscas na web</small></div>
    <div class="cu-kpi"><span>Tokens de saída</span><b>{{ '{:,}'.format(r.total.saida).replace(',', '.') }}</b><small class="text-body-secondary">a parte mais cara</small></div>
    <div class="cu-kpi"><span>Entrada vinda do cache</span><b>{{ r.cache_pct }}%</b><small class="text-body-secondary">quanto maior, mais barato</small></div>
  </div>

  <div class="card p-3">
    <h2 class="h6 fw-bold mb-2">Por agente</h2>
    {% if r.agentes %}
    <div class="cu-table"><table class="table table-sm align-middle mb-0">
      <thead><tr><th>Agente</th><th class="cu-num">Chamados</th><th class="cu-num">Chamadas</th><th class="cu-num">Entrada</th><th class="cu-num">Saída</th><th class="cu-num">Buscas</th><th class="cu-num">US$</th><th class="cu-num">R$</th><th style="width:18%">Peso</th></tr></thead>
      <tbody>{% for a in r.agentes %}
        <tr><td>{{ a.nome }}</td><td class="cu-num">{{ a.chamados }}</td><td class="cu-num">{{ a.chamadas }}</td>
          <td class="cu-num">{{ '{:,}'.format(a.entrada + a.cache_leitura + a.cache_escrita).replace(',', '.') }}</td>
          <td class="cu-num">{{ '{:,}'.format(a.saida).replace(',', '.') }}</td><td class="cu-num">{{ a.buscas }}</td>
          <td class="cu-num">{{ ('%.2f'|format(a.custo_usd))|replace('.', ',') }}</td><td class="cu-num">{{ ('%.2f'|format(a.custo_brl))|replace('.', ',') }}</td>
          <td><div class="cu-bar" style="width:{{ [a.pct, 100]|min }}%" title="{{ a.pct }}%"></div></td></tr>
      {% endfor %}</tbody>
    </table></div>
    {% else %}<p class="small text-body-secondary mb-0">Nenhum uso registrado neste mês. A medição começa a partir desta atualização.</p>{% endif %}
  </div>

  <div class="row g-3">
    <div class="col-12 col-lg-5"><div class="card p-3 h-100">
      <h2 class="h6 fw-bold mb-2">Por modelo</h2>
      {% if r.modelos %}<div class="cu-table"><table class="table table-sm mb-0" style="min-width:0">
        <thead><tr><th>Modelo</th><th class="cu-num">Chamadas</th><th class="cu-num">US$</th></tr></thead>
        <tbody>{% for m in r.modelos %}<tr><td>{{ m.modelo }}</td><td class="cu-num">{{ m.chamadas }}</td><td class="cu-num">{{ ('%.2f'|format(m.custo_usd))|replace('.', ',') }}</td></tr>{% endfor %}</tbody>
      </table></div>{% else %}<p class="small text-body-secondary mb-0">—</p>{% endif %}
    </div></div>
    <div class="col-12 col-lg-7"><div class="card p-3 h-100">
      <h2 class="h6 fw-bold mb-2">Chamados mais caros</h2>
      {% if r.caros %}<div class="cu-table"><table class="table table-sm mb-0" style="min-width:0">
        <tbody>{% for c in r.caros %}<tr><td><a href="/predio/chamados/{{ c.id }}">#{{ c.id }} {{ c.titulo }}</a>{% if c.reuniao %} <span class="badge text-bg-light">reunião</span>{% endif %}<div class="small text-body-secondary">{{ c.agente }}</div></td>
          <td class="cu-num">US$ {{ ('%.2f'|format(c.custo_usd))|replace('.', ',') }}<div class="small text-body-secondary">R$ {{ ('%.2f'|format(c.custo_brl))|replace('.', ',') }}</div></td></tr>{% endfor %}</tbody>
      </table></div>{% else %}<p class="small text-body-secondary mb-0">—</p>{% endif %}
    </div></div>
  </div>

  <div class="card p-3" id="modelos">
    <h2 class="h6 fw-bold mb-1">Modelo e esforço de cada agente</h2>
    <p class="small text-body-secondary mb-3">Opus 5.5: US$ 4 / 20 por milhão de tokens (entrada / saída) · Sonnet 5.5: US$ 2 / 10 · Haiku 5.5: US$ 0,10 / 0,50. Esforço alto faz o modelo pensar mais antes de responder (mais tokens de saída). Deixe em "Padrão" para usar a recomendação. Se um modelo mais barato não conseguir atender um pedido, o sistema refaz no Opus sozinho.</p>
    {% if salvo %}<div class="alert alert-success py-2 small">Salvo. Vale a partir do próximo chamado.</div>{% endif %}
    <form method="post" action="/predio/custos/modelos">
      <div class="cu-table"><table class="table table-sm align-middle cu-perfil">
        <thead><tr><th>Agente</th><th>Andar</th><th>Padrão</th><th>Modelo</th><th>Esforço</th></tr></thead>
        <tbody>{% for p in perfis %}
          <tr><td>{{ p.nome }}{% if p.web %} <span class="badge text-bg-light">web</span>{% endif %}</td><td class="small">{{ p.andar }}</td><td class="small text-body-secondary">{{ p.padrao }}</td>
            <td><select class="form-select form-select-sm" name="modelo_{{ p.key }}" aria-label="Modelo de {{ p.nome }}">
              <option value="">Padrão</option>{% for k, n in modelos_opc.items() %}<option value="{{ k }}" {{ 'selected' if p.modelo == k }}>{{ n }}</option>{% endfor %}</select></td>
            <td><select class="form-select form-select-sm" name="esforco_{{ p.key }}" aria-label="Esforço de {{ p.nome }}">
              <option value="">Padrão</option>{% for k, n in esforcos_opc.items() %}<option value="{{ k }}" {{ 'selected' if p.esforco == k }}>{{ n }}</option>{% endfor %}</select></td></tr>
        {% endfor %}</tbody>
      </table></div>
      <button type="submit" class="btn btn-primary btn-sm">Salvar</button>
    </form>
  </div>
</div>
{% endblock %}
"""

_CU_CARD = r"""
    {% if custos %}
    <div class="card p-3" id="custos-ia">
      <h2 class="h6 fw-bold mb-1">Custo da IA</h2>
      <p class="small mb-2">Este mês: <strong>US$ {{ ('%.2f'|format(custos.usd))|replace('.', ',') }}</strong> (≈ R$ {{ ('%.2f'|format(custos.brl))|replace('.', ',') }}) em {{ custos.chamadas }} chamadas{% if custos.top %} · mais caro: {{ custos.top }}{% endif %}.</p>
      <a class="btn btn-outline-primary btn-sm" href="/predio/custos">Ver custos e modelos</a>
    </div>
    {% endif %}
"""
_cu_tpl = TEMPLATES.get("predio.html", "")
_cu_ancora = "    {% if rh %}\n"
if _cu_ancora in _cu_tpl and 'id="custos-ia"' not in _cu_tpl:
    TEMPLATES["predio.html"] = _cu_tpl.replace(_cu_ancora, _CU_CARD.strip("\n") + "\n" + _cu_ancora, 1)
else:
    print("[predio_custos] card 'Custo da IA' não inserido (âncora não encontrada)")

print("[predio_custos] Medição de custo e modelo por agente carregados.")

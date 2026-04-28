# ============================================================================
# PATCH — Viabilidade: Salvar, Histórico e Compartilhamento
# ============================================================================
# Adiciona ao patch de viabilidade:
#   - Tabela ViabilidadeAnalise (id, company_id, client_id, nome, dados_json,
#     resultado_json, token, created_at)
#   - Freemium: 3 análises gratuitas, depois 49 créditos
#   - POST /ferramentas/viabilidade/salvar
#   - GET  /ferramentas/viabilidade/historico
#   - GET  /ferramentas/viabilidade/ver/{token}   (sem login)
#   - GET  /ferramentas/viabilidade/base/{id}     (reabre como base)
#   - DELETE /ferramentas/viabilidade/apagar/{id}
# ============================================================================

import uuid as _uuid
import json as _json2
from typing import Optional as _Opt
from sqlmodel import Field as _Field, SQLModel as _SQLModel

# ── Modelo ────────────────────────────────────────────────────────────────────

class ViabilidadeAnalise(_SQLModel, table=True):
    __tablename__ = "viabilidadeanalise"
    id:          _Opt[int]  = _Field(default=None, primary_key=True)
    company_id:  int        = _Field(index=True)
    client_id:   int        = _Field(index=True)
    nome:        str        = _Field(default="Sem nome")
    dados_json:  str        = _Field(default="{}")   # premissas completas
    resultado_json: str     = _Field(default="{}")   # resultado + fluxo
    token:       str        = _Field(default_factory=lambda: _uuid.uuid4().hex, unique=True, index=True)
    created_at:  _Opt[str]  = _Field(default=None)

# Cria a tabela se não existir
try:
    _SQLModel.metadata.create_all(engine, tables=[ViabilidadeAnalise.__table__])
except Exception as _e:
    pass

VIABILIDADE_CREDITOS    = 49
VIABILIDADE_GRATIS_MAX  = 3

def _contar_analises(session, company_id: int, client_id: int) -> int:
    return len(session.exec(
        select(ViabilidadeAnalise)
        .where(ViabilidadeAnalise.company_id == company_id,
               ViabilidadeAnalise.client_id  == client_id)
    ).all())

def _debitar_creditos(session, company_id: int, client_id: int) -> tuple[bool, str]:
    """Debita créditos da carteira do cliente. Retorna (ok, mensagem)."""
    try:
        wallet = session.exec(
            select(CreditWallet)
            .where(CreditWallet.company_id == company_id,
                   CreditWallet.client_id  == client_id)
        ).first()
        if not wallet:
            return False, "Carteira de créditos não encontrada para este cliente."
        bal = float(wallet.balance_credits or 0)
        if bal < VIABILIDADE_CREDITOS:
            return False, f"Saldo insuficiente. Necessário: {VIABILIDADE_CREDITOS} créditos. Disponível: {bal:.0f}."
        wallet.balance_credits = bal - VIABILIDADE_CREDITOS
        session.add(wallet)
        # Lançamento no ledger
        try:
            ledger = CreditLedger(
                company_id=company_id,
                client_id=client_id,
                amount_credits=-VIABILIDADE_CREDITOS,
                description="Análise de Viabilidade Imobiliária salva",
            )
            session.add(ledger)
        except Exception:
            pass
        return True, "ok"
    except Exception as ex:
        return False, str(ex)


# ── POST /ferramentas/viabilidade/salvar ─────────────────────────────────────

@app.post("/ferramentas/viabilidade/salvar")
@require_login
async def viabilidade_salvar(
    request: Request,
    session: Session = Depends(get_session),
):
    ctx = get_tenant_context(request, session)
    if not ctx:
        return JSONResponse({"ok": False, "erro": "Não autenticado."}, status_code=401)

    client = get_client_or_none(session, ctx.company.id,
                                get_active_client_id(request, session, ctx))
    if not client:
        return JSONResponse({"ok": False, "erro": "Nenhum cliente ativo."}, status_code=400)

    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"ok": False, "erro": "JSON inválido."}, status_code=400)

    dados_json    = body.get("dados_json", "{}")
    resultado_json = body.get("resultado_json", "{}")
    nome          = body.get("nome", "Análise sem nome")[:120]

    total = _contar_analises(session, ctx.company.id, client.id)

    # Freemium: cobra se já usou as 3 grátis
    if total >= VIABILIDADE_GRATIS_MAX:
        ok, msg = _debitar_creditos(session, ctx.company.id, client.id)
        if not ok:
            return JSONResponse({
                "ok": False,
                "erro": msg,
                "precisa_creditos": True,
                "creditos_necessarios": VIABILIDADE_CREDITOS,
            })

    analise = ViabilidadeAnalise(
        company_id=ctx.company.id,
        client_id=client.id,
        nome=nome,
        dados_json=dados_json,
        resultado_json=resultado_json,
        created_at=str(utcnow()),
    )
    session.add(analise)
    session.commit()
    session.refresh(analise)

    gratuitas_usadas = min(total + 1, VIABILIDADE_GRATIS_MAX)
    gratis_restantes = max(0, VIABILIDADE_GRATIS_MAX - (total + 1))

    return JSONResponse({
        "ok": True,
        "id": analise.id,
        "token": analise.token,
        "link": f"/ferramentas/viabilidade/ver/{analise.token}",
        "gratis_restantes": gratis_restantes,
        "cobrado": total >= VIABILIDADE_GRATIS_MAX,
        "creditos_cobrados": VIABILIDADE_CREDITOS if total >= VIABILIDADE_GRATIS_MAX else 0,
    })


# ── GET /ferramentas/viabilidade/historico ───────────────────────────────────

@app.get("/ferramentas/viabilidade/historico", response_class=HTMLResponse)
@require_login
async def viabilidade_historico(
    request: Request,
    session: Session = Depends(get_session),
) -> HTMLResponse:
    ctx = get_tenant_context(request, session)
    if not ctx:
        request.session.clear()
        return RedirectResponse("/login", status_code=303)

    client = get_client_or_none(session, ctx.company.id,
                                get_active_client_id(request, session, ctx))
    if not client:
        return RedirectResponse("/ferramentas/viabilidade", status_code=303)

    analises_raw = session.exec(
        select(ViabilidadeAnalise)
        .where(ViabilidadeAnalise.company_id == ctx.company.id,
               ViabilidadeAnalise.client_id  == client.id)
        .order_by(ViabilidadeAnalise.id.desc())
    ).all()

    # Enriquece com KPIs do resultado
    analises = []
    for a in analises_raw:
        try:
            r = _json2.loads(a.resultado_json)
        except Exception:
            r = {}
        analises.append({
            "id":       a.id,
            "nome":     a.nome,
            "token":    a.token,
            "created":  a.created_at,
            "vgv":      r.get("vgv_liquido", 0),
            "margem":   r.get("margem_vgv", 0),
            "tir":      r.get("tir_anual"),
            "status":   r.get("status", {}).get("label", "—"),
            "cor":      r.get("status", {}).get("color", "secondary"),
        })

    total = len(analises)
    gratis_restantes = max(0, VIABILIDADE_GRATIS_MAX - total)

    return render("viabilidade_historico.html", request=request, context={
        "current_user":      ctx.user,
        "current_company":   ctx.company,
        "role":              ctx.membership.role,
        "current_client":    client,
        "analises":          analises,
        "total":             total,
        "gratis_restantes":  gratis_restantes,
        "creditos_por_analise": VIABILIDADE_CREDITOS,
    })


# ── GET /ferramentas/viabilidade/ver/{token} (público, sem login) ────────────

@app.get("/ferramentas/viabilidade/ver/{token}", response_class=HTMLResponse)
async def viabilidade_ver(
    token: str,
    request: Request,
    session: Session = Depends(get_session),
) -> HTMLResponse:
    analise = session.exec(
        select(ViabilidadeAnalise).where(ViabilidadeAnalise.token == token)
    ).first()

    if not analise:
        return HTMLResponse("<h2 style='font-family:sans-serif;padding:2rem;'>Análise não encontrada ou link inválido.</h2>", status_code=404)

    try:
        resultado = _json2.loads(analise.resultado_json)
        dados     = _json2.loads(analise.dados_json)
    except Exception:
        resultado = {}
        dados = {}

    return render("viabilidade_publica.html", request=request, context={
        "analise":   analise,
        "resultado": resultado,
        "dados":     dados,
        "link":      f"/ferramentas/viabilidade/ver/{token}",
    })


# ── GET /ferramentas/viabilidade/base/{id} (reabre como base) ────────────────

@app.get("/ferramentas/viabilidade/base/{analise_id}", response_class=HTMLResponse)
@require_login
async def viabilidade_base(
    analise_id: int,
    request: Request,
    session: Session = Depends(get_session),
) -> HTMLResponse:
    ctx = get_tenant_context(request, session)
    if not ctx:
        request.session.clear()
        return RedirectResponse("/login", status_code=303)

    analise = session.get(ViabilidadeAnalise, analise_id)
    if not analise or analise.company_id != ctx.company.id:
        return RedirectResponse("/ferramentas/viabilidade", status_code=303)

    try:
        dados = _json2.loads(analise.dados_json)
    except Exception:
        dados = {}

    cc = get_client_or_none(session, ctx.company.id,
                            get_active_client_id(request, session, ctx))

    # Recalcula para mostrar resultado imediato
    resultado = _calcular_viabilidade_v2(dados)

    return render("ferramenta_viabilidade.html", request=request, context={
        "current_user":    ctx.user,
        "current_company": ctx.company,
        "role":            ctx.membership.role,
        "current_client":  cc,
        "resultado":       resultado,
        "dados":           dados,
        "base_de":         analise.nome,
    })


# ── DELETE /ferramentas/viabilidade/apagar/{id} ──────────────────────────────

@app.post("/ferramentas/viabilidade/apagar/{analise_id}")
@require_login
async def viabilidade_apagar(
    analise_id: int,
    request: Request,
    session: Session = Depends(get_session),
):
    ctx = get_tenant_context(request, session)
    if not ctx:
        return JSONResponse({"ok": False}, status_code=401)

    analise = session.get(ViabilidadeAnalise, analise_id)
    if not analise or analise.company_id != ctx.company.id:
        return JSONResponse({"ok": False, "erro": "Não encontrada."}, status_code=404)

    session.delete(analise)
    session.commit()
    return JSONResponse({"ok": True})


# ── Template: histórico ───────────────────────────────────────────────────────

TEMPLATES["viabilidade_historico.html"] = r"""
{% extends "base.html" %}
{% block content %}
<style>
  .vh-card{border:1px solid var(--mc-border);border-radius:14px;padding:1.1rem 1.25rem;background:#fff;margin-bottom:.75rem;display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:.75rem;transition:box-shadow .15s;}
  .vh-card:hover{box-shadow:0 2px 12px rgba(0,0,0,.07);}
  .vh-nome{font-weight:700;font-size:.95rem;margin-bottom:.2rem;}
  .vh-meta{font-size:.75rem;color:var(--mc-muted);}
  .vh-kpis{display:flex;gap:1.25rem;flex-wrap:wrap;}
  .vh-kpi{text-align:center;}<br>
  .vh-kpi-l{font-size:.65rem;font-weight:700;text-transform:uppercase;color:var(--mc-muted);}
  .vh-kpi-v{font-size:.9rem;font-weight:700;}
  .vh-badge{font-size:.68rem;font-weight:700;padding:.2rem .6rem;border-radius:999px;}
  .vh-badge.success{background:rgba(22,163,74,.12);color:#166534;}
  .vh-badge.primary{background:rgba(59,130,246,.12);color:#1e40af;}
  .vh-badge.warning{background:rgba(202,138,4,.12);color:#854d0e;}
  .vh-badge.danger{background:rgba(220,38,38,.12);color:#991b1b;}
  .vh-badge.secondary{background:#f3f4f6;color:#6b7280;}
  .vh-acoes{display:flex;gap:.5rem;flex-wrap:wrap;}
</style>

<div class="d-flex justify-content-between align-items-start flex-wrap gap-3 mb-3">
  <div>
    <a href="/ferramentas/viabilidade" class="btn btn-outline-secondary btn-sm mb-2">
      <i class="bi bi-arrow-left"></i> Nova análise
    </a>
    <h4 class="mb-1">Minhas Análises</h4>
    <div class="muted small">Histórico de viabilidades salvas de {{ current_client.name }}</div>
  </div>
  <div class="text-end">
    {% if gratis_restantes > 0 %}
      <div class="badge text-bg-success fs-6 px-3 py-2">{{ gratis_restantes }} gratuita{{ 's' if gratis_restantes > 1 }} restante{{ 's' if gratis_restantes > 1 }}</div>
    {% else %}
      <div class="badge text-bg-warning fs-6 px-3 py-2">{{ creditos_por_analise }} créditos por análise</div>
      <div class="muted tiny mt-1">Plano gratuito esgotado</div>
    {% endif %}
  </div>
</div>

{% if not analises %}
  <div class="card p-4 text-center">
    <div style="font-size:2.5rem;margin-bottom:.75rem;">📊</div>
    <h5>Nenhuma análise salva ainda</h5>
    <div class="muted mb-3">Calcule uma viabilidade e salve o resultado para encontrá-la aqui.</div>
    <a href="/ferramentas/viabilidade" class="btn btn-primary">Fazer uma análise</a>
  </div>
{% else %}
  {% for a in analises %}
  <div class="vh-card" id="analise-{{ a.id }}">
    <div>
      <div class="vh-nome">{{ a.nome }}</div>
      <div class="vh-meta">
        <span class="vh-badge {{ a.cor }}">{{ a.status }}</span>
        {% if a.created %}<span class="ms-2">{{ a.created[:10] }}</span>{% endif %}
      </div>
    </div>
    <div class="vh-kpis">
      {% if a.vgv %}
      <div class="vh-kpi">
        <div class="vh-kpi-l">VGV Líquido</div>
        <div class="vh-kpi-v">{{ a.vgv|brl }}</div>
      </div>
      {% endif %}
      {% if a.margem %}
      <div class="vh-kpi">
        <div class="vh-kpi-l">Margem</div>
        <div class="vh-kpi-v">{{ a.margem }}%</div>
      </div>
      {% endif %}
      {% if a.tir %}
      <div class="vh-kpi">
        <div class="vh-kpi-l">TIR</div>
        <div class="vh-kpi-v">{{ a.tir }}%</div>
      </div>
      {% endif %}
    </div>
    <div class="vh-acoes">
      <a href="/ferramentas/viabilidade/ver/{{ a.token }}" target="_blank"
         class="btn btn-sm btn-outline-primary">
        <i class="bi bi-eye me-1"></i> Ver
      </a>
      <button class="btn btn-sm btn-outline-secondary"
              onclick="copiarLink('/ferramentas/viabilidade/ver/{{ a.token }}', this)">
        <i class="bi bi-link-45deg me-1"></i> Copiar link
      </button>
      <a href="/ferramentas/viabilidade/base/{{ a.id }}"
         class="btn btn-sm btn-outline-secondary">
        <i class="bi bi-pencil me-1"></i> Usar como base
      </a>
      <button class="btn btn-sm btn-outline-danger"
              onclick="apagarAnalise({{ a.id }})">
        <i class="bi bi-trash"></i>
      </button>
    </div>
  </div>
  {% endfor %}
{% endif %}

<script>
function copiarLink(path, btn) {
  const url = window.location.origin + path;
  navigator.clipboard.writeText(url).then(() => {
    const orig = btn.innerHTML;
    btn.innerHTML = '<i class="bi bi-check2 me-1"></i> Copiado!';
    btn.classList.add('btn-success');
    btn.classList.remove('btn-outline-secondary');
    setTimeout(() => { btn.innerHTML = orig; btn.classList.remove('btn-success'); btn.classList.add('btn-outline-secondary'); }, 2000);
  });
}

async function apagarAnalise(id) {
  if (!confirm('Apagar esta análise? Esta ação não pode ser desfeita.')) return;
  const r = await fetch('/ferramentas/viabilidade/apagar/' + id, { method: 'POST' });
  const d = await r.json();
  if (d.ok) {
    const el = document.getElementById('analise-' + id);
    if (el) el.remove();
  } else {
    alert('Erro ao apagar: ' + (d.erro || 'tente novamente'));
  }
}
</script>
{% endblock %}
"""


# ── Template: visualização pública ───────────────────────────────────────────

TEMPLATES["viabilidade_publica.html"] = r"""
<!DOCTYPE html>
<html lang="pt-BR">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{{ analise.nome }} — Análise de Viabilidade</title>
  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
  <link href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.0/font/bootstrap-icons.css" rel="stylesheet">
  <style>
    :root { --mc-primary: #E07020; }
    body { background: #f8f9fa; font-family: system-ui, sans-serif; }
    .pub-header { background: #fff; border-bottom: 3px solid var(--mc-primary); padding: 1.25rem 0; margin-bottom: 2rem; }
    .pub-logo { font-weight: 800; font-size: 1.2rem; color: var(--mc-primary); letter-spacing: -.02em; }
    .kpi { background: #fff; border: 1px solid #e5e7eb; border-radius: 13px; padding: .9rem 1rem; }
    .kpi-l { font-size: .68rem; font-weight: 700; text-transform: uppercase; letter-spacing: .06em; color: #6b7280; }
    .kpi-v { font-size: 21px; font-weight: 700; margin-top: .2rem; }
    .kpi-f { font-size: .72rem; color: #6b7280; margin-top: .15rem; }
    .bk { border: 1px solid #e5e7eb; border-radius: 12px; overflow: hidden; }
    .bk-r { display: flex; justify-content: space-between; padding: .48rem 1rem; font-size: .86rem; border-bottom: 1px solid #e5e7eb; }
    .bk-r:last-child { border-bottom: 0; }
    .bk-t { font-weight: 700; background: #fff7f0; }
    .bk-l { color: #6b7280; }
    .fc-wrap { max-height: 420px; overflow-y: auto; border: 1px solid #e5e7eb; border-radius: 12px; }
    .fc-table { width: 100%; border-collapse: collapse; font-size: .78rem; }
    .fc-table th { background: var(--mc-primary); color: #fff; padding: .4rem .6rem; text-align: right; position: sticky; top: 0; }
    .fc-table th:first-child { text-align: left; }
    .fc-table td { padding: .35rem .6rem; text-align: right; border-bottom: 1px solid #f3f4f6; }
    .fc-table td:first-child { text-align: left; font-weight: 600; }
    .fc-pos { color: #16a34a; } .fc-neg { color: #dc2626; }
    .verdict { border-radius: 14px; padding: 1rem 1.2rem; border: 1px solid #e5e7eb; background: #fff; }
    .v-badge { display: inline-flex; align-items: center; gap: .4rem; font-size: .74rem; font-weight: 700; text-transform: uppercase; letter-spacing: .07em; padding: .28rem .7rem; border-radius: 999px; margin-bottom: .55rem; }
    .v-badge.success { background: rgba(22,163,74,.12); color: #166534; }
    .v-badge.primary { background: rgba(59,130,246,.12); color: #1e40af; }
    .v-badge.warning { background: rgba(202,138,4,.12); color: #854d0e; }
    .v-badge.danger { background: rgba(220,38,38,.12); color: #991b1b; }
    .share-bar { background: #fff; border: 1px solid #e5e7eb; border-radius: 12px; padding: .75rem 1rem; display: flex; align-items: center; gap: 1rem; flex-wrap: wrap; margin-bottom: 1.5rem; }
    @media print { .share-bar, .no-print { display: none !important; } }
  </style>
</head>
<body>
  <div class="pub-header">
    <div class="container">
      <div class="d-flex justify-content-between align-items-center">
        <div class="pub-logo">Maffezzolli Capital</div>
        <div style="font-size:.8rem;color:#6b7280;">Análise de Viabilidade Imobiliária</div>
      </div>
    </div>
  </div>

  <div class="container pb-5">
    <h4 class="mb-1">{{ analise.nome }}</h4>
    {% if analise.created_at %}<div class="text-muted small mb-3">Gerado em {{ analise.created_at[:10] }}</div>{% endif %}

    {# Barra de compartilhamento #}
    <div class="share-bar no-print">
      <div style="font-size:.85rem;color:#6b7280;flex:1;">
        <i class="bi bi-link-45deg me-1"></i> Link desta análise
      </div>
      <input type="text" id="linkInput" value="{{ request.url }}" readonly
             style="border:1px solid #e5e7eb;border-radius:8px;padding:.35rem .75rem;font-size:.8rem;width:320px;max-width:100%;">
      <button class="btn btn-sm btn-outline-primary" onclick="copiarLink()">
        <i class="bi bi-clipboard me-1"></i> Copiar
      </button>
      <button class="btn btn-sm btn-outline-secondary" onclick="window.print()">
        <i class="bi bi-printer me-1"></i> PDF
      </button>
    </div>

    {% if resultado %}
    {% set r = resultado %}
    {% set st = r.status if r.status else {} %}

    {# Veredicto #}
    {% if st %}
    <div class="verdict mb-3">
      <div class="v-badge {{ st.color }}">{{ st.icon }} {{ st.label }}</div>
      <div style="font-size:.9rem;line-height:1.5;">{{ st.desc }}</div>
    </div>
    {% endif %}

    {# KPIs #}
    <div class="row g-2 mb-3">
      {% for lb, vl, ft, cor in [
        ("VGV Líquido", r.vgv_liquido|brl, r.unidades_total|string + " unidades", "#E07020"),
        ("Custo Total", r.custo_total|brl, r.custo_m2_equiv|round|int|string + " R$/m²", "#374151"),
        ("Resultado Bruto", r.resultado_bruto|brl, r.margem_vgv|string + "% sobre VGV", "#16a34a" if r.resultado_bruto >= 0 else "#dc2626"),
        ("Margem s/ Custo", r.margem_custo|string + "%", "Retorno s/ investimento", "#16a34a" if r.margem_custo >= 20 else ("#ca8a04" if r.margem_custo >= 10 else "#dc2626")),
      ] %}
      <div class="col-6 col-md-3">
        <div class="kpi">
          <div class="kpi-l">{{ lb }}</div>
          <div class="kpi-v" style="color:{{ cor }};">{{ vl }}</div>
          <div class="kpi-f">{{ ft }}</div>
        </div>
      </div>
      {% endfor %}

      {% if r.tir_anual is not none %}
      <div class="col-6 col-md-3"><div class="kpi"><div class="kpi-l">TIR Anual</div><div class="kpi-v" style="color:{{ '#16a34a' if r.tir_anual >= 20 else ('#ca8a04' if r.tir_anual >= 15 else '#dc2626') }};">{{ r.tir_anual }}%</div><div class="kpi-f">Taxa interna de retorno</div></div></div>
      {% endif %}
      <div class="col-6 col-md-3"><div class="kpi"><div class="kpi-l">Exposição Máxima</div><div class="kpi-v" style="color:#dc2626;">{{ r.exposicao_maxima|brl }}</div><div class="kpi-f">Capital necessário no pico</div></div></div>
      {% if r.vpl %}<div class="col-6 col-md-3"><div class="kpi"><div class="kpi-l">VPL (TMA 12% a.a.)</div><div class="kpi-v" style="color:{{ '#16a34a' if r.vpl >= 0 else '#dc2626' }};">{{ r.vpl|brl }}</div><div class="kpi-f">Valor presente líquido</div></div></div>{% endif %}
      {% if r.payback_mes %}<div class="col-6 col-md-3"><div class="kpi"><div class="kpi-l">Payback</div><div class="kpi-v">Mês {{ r.payback_mes }}</div><div class="kpi-f">Retorno do capital</div></div></div>{% endif %}
    </div>

    {# Breakdown #}
    <div class="row g-3 mb-3">
      <div class="col-md-6">
        <h6 class="mb-2">Composição de Custos</h6>
        <div class="bk">
          <div class="bk-r"><span class="bk-l">CUB × Área equivalente</span><span>{{ r.custo_cub|brl }}</span></div>
          {% if r.itens_extra > 0 %}<div class="bk-r"><span class="bk-l">Itens fora do CUB</span><span>{{ r.itens_extra|brl }}</span></div>{% endif %}
          <div class="bk-r"><span class="bk-l">Despesas indiretas</span><span>{{ r.custo_indiretos|brl }}</span></div>
          {% if r.valor_terreno > 0 %}<div class="bk-r"><span class="bk-l">Terreno</span><span>{{ r.valor_terreno|brl }}</span></div>{% endif %}
          <div class="bk-r"><span class="bk-l">Comercialização</span><span>{{ r.custo_comercial|brl }}</span></div>
          <div class="bk-r"><span class="bk-l">Impostos</span><span>{{ r.custo_impostos|brl }}</span></div>
          <div class="bk-r bk-t"><span>Total</span><span>{{ r.custo_total|brl }}</span></div>
        </div>
      </div>
      <div class="col-md-6">
        <h6 class="mb-2">Composição do VGV</h6>
        <div class="bk">
          <div class="bk-r"><span class="bk-l">VGV Bruto</span><span>{{ r.vgv_bruto|brl }}</span></div>
          {% if r.valor_permuta > 0 %}<div class="bk-r"><span class="bk-l">(−) Permuta</span><span style="color:#dc2626;">−{{ r.valor_permuta|brl }}</span></div>{% endif %}
          <div class="bk-r bk-t"><span>VGV Líquido</span><span>{{ r.vgv_liquido|brl }}</span></div>
          <div class="bk-r"><span class="bk-l">(−) Custo Total</span><span style="color:#dc2626;">−{{ r.custo_total|brl }}</span></div>
          <div class="bk-r bk-t" style="color:{{ '#16a34a' if r.resultado_bruto >= 0 else '#dc2626' }};"><span>Resultado</span><span>{{ r.resultado_bruto|brl }}</span></div>
        </div>
      </div>
    </div>

    {# Fluxo de caixa #}
    <h6 class="mb-2">Fluxo de Caixa Mensal</h6>
    <div class="fc-wrap">
      <table class="fc-table">
        <thead><tr>
          <th style="text-align:left;">Mês</th>
          <th>Receita</th><th>Comissão</th><th>Tributos</th>
          <th>Custo Obra</th><th>Saldo Mês</th><th>Saldo Acumulado</th>
        </tr></thead>
        <tbody>
          {% for f in r.fluxo %}
          {% if f.receita != 0 or f.custo_obra != 0 or f.saldo_mes != 0 %}
          <tr>
            <td>{{ f.mes }}</td>
            <td>{{ f.receita|brl }}</td>
            <td class="fc-neg">{{ f.comissao|brl }}</td>
            <td class="fc-neg">{{ f.tributos|brl }}</td>
            <td class="fc-neg">{{ f.custo_obra|brl }}</td>
            <td class="{{ 'fc-pos' if f.saldo_mes >= 0 else 'fc-neg' }}">{{ f.saldo_mes|brl }}</td>
            <td class="{{ 'fc-pos' if f.saldo_acumulado >= 0 else 'fc-neg' }}">{{ f.saldo_acumulado|brl }}</td>
          </tr>
          {% endif %}
          {% endfor %}
        </tbody>
      </table>
    </div>
    {% endif %}

    <div class="text-center mt-4 text-muted no-print" style="font-size:.78rem;">
      Análise gerada pela plataforma Maffezzolli Capital · app.maffezzollicapital.com.br
    </div>
  </div>

  <script>
  function copiarLink() {
    const inp = document.getElementById('linkInput');
    navigator.clipboard.writeText(inp.value).then(() => {
      const btn = event.target.closest('button');
      const orig = btn.innerHTML;
      btn.innerHTML = '<i class="bi bi-check2 me-1"></i> Copiado!';
      setTimeout(() => btn.innerHTML = orig, 2000);
    });
  }
  </script>
</body>
</html>
"""

# ── Injeta botão "Salvar" e "Ver histórico" no template de resultado ──────────
# Adiciona script de salvamento ao template existente
_SALVAR_SCRIPT = r"""
<script>
(function(){
  // Injeta botões de salvar e histórico no resultado
  document.addEventListener('DOMContentLoaded', function() {
    const acoes = document.querySelector('#tab-resultado .d-flex.gap-2');
    if (!acoes) return;

    const btnSalvar = document.createElement('button');
    btnSalvar.type = 'button';
    btnSalvar.className = 'btn btn-primary';
    btnSalvar.id = 'btnSalvar';
    btnSalvar.innerHTML = '<i class="bi bi-bookmark-plus me-1"></i> Salvar análise';
    btnSalvar.onclick = salvarAnalise;

    const btnHistorico = document.createElement('a');
    btnHistorico.href = '/ferramentas/viabilidade/historico';
    btnHistorico.className = 'btn btn-outline-secondary';
    btnHistorico.innerHTML = '<i class="bi bi-clock-history me-1"></i> Ver histórico';

    acoes.prepend(btnHistorico);
    acoes.prepend(btnSalvar);
  });

  window.salvarAnalise = async function() {
    const btn = document.getElementById('btnSalvar');
    if (!btn) return;
    btn.disabled = true;
    btn.innerHTML = '<i class="bi bi-hourglass-split me-1"></i> Salvando...';

    // Coleta dados do form
    const form = document.getElementById('vbForm');
    const fd = new FormData(form);
    const dados = {};
    for (let [k,v] of fd.entries()) dados[k] = v;

    // Coleta resultado do DOM (via data attributes injetados)
    const resEl = document.getElementById('vbResultadoJson');
    const resultado = resEl ? JSON.parse(resEl.value) : {};

    const nome = dados.nome_projeto || prompt('Nome desta análise:', 'Análise sem nome') || 'Análise sem nome';

    try {
      const r = await fetch('/ferramentas/viabilidade/salvar', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
          nome: nome,
          dados_json: JSON.stringify(dados),
          resultado_json: resEl ? resEl.value : '{}',
        }),
      });
      const d = await r.json();

      if (d.ok) {
        btn.innerHTML = '<i class="bi bi-check2 me-1"></i> Salvo!';
        btn.className = 'btn btn-success';

        // Mostra link de compartilhamento
        const linkDiv = document.createElement('div');
        linkDiv.className = 'alert alert-success mt-2';
        linkDiv.style.fontSize = '.85rem';
        linkDiv.innerHTML = `
          <strong>✅ Análise salva!</strong>
          ${d.cobrado ? `<span class="text-muted ms-2">(${d.creditos_cobrados} créditos debitados)</span>` : `<span class="text-muted ms-2">(${d.gratis_restantes} gratuita${d.gratis_restantes !== 1 ? 's' : ''} restante${d.gratis_restantes !== 1 ? 's' : ''})</span>`}
          <div class="d-flex gap-2 align-items-center mt-2 flex-wrap">
            <input type="text" id="linkSalvo" value="${window.location.origin}${d.link}"
                   readonly style="border:1px solid #ccc;border-radius:6px;padding:.3rem .65rem;font-size:.8rem;flex:1;min-width:200px;">
            <button class="btn btn-sm btn-success" onclick="navigator.clipboard.writeText(document.getElementById('linkSalvo').value).then(()=>{this.textContent='Copiado!'})">
              <i class="bi bi-clipboard"></i> Copiar link
            </button>
            <a href="/ferramentas/viabilidade/historico" class="btn btn-sm btn-outline-success">Ver histórico</a>
          </div>
        `;
        const acoes = document.querySelector('#tab-resultado .d-flex.gap-2');
        if (acoes) acoes.parentNode.insertBefore(linkDiv, acoes.nextSibling);

      } else if (d.precisa_creditos) {
        btn.innerHTML = '<i class="bi bi-bookmark-plus me-1"></i> Salvar análise';
        btn.disabled = false;
        btn.className = 'btn btn-primary';
        const msg = document.createElement('div');
        msg.className = 'alert alert-warning mt-2';
        msg.style.fontSize = '.85rem';
        msg.innerHTML = `<strong>⚠️ Plano gratuito esgotado</strong><br>Você já usou suas 3 análises gratuitas. Para salvar mais, é necessário <strong>${d.creditos_necessarios} créditos</strong>. <a href="/creditos" class="alert-link">Adquirir créditos →</a>`;
        const acoes = document.querySelector('#tab-resultado .d-flex.gap-2');
        if (acoes) acoes.parentNode.insertBefore(msg, acoes.nextSibling);
      } else {
        btn.innerHTML = '<i class="bi bi-bookmark-plus me-1"></i> Salvar análise';
        btn.disabled = false;
        alert('Erro: ' + (d.erro || 'tente novamente'));
      }
    } catch(e) {
      btn.innerHTML = '<i class="bi bi-bookmark-plus me-1"></i> Salvar análise';
      btn.disabled = false;
      btn.className = 'btn btn-primary';
      alert('Erro de conexão. Tente novamente.');
    }
  };
})();
</script>
"""

# Injeta script no template de viabilidade
_vb_tmpl = TEMPLATES.get("ferramenta_viabilidade.html", "")
if _vb_tmpl and "_SALVAR_SCRIPT" not in _vb_tmpl and "salvarAnalise" not in _vb_tmpl:
    # Injeta campo hidden com resultado JSON + script antes do </form>
    _vb_tmpl = _vb_tmpl.replace(
        "</form>",
        """{% if resultado %}<input type="hidden" id="vbResultadoJson" value="{{ resultado|tojson|e }}">{% endif %}\n</form>\n""" + _SALVAR_SCRIPT,
        1,
    )
    TEMPLATES["ferramenta_viabilidade.html"] = _vb_tmpl

if hasattr(templates_env.loader, "mapping"):
    templates_env.loader.mapping = TEMPLATES

# ============================================================================
# FIM DO PATCH — Viabilidade: Salvar, Histórico e Compartilhamento
# ============================================================================

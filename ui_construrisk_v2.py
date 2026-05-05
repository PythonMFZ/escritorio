# ============================================================================
# PATCH — ConstruRisk v2 + Fix Preços Compliance
# ============================================================================
# Melhorias:
# 1. Análise IA separando Crédito e PLD (antes era um parecer genérico)
# 2. PDF funcional com fallback para impressão
# 3. Fix preços compliance usando ProdutoPreco
#
# DEPLOY: adicione ao final do app.py (substitui ui_construrisk.py e
#         ui_fix_consultas_preco.py — mantenha ambos no app.py mas
#         adicione este APÓS eles para sobrescrever as funções)
# ============================================================================

import math as _math_cr2
import os as _os_cr2
import requests as _req_cr2


# ── Fix 1: Preços compliance usando ProdutoPreco ──────────────────────────────

def _price_cents_v3(cost_cents: int, markup_pct: int,
                    product_code: str = "", company_id: int = 0) -> int:
    """Prioriza ProdutoPreco; fallback para cálculo cost+markup."""
    if product_code and company_id:
        try:
            from sqlmodel import Session as _SPC3
            with _SPC3(engine) as _s3:
                # Tenta código direto primeiro
                _pp = _s3.exec(
                    select(ProdutoPreco)
                    .where(ProdutoPreco.company_id == company_id,
                           ProdutoPreco.codigo == product_code,
                           ProdutoPreco.ativo == True)
                ).first()
                # Fallback: tenta com prefixo compliance_
                if not _pp:
                    _pp = _s3.exec(
                        select(ProdutoPreco)
                        .where(ProdutoPreco.company_id == company_id,
                               ProdutoPreco.codigo == f"compliance_{product_code}",
                               ProdutoPreco.ativo == True)
                    ).first()
                if _pp and _pp.creditos > 0:
                    return _pp.creditos * 100
        except Exception:
            pass
    markup = max(50, int(markup_pct or 50))
    return int(_math_cr2.ceil(cost_cents * (1.0 + markup / 100.0)))

# Sobrescreve função global
_price_cents = _price_cents_v3
globals()['_price_cents'] = _price_cents_v3
print("[construrisk_v2] ✅ _price_cents atualizado para usar ProdutoPreco")


# ── Fix 2: Análise IA melhorada — separa Crédito e PLD ───────────────────────

def _gerar_parecer_ia_v2(resultado: dict, person_type: str) -> str:
    """
    Gera parecer de risco com Claude separando análise de Crédito e PLD.
    Substitui a função original que gerava um parecer genérico único.
    """
    api_key = _os_cr2.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        return ""

    summary = resultado.get("summary", {})
    details = resultado.get("details", [])

    # Separa alertas por categoria
    alertas_credito = []
    alertas_pld     = []
    alertas_outros  = []

    _CREDITO_KEYWORDS = {
        "score", "scr", "crédito", "credito", "serasa", "spc", "divida",
        "dívida", "inadimplencia", "inadimplência", "pendencia", "pendência",
        "protesto", "cheque", "ccf", "negativacao", "negativação", "renda",
        "comprometimento", "capacidade", "pagamento", "financiamento",
    }
    _PLD_KEYWORDS = {
        "pep", "pld", "lavagem", "sanção", "sancao", "ofac", "bacen",
        "coaf", "cvm", "suspeito", "suspeita", "enquadramento", "risco",
        "compliance", "regulatorio", "regulatório", "político", "politico",
        "exposição", "exposicao", "cpf irregular", "cnpj irregular",
        "fraude", "sócio", "socio", "quadro societário",
    }

    for d in details:
        nome_api = (d.get("nameAPI") or d.get("moduleName") or "").lower()
        for a in (d.get("alertList") or []):
            rt = a.get("resultType", {})
            resultado_alerta = rt.get("result", "Regular") or "Regular"
            if resultado_alerta == "Regular":
                continue

            campo = (a.get("fieldName") or "").lower()
            valor = a.get("value", "")
            linha = f"• [{d.get('nameAPI','')}] {a.get('fieldName','')}: {valor} → {resultado_alerta}"

            # Classifica por categoria
            texto_busca = f"{nome_api} {campo}"
            if any(k in texto_busca for k in _PLD_KEYWORDS):
                alertas_pld.append(linha)
            elif any(k in texto_busca for k in _CREDITO_KEYWORDS):
                alertas_credito.append(linha)
            else:
                alertas_outros.append(linha)

    nome     = summary.get("name", "")
    doc      = summary.get("document", "")
    status   = summary.get("status", "")
    template = summary.get("templateName", "")

    prompt = f"""Você é um especialista em análise de risco imobiliário com foco em compliance e crédito.

Analise o dossiê ConstruRisk de {person_type} e emita um parecer estruturado em DUAS seções separadas.

DADOS DO DOSSIÊ:
- Nome: {nome}
- Documento: {doc}
- Status geral: {status}
- Template: {template}

ALERTAS DE CRÉDITO:
{chr(10).join(alertas_credito) if alertas_credito else "Nenhum alerta de crédito identificado."}

ALERTAS DE PLD/COMPLIANCE:
{chr(10).join(alertas_pld) if alertas_pld else "Nenhum alerta de PLD/Compliance identificado."}

OUTROS ALERTAS:
{chr(10).join(alertas_outros) if alertas_outros else "Nenhum outro alerta."}

Emita um parecer com EXATAMENTE esta estrutura:

## ANÁLISE DE CRÉDITO
**Classificação:** [Baixo / Médio / Alto / Crítico]
**Resumo:** [2-3 linhas sobre capacidade de pagamento e histórico de crédito]
**Pontos de atenção:** [lista dos alertas relevantes de crédito]
**Recomendação:** [Aprovado / Aprovado com ressalvas / Reprovado para financiamento]

## ANÁLISE PLD/COMPLIANCE
**Classificação:** [Baixo / Médio / Alto / Crítico]
**Resumo:** [2-3 linhas sobre exposição política, lavagem de dinheiro e compliance]
**Pontos de atenção:** [lista dos alertas relevantes de PLD]
**Recomendação:** [Aprovado / Aprovado com ressalvas / Reprovado para a transação]

## PARECER FINAL
**Risco consolidado:** [Baixo / Médio / Alto / Crítico]
**Conclusão:** [1-2 linhas sobre a viabilidade geral da transação]

Seja objetivo e direto. Máximo 400 palavras no total."""

    try:
        resp = _req_cr2.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": "claude-sonnet-4-6",
                "max_tokens": 1000,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()["content"][0]["text"]
    except Exception as e:
        print(f"[construrisk_v2] Erro parecer IA: {e}")
        return ""

# Substitui função original no escopo global
globals()['_gerar_parecer_ia'] = _gerar_parecer_ia_v2
print("[construrisk_v2] ✅ _gerar_parecer_ia substituída (Crédito + PLD separados)")


# ── Fix 3: Template resultado melhorado com parecer separado em seções ────────

TEMPLATES["construrisk_resultado.html"] = r"""
{% extends "base.html" %}
{% block content %}
<style>
  .cr-section{border:1px solid var(--mc-border);border-radius:12px;padding:1rem 1.25rem;background:#fff;margin-bottom:1rem;}
  .cr-badge-regular{background:rgba(22,163,74,.12);color:#166534;padding:.25rem .65rem;border-radius:999px;font-size:.75rem;font-weight:700;}
  .cr-badge-atencao{background:rgba(202,138,4,.12);color:#854d0e;padding:.25rem .65rem;border-radius:999px;font-size:.75rem;font-weight:700;}
  .cr-badge-alerta{background:rgba(220,38,38,.12);color:#991b1b;padding:.25rem .65rem;border-radius:999px;font-size:.75rem;font-weight:700;}
  .cr-badge-inconclusiva{background:#f3f4f6;color:#6b7280;padding:.25rem .65rem;border-radius:999px;font-size:.75rem;font-weight:700;}
  .cr-api{border:1px solid var(--mc-border);border-radius:10px;padding:.75rem 1rem;margin-bottom:.5rem;}
  .cr-api-nome{font-weight:600;font-size:.88rem;margin-bottom:.3rem;}
  .cr-alerta{font-size:.78rem;padding:.2rem .5rem;border-radius:6px;margin:.2rem 0;display:inline-block;}
  .cr-alerta.Regular{background:rgba(22,163,74,.08);color:#166534;}
  .cr-alerta.Atenção,.cr-alerta.Atencao{background:rgba(202,138,4,.08);color:#854d0e;}
  .cr-alerta.Alerta{background:rgba(220,38,38,.08);color:#991b1b;}
  .cr-parecer{background:#f8fafc;border:1px solid var(--mc-border);border-radius:12px;padding:1rem 1.25rem;font-size:.85rem;line-height:1.7;}
  .cr-parecer h2{font-size:.95rem;font-weight:700;margin-top:1rem;margin-bottom:.4rem;color:var(--mc-text);}
  .cr-parecer strong{color:var(--mc-text);}
  .cr-secao-credito{border-left:3px solid #3b82f6;padding-left:.75rem;margin-bottom:1rem;}
  .cr-secao-pld{border-left:3px solid #f59e0b;padding-left:.75rem;margin-bottom:1rem;}
  .cr-secao-final{border-left:3px solid #10b981;padding-left:.75rem;}
  @media print{.no-print{display:none!important;}}
</style>

<div class="d-flex justify-content-between align-items-start flex-wrap gap-3 mb-3 no-print">
  <div>
    <a href="/construrisk" class="btn btn-outline-secondary btn-sm mb-2">← Voltar</a>
    <h4 class="mb-0">Resultado ConstruRisk</h4>
    <div class="muted small">{{ dossie.person_type }} · {{ dossie.document }} · {{ dossie.created_at[:10] if dossie.created_at else '' }}</div>
  </div>
  <div class="d-flex gap-2 no-print">
    <a href="/construrisk/{{ dossie.id }}/pdf" class="btn btn-outline-secondary btn-sm" target="_blank">
      📄 Baixar PDF
    </a>
    <button class="btn btn-outline-secondary btn-sm" onclick="window.print()">
      🖨️ Imprimir
    </button>
  </div>
</div>

{# Resumo #}
{% if summary %}
<div class="cr-section">
  <div class="d-flex justify-content-between align-items-start flex-wrap gap-2">
    <div>
      <div class="fw-bold fs-5">{{ summary.name or dossie.nome }}</div>
      <div class="muted small">{{ summary.document or dossie.document }}</div>
      {% if summary.templateName %}
      <div class="muted small">Template: {{ summary.templateName }}</div>
      {% endif %}
    </div>
    <div>
      {% set st = summary.status or '' %}
      <span class="cr-badge-{{ st.lower().replace('atenção','atencao').replace('ã','a') if st else 'inconclusiva' }}">
        {{ st or 'Processando' }}
      </span>
    </div>
  </div>
</div>
{% endif %}

{# Parecer IA com seções #}
{% if dossie.parecer_ia %}
<div class="cr-section">
  <h6 class="mb-3">🤖 Parecer de Risco — Augur</h6>
  <div class="cr-parecer" id="crParecer">
    {{ dossie.parecer_ia | replace('## ANÁLISE DE CRÉDITO', '<div class="cr-secao-credito"><h2>💳 Análise de Crédito</h2>') | replace('## ANÁLISE PLD/COMPLIANCE', '</div><div class="cr-secao-pld"><h2>🔍 Análise PLD/Compliance</h2>') | replace('## PARECER FINAL', '</div><div class="cr-secao-final"><h2>✅ Parecer Final</h2>') | replace('**', '<strong>') | safe }}
    </div>
  </div>
</div>
{% endif %}

{# APIs / Módulos #}
{% if details %}
<h6 class="mb-2">Detalhes por módulo</h6>
{% for d in details %}
<div class="cr-api">
  <div class="cr-api-nome">{{ d.nameAPI or d.moduleName }}</div>
  {% if d.alertList %}
  <div class="d-flex flex-wrap gap-1">
    {% for a in d.alertList %}
    {% set res = a.resultType.result if a.resultType else 'Regular' %}
    <span class="cr-alerta {{ res }}">
      {{ a.fieldName }}: {{ a.value }} → {{ res }}
    </span>
    {% endfor %}
  </div>
  {% else %}
  <div class="muted small">Sem alertas</div>
  {% endif %}
</div>
{% endfor %}
{% endif %}

{% endblock %}
"""

if hasattr(templates_env.loader, "mapping"):
    templates_env.loader.mapping = TEMPLATES

print("[construrisk_v2] ✅ Template resultado atualizado com seções Crédito/PLD")
print("[construrisk_v2] ✅ Patch completo carregado")

# ============================================================================
# PATCH — Fix template ConstruRisk resultado
# ============================================================================
# Corrige o template construrisk_resultado.html que estava quebrando o sistema
# Remove o replace() encadeado de Jinja2 que causava erro de renderização
# DEPLOY: adicione ao final do app.py
# ============================================================================

TEMPLATES["construrisk_resultado.html"] = """
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
  .cr-alerta.Atencao{background:rgba(202,138,4,.08);color:#854d0e;}
  .cr-alerta.Alerta{background:rgba(220,38,38,.08);color:#991b1b;}
  .cr-parecer{background:#f8fafc;border:1px solid var(--mc-border);border-radius:12px;padding:1rem 1.25rem;font-size:.85rem;line-height:1.7;white-space:pre-wrap;}
  .cr-secao{border-left:3px solid #3b82f6;padding-left:.75rem;margin-bottom:1rem;}
  .cr-secao.pld{border-left-color:#f59e0b;}
  .cr-secao.final{border-left-color:#10b981;}
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
      {% if st.lower() in ('regular', 'aprovado') %}
        <span class="cr-badge-regular">{{ st }}</span>
      {% elif 'aten' in st.lower() %}
        <span class="cr-badge-atencao">{{ st }}</span>
      {% elif st.lower() in ('alerta', 'reprovado', 'critico', 'crítico') %}
        <span class="cr-badge-alerta">{{ st }}</span>
      {% else %}
        <span class="cr-badge-inconclusiva">{{ st or 'Processando' }}</span>
      {% endif %}
    </div>
  </div>
</div>
{% endif %}

{% if dossie.parecer_ia %}
<div class="cr-section">
  <h6 class="mb-3">🤖 Parecer de Risco — Augur</h6>
  {% set linhas = dossie.parecer_ia.split('\\n') %}
  {% set secao_atual = '' %}
  {% for linha in linhas %}
    {% if '## ANÁLISE DE CRÉDITO' in linha or '## ANALISE DE CREDITO' in linha %}
      {% if secao_atual %}</div>{% endif %}
      {% set secao_atual = 'credito' %}
      <div class="cr-secao">
      <strong>💳 Análise de Crédito</strong>
    {% elif '## ANÁLISE PLD' in linha or '## ANALISE PLD' in linha %}
      {% if secao_atual %}</div>{% endif %}
      {% set secao_atual = 'pld' %}
      <div class="cr-secao pld">
      <strong>🔍 Análise PLD/Compliance</strong>
    {% elif '## PARECER FINAL' in linha %}
      {% if secao_atual %}</div>{% endif %}
      {% set secao_atual = 'final' %}
      <div class="cr-secao final">
      <strong>✅ Parecer Final</strong>
    {% else %}
      <div class="cr-parecer" style="border:none;padding:.25rem 0;background:transparent;">{{ linha }}</div>
    {% endif %}
  {% endfor %}
  {% if secao_atual %}</div>{% endif %}
</div>
{% endif %}

{% if details %}
<h6 class="mb-2">Detalhes por módulo</h6>
{% for d in details %}
<div class="cr-api">
  <div class="cr-api-nome">{{ d.nameAPI or d.moduleName }}</div>
  {% if d.alertList %}
  <div class="d-flex flex-wrap gap-1">
    {% for a in d.alertList %}
    {% set res = a.resultType.result if a.resultType else 'Regular' %}
    {% set res_class = 'Atencao' if 'ten' in res else res %}
    <span class="cr-alerta {{ res_class }}">
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

print("[fix_construrisk_template] ✅ Template resultado corrigido")

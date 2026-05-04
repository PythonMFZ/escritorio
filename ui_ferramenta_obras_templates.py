# ============================================================================
# PATCH — Ferramenta: Gestão de Obras (Parte 2 — Templates)
# ============================================================================
# Salve como ui_ferramenta_obras_templates.py e adicione ao final do app.py:
#   exec(open('ui_ferramenta_obras_templates.py').read())
# IMPORTANTE: carregar DEPOIS de ui_ferramenta_obras.py
# ============================================================================

# ── Template: lista de obras ─────────────────────────────────────────────────

TEMPLATES["ferramenta_obras_lista.html"] = r"""
{% extends "base.html" %}
{% block content %}
<style>
  .ob-card{border:1px solid var(--mc-border);border-radius:14px;padding:1.1rem 1.25rem;background:#fff;margin-bottom:.75rem;transition:box-shadow .15s;}
  .ob-card:hover{box-shadow:0 2px 12px rgba(0,0,0,.07);}
  .ob-nome{font-weight:700;font-size:1rem;margin-bottom:.2rem;}
  .ob-meta{font-size:.75rem;color:var(--mc-muted);margin-bottom:.75rem;}
  .ob-kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(110px,1fr));gap:.5rem;margin-bottom:.75rem;}
  .ob-kpi{background:#f9fafb;border-radius:10px;padding:.5rem .7rem;}
  .ob-kpi-l{font-size:.65rem;font-weight:700;text-transform:uppercase;color:var(--mc-muted);}
  .ob-kpi-v{font-size:.9rem;font-weight:700;margin-top:.1rem;}
  .ob-bar-wrap{background:#f3f4f6;border-radius:999px;height:8px;margin:.3rem 0;overflow:hidden;}
  .ob-bar{height:100%;border-radius:999px;transition:width .5s;}
  .ob-bar.fisico{background:var(--mc-primary);}
  .ob-bar.financeiro{background:#3b82f6;}
  .ob-status{font-size:.7rem;font-weight:700;padding:.2rem .6rem;border-radius:999px;}
  .ob-status.em_andamento{background:rgba(59,130,246,.12);color:#1e40af;}
  .ob-status.concluida{background:rgba(22,163,74,.12);color:#166534;}
  .ob-status.paralisada{background:rgba(220,38,38,.12);color:#991b1b;}
  .idc-ok{color:#16a34a;} .idc-warn{color:#ca8a04;} .idc-bad{color:#dc2626;}
</style>

<div class="d-flex justify-content-between align-items-center flex-wrap gap-3 mb-3">
  <div>
    <a href="/ferramentas" class="btn btn-outline-secondary btn-sm mb-2"><i class="bi bi-arrow-left"></i> Ferramentas</a>
    <h4 class="mb-0">Gestão de Obras</h4>
    <div class="muted small">{% if current_client %}{{ current_client.name }}{% endif %}</div>
  </div>
  <a href="/ferramentas/obras/nova" class="btn btn-primary"><i class="bi bi-plus-circle me-1"></i> Nova Obra</a>
</div>

{% if not obras %}
  <div class="card p-4 text-center">
    <div style="font-size:2.5rem;margin-bottom:.75rem;">🏗️</div>
    <h5>Nenhuma obra cadastrada</h5>
    <div class="muted mb-3">Crie a primeira obra para começar o cronograma físico-financeiro.</div>
    <a href="/ferramentas/obras/nova" class="btn btn-primary">Criar primeira obra</a>
  </div>
{% else %}
  {% for item in obras %}
  {% set o = item.obra %}
  {% set c = item.calc %}
  <div class="ob-card">
    <div class="d-flex justify-content-between align-items-start gap-2 flex-wrap mb-1">
      <div>
        <div class="ob-nome">{{ o.nome }}</div>
        <div class="ob-meta">
          <span class="ob-status {{ o.status }}">{{ o.status.replace('_',' ').title() }}</span>
          {% if o.data_inicio %}<span class="ms-2">Início: {{ o.data_inicio }}</span>{% endif %}
          {% if o.data_fim %}<span class="ms-2">Previsão: {{ o.data_fim }}</span>{% endif %}
          {% if o.endereco %}<span class="ms-2">· {{ o.endereco }}</span>{% endif %}
        </div>
      </div>
      <div class="d-flex gap-2">
        <a href="/ferramentas/obras/{{ o.id }}" class="btn btn-sm btn-primary">Abrir</a>
        <a href="/ferramentas/obras/{{ o.id }}/editar" class="btn btn-sm btn-outline-secondary"><i class="bi bi-pencil"></i></a>
        <a href="/ferramentas/obras/{{ o.id }}/apagar" class="btn btn-sm btn-outline-danger"
           onclick="return confirm('Apagar esta obra e todo seu histórico?')"><i class="bi bi-trash"></i></a>
      </div>
    </div>

    <div class="ob-kpis">
      <div class="ob-kpi">
        <div class="ob-kpi-l">Orçamento</div>
        <div class="ob-kpi-v">{{ c.orcado_total|brl }}</div>
      </div>
      <div class="ob-kpi">
        <div class="ob-kpi-l">Realizado</div>
        <div class="ob-kpi-v">{{ c.realizado_rs|brl }}</div>
      </div>
      <div class="ob-kpi">
        <div class="ob-kpi-l">A Incorrer</div>
        <div class="ob-kpi-v">{{ c.a_incorrer|brl }}</div>
      </div>
      <div class="ob-kpi">
        <div class="ob-kpi-l">IDC</div>
        <div class="ob-kpi-v {{ 'idc-ok' if c.idc >= 0.95 else ('idc-warn' if c.idc >= 0.8 else 'idc-bad') }}">
          {{ "%.3f"|format(c.idc) }}
        </div>
      </div>
      <div class="ob-kpi">
        <div class="ob-kpi-l">Projeção Final</div>
        <div class="ob-kpi-v">{{ c.projecao_final|brl }}</div>
      </div>
    </div>

    <div class="d-flex gap-4 align-items-center" style="font-size:.78rem;">
      <div style="flex:1;">
        <div class="d-flex justify-content-between mb-1"><span style="color:var(--mc-primary);font-weight:600;">Físico</span><span>{{ c.fisico_geral }}%</span></div>
        <div class="ob-bar-wrap"><div class="ob-bar fisico" style="width:{{ c.fisico_geral }}%;"></div></div>
      </div>
      <div style="flex:1;">
        <div class="d-flex justify-content-between mb-1"><span style="color:#3b82f6;font-weight:600;">Financeiro</span><span>{{ ((c.realizado_rs / c.orcado_total * 100)|round(1)) if c.orcado_total > 0 else 0 }}%</span></div>
        <div class="ob-bar-wrap"><div class="ob-bar financeiro" style="width:{{ ((c.realizado_rs / c.orcado_total * 100)|round(1)) if c.orcado_total > 0 else 0 }}%;"></div></div>
      </div>
    </div>
  </div>
  {% endfor %}
{% endif %}
{% endblock %}
"""


# ── Template: form nova/editar obra ──────────────────────────────────────────

TEMPLATES["ferramenta_obras_form.html"] = r"""
{% extends "base.html" %}
{% block content %}
<a href="/ferramentas/obras" class="btn btn-outline-secondary btn-sm mb-3"><i class="bi bi-arrow-left"></i> Voltar</a>
<div class="card p-4">
  <h5 class="mb-3">{{ 'Editar Obra' if obra else 'Nova Obra' }}</h5>
  <form method="post">
    <div class="row g-3">
      <div class="col-md-8">
        <label class="form-label fw-semibold small">Nome da Obra</label>
        <input class="form-control" name="nome" required placeholder="Ex: Edifício Passione" value="{{ obra.nome if obra else '' }}">
      </div>
      <div class="col-md-4">
        <label class="form-label fw-semibold small">Status</label>
        <select class="form-select" name="status">
          <option value="em_andamento" {% if not obra or obra.status=='em_andamento' %}selected{% endif %}>Em andamento</option>
          <option value="concluida" {% if obra and obra.status=='concluida' %}selected{% endif %}>Concluída</option>
          <option value="paralisada" {% if obra and obra.status=='paralisada' %}selected{% endif %}>Paralisada</option>
        </select>
      </div>
      <div class="col-12">
        <label class="form-label fw-semibold small">Endereço</label>
        <input class="form-control" name="endereco" placeholder="Rua, número, bairro, cidade" value="{{ obra.endereco if obra else '' }}">
      </div>
      <div class="col-md-3">
        <label class="form-label fw-semibold small">Área construída (m²)</label>
        <input class="form-control" name="area_m2" type="number" step="0.01" min="0" placeholder="2.500" value="{{ obra.area_m2 if obra else '' }}">
      </div>
      <div class="col-md-3">
        <label class="form-label fw-semibold small">CUB (R$/m²)</label>
        <input class="form-control" name="cub_m2" type="number" step="1" min="0" placeholder="3.019" value="{{ obra.cub_m2 if obra else '3019' }}">
      </div>
      <div class="col-md-3">
        <label class="form-label fw-semibold small">Orçamento Total (R$)</label>
        <input class="form-control" name="orcamento_total" type="number" step="1000" min="0"
               placeholder="2.634.253" value="{{ obra.orcamento_total if obra else '' }}"
               id="orcTotal">
        <div class="form-text">Deixe 0 para calcular pela soma das etapas</div>
      </div>
      <div class="col-md-3">
        <label class="form-label fw-semibold small">&nbsp;</label>
        <button type="button" class="btn btn-outline-secondary w-100" onclick="calcOrc()">
          <i class="bi bi-calculator me-1"></i> Calcular pelo CUB
        </button>
      </div>
      <div class="col-md-6">
        <label class="form-label fw-semibold small">Data de Início</label>
        <input class="form-control" name="data_inicio" type="date" value="{{ obra.data_inicio if obra else '' }}">
      </div>
      <div class="col-md-6">
        <label class="form-label fw-semibold small">Data de Término Prevista</label>
        <input class="form-control" name="data_fim" type="date" value="{{ obra.data_fim if obra else '' }}">
      </div>
      <div class="col-12">
        <label class="form-label fw-semibold small">Observações</label>
        <textarea class="form-control" name="obs" rows="2">{{ obra.obs if obra else '' }}</textarea>
      </div>
      {% if not obra %}
      <div class="col-12">
        <div class="form-check">
          <input class="form-check-input" type="checkbox" name="usar_modelo" value="1" id="usarModelo" checked>
          <label class="form-check-label" for="usarModelo">
            <strong>Criar fases do modelo base</strong>
            <span class="text-muted">({{ fases_base|length }} fases padrão — você pode editar depois)</span>
          </label>
        </div>
        <div class="mt-2 ms-4" style="font-size:.8rem;color:var(--mc-muted);">
          {% for f in fases_base %}{{ f.nome }}{% if not loop.last %} · {% endif %}{% endfor %}
        </div>
      </div>
      {% endif %}
    </div>
    <div class="d-flex gap-2 mt-4">
      <button type="submit" class="btn btn-primary">{{ 'Salvar alterações' if obra else 'Criar obra' }}</button>
      <a href="/ferramentas/obras" class="btn btn-outline-secondary">Cancelar</a>
    </div>
  </form>
</div>
<script>
function calcOrc() {
  const area = parseFloat(document.querySelector('[name=area_m2]').value || 0);
  const cub  = parseFloat(document.querySelector('[name=cub_m2]').value || 3019);
  if (area > 0) document.getElementById('orcTotal').value = Math.round(area * cub);
}
</script>
{% endblock %}
"""


# ── Template: cronograma da obra ─────────────────────────────────────────────

TEMPLATES["ferramenta_obras_cronograma.html"] = r"""
{% extends "base.html" %}
{% block content %}
<style>
  .cr-hdr{display:flex;justify-content:space-between;align-items:flex-start;flex-wrap:wrap;gap:1rem;margin-bottom:1.25rem;}
  .cr-kpi-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:.6rem;margin-bottom:1.25rem;}
  .cr-kpi{background:#fff;border:1px solid var(--mc-border);border-radius:12px;padding:.8rem 1rem;}
  .cr-kpi-l{font-size:.65rem;font-weight:700;text-transform:uppercase;letter-spacing:.06em;color:var(--mc-muted);}
  .cr-kpi-v{font-size:1.1rem;font-weight:700;margin-top:.15rem;}
  .cr-kpi-f{font-size:.7rem;color:var(--mc-muted);margin-top:.1rem;}
  /* Barras duplas */
  .cr-bars{margin-bottom:1rem;}
  .cr-bar-row{display:flex;align-items:center;gap:.75rem;margin-bottom:.4rem;font-size:.78rem;}
  .cr-bar-lbl{width:80px;text-align:right;font-weight:600;}
  .cr-bar-wrap{flex:1;background:#f3f4f6;border-radius:999px;height:10px;overflow:hidden;}
  .cr-bar{height:100%;border-radius:999px;}
  .cr-bar.fis{background:var(--mc-primary);}
  .cr-bar.fin{background:#3b82f6;}
  .cr-bar-val{width:50px;font-weight:600;}
  /* Tabela */
  .cr-fase-hdr{background:#f9fafb;border:1px solid var(--mc-border);border-radius:10px;padding:.55rem .85rem;font-weight:700;font-size:.85rem;display:flex;justify-content:space-between;align-items:center;margin-bottom:.3rem;cursor:pointer;}
  .cr-fase-body{margin-bottom:.75rem;}
  .cr-etapa{display:grid;grid-template-columns:2fr 1fr 1fr 1fr 1fr 1fr auto;gap:.5rem;align-items:center;padding:.45rem .85rem;border:1px solid var(--mc-border);border-radius:8px;margin-bottom:.25rem;font-size:.82rem;background:#fff;}
  .cr-etapa:hover{background:#fafafa;}
  .cr-etapa-hdr{display:grid;grid-template-columns:2fr 1fr 1fr 1fr 1fr 1fr auto;gap:.5rem;padding:.3rem .85rem;font-size:.68rem;font-weight:700;text-transform:uppercase;color:var(--mc-muted);margin-bottom:.2rem;}
  .bar-sm{background:#f3f4f6;border-radius:999px;height:5px;margin-top:3px;overflow:hidden;}
  .bar-sm-inner{height:100%;border-radius:999px;}
  .desvio-pos{color:#dc2626;} .desvio-neg{color:#16a34a;} .desvio-zero{color:var(--mc-muted);}
  .idc-ok{color:#16a34a;font-weight:700;} .idc-warn{color:#ca8a04;font-weight:700;} .idc-bad{color:#dc2626;font-weight:700;}
  /* Modal */
  .modal-overlay{position:fixed;inset:0;background:rgba(0,0,0,.4);z-index:1000;display:flex;align-items:center;justify-content:center;padding:1rem;}
  .modal-box{background:#fff;border-radius:16px;padding:1.5rem;width:100%;max-width:480px;max-height:90vh;overflow-y:auto;}
  .modal-box h6{font-weight:700;margin-bottom:1rem;}
  @media(max-width:640px){.cr-etapa,.cr-etapa-hdr{grid-template-columns:2fr 1fr 1fr auto;}.cr-etapa>*:nth-child(4),.cr-etapa>*:nth-child(5),.cr-etapa-hdr>*:nth-child(4),.cr-etapa-hdr>*:nth-child(5){display:none;}}
  @media print{.no-print{display:none!important;}}
</style>

<div class="cr-hdr">
  <div>
    <a href="/ferramentas/obras" class="btn btn-outline-secondary btn-sm mb-2 no-print"><i class="bi bi-arrow-left"></i> Obras</a>
    <h4 class="mb-0">{{ obra.nome }}</h4>
    <div class="muted small">
      {% if obra.endereco %}{{ obra.endereco }} · {% endif %}
      {% if obra.data_inicio %}Início: {{ obra.data_inicio }}{% endif %}
      {% if obra.data_fim %} · Previsão: {{ obra.data_fim }}{% endif %}
    </div>
  </div>
  <div class="d-flex gap-2 flex-wrap no-print">
    <button onclick="abrirNovaFase()" class="btn btn-outline-secondary btn-sm"><i class="bi bi-plus me-1"></i> Fase</button>
    <a href="/ferramentas/obras/{{ obra.id }}/editar" class="btn btn-outline-secondary btn-sm"><i class="bi bi-pencil me-1"></i> Editar</a>
    <button onclick="window.print()" class="btn btn-outline-secondary btn-sm"><i class="bi bi-printer me-1"></i> PDF</button>
  </div>
</div>

{# KPIs #}
<div class="cr-kpi-grid">
  <div class="cr-kpi">
    <div class="cr-kpi-l">Orçamento Total</div>
    <div class="cr-kpi-v">{{ calc.orcado_total|brl }}</div>
    <div class="cr-kpi-f">{{ calc.n_etapas }} etapas · {{ calc.n_fases }} fases</div>
  </div>
  <div class="cr-kpi">
    <div class="cr-kpi-l">Realizado</div>
    <div class="cr-kpi-v" style="color:#3b82f6;">{{ calc.realizado_rs|brl }}</div>
    <div class="cr-kpi-f">{{ ((calc.realizado_rs/calc.orcado_total*100)|round(1)) if calc.orcado_total > 0 else 0 }}% do orçado</div>
  </div>
  <div class="cr-kpi">
    <div class="cr-kpi-l">A Incorrer</div>
    <div class="cr-kpi-v">{{ calc.a_incorrer|brl }}</div>
    <div class="cr-kpi-f">Saldo orçado</div>
  </div>
  <div class="cr-kpi">
    <div class="cr-kpi-l">Desvio de Custo</div>
    <div class="cr-kpi-v {{ 'desvio-pos' if calc.desvio_geral > 0 else ('desvio-neg' if calc.desvio_geral < 0 else 'desvio-zero') }}">
      {{ calc.desvio_geral|brl }}
    </div>
    <div class="cr-kpi-f">{{ 'Acima do esperado' if calc.desvio_geral > 0 else ('Abaixo do esperado' if calc.desvio_geral < 0 else 'No esperado') }}</div>
  </div>
  <div class="cr-kpi">
    <div class="cr-kpi-l">IDC</div>
    <div class="cr-kpi-v {{ 'idc-ok' if calc.idc >= 0.95 else ('idc-warn' if calc.idc >= 0.8 else 'idc-bad') }}">
      {{ "%.3f"|format(calc.idc) }}
    </div>
    <div class="cr-kpi-f">{{ '≥ 1 = dentro do orçado' if calc.idc >= 1 else '< 1 = acima do orçado' }}</div>
  </div>
  <div class="cr-kpi">
    <div class="cr-kpi-l">Projeção Final</div>
    <div class="cr-kpi-v" style="color:{{ '#dc2626' if calc.projecao_final > calc.orcado_total else '#16a34a' }};">
      {{ calc.projecao_final|brl }}
    </div>
    <div class="cr-kpi-f">Se o IDC atual continuar</div>
  </div>
</div>

{# Barras duplas #}
<div class="cr-bars card p-3 mb-3">
  <div class="cr-bar-row">
    <span class="cr-bar-lbl" style="color:var(--mc-primary);">Físico</span>
    <div class="cr-bar-wrap"><div class="cr-bar fis" style="width:{{ calc.fisico_geral }}%;"></div></div>
    <span class="cr-bar-val">{{ calc.fisico_geral }}%</span>
  </div>
  <div class="cr-bar-row">
    <span class="cr-bar-lbl" style="color:#3b82f6;">Financeiro</span>
    <div class="cr-bar-wrap"><div class="cr-bar fin" style="width:{{ ((calc.realizado_rs/calc.orcado_total*100)|round(1)) if calc.orcado_total > 0 else 0 }}%;"></div></div>
    <span class="cr-bar-val">{{ ((calc.realizado_rs/calc.orcado_total*100)|round(1)) if calc.orcado_total > 0 else 0 }}%</span>
  </div>
</div>

{# Cronograma por fase #}
{% for fase in calc.fases %}
<div class="cr-fase-hdr" onclick="toggleFase({{ fase.id }})">
  <div class="d-flex align-items-center gap-2">
    <i class="bi bi-chevron-down" id="icon-fase-{{ fase.id }}"></i>
    <span>{{ fase.nome }}</span>
    <span class="badge text-bg-light border ms-1">{{ fase.etapas|length }} etapas</span>
  </div>
  <div class="d-flex gap-3 align-items-center" style="font-size:.78rem;">
    <span style="color:var(--mc-primary);">Físico: {{ fase.fisico_pct }}%</span>
    <span style="color:#3b82f6;">{{ fase.realizado_rs|brl }} / {{ fase.orcado_rs|brl }}</span>
    {% if fase.desvio_rs != 0 %}
    <span class="{{ 'desvio-pos' if fase.desvio_rs > 0 else 'desvio-neg' }}">
      {{ '+' if fase.desvio_rs > 0 else '' }}{{ fase.desvio_rs|brl }}
    </span>
    {% endif %}
    <button class="btn btn-xs btn-outline-secondary no-print" style="padding:.1rem .4rem;font-size:.7rem;"
            onclick="event.stopPropagation();abrirNovaEtapa({{ fase.id }},'{{ fase.nome }}')">
      + Etapa
    </button>
    <button class="btn btn-xs btn-outline-secondary no-print" style="padding:.1rem .4rem;font-size:.7rem;"
            onclick="event.stopPropagation();editarFase({{ fase.id }},'{{ fase.nome }}',{{ fase.orcado_rs }})">
      <i class="bi bi-pencil"></i>
    </button>
    <button class="btn btn-xs btn-outline-danger no-print" style="padding:.1rem .4rem;font-size:.7rem;"
            onclick="event.stopPropagation();apagarFase({{ fase.id }},'{{ fase.nome }}')">
      <i class="bi bi-trash"></i>
    </button>
  </div>
</div>

<div class="cr-fase-body" id="fase-body-{{ fase.id }}">
  {% if fase.etapas %}
  <div class="cr-etapa-hdr">
    <span>Descrição / Insumo</span>
    <span>Orçado</span>
    <span>Realizado</span>
    <span>Físico</span>
    <span>Desvio</span>
    <span>A Incorrer</span>
    <span></span>
  </div>
  {% for e in fase.etapas %}
  <div class="cr-etapa" id="etapa-row-{{ e.id }}">
    <div>
      <div style="font-weight:600;">{{ e.descricao }}</div>
      {% if e.insumo %}<div style="font-size:.72rem;color:var(--mc-muted);">{{ e.insumo }}</div>{% endif %}
      {% if e.data_inicio or e.data_fim %}<div style="font-size:.7rem;color:var(--mc-muted);">{{ e.data_inicio }} → {{ e.data_fim }}</div>{% endif %}
      <div class="bar-sm"><div class="bar-sm-inner" style="width:{{ e.fisico_pct }}%;background:var(--mc-primary);"></div></div>
    </div>
    <div>{{ e.orcado_rs|brl }}</div>
    <div style="color:#3b82f6;">
      {{ e.financeiro_rs|brl }}
      {% if e.versao != '—' %}<div style="font-size:.68rem;color:var(--mc-muted);">{{ e.versao }} · {{ e.data_apt }}</div>{% endif %}
    </div>
    <div>
      <span style="font-weight:700;color:var(--mc-primary);">{{ e.fisico_pct }}%</span>
    </div>
    <div class="{{ 'desvio-pos' if e.desvio_rs > 0 else ('desvio-neg' if e.desvio_rs < 0 else 'desvio-zero') }}">
      {{ '+' if e.desvio_rs > 0 else '' }}{{ e.desvio_rs|brl }}
      {% if e.desvio_pct != 0 %}<div style="font-size:.68rem;">{{ '+' if e.desvio_pct > 0 else '' }}{{ e.desvio_pct }}%</div>{% endif %}
    </div>
    <div>{{ e.a_incorrer|brl }}</div>
    <div class="d-flex gap-1 no-print">
      <button class="btn btn-sm btn-outline-secondary"
              onclick="editarEtapa({{ e.id }},'{{ e.descricao }}','{{ e.insumo }}',{{ e.orcado_rs }},'{{ e.data_inicio }}','{{ e.data_fim }}')"
              title="Editar etapa">
        <i class="bi bi-pencil"></i>
      </button>
      <button class="btn btn-sm btn-primary" onclick="abrirApontamento({{ e.id }},'{{ e.descricao }}',{{ e.orcado_rs }},{{ e.fisico_pct }},{{ e.financeiro_rs }})"
              title="Apontar">
        <i class="bi bi-pencil-square"></i>
      </button>
      {% if e.historico %}
      <button class="btn btn-sm btn-outline-secondary" onclick="verHistorico({{ e.id }})" title="Histórico">
        <i class="bi bi-clock-history"></i>
      </button>
      {% endif %}
      <button class="btn btn-sm btn-outline-danger" onclick="apagarEtapa({{ e.id }},'{{ e.descricao }}')" title="Apagar">
        <i class="bi bi-trash"></i>
      </button>
    </div>
  </div>
  {% endfor %}
  {% else %}
  <div style="padding:.5rem .85rem;color:var(--mc-muted);font-size:.82rem;">
    Nenhuma etapa. <button class="btn btn-link btn-sm p-0" onclick="abrirNovaEtapa({{ fase.id }},'{{ fase.nome }}')">Adicionar primeira etapa</button>
  </div>
  {% endif %}
</div>
{% endfor %}

{# Modais #}
<div id="modalOverlay" class="modal-overlay" style="display:none;" onclick="fecharModal(event)">

  {# Modal: apontamento #}
  <div class="modal-box" id="modalApt" style="display:none;">
    <h6>📋 Apontamento</h6>
    <div id="aptNome" class="muted small mb-3"></div>
    <div class="mb-3">
      <label class="form-label fw-semibold small">% Físico Concluído</label>
      <div class="d-flex align-items-center gap-2">
        <input type="range" class="form-range flex-1" id="aptFisico" min="0" max="100" step="5" oninput="document.getElementById('aptFisicoVal').textContent=this.value+'%'">
        <span id="aptFisicoVal" style="width:40px;font-weight:700;color:var(--mc-primary);"></span>
      </div>
    </div>
    <div class="mb-3">
      <label class="form-label fw-semibold small">Valor Desembolsado (R$)</label>
      <input type="number" class="form-control" id="aptFinanceiro" step="100" min="0" placeholder="0">
      <div class="form-text" id="aptOrcadoRef"></div>
    </div>
    <div class="mb-3">
      <label class="form-label fw-semibold small">Data do Apontamento</label>
      <input type="date" class="form-control" id="aptData">
    </div>
    <div class="mb-3">
      <label class="form-label fw-semibold small">Observação</label>
      <textarea class="form-control" id="aptObs" rows="2" placeholder="Motivo de desvio, pendências, etc."></textarea>
    </div>
    <div class="d-flex gap-2">
      <button class="btn btn-primary flex-1" onclick="salvarApontamento()">Salvar Apontamento</button>
      <button class="btn btn-outline-secondary" onclick="fecharModal()">Cancelar</button>
    </div>
  </div>

  {# Modal: nova fase #}
  <div class="modal-box" id="modalFase" style="display:none;">
    <h6>➕ Nova Fase</h6>
    <div class="mb-3">
      <label class="form-label fw-semibold small">Nome da Fase</label>
      <input type="text" class="form-control" id="faseNome" placeholder="Ex: Instalações Hidráulicas">
    </div>
    <div class="d-flex gap-2">
      <button class="btn btn-primary flex-1" onclick="salvarFase()">Criar Fase</button>
      <button class="btn btn-outline-secondary" onclick="fecharModal()">Cancelar</button>
    </div>
  </div>

  {# Modal: nova etapa #}
  <div class="modal-box" id="modalEtapa" style="display:none;">
    <h6>➕ Nova Etapa</h6>
    <div class="muted small mb-3" id="etapaFaseNome"></div>
    <div class="mb-3">
      <label class="form-label fw-semibold small">Descrição</label>
      <input type="text" class="form-control" id="etapaDesc" placeholder="Ex: Concreto G1">
    </div>
    <div class="mb-3">
      <label class="form-label fw-semibold small">Insumo / Categoria</label>
      <select class="form-select" id="etapaInsumo">
        <option value="">— Selecione —</option>
        {% for ins in insumos %}<option value="{{ ins }}">{{ ins }}</option>{% endfor %}
      </select>
    </div>
    <div class="mb-3">
      <label class="form-label fw-semibold small">Valor Orçado (R$)</label>
      <input type="number" class="form-control" id="etapaOrcado" step="100" min="0" placeholder="0">
    </div>
    <div class="row g-2 mb-3">
      <div class="col">
        <label class="form-label fw-semibold small">Início</label>
        <input type="date" class="form-control" id="etapaIni">
      </div>
      <div class="col">
        <label class="form-label fw-semibold small">Término</label>
        <input type="date" class="form-control" id="etapaFim">
      </div>
    </div>
    <div class="d-flex gap-2">
      <button class="btn btn-primary flex-1" onclick="salvarEtapa()">Criar Etapa</button>
      <button class="btn btn-outline-secondary" onclick="fecharModal()">Cancelar</button>
    </div>
  </div>

  {# Modal: histórico #}
  <div class="modal-box" id="modalHistorico" style="display:none;">
    <h6>📅 Histórico de Apontamentos</h6>
    <div id="historicoContent"></div>
    <button class="btn btn-outline-secondary w-100 mt-3" onclick="fecharModal()">Fechar</button>
  </div>

</div>

<script>
const OBRA_ID = {{ obra.id }};
let _aptEtapaId = null;
let _etapaFaseId = null;
const HISTORICOS = {{ calc.fases | map(attribute='etapas') | sum(start=[]) | map(attribute='historico') | list | tojson }};
const ETAPA_IDS  = {{ calc.fases | map(attribute='etapas') | sum(start=[]) | map(attribute='id') | list | tojson }};

// ── Toggle fase ──
function toggleFase(id) {
  const body = document.getElementById('fase-body-' + id);
  const icon = document.getElementById('icon-fase-' + id);
  if (!body) return;
  const hidden = body.style.display === 'none';
  body.style.display = hidden ? '' : 'none';
  icon.className = hidden ? 'bi bi-chevron-down' : 'bi bi-chevron-right';
}

// ── Modais ──
function fecharModal(e) {
  if (e && e.target.id !== 'modalOverlay') return;
  document.getElementById('modalOverlay').style.display = 'none';
  ['modalApt','modalFase','modalEtapa','modalHistorico'].forEach(id => {
    document.getElementById(id).style.display = 'none';
  });
}
function abrirModal(id) {
  document.getElementById('modalOverlay').style.display = 'flex';
  document.getElementById(id).style.display = 'block';
}

// ── Apontamento ──
function abrirApontamento(etapaId, nome, orcado, fisicoAtual, financAtual) {
  _aptEtapaId = etapaId;
  document.getElementById('aptNome').textContent = nome;
  document.getElementById('aptFisico').value = fisicoAtual;
  document.getElementById('aptFisicoVal').textContent = fisicoAtual + '%';
  document.getElementById('aptFinanceiro').value = financAtual || '';
  document.getElementById('aptOrcadoRef').textContent = 'Orçado: R$ ' + orcado.toLocaleString('pt-BR', {minimumFractionDigits:2});
  document.getElementById('aptData').value = new Date().toISOString().slice(0,10);
  document.getElementById('aptObs').value = '';
  abrirModal('modalApt');
}
async function salvarApontamento() {
  const btn = event.target;
  btn.disabled = true; btn.textContent = 'Salvando...';
  const r = await fetch('/ferramentas/obras/etapa/' + _aptEtapaId + '/apontar', {
    method: 'POST', headers: {'Content-Type':'application/json'},
    body: JSON.stringify({
      fisico_pct: parseFloat(document.getElementById('aptFisico').value),
      financeiro_rs: parseFloat(document.getElementById('aptFinanceiro').value || 0),
      data: document.getElementById('aptData').value,
      obs: document.getElementById('aptObs').value,
    }),
  });
  const d = await r.json();
  if (d.ok) { fecharModal(); location.reload(); }
  else { btn.disabled = false; btn.textContent = 'Salvar Apontamento'; alert('Erro ao salvar.'); }
}

// ── Nova fase ──
function abrirNovaFase() { document.getElementById('faseNome').value = ''; abrirModal('modalFase'); }
async function salvarFase() {
  const nome = document.getElementById('faseNome').value.trim();
  if (!nome) return;
  const r = await fetch('/ferramentas/obras/' + OBRA_ID + '/fase/nova', {
    method: 'POST', headers: {'Content-Type':'application/json'},
    body: JSON.stringify({nome}),
  });
  const d = await r.json();
  if (d.ok) { fecharModal(); location.reload(); }
}

// ── Nova etapa ──
function abrirNovaEtapa(faseId, faseNome) {
  _etapaFaseId = faseId;
  document.getElementById('etapaFaseNome').textContent = 'Fase: ' + faseNome;
  document.getElementById('etapaDesc').value = '';
  document.getElementById('etapaInsumo').value = '';
  document.getElementById('etapaOrcado').value = '';
  document.getElementById('etapaIni').value = '';
  document.getElementById('etapaFim').value = '';
  abrirModal('modalEtapa');
}
async function salvarEtapa() {
  const r = await fetch('/ferramentas/obras/' + OBRA_ID + '/etapa/nova', {
    method: 'POST', headers: {'Content-Type':'application/json'},
    body: JSON.stringify({
      fase_id: _etapaFaseId,
      descricao: document.getElementById('etapaDesc').value,
      insumo: document.getElementById('etapaInsumo').value,
      orcado_rs: parseFloat(document.getElementById('etapaOrcado').value || 0),
      data_inicio: document.getElementById('etapaIni').value,
      data_fim: document.getElementById('etapaFim').value,
    }),
  });
  const d = await r.json();
  if (d.ok) { fecharModal(); location.reload(); }
}

// ── Histórico ──
function verHistorico(etapaId) {
  const idx = ETAPA_IDS.indexOf(etapaId);
  const hist = idx >= 0 ? HISTORICOS[idx] : [];
  let html = hist.length === 0 ? '<p class="text-muted">Sem apontamentos.</p>' : '';
  hist.forEach(h => {
    const cor = h.fisico >= 100 ? '#16a34a' : (h.fisico >= 50 ? '#ca8a04' : '#dc2626');
    html += `<div style="border:1px solid #e5e7eb;border-radius:10px;padding:.65rem .85rem;margin-bottom:.5rem;">
      <div style="display:flex;justify-content:space-between;align-items:center;">
        <span style="font-weight:700;">${h.versao}</span>
        <span style="font-size:.75rem;color:#6b7280;">${h.data}</span>
      </div>
      <div style="margin-top:.3rem;font-size:.82rem;">
        <span style="color:${cor};font-weight:600;">Físico: ${h.fisico}%</span>
        <span style="color:#3b82f6;margin-left:1rem;">Financeiro: R$ ${h.financeiro.toLocaleString('pt-BR',{minimumFractionDigits:2})}</span>
      </div>
      ${h.obs ? `<div style="font-size:.75rem;color:#6b7280;margin-top:.2rem;">${h.obs}</div>` : ''}
    </div>`;
  });
  document.getElementById('historicoContent').innerHTML = html;
  abrirModal('modalHistorico');
}

// ── Apagar ──
async function apagarEtapa(id, nome) {
  if (!confirm('Apagar etapa "' + nome + '" e todo seu histórico?')) return;
  const r = await fetch('/ferramentas/obras/etapa/' + id + '/apagar', {method:'POST'});
  const d = await r.json();
  if (d.ok) { const el = document.getElementById('etapa-row-' + id); if(el) el.remove(); }
}
async function apagarFase(id, nome) {
  if (!confirm('Apagar fase "' + nome + '" e todas suas etapas?')) return;
  const r = await fetch('/ferramentas/obras/fase/' + id + '/apagar', {method:'POST'});
  const d = await r.json();
  if (d.ok) location.reload();
}
</script>

{# ── Modal Editar Fase ── #}
<div class="modal fade" id="modalEditarFase" tabindex="-1">
  <div class="modal-dialog modal-dialog-centered">
    <div class="modal-content">
      <div class="modal-header"><h5 class="modal-title">Editar Fase</h5><button type="button" class="btn-close" data-bs-dismiss="modal"></button></div>
      <div class="modal-body">
        <input type="hidden" id="ef_id">
        <div class="mb-3"><label class="form-label fw-semibold">Nome da fase</label>
          <input type="text" class="form-control" id="ef_nome"></div>
        <div class="mb-3"><label class="form-label fw-semibold">Orçado (R$)</label>
          <input type="number" class="form-control" id="ef_orcado" step="0.01" min="0"></div>
        <div class="mb-3"><label class="form-label fw-semibold">Ordem</label>
          <input type="number" class="form-control" id="ef_ordem" min="0"></div>
      </div>
      <div class="modal-footer">
        <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Cancelar</button>
        <button type="button" class="btn btn-primary" onclick="salvarFase()">Salvar</button>
      </div>
    </div>
  </div>
</div>

{# ── Modal Editar Etapa ── #}
<div class="modal fade" id="modalEditarEtapa" tabindex="-1">
  <div class="modal-dialog modal-dialog-centered modal-lg">
    <div class="modal-content">
      <div class="modal-header"><h5 class="modal-title">Editar Etapa</h5><button type="button" class="btn-close" data-bs-dismiss="modal"></button></div>
      <div class="modal-body">
        <input type="hidden" id="ee_id">
        <div class="row g-3">
          <div class="col-md-8"><label class="form-label fw-semibold">Descrição</label>
            <input type="text" class="form-control" id="ee_descricao"></div>
          <div class="col-md-4"><label class="form-label fw-semibold">Insumo</label>
            <select class="form-select" id="ee_insumo">
              <option value="">— Selecione —</option>
              <option value="Concreto">Concreto</option>
              <option value="Aço">Aço</option>
              <option value="Empreitada">Empreitada</option>
              <option value="INSS">INSS</option>
              <option value="Diversos">Diversos</option>
            </select></div>
          <div class="col-md-4"><label class="form-label fw-semibold">Orçado (R$)</label>
            <input type="number" class="form-control" id="ee_orcado" step="0.01" min="0"></div>
          <div class="col-md-4"><label class="form-label fw-semibold">Data início</label>
            <input type="text" class="form-control" id="ee_inicio" placeholder="DD/MM/AAAA"></div>
          <div class="col-md-4"><label class="form-label fw-semibold">Data fim</label>
            <input type="text" class="form-control" id="ee_fim" placeholder="DD/MM/AAAA"></div>
        </div>
      </div>
      <div class="modal-footer">
        <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Cancelar</button>
        <button type="button" class="btn btn-primary" onclick="salvarEtapa()">Salvar</button>
      </div>
    </div>
  </div>
</div>

<script>
function editarFase(id, nome, orcado) {
  document.getElementById('ef_id').value = id;
  document.getElementById('ef_nome').value = nome;
  document.getElementById('ef_orcado').value = orcado;
  document.getElementById('ef_ordem').value = 0;
  new bootstrap.Modal(document.getElementById('modalEditarFase')).show();
}

async function salvarFase() {
  const id = document.getElementById('ef_id').value;
  const fd = new FormData();
  fd.append('nome', document.getElementById('ef_nome').value);
  fd.append('orcado_rs', document.getElementById('ef_orcado').value);
  fd.append('ordem', document.getElementById('ef_ordem').value);
  const r = await fetch('/ferramentas/obras/fase/' + id + '/editar', {method:'POST', body:fd});
  const d = await r.json();
  if (d.ok) { location.reload(); }
  else { alert('Erro ao salvar fase.'); }
}

function editarEtapa(id, descricao, insumo, orcado, inicio, fim) {
  document.getElementById('ee_id').value = id;
  document.getElementById('ee_descricao').value = descricao;
  document.getElementById('ee_insumo').value = insumo;
  document.getElementById('ee_orcado').value = orcado;
  document.getElementById('ee_inicio').value = inicio;
  document.getElementById('ee_fim').value = fim;
  new bootstrap.Modal(document.getElementById('modalEditarEtapa')).show();
}

async function salvarEtapa() {
  const id = document.getElementById('ee_id').value;
  const fd = new FormData();
  fd.append('descricao', document.getElementById('ee_descricao').value);
  fd.append('insumo', document.getElementById('ee_insumo').value);
  fd.append('orcado_rs', document.getElementById('ee_orcado').value);
  fd.append('data_inicio', document.getElementById('ee_inicio').value);
  fd.append('data_fim', document.getElementById('ee_fim').value);
  fd.append('ordem', 0);
  const r = await fetch('/ferramentas/obras/etapa/' + id + '/editar-completo', {method:'POST', body:fd});
  const d = await r.json();
  if (d.ok) { location.reload(); }
  else { alert('Erro ao salvar etapa.'); }
}
</script>

{% endblock %}
"""

if hasattr(templates_env.loader, "mapping"):
    templates_env.loader.mapping = TEMPLATES

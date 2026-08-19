# ============================================================================
# ui_sidebar.py — Barra lateral de navegação fixa (esquerda) v3
# ============================================================================

_SIDEBAR_CSS = r"""
<style id="sb-styles">
:root {
  --sb-w: 220px;
  --sb-w-col: 56px;
  --sb-bg: #0B1E1E;
  --sb-txt: rgba(255,255,255,.72);
  --sb-accent: #E07020;
  --sb-hover-bg: rgba(255,255,255,.07);
  --sb-active-bg: rgba(224,112,32,.14);
}

/* ── Sidebar container ──────────────────────────────────────────────────── */
#app-sidebar {
  position: fixed; top: 0; left: 0; height: 100vh; width: var(--sb-w);
  background: var(--sb-bg); z-index: 1040;
  display: flex; flex-direction: column;
  overflow-y: auto; overflow-x: hidden;
  transition: width .22s cubic-bezier(.4,0,.2,1),
              transform .24s cubic-bezier(.4,0,.2,1);
  scrollbar-width: thin; scrollbar-color: rgba(255,255,255,.1) transparent;
}
#app-sidebar::-webkit-scrollbar { width: 3px; }
#app-sidebar::-webkit-scrollbar-thumb { background: rgba(255,255,255,.1); border-radius: 2px; }

/* ── Logo block ──────────────────────────────────────────────────────────── */
.sb-logo {
  padding: 13px 10px 11px;
  border-bottom: 1px solid rgba(255,255,255,.08);
  display: flex; align-items: center; justify-content: space-between;
  gap: 6px; flex-shrink: 0; min-height: 56px;
}
/* Logo branca: filter inverte logo escuro para branco no fundo escuro */
.sb-logo img {
  height: 32px; width: auto; display: block;
  filter: brightness(0) invert(1);
  flex-shrink: 0;
}

/* ── Collapse toggle button ──────────────────────────────────────────────── */
#sb-collapse-btn {
  background: none; border: none; cursor: pointer;
  color: rgba(255,255,255,.35); padding: 5px 7px;
  border-radius: 6px; font-size: 18px; line-height: 1;
  flex-shrink: 0; transition: color .14s, background .14s;
}
#sb-collapse-btn:hover { color: rgba(255,255,255,.75); background: rgba(255,255,255,.08); }

/* ── Collapsed state ─────────────────────────────────────────────────────── */
#app-sidebar.sb-collapsed { width: var(--sb-w-col); }
/* No modo recolhido: esconde logo, centraliza botão */
#app-sidebar.sb-collapsed .sb-logo { justify-content: center; }
#app-sidebar.sb-collapsed .sb-logo img { display: none; }
#app-sidebar.sb-collapsed .sb-label { display: none; }
#app-sidebar.sb-collapsed .sb-section-label { display: none; }
#app-sidebar.sb-collapsed .sb-link { padding: 10px 0; justify-content: center; }
#app-sidebar.sb-collapsed .sb-icon { width: auto; font-size: 18px; }
#app-sidebar.sb-collapsed .sb-footer-text { display: none; }
#app-sidebar.sb-collapsed .sb-footer { padding: 10px 6px; text-align: center; }

/* ── Section / links ─────────────────────────────────────────────────────── */
.sb-section { padding: 10px 0 2px; }
.sb-section-label {
  padding: 0 16px 4px;
  font-size: 10px; font-weight: 700; letter-spacing: .1em;
  text-transform: uppercase; color: rgba(255,255,255,.28);
  white-space: nowrap; overflow: hidden;
}
.sb-link {
  display: flex; align-items: center; gap: 9px;
  padding: 8px 16px; color: var(--sb-txt); font-size: .85rem;
  text-decoration: none; border-left: 3px solid transparent;
  transition: background .13s, color .13s;
  white-space: nowrap; overflow: hidden;
}
.sb-link:hover { background: var(--sb-hover-bg); color: #fff; }
.sb-link.active {
  background: var(--sb-active-bg); color: var(--sb-accent);
  border-left-color: var(--sb-accent); font-weight: 600;
}
#app-sidebar.sb-collapsed .sb-link { border-left-color: transparent !important; }
#app-sidebar.sb-collapsed .sb-link.active { background: var(--sb-active-bg); }
.sb-icon { font-size: 15px; width: 20px; text-align: center; flex-shrink: 0; }
.sb-label { overflow: hidden; }

/* ── Footer ──────────────────────────────────────────────────────────────── */
.sb-footer {
  margin-top: auto; padding: 10px 16px 14px;
  border-top: 1px solid rgba(255,255,255,.08);
  font-size: .74rem; color: rgba(255,255,255,.4); flex-shrink: 0;
}
.sb-footer .sb-user-name { color: rgba(255,255,255,.6); font-weight: 600; margin-bottom: 2px; }

/* ── Desktop ─────────────────────────────────────────────────────────────── */
@media (min-width: 992px) {
  body { padding-left: var(--sb-w) !important; transition: padding-left .22s cubic-bezier(.4,0,.2,1); }
  body.sb-is-collapsed { padding-left: var(--sb-w-col) !important; }
  .navbar-brand { display: none !important; }
  #sb-toggle { display: none !important; }
}

/* ── Mobile ──────────────────────────────────────────────────────────────── */
@media (max-width: 991px) {
  #app-sidebar { transform: translateX(calc(-1 * var(--sb-w))); width: var(--sb-w) !important; }
  #app-sidebar.sb-open { transform: translateX(0); box-shadow: 4px 0 28px rgba(0,0,0,.4); }
  #sb-collapse-btn { display: none !important; }
  #sb-overlay { display: none; position: fixed; inset: 0; background: rgba(0,0,0,.5); z-index: 1039; }
  #sb-overlay.sb-open { display: block; }
  .sb-label { display: block !important; }
  .sb-section-label { display: block !important; }
}
</style>
"""

_SIDEBAR_HTML = r"""
<div id="sb-overlay" onclick="sbClose()"></div>

<aside id="app-sidebar">

  <!-- Logo + botão recolher -->
  <div class="sb-logo">
    <img src="/static/logo.png" alt="Maffezzolli Capital">
    <button id="sb-collapse-btn" onclick="sbToggleCollapse()" title="Recolher / expandir">&#8249;</button>
  </div>

  {% if current_user %}

  <!-- Início -->
  <div class="sb-section">
    <a class="sb-link" href="/" data-sbpath="/" title="Início">
      <span class="sb-icon">🏠</span><span class="sb-label">Início</span>
    </a>
  </div>

  <!-- Minha Empresa -->
  <div class="sb-section">
    <div class="sb-section-label">Minha Empresa</div>
    <a class="sb-link" href="/empresa" data-sbpath="/empresa" title="Empresa">
      <span class="sb-icon">🏢</span><span class="sb-label">Empresa</span>
    </a>
    <a class="sb-link" href="/financeiro" data-sbpath="/financeiro" title="Financeiro">
      <span class="sb-icon">📄</span><span class="sb-label">Financeiro</span>
    </a>
    <a class="sb-link" href="/documentos" data-sbpath="/documentos" title="Documentos">
      <span class="sb-icon">📁</span><span class="sb-label">Documentos</span>
    </a>
    <a class="sb-link" href="/planos" data-sbpath="/planos" title="Planos">
      <span class="sb-icon">📦</span><span class="sb-label">Planos</span>
    </a>
    <a class="sb-link" href="/minha-assinatura" data-sbpath="/minha-assinatura" title="Assinatura">
      <span class="sb-icon">⭐</span><span class="sb-label">Assinatura</span>
    </a>
  </div>

  <!-- Diagnóstico -->
  <div class="sb-section">
    <div class="sb-section-label">Diagnóstico</div>
    <a class="sb-link" href="/perfil" data-sbpath="/perfil" title="Diagnóstico Financeiro">
      <span class="sb-icon">🩺</span><span class="sb-label">Diagnóstico Financeiro</span>
    </a>
    <a class="sb-link" href="/consultas" data-sbpath="/consultas" title="Consultas de Risco">
      <span class="sb-icon">🔍</span><span class="sb-label">Consultas de Risco</span>
    </a>
    <a class="sb-link" href="/construrisk" data-sbpath="/construrisk" title="ConstruRisk">
      <span class="sb-icon">🏗️</span><span class="sb-label">ConstruRisk</span>
    </a>
  </div>

  <!-- Soluções -->
  <div class="sb-section">
    <div class="sb-section-label">Soluções</div>
    <a class="sb-link" href="/ofertas" data-sbpath="/ofertas" title="Ofertas">
      <span class="sb-icon">💡</span><span class="sb-label">Ofertas</span>
    </a>
    <a class="sb-link" href="/simulador" data-sbpath="/simulador" title="Simulador">
      <span class="sb-icon">🧮</span><span class="sb-label">Simulador</span>
    </a>
    <a class="sb-link" href="/propostas" data-sbpath="/propostas" title="Propostas">
      <span class="sb-icon">📋</span><span class="sb-label">Propostas</span>
    </a>
  </div>

  <!-- Ferramentas -->
  <div class="sb-section">
    <div class="sb-section-label">Ferramentas</div>
    <a class="sb-link" href="/ferramentas" data-sbpath="/ferramentas" title="Ferramentas">
      <span class="sb-icon">🔧</span><span class="sb-label">Ferramentas</span>
    </a>
    <a class="sb-link" href="/educacao" data-sbpath="/educacao" title="Educação">
      <span class="sb-icon">🎓</span><span class="sb-label">Educação</span>
    </a>
  </div>

  <!-- Gestão -->
  {% if role in ["admin", "equipe"] %}
  <div class="sb-section">
    <div class="sb-section-label">Gestão</div>
    <a class="sb-link" href="/ferramentas/bsc" data-sbpath="/ferramentas/bsc" title="BSC">
      <span class="sb-icon">📊</span><span class="sb-label">BSC</span>
    </a>
    <a class="sb-link" href="/ferramentas/orcamento" data-sbpath="/ferramentas/orcamento" title="Orçamento">
      <span class="sb-icon">💰</span><span class="sb-label">Orçamento</span>
    </a>
    <a class="sb-link" href="/admin/acoes" data-sbpath="/admin/acoes" title="Ações">
      <span class="sb-icon">⚡</span><span class="sb-label">Ações</span>
    </a>
    <a class="sb-link" href="/admin/grafo" data-sbpath="/admin/grafo" title="2º Cérebro">
      <span class="sb-icon">🧠</span><span class="sb-label">2º Cérebro</span>
    </a>
  </div>
  {% elif role == "cliente" %}
  <div class="sb-section">
    <div class="sb-section-label">Gestão</div>
    <a class="sb-link" href="/cliente/bsc" data-sbpath="/cliente/bsc" title="BSC">
      <span class="sb-icon">📊</span><span class="sb-label">BSC</span>
    </a>
    <a class="sb-link" href="/ferramentas/orcamento" data-sbpath="/ferramentas/orcamento" title="Orçamento">
      <span class="sb-icon">💰</span><span class="sb-label">Orçamento</span>
    </a>
    <a class="sb-link" href="/admin/acoes" data-sbpath="/admin/acoes" title="Ações">
      <span class="sb-icon">⚡</span><span class="sb-label">Ações</span>
    </a>
    <a class="sb-link" href="/cliente/grafo" data-sbpath="/cliente/grafo" title="2º Cérebro">
      <span class="sb-icon">🧠</span><span class="sb-label">2º Cérebro</span>
    </a>
  </div>
  {% endif %}

  <!-- Reuniões -->
  <div class="sb-section">
    <div class="sb-section-label">Reuniões</div>
    {% if role in ["admin", "equipe"] %}
    <a class="sb-link" href="/reunioes" data-sbpath="/reunioes" title="Reuniões">
      <span class="sb-icon">📅</span><span class="sb-label">Reuniões</span>
    </a>
    {% else %}
    <a class="sb-link" href="/cliente/reunioes" data-sbpath="/cliente/reunioes" title="Reuniões">
      <span class="sb-icon">📅</span><span class="sb-label">Reuniões</span>
    </a>
    {% endif %}
  </div>

  <!-- Negócios / CRM (apenas admin/equipe) -->
  {% if role in ["admin", "equipe"] %}
  <div class="sb-section">
    <div class="sb-section-label">Negócios</div>
    <a class="sb-link" href="/negocios" data-sbpath="/negocios" title="Pipeline">
      <span class="sb-icon">💼</span><span class="sb-label">Pipeline CRM</span>
    </a>
  </div>
  {% endif %}

  <!-- Projeto -->
  <div class="sb-section">
    <div class="sb-section-label">Projeto</div>
    <a class="sb-link" href="/tarefas" data-sbpath="/tarefas" title="Tarefas">
      <span class="sb-icon">✅</span><span class="sb-label">Tarefas</span>
    </a>
    <a class="sb-link" href="/consultoria" data-sbpath="/consultoria" title="Consultoria">
      <span class="sb-icon">🤝</span><span class="sb-label">Consultoria</span>
    </a>
  </div>

  <!-- Administração -->
  {% if role in ["admin", "equipe"] %}
  <div class="sb-section">
    <div class="sb-section-label">Administração</div>
    <a class="sb-link" href="/admin/clientes" data-sbpath="/admin/clientes" title="Clientes">
      <span class="sb-icon">🏢</span><span class="sb-label">Clientes</span>
    </a>
    <a class="sb-link" href="/admin/members" data-sbpath="/admin/members" title="Membros">
      <span class="sb-icon">👥</span><span class="sb-label">Membros</span>
    </a>
    {% if role == "admin" %}
    <a class="sb-link" href="/integrations" data-sbpath="/integrations" title="Integrações">
      <span class="sb-icon">☁️</span><span class="sb-label">Integrações</span>
    </a>
    {% endif %}
  </div>
  {% endif %}

  <!-- Escritório interno (apenas admin/equipe) -->
  {% if role in ["admin", "equipe"] %}
  <div class="sb-section">
    <div class="sb-section-label">Escritório</div>
    <a class="sb-link" href="/admin/financeiro" data-sbpath="/admin/financeiro" title="Financeiro Interno">
      <span class="sb-icon">🏦</span><span class="sb-label">Financeiro Interno</span>
    </a>
    <a class="sb-link" href="/motor-ofertas" data-sbpath="/motor-ofertas" title="Motor de Ofertas">
      <span class="sb-icon">⚙️</span><span class="sb-label">Motor de Ofertas</span>
    </a>
    <a class="sb-link" href="/admin/servicos-internos" data-sbpath="/admin/servicos-internos" title="Produtos Internos">
      <span class="sb-icon">📦</span><span class="sb-label">Produtos Internos</span>
    </a>
    <a class="sb-link" href="/admin/parceiros" data-sbpath="/admin/parceiros" title="Parceiros">
      <span class="sb-icon">🤝</span><span class="sb-label">Parceiros</span>
    </a>
    <a class="sb-link" href="/admin/agenda" data-sbpath="/admin/agenda" title="Agenda">
      <span class="sb-icon">📆</span><span class="sb-label">Agenda</span>
    </a>
    {% if role == "admin" %}
    <a class="sb-link" href="/admin/assinaturas" data-sbpath="/admin/assinaturas" title="Assinaturas">
      <span class="sb-icon">💳</span><span class="sb-label">Assinaturas</span>
    </a>
    <a class="sb-link" href="/admin/pesquisas" data-sbpath="/admin/pesquisas" title="Pesquisas">
      <span class="sb-icon">📊</span><span class="sb-label">Pesquisas</span>
    </a>
    <a class="sb-link" href="/admin/saude" data-sbpath="/admin/saude" title="Saúde do Sistema">
      <span class="sb-icon">🩺</span><span class="sb-label">Saúde do Sistema</span>
    </a>
    <a class="sb-link" href="/admin/uso" data-sbpath="/admin/uso" title="Uso da Plataforma">
      <span class="sb-icon">📈</span><span class="sb-label">Uso da Plataforma</span>
    </a>
    {% endif %}
  </div>
  {% endif %}

  <!-- Meu Time (gestor de cliente) -->
  {% if role == "cliente" %}
  <div class="sb-section">
    <div class="sb-section-label">Time</div>
    <a class="sb-link" href="/meu-time" data-sbpath="/meu-time" title="Meu Time">
      <span class="sb-icon">👥</span><span class="sb-label">Meu Time</span>
    </a>
  </div>
  {% endif %}

  <!-- Rodapé com usuário -->
  <div class="sb-footer">
    <div class="sb-footer-text">
      <div class="sb-user-name">{{ current_user.name }}</div>
      <div>{{ current_company.name if current_company else "" }}</div>
      <a href="/logout" style="color:rgba(255,255,255,.3);font-size:.68rem;">Sair</a>
    </div>
  </div>

  {% endif %}
</aside>

<script>
(function(){
  var STORAGE_KEY = 'sb_collapsed';
  var sidebar = document.getElementById('app-sidebar');
  var btn     = document.getElementById('sb-collapse-btn');

  function setCollapsed(collapsed) {
    sidebar.classList.toggle('sb-collapsed', collapsed);
    document.body.classList.toggle('sb-is-collapsed', collapsed);
    if (btn) btn.innerHTML = collapsed ? '&#8250;' : '&#8249;';
    localStorage.setItem(STORAGE_KEY, collapsed ? '1' : '0');
  }

  // Restaura estado salvo sem animação
  var saved = localStorage.getItem(STORAGE_KEY) === '1';
  if (saved) {
    sidebar.style.transition = 'none';
    setCollapsed(true);
    requestAnimationFrame(function(){ sidebar.style.transition = ''; });
  }

  window.sbToggleCollapse = function() {
    setCollapsed(!sidebar.classList.contains('sb-collapsed'));
  };

  // Ativa link correto
  var path = window.location.pathname;
  document.querySelectorAll('#app-sidebar .sb-link').forEach(function(a){
    var p = a.getAttribute('data-sbpath');
    if (!p) return;
    var match = (p === '/') ? (path === '/') : (path === p || path.startsWith(p + '/'));
    if (match) a.classList.add('active');
  });

  // Mobile
  window.sbOpen = function() {
    sidebar.classList.add('sb-open');
    document.getElementById('sb-overlay').classList.add('sb-open');
  };
  window.sbClose = function() {
    sidebar.classList.remove('sb-open');
    document.getElementById('sb-overlay').classList.remove('sb-open');
  };
})();
</script>
"""

_SB_TOGGLE_BTN = '<button id="sb-toggle" class="btn btn-outline-secondary btn-sm me-2" onclick="sbOpen()" aria-label="Abrir menu" style="border-radius:8px;">☰</button>'

# ── Patch base.html ──────────────────────────────────────────────────────────

try:
    _base = TEMPLATES.get("base.html", "")

    # Remove versão anterior se existir
    if "sb-styles" in _base:
        import re as _re_sb
        _base = _re_sb.sub(r'<style id="sb-styles">.*?</style>\s*', '', _base, flags=_re_sb.DOTALL)
        _base = _re_sb.sub(r'<div id="sb-overlay"[^>]*>.*?</aside>\s*', '', _base, flags=_re_sb.DOTALL)
        # Remove script da sidebar (bloco IIFE que contém 'sb_collapsed')
        _base = _re_sb.sub(r'<script>\s*\(function\(\)\{.*?sb_collapsed.*?\}\)\(\);\s*</script>', '', _base, flags=_re_sb.DOTALL)
        _base = _base.replace(_SB_TOGGLE_BTN, '')

    # 1. CSS no <head>
    _base = _base.replace("</head>", _SIDEBAR_CSS + "\n  </head>", 1)

    # 2. Sidebar antes do <nav>
    _base = _base.replace(
        '<nav class="navbar',
        _SIDEBAR_HTML + '\n    <nav class="navbar',
        1,
    )

    # 3. Botão hambúrguer mobile
    if _SB_TOGGLE_BTN not in _base:
        _base = _base.replace(
            '<div class="container py-2">',
            '<div class="container py-2">\n        ' + _SB_TOGGLE_BTN,
            1,
        )

    TEMPLATES["base.html"] = _base
    if hasattr(templates_env.loader, "mapping"):
        templates_env.loader.mapping["base.html"] = _base
    print("[sidebar] ✅ Sidebar v3 injetada no base.html.")

except Exception as _e_sb:
    print(f"[sidebar] ⚠️ Erro ao injetar sidebar: {_e_sb}")

print("[sidebar] ✅ Módulo de sidebar v3 carregado.")

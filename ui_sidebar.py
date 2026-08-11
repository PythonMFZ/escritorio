# ============================================================================
# ui_sidebar.py — Barra lateral de navegação fixa (esquerda)
# ============================================================================
# Injeta no base.html uma sidebar fixa com os grupos de navegação.
# Usa CSS position:fixed + padding-left no body para deslocar o conteúdo.
# Em mobile a sidebar fica oculta e abre via botão hambúrguer na navbar.
# ============================================================================

_SIDEBAR_CSS = r"""
<style id="sb-styles">
:root {
  --sb-w: 220px;
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
  transition: transform .24s cubic-bezier(.4,0,.2,1);
  scrollbar-width: thin; scrollbar-color: rgba(255,255,255,.12) transparent;
}
#app-sidebar::-webkit-scrollbar { width: 4px; }
#app-sidebar::-webkit-scrollbar-thumb { background: rgba(255,255,255,.12); border-radius: 2px; }

/* ── Logo block ──────────────────────────────────────────────────────────── */
.sb-logo {
  padding: 14px 14px 12px;
  border-bottom: 1px solid rgba(255,255,255,.08);
  display: flex; align-items: center; gap: 8px; flex-shrink: 0;
}
.sb-logo img { height: 30px; width: auto; }
.sb-logo-name {
  font-size: .72rem; font-weight: 600; color: rgba(255,255,255,.5);
  letter-spacing: .04em; line-height: 1.3;
}

/* ── Section ─────────────────────────────────────────────────────────────── */
.sb-section { padding: 12px 0 2px; }
.sb-section-label {
  padding: 0 16px 5px;
  font-size: 10px; font-weight: 700; letter-spacing: .1em;
  text-transform: uppercase; color: rgba(255,255,255,.3);
}

/* ── Nav link ────────────────────────────────────────────────────────────── */
.sb-link {
  display: flex; align-items: center; gap: 9px;
  padding: 8px 16px; color: var(--sb-txt); font-size: .85rem;
  text-decoration: none; border-left: 3px solid transparent;
  transition: background .14s, color .14s;
}
.sb-link:hover { background: var(--sb-hover-bg); color: #fff; }
.sb-link.active {
  background: var(--sb-active-bg); color: var(--sb-accent);
  border-left-color: var(--sb-accent); font-weight: 600;
}
.sb-icon { font-size: 15px; width: 20px; text-align: center; flex-shrink: 0; }

/* ── Bottom user info ────────────────────────────────────────────────────── */
.sb-footer {
  margin-top: auto; padding: 12px 16px 16px;
  border-top: 1px solid rgba(255,255,255,.08);
  font-size: .75rem; color: rgba(255,255,255,.45);
}
.sb-footer .sb-user-name { color: rgba(255,255,255,.65); font-weight: 600; }

/* ── Desktop: push content right ─────────────────────────────────────────── */
@media (min-width: 992px) {
  body { padding-left: var(--sb-w) !important; }
  /* Hide logo from top navbar on desktop (sidebar has it) */
  .navbar-brand { display: none !important; }
  #sb-toggle { display: none !important; }
}

/* ── Mobile: sidebar hidden, toggle in navbar ────────────────────────────── */
@media (max-width: 991px) {
  #app-sidebar { transform: translateX(calc(-1 * var(--sb-w))); box-shadow: none; }
  #app-sidebar.sb-open { transform: translateX(0); box-shadow: 4px 0 24px rgba(0,0,0,.35); }
  #sb-overlay { display: none; position: fixed; inset: 0; background: rgba(0,0,0,.48); z-index: 1039; }
  #sb-overlay.sb-open { display: block; }
}
</style>
"""

_SIDEBAR_HTML = r"""
<div id="sb-overlay" onclick="sbClose()"></div>

<aside id="app-sidebar">
  <div class="sb-logo">
    <img src="/static/logo.png" alt="Maffezzolli Capital">
    <span class="sb-logo-name">Maffezzolli<br>Capital</span>
  </div>

  {% if current_user %}

  <!-- Início -->
  <div class="sb-section">
    <a class="sb-link" href="/" data-sbpath="/">
      <span class="sb-icon">🏠</span> Início
    </a>
  </div>

  <!-- Gestão -->
  {% if role in ["admin", "equipe"] %}
  <div class="sb-section">
    <div class="sb-section-label">Gestão</div>
    <a class="sb-link" href="/ferramentas/bsc" data-sbpath="/ferramentas/bsc">
      <span class="sb-icon">📊</span> BSC
    </a>
    <a class="sb-link" href="/ferramentas/orcamento" data-sbpath="/ferramentas/orcamento">
      <span class="sb-icon">💰</span> Orçamento
    </a>
    <a class="sb-link" href="/admin/acoes" data-sbpath="/admin/acoes">
      <span class="sb-icon">⚡</span> Ações
    </a>
    <a class="sb-link" href="/admin/grafo" data-sbpath="/admin/grafo">
      <span class="sb-icon">🧠</span> 2º Cérebro
    </a>
  </div>
  {% elif role == "cliente" %}
  <div class="sb-section">
    <div class="sb-section-label">Gestão</div>
    <a class="sb-link" href="/cliente/bsc" data-sbpath="/cliente/bsc">
      <span class="sb-icon">📊</span> BSC
    </a>
    <a class="sb-link" href="/ferramentas/orcamento" data-sbpath="/ferramentas/orcamento">
      <span class="sb-icon">💰</span> Orçamento
    </a>
    <a class="sb-link" href="/admin/acoes" data-sbpath="/admin/acoes">
      <span class="sb-icon">⚡</span> Ações
    </a>
  </div>
  {% endif %}

  <!-- Reuniões -->
  <div class="sb-section">
    <div class="sb-section-label">Reuniões</div>
    {% if role in ["admin", "equipe"] %}
    <a class="sb-link" href="/reunioes" data-sbpath="/reunioes">
      <span class="sb-icon">📅</span> Reuniões
    </a>
    {% else %}
    <a class="sb-link" href="/cliente/reunioes" data-sbpath="/cliente/reunioes">
      <span class="sb-icon">📅</span> Reuniões
    </a>
    {% endif %}
  </div>

  <!-- Projeto -->
  <div class="sb-section">
    <div class="sb-section-label">Projeto</div>
    <a class="sb-link" href="/tarefas" data-sbpath="/tarefas">
      <span class="sb-icon">✅</span> Tarefas
    </a>
    <a class="sb-link" href="/consultoria" data-sbpath="/consultoria">
      <span class="sb-icon">🤝</span> Consultoria
    </a>
  </div>

  <!-- Administração (admin/equipe) -->
  {% if role in ["admin", "equipe"] %}
  <div class="sb-section">
    <div class="sb-section-label">Administração</div>
    <a class="sb-link" href="/admin/clientes" data-sbpath="/admin/clientes">
      <span class="sb-icon">🏢</span> Clientes
    </a>
    <a class="sb-link" href="/admin/members" data-sbpath="/admin/members">
      <span class="sb-icon">👥</span> Membros
    </a>
    {% if role == "admin" %}
    <a class="sb-link" href="/integrations" data-sbpath="/integrations">
      <span class="sb-icon">☁️</span> Integrações
    </a>
    {% endif %}
  </div>
  {% endif %}

  <!-- Rodapé com usuário -->
  <div class="sb-footer">
    <div class="sb-user-name">{{ current_user.name }}</div>
    <div>{{ current_company.name if current_company else "" }}</div>
    <a href="/logout" style="color: rgba(255,255,255,.35); font-size:.7rem;">Sair</a>
  </div>

  {% endif %}
</aside>

<script>
(function(){
  // Marca link ativo pelo pathname
  var path = window.location.pathname;
  document.querySelectorAll('#app-sidebar .sb-link').forEach(function(a){
    var p = a.getAttribute('data-sbpath');
    if (!p) return;
    if (p === '/' ? path === '/' : path === p || path.startsWith(p + '/')) {
      a.classList.add('active');
    }
  });

  // Funções de toggle (mobile)
  window.sbOpen = function() {
    document.getElementById('app-sidebar').classList.add('sb-open');
    document.getElementById('sb-overlay').classList.add('sb-open');
  };
  window.sbClose = function() {
    document.getElementById('app-sidebar').classList.remove('sb-open');
    document.getElementById('sb-overlay').classList.remove('sb-open');
  };
})();
</script>
"""

# Botão hambúrguer para mobile — injetado no início da navbar
_SB_TOGGLE_BTN = '<button id="sb-toggle" class="btn btn-outline-secondary btn-sm me-2" onclick="sbOpen()" aria-label="Abrir menu" style="border-radius:8px;">☰</button>'

# ── Patch base.html ──────────────────────────────────────────────────────────

try:
    _base = TEMPLATES.get("base.html", "")

    if "app-sidebar" not in _base:
        # 1. Injeta CSS no <head> (antes de </style> existente ou em </head>)
        _base = _base.replace("</head>", _SIDEBAR_CSS + "\n  </head>", 1)

        # 2. Injeta sidebar HTML + overlay logo após <body>
        #    Insere antes do <nav> que já existe
        _base = _base.replace(
            '<nav class="navbar',
            _SIDEBAR_HTML + '\n    <nav class="navbar',
            1,
        )

        # 3. Injeta botão hambúrguer no início do container da navbar
        _base = _base.replace(
            '<div class="container py-2">',
            '<div class="container py-2">\n        ' + _SB_TOGGLE_BTN,
            1,
        )

        TEMPLATES["base.html"] = _base
        if hasattr(templates_env.loader, "mapping"):
            templates_env.loader.mapping["base.html"] = _base
        print("[sidebar] ✅ Barra lateral injetada no base.html.")
    else:
        print("[sidebar] ℹ️ Sidebar já presente no base.html.")

except Exception as _e_sb:
    print(f"[sidebar] ⚠️ Erro ao injetar sidebar: {_e_sb}")

print("[sidebar] ✅ Módulo de sidebar carregado.")

# ============================================================================
# ui_sidebar.py — Barra lateral de navegação fixa (esquerda) v2
# ============================================================================
# Melhorias v2:
#   - Logo: apenas imagem, sem texto duplicado
#   - Recolher/expandir: toggle ‹/› salvo em localStorage
#   - Modo recolhido: 52px com ícones centralizados + tooltips nativos
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
  --sb-transition: width .22s cubic-bezier(.4,0,.2,1),
                   padding .22s cubic-bezier(.4,0,.2,1);
}

/* ── Sidebar container ──────────────────────────────────────────────────── */
#app-sidebar {
  position: fixed; top: 0; left: 0; height: 100vh; width: var(--sb-w);
  background: var(--sb-bg); z-index: 1040;
  display: flex; flex-direction: column;
  overflow-y: auto; overflow-x: hidden;
  transition: var(--sb-transition), transform .24s cubic-bezier(.4,0,.2,1);
  scrollbar-width: thin; scrollbar-color: rgba(255,255,255,.1) transparent;
}
#app-sidebar::-webkit-scrollbar { width: 3px; }
#app-sidebar::-webkit-scrollbar-thumb { background: rgba(255,255,255,.1); border-radius: 2px; }

/* ── Collapsed state ─────────────────────────────────────────────────────── */
#app-sidebar.sb-collapsed { width: var(--sb-w-col); }
#app-sidebar.sb-collapsed .sb-label { display: none; }
#app-sidebar.sb-collapsed .sb-section-label { display: none; }
#app-sidebar.sb-collapsed .sb-link { padding: 10px; justify-content: center; }
#app-sidebar.sb-collapsed .sb-icon { width: auto; font-size: 18px; }
#app-sidebar.sb-collapsed .sb-logo { justify-content: center; padding: 12px 8px; }
#app-sidebar.sb-collapsed .sb-logo-img-full { display: none; }
#app-sidebar.sb-collapsed .sb-logo-icon { display: flex !important; }
#app-sidebar.sb-collapsed .sb-footer { padding: 10px 6px; text-align: center; }
#app-sidebar.sb-collapsed .sb-footer-text { display: none; }
#app-sidebar.sb-collapsed .sb-collapse-btn { justify-content: center; }

/* ── Logo block ──────────────────────────────────────────────────────────── */
.sb-logo {
  padding: 13px 14px 11px;
  border-bottom: 1px solid rgba(255,255,255,.08);
  display: flex; align-items: center; justify-content: space-between;
  gap: 8px; flex-shrink: 0;
}
.sb-logo-img-full { height: 34px; width: auto; display: block; }
.sb-logo-icon { height: 28px; width: auto; display: none; }

/* ── Collapse toggle button ──────────────────────────────────────────────── */
.sb-collapse-btn {
  background: none; border: none; cursor: pointer;
  color: rgba(255,255,255,.3); padding: 4px 6px;
  border-radius: 6px; font-size: 14px; line-height: 1;
  display: flex; align-items: center;
  transition: color .14s, background .14s;
  flex-shrink: 0;
}
.sb-collapse-btn:hover { color: rgba(255,255,255,.7); background: rgba(255,255,255,.08); }

/* ── Section ─────────────────────────────────────────────────────────────── */
.sb-section { padding: 10px 0 2px; }
.sb-section-label {
  padding: 0 16px 4px;
  font-size: 10px; font-weight: 700; letter-spacing: .1em;
  text-transform: uppercase; color: rgba(255,255,255,.28);
  white-space: nowrap; overflow: hidden;
}

/* ── Nav link ────────────────────────────────────────────────────────────── */
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
#app-sidebar.sb-collapsed .sb-link.active {
  background: var(--sb-active-bg);
}
.sb-icon { font-size: 15px; width: 20px; text-align: center; flex-shrink: 0; }
.sb-label { overflow: hidden; }

/* ── Footer ──────────────────────────────────────────────────────────────── */
.sb-footer {
  margin-top: auto; padding: 10px 16px 14px;
  border-top: 1px solid rgba(255,255,255,.08);
  font-size: .74rem; color: rgba(255,255,255,.4);
  flex-shrink: 0;
}
.sb-footer .sb-user-name { color: rgba(255,255,255,.6); font-weight: 600; margin-bottom: 2px; }

/* ── Desktop: push content right ─────────────────────────────────────────── */
@media (min-width: 992px) {
  body {
    padding-left: var(--sb-w) !important;
    transition: padding-left .22s cubic-bezier(.4,0,.2,1);
  }
  body.sb-is-collapsed { padding-left: var(--sb-w-col) !important; }
  .navbar-brand { display: none !important; }
  #sb-toggle { display: none !important; }
}

/* ── Mobile ──────────────────────────────────────────────────────────────── */
@media (max-width: 991px) {
  #app-sidebar { transform: translateX(calc(-1 * var(--sb-w))); width: var(--sb-w) !important; }
  #app-sidebar.sb-open { transform: translateX(0); box-shadow: 4px 0 28px rgba(0,0,0,.4); }
  .sb-collapse-btn { display: none !important; }
  #sb-overlay { display: none; position: fixed; inset: 0; background: rgba(0,0,0,.5); z-index: 1039; }
  #sb-overlay.sb-open { display: block; }
  /* Always show labels on mobile */
  .sb-label { display: block !important; }
  .sb-section-label { display: block !important; }
}
</style>
"""

_SIDEBAR_HTML = r"""
<div id="sb-overlay" onclick="sbClose()"></div>

<aside id="app-sidebar">

  <!-- Logo + collapse toggle -->
  <div class="sb-logo">
    <img class="sb-logo-img-full" src="/static/logo.png" alt="Maffezzolli Capital">
    <img class="sb-logo-icon" src="/static/logo.png" alt="M" style="object-fit:contain;">
    <button class="sb-collapse-btn" id="sb-collapse-btn" onclick="sbToggleCollapse()" title="Recolher/expandir menu" aria-label="Recolher menu">
      &#8249;
    </button>
  </div>

  {% if current_user %}

  <!-- Início -->
  <div class="sb-section">
    <a class="sb-link" href="/" data-sbpath="/" title="Início">
      <span class="sb-icon">🏠</span><span class="sb-label">Início</span>
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

  <!-- Administração (admin/equipe) -->
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

  <!-- Rodapé com usuário -->
  <div class="sb-footer">
    <div class="sb-footer-text">
      <div class="sb-user-name">{{ current_user.name }}</div>
      <div>{{ current_company.name if current_company else "" }}</div>
      <a href="/logout" style="color:rgba(255,255,255,.3);font-size:.68rem;">Sair</a>
    </div>
    <a href="/logout" class="sb-footer-logout" title="Sair" style="display:none;color:rgba(255,255,255,.35);font-size:16px;text-decoration:none;">⏻</a>
  </div>

  {% endif %}
</aside>

<script>
(function(){
  var STORAGE_KEY = 'sb_collapsed';
  var sidebar = document.getElementById('app-sidebar');
  var colBtn  = document.getElementById('sb-collapse-btn');

  // ── Ativa link correto ────────────────────────────────────────────────────
  var path = window.location.pathname;
  document.querySelectorAll('#app-sidebar .sb-link').forEach(function(a){
    var p = a.getAttribute('data-sbpath');
    if (!p) return;
    var match = (p === '/') ? (path === '/') : (path === p || path.startsWith(p + '/'));
    if (match) a.classList.add('active');
  });

  // ── Colapso ───────────────────────────────────────────────────────────────
  function applyCollapse(collapsed, animate) {
    if (!animate) sidebar.style.transition = 'none';
    sidebar.classList.toggle('sb-collapsed', collapsed);
    document.body.classList.toggle('sb-is-collapsed', collapsed);
    if (colBtn) colBtn.innerHTML = collapsed ? '&#8250;' : '&#8249;';

    // Ícone de logout no rodapé
    var logoutText = sidebar.querySelector('.sb-footer-logout');
    if (logoutText) logoutText.style.display = collapsed ? 'block' : 'none';

    if (!animate) {
      // Força reflow e restaura transição
      sidebar.offsetHeight;
      sidebar.style.transition = '';
    }
  }

  // Restaura estado salvo (sem animação)
  var saved = localStorage.getItem(STORAGE_KEY) === '1';
  applyCollapse(saved, false);

  window.sbToggleCollapse = function() {
    var isNowCollapsed = !sidebar.classList.contains('sb-collapsed');
    applyCollapse(isNowCollapsed, true);
    localStorage.setItem(STORAGE_KEY, isNowCollapsed ? '1' : '0');
  };

  // ── Mobile open/close ─────────────────────────────────────────────────────
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

# Botão hambúrguer para mobile
_SB_TOGGLE_BTN = '<button id="sb-toggle" class="btn btn-outline-secondary btn-sm me-2" onclick="sbOpen()" aria-label="Abrir menu" style="border-radius:8px;">☰</button>'

# ── Patch base.html ──────────────────────────────────────────────────────────

try:
    _base = TEMPLATES.get("base.html", "")

    # Remove versão anterior se existir, para reaplicar
    if "sb-styles" in _base:
        import re as _re_sb
        # Remove bloco <style id="sb-styles">...</style>
        _base = _re_sb.sub(r'<style id="sb-styles">.*?</style>', '', _base, flags=_re_sb.DOTALL)
        # Remove bloco aside + overlay
        _base = _re_sb.sub(r'<div id="sb-overlay".*?</aside>', '', _base, flags=_re_sb.DOTALL)
        # Remove script de sidebar
        _base = _re_sb.sub(r'\(function\(\)\{[^}]*sb-collapse-btn.*?\}\)\(\);', '', _base, flags=_re_sb.DOTALL)
        # Remove botão hamburger antigo
        _base = _base.replace(_SB_TOGGLE_BTN, '')

    # 1. Injeta CSS no <head>
    _base = _base.replace("</head>", _SIDEBAR_CSS + "\n  </head>", 1)

    # 2. Injeta sidebar + overlay antes do <nav>
    _base = _base.replace(
        '<nav class="navbar',
        _SIDEBAR_HTML + '\n    <nav class="navbar',
        1,
    )

    # 3. Injeta botão hambúrguer no container da navbar
    if _SB_TOGGLE_BTN not in _base:
        _base = _base.replace(
            '<div class="container py-2">',
            '<div class="container py-2">\n        ' + _SB_TOGGLE_BTN,
            1,
        )

    TEMPLATES["base.html"] = _base
    if hasattr(templates_env.loader, "mapping"):
        templates_env.loader.mapping["base.html"] = _base
    print("[sidebar] ✅ Sidebar v2 (colapsável) injetada no base.html.")

except Exception as _e_sb:
    print(f"[sidebar] ⚠️ Erro ao injetar sidebar: {_e_sb}")

print("[sidebar] ✅ Módulo de sidebar v2 carregado.")

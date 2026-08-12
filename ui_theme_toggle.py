# ui_theme_toggle.py — Botão claro/escuro no navbar
# Injeta toggle de tema (light/dark) com persistência em localStorage.
# Usa data-bs-theme para acionar o dark mode nativo do Bootstrap 5.

_TOGGLE_BTN = '''<button id="themeToggle" onclick="(function(){
  var n=document.documentElement.getAttribute('data-bs-theme')==='dark'?'light':'dark';
  document.documentElement.setAttribute('data-bs-theme',n);
  document.documentElement.setAttribute('data-theme',n);
  localStorage.setItem('theme',n);
  var b=document.getElementById('themeToggle');
  if(b)b.textContent=n==='dark'?'☀️':'🌙';
})()" title="Alternar tema" style="background:none;border:1px solid rgba(128,128,128,.25);border-radius:20px;padding:3px 10px;cursor:pointer;font-size:.85rem;line-height:1.4;">🌙</button>'''

_THEME_INIT = '''<script>(function(){
  var t=localStorage.getItem('theme')||'light';
  document.documentElement.setAttribute('data-bs-theme',t);
  document.documentElement.setAttribute('data-theme',t);
  document.addEventListener('DOMContentLoaded',function(){
    var b=document.getElementById('themeToggle');
    if(b)b.textContent=t==='dark'?'☀️':'🌙';
  });
})();</script>'''

_DARK_CSS = """<style>
/* ── Dark mode global ── */
[data-bs-theme="dark"] body {
  background: #0f1923 !important;
  color: #d8e8f4 !important;
}

/* Navbar */
[data-bs-theme="dark"] .navbar,
[data-bs-theme="dark"] nav.navbar {
  background: #0a1219 !important;
  border-color: rgba(255,255,255,.08) !important;
}
[data-bs-theme="dark"] .navbar .badge,
[data-bs-theme="dark"] .navbar .text-bg-light {
  background: #1e3047 !important;
  color: #a0bfd4 !important;
  border-color: rgba(255,255,255,.1) !important;
}
[data-bs-theme="dark"] .navbar a { color: #a0bfd4 !important; }
[data-bs-theme="dark"] .navbar-brand span { color: #a0bfd4 !important; }

/* Cards e painéis */
[data-bs-theme="dark"] .card {
  background: #162233 !important;
  border-color: rgba(255,255,255,.08) !important;
  box-shadow: 0 6px 18px rgba(0,0,0,.35) !important;
  color: #d8e8f4 !important;
}
[data-bs-theme="dark"] .card-header,
[data-bs-theme="dark"] .card-footer {
  background: rgba(255,255,255,.04) !important;
  border-color: rgba(255,255,255,.08) !important;
}

/* Texto e títulos */
[data-bs-theme="dark"] h1,[data-bs-theme="dark"] h2,
[data-bs-theme="dark"] h3,[data-bs-theme="dark"] h4,
[data-bs-theme="dark"] h5,[data-bs-theme="dark"] h6 { color: #e8f2fa !important; }
[data-bs-theme="dark"] .text-muted { color: #7aafd4 !important; }
[data-bs-theme="dark"] .muted { color: #7aafd4 !important; }
[data-bs-theme="dark"] small { color: #7aafd4 !important; }

/* Formulários */
[data-bs-theme="dark"] .form-control,
[data-bs-theme="dark"] .form-select,
[data-bs-theme="dark"] .input-group-text {
  background: #0f1923 !important;
  border-color: rgba(255,255,255,.15) !important;
  color: #d8e8f4 !important;
}
[data-bs-theme="dark"] .form-control::placeholder { color: #4a6375 !important; }
[data-bs-theme="dark"] .form-label { color: #a0bfd4 !important; }

/* Tabelas */
[data-bs-theme="dark"] table { color: #d8e8f4 !important; }
[data-bs-theme="dark"] .table { --bs-table-bg: #162233; --bs-table-striped-bg: #1a2940; }
[data-bs-theme="dark"] thead th {
  background: #0f1923 !important;
  color: #7aafd4 !important;
  border-color: rgba(255,255,255,.08) !important;
}
[data-bs-theme="dark"] td, [data-bs-theme="dark"] th {
  border-color: rgba(255,255,255,.06) !important;
}

/* Botões secundários */
[data-bs-theme="dark"] .btn-outline-secondary {
  border-color: rgba(255,255,255,.2) !important;
  color: #a0bfd4 !important;
}
[data-bs-theme="dark"] .btn-outline-secondary:hover {
  background: rgba(255,255,255,.08) !important;
}
[data-bs-theme="dark"] .btn-light {
  background: #1e3047 !important;
  border-color: rgba(255,255,255,.1) !important;
  color: #d8e8f4 !important;
}

/* Sidebar */
[data-bs-theme="dark"] .sidebar,
[data-bs-theme="dark"] [class*="sidebar"] {
  background: #0a1219 !important;
  border-color: rgba(255,255,255,.08) !important;
}
[data-bs-theme="dark"] .sidebar a,
[data-bs-theme="dark"] [class*="sidebar"] a { color: #a0bfd4 !important; }
[data-bs-theme="dark"] .sidebar a:hover,
[data-bs-theme="dark"] [class*="sidebar"] a:hover { color: #00BFBF !important; }

/* Badges e pills */
[data-bs-theme="dark"] .badge.text-bg-light,
[data-bs-theme="dark"] .badge.bg-light {
  background: #1e3047 !important;
  color: #a0bfd4 !important;
}
[data-bs-theme="dark"] .badge.bg-white { background: #1e3047 !important; }

/* Bordas e divisores */
[data-bs-theme="dark"] .border,
[data-bs-theme="dark"] .border-bottom,
[data-bs-theme="dark"] hr { border-color: rgba(255,255,255,.08) !important; }

/* Alertas */
[data-bs-theme="dark"] .alert-info {
  background: #0e253a !important;
  border-color: #1b4a70 !important;
  color: #7aafd4 !important;
}

/* Botão toggle */
[data-bs-theme="dark"] #themeToggle {
  border-color: rgba(255,255,255,.2) !important;
  color: #7aafd4 !important;
}

/* Fundo de painéis internos */
[data-bs-theme="dark"] .bg-white,
[data-bs-theme="dark"] .bg-light { background: #162233 !important; }
[data-bs-theme="dark"] [style*="background:#fff"],
[data-bs-theme="dark"] [style*="background: #fff"],
[data-bs-theme="dark"] [style*="background:white"] { background: #162233 !important; }

/* Dropdown menus */
[data-bs-theme="dark"] .dropdown-menu {
  background: #162233 !important;
  border-color: rgba(255,255,255,.1) !important;
}
[data-bs-theme="dark"] .dropdown-item { color: #d8e8f4 !important; }
[data-bs-theme="dark"] .dropdown-item:hover { background: #1e3047 !important; }
</style>"""

try:
    _tpl = TEMPLATES.get("base.html", "")  # type: ignore[name-defined]
    if _tpl and "themeToggle" not in _tpl:
        # 1. Injeta script de inicialização logo após <head>
        _tpl = _tpl.replace("<head>", "<head>\n" + _THEME_INIT, 1)
        # 2. Injeta CSS dark logo antes de </head>
        _tpl = _tpl.replace("</head>", _DARK_CSS + "\n  </head>", 1)
        # 3. Injeta botão no navbar antes do botão Sair (última ocorrência)
        _LOGOUT = '<a class="btn btn-outline-secondary btn-sm" href="/logout">Sair</a>'
        if _LOGOUT in _tpl:
            _tpl = _tpl.replace(
                _LOGOUT,
                _TOGGLE_BTN + "\n            " + _LOGOUT,
                1,
            )
        TEMPLATES["base.html"] = _tpl  # type: ignore[name-defined]
        if hasattr(templates_env.loader, "mapping"):  # type: ignore[name-defined]
            templates_env.loader.mapping = TEMPLATES  # type: ignore[name-defined]
        print("[theme_toggle] ✅ Botão claro/escuro injetado no navbar")
except Exception as _e_tt:
    print(f"[theme_toggle] ⚠️ {_e_tt}")

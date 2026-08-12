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
  if(n==='dark'){
    var whites=['#fff','#FFF','#ffffff','#FFFFFF','white','rgb(255,255,255)','rgb(255, 255, 255)'];
    document.querySelectorAll('[style]').forEach(function(el){
      var s=el.style;
      if(whites.indexOf(s.background)>-1||whites.indexOf(s.backgroundColor)>-1){
        el.style.background='#162233';el.style.backgroundColor='#162233';el.style.color='#d8e8f4';
      }
    });
  }
})()" title="Alternar tema" style="background:none;border:1px solid rgba(128,128,128,.25);border-radius:20px;padding:3px 10px;cursor:pointer;font-size:.85rem;line-height:1.4;">🌙</button>'''

_THEME_INIT = '''<script>(function(){
  var t=localStorage.getItem('theme')||'light';
  document.documentElement.setAttribute('data-bs-theme',t);
  document.documentElement.setAttribute('data-theme',t);

  function applyDarkInline(){
    if(document.documentElement.getAttribute('data-bs-theme')!=='dark') return;
    // Força fundo escuro em elementos com style inline branco
    var whites=['#fff','#FFF','#ffffff','#FFFFFF','white','rgb(255,255,255)','rgb(255, 255, 255)'];
    document.querySelectorAll('[style]').forEach(function(el){
      var s=el.style;
      if(whites.indexOf(s.background)>-1||whites.indexOf(s.backgroundColor)>-1){
        el.style.background='#162233';
        el.style.backgroundColor='#162233';
        el.style.color='#d8e8f4';
      }
    });
  }

  document.addEventListener('DOMContentLoaded',function(){
    var b=document.getElementById('themeToggle');
    if(b)b.textContent=t==='dark'?'☀️':'🌙';
    applyDarkInline();
    // Observa mudanças dinâmicas (chat, modais)
    if(t==='dark'){
      var obs=new MutationObserver(function(){applyDarkInline();});
      obs.observe(document.body,{childList:true,subtree:true,attributes:true,attributeFilter:['style']});
    }
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

/* Dropdown menus */
[data-bs-theme="dark"] .dropdown-menu {
  background: #162233 !important;
  border-color: rgba(255,255,255,.1) !important;
}
[data-bs-theme="dark"] .dropdown-item { color: #d8e8f4 !important; }
[data-bs-theme="dark"] .dropdown-item:hover { background: #1e3047 !important; }

/* ── Força escuro em QUALQUER elemento com style inline branco ── */
[data-bs-theme="dark"] * {
  --white-override: #162233;
}

/* Chat Augur */
[data-bs-theme="dark"] #augur-chat,
[data-bs-theme="dark"] [id*="augur"],
[data-bs-theme="dark"] [id*="Augur"],
[data-bs-theme="dark"] [class*="augur"],
[data-bs-theme="dark"] [class*="chat-"] {
  background: #0f1923 !important;
  color: #d8e8f4 !important;
  border-color: rgba(255,255,255,.08) !important;
}

/* Mensagens do chat */
[data-bs-theme="dark"] [id*="msgs"],
[data-bs-theme="dark"] [id*="Msgs"],
[data-bs-theme="dark"] [id*="messages"],
[data-bs-theme="dark"] [class*="msg-"],
[data-bs-theme="dark"] [class*="-msg"] {
  background: #0f1923 !important;
  color: #d8e8f4 !important;
}

/* Input area */
[data-bs-theme="dark"] textarea,
[data-bs-theme="dark"] input[type="text"],
[data-bs-theme="dark"] input[type="search"],
[data-bs-theme="dark"] input[type="email"],
[data-bs-theme="dark"] input[type="password"] {
  background: #0f1923 !important;
  color: #d8e8f4 !important;
  border-color: rgba(255,255,255,.15) !important;
}
[data-bs-theme="dark"] textarea::placeholder,
[data-bs-theme="dark"] input::placeholder { color: #4a6375 !important; }

/* Painéis flutuantes e modais */
[data-bs-theme="dark"] .modal-content,
[data-bs-theme="dark"] .offcanvas,
[data-bs-theme="dark"] .popover,
[data-bs-theme="dark"] .tooltip-inner {
  background: #162233 !important;
  color: #d8e8f4 !important;
  border-color: rgba(255,255,255,.08) !important;
}

/* Qualquer div/section/article com fundo branco inline */
[data-bs-theme="dark"] div[style*="#fff"],
[data-bs-theme="dark"] div[style*="#FFF"],
[data-bs-theme="dark"] div[style*="white"],
[data-bs-theme="dark"] section[style*="#fff"],
[data-bs-theme="dark"] article[style*="#fff"],
[data-bs-theme="dark"] aside[style*="#fff"] {
  background: #162233 !important;
  color: #d8e8f4 !important;
}

/* Listas e items */
[data-bs-theme="dark"] li { color: #d8e8f4 !important; }
[data-bs-theme="dark"] p { color: #c8dcea !important; }
[data-bs-theme="dark"] span:not(.badge):not([class*="text-"]) { color: inherit; }

/* Links dentro de cards e painéis */
[data-bs-theme="dark"] .card a,
[data-bs-theme="dark"] .card p,
[data-bs-theme="dark"] .card span,
[data-bs-theme="dark"] .card li { color: #c8dcea !important; }

/* Nav lateral / sidebar links */
[data-bs-theme="dark"] nav a,
[data-bs-theme="dark"] [class*="nav"] a { color: #a0bfd4 !important; }

/* Scores e números grandes */
[data-bs-theme="dark"] [class*="score"],
[data-bs-theme="dark"] [class*="Score"] { color: #d8e8f4 !important; }

/* Bordas de separação */
[data-bs-theme="dark"] [style*="border"][style*="#e"],
[data-bs-theme="dark"] [style*="border"][style*="#d"] {
  border-color: rgba(255,255,255,.08) !important;
}
</style>"""

try:
    _tpl = TEMPLATES.get("base.html", "")  # type: ignore[name-defined]
    print(f"[theme_toggle] base.html len={len(_tpl)}, themeToggle={'themeToggle' in _tpl}")
    if _tpl and "themeToggle" not in _tpl:
        # 1. Injeta script de inicialização logo após <head>
        _tpl = _tpl.replace("<head>", "<head>\n" + _THEME_INIT, 1)
        # 2. Injeta CSS dark logo antes de </head>
        _tpl = _tpl.replace("</head>", _DARK_CSS + "\n  </head>", 1)
        # 3. Injeta botão no navbar antes do botão Sair
        # Tenta string exata; fallback para qualquer href="/logout"
        _LOGOUT_EXACT = '<a class="btn btn-outline-secondary btn-sm" href="/logout">Sair</a>'
        import re as _re_tt
        if _LOGOUT_EXACT in _tpl:
            _tpl = _tpl.replace(
                _LOGOUT_EXACT,
                _TOGGLE_BTN + "\n            " + _LOGOUT_EXACT,
                1,
            )
            print("[theme_toggle] injetou via string exata")
        elif 'href="/logout"' in _tpl:
            _tpl = _re_tt.sub(
                r'(<a [^>]*href="/logout"[^>]*>Sair</a>)',
                _TOGGLE_BTN + r"\n            \1",
                _tpl,
                count=1,
            )
            print("[theme_toggle] injetou via regex logout")
        else:
            # Fallback: injeta antes de </nav>
            _tpl = _tpl.replace("</nav>", _TOGGLE_BTN + "\n</nav>", 1)
            print("[theme_toggle] injetou via </nav> fallback")
        TEMPLATES["base.html"] = _tpl  # type: ignore[name-defined]
        if hasattr(templates_env.loader, "mapping"):  # type: ignore[name-defined]
            templates_env.loader.mapping = TEMPLATES  # type: ignore[name-defined]
        print("[theme_toggle] ✅ Botão claro/escuro injetado no navbar")
    elif not _tpl:
        print("[theme_toggle] ⚠️ base.html não encontrado em TEMPLATES")
    else:
        print("[theme_toggle] ℹ️ themeToggle já presente, pulando injeção")
except Exception as _e_tt:
    import traceback as _tb_tt
    print(f"[theme_toggle] ⚠️ {_e_tt}")
    _tb_tt.print_exc()

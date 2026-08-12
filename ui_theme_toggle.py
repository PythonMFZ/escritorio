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
[data-theme="dark"] body,[data-bs-theme="dark"] body{background:#0f1923!important;}
[data-theme="dark"] .card,[data-bs-theme="dark"] .card{background:#162233!important;box-shadow:0 6px 18px rgba(0,0,0,.3);}
[data-theme="dark"] .navbar,[data-bs-theme="dark"] .navbar{background:#0a1219!important;border-color:rgba(255,255,255,.08)!important;}
[data-theme="dark"] #themeToggle,[data-bs-theme="dark"] #themeToggle{border-color:rgba(255,255,255,.2);color:#8aacbf;}
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

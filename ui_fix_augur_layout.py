# ============================================================================
# PATCH — Fix layout Augur (largura total) + Convite membros na tela certa
# ============================================================================
# 1. Augur ocupa largura total no dashboard
# 2. Botão convidar aparece na tela /admin/members
# 3. Sessões salvando corretamente
# DEPLOY: adicione ao final do app.py
# ============================================================================

# ── Fix 1: Dashboard — Augur ocupa largura total ──────────────────────────────

_dash = TEMPLATES.get("dashboard.html", "")

if _dash and "augurCard" in _dash:
    # Remove o Augur de onde está e coloca numa row separada acima do conteúdo
    import re as _re_al

    # Extrai o bloco do Augur (do card até base de conhecimento)
    _augur_match = _re_al.search(
        r'\{#\s*── AUGUR WIDGET.*?── /AUGUR WIDGET.*?#\}',
        _dash, flags=_re_al.DOTALL
    )

    if _augur_match:
        _augur_block = _augur_match.group(0)
        # Remove do lugar atual
        _dash = _dash.replace(_augur_block, "")

        # Injeta numa row de largura total ANTES do {% block content %}
        _augur_row = f"""
<div class="row g-3 mb-0">
  <div class="col-12">
    {_augur_block}
  </div>
</div>
"""
        # Coloca antes do primeiro card do dashboard
        if '{% block content %}' in _dash:
            _dash = _dash.replace(
                '{% block content %}\n<div class="row g-3">',
                '{% block content %}\n' + _augur_row + '\n<div class="row g-3">',
                1
            )
        TEMPLATES["dashboard.html"] = _dash
        print("[fix_augur_layout] ✅ Augur movido para largura total")
    else:
        # Fallback: injeta estilo para ampliar o widget
        _dash = _dash.replace(
            '<div class="card mb-3" id="augurCard"',
            '<div class="card mb-3" id="augurCard" style="max-width:100%;"'
        )
        TEMPLATES["dashboard.html"] = _dash
        print("[fix_augur_layout] ✅ Augur ampliado via estilo")

# ── Fix 2: Amplia sidebar e altura do Augur via CSS injetado ─────────────────

_AUGUR_CSS_FIX = """
<style>
  #augurCard { width: 100% !important; }
  #augurSidebar { width: 240px !important; min-width: 240px !important; }
  #augurCard > .card-body > div:last-of-type { height: 500px !important; }
  .aug-bubble { max-width: 80% !important; }
</style>
"""

_dash2 = TEMPLATES.get("dashboard.html", "")
if _dash2 and "augur_css_fix" not in _dash2:
    if "{% endblock %}" in _dash2:
        _dash2 = _dash2.replace("{% endblock %}", _AUGUR_CSS_FIX + "\n{% endblock %}", 1)
        TEMPLATES["dashboard.html"] = _dash2
        print("[fix_augur_layout] ✅ CSS fix injetado")

# ── Fix 3: Convite membros — garante que aparece em /admin/members ────────────

_members_tpl = TEMPLATES.get("members.html", "")
if _members_tpl and "convidar" not in _members_tpl:
    _CONVITE_FORM = """
<div class="card p-3 mb-4" style="border:1px solid var(--mc-border);">
  <h6 class="mb-3">✉️ Convidar novo membro</h6>
  <form method="post" action="/admin/members/convidar" class="row g-2 align-items-end">
    <div class="col-md-5">
      <label class="form-label small fw-semibold">E-mail</label>
      <input type="email" name="email" class="form-control form-control-sm" required placeholder="email@exemplo.com">
    </div>
    <div class="col-md-3">
      <label class="form-label small fw-semibold">Perfil</label>
      <select name="role" class="form-select form-select-sm">
        <option value="equipe">Equipe</option>
        <option value="admin">Admin</option>
        <option value="cliente">Cliente</option>
      </select>
    </div>
    <div class="col-md-4">
      <button type="submit" class="btn btn-primary btn-sm w-100">Gerar link de convite</button>
    </div>
  </form>
</div>
"""
    # Injeta no início do conteúdo da página de membros
    if "<h4" in _members_tpl:
        _members_tpl = _members_tpl.replace("<h4", _CONVITE_FORM + "\n<h4", 1)
    elif "{% for row" in _members_tpl:
        _members_tpl = _members_tpl.replace("{% for row", _CONVITE_FORM + "\n{% for row", 1)
    elif "<table" in _members_tpl:
        _members_tpl = _members_tpl.replace("<table", _CONVITE_FORM + "\n<table", 1)

    TEMPLATES["members.html"] = _members_tpl
    print("[fix_augur_layout] ✅ Formulário de convite adicionado em members.html")
elif _members_tpl and "convidar" in _members_tpl:
    print("[fix_augur_layout] ✅ Formulário de convite já existe em members.html")

# ── Fix 4: Mostra link do último convite gerado ───────────────────────────────

_members_tpl2 = TEMPLATES.get("members.html", "")
if _members_tpl2 and "last_invite_url" not in _members_tpl2:
    _INVITE_LINK = """
{% if request.session.get('last_invite_url') %}
<div class="alert alert-success py-2 mb-3 small">
  <strong>Link de convite gerado:</strong>
  <a href="{{ request.session.get('last_invite_url') }}" target="_blank" style="word-break:break-all;">
    {{ request.session.get('last_invite_url') }}
  </a>
  <div class="muted" style="font-size:.7rem;">Copie e envie para o convidado. Válido por 7 dias.</div>
</div>
{% endif %}
"""
    if "Gerar link de convite" in _members_tpl2:
        _members_tpl2 = _members_tpl2.replace(
            "</form>\n</div>",
            "</form>\n" + _INVITE_LINK + "\n</div>",
            1
        )
        TEMPLATES["members.html"] = _members_tpl2
        print("[fix_augur_layout] ✅ Link do convite adicionado em members.html")

if hasattr(templates_env.loader, "mapping"):
    templates_env.loader.mapping = TEMPLATES

print("[fix_augur_layout] ✅ Patch completo carregado")

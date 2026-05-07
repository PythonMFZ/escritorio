# ============================================================================
# PATCH — Batch de fixes (batch4)
#
# 1. base.html: restaura {% else %}/{% endif %} removidos pelo batch3
#    O regex do _b3_fix_sininho() consumiu o bloco outer do {% if current_user %}
#    junto com o sininho, quebrando o template com TemplateSyntaxError.
# ============================================================================

import re as _re_b4


def _b4_restore_base_nav() -> None:
    tpl = TEMPLATES.get("base.html", "")
    if not tpl:
        return

    _sair_pos = tpl.find('href="/logout">Sair</a>')
    if _sair_pos == -1:
        print("[fixes_batch4] base nav: Sair link nao encontrado")
        return

    _after = tpl[_sair_pos:_sair_pos + 400]
    if "{% else %}" in _after or "{%- else -%}" in _after or "{%- else %}" in _after or "{% else -%}" in _after:
        print("[fixes_batch4] base nav: else/endif intactos, nada a fazer")
        return

    m = _re_b4.search(
        r'(<a [^>]*href="/logout"[^>]*>Sair</a>)([\s]*)(</div>)',
        tpl,
    )
    if m:
        _old = m.group(0)
        _new = (
            m.group(1) + "\n"
            "          {% else %}\n"
            "            <a class=\"btn btn-outline-primary btn-sm\" href=\"/login\">Entrar</a>\n"
            "          {% endif %}\n"
            "        " + m.group(3)
        )
        tpl = tpl.replace(_old, _new, 1)
        TEMPLATES["base.html"] = tpl
        print("[fixes_batch4] base.html: {% else %}/{% endif %} restaurados apos dano do batch3")
    else:
        print("[fixes_batch4] base nav: padrao danificado nao encontrado (verifique manualmente)")


_b4_restore_base_nav()

print("[fixes_batch4] Todos os fixes do batch4 aplicados.")

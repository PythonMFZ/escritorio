# ============================================================================
# PATCH — Remove botão PDF ConstruRisk (mantém só Imprimir)
# ============================================================================
# A DirectData não suporta GeneratePDF para esses dossiês.
# O botão Imprimir já permite salvar como PDF pelo browser.
# Remove os botões "Baixar PDF" do histórico e da página de resultado.
# DEPLOY: adicione ao final do app.py
# ============================================================================

# ── Fix template resultado — remove botão PDF ─────────────────────────────────
_cr_resultado = TEMPLATES.get("construrisk_resultado.html", "")
if _cr_resultado and "Baixar PDF" in _cr_resultado:
    import re as _re_crpdf
    # Remove o bloco do botão PDF
    _cr_resultado = _re_crpdf.sub(
        r'<a href="/construrisk/.*?/pdf".*?Baixar PDF.*?</a>\s*',
        '',
        _cr_resultado,
        flags=_re_crpdf.DOTALL,
    )
    TEMPLATES["construrisk_resultado.html"] = _cr_resultado
    print("[fix_cr_pdf] ✅ Botão PDF removido do resultado")

# ── Fix template lista — remove botão PDF do histórico ───────────────────────
_cr_lista = TEMPLATES.get("construrisk.html", "")
if _cr_lista and "construrisk/{{ d.id }}/pdf" in _cr_lista:
    import re as _re_crpdf2
    _cr_lista = _re_crpdf2.sub(
        r'<a href="/construrisk/\{\{ d\.id \}\}/pdf".*?</a>\s*',
        '',
        _cr_lista,
        flags=_re_crpdf2.DOTALL,
    )
    TEMPLATES["construrisk.html"] = _cr_lista
    print("[fix_cr_pdf] ✅ Botão PDF removido do histórico")

if hasattr(templates_env.loader, "mapping"):
    templates_env.loader.mapping = TEMPLATES

print("[fix_cr_pdf] ✅ Patch concluído")

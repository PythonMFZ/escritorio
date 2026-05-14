# ============================================================================
# PATCH — Batch de fixes (batch7)
#
# 1. obras_nova_post: rota duplicada — FastAPI usa a 1ª registrada (original
#    sem etapas/sub-etapas). Remove a original para que nossa override funcione.
# 2. Gantt: adiciona linha vertical "hoje" em cada gantt-track.
# ============================================================================


# ── 1. Fix route override ─────────────────────────────────────────────────────

def _b7_fix_obras_nova_route() -> None:
    _removed = 0
    _new_routes = []
    _seen_nova_post = False

    for route in app.router.routes:
        path    = getattr(route, "path",    None)
        methods = getattr(route, "methods", None) or set()
        if path == "/ferramentas/obras/nova" and "POST" in methods:
            if not _seen_nova_post:
                # Primeira ocorrência: é a original (sem etapas) — remove
                _seen_nova_post = True
                _removed += 1
                print(f"[fixes_batch7] Removendo rota original: {route.endpoint.__name__}")
                continue
        _new_routes.append(route)

    if _removed:
        app.router.routes[:] = _new_routes
        print("[fixes_batch7] obras_nova_post: override com etapas/sub-etapas ativo")
    else:
        print("[fixes_batch7] obras_nova_post: nenhuma rota duplicada (ja ok)")


_b7_fix_obras_nova_route()


# ── 2. Gantt — linha "hoje" em cada track + header ────────────────────────────

def _b7_patch_gantt_hoje() -> None:
    tpl = TEMPLATES.get("ferramenta_obras_cronograma.html", "")
    if not tpl:
        print("[fixes_batch7] Gantt hoje: template nao encontrado")
        return
    if "_b7GanttHoje" in tpl:
        print("[fixes_batch7] Gantt hoje: ja aplicado")
        return

    _OLD_GANTT_CSS = (
        "  .gantt-row.se-row .gantt-label{padding-left:28px;color:#64748b;font-size:.72rem;}\n"
        "</style>"
    )
    _NEW_GANTT_CSS = (
        "  .gantt-row.se-row .gantt-label{padding-left:28px;color:#64748b;font-size:.72rem;}\n"
        "  .gantt-today-line{position:absolute;top:-4px;bottom:-4px;width:2px;"
        "background:#ef4444;opacity:.85;z-index:6;border-radius:1px;pointer-events:none;}\n"
        "  .gantt-today-lbl{position:absolute;top:-22px;transform:translateX(-50%);"
        "font-size:.58rem;color:#ef4444;font-weight:700;white-space:nowrap;"
        "background:#fff;padding:0 3px;border-radius:3px;border:1px solid #fca5a5;}\n"
        "  /* _b7GanttHoje */\n"
        "</style>"
    )

    _OLD_GANTT_END = (
        "  document.getElementById('ganttGrid').innerHTML = rows;\n"
        "}\n"
        "</script>"
    )
    _NEW_GANTT_END = (
        "  document.getElementById('ganttGrid').innerHTML = rows;\n"
        "  // Linha de hoje\n"
        "  (function() {\n"
        "    const now = new Date();\n"
        "    if (now < t0 || now > t1) return;\n"
        "    const pct = ((now - t0) / totalMs * 100).toFixed(2);\n"
        "    document.querySelectorAll('.gantt-track').forEach(function(track) {\n"
        "      const ln = document.createElement('div');\n"
        "      ln.className = 'gantt-today-line';\n"
        "      ln.style.left = pct + '%';\n"
        "      ln.title = 'Hoje: ' + now.toLocaleDateString('pt-BR');\n"
        "      track.appendChild(ln);\n"
        "    });\n"
        "    const hdr = document.getElementById('ganttMonths');\n"
        "    if (hdr) {\n"
        "      hdr.style.position = 'relative';\n"
        "      const lbl = document.createElement('div');\n"
        "      lbl.className = 'gantt-today-lbl';\n"
        "      lbl.style.left = pct + '%';\n"
        "      lbl.textContent = '▼ hoje';\n"
        "      hdr.appendChild(lbl);\n"
        "    }\n"
        "  })();\n"
        "}\n"
        "</script>"
    )

    changed = False

    if _OLD_GANTT_CSS in tpl:
        tpl = tpl.replace(_OLD_GANTT_CSS, _NEW_GANTT_CSS, 1)
        changed = True
        print("[fixes_batch7] Gantt: CSS linha hoje injetado")
    else:
        print("[fixes_batch7] Gantt: CSS anchor nao encontrado (verificar _seGanttV1)")

    if _OLD_GANTT_END in tpl:
        tpl = tpl.replace(_OLD_GANTT_END, _NEW_GANTT_END, 1)
        changed = True
        print("[fixes_batch7] Gantt: JS linha hoje injetado")
    else:
        print("[fixes_batch7] Gantt: JS anchor nao encontrado")

    if changed:
        TEMPLATES["ferramenta_obras_cronograma.html"] = tpl
        if hasattr(templates_env.loader, "mapping"):
            templates_env.loader.mapping = TEMPLATES


_b7_patch_gantt_hoje()

print("[fixes_batch7] Todos os fixes do batch7 aplicados.")

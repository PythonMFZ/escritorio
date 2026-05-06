# ============================================================================
# PATCH — Fix texto contexto interno Augur
# ============================================================================
# O marcador "CONTEXTO INTERNO — NÃO MENCIONAR AO CLIENTE" estava
# fazendo o Claude gerar alertas técnicos desnecessários.
# DEPLOY: adicione ao final do app.py
# ============================================================================

try:
    import ai_assistant.assistant as _augur_fix_ctx

    _ask_atual = _augur_fix_ctx.ask

    def _ask_sem_alerta(
        question: str,
        client_data: dict,
        n_similar_cases: int = 4,
        conversation_history: list = None,
        attachments: list = None,
    ) -> dict:
        import requests as _req_fctx
        import os as _os_fctx

        ANTHROPIC_API_KEY = _os_fctx.environ.get("ANTHROPIC_API_KEY", "")
        if not ANTHROPIC_API_KEY:
            return {"response": "Augur não configurado.", "confidence": 0.0, "error": True, "error_message": "API key ausente"}

        seg = (client_data.get("segment") or "").lower()

        try:
            from ai_assistant.vector_store import search_similar_cases as _search
            similar = _search(
                question, n_results=n_similar_cases,
                segmento=seg if seg in ("pme", "middle", "construtora") else None
            )
        except Exception:
            similar = []

        confidence = sum(c.get("similarity", 0) for c in similar) / max(len(similar), 1)

        ctx = _augur_fix_ctx._format_client_context(client_data)

        # ← FIX: texto neutro que não aciona alertas do Claude
        if similar:
            ctx += "\n\n=== REFERÊNCIAS DE CASOS SIMILARES ==="
            ctx += "\nExemplos anônimos de situações parecidas para calibrar a resposta:"
            for c in similar:
                if c.get("similarity", 0) > 0.3:
                    segmento    = c.get("segmento", "empresa")
                    setor       = c.get("full", {}).get("setor", "") or ""
                    problema    = c.get("problema", "")[:200]
                    solucao     = c.get("solucao", "")[:200]
                    aprendizado = c.get("aprendizado", "")[:150]

                    ctx += f"\n— Segmento: {segmento}"
                    if setor:
                        ctx += f" | Setor: {setor}"
                    ctx += f"\n  Situação: {problema}"
                    ctx += f"\n  Abordagem: {solucao}"
                    if aprendizado:
                        ctx += f"\n  Aprendizado: {aprendizado}"

        messages = list(conversation_history or [])

        user_content = []
        if attachments:
            for att in attachments:
                att_type = att.get("type", "")
                att_data = att.get("data", "")
                att_name = att.get("name", "arquivo")
                if att_type == "pdf":
                    user_content.append({"type": "document", "source": {"type": "base64", "media_type": "application/pdf", "data": att_data}, "title": att_name})
                elif att_type in ("image/jpeg", "image/png", "image/gif", "image/webp"):
                    user_content.append({"type": "image", "source": {"type": "base64", "media_type": att_type, "data": att_data}})
                elif att_type in ("csv", "xlsx"):
                    user_content.append({"type": "text", "text": f"[Arquivo: {att_name}]\n{att_data}"})

        user_content.append({"type": "text", "text": f"{ctx}\n\n=== PERGUNTA ===\n{question}"})

        if len(user_content) == 1:
            messages.append({"role": "user", "content": user_content[0]["text"]})
        else:
            messages.append({"role": "user", "content": user_content})

        try:
            resp = _req_fctx.post(
                "https://api.anthropic.com/v1/messages",
                headers={"x-api-key": ANTHROPIC_API_KEY, "anthropic-version": "2023-06-01", "content-type": "application/json"},
                json={"model": "claude-sonnet-4-6", "max_tokens": 1500, "system": _augur_fix_ctx.AUGUR_SYSTEM_PROMPT, "messages": messages},
                timeout=120,
            )
            resp.raise_for_status()
            return {"response": resp.json()["content"][0]["text"], "confidence": round(confidence, 3), "error": False, "error_message": ""}
        except Exception as e:
            return {"response": "Não consegui processar sua pergunta agora. Tente novamente.", "confidence": 0.0, "error": True, "error_message": str(e)}

    _augur_fix_ctx.ask = _ask_sem_alerta
    print("[fix_augur_ctx] ✅ Texto do contexto interno corrigido — sem alertas")

except Exception as _e_fctx:
    print(f"[fix_augur_ctx] ⚠️ Erro: {_e_fctx}")

# ============================================================================
# PATCH — Augur Privacy Fix
# Corrige dois vetores de vazamento de dados entre clientes:
#
# 1. RAG (casos_estruturados.jsonl): remove nomes/títulos identificáveis
#    antes de injetar no contexto do Augur
#
# 2. Notion (_get_reunioes_cliente): remove inclusão de reuniões recentes
#    sem match do cliente — só inclui reuniões que mencionam explicitamente
#    o cliente atual
#
# DEPLOY: adicione ao final do app.py (após ui_upgrade_augur.py)
# ============================================================================

import sys as _sys_pf
import os as _os_pf

# ── Patch 1: Substitui a função ask() no assistant.py para anonimizar RAG ──

try:
    import ai_assistant.assistant as _augur_assistant

    _ask_original = _augur_assistant.ask

    def _ask_privacy_safe(
        question: str,
        client_data: dict,
        n_similar_cases: int = 4,
        conversation_history: list = None,
        attachments: list = None,
    ) -> dict:
        """
        Wrapper que anonimiza os casos similares do RAG antes de injetar
        no contexto, removendo campos identificáveis (titulo, notion_url, caso_id).
        """
        import requests as _req_pf
        import os as _os_pf2

        ANTHROPIC_API_KEY = _os_pf2.environ.get("ANTHROPIC_API_KEY", "")
        if not ANTHROPIC_API_KEY:
            return {"response": "Augur não configurado.", "confidence": 0.0, "error": True, "error_message": "API key ausente"}

        seg = (client_data.get("segment") or "").lower()

        # Busca casos similares
        try:
            from ai_assistant.vector_store import search_similar_cases as _search
            similar = _search(
                question, n_results=n_similar_cases,
                segmento=seg if seg in ("pme", "middle", "construtora") else None
            )
        except Exception:
            similar = []

        confidence = sum(c.get("similarity", 0) for c in similar) / max(len(similar), 1)

        # Formata contexto do cliente
        ctx = _augur_assistant._format_client_context(client_data)

        # ── FIX 1: Injeta casos RAG SEM campos identificáveis ──────────────────
        if similar:
            ctx += "\n\n=== CONTEXTO INTERNO — NÃO MENCIONAR AO CLIENTE ==="
            ctx += "\nUse os casos abaixo para calibrar sua resposta. Não cite nomes, empresas ou detalhes identificáveis."
            for c in similar:
                if c.get("similarity", 0) > 0.3:
                    # Remove titulo, notion_url, caso_id — só usa conteúdo anônimo
                    segmento   = c.get("segmento", "empresa")
                    setor      = c.get("full", {}).get("setor", "") or ""
                    problema   = c.get("problema", "")[:200]
                    solucao    = c.get("solucao", "")[:200]
                    aprendizado = c.get("aprendizado", "")[:150]
                    resultado  = c.get("resultado", "")[:150]

                    ctx += f"\n— Segmento: {segmento}"
                    if setor:
                        ctx += f" | Setor: {setor}"
                    ctx += f"\n  Problema similar: {problema}"
                    ctx += f"\n  Solução adotada: {solucao}"
                    if aprendizado:
                        ctx += f"\n  Aprendizado: {aprendizado}"
                    if resultado:
                        ctx += f"\n  Resultado: {resultado}"

        messages = list(conversation_history or [])

        # Monta mensagem do usuário com contexto + anexos
        user_content = []

        if attachments:
            for att in attachments:
                att_type = att.get("type", "")
                att_data = att.get("data", "")
                att_name = att.get("name", "arquivo")

                if att_type == "pdf":
                    user_content.append({
                        "type": "document",
                        "source": {
                            "type": "base64",
                            "media_type": "application/pdf",
                            "data": att_data,
                        },
                        "title": att_name,
                    })
                elif att_type in ("image/jpeg", "image/png", "image/gif", "image/webp"):
                    user_content.append({
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": att_type,
                            "data": att_data,
                        },
                    })
                elif att_type in ("csv", "xlsx"):
                    user_content.append({
                        "type": "text",
                        "text": f"[Arquivo: {att_name}]\n{att_data}",
                    })

        user_content.append({
            "type": "text",
            "text": f"{ctx}\n\n=== PERGUNTA ===\n{question}",
        })

        if len(user_content) == 1:
            messages.append({"role": "user", "content": user_content[0]["text"]})
        else:
            messages.append({"role": "user", "content": user_content})

        try:
            resp = _req_pf.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": ANTHROPIC_API_KEY,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": "claude-sonnet-4-6",
                    "max_tokens": 1500,
                    "system": _augur_assistant.AUGUR_SYSTEM_PROMPT,
                    "messages": messages,
                },
                timeout=120,
            )
            resp.raise_for_status()
            return {
                "response": resp.json()["content"][0]["text"],
                "confidence": round(confidence, 3),
                "error": False,
                "error_message": "",
            }
        except Exception as e:
            return {
                "response": "Não consegui processar sua pergunta agora. Tente novamente.",
                "confidence": 0.0,
                "error": True,
                "error_message": str(e),
            }

    # Substitui a função ask do módulo
    _augur_assistant.ask = _ask_privacy_safe
    print("[augur_privacy_fix] ✅ Patch 1 aplicado: RAG anonimizado")

except Exception as _e_pf1:
    print(f"[augur_privacy_fix] ⚠️  Patch 1 falhou: {_e_pf1}")


# ── Patch 2: Corrige _get_reunioes_cliente para NÃO incluir reuniões ────────
#             recentes de outros clientes (remove bloco `elif data >= ultima_semana`)

try:
    import ai_assistant.assistant as _augur_assistant2

    def _get_reunioes_cliente_safe(client_name: str, limit: int = 5) -> list:
        """
        Busca reuniões do Notion SOMENTE se mencionarem explicitamente o cliente.
        Remove a lógica anterior que incluía qualquer reunião recente da semana,
        o que causava vazamento de dados de outros clientes.
        """
        try:
            import requests as _req2
            from datetime import datetime as _dt2, timedelta as _td2
            import os as _os2

            notion_token = (
                _os2.environ.get("NOTION_TOKEN") or
                _os2.environ.get("NOTION_API_KEY") or ""
            )
            notion_db_id = _os2.environ.get("NOTION_MEETINGS_DB_ID", "")

            if not notion_token or not notion_db_id:
                return []

            headers = {
                "Authorization": f"Bearer {notion_token}",
                "Notion-Version": "2022-06-28",
                "Content-Type": "application/json",
            }

            url = f"https://api.notion.com/v1/databases/{notion_db_id}/query"
            resp = _req2.post(url, headers=headers, json={
                "page_size": 10,  # busca mais para aumentar chance de achar o cliente
                "sorts": [{"timestamp": "created_time", "direction": "descending"}],
            }, timeout=10)
            resp.raise_for_status()
            pages = resp.json().get("results", [])

            # Palavras-chave do cliente (mínimo 3 chars para evitar falsos positivos)
            palavras = [p.strip().lower() for p in client_name.replace("-", "").split() if len(p) >= 3]
            if not palavras:
                return []

            prioritarias = []

            for page in pages:
                props = page.get("properties", {})
                titulo = ""
                for key in ("Nome da reunião", "Name", "Título", "Title", "nome", "título"):
                    prop = props.get(key, {})
                    tl = prop.get("title", [])
                    if tl:
                        titulo = tl[0].get("plain_text", "")
                        break

                data = (page.get("created_time") or "")[:10]
                titulo_lower = titulo.lower()

                # ── FIX 2: SOMENTE inclui se o título mencionar o cliente ──────
                menciona_titulo = any(p in titulo_lower for p in palavras)

                if not menciona_titulo:
                    # Verifica no conteúdo também, mas só inclui se mencionar
                    conteudo = _augur_assistant2._extrair_texto_bloco(
                        page["id"], headers, profundidade=0, max_prof=3
                    )
                    menciona_conteudo = any(p in conteudo.lower() for p in palavras)

                    if not menciona_conteudo:
                        # ← REMOVIDO: não inclui mais reuniões recentes sem match
                        continue

                    item = {
                        "titulo": titulo,
                        "data":   data,
                        "resumo": conteudo[:800],
                        "acoes":  "",
                    }
                else:
                    conteudo = _augur_assistant2._extrair_texto_bloco(
                        page["id"], headers, profundidade=0, max_prof=3
                    )
                    item = {
                        "titulo": titulo,
                        "data":   data,
                        "resumo": conteudo[:800],
                        "acoes":  "",
                    }

                prioritarias.append(item)
                if len(prioritarias) >= limit:
                    break

            return prioritarias[:limit]

        except Exception as e:
            print(f"[augur] Erro ao buscar reuniões Notion: {e}")
            return []

    # Substitui a função no módulo
    _augur_assistant2._get_reunioes_cliente = _get_reunioes_cliente_safe
    print("[augur_privacy_fix] ✅ Patch 2 aplicado: reuniões Notion filtradas por cliente")

except Exception as _e_pf2:
    print(f"[augur_privacy_fix] ⚠️  Patch 2 falhou: {_e_pf2}")


print("[augur_privacy_fix] ✅ Privacy fix completo — vazamento de dados corrigido")

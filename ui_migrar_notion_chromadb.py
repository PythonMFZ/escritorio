# ui_migrar_notion_chromadb.py
# Migra as 223 reuniões do casos_estruturados.jsonl → BaseConhecimento (PostgreSQL)
# e substitui busca ChromaDB por SQL na função de contexto do Augur.
# Exec'd uma vez; idempotente (não duplica registros).

import json as _json_mn
import os   as _os_mn
from pathlib import Path as _Path_mn

_JSONL_PATH = _Path_mn(__file__).parent / "ai_assistant" / "casos_estruturados.jsonl"
_COMPANY_ID_MAFFEZZOLLI = 1   # company_id da Maffezzolli Capital no banco
_CLIENT_ID_GLOBAL        = 0  # client_id=0 = conhecimento geral da empresa (não por cliente)
_TIPO = "caso_historico_notion"

def _mn_build_texto(caso: dict) -> str:
    """Monta texto estruturado legível para o Augur — sem título, data ou nomes."""
    parts = []
    # ⚠️ título e data omitidos intencionalmente — contêm nomes de clientes
    if caso.get("segmento"):
        parts.append(f"Segmento: {caso['segmento']} | Setor: {caso.get('setor','')}")
    if caso.get("problema_principal"):
        parts.append(f"Problema principal: {caso['problema_principal']}")
    if caso.get("problemas_secundarios"):
        parts.append("Problemas secundários:\n" + "\n".join(f"  - {p}" for p in caso["problemas_secundarios"]))
    df = caso.get("dados_financeiros") or {}
    if df:
        parts.append("Dados financeiros: " + "; ".join(f"{k}={v}" for k, v in df.items() if v))
    if caso.get("solucao_recomendada"):
        parts.append(f"Solução recomendada: {caso['solucao_recomendada']}")
    if caso.get("produtos_sugeridos"):
        parts.append("Produtos sugeridos: " + ", ".join(caso["produtos_sugeridos"]))
    if caso.get("resultado"):
        parts.append(f"Resultado: {caso['resultado']}")
    if caso.get("aprendizado"):
        parts.append(f"Aprendizado: {caso['aprendizado']}")
    if caso.get("tags"):
        parts.append("Tags: " + ", ".join(caso["tags"]))
    if caso.get("resumo_para_busca"):
        parts.append(f"Resumo: {caso['resumo_para_busca']}")
    return "\n\n".join(parts)


def _mn_run_migration():
    if not _JSONL_PATH.exists():
        print("[migrar_notion] casos_estruturados.jsonl não encontrado — pulando migração")
        return

    from sqlmodel import Session as _MnSes, select as _mn_sel
    try:
        with _MnSes(engine) as s:  # type: ignore[name-defined]
            existing = s.exec(
                _mn_sel(BaseConhecimento).where(  # type: ignore[name-defined]
                    BaseConhecimento.tipo == _TIPO,  # type: ignore[name-defined]
                    BaseConhecimento.company_id == _COMPANY_ID_MAFFEZZOLLI,
                )
            ).all()
            existing_nomes = {e.nome for e in existing}

            with open(_JSONL_PATH) as f:
                casos = [_json_mn.loads(l) for l in f if l.strip()]

            novos = 0
            for caso in casos:
                # Usa caso_id como nome — sem título (contém nome de cliente)
                nome = (caso.get("caso_id") or f"caso_{casos.index(caso)+1:04d}")[:200]
                if nome in existing_nomes:
                    continue
                texto = _mn_build_texto(caso)
                bc = BaseConhecimento(  # type: ignore[name-defined]
                    company_id=_COMPANY_ID_MAFFEZZOLLI,
                    client_id=_CLIENT_ID_GLOBAL,
                    user_id=0,
                    nome=nome,
                    descricao=(caso.get("problema_principal") or "")[:500],
                    tipo=_TIPO,
                    conteudo_texto=texto,
                    created_at=utcnow().isoformat(),  # type: ignore[name-defined]
                )
                s.add(bc)
                novos += 1

            if novos:
                s.commit()
                print(f"[migrar_notion] ✅ {novos} casos históricos migrados para BaseConhecimento")
            else:
                print(f"[migrar_notion] Já migrado ({len(existing)} registros existentes)")
    except Exception as _e_mn:
        print(f"[migrar_notion] Erro: {_e_mn}")


_mn_run_migration()


# ── Substitui busca ChromaDB por SQL na função de contexto do Augur ───────────

def _mn_search_casos_pg(pergunta: str, n: int = 4, company_id: int = _COMPANY_ID_MAFFEZZOLLI,
                        client_id: int = None) -> list:
    """Busca no PostgreSQL usando palavras-chave.

    Retorna registros de:
      - client_id=0  (conhecimento geral / casos históricos anônimos)
      - client_id=<client_id>  (dados específicos do cliente, se fornecido)
    Nunca mistura dados de clientes diferentes.
    """
    from sqlmodel import Session as _MnSes2, select as _mn_sel2, or_ as _or_mn
    import re as _re_mn
    palavras = [p for p in _re_mn.split(r'\W+', pergunta.lower()) if len(p) > 3][:8]
    if not palavras:
        palavras = [pergunta[:30]]
    try:
        with _MnSes2(engine) as s:  # type: ignore[name-defined]
            # Filtro de client_id: sempre inclui global (0); se houver cliente específico, inclui também
            if client_id:
                cid_filter = _or_mn(
                    BaseConhecimento.client_id == _CLIENT_ID_GLOBAL,  # type: ignore[name-defined]
                    BaseConhecimento.client_id == client_id,
                )
            else:
                cid_filter = (BaseConhecimento.client_id == _CLIENT_ID_GLOBAL)  # type: ignore[name-defined]

            todos = s.exec(
                _mn_sel2(BaseConhecimento).where(  # type: ignore[name-defined]
                    BaseConhecimento.company_id == company_id,
                    cid_filter,
                )
            ).all()
            scored = []
            for bc in todos:
                texto_lower = (bc.conteudo_texto + " " + bc.nome + " " + (bc.descricao or "")).lower()
                score = sum(1 for p in palavras if p in texto_lower)
                # Prioriza dados do cliente específico sobre conhecimento geral
                if bc.client_id and bc.client_id != _CLIENT_ID_GLOBAL:
                    score += 5
                if score > 0:
                    scored.append((score, bc))
            scored.sort(key=lambda x: -x[0])
            return [bc for _, bc in scored[:n]]
    except Exception as _e_s:
        print(f"[migrar_notion] search erro: {_e_s}")
        return []


# ── Patch na função de contexto do Augur (ui_fix_augur_ctx_texto.py) ─────────
try:
    import ui_fix_augur_ctx_texto as _fctx_mod

    _fctx_ask_orig = _fctx_mod._ask_sem_alerta

    def _ask_pg_casos(question, client_data, n_similar_cases=4,
                      conversation_history=None, attachments=None):
        """Mesma função mas usa PostgreSQL em vez de ChromaDB."""
        import os as _os_fctx2, requests as _req_fctx2
        ANTHROPIC_API_KEY = _os_fctx2.environ.get("ANTHROPIC_API_KEY", "")
        if not ANTHROPIC_API_KEY:
            return {"response": "Augur não configurado.", "confidence": 0.0,
                    "error": True, "error_message": "API key ausente"}

        # Busca casos similares no PostgreSQL (inclui dados específicos do cliente se disponível)
        _cid_ask = client_data.get("client_id") or client_data.get("id")
        casos_pg = _mn_search_casos_pg(question, n=n_similar_cases, client_id=_cid_ask)

        import ai_assistant.assistant as _aug_ast
        ctx = _aug_ast._format_client_context(client_data)

        if casos_pg:
            ctx += "\n\n=== REFERÊNCIAS DE CASOS SIMILARES ==="
            ctx += "\nExemplos de situações atendidas anteriormente para calibrar a resposta:"
            for bc in casos_pg:
                ctx += f"\n— {bc.nome}"
                # Extrai campos do texto estruturado
                for linha in bc.conteudo_texto.split("\n"):
                    if linha.startswith(("Segmento:", "Problema principal:", "Solução:", "Aprendizado:")):
                        ctx += f"\n  {linha}"

        messages = list(conversation_history or [])
        user_content = []
        if attachments:
            for att in (attachments or []):
                att_type = att.get("type", "")
                att_data = att.get("data", "")
                att_name = att.get("name", "arquivo")
                if att_type == "pdf":
                    user_content.append({"type": "document",
                        "source": {"type": "base64", "media_type": "application/pdf", "data": att_data},
                        "title": att_name})
                elif att_type in ("image/jpeg", "image/png", "image/gif", "image/webp"):
                    user_content.append({"type": "image",
                        "source": {"type": "base64", "media_type": att_type, "data": att_data}})
                elif att_type in ("csv", "xlsx"):
                    user_content.append({"type": "text", "text": f"[Arquivo: {att_name}]\n{att_data}"})

        user_content.append({"type": "text", "text": f"{ctx}\n\n=== PERGUNTA ===\n{question}"})

        if len(user_content) == 1:
            user_content = user_content[0]["text"]

        messages.append({"role": "user", "content": user_content})

        try:
            resp = _req_fctx2.post(
                "https://api.anthropic.com/v1/messages",
                headers={"x-api-key": ANTHROPIC_API_KEY,
                         "anthropic-version": "2023-06-01",
                         "content-type": "application/json"},
                json={"model": "claude-opus-4-8",
                      "max_tokens": 2048,
                      "system": _aug_ast.SYSTEM_PROMPT,
                      "messages": messages},
                timeout=90,
            )
            resp.raise_for_status()
            data = resp.json()
            text = (data.get("content") or [{}])[0].get("text", "")
            return {"response": text, "confidence": min(1.0, len(casos_pg) * 0.25),
                    "similar_cases_used": len(casos_pg)}
        except Exception as _e_ask:
            return {"response": f"Erro ao consultar Augur: {_e_ask}",
                    "confidence": 0.0, "error": True}

    _fctx_mod._ask_sem_alerta = _ask_pg_casos
    # Propaga para o módulo raiz se existir
    try:
        import assistant as _ass_root
        if hasattr(_ass_root, "ask"):
            _ass_root.ask = _ask_pg_casos
    except Exception:
        pass
    print("[migrar_notion] ✅ Augur agora usa PostgreSQL em vez de ChromaDB")
except Exception as _e_patch:
    print(f"[migrar_notion] patch Augur: {_e_patch}")

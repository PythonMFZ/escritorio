"""
vector_store.py — Etapa 3
Salva os casos estruturados no ChromaDB (banco vetorial local).
Permite busca semântica por similaridade.
"""

import os
import json
from typing import Optional

# ChromaDB usa SQLite por baixo — sem dependência de PostgreSQL
try:
    import chromadb
    from chromadb.utils import embedding_functions
    CHROMA_AVAILABLE = True
except ImportError:
    CHROMA_AVAILABLE = False
    print("[vector_store] ⚠️  ChromaDB não instalado. Rode: pip install chromadb")


CHROMA_PATH       = os.environ.get("CHROMA_PATH", "ai_assistant/chroma_db")
COLLECTION_NAME   = "reunioes_maffezzolli"
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")


def _get_client():
    """Retorna o cliente ChromaDB (persistente em disco)."""
    if not CHROMA_AVAILABLE:
        raise ImportError("ChromaDB não instalado.")
    os.makedirs(CHROMA_PATH, exist_ok=True)
    return chromadb.PersistentClient(path=CHROMA_PATH)


def _get_collection(client=None):
    """Retorna (ou cria) a collection de reuniões."""
    if client is None:
        client = _get_client()

    # Usa embeddings do sentence-transformers (grátis, roda local)
    # Alternativa: usar embeddings da OpenAI/Anthropic (pago, melhor qualidade)
    ef = embedding_functions.DefaultEmbeddingFunction()

    collection = client.get_or_create_collection(
        name=COLLECTION_NAME,
        embedding_function=ef,
        metadata={"hnsw:space": "cosine"},
    )
    return collection


def _case_to_document(caso: dict) -> tuple[str, dict]:
    """
    Converte um caso estruturado em (texto para embedding, metadados).
    O texto precisa capturar bem a essência para a busca semântica funcionar.
    """
    parts = []

    if caso.get("resumo_para_busca"):
        parts.append(caso["resumo_para_busca"])

    if caso.get("problema_principal"):
        parts.append(f"Problema: {caso['problema_principal']}")

    if caso.get("solucao_recomendada"):
        parts.append(f"Solução: {caso['solucao_recomendada']}")

    if caso.get("aprendizado"):
        parts.append(f"Aprendizado: {caso['aprendizado']}")

    if caso.get("tags"):
        parts.append(f"Tags: {', '.join(caso['tags'])}")

    document = " | ".join(parts)

    # Metadados para filtro (ChromaDB só aceita str/int/float/bool)
    metadata = {
        "caso_id":   str(caso.get("caso_id", "")),
        "titulo":    str(caso.get("titulo", ""))[:500],
        "data":      str(caso.get("data", "")),
        "segmento":  str(caso.get("segmento", "indefinido")),
        "setor":     str(caso.get("setor", ""))[:200],
        "problema":  str(caso.get("problema_principal", ""))[:500],
        "solucao":   str(caso.get("solucao_recomendada", ""))[:500],
        "resultado": str(caso.get("resultado", "") or "")[:300],
        "aprendizado": str(caso.get("aprendizado", "") or "")[:300],
        "notion_url": str(caso.get("notion_url", ""))[:500],
        "produtos":  ", ".join(caso.get("produtos_sugeridos", []))[:300],
        "tags":      ", ".join(caso.get("tags", []))[:300],
        "full_json": json.dumps(caso, ensure_ascii=False)[:2000],
    }

    return document, metadata


def index_cases(casos: list[dict], batch_size: int = 50) -> int:
    """
    Indexa uma lista de casos estruturados no ChromaDB.
    Retorna o número de casos indexados com sucesso.
    """
    collection = _get_collection()
    indexed = 0

    print(f"[vector_store] Indexando {len(casos)} casos...")

    for i in range(0, len(casos), batch_size):
        batch = casos[i:i + batch_size]

        ids, documents, metadatas = [], [], []
        for caso in batch:
            caso_id = caso.get("caso_id", f"caso_{i}")
            doc, meta = _case_to_document(caso)
            if doc.strip():
                ids.append(caso_id)
                documents.append(doc)
                metadatas.append(meta)

        if ids:
            try:
                collection.upsert(
                    ids=ids,
                    documents=documents,
                    metadatas=metadatas,
                )
                indexed += len(ids)
                print(f"[vector_store]   ✅ Batch {i//batch_size + 1}: {len(ids)} casos indexados")
            except Exception as e:
                print(f"[vector_store]   ❌ Erro no batch {i//batch_size + 1}: {e}")

    total = collection.count()
    print(f"[vector_store] Total na collection: {total} casos")
    return indexed


def search_similar_cases(
    query: str,
    n_results: int = 5,
    segmento: Optional[str] = None,
) -> list[dict]:
    """
    Busca os N casos mais similares à query.

    Args:
        query: texto da pergunta do usuário
        n_results: quantos casos retornar
        segmento: filtrar por segmento (pme/middle/construtora)

    Returns:
        Lista de casos similares com score de similaridade
    """
    collection = _get_collection()

    if collection.count() == 0:
        return []

    # Filtro opcional por segmento
    where = None
    if segmento and segmento in ("pme", "middle", "construtora"):
        where = {"segmento": segmento}

    try:
        results = collection.query(
            query_texts=[query],
            n_results=min(n_results, collection.count()),
            where=where,
            include=["documents", "metadatas", "distances"],
        )

        casos_similares = []
        for j, (doc, meta, dist) in enumerate(zip(
            results["documents"][0],
            results["metadatas"][0],
            results["distances"][0],
        )):
            # Converte distância cosine para similaridade (0-1)
            similarity = round(1 - dist, 3)

            # Tenta recuperar o JSON completo
            full = {}
            try:
                full = json.loads(meta.get("full_json", "{}"))
            except Exception:
                pass

            casos_similares.append({
                "caso_id":    meta.get("caso_id", ""),
                "titulo":     meta.get("titulo", ""),
                "data":       meta.get("data", ""),
                "segmento":   meta.get("segmento", ""),
                "problema":   meta.get("problema", ""),
                "solucao":    meta.get("solucao", ""),
                "resultado":  meta.get("resultado", ""),
                "aprendizado": meta.get("aprendizado", ""),
                "produtos":   meta.get("produtos", ""),
                "notion_url": meta.get("notion_url", ""),
                "similarity": similarity,
                "full":       full,
            })

        return casos_similares

    except Exception as e:
        print(f"[vector_store] Erro na busca: {e}")
        return []


def get_stats() -> dict:
    """Retorna estatísticas da collection."""
    try:
        collection = _get_collection()
        return {
            "total_casos": collection.count(),
            "collection": COLLECTION_NAME,
            "path": CHROMA_PATH,
        }
    except Exception as e:
        return {"error": str(e)}


if __name__ == "__main__":
    stats = get_stats()
    print(f"Stats: {stats}")

    if stats.get("total_casos", 0) > 0:
        print("\nTeste de busca:")
        results = search_similar_cases("empresa com caixa apertado e dívida alta", n_results=3)
        for r in results:
            print(f"\n  [{r['similarity']:.0%}] {r['titulo']}")
            print(f"  Problema: {r['problema'][:100]}")
            print(f"  Solução:  {r['solucao'][:100]}")

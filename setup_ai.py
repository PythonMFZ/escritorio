"""
setup_ai.py — Script de setup do Assistente Maffezzolli
Roda as 3 etapas em sequência:
  1. Extrai reuniões do Notion
  2. Estrutura cada reunião em caso clínico (via Claude Haiku)
  3. Indexa no ChromaDB

USO:
  # Instalar dependências primeiro:
  pip install chromadb requests

  # Rodar setup completo:
  python setup_ai.py

  # Testar com apenas 5 reuniões:
  python setup_ai.py --limit 5

  # Pular extração (se já tem o JSONL):
  python setup_ai.py --skip-extract

  # Só reindexar (se já tem o JSONL estruturado):
  python setup_ai.py --only-index
"""

import os
import sys
import json
import argparse

# Garante que o diretório raiz está no path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def check_env():
    """Verifica se as variáveis de ambiente estão definidas."""
    missing = []
    for var in ("ANTHROPIC_API_KEY", "NOTION_API_KEY", "NOTION_MEETINGS_DB_ID"):
        if not os.environ.get(var):
            missing.append(var)
    if missing:
        print(f"❌ Variáveis de ambiente faltando: {', '.join(missing)}")
        print("\nDefina-as antes de rodar:")
        for var in missing:
            print(f"  export {var}=seu_valor")
        sys.exit(1)
    print("✅ Variáveis de ambiente OK")


def check_dependencies():
    """Verifica se as dependências estão instaladas."""
    missing = []
    try:
        import chromadb
    except ImportError:
        missing.append("chromadb")
    try:
        import requests
    except ImportError:
        missing.append("requests")

    if missing:
        print(f"❌ Dependências faltando: {', '.join(missing)}")
        print(f"\nInstale com:")
        print(f"  pip install {' '.join(missing)}")
        sys.exit(1)
    print("✅ Dependências OK")


def main():
    parser = argparse.ArgumentParser(description="Setup do Assistente Maffezzolli")
    parser.add_argument("--limit", type=int, default=None,
                        help="Limitar número de reuniões (para teste)")
    parser.add_argument("--skip-extract", action="store_true",
                        help="Pular extração (usa JSONL existente)")
    parser.add_argument("--only-index", action="store_true",
                        help="Só indexar (pula extração e estruturação)")
    parser.add_argument("--jsonl", default="ai_assistant/casos_estruturados.jsonl",
                        help="Caminho do arquivo JSONL")
    args = parser.parse_args()

    print("\n" + "="*60)
    print("  SETUP DO ASSISTENTE MAFFEZZOLLI")
    print("="*60 + "\n")

    check_dependencies()
    check_env()

    casos: list[dict] = []

    # ── ETAPA 1: Extração ────────────────────────────────────────
    if not args.skip_extract and not args.only_index:
        print("\n📥 ETAPA 1: Extraindo reuniões do Notion...")
        print("-" * 40)
        from ai_assistant.extractor import extract_all_meetings
        meetings = extract_all_meetings(limit=args.limit)
        print(f"\n✅ {len(meetings)} reuniões extraídas")

        if not meetings:
            print("❌ Nenhuma reunião encontrada. Verifique:")
            print("   - NOTION_MEETINGS_DB_ID está correto?")
            print("   - A integração tem acesso à database?")
            sys.exit(1)
    else:
        meetings = []
        print("\n⏩ Etapa 1 pulada")

    # ── ETAPA 2: Estruturação ─────────────────────────────────────
    if not args.only_index:
        if meetings:
            print(f"\n🧠 ETAPA 2: Estruturando {len(meetings)} reuniões com IA...")
            print("-" * 40)
            print(f"   Usando Claude Haiku (~R$ 0,001 por reunião)")
            custo_est = len(meetings) * 0.001
            print(f"   Custo estimado: R$ {custo_est:.2f}")
            print(f"   Tempo estimado: {len(meetings) * 2 // 60}min {len(meetings) * 2 % 60}s\n")

            confirm = input("Continuar? (s/n): ").strip().lower()
            if confirm != "s":
                print("Abortado.")
                sys.exit(0)

            from ai_assistant.structurer import structure_all_meetings
            casos = structure_all_meetings(meetings, save_path=args.jsonl)
            print(f"\n✅ {len(casos)} casos estruturados → {args.jsonl}")
        else:
            # Carrega JSONL existente
            if os.path.exists(args.jsonl):
                from ai_assistant.structurer import load_structured_cases
                casos = load_structured_cases(args.jsonl)
                print(f"\n✅ {len(casos)} casos carregados de {args.jsonl}")
            else:
                print(f"❌ Arquivo {args.jsonl} não encontrado")
                sys.exit(1)
    else:
        # Só indexação: carrega o JSONL
        if os.path.exists(args.jsonl):
            from ai_assistant.structurer import load_structured_cases
            casos = load_structured_cases(args.jsonl)
            print(f"\n✅ {len(casos)} casos carregados de {args.jsonl}")
        else:
            print(f"❌ Arquivo {args.jsonl} não encontrado")
            sys.exit(1)

    # ── ETAPA 3: Indexação ────────────────────────────────────────
    print(f"\n🔍 ETAPA 3: Indexando {len(casos)} casos no ChromaDB...")
    print("-" * 40)

    from ai_assistant.vector_store import index_cases, get_stats
    indexed = index_cases(casos)

    stats = get_stats()
    print(f"\n✅ {indexed} casos indexados")
    print(f"   Total na base: {stats.get('total_casos', '?')} casos")
    print(f"   Local: {stats.get('path', '?')}")

    # ── TESTE RÁPIDO ──────────────────────────────────────────────
    print("\n🧪 TESTE RÁPIDO DE BUSCA")
    print("-" * 40)
    from ai_assistant.vector_store import search_similar_cases
    results = search_similar_cases("empresa com caixa apertado", n_results=3)
    if results:
        print("Busca funcionando! Top 3 resultados:")
        for r in results:
            print(f"  [{r['similarity']:.0%}] {r['titulo'][:60]}")
    else:
        print("Nenhum resultado — base vazia ou erro de busca")

    print("\n" + "="*60)
    print("  SETUP CONCLUÍDO!")
    print("="*60)
    print("\nPróximo passo: adicionar a rota /api/ai/ask no app.py")
    print("Execute: python setup_ai.py --help para opções\n")


if __name__ == "__main__":
    main()

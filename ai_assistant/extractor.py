"""
extractor.py — Etapa 1
Extrai todas as reuniões da database do Notion e retorna
uma lista de dicts prontos para estruturação.
"""

import os
import time
import requests
from typing import Optional

NOTION_API_KEY = os.environ.get("NOTION_API_KEY", "")
NOTION_DB_ID   = os.environ.get("NOTION_MEETINGS_DB_ID", "")

HEADERS = {
    "Authorization": f"Bearer {NOTION_API_KEY}",
    "Notion-Version": "2022-06-28",
    "Content-Type": "application/json",
}


def _get_page_text(page_id: str) -> str:
    """
    Busca o conteúdo completo de uma página do Notion
    (blocos de texto, incluindo transcrição, notas e resumo).
    """
    url = f"https://api.notion.com/v1/blocks/{page_id}/children"
    all_text: list[str] = []
    cursor = None

    while True:
        params = {"page_size": 100}
        if cursor:
            params["start_cursor"] = cursor

        resp = requests.get(url, headers=HEADERS, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()

        for block in data.get("results", []):
            btype = block.get("type", "")
            block_data = block.get(btype, {})

            # Extrai texto de tipos comuns
            rich_texts = block_data.get("rich_text", [])
            for rt in rich_texts:
                text = rt.get("plain_text", "").strip()
                if text:
                    all_text.append(text)

            # Títulos
            if btype in ("heading_1", "heading_2", "heading_3"):
                for rt in block_data.get("rich_text", []):
                    t = rt.get("plain_text", "").strip()
                    if t:
                        all_text.append(f"\n## {t}\n")

            # Blocos filhos (recursivo 1 nível — suficiente para Notion IA)
            if block.get("has_children"):
                child_text = _get_page_text(block["id"])
                if child_text:
                    all_text.append(child_text)

        if not data.get("has_more"):
            break
        cursor = data.get("next_cursor")
        time.sleep(0.3)  # respeita rate limit do Notion

    return "\n".join(all_text)


def _extract_title(page: dict) -> str:
    """Extrai o título da página do Notion."""
    props = page.get("properties", {})
    for key in ("Nome da reunião", "Name", "Título", "Title", "nome", "título"):
        prop = props.get(key, {})
        title_list = prop.get("title", [])
        if title_list:
            return title_list[0].get("plain_text", "Sem título")
    return "Sem título"


def _extract_date(page: dict) -> str:
    """Extrai a data de criação da página."""
    created = page.get("created_time", "")
    if created:
        return created[:10]  # YYYY-MM-DD
    return ""


def extract_all_meetings(limit: Optional[int] = None) -> list[dict]:
    """
    Extrai todas as reuniões da database do Notion.

    Retorna lista de dicts:
    {
        "id": str,           — ID da página no Notion
        "title": str,        — Título da reunião
        "date": str,         — Data (YYYY-MM-DD)
        "content": str,      — Texto completo (transcrição + notas + resumo)
        "url": str,          — Link direto para a página
    }
    """
    if not NOTION_API_KEY or not NOTION_DB_ID:
        raise ValueError(
            "NOTION_API_KEY e NOTION_MEETINGS_DB_ID precisam estar definidos "
            "nas variáveis de ambiente."
        )

    url = f"https://api.notion.com/v1/databases/{NOTION_DB_ID}/query"
    meetings: list[dict] = []
    cursor = None

    print(f"[extractor] Iniciando extração da database {NOTION_DB_ID}...")

    while True:
        body: dict = {"page_size": 100}
        if cursor:
            body["start_cursor"] = cursor

        resp = requests.post(url, headers=HEADERS, json=body, timeout=30)
        resp.raise_for_status()
        data = resp.json()

        pages = data.get("results", [])
        print(f"[extractor] Página de resultados: {len(pages)} reuniões...")

        for page in pages:
            page_id    = page["id"]
            title      = _extract_title(page)
            date       = _extract_date(page)
            notion_url = page.get("url", "")

            print(f"[extractor]   → Lendo: {title} ({date})")

            try:
                content = _get_page_text(page_id)
            except Exception as e:
                print(f"[extractor]   ⚠️  Erro ao ler {title}: {e}")
                content = ""

            if content.strip():
                meetings.append({
                    "id":      page_id,
                    "title":   title,
                    "date":    date,
                    "content": content,
                    "url":     notion_url,
                })

            if limit and len(meetings) >= limit:
                print(f"[extractor] Limite de {limit} atingido.")
                return meetings

            time.sleep(0.2)

        if not data.get("has_more"):
            break
        cursor = data.get("next_cursor")

    print(f"[extractor] Total extraído: {len(meetings)} reuniões.")
    return meetings


if __name__ == "__main__":
    # Teste rápido: extrai só as 3 primeiras
    meetings = extract_all_meetings(limit=3)
    for m in meetings:
        print(f"\n{'='*60}")
        print(f"Título: {m['title']}")
        print(f"Data:   {m['date']}")
        print(f"Chars:  {len(m['content'])}")
        print(f"Prévia: {m['content'][:300]}...")

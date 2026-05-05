import json, time, requests, os

processados = set()
with open("ai_assistant/casos_estruturados.jsonl") as f:
    for line in f:
        line = line.strip()
        if line:
            processados.add(json.loads(line).get("notion_id", ""))

print(f"Ja processados: {len(processados)}")

notion_token = os.environ.get("NOTION_TOKEN") or os.environ.get("NOTION_API_KEY")
notion_db_id = os.environ.get("NOTION_MEETINGS_DB_ID")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
headers = {"Authorization": f"Bearer {notion_token}", "Notion-Version": "2022-06-28", "Content-Type": "application/json"}

todas_paginas = []
cursor = None
while True:
    body = {"page_size": 100}
    if cursor:
        body["start_cursor"] = cursor
    resp = requests.post(f"https://api.notion.com/v1/databases/{notion_db_id}/query", headers=headers, json=body, timeout=30)
    data = resp.json()
    todas_paginas.extend(data.get("results", []))
    if not data.get("has_more"):
        break
    cursor = data.get("next_cursor")

faltando = [p for p in todas_paginas if p["id"] not in processados]
print(f"Faltando: {len(faltando)}")

from ai_assistant.extractor import _get_page_text, _extract_title, _extract_date
from ai_assistant.structurer import STRUCTURE_PROMPT

def structure_safe(meeting, case_number):
    content = meeting.get("content", "")[:8000]
    if len(content) < 100:
        return None
    try:
        resp = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": ANTHROPIC_API_KEY, "anthropic-version": "2023-06-01", "content-type": "application/json"},
            json={"model": "claude-haiku-4-5-20251001", "max_tokens": 2000, "messages": [{"role": "user", "content": STRUCTURE_PROMPT + content}]},
            timeout=30,
        )
        raw = resp.json()["content"][0]["text"].strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        raw = raw.strip()
        try:
            structured = json.loads(raw)
        except json.JSONDecodeError:
            return None
        structured["caso_id"]   = f"caso_{case_number:04d}"
        structured["notion_id"] = meeting.get("id", "")
        structured["titulo"]    = meeting.get("title", "")
        structured["data"]      = meeting.get("date", "")
        return structured
    except Exception as e:
        print(f"  Erro: {e}")
        return None

with open("ai_assistant/casos_estruturados.jsonl", "a") as f:
    for i, page in enumerate(faltando, 1):
        titulo = _extract_title(page)
        data   = _extract_date(page)
        print(f"[{i}/{len(faltando)}] {titulo[:60]}")
        try:
            content = _get_page_text(page["id"])
        except Exception as e:
            print(f"  Erro leitura: {e}")
            continue
        if not content or not content.strip():
            continue
        meeting = {"id": page["id"], "title": titulo, "date": data, "content": content, "url": page.get("url","")}
        caso = structure_safe(meeting, len(processados) + i)
        if caso:
            f.write(json.dumps(caso, ensure_ascii=False) + "\n")
            f.flush()
            print(f"  OK: {caso.get('problema_principal','')[:60]}")
        time.sleep(1.5)

print("Concluido!")

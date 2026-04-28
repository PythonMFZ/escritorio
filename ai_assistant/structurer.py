"""
structurer.py — Etapa 2
Usa a API do Claude para transformar cada reunião bruta
em um "caso clínico" estruturado, pronto para busca vetorial.
"""

import os
import json
import time
import requests
from typing import Optional

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

STRUCTURE_PROMPT = """Você é um analista financeiro sênior da Maffezzolli Capital.
Analise a transcrição/notas desta reunião de consultoria e extraia as informações
no formato JSON abaixo. Seja preciso e conciso.

Se alguma informação não estiver disponível, use null.

Retorne SOMENTE o JSON, sem texto adicional, sem markdown, sem explicações.

{
  "segmento": "pme|middle|construtora|indefinido",
  "setor": "string — setor da empresa (ex: construção civil, varejo, serviços)",
  "problema_principal": "string — a dor/problema central da reunião (1-2 frases)",
  "problemas_secundarios": ["lista", "de", "problemas", "mencionados"],
  "dados_financeiros": {
    "faturamento_mensal_estimado": "string ou null (ex: R$ 200k/mês)",
    "nivel_endividamento": "baixo|medio|alto|critico|indefinido",
    "situacao_caixa": "saudavel|apertado|critico|indefinido"
  },
  "solucao_recomendada": "string — o que foi recomendado (2-4 frases)",
  "produtos_sugeridos": ["lista de produtos Maffezzolli mencionados"],
  "resultado": "string — o que aconteceu depois, se mencionado (ou null)",
  "aprendizado": "string — insight principal que pode ajudar casos futuros (1-2 frases)",
  "tags": ["lista", "de", "palavras-chave", "para", "busca"],
  "resumo_para_busca": "string — resumo de 3-5 linhas que captura a essência do caso para busca semântica"
}

TRANSCRIÇÃO/NOTAS DA REUNIÃO:
"""


def structure_meeting(meeting: dict, case_number: int) -> Optional[dict]:
    """
    Recebe um dict de reunião bruta e retorna o caso estruturado.
    Retorna None se não conseguir estruturar.
    """
    if not ANTHROPIC_API_KEY:
        raise ValueError("ANTHROPIC_API_KEY não definida.")

    content = meeting.get("content", "")
    if len(content) < 100:
        print(f"[structurer]   ⚠️  Conteúdo muito curto, pulando.")
        return None

    # Trunca para não estourar o contexto (Claude suporta 200k tokens,
    # mas para economizar usamos no máx 8000 chars por reunião)
    content_truncated = content[:8000]

    prompt = STRUCTURE_PROMPT + content_truncated

    try:
        resp = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": "claude-haiku-4-5-20251001",  # rápido e barato para estruturação
                "max_tokens": 1000,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        raw_text = data["content"][0]["text"].strip()

        # Remove markdown se vier com ```json
        if raw_text.startswith("```"):
            raw_text = raw_text.split("```")[1]
            if raw_text.startswith("json"):
                raw_text = raw_text[4:]
        raw_text = raw_text.strip()

        structured = json.loads(raw_text)

        # Adiciona metadados da reunião original
        structured["caso_id"]    = f"caso_{case_number:04d}"
        structured["notion_id"]  = meeting.get("id", "")
        structured["notion_url"] = meeting.get("url", "")
        structured["titulo"]     = meeting.get("title", "")
        structured["data"]       = meeting.get("date", "")
        structured["content_original_chars"] = len(content)

        return structured

    except json.JSONDecodeError as e:
        print(f"[structurer]   ⚠️  JSON inválido: {e}")
        print(f"[structurer]   Raw: {raw_text[:200]}")
        return None
    except Exception as e:
        print(f"[structurer]   ⚠️  Erro na API: {e}")
        return None


def structure_all_meetings(
    meetings: list[dict],
    save_path: str = "ai_assistant/casos_estruturados.jsonl",
) -> list[dict]:
    """
    Estrutura todas as reuniões e salva em arquivo JSONL
    (uma linha por caso, fácil de inspecionar e reprocessar).
    """
    import os
    os.makedirs(os.path.dirname(save_path), exist_ok=True)

    casos: list[dict] = []
    erros = 0

    print(f"[structurer] Estruturando {len(meetings)} reuniões...")

    with open(save_path, "w", encoding="utf-8") as f:
        for i, meeting in enumerate(meetings, 1):
            print(f"[structurer] [{i}/{len(meetings)}] {meeting.get('title', '?')[:60]}")

            caso = structure_meeting(meeting, i)

            if caso and isinstance(caso, dict):
                casos.append(caso)
                f.write(json.dumps(caso, ensure_ascii=False) + "\n")
                f.flush()
                prob = caso.get('problema_principal') or ''
                print(f"[structurer]   ✅ {prob[:80]}")
            else:
                print(f"[structurer]   ❌ Não estruturado")

            # Rate limit: Claude Haiku suporta ~50 req/min
            time.sleep(1.5)

    print(f"\n[structurer] Concluído: {len(casos)} casos / {erros} erros")
    print(f"[structurer] Salvo em: {save_path}")
    return casos


def load_structured_cases(
    path: str = "ai_assistant/casos_estruturados.jsonl",
) -> list[dict]:
    """Carrega casos já estruturados do arquivo JSONL."""
    casos = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    casos.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return casos


if __name__ == "__main__":
    # Teste: estrutura 1 caso fake para ver o output
    fake_meeting = {
        "id": "test-123",
        "title": "Reunião Teste - Empresa ABC",
        "date": "2024-01-15",
        "url": "https://notion.so/test",
        "content": """
        Reunião com empresa de construção civil, faturamento ~R$ 5M/mês.
        Principal problema: caixa muito apertado, obra parada por falta de recurso.
        Dívida bancária alta, cerca de R$ 3M em financiamentos.
        
        Recomendação: estruturar FIDC para antecipar recebíveis das unidades vendidas.
        Também sugerimos renegociar dívida bancária de CP para LP.
        
        Resultado: cliente aprovou a proposta, iniciamos estruturação do FIDC.
        """,
    }

    caso = structure_meeting(fake_meeting, 1)
    if caso:
        print(json.dumps(caso, indent=2, ensure_ascii=False))
    else:
        print("Erro ao estruturar")

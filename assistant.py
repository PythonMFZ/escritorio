"""
assistant.py — Etapa 4
O "Pergunte ao Rafael" — recebe pergunta + dados do cliente,
busca casos similares e gera recomendação personalizada.
"""

import os
import json
import requests
from typing import Optional

from ai_assistant.vector_store import search_similar_cases

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

SYSTEM_PROMPT = """Você é o Assistente Maffezzolli — a inteligência financeira do app, \
criada a partir do conhecimento e experiência do Rafael Maffezzolli, consultor \
financeiro especializado em PMEs, Middle Market e Construtoras brasileiras.

Seu papel é analisar a situação financeira do cliente e dar uma recomendação \
executiva, direta e acionável — exatamente como o Rafael faria numa reunião presencial.

DIRETRIZES:
1. Seja direto e executivo. Sem rodeios, sem jargão desnecessário.
2. Use os dados reais do cliente (fornecidos abaixo) para personalizar a resposta.
3. Baseie-se nos casos similares encontrados na base de conhecimento do Rafael.
4. Sempre termine com 1-2 ações concretas que o cliente pode tomar AGORA.
5. Se o problema for complexo demais, diga claramente: "Este caso precisa de \
uma reunião com o Rafael" e explique por quê.
6. Não invente dados. Se não souber, diga.
7. Cite os casos de referência pelo número (ex: "Baseado no Caso #0042...").

FORMATO DA RESPOSTA:
- Diagnóstico (2-3 linhas do que está acontecendo)
- Recomendação principal (o que fazer)
- Próximos passos (ações concretas, numeradas)
- Casos de referência (se houver)
"""


def _format_client_context(client_data: dict) -> str:
    """Formata os dados do cliente para injeção no prompt."""
    lines = ["=== DADOS DO CLIENTE ==="]

    name = client_data.get("name") or client_data.get("nome", "")
    if name:
        lines.append(f"Empresa: {name}")

    seg = client_data.get("segment") or client_data.get("segmento", "")
    if seg:
        lines.append(f"Segmento: {seg.upper()}")

    rev = client_data.get("revenue_monthly_brl", 0) or 0
    if rev:
        lines.append(f"Faturamento mensal: R$ {rev:,.0f}")

    cash = client_data.get("cash_balance_brl", 0) or 0
    lines.append(f"Caixa disponível: R$ {cash:,.0f}")

    debt = client_data.get("debt_total_brl", 0) or 0
    if debt:
        lines.append(f"Dívida total: R$ {debt:,.0f}")
        if rev > 0:
            ratio = debt / rev
            lines.append(f"Dívida/Faturamento: {ratio:.1f}x")

    s_total = client_data.get("score_total", 0) or 0
    s_fin   = client_data.get("score_financial", 0) or 0
    s_proc  = client_data.get("score_process", 0) or 0
    if s_total:
        lines.append(f"Score Geral: {s_total:.0f}/100")
        lines.append(f"Score Financeiro: {s_fin:.0f}/100")
        lines.append(f"Score de Processos: {s_proc:.0f}/100")

    # Classificação G4
    if s_total >= 65:
        lines.append("Status: SAUDÁVEL")
    elif s_total >= 50:
        lines.append("Status: ATENÇÃO")
    else:
        lines.append("Status: EM RISCO")

    # Dados do balanço se disponíveis
    for field, label in [
        ("receivables_brl", "Recebíveis"),
        ("inventory_brl", "Estoque"),
        ("immobilized_brl", "Imobilizado"),
        ("payables_360_brl", "Contas a pagar (CP)"),
        ("short_term_debt_brl", "Dívida CP"),
        ("long_term_debt_brl", "Dívida LP"),
        ("collateral_brl", "Garantias disponíveis"),
        ("delinquency_brl", "Inadimplência"),
    ]:
        val = client_data.get(field, 0) or 0
        if val > 0:
            lines.append(f"{label}: R$ {val:,.0f}")

    # DRE se disponível
    for field, label in [
        ("cmv", "CMV mensal"),
        ("payroll", "Folha mensal"),
        ("opex", "Despesas fixas"),
        ("mb", "Margem bruta"),
        ("mb_pct", "Margem bruta %"),
        ("ebitda", "Resultado operacional"),
    ]:
        val = client_data.get(field, 0) or 0
        if val:
            if "pct" in field:
                lines.append(f"{label}: {val:.1f}%")
            else:
                lines.append(f"{label}: R$ {val:,.0f}")

    return "\n".join(lines)


def _format_similar_cases(cases: list[dict]) -> str:
    """Formata os casos similares para o prompt."""
    if not cases:
        return "Nenhum caso similar encontrado na base de conhecimento."

    lines = ["\n=== CASOS SIMILARES DA BASE DE CONHECIMENTO DO RAFAEL ==="]

    for c in cases:
        sim_pct = int(c.get("similarity", 0) * 100)
        lines.append(f"\n{c['caso_id'].upper()} ({sim_pct}% similar) — {c['titulo'][:60]}")
        if c.get("segmento"):
            lines.append(f"  Segmento: {c['segmento']}")
        if c.get("problema"):
            lines.append(f"  Problema: {c['problema'][:200]}")
        if c.get("solucao"):
            lines.append(f"  Solução aplicada: {c['solucao'][:200]}")
        if c.get("resultado"):
            lines.append(f"  Resultado: {c['resultado'][:150]}")
        if c.get("aprendizado"):
            lines.append(f"  Aprendizado: {c['aprendizado'][:150]}")

    return "\n".join(lines)


def ask(
    question: str,
    client_data: dict,
    n_similar_cases: int = 4,
    conversation_history: Optional[list] = None,
) -> dict:
    """
    Processa uma pergunta do usuário e retorna a resposta do assistente.

    Args:
        question: pergunta do usuário
        client_data: dados financeiros do cliente (do ClientSnapshot/BusinessProfile)
        n_similar_cases: quantos casos similares buscar
        conversation_history: histórico de mensagens anteriores (para multi-turn)

    Returns:
        {
            "response": str,           — resposta do assistente
            "cases_used": list,        — casos de referência usados
            "confidence": float,       — similaridade média dos casos (0-1)
            "error": bool,
            "error_message": str,
        }
    """
    if not ANTHROPIC_API_KEY:
        return {
            "response": "Assistente não configurado. Contate o administrador.",
            "cases_used": [],
            "confidence": 0.0,
            "error": True,
            "error_message": "ANTHROPIC_API_KEY não definida",
        }

    # 1. Determina segmento para filtrar busca
    segmento = client_data.get("segment") or client_data.get("segmento")
    if segmento:
        segmento = segmento.lower()
        if segmento not in ("pme", "middle", "construtora"):
            segmento = None

    # 2. Busca casos similares
    similar_cases = search_similar_cases(
        query=question,
        n_results=n_similar_cases,
        segmento=segmento,
    )

    # Confiança média
    confidence = 0.0
    if similar_cases:
        confidence = sum(c.get("similarity", 0) for c in similar_cases) / len(similar_cases)

    # 3. Monta o prompt
    client_context = _format_client_context(client_data)
    cases_context  = _format_similar_cases(similar_cases)

    user_message = f"""{client_context}

{cases_context}

=== PERGUNTA DO CLIENTE ===
{question}

Por favor, forneça uma recomendação executiva baseada nos dados acima."""

    # 4. Monta histórico de mensagens
    messages = []
    if conversation_history:
        messages.extend(conversation_history)
    messages.append({"role": "user", "content": user_message})

    # 5. Chama a API do Claude
    try:
        resp = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": "claude-sonnet-4-6",  # Sonnet para respostas de qualidade
                "max_tokens": 1500,
                "system": SYSTEM_PROMPT,
                "messages": messages,
            },
            timeout=45,
        )
        resp.raise_for_status()
        data = resp.json()
        response_text = data["content"][0]["text"]

        return {
            "response":   response_text,
            "cases_used": [
                {
                    "id":         c["caso_id"],
                    "titulo":     c["titulo"],
                    "similarity": c["similarity"],
                    "url":        c.get("notion_url", ""),
                }
                for c in similar_cases
            ],
            "confidence":    round(confidence, 3),
            "error":         False,
            "error_message": "",
        }

    except Exception as e:
        return {
            "response":      "Desculpe, ocorreu um erro ao processar sua pergunta. Tente novamente.",
            "cases_used":    [],
            "confidence":    0.0,
            "error":         True,
            "error_message": str(e),
        }


if __name__ == "__main__":
    # Teste com cliente fake
    fake_client = {
        "name":                "Empresa Teste Ltda",
        "segment":             "pme",
        "revenue_monthly_brl": 80000,
        "cash_balance_brl":    3000,
        "debt_total_brl":      250000,
        "score_total":         38,
        "score_financial":     32,
        "score_process":       45,
    }

    result = ask(
        question="Meu caixa está muito apertado e não consigo pagar os fornecedores. O que fazer?",
        client_data=fake_client,
    )

    print(f"\nResposta:\n{result['response']}")
    print(f"\nConfiança: {result['confidence']:.0%}")
    print(f"Casos usados: {len(result['cases_used'])}")
    for c in result["cases_used"]:
        print(f"  - {c['id']}: {c['titulo'][:50]} ({c['similarity']:.0%})")

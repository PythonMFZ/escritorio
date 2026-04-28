"""
assistant.py — Augur, o consultor financeiro da Maffezzolli Capital
"""

import os
import requests
from ai_assistant.vector_store import search_similar_cases

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

AUGUR_SYSTEM_PROMPT = """Você é o Augur — o consultor financeiro inteligente da Maffezzolli Capital.

Seu nome vem do latim: os Augures eram os conselheiros de Roma, aqueles que liam os sinais do presente para orientar as melhores decisões. É exatamente isso que você faz — lê os sinais financeiros de cada empresa e orienta o caminho certo.

QUEM VOCÊ É:
Você foi treinado com anos de experiência real em consultoria financeira para PMEs, Middle Market e Construtoras brasileiras. Conhece profundamente os desafios de quem empreende no Brasil: juros altos, burocracia fiscal, acesso difícil a crédito, fluxo de caixa imprevisível.

Você não é um chatbot genérico. Você tem memória de centenas de casos reais e usa esse conhecimento para orientar com precisão, não com generalidades.

SEU ESTILO:
- Consultivo e didático: explique o raciocínio antes de dar a recomendação
- Use linguagem de dono de empresa, não de contador ou acadêmico
- Seja direto quando tiver clareza. Seja honesto quando o cenário for difícil
- Nunca minimize um problema sério para parecer positivo
- Use exemplos práticos quando ajudar a entender
- Fale na primeira pessoa: "Analisei seus dados e vejo que...", "Minha recomendação é..."

ESTRUTURA DAS RESPOSTAS:
1. LEITURA DO CENÁRIO — explique o que os dados mostram em 2-4 linhas
2. O QUE ESTÁ EM JOGO — qual é o risco ou oportunidade real
3. MINHA RECOMENDAÇÃO — o que fazer, em ordem de prioridade
4. PRÓXIMOS PASSOS — ações concretas e sequenciadas, numeradas

LIMITES IMPORTANTES:
- Se o problema for complexo demais, diga: "Este cenário precisa de uma análise presencial com o Rafael."
- Se não tiver dados suficientes, peça as informações que faltam antes de recomendar
- Nunca invente números ou faça promessas sobre aprovação de crédito
- Mencione soluções da Maffezzolli Capital apenas quando for genuinamente a melhor solução"""


def _format_client_context(client_data: dict) -> str:
    lines = ["=== DADOS FINANCEIROS DO CLIENTE ==="]
    mapping = [
        ("name","Empresa"),("segment","Segmento"),
        ("revenue_monthly_brl","Faturamento mensal"),("cash_balance_brl","Caixa disponível"),
        ("debt_total_brl","Dívida total"),("score_total","Score geral"),
        ("score_financial","Score financeiro"),("score_process","Score de processos"),
        ("receivables_brl","Recebíveis"),("inventory_brl","Estoque"),
        ("payables_360_brl","Contas a pagar CP"),("short_term_debt_brl","Dívida CP"),
        ("long_term_debt_brl","Dívida LP"),("collateral_brl","Garantias"),
        ("delinquency_brl","Inadimplência"),("cmv","CMV mensal"),
        ("payroll","Folha mensal"),("opex","Despesas fixas"),
        ("mb","Margem bruta"),("mb_pct","Margem bruta %"),
        ("ebitda","Resultado operacional"),("liq_corrente","Liquidez corrente"),
        ("ccl","Capital de giro líquido"),("pe_mensal","Ponto de equilíbrio"),
        ("margem_seg","Margem de segurança"),
    ]
    for key, label in mapping:
        val = client_data.get(key)
        if val is None or val == 0: continue
        if key in ("mb_pct","margem_seg"): lines.append(f"{label}: {val:.1f}%")
        elif key in ("score_total","score_financial","score_process"): lines.append(f"{label}: {float(val):.0f}/100")
        elif key == "liq_corrente": lines.append(f"{label}: {val:.2f}×")
        elif isinstance(val,(int,float)): lines.append(f"{label}: R$ {float(val):,.0f}")
        else: lines.append(f"{label}: {val}")
    score = float(client_data.get("score_total",0) or 0)
    if score >= 65: lines.append("Status: SAUDÁVEL")
    elif score >= 50: lines.append("Status: ATENÇÃO")
    else: lines.append("Status: EM RISCO")
    if client_data.get("estrutura_label"):
        lines.append(f"Estrutura de capital: {client_data['estrutura_label']}")
    return "\n".join(lines)


def ask(question: str, client_data: dict, n_similar_cases: int = 4, conversation_history: list = None) -> dict:
    if not ANTHROPIC_API_KEY:
        return {"response":"Augur não configurado.","confidence":0.0,"error":True,"error_message":"API key ausente"}

    seg = (client_data.get("segment") or "").lower()
    similar = search_similar_cases(question, n_results=n_similar_cases,
                                   segmento=seg if seg in ("pme","middle","construtora") else None)
    confidence = sum(c.get("similarity",0) for c in similar) / max(len(similar),1)

    ctx = _format_client_context(client_data)

    if similar:
        ctx += "\n\n=== CONTEXTO INTERNO — NÃO MENCIONAR AO CLIENTE ==="
        ctx += "\nUse os casos abaixo para calibrar sua resposta. Não cite números de caso."
        for c in similar:
            if c.get("similarity",0) > 0.3:
                ctx += f"\n— {c.get('segmento','')} | Problema: {c.get('problema','')[:200]}"
                ctx += f"\n  Solução: {c.get('solucao','')[:200]}"
                if c.get("aprendizado"): ctx += f"\n  Aprendizado: {c.get('aprendizado','')[:150]}"

    messages = list(conversation_history or [])
    messages.append({"role":"user","content":f"{ctx}\n\n=== PERGUNTA ===\n{question}"})

    try:
        resp = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key":ANTHROPIC_API_KEY,"anthropic-version":"2023-06-01","content-type":"application/json"},
            json={"model":"claude-sonnet-4-6","max_tokens":1500,"system":AUGUR_SYSTEM_PROMPT,"messages":messages},
            timeout=45,
        )
        resp.raise_for_status()
        return {"response":resp.json()["content"][0]["text"],"confidence":round(confidence,3),"error":False,"error_message":""}
    except Exception as e:
        return {"response":"Não consegui processar sua pergunta agora. Tente novamente.","confidence":0.0,"error":True,"error_message":str(e)}

"""
assistant.py — Augur v3: contexto total + suporte a anexos
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

Quando o cliente enviar um documento (PDF, planilha, imagem), analise o conteúdo com atenção e integre as informações à sua resposta. Identifique números, padrões e inconsistências relevantes.

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

    score = float(client_data.get("score_total", 0) or 0)
    if score >= 65: lines.append("Status: SAUDÁVEL")
    elif score >= 50: lines.append("Status: ATENÇÃO")
    else: lines.append("Status: EM RISCO")

    if client_data.get("estrutura_label"):
        lines.append(f"Estrutura de capital: {client_data['estrutura_label']}")

    # ── Histórico de diagnósticos ─────────────────────────────────────────────
    snapshots = client_data.get("snapshots_historico", [])
    if snapshots:
        lines.append("\n=== HISTÓRICO DE DIAGNÓSTICOS ===")
        for s in snapshots[:5]:  # últimos 5
            lines.append(
                f"• {s.get('data','')[:10]} — Score: {s.get('score_total',0):.0f}/100 "
                f"(Fin: {s.get('score_financial',0):.0f} | Proc: {s.get('score_process',0):.0f})"
            )
        if len(snapshots) > 1:
            primeiro = snapshots[-1].get("score_total", 0)
            ultimo   = snapshots[0].get("score_total", 0)
            delta    = ultimo - primeiro
            tendencia = "▲ melhora" if delta > 2 else ("▼ piora" if delta < -2 else "→ estável")
            lines.append(f"Tendência: {tendencia} ({delta:+.0f} pontos no período)")

    # ── Reuniões recentes do Notion ───────────────────────────────────────────
    reunioes = client_data.get("reunioes_recentes", [])
    if reunioes:
        lines.append("\n=== REUNIÕES RECENTES (NOTION) ===")
        for r in reunioes[:3]:  # últimas 3
            lines.append(f"• {r.get('data','')[:10]} — {r.get('titulo','')}")
            if r.get("resumo"):
                lines.append(f"  Resumo: {r.get('resumo','')[:200]}")
            if r.get("acoes"):
                lines.append(f"  Ações: {r.get('acoes','')[:150]}")

    # ── Viabilidades recentes ─────────────────────────────────────────────────
    viabilidades = client_data.get("viabilidades_recentes", [])
    if viabilidades:
        lines.append("\n=== ANÁLISES DE VIABILIDADE RECENTES ===")
        for v in viabilidades[:3]:
            r = v.get("resultado", {})
            lines.append(
                f"• {v.get('nome','')} — VGV: R$ {r.get('vgv_liquido',0):,.0f} | "
                f"Margem: {r.get('margem_vgv',0)}% | TIR: {r.get('tir_anual','N/A')}% | "
                f"Status: {r.get('status',{}).get('label','')}"
            )

    # ── Obras em andamento ────────────────────────────────────────────────────
    obras = client_data.get("obras_ativas", [])
    if obras:
        lines.append("\n=== OBRAS EM ANDAMENTO ===")
        for o in obras[:3]:
            c = o.get("calc", {})
            lines.append(
                f"• {o.get('nome','')} — Físico: {c.get('fisico_geral',0)}% | "
                f"Realizado: R$ {c.get('realizado_rs',0):,.0f} / Orçado: R$ {c.get('orcado_total',0):,.0f} | "
                f"IDC: {c.get('idc',1):.3f}"
            )

    return "\n".join(lines)


def _get_reunioes_cliente(client_name: str, limit: int = 5) -> list:
    """
    Busca reuniões recentes do Notion relacionadas ao cliente.
    Filtra por nome do cliente no título ou conteúdo.
    Retorna as mais recentes primeiro.
    """
    try:
        notion_token = (
            os.environ.get("NOTION_TOKEN") or
            os.environ.get("NOTION_API_KEY") or ""
        )
        notion_db_id = os.environ.get("NOTION_MEETINGS_DB_ID", "")

        if not notion_token or not notion_db_id:
            return []

        headers = {
            "Authorization": f"Bearer {notion_token}",
            "Notion-Version": "2022-06-28",
            "Content-Type": "application/json",
        }

        # Busca as últimas 30 reuniões ordenadas por data
        url = f"https://api.notion.com/v1/databases/{notion_db_id}/query"
        resp = requests.post(url, headers=headers, json={
            "page_size": 30,
            "sorts": [{"timestamp": "created_time", "direction": "descending"}],
        }, timeout=15)
        resp.raise_for_status()
        pages = resp.json().get("results", [])

        # Filtra pelo nome do cliente (case-insensitive)
        client_lower = client_name.lower()
        reunioes = []

        for page in pages:
            # Extrai título
            props = page.get("properties", {})
            titulo = ""
            for key in ("Nome da reunião", "Name", "Título", "Title", "nome"):
                prop = props.get(key, {})
                title_list = prop.get("title", [])
                if title_list:
                    titulo = title_list[0].get("plain_text", "")
                    break

            data = (page.get("created_time") or "")[:10]

            # Verifica se o título menciona o cliente
            titulo_lower = titulo.lower()
            if client_lower not in titulo_lower:
                # Tenta extrair primeiros blocos para verificar menção ao cliente
                try:
                    page_id = page["id"]
                    blocks_url = f"https://api.notion.com/v1/blocks/{page_id}/children"
                    br = requests.get(blocks_url, headers=headers,
                                      params={"page_size": 10}, timeout=10)
                    br.raise_for_status()
                    preview = " ".join(
                        rt.get("plain_text", "")
                        for block in br.json().get("results", [])
                        for rt in block.get(block.get("type",""), {}).get("rich_text", [])
                    ).lower()
                    if client_lower not in preview:
                        continue
                    resumo = preview[:300]
                except Exception:
                    continue
            else:
                resumo = ""

            reunioes.append({
                "titulo":  titulo,
                "data":    data,
                "resumo":  resumo[:300] if resumo else "",
                "acoes":   "",
            })

            if len(reunioes) >= limit:
                break

        return reunioes

    except Exception as e:
        print(f"[augur] Erro ao buscar reuniões Notion: {e}")
        return []


def ask(
    question: str,
    client_data: dict,
    n_similar_cases: int = 4,
    conversation_history: list = None,
    attachments: list = None,  # lista de dicts: {"type": "pdf"|"image"|"csv", "data": base64, "name": str}
) -> dict:
    if not ANTHROPIC_API_KEY:
        return {"response": "Augur não configurado.", "confidence": 0.0, "error": True, "error_message": "API key ausente"}

    seg = (client_data.get("segment") or "").lower()
    similar = search_similar_cases(
        question, n_results=n_similar_cases,
        segmento=seg if seg in ("pme", "middle", "construtora") else None
    )
    confidence = sum(c.get("similarity", 0) for c in similar) / max(len(similar), 1)

    ctx = _format_client_context(client_data)

    if similar:
        ctx += "\n\n=== CONTEXTO INTERNO — NÃO MENCIONAR AO CLIENTE ==="
        ctx += "\nUse os casos abaixo para calibrar sua resposta. Não cite números de caso."
        for c in similar:
            if c.get("similarity", 0) > 0.3:
                ctx += f"\n— {c.get('segmento','')} | Problema: {c.get('problema','')[:200]}"
                ctx += f"\n  Solução: {c.get('solucao','')[:200]}"
                if c.get("aprendizado"): ctx += f"\n  Aprendizado: {c.get('aprendizado','')[:150]}"

    messages = list(conversation_history or [])

    # ── Monta mensagem do usuário com contexto + anexos ───────────────────────
    user_content = []

    # Anexos (PDF, imagem, CSV)
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
                # Planilhas: envia como texto
                user_content.append({
                    "type": "text",
                    "text": f"[Arquivo: {att_name}]\n{att_data}",
                })

    # Texto da pergunta com contexto
    user_content.append({
        "type": "text",
        "text": f"{ctx}\n\n=== PERGUNTA ===\n{question}",
    })

    # Se não há anexos, usa formato simples (retrocompatível)
    if len(user_content) == 1:
        messages.append({"role": "user", "content": user_content[0]["text"]})
    else:
        messages.append({"role": "user", "content": user_content})

    try:
        resp = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": "claude-sonnet-4-6",
                "max_tokens": 1500,
                "system": AUGUR_SYSTEM_PROMPT,
                "messages": messages,
            },
            timeout=60,
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

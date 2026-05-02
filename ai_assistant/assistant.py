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
        lines.append("Abaixo estão as reuniões mais recentes. Analise quais são relevantes para a pergunta do cliente.")
        for r in reunioes[:5]:
            lines.append(f"\n--- Reunião: {r.get('titulo','')} ({r.get('data','')[:10]}) ---")
            if r.get("resumo"):
                lines.append(r.get("resumo","")[:500])

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


def _extrair_texto_bloco(block_id: str, headers: dict, profundidade: int = 0, max_prof: int = 4) -> str:
    """Extrai texto recursivamente de blocos do Notion até max_prof níveis."""
    if profundidade > max_prof:
        return ""
    try:
        import requests as _req
        resp = _req.get(
            f"https://api.notion.com/v1/blocks/{block_id}/children",
            headers=headers, params={"page_size": 50}, timeout=10
        )
        resp.raise_for_status()
        textos = []
        for block in resp.json().get("results", []):
            btype = block.get("type", "")
            block_data = block.get(btype, {})
            rts = block_data.get("rich_text", [])
            texto = " ".join(rt.get("plain_text","") for rt in rts).strip()

            # Prefixo por tipo
            if btype in ("heading_1", "heading_2", "heading_3") and texto:
                textos.append(f"\n## {texto}")
            elif btype == "to_do" and texto:
                checked = block_data.get("checked", False)
                textos.append(f"  {'[x]' if checked else '[ ]'} {texto}")
            elif btype == "bulleted_list_item" and texto:
                textos.append(f"  • {texto}")
            elif btype == "numbered_list_item" and texto:
                textos.append(f"  {texto}")
            elif texto:
                textos.append(texto)

            # Recursão nos filhos
            if block.get("has_children"):
                filho_texto = _extrair_texto_bloco(
                    block["id"], headers, profundidade + 1, max_prof
                )
                if filho_texto:
                    textos.append(filho_texto)

        return "\n".join(t for t in textos if t)
    except Exception:
        return ""


def _get_reunioes_cliente(client_name: str, limit: int = 5) -> list:
    """
    Busca reuniões recentes do Notion com extração profunda de conteúdo.
    Prioriza reuniões que mencionam o cliente; inclui recentes dos últimos 7 dias.
    """
    try:
        import requests as _req
        from datetime import datetime as _dt2, timedelta as _td2

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

        url = f"https://api.notion.com/v1/databases/{notion_db_id}/query"
        resp = _req.post(url, headers=headers, json={
            "page_size": 30,
            "sorts": [{"timestamp": "created_time", "direction": "descending"}],
        }, timeout=15)
        resp.raise_for_status()
        pages = resp.json().get("results", [])

        # Palavras-chave do cliente
        palavras = [p.strip().lower() for p in client_name.replace("-","").split() if len(p) > 2]
        hoje = _dt2.utcnow().date()
        ultima_semana = (hoje - _td2(days=7)).isoformat()

        prioritarias = []
        recentes     = []

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
            menciona = any(p in titulo_lower for p in palavras)

            # Extrai conteúdo completo (recursivo)
            conteudo = _extrair_texto_bloco(page["id"], headers, profundidade=0, max_prof=5)

            if not menciona:
                conteudo_lower = conteudo.lower()
                menciona = any(p in conteudo_lower for p in palavras)

            item = {
                "titulo":  titulo,
                "data":    data,
                "resumo":  conteudo[:1500],  # até 1500 chars de conteúdo real
                "acoes":   "",
            }

            if menciona:
                prioritarias.append(item)
            elif data >= ultima_semana:
                recentes.append(item)

        resultado = prioritarias[:limit] + recentes[:max(0, limit - len(prioritarias))]
        return resultado[:limit]

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

# ============================================================================
# ui_predio_juridico.py — 7º andar do prédio: Jurídico e Compliance
# ============================================================================
# Exec'd no namespace do app.py, DEPOIS de ui_predio.py e dos demais módulos do
# prédio (usa _pr_*, _mk_salvar_gerado, _mk_slug, _cm_brl, _cm_digitos).
#
# AGENTES
#   contratos   (admin) — carteira de contratos e vencimentos, minuta em Word com
#                         cláusulas numeradas e cadastro do contrato no financeiro
#                         (o Faturamento passa a cobrar) com aprovação
#   compliance          — KYC do cliente novo (dossiês, SCR, web), checagem de
#                         conflito de interesse na base e parecer registrado
#   lgpd        (admin) — onde estão os dados de uma pessoa, resposta ao titular,
#                         retenção e anonimização de leads/contatos com aprovação
#
# Nada aqui substitui revisão jurídica: minutas e pareceres saem como rascunho.
# ============================================================================

import io as _io_jr
import re as _re_jr


# ── Contratos ─────────────────────────────────────────────────────────────────

def _jr_t_contratos(s, cid, situacao):
    CC = globals().get("ContratoCliente")
    if CC is None:
        return {"erro": "Contratos indisponíveis."}
    hoje = _pr_hoje()
    nomes = _pr_clientes(s, cid)
    out = []
    for k in s.exec(_sel_pr(CC).where(CC.company_id == cid).order_by(CC.data_fim)).all():
        fim = _pr_data(k.data_fim)
        dias = (fim - hoje).days if fim else None
        item = {"contrato_id": k.id, "cliente": nomes.get(k.client_id, k.nome_cliente), "contrato": k.nome_contrato,
                "servicos": k.servicos, "valor_mensal": round(k.valor_cents / 100, 2), "dia_vencimento": k.dia_vencimento,
                "inicio": _pr_fmt_data(_pr_data(k.data_inicio)) if _pr_data(k.data_inicio) else "",
                "fim": _pr_fmt_data(fim) if fim else "", "dias_para_terminar": dias, "status": k.status,
                "sem_email_cobranca": not (k.email_cliente or "").strip(), "observacao": (k.observacao or "")[:200]}
        if situacao == "vencendo" and not (k.status == "ativo" and dias is not None and 0 <= dias <= 90):
            continue
        if situacao == "sem_fim" and not (k.status == "ativo" and fim is None):
            continue
        if situacao == "ativos" and k.status != "ativo":
            continue
        out.append(item)
    return {"contratos": out[:80], "total": len(out),
            "observacao": "Contratos cadastrados no financeiro (são eles que geram as cobranças mensais)."}


_JR_ORDINAIS = ["PRIMEIRA", "SEGUNDA", "TERCEIRA", "QUARTA", "QUINTA", "SEXTA", "SÉTIMA", "OITAVA", "NONA", "DÉCIMA",
                "DÉCIMA PRIMEIRA", "DÉCIMA SEGUNDA", "DÉCIMA TERCEIRA", "DÉCIMA QUARTA", "DÉCIMA QUINTA", "DÉCIMA SEXTA",
                "DÉCIMA SÉTIMA", "DÉCIMA OITAVA", "DÉCIMA NONA", "VIGÉSIMA"]


def _jr_docx_minuta(m: dict) -> bytes:
    from docx import Document
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.shared import Cm, Pt, RGBColor

    doc = Document()
    for sec in doc.sections:
        sec.left_margin = sec.right_margin = Cm(2.5)
        rod = sec.footer.paragraphs[0]
        rod.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = rod.add_run("MINUTA — sujeita a revisão jurídica")
        run.font.size, run.font.color.rgb = Pt(8), RGBColor(0x9C, 0xA3, 0xAF)
    doc.styles["Normal"].font.name, doc.styles["Normal"].font.size = "Arial", Pt(10.5)

    def par(texto, negrito=False, centro=False, antes=0, depois=6):
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER if centro else WD_ALIGN_PARAGRAPH.JUSTIFY
        for parte in _re_jr.split(r"(\*\*.+?\*\*)", str(texto or "")):
            if parte.startswith("**") and parte.endswith("**"):
                r_ = p.add_run(parte[2:-2]); r_.bold = True
            elif parte:
                r_ = p.add_run(parte); r_.bold = negrito
        p.paragraph_format.space_before, p.paragraph_format.space_after = Pt(antes), Pt(depois)
        return p

    p = par(m["titulo"].upper(), negrito=True, centro=True, depois=14)
    p.runs[0].font.size = Pt(13)
    par("Pelo presente instrumento particular, as partes abaixo qualificadas:", depois=8)
    par(f"**CONTRATANTE:** {m['contratante']}")
    par(f"**CONTRATADA:** {m['contratada']}", depois=10)
    par("têm entre si justo e contratado o presente, que se regerá pelas cláusulas e condições seguintes:", depois=10)
    for i, cl in enumerate(m["clausulas"], 1):
        ordinal = _JR_ORDINAIS[i - 1] if i <= len(_JR_ORDINAIS) else f"{i}ª"
        par(f"CLÁUSULA {ordinal} — {str(cl.get('titulo', '')).upper()}", negrito=True, antes=8, depois=4)
        for j, item in enumerate(cl.get("itens") or [], 1):
            par(f"{i}.{j}. {item}")
    par(m.get("fecho") or "E, por estarem assim justas e contratadas, as partes assinam o presente instrumento em 2 (duas) vias "
        "de igual teor e forma, na presença das testemunhas abaixo.", antes=8)
    par(f"{m.get('local') or 'Brusque (SC)'}, {m.get('data') or '___ de __________ de ______'}.", centro=True, antes=10, depois=24)
    for rotulo in (f"CONTRATANTE — {m.get('assinatura_contratante') or ''}", f"CONTRATADA — {m.get('assinatura_contratada') or ''}"):
        par("_" * 45, centro=True, antes=18, depois=0)
        par(rotulo.strip(" —"), centro=True)
    par("TESTEMUNHAS:", negrito=True, antes=14)
    for n in (1, 2):
        par(f"{n}. _______________________________   Nome:                         CPF:", antes=10)
    buf = _io_jr.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def _jr_t_gerar_minuta(s, cid, titulo, contratante, contratada, clausulas, local, data, assinatura_contratante,
                       assinatura_contratada, fecho):
    clausulas = [c for c in (clausulas or []) if isinstance(c, dict) and (c.get("titulo") or "").strip() and c.get("itens")]
    if len(clausulas) < 4:
        return {"ok": False, "erro": "Uma minuta precisa de pelo menos 4 cláusulas com itens (objeto, prazo, preço, rescisão...)."}
    if len((contratante or "").strip()) < 20:
        return {"ok": False, "erro": "Qualifique o contratante (razão social, CNPJ, endereço, representante)."}
    m = {"titulo": titulo or "Contrato de Prestação de Serviços", "contratante": contratante,
         "contratada": contratada or "[QUALIFICAÇÃO DA M. CAPITAL: razão social, CNPJ, endereço e representante]",
         "clausulas": clausulas, "local": local, "data": data, "assinatura_contratante": assinatura_contratante,
         "assinatura_contratada": assinatura_contratada, "fecho": fecho}
    nome = f"Minuta_-_{_mk_slug(contratante.split(',')[0], 40).replace('-', '_')}.docx"
    a = _mk_salvar_gerado(s, cid, nome, "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                          _jr_docx_minuta(m))
    pend = sorted(set(_re_jr.findall(r"\[[^\]]{3,80}\]", " ".join([contratante, m["contratada"]] +
                                                                  [i for c in clausulas for i in c["itens"]]))))
    return {"ok": True, "anexo_id": a.id, "arquivo": a.nome, "clausulas": len(clausulas), "campos_a_preencher": pend[:20],
            "observacao": "Minuta em Word em 'Arquivos gerados'. Precisa de revisão jurídica antes de assinar."}


def _jr_t_propor_contrato(s, cid, cliente, nome_contrato, servicos, valor_mensal, dia_vencimento, data_inicio, data_fim,
                          email_cobranca, observacao):
    c, cands = _pr_resolver_cliente(s, cid, cliente)
    if not c:
        return _pr_nao_achei(cliente, cands)
    if float(valor_mensal or 0) <= 0 or not (nome_contrato or "").strip():
        return {"ok": False, "erro": "Informe o nome do contrato e o valor mensal."}
    ini, fim = _pr_data(data_inicio), _pr_data(data_fim) if (data_fim or "").strip() else None
    if not ini or ((data_fim or "").strip() and not fim) or (fim and fim <= ini):
        return {"ok": False, "erro": "Datas inválidas: use DD/MM/AAAA, com fim depois do início (ou fim vazio)."}
    dia = int(dia_vencimento or 10)
    if not 1 <= dia <= 28:
        return {"ok": False, "erro": "Dia de vencimento entre 1 e 28."}
    CC = globals().get("ContratoCliente")
    if CC is not None and s.exec(_sel_pr(CC).where(CC.company_id == cid, CC.client_id == c.id, CC.status == "ativo",
                                                   CC.nome_contrato == nome_contrato.strip())).first():
        return {"ok": False, "erro": f"{c.name} já tem um contrato ativo com esse nome."}
    email = (email_cobranca or "").strip() or c.finance_email or c.email or ""
    payload = {"nome_contrato": nome_contrato.strip()[:200], "servicos": (servicos or "").strip()[:500],
               "valor_cents": int(round(float(valor_mensal) * 100)), "dia_vencimento": dia, "data_inicio": ini.isoformat(),
               "data_fim": fim.isoformat() if fim else "", "email": email, "observacao": (observacao or "").strip()[:500]}
    acao = _pr_registrar_proposta(
        s, cid, tipo="registrar_contrato", client_id=c.id, titulo=f"Cadastrar contrato: {c.name} — {payload['nome_contrato']}",
        destinatario=f"Financeiro · contratos ativos (passa a gerar cobrança mensal) · {c.name}",
        assunto=payload["nome_contrato"],
        corpo=(f"{_cm_brl(valor_mensal)} por mês, vencimento dia {dia}, de {_pr_fmt_data(ini)}"
               f"{' a ' + _pr_fmt_data(fim) if fim else ' (sem data de término)'}.\nServiços: {payload['servicos'] or '—'}\n"
               f"E-mail de cobrança: {email or 'sem e-mail cadastrado'}"),
        payload_json=_json_pr.dumps(payload, ensure_ascii=False))
    return {"ok": True, "proposta_id": acao.id, "status": "aguardando aprovação de um admin",
            "observacao": "Aprove quando o contrato estiver assinado: a partir daí o Faturamento passa a gerar as cobranças."}


def _jr_exec_registrar_contrato(s, acao) -> str:
    CC = globals().get("ContratoCliente")
    if CC is None:
        raise _PrErro("Contratos indisponíveis.")
    p = _json_pr.loads(acao.payload_json or "{}")
    c = s.get(Client, acao.client_id)
    k = CC(company_id=acao.company_id, client_id=acao.client_id, nome_cliente=c.name if c else "",
           nome_contrato=p["nome_contrato"], servicos=p["servicos"], valor_cents=p["valor_cents"],
           dia_vencimento=p["dia_vencimento"], data_inicio=p["data_inicio"], data_fim=p["data_fim"], status="ativo",
           observacao=p["observacao"], email_cliente=p["email"])
    s.add(k)
    s.commit()
    s.refresh(k)
    return f"Contrato #{k.id} cadastrado e ativo: as cobranças passam a ser geradas pelo Faturamento."


# ── Compliance ────────────────────────────────────────────────────────────────

def _jr_t_conflitos(s, cid, nome, cnpj):
    termos = [t for t in _pr_norm(nome or "").split() if len(t) >= 4 and t not in
              ("ltda", "eireli", "industria", "comercio", "servicos", "grupo", "empresa", "brasil")][:4]
    doc = _cm_digitos(cnpj)
    if not termos and len(doc) < 11:
        return {"erro": "Informe um nome com palavras distintivas ou o CNPJ/CPF."}

    def casa(*campos):
        texto = _pr_norm(" ".join(str(x or "") for x in campos))
        dig = _re_jr.sub(r"\D", "", " ".join(str(x or "") for x in campos))
        return (doc and len(doc) >= 11 and doc in dig) or (termos and all(t in texto for t in termos))

    achados = []
    for c in s.exec(_sel_pr(Client).where(Client.company_id == cid)).all():
        if casa(c.name, c.cnpj, c.notes):
            achados.append({"onde": "Cliente", "registro": c.name, "detalhe": f"CNPJ {c.cnpj or '—'}"})
    nomes = _pr_clientes(s, cid)
    for d in s.exec(_sel_pr(BusinessDeal.id, BusinessDeal.title, BusinessDeal.client_id, BusinessDeal.stage,
                            _func_pr.substr(BusinessDeal.demand, 1, 3000)).where(BusinessDeal.company_id == cid)).all():
        if casa(d[1], d[4]):
            achados.append({"onde": "Negócio no CRM", "registro": d[1], "detalhe": f"cliente {nomes.get(d[2], '')} · etapa {d[3]}"})
    for p in s.exec(_sel_pr(Partner).where(Partner.company_id == cid)).all():
        if casa(p.name, p.notes):
            achados.append({"onde": "Parceiro", "registro": p.name, "detalhe": p.partner_type})
    for modelo, rotulo, campos in (("NegocioVenda", "Empresa à venda (vitrine)", ("nome", "descricao")),
                                   ("LeadCredito", "Lead do site", ("empresa", "cnpj", "nome")),
                                   ("TrialLead", "Teste do Augur", ("empresa", "cnpj", "nome"))):
        M = globals().get(modelo)
        if M is None:
            continue
        cols = [getattr(M, f) for f in campos]
        for linha in s.exec(_sel_pr(*cols)).all():
            if casa(*linha):
                achados.append({"onde": rotulo, "registro": str(linha[0])[:120], "detalhe": ""})
    return {"buscado": {"nome": nome, "documento": f"***{doc[-4:]}" if doc else ""}, "ocorrencias": achados[:40],
            "observacao": ("Nenhuma ocorrência na base do escritório." if not achados else
                           "Avalie se há conflito: mesma empresa já atendida, contraparte de um cliente na mesma operação, "
                           "concorrente direto de cliente ativo ou parceiro com interesse no resultado.")}


_JR_KYC = {
    "PJ": ["Contrato social/estatuto e última alteração consolidada", "Cartão CNPJ e situação cadastral",
           "Quadro societário até as pessoas físicas (beneficiário final, art. 13 da Res. COAF 36/2021 e Circular BCB 3.978/2020)",
           "Documento dos administradores e procuradores", "Comprovante de endereço da sede",
           "Últimas demonstrações financeiras (faturamento compatível com a operação)",
           "Pesquisa de PEP (pessoa exposta politicamente) entre sócios e administradores",
           "Listas restritivas: CEIS/CNEP (CGU), CEPIM, trabalho escravo (MTE), sanções ONU/OFAC",
           "Processos relevantes, recuperação judicial/falência, protestos", "Mídia negativa (lavagem, corrupção, fraude, ambiental)",
           "Origem dos recursos da operação"],
    "PF": ["Documento de identidade e CPF regular", "Comprovante de endereço", "Pesquisa de PEP e familiares próximos",
           "Listas restritivas e sanções", "Processos e protestos", "Mídia negativa", "Origem do patrimônio/recursos"],
}


def _jr_t_kyc(s, cid, tipo):
    tipo = "PF" if (tipo or "").upper() == "PF" else "PJ"
    return {"tipo": tipo, "itens": _JR_KYC[tipo],
            "observacao": "Use o dossiê do ConstruRisk e a pesquisa na web; marque cada item como ok, pendente ou alerta."}


# ── LGPD ──────────────────────────────────────────────────────────────────────

_JR_ANONIMIZAVEIS = {
    # tabela lógica -> (modelo, campos que viram "[removido LGPD]")
    "lead_site": ("LeadCredito", ["nome", "email", "whatsapp", "empresa", "cnpj", "ip", "garantias"]),
    "teste_augur": ("TrialLead", ["nome", "email", "whatsapp", "empresa", "cnpj"]),
    "prospect_whatsapp": ("WhatsAppProspectSession", ["nome", "empresa", "cnpj", "history_json"]),
    "agendamento": ("AgendaBooking", ["solicitante_nome", "solicitante_email", "solicitante_telefone", "notas"]),
    "formulario": ("FormSubmission", ["enviado_para", "answers_json"]),
}


def _jr_t_localizar(s, cid, termo):
    termo = (termo or "").strip()
    dig = _re_jr.sub(r"\D", "", termo)
    if len(termo) < 4:
        return {"erro": "Informe nome completo, e-mail, telefone ou CPF/CNPJ."}
    alvo = _pr_norm(termo)

    def casa(*v):
        texto = _pr_norm(" ".join(str(x or "") for x in v))
        if "@" in termo:
            return alvo in texto
        if len(dig) >= 8:
            return dig in _re_jr.sub(r"\D", "", " ".join(str(x or "") for x in v))
        return alvo in texto

    fontes = [
        ("cliente", Client, ["name", "email", "finance_email", "phone", "cnpj"], Client.company_id == cid, False),
        ("usuario", User, ["name", "email"], None, False),
        ("lead_site", globals().get("LeadCredito"), ["nome", "email", "whatsapp", "empresa", "cnpj"], None, True),
        ("teste_augur", globals().get("TrialLead"), ["nome", "email", "whatsapp", "empresa", "cnpj"], None, True),
        ("prospect_whatsapp", globals().get("WhatsAppProspectSession"), ["nome", "phone", "empresa", "cnpj"], None, True),
        ("conversa_whatsapp", globals().get("WhatsAppThread"), ["contact_name", "contact_phone"],
         "company", False),
        ("agendamento", AgendaBooking, ["solicitante_nome", "solicitante_email", "solicitante_telefone"],
         AgendaBooking.company_id == cid, True),
        ("formulario", globals().get("FormSubmission"), ["enviado_para"], "company", True),
        ("consentimento_credito", globals().get("CreditConsent"), ["signed_by_name", "signed_by_document"], "company", False),
        ("consentimento_scr", globals().get("ConsultaScrConsent"), ["subject_doc", "invited_email", "signed_by_name"], "company", False),
    ]
    achados = []
    for nome_fonte, M, campos, filtro, anonimizavel in fontes:
        if M is None:
            continue
        q = _sel_pr(M.id, *[getattr(M, f) for f in campos])
        if nome_fonte == "usuario":  # a tabela de usuários é compartilhada: só quem tem vínculo com este escritório
            q = q.join(Membership, Membership.user_id == User.id).where(Membership.company_id == cid)
        if filtro == "company" and hasattr(M, "company_id"):
            q = q.where(M.company_id == cid)
        elif filtro is not None and filtro != "company":
            q = q.where(filtro)
        for linha in s.exec(q).all():
            if casa(*linha[1:]):
                dados = {f: ("***" + str(v)[-4:] if f in ("cnpj", "signed_by_document", "subject_doc") and v else v)
                         for f, v in zip(campos, linha[1:]) if v}
                if nome_fonte == "agendamento":
                    b = s.get(AgendaBooking, linha[0])
                    anonimizavel = not b.client_id
                achados.append({"tabela": nome_fonte, "id": linha[0], "dados": dados, "pode_anonimizar": anonimizavel})
                if len(achados) >= 60:
                    break
    return {"termo": termo, "ocorrencias": achados, "total": len(achados),
            "observacao": ("Clientes, usuários, conversas e consentimentos não são anonimizados por aqui: dependem de análise "
                           "(obrigação legal, contrato, defesa em processo). Leads, testes, prospects, agendamentos de "
                           "não clientes e formulários podem ser anonimizados com aprovação.")}


def _jr_t_retencao(s, cid, meses):
    meses = max(3, min(int(meses or 24), 120))
    corte = _pr_hoje() - _td_pr(days=30 * meses)
    out = {}
    for nome, (modelo, _) in _JR_ANONIMIZAVEIS.items():
        M = globals().get(modelo)
        if M is None:
            continue
        campo_data = next((f for f in ("criado_em", "created_at", "sent_at") if hasattr(M, f)), None)
        if not campo_data:
            continue
        ids = []
        for i, d in s.exec(_sel_pr(M.id, getattr(M, campo_data))).all():
            dt = _pr_data(str(d)[:10]) if d else None
            if dt and dt < corte:
                if nome == "agendamento" and s.get(M, i).client_id:
                    continue
                if nome == "teste_augur" and getattr(s.get(M, i), "converted", False):
                    continue
                ids.append(i)
        out[nome] = {"registros_antigos": len(ids), "ids": ids[:200]}
    return {"mais_antigos_que_meses": meses, "por_tabela": out,
            "observacao": "Leads e contatos que não viraram cliente e já passaram do prazo de retenção sugerido."}


def _jr_t_propor_anonimizacao(s, cid, itens, motivo):
    validos, recusados = [], []
    for it in itens or []:
        tab, rid = str((it or {}).get("tabela", "")), int((it or {}).get("id") or 0)
        if tab not in _JR_ANONIMIZAVEIS or not rid:
            recusados.append(f"{tab}#{rid}")
            continue
        M = globals().get(_JR_ANONIMIZAVEIS[tab][0])
        reg = s.get(M, rid) if M is not None else None
        if not reg or (hasattr(reg, "company_id") and reg.company_id not in (cid, None)) or (tab == "agendamento" and reg.client_id):
            recusados.append(f"{tab}#{rid}")
            continue
        validos.append({"tabela": tab, "id": rid})
    if not validos:
        return {"ok": False, "erro": "Nenhum item anonimizável (só leads, testes, prospects, agendamentos de não clientes e "
                                     "formulários).", "recusados": recusados}
    if len((motivo or "").strip()) < 10:
        return {"ok": False, "erro": "Informe o motivo (pedido do titular, fim do prazo de retenção...)."}
    resumo = {}
    for v in validos:
        resumo[v["tabela"]] = resumo.get(v["tabela"], 0) + 1
    acao = _pr_registrar_proposta(
        s, cid, tipo="lgpd_anonimizar", titulo=f"LGPD: anonimizar {len(validos)} registro(s)",
        destinatario="Banco de dados da plataforma (irreversível)", assunto=motivo.strip()[:200],
        corpo=f"Motivo: {motivo.strip()}\n\n" + "\n".join(f"• {k}: {n} registro(s)" for k, n in resumo.items()),
        payload_json=_json_pr.dumps({"itens": validos[:500], "motivo": motivo.strip()[:500]}, ensure_ascii=False))
    return {"ok": True, "proposta_id": acao.id, "anonimizar": len(validos), "recusados": recusados,
            "observacao": "Irreversível: só um admin aprova. Os campos pessoais viram '[removido LGPD]'."}


def _jr_exec_anonimizar(s, acao) -> str:
    p = _json_pr.loads(acao.payload_json or "{}")
    n = 0
    for it in p.get("itens") or []:
        modelo, campos = _JR_ANONIMIZAVEIS.get(it.get("tabela"), (None, []))
        M = globals().get(modelo) if modelo else None
        reg = s.get(M, int(it.get("id") or 0)) if M is not None else None
        if not reg or (it.get("tabela") == "agendamento" and reg.client_id):
            continue
        for f in campos:
            if hasattr(reg, f):
                setattr(reg, f, "{}" if f in ("answers_json",) else "[]" if f == "history_json" else "[removido LGPD]")
        s.add(reg)
        n += 1
    s.commit()
    print(f"[lgpd] {n} registro(s) anonimizado(s) — ação #{acao.id}, motivo: {p.get('motivo', '')[:120]}")
    return f"{n} registro(s) anonimizado(s). Motivo registrado na proposta #{acao.id}."


# ── Registro ──────────────────────────────────────────────────────────────────

_JR_S = {"type": "string"}
_JR_FERRAMENTAS = {
    "jur_contratos": {
        "fn": _jr_t_contratos, "rotulo": "Consultou os contratos",
        "description": "Contratos cadastrados no financeiro: valor mensal, vencimento, início e fim, dias para terminar e "
                       "contratos sem e-mail de cobrança.",
        "props": {"situacao": {"type": "string", "enum": ["todos", "ativos", "vencendo", "sem_fim"]}}},
    "jur_gerar_minuta": {
        "fn": _jr_t_gerar_minuta, "rotulo": "Gerou a minuta do contrato",
        "description": "Gera a minuta em Word: qualificação das partes, cláusulas numeradas (CLÁUSULA PRIMEIRA — ..., itens "
                       "1.1, 1.2), fecho, local e data, assinaturas e testemunhas. Campos desconhecidos entre colchetes.",
        "props": {"titulo": _JR_S, "contratante": {"type": "string", "description": "Qualificação completa do contratante."},
                  "contratada": {"type": "string", "description": "Qualificação da M. Capital (vazio = campo a preencher)."},
                  "clausulas": {"type": "array", "items": {"type": "object", "additionalProperties": False,
                                                           "required": ["titulo", "itens"],
                                                           "properties": {"titulo": _JR_S, "itens": {"type": "array", "items": _JR_S}}}},
                  "local": _JR_S, "data": _JR_S, "assinatura_contratante": _JR_S, "assinatura_contratada": _JR_S, "fecho": _JR_S}},
    "jur_propor_contrato": {
        "fn": _jr_t_propor_contrato, "rotulo": "Propôs cadastrar o contrato",
        "description": "Cria uma PROPOSTA de cadastro do contrato assinado no financeiro (gera cobrança mensal). Só um "
                       "admin aprova.",
        "props": {"cliente": _JR_S, "nome_contrato": _JR_S, "servicos": _JR_S, "valor_mensal": {"type": "number"},
                  "dia_vencimento": {"type": "integer", "description": "1 a 28."},
                  "data_inicio": {"type": "string", "description": "DD/MM/AAAA"},
                  "data_fim": {"type": "string", "description": "DD/MM/AAAA ou vazio."},
                  "email_cobranca": {"type": "string", "description": "Vazio = e-mail financeiro do cadastro."},
                  "observacao": _JR_S}},
    "comp_conflitos": {
        "fn": _jr_t_conflitos, "rotulo": "Checou conflito de interesse",
        "description": "Procura a empresa (nome ou CNPJ/CPF) em clientes, negócios do CRM, parceiros, vitrine de empresas à "
                       "venda e leads, para avaliar conflito de interesse.",
        "props": {"nome": _JR_S, "cnpj": {"type": "string", "description": "CNPJ/CPF ou vazio."}}},
    "comp_checklist_kyc": {
        "fn": _jr_t_kyc, "rotulo": "Montou o checklist de KYC",
        "description": "Checklist de KYC/PLD para pessoa jurídica ou física.",
        "props": {"tipo": {"type": "string", "enum": ["PJ", "PF"]}}},
    "lgpd_localizar": {
        "fn": _jr_t_localizar, "rotulo": "Localizou os dados da pessoa",
        "description": "Onde estão os dados de uma pessoa na plataforma (cliente, usuário, leads, teste do Augur, WhatsApp, "
                       "agendamentos, formulários, consentimentos), por nome, e-mail, telefone ou CPF/CNPJ.",
        "props": {"termo": _JR_S}},
    "lgpd_retencao": {
        "fn": _jr_t_retencao, "rotulo": "Levantou dados fora do prazo de retenção",
        "description": "Leads, testes, prospects, agendamentos de não clientes e formulários mais antigos que N meses.",
        "props": {"meses": {"type": "integer", "description": "3 a 120 (padrão 24)."}}},
    "lgpd_propor_anonimizacao": {
        "fn": _jr_t_propor_anonimizacao, "rotulo": "Propôs anonimizar dados",
        "description": "Cria uma PROPOSTA de anonimização (irreversível) de leads, testes, prospects, agendamentos de não "
                       "clientes e formulários. Só um admin aprova.",
        "props": {"itens": {"type": "array", "items": {"type": "object", "additionalProperties": False, "required": ["tabela", "id"],
                                                       "properties": {"tabela": {"type": "string", "enum": list(_JR_ANONIMIZAVEIS)},
                                                                      "id": {"type": "integer"}}}},
                  "motivo": _JR_S}},
}

for _nome_jr, _spec_jr in _JR_FERRAMENTAS.items():
    _pr_registrar_ferramenta(_nome_jr, _spec_jr)

_PR_EXECUTORES_EXTRA["registrar_contrato"] = _jr_exec_registrar_contrato
_PR_EXECUTORES_EXTRA["lgpd_anonimizar"] = _jr_exec_anonimizar

_JR_AGENTES = {
    "contratos": {
        "web": False, "papeis": _PR_ADMIN,
        "ferramentas": ["jur_contratos", "jur_gerar_minuta", "jur_propor_contrato", "com_negocios", "com_formularios",
                        "cli_panorama", "conh_buscar", "conh_ler", "dr_documentos", "dr_ler_documento", "ops_propor_tarefa"],
        "instrucoes": (
            "Você cuida dos contratos do escritório com os clientes.\n"
            "- Carteira: contratos que terminam em 90 dias, sem data de fim, sem e-mail de cobrança; proponha tarefas de "
            "renovação ou ajuste para quem cuida do cliente.\n"
            "- Minuta: a partir da proposta aceita (com_negocios, documentos, conversa) e, se houver, de um contrato "
            "modelo anexado ou na base (conh_buscar 'contrato'). Cláusulas mínimas: objeto e escopo (com o que NÃO está "
            "incluído), prazo e renovação, honorários e forma de pagamento, reajuste anual pelo IPCA, obrigações das "
            "partes (inclusive envio de informações pelo cliente), confidencialidade, proteção de dados (LGPD, papel de "
            "operador), propriedade intelectual dos materiais, limitação de responsabilidade (obrigação de meio, sem "
            "garantia de resultado), rescisão com aviso prévio, multa, foro de Brusque (SC). Use colchetes para o que "
            "não souber; nunca invente CNPJ, endereço ou valor. Gere com jur_gerar_minuta.\n"
            "- Contrato assinado: proponha o cadastro no financeiro com jur_propor_contrato (isso liga a cobrança "
            "mensal).\n"
            "Lembre no chat que a minuta precisa de revisão jurídica antes de ser assinada.")},
    "compliance": {
        "web": True, "papeis": _PR_TODOS,
        "ferramentas": ["comp_conflitos", "comp_checklist_kyc", "cred_dossies", "cred_scr", "cli_panorama", "com_negocios",
                        "conh_buscar", "conh_propor_registro", "ops_propor_tarefa"],
        "instrucoes": (
            "Você faz o KYC e a checagem de conflitos antes de o escritório aceitar um cliente ou operação.\n"
            "1) Conflito de interesse (comp_conflitos) com o nome e o CNPJ da empresa e dos sócios relevantes; "
            "2) checklist de KYC (comp_checklist_kyc) — para cada item: ok, pendente ou alerta, com a fonte; use os "
            "dossiês do ConstruRisk (cred_dossies) e pesquise na web: PEP, listas restritivas (CEIS/CNEP, trabalho "
            "escravo, sanções), recuperação judicial/falência, processos relevantes e mídia negativa; 3) conclusão: "
            "aprovado, aprovado com ressalvas (quais) ou recusado, e o que pedir ao cliente.\n"
            "Seja factual: diferencie fato confirmado de indício. Ao final, proponha registrar o parecer na base "
            "(conh_propor_registro, interno, tipo 'decisao').")},
    "lgpd": {
        "web": False, "papeis": _PR_ADMIN,
        "ferramentas": ["lgpd_localizar", "lgpd_retencao", "lgpd_propor_anonimizacao", "rel_gerar_relatorio", "conh_buscar",
                        "ops_propor_tarefa"],
        "instrucoes": (
            "Você cuida da privacidade (LGPD) dos dados na plataforma.\n"
            "- Pedido de titular (acesso, correção, exclusão — art. 18): localize os dados com lgpd_localizar, explique "
            "onde estão e por quê (base legal provável: execução de contrato, obrigação legal, legítimo interesse, "
            "consentimento) e prepare a resposta ao titular em Word (rel_gerar_relatorio, tipo 'outro'), no prazo de "
            "15 dias. Exclusão: proponha a anonimização do que for possível (lgpd_propor_anonimizacao) e diga o que "
            "precisa ser mantido e por quê (ex.: contrato, obrigações fiscais).\n"
            "- Retenção: com lgpd_retencao, liste leads e contatos que não viraram cliente e já passaram do prazo, e "
            "proponha a anonimização em lote com o motivo.\n"
            "- Clientes, usuários, conversas e consentimentos não são anonimizados por aqui: se for o caso, proponha uma "
            "tarefa para análise com o responsável.\n"
            "Nunca exponha dados completos no chat além do necessário para o pedido.")},
}

for _key_jr, _cfg_jr in _JR_AGENTES.items():
    _ag_jr = _PREDIO_AGENTES.get(_key_jr)
    if not _ag_jr:
        continue
    _ag_jr.update(ferramentas=list(_cfg_jr["ferramentas"]), web=_cfg_jr["web"], papeis=_cfg_jr["papeis"], ativo=True)
    _PR_INSTRUCOES[_key_jr] = _cfg_jr["instrucoes"]

print("[predio_juridico] Andar de Jurídico e Compliance carregado.")

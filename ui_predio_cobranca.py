# ============================================================================
# ui_predio_cobranca.py — 9º andar: a Cobrança dá baixa, altera e cancela títulos
# ============================================================================
# Exec'd no namespace do app.py, DEPOIS de ui_predio.py, ui_financeiro_contratos.py,
# ui_predio_financeiro.py e ui_predio_faturamento.py.
#
# Títulos a receber = OfficeFinancialEntry (entry_kind "receber"). Os que vêm de contrato
# têm uma CobrancaMensal por trás (document_number "contrato-{id}-{AAAA-MM}"): nesses, a
# mudança é feita na cobrança e sincronizada no título, como a tela de Cobranças faz.
#
# Quando o sócio pedir, a Cobrança propõe (sempre com aprovação de admin):
#   - baixa: data, valor recebido, forma e conta; pagamento parcial pode gerar um título
#     com o saldo; recebido por fora do boleto, o boleto é cancelado no Mercado Pago
#   - alteração: vencimento, valor, descrição, observação; com boleto emitido, só com
#     reemissão (cancela o antigo, gera o novo e envia ao cliente); com NF emitida, o
#     valor não muda (a NF teria de ser cancelada antes)
#   - cancelamento: cancela o título (e o boleto); com NF emitida, recusa
# ============================================================================

import re as _re_cb

_CB_FORMAS = ["pix", "boleto", "transferencia", "cartao", "dinheiro", "outro"]
_CB_REF = _re_cb.compile(r"^contrato-(\d+)-(\d{4}-\d{2})$")


def _cb_titulo(s, cid, titulo_id):
    e = s.get(OfficeFinancialEntry, int(titulo_id or 0))
    return e if e and e.company_id == cid and e.entry_kind == "receber" else None


def _cb_cobranca(s, e):
    """A CobrancaMensal por trás do título, se ele veio de um contrato."""
    m = _CB_REF.match(e.document_number or "")
    if not m or globals().get("CobrancaMensal") is None:
        return None
    return s.exec(_sel_pr(CobrancaMensal).where(CobrancaMensal.contrato_id == int(m.group(1)),
                                                CobrancaMensal.competencia == m.group(2),
                                                CobrancaMensal.company_id == e.company_id)).first()


def _cb_aberto(e) -> bool:
    return _office_is_open(e) if "_office_is_open" in globals() else e.status == "aberto"


def _cb_desc(e, nomes) -> str:
    return f"{nomes.get(e.client_id, 'sem cliente')} — {e.description}"


# ── Consulta ─────────────────────────────────────────────────────────────────

def _cb_t_titulos(s, cid, cliente, situacao, dias):
    E = OfficeFinancialEntry
    q = _sel_pr(E).where(E.company_id == cid, E.entry_kind == "receber")
    if (cliente or "").strip():
        c, cands = _pr_resolver_cliente(s, cid, cliente)
        if not c:
            return _pr_nao_achei(cliente, cands)
        q = q.where(E.client_id == c.id)
    hoje = _pr_hoje()
    janela = max(1, min(int(dias or 180), 730))
    nomes = _pr_clientes(s, cid)
    out = []
    for e in s.exec(q.order_by(E.due_date)).all():
        venc = _pr_data(e.due_date)
        aberto = _cb_aberto(e)
        if situacao == "em_aberto" and not aberto:
            continue
        if situacao == "vencidos" and not (aberto and venc and venc < hoje):
            continue
        if situacao == "pagos" and e.status not in ("recebido", "pago", "parcial"):
            continue
        if situacao in ("pagos", "todos") and venc and venc < hoje - _td_pr(days=janela):
            continue
        cob = _cb_cobranca(s, e)
        out.append({"titulo_id": e.id, "cliente": nomes.get(e.client_id, ""), "descricao": e.description,
                    "vencimento": _pr_fmt_data(venc), "valor": round(e.amount_expected_brl or 0, 2), "status": e.status,
                    "dias_atraso": (hoje - venc).days if aberto and venc and venc < hoje else 0,
                    "recebido_em": _pr_fmt_data(_pr_data(e.settlement_date)), "valor_recebido": round(e.amount_realized_brl or 0, 2),
                    "origem": "contrato" if cob else "avulso",
                    "boleto_emitido": bool(cob and cob.boleto_url), "nf_emitida": bool(cob and (cob.nf_numero or cob.nf_chave))})
        if len(out) >= 60:
            break
    return {"titulos": out, "total": len(out), "hoje": _pr_fmt_data(hoje),
            "observacao": "Use o titulo_id nas propostas de baixa, alteração ou cancelamento."}


# ── Baixa ────────────────────────────────────────────────────────────────────

def _cb_t_propor_baixa(s, cid, titulo_id, data_pagamento, valor_pago, forma_pagamento, conta_bancaria, saldo_vencimento,
                       observacao):
    e = _cb_titulo(s, cid, titulo_id)
    if not e:
        return {"ok": False, "erro": "Título não encontrado (use o titulo_id de cob_titulos)."}
    if not _cb_aberto(e):
        return {"ok": False, "erro": f"Esse título já está '{e.status}'."}
    d = _pr_data(data_pagamento) if (data_pagamento or "").strip() else _pr_hoje()
    if not d or d > _pr_hoje():
        return {"ok": False, "erro": "Data de recebimento inválida ou no futuro."}
    previsto = round(float(e.amount_expected_brl or 0), 2)
    valor = round(float(valor_pago or 0) or previsto, 2)
    if valor <= 0:
        return {"ok": False, "erro": "Valor recebido inválido."}
    forma = forma_pagamento if forma_pagamento in _CB_FORMAS else "outro"
    conta_id, conta_nome = (_fi_resolver(s, cid, "OfficeBankAccount", conta_bancaria) if "_fi_resolver" in globals()
                            else (None, ""))
    if (conta_bancaria or "").strip() and not conta_id:
        return {"ok": False, "erro": f"Conta bancária '{conta_bancaria}' não encontrada (veja cp_cadastros)."}
    saldo, sv = round(previsto - valor, 2), None
    if (saldo_vencimento or "").strip():
        sv = _pr_data(saldo_vencimento)
        if saldo <= 0:
            return {"ok": False, "erro": "Não há saldo: o valor recebido cobre o título."}
        if not sv or sv < _pr_hoje():
            return {"ok": False, "erro": "Vencimento do saldo inválido (DD/MM/AAAA, hoje ou depois)."}
    cob = _cb_cobranca(s, e)
    nomes = _pr_clientes(s, cid)
    linhas = [f"Recebido em {_pr_fmt_data(d)} · {_cm_brl(valor)} · {forma}" + (f" · conta {conta_nome}" if conta_nome else "")]
    if abs(saldo) >= 0.01:
        if saldo < 0:
            linhas.append(f"Recebido {_cm_brl(-saldo)} acima do previsto ({_cm_brl(previsto)}): juros/multa.")
        elif sv:
            linhas.append(f"Pagamento parcial: o saldo de {_cm_brl(saldo)} vira um título novo com vencimento {_pr_fmt_data(sv)}.")
        else:
            linhas.append(f"Recebido {_cm_brl(saldo)} abaixo do previsto ({_cm_brl(previsto)}) e baixado como quitado "
                          "(desconto). Para cobrar o saldo, informe o vencimento do saldo.")
    if cob and cob.boleto_url and forma != "boleto":
        linhas.append("O boleto em aberto será cancelado no Mercado Pago para o cliente não pagar duas vezes.")
    if (observacao or "").strip():
        linhas.append(f"Obs.: {observacao.strip()[:300]}")
    acao = _pr_registrar_proposta(
        s, cid, tipo="baixar_titulo", client_id=e.client_id, titulo=f"Baixar recebimento: {_cb_desc(e, nomes)}",
        destinatario=f"Financeiro · título #{e.id} ({'contrato' if cob else 'avulso'}) · venc. {_pr_fmt_data(_pr_data(e.due_date))}",
        assunto=e.description, corpo="\n".join(linhas),
        payload_json=_json_pr.dumps({"titulo_id": e.id, "data": d.isoformat(), "valor": valor, "forma": forma, "conta_id": conta_id,
                                     "saldo": saldo if sv else 0, "saldo_vencimento": sv.isoformat() if sv else "",
                                     "observacao": (observacao or "").strip()[:300]}))
    return {"ok": True, "proposta_id": acao.id, "status": "aguardando aprovação"}


def _cb_exec_baixa(s, acao) -> str:
    p = _json_pr.loads(acao.payload_json or "{}")
    e = _cb_titulo(s, acao.company_id, p["titulo_id"])
    if not e:
        raise _PrErro("Título não encontrado.")
    if not _cb_aberto(e):
        raise _PrErro(f"O título já está '{e.status}'.")
    cob = _cb_cobranca(s, e)
    extra = ""
    if cob:
        if cob.boleto_url and cob.mp_payment_id and p["forma"] != "boleto":
            try:
                _ct_mp_cancelar_boleto(cob.mp_payment_id)
                cob.boleto_url = ""
                extra = " Boleto cancelado no Mercado Pago."
            except Exception as ex:
                extra = f" Atenção: o boleto não foi cancelado no Mercado Pago ({str(ex)[:80]}); cancele na tela de Cobranças."
        cob.status, cob.valor_pago_cents = "pago", int(round(p["valor"] * 100))
        cob.data_pagamento, cob.forma_pagamento = p["data"], p["forma"]
        if p.get("observacao"):
            cob.observacao = p["observacao"]
        cob.updated_at = _dt_pr.utcnow()
        s.add(cob)
        s.commit()
        _ct_sync_entry(s, cob, user_id=acao.decidido_por_user_id or 1)
        s.refresh(e)
    else:
        e.status, e.settlement_date, e.amount_realized_brl = "recebido", p["data"], p["valor"]
        if p.get("observacao"):
            e.notes = ((e.notes or "") + "\n" + p["observacao"]).strip()
    if p.get("conta_id"):
        e.bank_account_id = p["conta_id"]
    e.updated_by_user_id, e.updated_at = acao.decidido_por_user_id, _dt_pr.utcnow()
    s.add(e)
    s.commit()
    msg = f"Título #{e.id} baixado: {_cm_brl(p['valor'])} em {_pr_fmt_data(_pr_data(p['data']))}.{extra}"
    if p.get("saldo") and p.get("saldo_vencimento"):
        novo = OfficeFinancialEntry(company_id=e.company_id, created_by_user_id=acao.decidido_por_user_id or e.created_by_user_id,
                                    entry_kind="receber", status="aberto", client_id=e.client_id,
                                    description=f"Saldo — {e.description}"[:300], document_number=f"saldo-{e.id}",
                                    competence_date=e.competence_date, due_date=p["saldo_vencimento"],
                                    amount_expected_brl=p["saldo"], revenue_type_id=e.revenue_type_id,
                                    category_id=e.category_id, cost_center_id=e.cost_center_id)
        s.add(novo)
        s.commit()
        s.refresh(novo)
        msg += f" Saldo de {_cm_brl(p['saldo'])} lançado no título #{novo.id}, vencimento {_pr_fmt_data(_pr_data(p['saldo_vencimento']))}."
    return msg


# ── Alteração ────────────────────────────────────────────────────────────────

def _cb_t_propor_alterar(s, cid, titulo_id, novo_vencimento, novo_valor, descricao, observacao, reemitir_boleto, motivo):
    e = _cb_titulo(s, cid, titulo_id)
    if not e:
        return {"ok": False, "erro": "Título não encontrado (use o titulo_id de cob_titulos)."}
    if not _cb_aberto(e):
        return {"ok": False, "erro": f"Esse título está '{e.status}': só títulos em aberto mudam."}
    if len((motivo or "").strip()) < 5:
        return {"ok": False, "erro": "Informe o motivo (ex.: cliente pediu prorrogação, renegociação)."}
    mud = {}
    if (novo_vencimento or "").strip():
        d = _pr_data(novo_vencimento)
        if not d:
            return {"ok": False, "erro": "Vencimento inválido: DD/MM/AAAA."}
        if d.isoformat() != (e.due_date or "")[:10]:
            mud["vencimento"] = d.isoformat()
    if float(novo_valor or 0) > 0 and abs(float(novo_valor) - float(e.amount_expected_brl or 0)) >= 0.01:
        mud["valor"] = round(float(novo_valor), 2)
    cob = _cb_cobranca(s, e)
    if (descricao or "").strip() and not cob and descricao.strip() != e.description:
        mud["descricao"] = descricao.strip()[:300]
    if (observacao or "").strip():
        mud["observacao"] = observacao.strip()[:500]
    if not mud:
        return {"ok": False, "erro": "Nada muda em relação ao título atual."}
    if cob:
        if "valor" in mud and (cob.nf_numero or cob.nf_chave):
            return {"ok": False, "erro": f"A NFS-e {cob.nf_numero or ''} já foi emitida no valor atual: cancele a NF na tela de "
                                         "Cobranças antes de mudar o valor (ou registre a diferença numa baixa)."}
        if cob.boleto_url and {"vencimento", "valor"} & set(mud) and not reemitir_boleto:
            return {"ok": False, "erro": "Esse título tem boleto emitido: para mudar vencimento ou valor, use reemitir_boleto "
                                         "= true (cancela o boleto antigo e envia um novo ao cliente)."}
    nomes = _pr_clientes(s, cid)
    linhas = [f"Motivo: {motivo.strip()[:500]}"]
    if "vencimento" in mud:
        linhas.append(f"• Vencimento: {_pr_fmt_data(_pr_data(e.due_date))} → {_pr_fmt_data(_pr_data(mud['vencimento']))}")
    if "valor" in mud:
        linhas.append(f"• Valor: {_cm_brl(e.amount_expected_brl)} → {_cm_brl(mud['valor'])}")
    if "descricao" in mud:
        linhas.append(f"• Descrição: {e.description} → {mud['descricao']}")
    if "observacao" in mud:
        linhas.append(f"• Observação: {mud['observacao']}")
    reemitir = bool(cob and cob.boleto_url and reemitir_boleto and {"vencimento", "valor"} & set(mud))
    if reemitir:
        linhas.append("O boleto atual é cancelado no Mercado Pago e um novo é emitido e enviado ao cliente.")
    acao = _pr_registrar_proposta(
        s, cid, tipo="alterar_titulo", client_id=e.client_id, titulo=f"Alterar título: {_cb_desc(e, nomes)}",
        destinatario=f"Financeiro · título #{e.id} ({'contrato' if cob else 'avulso'})", assunto=e.description,
        corpo="\n".join(linhas), payload_json=_json_pr.dumps({"titulo_id": e.id, "mudancas": mud, "reemitir": reemitir},
                                                             ensure_ascii=False))
    return {"ok": True, "proposta_id": acao.id, "mudancas": list(mud), "reemite_boleto": reemitir}


def _cb_exec_alterar(s, acao) -> str:
    p = _json_pr.loads(acao.payload_json or "{}")
    e = _cb_titulo(s, acao.company_id, p["titulo_id"])
    if not e or not _cb_aberto(e):
        raise _PrErro("Título não encontrado ou já baixado.")
    mud, cob = p["mudancas"], _cb_cobranca(s, e)
    extra = ""
    if cob:
        if p.get("reemitir") and cob.boleto_url:
            if cob.mp_payment_id:
                _ct_mp_cancelar_boleto(cob.mp_payment_id)  # falha aqui interrompe: nada muda
            cob.boleto_url, cob.boleto_codigo, cob.mp_payment_id = "", "", ""
        if "vencimento" in mud:
            cob.data_vencimento = mud["vencimento"]
            if cob.status == "vencido" and _pr_data(mud["vencimento"]) >= _pr_hoje():
                cob.status = "pendente"
        if "valor" in mud:
            cob.valor_cents = int(round(mud["valor"] * 100))
        if "observacao" in mud:
            cob.observacao = mud["observacao"]
        cob.updated_at = _dt_pr.utcnow()
        s.add(cob)
        s.commit()
        _ct_sync_entry(s, cob, user_id=acao.decidido_por_user_id or 1)
        if p.get("reemitir"):
            k = s.get(ContratoCliente, cob.contrato_id)
            try:
                dados = _ct_mp_gerar_boleto(cob, k, s)
                cob.mp_payment_id, cob.boleto_url, cob.boleto_codigo = dados["mp_payment_id"], dados["boleto_url"], dados["boleto_codigo"]
                s.add(cob)
                s.commit()
                try:
                    _ct_enviar_email_boleto(cob, k, s)
                    extra = " Novo boleto emitido e enviado ao cliente."
                except Exception as em:
                    extra = f" Novo boleto emitido, mas o e-mail falhou ({str(em)[:60]}): reenvie pela tela de Cobranças."
            except Exception as eb:
                extra = (f" Atenção: o boleto antigo foi cancelado e o novo NÃO foi emitido ({str(eb)[:80]}); "
                         "emita pela tela de Cobranças ou peça ao Faturamento.")
    else:
        if "vencimento" in mud:
            e.due_date = mud["vencimento"]
        if "valor" in mud:
            e.amount_expected_brl = mud["valor"]
        if "descricao" in mud:
            e.description = mud["descricao"]
        if "observacao" in mud:
            e.notes = ((e.notes or "") + "\n" + mud["observacao"]).strip()
        e.updated_by_user_id, e.updated_at = acao.decidido_por_user_id, _dt_pr.utcnow()
        s.add(e)
        s.commit()
    return f"Título #{e.id} alterado.{extra}"


# ── Cancelamento ─────────────────────────────────────────────────────────────

def _cb_t_propor_cancelar(s, cid, titulo_id, motivo):
    e = _cb_titulo(s, cid, titulo_id)
    if not e:
        return {"ok": False, "erro": "Título não encontrado (use o titulo_id de cob_titulos)."}
    if not _cb_aberto(e):
        return {"ok": False, "erro": f"Esse título já está '{e.status}'."}
    if len((motivo or "").strip()) < 5:
        return {"ok": False, "erro": "Informe o motivo do cancelamento."}
    cob = _cb_cobranca(s, e)
    if cob and (cob.nf_numero or cob.nf_chave):
        return {"ok": False, "erro": f"A NFS-e {cob.nf_numero or ''} já foi emitida para este título: cancele a NF na tela de "
                                     "Cobranças primeiro (o cancelamento fiscal tem prazo e regras próprias)."}
    nomes = _pr_clientes(s, cid)
    acao = _pr_registrar_proposta(
        s, cid, tipo="cancelar_titulo", client_id=e.client_id, titulo=f"Cancelar título: {_cb_desc(e, nomes)}",
        destinatario=f"Financeiro · título #{e.id} · {_cm_brl(e.amount_expected_brl)} · venc. {_pr_fmt_data(_pr_data(e.due_date))}",
        assunto=e.description, corpo=f"Motivo: {motivo.strip()[:500]}"
                                     + ("\nO boleto emitido é cancelado no Mercado Pago." if cob and cob.boleto_url else ""),
        payload_json=_json_pr.dumps({"titulo_id": e.id, "motivo": motivo.strip()[:500]}, ensure_ascii=False))
    return {"ok": True, "proposta_id": acao.id}


def _cb_exec_cancelar(s, acao) -> str:
    p = _json_pr.loads(acao.payload_json or "{}")
    e = _cb_titulo(s, acao.company_id, p["titulo_id"])
    if not e or not _cb_aberto(e):
        raise _PrErro("Título não encontrado ou já baixado.")
    cob = _cb_cobranca(s, e)
    if cob:
        if cob.nf_numero or cob.nf_chave:
            raise _PrErro("A NFS-e foi emitida depois da proposta: cancele a NF antes.")
        if cob.boleto_url and cob.mp_payment_id:
            _ct_mp_cancelar_boleto(cob.mp_payment_id)
            cob.boleto_url = ""
        cob.status, cob.updated_at = "cancelado", _dt_pr.utcnow()
        cob.observacao = ((cob.observacao or "") + f" Cancelado: {p['motivo']}").strip()[:500]
        s.add(cob)
        s.commit()
        _ct_sync_entry(s, cob, user_id=acao.decidido_por_user_id or 1)
    else:
        e.status = "cancelado"
        e.notes = ((e.notes or "") + f"\nCancelado: {p['motivo']}").strip()
        e.updated_by_user_id, e.updated_at = acao.decidido_por_user_id, _dt_pr.utcnow()
        s.add(e)
        s.commit()
    return f"Título #{e.id} cancelado."


# ── Registro ──────────────────────────────────────────────────────────────────

_CB_S = {"type": "string"}
_CB_FERRAMENTAS = {
    "cob_titulos": {
        "fn": _cb_t_titulos, "rotulo": "Consultou os títulos a receber",
        "description": "Títulos a receber com titulo_id: cliente, descrição, vencimento, valor, status, dias de atraso, "
                       "recebimento, origem (contrato ou avulso) e se já têm boleto ou NF.",
        "props": {"cliente": {"type": "string", "description": "Nome do cliente ou vazio."},
                  "situacao": {"type": "string", "enum": ["em_aberto", "vencidos", "pagos", "todos"]},
                  "dias": {"type": "integer", "description": "Para pagos/todos: janela em dias (padrão 180)."}}},
    "cob_propor_baixa": {
        "fn": _cb_t_propor_baixa, "rotulo": "Propôs dar baixa num título",
        "description": "Cria uma PROPOSTA de baixa (recebimento) de um título: data, valor, forma e conta. Pagamento parcial "
                       "com saldo_vencimento gera um título novo com o saldo. Recebido por fora do boleto, cancela o boleto.",
        "props": {"titulo_id": {"type": "integer"},
                  "data_pagamento": {"type": "string", "description": "DD/MM/AAAA (vazio = hoje)."},
                  "valor_pago": {"type": "number", "description": "0 = valor do título."},
                  "forma_pagamento": {"type": "string", "enum": _CB_FORMAS},
                  "conta_bancaria": {"type": "string", "description": "Nome da conta (cp_cadastros) ou vazio."},
                  "saldo_vencimento": {"type": "string", "description": "Parcial: vencimento do saldo (DD/MM/AAAA) ou vazio."},
                  "observacao": _CB_S}},
    "cob_propor_alterar": {
        "fn": _cb_t_propor_alterar, "rotulo": "Propôs alterar um título",
        "description": "Cria uma PROPOSTA de alteração de um título em aberto: novo vencimento, novo valor, descrição (só "
                       "avulsos) e observação. Com boleto emitido, exige reemitir_boleto = true.",
        "props": {"titulo_id": {"type": "integer"}, "novo_vencimento": {"type": "string", "description": "DD/MM/AAAA ou vazio."},
                  "novo_valor": {"type": "number", "description": "0 = mantém."}, "descricao": _CB_S, "observacao": _CB_S,
                  "reemitir_boleto": {"type": "boolean"}, "motivo": _CB_S}},
    "cob_propor_cancelar": {
        "fn": _cb_t_propor_cancelar, "rotulo": "Propôs cancelar um título",
        "description": "Cria uma PROPOSTA de cancelamento de um título em aberto (e do boleto, se houver). Recusa se já "
                       "houver NFS-e emitida.",
        "props": {"titulo_id": {"type": "integer"}, "motivo": _CB_S}},
}

for _nome_cb, _spec_cb in _CB_FERRAMENTAS.items():
    _pr_registrar_ferramenta(_nome_cb, _spec_cb)

_PR_EXECUTORES_EXTRA.update({"baixar_titulo": _cb_exec_baixa, "alterar_titulo": _cb_exec_alterar,
                             "cancelar_titulo": _cb_exec_cancelar})

_ag_cb = _PREDIO_AGENTES.get("cobranca")
if _ag_cb:
    _ag_cb.update(
        atribuicoes="Identifica inadimplentes, propõe e-mails de cobrança no tom certo e, quando pedido, dá baixa, altera "
                    "(prorroga, renegocia, reemite boleto) e cancela títulos (com aprovação).",
        ferramentas=list(dict.fromkeys(_ag_cb["ferramentas"] + ["cob_titulos", "cob_propor_baixa", "cob_propor_alterar",
                                                                "cob_propor_cancelar", "cp_cadastros"])))
    _PR_INSTRUCOES["cobranca"] = (_PR_INSTRUCOES.get("cobranca", "") + "\n\n"
        "TÍTULOS (só quando o sócio pedir)\n"
        "- Localize o título com cob_titulos e use o titulo_id; se houver mais de um candidato, mostre-os e confirme qual.\n"
        "- Baixa (cob_propor_baixa): data, valor, forma e conta informados pelo sócio ou pelo comprovante anexo (leia o "
        "comprovante). Valor menor: pergunte se é desconto (quita) ou parcial (informe o vencimento do saldo). Valor maior: "
        "juros/multa.\n"
        "- Prorrogação ou renegociação (cob_propor_alterar): novo vencimento e/ou valor, com o motivo. Se o título tem "
        "boleto, use reemitir_boleto = true. Para dividir em parcelas, dê baixa parcial com saldo ou altere e proponha os "
        "títulos novos que faltarem, explicando o plano.\n"
        "- Cancelamento (cob_propor_cancelar): só com o motivo; títulos com NFS-e emitida exigem cancelar a NF antes.\n"
        "Nunca proponha baixa, alteração ou cancelamento sem o pedido do sócio.")

# títulos com id na inadimplência, para a Cobrança agir direto
_cb_inad_orig = _pr_t_inadimplencia


def _pr_t_inadimplencia(s, cid):  # noqa: F811
    r = _cb_inad_orig(s, cid)
    E = OfficeFinancialEntry
    nomes = _pr_clientes(s, cid)
    ids = {}
    for e in s.exec(_sel_pr(E.id, E.client_id, E.description, E.due_date).where(
            E.company_id == cid, E.entry_kind == "receber", E.status == "aberto")).all():
        ids.setdefault((nomes.get(e.client_id, "Sem cliente vinculado"), e.description, _pr_fmt_data(_pr_data(e.due_date))), e.id)
    for c in r.get("por_cliente", []):
        for it in c.get("itens", []):
            it["titulo_id"] = ids.get((c["cliente"], it["descricao"], it["vencimento"]))
    return r


if "fin_inadimplencia" in _PR_TOOLS:
    _PR_TOOLS["fin_inadimplencia"]["fn"] = _pr_t_inadimplencia

print("[predio_cobranca] Cobrança com baixa, alteração e cancelamento de títulos carregada.")

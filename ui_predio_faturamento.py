# ============================================================================
# ui_predio_faturamento.py — 9º andar: o Faturamento trabalha como uma pessoa do faturamento
# ============================================================================
# Exec'd no namespace do app.py, DEPOIS de ui_predio.py, ui_financeiro_contratos.py,
# ui_nfse.py e ui_predio_juridico.py.
#
# O agente Faturamento passa a:
#   - emitir boletos (Mercado Pago) e NFS-e (emissor nacional) das cobranças do mês,
#     com envio ao cliente — tudo numa proposta por competência, com aprovação
#   - cadastrar contratos novos (jur_propor_contrato), alterar contratos (valor,
#     vencimento, término, e-mail, documento...) e pausar, encerrar ou reativar
#
# Toda ação passa pela aprovação de um admin. A emissão é idempotente: o que já saiu
# (boleto ou NF) nunca é emitido de novo, então "Tentar de novo" só refaz o que falhou.
# ============================================================================

import asyncio as _aio_ft
import re as _re_ft

_FT_MAX_ITENS = 25
_FT_DOCS = {"boleto_e_nfse": ("boleto", "nfse"), "nfse": ("nfse",), "boleto": ("boleto",)}


def _ft_digitos(v) -> str:
    return "".join(ch for ch in str(v or "") if ch.isdigit())


def _ft_brl_cents(cents) -> str:
    return _cm_brl((cents or 0) / 100)


def _ft_cadastro(s, contrato) -> dict:
    """O que o cadastro tem (ou não) para emitir boleto e NF deste contrato."""
    cl = s.get(Client, contrato.client_id) if contrato.client_id else None
    doc = _ft_digitos((cl.cnpj if cl else "") or contrato.documento_cliente)
    email_boleto = ((cl.email if cl else "") or contrato.email_cliente or "").strip()
    email_nf = (contrato.email_cliente or "").strip()
    falta_boleto = []
    if not email_boleto:
        falta_boleto.append("e-mail")
    if len(doc) not in (11, 14):
        falta_boleto.append("CNPJ/CPF")
    if not cl or not (cl.zip_code or "").strip() or not (cl.city or "").strip() or not (cl.state or "").strip():
        falta_boleto.append("CEP, cidade e UF no cadastro do cliente")
    falta_nf = [] if len(doc) in (11, 14) else ["CNPJ/CPF"]
    return {"documento_ok": len(doc) in (11, 14), "email_boleto": email_boleto, "email_nf": email_nf,
            "falta_boleto": falta_boleto, "falta_nf": falta_nf}


def _ft_contrato(s, cid, contrato_id):
    k = s.get(ContratoCliente, int(contrato_id or 0))
    return k if k and k.company_id == cid else None


# ── Contratos ─────────────────────────────────────────────────────────────────

def _ft_t_contratos(s, cid, status, cliente):
    q = _sel_pr(ContratoCliente).where(ContratoCliente.company_id == cid)
    if status and status != "todos":
        q = q.where(ContratoCliente.status == status)
    if (cliente or "").strip():
        c, cands = _pr_resolver_cliente(s, cid, cliente)
        if not c:
            return _pr_nao_achei(cliente, cands)
        q = q.where(ContratoCliente.client_id == c.id)
    nomes = _pr_clientes(s, cid)
    out = []
    for k in s.exec(q.order_by(ContratoCliente.status, ContratoCliente.nome_cliente)).all()[:80]:
        cad = _ft_cadastro(s, k)
        out.append({"contrato_id": k.id, "cliente": nomes.get(k.client_id, k.nome_cliente), "contrato": k.nome_contrato,
                    "servicos": (k.servicos or "")[:160],
                    "valor_mensal": round((k.valor_cents or 0) / 100, 2), "dia_vencimento": k.dia_vencimento,
                    "inicio": _pr_fmt_data(_pr_data(k.data_inicio)), "fim": _pr_fmt_data(_pr_data(k.data_fim)),
                    "status": k.status, "email_cobranca": cad["email_boleto"], "email_da_nf": cad["email_nf"],
                    "falta_para_boleto": cad["falta_boleto"], "falta_para_nf": cad["falta_nf"]})
    return {"contratos": out, "total": len(out),
            "observacao": "A NF é enviada ao e-mail do contrato; o boleto ao e-mail do cliente (ou do contrato)."}


def _ft_t_propor_alterar(s, cid, contrato_id, nome_contrato, servicos, valor_mensal, dia_vencimento, data_fim,
                         email_cobranca, documento, observacao, motivo):
    k = _ft_contrato(s, cid, contrato_id)
    if not k:
        return {"ok": False, "erro": "Contrato não encontrado (use contrato_id de fat_contratos)."}
    mud = {}
    if (nome_contrato or "").strip() and nome_contrato.strip() != k.nome_contrato:
        mud["nome_contrato"] = nome_contrato.strip()[:200]
    if (servicos or "").strip() and servicos.strip() != k.servicos:
        mud["servicos"] = servicos.strip()[:500]
    if float(valor_mensal or 0) > 0 and int(round(float(valor_mensal) * 100)) != k.valor_cents:
        mud["valor_cents"] = int(round(float(valor_mensal) * 100))
    if int(dia_vencimento or 0):
        if not 1 <= int(dia_vencimento) <= 28:
            return {"ok": False, "erro": "Dia de vencimento entre 1 e 28."}
        if int(dia_vencimento) != k.dia_vencimento:
            mud["dia_vencimento"] = int(dia_vencimento)
    df = (data_fim or "").strip()
    if df:
        if df.lower() in ("remover", "sem fim", "indeterminado"):
            if k.data_fim:
                mud["data_fim"] = ""
        else:
            d = _pr_data(df)
            ini = _pr_data(k.data_inicio)
            if not d or (ini and d <= ini):
                return {"ok": False, "erro": "Término inválido: DD/MM/AAAA depois do início (ou 'remover')."}
            if d.isoformat() != k.data_fim:
                mud["data_fim"] = d.isoformat()
    if (email_cobranca or "").strip():
        e = email_cobranca.strip()
        if not _re_ft.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", e):
            return {"ok": False, "erro": "E-mail inválido."}
        if e != k.email_cliente:
            mud["email_cliente"] = e[:200]
    if (documento or "").strip():
        d = _ft_digitos(documento)
        if len(d) not in (11, 14):
            return {"ok": False, "erro": "CNPJ (14 dígitos) ou CPF (11)."}
        if d != k.documento_cliente:
            mud["documento_cliente"] = d
    if (observacao or "").strip() and observacao.strip() != k.observacao:
        mud["observacao"] = observacao.strip()[:500]
    if not mud:
        return {"ok": False, "erro": "Nada muda em relação ao contrato atual."}
    if len((motivo or "").strip()) < 5:
        return {"ok": False, "erro": "Informe o motivo (ex.: reajuste anual pelo IPCA, aditivo assinado)."}
    rot = {"nome_contrato": "Nome", "servicos": "Serviços", "valor_cents": "Valor mensal", "dia_vencimento": "Dia de vencimento",
           "data_fim": "Término", "email_cliente": "E-mail do contrato", "documento_cliente": "CNPJ/CPF", "observacao": "Observação"}

    def fmt(campo, v):
        if campo == "valor_cents":
            return _ft_brl_cents(v)
        if campo == "data_fim":
            return _pr_fmt_data(_pr_data(v)) or "sem término"
        return str(v) if v not in ("", None) else "—"
    linhas = [f"• {rot[c]}: {fmt(c, getattr(k, c))} → {fmt(c, v)}" for c, v in mud.items()]
    abertas = s.exec(_sel_pr(CobrancaMensal).where(CobrancaMensal.contrato_id == k.id,
                                                   CobrancaMensal.status.in_(["pendente", "vencido"]))).all()
    emitidas = [c.competencia for c in abertas if c.boleto_url or c.nf_numero or c.nf_chave]
    if {"valor_cents", "dia_vencimento", "nome_contrato"} & set(mud):
        livres = len(abertas) - len(emitidas)
        linhas.append(f"\nCobranças em aberto atualizadas junto: {livres}.")
        if emitidas:
            linhas.append(f"Já têm boleto ou NF e NÃO mudam (cancele e reemita se preciso): {', '.join(sorted(emitidas))}.")
    acao = _pr_registrar_proposta(
        s, cid, tipo="alterar_contrato", client_id=k.client_id, titulo=f"Alterar contrato: {k.nome_cliente} — {k.nome_contrato}",
        destinatario=f"Financeiro · contrato #{k.id}", assunto=k.nome_contrato,
        corpo=f"Motivo: {motivo.strip()[:500]}\n\n" + "\n".join(linhas),
        payload_json=_json_pr.dumps({"contrato_id": k.id, "mudancas": mud}, ensure_ascii=False))
    return {"ok": True, "proposta_id": acao.id, "mudancas": list(mud), "cobrancas_ja_emitidas_que_nao_mudam": emitidas}


def _ft_exec_alterar(s, acao) -> str:
    p = _json_pr.loads(acao.payload_json or "{}")
    k = _ft_contrato(s, acao.company_id, p["contrato_id"])
    if not k:
        raise _PrErro("Contrato não encontrado.")
    for campo, v in p["mudancas"].items():
        setattr(k, campo, v)
    k.updated_at = _dt_pr.utcnow()
    s.add(k)
    s.commit()
    atualizadas, mantidas = 0, []
    if {"valor_cents", "dia_vencimento", "nome_contrato"} & set(p["mudancas"]):
        for c in s.exec(_sel_pr(CobrancaMensal).where(CobrancaMensal.contrato_id == k.id,
                                                      CobrancaMensal.status.in_(["pendente", "vencido"]))).all():
            if c.boleto_url or c.nf_numero or c.nf_chave:
                mantidas.append(c.competencia)
                continue
            c.valor_cents, c.nome_contrato, c.nome_cliente = k.valor_cents, k.nome_contrato, k.nome_cliente
            c.data_vencimento = _ct_vencimento(k, c.competencia)
            c.updated_at = _dt_pr.utcnow()
            s.add(c)
            s.commit()
            _ct_sync_entry(s, c, user_id=acao.decidido_por_user_id or 1)
            atualizadas += 1
    msg = f"Contrato #{k.id} atualizado."
    if atualizadas:
        msg += f" {atualizadas} cobrança(s) em aberto acompanharam."
    if mantidas:
        msg += f" Com boleto/NF já emitidos, ficaram como estavam: {', '.join(sorted(mantidas))}."
    return msg


def _ft_meses_sem_cobranca(s, k, ate: str) -> list:
    inicio = (k.data_inicio or ate)[:7]
    fim = ate if not (k.data_fim and k.data_fim[:7] < ate) else k.data_fim[:7]
    if inicio > fim:
        return []
    existentes = set(s.exec(_sel_pr(CobrancaMensal.competencia).where(CobrancaMensal.contrato_id == k.id)).all())
    return [m for m in _ct_meses_entre(inicio, fim) if m not in existentes]


def _ft_t_propor_status(s, cid, contrato_id, acao, data_fim, motivo):
    k = _ft_contrato(s, cid, contrato_id)
    if not k:
        return {"ok": False, "erro": "Contrato não encontrado (use contrato_id de fat_contratos)."}
    if len((motivo or "").strip()) < 5:
        return {"ok": False, "erro": "Informe o motivo."}
    hoje = _pr_hoje()
    payload = {"contrato_id": k.id, "acao": acao}
    avisos = []
    if acao == "pausar":
        if k.status != "ativo":
            return {"ok": False, "erro": f"O contrato está {k.status}: só um contrato ativo pode ser pausado."}
        descricao = "Pausar: deixa de gerar cobranças até ser reativado. Cobranças já geradas continuam."
    elif acao == "encerrar":
        if k.status == "encerrado":
            return {"ok": False, "erro": "O contrato já está encerrado."}
        fim = _pr_data(data_fim) if (data_fim or "").strip() else hoje
        if not fim:
            return {"ok": False, "erro": "Data de término inválida (DD/MM/AAAA)."}
        payload["data_fim"] = fim.isoformat()
        depois = [c for c in s.exec(_sel_pr(CobrancaMensal).where(CobrancaMensal.contrato_id == k.id,
                                                                  CobrancaMensal.status.in_(["pendente", "vencido"]))).all()
                  if c.competencia > fim.isoformat()[:7]]
        canceladas = [c.competencia for c in depois if not (c.boleto_url or c.nf_numero or c.nf_chave)]
        manuais = [c.competencia for c in depois if c.boleto_url or c.nf_numero or c.nf_chave]
        descricao = f"Encerrar em {_pr_fmt_data(fim)}: para de gerar cobranças depois dessa data."
        if canceladas:
            avisos.append(f"Cobranças depois do término canceladas junto: {', '.join(sorted(canceladas))}.")
        if manuais:
            avisos.append(f"Já têm boleto/NF e precisam ser canceladas na tela de Cobranças: {', '.join(sorted(manuais))}.")
    elif acao == "reativar":
        if k.status != "pausado":
            return {"ok": False, "erro": "Só um contrato pausado pode ser reativado. Contrato encerrado: cadastre um novo "
                                         "(jur_propor_contrato) com a nova data de início."}
        falt = _ft_meses_sem_cobranca(s, k, _pr_competencia(""))
        descricao = "Reativar: volta a gerar cobranças."
        if falt:
            avisos.append(f"Atenção: na próxima geração, os meses sem cobrança também serão cobrados: {', '.join(falt)}. "
                          "Se o período pausado não deve ser cobrado, encerre este contrato e cadastre um novo.")
    else:
        return {"ok": False, "erro": "Ação: pausar, encerrar ou reativar."}
    a = _pr_registrar_proposta(
        s, cid, tipo="status_contrato", client_id=k.client_id,
        titulo=f"{acao.capitalize()} contrato: {k.nome_cliente} — {k.nome_contrato}",
        destinatario=f"Financeiro · contrato #{k.id} ({_ft_brl_cents(k.valor_cents)}/mês)", assunto=k.nome_contrato,
        corpo=f"Motivo: {motivo.strip()[:500]}\n\n{descricao}" + ("\n" + "\n".join(avisos) if avisos else ""),
        payload_json=_json_pr.dumps(payload))
    return {"ok": True, "proposta_id": a.id, "avisos": avisos}


def _ft_exec_status(s, acao) -> str:
    p = _json_pr.loads(acao.payload_json or "{}")
    k = _ft_contrato(s, acao.company_id, p["contrato_id"])
    if not k:
        raise _PrErro("Contrato não encontrado.")
    if p["acao"] == "pausar":
        k.status = "pausado"
        msg = f"Contrato #{k.id} pausado."
    elif p["acao"] == "reativar":
        k.status = "ativo"
        msg = f"Contrato #{k.id} reativado."
    else:
        k.status, k.data_fim = "encerrado", p["data_fim"]
        canceladas = 0
        for c in s.exec(_sel_pr(CobrancaMensal).where(CobrancaMensal.contrato_id == k.id,
                                                      CobrancaMensal.status.in_(["pendente", "vencido"]))).all():
            if c.competencia > p["data_fim"][:7] and not (c.boleto_url or c.nf_numero or c.nf_chave):
                c.status, c.updated_at = "cancelado", _dt_pr.utcnow()
                s.add(c)
                s.commit()
                _ct_sync_entry(s, c, user_id=acao.decidido_por_user_id or 1)
                canceladas += 1
        msg = f"Contrato #{k.id} encerrado em {_pr_fmt_data(_pr_data(p['data_fim']))}." + (
            f" {canceladas} cobrança(s) posteriores canceladas." if canceladas else "")
    k.updated_at = _dt_pr.utcnow()
    s.add(k)
    s.commit()
    return msg


# ── Emissão de boletos e NFS-e ───────────────────────────────────────────────

def _ft_t_propor_emissao(s, cid, competencia, documentos, contrato_ids):
    comp = _pr_competencia(competencia)
    docs = _FT_DOCS.get(documentos)
    if not docs:
        return {"ok": False, "erro": "documentos: boleto_e_nfse, nfse ou boleto."}
    if "nfse" in docs and "_nf_emitir_cobranca" not in globals():
        return {"ok": False, "erro": "Emissão de NFS-e indisponível neste servidor (módulo de NFS-e não carregado)."}
    pend = s.exec(_sel_pr(PredioAcao).where(PredioAcao.company_id == cid, PredioAcao.tipo == "emitir_faturamento",
                                            PredioAcao.status == "pendente")).all()
    for a in pend:
        if _json_pr.loads(a.payload_json or "{}").get("competencia") == comp:
            return {"ok": False, "erro": f"Já existe uma proposta de emissão de {comp} aguardando aprovação (#{a.id})."}
    ids = {int(x) for x in (contrato_ids or []) if str(x).strip().isdigit()}
    contratos = s.exec(_sel_pr(ContratoCliente).where(ContratoCliente.company_id == cid, ContratoCliente.status == "ativo")).all()
    nomes = _pr_clientes(s, cid)
    itens, fora, a_gerar = [], [], 0
    for k in contratos:
        if ids and k.id not in ids:
            continue
        inicio = (k.data_inicio or comp)[:7]
        if inicio > comp or (k.data_fim and k.data_fim[:7] < comp):
            if ids:
                fora.append({"cliente": k.nome_cliente, "motivo": f"contrato não vigente em {comp}"})
            continue
        nome = nomes.get(k.client_id, k.nome_cliente)
        cob = s.exec(_sel_pr(CobrancaMensal).where(CobrancaMensal.contrato_id == k.id, CobrancaMensal.competencia == comp)).first()
        if cob and cob.status == "cancelado":
            fora.append({"cliente": nome, "motivo": "cobrança cancelada"})
            continue
        valor = cob.valor_cents if cob else k.valor_cents
        if (valor or 0) <= 0:
            fora.append({"cliente": nome, "motivo": "valor zero"})
            continue
        cad = _ft_cadastro(s, k)
        quer_nf = "nfse" in docs and not (cob and (cob.nf_numero or cob.nf_chave))
        quer_bol = "boleto" in docs and not (cob and cob.boleto_url) and not (cob and cob.status == "pago")
        notas = []
        if quer_nf and cad["falta_nf"]:
            quer_nf = False
            notas.append("NF: falta " + ", ".join(cad["falta_nf"]))
        if quer_bol and cad["falta_boleto"]:
            quer_bol = False
            notas.append("boleto: falta " + ", ".join(cad["falta_boleto"]))
        if not quer_nf and not quer_bol:
            fora.append({"cliente": nome, "motivo": "; ".join(notas) or "já emitido (ou pago)"})
            continue
        if quer_nf and not cad["email_nf"]:
            notas.append("NF sai sem envio por e-mail (contrato sem e-mail)")
        if not cob:
            a_gerar += 1
        itens.append({"contrato_id": k.id, "cliente": nome, "contrato": k.nome_contrato, "valor_cents": valor,
                      "vencimento": _pr_fmt_data(_pr_data(cob.data_vencimento if cob else _ct_vencimento(k, comp))),
                      "nfse": quer_nf, "boleto": quer_bol, "email": cad["email_boleto"] if quer_bol else cad["email_nf"],
                      "notas": notas})
    if not itens:
        return {"ok": False, "erro": f"Nada a emitir em {comp}.", "nao_incluidos": fora}
    if len(itens) > _FT_MAX_ITENS:
        return {"ok": False, "erro": f"{len(itens)} cobranças: proponha em lotes de até {_FT_MAX_ITENS} (use contrato_ids)."}
    linhas = [f"• {i['cliente']} — {i['contrato']} · {_ft_brl_cents(i['valor_cents'])} · venc. {i['vencimento']} · "
              f"{' + '.join(x for x, q in (('NFS-e', i['nfse']), ('boleto', i['boleto'])) if q)} → {i['email'] or 'sem e-mail'}"
              + (f" ({'; '.join(i['notas'])})" if i["notas"] else "") for i in itens]
    total = sum(i["valor_cents"] for i in itens)
    corpo = (f"Competência {comp} · {len(itens)} cobrança(s) · {_ft_brl_cents(total)}\n"
             + (f"Antes, gera as cobranças que faltam no sistema ({a_gerar} deste mês, e meses anteriores em aberto).\n" if a_gerar else "")
             + "Cada documento é enviado ao cliente por e-mail, com cópia ao escritório.\n\n" + "\n".join(linhas)
             + ("\n\nFora deste lote:\n" + "\n".join(f"• {f['cliente']}: {f['motivo']}" for f in fora) if fora else ""))
    a = _pr_registrar_proposta(
        s, cid, tipo="emitir_faturamento",
        titulo=f"Faturar {comp}: {sum(i['nfse'] for i in itens)} NFS-e e {sum(i['boleto'] for i in itens)} boleto(s)",
        destinatario="Clientes (e-mails do cadastro) · NFS-e pelo emissor nacional · boleto pelo Mercado Pago",
        assunto=f"Faturamento {comp}", corpo=corpo,
        payload_json=_json_pr.dumps({"competencia": comp, "itens": [{k_: i[k_] for k_ in ("contrato_id", "nfse", "boleto")}
                                                                    for i in itens]}))
    return {"ok": True, "proposta_id": a.id, "status": "aguardando aprovação", "itens": len(itens), "total": total / 100,
            "nao_incluidos": fora}


def _ft_emitir_item(s, item, comp) -> str:
    """Emite o que falta de um item. Retorna o resumo; levanta exceção com o que falhou (o que já saiu fica gravado)."""
    k = s.get(ContratoCliente, item["contrato_id"])
    cob = s.exec(_sel_pr(CobrancaMensal).where(CobrancaMensal.contrato_id == item["contrato_id"],
                                               CobrancaMensal.competencia == comp)).first()
    if not k or not cob:
        raise ValueError("cobrança não encontrada")
    if cob.status == "cancelado":
        return "cobrança cancelada, nada emitido"
    feito, erros = [], []
    if item.get("nfse"):
        if cob.nf_numero or cob.nf_chave:
            feito.append(f"NF {cob.nf_numero or 'já emitida'}")
        else:
            try:
                nr = _aio_ft.run(_nf_emitir_cobranca(s, cob, k))
                feito.append(f"NF {nr}")
            except Exception as e:
                s.rollback()
                erros.append(f"NF: {str(e)[:120]}")
    if item.get("boleto") and cob.status != "pago":
        if cob.boleto_url:
            feito.append("boleto já gerado")
        else:
            try:
                dados = _ct_mp_gerar_boleto(cob, k, s)
                cob.mp_payment_id, cob.boleto_url, cob.boleto_codigo = dados["mp_payment_id"], dados["boleto_url"], dados["boleto_codigo"]
                cob.updated_at = _dt_pr.utcnow()
                s.add(cob)
                s.commit()
                feito.append("boleto")
                try:
                    _ct_enviar_email_boleto(cob, k, s)
                except Exception as e_m:
                    feito.append(f"(e-mail do boleto falhou: {str(e_m)[:60]})")
            except Exception as e:
                s.rollback()
                erros.append(f"boleto: {str(e)[:120]}")
    if erros:
        raise ValueError((f"saiu {', '.join(feito)}; " if feito else "") + "falhou " + "; ".join(erros))
    return ", ".join(feito)


def _ft_exec_emissao(s, acao) -> str:
    p = _json_pr.loads(acao.payload_json or "{}")
    comp = p["competencia"]
    for item in p["itens"]:
        if not s.exec(_sel_pr(CobrancaMensal.id).where(CobrancaMensal.contrato_id == item["contrato_id"],
                                                       CobrancaMensal.competencia == comp)).first():
            _ct_gerar_cobrancas_mes(s, acao.company_id, comp)
            break
    nomes = {k.id: k.nome_cliente for k in s.exec(_sel_pr(ContratoCliente).where(
        ContratoCliente.id.in_([i["contrato_id"] for i in p["itens"]]))).all()}
    ok, falhas = [], []
    for item in p["itens"]:
        nome = nomes.get(item["contrato_id"], f"contrato #{item['contrato_id']}")
        try:
            ok.append(f"{nome}: {_ft_emitir_item(s, item, comp)}")
        except Exception as e:
            falhas.append(f"{nome}: {str(e)[:160]}")
    if falhas:
        # status "Falhou": "Tentar de novo" refaz só o que falta (o que já saiu não é emitido de novo)
        raise _PrErro(f"{len(ok)} de {len(p['itens'])} ok. Falharam — " + " | ".join(falhas))
    return f"Faturamento {comp}: " + " | ".join(ok)


# ── Registro ──────────────────────────────────────────────────────────────────

_FT_S = {"type": "string"}
_FT_FERRAMENTAS = {
    "fat_contratos": {
        "fn": _ft_t_contratos, "rotulo": "Consultou os contratos",
        "description": "Contratos do financeiro com contrato_id, valor, vencimento, vigência, status, e-mails de cobrança e "
                       "o que falta no cadastro para emitir boleto e NF.",
        "props": {"status": {"type": "string", "enum": ["todos", "ativo", "pausado", "encerrado"]},
                  "cliente": {"type": "string", "description": "Nome do cliente ou vazio para todos."}}},
    "fat_propor_emissao": {
        "fn": _ft_t_propor_emissao, "rotulo": "Propôs emitir boletos e NFS-e",
        "description": "Cria UMA proposta com a emissão da competência: NFS-e (emissor nacional) e/ou boleto (Mercado Pago) "
                       "de cada contrato, com envio ao cliente. Gera antes as cobranças que faltarem. Pula o que já foi "
                       "emitido e explica o que ficou de fora (cadastro incompleto, valor zero, cancelada).",
        "props": {"competencia": {"type": "string", "description": "AAAA-MM ou MM/AAAA (padrão: mês atual)."},
                  "documentos": {"type": "string", "enum": ["boleto_e_nfse", "nfse", "boleto"]},
                  "contrato_ids": {"type": "array", "items": {"type": "integer"}, "description": "Vazio = todos os contratos ativos."}}},
    "fat_propor_alterar_contrato": {
        "fn": _ft_t_propor_alterar, "rotulo": "Propôs alterar um contrato",
        "description": "Cria uma PROPOSTA de alteração de contrato (reajuste, vencimento, término, e-mail, documento...). "
                       "Campos vazios ou 0 ficam como estão. Cobranças em aberto sem boleto/NF acompanham o novo valor.",
        "props": {"contrato_id": {"type": "integer"}, "nome_contrato": _FT_S, "servicos": _FT_S,
                  "valor_mensal": {"type": "number", "description": "Novo valor em reais ou 0."},
                  "dia_vencimento": {"type": "integer", "description": "1 a 28 ou 0."},
                  "data_fim": {"type": "string", "description": "DD/MM/AAAA, 'remover' ou vazio."},
                  "email_cobranca": _FT_S, "documento": {"type": "string", "description": "CNPJ/CPF ou vazio."},
                  "observacao": _FT_S, "motivo": _FT_S}},
    "fat_propor_status_contrato": {
        "fn": _ft_t_propor_status, "rotulo": "Propôs mudar o status de um contrato",
        "description": "Cria uma PROPOSTA para pausar (para de gerar cobranças), encerrar (com data de término; cancela as "
                       "cobranças posteriores ainda não emitidas) ou reativar um contrato pausado.",
        "props": {"contrato_id": {"type": "integer"}, "acao": {"type": "string", "enum": ["pausar", "encerrar", "reativar"]},
                  "data_fim": {"type": "string", "description": "Encerrar: DD/MM/AAAA (vazio = hoje)."}, "motivo": _FT_S}},
}

for _nome_ft, _spec_ft in _FT_FERRAMENTAS.items():
    _pr_registrar_ferramenta(_nome_ft, _spec_ft)

_PR_EXECUTORES_EXTRA.update({"emitir_faturamento": _ft_exec_emissao, "alterar_contrato": _ft_exec_alterar,
                             "status_contrato": _ft_exec_status})

_ag_ft = _PREDIO_AGENTES.get("faturamento")
if _ag_ft:
    _ag_ft.update(
        atribuicoes="Fatura o mês como uma pessoa do faturamento: gera as cobranças, emite boletos e NFS-e e envia aos "
                    "clientes; cadastra, altera, pausa e encerra contratos (tudo com aprovação).",
        ferramentas=["fat_competencia", "fat_contratos", "fat_propor_geracao", "fat_propor_emissao",
                     "fat_propor_alterar_contrato", "fat_propor_status_contrato", "jur_propor_contrato",
                     "fin_contratos", "fin_receita_por_cliente", "fin_inadimplencia"])
    _PR_INSTRUCOES["faturamento"] = (
        "Você é a pessoa do faturamento do escritório. Trabalhe como ela: confira, prepare e deixe tudo pronto para o "
        "sócio aprovar com um clique.\n"
        "FATURAR O MÊS (padrão: competência atual)\n"
        "- fat_competencia mostra o que falta gerar, o que está sem NFS-e e sem boleto. Para faturar, use "
        "fat_propor_emissao (documentos 'boleto_e_nfse', salvo pedido diferente): ela gera as cobranças que faltam e "
        "emite tudo numa proposta só. Não use fat_propor_geracao junto: só quando o sócio quiser gerar as cobranças "
        "sem emitir nada.\n"
        "- Leia o que ficou de fora da proposta e diga exatamente o que corrigir (ex.: 'falta CEP no cadastro da GSW'). "
        "Se for e-mail ou documento do contrato, proponha a correção com fat_propor_alterar_contrato.\n"
        "- Cliente pago no mês não precisa de boleto. Valores diferentes do contrato: aponte antes de emitir.\n"
        "- Depois da aprovação, se a proposta voltar como 'Falhou', explique cada erro: o botão Tentar de novo refaz só o "
        "que falhou.\n"
        "CONTRATOS\n"
        "- Novo contrato (assinado): jur_propor_contrato. Alteração (reajuste, vencimento, término, e-mail, CNPJ): "
        "fat_propor_alterar_contrato com o motivo; para reajuste por índice, calcule e mostre a conta. Pausar, encerrar "
        "ou reativar: fat_propor_status_contrato.\n"
        "- Sempre localize o contrato com fat_contratos e use o contrato_id; se houver mais de um contrato do cliente, "
        "confirme qual.\n"
        "Nada é emitido, enviado ou alterado sem a aprovação de um admin; nunca diga que algo foi feito antes disso.")

print("[predio_faturamento] Faturamento com boleto, NFS-e e contratos carregado.")

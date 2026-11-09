# ============================================================================
# ui_predio_comercial.py — 2º andar do prédio: Comercial
# ============================================================================
# Exec'd no namespace do app.py, DEPOIS de ui_predio.py (usa os helpers _pr_*).
#
# AGENTES
#   prospeccao      — leads do site, do trial do Augur e do WhatsApp; listas do
#                     radar (coladas ou anexadas); pesquisa a empresa; propõe o
#                     negócio no CRM
#   propostas       — proposta comercial em PDF no padrão M. Capital, com base
#                     no diagnóstico, nas reuniões e nos honorários já praticados;
#                     registra no CRM (só admin: vê valores de contratos)
#   sucesso_cliente — renovações, sinais de risco de cancelamento e oportunidades
#                     de venda adicional
#
# Toda ação (criar negócio, registrar proposta, tarefa) passa por aprovação.
# ============================================================================

import io as _io_cm
import re as _re_cm
from xml.sax.saxutils import escape as _xesc_cm

_CM_EMISSOR = {
    "marca": "M. CAPITAL", "linha": "Advisory & Structured Finance", "nome": "M. Capital",
    "cidade": "Brusque, SC", "email": "contato@maffezzollicapital.com.br", "fone": "(47) 99135-9091",
    "signatario": "Rafael Maffezzolli — M. Capital",
}
_CM_MESES = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro", "outubro",
             "novembro", "dezembro"]


# ── PDF da proposta (padrão M. Capital) ───────────────────────────────────────

def _cm_txt(texto) -> str:
    """Texto seguro para Paragraph do reportlab; **trecho** vira negrito."""
    t = _xesc_cm(str(texto or "").strip())
    t = _re_cm.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", t)
    return t.replace("\n", "<br/>")


def _cm_pdf_proposta(p: dict) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER, TA_RIGHT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.pdfgen import canvas as _canvas
    from reportlab.platypus import (KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table,
                                    TableStyle)

    LAR = colors.HexColor("#E8772E")
    LAR_CLARO = colors.HexColor("#FFF6EE")
    TINTA = colors.HexColor("#1F2329")
    CINZA = colors.HexColor("#6B7280")
    CINZA_CLARO = colors.HexColor("#F6F7F9")
    LINHA = colors.HexColor("#E3E6EA")
    NAVY = colors.HexColor("#1E2235")
    ASSOC = colors.HexColor("#6B7280")
    VERM, VERM_CLARO = colors.HexColor("#C0392B"), colors.HexColor("#FDF1F0")
    VERDE, VERDE_CLARO = colors.HexColor("#1E8449"), colors.HexColor("#EEF8F1")

    def st(nome, **kw):
        base = dict(fontName="Helvetica", fontSize=10, leading=13.5, textColor=TINTA)
        base.update(kw)
        return ParagraphStyle(nome, **base)

    S = {
        "corpo": st("corpo"),
        "cinza": st("cinza", textColor=CINZA, fontSize=9.5, leading=12.5),
        "cinza_c": st("cinza_c", textColor=CINZA, fontSize=9.5, leading=12.5, alignment=TA_CENTER),
        "negrito": st("negrito", fontName="Helvetica-Bold", fontSize=9.5, leading=12.5),
        "neg_c": st("neg_c", fontName="Helvetica-Bold", fontSize=9.5, leading=12.5, alignment=TA_CENTER),
        "h1": st("h1", fontName="Helvetica-Bold", fontSize=17, leading=21, textColor=LAR),
        "capa_t": st("capa_t", fontName="Helvetica-Bold", fontSize=25, leading=30, textColor=LAR, alignment=TA_CENTER),
        "capa_s": st("capa_s", fontName="Helvetica-Bold", fontSize=12.5, leading=16, alignment=TA_CENTER),
        "capa_c": st("capa_c", fontName="Helvetica-Oblique", fontSize=12, leading=15, textColor=CINZA, alignment=TA_CENTER),
        "rotulo": st("rotulo", fontName="Helvetica-Bold", fontSize=8.5, leading=11, textColor=LAR),
        "grande": st("grande", fontName="Helvetica-Bold", fontSize=12, leading=15),
        "ital_c": st("ital_c", fontName="Helvetica-Oblique", fontSize=9, textColor=CINZA, alignment=TA_CENTER),
        "cab": st("cab", fontName="Helvetica-Bold", fontSize=9.5, leading=12, textColor=colors.white, alignment=TA_CENTER),
        "cab_e": st("cab_e", fontName="Helvetica-Bold", fontSize=9, leading=12, textColor=colors.white),
        "lar_c": st("lar_c", fontName="Helvetica-Bold", fontSize=9.5, leading=12.5, textColor=LAR, alignment=TA_CENTER),
        "lar_e": st("lar_e", fontName="Helvetica-Bold", fontSize=9, leading=12, textColor=LAR),
        "preco": st("preco", fontName="Helvetica-Bold", fontSize=22, leading=26, alignment=TA_CENTER),
    }
    LARG = A4[0] - 40 * mm

    def P(texto, estilo="corpo"):
        return Paragraph(_cm_txt(texto), S[estilo])

    from reportlab.graphics.shapes import Drawing, PolyLine

    def check(texto, estilo="corpo", largura=None):
        # visto desenhado (não depende de fonte com o caractere ✓)
        d = Drawing(9, 8)
        d.add(PolyLine([1, 4, 3.5, 1.2, 8, 7], strokeColor=VERDE, strokeWidth=1.4))
        t = Table([[d, Paragraph(_cm_txt(texto), S[estilo])]], colWidths=[12, None])
        t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0),
                               ("RIGHTPADDING", (0, 0), (-1, -1), 0), ("TOPPADDING", (0, 0), (0, 0), 3),
                               ("TOPPADDING", (1, 0), (1, 0), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 2)]))
        return t

    def bullet(texto):
        return Paragraph(f"•&nbsp; {_cm_txt(texto)}", st("bul", fontSize=9.5, leading=12.5, leftIndent=9, firstLineIndent=-9))

    def secao(titulo):
        linha = Table([[""]], colWidths=[LARG], rowHeights=[2])
        linha.setStyle(TableStyle([("LINEBELOW", (0, 0), (-1, -1), 0.8, LAR)]))
        return [Paragraph(_cm_txt(titulo), S["h1"]), Spacer(1, 4), linha, Spacer(1, 10)]

    def caixa(conteudo, fundo, borda=None, larg=LARG):
        t = Table([[conteudo]], colWidths=[larg])
        estilo = [("BACKGROUND", (0, 0), (-1, -1), fundo), ("LEFTPADDING", (0, 0), (-1, -1), 9),
                  ("RIGHTPADDING", (0, 0), (-1, -1), 9), ("TOPPADDING", (0, 0), (-1, -1), 7),
                  ("BOTTOMPADDING", (0, 0), (-1, -1), 8)]
        estilo.append(("BOX", (0, 0), (-1, -1), 0.8, borda or LINHA))
        t.setStyle(TableStyle(estilo))
        return t

    def tabela(dados, larguras, estilo_extra, repetir=1):
        t = Table(dados, colWidths=larguras, repeatRows=repetir)
        t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("BOX", (0, 0), (-1, -1), 0.6, LINHA),
                               ("INNERGRID", (0, 0), (-1, -1), 0.4, LINHA), ("TOPPADDING", (0, 0), (-1, -1), 5),
                               ("BOTTOMPADDING", (0, 0), (-1, -1), 6), ("LEFTPADDING", (0, 0), (-1, -1), 7),
                               ("RIGHTPADDING", (0, 0), (-1, -1), 7)] + estilo_extra))
        return t

    cliente = p["cliente"]
    data = _pr_data(p["data_emissao"]) or _pr_hoje()
    data_ext = f"{data.day:02d} de {_CM_MESES[data.month - 1]} de {data.year}"
    E = _CM_EMISSOR
    hist = []

    # Capa
    hist += [Spacer(1, 34 * mm), P(p["titulo"].upper(), "capa_t"), Spacer(1, 6), P(p["subtitulo"], "capa_s"),
             Spacer(1, 3), P(cliente["nome"], "capa_c"), Spacer(1, 14 * mm)]
    sep = Table([[""]], colWidths=[LARG], rowHeights=[2])
    sep.setStyle(TableStyle([("LINEBELOW", (0, 0), (-1, -1), 0.8, LAR)]))
    hist += [sep, Spacer(1, 12 * mm)]
    contato = " | ".join(x for x in (cliente.get("email"), cliente.get("telefone")) if x)
    esq = [P("CLIENTE", "rotulo"), P(cliente["nome"], "grande")]
    if cliente.get("contato"):
        esq.append(P(f"Attn.: {cliente['contato']}", "cinza"))
    if contato:
        esq.append(P(contato, "cinza"))
    if cliente.get("setor"):
        esq.append(P(f"Setor: {cliente['setor']}", "cinza"))
    dir_ = [P("EMITIDO POR", "rotulo"), P(E["nome"], "grande"), P(E["linha"], "cinza"),
            P(f"{E['cidade']} · {data_ext}", "cinza")]
    capa = Table([[esq, dir_]], colWidths=[LARG / 2, LARG / 2])
    capa.setStyle(TableStyle([("BACKGROUND", (0, 0), (0, 0), CINZA_CLARO), ("BACKGROUND", (1, 0), (1, 0), LAR_CLARO),
                              ("BOX", (0, 0), (-1, -1), 0.6, LINHA), ("INNERGRID", (0, 0), (-1, -1), 0.6, LINHA),
                              ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("TOPPADDING", (0, 0), (-1, -1), 9),
                              ("BOTTOMPADDING", (0, 0), (-1, -1), 10), ("LEFTPADDING", (0, 0), (-1, -1), 10)]))
    hist += [capa, Spacer(1, 10 * mm),
             P(f"Validade desta proposta: {int(p['validade_dias'])} dias corridos a partir da data de emissão.", "ital_c")]

    n = 0

    def proxima(titulo):
        nonlocal n
        n += 1
        return secao(f"{n}. {titulo}")

    # 1. Contexto
    hist += [PageBreak()] + proxima("Contexto e Diagnóstico Preliminar") + [P(p["contexto"]), Spacer(1, 8)]
    if p["gaps"] or p["pontos_positivos"]:
        col_g = [P("GAPS CRÍTICOS IDENTIFICADOS", "rotulo")] + [bullet(g) for g in p["gaps"]]
        col_p = [P("PONTOS POSITIVOS IDENTIFICADOS", "rotulo")] + [check(x, "cinza") for x in p["pontos_positivos"]]
        col_g[0] = Paragraph("GAPS CRÍTICOS IDENTIFICADOS", st("rv", fontName="Helvetica-Bold", fontSize=9, textColor=VERM))
        col_p[0] = Paragraph("PONTOS POSITIVOS IDENTIFICADOS", st("rg", fontName="Helvetica-Bold", fontSize=9, textColor=VERDE))
        dupla = Table([[col_g, col_p]], colWidths=[LARG / 2, LARG / 2])
        dupla.setStyle(TableStyle([("BACKGROUND", (0, 0), (0, 0), VERM_CLARO), ("BACKGROUND", (1, 0), (1, 0), VERDE_CLARO),
                                   ("LINEBEFORE", (0, 0), (0, 0), 2, VERM), ("LINEBEFORE", (1, 0), (1, 0), 2, VERDE),
                                   ("VALIGN", (0, 0), (-1, -1), "TOP"), ("TOPPADDING", (0, 0), (-1, -1), 8),
                                   ("BOTTOMPADDING", (0, 0), (-1, -1), 9), ("LEFTPADDING", (0, 0), (-1, -1), 9)]))
        hist += [dupla, Spacer(1, 10)]
    if p["contexto_estrategico"]:
        hist.append(caixa([P("CONTEXTO ESTRATÉGICO", "rotulo"), Spacer(1, 2), P(p["contexto_estrategico"])], CINZA_CLARO))

    # 2. Escopo
    hist += [PageBreak()] + proxima("Escopo dos Serviços")
    if p["escopo_intro"]:
        hist += [P(p["escopo_intro"]), Spacer(1, 8)]
    for pil in p["pilares"]:
        linhas = [[Paragraph(_cm_txt(pil["titulo"]), S["cab"]), ""]]
        for it in pil["itens"]:
            linhas.append([P(it["nome"], "negrito"), P(it["descricao"], "cinza")])
        t = tabela(linhas, [LARG * 0.3, LARG * 0.7],
                   [("SPAN", (0, 0), (-1, 0)), ("BACKGROUND", (0, 0), (-1, 0), LAR),
                    ("BACKGROUND", (0, 1), (0, -1), LAR_CLARO)])
        hist += [t, Spacer(1, 10)]

    # 3. Cronograma + 4. Metodologia
    if p["cronograma"] or p["metodologia"]:
        hist.append(PageBreak())
    if p["cronograma"]:
        hist += proxima("Cronograma Estimado")
        linhas = [[Paragraph("FASE", S["cab_e"]), Paragraph("PRAZO", S["cab"]), Paragraph("ENTREGAS", S["cab_e"])]]
        for c in p["cronograma"]:
            linhas.append([P(c["fase"], "negrito"), P(c["prazo"], "lar_c"), P(c["entregas"], "cinza")])
        hist += [tabela(linhas, [LARG * 0.34, LARG * 0.18, LARG * 0.48],
                        [("BACKGROUND", (0, 0), (-1, 0), LAR),
                         ("ROWBACKGROUNDS", (0, 1), (-1, -1), [LAR_CLARO, colors.white])]), Spacer(1, 16)]
    if p["metodologia"]:
        hist += proxima("Metodologia de Trabalho")
        linhas = [[Paragraph(f"{i:02d}", S["cab"]), P(m["etapa"].upper(), "negrito"), P(m["descricao"], "cinza")]
                  for i, m in enumerate(p["metodologia"], 1)]
        hist.append(tabela(linhas, [LARG * 0.07, LARG * 0.25, LARG * 0.68],
                           [("BACKGROUND", (0, 0), (0, -1), LAR),
                            ("ROWBACKGROUNDS", (1, 0), (-1, -1), [LAR_CLARO, CINZA_CLARO])], repetir=0))

    # 5. Modalidades
    mods = p["modalidades"]
    hist += [PageBreak()] + proxima("Modalidades de Engajamento" if len(mods) > 1 else "Investimento")
    if p["comparativo"]:
        cab = [Paragraph("ITEM", S["cab_e"])] + [Paragraph(_cm_txt(m["nome"].upper()), S["cab"]) for m in mods]
        linhas = [cab]
        for r in p["comparativo"]:
            vals = (list(r["valores"]) + [""] * len(mods))[:len(mods)]
            linhas.append([P(r["item"], "cinza")] + [P(v, "cinza_c") for v in vals])
        linhas.append([P("Honorário", "lar_e")] + [P(m["valor"], "lar_c") for m in mods])
        larg_mod = LARG * 0.6 / len(mods)
        extra = [("BACKGROUND", (0, 0), (0, 0), NAVY), ("BACKGROUND", (1, 0), (1, 0), LAR)]
        if len(mods) > 1:
            extra.append(("BACKGROUND", (2, 0), (2, 0), ASSOC))
        extra.append(("BACKGROUND", (1, 1), (1, -1), LAR_CLARO))
        hist += [tabela(linhas, [LARG * 0.4] + [larg_mod] * len(mods), extra), Spacer(1, 10)]
    if p["nota_modalidades"]:
        hist += [caixa([P("NOTA", "negrito"), Paragraph(_cm_txt(p["nota_modalidades"]),
                                                        st("nota", fontName="Helvetica-Oblique", fontSize=9.5, textColor=CINZA))],
                       CINZA_CLARO), Spacer(1, 10)]
    if p["retorno_esperado"]:
        hist.append(caixa([P("RETORNO ESPERADO SOBRE O INVESTIMENTO", "rotulo"), Spacer(1, 2), P(p["retorno_esperado"])],
                          LAR_CLARO, borda=LAR))

    # 6. Condições comerciais + 7. Por que
    hist += [PageBreak()] + proxima("Condições Comerciais")
    cards = []
    for i, m in enumerate(mods):
        cor = LAR if i == 0 else ASSOC
        cel = [Paragraph(_cm_txt(m["nome"].upper()), st(f"mn{i}", fontName="Helvetica-Bold", fontSize=9.5,
                                                        textColor=cor, alignment=TA_CENTER)),
               P(m["valor"], "preco"), P(m["detalhe_valor"], "cinza_c"), Spacer(1, 6)]
        if m.get("conduzido_por"):
            cel.append(check(m["conduzido_por"], "cinza"))
        cel += [check(d, "cinza") for d in m["destaques"]]
        cards.append(cel)
    lc = LARG / len(cards) if len(cards) > 1 else LARG * 0.6
    tc = Table([cards], colWidths=[lc] * len(cards))
    est = [("VALIGN", (0, 0), (-1, -1), "TOP"), ("TOPPADDING", (0, 0), (-1, -1), 10),
           ("BOTTOMPADDING", (0, 0), (-1, -1), 12), ("LEFTPADDING", (0, 0), (-1, -1), 12),
           ("RIGHTPADDING", (0, 0), (-1, -1), 12), ("BACKGROUND", (0, 0), (0, 0), LAR_CLARO),
           ("BOX", (0, 0), (0, 0), 0.9, LAR)]
    if len(cards) > 1:
        est += [("BACKGROUND", (1, 0), (1, 0), CINZA_CLARO), ("BOX", (1, 0), (1, 0), 0.9, ASSOC)]
    tc.setStyle(TableStyle(est))
    hist += [tc, Spacer(1, 12)]
    if p["condicoes"]:
        linhas = [[Paragraph("CONDIÇÃO", S["cab_e"]), Paragraph("DETALHE", S["cab_e"])]]
        linhas += [[P(c["condicao"].upper(), "lar_e"), P(c["detalhe"], "cinza")] for c in p["condicoes"]]
        hist += [tabela(linhas, [LARG * 0.3, LARG * 0.7],
                        [("BACKGROUND", (0, 0), (-1, 0), LAR),
                         ("ROWBACKGROUNDS", (0, 1), (-1, -1), [LAR_CLARO, colors.white])]), Spacer(1, 16)]
    if p["diferenciais"]:
        hist += proxima(f"Por Que a {E['nome']}")
        cel = [[P(d["titulo"], "negrito"), Spacer(1, 2), P(d["texto"], "cinza")] for d in p["diferenciais"]]
        if len(cel) % 2:
            cel.append("")
        grade = Table([cel[i:i + 2] for i in range(0, len(cel), 2)], colWidths=[LARG / 2, LARG / 2])
        grade.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), CINZA_CLARO), ("BOX", (0, 0), (-1, -1), 0.6, LINHA),
                                   ("INNERGRID", (0, 0), (-1, -1), 0.6, LINHA), ("VALIGN", (0, 0), (-1, -1), "TOP"),
                                   ("TOPPADDING", (0, 0), (-1, -1), 8), ("BOTTOMPADDING", (0, 0), (-1, -1), 9),
                                   ("LEFTPADDING", (0, 0), (-1, -1), 9)]))
        hist.append(grade)

    # 8. Aceite
    hist += [PageBreak()] + proxima("Aceite e Contratação") + [P(p["texto_aceite"]), Spacer(1, 10)]
    assin = []
    for i, m in enumerate(mods):
        cor = LAR if i == 0 else ASSOC
        assin.append([
            Paragraph(_cm_txt(m["nome"].upper()), st(f"an{i}", fontName="Helvetica-Bold", fontSize=10, textColor=cor,
                                                     alignment=TA_CENTER)),
            Paragraph(_cm_txt(f"{m['valor']} · {m['detalhe_valor']}"), st(f"av{i}", fontName="Helvetica-Bold", fontSize=8.5,
                                                                         textColor=cor, alignment=TA_CENTER)),
            Spacer(1, 26),
            Paragraph("_" * 38, S["cinza_c"]),
            P(cliente.get("contato") or cliente["nome"], "neg_c"), P(cliente["nome"], "cinza_c"),
            Spacer(1, 22),
            Paragraph("_" * 38, S["cinza_c"]),
            P(E["signatario"], "neg_c"), P(E["linha"], "cinza_c"), Spacer(1, 8),
            P(f"Data: _____ / _____ / {data.year}", "cinza_c"),
        ])
    la = (LARG - 8 * mm) / len(assin) if len(assin) > 1 else LARG * 0.55
    ta = Table([assin], colWidths=[la] * len(assin))
    est = [("VALIGN", (0, 0), (-1, -1), "TOP"), ("TOPPADDING", (0, 0), (-1, -1), 8),
           ("BOTTOMPADDING", (0, 0), (-1, -1), 10), ("BOX", (0, 0), (0, 0), 0.8, LAR),
           ("BACKGROUND", (0, 0), (0, 0), LAR_CLARO)]
    if len(assin) > 1:
        est += [("BOX", (1, 0), (1, 0), 0.8, ASSOC), ("BACKGROUND", (1, 0), (1, 0), CINZA_CLARO)]
    ta.setStyle(TableStyle(est))
    hist += [KeepTogether([ta]), Spacer(1, 12),
             P(f"{E['nome']} · {E['linha']} · {E['cidade']} · {E['email']} · {E['fone']}", "cinza_c")]

    class _Numerado(_canvas.Canvas):
        def __init__(self, *a, **kw):
            super().__init__(*a, **kw)
            self._paginas = []

        def showPage(self):
            self._paginas.append(dict(self.__dict__))
            self._startPage()

        def save(self):
            total = len(self._paginas)
            for estado in self._paginas:
                self.__dict__.update(estado)
                self._moldura(total)
                super().showPage()
            super().save()

        def _moldura(self, total):
            w, h = A4
            self.setFont("Helvetica-Bold", 13)
            self.setFillColor(LAR)
            self.drawString(20 * mm, h - 17 * mm, E["marca"])
            x = 20 * mm + self.stringWidth(E["marca"], "Helvetica-Bold", 13)
            self.setFont("Helvetica", 9)
            self.setFillColor(CINZA)
            self.drawString(x + 2 * mm, h - 17 * mm, f"|  {E['linha']}")
            self.setFont("Helvetica-Oblique", 9)
            self.drawRightString(w - 20 * mm, h - 16 * mm, "Proposta Comercial")
            self.setStrokeColor(LAR)
            self.setLineWidth(0.8)
            self.line(18 * mm, h - 23 * mm, w - 18 * mm, h - 23 * mm)
            self.setStrokeColor(LINHA)
            self.setLineWidth(0.5)
            self.line(18 * mm, 20 * mm, w - 18 * mm, 20 * mm)
            self.setFont("Helvetica", 8)
            self.setFillColor(CINZA)
            self.drawString(20 * mm, 15 * mm, f"{E['nome']} — {E['cidade']}  |  {E['email']}  |  {E['fone']}")
            self.drawRightString(w - 20 * mm, 15 * mm, f"Página {self._pageNumber} de {total}")

    buf = _io_cm.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=20 * mm, rightMargin=20 * mm, topMargin=30 * mm,
                            bottomMargin=26 * mm, title=f"Proposta — {cliente['nome']}", author=E["nome"])
    doc.build(hist, canvasmaker=_Numerado)
    return buf.getvalue()


def _cm_validar_proposta(p: dict) -> str:
    if not (p.get("cliente") or {}).get("nome", "").strip():
        return "Informe o nome do cliente."
    if not _pr_data(p.get("data_emissao")):
        return "Data de emissão inválida: use DD/MM/AAAA."
    if not 1 <= len(p.get("modalidades") or []) <= 2:
        return "Informe 1 ou 2 modalidades de engajamento."
    if not p.get("pilares"):
        return "Informe pelo menos um pilar de escopo com itens."
    if any(not pil.get("itens") for pil in p["pilares"]):
        return "Todo pilar precisa de pelo menos um item."
    for m in p["modalidades"]:
        if not _re_cm.search(r"\d", m.get("valor") or ""):
            return f"Modalidade {m.get('nome')}: informe o valor."
    if len((p.get("contexto") or "").strip()) < 40:
        return "Escreva o contexto e diagnóstico preliminar."
    return ""


def _cm_t_gerar_proposta(s, cid, **p):
    erro = _cm_validar_proposta(p)
    if erro:
        return {"ok": False, "erro": erro}
    try:
        pdf = _cm_pdf_proposta(p)
    except Exception as e:
        return {"ok": False, "erro": f"Não foi possível montar o PDF: {e}"}
    nome = f"Proposta_-_{_mk_slug(p['cliente']['nome'], 40).replace('-', '_')}.pdf"
    a = _mk_salvar_gerado(s, cid, nome, "application/pdf", pdf)
    return {"ok": True, "anexo_id": a.id, "arquivo": nome, "tamanho_kb": round(len(pdf) / 1024),
            "observacao": "O PDF aparece no chamado, em 'Arquivos gerados'. Peça ao sócio para revisar valores e escopo."}


# ── Leads, negócios e referências de honorários ───────────────────────────────

def _cm_brl(v) -> str:
    return "R$ " + f"{float(v or 0):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _cm_digitos(v) -> str:
    return _re_cm.sub(r"\D", "", str(v or ""))


def _cm_clientes_idx(s, cid):
    por_cnpj, por_nome = {}, {}
    for c in s.exec(_sel_pr(Client).where(Client.company_id == cid)).all():
        if len(_cm_digitos(c.cnpj)) == 14 and _cm_digitos(c.cnpj) != "0" * 14:
            por_cnpj[_cm_digitos(c.cnpj)] = c
        por_nome[_pr_norm(c.name)] = c
    return por_cnpj, por_nome


def _cm_ja_cadastrado(idx, cnpj, empresa) -> str:
    por_cnpj, por_nome = idx
    c = por_cnpj.get(_cm_digitos(cnpj)) or por_nome.get(_pr_norm(empresa or ""))
    return c.name if c else ""


def _cm_t_leads(s, cid, dias):
    dias = max(1, min(int(dias or 30), 365))
    corte = _pr_hoje() - _td_pr(days=dias)
    idx = _cm_clientes_idx(s, cid)
    leads = []
    LC, TL, WP = globals().get("LeadCredito"), globals().get("TrialLead"), globals().get("WhatsAppProspectSession")
    if LC is not None:
        for l in s.exec(_sel_pr(LC)).all():
            d = _pr_data(l.criado_em)
            if d and d >= corte:
                leads.append({"origem": "Site — simulação de crédito", "data": _pr_fmt_data(d), "nome": l.nome,
                              "empresa": l.empresa, "cnpj": l.cnpj, "email": l.email, "whatsapp": l.whatsapp,
                              "detalhes": f"Finalidade: {l.finalidade}; valor pedido {_cm_brl(l.valor)}; prazo {l.prazo} meses; "
                                          f"faturamento informado {_cm_brl(l.faturamento)}; garantias: {l.garantias}",
                              "ja_no_cadastro": _cm_ja_cadastrado(idx, l.cnpj, l.empresa)})
    if TL is not None:
        for l in s.exec(_sel_pr(TL)).all():
            d = _pr_data(l.created_at)
            if d and d >= corte:
                leads.append({"origem": "Teste grátis do Augur PME", "data": _pr_fmt_data(d), "nome": l.nome,
                              "empresa": l.empresa, "cnpj": l.cnpj, "email": l.email, "whatsapp": l.whatsapp,
                              "detalhes": f"Usou {l.messages_used} de {l.messages_limit} mensagens; "
                                          f"{'convertido' if l.converted else 'não convertido'}",
                              "ja_no_cadastro": _cm_ja_cadastrado(idx, l.cnpj, l.empresa)})
    if WP is not None:
        for l in s.exec(_sel_pr(WP)).all():
            d = _pr_data(l.created_at)
            if d and d >= corte:
                leads.append({"origem": "WhatsApp (contato novo)", "data": _pr_fmt_data(d), "nome": l.nome,
                              "empresa": l.empresa, "cnpj": l.cnpj, "email": "", "whatsapp": l.phone,
                              "detalhes": f"Etapa da conversa: {l.state}; {l.msgs_used} mensagens",
                              "ja_no_cadastro": _cm_ja_cadastrado(idx, l.cnpj, l.empresa)})
    leads.sort(key=lambda x: _pr_data(x["data"]) or corte, reverse=True)
    return {"periodo_dias": dias, "total": len(leads), "novos_fora_do_cadastro": sum(1 for x in leads if not x["ja_no_cadastro"]),
            "leads": leads[:60]}


def _cm_t_negocios(s, cid, cliente, etapa):
    rotulos = {st["key"]: st["label"] for st in globals().get("CRM_STAGES", [])}
    q = _sel_pr(BusinessDeal).where(BusinessDeal.company_id == cid)
    if (cliente or "").strip():
        c, cands = _pr_resolver_cliente(s, cid, cliente)
        if not c:
            return _pr_nao_achei(cliente, cands)
        q = q.where(BusinessDeal.client_id == c.id)
    if etapa and etapa != "todas":
        q = q.where(BusinessDeal.stage == etapa)
    elif not (cliente or "").strip():
        q = q.where(BusinessDeal.stage.notin_(["ganho", "perdido"]))
    nomes = _pr_clientes(s, cid)
    saida = []
    for d in s.exec(q.order_by(BusinessDeal.updated_at.desc()).limit(40)).all():
        notas = s.exec(_sel_pr(BusinessDealNote).where(BusinessDealNote.deal_id == d.id)
                       .order_by(BusinessDealNote.created_at.desc()).limit(4)).all()
        saida.append({"negocio_id": d.id, "titulo": d.title, "cliente": nomes.get(d.client_id, ""),
                      "etapa": rotulos.get(d.stage, d.stage), "servico": d.service_name,
                      "valor_estimado": d.value_estimate_brl, "probabilidade": d.probability_pct,
                      "demanda": (d.demand or "")[:1500], "observacoes": (d.notes or "")[:800],
                      "proximo_passo": d.next_step, "data_proximo_passo": d.next_step_date, "origem": d.source,
                      "proposta_registrada": bool(d.proposal_id), "atualizado": _pr_quando(d.updated_at),
                      "notas_recentes": [n.message[:300] for n in notas]})
    return {"negocios": saida, "total": len(saida)}


def _cm_t_referencias(s, cid, termo):
    termos = [_pr_norm(t) for t in (termo or "").split() if len(t) > 2]

    def casa(*textos):
        alvo = _pr_norm(" ".join(str(t or "") for t in textos))
        return not termos or any(t in alvo for t in termos)

    nomes = _pr_clientes(s, cid)
    contratos = []
    CC = globals().get("ContratoCliente")
    todos = s.exec(_sel_pr(CC).where(CC.company_id == cid).order_by(CC.data_inicio.desc())).all() if CC is not None else []
    for k in todos:
        if not casa(k.nome_contrato, k.servicos, k.observacao):
            continue
        ini, fim = _pr_data(k.data_inicio), _pr_data(k.data_fim)
        meses = round((fim - ini).days / 30.4) if ini and fim else None
        contratos.append({"cliente": nomes.get(k.client_id, k.nome_cliente), "contrato": k.nome_contrato,
                          "servicos": k.servicos, "valor_mensal": round(k.valor_cents / 100, 2), "status": k.status,
                          "inicio": _pr_fmt_data(ini) if ini else "", "fim": _pr_fmt_data(fim) if fim else "",
                          "duracao_meses": meses})
    propostas = []
    for pr in s.exec(_sel_pr(Proposal).where(Proposal.company_id == cid, Proposal.kind == "proposta")
                     .order_by(Proposal.created_at.desc()).limit(80)).all():
        if casa(pr.title, pr.service_name, pr.description):
            propostas.append({"cliente": nomes.get(pr.client_id, ""), "titulo": pr.title, "servico": pr.service_name,
                              "valor": pr.value_brl, "status": pr.status, "data": _pr_fmt_data(pr.created_at.date())})
    ganhos = []
    for d in s.exec(_sel_pr(BusinessDeal).where(BusinessDeal.company_id == cid, BusinessDeal.stage.in_(["ganho", "perdido"]))
                    .order_by(BusinessDeal.updated_at.desc()).limit(80)).all():
        if casa(d.title, d.service_name, d.demand):
            ganhos.append({"cliente": nomes.get(d.client_id, ""), "negocio": d.title, "servico": d.service_name,
                           "valor_estimado": d.value_estimate_brl, "resultado": d.stage})
    return {"contratos": contratos[:40], "propostas": propostas[:40], "negocios_fechados": ganhos[:40],
            "observacao": "Referências reais do escritório. Honorários dependem do tipo de negócio e da demanda: "
                          "use como base e deixe claro ao sócio de onde veio cada número."}


# ── Sucesso do cliente ────────────────────────────────────────────────────────

def _cm_t_saude(s, cid):
    hoje = _pr_hoje()
    nomes = _pr_clientes(s, cid)
    carteira = {r["cliente"]: r for r in _pr_t_carteira(s, cid)["por_prioridade"]}
    contratos = _pr_contratos_ativos(s, cid)
    com_contrato = {}
    renovacoes = []
    for k in contratos:
        nome = nomes.get(k.client_id, k.nome_cliente)
        com_contrato.setdefault(nome, []).append(k.nome_contrato)
        fim = _pr_data(k.data_fim)
        if fim and fim <= hoje + _td_pr(days=120):
            renovacoes.append({"cliente": nome, "contrato": k.nome_contrato, "termina_em": _pr_fmt_data(fim),
                               "dias": (fim - hoje).days, "sinais_de_atencao": carteira.get(nome, {}).get("motivos", [])})
    renovacoes.sort(key=lambda x: x["dias"])
    risco = []
    for nome, contr in com_contrato.items():
        r = carteira.get(nome)
        if not r:
            continue
        pontos = len(r["motivos"]) + (2 if any(x["cliente"] == nome and x["dias"] <= 60 for x in renovacoes) else 0)
        risco.append({"cliente": nome, "contratos": contr, "nivel": "alto" if pontos >= 3 else "médio",
                      "motivos": r["motivos"], "dias_sem_reuniao": r["dias_sem_reuniao"],
                      "proxima_reuniao": r["proxima_reuniao"]})
    risco.sort(key=lambda x: (x["nivel"] != "alto", -len(x["motivos"])))
    saudaveis = [n for n in com_contrato if n not in carteira]
    return {"clientes_com_contrato_ativo": len(com_contrato), "renovacoes_em_120_dias": renovacoes,
            "risco_de_cancelamento": risco, "contratos_sem_sinais_de_atencao": saudaveis,
            "observacao": "Valores de contrato e pagamentos não aparecem aqui. Para oportunidades de venda adicional, "
                          "leia as últimas reuniões (reu_listar/reu_conteudo) e o panorama do cliente."}


# ── Propostas de ação: negócio no CRM e proposta registrada ───────────────────

_CM_ETAPAS = ["qualificacao", "criar_proposta", "proposta_enviada", "negociacao", "pausado", "ganho", "perdido"]


def _cm_t_propor_negocio(s, cid, empresa, cnpj, contato, email, telefone, cidade, estado, titulo, servico, demanda,
                         valor_estimado, probabilidade, proximo_passo, data_proximo_passo, origem):
    if len((empresa or "").strip()) < 2 or len((titulo or "").strip()) < 3:
        return {"ok": False, "erro": "Informe a empresa e o título do negócio."}
    if servico not in globals().get("SERVICE_NAME_SET", set()):
        return {"ok": False, "erro": "Serviço fora do catálogo do CRM."}
    if (data_proximo_passo or "").strip() and not _pr_data(data_proximo_passo):
        return {"ok": False, "erro": "Data do próximo passo inválida: use DD/MM/AAAA."}
    por_cnpj, por_nome = _cm_clientes_idx(s, cid)
    existente = por_cnpj.get(_cm_digitos(cnpj)) or por_nome.get(_pr_norm(empresa))
    if existente:
        aberto = s.exec(_sel_pr(BusinessDeal).where(BusinessDeal.company_id == cid, BusinessDeal.client_id == existente.id,
                                                    BusinessDeal.service_name == servico,
                                                    BusinessDeal.stage.notin_(["ganho", "perdido"]))).first()
        if aberto:
            return {"ok": False, "erro": f"Já existe o negócio #{aberto.id} '{aberto.title}' em aberto para "
                                         f"{existente.name} nesse serviço. Atualize-o em vez de criar outro."}
    for a in s.exec(_sel_pr(PredioAcao).where(PredioAcao.company_id == cid, PredioAcao.tipo == "criar_negocio",
                                              PredioAcao.status == "pendente")).all():
        pa = _json_pr.loads(a.payload_json or "{}")
        if _pr_norm(pa.get("empresa", "")) == _pr_norm(empresa) and pa.get("servico") == servico:
            return {"ok": False, "erro": f"Já existe uma proposta de negócio igual aguardando aprovação (#{a.id})."}
    payload = {"cliente_id": existente.id if existente else None, "empresa": empresa.strip(), "cnpj": _cm_digitos(cnpj),
               "contato": contato.strip(), "email": email.strip(), "telefone": telefone.strip(), "cidade": cidade.strip(),
               "estado": estado.strip()[:2].upper(), "titulo": titulo.strip()[:200], "servico": servico,
               "demanda": demanda.strip()[:4000], "valor": max(0.0, float(valor_estimado or 0)),
               "probabilidade": max(0, min(100, int(probabilidade or 0))), "proximo_passo": proximo_passo.strip()[:300],
               "data_proximo_passo": _pr_fmt_data(_pr_data(data_proximo_passo)) if _pr_data(data_proximo_passo) else "",
               "origem": origem.strip()[:120]}
    quem = existente.name if existente else f"{empresa.strip()} (novo no cadastro)"
    corpo = (f"{payload['demanda']}\n\nServiço: {servico} · Valor estimado: {_cm_brl(payload['valor'])} · "
             f"Probabilidade: {payload['probabilidade']}%\nPróximo passo: {payload['proximo_passo'] or '—'} "
             f"{payload['data_proximo_passo']}\nOrigem: {payload['origem'] or '—'}")
    acao = _pr_registrar_proposta(s, cid, tipo="criar_negocio", client_id=existente.id if existente else None,
                                  titulo=f"Novo negócio no CRM: {payload['titulo']}",
                                  destinatario=f"CRM · Qualificação · {quem}", assunto=payload["titulo"], corpo=corpo,
                                  payload_json=_json_pr.dumps(payload, ensure_ascii=False))
    return {"ok": True, "proposta_id": acao.id, "status": "aguardando aprovação",
            "observacao": "O negócio só é criado no CRM depois da aprovação." +
                          ("" if existente else " A empresa também será cadastrada como cliente (lead).")}


def _cm_exec_criar_negocio(s, acao) -> str:
    p = _json_pr.loads(acao.payload_json or "{}")
    cliente = s.get(Client, p["cliente_id"]) if p.get("cliente_id") else None
    if cliente and cliente.company_id != acao.company_id:
        raise _PrErro("Cliente inválido.")
    if not cliente:
        por_cnpj, por_nome = _cm_clientes_idx(s, acao.company_id)
        cliente = por_cnpj.get(p.get("cnpj", "")) or por_nome.get(_pr_norm(p["empresa"]))
    novo = cliente is None
    if novo:
        cliente = Client(company_id=acao.company_id, name=p["empresa"], cnpj=p.get("cnpj", ""), email=p.get("email", ""),
                         phone=p.get("telefone", ""), city=p.get("cidade", ""), state=p.get("estado", ""),
                         notes=f"Lead cadastrado pelo Prédio (Comercial). Contato: {p.get('contato', '')}")
        s.add(cliente)
        s.commit()
        s.refresh(cliente)
    deal = BusinessDeal(company_id=acao.company_id, client_id=cliente.id,
                        created_by_user_id=acao.decidido_por_user_id or 0, owner_user_id=acao.decidido_por_user_id,
                        title=p["titulo"], demand=p.get("demanda", ""), stage="qualificacao", service_name=p["servico"],
                        value_estimate_brl=p.get("valor", 0), probability_pct=p.get("probabilidade", 0),
                        next_step=p.get("proximo_passo", ""), next_step_date=p.get("data_proximo_passo", ""),
                        source=p.get("origem", "") or "predio", notes=f"Contato: {p.get('contato', '')}".strip())
    s.add(deal)
    s.commit()
    s.refresh(deal)
    return f"Negócio #{deal.id} criado no CRM" + (f" e {cliente.name} cadastrado como cliente." if novo else ".")


def _cm_t_propor_registrar_proposta(s, cid, negocio_id, anexo_id, titulo, valor_total):
    d = s.get(BusinessDeal, int(negocio_id or 0))
    if not d or d.company_id != cid:
        return {"ok": False, "erro": "Negócio não encontrado: use o negocio_id de com_negocios."}
    a = s.get(PredioAnexo, int(anexo_id or 0))
    if not a or a.company_id != cid or a.tipo != "gerado" or not a.nome.lower().endswith(".pdf"):
        return {"ok": False, "erro": "PDF da proposta não encontrado: gere com com_gerar_proposta e use o anexo_id."}
    if float(valor_total or 0) <= 0:
        return {"ok": False, "erro": "Informe o valor total da proposta (para o CRM)."}
    nome = _pr_clientes(s, cid).get(d.client_id, "")
    payload = {"negocio_id": d.id, "anexos": [{"id": a.id, "nome": a.nome}], "valor": float(valor_total),
               "titulo": titulo.strip()[:200]}
    acao = _pr_registrar_proposta(
        s, cid, tipo="registrar_proposta", client_id=d.client_id, titulo=f"Registrar proposta no CRM: {nome}",
        destinatario=f"CRM · negócio #{d.id} '{d.title}' → Proposta Enviada",
        assunto=payload["titulo"], corpo=f"Valor total: {_cm_brl(valor_total)}",
        payload_json=_json_pr.dumps(payload, ensure_ascii=False))
    return {"ok": True, "proposta_id": acao.id, "status": "aguardando aprovação",
            "observacao": "Aprove quando a proposta for enviada ao cliente: o negócio vai para 'Proposta Enviada'."}


def _cm_exec_registrar_proposta(s, acao) -> str:
    p = _json_pr.loads(acao.payload_json or "{}")
    d = s.get(BusinessDeal, int(p.get("negocio_id") or 0))
    if not d or d.company_id != acao.company_id:
        raise _PrErro("Negócio não encontrado.")
    anexo = (p.get("anexos") or [{}])[0]
    prop = Proposal(company_id=acao.company_id, client_id=d.client_id, created_by_user_id=acao.decidido_por_user_id or 0,
                    kind="proposta", title=acao.assunto or p.get("titulo") or d.title,
                    description=f"Proposta gerada no Prédio (PDF: /predio/anexos/{anexo.get('id')}).",
                    service_name=d.service_name, value_brl=p.get("valor", 0), status="enviada")
    s.add(prop)
    s.commit()
    s.refresh(prop)
    d.proposal_id = prop.id
    if d.stage in ("qualificacao", "criar_proposta"):
        d.stage = "proposta_enviada"
    if not d.value_estimate_brl:
        d.value_estimate_brl = p.get("valor", 0)
    d.updated_at = _dt_pr.utcnow()
    s.add(d)
    s.add(BusinessDealNote(deal_id=d.id, author_user_id=acao.decidido_por_user_id or 0,
                           message=f"Proposta registrada pelo Prédio: {prop.title} — PDF em /predio/anexos/{anexo.get('id')}"))
    s.commit()
    return f"Proposta #{prop.id} registrada; negócio #{d.id} em '{d.stage}'."


# ── Registro ──────────────────────────────────────────────────────────────────

_CM_S = {"type": "string"}
_CM_LISTA = {"type": "array", "items": _CM_S}

_CM_SCHEMA_PROPOSTA = {
    "titulo": {"type": "string", "description": "Ex.: Proposta de Consultoria Empresarial"},
    "subtitulo": {"type": "string", "description": "O projeto em uma linha (ex.: Implantação de Controladoria Gerencial...)."},
    "cliente": _mk_obj({"nome": {"type": "string", "description": "Razão social ou nome do cliente."},
                        "contato": {"type": "string", "description": "Pessoa de contato (Sr./Sra.) ou vazio."},
                        "email": _CM_S, "telefone": _CM_S,
                        "setor": {"type": "string", "description": "Ex.: Indústria — Fabricação de Argamassas"}}),
    "data_emissao": {"type": "string", "description": "DD/MM/AAAA (normalmente hoje)."},
    "validade_dias": {"type": "integer", "description": "Validade em dias corridos (padrão 15)."},
    "contexto": {"type": "string", "description": "Contexto e diagnóstico preliminar: 1 a 2 parágrafos."},
    "gaps": dict(_CM_LISTA, description="Gaps críticos identificados — 'Título — explicação'."),
    "pontos_positivos": dict(_CM_LISTA, description="Pontos positivos — 'Título — explicação'."),
    "contexto_estrategico": {"type": "string", "description": "Parágrafo de síntese estratégica (ou vazio)."},
    "escopo_intro": {"type": "string", "description": "Como o engajamento está estruturado."},
    "pilares": {"type": "array", "description": "Pilares do escopo, com itens numerados (1.1, 1.2...).",
                "items": _mk_obj({"titulo": {"type": "string", "description": "Ex.: PILAR 1 — Diagnóstico Financeiro..."},
                                  "itens": {"type": "array", "items": _mk_obj({
                                      "nome": {"type": "string", "description": "Ex.: 1.1 Levantamento Documental"},
                                      "descricao": _CM_S})}})},
    "cronograma": {"type": "array", "items": _mk_obj({"fase": _CM_S, "prazo": {"type": "string", "description": "Ex.: Meses 1–2"},
                                                      "entregas": _CM_S})},
    "metodologia": {"type": "array", "items": _mk_obj({"etapa": {"type": "string", "description": "Ex.: Imersão"},
                                                       "descricao": _CM_S})},
    "modalidades": {"type": "array", "description": "1 ou 2 modalidades (ex.: Sênior e Associada).",
                    "items": _mk_obj({"nome": {"type": "string", "description": "Ex.: Modalidade Sênior"},
                                      "conduzido_por": {"type": "string", "description": "Ex.: Atendimento direto com Rafael Maffezzolli"},
                                      "valor": {"type": "string", "description": "Ex.: R$ 8.300,00"},
                                      "detalhe_valor": {"type": "string", "description": "Ex.: por mês · 12 parcelas · Total: R$ 99.600,00"},
                                      "destaques": _CM_LISTA})},
    "comparativo": {"type": "array", "description": "Linhas da tabela comparativa (ou vazio). Uma coluna por modalidade.",
                    "items": _mk_obj({"item": _CM_S, "valores": _CM_LISTA})},
    "nota_modalidades": {"type": "string", "description": "Nota explicativa sobre as modalidades (ou vazio)."},
    "retorno_esperado": {"type": "string", "description": "Retorno esperado sobre o investimento, sem prometer resultado."},
    "condicoes": {"type": "array", "items": _mk_obj({"condicao": {"type": "string", "description": "Ex.: Pagamento"},
                                                     "detalhe": _CM_S})},
    "diferenciais": {"type": "array", "items": _mk_obj({"titulo": _CM_S, "texto": _CM_S})},
    "texto_aceite": {"type": "string", "description": "Instruções de aceite e contratação."},
}

_CM_FERRAMENTAS = {
    "com_leads": {
        "fn": _cm_t_leads, "rotulo": "Levantou os leads recentes",
        "description": "Leads que chegaram sozinhos: simulação de crédito do site, teste grátis do Augur PME e contatos "
                       "novos no WhatsApp, com dados informados e se já estão no cadastro.",
        "props": {"dias": {"type": "integer", "description": "Janela em dias (1 a 365)."}}},
    "com_negocios": {
        "fn": _cm_t_negocios, "rotulo": "Consultou os negócios do CRM",
        "description": "Negócios do CRM com negocio_id, etapa, serviço, valor, demanda, próximo passo e notas recentes. "
                       "Sem cliente e com etapa 'todas': todos os negócios em aberto.",
        "props": {"cliente": {"type": "string", "description": "Nome do cliente (vazio = todos)."},
                  "etapa": {"type": "string", "enum": ["todas"] + _CM_ETAPAS, "description": "Filtrar por etapa."}}},
    "com_referencias_honorarios": {
        "fn": _cm_t_referencias, "rotulo": "Levantou referências de honorários",
        "description": "Contratos (valor mensal, duração), propostas já feitas e negócios fechados do escritório, "
                       "filtrados por palavra (serviço, setor, tipo de projeto). Base para precificar.",
        "props": {"termo": {"type": "string", "description": "Palavras para filtrar (vazio = todos)."}}},
    "com_gerar_proposta": {
        "fn": _cm_t_gerar_proposta, "rotulo": "Gerou o PDF da proposta",
        "description": "Gera a proposta comercial em PDF no padrão M. Capital (capa, contexto e diagnóstico, escopo por "
                       "pilares, cronograma, metodologia, modalidades, condições, diferenciais e aceite) e anexa ao "
                       "chamado. Devolve o anexo_id. Pode ser gerada de novo após ajustes.",
        "props": _CM_SCHEMA_PROPOSTA},
    "com_propor_negocio": {
        "fn": _cm_t_propor_negocio, "rotulo": "Propôs um negócio no CRM",
        "description": "Cria uma PROPOSTA de novo negócio no CRM (etapa Qualificação). Se a empresa não estiver no "
                       "cadastro, ela é cadastrada como cliente/lead na aprovação. Nada é criado agora.",
        "props": {"empresa": _CM_S, "cnpj": {"type": "string", "description": "CNPJ ou vazio."},
                  "contato": {"type": "string", "description": "Nome do contato."}, "email": _CM_S, "telefone": _CM_S,
                  "cidade": _CM_S, "estado": {"type": "string", "description": "UF (ex.: SC)."},
                  "titulo": {"type": "string", "description": "Título do negócio (ex.: Reestruturação — Têxtil X)."},
                  "servico": {"type": "string", "enum": sorted(globals().get("SERVICE_NAME_SET", set())) or ["-"],
                              "description": "Serviço do catálogo."},
                  "demanda": {"type": "string", "description": "Dor, contexto e por que vale a pena (com fontes)."},
                  "valor_estimado": {"type": "number", "description": "Valor estimado em reais (0 se desconhecido)."},
                  "probabilidade": {"type": "integer", "description": "0 a 100."},
                  "proximo_passo": _CM_S, "data_proximo_passo": {"type": "string", "description": "DD/MM/AAAA ou vazio."},
                  "origem": {"type": "string", "description": "Ex.: Radar, Site — simulação de crédito, Indicação."}}},
    "com_propor_registrar_proposta": {
        "fn": _cm_t_propor_registrar_proposta, "rotulo": "Propôs registrar a proposta no CRM",
        "description": "Cria uma PROPOSTA para registrar a proposta comercial (PDF gerado) no CRM e mover o negócio "
                       "para 'Proposta Enviada'. O sócio aprova quando enviar a proposta ao cliente.",
        "props": {"negocio_id": {"type": "integer"}, "anexo_id": {"type": "integer", "description": "anexo_id do PDF."},
                  "titulo": _CM_S, "valor_total": {"type": "number", "description": "Valor total em reais (para o CRM)."}}},
    "com_saude_clientes": {
        "fn": _cm_t_saude, "rotulo": "Avaliou a saúde dos clientes",
        "description": "Clientes com contrato ativo: renovações em até 120 dias e risco de cancelamento (tarefas e ações "
                       "atrasadas, tempo sem reunião, projetos atrasados, pendências), sem valores financeiros.",
        "props": {}},
}

for _nome_cm, _spec_cm in _CM_FERRAMENTAS.items():
    _pr_registrar_ferramenta(_nome_cm, _spec_cm)

_PR_EXECUTORES_EXTRA["criar_negocio"] = _cm_exec_criar_negocio
_PR_EXECUTORES_EXTRA["registrar_proposta"] = _cm_exec_registrar_proposta
_PR_TIPOS_EQUIPE.update({"criar_negocio", "registrar_proposta"})

_CM_AGENTES = {
    "prospeccao": {
        "web": True, "papeis": _PR_TODOS,
        "ferramentas": ["com_leads", "com_negocios", "com_pipeline", "cli_panorama", "conh_buscar", "conh_ler",
                        "com_propor_negocio", "ops_propor_tarefa"],
        "instrucoes": (
            "Você é a prospecção da M. Capital, boutique financeira que atende empresas de R$ 10 a 150 milhões de "
            "faturamento no Sul do Brasil (reestruturação, gestão financeira/CFO externo, mercado de capitais — CRI, "
            "CRA, debêntures —, M&A e special situations).\n"
            "Fontes de leads: com_leads (site, teste do Augur, WhatsApp) e as listas do radar que o sócio colar ou "
            "anexar no chamado.\n"
            "Para cada lead ou empresa da lista:\n"
            "1. Veja se já está no CRM (com_negocios) ou é cliente (cli_panorama).\n"
            "2. Pesquise na web: porte e faturamento estimado, setor, notícias recentes, sinais de aperto (RJ, "
            "protestos, demissões, atrasos de obra, troca de gestão) e de oportunidade (expansão, captação, sucessão).\n"
            "3. Classifique: **Quente** (dor clara e porte no alvo), **Morno** ou **Fora do perfil**, com o motivo.\n"
            "4. Diga qual serviço oferecer e a abordagem: gancho da conversa e primeira mensagem curta e "
            "personalizada (sem prometer resultado).\n"
            "Para os quentes, proponha o negócio no CRM com com_propor_negocio (demanda com as fontes). Nunca faça "
            "contato: só prepare para a equipe. Cite a fonte de cada informação; o que não confirmar, marque como "
            "estimativa.")},
    "propostas": {
        "web": True, "papeis": _PR_ADMIN,
        "ferramentas": ["com_negocios", "com_referencias_honorarios", "cli_panorama", "reu_listar", "reu_conteudo",
                        "conh_buscar", "conh_ler", "com_gerar_proposta", "com_propor_registrar_proposta"],
        "instrucoes": (
            "Você monta as propostas comerciais da M. Capital no padrão da casa (o mesmo da proposta JVC): capa; "
            "1. Contexto e Diagnóstico Preliminar (gaps críticos e pontos positivos, contexto estratégico); 2. Escopo "
            "dos Serviços em pilares com itens numerados; 3. Cronograma; 4. Metodologia (Imersão, Diagnóstico, Plano de "
            "Ação, Implantação, Monitoramento); 5. Modalidades de Engajamento — normalmente Sênior (conduzida por "
            "Rafael Maffezzolli) e Associada (Consultor Associado, com revisão técnica de Rafael), mesmo escopo; 6. "
            "Condições Comerciais (estrutura do contrato, pagamento, reajuste pelo IPCA, extras não incluídos, "
            "confidencialidade); 7. Por que a M. Capital; 8. Aceite.\n"
            "Como trabalhar:\n"
            "- Base: a demanda do negócio no CRM, o pré-diagnóstico ou a reunião (reu_conteudo), arquivos anexados e "
            "a pesquisa sobre a empresa. Use os fatos do cliente; não invente números dele.\n"
            "- Honorários dependem do tipo de negócio e da demanda: se o sócio não informou, consulte "
            "com_referencias_honorarios, sugira valores e explique a base (\"contratos parecidos: R$ X a Y\"). Deixe "
            "claro no chat que os valores são sugestão para confirmar. Em captação/M&A, considere fee fixo + taxa de "
            "sucesso.\n"
            "- Escreva como consultor sênior: direto, específico para o setor do cliente, sem jargão vazio e sem "
            "prometer resultado (use \"tipicamente\", \"potencial\").\n"
            "- Gere o PDF com com_gerar_proposta e, no chat, resuma escopo, valores e o que o sócio deve conferir. "
            "Ajustes pedidos depois: gere de novo.\n"
            "- Quando o sócio disser que enviou (ou pedir), proponha registrar no CRM com com_propor_registrar_proposta.")},
    "sucesso_cliente": {
        "web": False, "papeis": _PR_TODOS,
        "ferramentas": ["com_saude_clientes", "cli_carteira", "cli_panorama", "reu_listar", "reu_conteudo", "conh_buscar",
                        "com_negocios", "com_propor_negocio", "ops_propor_tarefa"],
        "instrucoes": (
            "Você cuida da retenção e do crescimento da carteira.\n"
            "- Renovações: contratos que terminam em até 120 dias — diga o que mostrar ao cliente na conversa de "
            "renovação (resultados entregues, a partir das reuniões e do BSC) e proponha a tarefa de preparar a "
            "renovação para quem cuida do cliente.\n"
            "- Risco de cancelamento: explique os sinais de cada cliente e o próximo passo concreto, com responsável.\n"
            "- Venda adicional: leia as últimas reuniões e o panorama; quando aparecer uma dor que outro serviço "
            "resolve (crédito caro → captação/CRI; sem orçamento → BSC/Orçamento; sócio saindo → M&A/sucessão), "
            "aponte a oportunidade com o trecho que a sustenta e, se fizer sentido, proponha o negócio no CRM.\n"
            "Seja específico por cliente; não invente dados.")},
}

for _key_cm, _cfg_cm in _CM_AGENTES.items():
    _ag_cm = _PREDIO_AGENTES.get(_key_cm)
    if not _ag_cm:
        continue
    _ag_cm.update(ferramentas=list(_cfg_cm["ferramentas"]), web=_cfg_cm["web"], papeis=_cfg_cm["papeis"], ativo=True)
    _PR_INSTRUCOES[_key_cm] = _cfg_cm["instrucoes"]

print("[predio_comercial] Andar Comercial carregado.")

# ============================================================================
# ui_predio_ma.py — 3º andar do prédio: M&A e Valuation
# ============================================================================
# Exec'd no namespace do app.py, DEPOIS de ui_predio.py, ui_predio_marketing.py e
# ui_predio_comercial.py (usa _pr_*, _mk_salvar_gerado, _mk_slug, _cm_brl).
#
# AGENTES
#   valuation      — DCF (FCFF) e múltiplos calculados em Python com premissas
#                    explícitas; sensibilidade; laudo preliminar em PDF + modelo Excel
#   data_room      — checklist de due diligence por tipo de operação, documentos que
#                    o cliente já enviou (com leitura), o que falta e pedido de
#                    documentos (vira pendência "aguardando cliente" na aprovação)
#   originacao_ma  — sell-side: teaser anônimo em PDF, mapa de compradores e vitrine
#                    "Empresas à Venda" do site (só admin aprova a publicação)
#
# O modelo nunca faz conta: ele escolhe e justifica premissas; os números saem
# de _ma_calcular.
# ============================================================================

import io as _io_ma
import re as _re_ma
from xml.sax.saxutils import escape as _xesc_ma


# ── Cálculo: DCF + múltiplos ─────────────────────────────────────────────────

def _ma_pct(v) -> float:
    return float(v or 0) / 100.0


def _ma_estender(lista, n: int) -> list:
    if isinstance(lista, (int, float)):
        lista = [lista]
    lista = [float(x) for x in (lista or [])]
    if not lista:
        return [0.0] * n
    return (lista + [lista[-1]] * n)[:n]


def _ma_calcular(p: dict) -> dict:
    """Valuation por FCFF descontado (fim de período) + múltiplos de EV/EBITDA. Levanta ValueError com
    mensagem em português quando as premissas não fecham."""
    cresc = p.get("crescimento")
    anos = max(3, min(int(p.get("anos_projecao") or (len(cresc) if isinstance(cresc, list) else 0) or 5), 10))
    receita0 = float(p.get("receita_base") or 0)
    if receita0 <= 0:
        raise ValueError("Informe a receita do ano-base (maior que zero).")
    g = _ma_estender(p.get("crescimento"), anos)
    margem = _ma_estender(p.get("margem_ebitda"), anos)
    t = _ma_pct(p.get("aliquota_ir") if p.get("aliquota_ir") not in (None, "") else 34)
    dep, capex, ncg = _ma_pct(p.get("depreciacao_pct_receita")), _ma_pct(p.get("capex_pct_receita")), _ma_pct(p.get("ncg_pct_receita"))
    rf, beta, mrp = _ma_pct(p.get("taxa_livre_risco")), float(p.get("beta") or 1), _ma_pct(p.get("premio_mercado"))
    ke = rf + beta * mrp + _ma_pct(p.get("premio_tamanho")) + _ma_pct(p.get("premio_especifico"))
    kd = _ma_pct(p.get("custo_divida")) * (1 - t)
    wd = min(max(_ma_pct(p.get("peso_divida")), 0), 0.9)
    wacc = ke * (1 - wd) + kd * wd
    gp = _ma_pct(p.get("crescimento_perpetuo"))
    if wacc - gp < 0.01:
        raise ValueError(f"WACC ({wacc:.2%}) precisa ser pelo menos 1 p.p. maior que o crescimento na perpetuidade ({gp:.2%}).")
    divida_liq = float(p.get("divida_liquida") or 0)
    ano0 = int(p.get("ano_base") or _pr_hoje().year - 1)

    def dcf(taxa: float, g_perp: float) -> dict:
        linhas, rec_ant, vp = [], receita0, 0.0
        for i in range(anos):
            rec = rec_ant * (1 + g[i] / 100)
            ebitda = rec * margem[i] / 100
            d = rec * dep
            ebit = ebitda - d
            ir = max(ebit, 0) * t
            fc = ebit - ir + d - rec * capex - ncg * (rec - rec_ant)
            fator = 1 / (1 + taxa) ** (i + 1)
            vp += fc * fator
            linhas.append({"ano": ano0 + i + 1, "receita": rec, "crescimento_pct": g[i], "ebitda": ebitda,
                           "margem_ebitda_pct": margem[i], "depreciacao": d, "ebit": ebit, "ir": ir,
                           "capex": rec * capex, "variacao_ncg": ncg * (rec - rec_ant), "fcff": fc, "fator": fator,
                           "vp_fcff": fc * fator})
            rec_ant = rec
        vt = linhas[-1]["fcff"] * (1 + g_perp) / (taxa - g_perp)
        vp_vt = vt * linhas[-1]["fator"]
        ev = vp + vp_vt
        return {"linhas": linhas, "vp_fluxos": vp, "valor_terminal": vt, "vp_valor_terminal": vp_vt, "ev": ev,
                "equity": ev - divida_liq, "peso_valor_terminal_pct": (vp_vt / ev * 100) if ev else 0}

    base = dcf(wacc, gp)
    passos_w, passos_g = [-0.02, -0.01, 0, 0.01, 0.02], [-0.01, -0.005, 0, 0.005, 0.01]
    sens = []
    for dw in passos_w:
        linha = []
        for dg in passos_g:
            w2, g2 = wacc + dw, gp + dg
            linha.append(dcf(w2, g2)["equity"] if w2 - g2 >= 0.01 else None)
        sens.append({"wacc_pct": round((wacc + dw) * 100, 2), "equity": linha})
    validos = [v for l in sens for v in l["equity"][1:4] if v is not None]  # faixa central (g ± 0,5 p.p.)
    ebitda_atual = float(p.get("ebitda_atual") or 0)
    mult_min, mult_max = float(p.get("multiplo_min") or 0), float(p.get("multiplo_max") or 0)
    multiplos = None
    if ebitda_atual > 0 and mult_max >= mult_min > 0:
        multiplos = {"ebitda_atual": ebitda_atual, "multiplo_min": mult_min, "multiplo_max": mult_max,
                     "ev_min": ebitda_atual * mult_min, "ev_max": ebitda_atual * mult_max,
                     "equity_min": ebitda_atual * mult_min - divida_liq, "equity_max": ebitda_atual * mult_max - divida_liq}
    return {
        "anos": anos, "ano_base": ano0, "receita_base": receita0, "divida_liquida": divida_liq,
        "custo_capital_proprio_pct": ke * 100, "custo_divida_pos_ir_pct": kd * 100, "peso_divida_pct": wd * 100,
        "wacc_pct": wacc * 100, "crescimento_perpetuo_pct": gp * 100, "aliquota_ir_pct": t * 100,
        "dcf": base, "sensibilidade": {"crescimento_perpetuo_pct": [round((gp + d) * 100, 2) for d in passos_g], "linhas": sens},
        "faixa_dcf": {"min": min(validos), "max": max(validos)} if validos else None,
        "multiplos": multiplos,
        "multiplo_implicito_dcf": (base["ev"] / ebitda_atual) if ebitda_atual > 0 else None,
    }


def _ma_resumo(r: dict) -> dict:
    """Versão enxuta do cálculo para devolver ao agente (números arredondados)."""
    def m(v):
        return None if v is None else round(v / 1e6, 2)
    d = r["dcf"]
    return {
        "unidade": "R$ milhões",
        "wacc_pct": round(r["wacc_pct"], 2), "custo_capital_proprio_pct": round(r["custo_capital_proprio_pct"], 2),
        "crescimento_perpetuo_pct": round(r["crescimento_perpetuo_pct"], 2),
        "projecao": [{"ano": l["ano"], "receita": m(l["receita"]), "ebitda": m(l["ebitda"]), "fcff": m(l["fcff"])}
                     for l in d["linhas"]],
        "vp_fluxos": m(d["vp_fluxos"]), "vp_valor_terminal": m(d["vp_valor_terminal"]),
        "peso_valor_terminal_pct": round(d["peso_valor_terminal_pct"], 1),
        "enterprise_value": m(d["ev"]), "divida_liquida": m(r["divida_liquida"]), "equity_value": m(d["equity"]),
        "faixa_dcf_equity": {k: m(v) for k, v in (r["faixa_dcf"] or {}).items()},
        "multiplos_equity": {"min": m(r["multiplos"]["equity_min"]), "max": m(r["multiplos"]["equity_max"])} if r["multiplos"] else None,
        "multiplo_implicito_dcf": round(r["multiplo_implicito_dcf"], 1) if r["multiplo_implicito_dcf"] else None,
        "sensibilidade_equity": {"g_pct": r["sensibilidade"]["crescimento_perpetuo_pct"],
                                 "linhas": [{"wacc_pct": l["wacc_pct"], "equity": [m(v) for v in l["equity"]]}
                                            for l in r["sensibilidade"]["linhas"]]},
        "alertas": [a for a in (
            "O valor terminal passa de 75% do EV: o resultado depende muito da perpetuidade." if d["peso_valor_terminal_pct"] > 75 else "",
            "Equity negativo: a dívida líquida supera o valor da operação." if d["equity"] < 0 else "",
            ("O múltiplo implícito do DCF está fora da faixa de múltiplos informada: revise premissas ou comparáveis."
             if r["multiplos"] and r["multiplo_implicito_dcf"] and not (r["multiplos"]["multiplo_min"] * 0.7
                                                                       <= r["multiplo_implicito_dcf"]
                                                                       <= r["multiplos"]["multiplo_max"] * 1.3) else ""),
        ) if a],
    }


_MA_PROPS_PREMISSAS = {
    "empresa": {"type": "string"},
    "ano_base": {"type": "integer", "description": "Último ano com dados reais (ex.: 2025)."},
    "receita_base": {"type": "number", "description": "Receita líquida do ano-base em R$."},
    "anos_projecao": {"type": "integer", "description": "3 a 10 (padrão 5)."},
    "crescimento": {"type": "array", "items": {"type": "number"}, "description": "Crescimento da receita em % por ano."},
    "margem_ebitda": {"type": "array", "items": {"type": "number"}, "description": "Margem EBITDA em % por ano."},
    "depreciacao_pct_receita": {"type": "number", "description": "% da receita."},
    "capex_pct_receita": {"type": "number", "description": "% da receita."},
    "ncg_pct_receita": {"type": "number", "description": "Necessidade de capital de giro em % da receita."},
    "aliquota_ir": {"type": "number", "description": "IR+CSLL em % (34 no Lucro Real)."},
    "taxa_livre_risco": {"type": "number", "description": "% a.a. (ex.: NTN-B longa + inflação, ou Selic de longo prazo)."},
    "beta": {"type": "number", "description": "Beta alavancado do setor."},
    "premio_mercado": {"type": "number", "description": "Prêmio de risco de mercado em %."},
    "premio_tamanho": {"type": "number", "description": "Prêmio por tamanho em % (empresas fechadas médias: 2 a 5)."},
    "premio_especifico": {"type": "number", "description": "Risco específico em % (dependência do dono, concentração etc.)."},
    "custo_divida": {"type": "number", "description": "Custo da dívida antes do IR em % a.a."},
    "peso_divida": {"type": "number", "description": "Peso da dívida na estrutura de capital em %."},
    "crescimento_perpetuo": {"type": "number", "description": "Crescimento nominal na perpetuidade em %."},
    "divida_liquida": {"type": "number", "description": "Dívida bruta menos caixa, em R$ (negativo = caixa líquido)."},
    "ebitda_atual": {"type": "number", "description": "EBITDA do ano-base em R$ (para múltiplos)."},
    "multiplo_min": {"type": "number", "description": "EV/EBITDA mínimo dos comparáveis."},
    "multiplo_max": {"type": "number", "description": "EV/EBITDA máximo dos comparáveis."},
}


def _ma_t_calcular(s, cid, **p):
    try:
        return {"ok": True, **_ma_resumo(_ma_calcular(p))}
    except (ValueError, TypeError, ZeroDivisionError, OverflowError) as e:
        return {"ok": False, "erro": str(e)}


# ── PDF (laudo e teaser) no padrão M. Capital ─────────────────────────────────

def _ma_txt(texto) -> str:
    t = _xesc_ma(str(texto or "").strip())
    return _re_ma.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", t).replace("\n", "<br/>")


def _ma_mi(v) -> str:
    if v is None:
        return "—"
    return "R$ " + f"{v / 1e6:,.1f}".replace(",", "X").replace(".", ",").replace("X", ".") + " mi"


def _ma_doc(titulo_pagina: str, construir) -> bytes:
    """Monta um PDF A4 com cabeçalho/rodapé M. Capital; construir(estilos, cores, largura) devolve os flowables."""
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.pdfgen import canvas as _canvas
    from reportlab.platypus import SimpleDocTemplate

    C = {"lar": colors.HexColor("#E8772E"), "lar_claro": colors.HexColor("#FFF6EE"), "tinta": colors.HexColor("#1F2329"),
         "cinza": colors.HexColor("#6B7280"), "cinza_claro": colors.HexColor("#F6F7F9"), "linha": colors.HexColor("#E3E6EA"),
         "navy": colors.HexColor("#1E2235"), "branco": colors.white}

    def st(nome, **kw):
        base = dict(fontName="Helvetica", fontSize=9.5, leading=13, textColor=C["tinta"])
        base.update(kw)
        return ParagraphStyle(nome, **base)

    S = {"corpo": st("corpo"), "cinza": st("cinza", textColor=C["cinza"], fontSize=9),
         "h1": st("h1", fontName="Helvetica-Bold", fontSize=15, leading=19, textColor=C["lar"]),
         "titulo": st("titulo", fontName="Helvetica-Bold", fontSize=22, leading=27, textColor=C["lar"], alignment=TA_CENTER),
         "sub": st("sub", fontName="Helvetica-Bold", fontSize=12, leading=15, alignment=TA_CENTER),
         "sub_c": st("sub_c", fontName="Helvetica-Oblique", fontSize=11, textColor=C["cinza"], alignment=TA_CENTER),
         "cab": st("cab", fontName="Helvetica-Bold", fontSize=8.5, textColor=C["branco"], alignment=TA_CENTER),
         "cel": st("cel", fontSize=8.5, leading=11, alignment=TA_CENTER),
         "cel_e": st("cel_e", fontSize=8.5, leading=11), "neg": st("neg", fontName="Helvetica-Bold", fontSize=8.5, leading=11),
         "rotulo": st("rotulo", fontName="Helvetica-Bold", fontSize=8, textColor=C["lar"]),
         "grande": st("grande", fontName="Helvetica-Bold", fontSize=18, leading=22, alignment=TA_CENTER),
         "nota": st("nota", fontName="Helvetica-Oblique", fontSize=7.5, leading=10, textColor=C["cinza"])}
    largura = A4[0] - 40 * mm
    E = _CM_EMISSOR

    class _Moldura(_canvas.Canvas):
        def __init__(self, *a, **kw):
            super().__init__(*a, **kw)
            self._pags = []

        def showPage(self):
            self._pags.append(dict(self.__dict__))
            self._startPage()

        def save(self):
            total = len(self._pags)
            for estado in self._pags:
                self.__dict__.update(estado)
                w, h = A4
                self.setFont("Helvetica-Bold", 13); self.setFillColor(C["lar"])
                self.drawString(20 * mm, h - 17 * mm, E["marca"])
                x = 20 * mm + self.stringWidth(E["marca"], "Helvetica-Bold", 13)
                self.setFont("Helvetica", 9); self.setFillColor(C["cinza"])
                self.drawString(x + 2 * mm, h - 17 * mm, f"|  {E['linha']}")
                self.setFont("Helvetica-Oblique", 9)
                self.drawRightString(w - 20 * mm, h - 16 * mm, titulo_pagina)
                self.setStrokeColor(C["lar"]); self.setLineWidth(0.8)
                self.line(18 * mm, h - 23 * mm, w - 18 * mm, h - 23 * mm)
                self.setStrokeColor(C["linha"]); self.setLineWidth(0.5)
                self.line(18 * mm, 20 * mm, w - 18 * mm, 20 * mm)
                self.setFont("Helvetica", 7.5); self.setFillColor(C["cinza"])
                self.drawString(20 * mm, 15 * mm, f"{E['nome']} — {E['cidade']}  |  {E['email']}  |  {E['fone']}  |  Confidencial")
                self.drawRightString(w - 20 * mm, 15 * mm, f"Página {self._pageNumber} de {total}")
                super().showPage()
            super().save()

    buf = _io_ma.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=20 * mm, rightMargin=20 * mm, topMargin=30 * mm,
                            bottomMargin=26 * mm, title=titulo_pagina, author=E["nome"])
    doc.build(construir(S, C, largura), canvasmaker=_Moldura)
    return buf.getvalue()


def _ma_tabela(dados, larguras, C, extra=None):
    from reportlab.platypus import Table, TableStyle
    t = Table(dados, colWidths=larguras, repeatRows=1)
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), C["lar"]), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                           ("BOX", (0, 0), (-1, -1), 0.6, C["linha"]), ("INNERGRID", (0, 0), (-1, -1), 0.4, C["linha"]),
                           ("ROWBACKGROUNDS", (0, 1), (-1, -1), [C["branco"], C["cinza_claro"]]),
                           ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 5)] + (extra or [])))
    return t


def _ma_pdf_laudo(l: dict, r: dict) -> bytes:
    from reportlab.graphics.shapes import Drawing, Line, Rect, String
    from reportlab.platypus import PageBreak, Paragraph, Spacer, Table, TableStyle

    def construir(S, C, LARG):
        P = lambda t, e="corpo": Paragraph(_ma_txt(t), S[e])
        h = []
        d = r["dcf"]
        data = _pr_data(l.get("data_base")) or _pr_hoje()
        h += [Spacer(1, 30), P("LAUDO PRELIMINAR DE VALUATION", "titulo"), Spacer(1, 6), P(l["empresa"], "sub"),
              P(f"Data-base: {data.strftime('%d/%m/%Y')} · Finalidade: {l.get('finalidade') or 'referência para negociação'}", "sub_c"),
              Spacer(1, 22)]
        faixa = r["faixa_dcf"] or {"min": d["equity"], "max": d["equity"]}
        destaque = Table([[[P("VALOR DO EQUITY (DCF)", "rotulo"), P(_ma_mi(d["equity"]), "grande"),
                            P(f"Faixa de sensibilidade: {_ma_mi(faixa['min'])} a {_ma_mi(faixa['max'])}", "cinza")],
                           [P("MÚLTIPLOS EV/EBITDA", "rotulo"),
                            P(f"{_ma_mi(r['multiplos']['equity_min'])} a {_ma_mi(r['multiplos']['equity_max'])}" if r["multiplos"] else "—", "grande"),
                            P(f"{r['multiplos']['multiplo_min']:.1f}x a {r['multiplos']['multiplo_max']:.1f}x EBITDA" if r["multiplos"] else "Sem comparáveis", "cinza")]]],
                         colWidths=[LARG / 2, LARG / 2])
        destaque.setStyle(TableStyle([("BACKGROUND", (0, 0), (0, 0), C["lar_claro"]), ("BACKGROUND", (1, 0), (1, 0), C["cinza_claro"]),
                                      ("BOX", (0, 0), (-1, -1), 0.8, C["lar"]), ("INNERGRID", (0, 0), (-1, -1), 0.6, C["linha"]),
                                      ("TOPPADDING", (0, 0), (-1, -1), 10), ("BOTTOMPADDING", (0, 0), (-1, -1), 12),
                                      ("VALIGN", (0, 0), (-1, -1), "TOP")]))
        h += [destaque, Spacer(1, 14), P("Sumário executivo", "h1"), Spacer(1, 4), P(l.get("conclusao", ""))]

        # football field
        barras = [("DCF (sensibilidade)", faixa["min"], faixa["max"])]
        if r["multiplos"]:
            barras.append(("Múltiplos EV/EBITDA", r["multiplos"]["equity_min"], r["multiplos"]["equity_max"]))
        lo = min(min(b[1], b[2]) for b in barras + [("", d["equity"], d["equity"])])
        hi = max(max(b[1], b[2]) for b in barras + [("", d["equity"], d["equity"])])
        lo, hi = min(lo, 0) if lo < 0 else lo * 0.85, hi * 1.1 if hi > 0 else 1
        W, H = LARG, 30 + 26 * len(barras)
        ff = Drawing(W, H)
        x0, x1 = 120, W - 20
        esc = lambda v: x0 + (v - lo) / ((hi - lo) or 1) * (x1 - x0)
        for i, (nome, a, b) in enumerate(barras):
            y = H - 26 * (i + 1)
            ff.add(String(0, y + 4, nome, fontName="Helvetica", fontSize=8, fillColor=C["tinta"]))
            ff.add(Rect(esc(min(a, b)), y, max(esc(max(a, b)) - esc(min(a, b)), 2), 14, fillColor=C["lar"] if i == 0 else C["navy"],
                        strokeColor=None))
            ff.add(String(esc(max(a, b)) + 3, y + 4, _ma_mi(max(a, b)), fontName="Helvetica", fontSize=7, fillColor=C["cinza"]))
            ff.add(String(max(esc(min(a, b)) - 3, x0), y + 4, _ma_mi(min(a, b)), fontName="Helvetica", fontSize=7,
                          fillColor=C["cinza"], textAnchor="end"))
        xb = esc(d["equity"])
        ff.add(Line(xb, 6, xb, H - 4, strokeColor=C["tinta"], strokeWidth=1, strokeDashArray=[3, 2]))
        ff.add(String(xb, 0, f"DCF base {_ma_mi(d['equity'])}", fontName="Helvetica-Bold", fontSize=7, textAnchor="middle"))
        h += [Spacer(1, 10), P("Faixas de valor do equity", "rotulo"), Spacer(1, 4), ff]

        # empresa e premissas
        h += [PageBreak(), P("1. A empresa e a operação", "h1"), Spacer(1, 4), P(l.get("empresa_descricao", "")), Spacer(1, 10),
              P("2. Premissas", "h1"), Spacer(1, 4)]
        pr = [[Paragraph("PREMISSA", S["cab"]), Paragraph("VALOR", S["cab"]), Paragraph("JUSTIFICATIVA", S["cab"])]]
        for j in l.get("justificativas") or []:
            pr.append([P(j.get("premissa"), "neg"), P(j.get("valor"), "cel"), P(j.get("justificativa"), "cel_e")])
        if len(pr) > 1:
            h.append(_ma_tabela(pr, [LARG * 0.25, LARG * 0.15, LARG * 0.6], C))
        wacc = [[Paragraph("COMPONENTE", S["cab"]), Paragraph("VALOR", S["cab"])],
                [P("Custo do capital próprio (CAPM + prêmios)", "cel_e"), P(f"{r['custo_capital_proprio_pct']:.2f}%", "cel")],
                [P("Custo da dívida após IR", "cel_e"), P(f"{r['custo_divida_pos_ir_pct']:.2f}%", "cel")],
                [P("Peso da dívida", "cel_e"), P(f"{r['peso_divida_pct']:.0f}%", "cel")],
                [P("WACC", "neg"), P(f"{r['wacc_pct']:.2f}%", "neg")],
                [P("Crescimento na perpetuidade", "cel_e"), P(f"{r['crescimento_perpetuo_pct']:.2f}%", "cel")]]
        h += [Spacer(1, 10), P("Taxa de desconto", "rotulo"), Spacer(1, 3), _ma_tabela(wacc, [LARG * 0.7, LARG * 0.3], C)]

        # projeção
        cols = ["Ano"] + [str(x["ano"]) for x in d["linhas"]]
        def linha(rot, chave, pct=False):
            return [P(rot, "neg")] + [P(f"{x[chave]:.1f}%" if pct else f"{x[chave] / 1e6:,.1f}".replace(",", "X").replace(".", ",").replace("X", "."), "cel")
                                      for x in d["linhas"]]
        proj = [[Paragraph(c, S["cab"]) for c in cols], linha("Receita", "receita"), linha("Crescimento", "crescimento_pct", True),
                linha("EBITDA", "ebitda"), linha("Margem EBITDA", "margem_ebitda_pct", True), linha("(–) IR sobre EBIT", "ir"),
                linha("(–) Capex", "capex"), linha("(–) Var. capital de giro", "variacao_ncg"), linha("FCFF", "fcff"),
                linha("Valor presente", "vp_fcff")]
        n = len(cols)
        h += [PageBreak(), P("3. Projeção e fluxo de caixa livre (R$ milhões)", "h1"), Spacer(1, 4),
              _ma_tabela(proj, [LARG * 0.24] + [LARG * 0.76 / (n - 1)] * (n - 1), C,
                         [("BACKGROUND", (0, 8), (-1, 8), C["lar_claro"])])]
        res = [[Paragraph("DCF", S["cab"]), Paragraph("R$ MILHÕES", S["cab"])],
               [P("VP dos fluxos projetados", "cel_e"), P(f"{d['vp_fluxos'] / 1e6:,.1f}", "cel")],
               [P(f"VP do valor terminal ({d['peso_valor_terminal_pct']:.0f}% do EV)", "cel_e"), P(f"{d['vp_valor_terminal'] / 1e6:,.1f}", "cel")],
               [P("Enterprise value", "neg"), P(f"{d['ev'] / 1e6:,.1f}", "neg")],
               [P("(–) Dívida líquida", "cel_e"), P(f"{r['divida_liquida'] / 1e6:,.1f}", "cel")],
               [P("Equity value", "neg"), P(f"{d['equity'] / 1e6:,.1f}", "neg")]]
        h += [Spacer(1, 10), _ma_tabela(res, [LARG * 0.7, LARG * 0.3], C)]
        sens = r["sensibilidade"]
        st_ = [[Paragraph("WACC \\ g", S["cab"])] + [Paragraph(f"{g:.1f}%", S["cab"]) for g in sens["crescimento_perpetuo_pct"]]]
        for ln in sens["linhas"]:
            st_.append([P(f"{ln['wacc_pct']:.1f}%", "neg")] + [P("—" if v is None else f"{v / 1e6:,.1f}", "cel") for v in ln["equity"]])
        h += [Spacer(1, 12), P("4. Sensibilidade do equity (R$ milhões)", "h1"), Spacer(1, 4),
              _ma_tabela(st_, [LARG / 6] * 6, C, [("BACKGROUND", (3, 3), (3, 3), C["lar_claro"])])]
        if l.get("comparaveis"):
            cp = [[Paragraph("COMPARÁVEL", S["cab"]), Paragraph("EV/EBITDA", S["cab"]), Paragraph("FONTE", S["cab"])]]
            cp += [[P(c.get("empresa"), "cel_e"), P(c.get("multiplo"), "cel"), P(c.get("fonte"), "cel_e")] for c in l["comparaveis"]]
            h += [Spacer(1, 12), P("5. Múltiplos de comparáveis", "h1"), Spacer(1, 4),
                  _ma_tabela(cp, [LARG * 0.4, LARG * 0.15, LARG * 0.45], C)]
        h += [Spacer(1, 14), P("Ressalvas", "rotulo"), P(l.get("ressalvas", ""), "cinza"), Spacer(1, 8),
              P("Este é um laudo preliminar, baseado em informações fornecidas pela empresa e em premissas estimadas, "
                "sem auditoria ou verificação independente. Não constitui laudo de avaliação para fins legais, "
                "societários ou fiscais nem recomendação de investimento.", "nota")]
        return h

    return _ma_doc("Laudo Preliminar de Valuation", construir)


def _ma_excel_laudo(l: dict, r: dict) -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill
    wb = Workbook()
    ws = wb.active
    ws.title = "DCF"
    neg = Font(bold=True)
    ws.append([f"Valuation preliminar — {l['empresa']}"]); ws["A1"].font = Font(bold=True, size=13)
    ws.append([f"WACC {r['wacc_pct']:.2f}% · g {r['crescimento_perpetuo_pct']:.2f}% · IR {r['aliquota_ir_pct']:.0f}% · valores em R$"])
    ws.append([])
    linhas = r["dcf"]["linhas"]
    ws.append(["Ano"] + [x["ano"] for x in linhas])
    for c in ws[4]:
        c.font = Font(bold=True, color="FFFFFF"); c.fill = PatternFill("solid", fgColor="E8772E")
    for rot, k in [("Receita", "receita"), ("Crescimento %", "crescimento_pct"), ("EBITDA", "ebitda"),
                   ("Margem EBITDA %", "margem_ebitda_pct"), ("Depreciação", "depreciacao"), ("EBIT", "ebit"),
                   ("IR", "ir"), ("Capex", "capex"), ("Variação capital de giro", "variacao_ncg"), ("FCFF", "fcff"),
                   ("Fator de desconto", "fator"), ("VP FCFF", "vp_fcff")]:
        ws.append([rot] + [round(x[k], 4 if k == "fator" else 2) for x in linhas])
    d = r["dcf"]
    ws.append([])
    for rot, v in [("VP dos fluxos", d["vp_fluxos"]), ("Valor terminal", d["valor_terminal"]),
                   ("VP do valor terminal", d["vp_valor_terminal"]), ("Enterprise value", d["ev"]),
                   ("Dívida líquida", r["divida_liquida"]), ("Equity value", d["equity"])]:
        ws.append([rot, round(v, 2)])
        ws.cell(row=ws.max_row, column=1).font = neg
    ws.column_dimensions["A"].width = 28
    s2 = wb.create_sheet("Sensibilidade")
    s2.append(["Equity (R$) — WACC x crescimento na perpetuidade"])
    s2.append(["WACC \\ g"] + [f"{g:.2f}%" for g in r["sensibilidade"]["crescimento_perpetuo_pct"]])
    for ln in r["sensibilidade"]["linhas"]:
        s2.append([f"{ln['wacc_pct']:.2f}%"] + [None if v is None else round(v, 2) for v in ln["equity"]])
    s3 = wb.create_sheet("Premissas")
    s3.append(["Premissa", "Valor", "Justificativa"])
    for j in l.get("justificativas") or []:
        s3.append([j.get("premissa"), j.get("valor"), j.get("justificativa")])
    for k, v in (l.get("premissas") or {}).items():
        s3.append([k, str(v), "(entrada do modelo)"])
    buf = _io_ma.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _ma_t_gerar_laudo(s, cid, empresa, data_base, finalidade, empresa_descricao, premissas, justificativas,
                      comparaveis, conclusao, ressalvas):
    if not isinstance(premissas, dict):
        return {"ok": False, "erro": "Envie as premissas (as mesmas de val_calcular)."}
    try:
        r = _ma_calcular(premissas)
    except (ValueError, ZeroDivisionError, OverflowError) as e:
        return {"ok": False, "erro": str(e)}
    if len((conclusao or "").strip()) < 40 or len((empresa_descricao or "").strip()) < 40:
        return {"ok": False, "erro": "Escreva a descrição da empresa e o sumário executivo."}
    l = {"empresa": empresa or premissas.get("empresa") or "Empresa", "data_base": data_base, "finalidade": finalidade,
         "empresa_descricao": empresa_descricao, "justificativas": justificativas or [], "comparaveis": comparaveis or [],
         "conclusao": conclusao, "ressalvas": ressalvas or "", "premissas": premissas}
    base = _mk_slug(l["empresa"], 40).replace("-", "_")
    pdf = _mk_salvar_gerado(s, cid, f"Laudo_preliminar_-_{base}.pdf", "application/pdf", _ma_pdf_laudo(l, r))
    xlsx = _mk_salvar_gerado(s, cid, f"Modelo_DCF_-_{base}.xlsx",
                             "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", _ma_excel_laudo(l, r))
    return {"ok": True, "arquivos": [{"anexo_id": pdf.id, "nome": pdf.nome}, {"anexo_id": xlsx.id, "nome": xlsx.nome}],
            "resultado": _ma_resumo(r), "observacao": "Arquivos em 'Arquivos gerados' no chamado."}


# ── Dados do cliente e documentos ─────────────────────────────────────────────

def _ma_t_dados_cliente(s, cid, cliente):
    c, cands = _pr_resolver_cliente(s, cid, cliente)
    if not c:
        return _pr_nao_achei(cliente, cands)
    snaps = s.exec(_sel_pr(ClientSnapshot).where(ClientSnapshot.company_id == cid, ClientSnapshot.client_id == c.id)
                   .order_by(ClientSnapshot.created_at.desc()).limit(8)).all()
    return {"cliente": c.name, "cnpj": c.cnpj, "cidade": f"{c.city}/{c.state}".strip("/"),
            "cadastro": {"receita_mensal": c.revenue_monthly_brl, "divida_total": c.debt_total_brl,
                         "caixa": c.cash_balance_brl, "funcionarios": c.employees_count},
            "historico_diagnosticos": [{"data": x.snapshot_date or _pr_fmt_data(x.created_at.date()), "rotulo": x.label,
                                        "receita_mensal": x.revenue_monthly_brl, "divida_total": x.debt_total_brl,
                                        "caixa": x.cash_balance_brl, "funcionarios": x.employees_count,
                                        "score_financeiro": x.score_financial} for x in snaps],
            "observacao": "Para DRE e balanço, veja os documentos do cliente (dr_documentos / dr_ler_documento) ou peça o arquivo."}


def _ma_t_documentos(s, cid, cliente):
    c, cands = _pr_resolver_cliente(s, cid, cliente)
    if not c:
        return _pr_nao_achei(cliente, cands)
    BC = globals().get("BaseConhecimento")
    indexados = set()
    if BC is not None and hasattr(BC, "attachment_id"):
        indexados = {i for (i,) in [(x,) for x in s.exec(_sel_pr(BC.attachment_id).where(BC.company_id == cid,
                                                                                         BC.client_id == c.id)).all()] if i}
    docs = [{"documento_id": a.id, "arquivo": a.original_filename, "tipo": a.mime_type, "kb": round((a.size_bytes or 0) / 1024),
             "enviado_em": _pr_fmt_data(a.created_at.date()) if a.created_at else "", "texto_indexado": a.id in indexados}
            for a in s.exec(_sel_pr(Attachment).where(Attachment.company_id == cid, Attachment.client_id == c.id)
                            .order_by(Attachment.created_at.desc()).limit(150)).all()]
    base = []
    if BC is not None:
        base = [{"base_id": i, "titulo": n, "tipo": t} for i, n, t in s.exec(
            _sel_pr(BC.id, BC.nome, BC.tipo).where(BC.company_id == cid, BC.client_id == c.id).order_by(BC.id.desc()).limit(60)).all()]
    return {"cliente": c.name, "documentos": docs, "itens_na_base_de_conhecimento": base,
            "observacao": "Leia um documento com dr_ler_documento(documento_id) ou um item da base com conh_ler."}


_MA_MAX_DOC = 15 * 1024 * 1024


def _ma_t_ler_documento(s, cid, documento_id):
    a = s.get(Attachment, int(documento_id or 0))
    if not a or a.company_id != cid:
        return {"erro": "Documento não encontrado."}
    caminho = UPLOAD_DIR / a.stored_filename
    if not caminho.exists():
        return {"erro": "Arquivo não está no servidor. Peça para anexar no chamado."}
    if caminho.stat().st_size > _MA_MAX_DOC:
        return {"erro": "Arquivo grande demais para ler aqui (acima de 15 MB). Peça um recorte ou anexe no chamado."}
    dados, nome = caminho.read_bytes(), (a.original_filename or "").lower()
    texto = ""
    try:
        if nome.endswith((".xlsx", ".xlsm", ".xls")):
            texto = _pr_extrair_planilha(nome, dados)
        elif nome.endswith(".docx"):
            texto = _pr_extrair_docx(dados)
        elif nome.endswith(".pdf") or a.mime_type == "application/pdf":
            from pypdf import PdfReader
            leitor = PdfReader(_io_ma.BytesIO(dados))
            partes, total = [], 0
            for pg in leitor.pages[:80]:
                t = pg.extract_text() or ""
                partes.append(t)
                total += len(t)
                if total > 80_000:
                    break
            texto = "\n".join(partes)
        elif nome.endswith((".csv", ".txt", ".md")):
            texto = dados.decode("utf-8", errors="replace")
    except Exception as e:
        return {"erro": f"Não consegui ler {a.original_filename}: {e}"}
    del dados
    if len(texto.strip()) < 30:
        return {"arquivo": a.original_filename, "texto": "",
                "observacao": "Sem texto extraível (provavelmente escaneado ou imagem). Peça para anexar o arquivo no chamado: "
                              "assim o agente lê o PDF/imagem diretamente."}
    return {"arquivo": a.original_filename, "texto": texto[:80_000], "cortado": len(texto) > 80_000}


# ── Data Room: checklists e pedido de documentos ──────────────────────────────

_MA_CHECKLIST_BASE = {
    "Societário": [("Contrato/estatuto social e alterações", "alta"), ("Acordo de sócios/acionistas", "alta"),
                   ("Atas de reuniões e assembleias (3 anos)", "media"), ("Organograma societário do grupo", "alta"),
                   ("Procurações vigentes", "baixa")],
    "Financeiro": [("DRE dos últimos 3 anos e do ano corrente", "alta"), ("Balanços patrimoniais (3 anos)", "alta"),
                   ("Balancetes mensais do ano corrente", "alta"), ("Fluxo de caixa realizado (12 meses)", "media"),
                   ("Relação de contas a receber por cliente e aging", "media"), ("Relação de contas a pagar e aging", "media"),
                   ("Orçamento/projeções do ano", "media"), ("Relatórios de auditoria, se houver", "media")],
    "Endividamento": [("Mapa de dívidas (credor, saldo, taxa, prazo, garantias)", "alta"),
                      ("Contratos de financiamento e aditivos", "alta"), ("Garantias prestadas e avais", "alta"),
                      ("Extrato SCR/Registrato do Banco Central", "media")],
    "Tributário": [("Certidões negativas (federal, estadual, municipal, FGTS, trabalhista)", "alta"),
                   ("Parcelamentos fiscais em andamento", "alta"), ("Regime tributário e apurações (12 meses)", "media"),
                   ("Autos de infração e processos administrativos", "alta")],
    "Trabalhista": [("Quadro de funcionários e folha (12 meses)", "media"), ("Processos trabalhistas e provisões", "alta"),
                    ("Acordos e convenções coletivas", "baixa")],
    "Jurídico e contingências": [("Relação de processos judiciais com valores e chance de perda", "alta"),
                                 ("Contratos relevantes com clientes e fornecedores", "alta"),
                                 ("Licenças e alvarás de operação", "media"), ("Questões ambientais", "media")],
    "Operacional e comercial": [("Faturamento por cliente/produto (concentração)", "alta"),
                                ("Principais fornecedores e dependências", "media"), ("Ativos imobilizados e laudos", "media"),
                                ("Marcas, patentes e softwares", "baixa")],
}
_MA_CHECKLIST_EXTRA = {
    "venda_empresa": {"Transação": [("Teaser e memorando de informações aprovados", "media"),
                                    ("Expectativa de valor e estrutura desejada pelos sócios", "alta"),
                                    ("Plano de transição da gestão", "media")]},
    "compra_empresa": {"Transação": [("Tese de aquisição e sinergias", "alta"), ("Fontes de recursos da aquisição", "alta")]},
    "captacao_divida": {"Crédito": [("Projeção de caixa e capacidade de pagamento (24 meses)", "alta"),
                                    ("Garantias disponíveis com laudos/matrículas", "alta"), ("Rating/SCR atualizado", "media")]},
    "captacao_equity": {"Investidor": [("Plano de negócios e uso dos recursos", "alta"), ("Cap table atual", "alta"),
                                       ("Métricas operacionais (KPIs) históricas", "media")]},
    "cri_cra": {"Lastro e garantias": [("Matrículas atualizadas dos imóveis", "alta"), ("Contratos de venda/recebíveis (lastro)", "alta"),
                                       ("Cronograma físico-financeiro da obra", "alta"), ("Laudo de avaliação dos imóveis", "alta"),
                                       ("Licenças, alvará e habite-se/registro de incorporação", "alta")]},
    "reestruturacao": {"Reestruturação": [("Lista de credores com valores e classes", "alta"),
                                          ("Fluxo de caixa de 13 semanas", "alta"), ("Ativos não operacionais vendáveis", "media")]},
}
_MA_TIPOS = list(_MA_CHECKLIST_EXTRA)


def _ma_t_checklist(s, cid, tipo):
    if tipo not in _MA_CHECKLIST_EXTRA:
        return {"erro": f"Tipo inválido. Use: {', '.join(_MA_TIPOS)}."}
    cats = dict(_MA_CHECKLIST_BASE, **_MA_CHECKLIST_EXTRA[tipo])
    return {"tipo": tipo, "categorias": [{"categoria": k, "itens": [{"documento": d, "criticidade": c} for d, c in v]}
                                        for k, v in cats.items()],
            "observacao": "Ponto de partida padrão: adapte ao caso (inclua ou retire itens) antes de pedir ao cliente."}


def _ma_t_gerar_checklist(s, cid, cliente, tipo, itens):
    if not itens:
        return {"ok": False, "erro": "Nenhum item informado."}
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    wb = Workbook()
    ws = wb.active
    ws.title = "Due diligence"
    ws.append([f"Data room — {cliente} — {tipo.replace('_', ' ')}"]); ws["A1"].font = Font(bold=True, size=13)
    cont = {k: sum(1 for i in itens if i.get("status") == k) for k in ("recebido", "pendente", "nao_aplica")}
    ws.append([f"Gerado em {_pr_agora_brt().strftime('%d/%m/%Y')} · recebidos {cont['recebido']} · pendentes "
               f"{cont['pendente']} · não se aplica {cont['nao_aplica']}"])
    ws.append([])
    cab = ["Categoria", "Documento", "Criticidade", "Status", "Arquivo recebido", "Observação"]
    ws.append(cab)
    for cel in ws[4]:
        cel.font = Font(bold=True, color="FFFFFF"); cel.fill = PatternFill("solid", fgColor="1E2235")
    cores = {"recebido": "E8F6EE", "pendente": "FDF1F0", "nao_aplica": "F3F4F6"}
    for it in itens:
        ws.append([it.get("categoria"), it.get("documento"), it.get("criticidade"), it.get("status"), it.get("arquivo"),
                   it.get("observacao")])
        cor = cores.get(it.get("status"))
        if cor:
            ws.cell(row=ws.max_row, column=4).fill = PatternFill("solid", fgColor=cor)
    for col, w in zip("ABCDEF", (22, 55, 12, 13, 35, 45)):
        ws.column_dimensions[col].width = w
    for row in ws.iter_rows(min_row=5):
        for cel in row:
            cel.alignment = Alignment(wrap_text=True, vertical="top")
    ws.freeze_panes = "A5"
    buf = _io_ma.BytesIO()
    wb.save(buf)
    a = _mk_salvar_gerado(s, cid, f"Data_room_-_{_mk_slug(cliente, 40).replace('-', '_')}.xlsx",
                          "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", buf.getvalue())
    return {"ok": True, "anexo_id": a.id, "arquivo": a.nome, **cont}


def _ma_t_propor_solicitacao(s, cid, cliente, documentos, prazo, mensagem):
    c, cands = _pr_resolver_cliente(s, cid, cliente)
    if not c:
        return _pr_nao_achei(cliente, cands)
    docs = [str(d).strip()[:200] for d in (documentos or []) if str(d).strip()][:40]
    if not docs:
        return {"ok": False, "erro": "Liste os documentos a pedir."}
    if (prazo or "").strip() and not _pr_data(prazo):
        return {"ok": False, "erro": "Prazo inválido: use DD/MM/AAAA."}
    abertas = {_pr_norm(t) for (t,) in [(x,) for x in s.exec(_sel_pr(PendingItem.title).where(
        PendingItem.company_id == cid, PendingItem.client_id == c.id, PendingItem.status != "concluido")).all()]}
    novos = [d for d in docs if _pr_norm(d) not in abertas]
    if not novos:
        return {"ok": False, "erro": "Todos esses documentos já estão pedidos em pendências abertas do cliente."}
    corpo = "\n".join(f"• {d}" for d in novos) + (f"\n\n{mensagem.strip()}" if (mensagem or "").strip() else "")
    acao = _pr_registrar_proposta(
        s, cid, tipo="solicitar_documentos", client_id=c.id, titulo=f"Pedir {len(novos)} documento(s) a {c.name}",
        destinatario=f"Pendências do cliente {c.name} (ele vê na área dele) · prazo {_pr_fmt_data(_pr_data(prazo)) if _pr_data(prazo) else 'sem prazo'}",
        assunto=f"Documentos para análise — {c.name}", corpo=corpo,
        payload_json=_json_pr.dumps({"documentos": novos, "prazo": _pr_fmt_data(_pr_data(prazo)) if _pr_data(prazo) else "",
                                     "mensagem": (mensagem or "").strip()}, ensure_ascii=False))
    return {"ok": True, "proposta_id": acao.id, "pedidos": len(novos), "ja_pedidos_antes": len(docs) - len(novos),
            "observacao": "Na aprovação, cada documento vira uma pendência 'aguardando cliente'."}


def _ma_exec_solicitar(s, acao) -> str:
    p = _json_pr.loads(acao.payload_json or "{}")
    n = 0
    for d in p.get("documentos") or []:
        s.add(PendingItem(company_id=acao.company_id, client_id=acao.client_id, created_by_user_id=acao.decidido_por_user_id or 0,
                          title=d[:200], description=p.get("mensagem", ""), status="aguardando_cliente", due_date=p.get("prazo", "")))
        n += 1
    s.commit()
    return f"{n} pendência(s) criada(s) para o cliente, com status 'aguardando cliente'."


# ── Originação: teaser e vitrine Empresas à Venda ─────────────────────────────

_MA_GENERICAS = set("""
ltda eireli epp sa s/a me industria industrial comercio comercial servicos grupo empresa empresas holding participacoes
brasil brasileira nacional sul norte nordeste centro oeste leste vale serra litoral regiao regional santa catarina parana
rio grande paulo minas gerais textil texteis confeccao confeccoes malharia moveis metalurgica metal metais construtora
construcoes construcao incorporadora incorporacoes engenharia alimentos alimenticia bebidas transportes transportadora
logistica agro agricola agropecuaria pecuaria distribuidora distribuicao atacado varejo farmaceutica quimica plasticos
embalagens energia solar tecnologia sistemas software saude hospital clinica educacao escola imoveis imobiliaria
""".split())


def _ma_anonimo(texto: str, s, cid, cliente: str) -> str:
    """Devolve o que identifica o cliente no texto (nome completo, termo distintivo do nome ou CNPJ), ou vazio.
    Palavras genéricas de setor/região ('têxtil', 'Vale', 'Santa Catarina') sozinhas não contam."""
    if not (cliente or "").strip():
        return ""
    c, _ = _pr_resolver_cliente(s, cid, cliente)
    if not c:
        return ""
    alvo = " " + _re_ma.sub(r"[^a-z0-9]+", " ", _pr_norm(texto)) + " "
    tokens = [p for p in _re_ma.split(r"[^a-z0-9]+", _pr_norm(c.name)) if p]
    nucleo = " ".join(p for p in tokens if p not in ("ltda", "eireli", "epp", "sa", "me"))
    if nucleo and f" {nucleo} " in alvo:
        return c.name
    conectivos = ("do", "da", "de", "dos", "das", "e")
    for p in tokens:
        if len(p) >= 3 and p not in _MA_GENERICAS and p not in conectivos and f" {p} " in alvo:
            return f"{c.name} — termo '{p}'"
    # nome comercial feito de palavras genéricas ("Têxtil Vale"): a sequência de duas palavras identifica
    uteis = [p for p in tokens if p not in conectivos and p not in ("ltda", "eireli", "epp", "sa", "me")]
    for a, b in zip(uteis, uteis[1:]):
        if f" {a} {b} " in alvo:
            return f"{c.name} — '{a} {b}'"
    if len(_cm_digitos(c.cnpj)) == 14 and _cm_digitos(c.cnpj) in _re_ma.sub(r"\D", "", texto):
        return f"CNPJ de {c.name}"
    return ""


def _ma_t_gerar_teaser(s, cid, cliente, codinome, setor, regiao, tipo_transacao, descricao, destaques, faturamento,
                       ebitda, crescimento, tese, contato):
    texto = " ".join([codinome, setor, regiao, descricao, tese, " ".join(destaques or [])])
    vaz = _ma_anonimo(texto, s, cid, cliente)
    if vaz:
        return {"ok": False, "erro": f"O teaser identifica a empresa ({vaz}). Use só o codinome e dados genéricos."}
    from reportlab.platypus import Paragraph, Spacer, Table, TableStyle

    def construir(S, C, LARG):
        P = lambda t, e="corpo": Paragraph(_ma_txt(t), S[e])
        h = [Spacer(1, 6), P("OPORTUNIDADE DE INVESTIMENTO", "rotulo"), P(f"Projeto {codinome}", "titulo"),
             P(f"{setor} · {regiao} · {tipo_transacao}", "sub_c"), Spacer(1, 14)]
        nums = [[P("FATURAMENTO", "rotulo"), P("EBITDA", "rotulo"), P("CRESCIMENTO", "rotulo")],
                [P(faturamento, "grande"), P(ebitda, "grande"), P(crescimento, "grande")]]
        t = Table(nums, colWidths=[LARG / 3] * 3)
        t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), C["lar_claro"]), ("BOX", (0, 0), (-1, -1), 0.8, C["lar"]),
                               ("ALIGN", (0, 0), (-1, -1), "CENTER"), ("TOPPADDING", (0, 0), (-1, -1), 6),
                               ("BOTTOMPADDING", (0, 0), (-1, -1), 8)]))
        h += [t, Spacer(1, 14), P("A empresa", "h1"), Spacer(1, 3), P(descricao), Spacer(1, 10), P("Destaques", "h1"), Spacer(1, 3)]
        h += [P(f"•  {d}") for d in destaques or []]
        h += [Spacer(1, 10), P("Tese de investimento", "h1"), Spacer(1, 3), P(tese), Spacer(1, 14),
              P(f"Contato: {contato or 'Rafael Maffezzolli — M. Capital · contato@maffezzollicapital.com.br · (47) 99135-9091'}", "cinza"),
              Spacer(1, 6),
              P("Documento confidencial e não vinculante, preparado com informações fornecidas pela empresa, sem verificação "
                "independente. Informações adicionais somente mediante assinatura de acordo de confidencialidade (NDA).", "nota")]
        return h

    pdf = _ma_doc(f"Teaser — Projeto {codinome}", construir)
    a = _mk_salvar_gerado(s, cid, f"Teaser_-_Projeto_{_mk_slug(codinome, 30).replace('-', '_')}.pdf", "application/pdf", pdf)
    return {"ok": True, "anexo_id": a.id, "arquivo": a.nome}


def _ma_t_vitrine(s, cid):
    NV = globals().get("NegocioVenda")
    if NV is None:
        return {"erro": "Vitrine indisponível."}
    return {"publicados": [{"id": n.id, "nome": n.nome, "setor": n.setor, "faturamento": n.faturamento, "ebitda": n.ebitda,
                            "localizacao": n.localizacao, "status": n.status} for n in s.exec(_sel_pr(NV).order_by(NV.ordem, NV.id)).all()],
            "observacao": "É a lista que aparece na página Empresas à Venda do site."}


def _ma_t_propor_vitrine(s, cid, cliente, nome, setor, descricao, faturamento, ebitda, localizacao):
    vaz = _ma_anonimo(" ".join([nome, setor, descricao, localizacao]), s, cid, cliente)
    if vaz:
        return {"ok": False, "erro": f"O anúncio identifica a empresa ({vaz}). Use descrição anônima."}
    if len((descricao or "").strip()) < 60 or not (nome or "").strip():
        return {"ok": False, "erro": "Informe um título anônimo e uma descrição de pelo menos 2 frases."}
    payload = {"nome": nome.strip()[:120], "setor": setor.strip()[:80], "descricao": descricao.strip()[:1500],
               "faturamento": max(0.0, float(faturamento or 0)), "ebitda": float(ebitda or 0), "localizacao": localizacao.strip()[:80]}
    acao = _pr_registrar_proposta(
        s, cid, tipo="publicar_vitrine", titulo=f"Empresas à Venda no site: {payload['nome']}",
        destinatario="Site · página Empresas à Venda (publicada na hora da aprovação)", assunto=payload["nome"],
        corpo=f"{payload['setor']} · {payload['localizacao']}\nFaturamento {_cm_brl(payload['faturamento'])} · EBITDA "
              f"{_cm_brl(payload['ebitda'])}\n\n{payload['descricao']}",
        payload_json=_json_pr.dumps(payload, ensure_ascii=False))
    return {"ok": True, "proposta_id": acao.id, "status": "aguardando aprovação de um admin"}


def _ma_exec_vitrine(s, acao) -> str:
    NV = globals().get("NegocioVenda")
    if NV is None:
        raise _PrErro("Vitrine indisponível.")
    p = _json_pr.loads(acao.payload_json or "{}")
    n = NV(nome=p["nome"], setor=p["setor"], descricao=p["descricao"], faturamento=p["faturamento"], ebitda=p["ebitda"],
           localizacao=p["localizacao"], status="disponivel", criado_em=_pr_agora_brt().strftime("%Y-%m-%d %H:%M"))
    s.add(n)
    s.commit()
    s.refresh(n)
    return f"Publicado na página Empresas à Venda (#{n.id}). Para tirar do ar: Admin → Negócios à venda."


# ── Registro ──────────────────────────────────────────────────────────────────

_MA_S = {"type": "string"}
_MA_FERRAMENTAS = {
    "val_dados_cliente": {
        "fn": _ma_t_dados_cliente, "rotulo": "Levantou os dados financeiros do cliente",
        "description": "Cadastro financeiro do cliente (receita mensal, dívida, caixa, funcionários) e histórico dos "
                       "diagnósticos financeiros.",
        "props": {"cliente": {"type": "string", "description": "Nome do cliente."}}},
    "val_calcular": {
        "fn": _ma_t_calcular, "rotulo": "Calculou o valuation (DCF e múltiplos)",
        "description": "Calcula o valuation por fluxo de caixa livre da firma descontado (WACC por CAPM com prêmios de "
                       "tamanho e risco específico) e por múltiplos de EV/EBITDA, com sensibilidade WACC x crescimento. "
                       "Use sempre esta ferramenta para os números: nunca calcule de cabeça.",
        "props": _MA_PROPS_PREMISSAS},
    "val_gerar_laudo": {
        "fn": _ma_t_gerar_laudo, "rotulo": "Gerou o laudo preliminar (PDF + Excel)",
        "description": "Gera o laudo preliminar de valuation em PDF (sumário, faixas de valor, premissas justificadas, WACC, "
                       "projeção, DCF, sensibilidade, comparáveis e ressalvas) e o modelo em Excel. Recalcula com as "
                       "premissas enviadas.",
        "props": {"empresa": _MA_S, "data_base": {"type": "string", "description": "DD/MM/AAAA"},
                  "finalidade": {"type": "string", "description": "Ex.: referência para venda de participação."},
                  "empresa_descricao": {"type": "string", "description": "Empresa, mercado e operação, 1 a 3 parágrafos."},
                  "premissas": {"type": "object", "description": "As mesmas premissas de val_calcular.",
                                "properties": _MA_PROPS_PREMISSAS},
                  "justificativas": {"type": "array", "description": "Por que cada premissa (com fonte).",
                                     "items": {"type": "object", "properties": {"premissa": _MA_S, "valor": _MA_S,
                                                                                "justificativa": _MA_S}}},
                  "comparaveis": {"type": "array", "items": {"type": "object", "properties": {
                      "empresa": _MA_S, "multiplo": _MA_S, "fonte": _MA_S}}},
                  "conclusao": {"type": "string", "description": "Sumário executivo: valor, faixa e o que move o número."},
                  "ressalvas": _MA_S}},
    "dr_checklist": {
        "fn": _ma_t_checklist, "rotulo": "Montou o checklist de due diligence",
        "description": "Checklist padrão de due diligence por tipo de operação, com criticidade.",
        "props": {"tipo": {"type": "string", "enum": _MA_TIPOS}}},
    "dr_documentos": {
        "fn": _ma_t_documentos, "rotulo": "Listou os documentos do cliente",
        "description": "Documentos que o cliente já enviou à plataforma (com documento_id) e itens dele na base de conhecimento.",
        "props": {"cliente": _MA_S}},
    "dr_ler_documento": {
        "fn": _ma_t_ler_documento, "rotulo": "Leu um documento do cliente",
        "description": "Texto de um documento do cliente (PDF com texto, Excel, Word, CSV), até 80 mil caracteres.",
        "props": {"documento_id": {"type": "integer"}}},
    "dr_gerar_checklist": {
        "fn": _ma_t_gerar_checklist, "rotulo": "Gerou a planilha do data room",
        "description": "Gera a planilha de controle do data room (item, criticidade, status, arquivo recebido, observação).",
        "props": {"cliente": _MA_S, "tipo": _MA_S,
                  "itens": {"type": "array", "items": {"type": "object", "properties": {
                      "categoria": _MA_S, "documento": _MA_S, "criticidade": {"type": "string", "enum": ["alta", "media", "baixa"]},
                      "status": {"type": "string", "enum": ["recebido", "pendente", "nao_aplica"]},
                      "arquivo": _MA_S, "observacao": _MA_S}}}}},
    "dr_propor_solicitacao": {
        "fn": _ma_t_propor_solicitacao, "rotulo": "Propôs pedir documentos ao cliente",
        "description": "Cria uma PROPOSTA de pedido de documentos: na aprovação, cada documento vira uma pendência "
                       "'aguardando cliente', que ele vê na área dele. Não repete o que já está pedido.",
        "props": {"cliente": _MA_S, "documentos": {"type": "array", "items": _MA_S},
                  "prazo": {"type": "string", "description": "DD/MM/AAAA ou vazio."},
                  "mensagem": {"type": "string", "description": "Orientação ao cliente (ou vazio)."}}},
    "ma_gerar_teaser": {
        "fn": _ma_t_gerar_teaser, "rotulo": "Gerou o teaser anônimo",
        "description": "Gera o teaser de uma página (anônimo, com codinome) em PDF. Recusa se o texto identificar a empresa.",
        "props": {"cliente": {"type": "string", "description": "Cliente real (só para checar o anonimato)."},
                  "codinome": _MA_S, "setor": _MA_S, "regiao": {"type": "string", "description": "Ex.: Vale do Itajaí (SC)."},
                  "tipo_transacao": {"type": "string", "description": "Ex.: venda de 100%, entrada de sócio, sucessão."},
                  "descricao": _MA_S, "destaques": {"type": "array", "items": _MA_S},
                  "faturamento": {"type": "string", "description": "Faixa, ex.: R$ 40–50 mi."},
                  "ebitda": {"type": "string", "description": "Faixa ou margem, ex.: ~15%."},
                  "crescimento": {"type": "string", "description": "Ex.: 12% a.a. (3 anos)."},
                  "tese": _MA_S, "contato": {"type": "string", "description": "Vazio = contato padrão da M. Capital."}}},
    "ma_vitrine": {
        "fn": _ma_t_vitrine, "rotulo": "Consultou a vitrine Empresas à Venda",
        "description": "Negócios publicados na página Empresas à Venda do site.", "props": {}},
    "ma_propor_vitrine": {
        "fn": _ma_t_propor_vitrine, "rotulo": "Propôs anúncio em Empresas à Venda",
        "description": "Cria uma PROPOSTA de anúncio anônimo na página Empresas à Venda do site. Só um admin publica.",
        "props": {"cliente": {"type": "string", "description": "Cliente real (só para checar o anonimato)."},
                  "nome": {"type": "string", "description": "Título anônimo, ex.: Indústria têxtil — SC."},
                  "setor": _MA_S, "descricao": _MA_S, "faturamento": {"type": "number", "description": "R$ anual."},
                  "ebitda": {"type": "number", "description": "R$ anual."}, "localizacao": {"type": "string", "description": "Estado ou região."}}},
}
# objetos internos do laudo/data room/teaser seguem schema sem strict (validados no código)
for _o in (_MA_FERRAMENTAS["val_gerar_laudo"]["props"]["justificativas"]["items"],
           _MA_FERRAMENTAS["val_gerar_laudo"]["props"]["comparaveis"]["items"]):
    _o["additionalProperties"] = False
    _o["required"] = list(_o["properties"])
_o = _MA_FERRAMENTAS["dr_gerar_checklist"]["props"]["itens"]["items"]
_o["additionalProperties"], _o["required"] = False, list(_o["properties"])
_o = _MA_FERRAMENTAS["val_gerar_laudo"]["props"]["premissas"]
_o["additionalProperties"], _o["required"] = False, list(_o["properties"])

for _nome_ma, _spec_ma in _MA_FERRAMENTAS.items():
    _pr_registrar_ferramenta(_nome_ma, _spec_ma)

_PR_EXECUTORES_EXTRA["solicitar_documentos"] = _ma_exec_solicitar
_PR_EXECUTORES_EXTRA["publicar_vitrine"] = _ma_exec_vitrine
_PR_TIPOS_EQUIPE.add("solicitar_documentos")

_MA_AGENTES = {
    "valuation": {
        "web": True,
        "ferramentas": ["val_dados_cliente", "val_calcular", "val_gerar_laudo", "dr_documentos", "dr_ler_documento",
                        "cli_panorama", "reu_listar", "reu_conteudo", "conh_buscar", "conh_ler", "mkt_indicadores", "com_formularios"],
        "instrucoes": (
            "Você faz valuation de empresas médias (R$ 10 a 150 mi de faturamento) do Sul do Brasil.\n"
            "Método: 1) levante os números reais — DRE, balanço e dívida — nos documentos do cliente (dr_documentos, "
            "dr_ler_documento), nos arquivos anexados ao chamado, no pré-diagnóstico (com_formularios) e no cadastro "
            "(val_dados_cliente); 2) normalize o EBITDA (retire não recorrentes e ajuste pró-labore fora de mercado) e "
            "explique os ajustes; 3) monte as premissas e justifique cada uma com dado ou fonte: taxa livre de risco "
            "(use mkt_indicadores e a NTN-B longa pesquisada na web), beta e prêmio de mercado do setor (Damodaran, "
            "emergentes), prêmio por tamanho e risco específico (dependência do dono, concentração de clientes, "
            "governança), crescimento e margens coerentes com o histórico; 4) pesquise múltiplos EV/EBITDA de transações "
            "e empresas comparáveis no Brasil, com fonte, e aplique desconto de liquidez para empresa fechada; "
            "5) calcule SEMPRE com val_calcular — nunca faça contas de cabeça; 6) leia os alertas e a sensibilidade e "
            "revise o que não fizer sentido (valor terminal acima de 75% do EV, múltiplo implícito fora da faixa); "
            "7) quando pedido, gere o laudo com val_gerar_laudo.\n"
            "Apresente: valor base, faixa, o que mais move o número e o que falta de informação. Se faltar DRE ou "
            "balanço, diga exatamente o que pedir (o Data Room pode pedir ao cliente). É um laudo preliminar: deixe "
            "claro que não substitui laudo formal.")},
    "data_room": {
        "web": False,
        "ferramentas": ["dr_checklist", "dr_documentos", "dr_ler_documento", "dr_gerar_checklist", "dr_propor_solicitacao",
                        "cli_panorama", "conh_buscar", "conh_ler", "ops_propor_tarefa"],
        "instrucoes": (
            "Você organiza o data room e a due diligence das operações (venda ou compra de empresa, captação de dívida "
            "ou equity, CRI/CRA, reestruturação).\n"
            "1) Pegue o checklist do tipo de operação (dr_checklist) e adapte ao caso; 2) cruze com os documentos que o "
            "cliente já enviou (dr_documentos) — abra os que tiver dúvida (dr_ler_documento) para confirmar o que são e "
            "o período que cobrem; 3) classifique cada item em recebido, pendente ou não se aplica, e aponte "
            "inconsistências (período faltando, documento vencido, números que não batem); 4) gere a planilha de "
            "controle com dr_gerar_checklist; 5) proponha o pedido dos pendentes com dr_propor_solicitacao, priorizando "
            "criticidade alta, em linguagem clara para o cliente.\n"
            "Nunca diga que um documento foi recebido sem ver o arquivo correspondente.")},
    "originacao_ma": {
        "web": True,
        "ferramentas": ["val_dados_cliente", "cli_panorama", "dr_documentos", "dr_ler_documento", "conh_buscar", "conh_ler",
                        "ma_gerar_teaser", "ma_vitrine", "ma_propor_vitrine", "com_negocios", "com_propor_negocio"],
        "instrucoes": (
            "Você cuida do sell-side de M&A: preparar a empresa para venda e encontrar compradores.\n"
            "- Teaser: uma página anônima com codinome, setor, região, faixas de faturamento e EBITDA, destaques e tese "
            "de investimento. Nada que identifique a empresa (nome, marcas, cidade pequena, clientes, CNPJ) — a "
            "ferramenta recusa se identificar. Use faixas, não números exatos.\n"
            "- Compradores: pesquise na web e monte a lista em três grupos — estratégicos (concorrentes, fornecedores, "
            "clientes, players que querem entrar na região), financeiros (fundos de private equity e search funds que "
            "investem no porte e no setor) e family offices — com o racional de cada um e a fonte. Não faça contato.\n"
            "- Vitrine Empresas à Venda do site: veja o que já está publicado (ma_vitrine) e proponha o anúncio anônimo "
            "com ma_propor_vitrine; só um admin publica.\n"
            "- Compra: quando o cliente quer comprar, mapeie alvos com os mesmos critérios.\n"
            "Para cada mandato novo, se ainda não houver, proponha o negócio no CRM.")},
}

for _key_ma, _cfg_ma in _MA_AGENTES.items():
    _ag_ma = _PREDIO_AGENTES.get(_key_ma)
    if not _ag_ma:
        continue
    _ag_ma.update(ferramentas=list(_cfg_ma["ferramentas"]), web=_cfg_ma["web"], ativo=True)
    _PR_INSTRUCOES[_key_ma] = _cfg_ma["instrucoes"]

print("[predio_ma] Andar de M&A e Valuation carregado.")

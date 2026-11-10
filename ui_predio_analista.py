# ============================================================================
# ui_predio_analista.py — 6º andar: Analista Financeiro com Excel e mais análises
# ============================================================================
# Exec'd no namespace do app.py, DEPOIS de ui_predio_consultoria.py (usa _pr_*,
# _mk_salvar_gerado, _mk_slug, _cm_brl).
#
# Ferramentas novas (cálculo sempre em Python; Excel com FÓRMULAS VIVAS, para o
# cliente mexer nas premissas e ver o resultado mudar):
#   an_gerar_excel      — planilha livre em abas (DRE reclassificada, balancete extraído,
#                         comparativos...), com formatos, totais e fórmulas
#   an_analise_hv       — análise horizontal e vertical de DRE ou balanço
#   an_projecao_caixa   — fluxo de caixa projetado (13 semanas ou meses): saldo, menor
#                         saldo, quando fica negativo e a necessidade de capital
#   an_cenarios         — DRE projetada em cenários, ponto de equilíbrio e margem de segurança
#   an_amortizacao      — tabela Price ou SAC, com carência
# Os arquivos aparecem em "Arquivos gerados" no chamado.
# ============================================================================

import io as _io_an
import re as _re_an
from datetime import date as _date_an

_AN_LARANJA = "E8772E"
_AN_FMT = {"moeda": 'R$ #,##0.00;[Red]-R$ #,##0.00', "numero": '#,##0.00;[Red]-#,##0.00', "inteiro": '#,##0',
           "pct": '0.0%;[Red]-0.0%', "data": 'DD/MM/YYYY', "texto": '@'}
_AN_MAX_LINHAS = 3000


class _AnErro(ValueError):
    pass


def _an_lista(v) -> list:
    return v if isinstance(v, list) else []


# ── Excel: base ───────────────────────────────────────────────────────────────

def _an_wb():
    from openpyxl import Workbook
    wb = Workbook()
    wb.remove(wb.active)
    return wb


def _an_nome_aba(nome, usados: set) -> str:
    n = _re_an.sub(r"[\[\]:*?/\\]", " ", str(nome or "Planilha")).strip()[:31] or "Planilha"
    base, i = n, 2
    while n.lower() in usados:
        n = f"{base[:28]} {i}"
        i += 1
    usados.add(n.lower())
    return n


def _an_topo(ws, titulo, subtitulo, ncols):
    from openpyxl.styles import Font
    ws["A1"] = titulo
    ws["A1"].font = Font(bold=True, size=14)
    ws["A2"] = subtitulo
    ws["A2"].font = Font(italic=True, size=9, color="666666")


def _an_cabecalho(ws, linha, titulos):
    from openpyxl.styles import Alignment, Font, PatternFill
    for i, t in enumerate(titulos, 1):
        c = ws.cell(row=linha, column=i, value=t)
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor=_AN_LARANJA)
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)


def _an_negrito(ws, linha, ncols, fundo="F3E6DC"):
    from openpyxl.styles import Font, PatternFill
    for i in range(1, ncols + 1):
        c = ws.cell(row=linha, column=i)
        c.font = Font(bold=True)
        c.fill = PatternFill("solid", fgColor=fundo)


def _an_larguras(ws, primeira=34, demais=16, ncols=2):
    from openpyxl.utils import get_column_letter
    ws.column_dimensions["A"].width = primeira
    for i in range(2, ncols + 1):
        ws.column_dimensions[get_column_letter(i)].width = demais


def _an_sub(cliente) -> str:
    return f"Maffezzolli Capital · {cliente or 'análise'} · gerado em {_pr_fmt_data(_pr_hoje())}"


def _an_salvar(s, cid, wb, nome) -> dict:
    buf = _io_an.BytesIO()
    wb.save(buf)
    a = _mk_salvar_gerado(s, cid, nome, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", buf.getvalue())
    return {"anexo_id": a.id, "arquivo": a.nome}


def _an_arquivo(prefixo, cliente) -> str:
    return f"{prefixo}_-_{_mk_slug(cliente or 'analise', 40).replace('-', '_')}.xlsx"


def _an_formula_ok(f: str) -> str:
    f = f.strip()
    if len(f) > 1000 or "|" in f or _re_an.search(r"\[[^\]]*\]", f) or _re_an.search(r"(?i)\b(WEBSERVICE|CALL|REGISTER|EXEC)\s*\(", f):
        raise _AnErro(f"Fórmula não permitida: {f[:60]}")
    return f


def _an_num(t: str):
    t = str(t).replace("R$", "").replace("%", "").replace(" ", "").replace(" ", "").strip()
    neg = t.startswith("(") and t.endswith(")")
    t = t.strip("()")
    if "," in t and "." in t:
        t = t.replace(".", "").replace(",", ".") if t.rfind(",") > t.rfind(".") else t.replace(",", "")
    elif "," in t:
        t = t.replace(",", ".")
    v = float(t)
    return -v if neg else v


def _an_valor(txt, fmt):
    if txt is None:
        return None
    if isinstance(txt, (int, float)) and not isinstance(txt, bool):
        return txt / 100 if fmt == "pct" else txt
    t = str(txt).strip()
    if not t:
        return None
    if t.startswith("="):
        return _an_formula_ok(t)
    if fmt in ("moeda", "numero", "inteiro", "pct"):
        try:
            v = _an_num(t)
            return v / 100 if fmt == "pct" else v
        except ValueError:
            return t
    if fmt == "data":
        return _pr_data(t) or t
    return t


# ── an_gerar_excel ────────────────────────────────────────────────────────────

def _an_t_gerar_excel(s, cid, cliente, titulo, abas):
    from openpyxl.utils import get_column_letter
    abas = [a for a in _an_lista(abas) if isinstance(a, dict) and isinstance(a.get("colunas"), list) and a["colunas"]]
    if not abas:
        return {"ok": False, "erro": "Envie ao menos uma aba com colunas e linhas."}
    if len(abas) > 12:
        return {"ok": False, "erro": "No máximo 12 abas."}
    wb, usados = _an_wb(), set()
    try:
        for aba in abas:
            cols = [c for c in aba["colunas"] if isinstance(c, dict)]
            linhas = [l for l in _an_lista(aba.get("linhas")) if isinstance(l, list)]
            if len(linhas) > _AN_MAX_LINHAS:
                raise _AnErro(f"Aba '{aba.get('nome')}' com mais de {_AN_MAX_LINHAS} linhas: resuma ou divida.")
            ws = wb.create_sheet(_an_nome_aba(aba.get("nome"), usados))
            _an_topo(ws, titulo or "Análise financeira", _an_sub(cliente), len(cols))
            if (aba.get("notas") or "").strip():
                ws["A3"] = aba["notas"].strip()[:500]
            _an_cabecalho(ws, 4, [c.get("titulo", "") for c in cols])
            fmts = [c.get("formato") if c.get("formato") in _AN_FMT else "texto" for c in cols]
            for i, ln in enumerate(linhas):
                for j, fmt in enumerate(fmts):
                    cel = ws.cell(row=5 + i, column=j + 1, value=_an_valor(ln[j] if j < len(ln) else None, fmt))
                    if fmt != "texto":
                        cel.number_format = _AN_FMT[fmt]
            fim = 4 + len(linhas)
            if aba.get("linha_total") and linhas:
                r = fim + 1
                ws.cell(row=r, column=1, value="Total")
                for j, fmt in enumerate(fmts):
                    if j and fmt in ("moeda", "numero", "inteiro"):
                        L = get_column_letter(j + 1)
                        ws.cell(row=r, column=j + 1, value=f"=SUM({L}5:{L}{fim})").number_format = _AN_FMT[fmt]
                _an_negrito(ws, r, len(cols))
            ws.freeze_panes = "B5"
            if linhas:
                ws.auto_filter.ref = f"A4:{get_column_letter(len(cols))}{fim}"
            _an_larguras(ws, 36, 16, len(cols))
    except _AnErro as e:
        return {"ok": False, "erro": str(e)}
    out = _an_salvar(s, cid, wb, _an_arquivo(_mk_slug(titulo or "Planilha", 30).replace("-", "_") or "Planilha", cliente))
    return {"ok": True, **out, "abas": len(abas), "observacao": "Planilha em 'Arquivos gerados' no chamado."}


# ── Análise horizontal e vertical ─────────────────────────────────────────────

def _an_hv(base_vertical, periodos, contas) -> dict:
    periodos = [str(p) for p in _an_lista(periodos)][:24]
    contas = [c for c in _an_lista(contas) if isinstance(c, dict) and str(c.get("conta") or "").strip()]
    if len(periodos) < 1 or not contas:
        raise _AnErro("Informe os períodos e as contas com os valores.")
    for c in contas:
        if len(_an_lista(c.get("valores"))) != len(periodos):
            raise _AnErro(f"A conta '{c['conta']}' tem {len(_an_lista(c.get('valores')))} valores para {len(periodos)} períodos.")
    alvo = _pr_norm(base_vertical or "")
    base = next((c for c in contas if _pr_norm(c["conta"]) == alvo), None) or contas[0]
    linhas = []
    for c in contas:
        vals = [float(v or 0) for v in c["valores"]]
        av = [round(v / float(b) * 100, 1) if float(b or 0) else None for v, b in zip(vals, base["valores"])]
        ah = [None] + [round((vals[i] / vals[i - 1] - 1) * 100, 1) if vals[i - 1] else None for i in range(1, len(vals))]
        linhas.append({"conta": c["conta"], "valores": vals, "av_pct": av, "ah_pct": ah,
                       "ah_acumulada_pct": round((vals[-1] / vals[0] - 1) * 100, 1) if vals[0] and len(vals) > 1 else None})
    destaques = sorted([l for l in linhas if l["ah_pct"][-1] is not None and l is not None],
                       key=lambda l: -abs(l["ah_pct"][-1]))[:5] if len(periodos) > 1 else []
    return {"periodos": periodos, "base_vertical": base["conta"], "linhas": linhas,
            "maiores_variacoes_ultimo_periodo": [{"conta": l["conta"], "ah_pct": l["ah_pct"][-1]} for l in destaques]}


def _an_excel_hv(r, cliente, titulo):
    from openpyxl.utils import get_column_letter as L
    wb = _an_wb()
    ws = wb.create_sheet("Análise H e V")
    n = len(r["periodos"])
    _an_topo(ws, titulo or "Análise horizontal e vertical", _an_sub(cliente) + f" · base da vertical: {r['base_vertical']}", 1 + 3 * n)
    cab = ["Conta"] + r["periodos"] + [f"AV% {p}" for p in r["periodos"]] + [f"AH% {p}" for p in r["periodos"][1:]]
    _an_cabecalho(ws, 4, cab)
    base_row = 5 + next(i for i, l in enumerate(r["linhas"]) if l["conta"] == r["base_vertical"])
    for i, l in enumerate(r["linhas"]):
        row = 5 + i
        ws.cell(row=row, column=1, value=l["conta"])
        for j, v in enumerate(l["valores"]):
            ws.cell(row=row, column=2 + j, value=v).number_format = _AN_FMT["moeda"]
            col = L(2 + j)
            ws.cell(row=row, column=2 + n + j, value=f"=IF({col}${base_row}=0,\"\",{col}{row}/{col}${base_row})").number_format = _AN_FMT["pct"]
        for j in range(1, n):
            a, b = L(1 + j), L(2 + j)
            ws.cell(row=row, column=2 + 2 * n + j - 1, value=f"=IF({a}{row}=0,\"\",{b}{row}/{a}{row}-1)").number_format = _AN_FMT["pct"]
    _an_negrito(ws, base_row, len(cab))
    ws.freeze_panes = "B5"
    _an_larguras(ws, 36, 14, len(cab))
    return wb


def _an_t_analise_hv(s, cid, cliente, titulo, base_vertical, periodos, contas, gerar_excel):
    try:
        r = _an_hv(base_vertical, periodos, contas)
    except _AnErro as e:
        return {"ok": False, "erro": str(e)}
    if gerar_excel:
        r["excel"] = _an_salvar(s, cid, _an_excel_hv(r, cliente, titulo), _an_arquivo("Analise_HV", cliente))
    return {"ok": True, **r}


# ── Projeção de caixa ─────────────────────────────────────────────────────────

def _an_rotulos(periodicidade, n, inicio):
    out = []
    for p in range(n):
        if periodicidade == "semanal":
            out.append(f"Sem {p + 1} ({(inicio + _td_pr(days=7 * p)).strftime('%d/%m')})")
        else:
            m = inicio.month - 1 + p
            out.append(f"{m % 12 + 1:02d}/{inicio.year + m // 12}")
    return out


def _an_caixa(periodicidade, periodos, saldo_inicial, saldo_minimo, linhas, inicio_em) -> dict:
    per = "semanal" if periodicidade == "semanal" else "mensal"
    n = max(1, min(int(periodos or (13 if per == "semanal" else 12)), 52 if per == "semanal" else 36))
    inicio = _pr_data(inicio_em) if (inicio_em or "").strip() else _pr_hoje()
    if not inicio:
        raise _AnErro("Data de início inválida (DD/MM/AAAA).")
    ls = []
    for l in _an_lista(linhas):
        if not isinstance(l, dict) or not (l.get("descricao") or "").strip():
            continue
        ini = max(1, int(l.get("inicio") or 1))
        fim = int(l.get("fim") or 0)
        ls.append({"descricao": l["descricao"].strip()[:120], "tipo": "saida" if l.get("tipo") == "saida" else "entrada",
                   "valor": float(l.get("valor") or 0), "g": float(l.get("crescimento_pct") or 0) / 100,
                   "inicio": ini, "fim": fim if fim >= ini else 0, "recorrente": bool(l.get("recorrente", True))})
    if not ls:
        raise _AnErro("Informe as linhas de entradas e saídas.")
    ls.sort(key=lambda x: x["tipo"] != "entrada")

    def valor(l, p):
        if l["recorrente"]:
            return l["valor"] * (1 + l["g"]) ** (p - l["inicio"]) if p >= l["inicio"] and (l["fim"] == 0 or p <= l["fim"]) else 0.0
        return l["valor"] if p == l["inicio"] else 0.0
    rot = _an_rotulos(per, n, inicio)
    saldo, tabela, menor, menor_p, negativo = float(saldo_inicial or 0), [], None, None, None
    for p in range(1, n + 1):
        ent = sum(valor(l, p) for l in ls if l["tipo"] == "entrada")
        sai = sum(valor(l, p) for l in ls if l["tipo"] == "saida")
        ini_p = saldo
        saldo = ini_p + ent - sai
        tabela.append({"periodo": rot[p - 1], "saldo_inicial": round(ini_p, 2), "entradas": round(ent, 2), "saidas": round(sai, 2),
                       "saldo_final": round(saldo, 2)})
        if menor is None or saldo < menor:
            menor, menor_p = saldo, rot[p - 1]
        if negativo is None and saldo < 0:
            negativo = rot[p - 1]
    minimo = float(saldo_minimo or 0)
    return {"periodicidade": per, "periodos": n, "inicio": _pr_fmt_data(inicio), "linhas": ls, "rotulos": rot,
            "tabela": tabela, "saldo_inicial": float(saldo_inicial or 0), "saldo_minimo": minimo,
            "menor_saldo": round(menor, 2), "periodo_do_menor_saldo": menor_p, "primeiro_periodo_negativo": negativo,
            "necessidade_de_capital": round(max(0.0, minimo - menor), 2), "saldo_final": round(saldo, 2),
            "total_entradas": round(sum(t["entradas"] for t in tabela), 2), "total_saidas": round(sum(t["saidas"] for t in tabela), 2)}


def _an_excel_caixa(r, cliente, titulo):
    from openpyxl.utils import get_column_letter as L
    wb = _an_wb()
    pr = wb.create_sheet("Premissas")
    _an_topo(pr, "Premissas da projeção", _an_sub(cliente) + " · altere os valores em azul: o fluxo recalcula", 7)
    from openpyxl.styles import Font
    azul = Font(color="1F4E99")
    pr["A3"], pr["B3"] = "Saldo inicial", r["saldo_inicial"]
    pr["D3"], pr["E3"] = "Saldo mínimo desejado", r["saldo_minimo"]
    for ref in ("B3", "E3"):
        pr[ref].number_format, pr[ref].font = _AN_FMT["moeda"], azul
    _an_cabecalho(pr, 4, ["Descrição", "Tipo", "Valor", "Crescimento por período", "Início (nº)", "Fim (nº, 0 = até o fim)",
                          "Recorrente (1/0)"])
    for i, l in enumerate(r["linhas"]):
        row = 5 + i
        for j, v in enumerate([l["descricao"], l["tipo"], l["valor"], l["g"], l["inicio"], l["fim"], 1 if l["recorrente"] else 0]):
            c = pr.cell(row=row, column=j + 1, value=v)
            if j >= 2:
                c.font = azul
        pr.cell(row=row, column=3).number_format = _AN_FMT["moeda"]
        pr.cell(row=row, column=4).number_format = _AN_FMT["pct"]
    _an_larguras(pr, 34, 16, 7)
    fx = wb.create_sheet("Fluxo")
    n = r["periodos"]
    _an_topo(fx, titulo or f"Fluxo de caixa projetado ({r['periodicidade']})", _an_sub(cliente) + f" · início {r['inicio']}", n + 1)
    _an_cabecalho(fx, 4, ["Linha"] + r["rotulos"])
    fx.cell(row=5, column=1, value="Período nº")
    for p in range(1, n + 1):
        fx.cell(row=5, column=1 + p, value=p)
    linha0 = 6
    ents = [i for i, l in enumerate(r["linhas"]) if l["tipo"] == "entrada"]
    sais = [i for i, l in enumerate(r["linhas"]) if l["tipo"] == "saida"]
    for i, l in enumerate(r["linhas"]):
        row, pr_row = linha0 + i, 5 + i
        fx.cell(row=row, column=1, value=("(+) " if l["tipo"] == "entrada" else "(−) ") + l["descricao"])
        for p in range(1, n + 1):
            col = L(1 + p)
            P = f"{col}$5"
            rec = (f"IF(AND({P}>=Premissas!$E${pr_row},OR(Premissas!$F${pr_row}=0,{P}<=Premissas!$F${pr_row})),"
                   f"Premissas!$C${pr_row}*(1+Premissas!$D${pr_row})^({P}-Premissas!$E${pr_row}),0)")
            uni = f"IF({P}=Premissas!$E${pr_row},Premissas!$C${pr_row},0)"
            fx.cell(row=row, column=1 + p, value=f"=IF(Premissas!$G${pr_row}=1,{rec},{uni})").number_format = _AN_FMT["moeda"]
    base = linha0 + len(r["linhas"])
    rot = {"ent": base + 1, "sai": base + 2, "ini": base + 3, "fim": base + 4}
    fx.cell(row=rot["ent"], column=1, value="Total de entradas")
    fx.cell(row=rot["sai"], column=1, value="Total de saídas")
    fx.cell(row=rot["ini"], column=1, value="Saldo inicial")
    fx.cell(row=rot["fim"], column=1, value="Saldo final")
    for p in range(1, n + 1):
        col = L(1 + p)
        soma = lambda idx: "+".join(f"{col}{linha0 + i}" for i in idx) or "0"
        fx.cell(row=rot["ent"], column=1 + p, value=f"={soma(ents)}")
        fx.cell(row=rot["sai"], column=1 + p, value=f"={soma(sais)}")
        fx.cell(row=rot["ini"], column=1 + p, value="=Premissas!$B$3" if p == 1 else f"={L(p)}{rot['fim']}")
        fx.cell(row=rot["fim"], column=1 + p, value=f"={col}{rot['ini']}+{col}{rot['ent']}-{col}{rot['sai']}")
        for k in rot.values():
            fx.cell(row=k, column=1 + p).number_format = _AN_FMT["moeda"]
    _an_negrito(fx, rot["fim"], n + 1)
    ult = L(1 + n)
    fx.cell(row=rot["fim"] + 2, column=1, value="Menor saldo do período")
    fx.cell(row=rot["fim"] + 2, column=2, value=f"=MIN(B{rot['fim']}:{ult}{rot['fim']})").number_format = _AN_FMT["moeda"]
    fx.cell(row=rot["fim"] + 3, column=1, value="Necessidade de capital (para o saldo mínimo)")
    fx.cell(row=rot["fim"] + 3, column=2, value=f"=MAX(0,Premissas!$E$3-B{rot['fim'] + 2})").number_format = _AN_FMT["moeda"]
    fx.freeze_panes = "B6"
    _an_larguras(fx, 38, 14, n + 1)
    return wb


def _an_t_projecao_caixa(s, cid, cliente, titulo, periodicidade, periodos, inicio_em, saldo_inicial, saldo_minimo, linhas,
                         gerar_excel):
    try:
        r = _an_caixa(periodicidade, periodos, saldo_inicial, saldo_minimo, linhas, inicio_em)
    except (_AnErro, TypeError) as e:
        return {"ok": False, "erro": str(e)}
    out = {k: v for k, v in r.items() if k not in ("linhas", "rotulos")}
    if gerar_excel:
        out["excel"] = _an_salvar(s, cid, _an_excel_caixa(r, cliente, titulo), _an_arquivo("Fluxo_projetado", cliente))
    return {"ok": True, **out}


# ── Cenários e ponto de equilíbrio ────────────────────────────────────────────

def _an_cen(receita_base, anos, cenarios) -> dict:
    anos = max(1, min(int(anos or 3), 10))
    rb = float(receita_base or 0)
    if rb <= 0:
        raise _AnErro("Informe a receita base (último ano realizado).")
    cens = [c for c in _an_lista(cenarios) if isinstance(c, dict) and str(c.get("nome") or "").strip()][:5]
    if not cens:
        raise _AnErro("Informe ao menos um cenário.")
    out = []
    for c in cens:
        g, mc = float(c.get("crescimento_pct") or 0) / 100, float(c.get("margem_contribuicao_pct") or 0) / 100
        cf0, gcf = float(c.get("custos_fixos") or 0), float(c.get("crescimento_custos_fixos_pct") or 0) / 100
        dfin, ir = float(c.get("despesas_financeiras") or 0), float(c.get("aliquota_ir_pct") or 0) / 100
        if mc <= 0:
            raise _AnErro(f"Cenário '{c['nome']}': margem de contribuição precisa ser positiva.")
        linhas = []
        for n in range(1, anos + 1):
            rec = rb * (1 + g) ** n
            cf = cf0 * (1 + gcf) ** n
            ebitda = rec * mc - cf
            lair = ebitda - dfin
            imp = max(0.0, lair) * ir
            pe = cf / mc
            linhas.append({"ano": n, "receita": round(rec, 2), "margem_contribuicao": round(rec * mc, 2), "custos_fixos": round(cf, 2),
                           "ebitda": round(ebitda, 2), "despesas_financeiras": round(dfin, 2), "lair": round(lair, 2),
                           "ir": round(imp, 2), "lucro_liquido": round(lair - imp, 2),
                           "margem_liquida_pct": round((lair - imp) / rec * 100, 1),
                           "ponto_equilibrio_receita": round(pe, 2), "margem_seguranca_pct": round((rec - pe) / rec * 100, 1)})
        out.append({"cenario": c["nome"].strip()[:40], "premissas": {"crescimento": g, "margem_contribuicao": mc, "custos_fixos": cf0,
                                                                    "crescimento_custos_fixos": gcf, "despesas_financeiras": dfin,
                                                                    "aliquota_ir": ir}, "anos": linhas})
    return {"receita_base": rb, "anos": anos, "cenarios": out}


def _an_excel_cen(r, cliente, titulo):
    from openpyxl.styles import Font
    from openpyxl.utils import get_column_letter as L
    wb = _an_wb()
    pr = wb.create_sheet("Premissas")
    azul = Font(color="1F4E99")
    _an_topo(pr, "Premissas dos cenários", _an_sub(cliente) + " · altere os valores em azul: a projeção recalcula", 1 + len(r["cenarios"]))
    _an_cabecalho(pr, 4, ["Premissa"] + [c["cenario"] for c in r["cenarios"]])
    campos = [("Receita base (último ano)", None, "moeda"), ("Crescimento da receita ao ano", "crescimento", "pct"),
              ("Margem de contribuição", "margem_contribuicao", "pct"), ("Custos fixos (último ano)", "custos_fixos", "moeda"),
              ("Crescimento dos custos fixos ao ano", "crescimento_custos_fixos", "pct"),
              ("Despesas financeiras ao ano", "despesas_financeiras", "moeda"), ("Alíquota de IR/CSLL", "aliquota_ir", "pct")]
    for i, (rot, k, fmt) in enumerate(campos):
        row = 5 + i
        pr.cell(row=row, column=1, value=rot)
        for j, c in enumerate(r["cenarios"]):
            cel = pr.cell(row=row, column=2 + j, value=r["receita_base"] if k is None else c["premissas"][k])
            cel.number_format, cel.font = _AN_FMT[fmt], azul
    _an_larguras(pr, 38, 18, 1 + len(r["cenarios"]))
    pj = wb.create_sheet("Projeção")
    _an_topo(pj, titulo or "DRE projetada por cenário", _an_sub(cliente), 1 + r["anos"])
    row = 4
    rotulos = ["Receita", "Margem de contribuição", "Custos fixos", "EBITDA", "Despesas financeiras", "Resultado antes do IR",
               "IR/CSLL", "Lucro líquido", "Margem líquida", "Ponto de equilíbrio (receita)", "Margem de segurança"]
    for j, c in enumerate(r["cenarios"]):
        P = lambda lin: f"Premissas!${L(2 + j)}${lin}"
        _an_cabecalho(pj, row, [f"Cenário {c['cenario']}"] + [f"Ano {n}" for n in range(1, r["anos"] + 1)])
        b = row + 1
        for k, rot in enumerate(rotulos):
            pj.cell(row=b + k, column=1, value=rot)
        for n in range(1, r["anos"] + 1):
            col = L(1 + n)
            f = {0: f"={P(5)}*(1+{P(6)})^{n}", 1: f"={col}{b}*{P(7)}", 2: f"={P(8)}*(1+{P(9)})^{n}", 3: f"={col}{b + 1}-{col}{b + 2}",
                 4: f"={P(10)}", 5: f"={col}{b + 3}-{col}{b + 4}", 6: f"=MAX(0,{col}{b + 5})*{P(11)}", 7: f"={col}{b + 5}-{col}{b + 6}",
                 8: f"=IF({col}{b}=0,\"\",{col}{b + 7}/{col}{b})", 9: f"={col}{b + 2}/{P(7)}",
                 10: f"=IF({col}{b}=0,\"\",({col}{b}-{col}{b + 9})/{col}{b})"}
            for k in range(len(rotulos)):
                pj.cell(row=b + k, column=1 + n, value=f[k]).number_format = _AN_FMT["pct" if k in (8, 10) else "moeda"]
        _an_negrito(pj, b + 3, 1 + r["anos"])
        _an_negrito(pj, b + 7, 1 + r["anos"])
        row = b + len(rotulos) + 1
    _an_larguras(pj, 34, 16, 1 + r["anos"])
    return wb


def _an_t_cenarios(s, cid, cliente, titulo, receita_base, anos, cenarios, gerar_excel):
    try:
        r = _an_cen(receita_base, anos, cenarios)
    except (_AnErro, TypeError) as e:
        return {"ok": False, "erro": str(e)}
    if gerar_excel:
        r["excel"] = _an_salvar(s, cid, _an_excel_cen(r, cliente, titulo), _an_arquivo("Cenarios", cliente))
    return {"ok": True, **r}


# ── Amortização ───────────────────────────────────────────────────────────────

def _an_amort(principal, taxa_pct, taxa_periodo, prazo_meses, carencia_meses, sistema) -> dict:
    pv = float(principal or 0)
    n = int(prazo_meses or 0)
    car = max(0, int(carencia_meses or 0))
    if pv <= 0 or not 1 <= n <= 420 or car >= n:
        raise _AnErro("Informe principal, prazo (1 a 420 meses) e carência menor que o prazo.")
    t = float(taxa_pct or 0) / 100
    i = (1 + t) ** (1 / 12) - 1 if taxa_periodo == "anual" else t
    amort_n = n - car
    saldo, linhas = pv, []
    pmt = pv * i / (1 - (1 + i) ** -amort_n) if i else pv / amort_n
    for m in range(1, n + 1):
        juros = saldo * i
        if m <= car:
            amort = 0.0
        elif sistema == "sac":
            amort = pv / amort_n
        else:
            amort = pmt - juros
        amort = min(amort, saldo)
        parcela = juros + amort
        saldo = max(0.0, saldo - amort)
        linhas.append({"mes": m, "parcela": round(parcela, 2), "juros": round(juros, 2), "amortizacao": round(amort, 2),
                       "saldo_devedor": round(saldo, 2)})
    return {"sistema": "SAC" if sistema == "sac" else "Price", "taxa_mensal_pct": round(i * 100, 4),
            "taxa_anual_equivalente_pct": round(((1 + i) ** 12 - 1) * 100, 2), "principal": pv, "prazo_meses": n,
            "carencia_meses": car, "total_pago": round(sum(l["parcela"] for l in linhas), 2), "total_juros": round(sum(l["juros"] for l in linhas), 2),
            "primeira_parcela_apos_carencia": linhas[car]["parcela"], "ultima_parcela": linhas[-1]["parcela"], "tabela": linhas}


def _an_t_amortizacao(s, cid, cliente, principal, taxa_pct, taxa_periodo, prazo_meses, carencia_meses, sistema, gerar_excel):
    try:
        r = _an_amort(principal, taxa_pct, taxa_periodo, prazo_meses, carencia_meses, sistema)
    except _AnErro as e:
        return {"ok": False, "erro": str(e)}
    if gerar_excel:
        wb = _an_wb()
        ws = wb.create_sheet("Amortização")
        _an_topo(ws, f"Tabela {r['sistema']} — {_cm_brl(r['principal'])} em {r['prazo_meses']} meses",
                 _an_sub(cliente) + f" · taxa {r['taxa_mensal_pct']:.4f}% a.m. ({r['taxa_anual_equivalente_pct']:.2f}% a.a.)"
                 + (f" · carência {r['carencia_meses']} meses (só juros)" if r["carencia_meses"] else ""), 5)
        _an_cabecalho(ws, 4, ["Mês", "Parcela", "Juros", "Amortização", "Saldo devedor"])
        for k, l in enumerate(r["tabela"]):
            for j, v in enumerate([l["mes"], l["parcela"], l["juros"], l["amortizacao"], l["saldo_devedor"]]):
                ws.cell(row=5 + k, column=1 + j, value=v).number_format = _AN_FMT["inteiro" if j == 0 else "moeda"]
        fim = 4 + len(r["tabela"])
        ws.cell(row=fim + 1, column=1, value="Total")
        for j, L_ in enumerate("BCD"):
            ws.cell(row=fim + 1, column=2 + j, value=f"=SUM({L_}5:{L_}{fim})").number_format = _AN_FMT["moeda"]
        _an_negrito(ws, fim + 1, 5)
        ws.freeze_panes = "A5"
        _an_larguras(ws, 8, 18, 5)
        r["excel"] = _an_salvar(s, cid, wb, _an_arquivo(f"Amortizacao_{r['sistema']}", cliente))
    tabela = r.pop("tabela")
    r["primeiros_meses"] = tabela[:max(3, r["carencia_meses"] + 2)]
    return {"ok": True, **r}


# ── Registro ──────────────────────────────────────────────────────────────────

_AN_S = {"type": "string"}
_AN_N = {"type": "number"}
_AN_FMTS = ["texto", "moeda", "numero", "inteiro", "pct", "data"]
_AN_FERRAMENTAS = {
    "an_gerar_excel": {
        "fn": _an_t_gerar_excel, "rotulo": "Gerou a planilha em Excel",
        "description": "Gera uma planilha Excel no padrão M. Capital, em abas, com cabeçalho, formatos (moeda, %, data...), "
                       "linha de total e FÓRMULAS (células que começam com '=', em inglês e com vírgula: =SUM(B5:B9), "
                       "=B5/B$12). Números: '1234.56' ou '1.234,56'; porcentagem: 12.5 = 12,5%. Use para DRE "
                       "reclassificada, balancete extraído, comparativos, listas.",
        "props": {"cliente": _AN_S, "titulo": _AN_S,
                  "abas": {"type": "array", "items": {
                      "type": "object", "additionalProperties": False, "required": ["nome", "colunas", "linhas", "linha_total", "notas"],
                      "properties": {"nome": _AN_S, "notas": {"type": "string", "description": "Fonte e observações (vai no topo)."},
                                     "colunas": {"type": "array", "items": {
                                         "type": "object", "additionalProperties": False, "required": ["titulo", "formato"],
                                         "properties": {"titulo": _AN_S, "formato": {"type": "string", "enum": _AN_FMTS}}}},
                                     "linhas": {"type": "array", "items": {"type": "array", "items": _AN_S}},
                                     "linha_total": {"type": "boolean"}}}}}},
    "an_analise_hv": {
        "fn": _an_t_analise_hv, "rotulo": "Fez a análise horizontal e vertical",
        "description": "Análise horizontal (variação entre períodos) e vertical (% da conta base, ex.: Receita líquida ou "
                       "Ativo total) de DRE ou balanço, com as maiores variações; opcionalmente em Excel com fórmulas.",
        "props": {"cliente": _AN_S, "titulo": _AN_S, "base_vertical": {"type": "string", "description": "Nome da conta base."},
                  "periodos": {"type": "array", "items": _AN_S},
                  "contas": {"type": "array", "items": {"type": "object", "additionalProperties": False, "required": ["conta", "valores"],
                                                        "properties": {"conta": _AN_S, "valores": {"type": "array", "items": _AN_N}}}},
                  "gerar_excel": {"type": "boolean"}}},
    "an_projecao_caixa": {
        "fn": _an_t_projecao_caixa, "rotulo": "Projetou o fluxo de caixa",
        "description": "Fluxo de caixa projetado (semanal, ex.: 13 semanas, ou mensal): saldo por período, menor saldo, "
                       "primeiro período negativo e necessidade de capital para manter o saldo mínimo. Linhas recorrentes "
                       "(com crescimento por período) ou pontuais. Excel com premissas editáveis e fórmulas.",
        "props": {"cliente": _AN_S, "titulo": _AN_S, "periodicidade": {"type": "string", "enum": ["semanal", "mensal"]},
                  "periodos": {"type": "integer", "description": "Semanal até 52 (padrão 13); mensal até 36 (padrão 12)."},
                  "inicio_em": {"type": "string", "description": "DD/MM/AAAA (vazio = hoje)."},
                  "saldo_inicial": _AN_N, "saldo_minimo": _AN_N,
                  "linhas": {"type": "array", "items": {
                      "type": "object", "additionalProperties": False,
                      "required": ["descricao", "tipo", "valor", "crescimento_pct", "inicio", "fim", "recorrente"],
                      "properties": {"descricao": _AN_S, "tipo": {"type": "string", "enum": ["entrada", "saida"]}, "valor": _AN_N,
                                     "crescimento_pct": {"type": "number", "description": "% por período (0 = fixo)."},
                                     "inicio": {"type": "integer", "description": "Período em que começa (1 = primeiro)."},
                                     "fim": {"type": "integer", "description": "Último período (0 = até o fim)."},
                                     "recorrente": {"type": "boolean", "description": "false = só no período de início."}}}},
                  "gerar_excel": {"type": "boolean"}}},
    "an_cenarios": {
        "fn": _an_t_cenarios, "rotulo": "Projetou os cenários",
        "description": "DRE projetada por cenário (até 5, até 10 anos) a partir da receita base: receita, margem de "
                       "contribuição, custos fixos, EBITDA, despesas financeiras, IR, lucro, ponto de equilíbrio e margem "
                       "de segurança. Excel com premissas editáveis e fórmulas.",
        "props": {"cliente": _AN_S, "titulo": _AN_S, "receita_base": {"type": "number", "description": "Receita do último ano."},
                  "anos": {"type": "integer"},
                  "cenarios": {"type": "array", "items": {
                      "type": "object", "additionalProperties": False,
                      "required": ["nome", "crescimento_pct", "margem_contribuicao_pct", "custos_fixos", "crescimento_custos_fixos_pct",
                                   "despesas_financeiras", "aliquota_ir_pct"],
                      "properties": {"nome": _AN_S, "crescimento_pct": _AN_N, "margem_contribuicao_pct": _AN_N,
                                     "custos_fixos": {"type": "number", "description": "Do último ano."},
                                     "crescimento_custos_fixos_pct": _AN_N, "despesas_financeiras": {"type": "number", "description": "Ao ano."},
                                     "aliquota_ir_pct": _AN_N}}},
                  "gerar_excel": {"type": "boolean"}}},
    "an_amortizacao": {
        "fn": _an_t_amortizacao, "rotulo": "Montou a tabela de amortização",
        "description": "Tabela de amortização Price ou SAC com carência (só juros), taxa mensal ou anual: parcelas, juros, "
                       "saldo devedor e totais; opcionalmente em Excel.",
        "props": {"cliente": _AN_S, "principal": _AN_N, "taxa_pct": _AN_N,
                  "taxa_periodo": {"type": "string", "enum": ["mensal", "anual"]}, "prazo_meses": {"type": "integer"},
                  "carencia_meses": {"type": "integer"}, "sistema": {"type": "string", "enum": ["price", "sac"]},
                  "gerar_excel": {"type": "boolean"}}},
}

for _nome_an, _spec_an in _AN_FERRAMENTAS.items():
    _pr_registrar_ferramenta(_nome_an, _spec_an)

_AN_TODAS = list(_AN_FERRAMENTAS)
_ag_an = _PREDIO_AGENTES.get("analista_financeiro")
if _ag_an:
    _ag_an.update(
        web=True,
        atribuicoes="Analisa DRE, balanço, balancetes e fluxo de caixa do cliente com indicadores calculados; faz análise "
                    "horizontal e vertical, projeção de caixa, cenários, ponto de equilíbrio e amortização, e entrega em "
                    "Excel (com fórmulas) ou Word.",
        ferramentas=list(dict.fromkeys(_ag_an["ferramentas"] + _AN_TODAS + ["val_calcular", "cred_simular"])))
    _ag_an["ferramentas"] = [f for f in _ag_an["ferramentas"] if f in _PR_TOOLS]
    _PR_INSTRUCOES["analista_financeiro"] = _PR_INSTRUCOES.get("analista_financeiro", "") + (
        "\n\nANÁLISES E PLANILHAS\n"
        "- Análise horizontal e vertical: an_analise_hv (base da vertical = Receita líquida na DRE, Ativo total no balanço).\n"
        "- Caixa: para 'o caixa aguenta?', projete com an_projecao_caixa (13 semanas para aperto de curto prazo, 12 meses "
        "para planejamento). Monte as linhas a partir do fluxo realizado (fc_resumo), contas a receber e a pagar e do que "
        "o sócio contar; diga o menor saldo, quando fica negativo e quanto capital falta.\n"
        "- Cenários: an_cenarios com base, otimista e pessimista, premissas explícitas e justificadas a partir do "
        "histórico; destaque ponto de equilíbrio e margem de segurança.\n"
        "- Dívidas do cliente: an_amortizacao para uma operação; cred_simular para comparar alternativas com CET.\n"
        "- Excel: quando o sócio pedir planilha, ou quando a entrega for para o cliente mexer, use gerar_excel = true nas "
        "calculadoras (o Excel sai com premissas editáveis e fórmulas). Para outras tabelas (DRE reclassificada, "
        "balancete extraído, comparativos), use an_gerar_excel e prefira fórmulas a números digitados para totais e "
        "percentuais. Toda planilha diz a fonte dos números nas notas.\n"
        "- Mercado (Selic, IPCA, margens típicas do setor): pesquise na web e cite a fonte.\n"
        "- Os arquivos ficam em 'Arquivos gerados' no chamado: diga ao sócio o que tem em cada aba.")

for _key_an in ("orcamento_bsc", "relatorio_mensal"):
    _ag_x = _PREDIO_AGENTES.get(_key_an)
    if _ag_x and "an_gerar_excel" not in _ag_x["ferramentas"]:
        _ag_x["ferramentas"] = _ag_x["ferramentas"] + ["an_gerar_excel", "an_analise_hv"]
        _PR_INSTRUCOES[_key_an] = _PR_INSTRUCOES.get(_key_an, "") + (
            "\n- Quando pedido, entregue também as tabelas em Excel com an_gerar_excel (fórmulas para totais e variações).")

print("[predio_analista] Analista Financeiro com Excel, projeções e cenários carregado.")

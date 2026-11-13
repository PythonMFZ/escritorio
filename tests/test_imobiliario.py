"""4º andar — Imobiliário: estudos e motor de viabilidade, mapa de vendas e obras por valor agregado."""
import json
import os
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _base import preparar, check, fim, criar_empresa  # noqa: E402

A, c = preparar()
from sqlmodel import Session  # noqa: E402
cid, us = criar_empresa(A)
hoje = date.today()
PREM = {"nome_projeto": "Residencial Alfa", "area_terreno": 1200, "indice_aproveitamento": 4, "valor_terreno": 3000000,
        "preco_m2_base": 11000, "cub_m2": 3000, "duracao_obra": 30, "mes_inicio_obra": 6, "mes_inicio_vendas": 1,
        "tipologias": [{"nome": "2D", "tipo": "Residencial", "metragem": 70, "quantidade": 24, "andar_inicio": 2},
                       {"nome": "3D", "tipo": "Residencial", "metragem": 95, "quantidade": 12, "andar_inicio": 2}]}
with Session(A.engine) as s:
    cl = A.Client(company_id=cid, name="Construtora Alfa"); s.add(cl); s.commit(); s.refresh(cl); CL = cl.id
    res = A._calcular_viabilidade_v2(dict(PREM))
    est = A.EstudoViabilidade(company_id=cid, client_id=CL, nome_projeto="Residencial Alfa", dados_input_json=json.dumps(PREM),
                              resultado_realista_json=json.dumps({k: v for k, v in res.items() if not isinstance(v, (list,))}, default=str),
                              share_token="t1")
    s.add(est)
    emp = A.Empreendimento(company_id=cid, client_id=CL, nome="Residencial Alfa", estudo_id=None); s.add(emp); s.commit(); s.refresh(emp)
    us_ = []
    for i in range(10):
        u = A.UnidadeEmpreendimento(empreendimento_id=emp.id, tipologia_nome="2D", numero=str(101 + i), andar=1 + i // 2,
                                    metragem=70, valor_vgv_projetado=770000, permuta=(i == 9),
                                    status="vendida" if i < 4 else "disponivel")
        s.add(u); s.commit(); s.refresh(u); us_.append(u)
    for i in range(4):
        s.add(A.VendaUnidade(unidade_id=us_[i].id, empreendimento_id=emp.id, comprador_nome=f"C{i}",
                             data_venda=(hoje - timedelta(days=30 * i)).isoformat(), valor_total=700000, status="ativa"))
    ob = A.Obra(company_id=cid, client_id=CL, nome="Obra Alfa", orcamento_total=1000000,
                data_inicio=(hoje - timedelta(days=200)).isoformat(), data_fim=(hoje + timedelta(days=200)).isoformat())
    s.add(ob); s.commit(); s.refresh(ob)
    f1 = A.ObraFase(obra_id=ob.id, nome="Estrutura", ordem=1, orcado_rs=600000); s.add(f1); s.commit(); s.refresh(f1)
    e1 = A.ObraEtapa(fase_id=f1.id, obra_id=ob.id, descricao="Fundação", orcado_rs=300000,
                     data_inicio=(hoje - timedelta(days=200)).isoformat(), data_fim=(hoje - timedelta(days=100)).isoformat())
    e2 = A.ObraEtapa(fase_id=f1.id, obra_id=ob.id, descricao="Lajes", orcado_rs=300000,
                     data_inicio=(hoje - timedelta(days=100)).isoformat(), data_fim=(hoje + timedelta(days=100)).isoformat())
    s.add(e1); s.add(e2); s.commit(); s.refresh(e1); s.refresh(e2)
    s.add(A.ObraApontamento(etapa_id=e1.id, obra_id=ob.id, data=hoje.isoformat(), fisico_pct=100, financeiro_rs=380000))
    s.add(A.ObraApontamento(etapa_id=e2.id, obra_id=ob.id, data=hoje.isoformat(), fisico_pct=20, financeiro_rs=60000))
    s.commit()
    EST, EMP, OB = est.id, emp.id, ob.id

print("[1] Viabilidade")
with Session(A.engine) as s:
    lst = A._im_t_estudos(s, cid, "Construtora Alfa")
    check(lst["total"] == 1 and lst["estudos"][0]["realista"]["vgv_bruto"] == res["vgv_bruto"], "estudos com o resumo do resultado")
    d = A._im_t_estudo(s, cid, EST, "estudo")
    check(d["premissas"]["area_terreno"] == 1200 and d["realista"]["margem_vgv"] == res["margem_vgv"], "premissas e resultado do estudo")
    r = A._im_t_calcular(s, cid, PREM, True)
    check(r["ok"] and r["resultado"]["vgv_bruto"] == res["vgv_bruto"] and r["resultado"]["status"], "motor dá o mesmo resultado da ferramenta")
    g = r["sensibilidade_preco_x_custo"]
    base = next(x for x in g[1]["por_variacao_custo"] if x["variacao_custo_pct"] == 0)
    pior = next(x for x in g[0]["por_variacao_custo"] if x["variacao_custo_pct"] == 10)
    check(len(g) == 3 and base["margem_vgv"] == res["margem_vgv"] and pior["margem_vgv"] < base["margem_vgv"],
          "sensibilidade 3x3: preço -10% e custo +10% derrubam a margem")
    check(not A._im_t_calcular(s, cid, {"area_terreno": 0}, False)["ok"], "premissas incompletas recusadas")

print("[2] Produto e vendas")
with Session(A.engine) as s:
    e = A._im_t_empreendimentos(s, cid, "")["empreendimentos"][0]
    check(e["unidades"] == 10 and e["permuta"] == 1 and e["por_status"]["vendida"] == 4, "unidades por status e permuta")
    check(e["valor_vendido"] == 2800000 and e["pct_vgv_vendido"] == round(2800000 / (770000 * 9) * 100, 1), "% do VGV vendido (sem permuta)")
    check(e["desconto_medio_sobre_tabela_pct"] == round((1 - 2800000 / 3080000) * 100, 1) and e["preco_m2_medio_vendido"] == 10000.0,
          "desconto sobre tabela e preço médio/m²")
    check(e["ritmo_vendas_mes"] == round(4 / 6, 2) and e["meses_de_estoque"] == round(5 / (4 / 6), 1), "ritmo e meses de estoque")
    u = A._im_t_unidades(s, cid, EMP)
    check(u["total"] == 10 and u["unidades"][0]["vendido_por"] == 700000, "mapa de unidades com valor de venda")

print("[3] Obras")
with Session(A.engine) as s:
    o = A._im_t_obras(s, cid, "Construtora Alfa")["obras"][0]
    check(o["BAC"] == 600000 and o["AC"] == 440000 and o["EV"] == 360000 and o["IDC"] < 1, "valor agregado: IDC < 1 (gasto acima do executado)")
    d = A._im_t_obra(s, cid, OB)
    check(d["etapas_acima_do_custo"][0]["descricao"] == "Fundação" and d["etapas_acima_do_custo"][0]["estouro"] == 80000,
          "etapa que estoura o custo")
    check(any(x["descricao"] == "Lajes" for x in d["etapas_atrasadas"]), "etapa atrasada")
    check("erro" in A._im_t_obra(s, cid, 9999), "obra inexistente")

print("[4] Agentes")
for k in ("viabilidade", "produto_vendas", "obras"):
    ag = A._PREDIO_AGENTES[k]
    check(ag["ativo"] and all(f in A._PR_TOOLS for f in ag["ferramentas"]) and k in A._PR_INSTRUCOES, f"{k} ativo")
check(all(a["ativo"] for a in next(x for x in A._PREDIO_ANDARES if x["key"] == "imobiliario")["agentes"]), "4º andar completo")
check(A._pr_perfil("viabilidade", cid) == ("claude-opus-5-5", "high") and A._pr_perfil("obras", cid)[0] == "claude-sonnet-5-5",
      "modelo por agente")
fim()

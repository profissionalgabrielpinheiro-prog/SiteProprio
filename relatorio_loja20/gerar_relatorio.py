"""Gera o relatório HTML dinâmico da Loja 20 (venda x pesquisa x economia).

Uso:  python gerar_relatorio.py
Lê a tabela de cupons ("cupom - 20.csv", uma linha por cupom x produto), o cadastro de produtos
("produtos.csv") e a pesquisa de preços (1067), recalcula tudo em Python (conferindo com o modelo)
e grava `Relatorio Loja 20.html` (arquivo único, sem dependências externas).
"""
import base64
import hashlib
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

AQUI = Path(__file__).resolve().parent
BASE = AQUI.parent
CSV_CUPONS = BASE / "cupom - 20.csv"          # id_cupom, dia, codigo_pdv, id_produto, qtd_vendida, preco_total
CSV_PRODUTOS = BASE / "produtos.csv"          # id_produto, produto, setor, categoria (do dim_produto do modelo)
CSV_PESQ = BASE / "1067 - Loja 20 1 a 12" / "tmp" / "1067 - Loja 20.csv"
SAIDA = AQUI / "Relatorio Loja 20.html"

# Alto giro (proporcional ao período): vendeu em pelo menos metade dos dias E em pelo menos 0,1% dos cupons.
PCT_DIAS, PCT_CUPONS = 0.5, 0.001

# tipos de preço da pesquisa considerados (filtro do Power BI)
TIPOS_VALIDOS = ["1-PRECO REGULAR", "6-PONTO EXTRA"]

# Valores calculados pelas medidas do Power BI (tabela _Medidas), para conferir com o Python.
# Ficam num arquivo LOCAL (fora do Git, pois são totais de venda). Sem o arquivo, a conferência é omitida.
_MODELO_JSON = AQUI / "validacao_modelo.json"
MODELO = json.loads(_MODELO_JSON.read_text(encoding="utf-8")) if _MODELO_JSON.exists() else {}


def ler_cupons() -> pd.DataFrame:
    c = pd.read_csv(CSV_CUPONS, dtype={"id_cupom": str, "codigo_pdv": str, "id_produto": int})
    c = c.rename(columns={"id_cupom": "CUPOM", "codigo_pdv": "PDV", "qtd_vendida": "QTD", "preco_total": "Vlr",
                          "id_produto": "id"})
    c["data"] = pd.to_datetime(c["dia"], format="%Y-%m-%d")
    prod = pd.read_csv(CSV_PRODUTOS, dtype={"id_produto": int}).rename(
        columns={"id_produto": "id", "produto": "nome"}).drop_duplicates("id")
    c = c.merge(prod, on="id", how="left")
    for col, padrao in (("nome", "(produto sem cadastro)"), ("setor", "SEM SETOR"), ("categoria", "SEM CATEGORIA")):
        c[col] = c[col].fillna(padrao)
    return c


def ler_pesquisa() -> pd.DataFrame:
    p = pd.read_csv(CSV_PESQ, sep="|", dtype=str, encoding="cp1252")  # ponto decimal neste arquivo
    p["id"] = p["PRODUTO"].str.split(" - ", n=1).str[0].astype(int)
    for n in ["Vlr. Varejo PDV", "Vlr. Atacado PDV", "Vlr.Vare.Conc", "Vlr.Atac.Conc.", "CustoMedio"]:
        p[n] = p[n].astype(float)
    p["dt"] = pd.to_datetime(p["PESQUISADATA"], dayfirst=True)
    p["conc"] = p["EMPRESACONCORRENTE"].str.split(" - ", n=1).str[1]
    # mesmo filtro aplicado no Power BI: só preço regular e ponto extra
    p = p[p["Tipo"].isin(TIPOS_VALIDOS)].copy()
    p["tipo"] = p["Tipo"].str.split("-", n=1).str[1].str.strip()
    return p


def _num(x: float):
    """Número enxuto para o JSON (inteiro quando possível)."""
    return int(x) if float(x).is_integer() else x


def main() -> None:
    c = ler_cupons()
    p = ler_pesquisa()
    n_cupons, n_dias = c["CUPOM"].nunique(), c["data"].nunique()
    min_dias, min_cupons = math.ceil(PCT_DIAS * n_dias), math.ceil(PCT_CUPONS * n_cupons)

    # ---------- produtos (lado venda) ----------
    ok = c[c["QTD"] > 0]
    g = c.groupby("id").agg(nome=("nome", "first"), setor=("setor", "first"), categoria=("categoria", "first"),
                            cupons=("CUPOM", "nunique"), dias=("data", "nunique"),
                            valor=("Vlr", "sum")).reset_index()
    g = g.merge(ok.groupby("id")["QTD"].sum().rename("unid"), on="id", how="left").fillna({"unid": 0})
    g["alto"] = ((g["dias"] >= min_dias) & (g["cupons"] >= min_cupons)).astype(int)

    # ---------- referência Mateus na pesquisa (última data de cada produto) ----------
    ult = p.groupby("id")["dt"].transform("max")
    ref = p[p["dt"] == ult].groupby("id").agg(pdv_var=("Vlr. Varejo PDV", "median"),
                                              pdv_atac=("Vlr. Atacado PDV", "median"),
                                              custo=("CustoMedio", "median"), ult=("dt", "max"))
    g = g.merge(ref, on="id", how="left")
    g["fora"] = g["pdv_var"].isna().astype(int)

    # ---------- preço por produto x concorrente (última data de cada par) ----------
    ult_pc = p.groupby(["id", "conc"])["dt"].transform("max")
    pc = p[p["dt"] == ult_pc].groupby(["id", "conc"]).agg(
        var=("Vlr.Vare.Conc", "median"), atac=("Vlr.Atac.Conc.", "median"),
        tipo=("tipo", lambda s: s.mode().iat[0]), dt=("dt", "max")).reset_index()
    concs = sorted(pc["conc"].unique())
    tipos = sorted(pc["tipo"].unique())
    idx = {pid: i for i, pid in enumerate(g["id"])}

    # ---------- linhas de venda (todas; as sem pesquisa ficam sem preço de referência) ----------
    L = ok.merge(ref[["pdv_var", "pdv_atac"]], left_on="id", right_index=True, how="left")
    L["preco"] = L["Vlr"] / L["QTD"]
    # "tier atacado": a linha foi vendida pelo preço de atacado (e atacado < varejo)
    L["tier"] = ((L["pdv_atac"] < L["pdv_var"]) & (L["preco"] <= L["pdv_atac"] * 1.005)).astype(int)
    cup = c.groupby("CUPOM").agg(dia=("data", "min"), pdv=("PDV", "first"), itens=("id", "size"),
                                 valor=("Vlr", "sum")).reset_index().sort_values(["dia", "CUPOM"], kind="stable")
    cix = {k: i for i, k in enumerate(cup["CUPOM"])}
    L["ci"] = L["CUPOM"].map(cix)
    L = L.sort_values("ci", kind="stable")                      # linhas agrupadas por cupom (sem coluna de cupom)
    nl = L.groupby("ci").size().reindex(range(len(cup)), fill_value=0)
    dias = sorted(c["data"].unique())
    dia_idx = {d: i for i, d in enumerate(dias)}
    cupons = {"id": [int(x) for x in cup["CUPOM"]], "d": [dia_idx[d] for d in cup["dia"]],
              "pdv": [int(x) for x in cup["pdv"]], "it": cup["itens"].astype(int).tolist(),
              "v": np.rint(cup["valor"].to_numpy() * 100).astype(np.int64).tolist(), "n": nl.astype(int).tolist()}
    linhas = {"p": L["id"].map(idx).astype(int).tolist(),
              "q": [_num(x) for x in np.round(L["QTD"].to_numpy(), 3)],
              "v": np.rint(L["Vlr"].to_numpy() * 100).astype(np.int64).tolist(),
              "t": L["tier"].astype(int).tolist()}

    # ---------- conferência com o modelo ----------
    dentro = int((g["fora"] == 0).sum())
    py = {"Qtd Cupons": n_cupons, "Produtos Vendidos": len(g), "Produtos Vendidos Dentro Pesquisa": dentro,
          "Produtos Vendidos Fora Pesquisa": len(g) - dentro, "Unidades Vendidas": round(float(ok["QTD"].sum()), 2),
          "Valor Vendido": round(float(c["Vlr"].sum()), 2),
          "Valor Dentro Pesquisa": round(float(g.loc[g["fora"] == 0, "valor"].sum()), 2)}
    validacao = [{"medida": k, "modelo": MODELO[k], "python": py[k], "ok": abs(MODELO[k] - py[k]) < 0.05}
                 for k in MODELO]

    # ---------- perfil dos dados ----------
    q0 = c[c["QTD"] <= 0]
    dup = int(c.duplicated(["CUPOM", "id"]).sum())
    Lr = L[L["pdv_var"] > 0]
    razao = (Lr["preco"] / Lr["pdv_var"])
    # compatibilidade: preço do concorrente x preço do PDV Mateus (faixa padrão ±50%)
    pcx = pc[pc["var"] > 0].merge(ref[["pdv_var"]], left_on="id", right_index=True)
    pcx = pcx[pcx["pdv_var"] > 0]
    inc = (pcx["var"] / pcx["pdv_var"] - 1).abs() > 0.5
    perfil = {
        "cupons": {"linhas": len(c), "cupons": n_cupons, "produtos": len(g), "lojas": int(c["id_filial"].nunique()),
                   "pdvs": int(c["PDV"].nunique()), "dias": n_dias,
                   "de": f"{c['data'].min():%d/%m/%Y}", "ate": f"{c['data'].max():%d/%m/%Y}",
                   "duplicados_cupom_produto": dup, "qtd_zero": len(q0), "qtd_zero_valor": round(float(q0["Vlr"].sum()), 2),
                   "nulos_id_produto": int(c["id"].isna().sum()), "loja": p["FILIAL"].iat[0],
                   "sem_cadastro": int((c["nome"] == "(produto sem cadastro)").sum())},
        "pesquisa": {"linhas": len(p), "produtos": int(p["id"].nunique()), "concorrentes": len(concs),
                     "filiais_concorrentes": int(p["FILIALCONCORRENTE"].nunique()), "datas": int(p["dt"].nunique()),
                     "de": f"{p['dt'].min():%d/%m/%Y}", "ate": f"{p['dt'].max():%d/%m/%Y}",
                     "valores_pesquisa": sorted(p["PESQUISA"].unique().tolist())},
        "concorrentes": [{"nome": k, "produtos": int(v)} for k, v in
                         p.groupby("conc")["id"].nunique().sort_values(ascending=False).items()],
        "tipos": [{"nome": k, "linhas": int(v)} for k, v in p["tipo"].value_counts().items()],
        "precos": {"cupom_sobre_pdv_mediana": round(float(razao.median()), 3),
                   "linhas_comparaveis": int(len(razao)),
                   "linhas_fora_50pct": int(((razao < 0.5) | (razao > 1.5)).sum()),
                   "produtos_pdv_igual_atacado": int((g["pdv_var"] == g["pdv_atac"]).sum()),
                   "conc_precos": int(len(pcx)), "conc_incompativeis": int(inc.sum()),
                   "conc_zerados": int((pc["var"] <= 0).sum()),
                   "linhas_tier_atacado": int(L["tier"].sum())},
        "cobertura_pesquisa_dias": [{"data": f"{k:%d/%m}", "linhas": int(v)}
                                    for k, v in p.groupby("dt").size().items()],
    }

    cfg = {"min_dias": min_dias, "min_cupons": min_cupons}
    produtos = [[int(r.id), r.nome, r.setor, r.categoria, int(r.cupons), int(r.dias), _num(round(float(r.unid), 3)),
                 round(float(r.valor), 2), int(r.fora), int(r.alto),
                 None if pd.isna(r.pdv_var) else round(float(r.pdv_var), 2),
                 None if pd.isna(r.pdv_atac) else round(float(r.pdv_atac), 2),
                 None if pd.isna(r.custo) else round(float(r.custo), 2)] for r in g.itertuples()]
    pcl = [[idx[r.id], concs.index(r.conc), round(float(r.var), 2), round(float(r.atac), 2),
            tipos.index(r.tipo), f"{r.dt:%d/%m}"] for r in pc.itertuples() if r.id in idx]

    dados = {"gerado": pd.Timestamp.now().strftime("%d/%m/%Y %H:%M"), "cfg": cfg, "perfil": perfil,
             "validacao": validacao, "concs": concs, "tipos": tipos, "produtos": produtos, "pc": pcl,
             "dias": [f"{pd.Timestamp(d):%d/%m}" for d in dias], "linhas": linhas, "cupons": cupons}
    js = json.dumps(dados, ensure_ascii=False, separators=(",", ":"))
    js = js.replace("<", "\\u003c").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")

    tpl = (AQUI / "template.html").read_text(encoding="utf-8")
    ini = tpl.index("<script>") + len("<script>")
    fim = tpl.index("</script>", ini)
    sha = base64.b64encode(hashlib.sha256(tpl[ini:fim].encode("utf-8")).digest()).decode()
    csp = f"default-src 'none'; style-src 'unsafe-inline'; script-src 'sha256-{sha}'; img-src data:; base-uri 'none'; form-action 'none'"
    html = tpl.replace("__CSP__", csp).replace("__DADOS__", js)
    SAIDA.write_text(html, encoding="utf-8")
    print("ok:", SAIDA, f"{SAIDA.stat().st_size/1024:.0f} KB")
    for v in validacao:
        print(("OK   " if v["ok"] else "DIVERGE"), v["medida"], v["modelo"], v["python"])


if __name__ == "__main__":
    main()

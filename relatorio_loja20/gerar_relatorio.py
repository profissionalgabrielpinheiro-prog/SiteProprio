"""Gera o relatório HTML dinâmico da Loja 20 (venda x pesquisa x economia).

Uso:  python gerar_relatorio.py
Lê os CSVs exportados do Power BI, recalcula tudo em Python (conferindo com o modelo)
e grava `Relatorio Loja 20.html` (arquivo único, sem dependências externas).
"""
import base64
import hashlib
import json
from pathlib import Path

import pandas as pd

AQUI = Path(__file__).resolve().parent
BASE = AQUI.parent
CSV_CUPONS = BASE / "561 - Cupons" / "tmp" / "561 - Cupons.csv"
CSV_PESQ = BASE / "1067 - Loja 20 1 a 12" / "tmp" / "1067 - Loja 20.csv"
SAIDA = AQUI / "Relatorio Loja 20.html"

# critério de alto giro (mesmo da planilha Produtos Alto Giro.xlsx)
MIN_DIAS, MIN_CUPONS = 5, 6

# Valores calculados pelas medidas do Power BI (tabela _Medidas), para conferir com o Python.
# Ficam num arquivo LOCAL (fora do Git, pois são totais de venda). Sem o arquivo, a conferência é omitida.
_MODELO_JSON = AQUI / "validacao_modelo.json"
MODELO = json.loads(_MODELO_JSON.read_text(encoding="utf-8")) if _MODELO_JSON.exists() else {}


def ler_cupons() -> pd.DataFrame:
    c = pd.read_csv(CSV_CUPONS, sep="|", dtype=str, encoding="cp1252")
    c["QTD"] = c["QTD"].str.replace(".", "", regex=False).astype(int)
    c["Vlr"] = c["VlrVenda"].str.replace(".", "", regex=False).str.replace(",", ".", regex=False).astype(float)
    c["id"] = c["PRODUTO"].str.split(" - ", n=1).str[0].astype(int)
    c["nome"] = c["PRODUTO"].str.split(" - ", n=1).str[1]
    c["data"] = pd.to_datetime(c["DIA"].str.split(" - ", n=1).str[1], format="%d/%m/%Y")
    c["setor"] = c["SETOR"].str.split(" - ", n=1).str[1].fillna(c["SETOR"])
    c["categoria"] = c["CATEGORIA"].str.split(" - ", n=1).str[1].fillna(c["CATEGORIA"])
    return c


def ler_pesquisa() -> pd.DataFrame:
    p = pd.read_csv(CSV_PESQ, sep="|", dtype=str, encoding="cp1252")  # ponto decimal neste arquivo
    p["id"] = p["PRODUTO"].str.split(" - ", n=1).str[0].astype(int)
    for n in ["Vlr. Varejo PDV", "Vlr. Atacado PDV", "Vlr.Vare.Conc", "Vlr.Atac.Conc.", "CustoMedio"]:
        p[n] = p[n].astype(float)
    p["dt"] = pd.to_datetime(p["PESQUISADATA"], dayfirst=True)
    p["conc"] = p["EMPRESACONCORRENTE"].str.split(" - ", n=1).str[1]
    p["tipo"] = p["Tipo"].str.split("-", n=1).str[1].str.strip().fillna("SEM TIPO")
    return p


def main() -> None:
    c = ler_cupons()
    p = ler_pesquisa()
    n_cupons, n_dias = c["CUPOM"].nunique(), c["data"].nunique()

    # ---------- produtos (lado venda) ----------
    ok = c[c["QTD"] > 0]
    g = c.groupby("id").agg(nome=("nome", "first"), setor=("setor", "first"), categoria=("categoria", "first"),
                            cupons=("CUPOM", "nunique"), dias=("data", "nunique"),
                            valor=("Vlr", "sum")).reset_index()
    g = g.merge(ok.groupby("id")["QTD"].sum().rename("unid"), on="id", how="left").fillna({"unid": 0})
    g["alto"] = ((g["dias"] >= MIN_DIAS) & (g["cupons"] >= MIN_CUPONS)).astype(int)

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

    # ---------- linhas de venda para a simulação ----------
    L = ok[ok["id"].isin(ref.index)].copy()
    L = L.merge(ref[["pdv_var", "pdv_atac"]], left_on="id", right_index=True)
    L["preco"] = L["Vlr"] / L["QTD"]
    # "tier atacado": a linha foi vendida pelo preço de atacado (e atacado < varejo)
    L["tier"] = ((L["pdv_atac"] < L["pdv_var"]) & (L["preco"] <= L["pdv_atac"] * 1.005)).astype(int)
    cup = c.groupby("CUPOM").agg(dia=("data", "min"), pdv=("PDV", "first"), itens=("id", "size"),
                                 valor=("Vlr", "sum")).reset_index()
    cix = {k: i for i, k in enumerate(cup["CUPOM"])}
    cupons = [[r.CUPOM, f"{r.dia:%d/%m}", r.pdv, int(r.itens), round(float(r.valor), 2)] for r in cup.itertuples()]
    linhas = [[idx[r.id], int(r.QTD), round(float(r.Vlr), 2), int(r.tier), cix[r.CUPOM]] for r in L.itertuples()]

    # ---------- conferência com o modelo ----------
    dentro = int((g["fora"] == 0).sum())
    py = {"Qtd Cupons": n_cupons, "Produtos Vendidos": len(g), "Produtos Vendidos Dentro Pesquisa": dentro,
          "Produtos Vendidos Fora Pesquisa": len(g) - dentro, "Unidades Vendidas": int(ok["QTD"].sum()),
          "Valor Vendido": round(float(c["Vlr"].sum()), 2),
          "Valor Dentro Pesquisa": round(float(g.loc[g["fora"] == 0, "valor"].sum()), 2)}
    validacao = [{"medida": k, "modelo": MODELO[k], "python": py[k], "ok": abs(MODELO[k] - py[k]) < 0.05}
                 for k in MODELO]

    # ---------- perfil dos dados ----------
    q0 = c[c["QTD"] <= 0]
    dup = int(c.duplicated(["CUPOM", "id"]).sum())
    razao = (L["preco"] / L["pdv_var"])
    perfil = {
        "cupons": {"linhas": len(c), "cupons": n_cupons, "produtos": len(g), "lojas": int(c["LOJA"].nunique()),
                   "pdvs": int(c["PDV"].nunique()), "dias": n_dias,
                   "de": f"{c['data'].min():%d/%m/%Y}", "ate": f"{c['data'].max():%d/%m/%Y}",
                   "duplicados_cupom_produto": dup, "qtd_zero": len(q0), "qtd_zero_valor": round(float(q0["Vlr"].sum()), 2),
                   "nulos_id_produto": int(c["id"].isna().sum()), "loja": c["LOJA"].iat[0]},
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
                   "linhas_tier_atacado": int(L["tier"].sum())},
        "cobertura_pesquisa_dias": [{"data": f"{k:%d/%m}", "linhas": int(v)}
                                    for k, v in p.groupby("dt").size().items()],
    }

    cfg = {"min_dias": MIN_DIAS, "min_cupons": MIN_CUPONS}
    produtos = [[int(r.id), r.nome, r.setor, r.categoria, int(r.cupons), int(r.dias), int(r.unid),
                 round(float(r.valor), 2), int(r.fora), int(r.alto),
                 None if pd.isna(r.pdv_var) else round(float(r.pdv_var), 2),
                 None if pd.isna(r.pdv_atac) else round(float(r.pdv_atac), 2),
                 None if pd.isna(r.custo) else round(float(r.custo), 2)] for r in g.itertuples()]
    pcl = [[idx[r.id], concs.index(r.conc), round(float(r.var), 2), round(float(r.atac), 2),
            tipos.index(r.tipo), f"{r.dt:%d/%m}"] for r in pc.itertuples() if r.id in idx]

    dados = {"gerado": pd.Timestamp.now().strftime("%d/%m/%Y %H:%M"), "cfg": cfg, "perfil": perfil,
             "validacao": validacao, "concs": concs, "tipos": tipos, "produtos": produtos, "pc": pcl,
             "linhas": linhas, "cupons": cupons}
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

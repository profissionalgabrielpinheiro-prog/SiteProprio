"""Gera o relatório HTML dinâmico das filiais Mix (venda x pesquisa x economia).

Uso:  python gerar_relatorio.py
Lê a tabela de cupons de todas as filiais ("cupom gabriel.csv", uma linha por cupom x produto), o cadastro de
produtos ("produtos.csv") e a pesquisa de preços (1067 - Filial Mix.csv), recalcula tudo em Python
(conferindo a Loja 20 com o modelo) e grava `Relatorio Loja 20.html` (arquivo único, sem dependências externas).

Modelagem: o "produto" do site é o par (filial, produto): cada filial tem o seu preço de PDV e a sua pesquisa
de concorrentes. As colunas grandes (linhas de venda, cupons, preços de concorrentes) vão em binário (base64)
para o arquivo não explodir; só entram nas linhas de venda os itens que têm preço de referência na pesquisa
da filial (os demais nunca entram no cálculo de economia). O valor total de cada cupom é mantido.
"""
import base64
import hashlib
import json
import math
import re
from pathlib import Path

import numpy as np
import pandas as pd

AQUI = Path(__file__).resolve().parent
BASE = AQUI.parent
CSV_CUPONS = BASE / "cupom gabriel.csv"       # id_filial, dia, id_cupom, codigo_pdv, id_produto, qtd_vendida, preco_total
CSV_PRODUTOS = BASE / "produtos.csv"          # id_produto, produto, setor, categoria (do dim_produto do modelo)
CSV_PESQ = BASE / "1067 - Filial Mix.csv"
SAIDA = AQUI / "Relatorio Loja 20.html"
FILIAL_MODELO = 20                            # o Power BI (validacao_modelo.json) só tem a Loja 20

# Alto giro (proporcional ao período, por filial): vendeu em pelo menos metade dos dias E em pelo menos 0,1% dos cupons.
PCT_DIAS, PCT_CUPONS = 0.5, 0.001

# tipos de preço da pesquisa considerados (filtro do Power BI)
TIPOS_VALIDOS = ["1-PRECO REGULAR", "6-PONTO EXTRA"]

# Valores calculados pelas medidas do Power BI (tabela _Medidas), para conferir com o Python.
# Ficam num arquivo LOCAL (fora do Git, pois são totais de venda). Sem o arquivo, a conferência é omitida.
_MODELO_JSON = AQUI / "validacao_modelo.json"
MODELO = json.loads(_MODELO_JSON.read_text(encoding="utf-8")) if _MODELO_JSON.exists() else {}


def b64(a, dtype) -> str:
    return base64.b64encode(np.ascontiguousarray(np.asarray(a).astype(dtype)).tobytes()).decode("ascii")


def _num(x: float):
    """Número enxuto para o JSON (inteiro quando possível)."""
    return int(x) if float(x).is_integer() else x


def nome_curto(filial: str) -> str:
    """'20 - MATEUS SUPERMERCADOS S.A. - MIX VINHAIS' -> 'Vinhais'."""
    n = filial.split(" - ", 1)[1] if " - " in filial else filial
    n = re.sub(r"^MATEUS SUPERMERCADOS( S\.? ?A\.?)?[ .-]*", "", n.strip())
    n = re.sub(r"^MIX ", "", n.strip(" -"))
    return n.strip(" -").title() or filial


def ler_cupons() -> pd.DataFrame:
    c = pd.read_csv(CSV_CUPONS, usecols=["id_filial", "dia", "id_cupom", "codigo_pdv", "id_produto", "qtd_vendida", "preco_total"],
                    dtype={"id_filial": np.int32, "id_cupom": np.int64, "codigo_pdv": np.int32, "id_produto": np.int32,
                           "qtd_vendida": np.float64, "preco_total": np.float64})
    return c.rename(columns={"id_filial": "fil", "id_cupom": "CUPOM", "codigo_pdv": "PDV", "qtd_vendida": "QTD",
                             "preco_total": "Vlr", "id_produto": "id"})


def ler_pesquisa() -> pd.DataFrame:
    cols = ["FILIAL", "PESQUISA", "EMPRESACONCORRENTE", "FILIALCONCORRENTE", "PRODUTO", "PESQUISADATA", "Tipo",
            "CustoMedio", "Vlr. Varejo PDV", "Vlr. Atacado PDV", "Vlr.Vare.Conc", "Vlr.Atac.Conc."]
    p = pd.read_csv(CSV_PESQ, sep="|", dtype=str, encoding="cp1252", usecols=cols)  # ponto decimal neste arquivo
    p["id"] = p["PRODUTO"].str.split(" - ", n=1).str[0].astype(np.int32)
    p["fil"] = p["FILIAL"].str.split(" - ", n=1).str[0].astype(np.int32)
    for n in ["Vlr. Varejo PDV", "Vlr. Atacado PDV", "Vlr.Vare.Conc", "Vlr.Atac.Conc.", "CustoMedio"]:
        p[n] = p[n].astype(float)
    p["dt"] = pd.to_datetime(p["PESQUISADATA"], dayfirst=True)
    p["conc"] = p["EMPRESACONCORRENTE"].str.split(" - ", n=1).str[1]
    # mesmo filtro aplicado no Power BI: só preço regular e ponto extra
    p = p[p["Tipo"].isin(TIPOS_VALIDOS)].copy()
    p["tipo"] = p["Tipo"].str.split("-", n=1).str[1].str.strip()
    return p


def main() -> None:
    print("lendo cupons…")
    c = ler_cupons()
    print("lendo pesquisa…")
    p = ler_pesquisa()

    # ---------- dimensões ----------
    fils = np.sort(c["fil"].unique())
    nf = len(fils)
    nomes_fil = p.drop_duplicates("fil").set_index("fil")["FILIAL"].to_dict()
    c["fi"] = np.searchsorted(fils, c["fil"].to_numpy()).astype(np.int16)
    prod_ids = np.sort(c["id"].unique())
    npd = len(prod_ids)
    c["pi"] = np.searchsorted(prod_ids, c["id"].to_numpy()).astype(np.int32)
    c["pk"] = c["fi"].astype(np.int32) * npd + c["pi"]
    dia_cod, dias_u = pd.factorize(c["dia"], sort=True)
    c["di"] = dia_cod.astype(np.int16)
    dias = [pd.Timestamp(d) for d in dias_u]
    # cupom = filial + dia + PDV + número
    c["key"] = (((c["fi"].astype(np.int64) * 64 + c["di"]) * 1000 + c["PDV"]) * 1_000_000_000) + c["CUPOM"]

    prod = pd.read_csv(CSV_PRODUTOS, dtype={"id_produto": int}).drop_duplicates("id_produto").set_index("id_produto")
    pt = prod.reindex(prod_ids)
    sem_cad = int(pt["produto"].isna().sum())
    nome = pt["produto"].fillna("(produto sem cadastro)").tolist()
    setor = pt["setor"].fillna("SEM SETOR").tolist()
    categ = pt["categoria"].fillna("SEM CATEGORIA").tolist()
    sem_cad_linhas = int(np.isin(c["id"].to_numpy(), prod_ids[pt["produto"].isna().to_numpy()]).sum())

    n_cup_f = c.groupby("fi")["key"].nunique()
    n_dias_f = c.groupby("fi")["di"].nunique()
    n_cupons = int(c["key"].nunique())
    ok = c[c["QTD"] > 0]

    # ---------- pares (filial, produto) vendidos ----------
    g = c.groupby("pk").agg(cupons=("key", "nunique"), dias=("di", "nunique"), valor=("Vlr", "sum")).reset_index()
    g = g.merge(ok.groupby("pk")["QTD"].sum().rename("unid"), on="pk", how="left").fillna({"unid": 0})
    g["fi"] = g["pk"] // npd
    min_d = np.ceil(PCT_DIAS * n_dias_f.reindex(range(nf)).to_numpy()).astype(int)
    min_c = np.ceil(PCT_CUPONS * n_cup_f.reindex(range(nf)).to_numpy()).astype(int)
    g["alto"] = ((g["dias"] >= min_d[g["fi"]]) & (g["cupons"] >= min_c[g["fi"]])).astype(int)
    pares = set(g["pk"].tolist())

    # ---------- pesquisa: chave do par ----------
    p["fi"] = np.searchsorted(fils, p["fil"].to_numpy())
    p = p[(p["fi"] < nf) & (fils[np.minimum(p["fi"], nf - 1)] == p["fil"])].copy()
    pp = np.searchsorted(prod_ids, p["id"].to_numpy())
    p = p[(pp < npd) & (prod_ids[np.minimum(pp, npd - 1)] == p["id"].to_numpy())].copy()
    p["pk"] = p["fi"].astype(np.int32) * npd + np.searchsorted(prod_ids, p["id"].to_numpy()).astype(np.int32)
    p = p[p["pk"].isin(pares)].copy()                           # só pares que a filial vendeu

    # referência Mateus na pesquisa (última data de cada par)
    ult = p.groupby("pk")["dt"].transform("max")
    ref = p[p["dt"] == ult].groupby("pk").agg(pdv_var=("Vlr. Varejo PDV", "median"), pdv_atac=("Vlr. Atacado PDV", "median"),
                                              custo=("CustoMedio", "median"))
    g = g.merge(ref, left_on="pk", right_index=True, how="left")
    g["fora"] = g["pdv_var"].isna().astype(int)

    # preço por par x concorrente (última data de cada trio)
    ult_pc = p.groupby(["pk", "conc"])["dt"].transform("max")
    q = p[p["dt"] == ult_pc]
    pc = q.groupby(["pk", "conc"]).agg(var=("Vlr.Vare.Conc", "median"), atac=("Vlr.Atac.Conc.", "median"), dt=("dt", "max")).reset_index()
    moda = (q.groupby(["pk", "conc", "tipo"]).size().rename("n").reset_index()
            .sort_values(["pk", "conc", "n", "tipo"], ascending=[True, True, False, True]).drop_duplicates(["pk", "conc"]))
    pc = pc.merge(moda[["pk", "conc", "tipo"]], on=["pk", "conc"])
    concs = sorted(pc["conc"].unique())
    tipos = sorted(pc["tipo"].unique())
    datas = sorted(pc["dt"].unique())
    pc["ci"] = pc["conc"].map({k: i for i, k in enumerate(concs)}).astype(np.uint8)
    pc["ti"] = pc["tipo"].map({k: i for i, k in enumerate(tipos)}).astype(np.uint8)
    pc["di"] = np.searchsorted(np.array(datas), pc["dt"].to_numpy()).astype(np.uint8)
    pc = pc.sort_values("pk", kind="stable")

    # ---------- linhas de venda ----------
    pv = np.full(nf * npd, np.nan); pa = np.full(nf * npd, np.nan)
    pv[g["pk"].to_numpy()] = g["pdv_var"].to_numpy(); pa[g["pk"].to_numpy()] = g["pdv_atac"].to_numpy()
    L = ok[["key", "pk", "QTD", "Vlr", "fi"]].copy()
    L["pdv_var"] = pv[L["pk"].to_numpy()]
    L["pdv_atac"] = pa[L["pk"].to_numpy()]
    L["preco"] = L["Vlr"] / L["QTD"]
    # "tier atacado": a linha foi vendida pelo preço de atacado (e atacado < varejo)
    L["tier"] = ((L["pdv_atac"] < L["pdv_var"]) & (L["preco"] <= L["pdv_atac"] * 1.005)).astype(np.uint8)

    cup = c.groupby("key").agg(fi=("fi", "first"), di=("di", "first"), pdv=("PDV", "first"), cupom=("CUPOM", "first"),
                               valor=("Vlr", "sum")).reset_index().sort_values(["fi", "di", "cupom", "pdv"], kind="stable")
    cup["ci"] = np.arange(len(cup))
    cix = pd.Series(cup["ci"].to_numpy(), index=cup["key"].to_numpy())

    # ---------- perfil dos dados (antes de descartar as linhas sem pesquisa) ----------
    q0 = c[c["QTD"] <= 0]
    dup = int(c.duplicated(["key", "id"]).sum())
    Lr = L[L["pdv_var"] > 0]
    razao = (Lr["preco"] / Lr["pdv_var"])
    pcx = pc[pc["var"] > 0].copy()
    pcx["pdv_var"] = pv[pcx["pk"].to_numpy()]
    pcx = pcx[pcx["pdv_var"] > 0]
    inc = (pcx["var"] / pcx["pdv_var"] - 1).abs() > 0.5

    # ---------- só entram as linhas com preço de referência ----------
    Lk = L[L["pdv_var"].notna()].copy()
    Lk["ci"] = cix.reindex(Lk["key"].to_numpy()).to_numpy()
    Lk = Lk.sort_values("ci", kind="stable")
    nl = np.bincount(Lk["ci"].to_numpy(), minlength=len(cup))
    del L, Lr

    # ---------- conferência com o modelo (Loja 20) ----------
    f20 = int(np.searchsorted(fils, FILIAL_MODELO)) if FILIAL_MODELO in fils else None
    validacao = []
    if f20 is not None and MODELO:
        c20 = c[c["fi"] == f20]
        g20 = g[g["fi"] == f20]
        dentro = int((g20["fora"] == 0).sum())
        py = {"Qtd Cupons": int(c20["key"].nunique()), "Produtos Vendidos": len(g20), "Produtos Vendidos Dentro Pesquisa": dentro,
              "Produtos Vendidos Fora Pesquisa": len(g20) - dentro, "Unidades Vendidas": round(float(c20.loc[c20["QTD"] > 0, "QTD"].sum()), 2),
              "Valor Vendido": round(float(c20["Vlr"].sum()), 2),
              "Valor Dentro Pesquisa": round(float(g20.loc[g20["fora"] == 0, "valor"].sum()), 2)}
        validacao = [{"medida": k, "modelo": MODELO[k], "python": py[k], "ok": abs(MODELO[k] - py[k]) < 0.05} for k in MODELO if k in py]

    # ---------- resumo por filial ----------
    fil_info = []
    for i, fid in enumerate(fils):
        gi = g[g["fi"] == i]
        tot, vd = float(gi["valor"].sum()), float(gi.loc[gi["fora"] == 0, "valor"].sum())
        cf = cup[cup["fi"] == i]
        fil_info.append({"id": int(fid), "nome": nomes_fil.get(int(fid), str(fid)), "curto": f"{fid} · {nome_curto(nomes_fil.get(int(fid), str(fid)))}",
                         "cupons": int(len(cf)), "valor": round(tot, 2), "produtos": int(len(gi)), "dentro": int((gi["fora"] == 0).sum()),
                         "valor_dentro": round(vd, 2), "alto": int(gi["alto"].sum()), "dias": int(n_dias_f.get(i, 0))})

    perfil = {
        "cupons": {"linhas": len(c), "cupons": n_cupons, "produtos": npd, "lojas": nf,
                   "pdvs": int(c[["fi", "PDV"]].drop_duplicates().shape[0]), "dias": len(dias),
                   "de": f"{dias[0]:%d/%m/%Y}", "ate": f"{dias[-1]:%d/%m/%Y}",
                   "duplicados_cupom_produto": dup, "qtd_zero": len(q0), "qtd_zero_valor": round(float(q0["Vlr"].sum()), 2),
                   "nulos_id_produto": 0, "loja": f"{nf} filiais Mix", "sem_cadastro": sem_cad_linhas, "produtos_sem_cadastro": sem_cad},
        "pesquisa": {"linhas": len(p), "produtos": int(p["id"].nunique()), "concorrentes": len(concs),
                     "filiais_concorrentes": int(p["FILIALCONCORRENTE"].nunique()), "datas": int(p["dt"].nunique()),
                     "de": f"{p['dt'].min():%d/%m/%Y}", "ate": f"{p['dt'].max():%d/%m/%Y}",
                     "valores_pesquisa": sorted(p["PESQUISA"].unique().tolist())},
        "concorrentes": [{"nome": k, "produtos": int(v)} for k, v in
                         p.groupby("conc")["id"].nunique().sort_values(ascending=False).items()],
        "tipos": [{"nome": k, "linhas": int(v)} for k, v in p["tipo"].value_counts().items()],
        "precos": {"cupom_sobre_pdv_mediana": round(float(razao.median()), 3), "linhas_comparaveis": int(len(razao)),
                   "linhas_fora_50pct": int(((razao < 0.5) | (razao > 1.5)).sum()),
                   "produtos_pdv_igual_atacado": int((g["pdv_var"] == g["pdv_atac"]).sum()),
                   "conc_precos": int(len(pcx)), "conc_incompativeis": int(inc.sum()),
                   "conc_zerados": int((pc["var"] <= 0).sum()), "linhas_tier_atacado": int(Lk["tier"].sum())},
        "cobertura_pesquisa_dias": [{"data": f"{k:%d/%m}", "linhas": int(v)} for k, v in p.groupby("dt").size().items()],
    }
    visao = {"produtos": npd, "pares": len(g), "pares_dentro": int((g["fora"] == 0).sum()), "valor": round(float(g["valor"].sum()), 2),
             "valor_dentro": round(float(g.loc[g["fora"] == 0, "valor"].sum()), 2), "alto": int(g["alto"].sum()),
             "alto_prod": int(g.loc[g["alto"] == 1, "pk"].mod(npd).nunique())}

    # ---------- dados do site ----------
    def r(x, n):
        return None if pd.isna(x) else round(float(x), n)

    pares_js = [[int(a.pk), int(a.cupons), int(a.dias), _num(round(float(a.unid), 3)), round(float(a.valor), 2), int(a.fora), int(a.alto),
                 r(a.pdv_var, 4), r(a.pdv_atac, 4), r(a.custo, 2)] for a in g.itertuples()]
    dados = {"gerado": pd.Timestamp.now().strftime("%d/%m/%Y %H:%M"), "cfg": {"pct_dias": PCT_DIAS, "pct_cupons": PCT_CUPONS},
             "perfil": perfil, "validacao": validacao, "visao": visao, "filiais": fil_info, "concs": concs, "tipos": tipos,
             "datas": [f"{pd.Timestamp(d):%d/%m/%Y}" for d in datas],
             "produtos": [[int(i), n, s, ct] for i, n, s, ct in zip(prod_ids, nome, setor, categ)], "pares": pares_js,
             "dias": [f"{d:%d/%m}" for d in dias],
             "bin": {
                 # linhas de venda (agrupadas por cupom): par, quantidade (milésimos), valor (centavos), tabela atacado
                 "lp": b64(Lk["pk"], "<u4"), "lq": b64(np.rint(Lk["QTD"].to_numpy() * 1000), "<i4"),
                 "lv": b64(np.rint(Lk["Vlr"].to_numpy() * 100), "<i4"), "lt": b64(Lk["tier"], "u1"),
                 # cupons
                 "ci": b64(cup["cupom"], "<u4"), "cf": b64(cup["fi"], "u1"), "cd": b64(cup["di"], "u1"), "cp": b64(cup["pdv"], "<u2"),
                 "cv": b64(np.rint(cup["valor"].to_numpy() * 100), "<u4"), "cn": b64(nl, "<u2"),
                 # preço dos concorrentes por par
                 "pk": b64(pc["pk"], "<u4"), "pc": b64(pc["ci"], "u1"), "pv": b64(pc["var"], "<f4"), "pa": b64(pc["atac"], "<f4"),
                 "pt": b64(pc["ti"], "u1"), "pd": b64(pc["di"], "u1")}}
    js = json.dumps(dados, ensure_ascii=False, separators=(",", ":"))
    js = js.replace("<", "\\u003c").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")

    tpl = (AQUI / "template.html").read_text(encoding="utf-8")
    ini = tpl.index("<script>") + len("<script>")
    fim = tpl.index("</script>", ini)
    sha = base64.b64encode(hashlib.sha256(tpl[ini:fim].encode("utf-8")).digest()).decode()
    csp = f"default-src 'none'; style-src 'unsafe-inline'; script-src 'sha256-{sha}'; img-src data:; base-uri 'none'; form-action 'none'"
    html = tpl.replace("__CSP__", csp).replace("__DADOS__", js)
    SAIDA.write_text(html, encoding="utf-8")
    print("ok:", SAIDA, f"{SAIDA.stat().st_size / 1024:.0f} KB")
    print(f"filiais={nf} cupons={n_cupons} linhas={len(c)} linhas_no_site={len(Lk)} pares={len(g)} pares_pesquisa={len(pc)} produtos={npd} sem_cadastro={sem_cad}")
    for fi_ in fil_info:
        print(fi_["curto"], fi_["cupons"], round(fi_["valor_dentro"] / fi_["valor"] * 100, 1), "% do valor dentro da pesquisa")
    for v in validacao:
        print(("OK   " if v["ok"] else "DIVERGE"), v["medida"], v["modelo"], v["python"])


if __name__ == "__main__":
    main()

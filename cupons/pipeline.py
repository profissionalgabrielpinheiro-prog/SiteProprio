"""Pipeline: lê os cupons, cruza com categoria/mapa mãe x complementar, agrega e gera o site.

Fluxo:
  1. lê o(s) arquivo(s) de cupons (Excel exportado do Power BI ou CSV) em dados/entrada;
  2. cruza cada produto com a categoria (dados/produtos_cupom.csv);
  3. cruza as categorias com o mapa mãe x complementar (dados/mapa_mae_complementar.csv);
  4. agrega tudo (dia, categoria, par mãe/complementar, cestas) em um JSON compacto;
  5. injeta o JSON no template (com escape seguro) e aplica a Content-Security-Policy.

Por que agregar: o arquivo bruto tem centenas de milhares de linhas (e pode chegar a GBs).
O navegador só precisa dos totais por dia/categoria/par. Todas as taxas (penetração, attach,
lift) são recalculadas no navegador a partir de contagens aditivas, então os filtros valem.

Uso:
    python -m cupons                    # lê dados/entrada/*.xlsx|csv
    python -m cupons caminho\\cupons.xlsx
"""
import json
import os
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime
from itertools import combinations
from pathlib import Path
from statistics import median

import pandas as pd

from .config import Config
from .seguranca import aplicar_csp, checar_tamanho, json_para_script, texto_csv

TEMPLATE = Path(__file__).parent / "templates" / "index.html"
LIMITE_EXPORT_POWERBI = 150_000  # linhas que o Power BI exporta para Excel

BINS_ITENS = [(1, 1, "1"), (2, 2, "2"), (3, 3, "3"), (4, 5, "4-5"), (6, 10, "6-10"),
              (11, 20, "11-20"), (21, 10**9, "21+")]
BINS_TICKET = [(0, 10, "< R$ 10"), (10, 25, "10-25"), (25, 50, "25-50"),
               (50, 100, "50-100"), (100, 200, "100-200"), (200, 10**12, "200+")]


# ----------------------------------------------------------------------------- leitura
def ler_arquivo(caminho: Path, max_mb: int):
    """Devolve (DataFrame com 5 colunas, texto de filtros do export ou '')."""
    checar_tamanho(caminho, max_mb)
    if caminho.suffix.lower() in (".xlsx", ".xlsm"):
        bruto = pd.read_excel(caminho, header=None)
    else:
        bruto = pd.read_csv(caminho, header=None, sep=None, engine="python",
                            encoding="utf-8-sig")
    filtros = ""
    linha_cab = None
    for i in range(min(len(bruto), 10)):
        primeira = str(bruto.iat[i, 0])
        if primeira.strip().lower() == "filial":
            linha_cab = i
            break
        if primeira.lower().startswith("filtros"):
            filtros = primeira
    if linha_cab is None:
        raise ValueError(f"{caminho.name}: não achei a linha de cabeçalho (coluna 'Filial').")
    df = bruto.iloc[linha_cab + 1:, :5].copy()
    df.columns = ["filial", "dia", "cupom", "produto", "valor"]
    df = df.dropna(subset=["cupom", "produto"])
    df["dia"] = pd.to_datetime(df["dia"], errors="coerce")
    # Excel já traz número; só o que não converte e tem vírgula é texto pt-BR ("1.234,56").
    valor = pd.to_numeric(df["valor"], errors="coerce")
    texto_ptbr = valor.isna() & df["valor"].astype(str).str.contains(",", regex=False)
    if texto_ptbr.any():
        valor[texto_ptbr] = pd.to_numeric(
            df.loc[texto_ptbr, "valor"].astype(str).str.replace(".", "", regex=False)
            .str.replace(",", ".", regex=False), errors="coerce")
    df["valor"] = valor
    df = df.dropna(subset=["dia", "valor"])
    df["arquivo"] = caminho.name
    return df, filtros


def carregar_cupons(arquivos, max_mb):
    partes, filtros, avisos = [], [], []
    for a in arquivos:
        df, f = ler_arquivo(a, max_mb)
        partes.append(df)
        filtros.append(f)
        print(f"  {a.name}: {len(df):,} linhas")
    todos = pd.concat(partes, ignore_index=True)
    bruto = len(todos)
    if len(arquivos) > 1:
        # Mesmo cupom em mais de um arquivo (períodos sobrepostos): fica só no primeiro.
        primeiro = todos.groupby("cupom")["arquivo"].first()
        todos = todos[todos["arquivo"] == todos["cupom"].map(primeiro)]
        if len(todos) < bruto:
            avisos.append(f"{bruto - len(todos):,} linhas repetidas entre arquivos foram descartadas.")
    return todos.reset_index(drop=True), filtros, avisos


# ----------------------------------------------------------------------------- apoio
def ler_csv(cfg, nome):
    checar_tamanho(cfg.dados / nome, cfg.max_mb)
    return pd.read_csv(cfg.dados / nome, sep=";", encoding="utf-8-sig")


def faixa(valor, bins):
    """Índice da faixa [lo, hi] (itens, inteiros) ou [lo, hi) (valores em R$)."""
    for i, (lo, hi, _) in enumerate(bins):
        dentro = lo <= valor <= hi if bins is BINS_ITENS else lo <= valor < hi
        if dentro:
            return i
    return len(bins) - 1


def pct(a, b):
    return (a / b * 100) if b else 0.0


def dec(v, casas=1):
    """Número com vírgula decimal (pt-BR)."""
    return f"{v:.{casas}f}".replace(".", ",")


def mil(n):
    """Inteiro com ponto de milhar (pt-BR)."""
    return f"{int(n):,}".replace(",", ".")


def brl(v):
    return "R$ " + f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


# ----------------------------------------------------------------------------- principal
def main(argv=None, cfg=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # console do Windows usa cp1252
    cfg = cfg or Config.carregar()
    if argv:
        arquivos = [Path(a) for a in argv]
    else:
        arquivos = sorted(p for p in cfg.entrada.glob("*") if p.suffix.lower() in (".xlsx", ".csv")) \
            if cfg.entrada.exists() else []
    arquivos = [a for a in arquivos if a.exists()]
    if not arquivos:
        sys.exit(f"Nenhum arquivo de cupons encontrado. Coloque exportações (.xlsx/.csv) em {cfg.entrada}.")

    print("Lendo cupons...")
    df, filtros, avisos = carregar_cupons(arquivos, cfg.max_mb)
    linhas_lidas = len(df)

    # produto -> categoria
    df["id_produto"] = pd.to_numeric(df["produto"].str.extract(r"^\s*(\d+)\s*-")[0], errors="coerce")
    prod = ler_csv(cfg, "produtos_cupom.csv")
    df = df.merge(prod[["id_produto", "id_categoria", "categoria", "departamento", "secao", "tipo_produto"]],
                  on="id_produto", how="left")
    sem_cat = df["id_categoria"].isna()
    pct_sem_cat = pct(sem_cat.sum(), len(df))
    df["id_categoria"] = df["id_categoria"].fillna(-1).astype(int)
    df["categoria"] = df["categoria"].fillna("SEM CATEGORIA")
    df["departamento"] = df["departamento"].fillna("SEM DEPARTAMENTO")
    df["secao"] = df["secao"].fillna("-")
    df["tipo_produto"] = df["tipo_produto"].fillna("SEM TIPO")
    df["dia"] = df["dia"].dt.strftime("%Y-%m-%d")

    mapa = ler_csv(cfg, "mapa_mae_complementar.csv")
    cats_papel = ler_csv(cfg, "categorias.csv").set_index("id_categoria")["papel"].to_dict()

    dias = sorted(df["dia"].unique())
    d_idx = {d: i for i, d in enumerate(dias)}
    deptos = sorted(df["departamento"].unique())
    tipos = sorted(df["tipo_produto"].unique())
    dep_idx = {d: i for i, d in enumerate(deptos)}
    tip_idx = {t: i for i, t in enumerate(tipos)}

    # ---- nível cupom
    cup = df.groupby("cupom").agg(dia=("dia", "first"), total=("valor", "sum"),
                                  itens=("valor", "size"))
    n_dia = cup.groupby("dia").size()
    # dia parcial: bem menos cupons que a mediana dos anteriores (export cortado)
    parcial = []
    for i, d in enumerate(dias):
        anteriores = [n_dia[x] for x in dias[:i]]
        parcial.append(bool(i == len(dias) - 1 and anteriores and n_dia[d] < 0.6 * median(anteriores)))

    # ---- cubo dia x categoria x depto x tipo
    cubo_df = df.groupby(["dia", "id_categoria", "departamento", "tipo_produto"]).agg(
        venda=("valor", "sum"), itens=("valor", "size"), cupons=("cupom", "nunique")).reset_index()
    cubo = [[d_idx[r.dia], int(r.id_categoria), dep_idx[r.departamento], tip_idx[r.tipo_produto],
             round(r.venda, 2), int(r.itens), int(r.cupons)] for r in cubo_df.itertuples()]
    # cupons DISTINTOS por corte (somar o cubo contaria o mesmo cupom em várias categorias)
    cdep = [[d_idx[d], dep_idx[x], int(n)]
            for (d, x), n in df.groupby(["dia", "departamento"])["cupom"].nunique().items()]
    ctip = [[d_idx[d], tip_idx[x], int(n)]
            for (d, x), n in df.groupby(["dia", "tipo_produto"])["cupom"].nunique().items()]
    cdt = [[d_idx[d], dep_idx[x], tip_idx[t], int(n)]
           for (d, x, t), n in df.groupby(["dia", "departamento", "tipo_produto"])["cupom"].nunique().items()]
    cat_info = df.drop_duplicates("id_categoria").set_index("id_categoria")
    cats = {}
    for cid, r in cat_info.iterrows():
        papel = cats_papel.get(cid, "")
        cats[int(cid)] = {"n": r["categoria"], "s": r["secao"], "p": papel if isinstance(papel, str) else ""}

    # ---- composição de cada cupom
    cats_cupom = defaultdict(dict)
    for (cp, cat), v in df.groupby(["cupom", "id_categoria"])["valor"].sum().items():
        cats_cupom[cp][int(cat)] = float(v)

    # mapa: pares mãe -> complementares
    pares_mapa = []
    comps_de = defaultdict(list)
    for r in mapa.itertuples():
        pares_mapa.append({"m": int(r.id_categoria_mae), "mn": r.categoria_mae,
                           "c": int(r.id_categoria_complementar), "cn": r.categoria_complementar,
                           "g": r.grupo, "r": r.relacao, "f": r.forca, "mo": r.motivo})
        comps_de[int(r.id_categoria_mae)].append(int(r.id_categoria_complementar))
    par_idx = {(p["m"], p["c"]): i for i, p in enumerate(pares_mapa)}
    maes = set(comps_de)

    par_stats = defaultdict(lambda: [0, 0, 0.0, 0.0, 0.0])   # (dia,pidx): n_mae,n_both,tot_both,tot_maeonly,v_comp_both
    mae_stats = defaultdict(lambda: [0, 0, 0.0, 0.0, 0.0])   # (dia,mae): n_mae,n_any,tot_any,tot_none,v_comp_any
    ncat = defaultdict(int)                                   # (dia,cat): cupons com a categoria
    kpi = [dict(n=0, venda=0.0, itens=0, unit=0, com_mae=0, com_mae_comp=0, tot_mae_comp=0.0, tot_mae_sem=0.0)
           for _ in dias]
    h_itens = [[0] * len(BINS_ITENS) for _ in dias]
    h_ticket = [[0] * len(BINS_TICKET) for _ in dias]
    cat_total = Counter()

    for cp, r in cup.iterrows():
        di = d_idx[r["dia"]]
        S = cats_cupom[cp]
        total, itens = float(r["total"]), int(r["itens"])
        k = kpi[di]
        k["n"] += 1
        k["venda"] += total
        k["itens"] += itens
        k["unit"] += itens == 1
        h_itens[di][faixa(itens, BINS_ITENS)] += 1
        h_ticket[di][faixa(total, BINS_TICKET)] += 1
        for c in S:
            ncat[(di, c)] += 1
            cat_total[c] += 1
        tem_mae = tem_mae_comp = False
        for m in maes:
            if m not in S:
                continue
            tem_mae = True
            ms = mae_stats[(di, m)]
            ms[0] += 1
            presentes = [c for c in comps_de[m] if c in S]
            if presentes:
                tem_mae_comp = True
                ms[1] += 1
                ms[2] += total
                ms[4] += sum(S[c] for c in presentes)
            else:
                ms[3] += total
            for c in comps_de[m]:
                ps = par_stats[(di, par_idx[(m, c)])]
                ps[0] += 1
                if c in S:
                    ps[1] += 1
                    ps[2] += total
                    ps[4] += S[c]
                else:
                    ps[3] += total
        k["com_mae"] += tem_mae
        k["com_mae_comp"] += tem_mae_comp
        if tem_mae_comp:
            k["tot_mae_comp"] += total
        elif tem_mae:
            k["tot_mae_sem"] += total

    for k in kpi:
        for campo in ("venda", "tot_mae_comp", "tot_mae_sem"):
            k[campo] = round(k[campo], 2)
    pares = [[di, pi] + [round(x, 2) if isinstance(x, float) else x for x in v]
             for (di, pi), v in sorted(par_stats.items())]
    maes_rows = [[di, m] + [round(x, 2) if isinstance(x, float) else x for x in v]
                 for (di, m), v in sorted(mae_stats.items())]
    ncat_rows = [[di, c, n] for (di, c), n in sorted(ncat.items())]

    # ---- pares frequentes fora do mapa (sugestões)
    N = len(cup)
    elegiveis = {c for c, n in cat_total.items() if n >= 40 and c != -1}
    mapeados = set(par_idx) | {(c, m) for (m, c) in par_idx}
    contagem = Counter()
    for S in cats_cupom.values():
        for a, b in combinations(sorted(c for c in S if c in elegiveis), 2):
            contagem[(a, b)] += 1
    descobertos = []
    for (a, b), n in contagem.items():
        if n < 25 or (a, b) in mapeados:
            continue
        lift = n * N / (cat_total[a] * cat_total[b])
        if lift >= 1.8:
            descobertos.append({"a": cats[a]["n"], "b": cats[b]["n"], "n": n, "na": cat_total[a],
                                "nb": cat_total[b], "lift": round(lift, 2),
                                "ab": round(n / cat_total[a] * 100, 1), "ba": round(n / cat_total[b] * 100, 1),
                                "score": n * (lift - 1)})
    descobertos.sort(key=lambda x: -x["score"])
    descobertos = descobertos[:80]
    for x in descobertos:
        del x["score"]

    # ---- indicadores do período completo (para os textos da análise técnica)
    venda_tot = sum(k["venda"] for k in kpi)
    pa = defaultdict(lambda: [0, 0, 0.0, 0.0, 0.0])
    for (_di, pi), v in par_stats.items():
        for j in range(5):
            pa[pi][j] += v[j]
    ma = defaultdict(lambda: [0, 0, 0.0, 0.0, 0.0])
    for (_di, m), v in mae_stats.items():
        for j in range(5):
            ma[m][j] += v[j]
    resumo_pares = []
    for pi, v in pa.items():
        p = pares_mapa[pi]
        n_comp = cat_total.get(p["c"], 0)
        if v[0] and n_comp:
            resumo_pares.append({**p, "n_mae": v[0], "n_both": v[1], "n_comp": n_comp,
                                 "attach": pct(v[1], v[0]), "lift": v[1] * N / (v[0] * n_comp)})
    resumo_maes = []
    for m, v in ma.items():
        nome = cats.get(m, {}).get("n", str(m))
        resumo_maes.append({"id": m, "n": nome, "n_mae": v[0], "pen": pct(v[0], N), "attach": pct(v[1], v[0]),
                            "tk_com": v[2] / v[1] if v[1] else 0, "tk_sem": v[3] / (v[0] - v[1]) if v[0] > v[1] else 0,
                            "vcomp": v[4] / v[1] if v[1] else 0, "gap": v[0] - v[1]})

    pro, contra = [], []
    firmes = [p for p in resumo_pares if p["n_mae"] >= 100]
    fortes = sorted([p for p in firmes if p["lift"] >= 1.2 and p["f"] == "ALTA"], key=lambda x: -x["n_both"])[:5]
    if fortes:
        lista = "; ".join(f'{p["mn"]} → {p["cn"]} (lift {dec(p["lift"])}, attach {dec(p["attach"], 0)}%)' for p in fortes[:3])
        pro.append({"t": "O mapa tem suporte real nos cupons",
                    "x": f"{len([p for p in firmes if p['lift'] >= 1.2])} de {len(firmes)} relações com amostra ≥ 100 cupons "
                         f"aparecem juntas mais do que o acaso (lift ≥ 1,2). Mais fortes: {lista}.",
                    "e": "lift = P(mãe e compl.) ÷ (P(mãe) × P(compl.))"})
    n_com = sum(k["com_mae_comp"] for k in kpi)
    n_sem = sum(k["com_mae"] - k["com_mae_comp"] for k in kpi)
    if n_com and n_sem:
        a = sum(k["tot_mae_comp"] for k in kpi) / n_com
        b = sum(k["tot_mae_sem"] for k in kpi) / n_sem
        pro.append({"t": "Cupons com complementar têm ticket maior",
                    "x": f"Entre os cupons que têm alguma categoria mãe, o ticket médio é {brl(a)} quando há complementar "
                         f"({mil(n_com)} cupons) contra {brl(b)} quando não há ({mil(n_sem)} cupons): {dec((a / b - 1) * 100, 0)}% maior. "
                         "Atenção: parte do efeito é só cesta maior (mais itens), não causalidade.",
                    "e": "cada cupom é contado uma única vez, independentemente de quantas mães tenha"})
    alta = sorted([m for m in resumo_maes if m["n_mae"] >= 200], key=lambda x: -x["attach"])[:3]
    if alta:
        pro.append({"t": "Mães com venda casada já consolidada",
                    "x": "Maiores taxas de complementar entre mães relevantes: " +
                         "; ".join(f'{m["n"]} ({dec(m["attach"], 0)}%)' for m in alta) +
                         ". Servem de referência de exposição/cross-sell para as demais.",
                    "e": "attach = cupons com mãe e complementar ÷ cupons com mãe"})
    # só vale concluir "abaixo do acaso" se o esperado por acaso seria ao menos 5 cupons juntos
    fracos = sorted([p for p in firmes if p["lift"] < 0.8 and p["n_mae"] * p["n_comp"] / N >= 5],
                    key=lambda x: x["lift"])
    if fracos:
        contra.append({"t": "Relações do mapa sem respaldo nos dados",
                       "x": f"{len(fracos)} relações (amostra ≥ 100) aparecem juntas MENOS que o acaso (lift < 0,8), "
                            f"por ex.: " + "; ".join(f'{p["mn"]} → {p["cn"]} (lift {dec(p["lift"], 2)})' for p in fracos[:3]) +
                            ". Vale revisar: podem ser itens substitutos, não complementares.",
                       "e": "lift < 0,8"})
    gaps = sorted([m for m in resumo_maes if m["n_mae"] >= 200 and m["vcomp"]],
                  key=lambda x: -(x["gap"] * x["vcomp"]))[:3]
    if gaps:
        contra.append({"t": "Muitos cupons com mãe saem sem complementar",
                       "x": "Maiores lacunas em valor potencial: " +
                            "; ".join(f'{m["n"]} ({mil(m["gap"])} cupons sem complementar, {dec(100 - m["attach"], 0)}% dos cupons da mãe)' for m in gaps) +
                            ". É aqui que ação de exposição/combo tem mais espaço.",
                       "e": "gap = cupons com mãe − cupons com mãe e complementar"})
    uni = sum(k["unit"] for k in kpi)
    contra.append({"t": "Parcela relevante de cupons de 1 item",
                   "x": f"{dec(pct(uni, N), 0)}% dos cupons têm um único item e não permitem venda casada. "
                        "Perfil de compra rápida/conveniência; o teto de attach das mães fica limitado por isso.",
                   "e": "cupons com 1 linha ÷ cupons"})
    contra.append({"t": "Sem quantidade, custo ou cliente",
                   "x": "O export traz só valor por linha. Não dá para medir margem, unidades, elasticidade ou recompra; "
                        "a análise é de receita e coocorrência.", "e": "colunas disponíveis: filial, dia, cupom, produto, valor"})

    # ---- qualidade dos dados
    qual = []
    atingiu_limite = linhas_lidas in (LIMITE_EXPORT_POWERBI, LIMITE_EXPORT_POWERBI + 1, LIMITE_EXPORT_POWERBI + 2)
    solicitado = ""
    m_ = re.search(r"'Data'\[DIA\][^0-9]*(\d{2})-(\d{2})-(\d{4})[^0-9]*(\d{2})-(\d{2})-(\d{4})", " ".join(filtros))
    if m_:
        d1, mo1, a1, d2, mo2, a2 = m_.groups()
        solicitado = f"{d1}/{mo1}/{a1} a {d2}/{mo2}/{a2} (exclusive)"
    qual.append({"s": "erro" if atingiu_limite else "ok", "t": "Linhas lidas",
                 "x": f"{linhas_lidas:,} linhas".replace(",", ".") +
                      (" — é o limite de 150.000 linhas do export do Power BI: o arquivo foi cortado e há dias faltando/incompletos."
                       if atingiu_limite else ".")})
    if solicitado:
        qual.append({"s": "aviso" if atingiu_limite else "ok", "t": "Período do filtro × período recebido",
                     "x": f"O filtro do export pedia {solicitado}; os dados vão de "
                          f"{datetime.strptime(dias[0], '%Y-%m-%d'):%d/%m} a {datetime.strptime(dias[-1], '%Y-%m-%d'):%d/%m/%Y}."})
    if any(parcial):
        qual.append({"s": "erro", "t": "Último dia incompleto",
                     "x": f"{datetime.strptime(dias[-1], '%Y-%m-%d'):%d/%m} tem {n_dia[dias[-1]]:,} cupons contra mediana de "
                          f"{int(median([n_dia[d] for d in dias[:-1]])):,} nos dias anteriores. Marcado como parcial e excluído "
                          "das variações dia a dia.".replace(",", ".")})
    qual.append({"s": "ok" if pct_sem_cat == 0 else "aviso", "t": "Produtos sem categoria",
                 "x": f"{dec(pct_sem_cat, 2)}% das linhas ({mil(sem_cat.sum())})."})
    qual.append({"s": "ok" if (df['valor'] > 0).all() else "aviso", "t": "Valores ≤ 0",
                 "x": f"{int((df['valor'] <= 0).sum())} linhas com valor zero ou negativo."})
    qual.append({"s": "ok", "t": "Cupons únicos",
                 "x": f"{N:,} cupons em {df['cupom'].str.split('_').str[2].nunique()} caixas (PDV).".replace(",", ".")})
    for a in avisos:
        qual.append({"s": "aviso", "t": "Arquivos", "x": a})

    loja = str(df["filial"].dropna().iloc[0]) if df["filial"].notna().any() else ""
    dados = {
        "meta": {"loja": loja, "gerado": datetime.now().strftime("%d/%m/%Y %H:%M"),
                 "arquivos": [a.name for a in arquivos], "linhas": linhas_lidas, "cupons": N,
                 "produtos": int(df["id_produto"].nunique())},
        "dias": dias, "parcial": parcial, "kpi": kpi, "deptos": deptos, "tipos": tipos,
        "cats": cats, "cubo": cubo, "cdep": cdep, "ctip": ctip, "cdt": cdt, "mapa": pares_mapa, "pares": pares, "maes": maes_rows,
        "ncat": ncat_rows, "hItens": h_itens, "hTicket": h_ticket,
        "binsItens": [b[2] for b in BINS_ITENS], "binsTicket": [b[2] for b in BINS_TICKET],
        "descobertos": descobertos, "pro": pro, "contra": contra, "qualidade": qual,
    }

    # ---- encarte x mãe/complementar (precisa dos CSVs de preço e da venda da loja 20)
    necessarios = [cfg.tipopreco_csv, cfg.dados / "venda_dia_produto_loja20.csv", cfg.dados / "produtos_loja20.csv"]
    if all(a.exists() for a in necessarios):
        from .encarte import construir
        print("Analisando encarte...")
        for a in necessarios:
            checar_tamanho(a, cfg.max_mb)
        dados["enc"] = construir(cfg.tipopreco_csv, cfg.dados, df[["cupom", "dia", "id_produto", "id_categoria", "valor"]],
                                 janelas_csv=cfg.dados / "encarte_janelas.csv")
        # modelo para o usuário preencher as datas do encarte. O nome do produto vem dos dados e a
        # planilha será aberta no Excel: texto_csv evita que "=..." vire fórmula (CSV injection).
        modelo_jan = cfg.dados / "encarte_janelas_modelo.csv"
        pd.DataFrame({"id_produto": [x["id"] for x in dados["enc"]["produtos"]],
                      "produto": [texto_csv(x["n"]) for x in dados["enc"]["produtos"]],
                      "inicio": "", "fim": ""}).to_csv(modelo_jan, sep=";", index=False, encoding="utf-8-sig")
    else:
        print("Encarte: arquivos de preço/venda não encontrados; abas de encarte ficam de fora.")
        dados["enc"] = None

    modelo = TEMPLATE.read_text(encoding="utf-8")
    if modelo.count("/*__DADOS__*/null") != 1:   # trava explícita (assert some com python -O)
        raise ValueError("marcador de dados ausente ou duplicado no template")
    html = aplicar_csp(modelo.replace("/*__DADOS__*/null", json_para_script(dados)))
    cfg.saida.parent.mkdir(parents=True, exist_ok=True)
    cfg.saida.write_text(html, encoding="utf-8")
    (cfg.dados / "agregado.json").write_text(json.dumps(dados, ensure_ascii=False), encoding="utf-8")
    usuario, senha = os.environ.get("CUPONS_USUARIO"), os.environ.get("CUPONS_SENHA")
    if usuario and senha:   # versão cifrada para publicar (Cloudflare Pages): pasta publico/
        from .protecao import publicar
        print(f"Versão protegida: {publicar(cfg.saida, cfg.raiz / 'publico', usuario, senha)}")
    elif usuario or senha:
        sys.exit("Defina CUPONS_USUARIO e CUPONS_SENHA juntos.")
    print(f"\nCupons: {N:,} | Venda: {brl(venda_tot)} | Dias: {', '.join(dias)} | Parcial: {parcial}")
    print(f"Pares ativos: {len(pa)} | Mães ativas: {len(ma)} | Pares descobertos: {len(descobertos)}")
    print(f"Site: {cfg.saida}  ({cfg.saida.stat().st_size / 1024:.0f} KB)")

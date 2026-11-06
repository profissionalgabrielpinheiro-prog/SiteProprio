"""Análise de encarte (preço promocional do Mateus) x categorias mãe/complementares - loja 20.

Duas entregas, com exigências de dado diferentes:

1) ECONOMIA DO PRODUTO (sempre roda). Para cada produto em promoção na tabela Tipo de Preço
   (por padrão só TIPOPROMOCAO = ENCARTE): preço de tabela, preço promocional, custo, margem
   unitária e QUANTO VENDER A MAIS para manter a mesma margem total:
        volume necessário = volume atual x margem unitária normal / margem unitária com desconto
   Não precisa de datas.

2) INFLUÊNCIA NAS VENDAS DE OUTROS PRODUTOS (só roda se existir dados/encarte_janelas.csv).
   A tabela Tipo de Preço não traz datas e a venda não deixa o início do encarte claro, então
   as datas vêm de um arquivo: id_produto;inicio;fim (AAAA-MM-DD). Com elas o motor compara:
     * a participação do item na venda da loja dentro x fora do encarte;
     * as categorias complementares das mães em encarte contra o resto da loja;
     * a cesta (cupom): cupons com item da mãe em encarte x sem, e se levam complementar.
   Venda sempre como participação na venda da loja no dia (tira efeito de dia forte/fraco).
"""
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

from .seguranca import checar_tamanho

TIPOS_ENCARTE = ("ENCARTE",)   # trechos de TIPOPROMOCAO considerados "encarte"; ("",) = toda promoção
SEMANAS_BASE = 2
MIN_CUPONS = 30
TOL_PRECO = 0.03


def volume_necessario(vol_base, margem_normal, margem_promo):
    """Volume (un/dia) que mantém a margem total depois do desconto.

        volume necessário = volume atual x margem unitária normal / margem unitária em promoção

    Devolve None quando a margem em promoção (ou a normal) é <= 0: nenhum volume compensa.
    """
    if margem_promo is None or margem_normal is None or margem_promo <= 0 or margem_normal <= 0:
        return None
    return vol_base * margem_normal / margem_promo


def _num(s):
    return pd.to_numeric(s, errors="coerce")


def _r(x, n=4):
    if x is None:
        return None
    try:
        x = float(x)
    except (TypeError, ValueError):
        return None
    return round(x, n) if np.isfinite(x) else None


def _fmt(x, casas=1, sinal=False):
    if x is None or not np.isfinite(x):
        return "—"
    s = f"{abs(x):.{casas}f}".replace(".", ",")
    return (("+" if x >= 0 else "−") + s) if sinal else (("-" if x < 0 else "") + s)


def _ler_tipopreco(caminho):
    t = pd.read_csv(caminho, sep="|", encoding="cp1252", dtype=str)
    t["id_produto"] = _num(t["PRODUTO"].str.extract(r"^\s*(\d+)\s*-")[0])
    for c in ["PcoVenda", "PcoPrmVarejo", "PcoPrmAtac"]:
        t[c] = _num(t[c].str.replace(",", ".", regex=False))      # este CSV usa vírgula decimal
    t["TIPOPROMOCAO"] = t["TIPOPROMOCAO"].str.strip()
    t["PRODUTO"] = t["PRODUTO"].str.strip()
    return t.dropna(subset=["id_produto"])


def _dias_base(v, T, ate):
    """Últimos 10 dias úteis com venda normal até `ate` (exclui feriado/falha de dado)."""
    uteis = [d for d in T.index if d <= ate and d.weekday() < 5]
    mediana = float(np.median([T[d] for d in uteis]))
    normais = [d for d in uteis if T[d] >= 0.7 * mediana]
    excl = [d for d in uteis[-5 * SEMANAS_BASE - 3:] if d not in normais]
    return normais[-5 * SEMANAS_BASE:], excl


def construir(tipopreco_csv, dados: Path, df_cupom: pd.DataFrame, janelas_csv=None):
    t = _ler_tipopreco(tipopreco_csv)
    v = pd.read_csv(dados / "venda_dia_produto_loja20.csv", sep=";", encoding="utf-8-sig",
                    parse_dates=["dia_venda"]).rename(columns={"dia_venda": "dia"})
    prod = pd.read_csv(dados / "produtos_loja20.csv", sep=";", encoding="utf-8-sig").set_index("id_produto")
    mapa = pd.read_csv(dados / "mapa_mae_complementar.csv", sep=";", encoding="utf-8-sig")

    T = v.groupby("dia")["venda"].sum()
    ult = T.index.max()
    base, excl = _dias_base(v, T, ult)
    qtd = v.pivot_table(index="id_produto", columns="dia", values="quantidade", aggfunc="sum", fill_value=0.0)
    ven = v.pivot_table(index="id_produto", columns="dia", values="venda", aggfunc="sum", fill_value=0.0)
    luc = v.pivot_table(index="id_produto", columns="dia", values="lucro", aggfunc="sum", fill_value=0.0)
    ultimos = [d for d in T.index if d > ult - pd.Timedelta(days=4)]
    mes = list(T.index)

    maes = set(mapa["id_categoria_mae"])
    comps = set(mapa["id_categoria_complementar"])
    comps_de = mapa.groupby("id_categoria_mae")["id_categoria_complementar"].apply(list).to_dict()
    nome_cat = prod.drop_duplicates("id_categoria").set_index("id_categoria")["categoria"].to_dict()
    grupo_mae = mapa.drop_duplicates("id_categoria_mae").set_index("id_categoria_mae")["grupo"].to_dict()

    # ---- atach de referência na cesta (todas as mães, sem separar por encarte)
    c = df_cupom.copy()
    cats_cupom = defaultdict(set)
    for cp, cat in zip(c["cupom"], c["id_categoria"], strict=True):
        cats_cupom[cp].add(int(cat))
    att_mae = {}
    for m, cs in comps_de.items():
        n = tem = 0
        for S in cats_cupom.values():
            if m in S:
                n += 1
                tem += bool(set(cs) & S)
        att_mae[m] = (n, tem)

    # ---- universo: produtos em promoção (padrão: encarte)
    sel = t[t["TIPOPROMOCAO"].apply(lambda x: any(k in str(x) for k in TIPOS_ENCARTE))]
    sel = sel[sel["TIPOPRECO"].str.contains("PROMOCAO", na=False)]
    linhas = []
    for r in sel.itertuples():
        pid = int(r.id_produto)
        info = prod.loc[pid] if pid in prod.index else None
        cat = int(info["id_categoria"]) if info is not None else None
        papel = ("M" if cat in maes else "") + ("C" if cat in comps else "")
        tem_v = pid in qtd.index
        q_base = float(qtd.loc[pid, base].mean()) if tem_v else 0.0
        q_mes = qtd.loc[pid, mes] if tem_v else pd.Series(dtype=float)
        # custo implícito: (venda - lucro) / quantidade, no mês todo
        sq, sv, sl = (q_mes.sum(), ven.loc[pid, mes].sum(), luc.loc[pid, mes].sum()) if tem_v else (0, 0, 0)
        custo = (sv - sl) / sq if sq > 0 else np.nan
        tab, pv_, pa_ = r.PcoVenda, r.PcoPrmVarejo, r.PcoPrmAtac
        m_reg = tab - custo if np.isfinite(custo) else np.nan
        m_enc = pv_ - custo if np.isfinite(custo) else np.nan
        desc = (1 - pv_ / tab) * 100 if tab and tab > 0 and pv_ and pv_ > 0 else np.nan
        nec = aum = estado = None
        pm = sv / sq if sq > 0 else np.nan       # preço médio realmente praticado no mês
        diverge = bool(np.isfinite(pm) and tab and tab > 0 and abs(pm / tab - 1) > 0.35)
        if not np.isfinite(custo):
            estado = "sem venda no mês"
        elif diverge:
            estado = "preço divergente"          # venda a preço bem diferente da tabela: custo implícito pouco confiável
        elif not (np.isfinite(desc) and desc > 0):
            estado = "sem desconto"
        elif m_enc <= 0:
            estado = "abaixo do custo"
        elif m_reg <= 0:
            estado = "margem normal ≤ 0"
        else:
            nec = volume_necessario(q_base, m_reg, m_enc)
            aum = (m_reg / m_enc - 1) * 100
            estado = "ok"
        diarios = q_mes[q_mes > 0] if tem_v else pd.Series(dtype=float)
        p90 = float(np.percentile(diarios, 90)) if len(diarios) else None
        mx = float(diarios.max()) if len(diarios) else None
        viab = None
        if estado == "ok":
            if q_base <= 0:
                viab = "sem histórico"
            elif nec <= (p90 or 0):
                viab = "plausível"
            elif nec <= (mx or 0):
                viab = "exige pico"
            else:
                viab = "acima do histórico"
        u4 = float(qtd.loc[pid, ultimos].mean()) if tem_v else 0.0
        v4 = ven.loc[pid, ultimos].sum() if tem_v else 0.0
        q4 = qtd.loc[pid, ultimos].sum() if tem_v else 0.0
        pr4 = v4 / q4 if q4 > 0 else np.nan
        promo_ativa = bool(np.isfinite(pr4) and pv_ and abs(pr4 / pv_ - 1) <= TOL_PRECO)
        cm = []
        if "M" in papel:
            n_, tem_ = att_mae.get(cat, (0, 0))
            cm = [nome_cat.get(x, str(x)) for x in comps_de.get(cat, [])][:6]
        else:
            n_ = tem_ = 0
        linhas.append({
            "id": pid, "n": r.PRODUTO.split(" - ", 1)[-1], "tp": r.TIPOPROMOCAO, "cat": nome_cat.get(cat, ""),
            "dep": info["departamento"] if info is not None else "", "papel": papel or "-",
            "tab": _r(tab, 2), "pv": _r(pv_, 2), "pa": _r(pa_, 2), "ds": _r(desc, 1), "cu": _r(custo, 2),
            "mr": _r(m_reg, 2), "me": _r(m_enc, 2), "vb": _r(q_base, 2), "vn": _r(nec, 2), "au": _r(aum, 0),
            "ex": _r(nec - q_base if nec is not None else None, 2),
            "mt": _r(m_reg * q_base if np.isfinite(m_reg) else None, 2),
            "pm": _r(pm, 2), "p90": _r(p90, 1), "mx": _r(mx, 0), "vi": viab, "st": estado,
            "u4": _r(u4, 2), "pr4": _r(pr4, 2), "ativa": promo_ativa,
            "lb": _r(float(luc.loc[pid, base].mean()) if tem_v else 0, 2),
            "cm": cm, "m_n": n_, "m_att": _r(tem_ / n_ if n_ else None)})

    ok = [l for l in linhas if l["st"] == "ok"]
    aums = [l["au"] for l in ok if l["au"] is not None]
    kpi = {"n": len(linhas), "n_mae": sum("M" in l["papel"] for l in linhas), "n_comp": sum("C" in l["papel"] for l in linhas),
           "n_ok": len(ok), "desc_med": _r(np.mean([l["ds"] for l in ok]) if ok else np.nan, 1),
           "aum_med": _r(np.median(aums) if aums else np.nan, 0),
           "n_plaus": sum(l["vi"] == "plausível" for l in ok), "n_pico": sum(l["vi"] == "exige pico" for l in ok),
           "n_acima": sum(l["vi"] == "acima do histórico" for l in ok),
           "n_sem_desc": sum(l["st"] == "sem desconto" for l in linhas), "n_abaixo": sum(l["st"] == "abaixo do custo" for l in linhas),
           "n_div": sum(l["st"] == "preço divergente" for l in linhas),
           "n_ativa": sum(l["ativa"] for l in linhas), "maes_enc": len({l["cat"] for l in linhas if "M" in l["papel"]}),
           "margem_dia": _r(sum(l["mt"] or 0 for l in ok), 0)}

    # ---- mães com encarte (visão estrutural, sem precisar de datas)
    por_mae = defaultdict(list)
    for l in linhas:
        if "M" in l["papel"]:
            por_mae[l["cat"]].append(l)
    maes_tab = []
    for nome, ls in por_mae.items():
        cat = next(k for k, v_ in nome_cat.items() if v_ == nome and k in maes)
        n_, tem_ = att_mae.get(cat, (0, 0))
        comp_ids = comps_de.get(cat, [])
        run = {cc: float(ven.loc[[x for x in prod.index[prod["id_categoria"] == cc] if x in ven.index], base].sum().mean())
               if len(prod.index[prod["id_categoria"] == cc]) else 0.0 for cc in comp_ids}
        maes_tab.append({
            "id": int(cat), "nome": nome, "grupo": grupo_mae.get(cat, ""), "n_enc": len(ls),
            "produtos": [x["n"] for x in ls][:8], "desc_med": _r(np.nanmean([x["ds"] for x in ls if x["ds"] is not None]) if ls else np.nan, 1),
            "cupons": n_, "att": _r(tem_ / n_ if n_ else None),
            "comps": [{"c": nome_cat[cc], "vd": _r(run[cc], 0)} for cc in sorted(run, key=lambda k: -run[k])
                      if cc in nome_cat and run[cc] > 0][:8]})
    maes_tab.sort(key=lambda x: -x["n_enc"])

    efeito = None
    jan = Path(janelas_csv) if janelas_csv else None
    if jan is not None and jan.exists():
        efeito = _efeito(jan, v, T, prod, mapa, df_cupom, maes, comps_de, nome_cat, grupo_mae, base)

    qual = [
        {"s": "ok", "t": "Fonte do encarte", "x": f"{len(linhas)} produtos de {', '.join(TIPOS_ENCARTE) or 'toda promoção'} na tabela Tipo de Preço "
                                                   f"({len(sel[sel['TIPOPRECO'].str.contains('PROMOCAO', na=False)])} linhas). Preço de tabela e promocional vêm dela."},
        {"s": "aviso", "t": "Sem datas do encarte", "x": "A tabela Tipo de Preço não tem datas e o preço praticado na venda não mostra o início do encarte "
         f"(só {kpi['n_ativa']} dos {len(linhas)} aparecem vendendo ao preço promocional nos últimos 4 dias). Para medir a influência nas vendas, "
         "preencha dados/encarte_janelas.csv." if efeito is None else "Janelas de encarte lidas de dados/encarte_janelas.csv."},
        {"s": "ok", "t": "Período-base do volume atual", "x": f"{len(base)} dias úteis: {', '.join(pd.Timestamp(d).strftime('%d/%m') for d in base)}."
         + (f" Dias com venda anormal ficaram de fora: {', '.join(pd.Timestamp(d).strftime('%d/%m') for d in excl)}." if excl else "")},
        {"s": "aviso", "t": "Custo implícito", "x": "Custo unitário = (venda − lucro) ÷ quantidade no mês, da f_Venda_atual (loja 20). Inclui o que o sistema abate como custo "
         "(impostos, frete etc.); confira com o custo de compra antes de negociar."},
        {"s": "aviso", "t": "Preço promocional", "x": "Usei o preço promocional de varejo. Itens de atacado têm preço próprio (coluna pa) que não entra na conta."},
        {"s": "aviso", "t": "Itens fora da conta", "x": f"{kpi['n_abaixo']} produtos têm preço promocional abaixo do custo implícito, "
         f"{kpi['n_div']} vendem a preço bem diferente do de tabela (custo implícito pouco confiável) e "
         f"{kpi['n_sem_desc']} não têm desconto: a conta de volume não se aplica a eles."},
    ]
    return {"kpi": kpi, "produtos": linhas, "maes": maes_tab, "efeito": efeito, "qualidade": qual,
            "base": [pd.Timestamp(d).strftime("%Y-%m-%d") for d in base],
            "ultimo": pd.Timestamp(ult).strftime("%Y-%m-%d"), "tipos": list(TIPOS_ENCARTE),
            "tipos_disponiveis": sorted(t["TIPOPROMOCAO"].dropna().unique().tolist())}


# --------------------------------------------------------------------------------------------
def _efeito(janelas_csv, v, T, prod, mapa, df_cupom, maes, comps_de, nome_cat, grupo_mae, base):
    """Influência do encarte nas vendas: precisa de datas (id_produto;inicio;fim)."""
    checar_tamanho(janelas_csv, 5)
    j = pd.read_csv(janelas_csv, sep=";", encoding="utf-8-sig", dtype=str)
    faltando = {"id_produto", "inicio", "fim"} - set(j.columns)
    if faltando:
        raise ValueError(f"encarte_janelas.csv: faltam as colunas {sorted(faltando)} (modelo: encarte_janelas_modelo.csv)")
    j = j.dropna(subset=["inicio", "fim"])
    if j.empty:
        return None
    j["id_produto"] = _num(j["id_produto"])
    try:
        j["inicio"] = pd.to_datetime(j["inicio"], format="%Y-%m-%d")
        j["fim"] = pd.to_datetime(j["fim"], format="%Y-%m-%d")
    except ValueError as e:
        raise ValueError(f"encarte_janelas.csv: datas devem estar como AAAA-MM-DD ({e})") from None
    dias_venda = set(T.index)
    enc_dias = defaultdict(set)
    for r in j.dropna(subset=["id_produto"]).itertuples():
        for d in pd.date_range(r.inicio, r.fim):
            if d in dias_venda:
                enc_dias[int(r.id_produto)].add(d)
    enc_dias = {k: s for k, s in enc_dias.items() if s}
    if not enc_dias:
        return None
    janela = sorted({d for s in enc_dias.values() for d in s})
    # base: dias úteis normais antes do primeiro dia de encarte
    base_e, _ = _dias_base(v, T, janela[0] - pd.Timedelta(days=1))
    v = v.copy()
    v["share"] = v["venda"] / v["dia"].map(T)
    pv = v.pivot_table(index="id_produto", columns="dia", values="share", aggfunc="sum", fill_value=0.0)
    b = pv[base_e].mean(axis=1)
    cat_of = prod["id_categoria"]
    enc_prod = set(enc_dias)
    prods_da_cat = defaultdict(list)
    for pid in pv.index:
        if pid in cat_of.index and b.get(pid, 0) > 0:
            prods_da_cat[int(cat_of[pid])].append(pid)

    def idx(prods, dias):
        prods = [x for x in prods if x in pv.index]
        sb = b.loc[prods].sum() if prods else 0
        return pv.loc[prods, dias].sum().mean() / sb if sb else np.nan

    enc_por_cat = defaultdict(set)
    for pid in enc_prod:
        if pid in cat_of.index:
            enc_por_cat[int(cat_of[pid])].add(pid)
    maes_enc = sorted(m for m in maes if enc_por_cat.get(m))
    set_me = set(maes_enc)
    comp_cats = set().union(*[set(comps_de[m]) for m in maes_enc]) - set_me if maes_enc else set()
    P_comp = [x for cc in comp_cats for x in prods_da_cat.get(cc, []) if x not in enc_prod]
    fora = set_me | comp_cats
    P_ref = [x for x in pv.index if x in cat_of.index and int(cat_of[x]) not in fora and x not in enc_prod and b.get(x, 0) > 0]
    idx_ref, idx_comp = idx(P_ref, janela), idx(P_comp, janela)

    # itens em encarte: participação nos dias com encarte vs base
    sw = sum(pv.loc[x, d] for x in enc_prod if x in pv.index for d in enc_dias[x])
    sb = sum(b.get(x, 0) for x in enc_prod for _ in enc_dias[x])
    idx_item = sw / sb if sb else np.nan

    # cesta
    c = df_cupom.copy()
    c["dia_ts"] = pd.to_datetime(c["dia"])
    enc_pd = {(p_, d) for p_, ds in enc_dias.items() for d in ds}
    c["enc"] = [(a, b_) in enc_pd for a, b_ in zip(c["id_produto"], c["dia_ts"], strict=True)]
    flags = c.groupby(["cupom", "id_categoria"])["enc"].any()
    cc_cupom = defaultdict(dict)
    for (cp, cat), f in flags.items():
        cc_cupom[cp][int(cat)] = bool(f)
    cesta = {m: [0, 0, 0, 0] for m in maes_enc}   # n_enc, n_sem, att_enc, att_sem
    for S in cc_cupom.values():
        for m in maes_enc:
            if m in S:
                tem = bool([x for x in comps_de[m] if x in S])
                k = 0 if S[m] else 1
                cesta[m][k] += 1
                cesta[m][2 + k] += tem
    linhas = []
    for m in maes_enc:
        ne, ns, ae, as_ = cesta[m]
        pe = ae / ne if ne else np.nan; ps = as_ / ns if ns else np.nan
        z = np.nan
        if ne >= MIN_CUPONS and ns >= MIN_CUPONS:
            pp = (ae + as_) / (ne + ns)
            se = np.sqrt(pp * (1 - pp) * (1 / ne + 1 / ns)) if 0 < pp < 1 else np.nan
            z = (pe - ps) / se if se else np.nan
        comp_m = [x for cc in comps_de[m] if cc not in set_me for x in prods_da_cat.get(cc, []) if x not in enc_prod]
        E = [x for x in enc_por_cat[m] if x in pv.index]
        swm = sum(pv.loc[x, d] for x in E for d in enc_dias[x])
        sbm = sum(b.get(x, 0) for x in E for _ in enc_dias[x])
        linhas.append({"id": int(m), "nome": nome_cat.get(m, str(m)), "grupo": grupo_mae.get(m, ""), "n_enc": len(E),
                       "idx_enc": _r(swm / sbm if sbm else np.nan), "idx_comp": _r(idx(comp_m, janela)),
                       "dif_ref": _r(idx(comp_m, janela) - idx_ref), "ne": ne, "ns": ns,
                       "att_e": _r(pe), "att_s": _r(ps), "dif_pp": _r((pe - ps) * 100 if ne and ns else np.nan, 2), "z": _r(z, 2)})
    aptas = [l for l in linhas if l["ne"] >= MIN_CUPONS and l["ns"] >= MIN_CUPONS]
    num = den = var = 0.0
    for l in aptas:
        wt = l["ne"] * l["ns"] / (l["ne"] + l["ns"])
        num += wt * (l["att_e"] - l["att_s"]); den += wt
        var += wt ** 2 * (l["att_e"] * (1 - l["att_e"]) / l["ne"] + l["att_s"] * (1 - l["att_s"]) / l["ns"])
    dif = num / den * 100 if den else np.nan
    ic = 1.96 * np.sqrt(var) / den * 100 if den else np.nan
    dc = idx_comp - idx_ref
    leit = [
        {"k": "pro" if idx_item > 1.0 else "neu", "t": "Itens em encarte",
         "x": f"Participação dos itens em encarte nos dias de encarte: índice {_fmt(idx_item * 100, 0)} (base 100)."},
        {"k": "pro" if dc > .03 else ("con" if dc < -.03 else "neu"), "t": "Complementares das mães em encarte",
         "x": f"Índice {_fmt(idx_comp * 100, 0)} contra {_fmt(idx_ref * 100, 0)} do resto da loja ({_fmt(dc * 100, 0, True)} pontos)."},
        {"k": "pro" if (np.isfinite(dif) and dif - ic > 0) else ("con" if (np.isfinite(dif) and dif + ic < 0) else "neu"),
         "t": "Venda casada na cesta",
         "x": (f"Cupons com item da mãe em encarte levam complementar {_fmt(dif, 1, True)} p.p. (±{_fmt(ic, 1)}) em relação aos sem encarte."
               if np.isfinite(dif) else
               f"Amostra insuficiente: nenhuma mãe tem {MIN_CUPONS}+ cupons com item em encarte e {MIN_CUPONS}+ sem. "
               "Com mais dias de cupons (o export do Power BI cortou em 30/10) a comparação passa a valer.")}]
    return {"janela": [pd.Timestamp(d).strftime("%Y-%m-%d") for d in janela], "base": [pd.Timestamp(d).strftime("%Y-%m-%d") for d in base_e],
            "kpi": {"idx_item": _r(idx_item), "idx_comp": _r(idx_comp), "idx_ref": _r(idx_ref), "cesta_dif": _r(dif, 2), "cesta_ic": _r(ic, 2)},
            "maes": linhas, "leitura": leit}

"""Dados SINTÉTICOS para testes. Nada aqui vem da empresa.

`criar_dataset(destino, payload)` grava, em `destino`, os mesmos arquivos que o pipeline lê
(cupons em Excel, CSVs de apoio exportados do Power BI, tabela Tipo de Preço). Se `payload`
for informado, ele é anexado a TODO campo de texto: é assim que o teste de ataque verifica
se algum texto dos dados consegue virar código no site.
"""
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

# Cadeia de ataque: quebra de atributo, <img onerror>, <svg onload>, fechamento de <script>,
# comentário HTML, separadores de linha Unicode e fórmula de planilha.
PAYLOAD_XSS = (
    '"><img src=x onerror="window.__pwn=1;document.title=\'PWNED\'">'
    "<svg/onload=window.__pwn=1></script><script>window.__pwn=1</script><!--"
    "  '-alert(1)-'"
)
PAYLOAD_FORMULA = '=HYPERLINK("http://evil.example","x")'

CATS = {  # id -> (nome, papel)
    10: ("CAFE", "MAE"), 11: ("ARROZ", "MAE"),
    20: ("ACUCAR", "COMPLEMENTAR"), 21: ("OLEO", "COMPLEMENTAR"), 30: ("OUTROS", "PADRAO"),
}
PRODUTOS_POR_CAT = {10: range(1001, 1006), 11: range(1006, 1011), 20: range(1011, 1016),
                    21: range(1016, 1021), 30: range(1021, 1031)}
MAPA = [(10, 20), (10, 21), (11, 21)]
DIAS_VENDA = [date(2026, 10, 5) + timedelta(days=i) for i in range(30)]   # 05/10 a 03/11
DIAS_CUPOM = [date(2026, 10, 26), date(2026, 10, 27), date(2026, 10, 28)]
ENCARTE = [1001, 1006, 1011, 1021]


def criar_dataset(destino: Path, payload: str = "") -> dict:
    p = payload
    destino = Path(destino)
    destino.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(42)

    prod_rows = []
    for cat, ids in PRODUTOS_POR_CAT.items():
        for pid in ids:
            prod_rows.append({
                "id_produto": pid, "produto": f"PRODUTO {pid}{p}", "id_categoria": cat,
                "categoria": CATS[cat][0] + p, "departamento": "MERCEARIA" + p, "secao": "SECAO" + p,
                "setor": "REPOSICAO" + p, "marca": "MARCA" + p,
                "tipo_produto": "COMPLEMENTAR" if CATS[cat][1] == "COMPLEMENTAR" else "PADRÃO"})
    prod = pd.DataFrame(prod_rows)
    prod.to_csv(destino / "produtos_cupom.csv", sep=";", index=False, encoding="utf-8-sig")
    prod.to_csv(destino / "produtos_loja20.csv", sep=";", index=False, encoding="utf-8-sig")

    pd.DataFrame([{"grupo": "G01" + p, "id_categoria_mae": m, "categoria_mae": CATS[m][0] + p,
                   "id_categoria_complementar": c, "categoria_complementar": CATS[c][0] + p,
                   "relacao": "Preparo conjunto" + p, "forca": "ALTA" + p, "motivo": "Teste" + p}
                  for m, c in MAPA]).to_csv(destino / "mapa_mae_complementar.csv", sep=";", index=False,
                                            encoding="utf-8-sig")
    pd.DataFrame([{"id_categoria": k, "categoria": v[0] + p, "papel": v[1]} for k, v in CATS.items()]
                 ).to_csv(destino / "categorias.csv", sep=";", index=False, encoding="utf-8-sig")

    vendas = []
    for d in DIAS_VENDA:
        for pid in prod["id_produto"]:
            v = float(rng.uniform(20, 400))
            vendas.append({"dia_venda": d.isoformat(), "id_produto": pid, "venda": round(v, 2),
                           "quantidade": round(v / 10, 2), "lucro": round(v * 0.2, 2)})
    pd.DataFrame(vendas).to_csv(destino / "venda_dia_produto_loja20.csv", sep=";", index=False,
                                encoding="utf-8-sig")

    # Tipo de Preço: pipe, vírgula decimal, cp1252, cabeçalho com coluna repetida (como o real)
    linhas = ["EMPRESA|FILIAL|TIPOPRECO|TIPOPROMOCAO|MotivoAlteracao|SETOR|DEPARTAMENTO|SECAO|PRODUTO|"
              "QtdProd|PcoVenda|PcoPrmVarejo|PcoPrmAtac|MotivoAlteracao"]
    for pid in ENCARTE:
        linhas.append(f"2 - EMPRESA|20 - LOJA|2 - PROMOCAO|2 - ENCARTE{p}|12 - MOTIVO|1 - REP|MERCEARIA|SEC|"
                      f"{pid} - PRODUTO {pid}{p}|0|19,90|14,90|14,90|12 - MOTIVO")
    (destino / "1082.csv").write_text("\n".join(linhas) + "\n", encoding="cp1252", errors="replace")

    # cupons (Excel): linha de filtros, cabeçalho, dados
    cup = []
    for d in DIAS_CUPOM:
        for _ in range(40):
            itens = rng.choice(np.arange(1001, 1031), size=int(rng.integers(2, 5)), replace=False)
            cid = f"20_{30300000000 + len(cup)}_303_{d.isoformat()} 00:00:00"
            for pid in itens:
                cup.append(["20 - LOJA TESTE" + p, pd.Timestamp(d), cid, f"{pid} - PRODUTO {pid}{p}",
                            round(float(rng.uniform(3, 60)), 2)])
    cab = ["Filial", "'Cupom'[DIA]", "CUPOM", "PRODUTO", "Vlr Venda R$"]
    filtros = "Filtros aplicados: \nFilial é 20 - LOJA TESTE" + p
    bruto = [[filtros, None, None, None, None], cab] + cup
    pd.DataFrame(bruto).to_excel(destino / "Cupom Produtos.xlsx", header=False, index=False)

    return {"cupons": destino / "Cupom Produtos.xlsx", "dados": destino, "tipopreco": destino / "1082.csv"}

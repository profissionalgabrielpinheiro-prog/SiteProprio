"""Utilitários comuns dos testes."""
from pathlib import Path

import fixtures

from cupons.config import Config
from cupons.pipeline import main


def gerar(tmp: Path, payload: str = "", janelas: bool = False, max_mb: int = 50) -> Config:
    """Gera o site a partir do dataset sintético e devolve a Config usada."""
    ds = fixtures.criar_dataset(tmp / "dados", payload)
    if janelas:  # datas de encarte -> exercita também a parte de "influência" do site
        import pandas as pd
        pd.DataFrame({"id_produto": fixtures.ENCARTE, "inicio": "2026-10-26", "fim": "2026-10-28"}).to_csv(
            ds["dados"] / "encarte_janelas.csv", sep=";", index=False)
    cfg = Config(raiz=tmp, dados=ds["dados"], entrada=ds["dados"] / "entrada", saida=tmp / "site" / "index.html",
                 tipopreco_csv=ds["tipopreco"], max_mb=max_mb)
    main([str(ds["cupons"])], cfg)
    return cfg

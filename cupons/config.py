"""Configuração: caminhos e limites. Nenhum caminho pessoal fica no código.

Ordem de precedência: variável de ambiente > config.local.toml (fora do Git) > padrão relativo
ao projeto. Veja config.exemplo.toml.
"""
import os
import tomllib
from dataclasses import dataclass
from pathlib import Path

from .seguranca import dentro_de

RAIZ = Path(__file__).resolve().parent.parent
MAX_MB_PADRAO = 600


@dataclass(frozen=True)
class Config:
    raiz: Path
    dados: Path           # CSVs de apoio exportados do Power BI (NÃO vão para o Git)
    entrada: Path         # exportações de cupons (xlsx/csv) soltas aqui
    saida: Path           # HTML gerado
    tipopreco_csv: Path   # tabela Tipo de Preço (encarte)
    max_mb: int = MAX_MB_PADRAO

    @classmethod
    def carregar(cls, raiz: Path | None = None) -> "Config":
        raiz = Path(raiz or RAIZ).resolve()
        local = {}
        arq = raiz / "config.local.toml"
        if arq.exists():
            local = tomllib.loads(arq.read_text(encoding="utf-8")).get("caminhos", {})

        def pega(env, chave, padrao):
            return Path(os.environ.get(env) or local.get(chave) or padrao)

        dados = pega("CUPONS_DADOS", "dados", raiz / "dados")
        saida = pega("CUPONS_SAIDA", "saida", raiz / "site" / "index.html")
        if saida.suffix.lower() != ".html":
            raise ValueError("CUPONS_SAIDA precisa terminar em .html")
        return cls(
            raiz=raiz, dados=dados.resolve(),
            entrada=pega("CUPONS_ENTRADA", "entrada", dados / "entrada").resolve(),
            # a saída só pode ficar dentro do projeto: impede sobrescrever arquivo de outro lugar
            saida=dentro_de(saida, raiz),
            tipopreco_csv=pega("CUPONS_TIPOPRECO", "tipopreco", dados / "tipo_preco.csv").resolve(),
            max_mb=int(os.environ.get("CUPONS_MAX_MB") or local.get("max_mb") or MAX_MB_PADRAO))

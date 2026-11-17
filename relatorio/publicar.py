"""Cifra o relatório e grava `publico/` (index.html + _headers) pronto para o Cloudflare Pages.

Uso (PowerShell):
    $env:RELATORIO_USUARIO = "usuario"; $env:RELATORIO_SENHA = "senha-longa-aqui"
    python gerar_relatorio.py          # gera 'Relatorio Loja 20.html' (aberto, só local)
    python publicar.py                 # gera publico/ cifrado
    wrangler pages deploy publico --project-name=<projeto>

A senha nunca vai para o código nem para o Git. Publique SOMENTE a pasta publico/.
"""
import os
import sys
from pathlib import Path

import protecao

AQUI = Path(__file__).resolve().parent


def main() -> None:
    usuario, senha = os.environ.get("RELATORIO_USUARIO", ""), os.environ.get("RELATORIO_SENHA", "")
    if not usuario or not senha:
        sys.exit("Defina RELATORIO_USUARIO e RELATORIO_SENHA (mínimo 8 caracteres).")
    origem = AQUI / "Relatorio Loja 20.html"
    if not origem.exists():
        sys.exit("Rode antes: python gerar_relatorio.py")
    saida = protecao.publicar(origem, AQUI / "publico", usuario, senha)
    print("cifrado em:", saida, f"({saida.stat().st_size / 1024:.0f} KB)")


if __name__ == "__main__":
    main()

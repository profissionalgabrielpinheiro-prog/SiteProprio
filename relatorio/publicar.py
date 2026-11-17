"""Cifra o relatório e grava `publico/` (index.html + _headers) pronto para o Cloudflare Pages.

Uso (PowerShell):
    $env:RELATORIO_USUARIO = "usuario"; $env:RELATORIO_SENHA = "senha-longa-aqui"
    python gerar_relatorio.py          # gera o HTML local, a versão leve e as partes por filial
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
    origem = AQUI / "Relatorio Loja 20 (leve).html"
    if not origem.exists():
        sys.exit("Rode antes: python gerar_relatorio.py")
    partes = AQUI / "partes"
    if not partes.exists() or not list(partes.glob("*.json")):
        sys.exit("Faltam as partes por filial: rode antes python gerar_relatorio.py")
    saida = protecao.publicar(origem, AQUI / "publico", usuario, senha, partes)
    print("cifrado em:", saida, f"({saida.stat().st_size / 1024:.0f} KB)")
    for arq in sorted((AQUI / "publico").rglob("*")):
        if arq.is_file():
            tam = arq.stat().st_size
            print(f"  {arq.relative_to(AQUI / 'publico')}  {tam / 1024 / 1024:.1f} MB")
            if tam > 24 * 1024 * 1024:
                sys.exit(f"{arq.name} passa do limite de 25 MB do Cloudflare Pages.")


if __name__ == "__main__":
    main()

"""Guarda anti-vazamento: falha se dados da empresa ou segredos forem versionados.

Usos:
    python scripts/bloquear_dados.py            # confere TODOS os arquivos versionados (CI)
    python scripts/bloquear_dados.py --staged   # confere só o que está no commit (pre-commit)

É a segunda barreira depois do .gitignore: o .gitignore não impede `git add -f`, este guarda sim.
"""
import re
import subprocess
import sys
from pathlib import Path

EXTENSOES_PROIBIDAS = {".xlsx", ".xlsm", ".xls", ".csv", ".parquet", ".pbix", ".pbit", ".zip", ".7z", ".pem", ".key", ".pfx", ".p12"}
PERMITIDOS = {"dados/README.md", "dados/entrada/.gitkeep"}
PREFIXOS_PROIBIDOS = ("dados/", "site/")
NOMES_PROIBIDOS = {".env", "config.local.toml"}
PADROES_SEGREDO = [
    (re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----"), "chave privada"),
    (re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b"), "token do GitHub"),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "chave de acesso AWS"),
    (re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}\b"), "token do Slack"),
    (re.compile(r"(?i)\b(?:senha|password|passwd|pwd|secret|token|api[_-]?key)\b\s*[:=]\s*[\"'][^\"'\s]{6,}[\"']"), "credencial atribuída no código"),
    (re.compile(r"\b\d{3}\.\d{3}\.\d{3}-\d{2}\b"), "CPF"),
]
EXTENSOES_TEXTO = {".py", ".ps1", ".md", ".toml", ".yml", ".yaml", ".txt", ".html", ".in", ".cfg", ".ini", ".json"}


def verificar(arquivos, ler=None):
    """Devolve a lista de problemas encontrados em `arquivos` (caminhos relativos, com /)."""
    ler = ler or (lambda f: Path(f).read_text(encoding="utf-8", errors="ignore"))
    problemas = []
    for f in arquivos:
        f = f.replace("\\", "/")
        p = Path(f)
        if f in PERMITIDOS:
            continue
        if p.name in NOMES_PROIBIDOS or p.suffix.lower() in EXTENSOES_PROIBIDAS or f.startswith(PREFIXOS_PROIBIDOS):
            problemas.append(f"{f}: arquivo de dados/segredo não pode ser versionado")
            continue
        if p.suffix.lower() in EXTENSOES_TEXTO and p.name != "bloquear_dados.py":
            try:
                texto = ler(f)
            except OSError:
                continue
            for rx, nome in PADROES_SEGREDO:
                if rx.search(texto):
                    problemas.append(f"{f}: possível {nome}")
    return problemas


def _git(*args):
    return subprocess.run(["git", *args], capture_output=True, text=True, check=True).stdout.split("\n")  # noqa: S603, S607


def main(argv):
    arquivos = [x for x in (_git("diff", "--cached", "--name-only", "--diff-filter=ACMR") if "--staged" in argv
                            else _git("ls-files")) if x]
    problemas = verificar(arquivos)
    for p in problemas:
        print("BLOQUEADO:", p)
    if problemas:
        print(f"\n{len(problemas)} problema(s). Dados e segredos ficam fora do Git (veja docs/SEGURANCA.md).")
        return 1
    print(f"ok: {len(arquivos)} arquivos sem dados da empresa nem segredos.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

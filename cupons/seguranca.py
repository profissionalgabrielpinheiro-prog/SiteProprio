"""Controles de segurança do gerador. Tudo que toca dado não confiável passa por aqui.

Ameaças tratadas (detalhes em docs/SEGURANCA.md):
  * XSS / quebra de página por texto malicioso nos dados  -> json_para_script + CSP;
  * injeção de fórmula em planilha (CSV injection)         -> texto_csv;
  * arquivo de entrada gigante (negação de serviço)        -> checar_tamanho;
  * escrita fora da pasta do projeto                       -> dentro_de.
"""
import base64
import hashlib
import json
import re
from pathlib import Path

_ESCAPES_SCRIPT = {
    "<": "\\u003c", ">": "\\u003e", "&": "\\u0026",
    " ": "\\u2028", " ": "\\u2029",
}
_PREFIXOS_FORMULA = ("=", "+", "-", "@", "\t", "\r", "\n")


def json_para_script(obj) -> str:
    """JSON seguro para ficar DENTRO de um <script> inline.

    Escapar só `</script>` não basta: `<!--` seguido de `<script` põe o analisador de HTML em
    "script data double escaped" e o `</script>` verdadeiro deixa de fechar o bloco (a página
    inteira vira texto de script). Por isso todo `<`, `>` e `&` vira \\uXXXX, o que é JSON/JS
    válido e idêntico para o navegador, mas invisível para o analisador de HTML.
    """
    txt = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
    return "".join(_ESCAPES_SCRIPT.get(c, c) for c in txt)


def texto_csv(valor):
    """Neutraliza fórmulas em CSV/Excel: texto que começa com = + - @ ganha um apóstrofo."""
    if isinstance(valor, str) and valor.startswith(_PREFIXOS_FORMULA):
        return "'" + valor
    return valor


def checar_tamanho(caminho: Path, max_mb: int) -> None:
    """Recusa arquivo de entrada maior que o limite (proteção contra DoS por memória)."""
    tamanho = Path(caminho).stat().st_size
    if tamanho > max_mb * 1024 * 1024:
        raise ValueError(f"{Path(caminho).name}: {tamanho / 1048576:.0f} MB passa do limite de {max_mb} MB "
                         "(ajuste CUPONS_MAX_MB só se confiar na origem do arquivo).")


def dentro_de(caminho: Path, raiz: Path) -> Path:
    """Resolve `caminho` e garante que fica dentro de `raiz` (sem `..` nem link para fora)."""
    p, r = Path(caminho).resolve(), Path(raiz).resolve()
    try:
        p.relative_to(r)
    except ValueError:
        raise ValueError(f"Caminho fora da pasta permitida: {p} (permitido: {r})") from None
    return p


def _sha256_b64(texto: str) -> str:
    return "sha256-" + base64.b64encode(hashlib.sha256(texto.encode("utf-8")).digest()).decode("ascii")


def calcular_csp(html: str) -> str:
    """Monta a Content-Security-Policy para o HTML final.

    O site tem exatamente um <script> e um <style> inline; cada um é liberado pelo seu hash
    SHA-256. Sem 'unsafe-inline' para script: handlers on*, javascript: e scripts injetados
    não executam, mesmo que algum escape falhe no futuro. Sem rede (connect-src 'none') e sem
    imagens externas, então nada é exfiltrado. Atributos style="..." são usados pelos gráficos
    (style-src-attr), mas não podem carregar nada externo.
    """
    scripts = re.findall(r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>", html, re.S)
    estilos = re.findall(r"<style[^>]*>(.*?)</style>", html, re.S)
    if len(scripts) != 1 or len(estilos) != 1:
        raise ValueError(f"Esperava 1 <script> e 1 <style> inline; achei {len(scripts)} e {len(estilos)}.")
    return "; ".join([
        "default-src 'none'",
        f"script-src '{_sha256_b64(scripts[0])}'",
        f"style-src-elem '{_sha256_b64(estilos[0])}'",
        "style-src-attr 'unsafe-inline'",
        "img-src data:",
        "connect-src 'none'", "font-src 'none'", "frame-src 'none'", "worker-src 'none'",
        "media-src 'none'", "manifest-src 'none'", "object-src 'none'",
        "base-uri 'none'", "form-action 'none'",
    ])


def aplicar_csp(html: str) -> str:
    """Troca o marcador __CSP__ do template pela política calculada para este HTML."""
    if "__CSP__" not in html:
        raise ValueError("Template sem o marcador __CSP__ na meta Content-Security-Policy.")
    return html.replace("__CSP__", calcular_csp(html.replace("__CSP__", "")), 1)

"""Ataque automatizado no navegador. Roda na CI e antes de cada release.

Dois cenários, de propósito:
  * COM CSP (como o site é entregue): nada pode executar nem aparecer injetado;
  * SEM CSP (só no teste): mede se o ESCAPE sozinho segura o ataque. A CSP é a segunda barreira.
E um experimento de controle: se uma falha de escape existisse, a CSP bloquearia a execução?
"""
import pytest
from ataque_navegador import achar_navegador, auditar
from conftest import gerar
from fixtures import PAYLOAD_XSS

pytestmark = [pytest.mark.navegador, pytest.mark.skipif(not achar_navegador(), reason="Edge/Chrome não encontrado")]


@pytest.mark.parametrize("sem_csp", [False, True], ids=["com-csp", "so-escape"])
def test_payload_em_todos_os_campos_nao_executa_nem_injeta(tmp_path, sem_csp):
    cfg = gerar(tmp_path, PAYLOAD_XSS, janelas=True)
    r = auditar(cfg.saida, PAYLOAD_XSS, sem_csp=sem_csp)
    assert "erro" not in r, r
    assert r["passos"] > 30, "a auditoria precisa ter exercitado as abas, filtros e tooltips"
    assert not r["pwn"], r["achados"][:3]
    assert r["achados"] == [], r["achados"][:3]
    assert r["dom_img_x"] == 0 and r["dom_svg_onload"] == 0


def test_controle_csp_bloqueia_handler_inline_injetado(tmp_path):
    """Simula uma falha de escape futura: injeta <img onerror> direto no HTML final."""
    cfg = gerar(tmp_path)
    html = cfg.saida.read_text(encoding="utf-8").replace(
        "</body>", "<img src=x onerror=\"window.__pwn=1;document.title='PWNED'\"></body>")
    atacado = tmp_path / "atacado.html"
    atacado.write_text(html, encoding="utf-8")
    protegido = auditar(atacado, "x", sem_csp=False)
    exposto = auditar(atacado, "x", sem_csp=True)
    assert exposto["pwn"], "o experimento de controle precisa conseguir executar sem CSP (senão o teste não prova nada)"
    assert not protegido["pwn"], "a CSP deveria ter bloqueado o handler injetado"

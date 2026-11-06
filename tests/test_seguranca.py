import base64
import hashlib
import json
import re

import pytest
from fixtures import PAYLOAD_XSS

from cupons.config import Config
from cupons.seguranca import aplicar_csp, calcular_csp, checar_tamanho, dentro_de, json_para_script, texto_csv


def test_json_para_script_nao_tem_caracteres_perigosos():
    obj = {"nome": PAYLOAD_XSS, "lista": ["</script>", "<!--", "<script>", "a&b"]}
    js = json_para_script(obj)
    for c in "<>&  ":
        assert c not in js, f"caractere {c!r} sobrou no JSON embutido"


def test_json_para_script_e_equivalente_ao_original():
    obj = {"nome": PAYLOAD_XSS, "n": [1, 2.5, None], "u": "ação ç"}
    assert json.loads(json_para_script(obj)) == obj


@pytest.mark.parametrize("entrada,esperado", [
    ("=HYPERLINK(\"x\")", "'=HYPERLINK(\"x\")"), ("+1+1", "'+1+1"), ("-2+3", "'-2+3"), ("@SUM(A1)", "'@SUM(A1)"),
    ("\t=1", "'\t=1"), ("PRODUTO NORMAL", "PRODUTO NORMAL"), ("", ""), (5, 5),
])
def test_texto_csv_neutraliza_formula(entrada, esperado):
    assert texto_csv(entrada) == esperado


def test_checar_tamanho(tmp_path):
    f = tmp_path / "a.csv"
    f.write_bytes(b"x" * 2048)
    checar_tamanho(f, 1)
    with pytest.raises(ValueError, match="passa do limite"):
        checar_tamanho(f, 0)


def test_dentro_de_bloqueia_saida_da_pasta(tmp_path):
    assert dentro_de(tmp_path / "a" / "b.html", tmp_path)
    with pytest.raises(ValueError, match="fora da pasta"):
        dentro_de(tmp_path / ".." / "fora.html", tmp_path)


def test_config_recusa_saida_fora_do_projeto(tmp_path, monkeypatch):
    monkeypatch.setenv("CUPONS_SAIDA", str(tmp_path.parent / "fora.html"))
    with pytest.raises(ValueError, match="fora da pasta"):
        Config.carregar(tmp_path)
    monkeypatch.setenv("CUPONS_SAIDA", str(tmp_path / "x.txt"))
    with pytest.raises(ValueError, match=".html"):
        Config.carregar(tmp_path)


def _hash(txt):
    return "sha256-" + base64.b64encode(hashlib.sha256(txt.encode()).digest()).decode()


def test_csp_usa_hash_do_script_e_do_estilo():
    html = '<meta content="__CSP__"><style>a{}</style><script>var x=1;</script>'
    final = aplicar_csp(html)
    csp = re.search(r'content="([^"]+)"', final).group(1)
    assert f"script-src '{_hash('var x=1;')}'" in csp
    assert f"style-src-elem '{_hash('a{}')}'" in csp
    assert "unsafe-inline" not in csp.split("style-src-attr")[0]          # script/estilo-elemento sem unsafe-inline
    assert "script-src 'unsafe" not in csp and "connect-src 'none'" in csp and "default-src 'none'" in csp


def test_csp_exige_exatamente_um_script_e_um_estilo():
    with pytest.raises(ValueError):
        calcular_csp("<style>a{}</style><script>1</script><script>2</script>")
    with pytest.raises(ValueError):
        calcular_csp("<script>1</script>")
    with pytest.raises(ValueError, match="marcador"):
        aplicar_csp("<script>1</script><style>a{}</style>")

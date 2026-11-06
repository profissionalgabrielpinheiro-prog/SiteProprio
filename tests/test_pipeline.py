import base64
import hashlib
import json
import re

import pytest
from conftest import gerar
from fixtures import PAYLOAD_FORMULA, PAYLOAD_XSS, criar_dataset

from cupons.config import Config
from cupons.pipeline import main


def _html(cfg):
    return cfg.saida.read_text(encoding="utf-8")


def _dados(html):
    m = re.search(r"const D = (.*?);\n\(function\(\)\{", html, re.S)
    assert m, "não achei o JSON de dados"
    return m.group(1)


def test_gera_site_completo(tmp_path):
    html = _html(gerar(tmp_path))
    d = json.loads(_dados(html))
    assert d["meta"]["cupons"] == 120 and d["enc"] is not None and len(d["enc"]["produtos"]) == 4
    assert d["enc"]["efeito"] is None          # sem encarte_janelas.csv


def test_site_nao_chama_nada_externo(tmp_path):
    html = _html(gerar(tmp_path))
    assert "http://" not in html and "https://" not in html, "o site não pode carregar recursos de fora"
    assert "googleapis" not in html and "<link" not in html and " src=" not in html


def test_csp_confere_com_o_conteudo(tmp_path):
    html = _html(gerar(tmp_path))
    csp = re.search(r'http-equiv="Content-Security-Policy" content="([^"]+)"', html).group(1)
    script = re.search(r"<script>(.*?)</script>", html, re.S).group(1)
    estilo = re.search(r"<style>(.*?)</style>", html, re.S).group(1)
    h = lambda t: "sha256-" + base64.b64encode(hashlib.sha256(t.encode()).digest()).decode()  # noqa: E731
    assert h(script) in csp and h(estilo) in csp and "__CSP__" not in html


def test_payload_nao_quebra_o_script(tmp_path):
    """Ataque 1 (versão antiga): `<!--` + `<script` nos dados fazia o </script> verdadeiro não fechar."""
    html = _html(gerar(tmp_path, PAYLOAD_XSS))
    dados = _dados(html)
    assert "<" not in dados and ">" not in dados and " " not in dados
    assert html.count("<script") == 1 and html.count("</script>") == 1
    assert json.loads(dados)["meta"]["loja"].endswith(PAYLOAD_XSS)    # dado preservado, só inofensivo


def test_csv_modelo_nao_vira_formula(tmp_path):
    """Ataque 2 (versão antiga): nome de produto com `=` virava fórmula ao abrir o modelo no Excel."""
    ds = criar_dataset(tmp_path / "dados")
    t = ds["tipopreco"].read_text(encoding="cp1252").replace("1001 - PRODUTO 1001", "1001 - " + PAYLOAD_FORMULA)
    ds["tipopreco"].write_text(t, encoding="cp1252")
    cfg = Config(raiz=tmp_path, dados=ds["dados"], entrada=ds["dados"] / "entrada", saida=tmp_path / "s" / "i.html",
                 tipopreco_csv=ds["tipopreco"], max_mb=50)
    main([str(ds["cupons"])], cfg)
    linhas = (ds["dados"] / "encarte_janelas_modelo.csv").read_text(encoding="utf-8-sig").splitlines()
    alvo = [x for x in linhas if "HYPERLINK" in x][0]
    assert alvo.split(";")[1].lstrip('"').startswith("'="), alvo


def test_arquivo_grande_demais_e_recusado(tmp_path):
    with pytest.raises(ValueError, match="passa do limite"):
        gerar(tmp_path, max_mb=0)


def test_saida_fora_do_projeto_e_recusada(tmp_path):
    ds = criar_dataset(tmp_path / "dados")
    with pytest.raises(ValueError, match="fora da pasta"):
        Config(raiz=tmp_path, dados=ds["dados"], entrada=ds["dados"], saida=__import__("cupons.seguranca", fromlist=["x"]).dentro_de(
            tmp_path.parent / "fora.html", tmp_path), tipopreco_csv=ds["tipopreco"])


def test_janelas_de_encarte_validas_geram_efeito(tmp_path):
    d = json.loads(_dados(_html(gerar(tmp_path, janelas=True))))
    assert d["enc"]["efeito"] is not None and d["enc"]["efeito"]["janela"][0] == "2026-10-26"


def test_janelas_com_data_invalida_dao_erro_claro(tmp_path):
    ds = criar_dataset(tmp_path / "dados")
    (ds["dados"] / "encarte_janelas.csv").write_text("id_produto;inicio;fim\n1001;26/10/2026;28/10/2026\n", encoding="utf-8")
    cfg = Config(raiz=tmp_path, dados=ds["dados"], entrada=ds["dados"], saida=tmp_path / "s" / "i.html", tipopreco_csv=ds["tipopreco"])
    with pytest.raises(ValueError, match="AAAA-MM-DD"):
        main([str(ds["cupons"])], cfg)

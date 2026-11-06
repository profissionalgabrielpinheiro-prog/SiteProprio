import importlib.util
from pathlib import Path

_spec = importlib.util.spec_from_file_location("bloquear_dados", Path(__file__).parent.parent / "scripts" / "bloquear_dados.py")
bd = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bd)


def _ler(texto):
    return lambda f: texto


def test_bloqueia_dados_e_formatos_de_negocio():
    ruins = ["dados/venda.csv", "dados/agregado.json", "site/index.html", "x/Cupom Produtos.xlsx", "a/b.pbix",
             ".env", "config.local.toml", "chave.pem"]
    assert len(bd.verificar(ruins, _ler(""))) == len(ruins)


def test_permite_codigo_e_marcadores():
    assert bd.verificar(["cupons/pipeline.py", "README.md", "dados/README.md", "dados/entrada/.gitkeep"], _ler("x = 1")) == []


def test_detecta_segredos_no_texto():
    # Montados em tempo de execução: o código-fonte não contém nenhum padrão de segredo
    # (senão o próprio Gitleaks e o guarda acusariam este arquivo).
    falsos = [
        "senha" + " = " + '"' + "abc" + "12345" + '"',
        "-----BEGIN " + "PRIVATE KEY" + "-----",
        "gh" + "p_" + "a" * 36,
        "AK" + "IA" + "A" * 16,
        "CPF 123.456." + "789-09",
    ]
    for texto in falsos:
        assert bd.verificar(["cupons/x.py"], _ler(texto)), texto


def test_nao_acusa_texto_normal():
    assert bd.verificar(["cupons/x.py"], _ler('nome = "Venda por dia"  # a senha vem de variável de ambiente')) == []

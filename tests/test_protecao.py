"""A versão publicada tem de ser cifrada de verdade: sem a senha, nenhum dado legível."""
import base64
import hashlib
import re

import pytest
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from cupons import protecao

SITE = ("<html><head><meta http-equiv=\"Content-Security-Policy\" content=\"x\"><style>a{}</style></head>"
        "<body><script>const D={\"segredo\":\"VENDA-CONFIDENCIAL\"};</script></body></html>")


def _decifra(pagina, usuario, senha):
    dado = dict(re.findall(r'data-(\w)="([^"]+)"', pagina))
    b = base64.b64decode
    chave = hashlib.pbkdf2_hmac("sha256", (usuario.lower() + "\0" + senha).encode(), b(dado["s"]),
                                int(dado["n"]), 32)
    return AESGCM(chave).decrypt(b(dado["i"]), b(dado["c"]), protecao._AAD).decode()


def test_conteudo_nao_aparece_em_claro():
    pagina = protecao.proteger(SITE, "Price", "senha-forte-1")
    assert "VENDA-CONFIDENCIAL" not in pagina and "segredo" not in pagina


def test_senha_certa_decifra_e_errada_falha():
    pagina = protecao.proteger(SITE, "Price", "senha-forte-1")
    assert _decifra(pagina, "price", "senha-forte-1") == SITE
    with pytest.raises(InvalidTag):
        _decifra(pagina, "Price", "senha-errada-9")


def test_senha_fraca_recusada():
    with pytest.raises(ValueError):
        protecao.proteger(SITE, "Price", "curta")


def test_csp_do_login_e_ascii_e_libera_so_hashes():
    pagina = protecao.proteger(SITE, "Price", "senha-forte-1")
    script = re.findall(r"<script[^>]*>(.*?)</script>", pagina, re.S)[0]
    assert script.isascii() and "\0" not in script   # o parser troca NUL por U+FFFD e quebra o hash
    assert "unsafe-inline'" not in re.search(r"script-src [^;]*", pagina).group(0)

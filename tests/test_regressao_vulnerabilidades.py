"""Regressão: recria as falhas encontradas no ataque inicial e prova que o teste as detecta.

Se alguém simplificar json_para_script de volta para `.replace("</", "<\\/")`, estes testes
quebram. Eles documentam POR QUE o escape é feito do jeito que é.
"""
import pytest
from ataque_navegador import achar_navegador, auditar
from conftest import gerar
from fixtures import PAYLOAD_XSS

import cupons.pipeline as pipeline


def _escape_antigo(obj):
    import json
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")


def test_escape_antigo_deixa_script_sem_fechar(tmp_path, monkeypatch):
    monkeypatch.setattr(pipeline, "json_para_script", _escape_antigo)
    # a CSP calcula o hash do HTML já com o JSON; o ataque ainda aparece como script a mais
    html = gerar(tmp_path, PAYLOAD_XSS).saida.read_text(encoding="utf-8")
    assert html.count("<script") > 1, "com o escape antigo o payload cria <script> extras no arquivo"


@pytest.mark.navegador
@pytest.mark.skipif(not achar_navegador(), reason="Edge/Chrome não encontrado")
def test_escape_antigo_quebra_a_pagina_no_navegador(tmp_path, monkeypatch):
    monkeypatch.setattr(pipeline, "json_para_script", _escape_antigo)
    cfg = gerar(tmp_path, PAYLOAD_XSS)
    r = auditar(cfg.saida, PAYLOAD_XSS, sem_csp=True, orcamento_ms=15000)
    assert "erro" in r or r.get("pwn"), "a falha antiga precisa ser detectada pelo teste de ataque"

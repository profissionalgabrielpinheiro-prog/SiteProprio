# Relatório Loja 20: venda × pesquisa × economia

Gera um HTML único e dinâmico a partir de dois CSVs exportados do Power BI (cupons e pesquisa de preços):
cobertura da pesquisa, preço de venda × preço da pesquisa, simulador de economia por item e
"quanto cada cupom custaria no concorrente".

**Este repositório só contém código.** Nenhum dado de venda, preço ou cupom é versionado
(ver `.gitignore`). Os CSVs ficam só na máquina de quem gera o relatório.

## Gerar e publicar (PowerShell)

```powershell
python gerar_relatorio.py                         # lê os CSVs e grava 'Relatorio Loja 20.html' (aberto, só local)

$env:RELATORIO_USUARIO = "usuario"
$env:RELATORIO_SENHA   = "senha-longa-aqui"       # mínimo 8 caracteres; nunca vai para o código nem para o Git
python publicar.py                                # cifra e grava publico/ (index.html + _headers)

wrangler pages deploy publico --project-name=<projeto>
```

Publique **somente** `publico/`, nunca o HTML aberto.

## Como a proteção funciona

`protecao.py` cifra o relatório inteiro com AES-256-GCM; a chave vem de usuário + senha
(PBKDF2-SHA256, 600 mil iterações). O arquivo publicado contém apenas texto cifrado e a tela de login:
sem a senha certa não há dado legível, nem lendo o código-fonte. Com a senha, o navegador decifra e
mostra o relatório completo. Limite honesto: quem baixar o arquivo pode tentar adivinhar a senha offline,
então use senha longa e aleatória.

## Conferência com o Power BI (opcional)

Se existir `validacao_modelo.json` (ignorado pelo Git) com os totais das medidas do modelo, o relatório
mostra a conferência modelo × Python na aba "Visão geral".

## Requisitos

`pandas` para gerar o relatório; `cryptography` para cifrar.

# Cupons Loja 20 · venda casada e encarte

Gera um site (um único HTML, modo claro e escuro) com a análise de cupons de uma loja: categorias
**mãe × complementar**, cestas, variação por dia e **produtos em encarte** (quanto vender a mais para
manter a margem depois do desconto).

> **Uso interno. Os dados são confidenciais** (vendas, margens, custos). Este repositório contém só o
> código: dados e o site gerado **nunca** vão para o Git (veja [docs/SEGURANCA.md](docs/SEGURANCA.md)).

## Como funciona

```
Power BI (modelo Produtos) ──scripts/exportar_apoio_powerbi.ps1──▶ dados/*.csv   (apoio: produto→categoria, mapa mãe/compl., vendas)
Export de cupons (.xlsx) ───────────────────────────────────────▶ dados/entrada/
Tipo de Preço (encarte) ────────────────────────────────────────▶ dados/tipo_preco.csv
                                      python -m cupons ──▶ site/index.html   (números agregados + CSP; abre direto no navegador)
```

O arquivo bruto de cupons pode ter centenas de milhares de linhas. O gerador agrega por dia, categoria
e par mãe/complementar; o navegador recalcula taxas (penetração, attach, lift) a partir dessas contagens.

## Instalação

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install --require-hashes -r requirements.txt -r requirements-dev.txt
```

`--require-hashes` recusa qualquer pacote cujo hash não esteja travado nos `requirements*.txt`
(defesa contra pacote adulterado). Para atualizar dependências, edite os `.in` e rode
`pip-compile --generate-hashes --allow-unsafe -o requirements.txt requirements.in` (idem `-dev`).

## Uso

1. Com o Power BI aberto no modelo **Produtos**, exporte as tabelas de apoio (só lê o modelo):
   `powershell -ExecutionPolicy Bypass -File scripts\exportar_apoio_powerbi.ps1`
2. Coloque a exportação de cupons em `dados/entrada/` e a tabela Tipo de Preço em `dados/tipo_preco.csv`.
3. Gere o site: `python -m cupons` (ou `python gerar_site.py`). Resultado em `site/index.html`.

Caminhos e limites: variáveis de ambiente (`CUPONS_DADOS`, `CUPONS_ENTRADA`, `CUPONS_SAIDA`,
`CUPONS_TIPOPRECO`, `CUPONS_MAX_MB`) ou `config.local.toml` (modelo em `config.exemplo.toml`; fica fora do Git).

### Medir a influência do encarte nas vendas

A tabela Tipo de Preço não traz datas. Preencha `dados/encarte_janelas.csv` (modelo gerado em
`dados/encarte_janelas_modelo.csv`: `id_produto;inicio;fim`, datas `AAAA-MM-DD`) e gere de novo.

## Testes e segurança

```powershell
.venv\Scripts\pytest          # unitários + pipeline + ATAQUE XSS no navegador (Edge/Chrome headless)
.venv\Scripts\ruff check .
.venv\Scripts\bandit -q -r cupons gerar_site.py scripts -c pyproject.toml
.venv\Scripts\pip-audit -r requirements.txt --require-hashes
python scripts\bloquear_dados.py     # nenhum dado/segredo versionado
```

Os testes usam **dados sintéticos** (`tests/fixtures.py`): nada da empresa entra no repositório.
Ligue o hook de commit uma vez: `pip install pre-commit && pre-commit install`.

A CI (`.github/workflows`) roda tudo isso a cada push/PR, mais CodeQL e Gitleaks no histórico completo.

## Estrutura

| Caminho | O que é |
|---|---|
| `cupons/pipeline.py` | leitura, agregação e geração do site |
| `cupons/encarte.py` | economia do encarte (volume necessário) e influência nas vendas |
| `cupons/seguranca.py` | controles: JSON seguro para `<script>`, CSV sem fórmula, CSP, limites |
| `cupons/templates/index.html` | interface (gráficos em SVG, sem bibliotecas nem recursos externos) |
| `scripts/` | exportação do Power BI e guarda anti-vazamento |
| `tests/` | testes, dados sintéticos e o ataque automatizado |
| `docs/` | modelo de ameaças, configuração do GitHub e relatório do ataque |

## Publicar no GitHub (resumo)

Repositório **privado**, branch `main` protegida, secret scanning com push protection e **nunca** GitHub
Pages. O passo a passo completo, com comandos, está em [docs/SEGURANCA.md](docs/SEGURANCA.md#configuração-do-repositório-no-github).

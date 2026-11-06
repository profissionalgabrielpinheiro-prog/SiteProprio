# dados/

**Nada desta pasta vai para o Git** (o `.gitignore` e a CI bloqueiam). Aqui ficam, só na sua máquina:

| Arquivo | Origem |
|---|---|
| `produtos_cupom.csv`, `produtos_loja20.csv`, `mapa_mae_complementar.csv`, `categorias.csv`, `venda_dia_produto_loja20.csv` | `scripts/exportar_apoio_powerbi.ps1` (modelo Produtos aberto no Power BI) |
| `tipo_preco.csv` | tabela Tipo de Preço (separador `\|`, vírgula decimal, cp1252) |
| `encarte_janelas.csv` (opcional) | você preenche: `id_produto;inicio;fim` (AAAA-MM-DD) |
| `entrada/` | exportações de cupons (`.xlsx` ou `.csv`) |
| `agregado.json`, `encarte_janelas_modelo.csv` | gerados pelo sistema |

Os dados de vendas e margens são **confidenciais**. Não os envie por e-mail ou chat fora da empresa e não os
anexe em issues ou PRs. Para testes, o projeto usa dados sintéticos (`tests/fixtures.py`).

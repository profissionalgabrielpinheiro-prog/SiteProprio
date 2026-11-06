# Relatório do ataque ao site

**Alvo:** `site/index.html` gerado por `gerar_site.py` (versão anterior à reorganização em `cupons/`).
**Método:** teste de caixa-cinza no ambiente de desenvolvimento, com dados sintéticos, em navegador headless
(Edge). Não houve ataque a sistema de terceiros nem a dados reais.

## Como foi feito

1. Dados sintéticos (`tests/fixtures.py`) com um **payload em todos os campos de texto** (produto, categoria,
   departamento, seção, marca, grupo, relação, força, motivo, loja, tipo de promoção):
   `"><img src=x onerror=...><svg/onload=...></script><script>...</script><!--` + U+2028/9 + `'-alert(1)-'`.
2. Geração do site com esses dados.
3. Auditoria no navegador (`tests/ataque_navegador.py`): troca todas as abas, ordena todas as colunas, clica nas
   linhas, muda todos os filtros, digita o payload nas buscas e passa o mouse sobre ~120 elementos com tooltip por aba.
   Procura execução de código (`window.__pwn`, título alterado), elementos injetados, `<script>` extra e HTML no tooltip.
4. Verificações complementares: injeção de fórmula nos CSVs gerados, bomba de XML, `bandit`, `ruff`, `pip-audit`.

## Achados

| # | Gravidade | Achado | Estado |
|---|---|---|---|
| 1 | **Alta** | **Quebra de página e manipulação do HTML via JSON embutido.** O JSON ia dentro do `<script>` escapando só `</`. O payload contém `<!--` e `<script>`, que põem o analisador de HTML em *script data double escaped*: o `</script>` verdadeiro deixa de fechar o bloco e a página inteira vira texto de script. Reproduzido: o arquivo saiu com **60 aberturas de `<script>` e 1 fechamento** e a página não renderizou. | **Corrigido** |
| 2 | Média | **Injeção de fórmula (CSV injection).** `encarte_janelas_modelo.csv`, que o sistema manda abrir no Excel, gravava o nome do produto sem proteção. Nome começando com `=` (ex.: `=HYPERLINK("http://evil.example","x")`) virava fórmula executável. Reproduzido. | **Corrigido** |
| 3 | Média | **Sem defesa em profundidade.** Nenhuma CSP: se qualquer escape falhasse, o script injetado executaria e poderia enviar dados para fora. Sem limite de tamanho de arquivo de entrada (DoS por memória). `defusedxml` (que protege contra bomba de XML em Excel) só existia por acaso no ambiente, sem ser declarado. | **Corrigido** |
| 4 | Baixa | Fonte carregada do Google Fonts: cada acesso avisa terceiro e o site depende de fora (privacidade e cadeia de suprimentos). Caminhos absolutos com nome de usuário do Windows no código. | **Corrigido** |
| 5 | Baixa | `assert` usado como trava de segurança no pipeline (removido com `python -O`). Achado do `bandit` (B101). | **Corrigido** |
| 6 | Info | Sem cabeçalhos HTTP (é arquivo estático): clickjacking possível se embutido em iframe. | **Mitigado** (guarda em JS) e documentado para hospedagem |
| 7 | **Alta** (confidencialidade) | **Dados da empresa já versionados.** A cópia enviada ao repositório `MatheusPrice` (commit `a031b74`) contém `Cupons Loja 20/dados/*.csv`, `agregado.json` e `site/index.html` (vendas, margens e custos da loja 20). | **Pendente: ação manual**, veja abaixo |

### O que **não** foi encontrado

- Com o JSON corrigido, a auditoria de 53 passos (todas as abas, ordenação, cliques, filtros, buscas e tooltips) não
  achou execução de código, elemento injetado nem HTML em tooltip: o escape de `innerHTML` (`esc()`) estava correto
  em todos os pontos exercitados. O furo real era a incorporação do JSON.
- Nenhum segredo no código (os achados do primeiro varrimento eram nomes de marca, como "SECRET" de desodorante).
- `pip-audit`: nenhuma vulnerabilidade conhecida nas dependências travadas.
- Bomba de entidades XML: bloqueada (`defusedxml` ativo; agora declarado e travado por hash).

## Correções

| Achado | Correção |
|---|---|
| 1 | `json_para_script`: todo `<`, `>`, `&`, U+2028 e U+2029 vira `\uXXXX` (JSON/JS equivalentes; invisíveis para o analisador de HTML). |
| 2 | `texto_csv` em tudo que o sistema grava em CSV a partir de dados. |
| 3 | CSP com hash do único `<script>` e `<style>` (`default-src 'none'`, `connect-src 'none'`, sem `unsafe-inline` em script); `CUPONS_MAX_MB` (padrão 600); `defusedxml` em `requirements.in`. |
| 4 | Fonte do sistema (sem requisição externa); caminhos em `config.py` (env, `config.local.toml`, padrão relativo). |
| 5 | `raise ValueError` explícito. |
| 6 | Guarda de iframe no JavaScript; cabeçalhos recomendados em `docs/SEGURANCA.md` §5. |

## Provas que ficaram no repositório

- `tests/test_ataque_xss.py`: o ataque completo, em dois cenários: **só com escape** (CSP removida na cópia de teste) e **com CSP**;
  e um *experimento de controle*: injeta `<img onerror>` direto no HTML final — **executa sem CSP e é bloqueado com CSP**,
  o que prova que a CSP é a segunda barreira e que o teste tem poder de detectar.
- `tests/test_regressao_vulnerabilidades.py`: recria o escape antigo e verifica que o ataque o detecta (a falha 1 não volta).
- `tests/test_pipeline.py`: `<` ausente do JSON embutido, um único `<script>`, hash da CSP confere, nada externo, CSV sem fórmula.
- `tests/test_seguranca.py` e `tests/test_bloquear_dados.py`: unitários dos controles.

## Ação pendente (achado 7)

O repositório `MatheusPrice` recebeu a pasta com dados. Mesmo privado, remova:

```powershell
cd ..\MatheusPrice
git rm -r --cached "Cupons Loja 20/dados" "Cupons Loja 20/site"
git commit -m "Remove dados e site gerado da pasta Cupons Loja 20"
# limpar também o HISTÓRICO (o dado continua nos commits antigos):
git filter-repo --path "Cupons Loja 20/dados" --path "Cupons Loja 20/site" --invert-paths
git push --force origin main      # combine antes com quem tiver clone
```

Depois: este projeto passa a viver em repositório próprio, privado, com a configuração de `docs/SEGURANCA.md` §3.

## Riscos residuais

- Quem recebe o HTML vê todos os números. Distribua só por canal interno com controle de acesso.
- Sem um pentest externo: este teste cobre XSS/injeção de HTML pelos dados e a cadeia de suprimentos, não infraestrutura de hospedagem.

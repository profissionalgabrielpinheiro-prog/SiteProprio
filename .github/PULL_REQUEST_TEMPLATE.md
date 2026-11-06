## O que muda

<!-- Resumo em 2 ou 3 linhas. -->

## Checklist de segurança (obrigatório)

- [ ] Nenhum dado da empresa (vendas, custos, margens, cupons) está no PR: nem em arquivo, nem em print, nem em teste.
- [ ] Nenhum segredo, token, senha ou caminho pessoal no código.
- [ ] Texto que vem dos dados e vai para o HTML passa por `esc()` (JavaScript) ou `json_para_script()` (Python).
- [ ] Texto dos dados que vai para CSV passa por `texto_csv()`.
- [ ] `pytest` e `ruff check .` passam localmente (o ataque XSS no navegador incluso).
- [ ] Se mexeu em dependência: o `.txt` foi regerado com `pip-compile --generate-hashes`.

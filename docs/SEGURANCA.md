# Segurança: modelo de ameaças e controles

## 1. O que protegemos

| Ativo | Classificação | Observação |
|---|---|---|
| Vendas, margens, custos, preços de encarte, cestas | **Confidencial** | valor competitivo; vazar para concorrente ou fornecedor causa dano |
| Código e testes | Interno | não contém dado nem segredo |
| Cupons | Sem dado pessoal | o identificador é `filial_número_caixa_data`; não há CPF, nome nem cartão |
| O site gerado (`site/index.html`) | **Confidencial** | embute todos os números agregados da loja |

Não há servidor, banco de dados, login ou API: o sistema é um gerador local que produz um arquivo estático.
Isso elimina classes inteiras de ataque (injeção SQL, sessão, CSRF, SSRF), mas concentra o risco em três
pontos: **dado não confiável virando código no HTML**, **dado confidencial saindo da máquina** e
**cadeia de suprimentos** (dependências e CI).

## 2. Ameaças e controles

| # | Ameaça | Controle | Onde | Teste que prova |
|---|---|---|---|---|
| T1 | Texto malicioso nos dados quebra a página ou injeta HTML/JS (XSS) | `json_para_script` escapa `<`, `>`, `&`, U+2028/9 no JSON embutido; `esc()` em todo texto dos dados no `innerHTML`; tooltip só aceita `<b>` do título | `cupons/seguranca.py`, `templates/index.html` | `test_payload_nao_quebra_o_script`, `test_ataque_xss.py` |
| T2 | Falha futura de escape executa script | **CSP** com hash do único `<script>` e `<style>`, sem `unsafe-inline` em script, `connect-src 'none'`, `default-src 'none'` | `calcular_csp` | `test_controle_csp_bloqueia_handler_inline_injetado` |
| T3 | Exfiltração: o site manda dado para fora | sem rede (`connect-src 'none'`), sem recurso externo, sem biblioteca de terceiros, sem fonte do Google | CSP + template | `test_site_nao_chama_nada_externo` |
| T4 | Fórmula em planilha gerada (CSV injection) | `texto_csv` prefixa `'` em texto que começa com `= + - @` | `pipeline.py` | `test_csv_modelo_nao_vira_formula` |
| T5 | Arquivo de entrada gigante / malicioso (DoS, bomba de XML) | limite `CUPONS_MAX_MB`; `defusedxml` declarado e travado (openpyxl o usa) | `checar_tamanho`, `requirements.in` | `test_arquivo_grande_demais_e_recusado` |
| T6 | Escrita fora do projeto por configuração | `saida` resolvida e obrigada a ficar dentro do projeto, extensão `.html` | `config.py`, `dentro_de` | `test_config_recusa_saida_fora_do_projeto` |
| T7 | Site embutido em outra página (clickjacking) | a meta CSP não aceita `frame-ancestors`; a página se recusa a rodar dentro de iframe | `templates/index.html` | revisão; veja §5 se hospedar |
| T8 | Dado da empresa ou segredo vai para o GitHub | `.gitignore` em lista de bloqueio, `scripts/bloquear_dados.py` (pre-commit e CI), Gitleaks no histórico completo, push protection | repositório | `test_bloquear_dados.py` |
| T9 | Pacote adulterado (cadeia de suprimentos) | `requirements*.txt` com hash (`--require-hashes`), `pip-audit`, Dependabot, revisão de dependências em PR | `requirements*.txt`, `.github/` | CI `seguranca.yml` |
| T10 | Action da CI comprometida | cada Action travada no **hash do commit**; permissões mínimas (`contents: read`); `persist-credentials: false`; sem segredos na CI | `.github/workflows` | revisão; Dependabot troca o hash |
| T11 | Guarda desligado "só dessa vez" | CODEOWNERS + proteção de branch exigindo os checks | GitHub | configuração (§3) |
| T12 | Controle removido por otimização do Python (`-O`) | travas com `raise` explícito, não `assert` | `pipeline.py` | `bandit` (B101) |

## 3. Configuração do repositório no GitHub

Faça **antes do primeiro push** e confira depois. Substitua `OWNER/REPO`.

1. **Repositório privado.** `gh repo create OWNER/REPO --private --source . --remote origin` (não use `--push` ainda).
2. **Nunca habilite GitHub Pages** (o site contém dados confidenciais). *Settings → Pages* deve ficar em "None".
3. **Autenticação:** 2FA obrigatório para todos com acesso; sem deploy keys nem tokens de longa duração; use
   `gh auth login` com escopo mínimo.
4. **Secret scanning + push protection:** *Settings → Code security*: ligar "Secret scanning" e "Push protection".
   `gh api -X PATCH repos/OWNER/REPO -f 'security_and_analysis[secret_scanning][status]=enabled' -f 'security_and_analysis[secret_scanning_push_protection][status]=enabled'`
5. **Dependabot alerts e security updates** ligados; **private vulnerability reporting** ligado.
6. **Actions:** *Settings → Actions → General*: "Allow OWNER, and select non-OWNER actions" com "Require actions to be pinned
   to a full-length commit SHA" ligado; token padrão do workflow em **Read repository contents**; "Allow GitHub Actions to
   create and approve pull requests" desligado.
7. **Proteção da branch `main`** (*Settings → Branches* ou ruleset):
   - exigir pull request com 1 aprovação e **Code Owners** (já definidos em `.github/CODEOWNERS`);
   - exigir os checks: `Testes (Python 3.12)`, `Testes (Python 3.13)`, `Dados e segredos fora do Git`,
     `Bandit e pip-audit`, `Gitleaks (histórico completo)`, `Análise CodeQL (Python)`;
   - exigir branch atualizada, resolver conversas, histórico linear, **bloquear force push e exclusão**;
   - valer também para administradores; (opcional) exigir commits assinados.
8. **Antes do primeiro push**, confira o que seria enviado:
   ```powershell
   git add -A
   .venv\Scripts\python scripts\bloquear_dados.py --staged   # tem que dizer "ok"
   git status --short                                        # nenhum .csv/.xlsx/.pbix/site/dados
   ```

## 4. Segurança no desenvolvimento

- Dependências só via `pip install --require-hashes`. Subir versão = regerar os `.txt` com `pip-compile --generate-hashes`.
- Texto dos dados nunca entra no HTML sem `esc()` e nunca entra no JSON do `<script>` sem `json_para_script()`.
- Texto dos dados nunca entra em CSV sem `texto_csv()`.
- Não adicione `unsafe-inline`/`unsafe-eval` à CSP, biblioteca de CDN, fonte externa, `eval`, `new Function`, `document.write`
  nem `javascript:` URLs. O teste de ataque e a revisão devem barrar.
- Testes usam apenas dados sintéticos. Print de tela com números reais **não** entra em issue/PR.

## 5. Se um dia o site for hospedado

Preferível: manter como arquivo interno (unidade de rede da empresa com permissão por grupo). Se hospedar:

- atrás de **SSO/VPN**; nunca público; nunca GitHub Pages;
- cabeçalhos HTTP (a meta CSP não cobre todos):
  `Content-Security-Policy` igual à da meta **mais** `frame-ancestors 'none'`, `X-Content-Type-Options: nosniff`,
  `Referrer-Policy: no-referrer`, `Permissions-Policy: ()`, `Strict-Transport-Security: max-age=31536000`,
  `Cache-Control: private, no-store`, `X-Robots-Tag: noindex`;
- registre acessos (quem abriu e quando).

## 6. Se um dado vazou

1. **Contenha:** torne o repositório privado ou apague-o imediatamente; avise o responsável pela informação.
2. **Não basta apagar o arquivo num commit novo:** o dado continua no histórico. Reescreva o histórico com
   `git filter-repo --path dados --path site --invert-paths` e faça `git push --force` (combine antes com quem tem clone).
3. Peça ao GitHub a limpeza de caches/forks/PRs (Support → "remove cached views") e revise forks.
4. **Rotacione** qualquer credencial que tenha aparecido (token, senha) e revise logs de acesso.
5. Registre o incidente: o que vazou, por quanto tempo, quem poderia ter acessado.

## 7. Limitações conhecidas

- O site embute todos os números: quem tem o arquivo vê tudo. A proteção é de **distribuição** (quem recebe o HTML), não do arquivo.
- `style-src-attr 'unsafe-inline'` é necessário para os gráficos; sem `connect-src` e sem imagens externas isso não permite exfiltração.
- A meta CSP não aplica `frame-ancestors` nem `report-uri`; por isso o guarda de iframe em JavaScript e os cabeçalhos do §5.
- O teste de ataque no navegador cobre XSS e injeção de HTML pelos campos de texto. Não substitui um pentest externo se o site for exposto.

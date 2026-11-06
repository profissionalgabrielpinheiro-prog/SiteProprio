# Política de segurança

## Reportar uma vulnerabilidade

Use **Security → Report a vulnerability** neste repositório (relato privado do GitHub). Não abra issue
pública nem cole dados da empresa em issue, PR ou comentário.

Inclua: o que acontece, passos para reproduzir e o impacto. Responderemos em até 5 dias úteis.

## O que consideramos vulnerabilidade

- texto vindo dos dados (produto, categoria, motivo...) que execute código ou injete HTML no site;
- fórmula executável em planilha gerada pelo sistema;
- segredo, dado da empresa ou caminho pessoal versionado;
- dependência com falha conhecida sem correção planejada;
- qualquer forma de o site enviar dados para fora do navegador.

## Versões suportadas

Apenas a `main`. Correções de segurança saem nela e passam por todos os testes de ataque.

## Dados

Este repositório **não** contém dados da empresa e não deve contê-los. Se algo assim for versionado por
engano, trate como incidente: siga [docs/SEGURANCA.md](docs/SEGURANCA.md#se-um-dado-vazou).

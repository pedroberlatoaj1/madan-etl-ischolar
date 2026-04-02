# Operacao via Google Sheets

Este projeto suporta um fluxo operacional sem terminal para o operador final.

O Google Sheets funciona como cliente fino:
- le a aba `Notas`;
- envia os dados para o backend;
- faz polling de validacao e envio;
- mostra dialogs simples;
- guarda `lote_id`, `snapshot_hash` e os `job_id` mais recentes localmente entre as etapas.

## 1. Subir backend e worker

Antes de rodar o backend, o worker ou os testes do webhook no ambiente de desenvolvimento:

```bash
pip install -r requirements-dev.txt
```

No servidor/backend:

```bash
.\.venv\Scripts\python.exe webhook_google_sheets.py
```

Em outro terminal:

```bash
.\.venv\Scripts\python.exe worker.py
```

Se quiser processar apenas uma rodada para teste manual:

```bash
.\.venv\Scripts\python.exe worker.py --once
```

## 2. Variaveis e configuracao minima

Obrigatorias:
- `WEBHOOK_SECRET`: segredo compartilhado entre backend e Apps Script.
- `ISCHOLAR_API_TOKEN`
- `ISCHOLAR_CODIGO_ESCOLA`

Opcionalmente configuraveis:
- `VALIDACAO_LOTE_DB`
- `APROVACAO_LOTE_DB`
- `LOTE_ITENS_DB`
- `ENVIO_LOTE_AUDIT_DB`
- `RESULTADO_ENVIO_LOTE_DB`
- `MAPA_DISCIPLINAS`
- `MAPA_AVALIACOES`
- `MAPA_PROFESSORES`
- `WEBHOOK_MAX_CONTENT_LENGTH`
- `WEBHOOK_MAX_ROWS`
- `WEBHOOK_AUTH_WINDOW_SECONDS`
- `WEBHOOK_RATE_LIMIT_WINDOW_SECONDS`
- `WEBHOOK_RATE_LIMIT_MAX_REQUESTS`

No `google_apps_script.gs`, ajuste:
- `API_BASE_URL`
- `WEBHOOK_SECRET`
- `NOME_ABA_NOTAS`

## 3. Como instalar o Apps Script

1. Abra a planilha no Google Sheets.
2. Va em `Extensoes > Apps Script`.
3. Substitua o conteudo do projeto pelo arquivo `google_apps_script.gs` deste repositorio.
4. Ajuste as constantes no topo do arquivo.
5. Salve o projeto.
6. Recarregue a planilha para o menu `iScholar ETL` aparecer.
7. Na primeira execucao, autorize o script.

## 4. Fluxo do operador

1. Abra a aba configurada em `NOME_ABA_NOTAS`.
2. Clique em `iScholar ETL > Validar Lote`.
3. Aguarde o polling terminar e revise o resumo exibido.
4. Se o lote estiver apto, clique em `iScholar ETL > Aprovar e Enviar`.
5. Confirme o aprovador. Quando o Google Workspace disponibiliza `Session.getActiveUser().getEmail()`, o script envia esse email ao backend como identidade de sessao; quando isso nao ocorre, a aprovacao continua possivel, mas fica marcada como identidade fraca.
6. Aguarde o resultado final do envio.
7. Se quiser apenas testar sem envio real, use `iScholar ETL > Simular (Dry Run)`.
8. Se o processamento demorar mais do que o polling do dialog, use `iScholar ETL > Mostrar Ultimo Status`. O script consulta primeiro os resultados persistidos e, se ainda nao houver consolidacao, cai para o status do job assincrono.

## 5. O que o operador ve

Na validacao:
- status da validacao;
- resumo do lote;
- avisos;
- pendencias;
- erros de bloqueio.

No envio:
- status geral;
- status do job quando o worker ainda nao publicou o resultado consolidado;
- quantidade enviada;
- quantidade com erro;
- totais de dry run;
- resumo agregado da auditoria por item;
- forca da identidade do aprovador (`medium` para email de sessao do Apps Script, `weak` para identidade declarada).

## 6. Teste manual rapido

> **Estado atual:** o fluxo de envio via CLI foi validado em homologação assistida com múltiplas disciplinas (Arte, Inglês, Física A, Gramática/Língua Portuguesa). O próximo passo é validar o fluxo completo via Google Sheets (backend + worker) com planilha real antes do go-live em escala.

1. Inicie backend e worker.
2. Abra a planilha.
3. Preencha ou ajuste a aba `Notas`.
4. Rode `Validar Lote`.
5. Confirme que o dialog mostra `Apto para aprovacao: sim` quando esperado.
6. Rode `Simular (Dry Run)` para homologar o fluxo sem envio real.
7. Rode `Aprovar e Enviar` quando quiser executar o envio real.

## 7. Contingencia via CLI

Se o Apps Script ficar indisponivel, o fluxo oficial continua disponivel pelo CLI:

```bash
.\.venv\Scripts\python.exe cli_envio.py --planilha notas.xlsx --lote-id lote-manual --dry-run
.\.venv\Scripts\python.exe cli_envio.py --planilha notas.xlsx --lote-id lote-manual --aprovador "Coordenacao"
```

O CLI usa o mesmo runner oficial do backend.

## 8. Limitacoes atuais

- O Apps Script depende do tempo maximo de execucao da plataforma; por isso o polling e curto e pode pedir consulta posterior.
- O anti-replay e o rate limit do backend usam cache em memoria do processo web; sao endurecimentos locais, nao controles distribuidos.
- O email do aprovador depende de o Google Workspace expor `Session.getActiveUser().getEmail()` para a conta e o dominio em uso.
- Nao existe painel web; a consulta operacional e feita por dialogs do Sheets ou pelos endpoints HTTP.

## 9. Trade-offs atuais

- O Google Sheets permanece simples e sem regra de negocio.
- O backend concentra validacao, aprovacao, stale check, retry e persistencia.
- O resultado consolidado do envio e consultavel sem precisar ler toda a auditoria por item.

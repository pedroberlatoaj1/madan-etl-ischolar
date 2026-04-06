# Operacao via Google Sheets

Este projeto suporta um fluxo operacional sem terminal para o operador final.

O Google Sheets funciona como cliente fino:
- le a aba `Notas`;
- envia os dados para o backend;
- faz polling de validacao e envio;
- mostra dialogs simples;
- guarda `lote_id`, `snapshot_hash` e os `job_id` mais recentes localmente entre as etapas.

## 0. Requisitos operacionais — leia antes de subir

### Túnel HTTPS (obrigatório para o Apps Script alcançar o backend)

O Apps Script do Google Sheets roda nos servidores do Google e não consegue acessar `localhost`. É necessário expor o backend com um túnel HTTPS público.

**Subir o túnel:**
```powershell
& "C:\Users\PICHAU\Downloads\ngrok-v3-stable-windows-amd64\ngrok.exe" http 5000
```

Ou dar double-click em `subir_tunel.bat`.

**Copiar a URL** da linha `Forwarding https://XXXX.ngrok-free.app` e atualizar `API_BASE_URL` no Apps Script a cada reinício.

> **Atenção:** a URL do ngrok muda a cada vez que o túnel é reiniciado (plano gratuito). O operador deve copiar a nova URL e colar no Apps Script (`Extensões > Apps Script > constante API_BASE_URL`) antes de cada sessão de uso.

### Header obrigatório para ngrok

O ngrok (plano gratuito) exibe uma página de aviso antes de repassar a requisição ao backend. Para contornar isso, todas as requisições do Apps Script ao backend devem incluir o header:

```
ngrok-skip-browser-warning: true
```

Este header está configurado na função `chamarApi_` do `google_apps_script.gs` versionado no repositório. Ao copiar o script para uma nova instância no Google Sheets, o header já estará presente. Não remover.

### Sequência correta de subida

**Opção rápida (double-click):**
1. `iniciar_servicos.bat` — sobe backend + worker em janelas separadas (aguardar ~3s)
2. `subir_tunel.bat` — sobe o túnel ngrok
3. Copiar URL `https://XXXX.ngrok-free.app` → colar em `API_BASE_URL` no Apps Script
4. Abrir a planilha Google Sheets e usar o menu `iScholar ETL`

**Opção manual (terminal):**
1. Terminal 1: `.venv\Scripts\python.exe webhook_google_sheets.py`
2. Terminal 2: `.venv\Scripts\python.exe worker.py`
3. Terminal 3: `subir_tunel.bat` ou ngrok direto
4. Atualizar `API_BASE_URL` no Apps Script com a nova URL do ngrok
5. Abrir a planilha Google Sheets e usar o menu `iScholar ETL`

> **Startup via `iniciar_servicos.bat`:** logs gravados em `logs/webhook.log` e `logs/worker.log`. Se algo não subir, abrir esses arquivos para diagnóstico.

---

## Status de validacao

**Fluxo completo via Google Sheets validado com POST real no iScholar.**
**Projeto pronto para go-live assistido. Aceite pendente de sessao com operador.**

| Etapa | Resultado | Evidencia |
|-------|-----------|-----------|
| Gate de validacao (sem POST) | ✅ comprovado | Execucao 004 |
| Onda A — envio pequeno (3 alunos, 1 disciplina) | ✅ 3/3 enviados, notas no diario | Execucao 005 |
| Onda B — lote completo (44 alunos, 2 disciplinas) | ✅ 71/91 enviados, erros isolados | Execucao 006 |
| snapshot_hash coerente entre validacao e aprovacao | ✅ comprovado | |
| Fluxo completo sem intervencao do dev | ✅ comprovado | |

**O que ainda depende de sessao com operador:**
- Handoff observado (operador executar o fluxo sozinho)
- Aceite formal assinado
- Resolucao dos 10 alunos com dados inconsistentes no iScholar (ver `pendencias_admin_ischolar.md`)

---

## Regras operacionais

### Lote homogeneo

Um lote de envio deve ser homogeneo por turma, trilha, grade curricular e sistema
avaliativo. Se a escola tiver alunos em trilhas diferentes dentro da mesma turma,
esses alunos devem ser enviados em lotes separados com os IDs corretos.

O pipeline NAO tenta adivinhar a grade do aluno. Se o iScholar rejeitar uma nota
com "Disciplina nao pertence a grade curricular", o aluno esta em uma trilha diferente.

### send_failed com sucesso parcial

O status `send_failed` significa "houve pelo menos um erro no lote". Ele pode
coexistir com muitos envios bem-sucedidos. O operador deve SEMPRE ler os contadores:

- `Quantidade enviada: 71` — 71 notas foram enviadas com sucesso
- `Quantidade com erro: 20` — 20 falharam
- `Erros de resolucao: 8` — 8 por RA/matricula nao encontrado
- `Erros de envio: 12` — 12 por rejeicao do iScholar

`send_failed` NAO significa "nada foi enviado".

### Erro do pipeline vs erro externo do iScholar

| Tipo | Significado | O que fazer |
|------|-------------|-------------|
| `erro_resolucao` | RA nao encontrado ou matricula nao acessivel na API | Verificar com admin iScholar |
| `erro_envio` | iScholar rejeitou a nota (grade/disciplina/avaliacao) | Verificar trilha do aluno |
| Erro de rede / timeout | Backend ou iScholar temporariamente indisponivel | Aguardar e tentar novamente |

O pipeline isola cada erro sem bloquear os demais envios.

### Tunel expirado

Se o ngrok cair ou expirar:
1. O Sheets vai mostrar erro de conexao
2. Subir o tunel novamente: double-click em `subir_tunel.bat`
3. Copiar a nova URL e atualizar `API_BASE_URL` no Apps Script
4. Continuar normalmente — o lote pode ser revalidado

O backend e o worker NAO precisam ser reiniciados quando o tunel cai.

---

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

> **Estado atual:** fluxo validado end-to-end via Google Sheets com POST real no iScholar (Onda A e Onda B concluidas). Ver secao "Status de validacao" acima.

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

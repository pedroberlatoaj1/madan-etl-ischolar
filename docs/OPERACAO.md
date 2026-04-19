# Operacao Madan ETL -> iScholar

> Este runbook foi escrito a partir do comportamento atual do codigo.
> Os comandos abaixo assumem a estrutura de VPS documentada em `PLANO_DEPLOY_VPS.md`:
> `/opt/madan-etl/app`, `/opt/madan-etl/data` e `/opt/madan-etl/logs`.
> Se a VPS usar outros paths via `.env`, ajuste os caminhos antes de executar.

## 1. Quem opera

- Marina (aprovadora) -> usa a planilha Google Sheets e o menu `iScholar ETL`.
- Pedro (manutencao) -> acessa a VPS, faz deploy, ajusta mapas, consulta logs e destrava filas.

## 2. Fluxo normal de operacao

### Menu atual do operador

Nao ha screenshot versionada no repositorio. O menu atual definido em `google_apps_script.gs` e:

```text
iScholar ETL
|- Validar Lote
|- Aprovar e Enviar
|- Simular (Dry Run)
|- Simular via Apps Script
|- Aprovar e Enviar (Apps Script)
|- Mostrar Ultimo Status
`- Limpar Estado Local
```

### Passo a passo da Marina

1. Abrir a planilha no Google Sheets.
2. Clicar na aba correta antes de qualquer acao.
   O fluxo Plano B usa nomes como `1A_T1`, `1B_T2`, `2A_T3`, `2B_T1`.
3. Clicar em `iScholar ETL > Validar Lote`.
4. Ler o dialogo de confirmacao da aba.
   O script mostra `Aba`, `Turma` e `Trimestre`.
   Se estiver na aba errada, clicar em `Cancelar`.
5. Aguardar o fim da validacao.
6. Ler o resumo.
   O resumo mostrado pelo script traz pelo menos:
   `Linhas`, `Lancamentos`, `Sendaveis`, `Bloqueados`, `Avisos`, `Pendencias` e `Erros`.
7. Se `Apto para aprovacao: sim`, clicar em uma das opcoes abaixo:
   `Aprovar e Enviar` para o fluxo normal via worker da VPS.
   `Aprovar e Enviar (Apps Script)` se a chamada final ao iScholar precisar sair do Apps Script.
8. Informar o aprovador quando o prompt aparecer.
9. Confirmar o dialogo final com `Lote`, `Snapshot`, `Aprovador` e `Modo`.
10. Aguardar o resultado.
11. Se o polling acabar antes do processamento terminar, usar `iScholar ETL > Mostrar Ultimo Status`.
12. Se o lote local guardado estiver errado, usar `iScholar ETL > Limpar Estado Local` antes de validar de novo.

### O que Marina deve conferir antes de aprovar

- A aba ativa e a turma correta.
- `Sendaveis > 0` quando houver notas para enviar.
- `Apto para aprovacao: sim`.
- Se houver `Erros`, o lote nao deve ser aprovado.

## 3. Como deployar mudancas de codigo

### Comando unico

Na VPS:

```bash
ssh madan@vps
madan-deploy
```

O alias documentado no `README.md` e:

```bash
alias madan-deploy='/opt/madan-etl/app/deploy.sh'
alias madan-status='systemctl status madan-webhook madan-worker --no-pager | head -20'
alias madan-logs='sudo journalctl -u madan-worker -u madan-webhook -f'
```

### O que o deploy faz

`deploy.sh` executa, nesta ordem:

1. `git fetch --prune`
2. revisao dos commits que vao entrar
3. `git pull --ff-only`
4. limpeza de `__pycache__` e `*.pyc`
5. `sudo systemctl restart madan-webhook madan-worker`
6. validacao final de import de `validacao_pre_envio.py`

### O que fazer se falhar

Rodar, na VPS:

```bash
madan-status
sudo journalctl -u madan-webhook -u madan-worker -n 100 --no-pager
cd /opt/madan-etl/app
git status --short
./deploy.sh --dry-run
```

Sinais comuns:

- `git pull --ff-only` falhou -> ha divergencia ou alteracao local na VPS.
- servico nao sobe -> ler `journalctl` do `madan-webhook` e `madan-worker`.
- import final falhou -> o codigo deployado nao esta consistente; corrigir e rodar `madan-deploy` de novo.

## 4. Como atualizar mapas (IDs do iScholar)

Regra fixa:

- editar o JSON no repositorio ou direto em `/opt/madan-etl/app/`
- salvar
- rodar `madan-deploy`

### `mapa_disciplinas.json`

Quando atualizar:

- disciplina nova entrou na grade
- nome de disciplina mudou
- o sistema passou a rejeitar uma disciplina com erro de mapeamento local

Como obter os IDs:

- fonte tecnica principal: `GET /disciplinas`
- fonte auxiliar: `python descobrir_ids_ischolar.py --ra <RA_COM_NOTAS> --gerar-mapas`
- o proprio `README.md` registra que os IDs atuais vieram da interface web do iScholar

Comando util:

```bash
cd /opt/madan-etl/app
.venv/bin/python - <<'PY'
from ischolar_client import IScholarClient
c = IScholarClient()
r = c.listar_disciplinas()
print(r.dados)
c.close()
PY
.venv/bin/python descobrir_ids_ischolar.py --ra <RA_COM_NOTAS> --gerar-mapas
```

Se quiser so o discovery por um aluno ja existente:

```bash
cd /opt/madan-etl/app
.venv/bin/python descobrir_ids_ischolar.py --ra <RA_COM_NOTAS> --gerar-mapas
```

Observacoes do arquivo atual:

- as chaves sao nomes normalizados
- `gramatica`, `literatura` e `lingua portuguesa` apontam para o mesmo `id_disciplina=29`

### `mapa_professores.json`

Quando atualizar:

- professor mudou
- frente mudou de dono
- turma passou a usar professor diferente para a mesma frente
- apareceu erro de `id_professor` nao resolvido

Como obter os IDs:

- fonte tecnica principal: `GET /funcionarios/professores`
- fonte auxiliar: `python descobrir_ids_ischolar.py --ra <RA_COM_NOTAS> --gerar-mapas`

Comando util:

```bash
cd /opt/madan-etl/app
.venv/bin/python - <<'PY'
from ischolar_client import IScholarClient
c = IScholarClient()
r = c.listar_professores()
print(r.dados)
c.close()
PY
.venv/bin/python descobrir_ids_ischolar.py --ra <RA_COM_NOTAS> --gerar-mapas
```

Se quiser so o discovery por um aluno ja existente:

```bash
cd /opt/madan-etl/app
.venv/bin/python descobrir_ids_ischolar.py --ra <RA_COM_NOTAS> --gerar-mapas
```

Observacoes do arquivo atual:

- o resolvedor tenta primeiro `professores_por_turma`
- sem entrada especifica, cai no fallback global `professores`
- se o ID nao for conhecido, omitir a chave e deixar falhar fechado; nao usar `0`

### `mapa_avaliacoes.json`

Quando atualizar:

- virou o trimestre
- mudou o sistema avaliativo do ano
- o iScholar trocou `id_avaliacao`
- entrou ou saiu recuperacao trimestral/final

Como obter os IDs:

- este e o mapa mais sensivel
- o arquivo atual esta amarrado ao sistema avaliativo `ENSINO MEDIO (1a E 2a SERIE) - 2026`
- o `README.md` registra que os IDs atuais foram coletados manualmente da interface web do iScholar
- o proprio `README.md` tambem registra uma limitacao importante:
  `GET /diario/notas` fica bloqueado para token de integracao, entao este mapa nao deve depender de discovery automatico

O que conferir:

- `componente`
- `trimestre`
- `id_avaliacao`
- se o componente de recuperacao daquele trimestre realmente e usado pela escola

### `mapa_turmas.json`

Quando atualizar:

- inicio de ano letivo
- mudanca de ID de turma no iScholar
- entrada/saida de turma do escopo operacional
- erro `Turma '<codigo>' sem id_turma configurado`

Como obter os IDs:

- fonte tecnica principal: `GET /turma/lista`
- o proprio `mapa_turmas.json` aponta duas fontes:
  a funcao auxiliar `utilListarTurmas()` do `google_apps_script.gs`
  a planilha `Envio para Ischolar - OFICIAL 2025 (2).xlsx`, aba `Turmas_Periodos`

Como usar a funcao auxiliar:

1. Abrir `Extensoes > Apps Script`.
2. Selecionar a funcao `utilListarTurmas`.
3. Executar.
4. Ler o dialogo com a resposta do endpoint `/turma/lista`.

Observacoes do arquivo atual:

- hoje so existem `1A`, `1B`, `2A` e `2B`
- `0` significa nao mapeado
- o endpoint `/lote/{id}/pacote-execucao` falha se a turma estiver sem ID

### Quem fornece os IDs no Madan/iScholar

- fonte tecnica dos IDs: o proprio iScholar
- o nome da pessoa responsavel no Madan por consolidar esses IDs nao esta documentado neste repositorio
- antes de operar sem o Pedro, esse dono precisa ser definido formalmente

## 5. Cenarios de falha - runbook

### Cenario A: Marina diz "Sendaveis: 0" mas tem notas

Checklist:

1. Confirmar se a aba certa foi validada.
   O Apps Script usa sempre a aba ativa.
2. Confirmar se as celulas realmente estao preenchidas.
   Linhas totalmente vazias e celulas vazias sao ignoradas.
3. Confirmar se o worker esta de pe:

```bash
madan-status
sudo journalctl -u madan-worker -n 100 --no-pager
```

4. Rodar smoke test do `_is_sendavel` na VPS:

```bash
cd /opt/madan-etl/app
.venv/bin/python - <<'PY'
from validacao_pre_envio import _is_sendavel
from avaliacao_rules import StatusLancamento
print(_is_sendavel({
    "status": StatusLancamento.PRONTO,
    "subcomponente": None,
    "componente": "av1",
    "peso_avaliacao": 1,
    "valor_ponderado": 7.0,
}))
PY
```

Resultado esperado:

- `True` -> a logica basica carregada na VPS esta correta
- erro de import ou `False` -> deploy incompleto ou modulo errado carregado

5. Ver a ultima validacao persistida:

```bash
sqlite3 /opt/madan-etl/data/validacoes_lote.db "select lote_id, job_id, status, updated_at from validacoes_lote order by updated_at desc limit 10;"
```

6. Se houve deploy recente, reiniciar so o worker e validar de novo:

```bash
sudo systemctl restart madan-worker
madan-status
```

### Cenario B: Envio falha com 401/403

Causa mais provavel:

- token/JWT do iScholar expirado ou rejeitado

Primeiro: identificar em qual modo o erro aconteceu.

- `Aprovar e Enviar` -> token vem da VPS (`ISCHOLAR_API_TOKEN` no `.env`)
- `Aprovar e Enviar (Apps Script)` -> token vem do Apps Script (`ISCHOLAR_TOKEN` em Script Properties)

#### Se o erro foi no modo Apps Script

Importante:

- o arquivo nao guarda o JWT em texto puro
- o codigo usa `const PROP_ISCHOLAR_TOKEN = "ISCHOLAR_TOKEN"`
- o valor real fica em `Apps Script > Project Settings > Script properties`

Passo a passo:

1. Gerar um novo token JWT no iScholar do ambiente em uso.
   O procedimento de geracao do token nao esta versionado no repositorio.
2. Abrir `Extensoes > Apps Script`.
3. Abrir `Project Settings`.
4. Atualizar a Script Property `ISCHOLAR_TOKEN`.
5. Salvar.
6. Voltar para a planilha.
7. Rodar `Simular via Apps Script`.

#### Se o erro foi no modo normal da VPS

Passo a passo:

```bash
ssh madan@vps
cd /opt/madan-etl/app
grep -n "^ISCHOLAR_API_TOKEN=" .env
```

Editar o `.env`, salvar o novo token e depois:

```bash
madan-deploy
```

Teste read-only:

```bash
cd /opt/madan-etl/app
.venv/bin/python descobrir_ids_ischolar.py --ra <RA_TESTE>
```

Se o erro persistir em `403`, conferir tambem `ISCHOLAR_CODIGO_ESCOLA`.

### Cenario C: VPS nao responde

Primeiros testes:

```bash
ping <host-ou-ip-da-vps>
ssh madan@vps
```

Se o `ping` responde e o `ssh` nao:

- checar chave SSH, rede e firewall

Se a VPS nao responde nem a `ping`:

- reiniciar pelo painel da Hetzner
- o passo exato do painel nao esta versionado neste repositorio; usar o console web do provedor

Depois do reboot:

```bash
ssh madan@vps
madan-status
sudo journalctl -u madan-webhook -u madan-worker -n 100 --no-pager
curl -fsS http://127.0.0.1:5000/health
```

Se precisar restaurar backup:

- o repositorio nao versiona um script de restore
- o minimo a restaurar e o conteudo de `/opt/madan-etl/data/`
- isso inclui `jobs.sqlite3`, `validacoes_lote.db`, `aprovacoes_lote.db`, `lote_itens.db`, `envio_lote_audit.db`, `resultados_envio_lote.db` e `snapshots/`

### Cenario D: Lote travado em `processing` ha mais de 5 min

Referencia do codigo:

- `PROCESSING_STALE_SECONDS = 300`
- o worker considera `processing` acima de 5 minutos como stale

Ver o job:

```bash
sqlite3 /opt/madan-etl/data/jobs.sqlite3 "select id, job_type, status, retry_count, attempt_count, updated_at, next_retry_at, substr(coalesce(last_error,''),1,120) from jobs order by updated_at desc limit 20;"
sqlite3 /opt/madan-etl/data/validacoes_lote.db "select lote_id, job_id, status, updated_at from validacoes_lote order by updated_at desc limit 20;"
sqlite3 /opt/madan-etl/data/resultados_envio_lote.db "select lote_id, job_id, status, updated_at, mensagem from resultados_envio_lote order by updated_at desc limit 20;"
sudo journalctl -u madan-worker -n 100 --no-pager
```

Tentar destravar pelo caminho oficial:

```bash
cd /opt/madan-etl/app
.venv/bin/python worker.py --once --limit 10
```

Por que isso funciona:

- `worker.py --once` chama `requeue_stale_processing_jobs()` antes de consumir a fila

Se ainda ficar preso e o job ja estiver acima de 5 minutos, destravar manualmente:

```bash
sqlite3 /opt/madan-etl/data/jobs.sqlite3 "UPDATE jobs SET status='pending', updated_at=strftime('%Y-%m-%dT%H:%M:%SZ','now'), retry_count=retry_count+1 WHERE id=<JOB_ID> AND status='processing';"
cd /opt/madan-etl/app
.venv/bin/python worker.py --once --limit 10
```

Se `retry_count` ja estourou e o job caiu em `error`, nao insistir no mesmo registro:

- ler `last_error`
- corrigir a causa
- revalidar a aba para gerar um lote novo

### Cenario E: Marina enviou para a planilha errada

#### Antes de aprovar

1. No dialogo `Confirmar aba a processar`, clicar em `Cancelar`.
2. Se o lote errado ja ficou salvo localmente, usar `iScholar ETL > Limpar Estado Local`.
3. Ir para a aba correta.
4. Rodar `Validar Lote` de novo.

#### Depois de aprovar

Limites reais do sistema atual:

- nao existe endpoint HTTP de cancelamento
- nao existe rollback automatico
- depois de `POST /lote/{lote_id}/aprovar`, o fluxo segue para fila/execucao

O que fazer:

- se foi `Simular (Dry Run)` ou `Simular via Apps Script`, nao houve POST real
- se foi envio real, consultar a auditoria do lote e reverter manualmente no iScholar

## 6. Como rodar dry run (sem afetar boletim)

### Dry run pelo fluxo normal

1. Abrir a aba correta.
2. Rodar `iScholar ETL > Validar Lote`.
3. Conferir o resumo.
4. Rodar `iScholar ETL > Simular (Dry Run)`.
5. Informar o aprovador.
6. Ler o dialogo `Resultado da Simulacao`.

### Dry run pelo Apps Script

Usar quando quiser testar o caminho que faz a chamada final pelo Google.

1. Garantir `ISCHOLAR_TOKEN` nas Script Properties.
2. Abrir a aba correta.
3. Rodar `Validar Lote`.
4. Rodar `Simular via Apps Script`.
5. Ler o dialogo `Resultado da Simulacao via Apps Script`.

Onde ver o resultado:

- dialogo final do proprio Sheets
- `iScholar ETL > Mostrar Ultimo Status`
- `GET /lote/{lote_id}/resultado-envio`
- `resultados_envio_lote.db`, com status esperado `dry_run_completed`

## 7. Como ler o audit trail

### Paths principais

Assumindo a estrutura de producao da VPS:

```text
/opt/madan-etl/data/jobs.sqlite3
/opt/madan-etl/data/validacoes_lote.db
/opt/madan-etl/data/aprovacoes_lote.db
/opt/madan-etl/data/lote_itens.db
/opt/madan-etl/data/resultados_envio_lote.db
/opt/madan-etl/data/envio_lote_audit.db
/opt/madan-etl/data/snapshots/<job_id>.json
/opt/madan-etl/logs/etl_ischolar.log
```

### Estrutura de um lote

- `lote_id` -> no Sheets, e montado como `<spreadsheet_id>/<sheet_name>`
- `validacoes_lote.db` -> resumo oficial da validacao, incluindo `snapshot_hash`, `status`, `avisos`, `erros`, `pendencias` e `itens_sendaveis`
- `aprovacoes_lote.db` -> quem aprovou e o snapshot aprovado
- `lote_itens.db` -> conjunto exato de itens sendaveis aprovados
- `resultados_envio_lote.db` -> resultado consolidado do envio
- `envio_lote_audit.db` -> um registro por item enviado, `dry_run`, `erro_resolucao` ou `erro_envio`
- `snapshots/<job_id>.json` -> payload bruto recebido do Sheets

### Comandos de leitura

Ultimos lotes:

```bash
sqlite3 /opt/madan-etl/data/resultados_envio_lote.db "select lote_id, status, quantidade_enviada, quantidade_com_erro, total_sendaveis, updated_at from resultados_envio_lote order by updated_at desc limit 20;"
```

Itens de um lote:

```bash
sqlite3 /opt/madan-etl/data/envio_lote_audit.db "select lote_id, estudante, disciplina, componente, trimestre, status, mensagem, timestamp from envio_lote_audit where lote_id='<LOTE_ID>' order by id;"
```

Validacao oficial:

```bash
sqlite3 /opt/madan-etl/data/validacoes_lote.db "select lote_id, snapshot_hash, status, updated_at from validacoes_lote where lote_id='<LOTE_ID>';"
```

### Como buscar historico de uma nota especifica

Por aluno + disciplina + trimestre no audit DB:

```bash
sqlite3 /opt/madan-etl/data/envio_lote_audit.db "select lote_id, estudante, disciplina, componente, trimestre, valor_bruta, status, mensagem, timestamp from envio_lote_audit where estudante like '%<NOME_DO_ALUNO>%' and disciplina like '%<DISCIPLINA>%' order by timestamp desc;"
```

Se voce so tiver o RA:

- o audit DB nao guarda RA como coluna dedicada
- para RA, buscar no snapshot bruto do lote

```bash
grep -R "\"RA\"" /opt/madan-etl/data/snapshots
grep -R "<RA_DO_ALUNO>" /opt/madan-etl/data/snapshots
```

## 8. Manutencao periodica

### Por trimestre

- revisar `mapa_avaliacoes.json`
- confirmar se os `id_avaliacao` daquele trimestre continuam os mesmos
- se mudar, editar e rodar `madan-deploy`

### Por ano

- refazer `mapa_turmas.json`
- confirmar as turmas do ano e os novos `id_turma`
- hoje o arquivo cobre so `1A`, `1B`, `2A` e `2B`

### Mensalmente

Conferir backups:

```bash
ls -la /opt/madan-etl/backups/
```

Observacao:

- o repositorio nao cria esse diretorio nem versiona a rotina de backup
- esse comando serve para confirmar se a rotina da VPS ja esta gerando arquivos

Revisar logs de erro:

```bash
sudo journalctl -u madan-webhook -u madan-worker --since "30 days ago" --no-pager | tail -200
grep -n "ERROR\\|Falha\\|Traceback\\|Exception" /opt/madan-etl/logs/etl_ischolar.log | tail -50
```

## 9. Contatos

- Pedro (Berlato): `pedroberlatoaj1@gmail.com`
- Responsavel no Madan por fornecer os IDs do iScholar: nao documentado neste repositorio
- Suporte iScholar: nao documentado neste repositorio

## 10. Limitacoes conhecidas

- Escopo operacional atual: somente Ensino Medio 1a e 2a serie
- `mapa_turmas.json` atual cobre apenas `1A`, `1B`, `2A` e `2B`
- Nao existe cancelamento nem rollback automatico depois de `POST /lote/{lote_id}/aprovar`
- Se a chamada direta da VPS sofrer bloqueio `403` com indicio de Cloudflare, o caminho suportado pelo codigo e usar `Simular via Apps Script` ou `Aprovar e Enviar (Apps Script)`
- O Apps Script tem tempo maximo de execucao; se o lote for grande, usar `Mostrar Ultimo Status` para consultar depois
- `recuperacao_final` ja existe no codigo e no `mapa_avaliacoes.json`; este runbook nao trata recuperacao final como funcionalidade pendente

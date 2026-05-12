# Plano De Finalizacao E Entrega - 15/04/2026

## Objetivo Do Dia

Finalizar o projeto Madan -> iScholar com a arquitetura original:

- Google Apps Script -> VPS -> iScholar
- sem reintroduzir a arquitetura alternativa onde o Apps Script envia direto para o iScholar
- com controle de taxa no cliente HTTP da VPS para respeitar o limite informado pelo iScholar

## Estado De Partida

Ja foi feito:

- VPS Hetzner criada e configurada
- `nginx`, `madan-webhook.service` e `madan-worker.service` funcionando
- endpoint publico `/health` respondendo
- Apps Script falando com a VPS
- validacao de lote via planilha funcionando
- correcoes do Plano B ja homologadas no `2B`
- correcao de rate limit implementada localmente no codigo para manter a VPS como executora

Restricoes conhecidas:

- o `2A` continua como pendencia de configuracao no iScholar
- o foco de homologacao e entrega deve continuar no `2B`
- o fornecedor informou limite de `50` chamadas a cada `10` segundos
- o cliente foi ajustado para operar com margem de seguranca em `45` chamadas a cada `10` segundos

## Roteiro De Amanhã

### 1. Confirmar Que O Codigo Certo Foi Para O GitHub E Para A VPS

No computador local:

```powershell
git status --short
git log -1 --oneline
```

Na VPS:

```bash
cd /opt/madan-etl/app
git log -1 --oneline
grep -E "ISCHOLAR_RATE_LIMIT_ENABLED|ISCHOLAR_RATE_LIMIT_MAX_REQUESTS|ISCHOLAR_RATE_LIMIT_WINDOW_SECONDS" .env
```

O que precisa estar verdadeiro:

- a VPS deve estar com o commit que contem a correcao de rate limit
- o `.env` da VPS deve conter:
  - `ISCHOLAR_RATE_LIMIT_ENABLED=true`
  - `ISCHOLAR_RATE_LIMIT_MAX_REQUESTS=45`
  - `ISCHOLAR_RATE_LIMIT_WINDOW_SECONDS=10`

### 2. Reiniciar E Validar A Infraestrutura

Na VPS:

```bash
sudo systemctl restart madan-webhook
sudo systemctl restart madan-worker
sudo systemctl status madan-webhook --no-pager
sudo systemctl status madan-worker --no-pager
curl http://127.0.0.1:5000/health
```

No computador local:

```powershell
curl.exe http://77.42.26.143/health
```

Critério:

- ambos os servicos em `active (running)`
- `/health` respondendo local e externamente

### 3. Fazer Um Teste Controlado No `2B`

Usar primeiro um caso pequeno e seguro no `2B_T2`.

Sugestao:

- `3` alunos
- `Arte`
- `Educacao Fisica`
- total de `6` lancamentos

Sequencia na planilha:

1. `Validar Lote`
2. `Simular (Dry Run)`
3. se passar, `Aprovar e Enviar`
4. conferir o resultado no iScholar

Critério:

- sem `403 Cloudflare`
- sem `buscar_aluno falhou`
- sem `erro_resolucao`
- lancamentos visiveis no iScholar

### 4. Coletar Evidencias

Na VPS:

```bash
sudo journalctl -u madan-webhook -n 80 --no-pager
sudo journalctl -u madan-worker -n 120 --no-pager
grep -n "Rate limit iScholar acionado" /opt/madan-etl/logs/etl_ischolar.log
```

Guardar:

- print do `Validar Lote`
- print do `Dry Run`
- print do `Aprovar e Enviar`
- print do iScholar com as notas
- logs mostrando funcionamento normal ou atuacao do rate limiter

### 5. Expandir O Piloto Se O Teste Pequeno Passar

Se o teste pequeno for aprovado:

- repetir com um lote um pouco maior do `2B`
- continuar evitando o `2A`
- manter a homologacao focada no que ja esta tecnicamente validado

### 6. Plano De Contingencia Se Ainda Houver Bloqueio

Se ainda houver erro associado a burst/rate limit:

1. reduzir o limite para `30/10`
2. reiniciar os servicos
3. repetir o teste pequeno
4. so depois decidir se vale um segundo ajuste

Configuracao de contingencia:

```env
ISCHOLAR_RATE_LIMIT_ENABLED=true
ISCHOLAR_RATE_LIMIT_MAX_REQUESTS=30
ISCHOLAR_RATE_LIMIT_WINDOW_SECONDS=10
```

### 7. Fechar A Entrega Para O Madan

Entregar com estes pontos objetivos:

- a VPS esta operacional
- o fluxo planilha -> Apps Script -> VPS -> iScholar esta funcional
- o controle de taxa foi implementado para respeitar o limite informado pelo iScholar
- o `2B` esta homologado para operacao
- o `2A` segue como pendencia externa de configuracao no iScholar

Arquivos de apoio:

- `README.md`
- `runbook_operador.md`
- `operacao_google_sheets.md`
- `PLANO_DEPLOY_VPS.md`

## Definicao De Projeto Entregue

Considerar o projeto entregue quando estes quatro pontos forem verdadeiros:

1. a VPS estiver saudavel
2. o `Dry Run` hospedado passar
3. um envio real hospedado passar
4. as evidencias estiverem registradas

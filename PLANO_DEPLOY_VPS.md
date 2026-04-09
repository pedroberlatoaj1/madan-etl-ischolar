# Plano de Deploy na VPS

> Este arquivo deve ser usado como contexto operacional para o deploy do projeto na VPS e como referência compartilhada entre Codex e Claude.
>
> Escopo: colocar o backend do projeto em uma VPS Linux, remover a dependência de `ngrok` e da máquina local, e manter o fluxo do Madan operando apenas pela planilha.

---

## 1. Objetivo

Substituir o fluxo atual:

- Google Sheets / Apps Script
- túnel `ngrok`
- backend rodando na máquina local

Pelo fluxo final:

- Google Sheets / Apps Script
- URL pública da VPS
- backend + worker rodando 24/7 na VPS
- bancos SQLite e snapshots persistidos no servidor

---

## 2. Estado Atual do Projeto

### Já validado

- Plano B multi-aba funcionando
- workbook anual com 12 abas funcionando
- seleção por `--aba` funcionando
- leitura de `Turma` e `Trimestre` a partir do nome da aba funcionando
- planilha corrigida `dryrun2ano_corrigida.xlsx` funcionando
- POST real validado em produção para:
  - `2B_T1 -> Arte`
  - `2B_T2 -> Biologia - Frente B`
  - `2B_T2 -> Geografia - Frente B`
  - `2B_T2 -> Educação Física - Frente Única`

### Pendência conhecida

- `2A` ainda não está homologado
- o problema do `2A` está ligado ao iScholar / sistema avaliativo / configuração da turma
- isso não bloqueia o deploy da VPS

### Conclusão operacional

O projeto já tem evidência suficiente para sair da máquina local e ir para uma VPS.

---

## 3. Arquitetura-Alvo

### Componentes

- `nginx`
  - HTTPS público
  - proxy para o backend Python

- `webhook_google_sheets.py`
  - recebe chamadas do Apps Script
  - expõe endpoints HTTP
  - roda com `Flask + Waitress`

- `worker.py`
  - processa jobs assíncronos
  - deve rodar como processo separado

- `SQLite`
  - armazenamento local da VPS
  - sem cluster
  - sem múltiplas instâncias

### Topologia

```text
Google Sheets / Apps Script
        ->
HTTPS público na VPS
        ->
Nginx
        ->
Waitress / Flask (webhook_google_sheets.py)
        ->
SQLite + snapshots + worker.py
        ->
API iScholar
```

### Decisão de infraestrutura

Não reabrir arquitetura agora.

Não usar neste momento:

- Docker
- Kubernetes
- fila externa
- banco remoto
- múltiplas instâncias

O deploy deve ser simples e estável.

---

## 4. Premissas

- haverá apenas uma VPS Linux
- haverá apenas uma instância do backend
- haverá apenas uma instância do worker
- os bancos SQLite ficarão em disco local persistente da VPS
- o Apps Script continuará sendo a interface do operador
- o Madan não dependerá mais da máquina local para operar

---

## 5. Estrutura Recomendada na VPS

```text
/opt/madan-etl/
  app/
  data/
    jobs.sqlite3
    validacoes_lote.db
    aprovacoes_lote.db
    lote_itens.db
    envio_lote_audit.db
    resultados_envio_lote.db
    snapshots/
  logs/
```

### Diretórios

- `/opt/madan-etl/app`
  - código do projeto

- `/opt/madan-etl/data`
  - bancos SQLite
  - snapshots

- `/opt/madan-etl/logs`
  - logs persistentes

---

## 6. Pacotes da VPS

Instalar no Linux:

- `python3`
- `python3-venv`
- `nginx`
- `git`
- `certbot`
- `python3-certbot-nginx`

Opcional:

- `ufw`
- `htop`
- `sqlite3`

---

## 7. Variáveis de Ambiente

Criar um `.env` na VPS baseado em `.env.example`.

### Obrigatórias

- `ISCHOLAR_API_TOKEN`
- `ISCHOLAR_CODIGO_ESCOLA`
- `WEBHOOK_SECRET`

### Recomendadas para produção

- `JOB_DB_PATH=/opt/madan-etl/data/jobs.sqlite3`
- `VALIDACAO_LOTE_DB=/opt/madan-etl/data/validacoes_lote.db`
- `APROVACAO_LOTE_DB=/opt/madan-etl/data/aprovacoes_lote.db`
- `LOTE_ITENS_DB=/opt/madan-etl/data/lote_itens.db`
- `ENVIO_LOTE_AUDIT_DB=/opt/madan-etl/data/envio_lote_audit.db`
- `RESULTADO_ENVIO_LOTE_DB=/opt/madan-etl/data/resultados_envio_lote.db`
- `SNAPSHOTS_DIR=/opt/madan-etl/data/snapshots`
- `LOG_FILE=/opt/madan-etl/logs/etl_ischolar.log`
- `LOG_LEVEL=INFO`

### Observações

- `WEBHOOK_SECRET` deve ser forte e exclusivo
- o `.env` da VPS não deve ser commitado
- o token do iScholar deve ficar apenas no servidor

---

## 8. Fases do Deploy

## Fase 1 - Preparar a VPS

### Objetivo

Deixar a máquina pronta para receber o projeto.

### Checklist

- criar VPS Linux
- criar usuário de serviço, ex.: `madan`
- criar diretórios `/opt/madan-etl/app`, `/opt/madan-etl/data`, `/opt/madan-etl/logs`
- instalar dependências do sistema

### Critério de saída

- servidor acessível
- usuário criado
- pastas criadas

---

## Fase 2 - Subir o Código

### Objetivo

Colocar o projeto na VPS e instalar o ambiente Python.

### Checklist

- clonar o repositório em `/opt/madan-etl/app`
- criar `venv`
- instalar `requirements.txt`
- confirmar que os arquivos essenciais existem:
  - `webhook_google_sheets.py`
  - `worker.py`
  - `config.py`
  - `mapa_disciplinas.json`
  - `mapa_avaliacoes.json`
  - `mapa_professores.json`

### Critério de saída

- ambiente Python funcional
- importações funcionando

---

## Fase 3 - Configurar o Ambiente

### Objetivo

Apontar bancos, logs e snapshots para o disco persistente da VPS.

### Checklist

- criar `.env`
- configurar caminhos absolutos de DB e snapshots
- validar permissões de escrita em `/opt/madan-etl/data`
- validar permissões de escrita em `/opt/madan-etl/logs`

### Critério de saída

- backend e worker conseguem iniciar sem erro de configuração

---

## Fase 4 - Criar Serviços

### Objetivo

Fazer backend e worker subirem automaticamente e reiniciarem em caso de falha.

### Serviços esperados

- `madan-webhook.service`
- `madan-worker.service`

### Requisitos dos serviços

- `Restart=always`
- `WorkingDirectory=/opt/madan-etl/app`
- `User=madan`
- `EnvironmentFile=/opt/madan-etl/app/.env`

### Critério de saída

- ambos os serviços ativos
- ambos sobem após reboot

---

## Fase 5 - Publicar com Nginx e HTTPS

### Objetivo

Expor a aplicação via URL pública segura.

### Checklist

- configurar reverse proxy para `127.0.0.1:5000`
- apontar domínio ou subdomínio
- emitir certificado com Certbot
- testar HTTPS

### Endpoints esperados

- `/health`
- endpoint do webhook usado pelo Apps Script
- status de jobs, se aplicável

### Critério de saída

- URL pública funcionando com HTTPS

---

## Fase 6 - Validar na VPS sem Trocar o Apps Script Oficial

### Objetivo

Garantir que a VPS funciona antes de substituir o `ngrok`.

### Checklist

- testar endpoint de health
- confirmar backend respondendo
- confirmar worker consumindo jobs
- confirmar criação dos arquivos SQLite
- confirmar gravação de snapshots
- repetir um caso real já homologado:
  - `2B_T1 -> Arte`
  - ou `2B_T2 -> Biologia - Frente B`

### Critério de saída

- 1 envio real bem-sucedido pela VPS

---

## Fase 7 - Apontar o Apps Script para a VPS

### Objetivo

Trocar definitivamente a URL usada pela planilha.

### Checklist

- atualizar URL base no Apps Script
- manter o `WEBHOOK_SECRET`
- publicar nova versão do script
- testar fluxo real com turma já homologada

### Critério de saída

- planilha operando via VPS
- `ngrok` não é mais necessário

---

## Fase 8 - Go-Live

### Objetivo

Concluir a migração para operação hospedada.

### Critérios de go-live

- backend estável na VPS
- worker estável na VPS
- 1 envio real via planilha usando a VPS funcionando
- notas confirmadas no iScholar
- dados persistindo após restart

---

## 9. Checklist Técnico de Validação Pós-Deploy

- [ ] `health` responde
- [ ] backend sobe sem erro
- [ ] worker sobe sem erro
- [ ] SQLite criado em `/opt/madan-etl/data`
- [ ] snapshots gravando em `/opt/madan-etl/data/snapshots`
- [ ] logs gravando em `/opt/madan-etl/logs`
- [ ] HTTPS válido
- [ ] Apps Script consegue chamar a VPS
- [ ] 1 lote real homologado via VPS
- [ ] reboot da VPS não derruba a operação

---

## 10. Riscos Conhecidos

### Risco 1 - `2A`

O `2A` continua pendente por causa do iScholar.

Esse ponto não deve bloquear o deploy da VPS.

### Risco 2 - SQLite

SQLite é suficiente para a fase atual, mas exige:

- uma única instância da aplicação
- um único worker
- disco estável
- backup periódico

### Risco 3 - Configuração do Apps Script

Uma troca incorreta da URL pode interromper o fluxo do operador.

Por isso:

- validar primeiro na VPS
- trocar a URL só depois

---

## 11. Estratégia de Rollback

Se algo falhar após a migração:

1. voltar temporariamente o Apps Script para o endpoint antigo
2. manter a VPS fora do caminho até corrigir
3. usar uma turma já homologada para revalidar

Rollback deve ser simples e rápido.

---

## 12. Definição de Pronto

O deploy na VPS estará concluído quando:

- o Madan puder operar apenas pela planilha
- o Apps Script chamar a VPS
- a VPS processar os lotes sozinha
- as notas forem lançadas no iScholar sem depender da máquina local
- `ngrok` deixar de ser necessário

---

## 13. Próxima Prioridade

A próxima frente recomendada é:

1. preparar a VPS
2. subir backend e worker
3. validar um envio real hospedado com turma já homologada
4. só depois voltar para a pendência específica do `2A`

---

## 14. Arquivos do Projeto Mais Relevantes para o Deploy

- `webhook_google_sheets.py`
- `worker.py`
- `config.py`
- `requirements.txt`
- `.env.example`
- `google_apps_script.gs`
- `checklist_homologacao.md`
- `pendencias_admin_ischolar.md`

---

## 15. Observação Final

Este plano trata apenas do deploy operacional da infraestrutura.

Ele não substitui:

- a pendência do `2A` no iScholar
- o checklist de homologação pedagógica
- a documentação operacional do Plano B

Mas ele já é suficiente para orientar a migração do projeto para produção hospedada.

# Checklist de Homologação — Sistema Madan → iScholar

Este documento define o roteiro de validação do fluxo oficial novo antes de qualquer execução em produção.  
Ele serve tanto como **checklist de smoke test local** quanto como **guia de go/no-go para homologação**.

> **Convenção de marcação**
> - `[ ]` — item pendente
> - `[x]` — item concluído
> - **🔴 BLOQUEANTE** — se não passar, não avançar
> - **🟡 ATENÇÃO** — pode avançar com ressalva registrada
> - **🟢 INFORMATIVO** — não bloqueia, mas deve ser documentado

---

## 1. Pré-requisitos locais antes de qualquer execução

### 1.1 Instalação e configuração

- [ ] Projeto instalado e dependências Python satisfeitas
- [ ] Arquivo `.env` presente com `ISCHOLAR_API_TOKEN` e `ISCHOLAR_CODIGO_ESCOLA` preenchidos **🔴 BLOQUEANTE**
- [ ] `mapa_disciplinas.json` presente e preenchido com IDs reais **🔴 BLOQUEANTE**
- [ ] `mapa_avaliacoes.json` presente e preenchido com IDs reais **🔴 BLOQUEANTE**
- [ ] `mapa_professores.json` presente se a escola exigir professor no lançamento **🔴 BLOQUEANTE (condicional)**
- [ ] Ambiente configurado corretamente: homologação **ou** produção — nunca ambos ao mesmo tempo

### 1.2 Template da planilha

- [ ] Planilha no modelo oficial (`planilha_modelo_notas.xlsx`) — **não adaptada**
- [ ] Coluna `Estudante` presente
- [ ] Coluna `RA` presente e preenchida para todos os alunos **🔴 BLOQUEANTE**
- [ ] Coluna `Turma` presente
- [ ] Coluna `Trimestre` presente (valores `1`, `2` ou `3`)
- [ ] Coluna `Disciplina` presente
- [ ] Coluna `Frente - Professor` presente
- [ ] Nenhuma coluna obrigatória renomeada ou removida
- [ ] Notas entre 0 e 10 (célula vazia = não se aplica, zero = nota real)
- [ ] Uma linha por aluno por disciplina

---

## 2. Smoke test local — antes de homologar

Executar com a planilha de exemplo e o ambiente de homologação configurado.

### 2.1 Comando padrão de dry-run

```bash
python cli_envio.py \
  --planilha planilha_modelo_notas.xlsx \
  --lote-id smoke-test-001 \
  --dry-run \
  --aprovador "Nome do Operador" \
  --mapa-disciplinas mapa_disciplinas.json \
  --mapa-avaliacoes mapa_avaliacoes.json
```

### 2.2 Sinais esperados no terminal (dry-run bem-sucedido)

- [ ] `ETAPA 1 — Carregando planilha` → linha com `✅ Planilha carregada`
- [ ] `ETAPA 2 — Validando template` → `✅ Template válido`
- [ ] `ETAPA 3/4 — Gerando lançamentos e validando` — sem mensagem de erro
- [ ] `RESUMO DO LOTE` — total de linhas, alunos e sendáveis coerentes com a planilha
- [ ] `ETAPA 6 — Preflight Técnico` → `✅ Resolvedor pronto` com contagem de disciplinas e avaliações **🔴 BLOQUEANTE**
- [ ] `ETAPA 7 — Aprovação` → aprovação automática registrada
- [ ] `ETAPA 8 — DRY RUN` → processados sem erro de resolução
- [ ] `RESULTADO DO ENVIO` → modo `DRY RUN`, total sendáveis > 0, erros de resolução = 0

### 2.3 Sinais de erro que exigem parada imediata 🔴

| Sinal no terminal | O que fazer |
|-------------------|-------------|
| `❌ Colunas obrigatórias ausentes` (exit 2) | Corrija a planilha — coluna faltando ou renomeada |
| `❌ Falha ao inicializar IScholarClient` (exit 5) | Verifique `.env` — credenciais ausentes ou inválidas |
| `❌ Mapa de disciplinas não encontrado` (exit 5) | Verifique o caminho do mapa |
| `❌ Mapa de avaliações não encontrado` (exit 5) | Verifique o caminho do mapa |
| `⚠️ N linha(s) com RA vazio` | Preencha os RAs antes de avançar |
| `Erros de resolução: N > 0` no resumo final | Mapa incompleto — disciplina ou avaliação sem ID |
| Exit code `1` (erro inesperado) | Chame o desenvolvedor com o log completo |

### 2.4 Checklist de resultado do smoke test local

- [ ] Exit code `0` no dry-run **🔴 BLOQUEANTE**
- [ ] Nenhum erro de resolução de IDs no dry-run **🔴 BLOQUEANTE**
- [ ] Nenhuma linha bloqueada por erro de validação (total_erros = 0) **🔴 BLOQUEANTE**
- [ ] Total sendáveis > 0 (o lote tem itens para enviar) **🔴 BLOQUEANTE**
- [ ] Resumo do lote condiz com o conteúdo da planilha **🟡 ATENÇÃO**

---

## 3. Validação em homologação — quando o ambiente estiver disponível

### 3.1 Pré-requisitos do ambiente de homologação

- [ ] Credenciais de homologação fornecidas pelo TI do iScholar **🔴 BLOQUEANTE**
- [ ] Código da escola de teste configurado no `.env`
- [ ] Ambiente de homologação confirmado como separado da produção **🔴 BLOQUEANTE**
- [ ] Ao menos um aluno real (ou de teste) com RA conhecido disponível no ambiente
- [ ] IDs de disciplina e avaliação confirmados para o ambiente de homologação

### 3.2 Validação de conectividade

- [ ] `cli_envio.py` consegue inicializar `IScholarClient` sem erro (exit 5 ausente)
- [ ] Preflight técnico completa com sucesso no ambiente de homologação

### 3.3 Validação do shape real da API

- [ ] `/aluno/busca` retorna resposta com estrutura compatível com o resolvedor
- [ ] `id_aluno` presente e único na resposta
- [ ] `/matricula/listar` retorna lista de matrículas sem ambiguidade para os alunos do piloto
- [ ] Confirmado com o TI se `id_professor` é obrigatório para a escola Madan **🟡 ATENÇÃO**

### 3.4 Validação dos mapas com IDs reais

- [ ] `mapa_disciplinas.json` preenchido com IDs reais do ambiente de homologação
- [ ] `mapa_avaliacoes.json` preenchido com IDs reais do ambiente de homologação
- [ ] Dry-run no ambiente de homologação: zero erros de resolução

### 3.5 Validação do POST real em homologação (piloto controlado)

Executar com 1–3 alunos reais em ambiente de homologação, nunca diretamente em produção:

- [ ] Dry-run passa sem erros
- [ ] Envio real executado com `--lote-id` exclusivo (ex.: `homolog-piloto-001`)
- [ ] Exit code `0` após envio real
- [ ] Nota aparece corretamente no diário do iScholar após o envio
- [ ] Valor enviado é a nota bruta (não ponderada)
- [ ] Auditoria registrada localmente no `envio_lote_audit.db`
- [ ] Reenvio do mesmo lote não duplica nota no diário (idempotência)

### 3.6 Validação de falhas esperadas

- [ ] Aluno com RA inexistente → item registrado como `erro_resolucao`, demais itens continuam
- [ ] Disciplina sem mapeamento → item registrado como `erro_resolucao`, demais itens continuam
- [ ] Lote com nota inválida (>10) → exit code 3, envio bloqueado antes do POST

---

## 4. Critérios de go/no-go

### ✅ Pode avançar para produção

Todos os itens abaixo precisam estar marcados:

- [ ] Smoke test local passou (exit 0 no dry-run, zero erros de resolução)
- [ ] Conectividade com homologação validada
- [ ] Shape real das APIs validado com o TI
- [ ] Mapas preenchidos com IDs reais de homologação
- [ ] POST real em homologação bem-sucedido (piloto 1–3 alunos)
- [ ] Nota aparece corretamente no diário de homologação
- [ ] Idempotência confirmada (reenvio não duplica)
- [ ] Primeiro envio em produção acompanhado pelo desenvolvedor

### 🔴 Não avançar se

Qualquer um dos itens abaixo estiver presente:

- [ ] Exit code 5 no ambiente alvo (credencial ou mapa inválido)
- [ ] Exit code 1 (erro inesperado) sem diagnóstico do desenvolvedor
- [ ] Erros de resolução de IDs > 0 no dry-run
- [ ] Nota não aparece no diário após POST real em homologação
- [ ] Shape de resposta da API diferente do esperado pelo resolvedor
- [ ] TI não confirmou obrigatoriedade de `id_professor` quando este for necessário
- [ ] Mapeamentos preenchidos "no chute" sem confirmação com o iScholar

---

## 5. Pendências externas (não bloqueiam o código, bloqueiam a operação)

| Item | Quem resolve | Status |
|------|-------------|--------|
| Acesso ao ambiente de homologação | TI do iScholar | Pendente |
| Credenciais e código da escola de teste | TI do iScholar | Pendente |
| Shape real de `/aluno/busca` | TI do iScholar | Pendente |
| Shape real de `/matricula/listar` | TI do iScholar | Pendente |
| Confirmação se `id_professor` é obrigatório para o Madan | TI do iScholar | Pendente |
| IDs reais de disciplina para homologação | TI / Madan | Pendente |
| IDs reais de avaliação para homologação | TI / Madan | Pendente |
| Adoção formal do template fixo pelo Madan | Madan | Pendente |
| Garantia de preenchimento do RA pelo Madan | Madan | Pendente |
| Fechamento das regras pedagógicas provisórias | Madan | Pendente |

---

## 6. Registro de execução do checklist

Preencher a cada execução:

| Campo | Valor |
|-------|-------|
| Data | |
| Ambiente | homologação / produção |
| Lote ID | |
| Operador | |
| Resultado | sucesso / falha parcial / falha total |
| Exit code | |
| Observações | |
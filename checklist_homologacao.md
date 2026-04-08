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

- [x] Projeto instalado e dependências Python satisfeitas
- [x] Arquivo `.env` criado a partir de `.env.example` **🔴 BLOQUEANTE**
- [x] `ISCHOLAR_API_TOKEN` preenchido no `.env` (token de integração gerado) **🔴 BLOQUEANTE**
- [x] `ISCHOLAR_CODIGO_ESCOLA` preenchido no `.env` — valor: `madan` (extraído do JWT) **🔴 BLOQUEANTE**
- [x] `ISCHOLAR_BASE_URL` confirmada: `https://api.ischolar.app` (mesma para homologação e produção)
- [x] `mapa_disciplinas.json` presente e preenchido com 16 IDs reais **🔴 BLOQUEANTE**
- [x] `mapa_avaliacoes.json` presente e preenchido com 19 IDs reais (92–110) **🔴 BLOQUEANTE**
- [x] `mapa_professores.json` presente com 25 IDs reais (10 aliases em 0 — professores fora de 1ª/2ª série) **🔴 BLOQUEANTE (condicional)**
- [x] Ambiente configurado corretamente

> **Informações confirmadas (2026-03-28):**
> - URL da API: `https://api.ischolar.app` (mesma para todos os ambientes)
> - `X-Codigo-Escola`: `madan` (extraído do campo `escola` no payload JWT do token)
> - Interface web: `https://madan.ischolar.com.br/`
> - Token de integração ativo (tipo `integracao`, sem expiração)
> - `/diario/notas` bloqueado para tokens de integração (não afeta envio de notas)
> - IDs de avaliação coletados manualmente da interface web (sistema avaliativo ID=9)

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

## 1.5 Discovery de IDs no ambiente de homologação

Antes do smoke test, é necessário descobrir os IDs reais do iScholar e preencher os mapas JSON.

### 1.5.1 Configurar credenciais

1. Copiar `.env.example` para `.env`
2. Gerar o token em https://madan_homolog.ischolar.com.br/ (seguir instruções do iScholar)
3. Preencher `ISCHOLAR_API_TOKEN` no `.env`

### 1.5.2 Rodar o script de discovery

```bash
# Discovery básico com um RA de teste conhecido:
python descobrir_ids_ischolar.py --ra <RA_TESTE>

# Com respostas brutas da API (para debug):
python descobrir_ids_ischolar.py --ra <RA_TESTE> --verbose

# Gerar esqueletos dos mapas JSON:
python descobrir_ids_ischolar.py --ra <RA_TESTE> --gerar-mapas
```

### 1.5.3 Checklist do discovery

- [x] `descobrir_ids_ischolar.py` etapa 1 (conectividade) passa sem erro **🔴 BLOQUEANTE**
- [x] `descobrir_ids_ischolar.py` etapa 2 (buscar aluno) retorna id_aluno (confirmado: RA 1222 → id_aluno 1222) **🔴 BLOQUEANTE**
- [x] `descobrir_ids_ischolar.py` etapa 3 (listar matrículas) retorna id_matricula (confirmado: id_matricula 1184 via heurística MATRICULADO) **🔴 BLOQUEANTE**
- [x] `descobrir_ids_ischolar.py` etapa 4 (listar notas) — **bloqueado** para tokens de integração (não afeta envio) **🟡 ATENÇÃO**
- [x] Shape de `/aluno/busca` compatível com `_extrair_id_aluno_da_resposta()` (campo em `dados.informacoes_basicas.id_aluno`) **🔴 BLOQUEANTE**
- [x] Shape de `/matricula/listar` compatível com a extração de `id_matricula` **🔴 BLOQUEANTE**

### 1.5.4 Preencher os mapas

1. Copiar os esqueletos gerados pelo `--gerar-mapas` para os arquivos de mapa
2. Completar com IDs adicionais da interface web do iScholar se necessário
3. Revisar nomes normalizados (sem acentos, minúsculas)

> **Limitação:** O script extrai IDs das notas de UMA matrícula. Para cobertura completa, rode com alunos de diferentes disciplinas ou consulte a interface web do iScholar.

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

- [x] `ETAPA 1 — Carregando planilha` → `✅ Planilha carregada` (10 linhas)
- [x] `ETAPA 2 — Validando template` → `✅ Template válido`
- [x] `ETAPA 3/4 — Gerando lançamentos e validando` — 30 itens sendáveis, 0 erros
- [x] `RESUMO DO LOTE` — totais coerentes com a planilha
- [x] `ETAPA 6 — Preflight Técnico` → `✅ Resolvedor pronto` (89 professores, 35 disciplinas, 19 avaliações) **🔴 BLOQUEANTE**
- [x] `ETAPA 7 — Aprovação` → aprovação automática registrada (aprovador: Pedro)
- [x] `ETAPA 8 — DRY RUN` → processados sem erro de resolução
- [x] `RESULTADO DO ENVIO` → modo `DRY RUN`, 30 sendáveis, 0 erros de resolução

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

- [x] Exit code `0` no dry-run **🔴 BLOQUEANTE**
- [x] Nenhum erro de resolução de IDs no dry-run **🔴 BLOQUEANTE**
- [x] Nenhuma linha bloqueada por erro de validação (total_erros = 0) **🔴 BLOQUEANTE**
- [x] Total sendáveis > 0 (30 itens sendáveis) **🔴 BLOQUEANTE**
- [x] Resumo do lote condiz com o conteúdo da planilha **🟡 ATENÇÃO**

---

## 3. Validação em homologação — quando o ambiente estiver disponível

### 3.1 Pré-requisitos do ambiente de homologação

- [x] URL da API confirmada: `https://api.ischolar.app`
- [x] Código da escola: `madan` (extraído do JWT)
- [x] Interface web disponível: `https://madan.ischolar.com.br/`
- [x] Token (`X-Autorizacao`) gerado e configurado no `.env` **🔴 BLOQUEANTE**
- [x] Alunos reais com RA conhecido (ALICE BARCELOS LINS RA 1222, ALICE DE MEDEIROS RA 1239, ALICE DE SÁ RA 1437)
- [x] IDs de disciplina e avaliação coletados da interface web e preenchidos nos mapas

### 3.2 Validação de conectividade

- [x] `python descobrir_ids_ischolar.py --ra <RA_TESTE>` executa sem erro de autenticação **🔴 BLOQUEANTE**
- [x] `cli_envio.py` consegue inicializar `IScholarClient` sem erro (exit 5 ausente)
- [x] Preflight técnico completa com sucesso no ambiente de homologação

### 3.3 Validação do shape real da API

- [x] `/aluno/busca` retorna resposta com estrutura compatível com o resolvedor (campo em `dados.informacoes_basicas.id_aluno`)
- [x] `id_aluno` presente e único na resposta
- [x] `/matricula/listar` retorna lista de matrículas (resolvido via heurística `status_matricula_diario == "MATRICULADO"`)
- [x] `id_professor` obrigatório confirmado na prática — piloto real bloqueou sem professor; `professor_obrigatorio=True` agora é o default do sistema **🟡 ATENÇÃO**

### 3.4 Validação dos mapas com IDs reais

- [x] `mapa_disciplinas.json` preenchido com 16 IDs reais
- [x] `mapa_avaliacoes.json` preenchido com 19 IDs reais (sistema avaliativo ID=9)
- [x] Dry-run: zero erros de resolução (30 itens sendáveis)

### 3.5 Validação do POST real em homologação (piloto controlado)

Executar com 1–3 alunos reais em ambiente de homologação, nunca diretamente em produção:

- [x] Dry-run passa sem erros
- [x] Envio real executado com `--lote-id` exclusivo (execuções 001, 002, 003)
- [x] Exit code `0` após envio real
- [x] Nota aparece corretamente no diário do iScholar após o envio (confirmado visualmente nas três execuções)
- [x] Valor enviado é a nota bruta (não ponderada)
- [x] Auditoria registrada localmente no `envio_lote_audit.db`
- [x] Reenvio do mesmo lote não duplica nota no diário (idempotência) — `LoteJaAprovadoError` antes de qualquer POST

### 3.6 Validação de falhas esperadas

- [ ] Aluno com RA inexistente → item registrado como `erro_resolucao`, demais itens continuam **🟡 pendente**
- [ ] Disciplina sem mapeamento → item registrado como `erro_resolucao`, demais itens continuam **🟡 pendente**
- [ ] Lote com nota inválida (>10) → exit code 3, envio bloqueado antes do POST **🟡 pendente**

---

## 4. Critérios de go/no-go

### ✅ Pode avançar para produção

Todos os itens abaixo precisam estar marcados:

- [x] Smoke test local passou (exit 0 no dry-run, zero erros de resolução)
- [x] Conectividade com homologação validada
- [x] Shape real das APIs validado com o TI
- [x] Mapas preenchidos com IDs reais de homologação
- [x] POST real em homologação bem-sucedido — validado com Arte, Inglês, Física A e Gramática (Língua Portuguesa)
- [x] Nota aparece corretamente no diário de homologação (confirmado visualmente nas execuções 001, 002, 003)
- [x] Idempotência confirmada (reenvio não duplica) — `LoteJaAprovadoError` bloqueia antes de qualquer POST
- [ ] Validação de falhas esperadas (RA inválido, disciplina sem mapa) — **🟡 pendente antes de lote completo**
- [x] Primeiro envio em produção acompanhado pelo desenvolvedor — **confirmado na Execução 005 (Onda A via Google Sheets, 2026-04-04)**

### 🔴 Não avançar se

Qualquer um dos itens abaixo estiver presente:

- [ ] Exit code 5 no ambiente alvo (credencial ou mapa inválido)
- [ ] Exit code 1 (erro inesperado) sem diagnóstico do desenvolvedor
- [ ] Erros de resolução de IDs > 0 no dry-run
- [ ] Nota não aparece no diário após POST real em homologação
- [ ] Shape de resposta da API diferente do esperado pelo resolvedor
- [x] ~~TI não confirmou obrigatoriedade de `id_professor`~~ — confirmado na prática; `professor_obrigatorio=True` é o default
- [ ] Mapeamentos preenchidos "no chute" sem confirmação com o iScholar

---

## 5. Pendências externas (não bloqueiam o código, bloqueiam a operação)

| Item | Quem resolve | Status |
|------|-------------|--------|
| Acesso ao ambiente | TI do iScholar | **Resolvido** — código escola `madan` |
| Credenciais | TI do iScholar | **Resolvido** — token de integração ativo |
| Shape real de `/aluno/busca` | Desenvolvedor | **Resolvido** — campo em `dados.informacoes_basicas.id_aluno` |
| Shape real de `/matricula/listar` | Desenvolvedor | **Resolvido** — heurística MATRICULADO |
| `/diario/notas` para tokens de integração | TI do iScholar | **Bloqueado** — não afeta envio |
| Confirmação se `id_professor` é obrigatório para o Madan | TI do iScholar | **Confirmado na prática** — sistema bloqueou sem professor; default alterado para `True` |
| IDs reais de disciplina | Desenvolvedor | **Resolvido** — 16 IDs coletados da interface web |
| IDs reais de avaliação | Desenvolvedor | **Resolvido** — 19 IDs do sistema avaliativo ID=9 |
| IDs reais de professor | Desenvolvedor | **Resolvido** — 25 IDs coletados da interface web |
| POST real em homologação | Operador | **Concluído** — execuções 001 (Arte), 002 (Inglês), 003 (Física A + Gramática), 005 (Onda A via Sheets) |
| Teste de idempotência | Operador | **Concluído** — `LoteJaAprovadoError` confirmado em execução 001 |
| Adoção formal do template fixo pelo Madan | Madan | Pendente |
| Garantia de preenchimento do RA pelo Madan | Madan | Pendente |

---

## 5.1 Expansao controlada para o 2o ano

> **Atualizacao de status (2026-04-07):**
> - RAs reais de `2A` e `2B` ja foram usados no checker de cadastro;
> - `buscar_aluno` + `listar_matriculas` ja foram validados tecnicamente para as turmas do 2o ano, com pendencias isoladas por aluno;
> - `2A_T1` ja passou pelo dry-run tecnico no workbook anual;
> - `2B_T1 / Arte` foi enviado com sucesso em producao real via Plano B (3/3 enviados, 0 erros);
> - `2A_T1` e `2A_T2` chegaram ao POST real, mas o iScholar rejeitou os itens com
>   `Divisao nao pertence ao sistema avaliativo da turma vinculada a matricula informada na requisicao`;
> - isso caracteriza pendencia de sistema avaliativo/configuracao do `2A`, nao falha da arquitetura Plano B;
> - apos regularizacao do `2A` no iScholar, o proximo teste alvo deve ser:
>   **aba `2A_T1` -> Matematica Frente A -> 2 ou 3 alunos**, para fechar a validacao
>   do caso sensivel de professor (`Daniel`, id 66).

> **Desambiguacao automatica implementada (Plano B):** o adaptador wide agora resolve o professor
> correto por turma a partir do nome da aba (`2A_T1`, `2B_T2`, etc.). Aliases manuais em
> `Frente - Professor` nao sao mais necessarios no fluxo Plano B. Os itens abaixo refletem
> o estado atual.

- [ ] Confirmar nomes das turmas do iScholar para o 2o ano (`2A`, `2B` ou variante oficial) **BLOQUEANTE**
- [ ] Obter RA real de 1-2 alunos de `2A` e `2B` para dry-run tecnico **BLOQUEANTE**
- [ ] Validar `buscar_aluno` + `listar_matriculas` para alunos reais do 2o ano **BLOQUEANTE**
- [x] ~~Rodar piloto com aliases explicitos em `Frente - Professor`~~ — **automatizado via Plano B**: o adaptador qualifica a chave com o professor correto ao detectar a turma no nome da aba
- [ ] Dry-run com aba `2A_T1` do workbook anual — confirmar resolucao automatica de professor **BLOQUEANTE**
- [ ] Confirmar no diario do iScholar um envio pequeno do 2o ano via aba `2A_T1` (Sheets) **BLOQUEANTE**
- [ ] Validar a geracao automatica de planilhas 2A/2B com o registro do PDF 2026 ja reconciliado
- [ ] Confirmar no iScholar os casos ainda sensiveis: Redacao, Literatura e Interpretacao de Texto no 2o ano

Resolucao automatica por turma ja implementada e testada unitariamente:

| Turma | Disciplina / Frente | Professor resolvido automaticamente |
|-------|---------------------|--------------------------------------|
| 2A    | Matematica Frente A | Daniel (id 66)                       |
| 2B    | Matematica Frente B | Luan (id 71)                         |
| 2C    | Matematica Frente C | Carioca (id 57)                      |
| 2A    | Biologia            | Perrone (id 86)                      |
| 2B    | Biologia Frente B   | Mayara (id 59)                       |
| 2A    | Geografia Frente A  | Carla (id 72)                        |
| 2B    | Geografia Frente B  | Moreto (id 165)                      |

---

## 6. Registro de execução do checklist

---

### Execução 001 — Piloto Arte AV1 (homologação assistida — correção de bugs)

| Campo | Valor |
|-------|-------|
| Data | 2026-04-01 |
| Ambiente | produção (iScholar real) |
| Lote ID (dry-run) | homolog-piloto-003-dryrun |
| Lote ID (real) | homolog-piloto-003-real |
| Planilha | nova_planilha.xlsx |
| Disciplina testada | Arte — Frente Única (AV 1 Obj + AV 1 Disc) |
| Alunos | 3 (ALICE BARCELOS LINS / RA 1222, ALICE DE MEDEIROS GARCIA / RA 1239, ALICE DE SÁ FREITAS SOARES / RA 1437 — Turma 1A, T2) |
| Operador / aprovador | pedro |
| Resultado dry-run | ✅ sucesso — 3/3 processados, 0 erros de resolução, 0 erros de envio |
| Resultado POST real | ✅ sucesso — 3/3 enviados, status `sent`, exit code 0 |
| Evidência no diário | ✅ notas apareceram corretamente no diário do iScholar (confirmado visualmente) |
| Idempotência | ✅ reenvio com mesmo lote-id bloqueado com `LoteJaAprovadoError` antes de qualquer POST |
| Exit code | 0 |
| ObservaÃ§Ãµes | 10 linhas processadas, 30 itens sendÃ¡veis, 0 erros. Planilha com 3 alunos (RA 1222, 1239, 1437) Ã— 7 disciplinas. Avisos PROFESSOR_NAO_ENCONTRADO_REGISTRO nÃ£o bloqueantes (frentes tipo "Matematica A" vs registro hardcoded). Auto-detecÃ§Ã£o de header funcionou (planilha com cÃ©lula mesclada na linha 1). |

---

### ExecuÃ§Ã£o 007 â€” Plano B: piloto real 2B_T1 com Arte

| Campo | Valor |
|-------|-------|
| Data | 2026-04-07 |
| Ambiente | produÃ§Ã£o (iScholar real) |
| Lote ID | `plano-b-2b-t1-arte-real` |
| Planilha | `dryrun2ano.xlsx` â€” workbook anual multi-aba, aba `2B_T1` |
| Disciplina testada | Arte â€” Frente Ãšnica |
| Alunos | 3 alunos da turma 2B (`OK` no checker de cadastro) |
| Operador / aprovador | Coordenacao |
| Resultado dry-run | n/a â€” registro baseado no POST real validado |
| Resultado POST real | **Sucesso** â€” 3/3 enviados, 0 erros de resolucao, 0 erros de envio, status final `sent` |
| EvidÃªncia no diÃ¡rio | âœ… confirmado visualmente no iScholar â€” notas postadas corretamente |
| IdempotÃªncia | pendente de teste dedicado |
| Exit code | 0 |
| Warnings presentes | âš ï¸ `PROFESSOR_NAO_ENCONTRADO_REGISTRO` para `interpretacao de texto - lucas` (nao bloqueante e sem relacao com o lote de Arte) |
| ObservaÃ§Ãµes | **Primeira validacao real do Plano B em producao**: workbook anual, selecao por `--aba`, derivacao de `Turma/Trimestre`, resolucao de IDs e POST real funcionando para o 2o ano. O caso `2A` permanece pendente por configuracao de sistema avaliativo no iScholar; o proximo teste alvo apos regularizacao e `2A_T1 / Matematica Frente A` com 2â€“3 alunos para fechar a validacao da desambiguacao de professor. |
| Bugs corrigidos nesta execução | **Bug 1:** `ischolar_client.py` declarava `sucesso=True` para HTTP 200 com `{"status":"erro"}` no corpo — corrigido: agora inspeciona o corpo e retorna `sucesso=False` + `erro_categoria="negocio"`. **Bug 2:** `mapa_professores.json` não tinha a chave `"arte"` (wide_format_adapter produz chave sem sufixo de professor para Frente Única) — corrigido: adicionados aliases `"arte": 96`, `"biologia": 61`, `"sociologia": 49`, `"filosofia": 49`. |
| Warnings presentes | ⚠️ `PROFESSOR_NAO_ENCONTRADO_REGISTRO` para arte, biologia, fisica a, fisica b, fisica c — avisos de validação (estágio 1-5) contra registro oficial Madan 2026. Não bloquearam o envio. Professor foi resolvido corretamente na etapa 8 via `mapa_professores.json`. A investigar: de onde vem esse registro oficial e como atualizá-lo. |
| Observações | Primeira execução real bem-sucedida após correção dos dois bugs críticos de homologação. |

---

### Execução 002 — Piloto Inglês AV1 (validação de segunda disciplina)

| Campo | Valor |
|-------|-------|
| Data | 2026-04-01 |
| Ambiente | produção (iScholar real) |
| Lote ID (dry-run) | homolog-piloto-004-dryrun |
| Lote ID (real) | homolog-piloto-004-real |
| Planilha | planilha_homolog_disciplina_simples.xlsx |
| Disciplina testada | Inglês — Frente Única (AV 1 Obj + AV 1 Disc) |
| Alunos | 3 (ALICE BARCELOS LINS / RA 1222 → 10, ALICE DE MEDEIROS GARCIA / RA 1239 → 10, ALICE DE SÁ FREITAS SOARES / RA 1437 → 10 — Turma 1A, T2) |
| Operador / aprovador | pedro |
| Resultado dry-run | ✅ sucesso — 3/3 processados, 0 erros de resolução, 0 erros de envio |
| Resultado POST real | ✅ sucesso — 3/3 enviados, status `sent`, exit code 0 |
| Evidência no diário | ✅ nota 10 apareceu corretamente para as 3 alunas no diário do iScholar (confirmado por screenshot) |
| Idempotência | não testada nesta execução (já validada na execução 001) |
| Exit code | 0 |
| Warnings presentes | ⚠️ mesmos `PROFESSOR_NAO_ENCONTRADO_REGISTRO` da execução 001 (arte, biologia, fisica a/b/c). Inglês não gerou aviso — professor `"ingles": 60` já estava no mapa e no registro oficial. |
| Observações | Confirma que o fluxo funciona para disciplinas além de Arte. Inglês tem professor único sem dependência de série — escolha ideal para segundo piloto. Nota 10 no diário é soma de AV1 Obj (6+5+7) + AV1 Disc (4+5+3) conforme ponderação do iScholar. |

---

### Execução 003 — Piloto Ampliado (Física A + Gramática/Língua Portuguesa)

| Campo | Valor |
|-------|-------|
| Data | 2026-04-02 |
| Ambiente | produção (iScholar real) |
| Lote ID (tentativa 1) | homolog-piloto-005-real |
| Lote ID (real, v2) | homolog-piloto-005-real-v2 |
| Planilha | planilha_homolog_piloto_ampliado.xlsx |
| Disciplinas testadas | Física A (multi-frente) e Gramática — Frente Única (AV 1 Obj + AV 1 Disc) |
| Alunos | 3 (ALICE BARCELOS LINS / RA 1222, ALICE DE MEDEIROS GARCIA / RA 1239, ALICE DE SÁ FREITAS SOARES / RA 1437 — Turma 1A, T2) |
| Operador / aprovador | pedro |
| Resultado dry-run | ✅ sucesso — 6/6 processados, 0 erros de resolução |
| Resultado POST real | ✅ sucesso — 6/6 enviados, status `sent`, exit code 0 (após correção de mapeamento) |
| Evidência no diário | ✅ notas apareceram corretamente no diário do iScholar — LÍNGUA PORTUGUESA com professor NERYANNE REIS ZANOTELLI, notas 7/10/8 para as 3 alunas (confirmado visualmente) |
| Idempotência | não testada nesta execução (já validada na execução 001) |
| Exit code | 0 |
| Bug corrigido nesta execução | `mapa_disciplinas.json` tinha `"gramatica": 172` (id inválido). iScholar retornou HTTP 200 + `{"status":"erro", "mensagem":"Disciplina não pertence a grade curricular..."}` — diagnóstico via `envio_lote_audit.db`. Corrigido: `"gramatica": 29`, `"lingua portuguesa": 29` (id confirmado via interface web do iScholar). |
| Observações | Gramática não existe como disciplina autônoma no iScholar para 1ª e 2ª série — está cadastrada como **LÍNGUA PORTUGUESA** (id=29, sigla POR). Literatura e Gramática compartilham a mesma disciplina; o professor é o elemento que diferencia as frentes. Física A validou o cenário multi-frente (disciplina com mais de uma frente por turma). |

---

### Execução 004 — Gate Validação via Google Sheets (sem POST real)

| Campo | Valor |
|-------|-------|
| Data | 2026-04-03 |
| Ambiente | produção (iScholar real — sem POST, apenas validação) |
| Lote ID | 1-xFbHa89XLIIxqcGbCtwzuB2lN4anFjt1cZjWdJzhAg/Notas |
| Snapshot hash | ed12bb6fbbf9259743c662b205b1954cd2f577475cca4efb7c399d247adee341 |
| Planilha | Google Sheets (nova, aba "Notas") |
| Disciplina testada | Gramática — Frente Única (AV 1 Obj + AV 1 Disc) |
| Alunos | 3 (RA 1222, 1239, 1437 — Turma 1A, T2) |
| Operador / aprovador | pedro |
| Resultado auth sem secret | ✅ HTTP 401 na rota protegida `/lote/__probe__/validacao` |
| Resultado auth com secret | ✅ HTTP 404 (auth passou, lote inexistente esperado) |
| Resultado POST /webhook/notas | ✅ HTTP 202, job_id e snapshot_hash presentes |
| Resultado worker | ✅ job processado com sucesso |
| Resultado GET /lote/{id}/validacao | ✅ status: validation_pending_approval, finalizado: true, pode_aprovar: true |
| Dialog no Sheets | ✅ "Validacao concluida. O lote esta apto para aprovacao." |
| Evidência no diário | — (sem POST real nesta execução) |
| Observações | Primeiro teste end-to-end via Google Sheets. Túnel ngrok usado para expor backend. Header `ngrok-skip-browser-warning: true` necessário em todas as requisições. Pendências IDENTIFICADOR_ISCHOLAR_PENDENTE são não-bloqueantes — resolvidas apenas no envio real. Gate de validação via Sheets: **FECHADO**. |

---

### Execução 005 — Onda A: Primeiro POST real via Google Sheets

| Campo | Valor |
|-------|-------|
| Data | 2026-04-04 |
| Ambiente | produção (iScholar real) |
| Lote ID | 1-xFbHa89XLIIxqcGbCtwzuB2lN4anFjt1cZjWdJzhAg/Notas |
| Snapshot hash | ed12bb6fbbf9259743c662b205b1954cd2f577475cca4efb7c399d247adee341 |
| Planilha | Google Sheets (aba "Notas") |
| Disciplina testada | Gramática — Frente Única (AV 1 Obj + AV 1 Disc) |
| Alunos | 3 (ALICE BARCELOS LINS RA 1222 → 7, ALICE DE MEDEIROS GARCIA RA 1239 → 10, ALICE DE SÁ FREITAS SOARES RA 1437 → 8 — Turma 1A, T2) |
| Operador / aprovador | Pedro (email: pedroberlatoaj1@gmail.com, identidade: medium) |
| Resultado POST /webhook/notas | ✅ HTTP 202 |
| Resultado worker | ✅ job processado |
| Resultado GET /lote/{id}/validacao | ✅ validation_pending_approval, pode_aprovar: true |
| Resultado Aprovar e Enviar | ✅ 3/3 enviados, 0 erros de resolução, 0 erros de envio, status: sent |
| Evidência no diário | ✅ notas 7, 10 e 8 visíveis no diário do iScholar para as 3 alunas (confirmado visualmente) |
| Identidade do aprovador | medium (email de sessão Apps Script disponível) |
| Observações | **Primeiro fluxo completo end-to-end via Google Sheets com POST real no iScholar.** Fluxo: Apps Script → ngrok → backend → worker → iScholar. Snapshot hash coerente entre validação (Execução 004) e aprovação. Onda A: **FECHADA**. |

---

### Execução 006 — Onda B: Lote completo 1A via Google Sheets (91 sendáveis)

| Campo | Valor |
|-------|-------|
| Data | 2026-04-04 |
| Ambiente | produção (iScholar real) |
| Lote ID | 1-xFbHa89XLIIxqcGbCtwzuB2lN4anFjt1cZjWdJzhAg/Notas |
| Planilha | Google Sheets (aba "Notas") — turma 1A completa |
| Disciplinas testadas | Arte + Inglês (Frente Única, AV 1 Obj + AV 1 Disc) |
| Alunos | ~44 alunos da turma 1A T2 |
| Total sendáveis | 91 |
| Operador / aprovador | Pedro |
| Resultado | 71–72 enviados / 8 erro_resolucao / 12 erro_envio |
| Evidência no diário | ✅ confirmado visualmente — exatamente 10 alunos sem nota (os esperados pelo audit) |
| Bug descoberto | `resolvedor_ids_ischolar.py`: heurística `situacao=cursando` só ativava com múltiplos resultados. Corrigido para ativar também com 0 resultados. Fix commitado em 034f914. |
| Erros residuais | **8 erro_resolucao (4 alunos):** matrícula não acessível via API mesmo com filtro `situacao=cursando` — dado iScholar incompleto. **12 erro_envio (6 alunos):** grade curricular diferente no iScholar — alunos em trilha separada. Ambos requerem intervenção do admin iScholar. |
| Observações | Onda B valida escala operacional. Pipeline isolou corretamente todos os erros sem bloquear os 71+ enviados com sucesso. Erros são dados do iScholar, não bugs do pipeline. |

---

### Execução 007 — Plano B: Piloto 2B_T2 via CLI (multi-frente, aba anual)

| Campo | Valor |
|-------|-------|
| Data | 2026-04-08 |
| Ambiente | produção (iScholar real) |
| Planilha | `madan_2026_anual.xlsx` — aba `2B_T2` |
| Disciplinas testadas | Geografia Frente B + Educação Física Frente Única |
| Alunos | turma 2B — lote real |
| Operador / aprovador | Pedro |
| Resultado Geografia — Frente B | ✅ POST real aceito — professor Moreto (id 165) resolvido corretamente via `_qualificar_chave_com_professor` |
| Resultado Ed Física — Frente Única | ❌ `[professor_sem_mapeamento] 'educacao fisica - joao' (chave: 'educacao fisica joao') não encontrado em mapa_professores` |
| Causa do erro Ed Física | `_apelido_slug` usa `prof.nome.split()[0]` = `"joao"` (João Paulo sem apelido definido). Chave gerada `"educacao fisica joao"` ausente no mapa. |
| Correção aplicada | Adicionados 4 aliases em `mapa_professores.json`: `"educacao fisica - joao": 148`, `"educacao fisica joao": 148`, `"ed fisica - joao": 148`, `"ed fisica joao": 148` |
| Risco de regressão | Zero — novas chaves adicionais, nenhuma removida, mesmo ID 148 já mapeado |
| Próximo passo | Reenviar 2B_T2 Ed Física com o mapa corrigido para confirmar resolução |
| Observações | Execução confirma que a estrutura de 193 colunas do Plano B está operacional. Desambiguação por professor funciona corretamente para multi-frente (GEO Frente B → Moreto). Falha de Ed Física é alias ausente no mapa — incidente do pipeline, não do iScholar. |

---

### Template para próximas execuções

| Campo | Valor |
|-------|-------|
| Data | |
| Ambiente | homologação / produção |
| Lote ID (dry-run) | |
| Lote ID (real) | |
| Planilha | |
| Disciplina testada | |
| Alunos | |
| Operador / aprovador | |
| Resultado dry-run | |
| Resultado POST real | |
| Evidência no diário | |
| Idempotência | |
| Exit code | |
| Warnings presentes | |
| Observações | |

### Execução 1 — Dry-run (2026-03-28)

| Campo | Valor |
|-------|-------|
| Data | 2026-03-28 |
| Ambiente | produção (código escola: `madan`) |
| Lote ID | smoke-test-001 |
| Operador | Pedro |
| Resultado | **Sucesso** (dry-run) |
| Exit code | 0 |
| Observações | 10 linhas processadas, 30 itens sendáveis, 0 erros. Planilha com 3 alunos (RA 1222, 1239, 1437) × 7 disciplinas. Avisos PROFESSOR_NAO_ENCONTRADO_REGISTRO não bloqueantes (frentes tipo "Matematica A" vs registro hardcoded). Auto-detecção de header funcionou (planilha com célula mesclada na linha 1). |

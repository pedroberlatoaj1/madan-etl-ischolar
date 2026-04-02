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

- [ ] `python descobrir_ids_ischolar.py --ra <RA_TESTE>` executa sem erro de autenticação **🔴 BLOQUEANTE**
- [ ] `cli_envio.py` consegue inicializar `IScholarClient` sem erro (exit 5 ausente)
- [ ] Preflight técnico completa com sucesso no ambiente de homologação

### 3.3 Validação do shape real da API

- [x] `/aluno/busca` retorna resposta com estrutura compatível com o resolvedor (campo em `dados.informacoes_basicas.id_aluno`)
- [x] `id_aluno` presente e único na resposta
- [x] `/matricula/listar` retorna lista de matrículas (resolvido via heurística `status_matricula_diario == "MATRICULADO"`)
- [ ] Confirmado com o TI se `id_professor` é obrigatório para a escola Madan **🟡 ATENÇÃO**

### 3.4 Validação dos mapas com IDs reais

- [x] `mapa_disciplinas.json` preenchido com 16 IDs reais
- [x] `mapa_avaliacoes.json` preenchido com 19 IDs reais (sistema avaliativo ID=9)
- [x] Dry-run: zero erros de resolução (30 itens sendáveis)

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
| Acesso ao ambiente | TI do iScholar | **Resolvido** — código escola `madan` |
| Credenciais | TI do iScholar | **Resolvido** — token de integração ativo |
| Shape real de `/aluno/busca` | Desenvolvedor | **Resolvido** — campo em `dados.informacoes_basicas.id_aluno` |
| Shape real de `/matricula/listar` | Desenvolvedor | **Resolvido** — heurística MATRICULADO |
| `/diario/notas` para tokens de integração | TI do iScholar | **Bloqueado** — não afeta envio |
| Confirmação se `id_professor` é obrigatório para o Madan | TI do iScholar | **Pendente** |
| IDs reais de disciplina | Desenvolvedor | **Resolvido** — 16 IDs coletados da interface web |
| IDs reais de avaliação | Desenvolvedor | **Resolvido** — 19 IDs do sistema avaliativo ID=9 |
| IDs reais de professor | Desenvolvedor | **Resolvido** — 25 IDs coletados da interface web |
| POST real em homologação | Operador | **Pendente** — próximo passo |
| Teste de idempotência | Operador | **Pendente** |
| Adoção formal do template fixo pelo Madan | Madan | Pendente |
| Garantia de preenchimento do RA pelo Madan | Madan | Pendente |

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
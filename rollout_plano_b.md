# Plano de Rollout — Plano B (Workbook Anual Multi-Aba)

**Data de elaboração:** 2026-04-07
**Escopo:** Implantação gradual do workbook anual `madan_2026_anual.xlsx` (12 abas trimestrais) como fluxo operacional padrão, com coexistência controlada com o fluxo por turma até validação completa do 2º ano.

> **O 1º ano não será tocado até a Fase 3.** Todas as fases iniciais incidem exclusivamente sobre o 2º ano. A homologação das Execuções 001–006 permanece intacta.

---

## Estado de partida

| Componente | Status |
|------------|--------|
| 1º ano (1A, 1B) via Plano B | ✅ Pronto no código — não pilotado ainda via workbook anual |
| 1º ano (1A, 1B) via fluxo legado (planilha por turma) | ✅ Homologado (Execuções 001–006) |
| 2º ano — disambiguação automática (código) | ✅ Implementado e testado (42 testes unitários) |
| 2º ano — validação de `buscar_aluno` / `listar_matriculas` no iScholar | ❌ Não feito — RAs reais de 2A/2B nunca testados |
| 2º ano — POST real no iScholar | ❌ Nenhum envio feito para alunos do 2º ano |
| Apps Script — aba ativa em vez de "Notas" fixo | ✅ Implementado |
| `verificar_cadastro.py` — deduplicação Plano B | ✅ Implementado |

**Risco principal:** resolução de IDs do 2º ano nunca foi validada contra a API real. A disambiguação automática pode estar correta no código e ainda assim falhar se o iScholar tiver as turmas `2A`/`2B` com nomes ou estruturas diferentes do esperado.

---

## Critérios gerais de go/no-go

Um critério marcado como **BLOQUEANTE** impede avançar para a fase seguinte mesmo que tudo mais esteja ok.

| Critério | Classificação |
|----------|---------------|
| `buscar_aluno` retorna `id_aluno` para RA real de 2A | BLOQUEANTE |
| `listar_matriculas` retorna `id_matricula` para aluno de 2A | BLOQUEANTE |
| Dry-run com aba `2A_T1` sai com exit 0, 0 erros de resolução | BLOQUEANTE |
| POST real aparece no diário do iScholar com valor correto | BLOQUEANTE |
| Reenvio do mesmo lote não duplica nota no diário | BLOQUEANTE |
| 1º ano continua funcionando sem regressão após cada fase | BLOQUEANTE |
| Erros de resolução ≤ 20% dos itens enviados | ATENÇÃO — investigar antes de ampliar |

---

## Fase 0 — Pré-condições (antes de qualquer piloto do 2º ano)

**Responsável:** Dev
**Duração estimada:** 1 sessão (~30 min)
**Objetivo:** Garantir que o terreno está preparado antes de qualquer envio real do 2º ano.

### Checklist

- [ ] Obter pelo menos 1 RA real de aluno de `2A` e 1 de `2B` com a coordenação
- [ ] Confirmar com a coordenação o nome oficial das turmas no iScholar (`2A`, `2B`, ou variante)
- [ ] Rodar `verificar_cadastro.py` com o workbook anual para validar cadastro dos alunos de 2A/2B:
  ```bash
  .venv\Scripts\python.exe verificar_cadastro.py madan_2026_anual.xlsx --aba 2A_T1
  ```
- [ ] Confirmar que `buscar_aluno` retorna `id_aluno` para pelo menos 1 RA de 2A
- [ ] Confirmar que `listar_matriculas` retorna `id_matricula` para o mesmo aluno

### Critério de conclusão da Fase 0

Todos os itens do checklist marcados. Sem exceção — esses dados são pré-requisito das fases seguintes.

### Ponto de parada

Se `buscar_aluno` falhar para todos os RAs de 2A testados: **parar e contatar TI do iScholar**. Não avançar.

---

## Fase 1 — Piloto 2A_T1: Arte (disciplina sem ambiguidade)

**Responsável:** Dev (executa) + Coordenação (observa)
**Pré-requisito:** Fase 0 concluída
**Objetivo:** Provar que o fluxo Plano B (aba ativa → validação → envio) funciona para o 2º ano com uma disciplina de professor único — sem acionar a disambiguação automática.

Arte foi escolhida porque:
- Professor único para 1A e 2A (`arte: 96`) — não há ambiguidade a resolver
- Já homologada para 1A (Execução 001) — comportamento conhecido
- Isola o risco: se falhar, é problema de infraestrutura (RA/matrícula 2A), não de disambiguação

### Passos

1. No Google Sheets, navegar até a aba **`2A_T1`**
2. Preencher 2–3 alunos com notas de Arte apenas
3. Dry-run via CLI:
   ```bash
   .venv\Scripts\python.exe cli_envio.py \
     --planilha madan_2026_anual.xlsx \
     --aba 2A_T1 \
     --lote-id plano-b-2a-t1-arte-dryrun \
     --dry-run \
     --aprovador "Coordenacao"
   ```
4. Conferir: `erros_resolucao: 0`, `erros_envio: 0` no dry-run
5. POST real:
   ```bash
   .venv\Scripts\python.exe cli_envio.py \
     --planilha madan_2026_anual.xlsx \
     --aba 2A_T1 \
     --lote-id plano-b-2a-t1-arte-real \
     --aprovador "Coordenacao"
   ```
6. Verificar nota no diário do iScholar para os alunos enviados
7. Repetir o envio com o **mesmo lote-id** e confirmar que `LoteJaAprovadoError` bloqueia (idempotência)

### Critérios de go

- [ ] Dry-run: exit 0, `erros_resolucao: 0` **BLOQUEANTE**
- [ ] POST real: exit 0, nota enviada **BLOQUEANTE**
- [ ] Nota visível no diário com valor correto **BLOQUEANTE**
- [ ] Reenvio bloqueado (idempotência) **BLOQUEANTE**
- [ ] 1A continua funcionando (testar 1 dry-run de `1A_T1` para confirmar sem regressão)

### Ponto de parada

Se `erros_resolucao > 0` no dry-run: RAs de 2A não estão acessíveis via API. **Parar e acionar TI do iScholar antes de continuar.**

Se POST real falhar com erro de grade curricular em >50% dos alunos: turma 2A pode ter grade diferente no iScholar. **Parar e mapear.**

---

## Fase 2 — Piloto 2A_T1: Matemática Frente A — Daniel

**Pré-requisito:** Fase 1 concluída
**Objetivo:** Validar em produção a disambiguação automática — o caso central do Plano B para o 2º ano.

Esta é a disciplina de maior risco: Matemática Frente A resolve para **Luan** em 1A e para **Daniel** em 2A. Se a disambiguação estiver errada, a nota é lançada com o professor incorreto.

### Verificação antes do envio

Antes do POST real, inspecionar o dry-run para confirmar a resolução:

```bash
.venv\Scripts\python.exe cli_envio.py \
  --planilha madan_2026_anual.xlsx \
  --aba 2A_T1 \
  --lote-id plano-b-2a-t1-mat-a-dryrun \
  --dry-run \
  --aprovador "Coordenacao"
```

Verificar nos logs que `id_professor` resolvido é **66 (Daniel)** e **não 71 (Luan)**.

Se o log não for explícito, consultar o audit store após o dry-run:
```bash
sqlite3 envio_lote_audit.db "SELECT id_professor FROM audit WHERE lote_id = 'plano-b-2a-t1-mat-a-dryrun';"
```

### Passos

1. Preencher 2–3 alunos com notas de Matemática Frente A na aba `2A_T1`
2. Dry-run + verificação de `id_professor = 66` nos logs
3. POST real com lote-id exclusivo (`plano-b-2a-t1-mat-a-real`)
4. Verificar no diário do iScholar: disciplina, professor e valor corretos

### Critérios de go

- [ ] Dry-run: `id_professor = 66` (Daniel) — **não 71 (Luan)** **BLOQUEANTE**
- [ ] POST real: exit 0, nota enviada **BLOQUEANTE**
- [ ] Diário mostra professor Daniel, não Luan **BLOQUEANTE**
- [ ] 1A não afetado: dry-run de `1A_T1` com Matemática ainda resolve Luan (id 71) **BLOQUEANTE**

### Ponto de parada

Se `id_professor = 71` aparecer no dry-run de 2A_T1: disambiguação com defeito — **não enviar, abrir investigação antes de continuar**.

---

## Fase 3 — Expansão para turmas sensíveis restantes de 2A

**Pré-requisito:** Fases 1 e 2 concluídas
**Objetivo:** Validar as demais disciplinas com troca de professor no 2º ano.

Sequência recomendada (do mais simples ao mais complexo):

| Passo | Disciplina | Professor esperado | Por que esta ordem |
|-------|-----------|-------------------|-------------------|
| 3.1 | Biologia | Perrone (id 86) | Professor único para 2A — sem ambiguidade de frente |
| 3.2 | Geografia Frente A | Carla (id 72) | Frente explícita — resolve limpo |
| 3.3 | Matemática Frente B | Luan (id 71) | Luan em 2A para Frente B — diferente de Frente A |
| 3.4 | Matemática Frente C | Carioca (id 57) | Terceira frente — confirma múltiplas frentes em 2A |

Para cada passo: dry-run primeiro, verificar `id_professor`, depois POST real com lote-id exclusivo.

### Critérios de conclusão da Fase 3

- [ ] Todas as 4 disciplinas acima: exit 0, professor correto no diário
- [ ] Nenhuma regressão no 1º ano (1 dry-run de controle por semana de piloto)

---

## Fase 4 — Validação de 2B

**Pré-requisito:** Fase 3 concluída
**Objetivo:** Confirmar que `2B` tem o mesmo comportamento que `2A` na API do iScholar.

2B tem mapa próprio (Mayara para Biologia, Moreto para Geografia, Luan para Matemática Frente B). Pilotar com Arte primeiro (mesmo protocolo da Fase 1 para 2A), depois Matemática.

### Critérios

- [ ] Arte 2B: exit 0, nota no diário **BLOQUEANTE**
- [ ] Matemática 2B (Luan Frente B): `id_professor = 71` confirmado no dry-run
- [ ] Biologia 2B: Mayara (id 59) confirmada

---

## Fase 5 — Migração do 1º ano para Plano B

**Pré-requisito:** Fases 1–4 concluídas
**Objetivo:** Consolidar o fluxo: operador usa apenas o workbook anual para todas as turmas.

Esta fase é opcional operacionalmente — o 1º ano continua funcionando com planilhas individuais indefinidamente. A migração só faz sentido quando o operador estiver confortável com o Plano B.

### Estratégia de migração

1. Dry-run de `1A_T1` via aba do workbook anual (comparar com resultado do fluxo legado)
2. Se idêntico: adotar o workbook anual como fonte única
3. Arquivar as planilhas individuais (não deletar — manter por 1 trimestre como fallback)

### Critério

- [ ] Dry-run de `1A_T1` via workbook anual produz lote idêntico ao dry-run com planilha individual

---

## Plano de coexistência durante o rollout

O fluxo legado (planilha individual por turma) permanece operacional durante todo o rollout. Não há necessidade de desativá-lo.

| Turma | Fluxo durante rollout | Condição para migrar |
|-------|----------------------|----------------------|
| 1A, 1B | **Legado** (planilha individual) | Após Fase 5 |
| 2A | **Plano B** (aba `2A_T*`) | A partir da Fase 1 |
| 2B | **Plano B** (aba `2B_T*`) | A partir da Fase 4 |

### Regra de convivência

- Nunca misturar fluxos para a mesma turma e trimestre no mesmo ciclo de envio
- Se o operador processar `2A_T1` via Plano B, não processar `2A_T1` via planilha individual (duplicação)
- `lote_id` diferente por fluxo garante isolamento técnico; o risco real é duplicar nota no diário do iScholar

---

## Como voltar atrás

O rollback é sempre possível. O fluxo legado nunca foi removido.

### Por turma

Se uma turma falhar no Plano B, retornar imediatamente para o fluxo legado:

```bash
# Voltar para planilha individual (1A exemplo):
.venv\Scripts\python.exe cli_envio.py \
  --planilha planilhas/1A_T1_2026.xlsx \
  --lote-id rollback-1a-t1-001 \
  --aprovador "Coordenacao"
```

### Via Google Sheets (rollback operacional)

1. Criar (ou acessar) a planilha legada com aba `Notas`
2. O Apps Script usa aba ativa — navegar para a aba `Notas`
3. O dialog de confirmação vai indicar que a aba não segue o padrão Plano B — confirmar para prosseguir

### O que NÃO muda no rollback

- Nenhum arquivo de código precisa ser revertido
- Os stores SQLite (audit, aprovações) são independentes por `lote_id`
- O `mapa_professores.json` não precisa ser alterado

---

## Critérios de parada total (stop criteria)

**Interromper o rollout imediatamente e acionar o dev se:**

- POST real do 2º ano lançar nota com professor errado no diário (id_professor incorreto)
- Nota do 2º ano duplicar no diário após reenvio
- Erros de resolução sistemáticos em 2A (>30% dos alunos) sem causa identificada
- Qualquer regressão no 1º ano (exit 0 que antes era 0 passa a ter erros_resolucao > 0)
- Worker morrer e jobs do Plano B ficarem presos em `pending` permanentemente

**Não parar por:**

- Erros de resolução isolados (1–2 alunos com RA errado na planilha)
- Timeout de polling no Sheets — usar "Mostrar Último Status"
- `send_failed` com >70% de sucesso (erros são dados do iScholar, não do pipeline)

---

## Pontos de controle

| Fase | Controle | O que verificar |
|------|---------|-----------------|
| 0 | RA real de 2A resolve no iScholar | `buscar_aluno` retorna id_aluno |
| 1 | Arte 2A no diário | Nota correta, professor correto (id 96) |
| 2 | Matemática Frente A 2A no diário | Professor = Daniel (id 66), não Luan (id 71) |
| 2 | Regressão 1A | Matemática 1A ainda resolve Luan (id 71) |
| 3 | Todas as disciplinas sensíveis 2A | Professor correto por disciplina no audit |
| 4 | Arte 2B no diário | Mesma estrutura que 2A — confirma paridade |
| 5 | Dry-run 1A via Plano B | Resultado idêntico ao fluxo legado |

---

## Sugestão de commit

```
feat: plano de rollout Plano B — sequencia de implantacao gradual por turma

Cobre: precondições (RAs 2A/2B), piloto 2A_T1 com Arte e Matemática A,
expansão para disciplinas sensíveis, validação 2B, migração opcional
do 1º ano. Inclui critérios objetivos de go/no-go, ponto de parada
e procedimento de rollback sem alteração de código.
```

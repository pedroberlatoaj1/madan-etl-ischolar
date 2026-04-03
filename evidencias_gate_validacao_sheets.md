# Evidências — Gate Validação via Google Sheets
**Data:** 2026-04-03
**Executor:** Pedro
**Gate:** Provar fluxo de Validar Lote via Google Sheets (sem POST real no iScholar)

---

## Teste de Autenticação (rota protegida)

Rota usada: `GET /lote/__probe__/validacao`

| Cenário | HTTP retornado | Esperado | Status |
|---------|---------------|----------|--------|
| Sem `X-Webhook-Secret` | **401** | 401 | ✅ |
| Com `X-Webhook-Secret: Madan2026!SuperSeguroEtl` | **404** | 404 | ✅ |

Corpo da resposta sem secret:
```json
{"codigo":"nao_autorizado","erro":"Nao autorizado","request_id":"d74ecc2edec9a56c"}
```

Corpo da resposta com secret:
```json
{"erro":"Resultado de validacao nao encontrado."}
```

---

## Execução de Validar Lote

**Planilha Google Sheets:** nova planilha (sheets.new)
**Aba:** Notas
**Dados:** Gramática - Frente Única - AV 1 Obj/Disc, 3 alunos (RA 1222, 1239, 1437), Turma 1A, T2

### Resposta do POST /webhook/notas

- HTTP: **202** ✅
- `lote_id`: `1-xFbHa89XLIIxqcGbCtwzuB2lN4anFjt1cZjWdJzhAg/Notas`
- `snapshot_hash`: `ed12bb6fbbf9259743c662b205b1954cd2f577475cca4efb7c399d247adee341`

### Resposta final de GET /lote/{lote_id}/validacao

```
Status: validation_pending_approval
Apto para aprovacao: sim
Finalizado: true
Pode aprovar: true

Resumo:
- Linhas: 36
- Lancamentos: 432
- Sendaveis: 3
- Bloqueados: 0
- Avisos: 0
- Pendencias: 36 (todas IDENTIFICADOR_ISCHOLAR_PENDENTE — não bloqueantes)
- Erros: 0
```

### Dialog final no Google Sheets

```
Validacao concluida. O lote esta apto para aprovacao.

Lote: 1-xFbHa89XLIIxqcGbCtwzuB2lN4anFjt1cZjWdJzhAg/Notas
Snapshot: ed12bb6fbbf9259743c662b205b1954cd2f577475cca4efb7c399d247adee341
Status: validation_pending_approval
Apto para aprovacao: sim

Resumo:
- Linhas: 36
- Lancamentos: 432
- Sendaveis: 3
- Bloqueados: 0
- Avisos: 0
- Pendencias: 36
- Erros: 0
```

---

## Resultado do Gate

| Critério | Resultado |
|----------|-----------|
| Auth sem secret → 401 | ✅ |
| Auth com secret → 404 | ✅ |
| POST /webhook/notas → 202 | ✅ |
| job_id e snapshot_hash presentes | ✅ |
| Worker processou o job | ✅ |
| status: validation_pending_approval | ✅ |
| finalizado: true | ✅ |
| pode_aprovar: true | ✅ |
| Dialog fechou sem erro de rede | ✅ |

**GATE FECHADO ✅**

---

## O que fica aberto para sexta

- `Aprovar e Enviar` via Sheets com POST real no iScholar
- Notas aparecerem no diário via fluxo Sheets
- `snapshot_hash` coerente entre validação e aprovação

# Pendencias Administrativas — iScholar

Data de identificacao: 2026-04-04 (Onda B)
Pipeline: Madan -> iScholar ETL via Google Sheets

---

## Contexto

Na execucao do lote completo da turma 1A (91 lancamentos, 2 disciplinas, ~44 alunos),
o pipeline enviou 71 notas com sucesso e isolou 20 erros (10 alunos x 2 disciplinas).

Os erros NAO sao bugs do pipeline. Sao inconsistencias nos dados do iScholar
que impedem o envio para esses alunos especificos.

O pipeline isolou cada erro sem bloquear os demais envios.

---

## Grupo A — Matricula nao acessivel via API (4 alunos)

**Sintoma:** A API `/matricula/listar` retorna lista vazia para esses alunos,
mesmo com filtro `situacao=cursando`. A interface web do iScholar mostra o aluno
normalmente na turma 1A com situacao "CURSANDO".

**Mensagem do pipeline:** `[matricula_nao_encontrada] listar_matriculas: Nenhuma matricula retornada`

| Aluno | RA | Turma | Situacao (web) |
|-------|-----|-------|----------------|
| JOSE DIONIZIO PERTEL BORGES FILHO | 1234 | 1A | CURSANDO |
| JULIA TIRELO PEREIRA | 1276 | 1A | CURSANDO |
| MARINA COELHO ZANQUETTO | 1187 | 1A | CURSANDO |
| MIGUEL SCHINEIDER CASOTTI | 1260 | 1A | CURSANDO |

**Causa provavel:** matricula em estado intermediario no iScholar, ou token de
integracao sem permissao para acessar matriculas com situacao CURSANDO.

**Acao esperada do admin iScholar:**
1. Verificar o status real da matricula desses 4 alunos no painel administrativo
2. Confirmar se o token de integracao tem permissao para listar matriculas CURSANDO
3. Se necessario, ajustar a situacao da matricula ou as permissoes do token

---

## Grupo B — Grade curricular / sistema avaliativo divergente (6 alunos)

**Sintoma:** A API encontrou a matricula e resolveu o id_matricula, mas rejeitou
o envio da nota com erro de grade curricular ou sistema avaliativo.

**Mensagens do iScholar:**
- `Disciplina nao pertence a grade curricular da turma vinculada a matricula informada na requisicao.`
- `Divisao nao pertence ao sistema avaliativo da turma vinculada a matricula informada na requisicao.`

| Aluno | RA | Turma | Disciplinas rejeitadas |
|-------|-----|-------|----------------------|
| FIORELLA SALEZZE SULTI | 1200 | 1A | Arte, Ingles |
| ISABELA DE BARROS CABALEIRO E LIMA | 1193 | 1A | Arte, Ingles |
| LUIZA DE FARIA MENDONCA | 1247 | 1A | Arte, Ingles |
| LUIZA LIBORIO BARBOSA ALONSO | 1220 | 1A | Arte, Ingles |
| MARIA LUISA ARCHANJO SARTORIO SILVA | 1218 | 1A | Arte, Ingles |
| OTAVIO ZANAO HEMERLY | 1369 | 1A | Arte, Ingles |

**Causa provavel:** esses alunos estao matriculados em uma turma, trilha ou grade
curricular diferente dentro do 1A no iScholar. A grade vinculada a matricula deles
nao inclui as disciplinas Arte e/ou Ingles com o mesmo sistema avaliativo.

**Acao esperada do admin iScholar:**
1. Abrir o perfil de cada aluno e verificar a grade curricular vinculada a matricula
2. Comparar com a grade de um aluno que funcionou (ex: ALICE BARCELOS LINS, RA 1222)
3. Se a grade for diferente, identificar quais disciplinas e avaliacoes estao disponiveis
   para esses alunos — o lote precisa ser organizado separadamente

---

## Regra operacional

> **RA correto + UI mostra matricula + API retorna vazio ou rejeita disciplina =
> incidente externo. Nao reenviar indefinidamente. Registrar e encaminhar ao admin iScholar.**

O pipeline faz o correto nesses casos:
- isola o aluno com erro
- continua enviando os demais
- registra a auditoria completa no banco local

A resolucao depende do admin do iScholar, nao do desenvolvedor do pipeline.

---

## Status

- [ ] Grupo A resolvido pelo admin iScholar
- [ ] Grupo B resolvido pelo admin iScholar
- [ ] Reenvio bem-sucedido apos correcao

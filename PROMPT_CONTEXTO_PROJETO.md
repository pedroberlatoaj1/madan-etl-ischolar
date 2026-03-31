# Prompt de Contexto — Projeto Madan → iScholar

> **Instrução:** Cole este prompt inteiro no início de uma nova conversa com o Claude para restaurar o contexto completo do projeto. Não é necessário enviar arquivos adicionais — o Claude terá acesso ao código no mesmo diretório.

---

## Papel

Atue como engenheiro de software sênior e especialista em integrações de API (Python). Você é o arquiteto e desenvolvedor principal deste projeto. O operador é o Pedro.

## Projeto

Pipeline ETL operacional que transforma planilhas de notas da Escola Madan em lançamentos via API REST ao iScholar (sistema de gestão escolar). O fluxo é:

```
planilha Excel (template fixo)
  → transformação canônica (regras pedagógicas)
  → validação pré-envio
  → preflight técnico (API + mapas)
  → aprovação humana do lote
  → resolução de IDs no iScholar
  → envio POST item a item
  → auditoria por item
```

**Diretório raiz:** `C:\Users\PICHAU\Desktop\Claude Cenario 2`

## Arquitetura — Arquivos Principais

### Núcleo do pipeline
| Arquivo | Função |
|---------|--------|
| `cli_envio.py` | Orquestrador principal (entrypoint). 9 ETAPAs. Exit codes 0-5. |
| `madan_planilha_mapper.py` | Mapeamento de colunas e aliases da planilha |
| `avaliacao_rules.py` | Regras pedagógicas (AV1/AV2 = OBJ+DISC somados, recuperação, bloqueio 3ª série) |
| `transformador.py` | Transforma linha wide → lançamentos canônicos auditáveis |
| `validacao_pre_envio.py` | Validação pré-envio + cross-validation professor (avisos cosméticos) |
| `resolvedor_ids_ischolar.py` | Resolvedor híbrido de IDs: matrícula via API, disciplina/avaliação/professor via mapas JSON |
| `ischolar_client.py` | Client HTTP para API iScholar (7 endpoints, dataclasses tipadas) |
| `envio_lote.py` | Envio item a item com rastreabilidade |
| `aprovacao_lote.py` / `aprovacao_lote_store.py` / `lote_itens_store.py` | Controle de lote e aprovação (SQLite) |
| `envio_lote_audit_store.py` | Auditoria por item (SQLite) |

### Mapas DE-PARA (JSON)
| Arquivo | Conteúdo | Entradas |
|---------|----------|----------|
| `mapa_disciplinas.json` | nome_disciplina → id_disciplina | 35 aliases → 16 IDs reais |
| `mapa_avaliacoes.json` | componente + trimestre → id_avaliacao | 19 entradas (IDs 92-110) |
| `mapa_professores.json` | frente_professor → id_professor | 114 aliases → 25 IDs reais (10 aliases com ID=0) |

### Auxiliares
| Arquivo | Função |
|---------|--------|
| `professores_madan.py` | Registro hardcoded de 38 professores (do PDF oficial). Gera avisos cosméticos `PROFESSOR_NAO_ENCONTRADO_REGISTRO` — NÃO bloqueia envio. |
| `gerador_planilhas.py` | Geração de planilhas multi-abas por turma |
| `compilador_turma.py` | Compilação multi-abas → formato pipeline |
| `descobrir_ids_ischolar.py` | Script standalone de discovery (read-only, chama API real) |

## Contrato com a API iScholar

### Autenticação
- Header `X-Autorizacao`: token JWT (tipo integração, sem expiração)
- Header `X-Codigo-Escola`: `madan` (extraído do payload JWT — NÃO é `madan_homolog`)
- Base URL: `https://api.ischolar.app` (mesma para todos os ambientes)

### Endpoints integrados
| Endpoint | Método | Função |
|----------|--------|--------|
| `/aluno/busca` | GET | Busca aluno por RA (`numero_re`). Retorna `id_aluno` em `dados.informacoes_basicas.id_aluno` |
| `/matricula/listar` | GET | Lista matrículas de um `id_aluno`. Retorna `id_matricula` |
| `/notas/lanca_nota` | POST | Lançamento de nota (idempotente por contrato) |
| `/matricula/pega_alunos` | GET | Fallback: busca alunos de uma turma |
| `/diario/notas` | GET | Consulta notas — **BLOQUEADO para tokens de integração** |

### Payload de envio (POST `/notas/lanca_nota`)
```json
{
  "id_matricula": 1603,
  "id_disciplina": 1,
  "id_avaliacao": 92,
  "id_professor": 71,
  "valor": 5.0
}
```
- `id_professor` é **condicional** — necessário quando a mesma disciplina tem múltiplas frentes (A/B/C) com professores diferentes
- `valor` é a nota bruta (OBJ+DISC somados), confirmado pela pedagoga Marina

### Envelope padrão da API
```json
{"status": "sucesso", "mensagem": "...", "dados": ...}
```
A API retorna HTTP 200 mesmo em erros lógicos (ex: `{"status": "erro", "msg": "escolainvalida"}`). O client verifica o HTTP status, não o campo `status` do JSON.

## Sistema Avaliativo — Escola Madan

**ID do sistema avaliativo no iScholar:** 9 ("ENSINO MÉDIO 1ª E 2ª SÉRIE - 2026")

### Estrutura
- 3 trimestres: BIM1 (30pts), BIM2 (30pts), BIM3 (40pts) = 100pts
- 4 períodos de recuperação: REC 1ºTRI, REC 2ºTRI, REC 3ºTRI (não usado pela escola), REC FINAL
- 5 avaliações por trimestre: P1/AVA1, P2/AVA2, P3(NIVELAMENTO)/AVA3, SIMULADO/AVA4, CONCEITUAL/AVA5

### IDs de avaliação por trimestre
| Componente | 1ºTRI | 2ºTRI | 3ºTRI |
|-----------|-------|-------|-------|
| P1 (av1) | 92 | 97 | 102 |
| P2 (av2) | 93 | 98 | 103 |
| SIMULADO | 94 | 99 | 104 |
| P3 (av3) | 95 | 100 | 105 |
| CONCEITUAL | 96 | 101 | 106 |
| REC | 107 | 108 | 109 (não usado) |
| REC FINAL | 110 | | |

### Regra de notas (confirmada pela pedagoga Marina)
- No iScholar entra a **soma de OBJ + DISC** (não separado)
- Cada **frente** é lançada separadamente (Frente A, B, C são entradas distintas)
- Quem lança as notas são os funcionários da secretaria pedagógica
- Avaliações no iScholar aparecem como "P1 (SÓ DISC. NUMÉRICA)" — é o tipo do campo, não indica que só DISC vai

## Resolução de Matrículas — Heurísticas

O resolvedor (`resolvedor_ids_ischolar.py`) implementa 3 tentativas para resolver `id_matricula` quando há ambiguidade (aluno com múltiplas matrículas):

1. **Chamada direta**: `listar_matriculas(id_aluno=X)` — se retorna 1 resultado único, usa
2. **Filtro por situação**: `listar_matriculas(id_aluno=X, situacao="cursando")` — tenta desambiguar
3. **Heurística por status**: varre payload bruto procurando `status_matricula_diario == "MATRICULADO"` — escolhe esse

Auto-detecção de header no `cli_envio.py`: tenta `header=0`; se colunas obrigatórias não encontradas, tenta `header=1` (planilha Madan tem célula mesclada "DADOS OBRIGATÓRIOS" na linha 1).

## Template da Planilha

### Colunas obrigatórias
`Estudante`, `RA`, `Turma`, `Trimestre`, `Disciplina`, `Frente - Professor`

### Colunas de nota
`AV 1 (OBJ)`, `AV 1 (DISC)`, `AV 2 (OBJ)`, `AV 2 (DISC)`, `AV 3 (listas)`, `AV 3 (avaliação)`, `Simulado`, `Ponto extra`, `Recuperação`

### Colunas de conferência (opcionais)
`Nota sem a AV 3`, `Nota com a AV 3`, `Nota Final`

### Formato
- Notas entre 0 e 10, decimais com vírgula (formato brasileiro)
- Célula vazia = não se aplica (nunca zero)
- Uma linha por aluno × disciplina × frente
- Excel com header mesclado na linha 1 (auto-detectado)

## Estado Atual do Projeto (2026-03-31)

### Validado em homologação
- Dry-run passando (30/30 itens, 0 erros) ✅
- POST real bem-sucedido (30/30 enviados, 0 erros) ✅
- Notas confirmadas visualmente no diário do iScholar ✅
- Teste de idempotência aprovado (reenvio não duplica) ✅
- Heurística de matrícula ambígua funcionando (status=MATRICULADO) ✅
- Auto-detecção de header funcionando ✅
- 402 testes automatizados passando ✅
- Merge do worktree `goofy-kirch` para `main` concluído ✅
- `.env` do diretório principal corrigido (`madan`, não `madan_homolog`) ✅

### Pendente
- [ ] **Confirmar se `id_professor` é obrigatório** para diferenciar frentes da mesma disciplina (ex: Matemática A vs B). Teste em andamento com `planilha_teste_frente.xlsx` (3 frentes de Matemática para Alice RA 1222, trimestre 2).
- [ ] **Primeiro envio real de produção** com planilha preenchida pelos professores
- [ ] **Teste de volume** com turma inteira (~30-40 alunos)
- [ ] **Documentar procedimento operacional** para a secretaria pedagógica
- [ ] **Acordo de pagamento** com Marina (pedagógica) — pendente resposta

### Bugs conhecidos / limitações
- Avisos `PROFESSOR_NAO_ENCONTRADO_REGISTRO` são **cosméticos** (registro hardcoded em `professores_madan.py` espera nomes de professores; a planilha traz frentes como "Matematica A"). O mapa JSON resolve corretamente.
- `/diario/notas` bloqueado para tokens de integração — não afeta envio
- Mapa de professores configurado para **1ª série**; 2ª série tem professores diferentes para algumas frentes (Math, Bio, Geo)
- API retorna HTTP 200 mesmo em erros lógicos (`{"status": "erro", "msg": "escolainvalida"}`) — o client NÃO verifica o campo `status` do JSON, apenas o HTTP status code

### Alunos usados nos testes
- ALICE BARCELOS LINS (RA 1222) — id_aluno 1222, id_matricula 1603 (via heurística MATRICULADO)
- ALICE DE MEDEIROS GARCIA (RA 1239)
- ALICE DE SÁ FREITAS SOARES (RA 1437)

## Comandos Úteis

```bash
# Dry-run (sem POST real)
python cli_envio.py --planilha notas.xlsx --lote-id nome-lote --dry-run --aprovador "Pedro"

# Envio real
python cli_envio.py --planilha notas.xlsx --lote-id nome-lote --aprovador "Pedro"

# Testes
python -m pytest -q --tb=no

# Discovery de IDs
python descobrir_ids_ischolar.py --ra 1222 --verbose
```

## Configuração do .env

```env
ISCHOLAR_BASE_URL=https://api.ischolar.app
ISCHOLAR_API_TOKEN=<token JWT gerado no iScholar>
ISCHOLAR_CODIGO_ESCOLA=madan
```

**IMPORTANTE:** O código da escola é `madan` (extraído do campo `escola` no payload JWT), NÃO `madan_homolog`.

---

> **Para o Claude:** Com este contexto, você pode continuar o desenvolvimento do projeto. Os arquivos estão em `C:\Users\PICHAU\Desktop\Claude Cenario 2`. Leia os arquivos relevantes antes de fazer alterações. Sempre rode `python -m pytest -q --tb=no` após mudanças para garantir que os 402 testes continuam passando.

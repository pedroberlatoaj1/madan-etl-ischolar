# Pipeline Madan → iScholar

Integração operacional para receber uma planilha de notas do Madan, aplicar regras pedagógicas explícitas, transformar cada linha em lançamentos canônicos auditáveis, validar o lote, executar preflight técnico, exigir aprovação humana, resolver os IDs necessários no iScholar e enviar apenas o que foi aprovado — com auditoria por item.

**Fluxo resumido:**

```
template wide por turma → professor preenche → auto-detecção de formato
→ adaptador unpivot → transformação canônica → validação → preflight
→ aprovação → resolução de IDs → envio → auditoria
```

> **Fonte de verdade deste README**
>
> Este documento descreve o **fluxo oficial** do projeto.
> Componentes de monitoramento, webhook e worker legados podem continuar no
> repositório por compatibilidade ou transição, mas **não são a rota oficial principal**.
>
> Para operação do dia a dia, deploy e resposta a incidentes, consulte também
> `docs/OPERACAO.md`.
>
> O README não substitui:
> - o contrato efetivo do código;
> - a validação em homologação com o iScholar;
> - as decisões pedagógicas e operacionais do Madan ainda pendentes.

---

## 1. Objetivo

O objetivo do projeto **não** é apenas "chamar a API do iScholar".

O objetivo é construir um fluxo operacional completo, confiável e auditável que:

1. gera um template por turma com todas as disciplinas e frentes já estruturadas;
2. recebe o template preenchido pelos professores;
3. interpreta a planilha segundo regras pedagógicas explícitas;
4. transforma cada entrada em lançamentos canônicos auditáveis;
5. valida os lançamentos antes do envio;
6. executa preflight técnico antes da aprovação humana;
7. exige aprovação manual do lote;
8. resolve os IDs necessários no iScholar;
9. envia apenas os itens aprovados;
10. registra auditoria por item.

Em outras palavras: este projeto é um **pipeline operacional**, não um script isolado.

---

## 2. Fluxo Operacional

### 2.1 Papel da Coordenação — geração do template

#### Plano B — workbook anual multi-aba (modelo operacional atual)

O modelo operacional atual usa um único arquivo Excel (`madan_2026_anual.xlsx`) com **12 abas** — uma por turma × trimestre:

```
1A_T1  1A_T2  1A_T3
1B_T1  1B_T2  1B_T3
2A_T1  2A_T2  2A_T3
2B_T1  2B_T2  2B_T3
```

Cada aba segue o padrão `<Turma>_<Trimestre>` (ex: `2A_T1`, `1B_T2`). O nome da aba é a fonte de verdade para turma e trimestre — o operador navega até a aba correta antes de processar.

Cada aba contém:
- **4 colunas fixas** pré-preenchidas: `Estudante`, `RA`, `Turma`, `Trimestre`
- **1 coluna por (disciplina, frente, tipo de avaliação)** — geradas automaticamente a partir do registro de professores da turma

> O cabeçalho é derivado de `professores_madan.py`, garantindo que apenas as combinações disciplina-frente válidas para aquela turma apareçam como colunas.

#### Alternativa — planilha por turma e trimestre (legado)

```bash
python gerador_planilhas.py \
    --trimestre T1 \
    --ano 2026 \
    --alunos roster.csv \
    --output ./planilhas/
```

Gera um arquivo por turma (ex: `1A_T1_2026.xlsx`) com 1 aba única chamada `Notas`. Continua funcionando sem alteração.

### 2.2 Papel do Professor — preenchimento

O professor recebe a planilha de sua turma e preenche **apenas as colunas das suas disciplinas e frentes**. As demais colunas podem ficar em branco — o sistema ignora células vazias.

```
Estudante          | RA   | Turma | Trimestre | Física - Frente A - AV 1 Obj | Física - Frente A - AV 1 Disc | ...
Alice de Medeiros  | 1239 | 1A    | T1        | 5,5                           | 3,0                           | ...
Bruno Carvalho     | 1101 | 1A    | T1        | Faltou                        | Faltou                        | ...
Clara Fontes       | 1058 | 1A    | T1        |                               |                               | ...
```

**Convenções de preenchimento:**

| Situação | Como preencher | Comportamento |
|---|---|---|
| Nota normal | `7,5` ou `7.5` | Lançado normalmente |
| Ausência na prova | `Faltou` | Registrado com flag de ausência |
| Ainda não aplicado | *(célula vazia)* | Ignorado — não gera lançamento |
| OBJ + DISC acima de 10 | ex: `7 + 5 = 12` | Erro de validação — bloqueia o envio |

### 2.3 Papel do Pipeline — processamento

Ao receber a planilha preenchida, o CLI:

1. **Auto-detecta o formato** — wide novo ou semi-wide antigo;
2. Se wide novo: **valida e despivota** (1 linha por aluno → N linhas por aluno × disciplina × frente);
3. Se Plano B (nome de aba `<Turma>_<Trimestre>`): **injeta contexto de turma e trimestre** na linha antes da transformação (`aplicar_contexto_aba`);
4. **Desambiguação automática do 2º ano:** o adaptador usa o contexto de turma para qualificar a chave `Frente - Professor` com o professor correto (ex: `matematica a - daniel` para 2A vs `matematica a - luan` para 1A) — sem necessidade de alias manual;
5. Processa via pipeline canônico existente sem alteração alguma nas regras pedagógicas.

---

## 3. Arquitetura Técnica

```text
┌─────────────────────────────────────────────────────────────────────┐
│  GERAÇÃO DO TEMPLATE (gerador_planilhas.py)                         │
│  Plano B: 1 workbook anual · 12 abas (<Turma>_<Trimestre>)          │
│  Legado:  1 arquivo .xlsx por turma · 1 aba "Notas"                 │
│  cabeçalho derivado de professores_madan.py · formato wide          │
└────────────────────────────────┬────────────────────────────────────┘
                                 │  professor preenche
┌────────────────────────────────▼────────────────────────────────────┐
│  ENTRADA                                                            │
│  planilha wide (novo) OU planilha semi-wide (legado)                │
│  auto-detecção transparente via detectar_formato()                  │
└────────────────────────────────┬────────────────────────────────────┘
                                 │
             ┌───────────────────▼──────────────────────┐
             │  ADAPTER PATTERN (wide_format_adapter.py) │
             │  Unpivot: 1 linha → N linhas virtuais     │
             │  Regex extrai disciplina, frente, tipo    │
             │  Desambigua professor por turma (2º ano)  │
             │  Isola regras de negócio do transformador │
             └───────────────────┬──────────────────────┘
                                 │  formato canônico (semi-wide)
┌────────────────────────────────▼────────────────────────────────────┐
│  TRANSFORMAÇÃO CANÔNICA                                             │
│  madan_planilha_mapper.py · avaliacao_rules.py · transformador.py  │
│  validacao_pre_envio.py                                             │
│  → lançamentos canônicos auditáveis                                 │
└────────────────────────────────┬────────────────────────────────────┘
                                 │
┌────────────────────────────────▼────────────────────────────────────┐
│  PREFLIGHT TÉCNICO                                                  │
│  cli_envio.py · resolvedor_ids_ischolar.py · ischolar_client.py    │
│  valida credenciais, mapas e capacidade de resolver IDs             │
└────────────────────────────────┬────────────────────────────────────┘
                                 │
┌────────────────────────────────▼────────────────────────────────────┐
│  CONTROLE OPERACIONAL                                               │
│  aprovacao_lote.py · aprovacao_lote_store.py · lote_itens_store.py │
│  resumo do lote → elegibilidade → aprovação explícita              │
└────────────────────────────────┬────────────────────────────────────┘
                                 │
┌────────────────────────────────▼────────────────────────────────────┐
│  RESOLUÇÃO + ENVIO                                                  │
│  resolvedor_ids_ischolar.py · ischolar_client.py · envio_lote.py   │
│  resolve IDs exigidos → monta payload oficial → envia por item      │
└────────────────────────────────┬────────────────────────────────────┘
                                 │
┌────────────────────────────────▼────────────────────────────────────┐
│  AUDITORIA E SUPORTE OPERACIONAL                                    │
│  envio_lote_audit_store.py · alertas.py                             │
│  auditoria por item + rastreabilidade + alertas operacionais        │
└─────────────────────────────────────────────────────────────────────┘
```

### 3.1 Adapter Pattern — por que existe

O `wide_format_adapter.py` foi introduzido para absorver o novo formato de planilha **sem tocar nas regras pedagógicas**. Em vez de reescrever `transformador.py` (849 linhas) e `avaliacao_rules.py` (577 linhas), o adaptador converte o novo formato para o formato que o pipeline já conhece.

**Benefícios:**
- Isolamento total: nenhuma linha de regra de negócio foi alterada;
- Retrocompatibilidade: planilhas no formato antigo continuam funcionando sem qualquer modificação;
- Testabilidade: a camada de adaptação tem seus próprios 51 testes unitários;
- **471 testes passando com 0 falhas** após a refatoração completa.

### 3.2 Auto-detecção de formato

`detectar_formato(colunas)` em `wide_format_adapter.py` classifica automaticamente:

| Formato | Critério de detecção | Rota |
|---|---|---|
| `wide_novo` | Presença de colunas `Disciplina - Frente X - Tipo` (regex) | Valida + despivota antes do pipeline |
| `semi_wide_antigo` | Presença de colunas fixas `Disciplina` + `Frente - Professor` | Fluxo original sem alteração |

---

## 4. Estrutura do Formato Wide

### 4.1 Anatomia de uma coluna dinâmica

```
Matemática  -  Frente A  -  AV 1 Obj
│              │             │
│              │             └─ Tipo de avaliação
│              └─────────────── Frente → identifica o professor via mapa_professores.json
└────────────────────────────── Disciplina → normalizada para slug canônico
```

**Regex de extração** (em `wide_format_adapter.py`):

```python
REGEX_COLUNA_DINAMICA = re.compile(
    r"^(.+?)\s*-\s*(Frente\s+\S+)\s*-\s*(.+)$",
    re.IGNORECASE,
)
```

### 4.2 Exemplo de cabeçalho completo

```
Estudante | RA | Turma | Trimestre
  Matemática - Frente Única - AV 1 Obj
  Matemática - Frente Única - AV 1 Disc
  Matemática - Frente Única - AV 2 Obj
  Matemática - Frente Única - AV 2 Disc
  Matemática - Frente Única - AV 3 Listas
  Matemática - Frente Única - AV 3 Avaliacao
  Matemática - Frente Única - Simulado
  Matemática - Frente Única - Ponto Extra
  Matemática - Frente Única - Recuperação
  Física - Frente A - AV 1 Obj
  Física - Frente A - AV 1 Disc
  ...
  Física - Frente B - AV 1 Obj
  ...
  Gramática - Frente Única - AV 1 Obj
  ...
```

> Para a turma **1A**, o gerador produz 12 grupos disciplina-frente × 9 tipos de avaliação = **112 colunas** (incluindo as 4 fixas).

### 4.3 Tipos de avaliação suportados

| Coluna wide | Coluna canônica (pipeline interno) |
|---|---|
| `AV 1 Obj` | `AV 1 (OBJ)` |
| `AV 1 Disc` | `AV 1 (DISC)` |
| `AV 2 Obj` | `AV 2 (OBJ)` |
| `AV 2 Disc` | `AV 2 (DISC)` |
| `AV 3 Listas` | `AV 3 (listas)` |
| `AV 3 Avaliacao` | `AV 3 (avaliação)` |
| `Simulado` | `Simulado` |
| `Ponto Extra` | `Ponto extra` |
| `Recuperação` | `Recuperação` |

### 4.4 Regras de preenchimento

- Notas entre `0` e `10`;
- `AV 1 (OBJ) + AV 1 (DISC) ≤ 10` — validado antes do envio;
- Célula vazia = não se aplica (nunca lançado como zero);
- `Faltou` = ausência registrada com flag;
- Decimais com vírgula ou ponto são aceitos;
- RA é obrigatório para resolução de matrícula no iScholar.

---

## 5. Componentes Principais

### 5.1 Geração de templates

- **`gerador_planilhas.py`** — gera planilhas Excel no formato wide por turma.
  Funções principais:
  - `descobrir_grupos_wide(serie, turma_letra)` → lista de `(disciplina, frente)` válidos para a turma
  - `construir_cabecalho_wide(grupos)` → lista de nomes de coluna compatíveis com o adapter
  - `gerar_planilha_turma(turma, trimestre, ano, alunos, output_dir)` → gera 1 arquivo `.xlsx`
  - `gerar_todas_planilhas(trimestre, ano, alunos, output_dir)` → itera todas as turmas do roster
  - `gerar_workbook_anual(ano, alunos_por_turma, output_path)` → gera 1 workbook anual com 12 abas trimestrais

### 5.2 Adaptador de formato

- **`wide_format_adapter.py`** — Adapter Pattern entre formato wide e pipeline canônico.
  Funções principais:
  - `detectar_formato(colunas)` → `"wide_novo"` | `"semi_wide_antigo"`
  - `validar_colunas_wide_novo(colunas)` → lista de problemas (vazia se ok)
  - `despivotar_dataframe(df)` → DataFrame no formato semi-wide antigo
  - `parsear_coluna_dinamica(nome)` → `ColunaDinamica` com `disciplina`, `frente`, `tipo_avaliacao`
  - `construir_frente_professor(disciplina, frente)` → chave base compatível com `mapa_professores.json`
  - `_qualificar_chave_com_professor(base_key, disciplina, serie, letra)` → qualifica a chave com o professor da turma quando há ambiguidade entre anos (ex: Matemática A é Daniel em 2A e Luan em 1A)

### 5.3 Entrada e normalização

- **`madan_planilha_mapper.py`** — mapeia aliases, colunas obrigatórias e contexto canônico da linha.

### 5.4 Regras pedagógicas

- **`avaliacao_rules.py`** — centraliza regras explícitas de cálculo e interpretação pedagógica.

### 5.5 Transformação

- **`transformador.py`** — converte linha semi-wide em lançamentos canônicos auditáveis.

### 5.6 Validação pré-envio

- **`validacao_pre_envio.py`** — qualifica os lançamentos antes da aprovação e do envio.

### 5.7 Compilador de turma (legado)

- **`compilador_turma.py`** — compila planilhas multi-abas (formato antigo) para 1 linha por aluno × disciplina. Mantido para retrocompatibilidade com a flag `--turma-dir`.

### 5.8 Controle de lote

- **`aprovacao_lote.py`** / **`aprovacao_lote_store.py`** / **`lote_itens_store.py`**

  Responsáveis por: resumo do lote, elegibilidade, aprovação explícita e persistência dos itens aprovados.

### 5.9 Integração com iScholar

- **`resolvedor_ids_ischolar.py`** / **`ischolar_client.py`** / **`envio_lote.py`**

  Responsáveis por: resolver `id_matricula`, `id_disciplina`, `id_avaliacao`, `id_professor`; montar payload oficial; enviar por item; registrar falhas parciais sem perder rastreabilidade.

### 5.10 Discovery e autopreenchimento de mapas

- **`descobrir_ids_ischolar.py`** — script standalone de discovery, read-only, que chama a API real para descobrir shapes e IDs.

### 5.11 Auditoria e observabilidade

- **`envio_lote_audit_store.py`** — persiste auditoria do resultado por item.
- **`alertas.py`** / **`logger.py`** — logging e alertas operacionais.

---

## 6. CLI Oficial (`cli_envio.py`)

O `cli_envio.py` continua sendo a rota oficial de contingencia no terminal, mas a
orquestracao do pipeline agora vive no runner reutilizavel usado tambem pelo
backend HTTP e pelo worker.

### 6.1 Fluxo interno

| Etapa | O que faz |
|---|---|
| **ETAPA 1** | Carrega planilha (`.xlsx`, `.xls`, `.csv`). Tenta `header=0`; fallback para `header=1` se colunas não forem encontradas. |
| **ETAPA 2** | **Auto-detecção de formato.** Se wide novo → valida + despivota via adapter. Se semi-wide → validação de template original. |
| **ETAPA 3/4** | Gera lançamentos canônicos + validação pré-envio por linha. |
| **ETAPA 5** | Gera e exibe resumo do lote. |
| **ETAPA 6** | Preflight técnico (inicializa cliente, carrega mapas, instancia resolvedor). |
| **ETAPA 6b** | Cria stores SQLite e estado inicial do lote. |
| **ETAPA 7** | Aprovação explícita (automática via `--aprovador` ou interativa). |
| **ETAPA 8** | Envio (dry-run ou real) + auditoria por item. |
| **ETAPA 9** | Resultado final. |

### 6.2 Exemplos de uso

```bash
# Plano B — workbook anual, especificar a aba com --aba:
python cli_envio.py --planilha madan_2026_anual.xlsx --aba 2A_T1 --lote-id 2026-2a-t1 --dry-run
python cli_envio.py --planilha madan_2026_anual.xlsx --aba 2A_T1 --lote-id 2026-2a-t1 --aprovador "Coordenacao"

# Planilha por turma (legado):
python cli_envio.py --planilha planilhas/1A_T1_2026.xlsx --lote-id t1-1A-2026 --dry-run

# Envio real com aprovação automática:
python cli_envio.py --planilha planilhas/1A_T1_2026.xlsx --lote-id t1-1A-2026 --aprovador "Pedro"

# Envio real com confirmação interativa no terminal:
python cli_envio.py --planilha planilhas/1A_T1_2026.xlsx --lote-id t1-1A-2026

# Batch via diretório (formato antigo multi-abas, compilado automaticamente):
python cli_envio.py --turma-dir planilhas/ --lote-id t1-2026 --dry-run

# Mapas e DBs em caminhos explícitos:
python cli_envio.py \
    --planilha notas.xlsx \
    --lote-id t1-1A-2026 \
    --dry-run \
    --mapa-disciplinas mapas/disciplinas.json \
    --mapa-avaliacoes  mapas/avaliacoes.json  \
    --mapa-professores mapas/professores.json \
    --db-aprovacoes    aprovacoes.db          \
    --db-itens         itens.db               \
    --db-audit         audit.db
```

### 6.3 Argumentos disponíveis

| Argumento | Obrigatório | Descrição |
|---|---|---|
| `--planilha` | Sim¹ | Caminho para o Excel/CSV de notas |
| `--aba` | Não² | Nome da aba a processar no workbook anual (ex: `2A_T1`). Obrigatório para Plano B. |
| `--turma-dir` | Sim¹ | Diretório com planilhas multi-abas (formato legado) |
| `--lote-id` | Sim | Identificador único do lote (ex: `t1-1A-2026`) |
| `--dry-run` | Não | Valida e monta payloads sem POST real |
| `--aprovador` | Não | Nome do aprovador (pula prompt interativo) |
| `--mapa-disciplinas` | Não | Padrão: `mapa_disciplinas.json` |
| `--mapa-avaliacoes` | Não | Padrão: `mapa_avaliacoes.json` |
| `--mapa-professores` | Não | Padrão: `mapa_professores.json` |
| `--professor-obrigatorio` / `--no-professor-obrigatorio` | Não | Bloqueia lançamentos sem `id_professor` (default: ativado) |
| `--db-aprovacoes` | Não | Padrão: `aprovacoes_lote.db` |
| `--db-itens` | Não | Padrão: `lote_itens.db` |
| `--db-audit` | Não | Padrão: `envio_lote_audit.db` |

¹ `--planilha` e `--turma-dir` são mutuamente exclusivos; exatamente um dos dois deve ser informado.
² `--aba` é necessário quando `--planilha` aponta para o workbook anual (Plano B). Dispensável para planilhas com aba única.

### 6.4 Exit codes

| Código | Significado |
|---|---|
| `0` | Sucesso |
| `1` | Erro operacional inesperado |
| `2` | Problema de entrada / planilha / template |
| `3` | Lote não elegível / pré-condição violada |
| `4` | Cancelamento do operador |
| `5` | Configuração / mapas / credenciais / preflight técnico |

---

## 7. Gerador de Planilhas (`gerador_planilhas.py`)

```bash
# Gerar workbook anual do Plano B:
python gerador_planilhas.py \
    --anual \
    --ano 2026 \
    --alunos roster.csv \
    --output ./planilhas/

# Saída esperada:
# Roster carregado: 120 alunos
# Workbook anual gerado:
#   planilhas/madan_2026_anual.xlsx

# Gerar planilhas para todas as turmas do roster:
python gerador_planilhas.py \
    --trimestre T1 \
    --ano 2026 \
    --alunos roster.csv \
    --output ./planilhas/

# Saída esperada:
# Roster carregado: 120 alunos
# 6 planilha(s) gerada(s):
#   planilhas/1A_T1_2026.xlsx
#   planilhas/1B_T1_2026.xlsx
#   ...
```

**Formato do CSV de roster** (`--alunos`):

```csv
Nome,RA,Turma
Alice de Medeiros,1239,1A
Bruno Carvalho,1101,1A
Clara Fontes,1058,1B
```

Colunas aceitas (case-insensitive): `Nome` / `Estudante` / `Aluno`, `RA` / `Registro_Aluno`, `Turma` / `Sala` / `Classe`.

---

## 8. Dry-run

O dry-run:

- não faz POST real ao iScholar;
- valida planilha, adaptação de formato e lote completo;
- passa pelo fluxo de resolução e preflight com a configuração atual;
- pode falhar por credencial, mapa ou resolução de IDs mesmo sem POST real.

**Dry-run não deve ser interpretado como modo totalmente offline.**

---

## 9. Contrato com o iScholar

### 9.1 Endpoints integrados

#### Resolução de IDs

| Endpoint | Método | Função |
|---|---|---|
| `/aluno/busca` | GET | Busca aluno por RA (`numero_re`). Retorna `id_aluno`. |
| `/matricula/listar` | GET | Lista matrículas de um `id_aluno`. Retorna `id_matricula`. |
| `/matricula/pega_alunos` | GET | **Fallback:** retorna `id_aluno`, `id_matricula` e `numero_re` para todos os alunos da turma. |

#### Discovery e autopreenchimento de mapas

| Endpoint | Método | Função |
|---|---|---|
| `/disciplinas` | GET | Lista todas as disciplinas cadastradas (id, nome, abreviação). |
| `/funcionarios/professores` | GET | Lista todos os professores cadastrados (id, nome). |

#### Auditoria

| Endpoint | Método | Função |
|---|---|---|
| `/diario/notas` | GET | Consulta notas já lançadas para uma matrícula (reconciliação). |

#### Lançamento

| Endpoint | Método | Função |
|---|---|---|
| `/notas/lanca_nota` | POST | Lançamento de nota. Idempotente por contrato. |

### 9.2 Envelope padrão da API

```json
{
  "status": "sucesso",
  "mensagem": "...",
  "dados": { ... }
}
```

O campo `dados` contém o payload real. O sistema extrai automaticamente em todos os caminhos de resposta.

> **Nota:** A API retorna IDs como strings (ex: `"id_matricula": "97"`). O sistema converte automaticamente via `_coerce_int_strict()` em todos os caminhos de extração.

### 9.3 Payload oficial de lançamento

POST `/notas/lanca_nota`:

| Campo | Tipo | Obrigatoriedade |
|---|---|---|
| `id_matricula` | `int` | Obrigatório |
| `id_disciplina` | `int` | Obrigatório |
| `id_avaliacao` | `int` | Obrigatório |
| `id_professor` | `int` | Condicional (depende de `--professor-obrigatorio`) |
| `valor` | `float` | Obrigatório — nota bruta, não ponderada |

### 9.4 Semântica confirmada

- `id_matricula` pode variar por turma/ano/série;
- o endpoint de lançamento é idempotente;
- a autenticação usa `X-Autorizacao` + `X-Codigo-Escola`;
- URL da API: `https://api.ischolar.app` (mesma para homologação e produção);
- diferença entre ambientes: apenas o valor de `X-Codigo-Escola`.

### 9.5 Estado de homologação

- `id_professor` obrigatório confirmado na prática — `professor_obrigatorio=True` é o default;
- POST real validado com Arte, Inglês, Física A e Gramática (Língua Portuguesa, id=29);
- Pendente: validação de cenários de falha (RA inválido, disciplina sem mapa).

---

## 10. Estratégia de Resolução de IDs

O resolvedor (`ResolvedorIDsHibrido`) é conservador e fail-closed.

### 10.1 `id_matricula` — via API oficial

```text
buscar_aluno(ra="12345")
    │
    ├─ id_aluno extraído? ──► listar_matriculas(id_aluno) ──► id_matricula
    │
    └─ id_aluno NÃO extraído? ──► pega_alunos(id_turma)
                                      │
                                      └─ encontrar_por_ra("12345")
                                            ├─ 1 match ──► id_aluno + id_matricula
                                            └─ 0 ou N matches ──► BLOQUEIO
```

### 10.2 `id_disciplina` — via DE-PARA local

Resolvido por `mapa_disciplinas.json`. Autopreenchimento via `GET /disciplinas`.

### 10.3 `id_avaliacao` — via DE-PARA local

Resolvido por `mapa_avaliacoes.json`. IDs coletados manualmente da interface web do iScholar (sistema avaliativo ID=9, `BIM1`–`BIM7`).

> **Limitação:** O endpoint `GET /diario/notas` está **bloqueado para tokens de integração**. IDs de avaliação não podem ser obtidos automaticamente.

### 10.4 `id_professor` — via DE-PARA local

Resolvido por `mapa_professores.json` (com chaves base e, no Plano B, também chaves qualificadas como `"matematica a - daniel"`). Autopreenchimento via `GET /funcionarios/professores`.

**A chave de lookup é construída pelo adapter:**
```python
construir_frente_professor("Matemática", "Frente A")  # → "matematica a"
construir_frente_professor("Gramática",  "Frente Única")  # → "gramatica"
```

Quando o adapter consegue desambiguar a turma, ele qualifica essa chave com o professor esperado da série/turma. O resolvedor faz lookup direto no `mapa_professores.json`; ele não faz fallback automático da chave qualificada para a chave base. Por isso, as chaves qualificadas exigidas pelo Plano B precisam existir no mapa.

### 10.5 Postura do resolvedor

**Fail-closed sem exceções:**
matrícula ambígua · disciplina sem mapa · avaliação sem mapa · professor obrigatório sem mapa · identificador insuficiente do aluno → todos bloqueiam com rastreabilidade.

---

## 11. Dataclasses de Resultado da API

| Dataclass | Endpoint | Campos relevantes |
|---|---|---|
| `ResultadoBuscaAluno` | GET `/aluno/busca` | `sucesso`, `dados`, `erro_categoria` |
| `ResultadoListagemMatriculas` | GET `/matricula/listar` | `sucesso`, `id_matricula_resolvido`, `rastreabilidade` |
| `ResultadoListagemNotas` | GET `/diario/notas` | `sucesso`, `dados` |
| `ResultadoLancamentoNota` | POST `/notas/lanca_nota` | `sucesso`, `idempotente`, `dry_run`, `payload` |
| `ResultadoListagemDisciplinas` | GET `/disciplinas` | `sucesso`, `disciplinas` |
| `ResultadoListagemProfessores` | GET `/funcionarios/professores` | `sucesso`, `professores` |
| `ResultadoPegaAlunos` | GET `/matricula/pega_alunos` | `sucesso`, `alunos` |

Todas seguem o padrão: `sucesso: bool`, `status_code`, `transitorio: bool`, `erro_categoria`, `dados`.

---

## 12. Discovery de IDs (`descobrir_ids_ischolar.py`)

Script standalone, read-only. Não modifica dados.

```bash
# Discovery básico:
python descobrir_ids_ischolar.py --ra <RA_TESTE>

# Com respostas brutas da API:
python descobrir_ids_ischolar.py --ra <RA_TESTE> --verbose

# Gerar esqueletos dos mapas JSON:
python descobrir_ids_ischolar.py --ra <RA_TESTE> --gerar-mapas
```

| Etapa | Endpoint |
|---|---|
| 1. Conectividade | Headers de autenticação |
| 2. Buscar aluno por RA | GET `/aluno/busca` |
| 3. Listar matrículas | GET `/matricula/listar` |
| 4. Listar notas existentes | GET `/diario/notas` |
| 5. Gerar esqueletos (com `--gerar-mapas`) | `GET /disciplinas`, `GET /funcionarios/professores` |

---

## 13. Configuração do Ambiente

### 13.1 Arquivo `.env`

```bash
cp .env.example .env
# Editar .env com as credenciais reais
```

| Variável | Obrigatória | Descrição |
|---|---|---|
| `ISCHOLAR_BASE_URL` | Sim | `https://api.ischolar.app` |
| `ISCHOLAR_API_TOKEN` | Sim | Token gerado na interface do iScholar |
| `ISCHOLAR_CODIGO_ESCOLA` | Sim | Valor do campo `"escola"` no payload JWT do token |

### 13.2 Ambientes

- **Madan:** `ISCHOLAR_CODIGO_ESCOLA=madan` (extraído do JWT do token de integração);
- A `ISCHOLAR_BASE_URL` é a mesma para qualquer ambiente;
- Interface web: `https://madan.ischolar.com.br/`.

> **Atenção:** Use sempre o valor do JWT, não assuma `madan_homolog` ou outro sufixo.

---

## 14. Estado Atual do Projeto

### 14.1 Concluído

- **Formato wide (novo):** gerador, adapter, auto-detecção e despivotamento;
- **Retrocompatibilidade total:** planilhas no formato semi-wide antigo continuam funcionando;
- **530 testes automatizados passando** (0 falhas);
- Template wide gerado com cabeçalho derivado de `professores_madan.py`;
- Adapter Pattern com isolamento total das regras pedagógicas;
- `mapa_disciplinas.json`: IDs reais coletados da interface web do iScholar (`"gramatica"` e `"lingua portuguesa"` mapeados para id=29 — LÍNGUA PORTUGUESA);
- `mapa_avaliacoes.json`: 19 IDs reais (92–110) do sistema avaliativo ID=9 "ENSINO MÉDIO (1ª E 2ª SÉRIE) - 2026";
- `mapa_professores.json`: IDs reais com aliases por frente (`"matematica a"`, `"fisica b"`, `"arte"`, etc.);
- Dry-run e envio real passando com sucesso em todas as 9 etapas;
- **Homologação assistida avançada:** POST real validado com Arte, Inglês, Física A (multi-frente) e Gramática/Língua Portuguesa — notas apareceram corretamente no diário do iScholar em todas as execuções;
- Idempotência confirmada — reenvio bloqueado por `LoteJaAprovadoError` antes de qualquer POST;
- `id_professor` obrigatório por default (`professor_obrigatorio=True`) — confirmado na prática durante piloto;
- AV1/AV2 consolidados por soma simples (OBJ + DISC ≤ 10), validado pelo pedagógico;
- 3ª série bloqueada explicitamente com motivo claro;
- Regras de recuperação trimestral (T1/T2) e final implementadas;
- Rendimento anual por média ponderada 30-30-40 implementado;
- 37 professores registrados em `professores_madan.py` conforme PDF oficial;
- Cross-validation professor × disciplina × turma com aviso não-bloqueante;
- Stores SQLite com `:memory:` para testes, arquivo para produção;
- Heurística de matrícula por `status_matricula_diario == "MATRICULADO"`.

### 14.2 Pendente

- Validação de falhas esperadas (RA inválido, disciplina sem mapa) antes de lote completo;
- Coleta manual dos IDs de avaliação para T2 e T3 (via interface web do iScholar);
- Scripts de startup (`iniciar_servicos.bat`) e documentação de reinício após reboot;
- Primeiro envio de lote completo em produção acompanhado pelo desenvolvedor.

---

## 15. Semântica Oficial do Domínio

- A planilha wide por turma é a única entrada oficial para o fluxo novo;
- O lançamento canônico é a verdade interna do sistema;
- `valor_ponderado` é artefato interno de validação e auditoria — nunca é enviado;
- O valor enviado ao iScholar deve ser a **nota bruta**;
- `sendavel=True` significa item final pronto para virar POST oficial;
- Tudo que orbita conceitos como `consultar_notas`, `criar_nota`, `sync_notas_idempotente`, `identificacao`, `tipo`, `data_lancamento` deve ser tratado como legado.

---

## 16. Operacao via Google Sheets

O projeto agora suporta operacao assíncrona via Google Sheets, sem depender de terminal para o fluxo normal do operador.

Fluxo resumido:

1. O Apps Script lê a aba `Notas` e chama `POST /webhook/notas`.
2. O backend cria um job `google_sheets_validation`.
3. O worker executa o pipeline oficial e persiste o resultado da validação.
4. O operador revisa o resumo e aprova no Google Sheets.
5. O Apps Script chama `POST /lote/{lote_id}/aprovar`.
6. O backend cria um job `approval_and_send`.
7. O worker executa aprovação/envio e persiste o resultado consolidado final.
8. O Apps Script consulta `GET /lote/{lote_id}/validacao` e `GET /lote/{lote_id}/resultado-envio` durante o polling.

O Google Sheets permanece cliente fino:
- coleta dados;
- chama endpoints;
- faz polling;
- mostra dialogs;
- guarda `lote_id`, `snapshot_hash` e os `job_id` mais recentes localmente.

O backend continua dono do processo:
- valida payload, autenticacao, anti-replay, limites e stale check;
- cria jobs assincronos;
- persiste validacao e resultado consolidado do envio;
- expoe o estado consultavel para polling do operador.

Consulte o guia operacional em `operacao_google_sheets.md` e o runbook
operacional em `docs/OPERACAO.md`.

## 17. Contingencia

O CLI continua suportado como rota de contingência operacional e usa o mesmo runner oficial do backend:

```bash
.\.venv\Scripts\python.exe cli_envio.py --planilha notas.xlsx --lote-id lote-manual --dry-run
.\.venv\Scripts\python.exe cli_envio.py --planilha notas.xlsx --lote-id lote-manual --aprovador "Coordenacao"
```

## 18. Deploy

Na VPS, o deploy deve passar sempre por `deploy.sh` para garantir o fluxo completo no mesmo comando:

- `git fetch` com revisao dos commits que vao entrar;
- confirmacao explicita do operador;
- `git pull --ff-only`;
- limpeza de `__pycache__` e `*.pyc`;
- restart de `madan-webhook` e `madan-worker`;
- validacao final do import de `validacao_pre_envio`.

### 18.1 Comandos

1. Local: `git push`
2. VPS: `ssh madan@vps` e depois `madan-deploy`
3. Verificar: `madan-status`

### 18.2 Aliases sugeridos para `~/.bashrc`

```bash
alias madan-deploy='/opt/madan-etl/app/deploy.sh'
alias madan-status='systemctl status madan-webhook madan-worker --no-pager | head -20'
alias madan-logs='sudo journalctl -u madan-worker -u madan-webhook -f'
```

## 19. Disaster Recovery

O historico operacional da VPS fica em `/opt/madan-etl/data` e precisa de backup
diario. Isso inclui:

- `jobs.sqlite3`
- `validacoes_lote.db`
- `aprovacoes_lote.db`
- `lote_itens.db`
- `envio_lote_audit.db`
- `resultados_envio_lote.db`
- `snapshots/`
- mapas `mapa*.json` em `/opt/madan-etl/app`

O script oficial de backup fica em `/opt/madan-etl/scripts/backup.sh` e usa:

- `sqlite3 .backup` para gerar copias consistentes dos bancos SQLite abertos
- `tar.gz` com nome `madan-backup-YYYY-MM-DD-HHMMSS.tar.gz`
- destino local `/opt/madan-etl/backups/`
- upload remoto via `rclone` para Google Drive
- retencao simples de 14 backups locais e 14 remotos

### 19.1 Setup unico na VPS

Como o cron roda em `root` (`sudo crontab -e`), configure o `rclone` tambem com `sudo`:

```bash
sudo apt-get update
sudo apt-get install -y rclone sqlite3 mailutils
sudo rclone config
sudo rclone mkdir gdrive:madan-etl-backups
sudo mkdir -p /opt/madan-etl/scripts /opt/madan-etl/backups
sudo touch /var/log/madan-backup.log
```

Recomendacao:

- criar o remote com nome `gdrive`
- usar a pasta remota `gdrive:madan-etl-backups`
- manter um MTA funcional para que `mail` ou `sendmail` consigam avisar falhas por email

### 19.2 Cron diario

Adicione no `sudo crontab -e`:

```cron
MAILTO=pedroberlatoaj1@gmail.com
0 3 * * * /opt/madan-etl/scripts/backup.sh >> /var/log/madan-backup.log 2>&1
```

Observacoes:

- o log fica em `/var/log/madan-backup.log`
- o script tenta enviar notificacao por email em falha usando `mail` ou `sendmail`
- falha de upload remoto nao apaga o `.tar.gz` local ja criado

### 19.3 Restore em producao

O restore oficial fica em `/opt/madan-etl/scripts/restore.sh` e:

- exige um argumento com o caminho do `.tar.gz`
- pede confirmacao explicita `yes`
- para `madan-webhook` e `madan-worker`
- restaura `/opt/madan-etl/data`
- restaura os mapas `mapa*.json` em `/opt/madan-etl/app`
- sobe os servicos novamente

Exemplo:

```bash
sudo /opt/madan-etl/scripts/restore.sh /opt/madan-etl/backups/madan-backup-2026-04-19-030000.tar.gz
```

### 19.4 Teste trimestral de restore

Uma vez por trimestre, valide um backup sem tocar no ambiente em producao:

```bash
LATEST_BACKUP="$(ls -1 /opt/madan-etl/backups/madan-backup-*.tar.gz | tail -n 1)"
TMP_RESTORE_DIR="/tmp/madan-restore-check"
rm -rf "$TMP_RESTORE_DIR"
mkdir -p "$TMP_RESTORE_DIR"
tar -xzf "$LATEST_BACKUP" -C "$TMP_RESTORE_DIR"
sqlite3 "$TMP_RESTORE_DIR/data/jobs.sqlite3" "SELECT COUNT(*) AS total_jobs FROM jobs;"
find "$TMP_RESTORE_DIR/data/snapshots" -maxdepth 1 -type f | wc -l
```

Registrar no teste:

- nome do arquivo restaurado
- contagem de jobs em `jobs.sqlite3`
- contagem de snapshots restaurados
- hora do teste e responsavel

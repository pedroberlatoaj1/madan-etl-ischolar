# Pipeline Madan → iScholar

Integração operacional para receber uma planilha fixa de notas do Madan, aplicar regras pedagógicas explícitas, transformar cada linha em lançamentos canônicos auditáveis, validar o lote, executar um preflight técnico, exigir aprovação humana, resolver os IDs necessários no iScholar e enviar apenas o que foi aprovado, com auditoria por item.

**Fluxo oficial novo:**

**planilha fixa → transformação canônica → validação → preflight técnico → lote → aprovação → resolução de IDs → envio → auditoria**

> **Fonte de verdade deste README**
>
> Este documento descreve o **fluxo oficial novo** do projeto.
>
> Componentes antigos de monitoramento, webhook e worker podem continuar no repositório por compatibilidade, ingestão auxiliar ou transição, mas **não devem ser tratados como a rota oficial principal**.
>
> O README não substitui:
> - o contrato efetivo do código;
> - a validação em homologação com o iScholar;
> - as decisões pedagógicas e operacionais do Madan ainda pendentes.

---

## 1. Objetivo

O objetivo do projeto **não** é apenas "chamar a API do iScholar".

O objetivo é construir um fluxo operacional completo, confiável e auditável que:

1. recebe uma planilha oficial de notas;
2. interpreta essa planilha segundo regras pedagógicas explícitas;
3. transforma cada linha em lançamentos canônicos auditáveis;
4. valida os lançamentos antes do envio;
5. executa um preflight técnico antes da aprovação humana;
6. exige aprovação manual do lote;
7. resolve os IDs necessários no iScholar;
8. envia apenas os itens aprovados;
9. registra auditoria por item.

Em outras palavras: este projeto é um **pipeline operacional**, não um script isolado.

---

## 2. Arquitetura oficial

```text
┌──────────────────────────────────────────────────────────────────────┐
│  ENTRADA OFICIAL                                                    │
│  planilha Excel/CSV fixa do Madan                                   │
│  template oficial com colunas obrigatórias, notas e conferência     │
└──────────────────────────────┬───────────────────────────────────────┘
                               │
┌──────────────────────────────▼───────────────────────────────────────┐
│  TRANSFORMAÇÃO CANÔNICA                                              │
│  madan_planilha_mapper.py                                            │
│  avaliacao_rules.py                                                  │
│  transformador.py                                                    │
│  validacao_pre_envio.py                                              │
│                                                                      │
│  Resultado: lançamentos canônicos auditáveis                         │
│  com RA, disciplina, avaliação, professor (quando aplicável),        │
│  nota bruta de envio e artefatos internos de auditoria               │
└──────────────────────────────┬───────────────────────────────────────┘
                               │
┌──────────────────────────────▼───────────────────────────────────────┐
│  PREFLIGHT TÉCNICO                                                   │
│  cli_envio.py                                                        │
│  resolvedor_ids_ischolar.py                                          │
│  ischolar_client.py                                                  │
│                                                                      │
│  valida credenciais, mapas e capacidade de resolver IDs              │
│  antes da persistência inicial do lote e da aprovação humana         │
└──────────────────────────────┬───────────────────────────────────────┘
                               │
┌──────────────────────────────▼───────────────────────────────────────┐
│  CONTROLE OPERACIONAL                                                │
│  aprovacao_lote.py                                                   │
│  aprovacao_lote_store.py                                             │
│  lote_itens_store.py                                                 │
│                                                                      │
│  resumo do lote → elegibilidade → aprovação explícita                │
└──────────────────────────────┬───────────────────────────────────────┘
                               │
┌──────────────────────────────▼───────────────────────────────────────┐
│  RESOLUÇÃO + ENVIO                                                   │
│  resolvedor_ids_ischolar.py                                          │
│  ischolar_client.py                                                  │
│  envio_lote.py                                                       │
│                                                                      │
│  resolve IDs exigidos → monta payload oficial → envia por item       │
└──────────────────────────────┬───────────────────────────────────────┘
                               │
┌──────────────────────────────▼───────────────────────────────────────┐
│  SAÍDA, AUDITORIA E SUPORTE OPERACIONAL                              │
│  envio_lote_audit_store.py                                           │
│  alertas.py                                                          │
│                                                                      │
│  auditoria por item + rastreabilidade + alertas operacionais         │
└──────────────────────────────────────────────────────────────────────┘
```

---

## 3. Entrypoint oficial

O entrypoint oficial de operação do fluxo novo é:

- `cli_envio.py`

É ele que deve orquestrar o fluxo:

- carregar planilha;
- validar template;
- transformar e validar linhas;
- gerar resumo do lote;
- executar preflight técnico;
- criar stores e persistir o estado inicial do lote;
- solicitar aprovação;
- enviar;
- exibir resultado final;
- registrar auditoria.

---

## 4. Template oficial da planilha

A planilha de entrada é ditada pelo sistema, não pelo usuário.

O projeto não tenta se adaptar a planilhas arbitrárias do Madan.
Em vez disso, usa um modelo oficial fixo.

### 4.1 Colunas obrigatórias

- Estudante
- RA
- Turma
- Trimestre
- Disciplina
- Frente - Professor

### 4.2 Colunas de nota

- AV 1 (OBJ)
- AV 1 (DISC)
- AV 2 (OBJ)
- AV 2 (DISC)
- AV 3 (listas)
- AV 3 (avaliação)
- Simulado
- Ponto extra
- Recuperação

### 4.3 Colunas opcionais de conferência

- Nota sem a AV 3
- Nota com a AV 3
- Nota Final

### 4.4 Regras do template

- notas entre 0 e 10;
- célula vazia significa não se aplica, nunca zero;
- decimais com vírgula ou ponto são aceitos;
- uma linha por aluno por disciplina;
- RA é obrigatório;
- RA faz parte do schema canônico e é usado para localizar o aluno e sua matrícula no iScholar;
- Frente - Professor faz parte do template oficial, mesmo que `id_professor` possa ou não ser obrigatório no envio dependendo da escola.

As colunas de conferência são auxiliares.
Elas não comandam o payload oficial de envio.

---

## 5. Semântica oficial do domínio

As decisões centrais do fluxo novo são:

- a planilha fixa é a única entrada oficial;
- o lançamento canônico é a verdade interna do sistema;
- `valor_ponderado` é artefato interno de validação e auditoria;
- o valor enviado ao iScholar deve ser a nota bruta;
- `sendavel=True` significa item final pronto para virar POST oficial;
- o fluxo oficial é o novo pipeline auditável, e não o fluxo legado.

### 5.1 O que deve ser tratado como legado

Tudo que ainda orbita em torno de conceitos como:

- `consultar_notas`
- `criar_nota`
- `sync_notas_idempotente`
- `identificacao`
- `tipo`
- `data_lancamento`
- `observacao`

deve ser tratado como legado ou compatibilidade transitória, não como rota oficial do sistema.

---

## 6. Componentes principais

### 6.1 Entrada e normalização

- `madan_planilha_mapper.py` — mapeia aliases, colunas obrigatórias e contexto canônico da linha.

### 6.2 Regras pedagógicas

- `avaliacao_rules.py` — centraliza regras explícitas de cálculo e interpretação pedagógica.

### 6.3 Transformação

- `transformador.py` — converte linha wide da planilha em lançamentos canônicos auditáveis.

### 6.4 Validação pré-envio

- `validacao_pre_envio.py` — qualifica os lançamentos antes da aprovação e do envio.

### 6.5 Controle de lote

- `aprovacao_lote.py`
- `aprovacao_lote_store.py`
- `lote_itens_store.py`

Responsáveis por:

- resumo do lote;
- elegibilidade;
- aprovação explícita;
- persistência dos itens aprovados.

### 6.6 Integração com iScholar

- `resolvedor_ids_ischolar.py`
- `ischolar_client.py`
- `envio_lote.py`

Responsáveis por:

- resolver `id_matricula`, `id_disciplina`, `id_avaliacao` e `id_professor` quando aplicável;
- montar o payload oficial;
- enviar item a item;
- registrar falhas parciais sem perder rastreabilidade.

### 6.7 Discovery e autopreenchimento de mapas

- `descobrir_ids_ischolar.py` — script standalone de discovery que chama a API real para descobrir shapes e IDs, sem modificar nenhum dado.

### 6.8 Auditoria

- `envio_lote_audit_store.py` — persiste auditoria do resultado por item.

### 6.9 Observabilidade e suporte

- `alertas.py`
- `logger.py`

Responsáveis por logging e alertas operacionais.

---

## 7. Contrato atual com o iScholar

### 7.1 Endpoints oficiais integrados

O sistema integra os seguintes endpoints da API iScholar, todos autenticados via `X-Autorizacao` (token) + `X-Codigo-Escola` (headers):

#### Resolução de IDs (fluxo principal)

| Endpoint | Método | Função no sistema |
|----------|--------|-------------------|
| `/aluno/busca` | GET | Busca aluno por RA (`numero_re`), CPF ou `id_aluno`. Retorna `id_aluno`. |
| `/matricula/listar` | GET | Lista matrículas de um `id_aluno`. Retorna `id_matricula`. |
| `/matricula/pega_alunos` | GET | **Fallback:** busca alunos de uma turma, retornando `id_aluno`, `id_matricula` e `numero_re` juntos. |

#### Discovery e autopreenchimento de mapas

| Endpoint | Método | Função no sistema |
|----------|--------|-------------------|
| `/disciplinas` | GET | Lista todas as disciplinas cadastradas na escola (id, nome, abreviação). |
| `/funcionarios/professores` | GET | Lista todos os professores cadastrados (id_professor, nome_professor). |

#### Auditoria

| Endpoint | Método | Função no sistema |
|----------|--------|-------------------|
| `/diario/notas` | GET | Consulta notas já lançadas para uma matrícula (reconciliação). |

#### Lançamento (idempotente)

| Endpoint | Método | Função no sistema |
|----------|--------|-------------------|
| `/notas/lanca_nota` | POST | Lançamento principal de nota. Idempotente por contrato. |

### 7.2 Envelope padrão da API

Todas as respostas da API iScholar seguem o envelope:

```json
{
  "status": "sucesso",
  "mensagem": "...",
  "dados": ...
}
```

O campo `dados` contém o payload real (dict ou lista). O sistema extrai automaticamente o conteúdo de `dados` em todas as funções de resposta.

> **Nota importante:** A API retorna IDs como strings (ex: `"id_matricula": "97"`, não `97`). O sistema converte automaticamente via `_coerce_int_strict()` e `int()` com tratamento de erro em todos os caminhos de extração.

### 7.3 Payload oficial de lançamento

O payload oficial de envio (POST `/notas/lanca_nota`) usa:

- `id_matricula` (int, obrigatório)
- `id_disciplina` (int, obrigatório)
- `id_avaliacao` (int, obrigatório)
- `id_professor` (int, condicional — obrigatório somente quando a escola permite lançamentos de nota do mesmo componente por professores diferentes)
- `valor` (float, obrigatório — nota bruta, não ponderada)

### 7.4 Semântica confirmada

- `id_matricula` pode variar por turma/ano/série;
- o aluno pode ser localizado via `/aluno/busca`;
- o `id_aluno` retornado é único e permanente;
- as matrículas podem ser listadas via `/matricula/listar`;
- o valor enviado deve ser a nota pedagógica bruta;
- o endpoint de lançamento é idempotente;
- a autenticação usa `X-Autorizacao` e `X-Codigo-Escola`;
- URL da API: mesma para homologação e produção (`https://api.ischolar.app`);
- diferença entre ambientes: apenas o valor de `X-Codigo-Escola` (homologação: `madan_homolog`).

### 7.5 O que ainda depende de validação em homologação

- confirmação visual dos shapes reais com dados ao vivo (shapes já confirmados via documentação, pendente sanity check com token real);
- confirmação se `id_avaliacao` varia por disciplina, turma, trimestre ou aluno;
- confirmação se `id_professor` é obrigatório para a escola Madan.

---

## 8. Estratégia de resolução de IDs

O resolvedor atual (`ResolvedorIDsHibrido`) é conservador e fail-closed.

### 8.1 id_matricula — via API oficial

Fluxo principal (2 chamadas):

1. `buscar_aluno(ra=...)` → obtém `id_aluno`
2. `listar_matriculas(id_aluno=...)` → obtém `id_matricula`

**Fallback via `pega_alunos`** (1 chamada):

Quando `buscar_aluno` retorna sucesso mas `id_aluno` não pode ser extraído da resposta, o sistema pode acionar `pega_alunos(id_turma=...)` que retorna `id_aluno`, `id_matricula` e `numero_re` juntos para todos os alunos da turma. O aluno é localizado pelo RA (comparação normalizada, fail-closed: `None` se zero ou múltiplos matches).

```text
buscar_aluno(ra="12345")
    │
    ├─ id_aluno extraído? ──► listar_matriculas(id_aluno) ──► id_matricula
    │
    └─ id_aluno NÃO extraído? ──► pega_alunos(id_turma)
                                      │
                                      └─ encontrar_por_ra("12345")
                                            │
                                            ├─ 1 match ──► id_aluno + id_matricula
                                            └─ 0 ou N matches ──► BLOQUEIO (fail-closed)
```

### 8.2 id_disciplina — via DE-PARA local ou discovery

Resolvido por `mapa_disciplinas.json`.

**Autopreenchimento:** O endpoint `GET /disciplinas` retorna todas as disciplinas cadastradas na escola. A função auxiliar `_gerar_mapa_disciplinas()` gera o esqueleto do mapa no formato `mapa_disciplinas_v1`:

```json
{
  "schema": "mapa_disciplinas_v1",
  "disciplinas": [
    {"nome_planilha": "arte", "id_disciplina": 1},
    {"nome_planilha": "matematica", "id_disciplina": 11}
  ]
}
```

### 8.3 id_avaliacao — via DE-PARA local

Resolvido por `mapa_avaliacoes.json`.

### 8.4 id_professor — via DE-PARA local ou discovery

Resolvido por `mapa_professores.json`, quando necessário.

**Autopreenchimento:** O endpoint `GET /funcionarios/professores` retorna todos os professores cadastrados. A função auxiliar `_gerar_mapa_professores()` gera o esqueleto do mapa no formato `mapa_professores_v1`:

```json
{
  "schema": "mapa_professores_v1",
  "professores": [
    {"nome_planilha": "arnold schwarzenegger", "id_professor": 2},
    {"nome_planilha": "maria silva", "id_professor": 5}
  ]
}
```

### 8.5 Postura do resolvedor

O resolvedor é **fail-closed**:

- matrícula ambígua bloqueia;
- disciplina sem mapa bloqueia;
- avaliação sem mapa bloqueia;
- professor obrigatório sem mapa bloqueia;
- ausência de identificador suficiente do aluno bloqueia;
- múltiplos matches no fallback `pega_alunos` bloqueia.

**Nenhuma inferência. Nenhum desempate automático. Bloqueio explícito com rastreabilidade.**

---

## 9. Dataclasses de resultado da API

O `ischolar_client.py` define dataclasses tipadas para cada tipo de operação:

| Dataclass | Endpoint | Campos relevantes |
|-----------|----------|-------------------|
| `ResultadoBuscaAluno` | GET `/aluno/busca` | `sucesso`, `dados`, `erro_categoria` |
| `ResultadoListagemMatriculas` | GET `/matricula/listar` | `sucesso`, `id_matricula_resolvido`, `rastreabilidade` |
| `ResultadoListagemNotas` | GET `/diario/notas` | `sucesso`, `dados` |
| `ResultadoLancamentoNota` | POST `/notas/lanca_nota` | `sucesso`, `idempotente`, `dry_run`, `payload` |
| `ResultadoListagemDisciplinas` | GET `/disciplinas` | `sucesso`, `disciplinas` (lista extraída) |
| `ResultadoListagemProfessores` | GET `/funcionarios/professores` | `sucesso`, `professores` (lista extraída) |
| `ResultadoPegaAlunos` | GET `/matricula/pega_alunos` | `sucesso`, `alunos` (lista extraída) |

Todas seguem o padrão:

- `sucesso: bool` — indica se a operação HTTP foi bem-sucedida;
- `status_code: Optional[int]` — código HTTP da resposta;
- `transitorio: bool` — se o erro é candidato a retry (rede/5xx);
- `erro_categoria: Optional[str]` — classificação machine-readable (`"auth"`, `"validacao"`, `"http"`, `"rede"`);
- `dados: Optional[Any]` — resposta bruta da API.

---

## 10. CLI oficial (cli_envio.py)

O `cli_envio.py` é o orquestrador oficial do fluxo novo.

### 10.1 Fluxo interno atual

1. Carregar planilha;
2. Validar template fixo;
3. Gerar lançamentos canônicos e validar linha a linha;
4. Gerar resumo do lote;
5. Executar preflight técnico;
6. Criar stores e estado inicial do lote;
7. Solicitar aprovação;
8. Enviar (dry-run ou real);
9. Imprimir resultado final.

### 10.2 Exit codes

| Código | Significado |
|--------|-------------|
| `0` | Sucesso |
| `1` | Erro operacional inesperado |
| `2` | Problema de entrada / planilha / template |
| `3` | Lote não elegível / pré-condição violada |
| `4` | Cancelamento do operador |
| `5` | Configuração / mapas / credenciais / preflight técnico |

### 10.3 Bancos locais

O CLI suporta sobrescrever explicitamente os bancos usados no fluxo:

- `--db-aprovacoes`
- `--db-itens`
- `--db-audit`

Defaults continuam vindo de env ou nomes padrão.

---

## 11. Dry-run

O dry-run:

- não faz POST real ao iScholar;
- valida planilha e lote;
- passa pelo fluxo de resolução e preflight conforme a configuração atual;
- pode falhar por credencial, mapa ou resolução de IDs mesmo sem POST real.

**Dry-run não deve ser interpretado como modo totalmente offline.**

---

## 12. Discovery de IDs (`descobrir_ids_ischolar.py`)

Script standalone de discovery, read-only, que chama a API real para descobrir shapes e IDs.

### 12.1 Uso

```bash
# Discovery básico com um RA de teste conhecido:
python descobrir_ids_ischolar.py --ra <RA_TESTE>

# Com respostas brutas da API (para debug):
python descobrir_ids_ischolar.py --ra <RA_TESTE> --verbose

# Gerar esqueletos dos mapas JSON:
python descobrir_ids_ischolar.py --ra <RA_TESTE> --gerar-mapas
```

### 12.2 Etapas internas

| Etapa | O que faz | Endpoint |
|-------|-----------|----------|
| 1. Conectividade | Valida token e código escola | Headers |
| 2. Buscar aluno | Chama com RA, mostra shape, extrai `id_aluno` | GET `/aluno/busca` |
| 3. Listar matrículas | Chama com `id_aluno`, extrai `id_matricula` | GET `/matricula/listar` |
| 4. Listar notas | Mostra IDs de disciplina/avaliação visíveis | GET `/diario/notas` |
| 5. Gerar esqueletos | (com `--gerar-mapas`) Imprime JSON nos schemas dos mapas | — |

### 12.3 Autopreenchimento de mapas via API

Com os novos endpoints, o discovery pode também chamar:

- `GET /disciplinas` → gera esqueleto de `mapa_disciplinas.json` com todas as disciplinas da escola;
- `GET /funcionarios/professores` → gera esqueleto de `mapa_professores.json` com todos os professores.

Isso elimina a necessidade de preencher manualmente os mapas de disciplinas e professores — basta revisar os nomes normalizados gerados.

> **Limitação:** Não existe endpoint equivalente para avaliações. O `mapa_avaliacoes.json` ainda precisa ser preenchido com IDs obtidos via `/diario/notas` ou interface web do iScholar.

---

## 13. Configuração do ambiente

### 13.1 `.env.example`

O projeto inclui um `.env.example` com todas as variáveis documentadas:

```bash
cp .env.example .env
# Editar .env com as credenciais reais
```

Variáveis principais:

| Variável | Obrigatória | Descrição |
|----------|-------------|-----------|
| `ISCHOLAR_BASE_URL` | Sim | `https://api.ischolar.app` (mesma para homologação e produção) |
| `ISCHOLAR_API_TOKEN` | Sim | Token gerado na interface do iScholar |
| `ISCHOLAR_CODIGO_ESCOLA` | Sim | `madan_homolog` (homologação) ou código real (produção) |

### 13.2 Ambientes

- **Homologação:** `ISCHOLAR_CODIGO_ESCOLA=madan_homolog`, interface em `https://madan_homolog.ischolar.com.br/`
- **Produção:** código real da escola, mesmo `ISCHOLAR_BASE_URL`
- **Nunca configure ambos ao mesmo tempo.**

---

## 14. Estado atual do projeto

### 14.1 Já implementado

- template fixo da planilha;
- presença de RA no schema canônico;
- transformação da linha da planilha em lançamentos canônicos;
- validação pré-envio;
- aprovação manual do lote;
- persistência de estado do lote e itens aprovados;
- client oficial completo do iScholar (7 endpoints integrados);
- resolvedor híbrido de IDs com fallback `pega_alunos`;
- envio por item;
- auditoria por item;
- CLI operacional do fluxo novo;
- mapas JSON estruturados;
- suporte a dry-run;
- script de discovery de IDs;
- autopreenchimento de mapas via API;
- 265 testes automatizados passando.

### 14.2 Hardening concluído

**Stores SQLite corrigidos para `:memory:`:**

- `lote_itens_store.py`
- `aprovacao_lote_store.py`
- `envio_lote_audit_store.py`

Todos mantêm conexão compartilhada por instância em `:memory:` e preservam o comportamento antigo para banco em arquivo.

**`cli_envio.py` endurecido para homologação:**

- preflight técnico antes da criação inicial do lote;
- importação defensiva de `IScholarClient` para preservar testabilidade;
- exit codes centralizados no `main()` com exceções específicas;
- processamento resiliente por linha;
- helper explícito para falha interna por linha;
- remoção de acesso a atributos privados do resolvedor;
- flags para `--db-aprovacoes`, `--db-itens` e `--db-audit`.

**Bug do envelope `"dados"` corrigido:**

- `listar_matriculas()` agora reconhece o envelope padrão `"dados"` da API iScholar como primeira chave na extração de itens;
- tratamento adicional para quando `"dados"` contém um dict único (convertido para lista de 1 item);
- compatibilidade mantida com chaves legadas (`"matriculas"`, `"items"`, `"data"`).

**Semântica de dry-run esclarecida:**

- não faz POST real;
- ainda pode exigir credenciais, mapas e resolução de IDs.

### 14.3 Provisório / sujeito a validação

- confirmação visual dos shapes reais com dados ao vivo (pendente token);
- parte da semântica pedagógica ainda dependente de validação operacional;
- procedimento formal de retry/reprocessamento em produção.

### 14.4 Depende do TI do iScholar

- ~~acesso ao ambiente de homologação~~ → **Resolvido** (`madan_homolog`);
- ~~credenciais e código da escola de teste~~ → **Parcialmente resolvido** (código = `madan_homolog`, token a gerar pelo operador);
- ~~shape de `/aluno/busca`~~ → **Resolvido** (confirmado via documentação oficial da API);
- ~~shape de `/matricula/listar`~~ → **Resolvido** (confirmado via documentação oficial da API);
- ~~forma de obter `id_disciplina`~~ → **Resolvido** (endpoint `GET /disciplinas` confirmado);
- ~~forma de obter `id_professor`~~ → **Resolvido** (endpoint `GET /funcionarios/professores` confirmado);
- ~~diferenças entre homologação e produção~~ → **Resolvido** (mesma URL, só muda `X-Codigo-Escola`);
- confirmação se `id_professor` é obrigatório para a escola Madan → **Pendente**;
- confirmação se `id_avaliacao` varia por disciplina/turma/trimestre → **Pendente**.

### 14.5 Depende do Madan

- adoção formal do template fixo;
- garantia de preenchimento do RA;
- fechamento final das regras pedagógicas ainda provisórias;
- definição do piloto controlado;
- política operacional de exceções.

---

## 15. Regras pedagógicas: o que está fechado e o que não está

### 15.1 Fechado no sistema

O sistema já implementa regras pedagógicas explícitas e auditáveis, em vez de heurísticas silenciosas.

### 15.2 Ainda não completamente fechado

As seguintes frentes ainda exigem validação final do Madan ou confirmação operacional:

- consolidação final de AV1 OBJ + AV1 DISC;
- consolidação final de AV2 OBJ + AV2 DISC;
- política final de AV3 incompleta;
- política final de Recuperação;
- política final de Ponto extra em casos de borda;
- como essas regras devem aparecer no diário do iScholar.

O projeto prefere:

- erro explícito;
- pendência clara;
- bloqueio seguro;
- DE-PARA provisório bem documentado;

e evita heurísticas silenciosas perigosas.

---

## 16. Fluxo operacional esperado

1. Preencher a planilha oficial;
2. Validar colunas obrigatórias e RAs;
3. Rodar `cli_envio.py` em `--dry-run`;
4. Corrigir erros encontrados;
5. Repetir dry-run até o lote ficar consistente;
6. Confirmar o preflight técnico;
7. Aprovar o lote;
8. Executar envio real;
9. Conferir resultado no iScholar;
10. Registrar divergências e ajustes.

---

## 17. Fluxo de homologação esperado

1. Copiar `.env.example` para `.env` e configurar credenciais;
2. Rodar `descobrir_ids_ischolar.py --ra <RA_TESTE>` para validar conectividade e shapes;
3. Rodar com `--gerar-mapas` para criar esqueletos dos mapas;
4. Preencher mapas com IDs reais (disciplinas e professores podem ser autopreenchidos via API);
5. Rodar dry-run completo;
6. Validar payloads e resolução de IDs;
7. Executar POST real em homologação (piloto 1-3 alunos);
8. Conferir nota no diário do iScholar;
9. Confirmar idempotência (reenvio não duplica);
10. Só depois considerar produção (primeiro envio acompanhado pelo desenvolvedor).

> Consultar `checklist_homologacao.md` para o checklist detalhado de go/no-go.

---

## 18. O que não fazer

- Não tentar adaptar planilhas arbitrárias;
- Não inventar mapeamentos no chute;
- Não tratar o fluxo legado como principal;
- Não supor que homologação e produção são equivalentes sem validação;
- Não endurecer regra pedagógica provisória sem confirmação do Madan;
- Não apagar bancos locais de auditoria/estado sem motivo operacional claro.

---

## 19. Estrutura resumida do repositório

**Núcleo do fluxo oficial novo:**

- `cli_envio.py` — orquestrador principal
- `madan_planilha_mapper.py` — mapeamento e validação do template
- `avaliacao_rules.py` — regras pedagógicas
- `transformador.py` — transformação canônica
- `validacao_pre_envio.py` — validação pré-envio
- `aprovacao_lote.py` — controle de lote e aprovação
- `aprovacao_lote_store.py` — persistência de aprovações (SQLite)
- `lote_itens_store.py` — persistência de itens aprovados (SQLite)
- `resolvedor_ids_ischolar.py` — resolvedor híbrido de IDs (fail-closed)
- `ischolar_client.py` — cliente HTTP para a API iScholar (7 endpoints)
- `envio_lote.py` — envio por item com rastreabilidade
- `envio_lote_audit_store.py` — auditoria por item (SQLite)

**Discovery e configuração:**

- `descobrir_ids_ischolar.py` — script standalone de discovery de IDs
- `.env.example` — template de configuração do ambiente
- `mapa_disciplinas.json` — DE-PARA de disciplinas
- `mapa_avaliacoes.json` — DE-PARA de avaliações
- `mapa_professores.json` — DE-PARA de professores

**Documentação operacional:**

- `operacoes.md` — guia de operação para o operador
- `checklist_homologacao.md` — checklist de homologação e go/no-go

**Suporte operacional:**

- `logger.py`
- `alertas.py`

**Compatibilidade / transição / auxiliares:**

- `worker.py`
- `monitor.py`
- `webhook_google_sheets.py`
- outros componentes legados ainda presentes no repositório

---

## 20. Cobertura de testes

O projeto possui **265 testes automatizados** organizados em:

| Suite | Cobertura |
|-------|-----------|
| `test_ischolar_client.py` | Sync idempotente, conflitos, fallbacks legados |
| `test_resolvedor_ids_ischolar.py` | Resolução de IDs, mapas, fail-closed |
| `test_cli_envio.py` | Fluxo completo do CLI, exit codes |
| `test_transformador.py` | Transformação canônica |
| `test_validacao_pre_envio.py` | Validação pré-envio |
| `test_aprovacao_lote.py` | Aprovação, elegibilidade, snapshot |
| `test_madan_planilha_mapper.py` | Template, colunas, aliases |
| `test_avaliacao_rules.py` | Regras pedagógicas |
| `test_novos_endpoints.py` | Novos endpoints, envelope "dados", fallback pega_alunos, autopreenchimento de mapas, coerção int/string |
| `test_alertas.py` | Alertas operacionais |
| `test_snapshot_store.py` | Persistência de snapshots |
| `test_job_store.py` | Persistência de jobs |
| `test_worker_retry.py` | Retry do worker legado |
| `test_worker_semantica_envio.py` | Semântica de envio legado |

---

## 21. Resumo executivo

Este projeto já possui:

- arquitetura correta;
- semântica interna forte;
- controle operacional de lote;
- rastreabilidade;
- stores endurecidos;
- CLI endurecido para homologação;
- 7 endpoints da API integrados com dataclasses tipadas;
- fallback robusto para resolução de IDs;
- autopreenchimento de mapas via API;
- script de discovery para homologação;
- 265 testes automatizados passando;
- base técnica suficiente para validar a integração real.

O que ainda falta não é "escrever o pipeline do zero".
O que falta é fechar a integração real e as decisões operacionais externas para transformar esse pipeline em rotina confiável de produção.

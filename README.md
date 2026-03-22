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

O objetivo do projeto **não** é apenas “chamar a API do iScholar”.

O objetivo é construir um fluxo operacional completo, confiável e auditável que:

- 1. recebe uma planilha oficial de notas;
- 2. interpreta essa planilha segundo regras pedagógicas explícitas;
- 3. transforma cada linha em lançamentos canônicos auditáveis;
- 4. valida os lançamentos antes do envio;
- 5. executa um preflight técnico antes da aprovação humana;
- 6. exige aprovação manual do lote;
- 7. resolve os IDs necessários no iScholar;
- 8. envia apenas os itens aprovados;
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
## 4. Template oficial da planilha

A planilha de entrada é ditada pelo sistema, não pelo usuário.

O projeto não tenta se adaptar a planilhas arbitrárias do Madan.
Em vez disso, usa um modelo oficial fixo.

### 4.1 Colunas obrigatórias
Estudante
RA
Turma
Trimestre
Disciplina
Frente - Professor
### 4.2 Colunas de nota
AV 1 (OBJ)
AV 1 (DISC)
AV 2 (OBJ)
AV 2 (DISC)
AV 3 (listas)
AV 3 (avaliação)
Simulado
Ponto extra
Recuperação
### 4.3 Colunas opcionais de conferência
Nota sem a AV 3
Nota com a AV 3
Nota Final
### 4.4 Regras do template
- notas entre 0 e 10;
- célula vazia significa não se aplica, nunca zero;
- decimais com vírgula ou ponto são aceitos;
- uma linha por aluno por disciplina;
- RA é obrigatório;
- RA faz parte do schema canônico e é usado para localizar o aluno e sua matrícula no iScholar;
Frente - Professor faz parte do template oficial, mesmo que id_professor possa ou não ser obrigatório no envio dependendo da escola.

As colunas de conferência são auxiliares.
Elas não comandam o payload oficial de envio.

## 5. Semântica oficial do domínio

As decisões centrais do fluxo novo são:

- a planilha fixa é a única entrada oficial;
- o lançamento canônico é a verdade interna do sistema;
- valor_ponderado é artefato interno de validação e auditoria;
- o valor enviado ao iScholar deve ser a nota bruta;
- sendavel=True significa item final pronto para virar POST oficial;
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

## 6. Componentes principais
### 6.1 Entrada e normalização
- `madan_planilha_mapper.py`
Mapeia aliases, colunas obrigatórias e contexto canônico da linha.
### 6.2 Regras pedagógicas
- `avaliacao_rules.py`
Centraliza regras explícitas de cálculo e interpretação pedagógica.
### 6.3 Transformação
- `transformador.py`
Converte linha wide da planilha em lançamentos canônicos auditáveis.
### 6.4 Validação pré-envio
- `validacao_pre_envio.py`
Qualifica os lançamentos antes da aprovação e do envio.
### 6.5 Controle de lote
- `aprovacao_lote.py`
- `aprovacao_lote_store.py`
- `lote_itens_store.py`

Responsáveis por:

- resumo do lote;
- elegibilidade;
- aprovação explícita;
persistência dos itens aprovados.
### 6.6 Integração com iScholar
- `resolvedor_ids_ischolar.py`
- `ischolar_client.py`
- `envio_lote.py`

Responsáveis por:

- resolver id_matricula, id_disciplina, id_avaliacao e id_professor quando aplicável;
- montar o payload oficial;
- enviar item a item;
registrar falhas parciais sem perder rastreabilidade.
### 6.7 Auditoria
- `envio_lote_audit_store.py`

Responsável por persistir auditoria do resultado por item.

### 6.8 Observabilidade e suporte
- `alertas.py`
- `logger.py`

Responsáveis por logging e alertas operacionais.

## 7. Contrato atual com o iScholar

Com base no retorno já confirmado pelo suporte do iScholar:

### 7.1 Payload oficial de lançamento

O payload oficial de envio usa:

id_matricula
id_disciplina
id_avaliacao
id_professor (quando aplicável)
valor
### 7.2 Semântica confirmada
- id_matricula pode variar por turma/ano/série;
- o aluno pode ser localizado via /aluno/busca;
- o id_aluno retornado é único e permanente;
- as matrículas podem ser listadas via /matricula/listar;
- o valor enviado deve ser a nota pedagógica bruta;
- o endpoint de lançamento é idempotente;
a autenticação usa X-Autorizacao e X-Codigo-Escola.
### 7.3 O que ainda não deve ser tratado como resolvido

Ainda dependem de validação final em homologação e/ou resposta complementar do TI:

- shape real de /aluno/busca;
- shape real de /matricula/listar;
- critério formal para desempate de matrícula ambígua;
- forma correta de obter ou mapear id_disciplina;
- forma correta de obter ou mapear id_avaliacao;
- confirmação se id_avaliacao varia por disciplina, turma, trimestre ou aluno;
- confirmação se id_professor é obrigatório para a escola Madan;
diferenças reais entre homologação e produção.
## 8. Estado atual do projeto
### 8.1 Já implementado
- template fixo da planilha;
- presença de RA no schema canônico;
- transformação da linha da planilha em lançamentos canônicos;
- validação pré-envio;
- aprovação manual do lote;
- persistência de estado do lote e itens aprovados;
- client oficial novo do iScholar;
- resolvedor híbrido de IDs;
- envio por item;
- auditoria por item;
- CLI operacional do fluxo novo;
- mapas JSON estruturados;
- suporte a dry-run.
### 8.2 Hardening recente concluído

Foram concluídos os ajustes de infraestrutura e orquestração mais importantes para a homologação:

**Stores SQLite corrigidos para `:memory:`:**

- `lote_itens_store.py`
- `aprovacao_lote_store.py`
- `envio_lote_audit_store.py`

Todos agora mantêm conexão compartilhada por instância em :memory: e preservam o comportamento antigo para banco em arquivo.

**`cli_envio.py` endurecido para homologação:**
- preflight técnico antes da criação inicial do lote;
- importação defensiva de IScholarClient para preservar testabilidade;
- exit codes centralizados no main() com exceções específicas;
- processamento resiliente por linha;
- helper explícito para falha interna por linha;
- remoção de acesso a atributos privados do resolvedor;
- flags para --db-aprovacoes, --db-itens e --db-audit;
- docstring e help alinhados ao fluxo oficial novo.
**Semântica de dry-run esclarecida:**
- não faz POST real;
- ainda pode exigir credenciais, mapas e resolução de IDs.
### 8.3 Provisório / sujeito a validação
- comportamento exato de resolução de aluno e matrícula com a resposta real da API;
- shape final dos mapas conforme ambiente real do Madan;
- parte da semântica pedagógica ainda dependente de validação operacional;
- procedimento formal de retry/reprocessamento em produção;
- fechamento total do comportamento em homologação;
- alinhamento final dos testes ligados ao CLI e ao envio, conforme evolução do fluxo oficial.
### 8.4 Depende do TI do iScholar
- acesso ao ambiente de homologação;
- credenciais e código da escola de teste;
- exemplos reais ou anonimizados das respostas de aluno e matrícula;
- confirmação sobre disciplina, avaliação e professor;
- diferenças entre homologação e produção.
### 8.5 Depende do Madan
- adoção formal do template fixo;
- garantia de preenchimento do RA;
- fechamento final das regras pedagógicas ainda provisórias;
- definição do piloto controlado;
política operacional de exceções.
## 9. Regras pedagógicas: o que está fechado e o que não está
### 9.1 Fechado no sistema

O sistema já implementa regras pedagógicas explícitas e auditáveis, em vez de heurísticas silenciosas.

### 9.2 Ainda não deve ser vendido como completamente fechado

As seguintes frentes ainda exigem validação final do Madan ou confirmação operacional:

- - consolidação final de AV1 OBJ + AV1 DISC;
- - consolidação final de AV2 OBJ + AV2 DISC;
- política final de AV3 incompleta;
- política final de Recuperação;
- política final de Ponto extra em casos de borda;
como essas regras devem aparecer no diário do iScholar.

O projeto prefere:

- - erro explícito;
- - pendência clara;
- - bloqueio seguro;
- - DE-PARA provisório bem documentado;

e evita heurísticas silenciosas perigosas.

## 10. Estratégia de resolução de IDs

O resolvedor atual é conservador.

### 10.1 id_matricula

Resolvido via API oficial:

- `/aluno/busca`
- `/matricula/listar`
### 10.2 id_disciplina

Atualmente resolvido por DE-PARA local:

- `mapa_disciplinas.json`
### 10.3 id_avaliacao

Atualmente resolvido por DE-PARA local:

- `mapa_avaliacoes.json`
### 10.4 id_professor

Resolvido por:

- `mapa_professores.json`, quando necessário
### 10.5 Postura do resolvedor

O resolvedor é fail-closed:

- matrícula ambígua bloqueia;
- disciplina sem mapa bloqueia;
- avaliação sem mapa bloqueia;
- professor obrigatório sem mapa bloqueia;
- ausência de identificador suficiente do aluno bloqueia.
## 11. CLI oficial (cli_envio.py)

O cli_envio.py é o orquestrador oficial do fluxo novo.

### 11.1 Fluxo interno atual
- carregar planilha;
- validar template fixo;
- gerar lançamentos canônicos e validar linha a linha;
- gerar resumo do lote;
- executar preflight técnico;
- criar stores e estado inicial do lote;
- solicitar aprovação;
- enviar (dry-run ou real);
- - imprimir resultado final.
### 11.2 Exit codes
- 0 — sucesso
- 1 — erro operacional inesperado
- 2 — problema de entrada / planilha / template
- 3 — lote não elegível / pré-condição violada
- 4 — cancelamento do operador
- 5 — configuração / mapas / credenciais / preflight técnico
### 11.3 Bancos locais

O CLI suporta sobrescrever explicitamente os bancos usados no fluxo:

- `--db-aprovacoes`
- `--db-itens`
- `--db-audit`

Defaults continuam vindo de env ou nomes padrão.

## 12. Dry-run

O dry-run:

- não faz POST real ao iScholar;
- valida planilha e lote;
- passa pelo fluxo de resolução e preflight conforme a configuração atual;
- - pode falhar por credencial, mapa ou resolução de IDs mesmo sem POST real.

dry-run não deve ser interpretado como modo totalmente offline.

## 13. Fluxo operacional esperado
- preencher a planilha oficial;
- validar colunas obrigatórias e RAs;
- rodar cli_envio.py em --dry-run;
- corrigir erros encontrados;
- repetir dry-run até o lote ficar consistente;
- confirmar o preflight técnico;
- aprovar o lote;
- executar envio real;
- conferir resultado no iScholar;
- registrar divergências e ajustes.
## 14. Fluxo de homologação esperado

Assim que o ambiente de homologação estiver liberado, o fluxo esperado é:

- configurar credenciais e ambiente de teste;
- validar conectividade;
- validar shape real das respostas da API;
- preencher mapas com IDs reais;
- rodar dry-run;
- validar payloads;
- executar POST real em homologação;
- rodar piloto pequeno e controlado;
- só depois considerar produção.
## 15. O que não fazer
- não tentar adaptar planilhas arbitrárias;
- não inventar mapeamentos no chute;
- não tratar o fluxo legado como principal;
- não supor que homologação e produção são equivalentes sem validação;
- não endurecer regra pedagógica provisória sem confirmação do Madan;
- não apagar bancos locais de auditoria/estado sem motivo operacional claro.
## 16. Estrutura resumida do repositório
**Núcleo do fluxo oficial novo:**
- `cli_envio.py`
- `madan_planilha_mapper.py`
- `avaliacao_rules.py`
- `transformador.py`
- `validacao_pre_envio.py`
- `aprovacao_lote.py`
- `aprovacao_lote_store.py`
- `lote_itens_store.py`
- `resolvedor_ids_ischolar.py`
- `ischolar_client.py`
- `envio_lote.py`
- `envio_lote_audit_store.py`
**Suporte operacional:**
- `logger.py`
- `alertas.py`
**Compatibilidade / transição / auxiliares:**
- `worker.py`
- `monitor.py`
- `webhook_google_sheets.py`
- outros componentes legados ainda presentes no repositório
## 17. Próximos passos

Os próximos passos mais prováveis são:

- - alinhar e consolidar os testes ligados ao CLI e ao envio;
- receber a resposta complementar do TI do iScholar;
- preencher os mapas com dados reais;
- executar homologação;
- rodar piloto controlado;
só então avançar para produção.
## 18. Resumo executivo

Este projeto já possui:

- arquitetura correta;
- semântica interna forte;
- controle operacional de lote;
- rastreabilidade;
- stores endurecidos;
- CLI endurecido para homologação;
base técnica suficiente para validar a integração real.

O que ainda falta não é “escrever o pipeline do zero”.
O que falta é fechar a integração real e as decisões operacionais externas para transformar esse pipeline em rotina confiável de produção.
# Guia de Operação — Sistema de Lançamento de Notas Madan → iScholar

Este guia é destinado ao operador responsável por preparar a planilha, executar o sistema e aprovar o lote.  
Você **não precisa ser programador** para seguir estas instruções, mas algumas ações continuam sendo responsabilidade do desenvolvedor.

---

## 1. O que o sistema faz

O sistema:

1. lê a planilha oficial de notas do Madan;
2. valida o template e as regras de preenchimento;
3. transforma cada linha em lançamentos canônicos auditáveis;
4. gera um resumo do lote;
5. realiza o **preflight técnico** — verifica credenciais, carrega os mapas de IDs e confirma que a comunicação com o iScholar está disponível;
6. cria o estado do lote e exige **aprovação explícita**;
7. resolve os IDs necessários no iScholar;
8. envia apenas os itens aprovados;
9. registra auditoria por item.

**Nenhuma nota é lançada sem aprovação explícita.**

**O preflight técnico acontece antes da aprovação.** Se as credenciais ou os mapas de IDs estiverem incorretos, o sistema falha antes de criar qualquer registro de lote.

---

## 2. Limites de responsabilidade

### O operador pode
- preencher a planilha no modelo oficial;
- executar o sistema em `--dry-run` para verificação prévia;
- revisar o resumo do lote;
- aprovar o lote quando estiver correto;
- conferir o resultado no iScholar após o envio.

### O operador não deve
- editar arquivos `.json` de mapeamento manualmente;
- alterar o arquivo `.env`;
- mudar o template oficial por conta própria;
- tentar "forçar" envio quando houver erro de resolução;
- apagar os bancos `.db` de histórico e auditoria.

### O desenvolvedor deve ser acionado quando houver
- erro de configuração (credenciais, `.env`);
- disciplina sem mapeamento;
- avaliação sem mapeamento;
- dúvida sobre reprocessamento de um lote;
- divergência entre planilha e iScholar;
- problema de homologação ou produção;
- necessidade de alterar regra de negócio ou template.

---

## 3. Ambientes: homologação e produção

### Homologação
Ambiente de testes para validar:
- credenciais;
- resolução de IDs;
- comportamento real da API;
- mapeamentos;
- piloto controlado.

A homologação precisa de dados reais (IDs, credenciais) fornecidos pelo TI. Não assuma que o ambiente de homologação funciona apenas trocando a URL — isso ainda precisa ser validado operacionalmente.

### Produção
Ambiente real de lançamento.  
Use produção **somente após** a homologação estar validada e os mapeamentos confirmados.

**Recomendação:** o primeiro envio em produção deve ser acompanhado pelo desenvolvedor.

---

## 4. Pré-requisitos antes de começar

Antes de executar o sistema, confirme:

1. o projeto está instalado no computador;
2. o arquivo `.env` está configurado com as credenciais corretas do iScholar;
3. os arquivos `mapa_disciplinas.json` e `mapa_avaliacoes.json` estão preenchidos com IDs reais;
4. se a escola exigir professor no lançamento, o arquivo `mapa_professores.json` também está preenchido;
5. o ambiente correto está configurado: homologação ou produção.

Se qualquer um desses itens estiver incerto, chame o desenvolvedor.

---

## 5. Planilha oficial

O sistema aceita **somente** a planilha no formato do modelo oficial.

**Não use outra planilha.**  
**Não adapte planilhas antigas.**  
**Não renomeie colunas.**

### 5.1 Colunas obrigatórias do template

| Coluna | O que colocar |
|--------|---------------|
| Estudante | Nome completo do aluno |
| RA | Identificador usado para localizar o aluno e sua matrícula no iScholar |
| Turma | Identificador da turma (ex.: `2A`, `3B`) |
| Trimestre | Apenas `1`, `2` ou `3` |
| Disciplina | Nome da disciplina no padrão adotado pelo projeto |
| Frente - Professor | Frente e professor no padrão adotado pelo template |

### 5.2 Colunas de nota

- `AV 1 (OBJ)`
- `AV 1 (DISC)`
- `AV 2 (OBJ)`
- `AV 2 (DISC)`
- `AV 3 (listas)`
- `AV 3 (avaliação)`
- `Simulado`
- `Ponto extra`
- `Recuperação`

### 5.3 Colunas opcionais de conferência

- `Nota sem a AV 3`
- `Nota com a AV 3`
- `Nota Final`

Essas colunas são **auxiliares** — servem apenas para apoio visual.  
Elas **não comandam o envio** e não substituem a lógica interna do sistema.

---

## 6. Regras de preenchimento da planilha

### Regras gerais
- As notas devem estar entre **0 e 10**.
- Decimais com **vírgula ou ponto** são aceitos.
  - Exemplos: `8,5` e `8.5`
- Célula vazia significa **"não se aplica"**.
- **Não use zero** para representar ausência de avaliação.
- Deve existir **uma linha por aluno por disciplina**.

### Sobre o RA
O **RA é obrigatório**.  
Ele é o identificador usado na planilha para localizar o aluno e sua matrícula no iScholar.

Sem RA, o sistema não consegue resolver o aluno com segurança.

Se você não tiver o RA, solicite ao setor responsável antes de prosseguir.

### Sobre `Frente - Professor`
A coluna `Frente - Professor` **faz parte do template oficial** e deve ser preenchida conforme o padrão definido pelo projeto.

**Importante:** o preenchimento da coluna no arquivo não significa, por si só, que `id_professor` será sempre exigido no envio.  
Essa obrigatoriedade depende da configuração da escola no iScholar.

### Sobre AV3
O sistema trata AV3 com duas colunas:
- `AV 3 (listas)`
- `AV 3 (avaliação)`

Se apenas uma delas estiver preenchida, o sistema pode sinalizar a AV3 como incompleta.

**Observação:** a regra pedagógica final de AV3 deve seguir o que foi validado com o Madan. Em caso de dúvida operacional, consulte o desenvolvedor antes do envio.

### Sobre ponto extra
Preencha `Ponto extra` apenas quando houver bônus real.

**Não coloque zero** quando não houver ponto extra.

A forma de aplicação do ponto extra segue as regras pedagógicas validadas no sistema. Se houver dúvida sobre o comportamento esperado no diário, consulte o desenvolvedor.

### Sobre recuperação
Preencha `Recuperação` apenas para alunos em recuperação.  
Não preencha para alunos que não estejam nessa situação.

---

## 7. Execução do sistema

Abra o terminal na pasta do projeto.

### 7.1 Verificação prévia (`--dry-run`)

Recomendado sempre antes do envio real:

```bash
python cli_envio.py --planilha notas_t1_2A.xlsx --lote-id t1-2A-2026 --dry-run --aprovador "Seu Nome"
```

**O `--dry-run` não faz POST real**, mas **não é um modo offline**.  
O sistema ainda pode precisar de credenciais e fazer chamadas à API do iScholar para resolver IDs.  
Erros de credencial ou de mapa de IDs aparecem normalmente no dry-run.

Use o dry-run para:
- verificar se o template está correto;
- confirmar que os mapas de disciplinas e avaliações estão carregados;
- revisar o resumo do lote antes de aprovar.

### 7.2 Envio real

Após revisar o resultado do dry-run e confirmar que está correto:

```bash
python cli_envio.py --planilha notas_t1_2A.xlsx --lote-id t1-2A-2026 --aprovador "Seu Nome"
```

O sistema irá:
1. processar a planilha e gerar o resumo;
2. executar o preflight técnico (credenciais e mapas);
3. apresentar o resumo do lote e solicitar aprovação;
4. após aprovação, enviar os itens ao iScholar;
5. exibir o resultado final com contagens de itens enviados e eventuais erros.

### 7.3 Caminhos opcionais para os bancos de dados

Se precisar usar caminhos específicos para os bancos:

```bash
python cli_envio.py \
  --planilha notas_t1_2A.xlsx \
  --lote-id t1-2A-2026 \
  --dry-run \
  --aprovador "Seu Nome" \
  --db-aprovacoes aprovacoes.db \
  --db-itens itens.db \
  --db-audit audit.db
```

---

## 8. Códigos de saída do sistema

| Código | Significado |
|--------|-------------|
| `0` | Sucesso — lote enviado sem erros |
| `1` | Erro operacional inesperado — chame o desenvolvedor |
| `2` | Problema na planilha ou no template — verifique as colunas |
| `3` | Lote não elegível ou pré-condição de envio violada |
| `4` | Aprovação cancelada pelo operador |
| `5` | Problema de configuração — credenciais, mapas ou preflight técnico |

---

## 9. O que fazer em caso de erro

| Situação | Ação |
|----------|------|
| Coluna obrigatória ausente (código 2) | Corrija a planilha e reprocesse |
| Lote não elegível (código 3) | Verifique as notas inválidas no resumo e corrija a planilha |
| Erro de credencial ou mapa (código 5) | Chame o desenvolvedor |
| Erro inesperado (código 1) | Chame o desenvolvedor com o texto do erro |
| Item com erro de resolução de IDs | Chame o desenvolvedor — pode ser disciplina ou avaliação sem mapeamento |

**Nunca tente reprocessar ou reenviar** sem entender a causa do erro.  
Em caso de dúvida, chame o desenvolvedor.

---

## 10. Notas sobre reprocessamento e retry

O sistema **não realiza retry ou reexecução automática** em produção.  
Se um envio falhar parcialmente, o comportamento correto de reprocessamento precisa ser definido e acompanhado pelo desenvolvedor.

Não tente reenviar um lote por conta própria sem confirmar com o desenvolvedor o que aconteceu.

---

## 11. Rota oficial de lançamento

A rota oficial deste projeto é o envio via CLI a partir da planilha fixa.

A importação por planilha diretamente no painel do iScholar é uma funcionalidade separada do sistema e **não é a rota oficial deste projeto**.
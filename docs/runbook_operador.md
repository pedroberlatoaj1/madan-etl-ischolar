# Runbook do Operador — Envio de Notas via Google Sheets

Guia para o operador/coordenador que envia notas ao iScholar pela planilha
`madan_2026_anual` no Google Sheets.

**O backend fica no ar 24/7 (Railway).** Não existe mais nada para "subir":
sem janelas pretas, sem túnel, sem atualizar URL. Se o menu **iScholar ETL**
aparece na barra da planilha, está tudo pronto.

---

## Fluxo normal de envio

### Passo 0 — Ir até a aba correta

1. Na parte inferior do Sheets, clique na aba da turma e trimestre
   (ex.: `1B_T2`, `2A_T3`).
2. Um diálogo de confirmação sempre mostra qual aba será processada —
   leia antes de dar OK.
3. Cada aba é um envio independente.

### Passo 1 — Validar

1. **iScholar ETL > Validar Lote**
2. Aguarde o diálogo "Resultado da Validacao" e confira:
   - `Apto para aprovacao: sim` → pode seguir
   - A seção **Erros** lista cada problema com linha e motivo
   - A seção **Colunas da planilha** avisa se algum cabeçalho não foi
     reconhecido (notas nessas colunas seriam descartadas)
3. **Validar NÃO envia nada.** O diálogo e o e-mail dizem isso
   explicitamente ("AGUARDANDO APROVACAO / nenhuma nota foi enviada ainda").
   O envio só acontece no Passo 2.

### Passo 2 — Aprovar e Enviar

1. **iScholar ETL > Aprovar e Enviar**
2. Digite seu nome no campo do aprovador e dê **OK**
   (cancelar aqui aborta tudo — aparece um aviso de "NADA foi enviado")
3. Confirme o diálogo final
4. Aguarde o "Resultado do Envio" com as contagens (ex.: `740/743 enviados`)

### Passo 3 — Conferir no iScholar

Acesse `madan.ischolar.com.br`, abra o Detalhamento de Notas da turma e
confira uma amostra das notas enviadas.

### Em caso de dúvida — Simular primeiro

**iScholar ETL > Simular (Dry Run)** faz todo o fluxo sem gravar nada no
iScholar. Use sempre que não tiver certeza.

---

## O que significam as mensagens

| Mensagem | Significado | O que fazer |
|----------|-------------|-------------|
| `X/Y enviados` | Envio concluído | Conferir amostra no iScholar |
| `Validacao concluida com bloqueios. Total de erros: N` | Há linhas/notas inválidas na aba; nada foi enviado | Rodar **Validar Lote** e ler a lista "Erros" — corrigir na planilha e validar de novo |
| `Este snapshot ja foi processado anteriormente` | A planilha não mudou desde a última validação | Não é erro — pode seguir para Aprovar e Enviar |
| `Campo 'estudante' ausente/vazio` | Há notas digitadas em linha sem nome de aluno | Achar a linha sem Estudante e corrigir (ver regras abaixo) |
| `professor sem mapeamento` | Cabeçalho com professor que o sistema não reconhece (ex.: professor antigo no trimestre errado) | Avisar o desenvolvedor ANTES de mexer no cabeçalho |
| `Coluna 'X' nao reconhecida ... seriam DESCARTADAS` | Cabeçalho fora do padrão | Corrigir o cabeçalho para `Disciplina - Professor (Frente X) - Tipo` antes de aprovar |
| `RA nao encontrado via pega_alunos` | Aluno sem matrícula ativa naquela turma no iScholar (ex-aluno ou cadastro pendente) | Avisar a coordenação; as demais notas seguem normalmente |
| `Erros de envio: N` | O iScholar rejeitou N notas | Avisar o desenvolvedor com o print do resultado |
| `NADA foi enviado: a identificacao do aprovador foi cancelada` | Você cancelou o prompt do aprovador | Repetir Aprovar e Enviar e preencher o nome |

---

## Regras da planilha (importantes de verdade)

1. **Nunca digite linhas auxiliares dentro da aba de notas** — pesos,
   médias da turma, rascunhos, totais. Qualquer linha com conteúdo é
   tratada como aluno e **bloqueia o lote inteiro**. Cálculos auxiliares
   vão em outra aba.
2. **Aluno novo:** preencha `Estudante`, `RA`, `Turma` e `Trimestre` antes
   das notas — e digite as notas **na mesma linha do nome** (já houve caso
   de notas digitadas uma linha acima, bloqueando o lote).
3. **Apagar = limpar o conteúdo das células.** Ocultar a linha NÃO a
   remove do envio — o sistema lê linhas ocultas.
4. **Cabeçalho** segue o padrão `Disciplina - Professor (Frente X) - Tipo`
   e o professor deve ser o **vigente no trimestre da aba** (T1 =
   professores do início do ano; T2/T3 = ex.: Química Caroline, Geografia
   Emerson). Troca de professor exige atualização do mapa pelo
   desenvolvedor — avise antes de renomear qualquer cabeçalho.
5. **Não renomeie as abas** (`1A_T1` ... `2B_T3`).

---

## Reenvio

Reenviar uma aba é seguro: o iScholar substitui a nota existente da mesma
avaliação/professor. **Exceção:** notas gravadas no passado com professor
diferente (ex.: professor antigo) não são substituídas — ficam numa divisão
separada no iScholar. Casos assim são resolvidos pelo desenvolvedor/escola,
não por reenvio.

---

## Quando acionar o desenvolvedor

- Erro que persiste depois de você corrigir a planilha e revalidar
- Qualquer mensagem de `professor sem mapeamento`
- `Erros de envio` (rejeição do iScholar) em qualquer volume
- Alerta de token iScholar expirado/perto de expirar (chega por e-mail)
- Antes de qualquer mudança estrutural na planilha (coluna nova, aba nova,
  troca de professor no cabeçalho)

## E-mails automáticos

O sistema envia para a coordenação (com cópia ao desenvolvedor):

- `Lote X validado — AGUARDANDO APROVACAO (...)` → só validação, nada enviado
- `Lote aprovado — iniciando envio` → envio em andamento
- `Envio concluído — X/Y` → resultado final (com ⚠️ se houve erro HTTP)

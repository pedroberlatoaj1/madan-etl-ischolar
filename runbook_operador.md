# Guia de Operacao — Envio de Notas via Google Sheets

Este guia e para o operador/coordenador que vai usar o Google Sheets
para enviar notas para o iScholar. Nenhum terminal e necessario apos
a subida inicial dos servicos.

---

## Antes de comecar (uma vez por sessao)

1. Na pasta do projeto, de double-click em **`iniciar_servicos.bat`**
   - Duas janelas pretas vao abrir (backend e worker)
   - NAO feche essas janelas durante o uso

2. De double-click em **`subir_tunel.bat`**
   - Uma janela vai abrir mostrando uma URL tipo `https://xxxx.ngrok-free.app`
   - Copie essa URL

3. No Google Sheets, va em **Extensoes > Apps Script**
   - No topo do codigo, encontre `API_BASE_URL`
   - Cole a URL copiada (sem barra no final)
   - Salve (Ctrl+S)
   - Feche a aba do Apps Script

4. Recarregue a planilha (F5)

O menu **iScholar ETL** deve aparecer na barra superior.

---

## Fluxo normal de envio

### Passo 0 — Navegar ate a aba correta (Plano B)

Se voce esta usando o workbook anual (`madan_2026_anual.xlsx`):

1. Na parte inferior do Sheets, clique na **aba da turma e trimestre** que quer processar
   - Ex: `2A_T1`, `1B_T2`, `2B_T3`
2. Confirme que o nome da aba esta correto antes de prosseguir
3. Cada aba gera um envio independente — nao e preciso processar todas de uma vez

> Se voce esta em uma planilha legada com aba "Notas", pule este passo.

### Passo 1 — Validar

1. Clique em **iScholar ETL > Validar Lote**
2. Um dialog vai mostrar **qual aba sera processada** — confirme que e a correta
3. Aguarde o resultado aparecer
4. Confira o resumo:
   - `Apto para aprovacao: sim` = pode prosseguir
   - `Erros: 0` e `Bloqueados: 0` = tudo certo
5. Clique **OK**

### Passo 2 — Enviar

1. Clique em **iScholar ETL > Aprovar e Enviar**
2. Digite seu nome no campo "Aprovador"
3. Clique **OK**
4. Aguarde o resultado

### Se aparecer "envio em background"

Com lotes grandes (mais de ~10 alunos), o processamento pode demorar.
Se aparecer a mensagem "O envio ainda nao terminou":

1. Clique **OK**
2. Aguarde 2–3 minutos
3. Clique em **iScholar ETL > Mostrar Ultimo Status**
4. Repita ate o resultado final aparecer

### Passo 3 — Conferir no iScholar

1. Acesse `madan.ischolar.com.br`
2. Va ao diario da disciplina enviada
3. Confira que as notas apareceram com o check verde

---

## O que significam os resultados

| Mensagem | Significado | O que fazer |
|----------|-------------|-------------|
| "X/Y enviados" | X notas enviadas com sucesso de Y total | Conferir no diario |
| "Apto para aprovacao: sim" | Validacao OK, pode enviar | Clicar Aprovar e Enviar |
| "Lote ja passou pela fase de envio" | Esse lote ja foi enviado antes | NAO reenviar; conferir no diario |
| "Envio em background" | Lote grande, processando | Esperar e usar Mostrar Ultimo Status |
| "Erros de resolucao: N" | N alunos com RA ou matricula nao encontrada | Avisar a coordenacao (ver abaixo) |
| "Erros de envio: N" | iScholar rejeitou N notas | Avisar a coordenacao (ver abaixo) |
| Erro de conexao | Tunel ngrok caiu | Subir tunel novamente (passo 2 do "Antes de comecar") |

---

## Uso do 2o ano

O 2o ano funciona automaticamente no formato Plano B (workbook anual multi-aba).

Ao processar uma aba como `2A_T1` ou `2B_T2`, o pipeline detecta a turma pelo
nome da aba e resolve o professor correto automaticamente:

| Turma | Disciplina / Frente | Professor resolvido |
|-------|---------------------|---------------------|
| 2A    | Matematica Frente A | Daniel              |
| 2B    | Matematica Frente B | Luan                |
| 2C    | Matematica Frente C | Carioca             |
| 2A    | Biologia            | Perrone             |
| 2B    | Biologia Frente B   | Mayara              |
| 2A    | Geografia Frente A  | Carla               |
| 2B    | Geografia Frente B  | Moreto              |

**Nenhuma acao do operador e necessaria** — basta estar na aba correta ao clicar
em Validar Lote.

> **Nota tecnica (para referencia):** A desambiguacao automatica so funciona
> no formato wide (Plano B). Se por algum motivo voce estiver usando uma
> planilha no formato semi-wide com a coluna `Frente - Professor` preenchida
> manualmente, use os aliases explicitos (`Matematica A - Daniel`, etc.).

---

## Quando algo nao funciona

### O menu "iScholar ETL" nao aparece
- Recarregue a planilha (F5)
- Se nao resolver: Extensoes > Apps Script > verifique se o codigo esta la

### Erro de conexao
- A janela do tunel (ngrok) pode ter fechado
- Suba o tunel novamente e atualize a URL no Apps Script

### "Erros de resolucao" ou "Erros de envio"
- O pipeline enviou as notas que conseguiu e isolou os erros
- As notas enviadas com sucesso JA estao no iScholar
- Os erros sao alunos com dados inconsistentes no iScholar
- Avisar a coordenacao/admin com a lista de alunos que falharam

### As janelas pretas fecharam
- Rode `iniciar_servicos.bat` novamente
- Depois rode `subir_tunel.bat` e atualize a URL

---

## O que NAO fazer

- NAO feche as janelas pretas durante o uso
- NAO clique em Validar Lote sem primeiro navegar ate a aba correta (Passo 0)
- NAO envie o mesmo lote duas vezes sem verificar no diario primeiro
- NAO reenvie indefinidamente quando aparecer erro de resolucao — avisar a coordenacao
- NAO modifique o codigo do Apps Script (exceto a URL do tunel)

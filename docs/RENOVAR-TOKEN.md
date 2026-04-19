# Renovacao do token iScholar (Apps Script)

## Objetivo

Este guia cobre a renovacao manual do JWT do iScholar usado no fluxo `Aprovar e Enviar (Apps Script)`.
Nao existe refresh token automatico para esse integrador.

## 1. Como gerar um novo token no iScholar

> O caminho exato de menu pode variar por perfil no iScholar. O procedimento abaixo descreve o fluxo esperado para usuario administrador.

1. Entrar no iScholar com um usuario autorizado para integracoes/API.
2. Abrir o modulo de integracoes/tokens de API.
3. Selecionar a escola/codigo `madan`.
4. Gerar novo token JWT.
5. Copiar o token completo (cabecalho.payload.assinatura).
6. Registrar a data/hora de expiracao informada no iScholar (quando exibida na tela).

Prints sugeridos para anexar neste documento:
- Tela do menu de Integracoes/API no iScholar.
- Tela de geracao do token (sem expor o token completo no print).

## 2. Onde substituir no codigo

No projeto Apps Script, o token real e lido da Script Property `ISCHOLAR_TOKEN`.
A chave esta definida no arquivo `google_apps_script.gs`:

- `const PROP_ISCHOLAR_TOKEN = "ISCHOLAR_TOKEN";`

Passos de atualizacao:

1. Abrir a planilha no Google Sheets.
2. Ir em `Extensoes > Apps Script`.
3. Abrir `Project Settings`.
4. Em `Script properties`, localizar `ISCHOLAR_TOKEN`.
5. Substituir pelo novo JWT.
6. Salvar.

Importante:
- Nao commitar token em texto claro no repositorio.
- Nao colar token em chat, ticket ou log.

## 3. Como testar sem afetar producao

Use apenas fluxo de validacao + simulacao (dry run):

1. Na planilha, escolher a aba correta (`1A_T1`, `2B_T2`, etc.).
2. Rodar `iScholar ETL > Validar Lote`.
3. Rodar `iScholar ETL > Simular via Apps Script`.
4. Conferir se nao houve 401/403 e se o resumo final veio sem erro de autenticacao.
5. Executar manualmente `verificarTokenIScholar_()` no Apps Script e conferir retorno/log.

Somente apos esse teste usar envio real.

## 4. Quem no Madan pode gerar token

Permissao minima recomendada:

- Usuario administrativo do iScholar com permissao de integracao/API para a escola `madan`.
- Pedro (suporte tecnico) como ponto de contingencia e validacao operacional.

Definir e manter atualizado:

- Nome do responsavel principal no Madan.
- Nome de ao menos 1 substituto.
- Canal de acionamento (email/telefone) em caso de expiracao critica.

## 5. Monitoramento proativo (implementado no Apps Script)

Funcoes adicionadas em `google_apps_script.gs`:

- `decodificarExpiracaoJwt_(token)`: le `exp` do payload JWT com tratamento de padding base64.
- `verificarTokenIScholar_()`: calcula dias para expiracao e envia alerta por email quando necessario.
- `criarTriggerVerificacaoToken_()`: recria trigger semanal (segunda-feira, 9h) de forma idempotente.

Regras de alerta:

- Menos de 30 dias: `[Madan ETL] ⚠️ Token iScholar expira em X dias`.
- Menos de 7 dias: `🚨 URGENTE — Token iScholar expira em X dias`.
- Expirado: `🚨 EXPIRADO — Token iScholar invalido`.

Dedupe:

- O email de alerta e enviado no maximo 1 vez por dia (`PropertiesService`).

## 6. Checklist rapido de renovacao

1. Gerar novo JWT no iScholar.
2. Atualizar `ISCHOLAR_TOKEN` em Script Properties.
3. Rodar `verificarTokenIScholar_()` manualmente.
4. Rodar `Validar Lote` + `Simular via Apps Script`.
5. Confirmar ausencia de 401/403.
6. Registrar data da troca e validade em controle interno.

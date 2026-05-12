Quero retomar o projeto Madan -> iScholar a partir do estado mais recente, sem reabrir caminhos ja descartados.

Contexto importante:

- estamos na pasta `C:\\Users\\PICHAU\\Desktop\\Claude Cenario 2`
- a arquitetura correta continua sendo `Apps Script -> VPS -> iScholar`
- eu nao quero voltar para a alternativa onde o Apps Script envia direto ao iScholar
- a VPS Hetzner ja esta pronta e funcionando na camada de entrada
- o problema apontado pelo iScholar foi rate limit da API, nao whitelist de IP
- por isso o codigo local foi ajustado para implementar controle de taxa no cliente HTTP da VPS
- o `2A` continua fora do escopo de homologacao final porque depende de configuracao do iScholar
- o foco da entrega continua no `2B`

Fonte de verdade para o plano de hoje:

- leia e siga o arquivo `C:\\Users\\PICHAU\\Desktop\\Claude Cenario 2\\PLANO_ENTREGA_MADAN_2026-04-15.md`

Quero que voce:

1. assuma esse plano como roteiro principal
2. primeiro confira o estado atual do repositorio local, do GitHub e da VPS
3. me diga apenas o proximo passo util, com os comandos exatos
4. me conduza ate a validacao final e entrega do projeto ao Madan
5. se algum teste falhar, faca diagnostico objetivo e proponha o menor ajuste necessario

Regras de trabalho para esta conversa:

- nao reintroduzir a arquitetura alternativa de Apps Script chamando o iScholar diretamente
- nao propor refatoracoes amplas
- nao mudar o escopo do projeto
- priorizar entrega segura e evidenciada
- usar o `2B` como trilha principal de homologacao

Comece verificando o estado atual e me diga o primeiro comando exato que devo rodar.

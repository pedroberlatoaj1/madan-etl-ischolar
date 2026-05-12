# Deploy no Railway + Cloudflare R2

## Pré-requisitos

- ✅ PostgreSQL provisionado no Railway (`DATABASE_URL` disponível)
- ✅ Bucket R2 criado (`madan-etl-snapshots`)
- ✅ Token R2 com permissão Read & Write (Access Key + Secret Key)
- ✅ Cloudflare Account ID anotado

---

## Etapa 1 — Push do código para o GitHub

No diretório do projeto local:

```bash
git add -A
git commit -m "feat: migração SQLite → PostgreSQL + Cloudflare R2 (Railway)"
git push origin main
```

---

## Etapa 2 — Conectar o GitHub ao Railway

1. No projeto Railway `acceptable-endurance`, clica em **"+ Create"** → **"GitHub Repo"**
2. Seleciona o repositório `pedroberlatoaj1/madan-etl-ischolar`
3. O Railway detecta o `Dockerfile` automaticamente e começa o build

---

## Etapa 3 — Configurar variáveis de ambiente do webhook

No serviço Web (recém-criado a partir do GitHub), aba **"Variables"**, adicionar:

| Variável | Valor |
|---|---|
| `DATABASE_URL` | Referenciar do Postgres: `${{ Postgres.DATABASE_URL }}` |
| `R2_ACCOUNT_ID` | (account ID do Cloudflare) |
| `R2_ACCESS_KEY_ID` | (Access Key gerada no token R2) |
| `R2_SECRET_ACCESS_KEY` | (Secret Access Key) |
| `R2_BUCKET_NAME` | `madan-etl-snapshots` |
| `WEBHOOK_SECRET` | (gerar string aleatória forte, ex: `python -c "import secrets; print(secrets.token_urlsafe(32))"`) |
| `ISCHOLAR_API_TOKEN` | (JWT do iScholar, mesmo da VPS) |
| `ISCHOLAR_CODIGO_ESCOLA` | `madan` |
| `LOG_LEVEL` | `INFO` |

---

## Etapa 4 — Criar serviço Worker

1. Mesmo projeto, clica em **"+ Create"** → **"Empty Service"**
2. Nome: `worker`
3. Aba **"Settings"** → **"Source"** → conectar o mesmo repositório GitHub
4. Aba **"Settings"** → **"Deploy"** → **"Custom Start Command"**: `python worker.py`
5. Aba **"Variables"** → **clicar em "Shared Variable"** ou copiar as mesmas variáveis do webhook
   - **Importante:** o worker também precisa de `DATABASE_URL`, R2 vars, `ISCHOLAR_*`

---

## Etapa 5 — Gerar domínio público para o webhook

1. No serviço Web, aba **"Settings"** → **"Networking"** → **"Generate Domain"**
2. Anotar a URL gerada (ex: `https://madan-etl-ischolar-production.up.railway.app`)

---

## Etapa 6 — Atualizar URL no Apps Script

Na planilha Google → **Extensões** → **Apps Script** → procurar a constante de URL do backend e trocar pela URL do Railway. Salvar.

---

## Etapa 7 — Smoke test

1. Verificar `/health`:
   ```
   curl https://<sua-url>.up.railway.app/health
   ```
   Esperado: `200 OK`

2. Verificar logs do webhook no painel do Railway — deve aparecer:
   ```
   [db] Schema inicializado com sucesso.
   Servidor webhook ETL iScholar iniciado na porta XXXX
   ```

3. Verificar logs do worker — deve aparecer mesma mensagem de schema OK.

4. Na planilha → preencher 1 nota → **Madan ETL → Validar Lote**
   - Esperado: `1 sendavel, 0 erros`

5. **Madan ETL → Aprovar Lote (Envio Real)**
   - Esperado: `1/1 enviado`

6. Conferir nota no iScholar.

---

## Troubleshooting

**Erro "DATABASE_URL não definida"**
→ Variável não foi configurada. Adicionar no painel do Railway.

**Erro "psycopg2.OperationalError: connection refused"**
→ DATABASE_URL incorreta. Verificar formato `postgresql://user:pass@host:port/db`.

**Erro "NoSuchBucket"**
→ R2_BUCKET_NAME errado, ou token R2 sem permissão no bucket.

**Snapshot não encontrado**
→ R2 credenciais incorretas, ou lifecycle rule apagou. Verificar prefixo `snapshots/` no bucket.

**Apps Script: "não conseguiu conectar"**
→ URL no Apps Script ainda aponta pra VPS antiga. Trocar.

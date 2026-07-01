-- schema.sql — DDL inicial do banco PostgreSQL (Railway)
-- Migrado de SQLite. Idempotente: usa IF NOT EXISTS em todas as instruções.
-- Aplicado automaticamente no boot via db.init_schema().

-- ---------------------------------------------------------------------------
-- 1. jobs (job_store.py)
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS jobs (
    id                  BIGSERIAL PRIMARY KEY,
    source_type         TEXT        NOT NULL,
    source_identifier   TEXT        NOT NULL,
    content_hash        TEXT        NOT NULL,
    job_type            TEXT        NOT NULL DEFAULT 'legacy_sync',
    payload_json        TEXT,
    status              TEXT        NOT NULL,
    created_at          TEXT        NOT NULL DEFAULT to_char(now() AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"'),
    updated_at          TEXT        NOT NULL DEFAULT to_char(now() AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"'),
    error_message       TEXT,
    skip_reason         TEXT,
    result_summary      TEXT,
    total_records       INTEGER,
    processed_records   INTEGER,
    retry_count         INTEGER     NOT NULL DEFAULT 0,
    attempt_count       INTEGER     NOT NULL DEFAULT 0,
    max_attempts        INTEGER     NOT NULL DEFAULT 4,
    error_type          TEXT,
    last_error          TEXT,
    next_retry_at       TEXT,
    last_attempt_at     TEXT
);

CREATE INDEX IF NOT EXISTS idx_jobs_status
    ON jobs (status);

CREATE INDEX IF NOT EXISTS idx_jobs_hash_source
    ON jobs (content_hash, source_type, source_identifier);

CREATE INDEX IF NOT EXISTS idx_jobs_status_next_retry
    ON jobs (status, next_retry_at);

CREATE INDEX IF NOT EXISTS idx_jobs_type_hash_source
    ON jobs (job_type, content_hash, source_type, source_identifier);


-- ---------------------------------------------------------------------------
-- 2. lote_itens (lote_itens_store.py)
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS lote_itens (
    lote_id       TEXT    NOT NULL PRIMARY KEY,
    itens_json    TEXT    NOT NULL,
    total_itens   INTEGER NOT NULL,
    hash_itens    TEXT    NOT NULL,
    criado_em     TEXT    NOT NULL DEFAULT to_char(now() AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"'),
    atualizado_em TEXT    NOT NULL DEFAULT to_char(now() AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"')
);


-- ---------------------------------------------------------------------------
-- 3. validacoes_lote (validacao_lote_store.py)
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS validacoes_lote (
    lote_id               TEXT    NOT NULL PRIMARY KEY,
    job_id                INTEGER,
    snapshot_hash         TEXT    NOT NULL,
    status                TEXT    NOT NULL,
    resumo                TEXT    NOT NULL,
    avisos                TEXT    NOT NULL,
    erros                 TEXT    NOT NULL,
    pendencias            TEXT    NOT NULL DEFAULT '[]',
    apto_para_aprovacao   INTEGER NOT NULL,
    resultados_validacao  TEXT    NOT NULL,
    itens_sendaveis       TEXT    NOT NULL,
    versao                INTEGER NOT NULL DEFAULT 1,
    expires_at            TEXT,
    created_at            TEXT    NOT NULL DEFAULT to_char(now() AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"'),
    updated_at            TEXT    NOT NULL DEFAULT to_char(now() AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"')
);


-- ---------------------------------------------------------------------------
-- 4. aprovacoes_lote (aprovacao_lote_store.py)
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS aprovacoes_lote (
    lote_id                     TEXT    NOT NULL PRIMARY KEY,
    status                      TEXT    NOT NULL,
    elegivel_para_aprovacao     INTEGER NOT NULL,
    resumo_atual                TEXT    NOT NULL,
    aprovado_por                TEXT,
    aprovador_nome_informado    TEXT,
    aprovador_email             TEXT,
    aprovador_origem            TEXT,
    aprovador_identity_strength TEXT,
    aprovado_em                 TEXT,
    rejeitado_por               TEXT,
    rejeitado_em                TEXT,
    motivo_rejeicao             TEXT,
    snapshot_resumo_aprovado    TEXT,
    hash_resumo_aprovado        TEXT,
    criado_em                   TEXT    NOT NULL DEFAULT to_char(now() AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"'),
    atualizado_em               TEXT    NOT NULL DEFAULT to_char(now() AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"')
);


-- ---------------------------------------------------------------------------
-- 5. envio_lote_audit (envio_lote_audit_store.py)
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS envio_lote_audit (
    id              BIGSERIAL   PRIMARY KEY,
    lote_id         TEXT        NOT NULL,
    item_key        TEXT        NOT NULL,
    estudante       TEXT,
    componente      TEXT,
    disciplina      TEXT,
    trimestre       TEXT,
    valor_bruta     REAL,
    id_matricula    INTEGER,
    id_disciplina   INTEGER,
    id_avaliacao    INTEGER,
    id_professor    INTEGER,
    dry_run         INTEGER     NOT NULL,
    status          TEXT        NOT NULL,
    mensagem        TEXT,
    transitorio     INTEGER     NOT NULL DEFAULT 0,
    payload_enviado TEXT,
    resposta_api    TEXT,
    erros_resolucao TEXT,
    rastreabilidade TEXT,
    timestamp       TEXT        NOT NULL,
    criado_em       TEXT        NOT NULL DEFAULT to_char(now() AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"'),
    atualizado_em   TEXT        NOT NULL DEFAULT to_char(now() AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"'),
    UNIQUE (lote_id, item_key)
);

CREATE INDEX IF NOT EXISTS idx_envio_lote_audit_lote_status
    ON envio_lote_audit (lote_id, status);

CREATE INDEX IF NOT EXISTS idx_envio_lote_audit_criado_em
    ON envio_lote_audit (criado_em);


-- ---------------------------------------------------------------------------
-- 5b. API Lumni (webhook_google_sheets.py) — camada de leitura
-- ---------------------------------------------------------------------------

-- Índices parciais para as consultas da API Lumni (por aluno e por disciplina).
-- Parciais de propósito: indexam apenas o subconjunto de notas confirmadas
-- (status='enviado' AND dry_run=0), que é exatamente o que a API lê.
CREATE INDEX IF NOT EXISTS idx_envio_lote_audit_lumni_matricula
    ON envio_lote_audit (id_matricula)
    WHERE status = 'enviado' AND dry_run = 0;

CREATE INDEX IF NOT EXISTS idx_envio_lote_audit_lumni_disciplina
    ON envio_lote_audit (id_disciplina)
    WHERE status = 'enviado' AND dry_run = 0;

-- vw_notas_confirmadas: fonte de leitura dos endpoints /api/v1/notas/aluno e
-- /api/v1/notas/disciplina. Encapsula em um único lugar a definição de
-- "nota confirmada" (status='enviado' AND dry_run=0) e o dedup "latest-wins":
-- quando uma nota é corrigida e reenviada em um lote posterior, vale a linha
-- de maior criado_em (desempate por id para reenvios no mesmo segundo).
--
-- Sobre a ordenação por criado_em (TEXT): a ordenação lexicográfica é segura
-- porque o campo é gravado EXCLUSIVAMENTE pelo próprio Postgres, no formato
-- fixo to_char(now() AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"') — ver
-- o DEFAULT da coluna acima e envio_lote_audit_store._UPSERT (único escritor).
-- Formato constante + sempre UTC + precisão de segundos ⇒ ordem lexicográfica
-- coincide com a cronológica. Recomendação futura: migrar a coluna para
-- TIMESTAMPTZ quando houver janela de manutenção (não executar a quente).
CREATE OR REPLACE VIEW vw_notas_confirmadas AS
SELECT DISTINCT ON (id_matricula, id_disciplina, trimestre, componente)
    id_matricula,
    estudante,
    id_disciplina,
    disciplina,
    trimestre,
    componente,
    valor_bruta,
    id_avaliacao,
    lote_id,
    criado_em
FROM envio_lote_audit
WHERE status = 'enviado'
  AND dry_run = 0
ORDER BY id_matricula, id_disciplina, trimestre, componente,
         criado_em DESC, id DESC;


-- ---------------------------------------------------------------------------
-- 6. resultados_envio_lote (resultado_envio_lote_store.py)
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS resultados_envio_lote (
    lote_id                     TEXT    NOT NULL PRIMARY KEY,
    job_id                      INTEGER,
    snapshot_hash               TEXT    NOT NULL,
    status                      TEXT    NOT NULL,
    aprovado_por                TEXT,
    aprovador_nome_informado    TEXT,
    aprovador_email             TEXT,
    aprovador_origem            TEXT,
    aprovador_identity_strength TEXT,
    sucesso                     INTEGER NOT NULL,
    quantidade_enviada          INTEGER NOT NULL,
    quantidade_com_erro         INTEGER NOT NULL,
    total_sendaveis             INTEGER NOT NULL,
    total_dry_run               INTEGER NOT NULL,
    total_erros_resolucao       INTEGER NOT NULL,
    total_erros_envio           INTEGER NOT NULL,
    mensagem                    TEXT,
    resumo                      TEXT    NOT NULL,
    auditoria_resumo            TEXT    NOT NULL,
    finished_at                 TEXT,
    created_at                  TEXT    NOT NULL DEFAULT to_char(now() AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"'),
    updated_at                  TEXT    NOT NULL DEFAULT to_char(now() AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"')
);

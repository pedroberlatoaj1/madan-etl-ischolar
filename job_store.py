"""
job_store.py — Camada de persistência de jobs de sincronização (SQLite).

Responsável por:
- inicializar banco SQLite
- criar tabela de jobs (se não existir)
- inserir job
- buscar jobs pendentes
- atualizar status e contadores
- registrar erro
- marcar job como skipped
- verificar se um hash já foi processado com sucesso
"""

from __future__ import annotations

import sqlite3
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Iterable, List, Optional, Callable, TypeVar

from config import config
from constants import JobStatus, ErrorType
from logger import configurar_logger
from alertas import alertar_falha_definitiva


log = configurar_logger("etl.job_store")

_INIT_LOCK = threading.Lock()
_INITIALIZED = False


T = TypeVar("T")


class JobStoreError(Exception):
    """Erro genérico da camada de persistência de jobs."""


@dataclass
class Job:
    id: Optional[int]
    source_type: str
    source_identifier: str
    content_hash: str
    status: str
    created_at: str
    updated_at: str
    error_message: Optional[str] = None
    skip_reason: Optional[str] = None
    # Resumo do resultado de execução (ex.: "Criadas: X | Puladas: Y | ...")
    # Útil para lotes idempotentes que concluem deterministicamente com ressalvas.
    result_summary: Optional[str] = None
    total_records: Optional[int] = None
    processed_records: Optional[int] = None
    # retry_count: usado EXCLUSIVAMENTE por stale recovery para contar
    # quantas vezes um job foi devolvido de 'processing' para 'pending'
    # após timeout (worker morto). Não interfere no retry automático.
    retry_count: int = 0
    # attempt_count/max_attempts: usados EXCLUSIVAMENTE pelo retry automático
    # de processamento/envio (worker.py). Cada vez que um job é reivindicado
    # com sucesso via claim_next_pending_job, attempt_count é incrementado
    # e o backoff progressivo é calculado com base nele.
    attempt_count: int = 0
    max_attempts: int = 4
    error_type: Optional[str] = None  # "transient" | "permanent" | "exhausted" | None
    last_error: Optional[str] = None
    next_retry_at: Optional[str] = None  # ISO UTC (string). Se > agora, não é elegível.
    last_attempt_at: Optional[str] = None  # ISO UTC do início da tentativa atual


def _agora_iso() -> str:
    """Retorna timestamp UTC em ISO 8601 (sem microssegundos)."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _conectar() -> sqlite3.Connection:
    """
    Abre uma conexão com o banco de jobs com configurações robustas para concorrência.

    - timeout: aguarda alguns segundos antes de falhar em disputas curtas de lock.
    - journal_mode=WAL: melhor convivência entre leitura/escrita (worker + webhook).
    - synchronous=NORMAL: equilíbrio entre durabilidade e desempenho.
    """
    try:
        conn = sqlite3.connect(
            getattr(config, "JOB_DB_PATH", "jobs.sqlite3"),
            timeout=5.0,
            isolation_level=None,  # autocommit com BEGIN explícito
        )
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL;")
        cur.execute("PRAGMA synchronous=NORMAL;")
        cur.close()
        return conn
    except sqlite3.Error as exc:
        log.exception("❌ Falha ao conectar ao banco de jobs: %s", exc)
        raise JobStoreError("Falha ao conectar ao banco de jobs") from exc


def _with_lock_retry(
    operation: Callable[[sqlite3.Connection], T],
    *,
    op_name: str,
    max_tries: int = 3,
    initial_backoff: float = 0.1,
) -> T:
    """
    Executa uma operação de banco com retry curto em caso de `database is locked`.

    Política:
      - Até max_tries tentativas (1 inicial + 2 retries, por padrão).
      - Backoff exponencial simples entre tentativas (100ms, ~250ms, ~625ms).
      - Apenas erros contendo "database is locked" entram em retry.
      - Outros erros são propagados como JobStoreError sem retry extra.
    """
    init_db()
    conn = _conectar()
    try:
        backoff = initial_backoff
        for tentativa in range(max_tries):
            try:
                return operation(conn)
            except sqlite3.OperationalError as exc:
                is_locked = "database is locked" in str(exc).lower()
                if is_locked and tentativa < max_tries - 1:
                    log.debug(
                        "Database locked em %s; retry em %.3fs (tentativa %d/%d).",
                        op_name,
                        backoff,
                        tentativa + 1,
                        max_tries,
                    )
                    try:
                        conn.execute("ROLLBACK")
                    except Exception:
                        pass
                    time.sleep(backoff)
                    backoff *= 2.5
                    continue

                try:
                    conn.execute("ROLLBACK")
                except Exception:
                    pass
                log.exception("❌ Erro em operação SQLite (%s): %s", op_name, exc)
                raise JobStoreError(f"Erro em operação SQLite ({op_name})") from exc
    finally:
        conn.close()


def _row_to_job(row: sqlite3.Row) -> Job:
    """Converte uma sqlite3.Row no dataclass Job."""
    return Job(
        id=row["id"],
        source_type=row["source_type"],
        source_identifier=row["source_identifier"],
        content_hash=row["content_hash"],
        status=row["status"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        error_message=row["error_message"],
        skip_reason=row["skip_reason"],
        result_summary=row["result_summary"] if "result_summary" in row.keys() else None,
        total_records=row["total_records"],
        processed_records=row["processed_records"],
        retry_count=row["retry_count"],
        attempt_count=row["attempt_count"] if "attempt_count" in row.keys() else 0,
        max_attempts=row["max_attempts"] if "max_attempts" in row.keys() else 4,
        error_type=row["error_type"] if "error_type" in row.keys() else None,
        last_error=row["last_error"] if "last_error" in row.keys() else None,
        next_retry_at=row["next_retry_at"] if "next_retry_at" in row.keys() else None,
        last_attempt_at=row["last_attempt_at"] if "last_attempt_at" in row.keys() else None,
    )


def _migrate_add_skip_reason(conn: sqlite3.Connection) -> None:
    """Adiciona coluna skip_reason em bancos existentes (migração incremental)."""
    cur = conn.execute("PRAGMA table_info(jobs)")
    colunas = {row["name"] for row in cur.fetchall()}
    if "skip_reason" in colunas:
        return

    log.info("🔄 Migrando schema: adicionando coluna skip_reason...")
    conn.execute("BEGIN")
    conn.execute("ALTER TABLE jobs ADD COLUMN skip_reason TEXT")
    conn.execute(
        "UPDATE jobs SET skip_reason = error_message, error_message = NULL "
        "WHERE status = 'skipped' AND error_message IS NOT NULL"
    )
    conn.execute("COMMIT")
    log.info("✅ Migração skip_reason concluída.")


def _migrate_add_retry_metadata(conn: sqlite3.Connection) -> None:
    """
    Adiciona colunas de retry automático em bancos existentes (migração incremental).

    Defaults seguros para compatibilidade:
    - attempt_count: 0
    - max_attempts: 4
    - next_retry_at: NULL (job pendente segue elegível)
    """
    cur = conn.execute("PRAGMA table_info(jobs)")
    colunas = {row["name"] for row in cur.fetchall()}

    novas_colunas: list[tuple[str, str]] = []
    if "attempt_count" not in colunas:
        novas_colunas.append(("attempt_count", "INTEGER NOT NULL DEFAULT 0"))
    if "max_attempts" not in colunas:
        novas_colunas.append(("max_attempts", "INTEGER NOT NULL DEFAULT 4"))
    if "error_type" not in colunas:
        novas_colunas.append(("error_type", "TEXT"))
    if "last_error" not in colunas:
        novas_colunas.append(("last_error", "TEXT"))
    if "next_retry_at" not in colunas:
        novas_colunas.append(("next_retry_at", "TEXT"))
    if "last_attempt_at" not in colunas:
        novas_colunas.append(("last_attempt_at", "TEXT"))

    if not novas_colunas:
        return

    log.info(
        "🔄 Migrando schema: adicionando colunas de retry automático (%d)...",
        len(novas_colunas),
    )
    conn.execute("BEGIN")
    for nome, ddl in novas_colunas:
        conn.execute(f"ALTER TABLE jobs ADD COLUMN {nome} {ddl}")
    conn.execute("COMMIT")
    log.info("✅ Migração de retry automático concluída.")


def _migrate_add_result_summary(conn: sqlite3.Connection) -> None:
    """Adiciona coluna result_summary para guardar resumo do lote (migração incremental)."""
    cur = conn.execute("PRAGMA table_info(jobs)")
    colunas = {row["name"] for row in cur.fetchall()}
    if "result_summary" in colunas:
        return

    log.info("🔄 Migrando schema: adicionando coluna result_summary...")
    conn.execute("BEGIN")
    conn.execute("ALTER TABLE jobs ADD COLUMN result_summary TEXT")
    conn.execute("COMMIT")
    log.info("✅ Migração result_summary concluída.")


def init_db() -> None:
    """Inicializa o banco de dados e cria a tabela de jobs, se necessário."""
    global _INITIALIZED
    if _INITIALIZED:
        return

    with _INIT_LOCK:
        if _INITIALIZED:
            return

        conn = _conectar()
        try:
            conn.execute("BEGIN")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_type TEXT NOT NULL,
                    source_identifier TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    error_message TEXT,
                    skip_reason TEXT,
                    result_summary TEXT,
                    total_records INTEGER,
                    processed_records INTEGER,
                    retry_count INTEGER NOT NULL DEFAULT 0,
                    attempt_count INTEGER NOT NULL DEFAULT 0,
                    max_attempts INTEGER NOT NULL DEFAULT 4,
                    error_type TEXT,
                    last_error TEXT,
                    next_retry_at TEXT,
                    last_attempt_at TEXT
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_jobs_status
                    ON jobs (status);
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_jobs_hash_source
                    ON jobs (content_hash, source_type, source_identifier);
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_jobs_status_next_retry
                    ON jobs (status, next_retry_at);
                """
            )
            conn.execute("COMMIT")
            _migrate_add_skip_reason(conn)
            _migrate_add_retry_metadata(conn)
            _migrate_add_result_summary(conn)
            _INITIALIZED = True
            log.info("🗄️ Banco de jobs inicializado com sucesso.")
        except sqlite3.Error as exc:
            conn.execute("ROLLBACK")
            log.exception("❌ Erro ao inicializar banco de jobs: %s", exc)
            raise JobStoreError("Erro ao inicializar banco de jobs") from exc
        finally:
            conn.close()


def criar_job(
    source_type: str,
    source_identifier: str,
    content_hash: str,
    total_records: Optional[int] = None,
) -> Job:
    """
    Cria um novo job com status 'pending'.

    Retorna o objeto Job criado (com id preenchido).
    """
    agora = _agora_iso()

    def _op(conn: sqlite3.Connection) -> Job:
        conn.execute("BEGIN")
        cur = conn.execute(
            """
            INSERT INTO jobs (
                source_type,
                source_identifier,
                content_hash,
                status,
                created_at,
                updated_at,
                total_records,
                processed_records,
                retry_count
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0)
            """,
            (
                source_type,
                source_identifier,
                content_hash,
                JobStatus.PENDING,
                agora,
                agora,
                total_records,
                0 if total_records is not None else None,
            ),
        )
        job_id = cur.lastrowid
        conn.execute("COMMIT")
        job = Job(
            id=job_id,
            source_type=source_type,
            source_identifier=source_identifier,
            content_hash=content_hash,
            status="pending",
            created_at=agora,
            updated_at=agora,
            total_records=total_records,
            processed_records=0 if total_records is not None else None,
            retry_count=0,
        )
        log.info(
            "📌 Job criado | id=%s | source_type=%s | source_identifier=%s",
            job_id,
            source_type,
            source_identifier,
        )
        return job

    return _with_lock_retry(_op, op_name="criar_job")


def buscar_jobs_pendentes(limit: int = 50) -> List[Job]:
    """
    Retorna a lista de jobs com status 'pending', ordenados por created_at.

    Importante: esta função é voltada para inspeção/uso administrativo e
    NÃO aplica a lógica de elegibilidade por next_retry_at. Ou seja, ela
    pode incluir jobs pendentes cujo next_retry_at ainda esteja no futuro.

    Para o consumo real da fila pelo worker (jobs elegíveis), usar
    claim_next_pending_job(), que já respeita next_retry_at.
    """
    init_db()
    conn = _conectar()
    try:
        cur = conn.execute(
            """
            SELECT *
            FROM jobs
            WHERE status = ?
            ORDER BY created_at ASC
            LIMIT ?
            """,
            (JobStatus.PENDING, limit),
        )
        rows = cur.fetchall()
        return [_row_to_job(row) for row in rows]
    except sqlite3.Error as exc:
        log.exception("❌ Erro ao buscar jobs pendentes: %s", exc)
        raise JobStoreError("Erro ao buscar jobs pendentes") from exc
    finally:
        conn.close()


def atualizar_status(
    job_id: int,
    novo_status: str,
    *,
    processed_records: Optional[int] = None,
    total_records: Optional[int] = None,
    increment_retry: bool = False,
) -> None:
    """
    Atualiza status do job e opcionalmente counters e retry_count.
    """
    agora = _agora_iso()

    def _op(conn: sqlite3.Connection) -> None:
        conn.execute("BEGIN")

        campos: list[str] = ["status = ?", "updated_at = ?"]
        valores: list[object] = [novo_status, agora]

        if processed_records is not None:
            campos.append("processed_records = ?")
            valores.append(processed_records)
        if total_records is not None:
            campos.append("total_records = ?")
            valores.append(total_records)
        if increment_retry:
            campos.append("retry_count = retry_count + 1")

        valores.append(job_id)

        sql = f"UPDATE jobs SET {', '.join(campos)} WHERE id = ?"
        conn.execute(sql, tuple(valores))
        conn.execute("COMMIT")
        log.info("🔄 Job %s atualizado para status='%s'.", job_id, novo_status)

    _with_lock_retry(_op, op_name="atualizar_status")


def atualizar_heartbeat(job_id: int) -> None:
    """
    Atualiza apenas updated_at do job (heartbeat para jobs longos).

    Evita que o job seja considerado stale durante processamento demorado
    (ex.: transformação pesada ou envio HTTP lento). Chamar em pontos seguros
    do fluxo, sem alterar status nem outros campos.
    """
    init_db()
    agora = _agora_iso()
    conn = _conectar()
    try:
        conn.execute("BEGIN")
        conn.execute(
            "UPDATE jobs SET updated_at = ? WHERE id = ?",
            (agora, job_id),
        )
        conn.execute("COMMIT")
    except sqlite3.Error as exc:
        try:
            conn.execute("ROLLBACK")
        except Exception:
            pass
        log.debug("Heartbeat job %s falhou (não crítico): %s", job_id, exc)
    finally:
        conn.close()


def registrar_erro(job_id: int, mensagem: str) -> None:
    """Registra mensagem de erro e marca status como 'error'."""
    init_db()
    agora = _agora_iso()
    conn = _conectar()
    try:
        conn.execute("BEGIN")
        conn.execute(
            """
            UPDATE jobs
            SET status = ?,
                error_message = ?,
                result_summary = NULL,
                last_error = ?,
                error_type = COALESCE(error_type, 'permanent'),
                next_retry_at = NULL,
                updated_at = ?
            WHERE id = ?
            """,
            (JobStatus.ERROR, mensagem[:1000], mensagem[:1000], agora, job_id),
        )
        conn.execute("COMMIT")
        log.error("💥 Job %s marcado como error: %s", job_id, mensagem)
    except sqlite3.Error as exc:
        conn.execute("ROLLBACK")
        log.exception("❌ Erro ao registrar erro do job %s: %s", job_id, exc)
        raise JobStoreError("Erro ao registrar erro do job") from exc
    finally:
        conn.close()


def marcar_skipped(job_id: int, motivo: str | None = None) -> None:
    """Marca job como 'skipped' e registra motivo em skip_reason."""
    init_db()
    agora = _agora_iso()
    conn = _conectar()
    try:
        conn.execute("BEGIN")
        conn.execute(
            """
            UPDATE jobs
            SET status = 'skipped',
                skip_reason = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (motivo[:500] if motivo else None, agora, job_id),
        )
        conn.execute("COMMIT")
        log.info("⏭️ Job %s marcado como skipped. Motivo: %s", job_id, motivo)
    except sqlite3.Error as exc:
        conn.execute("ROLLBACK")
        log.exception("❌ Erro ao marcar job %s como skipped: %s", job_id, exc)
        raise JobStoreError("Erro ao marcar job como skipped") from exc
    finally:
        conn.close()


def agendar_retry(
    job_id: int,
    *,
    next_retry_at: str,
    last_error: str,
    error_type: str = ErrorType.TRANSIENT,
) -> None:
    """
    Reagenda um job para retry (status volta para 'pending' com next_retry_at futuro).

    Importante: next_retry_at deve ser > agora para evitar loop apertado.
    """
    agora = _agora_iso()

    def _op(conn: sqlite3.Connection) -> None:
        conn.execute("BEGIN")
        conn.execute(
            """
            UPDATE jobs
            SET status = 'pending',
                error_type = ?,
                last_error = ?,
                error_message = ?,
                result_summary = NULL,
                next_retry_at = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (
                error_type,
                last_error[:1000],
                last_error[:1000],
                next_retry_at,
                agora,
                job_id,
            ),
        )
        conn.execute("COMMIT")
        log.warning(
            "⏳ Job %s reagendado para retry | error_type=%s | next_retry_at=%s",
            job_id,
            error_type,
            next_retry_at,
        )

    _with_lock_retry(_op, op_name="agendar_retry")


def marcar_falha_definitiva(
    job_id: int,
    *,
    last_error: str,
    error_type: str = ErrorType.PERMANENT,
) -> None:
    """Marca job como 'error' sem reagendar (falha definitiva)."""
    agora = _agora_iso()

    def _op(conn: sqlite3.Connection) -> None:
        conn.execute("BEGIN")
        conn.execute(
            """
            UPDATE jobs
            SET status = ?,
                error_type = ?,
                last_error = ?,
                error_message = ?,
                result_summary = NULL,
                next_retry_at = NULL,
                updated_at = ?
            WHERE id = ?
            """,
            (
                JobStatus.ERROR,
                error_type,
                last_error[:1000],
                last_error[:1000],
                agora,
                job_id,
            ),
        )
        conn.execute("COMMIT")
        log.error(
            "💥 Job %s falha definitiva | error_type=%s | %s",
            job_id,
            error_type,
            last_error,
        )

    _with_lock_retry(_op, op_name="marcar_falha_definitiva")


def marcar_sucesso(
    job_id: int,
    *,
    processed_records: int,
    total_records: int,
    result_summary: Optional[str] = None,
) -> None:
    """Marca job como success e limpa estado de erro/retry."""
    agora = _agora_iso()

    def _op(conn: sqlite3.Connection) -> None:
        conn.execute("BEGIN")
        conn.execute(
            """
            UPDATE jobs
            SET status = ?,
                processed_records = ?,
                total_records = ?,
                result_summary = ?,
                error_message = NULL,
                error_type = NULL,
                last_error = NULL,
                next_retry_at = NULL,
                updated_at = ?
            WHERE id = ?
            """,
            (
                JobStatus.SUCCESS,
                processed_records,
                total_records,
                (result_summary[:1000] if result_summary else None),
                agora,
                job_id,
            ),
        )
        conn.execute("COMMIT")
        log.info("✅ Job %s atualizado para status='success'.", job_id)

    _with_lock_retry(_op, op_name="marcar_sucesso")


def _idempotency_ja_sucesso(
    conn: sqlite3.Connection,
    mode: str,
    source_type: str,
    source_identifier: str,
    content_hash: str,
) -> bool:
    """
    Verifica se já existe job com status 'success' conforme a política de idempotência.

    - content_only: qualquer job success com o mesmo content_hash → True.
    - content_and_source: job success com mesmo (source_type, source_identifier, content_hash) → True.
    """
    mode = (mode or "content_and_source").strip().lower()
    if mode == "content_only":
        cur = conn.execute(
            "SELECT 1 FROM jobs WHERE content_hash = ? AND status = 'success' LIMIT 1",
            (content_hash,),
        )
    else:
        cur = conn.execute(
            """
            SELECT 1 FROM jobs
            WHERE source_type = ? AND source_identifier = ? AND content_hash = ?
              AND status = 'success'
            LIMIT 1
            """,
            (source_type, source_identifier, content_hash),
        )
    return cur.fetchone() is not None


def hash_ja_processado_com_sucesso(
    source_type: str,
    source_identifier: str,
    content_hash: str,
) -> bool:
    """
    Verifica se já existe job bem-sucedido conforme config.IDEMPOTENCY_MODE.

    - content_only: mesmo conteúdo em qualquer origem já processado → True.
    - content_and_source: mesmo conteúdo na mesma origem já processado → True.
    """
    init_db()
    mode = getattr(config, "IDEMPOTENCY_MODE", "content_and_source")
    conn = _conectar()
    try:
        achou = _idempotency_ja_sucesso(
            conn, mode, source_type, source_identifier, content_hash
        )
        if achou:
            log.info(
                "♻️ Conteúdo já processado com sucesso (idempotência: %s) | source_type=%s | source_identifier=%s",
                mode,
                source_type,
                source_identifier,
            )
        return achou
    except sqlite3.Error as exc:
        log.exception(
            "❌ Erro ao verificar hash já processado (source_type=%s, source_identifier=%s): %s",
            source_type,
            source_identifier,
            exc,
        )
        raise JobStoreError("Erro ao verificar hash já processado") from exc
    finally:
        conn.close()


def criar_job_com_idempotencia(
    source_type: str,
    source_identifier: str,
    content_hash: str,
    total_records: Optional[int] = None,
) -> Job:
    """
    Cria um job com idempotência conforme config.IDEMPOTENCY_MODE.

    - content_and_source: se já existir job 'success' para o mesmo
      (source_type, source_identifier, content_hash) → novo job com status 'skipped'.
    - content_only: se já existir job 'success' com o mesmo content_hash
      (qualquer origem) → novo job com status 'skipped'.
    Caso contrário → cria job 'pending' normal.
    """
    mode = getattr(config, "IDEMPOTENCY_MODE", "content_and_source")
    agora = _agora_iso()

    def _op(conn: sqlite3.Connection) -> Job:
        conn.execute("BEGIN")

        ja_sucesso = _idempotency_ja_sucesso(
            conn, mode, source_type, source_identifier, content_hash
        )

        status_inicial = JobStatus.SKIPPED if ja_sucesso else JobStatus.PENDING
        processed_records = 0 if (total_records is not None and not ja_sucesso) else None

        cur = conn.execute(
            """
            INSERT INTO jobs (
                source_type,
                source_identifier,
                content_hash,
                status,
                created_at,
                updated_at,
                skip_reason,
                total_records,
                processed_records,
                retry_count
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
            """,
            (
                source_type,
                source_identifier,
                content_hash,
                status_inicial,
                agora,
                agora,
                "Conteúdo já processado anteriormente com sucesso."
                if ja_sucesso
                else None,
                total_records,
                processed_records,
            ),
        )
        job_id = cur.lastrowid
        conn.execute("COMMIT")

        job = Job(
            id=job_id,
            source_type=source_type,
            source_identifier=source_identifier,
            content_hash=content_hash,
            status=status_inicial,
            created_at=agora,
            updated_at=agora,
            skip_reason=(
                "Conteúdo já processado anteriormente com sucesso." if ja_sucesso else None
            ),
            total_records=total_records,
            processed_records=processed_records,
            retry_count=0,
        )

        if ja_sucesso:
            log.info(
                "⏭️ Job %s criado como skipped (idempotência: %s) | source_type=%s | source_identifier=%s",
                job_id,
                mode,
                source_type,
                source_identifier,
            )
        else:
            log.info(
                "📌 Job %s criado como pending | source_type=%s | source_identifier=%s",
                job_id,
                source_type,
                source_identifier,
            )

        return job

    return _with_lock_retry(_op, op_name="criar_job_com_idempotencia")


def obter_job_por_id(job_id: int) -> Optional[Job]:
    """Obtém um job específico pelo ID."""
    init_db()
    conn = _conectar()
    try:
        cur = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,))
        row = cur.fetchone()
        if row is None:
            return None
        return _row_to_job(row)
    except sqlite3.Error as exc:
        log.exception("❌ Erro ao obter job %s: %s", job_id, exc)
        raise JobStoreError("Erro ao obter job") from exc
    finally:
        conn.close()


def obter_contagem_jobs_por_status() -> dict[str, int]:
    """Retorna a contagem de jobs agrupados por status."""
    init_db()
    conn = _conectar()
    try:
        cur = conn.execute(
            "SELECT status, COUNT(*) as total FROM jobs GROUP BY status"
        )
        return {row["status"]: int(row["total"]) for row in cur.fetchall()}
    except sqlite3.Error as exc:
        log.exception("❌ Erro ao obter contagem de jobs por status: %s", exc)
        raise JobStoreError("Erro ao obter contagem de jobs por status") from exc
    finally:
        conn.close()


def obter_contagem_jobs_por_error_type() -> dict[str, int]:
    """Retorna a contagem de jobs agrupados por error_type (apenas não nulos)."""
    init_db()
    conn = _conectar()
    try:
        cur = conn.execute(
            "SELECT error_type, COUNT(*) as total FROM jobs "
            "WHERE error_type IS NOT NULL GROUP BY error_type"
        )
        return {row["error_type"]: int(row["total"]) for row in cur.fetchall()}
    except sqlite3.Error as exc:
        log.exception("❌ Erro ao obter contagem de jobs por error_type: %s", exc)
        raise JobStoreError("Erro ao obter contagem de jobs por error_type") from exc
    finally:
        conn.close()


def obter_job_pendente_mais_antigo() -> Optional[Job]:
    """
    Retorna o job com status 'pending' mais antigo por created_at.

    Atenção: assim como buscar_jobs_pendentes(), esta função não considera
    next_retry_at; é útil para inspeção manual de envelhecimento da fila.
    """
    init_db()
    conn = _conectar()
    try:
        cur = conn.execute(
            """
            SELECT *
            FROM jobs
            WHERE status = ?
            ORDER BY created_at ASC
            LIMIT 1
            """
            ,
            (JobStatus.PENDING,),
        )
        row = cur.fetchone()
        if row is None:
            return None
        return _row_to_job(row)
    except sqlite3.Error as exc:
        log.exception("❌ Erro ao obter job pendente mais antigo: %s", exc)
        raise JobStoreError("Erro ao obter job pendente mais antigo") from exc
    finally:
        conn.close()


def obter_ultima_execucao_com_sucesso() -> Optional[str]:
    """
    Retorna o timestamp ISO (updated_at) da última execução bem-sucedida (status='success').
    """
    init_db()
    conn = _conectar()
    try:
        cur = conn.execute(
            "SELECT MAX(updated_at) AS last_success FROM jobs WHERE status = ?",
            (JobStatus.SUCCESS,),
        )
        row = cur.fetchone()
        return row["last_success"]
    except sqlite3.Error as exc:
        log.exception("❌ Erro ao obter última execução com sucesso: %s", exc)
        raise JobStoreError("Erro ao obter última execução com sucesso") from exc
    finally:
        conn.close()


def obter_estatisticas_recentes(janela_minutos: int = 60) -> dict[str, int]:
    """
    Retorna estatísticas simples de retries/exhausted em uma janela recente.

    - retries: jobs com attempt_count > 1 na janela (qualquer status).
    - exhausted: jobs com status='error' e error_type='exhausted' na janela.
    """
    init_db()
    cutoff_dt = datetime.now(timezone.utc) - timedelta(minutes=janela_minutos)
    cutoff = cutoff_dt.replace(microsecond=0).isoformat()

    conn = _conectar()
    try:
        cur = conn.execute(
            "SELECT COUNT(*) AS total FROM jobs "
            "WHERE attempt_count > 1 AND updated_at >= ?",
            (cutoff,),
        )
        retries = int(cur.fetchone()["total"])

        cur = conn.execute(
            "SELECT COUNT(*) AS total FROM jobs "
            "WHERE status = ? AND error_type = ? AND updated_at >= ?",
            (JobStatus.ERROR, ErrorType.EXHAUSTED, cutoff),
        )
        exhausted = int(cur.fetchone()["total"])

        return {
            "retries": retries,
            "exhausted": exhausted,
        }
    except sqlite3.Error as exc:
        log.exception("❌ Erro ao obter estatísticas recentes: %s", exc)
        raise JobStoreError("Erro ao obter estatísticas recentes") from exc
    finally:
        conn.close()


def listar_jobs_por_status(statuses: Iterable[str]) -> List[Job]:
    """Lista jobs filtrando por um ou mais status."""
    init_db()
    conn = _conectar()
    try:
        placeholders = ",".join("?" for _ in statuses)
        sql = f"SELECT * FROM jobs WHERE status IN ({placeholders}) ORDER BY created_at DESC"
        cur = conn.execute(sql, tuple(statuses))
        rows = cur.fetchall()
        return [_row_to_job(row) for row in rows]
    except sqlite3.Error as exc:
        log.exception("❌ Erro ao listar jobs por status: %s", exc)
        raise JobStoreError("Erro ao listar jobs por status") from exc
    finally:
        conn.close()


def claim_next_pending_job() -> Optional[Job]:
    """
    Reivindica atomicamente o próximo job pendente (pending → processing).

    Estratégia transacional:
      BEGIN IMMEDIATE adquire um lock RESERVED no arquivo SQLite,
      impedindo que outra conexão inicie escrita simultânea.
      Dentro da transação: SELECT do próximo pending → UPDATE para
      processing → SELECT completo do job. Se não houver pending,
      retorna None sem alterar nada.

    Resultado: mesmo com múltiplos workers, cada job é reivindicado
    por exatamente um processo.
    """
    agora = _agora_iso()

    def _op(conn: sqlite3.Connection) -> Optional[Job]:
        conn.execute("BEGIN IMMEDIATE")
        cur = conn.execute(
            """
            SELECT id
            FROM jobs
            WHERE status = 'pending'
              AND (next_retry_at IS NULL OR next_retry_at <= ?)
            ORDER BY created_at ASC
            LIMIT 1
            """,
            (agora,),
        )
        row = cur.fetchone()
        if row is None:
            conn.execute("COMMIT")
            return None

        job_id = row["id"]
        conn.execute(
            """
            UPDATE jobs
            SET status = 'processing',
                updated_at = ?,
                last_attempt_at = ?,
                attempt_count = attempt_count + 1
            WHERE id = ?
            """,
            (agora, agora, job_id),
        )
        cur = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,))
        row = cur.fetchone()
        conn.execute("COMMIT")

        job = _row_to_job(row)
        log.info(
            "🔒 Job %s reivindicado (pending → processing) | source=%s",
            job_id,
            job.source_identifier,
        )
        return job

    return _with_lock_retry(_op, op_name="claim_next_pending_job")


def requeue_stale_processing_jobs(
    timeout_seconds: Optional[int] = None,
    max_retries: Optional[int] = None,
) -> int:
    """
    Reenfileira jobs presos em 'processing' há mais tempo que o limite.

    Semântica dos contadores:
      - retry_count: usado APENAS aqui para contar quantas vezes o job foi
        devolvido de 'processing' para 'pending' por stale recovery
        (worker possivelmente morto ou travado).
      - attempt_count/max_attempts: usados APENAS pelo retry automático
        de falhas transitórias no processamento/envio (worker.py).
        Esta função não altera nem consulta attempt_count/max_attempts
        nem next_retry_at.

    A ideia é evitar ambiguidade: stale recovery lida com jobs presos em
    'processing'; retry automático lida com jobs que completam uma tentativa
    e falham de maneira transitória/permanente.

    Observação arquitetural: esta função contém hoje uma exceção pontual à
    responsabilidade de "persistência pura" ao acionar um alerta quando um
    job stale é definitivamente marcado como 'error' por exceder retry_count
    (job envenenado). Essa decisão foi adotada de forma pragmática para
    notificar falhas terminais de stale recovery sem alterar a assinatura
    ou o fluxo do worker. Se no futuro houver uma camada de domínio/serviço
    separada, essa lógica de alerta deve ser deslocada para lá.

    Se o worker morrer durante o processamento, o job fica stuck em
    'processing'. Esta rotina:
      - Jobs com retry_count >= max_retries: marca como 'error' (job envenenado).
      - Jobs com retry_count < max_retries: devolve para 'pending' com retry_count + 1.

    Args:
        timeout_seconds: Tempo máximo em processing antes de considerar
            stale. Se None, usa config.PROCESSING_STALE_SECONDS.
        max_retries: Limite de re-tentativas. Se None, usa config.STALE_MAX_RETRIES.

    Returns:
        Soma dos jobs afetados (marcados como error + reenfileirados).
    """
    if timeout_seconds is None:
        timeout_seconds = config.PROCESSING_STALE_SECONDS
    if max_retries is None:
        max_retries = getattr(config, "STALE_MAX_RETRIES", 3)

    init_db()
    agora = _agora_iso()
    cutoff = (
        datetime.now(timezone.utc) - timedelta(seconds=timeout_seconds)
    ).replace(microsecond=0).isoformat()

    def _op(conn: sqlite3.Connection) -> int:
        conn.execute("BEGIN IMMEDIATE")

        # 1) Jobs stale com retry_count >= max_retries → error (job envenenado)
        cur = conn.execute(
            """
            UPDATE jobs
            SET status = 'error',
                error_message = 'Max retries excedido',
                updated_at = ?
            WHERE status = 'processing'
              AND updated_at <= ?
              AND retry_count >= ?
            """,
            (agora, cutoff, max_retries),
        )
        count_error = cur.rowcount

        # Alerta apenas para jobs efetivamente envenenados (marcados como error).
        if count_error > 0:
            cur_alert = conn.execute(
                """
                SELECT id, source_type, source_identifier, retry_count
                FROM jobs
                WHERE status = 'error'
                  AND error_message = 'Max retries excedido'
                  AND updated_at = ?
                  AND retry_count >= ?
                """,
                (agora, max_retries),
            )
            rows = cur_alert.fetchall()
            for row in rows:
                try:
                    alertar_falha_definitiva(
                        job_id=row["id"],
                        status="error",
                                error_type=ErrorType.STALE_EXHAUSTED,
                        attempt_count=row["retry_count"],
                        max_attempts=max_retries,
                        source_type=row["source_type"],
                        source_identifier=row["source_identifier"],
                        mensagem_erro="Max retries excedido (stale processing)",
                    )
                except Exception:
                    log.debug(
                        "Falha ao enviar alerta de job stale envenenado (ignorado) | job_id=%s",
                        row["id"],
                    )

        # 2) Jobs stale com retry_count < max_retries → pending (nova tentativa)
        cur = conn.execute(
            """
            UPDATE jobs
            SET status = 'pending',
                updated_at = ?,
                retry_count = retry_count + 1
            WHERE status = 'processing'
              AND updated_at <= ?
              AND retry_count < ?
            """,
            (agora, cutoff, max_retries),
        )
        count_requeued = cur.rowcount

        conn.execute("COMMIT")

        total = count_error + count_requeued
        if total > 0:
            log.warning(
                "♻️ %d job(s) stale em 'processing' processado(s): "
                "%d marcado(s) como error (max retries), %d reenfileirado(s) "
                "(timeout=%ds, max_retries=%d).",
                total,
                count_error,
                count_requeued,
                timeout_seconds,
                max_retries,
            )
        return total

    return _with_lock_retry(_op, op_name="requeue_stale_processing_jobs")


__all__ = [
    "Job",
    "JobStoreError",
    "init_db",
    "criar_job",
    "buscar_jobs_pendentes",
    "atualizar_status",
    "atualizar_heartbeat",
    "registrar_erro",
    "marcar_skipped",
    "agendar_retry",
    "marcar_falha_definitiva",
    "marcar_sucesso",
    "obter_contagem_jobs_por_status",
    "obter_contagem_jobs_por_error_type",
    "obter_job_pendente_mais_antigo",
    "obter_ultima_execucao_com_sucesso",
    "obter_estatisticas_recentes",
    "hash_ja_processado_com_sucesso",
    "criar_job_com_idempotencia",
    "obter_job_por_id",
    "listar_jobs_por_status",
    "claim_next_pending_job",
    "requeue_stale_processing_jobs",
]


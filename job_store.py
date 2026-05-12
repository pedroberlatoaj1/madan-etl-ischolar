"""
job_store.py — Camada de persistência de jobs de sincronização (PostgreSQL).

Responsável por:
- inserir job
- buscar jobs pendentes
- atualizar status e contadores
- registrar erro
- marcar job como skipped
- verificar se um hash já foi processado com sucesso
- reivindicar atomicamente o próximo job (FOR UPDATE SKIP LOCKED)
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, List, Optional

from config import config
from constants import ErrorType, JobStatus, JobType
from db import get_connection
from logger import configurar_logger
from alertas import alertar_falha_definitiva


log = configurar_logger("etl.job_store")


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
    result_summary: Optional[str] = None
    total_records: Optional[int] = None
    processed_records: Optional[int] = None
    retry_count: int = 0
    attempt_count: int = 0
    max_attempts: int = 4
    error_type: Optional[str] = None
    last_error: Optional[str] = None
    next_retry_at: Optional[str] = None
    last_attempt_at: Optional[str] = None
    job_type: str = JobType.LEGACY_SYNC
    payload: Optional[dict[str, Any]] = None


def _agora_iso() -> str:
    """Retorna timestamp UTC em ISO 8601 (sem microssegundos)."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _row_to_job(row: dict) -> Job:
    """Converte uma linha (dict do RealDictCursor) no dataclass Job."""
    payload_json = row.get("payload_json")
    return Job(
        id=row["id"],
        source_type=row["source_type"],
        source_identifier=row["source_identifier"],
        content_hash=row["content_hash"],
        status=row["status"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        error_message=row.get("error_message"),
        skip_reason=row.get("skip_reason"),
        result_summary=row.get("result_summary"),
        total_records=row.get("total_records"),
        processed_records=row.get("processed_records"),
        retry_count=row.get("retry_count", 0),
        attempt_count=row.get("attempt_count", 0),
        max_attempts=row.get("max_attempts", 4),
        error_type=row.get("error_type"),
        last_error=row.get("last_error"),
        next_retry_at=row.get("next_retry_at"),
        last_attempt_at=row.get("last_attempt_at"),
        job_type=row.get("job_type") or JobType.LEGACY_SYNC,
        payload=json.loads(payload_json) if payload_json else None,
    )


def init_db() -> None:
    """No-op em PostgreSQL: schema é aplicado via db.init_schema() no boot."""
    pass


def criar_job(
    source_type: str,
    source_identifier: str,
    content_hash: str,
    total_records: Optional[int] = None,
    *,
    job_type: str = JobType.LEGACY_SYNC,
    payload: Optional[dict[str, Any]] = None,
) -> Job:
    """Cria um novo job com status 'pending'."""
    agora = _agora_iso()
    payload_str = json.dumps(payload, sort_keys=True, ensure_ascii=False) if payload is not None else None

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO jobs (
                    source_type, source_identifier, content_hash,
                    job_type, payload_json, status,
                    created_at, updated_at,
                    total_records, processed_records, retry_count
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 0)
                RETURNING id
                """,
                (
                    source_type, source_identifier, content_hash,
                    job_type, payload_str, JobStatus.PENDING,
                    agora, agora,
                    total_records, 0 if total_records is not None else None,
                ),
            )
            job_id = cur.fetchone()["id"]

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
        job_type=job_type,
        payload=payload,
    )
    log.info(
        "📌 Job criado | id=%s | job_type=%s | source_type=%s | source_identifier=%s",
        job_id, job_type, source_type, source_identifier,
    )
    return job


def buscar_jobs_pendentes(limit: int = 50) -> List[Job]:
    """Lista jobs com status 'pending' (sem aplicar next_retry_at)."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM jobs WHERE status = %s ORDER BY created_at ASC LIMIT %s",
                (JobStatus.PENDING, limit),
            )
            rows = cur.fetchall()
    return [_row_to_job(row) for row in rows]


def atualizar_status(
    job_id: int,
    novo_status: str,
    *,
    processed_records: Optional[int] = None,
    total_records: Optional[int] = None,
    increment_retry: bool = False,
) -> None:
    """Atualiza status do job e opcionalmente counters."""
    agora = _agora_iso()
    campos = ["status = %s", "updated_at = %s"]
    valores: list[Any] = [novo_status, agora]

    if processed_records is not None:
        campos.append("processed_records = %s")
        valores.append(processed_records)
    if total_records is not None:
        campos.append("total_records = %s")
        valores.append(total_records)
    if increment_retry:
        campos.append("retry_count = retry_count + 1")

    valores.append(job_id)
    sql = f"UPDATE jobs SET {', '.join(campos)} WHERE id = %s"

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, tuple(valores))
    log.info("🔄 Job %s atualizado para status='%s'.", job_id, novo_status)


def atualizar_heartbeat(job_id: int) -> None:
    """Atualiza apenas updated_at do job (heartbeat para jobs longos)."""
    agora = _agora_iso()
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("UPDATE jobs SET updated_at = %s WHERE id = %s", (agora, job_id))
    except Exception as exc:
        log.debug("Heartbeat job %s falhou (não crítico): %s", job_id, exc)


def registrar_erro(job_id: int, mensagem: str) -> None:
    """Registra mensagem de erro e marca status como 'error'."""
    agora = _agora_iso()
    msg = mensagem[:1000]
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE jobs
                SET status = %s,
                    error_message = %s,
                    result_summary = NULL,
                    last_error = %s,
                    error_type = COALESCE(error_type, 'permanent'),
                    next_retry_at = NULL,
                    updated_at = %s
                WHERE id = %s
                """,
                (JobStatus.ERROR, msg, msg, agora, job_id),
            )
    log.error("💥 Job %s marcado como error: %s", job_id, mensagem)


def marcar_skipped(job_id: int, motivo: str | None = None) -> None:
    """Marca job como 'skipped' e registra motivo em skip_reason."""
    agora = _agora_iso()
    motivo_trunc = motivo[:500] if motivo else None
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE jobs
                SET status = 'skipped', skip_reason = %s, updated_at = %s
                WHERE id = %s
                """,
                (motivo_trunc, agora, job_id),
            )
    log.info("⏭️ Job %s marcado como skipped. Motivo: %s", job_id, motivo)


def agendar_retry(
    job_id: int,
    *,
    next_retry_at: str,
    last_error: str,
    error_type: str = ErrorType.TRANSIENT,
) -> None:
    """Reagenda job para retry (status='pending' com next_retry_at futuro)."""
    agora = _agora_iso()
    err = last_error[:1000]
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE jobs
                SET status = 'pending',
                    error_type = %s,
                    last_error = %s,
                    error_message = %s,
                    result_summary = NULL,
                    next_retry_at = %s,
                    updated_at = %s
                WHERE id = %s
                """,
                (error_type, err, err, next_retry_at, agora, job_id),
            )
    log.warning(
        "⏳ Job %s reagendado para retry | error_type=%s | next_retry_at=%s",
        job_id, error_type, next_retry_at,
    )


def marcar_falha_definitiva(
    job_id: int,
    *,
    last_error: str,
    error_type: str = ErrorType.PERMANENT,
) -> None:
    """Marca job como 'error' sem reagendar (falha definitiva)."""
    agora = _agora_iso()
    err = last_error[:1000]
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE jobs
                SET status = %s,
                    error_type = %s,
                    last_error = %s,
                    error_message = %s,
                    result_summary = NULL,
                    next_retry_at = NULL,
                    updated_at = %s
                WHERE id = %s
                """,
                (JobStatus.ERROR, error_type, err, err, agora, job_id),
            )
    log.error("💥 Job %s falha definitiva | error_type=%s | %s", job_id, error_type, last_error)


def marcar_sucesso(
    job_id: int,
    *,
    processed_records: int,
    total_records: int,
    result_summary: Optional[str] = None,
) -> None:
    """Marca job como success e limpa estado de erro/retry."""
    agora = _agora_iso()
    summary = result_summary[:1000] if result_summary else None
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE jobs
                SET status = %s,
                    processed_records = %s,
                    total_records = %s,
                    result_summary = %s,
                    error_message = NULL,
                    error_type = NULL,
                    last_error = NULL,
                    next_retry_at = NULL,
                    updated_at = %s
                WHERE id = %s
                """,
                (JobStatus.SUCCESS, processed_records, total_records, summary, agora, job_id),
            )
    log.info("✅ Job %s atualizado para status='success'.", job_id)


def _idempotency_ja_sucesso(
    cur,
    mode: str,
    job_type: str,
    source_type: str,
    source_identifier: str,
    content_hash: str,
) -> bool:
    """Verifica se já existe job 'success' conforme a política de idempotência."""
    mode = (mode or "content_and_source").strip().lower()
    if mode == "content_only":
        cur.execute(
            """
            SELECT 1 FROM jobs
            WHERE job_type = %s AND content_hash = %s AND status = 'success'
            LIMIT 1
            """,
            (job_type, content_hash),
        )
    else:
        cur.execute(
            """
            SELECT 1 FROM jobs
            WHERE job_type = %s AND source_type = %s AND source_identifier = %s
              AND content_hash = %s AND status = 'success'
            LIMIT 1
            """,
            (job_type, source_type, source_identifier, content_hash),
        )
    return cur.fetchone() is not None


def hash_ja_processado_com_sucesso(
    source_type: str,
    source_identifier: str,
    content_hash: str,
    *,
    job_type: str = JobType.LEGACY_SYNC,
) -> bool:
    """Verifica se já existe job bem-sucedido conforme config.IDEMPOTENCY_MODE."""
    mode = getattr(config, "IDEMPOTENCY_MODE", "content_and_source")
    with get_connection() as conn:
        with conn.cursor() as cur:
            achou = _idempotency_ja_sucesso(
                cur, mode, job_type, source_type, source_identifier, content_hash
            )
    if achou:
        log.info(
            "♻️ Conteúdo já processado (idempotência: %s) | job_type=%s | source=%s",
            mode, job_type, source_identifier,
        )
    return achou


def criar_job_com_idempotencia(
    source_type: str,
    source_identifier: str,
    content_hash: str,
    total_records: Optional[int] = None,
    *,
    job_type: str = JobType.LEGACY_SYNC,
    payload: Optional[dict[str, Any]] = None,
) -> Job:
    """Cria job com idempotência conforme config.IDEMPOTENCY_MODE."""
    mode = getattr(config, "IDEMPOTENCY_MODE", "content_and_source")
    agora = _agora_iso()
    payload_str = json.dumps(payload, sort_keys=True, ensure_ascii=False) if payload is not None else None

    with get_connection() as conn:
        with conn.cursor() as cur:
            ja_sucesso = _idempotency_ja_sucesso(
                cur, mode, job_type, source_type, source_identifier, content_hash
            )
            status_inicial = JobStatus.SKIPPED if ja_sucesso else JobStatus.PENDING
            processed_records = 0 if (total_records is not None and not ja_sucesso) else None
            skip_reason = "Conteúdo já processado anteriormente com sucesso." if ja_sucesso else None

            cur.execute(
                """
                INSERT INTO jobs (
                    source_type, source_identifier, content_hash,
                    job_type, payload_json, status,
                    created_at, updated_at, skip_reason,
                    total_records, processed_records, retry_count
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 0)
                RETURNING id
                """,
                (
                    source_type, source_identifier, content_hash,
                    job_type, payload_str, status_inicial,
                    agora, agora, skip_reason,
                    total_records, processed_records,
                ),
            )
            job_id = cur.fetchone()["id"]

    job = Job(
        id=job_id,
        source_type=source_type,
        source_identifier=source_identifier,
        content_hash=content_hash,
        status=status_inicial,
        created_at=agora,
        updated_at=agora,
        skip_reason=skip_reason,
        total_records=total_records,
        processed_records=processed_records,
        retry_count=0,
        job_type=job_type,
        payload=payload,
    )

    if ja_sucesso:
        log.info("⏭️ Job %s criado como skipped (idempotência: %s)", job_id, mode)
    else:
        log.info("📌 Job %s criado como pending | job_type=%s", job_id, job_type)

    return job


def criar_job_validacao_google_sheets(
    *,
    source_identifier: str,
    content_hash: str,
    lote_id: str,
    total_records: Optional[int] = None,
    payload: Optional[dict[str, Any]] = None,
) -> Job:
    payload_final = {"lote_id": lote_id}
    if payload:
        payload_final.update(payload)
    return criar_job_com_idempotencia(
        source_type="google_sheets",
        source_identifier=source_identifier,
        content_hash=content_hash,
        total_records=total_records,
        job_type=JobType.GOOGLE_SHEETS_VALIDATION,
        payload=payload_final,
    )


def criar_job_aprovacao_envio(
    *,
    lote_id: str,
    aprovado_por: str,
    snapshot_hash: str,
    approval_identity: Optional[dict[str, Any]] = None,
    source_type: str = "google_sheets",
    source_identifier: Optional[str] = None,
    dry_run: bool = False,
    payload: Optional[dict[str, Any]] = None,
) -> Job:
    payload_final = {
        "lote_id": lote_id,
        "aprovado_por": aprovado_por,
        "expected_snapshot_hash": snapshot_hash,
        "dry_run": dry_run,
    }
    if approval_identity:
        payload_final["approval_identity"] = dict(approval_identity)
    if payload:
        payload_final.update(payload)
    return criar_job(
        source_type=source_type,
        source_identifier=source_identifier or lote_id,
        content_hash=snapshot_hash,
        job_type=JobType.APPROVAL_AND_SEND,
        payload=payload_final,
    )


def obter_job_por_id(job_id: int) -> Optional[Job]:
    """Obtém um job específico pelo ID."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM jobs WHERE id = %s", (job_id,))
            row = cur.fetchone()
    if row is None:
        return None
    return _row_to_job(row)


def obter_contagem_jobs_por_status() -> dict[str, int]:
    """Retorna a contagem de jobs agrupados por status."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT status, COUNT(*) AS total FROM jobs GROUP BY status")
            rows = cur.fetchall()
    return {row["status"]: int(row["total"]) for row in rows}


def obter_contagem_jobs_por_error_type() -> dict[str, int]:
    """Retorna a contagem de jobs agrupados por error_type."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT error_type, COUNT(*) AS total FROM jobs "
                "WHERE error_type IS NOT NULL GROUP BY error_type"
            )
            rows = cur.fetchall()
    return {row["error_type"]: int(row["total"]) for row in rows}


def obter_job_pendente_mais_antigo() -> Optional[Job]:
    """Retorna o job 'pending' mais antigo por created_at."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM jobs WHERE status = %s ORDER BY created_at ASC LIMIT 1",
                (JobStatus.PENDING,),
            )
            row = cur.fetchone()
    return _row_to_job(row) if row else None


def obter_ultima_execucao_com_sucesso() -> Optional[str]:
    """Retorna o timestamp ISO da última execução bem-sucedida."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT MAX(updated_at) AS last_success FROM jobs WHERE status = %s",
                (JobStatus.SUCCESS,),
            )
            row = cur.fetchone()
    return row["last_success"] if row else None


def obter_estatisticas_recentes(janela_minutos: int = 60) -> dict[str, int]:
    """Estatísticas de retries/exhausted em janela recente."""
    cutoff_dt = datetime.now(timezone.utc) - timedelta(minutes=janela_minutos)
    cutoff = cutoff_dt.replace(microsecond=0).isoformat()

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) AS total FROM jobs WHERE attempt_count > 1 AND updated_at >= %s",
                (cutoff,),
            )
            retries = int(cur.fetchone()["total"])

            cur.execute(
                "SELECT COUNT(*) AS total FROM jobs "
                "WHERE status = %s AND error_type = %s AND updated_at >= %s",
                (JobStatus.ERROR, ErrorType.EXHAUSTED, cutoff),
            )
            exhausted = int(cur.fetchone()["total"])

    return {"retries": retries, "exhausted": exhausted}


def listar_jobs_por_status(statuses: Iterable[str]) -> List[Job]:
    """Lista jobs filtrando por um ou mais status."""
    statuses_list = list(statuses)
    if not statuses_list:
        return []
    placeholders = ",".join(["%s"] * len(statuses_list))
    sql = f"SELECT * FROM jobs WHERE status IN ({placeholders}) ORDER BY created_at DESC"
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, tuple(statuses_list))
            rows = cur.fetchall()
    return [_row_to_job(row) for row in rows]


def claim_next_pending_job() -> Optional[Job]:
    """
    Reivindica atomicamente o próximo job pendente (pending → processing).

    Usa FOR UPDATE SKIP LOCKED — workers concorrentes nunca pegam o mesmo job.
    """
    agora = _agora_iso()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id FROM jobs
                WHERE status = 'pending'
                  AND (next_retry_at IS NULL OR next_retry_at <= %s)
                ORDER BY created_at ASC
                LIMIT 1
                FOR UPDATE SKIP LOCKED
                """,
                (agora,),
            )
            row = cur.fetchone()
            if row is None:
                return None

            job_id = row["id"]
            cur.execute(
                """
                UPDATE jobs
                SET status = 'processing',
                    updated_at = %s,
                    last_attempt_at = %s,
                    attempt_count = attempt_count + 1
                WHERE id = %s
                """,
                (agora, agora, job_id),
            )
            cur.execute("SELECT * FROM jobs WHERE id = %s", (job_id,))
            row_full = cur.fetchone()

    job = _row_to_job(row_full)
    log.info("🔒 Job %s reivindicado (pending → processing) | source=%s", job_id, job.source_identifier)
    return job


def requeue_stale_processing_jobs(
    timeout_seconds: Optional[int] = None,
    max_retries: Optional[int] = None,
) -> int:
    """
    Reenfileira jobs presos em 'processing' há mais tempo que o limite.

    - retry_count >= max_retries: marca como 'error' (job envenenado).
    - retry_count < max_retries: devolve para 'pending' com retry_count + 1.
    """
    if timeout_seconds is None:
        timeout_seconds = config.PROCESSING_STALE_SECONDS
    if max_retries is None:
        max_retries = getattr(config, "STALE_MAX_RETRIES", 3)

    agora = _agora_iso()
    cutoff = (datetime.now(timezone.utc) - timedelta(seconds=timeout_seconds)).replace(microsecond=0).isoformat()

    with get_connection() as conn:
        with conn.cursor() as cur:
            # 1) Jobs stale com retry_count >= max_retries → error (envenenado)
            cur.execute(
                """
                UPDATE jobs
                SET status = 'error',
                    error_message = 'Max retries excedido',
                    updated_at = %s
                WHERE status = 'processing'
                  AND updated_at <= %s
                  AND retry_count >= %s
                """,
                (agora, cutoff, max_retries),
            )
            count_error = cur.rowcount

            # Alertar para jobs envenenados
            if count_error > 0:
                cur.execute(
                    """
                    SELECT id, source_type, source_identifier, retry_count
                    FROM jobs
                    WHERE status = 'error'
                      AND error_message = 'Max retries excedido'
                      AND updated_at = %s
                      AND retry_count >= %s
                    """,
                    (agora, max_retries),
                )
                rows = cur.fetchall()
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
                        log.debug("Falha ao enviar alerta de job stale | job_id=%s", row["id"])

            # 2) Jobs stale com retry_count < max_retries → pending (nova tentativa)
            cur.execute(
                """
                UPDATE jobs
                SET status = 'pending',
                    updated_at = %s,
                    retry_count = retry_count + 1
                WHERE status = 'processing'
                  AND updated_at <= %s
                  AND retry_count < %s
                """,
                (agora, cutoff, max_retries),
            )
            count_requeued = cur.rowcount

    total = count_error + count_requeued
    if total > 0:
        log.warning(
            "♻️ %d job(s) stale processado(s): %d como error, %d reenfileirado(s) "
            "(timeout=%ds, max_retries=%d).",
            total, count_error, count_requeued, timeout_seconds, max_retries,
        )
    return total


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
    "criar_job_validacao_google_sheets",
    "criar_job_aprovacao_envio",
    "obter_job_por_id",
    "listar_jobs_por_status",
    "claim_next_pending_job",
    "requeue_stale_processing_jobs",
]

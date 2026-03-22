"""
worker.py — Consumidor de jobs de sincronização de notas.

Fluxo por job:
  1. Recuperar jobs stale em processing (stale recovery)
  2. Reivindicar próximo job pendente (claim atômico via BEGIN IMMEDIATE)
  3. Carregar origem (arquivo local ou snapshot Google Sheets)
  4. Transformar dados (transformador)
  5. Heartbeat (atualiza updated_at) para evitar stale durante envio
  6. Enviar para iScholar
  7. Atualizar status final (success/error) e contadores

Semântica de total_records / processed_records:
  - total_records: número de linhas do DataFrame após transformação.
  - processed_records: número de linhas processadas de forma determinística pelo pipeline.
    Importante: "sucesso" operacional do job NÃO significa "100% de notas criadas".
    Um lote pode concluir deterministicamente com created/skipped/conflicts/failed_permanent
    e ainda assim ser considerado concluído operacionalmente (sem retry).

Retry automático:
  O retry do job ocorre apenas quando a falha é transitória (ex.: timeout/5xx) e o
  cliente sinaliza `resultado.transitório == True`.

Uso:
  python worker.py              # loop contínuo
  python worker.py --once       # processa uma rodada e encerra
  python worker.py --limit 5    # até 5 jobs por rodada
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

import os
import signal
import sys
import time
from types import FrameType
from typing import Literal, Optional

import pandas as pd

from config import config
from ischolar_client import IScholarClient, ResultadoEnvio, get_client
from job_store import (
    Job,
    agendar_retry,
    atualizar_heartbeat,
    atualizar_status,
    claim_next_pending_job,
    marcar_falha_definitiva,
    marcar_sucesso,
    registrar_erro,
    requeue_stale_processing_jobs,
)
from alertas import alertar_falha_definitiva
from logger import configurar_logger
from constants import ErrorType
from snapshot_store import cleanup_old_snapshots, load_snapshot_records
from transformador import limpar_e_transformar_notas

log = configurar_logger("etl.worker")

# Flag para graceful shutdown (SIGINT/SIGTERM)
_rodando = True


def _solicitar_encerramento(signum: int, frame: Optional[FrameType]) -> None:
    """Handler de sinal: solicita parada após terminar o job atual."""
    global _rodando
    log.info("\n🛑 Sinal de encerramento recebido. Finalizando job atual antes de sair...")
    _rodando = False


# Tipos de origem suportados
SOURCE_LOCAL_FILE = "local_file"
SOURCE_GOOGLE_SHEETS = "google_sheets"


def _carregar_origem_local_file(source_identifier: str) -> pd.DataFrame:
    """
    Carrega e transforma dados a partir de um arquivo local.

    source_identifier deve ser o caminho absoluto (ou relativo) do arquivo.
    """
    if not os.path.isfile(source_identifier):
        raise FileNotFoundError(f"Arquivo não encontrado: {source_identifier}")
    return limpar_e_transformar_notas(source_identifier)


def _carregar_origem_google_sheets(job: Job) -> pd.DataFrame:
    """
    Carrega o snapshot persistido pelo webhook e transforma com o pipeline de notas.

    Usa snapshot_store.load_snapshot_records() que suporta tanto o formato
    novo (envelope com metadados) quanto o legado (lista pura de dicts).
    """
    if job.id is None:
        raise ValueError("Job Google Sheets sem id")
    df_bruto = load_snapshot_records(job.id)
    return limpar_e_transformar_notas(df_bruto)


def _carregar_e_transformar(job: Job) -> pd.DataFrame:
    """
    Carrega a origem do job e retorna o DataFrame transformado.

    Raises:
        FileNotFoundError: arquivo local não encontrado.
        ValueError: dados inválidos (colunas obrigatórias, etc.).
        NotImplementedError: source_type não suportado.
    """
    if job.source_type == SOURCE_LOCAL_FILE:
        return _carregar_origem_local_file(job.source_identifier)
    if job.source_type == SOURCE_GOOGLE_SHEETS:
        return _carregar_origem_google_sheets(job)
    raise ValueError(f"source_type não suportado: {job.source_type}")


# Resultado do processamento de um job (para observabilidade)
JobResultado = Literal["success", "success_empty", "error"]


def classify_error(exc: Exception, context: Optional[dict] = None) -> str:
    """
    Classifica erros em transitórios vs permanentes para retry automático,
    retornando valores centralizados em ErrorType.TRANSIENT ou
    ErrorType.PERMANENT.

    Heurística pragmática e explícita.
    Decisão conservadora: se não der para inferir com boa confiança, trata como PERMANENT
    para evitar loops de retry em erros de regra de negócio/entrada.
    """
    context = context or {}

    # Sinalização explícita vinda de camadas inferiores (ex.: ischolar_client)
    trans_flag = context.get("transitorio_flag")
    if trans_flag is True:
        return ErrorType.TRANSIENT

    # Erros estruturais/entrada (permanentes)
    if isinstance(exc, (ValueError, FileNotFoundError, NotImplementedError)):
        return ErrorType.PERMANENT

    # HTTP: 5xx típicos de indisponibilidade
    status_code = context.get("status_code")
    if isinstance(status_code, int) and status_code in (502, 503, 504):
        return ErrorType.TRANSIENT
    if isinstance(status_code, int) and 400 <= status_code < 500:
        return ErrorType.PERMANENT

    # requests (rede/timeout) quando disponível
    try:
        import requests  # type: ignore

        if isinstance(
            exc,
            (
                requests.exceptions.Timeout,
                requests.exceptions.ConnectionError,
            ),
        ):
            return ErrorType.TRANSIENT
    except Exception:
        pass

    # OSError genérico pode indicar falha temporária de transporte/rede
    if isinstance(exc, OSError):
        msg = str(exc).lower()
        if any(k in msg for k in ("timed out", "timeout", "temporar", "connection", "network")):
            return ErrorType.TRANSIENT

    msg = str(exc).lower()
    if any(k in msg for k in ("timeout", "timed out", "connection error", "temporary", "temporar", "network")):
        return ErrorType.TRANSIENT
    if any(k in msg for k in ("unauthorized", "forbidden", "invalid api key", "credencial", "autent")):
        return ErrorType.PERMANENT

    return ErrorType.PERMANENT


def _backoff_for_attempt(attempt_count: int) -> Optional[timedelta]:
    """
    Backoff progressivo fixo por tentativa (tentativas totais de processamento).

    1ª falha transitória (attempt=1) → 5 min
    2ª falha transitória (attempt=2) → 15 min
    3ª falha transitória (attempt=3) → 60 min
    4ª falha transitória (attempt=4) → sem novo retry (falha definitiva)
    """
    if attempt_count <= 1:
        return timedelta(minutes=5)
    if attempt_count == 2:
        return timedelta(minutes=15)
    if attempt_count == 3:
        return timedelta(minutes=60)
    return None


def _agora_iso_utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _calcular_next_retry_at_iso(attempt_count: int) -> Optional[str]:
    delta = _backoff_for_attempt(attempt_count)
    if delta is None:
        return None
    return (datetime.now(timezone.utc).replace(microsecond=0) + delta).isoformat()


def _falhar_job_com_retry(
    *,
    job: Job,
    mensagem: str,
    tipo: str,
    context: Optional[dict] = None,
) -> None:
    job_id = job.id
    if job_id is None:
        return

    attempt = int(getattr(job, "attempt_count", 0) or 0)
    max_attempts = int(getattr(job, "max_attempts", 4) or 4)

    if tipo == ErrorType.PERMANENT:
        log.error(
            "💥 Job %s falha permanente | tentativa=%d/%d | %s",
            job_id,
            attempt,
            max_attempts,
            mensagem,
        )
        marcar_falha_definitiva(job_id, last_error=mensagem, error_type="permanent")
        try:
            alertar_falha_definitiva(
                job_id=job_id,
                status="error",
                error_type="permanent",
                attempt_count=attempt,
                max_attempts=max_attempts,
                source_type=job.source_type,
                source_identifier=job.source_identifier,
                mensagem_erro=mensagem,
            )
        except Exception:
            # Falha de alerta nunca deve derrubar o worker.
            log.debug("Falha ao enviar alerta de falha permanente (ignorado).")
        return

    # transient
    if attempt >= max_attempts:
        log.error(
            "💥 Job %s falha definitiva (tentativas excedidas) | tentativa=%d/%d | %s",
            job_id,
            attempt,
            max_attempts,
            mensagem,
        )
        marcar_falha_definitiva(job_id, last_error=mensagem, error_type=ErrorType.EXHAUSTED)
        try:
            alertar_falha_definitiva(
                job_id=job_id,
                status="error",
                error_type="exhausted",
                attempt_count=attempt,
                max_attempts=max_attempts,
                source_type=job.source_type,
                source_identifier=job.source_identifier,
                mensagem_erro=mensagem,
            )
        except Exception:
            log.debug("Falha ao enviar alerta de falha por tentativas excedidas (ignorado).")
        return

    next_retry_at = _calcular_next_retry_at_iso(attempt)
    if not next_retry_at:
        # Redundante com attempt>=max_attempts, mas protege contra inconsistência interna.
        marcar_falha_definitiva(job_id, last_error=mensagem, error_type=ErrorType.EXHAUSTED)
        try:
            alertar_falha_definitiva(
                job_id=job_id,
                status="error",
                error_type="exhausted",
                attempt_count=attempt,
                max_attempts=max_attempts,
                source_type=job.source_type,
                source_identifier=job.source_identifier,
                mensagem_erro=mensagem,
            )
        except Exception:
            log.debug("Falha ao enviar alerta de falha por tentativas excedidas (ignorado).")
        return

    log.warning(
        "⏳ Job %s falha transitória → retry agendado | tentativa=%d/%d | next_retry_at=%s | %s",
        job_id,
        attempt,
        max_attempts,
        next_retry_at,
        mensagem,
    )
    agendar_retry(job_id, next_retry_at=next_retry_at, last_error=mensagem, error_type=ErrorType.TRANSIENT)


def processar_job(
    job: Job,
    client: Optional[IScholarClient] = None,
) -> JobResultado:
    """
    Processa um único job: processing → carregar → transformar → heartbeat → enviar → success/error.

    Returns:
        "success": enviado com registros; "success_empty": DataFrame vazio (success com 0 registros);
        "error": falha em carregar, transformar ou enviar.
    """
    if client is None:
        client = get_client()

    job_id = job.id
    if job_id is None:
        log.error("Job sem id, ignorando.")
        return "error"

    log.info(
        "▶️ Job %s reivindicado | source_type=%s | source_identifier=%s",
        job_id,
        job.source_type,
        job.source_identifier,
    )
    log.info(
        "   tentativa=%d/%d",
        int(getattr(job, "attempt_count", 0) or 0),
        int(getattr(job, "max_attempts", 4) or 4),
    )

    try:
        df = _carregar_e_transformar(job)
    except FileNotFoundError as exc:
        tipo = classify_error(exc, context={"fase": "carregar_transformar"})
        msg = f"Arquivo não encontrado: {exc}"
        _falhar_job_com_retry(job=job, mensagem=msg, tipo=tipo)
        return "error"
    except ValueError as exc:
        tipo = classify_error(exc, context={"fase": "carregar_transformar"})
        msg = f"Dados inválidos: {exc}"
        _falhar_job_com_retry(job=job, mensagem=msg, tipo=tipo)
        return "error"
    except Exception as exc:
        log.exception("❌ Job %s [error]: erro ao carregar/transformar: %s", job_id, exc)
        tipo = classify_error(exc, context={"fase": "carregar_transformar"})
        _falhar_job_com_retry(
            job=job,
            mensagem=f"Erro ao carregar/transformar: {exc!s}",
            tipo=tipo,
            context={"fase": "carregar_transformar"},
        )
        return "error"

    # Heartbeat 1: após carregamento
    try:
        atualizar_heartbeat(job_id)
    except Exception:
        pass

    if df.empty:
        # Coerente com job_store: success com 0 registros (processamos; não havia dados para enviar)
        try:
            marcar_sucesso(job_id, processed_records=0, total_records=0)
            log.info(
                "✅ Job %s [success_empty]: 0 registros — planilha vazia após transformação.",
                job_id,
            )
            return "success_empty"
        except Exception as exc:
            log.exception("Falha ao atualizar status do job %s: %s", job_id, exc)
            registrar_erro(job_id, f"Falha ao persistir status: {exc}")
            return "error"

    # Heartbeat 2: antes do envio
    try:
        atualizar_heartbeat(job_id)
    except Exception:
        pass

    idempotency_key = job.content_hash
    n_registros_deterministicos = len(df)

    resultado: ResultadoEnvio = client.enviar_notas(
        df=df,
        source_identifier=job.source_identifier,
        source_type=job.source_type,
        job_id=job_id,
        idempotency_key=idempotency_key,
    )

    # Nova semântica: retry é controlado APENAS por resultado.transitorio.
    # - transitorio=True  → manter fluxo atual de retry
    # - transitorio=False → job conclui operacionalmente (success ou falha definitiva), sem retry
    if resultado.transitorio:
        msg = resultado.mensagem or "Falha transitória no envio ao iScholar"
        msg = f"[Transitório] {msg}"
        log.error("❌ Job %s [error]: falha transitória no envio — %s", job_id, msg)
        _falhar_job_com_retry(
            job=job,
            mensagem=msg,
            tipo=ErrorType.TRANSIENT,
            context={"fase": "envio", "status_code": resultado.status_code},
        )
        return "error"

    if resultado.sucesso:
        # Heartbeat 3: após retorno da API
        try:
            atualizar_heartbeat(job_id)
        except Exception:
            pass
        try:
            # Compatibilidade com job_store: processed_records representa linhas concluídas
            # deterministicamente pelo pipeline (não "notas criadas com sucesso" na API).
            marcar_sucesso(
                job_id,
                processed_records=n_registros_deterministicos,
                total_records=n_registros_deterministicos,
                result_summary=resultado.mensagem,
            )
            log.info(
                "✅ Job %s [success]: %d registro(s) processados. %s",
                job_id,
                n_registros_deterministicos,
                (resultado.mensagem or "").strip(),
            )
            return "success"
        except Exception as exc:
            log.exception("Job %s: envio OK mas falha ao atualizar status: %s", job_id, exc)
            registrar_erro(job_id, f"Envio OK; falha ao persistir status: {exc!s}")
            return "error"

    # Falha não transitória (determinística): conclui como falha definitiva (sem retry).
    msg = resultado.mensagem or "Falha não transitória no envio ao iScholar"
    tipo = ErrorType.PERMANENT
    log.error("💥 Job %s [error]: falha definitiva no envio (sem retry) — %s", job_id, msg)
    _falhar_job_com_retry(
        job=job,
        mensagem=msg,
        tipo=tipo,
        context={"fase": "envio", "status_code": resultado.status_code},
    )
    return "error"


@dataclass
class RodadaStats:
    """Contadores da rodada para observabilidade."""
    reivindicados: int = 0
    success: int = 0
    success_empty: int = 0
    error: int = 0

    @property
    def total_processados(self) -> int:
        return self.success + self.success_empty + self.error


def processar_pendentes(
    limit: int = 50,
    client: Optional[IScholarClient] = None,
) -> RodadaStats:
    """
    Reivindica e processa jobs pendentes de forma atômica.

    Antes de consumir a fila, reenfileira jobs presos em 'processing'
    (stale recovery). Em seguida, reivindica um job por vez via
    claim_next_pending_job (BEGIN IMMEDIATE), garantindo que dois
    workers não processem o mesmo job.

    Returns:
        RodadaStats com reivindicados, success, success_empty, error.
    """
    requeue_stale_processing_jobs()

    stats = RodadaStats()
    for _ in range(limit):
        if not _rodando:
            break
        job = claim_next_pending_job()
        if job is None:
            break
        stats.reivindicados += 1
        try:
            resultado = processar_job(job, client=client)
            if resultado == "success":
                stats.success += 1
            elif resultado == "success_empty":
                stats.success_empty += 1
            else:
                stats.error += 1
        except Exception as exc:
            log.exception("Erro inesperado ao processar job %s: %s", job.id, exc)
            stats.error += 1
            try:
                registrar_erro(job.id, f"Erro inesperado no worker: {exc!s}")
            except Exception:
                pass

    if stats.reivindicados > 0:
        log.info(
            "📋 Rodada: %d reivindicado(s) | %d success | %d vazios (0 reg.) | %d error",
            stats.reivindicados,
            stats.success,
            stats.success_empty,
            stats.error,
        )
    return stats


def run_loop(
    interval_seconds: float = 30.0,
    limit_per_round: int = 50,
) -> None:
    """
    Executa o worker em loop: a cada interval_seconds, processa até limit_per_round jobs.
    Captura SIGINT/SIGTERM para encerramento gracioso (termina o job atual antes de sair).
    Executa cleanup de snapshots antigos a cada SNAPSHOT_CLEANUP_INTERVAL_SECONDS.
    """
    global _rodando
    _rodando = True

    # Captura Ctrl+C e SIGTERM para encerramento limpo
    signal.signal(signal.SIGINT, _solicitar_encerramento)
    signal.signal(signal.SIGTERM, _solicitar_encerramento)

    cleanup_interval = getattr(
        config, "SNAPSHOT_CLEANUP_INTERVAL_SECONDS", 3600
    )
    last_cleanup_at: float = 0.0

    log.info(
        "🔄 Worker em loop | intervalo=%.1fs | limite por rodada=%d | cleanup a cada %ds",
        interval_seconds,
        limit_per_round,
        cleanup_interval,
    )
    client = get_client()
    try:
        while _rodando:
            try:
                # Cleanup de snapshots antigos (uma vez por hora ou conforme config)
                now = time.monotonic()
                if now - last_cleanup_at >= cleanup_interval:
                    try:
                        removidos = cleanup_old_snapshots()
                        if removidos > 0:
                            log.info("🧹 Cleanup de snapshots: %d arquivo(s) removido(s).", removidos)
                    except Exception as exc:
                        log.warning("⚠️ Falha no cleanup de snapshots: %s", exc)
                    last_cleanup_at = now

                stats = processar_pendentes(limit=limit_per_round, client=client)
                if stats.reivindicados > 0:
                    log.info(
                        "Rodada concluída: %d job(s) processado(s) (%d success, %d vazios, %d error).",
                        stats.total_processados,
                        stats.success,
                        stats.success_empty,
                        stats.error,
                    )
            except Exception as exc:
                log.exception("Erro na rodada do worker: %s", exc)

            if _rodando:
                time.sleep(interval_seconds)
    finally:
        client.close()
        log.info("✅ Worker encerrado com sucesso.")


def _parsear_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Worker do pipeline ETL de notas → iScholar",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Processa uma rodada e encerra (sem loop).",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=30.0,
        help="Intervalo em segundos entre rodadas (modo loop).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=50,
        help="Máximo de jobs a processar por rodada.",
    )
    return parser.parse_args()


def main() -> None:
    args = _parsear_args()

    if args.once:
        stats = processar_pendentes(limit=args.limit)
        log.info(
            "Modo --once: %d reivindicado(s), %d success, %d vazios, %d error. Encerrando.",
            stats.reivindicados,
            stats.success,
            stats.success_empty,
            stats.error,
        )
        sys.exit(0)

    run_loop(
        interval_seconds=args.interval,
        limit_per_round=args.limit,
    )


if __name__ == "__main__":
    main()

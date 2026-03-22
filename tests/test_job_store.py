"""Testes da camada de persistência de jobs (riscos operacionais críticos)."""

import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from constants import JobStatus, ErrorType
import job_store as _job_store_mod
from job_store import (
    agendar_retry,
    atualizar_status,
    claim_next_pending_job,
    criar_job,
    criar_job_com_idempotencia,
    init_db,
    marcar_falha_definitiva,
    marcar_sucesso,
    obter_contagem_jobs_por_error_type,
    obter_contagem_jobs_por_status,
    obter_estatisticas_recentes,
    obter_job_pendente_mais_antigo,
    obter_job_por_id,
    obter_ultima_execucao_com_sucesso,
    requeue_stale_processing_jobs,
)


# ── claim atômico ──────────────────────────────────────────────────────────


class TestClaimAtomico:
    """Provar que dois claims sequenciais nunca retornam o mesmo job."""

    def test_claim_retorna_job_em_processing(self):
        init_db()
        criar_job("local_file", "/a.csv", "h1")

        job = claim_next_pending_job()

        assert job is not None
        assert job.status == "processing"

    def test_claims_sequenciais_retornam_jobs_distintos(self):
        init_db()
        j1 = criar_job("local_file", "/a.csv", "h1")
        j2 = criar_job("local_file", "/b.csv", "h2")

        claimed_1 = claim_next_pending_job()
        claimed_2 = claim_next_pending_job()

        assert claimed_1 is not None and claimed_2 is not None
        assert claimed_1.id == j1.id
        assert claimed_2.id == j2.id
        assert claimed_1.id != claimed_2.id

    def test_claim_fila_vazia_retorna_none(self):
        init_db()

        assert claim_next_pending_job() is None

    def test_claim_ignora_jobs_nao_pending(self):
        init_db()
        j = criar_job("local_file", "/a.csv", "h1")
        atualizar_status(j.id, "success")

        assert claim_next_pending_job() is None

    def test_claim_nao_pega_job_com_next_retry_at_no_futuro(self):
        from config import config

        init_db()
        j = criar_job("local_file", "/a.csv", "h1")

        futuro = (datetime.now(timezone.utc).replace(microsecond=0) + timedelta(hours=1)).isoformat()
        conn = sqlite3.connect(config.JOB_DB_PATH)
        try:
            conn.execute("UPDATE jobs SET next_retry_at = ? WHERE id = ?", (futuro, j.id))
            conn.commit()
        finally:
            conn.close()

        assert claim_next_pending_job() is None

    def test_claim_pega_job_com_next_retry_at_vencido(self):
        from config import config

        init_db()
        j = criar_job("local_file", "/a.csv", "h1")

        passado = (datetime.now(timezone.utc).replace(microsecond=0) - timedelta(minutes=1)).isoformat()
        conn = sqlite3.connect(config.JOB_DB_PATH)
        try:
            conn.execute("UPDATE jobs SET next_retry_at = ? WHERE id = ?", (passado, j.id))
            conn.commit()
        finally:
            conn.close()

        claimed = claim_next_pending_job()
        assert claimed is not None
        assert claimed.id == j.id


# ── stale requeue ──────────────────────────────────────────────────────────


class TestStaleRequeue:
    """Provar que jobs presos em processing voltam para pending."""

    def test_job_stale_volta_para_pending(self):
        init_db()
        j = criar_job("local_file", "/a.csv", "h1")
        claim_next_pending_job()

        count = requeue_stale_processing_jobs(timeout_seconds=0)

        assert count == 1
        refreshed = obter_job_por_id(j.id)
        assert refreshed.status == JobStatus.PENDING

    def test_retry_count_incrementa(self):
        init_db()
        j = criar_job("local_file", "/a.csv", "h1")
        claim_next_pending_job()
        requeue_stale_processing_jobs(timeout_seconds=0)

        refreshed = obter_job_por_id(j.id)

        assert refreshed.retry_count == 1

    def test_duplo_stale_recovery_incrementa_duas_vezes(self):
        init_db()
        j = criar_job("local_file", "/a.csv", "h1")

        claim_next_pending_job()
        requeue_stale_processing_jobs(timeout_seconds=0)
        claim_next_pending_job()
        requeue_stale_processing_jobs(timeout_seconds=0)

        refreshed = obter_job_por_id(j.id)
        assert refreshed.retry_count == 2
        assert refreshed.status == JobStatus.PENDING

    def test_nao_afeta_jobs_recentes(self):
        init_db()
        criar_job("local_file", "/a.csv", "h1")
        claim_next_pending_job()

        count = requeue_stale_processing_jobs(timeout_seconds=9999)

        assert count == 0


# ── idempotência ───────────────────────────────────────────────────────────


class TestIdempotencia:
    """Provar que conteúdo já processado gera skip com motivo correto."""

    def test_mesmo_hash_apos_sucesso_gera_skipped(self):
        init_db()
        j1 = criar_job_com_idempotencia("local_file", "/a.csv", "hash_x")
        atualizar_status(j1.id, "success", processed_records=5, total_records=5)

        j2 = criar_job_com_idempotencia("local_file", "/a.csv", "hash_x")

        assert j2.status == "skipped"

    def test_skip_reason_preenchido(self):
        init_db()
        j1 = criar_job_com_idempotencia("local_file", "/a.csv", "hash_x")
        atualizar_status(j1.id, "success")

        j2 = criar_job_com_idempotencia("local_file", "/a.csv", "hash_x")

        assert j2.skip_reason is not None
        assert "já processado" in j2.skip_reason.lower()

    def test_error_message_nulo_em_skip(self):
        init_db()
        j1 = criar_job_com_idempotencia("local_file", "/a.csv", "hash_x")
        atualizar_status(j1.id, "success")

        j2 = criar_job_com_idempotencia("local_file", "/a.csv", "hash_x")

        assert j2.error_message is None

    def test_hash_diferente_nao_gera_skip(self):
        init_db()
        j1 = criar_job_com_idempotencia("local_file", "/a.csv", "hash_a")
        atualizar_status(j1.id, "success")

        j2 = criar_job_com_idempotencia("local_file", "/a.csv", "hash_b")

        assert j2.status == JobStatus.PENDING

    def test_content_only_mesmo_hash_outra_origem_gera_skipped(self, monkeypatch):
        """Com IDEMPOTENCY_MODE=content_only, mesmo hash de outra origem deve ser skipped."""
        from config import config as cfg

        monkeypatch.setattr(cfg, "IDEMPOTENCY_MODE", "content_only")
        init_db()
        j1 = criar_job_com_idempotencia("local_file", "/a.csv", "hash_x")
        atualizar_status(j1.id, "success")

        j2 = criar_job_com_idempotencia("google_sheets", "other_id/Sheet1", "hash_x")

        assert j2.status == "skipped"


# ── retry automático (metadados) ────────────────────────────────────────────


class TestRetryMetadata:
    def test_erro_transitorio_agenda_retry_com_next_retry_at(self):
        init_db()
        j = criar_job("local_file", "/a.csv", "h1")
        claimed = claim_next_pending_job()
        assert claimed is not None

        next_retry_at = (datetime.now(timezone.utc).replace(microsecond=0) + timedelta(minutes=5)).isoformat()
        agendar_retry(claimed.id, next_retry_at=next_retry_at, last_error="Timeout")

        refreshed = obter_job_por_id(j.id)
        assert refreshed is not None
        assert refreshed.status == "pending"
        assert refreshed.error_type == "transient"
        assert refreshed.last_error is not None
        assert refreshed.next_retry_at == next_retry_at

    def test_erro_permanente_nao_agenda_retry(self):
        init_db()
        j = criar_job("local_file", "/a.csv", "h1")
        claim_next_pending_job()

        marcar_falha_definitiva(j.id, last_error="Dados inválidos", error_type=ErrorType.PERMANENT)

        refreshed = obter_job_por_id(j.id)
        assert refreshed is not None
        assert refreshed.status == "error"
        assert refreshed.error_type == ErrorType.PERMANENT
        assert refreshed.next_retry_at is None

    def test_sucesso_limpa_estado_de_erro_e_retry(self):
        init_db()
        j = criar_job("local_file", "/a.csv", "h1")
        claim_next_pending_job()

        next_retry_at = (datetime.now(timezone.utc).replace(microsecond=0) + timedelta(minutes=5)).isoformat()
        agendar_retry(j.id, next_retry_at=next_retry_at, last_error="Falha temporária")
        marcar_sucesso(j.id, processed_records=10, total_records=10)

        refreshed = obter_job_por_id(j.id)
        assert refreshed is not None
        assert refreshed.status == "success"
        assert refreshed.error_type is None
        assert refreshed.last_error is None
        assert refreshed.next_retry_at is None


# ── Configuração SQLite / robustez ────────────────────────────────────────────


class TestSQLiteConfig:
    def test_conexao_usa_wal_e_synchronous_normal(self):
        init_db()
        conn = _job_store_mod._conectar()
        try:
            cur = conn.execute("PRAGMA journal_mode;")
            (mode,) = cur.fetchone()
            assert str(mode).lower() == "wal"

            cur = conn.execute("PRAGMA synchronous;")
            (sync_level,) = cur.fetchone()
            # NORMAL = 1
            assert sync_level == 1
        finally:
            conn.close()

    def test_indices_principais_existem(self):
        init_db()
        conn = _job_store_mod._conectar()
        try:
            cur = conn.execute("PRAGMA index_list('jobs');")
            idx_names = {row[1] for row in cur.fetchall()}
            assert "idx_jobs_status" in idx_names
            assert "idx_jobs_hash_source" in idx_names
            assert "idx_jobs_status_next_retry" in idx_names
        finally:
            conn.close()

    def test_retry_curto_em_database_locked_no_claim(self, monkeypatch):
        init_db()
        criar_job("local_file", "/a.csv", "h1")

        original_connect = _job_store_mod._conectar
        calls = {"count": 0}

        class FakeConn:
            def __init__(self, real_conn):
                self._real = real_conn

            def execute(self, *args, **kwargs):
                calls["count"] += 1
                # Primeira chamada a BEGIN IMMEDIATE simula database locked
                if (
                    calls["count"] == 1
                    and isinstance(args[0], str)
                    and "BEGIN IMMEDIATE" in args[0]
                ):
                    raise sqlite3.OperationalError("database is locked")
                return self._real.execute(*args, **kwargs)

            def close(self):
                self._real.close()

        def fake_conectar():
            return FakeConn(original_connect())

        monkeypatch.setattr(_job_store_mod, "_conectar", fake_conectar)

        job = claim_next_pending_job()
        assert job is not None
        assert job.status == "processing"

    def test_with_lock_retry_nao_mascaras_erros_diferentes_de_lock(self, monkeypatch):
        init_db()

        original_connect = _job_store_mod._conectar
        calls = {"count": 0}

        class FakeConn:
            def __init__(self, real_conn):
                self._real = real_conn

            def execute(self, *args, **kwargs):
                calls["count"] += 1
                # Sempre lança um erro que NÃO é "database is locked"
                raise sqlite3.OperationalError("algum outro erro")

            def close(self):
                self._real.close()

        def fake_conectar():
            return FakeConn(original_connect())

        monkeypatch.setattr(_job_store_mod, "_conectar", fake_conectar)

        with pytest.raises(_job_store_mod.JobStoreError):
            _job_store_mod._with_lock_retry(
                lambda conn: conn.execute("BEGIN IMMEDIATE"),
                op_name="teste_erro_nao_lock",
            )


# ── Métricas básicas de saúde da fila ────────────────────────────────────────


class TestQueueMetrics:
    def test_contagem_por_status_e_error_type(self):
        init_db()
        j1 = criar_job("local_file", "/a.csv", "h1")
        j2 = criar_job("local_file", "/b.csv", "h2")
        j3 = criar_job("local_file", "/c.csv", "h3")

        # Marca alguns como success / error com tipos diferentes
        atualizar_status(j1.id, "success")
        marcar_falha_definitiva(j2.id, last_error="Erro permanente", error_type=ErrorType.PERMANENT)
        marcar_falha_definitiva(j3.id, last_error="Exausto", error_type=ErrorType.EXHAUSTED)

        por_status = obter_contagem_jobs_por_status()
        assert por_status[JobStatus.SUCCESS] == 1
        assert por_status[JobStatus.ERROR] == 2
        assert por_status.get(JobStatus.PENDING, 0) == 0

        por_error = obter_contagem_jobs_por_error_type()
        assert por_error[ErrorType.PERMANENT] == 1
        assert por_error[ErrorType.EXHAUSTED] == 1

    def test_job_pendente_mais_antigo(self):
        init_db()
        j1 = criar_job("local_file", "/a.csv", "h1")
        j2 = criar_job("local_file", "/b.csv", "h2")

        oldest = obter_job_pendente_mais_antigo()
        assert oldest is not None
        assert oldest.id == j1.id

        # Após reivindicar j1, o próximo pendente mais antigo deve ser j2
        claim_next_pending_job()
        oldest2 = obter_job_pendente_mais_antigo()
        assert oldest2 is not None
        assert oldest2.id == j2.id

    def test_ultima_execucao_com_sucesso(self):
        init_db()
        j1 = criar_job("local_file", "/a.csv", "h1")
        j2 = criar_job("local_file", "/b.csv", "h2")

        atualizar_status(j1.id, JobStatus.SUCCESS)
        first_ts = obter_ultima_execucao_com_sucesso()
        assert first_ts is not None

        # Marca outro success depois, timestamp deve avançar ou se manter no máximo
        atualizar_status(j2.id, JobStatus.SUCCESS)
        second_ts = obter_ultima_execucao_com_sucesso()
        assert second_ts is not None
        assert second_ts >= first_ts

    def test_estatisticas_recentes_retries_e_exhausted(self):
        init_db()
        j1 = criar_job("local_file", "/a.csv", "h1")
        j2 = criar_job("local_file", "/b.csv", "h2")

        # Simula um job com retries (attempt_count > 1)
        from config import config

        conn = sqlite3.connect(config.JOB_DB_PATH)
        try:
            conn.execute(
                "UPDATE jobs SET attempt_count = 2, updated_at = ? WHERE id = ?",
                (datetime.now(timezone.utc).replace(microsecond=0).isoformat(), j1.id),
            )
            conn.execute(
                "UPDATE jobs SET status = ?, error_type = ?, updated_at = ? WHERE id = ?",
                (
                    JobStatus.ERROR,
                    ErrorType.EXHAUSTED,
                    datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
                    j2.id,
                ),
            )
            conn.commit()
        finally:
            conn.close()

        stats = obter_estatisticas_recentes(janela_minutos=60)
        assert stats["retries"] >= 1
        assert stats["exhausted"] >= 1

    def test_lock_real_com_transacao_concorrente(self):
        """
        Usa duas conexões reais SQLite para simular disputa de lock em BEGIN IMMEDIATE.

        Cenário pragmático:
          - conn1 abre transação exclusiva em jobs (BEGIN IMMEDIATE).
          - Enquanto o lock está ativo, uma chamada direta a BEGIN IMMEDIATE
            por conn2 deve aguardar até o timeout curto da conexão.

        Não testa o retry interno (que atua via _conectar), mas garante que o
        comportamento real do SQLite sob WAL/timeout é previsível.
        """
        init_db()
        from config import config

        # Conexão 1: mantém um lock reservado/exclusivo.
        conn1 = sqlite3.connect(config.JOB_DB_PATH, timeout=5.0, isolation_level=None)
        conn2 = sqlite3.connect(config.JOB_DB_PATH, timeout=0.5, isolation_level=None)
        try:
            conn1.execute("BEGIN IMMEDIATE")

            inicio = datetime.now(timezone.utc)
            caught = None
            try:
                # Esta chamada deve bloquear até o timeout e então falhar com "database is locked".
                conn2.execute("BEGIN IMMEDIATE")
            except sqlite3.OperationalError as exc:
                caught = exc

            fim = datetime.now(timezone.utc)
            assert caught is not None
            assert "database is locked" in str(caught).lower()
            # Garante que houve espera pequena, não falha instantânea.
            delta = (fim - inicio).total_seconds()
            assert 0.3 <= delta <= 5.5
        finally:
            try:
                conn1.close()
            except Exception:
                pass
            try:
                conn2.close()
            except Exception:
                pass

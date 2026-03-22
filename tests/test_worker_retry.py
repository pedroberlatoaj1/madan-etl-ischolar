from datetime import datetime, timedelta, timezone

import pytest

from ischolar_client import ResultadoEnvio
from constants import ErrorType
from job_store import claim_next_pending_job, criar_job, init_db, obter_job_por_id
import worker
from worker import _falhar_job_com_retry, classify_error, processar_job


class TestWorkerRetry:
    def test_worker_transient_agenda_retry_com_backoff(self):
        init_db()
        import os

        # Garante que o arquivo de origem exista para que o erro venha da API,
        # e não de FileNotFoundError no carregamento.
        tmp_csv = "tmp_retry.csv"
        with open(tmp_csv, "w", encoding="utf-8") as f:
            f.write("coluna\nvalor\n")

        criar_job("local_file", tmp_csv, "h1")
        job = claim_next_pending_job()
        assert job is not None

        antes = datetime.now(timezone.utc).replace(microsecond=0)
        _falhar_job_com_retry(job=job, mensagem="Timeout", tipo=ErrorType.TRANSIENT)

        refreshed = obter_job_por_id(job.id)
        assert refreshed is not None
        assert refreshed.status == "pending"
        assert refreshed.error_type == ErrorType.TRANSIENT
        assert refreshed.next_retry_at is not None

        dt = datetime.fromisoformat(refreshed.next_retry_at)
        assert dt > antes + timedelta(minutes=4)
        assert dt < antes + timedelta(minutes=6)

    def test_worker_permanent_nao_agenda_retry(self):
        init_db()
        import os

        # Garante que o arquivo de origem exista para que o erro venha da API,
        # e não de FileNotFoundError no carregamento.
        tmp_csv = "tmp_retry.csv"
        with open(tmp_csv, "w", encoding="utf-8") as f:
            f.write("coluna\nvalor\n")

        criar_job("local_file", tmp_csv, "h1")
        job = claim_next_pending_job()
        assert job is not None

        _falhar_job_com_retry(job=job, mensagem="Dados inválidos", tipo=ErrorType.PERMANENT)

        refreshed = obter_job_por_id(job.id)
        assert refreshed is not None
        assert refreshed.status == "error"
        assert refreshed.error_type == ErrorType.PERMANENT
        assert refreshed.next_retry_at is None

    def test_worker_excede_limite_e_marca_exhausted(self):
        init_db()
        import os

        # Garante que o arquivo de origem exista para que o erro venha da API,
        # e não de FileNotFoundError no carregamento.
        tmp_csv = "tmp_retry.csv"
        with open(tmp_csv, "w", encoding="utf-8") as f:
            f.write("coluna\nvalor\n")

        criar_job("local_file", tmp_csv, "h1")
        job = claim_next_pending_job()
        assert job is not None

        job.attempt_count = 4
        job.max_attempts = 4
        _falhar_job_com_retry(job=job, mensagem="Falha temporária", tipo=ErrorType.TRANSIENT)

        refreshed = obter_job_por_id(job.id)
        assert refreshed is not None
        assert refreshed.status == "error"
        assert refreshed.error_type == ErrorType.EXHAUSTED

    def test_fluxo_completo_exaustao_real(self):
        """
        Fluxo completo:
          - claim
          - falha transitória
          - retry agendado
          - novo claim após next_retry_at vencido
          - repetir até esgotar tentativas
        """

        class FakeClient:
            def enviar_notas(self, **kwargs):
                return ResultadoEnvio(
                    sucesso=False,
                    status_code=503,
                    transitório=True,
                    mensagem="HTTP 503 (transitório)",
                )

        init_db()
        criar_job("local_file", "/a.csv", "h1")

        for tentativa in range(1, 5):
            job = claim_next_pending_job()
            # claim incrementa attempt_count de forma real
            assert job is not None
            assert job.attempt_count == tentativa

            # Simula falha transitória via função central de retry do worker
            _falhar_job_com_retry(job=job, mensagem="Falha temporária", tipo=ErrorType.TRANSIENT)

            refreshed = obter_job_por_id(job.id)
            assert refreshed is not None

            if tentativa < 4:
                # Ainda em modo retry
                assert refreshed.status == "pending"
                assert refreshed.error_type == ErrorType.TRANSIENT
                assert refreshed.next_retry_at is not None

                # Força o vencimento do next_retry_at para não precisar esperar
                passado = datetime.now(timezone.utc).replace(microsecond=0) - timedelta(
                    minutes=1
                )
                passado_iso = passado.isoformat()

                from config import config
                import sqlite3

                conn = sqlite3.connect(config.JOB_DB_PATH)
                try:
                    conn.execute(
                        "UPDATE jobs SET next_retry_at = ? WHERE id = ?",
                        (passado_iso, job.id),
                    )
                    conn.commit()
                finally:
                    conn.close()
            else:
                # Excedeu tentativas: falha definitiva
                assert refreshed.status == "error"
                assert refreshed.error_type == "exhausted"

    def test_nao_envia_alerta_para_retry_transitorio(self, monkeypatch):
        init_db()
        criar_job("local_file", "/a.csv", "h1")
        job = claim_next_pending_job()
        assert job is not None

        chamado = {"flag": False}

        def fake_alertar(**kwargs):
            chamado["flag"] = True

        monkeypatch.setattr(worker, "alertar_falha_definitiva", fake_alertar)

        _falhar_job_com_retry(job=job, mensagem="Falha temporária", tipo=ErrorType.TRANSIENT)

        assert chamado["flag"] is False

    def test_envia_alerta_em_falha_permanente(self, monkeypatch):
        init_db()
        criar_job("local_file", "/a.csv", "h1")
        job = claim_next_pending_job()
        assert job is not None

        chamado = {"flag": False}

        def fake_alertar(**kwargs):
            chamado["flag"] = True
            chamado["kwargs"] = kwargs

        monkeypatch.setattr(worker, "alertar_falha_definitiva", fake_alertar)

        _falhar_job_com_retry(job=job, mensagem="Erro permanente", tipo=ErrorType.PERMANENT)

        assert chamado["flag"] is True
        assert chamado["kwargs"]["error_type"] == "permanent"

    def test_envia_alerta_quando_excede_tentativas(self, monkeypatch):
        init_db()
        criar_job("local_file", "/a.csv", "h1")
        job = claim_next_pending_job()
        assert job is not None

        job.attempt_count = 4
        job.max_attempts = 4

        chamado = {"flag": False}

        def fake_alertar(**kwargs):
            chamado["flag"] = True
            chamado["kwargs"] = kwargs

        monkeypatch.setattr(worker, "alertar_falha_definitiva", fake_alertar)

        _falhar_job_com_retry(job=job, mensagem="Falha temporária", tipo=ErrorType.TRANSIENT)

        assert chamado["flag"] is True
        assert chamado["kwargs"]["error_type"] == "exhausted"

    def test_falha_no_alerta_nao_derruba_fluxo(self, monkeypatch):
        init_db()
        criar_job("local_file", "/a.csv", "h1")
        job = claim_next_pending_job()
        assert job is not None

        def fake_alertar(**kwargs):
            raise RuntimeError("falha no alerta")

        monkeypatch.setattr(worker, "alertar_falha_definitiva", fake_alertar)

        # Não deve levantar exceção para o chamador
        _falhar_job_com_retry(job=job, mensagem="Erro permanente", tipo=ErrorType.PERMANENT)

        refreshed = obter_job_por_id(job.id)
        assert refreshed is not None
        assert refreshed.status == "error"


class TestClassifyError:
    def test_value_error_eh_permanent(self):
        assert classify_error(ValueError("coluna obrigatória ausente")) == ErrorType.PERMANENT

    def test_requests_timeout_eh_transient(self):
        requests = pytest.importorskip("requests")
        assert classify_error(requests.exceptions.Timeout("timeout")) == ErrorType.TRANSIENT


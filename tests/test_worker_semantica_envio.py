from types import SimpleNamespace

import pandas as pd
import pytest

import worker
from ischolar_client import ResultadoEnvio
from constants import ErrorType


@pytest.fixture
def job_base(tmp_path):
    # Objeto mínimo compatível com o que o worker acessa em processar_job()
    return SimpleNamespace(
        id=123,
        source_type=worker.SOURCE_LOCAL_FILE,
        source_identifier=str(tmp_path / "a.csv"),
        content_hash="h1",
        attempt_count=1,
        max_attempts=4,
    )


class FakeClient:
    def __init__(self, resultados):
        self._resultados = list(resultados)
        self.calls = []

    def enviar_notas(self, **kwargs):
        self.calls.append(kwargs)
        if not self._resultados:
            raise AssertionError("FakeClient sem mais resultados configurados")
        return self._resultados.pop(0)


def _noop(*args, **kwargs):
    return None


class TestWorkerSemanticaEnvioIdempotente:
    def test_dataframe_vazio_retorna_success_empty(self, monkeypatch, job_base):
        monkeypatch.setattr(worker, "_carregar_e_transformar", lambda job: pd.DataFrame([]))
        monkeypatch.setattr(worker, "atualizar_heartbeat", _noop)

        marcado = {}

        def fake_marcar_sucesso(job_id, processed_records, total_records, result_summary=None):
            marcado["job_id"] = job_id
            marcado["processed_records"] = processed_records
            marcado["total_records"] = total_records
            marcado["result_summary"] = result_summary

        monkeypatch.setattr(worker, "marcar_sucesso", fake_marcar_sucesso)
        monkeypatch.setattr(worker, "registrar_erro", _noop)

        res = worker.processar_job(job_base, client=FakeClient([]))
        assert res == "success_empty"
        assert marcado == {"job_id": 123, "processed_records": 0, "total_records": 0, "result_summary": None}

    def test_transitorio_true_agenda_retry_e_retorna_error(self, monkeypatch, job_base):
        df = pd.DataFrame(
            [{"id_matricula": 115, "identificacao": 1, "valor": 8.5, "data_lancamento": "2026-03-16"}]
        )
        monkeypatch.setattr(worker, "_carregar_e_transformar", lambda job: df)
        monkeypatch.setattr(worker, "atualizar_heartbeat", _noop)

        falha = {}

        def fake_falhar_job_com_retry(*, job, mensagem, tipo, context=None):
            falha["job_id"] = job.id
            falha["mensagem"] = mensagem
            falha["tipo"] = tipo
            falha["context"] = context or {}

        monkeypatch.setattr(worker, "_falhar_job_com_retry", fake_falhar_job_com_retry)
        monkeypatch.setattr(worker, "registrar_erro", _noop)

        client = FakeClient(
            [
                ResultadoEnvio(
                    sucesso=False,
                    transitorio=True,
                    status_code=503,
                    mensagem="Erro Transitório (503): upstream",
                )
            ]
        )

        res = worker.processar_job(job_base, client=client)
        assert res == "error"
        assert falha["job_id"] == 123
        assert falha["tipo"] == ErrorType.TRANSIENT
        assert "Transitório" in falha["mensagem"]

    def test_mensagem_resumo_com_conflicts_transitorio_false_trata_como_success(self, monkeypatch, job_base):
        df = pd.DataFrame(
            [
                {"id_matricula": 115, "identificacao": 1, "valor": 8.5, "data_lancamento": "2026-03-16"},
                {"id_matricula": 116, "identificacao": 2, "valor": 9.0, "data_lancamento": "2026-03-16"},
            ]
        )
        monkeypatch.setattr(worker, "_carregar_e_transformar", lambda job: df)
        monkeypatch.setattr(worker, "atualizar_heartbeat", _noop)
        monkeypatch.setattr(worker, "registrar_erro", _noop)

        marcado = {}

        def fake_marcar_sucesso(job_id, processed_records, total_records, result_summary=None):
            marcado["job_id"] = job_id
            marcado["processed_records"] = processed_records
            marcado["total_records"] = total_records
            marcado["result_summary"] = result_summary

        monkeypatch.setattr(worker, "marcar_sucesso", fake_marcar_sucesso)

        client = FakeClient(
            [
                ResultadoEnvio(
                    sucesso=True,
                    transitorio=False,
                    mensagem="Lote finalizado. Total: 2 | Criadas: 1 | Puladas: 0 | Conflitos: 1 | Falhas Permanentes: 0",
                )
            ]
        )

        res = worker.processar_job(job_base, client=client)
        assert res == "success"
        assert marcado["job_id"] == 123
        assert marcado["processed_records"] == 2
        assert marcado["total_records"] == 2
        assert "Conflitos" in (marcado["result_summary"] or "")

    def test_repetir_tentativa_apos_transitorio_nao_quebra_fluxo(self, monkeypatch, job_base):
        df = pd.DataFrame(
            [{"id_matricula": 115, "identificacao": 1, "valor": 8.5, "data_lancamento": "2026-03-16"}]
        )
        monkeypatch.setattr(worker, "_carregar_e_transformar", lambda job: df)
        monkeypatch.setattr(worker, "atualizar_heartbeat", _noop)
        monkeypatch.setattr(worker, "registrar_erro", _noop)

        falhas = []

        def fake_falhar_job_com_retry(*, job, mensagem, tipo, context=None):
            falhas.append({"job_id": job.id, "tipo": tipo, "mensagem": mensagem})

        monkeypatch.setattr(worker, "_falhar_job_com_retry", fake_falhar_job_com_retry)

        marcados = []

        def fake_marcar_sucesso(job_id, processed_records, total_records, result_summary=None):
            marcados.append((job_id, processed_records, total_records, result_summary))

        monkeypatch.setattr(worker, "marcar_sucesso", fake_marcar_sucesso)

        client = FakeClient(
            [
                ResultadoEnvio(sucesso=False, transitorio=True, status_code=503, mensagem="timeout"),
                ResultadoEnvio(
                    sucesso=True,
                    transitorio=False,
                    mensagem="Lote finalizado. Total: 1 | Criadas: 0 | Puladas: 1 | Conflitos: 0 | Falhas Permanentes: 0",
                ),
            ]
        )

        # 1ª tentativa: falha transitória -> error operacional com retry
        res1 = worker.processar_job(job_base, client=client)
        assert res1 == "error"
        assert falhas and falhas[0]["tipo"] == ErrorType.TRANSIENT

        # 2ª tentativa: sucesso determinístico -> success
        job2 = SimpleNamespace(**{**job_base.__dict__, "attempt_count": 2})
        res2 = worker.processar_job(job2, client=client)
        assert res2 == "success"
        assert len(marcados) == 1
        assert marcados[0][0:3] == (123, 1, 1)
        assert "Puladas" in (marcados[0][3] or "")


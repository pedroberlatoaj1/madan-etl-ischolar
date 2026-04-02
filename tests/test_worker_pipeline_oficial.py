from __future__ import annotations

from typing import Any

import pandas as pd

import worker
from constants import ErrorType, JobType
from job_store import (
    claim_next_pending_job,
    criar_job_aprovacao_envio,
    criar_job_validacao_google_sheets,
    obter_job_por_id,
)
from pipeline_runner import (
    STATUS_APPROVAL_JOB_QUEUED,
    STATUS_SEND_RETRY_SCHEDULED,
    STATUS_SEND_FAILED,
    STATUS_VALIDATION_PENDING_APPROVAL,
    executar_validacao,
    registrar_solicitacao_aprovacao_envio,
)
from resultado_envio_lote_store import ResultadoEnvioLoteStore
from snapshot_store import save_snapshot
from aprovacao_lote_store import AprovacaoLoteStore
from validacao_lote_store import ValidacaoLoteStore


def _df_valido() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "Estudante": "Ana Silva",
                "RA": "RA001",
                "Turma": "2A",
                "Trimestre": "1",
                "Disciplina": "Matematica",
                "Frente - Professor": "Mat - Prof Silva",
                "AV 1 (OBJ)": "4",
                "AV 1 (DISC)": "4",
                "Simulado": "9",
            }
        ]
    )


def _job_payload(tmp_path) -> dict[str, Any]:
    return {
        "db_validacoes": str(tmp_path / "validacoes.db"),
        "db_aprovacoes": str(tmp_path / "aprovacoes.db"),
        "db_itens": str(tmp_path / "itens.db"),
        "db_audit": str(tmp_path / "audit.db"),
        "db_resultados_envio": str(tmp_path / "resultados_envio.db"),
        "mapa_disciplinas": "mapa_disciplinas.json",
        "mapa_avaliacoes": "mapa_avaliacoes.json",
        "mapa_professores": "mapa_professores.json",
    }


def test_worker_processa_job_validacao_oficial(tmp_path):
    payload = _job_payload(tmp_path)
    dados = _df_valido().to_dict(orient="records")

    job = criar_job_validacao_google_sheets(
        source_identifier="spreadsheet-1/Notas",
        content_hash="snapshot-validacao",
        lote_id="lote-worker-validacao",
        total_records=len(dados),
        payload=payload,
    )
    save_snapshot(
        job_id=int(job.id),
        records=dados,
        source_identifier="spreadsheet-1/Notas",
        spreadsheet_id="spreadsheet-1",
        sheet_name="Notas",
        content_hash="snapshot-validacao",
    )

    claimed = claim_next_pending_job()
    assert claimed is not None
    assert claimed.job_type == JobType.GOOGLE_SHEETS_VALIDATION

    resultado = worker.processar_job(claimed)
    assert resultado in {"success", "success_empty"}

    validacao = ValidacaoLoteStore(payload["db_validacoes"]).carregar("lote-worker-validacao")
    assert validacao is not None
    assert validacao.status == STATUS_VALIDATION_PENDING_APPROVAL


def test_worker_aprovacao_envio_transiente_persiste_retry(tmp_path, monkeypatch):
    payload = _job_payload(tmp_path)
    validation_store = ValidacaoLoteStore(payload["db_validacoes"])
    approval_store = AprovacaoLoteStore(payload["db_aprovacoes"])
    result_store = ResultadoEnvioLoteStore(payload["db_resultados_envio"])

    resultado_validacao = executar_validacao(
        lote_id="lote-worker-aprovacao",
        entrada=_df_valido(),
        validation_store=validation_store,
        snapshot_hash="snapshot-aprovacao",
    )

    job = criar_job_aprovacao_envio(
        lote_id="lote-worker-aprovacao",
        aprovado_por="Gestor",
        snapshot_hash=resultado_validacao["snapshot_hash"],
        source_identifier="lote-worker-aprovacao",
        payload=payload,
    )
    registro = registrar_solicitacao_aprovacao_envio(
        lote_id="lote-worker-aprovacao",
        job_id=int(job.id),
        aprovado_por="Gestor",
        validation_store=validation_store,
        approval_store=approval_store,
        result_store=result_store,
        expected_snapshot_hash=resultado_validacao["snapshot_hash"],
    )
    assert registro["send_result"]["status"] == STATUS_APPROVAL_JOB_QUEUED

    def fake_execute(**kwargs):
        raise OSError("timeout na chamada externa")

    monkeypatch.setattr(worker, "executar_aprovacao_e_envio", fake_execute)

    claimed = claim_next_pending_job()
    assert claimed is not None
    assert claimed.job_type == JobType.APPROVAL_AND_SEND

    resultado = worker.processar_job(claimed)
    assert resultado == "error"

    job_atual = obter_job_por_id(int(job.id))
    assert job_atual is not None
    assert job_atual.status == "pending"
    assert job_atual.error_type == ErrorType.TRANSIENT

    resultado_envio = result_store.carregar("lote-worker-aprovacao")
    assert resultado_envio is not None
    assert resultado_envio.status == STATUS_SEND_RETRY_SCHEDULED

    validacao = validation_store.carregar("lote-worker-aprovacao")
    assert validacao is not None
    assert validacao.status == STATUS_SEND_RETRY_SCHEDULED


def test_worker_aprovacao_envio_falha_permanente_persiste_resultado(tmp_path, monkeypatch):
    payload = _job_payload(tmp_path)
    validation_store = ValidacaoLoteStore(payload["db_validacoes"])
    approval_store = AprovacaoLoteStore(payload["db_aprovacoes"])
    result_store = ResultadoEnvioLoteStore(payload["db_resultados_envio"])

    resultado_validacao = executar_validacao(
        lote_id="lote-worker-falha",
        entrada=_df_valido(),
        validation_store=validation_store,
        snapshot_hash="snapshot-falha",
    )

    job = criar_job_aprovacao_envio(
        lote_id="lote-worker-falha",
        aprovado_por="Gestor",
        snapshot_hash=resultado_validacao["snapshot_hash"],
        source_identifier="lote-worker-falha",
        payload=payload,
    )
    registrar_solicitacao_aprovacao_envio(
        lote_id="lote-worker-falha",
        job_id=int(job.id),
        aprovado_por="Gestor",
        validation_store=validation_store,
        approval_store=approval_store,
        result_store=result_store,
        expected_snapshot_hash=resultado_validacao["snapshot_hash"],
    )

    def fake_execute(**kwargs):
        raise ValueError("falha de negocio")

    monkeypatch.setattr(worker, "executar_aprovacao_e_envio", fake_execute)

    claimed = claim_next_pending_job()
    assert claimed is not None

    resultado = worker.processar_job(claimed)
    assert resultado == "error"

    job_atual = obter_job_por_id(int(job.id))
    assert job_atual is not None
    assert job_atual.status == "error"
    assert job_atual.error_type == ErrorType.PERMANENT

    resultado_envio = result_store.carregar("lote-worker-falha")
    assert resultado_envio is not None
    assert resultado_envio.status == STATUS_SEND_FAILED

    validacao = validation_store.carregar("lote-worker-falha")
    assert validacao is not None
    assert validacao.status == STATUS_SEND_FAILED

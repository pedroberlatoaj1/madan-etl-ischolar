from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

import pandas as pd
import pytest

from aprovacao_lote_store import AprovacaoLoteStore
from envio_lote import ResultadoResolucaoIDs, ResolvedorIDsAbstrato
from envio_lote_audit_store import EnvioLoteAuditStore
from lote_itens_store import LoteItensStore
from resultado_envio_lote_store import ResultadoEnvioLoteStore
from pipeline_runner import (
    LoteJaAprovadoError,
    LoteNaoElegivelError,
    STATUS_APPROVAL_JOB_QUEUED,
    STATUS_DRY_RUN_COMPLETED,
    STATUS_SEND_RETRY_SCHEDULED,
    STATUS_SENT,
    STATUS_VALIDATION_FAILED,
    STATUS_VALIDATION_PENDING_APPROVAL,
    SnapshotStaleError,
    executar_aprovacao_e_envio,
    executar_validacao,
    registrar_solicitacao_aprovacao_envio,
)
from validacao_lote_store import ValidacaoLoteStore


def _df_valido() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "Estudante": "Ana Silva",
                "RA": "RA001",
                "Turma": "2A",
                "Trimestre": "1",
                "Disciplina": "Matemática",
                "Frente - Professor": "Mat - Prof Silva",
                "AV 1 (OBJ)": "4",
                "AV 1 (DISC)": "4",
                "Simulado": "9",
            }
        ]
    )


def _df_invalido() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "Estudante": "Beto",
                "RA": "RA002",
                "Turma": "2A",
                "Trimestre": "1",
                "Disciplina": "Física",
                "Frente - Professor": "",
                "AV 1 (OBJ)": "12",
                "AV 1 (DISC)": "8",
            }
        ]
    )


@dataclass
class FakeResultadoLancamento:
    sucesso: bool = True
    transitorio: bool = False
    mensagem: str = "ok"
    payload: Optional[dict[str, Any]] = None
    dados: Optional[Any] = None
    rastreabilidade: dict[str, Any] = field(default_factory=dict)


class FakeClient:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def lancar_nota(
        self,
        *,
        id_matricula: Optional[int] = None,
        id_disciplina: int,
        id_avaliacao: int,
        valor_bruta: Any,
        id_professor: Optional[int] = None,
        dry_run: bool = False,
    ) -> FakeResultadoLancamento:
        self.calls.append(
            {
                "id_matricula": id_matricula,
                "id_disciplina": id_disciplina,
                "id_avaliacao": id_avaliacao,
                "valor_bruta": valor_bruta,
                "id_professor": id_professor,
                "dry_run": dry_run,
            }
        )
        return FakeResultadoLancamento(
            sucesso=True,
            mensagem="dry_run=True: payload montado." if dry_run else "enviado com sucesso",
            payload={"id_matricula": id_matricula, "id_disciplina": id_disciplina},
        )


class ResolvedorFixo(ResolvedorIDsAbstrato):
    def resolver_ids(self, lancamento):
        return ResultadoResolucaoIDs(
            id_matricula=101,
            id_disciplina=202,
            id_avaliacao=303,
            id_professor=None,
            erros=[],
        )


def _stores():
    return (
        ValidacaoLoteStore(":memory:"),
        AprovacaoLoteStore(":memory:"),
        LoteItensStore(":memory:"),
        EnvioLoteAuditStore(":memory:"),
    )


def test_runner_validacao_persiste_resultado_pendente_aprovacao():
    validation_store, _, _, _ = _stores()

    resultado = executar_validacao(
        lote_id="lote-validacao",
        entrada=_df_valido(),
        validation_store=validation_store,
        job_id=77,
        snapshot_hash="snapshot-abc",
    )

    assert resultado["status"] == STATUS_VALIDATION_PENDING_APPROVAL
    assert resultado["job_id"] == 77
    assert resultado["snapshot_hash"] == "snapshot-abc"
    assert resultado["apto_para_aprovacao"] is True

    persistido = validation_store.carregar("lote-validacao")
    assert persistido is not None
    assert persistido.status == STATUS_VALIDATION_PENDING_APPROVAL
    assert persistido.job_id == 77
    assert persistido.snapshot_hash == "snapshot-abc"
    assert persistido.apto_para_aprovacao is True
    assert persistido.itens_sendaveis


def test_runner_aprovacao_e_envio_conclui_fluxo_oficial():
    validation_store, approval_store, itens_store, audit_store = _stores()
    client = FakeClient()

    executar_validacao(
        lote_id="lote-envio",
        entrada=_df_valido(),
        validation_store=validation_store,
        snapshot_hash="snapshot-ok",
    )

    resultado = executar_aprovacao_e_envio(
        lote_id="lote-envio",
        aprovado_por="Gestor",
        validation_store=validation_store,
        approval_store=approval_store,
        itens_store=itens_store,
        audit_store=audit_store,
        cliente=client,
        resolvedor=ResolvedorFixo(),
    )

    assert resultado["status"] == STATUS_SENT
    assert resultado["envio"]["sucesso"] is True
    assert resultado["aprovacao"]["status"] == "aprovado_para_envio"
    assert client.calls


def test_runner_aprovacao_e_envio_dry_run_retorna_status_serializavel():
    validation_store, approval_store, itens_store, audit_store = _stores()

    executar_validacao(
        lote_id="lote-dry",
        entrada=_df_valido(),
        validation_store=validation_store,
        snapshot_hash="snapshot-dry",
    )

    resultado = executar_aprovacao_e_envio(
        lote_id="lote-dry",
        aprovado_por="Gestor",
        validation_store=validation_store,
        approval_store=approval_store,
        itens_store=itens_store,
        audit_store=audit_store,
        cliente=FakeClient(),
        resolvedor=ResolvedorFixo(),
        dry_run=True,
    )

    assert resultado["status"] == STATUS_DRY_RUN_COMPLETED
    assert resultado["envio"]["sucesso"] is True
    assert resultado["envio"]["total_dry_run"] >= 1


def test_runner_lote_inelegivel_bloqueia_aprovacao_e_envio():
    validation_store, approval_store, itens_store, audit_store = _stores()

    resultado = executar_validacao(
        lote_id="lote-inelegivel",
        entrada=_df_invalido(),
        validation_store=validation_store,
        snapshot_hash="snapshot-bad",
    )

    assert resultado["status"] == STATUS_VALIDATION_FAILED
    assert resultado["apto_para_aprovacao"] is False

    with pytest.raises(LoteNaoElegivelError):
        executar_aprovacao_e_envio(
            lote_id="lote-inelegivel",
            aprovado_por="Gestor",
            validation_store=validation_store,
            approval_store=approval_store,
            itens_store=itens_store,
            audit_store=audit_store,
            cliente=FakeClient(),
            resolvedor=ResolvedorFixo(),
        )


def test_runner_dupla_aprovacao_e_rejeitada():
    validation_store, approval_store, itens_store, audit_store = _stores()

    executar_validacao(
        lote_id="lote-duplo",
        entrada=_df_valido(),
        validation_store=validation_store,
        snapshot_hash="snapshot-duplo",
    )

    executar_aprovacao_e_envio(
        lote_id="lote-duplo",
        aprovado_por="Gestor",
        validation_store=validation_store,
        approval_store=approval_store,
        itens_store=itens_store,
        audit_store=audit_store,
        cliente=FakeClient(),
        resolvedor=ResolvedorFixo(),
        dry_run=True,
    )

    with pytest.raises(LoteJaAprovadoError):
        executar_aprovacao_e_envio(
            lote_id="lote-duplo",
            aprovado_por="Gestor 2",
            validation_store=validation_store,
            approval_store=approval_store,
            itens_store=itens_store,
            audit_store=audit_store,
            cliente=FakeClient(),
            resolvedor=ResolvedorFixo(),
            dry_run=True,
        )


def test_runner_snapshot_stale_impede_aprovacao_e_envio():
    validation_store, approval_store, itens_store, audit_store = _stores()

    executar_validacao(
        lote_id="lote-stale",
        entrada=_df_valido(),
        validation_store=validation_store,
        snapshot_hash="snapshot-atual",
    )

    with pytest.raises(SnapshotStaleError):
        executar_aprovacao_e_envio(
            lote_id="lote-stale",
            aprovado_por="Gestor",
            validation_store=validation_store,
            approval_store=approval_store,
            itens_store=itens_store,
            audit_store=audit_store,
            cliente=FakeClient(),
            resolvedor=ResolvedorFixo(),
            expected_snapshot_hash="snapshot-antigo",
        )


def test_runner_registra_estado_de_envio_e_identidade_estruturada():
    validation_store = ValidacaoLoteStore(":memory:")
    approval_store = AprovacaoLoteStore(":memory:")
    itens_store = LoteItensStore(":memory:")
    audit_store = EnvioLoteAuditStore(":memory:")
    result_store = ResultadoEnvioLoteStore(":memory:")

    resultado_validacao = executar_validacao(
        lote_id="lote-identidade",
        entrada=_df_valido(),
        validation_store=validation_store,
        snapshot_hash="snapshot-identidade",
    )

    registro = registrar_solicitacao_aprovacao_envio(
        lote_id="lote-identidade",
        job_id=901,
        aprovado_por="Coordenacao",
        approval_identity={
            "aprovador_nome_informado": "Coordenacao",
            "aprovador_email": "coord@example.com",
            "aprovador_origem": "google_apps_script_session",
        },
        validation_store=validation_store,
        approval_store=approval_store,
        result_store=result_store,
        expected_snapshot_hash=resultado_validacao["snapshot_hash"],
    )

    assert registro["status"] == STATUS_APPROVAL_JOB_QUEUED
    assert registro["send_result"]["status"] == STATUS_APPROVAL_JOB_QUEUED
    assert registro["send_result"]["aprovador"]["email"] == "coord@example.com"
    assert registro["send_result"]["aprovador"]["identity_strength"] == "medium"


def test_runner_permite_retomada_de_retry_transitorio_no_mesmo_snapshot():
    validation_store = ValidacaoLoteStore(":memory:")
    approval_store = AprovacaoLoteStore(":memory:")
    itens_store = LoteItensStore(":memory:")
    audit_store = EnvioLoteAuditStore(":memory:")
    result_store = ResultadoEnvioLoteStore(":memory:")

    resultado_validacao = executar_validacao(
        lote_id="lote-retry",
        entrada=_df_valido(),
        validation_store=validation_store,
        snapshot_hash="snapshot-retry",
    )
    registrar_solicitacao_aprovacao_envio(
        lote_id="lote-retry",
        job_id=10,
        aprovado_por="Gestor",
        validation_store=validation_store,
        approval_store=approval_store,
        result_store=result_store,
        expected_snapshot_hash=resultado_validacao["snapshot_hash"],
    )
    atual = validation_store.carregar("lote-retry")
    assert atual is not None
    atual.status = STATUS_SEND_RETRY_SCHEDULED
    validation_store.salvar(atual)
    retry_result = result_store.carregar("lote-retry")
    assert retry_result is not None
    retry_result.status = STATUS_SEND_RETRY_SCHEDULED
    result_store.salvar(retry_result)

    resultado = executar_aprovacao_e_envio(
        lote_id="lote-retry",
        aprovado_por="Gestor",
        validation_store=validation_store,
        approval_store=approval_store,
        itens_store=itens_store,
        result_store=result_store,
        audit_store=audit_store,
        cliente=FakeClient(),
        resolvedor=ResolvedorFixo(),
        dry_run=True,
        expected_snapshot_hash="snapshot-retry",
        job_id=10,
    )

    assert resultado["status"] == STATUS_DRY_RUN_COMPLETED

from __future__ import annotations

import time
import uuid
from typing import Any

import pytest

pytest.importorskip("flask", reason="Os testes do webhook exigem Flask instalado no ambiente de desenvolvimento.")

import worker
from constants import JobType
from job_store import claim_next_pending_job, criar_job, obter_job_por_id, registrar_erro
from pipeline_runner import (
    STATUS_APPROVAL_JOB_QUEUED,
    STATUS_SENT,
    STATUS_VALIDATION_JOB_QUEUED,
    STATUS_VALIDATION_PENDING_APPROVAL,
    registrar_resultado_envio,
)
from resultado_envio_lote_store import ResultadoEnvioLoteStore
from validacao_lote_store import ValidacaoLoteStore
from webhook_google_sheets import create_app


def _payload(lote_id: str = "lote-http") -> dict[str, Any]:
    return {
        "spreadsheet_id": "spreadsheet-123",
        "sheet_name": "Notas",
        "lote_id": lote_id,
        "dados": [
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
        ],
    }

def _headers(secret: str = "segredo-teste", *, with_antireplay: bool = True, nonce: str | None = None) -> dict[str, str]:
    headers = {"X-Webhook-Secret": secret}
    if with_antireplay:
        headers["X-Webhook-Timestamp"] = str(int(time.time()))
        headers["X-Webhook-Nonce"] = nonce or str(uuid.uuid4())
    return headers


@pytest.fixture
def app(tmp_path):
    app = create_app(
        {
            "TESTING": True,
            "WEBHOOK_SECRET": "segredo-teste",
            "VALIDACAO_LOTE_DB": str(tmp_path / "validacoes.db"),
            "APROVACAO_LOTE_DB": str(tmp_path / "aprovacoes.db"),
            "LOTE_ITENS_DB": str(tmp_path / "itens.db"),
            "ENVIO_LOTE_AUDIT_DB": str(tmp_path / "audit.db"),
            "RESULTADO_ENVIO_LOTE_DB": str(tmp_path / "resultados_envio.db"),
            "MAPA_DISCIPLINAS": "mapa_disciplinas.json",
            "MAPA_AVALIACOES": "mapa_avaliacoes.json",
            "MAPA_PROFESSORES": "mapa_professores.json",
            "MAX_ROWS_PER_REQUEST": 2,
            "RATE_LIMIT_MAX_REQUESTS": 100,
        }
    )
    return app


@pytest.fixture
def client(app):
    return app.test_client()


def _processar_validacao_pendente():
    job = claim_next_pending_job()
    assert job is not None
    assert job.job_type == JobType.GOOGLE_SHEETS_VALIDATION
    resultado = worker.processar_job(job)
    assert resultado in {"success", "success_empty"}
    return job


def test_post_webhook_notas_cria_job_validacao(client, app):
    resp = client.post("/webhook/notas", json=_payload(), headers=_headers())

    assert resp.status_code == 202
    body = resp.get_json()
    assert body["status"] == "accepted"
    assert body["lote_id"] == "lote-http"
    assert "validacao" in body
    assert body["polling"]["endpoint"] == "/lote/lote-http/validacao"
    assert body["mensagem"]

    job = obter_job_por_id(body["job_id"])
    assert job is not None
    assert job.job_type == JobType.GOOGLE_SHEETS_VALIDATION

    store = ValidacaoLoteStore(app.config["VALIDACAO_LOTE_DB"])
    validacao = store.carregar("lote-http")
    assert validacao is not None
    assert validacao.status == STATUS_VALIDATION_JOB_QUEUED


def test_get_validacao_em_fila_expoe_contrato_para_polling(client):
    client.post("/webhook/notas", json=_payload(), headers=_headers())

    resp = client.get("/lote/lote-http/validacao", headers=_headers())
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["status"] == STATUS_VALIDATION_JOB_QUEUED
    assert body["finalizado"] is False
    assert body["pode_aprovar"] is False
    assert body["polling"]["endpoint"] == "/lote/lote-http/validacao"
    assert body["mensagem"]


def test_get_validacao_retorna_resultado_persistido_apos_worker(client, app):
    resp = client.post("/webhook/notas", json=_payload(), headers=_headers())
    assert resp.status_code == 202

    _processar_validacao_pendente()

    resp_validacao = client.get("/lote/lote-http/validacao", headers=_headers())
    assert resp_validacao.status_code == 200
    body = resp_validacao.get_json()
    assert body["status"] == STATUS_VALIDATION_PENDING_APPROVAL
    assert body["apto_para_aprovacao"] is True
    assert body["snapshot_hash"]
    assert body["finalizado"] is True
    assert body["pode_aprovar"] is True
    assert body["mensagem"]


def test_post_aprovar_cria_job_assincrono(client, app):
    client.post("/webhook/notas", json=_payload(), headers=_headers())
    _processar_validacao_pendente()

    validacao = ValidacaoLoteStore(app.config["VALIDACAO_LOTE_DB"]).carregar("lote-http")
    assert validacao is not None

    resp = client.post(
        "/lote/lote-http/aprovar",
        json={"snapshot_hash": validacao.snapshot_hash, "aprovador": "Gestor"},
        headers=_headers(),
    )

    assert resp.status_code == 202
    body = resp.get_json()
    assert body["status"] == "accepted"
    assert body["mensagem"]
    assert body["polling"]["endpoint"] == "/lote/lote-http/resultado-envio"

    job = obter_job_por_id(body["job_id"])
    assert job is not None
    assert job.job_type == JobType.APPROVAL_AND_SEND

    validacao_atual = ValidacaoLoteStore(app.config["VALIDACAO_LOTE_DB"]).carregar("lote-http")
    assert validacao_atual is not None
    assert validacao_atual.status == STATUS_APPROVAL_JOB_QUEUED

    resultado_envio = ResultadoEnvioLoteStore(app.config["RESULTADO_ENVIO_LOTE_DB"]).carregar("lote-http")
    assert resultado_envio is not None
    assert resultado_envio.status == STATUS_APPROVAL_JOB_QUEUED
    assert resultado_envio.aprovador_origem == "api_manual"
    assert resultado_envio.aprovador_identity_strength == "weak"


def test_get_resultado_envio_queued_expoe_contrato_para_polling(client, app):
    client.post("/webhook/notas", json=_payload(), headers=_headers())
    _processar_validacao_pendente()

    validacao = ValidacaoLoteStore(app.config["VALIDACAO_LOTE_DB"]).carregar("lote-http")
    assert validacao is not None

    client.post(
        "/lote/lote-http/aprovar",
        json={"snapshot_hash": validacao.snapshot_hash, "aprovador": "Gestor"},
        headers=_headers(),
    )

    resp = client.get("/lote/lote-http/resultado-envio", headers=_headers())
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["status"] == STATUS_APPROVAL_JOB_QUEUED
    assert body["finalizado"] is False
    assert body["retry_pendente"] is False
    assert body["polling"]["endpoint"] == "/lote/lote-http/resultado-envio"
    assert body["mensagem"]


def test_post_aprovar_bloqueia_snapshot_stale(client, app):
    client.post("/webhook/notas", json=_payload(), headers=_headers())
    _processar_validacao_pendente()

    resp = client.post(
        "/lote/lote-http/aprovar",
        json={"snapshot_hash": "snapshot-antigo", "aprovador": "Gestor"},
        headers=_headers(),
    )

    assert resp.status_code == 409
    assert "stale" in resp.get_json()["erro"].lower()


def test_post_aprovar_sem_validacao_retorna_404(client):
    resp = client.post(
        "/lote/lote-inexistente/aprovar",
        json={"snapshot_hash": "snapshot-x", "aprovador": "Gestor"},
        headers=_headers(),
    )
    assert resp.status_code == 404
    assert "validacao" in resp.get_json()["erro"].lower()


def test_post_aprovar_bloqueia_dupla_aprovacao(client, app):
    client.post("/webhook/notas", json=_payload(), headers=_headers())
    _processar_validacao_pendente()

    validacao = ValidacaoLoteStore(app.config["VALIDACAO_LOTE_DB"]).carregar("lote-http")
    assert validacao is not None

    resp1 = client.post(
        "/lote/lote-http/aprovar",
        json={"snapshot_hash": validacao.snapshot_hash, "aprovador": "Gestor"},
        headers=_headers(),
    )
    assert resp1.status_code == 202

    resp2 = client.post(
        "/lote/lote-http/aprovar",
        json={"snapshot_hash": validacao.snapshot_hash, "aprovador": "Gestor 2"},
        headers=_headers(),
    )
    assert resp2.status_code == 409


def test_get_resultado_envio_retorna_resultado_final(client, app, monkeypatch):
    client.post("/webhook/notas", json=_payload(), headers=_headers())
    _processar_validacao_pendente()
    validacao_store = ValidacaoLoteStore(app.config["VALIDACAO_LOTE_DB"])
    validacao = validacao_store.carregar("lote-http")
    assert validacao is not None

    resp = client.post(
        "/lote/lote-http/aprovar",
        json={"snapshot_hash": validacao.snapshot_hash, "aprovador": "Gestor"},
        headers=_headers(),
    )
    approval_job_id = resp.get_json()["job_id"]

    result_store = ResultadoEnvioLoteStore(app.config["RESULTADO_ENVIO_LOTE_DB"])

    def fake_execute(**kwargs):
        persistido = kwargs["validation_store"].carregar("lote-http")
        assert persistido is not None
        persistido.status = STATUS_SENT
        kwargs["validation_store"].salvar(persistido)
        send_result = registrar_resultado_envio(
            lote_id="lote-http",
            job_id=kwargs["job_id"],
            snapshot_hash=persistido.snapshot_hash,
            status=STATUS_SENT,
            result_store=kwargs["result_store"],
            aprovado_por=kwargs["aprovado_por"],
            sucesso=True,
            mensagem="Envio concluido",
            envio={
                "lote_id": "lote-http",
                "sucesso": True,
                "mensagem": "Envio concluido",
                "total_sendaveis": 1,
                "total_enviados": 1,
                "total_dry_run": 0,
                "total_erros_resolucao": 0,
                "total_erros_envio": 0,
            },
            auditoria_resumo={"enviado": 1},
            finished_at="2026-03-31T12:00:00+00:00",
        )
        return {
            "status": STATUS_SENT,
            "envio": {
                "sucesso": True,
                "mensagem": "Envio concluido",
                "total_sendaveis": 1,
                "total_enviados": 1,
                "total_dry_run": 0,
                "total_erros_resolucao": 0,
                "total_erros_envio": 0,
            },
            "send_result": send_result,
        }

    monkeypatch.setattr(worker, "executar_aprovacao_e_envio", fake_execute)

    approval_job = claim_next_pending_job()
    assert approval_job is not None
    assert approval_job.id == approval_job_id
    worker.processar_job(approval_job)

    resp_resultado = client.get("/lote/lote-http/resultado-envio", headers=_headers())
    assert resp_resultado.status_code == 200
    body = resp_resultado.get_json()
    assert body["status"] == STATUS_SENT
    assert body["quantidade_enviada"] == 1
    assert body["quantidade_com_erro"] == 0
    assert body["finalizado"] is True
    assert body["mensagem"] == "Envio concluido"
    assert result_store.carregar("lote-http") is not None


def test_get_resultado_envio_sem_envio_retorna_404(client):
    client.post("/webhook/notas", json=_payload(), headers=_headers())
    _processar_validacao_pendente()

    resp = client.get("/lote/lote-http/resultado-envio", headers=_headers())
    assert resp.status_code == 404
    assert "resultado de envio" in resp.get_json()["erro"].lower()


def test_auth_invalida_rejeita_endpoint_externo(client):
    resp = client.post("/webhook/notas", json=_payload(), headers=_headers(secret="segredo-ruim"))
    assert resp.status_code == 401


def test_payload_invalido_retorna_400(client):
    resp = client.post(
        "/webhook/notas",
        json={"spreadsheet_id": "abc", "sheet_name": "Notas", "dados": []},
        headers=_headers(),
    )
    assert resp.status_code == 400


def test_post_aprovar_persiste_identidade_estruturada(client, app):
    client.post("/webhook/notas", json=_payload(), headers=_headers())
    _processar_validacao_pendente()

    validacao = ValidacaoLoteStore(app.config["VALIDACAO_LOTE_DB"]).carregar("lote-http")
    assert validacao is not None

    resp = client.post(
        "/lote/lote-http/aprovar",
        json={
            "snapshot_hash": validacao.snapshot_hash,
            "aprovador": "Coordenacao",
            "aprovador_nome_informado": "Coordenacao",
            "aprovador_email": "coord@example.com",
            "aprovador_origem": "google_apps_script_session",
        },
        headers=_headers(),
    )

    assert resp.status_code == 202
    resultado_envio = ResultadoEnvioLoteStore(app.config["RESULTADO_ENVIO_LOTE_DB"]).carregar("lote-http")
    assert resultado_envio is not None
    assert resultado_envio.aprovador_email == "coord@example.com"
    assert resultado_envio.aprovador_origem == "google_apps_script_session"
    assert resultado_envio.aprovador_identity_strength == "medium"


def test_post_rejeita_antireplay_repetido(client):
    headers = _headers(nonce="nonce-fixo")
    resp1 = client.post("/webhook/notas", json=_payload("lote-anti-1"), headers=headers)
    assert resp1.status_code == 202

    resp2 = client.post("/webhook/notas", json=_payload("lote-anti-2"), headers=headers)
    assert resp2.status_code == 401


def test_post_webhook_notas_rejeita_quantidade_excessiva_de_linhas(client):
    payload = _payload("lote-muito-grande")
    payload["dados"] = payload["dados"] * 3

    resp = client.post("/webhook/notas", json=payload, headers=_headers())
    assert resp.status_code == 400
    assert "linhas" in resp.get_json()["erro"].lower()


def test_post_webhook_notas_aplica_rate_limit(tmp_path):
    app = create_app(
        {
            "TESTING": True,
            "WEBHOOK_SECRET": "segredo-teste",
            "VALIDACAO_LOTE_DB": str(tmp_path / "validacoes.db"),
            "APROVACAO_LOTE_DB": str(tmp_path / "aprovacoes.db"),
            "LOTE_ITENS_DB": str(tmp_path / "itens.db"),
            "ENVIO_LOTE_AUDIT_DB": str(tmp_path / "audit.db"),
            "RESULTADO_ENVIO_LOTE_DB": str(tmp_path / "resultados_envio.db"),
            "MAPA_DISCIPLINAS": "mapa_disciplinas.json",
            "MAPA_AVALIACOES": "mapa_avaliacoes.json",
            "MAPA_PROFESSORES": "mapa_professores.json",
            "RATE_LIMIT_MAX_REQUESTS": 1,
            "RATE_LIMIT_WINDOW_SECONDS": 60,
        }
    )
    client = app.test_client()

    resp1 = client.post("/webhook/notas", json=_payload("lote-rate-1"), headers=_headers())
    assert resp1.status_code == 202

    resp2 = client.post("/webhook/notas", json=_payload("lote-rate-2"), headers=_headers())
    assert resp2.status_code == 429


def test_get_job_status_expoe_finalizado_para_polling(client):
    resp = client.post("/webhook/notas", json=_payload(), headers=_headers())
    body = resp.get_json()

    resp_job = client.get("/job/%s/status" % body["job_id"], headers=_headers())
    assert resp_job.status_code == 200
    job = resp_job.get_json()
    assert job["job_type"] == JobType.GOOGLE_SHEETS_VALIDATION
    assert job["finalizado"] is False
    assert job["mensagem"]


def test_get_status_publico_retorna_json_basico(client):
    resp = client.get("/status")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["service"] == "madan-etl"
    assert isinstance(body["ok"], bool)
    assert isinstance(body["timestamp"], str)
    assert isinstance(body["uptime_segundos"], int)
    assert isinstance(body["jobs_pending"], int)
    assert isinstance(body["jobs_processing"], int)
    assert isinstance(body["jobs_failed_24h"], int)
    assert body["ultimo_lote_validado"] is None
    assert body["ultimo_envio"] is None
    assert body["ultimo_erro"] is None
    assert "git_commit" in body["deploy"]
    assert "validacao_pre_envio_mtime" in body["deploy"]


def test_get_status_expoe_ultimo_lote_envio_e_erro_truncado(client, app):
    lote_id = "lote-status"
    resp = client.post("/webhook/notas", json=_payload(lote_id), headers=_headers())
    assert resp.status_code == 202
    _processar_validacao_pendente()

    validacao = ValidacaoLoteStore(app.config["VALIDACAO_LOTE_DB"]).carregar(lote_id)
    assert validacao is not None
    aprovacao_resp = client.post(
        f"/lote/{lote_id}/aprovar",
        json={"snapshot_hash": validacao.snapshot_hash, "aprovador": "Gestor"},
        headers=_headers(),
    )
    assert aprovacao_resp.status_code == 202

    job_erro = criar_job(
        source_type="google_sheets",
        source_identifier=f"erro-status-{uuid.uuid4()}",
        content_hash=f"hash-erro-{uuid.uuid4()}",
    )
    assert job_erro.id is not None
    registrar_erro(int(job_erro.id), "x" * 280)

    status_resp = client.get("/status")
    assert status_resp.status_code == 200
    body = status_resp.get_json()

    assert body["ultimo_lote_validado"] is not None
    assert body["ultimo_lote_validado"]["lote_id"] == lote_id
    assert body["ultimo_envio"] is not None
    assert body["ultimo_envio"]["lote_id"] == lote_id
    assert body["jobs_failed_24h"] >= 1
    assert body["ultimo_erro"] is not None
    assert len(body["ultimo_erro"]["mensagem"]) <= 200


def test_get_status_html_renderiza_tabela(client):
    resp = client.get("/status.html")
    assert resp.status_code == 200
    assert resp.content_type.startswith("text/html")
    html = resp.get_data(as_text=True)
    assert "Status do servico madan-etl" in html
    assert "<table class='status-table'>" in html
    assert 'body class="ok"' in html


# ---------------------------------------------------------------------------
# Plano B — sheet_name como nome de aba trimestral (ex: "2A_T1")
# ---------------------------------------------------------------------------

def _payload_plano_b(turma: str = "2A", trimestre: str = "T1") -> dict:
    """Payload simulando aba ativa Plano B enviada pelo Apps Script."""
    nome_aba = f"{turma}_{trimestre}"
    return {
        "spreadsheet_id": "spreadsheet-planob",
        "sheet_name": nome_aba,
        "lote_id": f"spreadsheet-planob/{nome_aba}",
        "dados": [
            {
                "Estudante": "Carlos Madan",
                "RA": "RA999",
                "Turma": turma,
                "Trimestre": trimestre,
                "Matemática - Frente A - AV 1 Obj": "7",
                "Matemática - Frente A - AV 1 Disc": "6",
            }
        ],
    }


def test_plano_b_sheet_name_2a_t1_aceito(client):
    """sheet_name no padrão Plano B deve ser aceito com 202."""
    resp = client.post("/webhook/notas", json=_payload_plano_b("2A", "T1"), headers=_headers())
    assert resp.status_code == 202
    body = resp.get_json()
    assert body["status"] == "accepted"
    assert body["lote_id"] == "spreadsheet-planob/2A_T1"


def test_plano_b_sheet_name_1b_t2_aceito(client):
    resp = client.post("/webhook/notas", json=_payload_plano_b("1B", "T2"), headers=_headers())
    assert resp.status_code == 202
    body = resp.get_json()
    assert body["lote_id"] == "spreadsheet-planob/1B_T2"


def test_plano_b_sheet_name_2b_t3_aceito(client):
    resp = client.post("/webhook/notas", json=_payload_plano_b("2B", "T3"), headers=_headers())
    assert resp.status_code == 202
    body = resp.get_json()
    assert body["lote_id"] == "spreadsheet-planob/2B_T3"


def test_plano_b_lote_id_contem_nome_aba(client):
    """lote_id deve incluir o nome da aba para isolar lotes por turma/trimestre."""
    resp = client.post("/webhook/notas", json=_payload_plano_b("2A", "T1"), headers=_headers())
    body = resp.get_json()
    assert "2A_T1" in body["lote_id"]
    assert "2A_T1" in body["polling"]["endpoint"]


def test_plano_b_validacao_polling_retorna_lote_correto(client, app):
    """GET /lote/{id}/validacao deve encontrar o lote criado com nome de aba Plano B."""
    lote_id = "spreadsheet-planob/2A_T1"
    client.post("/webhook/notas", json=_payload_plano_b("2A", "T1"), headers=_headers())

    resp = client.get(f"/lote/{lote_id}/validacao", headers=_headers())
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["lote_id"] == lote_id
    assert body["status"] == STATUS_VALIDATION_JOB_QUEUED


def test_plano_b_abas_diferentes_geram_lotes_independentes(client, app):
    """Duas abas distintas (2A_T1 e 1B_T1) devem criar lotes completamente separados."""
    client.post("/webhook/notas", json=_payload_plano_b("2A", "T1"), headers=_headers())
    client.post("/webhook/notas", json=_payload_plano_b("1B", "T1"), headers=_headers())

    store = ValidacaoLoteStore(app.config["VALIDACAO_LOTE_DB"])
    v2a = store.carregar("spreadsheet-planob/2A_T1")
    v1b = store.carregar("spreadsheet-planob/1B_T1")

    assert v2a is not None
    assert v1b is not None
    assert v2a.lote_id != v1b.lote_id


def test_plano_b_sheet_name_ausente_retorna_400(client):
    payload = _payload_plano_b()
    del payload["sheet_name"]
    resp = client.post("/webhook/notas", json=payload, headers=_headers())
    assert resp.status_code == 400
    assert "sheet_name" in resp.get_json().get("erro", "").lower()


def test_plano_b_sheet_name_vazio_retorna_400(client):
    payload = _payload_plano_b()
    payload["sheet_name"] = "   "
    resp = client.post("/webhook/notas", json=payload, headers=_headers())
    assert resp.status_code == 400

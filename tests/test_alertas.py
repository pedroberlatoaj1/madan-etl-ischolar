from unittest.mock import MagicMock

import pytest

import alertas
from alertas import enviar_alerta, alertar_falha_definitiva


class DummyResponse:
    def __init__(self, status_code: int, text: str = "") -> None:
        self.status_code = status_code
        self.text = text


def test_enviar_alerta_nao_dispara_quando_desabilitado(monkeypatch):
    class DummyConfig:
        ALERTS_ENABLED = False
        ALERT_WEBHOOK_URL = ""
        APP_ENV = "test"

    monkeypatch.setattr(alertas, "config", DummyConfig(), raising=False)
    called = {"flag": False}

    def fake_post(*args, **kwargs):
        called["flag"] = True
        return DummyResponse(204)

    monkeypatch.setattr(alertas.requests, "post", fake_post)

    enviar_alerta("Titulo", "Mensagem")
    assert called["flag"] is False


def test_enviar_alerta_nao_dispara_quando_url_vazia(monkeypatch):
    class DummyConfig:
        ALERTS_ENABLED = True
        ALERT_WEBHOOK_URL = ""
        APP_ENV = "test"

    monkeypatch.setattr(alertas, "config", DummyConfig(), raising=False)
    called = {"flag": False}

    def fake_post(*args, **kwargs):
        called["flag"] = True
        return DummyResponse(204)

    monkeypatch.setattr(alertas.requests, "post", fake_post)

    enviar_alerta("Titulo", "Mensagem")
    assert called["flag"] is False


def test_alertar_falha_definitiva_monta_payload_e_chama_requests(monkeypatch):
    class DummyConfig:
        ALERTS_ENABLED = True
        ALERT_WEBHOOK_URL = "http://example.com/webhook"
        APP_ENV = "test"

    monkeypatch.setattr(alertas, "config", DummyConfig(), raising=False)

    captured = {}

    def fake_post(url, json=None, timeout=0):
        captured["url"] = url
        captured["json"] = json
        captured["timeout"] = timeout
        return DummyResponse(204)

    monkeypatch.setattr(alertas.requests, "post", fake_post)

    alertar_falha_definitiva(
        job_id=1,
        status="error",
        error_type="permanent",
        attempt_count=2,
        max_attempts=4,
        source_type="local_file",
        source_identifier="/tmp/a.csv",
        mensagem_erro="Erro X",
    )

    assert captured["url"] == "http://example.com/webhook"
    assert "FALHA DEFINITIVA" in captured["json"]["content"]
    assert "job_id=1" in captured["json"]["content"]
    assert captured["timeout"] == 5


def test_enviar_alerta_trata_excecao_do_requests(monkeypatch):
    class DummyConfig:
        ALERTS_ENABLED = True
        ALERT_WEBHOOK_URL = "http://example.com/webhook"
        APP_ENV = "test"

    monkeypatch.setattr(alertas, "config", DummyConfig(), raising=False)

    def fake_post(*args, **kwargs):
        raise RuntimeError("falha de rede")

    monkeypatch.setattr(alertas.requests, "post", fake_post)

    # Se a exceção não for tratada, o teste quebra.
    enviar_alerta("Titulo", "Mensagem")


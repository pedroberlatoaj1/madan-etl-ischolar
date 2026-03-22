from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import requests

from config import config
from logger import configurar_logger


log = configurar_logger("etl.alertas")


def _alerts_config_valid() -> bool:
    """Verifica se alertas estão habilitados e configurados."""
    enabled = str(getattr(config, "ALERTS_ENABLED", "false")).lower() in ("1", "true", "yes")
    url = getattr(config, "ALERT_WEBHOOK_URL", "") or ""
    if not enabled:
        log.debug("Alertas desabilitados (ALERTS_ENABLED=false).")
        return False
    if not url.strip():
        log.warning("Alertas habilitados mas ALERT_WEBHOOK_URL não está configurado.")
        return False
    return True


def _montar_payload_discord(conteudo: str) -> Dict[str, Any]:
    """
    Monta payload simples compatível com Discord webhook.

    Mantém formato genérico o suficiente para outros webhooks que aceitam
    um campo 'content' com texto curto.
    """
    return {"content": conteudo}


def enviar_alerta(titulo: str, mensagem: str, extra: Optional[dict] = None) -> None:
    """
    Envia um alerta por webhook HTTP (Discord-style).

    - Não lança exceção para o chamador.
    - Usa timeout curto (5s).
    - Loga sucesso/falha de forma simples.
    """
    if not _alerts_config_valid():
        return

    url = config.ALERT_WEBHOOK_URL
    env = getattr(config, "APP_ENV", None) or getattr(config, "ENV", None) or "unknown"
    timestamp = datetime.now(timezone.utc).replace(microsecond=0).isoformat()

    linhas = [titulo, mensagem, f"timestamp={timestamp}", f"env={env}"]
    if extra:
        for k, v in extra.items():
            linhas.append(f"{k}={v}")

    conteudo = "\n".join(linhas)
    payload = _montar_payload_discord(conteudo)

    try:
        resp = requests.post(url, json=payload, timeout=5)
        if 200 <= resp.status_code < 300:
            log.info("🔔 Alerta enviado com sucesso | status=%s", resp.status_code)
        else:
            log.warning(
                "⚠️ Falha ao enviar alerta | status=%s | body=%s",
                resp.status_code,
                (resp.text or "")[:300],
            )
    except Exception as exc:  # noqa: BLE001
        log.warning("⚠️ Erro ao enviar alerta (ignorado): %s", exc)


def alertar_falha_definitiva(
    *,
    job_id: int,
    status: str,
    error_type: str,
    attempt_count: int,
    max_attempts: int,
    source_type: str,
    source_identifier: str,
    mensagem_erro: str,
) -> None:
    """Helper específico para falhas definitivas de job."""
    titulo = "🚨 FALHA DEFINITIVA NO JOB"
    msg_linhas = [
        f"job_id={job_id}",
        f"status={status}",
        f"error_type={error_type}",
        f"attempts={attempt_count}/{max_attempts}",
        f"origem={source_identifier}",
        f"source_type={source_type}",
        f"erro={mensagem_erro}",
    ]
    enviar_alerta(titulo, "\n".join(msg_linhas))


__all__ = ["enviar_alerta", "alertar_falha_definitiva"]


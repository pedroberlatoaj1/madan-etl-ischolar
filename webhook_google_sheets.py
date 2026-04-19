"""
webhook_google_sheets.py - Backend HTTP do fluxo assincrono Google Sheets -> worker oficial.

Semantica suportada:
- POST /webhook/notas
- GET  /lote/<lote_id>/validacao
- POST /lote/<lote_id>/aprovar
- GET  /lote/<lote_id>/resultado-envio
- GET  /job/<job_id>/status
"""

from __future__ import annotations

import hmac
import os
import re
import sys
import time
from collections import deque
from functools import wraps
from typing import Any, Callable, Optional

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

import pandas as pd
from flask import Flask, current_app, jsonify, request

from config import config
from constants import JobStatus
from job_store import (
    JobStoreError,
    criar_job_aprovacao_envio,
    criar_job_validacao_google_sheets,
    obter_job_por_id,
    registrar_erro,
)
from logger import configurar_logger
from pipeline_runner import (
    LoteJaAprovadoError,
    LoteNaoElegivelError,
    MapaInvalidoError,
    SnapshotStaleError,
    STATUS_APPROVAL_JOB_QUEUED,
    STATUS_DRY_RUN_COMPLETED,
    STATUS_SEND_FAILED,
    STATUS_SEND_PROCESSING,
    STATUS_SEND_RETRY_SCHEDULED,
    STATUS_SENT,
    STATUS_VALIDATION_FAILED,
    STATUS_VALIDATION_JOB_QUEUED,
    STATUS_VALIDATION_PENDING_APPROVAL,
    consultar_resultado_envio_atual,
    aprovar_lote_para_execucao_externa,
    preparar_pacote_execucao,
    registrar_resultado_execucao_externa,
    registrar_solicitacao_aprovacao_envio,
    registrar_validacao_em_fila,
    validar_solicitacao_aprovacao,
)
from envio_lote_audit_store import EnvioLoteAuditStore
from lote_itens_store import LoteItensStore
from resultado_envio_lote_store import ResultadoEnvioLoteStore
from snapshot_store import save_snapshot
from utils.hash_utils import sha256_bytes, sha256_dataframe_normalizado
from validacao_lote_store import ValidacaoLoteStore
from aprovacao_lote_store import AprovacaoLoteStore

log = configurar_logger("etl.webhook")

WEBHOOK_SECRET_INSECURE_VALUES = frozenset(
    {
        "",
        "troque_por_um_segredo_forte_em_producao",
        "SUA_CHAVE_AQUI",
        "secret",
        "changeme",
    }
)

SOURCE_TYPE_GOOGLE_SHEETS = "google_sheets"
POLLING_RECOMENDADO_MS = 5000
MAX_ID_FIELD_LENGTH = 255


def _segredo_valido(segredo_recebido: str, segredo_configurado: str) -> bool:
    return hmac.compare_digest(segredo_recebido or "", segredo_configurado or "")


def _dados_para_dataframe(dados: list[dict[str, Any]]) -> pd.DataFrame:
    if not dados:
        return pd.DataFrame()
    return pd.DataFrame(dados)


def _normalizar_nome_coluna(nome: str) -> str:
    s = str(nome).strip().lower()
    s = re.sub(r"\s+", "_", s)
    s = re.sub(r"[áàãâ]", "a", s)
    s = re.sub(r"[éèê]", "e", s)
    s = re.sub(r"[íì]", "i", s)
    s = re.sub(r"[óòõô]", "o", s)
    s = re.sub(r"[úù]", "u", s)
    s = re.sub(r"[ç]", "c", s)
    s = re.sub(r"[^a-z0-9_]", "_", s)
    return s or "_"


def _normalizar_colunas_para_hash(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    df = df.copy()
    df.columns = [_normalizar_nome_coluna(c) for c in df.columns]
    return df


def _calcular_hash_conteudo(df: pd.DataFrame) -> str:
    if df.empty:
        return sha256_bytes(b"__EMPTY_GOOGLE_SHEETS__")
    df_norm = _normalizar_colunas_para_hash(df)
    return sha256_dataframe_normalizado(df_norm, sort_by_columns=["estudante", "disciplina"])


def _payload_json() -> dict[str, Any]:
    if not request.is_json:
        raise ValueError("Content-Type deve ser application/json.")
    payload = request.get_json(silent=True)
    if payload is None or not isinstance(payload, dict):
        raise ValueError("Body invalido ou nao-JSON.")
    return payload


def _stores() -> tuple[ValidacaoLoteStore, AprovacaoLoteStore, ResultadoEnvioLoteStore]:
    return (
        ValidacaoLoteStore(current_app.config["VALIDACAO_LOTE_DB"]),
        AprovacaoLoteStore(current_app.config["APROVACAO_LOTE_DB"]),
        ResultadoEnvioLoteStore(current_app.config["RESULTADO_ENVIO_LOTE_DB"]),
    )


def _job_payload_defaults() -> dict[str, Any]:
    return {
        "db_validacoes": current_app.config["VALIDACAO_LOTE_DB"],
        "db_aprovacoes": current_app.config["APROVACAO_LOTE_DB"],
        "db_itens": current_app.config["LOTE_ITENS_DB"],
        "db_audit": current_app.config["ENVIO_LOTE_AUDIT_DB"],
        "db_resultados_envio": current_app.config["RESULTADO_ENVIO_LOTE_DB"],
        "mapa_disciplinas": current_app.config["MAPA_DISCIPLINAS"],
        "mapa_avaliacoes": current_app.config["MAPA_AVALIACOES"],
        "mapa_professores": current_app.config["MAPA_PROFESSORES"],
        "mapa_turmas": current_app.config["MAPA_TURMAS"],
    }


def _request_id() -> str:
    cached = request.environ.get("etl_request_id")
    if cached:
        return str(cached)
    request_id = request.headers.get("X-Request-Id", "").strip()
    if request_id:
        final = request_id[:64]
        request.environ["etl_request_id"] = final
        return final
    nonce = request.headers.get("X-Webhook-Nonce", "").strip()
    if nonce:
        final = nonce[:64]
        request.environ["etl_request_id"] = final
        return final
    base = f"{request.method}:{request.path}:{time.time_ns()}"
    final = sha256_bytes(base.encode("utf-8"))[:16]
    request.environ["etl_request_id"] = final
    return final


def _request_ip() -> str:
    forwarded = request.headers.get("X-Forwarded-For", "").strip()
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.remote_addr or "unknown"


def _limpar_rate_limit() -> None:
    cache: dict[str, deque[float]] = current_app.config["_RATE_LIMIT_CACHE"]
    now = time.time()
    janela = float(current_app.config["RATE_LIMIT_WINDOW_SECONDS"])
    expirados = []
    for chave, eventos in cache.items():
        while eventos and (now - eventos[0]) > janela:
            eventos.popleft()
        if not eventos:
            expirados.append(chave)
    for chave in expirados:
        cache.pop(chave, None)


def _validar_rate_limit() -> None:
    _limpar_rate_limit()
    cache: dict[str, deque[float]] = current_app.config["_RATE_LIMIT_CACHE"]
    now = time.time()
    chave = f"{_request_ip()}:{request.endpoint or request.path}"
    janela = float(current_app.config["RATE_LIMIT_WINDOW_SECONDS"])
    limite = int(current_app.config["RATE_LIMIT_MAX_REQUESTS"])
    eventos = cache.setdefault(chave, deque())
    while eventos and (now - eventos[0]) > janela:
        eventos.popleft()
    if len(eventos) >= limite:
        raise PermissionError("Limite operacional de requisicoes excedido.")
    eventos.append(now)


def _cleanup_nonce_cache() -> None:
    cache: dict[str, int] = current_app.config["_NONCE_CACHE"]
    now = int(time.time())
    expirados = [nonce for nonce, expires_at in cache.items() if expires_at <= now]
    for nonce in expirados:
        cache.pop(nonce, None)


def _validar_antireplay() -> None:
    timestamp_raw = request.headers.get("X-Webhook-Timestamp", "").strip()
    nonce = request.headers.get("X-Webhook-Nonce", "").strip()
    requer_antireplay = request.method.upper() in {"POST", "PUT", "PATCH", "DELETE"}
    if not timestamp_raw and not nonce and not requer_antireplay:
        return
    if not timestamp_raw or not nonce:
        raise PermissionError("Headers de anti-replay incompletos.")

    try:
        timestamp = int(timestamp_raw)
    except ValueError as exc:
        raise PermissionError("Timestamp de autenticacao invalido.") from exc

    tolerancia = int(current_app.config["AUTH_TIMESTAMP_TOLERANCE_SECONDS"])
    agora = int(time.time())
    if abs(agora - timestamp) > tolerancia:
        raise PermissionError("Timestamp de autenticacao fora da janela permitida.")

    _cleanup_nonce_cache()
    cache: dict[str, int] = current_app.config["_NONCE_CACHE"]
    if nonce in cache:
        raise PermissionError("Nonce ja utilizado.")
    cache[nonce] = agora + tolerancia


def _normalizar_aprovador_payload(payload: dict[str, Any]) -> dict[str, Optional[str]]:
    nome = str(payload.get("aprovador_nome_informado") or "").strip() or None
    email = str(payload.get("aprovador_email") or "").strip().lower() or None
    if email and not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
        raise ValueError("Campo 'aprovador_email' invalido.")
    origem = str(payload.get("aprovador_origem") or "").strip() or None
    aprovado_por = str(payload.get("aprovador") or payload.get("aprovado_por") or "").strip()
    if not aprovado_por:
        aprovado_por = email or nome or ""
    return {
        "aprovado_por": aprovado_por or None,
        "aprovador_nome_informado": nome,
        "aprovador_email": email,
        "aprovador_origem": origem,
    }


def requer_autenticacao(f: Callable[..., Any]) -> Callable[..., Any]:
    @wraps(f)
    def decorado(*args: Any, **kwargs: Any):
        request_id = _request_id()
        segredo = request.headers.get("X-Webhook-Secret", "")
        if not _segredo_valido(segredo, current_app.config["WEBHOOK_SECRET"]):
            log.warning(
                "Acesso nao autorizado | request_id=%s | path=%s | ip=%s",
                request_id,
                request.path,
                _request_ip(),
            )
            return _json_erro("Nao autorizado", 401, codigo="nao_autorizado", request_id=request_id)
        try:
            _validar_rate_limit()
            _validar_antireplay()
        except PermissionError as exc:
            codigo = "rate_limit" if "limite operacional" in str(exc).lower() else "nao_autorizado"
            status = 429 if codigo == "rate_limit" else 401
            log.warning(
                "Requisicao rejeitada | request_id=%s | path=%s | ip=%s | motivo=%s",
                request_id,
                request.path,
                _request_ip(),
                exc,
            )
            return _json_erro(
                "Limite operacional excedido. Tente novamente em instantes."
                if codigo == "rate_limit"
                else "Nao autorizado",
                status,
                codigo=codigo,
                request_id=request_id,
            )
        return f(*args, **kwargs)

    return decorado


def _json_erro(
    mensagem: str,
    status_code: int,
    *,
    codigo: Optional[str] = None,
    request_id: Optional[str] = None,
) -> tuple[Any, int]:
    payload: dict[str, Any] = {"erro": mensagem}
    if codigo:
        payload["codigo"] = codigo
    if request_id:
        payload["request_id"] = request_id
    return jsonify(payload), status_code


def _job_finalizado(status: str) -> bool:
    return status in {JobStatus.SUCCESS, JobStatus.ERROR, JobStatus.SKIPPED}


def _validacao_finalizada(status: str) -> bool:
    return status != STATUS_VALIDATION_JOB_QUEUED


def _resultado_envio_finalizado(status: str) -> bool:
    return status in {STATUS_SENT, STATUS_DRY_RUN_COMPLETED, STATUS_SEND_FAILED}


def _mensagem_validacao(status: str, *, apto_para_aprovacao: bool, resumo: dict[str, Any]) -> str:
    if status == STATUS_VALIDATION_JOB_QUEUED:
        return "Validacao em fila. Aguarde alguns segundos e consulte novamente."
    if status == STATUS_VALIDATION_PENDING_APPROVAL:
        return (
            "Validacao concluida. O lote esta apto para aprovacao."
            if apto_para_aprovacao
            else "Validacao concluida, mas o lote ainda nao esta apto para aprovacao."
        )
    if status == STATUS_VALIDATION_FAILED:
        total_erros = int(resumo.get("total_erros", 0) or 0)
        return f"Validacao concluida com bloqueios. Total de erros: {total_erros}."
    if status == STATUS_APPROVAL_JOB_QUEUED:
        return "Aprovacao recebida. O envio foi enfileirado e esta aguardando o worker."
    if status == STATUS_SEND_PROCESSING:
        return "Validacao concluida e o envio esta em processamento."
    if status == STATUS_SEND_RETRY_SCHEDULED:
        return "Validacao concluida. O envio teve falha transitoria e sera tentado novamente."
    if status in {STATUS_SENT, STATUS_DRY_RUN_COMPLETED, STATUS_SEND_FAILED}:
        return "Validacao concluida e lote ja passou pela fase de envio."
    return f"Status atual da validacao: {status}."


def _mensagem_resultado_envio(resultado: dict[str, Any]) -> str:
    status = str(resultado.get("status") or "")
    if status == STATUS_APPROVAL_JOB_QUEUED:
        return "Solicitacao recebida. O envio esta em fila."
    if status == STATUS_SEND_PROCESSING:
        return "Envio em processamento pelo worker."
    if status == STATUS_SEND_RETRY_SCHEDULED:
        return "O envio teve uma falha transitoria e sera tentado novamente automaticamente."
    if status == STATUS_DRY_RUN_COMPLETED:
        return str(resultado.get("mensagem") or "Simulacao concluida.")
    if status == STATUS_SENT:
        return str(resultado.get("mensagem") or "Envio concluido com sucesso.")
    if status == STATUS_SEND_FAILED:
        return str(resultado.get("mensagem") or "Envio finalizado com erro.")
    return f"Status atual do envio: {status}."


def _serializar_job(job: Any) -> dict[str, Any]:
    mensagem = (
        "Retry agendado automaticamente."
        if str(job.status) == JobStatus.PENDING and str(job.error_type or "") == "transient" and job.next_retry_at
        else (
            job.last_error
            or job.result_summary
            or ("Job concluido." if _job_finalizado(str(job.status)) else "Job em processamento.")
        )
    )
    return {
        "job_id": job.id,
        "job_type": job.job_type,
        "status": job.status,
        "source_type": job.source_type,
        "source_identifier": job.source_identifier,
        "created_at": job.created_at,
        "updated_at": job.updated_at,
        "attempt_count": job.attempt_count,
        "max_attempts": job.max_attempts,
        "error_type": job.error_type,
        "last_error": job.last_error,
        "next_retry_at": job.next_retry_at,
        "result_summary": job.result_summary,
        "processed_records": job.processed_records,
        "total_records": job.total_records,
        "finalizado": _job_finalizado(str(job.status)),
        "mensagem": mensagem,
    }


def _validar_payload_notas(payload: dict[str, Any]) -> tuple[str, str, str, list[dict[str, Any]]]:
    spreadsheet_id = str(payload.get("spreadsheet_id") or "").strip()
    if not spreadsheet_id:
        raise ValueError("Campo 'spreadsheet_id' e obrigatorio.")
    if len(spreadsheet_id) > MAX_ID_FIELD_LENGTH:
        raise ValueError("Campo 'spreadsheet_id' excede o tamanho permitido.")

    sheet_name = str(payload.get("sheet_name") or "").strip()
    if not sheet_name:
        raise ValueError("Campo 'sheet_name' e obrigatorio.")
    if len(sheet_name) > MAX_ID_FIELD_LENGTH:
        raise ValueError("Campo 'sheet_name' excede o tamanho permitido.")

    lote_id = str(payload.get("lote_id") or f"{spreadsheet_id}/{sheet_name}").strip()
    if not lote_id:
        raise ValueError("Campo 'lote_id' invalido.")
    if len(lote_id) > MAX_ID_FIELD_LENGTH:
        raise ValueError("Campo 'lote_id' excede o tamanho permitido.")

    dados = payload.get("dados")
    if not isinstance(dados, list) or not dados:
        raise ValueError("Campo 'dados' deve ser uma lista nao vazia.")
    if len(dados) > int(current_app.config["MAX_ROWS_PER_REQUEST"]):
        raise ValueError("Quantidade de linhas excede o limite operacional permitido.")
    for idx, row in enumerate(dados):
        if not isinstance(row, dict):
            raise ValueError(f"Campo 'dados[{idx}]' deve ser um objeto JSON.")
        if not row:
            raise ValueError(f"Campo 'dados[{idx}]' nao pode ser vazio.")

    return spreadsheet_id, sheet_name, lote_id, dados


def create_app(config_overrides: dict[str, Any] | None = None) -> Flask:
    app = Flask(__name__)
    app.config.update(
        WEBHOOK_SECRET=os.getenv("WEBHOOK_SECRET", "").strip(),
        MAX_CONTENT_LENGTH=int(os.getenv("WEBHOOK_MAX_CONTENT_LENGTH", str(1024 * 1024))),
        AUTH_TIMESTAMP_TOLERANCE_SECONDS=int(os.getenv("WEBHOOK_AUTH_WINDOW_SECONDS", "300")),
        MAX_ROWS_PER_REQUEST=int(os.getenv("WEBHOOK_MAX_ROWS", "2000")),
        RATE_LIMIT_WINDOW_SECONDS=int(os.getenv("WEBHOOK_RATE_LIMIT_WINDOW_SECONDS", "60")),
        RATE_LIMIT_MAX_REQUESTS=int(os.getenv("WEBHOOK_RATE_LIMIT_MAX_REQUESTS", "120")),
        VALIDACAO_LOTE_DB=os.getenv("VALIDACAO_LOTE_DB", "validacoes_lote.db"),
        APROVACAO_LOTE_DB=os.getenv("APROVACAO_LOTE_DB", "aprovacoes_lote.db"),
        LOTE_ITENS_DB=os.getenv("LOTE_ITENS_DB", "lote_itens.db"),
        ENVIO_LOTE_AUDIT_DB=os.getenv("ENVIO_LOTE_AUDIT_DB", "envio_lote_audit.db"),
        RESULTADO_ENVIO_LOTE_DB=os.getenv("RESULTADO_ENVIO_LOTE_DB", "resultados_envio_lote.db"),
        MAPA_DISCIPLINAS=os.getenv("MAPA_DISCIPLINAS", "mapa_disciplinas.json"),
        MAPA_AVALIACOES=os.getenv("MAPA_AVALIACOES", "mapa_avaliacoes.json"),
        MAPA_PROFESSORES=os.getenv("MAPA_PROFESSORES", "mapa_professores.json"),
        MAPA_TURMAS=os.getenv("MAPA_TURMAS", "mapa_turmas.json"),
        _NONCE_CACHE={},
        _RATE_LIMIT_CACHE={},
    )
    if config_overrides:
        app.config.update(config_overrides)

    @app.errorhandler(413)
    def payload_grande(_: Any):
        return _json_erro("Payload excede o tamanho maximo permitido.", 413)

    @app.get("/health")
    def health_check():
        return (
            jsonify(
                {
                    "status": "online",
                    "servico": "etl-ischolar-webhook",
                    "source_type_suportado": SOURCE_TYPE_GOOGLE_SHEETS,
                }
            ),
            200,
        )

    @app.post("/webhook/notas")
    @requer_autenticacao
    def receber_notas_sheets():
        request_id = _request_id()
        try:
            payload = _payload_json()
            spreadsheet_id, sheet_name, lote_id, dados = _validar_payload_notas(payload)
        except ValueError as exc:
            return _json_erro(str(exc), 400, codigo="payload_invalido", request_id=request_id)

        source_identifier = f"{spreadsheet_id}/{sheet_name}"
        validation_store, _, _ = _stores()

        try:
            df = _dados_para_dataframe(dados)
            content_hash = _calcular_hash_conteudo(df)
            total_records = int(len(df))

            job = criar_job_validacao_google_sheets(
                source_identifier=source_identifier,
                content_hash=content_hash,
                lote_id=lote_id,
                total_records=total_records,
                payload=_job_payload_defaults(),
            )

            if job.status != JobStatus.SKIPPED:
                save_snapshot(
                    job_id=job.id,
                    records=dados,
                    source_type=SOURCE_TYPE_GOOGLE_SHEETS,
                    source_identifier=source_identifier,
                    spreadsheet_id=spreadsheet_id,
                    sheet_name=sheet_name,
                    content_hash=content_hash,
                )
                registrar_validacao_em_fila(
                    lote_id=lote_id,
                    job_id=int(job.id),
                    snapshot_hash=content_hash,
                    validation_store=validation_store,
                )

            validacao_atual = validation_store.carregar(lote_id)
            log.info(
                "Job de validacao recebido | request_id=%s | job_id=%s | lote_id=%s | snapshot_hash=%s | registros=%s | status_job=%s",
                request_id,
                job.id,
                lote_id,
                content_hash,
                total_records,
                job.status,
            )
            return (
                jsonify(
                    {
                        "status": "accepted" if job.status != JobStatus.SKIPPED else "skipped",
                        "job_id": job.id,
                        "lote_id": lote_id,
                        "snapshot_hash": content_hash,
                        "source_identifier": source_identifier,
                        "total_records": total_records,
                        "mensagem": (
                            "Lote recebido para validacao."
                            if job.status != JobStatus.SKIPPED
                            else "Este snapshot ja foi processado anteriormente."
                        ),
                        "polling": {
                            "endpoint": f"/lote/{lote_id}/validacao",
                            "recomendado_ms": POLLING_RECOMENDADO_MS,
                        },
                        "request_id": request_id,
                        "validacao": (
                            {
                                "lote_id": validacao_atual.lote_id,
                                "job_id": validacao_atual.job_id,
                                "snapshot_hash": validacao_atual.snapshot_hash,
                                "status": validacao_atual.status,
                                "finalizado": _validacao_finalizada(validacao_atual.status),
                                "created_at": validacao_atual.created_at,
                                "updated_at": validacao_atual.updated_at,
                            }
                            if validacao_atual is not None
                            else None
                        ),
                    }
                ),
                202,
            )
        except JobStoreError:
            log.exception("Falha ao criar job de validacao | request_id=%s | lote_id=%s", request_id, lote_id)
            return _json_erro("Falha ao registrar job.", 500, codigo="job_store_error", request_id=request_id)
        except Exception as exc:
            log.exception("Erro interno ao criar job de validacao | request_id=%s | lote_id=%s", request_id, lote_id)
            if "job" in locals() and getattr(job, "id", None) is not None:
                try:
                    registrar_erro(int(job.id), f"Falha ao preparar validacao: {exc!s}")
                except Exception:
                    pass
            return _json_erro("Erro interno ao processar solicitacao.", 500, codigo="erro_interno", request_id=request_id)

    @app.get("/lote/<path:lote_id>/validacao")
    @requer_autenticacao
    def obter_validacao(lote_id: str):
        validation_store, _, _ = _stores()
        resultado = validation_store.carregar(lote_id)
        if resultado is None:
            return _json_erro("Resultado de validacao nao encontrado.", 404)
        return (
            jsonify(
                {
                    "lote_id": resultado.lote_id,
                    "job_id": resultado.job_id,
                    "snapshot_hash": resultado.snapshot_hash,
                    "status": resultado.status,
                    "finalizado": _validacao_finalizada(resultado.status),
                    "mensagem": _mensagem_validacao(
                        resultado.status,
                        apto_para_aprovacao=resultado.apto_para_aprovacao,
                        resumo=resultado.resumo,
                    ),
                    "resumo": resultado.resumo,
                    "avisos": resultado.avisos,
                    "erros": resultado.erros,
                    "pendencias": resultado.pendencias,
                    "apto_para_aprovacao": resultado.apto_para_aprovacao,
                    "pode_aprovar": (
                        resultado.status == STATUS_VALIDATION_PENDING_APPROVAL
                        and resultado.apto_para_aprovacao
                    ),
                    "polling": {
                        "endpoint": f"/lote/{resultado.lote_id}/validacao",
                        "recomendado_ms": POLLING_RECOMENDADO_MS,
                    },
                    "created_at": resultado.created_at,
                    "updated_at": resultado.updated_at,
                }
            ),
            200,
        )

    @app.post("/lote/<path:lote_id>/aprovar")
    @requer_autenticacao
    def aprovar_lote_http(lote_id: str):
        request_id = _request_id()
        try:
            payload = _payload_json()
            snapshot_hash = str(payload.get("snapshot_hash") or "").strip()
            approval_identity = _normalizar_aprovador_payload(payload)
            aprovado_por = str(approval_identity.get("aprovado_por") or "").strip()
            dry_run = bool(payload.get("dry_run", False))
            modo_execucao = str(payload.get("modo_execucao") or "worker").strip().lower()
            if not snapshot_hash:
                raise ValueError("Campo 'snapshot_hash' e obrigatorio.")
            if not aprovado_por:
                raise ValueError("Campo 'aprovador' e obrigatorio.")
            if modo_execucao not in {"worker", "apps_script"}:
                raise ValueError("Campo 'modo_execucao' deve ser 'worker' ou 'apps_script'.")
        except ValueError as exc:
            return _json_erro(str(exc), 400, codigo="payload_invalido", request_id=request_id)

        validation_store, approval_store, result_store = _stores()
        try:
            if modo_execucao == "apps_script":
                itens_store = LoteItensStore(current_app.config["LOTE_ITENS_DB"])
                registro = aprovar_lote_para_execucao_externa(
                    lote_id=lote_id,
                    aprovado_por=aprovado_por,
                    approval_identity=approval_identity,
                    validation_store=validation_store,
                    approval_store=approval_store,
                    itens_store=itens_store,
                    result_store=result_store,
                    expected_snapshot_hash=snapshot_hash,
                    dry_run=dry_run,
                )
                log.info(
                    "Lote aprovado para execucao Apps Script | request_id=%s | lote_id=%s | snapshot_hash=%s | aprovador=%s",
                    request_id,
                    lote_id,
                    snapshot_hash,
                    aprovado_por,
                )
                return (
                    jsonify(
                        {
                            "status": "accepted",
                            "job_id": None,
                            "modo_execucao": "apps_script",
                            "dry_run": dry_run,
                            "lote_id": lote_id,
                            "snapshot_hash": snapshot_hash,
                            "mensagem": (
                                "Lote aprovado para simulacao via Apps Script."
                                if dry_run
                                else "Lote aprovado para envio via Apps Script."
                            ),
                            "pacote_execucao": {
                                "endpoint": f"/lote/{lote_id}/pacote-execucao",
                            },
                            "request_id": request_id,
                            "resultado_envio": registro.get("send_result"),
                        }
                    ),
                    202,
                )

            validar_solicitacao_aprovacao(
                lote_id=lote_id,
                aprovado_por=aprovado_por,
                approval_identity=approval_identity,
                validation_store=validation_store,
                approval_store=approval_store,
                expected_snapshot_hash=snapshot_hash,
                result_store=result_store,
            )

            job = criar_job_aprovacao_envio(
                lote_id=lote_id,
                aprovado_por=aprovado_por,
                approval_identity=approval_identity,
                snapshot_hash=snapshot_hash,
                source_identifier=lote_id,
                dry_run=dry_run,
                payload=_job_payload_defaults(),
            )

            registro = registrar_solicitacao_aprovacao_envio(
                lote_id=lote_id,
                job_id=int(job.id),
                aprovado_por=aprovado_por,
                approval_identity=approval_identity,
                validation_store=validation_store,
                approval_store=approval_store,
                result_store=result_store,
                expected_snapshot_hash=snapshot_hash,
            )

            log.info(
                "Job de aprovacao/envio criado | request_id=%s | job_id=%s | lote_id=%s | snapshot_hash=%s | aprovador=%s | origem=%s | email=%s",
                request_id,
                job.id,
                lote_id,
                snapshot_hash,
                aprovado_por,
                approval_identity.get("aprovador_origem"),
                approval_identity.get("aprovador_email"),
            )
            return (
                jsonify(
                    {
                        "status": "accepted",
                        "job_id": job.id,
                        "lote_id": lote_id,
                        "snapshot_hash": snapshot_hash,
                        "mensagem": (
                            "Solicitacao de simulacao enviada ao worker."
                            if dry_run
                            else "Solicitacao de aprovacao e envio enviada ao worker."
                        ),
                        "polling": {
                            "endpoint": f"/lote/{lote_id}/resultado-envio",
                            "recomendado_ms": POLLING_RECOMENDADO_MS,
                        },
                        "request_id": request_id,
                        "resultado_envio": registro.get("send_result"),
                    }
                ),
                202,
            )
        except (SnapshotStaleError, LoteJaAprovadoError, LoteNaoElegivelError) as exc:
            return _json_erro(str(exc), 409, codigo="conflito_de_estado", request_id=request_id)
        except KeyError as exc:
            return _json_erro(str(exc), 404, codigo="nao_encontrado", request_id=request_id)
        except ValueError as exc:
            return _json_erro(
                str(exc),
                409 if "status atual" in str(exc).lower() else 400,
                codigo="payload_invalido" if "status atual" not in str(exc).lower() else "conflito_de_estado",
                request_id=request_id,
            )
        except Exception:
            log.exception("Erro interno ao criar job de aprovacao | request_id=%s | lote_id=%s", request_id, lote_id)
            return _json_erro("Erro interno ao processar solicitacao.", 500, codigo="erro_interno", request_id=request_id)

    @app.get("/lote/<path:lote_id>/pacote-execucao")
    @requer_autenticacao
    def obter_pacote_execucao(lote_id: str):
        request_id = _request_id()
        dry_run = str(request.args.get("dry_run") or "").strip().lower() in {
            "1",
            "true",
            "sim",
            "yes",
        }
        validation_store, approval_store, _ = _stores()
        itens_store = LoteItensStore(current_app.config["LOTE_ITENS_DB"])
        try:
            pacote = preparar_pacote_execucao(
                lote_id=lote_id,
                validation_store=validation_store,
                approval_store=approval_store,
                itens_store=itens_store,
                mapa_disciplinas=current_app.config["MAPA_DISCIPLINAS"],
                mapa_avaliacoes=current_app.config["MAPA_AVALIACOES"],
                mapa_professores=current_app.config["MAPA_PROFESSORES"],
                mapa_turmas=current_app.config["MAPA_TURMAS"],
                professor_obrigatorio=True,
                dry_run=dry_run,
            )
            pacote["request_id"] = request_id
            return jsonify(pacote), 200
        except MapaInvalidoError as exc:
            return _json_erro(str(exc), 500, codigo="mapa_invalido", request_id=request_id)
        except KeyError as exc:
            return _json_erro(str(exc), 404, codigo="nao_encontrado", request_id=request_id)
        except ValueError as exc:
            return _json_erro(str(exc), 409, codigo="conflito_de_estado", request_id=request_id)
        except Exception:
            log.exception("Erro interno ao montar pacote de execucao | request_id=%s | lote_id=%s", request_id, lote_id)
            return _json_erro("Erro interno ao montar pacote de execucao.", 500, codigo="erro_interno", request_id=request_id)

    @app.post("/lote/<path:lote_id>/resultado-execucao")
    @requer_autenticacao
    def receber_resultado_execucao(lote_id: str):
        request_id = _request_id()
        try:
            payload = _payload_json()
            snapshot_hash = str(payload.get("snapshot_hash") or "").strip()
            resultados = payload.get("resultados")
            dry_run = bool(payload.get("dry_run", False))
            approval_identity = _normalizar_aprovador_payload(payload)
            aprovado_por = str(approval_identity.get("aprovado_por") or "").strip() or None
            if not snapshot_hash:
                raise ValueError("Campo 'snapshot_hash' e obrigatorio.")
            if not isinstance(resultados, list):
                raise ValueError("Campo 'resultados' deve ser uma lista.")
        except ValueError as exc:
            return _json_erro(str(exc), 400, codigo="payload_invalido", request_id=request_id)

        validation_store, _, result_store = _stores()
        itens_store = LoteItensStore(current_app.config["LOTE_ITENS_DB"])
        audit_store = EnvioLoteAuditStore(current_app.config["ENVIO_LOTE_AUDIT_DB"])
        try:
            registro = registrar_resultado_execucao_externa(
                lote_id=lote_id,
                snapshot_hash=snapshot_hash,
                resultados=resultados,
                validation_store=validation_store,
                itens_store=itens_store,
                result_store=result_store,
                audit_store=audit_store,
                aprovado_por=aprovado_por,
                approval_identity=approval_identity,
                dry_run=dry_run,
            )
            registro["request_id"] = request_id
            return jsonify(registro), 200
        except SnapshotStaleError as exc:
            return _json_erro(str(exc), 409, codigo="snapshot_stale", request_id=request_id)
        except KeyError as exc:
            return _json_erro(str(exc), 404, codigo="nao_encontrado", request_id=request_id)
        except ValueError as exc:
            return _json_erro(str(exc), 400, codigo="payload_invalido", request_id=request_id)
        except Exception:
            log.exception("Erro interno ao registrar resultado externo | request_id=%s | lote_id=%s", request_id, lote_id)
            return _json_erro("Erro interno ao registrar resultado externo.", 500, codigo="erro_interno", request_id=request_id)

    @app.get("/lote/<path:lote_id>/resultado-envio")
    @requer_autenticacao
    def obter_resultado_envio(lote_id: str):
        validation_store, _, result_store = _stores()
        resultado = consultar_resultado_envio_atual(
            lote_id=lote_id,
            validation_store=validation_store,
            result_store=result_store,
        )
        if resultado is None:
            return _json_erro("Resultado de envio nao encontrado para o snapshot atual.", 404)
        resultado["finalizado"] = _resultado_envio_finalizado(str(resultado.get("status") or ""))
        resultado["retry_pendente"] = str(resultado.get("status") or "") == STATUS_SEND_RETRY_SCHEDULED
        resultado["mensagem"] = _mensagem_resultado_envio(resultado)
        resultado["polling"] = {
            "endpoint": f"/lote/{lote_id}/resultado-envio",
            "recomendado_ms": POLLING_RECOMENDADO_MS,
        }
        return jsonify(resultado), 200

    @app.get("/job/<int:job_id>/status")
    @requer_autenticacao
    def obter_status_job(job_id: int):
        try:
            job = obter_job_por_id(job_id)
        except JobStoreError:
            log.exception("Falha ao consultar job | job_id=%s", job_id)
            return _json_erro("Falha ao consultar job.", 500)
        if job is None:
            return _json_erro("Job nao encontrado.", 404)
        return jsonify(_serializar_job(job)), 200

    return app


def _validar_segredo_webhook(segredo: str) -> None:
    if segredo in WEBHOOK_SECRET_INSECURE_VALUES:
        log.error(
            "WEBHOOK_SECRET ausente ou inseguro. Defina WEBHOOK_SECRET com um valor forte antes de iniciar o backend."
        )
        sys.exit(1)


app = create_app()


if __name__ == "__main__":
    _validar_segredo_webhook(app.config["WEBHOOK_SECRET"])
    from waitress import serve

    log.info("Servidor webhook ETL iScholar iniciado na porta 5000 (Waitress WSGI)")
    log.info("Endpoint: POST /webhook/notas")
    log.info("Health:   GET  /health")
    log.info("Snapshots: %s", config.SNAPSHOTS_DIR)
    serve(app, host="0.0.0.0", port=5000)

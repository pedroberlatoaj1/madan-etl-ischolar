"""
webhook_google_sheets.py — Receptor do Webhook disparado pelo Google Apps Script.

Segue a mesma arquitetura do fluxo local: evento → job → worker → transformação → envio.

O webhook:
  1. Recebe POST com dados da planilha (spreadsheet_id, sheet_name, dados)
  2. Valida o segredo (X-Webhook-Secret)
  3. Monta DataFrame em memória e calcula hash do conteúdo
  4. Cria job no SQLite (source_type=google_sheets, idempotência por hash)
  5. Persiste o payload em snapshot (JSON) para o worker consumir
  6. Retorna 202 Accepted com job_id; o worker processa depois

Uso:
  python webhook_google_sheets.py

Endpoint:
  POST /webhook/notas   — recebe dados e cria job
  GET  /health          — saúde do serviço
"""

from __future__ import annotations

import os
import re
import sys
import hmac

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from typing import Any, List

import pandas as pd
from flask import Flask, jsonify, request

from config import config
from job_store import JobStoreError, criar_job_com_idempotencia, registrar_erro
from logger import configurar_logger
from snapshot_store import save_snapshot
from utils.hash_utils import sha256_bytes, sha256_dataframe_normalizado

log = configurar_logger("etl.webhook")

app = Flask(__name__)

# Segredo obrigatório em produção; validado ao iniciar o servidor (__main__).
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "").strip()

# Placeholders inseguros: se o segredo for um deles, o servidor não inicia.
WEBHOOK_SECRET_INSECURE_VALUES = frozenset({
    "",
    "troque_por_um_segredo_forte_em_producao",
    "SUA_CHAVE_AQUI",
    "secret",
    "changeme",
})

# Identificador lógico para jobs do Google Sheets (fonte + aba)
SOURCE_TYPE_GOOGLE_SHEETS = "google_sheets"


def _segredo_valido(segredo_recebido: str) -> bool:
    """Comparação segura contra timing attacks."""
    return hmac.compare_digest(segredo_recebido or "", WEBHOOK_SECRET)


def _dados_para_dataframe(dados: List[dict]) -> pd.DataFrame:
    """Converte a lista de dicts do payload em DataFrame (em memória)."""
    if not dados:
        return pd.DataFrame()
    return pd.DataFrame(dados)


def _normalizar_nome_coluna(nome: str) -> str:
    """
    Normaliza nome de coluna para forma estável (hash agnóstico a variação de cabeçalho).
    Mesma lógica de normalização do transformador: lower, strip, espaços → _, acentos removidos.
    """
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
    """Aplica normalização de nomes de colunas para cálculo de hash estável."""
    if df.empty:
        return df
    df = df.copy()
    df.columns = [_normalizar_nome_coluna(c) for c in df.columns]
    return df


def _calcular_hash_conteudo(df: pd.DataFrame) -> str:
    """
    Hash determinístico do conteúdo para idempotência.
    Normaliza nomes de colunas antes do hash para não depender de cabeçalho bruto (ex.: "Estudante" vs "estudante").
    """
    if df.empty:
        return sha256_bytes(b"__EMPTY_GOOGLE_SHEETS__")
    df_norm = _normalizar_colunas_para_hash(df)
    return sha256_dataframe_normalizado(
        df_norm, sort_by_columns=["estudante", "disciplina"]
    )


# ---------------------------------------------------------------------------
# Autenticação
# ---------------------------------------------------------------------------

def requer_autenticacao(f):
    """Decorator que valida o header X-Webhook-Secret."""
    from functools import wraps
    @wraps(f)
    def decorado(*args, **kwargs):
        segredo = request.headers.get("X-Webhook-Secret", "")
        if not _segredo_valido(segredo):
            log.warning("🔒 Tentativa de acesso não autorizada de %s", request.remote_addr)
            return jsonify({"erro": "Não autorizado"}), 401
        return f(*args, **kwargs)
    return decorado


# ---------------------------------------------------------------------------
# Endpoint principal
# ---------------------------------------------------------------------------

@app.route("/webhook/notas", methods=["POST"])
@requer_autenticacao
def receber_notas_sheets():
    """
    Recebe dados do Google Sheets, cria job no SQLite e persiste snapshot para o worker.

    Payload esperado (JSON):
      - spreadsheet_id: str
      - sheet_name: str
      - dados: list[dict]  (uma linha por dict, chaves = nomes das colunas)

    Respostas:
      - 202: job criado (pending) ou já existente (skipped); body com job_id e status
      - 400: body inválido ou sem dados
      - 401: segredo inválido
      - 422: erro de validação (ex.: dados não formam DataFrame válido)
      - 500: erro ao persistir job ou snapshot
    """
    if not request.is_json:
        log.warning("Requisição sem Content-Type application/json")
        return jsonify({"erro": "Content-Type deve ser application/json"}), 400

    payload: dict[str, Any] = request.get_json(silent=True)
    if payload is None:
        return jsonify({"erro": "Body inválido ou não-JSON"}), 400

    # Validação estrita: campos obrigatórios
    spreadsheet_id = payload.get("spreadsheet_id")
    if spreadsheet_id is None or not str(spreadsheet_id).strip():
        return jsonify({"erro": "Campo 'spreadsheet_id' é obrigatório"}), 400
    spreadsheet_id = str(spreadsheet_id).strip()

    sheet_name = payload.get("sheet_name")
    if sheet_name is None or not str(sheet_name).strip():
        return jsonify({"erro": "Campo 'sheet_name' é obrigatório"}), 400
    sheet_name = str(sheet_name).strip()

    dados = payload.get("dados")
    if dados is None:
        return jsonify({"erro": "Campo 'dados' é obrigatório"}), 400
    if not isinstance(dados, list):
        return jsonify({"erro": "Campo 'dados' deve ser uma lista de objetos"}), 400
    for i, row in enumerate(dados):
        if not isinstance(row, dict):
            return jsonify({
                "erro": "Cada elemento de 'dados' deve ser um objeto",
                "detalhe": f"dados[{i}] não é um objeto",
            }), 400

    log.info(
        "📨 Webhook recebido | spreadsheet_id=%s | sheet_name=%s | registros=%d",
        spreadsheet_id,
        sheet_name,
        len(dados),
    )

    if not dados:
        log.warning("📭 Payload com dados vazios. Possível erro no Apps Script.")
        return jsonify({
            "erro": "Campo 'dados' não pode ser lista vazia",
            "detalhe": "Verifique se o Apps Script está enviando as linhas corretamente.",
        }), 400

    # Identificador lógico da origem (mesmo formato que o worker usa)
    source_identifier = f"{spreadsheet_id}/{sheet_name}"

    try:
        df = _dados_para_dataframe(dados)
        content_hash = _calcular_hash_conteudo(df)
        total_records = len(df)

        log.info(
            "🔑 Hash do conteúdo calculado | source=%s | hash=%s",
            source_identifier,
            content_hash[:16] + "...",
        )

        job = criar_job_com_idempotencia(
            source_type=SOURCE_TYPE_GOOGLE_SHEETS,
            source_identifier=source_identifier,
            content_hash=content_hash,
            total_records=total_records,
        )

        if job.status == "skipped":
            log.info(
                "⏭️ Job %s criado como skipped (conteúdo já processado com sucesso).",
                job.id,
            )
            return jsonify({
                "status": "skipped",
                "job_id": job.id,
                "mensagem": "Conteúdo já processado anteriormente.",
            }), 200

        # Job pending: persistir snapshot para o worker (evitar job sem snapshot)
        try:
            save_snapshot(
                job_id=job.id,
                records=dados,
                source_type=SOURCE_TYPE_GOOGLE_SHEETS,
                source_identifier=source_identifier,
                spreadsheet_id=spreadsheet_id,
                sheet_name=sheet_name,
                content_hash=content_hash,
            )
        except Exception as exc:
            log.exception("Falha ao salvar snapshot para job %s: %s", job.id, exc)
            registrar_erro(
                job.id,
                f"Falha ao persistir snapshot: {exc!s}. Job sem payload para o worker.",
            )
            return jsonify({
                "erro": "Falha ao persistir snapshot",
                "detalhe": str(exc),
                "job_id": job.id,
            }), 500

        log.info(
            "📌 Job %s criado como pending | snapshot salvo | source=%s",
            job.id,
            source_identifier,
        )

        return jsonify({
            "status": "accepted",
            "job_id": job.id,
            "source_identifier": source_identifier,
            "total_records": total_records,
            "mensagem": "Job criado. O worker processará em breve.",
        }), 202

    except JobStoreError as exc:
        log.exception("Falha ao criar job no SQLite: %s", exc)
        return jsonify({"erro": "Falha ao registrar job", "detalhe": str(exc)}), 500
    except Exception as exc:
        log.exception("Erro inesperado no webhook: %s", exc)
        return jsonify({"erro": "Erro interno", "detalhe": "Erro ao processar payload"}), 500


@app.route("/health", methods=["GET"])
def health_check():
    """Saúde do serviço para load balancers e monitoramento."""
    return jsonify({
        "status": "online",
        "servico": "etl-ischolar-webhook",
        "source_type_suportado": SOURCE_TYPE_GOOGLE_SHEETS,
    }), 200


# ---------------------------------------------------------------------------
# Inicialização
# ---------------------------------------------------------------------------

def _validar_segredo_webhook() -> None:
    """Falha ao iniciar se WEBHOOK_SECRET estiver ausente ou for placeholder inseguro."""
    if WEBHOOK_SECRET in WEBHOOK_SECRET_INSECURE_VALUES:
        log.error(
            "❌ WEBHOOK_SECRET ausente ou inseguro. Defina WEBHOOK_SECRET no ambiente "
            "(ex.: .env) com um valor forte e não use placeholders como "
            "'troque_por_um_segredo_forte_em_producao' ou 'changeme'."
        )
        sys.exit(1)


if __name__ == "__main__":
    _validar_segredo_webhook()
    from waitress import serve

    log.info("🚀 Servidor webhook ETL iScholar iniciado na porta 5000 (Waitress WSGI)")
    log.info("   Endpoint: POST /webhook/notas")
    log.info("   Health:   GET  /health")
    log.info("   Snapshots: %s", config.SNAPSHOTS_DIR)
    serve(app, host="0.0.0.0", port=5000)

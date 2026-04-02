"""
validacao_lote_store.py - Persistencia do resultado de validacao pendente de aprovacao.

Guarda o snapshot oficial validado antes da aprovacao humana, permitindo:
- aprovacao assincrona sem rerodar a validacao;
- deteccao de snapshot stale por hash;
- reaproveitamento do pipeline oficial pelo worker e pelo CLI.
"""

from __future__ import annotations

import json
import os
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

_DEFAULT_DB = "validacoes_lote.db"

_DDL = """
CREATE TABLE IF NOT EXISTS validacoes_lote (
    lote_id               TEXT    NOT NULL PRIMARY KEY,
    job_id                INTEGER,
    snapshot_hash         TEXT    NOT NULL,
    status                TEXT    NOT NULL,
    resumo                TEXT    NOT NULL,
    avisos                TEXT    NOT NULL,
    erros                 TEXT    NOT NULL,
    pendencias            TEXT    NOT NULL DEFAULT '[]',
    apto_para_aprovacao   INTEGER NOT NULL,
    resultados_validacao  TEXT    NOT NULL,
    itens_sendaveis       TEXT    NOT NULL,
    versao                INTEGER NOT NULL DEFAULT 1,
    expires_at            TEXT,
    created_at            TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    updated_at            TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);
"""

_UPSERT = """
INSERT INTO validacoes_lote (
    lote_id, job_id, snapshot_hash, status,
    resumo, avisos, erros, pendencias,
    apto_para_aprovacao, resultados_validacao, itens_sendaveis,
    versao, expires_at, created_at, updated_at
) VALUES (
    :lote_id, :job_id, :snapshot_hash, :status,
    :resumo, :avisos, :erros, :pendencias,
    :apto_para_aprovacao, :resultados_validacao, :itens_sendaveis,
    :versao, :expires_at,
    COALESCE(
        (SELECT created_at FROM validacoes_lote WHERE lote_id = :lote_id),
        strftime('%Y-%m-%dT%H:%M:%SZ','now')
    ),
    strftime('%Y-%m-%dT%H:%M:%SZ','now')
)
ON CONFLICT(lote_id) DO UPDATE SET
    job_id               = excluded.job_id,
    snapshot_hash        = excluded.snapshot_hash,
    status               = excluded.status,
    resumo               = excluded.resumo,
    avisos               = excluded.avisos,
    erros                = excluded.erros,
    pendencias           = excluded.pendencias,
    apto_para_aprovacao  = excluded.apto_para_aprovacao,
    resultados_validacao = excluded.resultados_validacao,
    itens_sendaveis      = excluded.itens_sendaveis,
    versao               = excluded.versao,
    expires_at           = excluded.expires_at,
    updated_at           = excluded.updated_at;
"""

_SELECT = """
SELECT
    lote_id, job_id, snapshot_hash, status,
    resumo, avisos, erros, pendencias,
    apto_para_aprovacao, resultados_validacao, itens_sendaveis,
    versao, expires_at, created_at, updated_at
FROM validacoes_lote
WHERE lote_id = ?;
"""

_LIST = "SELECT lote_id FROM validacoes_lote ORDER BY updated_at DESC LIMIT ?;"


def _db_path_from_env() -> str:
    return os.environ.get("VALIDACAO_LOTE_DB", _DEFAULT_DB)


def _json_dumps(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, default=str)


@dataclass
class ResultadoValidacaoPersistido:
    lote_id: str
    job_id: Optional[int]
    snapshot_hash: str
    status: str
    resumo: dict[str, Any]
    avisos: list[dict[str, Any]]
    erros: list[dict[str, Any]]
    pendencias: list[dict[str, Any]]
    apto_para_aprovacao: bool
    resultados_validacao: list[dict[str, Any]]
    itens_sendaveis: list[dict[str, Any]]
    versao: int = 1
    expires_at: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class ValidacaoLoteStore:
    """
    Persistencia SQLite do resultado oficial de validacao por lote.

    Segue o mesmo padrao dos demais stores do projeto, incluindo suporte
    a ':memory:' com conexao compartilhada para testes.
    """

    def __init__(self, db_path: str | Path | None = None) -> None:
        self._db_path = str(db_path) if db_path is not None else _db_path_from_env()
        self._shared_conn: Optional[sqlite3.Connection] = None

        if self._db_path == ":memory:":
            self._shared_conn = self._open_connection()
            self._init_db(self._shared_conn)
        else:
            self._init_db()

    def _open_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path, timeout=5.0)
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA foreign_keys=ON;")
        conn.row_factory = sqlite3.Row
        return conn

    def _connect(self) -> sqlite3.Connection:
        if self._shared_conn is not None:
            return self._shared_conn
        return self._open_connection()

    def _init_db(self, conn: Optional[sqlite3.Connection] = None) -> None:
        if conn is not None:
            conn.executescript(_DDL)
        else:
            with self._open_connection() as tmp:
                tmp.executescript(_DDL)

    def salvar(self, resultado: ResultadoValidacaoPersistido) -> ResultadoValidacaoPersistido:
        params = {
            "lote_id": resultado.lote_id,
            "job_id": resultado.job_id,
            "snapshot_hash": resultado.snapshot_hash,
            "status": resultado.status,
            "resumo": _json_dumps(resultado.resumo),
            "avisos": _json_dumps(resultado.avisos),
            "erros": _json_dumps(resultado.erros),
            "pendencias": _json_dumps(resultado.pendencias),
            "apto_para_aprovacao": int(resultado.apto_para_aprovacao),
            "resultados_validacao": _json_dumps(resultado.resultados_validacao),
            "itens_sendaveis": _json_dumps(resultado.itens_sendaveis),
            "versao": int(resultado.versao),
            "expires_at": resultado.expires_at,
        }
        with self._connect() as conn:
            conn.execute(_UPSERT, params)
        salvo = self.carregar(resultado.lote_id)
        if salvo is None:
            raise RuntimeError(f"Falha ao recarregar validacao persistida do lote '{resultado.lote_id}'.")
        return salvo

    def carregar(self, lote_id: str) -> Optional[ResultadoValidacaoPersistido]:
        with self._connect() as conn:
            row = conn.execute(_SELECT, (lote_id,)).fetchone()
        if row is None:
            return None
        return ResultadoValidacaoPersistido(
            lote_id=row["lote_id"],
            job_id=row["job_id"],
            snapshot_hash=row["snapshot_hash"],
            status=row["status"],
            resumo=json.loads(row["resumo"]),
            avisos=json.loads(row["avisos"]),
            erros=json.loads(row["erros"]),
            pendencias=json.loads(row["pendencias"]),
            apto_para_aprovacao=bool(row["apto_para_aprovacao"]),
            resultados_validacao=json.loads(row["resultados_validacao"]),
            itens_sendaveis=json.loads(row["itens_sendaveis"]),
            versao=int(row["versao"]),
            expires_at=row["expires_at"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def listar_ids(self, limit: int = 1000) -> list[str]:
        with self._connect() as conn:
            rows = conn.execute(_LIST, (limit,)).fetchall()
        return [r["lote_id"] for r in rows]


__all__ = ["ResultadoValidacaoPersistido", "ValidacaoLoteStore"]

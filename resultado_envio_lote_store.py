"""
resultado_envio_lote_store.py - Persistencia do resultado consolidado do envio por lote.

Mantem o estado agregado da fase assincrona de aprovacao/envio, permitindo:
- consulta do resultado final sem ler toda a auditoria por item;
- bloqueio de dupla aprovacao para o mesmo snapshot;
- rastreabilidade entre job assíncrono, snapshot validado e auditoria.
"""

from __future__ import annotations

import json
import os
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

_DEFAULT_DB = "resultados_envio_lote.db"

_DDL = """
CREATE TABLE IF NOT EXISTS resultados_envio_lote (
    lote_id                TEXT    NOT NULL PRIMARY KEY,
    job_id                 INTEGER,
    snapshot_hash          TEXT    NOT NULL,
    status                 TEXT    NOT NULL,
    aprovado_por           TEXT,
    aprovador_nome_informado TEXT,
    aprovador_email        TEXT,
    aprovador_origem       TEXT,
    aprovador_identity_strength TEXT,
    sucesso                INTEGER NOT NULL,
    quantidade_enviada     INTEGER NOT NULL,
    quantidade_com_erro    INTEGER NOT NULL,
    total_sendaveis        INTEGER NOT NULL,
    total_dry_run          INTEGER NOT NULL,
    total_erros_resolucao  INTEGER NOT NULL,
    total_erros_envio      INTEGER NOT NULL,
    mensagem               TEXT,
    resumo                 TEXT    NOT NULL,
    auditoria_resumo       TEXT    NOT NULL,
    finished_at            TEXT,
    created_at             TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    updated_at             TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);
"""

_UPSERT = """
INSERT INTO resultados_envio_lote (
    lote_id, job_id, snapshot_hash, status, aprovado_por,
    aprovador_nome_informado, aprovador_email, aprovador_origem,
    aprovador_identity_strength, sucesso,
    quantidade_enviada, quantidade_com_erro, total_sendaveis, total_dry_run,
    total_erros_resolucao, total_erros_envio, mensagem,
    resumo, auditoria_resumo, finished_at, created_at, updated_at
) VALUES (
    :lote_id, :job_id, :snapshot_hash, :status, :aprovado_por,
    :aprovador_nome_informado, :aprovador_email, :aprovador_origem,
    :aprovador_identity_strength, :sucesso,
    :quantidade_enviada, :quantidade_com_erro, :total_sendaveis, :total_dry_run,
    :total_erros_resolucao, :total_erros_envio, :mensagem,
    :resumo, :auditoria_resumo, :finished_at,
    COALESCE(
        (SELECT created_at FROM resultados_envio_lote WHERE lote_id = :lote_id),
        strftime('%Y-%m-%dT%H:%M:%SZ','now')
    ),
    strftime('%Y-%m-%dT%H:%M:%SZ','now')
)
ON CONFLICT(lote_id) DO UPDATE SET
    job_id                = excluded.job_id,
    snapshot_hash         = excluded.snapshot_hash,
    status                = excluded.status,
    aprovado_por          = excluded.aprovado_por,
    aprovador_nome_informado = excluded.aprovador_nome_informado,
    aprovador_email       = excluded.aprovador_email,
    aprovador_origem      = excluded.aprovador_origem,
    aprovador_identity_strength = excluded.aprovador_identity_strength,
    sucesso               = excluded.sucesso,
    quantidade_enviada    = excluded.quantidade_enviada,
    quantidade_com_erro   = excluded.quantidade_com_erro,
    total_sendaveis       = excluded.total_sendaveis,
    total_dry_run         = excluded.total_dry_run,
    total_erros_resolucao = excluded.total_erros_resolucao,
    total_erros_envio     = excluded.total_erros_envio,
    mensagem              = excluded.mensagem,
    resumo                = excluded.resumo,
    auditoria_resumo      = excluded.auditoria_resumo,
    finished_at           = excluded.finished_at,
    updated_at            = excluded.updated_at;
"""

_SELECT = """
SELECT
    lote_id, job_id, snapshot_hash, status, aprovado_por,
    aprovador_nome_informado, aprovador_email, aprovador_origem,
    aprovador_identity_strength, sucesso,
    quantidade_enviada, quantidade_com_erro, total_sendaveis, total_dry_run,
    total_erros_resolucao, total_erros_envio, mensagem,
    resumo, auditoria_resumo, finished_at, created_at, updated_at
FROM resultados_envio_lote
WHERE lote_id = ?;
"""

_LIST = "SELECT lote_id FROM resultados_envio_lote ORDER BY updated_at DESC LIMIT ?;"


def _db_path_from_env() -> str:
    return os.environ.get("RESULTADO_ENVIO_LOTE_DB", _DEFAULT_DB)


def _json_dumps(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, default=str)


def _ensure_columns(conn: sqlite3.Connection) -> None:
    cur = conn.execute("PRAGMA table_info(resultados_envio_lote)")
    colunas = {row["name"] for row in cur.fetchall()}
    novas_colunas = {
        "aprovador_nome_informado": "TEXT",
        "aprovador_email": "TEXT",
        "aprovador_origem": "TEXT",
        "aprovador_identity_strength": "TEXT",
    }
    for nome, ddl in novas_colunas.items():
        if nome not in colunas:
            conn.execute(f"ALTER TABLE resultados_envio_lote ADD COLUMN {nome} {ddl}")


@dataclass
class ResultadoEnvioPersistido:
    lote_id: str
    job_id: Optional[int]
    snapshot_hash: str
    status: str
    aprovado_por: Optional[str]
    aprovador_nome_informado: Optional[str]
    aprovador_email: Optional[str]
    aprovador_origem: Optional[str]
    aprovador_identity_strength: Optional[str]
    sucesso: bool
    quantidade_enviada: int
    quantidade_com_erro: int
    total_sendaveis: int
    total_dry_run: int
    total_erros_resolucao: int
    total_erros_envio: int
    mensagem: Optional[str]
    resumo: dict[str, Any]
    auditoria_resumo: dict[str, int]
    finished_at: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class ResultadoEnvioLoteStore:
    """Persistencia SQLite do resultado agregado de envio."""

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
            _ensure_columns(conn)
        else:
            with self._open_connection() as tmp:
                tmp.executescript(_DDL)
                _ensure_columns(tmp)

    def salvar(self, resultado: ResultadoEnvioPersistido) -> ResultadoEnvioPersistido:
        params = {
            "lote_id": resultado.lote_id,
            "job_id": resultado.job_id,
            "snapshot_hash": resultado.snapshot_hash,
            "status": resultado.status,
            "aprovado_por": resultado.aprovado_por,
            "aprovador_nome_informado": resultado.aprovador_nome_informado,
            "aprovador_email": resultado.aprovador_email,
            "aprovador_origem": resultado.aprovador_origem,
            "aprovador_identity_strength": resultado.aprovador_identity_strength,
            "sucesso": int(resultado.sucesso),
            "quantidade_enviada": int(resultado.quantidade_enviada),
            "quantidade_com_erro": int(resultado.quantidade_com_erro),
            "total_sendaveis": int(resultado.total_sendaveis),
            "total_dry_run": int(resultado.total_dry_run),
            "total_erros_resolucao": int(resultado.total_erros_resolucao),
            "total_erros_envio": int(resultado.total_erros_envio),
            "mensagem": resultado.mensagem,
            "resumo": _json_dumps(resultado.resumo),
            "auditoria_resumo": _json_dumps(resultado.auditoria_resumo),
            "finished_at": resultado.finished_at,
        }
        with self._connect() as conn:
            conn.execute(_UPSERT, params)
        salvo = self.carregar(resultado.lote_id)
        if salvo is None:
            raise RuntimeError(
                f"Falha ao recarregar resultado de envio persistido do lote '{resultado.lote_id}'."
            )
        return salvo

    def carregar(self, lote_id: str) -> Optional[ResultadoEnvioPersistido]:
        with self._connect() as conn:
            row = conn.execute(_SELECT, (lote_id,)).fetchone()
        if row is None:
            return None
        return ResultadoEnvioPersistido(
            lote_id=row["lote_id"],
            job_id=row["job_id"],
            snapshot_hash=row["snapshot_hash"],
            status=row["status"],
            aprovado_por=row["aprovado_por"],
            aprovador_nome_informado=row["aprovador_nome_informado"],
            aprovador_email=row["aprovador_email"],
            aprovador_origem=row["aprovador_origem"],
            aprovador_identity_strength=row["aprovador_identity_strength"],
            sucesso=bool(row["sucesso"]),
            quantidade_enviada=int(row["quantidade_enviada"]),
            quantidade_com_erro=int(row["quantidade_com_erro"]),
            total_sendaveis=int(row["total_sendaveis"]),
            total_dry_run=int(row["total_dry_run"]),
            total_erros_resolucao=int(row["total_erros_resolucao"]),
            total_erros_envio=int(row["total_erros_envio"]),
            mensagem=row["mensagem"],
            resumo=json.loads(row["resumo"]),
            auditoria_resumo=json.loads(row["auditoria_resumo"]),
            finished_at=row["finished_at"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def listar_ids(self, limit: int = 1000) -> list[str]:
        with self._connect() as conn:
            rows = conn.execute(_LIST, (limit,)).fetchall()
        return [r["lote_id"] for r in rows]


__all__ = ["ResultadoEnvioPersistido", "ResultadoEnvioLoteStore"]

"""
aprovacao_lote_store.py — Etapa 4 (persistência)

Camada de persistência do estado de aprovação do lote via SQLite.
Usa apenas stdlib (sqlite3, json, pathlib) — sem dependência externa.

Responsabilidades:
  - salvar(estado)  : insert ou update do estado completo
  - carregar(lote_id) : reconstrói EstadoAprovacaoLote a partir do banco
  - listar_ids()    : lista todos os lote_id conhecidos

O arquivo de banco é criado automaticamente no primeiro uso.
Caminho padrão: "aprovacoes_lote.db" (diretório de trabalho).
Pode ser sobrescrito via variável de ambiente APROVACAO_LOTE_DB ou
passando db_path explicitamente no construtor.

Limitações conhecidas (antes da Etapa 5 / envio real):
  - Não implementa locking distribuído; adequado para uso single-process.
  - Não há migração automática de schema; ao alterar colunas, recriar o banco
    ou aplicar ALTER TABLE manualmente.
  - Não há paginação em listar_ids(); para lotes grandes usar listar_ids(limit=N).
"""

from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from aprovacao_lote import EstadoAprovacaoLote

_DEFAULT_DB = "aprovacoes_lote.db"

_DDL = """
CREATE TABLE IF NOT EXISTS aprovacoes_lote (
    lote_id                     TEXT    NOT NULL PRIMARY KEY,
    status                      TEXT    NOT NULL,
    elegivel_para_aprovacao     INTEGER NOT NULL,   -- 0 | 1 (SQLite não tem BOOL)
    resumo_atual                TEXT    NOT NULL,   -- JSON
    aprovado_por                TEXT,
    aprovador_nome_informado    TEXT,
    aprovador_email             TEXT,
    aprovador_origem            TEXT,
    aprovador_identity_strength TEXT,
    aprovado_em                 TEXT,
    rejeitado_por               TEXT,
    rejeitado_em                TEXT,
    motivo_rejeicao             TEXT,
    snapshot_resumo_aprovado    TEXT,               -- JSON | NULL
    hash_resumo_aprovado        TEXT,               -- hex SHA-256 | NULL
    criado_em                   TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    atualizado_em               TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);
"""

_UPSERT = """
INSERT INTO aprovacoes_lote (
    lote_id, status, elegivel_para_aprovacao,
    resumo_atual,
    aprovado_por, aprovador_nome_informado, aprovador_email,
    aprovador_origem, aprovador_identity_strength, aprovado_em,
    rejeitado_por, rejeitado_em, motivo_rejeicao,
    snapshot_resumo_aprovado, hash_resumo_aprovado,
    criado_em, atualizado_em
) VALUES (
    :lote_id, :status, :elegivel,
    :resumo_atual_json,
    :aprovado_por, :aprovador_nome_informado, :aprovador_email,
    :aprovador_origem, :aprovador_identity_strength, :aprovado_em,
    :rejeitado_por, :rejeitado_em, :motivo_rejeicao,
    :snapshot_json, :hash_resumo_aprovado,
    COALESCE(
        (SELECT criado_em FROM aprovacoes_lote WHERE lote_id = :lote_id),
        strftime('%Y-%m-%dT%H:%M:%SZ','now')
    ),
    strftime('%Y-%m-%dT%H:%M:%SZ','now')
)
ON CONFLICT(lote_id) DO UPDATE SET
    status                   = excluded.status,
    elegivel_para_aprovacao  = excluded.elegivel_para_aprovacao,
    resumo_atual             = excluded.resumo_atual,
    aprovado_por             = excluded.aprovado_por,
    aprovador_nome_informado = excluded.aprovador_nome_informado,
    aprovador_email          = excluded.aprovador_email,
    aprovador_origem         = excluded.aprovador_origem,
    aprovador_identity_strength = excluded.aprovador_identity_strength,
    aprovado_em              = excluded.aprovado_em,
    rejeitado_por            = excluded.rejeitado_por,
    rejeitado_em             = excluded.rejeitado_em,
    motivo_rejeicao          = excluded.motivo_rejeicao,
    snapshot_resumo_aprovado = excluded.snapshot_resumo_aprovado,
    hash_resumo_aprovado     = excluded.hash_resumo_aprovado,
    atualizado_em            = excluded.atualizado_em;
"""

_SELECT = """
SELECT
    lote_id, status, elegivel_para_aprovacao,
    resumo_atual,
    aprovado_por, aprovador_nome_informado, aprovador_email,
    aprovador_origem, aprovador_identity_strength, aprovado_em,
    rejeitado_por, rejeitado_em, motivo_rejeicao,
    snapshot_resumo_aprovado, hash_resumo_aprovado
FROM aprovacoes_lote
WHERE lote_id = ?;
"""

_LIST = "SELECT lote_id FROM aprovacoes_lote ORDER BY atualizado_em DESC LIMIT ?;"


def _db_path_from_env() -> str:
    return os.environ.get("APROVACAO_LOTE_DB", _DEFAULT_DB)


def _json_dumps(obj: object) -> str:
    """Serialização determinística (sort_keys garante hash estável)."""
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, default=str)


def _ensure_columns(conn: sqlite3.Connection) -> None:
    cur = conn.execute("PRAGMA table_info(aprovacoes_lote)")
    colunas = {row["name"] for row in cur.fetchall()}
    novas_colunas = {
        "aprovador_nome_informado": "TEXT",
        "aprovador_email": "TEXT",
        "aprovador_origem": "TEXT",
        "aprovador_identity_strength": "TEXT",
    }
    for nome, ddl in novas_colunas.items():
        if nome not in colunas:
            conn.execute(f"ALTER TABLE aprovacoes_lote ADD COLUMN {nome} {ddl}")


class AprovacaoLoteStore:
    """
    Gerenciador de persistência de EstadoAprovacaoLote via SQLite.

    Uso típico:
        store = AprovacaoLoteStore()               # usa APROVACAO_LOTE_DB ou "aprovacoes_lote.db"
        store = AprovacaoLoteStore("meu_banco.db") # caminho explícito
        store = AprovacaoLoteStore(":memory:")     # banco em memória (testes)

    Nota sobre :memory::
        SQLite cria um banco novo por conexão quando db_path == ":memory:".
        Para preservar o schema entre operações, o store mantém uma única
        conexão compartilhada (_shared_conn) durante toda a vida da instância.
        Bancos em arquivo continuam abrindo uma conexão nova por operação
        (comportamento original).
    """

    def __init__(self, db_path: str | Path | None = None) -> None:
        self._db_path = str(db_path) if db_path is not None else _db_path_from_env()
        self._shared_conn: Optional[sqlite3.Connection] = None

        if self._db_path == ":memory:":
            # Abre e mantém a conexão para a vida inteira da instância.
            # _init_db recebe a conexão já aberta para que o schema seja
            # criado no mesmo banco que será usado nas operações seguintes.
            self._shared_conn = self._open_connection()
            self._init_db(self._shared_conn)
        else:
            self._init_db()

    # ------------------------------------------------------------------
    # Infraestrutura de conexão
    # ------------------------------------------------------------------

    def _open_connection(self) -> sqlite3.Connection:
        """
        Abre uma conexão física, configura PRAGMAs e row_factory.
        Sempre retorna uma conexão nova; nunca consulta _shared_conn.
        """
        conn = sqlite3.connect(self._db_path, timeout=5.0)
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA foreign_keys=ON;")
        conn.row_factory = sqlite3.Row
        return conn

    def _connect(self) -> sqlite3.Connection:
        """
        Retorna a conexão compartilhada (banco em memória) ou abre uma nova
        (banco em arquivo).

        Para banco em memória, o chamador NÃO deve fechar a conexão retornada
        — ela é gerenciada pelo ciclo de vida da instância.
        Para banco em arquivo, o comportamento de uso-com-context-manager
        (with self._connect() as conn) permanece o mesmo de antes.
        """
        if self._shared_conn is not None:
            return self._shared_conn
        return self._open_connection()

    def _init_db(self, conn: Optional[sqlite3.Connection] = None) -> None:
        """
        Inicializa o schema.

        Se `conn` for informado (caso :memory:), executa o DDL nessa conexão
        e não a fecha ao terminar.
        Se `conn` for None (caso arquivo), abre uma conexão temporária,
        executa o DDL e fecha via context manager.
        """
        if conn is not None:
            conn.executescript(_DDL)
            _ensure_columns(conn)
        else:
            with self._open_connection() as tmp:
                tmp.executescript(_DDL)
                _ensure_columns(tmp)

    # ------------------------------------------------------------------
    # API pública
    # ------------------------------------------------------------------

    def salvar(self, estado: "EstadoAprovacaoLote") -> None:
        """
        Persiste (insert ou update) o estado completo do lote.
        Idempotente: pode ser chamado múltiplas vezes para o mesmo lote_id.
        """
        snapshot = estado.snapshot_resumo_aprovado
        params = {
            "lote_id":              estado.lote_id,
            "status":               estado.status,
            "elegivel":             int(estado.elegivel_para_aprovacao),
            "resumo_atual_json":    _json_dumps(estado.resumo_atual),
            "aprovado_por":         estado.aprovado_por,
            "aprovador_nome_informado": getattr(estado, "aprovador_nome_informado", None),
            "aprovador_email":      getattr(estado, "aprovador_email", None),
            "aprovador_origem":     getattr(estado, "aprovador_origem", None),
            "aprovador_identity_strength": getattr(estado, "aprovador_identity_strength", None),
            "aprovado_em":          estado.aprovado_em,
            "rejeitado_por":        estado.rejeitado_por,
            "rejeitado_em":         estado.rejeitado_em,
            "motivo_rejeicao":      estado.motivo_rejeicao,
            "snapshot_json":        _json_dumps(snapshot) if snapshot is not None else None,
            "hash_resumo_aprovado": getattr(estado, "hash_resumo_aprovado", None),
        }
        with self._connect() as conn:
            conn.execute(_UPSERT, params)

    def carregar(self, lote_id: str) -> Optional["EstadoAprovacaoLote"]:
        """
        Reconstrói EstadoAprovacaoLote a partir do banco.
        Retorna None se o lote_id não existir.
        """
        # Import local para evitar dependência circular em tempo de módulo.
        from aprovacao_lote import EstadoAprovacaoLote  # noqa: PLC0415

        with self._connect() as conn:
            row = conn.execute(_SELECT, (lote_id,)).fetchone()

        if row is None:
            return None

        resumo_atual = json.loads(row["resumo_atual"])
        snap_raw = row["snapshot_resumo_aprovado"]
        snapshot = json.loads(snap_raw) if snap_raw is not None else None

        estado = EstadoAprovacaoLote(
            lote_id=row["lote_id"],
            status=row["status"],
            elegivel_para_aprovacao=bool(row["elegivel_para_aprovacao"]),
            resumo_atual=resumo_atual,
            aprovado_por=row["aprovado_por"],
            aprovador_nome_informado=row["aprovador_nome_informado"],
            aprovador_email=row["aprovador_email"],
            aprovador_origem=row["aprovador_origem"],
            aprovador_identity_strength=row["aprovador_identity_strength"],
            aprovado_em=row["aprovado_em"],
            rejeitado_por=row["rejeitado_por"],
            rejeitado_em=row["rejeitado_em"],
            motivo_rejeicao=row["motivo_rejeicao"],
            snapshot_resumo_aprovado=snapshot,
            hash_resumo_aprovado=row["hash_resumo_aprovado"],
        )
        return estado

    def listar_ids(self, limit: int = 1000) -> list[str]:
        """Retorna lote_ids ordenados por atualização mais recente."""
        with self._connect() as conn:
            rows = conn.execute(_LIST, (limit,)).fetchall()
        return [r["lote_id"] for r in rows]


__all__ = ["AprovacaoLoteStore"]

"""
lote_itens_store.py — Etapa 4.5 (persistência do conjunto aprovado)

Persiste o conjunto exato de lançamentos sendáveis aprovados para um lote.

Motivação:
  Antes deste módulo, enviar_lote() recebia `resultados_etapa3` como parâmetro
  externo, sem garantia de que esse iterable correspondesse ao conjunto que foi
  aprovado. Agora o vínculo é estrutural:

    APROVAÇÃO → salvar_itens(lote_id, itens)
    ENVIO     → carregar_itens(lote_id)

  Nenhum caminho fora desse ciclo pode injetar itens no fluxo de envio.

Chamadores:
  - aprovacao_lote.aprovar_lote()  → salvar_itens (via itens_store)
  - envio_lote.enviar_lote()       → carregar_itens

Não é chamado por worker, job_store, transformador nem pelo fluxo legado.

Limitações (documentadas, mesmo padrão dos outros stores):
  - Single-process; sem locking distribuído.
  - Sem migração automática de schema.
  - Uma linha por lote (itens como JSON blob). Para lotes muito grandes
    (> ~50k itens), considere sharding ou armazenamento externo.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from pathlib import Path
from typing import Any, Optional

_DEFAULT_DB = "lote_itens.db"

_DDL = """
CREATE TABLE IF NOT EXISTS lote_itens (
    lote_id     TEXT    NOT NULL PRIMARY KEY,
    itens_json  TEXT    NOT NULL,           -- JSON array de dicts (lançamentos sendáveis)
    total_itens INTEGER NOT NULL,
    hash_itens  TEXT    NOT NULL,           -- SHA-256(itens_json) para verificação de integridade
    criado_em   TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    atualizado_em TEXT  NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);
"""

# UPSERT — idempotente para retry de aprovação com o mesmo lote_id.
# Na prática deve ser chamado uma vez por lote; o ON CONFLICT é uma rede de segurança.
_UPSERT = """
INSERT INTO lote_itens (lote_id, itens_json, total_itens, hash_itens, criado_em, atualizado_em)
VALUES (
    :lote_id, :itens_json, :total_itens, :hash_itens,
    COALESCE(
        (SELECT criado_em FROM lote_itens WHERE lote_id = :lote_id),
        strftime('%Y-%m-%dT%H:%M:%SZ','now')
    ),
    strftime('%Y-%m-%dT%H:%M:%SZ','now')
)
ON CONFLICT(lote_id) DO UPDATE SET
    itens_json    = excluded.itens_json,
    total_itens   = excluded.total_itens,
    hash_itens    = excluded.hash_itens,
    atualizado_em = excluded.atualizado_em;
"""

_SELECT = "SELECT itens_json, hash_itens FROM lote_itens WHERE lote_id = ?;"
_EXISTS = "SELECT 1 FROM lote_itens WHERE lote_id = ? LIMIT 1;"


def _db_path_from_env() -> str:
    return os.environ.get("LOTE_ITENS_DB", _DEFAULT_DB)


def _json_dumps_canonico(obj: Any) -> str:
    """Serialização determinística. sort_keys garante hash estável."""
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, default=str)


def _hash_itens(itens_json: str) -> str:
    return hashlib.sha256(itens_json.encode("utf-8")).hexdigest()


class LoteItensStore:
    """
    Gerenciador de persistência do conjunto canônico de itens sendáveis aprovados.

    Uso típico:
        store = LoteItensStore()           # usa LOTE_ITENS_DB ou "lote_itens.db"
        store = LoteItensStore(":memory:") # banco em memória (testes)

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
        else:
            with self._open_connection() as tmp:
                tmp.executescript(_DDL)

    # ------------------------------------------------------------------
    # API pública
    # ------------------------------------------------------------------

    def salvar_itens(self, lote_id: str, itens: list[dict[str, Any]]) -> None:
        """
        Persiste o conjunto de lançamentos sendáveis do lote aprovado.

        Deve ser chamado APENAS pelo fluxo de aprovação (aprovar_lote).
        Idempotente: re-chamadas com o mesmo lote_id sobrescrevem o registro.
        """
        itens_json = _json_dumps_canonico(itens)
        params = {
            "lote_id":    lote_id,
            "itens_json": itens_json,
            "total_itens": len(itens),
            "hash_itens": _hash_itens(itens_json),
        }
        with self._connect() as conn:
            conn.execute(_UPSERT, params)

    def carregar_itens(self, lote_id: str) -> Optional[list[dict[str, Any]]]:
        """
        Reconstrói a lista de lançamentos sendáveis aprovados.
        Retorna None se o lote_id não existir (nunca foi aprovado com store).
        """
        with self._connect() as conn:
            row = conn.execute(_SELECT, (lote_id,)).fetchone()
        if row is None:
            return None
        return json.loads(row["itens_json"])

    def existe(self, lote_id: str) -> bool:
        """True se o lote_id tem itens aprovados persistidos."""
        with self._connect() as conn:
            row = conn.execute(_EXISTS, (lote_id,)).fetchone()
        return row is not None

    def verificar_integridade(self, lote_id: str) -> bool:
        """
        Verifica se os itens persistidos não foram adulterados (via hash SHA-256).
        Retorna False se o lote não existir ou se o hash divergir.
        """
        with self._connect() as conn:
            row = conn.execute(_SELECT, (lote_id,)).fetchone()
        if row is None:
            return False
        return _hash_itens(row["itens_json"]) == row["hash_itens"]


__all__ = ["LoteItensStore"]

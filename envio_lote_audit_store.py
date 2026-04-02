"""
envio_lote_audit_store.py — Etapa 5 (persistência de auditoria por item) v2
 
--- Mudança em relação ao v1 ---
 
UNIQUE key anterior (fraca, colide por nome):
  (lote_id, estudante, componente, disciplina, trimestre)
 
UNIQUE key nova (estável, resistente a colisão):
  (lote_id, item_key)
 
  item_key vem de ResultadoItemEnvio.item_key, calculado por
  envio_lote._compute_item_key():
    - hash_conteudo do lançamento (calculado pelo transformador), se presente
    - SHA-256(lote_id | linha_origem | componente | subcomponente) como fallback
 
  Nunca colide por nome de aluno homonômico, alias de disciplina ou componente.
 
AVISO DE MIGRAÇÃO:
  Este é um schema break. Bancos criados pelo v1 precisam ser recriados ou
  terem ALTER TABLE aplicado manualmente. Não há migração automática.
  Para desenvolvimento: apagar o arquivo .db e deixar o DDL recriar.
 
Mantido inalterado do v1:
  - Uso apenas stdlib (sqlite3, json, pathlib)
  - WAL mode, single-process
  - salvar_item(), listar_itens(), resumo_lote()
"""
 
from __future__ import annotations
 
import json
import os
import sqlite3
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional
 
if TYPE_CHECKING:
    from envio_lote import ResultadoItemEnvio
 
_DEFAULT_DB = "envio_lote_audit.db"
 
_DDL = """
CREATE TABLE IF NOT EXISTS envio_lote_audit (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    lote_id             TEXT    NOT NULL,
    item_key            TEXT    NOT NULL,           -- identidade estável (hash_conteudo ou SHA-256 estrutural)
    estudante           TEXT,
    componente          TEXT,
    disciplina          TEXT,
    trimestre           TEXT,
    valor_bruta         REAL,
    id_matricula        INTEGER,
    id_disciplina       INTEGER,
    id_avaliacao        INTEGER,
    id_professor        INTEGER,
    dry_run             INTEGER NOT NULL,           -- 0 | 1
    status              TEXT    NOT NULL,           -- "enviado" | "dry_run" | "erro_resolucao" | "erro_envio"
    mensagem            TEXT,
    transitorio         INTEGER NOT NULL DEFAULT 0,
    payload_enviado     TEXT,                       -- JSON | NULL
    resposta_api        TEXT,                       -- JSON | NULL
    erros_resolucao     TEXT,                       -- JSON array | NULL
    rastreabilidade     TEXT,                       -- JSON | NULL
    timestamp           TEXT    NOT NULL,
    criado_em           TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    atualizado_em       TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    UNIQUE (lote_id, item_key)                      -- identidade forte; substitui chave fraca do v1
);
"""
 
_UPSERT = """
INSERT INTO envio_lote_audit (
    lote_id, item_key,
    estudante, componente, disciplina, trimestre,
    valor_bruta, id_matricula, id_disciplina, id_avaliacao, id_professor,
    dry_run, status, mensagem, transitorio,
    payload_enviado, resposta_api, erros_resolucao, rastreabilidade,
    timestamp, criado_em, atualizado_em
) VALUES (
    :lote_id, :item_key,
    :estudante, :componente, :disciplina, :trimestre,
    :valor_bruta, :id_matricula, :id_disciplina, :id_avaliacao, :id_professor,
    :dry_run, :status, :mensagem, :transitorio,
    :payload_enviado, :resposta_api, :erros_resolucao, :rastreabilidade,
    :timestamp,
    COALESCE(
        (SELECT criado_em FROM envio_lote_audit
         WHERE lote_id = :lote_id AND item_key = :item_key),
        strftime('%Y-%m-%dT%H:%M:%SZ','now')
    ),
    strftime('%Y-%m-%dT%H:%M:%SZ','now')
)
ON CONFLICT(lote_id, item_key) DO UPDATE SET
    estudante        = excluded.estudante,
    componente       = excluded.componente,
    disciplina       = excluded.disciplina,
    trimestre        = excluded.trimestre,
    valor_bruta      = excluded.valor_bruta,
    id_matricula     = excluded.id_matricula,
    id_disciplina    = excluded.id_disciplina,
    id_avaliacao     = excluded.id_avaliacao,
    id_professor     = excluded.id_professor,
    dry_run          = excluded.dry_run,
    status           = excluded.status,
    mensagem         = excluded.mensagem,
    transitorio      = excluded.transitorio,
    payload_enviado  = excluded.payload_enviado,
    resposta_api     = excluded.resposta_api,
    erros_resolucao  = excluded.erros_resolucao,
    rastreabilidade  = excluded.rastreabilidade,
    timestamp        = excluded.timestamp,
    atualizado_em    = excluded.atualizado_em;
"""
 
_SELECT_LOTE = "SELECT * FROM envio_lote_audit WHERE lote_id = ? ORDER BY id;"
 
_RESUMO = """
SELECT status, COUNT(*) AS total
FROM envio_lote_audit
WHERE lote_id = ?
GROUP BY status;
"""
 
 
def _db_path_from_env() -> str:
    return os.environ.get("ENVIO_LOTE_AUDIT_DB", _DEFAULT_DB)
 
 
def _json_dumps(obj: Any) -> Optional[str]:
    if obj is None:
        return None
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, default=str)
 
 
class EnvioLoteAuditStore:
    """
    Gerenciador de persistência de ResultadoItemEnvio via SQLite.
 
    Uso típico:
        store = EnvioLoteAuditStore()           # usa ENVIO_LOTE_AUDIT_DB ou "envio_lote_audit.db"
        store = EnvioLoteAuditStore(":memory:") # banco em memória (testes)
 
    A chave de unicidade (lote_id, item_key) garante que re-envios (retry)
    de um mesmo lançamento sobrescrevam o registro anterior sem criar duplicata.
    item_key é calculado por envio_lote._compute_item_key() e nunca depende
    de strings de nome.

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
 
    def salvar_item(self, item: "ResultadoItemEnvio") -> None:
        """
        Persiste (insert ou update) um ResultadoItemEnvio.
        Idempotente: re-chamar com o mesmo (lote_id, item_key) sobrescreve.
        """
        params: dict[str, Any] = {
            "lote_id":        item.lote_id,
            "item_key":       item.item_key,
            "estudante":      item.estudante,
            "componente":     item.componente,
            "disciplina":     item.disciplina,
            "trimestre":      item.trimestre,
            "valor_bruta":    item.valor_bruta,
            "id_matricula":   item.id_matricula,
            "id_disciplina":  item.id_disciplina,
            "id_avaliacao":   item.id_avaliacao,
            "id_professor":   item.id_professor,
            "dry_run":        int(item.dry_run),
            "status":         item.status,
            "mensagem":       item.mensagem,
            "transitorio":    int(item.transitorio),
            "payload_enviado":  _json_dumps(item.payload_enviado),
            "resposta_api":     _json_dumps(item.resposta_api),
            "erros_resolucao":  _json_dumps(item.erros_resolucao),
            "rastreabilidade":  _json_dumps(item.rastreabilidade),
            "timestamp":        item.timestamp,
        }
        with self._connect() as conn:
            conn.execute(_UPSERT, params)
 
    def listar_itens(self, lote_id: str) -> list[dict[str, Any]]:
        """
        Retorna todos os itens de auditoria de um lote como lista de dicts.
        Retorna lista vazia se o lote_id não tiver registros.
        """
        with self._connect() as conn:
            rows = conn.execute(_SELECT_LOTE, (lote_id,)).fetchall()
        return [dict(r) for r in rows]
 
    def resumo_lote(self, lote_id: str) -> dict[str, int]:
        """
        Retorna contagens por status: {"enviado": N, "erro_envio": M, ...}.
        """
        with self._connect() as conn:
            rows = conn.execute(_RESUMO, (lote_id,)).fetchall()
        return {r["status"]: r["total"] for r in rows}
 
 
__all__ = ["EnvioLoteAuditStore"]

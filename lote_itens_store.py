"""
lote_itens_store.py — Persistência do conjunto aprovado (PostgreSQL).

Persiste o conjunto exato de lançamentos sendáveis aprovados para um lote.

Motivação:
  APROVAÇÃO → salvar_itens(lote_id, itens)
  ENVIO     → carregar_itens(lote_id)

  Nenhum caminho fora desse ciclo pode injetar itens no fluxo de envio.

Chamadores:
  - aprovacao_lote.aprovar_lote()  → salvar_itens
  - envio_lote.enviar_lote()       → carregar_itens
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Optional

from db import get_connection


_UPSERT = """
INSERT INTO lote_itens (lote_id, itens_json, total_itens, hash_itens, criado_em, atualizado_em)
VALUES (
    %(lote_id)s, %(itens_json)s, %(total_itens)s, %(hash_itens)s,
    COALESCE(
        (SELECT criado_em FROM lote_itens WHERE lote_id = %(lote_id)s),
        to_char(now() AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"')
    ),
    to_char(now() AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"')
)
ON CONFLICT (lote_id) DO UPDATE SET
    itens_json    = EXCLUDED.itens_json,
    total_itens   = EXCLUDED.total_itens,
    hash_itens    = EXCLUDED.hash_itens,
    atualizado_em = EXCLUDED.atualizado_em;
"""

_SELECT = "SELECT itens_json, hash_itens FROM lote_itens WHERE lote_id = %s;"
_EXISTS = "SELECT 1 FROM lote_itens WHERE lote_id = %s LIMIT 1;"


def _json_dumps_canonico(obj: Any) -> str:
    """Serialização determinística. sort_keys garante hash estável."""
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, default=str)


def _hash_itens(itens_json: str) -> str:
    return hashlib.sha256(itens_json.encode("utf-8")).hexdigest()


class LoteItensStore:
    """
    Gerenciador de persistência do conjunto canônico de itens sendáveis aprovados.

    Uso típico:
        store = LoteItensStore()
        store.salvar_itens(lote_id, itens)
        itens = store.carregar_itens(lote_id)
    """

    def __init__(self, db_path: Any = None) -> None:
        # db_path mantido na assinatura para compatibilidade com callers
        # legados, mas ignorado — a conexão é gerenciada por db.get_connection().
        pass

    def salvar_itens(self, lote_id: str, itens: list[dict[str, Any]]) -> None:
        """Persiste o conjunto de lançamentos sendáveis. Idempotente."""
        itens_json = _json_dumps_canonico(itens)
        params = {
            "lote_id":     lote_id,
            "itens_json":  itens_json,
            "total_itens": len(itens),
            "hash_itens":  _hash_itens(itens_json),
        }
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(_UPSERT, params)

    def carregar_itens(self, lote_id: str) -> Optional[list[dict[str, Any]]]:
        """Reconstrói a lista de lançamentos sendáveis. Retorna None se não existe."""
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(_SELECT, (lote_id,))
                row = cur.fetchone()
        if row is None:
            return None
        return json.loads(row["itens_json"])

    def existe(self, lote_id: str) -> bool:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(_EXISTS, (lote_id,))
                row = cur.fetchone()
        return row is not None

    def verificar_integridade(self, lote_id: str) -> bool:
        """Verifica integridade via hash SHA-256."""
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(_SELECT, (lote_id,))
                row = cur.fetchone()
        if row is None:
            return False
        return _hash_itens(row["itens_json"]) == row["hash_itens"]


__all__ = ["LoteItensStore"]

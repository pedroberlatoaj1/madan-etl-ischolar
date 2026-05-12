"""
envio_lote_audit_store.py — Persistência de auditoria por item (PostgreSQL).

UNIQUE key: (lote_id, item_key) — identidade forte.
item_key vem de ResultadoItemEnvio.item_key, calculado em envio_lote._compute_item_key().
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, Optional

from db import get_connection

if TYPE_CHECKING:
    from envio_lote import ResultadoItemEnvio


_UPSERT = """
INSERT INTO envio_lote_audit (
    lote_id, item_key,
    estudante, componente, disciplina, trimestre,
    valor_bruta, id_matricula, id_disciplina, id_avaliacao, id_professor,
    dry_run, status, mensagem, transitorio,
    payload_enviado, resposta_api, erros_resolucao, rastreabilidade,
    timestamp, criado_em, atualizado_em
) VALUES (
    %(lote_id)s, %(item_key)s,
    %(estudante)s, %(componente)s, %(disciplina)s, %(trimestre)s,
    %(valor_bruta)s, %(id_matricula)s, %(id_disciplina)s, %(id_avaliacao)s, %(id_professor)s,
    %(dry_run)s, %(status)s, %(mensagem)s, %(transitorio)s,
    %(payload_enviado)s, %(resposta_api)s, %(erros_resolucao)s, %(rastreabilidade)s,
    %(timestamp)s,
    COALESCE(
        (SELECT criado_em FROM envio_lote_audit
         WHERE lote_id = %(lote_id)s AND item_key = %(item_key)s),
        to_char(now() AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"')
    ),
    to_char(now() AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"')
)
ON CONFLICT (lote_id, item_key) DO UPDATE SET
    estudante        = EXCLUDED.estudante,
    componente       = EXCLUDED.componente,
    disciplina       = EXCLUDED.disciplina,
    trimestre        = EXCLUDED.trimestre,
    valor_bruta      = EXCLUDED.valor_bruta,
    id_matricula     = EXCLUDED.id_matricula,
    id_disciplina    = EXCLUDED.id_disciplina,
    id_avaliacao     = EXCLUDED.id_avaliacao,
    id_professor     = EXCLUDED.id_professor,
    dry_run          = EXCLUDED.dry_run,
    status           = EXCLUDED.status,
    mensagem         = EXCLUDED.mensagem,
    transitorio      = EXCLUDED.transitorio,
    payload_enviado  = EXCLUDED.payload_enviado,
    resposta_api     = EXCLUDED.resposta_api,
    erros_resolucao  = EXCLUDED.erros_resolucao,
    rastreabilidade  = EXCLUDED.rastreabilidade,
    timestamp        = EXCLUDED.timestamp,
    atualizado_em    = EXCLUDED.atualizado_em;
"""

_SELECT_LOTE = "SELECT * FROM envio_lote_audit WHERE lote_id = %s ORDER BY id;"

_RESUMO = """
SELECT status, COUNT(*) AS total
FROM envio_lote_audit
WHERE lote_id = %s
GROUP BY status;
"""


def _json_dumps(obj: Any) -> Optional[str]:
    if obj is None:
        return None
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, default=str)


class EnvioLoteAuditStore:
    """Persistência PostgreSQL de ResultadoItemEnvio com UNIQUE (lote_id, item_key)."""

    def __init__(self, db_path: Any = None) -> None:
        pass

    def salvar_item(self, item: "ResultadoItemEnvio") -> None:
        """Persiste (insert ou update) um ResultadoItemEnvio. Idempotente."""
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
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(_UPSERT, params)

    def listar_itens(self, lote_id: str) -> list[dict[str, Any]]:
        """Retorna todos os itens de auditoria de um lote como lista de dicts."""
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(_SELECT_LOTE, (lote_id,))
                rows = cur.fetchall()
        return [dict(r) for r in rows]

    def resumo_lote(self, lote_id: str) -> dict[str, int]:
        """Retorna contagens por status: {'enviado': N, 'erro_envio': M, ...}."""
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(_RESUMO, (lote_id,))
                rows = cur.fetchall()
        return {r["status"]: r["total"] for r in rows}


__all__ = ["EnvioLoteAuditStore"]

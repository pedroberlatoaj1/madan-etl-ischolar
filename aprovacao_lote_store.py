"""
aprovacao_lote_store.py — Persistência do estado de aprovação (PostgreSQL).

Responsabilidades:
  - salvar(estado)    : insert ou update do estado completo
  - carregar(lote_id) : reconstrói EstadoAprovacaoLote a partir do banco
  - listar_ids()      : lista todos os lote_id conhecidos
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, Optional

from db import get_connection

if TYPE_CHECKING:
    from aprovacao_lote import EstadoAprovacaoLote


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
    %(lote_id)s, %(status)s, %(elegivel)s,
    %(resumo_atual_json)s,
    %(aprovado_por)s, %(aprovador_nome_informado)s, %(aprovador_email)s,
    %(aprovador_origem)s, %(aprovador_identity_strength)s, %(aprovado_em)s,
    %(rejeitado_por)s, %(rejeitado_em)s, %(motivo_rejeicao)s,
    %(snapshot_json)s, %(hash_resumo_aprovado)s,
    COALESCE(
        (SELECT criado_em FROM aprovacoes_lote WHERE lote_id = %(lote_id)s),
        to_char(now() AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"')
    ),
    to_char(now() AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"')
)
ON CONFLICT (lote_id) DO UPDATE SET
    status                      = EXCLUDED.status,
    elegivel_para_aprovacao     = EXCLUDED.elegivel_para_aprovacao,
    resumo_atual                = EXCLUDED.resumo_atual,
    aprovado_por                = EXCLUDED.aprovado_por,
    aprovador_nome_informado    = EXCLUDED.aprovador_nome_informado,
    aprovador_email             = EXCLUDED.aprovador_email,
    aprovador_origem            = EXCLUDED.aprovador_origem,
    aprovador_identity_strength = EXCLUDED.aprovador_identity_strength,
    aprovado_em                 = EXCLUDED.aprovado_em,
    rejeitado_por               = EXCLUDED.rejeitado_por,
    rejeitado_em                = EXCLUDED.rejeitado_em,
    motivo_rejeicao             = EXCLUDED.motivo_rejeicao,
    snapshot_resumo_aprovado    = EXCLUDED.snapshot_resumo_aprovado,
    hash_resumo_aprovado        = EXCLUDED.hash_resumo_aprovado,
    atualizado_em               = EXCLUDED.atualizado_em;
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
WHERE lote_id = %s;
"""

_LIST = "SELECT lote_id FROM aprovacoes_lote ORDER BY atualizado_em DESC LIMIT %s;"


def _json_dumps(obj: object) -> str:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, default=str)


class AprovacaoLoteStore:
    """Persistência PostgreSQL do estado de aprovação por lote."""

    def __init__(self, db_path: Any = None) -> None:
        # db_path mantido por compatibilidade; ignorado em PostgreSQL.
        pass

    def salvar(self, estado: "EstadoAprovacaoLote") -> None:
        """Persiste (insert ou update) o estado completo do lote. Idempotente."""
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
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(_UPSERT, params)

    def carregar(self, lote_id: str) -> Optional["EstadoAprovacaoLote"]:
        """Reconstrói EstadoAprovacaoLote a partir do banco. Retorna None se não existe."""
        from aprovacao_lote import EstadoAprovacaoLote  # noqa: PLC0415

        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(_SELECT, (lote_id,))
                row = cur.fetchone()

        if row is None:
            return None

        resumo_atual = json.loads(row["resumo_atual"])
        snap_raw = row["snapshot_resumo_aprovado"]
        snapshot = json.loads(snap_raw) if snap_raw is not None else None

        return EstadoAprovacaoLote(
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

    def listar_ids(self, limit: int = 1000) -> list[str]:
        """Retorna lote_ids ordenados por atualização mais recente."""
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(_LIST, (limit,))
                rows = cur.fetchall()
        return [r["lote_id"] for r in rows]


__all__ = ["AprovacaoLoteStore"]

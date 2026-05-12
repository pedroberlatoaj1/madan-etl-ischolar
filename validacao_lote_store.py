"""
validacao_lote_store.py — Persistência do resultado de validação (PostgreSQL).

Guarda o snapshot oficial validado antes da aprovação humana, permitindo:
- aprovação assíncrona sem rerodar a validação
- detecção de snapshot stale por hash
- reaproveitamento do pipeline oficial pelo worker e pelo CLI
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Optional

from db import get_connection


_UPSERT = """
INSERT INTO validacoes_lote (
    lote_id, job_id, snapshot_hash, status,
    resumo, avisos, erros, pendencias,
    apto_para_aprovacao, resultados_validacao, itens_sendaveis,
    versao, expires_at, created_at, updated_at
) VALUES (
    %(lote_id)s, %(job_id)s, %(snapshot_hash)s, %(status)s,
    %(resumo)s, %(avisos)s, %(erros)s, %(pendencias)s,
    %(apto_para_aprovacao)s, %(resultados_validacao)s, %(itens_sendaveis)s,
    %(versao)s, %(expires_at)s,
    COALESCE(
        (SELECT created_at FROM validacoes_lote WHERE lote_id = %(lote_id)s),
        to_char(now() AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"')
    ),
    to_char(now() AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"')
)
ON CONFLICT (lote_id) DO UPDATE SET
    job_id               = EXCLUDED.job_id,
    snapshot_hash        = EXCLUDED.snapshot_hash,
    status               = EXCLUDED.status,
    resumo               = EXCLUDED.resumo,
    avisos               = EXCLUDED.avisos,
    erros                = EXCLUDED.erros,
    pendencias           = EXCLUDED.pendencias,
    apto_para_aprovacao  = EXCLUDED.apto_para_aprovacao,
    resultados_validacao = EXCLUDED.resultados_validacao,
    itens_sendaveis      = EXCLUDED.itens_sendaveis,
    versao               = EXCLUDED.versao,
    expires_at           = EXCLUDED.expires_at,
    updated_at           = EXCLUDED.updated_at;
"""

_SELECT = """
SELECT
    lote_id, job_id, snapshot_hash, status,
    resumo, avisos, erros, pendencias,
    apto_para_aprovacao, resultados_validacao, itens_sendaveis,
    versao, expires_at, created_at, updated_at
FROM validacoes_lote
WHERE lote_id = %s;
"""

_LIST = "SELECT lote_id FROM validacoes_lote ORDER BY updated_at DESC LIMIT %s;"


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
    """Persistência PostgreSQL do resultado oficial de validação por lote."""

    def __init__(self, db_path: Any = None) -> None:
        # db_path mantido por compatibilidade; ignorado em PostgreSQL.
        pass

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
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(_UPSERT, params)
        salvo = self.carregar(resultado.lote_id)
        if salvo is None:
            raise RuntimeError(f"Falha ao recarregar validacao do lote '{resultado.lote_id}'.")
        return salvo

    def carregar(self, lote_id: str) -> Optional[ResultadoValidacaoPersistido]:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(_SELECT, (lote_id,))
                row = cur.fetchone()
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
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(_LIST, (limit,))
                rows = cur.fetchall()
        return [r["lote_id"] for r in rows]


__all__ = ["ResultadoValidacaoPersistido", "ValidacaoLoteStore"]

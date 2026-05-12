"""
resultado_envio_lote_store.py — Persistência do resultado consolidado (PostgreSQL).

Mantém o estado agregado da fase assíncrona de aprovação/envio.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Optional

from db import get_connection


_UPSERT = """
INSERT INTO resultados_envio_lote (
    lote_id, job_id, snapshot_hash, status, aprovado_por,
    aprovador_nome_informado, aprovador_email, aprovador_origem,
    aprovador_identity_strength, sucesso,
    quantidade_enviada, quantidade_com_erro, total_sendaveis, total_dry_run,
    total_erros_resolucao, total_erros_envio, mensagem,
    resumo, auditoria_resumo, finished_at, created_at, updated_at
) VALUES (
    %(lote_id)s, %(job_id)s, %(snapshot_hash)s, %(status)s, %(aprovado_por)s,
    %(aprovador_nome_informado)s, %(aprovador_email)s, %(aprovador_origem)s,
    %(aprovador_identity_strength)s, %(sucesso)s,
    %(quantidade_enviada)s, %(quantidade_com_erro)s, %(total_sendaveis)s, %(total_dry_run)s,
    %(total_erros_resolucao)s, %(total_erros_envio)s, %(mensagem)s,
    %(resumo)s, %(auditoria_resumo)s, %(finished_at)s,
    COALESCE(
        (SELECT created_at FROM resultados_envio_lote WHERE lote_id = %(lote_id)s),
        to_char(now() AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"')
    ),
    to_char(now() AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"')
)
ON CONFLICT (lote_id) DO UPDATE SET
    job_id                      = EXCLUDED.job_id,
    snapshot_hash               = EXCLUDED.snapshot_hash,
    status                      = EXCLUDED.status,
    aprovado_por                = EXCLUDED.aprovado_por,
    aprovador_nome_informado    = EXCLUDED.aprovador_nome_informado,
    aprovador_email             = EXCLUDED.aprovador_email,
    aprovador_origem            = EXCLUDED.aprovador_origem,
    aprovador_identity_strength = EXCLUDED.aprovador_identity_strength,
    sucesso                     = EXCLUDED.sucesso,
    quantidade_enviada          = EXCLUDED.quantidade_enviada,
    quantidade_com_erro         = EXCLUDED.quantidade_com_erro,
    total_sendaveis             = EXCLUDED.total_sendaveis,
    total_dry_run               = EXCLUDED.total_dry_run,
    total_erros_resolucao       = EXCLUDED.total_erros_resolucao,
    total_erros_envio           = EXCLUDED.total_erros_envio,
    mensagem                    = EXCLUDED.mensagem,
    resumo                      = EXCLUDED.resumo,
    auditoria_resumo            = EXCLUDED.auditoria_resumo,
    finished_at                 = EXCLUDED.finished_at,
    updated_at                  = EXCLUDED.updated_at;
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
WHERE lote_id = %s;
"""

_LIST = "SELECT lote_id FROM resultados_envio_lote ORDER BY updated_at DESC LIMIT %s;"


def _json_dumps(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, default=str)


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
    """Persistência PostgreSQL do resultado agregado de envio."""

    def __init__(self, db_path: Any = None) -> None:
        pass

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
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(_UPSERT, params)
        salvo = self.carregar(resultado.lote_id)
        if salvo is None:
            raise RuntimeError(
                f"Falha ao recarregar resultado de envio do lote '{resultado.lote_id}'."
            )
        return salvo

    def carregar(self, lote_id: str) -> Optional[ResultadoEnvioPersistido]:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(_SELECT, (lote_id,))
                row = cur.fetchone()
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
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(_LIST, (limit,))
                rows = cur.fetchall()
        return [r["lote_id"] for r in rows]


__all__ = ["ResultadoEnvioPersistido", "ResultadoEnvioLoteStore"]

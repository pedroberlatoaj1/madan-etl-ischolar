"""
snapshot_store.py — Persistência de snapshots no Cloudflare R2.

Migrado de filesystem local para Cloudflare R2 (S3-compatible).
A assinatura pública das funções foi mantida para não quebrar callers
em webhook_google_sheets.py e worker.py.

Contrato do envelope JSON:
  {
    "job_id": int,
    "source_type": str,
    "source_identifier": str,
    "spreadsheet_id": str | null,
    "sheet_name": str | null,
    "received_at": str (ISO 8601 UTC),
    "content_hash": str,
    "total_records": int,
    "records": [ { col: val, ... }, ... ]
  }
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import pandas as pd

from logger import configurar_logger
from storage_r2 import upload_snapshot as r2_upload, download_snapshot as r2_download

log = configurar_logger("etl.snapshot_store")


@dataclass
class SnapshotMetadata:
    """Metadados do envelope de snapshot."""
    job_id: int
    source_type: str
    source_identifier: str
    spreadsheet_id: Optional[str]
    sheet_name: Optional[str]
    received_at: str
    content_hash: str
    total_records: int


# ---------------------------------------------------------------------------
# Escrita
# ---------------------------------------------------------------------------

def save_snapshot(
    job_id: int,
    records: List[Dict[str, Any]],
    *,
    source_type: str = "google_sheets",
    source_identifier: str = "",
    spreadsheet_id: Optional[str] = None,
    sheet_name: Optional[str] = None,
    content_hash: str = "",
) -> str:
    """
    Persiste snapshot com envelope de metadados no Cloudflare R2.

    Returns:
        Chave do objeto no R2 (ex: 'snapshots/42.json').
    """
    received_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()

    envelope: Dict[str, Any] = {
        "job_id": job_id,
        "source_type": source_type,
        "source_identifier": source_identifier,
        "spreadsheet_id": spreadsheet_id,
        "sheet_name": sheet_name,
        "received_at": received_at,
        "content_hash": content_hash,
        "total_records": len(records),
        "records": records,
    }

    key = r2_upload(job_id, envelope)

    log.info(
        "📸 Snapshot salvo | job_id=%s | records=%d | r2_key=%s",
        job_id, len(records), key,
    )
    return key


# ---------------------------------------------------------------------------
# Leitura
# ---------------------------------------------------------------------------

def _validar_envelope(data: dict, job_id: int) -> None:
    campos_obrigatorios = ["job_id", "source_type", "source_identifier", "received_at"]
    faltando = [c for c in campos_obrigatorios if c not in data]
    if faltando:
        raise ValueError(
            f"Snapshot job_id={job_id}: campos obrigatórios ausentes: {faltando}"
        )

    payload_job_id = data.get("job_id")
    if payload_job_id is not None:
        try:
            if int(payload_job_id) != job_id:
                raise ValueError(
                    f"Snapshot job_id={job_id}: job_id no payload ({payload_job_id}) não confere"
                )
        except (TypeError, ValueError) as e:
            raise ValueError(f"Snapshot job_id={job_id}: job_id inválido: {e}") from e

    records = data.get("records")
    if not isinstance(records, list):
        raise ValueError(
            f"Snapshot job_id={job_id}: 'records' deve ser lista, recebido {type(records).__name__}"
        )

    total_records = data.get("total_records")
    if total_records is not None:
        expected = int(total_records)
        actual = len(records)
        if expected != actual:
            raise ValueError(
                f"Snapshot job_id={job_id}: total_records ({expected}) não confere com len(records) ({actual})"
            )


def load_snapshot(job_id: int) -> tuple[SnapshotMetadata, List[Dict[str, Any]]]:
    """
    Carrega snapshot do Cloudflare R2.

    Returns:
        Tupla (metadados, lista de registros).

    Raises:
        FileNotFoundError: se o snapshot não existir no R2.
        ValueError: se o formato do envelope for inválido.
    """
    data = r2_download(job_id)
    if data is None:
        raise FileNotFoundError(
            f"Snapshot não encontrado no R2 para job {job_id}"
        )

    if isinstance(data, dict) and "records" in data:
        _validar_envelope(data, job_id)
        meta = SnapshotMetadata(
            job_id=data.get("job_id", job_id),
            source_type=data.get("source_type", "google_sheets"),
            source_identifier=data.get("source_identifier", ""),
            spreadsheet_id=data.get("spreadsheet_id"),
            sheet_name=data.get("sheet_name"),
            received_at=data.get("received_at", ""),
            content_hash=data.get("content_hash", ""),
            total_records=data.get("total_records", len(data["records"])),
        )
        return meta, data["records"]

    if isinstance(data, list):
        log.info("📦 Snapshot job_id=%s em formato legado. Convertendo.", job_id)
        meta = SnapshotMetadata(
            job_id=job_id,
            source_type="google_sheets",
            source_identifier="",
            spreadsheet_id=None,
            sheet_name=None,
            received_at="",
            content_hash="",
            total_records=len(data),
        )
        return meta, data

    raise ValueError(
        f"Formato de snapshot inválido para job {job_id}: tipo={type(data).__name__}"
    )


def load_snapshot_records(job_id: int) -> pd.DataFrame:
    """Conveniência: carrega snapshot e retorna os registros como DataFrame."""
    _meta, records = load_snapshot(job_id)
    if not records:
        return pd.DataFrame()
    return pd.DataFrame(records)


# ---------------------------------------------------------------------------
# Limpeza (no-op — gerenciada pelo lifecycle rule do R2)
# ---------------------------------------------------------------------------

def cleanup_old_snapshots(retention_days: Optional[int] = None) -> int:
    """
    No-op: limpeza gerenciada automaticamente pelo lifecycle rule do bucket R2
    (objetos com prefixo 'snapshots/' deletados após 7 dias).
    """
    log.debug("cleanup_old_snapshots: gerenciado pelo lifecycle rule do R2.")
    return 0


__all__ = [
    "SnapshotMetadata",
    "save_snapshot",
    "load_snapshot",
    "load_snapshot_records",
    "cleanup_old_snapshots",
]

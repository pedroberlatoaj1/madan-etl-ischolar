"""
snapshot_store.py — Persistência de snapshots de payloads do Google Sheets.

O webhook salva o payload recebido como snapshot JSON com envelope de
metadados. Escrita atômica: temp file → flush/fsync → rename, para
evitar snapshot corrompido ou parcial em caso de falha no meio da escrita.
O worker carrega esse snapshot para transformar e enviar ao iScholar.
Após N dias, snapshots antigos podem ser removidos.

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

Compatibilidade: load_snapshot() detecta o formato antigo (lista pura
de dicts, sem envelope) e o converte automaticamente.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd

from config import config
from logger import configurar_logger

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
# Paths
# ---------------------------------------------------------------------------

def _ensure_dir() -> Path:
    """Garante existência do diretório de snapshots e retorna o Path."""
    path = Path(config.SNAPSHOTS_DIR)
    path.mkdir(parents=True, exist_ok=True)
    return path


def snapshot_path(job_id: int) -> Path:
    """Caminho canônico do arquivo de snapshot para um job_id."""
    return _ensure_dir() / f"{job_id}.json"


def _snapshot_temp_path(job_id: int) -> Path:
    """Caminho do arquivo temporário para escrita atômica (mesmo diretório)."""
    return _ensure_dir() / f"{job_id}.json.tmp"


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
) -> Path:
    """
    Persiste snapshot com envelope de metadados.

    Args:
        job_id: ID do job associado.
        records: Lista de dicts (linhas da planilha).
        source_type: Tipo de origem (ex.: "google_sheets").
        source_identifier: Identificador lógico (ex.: "spreadsheet_id/sheet_name").
        spreadsheet_id: ID da planilha Google (opcional).
        sheet_name: Nome da aba (opcional).
        content_hash: Hash SHA-256 do conteúdo para rastreio.

    Returns:
        Path do arquivo salvo.
    """
    received_at = (
        datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    )

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

    path = snapshot_path(job_id)
    tmp_path = _snapshot_temp_path(job_id)
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(envelope, f, ensure_ascii=False, indent=None)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp_path, path)

    log.info(
        "📸 Snapshot salvo | job_id=%s | records=%d | path=%s",
        job_id,
        len(records),
        path,
    )
    return path


# ---------------------------------------------------------------------------
# Leitura
# ---------------------------------------------------------------------------

def _validar_envelope(data: dict, job_id: int) -> None:
    """
    Valida envelope de snapshot. Levanta ValueError com mensagem clara em inconsistência.
    Não aplicado a formato legado (lista pura).
    """
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
                    f"Snapshot job_id={job_id}: job_id no payload ({payload_job_id}) não confere com arquivo"
                )
        except (TypeError, ValueError) as e:
            raise ValueError(
                f"Snapshot job_id={job_id}: job_id no payload inválido: {e}"
            ) from e

    records = data.get("records")
    if not isinstance(records, list):
        raise ValueError(
            f"Snapshot job_id={job_id}: 'records' deve ser lista, recebido {type(records).__name__}"
        )

    total_records = data.get("total_records")
    if total_records is not None:
        try:
            expected = int(total_records)
        except (TypeError, ValueError):
            raise ValueError(
                f"Snapshot job_id={job_id}: total_records inválido ({total_records})"
            ) from None
        actual = len(records)
        if expected != actual:
            log.error(
                "Snapshot job_id=%s: total_records=%d não confere com len(records)=%d",
                job_id, expected, actual,
            )
            raise ValueError(
                f"Snapshot job_id={job_id}: total_records ({expected}) não confere com len(records) ({actual})"
            )


def load_snapshot(job_id: int) -> tuple[SnapshotMetadata, List[Dict[str, Any]]]:
    """
    Carrega snapshot do disco.

    Compatibilidade: se o arquivo for uma lista JSON pura (formato
    antigo, pré-snapshot_store), retorna metadados com valores default.
    Para envelope com metadados, valida records, total_records, job_id e campos obrigatórios.

    Returns:
        Tupla (metadados, lista de registros).

    Raises:
        FileNotFoundError: se o snapshot não existir.
        ValueError: se o formato do arquivo for inválido ou inconsistente.
    """
    path = snapshot_path(job_id)
    if not path.is_file():
        raise FileNotFoundError(
            f"Snapshot não encontrado para job {job_id}: {path}"
        )

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

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
        log.info(
            "📦 Snapshot job_id=%s em formato legado (lista pura). Convertendo.",
            job_id,
        )
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
        f"Formato de snapshot inválido para job {job_id}: "
        f"tipo={type(data).__name__}"
    )


def load_snapshot_records(job_id: int) -> pd.DataFrame:
    """
    Conveniência: carrega snapshot e retorna os registros como DataFrame.

    Raises:
        FileNotFoundError: se o snapshot não existir.
    """
    _meta, records = load_snapshot(job_id)
    if not records:
        return pd.DataFrame()
    return pd.DataFrame(records)


# ---------------------------------------------------------------------------
# Limpeza
# ---------------------------------------------------------------------------

def cleanup_old_snapshots(retention_days: Optional[int] = None) -> int:
    """
    Remove snapshots mais antigos que retention_days (pelo mtime do arquivo).

    Args:
        retention_days: Dias de retenção. Se None, usa
            config.SNAPSHOT_RETENTION_DAYS (padrão 7).

    Returns:
        Quantidade de arquivos removidos.
    """
    if retention_days is None:
        retention_days = getattr(config, "SNAPSHOT_RETENTION_DAYS", 7)

    base = Path(config.SNAPSHOTS_DIR)
    if not base.is_dir():
        return 0

    cutoff = time.time() - (retention_days * 86400)
    removidos = 0

    for arq in base.glob("*.json"):
        try:
            if arq.stat().st_mtime < cutoff:
                arq.unlink()
                removidos += 1
                log.debug("🗑️ Snapshot removido: %s", arq.name)
        except OSError as exc:
            log.warning("⚠️ Falha ao remover snapshot %s: %s", arq.name, exc)

    if removidos:
        log.info(
            "🧹 Limpeza de snapshots: %d arquivo(s) removido(s) (retenção=%d dias).",
            removidos,
            retention_days,
        )
    return removidos


__all__ = [
    "SnapshotMetadata",
    "snapshot_path",
    "save_snapshot",
    "load_snapshot",
    "load_snapshot_records",
    "cleanup_old_snapshots",
]

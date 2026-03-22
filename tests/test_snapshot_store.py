"""Testes do contrato de snapshots do Google Sheets."""

import json
import os
import time

from snapshot_store import (
    SnapshotMetadata,
    cleanup_old_snapshots,
    load_snapshot,
    load_snapshot_records,
    save_snapshot,
    snapshot_path,
)

SAMPLE_RECORDS = [
    {"estudante": "ANA", "disciplina": "MAT", "nota": "8,5"},
    {"estudante": "BOB", "disciplina": "FIS", "nota": "7,0"},
]


# ── save + load ────────────────────────────────────────────────────────────


class TestSaveLoad:
    def test_save_cria_arquivo(self):
        path = save_snapshot(job_id=1, records=SAMPLE_RECORDS)

        assert path.is_file()

    def test_load_retorna_metadados_e_records(self):
        save_snapshot(
            job_id=10,
            records=SAMPLE_RECORDS,
            source_type="google_sheets",
            source_identifier="abc/Notas",
            spreadsheet_id="abc",
            sheet_name="Notas",
            content_hash="deadbeef",
        )

        meta, records = load_snapshot(10)

        assert isinstance(meta, SnapshotMetadata)
        assert meta.job_id == 10
        assert meta.spreadsheet_id == "abc"
        assert meta.sheet_name == "Notas"
        assert meta.content_hash == "deadbeef"
        assert meta.total_records == 2
        assert len(records) == 2
        assert records[0]["estudante"] == "ANA"

    def test_received_at_preenchido(self):
        save_snapshot(job_id=11, records=SAMPLE_RECORDS)

        meta, _ = load_snapshot(11)

        assert meta.received_at != ""
        assert "T" in meta.received_at

    def test_load_snapshot_records_retorna_dataframe(self):
        save_snapshot(job_id=12, records=SAMPLE_RECORDS)

        df = load_snapshot_records(12)

        assert len(df) == 2
        assert "estudante" in df.columns


# ── formato legado ─────────────────────────────────────────────────────────


class TestFormatoLegado:
    def test_lista_pura_carrega_com_fallback(self):
        path = snapshot_path(77)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(SAMPLE_RECORDS, f)

        meta, records = load_snapshot(77)

        assert meta.job_id == 77
        assert meta.spreadsheet_id is None
        assert len(records) == 2

    def test_formato_invalido_levanta_erro(self):
        path = snapshot_path(88)
        with open(path, "w", encoding="utf-8") as f:
            json.dump("string solta", f)

        import pytest

        with pytest.raises(ValueError, match="Formato de snapshot inválido"):
            load_snapshot(88)


# ── snapshot não encontrado ────────────────────────────────────────────────


class TestSnapshotNaoEncontrado:
    def test_load_levanta_file_not_found(self):
        import pytest

        with pytest.raises(FileNotFoundError):
            load_snapshot(999999)


# ── cleanup ────────────────────────────────────────────────────────────────


class TestCleanup:
    def test_remove_snapshots_antigos(self):
        save_snapshot(job_id=20, records=SAMPLE_RECORDS)
        save_snapshot(job_id=21, records=SAMPLE_RECORDS)

        p20 = snapshot_path(20)
        p21 = snapshot_path(21)
        old_time = time.time() - (10 * 86400)
        os.utime(p20, (old_time, old_time))

        removed = cleanup_old_snapshots(retention_days=7)

        assert removed == 1
        assert not p20.is_file()
        assert p21.is_file()

    def test_cleanup_com_diretorio_inexistente(self):
        from config import config

        config.SNAPSHOTS_DIR = "/path/que/nao/existe/xyz"

        removed = cleanup_old_snapshots(retention_days=1)

        assert removed == 0

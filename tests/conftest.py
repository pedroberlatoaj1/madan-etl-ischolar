"""
conftest.py — Fixtures compartilhadas para isolar testes do ambiente real.

Cada teste recebe um banco SQLite e diretório de snapshots temporários
via tmp_path, sem tocar no banco/pasta de produção.
"""

import pytest

from config import config
import job_store as _job_store_mod


@pytest.fixture(autouse=True)
def _isolate_config(tmp_path):
    """Redireciona JOB_DB_PATH e SNAPSHOTS_DIR para diretórios temporários."""
    db_path = str(tmp_path / "test_jobs.sqlite3")
    snap_dir = str(tmp_path / "snapshots")

    original_db = config.JOB_DB_PATH
    original_snap = config.SNAPSHOTS_DIR

    config.JOB_DB_PATH = db_path
    config.SNAPSHOTS_DIR = snap_dir

    _job_store_mod._INITIALIZED = False

    yield

    config.JOB_DB_PATH = original_db
    config.SNAPSHOTS_DIR = original_snap
    _job_store_mod._INITIALIZED = False

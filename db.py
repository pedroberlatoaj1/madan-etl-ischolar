"""
db.py — Conexão centralizada com PostgreSQL (Railway).

Substitui os padrões sqlite3.connect() espalhados nos *_store.py.
Lê DATABASE_URL da variável de ambiente (injetada automaticamente pelo Railway
quando o serviço PostgreSQL está linkado ao projeto).

Uso:
    from db import get_connection

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1")
            row = cur.fetchone()
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Generator

import psycopg2
import psycopg2.extras


# ---------------------------------------------------------------------------
# URL de conexão
# ---------------------------------------------------------------------------

def _database_url() -> str:
    url = os.getenv("DATABASE_URL", "")
    if not url:
        raise RuntimeError(
            "DATABASE_URL não definida. "
            "Configure a variável de ambiente antes de iniciar o serviço.\n"
            "Exemplo local: DATABASE_URL=postgresql://user:pass@localhost/madan_dev"
        )
    return url


# ---------------------------------------------------------------------------
# Context manager de conexão
# ---------------------------------------------------------------------------

@contextmanager
def get_connection() -> Generator[psycopg2.extensions.connection, None, None]:
    """
    Retorna uma conexão PostgreSQL como context manager.

    Faz commit automático ao sair sem exceção; rollback em caso de erro.

    Uso:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("INSERT INTO ...")
    """
    conn = psycopg2.connect(
        _database_url(),
        cursor_factory=psycopg2.extras.RealDictCursor,
    )
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Inicialização do schema (executada no boot de cada serviço)
# ---------------------------------------------------------------------------

def init_schema() -> None:
    """
    Aplica o schema.sql no banco, criando tabelas e índices se não existirem.
    Idempotente: usa CREATE TABLE IF NOT EXISTS.
    """
    schema_path = os.path.join(os.path.dirname(__file__), "schema.sql")
    with open(schema_path, encoding="utf-8") as f:
        sql = f.read()

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql)

    print("[db] Schema inicializado com sucesso.")

"""
hash_utils.py — Funções de hashing SHA-256 para idempotência do pipeline.

Fornece:
- sha256_file: hash de um arquivo no disco (leitura em blocos)
- sha256_bytes: hash de bytes arbitrários
- sha256_dataframe_normalizado: hash determinístico de um DataFrame pandas
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import List, Optional

import pandas as pd


def sha256_bytes(data: bytes) -> str:
    """Retorna o SHA-256 hex de um bloco de bytes."""
    return hashlib.sha256(data).hexdigest()


def sha256_file(caminho: str, bloco: int = 65536) -> str:
    """
    Calcula SHA-256 de um arquivo lendo em blocos.

    Args:
        caminho: Caminho do arquivo.
        bloco: Tamanho do bloco de leitura em bytes (padrão 64 KB).

    Raises:
        FileNotFoundError: Se o arquivo não existir.
    """
    path = Path(caminho)
    if not path.is_file():
        raise FileNotFoundError(f"Arquivo não encontrado: {caminho}")

    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(bloco)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def sha256_dataframe_normalizado(
    df: pd.DataFrame,
    sort_by_columns: Optional[List[str]] = None,
) -> str:
    """
    Gera um hash SHA-256 determinístico de um DataFrame.

    Para garantir determinismo independente da ordem das linhas,
    o DataFrame é opcionalmente ordenado pelas colunas indicadas
    antes de serializar para CSV em memória.

    Args:
        df: DataFrame a ser hashado.
        sort_by_columns: Colunas usadas para ordenar antes do hash.
            Colunas ausentes no DataFrame são ignoradas silenciosamente.
    """
    df_work = df.copy()

    if sort_by_columns:
        colunas_presentes = [c for c in sort_by_columns if c in df_work.columns]
        if colunas_presentes:
            df_work = df_work.sort_values(by=colunas_presentes, ignore_index=True)

    csv_bytes = df_work.to_csv(index=False).encode("utf-8")
    return hashlib.sha256(csv_bytes).hexdigest()


__all__ = [
    "sha256_bytes",
    "sha256_file",
    "sha256_dataframe_normalizado",
]

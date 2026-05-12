"""
storage_r2.py — Cliente Cloudflare R2 para armazenamento de snapshots.

Cloudflare R2 é S3-compatible. Usamos boto3 apontando para o endpoint R2.

Variáveis de ambiente necessárias:
    R2_ACCOUNT_ID         — Cloudflare Account ID
    R2_ACCESS_KEY_ID      — R2 API Token Access Key ID
    R2_SECRET_ACCESS_KEY  — R2 API Token Secret Access Key
    R2_BUCKET_NAME        — Nome do bucket (ex: madan-etl-snapshots)

Uso:
    from storage_r2 import upload_snapshot, download_snapshot

    upload_snapshot(job_id=42, envelope={...})
    envelope = download_snapshot(job_id=42)
"""

from __future__ import annotations

import json
import os
from typing import Any

import boto3
from botocore.exceptions import ClientError


# ---------------------------------------------------------------------------
# Configuração do cliente R2
# ---------------------------------------------------------------------------

def _r2_client():
    account_id = os.environ["R2_ACCOUNT_ID"]
    return boto3.client(
        "s3",
        endpoint_url=f"https://{account_id}.r2.cloudflarestorage.com",
        aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"],
        region_name="auto",
    )


def _bucket() -> str:
    return os.environ.get("R2_BUCKET_NAME", "madan-etl-snapshots")


def _key(job_id: int) -> str:
    return f"snapshots/{job_id}.json"


# ---------------------------------------------------------------------------
# Operações públicas
# ---------------------------------------------------------------------------

def upload_snapshot(job_id: int, envelope: dict[str, Any]) -> str:
    """
    Faz upload do envelope JSON para o R2.
    Retorna a chave do objeto (ex: 'snapshots/42.json').
    """
    key = _key(job_id)
    body = json.dumps(envelope, ensure_ascii=False).encode("utf-8")
    _r2_client().put_object(
        Bucket=_bucket(),
        Key=key,
        Body=body,
        ContentType="application/json",
    )
    return key


def download_snapshot(job_id: int) -> dict[str, Any] | None:
    """
    Baixa e desserializa o envelope JSON do R2.
    Retorna None se o objeto não existir.
    """
    key = _key(job_id)
    try:
        response = _r2_client().get_object(Bucket=_bucket(), Key=key)
        body = response["Body"].read()
        return json.loads(body.decode("utf-8"))
    except ClientError as e:
        if e.response["Error"]["Code"] in ("NoSuchKey", "404"):
            return None
        raise


def delete_snapshot(job_id: int) -> bool:
    """
    Remove o snapshot do R2.
    Retorna True se foi deletado, False se não existia.
    """
    key = _key(job_id)
    try:
        _r2_client().delete_object(Bucket=_bucket(), Key=key)
        return True
    except ClientError:
        return False


def list_snapshots() -> list[str]:
    """
    Lista todas as chaves de snapshots no bucket.
    """
    response = _r2_client().list_objects_v2(
        Bucket=_bucket(),
        Prefix="snapshots/",
    )
    contents = response.get("Contents", [])
    return [obj["Key"] for obj in contents]

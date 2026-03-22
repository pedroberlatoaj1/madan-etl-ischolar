"""
config.py — Configurações centralizadas do pipeline ETL iScholar
"""

import os
from dataclasses import dataclass, field
from typing import List


@dataclass
class Config:
    # --- Pasta monitorada ---
    PASTA_NOTAS: str = os.getenv("PASTA_NOTAS", "/notas_pedagogico")
    EXTENSOES_SUPORTADAS: List[str] = field(
        default_factory=lambda: [".csv", ".xlsx", ".xls"]
    )

    # --- Debounce: espera N segundos após o último evento antes de processar ---
    DEBOUNCE_SEGUNDOS: float = 5.0

    # --- Estabilidade de arquivo: tamanho e mtime devem permanecer iguais ---
    FILE_STABILITY_CHECK_INTERVAL: float = float(
        os.getenv("FILE_STABILITY_CHECK_INTERVAL", "1.0")
    )  # segundos entre cada verificação
    FILE_STABILITY_REQUIRED_CHECKS: int = int(
        os.getenv("FILE_STABILITY_REQUIRED_CHECKS", "3")
    )  # verificações consecutivas estáveis para considerar pronto

    # --- API iScholar ---
    ISCHOLAR_BASE_URL: str = os.getenv("ISCHOLAR_BASE_URL", "https://api.ischolar.app")
    # Lê o token novo, mas faz fallback automático para o antigo ISCHOLAR_API_KEY
    ISCHOLAR_API_TOKEN: str = os.getenv("ISCHOLAR_API_TOKEN", os.getenv("ISCHOLAR_API_KEY", ""))
    ISCHOLAR_CODIGO_ESCOLA: str = os.getenv("ISCHOLAR_CODIGO_ESCOLA", "")
    ISCHOLAR_API_KEY: str = ISCHOLAR_API_TOKEN  # Alias de compatibilidade para código legado
    ISCHOLAR_TIMEOUT_SEGUNDOS: int = int(os.getenv("ISCHOLAR_TIMEOUT_SEGUNDOS", "30"))
    ISCHOLAR_MAX_RETRIES: int = int(os.getenv("ISCHOLAR_MAX_RETRIES", "3"))

    # --- Transformador: parser de colunas ---
    COLUNAS_OBRIGATORIAS: List[str] = field(
        default_factory=lambda: [
            "estudante",
            "disciplina",
            "turma",
        ]
    )
    NOTA_MINIMA: float = 0.0
    NOTA_MAXIMA: float = 10.0

    # --- Regras de negócio de aprovação ---
    MEDIA_APROVACAO: float = 6.0
    MEDIA_RECUPERACAO: float = 4.0

    # --- Job Store: idempotência ---
    # Política de deduplicação: "content_only" ou "content_and_source"
    IDEMPOTENCY_MODE: str = os.getenv("IDEMPOTENCY_MODE", "content_and_source")

    # --- Transformador: inferência e deduplicação (conservador por padrão) ---
    # Recalcular nota_final quando ausente (nota_com_a_av_3 ou média). Preferir dado do pedagógico.
    RECALCULAR_NOTA_FINAL: bool = os.getenv("RECALCULAR_NOTA_FINAL", "false").lower() in ("1", "true", "yes")
    # Se True, remove duplicatas pela chave abaixo (keep='last'). Se False, apenas loga possíveis duplicatas.
    DEDUPLICAR_REGISTROS: bool = os.getenv("DEDUPLICAR_REGISTROS", "false").lower() in ("1", "true", "yes")
    # Chave de negócio para deduplicação: estudante + disciplina + turma + trimestre evita colapsar registros legítimos.
    CHAVE_DEDUPLICACAO: List[str] = field(
        default_factory=lambda: ["estudante", "disciplina", "turma", "trimestre"]
    )

    # --- Worker: recuperação de jobs stale ---
    PROCESSING_STALE_SECONDS: int = 300  # 5 minutos
    STALE_MAX_RETRIES: int = int(os.getenv("STALE_MAX_RETRIES", "3"))

    # --- Caminhos de dados e log ---
    JOB_DB_PATH: str = os.getenv("JOB_DB_PATH", "jobs.sqlite3")
    SNAPSHOTS_DIR: str = os.getenv("SNAPSHOTS_DIR", "snapshots")
    LOG_FILE: str = os.getenv("LOG_FILE", "etl_ischolar.log")
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")


config = Config()
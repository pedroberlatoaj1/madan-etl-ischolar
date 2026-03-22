"""
logger.py — Configuração centralizada de logging com saída no terminal e em arquivo.
"""

import logging
import sys
from logging.handlers import RotatingFileHandler
from config import config


def configurar_logger(nome: str = "etl_ischolar") -> logging.Logger:
    """
    Retorna um logger configurado com:
      - StreamHandler → terminal (colorido com nível)
      - RotatingFileHandler → arquivo etl_ischolar.log (máx 5MB, 3 backups)
    """
    logger = logging.getLogger(nome)

    # Evita duplicação ao chamar múltiplas vezes
    if logger.handlers:
        return logger

    nivel = getattr(logging, config.LOG_LEVEL.upper(), logging.INFO)
    logger.setLevel(nivel)

    fmt = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # --- Terminal ---
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    sh.setLevel(nivel)
    logger.addHandler(sh)

    # --- Arquivo rotacionado ---
    fh = RotatingFileHandler(
        filename=config.LOG_FILE,
        maxBytes=5 * 1024 * 1024,  # 5 MB
        backupCount=3,
        encoding="utf-8",
    )
    fh.setFormatter(fmt)
    fh.setLevel(nivel)
    logger.addHandler(fh)

    return logger

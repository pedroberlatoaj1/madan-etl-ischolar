"""
logger.py — Configuração centralizada de logging.

Output exclusivamente em stdout (capturado automaticamente pelo Railway).
FileHandler removido: filesystem do Railway é efêmero, logs em arquivo seriam perdidos.
"""

import logging
import sys
from config import config


def configurar_logger(nome: str = "etl_ischolar") -> logging.Logger:
    """
    Retorna um logger configurado com StreamHandler → stdout.
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

    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    sh.setLevel(nivel)
    logger.addHandler(sh)

    return logger

class JobStatus:
    """Valores de status do job (persistidos no SQLite)."""

    PENDING = "pending"
    PROCESSING = "processing"
    SUCCESS = "success"
    ERROR = "error"
    SKIPPED = "skipped"


class ErrorType:
    """Tipos de erro de job (persistidos no SQLite)."""

    TRANSIENT = "transient"
    PERMANENT = "permanent"
    EXHAUSTED = "exhausted"
    STALE_EXHAUSTED = "stale_exhausted"


__all__ = ["JobStatus", "ErrorType"]


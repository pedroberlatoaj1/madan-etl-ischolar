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


class JobType:
    """Tipos logicos de job aceitos pelo worker."""

    LEGACY_SYNC = "legacy_sync"
    GOOGLE_SHEETS_VALIDATION = "google_sheets_validation"
    APPROVAL_AND_SEND = "approval_and_send"


__all__ = ["JobStatus", "ErrorType", "JobType"]

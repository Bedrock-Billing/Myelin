from __future__ import annotations

from myelin.batch.options import (
    BatchBackend,
    BatchOptions,
    OnError,
)
from myelin.batch.result import (
    BatchResult,
    BatchStats,
    classify_error,
    extract_per_pricer_totals,
    extract_total_payment,
)

__all__ = [
    "BatchBackend",
    "BatchOptions",
    "OnError",
    "BatchResult",
    "BatchStats",
    "classify_error",
    "extract_per_pricer_totals",
    "extract_total_payment",
]


def _rebuild_after_core_imports() -> None:
    try:
        from myelin.core import MyelinIO  # noqa: F401

        BatchResult.model_rebuild(force=True)
    except Exception:
        pass


_rebuild_after_core_imports()


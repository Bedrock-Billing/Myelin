from __future__ import annotations

import os
import sys
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class BatchBackend(str, Enum):
    THREAD = "threads"
    PROCESS = "processes"


class OnError(str, Enum):
    CONTINUE = "continue"
    FAIL_FAST = "fail_fast"


def _env_max_workers() -> int | None:
    raw = os.environ.get("MYELIN_BATCH_MAX_WORKERS")
    if not raw:
        return None
    try:
        value = int(raw)
    except ValueError:
        return None
    if value < 1:
        return None
    return value


def _default_max_workers(backend: BatchBackend) -> int:
    override = _env_max_workers()
    if override is not None:
        return override
    cpu = os.cpu_count() or 1
    if backend is BatchBackend.PROCESS:
        return min(cpu, 4)
    return min(cpu, 2)


def _default_progress() -> bool:
    try:
        return sys.stderr.isatty()
    except (AttributeError, ValueError):
        return False


class BatchOptions(BaseModel):
    """Options controlling batch execution behavior."""

    model_config = ConfigDict(extra="forbid", use_enum_values=False)

    max_workers: int | None = None
    backend: BatchBackend = BatchBackend.THREAD
    on_error: OnError = OnError.CONTINUE
    progress: bool | None = None
    preserve_order: bool = True
    chunk_size: int = Field(default=500, ge=1)

    def resolved_max_workers(self) -> int:
        if self.max_workers is None:
            return _default_max_workers(self.backend)
        if self.max_workers < 1:
            raise ValueError("max_workers must be >= 1")
        return self.max_workers

    def resolved_progress(self) -> bool:
        if self.progress is None:
            return _default_progress()
        return self.progress

    def to_kwargs(self) -> dict[str, object]:
        return {
            "max_workers": self.resolved_max_workers(),
            "backend": self.backend,
            "on_error": self.on_error,
            "progress": self.resolved_progress(),
            "preserve_order": self.preserve_order,
            "chunk_size": self.chunk_size,
        }


__all__ = [
    "BatchBackend",
    "OnError",
    "BatchOptions",
]

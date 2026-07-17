from __future__ import annotations

from types import TracebackType
from typing import Protocol


class _ProgressLike(Protocol):
    def update(self, n: int = 1) -> None: ...
    def close(self) -> None: ...


class NoOpProgress:
    def update(self, n: int = 1) -> None:
        return None

    def close(self) -> None:
        return None

    def __enter__(self) -> "NoOpProgress":
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        return None


class TqdmProgress:
    def __init__(self, total: int, desc: str = "Processing claims", unit: str = "claim"):
        from tqdm import tqdm

        self._bar = tqdm(total=total, desc=desc, unit=unit)

    def update(self, n: int = 1) -> None:
        self._bar.update(n)

    def close(self) -> None:
        self._bar.close()

    def __enter__(self) -> "TqdmProgress":
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        self.close()


def make_progress(enabled: bool, total: int) -> _ProgressLike:
    if enabled:
        return TqdmProgress(total=total)
    return NoOpProgress()


__all__ = ["NoOpProgress", "TqdmProgress", "make_progress"]

from __future__ import annotations

import pytest

from myelin.batch import BatchBackend, BatchOptions, OnError


def test_batch_options_defaults():
    opts = BatchOptions()
    assert opts.max_workers is None
    assert opts.backend is BatchBackend.THREAD
    assert opts.on_error is OnError.CONTINUE
    assert opts.progress is None
    assert opts.preserve_order is True
    assert opts.chunk_size == 500


def test_batch_options_resolve_max_workers_threads():
    opts = BatchOptions(backend=BatchBackend.THREAD)
    resolved = opts.resolved_max_workers()
    assert resolved >= 1


def test_batch_options_resolve_max_workers_process():
    import os

    opts = BatchOptions(backend=BatchBackend.PROCESS)
    resolved = opts.resolved_max_workers()
    assert resolved >= 1
    assert resolved == min(os.cpu_count() or 1, 4)


def test_batch_options_resolve_max_workers_explicit():
    opts = BatchOptions(max_workers=7)
    assert opts.resolved_max_workers() == 7


def test_batch_options_max_workers_invalid():
    opts = BatchOptions(max_workers=0)
    with pytest.raises(ValueError):
        opts.resolved_max_workers()


def test_batch_options_resolve_progress_explicit_true():
    opts = BatchOptions(progress=True)
    assert opts.resolved_progress() is True


def test_batch_options_resolve_progress_explicit_false():
    opts = BatchOptions(progress=False)
    assert opts.resolved_progress() is False


def test_batch_options_resolve_progress_auto():
    opts = BatchOptions()
    resolved = opts.resolved_progress()
    assert isinstance(resolved, bool)


def test_batch_options_extra_forbid():
    with pytest.raises(Exception):
        BatchOptions(unknown_field=42)


def test_batch_options_to_kwargs():
    opts = BatchOptions(max_workers=4, backend=BatchBackend.PROCESS)
    kw = opts.to_kwargs()
    assert kw["max_workers"] == 4
    assert kw["backend"] is BatchBackend.PROCESS


def test_batch_options_chunk_size_validation():
    with pytest.raises(Exception):
        BatchOptions(chunk_size=0)


def test_batch_backend_enum_values():
    assert BatchBackend.THREAD.value == "threads"
    assert BatchBackend.PROCESS.value == "processes"


def test_on_error_enum_values():
    assert OnError.CONTINUE.value == "continue"
    assert OnError.FAIL_FAST.value == "fail_fast"

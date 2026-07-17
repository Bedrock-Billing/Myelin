from __future__ import annotations

from myelin.batch.progress import NoOpProgress, TqdmProgress, make_progress


def test_noop_progress_update_does_nothing():
    p = NoOpProgress()
    assert p.update(5) is None
    assert p.update() is None
    p.close()
    with p as ctx:
        assert ctx is p


def test_make_progress_disabled_returns_noop():
    p = make_progress(enabled=False, total=10)
    assert isinstance(p, NoOpProgress)
    p.update(5)
    p.close()


def test_make_progress_enabled_returns_tqdm():
    p = make_progress(enabled=True, total=10)
    assert isinstance(p, TqdmProgress)
    p.update(5)
    p.close()


def test_tqdm_progress_context_manager():
    with make_progress(enabled=True, total=2) as p:
        assert isinstance(p, TqdmProgress)
        p.update(1)
        p.update(1)

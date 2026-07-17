"""Auto-mark tests as slow when they use fixtures that spin up a real Myelin.

This keeps `pytest` fast for unit testing and `pytest -m 'not slow'`
(skip-mark the JVM integration tests) for quick CI smoke runs. Full
integration tests run with `pytest` (no marker filter) or
`pytest -m slow`.
"""
from __future__ import annotations

import pytest


_SLOW_FIXTURES = frozenset(
    {
        "mock_myelin",
        "fast_myelin",
        "myelin_or_skip",
    }
)


def pytest_collection_modifyitems(config, items):
    marker = pytest.mark.slow
    for item in items:
        if any(fixture in _SLOW_FIXTURES for fixture in getattr(item, "fixturenames", ())):
            item.add_marker(marker)

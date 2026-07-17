from __future__ import annotations

import pytest

from myelin.batch.worker import (
    _init_worker,
    process_chunk,
    process_one,
    worker_process_claim,
)
from myelin.core import MyelinIO
from myelin.input import Claim, DiagnosisCode, PoaType, Provider


@pytest.fixture(autouse=True)
def reset_worker_global(monkeypatch):
    import myelin.batch.worker as w

    monkeypatch.setattr(w, "_WORKER_MYELIN", None)
    yield
    monkeypatch.setattr(w, "_WORKER_MYELIN", None)


def _test_claim() -> Claim:
    c = Claim()
    c.claimid = "WORKER_TEST_001"
    c.principal_dx = DiagnosisCode(code="A021", poa=PoaType.Y)
    c.billing_provider = Provider()
    c.billing_provider.other_id = "010001"
    return c


def test_init_worker_creates_myelin_instance(monkeypatch):
    import myelin.batch.worker as w

    called = {"count": 0}

    def fake_init(self, **kwargs):
        called["count"] += 1

    monkeypatch.setattr(w.Myelin, "__init__", fake_init)
    monkeypatch.setattr(w.Myelin, "setup_clients", lambda self: None)

    _init_worker(jar_path="./jars", db_path="./data/myelin.db", build_db=False)
    assert called["count"] == 1
    assert w._WORKER_MYELIN is not None


def test_init_worker_is_idempotent(monkeypatch):
    import myelin.batch.worker as w

    called = {"count": 0}

    def fake_init(self, **kwargs):
        called["count"] += 1

    monkeypatch.setattr(w.Myelin, "__init__", fake_init)
    monkeypatch.setattr(w.Myelin, "setup_clients", lambda self: None)

    _init_worker(jar_path="./jars", db_path="./data/myelin.db", build_db=False)
    _init_worker(jar_path="./jars", db_path="./data/myelin.db", build_db=False)
    _init_worker(jar_path="./jars", db_path="./data/myelin.db", build_db=False)
    assert called["count"] == 1


def test_process_one_returns_myoel_io(monkeypatch):
    import myelin.batch.worker as w

    output = type("FakeOut", (), {"model_dump": lambda self: {}})()
    fake_myelin = type(
        "FakeMyelin",
        (),
        {"process": lambda self, claim: MyelinIO(input=claim, output=output)},
    )()
    monkeypatch.setattr(w, "_WORKER_MYELIN", fake_myelin)
    c = _test_claim()
    mio = process_one((c, "./jars", "./data/myelin.db", False))
    assert isinstance(mio, MyelinIO)
    assert mio.input is c


def test_process_one_catches_exception(monkeypatch):
    import myelin.batch.worker as w

    def boom(self, claim):
        raise RuntimeError("kaboom")

    fake_myelin = type("FakeMyelin", (), {"process": boom})()
    monkeypatch.setattr(w, "_WORKER_MYELIN", fake_myelin)
    c = _test_claim()
    mio = process_one((c, "./jars", "./data/myelin.db", False))
    assert mio.input is c
    assert mio.output is not None
    assert "RuntimeError" in (mio.output.error or "")


def test_process_chunk_processes_all(monkeypatch):
    import myelin.batch.worker as w

    fake_myelin = type(
        "FakeMyelin",
        (),
        {"process": lambda self, claim: MyelinIO(input=claim, output=type("O", (), {})())},
    )()
    monkeypatch.setattr(w, "_WORKER_MYELIN", fake_myelin)
    claims = [_test_claim() for _ in range(5)]
    results = process_chunk((claims, "./jars", "./data/myelin.db", False))
    assert len(results) == 5
    for mio, claim in zip(results, claims):
        assert mio.input is claim


def test_worker_process_claim_uses_env(monkeypatch):
    import myelin.batch.worker as w

    monkeypatch.setenv("MYELIN_JAR_PATH", "/custom/jars")
    monkeypatch.setenv("MYELIN_DB_PATH", "/custom/data/myelin.db")
    monkeypatch.setenv("MYELIN_BUILD_DB", "1")

    captured = {}

    def fake_init(jar_path, db_path, build_db):
        captured["jar_path"] = jar_path
        captured["db_path"] = db_path
        captured["build_db"] = build_db
        w._WORKER_MYELIN = type(
            "FakeMyelin",
            (),
            {"process": lambda self, claim: MyelinIO(input=claim, output=type("O", (), {})())},
        )()

    monkeypatch.setattr(w, "_init_worker", fake_init)

    claim = _test_claim()
    mio = worker_process_claim(claim)
    assert captured["jar_path"] == "/custom/jars"
    assert captured["db_path"] == "/custom/data/myelin.db"
    assert captured["build_db"] is True
    assert mio.input is claim

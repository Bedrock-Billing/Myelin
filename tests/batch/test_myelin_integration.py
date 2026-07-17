from __future__ import annotations

from datetime import datetime

import pytest

from myelin import BatchOptions, Myelin
from myelin.batch.result import BatchResult
from myelin.core import MyelinIO, MyelinOutput
from myelin.helpers.claim_examples import claim_example


@pytest.fixture
def mock_myelin(monkeypatch):
    """Return a Myelin instance with Myelin.process replaced by a mock that
    returns a deterministic MyelinOutput based on claimid."""
    myelin = Myelin(build_jar_dirs=False, jar_path="./jars", db_path="./data/myelin.db")
    myelin.setup_clients_called = False

    def fake_process(self, claim, **kwargs):
        from myelin.pricers.opps import OppsOutput

        output = MyelinOutput(opps=OppsOutput(total_claim_payment=42.0))
        if claim.claimid.startswith("FAIL"):
            output.error = "simulated failure"
        return output

    monkeypatch.setattr(Myelin, "process", fake_process)
    return myelin


def test_process_batch_returns_batch_result(mock_myelin):
    claims = [claim_example() for _ in range(3)]
    result = mock_myelin.process_batch(claims, BatchOptions(progress=False))
    assert isinstance(result, BatchResult)
    assert result.stats.total_count == 3
    assert result.stats.success_count == 3
    assert result.stats.failure_count == 0
    assert len(result.items) == 3


def test_process_batch_preserves_order(mock_myelin):
    claims = []
    for i in range(5):
        c = claim_example()
        c.claimid = f"CLAIM_{i:03d}"
        claims.append(c)
    result = mock_myelin.process_batch(claims, BatchOptions(progress=False))
    for i, mio in enumerate(result.items):
        assert mio.input.claimid == f"CLAIM_{i:03d}"


def test_process_batch_records_failures(mock_myelin):
    claims = []
    for i in range(3):
        c = claim_example()
        c.claimid = "FAIL_CLAIM" if i == 1 else f"OK_{i}"
        claims.append(c)
    result = mock_myelin.process_batch(claims, BatchOptions(progress=False))
    assert result.stats.success_count == 2
    assert result.stats.failure_count == 1
    failed = result.failed()
    assert len(failed) == 1
    assert failed[0].input.claimid == "FAIL_CLAIM"


def test_process_batch_default_uses_threads(mock_myelin):
    claims = [claim_example() for _ in range(2)]
    result = mock_myelin.process_batch(claims, BatchOptions(progress=False))
    assert result.options.backend.value == "threads"


def test_process_batch_default_max_workers_set(mock_myelin):
    claims = [claim_example() for _ in range(1)]
    result = mock_myelin.process_batch(claims, BatchOptions(progress=False))
    assert result.options.resolved_max_workers() >= 1


def test_process_batch_computes_per_pricer_totals(mock_myelin):
    claims = [claim_example() for _ in range(3)]
    result = mock_myelin.process_batch(claims, BatchOptions(progress=False))
    assert "opps" in result.stats.per_pricer_total_payment
    assert result.stats.per_pricer_total_payment["opps"] == pytest.approx(42.0 * 3)


def test_process_batch_computes_throughput(mock_myelin):
    claims = [claim_example() for _ in range(3)]
    result = mock_myelin.process_batch(claims, BatchOptions(progress=False))
    assert result.stats.claims_per_second >= 0


def test_process_stream_yields_myoel_io(mock_myelin):
    claims = [claim_example() for _ in range(3)]
    opts = BatchOptions(progress=False, preserve_order=False)
    mios = list(mock_myelin.process_stream(claims, opts))
    assert len(mios) == 3
    for mio in mios:
        assert isinstance(mio, MyelinIO)


def test_process_in_order_yields_in_submission_order(mock_myelin):
    claims = []
    for i in range(5):
        c = claim_example()
        c.claimid = f"ORDER_{i:03d}"
        claims.append(c)
    opts = BatchOptions(progress=False, preserve_order=True)
    mios = list(mock_myelin.process_in_order(claims, opts))
    assert len(mios) == 5
    for i, mio in enumerate(mios):
        assert mio.input.claimid == f"ORDER_{i:03d}"


def test_process_in_order_preserves_order_even_if_stream_doesnt(mock_myelin):
    claims = []
    for i in range(5):
        c = claim_example()
        c.claimid = f"INORDER_{i:03d}"
        claims.append(c)
    opts = BatchOptions(progress=False, preserve_order=True)
    mios = list(mock_myelin.process_in_order(claims, opts))
    for i, mio in enumerate(mios):
        assert mio.input.claimid == f"INORDER_{i:03d}"


def test_process_batch_max_workers_invalid():
    opts = BatchOptions(max_workers=0, progress=False)
    with pytest.raises(ValueError):
        opts.resolved_max_workers()


def test_process_batch_handles_validation_error(monkeypatch):
    myelin = Myelin(build_jar_dirs=False, jar_path="./jars", db_path="./data/myelin.db")
    c = claim_example()
    c.cond_codes = [123]
    c.from_date = datetime(2030, 1, 1)
    c.thru_date = datetime(2025, 1, 1)
    result = myelin.process_batch([c], BatchOptions(progress=False))
    assert result.stats.total_count == 1
    assert result.stats.skipped_count == 1
    assert result.stats.failure_count == 0
    assert result.items[0].output.error is not None
    assert "ValidationError" in result.items[0].output.error


def test_process_batch_continues_on_per_claim_failure(mock_myelin):
    claims = []
    for i in range(3):
        c = claim_example()
        c.claimid = "FAIL_X" if i == 1 else f"OK_{i}"
        claims.append(c)
    result = mock_myelin.process_batch(claims, BatchOptions(progress=False))
    assert result.stats.failure_count == 1
    assert result.stats.success_count == 2

from __future__ import annotations

from datetime import datetime

from myelin.batch.executor import (
    _to_mio,
    _should_fail_fast,
    _validate,
    _record_mio,
    finalize_stats,
)
from myelin.batch.options import BatchOptions, OnError
from myelin.batch.result import BatchStats
from myelin.core import MyelinIO, MyelinOutput
from myelin.helpers.utils import ProviderDataError
from myelin.input import Claim, DiagnosisCode, PoaType, Provider


def _good_claim() -> Claim:
    c = Claim()
    c.claimid = "TEST_001"
    c.principal_dx = DiagnosisCode(code="A021", poa=PoaType.Y)
    c.billing_provider = Provider()
    c.billing_provider.other_id = "010001"
    return c


def test_to_mio_wraps_exception():
    c = _good_claim()
    mio = _to_mio(c, ValueError("nope"))
    assert mio.input is c
    assert mio.output is not None
    assert "ValueError" in (mio.output.error or "")
    assert "nope" in (mio.output.error or "")


def test_should_fail_fast_continue():
    opts = BatchOptions(on_error=OnError.CONTINUE)
    assert _should_fail_fast(opts, ValueError("x")) is False


def test_should_fail_fast_fail_fast_value_error():
    opts = BatchOptions(on_error=OnError.FAIL_FAST)
    assert _should_fail_fast(opts, ValueError("x")) is True


def test_should_fail_fast_fail_fast_keyboard_interrupt():
    opts = BatchOptions(on_error=OnError.FAIL_FAST)
    assert _should_fail_fast(opts, KeyboardInterrupt()) is False


def test_should_fail_fast_fail_fast_provider_data_error():
    opts = BatchOptions(on_error=OnError.FAIL_FAST)
    err = ProviderDataError(
        code="P0001",
        description="x",
        explanation="y",
    )
    assert _should_fail_fast(opts, err) is True


def test_validate_good_claim_returns_claim():
    c = _good_claim()
    result = _validate(c)
    assert isinstance(result, Claim)


def test_validate_invalid_claim_returns_mio_with_error():
    c = Claim()
    c.principal_dx = DiagnosisCode(code="A021", poa=PoaType.Y)
    c.cond_codes = [123]
    c.from_date = datetime(2030, 1, 1)
    c.thru_date = datetime(2025, 1, 1)
    result = _validate(c)
    assert isinstance(result, MyelinIO)
    assert "ValidationError" in (result.output.error or "")


def test_record_mio_success():
    mio = MyelinIO(input=_good_claim(), output=MyelinOutput())
    stats = BatchStats()
    _record_mio(mio, stats)
    assert stats.success_count == 1
    assert stats.failure_count == 0
    assert stats.error_histogram == {}


def test_record_mio_failure_records_error_in_histogram():
    mio = MyelinIO(input=_good_claim(), output=MyelinOutput(error="BOOM"))
    stats = BatchStats()
    _record_mio(mio, stats)
    assert stats.success_count == 0
    assert stats.failure_count == 1
    assert stats.error_histogram.get("BOOM") == 1


def test_record_mio_failure_increments_histogram():
    mio1 = MyelinIO(input=_good_claim(), output=MyelinOutput(error="SAME"))
    mio2 = MyelinIO(input=_good_claim(), output=MyelinOutput(error="SAME"))
    stats = BatchStats()
    _record_mio(mio1, stats)
    _record_mio(mio2, stats)
    assert stats.error_histogram.get("SAME") == 2


def test_finalize_stats_computes_throughput_and_totals():
    from myelin.pricers.ipps import IppsOutput

    items = [
        MyelinIO(
            input=_good_claim(),
            output=MyelinOutput(ipps=IppsOutput(total_payment=100.0)),
        ),
        MyelinIO(
            input=_good_claim(),
            output=MyelinOutput(ipps=IppsOutput(total_payment=200.0)),
        ),
    ]
    stats = BatchStats(total_count=2)
    finalize_stats(items, stats, elapsed=1.0, started_at=datetime.now(), finished_at=datetime.now())
    assert stats.total_payment == 300.0
    assert stats.per_pricer_total_payment.get("ipps") == 300.0
    assert stats.claims_per_second == 2.0
    assert stats.elapsed_seconds == 1.0


def test_finalize_stats_zero_elapsed_yields_zero_throughput():
    items = [MyelinIO(input=_good_claim(), output=MyelinOutput())]
    stats = BatchStats(total_count=1)
    finalize_stats(items, stats, elapsed=0.0, started_at=datetime.now(), finished_at=datetime.now())
    assert stats.claims_per_second == 0.0

from __future__ import annotations

from pathlib import Path

import pytest

from myelin.batch.options import BatchOptions
from myelin.batch.result import (
    BatchResult,
    BatchStats,
    classify_error,
    extract_per_pricer_totals,
    extract_total_payment,
)
from myelin.core import MyelinIO, MyelinOutput
from myelin.input import Claim
from myelin.pricers.fqhc import FqhcOutput
from myelin.pricers.ipps import IppsOutput
from myelin.pricers.opps import OppsOutput


def _empty_mio(claim: Claim | None = None, error: str | None = None) -> MyelinIO:
    return MyelinIO(input=claim, output=MyelinOutput(error=error))


def _ipps_mio(payment: float = 100.0) -> MyelinIO:
    out = MyelinOutput(ipps=IppsOutput(total_payment=payment))
    return MyelinIO(input=Claim(), output=out)


def _opps_mio(payment: float = 50.0) -> MyelinIO:
    out = MyelinOutput(opps=OppsOutput(total_claim_payment=payment))
    return MyelinIO(input=Claim(), output=out)


def _fqhc_mio(payment: float = 25.0) -> MyelinIO:
    out = MyelinOutput(fqhc=FqhcOutput(total_payment=payment))
    return MyelinIO(input=Claim(), output=out)


def test_classify_error_none_output():
    assert classify_error(None) == "MyelinOutput is None"


def test_classify_error_with_error_string():
    out = MyelinOutput(error="something failed")
    assert classify_error(out) == "something failed"


def test_classify_error_clean_output():
    out = MyelinOutput()
    assert classify_error(out) is None


def test_extract_total_payment_none():
    assert extract_total_payment(None) == 0.0


def test_extract_total_payment_empty():
    assert extract_total_payment(MyelinOutput()) == 0.0


def test_extract_total_payment_ipps():
    mio = _ipps_mio(123.45)
    assert extract_total_payment(mio.output) == 123.45


def test_extract_total_payment_opps_uses_claim_total():
    mio = _opps_mio(67.89)
    assert extract_total_payment(mio.output) == 67.89


def test_extract_total_payment_sums_multiple_pricers():
    out = MyelinOutput(
        ipps=IppsOutput(total_payment=100.0),
        opps=OppsOutput(total_claim_payment=50.0),
        fqhc=FqhcOutput(total_payment=25.0),
    )
    mio = MyelinIO(input=Claim(), output=out)
    assert extract_total_payment(mio.output) == 175.0


def test_extract_total_payment_skips_none_pricer_output():
    out = MyelinOutput(ipps=IppsOutput(total_payment=None))
    mio = MyelinIO(input=Claim(), output=out)
    assert extract_total_payment(mio.output) == 0.0


def test_extract_per_pricer_totals():
    out = MyelinOutput(
        ipps=IppsOutput(total_payment=100.0),
        opps=OppsOutput(total_claim_payment=50.0),
    )
    mio = MyelinIO(input=Claim(), output=out)
    totals = extract_per_pricer_totals(mio.output)
    assert totals == {"ipps": 100.0, "opps": 50.0}


def test_extract_per_pricer_totals_none():
    assert extract_per_pricer_totals(None) == {}


def test_batch_stats_defaults():
    stats = BatchStats()
    assert stats.total_count == 0
    assert stats.success_count == 0
    assert stats.failure_count == 0
    assert stats.skipped_count == 0
    assert stats.elapsed_seconds == 0.0
    assert stats.claims_per_second == 0.0
    assert stats.total_payment == 0.0
    assert stats.per_pricer_total_payment == {}
    assert stats.error_histogram == {}


def test_batch_result_succeeded_and_failed():
    mio_ok = _ipps_mio(10.0)
    mio_err = _empty_mio(error="boom")
    result = BatchResult(items=[mio_ok, mio_err], stats=BatchStats())
    assert len(result.succeeded()) == 1
    assert len(result.failed()) == 1
    assert result.succeeded()[0] is mio_ok
    assert result.failed()[0] is mio_err


def test_batch_result_to_jsonl(tmp_path: Path):
    mio_ok = _ipps_mio(10.0)
    mio_err = _empty_mio(error="boom")
    result = BatchResult(items=[mio_ok, mio_err], stats=BatchStats())
    path = tmp_path / "out.jsonl"
    result.to_jsonl(str(path))
    lines = path.read_text().strip().split("\n")
    assert len(lines) == 2
    assert "input" in lines[0]
    assert "output" in lines[0]


def test_batch_result_to_jsonl_bytes_empty():
    result = BatchResult(items=[], stats=BatchStats())
    assert result.to_jsonl_bytes() == b""


def test_batch_result_to_jsonl_bytes_nonempty():
    mio_ok = _ipps_mio(10.0)
    result = BatchResult(items=[mio_ok], stats=BatchStats())
    data = result.to_jsonl_bytes()
    assert b"input" in data
    assert b"output" in data


def test_batch_result_options_field():
    opts = BatchOptions(max_workers=3)
    result = BatchResult(items=[], stats=BatchStats(), options=opts)
    assert result.options is opts


def test_batch_result_extra_forbid():
    with pytest.raises(Exception):
        BatchResult(items=[], stats=BatchStats(), garbage="nope")


def test_batch_stats_extra_forbid():
    with pytest.raises(Exception):
        BatchStats(unknown_field=1)

from __future__ import annotations

import json
from pathlib import Path

import pytest

from myelin import BatchOptions, Myelin
from myelin.batch.jsonl import (
    iter_claims_from_jsonl,
    mio_to_dict,
    read_claim_line,
    write_mio_line,
)
from myelin.batch.result import BatchStats
from myelin.core import MyelinIO, MyelinOutput
from myelin.input import Claim


def _good_claim_dict(claimid: str = "TEST_001") -> dict:
    return {
        "claimid": claimid,
        "principal_dx": {"code": "A021", "poa": "Y"},
        "patient": {"age": 65, "sex": "M"},
        "from_date": "2025-07-01T00:00:00",
        "thru_date": "2025-07-10T00:00:00",
        "admit_date": "2025-07-01T00:00:00",
        "patient_status": "01",
        "los": 9,
        "billing_provider": {"other_id": "010001"},
    }


def _write_jsonl(path: Path, lines: list[dict | str]) -> None:
    with path.open("w", encoding="utf-8") as f:
        for line in lines:
            if isinstance(line, str):
                f.write(line + "\n")
            else:
                f.write(json.dumps(line) + "\n")


def _read_jsonl(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def test_write_mio_line_writes_one_jsonl_line():
    from io import StringIO

    mio = MyelinIO(input=Claim(), output=MyelinOutput(error="boom"))
    buf = StringIO()
    write_mio_line(mio, buf)
    line = buf.getvalue().rstrip("\n")
    record = json.loads(line)
    assert "input" in record
    assert "output" in record
    assert record["output"]["error"] == "boom"


def test_mio_to_dict_includes_input_and_output():
    mio = MyelinIO.model_construct(input=Claim(), output=MyelinOutput(error="x"))
    record = mio_to_dict(mio)
    assert "input" in record
    assert "output" in record
    assert record["output"]["error"] == "x"


def test_read_claim_line_parses_dict():
    line = json.dumps({"input": _good_claim_dict()})
    claim = read_claim_line(line)
    assert claim.claimid == "TEST_001"


def test_read_claim_line_parses_bare_dict():
    line = json.dumps(_good_claim_dict())
    claim = read_claim_line(line)
    assert claim.claimid == "TEST_001"


def test_iter_claims_from_jsonl_yields_claims(tmp_path: Path):
    in_path = tmp_path / "in.jsonl"
    _write_jsonl(in_path, [_good_claim_dict("C1"), _good_claim_dict("C2")])
    items = list(iter_claims_from_jsonl(in_path))
    assert len(items) == 2
    assert all(isinstance(item, Claim) for item in items)
    assert [c.claimid for c in items] == ["C1", "C2"]


def test_iter_claims_skips_blank_lines(tmp_path: Path):
    in_path = tmp_path / "in.jsonl"
    _write_jsonl(
        in_path,
        [
            _good_claim_dict("C1"),
            "",
            "   ",
            _good_claim_dict("C2"),
        ],
    )
    items = list(iter_claims_from_jsonl(in_path))
    assert len(items) == 2


def test_iter_claims_yields_error_tuples_for_malformed(tmp_path: Path):
    in_path = tmp_path / "in.jsonl"
    _write_jsonl(
        in_path,
        [
            _good_claim_dict("C1"),
            "not valid json",
            _good_claim_dict("C2"),
        ],
    )
    items = list(iter_claims_from_jsonl(in_path))
    assert len(items) == 3
    assert isinstance(items[0], Claim)
    assert isinstance(items[1], tuple)
    assert items[1][0] == 2
    assert isinstance(items[2], Claim)


def test_iter_claims_raises_on_malformed_when_skip_disabled(tmp_path: Path):
    in_path = tmp_path / "in.jsonl"
    _write_jsonl(in_path, [_good_claim_dict("C1"), "garbage"])
    with pytest.raises(Exception):
        list(iter_claims_from_jsonl(in_path, skip_malformed=False))


@pytest.fixture
def mock_myelin(monkeypatch):
    myelin = Myelin(build_jar_dirs=False, jar_path="./jars", db_path="./data/myelin.db")

    def fake_process(self, claim, **kwargs):
        from myelin.pricers.opps import OppsOutput

        out = MyelinOutput(opps=OppsOutput(total_claim_payment=10.0))
        if claim.claimid.startswith("FAIL"):
            out.error = "simulated"
        return out

    monkeypatch.setattr(Myelin, "process", fake_process)
    return myelin


def test_process_jsonl_basic(mock_myelin, tmp_path: Path):
    in_path = tmp_path / "in.jsonl"
    out_path = tmp_path / "out.jsonl"
    _write_jsonl(in_path, [_good_claim_dict("C1"), _good_claim_dict("C2")])

    stats = mock_myelin.process_jsonl(in_path, out_path, BatchOptions(progress=False))
    assert isinstance(stats, BatchStats)
    assert stats.total_count == 2
    assert stats.success_count == 2
    assert stats.failure_count == 0
    assert out_path.exists()
    records = _read_jsonl(out_path)
    assert len(records) == 2
    for record in records:
        assert "input" in record
        assert "output" in record


def test_process_jsonl_records_failures(mock_myelin, tmp_path: Path):
    in_path = tmp_path / "in.jsonl"
    out_path = tmp_path / "out.jsonl"
    _write_jsonl(
        in_path,
        [_good_claim_dict("C1"), _good_claim_dict("FAIL_C2"), _good_claim_dict("C3")],
    )

    stats = mock_myelin.process_jsonl(in_path, out_path, BatchOptions(progress=False))
    assert stats.total_count == 3
    assert stats.success_count == 2
    assert stats.failure_count == 1
    assert stats.error_histogram.get("simulated") == 1
    records = _read_jsonl(out_path)
    assert len(records) == 3


def test_process_jsonl_skip_malformed_writes_placeholder(mock_myelin, tmp_path: Path):
    in_path = tmp_path / "in.jsonl"
    out_path = tmp_path / "out.jsonl"
    _write_jsonl(
        in_path,
        [
            _good_claim_dict("C1"),
            "not valid json at all",
            _good_claim_dict("C2"),
        ],
    )

    stats = mock_myelin.process_jsonl(in_path, out_path, BatchOptions(progress=False))
    assert stats.total_count == 3
    assert stats.success_count == 2
    assert stats.skipped_count == 1
    assert stats.failure_count == 0
    parse_errors = [k for k in stats.error_histogram if k.startswith("JSONLParseError")]
    assert len(parse_errors) == 1

    records = _read_jsonl(out_path)
    assert len(records) == 3
    error_records = [
        r
        for r in records
        if (r.get("output", {}).get("error") or "").startswith("JSONLParseError")
    ]
    assert len(error_records) == 1
    assert error_records[0]["output"]["error"].startswith("JSONLParseError(line=2):")


def test_process_jsonl_raises_on_malformed_when_skip_disabled(mock_myelin, tmp_path: Path):
    in_path = tmp_path / "in.jsonl"
    out_path = tmp_path / "out.jsonl"
    _write_jsonl(in_path, [_good_claim_dict("C1"), "not json"])
    with pytest.raises(Exception):
        mock_myelin.process_jsonl(
            in_path, out_path, BatchOptions(progress=False), skip_malformed=False
        )


def test_process_jsonl_empty_input(mock_myelin, tmp_path: Path):
    in_path = tmp_path / "in.jsonl"
    out_path = tmp_path / "out.jsonl"
    in_path.write_text("")
    stats = mock_myelin.process_jsonl(in_path, out_path, BatchOptions(progress=False))
    assert stats.total_count == 0
    assert stats.success_count == 0
    assert out_path.exists()


def test_process_jsonl_only_blank_lines(mock_myelin, tmp_path: Path):
    in_path = tmp_path / "in.jsonl"
    out_path = tmp_path / "out.jsonl"
    in_path.write_text("\n\n\n")
    stats = mock_myelin.process_jsonl(in_path, out_path, BatchOptions(progress=False))
    assert stats.total_count == 0


def test_process_jsonl_creates_output_dir(mock_myelin, tmp_path: Path):
    in_path = tmp_path / "in.jsonl"
    out_path = tmp_path / "nested" / "deeper" / "out.jsonl"
    _write_jsonl(in_path, [_good_claim_dict("C1")])
    mock_myelin.process_jsonl(in_path, out_path, BatchOptions(progress=False))
    assert out_path.exists()


def test_process_jsonl_claim_count_eta(mock_myelin, tmp_path: Path):
    in_path = tmp_path / "in.jsonl"
    out_path = tmp_path / "out.jsonl"
    _write_jsonl(in_path, [_good_claim_dict("C1")] * 5)
    stats = mock_myelin.process_jsonl(
        in_path, out_path, BatchOptions(progress=False), claim_count=5
    )
    assert stats.total_count == 5


def test_process_jsonl_computes_throughput(mock_myelin, tmp_path: Path):
    in_path = tmp_path / "in.jsonl"
    out_path = tmp_path / "out.jsonl"
    _write_jsonl(in_path, [_good_claim_dict(f"C{i}") for i in range(3)])
    stats = mock_myelin.process_jsonl(in_path, out_path, BatchOptions(progress=False))
    assert stats.elapsed_seconds >= 0
    assert stats.claims_per_second >= 0
    assert stats.started_at is not None
    assert stats.finished_at is not None


def test_process_jsonl_with_wrapper_format(mock_myelin, tmp_path: Path):
    in_path = tmp_path / "in.jsonl"
    out_path = tmp_path / "out.jsonl"
    with in_path.open("w") as f:
        f.write(json.dumps({"input": _good_claim_dict("WRAPPED")}) + "\n")
    stats = mock_myelin.process_jsonl(in_path, out_path, BatchOptions(progress=False))
    assert stats.success_count == 1
    records = _read_jsonl(out_path)
    assert records[0]["input"]["claimid"] == "WRAPPED"


def test_process_jsonl_uses_max_workers(mock_myelin, tmp_path: Path):
    in_path = tmp_path / "in.jsonl"
    out_path = tmp_path / "out.jsonl"
    _write_jsonl(in_path, [_good_claim_dict(f"C{i}") for i in range(4)])
    opts = BatchOptions(max_workers=2, progress=False)
    stats = mock_myelin.process_jsonl(in_path, out_path, opts)
    assert stats.total_count == 4
    assert stats.success_count == 4


def test_process_jsonl_overwrites_existing_output(mock_myelin, tmp_path: Path):
    in_path = tmp_path / "in.jsonl"
    out_path = tmp_path / "out.jsonl"
    out_path.write_text("STALE DATA\n")
    _write_jsonl(in_path, [_good_claim_dict("C1")])
    mock_myelin.process_jsonl(in_path, out_path, BatchOptions(progress=False))
    records = _read_jsonl(out_path)
    assert len(records) == 1
    assert "STALE" not in out_path.read_text()

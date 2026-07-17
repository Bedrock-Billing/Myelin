from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from myelin import BatchOptions, Myelin
from myelin.batch.csv_io import (
    DEFAULT_OUTPUT_COLUMNS,
    iter_claims_from_csv,
    mio_to_csv_row,
    read_csv_claim,
    write_csv_header,
    write_mio_csv_row,
)
from myelin.batch.result import BatchStats
from myelin.core import MyelinIO, MyelinOutput
from myelin.input import Claim
from myelin.pricers.opps import OppsOutput


def _good_claim_row(claimid: str = "CSV_001") -> dict[str, str]:
    return {
        "claimid": claimid,
        "principal_dx.code": "A021",
        "principal_dx.poa": "Y",
        "patient.age": "65",
        "patient.sex": "M",
        "from_date": "2025-07-01T00:00:00",
        "thru_date": "2025-07-10T00:00:00",
        "admit_date": "2025-07-01T00:00:00",
        "patient_status": "01",
        "los": "9",
        "billing_provider.other_id": "010001",
    }


def _write_csv(path: Path, rows: list[dict[str, str]] | list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        if not rows:
            return
        if isinstance(rows[0], str):
            f.write("\n".join(rows) + "\n")
            return
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def test_read_csv_claim_basic():
    row = _good_claim_row()
    claim = read_csv_claim(row)
    assert claim.claimid == "CSV_001"
    assert claim.principal_dx is not None
    assert claim.principal_dx.code == "A021"
    assert claim.principal_dx.poa.value == "Y"
    assert claim.patient.age == 65
    assert claim.los == 9
    assert claim.billing_provider is not None
    assert claim.billing_provider.other_id == "010001"


def test_read_csv_claim_blank_cells_skipped():
    row = _good_claim_row()
    row["los"] = ""
    row["patient.sex"] = ""
    claim = read_csv_claim(row)
    assert claim.claimid == "CSV_001"
    assert claim.patient.sex in (None, "")


def test_read_csv_claim_with_json_input_column():
    payload = {
        "input": json.dumps(
            {
                "claimid": "WRAPPED",
                "principal_dx": {"code": "A021", "poa": "Y"},
            }
        )
    }
    claim = read_csv_claim(payload)
    assert claim.claimid == "WRAPPED"


def test_iter_claims_from_csv_yields_claims(tmp_path: Path):
    in_path = tmp_path / "in.csv"
    _write_csv(in_path, [_good_claim_row("C1"), _good_claim_row("C2")])
    items = list(iter_claims_from_csv(in_path))
    assert len(items) == 2
    assert all(isinstance(item, Claim) for item in items)


def test_iter_claims_from_csv_skips_blank_rows(tmp_path: Path):
    in_path = tmp_path / "in.csv"
    _write_csv(
        in_path,
        [
            _good_claim_row("C1"),
            {},
            _good_claim_row("C2"),
        ],
    )
    items = list(iter_claims_from_csv(in_path))
    assert len(items) == 2


def test_iter_claims_yields_error_tuples_for_malformed(tmp_path: Path):
    in_path = tmp_path / "in.csv"
    rows = [
        _good_claim_row("C1"),
        {"claimid": "BAD", "principal_dx.code": "Z999999", "los": "not-a-number"},
        _good_claim_row("C2"),
    ]
    _write_csv(in_path, rows)
    items = list(iter_claims_from_csv(in_path))
    assert len(items) == 3
    assert isinstance(items[0], Claim)
    assert isinstance(items[1], tuple)
    assert items[1][0] == 3
    assert isinstance(items[2], Claim)


def test_iter_claims_raises_on_malformed_when_skip_disabled(tmp_path: Path):
    in_path = tmp_path / "in.csv"
    rows = [
        _good_claim_row("C1"),
        {"claimid": "BAD", "principal_dx.code": "Z999999", "los": "not-a-number"},
    ]
    _write_csv(in_path, rows)
    with pytest.raises(Exception):
        list(iter_claims_from_csv(in_path, skip_malformed=False))


def test_mio_to_csv_row_ok():
    mio = MyelinIO(
        input=Claim(claimid="X"),
        output=MyelinOutput(opps=OppsOutput(total_claim_payment=42.0)),
    )
    row = mio_to_csv_row(mio)
    assert row["claimid"] == "X"
    assert row["status"] == "ok"
    assert row["error"] == ""
    assert row["total_payment"] == 42.0
    assert row["opps_payment"] == 42.0


def test_mio_to_csv_row_error():
    mio = MyelinIO(
        input=Claim(claimid="Y"),
        output=MyelinOutput(error="simulated"),
    )
    row = mio_to_csv_row(mio)
    assert row["claimid"] == "Y"
    assert row["status"] == "error"
    assert row["error"] == "simulated"


def test_write_csv_header_writes_columns(tmp_path: Path):
    out_path = tmp_path / "h.csv"
    with out_path.open("w", encoding="utf-8", newline="") as f:
        write_csv_header(f)
    assert out_path.read_text().strip() == ",".join(DEFAULT_OUTPUT_COLUMNS)


def test_write_mio_csv_row_round_trip(tmp_path: Path):
    out_path = tmp_path / "rt.csv"
    mio = MyelinIO(
        input=Claim(claimid="RT"),
        output=MyelinOutput(opps=OppsOutput(total_claim_payment=7.5)),
    )
    with out_path.open("w", encoding="utf-8", newline="") as f:
        write_csv_header(f)
        write_mio_csv_row(mio, f)
    rows = _read_csv(out_path)
    assert len(rows) == 1
    assert rows[0]["claimid"] == "RT"
    assert rows[0]["status"] == "ok"
    assert float(rows[0]["opps_payment"]) == 7.5


@pytest.fixture
def mock_myelin(monkeypatch):
    myelin = Myelin(build_jar_dirs=False, jar_path="./jars", db_path="./data/myelin.db")

    def fake_process(self, claim, **kwargs):
        out = MyelinOutput(opps=OppsOutput(total_claim_payment=10.0))
        if claim.claimid.startswith("FAIL"):
            out.error = "simulated"
        return out

    monkeypatch.setattr(Myelin, "process", fake_process)
    return myelin


def test_process_csv_basic(mock_myelin, tmp_path: Path):
    in_path = tmp_path / "in.csv"
    out_path = tmp_path / "out.csv"
    _write_csv(in_path, [_good_claim_row("C1"), _good_claim_row("C2")])
    stats = mock_myelin.process_csv(in_path, out_path, BatchOptions(progress=False))
    assert isinstance(stats, BatchStats)
    assert stats.total_count == 2
    assert stats.success_count == 2
    assert stats.failure_count == 0
    rows = _read_csv(out_path)
    assert len(rows) == 2
    assert set(rows[0].keys()) == set(DEFAULT_OUTPUT_COLUMNS)


def test_process_csv_records_failures(mock_myelin, tmp_path: Path):
    in_path = tmp_path / "in.csv"
    out_path = tmp_path / "out.csv"
    _write_csv(
        in_path,
        [
            _good_claim_row("C1"),
            _good_claim_row("FAIL_C2"),
            _good_claim_row("C3"),
        ],
    )
    stats = mock_myelin.process_csv(in_path, out_path, BatchOptions(progress=False))
    assert stats.total_count == 3
    assert stats.success_count == 2
    assert stats.failure_count == 1
    assert stats.error_histogram.get("simulated") == 1


def test_process_csv_skip_malformed_writes_placeholder(mock_myelin, tmp_path: Path):
    in_path = tmp_path / "in.csv"
    out_path = tmp_path / "out.csv"
    rows = [
        _good_claim_row("C1"),
        {"claimid": "BAD", "principal_dx.code": "Z999999", "los": "not-a-number"},
        _good_claim_row("C2"),
    ]
    _write_csv(in_path, rows)
    stats = mock_myelin.process_csv(in_path, out_path, BatchOptions(progress=False))
    assert stats.total_count == 3
    assert stats.success_count == 2
    assert stats.skipped_count == 1
    assert stats.failure_count == 0
    parse_errors = [k for k in stats.error_histogram if k.startswith("CSVParseError")]
    assert len(parse_errors) == 1
    out_rows = _read_csv(out_path)
    assert len(out_rows) == 3
    error_rows = [r for r in out_rows if (r.get("error") or "").startswith("CSVParseError")]
    assert len(error_rows) == 1
    assert "line=3" in error_rows[0]["error"]


def test_process_csv_raises_on_malformed_when_skip_disabled(mock_myelin, tmp_path: Path):
    in_path = tmp_path / "in.csv"
    out_path = tmp_path / "out.csv"
    rows = [
        _good_claim_row("C1"),
        {"claimid": "BAD", "principal_dx.code": "Z999999", "los": "not-a-number"},
    ]
    _write_csv(in_path, rows)
    with pytest.raises(Exception):
        mock_myelin.process_csv(
            in_path, out_path, BatchOptions(progress=False), skip_malformed=False
        )


def test_process_csv_empty_input(mock_myelin, tmp_path: Path):
    in_path = tmp_path / "empty.csv"
    out_path = tmp_path / "out.csv"
    in_path.write_text("")
    stats = mock_myelin.process_csv(in_path, out_path, BatchOptions(progress=False))
    assert stats.total_count == 0
    rows = _read_csv(out_path)
    assert len(rows) == 0
    assert out_path.read_text().strip() == ",".join(DEFAULT_OUTPUT_COLUMNS)


def test_process_csv_creates_output_dir(mock_myelin, tmp_path: Path):
    in_path = tmp_path / "in.csv"
    out_path = tmp_path / "nested" / "deeper" / "out.csv"
    _write_csv(in_path, [_good_claim_row("C1")])
    mock_myelin.process_csv(in_path, out_path, BatchOptions(progress=False))
    assert out_path.exists()


def test_process_csv_max_workers(mock_myelin, tmp_path: Path):
    in_path = tmp_path / "in.csv"
    out_path = tmp_path / "out.csv"
    _write_csv(in_path, [_good_claim_row(f"C{i}") for i in range(4)])
    stats = mock_myelin.process_csv(
        in_path, out_path, BatchOptions(max_workers=2, progress=False)
    )
    assert stats.total_count == 4
    assert stats.success_count == 4


def test_process_csv_claim_count_eta(mock_myelin, tmp_path: Path):
    in_path = tmp_path / "in.csv"
    out_path = tmp_path / "out.csv"
    _write_csv(in_path, [_good_claim_row("C1")] * 5)
    stats = mock_myelin.process_csv(
        in_path, out_path, BatchOptions(progress=False), claim_count=5
    )
    assert stats.total_count == 5


def test_process_csv_output_has_header_and_rows(mock_myelin, tmp_path: Path):
    in_path = tmp_path / "in.csv"
    out_path = tmp_path / "out.csv"
    _write_csv(in_path, [_good_claim_row("AAA"), _good_claim_row("BBB")])
    mock_myelin.process_csv(in_path, out_path, BatchOptions(progress=False))
    out_text = out_path.read_text()
    lines = out_text.strip().split("\n")
    assert len(lines) == 3
    assert lines[0] == ",".join(DEFAULT_OUTPUT_COLUMNS)

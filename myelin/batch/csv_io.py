from __future__ import annotations

import csv
from collections.abc import Iterator
from pathlib import Path
from typing import IO, Any

from myelin.batch.jsonl import read_claim_line
from myelin.batch.result import extract_per_pricer_totals, extract_total_payment
from myelin.core import MyelinIO
from myelin.input.claim import Claim


DEFAULT_OUTPUT_COLUMNS: list[str] = [
    "claimid",
    "status",
    "error",
    "total_payment",
    "ipps_payment",
    "opps_payment",
    "psych_payment",
    "ltch_payment",
    "irf_payment",
    "hospice_payment",
    "snf_payment",
    "hha_payment",
    "esrd_payment",
    "fqhc_payment",
    "asc_payment",
]


def read_csv_claim(row: dict[str, str]) -> Claim:
    """Convert a CSV row dict to a Claim.

    CSV columns use dot notation for nested fields (e.g. ``principal_dx.code``).
    Blank cells are skipped. A column named ``input`` whose value is JSON is
    passed through ``read_claim_line`` for full MyelinIO-payload support.
    """
    if "input" in row and row["input"]:
        return read_claim_line(row["input"])

    payload: dict[str, Any] = {}
    for key, value in row.items():
        if value is None or str(value).strip() == "":
            continue
        clean = str(value).strip()
        parts = key.split(".")
        cursor = payload
        for part in parts[:-1]:
            existing = cursor.get(part)
            if not isinstance(existing, dict):
                cursor[part] = {}
            cursor = cursor[part]
        cursor[parts[-1]] = clean

    return Claim.model_validate(payload)


def iter_claims_from_csv(
    path: str | Path,
    skip_malformed: bool = True,
) -> Iterator[Claim | tuple[int, dict[str, str], Exception]]:
    """Yield Claim objects from a CSV file, one per row.

    If ``skip_malformed`` is True, yield ``(line_number, raw_row, exc)``
    tuples for rows that fail to parse. If False, raise on the first error.
    Blank rows are skipped.
    """
    in_path = Path(path)
    with in_path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for line_number, row in enumerate(reader, start=2):
            if not any((v or "").strip() for v in row.values()):
                continue
            try:
                yield read_csv_claim(row)
            except Exception as exc:
                if not skip_malformed:
                    raise
                yield (line_number, row, exc)


def mio_to_csv_row(mio: MyelinIO) -> dict[str, Any]:
    """Convert a MyelinIO to a flat dict suitable for a CSV row."""
    error = None
    if mio.output is not None and mio.output.error:
        error = str(mio.output.error)
    status = "ok" if error is None else "error"
    claimid = mio.input.claimid if mio.input is not None else ""
    per_pricer = extract_per_pricer_totals(mio.output)
    row: dict[str, Any] = {
        "claimid": claimid,
        "status": status,
        "error": error or "",
        "total_payment": extract_total_payment(mio.output),
    }
    for attr in (
        "ipps",
        "opps",
        "psych",
        "ltch",
        "irf",
        "hospice",
        "snf",
        "hha",
        "esrd",
        "fqhc",
        "asc",
    ):
        row[f"{attr}_payment"] = per_pricer.get(attr, 0.0)
    return row


def write_csv_header(out_f: IO[str], columns: list[str] | None = None) -> None:
    """Write a CSV header row using ``columns`` (or the default)."""
    cols = columns or DEFAULT_OUTPUT_COLUMNS
    writer = csv.DictWriter(out_f, fieldnames=cols)
    writer.writeheader()


def write_mio_csv_row(
    mio: MyelinIO,
    out_f: IO[str],
    columns: list[str] | None = None,
) -> None:
    """Write a single MyelinIO as a CSV row (no header)."""
    cols = columns or DEFAULT_OUTPUT_COLUMNS
    row = mio_to_csv_row(mio)
    writer = csv.DictWriter(out_f, fieldnames=cols, extrasaction="ignore")
    writer.writerow(row)


__all__ = [
    "DEFAULT_OUTPUT_COLUMNS",
    "read_csv_claim",
    "iter_claims_from_csv",
    "mio_to_csv_row",
    "write_csv_header",
    "write_mio_csv_row",
]

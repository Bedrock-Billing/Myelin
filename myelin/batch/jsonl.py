from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import IO, Any

from myelin.core import MyelinIO
from myelin.input.claim import Claim


def mio_to_dict(mio: MyelinIO) -> dict[str, Any]:
    record: dict[str, Any] = {}
    if mio.input is not None:
        record["input"] = mio.input.model_dump(mode="json")
    if mio.output is not None:
        record["output"] = mio.output.model_dump(mode="json")
    return record


def write_mio_line(mio: MyelinIO, out_f: IO[str]) -> None:
    out_f.write(json.dumps(mio_to_dict(mio), default=str) + "\n")


def read_claim_line(line: str) -> Claim:
    record = json.loads(line)
    if "input" in record and isinstance(record["input"], dict):
        payload = record["input"]
    else:
        payload = record
    return Claim.model_validate(payload)


def iter_claims_from_jsonl(
    path: str | Path,
    skip_malformed: bool = True,
) -> Iterator[Claim | tuple[int, str, Exception]]:
    """Yield Claim objects from a JSONL file, one per line.

    If skip_malformed is True (default), yield ``(line_number, raw_line, exc)``
    tuples for lines that fail to parse. If False, raise on the first error.
    """
    in_path = Path(path)
    with in_path.open("r", encoding="utf-8") as f:
        for line_number, raw in enumerate(f, start=1):
            stripped = raw.strip()
            if not stripped:
                continue
            try:
                yield read_claim_line(stripped)
            except Exception as exc:
                if not skip_malformed:
                    raise
                yield (line_number, stripped, exc)


__all__ = [
    "mio_to_dict",
    "write_mio_line",
    "read_claim_line",
    "iter_claims_from_jsonl",
]

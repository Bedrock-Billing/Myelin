"""Generate a JSONL file of test claims for batch processing.

Usage:
    python examples/generate_test_jsonl.py --count 5000 --output test_claims.jsonl
    python examples/generate_test_jsonl.py  # defaults to 1000 claims, ./test_claims.jsonl
"""
from __future__ import annotations

import argparse
import json
import random
from datetime import datetime, timedelta
from pathlib import Path

from myelin.helpers.claim_examples import claim_example
from myelin.input import (
    DiagnosisCode,
    LineItem,
    Modules,
    PoaType,
    Provider,
    ValueCode,
)


_DX_CODES = [
    "A021", "J189", "I214", "N179", "R078", "E119",
    "M5450", "K219", "F329", "L03115", "G43909", "D649",
]
_REV_CODES = ["0022", "0024", "0110", "0250", "0300", "0360", "0450", "0636", "0710"]
_HCPCS = ["99213", "99214", "99223", "93000", "36415", "85025", "80053", "71046", "73721"]
_MODIFIERS = ["", "25", "59", "76", "77", "LT", "RT", "59", "22"]
_FACILITY_NAMES = [
    "GENERAL HOSPITAL",
    "REGIONAL MEDICAL CENTER",
    "MEMORIAL HOSPITAL",
    "COMMUNITY HEALTH",
    "UNIVERSITY HOSPITAL",
]


def _random_claim(i: int) -> dict:
    """Build a claim that varies in fields so the batch isn't all-identical."""
    base = claim_example()
    base.claimid = f"BATCH_{i:07d}"
    base.principal_dx = DiagnosisCode(
        code=random.choice(_DX_CODES), poa=random.choice(list(PoaType))
    )
    if random.random() < 0.5:
        base.secondary_dxs.append(
            DiagnosisCode(
                code=random.choice(_DX_CODES),
                poa=random.choice(list(PoaType)),
            )
        )
    base.patient.age = random.randint(18, 90)
    base.patient.sex = random.choice(["M", "F"])
    days = random.randint(1, 14)
    base.admit_date = datetime(2025, 1, 1) + timedelta(days=random.randint(0, 180))
    base.from_date = base.admit_date
    base.thru_date = base.from_date + timedelta(days=days)
    base.los = days + 1
    base.bill_type = random.choice(["111", "113", "131", "851"])
    base.patient_status = random.choice(["01", "02", "03", "20", "30", "40", "50"])

    base.billing_provider = Provider()
    base.billing_provider.other_id = "010001"
    base.billing_provider.facility_name = random.choice(_FACILITY_NAMES)
    base.billing_provider.npi = f"{random.randint(10**8, 10**9 - 1)}"

    if random.random() < 0.3:
        base.value_codes.append(
            ValueCode(
                code=random.choice(["50", "54", "61", "80"]),
                amount=round(random.uniform(0, 500), 2),
            )
        )

    if random.random() < 0.6:
        n_lines = random.randint(1, 4)
        for _ in range(n_lines):
            base.lines.append(
                LineItem(
                    service_date=base.from_date,
                    revenue_code=random.choice(_REV_CODES),
                    hcpcs=random.choice(_HCPCS),
                    modifiers=[m for m in [random.choice(_MODIFIERS)] if m],
                    units=random.choice([1, 1, 1, 2, 3]),
                    charges=round(random.uniform(50, 5000), 2),
                )
            )

    base.modules = [Modules.AUTO]
    return base.model_dump(mode="json")


def generate_jsonl(count: int, output_path: Path, seed: int = 42) -> None:
    random.seed(seed)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        for i in range(count):
            f.write(json.dumps(_random_claim(i), default=str) + "\n")
    size_mb = output_path.stat().st_size / (1024 * 1024)
    print(f"Wrote {count} claims to {output_path} ({size_mb:.1f} MB)")


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate a JSONL test file")
    parser.add_argument(
        "-c",
        "--count",
        type=int,
        default=1000,
        help="Number of claims to generate (default: 1000)",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=Path("test_claims.jsonl"),
        help="Output path (default: ./test_claims.jsonl)",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed for reproducibility (default: 42)",
    )
    args = parser.parse_args()
    generate_jsonl(args.count, args.output, args.seed)


if __name__ == "__main__":
    main()

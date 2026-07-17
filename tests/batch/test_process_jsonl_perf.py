from __future__ import annotations

import gc
import json
import tracemalloc
from pathlib import Path

import pytest

from myelin import BatchOptions, Myelin
from myelin.core import MyelinOutput
from myelin.pricers.opps import OppsOutput


def _good_claim_dict(claimid: str = "PERF_001") -> dict:
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


def _write_jsonl(path: Path, count: int) -> None:
    with path.open("w", encoding="utf-8") as f:
        for i in range(count):
            f.write(json.dumps(_good_claim_dict(f"PERF_{i:06d}")) + "\n")


def _read_jsonl_count(path: Path) -> int:
    count = 0
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                count += 1
    return count


@pytest.fixture
def fast_myelin(monkeypatch):
    """A Myelin instance with a fast in-process fake that doesn't touch JARs."""
    myelin = Myelin(build_jar_dirs=False, jar_path="./jars", db_path="./data/myelin.db")

    def fake_process(self, claim, **kwargs):
        return MyelinOutput(opps=OppsOutput(total_claim_payment=10.0))

    monkeypatch.setattr(Myelin, "process", fake_process)
    return myelin


def test_process_jsonl_large_file_streams_results(fast_myelin, tmp_path: Path):
    n = 2000
    in_path = tmp_path / "large_in.jsonl"
    out_path = tmp_path / "large_out.jsonl"
    _write_jsonl(in_path, n)

    stats = fast_myelin.process_jsonl(
        in_path, out_path, BatchOptions(progress=False), claim_count=n
    )

    assert stats.total_count == n
    assert stats.success_count == n
    assert stats.failure_count == 0
    assert _read_jsonl_count(out_path) == n


def test_process_jsonl_throughput_reasonable(fast_myelin, tmp_path: Path):
    n = 500
    in_path = tmp_path / "thr_in.jsonl"
    out_path = tmp_path / "thr_out.jsonl"
    _write_jsonl(in_path, n)

    stats = fast_myelin.process_jsonl(in_path, out_path, BatchOptions(progress=False))
    assert stats.elapsed_seconds >= 0
    assert stats.claims_per_second > 0
    assert stats.claims_per_second > 50


def test_process_jsonl_memory_bounded_for_large_file(fast_myelin, tmp_path: Path):
    n = 1500
    in_path = tmp_path / "mem_in.jsonl"
    out_path = tmp_path / "mem_out.jsonl"
    _write_jsonl(in_path, n)

    gc.collect()
    tracemalloc.start()
    try:
        stats = fast_myelin.process_jsonl(
            in_path, out_path, BatchOptions(progress=False, max_workers=2), claim_count=n
        )
        current, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()

    assert stats.total_count == n
    assert peak < 50 * 1024 * 1024, (
        f"Peak memory {peak / 1024 / 1024:.1f} MB exceeds 50 MB budget "
        f"for {n} claims — streaming may not be working"
    )


def test_process_jsonl_completes_in_reasonable_time(fast_myelin, tmp_path: Path):
    import time

    n = 500
    in_path = tmp_path / "time_in.jsonl"
    out_path = tmp_path / "time_out.jsonl"
    _write_jsonl(in_path, n)

    t0 = time.perf_counter()
    fast_myelin.process_jsonl(in_path, out_path, BatchOptions(progress=False))
    elapsed = time.perf_counter() - t0

    assert elapsed < 30.0, f"Processing {n} claims took {elapsed:.1f}s — too slow"


def test_process_jsonl_concurrent_workers_actually_used(fast_myelin, tmp_path: Path):
    import threading

    in_path = tmp_path / "concurrent_in.jsonl"
    out_path = tmp_path / "concurrent_out.jsonl"
    n = 100
    _write_jsonl(in_path, n)

    threads_seen: list[str] = []

    def fake_process(self, claim, **kwargs):
        threads_seen.append(threading.current_thread().name)
        return MyelinOutput(opps=OppsOutput(total_claim_payment=10.0))

    import myelin.core

    original = myelin.core.Myelin.process
    myelin.core.Myelin.process = fake_process
    try:
        fast_myelin.process_jsonl(
            in_path,
            out_path,
            BatchOptions(progress=False, max_workers=4),
        )
    finally:
        myelin.core.Myelin.process = original

    worker_threads = [
        t for t in threads_seen if t.startswith("myelin-jsonl")
    ]
    assert len(worker_threads) > 0
    distinct_workers = set(worker_threads)
    assert len(distinct_workers) >= 2, (
        f"Expected work to spread across multiple worker threads, "
        f"only saw {distinct_workers}"
    )


def test_process_jsonl_output_lines_match_input(fast_myelin, tmp_path: Path):
    n = 50
    in_path = tmp_path / "match_in.jsonl"
    out_path = tmp_path / "match_out.jsonl"
    _write_jsonl(in_path, n)

    fast_myelin.process_jsonl(in_path, out_path, BatchOptions(progress=False))

    input_claimids = []
    with in_path.open() as f:
        for line in f:
            if line.strip():
                input_claimids.append(json.loads(line)["claimid"])

    output_lines = 0
    with out_path.open() as f:
        for line in f:
            if line.strip():
                output_lines += 1

    assert output_lines == len(input_claimids) == n

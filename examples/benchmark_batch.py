"""Run a batch timing benchmark on a test JSONL file.

The first claim is slow (JVM warmup + pricer table loads). The benchmark
runs a warmup pass first, then times the actual batch.

Usage:
    python examples/benchmark_batch.py test_claims.jsonl
    python examples/benchmark_batch.py test_claims.jsonl --workers 2 --cache

Note on workers: the CMS pricing workload is GIL-bound. Each per-claim
Python work (Pydantic validation, IPSF provider SQLite lookup, MyelinOutput
construction) does not release the GIL. Benchmarking shows that 2 workers
is consistently the sweet spot -- 4+ workers actually hurts throughput
because the GIL contention overhead exceeds any parallelism benefit.

Note on the provider cache: enable it with --cache when the batch is
dominated by claims with a small number of distinct provider CCNs. The
SQLite IPSF lookup is the dominant per-claim cost in the default config;
caching it can double or triple throughput.
"""
from __future__ import annotations

import argparse
import time
from pathlib import Path

from myelin import BatchOptions, Myelin
from myelin.input import Modules
from myelin.helpers.claim_examples import claim_example


def _warmup(myelin: Myelin) -> None:
    print("Warming up JVM (loading pricer tables) ...", flush=True)
    t0 = time.perf_counter()
    for bill_type in ("111", "131"):
        c = claim_example()
        c.modules = [Modules.AUTO]
        c.bill_type = bill_type
        myelin.process(c)
    print(f"Warmup done in {time.perf_counter() - t0:.1f}s", flush=True)


def benchmark(
    input_path: Path,
    output_path: Path,
    max_workers: int,
    claim_count: int | None,
    enable_cache: bool,
) -> None:
    print(f"Input:   {input_path} ({input_path.stat().st_size / 1024 / 1024:.1f} MB)")
    print(f"Output:  {output_path}")
    print(f"Workers: {max_workers}")
    print(f"Cache:   {'enabled' if enable_cache else 'disabled'}")
    print()

    myelin = Myelin(build_jar_dirs=False, enable_provider_cache=enable_cache)
    myelin.setup_clients()
    _warmup(myelin)
    print()

    print("Running batch ...", flush=True)
    t0 = time.perf_counter()
    stats = myelin.process_jsonl(
        input_path,
        output_path,
        BatchOptions(max_workers=max_workers, progress=True),
        claim_count=claim_count,
    )
    elapsed = time.perf_counter() - t0

    print()
    print("=" * 50)
    print(f"Processed: {stats.total_count} claims in {elapsed:.2f}s")
    print(f"  success: {stats.success_count}")
    print(f"  failed:  {stats.failure_count}")
    print(f"  skipped: {stats.skipped_count}")
    print(f"  throughput: {stats.total_count / elapsed:.0f} claims/sec")
    cache = myelin.provider_cache_info()
    if cache["hits"] or cache["misses"]:
        hit_rate = (
            cache["hits"] / (cache["hits"] + cache["misses"]) * 100
            if (cache["hits"] + cache["misses"]) > 0
            else 0
        )
        print(
            f"  provider cache: {cache['hits']} hits / "
            f"{cache['misses']} misses ({hit_rate:.0f}% hit rate)"
        )
    if stats.error_histogram:
        print("  errors:")
        for err, count in stats.error_histogram.items():
            print(f"    {err}: {count}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark Myelin batch processing")
    parser.add_argument("input", type=Path, help="Input JSONL file")
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=Path("benchmark_results.jsonl"),
        help="Output JSONL file (default: ./benchmark_results.jsonl)",
    )
    parser.add_argument(
        "-w",
        "--workers",
        type=int,
        default=2,
        help=(
            "Number of worker threads (default: 2). "
            "More workers hurt throughput due to GIL contention; "
            "the per-claim Python work is significant relative to "
            "the Java pricing call."
        ),
    )
    parser.add_argument(
        "-n",
        "--claim-count",
        type=int,
        default=None,
        help="Total claim count (for progress ETA, optional)",
    )
    parser.add_argument(
        "--cache",
        action="store_true",
        help="Enable the opt-in IPSF provider cache (recommended for batches "
        "with repeated provider CCNs)",
    )
    args = parser.parse_args()
    benchmark(args.input, args.output, args.workers, args.claim_count, args.cache)


if __name__ == "__main__":
    main()

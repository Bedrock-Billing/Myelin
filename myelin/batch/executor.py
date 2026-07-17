from __future__ import annotations

import multiprocessing
import os
from concurrent.futures import (
    Executor,
    ProcessPoolExecutor,
    ThreadPoolExecutor,
    as_completed,
)
from datetime import datetime
from typing import Iterable, Iterator, Sequence

from myelin.batch.options import BatchOptions, OnError
from myelin.batch.progress import make_progress
from myelin.batch.result import (
    BatchStats,
    classify_error,
    extract_per_pricer_totals,
    extract_total_payment,
)
from myelin.batch.worker import process_chunk, worker_process_claim
from myelin.core import Myelin, MyelinIO, MyelinOutput
from myelin.input.claim import Claim


def _to_mio(claim: Claim, exc: BaseException) -> MyelinIO:
    error = f"{type(exc).__name__}: {exc}"
    return MyelinIO.model_construct(
        input=claim, output=MyelinOutput(error=error)
    )


def _should_fail_fast(options: BatchOptions, exc: BaseException) -> bool:
    if options.on_error is not OnError.FAIL_FAST:
        return False
    if isinstance(exc, (KeyboardInterrupt, SystemExit)):
        return False
    return True


def _build_thread_executor(max_workers: int) -> Executor:
    return ThreadPoolExecutor(
        max_workers=max_workers, thread_name_prefix="myelin-batch"
    )


def _build_process_executor(max_workers: int) -> Executor:
    ctx = multiprocessing.get_context("spawn")
    return ProcessPoolExecutor(max_workers=max_workers, mp_context=ctx)


def _validate(claim: Claim) -> Claim | MyelinIO:
    try:
        Claim.model_validate(claim)
    except Exception as exc:
        return MyelinIO.model_construct(
            input=claim,
            output=MyelinOutput(error=f"ValidationError: {exc}"),
        )
    if not claim.modules:
        from myelin.input.claim import Modules

        return claim.model_copy(update={"modules": [Modules.AUTO]})
    return claim


def _record_mio(
    mio: MyelinIO,
    stats: BatchStats,
) -> None:
    err = classify_error(mio.output)
    if err is None:
        stats.success_count += 1
    else:
        stats.failure_count += 1
        stats.error_histogram[err] = stats.error_histogram.get(err, 0) + 1


def _ensure_myelin_ready(myelin: Myelin) -> None:
    if getattr(myelin, "drg_client", None) is None:
        myelin.setup_clients()


def run_thread_batch(
    claims: Sequence[Claim],
    options: BatchOptions,
    myelin: Myelin,
) -> tuple[list[MyelinIO], BatchStats]:
    _ensure_myelin_ready(myelin)
    progress = make_progress(options.resolved_progress(), total=len(claims))
    results: list[MyelinIO | None] = [None] * len(claims)
    stats = BatchStats(total_count=len(claims))

    try:
        with _build_thread_executor(options.resolved_max_workers()) as pool:
            futures = {}
            for i, claim in enumerate(claims):
                validated = _validate(claim)
                if isinstance(validated, MyelinIO):
                    results[i] = validated
                    stats.skipped_count += 1
                    err = classify_error(validated.output)
                    if err is not None:
                        stats.error_histogram[err] = stats.error_histogram.get(err, 0) + 1
                    progress.update(1)
                    continue
                futures[pool.submit(myelin.process, validated)] = i

            for fut in as_completed(futures):
                i = futures.pop(fut)
                original_claim = claims[i]
                try:
                    output = fut.result()
                    mio: MyelinIO = MyelinIO(input=original_claim, output=output)
                except Exception as exc:
                    if _should_fail_fast(options, exc):
                        progress.close()
                        raise
                    mio = _to_mio(original_claim, exc)
                results[i] = mio
                progress.update(1)
                _record_mio(mio, stats)
    finally:
        progress.close()

    return [r for r in results if r is not None], stats


def run_thread_stream(
    claims: Iterable[Claim],
    options: BatchOptions,
    myelin: Myelin,
    total: int | None = None,
) -> Iterator[MyelinIO]:
    _ensure_myelin_ready(myelin)
    progress = make_progress(options.resolved_progress(), total=total if total else 0)
    try:
        with _build_thread_executor(options.resolved_max_workers()) as pool:
            for claim in claims:
                validated = _validate(claim)
                if isinstance(validated, MyelinIO):
                    progress.update(1)
                    yield validated
                    continue
                fut = pool.submit(myelin.process, validated)
                try:
                    output = fut.result()
                    mio: MyelinIO = MyelinIO(input=claim, output=output)
                except Exception as exc:
                    if _should_fail_fast(options, exc):
                        progress.close()
                        raise
                    mio = _to_mio(claim, exc)
                progress.update(1)
                yield mio
    finally:
        progress.close()


def run_process_batch(
    claims: Sequence[Claim],
    options: BatchOptions,
    jar_path: str,
    db_path: str,
    build_db: bool,
) -> tuple[list[MyelinIO], BatchStats]:
    progress = make_progress(options.resolved_progress(), total=len(claims))
    results: list[MyelinIO | None] = [None] * len(claims)
    stats = BatchStats(total_count=len(claims))

    os.environ.setdefault("MYELIN_JAR_PATH", jar_path)
    os.environ.setdefault("MYELIN_DB_PATH", db_path)
    os.environ.setdefault("MYELIN_BUILD_DB", "1" if build_db else "0")

    chunks: list[list[Claim]] = []
    for i in range(0, len(claims), max(1, options.chunk_size)):
        chunks.append(list(claims[i : i + options.chunk_size]))
    chunk_offsets = [0]
    for chunk in chunks[:-1]:
        chunk_offsets.append(chunk_offsets[-1] + len(chunk))

    try:
        with _build_process_executor(options.resolved_max_workers()) as pool:
            futures = {
                pool.submit(process_chunk, (chunk, jar_path, db_path, build_db)): off
                for chunk, off in zip(chunks, chunk_offsets)
            }
            for fut in as_completed(futures):
                offset = futures.pop(fut)
                chunk_results = fut.result()
                for j, mio in enumerate(chunk_results):
                    results[offset + j] = mio
                    progress.update(1)
                    _record_mio(mio, stats)
    finally:
        progress.close()

    return [r for r in results if r is not None], stats


def run_process_stream(
    claims: Iterable[Claim],
    options: BatchOptions,
    jar_path: str,
    db_path: str,
    build_db: bool,
    total: int | None = None,
) -> Iterator[MyelinIO]:
    progress = make_progress(options.resolved_progress(), total=total if total else 0)
    os.environ.setdefault("MYELIN_JAR_PATH", jar_path)
    os.environ.setdefault("MYELIN_DB_PATH", db_path)
    os.environ.setdefault("MYELIN_BUILD_DB", "1" if build_db else "0")
    try:
        with _build_process_executor(options.resolved_max_workers()) as pool:
            for claim in claims:
                fut = pool.submit(worker_process_claim, claim)
                try:
                    mio: MyelinIO = fut.result()
                except Exception as exc:
                    if _should_fail_fast(options, exc):
                        progress.close()
                        raise
                    mio = _to_mio(claim, exc)
                progress.update(1)
                yield mio
    finally:
        progress.close()


def finalize_stats(
    items: list[MyelinIO],
    stats: BatchStats,
    elapsed: float,
    started_at: datetime,
    finished_at: datetime,
) -> BatchStats:
    stats.elapsed_seconds = elapsed
    stats.claims_per_second = (stats.total_count / elapsed) if elapsed > 0 else 0.0
    stats.started_at = started_at
    stats.finished_at = finished_at
    per_pricer_acc: dict[str, float] = dict(stats.per_pricer_total_payment)
    total_payment = 0.0
    for mio in items:
        totals = extract_per_pricer_totals(mio.output)
        for attr, value in totals.items():
            per_pricer_acc[attr] = per_pricer_acc.get(attr, 0.0) + value
        total_payment += extract_total_payment(mio.output)
    stats.per_pricer_total_payment = per_pricer_acc
    stats.total_payment = total_payment
    return stats


__all__ = [
    "run_thread_batch",
    "run_thread_stream",
    "run_process_batch",
    "run_process_stream",
    "finalize_stats",
]

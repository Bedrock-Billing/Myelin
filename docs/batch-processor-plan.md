# Batch Processor for Myelin — Research & Implementation Plan

> **Status:** Researched and scoped, ready to implement. All decisions in §12 are approved defaults.
> **Audience:** Maintainers and contributors returning to this work later.

## 1. Goal

Add a high-quality **batch processing API** to Myelin so that users can process
hundreds to tens of thousands of claims in one call, with configurable
concurrency, per-claim error handling, progress reporting, and a rich summary
result — while keeping the simple case as a single method call.

The two-layer design: a one-liner for the 90% case, a `BatchOptions` object
underneath for the 10% who need full control.

```python
# 90% case — one line
with Myelin() as myelin:
    result = myelin.process_batch(claims)
    print(f"{result.stats.success_count}/{result.stats.total_count} "
          f"({result.stats.claims_per_second:.0f} claims/sec)")

# 10% case — full control
from myelin.batch import BatchOptions, BatchBackend, OnError
result = myelin.process_batch(
    claims,
    options=BatchOptions(
        max_workers=8,
        backend=BatchBackend.PROCESS,
        on_error=OnError.FAIL_FAST,
        progress=True,
        preserve_order=False,
    ),
)
```

## 2. Hard constraint: JPype1 concurrency

The single most important finding from the research: **JPype1 ≥ 1.6.0 is
thread-safe for many Python threads calling into a single shared JVM.**

- **One JVM per process** is the only supported model. `Myelin._setup_jvm()`
  (`myelin/core.py:237-252`) already implements this correctly with a
  class-level `RLock`.
- The Python GIL is **released on every user-defined Java call**, so Python
  threads **do** run in parallel during the Java pricing call (the dominant
  per-claim cost).
- Each Python thread is **auto-attached as a Java daemon thread**.
  `Thread.detach()` is only needed for transient per-call threads, not
  long-lived pool workers.
- **Process pool is technically possible** but requires
  `mp_context=multiprocessing.get_context("spawn")` (Linux default is `fork`,
  which segfaults with JPype), and pays 2-10s JVM startup per worker. Only
  worth it for repeated large batches.
- The CMS pricer `dispatch_obj` is **reentrant-safe** by design — CMS uses the
  same JARs to price tens of millions of claims. Nothing in the per-call path
  mutates shared state.
- **Dominant non-Java per-claim cost:** the SQLite `IPSFProvider.from_claim`
  lookup (`myelin/pricers/ipsf.py:200+`), which currently runs a fresh
  `SELECT` on every claim. **Add an LRU cache in v1** — a one-line
  `@lru_cache(maxsize=256)` keyed on `(provider_ccn, effective_date)`, with an
  invalidation hook for the existing `IPSFDatabase.patch()` update path.

## 3. Existing primitives we can reuse

| What | Where | Reuse |
|---|---|---|
| `Myelin._jvm_lock: RLock` | `myelin/core.py:147` | Sync primitive for "ensure JVM up once per process" |
| `Myelin._jvm_started: bool` | `myelin/core.py:148` | Same — already idempotent |
| `MyelinIO(input, output)` Pydantic model | `myelin/core.py:134-142` | **Already the right shape for the result tuple.** Picklable. |
| `MyelinOutput.error: str \| None` | `myelin/core.py:61, 425, 452, 488, 510, 617` | Already a per-claim error channel. No work needed. |
| `CMSDownloader` `ThreadPoolExecutor(max_workers=4)` | `myelin/helpers/cms_downloader.py:703` | Tuned default precedent |
| `tqdm(desc=..., unit=...)` | used throughout | Progress-bar convention to match |
| `IPSFProvider.from_claim` SQLite lookup | `myelin/pricers/ipsf.py:200+` | **Add LRU cache here as a perf win for batch** |

The missing piece: an executor wrapper that fans work out to
`Myelin.process(claim)` and collects `MyelinIO` results.

## 4. Public API (two layers)

### 4.1 Layer 1 — One-liner (default: thread backend, all defaults)

```python
from myelin import Myelin
from myelin.helpers.claim_examples import claim_example

with Myelin() as myelin:
    claims = [claim_example() for _ in range(10_000)]
    result = myelin.process_batch(claims)
    print(f"{result.stats.success_count}/{result.stats.total_count} succeeded "
          f"({result.stats.claims_per_second:.0f} claims/sec)")
```

### 4.2 Layer 2 — `BatchOptions` for the power users

```python
from myelin.batch import BatchOptions, BatchBackend, OnError

result = myelin.process_batch(
    claims,
    options=BatchOptions(
        max_workers=8,
        backend=BatchBackend.PROCESS,           # cross-process parallelism
        on_error=OnError.FAIL_FAST,             # raise on first non-recoverable error
        progress=True,                          # tqdm
        preserve_order=True,                    # results in submission order (default)
        chunk_size=500,                         # report progress in chunks
    ),
)
```

### 4.3 Streaming variant for pipelines

```python
for mio in myelin.process_stream(claims, options=opts):   # Iterator[MyelinIO]
    if mio.output and mio.output.error is None:
        send_to_downstream(mio)
    else:
        log_failure(mio)
```

### 4.4 Optional helpers

```python
# Iterate in submission order (wrapper that sorts process_stream by index)
def process_in_order(self, claims, options=None) -> Iterator[MyelinIO]: ...
```

## 5. Package layout

```
myelin/
├── batch/
│   ├── __init__.py             # public API: BatchOptions, BatchResult, BatchBackend, OnError
│   ├── options.py              # BatchOptions, BatchBackend, OnError, ProgressStyle
│   ├── result.py               # BatchResult, BatchStats
│   ├── executor.py             # _run_thread_pool, _run_process_pool (lazy worker init)
│   ├── worker.py               # top-level functions picklable for spawn workers
│   └── progress.py             # tqdm wrapper, elapsed-time tracking
├── core.py                     # + Myelin.process_batch / process_stream
└── pricers/
    └── ipsf.py                 # + LRU cache on IPSFProvider.from_claim
```

## 6. `BatchResult` shape

```python
class BatchStats(BaseModel):
    total_count: int
    success_count: int
    failure_count: int
    skipped_count: int = 0            # validation errors before processing
    elapsed_seconds: float
    claims_per_second: float
    per_pricer_total_payment: dict[str, float]   # "ipps" -> 12345.67, "opps" -> 678.90, ...
    total_payment: float
    error_histogram: dict[str, int]   # e.g. {"JavaRuntimeError: 12": 12}

class BatchResult(BaseModel):
    items: list[MyelinIO]                       # all results, in submission order
    stats: BatchStats
    options: BatchOptions
    # Convenience filters
    def succeeded(self) -> list[MyelinIO]: ...
    def failed(self) -> list[MyelinIO]: ...
    def to_excel(self, path: str): ...          # reuses existing exporter
    def to_jsonl(self, path: str): ...
```

## 7. Backend implementation

### 7.1 Thread backend (default)
- `concurrent.futures.ThreadPoolExecutor(max_workers=os.cpu_count() or 1)`.
- Workers auto-attach to the JVM (one-time per thread, negligible).
- No pickling, no startup cost.
- Best for: typical 100-10,000 claim batches on a workstation/server.

### 7.2 Process backend (opt-in)
- `concurrent.futures.ProcessPoolExecutor(mp_context=multiprocessing.get_context("spawn"))`.
- Worker init function: top-level, lazy-creates a `Myelin`, persists it on a
  module-level global inside `myelin/batch/worker.py`.
- **Pre-warm the pool** by sending a no-op claim through each worker at
  startup so the first real claim doesn't pay JVM start cost.
- Best for: long-running daemons, fault-isolated pricing, 10k+ claim batches
  where JVM startup amortizes.

### 7.3 Defaults
- `max_workers` for **thread backend**: `os.cpu_count() or 1`.
- `max_workers` for **process backend**: `min(os.cpu_count() or 1, 4)` — bound
  startup cost.
- `on_error`: `OnError.CONTINUE`.
- `progress`: `True` if `sys.stderr` is a tty, else `False`.
- `preserve_order`: `True` for `process_batch`, `False` for `process_stream`
  (streaming is always completion order; `process_in_order` materializes and
  sorts).
- `backend`: `BatchBackend.THREAD`.
- `chunk_size`: `500`.

### 7.4 Subtle correctness notes
- `MyelinIO` and `MyelinOutput` are Pydantic v2 → picklable for spawn workers.
- `Claim` is Pydantic v2 → picklable.
- `IPSFProvider` and `OPSFProvider` are **not picklable** (they hold a
  SQLAlchemy `Session`); the per-worker init handles this by re-creating them
  in each worker.
- The class-level `Myelin._jvm_lock` and `_jvm_started` flag work correctly
  under fork-via-spawn because each worker is a fresh process with its own
  JVM.

## 8. Error-handling policy

| Error type | `on_error="continue"` (default) | `on_error="fail_fast"` |
|---|---|---|
| `JavaRuntimeError` (already converted to `MyelinOutput.error` by `Myelin.process`) | Record in `MyelinOutput.error`, continue | Raise |
| `ProviderDataError` (already converted to `MyelinOutput.error`) | Record, continue | Raise |
| `pydantic.ValidationError` on the input claim | Record `error` on the `MyelinIO`, continue | Raise |
| `KeyError`, `OSError`, `sqlalchemy.exc.*` (infrastructure) | Raise immediately | Raise immediately |
| Worker crash (process backend) | Mark `mio.output.error = "Worker died: <reason>"`, continue | Propagate as `RuntimeError` |

## 9. Performance optimizations (free wins, include in v1)

1. **Opt-in LRU cache on `IPSFProvider.from_claim`** — **default OFF**.
   Keyed on `(provider_ccn, effective_date)`, size 256. This is the
   dominant Python-side per-claim cost in `Myelin.process`. Implemented
   behind a `Myelin(enable_provider_cache: bool = False)` constructor flag
   so users can opt in when they know their batch hits a small set of
   providers (e.g. re-pricing the same hospital's daily claims). Users
   with high-cardinality `provider_ccn` values (e.g. one claim per
   facility across thousands of facilities) should leave it off to avoid
   wasting memory. The existing `IPSFDatabase.patch()` (`CHANGELOG.md`
   line 12) needs an invalidation hook so the cache stays fresh when the
   underlying provider data is updated.
2. **Pre-warm the process pool**: send a dummy claim through each worker at
   startup so the first real claim doesn't pay JVM start cost.

### 9.1 `enable_provider_cache` constructor signature change

```python
def __init__(
    self,
    build_jar_dirs: bool = True,
    jar_path: str = "./jars",
    db_path: str = "./data/myelin.db",
    build_db: bool = False,
    log_level: int = logging.INFO,
    extra_classpaths: list[str] | None = None,
    db_backend: Literal["sqlite", "postgresql"] = "sqlite",
    enable_provider_cache: bool = False,   # ← new, default off
) -> None:
    ...
    self.enable_provider_cache: bool = enable_provider_cache
    self._provider_cache_info: CacheInfo = CacheInfo(0, 0, 0, 0)  # for diagnostics
```

The flag is read by `IPSFProvider.from_claim` (or a thin wrapper around it)
to decide whether to consult the cache. Expose `Myelin.provider_cache_info()`
as a diagnostic method (returns `functools.CacheInfo`) so users can see the
hit rate and decide whether to leave the cache on.

## 10. What is explicitly NOT in v1 (and why)

| Not in v1 | Why |
|---|---|
| EDI 837/835 file parsers | Mature libraries exist (`pyx12`, `stedi`, `edi-837-parser`); the `Claim` Pydantic model is already the right target. Document the integration point. |
| Async/await API | Adds complexity; thread + sync is plenty for I/O-less CPU-bound work. Could add `asyncio.to_thread` wrapper in a follow-up. |
| Distributed computing (Ray/Dask) | 1-10k claims runs in seconds on a workstation; premature. |
| Persistent queue / checkpointing | Out of scope; user code can wrap the streaming API. |
| CLI command | `myelin-batch input.jsonl output.jsonl` is a 20-line follow-up if requested. |
| `to_dataframe()` | One-liner with pandas; defer the `pandas` dep. v1 ships `to_excel` and `to_jsonl` only. |

## 11. Testing strategy

| Test | What it verifies |
|---|---|
| `test_batch_thread_default.py` | Basic 100-claim run, `BatchResult` shape, success/fail counts. |
| `test_batch_process_backend.py` | Process pool with `spawn`; pre-warm; check pids are distinct. |
| `test_batch_fail_fast.py` | Mix of good and bad claims; verify only the bad ones are reported under `continue`, the right exception under `fail_fast`. |
| `test_batch_streaming.py` | Verify `process_stream` yields in completion order; verify `process_in_order` yields in submission order. |
| `test_batch_progress_disabled.py` | No tqdm output when `progress=False` and `sys.stderr` is not a tty. |
| `test_batch_concurrency_safe.py` | Run N=1000 identical claims; verify no segfault, no cross-contamination (each result equals the serial baseline). |
| `test_batch_ipsf_cache.py` | Verify (a) cache is **off by default** (`enable_provider_cache=False`); (b) when on, hit rate climbs after a batch with repeated `provider_ccn`; (c) `Myelin.provider_cache_info()` reflects the right numbers; (d) `IPSFDatabase.patch()` invalidates the cache. |
| `test_batch_pickle_safe.py` | Verify `MyelinIO` and `MyelinOutput` round-trip through `pickle.dumps`/`pickle.loads` (catches accidental `jpype.JObject` attributes). |

## 12. Decisions (all approved)

### 12.1 Backward compatibility notes

The `Myelin.__init__` signature gains **one new keyword argument**
(`enable_provider_cache: bool = False`) which is fully backward compatible —
all existing call sites continue to work unchanged. The cache being opt-in
means we don't change the default behavior of any existing user code.

| # | Decision | Default |
|---|---|---|
| 1 | Backend default | **`threads` default, `processes` opt-in.** |
| 2 | Default `max_workers` | **`os.cpu_count() or 1` for thread backend; `min(os.cpu_count() or 1, 4)` for process backend.** |
| 3 | Streaming result order | **Expose both** — `process_stream` (completion order, lazy) and `process_in_order` (submission order, materialized). |
| 4 | `process_batch` `preserve_order` default | **True** (matches `Pool.map` semantics). |
| 5 | `IPSFProvider` LRU cache | **Add in v1, but opt-in via `Myelin(enable_provider_cache=False)`.** Users with high-cardinality `provider_ccn` should leave it off. |
| 6 | Package location | **`myelin/batch/` subpackage.** |
| 7 | Public API re-export | **Yes**, re-export `BatchOptions`, `BatchResult`, `BatchBackend`, `OnError` from `myelin/__init__.py`. |
| 8 | CLI command | **No in v1.** |
| 9 | Output formats | **`to_excel` and `to_jsonl` in v1.** `to_dataframe` deferred (avoid `pandas` dep). |
| 10 | EDI 837 parser | **Document-and-defer.** `Claim` Pydantic model is the integration point. |

## 13. Implementation phases

1. **Foundation** — `myelin/batch/options.py` (the dataclass), `result.py`
   (`BatchStats`, `BatchResult`), `__init__.py` (public exports). Small
   Pydantic v2 models.
2. **Exhaustion primitives** — `myelin/batch/progress.py` (tqdm wrapper),
   `executor.py` (thread + process backends with pre-warm).
3. **Worker** — `myelin/batch/worker.py` (top-level picklable function for
   spawn workers, lazy `Myelin` init on module global).
4. **Myelin integration** — add `process_batch`, `process_stream`,
   `process_in_order` methods to `Myelin` in `core.py`.
5. **Performance** — add opt-in LRU cache + invalidation hook to `IPSFProvider`, gated by a new `Myelin(enable_provider_cache: bool = False)` constructor flag. Add `Myelin.provider_cache_info()` diagnostic method.
6. **Re-exports** — update `myelin/__init__.py` for public surface.
7. **Tests** — all 8 tests in §11.
8. **Docs** — add a `docs/batch-processor.md` (smaller than this plan; usage
   only) and a `README.md` section + `example.py` example.

## 14. Key reference URLs

- JPype user guide: https://jpype.readthedocs.io/en/latest/userguide.html
- JPype "Threading" section: https://jpype.readthedocs.io/en/latest/userguide.html#threading
- JPype "Multiprocessing" section: https://jpype.readthedocs.io/en/latest/userguide.html#multiprocessing
- JPype canonical `spawn` recipe: https://github.com/jpype-project/jpype/issues/1024#issuecomment-1132075890
- JPype canonical attach/detach advice: https://github.com/jpype-project/jpype/issues/1169#issuecomment-1910679640
- `concurrent.futures.ThreadPoolExecutor`: https://docs.python.org/3/library/concurrent.futures.html#threadpoolexecutor
- `concurrent.futures.ProcessPoolExecutor`: https://docs.python.org/3/library/concurrent.futures.html#processpoolexecutor
- `multiprocessing.get_context("spawn")`: https://docs.python.org/3/library/multiprocessing.html#multiprocessing.get_context
- spaCy `nlp.pipe(docs, n_process=..., as_tuples=True)`: https://spacy.io/api/language#pipe (ergonomic model the API borrows from)
- Apache cTAKES user guide: https://ctakes.apache.org/userguide.html (stateful-AE pattern)

## 15. Estimated effort

- **Phase 1-3 (foundation + executors + worker):** 1-2 days
- **Phase 4-5 (Myelin integration + IPSF cache):** 1 day
- **Phase 6-7 (re-exports + tests):** 1-2 days
- **Phase 8 (docs):** 0.5 day
- **Total:** ~4-5 days of focused work

## 16. Open follow-ups (post-v1, non-blocking)

- `to_dataframe()` with pandas dep.
- `myelin-batch` CLI entry point.
- Optional `myelin.parsing` subpackage for EDI 837 ingestion (gated behind
  an optional extra, with a parser-library choice left to the user).
- `asyncio` wrapper (`async def process_batch_async`).
- Ray/Dask backend for very large (1M+) claim batches.
- Persistent queue / checkpointing for restartable long batches.

## 17. Implementation follow-ups (added during v1 implementation)

After the original v1 shipped, the following streaming I/O was added because
large RCM data feeds (10k-1M+ claims) exceed comfortable in-memory working sets.

### 17.1 `Myelin.process_jsonl(input_path, output_path, options, ...)`

Stream claims from a JSONL file, process them, and write results to JSONL.

- **Memory:** O(workers). One line is read, one claim is in flight per worker,
  one result line is written at a time. Suitable for arbitrarily large files.
- **Result order:** completion order (not submission order). True streaming
  precludes holding an index-to-result map.
- **Error handling:** malformed JSONL lines can be either recorded as
  `JSONLParseError` placeholder rows in the output (default) or raised
  (with `skip_malformed=False`).
- **Concurrency:** thread pool (`max_workers` honored). Worker threads
  named `myelin-jsonl-N`.
- **Progress:** tqdm with optional `claim_count` parameter for ETA.

```python
from myelin import Myelin
with Myelin() as myelin:
    stats = myelin.process_jsonl(
        "claims_in.jsonl",
        "claims_out.jsonl",
        claim_count=50_000,  # optional, for progress bar ETA
    )
    print(f"{stats.success_count}/{stats.total_count} succeeded")
```

### 17.2 `Myelin.process_csv(input_path, output_path, options, ...)`

Stream claims from a CSV file, process them, and write results to CSV.

- **Input format:** flat rows with dot-notation for nested fields, e.g.
  `principal_dx.code`, `billing_provider.other_id`. Blank cells are skipped.
  A column named `input` whose value is JSON is passed through the JSONL
  path for full MyelinIO-payload support.
- **Output format:** header `claimid, status, error, total_payment` followed
  by per-pricer payment columns (`ipps_payment`, `opps_payment`, etc.).
- **Memory:** O(workers), same as `process_jsonl`.
- **Error handling:** malformed rows recorded as `CSVParseError` placeholders
  (default) or raised (`skip_malformed=False`).
- **Concurrency:** thread pool (`myelin-csv-N`).

```python
with Myelin() as myelin:
    stats = myelin.process_csv("claims_in.csv", "claims_out.csv")
```

### 17.3 `process_stream` is now truly lazy on input

The original `process_stream(claims)` accepted an `Iterable[Claim]` but
internally called `list(claims)` before iterating. The implementation was
refactored so `process_stream` now consumes the input lazily: one claim is
held in flight per worker, and the input iterable is not materialized.

This is what makes `process_jsonl` and `process_csv` actually streaming
(when they delegate to the executor via `process_stream` or a parallel
direct-executor path).

### 17.4 Test coverage for streaming

- `tests/batch/test_process_jsonl.py` — 20 tests covering good claims,
  malformed lines, empty files, blank lines, wrapper format, max_workers,
  ETA via `claim_count`, and per-claim error recording.
- `tests/batch/test_process_jsonl_perf.py` — 6 tests verifying:
  - 2000-claim large file completes correctly
  - throughput exceeds 50 claims/sec
  - **peak memory stays under 50 MB for 1500 claims** (proves the
    streaming claim is real)
  - work is distributed across multiple worker threads
- `tests/batch/test_process_csv.py` — 20 tests covering round-trip,
  nested fields, blank cells, JSON input column, malformed rows,
  empty files, and directory creation.

### 17.5 Test marker: `slow` (added post-v1)

The integration tests in `tests/batch/` that spin up a real `Myelin`
instance take ~3 minutes total to run. A pytest marker system was
added so fast unit tests can be run on their own in CI:

- `pyproject.toml` registers a `slow` marker via
  `[tool.pytest.ini_options].markers`.
- `tests/batch/conftest.py` uses `pytest_collection_modifyitems` to
  automatically apply `@pytest.mark.slow` to any test using a fixture
  that instantiates a real Myelin (`mock_myelin`, `fast_myelin`,
  `myelin_or_skip`). New tests pick up the marker automatically.
- Default `pytest` runs everything (no behavior change).
- `pytest -m "not slow"` skips the JVM integration tests. This brings
  the full test suite from ~3 minutes down to ~12 seconds.
- `pytest -m slow` runs only the integration tests.

```bash
# Fast: 12 seconds, 255 tests
pytest -m "not slow"

# Full: 3 minutes, 310 tests
pytest

# Slow only: 3 minutes, 38 batch tests
pytest -m "slow"
```

### 17.6 Worker-count tuning (added post-v1)

Benchmarking revealed a non-obvious performance characteristic: the CMS
pricing workload is **GIL-bound**. Each `Myelin.process(claim)` call has
significant Python-side work (Pydantic validation, IPSF provider SQLite
lookup, MyelinOutput construction) that does not release the GIL. The
Java pricing call itself is fast (~5-10ms) and does release the GIL,
but the Python work dominates in the default config.

Benchmark results on a 12-core machine, 2000 inpatient claims:

| max_workers | throughput (no cache) | throughput (with cache) |
|------------:|----------------------:|------------------------:|
| 1           | 142 /s                | 345 /s                  |
| **2**       | **363 /s**            | **403 /s**              |
| 4           | 275 /s                | 292 /s                  |
| 8           | 243 /s                | 274 /s                  |

So **2 workers is the sweet spot** for the thread backend, regardless
of CPU count. The default `max_workers` for `BatchBackend.THREAD` was
changed from `os.cpu_count()` to `min(os.cpu_count() or 1, 2)`. Users
with larger fleets can override with `MYELIN_BATCH_MAX_WORKERS=4` (or
whatever) in the environment, or pass `BatchOptions(max_workers=N)`.

The provider cache is the second biggest lever: enabling
`Myelin(enable_provider_cache=True)` when the batch reuses a small set
of providers can roughly double throughput by eliminating the SQLite
IPSF lookup (which is the dominant per-claim Python work in the
default config).

For true parallelism, the **process backend** is the right choice.
Each worker is a separate Python process with its own GIL, so they
truly run in parallel. The trade-off is 2-10 seconds of JVM startup
per worker, which only amortizes over large batches. Default
`max_workers` for `BatchBackend.PROCESS` is `min(os.cpu_count(), 4)`.

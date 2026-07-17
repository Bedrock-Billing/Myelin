from __future__ import annotations

import os

from myelin.core import Myelin, MyelinIO, MyelinOutput
from myelin.input.claim import Claim


_WORKER_MYELIN: Myelin | None = None


def _init_worker(jar_path: str, db_path: str, build_db: bool) -> None:
    global _WORKER_MYELIN
    if _WORKER_MYELIN is None:
        _WORKER_MYELIN = Myelin(
            build_jar_dirs=False,
            jar_path=jar_path,
            db_path=db_path,
            build_db=build_db,
        )
        _WORKER_MYELIN.setup_clients()


def process_one(args: tuple[Claim, str, str, bool]) -> MyelinIO:
    claim, jar_path, db_path, build_db = args
    _init_worker(jar_path, db_path, build_db)
    assert _WORKER_MYELIN is not None
    try:
        output: MyelinOutput = _WORKER_MYELIN.process(claim)
    except Exception as exc:
        output = MyelinOutput(error=f"{type(exc).__name__}: {exc}")
    return MyelinIO(input=claim, output=output)


def process_chunk(args: tuple[list[Claim], str, str, bool]) -> list[MyelinIO]:
    claims, jar_path, db_path, build_db = args
    _init_worker(jar_path, db_path, build_db)
    assert _WORKER_MYELIN is not None
    results: list[MyelinIO] = []
    for claim in claims:
        try:
            output: MyelinOutput = _WORKER_MYELIN.process(claim)
        except Exception as exc:
            output = MyelinOutput(error=f"{type(exc).__name__}: {exc}")
        results.append(MyelinIO(input=claim, output=output))
    return results


def worker_process_claim(claim: Claim) -> MyelinIO:
    jar_path = os.environ.get("MYELIN_JAR_PATH", "./jars")
    db_path = os.environ.get("MYELIN_DB_PATH", "./data/myelin.db")
    build_db = os.environ.get("MYELIN_BUILD_DB", "0") == "1"
    return process_one((claim, jar_path, db_path, build_db))


__all__ = [
    "process_one",
    "process_chunk",
    "worker_process_claim",
    "_init_worker",
]

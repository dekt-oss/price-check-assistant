"""Compare the Track B price search with and without the substring side index.

Runs a fixed list of real searches against one local serving SQLite file twice: once forced onto
the original full-scan queries and once through the side index. For each it reports whether the
results are identical, how many bytes the process read, which path each substring query took, and
every SQL statement whose plan scans ``track_b_delivery_lines`` without an index.

    PYTHONPATH=src python -m purchase_price.scripts.audit_track_b_search_index --index <file.sqlite>

Bytes read come from the operating system's per-process I/O counter (psutil), so they include
every page SQLite asked for, whether or not the OS had it cached.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from purchase_price.schemas import ProductQuery
from purchase_price.services import category_market
from purchase_price.services import track_b_search_index as search_index
from purchase_price.services.track_b_db_quote_comparison import (
    compare_track_b_models_batch,
    compare_track_b_quote,
)
from purchase_price.services.track_b_live_gap_fill import indexed_detail_codes
from purchase_price.services.track_b_reference_quality import refine_track_b_reference_quality
from purchase_price.services.track_b_supplier_summary import supplier_trade_summary

WORKSPACE_LOOKUP_LIMIT = 500


def _lookup(query: ProductQuery) -> Callable[[Session], Any]:
    def run(session: Session) -> Any:
        # Same calls as TrackBServingSnapshot.lookup (the workspace search).
        result = compare_track_b_quote(
            session, query, quote_unit_price=None, limit=WORKSPACE_LOOKUP_LIMIT
        )
        return refine_track_b_reference_quality(session, query, result)

    return run


def _supplier(name: str) -> Callable[[Session], Any]:
    return lambda session: supplier_trade_summary(session, name)


def _models(models: tuple[str, ...], product: str = "") -> Callable[[Session], Any]:
    queries = tuple(ProductQuery(product_name=product, model_name=model) for model in models)
    return lambda session: compare_track_b_models_batch(session, queries, limit_per_model=500)


def _detail_codes(model: str) -> Callable[[Session], Any]:
    return lambda session: indexed_detail_codes(session, ProductQuery(model_name=model))


def _category(product: str) -> Callable[[Session], Any]:
    def run(session: Session) -> Any:
        codes = category_market.resolve_detail_codes(session, (product,))
        return category_market.load_category_trades(session, [code.code for code in codes])

    return run


DEFIBRILLATOR_MODELS = (
    "HeartOn A16-DS",
    "HeartOn A16-DF",
    "HeartOn A16-GS",
    "HeartOn A16-OS",
    "NT-381.C",
    "NT-381.B",
    "NT-381.G",
    "NT-381.AI",
    "NT-381.M",
    "NT-381",
    "Efficia DFM100",
)
MEDIANA_MODELS = (
    "HeartOn A16-DS",
    "MECASE-S",
    "HeartOn A16-DF",
    "MECASE-W",
    "i25",
    "HeartOn A16-GS",
    "i35",
    "HeartOn A16-OS",
)

# (label, step) - single lookups used for the results-equivalence table.
EQUIVALENCE_CASES: tuple[tuple[str, Callable[[Session], Any]], ...] = (
    ("HeartOn A16-DS / 저출력심장충격기", _lookup(ProductQuery("저출력심장충격기", "", "HeartOn A16-DS"))),
    ("Efficia DFM100 / 저출력심장충격기", _lookup(ProductQuery("저출력심장충격기", "", "Efficia DFM100"))),
    ("DFM100 (model only)", _lookup(ProductQuery(model_name="DFM100"))),
    ("Flow-c (model only)", _lookup(ProductQuery(model_name="Flow-c"))),
    ("Flow-c (model probe)", _lookup(ProductQuery(product_name="Flow-c", model_name="Flow-c"))),
    (
        "FLOW-C / 가스 마취기(Anesthesia Machine) (sync smoke)",
        _lookup(ProductQuery("가스 마취기(Anesthesia Machine)", "Maquet", "FLOW-C", "Flow-C")),
    ),
    ("NT-381.B / 저출력심장충격기", _lookup(ProductQuery("저출력심장충격기", "", "NT-381.B"))),
    ("NT-381.Z (typo) / 저출력심장충격기", _lookup(ProductQuery("저출력심장충격기", "", "NT-381.Z"))),
    ("가스마취기 (product only)", _lookup(ProductQuery(product_name="가스마취기"))),
    ("가스 마취기 (two words)", _lookup(ProductQuery(product_name="가스 마취기"))),
    ("저출력 심장 충격기 + HeartOn Z99", _lookup(ProductQuery("저출력 심장 충격기", "", "HeartOn Z99"))),
    ("환자감시장치 (product only)", _lookup(ProductQuery(product_name="환자감시장치"))),
    ("Fabius plus / 가스마취기", _lookup(ProductQuery("가스마취기", "", "Fabius plus"))),
    ("AB_12 (LIKE wildcard) / 수액세트", _lookup(ProductQuery("수액세트", "", "AB_12"))),
    ("M3 (two-character model)", _lookup(ProductQuery(model_name="M3"))),
    ("Flow Cytometer (English product)", _lookup(ProductQuery(product_name="Flow Cytometer"))),
    ("Attune NxT / 세포분석기", _lookup(ProductQuery("세포분석기", "", "Attune NxT"))),
    ("메디아나 (company typed as model)", _lookup(ProductQuery(product_name="메디아나", model_name="메디아나"))),
    ("supplier (주)메디아나", _supplier("(주)메디아나")),
    ("supplier 나눔테크", _supplier("나눔테크")),
    ("supplier 씨에스메디칼 주식회사", _supplier("씨에스메디칼 주식회사")),
    ("supplier GE (two characters)", _supplier("GE")),
    ("supplier 나눔_크 (LIKE wildcard)", _supplier("나눔_크")),
    ("supplier 주식회사 케이 (needle 케이, very common)", _supplier("주식회사 케이")),
)


@dataclass(frozen=True)
class Search:
    label: str
    steps: tuple[Callable[[Session], Any], ...]


# The SQL the dashboard runs for the six searches named in the 2026-10-09 memory incident.
TYPICAL_SEARCHES = (
    Search(
        "HeartOn A16-DS",
        (
            _lookup(ProductQuery("저출력심장충격기", "", "HeartOn A16-DS")),
            _detail_codes("HeartOn A16-DS"),
            _models(DEFIBRILLATOR_MODELS, "저출력심장충격기"),
            _category("저출력심장충격기"),
        ),
    ),
    Search(
        "DFM100",
        (
            _lookup(ProductQuery(model_name="DFM100")),
            _lookup(ProductQuery(product_name="DFM100", model_name="DFM100")),
            _detail_codes("DFM100"),
        ),
    ),
    Search(
        "Flow-c",
        (
            _lookup(ProductQuery(model_name="Flow-c")),
            _lookup(ProductQuery(product_name="Flow-c", model_name="Flow-c")),
            _detail_codes("Flow-c"),
        ),
    ),
    Search(
        "NT-381.B",
        (
            _lookup(ProductQuery("저출력심장충격기", "", "NT-381.B")),
            _detail_codes("NT-381.B"),
            _models(DEFIBRILLATOR_MODELS, "저출력심장충격기"),
            _category("저출력심장충격기"),
        ),
    ),
    Search("메디아나", (_models(MEDIANA_MODELS), _supplier("(주)메디아나"))),
    Search(
        "가스마취기",
        (_lookup(ProductQuery(product_name="가스마취기")), _category("가스마취기")),
    ),
)


SQLITE_CACHE_KIB = 0  # 0 = SQLite's default 2 MB page cache (what the app uses)


def _open(path: Path, *, legacy: bool) -> tuple[Any, Session, list[tuple[str, Any]]]:
    engine = create_engine(f"sqlite+pysqlite:///{path}", connect_args={"check_same_thread": False})
    statements: list[tuple[str, Any]] = []

    if SQLITE_CACHE_KIB:
        # A page cache larger than anything one search touches: every page is read from the file
        # once, so the bytes read equal the distinct file pages the search needs.
        @event.listens_for(engine, "connect")
        def _cache(dbapi_connection, _record):
            dbapi_connection.execute(f"PRAGMA cache_size=-{SQLITE_CACHE_KIB}")

    @event.listens_for(engine, "before_cursor_execute")
    def _capture(_conn, _cursor, statement, parameters, _context, _executemany):
        statements.append((statement, parameters))

    session = Session(bind=engine, autoflush=False, expire_on_commit=False)
    if legacy:
        search_index.use_legacy_queries(session)
    return engine, session, statements


def _bytes_read() -> int:
    import psutil  # audit-only dependency

    counters = psutil.Process().io_counters()
    # Linux: read_chars counts page-cache hits too (read_bytes only counts disk reads).
    return int(getattr(counters, "read_chars", counters.read_bytes))


def _run(path: Path, steps, *, legacy: bool) -> dict[str, Any]:
    engine, session, statements = _open(path, legacy=legacy)
    try:
        before = _bytes_read()
        results = [step(session) for step in steps]
        read_bytes = _bytes_read() - before
        paths = list(session.info.get(search_index.PATHS_KEY, []))
    finally:
        session.close()
    scans = _full_scans(engine, statements)
    engine.dispose()
    return {
        "results": results,
        "read_bytes": read_bytes,
        "paths": paths,
        "scans": scans,
        "statements": len(statements),
    }


def _full_scans(engine, statements: list[tuple[str, Any]]) -> list[str]:
    scans: list[str] = []
    with engine.connect() as connection:
        raw = connection.connection.driver_connection
        for statement, parameters in statements:
            if not statement.lstrip().upper().startswith("SELECT"):
                continue
            if " WHERE " not in statement and tuple(parameters or ()) == (1, 0):
                continue  # "is the table empty?" probe: stops at the first row

            plan = raw.execute(f"EXPLAIN QUERY PLAN {statement}", parameters or ()).fetchall()
            for row in plan:
                detail = str(row[-1])
                if detail.startswith("SCAN track_b_delivery_lines") or detail == "SCAN track_b_delivery_lines":
                    scans.append(" ".join(statement.split())[:160])
                    break
    return scans


def _summary(result: Any) -> str:
    if isinstance(result, dict):
        return f"{result.get('status')} trades={result.get('trade_count')}"
    status = getattr(result, "status", None)
    if status is not None:
        return (
            f"{status} direct={len(result.candidates)} refs={len(result.reference_candidates)}"
            f" suggest={len(result.suggestions)}"
        )
    return type(result).__name__


def _mb(value: int) -> str:
    return f"{value / 1_000_000:,.1f}"


def _warm_up(path: Path) -> None:
    # Imports and one-time file reads (aliases, mappings) must not count against the first case.
    for _label, step in EQUIVALENCE_CASES[:1]:
        _run(path, (step,), legacy=False)


def audit(path: Path, *, skip_legacy_searches: bool = False) -> dict[str, Any]:
    _warm_up(path)
    equivalence = []
    for label, step in EQUIVALENCE_CASES:
        legacy = _run(path, (step,), legacy=True)
        indexed = _run(path, (step,), legacy=False)
        same = legacy["results"] == indexed["results"]
        equivalence.append(
            {
                "case": label,
                "identical": same,
                "result": _summary(indexed["results"][0]),
                "legacy_mb": _mb(legacy["read_bytes"]),
                "index_mb": _mb(indexed["read_bytes"]),
                "index_paths": indexed["paths"],
                "index_full_scans": indexed["scans"],
            }
        )
        print(
            f"{'OK ' if same else 'DIFF'} | {label} | {_summary(indexed['results'][0])} | "
            f"legacy {_mb(legacy['read_bytes'])} MB | index {_mb(indexed['read_bytes'])} MB | "
            f"paths {indexed['paths']} | full scans {len(indexed['scans'])}",
            flush=True,
        )
    searches = []
    for search in TYPICAL_SEARCHES:
        indexed = _run(path, search.steps, legacy=False)
        legacy = None if skip_legacy_searches else _run(path, search.steps, legacy=True)
        row = {
            "search": search.label,
            "index_mb": _mb(indexed["read_bytes"]),
            "index_statements": indexed["statements"],
            "index_full_scans": indexed["scans"],
            "legacy_mb": _mb(legacy["read_bytes"]) if legacy else None,
            "legacy_full_scans": legacy["scans"] if legacy else None,
            "identical": (legacy["results"] == indexed["results"]) if legacy else None,
        }
        searches.append(row)
        print(
            f"SEARCH {search.label} | legacy {row['legacy_mb']} MB "
            f"({len(row['legacy_full_scans'] or [])} full scans) | index {row['index_mb']} MB "
            f"({len(row['index_full_scans'])} full scans) | identical {row['identical']}",
            flush=True,
        )
    return {
        "index": str(path),
        "file_mb": _mb(path.stat().st_size),
        "search_index_ready": _ready(path),
        "equivalence": equivalence,
        "all_identical": all(row["identical"] for row in equivalence)
        and all(row["identical"] in {True, None} for row in searches),
        "typical_searches": searches,
    }


def _ready(path: Path) -> bool:
    engine, session, _statements = _open(path, legacy=False)
    try:
        return search_index.search_index_ready(session)
    finally:
        session.close()
        engine.dispose()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--index", type=Path, required=True, help="local serving SQLite file")
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--skip-legacy-searches", action="store_true")
    parser.add_argument(
        "--distinct-pages",
        action="store_true",
        help="use a 1 GB SQLite page cache so bytes read = distinct file pages touched",
    )
    args = parser.parse_args()
    if args.distinct_pages:
        global SQLITE_CACHE_KIB
        SQLITE_CACHE_KIB = 1024 * 1024
    report = audit(args.index, skip_legacy_searches=args.skip_legacy_searches)
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "equivalence"}, ensure_ascii=False, indent=2))
    return 0 if report["all_identical"] else 1


if __name__ == "__main__":
    sys.exit(main())

"""The substring side index must return exactly what the original full-scan queries returned."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from purchase_price.db import Base
from purchase_price.models import TrackBDeliveryLine
from purchase_price.schemas import ProductQuery
from purchase_price.services import track_b_search_index as search_index
from purchase_price.services import track_b_supplier_summary
from purchase_price.services.matching import normalize_text
from purchase_price.services.track_b_db_quote_comparison import compare_track_b_quote
from purchase_price.services.track_b_reference_quality import refine_track_b_reference_quality
from purchase_price.ui import memory_diagnostic


def _line(
    number: int,
    *,
    title: str,
    product_class: str,
    model: str | None,
    supplier: str,
    when: date | None,
    price: str | None = "1000000",
    quantity: str = "1",
    change: int = 0,
    request: str | None = None,
    conflict: bool = False,
) -> TrackBDeliveryLine:
    request = request or f"R{number:04d}"
    return TrackBDeliveryLine(
        delivery_request_number=request,
        change_order=f"{change:02d}",
        change_order_number=change,
        product_sequence="1",
        item_sha256=f"{number:064d}",
        identity_conflict=conflict,
        identity_conflict_count=1 if conflict else 0,
        raw_object_key=f"raw/{request}.json.gz",
        raw_payload_sha256="b" * 64,
        detail_code="4217210101",
        product_id=None,
        product_title=title,
        product_class=product_class,
        class_key=normalize_text(product_class) or None,
        manufacturer=None,
        manufacturer_qualifier=None,
        model_name=model,
        model_qualifier=None,
        model_qualifier_verified_as_origin=False,
        model_key=normalize_text(model) or None,
        specification=None,
        unit_price=Decimal(price) if price is not None else None,
        quantity=Decimal(quantity),
        unit="EA",
        total_amount=Decimal(price or "500000") * Decimal(quantity),
        amount_check="consistent",
        transaction_date=when,
        supplier=supplier,
        demand_institution=f"기관{number % 5}",
        api_params_json="{}",
    )


def _lines() -> list[TrackBDeliveryLine]:
    lines: list[TrackBDeliveryLine] = []
    number = 0
    templates = [
        ("저출력심장충격기, 메디아나, HeartOn A16-DS, 170J", "저출력심장충격기", "HeartOn A16-DS", "(주)메디아나"),
        ("저출력심장충격기, 나눔테크, NT-381.B, 50J", "저출력심장충격기", "NT-381.B", "(주)나눔테크"),
        ("저출력심장충격기, 나눔테크, NT-381.C, 50J", "저출력심장충격기", "NT-381.C", "나눔테크 대리점"),
        ("가스마취기, 드래거, Fabius plus", "가스마취기", "Fabius plus", "씨에스메디칼 주식회사"),
        ("세포분석기, Agilent, NovoCyte Flow cytometer", "세포분석기", "NovoCyte Flow cytometer", "대명과학상사"),
        ("혈류계, Flow-c 프로브 세트", "혈류계", None, "GE헬스케어코리아"),
        ("교육용모형, 인체 심장", "교육용모형", "HM-1", "지이메디칼"),
        ("의료용 모형, 심장", "의료용모형", "Z9", "에이"),
        ("저출력 심장 충격기 보관함, MECASE-S", "보관함", "MECASE-S", "(주)메디아나"),
    ]
    for round_index in range(4):
        for title, product_class, model, supplier in templates:
            number += 1
            when = date(2021 + round_index, 1 + number % 12, 1 + number % 27)
            lines.append(
                _line(
                    number,
                    title=title,
                    product_class=product_class,
                    model=model,
                    supplier=supplier,
                    when=None if number % 17 == 0 else when,
                    price=None if number % 11 == 0 else str(1_000_000 + number * 1000),
                )
            )
    # Same date as another row: the id must break the tie in both paths.
    lines.append(_line(900, title="혈류계, Flow-c 본체", product_class="혈류계", model=None,
                       supplier="GE헬스케어코리아", when=date(2024, 3, 3)))
    lines.append(_line(901, title="혈류계, Flow-c 본체", product_class="혈류계", model=None,
                       supplier="GE헬스케어코리아", when=date(2024, 3, 3)))
    # A later change order supersedes (and cancels, quantity 0) the first one.
    lines.append(_line(902, title="혈류계, Flow-c 취소", product_class="혈류계", model=None,
                       supplier="GE헬스케어코리아", when=date(2025, 5, 5), request="RCANCEL"))
    lines.append(_line(903, title="혈류계, Flow-c 취소", product_class="혈류계", model=None,
                       supplier="GE헬스케어코리아", when=date(2025, 5, 6), request="RCANCEL",
                       change=1, quantity="0"))
    lines.append(_line(904, title="혈류계, Flow-c 충돌", product_class="혈류계", model=None,
                       supplier="GE헬스케어코리아", when=date(2025, 6, 6), conflict=True))
    return lines


QUERIES = (
    ProductQuery(model_name="Flow-c"),
    ProductQuery(product_name="Flow-c", model_name="Flow-c"),
    ProductQuery(product_name="저출력 심장 충격기", model_name="HeartOn Z99"),
    ProductQuery(product_name="저출력심장충격기", model_name="NT-381.Z"),
    ProductQuery(product_name="심장"),
    ProductQuery(product_name="flow cytometer"),
    ProductQuery(model_name="A"),  # one character: the original query runs
    ProductQuery(product_name="수액세트", model_name="NT_381"),  # LIKE wildcard in the needle
    ProductQuery(product_name="없는품목", model_name="없는모델"),
)
SUPPLIERS = ("(주)메디아나", "나눔테크", "GE", "나눔_크", "지이", "없는회사")


def _results(session: Session) -> tuple[list[object], list[object]]:
    lookups = []
    for query in QUERIES:
        result = compare_track_b_quote(session, query, quote_unit_price=None, limit=500)
        lookups.append((result, refine_track_b_reference_quality(session, query, result)))
    summaries = [
        track_b_supplier_summary.supplier_trade_summary(session, name) for name in SUPPLIERS
    ]
    return lookups, summaries


@pytest.fixture()
def serving_file(tmp_path: Path) -> Path:
    path = tmp_path / "serving.sqlite"
    engine = create_engine(f"sqlite+pysqlite:///{path}")
    Base.metadata.create_all(engine, tables=[TrackBDeliveryLine.__table__])
    with Session(engine) as session, session.begin():
        session.add_all(_lines())
    engine.dispose()
    return path


def _session(path: Path) -> tuple[object, Session]:
    engine = create_engine(f"sqlite+pysqlite:///{path}")
    return engine, Session(bind=engine, autoflush=False, expire_on_commit=False)


def _build(path: Path) -> dict[str, int]:
    engine = create_engine(f"sqlite+pysqlite:///{path}")
    with engine.begin() as connection:
        report = search_index.ensure_search_index(connection)
    engine.dispose()
    return report


def _legacy_and_indexed(path: Path):
    engine, legacy_session = _session(path)
    search_index.use_legacy_queries(legacy_session)
    legacy = _results(legacy_session)
    legacy_session.close()
    engine.dispose()
    engine, session = _session(path)
    indexed = _results(session)
    paths = list(session.info.get(search_index.PATHS_KEY, []))
    session.close()
    engine.dispose()
    return legacy, indexed, paths


def test_side_index_returns_exactly_the_original_results(serving_file: Path, monkeypatch) -> None:
    engine, before_session = _session(serving_file)
    assert search_index.search_index_ready(before_session) is False  # an older file: no index
    before = _results(before_session)
    before_session.close()
    engine.dispose()

    report = _build(serving_file)
    assert report["created"] == 1 and report["indexed_rows"] == len(_lines())
    monkeypatch.setattr(search_index, "FETCH_BATCH", 2)  # several follow-up batches per query

    legacy, indexed, paths = _legacy_and_indexed(serving_file)

    assert legacy == before
    assert indexed == legacy
    assert "index" in paths
    # Only the one-character model needle needs the original full-scan query.
    assert paths.count("legacy") == 1
    lookups, summaries = indexed
    _raw, flow_c = lookups[0]
    assert flow_c.status == "success_0" and flow_c.reference_candidates
    # The superseded change order stays hidden in both paths (only the latest one counts).
    assert "delivery:RCANCEL|change:00|line:1" not in {
        ref.source_record_id for ref in flow_c.reference_candidates
    }
    heart, _refined = lookups[4]  # "심장": two characters, also at the very end of a title
    assert "의료용 모형, 심장" in {ref.product_title for ref in heart.reference_candidates}
    assert summaries[0]["status"] == "success" and summaries[1]["trade_count"] > 0


def test_supplier_cut_keeps_the_full_scan_row_order(serving_file: Path, monkeypatch) -> None:
    _build(serving_file)
    monkeypatch.setattr(track_b_supplier_summary, "CANDIDATE_LIMIT", 3)
    monkeypatch.setattr(search_index, "FETCH_BATCH", 2)

    engine, legacy_session = _session(serving_file)
    search_index.use_legacy_queries(legacy_session)
    legacy = track_b_supplier_summary.supplier_trade_summary(legacy_session, "메디아나")
    legacy_session.close()
    engine.dispose()
    engine, session = _session(serving_file)
    indexed = track_b_supplier_summary.supplier_trade_summary(session, "메디아나")
    session.close()
    engine.dispose()

    assert legacy["truncated"] is True
    assert indexed == legacy


def test_index_behind_the_table_is_ignored_until_the_sync_catches_up(serving_file: Path) -> None:
    _build(serving_file)
    engine, session = _session(serving_file)
    with session.begin():
        session.add(
            _line(950, title="혈류계, Flow-c 신규", product_class="혈류계", model=None,
                  supplier="GE헬스케어코리아", when=date(2026, 9, 9))
        )
    session.close()
    engine.dispose()

    engine, stale = _session(serving_file)
    assert search_index.search_index_ready(stale) is False  # an older sync added rows only
    stale.close()
    engine.dispose()

    report = _build(serving_file)
    assert report == {"created": 0, "added": 1, "indexed_rows": len(_lines()) + 1}
    assert _build(serving_file)["added"] == 0

    legacy, indexed, paths = _legacy_and_indexed(serving_file)
    assert indexed == legacy and "index" in paths
    assert any(
        ref.product_title == "혈류계, Flow-c 신규" for ref in indexed[0][0][1].reference_candidates
    )


def test_candidate_ids_are_a_superset_of_like_matches(serving_file: Path) -> None:
    _build(serving_file)
    engine, session = _session(serving_file)
    raw = session.connection().connection.driver_connection

    def like_ids(column: str, needle: str) -> set[int]:
        return {
            row[0]
            for row in raw.execute(
                f"SELECT id FROM track_b_delivery_lines WHERE {column} LIKE ?", (f"%{needle}%",)
            )
        }

    for column, needle in [
        ("product_title", "flow-c"),
        ("product_title", "FLOW-C"),
        ("product_title", "심장"),
        ("product_title", "j"),  # one character: not indexable
        ("supplier", "ge"),
        ("supplier", "나눔_크"),
        ("model_key", "nt381"),
        ("class_key", "충격기"),
    ]:
        ids = search_index.candidate_ids(
            session, search_index.Contains(column, needle), order="id"
        )
        if len(needle) == 1:
            assert ids is None
            continue
        assert ids is not None and like_ids(column, needle) <= set(ids), (column, needle)
    assert search_index.candidate_ids(
        session, search_index.Contains("supplier", "없는회사"), order="recent"
    ) == []
    session.close()
    engine.dispose()


def test_postgres_or_unindexed_sessions_use_the_original_queries(tmp_path: Path) -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine, tables=[TrackBDeliveryLine.__table__])
    with Session(engine) as session:
        assert search_index.search_index_ready(session) is False
        assert (
            search_index.candidate_ids(
                session, search_index.Contains("supplier", "메디아나"), order="id"
            )
            is None
        )
    engine.dispose()


def test_runtime_reports_sqlite_search_support() -> None:
    version, supported = search_index.sqlite_search_support()
    assert version.count(".") == 2
    assert supported is True  # FTS5 trigram needs SQLite >= 3.34
    snapshot = memory_diagnostic.take_snapshot()
    assert "부분검색 색인 사용 가능" in memory_diagnostic.format_snapshot(snapshot)

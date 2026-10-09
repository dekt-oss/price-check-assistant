from __future__ import annotations

import importlib

from purchase_price.services import track_b_r2_quote_index


def test_track_b_snapshot_adapter_imports_when_loaded_legacy_module_lacks_new_opener(
    monkeypatch,
) -> None:
    monkeypatch.delattr(
        track_b_r2_quote_index,
        "open_track_b_serving_snapshot",
        raising=False,
    )

    module = importlib.import_module(
        "purchase_price.services.track_b_serving_snapshot"
    )

    assert callable(module.open_track_b_serving_snapshot)
    assert module._native_snapshot_opener() is None


def test_dashboard_uses_hot_reload_safe_track_b_snapshot_adapter() -> None:
    from pathlib import Path

    source = Path("pages/1_대시보드.py").read_text(encoding="utf-8")

    assert (
        "from purchase_price.services import track_b_serving_snapshot as track_b_snapshot_service"
    ) in source
    assert (
        "from purchase_price.services.track_b_r2_quote_index "
        "import open_track_b_serving_snapshot"
    ) not in source


def test_snapshot_falls_back_when_loaded_db_module_lacks_batch_lookup(monkeypatch) -> None:
    from types import SimpleNamespace

    from purchase_price.schemas import ProductQuery
    from purchase_price.services import track_b_db_quote_comparison
    from purchase_price.services.track_b_serving_snapshot import TrackBServingSnapshot

    monkeypatch.delattr(
        track_b_db_quote_comparison,
        "compare_track_b_models_batch",
        raising=False,
    )
    calls: list[tuple[str, object, int]] = []

    def fake_compare(_session, query, *, quote_unit_price, limit):
        calls.append((query.model_name, quote_unit_price, limit))
        return SimpleNamespace(status="success_0", candidates=())

    monkeypatch.setattr(
        track_b_db_quote_comparison,
        "compare_track_b_quote",
        fake_compare,
    )
    snapshot = TrackBServingSnapshot(status="available", session=object())
    queries = (
        ProductQuery(product_name="품목", model_name="MODEL-A"),
        ProductQuery(product_name="품목", model_name="MODEL-B"),
    )

    results = snapshot.lookup_model_summaries(
        queries,
        quote_unit_prices=(None, None),
        limit_per_model=50,
    )

    assert len(results) == 2
    assert calls == [
        ("MODEL-A", None, 50),
        ("MODEL-B", None, 50),
    ]


def test_dashboard_reloads_retained_pre_fix_track_b_modules() -> None:
    from pathlib import Path

    from purchase_price.services import track_b_db_quote_comparison, track_b_live_gap_fill
    from purchase_price.services import track_b_serving_snapshot as snapshot

    source = Path("pages/1_대시보드.py").read_text(encoding="utf-8")
    assert "snapshot_runtime, live_runtime = _track_b_runtime()" in source
    assert "with snapshot_runtime.open_track_b_serving_snapshot() as track_b_snapshot:" in source
    assert "merge_live_gap = live_runtime.merge_live_gap" in source
    # The markers the guard checks must exist in the current modules.
    assert hasattr(track_b_db_quote_comparison, "_not_cancelled_clause")
    assert hasattr(snapshot, "WORKSPACE_LOOKUP_LIMIT")
    assert track_b_live_gap_fill.DROPS_CANCELLED_LINES is True


def test_dashboard_reloads_pre_search_index_modules_in_dependency_order() -> None:
    """#329 changed three lookup modules; a stale process must reload them (helper first)."""

    from pathlib import Path

    from purchase_price.services import (
        track_b_db_quote_comparison,
        track_b_reference_quality,
        track_b_search_index,
        track_b_supplier_summary,
    )
    from purchase_price.ui import memory_diagnostic

    for module in (
        track_b_search_index,
        track_b_db_quote_comparison,
        track_b_reference_quality,
        track_b_supplier_summary,
        memory_diagnostic,
    ):
        assert module.SEARCH_INDEX_V1 is True

    source = Path("pages/1_대시보드.py").read_text(encoding="utf-8")
    entries = [
        '(track_b_search_index_service, "SEARCH_INDEX_V1")',
        '(track_b_comparison_service, "SEARCH_INDEX_V1")',
        '(track_b_reference_quality_service, "SEARCH_INDEX_V1")',
        '(supplier_summary_service, "SEARCH_INDEX_V1")',
    ]
    positions = [source.index(entry) for entry in entries]
    assert positions == sorted(positions)
    assert positions[0] > source.index("_TRACK_B_RUNTIME_MARKERS = (")

    home = Path("Home.py").read_text(encoding="utf-8")
    assert 'if not hasattr(memory_diagnostic, "SEARCH_INDEX_V1"):' in home


def test_native_snapshot_lookup_reads_beyond_50_rows(tmp_path) -> None:
    """The workspace opens the native snapshot; its lookup must use the 5,000-row limit."""

    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from purchase_price.models import Base
    from purchase_price.schemas import ProductQuery
    from purchase_price.services import track_b_r2_quote_index as native
    from purchase_price.services.g2b_track_b_normalization import TrackBRawPage
    from purchase_price.services.track_b_db_quote_comparison import ingest_track_b_page

    items = [
        {
            "cntrctDlvrReqNo": f"R{n}",
            "cntrctDlvrReqChgOrd": "00",
            "prdctSno": "1",
            "dtilPrdctClsfcNo": "4217210101",
            "prdctIdntNoNm": "저출력심장충격기, 나눔테크, NT-SG, 보관함",
            "prdctUprc": "396000",
            "prdctQty": "1",
            "prdctAmt": "396000",
            "cntrctDlvrReqDate": "20260901",
            "corpNm": "(주)나눔테크",
            "dminsttNm": f"기관{n}",
        }
        for n in range(60)
    ]
    page = TrackBRawPage(
        payload={
            "schema": "g2b-track-b-page-v1",
            "operation": "getSpcifyPrdlstPrcureInfoList",
            "request": {
                "detail_code": "4217210101",
                "begin_date": "2025-09-12",
                "end_date": "2026-09-11",
                "page_no": 1,
                "page_size": 999,
                "final_change_order_filter": "OMITTED",
            },
            "response": {"items": items},
        },
        raw_object_key="raw/v1/getSpcifyPrdlstPrcureInfoList-page/test.json.gz",
        raw_payload_sha256="a" * 64,
    )
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'i.sqlite'}")
    Base.metadata.create_all(engine)
    session = Session(bind=engine)
    ingest_track_b_page(session, page)
    session.commit()
    snapshot = native.TrackBServingSnapshot(status="available", engine=engine, session=session)

    result = snapshot.lookup(ProductQuery(product_name="", model_name="NT-SG"), quote_unit_price=None)

    assert native.WORKSPACE_LOOKUP_LIMIT == 5_000
    assert len(result.candidates) == 60
    session.close()
    engine.dispose()

from __future__ import annotations

from pathlib import Path

import pytest

from purchase_price.services.g2b_bulk_csv import (
    BulkCsvContractError,
    build_gap_plan,
    detect_csv_encoding,
    ingest_bulk_csv,
)
from purchase_price.storage.r2 import RawObjectRef, payload_sha256


class FakeStore:
    def __init__(self) -> None:
        self.payloads: list[object] = []

    def put_public_json(self, *, source_operation: str, payload: object) -> RawObjectRef:
        self.payloads.append(payload)
        digest, canonical = payload_sha256(payload)
        return RawObjectRef(
            bucket="price-check-raw",
            key=f"raw/v1/{source_operation}/{digest}.json.gz",
            payload_hash=digest,
            uncompressed_bytes=len(canonical),
            stored_bytes=max(1, len(canonical) // 2),
            created=True,
        )


def _write_sample(path: Path, *, encoding: str = "utf-8-sig") -> None:
    content = (
        "결재일자,세부품명,납품요구번호,납품요구변경차수,납품요구물품순번,납품단가,업체\n"
        "2026-09-10,4227250101,REQ-1,0,1,100000,의료업체\n"
        "2026-09-09,4321150301,REQ-2,1,2,1200000,전산업체\n"
        "2026-09-08,9900000001,REQ-3,0,1,5000,제외업체\n"
        "2025-08-01,4227220901,REQ-4,0,1,200000,기간외업체\n"
    )
    path.write_text(content, encoding=encoding)


def test_bulk_ingest_filters_scope_and_stores_manifest(tmp_path: Path) -> None:
    path = tmp_path / "g2b.csv"
    _write_sample(path)
    store = FakeStore()

    summary = ingest_bulk_csv(
        path=path,
        store=store,
        begin=__import__("datetime").date(2025, 9, 12),
        end=__import__("datetime").date(2026, 9, 11),
        retrieved_date=__import__("datetime").date(2026, 9, 12),
        chunk_size=1,
    )

    assert summary.rows_read == 4
    assert summary.rows_in_scope == 2
    assert summary.distinct_detail_codes == 2
    assert summary.earliest_approval_date == "2026-09-09"
    assert summary.latest_approval_date == "2026-09-10"
    assert summary.gap_plan.strategy == "BULK_ONLY"
    assert summary.gap_plan.api_gap_begin_date is None
    assert summary.chunks_stored == 3  # two data chunks + one manifest
    assert len(store.payloads) == 3

    first = store.payloads[0]
    assert isinstance(first, dict)
    rows = first["rows"]
    assert isinstance(rows, list)
    assert rows[0]["_normalized_detail_code"] == "4227250101"
    assert rows[0]["_stable_source_key"] == "REQ-1|0|1"


def test_gap_plan_only_requests_post_bulk_freshness_window() -> None:
    from datetime import date

    plan = build_gap_plan(retrieved_date=date(2026, 9, 11), requested_end=date(2026, 9, 11))

    assert plan.strategy == "RECENT_GAP_ONLY"
    assert plan.source_cutoff_date == "2026-09-10"
    assert plan.api_gap_begin_date == "2026-09-11"
    assert plan.api_gap_end_date == "2026-09-11"


def test_cp949_bulk_csv_is_supported(tmp_path: Path) -> None:
    path = tmp_path / "g2b-cp949.csv"
    _write_sample(path, encoding="cp949")

    assert detect_csv_encoding(path) == "cp949"


def test_missing_required_header_fails_closed(tmp_path: Path) -> None:
    from datetime import date

    path = tmp_path / "bad.csv"
    path.write_text("결재일자,납품단가\n2026-09-10,100\n", encoding="utf-8")

    with pytest.raises(BulkCsvContractError, match="detail code"):
        ingest_bulk_csv(
            path=path,
            store=FakeStore(),
            begin=date(2025, 9, 12),
            end=date(2026, 9, 11),
            retrieved_date=date(2026, 9, 12),
        )

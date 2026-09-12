from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from purchase_price.services.g2b_bulk_csv import (
    BulkCsvContractError,
    build_gap_plan,
    detect_csv_encoding,
    ingest_bulk_csv,
    inspect_bulk_export,
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


def _write_official_export(
    path: Path,
    *,
    encoding: str = "utf-16",
    delimiter: str = "\t",
    query_from: str = "20250912",
    query_to: str = "20260911",
) -> None:
    preamble = (
        "검색조건 : 프롬프트 1: 기준일자(From)\n"
        f"{query_from}\n"
        "프롬프트 2: 기준일자(To)\n"
        f"{query_to}\n"
        "프롬프트 3: 수요기관\n\n"
        "출력일자 : 2026-09-12\n"
    )
    header = delimiter.join(
        [
            "납품요구번호",
            "납품요구변경차수",
            "물품순번",
            "수요기관",
            "납품요구일자",
            "세부품명번호",
            "세부품명",
            "물품식별번호",
            "납품단가",
            "업체명",
        ]
    )
    rows = [
        delimiter.join(["REQ-1", "0", "1", "병원", "2026-09-10", "4227250101", "의료", "111", "100000", "의료업체"]),
        delimiter.join(["REQ-2", "1", "2", "병원", "2026-09-09", "4321150301", "전산", "222", "1200000", "전산업체"]),
        delimiter.join(["REQ-3", "0", "1", "기관", "2026-09-08", "9900000001", "제외", "333", "5000", "제외업체"]),
    ]
    path.write_text(preamble + header + "\n" + "\n".join(rows) + "\n", encoding=encoding)


def test_real_utf16_tsv_export_is_detected(tmp_path: Path) -> None:
    path = tmp_path / "UI-ADOXAA-038R.csv"
    _write_official_export(path)

    contract = inspect_bulk_export(path)

    assert detect_csv_encoding(path) == "utf-16"
    assert contract.delimiter == "\t"
    assert contract.query_begin_date == "2025-09-12"
    assert contract.query_end_date == "2026-09-11"
    assert contract.output_date == "2026-09-12"


def test_bulk_ingest_filters_scope_and_stores_manifest(tmp_path: Path) -> None:
    path = tmp_path / "g2b.csv"
    _write_official_export(path)
    store = FakeStore()

    summary = ingest_bulk_csv(
        path=path,
        store=store,
        begin=date(2025, 9, 12),
        end=date(2026, 9, 11),
        retrieved_date=date(2026, 9, 12),
        chunk_size=1,
    )

    assert summary.rows_read == 3
    assert summary.rows_in_scope == 2
    assert summary.distinct_detail_codes == 2
    assert summary.source_encoding == "utf-16"
    assert summary.source_delimiter == "TAB"
    assert summary.source_query_begin_date == "2025-09-12"
    assert summary.source_query_end_date == "2026-09-11"
    assert summary.gap_plan.strategy == "BULK_ONLY"
    assert summary.gap_plan.api_gap_begin_date is None
    assert summary.data_chunks_stored == 2
    assert summary.manifest_object_key.endswith(".json.gz")
    assert len(store.payloads) == 3

    first = store.payloads[0]
    assert isinstance(first, dict)
    rows = first["rows"]
    assert isinstance(rows, list)
    assert rows[0]["_normalized_detail_code"] == "4227250101"
    assert rows[0]["_stable_source_key"] == "REQ-1|0|1"


def test_gap_plan_only_requests_post_bulk_freshness_window() -> None:
    plan = build_gap_plan(
        retrieved_date=date(2026, 9, 11),
        requested_begin=date(2025, 9, 12),
        requested_end=date(2026, 9, 11),
        source_begin=date(2025, 9, 12),
        source_end=date(2026, 9, 10),
    )

    assert plan.strategy == "RECENT_GAP_ONLY"
    assert plan.source_cutoff_date == "2026-09-10"
    assert plan.api_gap_begin_date == "2026-09-11"
    assert plan.api_gap_end_date == "2026-09-11"


def test_day_only_export_is_rejected_before_any_r2_write(tmp_path: Path) -> None:
    path = tmp_path / "one-day.csv"
    _write_official_export(path, query_from="20260910", query_to="20260910")
    store = FakeStore()

    with pytest.raises(BulkCsvContractError, match="historical start"):
        ingest_bulk_csv(
            path=path,
            store=store,
            begin=date(2025, 9, 12),
            end=date(2026, 9, 11),
            retrieved_date=date(2026, 9, 12),
        )

    assert store.payloads == []


def test_cp949_comma_export_is_supported(tmp_path: Path) -> None:
    path = tmp_path / "g2b-cp949.csv"
    _write_official_export(path, encoding="cp949", delimiter=",")

    contract = inspect_bulk_export(path)

    assert detect_csv_encoding(path) == "cp949"
    assert contract.delimiter == ","


def test_missing_header_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / "bad.csv"
    path.write_text("출력일자 : 2026-09-12\n결재일자,납품단가\n2026-09-10,100\n", encoding="utf-8")

    with pytest.raises(BulkCsvContractError, match="header row"):
        ingest_bulk_csv(
            path=path,
            store=FakeStore(),
            begin=date(2025, 9, 12),
            end=date(2026, 9, 11),
            retrieved_date=date(2026, 9, 12),
        )

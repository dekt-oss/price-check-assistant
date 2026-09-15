from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

from purchase_price.scripts.collect_g2b_track_b_r2 import (
    TRACK_B_OPERATION,
    CollectionCursor,
    collect_track_b_batch,
)
from purchase_price.storage.r2 import RawObjectRef, payload_sha256


def _response(items: list[dict[str, Any]], *, total: int, page: int, rows: int) -> dict[str, Any]:
    return {
        "response": {
            "header": {"resultCode": "00", "resultMsg": "NORMAL SERVICE"},
            "body": {
                "items": items,
                "totalCount": total,
                "pageNo": page,
                "numOfRows": rows,
            },
        }
    }


class FakeClient:
    def __init__(self, responses: list[dict[str, Any] | Exception]) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def get_json(self, base_url: str, operation: str, **params: Any) -> dict[str, Any]:
        del base_url
        self.calls.append((operation, dict(params)))
        if not self.responses:
            raise AssertionError("unexpected API call")
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


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


def _write_snapshot(path: Path, *, segments: tuple[str, ...], codes: list[str]) -> None:
    path.write_text(
        json.dumps(
            {
                "schema": "g2b-target-code-snapshot-v1",
                "source": "data.go.kr/G2B ShoppingMallPrdctInfoService",
                "operation": "getPrdctClsfcNoUnit10Info02",
                "segments": list(segments),
                "active_only": True,
                "code_count": len(codes),
                "codes": codes,
                "generated_at": "2026-09-13T00:00:00+00:00",
                "dictionary_requests": 24,
            }
        ),
        encoding="utf-8",
    )


def test_batch_is_budget_bounded_and_resumes_inside_code() -> None:
    dictionary = [
        {"dtilPrdctClsfcNo": "2300000001", "useYn": "Y"},
        {"dtilPrdctClsfcNo": "2300000002", "useYn": "Y"},
        {"dtilPrdctClsfcNo": "9900000001", "useYn": "Y"},
    ]
    catalog = FakeClient(
        [
            _response(dictionary[:2], total=3, page=1, rows=2),
            _response(dictionary[2:], total=3, page=2, rows=2),
        ]
    )
    shopping = FakeClient(
        [
            _response([{"row": 1}, {"row": 2}], total=3, page=1, rows=2),
        ]
    )
    store = FakeStore()

    summary = collect_track_b_batch(
        catalog_client=catalog,
        shopping_client=shopping,
        store=store,
        catalog_base_url="https://catalog",
        shopping_base_url="https://shopping",
        begin=date(2025, 9, 12),
        end=date(2026, 9, 11),
        start_cursor=CollectionCursor(0, 1),
        request_budget=3,
        segments=("23",),
        page_size=2,
    )

    assert summary.status == "PARTIAL_SUCCESS"
    assert summary.stop_reason == "REQUEST_BUDGET_EXHAUSTED"
    assert summary.dictionary_requests == 2
    assert summary.track_b_requests == 1
    assert summary.total_requests == 3
    assert summary.codes_completed == 0
    assert summary.pages_stored == 1
    assert summary.rows_seen == 2
    assert summary.next_cursor == CollectionCursor(0, 2)


def test_snapshot_skips_dictionary_and_spends_full_budget_on_track_b(tmp_path: Path) -> None:
    snapshot_path = tmp_path / "target-codes.json"
    _write_snapshot(
        snapshot_path,
        segments=("42",),
        codes=["4200000001", "4200000002"],
    )
    catalog = FakeClient([])
    shopping = FakeClient(
        [
            _response([], total=0, page=1, rows=999),
            _response([], total=0, page=1, rows=999),
        ]
    )

    summary = collect_track_b_batch(
        catalog_client=catalog,
        shopping_client=shopping,
        store=FakeStore(),
        catalog_base_url="https://catalog",
        shopping_base_url="https://shopping",
        begin=date(2025, 9, 13),
        end=date(2026, 9, 12),
        start_cursor=CollectionCursor(0, 1),
        request_budget=2,
        segments=("42",),
        target_code_snapshot_path=snapshot_path,
    )

    assert summary.status == "SUCCESS"
    assert summary.target_code_source == "SNAPSHOT"
    assert summary.target_code_snapshot_sha256
    assert summary.dictionary_requests == 0
    assert summary.track_b_requests == 2
    assert summary.total_requests == 2
    assert catalog.calls == []


def test_track_b_request_omits_final_change_order_filter_and_stores_zero_result() -> None:
    dictionary = [{"dtilPrdctClsfcNo": "4200000001", "useYn": "Y"}]
    catalog = FakeClient([_response(dictionary, total=1, page=1, rows=999)])
    shopping = FakeClient([_response([], total=0, page=1, rows=999)])
    store = FakeStore()

    summary = collect_track_b_batch(
        catalog_client=catalog,
        shopping_client=shopping,
        store=store,
        catalog_base_url="https://catalog",
        shopping_base_url="https://shopping",
        begin=date(2025, 9, 12),
        end=date(2026, 9, 11),
        start_cursor=CollectionCursor(0, 1),
        request_budget=2,
        segments=("42",),
    )

    assert summary.status == "SUCCESS"
    assert summary.codes_completed == 1
    assert summary.next_cursor == CollectionCursor(1, 1)
    assert summary.rows_seen == 0
    assert len(store.payloads) == 1
    operation, params = shopping.calls[0]
    assert operation == TRACK_B_OPERATION
    assert "fnlCntrctDlvrReqChgOrdYn" not in params
    stored = store.payloads[0]
    assert isinstance(stored, dict)
    request = stored["request"]
    assert isinstance(request, dict)
    assert request["final_change_order_filter"] == "OMITTED"


def test_only_active_target_segment_codes_are_collected() -> None:
    dictionary = [
        {"dtilPrdctClsfcNo": "4100000001", "useYn": "Y"},
        {"dtilPrdctClsfcNo": "4100000002", "useYn": "N"},
        {"dtilPrdctClsfcNo": "4200000001", "useYn": "Y"},
    ]
    catalog = FakeClient([_response(dictionary, total=3, page=1, rows=999)])
    shopping = FakeClient([_response([{"row": 1}], total=1, page=1, rows=999)])
    store = FakeStore()

    summary = collect_track_b_batch(
        catalog_client=catalog,
        shopping_client=shopping,
        store=store,
        catalog_base_url="https://catalog",
        shopping_base_url="https://shopping",
        begin=date(2025, 9, 12),
        end=date(2026, 9, 11),
        start_cursor=CollectionCursor(0, 1),
        request_budget=2,
        segments=("41",),
    )

    assert summary.target_code_count == 1
    assert summary.codes_completed == 1
    _, params = shopping.calls[0]
    assert params["dtilPrdctClsfcNo"] == "4100000001"


def test_rate_limit_is_failed_and_counts_attempted_request(tmp_path: Path) -> None:
    snapshot_path = tmp_path / "target-codes.json"
    _write_snapshot(snapshot_path, segments=("42",), codes=["4200000001"])
    summary = collect_track_b_batch(
        catalog_client=FakeClient([]),
        shopping_client=FakeClient(
            [RuntimeError("HTTP 429 code=22 LIMITED_NUMBER_OF_SERVICE_REQUESTS_EXCEEDS_ERROR")]
        ),
        store=FakeStore(),
        catalog_base_url="https://catalog",
        shopping_base_url="https://shopping",
        begin=date(2025, 9, 13),
        end=date(2026, 9, 12),
        start_cursor=CollectionCursor(0, 1),
        request_budget=1,
        segments=("42",),
        target_code_snapshot_path=snapshot_path,
    )

    assert summary.status == "FAILED"
    assert summary.stop_reason == "RATE_LIMIT_EXHAUSTED"
    assert summary.dictionary_requests == 0
    assert summary.track_b_requests == 1
    assert summary.total_requests == 1
    assert summary.next_cursor == CollectionCursor(0, 1)


def test_source_error_after_partial_write_is_not_reported_as_success(tmp_path: Path) -> None:
    snapshot_path = tmp_path / "target-codes.json"
    _write_snapshot(snapshot_path, segments=("42",), codes=["4200000001"])
    shopping = FakeClient(
        [
            _response([{"row": 1}], total=1000, page=1, rows=999),
            RuntimeError("upstream connection failed"),
        ]
    )
    summary = collect_track_b_batch(
        catalog_client=FakeClient([]),
        shopping_client=shopping,
        store=FakeStore(),
        catalog_base_url="https://catalog",
        shopping_base_url="https://shopping",
        begin=date(2025, 9, 13),
        end=date(2026, 9, 12),
        start_cursor=CollectionCursor(0, 1),
        request_budget=2,
        segments=("42",),
        target_code_snapshot_path=snapshot_path,
    )

    assert summary.pages_stored == 1
    assert summary.status == "FAILED"
    assert summary.stop_reason == "SOURCE_OR_STORAGE_ERROR"
    assert summary.track_b_requests == 2
    assert summary.next_cursor == CollectionCursor(0, 2)

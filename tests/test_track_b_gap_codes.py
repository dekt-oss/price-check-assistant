from __future__ import annotations

from datetime import date
from typing import Any

from purchase_price.scripts.collect_g2b_track_b_r2 import (
    TRACK_B_OPERATION,
    CollectionCursor,
    collect_track_b_batch,
)
from purchase_price.storage.r2 import RawObjectRef, payload_sha256


def _response(items: list[dict[str, Any]], *, total: int) -> dict[str, Any]:
    return {
        "response": {
            "header": {"resultCode": "00", "resultMsg": "NORMAL SERVICE"},
            "body": {
                "items": items,
                "totalCount": total,
                "pageNo": 1,
                "numOfRows": 999,
            },
        }
    }


class NoCallCatalogClient:
    def get_json(self, base_url: str, operation: str, **params: Any) -> dict[str, Any]:
        raise AssertionError("dictionary API must not be called for explicit gap codes")


class ShoppingClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def get_json(self, base_url: str, operation: str, **params: Any) -> dict[str, Any]:
        del base_url
        self.calls.append((operation, dict(params)))
        return _response([{"prdctUprc": "12345"}], total=1)


class FakeStore:
    def put_public_json(self, *, source_operation: str, payload: object) -> RawObjectRef:
        digest, canonical = payload_sha256(payload)
        return RawObjectRef(
            bucket="price-check-raw",
            key=f"raw/v1/{source_operation}/{digest}.json.gz",
            payload_hash=digest,
            uncompressed_bytes=len(canonical),
            stored_bytes=max(1, len(canonical) // 2),
            created=True,
        )


def test_explicit_gap_codes_skip_dictionary_and_use_recent_window() -> None:
    shopping = ShoppingClient()
    summary = collect_track_b_batch(
        catalog_client=NoCallCatalogClient(),
        shopping_client=shopping,
        store=FakeStore(),
        catalog_base_url="https://catalog",
        shopping_base_url="https://shopping",
        begin=date(2026, 9, 11),
        end=date(2026, 9, 11),
        start_cursor=CollectionCursor(0, 1),
        request_budget=1,
        target_codes=("4227250101",),
    )

    assert summary.status == "SUCCESS"
    assert summary.dictionary_requests == 0
    assert summary.track_b_requests == 1
    assert summary.total_requests == 1
    assert summary.rows_seen == 1
    assert summary.codes_completed == 1
    assert len(shopping.calls) == 1
    operation, params = shopping.calls[0]
    assert operation == TRACK_B_OPERATION
    assert params["inqryBgnDate"] == "20260911"
    assert params["inqryEndDate"] == "20260911"
    assert params["dtilPrdctClsfcNo"] == "4227250101"
    assert "fnlCntrctDlvrReqChgOrdYn" not in params

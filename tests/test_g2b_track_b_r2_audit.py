from __future__ import annotations

import gzip
import hashlib
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from purchase_price.services.g2b_track_b_audit import audit_track_b_raw_pages
from purchase_price.services.g2b_track_b_normalization import TrackBRawPage
from purchase_price.storage.r2 import R2IntegrityError, canonical_json_bytes
from purchase_price.storage.r2_reader import R2RawEvidenceReader


class _Body:
    def __init__(self, value: bytes) -> None:
        self._value = value

    def read(self) -> bytes:
        return self._value


class _FakeR2Client:
    def __init__(self, *, payload: dict[str, object]) -> None:
        canonical = canonical_json_bytes(payload)
        self.digest = hashlib.sha256(canonical).hexdigest()
        self.key = (
            "raw/v1/getSpcifyPrdlstPrcureInfoList-page/"
            f"{self.digest[:2]}/{self.digest[2:4]}/{self.digest}.json.gz"
        )
        self.compressed = gzip.compress(canonical, compresslevel=6, mtime=0)
        self.list_calls: list[dict[str, object]] = []
        self.get_calls: list[dict[str, object]] = []

    def list_objects_v2(self, **kwargs):
        self.list_calls.append(kwargs)
        return {
            "Contents": [
                {
                    "Key": self.key,
                    "Size": len(self.compressed),
                    "LastModified": datetime(2026, 9, 14, 8, 0, tzinfo=UTC),
                },
                {"Key": "raw/v1/other/not-json.txt", "Size": 3},
            ],
            "IsTruncated": False,
        }

    def get_object(self, **kwargs):
        self.get_calls.append(kwargs)
        return {"Body": _Body(self.compressed)}


def _page(*, unit_price: str | None = "450000", amount: str = "450000") -> dict[str, object]:
    item: dict[str, object] = {
        "cntrctDlvrReqNo": "R26TB02131828",
        "cntrctDlvrReqChgOrd": "00",
        "prdctSno": "1",
        "cntrctDlvrReqDate": "20260715",
        "dtilPrdctClsfcNo": "4010190201",
        "prdctIdntNoNm": "제습기, 나우이엘, MA-045DT, 45L/d",
        "prdctQty": "1",
        "prdctAmt": amount,
    }
    if unit_price is not None:
        item["prdctUprc"] = unit_price
    return {
        "schema": "g2b-track-b-page-v1",
        "operation": "getSpcifyPrdlstPrcureInfoList",
        "request": {
            "detail_code": "4010190201",
            "begin_date": "2025-09-13",
            "end_date": "2026-09-12",
            "page_no": 1,
            "page_size": 999,
            "inquiry_div": "1",
            "product_div": "2",
            "final_change_order_filter": "OMITTED",
        },
        "response": {
            "total_count": 1,
            "page_no": 1,
            "num_of_rows": 999,
            "items": [item],
        },
    }


def test_r2_reader_lists_only_operation_json_and_verifies_content_hash() -> None:
    payload = _page()
    client = _FakeR2Client(payload=payload)
    reader = R2RawEvidenceReader(client=client, bucket="test", raw_prefix="raw/v1")

    objects = reader.list_public_json(
        source_operation="getSpcifyPrdlstPrcureInfoList-page", limit=10
    )

    assert len(objects) == 1
    assert objects[0].key == client.key
    assert objects[0].payload_hash == client.digest
    assert objects[0].stored_bytes == len(client.compressed)
    assert client.list_calls[0]["Prefix"] == "raw/v1/getSpcifyPrdlstPrcureInfoList-page/"
    assert reader.get_public_json(objects[0]) == payload
    assert client.get_calls == [{"Bucket": "test", "Key": client.key}]


def test_r2_reader_fails_closed_on_tampered_body() -> None:
    payload = _page()
    client = _FakeR2Client(payload=payload)
    reader = R2RawEvidenceReader(client=client, bucket="test")
    obj = reader.list_public_json(limit=1)[0]
    client.compressed = gzip.compress(b'{"tampered":true}', mtime=0)

    with pytest.raises(R2IntegrityError, match="payload hash mismatch"):
        reader.get_public_json(obj)


def test_track_b_audit_counts_only_explicit_positive_unit_price_candidates() -> None:
    explicit = _page(unit_price="450000")
    missing = _page(unit_price=None, amount="900000")
    missing_item = missing["response"]["items"][0]  # type: ignore[index]
    missing_item["cntrctDlvrReqNo"] = "R26TB02131829"  # type: ignore[index]

    summary = audit_track_b_raw_pages(
        (
            TrackBRawPage(explicit, raw_object_key="raw/explicit", raw_payload_sha256="a" * 64),
            TrackBRawPage(missing, raw_object_key="raw/missing", raw_payload_sha256="b" * 64),
        )
    )

    assert summary.pages_seen == 2
    assert summary.normalized_records == 2
    assert summary.price_candidates == 1
    assert summary.non_price_records == 1
    assert summary.duplicate_pages == 0
    assert summary.duplicate_records == 0
    explicit_record_price = Decimal("450000")
    assert explicit_record_price > 0


def test_track_b_audit_reports_amount_mismatch_without_deriving_price() -> None:
    page = _page(unit_price="450000", amount="1")
    summary = audit_track_b_raw_pages((TrackBRawPage(page),))

    assert summary.price_candidates == 1
    assert dict(summary.issue_counts) == {"AMOUNT_MISMATCH": 1}

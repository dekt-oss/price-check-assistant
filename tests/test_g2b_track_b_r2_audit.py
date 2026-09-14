from __future__ import annotations

import gzip
import hashlib
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from purchase_price.scripts.audit_g2b_track_b_r2 import TrackBAuditReadFailure, run
from purchase_price.services.g2b_track_b_audit import audit_track_b_raw_pages
from purchase_price.services.g2b_track_b_normalization import (
    TrackBIdentityConflictError,
    TrackBRawPage,
)
from purchase_price.storage.r2 import R2IntegrityError, canonical_json_bytes
from purchase_price.storage.r2_reader import R2RawEvidenceReader, R2RawObject, R2RawObjectPage


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
                }
            ],
            "IsTruncated": False,
        }

    def get_object(self, **kwargs):
        self.get_calls.append(kwargs)
        return {
            "Body": _Body(self.compressed),
            "Metadata": {
                "sha256": self.digest,
                "schema": "raw-v1",
                "source-operation": "getSpcifyPrdlstPrcureInfoList-page",
                "data-classification": "public-provenance",
            },
        }


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


def test_audit_summary_breaks_down_price_identity_amount_and_classification() -> None:
    page = _page(unit_price="450000", amount="1")
    items = page["response"]["items"]  # type: ignore[index]
    zero = dict(items[0])
    zero.update(cntrctDlvrReqNo="R2", cntrctDlvrReqChgOrd="01", prdctUprc="0")
    missing = dict(items[0])
    missing.update(cntrctDlvrReqNo="R3")
    missing.pop("prdctUprc")
    items.extend([zero, missing])

    summary = audit_track_b_raw_pages((TrackBRawPage(page),))

    assert summary.rows_seen == 3
    assert summary.normalized_records == 3
    assert dict(summary.price_counts) == {
        "missing": 1, "positive": 1, "present": 2, "zero": 1
    }
    assert dict(summary.identity_counts)["changed_order_records"] == 1
    assert dict(summary.amount_check_counts)["inconsistent"] == 2
    assert dict(summary.classification_counts)["4010190201"] == (
        ("mismatch_rows", 2),
        ("no_price_rows", 2),
        ("normalized_rows", 3),
        ("price_candidates", 1),
        ("raw_rows", 3),
    )


def test_audit_counts_negative_and_nonfinite_explicit_price_without_candidate() -> None:
    page = _page(unit_price="-1", amount="-1")
    invalid = dict(page["response"]["items"][0])  # type: ignore[index]
    invalid.update(cntrctDlvrReqNo="R2", prdctUprc="NaN")
    page["response"]["items"].append(invalid)  # type: ignore[index]

    summary = audit_track_b_raw_pages((TrackBRawPage(page),))

    assert summary.price_candidates == 0
    assert dict(summary.price_counts) == {"invalid": 1, "negative": 1, "present": 2}


def test_audit_fails_closed_on_same_page_identity_conflict() -> None:
    page = _page()
    items = page["response"]["items"]  # type: ignore[index]
    changed = dict(items[0])
    changed["corpNm"] = "different"
    items.append(changed)

    with pytest.raises(TrackBIdentityConflictError):
        audit_track_b_raw_pages((TrackBRawPage(page),))


def test_r2_reader_page_resumes_by_last_lexical_key() -> None:
    class ListingClient:
        def __init__(self) -> None:
            self.calls: list[dict[str, object]] = []
            self.keys = [
                "raw/v1/getSpcifyPrdlstPrcureInfoList-page/00/00/"
                f"{n:064x}.json.gz"
                for n in range(3)
            ]

        def list_objects_v2(self, **kwargs):
            self.calls.append(kwargs)
            keys = [key for key in self.keys if key > kwargs.get("StartAfter", "")]
            selected = keys[: kwargs["MaxKeys"]]
            return {
                "Contents": [{"Key": key, "Size": 10} for key in selected],
                "IsTruncated": len(keys) > len(selected),
            }

    client = ListingClient()
    reader = R2RawEvidenceReader(client=client, bucket="test")
    first = reader.list_public_json_page(
        source_operation="getSpcifyPrdlstPrcureInfoList-page", limit=2
    )
    second = reader.list_public_json_page(
        source_operation="getSpcifyPrdlstPrcureInfoList-page",
        limit=2,
        after_key=first.next_cursor,
    )

    assert [obj.key for obj in first.objects + second.objects] == client.keys
    assert first.has_more is True
    assert second.has_more is False
    assert client.calls[1]["StartAfter"] == client.keys[1]


def test_audit_batch_reports_resume_cursor_and_invalid_pages(monkeypatch) -> None:
    keys = [
        f"raw/v1/getSpcifyPrdlstPrcureInfoList-page/{letter}/{letter}/"
        f"{'a' * 64}.json.gz"
        for letter in ("a", "b")
    ]
    objects = tuple(R2RawObject("test", key, "a" * 64, 10, None) for key in keys)

    class Reader:
        def __init__(self) -> None:
            self.calls: list[tuple[int, str | None]] = []

        def list_public_json_page(self, *, source_operation, limit, after_key):
            assert source_operation == "getSpcifyPrdlstPrcureInfoList-page"
            self.calls.append((limit, after_key))
            return R2RawObjectPage(objects, keys[-1], True)

        def get_public_json(self, obj):
            return _page() if obj.key == keys[0] else {"malformed": True}

    reader = Reader()
    monkeypatch.setattr(R2RawEvidenceReader, "from_settings", lambda settings: reader)
    report = run(limit=2, cursor=None)

    assert report["objects_scanned"] == 2
    assert report["pages_parsed"] == 1
    assert report["invalid_pages"] == 1
    assert report["resume_cursor"] == keys[-1]
    assert report["has_more"] is True
    assert report["public_api_requests"] == 0
    assert report["writes_performed"] == 0
    assert reader.calls == [(2, None)]
    assert not hasattr(R2RawEvidenceReader, "put_public_json")


def test_audit_failure_exposes_only_last_completed_resume_key(monkeypatch) -> None:
    keys = [
        f"raw/v1/getSpcifyPrdlstPrcureInfoList-page/{letter}/{letter}/"
        f"{'a' * 64}.json.gz"
        for letter in ("a", "b")
    ]
    objects = tuple(R2RawObject("test", key, "a" * 64, 10, None) for key in keys)

    class Reader:
        def list_public_json_page(self, **kwargs):
            return R2RawObjectPage(objects, keys[-1], False)

        def get_public_json(self, obj):
            if obj.key == keys[1]:
                raise R2IntegrityError("payload hash mismatch")
            return _page()

    monkeypatch.setattr(R2RawEvidenceReader, "from_settings", lambda settings: Reader())
    with pytest.raises(TrackBAuditReadFailure) as raised:
        run(limit=2)

    assert raised.value.object_key == keys[1]
    assert raised.value.resume_cursor == keys[0]


def test_audit_run_aggregates_multiple_listing_pages_and_replay(monkeypatch) -> None:
    keys = [
        f"raw/v1/getSpcifyPrdlstPrcureInfoList-page/{letter}/{letter}/"
        f"{'a' * 63}{letter}.json.gz"
        for letter in ("a", "b")
    ]
    objects = [R2RawObject("test", key, "a" * 64, 10, None) for key in keys]

    class Reader:
        def __init__(self) -> None:
            self.cursors: list[str | None] = []

        def list_public_json_page(self, *, after_key, **kwargs):
            self.cursors.append(after_key)
            index = 0 if after_key is None else keys.index(after_key) + 1
            return R2RawObjectPage((objects[index],), keys[index], index == 0)

        def get_public_json(self, obj):
            return _page()

    reader = Reader()
    monkeypatch.setattr(R2RawEvidenceReader, "from_settings", lambda settings: reader)
    report = run(limit=2)

    assert reader.cursors == [None, keys[0]]
    assert report["objects_scanned"] == 2
    assert report["duplicate_pages"] == 1
    assert report["normalized_records"] == 1
    assert report["resume_cursor"] == keys[1]
    assert report["has_more"] is False


def test_reader_rejects_metadata_mismatch_and_corrupt_gzip() -> None:
    client = _FakeR2Client(payload=_page())
    reader = R2RawEvidenceReader(client=client, bucket="test")
    obj = reader.list_public_json(limit=1)[0]
    original_get = client.get_object

    def wrong_metadata(**kwargs):
        response = original_get(**kwargs)
        response["Metadata"]["sha256"] = "b" * 64
        return response

    client.get_object = wrong_metadata  # type: ignore[method-assign]
    with pytest.raises(R2IntegrityError, match="metadata"):
        reader.get_public_json(obj)

    client.get_object = original_get  # type: ignore[method-assign]
    client.compressed = b"not gzip"
    with pytest.raises(R2IntegrityError, match="valid gzip"):
        reader.get_public_json(obj)


def test_reader_rejects_key_with_wrong_content_address_shards() -> None:
    class Client:
        def list_objects_v2(self, **kwargs):
            return {
                "Contents": [{
                    "Key": "raw/v1/getSpcifyPrdlstPrcureInfoList-page/00/00/"
                    f"{'a' * 64}.json.gz",
                }],
                "IsTruncated": False,
            }

    reader = R2RawEvidenceReader(client=Client(), bucket="test")
    with pytest.raises(R2IntegrityError, match="shards"):
        reader.list_public_json_page(limit=1)


def test_audit_summary_is_independent_of_page_order() -> None:
    first = _page()
    second = _page(unit_price=None)
    second["response"]["items"][0]["cntrctDlvrReqNo"] = "R2"  # type: ignore[index]
    pages = (
        TrackBRawPage(first, raw_payload_sha256="a" * 64),
        TrackBRawPage(second, raw_payload_sha256="b" * 64),
    )
    assert audit_track_b_raw_pages(pages).as_dict() == audit_track_b_raw_pages(
        tuple(reversed(pages))
    ).as_dict()


def test_cross_page_conflict_stops_before_advancing_resume_cursor(monkeypatch) -> None:
    keys = [
        f"raw/v1/getSpcifyPrdlstPrcureInfoList-page/{n:02x}/00/{n:064x}.json.gz"
        for n in range(2)
    ]
    objects = [R2RawObject("test", key, f"{n:064x}", 10, None) for n, key in enumerate(keys)]
    changed = _page()
    changed["response"]["items"][0]["corpNm"] = "different"  # type: ignore[index]

    class Reader:
        def list_public_json_page(self, *, after_key, **kwargs):
            index = 0 if after_key is None else 1
            return R2RawObjectPage((objects[index],), keys[index], index == 0)

        def get_public_json(self, obj):
            return _page() if obj.key == keys[0] else changed

    monkeypatch.setattr(R2RawEvidenceReader, "from_settings", lambda settings: Reader())
    with pytest.raises(TrackBAuditReadFailure) as raised:
        run(limit=2)
    assert raised.value.object_key == keys[1]
    assert raised.value.resume_cursor == keys[0]


def test_audit_limit_above_1000_uses_bounded_listing_pages(monkeypatch) -> None:
    keys = [
        "raw/v1/getSpcifyPrdlstPrcureInfoList-page/00/00/"
        f"{n:064x}.json.gz"
        for n in range(1001)
    ]
    objects = tuple(R2RawObject("test", key, "a" * 64, 10, None) for key in keys)

    class Reader:
        def __init__(self):
            self.limits = []

        def list_public_json_page(self, *, limit, after_key, **kwargs):
            self.limits.append(limit)
            start = 0 if after_key is None else keys.index(after_key) + 1
            selected = objects[start : start + limit]
            return R2RawObjectPage(selected, selected[-1].key, start + len(selected) < len(keys))

        def get_public_json(self, obj):
            return _page()

    reader = Reader()
    monkeypatch.setattr(R2RawEvidenceReader, "from_settings", lambda settings: reader)
    report = run(limit=1001)
    assert reader.limits == [1000, 1]
    assert report["objects_scanned"] == 1001
    assert report["duplicate_pages"] == 1000

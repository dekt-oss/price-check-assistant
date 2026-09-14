from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from purchase_price.domain import ComparisonScope, EvidenceType
from purchase_price.services.g2b_track_b_normalization import (
    TrackBAmountCheck,
    TrackBIdentityConflictError,
    TrackBRawPage,
    build_track_b_price_candidate,
    consolidate_track_b_records,
    normalize_track_b_page,
    normalize_track_b_pages,
    project_change_order_state,
)


def _item(
    *,
    change_order: str = "00",
    unit_price: str | None = "450000",
    quantity: str | None = "1",
    total_amount: str | None = "450000",
) -> dict[str, object]:
    item: dict[str, object] = {
        "cntrctDlvrReqNo": "R26TB02131828",
        "cntrctDlvrReqChgOrd": change_order,
        "prdctSno": "1",
        "cntrctDlvrReqDate": "20260715",
        "cntrctDlvrDivNm": "납품요구",
        "cntrctDivNm": "제3자단가계약",
        "dminsttNm": "문화체육관광부 한국예술종합학교",
        "dtilPrdctClsfcNo": "4010190201",
        "dtilPrdctClsfcNoNm": "제습기",
        "prdctIdntNo": "24138760",
        "prdctIdntNoNm": "제습기, 나우이엘, MA-045DT, 45L/d",
        "prdctUnit": "대",
        "corpNm": "주식회사 나우이엘",
        "dlvryCndtnNm": "현장설치도",
    }
    if unit_price is not None:
        item["prdctUprc"] = unit_price
    if quantity is not None:
        item["prdctQty"] = quantity
    if total_amount is not None:
        item["prdctAmt"] = total_amount
    return item


def _page(items: list[object]) -> dict[str, object]:
    return {
        "schema": "g2b-track-b-page-v1",
        "source": "data.go.kr/G2B ShoppingMallPrdctInfoService",
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
            "total_count": len(items),
            "page_no": 1,
            "num_of_rows": 999,
            "items": items,
        },
    }


def test_normalizes_stable_identity_provenance_and_explicit_unit_price() -> None:
    fetched_at = datetime(2026, 9, 14, 8, 0, tzinfo=UTC)
    result = normalize_track_b_page(
        _page([_item()]),
        raw_object_key="raw/v1/getSpcifyPrdlstPrcureInfoList-page/abc.json.gz",
        raw_payload_sha256="abc",
        fetched_at=fetched_at,
    )

    assert result.issues == ()
    assert len(result.records) == 1
    record = result.records[0]
    assert record.identity.source_record_id == "delivery:R26TB02131828|change:00|line:1"
    assert record.provenance.detail_code == "4010190201"
    assert record.provenance.raw_payload_sha256 == "abc"
    assert record.provenance.fetched_at == fetched_at
    assert dict(record.provenance.api_params) == {
        "dtilPrdctClsfcNo": "4010190201",
        "inqryBgnDate": "20250913",
        "inqryDiv": "1",
        "inqryEndDate": "20260912",
        "inqryPrdctDiv": "2",
        "numOfRows": "999",
        "pageNo": "1",
    }
    assert record.unit_price == Decimal("450000")
    assert record.amount_check == TrackBAmountCheck.CONSISTENT
    assert record.transaction_date == date(2026, 7, 15)

    candidate = build_track_b_price_candidate(record, collected_at=date(2026, 9, 14))
    assert candidate is not None
    assert candidate.price == Decimal("450000")
    assert candidate.evidence_type == EvidenceType.DELIVERY_ORDER_UNIT_PRICE
    assert candidate.comparison_scope == ComparisonScope.OBSERVED_ONLY
    assert candidate.source_record_id == record.identity.source_record_id


def test_missing_prdct_uprc_never_falls_back_to_amount_quantity_or_generic_label() -> None:
    item = _item(unit_price=None, quantity="2", total_amount="900000")
    item["단가"] = "999999"
    result = normalize_track_b_page(_page([item]))

    assert len(result.records) == 1
    record = result.records[0]
    assert record.unit_price is None
    assert record.amount_check == TrackBAmountCheck.NOT_CHECKED
    assert build_track_b_price_candidate(record) is None


def test_zero_or_negative_prdct_uprc_is_not_a_price_candidate() -> None:
    zero = normalize_track_b_page(_page([_item(unit_price="0", total_amount="0")])).records[0]
    negative = normalize_track_b_page(
        _page([_item(unit_price="-1", total_amount="-1")])
    ).records[0]

    assert zero.unit_price == Decimal("0")
    assert negative.unit_price == Decimal("-1")
    assert build_track_b_price_candidate(zero) is None
    assert build_track_b_price_candidate(negative) is None


def test_amount_quantity_inconsistency_is_validation_only() -> None:
    result = normalize_track_b_page(
        _page([_item(unit_price="450000", quantity="2", total_amount="100000")])
    )
    record = result.records[0]

    assert record.amount_check == TrackBAmountCheck.INCONSISTENT
    assert any(issue.code == "AMOUNT_MISMATCH" for issue in result.issues)
    candidate = build_track_b_price_candidate(record)
    assert candidate is not None
    assert candidate.price == Decimal("450000")
    assert candidate.price != Decimal("50000")


def test_identical_replay_is_idempotent_but_divergent_identity_fails_closed() -> None:
    first = normalize_track_b_page(_page([_item()])).records[0]
    replay = normalize_track_b_page(_page([_item()])).records[0]
    assert consolidate_track_b_records([first, replay]) == (first,)

    changed_item = _item()
    changed_item["corpNm"] = "다른 공급사"
    divergent = normalize_track_b_page(_page([changed_item])).records[0]
    with pytest.raises(TrackBIdentityConflictError):
        consolidate_track_b_records([first, divergent])


def test_change_order_projection_preserves_history_and_marks_latest() -> None:
    first = normalize_track_b_page(_page([_item(change_order="00")])).records[0]
    second = normalize_track_b_page(_page([_item(change_order="01")])).records[0]

    states = project_change_order_state([first, second])

    assert len(states) == 2
    assert states[0].record.identity.change_order == "00"
    assert states[0].is_latest is False
    assert states[0].superseded_by == second.identity
    assert states[1].record.identity.change_order == "01"
    assert states[1].is_latest is True
    assert states[1].superseded_by is None


def test_same_page_duplicate_and_conflict_are_explicit() -> None:
    duplicate_result = normalize_track_b_page(_page([_item(), _item()]))
    assert len(duplicate_result.records) == 1
    assert duplicate_result.duplicate_count == 1
    assert duplicate_result.issues == ()

    changed = _item()
    changed["corpNm"] = "다른 공급사"
    conflict_result = normalize_track_b_page(_page([_item(), changed]))
    assert len(conflict_result.records) == 1
    assert any(issue.code == "IDENTITY_CONFLICT" for issue in conflict_result.issues)


def test_duplicate_page_is_skipped_before_record_consolidation() -> None:
    payload = _page([_item()])
    result = normalize_track_b_pages(
        [
            TrackBRawPage(payload, raw_object_key="raw/a"),
            TrackBRawPage(payload, raw_object_key="raw/a"),
        ]
    )

    assert len(result.records) == 1
    assert result.duplicate_pages == 1
    assert result.duplicate_records == 0


def test_missing_optional_fields_are_preserved_as_null_without_inventing_values() -> None:
    item = _item(quantity=None, total_amount=None)
    for key in (
        "corpNm",
        "dminsttNm",
        "prdctUnit",
        "cntrctDlvrDivNm",
        "cntrctDivNm",
        "dlvryCndtnNm",
        "cntrctDlvrReqDate",
    ):
        item[key] = None

    result = normalize_track_b_page(_page([item]))
    assert result.issues == ()
    record = result.records[0]
    assert record.quantity is None
    assert record.total_amount is None
    assert record.unit is None
    assert record.supplier is None
    assert record.demand_institution is None
    assert record.transaction_date is None
    assert record.amount_check == TrackBAmountCheck.NOT_CHECKED
    assert build_track_b_price_candidate(record) is not None

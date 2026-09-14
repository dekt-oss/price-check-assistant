from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from purchase_price.domain import ComparisonScope, EvidenceType
from purchase_price.services.g2b_track_b_normalization import (
    TrackBIdentityConflictError,
    build_track_b_price_candidate,
    consolidate_track_b_records,
    normalize_track_b_page,
    project_change_order_state,
)


def _item(*, change_order: str = "00", unit_price: str | None = "450000") -> dict[str, str]:
    item = {
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
        "prdctQty": "1",
        "prdctUnit": "대",
        "prdctAmt": "450000",
        "corpNm": "주식회사 나우이엘",
        "dlvryCndtnNm": "현장설치도",
    }
    if unit_price is not None:
        item["prdctUprc"] = unit_price
    return item


def _page(items: list[dict[str, str]]) -> dict[str, object]:
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
    result = normalize_track_b_page(
        _page([_item()]),
        raw_object_key="raw/v1/getSpcifyPrdlstPrcureInfoList-page/abc.json.gz",
        raw_payload_sha256="abc",
    )

    assert result.issues == ()
    assert len(result.records) == 1
    record = result.records[0]
    assert record.identity.source_record_id == "delivery:R26TB02131828|change:00|line:1"
    assert record.provenance.detail_code == "4010190201"
    assert record.provenance.raw_payload_sha256 == "abc"
    assert record.unit_price == Decimal("450000")
    assert record.transaction_date == date(2026, 7, 15)

    candidate = build_track_b_price_candidate(record, collected_at=date(2026, 9, 13))
    assert candidate is not None
    assert candidate.price == Decimal("450000")
    assert candidate.evidence_type == EvidenceType.DELIVERY_ORDER_UNIT_PRICE
    assert candidate.comparison_scope == ComparisonScope.OBSERVED_ONLY
    assert candidate.source_record_id == record.identity.source_record_id


def test_price_candidate_never_falls_back_from_missing_prdct_uprc() -> None:
    item = _item(unit_price=None)
    item["단가"] = "999999"
    item["prdctAmt"] = "888888"
    result = normalize_track_b_page(_page([item]))

    assert len(result.records) == 1
    assert result.records[0].unit_price is None
    assert build_track_b_price_candidate(result.records[0]) is None


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
    assert conflict_result.issues[0].code == "IDENTITY_CONFLICT"

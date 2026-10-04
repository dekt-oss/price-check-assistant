from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from purchase_price.services.mfds_business_license_view import (
    build_business_license_view,
    classify_company_match,
    company_core_key,
)
from purchase_price.services.mfds_device_intelligence import MedicalDeviceBusinessRecord


def _license(company: str, industry: str, status: str = "영업", number: str = "1") -> MedicalDeviceBusinessRecord:
    return MedicalDeviceBusinessRecord(
        company_name=company,
        industry_type=industry,
        business_status=status,
        permit_date=date(2020, 1, 1),
        address="서울",
        business_permit_number=number,
    )


@pytest.mark.parametrize(
    ("value", "key"),
    [
        ("(주)세종메디칼", "세종메디칼"),
        ("주식회사 세종메디칼", "세종메디칼"),
        ("㈜세종메디칼", "세종메디칼"),
        ("텔레플렉스코리아(유)", "텔레플렉스코리아"),
        ("Acme Medical Co., Ltd.", "acmemedical"),
        ("주원메디칼", "주원메디칼"),  # a leading 주 that is part of the name stays
    ],
)
def test_company_core_key_drops_legal_forms_only(value: str, key: str) -> None:
    assert company_core_key(value) == key


def test_classify_company_match() -> None:
    assert classify_company_match("(주)덴티움", "주식회사 덴티움") == "exact"
    assert classify_company_match("(주)덴티움", "(주)덴티움용인공장") == "branch"
    assert classify_company_match("세종메디칼", "신세종메디칼") == "partial"
    assert classify_company_match("메디칼", "세종메디칼") == "partial"


def test_view_orders_exact_then_branch_and_hides_partial_and_inactive() -> None:
    records = [
        _license("신세종메디칼", "판매업"),
        _license("(주)세종메디칼공장", "제조업", number="3"),
        _license("주식회사 세종메디칼", "수입업", number="2"),
        _license("(주)세종메디칼", "판매업", status="폐업", number="9"),
    ]

    view = build_business_license_view(records, "(주)세종메디칼")

    assert [(row["일치"], row["업종"]) for row in view.rows] == [
        ("정확 일치", "수입업"),
        ("같은 업체 지점·공장", "제조업"),
    ]
    assert view.hidden_inactive_count == 1
    assert view.hidden_partial_count == 1
    assert view.showing_partial_only is False


def test_view_can_include_inactive_and_partial() -> None:
    records = [
        _license("신세종메디칼", "판매업"),
        _license("(주)세종메디칼", "판매업", status="폐업"),
    ]

    view = build_business_license_view(
        records, "세종메디칼", include_inactive=True, include_partial=True
    )

    assert [row["일치"] for row in view.rows] == ["정확 일치", "이름 일부 일치"]
    assert view.hidden_inactive_count == 0
    assert view.hidden_partial_count == 0


def test_view_falls_back_to_flagged_partial_matches_when_no_exact_match() -> None:
    view = build_business_license_view([_license("신세종메디칼", "판매업")], "세종메디칼")

    assert view.showing_partial_only is True
    assert [row["일치"] for row in view.rows] == ["이름 일부 일치"]
    assert view.hidden_partial_count == 0


def test_dashboard_uses_business_license_view_with_default_filters() -> None:
    source = Path("pages/1_대시보드.py").read_text(encoding="utf-8")

    assert "from purchase_price.services.mfds_business_license_view import build_business_license_view" in source
    assert '"폐업·휴업·취소 업허가 포함"' in source
    assert '"이름 일부만 같은 다른 업체 포함"' in source
    assert "license_view.showing_partial_only" in source
    assert '"현재사용가능": item.is_active' not in source

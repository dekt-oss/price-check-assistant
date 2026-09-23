from decimal import Decimal
from types import SimpleNamespace

from purchase_price.domain import MatchGrade
from purchase_price.ui.purchase_workspace import (
    build_purchase_workspace_stats,
    supplier_rows,
)


def _candidate(
    *,
    price: str,
    supplier: str,
    institution: str,
    date: str,
    grade=MatchGrade.A,
):
    return SimpleNamespace(
        price=Decimal(price),
        supplier=supplier,
        demand_institution=institution,
        transaction_date=date,
        match_grade=grade,
    )


def test_workspace_stats_use_direct_evidence_only_for_price_band() -> None:
    direct_a = _candidate(
        price="9900000",
        supplier="공급사A",
        institution="병원1",
        date="2026-08-01",
    )
    direct_b = _candidate(
        price="13200000",
        supplier="공급사B",
        institution="병원2",
        date="2026-08-02",
        grade=MatchGrade.B,
    )
    category_reference = _candidate(
        price="50000000",
        supplier="참고공급사",
        institution="기관3",
        date="2026-08-03",
        grade=MatchGrade.C,
    )
    broad_reference = SimpleNamespace(
        price=Decimal("70000000"),
        reference_reason="동일 품목명 참고",
    )
    track_b = SimpleNamespace(
        candidates=(direct_a, direct_b, category_reference),
        reference_candidates=(broad_reference,),
    )
    market_bundle = SimpleNamespace(records=(object(), object(), object()))

    stats = build_purchase_workspace_stats(
        track_b=track_b,
        market_bundle=market_bundle,
        quote_unit_price=Decimal("12500000"),
    )

    assert stats.direct_count == 2
    assert stats.reference_count == 2
    assert stats.research_count == 3
    assert stats.supplier_count == 2
    assert stats.demand_institution_count == 2
    assert stats.min_price == Decimal("9900000")
    assert stats.median_price == Decimal("11550000")
    assert stats.max_price == Decimal("13200000")
    assert stats.latest_transaction_date == "2026-08-02"
    assert stats.quote_vs_median_percent == Decimal("8.2")


def test_supplier_rows_are_based_on_direct_procurement_only() -> None:
    direct_1 = _candidate(
        price="100",
        supplier="공급사A",
        institution="병원1",
        date="2026-08-01",
    )
    direct_2 = _candidate(
        price="120",
        supplier="공급사A",
        institution="병원2",
        date="2026-08-02",
        grade=MatchGrade.B,
    )
    reference = _candidate(
        price="999",
        supplier="참고공급사",
        institution="병원3",
        date="2026-08-03",
        grade=MatchGrade.C,
    )
    track_b = SimpleNamespace(
        candidates=(direct_1, direct_2, reference),
        reference_candidates=(),
    )

    rows = supplier_rows(track_b)

    assert rows == [
        {
            "공급업체": "공급사A",
            "직접거래건수": 2,
            "수요기관수": 2,
            "최저단가": Decimal("100"),
            "최고단가": Decimal("120"),
            "최근거래일": "2026-08-02",
            "근거": "나라장터 실제 납품요구 · A/B 직접근거",
        }
    ]

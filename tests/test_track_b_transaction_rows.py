from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

from purchase_price.domain import MatchGrade
from purchase_price.ui.track_b_transactions import (
    candidate_counts,
    has_transaction_candidates,
    model_price_group_rows,
    transaction_rows,
)


def test_legacy_comparison_without_reference_candidates_does_not_crash() -> None:
    legacy_candidate = SimpleNamespace(
        price=Decimal("2981000"),
        product_title="레이저프린터, Fujifilm, ApeosPrint C5570 GK",
        match_grade=MatchGrade.A,
    )
    legacy_comparison = SimpleNamespace(candidates=(legacy_candidate,), status="partial")

    rows = transaction_rows(legacy_comparison)

    assert candidate_counts(legacy_comparison) == (1, 0)
    assert has_transaction_candidates(legacy_comparison) is True
    assert rows == [
        {
            "가격": "2,981,000원",
            "총액": "미확인",
            "금액검증": "미확인",
            "제조사": "미확인",
            "모델": "미확인",
            "규격": "미확인",
            "품목식별번호": "미확인",
            "세부품명번호": "미확인",
            "판매처": "미확인",
            "구매처": "미확인",
            "거래일": "미확인",
            "수량/단위": "미확인",
            "거래기록": "나라장터 납품요구",
            "품목/모델": "레이저프린터, Fujifilm, ApeosPrint C5570 GK",
            "비교수준": "동일 모델",
        }
    ]


def test_reference_candidate_renders_purchase_facing_metadata() -> None:
    reference = SimpleNamespace(
        price=Decimal("9900000"),
        product_title="저출력심장충격기, Philips goldway, (CN)Efficia DFM100, 200J",
        reference_reason="모델명 포함 거래 참고 · 제조사/규격 직접 동일성 미검증",
        supplier="테스트공급사",
        demand_institution="테스트병원",
        transaction_date="2026-08-01",
        quantity=Decimal("1"),
        unit="대",
        transaction_type="나라장터 납품요구",
    )
    comparison = SimpleNamespace(
        candidates=(),
        reference_candidates=(reference,),
        status="success_0",
    )

    rows = transaction_rows(comparison)

    assert candidate_counts(comparison) == (0, 1)
    assert has_transaction_candidates(comparison) is True
    assert rows[0]["가격"] == "9,900,000원"
    assert rows[0]["판매처"] == "테스트공급사"
    assert rows[0]["구매처"] == "테스트병원"
    assert rows[0]["거래일"] == "2026-08-01"
    assert rows[0]["수량/단위"] == "1 대"
    assert rows[0]["비교수준"].startswith("모델명 포함 거래 참고")



def test_c_grade_candidate_counts_as_reference_not_direct() -> None:
    direct = SimpleNamespace(
        price=Decimal("12000000"),
        product_title="가스마취기, Getinge, FLOW-C",
        match_grade=MatchGrade.A,
    )
    category_reference = SimpleNamespace(
        price=Decimal("45000000"),
        product_title="가스마취기, 다른 규격",
        match_grade=MatchGrade.C,
    )
    broad_reference = SimpleNamespace(
        price=Decimal("50000000"),
        product_title="가스마취기 검색 참고",
        reference_reason="동일 품목명 참고",
    )
    comparison = SimpleNamespace(
        candidates=(direct, category_reference),
        reference_candidates=(broad_reference,),
        status="success",
    )

    assert candidate_counts(comparison) == (1, 2)
    rows = transaction_rows(comparison)
    assert rows[0]["비교수준"] == "동일 모델"
    assert rows[1]["비교수준"] == "동일 품목 참고"
    assert rows[2]["비교수준"] == "동일 품목명 참고"


def test_empty_legacy_comparison_is_safe() -> None:
    comparison = SimpleNamespace(candidates=(), status="success_0")

    assert transaction_rows(comparison) == []
    assert candidate_counts(comparison) == (0, 0)
    assert has_transaction_candidates(comparison) is False


def test_transaction_prices_are_comma_formatted() -> None:
    candidate = SimpleNamespace(
        price=Decimal("18900000"),
        product_title="전기수술기, Covidien, VLFT10GEN",
        match_grade=MatchGrade.B,
    )
    comparison = SimpleNamespace(candidates=(candidate,), reference_candidates=(), status="success")

    assert transaction_rows(comparison)[0]["가격"] == "18,900,000원"


def test_transaction_row_exposes_unit_price_total_and_identity_details() -> None:
    candidate = SimpleNamespace(
        price=Decimal("13200000"),
        total_amount=Decimal("26400000"),
        amount_check="consistent",
        manufacturer="Philips goldway",
        model_name="Efficia DFM100",
        specification="200J",
        product_id="12345678",
        detail_code="4217210101",
        product_title="저출력심장충격기, Philips goldway, Efficia DFM100, 200J",
        match_grade=MatchGrade.B,
        supplier="공급사",
        demand_institution="병원",
        transaction_date="2026-08-02",
        quantity=Decimal("2"),
        unit="대",
    )
    comparison = SimpleNamespace(candidates=(candidate,), reference_candidates=(), status="success")

    row = transaction_rows(comparison)[0]

    assert row["가격"] == "13,200,000원"
    assert row["총액"] == "26,400,000원"
    assert row["금액검증"] == "consistent"
    assert row["수량/단위"] == "2 대"
    assert row["제조사"] == "Philips goldway"
    assert row["모델"] == "Efficia DFM100"
    assert row["규격"] == "200J"
    assert row["품목식별번호"] == "12345678"
    assert row["세부품명번호"] == "4217210101"


def test_model_price_group_rows_use_direct_evidence_only() -> None:
    direct_a = SimpleNamespace(
        price=Decimal("9900000"),
        match_grade=MatchGrade.A,
        model_name="Efficia DFM100",
        specification="200J",
        quantity=Decimal("1"),
        transaction_date="2026-08-01",
    )
    direct_b = SimpleNamespace(
        price=Decimal("13200000"),
        match_grade=MatchGrade.B,
        model_name="Efficia DFM100",
        specification="200J",
        quantity=Decimal("2"),
        transaction_date="2026-08-02",
    )
    reference = SimpleNamespace(
        price=Decimal("50000000"),
        match_grade=MatchGrade.C,
        model_name="Other",
        specification="Other",
        quantity=Decimal("1"),
        transaction_date="2026-08-03",
    )
    comparison = SimpleNamespace(
        candidates=(direct_a, direct_b, reference),
        reference_candidates=(),
    )

    rows = model_price_group_rows(comparison)

    assert len(rows) == 1
    assert rows[0]["모델"] == "Efficia DFM100"
    assert rows[0]["규격"] == "200J"
    assert rows[0]["거래건수"] == 2
    assert rows[0]["최저단가"] == "9,900,000원"
    assert rows[0]["중앙값"] == "11,550,000원"
    assert rows[0]["최고단가"] == "13,200,000원"
    assert rows[0]["총수량"] == "3"
    assert rows[0]["최근거래일"] == "2026-08-02"

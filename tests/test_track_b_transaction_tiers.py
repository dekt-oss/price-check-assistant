from decimal import Decimal
from types import SimpleNamespace

from purchase_price.domain import MatchGrade
from purchase_price.ui.track_b_transactions import (
    direct_transaction_rows,
    reference_transaction_rows,
)


def _candidate(*, grade: MatchGrade, title: str, price: str):
    return SimpleNamespace(
        price=Decimal(price),
        match_grade=grade,
        product_title=title,
        manufacturer=None,
        model_name=title,
        specification=None,
        product_id=None,
        detail_code=None,
        supplier=None,
        demand_institution=None,
        transaction_date=None,
        quantity=None,
        unit=None,
        transaction_type=None,
        total_amount=None,
        amount_check=None,
        contract_delivery_type=None,
        contract_type=None,
        delivery_condition=None,
    )


def test_direct_and_reference_transaction_rows_are_disjoint() -> None:
    direct = _candidate(grade=MatchGrade.A, title="CN-6000", price="100")
    category_reference = _candidate(grade=MatchGrade.C, title="CN-6000 참고", price="200")
    broad_reference = SimpleNamespace(
        price=Decimal("300"),
        product_title="검색 참고",
        reference_reason="동일 품목명 참고",
        manufacturer=None,
        model_name=None,
        specification=None,
        product_id=None,
        detail_code=None,
        supplier=None,
        demand_institution=None,
        transaction_date=None,
        quantity=None,
        unit=None,
        transaction_type=None,
        total_amount=None,
        amount_check=None,
        contract_delivery_type=None,
        contract_type=None,
        delivery_condition=None,
    )
    track_b = SimpleNamespace(
        candidates=(direct, category_reference),
        reference_candidates=(broad_reference,),
    )

    direct_rows = direct_transaction_rows(track_b)
    reference_rows = reference_transaction_rows(track_b)

    assert len(direct_rows) == 1
    assert direct_rows[0]["비교수준"] == "동일 모델"
    assert len(reference_rows) == 2
    assert {row["비교수준"] for row in reference_rows} == {
        "동일 품목 참고",
        "동일 품목명 참고",
    }


def test_reference_only_search_does_not_create_direct_rows() -> None:
    references = tuple(
        _candidate(grade=MatchGrade.C, title=f"참고-{index}", price=str(100 + index))
        for index in range(25)
    )
    track_b = SimpleNamespace(candidates=references, reference_candidates=())

    assert direct_transaction_rows(track_b) == []
    assert len(reference_transaction_rows(track_b)) == 25

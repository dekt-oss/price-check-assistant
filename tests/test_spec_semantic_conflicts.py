import pytest

from purchase_price.domain import MatchGrade
from purchase_price.schemas import ProductQuery
from purchase_price.services.product_matching import ProductIdentity, grade_product_identity


@pytest.mark.parametrize(
    ("query_spec", "candidate_spec"),
    [
        ("182L", "200L"),
        ("220V", "110V"),
        ("1.5kW", "1200W"),
        ("32GB", "16GB"),
        ("10개입", "20개입"),
    ],
)
def test_single_measurement_family_conflict_fails_closed_to_x(
    query_spec: str,
    candidate_spec: str,
) -> None:
    decision = grade_product_identity(
        ProductQuery(
            product_name="의료기기",
            manufacturer="예시메디칼",
            model_name="M-100",
            specification=query_spec,
        ),
        ProductIdentity(
            product_name="의료기기",
            manufacturer="예시메디칼",
            model_name="M-100",
            specification=candidate_spec,
        ),
    )

    assert decision.grade == MatchGrade.X
    assert decision.specification_state == "explicit_conflict"


def test_equivalent_cross_unit_volume_is_not_a_conflict() -> None:
    decision = grade_product_identity(
        ProductQuery(
            product_name="의료기기",
            manufacturer="예시메디칼",
            model_name="M-100",
            specification="1L",
        ),
        ProductIdentity(
            product_name="의료기기",
            manufacturer="예시메디칼",
            model_name="M-100",
            specification="1000mL",
        ),
    )

    assert decision.grade == MatchGrade.B
    assert decision.specification_state == "different_or_incomplete"


def test_missing_same_measurement_family_is_incomplete_not_conflict() -> None:
    decision = grade_product_identity(
        ProductQuery(
            product_name="의료기기",
            manufacturer="예시메디칼",
            model_name="M-100",
            specification="220V",
        ),
        ProductIdentity(
            product_name="의료기기",
            manufacturer="예시메디칼",
            model_name="M-100",
            specification="이동형",
        ),
    )

    assert decision.grade == MatchGrade.B
    assert decision.specification_state == "different_or_incomplete"


def test_multi_family_spec_stays_reviewable_instead_of_overclaiming_conflict() -> None:
    decision = grade_product_identity(
        ProductQuery(
            product_name="노트북컴퓨터",
            manufacturer="삼성전자",
            model_name="NT960XJG-K72AG",
            specification="32GB 1TB",
        ),
        ProductIdentity(
            product_name="노트북컴퓨터",
            manufacturer="Samsung",
            model_name="NT960XJG-K72AG",
            specification="16GB 1TB",
        ),
    )

    assert decision.grade == MatchGrade.B
    assert decision.specification_state == "different_or_incomplete"

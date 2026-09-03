from purchase_price.domain import MatchGrade
from purchase_price.schemas import ProductQuery
from purchase_price.services.product_matching import (
    ProductIdentity,
    grade_product_identity,
    parse_g2b_identity,
)


def _c5570_query() -> ProductQuery:
    return ProductQuery(
        product_name="컬러 레이저프린터",
        manufacturer="FUJIFILM Business Innovation",
        model_name="ApeosPrint C5570 GK",
        specification="A3 55ppm",
    )


def test_generic_cn_qualifier_string_cannot_unlock_direct_grade() -> None:
    decision = grade_product_identity(
        _c5570_query(),
        ProductIdentity(
            product_name="레이저프린터",
            manufacturer="Fujifilm",
            model_name="ApeosPrint C5570 GK",
            model_qualifier="CN",
            specification="A3 55ppm",
        ),
    )

    assert decision.grade == MatchGrade.X
    assert decision.model_state == "exact_with_unverified_qualifier"


def test_g2b_parser_is_the_boundary_that_verifies_cn_origin_metadata() -> None:
    identity = parse_g2b_identity(
        "레이저프린터, Fujifilm, (CN)ApeosPrint C5570 GK, A3, 55ppm/55ppm"
    )
    decision = grade_product_identity(_c5570_query(), identity)

    assert identity.model_qualifier == "CN"
    assert identity.model_qualifier_verified_as_origin is True
    assert decision.grade == MatchGrade.A
    assert decision.model_state == "exact_with_verified_origin"


def test_a3_query_does_not_accept_a4_candidate_only_because_speed_matches() -> None:
    identity = parse_g2b_identity(
        "레이저프린터, Fujifilm, (CN)ApeosPrint C5570 GK, A4, 55ppm/55ppm"
    )
    decision = grade_product_identity(_c5570_query(), identity)

    assert decision.grade == MatchGrade.B
    assert decision.specification_state == "different_or_incomplete"

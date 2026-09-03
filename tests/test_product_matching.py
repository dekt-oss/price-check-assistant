from purchase_price.domain import MatchGrade
from purchase_price.schemas import ProductQuery
from purchase_price.services.product_matching import (
    ProductIdentity,
    grade_product_identity,
    load_manufacturer_aliases,
    parse_g2b_identity,
)


def test_manufacturer_alias_registry_normalizes_korean_and_english_names() -> None:
    aliases = load_manufacturer_aliases()
    decision = grade_product_identity(
        ProductQuery(
            product_name="노트북컴퓨터",
            manufacturer="삼성전자",
            model_name="NT960XJG-K72AG",
        ),
        ProductIdentity(
            product_name="노트북컴퓨터",
            manufacturer="Samsung Electronics",
            model_name="NT960XJG K72AG",
        ),
        manufacturer_aliases=aliases,
    )

    assert decision.grade == MatchGrade.A
    assert decision.model_state == "exact"
    assert decision.manufacturer_state == "exact_or_alias"


def test_exact_model_with_missing_manufacturer_is_downgraded_to_b() -> None:
    decision = grade_product_identity(
        ProductQuery(
            product_name="인공호흡기",
            manufacturer="Stephan",
            model_name="Sophie",
        ),
        ProductIdentity(product_name="인공호흡기", model_name="Sophie"),
    )

    assert decision.grade == MatchGrade.B
    assert decision.manufacturer_state == "missing"


def test_exact_model_with_incomplete_or_different_spec_is_b() -> None:
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


def test_explicit_manufacturer_conflict_fails_closed_even_when_model_matches() -> None:
    decision = grade_product_identity(
        ProductQuery(
            product_name="인공호흡기",
            manufacturer="Stephan",
            model_name="Sophie",
        ),
        ProductIdentity(
            product_name="인공호흡기",
            manufacturer="Other Medical",
            model_name="Sophie",
        ),
    )

    assert decision.grade == MatchGrade.X
    assert decision.manufacturer_state == "conflict"


def test_explicit_model_conflict_never_becomes_a_or_b() -> None:
    decision = grade_product_identity(
        ProductQuery(
            product_name="인공호흡기",
            manufacturer="Stephan",
            model_name="Sophie",
        ),
        ProductIdentity(
            product_name="인공호흡기",
            manufacturer="Stephan",
            model_name="CSI-2000",
        ),
    )

    assert decision.grade == MatchGrade.X
    assert decision.model_state == "conflict"


def test_same_product_class_without_exact_model_is_c_reference_only() -> None:
    decision = grade_product_identity(
        ProductQuery(product_name="인공호흡기", manufacturer="Stephan"),
        ProductIdentity(product_name="인공호흡기", manufacturer="Stephan", model_name="Sophie"),
    )

    assert decision.grade == MatchGrade.C


def test_d_requires_explicit_functional_alternative_relationship() -> None:
    decision = grade_product_identity(
        ProductQuery(product_name="인공호흡기", model_name="Sophie"),
        ProductIdentity(product_name="마취기", model_name=None),
        functional_alternative=True,
    )

    assert decision.grade == MatchGrade.D


def test_g2b_identity_parser_uses_common_live_title_shape_without_guessing_short_rows() -> None:
    parsed = parse_g2b_identity("인공호흡기, 조선기기, CSI-2000, 운반형")
    short = parse_g2b_identity("인공호흡기")

    assert parsed.product_name == "인공호흡기"
    assert parsed.manufacturer == "조선기기"
    assert parsed.model_name == "CSI-2000"
    assert parsed.specification == "운반형"
    assert short.product_name == "인공호흡기"
    assert short.manufacturer is None
    assert short.model_name is None

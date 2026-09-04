from purchase_price.domain import MatchGrade
from purchase_price.schemas import ProductQuery
from purchase_price.services.product_matching import (
    ProductIdentity,
    grade_product_identity,
    load_manufacturer_aliases,
    parse_g2b_identity,
)


def test_manufacturer_alias_and_spec_evidence_can_produce_a() -> None:
    aliases = load_manufacturer_aliases()
    decision = grade_product_identity(
        ProductQuery(
            product_name="노트북컴퓨터",
            manufacturer="삼성전자",
            model_name="NT960XJG-K72AG",
            specification="32GB 1TB",
        ),
        ProductIdentity(
            product_name="노트북컴퓨터",
            manufacturer="Samsung Electronics",
            model_name="NT960XJG K72AG",
            specification="32GB 1TB",
        ),
        manufacturer_aliases=aliases,
    )

    assert decision.grade == MatchGrade.A
    assert decision.model_state == "exact"
    assert decision.manufacturer_state == "exact_or_alias"
    assert decision.specification_state == "compatible"


def test_exact_model_and_manufacturer_without_real_spec_is_b() -> None:
    decision = grade_product_identity(
        ProductQuery(
            product_name="인공호흡기",
            manufacturer="Stephan",
            model_name="Sophie",
            specification="Sophie",
        ),
        ProductIdentity(
            product_name="인공호흡기",
            manufacturer="Stephan",
            model_name="Sophie",
            specification="운반형",
        ),
    )

    assert decision.grade == MatchGrade.B
    assert decision.specification_state == "not_provided"


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


def test_model_specific_query_rejects_bare_product_class_as_x() -> None:
    decision = grade_product_identity(
        ProductQuery(
            product_name="인공호흡기",
            manufacturer="Stephan",
            model_name="Sophie",
        ),
        ProductIdentity(product_name="인공호흡기"),
    )

    assert decision.grade == MatchGrade.X
    assert decision.model_state == "missing"
    assert decision.manufacturer_state == "missing"


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


def test_g2b_parser_splits_leading_qualifiers_without_interpreting_them() -> None:
    laptop = parse_g2b_identity(
        "노트북컴퓨터, (주문자상표부착)삼성전자, (CN)NT750XGK-KG56P, Intel Core 5 120U(1.4GHz)"
    )

    assert laptop.manufacturer == "삼성전자"
    assert laptop.manufacturer_qualifier == "주문자상표부착"
    assert laptop.model_name == "NT750XGK-KG56P"
    assert laptop.model_qualifier == "CN"
    assert laptop.specification == "Intel Core 5 120U(1.4GHz)"

    plain = parse_g2b_identity("인공호흡기, 조선기기, CSI-2000, 운반형")
    assert plain.manufacturer_qualifier is None
    assert plain.model_qualifier is None


def test_same_model_behind_unknown_qualifier_stays_x_but_is_not_reported_as_conflict() -> None:
    decision = grade_product_identity(
        ProductQuery(
            product_name="노트북컴퓨터",
            manufacturer="삼성전자",
            model_name="NT960XJG-K72AG",
            specification="NT960XJG-K72AG",
        ),
        parse_g2b_identity(
            "노트북컴퓨터, 삼성전자, (ZZ)NT960XJG-K72AG, Intel Core Ultra 7 256V"
        ),
    )

    assert decision.grade == MatchGrade.X
    assert decision.model_state == "exact_with_unverified_qualifier"
    assert decision.manufacturer_state == "exact_or_alias"
    assert "model_qualifier=ZZ" in decision.note


def test_verified_cn_origin_qualifier_does_not_reduce_exact_model_identity() -> None:
    decision = grade_product_identity(
        ProductQuery(
            product_name="컬러 레이저프린터",
            manufacturer="FUJIFILM Business Innovation",
            model_name="ApeosPrint C5570 GK",
            specification="A3 55ppm",
        ),
        parse_g2b_identity(
            "레이저프린터, Fujifilm, (CN)ApeosPrint C5570 GK, A3, 55ppm/55ppm"
        ),
    )

    assert decision.grade == MatchGrade.A
    assert decision.model_state == "exact_with_verified_origin"
    assert decision.manufacturer_state == "exact_or_alias"
    assert decision.specification_state == "compatible"
    assert "model_qualifier=CN" in decision.note


def test_verified_vn_origin_qualifier_can_produce_b_when_query_has_no_real_spec() -> None:
    decision = grade_product_identity(
        ProductQuery(
            product_name="노트북컴퓨터",
            manufacturer="삼성전자",
            model_name="NT960XJG-K72AG",
            specification="NT960XJG-K72AG",
        ),
        parse_g2b_identity(
            "노트북컴퓨터, 삼성전자, (VN)NT960XJG-K72AG, Intel Core Ultra 7 256V"
        ),
    )

    assert decision.grade == MatchGrade.B
    assert decision.model_state == "exact_with_verified_origin"
    assert decision.manufacturer_state == "exact_or_alias"
    assert decision.specification_state == "not_provided"


def test_different_model_behind_qualifier_is_still_an_explicit_conflict() -> None:
    decision = grade_product_identity(
        ProductQuery(
            product_name="노트북컴퓨터",
            manufacturer="삼성전자",
            model_name="NT960XJG-K72AG",
        ),
        parse_g2b_identity(
            "노트북컴퓨터, 삼성전자, (VN)NT960XHA-KG71G, Intel Core Ultra 7 256V"
        ),
    )

    assert decision.grade == MatchGrade.X
    assert decision.model_state == "conflict"


def test_manufacturer_qualifier_caps_exact_model_at_b_like_missing_manufacturer() -> None:
    decision = grade_product_identity(
        ProductQuery(
            product_name="노트북컴퓨터",
            manufacturer="삼성전자",
            model_name="NT750XGK-KG56P",
            specification="Intel Core 5 120U",
        ),
        parse_g2b_identity(
            "노트북컴퓨터, (주문자상표부착)삼성전자, NT750XGK-KG56P, Intel Core 5 120U(1.4GHz)"
        ),
    )

    assert decision.grade == MatchGrade.B
    assert decision.manufacturer_state == "alias_with_unverified_qualifier"
    assert decision.specification_state == "compatible"


def test_manufacturer_qualifier_does_not_unlock_c_for_model_specific_query() -> None:
    decision = grade_product_identity(
        ProductQuery(
            product_name="노트북컴퓨터",
            manufacturer="삼성전자",
            model_name="NT960XJG-K72AG",
        ),
        ProductIdentity(
            product_name="노트북컴퓨터",
            manufacturer="삼성전자",
            manufacturer_qualifier="주문자상표부착",
        ),
    )

    assert decision.grade == MatchGrade.X


def test_narrower_product_class_substring_is_not_a_c_candidate() -> None:
    """`모니터` must not pull in `심전도모니터` just because one label contains the other."""

    decision = grade_product_identity(
        ProductQuery(product_name="모니터", manufacturer="에이서"),
        ProductIdentity(
            product_name="심전도모니터",
            manufacturer="에이서",
            model_name="ECG-9020",
        ),
    )

    assert decision.grade == MatchGrade.X
    assert "product_class=related_unverified" in decision.note


def test_broader_product_class_substring_is_not_a_c_candidate() -> None:
    """The containment direction does not matter: neither side may promote the other."""

    decision = grade_product_identity(
        ProductQuery(product_name="레이저프린터", manufacturer="Fujifilm"),
        ProductIdentity(
            product_name="컬러 레이저프린터",
            manufacturer="Fujifilm",
            model_name="ApeosPrint C5570 GK",
        ),
    )

    assert decision.grade == MatchGrade.X
    assert "product_class=related_unverified" in decision.note


def test_live_g2b_class_variant_is_not_a_c_candidate() -> None:
    """`융복합인공호흡기` is a real live G2B title observed against a `인공호흡기` search."""

    decision = grade_product_identity(
        ProductQuery(product_name="인공호흡기", manufacturer="Stephan"),
        ProductIdentity(
            product_name="융복합인공호흡기",
            manufacturer="Stephan",
            model_name="CSI-2000",
        ),
    )

    assert decision.grade == MatchGrade.X
    assert "product_class=related_unverified" in decision.note


def test_punctuation_and_spacing_variants_of_one_class_still_reach_c() -> None:
    """`인공 호흡기` normalizes to `인공호흡기`, so the exact-equality rule still admits it."""

    decision = grade_product_identity(
        ProductQuery(product_name="인공 호흡기", manufacturer="Stephan"),
        ProductIdentity(
            product_name="인공호흡기",
            manufacturer="Stephan",
            model_name="Sophie",
        ),
    )

    assert decision.grade == MatchGrade.C
    assert "product_class=compatible" in decision.note


def test_exact_model_grade_is_unaffected_by_differing_product_class_labels() -> None:
    """The A/B path never consults product class, so the C tightening cannot break it."""

    decision = grade_product_identity(
        ProductQuery(
            product_name="컬러 레이저프린터",
            manufacturer="FUJIFILM Business Innovation",
            model_name="ApeosPrint C5570 GK",
            specification="A3 55ppm",
        ),
        parse_g2b_identity("레이저프린터, Fujifilm, (CN)ApeosPrint C5570 GK, A3, 55ppm/55ppm"),
    )

    assert decision.grade == MatchGrade.A
    assert "product_class=related_unverified" in decision.note

from purchase_price.services.price_conditions import PriceConditionProfile, UNKNOWN
from purchase_price.services.quote_condition_comparison import (
    ConditionComparisonStatus,
    build_quote_condition_profile,
    compare_quote_to_evidence_conditions,
)


def _evidence(**overrides: str) -> PriceConditionProfile:
    values = {
        "vat": UNKNOWN,
        "quantity_unit": UNKNOWN,
        "delivery": UNKNOWN,
        "installation": UNKNOWN,
        "options": UNKNOWN,
        "warranty": UNKNOWN,
        "maintenance": UNKNOWN,
        "basis_date": "거래일 2026-09-01",
    }
    values.update(overrides)
    return PriceConditionProfile(**values)


def test_explicit_same_conditions_match() -> None:
    quote = build_quote_condition_profile(
        vat="포함",
        delivery="무료",
        installation="별도",
        options="기본구성",
        warranty="2년",
        maintenance="별도계약",
    )
    evidence = _evidence(
        vat="VAT 포함",
        delivery="배송 무료",
        installation="설치 별도",
        options="기본구성",
        warranty="24개월",
        maintenance="서비스 별도",
    )

    comparison = compare_quote_to_evidence_conditions(quote, evidence)

    assert comparison.conflict_count == 0
    assert comparison.unknown_count == 0
    assert comparison.match_count == 6
    assert comparison.fully_aligned is True
    assert comparison.status_label == "조건 일치"


def test_explicit_conflicts_are_not_hidden() -> None:
    quote = build_quote_condition_profile(
        vat="포함",
        delivery="무료",
        installation="포함",
        warranty="1년",
    )
    evidence = _evidence(
        vat="별도",
        delivery="배송 별도",
        installation="설치 포함",
        warranty="24개월",
    )

    comparison = compare_quote_to_evidence_conditions(quote, evidence)
    statuses = {item.label: item.status for item in comparison.comparisons}

    assert statuses["VAT"] == ConditionComparisonStatus.CONFLICT
    assert statuses["배송"] == ConditionComparisonStatus.CONFLICT
    assert statuses["설치"] == ConditionComparisonStatus.MATCH
    assert statuses["보증"] == ConditionComparisonStatus.CONFLICT
    assert comparison.conflict_count == 3
    assert comparison.status_label == "조건 충돌"
    assert comparison.fully_aligned is False


def test_missing_condition_stays_unknown_instead_of_matching() -> None:
    quote = build_quote_condition_profile(vat="포함")
    evidence = _evidence(vat="VAT 포함")

    comparison = compare_quote_to_evidence_conditions(quote, evidence)

    assert comparison.match_count == 1
    assert comparison.unknown_count == 5
    assert comparison.conflict_count == 0
    assert comparison.status_label == "조건 확인 필요"
    assert comparison.fully_aligned is False


def test_free_and_included_are_kept_distinct() -> None:
    quote = build_quote_condition_profile(delivery="무료")
    evidence = _evidence(delivery="배송 포함")

    comparison = compare_quote_to_evidence_conditions(quote, evidence)
    delivery = next(item for item in comparison.comparisons if item.label == "배송")

    assert delivery.status == ConditionComparisonStatus.CONFLICT

from datetime import date
from decimal import Decimal

from purchase_price.domain import ComparisonScope, EvidenceType, MatchGrade, SourceType
from purchase_price.schemas import CollectedPrice, ProductQuery
from purchase_price.services.configuration_fingerprint import (
    ConfigurationAxisStatus,
    compare_quote_evidence_configuration,
)
from purchase_price.services.quote_comparability import QuoteComparabilityContext
from purchase_price.services.quote_comparable_approval import quote_evidence_pair_key
from purchase_price.services.quote_condition_comparison import build_quote_condition_profile


def _conditions():
    return build_quote_condition_profile(
        vat="포함",
        delivery="무료",
        installation="포함",
        options="기본구성",
        warranty="1년",
        maintenance="별도",
    )


def _evidence(**overrides: object) -> CollectedPrice:
    values: dict[str, object] = {
        "manufacturer": "Acme",
        "product_name": "Infusion Pump",
        "model_name": "IP-200",
        "specification": "IP-200",
        "price": Decimal("1000000"),
        "evidence_type": EvidenceType.DELIVERY_ORDER_UNIT_PRICE,
        "source_type": SourceType.PROCUREMENT,
        "source_name": "나라장터",
        "source_url": "https://example.invalid/evidence",
        "original_title": "Acme IP-200 납품",
        "collected_at": date(2026, 9, 1),
        "transaction_date": date(2026, 8, 30),
        "quantity": Decimal("1"),
        "unit": "대",
        "currency": "KRW",
        "vat_status": "포함",
        "conditions": "배송비=무료; 설치비=포함; 옵션=기본구성; 보증기간=1년; 유지보수=별도계약",
        "match_grade": MatchGrade.A,
        "comparison_scope": ComparisonScope.OBSERVED_ONLY,
    }
    values.update(overrides)
    return CollectedPrice(**values)  # type: ignore[arg-type]


def _compare(specification: str, evidence: CollectedPrice):
    return compare_quote_evidence_configuration(
        quote_identity=ProductQuery(
            product_name="Infusion Pump",
            manufacturer="Acme",
            model_name="IP-200",
            specification=specification,
        ),
        quote_quantity=Decimal("1"),
        quote_unit="대",
        quote_conditions=_conditions(),
        evidence=evidence,
    )


def test_placeholder_specification_never_becomes_match() -> None:
    result = _compare("미확인", _evidence(specification="미확인"))

    axis = result.axis("specification")
    assert axis.status == ConfigurationAxisStatus.UNKNOWN
    assert axis.required is False


def test_real_quote_spec_with_placeholder_evidence_blocks_as_unknown() -> None:
    result = _compare("IP-200", _evidence(specification="미확인"))

    axis = result.axis("specification")
    assert axis.status == ConfigurationAxisStatus.UNKNOWN
    assert axis.required is True
    assert "핵심 규격·구성 미확인" in result.blocking_reasons


def test_decimal_measurement_punctuation_is_not_collapsed_into_false_match() -> None:
    result = _compare("1.5kW", _evidence(specification="15kW", match_grade=MatchGrade.B))

    assert result.axis("specification").status == ConfigurationAxisStatus.CONFLICT
    assert "핵심 규격·구성 충돌" in result.blocking_reasons


def test_source_title_change_invalidates_quote_evidence_pair_key() -> None:
    context = QuoteComparabilityContext(
        quote_unit_price=Decimal("1100000"),
        quantity=Decimal("1"),
        unit="대",
        quote_date=date(2026, 9, 1),
        conditions=_conditions(),
        quote_identity=ProductQuery(
            product_name="Infusion Pump",
            manufacturer="Acme",
            model_name="IP-200",
            specification="IP-200",
        ),
    )
    evidence = _evidence()
    changed_title = _evidence(original_title="Acme IP-200 새 원문 제목")

    assert quote_evidence_pair_key(context, evidence) != quote_evidence_pair_key(
        context, changed_title
    )

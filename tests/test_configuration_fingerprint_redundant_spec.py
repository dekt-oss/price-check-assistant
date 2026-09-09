from datetime import date
from decimal import Decimal

from purchase_price.domain import ComparisonScope, EvidenceType, MatchGrade, SourceType
from purchase_price.schemas import CollectedPrice, ProductQuery
from purchase_price.services.configuration_fingerprint import (
    ConfigurationAxisStatus,
    compare_quote_evidence_configuration,
)
from purchase_price.services.quote_condition_comparison import build_quote_condition_profile


def test_exact_spec_repeating_model_is_confirmed_not_unknown() -> None:
    quote = ProductQuery(
        product_name="Infusion Pump",
        manufacturer="Acme",
        model_name="IP-200",
        specification="IP-200",
    )
    evidence = CollectedPrice(
        manufacturer="Acme",
        product_name="Infusion Pump",
        model_name="IP-200",
        specification="IP-200",
        price=Decimal("1000000"),
        evidence_type=EvidenceType.DELIVERY_ORDER_UNIT_PRICE,
        source_type=SourceType.PROCUREMENT,
        source_name="나라장터",
        source_url="https://example.invalid/evidence",
        collected_at=date(2026, 9, 1),
        transaction_date=date(2026, 8, 30),
        quantity=Decimal("1"),
        unit="대",
        currency="KRW",
        vat_status="포함",
        conditions="배송비=무료; 설치비=포함; 옵션=기본구성; 보증기간=1년; 유지보수=별도계약",
        match_grade=MatchGrade.A,
        comparison_scope=ComparisonScope.OBSERVED_ONLY,
    )
    conditions = build_quote_condition_profile(
        vat="포함",
        delivery="무료",
        installation="포함",
        options="기본구성",
        warranty="1년",
        maintenance="별도",
    )

    result = compare_quote_evidence_configuration(
        quote_identity=quote,
        quote_quantity=Decimal("1"),
        quote_unit="대",
        quote_conditions=conditions,
        evidence=evidence,
    )

    assert result.axis("specification").status == ConfigurationAxisStatus.MATCH
    assert "핵심 규격·구성 미확인" not in result.blocking_reasons

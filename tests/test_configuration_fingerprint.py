from datetime import date
from decimal import Decimal

from purchase_price.domain import ComparisonScope, EvidenceType, MatchGrade, SourceType
from purchase_price.schemas import CollectedPrice, ProductQuery
from purchase_price.services.configuration_fingerprint import (
    ConfigurationAxisStatus,
    compare_quote_evidence_configuration,
)
from purchase_price.services.quote_condition_comparison import build_quote_condition_profile


def _evidence(**overrides: object) -> CollectedPrice:
    values: dict[str, object] = {
        "manufacturer": "Maquet",
        "product_name": "가스마취기",
        "model_name": "FLOW-C",
        "specification": "FLOW-C console",
        "price": Decimal("66000000"),
        "evidence_type": EvidenceType.DELIVERY_ORDER_UNIT_PRICE,
        "source_type": SourceType.PROCUREMENT,
        "source_name": "나라장터",
        "source_url": "https://example.invalid/evidence",
        "collected_at": date(2026, 9, 1),
        "transaction_date": date(2026, 8, 30),
        "quantity": Decimal("1"),
        "unit": "set",
        "currency": "KRW",
        "vat_status": "포함",
        "conditions": (
            "배송비=무료; 설치비=포함; 옵션=Desflurane; 보증기간=3년; 유지보수=별도계약"
        ),
        "match_grade": MatchGrade.A,
        "comparison_scope": ComparisonScope.OBSERVED_ONLY,
    }
    values.update(overrides)
    return CollectedPrice(**values)  # type: ignore[arg-type]


def _conditions(**overrides: str) -> object:
    values = {
        "vat": "VAT 포함",
        "delivery": "무료",
        "installation": "설치 포함",
        "options": "Desflurane",
        "warranty": "3년",
        "maintenance": "별도",
    }
    values.update(overrides)
    return build_quote_condition_profile(**values)


def _quote(**overrides: str) -> ProductQuery:
    values = {
        "product_name": "가스마취기",
        "manufacturer": "Maquet",
        "model_name": "FLOW-C",
        "specification": "FLOW-C console",
    }
    values.update(overrides)
    return ProductQuery(**values)


def test_matching_flow_c_configuration_is_ready() -> None:
    result = compare_quote_evidence_configuration(
        quote_identity=_quote(),
        quote_quantity=Decimal("1"),
        quote_unit="set",
        quote_conditions=_conditions(),  # type: ignore[arg-type]
        evidence=_evidence(),
    )

    assert result.ready_for_quote_comparison is True
    assert result.blocking_reasons == ()
    assert result.axis("manufacturer").status == ConfigurationAxisStatus.MATCH
    assert result.axis("model").status == ConfigurationAxisStatus.MATCH
    assert result.axis("specification").status == ConfigurationAxisStatus.MATCH
    assert result.axis("warranty").status == ConfigurationAxisStatus.MATCH


def test_flow_c20_is_an_explicit_model_conflict() -> None:
    result = compare_quote_evidence_configuration(
        quote_identity=_quote(),
        quote_quantity=Decimal("1"),
        quote_unit="set",
        quote_conditions=_conditions(),  # type: ignore[arg-type]
        evidence=_evidence(model_name="FLOW-C20", match_grade=MatchGrade.B),
    )

    assert result.axis("model").status == ConfigurationAxisStatus.CONFLICT
    assert "모델 충돌" in result.blocking_reasons


def test_water_jacket_vs_air_jacket_is_explicit_configuration_conflict() -> None:
    result = compare_quote_evidence_configuration(
        quote_identity=ProductQuery(
            product_name="CO2 Incubator",
            manufacturer="ASTEC",
            model_name="APC-30D",
            specification="CO₂ Incubator (Water Jacket)",
        ),
        quote_quantity=Decimal("1"),
        quote_unit="대",
        quote_conditions=build_quote_condition_profile(
            vat="포함",
            delivery="무료",
            installation="포함",
            options="기본구성",
            warranty="1년",
            maintenance="별도",
        ),
        evidence=_evidence(
            manufacturer="ASTEC",
            product_name="CO2 Incubator",
            model_name="APC-30D",
            specification="CO2 Incubator Air Jacket",
            quantity=Decimal("1"),
            unit="대",
            conditions="배송비=무료; 설치비=포함; 옵션=기본구성; 보증기간=1년; 유지보수=별도",
        ),
    )

    assert result.axis("specification").status == ConfigurationAxisStatus.CONFLICT
    assert "핵심 규격·구성 충돌" in result.blocking_reasons


def test_present_quote_spec_with_missing_public_spec_stays_unknown() -> None:
    result = compare_quote_evidence_configuration(
        quote_identity=_quote(specification="FLOW-C Desflurane vaporizer"),
        quote_quantity=Decimal("1"),
        quote_unit="set",
        quote_conditions=_conditions(),  # type: ignore[arg-type]
        evidence=_evidence(specification=""),
    )

    assert result.axis("specification").status == ConfigurationAxisStatus.UNKNOWN
    assert "핵심 규격·구성 미확인" in result.blocking_reasons


def test_desflurane_vs_sevoflurane_and_warranty_difference_conflict() -> None:
    result = compare_quote_evidence_configuration(
        quote_identity=_quote(),
        quote_quantity=Decimal("1"),
        quote_unit="set",
        quote_conditions=_conditions(options="Desflurane", warranty="3년"),  # type: ignore[arg-type]
        evidence=_evidence(
            conditions="배송비=무료; 설치비=포함; 옵션=Sevoflurane; 보증기간=1년; 유지보수=별도계약"
        ),
    )

    assert result.axis("options").status == ConfigurationAxisStatus.CONFLICT
    assert result.axis("warranty").status == ConfigurationAxisStatus.CONFLICT


def test_missing_warranty_is_unknown_not_match() -> None:
    result = compare_quote_evidence_configuration(
        quote_identity=_quote(),
        quote_quantity=Decimal("1"),
        quote_unit="set",
        quote_conditions=_conditions(warranty="3년"),  # type: ignore[arg-type]
        evidence=_evidence(
            conditions="배송비=무료; 설치비=포함; 옵션=Desflurane; 유지보수=별도계약"
        ),
    )

    assert result.axis("warranty").status == ConfigurationAxisStatus.UNKNOWN
    assert "보증 미확인" in result.blocking_reasons


def test_fingerprint_never_mutates_public_evidence() -> None:
    evidence = _evidence()
    original_scope = evidence.comparison_scope

    compare_quote_evidence_configuration(
        quote_identity=_quote(),
        quote_quantity=Decimal("1"),
        quote_unit="set",
        quote_conditions=_conditions(),  # type: ignore[arg-type]
        evidence=evidence,
    )

    assert evidence.comparison_scope == original_scope == ComparisonScope.OBSERVED_ONLY

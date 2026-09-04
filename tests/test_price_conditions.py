from datetime import date
from decimal import Decimal

from purchase_price.domain import ComparisonScope, EvidenceType, MatchGrade, SourceType
from purchase_price.schemas import CollectedPrice
from purchase_price.services.price_conditions import (
    UNKNOWN,
    build_price_condition_profile,
)


def _item(**overrides: object) -> CollectedPrice:
    values: dict[str, object] = {
        "manufacturer": "예시",
        "product_name": "의료기기",
        "model_name": "M-1",
        "specification": None,
        "price": Decimal("1000000"),
        "evidence_type": EvidenceType.PUBLIC_SALE_PRICE,
        "source_type": SourceType.MANUFACTURER,
        "source_name": "공식가격",
        "source_url": "https://example.invalid",
        "collected_at": date(2026, 9, 4),
        "match_grade": MatchGrade.A,
        "comparison_scope": ComparisonScope.OBSERVED_ONLY,
    }
    values.update(overrides)
    return CollectedPrice(**values)  # type: ignore[arg-type]


def test_profile_preserves_only_explicit_conditions() -> None:
    profile = build_price_condition_profile(
        _item(
            vat_status="VAT 포함",
            quantity=Decimal("2"),
            unit="대",
            transaction_date=date(2026, 8, 31),
            conditions=(
                "배송비=포함; 설치비=별도; 옵션=기본구성; 보증기간=2년; 유지보수=별도계약"
            ),
        )
    )

    assert profile.vat == "VAT 포함"
    assert profile.quantity_unit == "2 대"
    assert profile.delivery == "포함"
    assert profile.installation == "별도"
    assert profile.options == "기본구성"
    assert profile.warranty == "2년"
    assert profile.maintenance == "별도계약"
    assert profile.basis_date == "거래일 2026-08-31"
    assert profile.completeness_percent == 100
    assert profile.missing_labels == ()


def test_generic_procurement_conditions_do_not_invent_commercial_terms() -> None:
    profile = build_price_condition_profile(
        _item(
            conditions="공급업체=서울메디칼; 수요기관=예시병원; 계약구분=납품",
        )
    )

    assert profile.delivery == UNKNOWN
    assert profile.installation == UNKNOWN
    assert profile.options == UNKNOWN
    assert profile.warranty == UNKNOWN
    assert profile.maintenance == UNKNOWN
    assert profile.basis_date == "수집/검증일 2026-09-04"
    assert set(profile.missing_labels) >= {"VAT", "배송", "설치", "옵션", "보증", "유지보수"}


def test_partial_quantity_is_not_treated_as_complete_quantity_unit() -> None:
    profile = build_price_condition_profile(_item(quantity=Decimal("3")))

    assert profile.quantity_unit == "수량 3 · 단위 미확인"
    assert profile.quantity_unit != UNKNOWN
    assert "수량·단위" in profile.missing_labels
    # Only the collection/verification date is fully known in this fixture.
    assert profile.completeness_percent == 12


def test_explicit_phrase_is_detected_without_guessing() -> None:
    profile = build_price_condition_profile(
        _item(conditions="설치 포함, 기타 조건 별도 협의")
    )

    assert profile.installation == "설치 포함"
    assert profile.delivery == UNKNOWN

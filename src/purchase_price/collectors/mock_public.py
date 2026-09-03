from datetime import date
from decimal import Decimal

from purchase_price.domain import EvidenceType, MatchGrade, SourceType
from purchase_price.schemas import CollectedPrice, ProductQuery

from .base import PriceCollector


class MockPublicCollector(PriceCollector):
    """Development-only collector used to verify the end-to-end search flow."""

    name = "mock_public"

    def search(self, query: ProductQuery) -> list[CollectedPrice]:
        token = " ".join(
            [query.product_name, query.manufacturer, query.model_name, query.specification]
        ).lower()
        if not token.strip():
            return []

        # Deliberately deterministic sample evidence. Never present this as real market data.
        if "xyz" in token or "monitor" in token or "모니터" in token:
            return [
                CollectedPrice(
                    manufacturer=query.manufacturer or "ABC Medical",
                    product_name=query.product_name or "Patient Monitor",
                    model_name=query.model_name or "XYZ-100",
                    specification=query.specification or "standard",
                    price=Decimal("35800000"),
                    evidence_type=EvidenceType.CONTRACT_UNIT_PRICE,
                    source_type=SourceType.PUBLIC_CONTRACT,
                    source_name="개발용 샘플 공공계약 A",
                    source_url=None,
                    collected_at=date.today(),
                    vat_status="미확인",
                    conditions="설치비 포함 여부 미확인",
                    match_grade=MatchGrade.A,
                    match_note="개발용 동일모델 샘플",
                ),
                CollectedPrice(
                    manufacturer=query.manufacturer or "ABC Medical",
                    product_name=query.product_name or "Patient Monitor",
                    model_name=query.model_name or "XYZ-100",
                    specification=query.specification or "standard",
                    price=Decimal("37500000"),
                    evidence_type=EvidenceType.PUBLIC_SALE_PRICE,
                    source_type=SourceType.B2B,
                    source_name="개발용 샘플 공개판매가 B",
                    source_url=None,
                    collected_at=date.today(),
                    vat_status="VAT 포함",
                    conditions="배송 조건 미확인",
                    match_grade=MatchGrade.B,
                    match_note="동일모델, 계약조건 차이 샘플",
                ),
            ]
        return []

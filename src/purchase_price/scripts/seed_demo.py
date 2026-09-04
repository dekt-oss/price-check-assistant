from datetime import date
from decimal import Decimal

from sqlalchemy import select

from purchase_price.db import SessionLocal
from purchase_price.domain import EvidenceType, MatchGrade, SourceType
from purchase_price.models import Product
from purchase_price.repositories.evidence import get_or_create_raw_evidence
from purchase_price.repositories.observations import get_or_create_price_observation
from purchase_price.schemas import CollectedPrice

DEMO_SOURCE_NAME = "개발용 샘플 공공기관 계약"


def main() -> None:
    with SessionLocal() as session:
        existing = session.scalar(select(Product).where(Product.model_name == "XYZ-100"))
        if existing:
            print("Demo data already exists.")
            return

        product = Product(
            manufacturer="ABC Medical",
            product_name="Patient Monitor",
            model_name="XYZ-100",
            specification="standard",
            category="의료장비",
            aliases="환자감시장치,patient monitor",
        )
        session.add(product)
        session.flush()

        evidence, _ = get_or_create_raw_evidence(
            session,
            run=None,
            source_name=DEMO_SOURCE_NAME,
            source_record_id="demo:xyz-100:v1",
            original_title="Patient Monitor, ABC Medical, XYZ-100, standard",
            payload={
                "kind": "development_demo_only",
                "manufacturer": "ABC Medical",
                "model": "XYZ-100",
                "price": "35800000",
                "currency": "KRW",
            },
            parser_version="demo-evidence-v1",
        )
        collected = CollectedPrice(
            manufacturer="ABC Medical",
            product_name="Patient Monitor",
            model_name="XYZ-100",
            specification="standard",
            price=Decimal("35800000"),
            evidence_type=EvidenceType.CONTRACT_UNIT_PRICE,
            source_type=SourceType.PUBLIC_CONTRACT,
            source_name=DEMO_SOURCE_NAME,
            source_url=None,
            source_record_id="demo:xyz-100:v1",
            original_title="Patient Monitor, ABC Medical, XYZ-100, standard",
            collected_at=date.today(),
            match_grade=MatchGrade.A,
            vat_status="미확인",
            conditions="개발 검증용 샘플 데이터",
            comparison_note="개발용 synthetic evidence; 사용자 가격판정용 아님",
        )
        get_or_create_price_observation(
            session,
            product=product,
            evidence=evidence,
            collected=collected,
            derivation_version="demo-normalization-v1",
        )
        session.commit()
        print("Demo data inserted with raw evidence provenance.")


if __name__ == "__main__":
    main()

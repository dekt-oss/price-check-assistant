from datetime import date
from decimal import Decimal

from sqlalchemy import select

from purchase_price.db import SessionLocal
from purchase_price.domain import EvidenceType, MatchGrade, SourceType
from purchase_price.models import PriceObservation, Product


def main() -> None:
    with SessionLocal() as session:
        existing = session.scalar(select(Product).where(Product.model_name == "XYZ-100"))
        if existing:
            print("Demo data already exists.")
            return
        p = Product(
            manufacturer="ABC Medical",
            product_name="Patient Monitor",
            model_name="XYZ-100",
            specification="standard",
            category="의료장비",
            aliases="환자감시장치,patient monitor",
        )
        p.observations = [
            PriceObservation(
                price=Decimal("35800000"),
                evidence_type=EvidenceType.CONTRACT_UNIT_PRICE,
                source_type=SourceType.PUBLIC_CONTRACT,
                source_name="샘플 공공기관 계약",
                collected_at=date.today(),
                match_grade=MatchGrade.A,
                vat_status="미확인",
                conditions="개발 검증용 샘플 데이터",
            )
        ]
        session.add(p)
        session.commit()
        print("Demo data inserted.")


if __name__ == "__main__":
    main()

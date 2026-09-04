from datetime import date
from decimal import Decimal

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from purchase_price.db import Base
from purchase_price.domain import (
    ComparisonScope,
    EvidenceType,
    MatchGrade,
    SourceType,
)
from purchase_price.models import PriceObservation, Product
from purchase_price.repositories.evidence import get_or_create_raw_evidence
from purchase_price.repositories.observations import get_or_create_price_observation
from purchase_price.schemas import CollectedPrice


def _collected() -> CollectedPrice:
    return CollectedPrice(
        manufacturer="ABC",
        product_name="Monitor",
        model_name="XYZ-100",
        specification="std",
        price=Decimal("1000000"),
        evidence_type=EvidenceType.CONTRACT_UNIT_PRICE,
        source_type=SourceType.PUBLIC_CONTRACT,
        source_name="source-a",
        source_url="https://example.com/evidence",
        source_record_id="record-1",
        original_title="Monitor, ABC, XYZ-100",
        collected_at=date(2026, 9, 4),
        match_grade=MatchGrade.A,
        comparison_scope=ComparisonScope.OBSERVED_ONLY,
        comparison_note="terms not normalized",
    )


def test_price_observation_is_idempotent_per_derivation_version() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        product = Product(product_name="Monitor", manufacturer="ABC", model_name="XYZ-100")
        session.add(product)
        evidence, _ = get_or_create_raw_evidence(
            session,
            run=None,
            source_name="source-a",
            source_record_id="record-1",
            payload={"price": 1000000, "model": "XYZ-100"},
        )

        first, first_created = get_or_create_price_observation(
            session,
            product=product,
            evidence=evidence,
            collected=_collected(),
            derivation_version="normalizer-v1",
        )
        second, second_created = get_or_create_price_observation(
            session,
            product=product,
            evidence=evidence,
            collected=_collected(),
            derivation_version="normalizer-v1",
        )

        assert first_created is True
        assert second_created is False
        assert first.id == second.id
        rows = session.scalars(select(PriceObservation)).all()
        assert len(rows) == 1
        assert rows[0].evidence_id == evidence.id
        assert rows[0].derivation_version == "normalizer-v1"
        assert rows[0].comparison_scope == ComparisonScope.OBSERVED_ONLY
        assert rows[0].comparison_note == "terms not normalized"


def test_new_derivation_version_preserves_reprocessing_history() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        product = Product(product_name="Monitor", manufacturer="ABC", model_name="XYZ-100")
        session.add(product)
        evidence, _ = get_or_create_raw_evidence(
            session,
            run=None,
            source_name="source-a",
            payload={"price": 1000000, "model": "XYZ-100"},
        )

        first, _ = get_or_create_price_observation(
            session,
            product=product,
            evidence=evidence,
            collected=_collected(),
            derivation_version="normalizer-v1",
        )
        second, second_created = get_or_create_price_observation(
            session,
            product=product,
            evidence=evidence,
            collected=_collected(),
            derivation_version="normalizer-v2",
        )

        assert second_created is True
        assert first.id != second.id
        assert len(session.scalars(select(PriceObservation)).all()) == 2


def test_observation_repository_rejects_cross_source_provenance() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        product = Product(product_name="Monitor")
        session.add(product)
        evidence, _ = get_or_create_raw_evidence(
            session,
            run=None,
            source_name="other-source",
            payload={"price": 1000000},
        )

        try:
            get_or_create_price_observation(
                session,
                product=product,
                evidence=evidence,
                collected=_collected(),
                derivation_version="normalizer-v1",
            )
        except ValueError as exc:
            assert "source_name" in str(exc)
        else:
            raise AssertionError("cross-source provenance must be rejected")


def test_price_observation_schema_requires_raw_evidence() -> None:
    assert PriceObservation.__table__.c.evidence_id.nullable is False

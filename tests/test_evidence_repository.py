from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from purchase_price.db import Base
from purchase_price.models import RawEvidence
from purchase_price.repositories.evidence import get_or_create_raw_evidence, start_collection_run


def test_raw_evidence_is_idempotent_by_source_and_payload_hash():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        run = start_collection_run(session, source_name="test-source", query_text="TN500")
        first, first_created = get_or_create_raw_evidence(
            session,
            run=run,
            source_name="test-source",
            payload={"model": "TN500", "price": 100},
        )
        second, second_created = get_or_create_raw_evidence(
            session,
            run=run,
            source_name="test-source",
            payload={"price": 100, "model": "TN500"},
        )

        assert first_created is True
        assert second_created is False
        assert first.id == second.id
        assert len(session.scalars(select(RawEvidence)).all()) == 1

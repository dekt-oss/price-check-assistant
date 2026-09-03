import json
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from purchase_price.collectors.g2b_shopping import G2BShoppingOperation, SOURCE_NAME
from purchase_price.db import Base
from purchase_price.models import RawEvidence
from purchase_price.repositories.evidence import start_collection_run
from purchase_price.services.g2b_shopping_ingest import persist_g2b_shopping_payload

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "g2b_shopping"


def _fixture(name: str) -> dict:
    return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))


def test_g2b_raw_page_ingest_is_idempotent() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    payload = _fixture("delivery_official_labels.json")

    with Session(engine) as session:
        first_run = start_collection_run(session, source_name=SOURCE_NAME, query_text="fixture-1")
        first = persist_g2b_shopping_payload(
            session,
            run=first_run,
            payload=payload,
            operation=G2BShoppingOperation.DELIVERY_REQUEST_DETAILS,
        )
        second_run = start_collection_run(session, source_name=SOURCE_NAME, query_text="fixture-2")
        second = persist_g2b_shopping_payload(
            session,
            run=second_run,
            payload=payload,
            operation=G2BShoppingOperation.DELIVERY_REQUEST_DETAILS,
        )

        evidence = session.scalars(select(RawEvidence)).all()

        assert first.record_count == 1
        assert first.created_count == 1
        assert first.duplicate_count == 0
        assert second.record_count == 1
        assert second.created_count == 0
        assert second.duplicate_count == 1
        assert len(evidence) == 1
        assert evidence[0].source_record_id == "DLVR-001"
        assert evidence[0].original_title == "테스트 의료비품"

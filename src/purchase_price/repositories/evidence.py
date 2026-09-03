from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from purchase_price.evidence import canonical_payload_text, payload_sha256
from purchase_price.models import CollectionRun, RawEvidence


def start_collection_run(session: Session, *, source_name: str, query_text: str) -> CollectionRun:
    run = CollectionRun(source_name=source_name, query_text=query_text, status="running")
    session.add(run)
    session.flush()
    return run


def finish_collection_run(
    run: CollectionRun,
    *,
    status: str,
    result_count: int,
    error_message: str | None = None,
) -> None:
    run.status = status
    run.result_count = result_count
    run.error_message = error_message
    run.finished_at = datetime.now(UTC)


def get_or_create_raw_evidence(
    session: Session,
    *,
    run: CollectionRun | None,
    source_name: str,
    payload: Mapping[str, Any] | list[Any],
    source_record_id: str | None = None,
    source_url: str | None = None,
    original_title: str | None = None,
    parser_version: str = "v1",
) -> tuple[RawEvidence, bool]:
    payload_hash = payload_sha256(payload)
    existing = session.scalar(
        select(RawEvidence).where(
            RawEvidence.source_name == source_name,
            RawEvidence.payload_hash == payload_hash,
        )
    )
    if existing is not None:
        return existing, False

    evidence = RawEvidence(
        run=run,
        source_name=source_name,
        source_record_id=source_record_id,
        source_url=source_url,
        original_title=original_title,
        payload_text=canonical_payload_text(payload),
        payload_hash=payload_hash,
        parser_version=parser_version,
    )
    session.add(evidence)
    session.flush()
    return evidence, True

"""Read immutable Track B R2 pages into the local PostgreSQL serving index."""

from __future__ import annotations

import argparse
import json
from collections.abc import Callable, Mapping
from typing import Any

from sqlalchemy.orm import Session

from purchase_price.config import Settings
from purchase_price.db import SessionLocal
from purchase_price.services.g2b_track_b_normalization import TrackBRawPage
from purchase_price.services.track_b_db_quote_comparison import ingest_track_b_page
from purchase_price.storage.r2_reader import R2RawEvidenceReader

TRACK_B_PAGE_OPERATION = "getSpcifyPrdlstPrcureInfoList-page"


class TrackBImportFailure(RuntimeError):
    def __init__(self, object_key: str, resume_cursor: str | None, cause: Exception) -> None:
        super().__init__(f"failed to import {object_key}: {cause}")
        self.object_key = object_key
        self.resume_cursor = resume_cursor


def run(
    *,
    reader: R2RawEvidenceReader,
    session_factory: Callable[[], Session],
    limit: int,
    cursor: str | None = None,
) -> dict[str, Any]:
    if limit < 1:
        raise ValueError("limit must be positive")
    completed_cursor = cursor
    scanned = inserted = replayed = invalid_rows = 0
    has_more = False
    while scanned < limit:
        try:
            page = reader.list_public_json_page(
                source_operation=TRACK_B_PAGE_OPERATION,
                limit=min(1000, limit - scanned),
                after_key=completed_cursor,
            )
        except Exception as exc:
            raise TrackBImportFailure("<listing>", completed_cursor, exc) from exc
        has_more = page.has_more
        for obj in page.objects:
            try:
                payload = reader.get_public_json(obj)
                if not isinstance(payload, Mapping):
                    raise ValueError("Track B R2 page must be a JSON object")
                with session_factory() as session, session.begin():
                    result = ingest_track_b_page(
                        session,
                        TrackBRawPage(
                            payload=payload,
                            raw_object_key=obj.key,
                            raw_payload_sha256=obj.payload_hash,
                        ),
                    )
            except Exception as exc:
                raise TrackBImportFailure(obj.key, completed_cursor, exc) from exc
            inserted += result.inserted
            replayed += result.replayed
            invalid_rows += result.invalid_rows
            scanned += 1
            completed_cursor = obj.key
        if not has_more:
            break
        if page.next_cursor is None or (
            not page.objects and page.next_cursor <= (completed_cursor or "")
        ):
            raise TrackBImportFailure(
                "<listing>", completed_cursor, ValueError("cursor did not advance")
            )
        completed_cursor = page.next_cursor
    return {
        "status": "PARTIAL" if invalid_rows else "SUCCESS",
        "objects_scanned": scanned,
        "inserted": inserted,
        "replayed": replayed,
        "invalid_rows": invalid_rows,
        "resume_cursor": completed_cursor,
        "has_more": has_more,
        "public_api_requests": 0,
        "r2_writes": 0,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--cursor", help="Last completed R2 object key")
    args = parser.parse_args()
    try:
        report = run(
            reader=R2RawEvidenceReader.from_settings(Settings()),
            session_factory=SessionLocal,
            limit=args.limit,
            cursor=args.cursor,
        )
    except TrackBImportFailure as exc:
        print(
            json.dumps(
                {
                    "status": "FAILED",
                    "object_key": exc.object_key,
                    "resume_cursor": exc.resume_cursor,
                    "error": str(exc),
                },
                ensure_ascii=False,
            )
        )
        return 1
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

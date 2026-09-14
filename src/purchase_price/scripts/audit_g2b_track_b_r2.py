from __future__ import annotations

import argparse
import json
from collections.abc import Mapping

from botocore.exceptions import BotoCoreError, ClientError

from purchase_price.config import Settings
from purchase_price.services.g2b_track_b_audit import TrackBAuditAccumulator
from purchase_price.services.g2b_track_b_normalization import (
    TrackBIdentityConflictError,
    TrackBNormalizationError,
    TrackBRawPage,
)
from purchase_price.storage.r2 import R2IntegrityError
from purchase_price.storage.r2_reader import R2RawEvidenceReader

TRACK_B_PAGE_OPERATION = "getSpcifyPrdlstPrcureInfoList-page"


class TrackBAuditReadFailure(RuntimeError):
    def __init__(self, *, object_key: str, resume_cursor: str | None, cause: Exception) -> None:
        super().__init__(f"failed to audit {object_key}: {cause}")
        self.object_key = object_key
        self.resume_cursor = resume_cursor


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Read Track B raw pages from R2, normalize them, and print an audit summary. "
            "This command performs no data.go.kr calls and writes no DB/R2 data."
        )
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=100,
        help="Maximum Track B raw objects in this run (default: 100)",
    )
    parser.add_argument(
        "--cursor", help="Last completed object key from an earlier batch report"
    )
    return parser


def run(*, limit: int, cursor: str | None = None) -> dict[str, object]:
    if limit < 1:
        raise ValueError("limit must be positive")
    reader = R2RawEvidenceReader.from_settings(Settings())
    audit = TrackBAuditAccumulator()
    completed_cursor = cursor
    objects_scanned = 0
    has_more = False
    while objects_scanned < limit:
        try:
            page = reader.list_public_json_page(
                source_operation=TRACK_B_PAGE_OPERATION,
                limit=min(1000, limit - objects_scanned),
                after_key=completed_cursor,
            )
        except (R2IntegrityError, BotoCoreError, ClientError, OSError) as exc:
            raise TrackBAuditReadFailure(
                object_key="<listing>", resume_cursor=completed_cursor, cause=exc
            ) from exc
        has_more = page.has_more
        for obj in page.objects:
            try:
                payload = reader.get_public_json(obj)
                if not isinstance(payload, Mapping):
                    audit.invalid_pages += 1
                else:
                    try:
                        audit.add_page(
                            TrackBRawPage(
                                payload=payload,
                                raw_object_key=obj.key,
                                raw_payload_sha256=obj.payload_hash,
                            )
                        )
                    except TrackBIdentityConflictError:
                        raise
                    except TrackBNormalizationError:
                        audit.invalid_pages += 1
            except (
                R2IntegrityError, TrackBIdentityConflictError, BotoCoreError,
                ClientError, OSError, KeyError, TypeError,
            ) as exc:
                raise TrackBAuditReadFailure(
                    object_key=obj.key, resume_cursor=completed_cursor, cause=exc
                ) from exc
            completed_cursor = obj.key
            objects_scanned += 1
        if page.next_cursor is not None:
            if completed_cursor is not None and page.next_cursor < completed_cursor:
                raise R2IntegrityError("R2 page cursor moved backwards")
            completed_cursor = page.next_cursor
        if not has_more:
            break
        if page.next_cursor is None:
            raise R2IntegrityError("R2 truncated listing has no resume cursor")
    summary = audit.summary()
    report = summary.as_dict()
    report.update(
        {
            "status": "SUCCESS",
            "mode": "READ_ONLY_DRY_RUN",
            "source_operation": TRACK_B_PAGE_OPERATION,
            "requested_limit": limit,
            "objects_scanned": objects_scanned,
            "objects_loaded": objects_scanned,
            "resume_cursor": completed_cursor,
            "has_more": has_more,
            "writes_performed": 0,
            "public_api_requests": 0,
        }
    )
    return report


def main() -> int:
    args = build_parser().parse_args()
    try:
        report = run(limit=args.limit, cursor=args.cursor)
    except TrackBAuditReadFailure as exc:
        print(json.dumps({
            "status": "FAILED",
            "object_key": exc.object_key,
            "resume_cursor": exc.resume_cursor,
            "error": str(exc),
        }, ensure_ascii=False, sort_keys=True))
        return 1
    except TrackBIdentityConflictError as exc:
        print(json.dumps({
            "status": "FAILED",
            "resume_cursor": args.cursor,
            "error": str(exc),
        }, ensure_ascii=False, sort_keys=True))
        return 1
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

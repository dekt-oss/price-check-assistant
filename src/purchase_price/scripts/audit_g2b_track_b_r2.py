from __future__ import annotations

import argparse
import json
from collections.abc import Mapping

from purchase_price.config import Settings
from purchase_price.services.g2b_track_b_audit import audit_track_b_raw_pages
from purchase_price.services.g2b_track_b_normalization import TrackBRawPage
from purchase_price.storage.r2 import R2IntegrityError
from purchase_price.storage.r2_reader import R2RawEvidenceReader

TRACK_B_PAGE_OPERATION = "getSpcifyPrdlstPrcureInfoList-page"


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
        help="Maximum R2 raw pages to audit (default: 100)",
    )
    return parser


def run(*, limit: int) -> dict[str, object]:
    if limit < 1:
        raise ValueError("limit must be positive")
    reader = R2RawEvidenceReader.from_settings(Settings())
    objects = reader.list_public_json(source_operation=TRACK_B_PAGE_OPERATION, limit=limit)
    pages: list[TrackBRawPage] = []
    for obj in objects:
        payload = reader.get_public_json(obj)
        if not isinstance(payload, Mapping):
            raise R2IntegrityError(f"Track B raw object must contain a JSON object: {obj.key}")
        pages.append(
            TrackBRawPage(
                payload=payload,
                raw_object_key=obj.key,
                raw_payload_sha256=obj.payload_hash,
            )
        )

    summary = audit_track_b_raw_pages(tuple(pages))
    report = summary.as_dict()
    report.update(
        {
            "status": "SUCCESS",
            "mode": "READ_ONLY_DRY_RUN",
            "source_operation": TRACK_B_PAGE_OPERATION,
            "requested_limit": limit,
            "objects_loaded": len(objects),
            "writes_performed": 0,
            "public_api_requests": 0,
        }
    )
    return report


def main() -> int:
    args = build_parser().parse_args()
    report = run(limit=args.limit)
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

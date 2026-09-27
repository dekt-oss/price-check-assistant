from __future__ import annotations

import argparse
import json
from pathlib import Path

from purchase_price.services.mfds_identity_status import (
    choose_mfds_collection_plan,
    get_mfds_identity_collection_status,
)


def build_plan(
    *,
    event_name: str,
    schedule: str | None,
    requested_chunks: int,
    requested_pages_per_chunk: int,
    requested_rows_per_page: int,
) -> dict[str, object]:
    status = get_mfds_identity_collection_status()
    plan = choose_mfds_collection_plan(
        complete_cycles=status.complete_cycles,
        event_name=event_name,
        schedule=schedule,
        requested_chunks=requested_chunks,
        requested_pages_per_chunk=requested_pages_per_chunk,
        requested_rows_per_page=requested_rows_per_page,
    )
    return {
        "status": status.status,
        "complete_cycles": status.complete_cycles,
        "row_count": status.row_count,
        "source_total_count": status.source_total_count,
        "next_page": status.next_page,
        "collection_mode": plan.mode,
        "chunks": plan.chunks,
        "pages_per_chunk": plan.pages_per_chunk,
        "rows_per_page": plan.rows_per_page,
        "reason": plan.reason,
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Plan MFDS backfill or rolling-refresh work.")
    parser.add_argument("--event-name", required=True)
    parser.add_argument("--schedule", default="")
    parser.add_argument("--requested-chunks", type=int, default=5)
    parser.add_argument("--requested-pages-per-chunk", type=int, default=200)
    parser.add_argument("--requested-rows-per-page", type=int, default=100)
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    payload = build_plan(
        event_name=args.event_name,
        schedule=args.schedule or None,
        requested_chunks=args.requested_chunks,
        requested_pages_per_chunk=args.requested_pages_per_chunk,
        requested_rows_per_page=args.requested_rows_per_page,
    )
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    print(text)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

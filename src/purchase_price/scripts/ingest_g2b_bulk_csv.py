from __future__ import annotations

import argparse
import json
from datetime import date, timedelta
from pathlib import Path

from purchase_price.config import get_settings
from purchase_price.services.g2b_bulk_csv import ingest_bulk_csv
from purchase_price.storage.r2 import R2RawEvidenceStore


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Ingest the official G2B shopping delivery-request bulk CSV into R2"
    )
    parser.add_argument("csv_path", type=Path)
    parser.add_argument("--retrieved-date", type=date.fromisoformat, default=date.today())
    parser.add_argument("--end-date", type=date.fromisoformat, default=date.today())
    parser.add_argument("--days", type=int, default=365)
    parser.add_argument("--chunk-size", type=int, default=1000)
    parser.add_argument("--output", type=Path, default=None)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    if args.days < 1:
        raise ValueError("days must be positive")

    settings = get_settings()
    if not settings.r2_configured:
        raise RuntimeError("R2 writer configuration is incomplete")

    begin = args.end_date - timedelta(days=args.days - 1)
    summary = ingest_bulk_csv(
        path=args.csv_path,
        store=R2RawEvidenceStore.from_settings(settings),
        begin=begin,
        end=args.end_date,
        retrieved_date=args.retrieved_date,
        chunk_size=args.chunk_size,
    )
    rendered = json.dumps(summary.to_dict(), ensure_ascii=False, indent=2)
    print(rendered)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

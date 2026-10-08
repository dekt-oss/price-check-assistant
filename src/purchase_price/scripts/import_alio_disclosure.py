"""Load ALIO (alio.go.kr) disclosure figures for 부산대학교병원 into ``data/alio_disclosure.csv``.

    # fetch the newest report of each item (public pages, no key, no login) and rebuild the CSV
    python -m purchase_price.scripts.import_alio_disclosure --fetch

    # rebuild the CSV from the raw files under data/alio_raw/ only (offline, idempotent)
    python -m purchase_price.scripts.import_alio_disclosure --from-raw
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from purchase_price.services import alio_disclosure as alio


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--fetch", action="store_true", help="download from alio.go.kr, then rebuild the CSV")
    mode.add_argument("--from-raw", action="store_true", help="rebuild the CSV from saved raw files only")
    parser.add_argument("--raw-dir", type=Path, default=alio.DEFAULT_RAW_DIR)
    parser.add_argument("--csv", type=Path, default=alio.DEFAULT_ALIO_CSV)
    parser.add_argument("--pause", type=float, default=1.0, help="seconds between requests")
    args = parser.parse_args(argv)

    if args.fetch:
        saved = alio.fetch_raw(args.raw_dir, pause=args.pause)
        print(f"raw files: {len(saved)}")
    rows = alio.rows_from_raw_dir(args.raw_dir)
    alio.write_alio_csv(rows, args.csv)
    years = sorted({row.fiscal_year for row in rows})
    print(f"rows: {len(rows)} years: {years[:1] + years[-1:]} -> {args.csv}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

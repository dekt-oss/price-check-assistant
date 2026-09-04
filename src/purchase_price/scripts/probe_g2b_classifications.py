"""Test candidate G2B detail-product classifications against live evidence, for human review.

Growing `data/g2b_product_mappings.csv` means answering one question per benchmark product:
which standard 세부품명 does this product actually belong to? The registry rule is that the
answer must come from observed public evidence, never from a guess, so this script gathers the
evidence rather than deciding.

For each candidate name it reports what the live specific-item procurement API returns: the
record count, the `dtilPrdctClsfcNo` values actually present, and the manufacturers and models
observed in that classification. A candidate is worth registering only when the observed
manufacturers/models are consistent with the product being mapped -- which a person judges from
this output.

Two traps this output is designed to expose:

- The service substring-matches `dtilPrdctClsfcNoNm`. Querying `냉장고` returns 김치냉장고,
  대형냉장고 and 시신보관냉장고 as well, so a candidate that looks like a hit may be several
  classifications at once. The per-code breakdown makes that visible.
- A classification can exist and still be the wrong one. `심장충격기` is real and busy, but its
  observed manufacturers are public-access AED makers, which is not evidence that a hospital
  defibrillator/monitor belongs there.

Requires DATA_GO_KR_SERVICE_KEY. Never runs in CI. The key is never printed.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import date, timedelta
from pathlib import Path

from purchase_price.clients.data_go_kr import PublicDataClientError
from purchase_price.collectors.g2b_shopping import G2BShoppingCollector
from purchase_price.config import get_settings


@dataclass
class CandidateProbe:
    candidate_name: str
    begin_date: str
    end_date: str
    total_count: int | None = None
    sampled_records: int = 0
    classifications: dict[str, int] = field(default_factory=dict)
    manufacturers: dict[str, int] = field(default_factory=dict)
    models: dict[str, int] = field(default_factory=dict)
    error: str | None = None

    @property
    def is_split_across_classifications(self) -> bool:
        return len(self.classifications) > 1


def _title_parts(record: dict) -> tuple[str | None, str | None]:
    """Pull manufacturer/model out of the `제품군, 제조사, 모델, 사양` title shape."""

    title = str(record.get("prdctIdntNoNm") or "")
    parts = [part.strip() for part in title.split(",")]
    if len(parts) < 3:
        return None, None
    return parts[1] or None, parts[2] or None


def probe_candidate(
    collector: G2BShoppingCollector,
    candidate_name: str,
    *,
    begin_date: date,
    end_date: date,
    max_pages: int,
    num_of_rows: int,
) -> CandidateProbe:
    probe = CandidateProbe(
        candidate_name=candidate_name,
        begin_date=begin_date.isoformat(),
        end_date=end_date.isoformat(),
    )
    classifications: Counter[str] = Counter()
    manufacturers: Counter[str] = Counter()
    models: Counter[str] = Counter()

    try:
        for page_no in range(1, max_pages + 1):
            page, _ = collector.fetch_specific_item_page(
                detail_product_name=candidate_name,
                begin_date=begin_date,
                end_date=end_date,
                num_of_rows=num_of_rows,
                page_no=page_no,
            )
            if probe.total_count is None:
                probe.total_count = page.total_count
            if not page.items:
                break
            probe.sampled_records += len(page.items)
            for record in page.items:
                name = str(record.get("dtilPrdctClsfcNoNm") or "?")
                code = str(record.get("dtilPrdctClsfcNo") or "?")
                classifications[f"{name} ({code})"] += 1
                manufacturer, model = _title_parts(record)
                if manufacturer:
                    manufacturers[manufacturer] += 1
                if model:
                    models[model] += 1
            if probe.total_count is not None and probe.sampled_records >= probe.total_count:
                break
    except PublicDataClientError as exc:
        probe.error = str(exc)

    probe.classifications = dict(classifications.most_common())
    probe.manufacturers = dict(manufacturers.most_common(12))
    probe.models = dict(models.most_common(12))
    return probe


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("candidates", nargs="+", help="Candidate 세부품명 names to test.")
    parser.add_argument("--lookback-days", type=int, default=90)
    parser.add_argument("--max-pages", type=int, default=3)
    parser.add_argument("--num-of-rows", type=int, default=100)
    parser.add_argument("--output", type=Path, default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.lookback_days < 1 or args.max_pages < 1 or args.num_of_rows < 1:
        print("probe_status=error reason=lookback-days, max-pages and num-of-rows must be positive")
        return 2

    settings = get_settings()
    service_key = (settings.data_go_kr_service_key or "").strip()
    if not service_key:
        print("probe_status=skipped reason=DATA_GO_KR_SERVICE_KEY not configured")
        return 2

    collector = G2BShoppingCollector(service_key)
    end_date = date.today()
    begin_date = end_date - timedelta(days=args.lookback_days - 1)

    probes = [
        probe_candidate(
            collector,
            candidate,
            begin_date=begin_date,
            end_date=end_date,
            max_pages=args.max_pages,
            num_of_rows=args.num_of_rows,
        )
        for candidate in args.candidates
    ]

    for probe in probes:
        if probe.error:
            print(f"candidate={probe.candidate_name} ERROR {probe.error}")
            continue
        print(
            f"candidate={probe.candidate_name} total={probe.total_count} "
            f"sampled={probe.sampled_records} "
            f"classifications={len(probe.classifications)}"
        )
        for label, count in probe.classifications.items():
            print(f"    {count:5d}  {label}")
        if probe.manufacturers:
            print("    manufacturers: " + ", ".join(f"{k}×{v}" for k, v in probe.manufacturers.items()))
        if probe.models:
            print("    models: " + ", ".join(f"{k}×{v}" for k, v in probe.models.items()))
        if probe.is_split_across_classifications:
            print(
                "    NOTE: this candidate name matched several classifications; it is a "
                "substring, not one classification."
            )

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps([asdict(probe) for probe in probes], ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"probe_output={args.output}")

    print("probe_status=ok")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

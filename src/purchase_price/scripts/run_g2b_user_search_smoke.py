"""Exercise the live G2B user-search path end to end, through the same entry points as the UI.

CI covers this pipeline with fixtures only. That verifies the wiring but not the contract with
the live data.go.kr service: parameter names, response envelopes, pagination totals and the
verified detail-product mappings can all drift without a single test failing. This script closes
that gap by calling `build_collectors()` -> `search_all()` -> `assess_prices()`, which is exactly
what `pages/1_통합검색.py` calls, so a pass here means the user surface itself works.

It never runs in CI and requires `DATA_GO_KR_SERVICE_KEY`. The key is never printed.

An empty result is a legitimate outcome: a verified model simply may have had no public
procurement in the window. The run therefore fails only on a broken pipeline -- a collector
error, a missing G2B collector despite a configured key, or an incomplete window collection --
and reports zero-candidate models as observations.
"""

from __future__ import annotations

import argparse
import csv
import json
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from purchase_price.collectors.registry import build_collectors
from purchase_price.config import get_settings
from purchase_price.schemas import ProductQuery
from purchase_price.services.g2b_product_mapping import load_g2b_product_mappings
from purchase_price.services.pricing import assess_prices
from purchase_price.services.search import search_all

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_PRODUCTS_PATH = PROJECT_ROOT / "data" / "phase0_products.csv"
G2B_SOURCE_NAME = "조달청_나라장터쇼핑몰 품목정보 서비스"


@dataclass
class ModelSmokeResult:
    model_name: str
    product_name: str
    manufacturer: str
    detail_product_name: str
    lookback_days: int
    begin_date: str
    end_date: str
    collector_names: list[str] = field(default_factory=list)
    collector_errors: list[str] = field(default_factory=list)
    total_rows: int = 0
    g2b_rows: int = 0
    other_source_rows: int = 0
    grades: list[str] = field(default_factory=list)
    comparison_scopes: list[str] = field(default_factory=list)
    observed_count: int = 0
    observed_low: str | None = None
    observed_high: str | None = None
    source_count: int = 0
    confidence: str = ""
    quote_position: str | None = None
    assessment_message: str = ""
    status: str = "ok"


def _load_benchmark_products(path: Path) -> dict[str, dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return {
            (row.get("model_name") or "").strip(): row
            for row in csv.DictReader(handle)
            if (row.get("model_name") or "").strip()
        }


def _verified_targets(products: dict[str, dict[str, str]]) -> list[tuple[str, str]]:
    """Return (model_name, detail_product_name) for every verified G2B mapping."""

    targets = []
    for mapping in load_g2b_product_mappings():
        if not mapping.verified or not mapping.detail_product_name:
            continue
        if mapping.model_name in products:
            targets.append((mapping.model_name, mapping.detail_product_name))
    return sorted(targets)


def _run_one(
    model_name: str,
    detail_product_name: str,
    row: dict[str, str],
    *,
    lookback_days: int,
    quote: Decimal | None,
) -> ModelSmokeResult:
    end_date = date.today()
    begin_date = end_date - timedelta(days=lookback_days - 1)
    query = ProductQuery(
        product_name=(row.get("product_name") or "").strip(),
        manufacturer=(row.get("manufacturer") or "").strip(),
        model_name=model_name,
        specification=(row.get("specification") or "").strip(),
    )

    result = ModelSmokeResult(
        model_name=model_name,
        product_name=query.product_name,
        manufacturer=query.manufacturer,
        detail_product_name=detail_product_name,
        lookback_days=lookback_days,
        begin_date=begin_date.isoformat(),
        end_date=end_date.isoformat(),
    )

    collectors = build_collectors(g2b_lookback_days=lookback_days)
    result.collector_names = [collector.name for collector in collectors]
    if G2B_SOURCE_NAME not in result.collector_names:
        result.status = "g2b_collector_missing"
        return result

    run = search_all(query, collectors)
    result.collector_errors = list(run.errors)
    result.total_rows = len(run.results)
    result.g2b_rows = sum(1 for x in run.results if x.source_name == G2B_SOURCE_NAME)
    result.other_source_rows = result.total_rows - result.g2b_rows
    result.grades = sorted({x.match_grade.value for x in run.results})
    result.comparison_scopes = sorted({x.comparison_scope.value for x in run.results})

    assessment = assess_prices(run.results, quote)
    result.observed_count = assessment.observed_count
    result.observed_low = str(assessment.low) if assessment.low is not None else None
    result.observed_high = str(assessment.high) if assessment.high is not None else None
    result.source_count = assessment.source_count
    result.confidence = assessment.confidence
    result.quote_position = assessment.quote_position
    result.assessment_message = assessment.message

    if run.errors:
        result.status = "collector_error"
    elif result.g2b_rows == 0:
        result.status = "no_g2b_candidate"
    return result


def _write_outputs(results: list[ModelSmokeResult], output_dir: Path) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    summary_path = output_dir / "g2b-live-smoke-summary.json"
    rows_path = output_dir / "g2b-live-smoke-models.csv"

    payload: dict[str, Any] = {
        "generated_at": datetime.now().astimezone().isoformat(),
        "model_count": len(results),
        "models": [asdict(item) for item in results],
    }
    summary_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    with rows_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(asdict(results[0]).keys()))
        writer.writeheader()
        for item in results:
            record = asdict(item)
            for key, value in record.items():
                if isinstance(value, list):
                    record[key] = "|".join(str(part) for part in value)
            writer.writerow(record)
    return summary_path, rows_path


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--model",
        action="append",
        default=[],
        help="Restrict the run to these exact model names. Repeat as needed.",
    )
    parser.add_argument("--lookback-days", type=int, default=90)
    parser.add_argument(
        "--quote",
        default=None,
        help="Optional quote unit price, to exercise the quote-comparison gate.",
    )
    parser.add_argument("--products", type=Path, default=DEFAULT_PRODUCTS_PATH)
    parser.add_argument("--output-dir", type=Path, default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.lookback_days < 1:
        print("smoke_status=error reason=lookback_days must be positive")
        return 2

    settings = get_settings()
    if not (settings.data_go_kr_service_key or "").strip():
        print(
            "smoke_status=skipped reason=DATA_GO_KR_SERVICE_KEY not configured "
            "(set it in .env; this script never runs in CI)"
        )
        return 2

    products = _load_benchmark_products(args.products)
    targets = _verified_targets(products)
    if args.model:
        wanted = {name.strip() for name in args.model}
        targets = [pair for pair in targets if pair[0] in wanted]
        missing = wanted - {pair[0] for pair in targets}
        if missing:
            print(f"smoke_status=error reason=no verified mapping for {sorted(missing)}")
            return 2
    if not targets:
        print("smoke_status=error reason=no verified G2B mapping to exercise")
        return 2

    quote = Decimal(args.quote) if args.quote else None

    results: list[ModelSmokeResult] = []
    for model_name, detail_product_name in targets:
        result = _run_one(
            model_name,
            detail_product_name,
            products[model_name],
            lookback_days=args.lookback_days,
            quote=quote,
        )
        results.append(result)
        print(
            f"model={result.model_name} class={result.detail_product_name} "
            f"window={result.begin_date}~{result.end_date} status={result.status} "
            f"rows={result.total_rows} g2b_rows={result.g2b_rows} "
            f"grades={','.join(result.grades) or '-'} "
            f"observed={result.observed_count} "
            f"range={result.observed_low or '-'}~{result.observed_high or '-'} "
            f"sources={result.source_count} quote_position={result.quote_position or '-'}"
        )
        for message in result.collector_errors:
            print(f"  collector_error: {message}")

    if args.output_dir:
        summary_path, rows_path = _write_outputs(results, args.output_dir)
        print(f"summary_output={summary_path}")
        print(f"models_output={rows_path}")

    broken = [item for item in results if item.status in {"collector_error", "g2b_collector_missing"}]
    empty = [item for item in results if item.status == "no_g2b_candidate"]
    print(
        f"models={len(results)} broken={len(broken)} no_g2b_candidate={len(empty)} "
        f"with_g2b_rows={len(results) - len(broken) - len(empty)}"
    )
    if broken:
        print("smoke_status=failed reason=pipeline error on " + ",".join(x.model_name for x in broken))
        return 1
    print("smoke_status=ok")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

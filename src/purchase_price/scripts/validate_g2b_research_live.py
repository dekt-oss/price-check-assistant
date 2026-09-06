from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from pathlib import Path

from purchase_price.config import get_settings
from purchase_price.schemas import ProductQuery
from purchase_price.services.g2b_unmapped_discovery import discover_unmapped_g2b_candidates

DEFAULT_CASES = Path(__file__).resolve().parents[3] / "data" / "g2b_research_validation_cases.csv"


@dataclass(frozen=True)
class LiveResearchCase:
    model_name: str
    product_name: str
    manufacturer: str


@dataclass(frozen=True)
class LiveResearchCaseResult:
    model_name: str
    product_name: str
    status: str
    request_count: int
    records_seen: int
    candidate_count: int
    model_candidates: int
    manufacturer_candidates: int
    category_candidates: int
    failed_query_count: int
    truncated_query_count: int
    error: str = ""


def load_cases(path: Path) -> tuple[LiveResearchCase, ...]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        required = {"model_name", "product_name", "manufacturer"}
        if reader.fieldnames is None or not required.issubset(reader.fieldnames):
            raise ValueError("research validation cases are missing required columns")
        return tuple(
            LiveResearchCase(
                model_name=(row.get("model_name") or "").strip(),
                product_name=(row.get("product_name") or "").strip(),
                manufacturer=(row.get("manufacturer") or "").strip(),
            )
            for row in reader
            if (row.get("model_name") or "").strip() and (row.get("product_name") or "").strip()
        )


def summarize_case(case: LiveResearchCase, discovery) -> LiveResearchCaseResult:
    relevance = Counter(candidate.relevance for candidate in discovery.candidates)
    return LiveResearchCaseResult(
        model_name=case.model_name,
        product_name=case.product_name,
        status=discovery.status,
        request_count=discovery.request_count,
        records_seen=discovery.records_seen,
        candidate_count=len(discovery.candidates),
        model_candidates=relevance["모델 표기 후보"],
        manufacturer_candidates=relevance["제조사 표기 후보"],
        category_candidates=relevance["분류 후보"],
        failed_query_count=discovery.failed_query_count,
        truncated_query_count=discovery.truncated_query_count,
    )


def failed_case(case: LiveResearchCase, exc: Exception) -> LiveResearchCaseResult:
    return LiveResearchCaseResult(
        model_name=case.model_name,
        product_name=case.product_name,
        status="failure",
        request_count=0,
        records_seen=0,
        candidate_count=0,
        model_candidates=0,
        manufacturer_candidates=0,
        category_candidates=0,
        failed_query_count=1,
        truncated_query_count=0,
        error=f"{type(exc).__name__}: {exc}",
    )


def build_report(results: tuple[LiveResearchCaseResult, ...]) -> dict[str, object]:
    total = len(results)
    hit = sum(result.candidate_count > 0 for result in results)
    model_hit = sum(result.model_candidates > 0 for result in results)
    complete = sum(result.status in {"success", "success_0"} for result in results)
    partial = sum(result.status == "partial" for result in results)
    failure = sum(result.status == "failure" for result in results)
    return {
        "total_cases": total,
        "research_hit_cases": hit,
        "research_hit_rate": round(hit / total, 4) if total else None,
        "model_candidate_hit_cases": model_hit,
        "model_candidate_hit_rate": round(model_hit / total, 4) if total else None,
        "complete_cases": complete,
        "partial_cases": partial,
        "failure_cases": failure,
        "total_requests": sum(result.request_count for result in results),
        "total_records_seen": sum(result.records_seen for result in results),
        "cases": [asdict(result) for result in results],
        "safety_note": (
            "Research candidates are discovery-only and are not CollectedPrice, MatchGrade, "
            "QUOTE_COMPARABLE, or price-verdict evidence."
        ),
    }


def run_case(
    case: LiveResearchCase,
    *,
    service_key: str,
    lookback_days: int,
    pages_per_term_window: int,
    request_budget_per_case: int,
    timeout_seconds: float,
    max_retries: int,
) -> LiveResearchCaseResult:
    discovery = discover_unmapped_g2b_candidates(
        ProductQuery(
            product_name=case.product_name,
            manufacturer=case.manufacturer,
            model_name=case.model_name,
        ),
        service_key=service_key,
        lookback_days=lookback_days,
        pages_per_term_window=pages_per_term_window,
        request_budget=request_budget_per_case,
        timeout_seconds=timeout_seconds,
        max_retries=max_retries,
    )
    return summarize_case(case, discovery)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run bounded live G2B Research Layer coverage checks")
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--lookback-days", type=int, default=365)
    parser.add_argument("--pages-per-term-window", type=int, default=1)
    parser.add_argument("--request-budget-per-case", type=int, default=8)
    parser.add_argument("--timeout-seconds", type=float, default=6.0)
    parser.add_argument("--max-retries", type=int, default=1)
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--output", type=Path, default=Path("artifacts/g2b-research-live/report.json"))
    args = parser.parse_args()

    settings = get_settings()
    service_key = (settings.resolved_g2b_service_key or "").strip()
    if not service_key:
        raise SystemExit(
            "G2B_SERVICE_KEY, DATA_GO_KR_MARKET_SERVICE_KEY, or DATA_GO_KR_SERVICE_KEY is required"
        )

    cases = load_cases(args.cases)
    if not cases:
        raise SystemExit("no G2B live research validation cases configured")

    ordered_results: list[LiveResearchCaseResult | None] = [None] * len(cases)
    workers = max(1, min(args.workers, len(cases)))
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="g2b-live") as executor:
        future_to_index = {
            executor.submit(
                run_case,
                case,
                service_key=service_key,
                lookback_days=args.lookback_days,
                pages_per_term_window=args.pages_per_term_window,
                request_budget_per_case=args.request_budget_per_case,
                timeout_seconds=args.timeout_seconds,
                max_retries=args.max_retries,
            ): index
            for index, case in enumerate(cases)
        }
        for future in as_completed(future_to_index):
            index = future_to_index[future]
            case = cases[index]
            try:
                result = future.result()
            except Exception as exc:  # live validator must preserve all other case results
                result = failed_case(case, exc)
            ordered_results[index] = result
            print(
                f"case={case.model_name} status={result.status} candidates={result.candidate_count} "
                f"model_candidates={result.model_candidates} requests={result.request_count} "
                f"records_seen={result.records_seen} error={result.error or '-'}",
                flush=True,
            )

    results = tuple(result for result in ordered_results if result is not None)
    report = build_report(results)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"research_hit_rate={report['research_hit_rate']}", flush=True)
    print(f"model_candidate_hit_rate={report['model_candidate_hit_rate']}", flush=True)
    print(f"failure_cases={report['failure_cases']}", flush=True)
    print(f"report={args.output}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

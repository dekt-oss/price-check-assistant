from __future__ import annotations

import argparse
import json
from collections import Counter
from collections.abc import Callable
from decimal import Decimal
from pathlib import Path
from typing import Any

from purchase_price.domain import MatchGrade
from purchase_price.schemas import ProductQuery
from purchase_price.services.matching import normalize_text
from purchase_price.services.product_matching import grade_product_identity, parse_g2b_identity
from purchase_price.services.track_b_r2_quote_index import lookup_track_b_quote_from_r2

MANIFEST_SCHEMA = "r2-search-recall-uat-v1"
TIERS = ("DIRECT_AB", "CLASS_C", "BROAD_REFERENCE", "ZERO")
INDEX_ERROR_STATUSES = {"unavailable", "not_ingested"}


def _load_manifest(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("schema") != MANIFEST_SCHEMA:
        raise ValueError("R2 search recall manifest schema mismatch")
    cases = payload.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError("R2 search recall manifest must contain at least one case")

    normalized: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for raw in cases:
        if not isinstance(raw, dict):
            raise ValueError("R2 search recall case must be an object")
        case_id = str(raw.get("case_id") or "").strip()
        if not case_id or case_id in seen_ids:
            raise ValueError("R2 search recall case_id must be unique and non-empty")
        query = {
            "case_id": case_id,
            "product_name": str(raw.get("product_name") or "").strip(),
            "manufacturer": str(raw.get("manufacturer") or "").strip(),
            "model_name": str(raw.get("model_name") or "").strip(),
            "specification": str(raw.get("specification") or "").strip(),
            "expected_negative": bool(raw.get("expected_negative", False)),
        }
        if not query["product_name"] and not query["model_name"]:
            raise ValueError(f"case {case_id} needs product_name or model_name")
        normalized.append(query)
        seen_ids.add(case_id)
    return normalized


def _tier_for_result(result: Any) -> str:
    if str(result.status) in INDEX_ERROR_STATUSES:
        return "INDEX_ERROR"
    grades = {candidate.match_grade for candidate in result.candidates}
    if grades & {MatchGrade.A, MatchGrade.B}:
        return "DIRECT_AB"
    if MatchGrade.C in grades:
        return "CLASS_C"
    if result.reference_candidates:
        return "BROAD_REFERENCE"
    return "ZERO"


def _price_text(value: Decimal | None) -> str | None:
    return str(value) if value is not None else None


def _reference_diagnostic(query: ProductQuery, candidate: Any) -> dict[str, Any]:
    identity = parse_g2b_identity(candidate.product_title)
    decision = grade_product_identity(query, identity)
    query_model = normalize_text(query.model_name)
    candidate_model = normalize_text(identity.model_name)
    model_variant = bool(
        query_model
        and candidate_model
        and query_model != candidate_model
        and (query_model in candidate_model or candidate_model in query_model)
    )

    if decision.grade in {MatchGrade.A, MatchGrade.B}:
        blocker = "STRICT_LOOKUP_GAP"
    elif (
        decision.model_state
        in {"exact_with_unverified_qualifier", "verified_alias_with_unverified_qualifier"}
        and decision.manufacturer_state == "exact_or_alias"
    ):
        blocker = "UNVERIFIED_MODEL_QUALIFIER"
    elif (
        decision.model_state == "conflict"
        and model_variant
        and decision.manufacturer_state == "exact_or_alias"
    ):
        blocker = "MODEL_VARIANT_CANDIDATE"
    elif decision.specification_state == "explicit_conflict":
        blocker = "SPEC_CONFLICT"
    elif (
        decision.model_state
        in {"exact", "exact_with_verified_origin", "verified_alias", "verified_alias_with_verified_origin"}
        and decision.manufacturer_state == "conflict"
    ):
        blocker = "MANUFACTURER_CONFLICT"
    elif decision.model_state == "missing":
        blocker = "MODEL_NOT_OBSERVED"
    else:
        blocker = "REFERENCE_ONLY"

    promotion_candidate = blocker in {
        "STRICT_LOOKUP_GAP",
        "UNVERIFIED_MODEL_QUALIFIER",
        "MODEL_VARIANT_CANDIDATE",
    }
    return {
        "source_record_id": candidate.source_record_id,
        "product_title": candidate.product_title,
        "price": _price_text(candidate.price),
        "parsed_manufacturer": identity.manufacturer,
        "parsed_model_name": identity.model_name,
        "model_qualifier": identity.model_qualifier,
        "blocker": blocker,
        "promotion_candidate": promotion_candidate,
        "match_note": decision.note,
    }


def _candidate_row(candidate: Any, *, reference: bool) -> dict[str, Any]:
    row = {
        "source_record_id": candidate.source_record_id,
        "product_title": candidate.product_title,
        "price": _price_text(candidate.price),
        "transaction_date": candidate.transaction_date,
        "supplier": candidate.supplier,
        "demand_institution": candidate.demand_institution,
        "quantity": _price_text(candidate.quantity),
        "unit": candidate.unit,
        "transaction_type": candidate.transaction_type,
    }
    if reference:
        row["reason"] = candidate.reference_reason
        row["model_name"] = candidate.model_name
    else:
        row["match_grade"] = candidate.match_grade.value
        row["match_note"] = candidate.match_note
    return row


def _evaluate_case(
    case: dict[str, Any],
    *,
    lookup: Callable[..., Any] = lookup_track_b_quote_from_r2,
) -> dict[str, Any]:
    query = ProductQuery(
        product_name=case["product_name"],
        manufacturer=case["manufacturer"],
        model_name=case["model_name"],
        specification=case["specification"],
    )
    result = lookup(query, quote_unit_price=None)
    tier = _tier_for_result(result)

    candidate_rows = list(result.candidates)
    reference_rows = list(result.reference_candidates)
    if tier == "DIRECT_AB":
        observations = [
            candidate
            for candidate in candidate_rows
            if candidate.match_grade in {MatchGrade.A, MatchGrade.B}
        ]
    elif tier == "CLASS_C":
        observations = [
            candidate for candidate in candidate_rows if candidate.match_grade == MatchGrade.C
        ]
    elif tier == "BROAD_REFERENCE":
        observations = reference_rows
    else:
        observations = []

    prices = [row.price for row in observations if row.price is not None]
    supplier_present = sum(bool(row.supplier) for row in observations)
    demand_present = sum(bool(row.demand_institution) for row in observations)
    observation_count = len(observations)
    reference_diagnostics = (
        [_reference_diagnostic(query, row) for row in reference_rows]
        if tier == "BROAD_REFERENCE"
        else []
    )
    promotion_candidates = [
        row for row in reference_diagnostics if row["promotion_candidate"]
    ]
    promotion_blockers = Counter(str(row["blocker"]) for row in promotion_candidates)

    return {
        "case_id": case["case_id"],
        "query": {
            "product_name": query.product_name,
            "manufacturer": query.manufacturer,
            "model_name": query.model_name,
            "specification": query.specification,
        },
        "lookup_status": result.status,
        "tier": tier,
        "candidate_count": len(candidate_rows),
        "reference_count": len(reference_rows),
        "examined": result.examined,
        "observation_count": observation_count,
        "price_min": _price_text(min(prices) if prices else None),
        "price_max": _price_text(max(prices) if prices else None),
        "supplier_present_count": supplier_present,
        "demand_institution_present_count": demand_present,
        "supplier_presence_rate": (
            round(supplier_present / observation_count, 4) if observation_count else None
        ),
        "demand_institution_presence_rate": (
            round(demand_present / observation_count, 4) if observation_count else None
        ),
        "external_research_rescue": "NOT_RUN",
        "expected_negative": bool(case.get("expected_negative", False)),
        "promotion_candidate_count": len(promotion_candidates),
        "promotion_blocker_counts": dict(sorted(promotion_blockers.items())),
        "promotion_candidates": promotion_candidates[:5],
        "sample_rows": [
            _candidate_row(row, reference=tier == "BROAD_REFERENCE")
            for row in observations[:5]
        ],
    }


def build_report(
    cases: list[dict[str, str]],
    *,
    lookup: Callable[..., Any] = lookup_track_b_quote_from_r2,
) -> dict[str, Any]:
    results = [_evaluate_case(case, lookup=lookup) for case in cases]
    counts = Counter(str(row["tier"]) for row in results)
    total = len(results)
    usable = total - counts["INDEX_ERROR"]
    summary: dict[str, Any] = {
        "total_queries": total,
        "usable_queries": usable,
        "index_error_count": counts["INDEX_ERROR"],
    }
    for tier in TIERS:
        count = counts[tier]
        summary[f"{tier.lower()}_count"] = count
        summary[f"{tier.lower()}_rate"] = round(count / usable, 4) if usable else None

    expected_negative_zeros = [
        row for row in results if row["tier"] == "ZERO" and row.get("expected_negative")
    ]
    unexpected_zeros = [
        row for row in results if row["tier"] == "ZERO" and not row.get("expected_negative")
    ]
    positive_queries = [row for row in results if not row.get("expected_negative")]
    summary["expected_negative_zero_count"] = len(expected_negative_zeros)
    summary["unexpected_zero_count"] = len(unexpected_zeros)
    summary["unexpected_zero_rate"] = (
        round(len(unexpected_zeros) / len(positive_queries), 4)
        if positive_queries
        else None
    )

    promotion_cases = [row for row in results if row["promotion_candidate_count"]]
    promotion_blockers = Counter(
        blocker
        for row in promotion_cases
        for blocker, count in row["promotion_blocker_counts"].items()
        for _ in range(int(count))
    )
    summary["promotion_candidate_case_count"] = len(promotion_cases)
    summary["promotion_candidate_count"] = sum(
        int(row["promotion_candidate_count"]) for row in promotion_cases
    )
    summary["promotion_blocker_counts"] = dict(sorted(promotion_blockers.items()))

    observations = [row for row in results if row["observation_count"]]
    total_observations = sum(int(row["observation_count"]) for row in observations)
    total_supplier = sum(int(row["supplier_present_count"]) for row in observations)
    total_demand = sum(int(row["demand_institution_present_count"]) for row in observations)
    summary["supplier_presence_rate"] = (
        round(total_supplier / total_observations, 4) if total_observations else None
    )
    summary["demand_institution_presence_rate"] = (
        round(total_demand / total_observations, 4) if total_observations else None
    )

    return {
        "schema": "r2-search-recall-report-v1",
        "status": "ERROR" if counts["INDEX_ERROR"] else "SUCCESS",
        "summary": summary,
        "cases": results,
    }


def _md_text(value: object) -> str:
    return str(value or "-").replace("|", "/").replace("\n", " ")


def _write_markdown(report: dict[str, Any], path: Path) -> None:
    summary = report["summary"]
    lines = [
        "# R2 Search Recall UAT",
        "",
        f"- status: `{report['status']}`",
        f"- total queries: **{summary['total_queries']}**",
        f"- usable queries: **{summary['usable_queries']}**",
        f"- index errors: **{summary['index_error_count']}**",
        f"- expected negative ZERO: **{summary['expected_negative_zero_count']}**",
        f"- unexpected ZERO: **{summary['unexpected_zero_count']}**",
        f"- unexpected ZERO rate (positive cases): **{summary['unexpected_zero_rate']}**",
        f"- promotion-candidate cases: **{summary['promotion_candidate_case_count']}**",
        f"- promotion-candidate rows: **{summary['promotion_candidate_count']}**",
        "",
        "| Query | Tier | Status | Candidates | References | Price range |",
        "|---|---|---|---:|---:|---:|",
    ]
    for row in report["cases"]:
        price_range = "-"
        if row["price_min"] is not None:
            price_range = f"{row['price_min']} ~ {row['price_max']}"
        lines.append(
            "| {case_id} | {tier} | {status} | {candidates} | {references} | {price_range} |".format(
                case_id=row["case_id"],
                tier=row["tier"],
                status=row["lookup_status"],
                candidates=row["candidate_count"],
                references=row["reference_count"],
                price_range=price_range,
            )
        )
    lines.extend(["", "## Sample evidence", ""])
    for row in report["cases"]:
        if not row["sample_rows"]:
            continue
        lines.extend(
            [
                f"### {row['case_id']}",
                "",
                "| Title | Price | Qty/Unit | Model | Reason |",
                "|---|---:|---|---|---|",
            ]
        )
        for sample in row["sample_rows"][:3]:
            qty_unit = f"{_md_text(sample.get('quantity'))} {_md_text(sample.get('unit'))}"
            reason = sample.get("reason") or sample.get("match_note") or "-"
            lines.append(
                "| {title} | {price} | {qty_unit} | {model} | {reason} |".format(
                    title=_md_text(sample.get("product_title")),
                    price=_md_text(sample.get("price")),
                    qty_unit=qty_unit,
                    model=_md_text(sample.get("model_name")),
                    reason=_md_text(reason),
                )
            )
        lines.append("")
    lines.extend(["", "## Promotion candidates", ""])
    promotion_rows = [
        (row["case_id"], candidate)
        for row in report["cases"]
        for candidate in row.get("promotion_candidates", [])
    ]
    if not promotion_rows:
        lines.append("- none")
    else:
        lines.extend(
            [
                "| Query | Blocker | Parsed model | Manufacturer | Price | Title |",
                "|---|---|---|---|---:|---|",
            ]
        )
        for case_id, candidate in promotion_rows:
            lines.append(
                "| {case_id} | {blocker} | {model} | {manufacturer} | {price} | {title} |".format(
                    case_id=case_id,
                    blocker=_md_text(candidate.get("blocker")),
                    model=_md_text(candidate.get("parsed_model_name")),
                    manufacturer=_md_text(candidate.get("parsed_manufacturer")),
                    price=_md_text(candidate.get("price")),
                    title=_md_text(candidate.get("product_title")),
                )
            )

    lines.extend(["", "## Tier summary", ""])
    for tier in TIERS:
        key = tier.lower()
        rate = summary[f"{key}_rate"]
        rendered_rate = "-" if rate is None else f"{rate * 100:.1f}%"
        lines.append(f"- {tier}: {summary[f'{key}_count']} ({rendered_rate})")
    lines.extend(
        [
            "",
            f"- supplier presence: {summary['supplier_presence_rate']}",
            f"- demand institution presence: {summary['demand_institution_presence_rate']}",
            "",
            "> BROAD_REFERENCE is observed transaction evidence only and is never promoted to A/B fair-price evidence.",
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Measure real R2 serving-index search recall")
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path("data/uat/r2-search-recall-cases.json"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("artifacts/r2-search-recall/report.json"),
    )
    parser.add_argument(
        "--summary",
        type=Path,
        default=Path("artifacts/r2-search-recall/summary.md"),
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    cases = _load_manifest(args.manifest)
    report = build_report(cases)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    _write_markdown(report, args.summary)
    print(json.dumps(report["summary"], ensure_ascii=False, sort_keys=True))
    return 0 if report["status"] == "SUCCESS" else 1


if __name__ == "__main__":
    raise SystemExit(main())

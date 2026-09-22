from __future__ import annotations

import argparse
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from purchase_price.config import Settings
from purchase_price.schemas import ProductQuery
from purchase_price.services.g2b_product_mapping import (
    G2BProductMapping,
    load_g2b_product_mappings,
)
from purchase_price.services.market_research import research_g2b_market
from purchase_price.services.matching import normalize_text

REPORT_SCHEMA = "r2-search-recall-report-v1"
OUTPUT_SCHEMA = "g2b-external-research-rescue-v1"


def _enum_text(value: Any) -> str:
    raw = getattr(value, "value", value)
    return str(raw or "")


def _mapping_for_model(
    model_name: str,
    mappings: tuple[G2BProductMapping, ...],
) -> G2BProductMapping | None:
    key = normalize_text(model_name)
    matches = [row for row in mappings if normalize_text(row.model_name) == key]
    return matches[0] if len(matches) == 1 else None


def _record_matches(
    record: Any,
    *,
    query: ProductQuery,
    mapping: G2BProductMapping | None,
) -> bool:
    detail_code = str(getattr(record, "detail_product_code", None) or "").strip()
    if (
        mapping is not None
        and mapping.detail_product_code
        and detail_code == mapping.detail_product_code
    ):
        return True

    searchable = " ".join(
        str(value)
        for value in (
            getattr(record, "title", None),
            getattr(record, "product_name", None),
            getattr(record, "model_name", None),
            getattr(record, "original_specification", None),
        )
        if value
    )
    searchable_key = normalize_text(searchable)
    if not searchable_key:
        return False

    model_key = normalize_text(query.model_name)
    product_key = normalize_text(query.product_name)
    return bool(
        (model_key and model_key in searchable_key)
        or (product_key and product_key in searchable_key)
    )


def build_report(
    recall_report: dict[str, Any],
    *,
    mappings: tuple[G2BProductMapping, ...],
    service_key: str | None,
    research: Callable[..., Any] = research_g2b_market,
    timeout_seconds: float = 15.0,
) -> dict[str, Any]:
    if recall_report.get("schema") != REPORT_SCHEMA:
        raise ValueError("R2 recall report schema mismatch")

    target_rows = [
        row
        for row in recall_report.get("cases", [])
        if row.get("expected_surface") == "external_research"
    ]
    cases: list[dict[str, Any]] = []

    for row in target_rows:
        query_payload = row.get("query") or {}
        query = ProductQuery(
            product_name=str(query_payload.get("product_name") or ""),
            manufacturer=str(query_payload.get("manufacturer") or ""),
            model_name=str(query_payload.get("model_name") or ""),
            specification=str(query_payload.get("specification") or ""),
        )
        mapping = _mapping_for_model(query.model_name, mappings)

        if row.get("tier") != "ZERO":
            cases.append(
                {
                    "case_id": row.get("case_id"),
                    "r2_tier": row.get("tier"),
                    "status": "DELIVERY_INDEX_RECOVERED",
                    "rescued": True,
                    "matching_record_count": 0,
                    "source_statuses": {},
                    "samples": [],
                }
            )
            continue

        bundle = research(
            query,
            service_key=service_key,
            lookback_days=365,
            timeout_seconds=timeout_seconds,
            max_retries=1,
            max_terms=4,
            max_pages_per_window=1,
        )
        matches = [
            record
            for record in bundle.records
            if _record_matches(record, query=query, mapping=mapping)
        ]
        source_statuses = {
            _enum_text(source.source): _enum_text(source.status)
            for source in bundle.sources
        }
        samples = [
            {
                "source_type": _enum_text(getattr(record, "source_type", "")),
                "source_record_id": getattr(record, "source_record_id", None),
                "title": getattr(record, "title", None),
                "product_name": getattr(record, "product_name", None),
                "detail_product_code": getattr(record, "detail_product_code", None),
                "published_date": (
                    getattr(record, "published_date", None).isoformat()
                    if getattr(record, "published_date", None) is not None
                    else None
                ),
                "amount": (
                    str(getattr(record, "amount", None))
                    if getattr(record, "amount", None) is not None
                    else None
                ),
                "source_url": getattr(record, "source_url", None),
            }
            for record in matches[:5]
        ]
        cases.append(
            {
                "case_id": row.get("case_id"),
                "r2_tier": row.get("tier"),
                "status": "RESEARCH_RESCUED" if matches else "RESEARCH_NOT_FOUND",
                "rescued": bool(matches),
                "matching_record_count": len(matches),
                "source_statuses": source_statuses,
                "mapping_detail_code": (
                    mapping.detail_product_code if mapping is not None else None
                ),
                "samples": samples,
            }
        )

    rescued_count = sum(bool(row["rescued"]) for row in cases)
    return {
        "schema": OUTPUT_SCHEMA,
        "status": "SUCCESS" if rescued_count == len(cases) else "ERROR",
        "expected_external_research_case_count": len(cases),
        "rescued_case_count": rescued_count,
        "cases": cases,
    }


def _write_summary(report: dict[str, Any], path: Path) -> None:
    lines = [
        "# G2B External Research Rescue UAT",
        "",
        f"- status: `{report['status']}`",
        (
            "- expected external-Research cases: "
            f"**{report['expected_external_research_case_count']}**"
        ),
        f"- rescued cases: **{report['rescued_case_count']}**",
        "",
        "| Case | R2 tier | Rescue | Matching records | Source statuses |",
        "|---|---|---|---:|---|",
    ]
    for row in report["cases"]:
        statuses = ", ".join(
            f"{name}={status}" for name, status in row["source_statuses"].items()
        ) or "-"
        lines.append(
            "| {case} | {tier} | {status} | {count} | {statuses} |".format(
                case=row["case_id"],
                tier=row["r2_tier"],
                status=row["status"],
                count=row["matching_record_count"],
                statuses=statuses.replace("|", "/"),
            )
        )
        for sample in row["samples"][:3]:
            lines.append(
                "  - {source}: {title} · {date} · {code}".format(
                    source=sample["source_type"] or "-",
                    title=(sample["title"] or sample["product_name"] or "-").replace("|", "/"),
                    date=sample["published_date"] or "-",
                    code=sample["detail_product_code"] or "-",
                )
            )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify G2B Research rescue for curated R2 delivery-index ZERO cases"
    )
    parser.add_argument(
        "--recall-report",
        type=Path,
        default=Path("artifacts/r2-search-recall/report.json"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("artifacts/r2-search-recall/external-research-rescue.json"),
    )
    parser.add_argument(
        "--summary",
        type=Path,
        default=Path("artifacts/r2-search-recall/external-research-rescue.md"),
    )
    args = parser.parse_args()

    payload = json.loads(args.recall_report.read_text(encoding="utf-8"))
    settings = Settings()
    report = build_report(
        payload,
        mappings=load_g2b_product_mappings(),
        service_key=settings.resolved_g2b_research_service_key,
        timeout_seconds=min(settings.g2b_request_timeout_seconds, 15.0),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    _write_summary(report, args.summary)
    print(
        json.dumps(
            {
                "status": report["status"],
                "expected_external_research_case_count": report[
                    "expected_external_research_case_count"
                ],
                "rescued_case_count": report["rescued_case_count"],
            },
            sort_keys=True,
        )
    )
    return 0 if report["status"] == "SUCCESS" else 1


if __name__ == "__main__":
    raise SystemExit(main())

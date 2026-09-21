from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, or_, select
from sqlalchemy.orm import Session, sessionmaker

from purchase_price.config import Settings
from purchase_price.domain import MatchGrade
from purchase_price.models import TrackBDeliveryLine
from purchase_price.schemas import ProductQuery
from purchase_price.services.matching import normalize_text
from purchase_price.services.track_b_db_quote_comparison import TrackBQuoteComparison
from purchase_price.services.track_b_r2_quote_index import (
    _local_index_path,
    lookup_track_b_quote_from_r2,
)

OUTPUT_SCHEMA = "r2-observed-model-recall-v1"
_GENERIC_MODELS = {
    "수요기관규격",
    "병원용",
    "기타",
    "기타물품포함",
    "해당없음",
    "없음",
    "none",
    "n/a",
}
_GENERIC_MANUFACTURERS = {"기타물품포함", "기타", "해당없음", "없음"}


@dataclass(frozen=True)
class ObservedCase:
    case_id: str
    source_record_id: str
    detail_code: str
    product_name: str
    manufacturer: str
    model_name: str
    transaction_date: str | None
    unit_price: str


def _source_record_id(row: TrackBDeliveryLine) -> str:
    return (
        f"delivery:{row.delivery_request_number}"
        f"|change:{row.change_order}|line:{row.product_sequence}"
    )


def _current_row_clause():
    from sqlalchemy.orm import aliased

    newer = aliased(TrackBDeliveryLine)
    return ~select(1).where(
        newer.delivery_request_number == TrackBDeliveryLine.delivery_request_number,
        newer.product_sequence == TrackBDeliveryLine.product_sequence,
        newer.change_order_number > TrackBDeliveryLine.change_order_number,
    ).exists()


def _eligible_identity(row: TrackBDeliveryLine) -> bool:
    model = (row.model_name or "").strip()
    manufacturer = (row.manufacturer or "").strip()
    product_name = (row.product_class or "").strip()
    if not model or not manufacturer or not product_name:
        return False
    if normalize_text(model) in {normalize_text(value) for value in _GENERIC_MODELS}:
        return False
    if normalize_text(manufacturer) in {
        normalize_text(value) for value in _GENERIC_MANUFACTURERS
    }:
        return False
    if row.model_qualifier and not row.model_qualifier_verified_as_origin:
        return False
    return True


def _load_excluded_models(path: Path | None) -> set[str]:
    if path is None:
        return set()
    payload = json.loads(path.read_text(encoding="utf-8"))
    cases = payload.get("cases") if isinstance(payload, dict) else None
    if not isinstance(cases, list):
        raise ValueError("exclude manifest cases are missing")
    return {
        normalize_text(str(case.get("model_name") or ""))
        for case in cases
        if isinstance(case, dict) and normalize_text(str(case.get("model_name") or ""))
    }


def select_observed_cases(
    session: Session,
    *,
    target_count: int,
    excluded_models: set[str] | None = None,
) -> list[ObservedCase]:
    if target_count < 1:
        raise ValueError("target_count must be positive")
    excluded = excluded_models or set()
    current = _current_row_clause()

    detail_codes = list(
        session.scalars(
            select(TrackBDeliveryLine.detail_code)
            .where(
                current,
                TrackBDeliveryLine.unit_price > 0,
                TrackBDeliveryLine.identity_conflict.is_(False),
                TrackBDeliveryLine.model_name.is_not(None),
                TrackBDeliveryLine.manufacturer.is_not(None),
                TrackBDeliveryLine.product_class.is_not(None),
                or_(
                    TrackBDeliveryLine.model_qualifier.is_(None),
                    TrackBDeliveryLine.model_qualifier_verified_as_origin.is_(True),
                ),
            )
            .distinct()
        ).all()
    )
    # Hash-order avoids lexical clustering while remaining deterministic across runs.
    detail_codes = sorted(
        {str(code) for code in detail_codes if code},
        key=lambda code: hashlib.sha256(code.encode("utf-8")).hexdigest(),
    )

    cases: list[ObservedCase] = []
    seen_models: set[str] = set(excluded)
    for detail_code in detail_codes:
        rows = session.scalars(
            select(TrackBDeliveryLine)
            .where(
                current,
                TrackBDeliveryLine.detail_code == detail_code,
                TrackBDeliveryLine.unit_price > 0,
                TrackBDeliveryLine.identity_conflict.is_(False),
                TrackBDeliveryLine.model_name.is_not(None),
                TrackBDeliveryLine.manufacturer.is_not(None),
                TrackBDeliveryLine.product_class.is_not(None),
                or_(
                    TrackBDeliveryLine.model_qualifier.is_(None),
                    TrackBDeliveryLine.model_qualifier_verified_as_origin.is_(True),
                ),
            )
            .order_by(
                TrackBDeliveryLine.transaction_date.desc(),
                TrackBDeliveryLine.id.desc(),
            )
            .limit(60)
        ).all()
        selected = None
        for row in rows:
            if not _eligible_identity(row):
                continue
            model_key = normalize_text(row.model_name)
            if not model_key or model_key in seen_models:
                continue
            selected = row
            seen_models.add(model_key)
            break
        if selected is None:
            continue
        cases.append(
            ObservedCase(
                case_id=f"observed_{len(cases) + 1:02d}",
                source_record_id=_source_record_id(selected),
                detail_code=selected.detail_code,
                product_name=str(selected.product_class),
                manufacturer=str(selected.manufacturer),
                model_name=str(selected.model_name),
                transaction_date=(
                    selected.transaction_date.isoformat()
                    if selected.transaction_date is not None
                    else None
                ),
                unit_price=str(selected.unit_price),
            )
        )
        if len(cases) >= target_count:
            break
    return cases


def evaluate_cases(
    cases: list[ObservedCase],
    *,
    lookup: Callable[..., TrackBQuoteComparison] = lookup_track_b_quote_from_r2,
) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    for case in cases:
        query = ProductQuery(
            product_name=case.product_name,
            manufacturer=case.manufacturer,
            model_name=case.model_name,
            specification="",
        )
        result = lookup(query, quote_unit_price=None)
        direct = [
            candidate
            for candidate in result.candidates
            if candidate.match_grade in {MatchGrade.A, MatchGrade.B}
        ]
        source_recovered = any(
            candidate.source_record_id == case.source_record_id for candidate in direct
        )
        results.append(
            {
                **asdict(case),
                "lookup_status": result.status,
                "direct_ab_count": len(direct),
                "source_record_recovered": source_recovered,
                "best_grade": (
                    direct[0].match_grade.value if direct else None
                ),
                "reference_count": len(result.reference_candidates),
            }
        )

    direct_count = sum(bool(row["direct_ab_count"]) for row in results)
    source_recovered_count = sum(bool(row["source_record_recovered"]) for row in results)
    return {
        "sample_count": len(results),
        "direct_ab_count": direct_count,
        "direct_ab_rate": round(direct_count / len(results), 4) if results else None,
        "source_recovered_count": source_recovered_count,
        "source_recovered_rate": (
            round(source_recovered_count / len(results), 4) if results else None
        ),
        "cases": results,
    }


def build_report(
    cases: list[ObservedCase],
    *,
    target_count: int,
    curated_case_count: int,
    lookup: Callable[..., TrackBQuoteComparison] = lookup_track_b_quote_from_r2,
) -> dict[str, Any]:
    measured = evaluate_cases(cases, lookup=lookup)
    complete_sample = measured["sample_count"] == target_count
    all_direct = measured["direct_ab_count"] == target_count
    all_sources_recovered = measured["source_recovered_count"] == target_count
    status = "SUCCESS" if complete_sample and all_direct and all_sources_recovered else "ERROR"
    return {
        "schema": OUTPUT_SCHEMA,
        "status": status,
        "target_sample_count": target_count,
        "curated_case_count": curated_case_count,
        "combined_case_count": curated_case_count + measured["sample_count"],
        **measured,
    }


def _write_summary(report: dict[str, Any], path: Path) -> None:
    lines = [
        "# Production R2 Observed-Model Recall Expansion",
        "",
        f"- status: `{report['status']}`",
        f"- curated cases: **{report['curated_case_count']}**",
        f"- observed-model cases: **{report['sample_count']}/{report['target_sample_count']}**",
        f"- combined UAT cases: **{report['combined_case_count']}**",
        f"- observed direct A/B: **{report['direct_ab_count']} ({report['direct_ab_rate']})**",
        f"- exact source row recovered: **{report['source_recovered_count']} ({report['source_recovered_rate']})**",
        "",
        "| Case | Detail code | Product | Manufacturer | Model | Direct A/B | Source recovered |",
        "|---|---|---|---|---|---:|---:|",
    ]
    for row in report["cases"]:
        lines.append(
            "| {case_id} | {code} | {product} | {manufacturer} | {model} | {direct} | {recovered} |".format(
                case_id=row["case_id"],
                code=row["detail_code"],
                product=str(row["product_name"]).replace("|", "/"),
                manufacturer=str(row["manufacturer"]).replace("|", "/"),
                model=str(row["model_name"]).replace("|", "/"),
                direct=row["direct_ab_count"],
                recovered="yes" if row["source_record_recovered"] else "no",
            )
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run deterministic observed-model recall UAT against Production R2"
    )
    parser.add_argument("--target-count", type=int, default=24)
    parser.add_argument(
        "--exclude-manifest",
        type=Path,
        default=Path("data/uat/r2-search-recall-cases.json"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("artifacts/r2-search-recall/observed-model-report.json"),
    )
    parser.add_argument(
        "--summary",
        type=Path,
        default=Path("artifacts/r2-search-recall/observed-model-summary.md"),
    )
    args = parser.parse_args()

    settings = Settings()
    if not settings.r2_configured:
        raise RuntimeError("R2 configuration is incomplete")
    index_path = _local_index_path(settings)
    if index_path is None:
        raise RuntimeError("Track B serving index is unavailable")

    excluded_models = _load_excluded_models(args.exclude_manifest)
    curated_payload = json.loads(args.exclude_manifest.read_text(encoding="utf-8"))
    curated_cases = curated_payload.get("cases") if isinstance(curated_payload, dict) else []
    curated_case_count = len(curated_cases) if isinstance(curated_cases, list) else 0

    engine = create_engine(
        f"sqlite+pysqlite:///{index_path}",
        connect_args={"check_same_thread": False},
    )
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    try:
        with factory() as session:
            cases = select_observed_cases(
                session,
                target_count=args.target_count,
                excluded_models=excluded_models,
            )
    finally:
        engine.dispose()

    report = build_report(
        cases,
        target_count=args.target_count,
        curated_case_count=curated_case_count,
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
                "combined_case_count": report["combined_case_count"],
                "sample_count": report["sample_count"],
                "direct_ab_count": report["direct_ab_count"],
                "source_recovered_count": report["source_recovered_count"],
            },
            sort_keys=True,
        )
    )
    return 0 if report["status"] == "SUCCESS" else 1


if __name__ == "__main__":
    raise SystemExit(main())

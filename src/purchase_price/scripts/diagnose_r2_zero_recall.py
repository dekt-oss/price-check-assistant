from __future__ import annotations

import argparse
import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, exists, func, select
from sqlalchemy.orm import Session, aliased, sessionmaker

from purchase_price.config import Settings
from purchase_price.models import TrackBDeliveryLine
from purchase_price.services.g2b_product_mapping import (
    G2BProductMapping,
    load_g2b_product_mappings,
)
from purchase_price.services.matching import normalize_text
from purchase_price.services.track_b_pipeline_state import SNAPSHOT_STATE_NAME, STATE_NAME
from purchase_price.services.track_b_r2_quote_index import _local_index_path
from purchase_price.storage.r2_state import R2OperationalStateStore


@dataclass(frozen=True)
class ZeroDiagnostic:
    case_id: str
    model_name: str
    cause: str
    mapping_status: str
    detail_product_code: str | None
    detail_product_name: str | None
    target_code_status: str
    current_detail_rows: int
    current_priced_detail_rows: int
    global_exact_model_rows: int
    global_title_literal_rows: int
    mapping_notes: str | None


def _mapping_for_model(
    model_name: str,
    mappings: tuple[G2BProductMapping, ...],
) -> G2BProductMapping | None:
    key = normalize_text(model_name)
    if not key:
        return None
    matches = [row for row in mappings if normalize_text(row.model_name) == key]
    return matches[0] if len(matches) == 1 else None


def classify_zero_cause(
    *,
    case_id: str,
    mapping: G2BProductMapping | None,
    target_code_status: str,
    current_detail_rows: int,
    global_exact_model_rows: int,
    global_title_literal_rows: int,
) -> str:
    if case_id.endswith("negative_control"):
        return "EXPECTED_NEGATIVE_CONTROL"
    if mapping is None:
        return "MAPPING_NOT_REGISTERED"
    if not mapping.verified or not mapping.detail_product_code:
        return "MAPPING_UNVERIFIED"
    if target_code_status == "not_in_snapshot":
        return "TARGET_CODE_COVERAGE_GAP"
    if target_code_status in {"pending", "partial"}:
        return "HISTORICAL_TARGET_NOT_COMPLETE"
    if current_detail_rows == 0:
        return "MAPPED_CLASS_NO_SERVING_ROWS"
    if global_exact_model_rows or global_title_literal_rows:
        return "MATCHER_OR_IDENTITY_RULE_GAP"
    return "MAPPED_CLASS_MODEL_NOT_OBSERVED"


def _target_code_status(
    detail_code: str | None,
    *,
    target_codes: tuple[str, ...],
    collection_cursor_index: int,
    backfill_complete: bool,
) -> str:
    if not detail_code:
        return "not_applicable"
    try:
        index = target_codes.index(detail_code)
    except ValueError:
        return "not_in_snapshot"
    if backfill_complete or index < collection_cursor_index:
        return "collected"
    if index == collection_cursor_index:
        return "partial"
    return "pending"


def _current_clause():
    newer = aliased(TrackBDeliveryLine)
    return ~exists(
        select(1).where(
            newer.delivery_request_number == TrackBDeliveryLine.delivery_request_number,
            newer.product_sequence == TrackBDeliveryLine.product_sequence,
            newer.change_order_number > TrackBDeliveryLine.change_order_number,
        )
    )


def _scalar_count(session: Session, *clauses) -> int:
    statement = select(func.count()).select_from(TrackBDeliveryLine)
    if clauses:
        statement = statement.where(*clauses)
    return int(session.scalar(statement) or 0)


def _load_recall_report(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema") != "r2-search-recall-report-v1":
        raise ValueError("R2 recall report schema mismatch")
    cases = payload.get("cases")
    if not isinstance(cases, list):
        raise ValueError("R2 recall report cases are missing")
    return payload


def build_zero_diagnostics(
    *,
    recall_report: dict[str, Any],
    mappings: tuple[G2BProductMapping, ...],
    target_codes: tuple[str, ...],
    collection_cursor_index: int,
    backfill_complete: bool,
    session: Session,
) -> dict[str, Any]:
    current = _current_clause()
    diagnostics: list[ZeroDiagnostic] = []

    for row in recall_report["cases"]:
        if row.get("tier") != "ZERO":
            continue
        query = row.get("query") or {}
        case_id = str(row.get("case_id") or "")
        model_name = str(query.get("model_name") or "").strip()
        mapping = _mapping_for_model(model_name, mappings)

        detail_code = mapping.detail_product_code if mapping is not None else None
        target_status = _target_code_status(
            detail_code,
            target_codes=target_codes,
            collection_cursor_index=collection_cursor_index,
            backfill_complete=backfill_complete,
        )
        detail_rows = (
            _scalar_count(
                session,
                current,
                TrackBDeliveryLine.detail_code == detail_code,
                TrackBDeliveryLine.identity_conflict.is_(False),
            )
            if detail_code
            else 0
        )
        priced_detail_rows = (
            _scalar_count(
                session,
                current,
                TrackBDeliveryLine.detail_code == detail_code,
                TrackBDeliveryLine.unit_price > 0,
                TrackBDeliveryLine.identity_conflict.is_(False),
            )
            if detail_code
            else 0
        )

        model_key = normalize_text(model_name)
        exact_rows = (
            _scalar_count(
                session,
                current,
                TrackBDeliveryLine.model_key == model_key,
                TrackBDeliveryLine.identity_conflict.is_(False),
            )
            if model_key
            else 0
        )
        title_rows = (
            _scalar_count(
                session,
                current,
                TrackBDeliveryLine.product_title.ilike(f"%{model_name}%"),
                TrackBDeliveryLine.identity_conflict.is_(False),
            )
            if model_name
            else 0
        )

        cause = classify_zero_cause(
            case_id=case_id,
            mapping=mapping,
            target_code_status=target_status,
            current_detail_rows=detail_rows,
            global_exact_model_rows=exact_rows,
            global_title_literal_rows=title_rows,
        )
        diagnostics.append(
            ZeroDiagnostic(
                case_id=case_id,
                model_name=model_name,
                cause=cause,
                mapping_status=(mapping.mapping_status if mapping is not None else "missing"),
                detail_product_code=detail_code,
                detail_product_name=(mapping.detail_product_name if mapping is not None else None),
                target_code_status=target_status,
                current_detail_rows=detail_rows,
                current_priced_detail_rows=priced_detail_rows,
                global_exact_model_rows=exact_rows,
                global_title_literal_rows=title_rows,
                mapping_notes=(mapping.notes if mapping is not None else None),
            )
        )

    counts = Counter(item.cause for item in diagnostics)
    return {
        "schema": "r2-zero-recall-diagnostic-v1",
        "status": "SUCCESS",
        "historical": {
            "collection_cursor_index": collection_cursor_index,
            "target_code_count": len(target_codes),
            "backfill_complete": backfill_complete,
        },
        "summary": {
            "zero_case_count": len(diagnostics),
            "cause_counts": dict(sorted(counts.items())),
        },
        "cases": [
            {
                "case_id": item.case_id,
                "model_name": item.model_name,
                "cause": item.cause,
                "mapping_status": item.mapping_status,
                "detail_product_code": item.detail_product_code,
                "detail_product_name": item.detail_product_name,
                "target_code_status": item.target_code_status,
                "current_detail_rows": item.current_detail_rows,
                "current_priced_detail_rows": item.current_priced_detail_rows,
                "global_exact_model_rows": item.global_exact_model_rows,
                "global_title_literal_rows": item.global_title_literal_rows,
                "mapping_notes": item.mapping_notes,
            }
            for item in diagnostics
        ],
    }


def _write_summary(report: dict[str, Any], path: Path) -> None:
    historical = report["historical"]
    lines = [
        "# R2 ZERO Recall Diagnostic",
        "",
        f"- ZERO cases: **{report['summary']['zero_case_count']}**",
        (
            "- historical cursor: "
            f"**{historical['collection_cursor_index']}/{historical['target_code_count']}**"
        ),
        f"- historical complete: **{historical['backfill_complete']}**",
        "",
        "| Case | Cause | Mapping | Detail code | Target | Detail rows | Exact model rows |",
        "|---|---|---|---|---|---:|---:|",
    ]
    for row in report["cases"]:
        lines.append(
            "| {case_id} | {cause} | {mapping_status} | {detail_code} | {target_status} | "
            "{detail_rows} | {model_rows} |".format(
                case_id=row["case_id"],
                cause=row["cause"],
                mapping_status=row["mapping_status"],
                detail_code=row["detail_product_code"] or "-",
                target_status=row["target_code_status"],
                detail_rows=row["current_detail_rows"],
                model_rows=row["global_exact_model_rows"],
            )
        )
    lines.extend(["", "## Cause counts", ""])
    for cause, count in report["summary"]["cause_counts"].items():
        lines.append(f"- {cause}: {count}")
    lines.extend(
        [
            "",
            "> ZERO diagnostics never promote price evidence. They only classify why strict "
            "R2 lookup returned no usable observation.",
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Diagnose ZERO cases in Production R2 recall")
    parser.add_argument(
        "--recall-report",
        type=Path,
        default=Path("artifacts/r2-search-recall/report.json"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("artifacts/r2-search-recall/zero-diagnostic.json"),
    )
    parser.add_argument(
        "--summary",
        type=Path,
        default=Path("artifacts/r2-search-recall/zero-diagnostic.md"),
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    settings = Settings()
    if not settings.r2_configured:
        raise RuntimeError("R2 configuration is incomplete")

    state_store = R2OperationalStateStore.from_settings(settings)
    snapshot = state_store.read_json(SNAPSHOT_STATE_NAME)
    pipeline = state_store.read_json(STATE_NAME)
    if snapshot is None or pipeline is None:
        raise RuntimeError("Track B target snapshot or pipeline state is missing")

    raw_codes = snapshot.get("codes")
    if not isinstance(raw_codes, list) or not all(isinstance(code, str) for code in raw_codes):
        raise RuntimeError("Track B target snapshot codes are invalid")
    target_codes = tuple(raw_codes)

    cursor = pipeline.get("collection_cursor")
    if not isinstance(cursor, dict):
        raise RuntimeError("Track B collection cursor is missing")
    collection_cursor_index = int(cursor.get("code_index", -1))
    if collection_cursor_index < 0:
        raise RuntimeError("Track B collection cursor is invalid")

    index_path = _local_index_path(settings)
    if index_path is None:
        raise RuntimeError("Track B serving index is not available")

    engine = create_engine(
        f"sqlite+pysqlite:///{index_path}",
        connect_args={"check_same_thread": False},
    )
    session_factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    try:
        with session_factory() as session:
            report = build_zero_diagnostics(
                recall_report=_load_recall_report(args.recall_report),
                mappings=load_g2b_product_mappings(),
                target_codes=target_codes,
                collection_cursor_index=collection_cursor_index,
                backfill_complete=bool(pipeline.get("backfill_complete")),
                session=session,
            )
    finally:
        engine.dispose()

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    _write_summary(report, args.summary)
    print(json.dumps(report["summary"], ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

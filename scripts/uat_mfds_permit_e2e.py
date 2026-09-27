from __future__ import annotations

import json
import sqlite3
from collections import defaultdict
from decimal import Decimal
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from purchase_price.config import Settings
from purchase_price.schemas import ProductQuery
from purchase_price.services.mfds_identity_index import lookup_identity
from purchase_price.services.mfds_identity_r2 import _local_index_path as mfds_local_index_path
from purchase_price.services.track_b_db_quote_comparison import compare_track_b_quote
from purchase_price.services.track_b_r2_quote_index import _local_index_path as track_b_local_index_path
from purchase_price.services.track_b_reference_quality import refine_track_b_reference_quality
from purchase_price.ui.track_b_transactions import strict_comparison_candidates

ARTIFACT_DIR = Path("artifacts/mfds-permit-uat")
REPORT_PATH = ARTIFACT_DIR / "backend-uat.json"
PERMIT_PATH = ARTIFACT_DIR / "production-permit.txt"


def _money(value: Decimal | None) -> str | None:
    return f"{value:,.0f}" if value is not None else None


def _candidate_permits(connection: sqlite3.Connection, limit: int = 80) -> list[str]:
    connection.row_factory = sqlite3.Row
    rows = connection.execute(
        """
        WITH grouped AS (
            SELECT
                permit_key,
                MIN(permit_number) AS permit_number,
                COUNT(DISTINCT CASE WHEN model_key <> '' THEN model_key END) AS model_count,
                COUNT(DISTINCT CASE WHEN company_key <> '' THEN company_key END) AS company_count
            FROM mfds_identity
            WHERE permit_key <> ''
              AND model_key <> ''
              AND product_key <> ''
              AND company_key <> ''
            GROUP BY permit_key
            HAVING model_count BETWEEN 1 AND 6
        )
        SELECT permit_number
        FROM grouped
        ORDER BY permit_key
        LIMIT ?
        """,
        (limit // 2,),
    ).fetchall()
    reverse = connection.execute(
        """
        WITH grouped AS (
            SELECT
                permit_key,
                MIN(permit_number) AS permit_number,
                COUNT(DISTINCT CASE WHEN model_key <> '' THEN model_key END) AS model_count,
                COUNT(DISTINCT CASE WHEN company_key <> '' THEN company_key END) AS company_count
            FROM mfds_identity
            WHERE permit_key <> ''
              AND model_key <> ''
              AND product_key <> ''
              AND company_key <> ''
            GROUP BY permit_key
            HAVING model_count BETWEEN 1 AND 6
        )
        SELECT permit_number
        FROM grouped
        ORDER BY permit_key DESC
        LIMIT ?
        """,
        (limit - len(rows),),
    ).fetchall()
    values: list[str] = []
    seen: set[str] = set()
    for row in [*rows, *reverse]:
        value = str(row["permit_number"] or "").strip()
        if value and value not in seen:
            seen.add(value)
            values.append(value)
    return values


def main() -> None:
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    settings = Settings()
    mfds_path = mfds_local_index_path(settings)
    track_b_path = track_b_local_index_path(settings)
    if mfds_path is None:
        raise RuntimeError("MFDS identity serving index is not available")
    if track_b_path is None:
        raise RuntimeError("Track B serving index is not available")

    mfds = sqlite3.connect(mfds_path)
    engine = create_engine(
        f"sqlite+pysqlite:///{track_b_path}",
        connect_args={"check_same_thread": False},
    )
    session_factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    report: dict[str, object] = {
        "status": "failure",
        "mfds_index": str(mfds_path),
        "track_b_index": str(track_b_path),
        "cases": [],
    }
    categories: defaultdict[str, int] = defaultdict(int)
    production_candidate: str | None = None
    exact_success = 0
    track_b_available_checks = 0
    multi_model_cases = 0

    try:
        permits = _candidate_permits(mfds, limit=80)
        with session_factory() as session:
            for permit in permits:
                identity = lookup_identity(mfds, permit)
                if identity.status != "success" or identity.match_type != "permit":
                    continue
                if not identity.records or not identity.model_names:
                    continue

                exact_success += 1
                if len(identity.model_names) > 1:
                    multi_model_cases += 1

                model_results: list[dict[str, object]] = []
                for model in identity.model_names[:6]:
                    record = next(
                        (
                            item
                            for item in identity.records
                            if (item.model_name or "").strip() == model
                        ),
                        identity.records[0],
                    )
                    query = ProductQuery(
                        product_name=record.product_name,
                        model_name=model,
                    )
                    result = compare_track_b_quote(
                        session,
                        query,
                        quote_unit_price=None,
                    )
                    result = refine_track_b_reference_quality(session, query, result)
                    if result.status in {"unavailable", "not_ingested"}:
                        model_results.append(
                            {
                                "model": model,
                                "track_b_status": result.status,
                                "direct_count": None,
                                "supplier_count": None,
                                "min_price": None,
                                "max_price": None,
                            }
                        )
                        continue

                    track_b_available_checks += 1
                    direct = strict_comparison_candidates(result)
                    prices = sorted(
                        Decimal(str(item.price))
                        for item in direct
                        if getattr(item, "price", None) is not None
                    )
                    suppliers = sorted(
                        {
                            str(getattr(item, "supplier", "") or "").strip()
                            for item in direct
                            if str(getattr(item, "supplier", "") or "").strip()
                        }
                    )
                    model_results.append(
                        {
                            "model": model,
                            "product_name": record.product_name,
                            "registered_company": record.registered_company,
                            "udi_di": record.udi_di,
                            "track_b_status": result.status,
                            "direct_count": len(direct),
                            "supplier_count": len(suppliers),
                            "suppliers": suppliers[:5],
                            "min_price": _money(prices[0]) if prices else None,
                            "max_price": _money(prices[-1]) if prices else None,
                        }
                    )

                any_direct = any(
                    isinstance(row.get("direct_count"), int) and int(row["direct_count"]) > 0
                    for row in model_results
                )
                category = "direct" if any_direct else "no_direct"
                if len(identity.model_names) > 1:
                    category = "multi_model_direct" if any_direct else "multi_model"

                if category.startswith("multi_model"):
                    if categories[category] >= 2:
                        continue
                elif category == "direct":
                    if categories[category] >= 5:
                        continue
                elif categories[category] >= 5:
                    continue

                categories[category] += 1
                case = {
                    "permit": permit,
                    "product_names": list(identity.product_names),
                    "models": list(identity.model_names),
                    "companies": list(identity.companies),
                    "record_count": len(identity.records),
                    "category": category,
                    "model_results": model_results,
                }
                report["cases"].append(case)

                if production_candidate is None and any_direct and len(identity.model_names) <= 3:
                    production_candidate = permit

                if (
                    len(report["cases"]) >= 10
                    and categories["direct"] + categories["multi_model_direct"] >= 2
                    and multi_model_cases >= 1
                ):
                    break
    finally:
        engine.dispose()
        mfds.close()

    cases = list(report["cases"])
    report["summary"] = {
        "cases": len(cases),
        "exact_permit_successes_scanned": exact_success,
        "track_b_available_checks": track_b_available_checks,
        "multi_model_cases_scanned": multi_model_cases,
        "selected_categories": dict(categories),
        "production_candidate": production_candidate,
    }

    if len(cases) < 8:
        raise RuntimeError(f"Too few real permit UAT cases selected: {len(cases)}")
    unavailable = [
        row
        for case in cases
        for row in case["model_results"]
        if row.get("track_b_status") in {"unavailable", "not_ingested"}
    ]
    if unavailable:
        raise RuntimeError(
            f"Track B serving index unavailable for {len(unavailable)} model checks"
        )
    if production_candidate is None:
        raise RuntimeError("No permit with direct G2B evidence found for Production UAT")

    report["status"] = "pass"
    REPORT_PATH.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    PERMIT_PATH.write_text(production_candidate + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

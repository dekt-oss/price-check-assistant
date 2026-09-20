from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from purchase_price.config import Settings
from purchase_price.services.g2b_catalog import G2BCatalogClient

INSPECTION_SCHEMA = "r2-promotion-source-inspection-v1"
OUTPUT_SCHEMA = "g2b-promotion-catalog-probe-v1"


def _load_inspection(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("schema") != INSPECTION_SCHEMA:
        raise ValueError("promotion source inspection schema mismatch")
    sources = payload.get("sources")
    if not isinstance(sources, list):
        raise ValueError("promotion source inspection sources are missing")
    return payload


def _product_ids(source: dict[str, Any]) -> tuple[str, ...]:
    values: list[str] = []
    records = source.get("records") or []
    if not isinstance(records, list):
        return ()
    for record in records:
        if not isinstance(record, dict):
            continue
        value = str(record.get("prdctIdntNo") or "").strip()
        if value and value not in values:
            values.append(value)
    return tuple(values)


def build_probe(
    inspection: dict[str, Any],
    *,
    client: G2BCatalogClient,
) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    seen: set[str] = set()

    for source in inspection["sources"]:
        if not isinstance(source, dict):
            continue
        case_id = str(source.get("case_id") or "")
        for product_id in _product_ids(source):
            if product_id in seen:
                continue
            seen.add(product_id)
            result = client.fetch_attributes(product_id=product_id)
            results.append(
                {
                    "case_id": case_id,
                    "product_id": product_id,
                    "detail_product_codes": list(result.detail_product_codes),
                    "product_names": list(
                        dict.fromkeys(
                            row.product_name for row in result.attributes if row.product_name
                        )
                    ),
                    "attributes": [
                        {
                            "name": row.attribute_name,
                            "value": row.attribute_value,
                            "unit": row.attribute_unit,
                            "detail_product_code": row.detail_product_code,
                        }
                        for row in result.attributes
                    ],
                }
            )

    return {
        "schema": OUTPUT_SCHEMA,
        "status": "SUCCESS",
        "product_count": len(results),
        "products": results,
    }


def _write_summary(report: dict[str, Any], path: Path) -> None:
    lines = [
        "# G2B Promotion Catalog Probe",
        "",
        f"- exact product IDs checked: **{report['product_count']}**",
        "",
    ]
    for product in report["products"]:
        lines.extend(
            [
                f"## {product['case_id']} / {product['product_id']}",
                "",
                f"- detail codes: `{', '.join(product['detail_product_codes']) or '-'}`",
                f"- product names: `{' / '.join(product['product_names']) or '-'}`",
                "",
            ]
        )
        if product["attributes"]:
            lines.extend(
                [
                    "| Attribute | Value | Unit | Detail code |",
                    "|---|---|---|---|",
                ]
            )
            for row in product["attributes"]:
                lines.append(
                    "| {name} | {value} | {unit} | {code} |".format(
                        name=str(row["name"]).replace("|", "/"),
                        value=str(row["value"]).replace("|", "/"),
                        unit=str(row["unit"]).replace("|", "/"),
                        code=str(row["detail_product_code"]).replace("|", "/"),
                    )
                )
        else:
            lines.append("- exact-ID catalog attributes: 0 rows")
        lines.append("")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Probe official G2B catalog attributes for promotion-candidate product IDs"
    )
    parser.add_argument(
        "--inspection",
        type=Path,
        default=Path("artifacts/r2-search-recall/promotion-source-inspection.json"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("artifacts/r2-search-recall/promotion-catalog-probe.json"),
    )
    parser.add_argument(
        "--summary",
        type=Path,
        default=Path("artifacts/r2-search-recall/promotion-catalog-probe.md"),
    )
    args = parser.parse_args()

    settings = Settings()
    service_key = (settings.resolved_g2b_catalog_service_key or "").strip()
    if not service_key:
        raise RuntimeError("G2B catalog service key is not configured")

    client = G2BCatalogClient(
        service_key,
        base_url=settings.g2b_catalog_base_url,
        timeout_seconds=settings.g2b_request_timeout_seconds,
        max_retries=settings.g2b_max_retries,
    )
    report = build_probe(_load_inspection(args.inspection), client=client)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    _write_summary(report, args.summary)
    print(json.dumps({"product_count": report["product_count"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

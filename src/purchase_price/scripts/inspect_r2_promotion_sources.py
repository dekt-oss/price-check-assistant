from __future__ import annotations

import argparse
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from purchase_price.config import Settings
from purchase_price.services.matching import normalize_text
from purchase_price.storage.r2_reader import R2RawEvidenceReader, R2RawObject

REPORT_SCHEMA = "r2-search-recall-report-v1"
OUTPUT_SCHEMA = "r2-promotion-source-inspection-v1"
_RELEVANT_FIELD_TOKENS = (
    "prdct",
    "idnt",
    "dtil",
    "origin",
    "orgpl",
    "nation",
    "country",
    "model",
    "mnfct",
    "manufacturer",
    "goods",
)


def _payload_hash_from_key(key: str) -> str:
    filename = key.rsplit("/", 1)[-1]
    suffix = ".json.gz"
    if not filename.endswith(suffix):
        raise ValueError(f"raw object key has unexpected suffix: {key}")
    digest = filename[: -len(suffix)]
    if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
        raise ValueError(f"raw object key lacks a SHA-256 digest: {key}")
    return digest


def _iter_dicts(value: object):
    if isinstance(value, Mapping):
        yield value
        for child in value.values():
            yield from _iter_dicts(child)
    elif isinstance(value, list):
        for child in value:
            yield from _iter_dicts(child)


def _primitive(value: object) -> bool:
    return value is None or isinstance(value, (str, int, float, bool))


def _record_matches(record: Mapping[str, Any], *, model_name: str, product_title: str) -> bool:
    model_key = normalize_text(model_name)
    title_key = normalize_text(product_title)
    for value in record.values():
        if not isinstance(value, str):
            continue
        value_key = normalize_text(value)
        if not value_key:
            continue
        if model_key and model_key in value_key:
            return True
        if title_key and title_key == value_key:
            return True
    return False


def _extract_relevant_fields(record: Mapping[str, Any]) -> dict[str, Any]:
    selected: dict[str, Any] = {}
    for key, value in record.items():
        if not _primitive(value):
            continue
        key_folded = str(key).casefold()
        if any(token in key_folded for token in _RELEVANT_FIELD_TOKENS):
            selected[str(key)] = value
    return selected


def inspect_payload(
    payload: object,
    *,
    model_name: str,
    product_title: str,
    limit: int = 10,
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    for record in _iter_dicts(payload):
        if not _record_matches(record, model_name=model_name, product_title=product_title):
            continue
        fields = _extract_relevant_fields(record)
        if not fields:
            continue
        fingerprint = json.dumps(fields, ensure_ascii=False, sort_keys=True, default=str)
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        records.append(fields)
        if len(records) >= limit:
            break
    return records


def _load_recall_report(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("schema") != REPORT_SCHEMA:
        raise ValueError("R2 recall report schema mismatch")
    cases = payload.get("cases")
    if not isinstance(cases, list):
        raise ValueError("R2 recall report cases are missing")
    return payload


def build_inspection(
    report: dict[str, Any],
    *,
    reader: R2RawEvidenceReader,
) -> dict[str, Any]:
    sources: list[dict[str, Any]] = []
    unique_keys: set[tuple[str, str]] = set()

    for case in report["cases"]:
        if not isinstance(case, Mapping):
            continue
        case_id = str(case.get("case_id") or "")
        query = case.get("query") or {}
        model_name = str(query.get("model_name") or "") if isinstance(query, Mapping) else ""
        candidates = case.get("promotion_candidates") or []
        if not isinstance(candidates, list):
            continue
        for candidate in candidates:
            if not isinstance(candidate, Mapping):
                continue
            raw_key = str(candidate.get("raw_object_key") or "").strip()
            product_title = str(candidate.get("product_title") or "").strip()
            if not raw_key:
                continue
            unique = (case_id, raw_key)
            if unique in unique_keys:
                continue
            unique_keys.add(unique)

            obj = R2RawObject(
                bucket=reader.bucket,
                key=raw_key,
                payload_hash=_payload_hash_from_key(raw_key),
                stored_bytes=0,
                last_modified=None,
            )
            payload = reader.get_public_json(obj)
            matching_records = inspect_payload(
                payload,
                model_name=model_name,
                product_title=product_title,
            )
            sources.append(
                {
                    "case_id": case_id,
                    "model_name": model_name,
                    "product_title": product_title,
                    "raw_object_key": raw_key,
                    "matching_record_count": len(matching_records),
                    "records": matching_records,
                }
            )

    return {
        "schema": OUTPUT_SCHEMA,
        "status": "SUCCESS",
        "source_count": len(sources),
        "sources": sources,
    }


def _write_summary(report: dict[str, Any], path: Path) -> None:
    lines = [
        "# R2 Promotion Source Inspection",
        "",
        f"- inspected raw sources: **{report['source_count']}**",
        "",
    ]
    for source in report["sources"]:
        lines.extend(
            [
                f"## {source['case_id']}",
                "",
                f"- model: `{source['model_name'] or '-'}`",
                f"- raw object: `{source['raw_object_key']}`",
                f"- matching records: **{source['matching_record_count']}**",
                "",
            ]
        )
        for index, fields in enumerate(source["records"], start=1):
            lines.append(f"### Record {index}")
            lines.append("")
            for key, value in fields.items():
                lines.append(f"- {key}: `{value}`")
            lines.append("")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Inspect raw R2 provenance for broad-reference promotion candidates"
    )
    parser.add_argument(
        "--recall-report",
        type=Path,
        default=Path("artifacts/r2-search-recall/report.json"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("artifacts/r2-search-recall/promotion-source-inspection.json"),
    )
    parser.add_argument(
        "--summary",
        type=Path,
        default=Path("artifacts/r2-search-recall/promotion-source-inspection.md"),
    )
    args = parser.parse_args()

    settings = Settings()
    if not settings.r2_configured:
        raise RuntimeError("R2 configuration is incomplete")
    reader = R2RawEvidenceReader.from_settings(settings)
    report = build_inspection(_load_recall_report(args.recall_report), reader=reader)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    _write_summary(report, args.summary)
    print(json.dumps({"source_count": report["source_count"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

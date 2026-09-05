from __future__ import annotations

import argparse
import csv
import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

from purchase_price.services.quote_extraction import (
    QuoteExtractionError,
    QuoteItem,
    extract_quote_file,
    parse_quote_decimal,
)
from purchase_price.services.quote_extraction_diagnostics import (
    diagnose_quote_extraction,
    diagnose_quote_extraction_error,
)

_REQUIRED_COLUMNS = {
    "case_id",
    "file_path",
    "item_index",
    "product_name",
    "manufacturer",
    "model_name",
    "specification",
    "quantity",
    "unit_price",
    "total_amount",
}
_TEXT_FIELDS = ("product_name", "manufacturer", "model_name", "specification")
_DECIMAL_FIELDS = ("quantity", "unit_price", "total_amount")


@dataclass(frozen=True)
class ExpectedItem:
    item_index: int
    values: dict[str, str]


@dataclass(frozen=True)
class UatCase:
    case_id: str
    file_path: str
    expected_items: tuple[ExpectedItem, ...]


def _normalize_text(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip()).casefold()


def _load_cases(path: Path) -> tuple[UatCase, ...]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        fieldnames = set(reader.fieldnames or ())
        missing = sorted(_REQUIRED_COLUMNS - fieldnames)
        if missing:
            raise ValueError("UAT manifest 필수 열 누락: " + ", ".join(missing))

        grouped: dict[str, list[ExpectedItem]] = defaultdict(list)
        file_paths: dict[str, str] = {}
        seen_indexes: set[tuple[str, int]] = set()
        for row in reader:
            case_id = (row.get("case_id") or "").strip()
            file_path = (row.get("file_path") or "").strip()
            if not case_id or not file_path:
                raise ValueError("case_id와 file_path는 비울 수 없습니다.")
            try:
                item_index = int((row.get("item_index") or "").strip())
            except ValueError as exc:
                raise ValueError(f"{case_id}: item_index는 1 이상의 정수여야 합니다.") from exc
            if item_index < 1:
                raise ValueError(f"{case_id}: item_index는 1 이상의 정수여야 합니다.")
            key = (case_id, item_index)
            if key in seen_indexes:
                raise ValueError(f"{case_id}: item_index {item_index} 중복")
            seen_indexes.add(key)

            previous_path = file_paths.setdefault(case_id, file_path)
            if previous_path != file_path:
                raise ValueError(f"{case_id}: 동일 case_id에 서로 다른 file_path가 있습니다.")
            grouped[case_id].append(
                ExpectedItem(
                    item_index=item_index,
                    values={field: (row.get(field) or "").strip() for field in _TEXT_FIELDS + _DECIMAL_FIELDS},
                )
            )

    return tuple(
        UatCase(
            case_id=case_id,
            file_path=file_paths[case_id],
            expected_items=tuple(sorted(items, key=lambda item: item.item_index)),
        )
        for case_id, items in grouped.items()
    )


def _resolve_case_path(root: Path, file_path: str) -> Path:
    candidate = Path(file_path)
    if candidate.is_absolute():
        return candidate
    root = root.resolve()
    resolved = (root / candidate).resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"UAT file_path가 root 밖을 가리킵니다: {file_path}") from exc
    return resolved


def _compare_item(expected: ExpectedItem, actual: QuoteItem) -> tuple[int, int, list[str]]:
    scored = 0
    errors = 0
    error_fields: list[str] = []

    for field in _TEXT_FIELDS:
        expected_value = expected.values[field]
        if not expected_value:
            continue
        scored += 1
        if _normalize_text(expected_value) != _normalize_text(getattr(actual, field)):
            errors += 1
            error_fields.append(field)

    for field in _DECIMAL_FIELDS:
        expected_value = expected.values[field]
        if not expected_value:
            continue
        scored += 1
        if parse_quote_decimal(expected_value) != getattr(actual, field):
            errors += 1
            error_fields.append(field)

    return scored, errors, error_fields


def evaluate_cases(cases: tuple[UatCase, ...], *, root: Path) -> tuple[list[dict[str, object]], dict[str, object]]:
    case_results: list[dict[str, object]] = []
    strategies: Counter[str] = Counter()
    total_scored_fields = 0
    total_field_errors = 0
    extraction_failures = 0
    exact_item_count_cases = 0

    for case in cases:
        path = _resolve_case_path(root, case.file_path)
        expected_count = len(case.expected_items)
        try:
            extraction = extract_quote_file(path)
        except (QuoteExtractionError, OSError) as exc:
            extraction_failures += 1
            if isinstance(exc, QuoteExtractionError):
                diagnostics = diagnose_quote_extraction_error(path, exc)
                strategy_label = diagnostics.strategy_label
                for strategy in diagnostics.strategies:
                    strategies[strategy.value] += 1
            else:
                strategy_label = "파일 읽기 실패"
            case_results.append(
                {
                    "case_id": case.case_id,
                    "status": "EXTRACTION_FAILED",
                    "expected_item_count": expected_count,
                    "actual_item_count": 0,
                    "strategy": strategy_label,
                    "scored_fields": 0,
                    "field_errors": 0,
                    "error_fields": "",
                }
            )
            continue

        diagnostics = diagnose_quote_extraction(path, extraction)
        for strategy in diagnostics.strategies:
            strategies[strategy.value] += 1

        actual_count = len(extraction.items)
        item_count_ok = expected_count == actual_count
        if item_count_ok:
            exact_item_count_cases += 1

        scored_fields = 0
        field_errors = 0
        error_fields: set[str] = set()
        for expected, actual in zip(case.expected_items, extraction.items, strict=False):
            scored, errors, fields = _compare_item(expected, actual)
            scored_fields += scored
            field_errors += errors
            error_fields.update(fields)

        total_scored_fields += scored_fields
        total_field_errors += field_errors
        status = "PASS" if item_count_ok and field_errors == 0 else "REVIEW_REQUIRED"
        case_results.append(
            {
                "case_id": case.case_id,
                "status": status,
                "expected_item_count": expected_count,
                "actual_item_count": actual_count,
                "strategy": diagnostics.strategy_label,
                "scored_fields": scored_fields,
                "field_errors": field_errors,
                "error_fields": "|".join(sorted(error_fields)),
            }
        )

    total_cases = len(cases)
    processed_cases = total_cases - extraction_failures
    summary = {
        "total_cases": total_cases,
        "processed_cases": processed_cases,
        "extraction_failures": extraction_failures,
        "extraction_failure_rate": extraction_failures / total_cases if total_cases else None,
        "exact_item_count_cases": exact_item_count_cases,
        "exact_item_count_rate": exact_item_count_cases / total_cases if total_cases else None,
        "scored_fields": total_scored_fields,
        "field_errors": total_field_errors,
        "field_error_rate": total_field_errors / total_scored_fields if total_scored_fields else None,
        "strategy_counts": dict(sorted(strategies.items())),
        "privacy_note": "결과에는 견적 원문, 제품명, 업체명, 단가/총액 값을 기록하지 않음",
    }
    return case_results, summary


def _write_results(output_dir: Path, rows: list[dict[str, object]], summary: dict[str, object]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    result_path = output_dir / "quote-extraction-uat-results.csv"
    summary_path = output_dir / "quote-extraction-uat-summary.json"
    fields = (
        "case_id",
        "status",
        "expected_item_count",
        "actual_item_count",
        "strategy",
        "scored_fields",
        "field_errors",
        "error_fields",
    )
    with result_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="실제 견적 파일의 추출 정확도를 로컬에서 측정합니다.")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--min-cases", type=int, default=5)
    parser.add_argument("--fail-on-errors", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    cases = _load_cases(args.manifest)
    rows, summary = evaluate_cases(cases, root=args.root)
    summary["minimum_case_target"] = args.min_cases
    summary["minimum_case_target_met"] = len(cases) >= args.min_cases
    _write_results(args.output_dir, rows, summary)

    print(f"total_cases={summary['total_cases']}")
    print(f"processed_cases={summary['processed_cases']}")
    print(f"extraction_failures={summary['extraction_failures']}")
    print(f"exact_item_count_cases={summary['exact_item_count_cases']}")
    print(f"scored_fields={summary['scored_fields']}")
    print(f"field_errors={summary['field_errors']}")
    print(f"field_error_rate={summary['field_error_rate']}")

    if len(cases) < args.min_cases:
        print(f"UAT 미완료: 최소 {args.min_cases}건이 필요합니다.")
        return 2
    if args.fail_on_errors and (summary["extraction_failures"] or summary["field_errors"]):
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

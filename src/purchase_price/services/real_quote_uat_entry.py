from __future__ import annotations

import csv
import io
import math
from collections.abc import Mapping, Sequence
from typing import Any

from purchase_price.scripts.summarize_real_quote_uat import REAL_UAT_COLUMNS

UI_NOT_EVALUATED = "미평가"
UI_NO_ISSUE = "없음"
UI_OCCURRED = "발생"
UI_CORRECT = "정확"
UI_ERROR = "오류"
UI_FOUND = "확보"
UI_NOT_FOUND = "미확보"
UI_TRACEABLE = "가능"
UI_NOT_TRACEABLE = "불가"

ERROR_SIGNAL_OPTIONS = (UI_NOT_EVALUATED, UI_NO_ISSUE, UI_OCCURRED)
CORRECTNESS_OPTIONS = (UI_NOT_EVALUATED, UI_CORRECT, UI_ERROR)
EVIDENCE_OPTIONS = (UI_NOT_EVALUATED, UI_FOUND, UI_NOT_FOUND)
TRACE_OPTIONS = (UI_NOT_EVALUATED, UI_TRACEABLE, UI_NOT_TRACEABLE)
SAMPLE_CLASSES = (
    "xlsx",
    "xls",
    "pdf_text",
    "pdf_ocr",
    "pdf_commercial",
    "direct_search",
    "other",
)

UI_COLUMNS = (
    "검토완료",
    "케이스ID",
    "표본유형",
    "공개사용승인",
    "제품식별 FP",
    "제품식별 FN",
    "비교판정 FP",
    "비교판정 FN",
    "0건/실패 구분",
    "직접가격 근거",
    "근거ID 추적",
    "원문URL 추적",
    "Fingerprint 추적",
    "수작업 분",
    "시스템 분",
    "재사용가치(1~5)",
    "검토메모",
)


def default_entry_rows(count: int = 5) -> list[dict[str, Any]]:
    if count < 1:
        raise ValueError("count must be positive")
    rows: list[dict[str, Any]] = []
    for index in range(1, count + 1):
        rows.append(
            {
                "검토완료": False,
                "케이스ID": f"REAL-{index:03d}",
                "표본유형": "other",
                "공개사용승인": False,
                "제품식별 FP": UI_NOT_EVALUATED,
                "제품식별 FN": UI_NOT_EVALUATED,
                "비교판정 FP": UI_NOT_EVALUATED,
                "비교판정 FN": UI_NOT_EVALUATED,
                "0건/실패 구분": UI_NOT_EVALUATED,
                "직접가격 근거": UI_NOT_EVALUATED,
                "근거ID 추적": UI_NOT_EVALUATED,
                "원문URL 추적": UI_NOT_EVALUATED,
                "Fingerprint 추적": UI_NOT_EVALUATED,
                "수작업 분": None,
                "시스템 분": None,
                "재사용가치(1~5)": None,
                "검토메모": "",
            }
        )
    return rows


def _bool_text(value: object) -> str:
    return "true" if bool(value) else "false"


def _error_signal(value: object) -> str:
    text = str(value or "").strip()
    if text == UI_NOT_EVALUATED:
        return ""
    if text == UI_NO_ISSUE:
        return "false"
    if text == UI_OCCURRED:
        return "true"
    raise ValueError(f"invalid error-signal value: {value!r}")


def _correctness(value: object) -> str:
    text = str(value or "").strip()
    if text == UI_NOT_EVALUATED:
        return ""
    if text == UI_CORRECT:
        return "true"
    if text == UI_ERROR:
        return "false"
    raise ValueError(f"invalid correctness value: {value!r}")


def _evidence(value: object) -> str:
    text = str(value or "").strip()
    if text == UI_NOT_EVALUATED:
        return ""
    if text == UI_FOUND:
        return "true"
    if text == UI_NOT_FOUND:
        return "false"
    raise ValueError(f"invalid evidence value: {value!r}")


def _trace(value: object) -> str:
    text = str(value or "").strip()
    if text == UI_NOT_EVALUATED:
        return ""
    if text == UI_TRACEABLE:
        return "true"
    if text == UI_NOT_TRACEABLE:
        return "false"
    raise ValueError(f"invalid traceability value: {value!r}")


def _number_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and math.isnan(value):
        return ""
    text = str(value).strip()
    return "" if not text or text.casefold() == "nan" else text


def _number_or_none(value: object) -> float | None:
    text = _number_text(value)
    if not text:
        return None
    return float(text)


def normalize_entry_rows(rows: Sequence[Mapping[str, object]]) -> list[dict[str, str]]:
    normalized: list[dict[str, str]] = []
    seen_case_ids: set[str] = set()

    for row in rows:
        if not bool(row.get("검토완료")):
            continue

        case_id = str(row.get("케이스ID") or "").strip()
        if not case_id:
            raise ValueError("검토완료 케이스에는 케이스ID가 필요합니다.")
        if case_id in seen_case_ids:
            raise ValueError(f"중복 케이스ID: {case_id}")
        seen_case_ids.add(case_id)

        sample_class = str(row.get("표본유형") or "").strip()
        if sample_class not in SAMPLE_CLASSES:
            raise ValueError(f"지원하지 않는 표본유형: {sample_class!r}")

        manual = _number_or_none(row.get("수작업 분"))
        system = _number_or_none(row.get("시스템 분"))
        if manual is not None and manual < 0:
            raise ValueError("수작업 분은 음수일 수 없습니다.")
        if system is not None and system < 0:
            raise ValueError("시스템 분은 음수일 수 없습니다.")

        reuse = _number_or_none(row.get("재사용가치(1~5)"))
        if reuse is not None and not 1 <= reuse <= 5:
            raise ValueError("재사용가치는 1~5 범위여야 합니다.")

        time_saved = ""
        if manual is not None and system is not None:
            time_saved = str(round(manual - system, 2))

        normalized.append(
            {
                "case_id": case_id,
                "sample_class": sample_class,
                "approved_public_sample": _bool_text(row.get("공개사용승인")),
                "false_positive_identity": _error_signal(row.get("제품식별 FP")),
                "false_negative_identity": _error_signal(row.get("제품식별 FN")),
                "false_positive_comparison": _error_signal(row.get("비교판정 FP")),
                "false_negative_comparison": _error_signal(row.get("비교판정 FN")),
                "zero_vs_failure_correct": _correctness(row.get("0건/실패 구분")),
                "direct_evidence_found": _evidence(row.get("직접가격 근거")),
                "source_record_traceable": _trace(row.get("근거ID 추적")),
                "source_url_traceable": _trace(row.get("원문URL 추적")),
                "fingerprint_traceable": _trace(row.get("Fingerprint 추적")),
                "manual_minutes": _number_text(row.get("수작업 분")),
                "system_minutes": _number_text(row.get("시스템 분")),
                "time_saved_minutes": time_saved,
                "reuse_value_1_to_5": _number_text(row.get("재사용가치(1~5)")),
                "reviewer_notes": str(row.get("검토메모") or "").strip(),
            }
        )

    return normalized


def render_review_csv(rows: Sequence[Mapping[str, str]]) -> str:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=list(REAL_UAT_COLUMNS))
    writer.writeheader()
    for row in rows:
        writer.writerow({column: row.get(column, "") for column in REAL_UAT_COLUMNS})
    return buffer.getvalue()


def completeness(rows: Sequence[Mapping[str, str]]) -> dict[str, int | bool]:
    sample_count = len(rows)
    return {
        "sample_count": sample_count,
        "minimum_case_target": 5,
        "minimum_case_target_met": sample_count >= 5,
        "notes_missing": sum(
            1 for row in rows if not str(row.get("reviewer_notes") or "").strip()
        ),
        "identity_not_evaluated": sum(
            1
            for row in rows
            if not str(row.get("false_positive_identity") or "").strip()
            and not str(row.get("false_negative_identity") or "").strip()
        ),
        "comparison_not_evaluated": sum(
            1
            for row in rows
            if not str(row.get("false_positive_comparison") or "").strip()
            and not str(row.get("false_negative_comparison") or "").strip()
        ),
        "zero_failure_not_evaluated": sum(
            1 for row in rows if not str(row.get("zero_vs_failure_correct") or "").strip()
        ),
        "direct_evidence_not_evaluated": sum(
            1 for row in rows if not str(row.get("direct_evidence_found") or "").strip()
        ),
    }

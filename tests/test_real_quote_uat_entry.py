from __future__ import annotations

import csv
import io

import pytest

from purchase_price.scripts.summarize_real_quote_uat import summarize_real_uat
from purchase_price.services.real_quote_uat_entry import (
    UI_CORRECT,
    UI_FOUND,
    UI_NO_ISSUE,
    UI_NOT_EVALUATED,
    UI_TRACEABLE,
    completeness,
    default_entry_rows,
    normalize_entry_rows,
    render_review_csv,
)


def _completed_row() -> dict[str, object]:
    row = default_entry_rows(1)[0]
    row.update(
        {
            "검토완료": True,
            "표본유형": "pdf_text",
            "제품식별 FP": UI_NO_ISSUE,
            "제품식별 FN": UI_NO_ISSUE,
            "비교판정 FP": UI_NO_ISSUE,
            "비교판정 FN": UI_NO_ISSUE,
            "0건/실패 구분": UI_CORRECT,
            "직접가격 근거": UI_FOUND,
            "근거ID 추적": UI_TRACEABLE,
            "원문URL 추적": UI_TRACEABLE,
            "Fingerprint 추적": UI_TRACEABLE,
            "수작업 분": 20.0,
            "시스템 분": 8.5,
            "재사용가치(1~5)": 5,
            "검토메모": "원문 대조 완료",
        }
    )
    return row


def test_default_rows_start_unconfirmed_and_deidentified() -> None:
    rows = default_entry_rows(5)

    assert len(rows) == 5
    assert rows[0]["케이스ID"] == "REAL-001"
    assert rows[-1]["케이스ID"] == "REAL-005"
    assert all(row["검토완료"] is False for row in rows)
    assert all(row["제품식별 FP"] == UI_NOT_EVALUATED for row in rows)


def test_normalize_completed_row_matches_existing_summary_contract() -> None:
    rows = normalize_entry_rows([_completed_row()])

    assert len(rows) == 1
    row = rows[0]
    assert row["false_positive_identity"] == "false"
    assert row["zero_vs_failure_correct"] == "true"
    assert row["direct_evidence_found"] == "true"
    assert row["manual_minutes"] == "20.0"
    assert row["system_minutes"] == "8.5"
    assert row["time_saved_minutes"] == "11.5"

    summary = summarize_real_uat(rows)
    assert summary["sample_count"] == 1
    assert summary["critical_error_count"] == 0
    assert summary["time_saved_minutes_average"] == 11.5
    assert summary["reuse_value_average_1_to_5"] == 5.0


def test_unconfirmed_rows_are_not_counted() -> None:
    row = _completed_row()
    row["검토완료"] = False

    assert normalize_entry_rows([row]) == []


def test_duplicate_case_id_fails_closed() -> None:
    first = _completed_row()
    second = _completed_row()

    with pytest.raises(ValueError, match="중복 케이스ID"):
        normalize_entry_rows([first, second])


def test_completed_case_requires_case_id() -> None:
    row = _completed_row()
    row["케이스ID"] = ""

    with pytest.raises(ValueError, match="케이스ID"):
        normalize_entry_rows([row])


def test_invalid_reuse_value_fails_closed() -> None:
    row = _completed_row()
    row["재사용가치(1~5)"] = 6

    with pytest.raises(ValueError, match="1~5"):
        normalize_entry_rows([row])


def test_csv_export_round_trips_required_columns() -> None:
    normalized = normalize_entry_rows([_completed_row()])
    rendered = render_review_csv(normalized)
    reader = csv.DictReader(io.StringIO(rendered))
    rows = list(reader)

    assert len(rows) == 1
    assert rows[0]["case_id"] == "REAL-001"
    assert rows[0]["time_saved_minutes"] == "11.5"
    assert rows[0]["reviewer_notes"] == "원문 대조 완료"


def test_completeness_does_not_treat_unreviewed_dimensions_as_success() -> None:
    row = _completed_row()
    row["제품식별 FP"] = UI_NOT_EVALUATED
    row["제품식별 FN"] = UI_NOT_EVALUATED
    normalized = normalize_entry_rows([row])

    report = completeness(normalized)

    assert report["sample_count"] == 1
    assert report["minimum_case_target_met"] is False
    assert report["identity_not_evaluated"] == 1
    assert report["comparison_not_evaluated"] == 0
    assert report["notes_missing"] == 0

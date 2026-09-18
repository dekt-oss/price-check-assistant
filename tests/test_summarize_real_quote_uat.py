import csv
from pathlib import Path

import pytest

from purchase_price.scripts.summarize_real_quote_uat import (
    REQUIRED_COLUMNS,
    load_real_uat_csv,
    render_summary_markdown,
    summarize_real_uat,
)


def _row(**updates: str) -> dict[str, str]:
    row = {column: "" for column in REQUIRED_COLUMNS}
    row.update(
        {
            "case_id": "REAL-01",
            "sample_class": "실제 견적",
            "approved_public_sample": "true",
            "reviewer_notes": "reviewed",
        }
    )
    row.update(updates)
    return row


def test_real_uat_summary_counts_precision_recall_and_value_signals() -> None:
    rows = [
        _row(
            case_id="REAL-01",
            false_positive_identity="false",
            false_negative_identity="false",
            false_positive_comparison="false",
            false_negative_comparison="true",
            zero_vs_failure_correct="true",
            direct_evidence_found="true",
            source_record_traceable="true",
            source_url_traceable="true",
            fingerprint_traceable="true",
            manual_minutes="20",
            system_minutes="5",
            time_saved_minutes="15",
            reuse_value_1_to_5="5",
        ),
        _row(
            case_id="REAL-02",
            approved_public_sample="false",
            false_positive_identity="true",
            false_negative_identity="false",
            false_positive_comparison="false",
            false_negative_comparison="false",
            zero_vs_failure_correct="false",
            direct_evidence_found="false",
            source_record_traceable="true",
            source_url_traceable="false",
            fingerprint_traceable="true",
            manual_minutes="10",
            system_minutes="8",
            time_saved_minutes="2",
            reuse_value_1_to_5="3",
        ),
    ]

    summary = summarize_real_uat(rows)

    assert summary["sample_count"] == 2
    assert summary["approved_public_sample_count"] == 1
    assert summary["identity_false_positive_count"] == 1
    assert summary["identity_false_negative_count"] == 0
    assert summary["comparison_false_positive_count"] == 0
    assert summary["comparison_false_negative_count"] == 1
    assert summary["zero_vs_failure_error_count"] == 1
    assert summary["direct_evidence_hit_rate_percent"] == 50.0
    assert summary["traceability_failure_count"] == 1
    assert summary["traceability_success_rate_percent"] == 83.3
    assert summary["manual_minutes_average"] == 15.0
    assert summary["system_minutes_average"] == 6.5
    assert summary["time_saved_minutes_average"] == 8.5
    assert summary["time_saved_minutes_median"] == 8.5
    assert summary["reuse_value_average_1_to_5"] == 4.0
    assert summary["critical_false_positive_count"] == 1
    assert summary["critical_error_count"] == 2
    assert summary["conservative_false_negative_signal_count"] == 1

    markdown = render_summary_markdown(summary)
    assert "Critical false positive" in markdown
    assert "재사용 가치" in markdown
    assert "83.3%" in markdown


def test_real_uat_summary_rejects_out_of_range_reuse_value() -> None:
    with pytest.raises(ValueError, match="between 1 and 5"):
        summarize_real_uat([_row(reuse_value_1_to_5="6")])


def test_load_real_uat_csv_validates_required_columns(tmp_path: Path) -> None:
    path = tmp_path / "bad.csv"
    path.write_text("case_id,sample_class\nREAL-01,test\n", encoding="utf-8")

    with pytest.raises(ValueError, match="missing required columns"):
        load_real_uat_csv(path)


def test_load_real_uat_csv_accepts_controlled_uat_shape(tmp_path: Path) -> None:
    path = tmp_path / "real.csv"
    fields = sorted(REQUIRED_COLUMNS)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerow(_row(case_id="REAL-001"))

    rows = load_real_uat_csv(path)

    assert rows[0]["case_id"] == "REAL-001"

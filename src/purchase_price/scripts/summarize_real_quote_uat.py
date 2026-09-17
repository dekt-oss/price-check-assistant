from __future__ import annotations

import argparse
import csv
import json
from decimal import Decimal, InvalidOperation
from pathlib import Path
from statistics import median
from typing import Any

REQUIRED_COLUMNS = {
    "case_id",
    "sample_class",
    "approved_public_sample",
    "false_positive_identity",
    "false_negative_identity",
    "false_positive_comparison",
    "false_negative_comparison",
    "zero_vs_failure_correct",
    "source_record_traceable",
    "source_url_traceable",
    "fingerprint_traceable",
    "manual_minutes",
    "system_minutes",
    "time_saved_minutes",
    "reuse_value_1_to_5",
    "reviewer_notes",
}


def _bool(value: object) -> bool | None:
    text = str(value or "").strip().casefold()
    if not text:
        return None
    if text in {"true", "1", "yes", "y"}:
        return True
    if text in {"false", "0", "no", "n"}:
        return False
    raise ValueError(f"invalid boolean value: {value!r}")


def _decimal(value: object) -> Decimal | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        result = Decimal(text)
    except InvalidOperation as exc:
        raise ValueError(f"invalid numeric value: {value!r}") from exc
    if not result.is_finite():
        raise ValueError(f"non-finite numeric value: {value!r}")
    return result


def _round(value: Decimal | None) -> float | None:
    return None if value is None else round(float(value), 2)


def _average(values: list[Decimal]) -> Decimal | None:
    if not values:
        return None
    return sum(values, Decimal("0")) / Decimal(len(values))


def _median(values: list[Decimal]) -> Decimal | None:
    if not values:
        return None
    return Decimal(str(median(values)))


def _rate(true_count: int, evaluated_count: int) -> float | None:
    if evaluated_count == 0:
        return None
    return round(true_count / evaluated_count * 100, 1)


def load_real_uat_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        columns = set(reader.fieldnames or ())
        missing = sorted(REQUIRED_COLUMNS - columns)
        if missing:
            raise ValueError(f"real UAT CSV missing required columns: {missing}")
        rows = [dict(row) for row in reader if any(str(value or "").strip() for value in row.values())]
    if not rows:
        raise ValueError("real UAT CSV has no data rows")
    for index, row in enumerate(rows, start=2):
        if not str(row.get("case_id") or "").strip():
            raise ValueError(f"real UAT CSV row {index} has no case_id")
    return rows


def summarize_real_uat(rows: list[dict[str, str]]) -> dict[str, Any]:
    if not rows:
        raise ValueError("at least one real UAT row is required")

    identity_evaluated = 0
    identity_fp = 0
    identity_fn = 0
    comparison_evaluated = 0
    comparison_fp = 0
    comparison_fn = 0
    zero_failure_evaluated = 0
    zero_failure_errors = 0
    approved_samples = 0
    direct_evidence_evaluated = 0
    direct_evidence_hits = 0
    trace_evaluated = 0
    trace_failures = 0
    notes_missing = 0
    manual_minutes: list[Decimal] = []
    system_minutes: list[Decimal] = []
    saved_minutes: list[Decimal] = []
    reuse_values: list[Decimal] = []

    for row in rows:
        if _bool(row.get("approved_public_sample")) is True:
            approved_samples += 1

        id_fp = _bool(row.get("false_positive_identity"))
        id_fn = _bool(row.get("false_negative_identity"))
        if id_fp is not None or id_fn is not None:
            identity_evaluated += 1
            identity_fp += id_fp is True
            identity_fn += id_fn is True

        cmp_fp = _bool(row.get("false_positive_comparison"))
        cmp_fn = _bool(row.get("false_negative_comparison"))
        if cmp_fp is not None or cmp_fn is not None:
            comparison_evaluated += 1
            comparison_fp += cmp_fp is True
            comparison_fn += cmp_fn is True

        zero_ok = _bool(row.get("zero_vs_failure_correct"))
        if zero_ok is not None:
            zero_failure_evaluated += 1
            zero_failure_errors += zero_ok is False

        direct_found = _bool(row.get("direct_evidence_found"))
        if direct_found is not None:
            direct_evidence_evaluated += 1
            direct_evidence_hits += direct_found is True

        trace_values = [
            _bool(row.get("source_record_traceable")),
            _bool(row.get("source_url_traceable")),
            _bool(row.get("fingerprint_traceable")),
        ]
        for value in trace_values:
            if value is None:
                continue
            trace_evaluated += 1
            trace_failures += value is False

        manual = _decimal(row.get("manual_minutes"))
        system = _decimal(row.get("system_minutes"))
        saved = _decimal(row.get("time_saved_minutes"))
        reuse = _decimal(row.get("reuse_value_1_to_5"))
        if manual is not None:
            if manual < 0:
                raise ValueError("manual_minutes must be non-negative")
            manual_minutes.append(manual)
        if system is not None:
            if system < 0:
                raise ValueError("system_minutes must be non-negative")
            system_minutes.append(system)
        if saved is not None:
            saved_minutes.append(saved)
        if reuse is not None:
            if reuse < 1 or reuse > 5:
                raise ValueError("reuse_value_1_to_5 must be between 1 and 5")
            reuse_values.append(reuse)

        if not str(row.get("reviewer_notes") or "").strip():
            notes_missing += 1

    critical_false_positive_count = identity_fp + comparison_fp
    critical_error_count = critical_false_positive_count + zero_failure_errors

    return {
        "mode": "real_quote_uat_reviewed_samples",
        "sample_count": len(rows),
        "approved_public_sample_count": approved_samples,
        "identity_evaluated_count": identity_evaluated,
        "identity_false_positive_count": identity_fp,
        "identity_false_negative_count": identity_fn,
        "identity_false_positive_rate_percent": _rate(identity_fp, identity_evaluated),
        "identity_false_negative_rate_percent": _rate(identity_fn, identity_evaluated),
        "comparison_evaluated_count": comparison_evaluated,
        "comparison_false_positive_count": comparison_fp,
        "comparison_false_negative_count": comparison_fn,
        "comparison_false_positive_rate_percent": _rate(comparison_fp, comparison_evaluated),
        "comparison_false_negative_rate_percent": _rate(comparison_fn, comparison_evaluated),
        "zero_vs_failure_evaluated_count": zero_failure_evaluated,
        "zero_vs_failure_error_count": zero_failure_errors,
        "direct_evidence_evaluated_count": direct_evidence_evaluated,
        "direct_evidence_hit_count": direct_evidence_hits,
        "direct_evidence_hit_rate_percent": _rate(direct_evidence_hits, direct_evidence_evaluated),
        "traceability_field_evaluated_count": trace_evaluated,
        "traceability_failure_count": trace_failures,
        "traceability_success_rate_percent": _rate(
            trace_evaluated - trace_failures,
            trace_evaluated,
        ),
        "manual_minutes_average": _round(_average(manual_minutes)),
        "system_minutes_average": _round(_average(system_minutes)),
        "time_saved_minutes_average": _round(_average(saved_minutes)),
        "time_saved_minutes_median": _round(_median(saved_minutes)),
        "reuse_value_average_1_to_5": _round(_average(reuse_values)),
        "reviewer_notes_missing_count": notes_missing,
        "critical_false_positive_count": critical_false_positive_count,
        "critical_error_count": critical_error_count,
        "conservative_false_negative_signal_count": identity_fn + comparison_fn,
    }


def render_summary_markdown(summary: dict[str, Any]) -> str:
    def value(key: str, suffix: str = "") -> str:
        raw = summary.get(key)
        return "N/A" if raw is None else f"{raw}{suffix}"

    return "\n".join(
        [
            "# 실제 견적 UAT 요약",
            "",
            f"- 표본: **{summary['sample_count']}건** / 공개 사용 승인 표본 {summary['approved_public_sample_count']}건",
            (
                "- 제품식별 FP/FN: "
                f"**{summary['identity_false_positive_count']} / {summary['identity_false_negative_count']}건** "
                f"(FP {value('identity_false_positive_rate_percent', '%')}, "
                f"FN {value('identity_false_negative_rate_percent', '%')})"
            ),
            (
                "- 비교판정 FP/FN: "
                f"**{summary['comparison_false_positive_count']} / {summary['comparison_false_negative_count']}건** "
                f"(FP {value('comparison_false_positive_rate_percent', '%')}, "
                f"FN {value('comparison_false_negative_rate_percent', '%')})"
            ),
            (
                "- API 0건/실패 구분 오류: "
                f"**{summary['zero_vs_failure_error_count']}건** / "
                f"{summary['zero_vs_failure_evaluated_count']}건 평가"
            ),
            (
                "- 근거 추적성 성공률: "
                f"**{value('traceability_success_rate_percent', '%')}** "
                f"({summary['traceability_field_evaluated_count']}개 필드 평가)"
            ),
            (
                "- 직접가격 근거 회수율: "
                f"**{value('direct_evidence_hit_rate_percent', '%')}**"
            ),
            (
                "- 평균 수작업/시스템 시간: "
                f"**{value('manual_minutes_average', '분')} / "
                f"{value('system_minutes_average', '분')}**"
            ),
            (
                "- 시간절감: 평균 "
                f"**{value('time_saved_minutes_average', '분')}**, "
                f"중앙값 **{value('time_saved_minutes_median', '분')}**"
            ),
            (
                "- 재사용 가치: "
                f"**{value('reuse_value_average_1_to_5')} / 5**"
            ),
            "",
            "## 안전 신호",
            "",
            (
                f"- Critical false positive: **{summary['critical_false_positive_count']}건** "
                "(제품식별 + 비교판정)"
            ),
            (
                f"- Critical error 합계: **{summary['critical_error_count']}건** "
                "(FP + 정상0건/실패 오분류)"
            ),
            (
                f"- 보수적 false negative 신호: **{summary['conservative_false_negative_signal_count']}건** "
                "— 실제 반복 표본 없이 규칙을 자동 완화하지 않습니다."
            ),
            (
                f"- Reviewer note 누락: **{summary['reviewer_notes_missing_count']}건**"
            ),
            "",
        ]
    )


def write_outputs(output_dir: Path, summary: dict[str, Any]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "real-quote-uat-summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (output_dir / "real-quote-uat-summary.md").write_text(
        render_summary_markdown(summary),
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Summarize human-reviewed real quote UAT results."
    )
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("artifacts/real-quote-uat"),
    )
    args = parser.parse_args()
    rows = load_real_uat_csv(args.input)
    summary = summarize_real_uat(rows)
    write_outputs(args.output_dir, summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

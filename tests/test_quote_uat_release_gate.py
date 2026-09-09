from purchase_price.services.quote_uat_review import QuoteUatCaseMetric, evaluate_uat_release_gate


def _pass(case_id: str, strategy: str) -> QuoteUatCaseMetric:
    return QuoteUatCaseMetric(
        case_id,
        strategy,
        1,
        1,
        1,
        0,
        0,
        3,
        0,
        (),
        commercial_scored_fields=1 if strategy == "pdf_commercial" else 0,
    )


def test_release_gate_requires_all_five_planned_formats() -> None:
    metrics = (
        _pass("1", "xlsx"),
        _pass("2", "xls"),
        _pass("3", "pdf_text"),
        _pass("4", "pdf_ocr"),
        _pass("5", "pdf_commercial"),
    )
    gate = evaluate_uat_release_gate(metrics)
    assert gate["release_ready"] is True
    assert gate["blockers"] == []
    assert gate["missing_strategies"] == []


def test_release_gate_fails_closed_on_unscored_commercial_case() -> None:
    metrics = (
        _pass("1", "xlsx"),
        _pass("2", "xls"),
        _pass("3", "pdf_text"),
        _pass("4", "pdf_ocr"),
        QuoteUatCaseMetric("5", "pdf_commercial", 1, 1, 1, 0, 0, 3, 0, ()),
    )
    gate = evaluate_uat_release_gate(metrics)

    assert gate["release_ready"] is False
    assert "pdf_commercial" in gate["missing_strategies"]
    assert "pdf_commercial requires scored commercial ground truth" in gate["blockers"]


def test_release_gate_fails_closed_on_missing_format_or_false_positive() -> None:
    metrics = (
        _pass("1", "xlsx"),
        _pass("2", "xls"),
        _pass("3", "pdf_text"),
        _pass("4", "pdf_ocr"),
        QuoteUatCaseMetric("5", "pdf_ocr", 1, 2, 1, 1, 0, 3, 0, ()),
    )
    gate = evaluate_uat_release_gate(metrics)
    assert gate["release_ready"] is False
    assert "pdf_commercial" in gate["missing_strategies"]
    assert "false-positive item present" in gate["blockers"]

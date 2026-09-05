from decimal import Decimal
from pathlib import Path

import pytest

from purchase_price.scripts import run_quote_extraction_uat as runner
from purchase_price.services.quote_extraction import QuoteExtractionResult, QuoteItem


def _expected_item(**overrides: str) -> runner.ExpectedItem:
    values = {
        "product_name": "Infusion Pump",
        "manufacturer": "Acme",
        "model_name": "IP-200",
        "specification": "220V",
        "quantity": "2",
        "unit_price": "1,250,000",
        "total_amount": "2,500,000",
    }
    values.update(overrides)
    return runner.ExpectedItem(item_index=1, values=values)


def test_evaluate_cases_reports_aggregate_errors_without_sensitive_values(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    quote_path = tmp_path / "quote.pdf"
    quote_path.write_bytes(b"fixture")
    case = runner.UatCase(
        case_id="QUOTE-01",
        file_path="quote.pdf",
        expected_items=(_expected_item(),),
    )
    extraction = QuoteExtractionResult(
        items=(
            QuoteItem(
                source_sheet="PDF 1페이지 단어좌표",
                source_row=2,
                product_name="Infusion Pump",
                manufacturer="Acme",
                model_name="IP-200",
                specification="110V",
                quantity=Decimal("2"),
                unit_price=Decimal("1250000"),
                total_amount=Decimal("2500000"),
            ),
        ),
        warnings=(),
    )
    monkeypatch.setattr(runner, "extract_quote_file", lambda _: extraction)

    rows, summary = runner.evaluate_cases((case,), root=tmp_path)

    assert rows[0]["status"] == "REVIEW_REQUIRED"
    assert rows[0]["field_errors"] == 1
    assert rows[0]["error_fields"] == "specification"
    assert summary["field_errors"] == 1
    assert summary["scored_fields"] == 7
    serialized = str(rows) + str(summary)
    assert "Infusion Pump" not in serialized
    assert "1250000" not in serialized
    assert "110V" not in serialized


def test_evaluate_cases_passes_exact_ground_truth(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    (tmp_path / "quote.pdf").write_bytes(b"fixture")
    case = runner.UatCase(
        case_id="QUOTE-01",
        file_path="quote.pdf",
        expected_items=(_expected_item(),),
    )
    extraction = QuoteExtractionResult(
        items=(
            QuoteItem(
                source_sheet="PDF 1페이지 표1",
                source_row=2,
                product_name="Infusion Pump",
                manufacturer="Acme",
                model_name="IP-200",
                specification="220V",
                quantity=Decimal("2"),
                unit_price=Decimal("1250000"),
                total_amount=Decimal("2500000"),
            ),
        ),
        warnings=(),
    )
    monkeypatch.setattr(runner, "extract_quote_file", lambda _: extraction)

    rows, summary = runner.evaluate_cases((case,), root=tmp_path)

    assert rows[0]["status"] == "PASS"
    assert summary["exact_item_count_cases"] == 1
    assert summary["field_error_rate"] == 0


def test_manifest_requires_consistent_file_path(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.csv"
    manifest.write_text(
        "case_id,file_path,item_index,product_name,manufacturer,model_name,"
        "specification,quantity,unit_price,total_amount\n"
        "Q1,a.pdf,1,A,,,,1,100,100\n"
        "Q1,b.pdf,2,B,,,,1,200,200\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="서로 다른 file_path"):
        runner._load_cases(manifest)


def test_relative_uat_path_cannot_escape_root(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="root 밖"):
        runner._resolve_case_path(tmp_path, "../secret.pdf")

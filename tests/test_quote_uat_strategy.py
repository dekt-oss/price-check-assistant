import pytest

from purchase_price.services.quote_uat_strategy import (
    default_uat_strategy,
    uat_strategy_options,
)


def test_excel_formats_map_to_release_gate_keys() -> None:
    assert default_uat_strategy(file_kind="xlsx", extraction_strategies=("xlsx_table",)) == "xlsx"
    assert default_uat_strategy(file_kind="xls", extraction_strategies=("xls_table",)) == "xls"
    assert uat_strategy_options(file_kind="xlsx") == ("xlsx",)
    assert uat_strategy_options(file_kind="xls") == ("xls",)


def test_pdf_text_and_ocr_paths_get_canonical_defaults() -> None:
    assert (
        default_uat_strategy(
            file_kind="pdf", extraction_strategies=("pdf_word_geometry",)
        )
        == "pdf_text"
    )
    assert (
        default_uat_strategy(file_kind="pdf", extraction_strategies=("pdf_local_ocr",))
        == "pdf_ocr"
    )
    assert (
        default_uat_strategy(file_kind="pdf", extraction_strategies=("pdf_ocr_unavailable",))
        == "pdf_ocr"
    )


def test_pdf_commercial_is_available_only_as_explicit_uat_designation() -> None:
    assert uat_strategy_options(file_kind="pdf") == (
        "pdf_text",
        "pdf_ocr",
        "pdf_commercial",
    )
    assert (
        default_uat_strategy(file_kind="pdf", extraction_strategies=("pdf_ruled_table",))
        != "pdf_commercial"
    )


def test_unsupported_file_kind_fails_closed() -> None:
    with pytest.raises(ValueError, match="지원하지 않는 UAT 파일 형식"):
        default_uat_strategy(file_kind="csv", extraction_strategies=())

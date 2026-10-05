from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from purchase_price.services.mfds_model_info_query import model_info_product_name


def _candidate(title: str, grade: str) -> SimpleNamespace:
    return SimpleNamespace(product_title=title, match_grade=grade)


def test_keeps_a_real_product_name() -> None:
    assert model_info_product_name("심장충격기", "NT-SG", ()) == "심장충격기"


def test_one_line_model_search_uses_product_class_of_direct_procurement_rows() -> None:
    candidates = (
        _candidate("심장충격기, 나눔테크, NT-SG", "B"),
        _candidate("심장충격기, 나눔테크, NT-SG", "B"),
        _candidate("의료용흡인기, 다른회사, NT-SG", "C"),
    )

    assert model_info_product_name("NT-SG", "NT-SG", candidates) == "심장충격기"
    assert model_info_product_name("", "NT-SG", candidates) == "심장충격기"


def test_falls_back_to_reference_rows_then_to_the_original_text() -> None:
    assert (
        model_info_product_name("NT-SG", "NT-SG", (_candidate("심장충격기, 나눔테크, NT-SG", "C"),))
        == "심장충격기"
    )
    assert model_info_product_name("NT-SG", "NT-SG", ()) == "NT-SG"


def test_dashboard_uses_product_class_for_deferred_model_info() -> None:
    source = Path("pages/1_대시보드.py").read_text(encoding="utf-8")

    assert "product_name = model_info_product_name(" in source

import inspect

from purchase_price.ui import widgets


def test_evidence_rows_split_ab_from_cd_reference() -> None:
    rows = [
        {"등급": "A", "근거ID": "a"},
        {"등급": "B", "근거ID": "b"},
        {"등급": "C", "근거ID": "c"},
        {"등급": "D", "근거ID": "d"},
    ]

    direct, reference = widgets.split_evidence_rows_by_match_grade(rows)

    assert [row["근거ID"] for row in direct] == ["a", "b"]
    assert [row["근거ID"] for row in reference] == ["c", "d"]


def test_evidence_ui_explicitly_separates_reference_section() -> None:
    source = inspect.getsource(widgets.render_evidence_table)

    assert "A/B 제품일치 근거" in source
    assert "C/D 참고자료 · 견적 판정 제외" in source
    assert "QUOTE_COMPARABLE" in source


def test_observation_card_names_median_explicitly() -> None:
    source = inspect.getsource(widgets.render_observation_cards)

    assert "중앙값(Median)" in source

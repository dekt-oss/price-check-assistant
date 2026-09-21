from types import SimpleNamespace

from purchase_price.scripts.audit_r2_broad_reference_composition import summarize_rows


def test_composition_summary_counts_exact_model_and_manufacturer_aliases() -> None:
    rows = [
        SimpleNamespace(
            model_name="CX30N",
            manufacturer="WIDE",
            unit_price=12000000,
        ),
        SimpleNamespace(
            model_name="Other Monitor",
            manufacturer="와이드",
            unit_price=8000000,
        ),
        SimpleNamespace(
            model_name="Other Monitor",
            manufacturer="Other",
            unit_price=6000000,
        ),
    ]

    report = summarize_rows(
        rows,
        query_model="CX30N",
        query_manufacturer="WIDE",
    )

    assert report["row_count"] == 3
    assert report["exact_model_rows"] == 1
    assert report["manufacturer_match_rows"] == 2
    assert report["price_min"] == 6000000
    assert report["price_max"] == 12000000
    assert report["top_models"][0] == ("Other Monitor", 2)


def test_composition_summary_handles_absent_model_and_price() -> None:
    rows = [
        SimpleNamespace(
            model_name=None,
            manufacturer=None,
            unit_price=None,
        )
    ]

    report = summarize_rows(
        rows,
        query_model="ROTAPRO",
        query_manufacturer="Boston Scientific",
    )

    assert report["row_count"] == 1
    assert report["exact_model_rows"] == 0
    assert report["manufacturer_match_rows"] == 0
    assert report["price_min"] is None
    assert report["price_max"] is None

import csv

import pytest

from purchase_price.ui.mapping_requests import register_mapping_request


def test_mapping_request_writes_identity_fields_only(tmp_path) -> None:
    path = tmp_path / "mapping_requests.csv"
    created = register_mapping_request(
        product_name="컬러 레이저프린터",
        manufacturer="FUJIFILM Business Innovation",
        model_name="ApeosPrint C5570 GK",
        path=path,
    )
    assert created is True
    with path.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert rows == [
        {
            "product_name": "컬러 레이저프린터",
            "manufacturer": "FUJIFILM Business Innovation",
            "model_name": "ApeosPrint C5570 GK",
        }
    ]
    assert set(rows[0]) == {"product_name", "manufacturer", "model_name"}


def test_mapping_request_deduplicates_same_identity(tmp_path) -> None:
    path = tmp_path / "mapping_requests.csv"
    kwargs = {
        "product_name": "Printer",
        "manufacturer": "Maker",
        "model_name": "M-1",
        "path": path,
    }
    assert register_mapping_request(**kwargs) is True
    assert register_mapping_request(**kwargs) is False


def test_mapping_request_requires_product_or_model(tmp_path) -> None:
    with pytest.raises(ValueError):
        register_mapping_request(
            product_name="",
            manufacturer="Maker",
            model_name="",
            path=tmp_path / "mapping_requests.csv",
        )

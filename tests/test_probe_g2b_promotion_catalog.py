from __future__ import annotations

from purchase_price.scripts.probe_g2b_promotion_catalog import build_probe
from purchase_price.services.g2b_catalog import G2BCatalogResult, G2BProductAttribute


def test_build_probe_uses_exact_product_id_from_raw_inspection() -> None:
    inspection = {
        "schema": "r2-promotion-source-inspection-v1",
        "sources": [
            {
                "case_id": "minion_mk1d",
                "records": [
                    {"prdctIdntNo": "25900137"},
                    {"prdctIdntNo": "25900137"},
                ],
            }
        ],
    }

    class FakeClient:
        def __init__(self) -> None:
            self.calls: list[str] = []

        def fetch_attributes(self, *, product_id: str):
            self.calls.append(product_id)
            return G2BCatalogResult(
                product_id=product_id,
                attributes=(
                    G2BProductAttribute(
                        product_id=product_id,
                        product_name="DNA서열분석기, Oxford nanopore technologies, (GB)MinION MK1D",
                        detail_product_code="4111581101",
                        attribute_name="모델명",
                        attribute_value="MinION MK1D",
                    ),
                ),
            )

    client = FakeClient()
    report = build_probe(inspection, client=client)

    assert client.calls == ["25900137"]
    assert report["status"] == "SUCCESS"
    assert report["product_count"] == 1
    assert report["products"][0]["detail_product_codes"] == ["4111581101"]
    assert report["products"][0]["attributes"][0]["value"] == "MinION MK1D"

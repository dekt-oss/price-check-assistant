from purchase_price.services.g2b_catalog import (
    G2B_CATALOG_ATTRIBUTE_OPERATION,
    G2B_CATALOG_BASE_URL,
    G2BCatalogClient,
)


class StubClient:
    def __init__(self, payload: dict) -> None:
        self.payload = payload
        self.calls: list[tuple[str, str, dict]] = []

    def get_json(self, base_url: str, endpoint: str, **params):
        self.calls.append((base_url, endpoint, params))
        return self.payload


def test_catalog_fetches_exact_product_id_and_filters_mismatched_rows() -> None:
    stub = StubClient(
        {
            "response": {
                "header": {"resultCode": "00", "resultMsg": "NORMAL SERVICE."},
                "body": {
                    "items": [
                        {
                            "prdctIdntNo": "24888744",
                            "prdctIdntNoNm": "레이저프린터",
                            "dtilPrdctClsfcNo": "4321210501",
                            "attrNm": "인쇄속도",
                            "attrVal": "55",
                            "attrUnit": "ppm",
                        },
                        {
                            "prdctIdntNo": "OTHER",
                            "prdctIdntNoNm": "무관품목",
                            "dtilPrdctClsfcNo": "0000000000",
                            "attrNm": "x",
                            "attrVal": "y",
                        },
                    ]
                },
            }
        }
    )
    client = G2BCatalogClient("unused", client=stub)

    result = client.fetch_attributes(product_id="24888744")

    assert stub.calls == [
        (
            G2B_CATALOG_BASE_URL,
            G2B_CATALOG_ATTRIBUTE_OPERATION,
            {"pageNo": 1, "numOfRows": 100, "prdctIdntNo": "24888744"},
        )
    ]
    assert len(result.attributes) == 1
    attribute = result.attributes[0]
    assert attribute.product_id == "24888744"
    assert attribute.detail_product_code == "4321210501"
    assert attribute.attribute_name == "인쇄속도"
    assert attribute.attribute_value == "55"
    assert attribute.attribute_unit == "ppm"
    assert result.detail_product_codes == ("4321210501",)


def test_catalog_requires_exact_product_id() -> None:
    stub = StubClient({"response": {"body": {"items": []}}})
    client = G2BCatalogClient("unused", client=stub)

    try:
        client.fetch_attributes(product_id="   ")
    except ValueError as exc:
        assert "product_id is required" in str(exc)
    else:
        raise AssertionError("blank product id must be rejected")

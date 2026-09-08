from purchase_price.services.g2b_classification_resolver import (
    DetailClassSearchField,
    G2BClassificationResolverClient,
    normalize_product_label,
)


class RecordingPortal:
    def __init__(self, items: list[dict]) -> None:
        self.items = items
        self.calls: list[tuple[str, str, dict]] = []

    def get_json(self, base_url: str, endpoint: str, **params):
        self.calls.append((base_url, endpoint, params))
        return {
            "response": {
                "header": {"resultCode": "00", "resultMsg": "OK"},
                "body": {
                    "items": self.items,
                    "totalCount": len(self.items),
                    "pageNo": 1,
                    "numOfRows": 100,
                },
            }
        }


def test_quote_label_normalization_preserves_subscript_meaning_and_parenthetical_spec() -> None:
    normalized = normalize_product_label("CO₂ Incubator(Water Jacket)")

    assert normalized.original == "CO₂ Incubator(Water Jacket)"
    assert normalized.base_name == "CO2 Incubator"
    assert normalized.parenthetical_terms == ("Water Jacket",)
    assert "CO Incubator" != normalized.base_name


def test_english_detail_class_search_uses_official_field_and_returns_candidate_only() -> None:
    portal = RecordingPortal(
        [
            {
                "dtilPrdctClsfcNo": "4110449801",
                "dtilPrdctClsfcNoNm": "이산화탄소배양기",
                "dtilPrdctClsfcNoEngNm": "Carbon dioxide incubators",
                "useYn": "Y",
            }
        ]
    )
    client = G2BClassificationResolverClient("key", client=portal)  # type: ignore[arg-type]

    result = client.search_detail_classes(
        term="incubator",
        field=DetailClassSearchField.ENGLISH_NAME,
    )

    _, endpoint, params = portal.calls[0]
    assert endpoint == "getPrdctClsfcNoUnit10Info02"
    assert params["dtilPrdctClsfcNoEngNm"] == "incubator"
    assert "dtilPrdctClsfcNoNm" not in params
    assert result.total_count == 1
    assert len(result.candidates) == 1
    candidate = result.candidates[0]
    assert candidate.detail_product_code == "4110449801"
    assert candidate.korean_name == "이산화탄소배양기"
    assert candidate.english_name == "Carbon dioxide incubators"
    assert candidate.search_field == DetailClassSearchField.ENGLISH_NAME
    assert candidate.search_term == "incubator"


def test_korean_search_does_not_create_verified_mapping_side_effect() -> None:
    portal = RecordingPortal(
        [
            {
                "dtilPrdctClsfcNo": "4110449801",
                "dtilPrdctClsfcNoNm": "이산화탄소배양기",
            },
            {
                "dtilPrdctClsfcNo": "4299030101",
                "dtilPrdctClsfcNoNm": "세포및조직배양기",
            },
        ]
    )
    client = G2BClassificationResolverClient("key", client=portal)  # type: ignore[arg-type]

    result = client.search_detail_classes(
        term="배양기",
        field=DetailClassSearchField.KOREAN_NAME,
    )

    assert [row.detail_product_code for row in result.candidates] == [
        "4110449801",
        "4299030101",
    ]
    # Resolver output has no verified/status field and performs no file/database writes. It is
    # deliberately a list of candidates, so downstream code must add an explicit confirmation gate.
    assert not hasattr(result.candidates[0], "verified")

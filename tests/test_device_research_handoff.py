from purchase_price.services.device_research_handoff import (
    DeviceResearchPrefill,
    build_device_research_prefill,
    parse_device_research_prefill,
)


def test_handoff_trims_and_preserves_only_identity_hints() -> None:
    prefill = build_device_research_prefill(
        product_name="  심장충격기  ",
        manufacturer="  예시메디칼 ",
        model_name=" DFM-100 ",
        specification=" biphasic ",
    )

    assert prefill == DeviceResearchPrefill(
        product_name="심장충격기",
        manufacturer="예시메디칼",
        model_name="DFM-100",
        specification="biphasic",
    )
    assert set(prefill.to_session_payload()) == {
        "product_name",
        "manufacturer",
        "model_name",
        "specification",
    }


def test_handoff_rejects_empty_identity_row() -> None:
    assert build_device_research_prefill(
        product_name=" ", manufacturer=None, model_name="<NA>", specification="nan"
    ) is None


def test_handoff_parser_ignores_quote_price_and_file_metadata() -> None:
    prefill = parse_device_research_prefill(
        {
            "product_name": "심장충격기",
            "manufacturer": "예시메디칼",
            "model_name": "DFM-100",
            "specification": "biphasic",
            "quote_unit_price": 1234567,
            "total_amount": 2469134,
            "source_sheet": "견적서",
            "source_row": 7,
            "uploaded_file": "hospital-quote.xls",
        }
    )

    assert prefill is not None
    assert prefill.to_session_payload() == {
        "product_name": "심장충격기",
        "manufacturer": "예시메디칼",
        "model_name": "DFM-100",
        "specification": "biphasic",
    }


def test_handoff_parser_rejects_non_mapping_payload() -> None:
    assert parse_device_research_prefill("not-a-payload") is None

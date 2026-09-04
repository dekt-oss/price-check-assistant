from pathlib import Path

from streamlit.testing.v1 import AppTest

from purchase_price.config import get_settings
from purchase_price.services.device_research_handoff import (
    DEVICE_RESEARCH_HANDOFF_SESSION_KEY,
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


def test_device_research_page_prefills_quote_identity(monkeypatch) -> None:
    monkeypatch.setenv("MFDS_SERVICE_KEY", "dummy-mfds-key")
    monkeypatch.setenv("G2B_SERVICE_KEY", "dummy-g2b-key")
    get_settings.cache_clear()

    page_path = Path(__file__).resolve().parents[1] / "pages" / "4_의료기기_시장조사.py"
    app = AppTest.from_file(page_path)
    app.session_state[DEVICE_RESEARCH_HANDOFF_SESSION_KEY] = {
        "product_name": "심장충격기",
        "manufacturer": "예시메디칼",
        "model_name": "DFM-100",
        "specification": "biphasic, pacing",
        "quote_unit_price": 1234567,
    }

    app.run(timeout=10)

    assert not app.exception
    inputs = {item.label: item.value for item in app.text_input}
    assert inputs["식약처 품목명"] == "심장충격기"
    assert inputs["모델명 (선택)"] == "DFM-100"
    assert inputs["확인할 업체명 (선택)"] == "예시메디칼"
    assert any("견적서 분석에서 선택한 행" in item.value for item in app.info)
    assert any("biphasic, pacing" in item.value for item in app.caption)

    get_settings.cache_clear()

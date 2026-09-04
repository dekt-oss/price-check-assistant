from pathlib import Path

from streamlit.testing.v1 import AppTest

from purchase_price.services.safety_support import (
    SafetyCheckStatus,
    build_manual_safety_check_state,
    no_match_safety_state,
)


def test_manual_safety_state_preserves_exact_verification_keys() -> None:
    state = build_manual_safety_check_state(
        model_name="DFM-100",
        permit_numbers=["수허 24-1", "수허 24-1", "제허 25-2"],
    )

    assert state.status == SafetyCheckStatus.CHECK_REQUIRED
    assert state.search_keys == (
        "모델명: DFM-100",
        "허가번호: 수허 24-1",
        "허가번호: 제허 25-2",
    )
    assert "안전하다는 뜻" in state.message


def test_manual_safety_state_without_identity_is_not_connected() -> None:
    state = build_manual_safety_check_state()

    assert state.status == SafetyCheckStatus.NOT_CONNECTED
    assert not state.search_keys
    assert "identity를 먼저 확인" in state.message


def test_successful_zero_match_wording_never_claims_safe() -> None:
    state = no_match_safety_state(model_name="DFM-100", permit_numbers=["수허 24-1"])

    assert state.status == SafetyCheckStatus.NO_MATCH
    assert state.message == "현재 연결된 공식 안전정보에서 일치 항목을 확인하지 못함"
    assert "안전함" not in state.message
    assert "문제없" not in state.message


def test_safety_supplier_page_loads_without_live_api_calls() -> None:
    root = Path(__file__).resolve().parents[1]
    app = AppTest.from_file(root / "pages" / "5_의료기기_안전_공급사.py")

    app.run(timeout=10)

    assert not app.exception
    assert app.title[0].value == "의료기기 안전·공급사 확인"
    assert any("현재 회수·판매중지 API" in item.value for item in app.caption)

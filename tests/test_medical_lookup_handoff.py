from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from purchase_price.services import medical_lookup_handoff as h


def _identity(permit="수허 15-1338 호", model="Efficia DFM100"):
    return SimpleNamespace(
        product_name="저출력 심장 충격기",
        model_name=model,
        registered_company="태바스라이프사이언스코리아 유한회사",
        permit_number=permit,
        udi_di="08806000000001",
    )


def test_identity_index_is_preferred_and_carries_only_identity_fields() -> None:
    handoff = h.build_medical_lookup_handoff(
        identity_records=[_identity(), _identity(permit="수허 15-1338 호"), _identity(permit="수허 9-9 호")],
        model_info_records=[SimpleNamespace(product_name="x", model_name="y", permit_number="z")],
        query_model_name="DFM100",
    )
    state = handoff.to_state()

    assert handoff.source == "식약처 제품정보"
    assert handoff.permit_numbers == ("수허 15-1338 호", "수허 9-9 호")
    assert set(state) == {"product_name", "model_name", "company", "permit_numbers", "udi_di", "source", "token"}


def test_falls_back_to_exact_model_info_then_query() -> None:
    exact = h.build_medical_lookup_handoff(
        model_info_records=[SimpleNamespace(product_name="심장충격기", model_name="NT-381.AI", permit_number="제허 12-1551 호")],
        query_model_name="NT-381.AI",
    )
    query_only = h.build_medical_lookup_handoff(query_model_name="NT-SG")

    assert exact.source == "식약처 형명정보" and exact.permit_numbers == ("제허 12-1551 호",)
    assert query_only.source == "검색어" and query_only.model_name == "NT-SG"
    assert h.build_medical_lookup_handoff().is_empty


def test_apply_fills_widgets_once_per_token_and_keeps_user_edits() -> None:
    state: dict = {h.MEDICAL_LOOKUP_HANDOFF_KEY: h.build_medical_lookup_handoff(identity_records=[_identity()]).to_state()}

    assert h.apply_handoff(state) is not None
    assert state[h.WIDGET_MODEL] == "Efficia DFM100"
    assert state[h.WIDGET_SAFETY_PERMITS] == "수허 15-1338 호"
    assert state[h.WIDGET_SAFETY_COMPANY] == "태바스라이프사이언스코리아 유한회사"
    assert state[h.WIDGET_UDI] == "08806000000001"

    state[h.WIDGET_MODEL] = "사용자가 고친 값"
    h.apply_handoff(state)
    assert state[h.WIDGET_MODEL] == "사용자가 고친 값"

    state[h.MEDICAL_LOOKUP_HANDOFF_KEY] = h.build_medical_lookup_handoff(query_model_name="NT-SG").to_state()
    h.apply_handoff(state)
    assert state[h.WIDGET_MODEL] == "NT-SG"
    assert h.apply_handoff({}) is None


def test_pages_use_the_shared_widget_keys() -> None:
    medical = Path("pages/4_의료기기_조회.py").read_text(encoding="utf-8")
    dashboard = Path("pages/1_대시보드.py").read_text(encoding="utf-8")

    for key in (h.WIDGET_SAFETY_MODEL, h.WIDGET_SAFETY_PERMITS, h.WIDGET_SAFETY_COMPANY):
        assert f'key="{key}"' in medical
    for name in ("WIDGET_PRODUCT", "WIDGET_MODEL", "WIDGET_MANUFACTURER", "WIDGET_UDI"):
        assert f"key={name}" in medical
    assert "apply_handoff(st.session_state)" in medical
    # Once beside the model table, once with 같은 품목 시장, once in the detail section.
    assert dashboard.count("_render_medical_lookup_link(indexed_identity, mfds, query)") == 3
    assert 'label="의료기기 상세 조회 화면 열기"' not in dashboard

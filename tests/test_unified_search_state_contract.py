from pathlib import Path


def test_unified_search_result_survives_streamlit_widget_reruns() -> None:
    source = Path("pages/1_대시보드.py").read_text(encoding="utf-8")

    assert 'HOME_SEARCH_STATE_KEY = "home_unified_search_result"' in source
    assert 'HOME_SEARCH_DETAILS_KEY = "home_search_details"' in source
    assert "st.session_state[HOME_SEARCH_STATE_KEY] = search_state" in source
    assert "search_state = st.session_state.get(HOME_SEARCH_STATE_KEY)" in source
    assert "_render_search_result(search_state)" in source
    assert 'st.tabs(' in source
    assert '"📚 Research·근거"' in source
    assert '"💰 거래가격"' in source
    assert 'id="unified-search-runtime-v3"' in source
    assert 'id="unified-search-runtime-v4"' in source
    assert 'id="purchase-workspace-runtime-v1"' in source
    assert 'id="purchase-workspace-runtime-v2"' in source
    assert 'id="purchase-workspace-mfds-v1"' in source
    assert "research_mfds_for_workspace" in source
    assert "interpret_unified_search" in source
    assert "_render_search_interpretation" in source
    assert "lookup_mfds_identity_from_r2" in source
    assert "lookup_same_mfds_product_from_r2" in source
    assert "허가번호" in source
    assert "동일 품목 → 허가번호 → 모델 → 등록업체 → 나라장터 가격" in source
    assert "direct_transaction_rows" in source
    assert "reference_transaction_rows" in source
    assert "검색 참고거래" in source

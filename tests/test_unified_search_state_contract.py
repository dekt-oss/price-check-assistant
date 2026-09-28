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
    assert 'id="purchase-workspace-mfds-v2"' in source
    assert "research_mfds_for_workspace" in source
    assert "interpret_unified_search" in source
    assert "_render_search_interpretation" in source
    assert "lookup_mfds_identity_from_r2" in source
    assert "lookup_same_mfds_product_from_r2" in source
    assert "get_mfds_identity_collection_status" in source
    assert "_render_mfds_collection_status" in source
    assert "exact_identity_crosslinks" in source
    assert "식약처 품목번호 기준 모델·조달가격 연결" in source
    assert "companies[0]" not in source
    assert "식약처 품목번호" in source
    assert "동일 품목 → 품목 책임주체 → 모델 → 식약처 품목번호 → 나라장터 가격" in source
    assert "_split_transaction_rows_compat" in source
    assert "_strict_candidates_compat" in source
    assert "direct_transaction_rows" not in source
    assert "reference_transaction_rows" not in source
    assert "검색 참고거래" in source
    assert "식약처 등록업체" not in source
    assert "품목 책임주체" in source
    assert "직접 동일성 확인 거래" in source
    assert "적정가격 범위" not in source
    assert "'안전함'" not in source

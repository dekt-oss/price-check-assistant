from pathlib import Path


def test_unified_search_result_survives_streamlit_widget_reruns() -> None:
    source = Path("pages/1_대시보드.py").read_text(encoding="utf-8")

    assert 'HOME_SEARCH_STATE_KEY = "home_unified_search_result"' in source
    assert 'HOME_SEARCH_DETAILS_KEY = "home_search_details"' in source
    assert "st.session_state[HOME_SEARCH_STATE_KEY] = search_state" in source
    assert "search_state = st.session_state.get(HOME_SEARCH_STATE_KEY)" in source
    assert "_render_search_result(search_state)" in source
    assert 'st.toggle("상세 조사·근거 보기"' in source
    assert 'st.markdown("#### 상세 조사·근거")' in source
    assert 'id="unified-search-runtime-v3"' in source
    assert 'id="unified-search-runtime-v4"' in source
    assert "interpret_unified_search" in source
    assert "_render_search_interpretation" in source

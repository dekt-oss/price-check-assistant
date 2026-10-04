from pathlib import Path


def test_unified_search_result_survives_streamlit_widget_reruns() -> None:
    source = Path("pages/1_대시보드.py").read_text(encoding="utf-8")

    assert 'HOME_SEARCH_STATE_KEY = "home_unified_search_result"' in source
    assert 'HOME_SEARCH_DETAILS_KEY = "home_search_details"' in source
    assert "st.session_state[HOME_SEARCH_STATE_KEY] = search_state" in source
    assert "search_state = st.session_state.get(HOME_SEARCH_STATE_KEY)" in source
    assert "_render_search_result(search_state)" in source
    assert "st.tabs(" not in source
    assert "st.segmented_control(" in source
    assert "workspace_quote_context::" in source
    assert '"내 견적가"' in source
    assert '"단위"' in source
    assert '"VAT"' in source
    assert '"설치·운송 등 조건"' in source
    assert "build_quote_position_message" in source
    assert "MFDS_PRODUCT_INFO_DATASET_URL" in source
    assert '"route": "candidate_selection"' in source
    assert "_render_identity_candidate_selection" in source
    assert "_candidate_identity_records" in source
    assert '"조사할 제품 identity 선택"' in source
    assert '"선택한 identity로 구매조사"' in source
    assert "selected_identity=selected" in source
    assert 'manufacturer=""' in source
    assert "_ambiguous_identity_candidates" in source
    assert "IdentityEvidenceStatus.AMBIGUOUS" in source
    assert "동일 모델명이 여러 식약처 품목번호" in source
    assert "후보 선택 전에는 나라장터 직접가격을 특정 제품의 가격으로 연결하지 않습니다." in source
    assert '"원문근거해시"' in source
    assert '"💰 가격 비교"' in source
    assert '"🏢 업체·조달"' in source
    assert '"🔁 동일품목 비교"' in source
    assert '"📚 Research·근거"' not in source
    assert "build_market_survey_workbook" in source
    assert "시장조사표 Excel 내려받기" in source
    assert '"track_b_data_as_of"' in source
    assert 'data_as_of=track_b_data_as_of' in source
    assert "나라장터 직접가격 데이터 기준일" in source
    assert "전체 데이터 coverage 기준일은 아직 미확인" in source
    assert "build_manual_safety_check_state" in source
    assert 'st.markdown("### Safety")' in source
    assert "MFDS_RECALL_PAGE_URL" in source
    assert "MFDS_ADMIN_SANCTION_PAGE_URL" in source
    assert "MFDS_SAFETY_LETTER_PAGE_URL" in source
    assert "공식 안전정보 확인키" in source
    assert "priced_active_crosslinks" in source
    assert '"현재 모델"' in source
    assert "최대 25개" not in source
    assert 'id="unified-search-runtime-v3"' in source
    assert 'id="unified-search-runtime-v4"' in source
    assert 'id="purchase-workspace-runtime-v1"' in source
    assert 'id="purchase-workspace-runtime-v2"' in source
    assert 'id="purchase-workspace-mfds-v1"' in source
    assert 'id="purchase-workspace-mfds-v2"' in source
    assert 'id="purchase-workspace-v3-shell"' in source
    assert 'st.query_params["q"]' in source
    assert 'st.query_params["view"]' in source
    assert 'st.query_params["identity"]' in source
    assert "_identity_selection_token" in source
    assert "_selected_identity_from_token" in source
    assert "selected_identity_token=str(st.query_params.get(\"identity\") or \"\")" in source
    assert 'st.query_params.pop("identity", None)' in source
    assert "공유된 검색조건을 복원하고 있습니다" in source
    assert "home_unified_search_compact" in source
    assert "research_mfds_for_workspace" in source
    assert "interpret_unified_search" in source
    assert "_render_search_interpretation" in source
    assert "lookup_mfds_identity_from_r2" in source
    assert "lookup_same_mfds_product_from_r2" in source
    assert "get_mfds_identity_collection_status" in source
    assert "_render_mfds_collection_status" in source
    assert "exact_identity_crosslinks" in source
    assert "track_b_snapshot.lookup_model_summaries(queries)" in source
    assert "for item in list(unique.values())[:limit]" not in source
    assert "track_b_snapshot=track_b_snapshot,\n            limit=25" not in source
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
    for prohibited in ("미등록", "거래 없음", "안전함", "이상 없음", "공식 공급처"):
        assert prohibited not in source

from __future__ import annotations

import csv
import runpy
from pathlib import Path

import pandas as pd
import streamlit as st
from streamlit.runtime.scriptrunner_utils.exceptions import StopException

from purchase_price.ui.mapping_requests import DEFAULT_MAPPING_REQUESTS_PATH

st.set_page_config(page_title="관리", page_icon="🛠️", layout="wide")
st.title("관리")
st.caption(
    "운영환경·견적추출 UAT·Phase0·공개가격 수집상태·식별 조사요청을 한 화면에서 관리합니다."
)

PAGES_DIR = Path(__file__).resolve().parent


def _render_legacy_admin(filename: str) -> None:
    """Render an existing admin page inside the current tab without adding it to navigation."""
    original_set_page_config = st.set_page_config
    st.set_page_config = lambda *args, **kwargs: None  # type: ignore[method-assign]
    try:
        try:
            runpy.run_path(str(PAGES_DIR / filename), run_name=f"__admin_{filename}__")
        except StopException:
            pass
    finally:
        st.set_page_config = original_set_page_config  # type: ignore[method-assign]


env_tab, uat_tab, phase_tab, collection_tab, registry_tab = st.tabs(
    ["운영환경", "견적추출 UAT", "Phase 0", "수집상태", "근거·조사 레지스트리"]
)

with env_tab:
    _render_legacy_admin("14_운영환경_진단.py")

with uat_tab:
    st.warning(
        "이 탭은 기존 UAT 화면을 그대로 이동한 것입니다. 알려진 release-gate strategy key 불일치는 "
        "R6에서 임의 수정하지 않습니다."
    )
    _render_legacy_admin("13_견적추출_UAT.py")

with phase_tab:
    _render_legacy_admin("3_Phase0_검증.py")

with collection_tab:
    _render_legacy_admin("8_공개가격_수집상태.py")

with registry_tab:
    st.markdown("### 제품 식별 조사요청")
    st.caption(
        "verified G2B mapping이 없어 S3에서 등록한 identity-only 요청입니다. "
        "견적가격·수량·상업조건·원문·업로드 파일명은 기록하지 않습니다."
    )
    if not DEFAULT_MAPPING_REQUESTS_PATH.exists():
        st.info("등록된 mapping 조사요청이 없습니다.")
    else:
        with DEFAULT_MAPPING_REQUESTS_PATH.open(
            "r", encoding="utf-8-sig", newline=""
        ) as handle:
            rows = list(csv.DictReader(handle))
        if rows:
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
            st.caption(f"현재 조사요청 {len(rows)}건")
        else:
            st.info("등록된 mapping 조사요청이 없습니다.")

    st.markdown("### 운영 원칙")
    st.markdown(
        """
- 조사요청은 **제품 identity 정비 큐**이며 가격판정 근거가 아닙니다.
- mapping을 추가할 때는 공식 세부품명/코드 근거를 별도로 검증합니다.
- 미검증 후보의 표시가격을 직접가격으로 승격하지 않습니다.
- 실제 병원 견적 원문이나 업체별 비공개 조건을 저장소 레지스트리에 넣지 않습니다.
"""
    )

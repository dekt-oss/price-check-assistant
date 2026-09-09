from __future__ import annotations

import os

import streamlit as st


def _truthy(value: object) -> bool:
    return str(value or "").strip().casefold() in {"1", "true", "yes", "y", "on"}


def _admin_mode() -> bool:
    value: object = os.getenv("ADMIN_MODE", "")
    try:
        secret_value = st.secrets.get("ADMIN_MODE")
    except (FileNotFoundError, KeyError):
        secret_value = None
    if secret_value is not None:
        value = secret_value
    return _truthy(value)


business_pages = [
    st.Page("pages/1_대시보드.py", title="대시보드", icon="🏠", default=True),
    st.Page("pages/2_견적_검토.py", title="견적 검토", icon="📋"),
    st.Page("pages/3_빠른_검색.py", title="빠른 검색", icon="🔎"),
    st.Page("pages/4_의료기기_조회.py", title="의료기기 조회", icon="🏥"),
]

validation_pages = [
    st.Page(
        "pages/13_견적추출_UAT.py",
        title="견적추출 UAT",
        icon="🧪",
        url_path="quote-extraction-uat",
    )
]

navigation: dict[str, list[st.Page]] = {
    "업무": business_pages,
    "검증": validation_pages,
}
if _admin_mode():
    navigation["관리"] = [st.Page("pages/9_관리.py", title="관리", icon="🛠️")]

page = st.navigation(navigation, position="sidebar", expanded=True)
page.run()

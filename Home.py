from __future__ import annotations

import os

import streamlit as st

from purchase_price.config import Settings
from purchase_price.ui.runtime_secrets import hydrate_streamlit_runtime_secrets

hydrate_streamlit_runtime_secrets()


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


def _render_r2_runtime_diagnostic() -> None:
    if str(st.query_params.get("_r2diag", "")).strip() != "1":
        return
    from purchase_price.ui.r2_runtime_diagnostic import diagnose_track_b_r2_runtime

    diagnostic = diagnose_track_b_r2_runtime()
    detail = f" missing={diagnostic.detail}" if diagnostic.detail else ""
    st.caption(f"R2_RUNTIME_DIAGNOSTIC code={diagnostic.code}{detail}")


def _render_runtime_readiness_notice() -> None:
    if Settings().r2_configured:
        return
    st.warning(
        "나라장터 거래가격 인덱스 연결 설정이 없어 현재 거래가격 DB를 사용할 수 없습니다. "
        "공개 Research 결과는 계속 확인할 수 있지만, 거래가격 기반 비교·건수·가격범위는 운영 설정 복구 전까지 제한됩니다."
    )


_render_r2_runtime_diagnostic()
_render_runtime_readiness_notice()

# The sidebar lists only what the purchasing team uses. Every other page stays registered so
# links (st.page_link / st.switch_page) and the production smoke URLs keep working.
price_page = st.Page("pages/1_대시보드.py", title="가격 조사", icon="🔎", default=True)
# The integrated home lives at /home so the root URL keeps opening the price search that the
# production smokes and purchasing-team bookmarks expect.
home_page = st.Page("pages/0_홈.py", title="홈", icon="🏠", url_path="home")
news_page = st.Page(
    "pages/20_병원_News_Radar.py", title="병원 News Radar", icon="📰", url_path="news-radar"
)
benchmark_page = st.Page(
    "pages/21_병원_경영_Benchmark.py",
    title="병원 경영 Benchmark",
    icon="📈",
    url_path="hospital-benchmark",
)
medical_page = st.Page("pages/4_의료기기_조회.py", title="의료기기 상세", icon="🏥")
quote_detail_page = st.Page("pages/2_견적_검토.py", title="견적 상세 검증", icon="📋")
legacy_search_page = st.Page("pages/3_빠른_검색.py", title="상세 검색(이전 화면)", icon="🧭")
validation_pages = [
    st.Page(
        "pages/13_견적추출_UAT.py",
        title="견적추출 UAT",
        icon="🧪",
        url_path="quote-extraction-uat",
    ),
    st.Page(
        "pages/15_전체구매검토_UAT.py",
        title="전체 구매검토 UAT",
        icon="📊",
        url_path="purchase-review-uat",
    ),
]
admin_pages: list[st.Page] = []
if _admin_mode():
    admin_pages = [st.Page("pages/9_관리.py", title="관리", icon="🛠️")]

page = st.navigation(
    [
        price_page,
        home_page,
        news_page,
        benchmark_page,
        medical_page,
        quote_detail_page,
        legacy_search_page,
        *validation_pages,
        *admin_pages,
    ],
    position="hidden",
)

with st.sidebar:
    st.page_link(home_page, label="홈", icon="🏠")
    st.page_link(price_page, label="구매가격 조사", icon="🔎")
    st.page_link(news_page, label="병원 News Radar", icon="📰")
    st.page_link(benchmark_page, label="병원 경영 Benchmark", icon="📈")
    st.page_link(medical_page, label="의료기기 상세", icon="🏥")
    if admin_pages:
        st.divider()
        st.caption("관리 · 검증")
        for admin_link in (*admin_pages, *validation_pages, quote_detail_page, legacy_search_page):
            st.page_link(admin_link)

page.run()

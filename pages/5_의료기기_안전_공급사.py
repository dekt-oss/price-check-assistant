from __future__ import annotations

import pandas as pd
import streamlit as st

from purchase_price.clients.data_go_kr import PublicDataClientError
from purchase_price.collectors.registry import build_collectors
from purchase_price.config import get_settings
from purchase_price.schemas import ProductQuery
from purchase_price.services.market_research_support import (
    build_web_supplier_search_links,
    extract_g2b_supplier_candidates,
    extract_mfds_business_supplier_candidates,
)
from purchase_price.services.mfds_device_intelligence import (
    MFDS_BUSINESS_LICENSE_BASE_URL,
    MFDS_MODEL_INFO_BASE_URL,
    MfdsBusinessLicenseClient,
    MfdsModelInfoClient,
    resolve_exact_model_identity,
)
from purchase_price.services.safety_support import (
    MFDS_ADMIN_SANCTION_PAGE_URL,
    MFDS_RECALL_DATASET_URL,
    MFDS_RECALL_PAGE_URL,
    MFDS_SAFETY_LETTER_PAGE_URL,
    MFDS_STANDARD_CODE_DATASET_URL,
    MFDS_UDI_PORTAL_URL,
    build_manual_safety_check_state,
)
from purchase_price.services.search import search_all

st.set_page_config(page_title="의료기기 안전·공급사", page_icon="🛡️", layout="wide")
st.title("의료기기 안전·공급사 확인")
st.caption(
    "식약처 exact identity, 나라장터 실제 납품업체, 식약처 업허가 업체와 공식 안전정보 확인 경로를 "
    "한 화면에서 검토합니다. 현재 회수·판매중지 API는 request contract 확인 전까지 자동조회하지 않습니다."
)

settings = get_settings()
mfds_service_key = (settings.resolved_mfds_service_key or "").strip()
g2b_service_key = (settings.resolved_g2b_service_key or "").strip()

c1, c2 = st.columns(2)
c1.caption("식약처 API: " + ("설정됨" if mfds_service_key else "미설정"))
c2.caption("나라장터 API: " + ("설정됨" if g2b_service_key else "미설정"))

with st.expander("이 화면에서 확인하는 근거의 우선순위", expanded=False):
    st.markdown(
        """
1. **나라장터 실제 공개 납품업체** — verified exact-model 근거가 있을 때만 자동 연결
2. **식약처 의료기기 업허가 업체** — 제조·수입·판매 등 업허가 확인 근거이며 특정 모델의 공식 총판을 의미하지 않음
3. **웹 공급사 후보** — 보조 탐색이며 반드시 별도 공식 근거 확인 필요

Safety는 별도 축입니다. 회수·판매중지/행정처분/안전성서한은 가격이 싸더라도 우선 확인해야 하며,
현재 자동 API가 미연결인 상태를 `안전`으로 해석하지 않습니다.
        """
    )

with st.form("device-safety-supplier-review"):
    c1, c2 = st.columns(2)
    with c1:
        product_name = st.text_input("식약처 품목명", placeholder="예: 심장충격기")
        model_name = st.text_input("모델명", placeholder="예: Efficia DFM100")
    with c2:
        permit_number = st.text_input("품목허가번호 (선택)", placeholder="식약처 확인값이 있으면 입력")
        company_name = st.text_input(
            "확인할 제조·수입·공급업체명 (선택)", placeholder="예: ○○메디칼"
        )
    g2b_lookback_days = st.selectbox(
        "나라장터 공급실적 검색기간",
        options=[30, 90, 180, 365],
        index=1,
        format_func=lambda days: f"최근 {days}일",
        disabled=not bool(g2b_service_key),
    )
    submitted = st.form_submit_button("안전·공급사 확인", type="primary")

if submitted:
    if not any(
        value.strip() for value in (product_name, model_name, permit_number, company_name)
    ):
        st.warning("품목명·모델명·허가번호·업체명 중 하나 이상 입력하세요.")
        st.stop()

    exact_matches = ()
    active_exact_matches = ()
    exact_ambiguous = False
    model_lookup_succeeded = False
    permit_numbers: list[str] = []
    if permit_number.strip():
        permit_numbers.append(permit_number.strip())

    st.subheader("1. 공식 identity 및 공급사 근거")

    if product_name.strip() and mfds_service_key:
        model_client = MfdsModelInfoClient(
            mfds_service_key,
            base_url=settings.mfds_model_info_base_url or MFDS_MODEL_INFO_BASE_URL,
            timeout_seconds=settings.mfds_request_timeout_seconds,
            max_retries=settings.mfds_max_retries,
        )
        try:
            models = model_client.search_models(product_name.strip())
            model_lookup_succeeded = True
        except (PublicDataClientError, ValueError) as exc:
            st.error(f"식약처 형명정보 조회 실패: {exc}")
            models = ()

        if model_lookup_succeeded and model_name.strip():
            identity = resolve_exact_model_identity(models, model_name.strip())
            exact_matches = identity.exact_matches
            active_exact_matches = tuple(
                item for item in exact_matches if item.active_for_domestic_candidate
            )
            exact_ambiguous = identity.ambiguous
            permit_numbers.extend(
                item.permit_number for item in exact_matches if item.permit_number
            )

            if exact_matches:
                identity_rows = [
                    {
                        "품목명": item.product_name or "",
                        "모델/형명": item.model_name or "",
                        "상품명": item.trade_name or "",
                        "허가번호": item.permit_number or "",
                        "허가구분": item.permission_type or "",
                        "현재 국내후보": "예" if item.active_for_domestic_candidate else "아니오",
                    }
                    for item in exact_matches
                ]
                st.dataframe(pd.DataFrame(identity_rows), use_container_width=True, hide_index=True)
                if exact_ambiguous:
                    st.warning(
                        "동일 exact 모델이 둘 이상의 품목허가번호에 연결되어 자동 교차연결을 보류합니다."
                    )
                elif active_exact_matches:
                    st.success("식약처 동일 품목 결과 안에서 입력 모델의 exact identity를 확인했습니다.")
                else:
                    st.error(
                        "exact 등록은 확인됐지만 취소·취하 또는 수출전용으로 분류되어 국내 신규구매 "
                        "후보로 자동 사용하지 않습니다."
                    )
            else:
                st.warning(
                    "식약처 품목 조회는 완료됐지만 입력 모델과 exact로 일치하는 형명을 찾지 못했습니다."
                )
        elif model_lookup_succeeded:
            st.info(
                f"식약처 동일 품목 등록 {len(models)}건을 확인했습니다. 모델명을 입력하면 exact identity를 추가 확인합니다."
            )
    elif product_name.strip():
        st.warning("식약처 서비스키가 없어 공식 품목/모델 자동조회는 실행하지 못했습니다.")

    g2b_suppliers = ()
    identity_ready_for_g2b = bool(
        model_lookup_succeeded
        and exact_matches
        and active_exact_matches
        and not exact_ambiguous
        and model_name.strip()
    )
    if g2b_service_key and identity_ready_for_g2b:
        run = search_all(
            ProductQuery(product_name=product_name.strip(), model_name=model_name.strip()),
            build_collectors(g2b_lookback_days=int(g2b_lookback_days)),
        )
        if run.errors:
            st.warning("나라장터 조회 중 일부 오류: " + " / ".join(run.errors))
        g2b_suppliers = extract_g2b_supplier_candidates(run.results)

    businesses = ()
    mfds_suppliers = ()
    if company_name.strip() and mfds_service_key:
        business_client = MfdsBusinessLicenseClient(
            mfds_service_key,
            base_url=settings.mfds_business_license_base_url or MFDS_BUSINESS_LICENSE_BASE_URL,
            timeout_seconds=settings.mfds_request_timeout_seconds,
            max_retries=settings.mfds_max_retries,
        )
        try:
            businesses = business_client.search_company(company_name.strip())
        except (PublicDataClientError, ValueError) as exc:
            st.error(f"식약처 업체 업허가 조회 실패: {exc}")
        mfds_suppliers = extract_mfds_business_supplier_candidates(businesses)

    st.markdown("#### 공급사 근거 우선순위")
    if g2b_suppliers:
        st.markdown("**① 나라장터 · 실제 공개 납품업체**")
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "업체명": item.name,
                        "출처": item.source.value,
                        "근거": item.evidence,
                    }
                    for item in g2b_suppliers
                ]
            ),
            use_container_width=True,
            hide_index=True,
        )
    elif g2b_service_key and model_name.strip():
        if identity_ready_for_g2b:
            st.info("현재 verified 나라장터 공급실적에서 실제 납품업체 근거를 확인하지 못했습니다.")
        else:
            st.info("나라장터 공급업체 자동연결은 식약처 active exact identity가 단일하게 확인될 때만 실행합니다.")

    if mfds_suppliers:
        st.markdown("**② 식약처 · 의료기기 업허가 업체**")
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "업체명": item.name,
                        "출처": item.source.value,
                        "근거": item.evidence,
                    }
                    for item in mfds_suppliers
                ]
            ),
            use_container_width=True,
            hide_index=True,
        )
    elif company_name.strip() and mfds_service_key:
        st.info("식약처 조회는 실행했지만 현재 사용 가능한 업허가 업체 근거를 확인하지 못했습니다.")

    st.markdown("**③ 웹 · 보조 공급사 탐색**")
    web_links = build_web_supplier_search_links(product_name, model_name)
    if web_links:
        cols = st.columns(len(web_links))
        for col, (label, url) in zip(cols, web_links, strict=False):
            col.link_button(label, url, use_container_width=True)
    else:
        st.caption("품목명 또는 모델명을 입력하면 보조 웹 탐색 링크를 표시합니다.")

    st.divider()
    st.subheader("2. 의료기기 Safety")
    safety_state = build_manual_safety_check_state(
        model_name=model_name.strip(),
        permit_numbers=permit_numbers,
    )
    st.warning(f"{safety_state.status.value} · {safety_state.message}")

    if safety_state.search_keys:
        st.markdown("**공식 안전정보 확인 키**")
        for key in safety_state.search_keys:
            st.code(key, language=None)

    safety_cols = st.columns(3)
    safety_cols[0].link_button(
        "식약처 회수·판매중지",
        MFDS_RECALL_PAGE_URL,
        use_container_width=True,
    )
    safety_cols[1].link_button(
        "식약처 행정처분",
        MFDS_ADMIN_SANCTION_PAGE_URL,
        use_container_width=True,
    )
    safety_cols[2].link_button(
        "식약처 안전성서한",
        MFDS_SAFETY_LETTER_PAGE_URL,
        use_container_width=True,
    )
    st.link_button(
        "공공데이터포털 · 의료기기 회수·판매중지정보 API",
        MFDS_RECALL_DATASET_URL,
    )
    st.caption(
        "자동 API 조회 결과가 아닌 공식 페이지 수동 확인 경로입니다. 회수·판매중지 exact hit가 "
        "자동으로 연결되기 전까지 `확인되지 않음`을 `안전`으로 바꾸지 않습니다."
    )

    st.divider()
    st.subheader("3. UDI·표준코드 identity 확장")
    st.info(
        "식약처 표준코드별 제품정보 API는 UDI-DI, 품목명·분류번호·등급·허가번호·모델명·제품명·"
        "제조/수입업체 등을 제공하는 공식 source입니다. 현재는 request filter 계약과 활용권한을 "
        "완전히 검증하기 전이라 자동 모델검색에 연결하지 않았습니다."
    )
    c1, c2 = st.columns(2)
    c1.link_button(
        "식약처 UDI 시스템에서 확인",
        MFDS_UDI_PORTAL_URL,
        use_container_width=True,
    )
    c2.link_button(
        "표준코드별 제품정보 API 명세",
        MFDS_STANDARD_CODE_DATASET_URL,
        use_container_width=True,
    )
else:
    st.info(
        "품목명·모델명·허가번호·업체명을 입력하면 현재 연결된 공식 근거와 Safety 확인 경로를 표시합니다."
    )

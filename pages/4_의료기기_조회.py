import pandas as pd
import streamlit as st

from purchase_price.clients.data_go_kr import PublicDataClientError
from purchase_price.collectors.registry import build_collectors
from purchase_price.config import get_settings
from purchase_price.schemas import ProductQuery
from purchase_price.services.market_research_support import (
    alternative_research_gate,
    build_alternative_web_search_links,
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
from purchase_price.services.mfds_udi import MFDS_UDI_CODE_BASE_URL, MfdsUdiCodeClient
from purchase_price.services.safety_support import (
    MFDS_ADMIN_SANCTION_PAGE_URL,
    MFDS_RECALL_PAGE_URL,
    MFDS_SAFETY_LETTER_PAGE_URL,
    MFDS_UDI_PORTAL_URL,
    build_manual_safety_check_state,
)
from purchase_price.services.search import search_all
from purchase_price.ui.widgets import render_evidence_table, render_source_status

st.set_page_config(page_title="의료기기 조회", page_icon="🏥", layout="wide")
st.title("의료기기 조회")
st.caption(
    "식약처 등록모델 → 공개 공급근거 → Safety·업허가 → UDI-DI를 한 업무 영역에서 확인합니다. "
    "공식 identity와 공급관계를 추정으로 승격하지 않습니다."
)

settings = get_settings()
mfds_key = (settings.resolved_mfds_service_key or "").strip()
g2b_key = (settings.resolved_g2b_service_key or "").strip()
st.caption(
    "API 연결 · 식약처: " + ("설정됨" if mfds_key else "미설정") + " · 나라장터: " + (
        "설정됨" if g2b_key else "미설정"
    )
)

market_tab, safety_tab, udi_tab = st.tabs(["등록·시장조사", "Safety·공급사", "UDI-DI"])

with market_tab:
    st.markdown("### 식약처 등록모델과 공개 공급근거")
    st.caption(
        "식약처 공식 품목명으로 조회하고, 모델명을 입력한 경우 결과 안에서 exact-normalized 모델만 identity로 확인합니다."
    )
    if not mfds_key:
        st.warning("MFDS 서비스키가 없어 식약처 live 조회가 비활성화되어 있습니다.")

    with st.form("medical-market-search"):
        c1, c2 = st.columns(2)
        product_name = c1.text_input("식약처 품목명", placeholder="예: 심장충격기")
        model_name = c2.text_input("모델명 (선택)", placeholder="예: Efficia DFM100")
        manufacturer = c1.text_input("제조사/업체명 (선택)")
        specification = c2.text_input("규격 (선택)")
        intended_use = c1.text_input("사용목적 (동일품목 국내후보 0건일 때만 보조탐색에 사용)")
        search_submitted = st.form_submit_button(
            "등록·시장근거 조회", type="primary", disabled=not bool(mfds_key)
        )

    if search_submitted:
        if not product_name.strip():
            st.warning("식약처 품목명을 입력하세요.")
        else:
            model_client = MfdsModelInfoClient(
                mfds_key,
                base_url=settings.mfds_model_info_base_url or MFDS_MODEL_INFO_BASE_URL,
                timeout_seconds=settings.mfds_request_timeout_seconds,
                max_retries=settings.mfds_max_retries,
            )
            try:
                records = model_client.search_models(product_name.strip())
            except (PublicDataClientError, ValueError) as exc:
                st.error(f"식약처 등록모델 조회 실패: {exc}")
            else:
                active = [item for item in records if item.active_for_domestic_candidate]
                st.success(f"식약처 등록 {len(records)}건 · 국내 정상 후보 {len(active)}건")
                if records:
                    st.dataframe(
                        pd.DataFrame(
                            [
                                {
                                    "품목명": item.product_name or "",
                                    "모델명": item.model_name or "",
                                    "허가번호": item.permit_number or "",
                                    "업체": item.industry_name or "",
                                    "허가일": item.permit_date.isoformat() if item.permit_date else "",
                                    "수출전용": item.export_only,
                                    "취소상태": item.cancellation_status or "",
                                }
                                for item in records
                            ]
                        ),
                        use_container_width=True,
                        hide_index=True,
                    )

                exact = resolve_exact_model_identity(records, model_name) if model_name.strip() else None
                exact_ready = bool(exact and exact.confirmed and not exact.ambiguous)
                if exact is not None:
                    if exact.ambiguous:
                        st.error("동일 모델명이 복수 허가번호에 걸려 자동 identity로 확정하지 않습니다.")
                    elif exact.confirmed:
                        permits = ", ".join(
                            item.permit_number or "허가번호 미표기" for item in exact.exact_matches
                        )
                        st.success(f"MFDS exact 모델 확인 · {permits}")
                    else:
                        st.warning("품목 조회 결과 안에서 exact 모델을 확인하지 못했습니다.")

                supplier_rows: list[dict[str, str]] = []
                if manufacturer.strip():
                    business_client = MfdsBusinessLicenseClient(
                        mfds_key,
                        base_url=(
                            settings.mfds_business_license_base_url
                            or MFDS_BUSINESS_LICENSE_BASE_URL
                        ),
                        timeout_seconds=settings.mfds_request_timeout_seconds,
                        max_retries=settings.mfds_max_retries,
                    )
                    try:
                        businesses = business_client.search_company(manufacturer.strip())
                    except (PublicDataClientError, ValueError) as exc:
                        st.warning(f"식약처 업체 업허가 조회 실패: {exc}")
                        businesses = ()
                    for candidate in extract_mfds_business_supplier_candidates(businesses):
                        supplier_rows.append(
                            {
                                "업체": candidate.name,
                                "출처": candidate.source.value,
                                "근거": candidate.evidence,
                            }
                        )

                if exact_ready and g2b_key:
                    query = ProductQuery(
                        product_name=product_name.strip(),
                        manufacturer=manufacturer.strip(),
                        model_name=model_name.strip(),
                        specification=specification.strip(),
                    )
                    run = search_all(query, build_collectors())
                    st.markdown("#### 공개 가격·납품 근거")
                    render_source_status(run)
                    if run.results:
                        render_evidence_table(run.results)
                        for candidate in extract_g2b_supplier_candidates(run.results):
                            supplier_rows.append(
                                {
                                    "업체": candidate.name,
                                    "출처": candidate.source.value,
                                    "근거": candidate.evidence,
                                }
                            )
                    else:
                        st.info("exact identity 이후에도 검증된 공개 납품·가격근거가 0건입니다.")
                elif model_name.strip() and not exact_ready:
                    st.info("MFDS exact identity가 확인되지 않아 나라장터와 자동 교차조회하지 않습니다.")

                if supplier_rows:
                    st.markdown("#### 공급사 근거")
                    st.dataframe(pd.DataFrame(supplier_rows), use_container_width=True, hide_index=True)
                    st.caption(
                        "식약처 업허가는 의료기기 영업 자격 근거이며 특정 모델의 공식 총판·대리점 관계를 의미하지 않습니다."
                    )

                gate = alternative_research_gate(len(active))
                st.info(gate.message)
                if gate.enabled:
                    for label, url in build_alternative_web_search_links(
                        product_name=product_name,
                        intended_use=intended_use,
                        key_specification=specification,
                    ):
                        st.link_button(label, url)
                for label, url in build_web_supplier_search_links(product_name, model_name):
                    st.link_button(label, url)

with safety_tab:
    st.markdown("### Safety·업허가 확인")
    st.caption(
        "회수·판매중지 자동 API 미연결 상태를 '안전'으로 해석하지 않습니다. exact 모델/허가번호를 공식 확인 키로 유지합니다."
    )
    c1, c2 = st.columns(2)
    safety_model = c1.text_input("확인할 exact 모델명", key="medical_safety_model")
    permit_text = c2.text_input(
        "허가번호 (여러 개면 쉼표 구분)", key="medical_safety_permits"
    )
    safety_state = build_manual_safety_check_state(
        model_name=safety_model,
        permit_numbers=[part.strip() for part in permit_text.split(",") if part.strip()],
    )
    if safety_state.search_keys:
        st.warning(safety_state.message)
        for key in safety_state.search_keys:
            st.write(f"- {key}")
    else:
        st.info(safety_state.message)

    c1, c2, c3 = st.columns(3)
    c1.link_button("식약처 회수·판매중지", MFDS_RECALL_PAGE_URL, use_container_width=True)
    c2.link_button("식약처 행정처분", MFDS_ADMIN_SANCTION_PAGE_URL, use_container_width=True)
    c3.link_button("식약처 안전성서한", MFDS_SAFETY_LETTER_PAGE_URL, use_container_width=True)

    st.markdown("#### 업체 업허가 조회")
    safety_company = st.text_input("업체명", key="medical_safety_company")
    if st.button("식약처 업체 업허가 확인", disabled=not bool(mfds_key)):
        if not safety_company.strip():
            st.warning("업체명을 입력하세요.")
        else:
            client = MfdsBusinessLicenseClient(
                mfds_key,
                base_url=settings.mfds_business_license_base_url or MFDS_BUSINESS_LICENSE_BASE_URL,
                timeout_seconds=settings.mfds_request_timeout_seconds,
                max_retries=settings.mfds_max_retries,
            )
            try:
                businesses = client.search_company(safety_company.strip())
            except (PublicDataClientError, ValueError) as exc:
                st.error(f"업허가 조회 실패: {exc}")
            else:
                st.dataframe(
                    pd.DataFrame(
                        [
                            {
                                "업체": item.company_name or "",
                                "업종": item.industry_type or "",
                                "상태": item.business_status or "",
                                "허가번호": item.business_permit_number or "",
                                "주소": item.address or "",
                                "현재사용가능": item.is_active,
                            }
                            for item in businesses
                        ]
                    ),
                    use_container_width=True,
                    hide_index=True,
                )

with udi_tab:
    st.markdown("### UDI-DI 공식조회")
    st.caption(
        "공식 API는 알고 있는 UDI-DI의 exact forward lookup입니다. 모델명에서 UDI를 역추정하지 않습니다."
    )
    if not mfds_key:
        st.warning("MFDS 서비스키가 없어 UDI live 조회가 비활성화되어 있습니다.")
    with st.form("medical-udi-search"):
        udi_di = st.text_input("UDI-DI", placeholder="알고 있는 UDI-DI를 입력하세요")
        udi_submitted = st.form_submit_button("UDI-DI 조회", disabled=not bool(mfds_key))
    if udi_submitted:
        if not udi_di.strip():
            st.warning("UDI-DI를 입력하세요.")
        else:
            client = MfdsUdiCodeClient(
                mfds_key,
                base_url=settings.mfds_udi_code_base_url or MFDS_UDI_CODE_BASE_URL,
                timeout_seconds=settings.mfds_request_timeout_seconds,
                max_retries=settings.mfds_max_retries,
            )
            try:
                records = client.lookup_udi(udi_di.strip())
            except (PublicDataClientError, ValueError) as exc:
                st.error(f"UDI-DI 조회 실패: {exc}")
            else:
                if not records:
                    st.info("공식 API는 정상 응답했지만 exact UDI-DI 일치 항목이 0건입니다.")
                else:
                    st.dataframe(
                        pd.DataFrame(
                            [
                                {
                                    "UDI-DI": item.udi_di or "",
                                    "코드체계": item.code_system_name or "",
                                    "코드구조": item.code_structure_code or "",
                                    "업체": item.company_name or "",
                                    "업체구분": item.company_type or "",
                                }
                                for item in records
                            ]
                        ),
                        use_container_width=True,
                        hide_index=True,
                    )
    st.link_button("식약처 UDI 포털", MFDS_UDI_PORTAL_URL)

from __future__ import annotations

import pandas as pd
import streamlit as st

from purchase_price.clients.data_go_kr import PublicDataClientError
from purchase_price.collectors.registry import build_collectors
from purchase_price.config import get_settings
from purchase_price.schemas import ProductQuery
from purchase_price.services.device_research_handoff import (
    DEVICE_RESEARCH_HANDOFF_SESSION_KEY,
    parse_device_research_prefill,
)
from purchase_price.services.market_research_support import (
    alternative_research_gate,
    build_alternative_web_search_links,
    build_web_supplier_search_links,
    extract_g2b_supplier_candidates,
)
from purchase_price.services.mfds_device_intelligence import (
    MFDS_BUSINESS_LICENSE_BASE_URL,
    MFDS_MODEL_INFO_BASE_URL,
    MfdsBusinessLicenseClient,
    MfdsModelInfoClient,
    resolve_exact_model_identity,
)
from purchase_price.services.search import search_all

st.set_page_config(page_title="의료기기 시장조사", page_icon="🏥", layout="wide")
st.title("의료기기 시장조사")
st.caption(
    "식약처 등록정보와 나라장터 공개 납품근거를 우선해 경쟁장비·공급사 후보를 조사합니다. "
    "웹 검색은 보조 근거로만 명확히 구분합니다."
)

settings = get_settings()
mfds_service_key = (settings.resolved_mfds_service_key or "").strip()
g2b_service_key = (settings.resolved_g2b_service_key or "").strip()

quote_prefill = parse_device_research_prefill(
    st.session_state.pop(DEVICE_RESEARCH_HANDOFF_SESSION_KEY, None)
)
if quote_prefill is not None:
    st.session_state["device_research_product_name"] = quote_prefill.product_name
    st.session_state["device_research_model_name"] = quote_prefill.model_name
    st.session_state["device_research_company_name"] = quote_prefill.manufacturer

st.caption(
    "API 연결설정 · 식약처: "
    + ("설정됨" if mfds_service_key else "미설정")
    + " · 나라장터: "
    + ("설정됨" if g2b_service_key else "미설정")
)

if quote_prefill is not None:
    st.info(
        "견적서 분석에서 선택한 행의 식별정보를 불러왔습니다. 이 값은 견적서 표기일 뿐 식약처 "
        "공식 identity로 확정된 값이 아닙니다. 품목명·모델명·업체명을 확인하고 필요하면 수정한 뒤 "
        "조회를 실행하세요."
    )
    if quote_prefill.specification:
        st.caption(f"견적서 규격 참고: {quote_prefill.specification}")

with st.expander("시장조사 판정 기준", expanded=False):
    st.markdown(
        """
- **1순위 경쟁장비:** 같은 식약처 품목에 등록되어 있고 취소·취하/수출전용이 아닌 국내 후보
- **모델 identity:** 식약처 품목 조회 결과 안에서 exact-normalized 모델이 확인되어야 다른 source와 자동 연결
- **대체탐색 예외:** 위 국내 후보가 **0건일 때만** 사용목적·주요사양을 이용한 보조탐색을 제안
- 보조탐색 결과는 **대체 가능 판정이 아니라 추가 확인할 조사 후보**
- **공급사 우선순위:** 나라장터 실제 납품업체 → 식약처 업허가 확인 → 웹
- 웹에서 발견한 업체는 반드시 `웹` 출처로 표시하며 공식 총판·대리점으로 자동 승격하지 않음
- 회수·판매중지 exact 모델이 연결되면 가격정보보다 먼저 **크고 강한 경고**를 표시하는 안전 레이어를 적용
        """
    )

with st.expander("취소·취하 / 수출전용은 무엇인가?", expanded=False):
    st.markdown(
        """
- **취소·취하:** 식약처 형명정보에 허가·신고의 취소 또는 취하 상태가 기록된 등록건입니다. 현재 국내 신규 구매 후보로 자동 사용하지 않습니다.
- **수출전용:** 국내 유통 후보가 아니라 수출 목적으로 등록된 모델입니다. 국내 공급 가능 장비 목록에서는 기본적으로 숨깁니다.
- 다만 국내 정상 후보가 **0건인 경우에만**, 시장에 어떤 등록 이력이 있었는지 참고할 수 있도록 `제외된 등록제품`에서 접어 보여줍니다.
        """
    )

if not mfds_service_key:
    st.warning(
        "MFDS_SERVICE_KEY가 설정되지 않아 식약처 live 조회가 비활성화되어 있습니다. "
        "기존 DATA_GO_KR_SERVICE_KEY가 있으면 하위호환으로 사용합니다."
    )
    st.stop()

if not g2b_service_key:
    st.warning(
        "G2B_SERVICE_KEY가 설정되지 않아 나라장터 공급실적 조회는 비활성화됩니다. "
        "식약처 조회는 계속 사용할 수 있습니다."
    )

with st.form("mfds-device-research"):
    c1, c2 = st.columns(2)
    with c1:
        product_name = st.text_input(
            "식약처 품목명",
            placeholder="예: 심장충격기",
            help=(
                "식약처 형명정보 API의 공식 품목명 필터로 조회합니다. 견적서에서 불러온 값은 "
                "일반 제품명일 수 있으므로 공식 품목명인지 확인해야 합니다."
            ),
            key="device_research_product_name",
        )
        model_name = st.text_input(
            "모델명 (선택)",
            placeholder="예: Efficia DFM100",
            help=(
                "형명정보 API에는 모델명 서버 필터가 없으므로, 품목 조회 결과 안에서 exact 모델을 "
                "확인합니다. exact identity가 확인된 경우에만 나라장터와 자동 교차조회합니다."
            ),
            key="device_research_model_name",
        )
    with c2:
        company_name = st.text_input(
            "확인할 업체명 (선택)",
            placeholder="예: ○○메디칼",
            help=(
                "해당 업체의 의료기기 제조/수입/판매/임대 등 업허가 상태를 확인합니다. 견적서 "
                "제조사 표기에서 불러온 경우에도 공식 제조·수입업체라는 뜻은 아닙니다."
            ),
            key="device_research_company_name",
        )
        g2b_lookback_days = st.selectbox(
            "나라장터 공급실적 검색기간",
            options=[30, 90, 180, 365],
            index=1,
            format_func=lambda days: f"최근 {days}일",
            disabled=not bool(g2b_service_key),
        )
    submitted = st.form_submit_button("의료기기 시장조사", type="primary")

if submitted:
    if not product_name.strip() and not company_name.strip():
        st.warning("품목명 또는 업체명을 하나 이상 입력하세요.")
        st.stop()

    models = ()
    active_models = ()
    inactive_models = ()
    exact_identity = None
    active_exact_matches = ()
    model_lookup_succeeded = False

    if product_name.strip():
        st.subheader("1. 식약처 동일 품목 등록장비")
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
            st.warning(
                "API 조회 실패는 검색결과 0건과 다릅니다. 인증·권한·통신 오류가 해결되기 전에는 "
                "대체장비 보조탐색이나 다른 source와의 자동 모델 연결을 실행하지 않습니다."
            )

        if model_lookup_succeeded:
            active_models = tuple(item for item in models if item.active_for_domestic_candidate)
            inactive_models = tuple(item for item in models if not item.active_for_domestic_candidate)
            exact_identity = resolve_exact_model_identity(models, model_name)
            active_exact_matches = tuple(
                item for item in exact_identity.exact_matches if item.active_for_domestic_candidate
            )

            if model_name.strip():
                st.markdown("#### 입력 모델 공식 identity 확인")
                if exact_identity.confirmed:
                    identity_rows = [
                        {
                            "품목명": item.product_name or "",
                            "모델/형명": item.model_name or "",
                            "상품명": item.trade_name or "",
                            "허가번호": item.permit_number or "",
                            "등록상태": (
                                "국내 정상 후보"
                                if item.active_for_domestic_candidate
                                else "취소·취하/수출전용 제외"
                            ),
                        }
                        for item in exact_identity.exact_matches
                    ]
                    st.dataframe(
                        pd.DataFrame(identity_rows), use_container_width=True, hide_index=True
                    )
                    if exact_identity.ambiguous:
                        st.warning(
                            "동일 exact 모델명이 둘 이상의 품목허가번호에 연결됩니다. 자동으로 하나를 "
                            "선택하지 않으며, 다른 source와의 자동 모델 연결은 보류합니다."
                        )
                    elif active_exact_matches:
                        st.success(
                            "입력 모델이 현재 식약처 품목 조회 결과에서 exact로 확인되었습니다. "
                            "이 identity에 한해 나라장터 자동 교차조회를 진행할 수 있습니다."
                        )
                    else:
                        st.error(
                            "입력 모델의 exact 등록은 확인됐지만 취소·취하 또는 수출전용으로 분류됩니다. "
                            "현재 국내 신규구매 모델로 자동 연결하지 않습니다."
                        )
                else:
                    st.warning(
                        "입력 모델과 exact로 일치하는 형명을 현재 품목 조회 결과에서 찾지 못했습니다. "
                        "부분일치·유사문자열을 공식 identity로 승격하지 않으며 나라장터 자동 교차조회도 "
                        "보류합니다."
                    )

            c1, c2 = st.columns(2)
            c1.metric("국내 경쟁후보", f"{len(active_models)}건")
            c2.metric("전체 등록검색", f"{len(models)}건")

            if active_models:
                exact_records = set(exact_identity.exact_matches) if exact_identity else set()
                model_rows = [
                    {
                        "모델 일치": "EXACT" if item in exact_records else "",
                        "품목명": item.product_name or "",
                        "모델/형명": item.model_name or "",
                        "상품명": item.trade_name or "",
                        "허가번호": item.permit_number or "",
                        "허가구분": item.permission_type or "",
                        "업종": item.industry_name or "",
                        "허가일": item.permit_date.isoformat() if item.permit_date else "",
                    }
                    for item in active_models
                ]
                st.dataframe(pd.DataFrame(model_rows), use_container_width=True, hide_index=True)
                st.info(
                    "같은 식약처 품목에 정상 등록된 모델을 경쟁장비 후보로 제시한 것입니다. "
                    "성능·옵션·임상적 대체 가능성은 수요부서 확인이 필요합니다."
                )
            else:
                st.warning(
                    "정상적으로 식약처를 조회했지만 현재 조회조건에서 국내 공급 후보로 볼 수 있는 "
                    "동일 품목 등록모델이 0건입니다."
                )

            gate = alternative_research_gate(len(active_models))
            if gate.enabled:
                st.subheader("2. 대체장비 보조탐색")
                st.warning(gate.message)
                with st.form("alternative-research"):
                    intended_use = st.text_input(
                        "사용목적",
                        placeholder="예: 응급 심율동전환 및 제세동",
                    )
                    key_specification = st.text_input(
                        "핵심 주요사양",
                        placeholder="예: biphasic, pacing, SpO2",
                    )
                    fallback_submitted = st.form_submit_button("대체 후보를 추가 확인")
                if fallback_submitted:
                    links = build_alternative_web_search_links(
                        product_name=product_name,
                        intended_use=intended_use,
                        key_specification=key_specification,
                    )
                    if links:
                        st.caption(
                            "동일 품목 공식 후보가 0건일 때만 여는 보조 경로입니다. 웹 결과는 단순 조사 "
                            "후보이며 식약처 품목/허가를 다시 확인하기 전까지 대체장비로 확정하지 않습니다."
                        )
                        for label, url in links:
                            st.link_button(label, url)
                    else:
                        st.info("사용목적 또는 주요사양을 입력하면 추가 조사 링크를 만들 수 있습니다.")

                if inactive_models:
                    with st.expander("참고용 · 제외된 등록제품", expanded=False):
                        inactive_rows = [
                            {
                                "품목명": item.product_name or "",
                                "모델/형명": item.model_name or "",
                                "상품명": item.trade_name or "",
                                "허가번호": item.permit_number or "",
                                "취소/취하 상태": item.cancellation_status or "",
                                "취소/취하일": (
                                    item.cancellation_date.isoformat()
                                    if item.cancellation_date
                                    else ""
                                ),
                                "수출전용": (
                                    "예"
                                    if item.export_only is True
                                    else "아니오"
                                    if item.export_only is False
                                    else "미상"
                                ),
                            }
                            for item in inactive_models
                        ]
                        st.dataframe(
                            pd.DataFrame(inactive_rows), use_container_width=True, hide_index=True
                        )
                        st.caption(
                            "국내 정상 후보가 없을 때 시장 등록이력을 이해하기 위한 참고자료입니다. "
                            "이 목록은 국내 공급 가능 장비로 취급하지 않습니다."
                        )

        if model_name.strip():
            st.subheader("3. 공급사 후보")
            identity_ready_for_g2b = bool(
                model_lookup_succeeded
                and exact_identity is not None
                and exact_identity.confirmed
                and active_exact_matches
                and not exact_identity.ambiguous
            )

            if g2b_service_key and identity_ready_for_g2b:
                query = ProductQuery(
                    product_name=product_name.strip(),
                    model_name=model_name.strip(),
                )
                run = search_all(
                    query,
                    build_collectors(g2b_lookback_days=int(g2b_lookback_days)),
                )
                g2b_suppliers = extract_g2b_supplier_candidates(run.results)

                if run.errors:
                    st.warning("나라장터 조회 중 일부 오류: " + " / ".join(run.errors))

                if g2b_suppliers:
                    st.markdown("#### ① 나라장터 · 실제 공개 납품업체")
                    st.dataframe(
                        pd.DataFrame(
                            [
                                {
                                    "우선순위": 1,
                                    "업체명": supplier.name,
                                    "출처": supplier.source.value,
                                    "근거": supplier.evidence,
                                }
                                for supplier in g2b_suppliers
                            ]
                        ),
                        use_container_width=True,
                        hide_index=True,
                    )
                else:
                    st.info(
                        "현재 verified 나라장터 mapping/검색기간에서 실제 공급업체 근거를 찾지 못했습니다. "
                        "없다는 뜻이 아니라 현재 연결된 공개근거에서 미확인이라는 뜻입니다."
                    )
            elif g2b_service_key:
                st.warning(
                    "나라장터 자동 교차조회 보류: 입력 모델의 식약처 exact identity가 국내 정상 단일 "
                    "후보로 확인되지 않았습니다. 잘못된 모델을 다른 source에 연결하지 않기 위한 "
                    "fail-closed 동작입니다."
                )

            st.markdown("#### ② 웹 · 보조 공급사 탐색")
            st.caption(
                "웹 검색은 나라장터보다 낮은 우선순위입니다. 검색 결과 업체는 공식 총판/대리점 여부를 "
                "제조사 또는 식약처/공식 근거로 추가 확인해야 합니다."
            )
            for label, url in build_web_supplier_search_links(product_name, model_name):
                st.link_button(label, url)

    if company_name.strip():
        st.subheader("4. 식약처 업체 업허가 확인")
        business_client = MfdsBusinessLicenseClient(
            mfds_service_key,
            base_url=settings.mfds_business_license_base_url or MFDS_BUSINESS_LICENSE_BASE_URL,
            timeout_seconds=settings.mfds_request_timeout_seconds,
            max_retries=settings.mfds_max_retries,
        )
        business_lookup_succeeded = False
        try:
            businesses = business_client.search_company(company_name.strip())
            business_lookup_succeeded = True
        except (PublicDataClientError, ValueError) as exc:
            st.error(f"식약처 업체 허가정보 조회 실패: {exc}")
            businesses = ()

        if business_lookup_succeeded and businesses:
            business_rows = [
                {
                    "업체명": item.company_name or "",
                    "출처": "식약처",
                    "업종": item.industry_type or "",
                    "상태": item.business_status or "정상/별도상태 없음",
                    "현재사용 후보": "예" if item.is_active else "아니오",
                    "업허가번호": item.business_permit_number or "",
                    "허가일": item.permit_date.isoformat() if item.permit_date else "",
                    "주소": item.address or "",
                }
                for item in businesses
            ]
            st.dataframe(pd.DataFrame(business_rows), use_container_width=True, hide_index=True)
            st.caption(
                "식약처 업허가 확인은 의료기기 관련 영업 자격 근거입니다. 특정 모델의 공식 총판·대리점 "
                "관계를 의미하지는 않습니다."
            )
        elif business_lookup_succeeded:
            st.info("식약처 조회는 정상 완료됐지만 입력한 업체명으로 업허가 정보를 찾지 못했습니다.")

    st.divider()
    st.markdown("### 안전정보")
    st.info(
        "회수·판매중지 자동연결은 공식 endpoint/request contract와 해당 API 접근권한을 확인한 뒤 "
        "연결합니다. 구현 전까지 `검색결과 없음=안전`으로 해석하지 않습니다. exact 모델/허가번호 "
        "회수대상이 확인되면 구매를 자동 차단하지는 않되 이 영역에 큰 빨간 경고를 표시합니다."
    )

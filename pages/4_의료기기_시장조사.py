from __future__ import annotations

import pandas as pd
import streamlit as st

from purchase_price.clients.data_go_kr import PublicDataClientError
from purchase_price.config import get_settings
from purchase_price.services.mfds_device_intelligence import (
    MFDS_BUSINESS_LICENSE_BASE_URL,
    MFDS_MODEL_INFO_BASE_URL,
    MfdsBusinessLicenseClient,
    MfdsModelInfoClient,
)

st.set_page_config(page_title="의료기기 시장조사", page_icon="🏥", layout="wide")
st.title("의료기기 시장조사")
st.caption(
    "식약처 공식 공개정보를 기준으로 같은 품목의 등록모델과 의료기기 관련 업체 허가상태를 "
    "조회합니다. 동일 품목은 경쟁후보이지 임상적 대체 가능성을 의미하지 않습니다."
)

settings = get_settings()
service_key = (settings.data_go_kr_service_key or "").strip()

with st.expander("판정 기준", expanded=False):
    st.write(
        "- 동일 식약처 품목의 다른 등록모델만 경쟁장비 후보로 표시합니다.\n"
        "- 사용목적·주요사양 유사도만으로 다른 품목을 자동 추천하지 않습니다.\n"
        "- 취소/취하 또는 수출전용 모델은 일반 경쟁후보에서 제외 표시합니다.\n"
        "- 업체 조회는 식약처의 제조/수입/수리/판매/임대 등 업허가 상태를 확인합니다.\n"
        "- 현재 단계는 품목/업체 조회 foundation이며 exact 모델→허가업체 자동 연결과 "
        "회수·판매중지 경고는 다음 구현에서 추가합니다."
    )

if not service_key:
    st.warning(
        "DATA_GO_KR_SERVICE_KEY가 설정되지 않아 식약처 live 조회가 비활성화되어 있습니다. "
        "서비스키 값은 화면이나 로그에 표시하지 않습니다."
    )
    st.stop()

with st.form("mfds-device-research"):
    c1, c2 = st.columns(2)
    with c1:
        product_name = st.text_input(
            "식약처 품목명",
            placeholder="예: 심장충격기",
            help="현재 M1은 식약처 공식 품목명을 기준으로 동일 품목 등록모델을 조회합니다.",
        )
    with c2:
        company_name = st.text_input(
            "확인할 업체명 (선택)",
            placeholder="예: ○○메디칼",
            help="해당 업체의 의료기기 제조/수입/판매/임대 등 업허가 상태를 확인합니다.",
        )
    submitted = st.form_submit_button("식약처 정보 조회", type="primary")

if submitted:
    if not product_name.strip() and not company_name.strip():
        st.warning("품목명 또는 업체명을 하나 이상 입력하세요.")
        st.stop()

    if product_name.strip():
        st.subheader("동일 식약처 품목 등록모델")
        model_client = MfdsModelInfoClient(
            service_key,
            base_url=settings.mfds_model_info_base_url or MFDS_MODEL_INFO_BASE_URL,
            timeout_seconds=settings.mfds_request_timeout_seconds,
            max_retries=settings.mfds_max_retries,
        )
        try:
            models = model_client.search_models(product_name.strip())
        except (PublicDataClientError, ValueError) as exc:
            st.error(f"식약처 형명정보 조회 실패: {exc}")
            models = ()

        if models:
            active_count = sum(item.active_for_domestic_candidate for item in models)
            c1, c2, c3 = st.columns(3)
            c1.metric("등록모델", f"{len(models)}건")
            c2.metric("일반 경쟁후보", f"{active_count}건")
            c3.metric("취소·수출전용 등", f"{len(models) - active_count}건")

            model_rows = [
                {
                    "경쟁후보": "후보" if item.active_for_domestic_candidate else "제외/확인",
                    "품목명": item.product_name or "",
                    "모델/형명": item.model_name or "",
                    "상품명": item.trade_name or "",
                    "허가번호": item.permit_number or "",
                    "허가구분": item.permission_type or "",
                    "업종": item.industry_name or "",
                    "허가일": item.permit_date.isoformat() if item.permit_date else "",
                    "취소/취하": item.cancellation_status or "",
                    "수출전용": (
                        "예" if item.export_only is True else "아니오" if item.export_only is False else "미상"
                    ),
                }
                for item in models
            ]
            st.dataframe(
                pd.DataFrame(model_rows),
                use_container_width=True,
                hide_index=True,
            )
            st.info(
                "여기 표시되는 모델은 같은 식약처 품목에 등록된 후보입니다. 성능·옵션·임상목적이 "
                "동등하다는 뜻은 아니며 실제 비교견적 요청 전 수요부서/사용부서 확인이 필요합니다."
            )
        else:
            st.info("해당 품목명으로 형명정보 등록모델을 찾지 못했습니다.")

    if company_name.strip():
        st.subheader("업체 의료기기 업허가 확인")
        business_client = MfdsBusinessLicenseClient(
            service_key,
            base_url=(
                settings.mfds_business_license_base_url or MFDS_BUSINESS_LICENSE_BASE_URL
            ),
            timeout_seconds=settings.mfds_request_timeout_seconds,
            max_retries=settings.mfds_max_retries,
        )
        try:
            businesses = business_client.search_company(company_name.strip())
        except (PublicDataClientError, ValueError) as exc:
            st.error(f"식약처 업체 허가정보 조회 실패: {exc}")
            businesses = ()

        if businesses:
            business_rows = [
                {
                    "업체명": item.company_name or "",
                    "업종": item.industry_type or "",
                    "상태": item.business_status or "정상/별도상태 없음",
                    "현재사용 후보": "예" if item.is_active else "아니오",
                    "업허가번호": item.business_permit_number or "",
                    "허가일": item.permit_date.isoformat() if item.permit_date else "",
                    "주소": item.address or "",
                }
                for item in businesses
            ]
            st.dataframe(
                pd.DataFrame(business_rows),
                use_container_width=True,
                hide_index=True,
            )
            st.caption(
                "업허가 확인은 해당 업체가 의료기기 관련 업종으로 허가된 상태인지 확인하는 근거입니다. "
                "특정 장비의 공식 총판/대리점 관계까지 의미하지는 않습니다."
            )
        else:
            st.info("입력한 업체명으로 의료기기 업허가 정보를 찾지 못했습니다.")

    st.divider()
    st.caption(
        "다음 M2/M3에서 exact 모델 → 품목/허가번호/제조·수입업체 자동연결, 기존 나라장터 실제 "
        "공급업체 join을 추가합니다. M4에서는 회수·판매중지 및 식약처 안전성서한을 별도 안전경고로 표시합니다."
    )

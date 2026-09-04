from __future__ import annotations

import pandas as pd
import streamlit as st

from purchase_price.clients.data_go_kr import PublicDataClientError
from purchase_price.config import get_settings
from purchase_price.services.mfds_udi import MFDS_UDI_CODE_BASE_URL, MfdsUdiCodeClient
from purchase_price.services.safety_support import (
    MFDS_STANDARD_CODE_DATASET_URL,
    MFDS_UDI_PORTAL_URL,
)

st.set_page_config(page_title="의료기기 UDI-DI 공식조회", page_icon="🏷️", layout="wide")
st.title("의료기기 UDI-DI 공식조회")
st.caption(
    "식약처 의료기기 표준코드(UDI코드)정보 API의 공식 `UDIDI_CD` 필터로 UDI-DI를 exact 조회합니다. "
    "이 API에는 모델명 검색 필터가 없으므로 모델명→UDI 역검색에는 사용하지 않습니다."
)

settings = get_settings()
mfds_service_key = (settings.resolved_mfds_service_key or "").strip()

if not mfds_service_key:
    st.warning(
        "MFDS_SERVICE_KEY가 설정되지 않아 live UDI-DI 조회가 비활성화되어 있습니다. "
        "기존 DATA_GO_KR_SERVICE_KEY가 있으면 하위호환으로 사용합니다."
    )

with st.form("mfds-udi-exact-lookup"):
    udi_di = st.text_input(
        "UDI-DI",
        placeholder="예: 0880...",
        help="제품 포장/라벨 또는 식약처 UDI 시스템에서 확인한 UDI-DI를 입력합니다.",
    )
    submitted = st.form_submit_button(
        "식약처 UDI-DI 조회",
        type="primary",
        disabled=not bool(mfds_service_key),
    )

if submitted:
    if not udi_di.strip():
        st.warning("UDI-DI를 입력하세요.")
        st.stop()

    client = MfdsUdiCodeClient(
        mfds_service_key,
        base_url=settings.mfds_udi_code_base_url or MFDS_UDI_CODE_BASE_URL,
        timeout_seconds=settings.mfds_request_timeout_seconds,
        max_retries=settings.mfds_max_retries,
    )

    try:
        records = client.lookup_udi(udi_di)
    except (PublicDataClientError, ValueError) as exc:
        st.error(f"식약처 UDI-DI 조회 실패: {exc}")
        st.warning(
            "API 조회 실패는 검색결과 0건과 다릅니다. 해당 OpenAPI 활용승인/권한 또는 통신 상태를 "
            "확인한 뒤 다시 조회해야 합니다."
        )
    else:
        if records:
            st.success(f"입력한 UDI-DI와 exact로 일치하는 공식 코드정보 {len(records)}건을 확인했습니다.")
            st.dataframe(
                pd.DataFrame(
                    [
                        {
                            "UDI-DI": item.udi_di or "",
                            "코드구조": item.code_structure_code or "",
                            "코드체계": item.code_system_name or "",
                            "업체명": item.company_name or "",
                            "업체형태": item.company_type or "",
                            "출처": "식약처",
                        }
                        for item in records
                    ]
                ),
                use_container_width=True,
                hide_index=True,
            )
            st.info(
                "이 결과는 입력한 UDI-DI의 공식 코드정보입니다. 현재 입력한 모델명과 동일 제품이라는 "
                "판정까지 자동으로 확장하지 않으며, 필요하면 형명정보/품목허가정보와 교차확인합니다."
            )
        else:
            st.info(
                "식약처 UDI-DI API 조회는 정상 완료됐지만 입력한 UDI-DI와 exact로 일치하는 코드정보를 "
                "확인하지 못했습니다. 이는 제품이 없거나 안전하다는 의미가 아닙니다."
            )

st.divider()
st.markdown("### 공식 확인 경로")
c1, c2 = st.columns(2)
c1.link_button("식약처 UDI 시스템", MFDS_UDI_PORTAL_URL, use_container_width=True)
c2.link_button(
    "공공데이터포털 · UDI코드정보 API 명세",
    "https://www.data.go.kr/data/15073874/openapi.do",
    use_container_width=True,
)
st.link_button(
    "표준코드별 제품정보 API 명세",
    MFDS_STANDARD_CODE_DATASET_URL,
)
st.caption(
    "`표준코드별 제품정보`는 모델·허가·품목 등 더 많은 필드를 제공하지만, 현재 접근 가능한 공식 "
    "명세에서 모델명 request filter를 확정하지 못해 모델명 역검색을 추정 구현하지 않습니다."
)

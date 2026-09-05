from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import streamlit as st

from purchase_price.clients.data_go_kr import PublicDataClientError
from purchase_price.config import get_settings
from purchase_price.services.g2b_contract_evidence import (
    G2B_CONTRACT_BASE_URL,
    G2B_CONTRACT_DATASET_URL,
    G2BContractEvidenceClient,
)

st.set_page_config(page_title="나라장터 계약근거", page_icon="📑", layout="wide")
st.title("나라장터 물품 계약근거")
st.caption(
    "나라장터 계약정보에서 품명 기준 계약 존재·계약번호·계약기관·계약방법·상세원문을 확인합니다. "
    "이 화면은 계약총액을 제품 단가로 환산하지 않습니다."
)

settings = get_settings()
service_key = (settings.resolved_g2b_service_key or "").strip()

with st.expander("이 근거를 가격과 어떻게 구분하나?", expanded=True):
    st.markdown(
        """
- 이 서비스는 **계약 체결 근거**를 추가하는 용도입니다.
- 계약번호·계약기관·계약방법·상세URL은 독립적인 시장근거로 사용할 수 있습니다.
- 계약금액이 있더라도 **수량·단위·구성조건이 검증되지 않으면 제품 단가로 나누지 않습니다.**
- 따라서 이 화면의 결과는 현재 A/B 직접가격 범위나 견적 높음/낮음 판정에 자동 투입되지 않습니다.
        """
    )

if not service_key:
    st.warning(
        "G2B_SERVICE_KEY가 설정되지 않아 live 계약조회가 비활성화되어 있습니다. "
        "계약정보서비스 활용신청 권한도 별도로 필요할 수 있습니다."
    )

with st.form("g2b-contract-evidence"):
    product_name = st.text_input("계약 품명", placeholder="예: 심장충격기, 의료용냉장고")
    c1, c2 = st.columns(2)
    with c1:
        begin_date = st.date_input("계약체결 시작일", value=date.today() - timedelta(days=90))
    with c2:
        end_date = st.date_input("계약체결 종료일", value=date.today())
    contract_method_code = st.text_input(
        "계약방법코드 (선택)",
        placeholder="비워두면 전체",
        help="특정 계약방법코드를 알고 있을 때만 입력합니다. 코드를 임의 추정하지 않습니다.",
    )
    submitted = st.form_submit_button(
        "계약근거 조회",
        type="primary",
        disabled=not bool(service_key),
    )

if submitted:
    if not product_name.strip():
        st.warning("계약 품명을 입력하세요.")
        st.stop()
    if begin_date > end_date:
        st.warning("시작일은 종료일보다 늦을 수 없습니다.")
        st.stop()

    client = G2BContractEvidenceClient(
        service_key,
        base_url=settings.g2b_contract_base_url or G2B_CONTRACT_BASE_URL,
        timeout_seconds=settings.g2b_request_timeout_seconds,
        max_retries=settings.g2b_max_retries,
    )

    try:
        records = client.search_product_contracts(
            product_name=product_name.strip(),
            begin_date=begin_date,
            end_date=end_date,
            contract_method_code=contract_method_code,
        )
    except (PublicDataClientError, ValueError) as exc:
        st.error(f"나라장터 계약정보 조회 실패: {exc}")
        st.warning(
            "API 실패는 계약 0건과 다릅니다. 해당 계약정보서비스 활용신청/권한, 요청조건 또는 "
            "통신상태를 확인해야 합니다."
        )
        st.stop()

    if not records:
        st.info(
            "나라장터 계약정보 API는 정상 응답했지만 현재 품명·기간 조건에서 계약근거를 확인하지 못했습니다."
        )
    else:
        st.success(f"계약근거 {len(records)}건을 확인했습니다.")
        rows = [
            {
                "확정계약번호": item.decision_contract_number or "",
                "품명": item.product_name or product_name.strip(),
                "계약체결일": item.contract_date.isoformat() if item.contract_date else "",
                "계약방법": item.contract_method_name or "",
                "계약기관": item.contract_institution_name or "",
                "상세원문": item.detail_url or "",
                "근거지문(SHA-256)": item.provenance.fingerprint if item.provenance else "",
            }
            for item in records
        ]
        st.dataframe(
            pd.DataFrame(rows),
            use_container_width=True,
            hide_index=True,
            column_config={"상세원문": st.column_config.LinkColumn("상세원문")},
        )
        st.caption(
            "근거지문은 계약정보 API 응답 중 명시적으로 허용한 공개 필드만 canonical JSON으로 만든 뒤 "
            "계산한 SHA-256입니다. serviceKey·token·password·secret 같은 비밀정보는 포함하지 않습니다."
        )
        st.caption(
            "계약근거는 구매시장 존재 여부와 조달기관·계약방법을 확인하는 참고자료입니다. "
            "수량·단위·옵션·VAT 등 단가 조건이 검증되지 않았으므로 가격범위에 자동 포함하지 않습니다."
        )

st.divider()
st.link_button("공공데이터포털 · 나라장터 계약정보서비스 공식 명세", G2B_CONTRACT_DATASET_URL)
st.caption(
    "현재 사용 operation은 `getCntrctInfoListThngPPSSrch`입니다. API 권한이 없거나 요청계약이 "
    "변경된 경우 오류를 0건으로 바꾸지 않고 그대로 실패로 표시합니다."
)

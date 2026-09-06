from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

import pandas as pd
import streamlit as st

from purchase_price.clients.data_go_kr import PublicDataClientError
from purchase_price.collectors.g2b_shopping import SOURCE_NAME
from purchase_price.config import get_settings
from purchase_price.services.g2b_contract_evidence import (
    G2B_CONTRACT_BASE_URL,
    G2B_CONTRACT_DATASET_URL,
    G2BContractEvidenceClient,
)
from purchase_price.services.g2b_search_policy import (
    G2B_DEFAULT_LOOKBACK_DAYS,
    G2B_LOOKBACK_OPTIONS,
    g2b_lookback_label,
)
from purchase_price.services.price_conditions import build_price_condition_profile
from purchase_price.services.pricing import assess_prices
from purchase_price.services.purchase_review import build_purchase_review_input
from purchase_price.ui.market_research import (
    render_external_research_links,
    render_market_reference_summary,
    run_market_research,
)
from purchase_price.ui.widgets import (
    render_condition_table,
    render_discovery_candidates,
    render_evidence_table,
    render_observation_cards,
    render_source_status,
)

st.set_page_config(page_title="빠른 검색", page_icon="🔎", layout="wide")
st.title("빠른 검색")
st.caption("제품명만 입력해도 나라장터 관련 거래를 먼저 넓게 조사하고, 확인 가능한 직접가격 근거는 별도로 표시합니다.")

settings = get_settings()
g2b_key = (settings.resolved_g2b_service_key or "").strip()
g2b_enabled = bool(g2b_key)
price_tab, contract_tab = st.tabs(["시장가격 검색", "나라장터 계약근거"])

with price_tab:
    if g2b_enabled:
        st.info(
            "모델명이나 verified mapping이 없어도 **제품명 키워드만으로 나라장터 Research를 실행**합니다. "
            "예: `마취`, `제세동기`, `약품냉장고`. 제품 식별·조건 확인은 검색을 막지 않고 결과의 신뢰도와 최종 판정에만 영향을 줍니다."
        )
    else:
        st.caption("현재 공식 제조사 공개가격 source만 사용합니다. 나라장터는 API key 설정 시 활성화됩니다.")

    with st.form("quick-price-search-form"):
        c1, c2 = st.columns(2)
        with c1:
            product_name = st.text_input("제품명", placeholder="예: 마취, 약품냉장고")
            manufacturer = st.text_input("제조사 (선택)", placeholder="예: GE, Dräger, GMS")
        with c2:
            model_name = st.text_input("모델명 (선택)", placeholder="예: FLOW-C, GMSR-182")
            specification = st.text_input("규격 (선택)", placeholder="예: 182L")
        quote_text = st.text_input("현재 견적 단가 (선택)", placeholder="예: 5000000")
        g2b_lookback_days = st.selectbox(
            "나라장터 검색기간",
            options=G2B_LOOKBACK_OPTIONS,
            index=G2B_LOOKBACK_OPTIONS.index(G2B_DEFAULT_LOOKBACK_DAYS),
            format_func=g2b_lookback_label,
            disabled=not g2b_enabled,
            help="1~5년 모두 API 허용범위 이내의 기간창으로 나눠 검색합니다.",
        )
        submitted = st.form_submit_button("시장가격 검색", type="primary")

    if submitted:
        quote = None
        if quote_text.strip():
            try:
                quote = Decimal(quote_text.replace(",", "").strip())
            except InvalidOperation:
                st.error("견적 단가는 숫자로 입력하세요.")
                st.stop()

        review_input = build_purchase_review_input(
            product_name=product_name,
            manufacturer=manufacturer,
            model_name=model_name,
            specification=specification,
            quote_unit_price=quote,
        )
        if review_input is None:
            st.warning("검색조건을 하나 이상 입력하세요.")
            st.stop()

        query = review_input.to_product_query()
        with st.status("시장가격을 조사하고 있습니다...", expanded=True) as status:
            status.write("공식 제조사/검증 직접가격 source를 확인합니다.")
            status.write("제품명이 있으면 verified mapping 여부와 관계없이 나라장터 관련 거래를 넓게 조사합니다.")
            run, discovery = run_market_research(
                query,
                lookback_days=int(g2b_lookback_days),
                research_pages_per_term=1,
                research_request_budget=24,
            )
            status.update(label="시장가격 조사 완료", state="complete", expanded=False)

        st.subheader("시장가격 요약")
        render_market_reference_summary(discovery, quote_unit_price=review_input.quote_unit_price)

        if run.results:
            assessment = assess_prices(run.results, review_input.quote_unit_price)
            st.markdown("**검증 직접가격 근거**")
            c1, c2, c3 = st.columns(3)
            c1.metric("직접근거", f"{assessment.observed_count}건")
            c2.metric("독립 출처", f"{assessment.source_count}개")
            c3.metric("근거 신뢰도", assessment.confidence)
            render_observation_cards(run.results)
            if review_input.quote_unit_price is not None:
                if assessment.quote_position is None:
                    st.caption("직접근거의 최종 높고 낮음 판정은 세부 거래조건 확인 전까지 보류됩니다.")
                else:
                    st.success(f"검증 직접근거 기준 견적 위치: {assessment.quote_position}")
        else:
            st.caption(
                "동일제품으로 검증된 직접가격은 아직 없을 수 있습니다. 위 나라장터 시장참고 범위와 후보는 계속 확인할 수 있습니다."
            )

        if discovery is not None:
            st.subheader("나라장터 관련 거래 후보")
            render_discovery_candidates(discovery)

        render_external_research_links(query)

        with st.expander("상세 근거·조건·수집상태", expanded=False):
            st.markdown("**출처별 검색상태**")
            render_source_status(run)
            failed_sources = [
                source for source in run.source_statuses if not source.succeeded and not source.skipped
            ]
            if failed_sources:
                st.error(
                    "일부 출처 수집 실패: "
                    + ", ".join(source.source_name for source in failed_sources)
                    + ". 실패는 정상 0건과 구분됩니다."
                )
            if run.errors:
                st.warning("일부 수집기 오류: " + " / ".join(run.errors))

            g2b_status = next(
                (source for source in run.source_statuses if source.source_name == SOURCE_NAME), None
            )
            if g2b_status is not None and g2b_status.telemetry:
                telemetry = g2b_status.telemetry
                st.caption(
                    "나라장터 검증 직접가격 수집: "
                    f"API 요청 {telemetry.get('request_count', '-')} / "
                    f"예산 {telemetry.get('request_budget', '-')}회 · "
                    f"완료 검색창 {telemetry.get('window_count', '-')}개 · "
                    f"원자료 {telemetry.get('records_seen', '-')}건"
                )

            if run.results:
                profiles = [build_price_condition_profile(item) for item in run.results]
                condition_average = round(
                    sum(profile.completeness_percent for profile in profiles) / len(profiles)
                )
                st.caption(f"직접근거 평균 조건명시율: {condition_average}%")
                st.markdown("**가격 근거자료**")
                render_evidence_table(run.results)
                st.markdown("**가격조건 구조화**")
                render_condition_table(run.results)

with contract_tab:
    st.caption(
        "계약번호·계약기관·계약방법·상세원문을 확인합니다. 계약총액은 수량·단위·구성조건 검증 없이 "
        "제품 단가로 환산하지 않으며 직접가격 판정에도 자동 투입하지 않습니다."
    )
    if not g2b_enabled:
        st.warning("G2B 서비스키가 설정되지 않아 live 계약조회가 비활성화되어 있습니다.")

    with st.form("quick-g2b-contract-evidence"):
        contract_product_name = st.text_input("계약 품명", placeholder="예: 마취, 심장충격기, 의료용냉장고")
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
        contract_submitted = st.form_submit_button(
            "계약근거 조회", type="primary", disabled=not g2b_enabled
        )

    if contract_submitted:
        if not contract_product_name.strip():
            st.warning("계약 품명을 입력하세요.")
        elif begin_date > end_date:
            st.warning("시작일은 종료일보다 늦을 수 없습니다.")
        else:
            client = G2BContractEvidenceClient(
                g2b_key,
                base_url=settings.g2b_contract_base_url or G2B_CONTRACT_BASE_URL,
                timeout_seconds=settings.g2b_request_timeout_seconds,
                max_retries=settings.g2b_max_retries,
            )
            try:
                records = client.search_product_contracts(
                    product_name=contract_product_name.strip(),
                    begin_date=begin_date,
                    end_date=end_date,
                    contract_method_code=contract_method_code,
                )
            except (PublicDataClientError, ValueError) as exc:
                st.error(f"나라장터 계약정보 조회 실패: {exc}")
                st.warning("API 실패는 계약 0건과 다릅니다. 서비스 권한·요청조건·통신상태를 확인하세요.")
            else:
                if not records:
                    st.info("API는 정상 응답했지만 현재 품명·기간 조건에서 계약근거가 0건입니다.")
                else:
                    st.success(f"계약근거 {len(records)}건을 확인했습니다.")
                    rows = [
                        {
                            "확정계약번호": item.decision_contract_number or "",
                            "품명": item.product_name or contract_product_name.strip(),
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
                    st.caption("계약근거는 시장 존재와 계약방식을 확인하는 참고자료이며 단가 비교범위에 자동 포함하지 않습니다.")

    st.link_button("공공데이터포털 · 나라장터 계약정보서비스 공식 명세", G2B_CONTRACT_DATASET_URL)

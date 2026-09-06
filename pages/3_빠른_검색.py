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
    render_market_reference_summary,
    render_procurement_research,
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
st.caption(
    "제품명만으로 나라장터 입찰공고·품목상세·낙찰·사전규격·계약을 먼저 조사하고, "
    "동일제품으로 검증된 직접가격은 별도로 엄격하게 표시합니다."
)

settings = get_settings()
g2b_key = (settings.resolved_g2b_service_key or "").strip()
g2b_enabled = bool(g2b_key)
price_tab, contract_tab = st.tabs(["시장가격 조사", "나라장터 계약근거"])

with price_tab:
    if g2b_enabled:
        st.info(
            "나라장터 Research는 exact 모델이나 verified mapping이 없어도 실행됩니다. "
            "입찰 추정가격·예정/추정단가·낙찰총액·사전규격 예산·계약총액은 시장조사 "
            "참고자료이며, 동일제품 거래단가로 확인되기 전에는 가격판정에 사용하지 않습니다."
        )
    else:
        st.caption(
            "현재 공식 제조사 공개가격 source를 사용합니다. 나라장터는 API key 설정 시 활성화됩니다."
        )

    with st.form("quick-price-search-form"):
        c1, c2 = st.columns(2)
        with c1:
            product_name = st.text_input("제품명", placeholder="예: 마취, 가스마취기")
            manufacturer = st.text_input("제조사", placeholder="예: Maquet")
        with c2:
            model_name = st.text_input("모델명", placeholder="예: FLOW-C")
            specification = st.text_input("규격", placeholder="선택")
        quote_text = st.text_input("현재 견적 단가 (선택)", placeholder="예: 66000000")
        g2b_lookback_days = st.selectbox(
            "나라장터 검색기간",
            options=G2B_LOOKBACK_OPTIONS,
            index=G2B_LOOKBACK_OPTIONS.index(G2B_DEFAULT_LOOKBACK_DAYS),
            format_func=g2b_lookback_label,
            disabled=not g2b_enabled,
            help=(
                "검증 직접가격은 선택 기간 전체를 안전한 기간창으로 나눠 조회합니다. "
                "입찰·낙찰·사전규격 Research는 응답시간을 위해 최근 최대 90일을 우선 조사하고, "
                "확인된 최신 공고는 품목상세·계약을 추가 조회합니다."
            ),
        )
        submitted = st.form_submit_button("시장가격 조사", type="primary")

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
        with st.status("공개 시장자료를 조사하고 있습니다...", expanded=True) as research_status:
            research_status.write("검증된 동일제품 직접가격 source를 확인합니다.")
            if g2b_enabled and query.product_name.strip():
                research_status.write(
                    "나라장터 입찰·낙찰·사전규격을 넓게 찾고, 최신 공고의 품목상세·계약을 연결합니다."
                )
                research_status.write("종합쇼핑몰 관련 단가 후보도 별도 Research로 확인합니다.")
            run, discovery, market_bundle = run_market_research(
                query,
                lookback_days=int(g2b_lookback_days),
                research_pages_per_term=1,
                research_request_budget=18,
                procurement_detail_limit=4,
            )
            research_status.update(label="시장가격 조사 완료", state="complete", expanded=False)

        if market_bundle is not None:
            render_procurement_research(market_bundle)

        if discovery is not None:
            render_market_reference_summary(
                discovery,
                quote_unit_price=review_input.quote_unit_price,
            )
            if discovery.candidates:
                with st.expander("나라장터 쇼핑몰 관련 단가 후보", expanded=False):
                    st.caption(
                        "쇼핑몰 후보도 검증 전에는 동일제품 직접가격으로 사용하지 않습니다."
                    )
                    render_discovery_candidates(discovery)

        st.subheader("검증된 직접가격 검색상태")
        render_source_status(run)
        failed_sources = [
            status for status in run.source_statuses if not status.succeeded and not status.skipped
        ]
        if failed_sources:
            failed_names = ", ".join(status.source_name for status in failed_sources)
            st.error(
                "직접가격 수집 미완료: 일부 출처가 실패했습니다. 실패는 가격 0건과 다릅니다. "
                f"실패 출처: {failed_names}"
            )
        if run.errors:
            st.warning("일부 수집기 오류: " + " / ".join(run.errors))

        g2b_status = next(
            (status for status in run.source_statuses if status.source_name == SOURCE_NAME), None
        )
        if g2b_status is not None and g2b_status.telemetry:
            telemetry = g2b_status.telemetry
            st.caption(
                "나라장터 직접가격 수집: "
                f"API 요청 {telemetry.get('request_count', '-')} / "
                f"예산 {telemetry.get('request_budget', '-')}회 · "
                f"완료 검색창 {telemetry.get('window_count', '-')}개 · "
                f"페이지 {telemetry.get('pages_fetched', '-')} · "
                f"원자료 {telemetry.get('records_seen', '-')}건"
            )

        if not run.results:
            st.warning(
                "검증된 동일제품 직접가격은 아직 확보하지 못했습니다. 위 조달 Research와 쇼핑몰 후보는 "
                "시장에 관련 구매·가격 자료가 존재하는지 확인하는 참고자료이며, 동일제품 및 비교조건이 "
                "확인되기 전에는 직접가격 판정에 사용하지 않습니다."
            )
        else:
            assessment = assess_prices(run.results, review_input.quote_unit_price)
            profiles = [build_price_condition_profile(item) for item in run.results]
            condition_average = round(
                sum(profile.completeness_percent for profile in profiles) / len(profiles)
            )

            st.subheader("검증된 동일제품 가격 요약")
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("관측 직접근거", f"{assessment.observed_count}건")
            c2.metric("독립 출처", f"{assessment.source_count}개")
            c3.metric("근거 신뢰도", assessment.confidence)
            c4.metric("평균 조건명시", f"{condition_average}%")
            render_observation_cards(run.results)
            st.write(assessment.message)
            if failed_sources:
                st.warning(
                    "위 가격 요약은 수집 완료 출처만 반영한 부분 요약입니다. "
                    "실패 출처 복구 전 최종 구매판정에 사용하지 마세요."
                )
            if review_input.quote_unit_price is not None:
                if assessment.quote_position is None:
                    st.info("입력 견적과의 엄격한 높고 낮음 판정은 거래조건 검증 전까지 보류합니다.")
                else:
                    st.success(f"견적 위치: {assessment.quote_position}")

            st.subheader("검증된 가격 근거자료")
            render_evidence_table(run.results)
            with st.expander("상세 가격조건", expanded=False):
                render_condition_table(run.results)

with contract_tab:
    st.caption(
        "계약번호·계약기관·계약방법·상세원문을 확인합니다. 계약총액은 수량·단위·구성조건 검증 없이 "
        "제품 단가로 환산하지 않으며 직접가격 판정에도 자동 투입하지 않습니다."
    )
    if not g2b_enabled:
        st.warning("G2B 서비스키가 설정되지 않아 live 계약조회가 비활성화되어 있습니다.")

    with st.form("quick-g2b-contract-evidence"):
        contract_product_name = st.text_input(
            "계약 품명", placeholder="예: 가스마취기, 심장충격기"
        )
        c1, c2 = st.columns(2)
        with c1:
            begin_date = st.date_input(
                "계약체결 시작일", value=date.today() - timedelta(days=90)
            )
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
                st.warning(
                    "API 실패는 계약 0건과 다릅니다. 서비스 권한·요청조건·통신상태를 확인하세요."
                )
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
                            "근거지문(SHA-256)": (
                                item.provenance.fingerprint if item.provenance else ""
                            ),
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
                        "계약근거는 시장 존재와 계약방식을 확인하는 참고자료이며 단가 비교범위에 자동 포함하지 않습니다."
                    )

    st.link_button("공공데이터포털 · 나라장터 계약정보서비스 공식 명세", G2B_CONTRACT_DATASET_URL)

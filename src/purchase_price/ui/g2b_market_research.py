from __future__ import annotations

import pandas as pd
import streamlit as st

from purchase_price.services.g2b_market_models import (
    G2BResearchRecord,
    G2BResearchSource,
    MarketResearchBundle,
    ResearchAmountType,
    ResearchSourceStatus,
)

_SOURCE_LABELS = {
    G2BResearchSource.BID_NOTICE: "입찰공고",
    G2BResearchSource.BID_ITEM: "공고 품목상세",
    G2BResearchSource.AWARD: "낙찰",
    G2BResearchSource.PRESPEC: "사전규격",
    G2BResearchSource.CONTRACT: "계약",
    G2BResearchSource.LIFECYCLE: "과정통합",
    G2BResearchSource.SHOPPING: "쇼핑몰·납품",
}

_AMOUNT_LABELS = {
    ResearchAmountType.UNIT_PRICE: "단가",
    ResearchAmountType.ESTIMATED_UNIT_PRICE: "예정/추정단가",
    ResearchAmountType.ESTIMATED_PRICE: "추정가격",
    ResearchAmountType.BASIC_AMOUNT: "기초금액",
    ResearchAmountType.BUDGET_AMOUNT: "예산",
    ResearchAmountType.AWARD_TOTAL: "낙찰총액",
    ResearchAmountType.CONTRACT_TOTAL: "계약총액",
    ResearchAmountType.UNKNOWN: "금액 의미 미확인",
}


def _format_amount(record: G2BResearchRecord) -> str:
    if record.amount is None:
        return ""
    return f"{record.amount:,.0f}원 ({_AMOUNT_LABELS[record.amount_type]})"


def _format_quantity(record: G2BResearchRecord) -> str:
    if record.quantity is None:
        return ""
    value = f"{record.quantity:,.4f}".rstrip("0").rstrip(".")
    return f"{value} {record.unit or ''}".strip()


def _row(record: G2BResearchRecord) -> dict[str, object]:
    return {
        "자료구분": _SOURCE_LABELS[record.source_type],
        "공고/자료명": record.title or record.product_name or "",
        "품목식별번호": record.product_id or "",
        "세부품명번호": record.detail_product_code or "",
        "라인": record.item_sequence or "",
        "원문규격": record.original_specification or "",
        "수량·단위": _format_quantity(record),
        "기관": record.institution or "",
        "일자": record.published_date.isoformat() if record.published_date else "",
        "금액": _format_amount(record),
        "원문금액": record.original_amount_text or "",
        "낙찰/공급업체": record.supplier or "",
        "납품조건": record.delivery_condition or "",
        "변경차수": record.record_change_order or "",
        "공고번호": record.bid_notice_no or "",
        "검색어": record.search_term or "",
        "원문": record.source_url or "",
    }


def _coverage_caption(bundle: MarketResearchBundle) -> str:
    parts: list[str] = []
    for source in bundle.sources:
        if not source.coverage_start and not source.coverage_end and not source.search_strategy:
            continue
        label = _SOURCE_LABELS[source.source]
        coverage = ""
        if source.coverage_start and source.coverage_end:
            coverage = f"{source.coverage_start.isoformat()} ~ {source.coverage_end.isoformat()}"
        elif source.coverage_start:
            coverage = f"{source.coverage_start.isoformat()} 이후"
        elif source.coverage_end:
            coverage = f"{source.coverage_end.isoformat()}까지"
        strategy = source.search_strategy.replace("adaptive independent product-name", "단계적 독립 품명검색")
        strategy = strategy.replace("bid-linked", "공고번호 연결")
        detail = " · ".join(part for part in (coverage, strategy) if part)
        if source.requested_lookback_days:
            detail += f" · 요청 {source.requested_lookback_days}일"
        parts.append(f"{label}: {detail}")
    return " / ".join(parts)


def render_g2b_market_research(bundle: MarketResearchBundle, *, max_rows: int = 100) -> None:
    """Render broad external procurement research without implying hospital procurement flow."""

    st.subheader("타 기관 나라장터 구매사례 Research")
    st.caption(
        "우리 병원의 입찰 절차가 아니라 타 기관의 공개 조달자료를 시장가격 조사 참고자료로 조회합니다. "
        "입찰공고·공고 품목상세·낙찰·사전규격·계약·과정통합 자료를 함께 보되, 추정가격·예산·낙찰총액·계약총액은 "
        "동일제품 거래단가가 아니며 제품 식별과 거래조건 검증 전에는 가격판정에 사용하지 않습니다."
    )
    if bundle.query_terms:
        st.markdown("**조사 기준 품목 후보**")
        st.write(" · ".join(f"`{term}`" for term in bundle.query_terms))
        st.caption("위 명칭은 검색 확장용 후보이며 공식 분류 또는 동일제품 확정 결과가 아닙니다.")

    columns = st.columns(len(bundle.sources))
    for column, source in zip(columns, bundle.sources, strict=True):
        label = _SOURCE_LABELS[source.source]
        if source.status in {ResearchSourceStatus.SUCCESS, ResearchSourceStatus.SUCCESS_0}:
            column.metric(label, f"{len(source.records)}건")
        elif source.status == ResearchSourceStatus.PARTIAL:
            column.metric(label, f"{len(source.records)}건 · 부분")
        elif source.status == ResearchSourceStatus.NOT_RUN:
            column.metric(label, "미조회")
        elif source.status == ResearchSourceStatus.NOT_CONFIGURED:
            column.metric(label, "미설정")
        elif source.status == ResearchSourceStatus.NOT_AUTHORIZED:
            column.metric(label, "인증 미승인")
        else:
            column.metric(label, "조회 실패")

    coverage = _coverage_caption(bundle)
    if coverage:
        st.caption(f"실제 조회범위/전략 · {coverage}")

    failures = [
        source
        for source in bundle.sources
        if source.status
        in {
            ResearchSourceStatus.FAILURE,
            ResearchSourceStatus.PARTIAL,
            ResearchSourceStatus.NOT_AUTHORIZED,
        }
    ]
    not_run = [source for source in bundle.sources if source.status == ResearchSourceStatus.NOT_RUN]

    for source in failures:
        label = _SOURCE_LABELS[source.source]
        if source.status == ResearchSourceStatus.NOT_AUTHORIZED:
            st.error(
                f"{label}: 현재 선택된 Research API 인증/활용신청으로 호출할 수 없습니다. "
                "검색 결과 0건이 아니라 서비스 권한 문제입니다. "
                f"{source.error_type}: {source.error_message}"
            )
        else:
            st.warning(
                f"{label}: API 조회 실패/부분완료입니다. 이것은 검색 결과 0건이 아닙니다. "
                f"{source.error_type}: {source.error_message}"
            )

    for source in not_run:
        label = _SOURCE_LABELS[source.source]
        st.info(
            f"{label}: 필요한 검색 seed/검색어가 없어 이 후속 조회는 실행하지 않았습니다. "
            "따라서 0건 검색 결과가 아니라 **미조회** 상태입니다."
        )

    records = sorted(
        bundle.records,
        key=lambda item: (item.published_date is not None, item.published_date),
        reverse=True,
    )
    if not records:
        if not failures and not not_run:
            st.info("API는 정상 응답했지만 현재 조사 기준·기간에서 유의미한 Research 결과가 0건입니다.")
        elif not_run and not failures:
            st.info(
                "실행된 1차 검색에서 연결 가능한 자료를 찾지 못해 일부 후속 조회가 미실행 상태입니다. "
                "미조회 source를 정상 0건으로 해석하지 마세요."
            )
        return

    shown = records[:max_rows]
    st.dataframe(
        pd.DataFrame([_row(record) for record in shown]),
        use_container_width=True,
        hide_index=True,
        column_config={"원문": st.column_config.LinkColumn("원문")},
    )
    st.caption(
        "품목식별번호·세부품명번호·라인·원문규격·납품조건·변경차수·원문금액은 원자료 추적과 "
        "후속 제품 fingerprint 비교를 위한 provenance입니다. 해당 필드 존재만으로 동일제품이나 단가 Evidence로 승격하지 않습니다."
    )
    if len(records) > len(shown):
        st.caption(f"총 {len(records)}건 중 최신 {len(shown)}건을 표시합니다.")

    attachment_count = sum(len(record.attachments) for record in records)
    if attachment_count:
        st.caption(
            f"규격/설명 첨부 링크 {attachment_count}개를 확인했습니다. 첨부문서의 제조사·모델 식별은 "
            "동일제품 여부 검증에 사용하되, 첨부 키워드만으로 직접가격을 자동 승격하지 않습니다."
        )

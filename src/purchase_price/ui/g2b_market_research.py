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
        "수량·단위": _format_quantity(record),
        "기관": record.institution or "",
        "일자": record.published_date.isoformat() if record.published_date else "",
        "금액": _format_amount(record),
        "낙찰/공급업체": record.supplier or "",
        "공고번호": record.bid_notice_no or "",
        "검색어": record.search_term or "",
        "원문": record.source_url or "",
    }


def render_g2b_market_research(bundle: MarketResearchBundle, *, max_rows: int = 100) -> None:
    """Render broad procurement research without implying direct-price comparability."""

    st.subheader("나라장터 전체 Research")
    st.caption(
        "종합쇼핑몰뿐 아니라 입찰공고·공고 품목상세·낙찰·사전규격을 함께 조회합니다. "
        "추정가격·예산·낙찰총액·예정단가는 동일제품 거래단가가 아니며, "
        "제품 식별과 거래조건 검증 전에는 가격판정에 사용하지 않습니다."
    )
    if bundle.query_terms:
        st.caption("검색어: " + " · ".join(bundle.query_terms))

    columns = st.columns(len(bundle.sources))
    for column, source in zip(columns, bundle.sources, strict=True):
        label = _SOURCE_LABELS[source.source]
        if source.status in {ResearchSourceStatus.SUCCESS, ResearchSourceStatus.SUCCESS_0}:
            column.metric(label, f"{len(source.records)}건")
        elif source.status == ResearchSourceStatus.PARTIAL:
            column.metric(label, f"{len(source.records)}건 · 부분")
        elif source.status == ResearchSourceStatus.NOT_CONFIGURED:
            column.metric(label, "미설정")
        elif source.status == ResearchSourceStatus.NOT_AUTHORIZED:
            column.metric(label, "인증 미승인")
        else:
            column.metric(label, "조회 실패")

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

    records = sorted(
        bundle.records,
        key=lambda item: (item.published_date is not None, item.published_date),
        reverse=True,
    )
    if not records:
        if not failures:
            st.info("API는 정상 응답했지만 현재 검색어·기간에서 Research 결과가 0건입니다.")
        return

    shown = records[:max_rows]
    st.dataframe(
        pd.DataFrame([_row(record) for record in shown]),
        use_container_width=True,
        hide_index=True,
        column_config={"원문": st.column_config.LinkColumn("원문")},
    )
    if len(records) > len(shown):
        st.caption(f"총 {len(records)}건 중 최신 {len(shown)}건을 표시합니다.")

    attachment_count = sum(len(record.attachments) for record in records)
    if attachment_count:
        st.caption(
            f"규격/설명 첨부 링크 {attachment_count}개를 확인했습니다. 첨부문서의 제조사·모델 식별은 "
            "동일제품 여부 검증에 사용하되, 첨부 키워드만으로 직접가격을 자동 승격하지 않습니다."
        )

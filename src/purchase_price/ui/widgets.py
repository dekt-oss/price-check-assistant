from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal

import pandas as pd
import streamlit as st

from purchase_price.schemas import CollectedPrice
from purchase_price.services.g2b_unmapped_discovery import G2BUnmappedDiscoveryResult
from purchase_price.services.price_conditions import build_price_condition_profile
from purchase_price.services.pricing import assess_prices
from purchase_price.services.search import SearchRun


@dataclass(frozen=True)
class ObservationGroup:
    source_name: str
    vat_status: str
    count: int
    low: Decimal | None
    median: Decimal | None
    high: Decimal | None


def source_status_rows(run: SearchRun) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for status in run.source_statuses:
        telemetry = status.telemetry or {}
        request_text = ""
        if telemetry.get("request_count") is not None:
            request_text = f"{telemetry['request_count']}/{telemetry.get('request_budget', '-')}"
        rows.append(
            {
                "출처": status.source_name,
                "상태": status.status_label,
                "건수": status.result_count,
                "API 요청/예산": request_text,
                "검색창": telemetry.get("window_count", ""),
                "원자료": telemetry.get("records_seen", ""),
                "메모": status.note or status.error or "",
            }
        )
    return rows


def render_source_status(run: SearchRun) -> None:
    rows = source_status_rows(run)
    if rows:
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)


def evidence_rows(items: Iterable[CollectedPrice]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for item in items:
        profile = build_price_condition_profile(item)
        rows.append(
            {
                "출처": item.source_name,
                "단가": float(item.price),
                "통화": item.currency,
                "등급": item.match_grade.value,
                "Evidence Type": item.evidence_type.value,
                "비교범위": item.comparison_scope.value,
                "자료성격": item.source_type.value,
                "거래일": item.transaction_date.isoformat() if item.transaction_date else "",
                "VAT": profile.vat,
                "수량·단위": profile.quantity_unit,
                "조건명시": f"{profile.completeness_percent}%",
                "조건": item.conditions or "",
                "비교메모": item.comparison_note or "",
                "근거ID": item.source_record_id or "",
                "수집일": item.collected_at.isoformat(),
                "URL": item.source_url or "",
            }
        )
    return rows


def render_evidence_table(items: Iterable[CollectedPrice]) -> None:
    rows = evidence_rows(items)
    if not rows:
        st.info("확보된 검증 공개가격 근거가 없습니다.")
        return
    st.dataframe(
        pd.DataFrame(rows),
        use_container_width=True,
        hide_index=True,
        column_config={"단가": st.column_config.NumberColumn(format="%d")},
    )


def condition_rows(items: Iterable[CollectedPrice]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for item in items:
        profile = build_price_condition_profile(item)
        rows.append(
            {
                "출처": item.source_name,
                "근거ID": item.source_record_id or "",
                "VAT": profile.vat,
                "수량·단위": profile.quantity_unit,
                "배송": profile.delivery,
                "설치": profile.installation,
                "옵션/부속": profile.options,
                "보증": profile.warranty,
                "유지보수": profile.maintenance,
                "거래/기준일": profile.basis_date,
                "명시율": f"{profile.completeness_percent}%",
                "미확인 조건": ", ".join(profile.missing_labels) or "없음",
            }
        )
    return rows


def render_condition_table(items: Iterable[CollectedPrice]) -> None:
    rows = condition_rows(items)
    if rows:
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
    st.caption("미확인은 조건이 없다는 뜻이 아니라 현재 공개근거에서 확인하지 못했다는 뜻입니다.")


def discovery_candidate_rows(discovery: G2BUnmappedDiscoveryResult) -> list[dict[str, object]]:
    return [
        {
            "관련성": candidate.relevance,
            "점수": candidate.score,
            "거래일": candidate.transaction_date.isoformat() if candidate.transaction_date else "",
            "나라장터 표기": candidate.title,
            "세부품명": candidate.classification_name,
            "세부품명코드": candidate.classification_code,
            "탐색어": candidate.search_term,
            "관련 근거": candidate.match_reason,
            "표기 금액 (미검증)": float(candidate.price),
            "근거ID": candidate.source_record_id,
        }
        for candidate in discovery.candidates
    ]


def _render_discovery_error_messages(discovery: G2BUnmappedDiscoveryResult) -> None:
    if not discovery.error_messages:
        return
    for message in discovery.error_messages[:3]:
        st.caption(f"API 진단: {message}")


def render_discovery_candidates(discovery: G2BUnmappedDiscoveryResult) -> None:
    budget_text = f"/{discovery.request_budget}" if discovery.request_budget else ""
    st.write(
        f"상태: **{discovery.status_label}** · 검색어: {', '.join(discovery.terms) or '-'} · "
        f"API 요청 {discovery.request_count}{budget_text}회 · 원자료 확인 {discovery.records_seen}건"
    )
    if discovery.status == "failure":
        st.warning(
            "나라장터 후보 탐색 실패입니다. 이는 '검색 결과 0건'과 다릅니다. "
            "API 연결·응답 오류가 해결되기 전에는 시장자료가 없다고 판단할 수 없습니다."
        )
        _render_discovery_error_messages(discovery)
        return
    if discovery.status == "partial":
        details: list[str] = []
        if discovery.failed_query_count:
            details.append(f"실패 검색구간 {discovery.failed_query_count}개")
        if discovery.truncated_query_count:
            details.append(f"페이지 상한으로 일부수집 {discovery.truncated_query_count}개")
        detail_text = " · " + " · ".join(details) if details else ""
        st.warning(
            "후보 탐색이 일부만 완료됐습니다. 현재 표는 부분 조사결과이며 누락 가능성이 있습니다"
            f"{detail_text}."
        )
        _render_discovery_error_messages(discovery)
    rows = discovery_candidate_rows(discovery)
    if not rows:
        st.info("선택 기간과 연구용 탐색어에서 나라장터 후보를 찾지 못했습니다.")
        return
    with st.expander("미검증 Research 후보 보기", expanded=True):
        st.dataframe(
            pd.DataFrame(rows),
            use_container_width=True,
            hide_index=True,
            column_config={
                "점수": st.column_config.NumberColumn(format="%d"),
                "표기 금액 (미검증)": st.column_config.NumberColumn(format="%d"),
            },
        )
        st.warning(
            "Research 후보의 관련성 점수는 조사 우선순위일 뿐 MatchGrade가 아닙니다. "
            "위 금액은 관측가격 범위와 견적 판정에 포함하지 않습니다."
        )


def build_observation_groups(items: Iterable[CollectedPrice]) -> list[ObservationGroup]:
    grouped: dict[tuple[str, str], list[CollectedPrice]] = defaultdict(list)
    for item in items:
        vat_status = build_price_condition_profile(item).vat
        grouped[(item.source_name, vat_status)].append(item)

    groups: list[ObservationGroup] = []
    for (source_name, vat_status), group_items in grouped.items():
        assessment = assess_prices(group_items)
        if assessment.observed_count == 0:
            continue
        groups.append(
            ObservationGroup(
                source_name=source_name,
                vat_status=vat_status,
                count=assessment.observed_count,
                low=assessment.low,
                median=assessment.median,
                high=assessment.high,
            )
        )
    return sorted(groups, key=lambda group: (group.source_name.casefold(), group.vat_status))


def render_observation_cards(items: Iterable[CollectedPrice]) -> None:
    groups = build_observation_groups(items)
    if not groups:
        st.info("A/B 직접가격 근거로 표시할 관측범위가 없습니다.")
        return
    st.caption("관측범위는 출처와 VAT 상태가 같은 근거끼리만 묶습니다. 조건이 다른 근거는 합치지 않습니다.")
    for group in groups:
        with st.container(border=True):
            st.markdown(f"**{group.source_name} · VAT {group.vat_status}**")
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("근거", f"{group.count}건")
            c2.metric("하단", f"{group.low:,.0f}원" if group.low is not None else "산정불가")
            c3.metric("중앙", f"{group.median:,.0f}원" if group.median is not None else "산정불가")
            c4.metric("상단", f"{group.high:,.0f}원" if group.high is not None else "산정불가")

"""병원 경영 Benchmark.

공개 회계자료(의료기관 회계정보 공시)와 병원 명단으로 병원을 같은 기준에서 비교한다. 숫자는 모두
services/hospital_metrics.py가 계산하고, 자료가 없는 칸은 '자료 없음'으로 둔다. 어떤 숫자도 추정해
넣지 않는다.
"""

from __future__ import annotations

from decimal import Decimal

import pandas as pd
import streamlit as st

from purchase_price.services import alio_disclosure
from purchase_price.services import hospital_ai_explanation as ai_explanation
from purchase_price.services import hospital_benchmark as benchmark
from purchase_price.services import hospital_master as master_service
from purchase_price.services import hospital_metrics as metrics
from purchase_price.services import hospital_report as report_service
from purchase_price.ui import benchmark_charts as charts
from purchase_price.ui.runtime_secrets import hydrate_streamlit_runtime_secrets

hydrate_streamlit_runtime_secrets()


def _streamlit_secrets():
    try:
        return st.secrets
    except Exception:  # noqa: BLE001 - no secrets file locally
        return None

DEFAULT_TARGET_ID = "H-BUSAN-PAIK"
HEADLINE_METRICS = (
    "revenue_growth",
    "medical_margin",
    "net_margin",
    "labor_ratio",
    "material_ratio",
    "admin_ratio",
    "revenue_per_bed",
)
TREND_YEARS = 5
DEFAULT_BED_RANGE = (700, 850)
TREND_CHARTS = (
    ("medical_revenue", "의료수익 (억원)", Decimal(100_000_000)),
    ("labor_ratio", "인건비율 (%)", Decimal(1)),
    ("material_ratio", "재료비율 (%)", Decimal(1)),
    ("medical_margin", "의료이익률 (%)", Decimal(1)),
)
SOURCE_NAME = "의료기관 회계정보 공시(한국보건산업진흥원, haspa.khidi.or.kr)"

data = benchmark.load_benchmark_data()
master = data.master
hospitals = master.hospitals
by_id = {hospital.hospital_id: hospital for hospital in hospitals}

st.title("병원 경영 Benchmark")
st.caption("공개 회계자료로 병원을 같은 기준에서 비교합니다. 숫자는 모두 프로그램이 계산합니다.")

target_options = [h.hospital_id for h in hospitals if h.group == "core"] + [
    h.hospital_id for h in sorted(hospitals, key=lambda h: h.short_name) if h.group != "core"
]
target_id = st.selectbox(
    "기준 병원",
    target_options,
    index=target_options.index(DEFAULT_TARGET_ID),
    format_func=lambda value: by_id[value].canonical_name
    + ("" if by_id[value].group == "core" else f" ({by_id[value].region}, 유사 규모)"),
)
target = by_id[target_id]

info_cols = st.columns(5)
for column, (label, value) in zip(
    info_cols,
    (
        ("법인", target.foundation or "확인 안 됨"),
        ("의료원", target.network or "확인 안 됨"),
        ("지역", target.region or "확인 안 됨"),
        ("종별", target.hospital_type or "확인 안 됨"),
        ("병상수", target.size_beds_text),
    ),
    strict=True,
):
    with column:
        st.caption(label)
        st.markdown(f"**{value}**")
if not target.type_verified or target.bed_count is None:
    st.caption("종별과 병상수는 심평원 병원정보 연계 후 확정합니다. 지금 종별은 공개자료 기준 1차 입력입니다.")

st.subheader("비교군")
peer_kind = st.radio(
    "비교 방식",
    list(master_service.PEER_GROUP_LABELS),
    format_func=lambda value: master_service.PEER_GROUP_LABELS[value],
    horizontal=True,
)
custom_ids: list[str] = []
if peer_kind == master_service.PEER_CUSTOM:
    custom_ids = st.multiselect(
        "비교할 병원 (2~10개)",
        [h.hospital_id for h in hospitals if h.hospital_id != target_id],
        format_func=lambda value: by_id[value].canonical_name,
        max_selections=10,
    )
bed_range: tuple[int, int] | None = None
if peer_kind == master_service.PEER_SIMILAR_SIZE:
    bed_range = st.slider(
        "병상수 범위",
        min_value=300,
        max_value=1500,
        value=DEFAULT_BED_RANGE,
        step=10,
        help="회계공시 목록에 실린 병상수(해당 연도 말 심평원 자료) 기준입니다. 전국 상급종합·종합병원 중 이 범위 병원을 비교합니다.",
    )
peers = master.peer_group(target, peer_kind, custom_ids=custom_ids, bed_range=bed_range)
peers_ready = True
if peer_kind == master_service.PEER_SIMILAR_SIZE and target.size_beds is None:
    st.warning("병상수 자료가 아직 없어 유사 규모 비교군을 만들 수 없습니다.")
    peers_ready = False
elif peer_kind == master_service.PEER_CUSTOM and len(peers) < 2:
    st.info("비교할 병원을 2개 이상 고르면 비교표가 만들어집니다.")
    peers_ready = False
elif not peers:
    st.info("이 조건에 맞는 비교 병원이 병원 명단에 없습니다.")
    peers_ready = False
else:
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "병원": peer.canonical_name,
                    "지역": peer.region,
                    "종별": peer.hospital_type,
                    "설립형태": peer.ownership,
                    "병상수": peer.size_beds_text,
                    "회계자료 연도": (
                        f"{years[0]}~{years[-1]}" if (years := data.years_for(peer.hospital_id)) else "자료 없음"
                    ),
                }
                for peer in peers
            ]
        ),
        hide_index=True,
        width="stretch",
    )
if not peers_ready:
    peers = ()

st.subheader("주요 경영지표")
fiscal_years = data.fiscal_years
if not fiscal_years:
    st.info("회계자료가 아직 적재되지 않았습니다. 아래 표는 모두 '자료 없음'으로 표시됩니다.")
    fiscal_year = None
else:
    fiscal_year = st.selectbox(
        "회계연도",
        fiscal_years,
        index=0,
        help="공시 회계연도입니다. 학교법인 병원은 그해 3월부터 다음 해 2월까지가 한 회계연도입니다.",
    )

if fiscal_year is None:
    rows = metrics.compare_to_peers({}, [], metric_keys=HEADLINE_METRICS)
else:
    rows = benchmark.compare(data, target, peers, fiscal_year, HEADLINE_METRICS)
st.dataframe(
    pd.DataFrame(
        [
            {
                "지표": row.label,
                target.short_name: metrics.format_metric(row.value, row.unit),
                "비교군 평균": metrics.format_metric(row.peer_average, row.unit),
                "비교 병원 수": f"{row.peer_count}곳",
                "위치": row.position_text,
            }
            for row in rows
        ]
    ),
    hide_index=True,
    width="stretch",
)

if fiscal_year is not None and peers:
    findings = metrics.describe_findings(
        rows, benchmark.gap_history(data, target, peers, fiscal_year, HEADLINE_METRICS)
    )
    st.markdown("**해석**")
    if findings:
        for finding in findings:
            st.markdown(f"- {finding.text}")
    else:
        st.caption("비교군 평균과 눈에 띄게 다른 지표가 없거나, 비교할 자료가 부족합니다.")
    st.caption("해석 문장은 위 표의 숫자만으로 프로그램이 만든 문장입니다.")

    ai_key = ai_explanation.resolve_api_key(_streamlit_secrets())
    explain_key = f"benchmark_ai::{target_id}::{peer_kind}::{','.join(custom_ids)}::{fiscal_year}"
    quality_for_ai = report_service.quality_notes(
        benchmark.quality_report(data, target, peers, fiscal_year)
    )
    with st.container(border=True):
        st.markdown("**AI 경영분석 설명**")
        if ai_key is None:
            st.caption("AI 설명 연결 설정이 아직 없습니다. 위 계산 문장으로 확인해 주세요.")
        elif st.button("AI 설명 보기", key=f"btn::{explain_key}"):
            source = ai_explanation.build_input(
                target_name=target.short_name,
                fiscal_year=fiscal_year,
                peer_label=master_service.PEER_GROUP_LABELS[peer_kind],
                peer_names=[p.short_name for p in peers],
                rows=rows,
                findings=findings,
                quality_notes=quality_for_ai,
            )
            with st.spinner("계산 결과를 바탕으로 설명을 쓰는 중입니다."):
                try:
                    st.session_state[explain_key] = ai_explanation.explain(source, api_key=ai_key).text
                except ai_explanation.ExplanationError as exc:
                    st.session_state[explain_key] = None
                    st.warning(f"{exc} 위 계산 문장을 기준으로 봐 주세요.")
        if st.session_state.get(explain_key):
            st.write(st.session_state[explain_key])
            st.caption(
                "AI는 위 표의 계산 결과만 받아 문장으로 풀어 썼습니다. 설명 속 숫자는 모두 계산 결과와 "
                "대조했고, 계산 결과에 없는 숫자가 나오면 표시하지 않습니다."
            )

if fiscal_year is not None:
    with st.expander("병원별 전체 지표 보기"):
        compare_hospitals = [target, *peers]
        table = []
        for key, (label, unit, _) in metrics.METRIC_SPECS.items():
            entry = {"지표": label}
            for hospital in compare_hospitals:
                values = benchmark.metrics_for(data, hospital, fiscal_year)
                entry[hospital.short_name] = metrics.format_metric(values.get(key) if values else None, unit)
            table.append(entry)
        st.dataframe(pd.DataFrame(table), hide_index=True, width="stretch")

with st.expander("지표 계산 방식"):
    st.dataframe(
        pd.DataFrame(
            [
                {"지표": label, "단위": unit, "계산 방식": formula}
                for (label, unit, _), formula in zip(
                    metrics.METRIC_SPECS.values(),
                    (
                        "올해 의료수익 ÷ 전년 의료수익 - 1",
                        "3년 전 대비 연평균 증가율",
                        "5년 전 대비 연평균 증가율",
                        "의료이익 ÷ 의료수익",
                        "당기순이익 ÷ 의료수익",
                        "인건비 ÷ 의료수익",
                        "(약품비 + 진료재료비) ÷ 의료수익",
                        "약품비 ÷ 의료수익",
                        "진료재료비 ÷ 의료수익",
                        "관리운영비 ÷ 의료수익",
                        "부채총계 ÷ 자본총계 (자본총계가 0 이하이면 계산하지 않음)",
                        "유동자산 ÷ 유동부채",
                        "(단기·임직원단기·장기·외화장기 차입금 + 유동성장기부채) ÷ 자산총계",
                        "의료수익 ÷ 병상수",
                        "인건비 ÷ 병상수",
                        "(약품비 + 진료재료비) ÷ 병상수",
                    ),
                    strict=True,
                )
            ]
        ),
        hide_index=True,
        width="stretch",
    )

st.subheader("최근 5년 추이")
if fiscal_year is None:
    st.caption("회계자료가 적재되면 그래프가 표시됩니다.")
else:
    trend_years = [y for y in range(fiscal_year - TREND_YEARS + 1, fiscal_year + 1)]
    chart_hospitals = [target, *peers]
    st.caption(
        f"파란 선은 {target.short_name}, 검은 점선은 비교군 평균, 회색 선은 비교 병원 하나하나입니다. "
        "선이나 점에 마우스를 올리면 병원 이름과 값이 보입니다. 세로축은 차이가 잘 보이도록 값의 범위에 맞췄고, "
        "값이 아주 크거나 작은 비교 병원 선은 그래프 가장자리에서 잘립니다(정확한 값은 '숫자로 보기')."
    )
    for metric_key, title, scale in TREND_CHARTS:
        st.markdown(f"**{title}**")
        table = benchmark.trend_table(data, chart_hospitals, metric_key, trend_years)
        frame = charts.trend_frame(table, target.short_name, scale)
        if frame.empty:
            st.caption("이 기간에는 표시할 자료가 없습니다.")
            continue
        unit = title.split("(")[-1].rstrip(")") if "(" in title else ""
        st.altair_chart(charts.trend_chart(frame, unit_label=unit), use_container_width=True)
        with st.expander(f"{title} 숫자로 보기"):
            st.dataframe(charts.wide_table(frame), hide_index=True, width="stretch")
    st.caption("빈 칸은 그해 공시가 없다는 뜻입니다. 빈 해를 다른 값으로 채우지 않습니다.")

st.subheader("자료 상태")
if fiscal_year is None:
    st.info("회계자료가 아직 없습니다. 모든 지표가 '자료 없음'입니다.")
else:
    quality = benchmark.quality_report(data, target, peers, fiscal_year)
    target_period = benchmark.target_period(data, target.hospital_id, fiscal_year)
    with st.container(border=True):
        st.markdown(
            f"**{target.short_name} {fiscal_year} 회계기간:** "
            + (f"{target_period[0]} ~ {target_period[1]}" if target_period else "확인 안 됨")
        )
        if quality.period_mismatch:
            st.warning(
                "회계기간이 기준 병원과 다른 병원이 있습니다. 같은 연도라도 기간이 달라 단순 비교에 주의하세요: "
                + "; ".join(quality.period_mismatch)
            )
        if quality.no_data:
            st.warning(f"{fiscal_year} 회계자료 없음: " + ", ".join(quality.no_data))
        for name, accounts in quality.missing_accounts.items():
            st.warning(f"{name}: 공시에 없는 항목 — " + ", ".join(accounts))
        if quality.negative_equity:
            st.info(
                "자본총계가 0 이하라 부채비율을 계산하지 않은 병원: " + ", ".join(quality.negative_equity)
            )
        st.markdown(
            "**병상수 기준일:** "
            + "; ".join(f"{name} {text}" for name, text in quality.bed_counts.items())
        )
        if any(benchmark.beds_for(data, h, fiscal_year) is None for h in (target, *peers)):
            st.caption("병상수가 없는 병원은 병상당 지표와 유사 규모 비교가 '자료 없음'입니다.")
        if quality.unverified_types:
            st.caption("종별 확인 전(심평원 연계 전): " + ", ".join(quality.unverified_types))
        st.caption(
            f"출처: {SOURCE_NAME}. 가져온 날: " + ", ".join(sorted(set(quality.fetched.values())))
        )

alio_hospitals = [h for h in (target, *peers) if alio_disclosure.alio_table_for(h.hospital_id)]
if alio_hospitals:
    st.subheader("공공기관 경영공시 (알리오) 보조 지표")
    st.info(alio_disclosure.ALIO_SCOPE_NOTE)
    shown_entities: set[str] = set()
    for hospital in alio_hospitals:
        table = alio_disclosure.alio_table_for(hospital.hospital_id)
        entity_key = repr(table[:2])
        if entity_key in shown_entities:  # 본원과 양산은 같은 법인 자료라 한 번만 보여 준다
            continue
        shown_entities.add(entity_key)
        with st.expander(f"{hospital.short_name} 법인 인력·재무·차입금 (알리오)", expanded=hospital is target):
            year_columns = sorted({k for row in table for k in row if k.endswith("년") or "분기" in k})
            st.dataframe(
                pd.DataFrame(
                    [
                        {
                            "항목": row["항목"],
                            "단위": row["단위"],
                            **{
                                col: (f"{row[col]:,}" if row.get(col) is not None else "-")
                                for col in year_columns
                            },
                        }
                        for row in table
                    ]
                ),
                hide_index=True,
                width="stretch",
            )
            st.caption(
                "출처: 알리오(alio.go.kr) 공시 원문. 연말 결산 기준이며 '분기 중간' 열은 올해 공시된 분기 값입니다."
            )

st.subheader("리포트 내려받기")
if fiscal_year is None or not peers:
    st.caption("회계연도와 비교군이 정해지면 리포트를 내려받을 수 있습니다.")
else:
    report = report_service.build_report(
        data, target, peer_kind, fiscal_year, custom_ids=custom_ids, bed_range=bed_range
    )
    ai_text = st.session_state.get(
        f"benchmark_ai::{target_id}::{peer_kind}::{','.join(custom_ids)}::{fiscal_year}"
    )
    if ai_text:
        report.explanation = ai_text
        report.explanation_note = "AI 설명: 위 표의 계산 결과만 입력으로 받아 쓴 문장입니다."
    excel_col, text_col = st.columns(2)
    with excel_col:
        st.download_button(
            "엑셀 리포트 내려받기",
            data=report_service.report_workbook(report),
            file_name=report_service.report_filename(report, "xlsx"),
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
    with text_col:
        st.download_button(
            "문서 리포트 내려받기 (.md)",
            data=report_service.report_markdown(report).encode("utf-8"),
            file_name=report_service.report_filename(report, "md"),
            mime="text/markdown",
        )
    st.caption(
        "지금 화면의 병원·연도·비교군 기준입니다. 요약표, 병원별 전체 지표, 5년 추이, 자료 상태가 들어 있고, "
        "AI 설명을 본 뒤 내려받으면 그 설명도 함께 들어갑니다. 매주 월요일 아침에는 같은 형식의 리포트가 "
        "자동으로 만들어집니다."
    )

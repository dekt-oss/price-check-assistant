"""병원 경영 Benchmark.

공개 회계자료(의료기관 회계정보 공시)와 병원 명단으로 병원을 같은 기준에서 비교한다. 숫자는 모두
services/hospital_metrics.py가 계산하고, 자료가 없는 칸은 '자료 없음'으로 둔다. 어떤 숫자도 추정해
넣지 않는다.
"""

from __future__ import annotations

from decimal import Decimal

import pandas as pd
import streamlit as st

from purchase_price.services import hospital_benchmark as benchmark
from purchase_price.services import hospital_master as master_service
from purchase_price.services import hospital_metrics as metrics
from purchase_price.ui.runtime_secrets import hydrate_streamlit_runtime_secrets

hydrate_streamlit_runtime_secrets()

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
TREND_CHARTS = (
    ("medical_revenue", "의료수익 (억원)", Decimal(100_000_000)),
    ("labor_ratio", "인건비율 (%)", Decimal(1)),
    ("material_ratio", "재료비율 (%)", Decimal(1)),
)
SOURCE_NAME = "의료기관 회계정보 공시(한국보건산업진흥원, haspa.khidi.or.kr)"

data = benchmark.load_benchmark_data()
master = data.master
hospitals = master.hospitals
by_id = {hospital.hospital_id: hospital for hospital in hospitals}

st.title("병원 경영 Benchmark")
st.caption("공개 회계자료로 병원을 같은 기준에서 비교합니다. 숫자는 모두 프로그램이 계산합니다.")

target_id = st.selectbox(
    "기준 병원",
    [hospital.hospital_id for hospital in hospitals],
    index=[h.hospital_id for h in hospitals].index(DEFAULT_TARGET_ID),
    format_func=lambda value: by_id[value].canonical_name,
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
        ("병상수", f"{target.bed_count:,}" if target.bed_count else "자료 없음"),
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
peers = master.peer_group(target, peer_kind, custom_ids=custom_ids)
peers_ready = True
if peer_kind == master_service.PEER_SIMILAR_SIZE and target.bed_count is None:
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
                    "병상수": f"{peer.bed_count:,}" if peer.bed_count is not None else "자료 없음",
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
    for metric_key, title, scale in TREND_CHARTS:
        st.markdown(f"**{title}**")
        table = benchmark.trend_table(data, chart_hospitals, metric_key, trend_years)
        frame = pd.DataFrame(
            {name: benchmark.as_float_series(values, scale) for name, values in table.items()}
        )
        frame.index = [str(year) for year in frame.index]
        if frame.notna().any().any():
            st.line_chart(frame)
        else:
            st.caption("이 기간에는 표시할 자료가 없습니다.")
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
        if any(h.bed_count is None for h in (target, *peers)):
            st.caption("병상수가 없는 병원은 병상당 지표와 유사 규모 비교가 '자료 없음'입니다.")
        if quality.unverified_types:
            st.caption("종별 확인 전(심평원 연계 전): " + ", ".join(quality.unverified_types))
        st.caption(
            f"출처: {SOURCE_NAME}. 가져온 날: " + ", ".join(sorted(set(quality.fetched.values())))
        )

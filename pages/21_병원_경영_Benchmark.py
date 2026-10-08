"""병원 경영 Benchmark (Phase 1 기본 화면).

병원 Master(표준 병원 명단)와 비교군 선택, 지표 표의 틀을 먼저 만든다. 회계 숫자는 KHIDI 공시자료를
적재한 뒤에만 채워지고, 그 전에는 '자료 없음'으로 표시한다. 어떤 숫자도 추정해 넣지 않는다.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from purchase_price.services import hospital_master as master_service
from purchase_price.services import hospital_metrics as metrics
from purchase_price.ui.runtime_secrets import hydrate_streamlit_runtime_secrets

hydrate_streamlit_runtime_secrets()

DEFAULT_TARGET_ID = "H-BUSAN-PAIK"
HEADLINE_METRICS = (
    "revenue_growth",
    "medical_margin",
    "labor_ratio",
    "material_ratio",
    "revenue_per_bed",
)
TREND_METRICS = ("의료수익", "인건비율", "재료비율")

master = master_service.load_hospital_master()
hospitals = master.hospitals
by_id = {hospital.hospital_id: hospital for hospital in hospitals}

st.title("병원 경영 Benchmark")
st.caption("공개 회계·병상 자료로 병원을 같은 기준에서 비교합니다. 숫자는 모두 프로그램이 계산합니다.")

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
    st.caption("종별과 병상수는 심평원 병원정보 연계 후 확정합니다. 지금 값은 공개자료 기준 1차 입력입니다.")

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

if peer_kind == master_service.PEER_SIMILAR_SIZE and target.bed_count is None:
    st.warning("병상수 자료가 아직 없어 유사 규모 비교군을 만들 수 없습니다.")
elif peer_kind == master_service.PEER_CUSTOM and len(peers) < 2:
    st.info("비교할 병원을 2개 이상 고르면 비교표가 만들어집니다.")
elif not peers:
    st.info("이 조건에 맞는 비교 병원이 병원 명단에 없습니다.")
else:
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "병원": peer.canonical_name,
                    "법인": peer.foundation,
                    "지역": peer.region,
                    "종별": peer.hospital_type,
                    "설립형태": peer.ownership,
                    "병상수": peer.bed_count if peer.bed_count is not None else "자료 없음",
                }
                for peer in peers
            ]
        ),
        hide_index=True,
        width="stretch",
    )

st.subheader("주요 경영지표")
st.info(
    "회계정보공시(KHIDI) 자료는 아직 적재하지 않았습니다. 적재가 끝나면 아래 표에 실제 값이 채워지고, "
    "회계기간이 다른 병원은 별도로 표시합니다."
)

fiscal_year = st.selectbox("회계연도", [2025, 2024, 2023, 2022, 2021], index=0)
# No financial data is loaded in Phase 1, so every metric is "자료 없음" by construction.
target_metrics = metrics.compute_metrics({}, fiscal_year=fiscal_year, bed_count=target.bed_count)
peer_metric_sets = [metrics.compute_metrics({}, bed_count=peer.bed_count) for peer in peers]
rows = metrics.compare_to_peers(target_metrics, peer_metric_sets, metric_keys=HEADLINE_METRICS)
st.dataframe(
    pd.DataFrame(
        [
            {
                "지표": row.label,
                target.short_name: metrics.format_metric(row.value, row.unit),
                "비교군 평균": metrics.format_metric(row.peer_average, row.unit),
                "위치": row.position_text,
            }
            for row in rows
        ]
    ),
    hide_index=True,
    width="stretch",
)

with st.expander("전체 지표 목록 보기"):
    st.dataframe(
        pd.DataFrame(
            [
                {"지표": label, "단위": unit, "계산 방식": _formula}
                for (label, unit, _), _formula in zip(
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
                        "부채총계 ÷ 자본총계",
                        "유동자산 ÷ 유동부채",
                        "차입금 ÷ 자산총계",
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
for metric_name in TREND_METRICS:
    st.markdown(f"**{metric_name}**")
    st.caption("2021 ─ 2022 ─ 2023 ─ 2024 ─ 2025 · 회계자료 적재 후 그래프가 표시됩니다.")

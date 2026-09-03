from pathlib import Path

import pandas as pd
import streamlit as st

st.set_page_config(page_title="Phase 0 검증", page_icon="🧪", layout="wide")
st.title("Phase 0 · 데이터 가능성 조사")
st.caption("대표품목 10~20개를 기준으로 실제 공개가격 확보 가능성을 기록하는 작업표입니다.")

path = Path(__file__).resolve().parents[1] / "data" / "phase0_products.csv"
df = pd.read_csv(path)
st.dataframe(df, use_container_width=True, hide_index=True)
st.markdown(
    "**통과 기준 예시:** 동일모델 식별 가능, 출처 URL 확보, 가격·계약시점 확인, VAT/설치/옵션 등 핵심 조건의 "
    "확인 가능 여부를 품목별로 기록합니다."
)

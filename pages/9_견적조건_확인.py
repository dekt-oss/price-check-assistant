from __future__ import annotations

import tempfile
from pathlib import Path

import pandas as pd
import streamlit as st

from purchase_price.services.quote_extraction import QuoteExtractionError, extract_quote_file

st.set_page_config(page_title="견적조건 확인", page_icon="🧾", layout="wide")
st.title("견적서 상업조건 자동추출")
st.caption(
    "Excel 또는 PDF에서 명시된 VAT·배송·설치·옵션·보증·유지보수 조건을 추출합니다. "
    "문서에 없는 조건은 추정하지 않으며 업로드 파일은 영구 저장하지 않습니다."
)

with st.expander("추출 원칙", expanded=False):
    st.markdown(
        """
- 지원: `.xlsx`, `.xls`, 텍스트 PDF, 스캔 이미지형 `.pdf`
- 텍스트 PDF: 표 선/셀 구조 → 단어 X/Y 좌표 → 텍스트 fallback 순으로 처리합니다.
- 스캔 PDF: 텍스트 레이어가 없을 때만 **로컬 Tesseract(kor+eng) OCR**을 실행합니다. 문서를 외부 Vision API로 전송하지 않습니다.
- OCR은 자원 보호를 위해 앞 12페이지까지만 처리하며 오인식 가능성이 있으므로 원문 이미지 대조가 필수입니다.
- 추출: 품명/제조사/모델/규격/수량/단가/총액 + VAT/배송/설치/옵션/보증/유지보수/기타조건
- **빈 값은 `해당 없음`이 아니라 `견적서에서 확인되지 않음`**을 의미합니다.
- 자유문장을 해석해 조건을 만들어내지 않고, 명시적으로 인식된 표/문맥만 사용합니다.
        """
    )

uploaded = st.file_uploader("견적서 업로드", type=["xlsx", "xls", "pdf"])

if uploaded is None:
    st.info("견적서를 업로드하면 품목별 가격조건을 표로 확인할 수 있습니다.")
    st.stop()

suffix = Path(uploaded.name).suffix
with tempfile.NamedTemporaryFile(delete=True, suffix=suffix) as tmp:
    tmp.write(uploaded.getbuffer())
    tmp.flush()
    try:
        result = extract_quote_file(Path(tmp.name))
    except QuoteExtractionError as exc:
        st.error(str(exc))
        st.stop()

for warning in result.warnings:
    st.warning(warning)

if not result.items:
    st.info("자동 추출된 품목이 없습니다.")
    st.stop()

condition_fields = (
    "VAT",
    "배송",
    "설치",
    "옵션·부속",
    "보증",
    "유지보수",
    "기타조건",
)

rows: list[dict[str, object]] = []
for item in result.items:
    condition_values = (
        item.vat_status,
        item.delivery_condition,
        item.installation_condition,
        item.option_condition,
        item.warranty_condition,
        item.maintenance_condition,
        item.other_conditions,
    )
    known_count = sum(bool(value.strip()) for value in condition_values)
    rows.append(
        {
            "제품명": item.product_name,
            "제조사": item.manufacturer,
            "모델명": item.model_name,
            "규격": item.specification,
            "수량": float(item.quantity) if item.quantity is not None else None,
            "견적단가": float(item.unit_price) if item.unit_price is not None else None,
            "총액": float(item.total_amount) if item.total_amount is not None else None,
            "VAT": item.vat_status,
            "배송": item.delivery_condition,
            "설치": item.installation_condition,
            "옵션·부속": item.option_condition,
            "보증": item.warranty_condition,
            "유지보수": item.maintenance_condition,
            "기타조건": item.other_conditions,
            "조건명시": f"{known_count}/{len(condition_fields)}",
            "원본위치": f"{item.source_sheet} · {item.source_row}행",
        }
    )

st.success(f"{uploaded.name}: {len(rows)}개 품목을 추출했습니다.")
st.caption(
    "아래 표는 수정 가능합니다. 빈 조건은 자동으로 `포함/별도/없음`으로 추정하지 않습니다. "
    "실제 비교 전 견적서 원문과 대조하세요."
)

edited = st.data_editor(
    pd.DataFrame(rows),
    use_container_width=True,
    hide_index=True,
    num_rows="fixed",
    disabled=["조건명시", "원본위치"],
    column_config={
        "견적단가": st.column_config.NumberColumn(format="%d"),
        "총액": st.column_config.NumberColumn(format="%d"),
    },
)

st.subheader("조건 확인 요약")
condition_summary: list[dict[str, object]] = []
for field in condition_fields:
    values = edited[field].fillna("").astype(str).str.strip()
    known = int((values != "").sum())
    condition_summary.append(
        {
            "조건": field,
            "명시 품목": known,
            "전체 품목": len(edited),
            "명시율": f"{round(known / len(edited) * 100)}%" if len(edited) else "0%",
        }
    )

st.dataframe(pd.DataFrame(condition_summary), use_container_width=True, hide_index=True)
st.info(
    "다음 단계에서는 이 견적조건과 외부 가격근거의 조건을 항목별로 대조해 "
    "`quote_comparable` 가능 여부를 더 엄격하게 판단합니다."
)

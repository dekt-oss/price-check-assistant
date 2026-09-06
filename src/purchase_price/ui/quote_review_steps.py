from __future__ import annotations

import html
import tempfile
from dataclasses import replace
from pathlib import Path

import streamlit as st

from purchase_price.clients.data_go_kr import PublicDataClientError
from purchase_price.config import get_settings
from purchase_price.services.g2b_product_mapping import resolve_verified_g2b_mapping
from purchase_price.services.mfds_device_intelligence import (
    MfdsModelInfoClient,
    resolve_exact_model_identity,
)
from purchase_price.services.quote_extraction import (
    QuoteExtractionError,
    QuoteItem,
    extract_quote_file,
    parse_quote_decimal,
    quote_item_query,
)
from purchase_price.services.quote_extraction_diagnostics import (
    diagnose_quote_extraction,
    diagnose_quote_extraction_error,
)
from purchase_price.services.runtime_readiness import ocr_runtime_readiness
from purchase_price.ui.mapping_requests import register_mapping_request
from purchase_price.ui.quote_review_state import (
    QUOTE_REVIEW_STEPS,
    IdentityResult,
    QuoteReviewState,
    can_enter,
)

_STEP_CSS = """
<style>
.quote-stepper{display:flex;gap:18px;flex-wrap:wrap;margin:0 0 18px 0}
.quote-step{display:flex;align-items:center;gap:7px;color:#8a877f;font-size:13px}
.quote-step .n{width:24px;height:24px;border-radius:50%;border:2px solid #cfcbc2;display:inline-flex;align-items:center;justify-content:center;font-size:12px;font-weight:700}
.quote-step.done{color:#1f5e42}.quote-step.done .n{background:#2e7d5b;border-color:#2e7d5b;color:white}
.quote-step.now{color:#1c1b19;font-weight:700}.quote-step.now .n{border-color:#1f6f8b;color:#1f6f8b}
.quote-muted{color:#6b6862;font-size:12px}.quote-title{font-size:20px;font-weight:700}
</style>
"""


def render_stepper(state: QuoteReviewState) -> None:
    chunks: list[str] = []
    for number, label in enumerate(QUOTE_REVIEW_STEPS, start=1):
        klass = "done" if number < state.step else "now" if number == state.step else ""
        marker = "✓" if number < state.step else str(number)
        chunks.append(
            f'<div class="quote-step {klass}"><span class="n">{marker}</span>'
            f"{html.escape(label)}</div>"
        )
    st.markdown(
        _STEP_CSS + '<div class="quote-stepper">' + "".join(chunks) + "</div>",
        unsafe_allow_html=True,
    )


def render_item_list(state: QuoteReviewState) -> int:
    st.markdown(f"**품목 {len(state.items)}건**")
    if not state.items:
        st.caption("견적서를 업로드하면 품목이 표시됩니다.")
        return 0
    selected = st.radio(
        "품목 선택",
        options=list(range(len(state.items))),
        format_func=lambda index: (
            f"{index + 1}. "
            f"{state.items[index].product_name or state.items[index].model_name or '미확인 품목'}"
            + (" · 확인" if state.item_confirmed.get(index) else " · 확인 필요")
        ),
        label_visibility="collapsed",
        key="quote_review_item_selector",
    )
    item = state.items[selected]
    st.caption(
        " · ".join(
            part
            for part in (
                item.manufacturer,
                item.model_name,
                f"{item.unit_price:,.0f}원" if item.unit_price is not None else "단가 미확인",
            )
            if part
        )
    )
    return int(selected)


def render_path_card(state: QuoteReviewState) -> None:
    st.markdown("**판정으로 가는 길**")
    if state.step >= 6:
        allowed, reasons = can_enter(6, state)
    else:
        allowed, reasons = can_enter(state.step + 1, state)
    if allowed:
        st.success("현재 단계의 진입 조건을 충족했습니다.")
    else:
        for reason in reasons:
            st.warning(reason)
    st.caption("이 카드의 차단 사유는 can_enter() 반환값을 그대로 표시합니다.")


def _store_extraction(uploaded_file, state: QuoteReviewState) -> None:
    suffix = Path(uploaded_file.name).suffix.casefold()
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as handle:
        handle.write(uploaded_file.getvalue())
        temp_path = Path(handle.name)
    try:
        result = extract_quote_file(temp_path)
        diagnostics = diagnose_quote_extraction(temp_path, result)
    except QuoteExtractionError as exc:
        state.diagnostics = diagnose_quote_extraction_error(temp_path, exc)
        state.extraction = None
        state.items = []
        st.error(str(exc))
        return
    finally:
        temp_path.unlink(missing_ok=True)

    state.file_name = uploaded_file.name
    state.file_kind = suffix.lstrip(".")
    state.extraction = result
    state.diagnostics = diagnostics
    state.items = list(result.items)
    state.item_confirmed = {index: False for index in range(len(state.items))}
    state.item_notes.clear()
    state.vat_conflict = any(
        "VAT 포함" in warning and "VAT 별도" in warning for warning in result.warnings
    )
    state.identity.clear()
    state.search_runs.clear()
    state.discoveries.clear()
    state.comparability_context.clear()
    state.approvals.clear()
    state.step = 1


def render_s1(state: QuoteReviewState) -> None:
    st.subheader("1. 업로드·추출")
    uploaded = st.file_uploader("견적서 파일", type=["pdf", "xlsx", "xls"])
    if uploaded is not None and (state.file_name != uploaded.name or state.extraction is None):
        _store_extraction(uploaded, state)

    if state.extraction is None:
        st.info(
            "PDF · xlsx · xls 견적서를 업로드하세요. "
            "원본 바이트는 session state에 저장하지 않습니다."
        )
        if st.button("OCR 준비상태 확인"):
            readiness = ocr_runtime_readiness()
            if readiness.ready:
                st.success(f"스캔 PDF OCR: {readiness.status}")
            else:
                st.warning(f"스캔 PDF OCR: {readiness.status} · {readiness.detail}")
        return

    diagnostics = state.diagnostics
    with st.container(border=True):
        st.markdown("**추출 경로와 판단 근거**")
        if diagnostics is not None:
            st.write(f"추출 경로: **{diagnostics.strategy_label}**")
        st.write(f"자동 추출 품목: **{len(state.items)}건**")
        excluded = state.extraction.excluded_rows
        st.write(f"품목에서 제외한 행: **{len(excluded)}건**")
        if excluded:
            st.caption(" / ".join(excluded))

    if state.extraction.warnings:
        with st.container(border=True):
            st.markdown(f"**확인이 필요한 경고 {len(state.extraction.warnings)}건**")
            for warning in state.extraction.warnings:
                st.warning(warning)

    allowed, _ = can_enter(2, state)
    if st.button("2. 품목 확인으로", type="primary", disabled=not allowed):
        state.step = 2
        st.rerun()


def _text_decimal(value) -> str:
    return "" if value is None else format(value, "f")


def render_s2(state: QuoteReviewState, index: int) -> None:
    st.subheader("2. 품목 확인")
    if not state.items:
        st.warning("확인할 품목이 없습니다.")
        return
    item = state.items[index]
    with st.form(f"quote_item_confirm_{index}"):
        c1, c2 = st.columns(2)
        product_name = c1.text_input("품명", value=item.product_name)
        manufacturer = c2.text_input("제조사", value=item.manufacturer)
        model_name = c1.text_input("모델명", value=item.model_name)
        specification = c2.text_input("규격", value=item.specification)
        quantity = c1.text_input("수량", value=_text_decimal(item.quantity))
        unit = c2.text_input("단위", value=item.unit)
        unit_price = c1.text_input("단가", value=_text_decimal(item.unit_price))
        total_amount = c2.text_input("금액", value=_text_decimal(item.total_amount))
        vat = st.text_input(
            "VAT",
            value=item.vat_status,
            help="포함/별도/면세 등 원문 표현을 확인하세요.",
        )
        delivery = c1.text_input("배송", value=item.delivery_condition)
        installation = c2.text_input("설치", value=item.installation_condition)
        options = c1.text_input("옵션/구성", value=item.option_condition)
        warranty = c2.text_input("보증", value=item.warranty_condition)
        maintenance = c1.text_input("유지보수", value=item.maintenance_condition)
        note = c2.text_input("확인 메모", value=state.item_notes.get(index, ""))
        other = st.text_input("기타 조건", value=item.other_conditions)
        confirmed = st.form_submit_button("이 품목 확인", type="primary")

    if confirmed:
        if state.vat_conflict and not vat.strip():
            st.error("VAT 상충 경고가 있으므로 원문을 확인해 VAT 상태를 직접 입력하세요.")
            return
        state.items[index] = replace(
            item,
            product_name=product_name.strip(),
            manufacturer=manufacturer.strip(),
            model_name=model_name.strip(),
            specification=specification.strip(),
            quantity=parse_quote_decimal(quantity),
            unit=unit.strip(),
            unit_price=parse_quote_decimal(unit_price),
            total_amount=parse_quote_decimal(total_amount),
            vat_status=vat.strip(),
            delivery_condition=delivery.strip(),
            installation_condition=installation.strip(),
            option_condition=options.strip(),
            warranty_condition=warranty.strip(),
            maintenance_condition=maintenance.strip(),
            other_conditions=other.strip(),
        )
        state.item_confirmed[index] = True
        state.item_notes[index] = note.strip()
        state.reset_downstream(after_step=2)
        st.success("이 품목의 추출값을 확인했습니다.")

    allowed, reasons = can_enter(3, state)
    for reason in reasons:
        st.info(reason)
    if st.button("3. 제품 식별로", type="primary", disabled=not allowed):
        state.step = 3
        st.rerun()


def _mfds_exact_confirmed(item: QuoteItem) -> tuple[bool, str]:
    settings = get_settings()
    service_key = (settings.resolved_mfds_service_key or "").strip()
    if not service_key:
        return False, "MFDS 인증이 설정되지 않아 exact 모델 확인을 실행할 수 없습니다."
    if not item.product_name.strip() or not item.model_name.strip():
        return False, "식약처 exact 모델 확인에는 품명과 모델명이 필요합니다."
    kwargs = {
        "timeout_seconds": settings.mfds_request_timeout_seconds,
        "max_retries": settings.mfds_max_retries,
    }
    if settings.mfds_model_info_base_url:
        kwargs["base_url"] = settings.mfds_model_info_base_url
    client = MfdsModelInfoClient(service_key, **kwargs)
    try:
        records = client.search_models(item.product_name)
    except (PublicDataClientError, ValueError) as exc:
        return False, f"MFDS 조회 실패: {type(exc).__name__}"
    resolution = resolve_exact_model_identity(records, item.model_name)
    active = [record for record in resolution.exact_matches if record.active_for_domestic_candidate]
    if resolution.ambiguous:
        return False, "동일 모델명이 복수 허가번호에 걸려 자동 식별하지 않았습니다."
    if not active:
        return False, "활성 국내용 exact 모델을 확인하지 못했습니다."
    record = active[0]
    return True, f"MFDS exact 모델 확인 · 허가번호 {record.permit_number or '-'}"


def render_s3(state: QuoteReviewState, index: int) -> None:
    st.subheader("3. 제품 식별")
    item = state.items[index]
    query = quote_item_query(item)
    mapping = resolve_verified_g2b_mapping(query)
    previous = state.identity.get(index)

    with st.container(border=True):
        st.markdown("**나라장터 verified mapping**")
        if mapping is not None:
            st.success(
                f"verified · {mapping.detail_product_name or '-'} · "
                f"코드 {mapping.detail_product_code or '-'}"
            )
        else:
            st.warning(
                "현재 입력 품목에 verified G2B mapping이 없습니다. "
                "조사요청을 등록하면 다음 단계에서는 직접가격으로 승격하지 않고 "
                "미검증 후보만 별도로 탐색합니다."
            )

    research_required = bool(previous and previous.research_required)
    if mapping is None:
        if st.button("나라장터 mapping 조사요청 등록", key=f"mapping_request_{index}"):
            try:
                created = register_mapping_request(
                    product_name=item.product_name,
                    manufacturer=item.manufacturer,
                    model_name=item.model_name,
                )
            except (OSError, ValueError) as exc:
                st.error(f"조사요청 등록 실패: {type(exc).__name__}")
            else:
                research_required = True
                state.identity[index] = IdentityResult(
                    ready=False,
                    status="mapping 조사요청 등록",
                    detail="G2B verified mapping 조사요청 등록됨",
                    source="G2B",
                    mapping_verified=False,
                    research_required=True,
                )
                if created:
                    st.success("mapping 조사요청을 등록했습니다.")
                else:
                    st.info("동일 제품 식별정보의 조사요청이 이미 등록되어 있습니다.")
        if research_required:
            st.caption(
                "조사요청에는 제품명·제조사·모델명만 기록하며 견적가격·수량·조건·원문은 저장하지 않습니다."
            )
    else:
        research_required = False

    is_medical = st.checkbox(
        "이 품목은 의료기기이며 MFDS exact 모델 확인이 필요함",
        key=f"quote_medical_{index}",
    )
    previous = state.identity.get(index)
    mfds_confirmed = bool(previous and previous.mfds_confirmed)
    mfds_detail = previous.detail if previous and previous.mfds_confirmed else ""
    if is_medical and st.button("MFDS exact 모델 확인", key=f"mfds_exact_{index}"):
        mfds_confirmed, mfds_detail = _mfds_exact_confirmed(item)
        state.identity[index] = IdentityResult(
            ready=False,
            status="MFDS exact 확인" if mfds_confirmed else "MFDS 확인 필요",
            detail=mfds_detail,
            source="MFDS",
            mapping_verified=mapping is not None,
            mfds_confirmed=mfds_confirmed,
            research_required=research_required,
        )
        if mfds_confirmed:
            st.success(mfds_detail)
        else:
            st.error(mfds_detail)

    base_ready = mapping is not None or research_required
    ready = base_ready and (not is_medical or mfds_confirmed)
    if st.button("제품 식별 상태 저장", type="primary", key=f"save_identity_{index}"):
        state.reset_downstream(after_step=3)
        state.identity[index] = IdentityResult(
            ready=ready,
            status="식별 완료" if ready else "식별 확인 필요",
            detail=mfds_detail or ("G2B verified mapping 조사요청 등록됨" if research_required else ""),
            source="MFDS+G2B" if is_medical else "G2B",
            mapping_verified=mapping is not None,
            mfds_confirmed=mfds_confirmed,
            research_required=research_required,
        )
        if ready:
            st.success("제품 식별 단계를 완료했습니다.")
        else:
            st.warning("식별 조건이 아직 충족되지 않았습니다.")

    allowed, reasons = can_enter(4, state)
    for reason in reasons:
        st.info(reason)
    if st.button("4. 근거 수집으로", type="primary", disabled=not allowed):
        state.step = 4
        st.rerun()

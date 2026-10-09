from __future__ import annotations

import html
import logging
from dataclasses import replace

import streamlit as st

from purchase_price.clients.data_go_kr import PublicDataClientError
from purchase_price.config import get_settings
from purchase_price.services.g2b_product_mapping import resolve_verified_g2b_mapping
from purchase_price.services.mfds_api_keys import (
    mfds_model_info_json_client,
    mfds_service_key_candidates,
)
from purchase_price.services.mfds_device_intelligence import (
    MfdsModelInfoClient,
    resolve_exact_model_identity,
)
from purchase_price.services.product_matching import (
    ManufacturerAliasError,
    canonical_manufacturer,
    load_manufacturer_aliases,
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
from purchase_price.services.quote_upload_security import temporary_quote_upload
from purchase_price.services.runtime_readiness import ocr_runtime_readiness
from purchase_price.ui.mapping_requests import register_mapping_request
from purchase_price.ui.quote_review_contract import (
    build_extracted_item_snippet,
    build_manual_quote_item,
    changed_item_field_labels,
)
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
        if state.extraction is not None:
            st.caption("자동 추출 품목이 없습니다. 2단계에서 수동 품목을 입력하세요.")
        else:
            st.caption("견적서를 업로드하면 품목이 표시됩니다.")
        return 0
    selected = st.radio(
        "품목 선택",
        options=list(range(len(state.items))),
        format_func=lambda index: (
            f"{index + 1}. "
            f"{state.items[index].product_name or state.items[index].model_name or '미확인 품목'}"
            + (" · 검증 완료" if state.item_confirmed.get(index) else " · 검증 전")
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
    st.markdown("**다음 단계로 가려면**")
    if state.step >= 6:
        allowed, reasons = can_enter(6, state)
    else:
        allowed, reasons = can_enter(state.step + 1, state)
    if allowed:
        st.success("다음 단계로 넘어갈 수 있습니다.")
    else:
        for reason in reasons:
            st.warning(reason)
    st.caption("위 안내를 마치면 다음 단계로 넘어갈 수 있습니다.")


QUOTE_REVIEW_ACCEPTANCE_V2 = True
READ_ERROR_SESSION_KEY = "quote_review_read_error_v1"

_READ_ERROR_BY_KIND = {
    "xlsx": "엑셀 파일이 손상됐거나 다른 형식입니다. 엑셀에서 다시 저장하거나 PDF로 올려 주세요.",
    "xls": "엑셀 파일이 손상됐거나 다른 형식입니다. 엑셀에서 .xlsx로 다시 저장하거나 PDF로 올려 주세요.",
    "pdf": (
        "PDF에서 견적 내용을 읽지 못했습니다. 파일이 손상됐거나 글자를 알아볼 수 없는 스캔본일 수 있습니다. "
        "엑셀 원본이나 더 선명한 PDF로 다시 올려 주세요."
    ),
    "image": (
        "사진에서 견적 내용을 읽지 못했습니다. 더 선명한 사진을 올리거나 PDF·엑셀로 저장해 올려 주세요."
    ),
}
_READ_ERROR_UNKNOWN = (
    "이 파일은 읽을 수 없는 형식입니다. 엑셀(.xlsx/.xls), PDF, PNG, JPG 견적서를 올려 주세요."
)
_log = logging.getLogger(__name__)


def friendly_read_error(file_name: str) -> str:
    """Plain Korean reason a quote file could not be read; the technical cause goes to the log."""

    suffix = file_name.rsplit(".", 1)[-1].casefold() if "." in file_name else ""
    if suffix in {"png", "jpg", "jpeg"}:
        suffix = "image"
    return _READ_ERROR_BY_KIND.get(suffix, _READ_ERROR_UNKNOWN)


def _store_extraction(uploaded_file, state: QuoteReviewState, *, show_error: bool = True) -> None:
    suffix = uploaded_file.name.rsplit(".", 1)[-1].casefold() if "." in uploaded_file.name else ""
    st.session_state.pop(READ_ERROR_SESSION_KEY, None)

    def fail(exc: Exception) -> None:
        # The reader sees only the Korean sentence; the cause stays in the server log.
        _log.warning("quote read failed (%s): %s: %s", suffix or "?", type(exc).__name__, exc)
        state.extraction = None
        state.items = []
        message = friendly_read_error(uploaded_file.name)
        st.session_state[READ_ERROR_SESSION_KEY] = message
        if show_error:
            st.error(message)

    try:
        with temporary_quote_upload(uploaded_file) as temp_path:
            try:
                result = extract_quote_file(temp_path)
                diagnostics = diagnose_quote_extraction(temp_path, result)
            except QuoteExtractionError as exc:
                state.diagnostics = diagnose_quote_extraction_error(temp_path, exc)
                fail(exc)
                return
            except Exception as exc:  # noqa: BLE001 - any parser crash is a read failure for the reader
                fail(exc)
                return
    except ValueError as exc:
        fail(exc)
        return

    state.file_name = uploaded_file.name
    state.file_kind = suffix
    state.extraction = result
    state.diagnostics = diagnostics
    state.items = list(result.items)
    state.item_confirmed = {index: False for index in range(len(state.items))}
    state.item_notes.clear()
    state.condition_notes.clear()
    state.vat_conflict = any(
        "VAT 포함" in warning and "VAT 별도" in warning for warning in result.warnings
    )
    state.identity.clear()
    state.search_runs.clear()
    state.discoveries.clear()
    state.market_bundles.clear()
    state.track_b_db.clear()
    state.mfds_workspace.clear()
    state.mfds_identity.clear()
    state.safety_lookup.clear()
    state.item_research_failures.clear()
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
            st.dataframe(
                [
                    {
                        "라벨": row.label,
                        "원문 위치": f"{row.source_sheet} {row.source_row}행",
                        "금액": f"{row.amount:,.0f}원" if row.amount is not None else "미확인",
                    }
                    for row in excluded
                ],
                use_container_width=True,
                hide_index=True,
            )

    if state.extraction.warnings:
        with st.container(border=True):
            st.markdown(f"**확인이 필요한 경고 {len(state.extraction.warnings)}건**")
            for warning in state.extraction.warnings:
                st.warning(warning)

    if not state.items:
        st.warning(
            "자동 추출 품목이 0건입니다. 2단계에서 품목을 직접 입력한 뒤 원문 대조를 완료해야 합니다."
        )

    allowed, _ = can_enter(2, state)
    next_label = "2. 수동 품목 입력으로" if not state.items else "2. 품목 확인으로"
    if st.button(next_label, type="primary", disabled=not allowed):
        state.step = 2
        st.rerun()


def _text_decimal(value) -> str:
    return "" if value is None else format(value, "f")


def _render_manual_item_form(state: QuoteReviewState) -> None:
    st.warning("자동 추출 결과가 없습니다. 원문을 보면서 품목을 직접 입력하세요.")
    with st.form("quote_manual_item"):
        c1, c2 = st.columns(2)
        product_name = c1.text_input("품명")
        manufacturer = c2.text_input("제조사")
        model_name = c1.text_input("모델명")
        specification = c2.text_input("규격")
        quantity = c1.text_input("수량")
        unit = c2.text_input("단위")
        unit_price = c1.text_input("단가")
        total_amount = c2.text_input("금액")
        vat = c1.text_input("VAT")
        delivery = c2.text_input("배송")
        installation = c1.text_input("설치")
        options = c2.text_input("옵션/구성")
        warranty = c1.text_input("보증")
        maintenance = c2.text_input("유지보수")
        other = st.text_input("기타 조건")
        submitted = st.form_submit_button("수동 품목 추가", type="primary")
    if not submitted:
        return
    try:
        item = build_manual_quote_item(
            product_name=product_name,
            manufacturer=manufacturer,
            model_name=model_name,
            specification=specification,
            quantity=parse_quote_decimal(quantity),
            unit=unit,
            unit_price=parse_quote_decimal(unit_price),
            total_amount=parse_quote_decimal(total_amount),
            vat_status=vat,
            delivery_condition=delivery,
            installation_condition=installation,
            option_condition=options,
            warranty_condition=warranty,
            maintenance_condition=maintenance,
            other_conditions=other,
        )
    except ValueError as exc:
        st.error(str(exc))
        return
    state.items = [item]
    state.item_confirmed = {0: False}
    state.item_notes = {0: "자동 추출 0건 — 담당자 수동 입력"}
    state.condition_notes = {0: {}}
    state.reset_downstream(after_step=2)
    st.success("수동 품목을 추가했습니다. 이제 원문 대조 완료를 확인하세요.")
    st.rerun()


def render_s2(state: QuoteReviewState, index: int) -> None:
    st.subheader("2. 품목 확인")
    if not state.items:
        _render_manual_item_form(state)
        return

    item = state.items[index]
    original = (
        state.extraction.items[index]
        if state.extraction is not None and index < len(state.extraction.items)
        else None
    )
    if original is not None:
        st.caption(f"원문 위치: {original.source_sheet} {original.source_row}행")
        with st.expander("견적서에서 자동으로 읽은 행", expanded=True):
            st.code(build_extracted_item_snippet(original), language=None)
        changed = changed_item_field_labels(original, item)
        if changed:
            st.info("수정된 필드: " + ", ".join(changed))
    else:
        st.caption("수동 입력 품목입니다. 업로드 원문을 직접 보면서 모든 필드를 확인하세요.")

    condition_notes = state.condition_notes.get(index, {})
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
        note = c2.text_input(
            "원문 대조/수정 근거 메모",
            value=state.item_notes.get(index, ""),
        )
        other = st.text_input("기타 조건", value=item.other_conditions)
        st.markdown("**거래 조건별 원문 메모**")
        n1, n2 = st.columns(2)
        vat_note = n1.text_input("VAT 근거", value=condition_notes.get("vat", ""))
        delivery_note = n2.text_input("배송 근거", value=condition_notes.get("delivery", ""))
        installation_note = n1.text_input(
            "설치 근거", value=condition_notes.get("installation", "")
        )
        options_note = n2.text_input("옵션 근거", value=condition_notes.get("options", ""))
        warranty_note = n1.text_input("보증 근거", value=condition_notes.get("warranty", ""))
        maintenance_note = n2.text_input(
            "유지보수 근거", value=condition_notes.get("maintenance", "")
        )
        source_checked = st.checkbox(
            "업로드 원문과 추출·수정값을 직접 대조했습니다.",
            value=state.item_confirmed.get(index, False),
        )
        confirmed = st.form_submit_button("이 품목 확인", type="primary")

    if confirmed:
        if not source_checked:
            st.error("원문 대조 완료를 확인해야 이 품목을 완료할 수 있습니다.")
            return
        if state.vat_conflict and not vat.strip():
            st.error("부가세(VAT) 표기가 서로 달라 보입니다. 원문을 확인해 부가세 포함 여부를 직접 입력하세요.")
            return
        updated = replace(
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
        state.items[index] = updated
        state.item_confirmed[index] = True
        state.item_notes[index] = note.strip()
        state.condition_notes[index] = {
            "vat": vat_note.strip(),
            "delivery": delivery_note.strip(),
            "installation": installation_note.strip(),
            "options": options_note.strip(),
            "warranty": warranty_note.strip(),
            "maintenance": maintenance_note.strip(),
        }
        state.reset_downstream(after_step=2)
        st.success("이 품목의 추출·수정값을 원문과 대조해 확인했습니다.")
        if original is not None:
            changed = changed_item_field_labels(original, updated)
            if changed:
                st.info("수정된 필드: " + ", ".join(changed))

    allowed, reasons = can_enter(3, state)
    for reason in reasons:
        st.info(reason)
    if st.button("3. 제품 식별로", type="primary", disabled=not allowed):
        state.step = 3
        st.rerun()


def _mfds_exact_confirmed(item: QuoteItem) -> tuple[bool, str]:
    settings = get_settings()
    service_key = (mfds_service_key_candidates(settings) or ("",))[0]
    if not service_key:
        return False, "식약처 조회 설정이 없어 허가 목록 확인을 할 수 없습니다."
    if not item.product_name.strip() or not item.model_name.strip():
        return False, "식약처 허가 목록 확인에는 품명과 모델명이 필요합니다."
    kwargs = {
        "timeout_seconds": settings.mfds_request_timeout_seconds,
        "max_retries": settings.mfds_max_retries,
    }
    if settings.mfds_model_info_base_url:
        kwargs["base_url"] = settings.mfds_model_info_base_url
    client = MfdsModelInfoClient(service_key, client=mfds_model_info_json_client(settings), **kwargs)
    try:
        records = client.search_models(item.product_name)
    except (PublicDataClientError, ValueError):
        return False, "식약처 조회에 실패했습니다. 잠시 뒤 다시 시도하세요."
    resolution = resolve_exact_model_identity(records, item.model_name)
    active = [record for record in resolution.exact_matches if record.active_for_domestic_candidate]
    if resolution.ambiguous:
        return False, "같은 모델명이 여러 허가번호에 걸려 있어 자동으로 확인하지 않았습니다."
    if not active:
        return False, "허가 목록에서 국내용으로 정상 등록된 같은 모델을 찾지 못했습니다."
    record = active[0]
    return True, f"식약처 허가 목록에서 같은 모델 확인 · 허가번호 {record.permit_number or '-'}"


def render_s3(state: QuoteReviewState, index: int) -> None:
    st.subheader("3. 제품 식별")
    item = state.items[index]
    query = quote_item_query(item)
    mapping = resolve_verified_g2b_mapping(query)
    previous = state.identity.get(index)

    aliases = None
    with st.container(border=True):
        st.markdown("**제조사 이름 맞춰 보기**")
        try:
            aliases = load_manufacturer_aliases()
            canonical = canonical_manufacturer(item.manufacturer, aliases)
        except ManufacturerAliasError:
            st.warning("제조사 이름 목록을 불러오지 못했습니다.")
        else:
            st.write(f"견적 표기: **{item.manufacturer or '미확인'}**")
            st.write(f"표준 이름: **{canonical or '미확인'}**")

    with st.container(border=True):
        st.markdown("**나라장터 등록 제품과의 연결**")
        if mapping is not None:
            st.success(
                f"연결 확인됨 · {mapping.detail_product_name or '-'} · "
                f"코드 {mapping.detail_product_code or '-'}"
            )
        else:
            st.warning(
                "이 품목은 나라장터 등록 제품과 아직 연결되어 있지 않습니다. "
                "조사 요청을 등록하면 담당자가 확인할 때까지 이름이 비슷한 후보만 따로 찾아 보여줍니다."
            )

    research_required = bool(previous and previous.research_required)
    if mapping is None:
        if st.button("나라장터 제품 연결 조사 요청하기", key=f"mapping_request_{index}"):
            try:
                created = register_mapping_request(
                    product_name=item.product_name,
                    manufacturer=item.manufacturer,
                    model_name=item.model_name,
                )
            except (OSError, ValueError):
                st.error("조사 요청을 등록하지 못했습니다. 잠시 뒤 다시 시도하세요.")
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
                    st.success("조사 요청을 등록했습니다.")
                else:
                    st.info("같은 제품 정보로 이미 조사 요청이 등록되어 있습니다.")
        if research_required:
            st.caption(
                "조사요청에는 제품명·제조사·모델명만 기록하며 견적가격·수량·조건·원문은 저장하지 않습니다."
            )
    else:
        research_required = False

    is_medical = st.checkbox(
        "의료기기라서 식약처 허가 목록에서 같은 모델인지 확인해야 함",
        key=f"quote_medical_{index}",
    )
    previous = state.identity.get(index)
    mfds_confirmed = bool(previous and previous.mfds_confirmed)
    mfds_detail = previous.detail if previous and previous.mfds_confirmed else ""
    if is_medical and st.button("식약처 허가 목록에서 확인", key=f"mfds_exact_{index}"):
        mfds_confirmed, mfds_detail = _mfds_exact_confirmed(item)
        state.identity[index] = IdentityResult(
            ready=False,
            status="식약처 허가 확인" if mfds_confirmed else "식약처 허가 미확인",
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
            status="식별 완료" if ready else "식별 전",
            detail=mfds_detail or ("G2B verified mapping 조사요청 등록됨" if research_required else ""),
            source="MFDS+G2B" if is_medical else "G2B",
            mapping_verified=mapping is not None,
            mfds_confirmed=mfds_confirmed,
            research_required=research_required,
        )
        if ready:
            st.success("제품 식별 단계를 완료했습니다.")
        else:
            st.warning("아직 조건이 채워지지 않았습니다. 위 안내를 먼저 마치세요.")

    allowed, reasons = can_enter(4, state)
    for reason in reasons:
        st.info(reason)
    if st.button("4. 근거 수집으로", type="primary", disabled=not allowed):
        state.step = 4
        st.rerun()

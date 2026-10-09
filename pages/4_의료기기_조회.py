from datetime import datetime

import pandas as pd
import streamlit as st

from purchase_price.clients.data_go_kr import PublicDataClientError
from purchase_price.collectors.g2b_shopping import G2B_SHOPPING_BASE_URL, SOURCE_NAME
from purchase_price.collectors.registry import build_collectors
from purchase_price.config import get_settings
from purchase_price.schemas import ProductQuery
from purchase_price.services.g2b_unmapped_discovery import discover_unmapped_g2b_candidates
from purchase_price.services.market_research_support import (
    alternative_research_gate,
    build_alternative_web_search_links,
    build_web_supplier_search_links,
    extract_g2b_supplier_candidates,
    extract_mfds_business_supplier_candidates,
)
from purchase_price.services.medical_lookup_handoff import (
    WIDGET_MANUFACTURER,
    WIDGET_MODEL,
    WIDGET_PRODUCT,
    WIDGET_UDI,
    apply_handoff,
)
from purchase_price.services.mfds_api_keys import (
    mfds_json_client,
    mfds_model_info_json_client,
    mfds_service_key_candidates,
)
from purchase_price.services.mfds_device_intelligence import (
    MFDS_BUSINESS_LICENSE_BASE_URL,
    MFDS_MODEL_INFO_BASE_URL,
    MfdsBusinessLicenseClient,
    MfdsModelInfoClient,
    resolve_exact_model_identity,
)
from purchase_price.services.mfds_recall import lookup_mfds_recall
from purchase_price.services.mfds_udi import MFDS_UDI_CODE_BASE_URL, MfdsUdiCodeClient
from purchase_price.services.safety_support import (
    MFDS_ADMIN_SANCTION_PAGE_URL,
    MFDS_RECALL_PAGE_URL,
    MFDS_SAFETY_LETTER_PAGE_URL,
    MFDS_UDI_PORTAL_URL,
)
from purchase_price.services.search import search_all
from purchase_price.ui import device_page as dev
from purchase_price.ui.production_runtime_compat import (
    mfds_recall_exception_result,
    normalize_mfds_recall_lookup,
)
from purchase_price.ui.theme import metric_card_html, page_header_html

st.set_page_config(page_title=dev.PAGE_TITLE, page_icon="🏥", layout="wide")
st.markdown(dev.DEVICE_CSS, unsafe_allow_html=True)
st.markdown(page_header_html(dev.PAGE_TITLE, subtitle=dev.PAGE_SUBTITLE), unsafe_allow_html=True)

settings = get_settings()
mfds_key = (mfds_service_key_candidates(settings) or ("",))[0]
g2b_key = (settings.resolved_g2b_service_key or "").strip()
st.markdown(
    dev.connection_chips_html(mfds_ready=bool(mfds_key), g2b_ready=bool(g2b_key)),
    unsafe_allow_html=True,
)

handoff = apply_handoff(st.session_state)
if handoff is not None:
    filled = " · ".join(
        part
        for part in (
            str(handoff.get("product_name") or ""),
            str(handoff.get("model_name") or ""),
            ", ".join(handoff.get("permit_numbers") or ()),
        )
        if part
    )
    st.markdown(
        dev.handoff_notice_html(str(handoff.get("source") or ""), filled), unsafe_allow_html=True
    )

# Results live in session state so a retry button or another widget rerun does not repeat API calls.
MARKET_SLOT = "device_market_v1"
RECALL_SLOT = "device_recall_v1"
COMPANY_SLOT = "device_company_v1"
UDI_SLOT = "device_udi_v1"


def _request_retry(slot: str) -> None:
    st.session_state[f"{slot}::retry"] = True


def _params_to_run(slot: str, submitted: bool, params: object) -> object | None:
    """The parameters to look up now: a fresh submit, or the saved ones after a retry click."""

    retry = bool(st.session_state.pop(f"{slot}::retry", False))
    if submitted:
        return params
    saved = st.session_state.get(slot)
    if retry and saved:
        return saved["params"]
    return None


def _retry_button(slot: str, suffix: str = "") -> None:
    st.button(
        dev.RETRY_BUTTON,
        key=f"{slot}::retry_button::{suffix}",
        on_click=_request_retry,
        args=(slot,),
    )


def _table(rows: list[dict[str, object]] | list[dict[str, str]], **kwargs: object) -> None:
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True, **kwargs)


def _lookup_recall(model_name: str, product_name: str) -> object:
    """Recall lookup that always returns a state; a crash becomes "확인하지 못함", never "0건"."""

    try:
        return normalize_mfds_recall_lookup(
            lookup_mfds_recall(model_name=model_name, product_name=product_name)
        )
    except Exception as exc:  # noqa: BLE001 - safety is its own axis; show a failed state instead
        return mfds_recall_exception_result(exc, model_name=model_name, product_name=product_name)


def _model_info_client() -> MfdsModelInfoClient:
    return MfdsModelInfoClient(
        mfds_key,
        client=mfds_model_info_json_client(settings),
        base_url=settings.mfds_model_info_base_url or MFDS_MODEL_INFO_BASE_URL,
        timeout_seconds=settings.mfds_request_timeout_seconds,
        max_retries=settings.mfds_max_retries,
    )


def _business_client() -> MfdsBusinessLicenseClient:
    return MfdsBusinessLicenseClient(
        mfds_key,
        client=mfds_json_client(settings),
        base_url=settings.mfds_business_license_base_url or MFDS_BUSINESS_LICENSE_BASE_URL,
        timeout_seconds=settings.mfds_request_timeout_seconds,
        max_retries=settings.mfds_max_retries,
    )


def _collect_market(params: dev.MarketParams, step) -> dev.MarketResult:
    """Run the 허가·시장조사 lookups. Each source fails on its own and says so."""

    result = dev.MarketResult(params=params, checked_at=datetime.now().strftime("%m-%d %H:%M"))
    step("식약처 등록 자료에서 품목을 찾는 중입니다.")
    try:
        result.records = tuple(_model_info_client().search_models(params.product_name))
    except (PublicDataClientError, ValueError) as exc:
        result.records_error = dev.safe_error_text(exc) or "응답을 받지 못했습니다"

    step("회수·판매중지 정보를 확인하는 중입니다.")
    result.recall = _lookup_recall(params.model_name, params.product_name)

    if result.records_failed:
        return result

    exact = resolve_exact_model_identity(result.records, params.model_name) if params.model_name else None
    result.exact = exact
    exact_ready = bool(exact and exact.confirmed and not exact.ambiguous)

    if params.manufacturer:
        step("식약처 업체 허가·신고를 확인하는 중입니다.")
        businesses = ()
        try:
            businesses = _business_client().search_company(params.manufacturer)
        except (PublicDataClientError, ValueError) as exc:
            result.business_error = dev.safe_error_text(exc) or "응답을 받지 못했습니다"
        for candidate in extract_mfds_business_supplier_candidates(businesses):
            result.supplier_rows.append(
                {
                    "업체": candidate.name,
                    "자료 출처": candidate.source.value,
                    "설명": dev.supplier_evidence_text(candidate.evidence),
                }
            )

    if exact_ready and g2b_key:
        step("나라장터 납품·가격 사례를 확인하는 중입니다. 1~2분 걸릴 수 있습니다.")
        query = ProductQuery(
            product_name=params.product_name,
            manufacturer=params.manufacturer,
            model_name=params.model_name,
            specification=params.specification,
        )
        try:
            run = search_all(query, build_collectors())
        except Exception as exc:  # noqa: BLE001 - one source must not blank the whole page
            result.procurement_error = dev.safe_error_text(exc) or "응답을 받지 못했습니다"
            return result
        result.procurement = run
        for candidate in extract_g2b_supplier_candidates(run.results):
            result.supplier_rows.append(
                {
                    "업체": candidate.name,
                    "자료 출처": candidate.source.value,
                    "설명": dev.supplier_evidence_text(candidate.evidence),
                }
            )
        g2b_status = next(
            (s for s in run.source_statuses if s.source_name == SOURCE_NAME),
            None,
        )
        research_needed = bool(
            g2b_status is not None
            and (g2b_status.skipped or (g2b_status.succeeded and g2b_status.result_count == 0))
        )
        if research_needed:
            step("나라장터에서 비슷한 후보를 찾는 중입니다.")
            try:
                result.discovery = discover_unmapped_g2b_candidates(
                    query,
                    service_key=g2b_key,
                    lookback_days=365,
                    base_url=settings.g2b_shopping_base_url or G2B_SHOPPING_BASE_URL,
                    timeout_seconds=settings.g2b_request_timeout_seconds,
                    max_retries=settings.g2b_max_retries,
                    pages_per_term_window=2,
                )
            except Exception as exc:  # noqa: BLE001
                result.procurement_error = dev.safe_error_text(exc) or "응답을 받지 못했습니다"
    elif params.model_name and not exact_ready:
        result.procurement_note = (
            "입력한 모델과 정확히 같은 등록을 확인하지 못해 나라장터 납품 사례는 찾지 않았습니다."
        )
    return result


def _render_market(result: dev.MarketResult) -> None:
    params = result.params
    recall = dev.recall_view(result.recall, searched=params.model_name or params.product_name)

    # 1. A recall / sale-stop hit goes above everything else.
    if recall.is_hit:
        st.markdown(recall.banner, unsafe_allow_html=True)

    st.markdown(dev.searched_chips_html(params, result.checked_at), unsafe_allow_html=True)
    st.markdown(dev.permit_summary_cards(result), unsafe_allow_html=True)

    if recall.is_hit:
        with st.expander(f"회수·판매중지 정보 {len(recall.rows)}건 보기", expanded=True):
            _table(list(recall.rows))
            st.markdown(
                '<div class="pc-dev-hint">회수 기록에는 허가번호가 없어 모델명·품목명이 비슷한 정보를 보여줍니다. '
                "우리가 쓰는 제품이 대상인지는 원문에서 확인하세요.</div>",
                unsafe_allow_html=True,
            )
    elif recall.notice and recall.state != "none" and not (result.records_failed and recall.state == "failed"):
        st.markdown(recall.notice, unsafe_allow_html=True)
        if recall.state == "failed":
            _retry_button(MARKET_SLOT, "recall")

    # 2. Registered items.
    st.markdown(
        dev.section_html(
            "식약처 등록 품목",
            "식약처에 등록된 품목명으로 찾은 허가 목록입니다. 모델명이 같은 등록이 맨 위에 옵니다.",
        ),
        unsafe_allow_html=True,
    )
    if result.records_failed:
        st.markdown(
            dev.lookup_failed_html("식약처 허가정보", result.records_error), unsafe_allow_html=True
        )
        _retry_button(MARKET_SLOT, "records")
        return
    if not result.records:
        st.markdown(dev.permit_not_found_html(params), unsafe_allow_html=True)
    else:
        _table(dev.permit_rows(result.records, params.model_name))
        st.markdown(dev.identity_notice_html(params.model_name, result.exact), unsafe_allow_html=True)
        if not result.active_count:
            st.markdown(
                dev.idle_html(
                    "효력 있는 국내용 등록이 없습니다.",
                    "찾은 등록은 모두 취소됐거나 수출 전용입니다. 다른 품목명으로 다시 찾아 보세요.",
                    dev.TONE_WARN,
                ),
                unsafe_allow_html=True,
            )

    # 3. Public delivery / price cases from 나라장터.
    if result.procurement is not None or result.procurement_error or result.procurement_note:
        st.markdown(
            dev.section_html(
                "나라장터 납품·가격 사례",
                "공개된 납품·구매 기록입니다. ‘같은 제품으로 확인’된 것만 가격 비교에 쓸 수 있습니다.",
            ),
            unsafe_allow_html=True,
        )
        _render_procurement(result)

    # 4. Companies (only when there is something to say about them).
    if result.supplier_rows or result.business_error or params.manufacturer:
        st.markdown(
            dev.section_html("업체·납품업체", "식약처 허가·신고와 나라장터 납품 기록에서 찾은 업체입니다."),
            unsafe_allow_html=True,
        )
    if result.business_error:
        st.markdown(
            dev.lookup_failed_html("식약처 업체 허가·신고", result.business_error),
            unsafe_allow_html=True,
        )
        _retry_button(MARKET_SLOT, "business")
    if result.supplier_rows:
        _table(result.supplier_rows)
        st.markdown(f'<div class="pc-dev-hint">{dev.SUPPLIER_NOTE}</div>', unsafe_allow_html=True)
    elif not result.business_error and params.manufacturer:
        st.markdown(dev.company_not_found_html(params.manufacturer), unsafe_allow_html=True)

    # 5. Where to look next.
    st.markdown(dev.section_html("더 찾아볼 곳"), unsafe_allow_html=True)
    gate = alternative_research_gate(result.active_count)
    if gate.enabled:
        st.markdown(
            dev.idle_html(
                "효력 있는 국내용 등록이 없어 대신 쓸 장비를 찾아볼 수 있습니다.",
                "아래 웹 검색 결과는 후보일 뿐 같은 제품이 아닙니다.",
            ),
            unsafe_allow_html=True,
        )
        for label, url in build_alternative_web_search_links(
            product_name=params.product_name,
            intended_use=params.intended_use,
            key_specification=params.specification,
        ):
            st.link_button(label.replace("웹 · ", "웹에서 "), url)
    links = build_web_supplier_search_links(params.product_name, params.model_name)
    if links:
        columns = st.columns(len(links))
        for column, (label, url) in zip(columns, links, strict=False):
            column.link_button(label.replace("웹 · ", "웹에서 "), url, use_container_width=True)


def _render_procurement(result: dev.MarketResult) -> None:
    params = result.params
    if result.procurement_error:
        st.markdown(
            dev.lookup_failed_html("나라장터 납품·가격 사례", result.procurement_error),
            unsafe_allow_html=True,
        )
        _retry_button(MARKET_SLOT, "procurement")
    if result.procurement_note:
        st.markdown(
            dev.idle_html("나라장터 납품 사례는 찾지 않았습니다.", result.procurement_note),
            unsafe_allow_html=True,
        )
    run = result.procurement
    if run is None:
        return
    state, detail = dev.procurement_state(run)
    if state == "found":
        st.markdown(dev.procurement_partial_notice(run), unsafe_allow_html=True)
        st.dataframe(
            pd.DataFrame(dev.procurement_rows(run.results)),
            use_container_width=True,
            hide_index=True,
            column_config={
                "1개당 가격(원)": st.column_config.NumberColumn(format="%d"),
                "원문 링크": st.column_config.LinkColumn(display_text="원문 열기"),
            },
        )
    elif state == "failed":
        st.markdown(dev.lookup_failed_html("나라장터 납품·가격 사례", detail), unsafe_allow_html=True)
        _retry_button(MARKET_SLOT, "procurement-run")
    elif state == "empty":
        st.markdown(dev.procurement_empty_html(params), unsafe_allow_html=True)
    discovery = result.discovery
    if discovery is None:
        return
    d_state = dev.discovery_state(discovery)
    if d_state == "failed":
        st.markdown(
            dev.lookup_failed_html("나라장터 비슷한 후보"),
            unsafe_allow_html=True,
        )
        _retry_button(MARKET_SLOT, "discovery")
        return
    if d_state == "partial":
        st.markdown(
            dev.lookup_failed_html("나라장터 비슷한 후보 일부"), unsafe_allow_html=True
        )
        _retry_button(MARKET_SLOT, "discovery-partial")
    if d_state == "empty":
        st.markdown(
            dev.not_found_html("나라장터 비슷한 후보", ("모델명 철자를 확인하거나 품목명만으로 다시 찾아 보세요",)),
            unsafe_allow_html=True,
        )
        return
    with st.expander("비슷한 후보 보기 (같은 제품인지 확인 전)", expanded=True):
        st.dataframe(
            pd.DataFrame(dev.discovery_rows(discovery)),
            use_container_width=True,
            hide_index=True,
            column_config={"표기 금액(원)": st.column_config.NumberColumn(format="%d")},
        )
        st.markdown(
            '<div class="pc-dev-hint">입력한 모델의 등록을 확인했다는 것과, 위 후보가 같은 제품이라는 것은 다릅니다. '
            "후보의 금액은 가격 비교와 견적 판단에 넣지 않습니다.</div>",
            unsafe_allow_html=True,
        )


market_tab, safety_tab, udi_tab = st.tabs(list(dev.TAB_NAMES))

with market_tab:
    st.markdown(
        dev.section_html(
            "의료기기 허가정보와 납품사례",
            "식약처에 등록된 품목명으로 찾고, 모델명을 적으면 정확히 같은 모델만 같은 제품으로 확인합니다.",
        ),
        unsafe_allow_html=True,
    )
    if not mfds_key:
        st.markdown(dev.missing_key_notice_html("식약처 허가정보"), unsafe_allow_html=True)

    with st.form("medical-market-search"):
        c1, c2 = st.columns(2)
        product_name = c1.text_input(
            "품목명 (식약처에 등록된 이름)", placeholder="예: 심장충격기", key=WIDGET_PRODUCT
        )
        model_name = c2.text_input("모델명 (선택)", placeholder="예: Efficia DFM100", key=WIDGET_MODEL)
        d1, d2, d3 = st.columns(3)
        manufacturer = d1.text_input("제조·수입업체 (선택)", key=WIDGET_MANUFACTURER)
        specification = d2.text_input("규격 (선택)")
        intended_use = d3.text_input(
            "용도 (선택)",
            help="같은 품목의 국내용 등록이 없을 때만, 대신 쓸 장비를 웹에서 찾는 데 씁니다.",
        )
        search_submitted = st.form_submit_button(
            dev.SEARCH_BUTTON, type="primary", disabled=not bool(mfds_key)
        )

    market_params = dev.MarketParams(
        product_name=product_name.strip(),
        model_name=model_name.strip(),
        manufacturer=manufacturer.strip(),
        specification=specification.strip(),
        intended_use=intended_use.strip(),
    )
    if search_submitted and not market_params.product_name:
        st.session_state.pop(MARKET_SLOT, None)
        st.markdown(
            dev.idle_html(
                "품목명을 넣어 주세요.",
                "식약처에 등록된 이름 그대로 넣습니다 (예: 심장충격기).",
                dev.TONE_WARN,
            ),
            unsafe_allow_html=True,
        )
    else:
        to_run = _params_to_run(MARKET_SLOT, search_submitted, market_params)
        if isinstance(to_run, dev.MarketParams):
            with st.status("식약처 자료를 확인하는 중입니다.", expanded=True) as status:
                collected = _collect_market(
                    to_run, lambda text: (status.update(label=text), st.write(text))
                )
                failed = collected.records_failed
                status.update(
                    label=(
                        "일부를 확인하지 못했습니다. 아래 안내를 확인하세요."
                        if failed or collected.procurement_error
                        else "확인을 마쳤습니다."
                    ),
                    state="error" if failed else "complete",
                    expanded=False,
                )
            st.session_state[MARKET_SLOT] = {"params": to_run, "result": collected}
        saved_market = st.session_state.get(MARKET_SLOT)
        if saved_market:
            _render_market(saved_market["result"])
        elif mfds_key:
            st.markdown(
                dev.idle_html(
                    "아직 조회하지 않았습니다.",
                    f"품목명을 넣고 ‘{dev.SEARCH_BUTTON}’을 눌러 주세요. 모델명을 같이 넣으면 같은 모델인지도 확인합니다.",
                ),
                unsafe_allow_html=True,
            )

with safety_tab:
    st.markdown(
        dev.section_html(
            "회수·판매중지 확인",
            "모델명이나 품목명으로 식약처 회수·판매중지 자료를 찾습니다. 확인하기 전에는 ‘안전하다’는 뜻이 아닙니다.",
        ),
        unsafe_allow_html=True,
    )
    if not mfds_key:
        st.markdown(dev.missing_key_notice_html("회수·판매중지 정보"), unsafe_allow_html=True)
    st.session_state.setdefault("medical_safety_product", st.session_state.get(WIDGET_PRODUCT, ""))
    with st.form("medical-safety-search"):
        s1, s2, s3 = st.columns(3)
        safety_model = s1.text_input("모델명", key="medical_safety_model")
        safety_product = s2.text_input("품목명 (모델명이 없을 때)", key="medical_safety_product")
        permit_text = s3.text_input("허가번호 (여러 개면 쉼표로 구분)", key="medical_safety_permits")
        recall_submitted = st.form_submit_button(dev.RECALL_BUTTON, type="primary")
    permit_numbers = [part.strip() for part in permit_text.split(",") if part.strip()]
    recall_params = (safety_model.strip(), safety_product.strip())
    if recall_submitted and not any(recall_params):
        st.session_state.pop(RECALL_SLOT, None)
        st.markdown(dev.safety_not_checked_html(False), unsafe_allow_html=True)
    else:
        recall_to_run = _params_to_run(RECALL_SLOT, recall_submitted, recall_params)
        if isinstance(recall_to_run, tuple):
            with st.spinner("회수·판매중지 정보를 확인하는 중입니다."):
                lookup = _lookup_recall(*recall_to_run)
            st.session_state[RECALL_SLOT] = {
                "params": recall_to_run,
                "result": lookup,
                "permits": permit_numbers,
                "checked_at": datetime.now().strftime("%m-%d %H:%M"),
            }
        saved_recall = st.session_state.get(RECALL_SLOT)
        if not saved_recall:
            st.markdown(dev.safety_not_checked_html(any(recall_params)), unsafe_allow_html=True)
        else:
            saved_model, saved_product = saved_recall["params"]
            view = dev.recall_view(saved_recall["result"], searched=saved_model or saved_product)
            if view.is_hit:
                st.markdown(view.banner, unsafe_allow_html=True)
            st.markdown(
                dev.safety_key_chips_html(
                    saved_model,
                    saved_recall["permits"],
                    saved_product,
                    checked_at=saved_recall["checked_at"],
                ),
                unsafe_allow_html=True,
            )
            st.markdown(
                dev.single_metric_html(
                    metric_card_html("회수·판매중지", view.card_value, view.card_sub, view.card_tone)
                ),
                unsafe_allow_html=True,
            )
            if view.is_hit:
                _table(list(view.rows))
                st.markdown(
                    '<div class="pc-dev-hint">회수 기록에는 허가번호가 없어 모델명·품목명이 비슷한 정보를 '
                    "보여줍니다. 대상 모델·제조번호·조치일은 원문에서 확인하세요.</div>",
                    unsafe_allow_html=True,
                )
            elif view.notice:
                st.markdown(view.notice, unsafe_allow_html=True)
            if view.state == "failed":
                _retry_button(RECALL_SLOT, "recall")

    st.markdown(
        dev.section_html("식약처 사이트에서 직접 확인", "중요한 구매는 원문 사이트에서 한 번 더 확인하세요."),
        unsafe_allow_html=True,
    )
    link1, link2, link3 = st.columns(3)
    link1.link_button("회수·판매중지 보기", MFDS_RECALL_PAGE_URL, use_container_width=True)
    link2.link_button("행정처분 보기", MFDS_ADMIN_SANCTION_PAGE_URL, use_container_width=True)
    link3.link_button("안전성 서한 보기", MFDS_SAFETY_LETTER_PAGE_URL, use_container_width=True)

    st.markdown(
        dev.section_html(
            "업체 허가·신고 확인",
            "업체가 의료기기를 만들거나 팔 수 있게 허가·신고했는지 확인합니다.",
        ),
        unsafe_allow_html=True,
    )
    with st.form("medical-company-search"):
        safety_company = st.text_input("업체명", key="medical_safety_company")
        company_submitted = st.form_submit_button(dev.COMPANY_BUTTON, disabled=not bool(mfds_key))
    company_text = safety_company.strip()
    if company_submitted and not company_text:
        st.session_state.pop(COMPANY_SLOT, None)
        st.markdown(
            dev.idle_html("업체명을 넣어 주세요.", "", dev.TONE_WARN),
            unsafe_allow_html=True,
        )
    else:
        company_to_run = _params_to_run(COMPANY_SLOT, company_submitted, company_text)
        if isinstance(company_to_run, str):
            outcome: dict[str, object] = {"params": company_to_run, "rows": [], "error": ""}
            with st.spinner("식약처 업체 허가·신고를 확인하는 중입니다."):
                try:
                    outcome["rows"] = dev.business_rows(_business_client().search_company(company_to_run))
                except (PublicDataClientError, ValueError) as exc:
                    outcome["error"] = dev.safe_error_text(exc) or "응답을 받지 못했습니다"
            st.session_state[COMPANY_SLOT] = outcome
        saved_company = st.session_state.get(COMPANY_SLOT)
        if saved_company:
            if saved_company["error"]:
                st.markdown(
                    dev.lookup_failed_html("식약처 업체 허가·신고", str(saved_company["error"])),
                    unsafe_allow_html=True,
                )
                _retry_button(COMPANY_SLOT, "company")
            elif saved_company["rows"]:
                _table(saved_company["rows"])
            else:
                st.markdown(dev.company_not_found_html(str(saved_company["params"])), unsafe_allow_html=True)

with udi_tab:
    st.markdown(
        dev.section_html(
            "UDI-DI 확인",
            "알고 있는 UDI-DI(제품 라벨에 적힌 의료기기 고유 번호)로 식약처 자료를 찾습니다. "
            "모델명으로 UDI-DI를 알아내지는 않습니다.",
        ),
        unsafe_allow_html=True,
    )
    if not mfds_key:
        st.markdown(dev.missing_key_notice_html("UDI-DI"), unsafe_allow_html=True)
    with st.form("medical-udi-search"):
        udi_di = st.text_input("UDI-DI", placeholder="알고 있는 UDI-DI를 입력하세요", key=WIDGET_UDI)
        udi_submitted = st.form_submit_button(dev.UDI_BUTTON, type="primary", disabled=not bool(mfds_key))
    udi_text = udi_di.strip()
    if udi_submitted and not udi_text:
        st.session_state.pop(UDI_SLOT, None)
        st.markdown(
            dev.idle_html("UDI-DI를 넣어 주세요.", "제품 라벨에 적힌 번호를 그대로 넣습니다.", dev.TONE_WARN),
            unsafe_allow_html=True,
        )
    else:
        udi_to_run = _params_to_run(UDI_SLOT, udi_submitted, udi_text)
        if isinstance(udi_to_run, str):
            udi_outcome: dict[str, object] = {"params": udi_to_run, "rows": [], "error": ""}
            with st.spinner("식약처 UDI 자료를 확인하는 중입니다."):
                try:
                    udi_client = MfdsUdiCodeClient(
                        mfds_key,
                        client=mfds_json_client(settings),
                        base_url=settings.mfds_udi_code_base_url or MFDS_UDI_CODE_BASE_URL,
                        timeout_seconds=settings.mfds_request_timeout_seconds,
                        max_retries=settings.mfds_max_retries,
                    )
                    udi_outcome["rows"] = dev.udi_rows(udi_client.lookup_udi(udi_to_run))
                except (PublicDataClientError, ValueError) as exc:
                    udi_outcome["error"] = dev.safe_error_text(exc) or "응답을 받지 못했습니다"
            st.session_state[UDI_SLOT] = udi_outcome
        saved_udi = st.session_state.get(UDI_SLOT)
        if saved_udi:
            if saved_udi["error"]:
                st.markdown(
                    dev.lookup_failed_html("UDI-DI", str(saved_udi["error"])), unsafe_allow_html=True
                )
                _retry_button(UDI_SLOT, "udi")
            elif saved_udi["rows"]:
                _table(saved_udi["rows"])
            else:
                st.markdown(dev.udi_not_found_html(str(saved_udi["params"])), unsafe_allow_html=True)
    st.link_button("식약처 UDI 포털에서 직접 찾기", MFDS_UDI_PORTAL_URL)

"""UX v1.2 Q2: another model opens in a new browser tab, so the current result stays for comparison.

Production (2026-10-14): the SJ-DFM100 top-model lists were plain text and the full model table sat
in a folded box where only the row checkbox moved to the model, in the same tab, inside the Cloud
iframe (the address bar never changed). Links are now absolute app URLs, never the inner ``/~/+/``.
"""

from __future__ import annotations

import re
from decimal import Decimal
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from purchase_price.services import category_market as cm
from purchase_price.ui import category_market as ui
from purchase_price.ui import model_links as links

FORBIDDEN = (
    "적정", "권장", "싸다", "비싸다", "절감액", "대체 가능", "안전한 제품", "원인 확정", "개선 필요",
    "우수", "부진", "인기", "대표", "추천",
)
DASHBOARD = Path("pages/1_대시보드.py")


def _query(url: str) -> dict[str, list[str]]:
    return parse_qs(urlsplit(url).query)


def test_url_encodes_the_model_and_adds_identity_and_exact() -> None:
    url = links.model_search_url("SJ DFM100 / 심장 & 충격기", identity_token="mfds:제허 1|A", base=links.PRODUCTION_APP_URL)
    assert url.startswith("https://bp-price-research.streamlit.app/?q=")
    assert " " not in url and url.count("&") == 1  # the model's own "&" is encoded
    assert _query(url) == {"q": ["SJ DFM100 / 심장 & 충격기"], "identity": ["mfds:제허 1|A"]}
    exact = links.model_search_url("가 상사", exact_company=True, base=links.PRODUCTION_APP_URL)
    assert _query(exact) == {"q": ["가 상사"], "exact": ["1"]}
    assert links.model_search_url("  ", base=links.PRODUCTION_APP_URL) == ""


def test_base_url_prefers_the_env_override_and_drops_the_inner_frame_path() -> None:
    env = {"PUBLIC_APP_URL": "https://example.test/~/+/?x=1"}
    assert links.app_base_url(env=env, context_url="http://localhost:8501/") == "https://example.test/"
    assert links.app_base_url(env={"PUBLIC_APP_URL": "https://example.test/app"}) == "https://example.test/app/"


def test_base_url_uses_the_local_origin_only_on_localhost() -> None:
    assert links.app_base_url(env={}, context_url="http://localhost:8599/some/page?q=1") == "http://localhost:8599/"
    assert links.app_base_url(env={}, context_url="http://127.0.0.1:8501/~/+/") == "http://127.0.0.1:8501/"
    cloud = "https://bp-price-research.streamlit.app/~/+/?q=DFM100"
    assert links.app_base_url(env={}, context_url=cloud) == links.PRODUCTION_APP_URL
    assert links.app_base_url(env={}, context_url="") == links.PRODUCTION_APP_URL


def test_no_url_ever_contains_the_inner_frame_path() -> None:
    for base in ("https://bp-price-research.streamlit.app/~/+/", "http://localhost:8501/~/+/x"):
        assert "/~/+" not in links.model_search_url("M40", base=base)
    assert "/~/+" not in links.model_search_url("M40", base=None)


def _model(name: str, *, current: bool = False, company: str = "A사", permit: str = "제허 1") -> cm.CategoryModel:
    return cm.CategoryModel(
        model=name, company=company, permit_number=permit, grade="2", status="국내 정상", trade_count=3,
        median=Decimal("1000000"), low=Decimal("900000"), high=Decimal("1100000"), latest="2026-09-01", current=current,
    )


def _url(model_name: str, registration: cm.CategoryModel | None) -> str:
    token = registration.permit_number if registration is not None else ""
    return links.model_search_url(model_name, identity_token=token, base=links.PRODUCTION_APP_URL)


def test_model_rows_start_with_the_link_column_and_skip_the_searched_model() -> None:
    rows = ui.model_rows([_model("SJ-DFM100", current=True), _model("B2", permit="제허 2")], model_url=_url)
    assert list(rows[0])[0] == links.LINK_COLUMN == "가격 조사"
    assert rows[0][links.LINK_COLUMN] is None  # the searched model is already open
    assert _query(str(rows[1][links.LINK_COLUMN])) == {"q": ["B2"], "identity": ["제허 2"]}
    assert links.LINK_COLUMN not in ui.model_rows([_model("B2")])  # no link without a builder


def test_model_table_is_shown_directly_with_a_link_column_and_no_selection() -> None:
    source = Path("src/purchase_price/ui/category_market.py").read_text(encoding="utf-8")
    body = source.split("def _render_models(", 1)[1].split("def models_table_caption(", 1)[0]
    assert "st.expander" not in body
    assert "on_select" not in body and "selection_mode" not in body
    assert "st.column_config.LinkColumn(LINK_COLUMN, display_text=LINK_TEXT" in body
    assert links.LINK_TEXT == "새 탭에서 보기"
    caption = ui.models_table_caption(cm.CategoryMarket(status="success", product_name="품목"))
    assert "새 탭에서 열리고" in caption


def _trade(model: str, institution: str) -> cm.CategoryTrade:
    return cm.CategoryTrade(
        source_record_id=f"delivery:{model}{institution}|change:00|line:1", raw_object_key="raw/key.json",
        transaction_date="2026-03-01", institution=institution, manufacturer="나눔", model_name=model,
        quantity=Decimal("1"), unit="대", unit_price=Decimal("1000000"), total_amount=Decimal("1000000"),
        supplier="가 상사", business_name="구매", product_title="품목", specification="", detail_code="4217210101",
    )


def test_top_lists_link_every_other_model_into_a_new_tab() -> None:
    trades = [_trade("M0", f"기관{n}") for n in range(3)] + [_trade("M1", "기관 X")]
    market = cm.CategoryMarket(
        status="success", product_name="품목",
        trades=tuple(cm.ClassifiedTrade(trade, cm.KIND_EQUIPMENT) for trade in trades),
        models=(_model("M1", permit="제허 9"),),
    )
    html = ui.top_models_html(market, searched_model="M0", model_url=_url)
    anchors = re.findall(r'<a class="cm-top-link" href="([^"]+)" target="_blank" rel="noopener">([^<]+)</a>', html)
    assert anchors and all(text.strip() == "나눔 M1" for _href, text in anchors)  # M0 is the searched model
    href = anchors[0][0].replace("&amp;", "&")
    assert _query(href) == {"q": ["M1"], "identity": ["제허 9"]}  # the one registration named M1
    assert "/~/+" not in href
    assert ui.TOP_MODELS_LINK_NOTE in html
    assert "cm-top-link" not in ui.top_models_html(market, searched_model="M0")  # no builder, no links


def test_new_visible_strings_use_no_judgement_words() -> None:
    texts = [
        links.LINK_COLUMN, links.LINK_TEXT, ui.TOP_MODELS_LINK_NOTE,
        ui.models_table_caption(cm.CategoryMarket(status="success", product_name="품목")),
        "이 모델 조사 · 새 탭", "표에서 모델을 누르면 그 모델의 가격 조사가 새 탭에서 열립니다.",
    ]
    for text in texts:
        for word in FORBIDDEN:
            assert word not in text, (word, text)


def test_dashboard_call_sites_follow_the_new_tab_rule() -> None:
    source = DASHBOARD.read_text(encoding="utf-8")
    # Result and overview lists open a different model in a new tab.
    assert "model_url=_category_model_url(records)" in source
    assert "_open_category_model" not in source
    overview = source.split('st.markdown(f"#### 모델별 나라장터 거래', 1)[1].split("전체 보기 · 품목별", 1)[0]
    assert "LinkColumn" in overview and "on_select" not in overview
    assert 'link_button(\n                    "이 모델 조사 · 새 탭"' in source
    # Pickers that resolve the current search stay in the same tab.
    assert '_open_model_from_overview(str(similar["name"]), exact_company=True)' in source
    assert '_open_model_from_overview(str(rows[selected[0]]["식약처 품목명"]))' in source
    assert source.count("_open_model_from_overview(") == 3  # the definition and the two pickers
    assert '("purchase_price.ui.category_market", "CATEGORY_MARKET_NEW_TAB_V1")' in source

"""UX v1.1 P4: the chosen trade period survives a refresh and a shared link (?period=3y|5y|all).

The dashboard calls the same helpers (``adopt_url_period`` before the 거래 기간 control,
``remember_picked_period`` as its on_change). The search result itself needs the Track B index,
so the AppTest below drives a small page wired exactly like ``_apply_search_period`` instead of
the dashboard.
"""

from __future__ import annotations

import importlib
import pathlib
from datetime import date

import pytest

from purchase_price.ui import result_summary as rs

AppTest = importlib.import_module("streamlit.testing.v1").AppTest
ROOT = pathlib.Path(__file__).resolve().parents[1]
KEY = "workspace_period::결과"
PICKED = f"{KEY}::picked"


@pytest.mark.parametrize(
    ("label", "token"), [("최근 3년", "3y"), ("최근 5년", "5y"), ("전체", "all")]
)
def test_label_and_url_token_map_both_ways(label: str, token: str) -> None:
    assert rs.period_url_token(label) == token
    assert rs.period_label_from_url(token) == label


def test_every_period_choice_has_a_url_token() -> None:
    assert [label for label, _years in rs.PERIOD_CHOICES] == [label for label, _ in rs.PERIOD_URL_TOKENS]


def test_url_token_tolerates_case_and_spaces() -> None:
    assert rs.period_label_from_url(" 5Y ") == "최근 5년"
    assert rs.period_label_from_url("ALL") == "전체"


@pytest.mark.parametrize("junk", [None, "", "10y", "3", "최근 3년", "all; drop", ["5y"]])
def test_junk_url_values_are_rejected(junk: object) -> None:
    assert rs.period_label_from_url(junk) is None


@pytest.mark.parametrize("junk", [None, "", "3y?", "1년"])
def test_unknown_labels_have_no_token(junk: object) -> None:
    assert rs.period_url_token(junk) is None


def test_url_period_is_adopted_as_a_choice() -> None:
    state: dict[str, object] = {}
    assert rs.adopt_url_period(state, key=KEY, picked_key=PICKED, url_value="5y") is True
    assert state == {KEY: "최근 5년", PICKED: True}


def test_invalid_url_period_leaves_the_default_and_widening() -> None:
    state: dict[str, object] = {}
    assert rs.adopt_url_period(state, key=KEY, picked_key=PICKED, url_value="7y") is False
    assert state == {}


def test_a_period_picked_this_session_wins_over_the_url() -> None:
    state: dict[str, object] = {KEY: "전체", PICKED: True}
    assert rs.adopt_url_period(state, key=KEY, picked_key=PICKED, url_value="3y") is False
    assert state[KEY] == "전체"


def test_picking_writes_the_period_to_the_url() -> None:
    state: dict[str, object] = {KEY: "전체"}
    params: dict[str, object] = {"q": "PNB-704"}
    rs.remember_picked_period(state, params, key=KEY, picked_key=PICKED)
    assert state[PICKED] is True
    assert params == {"q": "PNB-704", "period": "all"}


def test_deselecting_writes_the_default_period() -> None:
    state: dict[str, object] = {KEY: None}
    params: dict[str, object] = {}
    rs.remember_picked_period(state, params, key=KEY, picked_key=PICKED)
    assert params == {"period": "3y"}


def test_url_period_is_never_widened() -> None:
    state: dict[str, object] = {}
    rs.adopt_url_period(state, key=KEY, picked_key=PICKED, url_value="3y")
    choice = rs.choose_period(
        ["2015-01-01"], requested=state[KEY], user_chose=bool(state[PICKED]), today=date(2026, 10, 13)
    )
    assert choice.label == "최근 3년"
    assert choice.widened_from is None


def _period_page() -> None:
    import streamlit as st

    from purchase_price.ui import result_summary as rs

    key = "workspace_period::결과"
    picked_key = f"{key}::picked"
    rs.adopt_url_period(
        st.session_state, key=key, picked_key=picked_key, url_value=st.query_params.get(rs.PERIOD_URL_PARAM)
    )
    if not st.session_state.get(picked_key):
        st.session_state[key] = rs.DEFAULT_PERIOD_LABEL

    def _mark_picked() -> None:
        rs.remember_picked_period(st.session_state, st.query_params, key=key, picked_key=picked_key)

    st.segmented_control(
        "거래 기간",
        options=[label for label, _years in rs.PERIOD_CHOICES],
        key=key,
        on_change=_mark_picked,
    )


def test_loading_with_period_in_the_url_preselects_it() -> None:
    app = AppTest.from_function(_period_page, default_timeout=30)
    app.query_params["period"] = "5y"
    app.run()
    assert not app.exception
    assert app.button_group[0].value == "최근 5년"
    assert app.session_state[PICKED] is True


def test_loading_with_a_junk_period_falls_back_to_the_default() -> None:
    app = AppTest.from_function(_period_page, default_timeout=30)
    app.query_params["period"] = "forever"
    app.run()
    assert not app.exception
    assert app.button_group[0].value == "최근 3년"
    assert PICKED not in app.session_state


def test_picking_a_period_puts_it_in_the_url() -> None:
    app = AppTest.from_function(_period_page, default_timeout=30)
    app.query_params["q"] = "PNB-704"
    app.run()
    app.button_group[0].set_value("전체").run()
    assert not app.exception
    # AppTest reports each URL parameter as a list of values.
    assert dict(app.query_params) == {"q": ["PNB-704"], "period": ["all"]}


def test_dashboard_uses_the_period_url_helpers() -> None:
    source = (ROOT / "pages" / "1_대시보드.py").read_text(encoding="utf-8")
    assert "result_summary_ui.adopt_url_period(" in source
    assert "result_summary_ui.remember_picked_period(" in source
    assert '("purchase_price.ui.result_summary", "PERIOD_URL_V1")' in source
    # A new search from a recent/example query keeps the picked period.
    assert "st.query_params[result_summary_ui.PERIOD_URL_PARAM] = str(period)" in source

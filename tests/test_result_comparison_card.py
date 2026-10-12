"""거래가 비교 결과 card (UX v1.1 P1): status pill, evidence level, exclusions, sources, category line."""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

from purchase_price.services import price_metrics as pm
from purchase_price.ui import result_layout as rl

FIXTURES = Path(__file__).parent / "fixtures" / "price"
TODAY = date(2026, 10, 12)


def result_for(name: str, *, quote: str | None = None, identity_exact: bool = True) -> pm.PriceResult:
    data = json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))
    trades = [pm.PriceTrade.from_mapping(row) for row in data["trades"]]
    valid = [t for t in trades if t.entry_error_reason is None]
    return pm.build_price_result(
        trades,
        quote_unit_price=Decimal(quote) if quote else None,
        identity_confirmed=True,
        identity_exact=identity_exact,
        period_label="최근 3년",
        cutoff=date(2023, 10, 13),
        preferred_unit=pm.main_unit(valid),
        data_as_of="2026-10-10",
        today=TODAY,
    )


def test_status_pill_shows_the_contract_label_when_a_quote_is_typed() -> None:
    html = rl.comparison_status_html(result_for("many_mixed_units", quote="6500000"), quote_entered=True)
    assert 'id="purchase-comparison-status-v1"' in html
    assert "확인 필요" in html
    assert "근거 수준 <b>보통</b>" in html
    assert "다른 단위 거래 2건은 가격 계산에서 뺌" in html


def test_without_a_quote_only_the_evidence_level_shows_for_enough_trades() -> None:
    html = rl.comparison_status_html(result_for("many_single_unit"), quote_entered=False)
    assert "pc-pill" not in html
    assert "근거 수준 <b>높음</b>" in html


def test_short_evidence_shows_the_pill_even_without_a_quote() -> None:
    html = rl.comparison_status_html(result_for("few_trades"), quote_entered=False)
    assert "비교 근거 부족" in html
    assert "제한적" in html


def test_in_range_pill_keeps_the_condition_caveat() -> None:
    html = rl.comparison_status_html(result_for("many_single_unit", quote="12000000"), quote_entered=True)
    assert "거래 범위 안 (조건 미확인)" in html


def test_excluded_note_names_every_reason() -> None:
    assert rl.excluded_note(result_for("many_mixed_units").summary) == " (제외 2건: 다른 단위 2(set))"
    assert rl.excluded_note(result_for("entry_errors_and_outlier").summary) == " (제외 2건: 입력 오류 의심 2)"
    assert rl.excluded_note(result_for("many_single_unit").summary) == ""


def test_difference_amount_is_signed() -> None:
    assert "(+120,000원)" in rl.difference_amount_html(Decimal("2100000"), Decimal("1980000"))
    assert "(−1,050,000원)" in rl.difference_amount_html(Decimal("12000000"), Decimal("13050000"))
    assert rl.difference_amount_html(None, Decimal("1")) == ""


def test_headline_carries_the_difference_in_won() -> None:
    stats = SimpleNamespace(
        direct_count=8,
        min_price=Decimal("1731000"),
        max_price=Decimal("7920000"),
        median_price=Decimal("1980000"),
        latest_transaction_date="2026-09-10",
    )
    conclusion = SimpleNamespace(headline="", detail=None, quote_line=None)
    lead = rl.lead_view(
        stats, conclusion, quote=Decimal("2100000"), unit="대", excluded_text=" (제외 2건: 입력 오류 의심 2)"
    )
    assert "(+120,000원)" in lead.headline_html
    assert "8건 기준 (제외 2건: 입력 오류 의심 2)" in lead.basis


def test_recent_sources_link_the_three_latest_trades() -> None:
    rows = [
        {"거래일": f"2026-0{month}-01", "가격": "1,000,000원", "원천기록": f"delivery:R{month:04d}|change:0|line:1"}
        for month in range(1, 6)
    ]
    html = rl.recent_sources_html(rows, unit="대")
    assert html.count("<a ") == 3
    assert html.index("2026-05-01") < html.index("2026-04-01") < html.index("2026-03-01")
    assert "2026-02-01" not in html
    assert rl.recent_sources_html([], unit="대") == ""


def test_category_line_only_for_short_same_model_evidence() -> None:
    market = SimpleNamespace(level=SimpleNamespace(median=Decimal("3400000"), count=57, unit="대"))
    html = rl.category_reference_html(market, priced_count=2)
    assert "직접 비교 거래가 부족합니다" in html
    assert "다른 모델을 포함한 참고 시세" in html
    assert "3,400,000원" in html
    # 0 trades: the category market is the main body already; no duplicate line.
    assert rl.category_reference_html(market, priced_count=0) == ""
    assert pm.category_allowed_in_conclusion(result_for("few_trades").summary)
    assert not pm.category_allowed_in_conclusion(result_for("many_single_unit").summary)


def test_stale_data_turns_the_basis_chip_amber() -> None:
    chip = rl.basis_chip(track_b_data_as_of="2026-10-05", stale=True)
    assert chip is not None and chip.tone == rl.TONE_WARN
    assert "3일 넘게" in chip.text
    fresh = rl.basis_chip(track_b_data_as_of="2026-10-05", live_checked_until="2026-10-12", stale=True)
    assert fresh is not None and fresh.tone == rl.TONE_MUTED


def test_status_goes_inside_the_card_above_the_headline() -> None:
    lead = rl.LeadView("eyebrow", rl.TONE_OK, "headline", "basis")
    html = rl.lead_row_html(lead, price_html="", panel_html="", status_html="<STATUS>", after_price_html="<AFTER>")
    assert html.index("eyebrow") < html.index("<STATUS>") < html.index("headline") < html.index("<AFTER>")

"""The quote review and the price search count the same trades (index plus the live days)."""

from __future__ import annotations

import dataclasses
from contextlib import contextmanager
from datetime import date
from pathlib import Path

from test_track_b_live_gap_fill import QUERY, WINDOW, FakeClient, _item

from purchase_price.services import track_b_live_gap_fill as gap
from purchase_price.services import track_b_quote_with_live as quote_live
from purchase_price.services.track_b_db_quote_comparison import TrackBQuoteComparison


def _collected(*items):
    rows = gap.fetch_live_gap(
        QUERY, detail_codes=["4217210101"], window=WINDOW, client=FakeClient({"4217210101": list(items)})
    ).candidates
    return tuple(dataclasses.replace(row, transaction_type="나라장터 납품요구") for row in rows)


class _Snapshot:
    def __init__(self, result: TrackBQuoteComparison, *, data_as_of: str | None = "2026-10-05") -> None:
        self.result = result
        self.data_as_of = data_as_of
        self.session = None

    def lookup(self, query, *, quote_unit_price):
        return self.result


def _use_snapshot(monkeypatch, snapshot: _Snapshot) -> None:
    @contextmanager
    def opener():
        yield snapshot

    monkeypatch.setattr(quote_live, "open_track_b_serving_snapshot", opener)


def test_live_rows_are_added_to_the_indexed_trades(monkeypatch) -> None:
    indexed = TrackBQuoteComparison("success", _collected(_item("R1"), _item("R2")), 2)
    _use_snapshot(monkeypatch, _Snapshot(indexed))
    seen = {}

    def live_fetcher(query, *, detail_codes, data_as_of, quote_unit_price):
        seen["data_as_of"] = data_as_of
        return gap.fetch_live_gap(
            query,
            detail_codes=["4217210101"],
            window=WINDOW,
            client=FakeClient({"4217210101": [_item("R2"), _item("R3", when="20261007")]}),
        )

    merged, live = quote_live.lookup_track_b_quote_with_live(
        QUERY, quote_unit_price=None, live_fetcher=live_fetcher
    )

    assert seen["data_as_of"] == "2026-10-05"
    assert live.status == "success"
    assert len(merged.candidates) == 3  # R1, R2 (collected kept) and the new live R3


def test_failed_live_check_keeps_the_indexed_trades(monkeypatch) -> None:
    indexed = TrackBQuoteComparison("success", _collected(_item("R1")), 1)
    _use_snapshot(monkeypatch, _Snapshot(indexed))

    merged, live = quote_live.lookup_track_b_quote_with_live(
        QUERY,
        quote_unit_price=None,
        live_fetcher=lambda *_a, **_k: gap.TrackBLiveGapFill("failure", "실시간 조회 실패"),
    )

    assert merged is indexed
    assert live.status == "failure"


def test_missing_index_falls_back_without_a_live_call(monkeypatch) -> None:
    _use_snapshot(monkeypatch, _Snapshot(TrackBQuoteComparison("unavailable", (), 0)))
    fallback = TrackBQuoteComparison("success_0", (), 0)
    monkeypatch.setattr(quote_live, "lookup_track_b_quote", lambda query, *, quote_unit_price: fallback)

    def must_not_run(*_args, **_kwargs):
        raise AssertionError("live lookup without an index")

    merged, live = quote_live.lookup_track_b_quote_with_live(
        QUERY, quote_unit_price=None, live_fetcher=must_not_run
    )

    assert merged is fallback
    assert live.status == "not_applicable"


def test_run_live_gap_fill_is_up_to_date_when_the_index_covers_today() -> None:
    result = quote_live.run_live_gap_fill(
        QUERY, detail_codes=("4217210101",), data_as_of="2026-10-09", quote_unit_price=None, today=date(2026, 10, 9)
    )
    assert result.status == "up_to_date"


def test_quote_review_uses_the_shared_live_lookup() -> None:
    source = Path("src/purchase_price/ui/quote_market_research.py").read_text(encoding="utf-8")
    assert "lookup_track_b_quote_with_live(" in source
    assert "lookup_track_b_quote(" not in source

from __future__ import annotations

from datetime import date

from purchase_price.services.g2b_contract_research import _date_windows, _same_day_next_month


def test_same_day_next_month_clamps_short_months() -> None:
    assert _same_day_next_month(date(2026, 2, 7)) == date(2026, 3, 7)
    assert _same_day_next_month(date(2026, 1, 31)) == date(2026, 2, 28)
    assert _same_day_next_month(date(2028, 1, 31)) == date(2028, 2, 29)
    assert _same_day_next_month(date(2025, 12, 15)) == date(2026, 1, 15)


def test_windows_never_exceed_one_calendar_month_or_skip_days() -> None:
    windows = _date_windows(date(2025, 10, 6), date(2026, 10, 5))

    assert windows[0][0] == date(2025, 10, 6)
    assert windows[-1][1] == date(2026, 10, 5)
    for (begin, end), (next_begin, _next_end) in zip(windows, windows[1:], strict=False):
        assert (next_begin - end).days == 1
    for begin, end in windows:
        assert end <= _same_day_next_month(begin)
        assert (end - begin).days + 1 <= 31
    # The window that used to fail live (2026-02-07..2026-03-09) is now split at 03-07 or earlier.
    assert all(not (begin <= date(2026, 2, 7) and end >= date(2026, 3, 8)) for begin, end in windows)

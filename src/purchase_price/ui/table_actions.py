"""Row actions for the result tables (UX v1.2 Q3): reopenable trade windows and trade filters.

Production (2026-10-14): after closing a trade's 원문 window, picking the same row again did nothing,
because the page opened the window only when the picked row differed from the last one it had
applied. Now a pick runs a callback that remembers the row and resets the table (its key changes),
so the same row can be picked again, and the window opens once per pick: an ordinary rerun
(typing a quote) finds nothing waiting and opens nothing.

The same callbacks let a supplier row or a year row narrow the 거래 전체 table (one supplier and
one year at most), kept per result in session state, and switch to the tab that shows it.

New module (Streamlit keeps old modules after a deploy; a new module is always imported fresh).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, MutableMapping, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any

TABLE_ACTIONS_V1 = True
UNDATED_YEAR = "날짜 미확인"
CLEAR_LABEL = "전체 보기"


def _state(state: MutableMapping[str, Any] | None) -> MutableMapping[str, Any]:
    if state is not None:
        return state
    import streamlit as st

    return st.session_state


def selected_row(value: object) -> int | None:
    """The picked row index of a dataframe selection state (dict or attribute style); None if none."""

    selection = value.get("selection") if isinstance(value, Mapping) else getattr(value, "selection", None)
    rows = selection.get("rows") if isinstance(selection, Mapping) else getattr(selection, "rows", None)
    picked = list(rows or [])
    return int(picked[0]) if picked else None


def table_key(base: str, state: MutableMapping[str, Any] | None = None) -> str:
    """The table's widget key; it changes after every pick so the selection starts empty again."""

    return f"{base}::v{int(_state(state).get(f'{base}::version', 0))}"


def pick_callback(
    base: str,
    on_pick: Callable[[int], None],
    state: MutableMapping[str, Any] | None = None,
) -> Callable[[], None]:
    """``on_select`` callback: read the picked row, reset the table, then ``on_pick(index)``."""

    def callback() -> None:
        current = _state(state)
        index = selected_row(current.get(table_key(base, current)))
        current[f"{base}::version"] = int(current.get(f"{base}::version", 0)) + 1
        if index is not None:
            on_pick(index)

    return callback


def queue_dialog(slot: str, row: Mapping[str, object], state: MutableMapping[str, Any] | None = None) -> None:
    _state(state)[f"{slot}::dialog"] = dict(row)


def take_dialog(slot: str, state: MutableMapping[str, Any] | None = None) -> dict[str, object] | None:
    """The row picked since the last run (once); None on an ordinary rerun."""

    return _state(state).pop(f"{slot}::dialog", None)


# ── Trade filters ──


@dataclass(frozen=True)
class TradeFilter:
    supplier: str = ""
    year: str = ""

    @property
    def active(self) -> bool:
        return bool(self.supplier or self.year)


def filter_key(result_key: str) -> str:
    return f"trade_filter::{result_key}"


def get_filter(result_key: str, state: MutableMapping[str, Any] | None = None) -> TradeFilter:
    value = _state(state).get(filter_key(result_key))
    return value if isinstance(value, TradeFilter) else TradeFilter()


def set_filter(
    result_key: str,
    state: MutableMapping[str, Any] | None = None,
    *,
    supplier: str | None = None,
    year: str | None = None,
) -> TradeFilter:
    """Replace the supplier or the year (the other one stays); returns the new filter."""

    current = _state(state)
    old = get_filter(result_key, current)
    new = TradeFilter(
        supplier=old.supplier if supplier is None else " ".join(str(supplier).split()),
        year=old.year if year is None else str(year).strip(),
    )
    current[filter_key(result_key)] = new
    return new


def clear_filter(result_key: str, state: MutableMapping[str, Any] | None = None) -> None:
    _state(state).pop(filter_key(result_key), None)


def clear_all_filters(state: MutableMapping[str, Any] | None = None) -> None:
    """A new search starts unfiltered."""

    current = _state(state)
    for name in [name for name in current if str(name).startswith("trade_filter::")]:
        current.pop(name, None)


def _same_name(left: object, right: str) -> bool:
    return " ".join(str(left or "").split()) == right


def trade_year(value: object) -> str:
    """'2025' for '2025-03-01'; '날짜 미확인' without a readable date (same as the year table)."""

    try:
        return str(date.fromisoformat(str(value or "").strip()[:10]).year)
    except ValueError:
        return UNDATED_YEAR


def filter_rows(
    rows: Sequence[Mapping[str, object]],
    trade_filter: TradeFilter,
    *,
    supplier_field: str = "판매처",
    date_field: str = "거래일",
) -> list[Mapping[str, object]]:
    return [
        row
        for row in rows
        if (not trade_filter.supplier or _same_name(row.get(supplier_field), trade_filter.supplier))
        and (not trade_filter.year or trade_year(row.get(date_field)) == trade_filter.year)
    ]


def filter_line(trade_filter: TradeFilter, shown: int) -> str:
    parts = []
    if trade_filter.supplier:
        parts.append(f"납품업체: {trade_filter.supplier}")
    if trade_filter.year:
        parts.append(f"{trade_filter.year}년" if trade_filter.year.isdigit() else trade_filter.year)
    return f"{' · '.join(parts)} 거래만 보는 중 ({shown:,}건)"


# ── Tabs that follow a filter ──


def tabs_follow_key(result_key: str) -> str:
    return f"{filter_key(result_key)}::tabs"


def remember_tab_target(
    result_key: str,
    tabs_key: str,
    label: str,
    state: MutableMapping[str, Any] | None = None,
) -> None:
    """Where a filter pick should switch to (the tabs key and the trade tab's label of this run)."""

    _state(state)[tabs_key_slot(result_key)] = (tabs_key, label)


def tabs_key_slot(result_key: str) -> str:
    return f"{filter_key(result_key)}::target"


def show_trade_tab(result_key: str, state: MutableMapping[str, Any] | None = None) -> None:
    """After a filter pick: from now on this result's tabs keep state, and the trade tab is chosen."""

    current = _state(state)
    current[tabs_follow_key(result_key)] = True
    target = current.get(tabs_key_slot(result_key))
    if isinstance(target, tuple) and len(target) == 2:
        current[target[0]] = target[1]


def stateful_tabs(result_key: str, state: MutableMapping[str, Any] | None = None) -> bool:
    """Tabs keep state (one rerun per tab click) only once this result has used a filter."""

    return bool(_state(state).get(tabs_follow_key(result_key)))


def tabs_state_ready(tabs_key: str, labels: Sequence[str], state: MutableMapping[str, Any] | None = None) -> None:
    """Drop a remembered tab whose label no longer exists (the counts in a label changed)."""

    current = _state(state)
    if tabs_key in current and current[tabs_key] not in labels:
        current.pop(tabs_key, None)


def result_tabs(labels: Sequence[str], *, result_key: str, tabs_key: str) -> Sequence[Any]:
    """``st.tabs``: plain at first; keyed (a filter pick can switch it) once a filter was used."""

    import streamlit as st

    if stateful_tabs(result_key):
        tabs_state_ready(tabs_key, labels)
        try:
            return st.tabs(list(labels), key=tabs_key, on_change="rerun")
        except TypeError:  # a Streamlit without stateful tabs: the filter still applies
            pass
    return st.tabs(list(labels))

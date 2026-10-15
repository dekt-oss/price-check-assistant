"""Number columns for the price tables (UX v1.2 Q1).

Prices, counts and quantities reach ``st.dataframe`` as numbers, so a header click sorts
147,000,000 above 63,000,000. The thousands separator comes from the column format and the unit
from the header ("거래 총액(원)"). A missing value is None, which the table sorts last.

New module (Streamlit keeps old modules after a deploy; a new module is always imported fresh).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from decimal import Decimal, InvalidOperation
from typing import Any

NUMBER_COLUMNS_V1 = True
NUMBER_FORMAT = "localized"


def number(value: object) -> int | float | None:
    """Decimal, int, float or '1,234원' -> int when whole, else float; None when missing."""

    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    text = str(value).replace(",", "").replace("원", "").strip()
    try:
        amount = Decimal(text)
    except (InvalidOperation, ValueError):
        return None
    if not amount.is_finite():
        return None
    return int(amount) if amount == amount.to_integral_value() else float(amount)


def _is_number(value: object) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)


def numeric_columns(rows: Iterable[Mapping[str, object]]) -> list[str]:
    """Columns whose every value is a number or None (never text, never True/False)."""

    names: dict[str, bool] = {}
    for row in rows:
        for name, value in row.items():
            names[name] = names.get(name, True) and (value is None or _is_number(value))
    return [name for name, numeric in names.items() if numeric]


def number_column_config(
    rows: Iterable[Mapping[str, object]],
    overrides: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """``st.column_config.NumberColumn(format="localized")`` for every numeric column.

    ``overrides`` (a link column, a width, a renamed header) win over the automatic config."""

    import streamlit as st

    config: dict[str, Any] = {
        name: st.column_config.NumberColumn(name, format=NUMBER_FORMAT) for name in numeric_columns(rows)
    }
    config.update(overrides or {})
    return config

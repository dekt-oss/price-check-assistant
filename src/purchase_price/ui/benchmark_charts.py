"""Trend charts for the Benchmark screen.

The earlier ``st.line_chart`` started every axis at 0, so a 47% vs 50% gap was a flat band.
These charts zoom the y-axis to the data, draw the chosen hospital as the one colored line, the
비교군 평균 as a dark dashed line (computed by ``hospital_metrics.peer_average``), and every other
comparison hospital as a thin gray line that names itself on hover. With up to ~30 size peers
that is the only readable way: color for the two lines that matter, gray context for the rest.
"""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal

import altair as alt
import pandas as pd

from purchase_price.services import hospital_metrics as metrics

TARGET_COLOR = "#2a78d6"  # categorical slot 1 (validated against the white surface)
AVERAGE_COLOR = "#52514e"  # secondary ink, dashed: identity by line style, not hue
PEER_COLOR = "#c3c2b7"  # baseline ink: context lines recede
LABEL_COLOR = "#0b0b0b"
MUTED = "#898781"
GRID = "#e1e0d9"

ROLE_TARGET = "기준 병원"
ROLE_AVERAGE = "비교군 평균"
ROLE_PEER = "비교 병원"


def trend_frame(
    table: Mapping[str, Mapping[int, Decimal | None]],
    target_name: str,
    scale: Decimal = Decimal(1),
) -> pd.DataFrame:
    """Long table (연도, 병원, 값, 구분) with a computed 비교군 평균 row per year.

    Missing years stay missing (no interpolation); the average uses only peers with a value
    that year and records how many it used.
    """

    rows: list[dict[str, object]] = []
    years = sorted({y for values in table.values() for y in values})
    for name, values in table.items():
        role = ROLE_TARGET if name == target_name else ROLE_PEER
        for year in years:
            value = values.get(year)
            if value is not None:
                rows.append({"연도": str(year), "병원": name, "값": float(value / scale), "구분": role, "평균 병원 수": None})
    for year in years:
        peer_values = [values.get(year) for name, values in table.items() if name != target_name]
        average = metrics.peer_average(peer_values)
        if average is not None:
            rows.append(
                {
                    "연도": str(year),
                    "병원": ROLE_AVERAGE,
                    "값": float(average / scale),
                    "구분": ROLE_AVERAGE,
                    "평균 병원 수": sum(1 for v in peer_values if v is not None),
                }
            )
    return pd.DataFrame(rows, columns=["연도", "병원", "값", "구분", "평균 병원 수"])


def y_domain(frame: pd.DataFrame) -> list[float]:
    """Fit the axis to what the reader compares: the chosen hospital, the average, and the middle
    80% of comparison hospitals. A few extreme peers would otherwise flatten the blue line again;
    their gray lines are clipped at the chart edge (values stay in the tooltip and table)."""

    focus = frame[frame["구분"] != ROLE_PEER]["값"]
    peers = frame[frame["구분"] == ROLE_PEER]["값"]
    parts = [focus]
    if len(peers) >= 5:
        parts.append(peers[(peers >= peers.quantile(0.1)) & (peers <= peers.quantile(0.9))])
    else:
        parts.append(peers)
    values = pd.concat(parts)
    low, high = float(values.min()), float(values.max())
    span = (high - low) or abs(high) or 1.0
    return [low - span * 0.15, high + span * 0.15]


def trend_chart(frame: pd.DataFrame, *, unit_label: str, value_format: str = ",.1f", height: int = 260) -> alt.LayerChart:
    if frame.empty:
        raise ValueError("no data")
    domain = y_domain(frame)
    y = alt.Y(
        "값:Q",
        title=None,
        scale=alt.Scale(domain=domain, zero=False, nice=False),
        axis=alt.Axis(format=value_format, labelColor=MUTED, gridColor=GRID, domain=False, ticks=False, tickCount=5),
    )
    x = alt.X(
        "연도:O",
        title=None,
        axis=alt.Axis(labelAngle=0, labelColor=MUTED, domainColor="#c3c2b7", ticks=False),
    )
    tooltip = [
        alt.Tooltip("병원:N"),
        alt.Tooltip("연도:O"),
        alt.Tooltip("값:Q", title=unit_label, format=value_format),
    ]
    base = alt.Chart(frame).encode(x=x, y=y)

    hover = alt.selection_point(fields=["연도"], nearest=True, on="pointerover", empty=False)
    peers = (
        base.transform_filter(alt.datum["구분"] == ROLE_PEER)
        .mark_line(strokeWidth=1, color=PEER_COLOR, clip=True)
        .encode(detail="병원:N", tooltip=tooltip)
    )
    peer_points = (
        base.transform_filter(alt.datum["구분"] == ROLE_PEER)
        .mark_point(size=60, opacity=0, clip=True)  # invisible, larger hit target for the gray lines
        .encode(tooltip=tooltip)
    )
    average = (
        base.transform_filter(alt.datum["구분"] == ROLE_AVERAGE)
        .mark_line(strokeWidth=2, strokeDash=[6, 4], color=AVERAGE_COLOR, point=alt.OverlayMarkDef(size=36, color=AVERAGE_COLOR))
        .encode(tooltip=[*tooltip, alt.Tooltip("평균 병원 수:Q", title="평균에 쓴 병원 수")])
    )
    target = (
        base.transform_filter(alt.datum["구분"] == ROLE_TARGET)
        .mark_line(strokeWidth=3, color=TARGET_COLOR, point=alt.OverlayMarkDef(size=64, filled=True, color=TARGET_COLOR))
        .encode(tooltip=tooltip)
    )
    target_labels = (
        base.transform_filter(alt.datum["구분"] == ROLE_TARGET)
        .mark_text(dy=-12, fontSize=11, color=LABEL_COLOR)
        .encode(text=alt.Text("값:Q", format=value_format))
    )
    last_year = frame["연도"].max()
    end_labels = (
        base.transform_filter((alt.datum["연도"] == last_year) & (alt.datum["구분"] != ROLE_PEER))
        .mark_text(align="left", dx=10, fontSize=11, fontWeight="bold", color=LABEL_COLOR)
        .encode(text="병원:N")
    )
    rule = (
        alt.Chart(frame)
        .mark_rule(color="#c3c2b7", strokeWidth=1)
        .encode(x=x, opacity=alt.condition(hover, alt.value(1), alt.value(0)))
        .add_params(hover)
    )
    return (
        alt.layer(peers, peer_points, average, target, target_labels, end_labels, rule)
        .properties(height=height, padding={"left": 4, "right": 110, "top": 8, "bottom": 4})
        .configure_view(stroke=None)
        .configure_axis(labelFontSize=11)
    )


def wide_table(frame: pd.DataFrame, value_format: str = "{:,.1f}") -> pd.DataFrame:
    """Table view of the same numbers (병원 × 연도) for readers who need exact values."""

    if frame.empty:
        return frame
    order = [ROLE_TARGET, ROLE_AVERAGE, ROLE_PEER]
    pivot = frame.pivot_table(index=["구분", "병원"], columns="연도", values="값", aggfunc="first")
    pivot = pivot.reset_index()
    pivot["_o"] = pivot["구분"].map({k: i for i, k in enumerate(order)})
    pivot = pivot.sort_values(["_o", "병원"]).drop(columns=["_o", "구분"])
    for column in pivot.columns[1:]:
        pivot[column] = pivot[column].map(lambda v: "-" if pd.isna(v) else value_format.format(v))
    return pivot

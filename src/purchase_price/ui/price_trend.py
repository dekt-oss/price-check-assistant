"""기간별 가격 (UX v1.1 Phase P3a): the same-model price per month, quarter or year.

Reads ``services.price_metrics.price_trend`` only. Each bucket is a dot at its median with a
vertical bar from its lowest to its highest price; buckets with too few trades are grey and say
so. Dots are never joined by a line, so an empty quarter cannot look like a slope, and no word
such as 상승·하락·추세 appears. The same numbers are always given as a table below the chart.

New module (Streamlit keeps old modules after a deploy; the page reloads it by its marker).
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

PRICE_TREND_UI_V1 = True

ENOUGH_COLOR = "#1D4ED8"
THIN_COLOR = "#A9B4C2"
QUOTE_COLOR = "#B42318"
MUTED = "#7A899B"
GRID = "#E9EEF4"
ENOUGH_LABEL = "비교에 사용"
THIN_LABEL = "거래가 적어 비교 안 함"


def _won(value: Decimal | None) -> str:
    return f"{value:,.0f}원" if value is not None else "—"


def trend_rows(trend: Any, *, unit: str | None) -> list[dict[str, object]]:
    """The chart's numbers as a table (newest first): the accessible copy of the chart."""

    per = f"1{unit}당 " if unit and len(unit) <= 2 and not unit.isascii() else (f"1 {unit}당 " if unit else "")
    rows = []
    for bucket in reversed(trend.buckets):
        rows.append(
            {
                "기간": bucket.label + (" (진행 중)" if bucket.ongoing else ""),
                "거래 건수": f"{bucket.count}건",
                f"{per}가운데 값".strip(): _won(bucket.median),
                "최저~최고": f"{_won(bucket.low)} ~ {_won(bucket.high)}" if bucket.low is not None else "—",
                "비교": ENOUGH_LABEL if bucket.enough else THIN_LABEL,
            }
        )
    return rows


def trend_frame(trend: Any) -> Any:
    import pandas as pd

    return pd.DataFrame(
        [
            {
                "기간": bucket.label + (" (진행 중)" if bucket.ongoing else ""),
                "순서": bucket.key,
                "건수": bucket.count,
                "가운데 값": float(bucket.median) if bucket.median is not None else None,
                "최저": float(bucket.low) if bucket.low is not None else None,
                "최고": float(bucket.high) if bucket.high is not None else None,
                "비교": ENOUGH_LABEL if bucket.enough else THIN_LABEL,
            }
            for bucket in trend.buckets
        ]
    )


def trend_chart(trend: Any, *, quote: Decimal | None = None, height: int = 240) -> Any | None:
    """Altair layer: range bars + median dots per bucket, optional dashed quote line. None when
    the contract found no granularity (draw nothing rather than a misleading picture)."""

    if trend.granularity is None or not trend.buckets:
        return None
    import altair as alt

    frame = trend_frame(trend)
    order = list(frame["기간"])
    x = alt.X("기간:O", sort=order, title=None, axis=alt.Axis(labelAngle=0, labelColor=MUTED, ticks=False))
    values = [v for v in (*frame["최저"], *frame["최고"]) if v is not None]
    if quote is not None:
        values.append(float(quote))
    low, high = min(values), max(values)
    pad = (high - low) * 0.12 or high * 0.05 or 1.0
    scale = alt.Scale(domain=[max(0.0, low - pad), high + pad], zero=False)
    y = alt.Y(
        "가운데 값:Q",
        title=None,
        scale=scale,
        axis=alt.Axis(format=",.0f", labelColor=MUTED, gridColor=GRID, tickCount=5),
    )
    color = alt.Color(
        "비교:N",
        scale=alt.Scale(domain=[ENOUGH_LABEL, THIN_LABEL], range=[ENOUGH_COLOR, THIN_COLOR]),
        legend=alt.Legend(orient="top", title=None, labelColor=MUTED),
    )
    tooltip = [
        alt.Tooltip("기간:O"),
        alt.Tooltip("건수:Q", title="거래 건수"),
        alt.Tooltip("가운데 값:Q", format=",.0f"),
        alt.Tooltip("최저:Q", format=",.0f"),
        alt.Tooltip("최고:Q", format=",.0f"),
        alt.Tooltip("비교:N"),
    ]
    base = alt.Chart(frame)
    ranges = base.mark_rule(strokeWidth=3, opacity=0.55).encode(
        x=x, y=alt.Y("최저:Q", scale=scale), y2="최고:Q", color=color, tooltip=tooltip
    )
    dots = base.mark_point(size=90, filled=True, opacity=1).encode(x=x, y=y, color=color, tooltip=tooltip)
    counts = base.mark_text(dy=-14, fontSize=11, color=MUTED).encode(
        x=x, y=y, text=alt.Text("건수:Q", format="d")
    )
    layers = [ranges, dots, counts]
    if quote is not None:
        quote_frame = alt.Data(values=[{"내 견적": float(quote)}])
        layers.append(
            alt.Chart(quote_frame)
            .mark_rule(strokeDash=[6, 4], color=QUOTE_COLOR, strokeWidth=1.5)
            .encode(y=alt.Y("내 견적:Q", scale=scale), tooltip=[alt.Tooltip("내 견적:Q", format=",.0f")])
        )
    return alt.layer(*layers).properties(height=height).configure_view(strokeWidth=0)

"""P2a search timing: marker parsing, rolling merge, cold/warm summary, stage labels in the page."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from purchase_price.scripts import measure_price_search_timings as m

AT = datetime(2026, 10, 12, 3, 0, tzinfo=UTC)
DASHBOARD = Path(__file__).resolve().parents[1] / "pages" / "1_대시보드.py"


def test_marker_attributes_become_stage_names() -> None:
    sample = m.sample_from_markers(
        query="PNB-704",
        wall=4.2345,
        timings={"warmup-wait": "0.000", "cold": "1.000", "track-b": "1.250", "total": "2.5"},
        render={"card": "0.310"},
        status="ok",
        at=AT,
    )
    assert sample["cold"] is True
    assert sample["stages"] == {"warmup_wait": 0.0, "track_b": 1.25, "total": 2.5}
    assert sample["wall"] == 4.234
    assert sample["render_card"] == 0.31
    assert sample["at"] == "2026-10-12T03:00:00+00:00"


def test_rolling_samples_keep_the_newest() -> None:
    old = [{"at": f"2026-01-01T00:00:{i:02d}+00:00"} for i in range(m.MAX_SAMPLES)]
    merged = m.merge_samples(old, [{"at": "2026-10-12T00:00:00+00:00"}])
    assert len(merged) == m.MAX_SAMPLES
    assert merged[-1]["at"].startswith("2026-10-12")
    assert merged[0]["at"] == "2026-01-01T00:00:01+00:00"


def _sample(wall: float, *, cold: bool = False, status: str = "ok") -> dict:
    return {"status": status, "cold": cold, "wall": wall, "stages": {"total": wall - 1}, "render_card": 0.2}


def test_summary_splits_cold_and_warm_and_skips_failures() -> None:
    samples = [_sample(w) for w in (2, 3, 4, 5, 20)] + [_sample(60, cold=True), _sample(99, status="timeout")]
    rows = {(r["state"], r["stage"]): r for r in m.summarize(samples)}
    warm = rows[("따뜻한 상태", "wall")]
    assert (warm["n"], warm["median"], warm["p90"]) == (5, 4, 20)
    assert rows[("차가운 상태", "wall")]["n"] == 1
    assert ("따뜻한 상태", "render_card") in rows
    text = m.summary_markdown(samples)
    assert "표본 7개 (실패·시간 초과 1개)" in text


def test_dashboard_reports_each_stage_and_emits_the_v2_marker() -> None:
    source = DASHBOARD.read_text(encoding="utf-8")
    assert 'id="purchase-search-timings-v2"' in source
    assert 'id="purchase-render-timings-v1"' in source
    # The production smoke still reads v1; keep it.
    assert 'id="purchase-search-timings-v1"' in source
    for stage in ("identity", "track_b", "category_market", "track_b_live", "safety"):
        assert f'stage("{stage}")' in source
    assert source.count("progress=_stage_reporter(status)") >= 5
    for key in m.TIMING_KEYS:
        assert key.replace("-", "_") in source


def test_measure_clicks_the_streamlit_wake_button() -> None:
    source = Path("src/purchase_price/scripts/measure_price_search_timings.py").read_text(encoding="utf-8")
    assert "Yes, get this app back up!" in source
    assert "woke = _wake_if_sleeping(page)" in source

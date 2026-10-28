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


def _sample(
    wall: float,
    *,
    cold: bool = False,
    status: str = "ok",
    query: str = "PNB-704",
    stages: dict | None = None,
) -> dict:
    return {
        "query": query,
        "status": status,
        "cold": cold,
        "wall": wall,
        "stages": {"total": wall - 1} if stages is None else stages,
        "render_card": 0.2,
    }


def test_summary_splits_cold_and_warm_and_skips_failures() -> None:
    samples = [_sample(w) for w in (2, 3, 4, 5, 20)] + [_sample(60, cold=True), _sample(99, status="timeout")]
    rows = {(r["query"], r["state"], r["stage"]): r for r in m.summarize(samples)}
    warm = rows[("PNB-704", "따뜻한 상태", "wall")]
    assert (warm["n"], warm["median"], warm["p90"]) == (5, 4, 20)
    assert rows[("PNB-704", "차가운 상태", "wall")]["n"] == 1
    assert ("PNB-704", "따뜻한 상태", "render_card") in rows
    text = m.summary_markdown(samples)
    assert "표본 7개 (실패·시간 초과 1개)" in text


def test_summary_keeps_a_slow_model_apart_from_fast_ones() -> None:
    # Review C-04: 8-second and 14-second models were one warm median.
    samples = [_sample(8, query="PNB-704") for _ in range(3)] + [_sample(14, query="NT960XJG-K72AG")]
    rows = {(r["query"], r["stage"]): r for r in m.summarize(samples) if r["state"] == "따뜻한 상태"}
    assert rows[("PNB-704", "wall")]["median"] == 8
    assert rows[("NT960XJG-K72AG", "wall")]["median"] == 14
    text = m.summary_markdown(samples)
    assert "| NT960XJG-K72AG | 따뜻한 상태 | wall | 1 | 0 | 14.0 | 14.0 |" in text
    assert "- NT960XJG-K72AG: 표본 1개, 실패·시간 초과 0개" in text


def test_unreported_stage_is_missing_not_zero_seconds() -> None:
    sample = m.sample_from_markers(
        query="HeartOn A16-DS",
        wall=9.0,
        timings={"cold": "0", "same-item-models": None, "total": "3.0"},
        render={"card": None},
        status="ok",
        at=AT,
    )
    assert "same_item_models" not in sample["stages"]
    reported = _sample(9, query="HeartOn A16-DS", stages={"same_item_models": 4.5, "total": 3.0})
    rows = {r["stage"]: r for r in m.summarize([sample, reported]) if r["state"] == "따뜻한 상태"}
    assert (rows["same_item_models"]["n"], rows["same_item_models"]["missing"]) == (1, 1)
    assert rows["same_item_models"]["median"] == 4.5


def test_dashboard_reports_each_stage_and_emits_the_v2_marker() -> None:
    source = DASHBOARD.read_text(encoding="utf-8")
    assert 'id="purchase-search-timings-v2"' in source
    assert 'id="purchase-render-timings-v1"' in source
    # The production smoke still reads v1; keep it.
    assert 'id="purchase-search-timings-v1"' in source
    for stage in ("identity", "track_b", "track_b_live", "safety"):
        assert f'stage("{stage}")' in source
    # Review D-02: the same-품목 models and market are timed where they are built, after the card.
    assert '"same_item_models": round(' in source
    assert '"category_market": round(' in source
    assert source.count("progress=_stage_reporter(status)") >= 5
    for key in m.TIMING_KEYS:
        assert key.replace("-", "_") in source


def test_measure_clicks_the_streamlit_wake_button() -> None:
    source = Path("src/purchase_price/scripts/measure_price_search_timings.py").read_text(encoding="utf-8")
    assert "Yes, get this app back up!" in source
    assert "woke = _wake_if_sleeping(page)" in source


def test_after_card_marker_adds_the_same_item_stages_and_done_time() -> None:
    sample = m.sample_from_markers(
        query="HeartOn A16-DS",
        wall=3.6,
        timings={"cold": "0", "track-b": "1.2", "total": "1.5"},
        render={"card": "0.6"},
        status="ok",
        at=AT,
        deferred={"when": "after-card", "done": "10.4", "same-item-models": "6.7", "category-market": "3.4"},
        wall_done=14.3,
    )
    assert sample["stages"]["same_item_models"] == 6.7
    assert sample["stages"]["category_market"] == 3.4
    assert "done" not in sample["stages"] and "when" not in sample["stages"]
    assert (sample["wall"], sample["wall_done"], sample["same_item_when"]) == (3.6, 14.3, "after-card")
    rows = {r["stage"]: r for r in m.summarize([sample])}
    assert rows["wall_done"]["median"] == 14.3


def test_dashboard_writes_the_after_card_marker_and_omits_unrun_stages() -> None:
    source = DASHBOARD.read_text(encoding="utf-8")
    assert 'id="purchase-deferred-timings-v1"' in source
    assert m.DEFERRED_MARKER == "#purchase-deferred-timings-v1"
    assert 'if key not in timings and key not in {"warmup_wait", "cold"}:' in source
    for when in ('"before-card"', '"after-card"', '"none"'):
        assert when in source

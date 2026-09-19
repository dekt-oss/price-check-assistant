import json
from pathlib import Path
from types import SimpleNamespace

from purchase_price.scripts import run_g2b_track_b_supplemental as supplemental
from purchase_price.services.track_b_pipeline_state import STATE_NAME, TrackBPipelineState


class FakeStateStore:
    def __init__(self, base_payload):
        self.base_payload = base_payload
        self.writes = []

    def read_json(self, name):
        if name == STATE_NAME:
            return self.base_payload
        return None

    def write_json(self, name, payload):
        self.writes.append((name, payload))


def test_base_backfill_gate_makes_no_live_collection_call(monkeypatch, tmp_path: Path) -> None:
    base = TrackBPipelineState.bootstrap()
    assert base.backfill_complete is False
    store = FakeStateStore(base.to_payload())

    monkeypatch.setattr(
        supplemental,
        "get_settings",
        lambda: SimpleNamespace(r2_configured=True),
    )
    monkeypatch.setattr(
        supplemental.R2OperationalStateStore,
        "from_settings",
        lambda _settings: store,
    )
    monkeypatch.setattr(
        supplemental,
        "supplemental_verified_codes",
        lambda: ("4511181101",),
    )

    def forbidden_clients(*args, **kwargs):
        raise AssertionError("base historical gate must prevent live G2B client creation")

    monkeypatch.setattr(supplemental, "_collection_clients", forbidden_clients)

    output = tmp_path / "summary.json"
    rc = supplemental.run_supplemental(request_budget=25, summary_path=output)

    assert rc == 0
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["stop_reason"] == "BASE_HISTORICAL_BACKFILL_IN_PROGRESS"
    assert payload["target_codes"] == ["4511181101"]
    assert store.writes == []


def test_supplemental_budget_has_small_hard_cap(tmp_path: Path) -> None:
    try:
        supplemental.run_supplemental(request_budget=101, summary_path=tmp_path / "summary.json")
    except ValueError as exc:
        assert "between 1 and 100" in str(exc)
    else:
        raise AssertionError("supplemental request budget above 100 must fail closed")

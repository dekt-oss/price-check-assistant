from __future__ import annotations

from types import SimpleNamespace

import pytest

from purchase_price.scripts.sync_g2b_track_b_r2_index import (
    _load_or_bootstrap_pipeline_state,
)
from purchase_price.services.track_b_pipeline_state import (
    BOOTSTRAP_LAST_OBJECT_KEY,
    BOOTSTRAP_MIN_R2_OBJECTS,
    STATE_NAME,
    TrackBPipelineState,
)


class FakeStateStore:
    def __init__(self, payloads: dict[str, object] | None = None) -> None:
        self.payloads = dict(payloads or {})
        self.writes: list[tuple[str, object]] = []

    def read_json(self, name: str):
        return self.payloads.get(name)

    def write_json(self, name: str, payload: object) -> None:
        self.payloads[name] = payload
        self.writes.append((name, payload))


class FakeReader:
    def __init__(self, keys: list[str]) -> None:
        self.keys = keys
        self.calls = 0

    def list_public_json(self, *, source_operation: str):
        assert source_operation == "getSpcifyPrdlstPrcureInfoList-page"
        self.calls += 1
        return tuple(SimpleNamespace(key=key) for key in self.keys)


def _validated_legacy_keys() -> list[str]:
    filler_count = BOOTSTRAP_MIN_R2_OBJECTS - 1
    return [f"legacy-proof-{index:04d}" for index in range(filler_count)] + [
        BOOTSTRAP_LAST_OBJECT_KEY
    ]


def test_missing_state_recovers_only_after_validated_r2_proof() -> None:
    state_store = FakeStateStore()
    reader = FakeReader(_validated_legacy_keys())

    pipeline, recovered = _load_or_bootstrap_pipeline_state(
        state_store=state_store,
        reader=reader,
    )

    assert recovered is True
    assert reader.calls == 1
    assert pipeline.collection_cursor.code_index == 3196
    assert pipeline.collection_cursor.page_no == 1
    assert state_store.payloads[STATE_NAME] == pipeline.to_payload()
    assert state_store.writes and state_store.writes[-1][0] == STATE_NAME


def test_missing_state_fails_closed_when_legacy_proof_is_incomplete() -> None:
    state_store = FakeStateStore()
    reader = FakeReader([BOOTSTRAP_LAST_OBJECT_KEY])

    with pytest.raises(RuntimeError, match="validated batch-004 bootstrap proof"):
        _load_or_bootstrap_pipeline_state(state_store=state_store, reader=reader)

    assert STATE_NAME not in state_store.payloads


def test_existing_state_does_not_rescan_legacy_r2_proof() -> None:
    existing = TrackBPipelineState.bootstrap()
    state_store = FakeStateStore({STATE_NAME: existing.to_payload()})
    reader = FakeReader([])

    pipeline, recovered = _load_or_bootstrap_pipeline_state(
        state_store=state_store,
        reader=reader,
    )

    assert recovered is False
    assert reader.calls == 0
    assert pipeline.to_payload() == existing.to_payload()
    assert not state_store.writes

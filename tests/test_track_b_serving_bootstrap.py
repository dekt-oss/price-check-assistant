from __future__ import annotations

import pytest

from purchase_price.scripts.import_g2b_track_b_r2_to_db import TRACK_B_PAGE_OPERATION
from purchase_price.scripts.sync_g2b_track_b_r2_index import _load_or_bootstrap_pipeline_state
from purchase_price.services.track_b_pipeline_state import (
    BOOTSTRAP_LAST_OBJECT_KEY,
    BOOTSTRAP_MIN_R2_OBJECTS,
    STATE_NAME,
)
from purchase_price.storage.r2_reader import R2RawObject


class FakeStateStore:
    def __init__(self) -> None:
        self.payloads: dict[str, dict] = {}

    def read_json(self, name: str):
        return self.payloads.get(name)

    def write_json(self, name: str, payload) -> str:
        self.payloads[name] = dict(payload)
        return f"state/v1/{name}.json"


class FakeReader:
    def __init__(self, objects: list[R2RawObject]) -> None:
        self.objects = objects
        self.requested_operation: str | None = None

    def list_public_json(self, *, source_operation: str):
        self.requested_operation = source_operation
        return list(self.objects)


def _object(key: str, index: int) -> R2RawObject:
    digest = f"{index:064x}"[-64:]
    return R2RawObject(
        bucket="bucket",
        key=key,
        payload_hash=digest,
        stored_bytes=1,
        last_modified=None,
    )


def _audited_objects() -> list[R2RawObject]:
    objects = [
        _object(
            f"raw/v1/{TRACK_B_PAGE_OPERATION}/aa/bb/{index:064x}.json.gz",
            index,
        )
        for index in range(BOOTSTRAP_MIN_R2_OBJECTS - 1)
    ]
    objects.append(_object(BOOTSTRAP_LAST_OBJECT_KEY, BOOTSTRAP_MIN_R2_OBJECTS))
    return objects


def test_serving_index_can_bootstrap_pipeline_state_from_audited_r2_evidence() -> None:
    state_store = FakeStateStore()
    reader = FakeReader(_audited_objects())

    state = _load_or_bootstrap_pipeline_state(state_store=state_store, reader=reader)

    assert reader.requested_operation == TRACK_B_PAGE_OPERATION
    assert state.collection_cursor.code_index == 3196
    assert state.collection_cursor.page_no == 1
    assert STATE_NAME in state_store.payloads
    assert state_store.payloads[STATE_NAME]["collection_cursor"] == {
        "code_index": 3196,
        "page_no": 1,
    }


def test_serving_index_refuses_unproven_r2_cursor_bootstrap() -> None:
    state_store = FakeStateStore()
    reader = FakeReader(_audited_objects()[:-1])

    with pytest.raises(RuntimeError, match="audited batch-004 proof"):
        _load_or_bootstrap_pipeline_state(state_store=state_store, reader=reader)

    assert STATE_NAME not in state_store.payloads

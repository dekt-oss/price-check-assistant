from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from purchase_price.clients.data_go_kr import PublicDataTransportError
from purchase_price.scripts import sync_mfds_item_status_index as sync_module
from purchase_price.services.mfds_device_intelligence import parse_model_record
from purchase_price.services.mfds_item_status_index import (
    lookup_item_status,
    upsert_item_status,
)
from purchase_price.storage.r2_mfds_identity_index import MfdsIdentityIndexRef


def _row(index: int, *, item: str | None = None, cancelled: bool = False, export: bool = False):
    return {
        "MEDDEV_ITEM_NO": item or f"제허 {index:05d} 호",
        "PRDLST_NM": "심장충격기",
        "PRMSN_DCLR_DIVS_NM": "허가",
        "PRMSN_YMD": "2020-01-01",
        "TYPE_INFO": f"M-{index}",
        "RTRCN_DSCTN_DIVS_CD": "3" if cancelled else None,
        "DSCTN_RTRCN_YMD": "2024-01-01" if cancelled else None,
        "EXPORT_YN": "예" if export else "아니오",
    }


class FakeSource:
    def __init__(self, rows: list[dict[str, Any]], *, empty_pages=(), failing_pages=()) -> None:
        self.rows = rows
        self.empty_pages = set(empty_pages)
        self.failing_pages = set(failing_pages)
        self.requested: list[int] = []
        self.lock = threading.Lock()

    def get_json(self, base_url: str, endpoint: str, **params: Any) -> dict[str, Any]:
        page, size = params["pageNo"], params["numOfRows"]
        with self.lock:
            self.requested.append(page)
        if page in self.failing_pages:
            raise PublicDataTransportError("ReadTimeout")
        if page in self.empty_pages:
            return {"header": {"resultCode": "00"}, "body": {"items": [], "totalCount": 0}}
        items = self.rows[(page - 1) * size : page * size]
        return {"header": {"resultCode": "00"}, "body": {"items": items, "totalCount": len(self.rows)}}


class FakeStates:
    def __init__(self) -> None:
        self.states: dict[str, Any] = {}

    def read_json(self, name: str) -> Any:
        value = self.states.get(name)
        return json.loads(json.dumps(value)) if value is not None else None

    def write_json(self, name: str, payload: Any) -> None:
        self.states[name] = json.loads(json.dumps(payload))


class FakeRaw:
    def __init__(self) -> None:
        self.count = 0

    def put_public_json(self, *, source_operation: str, payload: Any) -> None:
        self.count += 1


class FakeArtifacts:
    def __init__(self) -> None:
        self.blobs: dict[str, bytes] = {}

    def download_sqlite(self, ref: MfdsIdentityIndexRef, destination: Path) -> Path:
        destination.write_bytes(self.blobs[ref.key])
        return destination

    def put_sqlite(self, path: Path) -> MfdsIdentityIndexRef:
        raw = path.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        self.blobs[digest] = raw
        return MfdsIdentityIndexRef(key=digest, sha256=digest, stored_bytes=len(raw), uncompressed_bytes=len(raw))


@pytest.fixture()
def harness(tmp_path: Path) -> SimpleNamespace:
    states, raw, artifacts = FakeStates(), FakeRaw(), FakeArtifacts()

    def run(source: FakeSource, *, max_pages: int, rows_per_page: int = 10) -> dict[str, Any]:
        return sync_module.sync(
            max_pages=max_pages,
            output=tmp_path / "report.json",
            settings=SimpleNamespace(mfds_model_info_base_url=None),  # type: ignore[arg-type]
            workers=3,
            rows_per_page=rows_per_page,
            client=source,
            state_store=states,
            raw_store=raw,
            artifact_store=artifacts,
        )

    def items() -> dict[str, Any]:
        pointer = states.states[sync_module.POINTER_STATE]
        db = tmp_path / "check.sqlite"
        db.write_bytes(artifacts.blobs[pointer["key"]])
        connection = sqlite3.connect(db)
        try:
            return {
                row[0]: row[1:]
                for row in connection.execute(
                    "SELECT item_key, domestic_active, cancellation_status FROM mfds_item_status"
                )
            }
        finally:
            connection.close()
            db.unlink()

    return SimpleNamespace(run=run, states=states, raw=raw, items=items)


def test_full_cycle_across_runs_is_verified_and_folds_rows_per_item(harness: SimpleNamespace) -> None:
    rows = [_row(i) for i in range(40)]
    # Two model rows of one item: one cancelled, one active -> item is active.
    rows.append(_row(100, item="수허 99-001 호", cancelled=True))
    rows.append(_row(101, item="수허 99-001 호"))
    rows.append(_row(102, item="수허 99-002 호", cancelled=True))
    rows.append(_row(103, item="수허 99-003 호", export=True))
    source = FakeSource(rows)

    first = harness.run(source, max_pages=3)
    assert first["status"] == "SUCCESS"
    assert first["cycle_completed"] is False
    assert first["next_page"] == 4

    second = harness.run(source, max_pages=10)
    assert second["cycle_completed"] is True
    assert second["cycle_verified"] is True
    assert second["verified_complete_cycles"] == 1
    assert second["next_page"] == 1
    assert harness.raw.count == 5

    items = harness.items()
    assert len(items) == 43
    assert items["수허99-001호"] == (1, "3")
    assert items["수허99-002호"] == (0, "3")
    assert items["수허99-003호"][0] == 0


def test_empty_page_before_source_end_does_not_complete_cycle(harness: SimpleNamespace) -> None:
    report = harness.run(FakeSource([_row(i) for i in range(50)], empty_pages={3}), max_pages=10)

    assert report["status"] == "SOURCE_EMPTY_PAGE"
    assert report["cycle_completed"] is False
    assert report["next_page"] == 3


def test_transport_error_after_progress_keeps_collected_pages(harness: SimpleNamespace) -> None:
    report = harness.run(FakeSource([_row(i) for i in range(50)], failing_pages={4}), max_pages=10)

    assert report["status"] == "SOURCE_TRANSPORT_ERROR"
    assert report["next_page"] == 4
    assert len(harness.items()) == 30


def test_transport_error_on_first_page_fails_loudly(harness: SimpleNamespace) -> None:
    with pytest.raises(PublicDataTransportError):
        harness.run(FakeSource([_row(i) for i in range(50)], failing_pages={1, 2, 3}), max_pages=10)


def test_verified_cycle_purges_items_no_longer_in_source(harness: SimpleNamespace) -> None:
    harness.run(FakeSource([_row(i) for i in range(30)]), max_pages=10)
    report = harness.run(FakeSource([_row(i) for i in range(20)]), max_pages=10)

    assert report["purged_stale_items"] == 10
    assert len(harness.items()) == 20


def test_lookup_item_status_ignores_whitespace() -> None:
    connection = sqlite3.connect(":memory:")
    upsert_item_status(
        connection,
        [parse_model_record(_row(1, item="제허 12-1551 호")), parse_model_record(_row(2, item="수허 1-1 호", cancelled=True))],
        cycle=1,
    )

    status = lookup_item_status(connection, ["제허12-1551호", "수허 1-1 호", "없음"])

    assert status["제허12-1551호"].status_label == "국내 정상"
    assert status["수허1-1호"].status_label == "취소·취하"
    assert "없음" not in status


@pytest.mark.parametrize(
    ("event", "identity", "item", "weekday", "force", "expected"),
    [
        ("schedule", 0, 0, 0, False, False),
        ("workflow_dispatch", 0, 0, 0, True, True),
        ("schedule", 1, 0, 2, False, True),
        ("schedule", 1, 1, 2, False, False),
        ("schedule", 1, 1, 6, False, True),
    ],
)
def test_plan_waits_for_identity_backfill_then_refreshes_weekly(
    event: str, identity: int, item: int, weekday: int, force: bool, expected: bool
) -> None:
    decision = sync_module.plan(
        event_name=event,
        identity_verified_cycles=identity,
        item_status_verified_cycles=item,
        weekday=weekday,
        force=force,
    )
    assert decision["run"] is expected


def test_plan_continues_a_started_first_cycle_before_identity_verifies() -> None:
    started = sync_module.plan(
        event_name="schedule",
        identity_verified_cycles=0,
        item_status_verified_cycles=0,
        weekday=2,
        cycle_in_progress=True,
    )
    assert started["run"] is True

    # Once verified, the weekly cadence applies again even if a refresh cycle is mid-way.
    weekly = sync_module.plan(
        event_name="schedule",
        identity_verified_cycles=0,
        item_status_verified_cycles=1,
        weekday=2,
        cycle_in_progress=True,
    )
    assert weekly["run"] is False

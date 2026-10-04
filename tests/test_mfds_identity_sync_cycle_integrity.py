from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from purchase_price.scripts import sync_mfds_identity_index as sync_module
from purchase_price.storage.r2_mfds_identity_index import MfdsIdentityIndexRef


class FakeStateStore:
    def __init__(self, states: dict[str, Any]) -> None:
        self.states = states

    def read_json(self, name: str) -> Any:
        value = self.states.get(name)
        return json.loads(json.dumps(value)) if value is not None else None

    def write_json(self, name: str, payload: Any) -> None:
        self.states[name] = json.loads(json.dumps(payload))


class FakeRawStore:
    def put_public_json(self, *, source_operation: str, payload: Any) -> Any:
        digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
        return SimpleNamespace(key=f"raw/{digest}", created=True, payload_hash=digest)


class FakeArtifactStore:
    def __init__(self, blobs: dict[str, bytes]) -> None:
        self.blobs = blobs

    def download_sqlite(self, ref: MfdsIdentityIndexRef, destination: Path) -> Path:
        destination.write_bytes(self.blobs[ref.key])
        return destination

    def put_sqlite(self, path: Path) -> MfdsIdentityIndexRef:
        raw = path.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        key = f"idx/{digest}"
        self.blobs[key] = raw
        return MfdsIdentityIndexRef(
            key=key, sha256=digest, stored_bytes=len(raw), uncompressed_bytes=len(raw)
        )

    def delete(self, key: str) -> None:
        self.blobs.pop(key, None)


def _item(n: int) -> dict[str, str]:
    return {
        "PRDLST_NM": f"product-{n}",
        "PERMIT_NO": f"permit-{n}",
        "FOML_INFO": f"model-{n}",
        "MNFT_IPRT_ENTP_NM": f"company-{n}",
    }


def _payload(items: list[dict[str, str]], total_count: int) -> dict[str, Any]:
    return {
        "response": {
            "header": {"resultCode": "00", "resultMsg": "NORMAL SERVICE."},
            "body": {"items": {"item": items}, "totalCount": total_count},
        }
    }


class FakeSource:
    """Serves `total` rows in pages; `empty_pages` return a glitch page with totalCount=0."""

    def __init__(self, total: int, empty_pages: set[int] | None = None) -> None:
        self.total = total
        self.empty_pages = empty_pages or set()
        self.requested: list[int] = []

    def __call__(self, *args: Any, **kwargs: Any) -> FakeSource:
        return self

    def __enter__(self) -> FakeSource:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def get_json(self, base_url: str, operation: str, *, pageNo: int, numOfRows: int) -> Any:
        self.requested.append(pageNo)
        if pageNo in self.empty_pages:
            return _payload([], 0)
        start = (pageNo - 1) * numOfRows
        items = [_item(n) for n in range(start, min(start + numOfRows, self.total))]
        return _payload(items, self.total)


@pytest.fixture()
def harness(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> SimpleNamespace:
    states: dict[str, Any] = {}
    blobs: dict[str, bytes] = {}
    settings = SimpleNamespace(
        resolved_mfds_service_key="test-key",
        r2_configured=True,
        mfds_request_timeout_seconds=5,
        mfds_max_retries=0,
        mfds_product_info_base_url=None,
    )
    monkeypatch.setattr(
        sync_module.R2OperationalStateStore, "from_settings", lambda _s: FakeStateStore(states)
    )
    monkeypatch.setattr(
        sync_module.R2RawEvidenceStore, "from_settings", lambda _s: FakeRawStore()
    )
    monkeypatch.setattr(
        sync_module.R2MfdsIdentityIndexStore,
        "from_settings",
        lambda _s: FakeArtifactStore(blobs),
    )

    def run(source: FakeSource, *, max_pages: int, rows_per_page: int = 10) -> dict[str, Any]:
        monkeypatch.setattr(sync_module, "PublicDataPortalClient", source)
        output = tmp_path / "report.json"
        sync_module._sync_without_lock(
            max_pages=max_pages,
            rows_per_page=rows_per_page,
            output=output,
            settings=settings,  # type: ignore[arg-type]
        )
        return json.loads(output.read_text(encoding="utf-8"))

    def index_rows() -> int:
        pointer = states[sync_module.MFDS_IDENTITY_POINTER_STATE]
        db = tmp_path / "check.sqlite"
        db.write_bytes(blobs[pointer["key"]])
        connection = sqlite3.connect(db)
        try:
            count = connection.execute("SELECT COUNT(*) FROM mfds_identity").fetchone()[0]
        finally:
            connection.close()
        db.unlink()
        return int(count)

    return SimpleNamespace(run=run, states=states, index_rows=index_rows, tmp_path=tmp_path)


def test_empty_page_before_source_end_does_not_complete_cycle(harness: SimpleNamespace) -> None:
    source = FakeSource(total=100, empty_pages={4})

    report = harness.run(source, max_pages=10)

    assert report["status"] == "SOURCE_EMPTY_PAGE"
    assert report["source_anomaly"] == "EMPTY_PAGE_BEFORE_SOURCE_END"
    assert report["cycle_completed"] is False
    assert report["complete_cycles"] == 0
    assert report["next_page"] == 4  # retried on the next run, not skipped
    assert report["source_total_count"] == 100  # totalCount=0 must not erase the known size
    pipeline = harness.states[sync_module.PIPELINE_STATE]
    assert pipeline["cycle"] == 1
    assert pipeline["last_total_count"] == 100
    assert pipeline["cycle_rows_seen"] == 30


def test_cycle_resumes_after_glitch_and_completes_verified(harness: SimpleNamespace) -> None:
    glitchy = FakeSource(total=100, empty_pages={4})
    harness.run(glitchy, max_pages=10)

    report = harness.run(FakeSource(total=100), max_pages=20)

    assert report["status"] == "SUCCESS"
    assert report["cycle_completed"] is True
    assert report["cycle_verified"] is True
    assert report["complete_cycles"] == 1
    assert report["verified_complete_cycles"] == 1
    assert harness.index_rows() == 100


def test_unverified_cycle_never_purges_serving_rows(harness: SimpleNamespace) -> None:
    # Cycle 1 completes legitimately with 100 rows.
    harness.run(FakeSource(total=100), max_pages=20)
    assert harness.index_rows() == 100

    # Cycle 2 sees a glitch empty page after only 20 rows. Before the fix this ended the
    # cycle and purged the 80 rows not yet refreshed in cycle 2.
    report = harness.run(FakeSource(total=100, empty_pages={3}), max_pages=20)

    assert report["cycle_completed"] is False
    assert report["purged_stale_rows"] == 0
    assert harness.index_rows() == 100


def test_verified_cycle_purges_rows_removed_from_source(harness: SimpleNamespace) -> None:
    harness.run(FakeSource(total=100), max_pages=20)

    report = harness.run(FakeSource(total=90), max_pages=20)

    assert report["cycle_verified"] is True
    assert report["purged_stale_rows"] == 10
    assert harness.index_rows() == 90


def test_legacy_pipeline_without_verified_counter_loads_as_unverified(
    harness: SimpleNamespace,
) -> None:
    # Production state after the false completion on 2026-10-01: complete_cycles=1 but no
    # verified counter, cycle 2 in progress.
    harness.states[sync_module.PIPELINE_STATE] = {
        "schema": sync_module.PIPELINE_SCHEMA,
        "next_page": 3,
        "cycle": 2,
        "complete_cycles": 1,
        "last_total_count": 100,
        "cycle_rows_seen": 20,
        "rows_per_page": 10,
    }

    report = harness.run(FakeSource(total=100), max_pages=20)

    assert report["cycle_completed"] is True
    assert report["complete_cycles"] == 2
    assert report["verified_complete_cycles"] == 1


def test_sync_report_shape_is_unchanged_for_workflow(harness: SimpleNamespace) -> None:
    report = harness.run(FakeSource(total=100), max_pages=2)

    for key in ("status", "cycle_completed", "next_page", "row_count", "source_total_count"):
        assert key in report
    assert report["status"] == "SUCCESS"

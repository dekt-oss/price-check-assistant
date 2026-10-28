"""Review B-03: a verified copy on disk answers through a network failure, and says so."""

from pathlib import Path
from types import SimpleNamespace

import pytest
from botocore.exceptions import EndpointConnectionError

from purchase_price.services import track_b_r2_quote_index as module
from purchase_price.storage.r2 import R2IntegrityError
from purchase_price.ui import result_layout

SETTINGS = SimpleNamespace(resolved_r2_endpoint_url="https://r2", resolved_r2_bucket_name="bucket")
POINTER = {"sha256": "a" * 64, "data_as_of": "2026-10-27", "updated_at": "2026-10-27T22:00:00+00:00"}


@pytest.fixture
def clock(monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(module, "monotonic", lambda: now[0])
    monkeypatch.setattr(module, "_LAST_GOOD_SNAPSHOT", {})
    return now


@pytest.fixture
def index_file(tmp_path: Path) -> Path:
    path = tmp_path / f"{'a' * 64}.sqlite"
    path.write_bytes(b"")
    return path


def _locked(monkeypatch, outcomes: list):
    calls = []

    def fake(_settings):
        calls.append(1)
        outcome = outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    monkeypatch.setattr(module, "_local_index_snapshot_locked", fake)
    return calls


def test_pointer_is_read_at_most_once_per_ttl(monkeypatch, clock, index_file) -> None:
    calls = _locked(monkeypatch, [(index_file, POINTER), (index_file, POINTER)])

    module._local_index_snapshot(SETTINGS)
    clock[0] += module.POINTER_TTL_SECONDS - 1
    path, pointer = module._local_index_snapshot(SETTINGS)
    assert len(calls) == 1 and path == index_file and "refresh_failed" not in pointer

    clock[0] += 2
    module._local_index_snapshot(SETTINGS)
    assert len(calls) == 2


def test_network_failure_uses_the_verified_copy_and_flags_it(monkeypatch, clock, index_file) -> None:
    calls = _locked(
        monkeypatch,
        [(index_file, POINTER), EndpointConnectionError(endpoint_url="https://r2"), (index_file, POINTER)],
    )
    module._local_index_snapshot(SETTINGS)

    clock[0] += module.POINTER_TTL_SECONDS + 1
    path, pointer = module._local_index_snapshot(SETTINGS)
    assert path == index_file
    assert pointer["refresh_failed"] is True and pointer["data_as_of"] == "2026-10-27"

    # Within the next TTL every search keeps the flag without calling R2 again.
    clock[0] += 10
    assert module._local_index_snapshot(SETTINGS)[1]["refresh_failed"] is True
    assert len(calls) == 2

    # R2 answers again: the flag goes away.
    clock[0] += module.POINTER_TTL_SECONDS
    assert "refresh_failed" not in module._local_index_snapshot(SETTINGS)[1]


def test_without_a_copy_the_failure_still_surfaces(monkeypatch, clock) -> None:
    _locked(monkeypatch, [OSError("network down")])
    with pytest.raises(OSError):
        module._local_index_snapshot(SETTINGS)


def test_integrity_errors_are_never_covered_by_the_old_copy(monkeypatch, clock, index_file) -> None:
    _locked(monkeypatch, [(index_file, POINTER), R2IntegrityError("schema mismatch")])
    module._local_index_snapshot(SETTINGS)
    clock[0] += module.POINTER_TTL_SECONDS + 1
    with pytest.raises(R2IntegrityError):
        module._local_index_snapshot(SETTINGS)


def test_copy_is_kept_per_endpoint_and_bucket(monkeypatch, clock, index_file) -> None:
    _locked(monkeypatch, [(index_file, POINTER), OSError("other bucket down")])
    module._local_index_snapshot(SETTINGS)
    other = SimpleNamespace(resolved_r2_endpoint_url="https://r2", resolved_r2_bucket_name="other")
    with pytest.raises(OSError):
        module._local_index_snapshot(other)


def test_snapshot_and_chip_say_the_refresh_failed(monkeypatch, index_file) -> None:
    monkeypatch.setattr(
        module, "_local_index_snapshot", lambda _s: (index_file, {**POINTER, "refresh_failed": True})
    )
    with module.open_track_b_serving_snapshot(settings=SimpleNamespace(r2_configured=True)) as snapshot:
        assert snapshot.status == "available" and snapshot.refresh_failed is True

    chip = result_layout.basis_chip(track_b_data_as_of="2026-10-27", index_refresh_failed=True)
    assert chip is not None
    assert chip.text == "나라장터 2026-10-27 수집분 · 최신 자료를 확인하지 못해 이 수집분으로 표시"
    assert chip.tone == result_layout.TONE_WARN
    plain = result_layout.basis_chip(track_b_data_as_of="2026-10-27")
    assert plain is not None and "확인하지 못해" not in plain.text

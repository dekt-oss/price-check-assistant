from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from purchase_price.services.mfds_identity_live_policy import (
    VERIFIED_STATUS_TTL_SECONDS,
    mfds_index_verified_complete,
    reset_live_policy_cache,
    should_query_live_mfds_identity,
)
from purchase_price.services.mfds_identity_status import build_mfds_identity_collection_status


@pytest.fixture(autouse=True)
def _clear_cache() -> None:
    reset_live_policy_cache()


def _status(**pipeline: object):
    return build_mfds_identity_collection_status(
        pointer={"row_count": 2700000},
        pipeline={"next_page": 1, "cycle": 2, "last_total_count": 2708719, **pipeline},
    )


def test_verified_index_skips_live_fallback() -> None:
    status = _status(complete_cycles=2, verified_complete_cycles=1)

    assert should_query_live_mfds_identity(lambda: status, now=0.0) is False


def test_falsely_completed_index_keeps_live_fallback() -> None:
    # Production state after 2026-10-01: complete_cycles=1 at 53% coverage, never verified.
    status = _status(complete_cycles=1)

    assert should_query_live_mfds_identity(lambda: status, now=0.0) is True


def test_stale_status_object_without_verified_counter_keeps_live_fallback() -> None:
    # Streamlit may retain the pre-verification status class whose
    # first_backfill_complete trusted complete_cycles alone.
    stale = SimpleNamespace(status="available", complete_cycles=1, first_backfill_complete=True)

    assert mfds_index_verified_complete(stale) is False
    assert should_query_live_mfds_identity(lambda: stale, now=0.0) is True


@pytest.mark.parametrize("state", ["unavailable", "not_ingested"])
def test_unavailable_status_keeps_live_fallback(state: str) -> None:
    status = SimpleNamespace(status=state, verified_complete_cycles=3)

    assert should_query_live_mfds_identity(lambda: status, now=0.0) is True


def test_status_errors_keep_live_fallback() -> None:
    def broken():
        raise RuntimeError("R2 down")

    assert should_query_live_mfds_identity(broken, now=0.0) is True


def test_status_is_read_once_per_ttl() -> None:
    calls = []

    def load():
        calls.append(1)
        return _status(complete_cycles=2, verified_complete_cycles=1)

    assert should_query_live_mfds_identity(load, now=0.0) is False
    assert should_query_live_mfds_identity(load, now=VERIFIED_STATUS_TTL_SECONDS - 1) is False
    assert len(calls) == 1
    should_query_live_mfds_identity(load, now=VERIFIED_STATUS_TTL_SECONDS + 1)
    assert len(calls) == 2


def test_dashboard_gates_live_identity_on_verified_index() -> None:
    source = Path("pages/1_대시보드.py").read_text(encoding="utf-8")

    assert "should_query_live_mfds_identity(_load_mfds_collection_status)" in source
    gate = source.index("should_query_live_mfds_identity(_load_mfds_collection_status)")
    assert gate < source.index("lookup_mfds_model_identity_live(query.model_name)")
    assert 'id="purchase-workspace-runtime-v9"' in source
    assert 'id="purchase-workspace-runtime-v10"' in source

from types import SimpleNamespace

from purchase_price.scripts.run_g2b_track_b_daily import _exit_code_for_collection


def _summary(**overrides):
    payload = {
        "status": "FAILED",
        "stop_reason": "RATE_LIMIT_EXHAUSTED",
        "codes_completed": 0,
        "pages_stored": 0,
    }
    payload.update(overrides)
    return SimpleNamespace(**payload)


def test_rate_limit_after_durable_progress_allows_downstream_index_sync() -> None:
    assert _exit_code_for_collection(_summary(codes_completed=84, pages_stored=49)) == 0


def test_rate_limit_without_progress_remains_failure() -> None:
    assert _exit_code_for_collection(_summary()) == 1


def test_non_quota_source_failure_remains_failure_even_after_progress() -> None:
    summary = _summary(
        stop_reason="SOURCE_OR_STORAGE_ERROR",
        codes_completed=84,
        pages_stored=49,
    )
    assert _exit_code_for_collection(summary) == 1


def test_normal_success_status_remains_success() -> None:
    assert _exit_code_for_collection(_summary(status="SUCCESS", stop_reason="COMPLETE")) == 0

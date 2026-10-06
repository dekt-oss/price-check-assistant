from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _no_portal_retry_waits(monkeypatch: pytest.MonkeyPatch) -> None:
    """Collectors wait 10 s and 30 s before retrying transient portal failures; tests that
    simulate those failures must not sleep for real."""

    from purchase_price.clients import data_go_kr

    monkeypatch.setattr(data_go_kr, "SERVER_ERROR_RETRY_DELAYS", (0.0, 0.0))

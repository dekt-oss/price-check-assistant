"""Route MFDS data.go.kr requests to whichever configured service key is approved.

data.go.kr approval is per service *and* per account key. On 2026-10-05 the deployment had two
distinct keys: one approved for the product-info service (identity index) and another approved
for model-info (형명) and business-license (업허가). The single `resolved_mfds_service_key`
picked the first one for every MFDS service, so approved services failed with code=30.

`KeyFallbackJsonClient` tries the configured keys in order, moves on only when a key is
explicitly not registered for that service, and remembers the working key per service URL.
"""

from __future__ import annotations

from collections.abc import Sequence
from threading import Lock
from typing import Any

from purchase_price.clients.data_go_kr import PublicDataClientError, PublicDataPortalClient
from purchase_price.config import Settings

_NOT_REGISTERED_MARKERS = (
    "SERVICE_KEY_IS_NOT_REGISTERED_ERROR",
    "SERVICE_ACCESS_DENIED_ERROR",
    "등록되지 않은 서비스키",
    "code=30",
    "code=20",
)
_WORKING_KEY_INDEX: dict[str, int] = {}
_WORKING_KEY_LOCK = Lock()


def is_key_not_registered(exc: BaseException) -> bool:
    message = str(exc)
    return isinstance(exc, PublicDataClientError) and any(
        marker in message for marker in _NOT_REGISTERED_MARKERS
    )


def mfds_service_key_candidates(settings: Settings) -> tuple[str, ...]:
    ordered = (
        settings.mfds_service_key,
        settings.mfds_recall_service_key,
        settings.data_go_kr_market_service_key,
        settings.data_go_kr_service_key,
        settings.g2b_research_service_key,
    )
    return tuple(dict.fromkeys(key.strip() for key in ordered if key and key.strip()))


class KeyFallbackJsonClient:
    """`get_json`-compatible client that falls back across service keys on code=30."""

    def __init__(
        self,
        keys: Sequence[str],
        *,
        timeout_seconds: float = 20.0,
        max_retries: int = 3,
        client_factory: Any = None,
    ) -> None:
        self.keys = tuple(dict.fromkeys(key for key in keys if key))
        if not self.keys:
            raise ValueError("at least one service key is required")
        factory = client_factory or (
            lambda key: PublicDataPortalClient(
                key,
                timeout_seconds=timeout_seconds,
                max_retries=max_retries,
            )
        )
        self._factory = factory
        self._clients: dict[int, Any] = {}
        self._clients_lock = Lock()

    def _client(self, index: int) -> Any:
        # Model-info pages are fetched concurrently; create each per-key client once.
        with self._clients_lock:
            if index not in self._clients:
                self._clients[index] = self._factory(self.keys[index])
            return self._clients[index]

    def get_json(self, base_url: str, endpoint: str, **params: Any) -> dict[str, Any]:
        with _WORKING_KEY_LOCK:
            start = _WORKING_KEY_INDEX.get(base_url, 0)
        order = [start, *(index for index in range(len(self.keys)) if index != start)]
        order = [index for index in order if index < len(self.keys)]
        last_error: BaseException | None = None
        for index in order:
            try:
                payload = self._client(index).get_json(base_url, endpoint, **params)
            except PublicDataClientError as exc:
                if not is_key_not_registered(exc):
                    raise
                last_error = exc
                continue
            with _WORKING_KEY_LOCK:
                _WORKING_KEY_INDEX[base_url] = index
            return payload
        assert last_error is not None
        raise last_error

    def close(self) -> None:
        for client in self._clients.values():
            close = getattr(client, "close", None)
            if callable(close):
                close()
        self._clients.clear()

    def __enter__(self) -> KeyFallbackJsonClient:
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        self.close()
        return False


def build_mfds_json_client(
    settings: Settings,
    *,
    timeout_seconds: float | None = None,
    max_retries: int | None = None,
) -> KeyFallbackJsonClient | None:
    keys = mfds_service_key_candidates(settings)
    if not keys:
        return None
    return KeyFallbackJsonClient(
        keys,
        timeout_seconds=settings.mfds_request_timeout_seconds
        if timeout_seconds is None
        else timeout_seconds,
        max_retries=settings.mfds_max_retries if max_retries is None else max_retries,
    )


# Model-info (형명) answers in ~28-59 s per 100-row page (measured 2026-10-05), far above the
# default 20 s timeout. Only call it from explicit, user-initiated lookups.
MODEL_INFO_TIMEOUT_SECONDS = 90.0


def mfds_model_info_json_client(settings: Settings) -> KeyFallbackJsonClient | None:
    return build_mfds_json_client(
        settings,
        timeout_seconds=max(settings.mfds_request_timeout_seconds, MODEL_INFO_TIMEOUT_SECONDS),
        max_retries=0,
    )


def mfds_json_client(settings: Settings) -> KeyFallbackJsonClient | None:
    return build_mfds_json_client(settings)


def reset_working_keys() -> None:
    with _WORKING_KEY_LOCK:
        _WORKING_KEY_INDEX.clear()

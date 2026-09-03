from __future__ import annotations

from typing import Any

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential


class PublicDataClientError(RuntimeError):
    pass


class PublicDataPortalClient:
    """Small common client for data.go.kr-backed APIs.

    Concrete collectors own endpoint paths and response parsing. The shared client only
    handles authentication, JSON requests, timeout and transient network retries.
    """

    def __init__(
        self,
        service_key: str,
        *,
        timeout_seconds: float = 20.0,
        max_retries: int = 3,
    ) -> None:
        if not service_key.strip():
            raise ValueError("DATA_GO_KR_SERVICE_KEY is required for live API calls")
        self.service_key = service_key
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries

    def _request(self, url: str, params: dict[str, Any]) -> dict[str, Any]:
        merged = {"serviceKey": self.service_key, "type": "json", **params}

        @retry(
            retry=retry_if_exception_type((httpx.TimeoutException, httpx.TransportError)),
            stop=stop_after_attempt(self.max_retries),
            wait=wait_exponential(multiplier=0.5, min=0.5, max=4),
            reraise=True,
        )
        def do_request() -> dict[str, Any]:
            with httpx.Client(timeout=self.timeout_seconds) as client:
                response = client.get(url, params=merged)
                response.raise_for_status()
                try:
                    payload = response.json()
                except ValueError as exc:
                    raise PublicDataClientError("API response is not valid JSON") from exc
            if not isinstance(payload, dict):
                raise PublicDataClientError("API response root must be a JSON object")
            return payload

        return do_request()

    def get_json(self, base_url: str, endpoint: str, **params: Any) -> dict[str, Any]:
        if not base_url.strip():
            raise ValueError("A service base URL must be configured")
        url = f"{base_url.rstrip('/')}/{endpoint.lstrip('/')}"
        return self._request(url, params)

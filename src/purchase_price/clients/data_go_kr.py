from __future__ import annotations

from typing import Any
from urllib.parse import quote, unquote
from xml.etree import ElementTree

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential


class PublicDataClientError(RuntimeError):
    pass


def normalize_service_key(service_key: str) -> str:
    """Accept either data.go.kr Encoding or Decoding key form.

    data.go.kr exposes both representations. Internally we keep the decoded value and let
    the HTTP client perform query-string encoding exactly once.
    """

    normalized = unquote(service_key.strip())
    if not normalized:
        raise ValueError("DATA_GO_KR_SERVICE_KEY is required for live API calls")
    return normalized


def _redact_secret(text: str, secret: str) -> str:
    redacted = text
    for candidate in {secret, quote(secret, safe=""), unquote(secret)}:
        if candidate:
            redacted = redacted.replace(candidate, "***")
    return redacted


def _public_data_error_fields(response: httpx.Response) -> tuple[str | None, str | None, str | None]:
    """Extract data.go.kr error fields from JSON or XML without logging request URLs."""

    try:
        payload = response.json()
    except ValueError:
        payload = None

    if isinstance(payload, dict):
        service_response = payload.get("OpenAPI_ServiceResponse")
        if isinstance(service_response, dict):
            header = service_response.get("cmmMsgHeader")
            if isinstance(header, dict):
                return (
                    str(header.get("errMsg") or "").strip() or None,
                    str(header.get("returnAuthMsg") or "").strip() or None,
                    str(header.get("returnReasonCode") or "").strip() or None,
                )

        common_response = payload.get("response")
        if isinstance(common_response, dict):
            header = common_response.get("header")
            if isinstance(header, dict):
                return (
                    str(header.get("resultMsg") or "").strip() or None,
                    None,
                    str(header.get("resultCode") or "").strip() or None,
                )

    text = response.text.strip()
    if text:
        try:
            root = ElementTree.fromstring(text)
        except ElementTree.ParseError:
            root = None
        if root is not None:
            err_msg = root.findtext(".//errMsg") or root.findtext(".//resultMsg")
            auth_msg = root.findtext(".//returnAuthMsg")
            reason_code = root.findtext(".//returnReasonCode") or root.findtext(".//resultCode")
            return (
                err_msg.strip() if err_msg else None,
                auth_msg.strip() if auth_msg else None,
                reason_code.strip() if reason_code else None,
            )

    return None, None, None


def _http_error_message(response: httpx.Response, secret: str) -> str:
    err_msg, auth_msg, reason_code = _public_data_error_fields(response)
    details = [f"HTTP {response.status_code}"]
    if err_msg:
        details.append(f"error={err_msg}")
    if auth_msg:
        details.append(f"auth={auth_msg}")
    if reason_code:
        details.append(f"code={reason_code}")
    if len(details) == 1:
        body = response.text.strip().replace("\n", " ")[:300]
        if body:
            details.append(f"body={body}")
    return _redact_secret("Public Data Portal request failed: " + " ".join(details), secret)


class PublicDataPortalClient:
    """Small common client for data.go.kr-backed APIs.

    Concrete collectors own endpoint paths and response parsing. The shared client handles
    authentication, JSON requests, timeout, transient network retries and sanitized errors.
    """

    def __init__(
        self,
        service_key: str,
        *,
        timeout_seconds: float = 20.0,
        max_retries: int = 3,
    ) -> None:
        self.service_key = normalize_service_key(service_key)
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
                if response.is_error:
                    raise PublicDataClientError(_http_error_message(response, self.service_key))
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

from __future__ import annotations

import logging
import re
from typing import Any
from urllib.parse import quote, unquote
from xml.etree import ElementTree

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential


class PublicDataClientError(RuntimeError):
    pass


_SERVICE_KEY_QUERY_PATTERN = re.compile(r"(serviceKey=)[^&\s\"']+", re.IGNORECASE)
_HTTP_LOGGER_NAMES = ("httpx", "httpcore")


def redact_service_key_query(text: str) -> str:
    """Mask any `serviceKey=` query value regardless of which key was used."""

    return _SERVICE_KEY_QUERY_PATTERN.sub(r"\1***", text)


class _ServiceKeyLogFilter(logging.Filter):
    """Rewrite HTTP transport log records so a request URL never carries the service key.

    httpx logs `HTTP Request: GET <full url>` at INFO level. If an application enables INFO
    logging (LOG_LEVEL=INFO is the documented default), that line would contain the
    data.go.kr service key. The filter formats the record eagerly and masks the query value.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:  # pragma: no cover - defensive: never break logging
            return True
        redacted = redact_service_key_query(message)
        if redacted != message:
            record.msg = redacted
            record.args = ()
        return True


def harden_http_logging() -> None:
    """Install the service-key redaction filter and keep HTTP transport logs at WARNING.

    Idempotent. The level is only raised when the logger has no explicit level so a caller
    that deliberately enabled httpx debug logging still gets redacted output.
    """

    for name in _HTTP_LOGGER_NAMES:
        logger = logging.getLogger(name)
        if not any(isinstance(existing, _ServiceKeyLogFilter) for existing in logger.filters):
            logger.addFilter(_ServiceKeyLogFilter())
        if logger.level == logging.NOTSET:
            logger.setLevel(logging.WARNING)


harden_http_logging()


def normalize_service_key(service_key: str) -> str:
    """Accept either data.go.kr Encoding or Decoding key form."""

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


def _payload_error_fields(payload: Any) -> tuple[str | None, str | None, str | None]:
    if not isinstance(payload, dict):
        return None, None, None

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
            result_code = str(header.get("resultCode") or "").strip()
            if result_code and result_code not in {"0", "00", "000"}:
                return (
                    str(header.get("resultMsg") or "").strip() or None,
                    None,
                    result_code,
                )

    return None, None, None


def _public_data_error_fields(response: httpx.Response) -> tuple[str | None, str | None, str | None]:
    """Extract data.go.kr error fields from JSON or XML without logging request URLs."""

    try:
        payload = response.json()
    except ValueError:
        payload = None

    fields = _payload_error_fields(payload)
    if any(fields):
        return fields

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


def _format_error(prefix: str, fields: tuple[str | None, str | None, str | None], secret: str) -> str:
    err_msg, auth_msg, reason_code = fields
    details = [prefix]
    if err_msg:
        details.append(f"error={err_msg}")
    if auth_msg:
        details.append(f"auth={auth_msg}")
    if reason_code:
        details.append(f"code={reason_code}")
    return _redact_secret(" ".join(details), secret)


def _http_error_message(response: httpx.Response, secret: str) -> str:
    fields = _public_data_error_fields(response)
    if any(fields):
        return _format_error(f"Public Data Portal request failed: HTTP {response.status_code}", fields, secret)

    body = response.text.strip().replace("\n", " ")[:300]
    message = f"Public Data Portal request failed: HTTP {response.status_code}"
    if body:
        message += f" body={body}"
    return _redact_secret(message, secret)


class PublicDataPortalClient:
    """Common data.go.kr client with single key encoding and fail-closed errors."""

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

            fields = _payload_error_fields(payload)
            if any(fields):
                raise PublicDataClientError(
                    _format_error("Public Data Portal API error:", fields, self.service_key)
                )
            return payload

        return do_request()

    def get_json(self, base_url: str, endpoint: str, **params: Any) -> dict[str, Any]:
        if not base_url.strip():
            raise ValueError("A service base URL must be configured")
        url = f"{base_url.rstrip('/')}/{endpoint.lstrip('/')}"
        return self._request(url, params)

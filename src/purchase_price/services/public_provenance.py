from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from purchase_price.evidence import canonical_payload_text, payload_sha256

_SENSITIVE_KEY_PATTERN = re.compile(
    r"(?:service[_-]?key|api[_-]?key|authorization|password|passwd|secret|token)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class PublicEvidenceProvenance:
    source_name: str
    source_record_id: str | None
    source_url: str | None
    parser_version: str
    payload_text: str
    payload_hash: str
    field_names: tuple[str, ...]

    @property
    def fingerprint(self) -> str:
        return self.payload_hash


def _validate_allow_fields(allow_fields: Iterable[str]) -> tuple[str, ...]:
    fields = tuple(dict.fromkeys(field.strip() for field in allow_fields if field.strip()))
    if not fields:
        raise ValueError("allow_fields must contain at least one field")
    sensitive = [field for field in fields if _SENSITIVE_KEY_PATTERN.search(field)]
    if sensitive:
        raise ValueError("sensitive field names cannot be allow-listed")
    return fields


def _sanitize_public_value(value: Any) -> Any:
    """Recursively remove secret-like keys from an allow-listed public response value."""

    if isinstance(value, Mapping):
        return {
            str(key): _sanitize_public_value(nested)
            for key, nested in value.items()
            if not _SENSITIVE_KEY_PATTERN.search(str(key))
        }
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_sanitize_public_value(item) for item in value]
    return value


def allow_list_public_payload(
    payload: Mapping[str, Any],
    *,
    allow_fields: Iterable[str],
) -> dict[str, Any]:
    """Return only explicitly approved public response fields.

    Unknown response keys are discarded. Secret-like field names cannot be approved, and any
    secret-like nested keys inside an otherwise public field are removed recursively. Values are
    otherwise preserved without semantic transformation so the fingerprint remains an audit marker
    for the public response fields used by the parser.
    """

    fields = _validate_allow_fields(allow_fields)
    return {
        field: _sanitize_public_value(payload[field])
        for field in fields
        if field in payload
    }


def build_public_evidence_provenance(
    *,
    source_name: str,
    payload: Mapping[str, Any],
    allow_fields: Iterable[str],
    source_record_id: str | None = None,
    source_url: str | None = None,
    parser_version: str = "v1",
) -> PublicEvidenceProvenance:
    safe_payload = allow_list_public_payload(payload, allow_fields=allow_fields)
    payload_text = canonical_payload_text(safe_payload)
    return PublicEvidenceProvenance(
        source_name=source_name.strip(),
        source_record_id=(source_record_id or "").strip() or None,
        source_url=(source_url or "").strip() or None,
        parser_version=parser_version.strip() or "v1",
        payload_text=payload_text,
        payload_hash=payload_sha256(safe_payload),
        field_names=tuple(safe_payload),
    )

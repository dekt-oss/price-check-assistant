import hashlib
import json
from collections.abc import Mapping
from typing import Any


def canonical_payload_text(payload: Mapping[str, Any] | list[Any]) -> str:
    """Return deterministic JSON used for evidence hashing and audit storage."""

    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def payload_sha256(payload: Mapping[str, Any] | list[Any]) -> str:
    text = canonical_payload_text(payload)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()

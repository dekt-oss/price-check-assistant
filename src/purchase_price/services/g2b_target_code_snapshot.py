from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

TARGET_CODE_SNAPSHOT_SCHEMA = "g2b-target-code-snapshot-v1"
TARGET_CODE_SNAPSHOT_SOURCE = "data.go.kr/G2B ShoppingMallPrdctInfoService"
TARGET_CODE_SNAPSHOT_OPERATION = "getPrdctClsfcNoUnit10Info02"


class TargetCodeSnapshotError(ValueError):
    """Raised when a persisted target-code snapshot violates its contract."""


@dataclass(frozen=True)
class TargetCodeSnapshot:
    segments: tuple[str, ...]
    codes: tuple[str, ...]
    generated_at: str
    dictionary_requests: int

    @property
    def code_count(self) -> int:
        return len(self.codes)

    def as_payload(self) -> dict[str, Any]:
        return {
            "schema": TARGET_CODE_SNAPSHOT_SCHEMA,
            "source": TARGET_CODE_SNAPSHOT_SOURCE,
            "operation": TARGET_CODE_SNAPSHOT_OPERATION,
            "segments": list(self.segments),
            "active_only": True,
            "code_count": self.code_count,
            "codes": list(self.codes),
            "generated_at": self.generated_at,
            "dictionary_requests": self.dictionary_requests,
        }

    @property
    def sha256(self) -> str:
        return hashlib.sha256(_canonical_json(self.as_payload())).hexdigest()


def target_codes_from_dictionary(
    items: Sequence[Mapping[str, Any]],
    segments: tuple[str, ...],
) -> list[str]:
    by_segment: dict[str, set[str]] = {segment: set() for segment in segments}
    for item in items:
        code = str(item.get("dtilPrdctClsfcNo") or "").strip()
        use_yn = str(item.get("useYn") or "").strip().upper()
        if len(code) != 10 or not code.isdigit() or use_yn != "Y":
            continue
        segment = code[:2]
        if segment in by_segment:
            by_segment[segment].add(code)
    return [code for segment in segments for code in sorted(by_segment[segment])]


def build_target_code_snapshot(
    *,
    dictionary_items: Sequence[Mapping[str, Any]],
    segments: tuple[str, ...],
    dictionary_requests: int,
    generated_at: datetime | None = None,
) -> TargetCodeSnapshot:
    if dictionary_requests < 1:
        raise TargetCodeSnapshotError("dictionary_requests must be positive for a live refresh")
    instant = generated_at or datetime.now(UTC)
    if instant.tzinfo is None:
        instant = instant.replace(tzinfo=UTC)
    snapshot = TargetCodeSnapshot(
        segments=segments,
        codes=tuple(target_codes_from_dictionary(dictionary_items, segments)),
        generated_at=instant.astimezone(UTC).isoformat(),
        dictionary_requests=dictionary_requests,
    )
    _validate_snapshot(snapshot)
    return snapshot


def load_target_code_snapshot(
    path: Path,
    *,
    expected_segments: tuple[str, ...],
) -> TargetCodeSnapshot:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise TargetCodeSnapshotError(f"unable to read target-code snapshot: {exc}") from exc
    if not isinstance(payload, Mapping):
        raise TargetCodeSnapshotError("target-code snapshot must be a JSON object")
    if payload.get("schema") != TARGET_CODE_SNAPSHOT_SCHEMA:
        raise TargetCodeSnapshotError("target-code snapshot schema mismatch")
    if payload.get("source") != TARGET_CODE_SNAPSHOT_SOURCE:
        raise TargetCodeSnapshotError("target-code snapshot source mismatch")
    if payload.get("operation") != TARGET_CODE_SNAPSHOT_OPERATION:
        raise TargetCodeSnapshotError("target-code snapshot operation mismatch")
    if payload.get("active_only") is not True:
        raise TargetCodeSnapshotError("target-code snapshot must contain active codes only")

    raw_segments = payload.get("segments")
    raw_codes = payload.get("codes")
    if not isinstance(raw_segments, list) or not all(isinstance(v, str) for v in raw_segments):
        raise TargetCodeSnapshotError("target-code snapshot segments must be a string list")
    segments = tuple(raw_segments)
    if segments != expected_segments:
        raise TargetCodeSnapshotError(
            f"target-code snapshot segments mismatch: expected={expected_segments!r} actual={segments!r}"
        )
    if not isinstance(raw_codes, list) or not all(isinstance(v, str) for v in raw_codes):
        raise TargetCodeSnapshotError("target-code snapshot codes must be a string list")

    try:
        dictionary_requests = int(payload.get("dictionary_requests"))
    except (TypeError, ValueError) as exc:
        raise TargetCodeSnapshotError("dictionary_requests must be an integer") from exc
    generated_at = str(payload.get("generated_at") or "").strip()
    snapshot = TargetCodeSnapshot(
        segments=segments,
        codes=tuple(raw_codes),
        generated_at=generated_at,
        dictionary_requests=dictionary_requests,
    )
    if payload.get("code_count") != snapshot.code_count:
        raise TargetCodeSnapshotError("target-code snapshot code_count does not match codes")
    _validate_snapshot(snapshot)
    return snapshot


def write_target_code_snapshot(path: Path, snapshot: TargetCodeSnapshot) -> None:
    _validate_snapshot(snapshot)
    path.parent.mkdir(parents=True, exist_ok=True)
    rendered = json.dumps(snapshot.as_payload(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temporary.write_text(rendered, encoding="utf-8")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _validate_snapshot(snapshot: TargetCodeSnapshot) -> None:
    if not snapshot.segments:
        raise TargetCodeSnapshotError("target-code snapshot segments must not be empty")
    if not snapshot.generated_at:
        raise TargetCodeSnapshotError("target-code snapshot generated_at must not be empty")
    if snapshot.dictionary_requests < 1:
        raise TargetCodeSnapshotError("target-code snapshot dictionary_requests must be positive")
    if not snapshot.codes:
        raise TargetCodeSnapshotError("target-code snapshot must contain at least one code")
    if len(snapshot.codes) != len(set(snapshot.codes)):
        raise TargetCodeSnapshotError("target-code snapshot contains duplicate codes")

    priority = {segment: index for index, segment in enumerate(snapshot.segments)}
    previous: tuple[int, str] | None = None
    for code in snapshot.codes:
        if len(code) != 10 or not code.isdigit():
            raise TargetCodeSnapshotError(f"invalid 10-digit target code: {code!r}")
        segment = code[:2]
        if segment not in priority:
            raise TargetCodeSnapshotError(f"target code is outside configured segments: {code}")
        current = (priority[segment], code)
        if previous is not None and current <= previous:
            raise TargetCodeSnapshotError("target-code snapshot order is not canonical")
        previous = current


def _canonical_json(payload: Mapping[str, Any]) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from botocore.exceptions import BotoCoreError, ClientError

from purchase_price.config import Settings
from purchase_price.services.mfds_identity_r2 import (
    MFDS_IDENTITY_POINTER_STATE,
)
from purchase_price.storage.r2 import R2ConfigurationError, R2IntegrityError
from purchase_price.storage.r2_state import R2OperationalStateStore

MFDS_IDENTITY_PIPELINE_STATE = "mfds-identity-pipeline"


@dataclass(frozen=True)
class MfdsIdentityCollectionStatus:
    status: str
    row_count: int
    source_total_count: int | None
    next_page: int | None
    cycle: int
    complete_cycles: int
    cycle_rows_seen: int
    rows_per_page: int | None
    updated_at: str | None
    stored_bytes: int
    mode: str

    @property
    def first_backfill_complete(self) -> bool:
        return self.complete_cycles >= 1

    @property
    def progress_fraction(self) -> float | None:
        total = self.source_total_count
        if total is None or total <= 0:
            return None
        if self.first_backfill_complete:
            return 1.0
        return min(max(self.cycle_rows_seen / total, 0.0), 1.0)

    @property
    def progress_percent(self) -> float | None:
        fraction = self.progress_fraction
        return None if fraction is None else fraction * 100.0


@dataclass(frozen=True)
class MfdsCollectionPlan:
    mode: str
    chunks: int
    pages_per_chunk: int
    rows_per_page: int
    reason: str


def _int(value: object | None, default: int = 0) -> int:
    try:
        return int(value or default)
    except (TypeError, ValueError):
        return default


def build_mfds_identity_collection_status(
    *,
    pointer: Mapping[str, Any] | None,
    pipeline: Mapping[str, Any] | None,
) -> MfdsIdentityCollectionStatus:
    pointer = pointer or {}
    pipeline = pipeline or {}
    complete_cycles = max(_int(pipeline.get("complete_cycles")), 0)
    next_page = max(_int(pipeline.get("next_page"), 1), 1) if pipeline else None
    persisted_rows_per_page = pipeline.get("rows_per_page")
    rows_per_page = (
        max(_int(persisted_rows_per_page), 1)
        if persisted_rows_per_page not in (None, "")
        else (100 if next_page and next_page > 1 and complete_cycles == 0 else None)
    )
    persisted_cycle_rows = pipeline.get("cycle_rows_seen")
    if persisted_cycle_rows not in (None, ""):
        cycle_rows_seen = max(_int(persisted_cycle_rows), 0)
    elif next_page is not None and rows_per_page is not None and complete_cycles == 0:
        cycle_rows_seen = max((next_page - 1) * rows_per_page, 0)
    else:
        cycle_rows_seen = 0

    return MfdsIdentityCollectionStatus(
        status="available" if pointer or pipeline else "not_ingested",
        row_count=max(_int(pointer.get("row_count")), 0),
        source_total_count=(
            max(_int(pipeline.get("last_total_count")), 0)
            if pipeline.get("last_total_count") not in (None, "")
            else None
        ),
        next_page=next_page,
        cycle=max(_int(pipeline.get("cycle"), 1), 1),
        complete_cycles=complete_cycles,
        cycle_rows_seen=cycle_rows_seen,
        rows_per_page=rows_per_page,
        updated_at=str(pointer.get("updated_at") or pipeline.get("updated_at") or "").strip()
        or None,
        stored_bytes=max(_int(pointer.get("stored_bytes")), 0),
        mode="rolling_refresh" if complete_cycles >= 1 else "backfill",
    )


def get_mfds_identity_collection_status(
    *,
    settings: Settings | None = None,
) -> MfdsIdentityCollectionStatus:
    settings = settings or Settings()
    if not settings.r2_configured:
        return MfdsIdentityCollectionStatus(
            status="unavailable",
            row_count=0,
            source_total_count=None,
            next_page=None,
            cycle=1,
            complete_cycles=0,
            cycle_rows_seen=0,
            rows_per_page=None,
            updated_at=None,
            stored_bytes=0,
            mode="unavailable",
        )
    try:
        store = R2OperationalStateStore.from_settings(settings)
        pointer = store.read_json(MFDS_IDENTITY_POINTER_STATE)
        pipeline = store.read_json(MFDS_IDENTITY_PIPELINE_STATE)
        return build_mfds_identity_collection_status(pointer=pointer, pipeline=pipeline)
    except (
        BotoCoreError,
        ClientError,
        OSError,
        R2ConfigurationError,
        R2IntegrityError,
        ValueError,
    ):
        return MfdsIdentityCollectionStatus(
            status="unavailable",
            row_count=0,
            source_total_count=None,
            next_page=None,
            cycle=1,
            complete_cycles=0,
            cycle_rows_seen=0,
            rows_per_page=None,
            updated_at=None,
            stored_bytes=0,
            mode="unavailable",
        )


def choose_mfds_collection_plan(
    *,
    complete_cycles: int,
    event_name: str,
    schedule: str | None,
    requested_chunks: int = 5,
    requested_pages_per_chunk: int = 200,
    requested_rows_per_page: int = 100,
) -> MfdsCollectionPlan:
    chunks = max(int(requested_chunks), 1)
    pages = max(int(requested_pages_per_chunk), 1)
    rows = max(int(requested_rows_per_page), 1)

    if complete_cycles < 1:
        return MfdsCollectionPlan(
            mode="backfill",
            chunks=chunks,
            pages_per_chunk=pages,
            rows_per_page=rows,
            reason="first full MFDS source cycle is still in progress",
        )

    if event_name == "schedule" and schedule == "23 12 * * *":
        return MfdsCollectionPlan(
            mode="maintenance_skip",
            chunks=0,
            pages_per_chunk=pages,
            rows_per_page=rows,
            reason="secondary daily schedule is skipped after first full cycle",
        )

    if event_name == "workflow_dispatch":
        return MfdsCollectionPlan(
            mode="manual",
            chunks=chunks,
            pages_per_chunk=pages,
            rows_per_page=rows,
            reason="manual dispatch keeps explicitly requested collection size",
        )

    return MfdsCollectionPlan(
        mode="rolling_refresh",
        chunks=1,
        pages_per_chunk=200,
        rows_per_page=100,
        reason="first full cycle completed; run one daily rolling-refresh checkpoint",
    )


def format_status_updated_at(value: str | None) -> str | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            return parsed.strftime("%Y-%m-%d %H:%M")
        return parsed.astimezone(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d %H:%M KST")
    except ValueError:
        return value

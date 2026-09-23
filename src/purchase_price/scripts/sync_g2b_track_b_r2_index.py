from __future__ import annotations

import argparse
import json
import tempfile
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, func, inspect, select
from sqlalchemy.orm import sessionmaker

from purchase_price.config import Settings
from purchase_price.db import Base
from purchase_price.models import TrackBDeliveryLine
from purchase_price.scripts.import_g2b_track_b_r2_to_db import TRACK_B_PAGE_OPERATION
from purchase_price.scripts.import_g2b_track_b_r2_to_db import run as import_r2_pages
from purchase_price.services.g2b_track_b_normalization import TrackBRawPage
from purchase_price.services.track_b_db_quote_comparison import ingest_track_b_page
from purchase_price.services.track_b_pipeline_state import (
    BOOTSTRAP_LAST_OBJECT_KEY,
    BOOTSTRAP_MIN_R2_OBJECTS,
    SERVING_INDEX_STATE_NAME,
    STATE_NAME,
    TrackBPipelineState,
)
from purchase_price.services.track_b_supplemental_state import (
    SUPPLEMENTAL_STATE_NAME,
    SupplementalTrackBState,
)
from purchase_price.storage.r2_reader import R2RawEvidenceReader, R2RawObject
from purchase_price.storage.r2_serving_index import (
    SERVING_INDEX_SCHEMA,
    R2ServingIndexRef,
    R2ServingIndexStore,
)
from purchase_price.storage.r2_state import R2OperationalStateStore

POINTER_SCHEMA = "track-b-serving-index-pointer-v1"



_REQUIRED_SERVING_V2_COLUMNS = {
    "contract_delivery_type",
    "contract_type",
    "delivery_condition",
}


def _serving_schema_is_current(engine) -> bool:
    try:
        columns = {
            str(column["name"])
            for column in inspect(engine).get_columns("track_b_delivery_lines")
        }
    except Exception:
        return False
    return _REQUIRED_SERVING_V2_COLUMNS.issubset(columns)

def _now() -> str:
    return datetime.now(UTC).isoformat()


def _ref_from_pointer(payload: Mapping[str, Any]) -> R2ServingIndexRef:
    if payload.get("schema") != POINTER_SCHEMA:
        raise ValueError("Track B serving-index pointer schema mismatch")
    key = str(payload.get("key") or "").strip()
    sha256 = str(payload.get("sha256") or "").strip()
    if not key or len(sha256) != 64:
        raise ValueError("Track B serving-index pointer is incomplete")
    return R2ServingIndexRef(
        key=key,
        sha256=sha256,
        stored_bytes=int(payload.get("stored_bytes") or 0),
        uncompressed_bytes=int(payload.get("uncompressed_bytes") or 0),
    )


def _load_or_bootstrap_pipeline_state(
    *,
    state_store: R2OperationalStateStore,
    reader: R2RawEvidenceReader,
) -> tuple[TrackBPipelineState, bool]:
    """Load pipeline state or synthesize a validated legacy state in memory.

    The historical R2 corpus predates the daily-pipeline state object. A missing state object is
    therefore not equivalent to an empty corpus. Recovery is allowed only when the same batch-004
    proof used by the daily collector is present: at least the validated object count and the known
    content-addressed proof object. Otherwise fail closed rather than guessing a collection cursor.

    A synthesized state is deliberately *not* persisted here. The caller commits it only after the
    serving-index pointer is successfully published, so a failed bootstrap retry preserves the
    `state_recovered=true` audit signal instead of looking like a normal pre-existing state.
    """

    payload = state_store.read_json(STATE_NAME)
    if payload is not None:
        return TrackBPipelineState.from_payload(payload), False

    objects = reader.list_public_json(source_operation=TRACK_B_PAGE_OPERATION)
    keys = {obj.key for obj in objects}
    if len(objects) < BOOTSTRAP_MIN_R2_OBJECTS or BOOTSTRAP_LAST_OBJECT_KEY not in keys:
        raise RuntimeError(
            "cannot recover missing Track B pipeline state: existing R2 evidence does not match "
            "the validated batch-004 bootstrap proof"
        )

    return TrackBPipelineState.bootstrap(), True


def _raw_object_for_key(reader: R2RawEvidenceReader, key: str) -> R2RawObject:
    prefix = f"{reader.raw_prefix}/{TRACK_B_PAGE_OPERATION}/"
    if not key.startswith(prefix) or not key.endswith(".json.gz"):
        raise ValueError(f"pending Track B key is outside the expected operation prefix: {key}")
    digest = key.rsplit("/", 1)[-1][: -len(".json.gz")]
    if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
        raise ValueError(f"pending Track B key lacks a valid SHA-256 digest: {key}")
    return R2RawObject(
        bucket=reader.bucket,
        key=key,
        payload_hash=digest,
        stored_bytes=0,
        last_modified=None,
    )


def _sync_exact_keys(*, reader: R2RawEvidenceReader, session_factory, keys: list[str]) -> dict[str, int]:
    totals = {
        "objects_scanned": 0,
        "inserted": 0,
        "replayed": 0,
        "invalid_rows": 0,
        "conflicts": 0,
    }
    for key in dict.fromkeys(keys):
        obj = _raw_object_for_key(reader, key)
        payload = reader.get_public_json(obj)
        if not isinstance(payload, Mapping):
            raise ValueError(f"Track B R2 page must be a JSON object: {key}")
        with session_factory() as session, session.begin():
            result = ingest_track_b_page(
                session,
                TrackBRawPage(
                    payload=payload,
                    raw_object_key=obj.key,
                    raw_payload_sha256=obj.payload_hash,
                ),
            )
        totals["objects_scanned"] += 1
        totals["inserted"] += result.inserted
        totals["replayed"] += result.replayed
        totals["invalid_rows"] += result.invalid_rows
        totals["conflicts"] += result.conflicts
    return totals


def _full_bootstrap(*, reader: R2RawEvidenceReader, session_factory, max_objects: int) -> dict[str, int]:
    totals = {
        "objects_scanned": 0,
        "inserted": 0,
        "replayed": 0,
        "invalid_rows": 0,
        "conflicts": 0,
    }
    cursor: str | None = None
    while totals["objects_scanned"] < max_objects:
        remaining = max_objects - totals["objects_scanned"]
        report = import_r2_pages(
            reader=reader,
            session_factory=session_factory,
            limit=min(1000, remaining),
            cursor=cursor,
        )
        for field in totals:
            totals[field] += int(report.get(field) or 0)
        cursor = report.get("resume_cursor") or cursor
        if not report.get("has_more"):
            return totals
        if int(report.get("objects_scanned") or 0) == 0:
            raise RuntimeError("Track B R2 serving-index bootstrap cursor did not advance")
    raise RuntimeError(f"Track B R2 serving-index bootstrap exceeded {max_objects} objects")


def sync(*, max_bootstrap_objects: int, output: Path) -> int:
    settings = Settings()
    if not settings.r2_configured:
        raise RuntimeError("R2 configuration is required for Track B serving-index sync")

    state_store = R2OperationalStateStore.from_settings(settings)
    reader = R2RawEvidenceReader.from_settings(settings)
    pipeline, state_recovered = _load_or_bootstrap_pipeline_state(
        state_store=state_store,
        reader=reader,
    )
    supplemental_payload = state_store.read_json(SUPPLEMENTAL_STATE_NAME)
    supplemental = (
        SupplementalTrackBState.from_payload(supplemental_payload)
        if supplemental_payload is not None
        else None
    )
    pointer = state_store.read_json(SERVING_INDEX_STATE_NAME)
    artifact_store = R2ServingIndexStore.from_settings(settings)

    with tempfile.TemporaryDirectory(prefix="track-b-r2-index-") as temp_dir:
        db_path = Path(temp_dir) / "track-b-serving.sqlite"
        previous_ref: R2ServingIndexRef | None = None
        mode = "full-bootstrap"
        base_pending_keys = list(pipeline.pending_object_keys)
        supplemental_pending_keys = (
            list(supplemental.pending_object_keys) if supplemental is not None else []
        )
        indexed_keys = list(dict.fromkeys([*base_pending_keys, *supplemental_pending_keys]))

        if pointer is not None:
            previous_ref = _ref_from_pointer(pointer)
            artifact_store.download_sqlite(previous_ref, db_path)
            mode = "incremental"

        engine = create_engine(f"sqlite+pysqlite:///{db_path}")
        if mode == "incremental" and not _serving_schema_is_current(engine):
            engine.dispose()
            db_path.unlink(missing_ok=True)
            engine = create_engine(f"sqlite+pysqlite:///{db_path}")
            mode = "schema-rebuild"

        Base.metadata.create_all(engine, tables=[TrackBDeliveryLine.__table__])
        session_factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
        try:
            if mode in {"full-bootstrap", "schema-rebuild"}:
                report = _full_bootstrap(
                    reader=reader,
                    session_factory=session_factory,
                    max_objects=max_bootstrap_objects,
                )
            elif indexed_keys:
                report = _sync_exact_keys(
                    reader=reader,
                    session_factory=session_factory,
                    keys=indexed_keys,
                )
            else:
                report = {
                    "objects_scanned": 0,
                    "inserted": 0,
                    "replayed": 0,
                    "invalid_rows": 0,
                    "conflicts": 0,
                }

            with session_factory() as session:
                row_count = int(
                    session.scalar(select(func.count()).select_from(TrackBDeliveryLine)) or 0
                )
            with engine.begin() as connection:
                connection.exec_driver_sql("PRAGMA optimize")
        finally:
            engine.dispose()

        if mode == "incremental" and not indexed_keys:
            final = {
                "status": "NO_CHANGE",
                "mode": mode,
                "serving_schema": SERVING_INDEX_SCHEMA,
                "state_recovered": state_recovered,
                "row_count": row_count,
                **report,
            }
            if state_recovered:
                pipeline.mark_pending_indexed(
                    [],
                    {**report, "mode": mode, "state_recovered": True, "row_count": row_count},
                )
                state_store.write_json(STATE_NAME, pipeline.to_payload())
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(
                json.dumps(final, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            print(json.dumps(final, ensure_ascii=False, sort_keys=True))
            return 0

        ref = artifact_store.put_sqlite(db_path)
        pointer_payload = {
            "schema": POINTER_SCHEMA,
            "key": ref.key,
            "sha256": ref.sha256,
            "stored_bytes": ref.stored_bytes,
            "uncompressed_bytes": ref.uncompressed_bytes,
            "row_count": row_count,
            "updated_at": _now(),
            "mode": mode,
            "serving_schema": SERVING_INDEX_SCHEMA,
            "state_recovered": state_recovered,
            "collection_cursor": {
                "code_index": pipeline.collection_cursor.code_index,
                "page_no": pipeline.collection_cursor.page_no,
            },
            "supplemental_target_count": (
                len(supplemental.target_codes) if supplemental is not None else 0
            ),
        }
        state_store.write_json(SERVING_INDEX_STATE_NAME, pointer_payload)
        pipeline.mark_pending_indexed(
            [key for key in indexed_keys if key in set(base_pending_keys)],
            {**report, "mode": mode, "state_recovered": state_recovered, "row_count": row_count},
        )
        state_store.write_json(STATE_NAME, pipeline.to_payload())
        if supplemental is not None:
            supplemental.mark_pending_indexed(
                [key for key in indexed_keys if key in set(supplemental_pending_keys)],
                {**report, "mode": mode, "row_count": row_count},
            )
            state_store.write_json(SUPPLEMENTAL_STATE_NAME, supplemental.to_payload())

        if previous_ref is not None and previous_ref.key != ref.key:
            try:
                artifact_store.delete(previous_ref.key)
            except Exception:
                # New pointer is already committed. A stale rebuildable artifact is preferable to
                # failing the live index because cleanup permissions were narrower.
                pass

        final = {
            "status": "PARTIAL" if report["invalid_rows"] or report["conflicts"] else "SUCCESS",
            "mode": mode,
            "serving_schema": SERVING_INDEX_SCHEMA,
            "state_recovered": state_recovered,
            "row_count": row_count,
            "index_key": ref.key,
            "index_sha256": ref.sha256,
            "stored_bytes": ref.stored_bytes,
            "uncompressed_bytes": ref.uncompressed_bytes,
            **report,
        }
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(final, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(json.dumps(final, ensure_ascii=False, sort_keys=True))
        return 0


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build/update the Track B SQLite serving index in R2")
    parser.add_argument("--max-bootstrap-objects", type=int, default=100000)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("artifacts/track-b-daily/r2-serving-index.json"),
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    if args.max_bootstrap_objects < 1:
        raise ValueError("max-bootstrap-objects must be positive")
    return sync(max_bootstrap_objects=args.max_bootstrap_objects, output=args.output)


if __name__ == "__main__":
    raise SystemExit(main())

"""The serving-index sync adds the search side index to an existing file and publishes it once."""

from __future__ import annotations

import json
import shutil
import sqlite3
from datetime import date
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from purchase_price.db import Base
from purchase_price.models import TrackBDeliveryLine
from purchase_price.scripts import sync_g2b_track_b_r2_index as sync_script
from purchase_price.services.matching import normalize_text
from purchase_price.services.track_b_pipeline_state import (
    SERVING_INDEX_STATE_NAME,
    STATE_NAME,
    TrackBPipelineState,
)
from purchase_price.services.track_b_search_index import SEARCH_INDEX_VERSION, SEARCH_TABLES
from purchase_price.storage.r2_serving_index import SERVING_INDEX_SCHEMA, R2ServingIndexRef


def _line(number: int, *, title: str, product_class: str, model: str | None, supplier: str, when: date):
    return TrackBDeliveryLine(
        delivery_request_number=f"R{number:04d}",
        change_order="00",
        change_order_number=0,
        product_sequence="1",
        item_sha256=f"{number:064d}",
        identity_conflict=False,
        identity_conflict_count=0,
        raw_object_key=f"raw/R{number:04d}.json.gz",
        raw_payload_sha256="b" * 64,
        detail_code="4217210101",
        product_title=title,
        product_class=product_class,
        class_key=normalize_text(product_class) or None,
        model_name=model,
        model_qualifier_verified_as_origin=False,
        model_key=normalize_text(model) or None,
        unit_price=Decimal("1000000"),
        quantity=Decimal("1"),
        unit="EA",
        total_amount=Decimal("1000000"),
        amount_check="consistent",
        transaction_date=when,
        supplier=supplier,
        demand_institution="기관",
        api_params_json="{}",
    )


class FakeStateStore:
    def __init__(self, payloads: dict[str, object]) -> None:
        self.payloads = dict(payloads)

    def read_json(self, name: str):
        return self.payloads.get(name)

    def write_json(self, name: str, payload: object) -> None:
        self.payloads[name] = payload


class FakeArtifactStore:
    def __init__(self, files: dict[str, Path], tmp_path: Path) -> None:
        self.files = files
        self.tmp_path = tmp_path
        self.uploads: list[Path] = []

    def download_sqlite(self, ref: R2ServingIndexRef, destination: Path) -> Path:
        shutil.copyfile(self.files[ref.key], destination)
        return destination

    def put_sqlite(self, path: Path) -> R2ServingIndexRef:
        number = len(self.uploads) + 1
        stored = self.tmp_path / f"upload-{number}.sqlite"
        shutil.copyfile(path, stored)
        self.uploads.append(stored)
        key = f"derived/v1/track-b-serving/{number:02d}/upload-{number}.sqlite.gz"
        self.files[key] = stored
        return R2ServingIndexRef(
            key=key,
            sha256=f"{number:064d}",
            stored_bytes=stored.stat().st_size,
            uncompressed_bytes=stored.stat().st_size,
        )

    def delete(self, key: str) -> None:
        self.files.pop(key, None)


def _v3_file(path: Path) -> Path:
    engine = create_engine(f"sqlite+pysqlite:///{path}")
    Base.metadata.create_all(engine, tables=[TrackBDeliveryLine.__table__])
    with Session(engine) as session, session.begin():
        session.add_all(
            [
                _line(1, title="혈류계, Flow-c 본체", product_class="혈류계", model=None,
                      supplier="GE헬스케어코리아", when=date(2024, 3, 3)),
                _line(2, title="저출력심장충격기, 메디아나, HeartOn A16-DS", product_class="저출력심장충격기",
                      model="HeartOn A16-DS", supplier="(주)메디아나", when=date(2025, 1, 1)),
            ]
        )
    engine.dispose()
    return path


def test_sync_adds_side_index_to_existing_file_then_reports_no_change(tmp_path: Path, monkeypatch) -> None:
    previous_key = "derived/v1/track-b-serving/aa/previous.sqlite.gz"
    files = {previous_key: _v3_file(tmp_path / "previous.sqlite")}
    state = FakeStateStore(
        {
            STATE_NAME: TrackBPipelineState.bootstrap().to_payload(),
            SERVING_INDEX_STATE_NAME: {
                "schema": sync_script.POINTER_SCHEMA,
                "key": previous_key,
                "sha256": "a" * 64,
                "stored_bytes": 1,
                "uncompressed_bytes": 1,
            },
        }
    )
    artifacts = FakeArtifactStore(files, tmp_path)
    monkeypatch.setattr(sync_script, "Settings", lambda: SimpleNamespace(r2_configured=True))
    monkeypatch.setattr(sync_script.R2OperationalStateStore, "from_settings", lambda _s: state)
    monkeypatch.setattr(sync_script.R2RawEvidenceReader, "from_settings", lambda _s: object())
    monkeypatch.setattr(sync_script.R2ServingIndexStore, "from_settings", lambda _s: artifacts)

    output = tmp_path / "first.json"
    assert sync_script.sync(max_bootstrap_objects=10, output=output) == 0

    first = json.loads(output.read_text(encoding="utf-8"))
    assert first["status"] == "SUCCESS" and first["mode"] == "incremental"
    assert first["serving_schema"] == SERVING_INDEX_SCHEMA  # old app processes still accept it
    assert first["search_index"] == {
        "version": SEARCH_INDEX_VERSION,
        "created": 1,
        "added": 2,
        "indexed_rows": 2,
    }
    assert len(artifacts.uploads) == 1
    pointer = state.payloads[SERVING_INDEX_STATE_NAME]
    assert pointer["search_index"]["indexed_rows"] == 2
    with sqlite3.connect(artifacts.uploads[0]) as connection:
        names = {row[0] for row in connection.execute("SELECT name FROM sqlite_master")}
    assert set(SEARCH_TABLES) <= names

    output = tmp_path / "second.json"
    assert sync_script.sync(max_bootstrap_objects=10, output=output) == 0

    second = json.loads(output.read_text(encoding="utf-8"))
    assert second["status"] == "NO_CHANGE"
    assert second["search_index"]["added"] == 0
    assert len(artifacts.uploads) == 1

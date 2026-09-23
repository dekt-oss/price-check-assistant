from __future__ import annotations

from sqlalchemy import create_engine

from purchase_price.db import Base
from purchase_price.models import TrackBDeliveryLine
from purchase_price.scripts.sync_g2b_track_b_r2_index import _serving_schema_is_current


def test_serving_schema_v2_detects_required_condition_columns(tmp_path) -> None:
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'current.sqlite'}")
    Base.metadata.create_all(engine, tables=[TrackBDeliveryLine.__table__])

    assert _serving_schema_is_current(engine) is True
    engine.dispose()


def test_serving_schema_v1_is_detected_as_legacy(tmp_path) -> None:
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'legacy.sqlite'}")
    with engine.begin() as connection:
        connection.exec_driver_sql(
            """
            CREATE TABLE track_b_delivery_lines (
                id INTEGER PRIMARY KEY,
                delivery_request_number VARCHAR(120) NOT NULL
            )
            """
        )

    assert _serving_schema_is_current(engine) is False
    engine.dispose()

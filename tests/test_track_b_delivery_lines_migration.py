from pathlib import Path

import sqlalchemy as sa
from alembic.config import Config

from alembic import command
from purchase_price.config import get_settings
from purchase_price.models import TrackBDeliveryLine

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_track_b_serving_table_migrates_and_downgrades(tmp_path: Path, monkeypatch) -> None:
    database_url = f"sqlite+pysqlite:///{(tmp_path / 'migration.db').as_posix()}"
    monkeypatch.setenv("DATABASE_URL", database_url)
    get_settings.cache_clear()
    config = Config(str(REPO_ROOT / "alembic.ini"))
    command.upgrade(config, "head")
    engine = sa.create_engine(database_url)
    inspector = sa.inspect(engine)
    assert "track_b_delivery_lines" in inspector.get_table_names()
    assert {column["name"] for column in inspector.get_columns("track_b_delivery_lines")} == set(
        TrackBDeliveryLine.__table__.columns.keys()
    )
    unique_names = {
        item["name"] for item in inspector.get_unique_constraints("track_b_delivery_lines")
    }
    assert {"uq_track_b_stable_identity", "uq_track_b_numeric_change_order"} <= unique_names
    command.downgrade(config, "0002_observation_provenance")
    assert "track_b_delivery_lines" not in sa.inspect(engine).get_table_names()
    engine.dispose()
    get_settings.cache_clear()

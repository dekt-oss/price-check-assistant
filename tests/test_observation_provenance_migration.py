from pathlib import Path

import sqlalchemy as sa
from alembic.config import Config

from alembic import command
from purchase_price.config import get_settings

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_0002_backfills_legacy_observation_and_enforces_provenance(
    tmp_path: Path, monkeypatch
) -> None:
    db_path = tmp_path / "migration.db"
    database_url = f"sqlite+pysqlite:///{db_path.as_posix()}"
    monkeypatch.setenv("DATABASE_URL", database_url)
    get_settings.cache_clear()

    config = Config(str(REPO_ROOT / "alembic.ini"))
    command.upgrade(config, "0001_phase0_foundation")

    engine = sa.create_engine(database_url)
    with engine.begin() as connection:
        connection.execute(sa.text("INSERT INTO products (product_name) VALUES ('Legacy Monitor')"))
        product_id = connection.execute(sa.text("SELECT id FROM products")).scalar_one()
        connection.execute(
            sa.text(
                """
                INSERT INTO price_observations (
                    product_id, evidence_id, price, evidence_type, currency,
                    source_type, source_name, collected_at, match_grade
                ) VALUES (
                    :product_id, NULL, 1000000, 'CONTRACT_UNIT_PRICE', 'KRW',
                    'PUBLIC_CONTRACT', 'legacy-source', '2026-09-04', 'A'
                )
                """
            ),
            {"product_id": product_id},
        )

    command.upgrade(config, "head")

    inspector = sa.inspect(engine)
    columns = {column["name"]: column for column in inspector.get_columns("price_observations")}
    assert columns["evidence_id"]["nullable"] is False
    assert "derivation_version" in columns
    assert "comparison_scope" in columns
    unique_names = {
        constraint["name"] for constraint in inspector.get_unique_constraints("price_observations")
    }
    assert "uq_price_observation_derivation" in unique_names

    with engine.begin() as connection:
        migrated = connection.execute(
            sa.text(
                """
                SELECT evidence_id, derivation_version, comparison_scope
                FROM price_observations
                """
            )
        ).mappings().one()
        assert migrated["evidence_id"] is not None
        assert migrated["derivation_version"] == "legacy-v1"
        assert migrated["comparison_scope"] == "OBSERVED_ONLY"

        evidence = connection.execute(
            sa.text(
                """
                SELECT parser_version, payload_text
                FROM raw_evidence WHERE id = :evidence_id
                """
            ),
            {"evidence_id": migrated["evidence_id"]},
        ).mappings().one()
        assert evidence["parser_version"] == "legacy-observation-backfill-v1"
        assert "synthetic migration backfill" in evidence["payload_text"]

    command.downgrade(config, "0001_phase0_foundation")
    inspector = sa.inspect(engine)
    downgraded_columns = {
        column["name"]: column for column in inspector.get_columns("price_observations")
    }
    assert "derivation_version" not in downgraded_columns
    assert "comparison_scope" not in downgraded_columns
    assert downgraded_columns["evidence_id"]["nullable"] is True

    with engine.begin() as connection:
        assert connection.execute(sa.text("SELECT evidence_id FROM price_observations")).scalar_one() is None
        assert (
            connection.execute(
                sa.text(
                    "SELECT COUNT(*) FROM raw_evidence WHERE parser_version = "
                    "'legacy-observation-backfill-v1'"
                )
            ).scalar_one()
            == 0
        )

    engine.dispose()
    get_settings.cache_clear()

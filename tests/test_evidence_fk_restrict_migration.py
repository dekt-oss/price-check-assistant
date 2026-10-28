"""Review B-04: deleting raw evidence an observation uses is refused, never a NOT NULL error.

Runs on SQLite by default. The evidence-fk-postgres workflow sets EVIDENCE_FK_POSTGRES_URL to a
throwaway PostgreSQL service so the same checks run against the production database engine.
"""

import os
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.config import Config

from alembic import command
from purchase_price.config import get_settings

REPO_ROOT = Path(__file__).resolve().parents[1]
POSTGRES_URL = os.environ.get("EVIDENCE_FK_POSTGRES_URL", "").strip()


@pytest.fixture(params=["sqlite", "postgresql"])
def database_url(request, tmp_path: Path, monkeypatch) -> str:
    if request.param == "postgresql":
        if not POSTGRES_URL:
            pytest.skip("EVIDENCE_FK_POSTGRES_URL is not set (the evidence-fk-postgres workflow sets it)")
        url = POSTGRES_URL
        engine = sa.create_engine(url)
        with engine.begin() as connection:
            connection.execute(sa.text("DROP SCHEMA public CASCADE"))
            connection.execute(sa.text("CREATE SCHEMA public"))
        engine.dispose()
    else:
        url = f"sqlite+pysqlite:///{(tmp_path / 'fk.db').as_posix()}"
    monkeypatch.setenv("DATABASE_URL", url)
    get_settings.cache_clear()
    yield url
    get_settings.cache_clear()


def _engine(url: str) -> sa.Engine:
    engine = sa.create_engine(url)
    if engine.dialect.name == "sqlite":

        @sa.event.listens_for(engine, "connect")
        def _foreign_keys_on(dbapi_connection, _record) -> None:
            dbapi_connection.execute("PRAGMA foreign_keys=ON")

    return engine


def _seed(engine: sa.Engine) -> int:
    with engine.begin() as connection:
        product_id = connection.execute(
            sa.text("INSERT INTO products (product_name) VALUES ('Monitor') RETURNING id")
        ).scalar_one()
        evidence_id = connection.execute(
            sa.text(
                """
                INSERT INTO raw_evidence (source_name, payload_text, payload_hash, parser_version)
                VALUES ('g2b', '{}', :hash, 'v1') RETURNING id
                """
            ),
            {"hash": "a" * 64},
        ).scalar_one()
        connection.execute(
            sa.text(
                """
                INSERT INTO price_observations (
                    product_id, evidence_id, price, evidence_type, currency, source_type,
                    source_name, collected_at, match_grade, derivation_version, comparison_scope
                ) VALUES (
                    :product_id, :evidence_id, 1000000, 'CONTRACT_UNIT_PRICE', 'KRW',
                    'PUBLIC_CONTRACT', 'g2b', '2026-10-28', 'A', 'v1', 'OBSERVED_ONLY'
                )
                """
            ),
            {"product_id": product_id, "evidence_id": evidence_id},
        )
    return evidence_id


def _evidence_fk(engine: sa.Engine) -> dict:
    (fk,) = [
        fk
        for fk in sa.inspect(engine).get_foreign_keys("price_observations")
        if fk["referred_table"] == "raw_evidence"
    ]
    return fk


def test_deleting_used_evidence_is_refused_and_downgrade_restores_the_old_rule(database_url) -> None:
    config = Config(str(REPO_ROOT / "alembic.ini"))
    command.upgrade(config, "head")
    engine = _engine(database_url)

    fk = _evidence_fk(engine)
    assert fk["name"] == "fk_price_observations_evidence_id"
    assert (fk["options"].get("ondelete") or "").upper() == "RESTRICT"

    evidence_id = _seed(engine)
    with pytest.raises(sa.exc.IntegrityError) as refused, engine.begin() as connection:
        connection.execute(sa.text("DELETE FROM raw_evidence WHERE id = :id"), {"id": evidence_id})
    assert "not null" not in str(refused.value).lower()
    with engine.connect() as connection:
        assert connection.execute(sa.text("SELECT count(*) FROM raw_evidence")).scalar_one() == 1
        assert connection.execute(sa.text("SELECT count(*) FROM price_observations")).scalar_one() == 1
    engine.dispose()

    command.downgrade(config, "0006_track_b_business_name")
    engine = _engine(database_url)
    assert (_evidence_fk(engine)["options"].get("ondelete") or "").upper() == "SET NULL"
    engine.dispose()

    command.upgrade(config, "head")
    engine = _engine(database_url)
    assert (_evidence_fk(engine)["options"].get("ondelete") or "").upper() == "RESTRICT"
    with engine.connect() as connection:
        assert connection.execute(sa.text("SELECT count(*) FROM price_observations")).scalar_one() == 1
    engine.dispose()

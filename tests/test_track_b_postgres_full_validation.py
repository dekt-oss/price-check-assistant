import pytest

from purchase_price.scripts.validate_g2b_track_b_postgres_full import require_postgres


def test_full_validation_refuses_non_postgres_database() -> None:
    with pytest.raises(ValueError, match="isolated PostgreSQL"):
        require_postgres("sqlite+pysqlite:///:memory:")


def test_full_validation_accepts_postgres_database() -> None:
    require_postgres("postgresql+psycopg://user:pass@localhost/db")

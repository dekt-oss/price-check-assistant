"""Refuse to delete raw evidence that a price observation still points at.

Revision ID: 0007_evidence_fk_restrict
Revises: 0006_track_b_business_name

0001 declared price_observations.evidence_id with ON DELETE SET NULL, and 0002 made the column
NOT NULL, so deleting a raw_evidence row failed with a NOT NULL error instead of a clear refusal
(review B-04). Evidence is immutable provenance: an observation must never lose it, so the
foreign key becomes ON DELETE RESTRICT. Allowing NULL would admit observations without a source.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0007_evidence_fk_restrict"
down_revision: str | None = "0006_track_b_business_name"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

FK_NAME = "fk_price_observations_evidence_id"
# 0001 left the constraint unnamed: PostgreSQL named it <table>_<column>_fkey; SQLite reflects it
# without a name, so batch mode names it through this convention before dropping it.
POSTGRES_DEFAULT_NAME = "price_observations_evidence_id_fkey"
SQLITE_CONVENTION = {"fk": "fk_%(table_name)s_%(column_0_name)s"}


def _replace_fk(*, old_name: str | None, ondelete: str, new_name: str) -> None:
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table(
            "price_observations", recreate="always", naming_convention=SQLITE_CONVENTION
        ) as batch_op:
            batch_op.drop_constraint(old_name or FK_NAME, type_="foreignkey")
            batch_op.create_foreign_key(
                new_name, "raw_evidence", ["evidence_id"], ["id"], ondelete=ondelete
            )
        return
    op.drop_constraint(old_name or POSTGRES_DEFAULT_NAME, "price_observations", type_="foreignkey")
    op.create_foreign_key(
        new_name, "price_observations", "raw_evidence", ["evidence_id"], ["id"], ondelete=ondelete
    )


def upgrade() -> None:
    _replace_fk(old_name=None, ondelete="RESTRICT", new_name=FK_NAME)


def downgrade() -> None:
    sqlite = op.get_bind().dialect.name == "sqlite"
    _replace_fk(
        old_name=FK_NAME,
        ondelete="SET NULL",
        new_name=FK_NAME if sqlite else POSTGRES_DEFAULT_NAME,
    )

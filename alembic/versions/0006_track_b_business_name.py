"""Add the Track B 사업명 (business name) field.

Revision ID: 0006_track_b_business_name
Revises: 0005_hospital_intelligence
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0006_track_b_business_name"
down_revision: str | None = "0005_hospital_intelligence"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("track_b_delivery_lines", sa.Column("business_name", sa.Text()))


def downgrade() -> None:
    op.drop_column("track_b_delivery_lines", "business_name")

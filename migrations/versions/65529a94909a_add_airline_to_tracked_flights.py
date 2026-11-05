"""trackers: airline label on a flight

Revision ID: 65529a94909a
Revises: f76c455f823b
Create Date: 2026-11-04 18:15:23.417240

An optional carrier name, shown after the route on the dashboard. It is a label
only: fares and checks stay keyed on the airports and dates.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "65529a94909a"
down_revision: str | Sequence[str] | None = "f76c455f823b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("tracked_flights", schema=None) as batch_op:
        batch_op.add_column(sa.Column("airline", sa.String(length=80), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("tracked_flights", schema=None) as batch_op:
        batch_op.drop_column("airline")

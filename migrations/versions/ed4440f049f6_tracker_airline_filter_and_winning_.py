"""trackers: airline filter and winning carrier

Revision ID: ed4440f049f6
Revises: a7c1e4f92b30
Create Date: 2026-11-11 17:45:26.859787

``airline_filter`` is a comma-separated list of IATA codes; NULL means any
airline. ``last_airline`` is the carrier on the latest successful check, so the
dashboard can show the winner without reading history. ``price_checks.airline``
keeps that carrier alongside each observation. Existing Southwest trackers are
given an explicit WN filter so the migration does not silently broaden them.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "ed4440f049f6"
down_revision: str | Sequence[str] | None = "a7c1e4f92b30"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("price_checks", schema=None) as batch_op:
        batch_op.add_column(sa.Column("airline", sa.String(length=120), nullable=True))

    with op.batch_alter_table("tracked_flights", schema=None) as batch_op:
        batch_op.add_column(sa.Column("airline_filter", sa.String(length=160), nullable=True))
        batch_op.add_column(sa.Column("last_airline", sa.String(length=120), nullable=True))

    op.execute("UPDATE tracked_flights SET airline_filter = 'WN' WHERE airline = 'Southwest'")


def downgrade() -> None:
    with op.batch_alter_table("tracked_flights", schema=None) as batch_op:
        batch_op.drop_column("last_airline")
        batch_op.drop_column("airline_filter")

    with op.batch_alter_table("price_checks", schema=None) as batch_op:
        batch_op.drop_column("airline")

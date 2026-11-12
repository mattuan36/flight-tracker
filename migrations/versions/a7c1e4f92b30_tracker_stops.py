"""trackers: stops ceiling and auto-relax markers

Revision ID: a7c1e4f92b30
Revises: 65529a94909a
Create Date: 2026-11-10 00:00:00.000000

``max_stops`` is a ceiling: 0 means non-stop, 1 means one stop or fewer and
NULL means any number of stops. Existing trackers keep NULL so the migration
never silently tightens a search. The two marker columns let the UI explain why
a tracker's stops changed, while the actual relaxation rule lives in M5.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a7c1e4f92b30"
down_revision: str | Sequence[str] | None = "65529a94909a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("tracked_flights", schema=None) as batch_op:
        batch_op.add_column(sa.Column("max_stops", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("stops_auto_relaxed_at", sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column("stops_auto_relaxed_from", sa.Integer(), nullable=True))
        batch_op.create_check_constraint(
            "max_stops_valid", "max_stops IS NULL OR max_stops IN (0, 1)"
        )
        batch_op.create_check_constraint(
            "relaxed_from_valid",
            "stops_auto_relaxed_from IS NULL OR stops_auto_relaxed_from IN (0, 1)",
        )


def downgrade() -> None:
    with op.batch_alter_table("tracked_flights", schema=None) as batch_op:
        batch_op.drop_constraint("relaxed_from_valid", type_="check")
        batch_op.drop_constraint("max_stops_valid", type_="check")
        batch_op.drop_column("stops_auto_relaxed_from")
        batch_op.drop_column("stops_auto_relaxed_at")
        batch_op.drop_column("max_stops")

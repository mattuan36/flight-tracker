"""trackers: normalize existing check intervals to daily

Revision ID: 21f7af727b75
Revises: ed4440f049f6
Create Date: 2026-11-11 17:56:43.561071

M5 makes daily the default and keeps the 6/12/24 selector for deliberate
changes. Existing rows are the old demo data, so this migration normalizes them
to 24 hours rather than leaving them on a faster cadence that would spend the
SerpAPI budget faster. The downgrade cannot recover the old per-row values and
therefore leaves the data at 24 hours.
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "21f7af727b75"
down_revision: str | Sequence[str] | None = "ed4440f049f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "UPDATE tracked_flights SET check_interval_hours = 24 WHERE check_interval_hours != 24"
    )


def downgrade() -> None:
    pass

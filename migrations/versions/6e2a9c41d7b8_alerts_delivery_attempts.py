"""alerts: delivery attempts and last error

Revision ID: 6e2a9c41d7b8
Revises: 21f7af727b75
Create Date: 2026-11-12 10:15:00.000000

M6 keeps a failed alert for the next scheduled run. ``email_attempts`` counts
total delivery attempts so the service can stop at three; ``last_attempt_at``
and ``last_error`` make a stuck mailbox diagnosable from the row itself.

Existing rows are given zero attempts, which is correct: they either have a
sent status from the demo seeder or were created before delivery was wired up.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "6e2a9c41d7b8"
down_revision: str | Sequence[str] | None = "21f7af727b75"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("alerts", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("email_attempts", sa.Integer(), nullable=False, server_default="0")
        )
        batch_op.add_column(sa.Column("last_attempt_at", sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column("last_error", sa.String(length=255), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("alerts", schema=None) as batch_op:
        batch_op.drop_column("last_error")
        batch_op.drop_column("last_attempt_at")
        batch_op.drop_column("email_attempts")

"""auth: password resets and login attempts

Revision ID: f76c455f823b
Revises: 7cd2764b2d62
Create Date: 2026-11-03 19:45:12.520191

Two tables M2 needs: single-use password reset tokens and the sign-in attempt
log that backs throttling. Timestamps stay naive DATETIME here on purpose; the
application type re-attaches UTC on read.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f76c455f823b"
down_revision: str | Sequence[str] | None = "7cd2764b2d62"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "login_attempts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("email", sa.String(length=254), nullable=True),
        sa.Column("ip", sa.String(length=45), nullable=True),
        sa.Column("attempted_at", sa.DateTime(), nullable=False),
        sa.Column("success", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_login_attempts")),
    )
    op.create_index(
        "ix_login_attempts_email_time",
        "login_attempts",
        ["email", "attempted_at"],
        unique=False,
    )
    op.create_index(
        "ix_login_attempts_ip_time", "login_attempts", ["ip", "attempted_at"], unique=False
    )

    op.create_table(
        "password_resets",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("used_at", sa.DateTime(), nullable=True),
        sa.Column("requested_ip", sa.String(length=45), nullable=True),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_password_resets_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_password_resets")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_password_resets_token_hash")),
    )


def downgrade() -> None:
    op.drop_table("password_resets")
    op.drop_index("ix_login_attempts_ip_time", table_name="login_attempts")
    op.drop_index("ix_login_attempts_email_time", table_name="login_attempts")
    op.drop_table("login_attempts")

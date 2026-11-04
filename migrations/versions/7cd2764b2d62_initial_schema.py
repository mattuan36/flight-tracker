"""initial schema

Revision ID: 7cd2764b2d62
Revises:
Create Date: 2026-11-03 19:33:39.187158

Kept deliberately dialect-neutral: plain Integer primary keys, String lengths
sized for a MySQL utf8mb4 index, booleans as tinyint, and a stored generated
column (``invites.pending_key``) rather than a partial unique index, which
MySQL does not have.

Timestamps are naive DATETIME in the database; the application's UTCDateTime
type re-attaches UTC on read, so this migration intentionally uses sa.DateTime.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "7cd2764b2d62"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "api_usage",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("calls", sa.Integer(), nullable=False),
        sa.Column("errors", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_api_usage")),
        sa.UniqueConstraint("provider", "day", name=op.f("uq_api_usage_provider_day")),
    )

    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("email", sa.String(length=254), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("display_name", sa.String(length=80), nullable=False),
        sa.Column("timezone", sa.String(length=64), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("session_version", sa.Integer(), nullable=False),
        sa.Column("last_login_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("role IN ('admin', 'member')", name=op.f("ck_users_role_valid")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.UniqueConstraint("email", name=op.f("uq_users_email")),
    )

    op.create_table(
        "invites",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("email", sa.String(length=254), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("created_by_id", sa.Integer(), nullable=True),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("used_at", sa.DateTime(), nullable=True),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.Column("accepted_user_id", sa.Integer(), nullable=True),
        sa.Column(
            "pending_key",
            sa.String(length=254),
            sa.Computed(
                "CASE WHEN used_at IS NULL AND revoked_at IS NULL THEN email ELSE NULL END",
                persisted=True,
            ),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["accepted_user_id"],
            ["users.id"],
            name=op.f("fk_invites_accepted_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"],
            ["users.id"],
            name=op.f("fk_invites_created_by_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_invites")),
        sa.UniqueConstraint("pending_key", name=op.f("uq_invites_pending_key")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_invites_token_hash")),
    )

    op.create_table(
        "tracked_flights",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("origin_iata", sa.String(length=3), nullable=False),
        sa.Column("dest_iata", sa.String(length=3), nullable=False),
        sa.Column("depart_date", sa.Date(), nullable=False),
        sa.Column("return_date", sa.Date(), nullable=True),
        sa.Column("cabin", sa.String(length=16), nullable=False),
        sa.Column("adults", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("flight_number", sa.String(length=8), nullable=True),
        sa.Column("target_price_cents", sa.Integer(), nullable=True),
        sa.Column("mode", sa.String(length=16), nullable=False),
        sa.Column("check_interval_hours", sa.Integer(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("last_checked_at", sa.DateTime(), nullable=True),
        sa.Column("last_price_cents", sa.Integer(), nullable=True),
        sa.Column("lowest_price_cents", sa.Integer(), nullable=True),
        sa.Column("last_alert_at", sa.DateTime(), nullable=True),
        sa.Column("last_alert_price_cents", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "cabin IN ('economy', 'premium_economy', 'business', 'first')",
            name=op.f("ck_tracked_flights_cabin_valid"),
        ),
        sa.CheckConstraint(
            "mode IN ('target', 'any_drop')", name=op.f("ck_tracked_flights_mode_valid")
        ),
        sa.CheckConstraint("adults >= 1", name=op.f("ck_tracked_flights_adults_positive")),
        sa.CheckConstraint(
            "check_interval_hours >= 1", name=op.f("ck_tracked_flights_interval_positive")
        ),
        sa.CheckConstraint(
            "return_date IS NULL OR return_date >= depart_date",
            name=op.f("ck_tracked_flights_return_after_depart"),
        ),
        sa.CheckConstraint(
            "target_price_cents IS NULL OR target_price_cents > 0",
            name=op.f("ck_tracked_flights_target_positive"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_tracked_flights_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tracked_flights")),
    )
    op.create_index(
        "ix_tracked_flights_due", "tracked_flights", ["is_active", "last_checked_at"], unique=False
    )
    op.create_index(
        "ix_tracked_flights_user", "tracked_flights", ["user_id", "is_active"], unique=False
    )

    op.create_table(
        "price_checks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("tracked_flight_id", sa.Integer(), nullable=False),
        sa.Column("checked_at", sa.DateTime(), nullable=False),
        sa.Column("ok", sa.Boolean(), nullable=False),
        sa.Column("price_cents", sa.Integer(), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=True),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("error", sa.String(length=255), nullable=True),
        sa.CheckConstraint(
            "ok = 0 OR price_cents IS NOT NULL", name=op.f("ck_price_checks_price_when_ok")
        ),
        sa.ForeignKeyConstraint(
            ["tracked_flight_id"],
            ["tracked_flights.id"],
            name=op.f("fk_price_checks_tracked_flight_id_tracked_flights"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_price_checks")),
    )
    op.create_index(
        "ix_price_checks_flight_time",
        "price_checks",
        ["tracked_flight_id", "checked_at"],
        unique=False,
    )

    op.create_table(
        "alerts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("tracked_flight_id", sa.Integer(), nullable=False),
        sa.Column("price_check_id", sa.Integer(), nullable=True),
        sa.Column("price_cents", sa.Integer(), nullable=False),
        sa.Column("target_cents", sa.Integer(), nullable=False),
        sa.Column("sent_at", sa.DateTime(), nullable=False),
        sa.Column("email_status", sa.String(length=16), nullable=False),
        sa.Column("idempotency_key", sa.String(length=64), nullable=False),
        sa.CheckConstraint(
            "email_status IN ('pending', 'sent', 'failed')",
            name=op.f("ck_alerts_status_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["price_check_id"],
            ["price_checks.id"],
            name=op.f("fk_alerts_price_check_id_price_checks"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["tracked_flight_id"],
            ["tracked_flights.id"],
            name=op.f("fk_alerts_tracked_flight_id_tracked_flights"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_alerts")),
        sa.UniqueConstraint("idempotency_key", name=op.f("uq_alerts_idempotency_key")),
    )
    op.create_index(
        "ix_alerts_flight_sent", "alerts", ["tracked_flight_id", "sent_at"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_alerts_flight_sent", table_name="alerts")
    op.drop_table("alerts")
    op.drop_index("ix_price_checks_flight_time", table_name="price_checks")
    op.drop_table("price_checks")
    op.drop_index("ix_tracked_flights_user", table_name="tracked_flights")
    op.drop_index("ix_tracked_flights_due", table_name="tracked_flights")
    op.drop_table("tracked_flights")
    op.drop_table("invites")
    op.drop_table("users")
    op.drop_table("api_usage")

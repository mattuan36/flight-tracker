"""Database models.

Conventions that apply everywhere:

* timestamps are timezone-aware in Python and stored as naive UTC (see
  :class:`UTCDateTime`), because MySQL has no timezone-aware type;
* money is integer cents, never floats;
* deletes cascade from ``users`` down through trackers, checks and alerts.

Schema changes go through Alembic (``migrations/``), never ``create_all`` in
production.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

from flask_login import UserMixin
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Computed,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    TypeDecorator,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from werkzeug.security import check_password_hash, generate_password_hash

from .extensions import Base

CABINS = ("economy", "premium_economy", "business", "first")
TRACKING_MODES = ("target", "any_drop")
ROLES = ("admin", "member")
EMAIL_STATUSES = ("pending", "sent", "failed")


def utcnow() -> datetime:
    """Current time as an aware UTC datetime."""
    return datetime.now(UTC)


class UTCDateTime(TypeDecorator):
    """Store naive UTC, return aware UTC.

    MySQL DATETIME has no timezone, and SQLite stores whatever string you give
    it. Mapping both ends here means application code never has to guess, and
    comparing two timestamps can never mix aware and naive values.
    """

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("refusing to store a naive datetime; pass utcnow()")
        return value.astimezone(UTC).replace(tzinfo=None)

    def process_result_value(self, value: datetime | None, dialect):
        if value is None:
            return None
        return value.replace(tzinfo=UTC)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime, default=utcnow, onupdate=utcnow, nullable=False
    )


class User(TimestampMixin, Base, UserMixin):
    __tablename__ = "users"
    __table_args__ = (CheckConstraint("role IN ('admin', 'member')", name="role_valid"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(254), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str] = mapped_column(String(80), nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), default="UTC", nullable=False)
    role: Mapped[str] = mapped_column(String(16), default="member", nullable=False)

    # Deactivating a user also bumps session_version, which invalidates every
    # existing cookie on its next request.
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    session_version: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    last_login_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)

    tracked_flights: Mapped[list[TrackedFlight]] = relationship(
        back_populates="user", cascade="all, delete-orphan", passive_deletes=True
    )

    def set_password(self, password: str) -> None:
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        if not self.password_hash:
            return False
        return check_password_hash(self.password_hash, password)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<User {self.email} role={self.role}>"


class Invite(TimestampMixin, Base):
    """A one-time signup token. The raw token is never stored, only its hash.

    ``pending_key`` is a generated column: it equals the email while the invite
    is still open and NULL otherwise, and it is unique. That is how "at most one
    pending invite per email" is enforced on both SQLite and MySQL, which has no
    partial indexes. Marking an invite used or revoked clears the key, so the
    same address can be invited again later.
    """

    __tablename__ = "invites"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(254), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    created_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    accepted_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    pending_key: Mapped[str | None] = mapped_column(
        String(254),
        Computed(
            "CASE WHEN used_at IS NULL AND revoked_at IS NULL THEN email ELSE NULL END",
            persisted=True,
        ),
        unique=True,
        nullable=True,
    )

    created_by: Mapped[User | None] = relationship(foreign_keys=[created_by_id])
    accepted_user: Mapped[User | None] = relationship(foreign_keys=[accepted_user_id])

    @property
    def is_pending(self) -> bool:
        return self.used_at is None and self.revoked_at is None and self.expires_at > utcnow()

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Invite {self.email} used={bool(self.used_at)}>"


class TrackedFlight(TimestampMixin, Base):
    """One route + date combination a user is watching."""

    __tablename__ = "tracked_flights"
    __table_args__ = (
        CheckConstraint("adults >= 1", name="adults_positive"),
        CheckConstraint(
            "target_price_cents IS NULL OR target_price_cents > 0", name="target_positive"
        ),
        CheckConstraint("check_interval_hours >= 1", name="interval_positive"),
        CheckConstraint(
            "return_date IS NULL OR return_date >= depart_date", name="return_after_depart"
        ),
        CheckConstraint(
            "cabin IN ('economy', 'premium_economy', 'business', 'first')", name="cabin_valid"
        ),
        CheckConstraint("mode IN ('target', 'any_drop')", name="mode_valid"),
        # The checker's query: active trackers whose last check is oldest.
        Index("ix_tracked_flights_due", "is_active", "last_checked_at"),
        Index("ix_tracked_flights_user", "user_id", "is_active"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)

    origin_iata: Mapped[str] = mapped_column(String(3), nullable=False)
    dest_iata: Mapped[str] = mapped_column(String(3), nullable=False)
    airline: Mapped[str | None] = mapped_column(String(80), nullable=True)
    depart_date: Mapped[date] = mapped_column(Date, nullable=False)
    return_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    cabin: Mapped[str] = mapped_column(String(16), default="economy", nullable=False)
    adults: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="GBP", nullable=False)
    flight_number: Mapped[str | None] = mapped_column(String(8), nullable=True)

    # NULL means "adopt the first price we see as the target" (see M6).
    target_price_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)
    mode: Mapped[str] = mapped_column(String(16), default="target", nullable=False)
    check_interval_hours: Mapped[int] = mapped_column(Integer, default=12, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Denormalised so the dashboard is one query.
    last_checked_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    last_price_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)
    lowest_price_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_alert_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    last_alert_price_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)

    user: Mapped[User] = relationship(back_populates="tracked_flights")
    price_checks: Mapped[list[PriceCheck]] = relationship(
        back_populates="tracked_flight",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="PriceCheck.checked_at",
    )
    alerts: Mapped[list[Alert]] = relationship(
        back_populates="tracked_flight", cascade="all, delete-orphan", passive_deletes=True
    )

    @property
    def route(self) -> str:
        return f"{self.origin_iata}-{self.dest_iata}"

    @property
    def is_below_target(self) -> bool:
        return (
            self.target_price_cents is not None
            and self.last_price_cents is not None
            and self.last_price_cents <= self.target_price_cents
        )

    @property
    def target_gap_cents(self) -> int | None:
        """How far the current fare is from the target; negative means below."""
        if self.target_price_cents is None or self.last_price_cents is None:
            return None
        return self.last_price_cents - self.target_price_cents

    @property
    def price_state(self) -> str:
        """One word the dashboard can style: paused, waiting, below, above, watching."""
        if not self.is_active:
            return "paused"
        if self.last_price_cents is None:
            return "waiting"
        if self.is_below_target:
            return "below"
        if self.target_price_cents is not None:
            return "above"
        return "watching"

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<TrackedFlight {self.route} {self.depart_date}>"


class PriceCheck(Base):
    """Append-only observation. Failed checks are recorded too."""

    __tablename__ = "price_checks"
    __table_args__ = (
        CheckConstraint("ok = 0 OR price_cents IS NOT NULL", name="price_when_ok"),
        Index("ix_price_checks_flight_time", "tracked_flight_id", "checked_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    tracked_flight_id: Mapped[int] = mapped_column(
        ForeignKey("tracked_flights.id", ondelete="CASCADE"), nullable=False
    )
    checked_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False)

    ok: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    price_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)
    currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    error: Mapped[str | None] = mapped_column(String(255), nullable=True)

    tracked_flight: Mapped[TrackedFlight] = relationship(back_populates="price_checks")

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<PriceCheck flight={self.tracked_flight_id} price={self.price_cents}>"


class Alert(Base):
    """One row per email we decided to send, so re-runs cannot double-send."""

    __tablename__ = "alerts"
    __table_args__ = (
        CheckConstraint("email_status IN ('pending', 'sent', 'failed')", name="status_valid"),
        Index("ix_alerts_flight_sent", "tracked_flight_id", "sent_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    tracked_flight_id: Mapped[int] = mapped_column(
        ForeignKey("tracked_flights.id", ondelete="CASCADE"), nullable=False
    )
    price_check_id: Mapped[int | None] = mapped_column(
        ForeignKey("price_checks.id", ondelete="SET NULL"), nullable=True
    )

    price_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    target_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    sent_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False)
    email_status: Mapped[str] = mapped_column(String(16), default="pending", nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)

    tracked_flight: Mapped[TrackedFlight] = relationship(back_populates="alerts")

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Alert flight={self.tracked_flight_id} price={self.price_cents}>"


class ApiUsage(Base):
    """Per-provider, per-day call counter for the budget guard."""

    __tablename__ = "api_usage"
    __table_args__ = (UniqueConstraint("provider", "day", name="uq_api_usage_provider_day"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    day: Mapped[date] = mapped_column(Date, nullable=False)
    calls: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    errors: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<ApiUsage {self.provider} {self.day} calls={self.calls}>"


class PasswordReset(Base):
    """A one-time password reset token, stored as a hash.

    Only the newest reset for a user is valid: requesting another marks the
    previous ones used, so a leaked link dies as soon as the owner asks again.
    """

    __tablename__ = "password_resets"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    requested_ip: Mapped[str | None] = mapped_column(String(45), nullable=True)

    user: Mapped[User] = relationship()

    @property
    def is_usable(self) -> bool:
        return self.used_at is None and self.expires_at > utcnow()


class LoginAttempt(Base):
    """Sign-in audit and the backing store for throttling.

    Deliberately in the database rather than in memory: three web workers each
    have their own memory, so counters would not be shared.
    """

    __tablename__ = "login_attempts"
    __table_args__ = (
        Index("ix_login_attempts_email_time", "email", "attempted_at"),
        Index("ix_login_attempts_ip_time", "ip", "attempted_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str | None] = mapped_column(String(254), nullable=True)
    ip: Mapped[str | None] = mapped_column(String(45), nullable=True)
    attempted_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False)
    success: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

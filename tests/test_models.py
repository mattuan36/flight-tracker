"""Model behaviour: defaults, constraints, cascades, timezone handling."""

from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError, StatementError

from app.extensions import db
from app.models import Alert, ApiUsage, Invite, PriceCheck, TrackedFlight, User, utcnow

PASSWORD = "correct-horse-battery-staple"


@pytest.fixture(autouse=True)
def _app_context(app):
    """Every test here touches the database session."""
    return app


def make_user(email: str = "friend@example.com", role: str = "member") -> User:
    user = User(email=email, display_name="Friend", role=role)
    user.set_password(PASSWORD)
    db.session.add(user)
    db.session.commit()
    return user


def make_flight(user: User, **overrides) -> TrackedFlight:
    values = {
        "user": user,
        "origin_iata": "LHR",
        "dest_iata": "JFK",
        "depart_date": date(2027, 3, 14),
        "cabin": "economy",
        "adults": 1,
        "currency": "GBP",
    }
    values.update(overrides)
    flight = TrackedFlight(**values)
    db.session.add(flight)
    db.session.commit()
    return flight


def test_user_defaults():
    user = make_user()
    db.session.expire_all()

    assert user.role == "member"
    assert user.is_active is True
    assert user.session_version == 0
    assert user.timezone == "UTC"
    assert user.created_at.tzinfo is not None
    assert user.created_at.utcoffset() == timedelta(0)


def test_password_is_hashed_and_verifiable():
    user = make_user()

    assert user.password_hash != PASSWORD
    assert user.check_password(PASSWORD) is True
    assert user.check_password("wrong") is False


def test_email_must_be_unique():
    make_user("dup@example.com")
    db.session.add(User(email="dup@example.com", display_name="X", password_hash="x"))

    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()


def test_one_pending_invite_per_email():
    make_user("admin@example.com", role="admin")
    db.session.add(
        Invite(
            email="friend@example.com", token_hash="a" * 64, expires_at=utcnow() + timedelta(days=7)
        )
    )
    db.session.commit()

    db.session.add(
        Invite(
            email="friend@example.com", token_hash="b" * 64, expires_at=utcnow() + timedelta(days=7)
        )
    )
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()

    assert db.session.scalar(select(func.count()).select_from(Invite)) == 1


def test_used_invite_releases_the_email():
    make_user("admin@example.com", role="admin")
    first = Invite(
        email="friend@example.com", token_hash="a" * 64, expires_at=utcnow() + timedelta(days=7)
    )
    db.session.add(first)
    db.session.commit()

    first.used_at = utcnow()
    db.session.commit()

    db.session.add(
        Invite(
            email="friend@example.com", token_hash="c" * 64, expires_at=utcnow() + timedelta(days=7)
        )
    )
    db.session.commit()

    assert db.session.scalar(select(func.count()).select_from(Invite)) == 2


def test_invite_is_pending_only_before_expiry():
    invite = Invite(
        email="friend@example.com", token_hash="a" * 64, expires_at=utcnow() + timedelta(days=1)
    )
    assert invite.is_pending is True

    invite.expires_at = utcnow() - timedelta(seconds=1)
    assert invite.is_pending is False


def test_deleting_a_user_removes_trackers_checks_and_alerts():
    user = make_user()
    flight = make_flight(user)
    check = PriceCheck(tracked_flight=flight, price_cents=39900, currency="GBP", provider="mock")
    db.session.add(check)
    db.session.commit()
    db.session.add(
        Alert(
            tracked_flight=flight,
            price_check_id=check.id,
            price_cents=39900,
            target_cents=42000,
            idempotency_key="k1",
        )
    )
    db.session.commit()

    db.session.delete(user)
    db.session.commit()

    for model in (TrackedFlight, PriceCheck, Alert):
        assert db.session.scalar(select(func.count()).select_from(model)) == 0


def test_api_usage_is_unique_per_provider_and_day():
    day = date(2026, 11, 3)
    db.session.add(ApiUsage(provider="apify", day=day, calls=1))
    db.session.commit()

    db.session.add(ApiUsage(provider="apify", day=day, calls=5))
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()


def test_naive_datetimes_are_rejected():
    user = make_user()
    flight = make_flight(user)
    db.session.add(
        PriceCheck(
            tracked_flight=flight,
            checked_at=datetime(2026, 11, 3, 12, 0),  # no tzinfo: a bug, not data
            price_cents=1000,
            provider="mock",
        )
    )

    with pytest.raises(StatementError, match="naive datetime"):
        db.session.commit()
    db.session.rollback()


def test_return_date_cannot_precede_departure():
    user = make_user()
    db.session.add(
        TrackedFlight(
            user=user,
            origin_iata="LHR",
            dest_iata="JFK",
            depart_date=date(2027, 3, 14),
            return_date=date(2027, 3, 1),
            cabin="economy",
            adults=1,
            currency="GBP",
        )
    )

    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()


def test_checker_index_is_defined():
    index_names = {index.name for index in TrackedFlight.__table__.indexes}

    assert "ix_tracked_flights_due" in index_names
    assert "ix_tracked_flights_user" in index_names

"""The demo seeder is what M3's dashboard renders, so it has to be stable."""

from __future__ import annotations

from sqlalchemy import func, select

from app.extensions import db
from app.models import Alert, PriceCheck, TrackedFlight, User
from app.seed import seed_demo


def test_seed_creates_user_flights_and_history(app):
    result = seed_demo("demo@example.com", "demo-password-123")

    assert result["created_user"] is True
    assert result["created_flights"] == 3
    assert result["created_checks"] > 0
    assert result["created_alerts"] >= 1
    assert result["user"].role == "admin"
    assert result["user"].check_password("demo-password-123")
    assert result["user"].tracked_flights


def test_seed_records_a_price_history_that_moves(app):
    seed_demo("demo@example.com", "demo-password-123")

    flight = db.session.scalars(
        select(TrackedFlight).where(TrackedFlight.origin_iata == "LHR")
    ).one()
    prices = db.session.scalars(
        select(PriceCheck.price_cents)
        .where(PriceCheck.tracked_flight_id == flight.id)
        .order_by(PriceCheck.checked_at)
    ).all()

    assert len(prices) > 60
    assert prices[0] != prices[-1]
    assert flight.last_price_cents == prices[-1]
    assert flight.lowest_price_cents == min(prices)


def test_seed_is_idempotent(app):
    seed_demo("demo@example.com", "demo-password-123")
    second = seed_demo("demo@example.com", "demo-password-123")

    assert second["created_user"] is False
    assert second["created_flights"] == 0
    assert second["skipped"]

    assert db.session.scalar(select(func.count()).select_from(User)) == 1
    assert db.session.scalar(select(func.count()).select_from(TrackedFlight)) == 3


def test_seed_reset_rebuilds_history(app):
    seed_demo("demo@example.com", "demo-password-123")
    first_checks = db.session.scalar(select(func.count()).select_from(PriceCheck))
    first_alerts = db.session.scalar(select(func.count()).select_from(Alert))

    seed_demo("demo@example.com", "demo-password-123", reset=True)

    assert db.session.scalar(select(func.count()).select_from(PriceCheck)) == first_checks
    assert db.session.scalar(select(func.count()).select_from(Alert)) == first_alerts


def test_seed_is_deterministic(app):
    seed_demo("one@example.com", "demo-password-123")
    prices_one = db.session.scalars(select(PriceCheck.price_cents).order_by(PriceCheck.id)).all()

    seed_demo("two@example.com", "demo-password-123")
    prices_two = db.session.scalars(
        select(PriceCheck.price_cents)
        .join(TrackedFlight)
        .join(User)
        .where(User.email == "two@example.com")
        .order_by(PriceCheck.id)
    ).all()

    assert prices_one == prices_two


def test_cli_refuses_to_seed_production(app, monkeypatch):
    monkeypatch.setitem(app.config, "ENV_NAME", "prod")

    result = app.test_cli_runner().invoke(
        args=["seed-demo", "--email", "demo@example.com", "--password", "demo-password-123"]
    )

    assert result.exit_code != 0
    assert "refusing" in result.output


def test_cli_seed_prints_a_summary(app):
    result = app.test_cli_runner().invoke(
        args=["seed-demo", "--email", "demo@example.com", "--password", "demo-password-123"]
    )

    assert result.exit_code == 0
    assert "3 tracked flights" in result.output
    assert "demo@example.com" in result.output

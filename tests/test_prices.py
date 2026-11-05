"""Mock provider, the check pipeline and the check-prices command."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select

from app.extensions import db
from app.models import PriceCheck, TrackedFlight, User, utcnow
from app.services import checks
from app.services.prices import MockProvider, ProviderError, get_provider

PASSWORD = "a-long-enough-password"


@pytest.fixture(autouse=True)
def _app_context(app):
    return app


class FailingProvider:
    name = "test"

    def fetch(self, flight):
        raise ProviderError("no seats at that fare")


def make_user(email: str = "friend@example.com") -> User:
    user = User(email=email, display_name="Friend")
    user.set_password(PASSWORD)
    db.session.add(user)
    db.session.commit()
    return user


def make_flight(user: User, **overrides) -> TrackedFlight:
    values = {
        "user_id": user.id,
        "origin_iata": "LHR",
        "dest_iata": "JFK",
        "depart_date": utcnow().date() + timedelta(days=90),
        "cabin": "economy",
        "adults": 1,
        "currency": "GBP",
        "mode": "target",
        "target_price_cents": 42000,
        "check_interval_hours": 12,
        "is_active": True,
    }
    values.update(overrides)
    flight = TrackedFlight(**values)
    db.session.add(flight)
    db.session.commit()
    return flight


def run_cli(app, *args: str):
    return app.test_cli_runner().invoke(args=list(args))


# --- the mock provider ----------------------------------------------------


def test_provider_is_stable_within_the_hour(monkeypatch):
    fixed = datetime(2027, 1, 1, 12, 0, tzinfo=UTC)
    monkeypatch.setattr("app.services.prices.utcnow", lambda: fixed)
    flight = make_flight(make_user())

    first = MockProvider().fetch(flight)
    second = MockProvider().fetch(flight)

    assert first == second
    assert first.currency == "GBP"
    assert first.provider == "mock"
    assert first.price_cents > 0


def test_later_quotes_drift_from_the_last_price(monkeypatch):
    fixed = datetime(2027, 1, 1, 12, 0, tzinfo=UTC)
    monkeypatch.setattr("app.services.prices.utcnow", lambda: fixed)
    flight = make_flight(make_user(), last_price_cents=50_000)

    quote = MockProvider().fetch(flight)

    assert 48_000 <= quote.price_cents <= 52_500


def test_base_fare_differs_between_routes():
    user = make_user()
    one = make_flight(user)
    two = make_flight(user, origin_iata="LGW", dest_iata="BCN")

    provider = MockProvider()

    assert provider.fetch(one).price_cents != provider.fetch(two).price_cents


def test_unknown_provider_is_a_clear_error():
    with pytest.raises(RuntimeError, match="unknown price provider"):
        get_provider("definitely-not-a-vendor")


def test_configured_provider_is_the_mock():
    assert get_provider().name == "mock"


# --- recording a check ----------------------------------------------------


def test_a_good_check_updates_the_tracker():
    flight = make_flight(make_user())

    check = checks.check_flight(flight, MockProvider())
    db.session.commit()

    assert check.ok is True
    assert check.price_cents == flight.last_price_cents
    assert flight.lowest_price_cents == check.price_cents
    assert flight.last_checked_at is not None


def test_lowest_price_only_moves_down():
    flight = make_flight(make_user(), last_price_cents=50_000, lowest_price_cents=30_000)

    checks.check_flight(flight, MockProvider())
    db.session.commit()

    assert flight.lowest_price_cents == 30_000


def test_a_failed_check_is_recorded_and_keeps_the_last_price():
    flight = make_flight(make_user(), last_price_cents=40_000, lowest_price_cents=40_000)

    check = checks.check_flight(flight, FailingProvider())
    db.session.commit()

    assert check.ok is False
    assert check.price_cents is None
    assert check.error == "no seats at that fare"
    assert flight.last_price_cents == 40_000
    # The interval still applies, so a broken provider is not hammered.
    assert flight.last_checked_at is not None


def test_due_respects_the_check_interval():
    user = make_user()
    make_flight(user, last_checked_at=utcnow() - timedelta(hours=1), check_interval_hours=12)

    assert checks.run_checks(provider=MockProvider()) == []

    forced = checks.run_checks(provider=MockProvider(), only_due=False)
    assert len(forced) == 1


def test_paused_trackers_are_never_checked():
    user = make_user()
    make_flight(user, is_active=False)

    assert checks.run_checks(provider=MockProvider(), only_due=False) == []


def test_checks_can_be_limited_to_one_account():
    first = make_user("one@example.com")
    second = make_user("two@example.com")
    make_flight(first)
    make_flight(second, origin_iata="LGW", dest_iata="BCN")

    results = checks.run_checks(provider=MockProvider(), user_id=first.id)

    assert len(results) == 1
    assert results[0][0].user_id == first.id
    assert db.session.scalar(select(func.count()).select_from(PriceCheck)) == 1


# --- the command ----------------------------------------------------------


def test_command_checks_and_reports(app):
    make_flight(make_user())

    result = run_cli(app, "check-prices")

    assert result.exit_code == 0, result.output
    assert "LHR-JFK" in result.output
    assert "1 checked, 1 ok" in result.output
    db.session.expire_all()
    check = db.session.scalar(select(PriceCheck))
    assert check is not None and check.ok is True


def test_command_says_when_nothing_is_due(app):
    make_flight(make_user(), last_checked_at=utcnow())

    result = run_cli(app, "check-prices")

    assert result.exit_code == 0
    assert "nothing due" in result.output


def test_command_all_ignores_the_interval(app):
    make_flight(make_user(), last_checked_at=utcnow())

    result = run_cli(app, "check-prices", "--all")

    assert result.exit_code == 0
    assert "1 checked" in result.output


def test_command_can_target_one_tracker(app):
    user = make_user()
    wanted = make_flight(user)
    make_flight(user, origin_iata="LGW", dest_iata="BCN")

    result = run_cli(app, "check-prices", "--flight", str(wanted.id))

    assert result.exit_code == 0
    assert "1 checked" in result.output


def test_command_refuses_a_paused_tracker(app):
    tracker = make_flight(make_user(), is_active=False)

    result = run_cli(app, "check-prices", "--flight", str(tracker.id))

    assert result.exit_code != 0
    assert "paused" in result.output


def test_command_reports_an_unknown_tracker(app):
    result = run_cli(app, "check-prices", "--flight", "999")

    assert result.exit_code != 0
    assert "no tracker with id 999" in result.output


def test_command_reports_an_unknown_account(app):
    result = run_cli(app, "check-prices", "--email", "nobody@example.com")

    assert result.exit_code != 0
    assert "no account" in result.output


def test_command_filters_by_account(app):
    one = make_user("one@example.com")
    two = make_user("two@example.com")
    make_flight(one)
    make_flight(two, origin_iata="LGW", dest_iata="BCN")

    result = run_cli(app, "check-prices", "--email", "one@example.com")

    assert result.exit_code == 0
    assert "1 checked" in result.output
    db.session.expire_all()
    assert db.session.scalar(select(func.count()).select_from(PriceCheck)) == 1

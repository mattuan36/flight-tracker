"""Mock provider, the check pipeline and the check-prices command."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select

from app.extensions import db
from app.models import PriceCheck, TrackedFlight, User, utcnow
from app.services import budget, checks
from app.services.prices import (
    MockProvider,
    NoMatchingFare,
    ProviderError,
    Quote,
    get_provider,
)

PASSWORD = "a-long-enough-password"


@pytest.fixture(autouse=True)
def _app_context(app):
    return app


class FailingProvider:
    name = "test"

    def fetch(self, flight):
        raise ProviderError("no seats at that fare")


class AirlineProvider:
    name = "test"

    def fetch(self, flight):
        return Quote(
            price_cents=38_900,
            currency=flight.currency,
            provider=self.name,
            airline="Alaska",
        )


class NoFareProvider:
    name = "test"

    def __init__(self) -> None:
        self.calls = 0

    def fetch(self, flight):
        self.calls += 1
        raise NoMatchingFare("no flights matched the stops filter")


class SerpApiLikeProvider:
    name = "serpapi"

    def __init__(self) -> None:
        self.calls = 0

    def estimated_calls(self, flight) -> int:
        return 2 if flight.return_date else 1

    def fetch(self, flight):
        self.calls += 1
        return Quote(
            price_cents=38_900,
            currency=flight.currency,
            provider=self.name,
            airline="Southwest",
        )


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


def test_a_good_check_records_the_winning_carrier():
    flight = make_flight(make_user())

    check = checks.check_flight(flight, AirlineProvider())
    db.session.commit()

    assert check.airline == "Alaska"
    assert flight.last_airline == "Alaska"


def test_lowest_price_only_moves_down():
    flight = make_flight(make_user(), last_price_cents=50_000, lowest_price_cents=30_000)

    checks.check_flight(flight, MockProvider())
    db.session.commit()

    assert flight.lowest_price_cents == 30_000


def test_a_failed_check_is_recorded_and_keeps_the_last_price():
    flight = make_flight(
        make_user(),
        last_price_cents=40_000,
        lowest_price_cents=40_000,
        last_airline="Alaska",
    )

    check = checks.check_flight(flight, FailingProvider())
    db.session.commit()

    assert check.ok is False
    assert check.price_cents is None
    assert check.error == "no seats at that fare"
    assert check.airline is None
    assert flight.last_price_cents == 40_000
    assert flight.last_airline == "Alaska"
    # The interval still applies, so a broken provider is not hammered.
    assert flight.last_checked_at is not None


def test_clean_no_fare_relaxes_nonstop_to_any_stops():
    now = utcnow()
    flight = make_flight(
        make_user(),
        max_stops=0,
        depart_date=now.date() + timedelta(days=60),
    )
    provider = NoFareProvider()

    check = checks.check_flight(flight, provider, now=now)
    db.session.commit()

    assert check.ok is False
    assert check.error == "no flights matched the stops filter"
    assert flight.max_stops is None
    assert flight.stops_auto_relaxed_from == 0
    assert flight.stops_auto_relaxed_at == now
    assert flight.last_checked_at == now
    assert provider.calls == 1


def test_clean_no_fare_relaxes_one_stop_to_any_stops():
    now = utcnow()
    flight = make_flight(
        make_user(),
        max_stops=1,
        depart_date=now.date() + timedelta(days=60),
    )

    checks.check_flight(flight, NoFareProvider(), now=now)

    assert flight.max_stops is None
    assert flight.stops_auto_relaxed_from == 1
    assert flight.stops_auto_relaxed_at == now


def test_clean_no_fare_leaves_any_stops_alone():
    now = utcnow()
    flight = make_flight(
        make_user(),
        max_stops=None,
        depart_date=now.date() + timedelta(days=60),
    )

    checks.check_flight(flight, NoFareProvider(), now=now)

    assert flight.max_stops is None
    assert flight.stops_auto_relaxed_from is None
    assert flight.stops_auto_relaxed_at is None


def test_an_already_relaxed_tracker_keeps_its_original_limit():
    now = utcnow()
    relaxed_at = now - timedelta(days=3)
    flight = make_flight(
        make_user(),
        max_stops=None,
        stops_auto_relaxed_from=0,
        stops_auto_relaxed_at=relaxed_at,
        depart_date=now.date() + timedelta(days=60),
    )

    checks.check_flight(flight, NoFareProvider(), now=now)

    assert flight.max_stops is None
    assert flight.stops_auto_relaxed_from == 0
    assert flight.stops_auto_relaxed_at == relaxed_at


def test_a_provider_failure_does_not_relax_stops():
    flight = make_flight(make_user(), max_stops=0)

    checks.check_flight(flight, FailingProvider())

    assert flight.max_stops == 0
    assert flight.stops_auto_relaxed_from is None
    assert flight.stops_auto_relaxed_at is None


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


def test_run_checks_reserves_one_call_for_a_one_way():
    now = utcnow()
    make_flight(make_user(), depart_date=now.date() + timedelta(days=60))
    provider = SerpApiLikeProvider()

    results = checks.run_checks(provider=provider, now=now)

    assert len(results) == 1
    assert provider.calls == 1
    assert budget.calls_this_month("serpapi", now.date()) == 1


def test_run_checks_reserves_two_calls_for_a_return():
    now = utcnow()
    make_flight(
        make_user(),
        depart_date=now.date() + timedelta(days=60),
        return_date=now.date() + timedelta(days=67),
    )
    provider = SerpApiLikeProvider()

    results = checks.run_checks(provider=provider, now=now)

    assert len(results) == 1
    assert provider.calls == 1
    assert budget.calls_this_month("serpapi", now.date()) == 2


def test_run_checks_stops_at_the_monthly_cap(app):
    now = utcnow()
    user = make_user()
    make_flight(user, dest_iata="LAS", depart_date=now.date() + timedelta(days=60))
    make_flight(user, dest_iata="HOU", depart_date=now.date() + timedelta(days=61))
    app.config["SERPAPI_MONTHLY_CAP"] = 1
    provider = SerpApiLikeProvider()

    results = checks.run_checks(provider=provider, now=now)

    assert len(results) == 1
    assert len(results.skipped) == 1
    assert results.skipped[0][1] == "monthly search budget reached"
    assert provider.calls == 1
    assert budget.calls_this_month("serpapi", now.date()) == 1
    assert db.session.scalar(select(func.count()).select_from(PriceCheck)) == 1


def test_run_checks_respects_the_per_run_call_cap(app):
    now = utcnow()
    user = make_user()
    make_flight(user, dest_iata="LAS", depart_date=now.date() + timedelta(days=60))
    make_flight(user, dest_iata="HOU", depart_date=now.date() + timedelta(days=61))
    app.config["CHECK_MAX_CALLS_PER_RUN"] = 1
    provider = SerpApiLikeProvider()

    results = checks.run_checks(provider=provider, now=now)

    assert len(results) == 1
    assert len(results.skipped) == 1
    assert results.skipped[0][1] == "per-run call cap reached"
    assert provider.calls == 1


def test_run_checks_skips_flights_whose_departure_has_passed():
    now = utcnow()
    make_flight(make_user(), depart_date=now.date() - timedelta(days=1))

    results = checks.run_checks(provider=MockProvider(), now=now)

    assert results == []
    assert results.skipped == []


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


def test_command_requires_a_key_for_serpapi(app, monkeypatch):
    monkeypatch.setitem(app.config, "PRICE_PROVIDER", "serpapi")
    monkeypatch.setitem(app.config, "SERPAPI_KEY", "")
    make_flight(make_user())

    result = run_cli(app, "check-prices")

    assert result.exit_code != 0
    assert "SERPAPI_KEY is not set" in result.output
    assert db.session.scalar(select(func.count()).select_from(PriceCheck)) == 0


def test_command_prints_the_auto_relax_warning(app):
    make_flight(
        make_user(),
        max_stops=None,
        stops_auto_relaxed_at=utcnow(),
        stops_auto_relaxed_from=1,
    )

    result = run_cli(app, "check-prices")

    assert result.exit_code == 0, result.output
    assert "stops relaxed from 1 stop or fewer to Any number of stops" in result.output


def test_command_reports_flights_skipped_by_the_budget(app, monkeypatch):
    now = utcnow()
    user = make_user()
    make_flight(user, dest_iata="LAS", depart_date=now.date() + timedelta(days=60))
    make_flight(user, dest_iata="HOU", depart_date=now.date() + timedelta(days=61))
    app.config["SERPAPI_MONTHLY_CAP"] = 1
    monkeypatch.setitem(app.config, "PRICE_PROVIDER", "serpapi")
    monkeypatch.setitem(app.config, "SERPAPI_KEY", "test-key")
    monkeypatch.setattr(
        "app.services.prices.get_provider",
        lambda: SerpApiLikeProvider(),
    )

    result = run_cli(app, "check-prices", "--all")

    assert result.exit_code == 0, result.output
    assert "skipped: monthly search budget reached" in result.output
    assert "1 checked" in result.output
    assert "1 skipped" in result.output

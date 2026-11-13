"""Alert rules, delivery attempts and the three-attempt retry cap."""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import func, select

from app.extensions import db
from app.models import Alert, PriceCheck, TrackedFlight, User, utcnow
from app.services import alerts, mailer

PASSWORD = "a-long-enough-password"


@pytest.fixture(autouse=True)
def _app_context(app):
    return app


def make_user(email: str = "friend@example.com") -> User:
    user = User(email=email, display_name="Friend")
    user.set_password(PASSWORD)
    db.session.add(user)
    db.session.commit()
    return user


def make_flight(user: User, **overrides) -> TrackedFlight:
    values = {
        "user_id": user.id,
        "origin_iata": "PDX",
        "dest_iata": "OAK",
        "depart_date": utcnow().date() + timedelta(days=90),
        "cabin": "economy",
        "adults": 1,
        "currency": "USD",
        "mode": "target",
        "target_price_cents": 42000,
        "check_interval_hours": 24,
        "is_active": True,
    }
    values.update(overrides)
    flight = TrackedFlight(**values)
    db.session.add(flight)
    db.session.commit()
    return flight


def add_check(
    flight: TrackedFlight,
    price: int | None,
    *,
    now=None,
    ok: bool = True,
    currency: str = "USD",
) -> PriceCheck:
    check = PriceCheck(
        tracked_flight_id=flight.id,
        checked_at=now or utcnow(),
        ok=ok,
        price_cents=price,
        currency=currency if ok else None,
        provider="test",
        error=None if ok else "provider failed",
    )
    db.session.add(check)
    flight.last_checked_at = check.checked_at
    if ok and price is not None:
        flight.last_price_cents = price
    db.session.commit()
    return check


def capture_mail(monkeypatch) -> list[dict]:
    sent: list[dict] = []

    def fake(**kwargs):
        sent.append(kwargs)

    monkeypatch.setattr("app.services.mailer.send_email", fake)
    return sent


def failing_mail(monkeypatch, failures: int):
    sent: list[dict] = []
    state = {"failures": failures}

    def fake(**kwargs):
        if state["failures"] > 0:
            state["failures"] -= 1
            raise mailer.MailError("relay unavailable")
        sent.append(kwargs)

    monkeypatch.setattr("app.services.mailer.send_email", fake)
    return sent


# --- target mode ----------------------------------------------------------


def test_first_crossing_sends_and_moves_the_alert_marker(monkeypatch):
    sent = capture_mail(monkeypatch)
    flight = make_flight(make_user())
    add_check(flight, 45000)
    check = add_check(flight, 41000)

    alert = alerts.create_and_deliver(flight, check)

    assert alert is not None
    assert alert.email_status == "sent"
    assert alert.email_attempts == 1
    assert len(sent) == 1
    assert sent[0]["to"] == "friend@example.com"
    assert "PDX-OAK" in sent[0]["subject"]
    assert flight.last_alert_at is not None
    assert flight.last_alert_price_cents == 41000


def test_a_fare_that_stays_below_target_only_alerts_on_a_new_low(monkeypatch):
    sent = capture_mail(monkeypatch)
    flight = make_flight(make_user())
    add_check(flight, 45000)
    first = add_check(flight, 41000)
    alerts.create_and_deliver(flight, first)

    same = add_check(flight, 41000)
    higher_but_below = add_check(flight, 41500)
    lower = add_check(flight, 40000)

    assert alerts.create_and_deliver(flight, same) is None
    assert alerts.create_and_deliver(flight, higher_but_below) is None
    new_low = alerts.create_and_deliver(flight, lower)

    assert new_low is not None and new_low.email_status == "sent"
    assert len(sent) == 2
    assert flight.last_alert_price_cents == 40000


def test_a_new_crossing_after_going_above_target_alerts_again(monkeypatch):
    sent = capture_mail(monkeypatch)
    flight = make_flight(make_user())
    add_check(flight, 45000)
    first = add_check(flight, 41000)
    alerts.create_and_deliver(flight, first)

    add_check(flight, 43000)  # above target: no alert
    recross = add_check(flight, 41500)  # below target, but not a global new low

    alert = alerts.create_and_deliver(flight, recross)

    assert alert is not None and alert.email_status == "sent"
    assert len(sent) == 2


def test_a_failed_check_never_alerts(monkeypatch):
    sent = capture_mail(monkeypatch)
    flight = make_flight(make_user())
    add_check(flight, 45000)
    check = add_check(flight, None, ok=False)

    assert alerts.create_and_deliver(flight, check) is None
    assert sent == []


def test_paused_and_past_dated_trackers_never_alert(monkeypatch):
    sent = capture_mail(monkeypatch)
    user = make_user()
    paused = make_flight(user, is_active=False)
    paused_check = add_check(paused, 30000)
    past = make_flight(
        user,
        origin_iata="SEA",
        dest_iata="SFO",
        depart_date=utcnow().date() - timedelta(days=1),
    )
    past_check = add_check(past, 30000)

    assert alerts.create_and_deliver(paused, paused_check) is None
    assert alerts.create_and_deliver(past, past_check) is None
    assert sent == []


def test_currency_mismatch_never_alerts(monkeypatch):
    sent = capture_mail(monkeypatch)
    flight = make_flight(make_user())
    add_check(flight, 45000)
    check = add_check(flight, 41000, currency="EUR")

    assert alerts.create_and_deliver(flight, check) is None
    assert sent == []


def test_the_same_observation_cannot_send_twice(monkeypatch):
    sent = capture_mail(monkeypatch)
    flight = make_flight(make_user())
    add_check(flight, 45000)
    check = add_check(flight, 41000)

    first = alerts.create_and_deliver(flight, check)
    second = alerts.create_and_deliver(flight, check)

    assert first is not None and second is not None
    assert first.id == second.id
    assert len(sent) == 1
    assert db.session.scalar(select(func.count()).select_from(Alert)) == 1


# --- any_drop mode --------------------------------------------------------


def test_any_drop_adopts_the_first_fare_without_alerting(monkeypatch):
    sent = capture_mail(monkeypatch)
    flight = make_flight(make_user(), mode="any_drop", target_price_cents=None)
    first = add_check(flight, 50000)

    assert alerts.create_and_deliver(flight, first) is None
    assert flight.target_price_cents == 50000
    assert sent == []


def test_any_drop_alerts_only_on_a_later_new_low(monkeypatch):
    sent = capture_mail(monkeypatch)
    flight = make_flight(make_user(), mode="any_drop", target_price_cents=None)
    alerts.create_and_deliver(flight, add_check(flight, 50000))

    drop = add_check(flight, 48000)
    alert = alerts.create_and_deliver(flight, drop)

    assert alert is not None and alert.email_status == "sent"
    assert len(sent) == 1
    assert flight.last_alert_price_cents == 48000

    # Still below the original baseline, but not a new low.
    assert alerts.create_and_deliver(flight, add_check(flight, 49000)) is None
    assert len(sent) == 1


def test_any_drop_does_not_repeat_a_permanently_failed_alert(monkeypatch):
    failing_mail(monkeypatch, failures=99)
    flight = make_flight(make_user(), mode="any_drop", target_price_cents=None)
    alerts.create_and_deliver(flight, add_check(flight, 50000))
    drop = add_check(flight, 48000)
    alert = alerts.create_and_deliver(flight, drop)
    alerts.process_pending()
    alerts.process_pending()

    assert alert is not None and alert.email_attempts == 3
    assert alerts.create_and_deliver(flight, add_check(flight, 48000)) is None
    lower = alerts.create_and_deliver(flight, add_check(flight, 47000))
    assert lower is not None and lower.email_status == "failed"


# --- retries --------------------------------------------------------------


def test_a_transient_failure_is_retried_on_the_next_run(monkeypatch):
    sent = failing_mail(monkeypatch, failures=2)
    flight = make_flight(make_user())
    add_check(flight, 45000)
    check = add_check(flight, 41000)

    alert = alerts.create_and_deliver(flight, check)
    assert alert is not None and alert.email_status == "failed"
    assert alert.email_attempts == 1
    assert flight.last_alert_at is None

    first_retry = alerts.process_pending()
    assert first_retry == {"attempted": 1, "sent": 0, "failed": 1}
    assert alert.email_attempts == 2
    assert flight.last_alert_at is None

    second_retry = alerts.process_pending()
    assert second_retry == {"attempted": 1, "sent": 1, "failed": 0}
    assert alert.email_status == "sent"
    assert alert.email_attempts == 3
    assert flight.last_alert_at is not None
    assert len(sent) == 1

    assert alerts.process_pending() == {"attempted": 0, "sent": 0, "failed": 0}


def test_a_permanent_failure_stops_after_three_attempts(monkeypatch):
    failing_mail(monkeypatch, failures=99)
    flight = make_flight(make_user())
    add_check(flight, 45000)
    check = add_check(flight, 41000)

    alert = alerts.create_and_deliver(flight, check)
    assert alert is not None
    alerts.process_pending()
    alerts.process_pending()

    assert alert.email_status == "failed"
    assert alert.email_attempts == 3
    assert alert.last_error == "relay unavailable"
    assert alerts.process_pending()["attempted"] == 0


def test_an_outstanding_alert_blocks_a_new_one_until_it_is_delivered(monkeypatch):
    sent = failing_mail(monkeypatch, failures=1)
    flight = make_flight(make_user())
    add_check(flight, 45000)
    first = add_check(flight, 41000)
    alert = alerts.create_and_deliver(flight, first)
    assert alert is not None and alert.email_status == "failed"

    lower = add_check(flight, 39000)
    assert alerts.create_and_deliver(flight, lower) is None

    assert alerts.process_pending()["sent"] == 1
    second = alerts.create_and_deliver(flight, lower)

    assert second is not None and second.email_status == "sent"
    assert len(sent) == 2
    assert flight.last_alert_price_cents == 39000


def test_retry_can_be_scoped_to_one_account(monkeypatch):
    failing_mail(monkeypatch, failures=99)
    one = make_user("one@example.com")
    two = make_user("two@example.com")
    first = make_flight(one)
    second = make_flight(two, origin_iata="SEA", dest_iata="SFO")
    add_check(first, 45000)
    add_check(second, 45000)
    first_alert = alerts.create_and_deliver(first, add_check(first, 41000))
    alerts.create_and_deliver(second, add_check(second, 41000))

    result = alerts.process_pending(user_id=one.id)

    assert result["attempted"] == 1
    assert first_alert is not None and first_alert.email_attempts == 2

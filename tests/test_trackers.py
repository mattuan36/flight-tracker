"""Tracked flight pages: dashboard, add, edit, pause, delete."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.extensions import db
from app.models import PriceCheck, TrackedFlight, User, utcnow
from app.money import format_cents, to_cents
from app.templating import shortdates, spark_points

PASSWORD = "a-long-enough-password"


@pytest.fixture(autouse=True)
def _app_context(app):
    return app


def make_user(email: str = "friend@example.com", timezone: str = "UTC") -> User:
    user = User(email=email, display_name="Friend", timezone=timezone)
    user.set_password(PASSWORD)
    db.session.add(user)
    db.session.commit()
    return user


def sign_in(client, email: str = "friend@example.com") -> None:
    client.post("/login", data={"email": email, "password": PASSWORD})


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


def payload(**overrides) -> dict[str, str]:
    values = {
        "origin_iata": "lhr",
        "dest_iata": "JFK",
        "depart_date": (utcnow().date() + timedelta(days=90)).isoformat(),
        "return_date": "",
        "airline": "",
        "cabin": "economy",
        "adults": "1",
        "currency": "GBP",
        "mode": "target",
        "target": "420.50",
        "check_interval_hours": "12",
    }
    values.update(overrides)
    return values


# --- dashboard ------------------------------------------------------------


def test_anonymous_visitors_get_the_landing_page(client):
    response = client.get("/")

    assert response.status_code == 200
    assert b"invite-only" in response.data
    assert b"Your flights" not in response.data


def test_dashboard_lists_only_your_flights(client):
    user = make_user()
    other = make_user("other@example.com")
    make_flight(user)
    make_flight(
        other,
        origin_iata="MAN",
        dest_iata="AYT",
        depart_date=utcnow().date() + timedelta(days=120),
    )
    sign_in(client)

    body = client.get("/").data

    assert b"LHR" in body
    assert b"JFK" in body
    assert b"MAN" not in body


def test_empty_dashboard_invites_a_first_flight(client):
    make_user()
    sign_in(client)

    body = client.get("/").data

    assert b"Nothing tracked yet" in body
    assert b"Add your first flight" in body


def test_dashboard_marks_a_fare_below_target(client):
    user = make_user()
    make_flight(user, last_price_cents=38900, lowest_price_cents=38900, last_checked_at=utcnow())
    sign_in(client)

    body = client.get("/").data

    assert b"\xc2\xa3389.00" in body  # £389.00
    assert b"under target" in body


def test_paused_flight_is_labelled(client):
    user = make_user()
    make_flight(user, is_active=False)
    sign_in(client)

    assert b"paused" in client.get("/").data


# --- adding ---------------------------------------------------------------


def test_adding_a_flight_converts_the_target_to_cents(client):
    user = make_user()
    sign_in(client)

    response = client.post("/flights/new", data=payload())

    flight = db.session.scalar(select(TrackedFlight))
    assert response.status_code == 302
    assert response.headers["Location"] == f"/flights/{flight.id}"
    assert flight.user_id == user.id
    assert flight.origin_iata == "LHR"
    assert flight.dest_iata == "JFK"
    assert flight.target_price_cents == 42050
    assert flight.adults == 1
    assert flight.check_interval_hours == 12
    assert flight.mode == "target"


def test_airline_is_stored_and_shown_after_the_route(client):
    make_user()
    sign_in(client)

    client.post("/flights/new", data=payload(airline="British Airways"))

    flight = db.session.scalar(select(TrackedFlight))
    assert flight.airline == "British Airways"
    dashboard = client.get("/").data
    detail = client.get(f"/flights/{flight.id}").data
    assert b'<span class="airline">British Airways</span>' in dashboard
    assert b'<span class="airline">British Airways</span>' in detail


def test_airline_is_optional(client):
    make_user()
    sign_in(client)

    client.post("/flights/new", data=payload(airline="  "))

    assert db.session.scalar(select(TrackedFlight)).airline is None


def test_any_drop_mode_ignores_a_leftover_target(client):
    make_user()
    sign_in(client)

    client.post("/flights/new", data=payload(mode="any_drop", target="99.00"))

    flight = db.session.scalar(select(TrackedFlight))
    assert flight.mode == "any_drop"
    assert flight.target_price_cents is None


def test_target_is_required_when_mode_is_target(client):
    make_user()
    sign_in(client)

    response = client.post("/flights/new", data=payload(target=""))

    assert response.status_code == 200
    assert b"Enter the price you would pay" in response.data
    assert db.session.scalar(select(TrackedFlight)) is None


def test_same_origin_and_destination_is_rejected(client):
    make_user()
    sign_in(client)

    response = client.post("/flights/new", data=payload(dest_iata="LHR"))

    assert response.status_code == 200
    assert b"cannot be the same" in response.data
    assert db.session.scalar(select(TrackedFlight)) is None


def test_return_before_departure_is_rejected(client):
    make_user()
    sign_in(client)
    depart = utcnow().date() + timedelta(days=30)

    response = client.post(
        "/flights/new",
        data=payload(
            depart_date=depart.isoformat(),
            return_date=(depart - timedelta(days=1)).isoformat(),
        ),
    )

    assert response.status_code == 200
    assert b"cannot be before" in response.data


def test_past_departure_is_rejected(client):
    make_user()
    sign_in(client)

    response = client.post("/flights/new", data=payload(depart_date="2020-01-01"))

    assert response.status_code == 200
    assert b"today or a later date" in response.data


def test_a_word_is_not_an_airport_code(client):
    make_user()
    sign_in(client)

    response = client.post("/flights/new", data=payload(origin_iata="LONDON"))

    assert response.status_code == 200
    assert b"three-letter airport code" in response.data


# --- ownership ------------------------------------------------------------


def test_another_users_flight_is_a_404_everywhere(client):
    make_user()
    other = make_user("other@example.com")
    flight = make_flight(other)
    sign_in(client)

    assert client.get(f"/flights/{flight.id}").status_code == 404
    assert client.get(f"/flights/{flight.id}/edit").status_code == 404
    assert client.get(f"/flights/{flight.id}/delete").status_code == 404
    assert client.post(f"/flights/{flight.id}/toggle").status_code == 404
    assert client.post(f"/flights/{flight.id}/delete").status_code == 404
    assert db.session.get(TrackedFlight, flight.id) is not None


def test_signed_out_visitors_are_sent_to_sign_in(client):
    user = make_user()
    flight = make_flight(user)

    response = client.get(f"/flights/{flight.id}")

    assert response.status_code == 302
    assert response.headers["Location"].startswith("/login")


# --- detail, edit and lifecycle -------------------------------------------


def test_detail_shows_price_target_and_recent_checks(client):
    user = make_user()
    flight = make_flight(
        user, last_price_cents=38900, lowest_price_cents=38900, last_checked_at=utcnow()
    )
    for price in (68500, 54000, 38900):
        db.session.add(
            PriceCheck(
                tracked_flight_id=flight.id,
                ok=True,
                price_cents=price,
                currency="GBP",
                provider="mock",
            )
        )
    db.session.commit()
    sign_in(client)

    body = client.get(f"/flights/{flight.id}").data

    assert b"LHR" in body and b"JFK" in body
    assert b"\xc2\xa3389.00" in body
    assert b"\xc2\xa3420.00" in body
    assert b"below" in body
    assert b"Price history" in body
    assert b"Recent checks" in body


def test_edit_form_is_prefilled(client):
    user = make_user()
    flight = make_flight(user, target_price_cents=42050, airline="British Airways")
    sign_in(client)

    body = client.get(f"/flights/{flight.id}/edit").data

    assert b'value="420.50"' in body
    assert b'value="LHR"' in body
    assert b'value="British Airways"' in body
    assert b"Every 12 hours" in body


def test_editing_updates_the_tracker(client):
    user = make_user()
    flight = make_flight(user)
    sign_in(client)

    response = client.post(
        f"/flights/{flight.id}/edit",
        data=payload(target="500.00", check_interval_hours="24"),
    )

    assert response.status_code == 302
    db.session.refresh(flight)
    assert flight.target_price_cents == 50000
    assert flight.check_interval_hours == 24


def test_currency_cannot_change_once_there_is_history(client):
    user = make_user()
    flight = make_flight(user, last_price_cents=40000)
    sign_in(client)

    response = client.post(f"/flights/{flight.id}/edit", data=payload(currency="USD"))

    assert response.status_code == 200
    assert b"price history in GBP" in response.data
    db.session.refresh(flight)
    assert flight.currency == "GBP"


def test_pausing_and_resuming(client):
    user = make_user()
    flight = make_flight(user)
    sign_in(client)

    client.post(f"/flights/{flight.id}/toggle")
    db.session.refresh(flight)
    assert flight.is_active is False

    client.post(f"/flights/{flight.id}/toggle")
    db.session.refresh(flight)
    assert flight.is_active is True


def test_detail_chart_draws_the_target_line(client):
    user = make_user()
    flight = make_flight(user, target_price_cents=42000, last_price_cents=38900)
    for day, price in ((1, 68500), (10, 54000), (20, 38900)):
        db.session.add(
            PriceCheck(
                tracked_flight_id=flight.id,
                checked_at=datetime(2026, 10, day, 12, tzinfo=UTC),
                ok=True,
                price_cents=price,
                currency="GBP",
                provider="mock",
            )
        )
    db.session.commit()
    sign_in(client)

    body = client.get(f"/flights/{flight.id}").data

    assert b'class="spark-target"' in body
    assert b"The dashed line is your" in body
    # Both axes are labelled: fares on the left, check dates along the bottom.
    assert b'class="chart-label"' in body
    assert b"01 Oct" in body
    assert b"20 Oct" in body
    assert b"\xc2\xa3300" in body
    assert b"\xc2\xa3700" in body
    # The target is labelled on the chart, and points carry exact tooltip data.
    assert b"target \xc2\xa3420" in body
    assert b"data-price-chart" in body
    assert b'data-when="01 Oct 2026, 12:00"' in body
    assert b"chart.js" in body


def test_a_flight_without_a_target_has_no_target_line(client):
    user = make_user()
    flight = make_flight(user, target_price_cents=None, mode="any_drop")
    for price in (30000, 28000):
        db.session.add(
            PriceCheck(
                tracked_flight_id=flight.id,
                ok=True,
                price_cents=price,
                currency="GBP",
                provider="mock",
            )
        )
    db.session.commit()
    sign_in(client)

    body = client.get(f"/flights/{flight.id}").data

    assert b'class="spark-target"' not in body
    assert b'class="chart-target-label"' not in body


def test_delete_asks_first_then_removes_everything(client):
    user = make_user()
    flight = make_flight(user)
    db.session.add(
        PriceCheck(tracked_flight_id=flight.id, ok=True, price_cents=40000, provider="mock")
    )
    db.session.commit()
    sign_in(client)

    confirm = client.get(f"/flights/{flight.id}/delete")
    assert confirm.status_code == 200
    assert b"Delete permanently" in confirm.data

    response = client.post(f"/flights/{flight.id}/delete")

    assert response.status_code == 302
    assert db.session.get(TrackedFlight, flight.id) is None
    assert db.session.scalar(select(PriceCheck)) is None


# --- model helpers --------------------------------------------------------


def test_price_state_below_above_and_watching():
    flight = TrackedFlight(
        origin_iata="LHR",
        dest_iata="JFK",
        depart_date=date(2027, 3, 14),
        target_price_cents=42000,
        last_price_cents=38900,
        is_active=True,
    )
    assert flight.price_state == "below"
    assert flight.is_below_target is True
    assert flight.target_gap_cents == -3100

    flight.last_price_cents = 50000
    assert flight.price_state == "above"
    assert flight.target_gap_cents == 8000

    flight.target_price_cents = None
    assert flight.price_state == "watching"

    flight.last_price_cents = None
    assert flight.price_state == "waiting"

    flight.is_active = False
    assert flight.price_state == "paused"


# --- formatting helpers ---------------------------------------------------


def test_money_is_formatted_from_integer_cents():
    assert format_cents(42000) == "£420.00"
    assert format_cents(42050, "EUR") == "€420.50"
    assert format_cents(0, "USD") == "$0.00"
    assert format_cents(None) == "—"
    assert format_cents(-3100) == "-£31.00"


def test_cents_conversion_rounds_half_up():
    assert to_cents(Decimal("420.50")) == 42050
    assert to_cents(Decimal("0.005")) == 1
    assert to_cents(Decimal("10")) == 1000


def test_short_dates_compress_a_range() -> None:
    assert shortdates(date(2027, 7, 19)) == "19 Jul 2027"
    assert shortdates(date(2027, 7, 19), date(2027, 8, 2)) == "19 Jul – 2 Aug 2027"
    assert shortdates(date(2027, 3, 14), date(2027, 3, 21)) == "14 – 21 Mar 2027"
    assert shortdates(date(2027, 12, 30), date(2028, 1, 4)) == "30 Dec 2027 – 4 Jan 2028"


def test_sparkline_needs_two_points():
    assert spark_points([]) == ""
    assert spark_points([100]) == ""
    assert spark_points([100, 200]) != ""


def test_sparkline_puts_lower_prices_lower():
    first, second = spark_points([100, 300]).split()
    assert float(second.split(",")[1]) < float(first.split(",")[1])

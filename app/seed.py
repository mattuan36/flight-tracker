"""Deterministic demo data.

The dashboard (M3) needs something to render before the price checker exists,
so this seeds a user, a few tracked flights, a plausible price history and one
sent alert. Everything is generated from a fixed random seed, so two runs look
the same.
"""

from __future__ import annotations

import random
from datetime import date, timedelta
from typing import Any

from .extensions import db
from .models import Alert, PriceCheck, TrackedFlight, User, utcnow

DEMO_SEED = 20261103
CHECKS_PER_DAY = 2

# origin, destination, dates, cabin, target, price at the start of recorded
# history, price now. Flight one has already dropped through its target, so the
# dashboard shows an alert; flight two is still waiting.
DEMO_FLIGHTS: list[dict[str, Any]] = [
    {
        "origin_iata": "LHR",
        "dest_iata": "JFK",
        "depart": date(2027, 3, 14),
        "return_": date(2027, 3, 21),
        "target_cents": 42000,
        "start_cents": 68500,
        "end_cents": 38900,
    },
    {
        "origin_iata": "LGW",
        "dest_iata": "BCN",
        "depart": date(2027, 6, 2),
        "return_": None,
        "target_cents": 9500,
        "start_cents": 7400,
        "end_cents": 11200,
    },
    {
        "origin_iata": "MAN",
        "dest_iata": "AYT",
        "depart": date(2027, 7, 19),
        "return_": date(2027, 8, 2),
        "target_cents": None,
        "start_cents": 31000,
        "end_cents": 27400,
    },
]


def _price_series(rng: random.Random, start: int, end: int, points: int) -> list[int]:
    """Linear drift from start to end with a little noise, in whole cents."""
    series: list[int] = []
    for index in range(points):
        ratio = index / max(points - 1, 1)
        baseline = start + (end - start) * ratio
        noise = rng.uniform(-0.035, 0.035) * baseline
        series.append(max(1000, round(baseline + noise)))
    return series


def seed_demo(
    email: str,
    password: str,
    *,
    display_name: str | None = None,
    history_days: int = 45,
    reset: bool = False,
) -> dict[str, Any]:
    """Create (or extend) a demo account. Returns a summary for the CLI."""
    email = email.strip().lower()
    user = db.session.scalar(db.select(User).where(User.email == email))

    created_user = False
    if user is None:
        user = User(
            email=email,
            display_name=display_name or email.split("@")[0],
            role="admin",
        )
        user.set_password(password)
        db.session.add(user)
        db.session.flush()
        created_user = True
    elif reset:
        for flight in list(user.tracked_flights):
            db.session.delete(flight)
        db.session.flush()

    if user.tracked_flights and not reset:
        db.session.commit()
        return {
            "user": user,
            "created_user": created_user,
            "created_flights": 0,
            "created_checks": 0,
            "created_alerts": 0,
            "skipped": "user already has tracked flights (use --reset)",
        }

    rng = random.Random(DEMO_SEED)
    now = utcnow()
    points = history_days * CHECKS_PER_DAY
    created_checks = 0
    created_alerts = 0
    flights: list[TrackedFlight] = []

    for spec in DEMO_FLIGHTS:
        flight = TrackedFlight(
            user=user,
            origin_iata=spec["origin_iata"],
            dest_iata=spec["dest_iata"],
            depart_date=spec["depart"],
            return_date=spec["return_"],
            cabin="economy",
            adults=1,
            currency="GBP",
            target_price_cents=spec["target_cents"],
            mode="target",
            check_interval_hours=12,
            is_active=True,
        )
        db.session.add(flight)
        db.session.flush()
        flights.append(flight)

        series = _price_series(rng, spec["start_cents"], spec["end_cents"], points)
        lowest: int | None = None
        first_alert: tuple[PriceCheck, int] | None = None

        for step, price in enumerate(series):
            checked_at = now - timedelta(days=history_days - step / CHECKS_PER_DAY)
            check = PriceCheck(
                tracked_flight=flight,
                checked_at=checked_at,
                ok=True,
                price_cents=price,
                currency="GBP",
                provider="mock",
            )
            db.session.add(check)
            created_checks += 1
            lowest = price if lowest is None else min(lowest, price)

            target = spec["target_cents"]
            if target is not None and price <= target and first_alert is None:
                first_alert = (check, price)

        flight.last_checked_at = now
        flight.last_price_cents = series[-1]
        flight.lowest_price_cents = lowest

        if first_alert is not None:
            check, price = first_alert
            db.session.flush()
            alert = Alert(
                tracked_flight=flight,
                price_check_id=check.id,
                price_cents=price,
                target_cents=spec["target_cents"],
                sent_at=check.checked_at,
                email_status="sent",
                idempotency_key=f"demo-{flight.id}-{check.id}",
            )
            db.session.add(alert)
            flight.last_alert_at = check.checked_at
            flight.last_alert_price_cents = price
            created_alerts += 1

    db.session.commit()
    return {
        "user": user,
        "created_user": created_user,
        "created_flights": len(flights),
        "created_checks": created_checks,
        "created_alerts": created_alerts,
        "skipped": None,
    }

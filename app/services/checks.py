"""Recording a price observation against a tracked flight.

This is the core the M6 scheduled job will reuse: fetch one quote, append a
``PriceCheck``, and keep the denormalised columns on the tracker in step so the
dashboard never has to aggregate history.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from ..extensions import db
from ..models import PriceCheck, TrackedFlight, utcnow
from .prices import PriceProvider, ProviderError, get_provider


def is_due(flight: TrackedFlight, now: datetime | None = None) -> bool:
    now = now or utcnow()
    if flight.last_checked_at is None:
        return True
    return flight.last_checked_at + timedelta(hours=flight.check_interval_hours) <= now


def check_flight(
    flight: TrackedFlight,
    provider: PriceProvider,
    *,
    now: datetime | None = None,
) -> PriceCheck:
    """Fetch one quote and record it, successes and failures alike.

    A failed check still moves ``last_checked_at``: otherwise a broken provider
    would be retried by every run instead of waiting out the interval.
    """
    now = now or utcnow()

    try:
        quote = provider.fetch(flight)
    except ProviderError as exc:
        check = PriceCheck(
            tracked_flight_id=flight.id,
            checked_at=now,
            ok=False,
            provider=provider.name,
            error=str(exc)[:255],
        )
        flight.last_checked_at = now
        db.session.add(check)
        return check

    check = PriceCheck(
        tracked_flight_id=flight.id,
        checked_at=now,
        ok=True,
        price_cents=quote.price_cents,
        currency=quote.currency,
        provider=quote.provider,
    )
    flight.last_checked_at = now
    flight.last_price_cents = quote.price_cents
    if quote.currency == flight.currency and (
        flight.lowest_price_cents is None or quote.price_cents < flight.lowest_price_cents
    ):
        flight.lowest_price_cents = quote.price_cents
    db.session.add(check)
    return check


def run_checks(
    *,
    provider: PriceProvider | None = None,
    only_due: bool = True,
    user_id: int | None = None,
    flight_id: int | None = None,
    now: datetime | None = None,
) -> list[tuple[TrackedFlight, PriceCheck]]:
    """Check active trackers and commit, returning what happened per flight."""
    provider = provider or get_provider()
    now = now or utcnow()

    query = (
        db.select(TrackedFlight)
        .where(TrackedFlight.is_active.is_(True))
        .order_by(TrackedFlight.last_checked_at)
    )
    if user_id is not None:
        query = query.where(TrackedFlight.user_id == user_id)
    if flight_id is not None:
        query = query.where(TrackedFlight.id == flight_id)

    flights = list(db.session.scalars(query))
    if only_due:
        flights = [flight for flight in flights if is_due(flight, now)]

    results = [(flight, check_flight(flight, provider, now=now)) for flight in flights]
    db.session.commit()
    return results

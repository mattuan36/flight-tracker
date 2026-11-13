"""Recording a price observation against a tracked flight.

This is the core the M6 scheduled job will reuse: fetch one quote, append a
``PriceCheck``, and keep the denormalised columns on the tracker in step so the
dashboard never has to aggregate history.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from flask import current_app

from ..extensions import db
from ..models import Alert, PriceCheck, TrackedFlight, utcnow
from . import alerts, budget
from .prices import NoMatchingFare, PriceProvider, ProviderError, get_provider


def is_due(flight: TrackedFlight, now: datetime | None = None) -> bool:
    now = now or utcnow()
    if flight.last_checked_at is None:
        return True
    return flight.last_checked_at + timedelta(hours=flight.check_interval_hours) <= now


def next_check_at(flight: TrackedFlight, now: datetime | None = None) -> datetime | None:
    """When the hourly task will next consider this flight.

    The task runs once an hour at ``CHECK_TASK_MINUTE``. A daily interval means
    "at least 24 hours since the last attempt", not a fixed clock time, so the
    answer is the first task run at or after that due moment.
    """
    now = now or utcnow()
    if not flight.is_active or flight.depart_date < now.date():
        return None

    due = (
        now
        if flight.last_checked_at is None
        else flight.last_checked_at + timedelta(hours=flight.check_interval_hours)
    )
    if due < now:
        due = now

    minute = int(current_app.config.get("CHECK_TASK_MINUTE", 0)) % 60
    run = due.replace(minute=0, second=0, microsecond=0) + timedelta(minutes=minute)
    if run < due:
        run += timedelta(hours=1)
    return run


def check_flight(
    flight: TrackedFlight,
    provider: PriceProvider,
    *,
    now: datetime | None = None,
) -> PriceCheck:
    """Fetch one quote and record it, successes and failures alike.

    A failed check still moves ``last_checked_at``: otherwise a broken provider
    would be retried by every run instead of waiting out the interval.

    A clean no-fare response is different from a transport failure. For a tracker
    with a stops ceiling, it is the signal to widen the next search to any number
    of stops. The widening happens now, but the provider is called exactly once:
    the next scheduled run uses the relaxed setting.
    """
    now = now or utcnow()

    try:
        quote = provider.fetch(flight)
    except NoMatchingFare as exc:
        check = PriceCheck(
            tracked_flight_id=flight.id,
            checked_at=now,
            ok=False,
            provider=provider.name,
            error=str(exc)[:255],
        )
        flight.last_checked_at = now
        if flight.max_stops in (0, 1):
            flight.stops_auto_relaxed_from = flight.max_stops
            flight.max_stops = None
            flight.stops_auto_relaxed_at = now
        db.session.add(check)
        return check
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
        airline=quote.airline,
    )
    flight.last_checked_at = now
    flight.last_price_cents = quote.price_cents
    flight.last_airline = quote.airline
    if quote.currency == flight.currency and (
        flight.lowest_price_cents is None or quote.price_cents < flight.lowest_price_cents
    ):
        flight.lowest_price_cents = quote.price_cents
    db.session.add(check)
    return check


class RunResults(list[tuple[TrackedFlight, PriceCheck]]):
    """Checks performed this run, plus alerts, retries and skipped trackers."""

    def __init__(self) -> None:
        super().__init__()
        self.not_due: list[TrackedFlight] = []
        self.skipped: list[tuple[TrackedFlight, str]] = []
        self.alerts: list[Alert] = []
        self.retries: dict[str, int] = {"attempted": 0, "sent": 0, "failed": 0}


def run_checks(
    *,
    provider: PriceProvider | None = None,
    only_due: bool = True,
    user_id: int | None = None,
    flight_id: int | None = None,
    now: datetime | None = None,
) -> RunResults:
    """Check active, current trackers and commit what happened per flight.

    SerpAPI runs reserve search credits before each provider call. The monthly
    guard is hard, and ``CHECK_MAX_CALLS_PER_RUN`` keeps a single run below the
    hourly vendor limit. A return is reserved as two calls. Trackers that cannot
    be reserved are returned in ``skipped`` and are not called.
    """
    provider = provider or get_provider()
    now = now or utcnow()
    results = RunResults()

    # Retry mail from earlier runs before evaluating today's prices. This also
    # runs when nothing is due, because a failed send is not a price check.
    results.retries = alerts.process_pending(now=now, user_id=user_id, flight_id=flight_id)

    query = (
        db.select(TrackedFlight)
        .where(
            TrackedFlight.is_active.is_(True),
            TrackedFlight.depart_date >= now.date(),
        )
        .order_by(TrackedFlight.last_checked_at)
    )
    if user_id is not None:
        query = query.where(TrackedFlight.user_id == user_id)
    if flight_id is not None:
        query = query.where(TrackedFlight.id == flight_id)

    flights = list(db.session.scalars(query))
    if only_due:
        due_flights = []
        for flight in flights:
            if is_due(flight, now):
                due_flights.append(flight)
            else:
                results.not_due.append(flight)
        flights = due_flights

    uses_budget = provider.name == budget.SERPAPI_PROVIDER
    per_run_cap = max(0, int(current_app.config.get("CHECK_MAX_CALLS_PER_RUN", 20)))
    reserved_this_run = 0

    for flight in flights:
        calls = 1
        if uses_budget:
            estimated = getattr(provider, "estimated_calls", None)
            calls = int(estimated(flight)) if callable(estimated) else 1
            if reserved_this_run + calls > per_run_cap:
                results.skipped.append((flight, "per-run call cap reached"))
                continue
            if not budget.reserve(provider.name, calls, day=now.date()):
                results.skipped.append((flight, "monthly search budget reached"))
                current_app.logger.warning(
                    "Skipped %s: monthly SerpAPI budget reached", flight.route
                )
                continue
            reserved_this_run += calls

        check = check_flight(flight, provider, now=now)
        results.append((flight, check))
        # Commit each observation before the next reservation. ``reserve`` may
        # roll back when the cap is reached, and that must not undo a check that
        # already ran. The alert service commits its own pending row before it
        # tries to send, so a mail failure never loses the observation either.
        db.session.commit()
        alert = alerts.create_and_deliver(flight, check, now=now)
        if alert is not None:
            results.alerts.append(alert)

    if results.skipped:
        current_app.logger.warning(
            "Skipped %d tracker(s) because the SerpAPI budget could not cover them",
            len(results.skipped),
        )

    db.session.commit()
    return results

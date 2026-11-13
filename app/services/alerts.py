"""Alert evaluation, delivery and retry.

The policy is deliberately small and explainable:

* a ``target`` tracker alerts on the first crossing and then only on a new low
  while it stays below the target; going back above the target makes the next
  crossing a fresh event;
* an ``any_drop`` tracker adopts the first successful fare as its baseline and
  never alerts on that observation. Later alerts need a genuinely lower fare;
* a failed delivery is kept and retried on the next scheduled run, up to three
  attempts, so a transient SMTP problem does not lose the alert;
* ``last_alert_*`` on the tracker only moves after a successful send.
"""

from __future__ import annotations

import logging
from datetime import datetime

from flask import current_app, render_template
from sqlalchemy import and_, or_
from sqlalchemy.exc import IntegrityError

from ..extensions import db
from ..models import Alert, PriceCheck, TrackedFlight, utcnow
from ..money import format_cents
from . import mailer

log = logging.getLogger(__name__)

MAX_EMAIL_ATTEMPTS = 3


def process_pending(
    *,
    now: datetime | None = None,
    user_id: int | None = None,
    flight_id: int | None = None,
) -> dict[str, int]:
    """Retry alerts whose earlier delivery failed, oldest first.

    Called before a check run evaluates new prices, including when no tracker is
    due, because the retry is part of the scheduled job rather than a new alert.
    """
    now = now or utcnow()
    query = (
        db.select(Alert)
        .join(TrackedFlight)
        .where(
            Alert.email_status.in_(("pending", "failed")),
            Alert.email_attempts < MAX_EMAIL_ATTEMPTS,
        )
        .order_by(Alert.sent_at, Alert.id)
    )
    if user_id is not None:
        query = query.where(TrackedFlight.user_id == user_id)
    if flight_id is not None:
        query = query.where(TrackedFlight.id == flight_id)

    attempted = sent = failed = 0
    for alert in list(db.session.scalars(query)):
        attempted += 1
        if deliver(alert, now=now):
            sent += 1
        else:
            failed += 1

    if attempted:
        log.info("Alert retry: %d attempted, %d sent, %d failed", attempted, sent, failed)
    return {"attempted": attempted, "sent": sent, "failed": failed}


def create_and_deliver(
    flight: TrackedFlight,
    check: PriceCheck,
    *,
    now: datetime | None = None,
) -> Alert | None:
    """Evaluate one successful check, persist an alert, then try to send it."""
    now = now or utcnow()
    if check.id is None:
        db.session.flush()

    if not _eligible(flight, check, now):
        return None
    if _adopt_any_drop_baseline(flight, check):
        return None
    if not _should_alert(flight, check):
        return None

    key = f"{flight.id}:{check.id}"
    existing = db.session.scalar(db.select(Alert).where(Alert.idempotency_key == key))
    if existing is not None:
        return existing

    alert = Alert(
        tracked_flight_id=flight.id,
        price_check_id=check.id,
        price_cents=check.price_cents,
        target_cents=flight.target_price_cents,
        sent_at=now,
        email_status="pending",
        email_attempts=0,
        idempotency_key=key,
    )
    db.session.add(alert)
    try:
        db.session.commit()
    except IntegrityError:
        # Two runners raced on the same observation. The unique key means only
        # one alert exists, which is exactly the guarantee we need.
        db.session.rollback()
        return db.session.scalar(db.select(Alert).where(Alert.idempotency_key == key))

    deliver(alert, now=now)
    return alert


def deliver(alert: Alert, *, now: datetime | None = None) -> bool:
    """Send one alert, recording the attempt either way. Returns success."""
    now = now or utcnow()
    if alert.email_status == "sent":
        return True
    if alert.email_attempts >= MAX_EMAIL_ATTEMPTS:
        if alert.email_status != "failed":
            alert.email_status = "failed"
            db.session.commit()
        return False

    alert.email_attempts += 1
    alert.last_attempt_at = now

    try:
        flight = alert.tracked_flight
        user = flight.user
        if not flight.is_active:
            raise mailer.MailError("tracker is paused")
        if flight.depart_date < now.date():
            raise mailer.MailError("flight date has passed")
        if user is None or not user.is_active:
            raise mailer.MailError("account is disabled")

        subject, text_body, html_body = _render_alert(alert)
        mailer.send_email(
            to=user.email,
            subject=subject,
            text_body=text_body,
            html_body=html_body,
        )
    except Exception as exc:
        alert.email_status = "failed"
        alert.last_error = (str(exc) or exc.__class__.__name__)[:255]
        db.session.commit()
        log.warning(
            "Alert %s for flight %s failed on attempt %d/%d: %s",
            alert.id,
            alert.tracked_flight_id,
            alert.email_attempts,
            MAX_EMAIL_ATTEMPTS,
            alert.last_error,
        )
        return False

    alert.email_status = "sent"
    alert.sent_at = now
    alert.last_error = None
    flight.last_alert_at = now
    flight.last_alert_price_cents = alert.price_cents
    db.session.commit()
    return True


def _adopt_any_drop_baseline(flight: TrackedFlight, check: PriceCheck) -> bool:
    """Store the first successful fare for ``any_drop`` without alerting on it."""
    if (
        flight.mode != "any_drop"
        or not check.ok
        or check.price_cents is None
        or flight.target_price_cents is not None
    ):
        return False
    flight.target_price_cents = check.price_cents
    db.session.commit()
    return True


def _eligible(flight: TrackedFlight, check: PriceCheck, now: datetime) -> bool:
    if not check.ok or check.price_cents is None:
        return False
    if not flight.is_active or flight.depart_date < now.date():
        return False
    if flight.user is None or not flight.user.is_active:
        return False
    if check.currency and flight.currency and check.currency.upper() != flight.currency.upper():
        return False
    return not _has_outstanding_alert(flight)


def _has_outstanding_alert(flight: TrackedFlight) -> bool:
    """Do not stack a new alert behind one that is still being retried."""
    return (
        db.session.scalar(
            db.select(Alert.id)
            .where(
                Alert.tracked_flight_id == flight.id,
                Alert.email_status.in_(("pending", "failed")),
                Alert.email_attempts < MAX_EMAIL_ATTEMPTS,
            )
            .limit(1)
        )
        is not None
    )


def _should_alert(flight: TrackedFlight, check: PriceCheck) -> bool:
    target = flight.target_price_cents
    if target is None:
        return False

    if flight.mode == "any_drop":
        if check.price_cents >= target:
            return False
        if flight.last_alert_price_cents is not None:
            return check.price_cents < flight.last_alert_price_cents
        previous = _previous_success(flight, check)
        # No successful alert yet. The baseline itself is previous for the
        # first drop; after a permanent mail failure, require a genuinely lower
        # fare rather than re-alerting at the same price every run.
        return previous is None or check.price_cents < previous.price_cents

    if check.price_cents > target:
        return False

    previous = _previous_success(flight, check)
    if previous is None or previous.price_cents > target:
        # First observation at/below target, or a fresh crossing after a fare
        # went back above it.
        return True

    if flight.last_alert_price_cents is not None:
        return check.price_cents < flight.last_alert_price_cents
    # No alert has ever succeeded for this below-target run. Use the previous
    # observation as the comparison so a failed first delivery can still be
    # superseded by a genuine new low.
    return previous.price_cents is not None and check.price_cents < previous.price_cents


def _previous_success(flight: TrackedFlight, check: PriceCheck) -> PriceCheck | None:
    conditions = [
        PriceCheck.tracked_flight_id == flight.id,
        PriceCheck.ok.is_(True),
        PriceCheck.price_cents.is_not(None),
        PriceCheck.currency == flight.currency,
    ]
    if check.id is None:
        conditions.append(PriceCheck.checked_at < check.checked_at)
    else:
        conditions.append(
            or_(
                PriceCheck.checked_at < check.checked_at,
                and_(
                    PriceCheck.checked_at == check.checked_at,
                    PriceCheck.id < check.id,
                ),
            )
        )
    return db.session.scalar(
        db.select(PriceCheck)
        .where(*conditions)
        .order_by(PriceCheck.checked_at.desc(), PriceCheck.id.desc())
        .limit(1)
    )


def _render_alert(alert: Alert) -> tuple[str, str, str]:
    flight = alert.tracked_flight
    price = format_cents(alert.price_cents, flight.currency)
    target = format_cents(alert.target_cents, flight.currency)
    label = "New low fare" if flight.mode == "any_drop" else "Fare alert"
    base_url = str(current_app.config["BASE_URL"]).rstrip("/")
    context = {
        "app_name": current_app.config["APP_NAME"],
        "mode": flight.mode,
        "route": flight.route,
        "depart_date": flight.depart_date.strftime("%a %d %b %Y"),
        "return_date": (flight.return_date.strftime("%a %d %b %Y") if flight.return_date else None),
        "price": price,
        "target": target,
        "airline": flight.last_airline,
        "detail_url": f"{base_url}/flights/{flight.id}",
    }
    subject = f"{label}: {flight.route} at {price}"
    return (
        subject,
        render_template("email/alert.txt", **context),
        render_template("email/alert.html", **context),
    )

"""Jinja filters: money, local time, relative time and sparkline geometry.

Times are stored in UTC and rendered in the signed-in user's timezone, because
"departs 09:10" is meaningless without one.
"""

from __future__ import annotations

from datetime import timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from flask import current_app
from flask_login import current_user

from .airports import AIRPORT_SUGGESTIONS
from .charts import price_chart
from .labels import CABIN_LABELS, MODE_LABELS, airline_filter_label, stops_label
from .models import utcnow
from .money import format_cents
from .services import budget
from .services.checks import next_check_at


def user_timezone() -> ZoneInfo:
    name = getattr(current_user, "timezone", None) or "UTC"
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo("UTC")


def localdt(value, fmt: str = "%d %b %Y, %H:%M") -> str:
    if value is None:
        return "—"
    return value.astimezone(user_timezone()).strftime(fmt)


def localdate(value, fmt: str = "%a %d %b %Y") -> str:
    if value is None:
        return "—"
    return value.strftime(fmt)


def shortdates(depart, return_=None) -> str:
    """A compact date or date range for list rows: "19 Jul – 2 Aug 2027"."""
    if depart is None:
        return "—"
    first = f"{depart.day} {depart:%b %Y}"
    if return_ is None:
        return first
    if return_.year != depart.year:
        return f"{first} – {return_.day} {return_:%b %Y}"
    if return_.month == depart.month:
        return f"{depart.day} – {return_.day} {depart:%b %Y}"
    return f"{depart.day} {depart:%b} – {return_.day} {return_:%b %Y}"


def ago(value) -> str:
    if value is None:
        return "never"
    seconds = int((utcnow() - value).total_seconds())
    if seconds < 90:
        return "just now"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes} min ago"
    hours = minutes // 60
    if hours < 24:
        return f"{hours} hour{'s' if hours != 1 else ''} ago"
    days = hours // 24
    if days < 30:
        return f"{days} day{'s' if days != 1 else ''} ago"
    return localdate(value)


def spark_points(values, width: int = 120, height: int = 32) -> str:
    """SVG polyline points for a price series, oldest first.

    Lower prices sit lower on the chart, which is what "the price fell" should
    look like.
    """
    points = [float(value) for value in values if value is not None]
    if len(points) < 2:
        return ""
    low, high = min(points), max(points)
    span = (high - low) or 1.0
    step = width / (len(points) - 1)
    return " ".join(
        f"{index * step:.1f},{height - 2 - (value - low) / span * (height - 4):.1f}"
        for index, value in enumerate(points)
    )


def _budget_exhausted() -> bool:
    if str(current_app.config.get("PRICE_PROVIDER", "mock")).lower() != "serpapi":
        return False
    return budget.remaining() <= 0


def _relative_future(delta: timedelta) -> str:
    minutes = max(1, round(delta.total_seconds() / 60))
    if minutes < 60:
        return f"in {minutes} min"
    hours = round(minutes / 60)
    if hours < 24:
        return f"in about {hours} hour{'s' if hours != 1 else ''}"
    days = round(hours / 24)
    return f"in about {days} day{'s' if days != 1 else ''}"


def _next_run_text(flight, now):
    next_at = next_check_at(flight, now)
    if next_at is None:
        return None
    when = localdt(next_at, "%a %d %b, %H:%M %Z")
    return f"{_relative_future(next_at - now)} ({when})"


def next_check_short(flight) -> str:
    """A compact phrase for the dashboard meta line."""
    now = utcnow()
    if not flight.is_active:
        return "checks paused"
    if flight.depart_date < now.date():
        return "flight date passed"
    if _budget_exhausted():
        return "budget used up; checks resume next month"
    if flight.last_checked_at is None:
        next_at = next_check_at(flight, now)
        if next_at is None:
            return "first check pending"
        return f"first check {_relative_future(next_at - now)}"
    due = flight.last_checked_at + timedelta(hours=flight.check_interval_hours)
    if due <= now:
        return "check due now"
    next_at = next_check_at(flight, now)
    if next_at is None:
        return "no check scheduled"
    return f"next check {_relative_future(next_at - now)}"


def next_check_note(flight) -> str:
    """The sentence shown beside "last checked" on the detail page."""
    now = utcnow()
    if not flight.is_active:
        return "Paused — no checks scheduled."
    if flight.depart_date < now.date():
        return "Flight date passed — no further checks."
    if _budget_exhausted():
        return "Monthly SerpAPI budget used up — checks resume next month."
    if flight.last_checked_at is None:
        next_run = _next_run_text(flight, now)
        if next_run:
            return f"Not checked yet — the first check is {next_run}."
        return "Not checked yet — the first check will run with the next scheduled task."
    due = flight.last_checked_at + timedelta(hours=flight.check_interval_hours)
    if due <= now:
        next_run = _next_run_text(flight, now)
        if next_run:
            return f"Due now — the next scheduled run is {next_run}."
        return "Due now — waiting for the next scheduled run."
    next_run = _next_run_text(flight, now)
    if next_run:
        return f"Next scheduled check {next_run}."
    return "No further check is scheduled."


def carrier_label(flight) -> str:
    """The carrier to headline: the winner, the filter, then legacy data."""
    if flight.last_airline:
        return flight.last_airline
    if flight.airline_filter:
        return airline_filter_label(flight.airline_filter)
    if flight.airline:
        return flight.airline
    return "Any airline"


def register_template_helpers(app) -> None:
    app.jinja_env.filters.update(
        money=format_cents,
        localdt=localdt,
        localdate=localdate,
        shortdates=shortdates,
        ago=ago,
        spark_points=spark_points,
        stops=stops_label,
        airlines=airline_filter_label,
        carrier=carrier_label,
        next_check=next_check_note,
        next_check_short=next_check_short,
        cabin=lambda value: CABIN_LABELS.get(value, str(value).title()),
        mode=lambda value: MODE_LABELS.get(value, value),
    )
    app.jinja_env.globals["airports"] = AIRPORT_SUGGESTIONS
    app.jinja_env.globals["price_chart"] = price_chart

"""Jinja filters: money, local time, relative time and sparkline geometry.

Times are stored in UTC and rendered in the signed-in user's timezone, because
"departs 09:10" is meaningless without one.
"""

from __future__ import annotations

from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from flask_login import current_user

from .airports import AIRPORT_SUGGESTIONS
from .charts import price_chart
from .labels import AIRLINE_SUGGESTIONS, CABIN_LABELS, MODE_LABELS
from .models import utcnow
from .money import format_cents


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


def register_template_helpers(app) -> None:
    app.jinja_env.filters.update(
        money=format_cents,
        localdt=localdt,
        localdate=localdate,
        shortdates=shortdates,
        ago=ago,
        spark_points=spark_points,
        cabin=lambda value: CABIN_LABELS.get(value, str(value).title()),
        mode=lambda value: MODE_LABELS.get(value, value),
    )
    app.jinja_env.globals["airports"] = AIRPORT_SUGGESTIONS
    app.jinja_env.globals["airlines"] = AIRLINE_SUGGESTIONS
    app.jinja_env.globals["price_chart"] = price_chart

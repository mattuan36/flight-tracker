"""The hard SerpAPI budget guard.

Calls are counted when they are attempted, not when they succeed: a timeout, a
bad response and a no-results reply all cost a search. The monthly ceiling is
deliberately not configurable above 250, even if an environment variable asks
for more, because the free plan has no overage path.
"""

from __future__ import annotations

from datetime import date

from flask import current_app
from sqlalchemy import func, select

from ..extensions import db
from ..models import ApiUsage, utcnow

SERPAPI_PROVIDER = "serpapi"
HARD_MONTHLY_CAP = 250


def monthly_cap() -> int:
    configured = int(current_app.config.get("SERPAPI_MONTHLY_CAP", HARD_MONTHLY_CAP))
    return max(1, min(configured, HARD_MONTHLY_CAP))


def _month_bounds(day: date) -> tuple[date, date]:
    first = day.replace(day=1)
    if first.month == 12:
        after = date(first.year + 1, 1, 1)
    else:
        after = date(first.year, first.month + 1, 1)
    return first, after


def calls_this_month(provider: str = SERPAPI_PROVIDER, day: date | None = None) -> int:
    day = day or utcnow().date()
    first, after = _month_bounds(day)
    total = db.session.scalar(
        select(func.sum(ApiUsage.calls)).where(
            ApiUsage.provider == provider,
            ApiUsage.day >= first,
            ApiUsage.day < after,
        )
    )
    return int(total or 0)


def remaining(provider: str = SERPAPI_PROVIDER, day: date | None = None) -> int:
    return max(0, monthly_cap() - calls_this_month(provider, day))


def reserve(
    provider: str,
    calls: int = 1,
    *,
    day: date | None = None,
    cap: int | None = None,
) -> bool:
    """Reserve ``calls`` searches for the day, or return False at the cap.

    This commits the reservation immediately so a crash after the HTTP request
    still leaves the attempt counted. Call it before doing other database work:
    the cap-reached path rolls back the short transaction.
    """
    if calls < 1:
        raise ValueError("reserve at least one call")
    day = day or utcnow().date()
    limit = min(cap, HARD_MONTHLY_CAP) if cap is not None else monthly_cap()

    # MySQL locks the day's row; SQLite ignores FOR UPDATE but the app has one
    # scheduled checker. The explicit rollback below releases either lock.
    row = db.session.scalar(
        select(ApiUsage).where(ApiUsage.provider == provider, ApiUsage.day == day).with_for_update()
    )
    used = calls_this_month(provider, day)
    if used + calls > limit:
        db.session.rollback()
        return False

    if row is None:
        row = ApiUsage(provider=provider, day=day, calls=0)
        db.session.add(row)
    row.calls += calls
    db.session.commit()
    return True

"""The monthly SerpAPI search budget."""

from __future__ import annotations

from datetime import date

import pytest

from app.extensions import db
from app.models import ApiUsage
from app.services import budget


def test_reserve_counts_attempts_and_stops_at_the_cap(app):
    day = date(2026, 11, 10)

    assert budget.reserve("serpapi", 1, day=day, cap=2) is True
    assert budget.reserve("serpapi", 1, day=day, cap=2) is True
    assert budget.reserve("serpapi", 1, day=day, cap=2) is False
    assert budget.calls_this_month("serpapi", day) == 2
    assert db.session.scalar(db.select(ApiUsage)).calls == 2


def test_a_return_reserves_both_calls_up_front(app):
    day = date(2026, 11, 10)

    assert budget.reserve("serpapi", 2, day=day, cap=3) is True
    assert budget.calls_this_month("serpapi", day) == 2
    assert budget.reserve("serpapi", 2, day=day, cap=3) is False


def test_usage_resets_at_the_month_boundary(app):
    october = date(2026, 10, 31)
    november = date(2026, 11, 10)

    assert budget.reserve("serpapi", 1, day=october, cap=2) is True

    assert budget.calls_this_month("serpapi", october) == 1
    assert budget.calls_this_month("serpapi", november) == 0
    assert budget.remaining("serpapi", november) == 250


def test_hard_cap_cannot_be_raised_by_configuration(app, monkeypatch):
    monkeypatch.setitem(app.config, "SERPAPI_MONTHLY_CAP", 10_000)

    assert budget.monthly_cap() == budget.HARD_MONTHLY_CAP


def test_reserve_rejects_zero_or_negative_calls(app):
    with pytest.raises(ValueError, match="at least one"):
        budget.reserve("serpapi", 0)

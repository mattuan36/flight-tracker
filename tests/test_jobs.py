"""The scheduled entry point reuses the normal check pipeline."""

from __future__ import annotations

from datetime import timedelta

from jobs.check_prices import run
from sqlalchemy import select

from app.extensions import db
from app.models import PriceCheck, TrackedFlight, User, utcnow
from app.services import mailer


def make_user() -> User:
    user = User(email="friend@example.com", display_name="Friend")
    user.set_password("a-long-enough-password")
    db.session.add(user)
    db.session.commit()
    return user


def test_job_runs_due_checks_and_sends_an_alert(app, monkeypatch):
    user = make_user()
    flight = TrackedFlight(
        user_id=user.id,
        origin_iata="PDX",
        dest_iata="OAK",
        depart_date=utcnow().date() + timedelta(days=90),
        currency="USD",
        target_price_cents=1_000_000,
        mode="target",
    )
    db.session.add(flight)
    db.session.commit()
    sent: list[dict] = []
    monkeypatch.setattr("app.services.mailer.send_email", lambda **kwargs: sent.append(kwargs))

    results = run(app=app)

    assert len(results) == 1
    assert db.session.scalar(select(PriceCheck)) is not None
    assert len(results.alerts) == 1
    assert len(sent) == 1


def test_job_refuses_serpapi_without_a_key(app, monkeypatch):
    app.config["PRICE_PROVIDER"] = "serpapi"
    app.config["SERPAPI_KEY"] = ""
    monkeypatch.setattr(mailer, "send_email", lambda **kwargs: None)

    try:
        run(app=app)
    except RuntimeError as exc:
        assert "SERPAPI_KEY is not set" in str(exc)
    else:  # pragma: no cover - the assertion is the point of the test
        raise AssertionError("the job should refuse a missing SerpAPI key")

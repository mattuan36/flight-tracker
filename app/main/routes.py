"""Public pages: landing (or dashboard), health check, robots.txt."""

from __future__ import annotations

from flask import Blueprint, current_app, jsonify, render_template
from flask_login import current_user
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import selectinload

from ..extensions import db
from ..models import TrackedFlight

main_bp = Blueprint("main", __name__)


@main_bp.get("/")
def index():
    if not current_user.is_authenticated:
        return render_template("index.html", app_name=current_app.config["APP_NAME"])

    flights = list(
        db.session.scalars(
            db.select(TrackedFlight)
            .where(TrackedFlight.user_id == current_user.id)
            .options(selectinload(TrackedFlight.price_checks))
            .order_by(
                TrackedFlight.is_active.desc(),
                TrackedFlight.depart_date,
                TrackedFlight.id,
            )
        )
    )
    active = [flight for flight in flights if flight.is_active]

    return render_template(
        "dashboard.html",
        app_name=current_app.config["APP_NAME"],
        flights=flights,
        active_count=len(active),
        below_count=len([flight for flight in active if flight.is_below_target]),
    )


@main_bp.get("/robots.txt")
def robots():
    """Private tool: keep it out of search engines entirely."""
    return "User-agent: *\nDisallow: /\n", 200, {"Content-Type": "text/plain; charset=utf-8"}


@main_bp.get("/health")
def health():
    """Used by the deploy smoke check and, later, by the task watchdog."""
    database_ok = True
    try:
        db.session.execute(text("SELECT 1"))
    except SQLAlchemyError:
        database_ok = False
        current_app.logger.exception("health check could not reach the database")

    payload = {
        "status": "ok" if database_ok else "degraded",
        "app": current_app.config["APP_NAME"],
        "environment": current_app.config.get("ENV_NAME", "dev"),
        "database": "up" if database_ok else "down",
    }
    return jsonify(payload), (200 if database_ok else 503)

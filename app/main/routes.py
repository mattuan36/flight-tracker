"""Public pages: landing, health check."""

from __future__ import annotations

from flask import Blueprint, current_app, jsonify, render_template
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from ..extensions import db

main_bp = Blueprint("main", __name__)


@main_bp.get("/")
def index():
    return render_template("index.html", app_name=current_app.config["APP_NAME"])


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

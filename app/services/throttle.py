"""Login throttling and audit.

Counters live in the database because three web workers each hold their own
memory; an in-process counter would let an attacker get three times the
attempts, and forget everything on reload.
"""

from __future__ import annotations

from datetime import timedelta

from flask import current_app
from sqlalchemy import func

from ..extensions import db
from ..models import LoginAttempt, utcnow


def record_attempt(email: str | None, ip: str | None, *, success: bool) -> None:
    db.session.add(LoginAttempt(email=email, ip=ip, success=success))
    db.session.commit()


def _failures(email: str | None, since, ip: str | None) -> int:
    query = (
        db.select(func.count())
        .select_from(LoginAttempt)
        .where(LoginAttempt.success.is_(False), LoginAttempt.attempted_at >= since)
    )
    if email is not None:
        query = query.where(LoginAttempt.email == email)
    if ip is not None:
        query = query.where(LoginAttempt.ip == ip)
    return db.session.scalar(query) or 0


def is_throttled(email: str | None, ip: str | None) -> bool:
    """True when this email or this IP has failed too often, too recently.

    Both windows are configurable; the email window is short and tight, the IP
    window longer and looser, so one person fat-fingering a password cannot lock
    out a shared connection.
    """
    now = utcnow()
    window = timedelta(minutes=current_app.config["LOGIN_WINDOW_MINUTES"])

    if email:
        email_failures = _failures(email, now - window, ip=None)
        if email_failures >= current_app.config["LOGIN_MAX_ATTEMPTS"]:
            return True

    if ip:
        ip_failures = _failures(None, now - timedelta(hours=1), ip=ip)
        if ip_failures >= current_app.config["LOGIN_IP_MAX_ATTEMPTS"]:
            return True

    return False

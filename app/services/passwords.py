"""Password policy and password-reset tokens."""

from __future__ import annotations

import logging
from datetime import timedelta
from functools import lru_cache
from pathlib import Path

from flask import current_app

from ..extensions import db
from ..models import PasswordReset, User, utcnow
from .tokens import hash_token, new_token

log = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
COMMON_PASSWORDS_FILE = DATA_DIR / "common-passwords.txt"


@lru_cache(maxsize=1)
def common_passwords() -> frozenset[str]:
    """The bundled list of very common passwords, lowercased.

    Missing file is not fatal (the length rule still applies) but it is logged,
    because silently losing a check is worse than a noisy log line.
    """
    try:
        with COMMON_PASSWORDS_FILE.open(encoding="utf-8", errors="ignore") as handle:
            words = {line.strip().casefold() for line in handle if line.strip()}
    except OSError:
        log.warning("common password list missing at %s", COMMON_PASSWORDS_FILE)
        return frozenset()
    return frozenset(words)


def validate_password(
    password: str,
    *,
    email: str = "",
    display_name: str = "",
    min_length: int | None = None,
    max_length: int | None = None,
) -> list[str]:
    """Return user-facing problems with a password; empty means acceptable.

    Length does the heavy lifting; the list check catches ``password123`` style
    choices that are long enough but hopeless. No composition rules, because
    they push people towards ``Passw0rd!`` and not towards entropy.
    """
    min_length = min_length or current_app.config.get("PASSWORD_MIN_LENGTH", 12)
    max_length = max_length or current_app.config.get("PASSWORD_MAX_LENGTH", 128)
    problems: list[str] = []

    if len(password) < min_length:
        problems.append(f"Use at least {min_length} characters.")
    if len(password) > max_length:
        problems.append(f"Use at most {max_length} characters.")
    if password.strip() != password:
        problems.append("Do not start or end the password with spaces.")
    if password.casefold() in common_passwords():
        problems.append("That password is one of the most commonly used ones; pick another.")

    local_part = email.split("@")[0].strip().casefold() if "@" in email else ""
    lowered = password.casefold()
    if local_part and len(local_part) >= 3 and local_part in lowered:
        problems.append("Do not use your email address in the password.")
    if display_name and len(display_name) >= 3 and display_name.casefold() in lowered:
        problems.append("Do not use your name in the password.")

    return problems


def request_reset(user: User, *, requested_ip: str | None = None) -> tuple[PasswordReset, str]:
    """Create a reset token, invalidating any earlier unused ones."""
    now = utcnow()
    for existing in db.session.scalars(
        db.select(PasswordReset).where(
            PasswordReset.user_id == user.id, PasswordReset.used_at.is_(None)
        )
    ):
        existing.used_at = now

    raw = new_token()
    reset = PasswordReset(
        user_id=user.id,
        token_hash=hash_token(raw),
        created_at=now,
        expires_at=now + timedelta(minutes=current_app.config["RESET_TTL_MINUTES"]),
        requested_ip=requested_ip,
    )
    db.session.add(reset)
    return reset, raw


def find_reset(raw: str) -> PasswordReset | None:
    return db.session.scalar(
        db.select(PasswordReset).where(PasswordReset.token_hash == hash_token(raw))
    )


def invalidate_all_resets(user: User) -> None:
    now = utcnow()
    for reset in db.session.scalars(
        db.select(PasswordReset).where(
            PasswordReset.user_id == user.id, PasswordReset.used_at.is_(None)
        )
    ):
        reset.used_at = now

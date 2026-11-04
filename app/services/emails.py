"""Email address normalisation and validation."""

from __future__ import annotations

from email_validator import EmailNotValidError, validate_email


def normalize(email: str) -> str:
    return email.strip().lower()


def clean(email: str) -> str:
    """Return the address lowercased, or raise ValueError with a readable reason."""
    try:
        result = validate_email(email.strip(), check_deliverability=False)
    except EmailNotValidError as exc:
        raise ValueError(str(exc)) from exc
    return result.normalized.lower()

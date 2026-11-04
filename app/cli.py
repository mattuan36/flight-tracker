"""Custom ``flask`` commands.

M0 ships the two commands that help you tell whether an environment is wired
up: ``config`` and ``health``. The admin commands (invite, users, ...) arrive
in M2.
"""

from __future__ import annotations

import re

import click
from flask import current_app
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from .extensions import db

_URL_PASSWORD = re.compile(r"(?<=://)([^:/@]+):([^@]*)@")


def _redact_url(url: str) -> str:
    if not url:
        return "<not set>"
    return _URL_PASSWORD.sub(r"\1:***@", url)


def _mask_secret(value: str | None) -> str:
    if not value:
        return "<not set>"
    if len(value) <= 8:
        return "<set>"
    return f"<set: {value[:4]}...>"


def _settings_rows(app) -> list[tuple[str, str]]:
    return [
        ("APP_ENV", str(app.config.get("ENV_NAME", "?"))),
        ("APP_NAME", str(app.config["APP_NAME"])),
        ("BASE_URL", str(app.config["BASE_URL"])),
        ("PRICE_PROVIDER", str(app.config["PRICE_PROVIDER"])),
        ("ADMIN_EMAIL", str(app.config.get("ADMIN_EMAIL") or "<not set>")),
        ("SECRET_KEY", _mask_secret(app.config.get("SECRET_KEY"))),
        ("DATABASE_URL", _redact_url(str(app.config.get("DATABASE_URL") or ""))),
        ("SQLALCHEMY_DATABASE_URI", _redact_url(str(app.config["SQLALCHEMY_DATABASE_URI"]))),
        ("LOG_LEVEL", str(app.config.get("LOG_LEVEL"))),
    ]


@click.command("config")
def config_command() -> None:
    """Print the resolved settings, with secrets masked."""
    app = current_app
    rows = _settings_rows(app)
    width = max(len(key) for key, _ in rows)
    for key, value in rows:
        click.echo(f"{key.ljust(width)}  {value}")


@click.command("health")
def health_command() -> None:
    """Check the database from the command line; non-zero exit on failure."""
    app = current_app
    try:
        db.session.execute(text("SELECT 1"))
    except SQLAlchemyError as exc:
        click.echo(f"database: DOWN ({exc.__class__.__name__})", err=True)
        raise SystemExit(1) from exc
    click.echo(f"database: up ({_redact_url(str(app.config['SQLALCHEMY_DATABASE_URI']))})")
    click.echo("status: ok")


def register_cli(app) -> None:
    app.cli.add_command(config_command)
    app.cli.add_command(health_command)

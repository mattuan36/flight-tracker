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


@click.command("seed-demo")
@click.option("--email", required=True, help="Account to create, or reuse if it already exists.")
@click.option("--password", required=True, help="Demo accounts only; this lands in shell history.")
@click.option("--name", default=None, help="Display name; defaults to the email local part.")
@click.option("--reset", is_flag=True, help="Delete this user's tracked flights before seeding.")
@click.option("--force", is_flag=True, help="Permit running against APP_ENV=prod.")
def seed_demo_command(
    email: str, password: str, name: str | None, reset: bool, force: bool
) -> None:
    """Create a demo account with tracked flights and price history."""
    from .seed import seed_demo

    if current_app.config.get("ENV_NAME") == "prod" and not force:
        raise click.ClickException(
            "refusing to seed demo data in production (pass --force if you really mean it)"
        )

    result = seed_demo(email, password, display_name=name, reset=reset)
    user = result["user"]

    click.echo(f"user:    {user.email} (role={user.role}, id={user.id})")
    if result["skipped"]:
        click.echo(f"skipped: {result['skipped']}")
        return
    click.echo(f"flights: {result['created_flights']} tracked flights")
    click.echo(f"checks:  {result['created_checks']} price checks")
    click.echo(f"alerts:  {result['created_alerts']} sent alert(s)")
    if result["created_user"]:
        click.echo("sign in with the password you passed to this command")


def register_cli(app) -> None:
    app.cli.add_command(config_command)
    app.cli.add_command(health_command)
    app.cli.add_command(seed_demo_command)

"""Custom ``flask`` commands.

M0 ships the two commands that help you tell whether an environment is wired
up: ``config`` and ``health``. The admin commands (invite, users, ...) arrive
in M2.
"""

from __future__ import annotations

import re
from datetime import date, timedelta

import click
from flask import current_app
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from .extensions import db
from .labels import AIRLINE_LABELS, airline_filter_label, split_airline_filter, stops_label
from .models import CABINS, utcnow
from .money import format_cents
from .services import emails as email_service

_URL_PASSWORD = re.compile(r"(?<=://)([^:/@]+):([^@]*)@")
_ROUTE = re.compile(r"^([A-Za-z]{3})-([A-Za-z]{3})$")


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
        ("SERPAPI_KEY", _mask_secret(app.config.get("SERPAPI_KEY"))),
        ("SERPAPI_MONTHLY_CAP", str(app.config.get("SERPAPI_MONTHLY_CAP"))),
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


@click.command("check-prices")
@click.option("--email", default=None, help="Only this account's flights.")
@click.option("--flight", "flight_id", type=int, default=None, help="Only this tracker id.")
@click.option("--all", "run_all", is_flag=True, help="Ignore each flight's check interval.")
def check_prices_command(email: str | None, flight_id: int | None, run_all: bool) -> None:
    """Record fares from the configured provider.

    Run by hand now; M6 moves the same service into the hourly scheduled task.
    The SerpAPI path is budget-guarded in ``checks.run_checks``.
    """
    from .models import TrackedFlight, User
    from .services import checks
    from .services.prices import get_provider

    provider = get_provider()
    if provider.name == "serpapi" and not str(current_app.config.get("SERPAPI_KEY") or "").strip():
        raise click.ClickException("SERPAPI_KEY is not set; add it to .env")

    user_id = None
    if email:
        try:
            normalised = email_service.clean(email)
        except ValueError as exc:
            raise click.ClickException(str(exc)) from exc
        user = db.session.scalar(db.select(User).where(User.email == normalised))
        if user is None:
            raise click.ClickException(f"no account for {normalised}")
        user_id = user.id

    if flight_id is not None:
        tracker = db.session.get(TrackedFlight, flight_id)
        if tracker is None:
            raise click.ClickException(f"no tracker with id {flight_id}")
        if not tracker.is_active:
            raise click.ClickException(f"tracker {flight_id} is paused; resume it first")

    results = checks.run_checks(
        provider=provider, only_due=not run_all, user_id=user_id, flight_id=flight_id
    )
    if not results and not results.skipped:
        click.echo("nothing due; use --all to check every active tracker")
        return

    ok = 0
    for flight, check in results:
        if check.ok:
            ok += 1
            price = format_cents(check.price_cents, check.currency or flight.currency)
            click.echo(f"{flight.route:<8} {flight.depart_date.isoformat()}  {price:>10}")
        else:
            click.echo(f"{flight.route:<8} {flight.depart_date.isoformat()}  failed: {check.error}")
        if flight.is_auto_relaxed:
            click.echo(
                "  warning: stops relaxed from "
                f"{stops_label(flight.stops_auto_relaxed_from)} to "
                f"{stops_label(flight.max_stops)}"
            )

    for flight, reason in results.skipped:
        click.echo(f"{flight.route:<8} {flight.depart_date.isoformat()}  skipped: {reason}")

    click.echo(
        f"\n{len(results)} checked, {ok} ok, {len(results) - ok} failed, "
        f"{len(results.skipped)} skipped"
    )


@click.command("probe-prices")
@click.option(
    "--route", default="PDX-OAK", show_default=True, help="Origin-destination, e.g. PDX-MDW."
)
@click.option("--depart", "depart_raw", default=None, help="YYYY-MM-DD; defaults to 8 weeks out.")
@click.option("--return", "return_raw", default=None, help="YYYY-MM-DD for a return trip.")
@click.option("--max-stops", type=click.Choice(["0", "1", "any"]), default="0", show_default=True)
@click.option("--adults", type=click.IntRange(1, 9), default=1, show_default=True)
@click.option("--cabin", type=click.Choice(CABINS), default="economy", show_default=True)
@click.option(
    "--airline",
    "airlines",
    multiple=True,
    metavar="IATA",
    help="Include this airline; repeat for several. Omit for any airline.",
)
def probe_prices_command(
    route: str,
    depart_raw: str | None,
    return_raw: str | None,
    max_stops: str,
    adults: int,
    cabin: str,
    airlines: tuple[str, ...],
) -> None:
    """Probe one itinerary without writing a PriceCheck.

    This is the M4b operator tool: it spends searches from the same monthly
    budget as the checker, prints the result, and only writes ``ApiUsage``.
    """
    from .models import TrackedFlight
    from .services import budget
    from .services.prices import NoMatchingFare, ProviderError
    from .services.serpapi import SerpApiProvider

    match = _ROUTE.match(route.strip())
    if not match:
        raise click.ClickException("route must look like PDX-OAK")
    origin, dest = (part.upper() for part in match.groups())

    def parse_date(value: str | None, name: str) -> date | None:
        if not value:
            return None
        try:
            return date.fromisoformat(value)
        except ValueError as exc:
            raise click.ClickException(f"{name} must be YYYY-MM-DD") from exc

    depart = parse_date(depart_raw, "--depart") or (utcnow().date() + timedelta(weeks=8))
    return_date = parse_date(return_raw, "--return")
    if return_date is not None and return_date < depart:
        raise click.ClickException("--return cannot be before --depart")

    if not str(current_app.config.get("SERPAPI_KEY") or "").strip():
        raise click.ClickException("SERPAPI_KEY is not set; add it to .env")

    codes = split_airline_filter(",".join(airlines))
    unsupported = [code for code in codes if code not in AIRLINE_LABELS]
    if unsupported:
        raise click.ClickException(
            "unsupported airline code(s): "
            f"{', '.join(unsupported)}; choose from {', '.join(AIRLINE_LABELS)}"
        )

    flight = TrackedFlight(
        origin_iata=origin,
        dest_iata=dest,
        depart_date=depart,
        return_date=return_date,
        cabin=cabin,
        adults=adults,
        currency="USD",
        max_stops=None if max_stops == "any" else int(max_stops),
        airline_filter=",".join(codes) or None,
    )
    provider = SerpApiProvider()
    calls = provider.estimated_calls(flight)

    click.echo(
        f"route:   {flight.route}  {depart.isoformat()}"
        + (f" to {return_date.isoformat()}" if return_date else "")
    )
    click.echo(f"stops:   {flight.max_stops if flight.max_stops is not None else 'any'}")
    click.echo(f"airline: {airline_filter_label(flight.airline_filter)}")
    if not budget.reserve(provider.name, calls):
        used = budget.calls_this_month(provider.name)
        raise click.ClickException(
            f"monthly SerpAPI budget reached ({used}/{budget.monthly_cap()}); no request was sent"
        )
    click.echo(f"calls:   {calls} reserved")

    try:
        quote = provider.fetch(flight)
    except NoMatchingFare as exc:
        click.echo(f"result:  no matching fare ({exc})")
        if flight.max_stops in (0, 1):
            click.echo("relax:   a scheduled check would widen this tracker to any stops.")
    except ProviderError as exc:
        raise click.ClickException(f"probe failed: {exc}") from exc
    else:
        click.echo(
            f"fare:    {format_cents(quote.price_cents, quote.currency)} "
            f"({quote.currency}, party total)"
        )
        click.echo(f"carrier: {quote.airline or 'not reported'}")
        click.echo(f"source:  {quote.provider}")
    click.echo(
        f"budget:  {budget.calls_this_month(provider.name)}/{budget.monthly_cap()} "
        "searches used this month"
    )


def register_cli(app) -> None:
    from .cli_admin import COMMANDS

    app.cli.add_command(config_command)
    app.cli.add_command(health_command)
    app.cli.add_command(seed_demo_command)
    app.cli.add_command(check_prices_command)
    app.cli.add_command(probe_prices_command)
    for command in COMMANDS:
        app.cli.add_command(command)

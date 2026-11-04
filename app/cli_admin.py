"""Admin commands. Invite-only means these are the only way accounts appear."""

from __future__ import annotations

import click
from flask import current_app
from sqlalchemy import func, select

from .extensions import db
from .models import Invite, TrackedFlight, User
from .services import emails as email_service
from .services import invites as invite_service
from .services import passwords
from .services.tokens import token_url


def _email_arg(ctx, param, value: str) -> str:
    try:
        return email_service.clean(value)
    except ValueError as exc:
        raise click.BadParameter(str(exc)) from exc


def _when(value) -> str:
    return value.strftime("%d %b %Y %H:%M UTC") if value else "-"


def _link(path: str, raw: str) -> str:
    """Always built from BASE_URL, never from the request or the terminal's host."""
    return token_url(current_app.config["BASE_URL"], path, raw)


def _require_user(email: str) -> User:
    user = db.session.scalar(select(User).where(User.email == email))
    if user is None:
        raise click.ClickException(f"no account for {email}")
    return user


@click.command("invite")
@click.argument("email", callback=_email_arg)
@click.option("--expires-in", "expires_in", type=int, default=None, help="Days until expiry.")
@click.option(
    "--force", is_flag=True, help="Replace a pending invite for this address with a new one."
)
def invite_command(email: str, expires_in: int | None, force: bool) -> None:
    """Create an invite and print its link. Paste the link to the person yourself."""
    if db.session.scalar(select(User).where(User.email == email)) is not None:
        raise click.ClickException(
            f"{email} already has an account; use `flask reset-link` if they are locked out"
        )

    pending = invite_service.pending_for(email)
    if pending is not None:
        if not force:
            raise click.ClickException(
                f"a pending invite for {email} already exists, "
                f"expiring {_when(pending.expires_at)}; pass --force to replace it"
            )
        invite_service.revoke(pending)
        db.session.flush()  # clear pending_key before inserting the replacement

    invite, raw = invite_service.create_invite(
        email, created_by_id=_current_admin_id(), ttl_days=expires_in
    )
    db.session.commit()

    click.echo(f"Invite for {email} - expires {_when(invite.expires_at)}")
    click.echo()
    click.echo(f"  {_link('/invite/', raw)}")
    click.echo()
    click.echo("Single use. Send it however you like; the raw token is not stored.")


def _current_admin_id() -> int | None:
    """Attribute the invite to an admin when exactly one exists."""
    admins = list(
        db.session.scalars(select(User).where(User.role == "admin", User.is_active.is_(True)))
    )
    return admins[0].id if len(admins) == 1 else None


@click.command("invites")
@click.option(
    "--all", "show_all", is_flag=True, help="Include used, expired and cancelled invites."
)
def invites_command(show_all: bool) -> None:
    """List invites."""
    query = select(Invite).order_by(Invite.created_at.desc())
    rows = list(db.session.scalars(query))

    shown = 0
    for invite in rows:
        status = invite_service.status_of(invite)
        if not show_all and status != invite_service.OK:
            continue
        shown += 1
        click.echo(
            f"{invite.email:<32} {status:<8} expires {_when(invite.expires_at)}  "
            f"created {_when(invite.created_at)}"
        )

    if shown == 0:
        click.echo("no invites to show" if show_all else "no pending invites (use --all)")
    else:
        click.echo(f"\n{shown} shown")


@click.command("revoke-invite")
@click.argument("email", callback=_email_arg)
def revoke_invite_command(email: str) -> None:
    """Cancel any pending invite for an address."""
    count = invite_service.revoke_all_pending(email)
    db.session.commit()
    if count == 0:
        raise click.ClickException(f"no pending invite for {email}")
    click.echo(f"revoked {count} invite(s) for {email}")


@click.command("reissue-invite")
@click.argument("email", callback=_email_arg)
@click.option("--expires-in", "expires_in", type=int, default=None, help="Days until expiry.")
def reissue_invite_command(email: str, expires_in: int | None) -> None:
    """Revoke a pending invite and print a fresh link."""
    invite_service.revoke_all_pending(email)
    db.session.flush()

    invite, raw = invite_service.create_invite(
        email, created_by_id=_current_admin_id(), ttl_days=expires_in
    )
    db.session.commit()
    click.echo(f"New invite for {email} - expires {_when(invite.expires_at)}")
    click.echo()
    click.echo(f"  {_link('/invite/', raw)}")


@click.command("users")
def users_command() -> None:
    """List accounts with tracker counts and activity."""
    tracker_counts = dict(
        db.session.execute(
            select(TrackedFlight.user_id, func.count()).group_by(TrackedFlight.user_id)
        ).all()
    )

    click.echo(f"{'email':<34} {'role':<7} {'active':<7} {'trackers':<9} last sign-in")
    for user in db.session.scalars(select(User).order_by(User.created_at)):
        click.echo(
            f"{user.email:<34} {user.role:<7} {user.is_active!s:<7} "
            f"{tracker_counts.get(user.id, 0):<9} {_when(user.last_login_at)}"
        )


@click.command("disable-user")
@click.argument("email", callback=_email_arg)
@click.option("--purge", is_flag=True, help="Delete the account and everything it owns.")
def disable_user_command(email: str, purge: bool) -> None:
    """Block sign-in, end existing sessions and pause the user's trackers."""
    user = _require_user(email)

    if purge:
        db.session.delete(user)
        db.session.commit()
        click.echo(f"deleted {email} and all of their data")
        return

    was_active = user.is_active
    user.is_active = False
    user.session_version += 1
    for flight in user.tracked_flights:
        flight.is_active = False
    db.session.commit()

    suffix = "" if was_active else " (was already disabled)"
    click.echo(
        f"disabled {email}{suffix}; sessions ended and "
        f"{len(user.tracked_flights)} tracker(s) paused"
    )


@click.command("enable-user")
@click.argument("email", callback=_email_arg)
def enable_user_command(email: str) -> None:
    """Allow sign-in again. Trackers stay paused until the owner resumes them."""
    user = _require_user(email)
    user.is_active = True
    user.session_version += 1
    db.session.commit()
    click.echo(f"enabled {email}")


@click.command("reset-link")
@click.argument("email", callback=_email_arg)
def reset_link_command(email: str) -> None:
    """Create a password reset link and print it."""
    user = _require_user(email)
    if not user.is_active:
        raise click.ClickException(f"{email} is disabled; enable it first")

    reset, raw = passwords.request_reset(user)
    db.session.commit()

    click.echo(f"Reset link for {email} - expires {_when(reset.expires_at)}")
    click.echo()
    click.echo(f"  {_link('/reset-password/', raw)}")
    click.echo()
    click.echo(
        f"Send it yourself; it works once and dies after "
        f"{current_app.config['RESET_TTL_MINUTES']} minutes."
    )


COMMANDS = [
    invite_command,
    invites_command,
    revoke_invite_command,
    reissue_invite_command,
    users_command,
    disable_user_command,
    enable_user_command,
    reset_link_command,
]

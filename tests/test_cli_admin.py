"""Admin CLI: the only way accounts and invites appear."""

from __future__ import annotations

import re
from datetime import date

from sqlalchemy import func, select

from app.extensions import db
from app.models import Invite, PasswordReset, TrackedFlight, User
from app.services import invites as invite_service

LINK = re.compile(r"(/invite/[A-Za-z0-9_-]{43})")
RESET_LINK = re.compile(r"(/reset-password/[A-Za-z0-9_-]{43})")


def run(app, *args: str):
    return app.test_cli_runner().invoke(args=list(args))


def token_from(output: str) -> str:
    match = LINK.search(output)
    assert match, output
    return match.group(1).rsplit("/", 1)[-1]


def make_user(email: str = "friend@example.com", *, role: str = "member") -> User:
    user = User(email=email, display_name="Friend", role=role)
    user.set_password("a-long-enough-password")
    db.session.add(user)
    db.session.commit()
    return user


def test_invite_prints_a_link_and_stores_only_the_hash(app):
    result = run(app, "invite", "friend@example.com")

    assert result.exit_code == 0
    raw = token_from(result.output)
    assert "invite" in result.output.lower()

    db.session.expire_all()
    invite = db.session.scalar(select(Invite))
    assert invite is not None
    assert invite.email == "friend@example.com"
    assert invite.token_hash != raw
    assert len(invite.token_hash) == 64
    assert invite_service.find_by_token(raw) is not None


def test_invite_normalises_the_address(app):
    run(app, "invite", "  Friend@Example.COM ")

    db.session.expire_all()
    assert db.session.scalar(select(Invite)).email == "friend@example.com"


def test_invite_refuses_a_second_pending_invite(app):
    run(app, "invite", "friend@example.com")

    result = run(app, "invite", "friend@example.com")

    assert result.exit_code != 0
    assert "--force" in result.output


def test_force_replaces_the_pending_invite(app):
    first = run(app, "invite", "friend@example.com")
    first_raw = token_from(first.output)

    second = run(app, "invite", "friend@example.com", "--force")
    second_raw = token_from(second.output)

    assert second.exit_code == 0
    assert first_raw != second_raw

    db.session.expire_all()
    old = invite_service.find_by_token(first_raw)
    assert old is not None and old.revoked_at is not None
    new = invite_service.find_by_token(second_raw)
    assert new is not None and new.revoked_at is None and new.used_at is None


def test_invite_refuses_an_existing_account(app):
    make_user("friend@example.com")

    result = run(app, "invite", "friend@example.com")

    assert result.exit_code != 0
    assert "reset-link" in result.output


def test_invite_rejects_a_malformed_address(app):
    result = run(app, "invite", "not-an-email")

    assert result.exit_code != 0
    assert db.session.scalar(select(func.count()).select_from(Invite)) == 0


def test_reissue_revokes_and_prints_a_new_link(app):
    old = run(app, "invite", "friend@example.com")
    old_raw = token_from(old.output)

    new = run(app, "reissue-invite", "friend@example.com")

    assert new.exit_code == 0
    new_raw = token_from(new.output)
    assert new_raw != old_raw
    db.session.expire_all()
    old_invite = invite_service.find_by_token(old_raw)
    assert old_invite is not None and old_invite.revoked_at is not None
    new_invite = invite_service.find_by_token(new_raw)
    assert new_invite is not None and new_invite.revoked_at is None


def test_revoke_invite_kills_the_link(app):
    created = run(app, "invite", "friend@example.com")
    raw = token_from(created.output)

    result = run(app, "revoke-invite", "friend@example.com")

    assert result.exit_code == 0
    assert "revoked 1" in result.output
    db.session.expire_all()
    assert invite_service.find_by_token(raw).revoked_at is not None


def test_users_lists_accounts(app):
    make_user("one@example.com")
    make_user("two@example.com", role="admin")

    result = run(app, "users")

    assert result.exit_code == 0
    assert "one@example.com" in result.output
    assert "two@example.com" in result.output
    assert "admin" in result.output


def test_disable_user_pauses_trackers_and_bumps_session_version(app):
    user = make_user()
    db.session.add(
        TrackedFlight(
            user=user,
            origin_iata="LHR",
            dest_iata="JFK",
            depart_date=date(2027, 3, 14),
            is_active=True,
        )
    )
    db.session.commit()

    result = run(app, "disable-user", "friend@example.com")

    assert result.exit_code == 0
    db.session.expire_all()
    user = db.session.scalar(select(User).where(User.email == "friend@example.com"))
    assert user.is_active is False
    assert user.session_version == 1
    assert user.tracked_flights[0].is_active is False


def test_enable_user_allows_sign_in_again_without_resuming_trackers(app):
    user = make_user()
    user.is_active = False
    db.session.commit()

    result = run(app, "enable-user", "friend@example.com")

    assert result.exit_code == 0
    db.session.expire_all()
    assert db.session.scalar(select(User)).is_active is True


def test_purge_deletes_the_account_and_its_data(app):
    user = make_user()
    db.session.add(
        TrackedFlight(
            user=user,
            origin_iata="LHR",
            dest_iata="JFK",
            depart_date=date(2027, 3, 14),
        )
    )
    db.session.commit()

    result = run(app, "disable-user", "friend@example.com", "--purge")

    assert result.exit_code == 0
    db.session.expire_all()
    assert db.session.scalar(select(func.count()).select_from(User)) == 0
    assert db.session.scalar(select(func.count()).select_from(TrackedFlight)) == 0


def test_disable_unknown_user_fails_cleanly(app):
    result = run(app, "disable-user", "nobody@example.com")

    assert result.exit_code != 0
    assert "no account" in result.output


def test_reset_link_prints_a_working_link(app):
    make_user()

    result = run(app, "reset-link", "friend@example.com")

    assert result.exit_code == 0
    match = RESET_LINK.search(result.output)
    assert match, result.output

    client = app.test_client()
    response = client.get(match.group(1))
    assert response.status_code == 200
    assert b"Choose a new password" in response.data

    db.session.expire_all()
    assert db.session.scalar(select(func.count()).select_from(PasswordReset)) == 1


def test_reset_link_refuses_a_disabled_account(app):
    user = make_user()
    user.is_active = False
    db.session.commit()

    result = run(app, "reset-link", "friend@example.com")

    assert result.exit_code != 0
    assert "disabled" in result.output

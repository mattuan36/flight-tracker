"""Invite acceptance, sign-in, session invalidation and password reset."""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import func, select

from app.extensions import db
from app.models import Invite, LoginAttempt, User, utcnow
from app.services import invites as invite_service
from app.services import passwords

GOOD_PASSWORD = "a-long-enough-password"


@pytest.fixture(autouse=True)
def _app_context(app):
    """The password policy reads config, and every test here uses the session."""
    return app


def make_user(
    email: str = "friend@example.com",
    password: str = GOOD_PASSWORD,
    *,
    role: str = "member",
    active: bool = True,
) -> User:
    user = User(email=email, display_name="Friend", role=role, is_active=active)
    user.set_password(password)
    db.session.add(user)
    db.session.commit()
    return user


def make_invite(email: str = "invited@example.com", **kwargs) -> tuple[Invite, str]:
    invite, raw = invite_service.create_invite(email, **kwargs)
    db.session.commit()
    return invite, raw


def sign_in(client, email: str = "friend@example.com", password: str = GOOD_PASSWORD):
    return client.post("/login", data={"email": email, "password": password})


def accept(client, raw: str, *, password: str = GOOD_PASSWORD, name: str = "Invited"):
    return client.post(
        f"/invite/{raw}",
        data={
            "display_name": name,
            "timezone": "Europe/London",
            "password": password,
            "confirm": password,
        },
    )


# --- invite pages ---------------------------------------------------------


def test_valid_invite_renders_the_form(client):
    _, raw = make_invite()

    response = client.get(f"/invite/{raw}")

    assert response.status_code == 200
    assert b"invited@example.com" in response.data


def test_unknown_token_is_a_404(client):
    response = client.get("/invite/" + "A" * 43)

    assert response.status_code == 404
    assert b"does not work" in response.data


def test_malformed_token_is_a_404_without_hitting_the_database(client):
    response = client.get("/invite/not-a-token")

    assert response.status_code == 404


def test_revoked_invite_says_cancelled(client):
    invite, raw = make_invite()
    invite.revoked_at = utcnow()
    db.session.commit()

    response = client.get(f"/invite/{raw}")

    assert response.status_code == 410
    assert b"cancelled" in response.data


def test_expired_invite_says_expired(client):
    invite, raw = make_invite()
    invite.expires_at = utcnow() - timedelta(minutes=1)
    db.session.commit()

    response = client.get(f"/invite/{raw}")

    assert response.status_code == 410
    assert b"expired" in response.data
    assert b"cancelled" not in response.data


def test_used_invite_offers_sign_in(client):
    invite, raw = make_invite()
    invite.used_at = utcnow()
    db.session.commit()

    response = client.get(f"/invite/{raw}")

    assert response.status_code == 200
    assert b"already been used" in response.data
    assert b"login?email=invited@example.com" in response.data


# --- accepting ------------------------------------------------------------


def test_accepting_creates_an_account_and_signs_in(client):
    invite, raw = make_invite()

    response = accept(client, raw)

    assert response.status_code == 302
    assert response.headers["Location"] == "/"

    user = db.session.scalar(select(User).where(User.email == "invited@example.com"))
    assert user is not None
    assert user.role == "member"
    assert user.display_name == "Invited"
    assert user.timezone == "Europe/London"
    assert user.check_password(GOOD_PASSWORD)

    db.session.refresh(invite)
    assert invite.used_at is not None
    assert invite.accepted_user_id == user.id
    assert invite.pending_key is None

    # Signed in: the dashboard is theirs.
    assert b"Your flights" in client.get("/").data


def test_used_invite_frees_the_address_for_a_new_one(client):
    _, raw = make_invite()
    accept(client, raw)

    invite, _ = make_invite()  # must not raise a unique violation
    assert invite.id is not None


def test_weak_password_does_not_burn_the_invite(client):
    invite, raw = make_invite()

    response = accept(client, raw, password="short")

    assert response.status_code == 200
    assert b"at least 12 characters" in response.data

    db.session.refresh(invite)
    assert invite.used_at is None
    assert db.session.scalar(select(func.count()).select_from(User)) == 0


def test_password_containing_the_email_is_rejected(client):
    invite, raw = make_invite("someone@example.com")

    response = accept(client, raw, password="someone-then-some-more")

    assert response.status_code == 200
    db.session.refresh(invite)
    assert invite.used_at is None


def test_accepting_twice_creates_one_account(client):
    _invite, raw = make_invite()

    accept(client, raw)
    second = accept(client, raw)

    assert second.status_code in {200, 302}
    assert db.session.scalar(select(func.count()).select_from(User)) == 1


def test_accepting_while_signed_in_as_someone_else_asks_first(client):
    make_user("existing@example.com")
    sign_in(client, "existing@example.com")
    _, raw = make_invite("invited@example.com")

    response = client.get(f"/invite/{raw}")

    assert response.status_code == 200
    assert b"existing@example.com" in response.data
    assert b"invited@example.com" in response.data
    assert db.session.scalar(select(func.count()).select_from(User)) == 1


def test_switching_accounts_signs_the_other_user_out(client):
    make_user("existing@example.com")
    sign_in(client, "existing@example.com")
    _, raw = make_invite("invited@example.com")

    response = client.post(f"/invite/{raw}/switch")

    assert response.status_code == 302
    assert response.headers["Location"] == f"/invite/{raw}"
    # The invite form is now reachable, and no account was created yet.
    assert b"invited@example.com" in client.get(f"/invite/{raw}").data
    assert b"Sign in" in client.get("/").data
    assert db.session.scalar(select(func.count()).select_from(User)) == 1


# --- sign in and out ------------------------------------------------------


def test_sign_in_succeeds(client):
    make_user()

    response = sign_in(client)

    assert response.status_code == 302
    assert response.headers["Location"] == "/"


def test_wrong_password_is_generic(client):
    make_user()

    response = sign_in(client, password="wrong-password-here")

    assert response.status_code == 401
    assert b"Email or password is incorrect" in response.data
    assert db.session.scalar(select(func.count()).select_from(LoginAttempt)) == 1


def test_unknown_email_looks_the_same_as_a_wrong_password(client):
    make_user()
    wrong_password = sign_in(client, password="wrong-password-here")
    unknown = sign_in(client, "nobody@example.com")

    assert wrong_password.status_code == unknown.status_code == 401
    assert b"Email or password is incorrect" in unknown.data


def test_disabled_account_cannot_sign_in(client):
    make_user(active=False)

    response = sign_in(client)

    assert response.status_code == 401
    assert b"Email or password is incorrect" in response.data


def test_sign_in_is_throttled_per_email(client):
    make_user()

    for _ in range(5):
        sign_in(client, password="wrong-password-here")

    response = sign_in(client)

    assert response.status_code == 429
    assert b"Too many attempts" in response.data


def test_next_parameter_only_allows_local_paths(client):
    make_user()

    local = client.post(
        "/login?next=/settings", data={"email": "friend@example.com", "password": GOOD_PASSWORD}
    )
    assert local.headers["Location"] == "/settings"

    client.post("/logout")
    hostile = client.post(
        "/login?next=//evil.example/steal",
        data={"email": "friend@example.com", "password": GOOD_PASSWORD},
    )
    assert hostile.headers["Location"] == "/"


def test_logout_clears_the_session(client):
    make_user()
    sign_in(client)

    response = client.post("/logout")

    assert response.status_code == 302
    assert b"Sign in" in client.get("/").data
    # The 30-day remember cookie must go too, or the next request restores the
    # user and /login bounces back to the dashboard.
    assert client.get("/login").status_code == 200


def test_session_version_change_logs_the_user_out(client):
    user = make_user()
    sign_in(client)

    user.session_version += 1
    db.session.commit()

    response = client.get("/")

    assert response.status_code == 302
    assert response.headers["Location"] == "/login"


# --- password reset -------------------------------------------------------


def test_forgot_password_answers_the_same_way_for_known_and_unknown_addresses(client):
    make_user()

    known = client.post("/forgot-password", data={"email": "friend@example.com"})
    unknown = client.post("/forgot-password", data={"email": "nobody@example.com"})

    assert known.status_code == unknown.status_code == 302
    assert known.headers["Location"] == unknown.headers["Location"] == "/login"


def test_reset_link_changes_the_password_and_signs_in(client):
    user = make_user()
    reset, raw = passwords.request_reset(user)
    db.session.commit()

    assert client.get(f"/reset-password/{raw}").status_code == 200

    response = client.post(
        f"/reset-password/{raw}",
        data={"password": "a-brand-new-password", "confirm": "a-brand-new-password"},
    )

    assert response.status_code == 302
    db.session.refresh(user)
    assert user.check_password("a-brand-new-password")
    assert user.session_version == 1
    db.session.refresh(reset)
    assert reset.used_at is not None
    assert b"Your flights" in client.get("/").data


def test_reset_link_works_once(client):
    user = make_user()
    _, raw = passwords.request_reset(user)
    db.session.commit()
    client.post(
        f"/reset-password/{raw}",
        data={"password": "a-brand-new-password", "confirm": "a-brand-new-password"},
    )

    second = client.get(f"/reset-password/{raw}")

    assert second.status_code == 410


def test_expired_reset_link_is_refused(client):
    user = make_user()
    reset, raw = passwords.request_reset(user)
    reset.expires_at = utcnow() - timedelta(minutes=1)
    db.session.commit()

    assert client.get(f"/reset-password/{raw}").status_code == 410


def test_requesting_a_new_reset_kills_the_old_one(client):
    user = make_user()
    _first, first_raw = passwords.request_reset(user)
    db.session.commit()
    _, second_raw = passwords.request_reset(user)
    db.session.commit()

    assert client.get(f"/reset-password/{first_raw}").status_code == 410
    assert client.get(f"/reset-password/{second_raw}").status_code == 200


def test_reset_bumps_session_version_and_kills_other_sessions(client):
    user = make_user()
    sign_in(client)
    other = client.application.test_client()
    sign_in(other)

    _, raw = passwords.request_reset(user)
    db.session.commit()
    client.post(
        f"/reset-password/{raw}",
        data={"password": "a-brand-new-password", "confirm": "a-brand-new-password"},
    )

    assert other.get("/").status_code == 302


# --- password policy ------------------------------------------------------


@pytest.mark.parametrize(
    ("password", "expected"),
    [
        ("short", "at least 12"),
        ("password", "commonly used"),
        (" friend-friend-friend ", "spaces"),
    ],
)
def test_password_policy_messages(password, expected):
    problems = passwords.validate_password(password)

    assert any(expected in problem for problem in problems)


def test_password_policy_accepts_a_long_passphrase():
    assert passwords.validate_password("correct horse battery staple", email="a@b.com") == []

"""Authentication: invite acceptance, sign in, password reset.

There is no registration route. Accounts only come from a consumed invite;
``grep`` for ``User(`` under ``app/`` should find exactly one place outside the
CLI and the seeder.
"""

from __future__ import annotations

import re
from functools import lru_cache

from flask import (
    Blueprint,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from flask_login import current_user, login_user, logout_user
from werkzeug.security import check_password_hash, generate_password_hash

from ..extensions import db
from ..models import User, utcnow
from ..services import invites as invite_service
from ..services import passwords, throttle
from ..services.tokens import looks_like_token, token_url
from .forms import (
    AcceptInviteForm,
    ForgotPasswordForm,
    LoginForm,
    ResetPasswordForm,
    SwitchAccountForm,
)

auth_bp = Blueprint("auth", __name__)

# A "next" target must be a path on this site. "//evil.example" and
# "https://evil.example" both fail, which matters because "next" is attacker
# controlled.
_LOCAL_PATH = re.compile(r"^/[^/\\]")


def _admin_email() -> str:
    return current_app.config.get("ADMIN_EMAIL") or "the site admin"


def _safe_next(target: str | None) -> str | None:
    if target and _LOCAL_PATH.match(target):
        return target
    return None


@lru_cache(maxsize=1)
def _decoy_hash() -> str:
    """A real hash of nothing, only used to equalise sign-in timing."""
    return generate_password_hash("not-a-real-password")


def _sign_in(user: User) -> None:
    """Start a fresh session for this user, with the version stamp."""
    session.clear()
    login_user(user, remember=True)
    session["sv"] = user.session_version
    session.permanent = True


def _notice(title: str, message: str, *, link: str | None = None, email: str | None = None):
    return render_template("auth/notice.html", title=title, message=message, link=link, email=email)


@auth_bp.before_app_request
def enforce_session_version():
    """Log out cookies issued before the account was disabled or its password reset.

    ``session_version`` lives on the user and is copied into the session at
    sign-in. Bumping it server-side invalidates every outstanding cookie on its
    next request, including the 30-day remember cookie.
    """
    if not current_user.is_authenticated:
        return None

    stamped = session.get("sv")
    if stamped is None:
        # Restored from a remember cookie: adopt the current version.
        session["sv"] = current_user.session_version
        return None

    if stamped != current_user.session_version:
        # Clear first: logout_user() sets the "clear" marker that deletes the
        # remember cookie, and session.clear() afterwards would erase it.
        session.clear()
        logout_user()
        flash("Your session has ended. Please sign in again.", "info")
        return redirect(url_for("auth.login"))

    return None


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("main.index"))

    form = LoginForm()
    prefill = request.args.get("email") or ""
    if request.method == "GET" and prefill:
        form.email.data = prefill

    next_url = request.args.get("next")

    if form.validate_on_submit():
        email = form.email.data.strip().lower()
        ip = request.remote_addr

        if throttle.is_throttled(email, ip):
            flash("Too many attempts. Wait a few minutes and try again.", "error")
            return render_template("auth/login.html", form=form), 429

        user = db.session.scalar(db.select(User).where(User.email == email))
        if user is None:
            # Spend the same hashing time as a real check, so response time does
            # not reveal which addresses have accounts.
            check_password_hash(_decoy_hash(), form.password.data)
            password_ok = False
        else:
            password_ok = user.check_password(form.password.data)
        allowed = password_ok and user.is_active

        throttle.record_attempt(email, ip, success=allowed)

        if not allowed:
            # Identical message for unknown address, wrong password and
            # disabled account: no account enumeration.
            flash("Email or password is incorrect.", "error")
            return render_template("auth/login.html", form=form), 401

        user.last_login_at = utcnow()
        db.session.commit()
        _sign_in(user)

        flash(f"Welcome back, {user.display_name}.", "success")
        return redirect(_safe_next(next_url) or url_for("main.index"))

    return render_template("auth/login.html", form=form)


@auth_bp.post("/logout")
def logout():
    if current_user.is_authenticated:
        session.clear()
        logout_user()
        flash("You are signed out.", "info")
    return redirect(url_for("auth.login"))


@auth_bp.route("/invite/<token>", methods=["GET", "POST"])
def accept_invite(token: str):
    if not looks_like_token(token):
        return _notice(
            "This invite link does not work",
            f"Check that you copied the whole link, or ask {_admin_email()} for a new one.",
        ), 404

    invite = invite_service.find_by_token(token)
    status = invite_service.status_of(invite)

    if status == invite_service.UNKNOWN:
        return _notice(
            "This invite link does not work",
            f"Check that you copied the whole link, or ask {_admin_email()} for a new one.",
        ), 404

    if status == invite_service.REVOKED:
        return _notice(
            "This invite was cancelled",
            f"Ask {_admin_email()} for a fresh invite.",
        ), 410

    if status == invite_service.EXPIRED:
        return _notice(
            "This invite has expired",
            f"Invites last {current_app.config['INVITE_TTL_DAYS']} days. "
            f"Ask {_admin_email()} for a new one.",
        ), 410

    if status == invite_service.USED:
        return _notice(
            "This invite has already been used",
            "If that was you, sign in instead.",
            link=url_for("auth.login", email=invite.email),
            email=invite.email,
        )

    # A different account is signed in: never swap identities silently.
    if current_user.is_authenticated and current_user.email != invite.email:
        return render_template(
            "auth/invite_switch.html",
            invite=invite,
            form=SwitchAccountForm(),
            current=current_user,
        )

    form = AcceptInviteForm(timezone_choices=current_app.config["TIMEZONE_CHOICES"])
    if request.method == "GET":
        form.timezone.data = "Europe/London"

    if form.validate_on_submit():
        problems = passwords.validate_password(
            form.password.data or "",
            email=invite.email,
            display_name=form.display_name.data or "",
        )
        if problems:
            for problem in problems:
                form.password.errors.append(problem)
        else:
            session.clear()
            logout_user()

            user = User(
                email=invite.email,
                display_name=form.display_name.data.strip(),
                timezone=form.timezone.data,
                role="member",
            )
            user.set_password(form.password.data)
            db.session.add(user)
            db.session.flush()

            if not invite_service.claim(invite, user.id):
                db.session.rollback()
                flash(
                    "That invite was just used in another window. Sign in instead.",
                    "info",
                )
                return redirect(url_for("auth.login", email=invite.email))

            db.session.commit()
            _sign_in(user)
            flash(f"You're in, {user.display_name}. Add your first flight.", "success")
            return redirect(url_for("main.index"))

    return render_template("auth/invite.html", form=form, invite=invite)


@auth_bp.post("/invite/<token>/switch")
def switch_account(token: str):
    """Sign out the current user so the invite form can be shown."""
    form = SwitchAccountForm()
    if form.validate_on_submit():
        session.clear()
        logout_user()
    return redirect(url_for("auth.accept_invite", token=token))


@auth_bp.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    form = ForgotPasswordForm()

    if form.validate_on_submit():
        email = form.email.data.strip().lower()
        user = db.session.scalar(db.select(User).where(User.email == email))

        if user is not None and user.is_active:
            passwords.request_reset(user, requested_ip=request.remote_addr)
            db.session.commit()

        # Same response either way. Until M6 ships the mailer, an admin prints
        # the link with `flask reset-link EMAIL`.
        flash(
            "If that address has an account, a reset link is waiting to be sent to you.",
            "info",
        )
        return redirect(url_for("auth.login"))

    return render_template("auth/forgot_password.html", form=form)


@auth_bp.route("/reset-password/<token>", methods=["GET", "POST"])
def reset_password(token: str):
    if not looks_like_token(token):
        return _notice(
            "This reset link does not work",
            f"Ask {_admin_email()} for a new one.",
        ), 404

    reset = passwords.find_reset(token)
    if reset is None:
        return _notice(
            "This reset link does not work",
            f"Ask {_admin_email()} for a new one.",
        ), 404

    if not reset.is_usable:
        return _notice(
            "This reset link has expired",
            f"Reset links last {current_app.config['RESET_TTL_MINUTES']} minutes and work once.",
            link=url_for("auth.forgot_password"),
        ), 410

    form = ResetPasswordForm()
    if form.validate_on_submit():
        user = reset.user
        problems = passwords.validate_password(
            form.password.data or "", email=user.email, display_name=user.display_name
        )
        if problems:
            for problem in problems:
                form.password.errors.append(problem)
        else:
            user.set_password(form.password.data)
            user.session_version += 1
            reset.used_at = utcnow()
            passwords.invalidate_all_resets(user)
            db.session.commit()

            _sign_in(user)
            flash("Password changed. You're signed in.", "success")
            return redirect(url_for("main.index"))

    return render_template("auth/reset_password.html", form=form)


def build_invite_link(raw: str) -> str:
    """The public URL for an invite, always from config rather than the request."""
    return token_url(current_app.config["BASE_URL"], "/invite/", raw)


def build_reset_link(raw: str) -> str:
    return token_url(current_app.config["BASE_URL"], "/reset-password/", raw)

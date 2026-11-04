"""Invite lifecycle: create, look up, evaluate, claim, revoke."""

from __future__ import annotations

from datetime import timedelta

from flask import current_app
from sqlalchemy import update

from ..extensions import db
from ..models import Invite, utcnow
from .tokens import hash_token, new_token

# Outcomes of opening an invite link, in evaluation order.
OK = "ok"
UNKNOWN = "unknown"
REVOKED = "revoked"
EXPIRED = "expired"
USED = "used"


def create_invite(
    email: str, *, created_by_id: int | None = None, ttl_days: int | None = None
) -> tuple[Invite, str]:
    """Create a pending invite and return it with its raw (unhashed) token."""
    raw = new_token()
    days = ttl_days or current_app.config["INVITE_TTL_DAYS"]
    invite = Invite(
        email=email.strip().lower(),
        token_hash=hash_token(raw),
        created_by_id=created_by_id,
        expires_at=utcnow() + timedelta(days=days),
    )
    db.session.add(invite)
    return invite, raw


def find_by_token(raw: str) -> Invite | None:
    return db.session.scalar(db.select(Invite).where(Invite.token_hash == hash_token(raw)))


def status_of(invite: Invite | None) -> str:
    """Classify an invite for the accept page.

    Order matters: a revoked invite must never render a form, and an expired
    one must not be reported as "already used".
    """
    if invite is None:
        return UNKNOWN
    if invite.revoked_at is not None:
        return REVOKED
    if invite.used_at is not None:
        return USED
    if invite.expires_at <= utcnow():
        return EXPIRED
    return OK


def claim(invite: Invite, user_id: int) -> bool:
    """Mark the invite used, atomically.

    Returns False when someone else got there first (double submit, two tabs,
    a forwarded link). The caller rolls the whole transaction back in that case,
    so a failed claim never leaves a half-created account behind.
    """
    result = db.session.execute(
        update(Invite)
        .where(
            Invite.id == invite.id,
            Invite.used_at.is_(None),
            Invite.revoked_at.is_(None),
        )
        .values(used_at=utcnow(), accepted_user_id=user_id)
    )
    return result.rowcount == 1


def revoke(invite: Invite) -> None:
    if invite.revoked_at is None:
        invite.revoked_at = utcnow()


def revoke_all_pending(email: str | None = None) -> int:
    """Revoke pending invites, optionally only those for one address."""
    query = db.select(Invite).where(Invite.used_at.is_(None), Invite.revoked_at.is_(None))
    if email:
        query = query.where(Invite.email == email.strip().lower())
    invites = list(db.session.scalars(query))
    now = utcnow()
    for invite in invites:
        invite.revoked_at = now
    return len(invites)


def pending_for(email: str) -> Invite | None:
    return db.session.scalar(
        db.select(Invite).where(
            Invite.email == email.strip().lower(),
            Invite.used_at.is_(None),
            Invite.revoked_at.is_(None),
        )
    )

"""Token generation and hashing.

Invite and password-reset tokens are 32 random bytes encoded as URL-safe text
(43 characters). Only the SHA-256 hash is stored, so a database dump does not
contain working links. The URL-safe alphabet means no ``+`` or ``/``, which
survives being line-wrapped by a chat client or mail app.
"""

from __future__ import annotations

import hashlib
import re
import secrets

TOKEN_BYTES = 32
TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9_-]{43}$")


def new_token() -> str:
    return secrets.token_urlsafe(TOKEN_BYTES)


def hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def looks_like_token(raw: str | None) -> bool:
    """Cheap shape check before touching the database."""
    return bool(raw and TOKEN_PATTERN.match(raw))


def token_url(base_url: str, path: str, raw: str) -> str:
    return f"{base_url.rstrip('/')}{path}{raw}"

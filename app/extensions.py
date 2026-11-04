"""Shared extension instances.

Kept in one module so the app factory, the CLI and the scheduled jobs all talk
to the same objects, and so models can import ``db`` without a circular import.
"""

from __future__ import annotations

from flask_login import LoginManager
from flask_sqlalchemy import SQLAlchemy
from flask_wtf import CSRFProtect
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Declarative base for all models (added in M1)."""


db = SQLAlchemy(model_class=Base)
csrf = CSRFProtect()

login_manager = LoginManager()
login_manager.login_view = "auth.login"
login_manager.login_message = "Please sign in to continue."
login_manager.login_message_category = "info"
# "basic" rather than "strong": sessions are stateless cookies served by three
# separate web workers, and "strong" ties the session to the client IP, which
# logs people out when their phone changes network.
login_manager.session_protection = "basic"


@login_manager.user_loader
def _load_user(user_id: str):
    """Placeholder until the User model arrives in M2.

    Returning None means "no signed-in user", which is correct while there are
    no accounts; Flask-Login calls this on every template render.
    """
    return None

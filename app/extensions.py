"""Shared extension instances.

Kept in one module so the app factory, the CLI and the scheduled jobs all talk
to the same objects, and so models can import ``db`` without a circular import.
"""

from __future__ import annotations

from flask_login import LoginManager
from flask_sqlalchemy import SQLAlchemy
from flask_wtf import CSRFProtect
from sqlalchemy import MetaData, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase

# Deterministic constraint names keep migrations readable and make indexes and
# constraints droppable by name, which MySQL requires.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Declarative base for all models."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)


db = SQLAlchemy(model_class=Base)
csrf = CSRFProtect()


@event.listens_for(Engine, "connect")
def _enable_sqlite_foreign_keys(dbapi_connection, connection_record) -> None:
    """SQLite ignores foreign keys unless asked; MySQL enforces them already.

    Without this, ``ON DELETE CASCADE`` is untested locally and the cascade
    tests would pass on SQLite while proving nothing.
    """
    module = type(dbapi_connection).__module__
    if module == "sqlite3" or module.startswith("sqlite3."):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


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
    """Load the signed-in user, or None.

    Deactivated accounts resolve to None, so disabling a user logs them out on
    their next request as well as blocking new sign-ins.
    """
    from .models import User

    try:
        user = db.session.get(User, int(user_id))
    except (TypeError, ValueError):
        return None
    if user is None or not user.is_active:
        return None
    return user

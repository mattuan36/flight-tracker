"""Configuration.

Everything is read from the environment (or a local ``.env`` file) at call time
rather than at import time, so tests can build an app with any environment they
like and so the same module works for the web app, the CLI and the scheduled
price checker.

On PythonAnywhere the WSGI file does not share its environment with scheduled
tasks, so the ``.env`` file is the single source of truth for both.
"""

from __future__ import annotations

import os
from datetime import timedelta
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
INSTANCE_DIR = PROJECT_ROOT / "instance"

# Load .env once, without overriding variables already set by the shell.
load_dotenv(PROJECT_ROOT / ".env", override=False)

DEFAULT_BASE_URL = "http://localhost:5000"


def _bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def normalize_database_url(url: str) -> str:
    """Turn the URL PythonAnywhere gives you into a SQLAlchemy URL.

    PythonAnywhere hands out ``mysql://user:pass@host/db``; SQLAlchemy needs a
    driver, and PyMySQL is the one we install.
    """
    if url.startswith("mysql://"):
        return "mysql+pymysql://" + url[len("mysql://") :]
    if url.startswith("mysql+mysqldb://"):
        return "mysql+pymysql://" + url[len("mysql+mysqldb://") :]
    return url


def _dev_database_uri() -> str:
    return f"sqlite:///{(INSTANCE_DIR / 'dev.sqlite3').as_posix()}"


def base_config() -> dict:
    """Settings shared by every environment."""
    secret_key = os.environ.get("SECRET_KEY") or None
    database_url = normalize_database_url(os.environ.get("DATABASE_URL", ""))

    return {
        "APP_NAME": os.environ.get("APP_NAME", "Flight Tracker"),
        "ADMIN_EMAIL": os.environ.get("ADMIN_EMAIL", ""),
        "BASE_URL": (os.environ.get("BASE_URL") or DEFAULT_BASE_URL).rstrip("/"),
        # The only price source wired up until M4b picks a real vendor.
        "PRICE_PROVIDER": os.environ.get("PRICE_PROVIDER", "mock"),
        "SECRET_KEY": secret_key,
        "DATABASE_URL": database_url,
        "SQLALCHEMY_DATABASE_URI": database_url or _dev_database_uri(),
        "SQLALCHEMY_TRACK_MODIFICATIONS": False,
        "SQLALCHEMY_ENGINE_OPTIONS": {"pool_pre_ping": True},
        "LOG_LEVEL": os.environ.get("LOG_LEVEL", "INFO").upper(),
        # Sessions: a private tool used occasionally, so long-lived and httpOnly.
        "PERMANENT_SESSION_LIFETIME": timedelta(days=30),
        "REMEMBER_COOKIE_DURATION": timedelta(days=30),
        "SESSION_COOKIE_HTTPONLY": True,
        "SESSION_COOKIE_SAMESITE": "Lax",
        "SESSION_COOKIE_SECURE": False,
        "REMEMBER_COOKIE_HTTPONLY": True,
        "REMEMBER_COOKIE_SAMESITE": "Lax",
        "REMEMBER_COOKIE_SECURE": False,
        # An invite form should not expire while a friend is reading the email
        # and deciding; the token in the URL is the real gate.
        "WTF_CSRF_TIME_LIMIT": None,
    }


def dev_config() -> dict:
    config = base_config()
    config.update(
        {
            "ENV_NAME": "dev",
            "DEBUG": True,
            "SECRET_KEY": config["SECRET_KEY"] or "dev-only-not-a-real-secret",
        }
    )
    return config


def test_config() -> dict:
    from sqlalchemy.pool import StaticPool

    config = base_config()
    config.update(
        {
            "ENV_NAME": "test",
            "TESTING": True,
            "SECRET_KEY": "test-secret",
            "SQLALCHEMY_DATABASE_URI": "sqlite://",
            "SQLALCHEMY_ENGINE_OPTIONS": {
                "poolclass": StaticPool,
                "connect_args": {"check_same_thread": False},
            },
            "WTF_CSRF_ENABLED": False,
            "LOG_LEVEL": "WARNING",
        }
    )
    return config


def prod_config() -> dict:
    config = base_config()
    config.update(
        {
            "ENV_NAME": "prod",
            "DEBUG": False,
            "SESSION_COOKIE_SECURE": True,
            "REMEMBER_COOKIE_SECURE": True,
        }
    )
    return config


CONFIGS = {"dev": dev_config, "test": test_config, "prod": prod_config}


def get_config(name: str) -> dict:
    """Build the settings dict for an already-resolved environment name."""
    return CONFIGS[name]()


def resolve_env_name(name: str | None = None) -> str:
    raw = name or os.environ.get("APP_ENV") or "dev"
    name = raw.strip().lower()
    if name in {"production", "live"}:
        name = "prod"
    if name not in CONFIGS:
        raise RuntimeError(f"Unknown APP_ENV {name!r}; expected one of {sorted(CONFIGS)}")
    return name


def validate(app, env_name: str) -> None:
    """Fail loudly at startup rather than at the first request."""
    if env_name != "prod":
        return

    missing = [
        key for key in ("SECRET_KEY", "DATABASE_URL") if not (app.config.get(key) or "").strip()
    ]
    if missing:
        raise RuntimeError("Production config is missing required settings: " + ", ".join(missing))

    if app.config["BASE_URL"].startswith(DEFAULT_BASE_URL):
        raise RuntimeError(
            "BASE_URL must be the public https URL in production; invite links are built from it."
        )

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
from urllib.parse import urlsplit

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
INSTANCE_DIR = PROJECT_ROOT / "instance"

# Load .env once, without overriding variables already set by the shell.
load_dotenv(PROJECT_ROOT / ".env", override=False)

DEFAULT_BASE_URL = "http://localhost:5000"

# Curated rather than all 600 zoneinfo names: a short list is legible in a
# form, and validation still runs through ZoneInfo so a typo cannot be stored.
TIMEZONE_CHOICES: list[tuple[str, str]] = [
    ("UTC", "UTC"),
    ("Europe/London", "London"),
    ("Europe/Dublin", "Dublin"),
    ("Europe/Paris", "Paris"),
    ("Europe/Berlin", "Berlin"),
    ("Europe/Madrid", "Madrid"),
    ("Europe/Rome", "Rome"),
    ("Europe/Amsterdam", "Amsterdam"),
    ("Europe/Lisbon", "Lisbon"),
    ("Europe/Warsaw", "Warsaw"),
    ("America/New_York", "New York"),
    ("America/Chicago", "Chicago"),
    ("America/Denver", "Denver"),
    ("America/Los_Angeles", "Los Angeles"),
    ("America/Toronto", "Toronto"),
    ("America/Sao_Paulo", "Sao Paulo"),
    ("Asia/Dubai", "Dubai"),
    ("Asia/Kolkata", "Kolkata"),
    ("Asia/Singapore", "Singapore"),
    ("Asia/Tokyo", "Tokyo"),
    ("Australia/Perth", "Perth"),
    ("Australia/Sydney", "Sydney"),
    ("Pacific/Auckland", "Auckland"),
]


def _bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _normalize_path(value: str | None, default: str = "/") -> str:
    """Return a leading-slash path without a trailing slash (except root)."""
    path = (value or "").strip() or default
    if not path.startswith("/"):
        path = "/" + path
    return path.rstrip("/") or "/"


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
    admin_email = os.environ.get("ADMIN_EMAIL", "")
    application_root = _normalize_path(os.environ.get("APPLICATION_ROOT"))

    return {
        "APP_NAME": os.environ.get("APP_NAME", "Flight Tracker"),
        "ADMIN_EMAIL": admin_email,
        "BASE_URL": (os.environ.get("BASE_URL") or DEFAULT_BASE_URL).rstrip("/"),
        # The app is mounted at a path on PythonAnywhere, so its cookie scope
        # and public URL prefix must match. Both default to local root access.
        "APPLICATION_ROOT": application_root,
        "BACK_TO_PROJECTS_URL": os.environ.get("BACK_TO_PROJECTS_URL") or "/",
        "BACK_TO_PROJECTS_LABEL": os.environ.get("BACK_TO_PROJECTS_LABEL") or "All projects",
        # ``mock`` is the safe default. Set ``serpapi`` for live checks; the
        # budget guard is applied in the check service, not in a web request.
        "PRICE_PROVIDER": os.environ.get("PRICE_PROVIDER", "mock"),
        # SerpAPI is priced in USD. The key is only used by the CLI/scheduler,
        # never by a web request. Airline scope lives on each tracker.
        "SERPAPI_KEY": os.environ.get("SERPAPI_KEY", ""),
        "SERPAPI_BASE_URL": os.environ.get("SERPAPI_BASE_URL", "https://serpapi.com/search.json"),
        "SERPAPI_GL": os.environ.get("SERPAPI_GL", "us"),
        "SERPAPI_HL": os.environ.get("SERPAPI_HL", "en"),
        "SERPAPI_MONTHLY_CAP": int(os.environ.get("SERPAPI_MONTHLY_CAP", "250")),
        "SERPAPI_TIMEOUT_SECONDS": int(os.environ.get("SERPAPI_TIMEOUT_SECONDS", "20")),
        # The hourly task only checks flights whose interval is due. Daily is
        # the default, so a flight is checked once per day, not at a fixed time.
        "CHECK_TASK_MINUTE": int(os.environ.get("CHECK_TASK_MINUTE", "0")),
        "CHECK_MAX_CALLS_PER_RUN": int(os.environ.get("CHECK_MAX_CALLS_PER_RUN", "20")),
        # Mail: ``console`` is the local/test default. Production must choose
        # ``smtp`` and provide a working relay; config validation enforces that.
        "MAIL_BACKEND": (os.environ.get("MAIL_BACKEND") or "console").strip().lower(),
        "MAIL_FROM": os.environ.get("MAIL_FROM") or admin_email or "flight-tracker@localhost",
        "SMTP_HOST": os.environ.get("SMTP_HOST", ""),
        "SMTP_PORT": int(os.environ.get("SMTP_PORT", "587")),
        "SMTP_USER": os.environ.get("SMTP_USER", ""),
        "SMTP_PASSWORD": os.environ.get("SMTP_PASSWORD", ""),
        "SMTP_USE_TLS": _bool("SMTP_USE_TLS", True),
        "SMTP_USE_SSL": _bool("SMTP_USE_SSL", False),
        "SMTP_TIMEOUT_SECONDS": int(os.environ.get("SMTP_TIMEOUT_SECONDS", "20")),
        "SECRET_KEY": secret_key,
        "DATABASE_URL": database_url,
        "SQLALCHEMY_DATABASE_URI": database_url or _dev_database_uri(),
        "SQLALCHEMY_TRACK_MODIFICATIONS": False,
        "SQLALCHEMY_ENGINE_OPTIONS": {"pool_pre_ping": True},
        "LOG_LEVEL": os.environ.get("LOG_LEVEL", "INFO").upper(),
        # Auth policy.
        "INVITE_TTL_DAYS": int(os.environ.get("INVITE_TTL_DAYS", "7")),
        "RESET_TTL_MINUTES": int(os.environ.get("RESET_TTL_MINUTES", "60")),
        "PASSWORD_MIN_LENGTH": 12,
        "PASSWORD_MAX_LENGTH": 128,
        "LOGIN_MAX_ATTEMPTS": int(os.environ.get("LOGIN_MAX_ATTEMPTS", "5")),
        "LOGIN_WINDOW_MINUTES": int(os.environ.get("LOGIN_WINDOW_MINUTES", "15")),
        "LOGIN_IP_MAX_ATTEMPTS": int(os.environ.get("LOGIN_IP_MAX_ATTEMPTS", "20")),
        "TIMEZONE_CHOICES": TIMEZONE_CHOICES,
        # Sessions: a private tool used occasionally, so long-lived and httpOnly.
        # The names and paths keep these cookies apart from the sibling
        # web-projects app when both are mounted under one hostname.
        "SESSION_COOKIE_NAME": os.environ.get("SESSION_COOKIE_NAME") or "flight_session",
        "SESSION_COOKIE_PATH": _normalize_path(
            os.environ.get("SESSION_COOKIE_PATH"), application_root
        ),
        "REMEMBER_COOKIE_NAME": os.environ.get("REMEMBER_COOKIE_NAME") or "flight_remember",
        "REMEMBER_COOKIE_PATH": _normalize_path(
            os.environ.get("REMEMBER_COOKIE_PATH"), application_root
        ),
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
        "WTF_CSRF_SSL_STRICT": False,
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
            "PRICE_PROVIDER": "mock",
            "SERPAPI_KEY": "",
            "MAIL_BACKEND": "console",
            "MAIL_FROM": "alerts@example.com",
            "SMTP_HOST": "",
            "SMTP_USER": "",
            "SMTP_PASSWORD": "",
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

    base_path = urlsplit(app.config["BASE_URL"]).path.rstrip("/") or "/"
    if base_path != app.config["APPLICATION_ROOT"]:
        raise RuntimeError(
            "BASE_URL must include the APPLICATION_ROOT path in production; "
            f"got {base_path!r} and {app.config['APPLICATION_ROOT']!r}."
        )

    backend = str(app.config.get("MAIL_BACKEND") or "").lower()
    if backend not in {"console", "smtp"}:
        raise RuntimeError("MAIL_BACKEND must be 'console' or 'smtp'")
    if backend == "console":
        raise RuntimeError(
            "MAIL_BACKEND=console in production would not deliver alerts; "
            "set MAIL_BACKEND=smtp and the SMTP_* settings."
        )
    mail_missing = [
        key for key in ("MAIL_FROM", "SMTP_HOST") if not str(app.config.get(key) or "").strip()
    ]
    if mail_missing:
        raise RuntimeError(
            "Production mail config is missing required settings: " + ", ".join(mail_missing)
        )

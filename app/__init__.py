"""Application factory."""

from __future__ import annotations

import logging
from pathlib import Path

from flask import Flask, request

from .config import INSTANCE_DIR, get_config, resolve_env_name, validate
from .extensions import csrf, db, login_manager

__all__ = ["create_app"]


def create_app(config_name: str | None = None) -> Flask:
    env_name = resolve_env_name(config_name)

    app_config = get_config(env_name)
    app = Flask(__name__, instance_relative_config=True)
    app.config.update(app_config)
    validate(app, env_name)

    _ensure_instance_dir(app)
    _configure_logging(app)

    db.init_app(app)
    login_manager.init_app(app)
    csrf.init_app(app)

    from . import models  # noqa: F401  (registers tables on Base.metadata)
    from .auth import auth_bp
    from .cli import register_cli
    from .main.routes import main_bp

    app.register_blueprint(main_bp)
    app.register_blueprint(auth_bp)
    register_cli(app)
    _security_headers(app)

    app.logger.debug("created %s app in %s mode", app.config["APP_NAME"], env_name)
    return app


def _ensure_instance_dir(app: Flask) -> None:
    """SQLite will not create the folder its file lives in."""
    if str(app.config["SQLALCHEMY_DATABASE_URI"]).startswith("sqlite:///"):
        Path(app.instance_path).mkdir(parents=True, exist_ok=True)
        Path(INSTANCE_DIR).mkdir(parents=True, exist_ok=True)


def _configure_logging(app: Flask) -> None:
    """Log to stdout so PythonAnywhere's web and task logs both capture it."""
    level = getattr(logging, str(app.config.get("LOG_LEVEL", "INFO")).upper(), logging.INFO)
    if not app.logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s"))
        app.logger.addHandler(handler)
    app.logger.setLevel(level)


def _security_headers(app: Flask) -> None:
    """Headers that cost nothing and close the obvious holes.

    The CSP is strict because the app ships no inline script or style; if that
    changes, this is the line that will tell you.
    """

    @app.after_request
    def apply(response):
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; img-src 'self' data:; style-src 'self'; "
            "form-action 'self'; frame-ancestors 'none'; base-uri 'self'",
        )
        if str(request.endpoint or "").startswith("auth."):
            # Tokens live in these URLs: keep them out of Referer headers and
            # out of browser caches.
            response.headers["Referrer-Policy"] = "no-referrer"
            response.headers["Cache-Control"] = "no-store"
        if app.config.get("ENV_NAME") == "prod":
            response.headers.setdefault(
                "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
            )
        return response

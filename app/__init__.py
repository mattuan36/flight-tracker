"""Application factory."""

from __future__ import annotations

import logging
from pathlib import Path

from flask import Flask

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

    from .cli import register_cli
    from .main.routes import main_bp

    app.register_blueprint(main_bp)
    register_cli(app)

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

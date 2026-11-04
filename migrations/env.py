"""Alembic environment.

The database URL comes from the app's own config (``DATABASE_URL``, or local
SQLite), so migrations run against exactly what the web app uses. ``APP_ENV``
picks the config, defaulting to ``dev``.
"""

# ruff: noqa: E402  -- the app imports below must follow the sys.path setup

from __future__ import annotations

import os
import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import app.models  # noqa: F401  (registers the tables on Base.metadata)
from app import create_app
from app.extensions import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

flask_app = create_app(os.environ.get("APP_ENV", "dev"))
database_url = flask_app.config["SQLALCHEMY_DATABASE_URI"]
# Alembic interpolates % in URLs, so escape them.
config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            # SQLite cannot ALTER most things; batch mode rewrites the table.
            render_as_batch=connection.dialect.name == "sqlite",
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

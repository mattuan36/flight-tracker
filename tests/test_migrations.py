"""The Alembic migration must build the schema the models expect."""

from __future__ import annotations

from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

from app.extensions import Base

PROJECT_ROOT = Path(__file__).resolve().parent.parent
EXPECTED_TABLES = {
    "alerts",
    "api_usage",
    "invites",
    "price_checks",
    "tracked_flights",
    "users",
}


def _alembic_config() -> Config:
    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(PROJECT_ROOT / "migrations"))
    return config


@pytest.fixture
def migrated_database(tmp_path, monkeypatch):
    database = tmp_path / "migrated.sqlite3"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database.as_posix()}")
    monkeypatch.setenv("APP_ENV", "dev")

    config = _alembic_config()
    command.upgrade(config, "head")
    return database


def test_upgrade_creates_every_table(migrated_database):
    engine = create_engine(f"sqlite:///{migrated_database.as_posix()}")

    assert set(inspect(engine).get_table_names()) >= EXPECTED_TABLES


def test_migration_matches_models(migrated_database):
    """Nothing in the models is missing a migration (same check as `alembic check`)."""
    import app.models  # noqa: F401  (registers tables)

    engine = create_engine(f"sqlite:///{migrated_database.as_posix()}")
    inspector = inspect(engine)

    assert set(Base.metadata.tables) == set(inspector.get_table_names()) - {"alembic_version"}


def test_downgrade_removes_everything(migrated_database):
    config = _alembic_config()
    command.downgrade(config, "base")

    engine = create_engine(f"sqlite:///{migrated_database.as_posix()}")
    remaining = set(inspect(engine).get_table_names())

    assert remaining <= {"alembic_version"}


def test_pending_key_is_a_generated_column(migrated_database):
    """MariaDB can index a stored generated column; it has no partial indexes."""
    engine = create_engine(f"sqlite:///{migrated_database.as_posix()}")
    columns = {column["name"]: column for column in inspect(engine).get_columns("invites")}

    assert columns["pending_key"].get("computed") is not None

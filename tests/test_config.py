from __future__ import annotations

import pytest

from app import create_app
from app.config import normalize_database_url, resolve_env_name


def test_env_name_aliases():
    assert resolve_env_name("production") == "prod"
    assert resolve_env_name("PROD") == "prod"
    assert resolve_env_name("dev") == "dev"


def test_unknown_env_name_rejected():
    with pytest.raises(RuntimeError, match="Unknown APP_ENV"):
        resolve_env_name("staging")


def test_mysql_url_gets_pymysql_driver():
    assert (
        normalize_database_url("mysql://user:pw@host.example.com/db")
        == "mysql+pymysql://user:pw@host.example.com/db"
    )
    assert normalize_database_url("sqlite:///x.db") == "sqlite:///x.db"


def test_prod_requires_secret_and_database(monkeypatch):
    monkeypatch.delenv("SECRET_KEY", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("BASE_URL", "https://flights.example.com")

    with pytest.raises(RuntimeError, match="SECRET_KEY"):
        create_app("prod")


def test_prod_rejects_local_base_url(monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "a" * 48)
    monkeypatch.setenv("DATABASE_URL", "mysql://user:pw@host.example.com/db")
    monkeypatch.setenv("BASE_URL", "http://localhost:5000")

    with pytest.raises(RuntimeError, match="BASE_URL"):
        create_app("prod")


def test_prod_accepts_complete_config(monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "a" * 48)
    monkeypatch.setenv("DATABASE_URL", "mysql://user:pw@host.example.com/db")
    monkeypatch.setenv("BASE_URL", "https://flights.example.com")

    app = create_app("prod")
    assert app.config["SQLALCHEMY_DATABASE_URI"].startswith("mysql+pymysql://")
    assert app.config["SESSION_COOKIE_SECURE"] is True
    assert app.config["DEBUG"] is False


def test_dev_defaults_to_mock_provider_and_sqlite(monkeypatch):
    monkeypatch.delenv("PRICE_PROVIDER", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)

    app = create_app("dev")
    assert app.config["PRICE_PROVIDER"] == "mock"
    assert app.config["SQLALCHEMY_DATABASE_URI"].startswith("sqlite:///")

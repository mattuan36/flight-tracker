"""Configuration and cookie isolation for mounting the app under a path."""

from __future__ import annotations

import pytest
from flask import Flask, session
from werkzeug.middleware.dispatcher import DispatcherMiddleware
from werkzeug.test import Client, TestResponse

from app import create_app


def _prod_env(monkeypatch) -> None:
    monkeypatch.setenv("SECRET_KEY", "a" * 48)
    monkeypatch.setenv("DATABASE_URL", "mysql://user:pw@host.example.com/db")
    monkeypatch.setenv("MAIL_BACKEND", "smtp")
    monkeypatch.setenv("MAIL_FROM", "alerts@flights.example.com")
    monkeypatch.setenv("SMTP_HOST", "smtp.example.com")


def test_mount_defaults_to_root_with_flight_cookies(monkeypatch):
    for key in (
        "APPLICATION_ROOT",
        "SESSION_COOKIE_NAME",
        "SESSION_COOKIE_PATH",
        "REMEMBER_COOKIE_NAME",
        "REMEMBER_COOKIE_PATH",
        "BACK_TO_PROJECTS_URL",
        "BACK_TO_PROJECTS_LABEL",
    ):
        monkeypatch.delenv(key, raising=False)

    app = create_app("test")

    assert app.config["APPLICATION_ROOT"] == "/"
    assert app.config["SESSION_COOKIE_NAME"] == "flight_session"
    assert app.config["SESSION_COOKIE_PATH"] == "/"
    assert app.config["REMEMBER_COOKIE_NAME"] == "flight_remember"
    assert app.config["REMEMBER_COOKIE_PATH"] == "/"
    assert app.config["BACK_TO_PROJECTS_URL"] == "/"
    assert app.config["BACK_TO_PROJECTS_LABEL"] == "All projects"


def test_mount_path_is_normalized_and_cookie_paths_follow_it(monkeypatch):
    monkeypatch.setenv("APPLICATION_ROOT", "flight/")
    monkeypatch.delenv("SESSION_COOKIE_PATH", raising=False)
    monkeypatch.delenv("REMEMBER_COOKIE_PATH", raising=False)

    app = create_app("test")

    assert app.config["APPLICATION_ROOT"] == "/flight"
    assert app.config["SESSION_COOKIE_PATH"] == "/flight"
    assert app.config["REMEMBER_COOKIE_PATH"] == "/flight"


def test_prod_requires_base_url_to_match_application_root(monkeypatch):
    _prod_env(monkeypatch)
    monkeypatch.setenv("BASE_URL", "https://flights.example.com")
    monkeypatch.setenv("APPLICATION_ROOT", "/flight")

    with pytest.raises(RuntimeError, match="APPLICATION_ROOT"):
        create_app("prod")


def test_prod_accepts_a_mounted_config(monkeypatch):
    _prod_env(monkeypatch)
    monkeypatch.setenv("BASE_URL", "https://flights.example.com/flight")
    monkeypatch.setenv("APPLICATION_ROOT", "/flight")

    app = create_app("prod")

    assert app.config["APPLICATION_ROOT"] == "/flight"
    assert app.config["SESSION_COOKIE_PATH"] == "/flight"
    assert app.config["REMEMBER_COOKIE_PATH"] == "/flight"


def test_mount_prefixes_urls_and_keeps_the_host_session_apart(app):
    app.config.update(
        APPLICATION_ROOT="/flight",
        BASE_URL="https://flights.example.com/flight",
        SESSION_COOKIE_NAME="flight_session",
        SESSION_COOKIE_PATH="/flight",
        REMEMBER_COOKIE_NAME="flight_remember",
        REMEMBER_COOKIE_PATH="/flight",
    )

    @app.get("/_mount_set")
    def _mount_set():
        session["site"] = "flight-tracker"
        return "set"

    @app.get("/_mount_read")
    def _mount_read():
        return session.get("site", "missing")

    host = Flask("web-projects")

    @host.get("/")
    def host_index():
        session.setdefault("site", "web-projects")
        return session["site"]

    host.secret_key = "host-secret"
    host.config.update(SESSION_COOKIE_NAME="session", SESSION_COOKIE_PATH="/")

    mounted = DispatcherMiddleware(host.wsgi_app, {"/flight": app.wsgi_app})
    client = Client(mounted, TestResponse)

    bare = client.get("/flight")
    assert bare.status_code == 308
    assert bare.headers["Location"].endswith("/flight/")

    assert client.get("/flight/_mount_set").text == "set"
    assert client.get("/").text == "web-projects"
    assert client.get("/flight/_mount_read").text == "flight-tracker"
    assert client.get("/").text == "web-projects"

    login = client.get("/flight/login")
    assert login.status_code == 200
    assert b'href="/flight/static/app.css"' in login.data
    assert b'action="/flight/login"' in login.data
    assert b'<a href="/">All projects</a>' in login.data

    assert client.get_cookie("session", path="/") is not None
    assert client.get_cookie("flight_session", path="/flight") is not None

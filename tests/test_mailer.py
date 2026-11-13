"""Mailer transports and rendered reset mail."""

from __future__ import annotations

import smtplib

import pytest

from app.services import mailer


@pytest.fixture(autouse=True)
def _app_context(app):
    return app


def test_console_backend_prints_the_message(app, capsys):
    app.config["MAIL_BACKEND"] = "console"
    app.config["MAIL_FROM"] = "alerts@example.com"

    mailer.send_email(
        to="friend@example.com",
        subject="A test",
        text_body="Hello from the console transporter.",
    )

    output = capsys.readouterr().out
    assert "email (console transport)" in output
    assert "To: friend@example.com" in output
    assert "Subject: A test" in output
    assert "Hello from the console transporter." in output


def test_unknown_backend_is_a_clear_error(app):
    app.config["MAIL_BACKEND"] = "carrier-pigeon"

    with pytest.raises(mailer.MailError, match="MAIL_BACKEND"):
        mailer.send_email(to="friend@example.com", subject="x", text_body="x")


def test_smtp_backend_uses_starttls_and_logs_in(app, monkeypatch):
    events: list[tuple] = []

    class FakeSMTP:
        def __init__(self, host, port, timeout, context=None):
            events.append(("connect", host, port, timeout))

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            events.append(("quit",))

        def starttls(self, context=None):
            events.append(("starttls", context is not None))

        def ehlo(self):
            events.append(("ehlo",))

        def login(self, user, password):
            events.append(("login", user, password))

        def send_message(self, message):
            events.append(("send", message["To"], message["Subject"]))

    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)
    app.config.update(
        MAIL_BACKEND="smtp",
        MAIL_FROM="alerts@example.com",
        SMTP_HOST="smtp.example.com",
        SMTP_PORT=587,
        SMTP_USE_TLS=True,
        SMTP_USE_SSL=False,
        SMTP_USER="mailer",
        SMTP_PASSWORD="secret",
    )

    mailer.send_email(to="friend@example.com", subject="Hello", text_body="Body")

    assert ("connect", "smtp.example.com", 587, 20.0) in events
    assert ("starttls", True) in events
    assert ("login", "mailer", "secret") in events
    assert ("send", "friend@example.com", "Hello") in events
    assert events[-1] == ("quit",)


def test_smtp_ssl_uses_the_ssl_constructor(app, monkeypatch):
    events: list[tuple] = []

    class FakeSMTPSSL:
        def __init__(self, host, port, timeout, context=None):
            events.append(("ssl-connect", host, port))

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            pass

        def login(self, user, password):
            events.append(("login", user))

        def send_message(self, message):
            events.append(("send", message["To"]))

    monkeypatch.setattr(smtplib, "SMTP_SSL", FakeSMTPSSL)
    app.config.update(
        MAIL_BACKEND="smtp",
        MAIL_FROM="alerts@example.com",
        SMTP_HOST="smtp.example.com",
        SMTP_PORT=465,
        SMTP_USE_SSL=True,
        SMTP_USER="mailer",
        SMTP_PASSWORD="secret",
    )

    mailer.send_email(to="friend@example.com", subject="Hello", text_body="Body")

    assert events == [
        ("ssl-connect", "smtp.example.com", 465),
        ("login", "mailer"),
        ("send", "friend@example.com"),
    ]


def test_smtp_errors_are_wrapped(app, monkeypatch):
    class BrokenSMTP:
        def __init__(self, *args, **kwargs):
            raise OSError("connection refused")

    monkeypatch.setattr(smtplib, "SMTP", BrokenSMTP)
    app.config.update(
        MAIL_BACKEND="smtp",
        MAIL_FROM="alerts@example.com",
        SMTP_HOST="smtp.example.com",
    )

    with pytest.raises(mailer.MailError, match="SMTP delivery failed"):
        mailer.send_email(to="friend@example.com", subject="x", text_body="x")


def test_password_reset_renders_both_bodies(app, monkeypatch):
    sent: list[dict] = []
    monkeypatch.setattr(mailer, "send_email", lambda **kwargs: sent.append(kwargs))

    mailer.send_password_reset(
        to="friend@example.com",
        reset_url="https://flights.example.com/reset-password/token",
        expires_minutes=60,
    )

    assert sent[0]["to"] == "friend@example.com"
    assert sent[0]["subject"] == "Reset your Flight Tracker password"
    assert "https://flights.example.com/reset-password/token" in sent[0]["text_body"]
    assert "60 minutes" in sent[0]["text_body"]
    assert "Choose a new password" in sent[0]["html_body"]

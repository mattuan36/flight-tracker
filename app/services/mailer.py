"""Outgoing mail.

Two transports keep local development honest and production simple:

* ``console`` prints the complete message to stdout, which is what both the
  Flask CLI and PythonAnywhere's task log capture. It is the default so a
  missing mail setup can never spend money or leak a token to a real address.
* ``smtp`` speaks to a normal SMTP relay using STARTTLS (port 587) or implicit
  TLS (port 465). Credentials are optional because some relays authenticate by
  network.

Callers only see :func:`send_email`; transport and template details stay here.
"""

from __future__ import annotations

import smtplib
import ssl
from email.message import EmailMessage

from flask import current_app, render_template


class MailError(RuntimeError):
    """Mail could not be built or delivered; the caller decides whether to retry."""


def send_email(
    *,
    to: str,
    subject: str,
    text_body: str,
    html_body: str | None = None,
) -> None:
    """Build and send one message, or raise :class:`MailError`."""
    recipient = (to or "").strip()
    if not recipient:
        raise MailError("recipient address is empty")

    message = EmailMessage()
    message["From"] = str(current_app.config.get("MAIL_FROM") or "")
    message["To"] = recipient
    message["Subject"] = subject
    message.set_content(text_body)
    if html_body:
        message.add_alternative(html_body, subtype="html")

    backend = str(current_app.config.get("MAIL_BACKEND") or "console").strip().lower()
    if backend == "console":
        _send_console(message)
    elif backend == "smtp":
        _send_smtp(message)
    else:
        raise MailError(f"unknown MAIL_BACKEND {backend!r}; expected 'console' or 'smtp'")


def send_password_reset(*, to: str, reset_url: str, expires_minutes: int) -> None:
    """Send the one-time reset link through the configured transport."""
    app_name = current_app.config["APP_NAME"]
    context = {
        "app_name": app_name,
        "reset_url": reset_url,
        "expires_minutes": expires_minutes,
        "admin_email": current_app.config.get("ADMIN_EMAIL") or "",
    }
    send_email(
        to=to,
        subject=f"Reset your {app_name} password",
        text_body=render_template("email/password_reset.txt", **context),
        html_body=render_template("email/password_reset.html", **context),
    )


def _send_console(message: EmailMessage) -> None:
    body = message.get_body(preferencelist=("plain",))
    text = body.get_content() if body is not None else ""
    print(
        "\n--- email (console transport) ---\n"
        f"From: {message['From']}\n"
        f"To: {message['To']}\n"
        f"Subject: {message['Subject']}\n\n"
        f"{text.rstrip()}\n"
        "--- end email ---"
    )


def _send_smtp(message: EmailMessage) -> None:
    host = str(current_app.config.get("SMTP_HOST") or "").strip()
    if not host:
        raise MailError("SMTP_HOST is not set")

    port = int(current_app.config.get("SMTP_PORT", 587))
    timeout = float(current_app.config.get("SMTP_TIMEOUT_SECONDS", 20))
    use_tls = bool(current_app.config.get("SMTP_USE_TLS", True))
    use_ssl = bool(current_app.config.get("SMTP_USE_SSL", False))
    user = str(current_app.config.get("SMTP_USER") or "").strip()
    password = str(current_app.config.get("SMTP_PASSWORD") or "")

    context = ssl.create_default_context()
    try:
        if use_ssl:
            server = smtplib.SMTP_SSL(host, port, timeout=timeout, context=context)
        else:
            server = smtplib.SMTP(host, port, timeout=timeout)
        with server:
            if use_tls and not use_ssl:
                server.starttls(context=context)
                server.ehlo()
            if user:
                server.login(user, password)
            server.send_message(message)
    except (OSError, smtplib.SMTPException) as exc:
        raise MailError(f"SMTP delivery failed: {exc}") from exc

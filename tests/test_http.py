"""The JSON GET helper's retry and error rules."""

from __future__ import annotations

import pytest
import requests

from app.services.http import HttpError, get_json


class FakeResponse:
    def __init__(self, status_code: int, payload=None, invalid_json: bool = False) -> None:
        self.status_code = status_code
        self.payload = payload
        self.invalid_json = invalid_json

    def json(self):
        if self.invalid_json:
            raise ValueError("not JSON")
        return self.payload


def test_successful_json_is_returned(monkeypatch):
    calls = []

    def fake_get(url, params, timeout):
        calls.append((url, params, timeout))
        return FakeResponse(200, {"ok": True})

    monkeypatch.setattr("app.services.http.requests.get", fake_get)

    assert get_json("https://example.test", {"api_key": "secret"}, timeout=3) == {"ok": True}
    assert len(calls) == 1
    assert calls[0][2] == 3


def test_server_error_is_retried_once(monkeypatch):
    responses = [FakeResponse(502), FakeResponse(200, {"ok": True})]

    monkeypatch.setattr("app.services.http.requests.get", lambda *args, **kwargs: responses.pop(0))

    assert get_json("https://example.test") == {"ok": True}


def test_client_error_is_not_retried(monkeypatch):
    calls = []

    def fake_get(*args, **kwargs):
        calls.append(1)
        return FakeResponse(429)

    monkeypatch.setattr("app.services.http.requests.get", fake_get)

    with pytest.raises(HttpError, match="HTTP 429") as excinfo:
        get_json("https://example.test", {"api_key": "do-not-leak"})

    assert len(calls) == 1
    assert "do-not-leak" not in str(excinfo.value)


def test_timeout_is_retried_once(monkeypatch):
    calls = []

    def fake_get(*args, **kwargs):
        calls.append(1)
        if len(calls) == 1:
            raise requests.Timeout("slow")
        return FakeResponse(200, {"ok": True})

    monkeypatch.setattr("app.services.http.requests.get", fake_get)

    assert get_json("https://example.test") == {"ok": True}
    assert len(calls) == 2


def test_persistent_timeout_is_an_error(monkeypatch):
    calls = []

    def fake_get(*args, **kwargs):
        calls.append(1)
        raise requests.Timeout("slow")

    monkeypatch.setattr("app.services.http.requests.get", fake_get)

    with pytest.raises(HttpError, match="timed out"):
        get_json("https://example.test")
    assert len(calls) == 2


def test_invalid_json_is_an_error(monkeypatch):
    monkeypatch.setattr(
        "app.services.http.requests.get",
        lambda *args, **kwargs: FakeResponse(200, invalid_json=True),
    )

    with pytest.raises(HttpError, match="invalid JSON"):
        get_json("https://example.test")

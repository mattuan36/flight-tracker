"""A tiny JSON GET helper for fare providers.

Errors never include the URL or query string: SerpAPI carries its API key in the
query, and an exception is the easiest place for a secret to end up in a log.
Retries are limited to timeouts, connection failures and 5xx responses; a 4xx
is a configuration or quota problem and retrying only spends another request.
"""

from __future__ import annotations

from typing import Any

import requests

DEFAULT_TIMEOUT_SECONDS = 20


class HttpError(Exception):
    """A provider request failed in a way the caller should record."""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


def get_json(
    url: str,
    params: dict[str, Any] | None = None,
    *,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    retries: int = 1,
) -> Any:
    """GET a JSON document, with one retry for transient failures."""
    attempts = max(1, retries + 1)
    last_error: HttpError | None = None

    for attempt in range(attempts):
        try:
            response = requests.get(url, params=params, timeout=timeout)
        except requests.Timeout as exc:
            last_error = HttpError("fare provider timed out")
            if attempt + 1 < attempts:
                continue
            raise last_error from exc
        except requests.ConnectionError as exc:
            last_error = HttpError("fare provider was unreachable")
            if attempt + 1 < attempts:
                continue
            raise last_error from exc
        except requests.RequestException as exc:
            raise HttpError("fare provider request failed") from exc

        if response.status_code >= 500:
            last_error = HttpError(
                f"fare provider returned HTTP {response.status_code}",
                status_code=response.status_code,
            )
            if attempt + 1 < attempts:
                continue
            raise last_error

        if response.status_code >= 400:
            raise HttpError(
                f"fare provider returned HTTP {response.status_code}",
                status_code=response.status_code,
            )

        try:
            return response.json()
        except ValueError as exc:
            raise HttpError("fare provider returned invalid JSON") from exc

    # The loop always returns or raises, but keeps type checkers honest.
    raise last_error or HttpError("fare provider request failed")

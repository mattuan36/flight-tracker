"""Hourly scheduled check.

PythonAnywhere's task command is:

    cd /home/<user>/flight-tracker && \
      /home/<user>/.virtualenvs/flight-tracker/bin/python -m jobs.check_prices

The task reads the same ``.env`` as the web app. There is no Flask request, so
this is the only place besides the CLI that is allowed to call a fare provider.
"""

from __future__ import annotations

import logging

from app import create_app
from app.services import checks
from app.services.prices import get_provider

log = logging.getLogger(__name__)


def run(app=None) -> checks.RunResults:
    """Run one scheduled pass, with retries first and due checks after."""
    app = app or create_app()
    with app.app_context():
        provider = get_provider()
        if provider.name == "serpapi" and not str(app.config.get("SERPAPI_KEY") or "").strip():
            raise RuntimeError("SERPAPI_KEY is not set; add it to .env")

        results = checks.run_checks(provider=provider)
        log.info(
            "Price run: %d checked, %d ok, %d not due, %d budget-skipped, "
            "%d alert(s), %d retry attempt(s) (%d sent, %d failed)",
            len(results),
            sum(1 for _flight, check in results if check.ok),
            len(results.not_due),
            len(results.skipped),
            len(results.alerts),
            results.retries["attempted"],
            results.retries["sent"],
            results.retries["failed"],
        )
        return results


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )
    run()


if __name__ == "__main__":
    main()

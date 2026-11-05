"""Fare providers behind a small adapter.

There is exactly one implementation, :class:`MockProvider`, and it is
deliberately fake. The real vendor is chosen in the M4b spike; the rest of the
app only knows the ``fetch(flight) -> Quote`` shape. Web requests never call a
provider — the scheduled check (M6) and ``flask check-prices`` do.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Protocol

from flask import current_app

from ..models import TrackedFlight, utcnow


class ProviderError(Exception):
    """A provider could not produce a quote. The message ends up in the check log."""


@dataclass(frozen=True)
class Quote:
    price_cents: int
    currency: str
    provider: str


class PriceProvider(Protocol):
    name: str

    def fetch(self, flight: TrackedFlight) -> Quote: ...


class MockProvider:
    """Deterministic-per-hour random walk, for development and demos.

    The first quote for a flight comes from a price band derived from the route
    and cabin; later quotes drift a few percent from the last one. Seeding on the
    current hour means asking twice in the same hour gives the same answer, which
    makes tests and demos reproducible without freezing the clock.
    """

    name = "mock"

    def fetch(self, flight: TrackedFlight) -> Quote:
        now = utcnow()
        rng = random.Random(
            f"mock:{flight.origin_iata}:{flight.dest_iata}:"
            f"{flight.depart_date.isoformat()}:{flight.cabin}:{flight.adults}:"
            f"{now:%Y%m%d%H}"
        )

        if flight.last_price_cents:
            price = round(flight.last_price_cents * rng.uniform(0.97, 1.04))
        else:
            price = round(self._base_fare(flight) * rng.uniform(0.92, 1.08))

        days_out = (flight.depart_date - now.date()).days
        if 0 <= days_out < 21:
            # Fares climb as departure approaches; a small, explainable nudge.
            price = round(price * (1 + (21 - days_out) * 0.015))

        return Quote(price_cents=max(price, 500), currency=flight.currency, provider=self.name)

    @staticmethod
    def _base_fare(flight: TrackedFlight) -> int:
        stable = random.Random(f"base:{flight.origin_iata}{flight.dest_iata}:{flight.cabin}")
        cabin_factor = {
            "economy": 1.0,
            "premium_economy": 1.9,
            "business": 3.4,
            "first": 5.2,
        }.get(flight.cabin, 1.0)
        if stable.random() < 0.45:
            base = stable.randint(38000, 95000)  # long haul
        else:
            base = stable.randint(5000, 22000)  # short haul
        return round(base * cabin_factor * flight.adults)


_PROVIDERS: dict[str, type[MockProvider]] = {"mock": MockProvider}


def get_provider(name: str | None = None) -> PriceProvider:
    key = (name or current_app.config["PRICE_PROVIDER"]).strip().lower()
    try:
        provider_class = _PROVIDERS[key]
    except KeyError:
        raise RuntimeError(
            f"unknown price provider {key!r}; set PRICE_PROVIDER to one of {sorted(_PROVIDERS)}"
        ) from None
    return provider_class()

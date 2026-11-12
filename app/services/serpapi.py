"""SerpAPI's Google Flights adapter.

The provider returns a party-total fare for the whole itinerary, so prices are
converted from whole dollars to integer cents but never multiplied by adults. A
round trip costs two searches: the first call returns a ``departure_token`` for
the outbound option, and the second call resolves the return options for that
token. Both calls count against the budget.

The tracker's ``airline_filter`` is a comma-separated list of IATA codes. When it
is empty the search deliberately omits ``include_airlines`` and covers every
carrier. The winning carrier comes from the chosen itinerary's ``flights`` legs,
never from the filter.
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Any

from flask import current_app

from ..labels import split_airline_filter
from ..models import TrackedFlight
from .http import HttpError, get_json
from .prices import NoMatchingFare, ProviderError, Quote

# SerpAPI's travel_class values.
TRAVEL_CLASS = {
    "economy": 1,
    "premium_economy": 2,
    "business": 3,
    "first": 4,
}

# SerpAPI stops: 0 any, 1 non-stop, 2 one stop or fewer.
STOPS_PARAM = {None: 0, 0: 1, 1: 2}
NO_RESULTS_TEXT = "Google Flights hasn't returned any results for this query."


def _price_cents(value: Any) -> int | None:
    """Turn a Google Flights whole-currency price into integer cents."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        amount = Decimal(str(value))
    elif isinstance(value, str):
        cleaned = re.sub(r"[^0-9.\-]", "", value)
        try:
            amount = Decimal(cleaned)
        except InvalidOperation:
            return None
    else:
        return None
    if amount <= 0:
        return None
    return int((amount * 100).quantize(Decimal("1")))


def _option_stops(option: dict[str, Any]) -> int:
    layovers = option.get("layovers")
    return len(layovers) if isinstance(layovers, list) else 0


def _options(response: dict[str, Any]) -> list[dict[str, Any]]:
    options = []
    for key in ("best_flights", "other_flights"):
        value = response.get(key)
        if isinstance(value, list):
            options.extend(item for item in value if isinstance(item, dict))
    return options


def _option_airlines(option: dict[str, Any]) -> list[str]:
    """The unique operating carriers named on an itinerary's legs."""
    legs = option.get("flights")
    if not isinstance(legs, list):
        return []
    names: list[str] = []
    for leg in legs:
        if not isinstance(leg, dict):
            continue
        value = leg.get("airline")
        if not isinstance(value, str):
            continue
        name = " ".join(value.split())
        if name and name not in names:
            names.append(name)
    return names


def _airline_label(names: list[str]) -> str | None:
    """A single display name, a short pair, or an honest mixed itinerary."""
    unique = list(dict.fromkeys(names))
    if not unique:
        return None
    if len(unique) == 1:
        return unique[0]
    if len(unique) == 2:
        return f"{unique[0]} / {unique[1]}"
    return "Multiple airlines"


def _clean_error(value: Any) -> str:
    message = " ".join(str(value).split())
    message = re.sub(r"(?i)(api_key=)[^&\s]+", r"\1***", message)
    return message[:240] or "SerpAPI returned an error"


class SerpApiProvider:
    name = "serpapi"

    def estimated_calls(self, flight: TrackedFlight) -> int:
        """A return costs two searches; a one-way costs one."""
        return 2 if flight.return_date else 1

    def fetch(self, flight: TrackedFlight) -> Quote:
        api_key = str(current_app.config.get("SERPAPI_KEY") or "").strip()
        if not api_key:
            raise ProviderError("SERPAPI_KEY is not set")

        params = self._params(flight, api_key)
        response = self._call(params)
        self._raise_for_error(response)
        currency = self._currency(response, flight)

        options = _options(response)
        if not options:
            raise NoMatchingFare("no flights matched the stops filter")

        if flight.return_date is None:
            candidate = self._cheapest(options, flight)
            if candidate is None:
                raise NoMatchingFare("no priced itinerary matched the stops filter")
            price_cents, option = candidate
            return Quote(
                price_cents=price_cents,
                currency=currency,
                provider=self.name,
                airline=_airline_label(_option_airlines(option)),
            )

        # The first call's option carries the token that resolves the return.
        priced_outbound = self._priced_options(options, flight)
        if not priced_outbound:
            raise NoMatchingFare("no priced outbound itinerary matched the stops filter")
        token_options = [
            (price, option) for price, option in priced_outbound if option.get("departure_token")
        ]
        if not token_options:
            raise ProviderError("SerpAPI did not return a departure token for the return")
        _, outbound_option = min(token_options, key=lambda item: item[0])

        return_params = params | {"departure_token": outbound_option["departure_token"]}
        return_response = self._call(return_params)
        self._raise_for_error(return_response)
        return_currency = self._currency(return_response, flight)
        if return_currency != currency:
            raise ProviderError("SerpAPI changed currency between outbound and return searches")

        return_options = _options(return_response)
        if not return_options:
            raise NoMatchingFare("no return flights matched the stops filter")
        return_candidate = self._cheapest(return_options, flight)
        if return_candidate is None:
            raise NoMatchingFare("no priced return itinerary matched the stops filter")
        price_cents, return_option = return_candidate
        # The first response only covers the outbound legs, so combine both
        # options to describe the whole trip.
        airlines = [
            *_option_airlines(outbound_option),
            *_option_airlines(return_option),
        ]
        return Quote(
            price_cents=price_cents,
            currency=return_currency,
            provider=self.name,
            airline=_airline_label(airlines),
        )

    def _params(self, flight: TrackedFlight, api_key: str) -> dict[str, Any]:
        try:
            travel_class = TRAVEL_CLASS[flight.cabin]
            stops = STOPS_PARAM[flight.max_stops]
        except KeyError as exc:
            raise ProviderError(f"unsupported flight option: {exc.args[0]}") from None

        params: dict[str, Any] = {
            "engine": "google_flights",
            "type": 1 if flight.return_date else 2,
            "departure_id": flight.origin_iata,
            "arrival_id": flight.dest_iata,
            "outbound_date": flight.depart_date.isoformat(),
            "currency": flight.currency.upper(),
            "hl": current_app.config.get("SERPAPI_HL", "en"),
            "gl": current_app.config.get("SERPAPI_GL", "us"),
            "stops": stops,
            "travel_class": travel_class,
            "adults": flight.adults,
            "sort_by": "2",
            "deep_search": "false",
            "api_key": api_key,
        }
        if flight.return_date is not None:
            params["return_date"] = flight.return_date.isoformat()
        airlines = split_airline_filter(flight.airline_filter)
        if airlines:
            params["include_airlines"] = ",".join(airlines)
        return params

    def _call(self, params: dict[str, Any]) -> dict[str, Any]:
        try:
            response = get_json(
                current_app.config["SERPAPI_BASE_URL"],
                params,
                timeout=float(current_app.config.get("SERPAPI_TIMEOUT_SECONDS", 20)),
            )
        except HttpError as exc:
            raise ProviderError(str(exc)) from exc
        if not isinstance(response, dict):
            raise ProviderError("SerpAPI returned an unexpected response")
        return response

    @staticmethod
    def _raise_for_error(response: dict[str, Any]) -> None:
        error = response.get("error")
        if not error:
            return
        message = _clean_error(error)
        if NO_RESULTS_TEXT in message or "no results" in message.lower():
            raise NoMatchingFare(message)
        raise ProviderError(message)

    @staticmethod
    def _currency(response: dict[str, Any], flight: TrackedFlight) -> str:
        search = response.get("search_parameters")
        currency = ""
        if isinstance(search, dict):
            currency = str(search.get("currency") or "")
        currency = (currency or str(response.get("currency") or "")).strip().upper()
        if currency and currency != flight.currency.upper():
            raise ProviderError(
                f"SerpAPI returned {currency} but this tracker is in {flight.currency}"
            )
        return currency or flight.currency.upper()

    @staticmethod
    def _priced_options(
        options: list[dict[str, Any]], flight: TrackedFlight
    ) -> list[tuple[int, dict[str, Any]]]:
        priced = []
        for option in options:
            price = _price_cents(option.get("price"))
            if price is None:
                continue
            if flight.max_stops is not None and _option_stops(option) > flight.max_stops:
                continue
            priced.append((price, option))
        return priced

    def _cheapest(
        self, options: list[dict[str, Any]], flight: TrackedFlight
    ) -> tuple[int, dict[str, Any]] | None:
        priced = self._priced_options(options, flight)
        return min(priced, key=lambda item: item[0]) if priced else None

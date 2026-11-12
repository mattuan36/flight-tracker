"""The SerpAPI adapter, with HTTP replaced by a fake JSON function."""

from __future__ import annotations

from datetime import date

import pytest

from app.models import TrackedFlight
from app.services.prices import NoMatchingFare, ProviderError, Quote
from app.services.serpapi import SerpApiProvider


@pytest.fixture(autouse=True)
def _app_config(app, monkeypatch):
    monkeypatch.setitem(app.config, "SERPAPI_KEY", "test-key")
    return app


def make_flight(**overrides) -> TrackedFlight:
    values = {
        "origin_iata": "PDX",
        "dest_iata": "OAK",
        "depart_date": date(2027, 1, 8),
        "cabin": "economy",
        "adults": 1,
        "currency": "USD",
        "max_stops": 0,
    }
    values.update(overrides)
    return TrackedFlight(**values)


def one_way(price: int = 110, airline: str | None = "Southwest", **overrides) -> dict:
    option = {"price": price, "layovers": []}
    if airline is not None:
        option["flights"] = [{"airline": airline}]
    option.update(overrides)
    return {"search_parameters": {"currency": "USD"}, "best_flights": [option]}


def fake_calls(monkeypatch, *responses, target="app.services.serpapi.get_json"):
    calls = []

    def fake(url, params, *, timeout):
        calls.append({"url": url, "params": dict(params), "timeout": timeout})
        return responses[len(calls) - 1]

    monkeypatch.setattr(target, fake)
    return calls


def test_one_way_maps_params_and_converts_dollars_to_cents(monkeypatch):
    calls = fake_calls(monkeypatch, one_way(110))
    flight = make_flight()

    quote = SerpApiProvider().fetch(flight)

    assert quote == Quote(
        price_cents=11_000,
        currency="USD",
        provider="serpapi",
        airline="Southwest",
    )
    params = calls[0]["params"]
    assert params["type"] == 2
    assert params["departure_id"] == "PDX"
    assert params["arrival_id"] == "OAK"
    assert "include_airlines" not in params
    assert params["gl"] == "us"
    assert params["hl"] == "en"
    assert params["currency"] == "USD"
    assert params["stops"] == 1
    assert params["travel_class"] == 1
    assert params["deep_search"] == "false"
    assert params["api_key"] == "test-key"
    assert "return_date" not in params


def test_airline_filter_is_sent_as_one_comma_separated_list(monkeypatch):
    calls = fake_calls(monkeypatch, one_way())
    flight = make_flight(airline_filter="AS,WN")

    SerpApiProvider().fetch(flight)

    assert calls[0]["params"]["include_airlines"] == "AS,WN"


def test_stops_mapping_is_a_ceiling(monkeypatch):
    calls = fake_calls(monkeypatch, one_way(), one_way())
    provider = SerpApiProvider()

    provider.fetch(make_flight(max_stops=1))
    provider.fetch(make_flight(max_stops=None))

    assert calls[0]["params"]["stops"] == 2
    assert calls[1]["params"]["stops"] == 0


def test_one_way_reports_each_operating_carrier(monkeypatch):
    response = {
        "search_parameters": {"currency": "USD"},
        "best_flights": [
            {
                "price": 110,
                "layovers": [],
                "flights": [{"airline": "Alaska"}, {"airline": "Alaska"}],
            }
        ],
    }
    fake_calls(monkeypatch, response)

    quote = SerpApiProvider().fetch(make_flight())

    assert quote.airline == "Alaska"


def test_mixed_carriers_are_named_in_order(monkeypatch):
    response = {
        "search_parameters": {"currency": "USD"},
        "best_flights": [
            {
                "price": 110,
                "layovers": [],
                "flights": [{"airline": "Alaska"}, {"airline": "American"}],
            }
        ],
    }
    fake_calls(monkeypatch, response)

    quote = SerpApiProvider().fetch(make_flight())

    assert quote.airline == "Alaska / American"


def test_more_than_two_carriers_are_called_multiple_airlines(monkeypatch):
    response = {
        "search_parameters": {"currency": "USD"},
        "best_flights": [
            {
                "price": 110,
                "layovers": [],
                "flights": [
                    {"airline": "Alaska"},
                    {"airline": "American"},
                    {"airline": "Delta"},
                ],
            }
        ],
    }
    fake_calls(monkeypatch, response)

    quote = SerpApiProvider().fetch(make_flight())

    assert quote.airline == "Multiple airlines"


def test_missing_carrier_data_is_not_invented(monkeypatch):
    fake_calls(monkeypatch, one_way(airline=None))

    quote = SerpApiProvider().fetch(make_flight())

    assert quote.airline is None


def test_return_trip_spends_two_searches_and_uses_the_token(monkeypatch):
    first = {
        "search_parameters": {"currency": "USD"},
        "best_flights": [
            {
                "price": 168,
                "layovers": [],
                "departure_token": "outbound-1",
                "flights": [{"airline": "Southwest"}],
            }
        ],
    }
    second = {
        "search_parameters": {"currency": "USD"},
        "best_flights": [{"price": 168, "layovers": [], "flights": [{"airline": "American"}]}],
    }
    calls = fake_calls(monkeypatch, first, second)
    flight = make_flight(return_date=date(2027, 1, 15))

    quote = SerpApiProvider().fetch(flight)

    assert quote.price_cents == 16_800
    assert quote.airline == "Southwest / American"
    assert len(calls) == 2
    assert calls[0]["params"]["type"] == 1
    assert calls[0]["params"]["return_date"] == "2027-01-15"
    assert calls[1]["params"]["departure_token"] == "outbound-1"


def test_party_total_is_not_multiplied_by_adults(monkeypatch):
    fake_calls(monkeypatch, one_way(168))
    flight = make_flight(adults=3)

    quote = SerpApiProvider().fetch(flight)

    assert quote.price_cents == 16_800


def test_cheapest_option_that_respects_the_stops_ceiling(monkeypatch):
    response = {
        "search_parameters": {"currency": "USD"},
        "best_flights": [
            {"price": 80, "layovers": [{}, {}]},
            {"price": 110, "layovers": []},
        ],
    }
    fake_calls(monkeypatch, response)

    quote = SerpApiProvider().fetch(make_flight(max_stops=0))

    assert quote.price_cents == 11_000


def test_any_stops_accepts_connections(monkeypatch):
    response = {
        "search_parameters": {"currency": "USD"},
        "other_flights": [{"price": 80, "layovers": [{}, {}]}],
    }
    fake_calls(monkeypatch, response)

    quote = SerpApiProvider().fetch(make_flight(max_stops=None))

    assert quote.price_cents == 8_000


def test_no_results_error_is_a_no_matching_fare(monkeypatch):
    fake_calls(monkeypatch, {"error": "Google Flights hasn't returned any results for this query."})

    with pytest.raises(NoMatchingFare):
        SerpApiProvider().fetch(make_flight())


def test_other_errors_are_provider_errors(monkeypatch):
    fake_calls(monkeypatch, {"error": "invalid api key"})

    with pytest.raises(ProviderError, match="invalid api key"):
        SerpApiProvider().fetch(make_flight())


def test_currency_mismatch_is_rejected(monkeypatch):
    fake_calls(monkeypatch, one_way())

    # The response says USD while the tracker is in GBP.
    with pytest.raises(ProviderError, match="returned USD"):
        SerpApiProvider().fetch(make_flight(currency="GBP"))


def test_missing_departure_token_is_an_error(monkeypatch):
    response = {
        "search_parameters": {"currency": "USD"},
        "best_flights": [{"price": 168, "layovers": []}],
    }
    fake_calls(monkeypatch, response)

    with pytest.raises(ProviderError, match="departure token"):
        SerpApiProvider().fetch(make_flight(return_date=date(2027, 1, 15)))


def test_empty_and_unpriced_results_are_no_matching_fares(monkeypatch):
    fake_calls(monkeypatch, {"search_parameters": {"currency": "USD"}})
    with pytest.raises(NoMatchingFare):
        SerpApiProvider().fetch(make_flight())

    fake_calls(monkeypatch, one_way(price=0))
    with pytest.raises(NoMatchingFare):
        SerpApiProvider().fetch(make_flight())


def test_estimated_calls_depends_on_the_return_date():
    provider = SerpApiProvider()

    assert provider.estimated_calls(make_flight()) == 1
    assert provider.estimated_calls(make_flight(return_date=date(2027, 1, 15))) == 2


def test_missing_key_fails_before_any_request(monkeypatch, app):
    monkeypatch.setitem(app.config, "SERPAPI_KEY", "")
    calls = fake_calls(monkeypatch, one_way())

    with pytest.raises(ProviderError, match="SERPAPI_KEY"):
        SerpApiProvider().fetch(make_flight())

    assert calls == []

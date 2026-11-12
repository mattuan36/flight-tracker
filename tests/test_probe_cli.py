"""``flask probe-prices``: no PriceCheck writes, but every attempt is billed."""

from __future__ import annotations

from sqlalchemy import func, select

from app.extensions import db
from app.models import ApiUsage, PriceCheck, utcnow


class FakeJson:
    def __init__(self, responses) -> None:
        self.responses = list(responses)
        self.calls = []

    def __call__(self, url, params, *, timeout):
        self.calls.append({"url": url, "params": dict(params), "timeout": timeout})
        return self.responses[len(self.calls) - 1]


def response(price: int, airline: str = "Southwest") -> dict:
    return {
        "search_parameters": {"currency": "USD"},
        "best_flights": [
            {
                "price": price,
                "layovers": [],
                "departure_token": f"token-{price}",
                "flights": [{"airline": airline}],
            }
        ],
    }


def invoke(app, *args: str):
    return app.test_cli_runner().invoke(args=["probe-prices", *args])


def test_probe_prints_a_fare_and_writes_only_usage(app, monkeypatch):
    fake = FakeJson([response(110)])
    monkeypatch.setitem(app.config, "SERPAPI_KEY", "test-key")
    monkeypatch.setattr("app.services.serpapi.get_json", fake)

    result = invoke(app, "--route", "pdx-oak", "--depart", "2027-01-08")

    assert result.exit_code == 0, result.output
    assert "PDX-OAK" in result.output
    assert "$110.00" in result.output
    assert "carrier: Southwest" in result.output
    assert "test-key" not in result.output
    assert "include_airlines" not in fake.calls[0]["params"]
    assert db.session.scalar(select(func.count()).select_from(PriceCheck)) == 0
    assert db.session.scalar(select(ApiUsage)).calls == 1


def test_probe_can_narrow_to_several_airlines(app, monkeypatch):
    fake = FakeJson([response(110, airline="Alaska")])
    monkeypatch.setitem(app.config, "SERPAPI_KEY", "test-key")
    monkeypatch.setattr("app.services.serpapi.get_json", fake)

    result = invoke(
        app,
        "--route",
        "PDX-OAK",
        "--depart",
        "2027-01-08",
        "--airline",
        "AS",
        "--airline",
        "WN",
    )

    assert result.exit_code == 0, result.output
    assert "airline: Alaska / Southwest" in result.output
    assert "carrier: Alaska" in result.output
    assert fake.calls[0]["params"]["include_airlines"] == "AS,WN"
    assert db.session.scalar(select(ApiUsage)).calls == 1


def test_probe_rejects_an_unknown_airline_before_reserving(app, monkeypatch):
    fake = FakeJson([response(110)])
    monkeypatch.setitem(app.config, "SERPAPI_KEY", "test-key")
    monkeypatch.setattr("app.services.serpapi.get_json", fake)

    result = invoke(app, "--depart", "2027-01-08", "--airline", "ZZ")

    assert result.exit_code != 0
    assert "unsupported airline code" in result.output
    assert fake.calls == []
    assert db.session.scalar(select(ApiUsage)) is None


def test_return_probe_reserves_two_calls(app, monkeypatch):
    fake = FakeJson([response(168), response(168)])
    monkeypatch.setitem(app.config, "SERPAPI_KEY", "test-key")
    monkeypatch.setattr("app.services.serpapi.get_json", fake)

    result = invoke(
        app,
        "--route",
        "PDX-MDW",
        "--depart",
        "2027-01-08",
        "--return",
        "2027-01-15",
    )

    assert result.exit_code == 0, result.output
    assert len(fake.calls) == 2
    assert fake.calls[1]["params"]["departure_token"]
    assert db.session.scalar(select(ApiUsage)).calls == 2


def test_probe_reports_a_clean_no_fare_without_writing_a_check(app, monkeypatch):
    fake = FakeJson([{"error": "Google Flights hasn't returned any results for this query."}])
    monkeypatch.setitem(app.config, "SERPAPI_KEY", "test-key")
    monkeypatch.setattr("app.services.serpapi.get_json", fake)

    result = invoke(app, "--depart", "2027-01-08")

    assert result.exit_code == 0, result.output
    assert "no matching fare" in result.output
    assert db.session.scalar(select(func.count()).select_from(PriceCheck)) == 0
    assert db.session.scalar(select(ApiUsage)).calls == 1


def test_probe_refuses_when_the_monthly_budget_is_exhausted(app, monkeypatch):
    monkeypatch.setitem(app.config, "SERPAPI_KEY", "test-key")
    db.session.add(ApiUsage(provider="serpapi", day=utcnow().date(), calls=250))
    db.session.commit()
    fake = FakeJson([response(110)])
    monkeypatch.setattr("app.services.serpapi.get_json", fake)

    result = invoke(app, "--depart", "2027-01-08")

    assert result.exit_code != 0
    assert "budget reached" in result.output
    assert fake.calls == []


def test_probe_requires_a_key(app, monkeypatch):
    monkeypatch.setitem(app.config, "SERPAPI_KEY", "")

    result = invoke(app, "--depart", "2027-01-08")

    assert result.exit_code != 0
    assert "SERPAPI_KEY is not set" in result.output


def test_probe_rejects_bad_route_and_dates(app, monkeypatch):
    monkeypatch.setitem(app.config, "SERPAPI_KEY", "test-key")

    assert invoke(app, "--route", "PDX").exit_code != 0
    assert invoke(app, "--depart", "tomorrow").exit_code != 0
    assert (
        invoke(
            app,
            "--depart",
            "2027-01-15",
            "--return",
            "2027-01-08",
        ).exit_code
        != 0
    )

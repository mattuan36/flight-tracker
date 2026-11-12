"""Display labels and choice lists shared by forms and templates.

Kept out of the models so a wording change never looks like a schema change.
"""

from __future__ import annotations

CABIN_LABELS: dict[str, str] = {
    "economy": "Economy",
    "premium_economy": "Premium economy",
    "business": "Business",
    "first": "First",
}
CABIN_CHOICES = list(CABIN_LABELS.items())

# A curated list, not an exhaustive airline database. The filter accepts any
# two-letter IATA code in storage, but the form only offers carriers the app can
# name clearly. Add more here as routes grow.
AIRLINE_LABELS: dict[str, str] = {
    "EI": "Aer Lingus",
    "AM": "Aeroméxico",
    "AC": "Air Canada",
    "AF": "Air France",
    "AS": "Alaska",
    "G4": "Allegiant",
    "AA": "American",
    "BA": "British Airways",
    "DL": "Delta",
    "U2": "easyJet",
    "F9": "Frontier",
    "HA": "Hawaiian",
    "IB": "Iberia",
    "LS": "Jet2",
    "B6": "JetBlue",
    "KL": "KLM",
    "LH": "Lufthansa",
    "WN": "Southwest",
    "NK": "Spirit",
    "SY": "Sun Country",
    "UA": "United",
    "VS": "Virgin Atlantic",
}
AIRLINE_CHOICES = list(AIRLINE_LABELS.items())


def split_airline_filter(value) -> list[str]:
    """Return the IATA codes from a stored filter, preserving their order."""
    if not value:
        return []
    raw = value.replace(" ", ",").split(",") if isinstance(value, str) else value
    codes = []
    for item in raw:
        code = str(item).strip().upper()
        if code and code not in codes:
            codes.append(code)
    return codes


def airline_label(code: str) -> str:
    return AIRLINE_LABELS.get(str(code).strip().upper(), str(code).strip().upper())


def airline_filter_label(value) -> str:
    """A compact label for the selected carriers, or 'Any airline'."""
    codes = split_airline_filter(value)
    if not codes:
        return "Any airline"
    names = [airline_label(code) for code in codes]
    if len(names) == 1:
        return names[0]
    if len(names) == 2:
        return f"{names[0]} / {names[1]}"
    return f"{names[0]} + {len(names) - 1} more"


MODE_LABELS: dict[str, str] = {
    "target": "Below a target price",
    "any_drop": "Any drop from the usual fare",
}
MODE_CHOICES = list(MODE_LABELS.items())

STOPS_LABELS: dict[int | None, str] = {
    0: "Non-stop",
    1: "1 stop or fewer",
    None: "Any number of stops",
}
STOPS_CHOICES = [
    ("0", "Non-stop"),
    ("1", "1 stop or fewer"),
    ("", "Any number of stops"),
]


def stops_label(value) -> str:
    if value in (None, "", "any"):
        return STOPS_LABELS[None]
    try:
        return STOPS_LABELS[int(value)]
    except (KeyError, TypeError, ValueError):
        return str(value)


CURRENCY_SYMBOLS: dict[str, str] = {"GBP": "£", "EUR": "€", "USD": "$"}
CURRENCY_CHOICES = [
    ("USD", "Dollars (USD)"),
    ("GBP", "Pounds (GBP)"),
    ("EUR", "Euros (EUR)"),
]

INTERVAL_CHOICES = [
    ("6", "Every 6 hours"),
    ("12", "Every 12 hours"),
    ("24", "Once a day"),
]

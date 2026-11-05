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

MODE_LABELS: dict[str, str] = {
    "target": "Below a target price",
    "any_drop": "Any drop from the usual fare",
}
MODE_CHOICES = list(MODE_LABELS.items())

AIRLINE_SUGGESTIONS: list[str] = [
    "Aer Lingus",
    "Air Canada",
    "Air France",
    "American Airlines",
    "British Airways",
    "Delta",
    "easyJet",
    "Emirates",
    "Iberia",
    "Jet2",
    "KLM",
    "Lufthansa",
    "Norwegian",
    "Qatar Airways",
    "Ryanair",
    "Singapore Airlines",
    "Swiss",
    "Turkish Airlines",
    "United",
    "Virgin Atlantic",
    "Wizz Air",
]

CURRENCY_SYMBOLS: dict[str, str] = {"GBP": "£", "EUR": "€", "USD": "$"}
CURRENCY_CHOICES = [
    ("GBP", "Pounds (GBP)"),
    ("EUR", "Euros (EUR)"),
    ("USD", "Dollars (USD)"),
]

INTERVAL_CHOICES = [
    ("6", "Every 6 hours"),
    ("12", "Every 12 hours"),
    ("24", "Once a day"),
]

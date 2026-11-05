"""Money helpers.

Everything is stored in integer cents. Formatting works on integers so a price
can never acquire a float rounding error on its way to the page.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from .labels import CURRENCY_SYMBOLS


def format_cents(cents: int | None, currency: str = "GBP") -> str:
    if cents is None:
        return "—"
    symbol = CURRENCY_SYMBOLS.get(currency, "")
    whole, part = divmod(abs(int(cents)), 100)
    sign = "-" if cents < 0 else ""
    return f"{sign}{symbol}{whole:,}.{part:02d}"


def to_cents(amount: Decimal) -> int:
    """Convert a decimal amount of money to whole cents, half up."""
    return int((amount * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))

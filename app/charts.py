"""Geometry for the detail price chart.

The dashboard's sparkline is deliberately label-free and tiny. The detail chart
carries a date axis, round fare steps and a hoverable point per check, so the
arithmetic lives here where it can be tested; the template only draws what this
returns.

Each history entry is a mapping with ``date`` (for the x axis), ``when`` (the
full local timestamp for the tooltip) and ``price`` in cents. Formatting the
timestamps is the caller's job because only it knows the account's timezone.
"""

from __future__ import annotations

import math

from .money import format_cents

LEFT = 62
RIGHT_PAD = 10
TOP = 10
BOTTOM_PAD = 26


def _nice_step(span: float) -> int:
    """A round fare step (in cents) that divides the range into about four."""
    rough = span / 4
    magnitude = 10 ** math.floor(math.log10(rough))
    for factor in (1, 2, 2.5, 5, 10):
        step = factor * magnitude
        if step >= rough:
            return max(1, int(step))
    return max(1, int(10 * magnitude))


def _fare_label(cents: int, currency: str) -> str:
    text = format_cents(cents, currency)
    return text[:-3] if text.endswith(".00") else text


def price_chart(
    history,
    target: int | None = None,
    width: int = 640,
    height: int = 220,
    currency: str = "GBP",
) -> dict | None:
    """Build the detail chart, or ``None`` when there is not enough history."""
    points = [
        {
            "date": str(entry.get("date", "")),
            "when": str(entry.get("when", "")),
            "price": int(entry["price"]),
        }
        for entry in history
        if entry.get("price") is not None
    ]
    if len(points) < 2:
        return None

    values = [point["price"] for point in points]
    low_value = min(values)
    high_value = max(values)
    if target is not None and target > 0:
        low_value = min(low_value, int(target))
        high_value = max(high_value, int(target))

    span_hint = high_value - low_value
    if span_hint <= 0:
        # A flat line still deserves a readable axis around it.
        span_hint = max(1000, high_value // 20)
        low_value -= span_hint // 2
        high_value += span_hint // 2

    step = _nice_step(span_hint)
    low = max(0, (low_value // step) * step)
    high = math.ceil(high_value / step) * step
    if high <= low:
        high = low + step

    left = LEFT
    right = width - RIGHT_PAD
    top = TOP
    bottom = height - BOTTOM_PAD
    span = high - low
    x_step = (right - left) / (len(points) - 1)

    def y_for(value: int) -> float:
        return round(top + (high - value) / span * (bottom - top), 1)

    point_data = []
    for index, point in enumerate(points):
        point_data.append(
            {
                "x": round(left + index * x_step, 1),
                "y": y_for(point["price"]),
                "when": point["when"],
                "price": format_cents(point["price"], currency),
            }
        )

    y_ticks = [
        {"y": y_for(value), "label": _fare_label(value, currency)}
        for value in range(low, high + step, step)
    ]

    x_ticks = []
    for index in sorted({0, len(points) // 2, len(points) - 1}):
        anchor = "start" if index == 0 else "end" if index == len(points) - 1 else "middle"
        x_ticks.append(
            {
                "x": round(left + index * x_step, 1),
                "label": points[index]["date"],
                "anchor": anchor,
            }
        )

    target_y = y_for(int(target)) if target is not None and target > 0 else None
    target_label = None
    if target_y is not None:
        label_y = target_y - 7
        if label_y < top + 9:
            label_y = target_y + 14
        target_label = {
            "x": left + 6,
            "y": round(label_y, 1),
            "text": f"target {_fare_label(int(target), currency)}",
        }

    return {
        "width": width,
        "height": height,
        "left": left,
        "right": right,
        "top": top,
        "bottom": bottom,
        "polyline": " ".join(f"{point['x']},{point['y']}" for point in point_data),
        "points": point_data,
        "y_ticks": y_ticks,
        "x_ticks": x_ticks,
        "target_y": target_y,
        "target_label": target_label,
    }

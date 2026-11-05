"""The detail chart's axes, target label and inspectable points."""

from __future__ import annotations

from app.charts import price_chart


def entry(day: int, price: int):
    return {
        "date": f"{day:02d} Oct",
        "when": f"{day:02d} Oct 2026, 12:00",
        "price": price,
    }


def test_a_single_point_is_not_a_chart() -> None:
    assert price_chart([]) is None
    assert price_chart([entry(1, 40000)]) is None


def test_y_axis_uses_round_fares() -> None:
    chart = price_chart([entry(1, 68500), entry(10, 50000), entry(20, 38900)], 42000)

    labels = [tick["label"] for tick in chart["y_ticks"]]
    assert labels == ["£300", "£400", "£500", "£600", "£700"]
    assert all(chart["top"] <= tick["y"] <= chart["bottom"] for tick in chart["y_ticks"])


def test_x_axis_labels_the_range_and_middle() -> None:
    chart = price_chart([entry(1, 68500), entry(10, 50000), entry(20, 38900)])

    assert [tick["label"] for tick in chart["x_ticks"]] == ["01 Oct", "10 Oct", "20 Oct"]
    assert chart["x_ticks"][0]["anchor"] == "start"
    assert chart["x_ticks"][-1]["anchor"] == "end"


def test_target_sits_on_the_same_scale() -> None:
    chart = price_chart([entry(1, 50000), entry(2, 40000)], 45000)

    assert chart["target_y"] is not None
    assert chart["top"] <= chart["target_y"] <= chart["bottom"]


def test_target_label_sits_above_the_line_by_the_y_axis() -> None:
    chart = price_chart([entry(1, 50000), entry(2, 40000)], 45000)

    label = chart["target_label"]
    assert label["text"] == "target £450"
    assert label["y"] < chart["target_y"]
    assert label["x"] > chart["left"]


def test_without_a_target_there_is_no_line_or_label() -> None:
    chart = price_chart([entry(1, 50000), entry(2, 40000)])

    assert chart["target_y"] is None
    assert chart["target_label"] is None


def test_every_point_carries_its_exact_fare_and_time() -> None:
    chart = price_chart([entry(1, 68500), entry(20, 38900)])

    first, last = chart["points"]
    assert first["when"] == "01 Oct 2026, 12:00"
    assert first["price"] == "£685.00"
    assert last["price"] == "£389.00"
    assert all(chart["left"] <= point["x"] <= chart["right"] for point in chart["points"])
    assert all(chart["top"] <= point["y"] <= chart["bottom"] for point in chart["points"])


def test_a_flat_history_still_gets_a_readable_axis() -> None:
    chart = price_chart([entry(1, 40000), entry(2, 40000)])

    assert len(chart["y_ticks"]) >= 2
    assert chart["y_ticks"][0]["label"] != chart["y_ticks"][-1]["label"]

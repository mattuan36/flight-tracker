"""Tracked flights: list, detail, add, edit, pause, delete.

Every route is scoped to the signed-in user. Another user's tracker answers 404
rather than 403, so ids cannot be probed for existence.
"""

from __future__ import annotations

from decimal import Decimal

from flask import (
    Blueprint,
    abort,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import current_user, login_required

from ..extensions import db
from ..models import TrackedFlight
from ..money import to_cents
from ..templating import localdt
from .forms import FlightForm

trackers_bp = Blueprint("trackers", __name__, url_prefix="/flights")


def _owned_flight(flight_id: int) -> TrackedFlight:
    flight = db.session.get(TrackedFlight, flight_id)
    if flight is None or flight.user_id != current_user.id:
        abort(404)
    return flight


def _apply(form: FlightForm, flight: TrackedFlight) -> None:
    flight.origin_iata = form.origin_iata.data
    flight.dest_iata = form.dest_iata.data
    flight.depart_date = form.depart_date.data
    flight.return_date = form.return_date.data or None
    flight.airline = form.airline.data or None
    flight.cabin = form.cabin.data
    flight.adults = int(form.adults.data)
    flight.currency = form.currency.data
    flight.mode = form.mode.data
    flight.check_interval_hours = int(form.check_interval_hours.data)
    flight.target_price_cents = (
        to_cents(form.target.data)
        if form.mode.data == "target" and form.target.data is not None
        else None
    )


@trackers_bp.route("/new", methods=["GET", "POST"])
@login_required
def new():
    form = FlightForm()
    if form.validate_on_submit():
        flight = TrackedFlight(user_id=current_user.id)
        _apply(form, flight)
        db.session.add(flight)
        db.session.commit()
        flash(
            f"Tracking {flight.route}. The first fare arrives with the next price check.",
            "success",
        )
        return redirect(url_for("trackers.detail", flight_id=flight.id))
    return render_template("trackers/form.html", form=form, flight=None)


@trackers_bp.get("/<int:flight_id>")
@login_required
def detail(flight_id: int):
    flight = _owned_flight(flight_id)
    recent = list(reversed(flight.price_checks[-12:]))
    history = [
        {
            "date": localdt(check.checked_at, "%d %b"),
            "when": localdt(check.checked_at, "%d %b %Y, %H:%M"),
            "price": check.price_cents,
        }
        for check in flight.price_checks[-60:]
        if check.ok and check.price_cents is not None
    ]
    return render_template(
        "trackers/detail.html",
        flight=flight,
        checks=recent,
        history=history,
    )


@trackers_bp.route("/<int:flight_id>/edit", methods=["GET", "POST"])
@login_required
def edit(flight_id: int):
    flight = _owned_flight(flight_id)

    if request.method == "GET":
        form = FlightForm(
            data={
                "origin_iata": flight.origin_iata,
                "dest_iata": flight.dest_iata,
                "depart_date": flight.depart_date,
                "return_date": flight.return_date,
                "airline": flight.airline or "",
                "cabin": flight.cabin,
                "adults": flight.adults,
                "currency": flight.currency,
                "mode": flight.mode,
                "target": (
                    Decimal(flight.target_price_cents) / 100
                    if flight.target_price_cents is not None
                    else None
                ),
                "check_interval_hours": str(flight.check_interval_hours),
            }
        )
    else:
        form = FlightForm()

    if form.validate_on_submit():
        if flight.last_price_cents is not None and form.currency.data != flight.currency:
            form.currency.errors.append(
                f"This tracker has price history in {flight.currency}; "
                "add a new one to watch a different currency."
            )
        else:
            _apply(form, flight)
            db.session.commit()
            flash("Saved.", "success")
            return redirect(url_for("trackers.detail", flight_id=flight.id))

    return render_template("trackers/form.html", form=form, flight=flight)


@trackers_bp.post("/<int:flight_id>/toggle")
@login_required
def toggle(flight_id: int):
    flight = _owned_flight(flight_id)
    flight.is_active = not flight.is_active
    db.session.commit()
    flash(
        "Resumed; checks will run again."
        if flight.is_active
        else "Paused. No checks run until you resume it.",
        "info",
    )
    return redirect(url_for("trackers.detail", flight_id=flight.id))


@trackers_bp.get("/<int:flight_id>/delete")
@login_required
def delete_confirm(flight_id: int):
    flight = _owned_flight(flight_id)
    return render_template("trackers/delete.html", flight=flight)


@trackers_bp.post("/<int:flight_id>/delete")
@login_required
def delete(flight_id: int):
    flight = _owned_flight(flight_id)
    route = flight.route
    db.session.delete(flight)
    db.session.commit()
    flash(f"Deleted {route}.", "info")
    return redirect(url_for("main.index"))

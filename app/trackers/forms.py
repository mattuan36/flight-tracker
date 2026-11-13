"""Form for adding and editing a tracked flight."""

from __future__ import annotations

from decimal import Decimal

from flask_wtf import FlaskForm
from wtforms import (
    DateField,
    DecimalField,
    IntegerField,
    RadioField,
    SelectField,
    SelectMultipleField,
    StringField,
    SubmitField,
    widgets,
)
from wtforms.validators import (
    DataRequired,
    InputRequired,
    NumberRange,
    Optional,
    Regexp,
    ValidationError,
)

from ..labels import (
    AIRLINE_CHOICES,
    CABIN_CHOICES,
    CURRENCY_CHOICES,
    INTERVAL_CHOICES,
    MODE_CHOICES,
    STOPS_CHOICES,
)
from ..models import utcnow

IATA_MESSAGE = "Use a three-letter airport code, like PDX."


def _airport_code(value):
    return value.strip().upper() if isinstance(value, str) else value


class FlightForm(FlaskForm):
    origin_iata = StringField(
        "From",
        filters=[_airport_code],
        validators=[
            DataRequired("Enter the departure airport."),
            Regexp(r"^[A-Z]{3}$", message=IATA_MESSAGE),
        ],
    )
    dest_iata = StringField(
        "To",
        filters=[_airport_code],
        validators=[
            DataRequired("Enter the destination airport."),
            Regexp(r"^[A-Z]{3}$", message=IATA_MESSAGE),
        ],
    )
    airlines = SelectMultipleField(
        "Airlines",
        choices=AIRLINE_CHOICES,
        coerce=str,
        widget=widgets.ListWidget(prefix_label=False),
        option_widget=widgets.CheckboxInput(),
        description="Leave all unchecked to search every airline.",
    )
    depart_date = DateField("Departing", validators=[DataRequired("Pick a departure date.")])
    return_date = DateField("Returning (optional)", validators=[Optional()])
    max_stops = SelectField(
        "Stops",
        choices=STOPS_CHOICES,
        default="0",
        description="0 is non-stop, 1 is one stop or fewer, blank is any.",
    )
    cabin = SelectField("Cabin", choices=CABIN_CHOICES, default="economy")
    adults = IntegerField(
        "Adults",
        default=1,
        validators=[
            InputRequired("How many adults?"),
            NumberRange(min=1, max=9, message="Between 1 and 9 adults."),
        ],
    )
    currency = SelectField("Currency", choices=CURRENCY_CHOICES, default="USD")
    mode = RadioField("Alert me", choices=MODE_CHOICES, default="target")
    target = DecimalField(
        "Target price",
        places=2,
        validators=[
            Optional(),
            NumberRange(
                min=Decimal("0.01"),
                max=Decimal("100000"),
                message="Enter an amount between 0.01 and 100,000.",
            ),
        ],
    )
    check_interval_hours = SelectField("Check frequency", choices=INTERVAL_CHOICES, default="24")
    submit = SubmitField("Save flight")

    def validate_dest_iata(self, field):
        if field.data and field.data == self.origin_iata.data:
            raise ValidationError("Origin and destination cannot be the same.")

    def validate_depart_date(self, field):
        if field.data and field.data < utcnow().date():
            raise ValidationError("Pick today or a later date.")

    def validate_return_date(self, field):
        if field.data and self.depart_date.data and field.data < self.depart_date.data:
            raise ValidationError("The return date cannot be before the departure date.")

    def validate(self, extra_validators=None):
        valid = super().validate(extra_validators)
        if self.mode.data == "any_drop":
            # Any target left over from a previous mode is meaningless.
            self.target.data = None
        elif self.target.data is None:
            self.target.errors.append("Enter the price you would pay, or choose any drop.")
            valid = False
        return valid

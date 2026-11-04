"""Forms. Validation messages are written for people, not for logs."""

from __future__ import annotations

from flask_wtf import FlaskForm
from wtforms import PasswordField, SelectField, StringField, SubmitField
from wtforms.validators import DataRequired, Email, EqualTo, Length


class LoginForm(FlaskForm):
    email = StringField(
        "Email",
        validators=[
            DataRequired("Enter your email address."),
            Email("That does not look like an email address."),
            Length(max=254),
        ],
    )
    password = PasswordField("Password", validators=[DataRequired("Enter your password.")])
    submit = SubmitField("Sign in")


class AcceptInviteForm(FlaskForm):
    display_name = StringField(
        "Your name",
        validators=[
            DataRequired("Tell us what to call you."),
            Length(min=2, max=80, message="Use between 2 and 80 characters."),
        ],
    )
    timezone = SelectField("Timezone", validators=[DataRequired()])
    password = PasswordField("Password")
    confirm = PasswordField(
        "Confirm password",
        validators=[
            DataRequired("Confirm your password."),
            EqualTo("password", message="The two passwords do not match."),
        ],
    )
    submit = SubmitField("Create account")

    def __init__(self, *args, timezone_choices=(), **kwargs):
        super().__init__(*args, **kwargs)
        self.timezone.choices = list(timezone_choices)


class SwitchAccountForm(FlaskForm):
    """The interstitial shown when an invite is opened while someone else is signed in."""

    submit = SubmitField("Sign out and continue")


class ForgotPasswordForm(FlaskForm):
    email = StringField(
        "Email",
        validators=[
            DataRequired("Enter your email address."),
            Email("That does not look like an email address."),
            Length(max=254),
        ],
    )
    submit = SubmitField("Request a reset link")


class ResetPasswordForm(FlaskForm):
    password = PasswordField("New password")
    confirm = PasswordField(
        "Confirm new password",
        validators=[
            DataRequired("Confirm your new password."),
            EqualTo("password", message="The two passwords do not match."),
        ],
    )
    submit = SubmitField("Set new password")

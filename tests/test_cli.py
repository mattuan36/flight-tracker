from __future__ import annotations


def test_config_prints_settings_with_masked_secret(app):
    app.config["SECRET_KEY"] = "super-secret-value-that-must-not-leak"

    result = app.test_cli_runner().invoke(args=["config"])

    assert result.exit_code == 0
    assert "SECRET_KEY" in result.output
    assert "super-secret-value" not in result.output
    assert "PRICE_PROVIDER" in result.output


def test_config_masks_database_password(app):
    app.config["SQLALCHEMY_DATABASE_URI"] = "mysql+pymysql://user:hunter2@host/db"

    result = app.test_cli_runner().invoke(args=["config"])

    assert result.exit_code == 0
    assert "hunter2" not in result.output


def test_health_command_succeeds(app):
    result = app.test_cli_runner().invoke(args=["health"])

    assert result.exit_code == 0
    assert "status: ok" in result.output

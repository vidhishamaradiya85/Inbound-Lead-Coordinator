"""Focused tests for application configuration loading and validation."""

from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import SecretStr, ValidationError

from config.settings import load_settings


SETTINGS_ENV_VARS = (
    "APP_NAME",
    "APP_ENV",
    "DATABASE_SQLITE_PATH",
    "DATABASE_BUSY_TIMEOUT_MS",
    "DATABASE_FOREIGN_KEYS_ENABLED",
    "AGENT_MAX_PROCESSING_ITERATIONS",
    "AGENT_MAX_LEADS_PER_RUN",
    "AGENT_CONFIDENCE_THRESHOLD",
    "AGENT_HUMAN_ESCALATION_THRESHOLD",
    "MODEL_API_KEY",
    "SAFETY_KILL_SWITCH_ENFORCED",
    "SAFETY_MAX_TOOL_RETRIES",
    "SAFETY_TOOL_TIMEOUT_SECONDS",
    "SAFETY_SPENDING_LIMIT_USD_PER_RUN",
    "LOG_LEVEL",
    "LOG_FILE_PATH",
)


@pytest.fixture(autouse=True)
def clear_settings_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Prevent settings tests from depending on the user's environment."""

    for variable_name in SETTINGS_ENV_VARS:
        monkeypatch.delenv(variable_name, raising=False)


def test_load_settings_uses_defaults() -> None:
    settings = load_settings()

    assert settings.application.name == "Inbound Lead Coordinator"
    assert settings.application.environment == "development"

    assert settings.database.sqlite_path == Path("database/inbound_leads.sqlite3")
    assert settings.database.busy_timeout_ms == 5000
    assert settings.database.foreign_keys_enabled is True

    assert settings.agent.max_processing_iterations == 100
    assert settings.agent.max_leads_per_run == 25
    assert settings.agent.confidence_threshold == 0.85
    assert settings.agent.human_escalation_threshold == 0.70
    assert settings.agent.model_api_key is None

    assert settings.safety.kill_switch_enforced is True
    assert settings.safety.max_tool_retries == 2
    assert settings.safety.tool_timeout_seconds == 5.0
    assert settings.safety.spending_limit_usd_per_run == Decimal("0.00")

    assert settings.logging.level == "INFO"
    assert settings.logging.file_path == Path("logs/agent.log")


def test_load_settings_applies_environment_overrides(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    overrides = {
        "APP_NAME": "Inbound Lead Coordinator Test",
        "APP_ENV": "testing",
        "DATABASE_SQLITE_PATH": "database/test.sqlite3",
        "DATABASE_BUSY_TIMEOUT_MS": "2500",
        "DATABASE_FOREIGN_KEYS_ENABLED": "false",
        "AGENT_MAX_PROCESSING_ITERATIONS": "12",
        "AGENT_MAX_LEADS_PER_RUN": "3",
        "AGENT_CONFIDENCE_THRESHOLD": "0.9",
        "AGENT_HUMAN_ESCALATION_THRESHOLD": "0.6",
        "MODEL_API_KEY": "override-test-secret",
        "SAFETY_KILL_SWITCH_ENFORCED": "true",
        "SAFETY_MAX_TOOL_RETRIES": "1",
        "SAFETY_TOOL_TIMEOUT_SECONDS": "2.5",
        "SAFETY_SPENDING_LIMIT_USD_PER_RUN": "1.25",
        "LOG_LEVEL": "DEBUG",
        "LOG_FILE_PATH": "logs/test.log",
    }
    for variable_name, value in overrides.items():
        monkeypatch.setenv(variable_name, value)

    settings = load_settings()

    assert settings.application.name == "Inbound Lead Coordinator Test"
    assert settings.application.environment == "testing"
    assert settings.database.sqlite_path == Path("database/test.sqlite3")
    assert settings.database.busy_timeout_ms == 2500
    assert settings.database.foreign_keys_enabled is False
    assert settings.agent.max_processing_iterations == 12
    assert settings.agent.max_leads_per_run == 3
    assert settings.agent.confidence_threshold == 0.9
    assert settings.agent.human_escalation_threshold == 0.6
    assert settings.safety.kill_switch_enforced is True
    assert settings.safety.max_tool_retries == 1
    assert settings.safety.tool_timeout_seconds == 2.5
    assert settings.safety.spending_limit_usd_per_run == Decimal("1.25")
    assert settings.logging.level == "DEBUG"
    assert settings.logging.file_path == Path("logs/test.log")

    # Avoid assertion introspection that could print the test secret on failure.
    if not isinstance(settings.agent.model_api_key, SecretStr):
        pytest.fail("environment API key was not stored as SecretStr", pytrace=False)
    if settings.agent.model_api_key.get_secret_value() != "override-test-secret":
        pytest.fail("environment API key did not round-trip", pytrace=False)


def test_invalid_application_environment_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APP_ENV", "staging")

    with pytest.raises(ValidationError):
        load_settings()


@pytest.mark.parametrize(
    ("variable_name", "value"),
    [
        ("AGENT_CONFIDENCE_THRESHOLD", "-0.01"),
        ("AGENT_CONFIDENCE_THRESHOLD", "1.01"),
        ("AGENT_HUMAN_ESCALATION_THRESHOLD", "-0.01"),
        ("AGENT_HUMAN_ESCALATION_THRESHOLD", "1.01"),
    ],
    ids=[
        "confidence-below-zero",
        "confidence-above-one",
        "escalation-below-zero",
        "escalation-above-one",
    ],
)
def test_confidence_values_outside_zero_to_one_are_rejected(
    monkeypatch: pytest.MonkeyPatch,
    variable_name: str,
    value: str,
) -> None:
    monkeypatch.setenv(variable_name, value)

    with pytest.raises(ValidationError):
        load_settings()


def test_human_escalation_threshold_cannot_exceed_confidence_threshold(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AGENT_CONFIDENCE_THRESHOLD", "0.80")
    monkeypatch.setenv("AGENT_HUMAN_ESCALATION_THRESHOLD", "0.81")

    with pytest.raises(ValidationError):
        load_settings()


@pytest.mark.parametrize(
    ("variable_name", "value"),
    [
        ("AGENT_MAX_PROCESSING_ITERATIONS", "0"),
        ("AGENT_MAX_PROCESSING_ITERATIONS", "-1"),
        ("AGENT_MAX_LEADS_PER_RUN", "0"),
        ("AGENT_MAX_LEADS_PER_RUN", "-1"),
        ("SAFETY_MAX_TOOL_RETRIES", "0"),
        ("SAFETY_MAX_TOOL_RETRIES", "-1"),
    ],
    ids=[
        "zero-iterations",
        "negative-iterations",
        "zero-leads",
        "negative-leads",
        "zero-retries",
        "negative-retries",
    ],
)
def test_zero_or_negative_execution_limits_are_rejected(
    monkeypatch: pytest.MonkeyPatch,
    variable_name: str,
    value: str,
) -> None:
    monkeypatch.setenv(variable_name, value)

    with pytest.raises(ValidationError):
        load_settings()


@pytest.mark.parametrize("value", ["0", "-0.1"], ids=["zero", "negative"])
def test_non_positive_tool_timeout_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
    value: str,
) -> None:
    monkeypatch.setenv("SAFETY_TOOL_TIMEOUT_SECONDS", value)

    with pytest.raises(ValidationError):
        load_settings()


def test_negative_spending_limit_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SAFETY_SPENDING_LIMIT_USD_PER_RUN", "-0.01")

    with pytest.raises(ValidationError):
        load_settings()


def test_kill_switch_enforcement_cannot_be_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SAFETY_KILL_SWITCH_ENFORCED", "false")

    with pytest.raises(ValidationError):
        load_settings()


def test_invalid_logging_level_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LOG_LEVEL", "VERBOSE")

    with pytest.raises(ValidationError):
        load_settings()


def test_optional_api_key_is_secret_and_masked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret_value = "settings-test-secret-value"
    monkeypatch.setenv("MODEL_API_KEY", secret_value)

    settings = load_settings()
    secret = settings.agent.model_api_key

    if not isinstance(secret, SecretStr):
        pytest.fail("API key was not stored as SecretStr", pytrace=False)
    if secret.get_secret_value() != secret_value:
        pytest.fail("API key did not round-trip", pytrace=False)
    if secret_value in str(secret):
        pytest.fail("SecretStr string representation exposed the API key", pytrace=False)
    if secret_value in repr(settings):
        pytest.fail("settings representation exposed the API key", pytrace=False)


@pytest.mark.parametrize("value", [None, ""], ids=["unset", "blank"])
def test_absent_or_blank_api_key_is_none(
    monkeypatch: pytest.MonkeyPatch,
    value: str | None,
) -> None:
    if value is None:
        monkeypatch.delenv("MODEL_API_KEY", raising=False)
    else:
        monkeypatch.setenv("MODEL_API_KEY", value)

    settings = load_settings()

    assert settings.agent.model_api_key is None

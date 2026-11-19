from decimal import Decimal
import os
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator


EnvironmentName = Literal["development", "testing", "production"]
LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]


class _SettingsModel(BaseModel):
    """Shared validation behavior for configuration sections."""

    model_config = ConfigDict(extra="forbid", validate_default=True)


class ApplicationSettings(_SettingsModel):
    name: str = Field(default="Inbound Lead Coordinator", min_length=1)
    environment: EnvironmentName = "development"


class DatabaseSettings(_SettingsModel):
    sqlite_path: Path = Path("database/inbound_leads.sqlite3")
    busy_timeout_ms: int = Field(default=5000, gt=0)
    foreign_keys_enabled: bool = True


class AgentSettings(_SettingsModel):
    max_processing_iterations: int = Field(default=100, gt=0)
    max_leads_per_run: int = Field(default=25, gt=0)
    confidence_threshold: float = Field(default=0.85, ge=0.0, le=1.0)
    human_escalation_threshold: float = Field(default=0.70, ge=0.0, le=1.0)

    # Reserved for a future, separately approved model integration. No
    # integration is enabled or implemented by this settings module.
    model_api_key: SecretStr | None = None

    @model_validator(mode="after")
    def escalation_threshold_must_not_exceed_automation_threshold(self) -> "AgentSettings":
        if self.human_escalation_threshold > self.confidence_threshold:
            raise ValueError(
                "human_escalation_threshold must be less than or equal to "
                "confidence_threshold"
            )
        return self


class SafetySettings(_SettingsModel):
    # The active on/off state belongs in persistent control data at runtime.
    # This setting requires application code to enforce that state.
    kill_switch_enforced: bool = True
    max_tool_retries: int = Field(default=2, gt=0)
    tool_timeout_seconds: float = Field(default=5.0, gt=0.0)
    spending_limit_usd_per_run: Decimal = Field(
        default=Decimal("0.00"), ge=Decimal("0.00")
    )

    @field_validator("kill_switch_enforced")
    @classmethod
    def kill_switch_enforcement_cannot_be_disabled(cls, value: bool) -> bool:
        if not value:
            raise ValueError("kill-switch enforcement cannot be disabled")
        return value


class LoggingSettings(_SettingsModel):
    level: LogLevel = "INFO"
    file_path: Path = Path("logs/agent.log")


class AppSettings(_SettingsModel):
    application: ApplicationSettings = Field(default_factory=ApplicationSettings)
    database: DatabaseSettings = Field(default_factory=DatabaseSettings)
    agent: AgentSettings = Field(default_factory=AgentSettings)
    safety: SafetySettings = Field(default_factory=SafetySettings)
    logging: LoggingSettings = Field(default_factory=LoggingSettings)


def _environment_overrides(field_to_variable: dict[str, str]) -> dict[str, str]:
    """Return only configured overrides that are present in os.environ."""

    return {
        field_name: os.environ[variable_name]
        for field_name, variable_name in field_to_variable.items()
        if variable_name in os.environ
    }


def load_settings() -> AppSettings:
    """Build and validate settings, applying optional environment overrides.

    Pydantic converts environment-variable strings to the declared field types
    and raises ValidationError when a value is invalid. No .env file is read.
    """

    settings_data: dict[str, dict[str, str]] = {
        "application": _environment_overrides(
            {
                "name": "APP_NAME",
                "environment": "APP_ENV",
            }
        ),
        "database": _environment_overrides(
            {
                "sqlite_path": "DATABASE_SQLITE_PATH",
                "busy_timeout_ms": "DATABASE_BUSY_TIMEOUT_MS",
                "foreign_keys_enabled": "DATABASE_FOREIGN_KEYS_ENABLED",
            }
        ),
        "agent": _environment_overrides(
            {
                "max_processing_iterations": "AGENT_MAX_PROCESSING_ITERATIONS",
                "max_leads_per_run": "AGENT_MAX_LEADS_PER_RUN",
                "confidence_threshold": "AGENT_CONFIDENCE_THRESHOLD",
                "human_escalation_threshold": "AGENT_HUMAN_ESCALATION_THRESHOLD",
            }
        ),
        "safety": _environment_overrides(
            {
                "kill_switch_enforced": "SAFETY_KILL_SWITCH_ENFORCED",
                "max_tool_retries": "SAFETY_MAX_TOOL_RETRIES",
                "tool_timeout_seconds": "SAFETY_TOOL_TIMEOUT_SECONDS",
                "spending_limit_usd_per_run": "SAFETY_SPENDING_LIMIT_USD_PER_RUN",
            }
        ),
        "logging": _environment_overrides(
            {
                "level": "LOG_LEVEL",
                "file_path": "LOG_FILE_PATH",
            }
        ),
    }

    # An absent or blank key remains None. The key is only made available to
    # a future integration; loading it does not enable or call that integration.
    model_api_key = os.environ.get("MODEL_API_KEY", "").strip()
    if model_api_key:
        settings_data["agent"]["model_api_key"] = model_api_key

    return AppSettings.model_validate(settings_data)

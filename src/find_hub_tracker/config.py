"""Configuration loaded from environment variables / .env file."""

from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from .env or environment variables."""

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}

    # Database
    db_backend: str = "sqlite"
    database_url: str = "postgresql://tracker:tracker@localhost:5432/find_hub_tracker"
    sqlite_path: str = "./data/tracker_history.db"

    # Discord
    discord_webhook_url: str = ""
    discord_battery_webhook_url: str = ""

    # Polling
    poll_interval_seconds: int = 300
    battery_check_interval_seconds: int = 900
    summary_interval_hours: int = 6

    # Battery thresholds
    battery_low_threshold_percent: int = 20
    battery_critical_threshold_percent: int = 10
    wearable_threshold_offset: int = 5

    # Alerts
    alert_cooldown_minutes: int = 60

    # History
    history_retention_days: int = 90

    # Auth
    auth_secrets_path: str = "./Auth/secrets.json"

    # Logging
    log_level: str = "INFO"

    # Sentinel / Heartbeat
    healthchecks_ping_url: str = ""
    heartbeat_stale_threshold_minutes: int = 15

    # Device filter
    devices_to_track: list[str] = []

    @field_validator("devices_to_track", mode="before")
    @classmethod
    def parse_devices_list(cls, v: object) -> list[str]:
        """Parse comma-separated device names into a list."""
        if isinstance(v, str):
            return [d.strip() for d in v.split(",") if d.strip()]
        return v  # type: ignore[return-value]

    @field_validator("db_backend", mode="after")
    @classmethod
    def validate_db_backend(cls, v: str) -> str:
        """Ensure db_backend is postgres or sqlite."""
        v = v.lower()
        if v not in ("postgres", "sqlite"):
            raise ValueError("DB_BACKEND must be 'postgres' or 'sqlite'")
        return v

    @property
    def battery_webhook_url(self) -> str:
        """Return the battery webhook URL, falling back to the main webhook."""
        return self.discord_battery_webhook_url or self.discord_webhook_url

    @property
    def sqlite_path_resolved(self) -> Path:
        """Return the SQLite database path as a resolved Path object."""
        return Path(self.sqlite_path).resolve()


_settings: Settings | None = None


def get_settings() -> Settings:
    """Create and return application settings (cached singleton)."""
    global _settings  # noqa: PLW0603
    if _settings is None:
        _settings = Settings()
    return _settings

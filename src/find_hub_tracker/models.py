"""Pydantic models for device data."""

from datetime import UTC, datetime

from pydantic import BaseModel, Field


class DeviceInfo(BaseModel):
    """A registered Find Hub device."""

    device_id: str
    name: str
    device_type: str = "unknown"  # phone, watch, buds, tracker, tablet, unknown
    model: str | None = None


class DeviceLocation(BaseModel):
    """A single device location reading."""

    device_id: str
    device_name: str
    device_type: str = "unknown"
    latitude: float
    longitude: float
    accuracy_meters: float | None = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    polled_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    address: str | None = None
    battery_percent: int | None = None
    is_charging: bool | None = None

    @property
    def maps_url(self) -> str:
        """Google Maps URL for this location."""
        return f"https://www.google.com/maps?q={self.latitude},{self.longitude}"


class BatteryAlert(BaseModel):
    """A battery alert event."""

    device_id: str
    device_name: str
    device_type: str = "unknown"
    battery_percent: int
    is_critical: bool = False
    alert_time: datetime = Field(default_factory=lambda: datetime.now(UTC))

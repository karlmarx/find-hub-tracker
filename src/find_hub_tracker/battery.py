"""Battery monitoring and alert logic.

NOTE: GoogleFindMyTools does NOT currently provide battery data.
This module is structured to work once battery data becomes available
upstream. Until then, battery_percent will always be None and no alerts
will fire.
"""

from datetime import UTC, datetime, timedelta

import structlog

from find_hub_tracker.db import DatabaseBackend
from find_hub_tracker.discord import DiscordPublisher
from find_hub_tracker.models import BatteryAlert, DeviceLocation

log = structlog.get_logger()

# Device types considered wearables (get lower alert thresholds)
WEARABLE_TYPES = {"watch", "buds"}


class BatteryMonitor:
    """Monitors device battery levels and sends alerts when thresholds are crossed."""

    def __init__(
        self,
        db: DatabaseBackend,
        publisher: DiscordPublisher,
        low_threshold: int = 20,
        critical_threshold: int = 10,
        wearable_offset: int = 5,
        cooldown_minutes: int = 60,
    ) -> None:
        self.db = db
        self.publisher = publisher
        self.low_threshold = low_threshold
        self.critical_threshold = critical_threshold
        self.wearable_offset = wearable_offset
        self.cooldown = timedelta(minutes=cooldown_minutes)

    def _thresholds_for(self, device_type: str) -> tuple[int, int]:
        """Return (low, critical) thresholds, adjusted for wearables."""
        if device_type.lower() in WEARABLE_TYPES:
            return (
                self.low_threshold + self.wearable_offset,
                self.critical_threshold + self.wearable_offset,
            )
        return (self.low_threshold, self.critical_threshold)

    async def check_device(self, location: DeviceLocation) -> BatteryAlert | None:
        """Check a device's battery level and generate an alert if needed.

        Returns:
            A BatteryAlert if one was fired, None otherwise.
        """
        if location.battery_percent is None:
            return None

        low, critical = self._thresholds_for(location.device_type)
        now = datetime.now(UTC)

        is_critical = location.battery_percent <= critical
        is_low = location.battery_percent <= low

        if not is_low:
            return None

        # Check cooldown
        last_alert = await self.db.get_last_alert(location.device_id)
        if last_alert and (now - last_alert.alert_time) < self.cooldown:
            log.debug(
                "alert_cooldown",
                device=location.device_name,
                last_alert_mins_ago=int((now - last_alert.alert_time).total_seconds() / 60),
            )
            return None

        alert = BatteryAlert(
            device_id=location.device_id,
            device_name=location.device_name,
            device_type=location.device_type,
            battery_percent=location.battery_percent,
            is_critical=is_critical,
            alert_time=now,
        )

        await self.db.store_alert(alert)
        await self.publisher.post_battery_alert(alert)

        log.info(
            "battery_alert_sent",
            device=location.device_name,
            battery=location.battery_percent,
            is_critical=is_critical,
        )
        return alert

    async def check_all(self, locations: list[DeviceLocation]) -> list[BatteryAlert]:
        """Check battery levels for all devices.

        Returns:
            All alerts generated across all devices.
        """
        alerts: list[BatteryAlert] = []
        for loc in locations:
            alert = await self.check_device(loc)
            if alert:
                alerts.append(alert)
        return alerts

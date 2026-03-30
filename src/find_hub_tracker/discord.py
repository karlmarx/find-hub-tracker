"""Discord webhook publisher for location updates and battery alerts."""

import asyncio
import math

import httpx
import structlog

from find_hub_tracker.models import BatteryAlert, DeviceLocation

log = structlog.get_logger()

# Embed colors
COLOR_LOCATION = 0x4285F4  # Google Blue
COLOR_SUMMARY = 0x4CAF50  # Green
COLOR_BATTERY_LOW = 0xFFA500  # Orange
COLOR_BATTERY_CRITICAL = 0xF44336  # Red
COLOR_STARTUP = 0x9C27B0  # Purple
COLOR_SHUTDOWN = 0x607D8B  # Blue Grey


class DiscordPublisher:
    """Publishes device updates to Discord via webhooks."""

    def __init__(
        self,
        webhook_url: str,
        battery_webhook_url: str | None = None,
    ) -> None:
        self.webhook_url = webhook_url
        self.battery_webhook_url = battery_webhook_url or webhook_url
        self._client = httpx.AsyncClient(timeout=30.0)

    async def close(self) -> None:
        """Close the HTTP client."""
        await self._client.aclose()

    async def post_location_update(
        self,
        location: DeviceLocation,
        previous: DeviceLocation | None = None,
    ) -> bool:
        """Post a location update embed to Discord."""
        if not self.webhook_url:
            return False

        fields = [
            {
                "name": "Location",
                "value": (
                    f"[{location.latitude:.6f}, {location.longitude:.6f}]({location.maps_url})"
                ),
                "inline": True,
            },
        ]

        if location.accuracy_meters is not None:
            fields.append(
                {
                    "name": "Accuracy",
                    "value": f"{location.accuracy_meters:.0f}m",
                    "inline": True,
                }
            )

        if location.battery_percent is not None:
            charging = " (charging)" if location.is_charging else ""
            fields.append(
                {
                    "name": "Battery",
                    "value": f"{location.battery_percent}%{charging}",
                    "inline": True,
                }
            )

        if previous:
            dist = haversine_distance(
                previous.latitude,
                previous.longitude,
                location.latitude,
                location.longitude,
            )
            fields.append(
                {
                    "name": "Distance Moved",
                    "value": _format_distance(dist),
                    "inline": True,
                }
            )

        fields.append(
            {
                "name": "Last Updated",
                "value": f"<t:{int(location.timestamp.timestamp())}:R>",
                "inline": True,
            }
        )

        embed = {
            "title": f"\U0001f4cd {location.device_name} moved",
            "color": COLOR_LOCATION,
            "fields": fields,
            "timestamp": location.timestamp.isoformat(),
            "footer": {"text": "Google Find Hub Tracker"},
        }

        return await self._send_webhook(self.webhook_url, {"embeds": [embed]})

    async def post_summary(self, locations: list[DeviceLocation]) -> bool:
        """Post a periodic summary embed showing all device locations."""
        if not self.webhook_url or not locations:
            return False

        fields = []
        for loc in locations:
            battery = f" | {loc.battery_percent}%" if loc.battery_percent is not None else ""
            fields.append(
                {
                    "name": loc.device_name,
                    "value": (
                        f"[{loc.latitude:.4f}, {loc.longitude:.4f}]({loc.maps_url})"
                        f"{battery}"
                        f" | <t:{int(loc.timestamp.timestamp())}:R>"
                    ),
                    "inline": False,
                }
            )

        embed = {
            "title": "\U0001f4ca Device Location Summary",
            "color": COLOR_SUMMARY,
            "fields": fields,
            "footer": {"text": "Next summary in 6 hours"},
        }

        return await self._send_webhook(self.webhook_url, {"embeds": [embed]})

    async def post_battery_alert(self, alert: BatteryAlert) -> bool:
        """Post a battery alert embed to Discord."""
        url = self.battery_webhook_url
        if not url:
            return False

        if alert.is_critical:
            title = f"\U0001faab Critical Battery: {alert.device_name}"
            color = COLOR_BATTERY_CRITICAL
        else:
            title = f"\U0001f50b Low Battery: {alert.device_name}"
            color = COLOR_BATTERY_LOW

        embed = {
            "title": title,
            "color": color,
            "fields": [
                {
                    "name": "Battery Level",
                    "value": f"{alert.battery_percent}%",
                    "inline": True,
                },
                {
                    "name": "Device Type",
                    "value": alert.device_type.title(),
                    "inline": True,
                },
            ],
            "timestamp": alert.alert_time.isoformat(),
            "footer": {"text": "Google Find Hub Tracker"},
        }

        return await self._send_webhook(url, {"embeds": [embed]})

    async def post_startup(self, device_count: int) -> bool:
        """Post a service startup message."""
        if not self.webhook_url:
            return False

        embed = {
            "title": "\u2705 Find Hub Tracker Started",
            "color": COLOR_STARTUP,
            "description": f"Tracking **{device_count}** device(s). Polling active.",
            "footer": {"text": "Google Find Hub Tracker"},
        }

        return await self._send_webhook(self.webhook_url, {"embeds": [embed]})

    async def post_shutdown(self) -> bool:
        """Post a service shutdown message."""
        if not self.webhook_url:
            return False

        embed = {
            "title": "\u26d4 Find Hub Tracker Stopped",
            "color": COLOR_SHUTDOWN,
            "description": "Service is shutting down gracefully.",
            "footer": {"text": "Google Find Hub Tracker"},
        }

        return await self._send_webhook(self.webhook_url, {"embeds": [embed]})

    async def post_test(self) -> bool:
        """Send a test message to verify webhook configuration."""
        if not self.webhook_url:
            return False

        embed = {
            "title": "\U0001f9ea Test Message",
            "color": COLOR_LOCATION,
            "description": "Discord webhook is configured correctly!",
            "footer": {"text": "Google Find Hub Tracker"},
        }

        return await self._send_webhook(self.webhook_url, {"embeds": [embed]})

    async def _send_webhook(self, url: str, payload: dict) -> bool:
        """Send a payload to a Discord webhook URL with exponential backoff on 429."""
        max_retries = 3
        for attempt in range(max_retries + 1):
            try:
                resp = await self._client.post(url, json=payload)
                if resp.status_code == 429:
                    retry_after = resp.json().get("retry_after", 2 ** (attempt + 1))
                    log.warning(
                        "discord_rate_limited",
                        retry_after=retry_after,
                        attempt=attempt + 1,
                    )
                    if attempt < max_retries:
                        await asyncio.sleep(retry_after)
                        continue
                    return False
                resp.raise_for_status()
                log.debug("discord_message_sent", status=resp.status_code)
                return True
            except httpx.HTTPError:
                log.exception("discord_webhook_error", attempt=attempt + 1)
                if attempt < max_retries:
                    await asyncio.sleep(2 ** (attempt + 1))
                    continue
                return False
        return False


def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate the great-circle distance between two points in meters."""
    earth_radius = 6_371_000  # meters
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)

    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return earth_radius * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _format_distance(meters: float) -> str:
    """Format a distance in meters to a human-readable string."""
    if meters < 1000:
        return f"{meters:.0f}m"
    return f"{meters / 1000:.1f}km"

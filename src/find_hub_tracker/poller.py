"""Core async polling loop using APScheduler."""

import asyncio
import signal

import structlog
from apscheduler import AsyncScheduler
from apscheduler.triggers.interval import IntervalTrigger

from find_hub_tracker import __version__
from find_hub_tracker.battery import BatteryMonitor
from find_hub_tracker.config import Settings
from find_hub_tracker.db import DatabaseBackend, create_backend
from find_hub_tracker.discord import DiscordPublisher, haversine_distance
from find_hub_tracker.google_fmd import GoogleFindMyDevices
from find_hub_tracker.heartbeat import ping_healthchecks, record_heartbeat
from find_hub_tracker.models import DeviceLocation

log = structlog.get_logger()

SIGNIFICANT_MOVE_METERS = 100.0


class Poller:
    """Polls Google Find Hub for device locations on a schedule."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.db: DatabaseBackend = create_backend(settings)
        self.fmd = GoogleFindMyDevices(auth_dir=str(settings.auth_secrets_path).rsplit("/", 1)[0])
        self.publisher = DiscordPublisher(
            webhook_url=settings.discord_webhook_url,
            battery_webhook_url=settings.battery_webhook_url,
        )
        self.battery_monitor = BatteryMonitor(
            db=self.db,
            publisher=self.publisher,
            low_threshold=settings.battery_low_threshold_percent,
            critical_threshold=settings.battery_critical_threshold_percent,
            wearable_offset=settings.wearable_threshold_offset,
            cooldown_minutes=settings.alert_cooldown_minutes,
        )
        self._shutdown_event = asyncio.Event()
        self._poll_count = 0
        self._error_count = 0

    async def start(self) -> None:
        """Start the polling daemon."""
        await self.db.connect()
        await self.db.migrate()

        log.info(
            "poller_starting",
            poll_interval=self.settings.poll_interval_seconds,
            battery_interval=self.settings.battery_check_interval_seconds,
            summary_interval_hours=self.settings.summary_interval_hours,
            db_backend=self.settings.db_backend,
            devices_filter=self.settings.devices_to_track or "all",
        )

        # Register signal handlers for graceful shutdown
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, self._signal_handler)
            except NotImplementedError:
                signal.signal(sig, lambda s, f: self._signal_handler())

        async with AsyncScheduler() as scheduler:
            # Schedule location polling
            await scheduler.add_schedule(
                self.poll_locations,
                IntervalTrigger(seconds=self.settings.poll_interval_seconds),
                id="location_poll",
            )

            # Schedule battery checks
            await scheduler.add_schedule(
                self.check_batteries,
                IntervalTrigger(seconds=self.settings.battery_check_interval_seconds),
                id="battery_check",
            )

            # Schedule periodic summary
            await scheduler.add_schedule(
                self.post_summary,
                IntervalTrigger(hours=self.settings.summary_interval_hours),
                id="periodic_summary",
            )

            # Schedule history pruning (once daily)
            await scheduler.add_schedule(
                self.prune_history,
                IntervalTrigger(hours=24),
                id="history_prune",
            )

            # Run an immediate poll on startup
            log.info("initial_poll")
            await self.poll_locations()

            # Post startup message
            try:
                devices = await self.fmd.list_devices()
                await self.publisher.post_startup(len(devices))
            except Exception:
                await self.publisher.post_startup(0)

            if not self.settings.healthchecks_ping_url:
                log.warning(
                    "healthchecks_not_configured",
                    message="HEALTHCHECKS_PING_URL not set — no external dead man's switch",
                )

            log.info("poller_running", message="Polling daemon started. Press Ctrl+C to stop.")

            # Wait for shutdown signal
            await self._shutdown_event.wait()

        # Graceful shutdown
        await self.publisher.post_shutdown()
        await self.publisher.close()
        await self.db.close()
        log.info("poller_stopped")

    def _signal_handler(self) -> None:
        """Handle shutdown signals gracefully."""
        log.info("shutdown_requested")
        self._shutdown_event.set()

    async def poll_locations(self) -> None:
        """Execute a single polling cycle: query devices, compare, persist, publish."""
        try:
            device_filter = self.settings.devices_to_track_list or None

            locations = await self.fmd.get_all_locations(device_filter)
            if not locations:
                log.warning("no_locations_returned")
                return

            log.info("poll_cycle", devices_found=len(locations))

            for loc in locations:
                prev = await self.db.get_last_location(loc.device_id)
                await self.db.store_location(loc)

                if _has_moved_significantly(prev, loc):
                    await self.publisher.post_location_update(loc, prev)
                    log.info(
                        "location_updated",
                        device=loc.device_name,
                        lat=loc.latitude,
                        lng=loc.longitude,
                    )
                else:
                    log.debug("location_unchanged", device=loc.device_name)

            # Heartbeat on success
            self._poll_count += 1
            await ping_healthchecks(self.settings.healthchecks_ping_url, success=True)
            await record_heartbeat(
                self.db,
                poll_count=self._poll_count,
                error_count=self._error_count,
                version=__version__,
            )

        except Exception:
            self._error_count += 1
            await ping_healthchecks(self.settings.healthchecks_ping_url, success=False)
            await record_heartbeat(
                self.db,
                poll_count=self._poll_count,
                error_count=self._error_count,
                version=__version__,
            )
            log.exception("poll_cycle_error")

    async def check_batteries(self) -> None:
        """Check battery levels for all tracked devices."""
        try:
            latest = await self.db.get_all_latest()
            if not latest:
                return

            alerts = await self.battery_monitor.check_all(latest)
            if alerts:
                log.info("battery_alerts_sent", count=len(alerts))
        except Exception:
            log.exception("battery_check_error")

    async def post_summary(self) -> None:
        """Post a periodic summary of all device locations to Discord."""
        try:
            latest = await self.db.get_all_latest()
            if latest:
                await self.publisher.post_summary(latest)
                log.info("summary_posted", devices=len(latest))
        except Exception:
            log.exception("summary_error")

    async def prune_history(self) -> None:
        """Prune old location records based on retention settings."""
        try:
            count = await self.db.prune_old_records(self.settings.history_retention_days)
            if count > 0:
                log.info("history_pruned", records_deleted=count)
        except Exception:
            log.exception("prune_error")


def _has_moved_significantly(
    previous: DeviceLocation | None,
    current: DeviceLocation,
) -> bool:
    """Check if a device has moved more than SIGNIFICANT_MOVE_METERS."""
    if previous is None:
        return True

    distance = haversine_distance(
        previous.latitude,
        previous.longitude,
        current.latitude,
        current.longitude,
    )
    return distance > SIGNIFICANT_MOVE_METERS

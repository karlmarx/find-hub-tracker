"""Wrapper around GoogleFindMyTools for querying Google Find Hub devices.

GoogleFindMyTools (https://github.com/leonboe1/GoogleFindMyTools) reverse-engineers
Google's Nova/Spot API to query Find Hub device locations and decrypt E2EE location data.

Auth is handled via a one-time Chrome login that produces an Auth/secrets.json file.
After that, the service runs headlessly.

NOTE: Battery level data is NOT currently supported by GoogleFindMyTools.
The battery_percent and is_charging fields will always be None.
This infrastructure exists so battery monitoring works automatically when
upstream adds support.
"""

import asyncio
import contextlib
import time
from datetime import UTC, datetime
from pathlib import Path

import structlog

from find_hub_tracker.models import DeviceLocation

log = structlog.get_logger()

# Location status mapping from GoogleFindMyTools integer codes
_LOCATION_STATUS_MAP = {
    0: "semantic",
    1: "last_known",
    2: "crowdsourced",
    3: "aggregated",
}


class AuthError(Exception):
    """Raised when Google authentication is missing or invalid."""


class GoogleFindMyDevices:
    """Interface to Google Find Hub via GoogleFindMyTools.

    This class wraps the GoogleFindMyTools library to provide a clean async API
    for listing devices and retrieving their locations.
    """

    def __init__(self, auth_dir: str = "Auth") -> None:
        self.auth_dir = Path(auth_dir)
        self._devices_cache: list[tuple[str, str]] | None = None
        self._cache_time: float = 0
        self._cache_ttl: float = 300
        self._gfmt_available = False
        self._init_gfmt()

    def _init_gfmt(self) -> None:
        """Check if GoogleFindMyTools modules are importable."""
        try:
            import importlib.util

            self._gfmt_available = (
                importlib.util.find_spec("NovaApi") is not None
                and importlib.util.find_spec("ProtoDecoders") is not None
            )
            if self._gfmt_available:
                log.info("googlefindmytools_available")
        except ImportError:
            self._gfmt_available = False

        if not self._gfmt_available:
            log.warning(
                "googlefindmytools_unavailable",
                hint="Ensure GoogleFindMyTools is on sys.path or vendored",
            )

    def _check_auth(self) -> None:
        """Verify that auth secrets exist."""
        secrets_file = self.auth_dir / "secrets.json"
        if not secrets_file.exists():
            raise AuthError(
                f"Auth secrets not found at {secrets_file}. "
                "Run 'find-hub-tracker auth' to authenticate with Google first."
            )

    def _check_available(self) -> None:
        """Verify GoogleFindMyTools is importable."""
        if not self._gfmt_available:
            raise RuntimeError(
                "GoogleFindMyTools is not installed or not on sys.path. "
                "Clone it and add its directory to PYTHONPATH, or vendor the modules."
            )

    async def list_devices(self) -> list[tuple[str, str]]:
        """List all registered Find Hub devices.

        Returns:
            List of (device_name, canonic_id) tuples.
        """
        self._check_available()
        self._check_auth()

        if self._devices_cache and (time.monotonic() - self._cache_time) < self._cache_ttl:
            return self._devices_cache

        devices = await asyncio.to_thread(self._list_devices_sync)
        self._devices_cache = devices
        self._cache_time = time.monotonic()
        log.info("devices_listed", count=len(devices))
        return devices

    def _list_devices_sync(self) -> list[tuple[str, str]]:
        """Synchronous device listing (runs in thread)."""
        from NovaApi.ListDevices.nbe_list_devices import request_device_list
        from ProtoDecoders.decoder import get_canonic_ids, parse_device_list_protobuf

        hex_result = request_device_list()
        device_list = parse_device_list_protobuf(hex_result)
        return get_canonic_ids(device_list)

    async def get_device_location(self, canonic_id: str, device_name: str) -> DeviceLocation | None:
        """Request and retrieve the current location for a device.

        Args:
            canonic_id: The device's canonical ID from list_devices().
            device_name: Human-readable device name.

        Returns:
            DeviceLocation if a location was obtained, None otherwise.
        """
        self._check_available()
        self._check_auth()

        try:
            return await asyncio.to_thread(self._get_location_sync, canonic_id, device_name)
        except Exception:
            log.exception("location_request_failed", device=device_name)
            return None

    def _get_location_sync(self, canonic_id: str, device_name: str) -> DeviceLocation | None:
        """Synchronous location retrieval (runs in thread).

        The upstream function prints locations to stdout. We capture the output
        and parse it. This is fragile but avoids deep modifications to the library.
        """
        import io
        from contextlib import redirect_stdout

        from NovaApi.ExecuteAction.LocateTracker.location_request import (
            get_location_data_for_device,
        )

        captured = io.StringIO()
        try:
            with redirect_stdout(captured):
                get_location_data_for_device(canonic_id, device_name)
        except Exception:
            log.exception("gfmt_location_error", device=device_name)
            return None

        output = captured.getvalue()
        return self._parse_location_output(output, canonic_id, device_name)

    def _parse_location_output(
        self, output: str, canonic_id: str, device_name: str
    ) -> DeviceLocation | None:
        """Parse the console output from GoogleFindMyTools into a DeviceLocation.

        The library prints lines like:
            Latitude: 47.1234567
            Longitude: -122.1234567
            Altitude: 50
            Time: 1711234567
            Accuracy: 25.0
            Status: LAST_KNOWN(1)
            Is own report: True
        """
        lat = lng = accuracy = None
        timestamp = None

        for line in output.splitlines():
            line = line.strip()
            if line.startswith("Latitude:"):
                with contextlib.suppress(ValueError):
                    lat = float(line.split(":", 1)[1].strip())
            elif line.startswith("Longitude:"):
                with contextlib.suppress(ValueError):
                    lng = float(line.split(":", 1)[1].strip())
            elif line.startswith("Time:"):
                try:
                    unix_ts = int(line.split(":", 1)[1].strip())
                    timestamp = datetime.fromtimestamp(unix_ts, tz=UTC)
                except ValueError:
                    pass
            elif line.startswith("Accuracy:"):
                with contextlib.suppress(ValueError):
                    accuracy = float(line.split(":", 1)[1].strip())

        if lat is None or lng is None:
            log.warning("location_parse_failed", device=device_name, output=output[:200])
            return None

        now = datetime.now(UTC)
        return DeviceLocation(
            device_id=canonic_id,
            device_name=device_name,
            device_type="unknown",
            latitude=lat,
            longitude=lng,
            accuracy_meters=accuracy,
            timestamp=timestamp or now,
            polled_at=now,
            battery_percent=None,
            is_charging=None,
        )

    async def get_all_locations(
        self, device_filter: list[str] | None = None
    ) -> list[DeviceLocation]:
        """Get current locations for all (or filtered) devices.

        Args:
            device_filter: Optional list of device names to track.
                          Empty list or None means track all.

        Returns:
            List of DeviceLocation objects for devices that returned data.
        """
        devices = await self.list_devices()

        if device_filter:
            filter_lower = {n.lower() for n in device_filter}
            devices = [(name, cid) for name, cid in devices if name.lower() in filter_lower]

        locations = []
        for device_name, canonic_id in devices:
            loc = await self.get_device_location(canonic_id, device_name)
            if loc:
                locations.append(loc)

        return locations

    async def authenticate(self) -> None:
        """Run the one-time authentication flow (requires Chrome)."""
        self._check_available()
        await asyncio.to_thread(self._authenticate_sync)

    def _authenticate_sync(self) -> None:
        """Synchronous auth flow."""
        from Auth.auth_flow import request_oauth_account_token_flow

        request_oauth_account_token_flow()
        log.info("authentication_complete")

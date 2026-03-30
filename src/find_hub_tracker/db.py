"""Database persistence layer with Postgres (primary) and SQLite (fallback) backends."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Protocol

import structlog

from find_hub_tracker.models import BatteryAlert, DeviceInfo, DeviceLocation

log = structlog.get_logger()

# Postgres SQL (also used by SQLite with minor tweaks in the SQLite backend)
POSTGRES_SCHEMA = """
CREATE TABLE IF NOT EXISTS devices (
    device_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    device_type TEXT NOT NULL DEFAULT 'unknown',
    model TEXT,
    first_seen TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_seen TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS device_locations (
    id BIGSERIAL PRIMARY KEY,
    device_id TEXT NOT NULL REFERENCES devices(device_id),
    device_name TEXT NOT NULL,
    device_type TEXT NOT NULL,
    latitude DOUBLE PRECISION NOT NULL,
    longitude DOUBLE PRECISION NOT NULL,
    accuracy_meters REAL,
    address TEXT,
    battery_percent INTEGER,
    is_charging BOOLEAN,
    google_timestamp TIMESTAMPTZ,
    polled_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_locations_device_polled
    ON device_locations(device_id, polled_at DESC);

CREATE INDEX IF NOT EXISTS idx_locations_polled
    ON device_locations(polled_at DESC);

CREATE TABLE IF NOT EXISTS battery_alerts (
    id BIGSERIAL PRIMARY KEY,
    device_id TEXT NOT NULL REFERENCES devices(device_id),
    device_name TEXT NOT NULL,
    device_type TEXT NOT NULL,
    battery_percent INTEGER NOT NULL,
    is_critical BOOLEAN NOT NULL DEFAULT FALSE,
    alerted_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_alerts_device_time
    ON battery_alerts(device_id, alerted_at DESC);

CREATE TABLE IF NOT EXISTS service_heartbeats (
    service_name TEXT NOT NULL,
    host TEXT NOT NULL,
    last_heartbeat TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    poll_count INTEGER NOT NULL DEFAULT 0,
    error_count INTEGER NOT NULL DEFAULT 0,
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    version TEXT,
    PRIMARY KEY (service_name, host)
);
"""

SQLITE_SCHEMA = """
CREATE TABLE IF NOT EXISTS devices (
    device_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    device_type TEXT NOT NULL DEFAULT 'unknown',
    model TEXT,
    first_seen TEXT NOT NULL DEFAULT (datetime('now')),
    last_seen TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS device_locations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id TEXT NOT NULL REFERENCES devices(device_id),
    device_name TEXT NOT NULL,
    device_type TEXT NOT NULL,
    latitude REAL NOT NULL,
    longitude REAL NOT NULL,
    accuracy_meters REAL,
    address TEXT,
    battery_percent INTEGER,
    is_charging INTEGER,
    google_timestamp TEXT,
    polled_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_locations_device_polled
    ON device_locations(device_id, polled_at DESC);

CREATE INDEX IF NOT EXISTS idx_locations_polled
    ON device_locations(polled_at DESC);

CREATE TABLE IF NOT EXISTS battery_alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id TEXT NOT NULL REFERENCES devices(device_id),
    device_name TEXT NOT NULL,
    device_type TEXT NOT NULL,
    battery_percent INTEGER NOT NULL,
    is_critical INTEGER NOT NULL DEFAULT 0,
    alerted_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_alerts_device_time
    ON battery_alerts(device_id, alerted_at DESC);

CREATE TABLE IF NOT EXISTS service_heartbeats (
    service_name TEXT NOT NULL,
    host TEXT NOT NULL,
    last_heartbeat TEXT NOT NULL DEFAULT (datetime('now')),
    poll_count INTEGER NOT NULL DEFAULT 0,
    error_count INTEGER NOT NULL DEFAULT 0,
    started_at TEXT NOT NULL DEFAULT (datetime('now')),
    version TEXT,
    PRIMARY KEY (service_name, host)
);
"""


class DatabaseBackend(Protocol):
    """Common interface for database backends."""

    async def connect(self) -> None: ...
    async def close(self) -> None: ...
    async def migrate(self) -> None: ...
    async def store_location(self, location: DeviceLocation) -> None: ...
    async def get_last_location(self, device_id: str) -> DeviceLocation | None: ...
    async def get_all_latest(self) -> list[DeviceLocation]: ...
    async def get_device_history(
        self, device_id: str, start: datetime, end: datetime
    ) -> list[DeviceLocation]: ...
    async def store_alert(self, alert: BatteryAlert) -> None: ...
    async def get_last_alert(self, device_id: str) -> BatteryAlert | None: ...
    async def upsert_device(self, device: DeviceInfo) -> None: ...
    async def prune_old_records(self, days: int) -> int: ...
    async def get_all_devices(self) -> list[DeviceInfo]: ...
    async def upsert_heartbeat(
        self,
        service_name: str,
        host: str,
        poll_count: int,
        error_count: int,
        version: str | None,
    ) -> None: ...
    async def get_heartbeat(self, service_name: str, host: str) -> dict | None: ...
    async def export_locations(
        self, device_id: str | None = None, days: int | None = None
    ) -> list[dict]: ...


class PostgresBackend:
    """Postgres backend using asyncpg connection pool."""

    def __init__(self, database_url: str) -> None:
        self.database_url = database_url
        self._pool = None

    async def connect(self) -> None:
        """Create the connection pool."""
        import asyncpg

        self._pool = await asyncpg.create_pool(self.database_url, min_size=1, max_size=5)
        log.info("postgres_connected", url=self.database_url.split("@")[-1])

    async def close(self) -> None:
        """Close the connection pool."""
        if self._pool:
            await self._pool.close()
            self._pool = None

    @property
    def pool(self):
        if self._pool is None:
            raise RuntimeError("Database not connected. Call connect() first.")
        return self._pool

    async def migrate(self) -> None:
        """Run schema migrations."""
        async with self.pool.acquire() as conn:
            await conn.execute(POSTGRES_SCHEMA)
        log.info("postgres_migrated")

    async def upsert_device(self, device: DeviceInfo) -> None:
        """Insert or update a device record."""
        async with self.pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO devices (device_id, name, device_type, model, first_seen, last_seen)
                   VALUES ($1, $2, $3, $4, NOW(), NOW())
                   ON CONFLICT (device_id) DO UPDATE
                   SET name = $2, device_type = $3, model = $4, last_seen = NOW()""",
                device.device_id,
                device.name,
                device.device_type,
                device.model,
            )

    async def store_location(self, location: DeviceLocation) -> None:
        """Insert a location record."""
        # Ensure device exists
        await self.upsert_device(
            DeviceInfo(
                device_id=location.device_id,
                name=location.device_name,
                device_type=location.device_type,
            )
        )
        async with self.pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO device_locations
                   (device_id, device_name, device_type, latitude, longitude,
                    accuracy_meters, address, battery_percent, is_charging,
                    google_timestamp, polled_at)
                   VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)""",
                location.device_id,
                location.device_name,
                location.device_type,
                location.latitude,
                location.longitude,
                location.accuracy_meters,
                location.address,
                location.battery_percent,
                location.is_charging,
                location.timestamp,
                location.polled_at,
            )

    async def get_last_location(self, device_id: str) -> DeviceLocation | None:
        """Get the most recent location for a device."""
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                """SELECT * FROM device_locations
                   WHERE device_id = $1
                   ORDER BY polled_at DESC LIMIT 1""",
                device_id,
            )
            if row is None:
                return None
            return _pg_row_to_location(row)

    async def get_all_latest(self) -> list[DeviceLocation]:
        """Get the latest location for every tracked device."""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT DISTINCT ON (device_id) *
                   FROM device_locations
                   ORDER BY device_id, polled_at DESC"""
            )
            return [_pg_row_to_location(r) for r in rows]

    async def get_device_history(
        self, device_id: str, start: datetime, end: datetime
    ) -> list[DeviceLocation]:
        """Get location history for a device in a time range."""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT * FROM device_locations
                   WHERE device_id = $1 AND polled_at >= $2 AND polled_at <= $3
                   ORDER BY polled_at DESC""",
                device_id,
                start,
                end,
            )
            return [_pg_row_to_location(r) for r in rows]

    async def store_alert(self, alert: BatteryAlert) -> None:
        """Insert a battery alert record."""
        async with self.pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO battery_alerts
                   (device_id, device_name, device_type, battery_percent, is_critical, alerted_at)
                   VALUES ($1, $2, $3, $4, $5, $6)""",
                alert.device_id,
                alert.device_name,
                alert.device_type,
                alert.battery_percent,
                alert.is_critical,
                alert.alert_time,
            )

    async def get_last_alert(self, device_id: str) -> BatteryAlert | None:
        """Get the most recent battery alert for a device."""
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                """SELECT * FROM battery_alerts
                   WHERE device_id = $1
                   ORDER BY alerted_at DESC LIMIT 1""",
                device_id,
            )
            if row is None:
                return None
            return BatteryAlert(
                device_id=row["device_id"],
                device_name=row["device_name"],
                device_type=row["device_type"],
                battery_percent=row["battery_percent"],
                is_critical=row["is_critical"],
                alert_time=row["alerted_at"],
            )

    async def prune_old_records(self, days: int) -> int:
        """Delete location records older than the given number of days."""
        cutoff = datetime.now(UTC) - timedelta(days=days)
        async with self.pool.acquire() as conn:
            result = await conn.execute("DELETE FROM device_locations WHERE polled_at < $1", cutoff)
            count = int(result.split()[-1])
            log.info("records_pruned", count=count, older_than_days=days)
            return count

    async def upsert_heartbeat(
        self,
        service_name: str,
        host: str,
        poll_count: int,
        error_count: int,
        version: str | None,
    ) -> None:
        """Insert or update a heartbeat record."""
        async with self.pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO service_heartbeats
                   (service_name, host, last_heartbeat, poll_count,
                    error_count, started_at, version)
                   VALUES ($1, $2, NOW(), $3, $4, NOW(), $5)
                   ON CONFLICT (service_name, host) DO UPDATE
                   SET last_heartbeat = NOW(), poll_count = $3,
                       error_count = $4, version = $5""",
                service_name,
                host,
                poll_count,
                error_count,
                version,
            )

    async def get_heartbeat(self, service_name: str, host: str) -> dict | None:
        """Get heartbeat record for a service/host pair."""
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                """SELECT * FROM service_heartbeats
                   WHERE service_name = $1 AND host = $2""",
                service_name,
                host,
            )
            return dict(row) if row else None

    async def get_all_devices(self) -> list[DeviceInfo]:
        """Get all registered devices."""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("SELECT * FROM devices ORDER BY name")
            return [
                DeviceInfo(
                    device_id=r["device_id"],
                    name=r["name"],
                    device_type=r["device_type"],
                    model=r["model"],
                )
                for r in rows
            ]

    async def export_locations(
        self, device_id: str | None = None, days: int | None = None
    ) -> list[dict]:
        """Export location records as dicts."""
        conditions = []
        params = []
        idx = 1

        if device_id:
            conditions.append(f"device_id = ${idx}")
            params.append(device_id)
            idx += 1
        if days:
            cutoff = datetime.now(UTC) - timedelta(days=days)
            conditions.append(f"polled_at >= ${idx}")
            params.append(cutoff)

        where = f" WHERE {' AND '.join(conditions)}" if conditions else ""
        query = f"SELECT * FROM device_locations{where} ORDER BY polled_at"

        async with self.pool.acquire() as conn:
            rows = await conn.fetch(query, *params)
            return [dict(r) for r in rows]


class SQLiteBackend:
    """SQLite backend using aiosqlite."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self._db = None

    async def connect(self) -> None:
        """Open the database connection."""
        import aiosqlite

        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(str(self.db_path))
        self._db.row_factory = aiosqlite.Row
        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._db.execute("PRAGMA foreign_keys=ON")
        log.info("sqlite_connected", path=str(self.db_path))

    async def close(self) -> None:
        """Close the database connection."""
        if self._db:
            await self._db.close()
            self._db = None

    @property
    def db(self):
        if self._db is None:
            raise RuntimeError("Database not connected. Call connect() first.")
        return self._db

    async def migrate(self) -> None:
        """Run schema migrations."""
        await self.db.executescript(SQLITE_SCHEMA)
        await self.db.commit()
        log.info("sqlite_migrated")

    async def upsert_device(self, device: DeviceInfo) -> None:
        """Insert or update a device record."""
        now = datetime.now(UTC).isoformat()
        await self.db.execute(
            """INSERT INTO devices (device_id, name, device_type, model, first_seen, last_seen)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT (device_id) DO UPDATE
               SET name = ?, device_type = ?, model = ?, last_seen = ?""",
            (
                device.device_id,
                device.name,
                device.device_type,
                device.model,
                now,
                now,
                device.name,
                device.device_type,
                device.model,
                now,
            ),
        )
        await self.db.commit()

    async def store_location(self, location: DeviceLocation) -> None:
        """Insert a location record."""
        await self.upsert_device(
            DeviceInfo(
                device_id=location.device_id,
                name=location.device_name,
                device_type=location.device_type,
            )
        )
        await self.db.execute(
            """INSERT INTO device_locations
               (device_id, device_name, device_type, latitude, longitude,
                accuracy_meters, address, battery_percent, is_charging,
                google_timestamp, polled_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                location.device_id,
                location.device_name,
                location.device_type,
                location.latitude,
                location.longitude,
                location.accuracy_meters,
                location.address,
                location.battery_percent,
                1 if location.is_charging else 0 if location.is_charging is not None else None,
                location.timestamp.isoformat(),
                location.polled_at.isoformat(),
            ),
        )
        await self.db.commit()

    async def get_last_location(self, device_id: str) -> DeviceLocation | None:
        """Get the most recent location for a device."""
        async with self.db.execute(
            """SELECT * FROM device_locations
               WHERE device_id = ?
               ORDER BY polled_at DESC LIMIT 1""",
            (device_id,),
        ) as cursor:
            row = await cursor.fetchone()
            if row is None:
                return None
            return _sqlite_row_to_location(row)

    async def get_all_latest(self) -> list[DeviceLocation]:
        """Get the latest location for every tracked device."""
        async with self.db.execute(
            """SELECT dl.* FROM device_locations dl
               INNER JOIN (
                   SELECT device_id, MAX(polled_at) as max_ts
                   FROM device_locations GROUP BY device_id
               ) latest ON dl.device_id = latest.device_id
                       AND dl.polled_at = latest.max_ts
               ORDER BY dl.device_name"""
        ) as cursor:
            rows = await cursor.fetchall()
            return [_sqlite_row_to_location(r) for r in rows]

    async def get_device_history(
        self, device_id: str, start: datetime, end: datetime
    ) -> list[DeviceLocation]:
        """Get location history for a device in a time range."""
        async with self.db.execute(
            """SELECT * FROM device_locations
               WHERE device_id = ? AND polled_at >= ? AND polled_at <= ?
               ORDER BY polled_at DESC""",
            (device_id, start.isoformat(), end.isoformat()),
        ) as cursor:
            rows = await cursor.fetchall()
            return [_sqlite_row_to_location(r) for r in rows]

    async def store_alert(self, alert: BatteryAlert) -> None:
        """Insert a battery alert record."""
        await self.db.execute(
            """INSERT INTO battery_alerts
               (device_id, device_name, device_type, battery_percent, is_critical, alerted_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                alert.device_id,
                alert.device_name,
                alert.device_type,
                alert.battery_percent,
                1 if alert.is_critical else 0,
                alert.alert_time.isoformat(),
            ),
        )
        await self.db.commit()

    async def get_last_alert(self, device_id: str) -> BatteryAlert | None:
        """Get the most recent battery alert for a device."""
        async with self.db.execute(
            """SELECT * FROM battery_alerts
               WHERE device_id = ?
               ORDER BY alerted_at DESC LIMIT 1""",
            (device_id,),
        ) as cursor:
            row = await cursor.fetchone()
            if row is None:
                return None
            return BatteryAlert(
                device_id=row["device_id"],
                device_name=row["device_name"],
                device_type=row["device_type"],
                battery_percent=row["battery_percent"],
                is_critical=bool(row["is_critical"]),
                alert_time=datetime.fromisoformat(row["alerted_at"]),
            )

    async def prune_old_records(self, days: int) -> int:
        """Delete location records older than the given number of days."""
        cutoff = (datetime.now(UTC) - timedelta(days=days)).isoformat()
        cursor = await self.db.execute(
            "DELETE FROM device_locations WHERE polled_at < ?", (cutoff,)
        )
        await self.db.commit()
        count = cursor.rowcount
        log.info("records_pruned", count=count, older_than_days=days)
        return count

    async def upsert_heartbeat(
        self,
        service_name: str,
        host: str,
        poll_count: int,
        error_count: int,
        version: str | None,
    ) -> None:
        """Insert or update a heartbeat record."""
        now = datetime.now(UTC).isoformat()
        await self.db.execute(
            """INSERT INTO service_heartbeats
               (service_name, host, last_heartbeat, poll_count, error_count, started_at, version)
               VALUES (?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT (service_name, host) DO UPDATE
               SET last_heartbeat = ?, poll_count = ?, error_count = ?, version = ?""",
            (
                service_name,
                host,
                now,
                poll_count,
                error_count,
                now,
                version,
                now,
                poll_count,
                error_count,
                version,
            ),
        )
        await self.db.commit()

    async def get_heartbeat(self, service_name: str, host: str) -> dict | None:
        """Get heartbeat record for a service/host pair."""
        async with self.db.execute(
            """SELECT * FROM service_heartbeats
               WHERE service_name = ? AND host = ?""",
            (service_name, host),
        ) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None

    async def get_all_devices(self) -> list[DeviceInfo]:
        """Get all registered devices."""
        async with self.db.execute("SELECT * FROM devices ORDER BY name") as cursor:
            rows = await cursor.fetchall()
            return [
                DeviceInfo(
                    device_id=r["device_id"],
                    name=r["name"],
                    device_type=r["device_type"],
                    model=r["model"],
                )
                for r in rows
            ]

    async def export_locations(
        self, device_id: str | None = None, days: int | None = None
    ) -> list[dict]:
        """Export location records as dicts."""
        conditions = []
        params: list = []

        if device_id:
            conditions.append("device_id = ?")
            params.append(device_id)
        if days:
            cutoff = (datetime.now(UTC) - timedelta(days=days)).isoformat()
            conditions.append("polled_at >= ?")
            params.append(cutoff)

        where = f" WHERE {' AND '.join(conditions)}" if conditions else ""
        query = f"SELECT * FROM device_locations{where} ORDER BY polled_at"

        async with self.db.execute(query, params) as cursor:
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]


def create_backend(settings) -> DatabaseBackend:
    """Create the appropriate database backend from settings."""
    if settings.db_backend == "postgres":
        return PostgresBackend(settings.database_url)  # type: ignore[return-value]
    return SQLiteBackend(settings.sqlite_path_resolved)  # type: ignore[return-value]


def _pg_row_to_location(row) -> DeviceLocation:
    """Convert a Postgres row to a DeviceLocation."""
    return DeviceLocation(
        device_id=row["device_id"],
        device_name=row["device_name"],
        device_type=row["device_type"],
        latitude=row["latitude"],
        longitude=row["longitude"],
        accuracy_meters=row["accuracy_meters"],
        address=row["address"],
        timestamp=row["google_timestamp"] or row["polled_at"],
        polled_at=row["polled_at"],
        battery_percent=row["battery_percent"],
        is_charging=row["is_charging"],
    )


def _sqlite_row_to_location(row) -> DeviceLocation:
    """Convert a SQLite row to a DeviceLocation."""
    is_charging = row["is_charging"]
    if is_charging is not None:
        is_charging = bool(is_charging)

    google_ts = row["google_timestamp"]
    polled_at = row["polled_at"]

    return DeviceLocation(
        device_id=row["device_id"],
        device_name=row["device_name"],
        device_type=row["device_type"],
        latitude=row["latitude"],
        longitude=row["longitude"],
        accuracy_meters=row["accuracy_meters"],
        address=row["address"],
        timestamp=(
            datetime.fromisoformat(google_ts) if google_ts else datetime.fromisoformat(polled_at)
        ),
        polled_at=datetime.fromisoformat(polled_at),
        battery_percent=row["battery_percent"],
        is_charging=is_charging,
    )

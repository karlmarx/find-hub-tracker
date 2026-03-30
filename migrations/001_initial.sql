-- Centralized automation database — find_hub_tracker schema
-- Other automation services will add their own tables to this database

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

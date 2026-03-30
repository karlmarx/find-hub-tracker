# Claude Code Prompt: Google Find Hub Device Tracker with Discord Integration

## Project Overview

Build a Python service called `find-hub-tracker` that polls Google Find Hub (formerly Find My Device) for device locations and battery levels, stores a running history in a database, and publishes updates to Discord via webhooks. The service should also send battery-low alerts for wearables (Pixel Watch, Pixel Buds).

This uses the open-source `GoogleFindMyTools` library (https://github.com/leonboe1/GoogleFindMyTools) which has reverse-engineered Google's Spot API (gRPC + Firebase Cloud Messaging) to query Find Hub device locations and decrypt E2EE location data. Auth is handled via a one-time Chrome login that produces an `Auth/secrets.json` file — after that, the service runs headlessly.

**Deployment strategy:** Local-first development and testing, then deploy to Oracle Cloud Free Tier ARM VM for always-on operation.

## Repository Setup

- Create a new GitHub repo: `karlmarx/find-hub-tracker`
- Initialize with `uv init` targeting Python 3.14
- Use `uv` for all package management (no pip, no poetry)
- Include PEP 723 inline metadata where applicable for any standalone scripts
- Set up `.gitignore` BEFORE any commits — include: `__pycache__/`, `.venv/`, `*.pyc`, `node_modules/`, `Auth/`, `secrets.json`, `*.db`, `.env`, `dist/`, `*.egg-info/`, `data/`
- The `Auth/` directory and `.env` must NEVER be committed — they contain Google session tokens and Discord webhook URLs
- Always run `git diff --stat` before committing
- Use `ruff` for linting and formatting
- Google-style docstrings throughout

## Project Structure

```
find-hub-tracker/
├── pyproject.toml
├── .gitignore
├── .env.example              # Template with placeholder values
├── README.md                 # Setup instructions, architecture overview
├── docker-compose.yml        # Local dev: app + Postgres
├── Dockerfile                # For containerized deployment
├── src/
│   └── find_hub_tracker/
│       ├── __init__.py
│       ├── main.py           # Entry point — CLI with start/status/history commands
│       ├── config.py         # Pydantic Settings loading from .env
│       ├── poller.py         # Core polling loop (async)
│       ├── google_fmd.py     # Wrapper around GoogleFindMyTools for querying devices
│       ├── db.py             # Database persistence layer (asyncpg for Postgres, aiosqlite fallback)
│       ├── discord.py        # Discord webhook publisher
│       ├── battery.py        # Battery monitoring and alert logic
│       └── models.py         # Pydantic models for DeviceLocation, BatteryStatus, etc.
├── migrations/
│   └── 001_initial.sql       # SQL migration for creating tables
├── scripts/
│   ├── authenticate.py       # One-time auth helper — wraps GoogleFindMyTools main.py auth flow
│   └── export_history.py     # Export location history to CSV/JSON
├── deploy/
│   ├── oracle-cloud-setup.md # Step-by-step Oracle Cloud Free Tier provisioning guide
│   ├── find-hub-tracker.service  # systemd unit file
│   └── tailscale-setup.md    # Notes on adding the VM to Tailscale mesh
├── tests/
│   └── ...
└── Auth/                     # Created by auth flow, GITIGNORED
    └── secrets.json
```

## Dependencies

In `pyproject.toml`, include:
- `asyncpg` — async Postgres driver (primary)
- `aiosqlite` — async SQLite driver (fallback/local dev without Docker)
- `httpx` — async HTTP client for Discord webhooks
- `pydantic` >= 2.0 — data models
- `pydantic-settings` — .env config loading
- `rich` — CLI output formatting
- `click` — CLI framework
- `apscheduler` >= 4.0 — scheduling (use async scheduler)
- `structlog` — structured logging

GoogleFindMyTools is NOT on PyPI. Clone it as a git dependency or vendor it. Check if it can be added as a `uv` git dependency:
```toml
[tool.uv.sources]
googlefindmytools = { git = "https://github.com/leonboe1/GoogleFindMyTools.git" }
```
If that doesn't work cleanly (it's not a proper Python package), vendor the relevant modules into `src/find_hub_tracker/vendor/` and document the version/commit pinned. The key modules needed are the Spot API client, the FCM listener, and the crypto/decryption utilities.

## Configuration (.env)

```env
# Database — set DB_BACKEND to "postgres" or "sqlite"
DB_BACKEND=postgres
DATABASE_URL=postgresql://tracker:tracker@localhost:5432/find_hub_tracker
SQLITE_PATH=./data/tracker_history.db  # Used only if DB_BACKEND=sqlite

# Discord
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/...
DISCORD_BATTERY_WEBHOOK_URL=https://discord.com/api/webhooks/...  # Optional separate channel for alerts

# Polling
POLL_INTERVAL_SECONDS=300          # 5 minutes default — don't go lower to avoid Google bans
BATTERY_CHECK_INTERVAL_SECONDS=900 # 15 minutes
BATTERY_LOW_THRESHOLD_PERCENT=20   # Alert when below this
BATTERY_CRITICAL_THRESHOLD_PERCENT=10

# Alerts
ALERT_COOLDOWN_MINUTES=60          # Don't spam — re-alert only after this cooldown per device

# History
HISTORY_RETENTION_DAYS=90          # Auto-prune entries older than this

# Auth
AUTH_SECRETS_PATH=./Auth/secrets.json

# Logging
LOG_LEVEL=INFO
```

## Database Design

### Why Postgres (with SQLite fallback)

This project is the first service in a planned centralized automation platform. Postgres is the primary backend because:
- Future automation services (Amex claims, scheduling, etc.) will share the same database
- Concurrent access from multiple services is a Postgres strength and a SQLite weakness
- Postgres runs great in Docker locally and on Oracle Cloud Free Tier
- The SQLite fallback exists for quick local testing without Docker — same schema, just swap the driver

### docker-compose.yml (local dev)

```yaml
services:
  postgres:
    image: postgres:17
    environment:
      POSTGRES_USER: tracker
      POSTGRES_PASSWORD: tracker
      POSTGRES_DB: find_hub_tracker
    ports:
      - "5432:5432"
    volumes:
      - pgdata:/var/lib/postgresql/data
      - ./migrations:/docker-entrypoint-initdb.d

  # The app itself can run outside Docker during dev (just `uv run`)
  # or be containerized for deployment:
  tracker:
    build: .
    env_file: .env
    depends_on:
      - postgres
    volumes:
      - ./Auth:/app/Auth:ro  # Mount secrets read-only
    profiles:
      - deploy  # Only start with `docker compose --profile deploy up`

volumes:
  pgdata:
```

### Schema (migrations/001_initial.sql)

```sql
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
```

The `db.py` module should abstract over both backends with a common interface:

```python
class DatabaseBackend(Protocol):
    async def store_location(self, location: DeviceLocation) -> None: ...
    async def get_last_location(self, device_id: str) -> DeviceLocation | None: ...
    async def get_all_latest(self) -> list[DeviceLocation]: ...
    async def get_device_history(self, device_id: str, start: datetime, end: datetime) -> list[DeviceLocation]: ...
    async def store_alert(self, alert: BatteryAlert) -> None: ...
    async def get_last_alert(self, device_id: str) -> BatteryAlert | None: ...
    async def upsert_device(self, device: DeviceInfo) -> None: ...
    async def prune_old_records(self, days: int) -> int: ...

class PostgresBackend(DatabaseBackend): ...   # Uses asyncpg
class SQLiteBackend(DatabaseBackend): ...     # Uses aiosqlite
```

Select backend based on `DB_BACKEND` config value. Both implementations must pass the same tests.

## Core Components — Detailed Specs

### 1. `config.py` — Configuration

Use `pydantic-settings` `BaseSettings` with `.env` file support. Validate all values. Expose a singleton `get_settings()`.

### 2. `models.py` — Data Models

```python
class DeviceInfo(BaseModel):
    device_id: str
    name: str
    device_type: str  # "phone", "watch", "buds", "tracker", "tablet", "unknown"
    model: str | None = None

class DeviceLocation(BaseModel):
    device_id: str
    device_name: str
    device_type: str
    latitude: float
    longitude: float
    accuracy_meters: float | None = None
    timestamp: datetime  # When Google reported the location
    polled_at: datetime  # When we queried for it
    address: str | None = None
    battery_percent: int | None = None
    is_charging: bool | None = None

class BatteryAlert(BaseModel):
    device_id: str
    device_name: str
    device_type: str
    battery_percent: int
    is_critical: bool
    alert_time: datetime
```

### 3. `google_fmd.py` — Google Find Hub Wrapper

This is the integration layer with GoogleFindMyTools. Key responsibilities:

- Load `secrets.json` for authentication
- Query all registered devices and their last known locations
- Extract battery levels where available (Pixel Watch, Pixel Buds, phones all report battery)
- Handle the E2EE decryption of location reports
- Handle FCM (Firebase Cloud Messaging) connection for push-based location updates if supported
- Graceful error handling — Google's unofficial API can return errors, rate limit, or change format
- Return normalized `DeviceLocation` and `BatteryStatus` objects

Important: Study GoogleFindMyTools' `main.py` and the Spot API module carefully to understand how it queries devices. The Traccar fork (https://github.com/traccar/google-find-hub-sync) has a `microservice.py` that shows how to wrap it as a service — reference that pattern.

### 4. `poller.py` — Core Polling Loop

Use `apscheduler` AsyncScheduler with two jobs:

**Location Poll Job** (every `POLL_INTERVAL_SECONDS`):
1. Query all devices via `google_fmd.py`
2. For each device, compare with last stored location
3. Store new location in the database (always, even if unchanged — we want a time series)
4. If device has moved significantly (>100m from last position), post to Discord
5. Post a periodic summary to Discord every 6 hours regardless of movement (configurable)

**Battery Check Job** (every `BATTERY_CHECK_INTERVAL_SECONDS`):
1. Check battery levels for all devices
2. If any device is below `BATTERY_LOW_THRESHOLD_PERCENT`, trigger alert
3. If below `BATTERY_CRITICAL_THRESHOLD_PERCENT`, trigger critical alert
4. Respect `ALERT_COOLDOWN_MINUTES` — don't re-alert for the same device within the cooldown window
5. Store alert history in database so we can track cooldowns across restarts

### 5. `db.py` — Database Persistence

Implement `PostgresBackend` and `SQLiteBackend` behind the `DatabaseBackend` protocol.

Both must support:
- Auto-migration on startup (run SQL migrations if tables don't exist)
- `store_location()` / `get_last_location()` / `get_all_latest()` / `get_device_history()`
- `store_alert()` / `get_last_alert()` — for cooldown checking
- `upsert_device()` — update device registry
- `prune_old_records()` — delete records older than `HISTORY_RETENTION_DAYS`

The Postgres backend uses `asyncpg` connection pool. The SQLite backend uses `aiosqlite`. Factory function selects based on config.

### 6. `discord.py` — Discord Webhook Publisher

Use `httpx` async client. Format messages as Discord embeds for clean presentation.

**Location Update Embed:**
- Color: Blue
- Title: "📍 {device_name} moved"
- Fields: New Location (with Google Maps link), Distance from last, Battery (if available), Last Updated
- Footer: timestamp
- Google Maps link format: `https://www.google.com/maps?q={lat},{lon}`

**Periodic Summary Embed:**
- Color: Green
- Title: "📊 Device Location Summary"
- One field per device showing: last known location (Google Maps link), battery %, last updated time
- Footer: "Next summary in 6 hours"

**Battery Low Alert Embed:**
- Color: Orange (low) / Red (critical)
- Title: "🔋 Low Battery: {device_name}" or "🪫 Critical Battery: {device_name}"
- Fields: Battery %, Device Type, Last Known Location
- Mention: Include `@here` for critical alerts if desired (make configurable)

**Startup/Shutdown Messages:**
- Post a message when service starts (with device count) and when it cleanly shuts down

Handle Discord rate limits (429) with exponential backoff. Log but don't crash on webhook failures.

### 7. `battery.py` — Battery Monitoring

- `check_batteries(devices: list[DeviceLocation]) -> list[BatteryAlert]`
- Filter to only devices that report battery (phones, watches, buds — not dumb trackers)
- Compare against thresholds
- Check cooldowns via `db.get_last_alert()`
- Return list of alerts to fire
- Special handling: Pixel Watch and Pixel Buds are the priority devices for battery alerts. If device_type can be determined as "watch" or "buds", lower the alert threshold by 5% (they die faster and are more annoying to charge). Make this configurable.

### 8. `main.py` — CLI Entry Point

Use `click` for CLI:

```
find-hub-tracker start            # Start the polling service (foreground)
find-hub-tracker status            # Show all devices and their last known locations (table via Rich)
find-hub-tracker history <device> [--days 7]  # Show location history for a device
find-hub-tracker devices           # List all known devices with types and battery
find-hub-tracker test-discord      # Send a test message to verify webhook config
find-hub-tracker auth              # Run the GoogleFindMyTools authentication flow
find-hub-tracker db-migrate        # Run pending migrations
find-hub-tracker db-prune          # Manually prune old records
```

### 9. `scripts/authenticate.py`

Standalone script that walks the user through the GoogleFindMyTools Chrome-based auth flow:
1. Check Chrome is installed
2. Run the auth sequence
3. Verify `secrets.json` was created
4. List discovered devices
5. Print next steps

Include PEP 723 inline metadata.

### 10. `scripts/export_history.py`

Export location history from the database to CSV or JSON. Include PEP 723 inline metadata.

```
uv run scripts/export_history.py --format csv --device "Pixel 9 Pro Fold" --days 30 --output locations.csv
```

## Deployment

### Local Development

1. `docker compose up postgres` — start Postgres
2. `cp .env.example .env` — configure
3. `uv run find-hub-tracker db-migrate` — create tables
4. `uv run find-hub-tracker auth` — one-time Chrome auth
5. `uv run find-hub-tracker start` — run the poller

For quick testing without Docker:
1. Set `DB_BACKEND=sqlite` in `.env`
2. Skip the docker compose step — SQLite file created automatically

### Oracle Cloud Deployment (deploy/ directory)

Create `deploy/oracle-cloud-setup.md` with step-by-step instructions:
1. Sign up for Oracle Cloud Free Tier
2. Provision Ampere A1 VM (1 OCPU, 4GB RAM — well within always-free limits)
3. Install Docker + Docker Compose on the ARM VM
4. Install Tailscale and join the mesh (for easy SSH from anywhere)
5. Clone repo, copy `Auth/secrets.json` from local machine
6. `docker compose --profile deploy up -d`
7. Verify Discord messages are flowing

Create `deploy/find-hub-tracker.service` — systemd unit file for running without Docker:
```ini
[Unit]
Description=Find Hub Device Tracker
After=network-online.target postgresql.service
Wants=network-online.target

[Service]
Type=simple
User=tracker
WorkingDirectory=/opt/find-hub-tracker
EnvironmentFile=/opt/find-hub-tracker/.env
ExecStart=/opt/find-hub-tracker/.venv/bin/python -m find_hub_tracker start
Restart=always
RestartSec=30

[Install]
WantedBy=multi-user.target
```

### Dockerfile

```dockerfile
FROM python:3.14-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

COPY src/ src/
COPY migrations/ migrations/

CMD ["uv", "run", "find-hub-tracker", "start"]
```

Note: The Dockerfile must work on both amd64 and arm64 (Oracle Cloud ARM). Use multi-arch base images.

## README.md Content

Write a thorough README covering:

1. **What this does** — one paragraph summary
2. **Architecture diagram** — ASCII art showing: Google Find Hub ← GoogleFindMyTools ← Poller → Postgres/SQLite + Discord
3. **Prerequisites** — Python 3.14, uv, Docker (for Postgres), Chrome (for initial auth only), Google account with Find Hub devices
4. **Quick Start** — step by step from clone to running
5. **Authentication** — detailed walkthrough of the one-time Chrome auth flow
6. **Configuration** — table of all .env variables with descriptions and defaults
7. **Database** — explain Postgres primary / SQLite fallback, how to switch, migration system
8. **Discord Setup** — how to create webhooks in Discord server settings
9. **Deployment Options** — local, Docker Compose, Oracle Cloud Free Tier (link to deploy/ docs)
10. **CLI Commands** — usage for each command
11. **Future Plans** — this is the first service in a centralized automation platform; the Postgres database will be shared by future services
12. **Caveats** — unofficial API, don't poll too aggressively, Google could break this

## Implementation Notes

- Use `asyncio` throughout — the poller, DB, HTTP client should all be async
- Graceful shutdown: catch SIGINT/SIGTERM, close DB connections, post shutdown message to Discord
- Retry logic: if a poll fails, log the error and retry on the next interval — don't crash
- Structured logging with `structlog` — JSON format option for production
- Type hints everywhere, strict mode in pyproject.toml for type checking
- The service should be resilient to temporary Google API failures — log warnings but keep running
- If `secrets.json` is missing or expired, log a clear error telling the user to re-authenticate
- The Dockerfile must build for both amd64 and arm64 architectures

## Git Workflow

1. Create the repo on GitHub: `karlmarx/find-hub-tracker`
2. Work on `main` branch — this is scaffolding, not a feature branch
3. Verify `.gitignore` is committed FIRST before any other files
4. Run `git diff --stat` before every commit
5. Never commit `Auth/`, `secrets.json`, `.env`, `*.db`, `data/`, or `node_modules/`
6. Use conventional commit messages
7. Push to main when done

## GitHub Issues to Create

After the initial scaffold is pushed, create these issues:

### Issue #1: Investigate old MacBook as dedicated home automation server

Title: `infra: evaluate 2018 MacBook as home automation server`

Labels: `infrastructure`, `investigation`

Body:

```
## Context
Planning to run find-hub-tracker and future automation services on a dedicated home machine
rather than (or in addition to) Oracle Cloud. Have an ~2018 MacBook that could serve as
an always-on home server.

## Questions to Research
- What model/specs does it have? (check: Apple menu → About This Mac)
- Is it Intel or Apple Silicon? (2018 = Intel, likely i5 or i7)
- How much RAM? (likely 8GB or 16GB)
- Can it run Docker Desktop or colima for containers?
- What's the macOS support status? (2018 models likely capped at Ventura or Sonoma depending on model)
- Option: Wipe macOS and install Ubuntu Server or Debian for better Docker/server support?
- Power consumption for always-on use vs Oracle Cloud Free Tier?
- Can it comfortably run Postgres + the tracker service + 2-3 future services simultaneously?
- Does it make sense as a Tailscale exit node for the home network?

## Advantages Over Oracle Cloud
- Local network access — can integrate with local IoT/smart home devices later
- No dependency on Oracle's free tier policies or capacity availability
- Full control over the hardware
- Could run Home Assistant later if we decide to add it
- Better for services that need local network discovery (Chromecast, Google Home local API, etc.)
- Physical access for debugging

## Disadvantages vs Oracle Cloud
- Power cost (Intel MacBook uses ~15-30W idle, roughly $20-40/year)
- Need to handle UPS/power outages
- Local ISP reliability becomes a factor
- macOS is not ideal as a server OS — Linux would be significantly better
- Hardware is aging and non-upgradeable (soldered RAM, limited storage)

## Decision Matrix
| Factor | MacBook (local) | Oracle Cloud |
|--------|-----------------|--------------|
| Cost | ~$30/yr power | Free |
| Uptime | ISP + power dependent | 99.9% SLA (but free tier = no SLA) |
| Local access | Yes | No (Tailscale only) |
| Performance | Likely i5/8GB | 1 OCPU/4-24GB ARM |
| Future expansion | Limited by hardware | Limited by free tier caps |
| Maintenance | Physical access needed | SSH only |

## Recommendation
Likely best to run BOTH:
- Oracle Cloud for the always-on polling service (tracker + Postgres)
- MacBook as a local home automation hub for future services that benefit from LAN access
- Tailscale mesh connects them seamlessly

## Action Items
- [ ] Check MacBook model and exact specs
- [ ] Decide: keep macOS + colima, or wipe and install Ubuntu Server 24.04 LTS
- [ ] If Linux: verify Ubuntu hardware support for that MacBook model (WiFi drivers, etc.)
- [ ] Set up Tailscale on the machine
- [ ] Benchmark: Docker + Postgres + Python services on that hardware
- [ ] Research compact UPS options (CyberPower CP425SLG or similar)
- [ ] Decide on a physical location — needs ethernet, ventilation, minimal noise concerns
```

### Issue #2: Plan centralized automation database schema

Title: `db: design shared schema for multi-service automation platform`

Labels: `database`, `architecture`

Body:

```
## Context
find-hub-tracker is the first service using the shared Postgres database. Future services
will include:
- Amex Claims Automator (github.com/karlmarx/amex-claims-automator)
- Potential scheduling/calendar automation
- Potential fitness/recovery tracking data aggregation
- Other life automation services TBD

## Design Decisions Needed
- Schema namespacing: separate Postgres schemas per service vs prefixed tables in public schema?
- Shared tables: common `audit_log`, `events`, or `notifications` table across services?
- Migration tooling: hand-rolled SQL files (current) vs alembic vs dbmate vs golang-migrate?
- Backup strategy: pg_dump cron → where? (Oracle object storage free tier? Local?)
- Connection pooling: per-service pools vs shared PgBouncer?
- Monitoring: table sizes, connection counts, basic health endpoint

## Proposed Convention (for now)
- Each service owns a set of tables with a common prefix (e.g., `fht_devices`, `fht_locations`)
- Migrations live in each service's repo under `migrations/`
- Numbered with service prefix: `fht_001_initial.sql`, `acl_001_initial.sql`
- Shared `_meta` table tracks which migrations have run

## For Now
The current `migrations/001_initial.sql` approach is fine for find-hub-tracker alone.
Revisit this issue when the second service is ready to share the database.
```

## What "done" looks like

- All files in the project structure exist with real implementations (not stubs)
- `uv sync` works without errors
- `ruff check` and `ruff format --check` pass
- `docker compose up postgres` starts and the migration runs
- The CLI commands are wired up and print help text
- The Discord webhook publisher can send test embeds
- Both Postgres and SQLite backends create tables and pass basic smoke tests
- The GoogleFindMyTools integration is wired up (even if we can't test it without secrets.json — make sure the code paths are complete and the import/wrapper logic is solid)
- Dockerfile builds on both amd64 and arm64
- README is comprehensive
- The two GitHub issues above are created
- Pushed to `karlmarx/find-hub-tracker` on GitHub

# Claude Code Prompt: Google Find Hub Device Tracker with Discord Integration

## ⚠️ Agent Instructions — Read First

**This is an UPDATED spec.** An earlier version of this prompt may have already been partially executed. Before creating or overwriting anything:

1. **Check what exists first.** If the repo `karlmarx/find-hub-tracker` already exists on GitHub, clone it and inspect what's been done. Run `find . -type f | head -50` and review the current state.
2. **Don't recreate files that already exist and are correct.** Only create, modify, or add files that are missing or need to change per this spec.
3. **Key changes from previous prompt versions:**
   - **Database:** Postgres is now the *future* backend (MacBook). SQLite is primary for WSL and ultra.cc. `DB_BACKEND=sqlite` is the default.
   - **Deployment target:** Oracle Cloud is removed. Deployment path is WSL → ultra.cc seedbox → MacBook (future). All Oracle Cloud references should be removed if they exist.
   - **New module:** `heartbeat.py` — external Healthchecks.io ping + internal DB heartbeat record. Ships with v1.
   - **New DB table:** `service_heartbeats` — tracks where/when the service last ran.
   - **New config vars:** `HEALTHCHECKS_PING_URL`, `HEARTBEAT_STALE_THRESHOLD_MINUTES` added to .env.
   - **Poller update:** After each successful poll, fire heartbeat (ping Healthchecks.io + update DB record).
   - **Deploy directory:** `deploy/oracle-cloud-setup.md` replaced with `deploy/ultra-cc-setup.md`.
   - **GitHub issues:** Now 4 issues (added #4: sentinel/heartbeat system).
   - **ultra.cc ToS compliance:** Reviewed and documented — we're clear.
4. **Commit this spec to the repo** as `SPEC.md` at the project root so future prompt updates can reference it. Add to git but it's fine to be public.
5. **BEFORE doing any implementation work**, output a structured preflight summary in exactly this format so it can be reviewed:

```
=== PREFLIGHT CHECK ===

REPO STATUS:
- Exists: [yes/no]
- Files found: [count]
- Last commit: [message + date, or "N/A"]

ALREADY DONE (will not redo):
- [list each file/feature that exists and matches the spec]

NEEDS CREATION:
- [list each file that doesn't exist yet]

NEEDS MODIFICATION:
- [list each existing file that needs changes, with a one-line description of what changes]

NEEDS DELETION:
- [list anything that exists but contradicts the spec, e.g., Oracle Cloud references]

GITHUB ISSUES:
- [list which of the 4 issues exist vs need creation]

KEY DECISIONS:
- GoogleFindMyTools integration approach: [git dep / vendored / submodule]
- DB backend defaulting to: [sqlite/postgres]
- Deployment docs targeting: [ultra.cc / other]

ESTIMATED SCOPE:
- [small/medium/large] — [one sentence summary of remaining work]

=== END PREFLIGHT ===
```

**Wait for confirmation before proceeding.** If running autonomously without human review, proceed after outputting the preflight.

6. **After finishing all work, push to main.**

---

## Project Overview

Build a Python service called `find-hub-tracker` that polls Google Find Hub (formerly Find My Device) for device locations and battery levels, stores a running history in a database, and publishes updates to Discord via webhooks. The service should also send battery-low alerts for wearables (Pixel Watch, Pixel Buds).

This uses the open-source `GoogleFindMyTools` library (https://github.com/leonboe1/GoogleFindMyTools) which has reverse-engineered Google's Spot API (gRPC + Firebase Cloud Messaging) to query Find Hub device locations and decrypt E2EE location data. Auth is handled via a one-time Chrome login that produces an `Auth/secrets.json` file — after that, the service runs headlessly.

**Deployment path:**
1. **Local (Windows WSL)** — develop, test, run the one-time Chrome auth
2. **ultra.cc seedbox** — always-on production deployment (SQLite, user-space systemd, no root/Docker)
3. **MacBook home server (future)** — Postgres, Docker, local network access for broader automation

## ultra.cc ToS Compliance Notes

Reviewed ultra.cc Terms of Service (https://docs.ultra.cc/policies/terms-of-service). This service is compliant:
- ✅ Custom software is explicitly allowed in userspace via SSH
- ✅ Only prohibited tool is crypto mining — Python polling service is fine
- ✅ Resource usage is negligible (a few HTTP calls every 5 minutes)
- ✅ No public-facing services hosted (outbound-only: polls Google API, posts to Discord)
- ✅ No inbound web endpoints, no public directories, no streaming
- ⚠️ Chrome-based auth CANNOT run on ultra.cc (no GUI) — must auth locally, then scp secrets.json

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
├── docker-compose.yml        # For future MacBook deployment with Postgres
├── Dockerfile                # For future containerized deployment
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
│       ├── heartbeat.py      # External ping (Healthchecks.io) + internal DB heartbeat
│       └── models.py         # Pydantic models for DeviceLocation, BatteryStatus, etc.
├── migrations/
│   └── 001_initial.sql       # SQL migration for creating tables (Postgres-flavored, with SQLite compat notes)
├── scripts/
│   ├── authenticate.py       # One-time auth helper — wraps GoogleFindMyTools main.py auth flow
│   └── export_history.py     # Export location history to CSV/JSON
├── deploy/
│   ├── ultra-cc-setup.md     # Step-by-step ultra.cc deployment guide
│   ├── macbook-server-setup.md  # Future: MacBook home server setup
│   └── find-hub-tracker.service  # systemd user service file (for ultra.cc --user mode)
├── tests/
│   └── ...
└── Auth/                     # Created by auth flow, GITIGNORED
    └── secrets.json
```

## Dependencies

In `pyproject.toml`, include:
- `asyncpg` — async Postgres driver (for future MacBook deployment)
- `aiosqlite` — async SQLite driver (primary for WSL and ultra.cc)
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
# Use "sqlite" for WSL and ultra.cc; "postgres" for future MacBook deployment
DB_BACKEND=sqlite
SQLITE_PATH=./data/tracker_history.db
DATABASE_URL=postgresql://tracker:tracker@localhost:5432/find_hub_tracker  # Future use

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

# Sentinel / Heartbeat
HEALTHCHECKS_PING_URL=              # Optional: https://hc-ping.com/<uuid> from healthchecks.io
HEARTBEAT_STALE_THRESHOLD_MINUTES=15
```

## Database Design

### Dual Backend Strategy

- **Now (WSL + ultra.cc):** SQLite via aiosqlite. Zero setup, single file, perfect for a single service.
- **Future (MacBook):** Postgres via asyncpg. When multiple automation services need concurrent DB access.

Both backends implement the same `DatabaseBackend` protocol so switching is a config change.

### Schema (migrations/001_initial.sql)

Write this as Postgres-flavored SQL with comments noting SQLite equivalents where they differ:

```sql
-- find_hub_tracker schema
-- Postgres: BIGSERIAL, TIMESTAMPTZ, DOUBLE PRECISION
-- SQLite equivalents: INTEGER PRIMARY KEY AUTOINCREMENT, TEXT (ISO8601), REAL

CREATE TABLE IF NOT EXISTS devices (
    device_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    device_type TEXT NOT NULL DEFAULT 'unknown',  -- phone, watch, buds, tracker, tablet
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
```

The `db.py` module abstracts over both backends:

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
    async def upsert_heartbeat(self, service_name: str, host: str, poll_count: int, error_count: int, version: str | None) -> None: ...
    async def get_heartbeat(self, service_name: str, host: str) -> dict | None: ...

class PostgresBackend(DatabaseBackend): ...   # Uses asyncpg
class SQLiteBackend(DatabaseBackend): ...     # Uses aiosqlite
```

The SQLiteBackend must translate Postgres-isms (TIMESTAMPTZ → TEXT with ISO8601, BIGSERIAL → INTEGER AUTOINCREMENT, etc.) in its migration runner.

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
6. On success: fire heartbeat (ping Healthchecks.io + update DB heartbeat record)
7. On failure: increment error count in heartbeat record, log warning, continue

**Battery Check Job** (every `BATTERY_CHECK_INTERVAL_SECONDS`):
1. Check battery levels for all devices
2. If any device is below `BATTERY_LOW_THRESHOLD_PERCENT`, trigger alert
3. If below `BATTERY_CRITICAL_THRESHOLD_PERCENT`, trigger critical alert
4. Respect `ALERT_COOLDOWN_MINUTES` — don't re-alert for the same device within the cooldown window
5. Store alert history in database so we can track cooldowns across restarts

### 5. `db.py` — Database Persistence

Implement `PostgresBackend` and `SQLiteBackend` behind the `DatabaseBackend` protocol.

Both must support:
- Auto-migration on startup (create tables if not exist)
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

### 8. `heartbeat.py` — Sentinel / Dead Man's Switch

Two responsibilities, both fire-and-forget (never block the main poll loop):

**External ping (Healthchecks.io):**
- If `HEALTHCHECKS_PING_URL` is configured, HTTP GET to the URL after each successful poll
- Use `httpx` with a short timeout (5s) — if it fails, log a warning but don't retry
- On poll failure, ping the `/fail` endpoint instead (Healthchecks.io tracks this separately)
- Log a warning at startup if `HEALTHCHECKS_PING_URL` is not configured

**Internal DB heartbeat:**
- Upsert into `service_heartbeats` table after each poll cycle
- Track: service_name ("find-hub-tracker"), host (from hostname or config), last_heartbeat, poll_count, error_count, started_at, version (git hash or package version)
- The `get_heartbeat_status()` function returns current heartbeat info for the CLI `status` command

### 9. `main.py` — CLI Entry Point

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

### 10. `scripts/authenticate.py`

Standalone script that walks the user through the GoogleFindMyTools Chrome-based auth flow:
1. Check Chrome is installed
2. Run the auth sequence
3. Verify `secrets.json` was created
4. List discovered devices
5. Print next steps (including how to scp to ultra.cc)

Include PEP 723 inline metadata.

### 11. `scripts/export_history.py`

Export location history from the database to CSV or JSON. Include PEP 723 inline metadata.

```
uv run scripts/export_history.py --format csv --device "Pixel 9 Pro Fold" --days 30 --output locations.csv
```

## Deployment

### Phase 1: Local Development (Windows WSL)

1. `cp .env.example .env` — configure with `DB_BACKEND=sqlite`
2. `uv sync` — install dependencies
3. `uv run find-hub-tracker auth` — one-time Chrome auth (needs Chrome on Windows side)
4. `uv run find-hub-tracker test-discord` — verify webhook
5. `uv run find-hub-tracker start` — run the poller

### Phase 2: ultra.cc Production Deployment

Create `deploy/ultra-cc-setup.md` with step-by-step instructions:

```markdown
# ultra.cc Deployment Guide

## Prerequisites
- SSH access to your ultra.cc slot
- Auth/secrets.json generated locally (Chrome auth can't run on ultra.cc)
- Discord webhook URL configured

## ToS Compliance
This service is compliant with ultra.cc Terms of Service:
- Runs as a lightweight Python process in userspace
- Only makes outbound HTTP calls (no public-facing services)
- Negligible resource usage (~5 HTTP calls every 5 minutes)
- Not crypto mining, not hosting public services, not reselling

## Setup Steps

### 1. Install Python on ultra.cc
ultra.cc may have Python pre-installed. Check with `python3 --version`.
If not, follow ultra.cc's Python installation guide or install via pyenv in userspace.

### 2. Install uv
curl -LsSf https://astral.sh/uv/install.sh | sh

### 3. Clone the repo
cd ~
git clone https://github.com/karlmarx/find-hub-tracker.git
cd find-hub-tracker

### 4. Install dependencies
uv sync --frozen

### 5. Copy secrets from local machine
# On your local Windows/WSL machine:
scp Auth/secrets.json <username>@<ultra-hostname>:~/find-hub-tracker/Auth/

### 6. Configure environment
cp .env.example .env
# Edit .env: set DB_BACKEND=sqlite, add Discord webhook URLs

### 7. Test
uv run find-hub-tracker test-discord
uv run find-hub-tracker start  # Test manually first, Ctrl+C to stop

### 8. Set up systemd user service for always-on operation
mkdir -p ~/.config/systemd/user/
cp deploy/find-hub-tracker.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable find-hub-tracker
systemctl --user start find-hub-tracker

### 9. Verify
systemctl --user status find-hub-tracker
# Check Discord for startup message

### 10. Enable linger (keeps service running after SSH disconnect)
# Note: ultra.cc may or may not support loginctl enable-linger
# If not, use screen/tmux as fallback:
# screen -dmS tracker uv run find-hub-tracker start
```

### systemd user service file (deploy/find-hub-tracker.service)

```ini
[Unit]
Description=Find Hub Device Tracker
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=%h/find-hub-tracker
ExecStart=%h/find-hub-tracker/.venv/bin/python -m find_hub_tracker start
Restart=always
RestartSec=30
Environment=PATH=%h/.local/bin:%h/find-hub-tracker/.venv/bin:/usr/bin:/bin

[Install]
WantedBy=default.target
```

### Phase 3: Future MacBook Home Server (see GitHub issue)

For the future: wipe macOS, install Ubuntu Server, run Docker + Postgres, migrate from SQLite.
The `DB_BACKEND=postgres` path + docker-compose.yml + Dockerfile are included in the repo
for when this becomes relevant.

### docker-compose.yml (for future MacBook deployment)

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

  tracker:
    build: .
    env_file: .env
    depends_on:
      - postgres
    volumes:
      - ./Auth:/app/Auth:ro
    profiles:
      - deploy

volumes:
  pgdata:
```

### Dockerfile (for future containerized deployment)

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

## README.md Content

Write a thorough README covering:

1. **What this does** — one paragraph summary
2. **Architecture diagram** — ASCII art showing: Google Find Hub ← GoogleFindMyTools ← Poller → SQLite/Postgres + Discord
3. **Prerequisites** — Python 3.14, uv, Chrome (for initial auth only, local machine), Google account with Find Hub devices
4. **Quick Start (Local/WSL)** — step by step from clone to running
5. **Authentication** — detailed walkthrough of the one-time Chrome auth flow, plus how to scp secrets.json to remote
6. **Configuration** — table of all .env variables with descriptions and defaults
7. **Database** — explain SQLite primary (WSL/ultra.cc) / Postgres future (MacBook), how to switch
8. **Discord Setup** — how to create webhooks in Discord server settings
9. **Deployment** — WSL (dev), ultra.cc (production), MacBook (future) — link to deploy/ docs
10. **CLI Commands** — usage for each command
11. **Future Plans** — MacBook home server, centralized Postgres, multi-service automation platform
12. **Caveats** — unofficial API, don't poll too aggressively, Google could break this, ultra.cc ToS compliance notes

## Implementation Notes

- Use `asyncio` throughout — the poller, DB, HTTP client should all be async
- Graceful shutdown: catch SIGINT/SIGTERM, close DB connections, post shutdown message to Discord
- Retry logic: if a poll fails, log the error and retry on the next interval — don't crash
- Structured logging with `structlog` — JSON format option for production
- Type hints everywhere, strict mode in pyproject.toml for type checking
- The service should be resilient to temporary Google API failures — log warnings but keep running
- If `secrets.json` is missing or expired, log a clear error telling the user to re-authenticate
- The ultra.cc environment has no root/sudo — everything must work in userspace
- No Docker on ultra.cc — the service runs directly via uv/venv

## Git Workflow

1. Create the repo on GitHub: `karlmarx/find-hub-tracker`
2. Work on `main` branch — this is scaffolding, not a feature branch
3. Verify `.gitignore` is committed FIRST before any other files
4. Run `git diff --stat` before every commit
5. Never commit `Auth/`, `secrets.json`, `.env`, `*.db`, `data/`, or `node_modules/`
6. Use conventional commit messages
7. Push to main when done

## GitHub Issues to Create

After the initial scaffold is pushed, create these three issues:

### Issue #1: Investigate old MacBook as dedicated home automation server

Title: `infra: evaluate 2018 MacBook as home automation server`

Labels: `infrastructure`, `investigation`

Body:

```
## Context
Planning to run find-hub-tracker and future automation services on a dedicated home machine.
Have an ~2018 MacBook that could serve as an always-on home server with Docker + Postgres.
This would complement the ultra.cc deployment by handling services that benefit from local
network access.

## Questions to Research
- What model/specs does it have? (check: Apple menu → About This Mac)
- Is it Intel or Apple Silicon? (2018 = Intel, likely i5 or i7)
- How much RAM? (likely 8GB or 16GB)
- Can it run Docker Desktop or colima for containers?
- What's the macOS support status? (2018 models likely capped at Ventura or Sonoma)
- Option: Wipe macOS and install Ubuntu Server 24.04 LTS for proper server support?
- Power consumption for always-on use? (Intel MacBook = ~15-30W idle, ~$20-40/year)
- Can it comfortably run Postgres + Docker + 2-3 Python services simultaneously?
- Tailscale integration for seamless access from anywhere

## Use Cases That Benefit From Local Hardware
- Services needing LAN access (Chromecast control, Google Home local API)
- Home Assistant (if we go that route later)
- Centralized Postgres database for multiple automation services
- Local backup target for ultra.cc data
- Services that need more resources than ultra.cc's shared environment allows

## Comparison: ultra.cc vs MacBook vs Both
| Factor | ultra.cc | MacBook | Both |
|--------|----------|---------|------|
| Cost | Already paying | ~$30/yr power | Same |
| Uptime | Managed 24/7 | ISP + power dependent | Redundancy |
| Local network | No | Yes | Best of both |
| Resources | Shared, limited | Dedicated 8-16GB | Split workloads |
| Maintenance | Minimal | Physical access needed | More ops work |
| Docker/Postgres | No | Yes | Where needed |

## Recommendation
Run both:
- ultra.cc: lightweight always-on services (find-hub-tracker, future cron-style automations)
- MacBook: heavier services needing Docker/Postgres/LAN (Home Assistant, centralized DB, etc.)
- Tailscale mesh connects them

## Action Items
- [ ] Check MacBook model and exact specs
- [ ] Decide: keep macOS + colima, or wipe and install Ubuntu Server 24.04 LTS
- [ ] If Linux: verify Ubuntu hardware support for that MacBook model (WiFi, drivers)
- [ ] Set up Tailscale on the machine
- [ ] Benchmark Docker + Postgres + Python services on that hardware
- [ ] Research compact UPS options (CyberPower CP425SLG or similar)
- [ ] Decide physical location — needs ethernet, ventilation, minimal noise
```

### Issue #2: Plan centralized automation database schema

Title: `db: design shared schema for multi-service automation platform`

Labels: `database`, `architecture`

Body:

```
## Context
find-hub-tracker is the first service in a planned centralized automation platform.
Currently uses SQLite on ultra.cc. Future services will share a Postgres database
on the MacBook home server (see #1).

## Future Services
- Amex Claims Automator (github.com/karlmarx/amex-claims-automator)
- Scheduling/calendar automation
- Fitness/recovery tracking data aggregation
- Other life automation TBD

## Design Decisions Needed
- Schema namespacing: separate Postgres schemas per service vs prefixed tables?
- Shared tables: common audit_log, events, or notifications table?
- Migration tooling: hand-rolled SQL (current) vs alembic vs dbmate?
- Data migration: script to move SQLite history → Postgres when MacBook is ready
- Backup strategy: pg_dump cron → where?
- Connection pooling: per-service pools vs shared PgBouncer?

## For Now
SQLite per-service is fine. Revisit when MacBook is set up and second service is ready.
```

### Issue #3: Consolidate WSL automation to ultra.cc or MacBook

Title: `infra: migrate periodic automation tasks from Windows WSL to dedicated infrastructure`

Labels: `infrastructure`, `planning`

Body:

```
## Context
Currently running various automation and dev tasks on Windows 11 / WSL, which has downsides:
- Windows updates and restarts interrupt long-running services
- WSL can be flaky with networking after sleep/wake cycles
- The machine isn't always on (it's a daily-use workstation, not a server)
- Tailscale connection drops require manual intervention

With ultra.cc as an always-on remote host and potentially a MacBook as a local server,
we should evaluate which tasks can move off WSL to more reliable infrastructure.

## Candidates for Migration

### To ultra.cc (lightweight, outbound-only, no root needed)
- [ ] find-hub-tracker (this project — first candidate)
- [ ] Any future cron-style scripts that just make API calls
- [ ] Monitoring/alerting scripts
- [ ] Git-based automation (scheduled pulls, checks)

### To MacBook (needs Docker, Postgres, local network, or more resources)
- [ ] Centralized Postgres database
- [ ] Home Assistant (if adopted)
- [ ] Amex Claims Automator (needs headed browser — could use Playwright on Mac)
- [ ] Any service needing local network device discovery
- [ ] Backup aggregation (pull from ultra.cc, store locally)

### Keep on WSL (interactive, needs Windows/GUI, or development-only)
- [ ] Claude Code development sessions
- [ ] One-time Chrome auth flows (GoogleFindMyTools, etc.)
- [ ] Active development and testing of new projects
- [ ] Anything requiring GUI interaction

## Decision Criteria
For each task, ask:
1. Does it need to run 24/7? → Move off WSL
2. Does it need local network access? → MacBook
3. Is it lightweight and outbound-only? → ultra.cc
4. Does it need root/Docker/Postgres? → MacBook
5. Does it need interactive/GUI access? → Keep on WSL

## Action Items
- [ ] Audit current WSL cron jobs and running services
- [ ] Prioritize migration candidates
- [ ] Set up deployment pipeline (git push → auto-deploy to ultra.cc?)
- [ ] Document the "where does this run?" decision for each service
```

### Issue #4: Sentinel / heartbeat system to detect service outages

Title: `feat: dead man's switch — alert when tracker stops running`

Labels: `feature`, `reliability`

Body:

```
## Problem
If find-hub-tracker crashes, gets killed by ultra.cc for resource reasons, or the host
goes down entirely, nobody knows until they happen to notice Discord went quiet. A local
DB heartbeat is useless if the whole machine is unreachable — the sentinel must be external.

## Proposed Architecture

### External heartbeat (dead man's switch)
Use Healthchecks.io (free tier: 20 checks, open source, can self-host later on MacBook):
- Service pings a unique Healthchecks.io URL at the end of every successful poll cycle
- Healthchecks.io expects a ping every POLL_INTERVAL + grace period (e.g., every 10 min)
- If the ping is missed, Healthchecks.io alerts via:
  - Discord webhook (separate #alerts channel)
  - Email
  - Push notification (via Pushover/ntfy integration)

### Internal heartbeat record (DB)
Even though external is the real safety net, also write a heartbeat row to the DB:
- Table: `service_heartbeats`
  - service_name TEXT (e.g., "find-hub-tracker")
  - host TEXT (e.g., "ultra.cc", "wsl", "macbook")
  - last_heartbeat TIMESTAMPTZ
  - poll_count INTEGER (total successful polls since startup)
  - error_count INTEGER (total failed polls since startup)
  - started_at TIMESTAMPTZ
  - version TEXT (git commit hash or semver)
- Updated every successful poll cycle
- Useful for: dashboarding, knowing where the service last ran, debugging after recovery

### Multi-host awareness (future)
When service can run on multiple hosts (ultra.cc + MacBook), the heartbeat table enables:
- Only one instance should be actively polling at a time (leader election via DB)
- If primary host's heartbeat goes stale beyond threshold, secondary can activate
- Simple implementation: check last_heartbeat for current host; if stale, take over
- Requires shared DB (Postgres on MacBook phase) — not possible with per-host SQLite
- For now with SQLite: just use Healthchecks.io and manual failover

## Implementation Plan

### Phase 1 (now — ship with initial build)
- Add HEALTHCHECKS_PING_URL to .env config (optional — service works fine without it)
- After each successful poll cycle, HTTP GET to the ping URL (fire-and-forget, don't block)
- Add service_heartbeats table to schema
- Write heartbeat record after each successful poll
- Log a warning if HEALTHCHECKS_PING_URL is not configured

### Phase 2 (when MacBook is set up + shared Postgres)
- Heartbeat table becomes the source of truth for "where is this running?"
- Build simple leader election: if my host's heartbeat is freshest, I'm active
- If primary misses 3x poll intervals, secondary takes over and posts to Discord
- Dashboard endpoint or CLI command to show all service statuses across hosts

## Config Additions
```env
# Sentinel / Heartbeat
HEALTHCHECKS_PING_URL=https://hc-ping.com/<uuid>  # Optional, from healthchecks.io
HEARTBEAT_STALE_THRESHOLD_MINUTES=15               # When to consider a heartbeat stale
FAILOVER_ENABLED=false                              # Future: auto-failover between hosts
```

## Healthchecks.io Setup Steps
1. Create free account at healthchecks.io
2. Create a new check named "find-hub-tracker"
3. Set period = 5 minutes, grace = 5 minutes
4. Add Discord integration (webhook to #alerts channel)
5. Copy the ping URL into .env as HEALTHCHECKS_PING_URL
6. Optionally add email or Pushover/ntfy notification channels

## Alternative: Self-hosted Healthchecks
Healthchecks.io is open source (github.com/healthchecks/healthchecks). When MacBook
server is set up, we could self-host it there. But the free hosted tier is fine to start.

## Action Items
- [ ] Phase 1: Add heartbeat ping + DB record to poller (ship with v1)
- [ ] Set up Healthchecks.io account and Discord integration
- [ ] Phase 2: Leader election when shared Postgres is available
- [ ] Phase 3: Consider self-hosting Healthchecks on MacBook
```

## What "done" looks like

- All files in the project structure exist with real implementations (not stubs)
- `uv sync` works without errors
- `ruff check` and `ruff format --check` pass
- The CLI commands are wired up and print help text
- The Discord webhook publisher can send test embeds
- SQLite backend creates tables and passes basic smoke tests
- Postgres backend code exists and is complete (even if untestable without Postgres running)
- Heartbeat module pings Healthchecks.io URL (when configured) and writes to service_heartbeats table
- The GoogleFindMyTools integration is wired up (even if we can't test it without secrets.json — make sure the code paths are complete and the import/wrapper logic is solid)
- deploy/ultra-cc-setup.md is comprehensive and accurate
- deploy/find-hub-tracker.service works with `systemctl --user`
- Dockerfile and docker-compose.yml exist for future MacBook deployment
- README is comprehensive
- All four GitHub issues above are created
- Pushed to `karlmarx/find-hub-tracker` on GitHub

# find-hub-tracker

Poll [Google Find Hub](https://www.google.com/android/find/) (formerly Find My Device) for device locations and battery levels, store a running history in Postgres (or SQLite), and publish updates to Discord via webhooks. Battery-low alerts for wearables (Pixel Watch, Pixel Buds) are supported with configurable thresholds.

Built on top of [GoogleFindMyTools](https://github.com/leonboe1/GoogleFindMyTools), which reverse-engineers Google's Nova/Spot API (gRPC + Firebase Cloud Messaging) to query device locations and decrypt E2EE location data.

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                       APScheduler                           │
│  ┌──────────────┐ ┌──────────────┐ ┌─────────────────────┐  │
│  │ Location Poll │ │ Battery Check│ │ Periodic Summary    │  │
│  │ (5 min)      │ │ (15 min)     │ │ (6 hr) + Prune (24h)│  │
│  └──────┬───────┘ └──────┬───────┘ └──────────┬──────────┘  │
└─────────┼────────────────┼────────────────────┼─────────────┘
          │                │                    │
          v                v                    v
┌──────────────────┐  ┌──────────┐    ┌──────────────────┐
│ GoogleFindMyTools │  │ Battery  │    │ Discord Webhooks │
│ (Nova API + FCM) │  │ Monitor  │    │ (location/alerts)│
└────────┬─────────┘  └──────────┘    └──────────────────┘
         │
         v
┌──────────────────────────────────────┐
│ Database (Postgres primary / SQLite) │
│ devices | device_locations | alerts  │
└──────────────────────────────────────┘
```

## Prerequisites

- **Python 3.14+**
- **[uv](https://docs.astral.sh/uv/)** for package management
- **Docker** (for Postgres, optional — SQLite fallback available)
- **Google Chrome** (for one-time authentication only)
- A Google account with devices registered in [Find Hub](https://www.google.com/android/find/)
- Discord webhook URL(s) for notifications

## Quick Start

### 1. Clone and install

```bash
git clone https://github.com/karlmarx/find-hub-tracker.git
cd find-hub-tracker
uv sync
```

### 2. Set up GoogleFindMyTools

GoogleFindMyTools is not on PyPI. Clone it and add to your `PYTHONPATH`:

```bash
git clone https://github.com/leonboe1/GoogleFindMyTools.git
export PYTHONPATH="$PWD/GoogleFindMyTools:$PYTHONPATH"
```

### 3. Authenticate with Google

Run the one-time authentication flow. This opens Chrome for you to log in:

```bash
find-hub-tracker auth
# or: uv run scripts/authenticate.py
```

This creates `Auth/secrets.json` with your session tokens. This file is git-ignored and must never be committed. After initial auth, the service runs headlessly.

### 4. Configure

```bash
cp .env.example .env
# Edit .env with your Discord webhook URLs and database settings
```

### 5. Start the database

**With Postgres (recommended):**
```bash
docker compose up -d postgres
find-hub-tracker db-migrate
```

**With SQLite (no Docker needed):**
```bash
# Set DB_BACKEND=sqlite in .env
find-hub-tracker db-migrate
```

### 6. Start tracking

```bash
find-hub-tracker start
```

## Authentication

The authentication flow uses GoogleFindMyTools to:

1. **Chrome login**: Opens an embedded Google login page and waits for an OAuth token cookie
2. **AAS token**: Exchanges the OAuth token for an Android Account Service token via `gpsoauth`
3. **FCM registration**: Registers with Firebase Cloud Messaging for push notifications
4. **Device queries**: Uses the AAS token to call Google's Nova API for device listing and location requests
5. **E2EE decryption**: Location reports are end-to-end encrypted; the library decrypts them using your account's key chain

All tokens are cached in `Auth/secrets.json` for subsequent headless runs. If tokens expire, re-run `find-hub-tracker auth`.

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `DB_BACKEND` | `postgres` | Database backend: `postgres` or `sqlite` |
| `DATABASE_URL` | `postgresql://tracker:tracker@localhost:5432/find_hub_tracker` | Postgres connection string |
| `SQLITE_PATH` | `./data/tracker_history.db` | SQLite database path (when `DB_BACKEND=sqlite`) |
| `DISCORD_WEBHOOK_URL` | (required) | Discord webhook for location updates |
| `DISCORD_BATTERY_WEBHOOK_URL` | (optional) | Separate webhook for battery alerts |
| `POLL_INTERVAL_SECONDS` | `300` | Location polling interval (5 min) |
| `BATTERY_CHECK_INTERVAL_SECONDS` | `900` | Battery check interval (15 min) |
| `SUMMARY_INTERVAL_HOURS` | `6` | Periodic summary interval |
| `BATTERY_LOW_THRESHOLD_PERCENT` | `20` | Low battery alert threshold |
| `BATTERY_CRITICAL_THRESHOLD_PERCENT` | `10` | Critical battery alert threshold |
| `WEARABLE_THRESHOLD_OFFSET` | `5` | Extra % added to thresholds for watches/buds |
| `ALERT_COOLDOWN_MINUTES` | `60` | Minimum time between repeated alerts per device |
| `HISTORY_RETENTION_DAYS` | `90` | Auto-prune records older than this |
| `AUTH_SECRETS_PATH` | `./Auth/secrets.json` | Path to Google auth secrets |
| `LOG_LEVEL` | `INFO` | Logging level |
| `DEVICES_TO_TRACK` | (empty = all) | Comma-separated device names to track |

## Database

### Postgres (primary)

Postgres is the primary backend because this is the first service in a planned centralized automation platform. Future services will share the same database.

```bash
docker compose up -d postgres
find-hub-tracker db-migrate
```

### SQLite (fallback)

For quick local testing without Docker:

```bash
# In .env:
DB_BACKEND=sqlite
SQLITE_PATH=./data/tracker_history.db
```

Both backends use the same schema and pass the same tests. The `db.py` module abstracts over both with a common `DatabaseBackend` protocol.

## Discord Setup

1. Open your Discord server settings → **Integrations → Webhooks**
2. Click **New Webhook**
3. Name it (e.g., "Find Hub Tracker"), select a channel
4. Copy the webhook URL and paste it into `.env` as `DISCORD_WEBHOOK_URL`
5. (Optional) Create a second webhook in a different channel for battery alerts → `DISCORD_BATTERY_WEBHOOK_URL`
6. Verify with: `find-hub-tracker test-discord`

### Discord Messages

- **Location updates** (blue): Posted when a device moves >100m. Includes Google Maps link, distance moved, battery.
- **Periodic summary** (green): All device locations posted every 6 hours.
- **Battery alerts** (orange/red): Low and critical battery warnings. Wearables get a 5% higher threshold.
- **Startup/shutdown** (purple/grey): Service lifecycle messages.

## Deployment Options

### Local development

```bash
docker compose up -d postgres  # Start Postgres
cp .env.example .env           # Configure
find-hub-tracker db-migrate    # Create tables
find-hub-tracker auth          # One-time Chrome auth
find-hub-tracker start         # Run the poller
```

### Docker Compose (full)

```bash
docker compose --profile deploy up -d
```

### Oracle Cloud Free Tier

See [deploy/oracle-cloud-setup.md](deploy/oracle-cloud-setup.md) for step-by-step instructions on deploying to an always-free ARM VM.

### systemd

See [deploy/find-hub-tracker.service](deploy/find-hub-tracker.service) for a systemd unit file.

## CLI Commands

| Command | Description |
|---------|-------------|
| `find-hub-tracker start` | Start the polling daemon |
| `find-hub-tracker status` | Show all devices and their last known locations |
| `find-hub-tracker history <device> [--days 7]` | Show location history for a device |
| `find-hub-tracker devices` | List all known devices with types and battery |
| `find-hub-tracker test-discord` | Send a test message to verify webhook config |
| `find-hub-tracker auth` | Run the Google authentication flow |
| `find-hub-tracker db-migrate` | Run pending database migrations |
| `find-hub-tracker db-prune [--days N]` | Manually prune old records |

### Export history

```bash
uv run scripts/export_history.py --format csv --device "Pixel 9 Pro Fold" --days 30 --output locations.csv
uv run scripts/export_history.py --format json --output all_locations.json
```

## Future Plans

This is the first service in a centralized automation platform. The Postgres database will be shared by future services including:

- Amex Claims Automator
- Scheduling/calendar automation
- Fitness/recovery tracking data aggregation

## Caveats

- **Unofficial API**: GoogleFindMyTools reverse-engineers Google's internal APIs. Google could change or block access at any time.
- **Polling rate**: Don't go below 5-minute intervals to avoid rate limiting or account flags.
- **Battery data**: GoogleFindMyTools does not currently expose battery levels. The monitoring infrastructure is built and ready — it will activate automatically when upstream adds support.
- **Console output parsing**: The GoogleFindMyTools wrapper parses stdout from the library. This is fragile and may break if the library changes its output format.
- **E2EE key chain**: Decrypting location data requires the full key chain from your Google account. If Google changes the encryption scheme, updates to GoogleFindMyTools will be needed.
- **Auth expiry**: Session tokens may expire. Re-run `find-hub-tracker auth` if you see authentication errors.

## Development

```bash
uv sync
uv run ruff check src/
uv run ruff format --check src/
uv run find-hub-tracker start
```

## License

MIT

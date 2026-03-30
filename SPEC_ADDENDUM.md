# Find Hub Tracker — Full Spec Addendum

## Additional Config (.env.example)

```
ALERT_COOLDOWN_MINUTES=60
HISTORY_RETENTION_DAYS=90
AUTH_SECRETS_PATH=./Auth/secrets.json
LOG_LEVEL=INFO
```

## models.py

```python
class DeviceInfo(BaseModel):
    device_id: str
    name: str
    device_type: str  # "phone", "watch", "buds", "tracker", "tablet", "unknown"
    model: str | None = None

class DeviceLocation(BaseModel):
    device_id: str
    device_name: str
    latitude: float
    longitude: float
    accuracy_meters: float | None = None
    timestamp: datetime
    polled_at: datetime
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

## google_fmd.py

- Load secrets.json for auth
- Query all registered devices + last known locations
- Extract battery levels (Pixel Watch, Buds, phones)
- Handle E2EE decryption
- Handle FCM connection for push-based updates if supported
- Graceful error handling for rate limits / API changes
- Reference pattern: https://github.com/traccar/google-find-hub-sync microservice.py

## poller.py — Two APScheduler AsyncScheduler jobs

**Location Poll Job (every POLL_INTERVAL_SECONDS):**
1. Query all devices via google_fmd.py
2. Compare with last stored location
3. Store new location in SQLite (always — time series)
4. If moved >100m from last position, post to Discord
5. Post periodic summary every 6 hours regardless of movement (configurable)

**Battery Check Job (every BATTERY_CHECK_INTERVAL_SECONDS):**
1. Check battery levels for all devices
2. If below BATTERY_LOW_THRESHOLD_PERCENT → alert
3. If below BATTERY_CRITICAL_THRESHOLD_PERCENT → critical alert
4. Respect ALERT_COOLDOWN_MINUTES — check cooldown across restarts via DB
5. Store alert history in SQLite

## db.py — Tables + Methods

**Tables:**
- `device_locations`: id, device_id, device_name, device_type, latitude, longitude, accuracy_meters, address, battery_percent, is_charging, google_timestamp, polled_at — Index on (device_id, polled_at)
- `battery_alerts`: id, device_id, device_name, battery_percent, is_critical, alerted_at — Index on (device_id, alerted_at)
- `devices`: device_id, name, device_type, model, first_seen, last_seen

**Methods:**
- `prune_old_records()` — delete records older than HISTORY_RETENTION_DAYS
- `get_device_history(device_id, start, end)`
- `get_last_location(device_id)`
- `get_all_latest()` — most recent per device
- `get_last_alert(device_id)` — for cooldown checking

## discord.py — Embeds

**Location Update:** Blue, "📍 {device_name} moved", fields: New Location (Google Maps link), Distance from last, Battery, Last Updated
**Periodic Summary:** Green, "📊 Device Location Summary", one field per device
**Battery Low:** Orange (low) / Red (critical), "🔋 Low Battery" or "🪫 Critical Battery", @here for critical (configurable)
**Startup/Shutdown:** Post on service start (device count) and clean shutdown
**Google Maps link:** `https://www.google.com/maps?q={lat},{lon}`
**Rate limit handling:** 429 with exponential backoff

## battery.py

- `check_batteries(devices: list[DeviceLocation]) -> list[BatteryAlert]`
- Filter to battery-reporting devices (phones, watches, buds — not dumb trackers)
- Check cooldowns via db.get_last_alert()
- Special: Pixel Watch and Pixel Buds → lower alert threshold by 5% (configurable)

## main.py CLI (click)

```
find-hub-tracker start        # Start polling service (foreground)
find-hub-tracker status       # Show all devices + last known locations (Rich table)
find-hub-tracker history <device> [--days 7]
find-hub-tracker devices      # List all known devices with types and battery
find-hub-tracker test-discord # Send test message to verify webhook
find-hub-tracker auth         # Run GoogleFindMyTools auth flow
```

## scripts/authenticate.py (PEP 723 inline metadata)

1. Check Chrome installed
2. Run auth sequence
3. Verify secrets.json created
4. List discovered devices
5. Print next steps

## scripts/export_history.py (PEP 723 inline metadata)

```
uv run scripts/export_history.py --format csv --device "Pixel 9 Pro Fold" --days 30 --output locations.csv
```

## README Sections

1. Summary paragraph
2. ASCII architecture diagram: Google Find Hub ← GoogleFindMyTools ← Poller → SQLite + Discord
3. Prerequisites
4. Quick Start
5. Authentication walkthrough
6. Config table (all .env vars)
7. Discord webhook setup
8. Running as service (systemd unit + WSL note)
9. CLI commands
10. Caveats (unofficial API, don't over-poll)

## Implementation Notes

- asyncio throughout — poller, DB, HTTP all async
- Graceful shutdown: SIGINT/SIGTERM, close DB, post shutdown to Discord
- Retry logic: poll failures log + retry next interval, never crash
- structlog structured logging, JSON format option for production
- Type hints everywhere, strict mypy in pyproject.toml
- Resilient to temporary Google API failures
- Clear error if secrets.json missing/expired

## Git Workflow

1. Create: `gh repo create karlmarx/find-hub-tracker --private`
2. .gitignore committed FIRST
3. `git diff --stat` before every commit
4. Never commit Auth/, secrets.json, .env, *.db
5. Conventional commit messages
6. Push to main when done

## Definition of Done

- All files exist with real implementations (not stubs)
- `uv sync` works
- `ruff check` and `ruff format --check` pass
- CLI commands wired up with help text
- Discord test embed works
- SQLite schema creates on first run
- GoogleFindMyTools integration wired (code paths complete even without secrets.json)
- README comprehensive
- Pushed to karlmarx/find-hub-tracker

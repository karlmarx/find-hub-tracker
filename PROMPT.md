# Claude Code Prompt: Google Find Hub Device Tracker with Discord Integration

## Project Overview

Build a Python service called find-hub-tracker that polls Google Find Hub (formerly Find My Device) for device locations and battery levels, stores a running history in SQLite, and publishes updates to Discord via webhooks. The service should also send battery-low alerts for wearables (Pixel Watch, Pixel Buds).

This uses the open-source GoogleFindMyTools library (https://github.com/leonboe1/GoogleFindMyTools) which has reverse-engineered Google's Spot API (gRPC + Firebase Cloud Messaging) to query Find Hub device locations and decrypt E2EE location data. Auth is handled via a one-time Chrome login that produces an Auth/secrets.json file — after that, the service runs headlessly.

## Repository Setup

- Create a new GitHub repo: karlmarx/find-hub-tracker
- Initialize with uv init targeting Python 3.14
- Use uv for all package management (no pip, no poetry)
- Include PEP 723 inline metadata where applicable for any standalone scripts
- Set up .gitignore BEFORE any commits — include: __pycache__/, .venv/, *.pyc, node_modules/, Auth/, secrets.json, *.db, .env, dist/, *.egg-info/
- The Auth/ directory and .env must NEVER be committed — they contain Google session tokens and Discord webhook URLs
- Always run git diff --stat before committing
- Use ruff for linting and formatting
- Google-style docstrings throughout

## Project Structure

find-hub-tracker/
+-- pyproject.toml
+-- .gitignore
+-- .env.example
+-- README.md
+-- src/
¦   +-- find_hub_tracker/
¦       +-- __init__.py
¦       +-- main.py          # Entry point — CLI with start/status/history commands
¦       +-- config.py        # Pydantic Settings loading from .env
¦       +-- poller.py        # Core polling loop (async)
¦       +-- google_fmd.py    # Wrapper around GoogleFindMyTools
¦       +-- db.py            # SQLite persistence layer (aiosqlite)
¦       +-- discord.py       # Discord webhook publisher
¦       +-- battery.py       # Battery monitoring and alert logic
¦       +-- models.py        # Pydantic models
+-- scripts/
¦   +-- authenticate.py      # One-time auth helper
¦   +-- export_history.py    # Export location history to CSV/JSON
+-- tests/

## Dependencies (pyproject.toml)

- aiosqlite
- httpx
- pydantic >= 2.0
- pydantic-settings
- rich
- click
- apscheduler >= 4.0
- structlog

GoogleFindMyTools is NOT on PyPI. Try as uv git dependency:
[tool.uv.sources]
googlefindmytools = { git = "https://github.com/leonboe1/GoogleFindMyTools.git" }
If that fails, vendor relevant modules into src/find_hub_tracker/vendor/ and document the commit pinned.

## Configuration (.env.example)

DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/...
DISCORD_BATTERY_WEBHOOK_URL=https://discord.com/api/webhooks/...
POLL_INTERVAL_SECONDS=300
BATTERY_CHECK_INTERVAL_SECONDS=900
BATTERY_LOW_THRESHOLD_PERCENT=20
BATTERY_CRITICAL_THRESHOLD_PERCENT=10
DB_PATH=./data/find_hub.db
LOG_LEVEL=INFO
DEVICES_TO_TRACK=  # comma-separated device names, empty = track all

## Core Implementation Details

### google_fmd.py
Wrap GoogleFindMyTools to:
- List all devices with their current locations and battery levels
- Return structured Pydantic models
- Handle auth errors gracefully (tell user to re-run authenticate.py)
- Cache device list to avoid redundant API calls

### poller.py
- Async polling loop using APScheduler
- On each tick: query all devices, compare with last known state, persist to DB
- Emit events for: location changed significantly (>50m), battery dropped, battery below threshold
- Graceful shutdown on SIGINT/SIGTERM

### db.py
Schema:
- device_locations: id, device_id, device_name, lat, lng, accuracy, timestamp, battery_percent, battery_state
- battery_alerts: id, device_id, device_name, alert_type (low/critical/charging/full), battery_percent, timestamp, notified_at

### discord.py
- Post rich embeds for location updates
- Post alert embeds for battery events
- Include device name, battery %, last seen timestamp, map link (Google Maps URL from lat/lng)
- Rate limit: max 1 message per device per poll cycle
- Separate webhook for battery alerts if DISCORD_BATTERY_WEBHOOK_URL is set

### main.py CLI (click)
Commands:
- `find-hub start` — start polling daemon
- `find-hub status` — show current device states from DB
- `find-hub history [--device NAME] [--hours 24]` — show location history
- `find-hub auth` — run the one-time authentication flow

## README

Write a clear README with:
- What this does
- Prerequisites (Python 3.14, uv, Chrome for auth)
- Setup steps (clone, uv sync, run auth, configure .env, start)
- Architecture overview
- How GoogleFindMyTools auth works
- Limitations (polling rate, E2EE decryption notes)

## GitHub Setup

After building, create the GitHub repo and push:
gh repo create karlmarx/find-hub-tracker --private --description "Google Find Hub device tracker with Discord notifications"
git add .
git commit -m "feat: initial find-hub-tracker implementation"
git push -u origin main

When completely finished, run:
openclaw system event --text "Done: find-hub-tracker built and pushed to GitHub" --mode now

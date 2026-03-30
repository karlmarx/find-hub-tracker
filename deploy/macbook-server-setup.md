# MacBook Home Server Setup (Future)

> This guide is for a future deployment when the MacBook is set up as a home server.
> See GitHub issue #1 for the investigation plan.

## Overview

Run find-hub-tracker on a dedicated MacBook home server with Docker + Postgres,
replacing the SQLite deployment on ultra.cc (or running alongside it for redundancy).

## Prerequisites

- MacBook wiped and running Ubuntu Server 24.04 LTS (or macOS with colima)
- Docker and Docker Compose installed
- Tailscale configured for remote access
- `Auth/secrets.json` from initial Chrome auth

## Setup Steps

### 1. Clone the repo

```bash
git clone https://github.com/karlmarx/find-hub-tracker.git
cd find-hub-tracker
```

### 2. Configure environment

```bash
cp .env.example .env
```

Edit `.env`:
- Set `DB_BACKEND=postgres`
- Set `DATABASE_URL=postgresql://tracker:tracker@localhost:5432/find_hub_tracker`
- Add Discord webhook URLs
- Add `HEALTHCHECKS_PING_URL` for monitoring

### 3. Copy secrets

```bash
mkdir -p Auth/
# Copy secrets.json from your local machine
scp user@workstation:~/find-hub-tracker/Auth/secrets.json Auth/
```

### 4. Start with Docker Compose

```bash
# Start Postgres first
docker compose up -d postgres

# Wait for Postgres to be ready, then start tracker
docker compose --profile deploy up -d tracker
```

### 5. Verify

```bash
docker compose logs -f tracker
# Check Discord for startup message
```

## Migrating Data from SQLite

When transitioning from ultra.cc SQLite to MacBook Postgres:

1. Export location history from ultra.cc:
   ```bash
   # On ultra.cc
   uv run scripts/export_history.py --format json --output history_export.json
   ```

2. Transfer the export:
   ```bash
   scp ultra-cc:~/find-hub-tracker/history_export.json .
   ```

3. Import into Postgres (script TBD — see GitHub issue #2)

## Multi-Host Awareness

When both ultra.cc and MacBook are running:
- The `service_heartbeats` table tracks which host last polled
- Only one instance should actively poll at a time
- See GitHub issue #4 for leader election plans (requires shared Postgres)

## Maintenance

```bash
# View logs
docker compose logs -f tracker

# Restart
docker compose --profile deploy restart tracker

# Update
git pull
docker compose build tracker
docker compose --profile deploy up -d tracker
```

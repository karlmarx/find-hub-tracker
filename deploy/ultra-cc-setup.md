# ultra.cc Deployment Guide

## Prerequisites
- SSH access to your ultra.cc slot
- `Auth/secrets.json` generated locally (Chrome auth can't run on ultra.cc — no GUI)
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
If not, follow ultra.cc's Python installation guide or install via pyenv in userspace:

```bash
curl https://pyenv.run | bash
# Add to ~/.bashrc:
# export PATH="$HOME/.pyenv/bin:$PATH"
# eval "$(pyenv init -)"
pyenv install 3.14
pyenv global 3.14
```

### 2. Install uv

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

### 3. Clone the repo

```bash
cd ~
git clone https://github.com/karlmarx/find-hub-tracker.git
cd find-hub-tracker
```

### 4. Install dependencies

```bash
uv sync --frozen
```

### 5. Copy secrets from local machine

On your local Windows/WSL machine:

```bash
scp Auth/secrets.json <username>@<ultra-hostname>:~/find-hub-tracker/Auth/
```

Make sure the `Auth/` directory exists on ultra.cc first:

```bash
mkdir -p ~/find-hub-tracker/Auth
```

### 6. Configure environment

```bash
cp .env.example .env
```

Edit `.env`:
- Set `DB_BACKEND=sqlite` (default)
- Add your `DISCORD_WEBHOOK_URL`
- Optionally add `DISCORD_BATTERY_WEBHOOK_URL` for a separate alerts channel
- Optionally add `HEALTHCHECKS_PING_URL` for dead man's switch monitoring

### 7. Test

```bash
# Verify Discord webhook works
uv run find-hub-tracker test-discord

# Test the poller manually (Ctrl+C to stop)
uv run find-hub-tracker start
```

### 8. Set up systemd user service for always-on operation

```bash
mkdir -p ~/.config/systemd/user/
cp deploy/find-hub-tracker.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable find-hub-tracker
systemctl --user start find-hub-tracker
```

### 9. Verify

```bash
systemctl --user status find-hub-tracker
# Check Discord for startup message
```

### 10. Enable linger (keeps service running after SSH disconnect)

```bash
# Note: ultra.cc may or may not support loginctl enable-linger
loginctl enable-linger
```

If `loginctl` is not available or linger is not supported, use screen/tmux as fallback:

```bash
screen -dmS tracker uv run find-hub-tracker start
```

To reattach: `screen -r tracker`

## Updating

```bash
cd ~/find-hub-tracker
git pull
uv sync --frozen
systemctl --user restart find-hub-tracker
```

## Logs

```bash
# If using systemd
journalctl --user -u find-hub-tracker -f

# If using screen
screen -r tracker
```

## Troubleshooting

- **"secrets.json not found"**: Re-run auth locally and scp the file again
- **"No devices found"**: Google auth may have expired — re-authenticate locally
- **Discord 429 errors**: Rate limited — the service handles this with backoff, but check your poll interval isn't too aggressive
- **Service won't start**: Check `LOG_LEVEL=DEBUG` in .env for more detail

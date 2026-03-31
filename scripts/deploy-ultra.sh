#!/usr/bin/env bash
# Deploy find-hub-tracker to ultra.cc
# Usage: ./scripts/deploy-ultra.sh <user>@<host>
#
# Prerequisites:
#   - SSH access to ultra.cc
#   - Auth/secrets.json generated locally (run: uv run find-hub-tracker auth)
#   - .env configured locally (used as template)

set -euo pipefail

REMOTE="${1:?Usage: $0 <user>@<host>}"
REPO_URL="https://github.com/karlmarx/find-hub-tracker.git"
REMOTE_DIR="find-hub-tracker"

echo "==> Deploying find-hub-tracker to ${REMOTE}"

# Check local prerequisites
if [[ ! -f Auth/secrets.json ]]; then
    echo "ERROR: Auth/secrets.json not found. Run 'uv run find-hub-tracker auth' locally first."
    exit 1
fi

if [[ ! -f .env ]]; then
    echo "ERROR: .env not found. Copy .env.example to .env and configure it first."
    exit 1
fi

echo "==> Installing uv on remote (if needed)"
ssh "$REMOTE" 'command -v uv >/dev/null 2>&1 || curl -LsSf https://astral.sh/uv/install.sh | sh'

echo "==> Cloning/updating repo on remote"
ssh "$REMOTE" "
    if [ -d ${REMOTE_DIR}/.git ]; then
        cd ${REMOTE_DIR} && git pull origin main
    else
        git clone ${REPO_URL} ${REMOTE_DIR}
    fi
"

echo "==> Syncing dependencies"
ssh "$REMOTE" "cd ${REMOTE_DIR} && ~/.local/bin/uv sync --frozen"

echo "==> Uploading Auth/secrets.json"
ssh "$REMOTE" "mkdir -p ~/${REMOTE_DIR}/Auth"
scp Auth/secrets.json "${REMOTE}:~/${REMOTE_DIR}/Auth/secrets.json"

echo "==> Uploading .env"
scp .env "${REMOTE}:~/${REMOTE_DIR}/.env"

echo "==> Installing systemd user service"
ssh "$REMOTE" "
    mkdir -p ~/.config/systemd/user
    cp ~/${REMOTE_DIR}/deploy/find-hub-tracker.service ~/.config/systemd/user/
    systemctl --user daemon-reload
    systemctl --user enable find-hub-tracker
    systemctl --user restart find-hub-tracker
"

echo "==> Enabling linger (keep service running after logout)"
ssh "$REMOTE" "loginctl enable-linger 2>/dev/null || echo 'WARN: loginctl enable-linger not available — use screen/tmux as fallback'"

echo "==> Checking service status"
ssh "$REMOTE" "systemctl --user status find-hub-tracker --no-pager" || true

echo ""
echo "Done! Check Discord for the startup message."
echo "Logs: ssh ${REMOTE} journalctl --user -u find-hub-tracker -f"

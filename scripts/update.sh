#!/usr/bin/env bash
#
# WeatherPi updater — pull the latest version from GitHub and restart.
# Any user on the Pi can run this:
#
#   cd ~/PiWeatherStation && ./scripts/update.sh
#
# Your config.yaml and frontend/icons/house.png are gitignored, so they are
# never touched. The kiosk reloads itself automatically after the restart.
#
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_DIR"

echo "==> Updating WeatherPi in $REPO_DIR"

BRANCH="$(git rev-parse --abbrev-ref HEAD)"
git fetch --quiet origin

OLD="$(git rev-parse HEAD)"
REMOTE="$(git rev-parse "origin/$BRANCH")"

if [ "$OLD" = "$REMOTE" ]; then
  echo "==> Already up to date ($(git rev-parse --short HEAD))."
  exit 0
fi

echo "==> $(git rev-parse --short "$OLD") -> $(git rev-parse --short "$REMOTE")"
if ! git merge --ff-only "origin/$BRANCH"; then
  echo "ERROR: cannot fast-forward (local commits/changes on $BRANCH)." >&2
  echo "       Resolve manually, e.g.: git stash && git pull --ff-only" >&2
  exit 1
fi
NEW="$(git rev-parse HEAD)"

# Update Python deps only if requirements changed.
if ! git diff --quiet "$OLD" "$NEW" -- requirements.txt; then
  echo "==> requirements.txt changed — updating dependencies..."
  .venv/bin/pip install -r requirements.txt --quiet
fi

# Restart the backend if the service is installed. With the polkit rule that
# setup.sh installs, this needs no sudo; otherwise fall back to sudo.
if systemctl list-unit-files 2>/dev/null | grep -q '^weatherpi\.service'; then
  echo "==> Restarting weatherpi service..."
  if ! systemctl restart weatherpi.service 2>/dev/null; then
    echo "    (no polkit permission yet — using sudo; run ./scripts/setup.sh to avoid this)"
    sudo systemctl restart weatherpi.service
  fi
else
  echo "==> weatherpi.service not installed; skipping restart."
  echo "    (Run ./scripts/setup.sh to install it.)"
fi

echo "==> Updated to $(git rev-parse --short HEAD). The kiosk will reload within ~60s."

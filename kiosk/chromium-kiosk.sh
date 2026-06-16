#!/usr/bin/env bash
# Launch Chromium full-screen in kiosk mode pointing at the local dashboard.
# Used by kiosk/autostart-example.desktop at login. See plan section 13.
set -euo pipefail

URL="http://localhost:8000"

# Wait for the backend to answer before opening the browser (max ~30s).
for _ in $(seq 1 30); do
  if curl -fsS "http://localhost:8000/healthz" >/dev/null 2>&1; then
    break
  fi
  sleep 1
done

# Disable screen blanking / power management for an always-on display.
xset s off || true
xset -dpms || true
xset s noblank || true

# Hide the mouse cursor when idle (install with: sudo apt install unclutter).
if command -v unclutter >/dev/null 2>&1; then
  unclutter -idle 0.5 -root &
fi

# Chromium is named chromium-browser on older Pi OS, chromium on Bookworm.
BROWSER="chromium-browser"
command -v "$BROWSER" >/dev/null 2>&1 || BROWSER="chromium"

exec "$BROWSER" \
  --kiosk \
  --noerrdialogs \
  --disable-infobars \
  --disable-translate \
  --disable-features=TranslateUI \
  --no-first-run \
  --fast \
  --fast-start \
  --check-for-update-interval=31536000 \
  --autoplay-policy=no-user-gesture-required \
  "$URL"

#!/usr/bin/env bash
# Launch Chromium full-screen in kiosk mode pointing at the local dashboard.
#
# Targets Raspberry Pi OS Bookworm/Trixie running the labwc Wayland session
# (the current Pi OS default). Invoked at login from ~/.config/labwc/autostart
# (see scripts/setup.sh). See plan section 13.
set -u

URL="http://localhost:8000"
PROFILE="$HOME/.config/weatherpi-kiosk"

# Ensure we can reach the Wayland session even if the env isn't inherited.
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
if [ -z "${WAYLAND_DISPLAY:-}" ]; then
  WAYLAND_DISPLAY="$(basename "$(ls "$XDG_RUNTIME_DIR"/wayland-* 2>/dev/null | grep -v '\.lock' | head -1)")"
  export WAYLAND_DISPLAY
fi

# Wait for the backend to answer before opening the browser (max ~30s).
# Uses bash's /dev/tcp so it needs no curl/wget.
for _ in $(seq 1 30); do
  if (exec 3<>/dev/tcp/127.0.0.1/8000) 2>/dev/null; then exec 3>&- 3<&-; break; fi
  sleep 1
done

# Keep the display powered on (best-effort; harmless if unavailable).
command -v wlopm >/dev/null 2>&1 && wlopm --on '*' >/dev/null 2>&1 || true

# Chromium is "chromium" on Bookworm/Trixie, "chromium-browser" on older images.
BROWSER="chromium"
command -v "$BROWSER" >/dev/null 2>&1 || BROWSER="chromium-browser"

exec "$BROWSER" \
  --kiosk \
  --ozone-platform=wayland \
  --user-data-dir="$PROFILE" \
  --password-store=basic \
  --noerrdialogs \
  --disable-infobars \
  --disable-translate \
  --disable-features=TranslateUI \
  --no-first-run \
  --check-for-update-interval=31536000 \
  --autoplay-policy=no-user-gesture-required \
  "$URL"

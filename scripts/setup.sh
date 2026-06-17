#!/usr/bin/env bash
#
# WeatherPi first-time setup for Raspberry Pi OS (Bookworm, Desktop).
# Idempotent: safe to re-run. Adapts to whatever user/path you cloned into.
#
#   git clone https://github.com/njoyzrd/PiWeatherStation.git
#   cd PiWeatherStation
#   ./scripts/setup.sh
#
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
USER_NAME="$(id -un)"
PORT="8000"
cd "$REPO_DIR"

echo "==> WeatherPi setup"
echo "    repo: $REPO_DIR"
echo "    user: $USER_NAME"

# 1. System packages -------------------------------------------------------
echo "==> Installing system packages (sudo)..."
sudo apt-get update -qq
sudo apt-get install -y python3-venv python3-pip unclutter curl
# Chromium package name varies across Pi OS releases.
sudo apt-get install -y chromium-browser || sudo apt-get install -y chromium || \
  echo "WARN: could not install chromium automatically — install it manually."

# 2. Python virtualenv + dependencies --------------------------------------
echo "==> Creating virtualenv and installing dependencies..."
[ -d .venv ] || python3 -m venv .venv
.venv/bin/pip install --upgrade pip --quiet
.venv/bin/pip install -r requirements.txt --quiet

# 3. Local config (never overwrite an existing one) ------------------------
if [ ! -f config.yaml ]; then
  cp config.example.yaml config.yaml
  echo "==> Created config.yaml from the example."
  echo "    EDIT config.yaml to set your location before/after this runs."
else
  echo "==> Keeping existing config.yaml."
fi

# 4. systemd service (rendered with this user + path) ----------------------
echo "==> Installing systemd service (sudo)..."
sudo tee /etc/systemd/system/weatherpi.service >/dev/null <<EOF
[Unit]
Description=WeatherPi Backend
After=network-online.target
Wants=network-online.target

[Service]
WorkingDirectory=$REPO_DIR
ExecStart=$REPO_DIR/.venv/bin/uvicorn backend.app:app --host 127.0.0.1 --port $PORT
Restart=always
RestartSec=5
User=$USER_NAME
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
EOF
sudo systemctl daemon-reload
sudo systemctl enable --now weatherpi.service

# 5. Kiosk autostart (Chromium full-screen at login) -----------------------
echo "==> Installing kiosk autostart..."
chmod +x "$REPO_DIR/kiosk/chromium-kiosk.sh"
mkdir -p "$HOME/.config/autostart"
cat > "$HOME/.config/autostart/weatherpi-kiosk.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=WeatherPi Kiosk
Comment=Launch the WeatherPi dashboard full-screen at login
Exec=$REPO_DIR/kiosk/chromium-kiosk.sh
X-GNOME-Autostart-enabled=true
EOF

echo
echo "==> Done."
echo "    Backend:   sudo systemctl status weatherpi"
echo "    Dashboard: http://localhost:$PORT"
echo "    If this is your first run, edit config.yaml and (optionally) add"
echo "    frontend/icons/house.png, then reboot to start the kiosk."

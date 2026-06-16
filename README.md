# WeatherPi

A batteryless, always-on Raspberry Pi weather-station dashboard. A small Python
(FastAPI) backend fetches and normalizes weather data; a lightweight HTML/CSS/JS
frontend renders a modern, near-real-time weather display in full-screen Chromium.

See [raspberry-pi-weather-station-project-plan.md](raspberry-pi-weather-station-project-plan.md)
for the full design rationale and roadmap.

## Status

Working vertical slice — live data end to end:

- ✅ FastAPI backend with a background poller and warm in-memory cache
- ✅ Live [Open-Meteo](https://open-meteo.com/) current + hourly + daily data (no API key)
- ✅ Normalized data model served at `/api/all` (and per-section endpoints)
- ✅ Dashboard: current conditions, animated wind compass, hourly strip, 7-day
  forecast, humidity / dew point / pressure / UV, sunrise / sunset, live clock
- ✅ Stale-data handling — keeps last good data and flags it when a fetch fails
- ✅ NWS severe-weather alerts (U.S.) — fetched, normalized, and shown as a
  severity-colored banner
- ✅ Live wind over a WebSocket (`/ws/live`) — nearest NWS station observations
  or a simulator; the wind widget switches to live and falls back to forecast
- ⏳ Kiosk autostart hardening on the Pi (files provided, not yet installed)
- ⏳ Real-time hardware wind source (Tempest / Ambient / GPIO) — drops into the
  live-wind manager with no frontend changes

## Quick start (development, any machine)

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp config.example.yaml config.yaml          # then edit for your location
.venv/bin/uvicorn backend.app:app --host 127.0.0.1 --port 8000
```

Open <http://localhost:8000>. (If `config.yaml` is missing the backend falls
back to `config.example.yaml`, so it still runs out of the box.) The dashboard polls the local backend; the backend
polls Open-Meteo every 5 minutes (configurable).

## Configuration

Copy [config.example.yaml](config.example.yaml) to `config.yaml` and edit it —
location, units, refresh intervals, and feature toggles. `config.yaml` is
gitignored so your personal location (and any house image) stays out of the
public repo; the backend reads it on startup, falling back to the example if it
is absent (override the path with the `WEATHERPI_CONFIG` env var).

## Wind compass

The compass shows a glowing arrow for the current wind direction (animated
smoothly between updates) plus speed and gusts. Configure it under `wind:` in
[config.yaml](config.yaml):

- `arrow_mode: "from"` — arrow points *into* the wind, at the windward side of
  the house being hit (meteorological convention, matches the cardinal label).
  Use `"to"` to point the way the wind is traveling instead.

### Optional satellite / aerial image of your property

You can place a north-up aerial image behind the compass so the wind arrow lines
up with your actual house — handy for seeing which side is taking the wind:

```yaml
wind:
  house_image: "icons/house.png"   # local file under frontend/, or a full URL
  house_image_rotation_deg: 0       # rotate so map-north points up
```

Two easy ways to get an image:

- **Local file:** drop a square aerial screenshot at `frontend/icons/house.png`
  (this path is gitignored, so a personal home image won't be pushed).
- **Static maps URL** centered on your coordinates (43.0128, -89.2901), e.g.
  Mapbox: `https://api.mapbox.com/styles/v1/mapbox/satellite-v9/static/-89.2901,43.0128,18,0/240x240@2x?access_token=YOUR_TOKEN`
  (or the Google Maps Static API). Paste the URL as `house_image`.

The image is shown only when `house_image` is set; the compass ring fades so the
image reads through.

## Live wind

The wind widget can switch from forecast values to a live feed pushed over a
WebSocket (`/ws/live`), and falls back to the forecast automatically when no live
data is available. Configure it under `live_wind:` in your config:

- `source: "nws_station"` — real measured wind from the nearest NWS observation
  station (free, no key, U.S. only). Polled every `poll_seconds`; the widget
  labels it with the station id and observation age, e.g. `● KMSN · 14 min ago`.
- `source: "simulator"` — smoothly-varying fake wind emitted every
  `simulator.update_seconds`, labeled `● LIVE · Simulated`. Handy for demos and
  for seeing the real-time motion before you have hardware.
- `source: "off"` — disable the live feed; the widget just uses the forecast.

These are *real* observations or simulated data — public forecast APIs don't
update every few seconds. For genuinely real-time wind, add a personal weather
station (WeatherFlow Tempest, Ambient Weather) or a DIY GPIO anemometer as a new
source in [backend/live_wind.py](backend/live_wind.py); the WebSocket and frontend
need no changes.

## Project layout

```text
config.yaml              # user-adjustable settings (location, units, refresh)
requirements.txt
backend/
  app.py                 # FastAPI app + API/WS endpoints, serves the frontend
  cache.py               # in-memory store + background poll loops
  live_wind.py           # live-wind manager + /ws/live broadcast + simulator
  models.py              # normalized Pydantic data model
  utils.py               # config loading, unit conversions, WMO code mapping
  weather_sources/
    open_meteo.py        # current/hourly/daily forecast fetch + normalize
    nws.py               # U.S. severe-weather alerts
    nws_station.py       # nearest NWS station live wind observations
    tempest.py           # stub: WeatherFlow Tempest live wind (future)
    ambient.py           # stub: Ambient Weather (future)
frontend/
  index.html             # dashboard markup
  styles.css             # dark glass-card theme, CSS Grid (3:2, adapts to 16:9/16:10)
  app.js                 # clock, fetch loop, rendering, compass animation
systemd/weatherpi.service
kiosk/chromium-kiosk.sh
kiosk/autostart-example.desktop
```

## API endpoints

| Endpoint        | Returns                                            |
|-----------------|----------------------------------------------------|
| `GET /api/all`     | Everything the dashboard needs (one call)       |
| `GET /api/current` | Current conditions                              |
| `GET /api/hourly`  | Hourly forecast (starts at the current hour)    |
| `GET /api/daily`   | 7-day forecast                                  |
| `GET /api/alerts`  | Active U.S. NWS alerts (most severe first)      |
| `GET /api/status`  | API health / freshness                          |
| `GET /api/config`  | Frontend-relevant config slice                  |
| `GET /healthz`     | Liveness probe (used by the kiosk launcher)     |
| `WS  /ws/live`     | Live wind feed (nearest NWS station or simulator) |

## Deploying on the Raspberry Pi

1. Clone the repo to `/home/pi/PiWeatherStation` and create the venv as above.
2. Create your local config (gitignored, so it isn't in the clone):
   ```bash
   cp config.example.yaml config.yaml      # then edit location/units/features
   ```
3. (Optional) Add your aerial house image for the wind compass — also gitignored,
   so copy it over manually and point `wind.house_image` at it in `config.yaml`:
   ```bash
   cp /path/to/your-aerial.png frontend/icons/house.png
   ```
4. Install the backend service (edit paths/user inside the file first):
   ```bash
   sudo cp systemd/weatherpi.service /etc/systemd/system/
   sudo systemctl daemon-reload
   sudo systemctl enable --now weatherpi.service
   ```
5. Autostart Chromium in kiosk mode:
   ```bash
   sudo apt install unclutter
   mkdir -p ~/.config/autostart
   cp kiosk/autostart-example.desktop ~/.config/autostart/weatherpi-kiosk.desktop
   # edit the Exec path in that file if your install dir differs
   ```
6. Reboot. The Pi auto-logs in, the backend starts, and Chromium opens the
   dashboard full-screen at <http://localhost:8000>.

## Next steps

- Validate Pi 4 performance with the mock dashboard (see plan §16).
- Harden kiosk autostart on real Pi hardware.
- Add a real-time hardware wind source (Tempest / Ambient / GPIO) into the
  live-wind manager (plan Phase 5).

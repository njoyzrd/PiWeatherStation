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
- ✅ Dashboard (optimized for 3:2 / 3000×2000): combined temperature + conditions
  card, a 24-hour temperature & pressure trend graph, animated wind compass,
  hourly strip, 7-day forecast, metrics grid, and a live clock
- ✅ Stale-data handling — keeps last good data and flags it when a fetch fails
- ✅ NWS severe-weather alerts (U.S.) — fetched, normalized, and shown as a
  severity-colored banner
- ✅ Live wind over a WebSocket (`/ws/live`) — nearest NWS station observations
  or a simulator; the wind widget switches to live and falls back to forecast
- ✅ Air quality (US AQI + PM2.5) via Open-Meteo's free Air Quality API
- ✅ Precipitation nowcast ("rain starting in ~X min") from Open-Meteo minutely data
- ✅ Pressure trend, visibility, moon phase, and daily snowfall
- ✅ Multi-source resilience — Met.no fallback forecast if Open-Meteo is down;
  the status shows which provider is live
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

## Data sources & resilience

Each provider feeds the one normalized model, so the frontend never knows which
source produced the data:

- **Open-Meteo** (free, no key) — current/hourly/daily forecast, minutely
  precipitation nowcast, air quality, and derived fields (pressure trend,
  visibility, moon phase, snowfall).
- **MET Norway / Yr** (free, needs a User-Agent) — **fallback** forecast used
  automatically if Open-Meteo fails, so an always-on display degrades gracefully.
- **National Weather Service** (free, no key, U.S.) — severe-weather alerts and
  nearest-station live wind observations.

`/api/status` reports which provider is live; the header shows `via met.no` when
running on the fallback.

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
    open_meteo.py        # current/hourly/daily forecast + nowcast + derived fields
    open_meteo_air.py    # air quality (US AQI, PM2.5, ozone)
    metno.py             # MET Norway (Yr) fallback forecast
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
scripts/setup.sh           # one-time Pi installer (venv, deps, service, kiosk)
scripts/update.sh          # pull latest from GitHub and restart
```

## API endpoints

| Endpoint        | Returns                                            |
|-----------------|----------------------------------------------------|
| `GET /api/all`     | Everything the dashboard needs (one call)       |
| `GET /api/current` | Current conditions                              |
| `GET /api/hourly`  | Hourly forecast (starts at the current hour)    |
| `GET /api/daily`   | 7-day forecast                                  |
| `GET /api/alerts`  | Active U.S. NWS alerts (most severe first)      |
| `GET /api/air_quality` | Current air quality (US AQI, PM2.5, ozone)  |
| `GET /api/nowcast` | Next-2-hour precipitation nowcast               |
| `GET /api/status`  | API health / freshness                          |
| `GET /api/config`  | Frontend-relevant config slice                  |
| `GET /healthz`     | Liveness probe (used by the kiosk launcher)     |
| `GET /api/version` | Running code revision (drives kiosk auto-reload)|
| `WS  /ws/live`     | Live wind feed (nearest NWS station or simulator) |

## Deploying on the Raspberry Pi

One-time setup — clone, then run the installer. It creates the virtualenv,
installs dependencies, your `config.yaml`, the systemd service, and the kiosk
autostart, adapting to whatever **user and path** you cloned into:

```bash
git clone https://github.com/njoyzrd/PiWeatherStation.git
cd PiWeatherStation
./scripts/setup.sh
```

Then personalize (both are gitignored, so they stay local and survive updates):

```bash
nano config.yaml                                       # your location/units
cp /path/to/your-aerial.png frontend/icons/house.png   # optional compass image
sudo systemctl restart weatherpi
```

Reboot. The Pi auto-logs in, the backend starts under systemd (`Restart=always`),
and Chromium opens the dashboard full-screen at <http://localhost:8000>.

## Updating

Pull the latest version from GitHub and restart — any user on the Pi can run:

```bash
cd ~/PiWeatherStation && ./scripts/update.sh
```

It fast-forwards to the latest commit, reinstalls dependencies only if
`requirements.txt` changed, and restarts the backend. Your `config.yaml` and
house image are never touched, and the kiosk **reloads itself within ~60 s** —
the dashboard watches `/api/version` and refreshes when the running revision
changes, so you don't need to touch the Pi's screen.

## Next steps

- Validate Pi 4 performance with the mock dashboard (see plan §16).
- Harden kiosk autostart on real Pi hardware.
- Add a real-time hardware wind source (Tempest / Ambient / GPIO) into the
  live-wind manager (plan Phase 5).

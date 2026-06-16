# Raspberry Pi Weather Station Display Project Plan

## 1. Project Goal

Build a batteryless, always-on Raspberry Pi weather station display that replaces an Android tablet running a weather-station-style app such as WhatWeather.

The application should:

- Run natively on Raspberry Pi OS.
- Load directly into the weather dashboard after boot.
- Display a modern, polished weather-station interface.
- Feel active and close to real-time, especially for wind speed and direction.
- Avoid Android, Google Play Services, and tablet battery issues.
- Run reliably on a Raspberry Pi 4 connected to a small external display.

## 2. Project Rationale

The original plan was to run Android on a Raspberry Pi 4 and install the Android weather app from the Google Play Store. Testing showed that Android on the Pi 4 became nearly unusable, even after replacing the microSD card with a faster model. This suggests the issue is likely related to RAM pressure, graphics acceleration, Google Play Services overhead, the Android build, or general platform fit.

A native Raspberry Pi OS dashboard should be more reliable because it avoids:

- Unofficial Android builds.
- Google Play Services overhead.
- Android Play Store compatibility issues.
- Tablet battery swelling or overcharging.
- Android lock screen and touch input assumptions.

## 3. Recommended Platform

### Operating System

Use:

```text
Raspberry Pi OS Bookworm, 64-bit, Desktop edition
```

Raspberry Pi OS Desktop is recommended for the first version because it simplifies:

- Display configuration.
- Wi-Fi setup.
- Chromium kiosk mode.
- Browser testing.
- Local debugging.
- Auto-login and startup configuration.

A Lite build could be considered later, but Desktop is the better starting point.

### Hardware

Recommended minimum hardware:

```text
Raspberry Pi 4 Model B
2 GB RAM minimum
4 GB or 8 GB preferred
Good 5V 3A USB-C power supply
Active cooling or effective passive cooling
Modern A2 microSD card or USB 3 SSD
External HDMI display
Keyboard/touchpad for setup and maintenance
```

The Pi 4 should run this project well if it is not a 1 GB model. The final application should be far lighter than Android because it will only run:

- Raspberry Pi OS.
- A local Python backend.
- A full-screen Chromium browser.
- A lightweight HTML/CSS/JavaScript dashboard.

### Display

The current display is a 3:2 "3K" external monitor. For performance and readability, start with a lower display resolution:

```text
Preferred: 1920x1280, if supported
Safe fallback: 1920x1080
Avoid initially: native 3K / 3000x2000-class resolution
```

The dashboard should be designed for 3:2, but it should also adapt gracefully to 16:9 and 16:10 displays.

## 4. High-Level Architecture

Build the application as a local web dashboard.

```text
Raspberry Pi OS
  ├── Python backend service
  │     ├── Fetches weather data
  │     ├── Caches latest data
  │     ├── Normalizes API responses
  │     └── Serves local JSON endpoints
  │
  └── Chromium kiosk browser
        └── Displays local dashboard UI
```

The frontend should only call the local backend. It should not call third-party weather APIs directly. This keeps the design flexible and allows caching, rate limiting, retry logic, provider changes, and offline fallback behavior.

## 5. Proposed Technology Stack

### Backend

Recommended:

```text
Python 3
FastAPI
Uvicorn
Requests or HTTPX
PyYAML
```

FastAPI is preferred over Flask because it provides a clean path for future WebSocket support, which may be useful if a personal weather station is added later.

Backend responsibilities:

- Fetch current conditions.
- Fetch hourly forecast.
- Fetch daily forecast.
- Fetch severe weather alerts.
- Cache successful API responses.
- Serve normalized local API responses.
- Track source freshness and API health.
- Provide fallback data if an external API is temporarily unavailable.

### Frontend

Recommended:

```text
HTML
CSS
Vanilla JavaScript
SVG-based gauges
CSS Grid layout
CSS transitions/animations
```

Avoid heavy frontend frameworks for the first version. A simple dashboard will be easier to maintain, faster on the Pi, and less likely to consume unnecessary resources.

Optional later:

```text
React, Vue, or Svelte
Chart.js or ECharts
WebSocket client for live personal weather station data
```

## 6. Weather Data Sources

### Primary Forecast Source: Open-Meteo

Use Open-Meteo as the primary source for current, hourly, and daily weather data.

Website:

```text
https://open-meteo.com/
```

Advantages:

- Free for non-commercial use under fair-use guidelines.
- No API key required.
- JSON responses.
- Supports global locations.
- Provides current, hourly, and daily forecast fields.
- Good fit for a personal Raspberry Pi display.

Useful fields:

```text
Current temperature
Feels-like temperature
Humidity
Dew point
Pressure
Cloud cover
Wind speed
Wind gusts
Wind direction
Precipitation
Precipitation probability
UV index
Sunrise
Sunset
Weather condition code
Hourly forecast
Daily high and low
```

Example request pattern:

```text
https://api.open-meteo.com/v1/forecast?latitude=43.0389&longitude=-87.9065&current=temperature_2m,relative_humidity_2m,apparent_temperature,precipitation,weather_code,cloud_cover,pressure_msl,wind_speed_10m,wind_direction_10m,wind_gusts_10m&hourly=temperature_2m,apparent_temperature,precipitation_probability,weather_code,wind_speed_10m&daily=weather_code,temperature_2m_max,temperature_2m_min,sunrise,sunset,precipitation_probability_max,uv_index_max&temperature_unit=fahrenheit&wind_speed_unit=mph&precipitation_unit=inch&timezone=auto
```

Recommended polling interval:

```text
Current/forecast data: every 5 minutes
Hourly/daily forecast: every 15 to 30 minutes
```

The frontend can refresh from the local backend every 10 to 15 seconds, but the backend should not poll Open-Meteo every 10 to 15 seconds because the underlying forecast data does not change that frequently.

### U.S. Weather Alerts: National Weather Service API

For U.S. locations, use the National Weather Service API for official alerts.

Website:

```text
https://www.weather.gov/documentation/services-web-api
```

Use it for:

```text
Severe thunderstorm warnings
Tornado watches and warnings
Winter storm warnings
Flood warnings
Special weather statements
Heat advisories
Other official watches, warnings, and advisories
```

Recommended polling interval:

```text
Alerts: every 1 to 5 minutes
```

The dashboard should show alerts prominently when they exist, but should not allow alert text to overwhelm the main display.

### Optional True Real-Time Sources

If truly live wind speed and direction are required, add a personal weather station source later.

Potential sources:

```text
WeatherFlow Tempest
Ambient Weather
Local sensor hardware
```

WeatherFlow Tempest is especially interesting because its WebSocket API can provide rapid wind observations, which would allow the wind widget to become genuinely real-time.

Design the app so these sources can be added later without rewriting the frontend.

## 7. Refresh Strategy

The dashboard should feel real-time without pretending that public forecast APIs update every few seconds.

Recommended refresh model:

```text
Clock: every 1 second
UI animations: continuous CSS/SVG animations
Frontend local API refresh: every 10 to 15 seconds
Open-Meteo backend fetch: every 5 minutes
NWS alerts backend fetch: every 1 to 5 minutes
Hourly/daily forecast refresh: every 15 to 30 minutes
Personal station data, future: 3 to 60 seconds depending on source
```

This lets the display feel alive while respecting API limits and data freshness.

## 8. Real-Time Feel Design

The app should clearly show when values were last updated while still feeling dynamic.

For wind speed and direction:

- Show current reported wind speed.
- Show gust speed.
- Show wind direction as a compass needle.
- Show cardinal direction, for example WSW or NE.
- Smoothly animate the needle to the latest direction.
- Pulse or highlight the gust value when gusts are high.
- Show a subtle "Updated X min ago" timestamp.

Do not fabricate second-by-second weather changes when using forecast APIs. Instead, animate the UI gently and accurately reflect the latest known observation or forecast value.

If a personal weather station is added later, the same wind widget can switch to true live updates.

## 9. Dashboard Layout Concept

Design for a modern weather station look, optimized for a 3:2 display.

Suggested layout:

```text
┌──────────────────────────────────────────────┐
│ Location              Time/Date      Alerts  │
├───────────────┬───────────────┬──────────────┤
│ Current Temp  │ Conditions    │ Wind Compass │
│ Feels Like    │ Icon/Summary  │ Speed/Gust   │
├───────────────┴───────┬───────┴──────────────┤
│ Hourly Forecast Strip │ Pressure / Humidity  │
│ next 12-24 hours      │ Dew Point / UV       │
├───────────────────────┴──────────────────────┤
│ 7-Day Forecast + Sunrise/Sunset + Rain Chance │
└──────────────────────────────────────────────┘
```

Primary widgets:

- Current temperature.
- Feels-like temperature.
- Current condition icon and summary.
- Wind compass, speed, gusts, and direction.
- Humidity and dew point.
- Pressure and trend.
- UV index.
- Rain probability.
- Hourly forecast strip.
- Daily forecast cards.
- Sunrise and sunset.
- Severe weather alert banner.
- Last updated status.

Visual style:

```text
Dark background
High contrast typography
Large readable numbers
Glass/card-style panels
Subtle gradients
Weather icons
Smooth transitions
Minimal clutter
Responsive 3:2 layout
```

## 10. Normalized Data Model

The backend should normalize all data sources into a common structure.

Example:

```json
{
  "location": {
    "name": "Milwaukee, WI",
    "latitude": 43.0389,
    "longitude": -87.9065
  },
  "current": {
    "temperature_f": 72.4,
    "feels_like_f": 73.1,
    "humidity_pct": 61,
    "dew_point_f": 58.2,
    "pressure_inhg": 29.92,
    "wind_speed_mph": 8.5,
    "wind_gust_mph": 14.2,
    "wind_direction_deg": 240,
    "wind_direction_cardinal": "WSW",
    "condition_code": 2,
    "condition_text": "Partly cloudy",
    "uv_index": 4.1,
    "precip_rate_in": 0,
    "updated_at": "2026-06-16T15:22:00-05:00",
    "source": "open-meteo"
  },
  "hourly": [],
  "daily": [],
  "alerts": [],
  "status": {
    "api_ok": true,
    "last_successful_refresh": "2026-06-16T15:22:00-05:00",
    "last_error": null
  }
}
```

This abstraction is important because it allows Open-Meteo, NWS, Tempest, Ambient Weather, or local sensors to feed the same frontend.

## 11. Proposed Project Structure

```text
weatherpi/
  README.md
  config.yaml
  requirements.txt

  backend/
    app.py
    cache.py
    models.py
    utils.py
    weather_sources/
      __init__.py
      open_meteo.py
      nws.py
      tempest.py
      ambient.py

  frontend/
    index.html
    app.js
    styles.css
    icons/

  systemd/
    weatherpi.service

  kiosk/
    chromium-kiosk.sh
    autostart-example.desktop
```

## 12. Backend API Endpoints

Suggested local endpoints:

```text
GET /api/current
GET /api/hourly
GET /api/daily
GET /api/alerts
GET /api/status
GET /api/all
```

For the frontend, `/api/all` may be the simplest first version because it can return everything needed to render the dashboard.

Future WebSocket endpoint:

```text
WS /ws/live
```

Use the WebSocket only when a true live source, such as a personal weather station, is added.

## 13. Kiosk Boot Plan

Final boot behavior:

```text
Power on Pi
Raspberry Pi OS boots
Auto-login starts desktop session
Python backend starts automatically with systemd
Chromium launches full-screen in kiosk mode
Dashboard opens at http://localhost:8000
Mouse cursor is hidden
Screen blanking is disabled
The app recovers from API or network failures
```

Example Chromium launch command:

```bash
chromium-browser \
  --kiosk \
  --noerrdialogs \
  --disable-infobars \
  --check-for-update-interval=31536000 \
  http://localhost:8000
```

Install cursor hiding utility:

```bash
sudo apt install unclutter
```

Disable screen blanking and power management during kiosk use.

## 14. Systemd Backend Service

Create a systemd service to start the backend automatically.

Example service file:

```ini
[Unit]
Description=WeatherPi Backend
After=network-online.target
Wants=network-online.target

[Service]
WorkingDirectory=/home/pi/weatherpi
ExecStart=/home/pi/weatherpi/.venv/bin/uvicorn backend.app:app --host 127.0.0.1 --port 8000
Restart=always
RestartSec=5
User=pi
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
```

Enable it:

```bash
sudo systemctl daemon-reload
sudo systemctl enable weatherpi.service
sudo systemctl start weatherpi.service
```

## 15. Development Phases

### Phase 1: Pi OS and Display Validation

Goal: confirm that the Pi 4 can run a full-screen dashboard smoothly.

Tasks:

- Install Raspberry Pi OS 64-bit Desktop.
- Configure display resolution.
- Open Chromium full-screen.
- Create a static HTML/CSS mock dashboard.
- Test animations and readability.
- Monitor CPU, memory, temperature, and throttling.

Validation commands:

```bash
free -h
vcgencmd measure_temp
vcgencmd get_throttled
top
```

Success criteria:

```text
Dashboard renders smoothly
No significant swapping
Temperature is controlled
vcgencmd get_throttled returns throttled=0x0
Display is readable from intended distance
```

### Phase 2: Open-Meteo Integration

Goal: display real weather data from Open-Meteo.

Tasks:

- Build FastAPI backend.
- Add Open-Meteo fetcher.
- Normalize current, hourly, and daily data.
- Cache successful responses.
- Serve `/api/all`.
- Update frontend from local backend.

Success criteria:

```text
Current weather displays correctly
Hourly forecast displays correctly
Daily forecast displays correctly
Last-updated timestamp is visible
App handles internet outage gracefully
```

### Phase 3: Alert Integration

Goal: add official severe weather alerts for U.S. locations.

Tasks:

- Add NWS alert fetcher.
- Normalize alerts by severity and event type.
- Display alert banner when active alerts exist.
- Add expanded alert details view if desired.

Success criteria:

```text
Alerts appear when present
No-alert state is clean and unobtrusive
Severity is visually obvious
Long alert text does not overwhelm dashboard
```

### Phase 4: Kiosk Hardening

Goal: make the Pi behave like an appliance.

Tasks:

- Enable auto-login.
- Start backend via systemd.
- Launch Chromium kiosk at boot.
- Hide mouse cursor.
- Disable screen blanking.
- Add local logging.
- Add automatic restart behavior.

Success criteria:

```text
Power cycling the Pi returns directly to dashboard
No keyboard or mouse needed for normal operation
Dashboard recovers from temporary network failures
Backend restarts if it crashes
```

### Phase 5: Real-Time Enhancements

Goal: add true live data if desired.

Options:

- WeatherFlow Tempest WebSocket integration.
- Ambient Weather API integration.
- Local sensor hardware integration.

Success criteria:

```text
Wind speed and direction update every few seconds when supported by data source
Dashboard clearly identifies data source and last update time
Fallback forecast data still works if live source is unavailable
```

## 16. Performance Validation Plan

Before building the complete app, validate the Pi 4 with a mock dashboard.

Things to test:

- CPU usage with dashboard open.
- Memory usage with Chromium open.
- Temperature after 30 to 60 minutes.
- Throttling state.
- Smoothness of SVG/CSS animations.
- Display readability.
- Stability after reboot.

Commands:

```bash
free -h
vcgencmd measure_temp
vcgencmd get_throttled
top
```

Desired result:

```text
No swap pressure
CPU usage reasonable at idle
Temperature stable
throttled=0x0
Dashboard remains responsive
```

## 17. Configuration File

Use `config.yaml` for user-adjustable settings.

Example:

```yaml
location:
  name: "Milwaukee, WI"
  latitude: 43.0389
  longitude: -87.9065
  timezone: "America/Chicago"

units:
  temperature: "fahrenheit"
  wind_speed: "mph"
  precipitation: "inch"
  pressure: "inhg"

refresh:
  frontend_seconds: 15
  open_meteo_current_minutes: 5
  open_meteo_forecast_minutes: 30
  nws_alerts_minutes: 2

features:
  nws_alerts: true
  show_uv_index: true
  show_pressure: true
  show_sunrise_sunset: true
  enable_animations: true
```

## 18. Risk Register

| Risk | Impact | Mitigation |
|---|---|---|
| Public APIs do not update every 10 seconds | Dashboard may not show true live data | Use local UI refresh and accurate timestamps. Add personal weather station later if needed. |
| Pi 4 is a low-RAM model | Chromium may run poorly | Confirm RAM. Use lightweight frontend. Avoid native 3K resolution. |
| Display resolution is too demanding | UI may lag | Use 1920x1280 or 1920x1080. |
| Network outage | Dashboard may show stale data | Cache last successful data and show stale-data indicator. |
| API changes or rate limits | Data fetch failures | Isolate provider code. Add error handling and fallback. |
| Screen burn-in or image retention | Display degradation | Add subtle movement, dimming schedule, or theme rotation. |
| Weather data feels too static | User experience may feel less live | Animate UI honestly and add real-time personal station source later. |

## 19. Initial Implementation Milestone

The first milestone should be a working local dashboard with mocked data.

Milestone 1 deliverables:

```text
Raspberry Pi OS installed
Static dashboard visible in Chromium
Dashboard layout fits the 3:2 display
Clock updates every second
Mock wind compass animates smoothly
CPU and memory usage are acceptable
Pi boots reliably
```

Only after that should live API integration be added.

## 20. Recommended First Build Path

Start here:

```text
1. Install Raspberry Pi OS 64-bit Desktop.
2. Set display to 1920x1080 or 1920x1280.
3. Create static HTML/CSS dashboard mock.
4. Run it full-screen in Chromium.
5. Validate Pi performance.
6. Add FastAPI backend.
7. Add Open-Meteo data.
8. Add NWS alerts.
9. Add kiosk boot behavior.
10. Consider real-time personal weather station integration later.
```

## 21. Key Design Principle

The application should update visually every second, query the local backend every 10 to 15 seconds, and fetch public weather APIs responsibly every few minutes.

This creates the feel of a modern real-time weather station while remaining accurate, reliable, and respectful of free weather data services.

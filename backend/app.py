"""WeatherPi FastAPI application.

Serves normalized weather data on /api/* and the static dashboard at /.
A background poller (backend.cache.WeatherStore) keeps the data warm so every
request is a cache read.

Run:  uvicorn backend.app:app --host 127.0.0.1 --port 8000
"""

from __future__ import annotations

import logging
import os
import subprocess
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Optional

import httpx
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from backend import utils
from backend.cache import WeatherStore
from backend.live_wind import LiveWindManager
from backend.models import WeatherData
from backend.settings_store import SettingsStore

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("weatherpi")

FRONTEND_DIR = os.path.join(utils.PROJECT_ROOT, "frontend")


def _app_version() -> str:
    """Current git revision, computed once at startup. After an update + service
    restart this changes, which the frontend uses to auto-reload the kiosk."""
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=utils.PROJECT_ROOT, stderr=subprocess.DEVNULL, timeout=5,
        )
        return out.decode().strip() or "unknown"
    except Exception:  # noqa: BLE001 - not a git checkout / git missing
        return "unknown"


APP_VERSION = _app_version()


@asynccontextmanager
async def lifespan(app: FastAPI):
    cfg = utils.load_config()
    # User-chosen location (from the settings page) overrides the config default.
    settings = SettingsStore(cfg)
    cfg["location"] = {
        "name": settings.active["name"],
        "latitude": settings.active["latitude"],
        "longitude": settings.active["longitude"],
        "timezone": settings.active.get("timezone"),
    }
    store = WeatherStore(cfg)
    live_wind = LiveWindManager(cfg)
    app.state.store = store
    app.state.live_wind = live_wind
    app.state.settings = settings
    app.state.cfg = cfg
    log.info("Starting WeatherPi poller for %s", cfg["location"]["name"])
    await store.start()
    await live_wind.start()
    try:
        yield
    finally:
        await live_wind.stop()
        await store.stop()


app = FastAPI(title="WeatherPi", version="0.1.0", lifespan=lifespan)


def _store() -> WeatherStore:
    return app.state.store


@app.get("/api/all", response_model=WeatherData)
async def get_all() -> WeatherData:
    """Everything the dashboard needs in one call."""
    return _store().data


@app.get("/api/current")
async def get_current():
    return _store().data.current


@app.get("/api/hourly")
async def get_hourly():
    return _store().data.hourly


@app.get("/api/daily")
async def get_daily():
    return _store().data.daily


@app.get("/api/alerts")
async def get_alerts():
    return _store().data.alerts


@app.get("/api/air_quality")
async def get_air_quality():
    return _store().data.air_quality


@app.get("/api/nowcast")
async def get_nowcast():
    return _store().data.nowcast


@app.get("/api/status")
async def get_status():
    return _store().data.status


@app.get("/api/config")
async def get_config():
    """Expose only the frontend-relevant slice of config (units, refresh, features)."""
    cfg = app.state.cfg
    return JSONResponse(
        {
            "location": cfg.get("location", {}),
            "units": cfg.get("units", {}),
            "refresh": cfg.get("refresh", {}),
            "features": cfg.get("features", {}),
            "wind": cfg.get("wind", {}),
            "live_wind": cfg.get("live_wind", {}),
        }
    )


# --- Settings: active location + preset locations --------------------------

class LocationIn(BaseModel):
    name: str
    latitude: float
    longitude: float
    timezone: Optional[str] = None


class PresetsIn(BaseModel):
    presets: list[LocationIn]


def _settings() -> SettingsStore:
    return app.state.settings


@app.get("/api/settings")
async def get_settings():
    """Active location and saved presets, for the settings page."""
    return _settings().as_dict()


@app.post("/api/settings/location")
async def set_location(loc: LocationIn):
    """Switch the active weather-station location and re-fetch immediately."""
    try:
        stored = _settings().set_active(loc.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    await _store().set_location(stored)
    await app.state.live_wind.restart()
    return _settings().as_dict()


@app.put("/api/settings/presets")
async def set_presets(body: PresetsIn):
    """Replace the saved preset list (max 4)."""
    _settings().set_presets([p.model_dump() for p in body.presets])
    return _settings().as_dict()


@app.get("/api/geocode")
async def geocode(q: str):
    """Search place names → coordinates + timezone via Open-Meteo's free
    geocoding API, so users can pick a location without knowing lat/long."""
    q = (q or "").strip()
    if len(q) < 2:
        return {"results": []}
    try:
        async with httpx.AsyncClient(headers={"User-Agent": "WeatherPi/0.1"}) as client:
            r = await client.get(
                "https://geocoding-api.open-meteo.com/v1/search",
                params={"name": q, "count": 6, "language": "en", "format": "json"},
                timeout=10.0,
            )
            r.raise_for_status()
            data = r.json()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"geocoding failed: {exc}")
    results = []
    for x in data.get("results", []) or []:
        parts = [x.get("name")]
        if x.get("admin1"):
            parts.append(x["admin1"])
        if x.get("country_code"):
            parts.append(x["country_code"])
        results.append(
            {
                "name": ", ".join(p for p in parts if p),
                "latitude": x.get("latitude"),
                "longitude": x.get("longitude"),
                "timezone": x.get("timezone"),
            }
        )
    return {"results": results}


def _age_seconds(iso: Optional[str]) -> Optional[float]:
    if not iso:
        return None
    try:
        then = datetime.fromisoformat(iso)
        now = datetime.now(timezone.utc).astimezone(then.tzinfo)
        return round((now - then).total_seconds(), 1)
    except Exception:  # noqa: BLE001
        return None


@app.get("/api/raw")
async def get_raw():
    """Full, unfiltered data from every source plus freshness, for the status
    page — including fields the main dashboard doesn't display."""
    store = _store()
    data = store.data
    mgr = app.state.live_wind
    now_iso = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")

    sources = [
        {
            "name": data.status.source or "open-meteo",
            "role": "Forecast & current conditions",
            "fetched_at": store.fetched_at.get("weather"),
            "age_seconds": _age_seconds(store.fetched_at.get("weather")),
            "ok": data.status.api_ok,
            "error": data.status.last_error,
        },
        {
            "name": "open-meteo air-quality",
            "role": "Air quality (US AQI, PM, ozone, NO₂)",
            "fetched_at": store.fetched_at.get("air_quality"),
            "age_seconds": _age_seconds(store.fetched_at.get("air_quality")),
            "ok": data.air_quality is not None,
            "error": None,
        },
        {
            "name": "nws-alerts",
            "role": "Severe-weather alerts",
            "fetched_at": store.fetched_at.get("alerts"),
            "age_seconds": _age_seconds(store.fetched_at.get("alerts")),
            "ok": True,
            "error": None,
        },
    ]

    live = mgr.latest.model_dump() if getattr(mgr, "latest", None) else None
    live_wind = {
        "enabled": mgr.enabled,
        "source": mgr.source,
        "latest": live,
        "age_seconds": _age_seconds(live.get("observed_at")) if live else None,
    }

    return JSONResponse(
        {
            "server_time": now_iso,
            "location": data.location.model_dump(),
            "status": data.status.model_dump(),
            "current": data.current.model_dump() if data.current else None,
            "air_quality": data.air_quality.model_dump() if data.air_quality else None,
            "nowcast": data.nowcast.model_dump() if data.nowcast else None,
            "alerts": [a.model_dump() for a in data.alerts],
            "hourly": [h.model_dump() for h in data.hourly],
            "daily": [d.model_dump() for d in data.daily],
            "live_wind": live_wind,
            "sources": sources,
        }
    )


@app.get("/healthz")
async def healthz():
    return {"ok": True, "api_ok": _store().data.status.api_ok}


@app.get("/api/version")
async def get_version():
    """Running code revision; the frontend reloads when this changes."""
    return {"version": APP_VERSION}


@app.websocket("/ws/live")
async def ws_live(websocket: WebSocket):
    """Push live wind observations to the dashboard as they arrive."""
    await websocket.accept()
    mgr: LiveWindManager = app.state.live_wind
    await mgr.connect(websocket)
    try:
        # We don't expect client messages; receiving just detects disconnect.
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    except Exception:  # noqa: BLE001
        pass
    finally:
        mgr.disconnect(websocket)


# Mount the static dashboard last so /api/* and /ws/* routes take precedence.
if os.path.isdir(FRONTEND_DIR):
    app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")

"""WeatherPi FastAPI application.

Serves normalized weather data on /api/* and the static dashboard at /.
A background poller (backend.cache.WeatherStore) keeps the data warm so every
request is a cache read.

Run:  uvicorn backend.app:app --host 127.0.0.1 --port 8000
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from backend import utils
from backend.cache import WeatherStore
from backend.live_wind import LiveWindManager
from backend.models import WeatherData

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("weatherpi")

FRONTEND_DIR = os.path.join(utils.PROJECT_ROOT, "frontend")


@asynccontextmanager
async def lifespan(app: FastAPI):
    cfg = utils.load_config()
    store = WeatherStore(cfg)
    live_wind = LiveWindManager(cfg)
    app.state.store = store
    app.state.live_wind = live_wind
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


@app.get("/healthz")
async def healthz():
    return {"ok": True, "api_ok": _store().data.status.api_ok}


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

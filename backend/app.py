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

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from backend import utils
from backend.cache import WeatherStore
from backend.models import WeatherData

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("weatherpi")

FRONTEND_DIR = os.path.join(utils.PROJECT_ROOT, "frontend")


@asynccontextmanager
async def lifespan(app: FastAPI):
    cfg = utils.load_config()
    store = WeatherStore(cfg)
    app.state.store = store
    app.state.cfg = cfg
    log.info("Starting WeatherPi poller for %s", cfg["location"]["name"])
    await store.start()
    try:
        yield
    finally:
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
        }
    )


@app.get("/healthz")
async def healthz():
    return {"ok": True, "api_ok": _store().data.status.api_ok}


# Mount the static dashboard last so /api/* routes take precedence.
if os.path.isdir(FRONTEND_DIR):
    app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")

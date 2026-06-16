"""Live wind manager: runs a pluggable wind source and broadcasts observations
to connected /ws/live WebSocket clients.

Sources (selected via config `live_wind.source`):
  - "nws_station": real measured wind from the nearest NWS station (free)
  - "simulator":   smoothly-varying fake wind for demoing the live path
  - "off":         disabled (frontend falls back to forecast wind)

A real Tempest/Ambient/GPIO source later just needs to call `_publish(obs)` on
the same manager — the WebSocket and frontend require no changes.
"""

from __future__ import annotations

import asyncio
import logging
import random
from datetime import datetime, timezone
from typing import Optional, Set

import httpx

from backend import utils
from backend.models import WindObservation
from backend.weather_sources import nws_station

log = logging.getLogger("weatherpi.live_wind")


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


class LiveWindManager:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.lw = cfg.get("live_wind", {}) or {}
        self.enabled = bool(self.lw.get("enabled"))
        self.source = (self.lw.get("source") or "off").lower()
        self.latest: Optional[WindObservation] = None
        self._clients: Set = set()
        self._client: Optional[httpx.AsyncClient] = None
        self._task: Optional[asyncio.Task] = None

    # --- lifecycle ---------------------------------------------------------

    async def start(self) -> None:
        if not self.enabled or self.source in ("off", "none", ""):
            log.info("Live wind disabled (source=%s)", self.source)
            return
        self._client = httpx.AsyncClient(headers={"User-Agent": "WeatherPi/0.1"})
        if self.source == "simulator":
            self._task = asyncio.create_task(self._run_simulator())
        elif self.source == "nws_station":
            self._task = asyncio.create_task(self._run_nws_station())
        else:
            log.warning("Unknown live_wind source: %s (disabling)", self.source)

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        for ws in list(self._clients):
            try:
                await ws.close()
            except Exception:  # noqa: BLE001
                pass
        self._clients.clear()
        if self._client:
            await self._client.aclose()

    # --- websocket registry ------------------------------------------------

    async def connect(self, ws) -> None:
        self._clients.add(ws)
        if self.latest is not None:
            await self._send(ws, self.latest)

    def disconnect(self, ws) -> None:
        self._clients.discard(ws)

    async def _send(self, ws, obs: WindObservation) -> bool:
        try:
            payload = obs.model_dump()
            payload["type"] = "wind"
            await ws.send_json(payload)
            return True
        except Exception:  # noqa: BLE001 - client went away
            return False

    async def _publish(self, obs: WindObservation) -> None:
        self.latest = obs
        for ws in list(self._clients):
            if not await self._send(ws, obs):
                self._clients.discard(ws)

    # --- sources -----------------------------------------------------------

    async def _run_simulator(self) -> None:
        sim = self.lw.get("simulator", {}) or {}
        interval = max(0.5, float(sim.get("update_seconds", 2)))
        base = float(sim.get("base_speed_mph", 8))
        speed, direction = base, 200.0
        log.info("Live wind: simulator started (base=%s mph, every %ss)", base, interval)
        while True:
            speed = max(0.0, min(base * 2.6, speed + random.uniform(-1.5, 1.5)))
            gust = speed + random.uniform(1.0, 6.0)
            direction = (direction + random.uniform(-9, 9)) % 360
            await self._publish(
                WindObservation(
                    wind_speed_mph=round(speed, 1),
                    wind_gust_mph=round(gust, 1),
                    wind_direction_deg=round(direction),
                    wind_direction_cardinal=utils.deg_to_cardinal(direction),
                    observed_at=_now_iso(),
                    source="simulator",
                    live=True,
                    interval_seconds=interval,
                )
            )
            await asyncio.sleep(interval)

    async def _run_nws_station(self) -> None:
        poll = max(60, int(self.lw.get("poll_seconds", 180)))
        station = None
        while station is None:
            try:
                station = await nws_station.resolve_station(self.cfg, self._client)
                if station is None:
                    raise RuntimeError("no station found for location")
            except Exception as exc:  # noqa: BLE001
                log.warning("NWS station resolve failed: %s (retry in 60s)", exc)
                await asyncio.sleep(60)
        sid, name = station
        log.info("Live wind: NWS station %s (%s), polling every %ss", sid, name, poll)
        while True:
            try:
                obs = await nws_station.latest(self.cfg, self._client, sid)
                if obs:
                    obs.interval_seconds = poll
                    await self._publish(obs)
                    log.info(
                        "Live wind obs %s: %s mph gust %s @ %s°",
                        sid, obs.wind_speed_mph, obs.wind_gust_mph, obs.wind_direction_deg,
                    )
            except Exception as exc:  # noqa: BLE001
                log.warning("NWS station obs failed: %s", exc)
            await asyncio.sleep(poll)

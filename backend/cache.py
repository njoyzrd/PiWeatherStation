"""In-memory store + background poller.

Holds the latest normalized WeatherData and refreshes it on a timer so the
frontend only ever reads from a warm cache. On a failed fetch we keep the last
good data and flag it stale rather than serving nothing.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

import httpx

from backend import utils
from backend.models import Location, Status, WeatherData
from backend.weather_sources import nws, open_meteo

log = logging.getLogger("weatherpi.cache")


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


class WeatherStore:
    """Single source of truth for the latest weather data."""

    def __init__(self, cfg: dict):
        self.cfg = cfg
        loc = cfg["location"]
        self._data = WeatherData(
            location=Location(
                name=loc["name"],
                latitude=loc["latitude"],
                longitude=loc["longitude"],
                timezone=loc.get("timezone"),
            ),
            status=Status(api_ok=False, stale=True, last_error="No data fetched yet"),
        )
        self._client: Optional[httpx.AsyncClient] = None
        self._tasks: list[asyncio.Task] = []

    @property
    def data(self) -> WeatherData:
        return self._data

    # --- lifecycle ---------------------------------------------------------

    async def start(self) -> None:
        self._client = httpx.AsyncClient(headers={"User-Agent": "WeatherPi/0.1"})
        # Prime once so the first request after boot has data, then poll on timers.
        await self._refresh_weather()
        self._tasks.append(asyncio.create_task(self._weather_loop()))
        if self.cfg.get("features", {}).get("nws_alerts"):
            self._tasks.append(asyncio.create_task(self._alerts_loop()))

    async def stop(self) -> None:
        for t in self._tasks:
            t.cancel()
        for t in self._tasks:
            try:
                await t
            except asyncio.CancelledError:
                pass
        self._tasks.clear()
        if self._client:
            await self._client.aclose()

    # --- poll loops --------------------------------------------------------

    async def _weather_loop(self) -> None:
        refresh = self.cfg.get("refresh", {})
        interval = max(60, int(refresh.get("open_meteo_current_minutes", 5)) * 60)
        retry = int(refresh.get("retry_seconds", 30))
        while True:
            await asyncio.sleep(interval if self._data.status.api_ok else retry)
            await self._refresh_weather()

    async def _alerts_loop(self) -> None:
        refresh = self.cfg.get("refresh", {})
        interval = max(60, int(refresh.get("nws_alerts_minutes", 2)) * 60)
        while True:
            await self._refresh_alerts()
            await asyncio.sleep(interval)

    # --- refreshers --------------------------------------------------------

    async def _refresh_weather(self) -> None:
        try:
            location, current, hourly, daily = await open_meteo.fetch(self.cfg, self._client)
            self._data.location = location
            self._data.current = current
            self._data.hourly = hourly
            self._data.daily = daily
            self._data.status = Status(
                api_ok=True,
                stale=False,
                last_successful_refresh=_now_iso(),
                last_error=None,
            )
            log.info("Weather refreshed: %s°F, %s", current.temperature_f, current.condition_text)
        except Exception as exc:  # noqa: BLE001 - keep serving stale data on any failure
            self._data.status.api_ok = False
            self._data.status.stale = True
            self._data.status.last_error = f"{type(exc).__name__}: {exc}"
            log.warning("Weather refresh failed: %s", exc)

    async def _refresh_alerts(self) -> None:
        try:
            self._data.alerts = await nws.fetch(self.cfg, self._client)
        except Exception as exc:  # noqa: BLE001
            log.warning("Alerts refresh failed: %s", exc)

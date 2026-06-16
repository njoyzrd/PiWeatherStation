"""Open-Meteo provider: fetches current conditions + hourly/daily forecast and
normalizes the response into backend.models structures.

Open-Meteo is free for non-commercial use and needs no API key.
Docs: https://open-meteo.com/en/docs
"""

from __future__ import annotations

from typing import List, Tuple

import httpx

from backend import utils
from backend.models import Current, DailyPoint, HourlyPoint, Location

BASE_URL = "https://api.open-meteo.com/v1/forecast"

CURRENT_FIELDS = [
    "temperature_2m",
    "relative_humidity_2m",
    "apparent_temperature",
    "is_day",
    "precipitation",
    "weather_code",
    "cloud_cover",
    "pressure_msl",
    "wind_speed_10m",
    "wind_direction_10m",
    "wind_gusts_10m",
    "uv_index",
]

HOURLY_FIELDS = [
    "temperature_2m",
    "apparent_temperature",
    "precipitation_probability",
    "weather_code",
    "wind_speed_10m",
    "is_day",
]

DAILY_FIELDS = [
    "weather_code",
    "temperature_2m_max",
    "temperature_2m_min",
    "sunrise",
    "sunset",
    "precipitation_probability_max",
    "uv_index_max",
]


def _build_params(cfg: dict) -> dict:
    loc = cfg["location"]
    units = cfg.get("units", {})
    return {
        "latitude": loc["latitude"],
        "longitude": loc["longitude"],
        "current": ",".join(CURRENT_FIELDS),
        "hourly": ",".join(HOURLY_FIELDS),
        "daily": ",".join(DAILY_FIELDS),
        "temperature_unit": units.get("temperature", "fahrenheit"),
        "wind_speed_unit": units.get("wind_speed", "mph"),
        "precipitation_unit": units.get("precipitation", "inch"),
        "timezone": loc.get("timezone") or "auto",
        "forecast_days": 7,
    }


def _normalize_current(data: dict) -> Current:
    cur = data.get("current", {}) or {}
    code = cur.get("weather_code")
    is_day = bool(cur.get("is_day", 1))
    humidity = cur.get("relative_humidity_2m")
    temp_f = cur.get("temperature_2m")

    # sunrise/sunset for "today" come from the daily block (first entry).
    daily = data.get("daily", {}) or {}
    sunrise = (daily.get("sunrise") or [None])[0]
    sunset = (daily.get("sunset") or [None])[0]

    return Current(
        temperature_f=temp_f,
        feels_like_f=cur.get("apparent_temperature"),
        humidity_pct=humidity,
        dew_point_f=utils.dew_point_f(temp_f, humidity),
        pressure_inhg=utils.hpa_to_inhg(cur.get("pressure_msl")),
        cloud_cover_pct=cur.get("cloud_cover"),
        wind_speed_mph=cur.get("wind_speed_10m"),
        wind_gust_mph=cur.get("wind_gusts_10m"),
        wind_direction_deg=cur.get("wind_direction_10m"),
        wind_direction_cardinal=utils.deg_to_cardinal(cur.get("wind_direction_10m")),
        condition_code=code,
        condition_text=utils.wmo_text(code),
        condition_icon=utils.wmo_icon(code, is_day),
        is_day=is_day,
        uv_index=cur.get("uv_index"),
        precip_rate_in=cur.get("precipitation"),
        sunrise=sunrise,
        sunset=sunset,
        updated_at=cur.get("time"),
        source="open-meteo",
    )


def _normalize_hourly(data: dict, limit: int) -> List[HourlyPoint]:
    h = data.get("hourly", {}) or {}
    times = h.get("time", []) or []

    # Open-Meteo returns hourly data starting at midnight; start the strip at the
    # current hour so the dashboard shows upcoming hours, not ones already past.
    start = 0
    cur_time = (data.get("current", {}) or {}).get("time")
    if cur_time:
        hour_prefix = cur_time[:13]  # "YYYY-MM-DDTHH"
        for idx, t in enumerate(times):
            if t[:13] >= hour_prefix:
                start = idx
                break
    times = times[start : start + limit]

    out: List[HourlyPoint] = []
    for i_off, t in enumerate(times):
        i = start + i_off
        code = _at(h.get("weather_code"), i)
        is_day = bool(_at(h.get("is_day"), i, 1))
        out.append(
            HourlyPoint(
                time=t,
                temperature_f=_at(h.get("temperature_2m"), i),
                feels_like_f=_at(h.get("apparent_temperature"), i),
                precip_probability_pct=_at(h.get("precipitation_probability"), i),
                condition_code=code,
                condition_icon=utils.wmo_icon(code, is_day),
                wind_speed_mph=_at(h.get("wind_speed_10m"), i),
                is_day=is_day,
            )
        )
    return out


def _normalize_daily(data: dict, limit: int) -> List[DailyPoint]:
    d = data.get("daily", {}) or {}
    dates = d.get("time", []) or []
    out: List[DailyPoint] = []
    for i, date in enumerate(dates[:limit]):
        code = _at(d.get("weather_code"), i)
        out.append(
            DailyPoint(
                date=date,
                temp_max_f=_at(d.get("temperature_2m_max"), i),
                temp_min_f=_at(d.get("temperature_2m_min"), i),
                condition_code=code,
                condition_text=utils.wmo_text(code),
                condition_icon=utils.wmo_icon(code, True),
                precip_probability_pct=_at(d.get("precipitation_probability_max"), i),
                uv_index_max=_at(d.get("uv_index_max"), i),
                sunrise=_at(d.get("sunrise"), i),
                sunset=_at(d.get("sunset"), i),
            )
        )
    return out


def _at(seq, i, default=None):
    if not seq or i >= len(seq):
        return default
    return seq[i]


async def fetch(cfg: dict, client: httpx.AsyncClient) -> Tuple[Location, Current, List[HourlyPoint], List[DailyPoint]]:
    """Fetch and normalize the full Open-Meteo payload. Raises on network/HTTP error."""
    params = _build_params(cfg)
    resp = await client.get(BASE_URL, params=params, timeout=15.0)
    resp.raise_for_status()
    data = resp.json()

    loc_cfg = cfg["location"]
    location = Location(
        name=loc_cfg["name"],
        latitude=loc_cfg["latitude"],
        longitude=loc_cfg["longitude"],
        timezone=data.get("timezone") or loc_cfg.get("timezone"),
    )

    fc = cfg.get("forecast", {})
    current = _normalize_current(data)
    hourly = _normalize_hourly(data, fc.get("hourly_hours", 24))
    daily = _normalize_daily(data, fc.get("daily_days", 7))
    return location, current, hourly, daily

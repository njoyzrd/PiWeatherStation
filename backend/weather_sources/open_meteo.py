"""Open-Meteo provider: fetches current conditions + hourly/daily forecast,
a short-term precipitation nowcast, and derived fields (visibility, pressure
trend, moon phase), normalized into backend.models structures.

Open-Meteo is free for non-commercial use and needs no API key.
Docs: https://open-meteo.com/en/docs
"""

from __future__ import annotations

from typing import List, Optional, Tuple

import httpx

from backend import utils
from backend.models import Current, DailyPoint, HourlyPoint, Location, Nowcast, NowcastPoint

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
    "visibility",
]

HOURLY_FIELDS = [
    "temperature_2m",
    "apparent_temperature",
    "precipitation_probability",
    "weather_code",
    "wind_speed_10m",
    "is_day",
    "pressure_msl",
]

DAILY_FIELDS = [
    "weather_code",
    "temperature_2m_max",
    "temperature_2m_min",
    "sunrise",
    "sunset",
    "precipitation_probability_max",
    "snowfall_sum",
    "uv_index_max",
]

PRECIP_EPS = 0.001  # inches per 15 min below this is treated as "no precip"


def _build_params(cfg: dict) -> dict:
    loc = cfg["location"]
    units = cfg.get("units", {})
    return {
        "latitude": loc["latitude"],
        "longitude": loc["longitude"],
        "current": ",".join(CURRENT_FIELDS),
        "hourly": ",".join(HOURLY_FIELDS),
        "daily": ",".join(DAILY_FIELDS),
        "minutely_15": "precipitation",
        "past_hours": 3,  # so we can compute a 3-hour pressure trend
        "temperature_unit": units.get("temperature", "fahrenheit"),
        "wind_speed_unit": units.get("wind_speed", "mph"),
        "precipitation_unit": units.get("precipitation", "inch"),
        "timezone": loc.get("timezone") or "auto",
        "forecast_days": 7,
    }


def _at(seq, i, default=None):
    if not seq or i < 0 or i >= len(seq):
        return default
    return seq[i]


def _current_hour_index(data: dict) -> Optional[int]:
    h = data.get("hourly", {}) or {}
    times = h.get("time", []) or []
    cur_time = (data.get("current", {}) or {}).get("time")
    if not cur_time:
        return None
    prefix = cur_time[:13]  # YYYY-MM-DDTHH
    for idx, t in enumerate(times):
        if t[:13] >= prefix:
            return idx
    return None


def _pressure_trend(data: dict) -> Tuple[Optional[str], Optional[float]]:
    """Compare current pressure to ~3 hours ago. Returns (trend, change_inhg)."""
    idx = _current_hour_index(data)
    if idx is None:
        return None, None
    pressures = (data.get("hourly", {}) or {}).get("pressure_msl") or []
    now = _at(pressures, idx)
    past = _at(pressures, idx - 3)
    if now is None or past is None:
        return None, None
    delta_hpa = now - past
    change_inhg = round(delta_hpa * 0.0295299830714, 2)
    if delta_hpa >= 0.6:
        return "rising", change_inhg
    if delta_hpa <= -0.6:
        return "falling", change_inhg
    return "steady", change_inhg


def _normalize_current(data: dict) -> Current:
    cur = data.get("current", {}) or {}
    code = cur.get("weather_code")
    is_day = bool(cur.get("is_day", 1))
    humidity = cur.get("relative_humidity_2m")
    temp_f = cur.get("temperature_2m")

    daily = data.get("daily", {}) or {}
    # First daily entry corresponds to today (past_hours doesn't shift daily).
    sunrise = (daily.get("sunrise") or [None])[0]
    sunset = (daily.get("sunset") or [None])[0]

    trend, change_inhg = _pressure_trend(data)
    frac, moon_name, moon_icon = utils.moon_phase()

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
        visibility_mi=utils.ft_to_mi(cur.get("visibility")),
        pressure_trend=trend,
        pressure_change_inhg=change_inhg,
        moon_phase=frac,
        moon_phase_name=moon_name,
        moon_icon=moon_icon,
        sunrise=sunrise,
        sunset=sunset,
        updated_at=cur.get("time"),
        source="open-meteo",
    )


def _normalize_hourly(data: dict, limit: int) -> List[HourlyPoint]:
    h = data.get("hourly", {}) or {}
    times = h.get("time", []) or []

    # Hourly data starts at midnight (and includes past_hours); start the strip
    # at the current hour so the dashboard shows upcoming hours.
    start = _current_hour_index(data) or 0
    window = times[start : start + limit]

    out: List[HourlyPoint] = []
    for i_off, t in enumerate(window):
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
                pressure_inhg=utils.hpa_to_inhg(_at(h.get("pressure_msl"), i)),
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
                snowfall_in=_at(d.get("snowfall_sum"), i),
                uv_index_max=_at(d.get("uv_index_max"), i),
                sunrise=_at(d.get("sunrise"), i),
                sunset=_at(d.get("sunset"), i),
            )
        )
    return out


def _normalize_nowcast(data: dict, slots: int = 8) -> Optional[Nowcast]:
    """Build a next-~2-hour precipitation nowcast from minutely_15 data."""
    m = data.get("minutely_15", {}) or {}
    times = m.get("time", []) or []
    precip = m.get("precipitation", []) or []
    if not times:
        return None
    cur_time = (data.get("current", {}) or {}).get("time")
    if not cur_time:
        return None

    start = next((i for i, t in enumerate(times) if t >= cur_time), None)
    if start is None:
        return None

    points: List[NowcastPoint] = []
    starts_in: Optional[int] = None
    for k in range(slots):
        i = start + k
        p = _at(precip, i)
        points.append(NowcastPoint(minute_offset=k * 15, precip_in=p))
        if starts_in is None and p is not None and p > PRECIP_EPS:
            starts_in = k * 15

    precipitating = bool(points and points[0].precip_in and points[0].precip_in > PRECIP_EPS)
    if precipitating:
        summary = "Precipitation now"
        starts_in = 0
    elif starts_in is not None:
        summary = f"Precip starting in ~{starts_in} min" if starts_in else "Precipitation now"
    else:
        summary = "No precip in the next 2 hours"

    return Nowcast(summary=summary, starts_in_min=starts_in, precipitating=precipitating, points=points)


async def fetch(
    cfg: dict, client: httpx.AsyncClient
) -> Tuple[Location, Current, List[HourlyPoint], List[DailyPoint], Optional[Nowcast]]:
    """Fetch and normalize the full Open-Meteo payload. Raises on network/HTTP error."""
    resp = await client.get(BASE_URL, params=_build_params(cfg), timeout=15.0)
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
    nowcast = _normalize_nowcast(data)
    return location, current, hourly, daily, nowcast

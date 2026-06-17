"""MET Norway (Yr) Locationforecast — free global forecast used as a FALLBACK
when Open-Meteo is unavailable, so an always-on display degrades gracefully
instead of going stale.

Free, no API key, but REQUIRES an identifying User-Agent.
Docs: https://api.met.no/weatherapi/locationforecast/2.0/documentation
"""

from __future__ import annotations

from typing import List, Optional, Tuple

import httpx

from backend import utils
from backend.models import Current, DailyPoint, HourlyPoint, Location

BASE_URL = "https://api.met.no/weatherapi/locationforecast/2.0/compact"


def _user_agent(cfg: dict) -> str:
    contact = (cfg.get("alerts", {}) or {}).get("contact") or "https://github.com/njoyzrd/PiWeatherStation"
    return f"WeatherPi/0.1 ({contact})"


def _condition(symbol: Optional[str], is_day: bool) -> Tuple[str, str]:
    s = (symbol or "").lower()
    if "thunder" in s:
        return "Thunderstorm", "⛈️"
    if "snow" in s:
        return ("Light snow", "🌨️") if "light" in s else ("Snow", "❄️")
    if "sleet" in s:
        return "Sleet", "🌨️"
    if "rain" in s:
        if "heavy" in s:
            return "Heavy rain", "🌧️"
        if "light" in s:
            return "Light rain", "🌦️"
        return "Rain", "🌧️"
    if "fog" in s:
        return "Fog", "🌫️"
    if "partlycloudy" in s:
        return "Partly cloudy", "⛅" if is_day else "☁️"
    if "cloudy" in s:
        return "Cloudy", "☁️"
    if "fair" in s:
        return "Mostly clear", "🌤️" if is_day else "🌙"
    if "clear" in s:
        return "Clear", "☀️" if is_day else "🌙"
    return "Cloudy", "☁️"


def _symbol(entry: dict) -> Optional[str]:
    data = entry.get("data", {}) or {}
    for key in ("next_1_hours", "next_6_hours", "next_12_hours"):
        sym = (data.get(key, {}) or {}).get("summary", {}).get("symbol_code")
        if sym:
            return sym
    return None


def _precip_in(entry: dict) -> Optional[float]:
    data = entry.get("data", {}) or {}
    for key in ("next_1_hours", "next_6_hours"):
        amt = (data.get(key, {}) or {}).get("details", {}).get("precipitation_amount")
        if amt is not None:
            return round(amt / 25.4, 2)  # mm -> inch
    return None


def _prob(entry: dict) -> Optional[float]:
    data = entry.get("data", {}) or {}
    for key in ("next_1_hours", "next_6_hours"):
        p = (data.get(key, {}) or {}).get("details", {}).get("probability_of_precipitation")
        if p is not None:
            return p
    return None


def _normalize_current(ts: List[dict]) -> Current:
    entry = ts[0]
    det = entry["data"]["instant"]["details"]
    symbol = _symbol(entry)
    is_day = "_night" not in (symbol or "")
    temp_f = utils.c_to_f(det.get("air_temperature"))
    humidity = det.get("relative_humidity")
    text, icon = _condition(symbol, is_day)
    frac, moon_name, moon_icon = utils.moon_phase()
    wd = det.get("wind_from_direction")
    return Current(
        temperature_f=round(temp_f, 1) if temp_f is not None else None,
        humidity_pct=humidity,
        dew_point_f=utils.dew_point_f(temp_f, humidity),
        pressure_inhg=utils.hpa_to_inhg(det.get("air_pressure_at_sea_level")),
        cloud_cover_pct=det.get("cloud_area_fraction"),
        wind_speed_mph=utils.ms_to_mph(det.get("wind_speed")),
        wind_direction_deg=wd,
        wind_direction_cardinal=utils.deg_to_cardinal(wd),
        condition_text=text,
        condition_icon=icon,
        is_day=is_day,
        precip_rate_in=_precip_in(entry),
        moon_phase=frac,
        moon_phase_name=moon_name,
        moon_icon=moon_icon,
        updated_at=entry.get("time"),
        source="met.no",
    )


def _normalize_hourly(ts: List[dict], limit: int) -> List[HourlyPoint]:
    out: List[HourlyPoint] = []
    for entry in ts[:limit]:
        det = entry["data"]["instant"]["details"]
        symbol = _symbol(entry)
        is_day = "_night" not in (symbol or "")
        _, icon = _condition(symbol, is_day)
        temp_f = utils.c_to_f(det.get("air_temperature"))
        out.append(
            HourlyPoint(
                time=entry.get("time"),
                temperature_f=round(temp_f, 1) if temp_f is not None else None,
                precip_probability_pct=_prob(entry),
                condition_icon=icon,
                wind_speed_mph=utils.ms_to_mph(det.get("wind_speed")),
                pressure_inhg=utils.hpa_to_inhg(det.get("air_pressure_at_sea_level")),
                is_day=is_day,
            )
        )
    return out


def _normalize_daily(ts: List[dict], limit: int) -> List[DailyPoint]:
    # Group timeseries entries by calendar date (UTC) and summarize.
    by_date: dict = {}
    for entry in ts:
        date = (entry.get("time") or "")[:10]
        if not date:
            continue
        by_date.setdefault(date, []).append(entry)

    out: List[DailyPoint] = []
    for date in sorted(by_date)[:limit]:
        entries = by_date[date]
        temps = [
            e["data"]["instant"]["details"].get("air_temperature")
            for e in entries
            if e["data"]["instant"]["details"].get("air_temperature") is not None
        ]
        temps_f = [utils.c_to_f(t) for t in temps]
        # Representative symbol: prefer an entry near midday.
        midday = min(entries, key=lambda e: abs(int((e.get("time") or "T12")[11:13] or 12) - 12))
        symbol = _symbol(midday)
        text, icon = _condition(symbol, True)
        probs = [p for p in (_prob(e) for e in entries) if p is not None]
        out.append(
            DailyPoint(
                date=date,
                temp_max_f=round(max(temps_f), 1) if temps_f else None,
                temp_min_f=round(min(temps_f), 1) if temps_f else None,
                condition_text=text,
                condition_icon=icon,
                precip_probability_pct=max(probs) if probs else None,
            )
        )
    return out


async def fetch(
    cfg: dict, client: httpx.AsyncClient
) -> Tuple[Location, Current, List[HourlyPoint], List[DailyPoint]]:
    """Fetch and normalize MET Norway forecast. Raises on network/HTTP error."""
    loc = cfg["location"]
    resp = await client.get(
        BASE_URL,
        params={"lat": loc["latitude"], "lon": loc["longitude"]},
        headers={"User-Agent": _user_agent(cfg)},
        timeout=15.0,
    )
    resp.raise_for_status()
    ts = resp.json()["properties"]["timeseries"]

    location = Location(
        name=loc["name"], latitude=loc["latitude"], longitude=loc["longitude"],
        timezone=loc.get("timezone"),
    )
    fc = cfg.get("forecast", {})
    current = _normalize_current(ts)
    hourly = _normalize_hourly(ts, fc.get("hourly_hours", 24))
    daily = _normalize_daily(ts, fc.get("daily_days", 7))
    return location, current, hourly, daily

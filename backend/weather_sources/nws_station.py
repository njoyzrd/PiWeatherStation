"""Nearest NWS observation station as a (near-)live wind source (U.S. only).

Resolves the closest official observation station (airport/ASOS) to the
configured point, then reads its latest measured wind. Free, no API key.
These are *real measurements* but typically refresh every ~20-60 min, so they
are surfaced as observations (live=False), not second-by-second data.

Reference: https://www.weather.gov/documentation/services-web-api
"""

from __future__ import annotations

from typing import Optional, Tuple

import httpx

from backend import utils
from backend.models import WindObservation
from backend.weather_sources.nws import _user_agent

POINTS_URL = "https://api.weather.gov/points/{lat},{lon}"
LATEST_OBS_URL = "https://api.weather.gov/stations/{sid}/observations/latest"


def _to_mph(field: Optional[dict]) -> Optional[float]:
    """Convert an NWS quantitative value ({unitCode, value}) to mph."""
    if not field:
        return None
    v = field.get("value")
    if v is None:
        return None
    unit = (field.get("unitCode") or "").lower()
    if "km_h" in unit or "km/h" in unit:
        return round(v * 0.621371, 1)
    if "m_s" in unit or "m/s" in unit:
        return round(v * 2.236936, 1)
    if "mi_h" in unit or "mph" in unit:
        return round(v, 1)
    # NWS default for wind is km/h; assume that if unspecified.
    return round(v * 0.621371, 1)


def _headers(cfg: dict) -> dict:
    return {"User-Agent": _user_agent(cfg), "Accept": "application/geo+json"}


async def resolve_station(cfg: dict, client: httpx.AsyncClient) -> Optional[Tuple[str, str]]:
    """Return (station_id, station_name) for the nearest observation station."""
    loc = cfg["location"]
    r = await client.get(
        POINTS_URL.format(lat=loc["latitude"], lon=loc["longitude"]),
        headers=_headers(cfg), timeout=15.0,
    )
    r.raise_for_status()
    stations_url = r.json()["properties"]["observationStations"]

    r2 = await client.get(stations_url, headers=_headers(cfg), timeout=15.0)
    r2.raise_for_status()
    body = r2.json()
    feats = body.get("features") or []
    if feats:
        p = feats[0].get("properties", {}) or {}
        sid = p.get("stationIdentifier")
        if sid:
            return sid, (p.get("name") or sid)
    # Fallback: observationStations may be a plain list of station URLs.
    ids = body.get("observationStations") or []
    if ids:
        sid = ids[0].rstrip("/").split("/")[-1]
        return sid, sid
    return None


async def latest(cfg: dict, client: httpx.AsyncClient, station_id: str) -> Optional[WindObservation]:
    """Fetch the latest wind observation from the given station."""
    r = await client.get(
        LATEST_OBS_URL.format(sid=station_id), headers=_headers(cfg), timeout=15.0
    )
    r.raise_for_status()
    p = r.json().get("properties", {}) or {}
    wd = (p.get("windDirection") or {}).get("value")
    return WindObservation(
        wind_speed_mph=_to_mph(p.get("windSpeed")),
        wind_gust_mph=_to_mph(p.get("windGust")),
        wind_direction_deg=wd,
        wind_direction_cardinal=utils.deg_to_cardinal(wd),
        observed_at=p.get("timestamp"),
        source=f"nws-station:{station_id}",
        live=False,
    )

"""Open-Meteo Air Quality provider. Free, no API key.

Docs: https://open-meteo.com/en/docs/air-quality-api
"""

from __future__ import annotations

from typing import Optional

import httpx

from backend import utils
from backend.models import AirQuality

BASE_URL = "https://air-quality-api.open-meteo.com/v1/air-quality"

CURRENT_FIELDS = [
    "us_aqi",
    "pm2_5",
    "pm10",
    "ozone",
    "nitrogen_dioxide",
]


async def fetch(cfg: dict, client: httpx.AsyncClient) -> Optional[AirQuality]:
    """Fetch current air quality for the configured location."""
    loc = cfg["location"]
    params = {
        "latitude": loc["latitude"],
        "longitude": loc["longitude"],
        "current": ",".join(CURRENT_FIELDS),
        "timezone": loc.get("timezone") or "auto",
    }
    resp = await client.get(BASE_URL, params=params, timeout=15.0)
    resp.raise_for_status()
    cur = resp.json().get("current", {}) or {}

    aqi = cur.get("us_aqi")
    level, category = utils.aqi_category(aqi)
    return AirQuality(
        us_aqi=int(aqi) if aqi is not None else None,
        category=category,
        level=level,
        pm2_5=cur.get("pm2_5"),
        pm10=cur.get("pm10"),
        ozone=cur.get("ozone"),
        nitrogen_dioxide=cur.get("nitrogen_dioxide"),
        updated_at=cur.get("time"),
        source="open-meteo",
    )

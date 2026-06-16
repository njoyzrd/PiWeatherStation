"""National Weather Service alerts provider (U.S. only).

Fetches active watches/warnings/advisories for the configured location and
normalizes them into backend.models.Alert, sorted most-severe first.

Reference: https://www.weather.gov/documentation/services-web-api
Endpoint:  https://api.weather.gov/alerts/active?point={lat},{lon}
The NWS API requires a descriptive User-Agent header on every request and is
U.S.-only — outside the U.S. it errors, which the caller treats as "no alerts".
"""

from __future__ import annotations

from typing import List

import httpx

from backend.models import Alert

API_URL = "https://api.weather.gov/alerts/active"

# Lower rank = more severe, so a simple sort surfaces the worst alert first.
_SEVERITY_RANK = {"extreme": 0, "severe": 1, "moderate": 2, "minor": 3, "unknown": 4}


def _user_agent(cfg: dict) -> str:
    """NWS asks for an identifying UA with a contact. Configurable via alerts.contact."""
    contact = (cfg.get("alerts", {}) or {}).get("contact") or "https://github.com/njoyzrd/PiWeatherStation"
    return f"WeatherPi/0.1 ({contact})"


async def fetch(cfg: dict, client: httpx.AsyncClient) -> List[Alert]:
    """Return active alerts for the configured location, most severe first."""
    loc = cfg["location"]
    params = {"point": f'{loc["latitude"]},{loc["longitude"]}', "status": "actual"}
    headers = {"User-Agent": _user_agent(cfg), "Accept": "application/geo+json"}

    resp = await client.get(API_URL, params=params, headers=headers, timeout=15.0)
    resp.raise_for_status()
    data = resp.json()

    alerts: List[Alert] = []
    for feat in data.get("features", []) or []:
        p = feat.get("properties", {}) or {}
        # Skip cancellations — they describe an alert that is no longer in effect.
        if (p.get("messageType") or "").lower() == "cancel":
            continue
        alerts.append(
            Alert(
                id=str(feat.get("id") or p.get("id") or p.get("event") or "alert"),
                event=p.get("event") or "Weather Alert",
                severity=p.get("severity"),
                headline=p.get("headline"),
                description=p.get("description"),
                onset=p.get("onset") or p.get("effective"),
                expires=p.get("expires") or p.get("ends"),
                source="nws",
            )
        )

    alerts.sort(key=lambda a: _SEVERITY_RANK.get((a.severity or "").lower(), 99))
    return alerts

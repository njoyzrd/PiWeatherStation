"""National Weather Service alerts provider (U.S. only).

STUB — wired into the cache/poller architecture but not yet implemented. The next
build pass should fetch active alerts and normalize them into backend.models.Alert.

Reference: https://www.weather.gov/documentation/services-web-api
Endpoint:  https://api.weather.gov/alerts/active?point={lat},{lon}
Note: the NWS API requires a descriptive User-Agent header on every request.
"""

from __future__ import annotations

from typing import List

import httpx

from backend.models import Alert

API_URL = "https://api.weather.gov/alerts/active"
USER_AGENT = "WeatherPi/0.1 (Raspberry Pi weather station; contact: set-in-config)"


async def fetch(cfg: dict, client: httpx.AsyncClient) -> List[Alert]:
    """Return active alerts for the configured location. Currently returns []."""
    # TODO (Phase 3): GET {API_URL}?point={lat},{lon} with the NWS User-Agent header,
    # then map features[].properties -> Alert(id, event, severity, headline, ...).
    return []

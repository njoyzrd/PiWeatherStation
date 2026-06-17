"""Shared helpers: config loading, unit conversions, and WMO weather-code mapping."""

from __future__ import annotations

import os
from functools import lru_cache
from typing import Any, Optional

import yaml

# Resolve config relative to the project root (one level above backend/).
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_CONFIG = os.path.join(PROJECT_ROOT, "config.yaml")
EXAMPLE_CONFIG = os.path.join(PROJECT_ROOT, "config.example.yaml")
CONFIG_PATH = os.environ.get("WEATHERPI_CONFIG", DEFAULT_CONFIG)


@lru_cache(maxsize=1)
def load_config() -> dict:
    """Load and cache the config. Set WEATHERPI_CONFIG to override the path.

    config.yaml holds personal settings and is gitignored; on a fresh clone it
    won't exist, so fall back to the committed config.example.yaml.
    """
    path = CONFIG_PATH
    if path == DEFAULT_CONFIG and not os.path.exists(path) and os.path.exists(EXAMPLE_CONFIG):
        path = EXAMPLE_CONFIG
    with open(path, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


# --- Unit conversions -------------------------------------------------------

def hpa_to_inhg(hpa: Optional[float]) -> Optional[float]:
    if hpa is None:
        return None
    return round(hpa * 0.0295299830714, 2)


def f_to_c(f: Optional[float]) -> Optional[float]:
    if f is None:
        return None
    return (f - 32.0) * 5.0 / 9.0


def c_to_f(c: Optional[float]) -> Optional[float]:
    if c is None:
        return None
    return c * 9.0 / 5.0 + 32.0


def ft_to_mi(ft: Optional[float]) -> Optional[float]:
    if ft is None:
        return None
    return round(ft / 5280.0, 1)


def ms_to_mph(ms: Optional[float]) -> Optional[float]:
    if ms is None:
        return None
    return round(ms * 2.2369362921, 1)


# US EPA AQI bands: (upper_bound, level, category).
_AQI_BANDS = [
    (50, 0, "Good"),
    (100, 1, "Moderate"),
    (150, 2, "Unhealthy (sensitive)"),
    (200, 3, "Unhealthy"),
    (300, 4, "Very unhealthy"),
    (10_000, 5, "Hazardous"),
]


def aqi_category(us_aqi: Optional[float]):
    """Return (level 0-5, category text) for a US AQI value, or (None, None)."""
    if us_aqi is None:
        return None, None
    for upper, level, name in _AQI_BANDS:
        if us_aqi <= upper:
            return level, name
    return 5, "Hazardous"


def moon_phase(now=None):
    """Return (fraction 0..1 through the synodic month, name, emoji)."""
    from datetime import datetime, timezone

    if now is None:
        now = datetime.now(timezone.utc)
    jd = now.timestamp() / 86400.0 + 2440587.5  # Unix time -> Julian date
    synodic = 29.530588853
    known_new_moon = 2451550.1  # 2000-01-06 18:14 UTC
    frac = ((jd - known_new_moon) % synodic) / synodic
    names = [
        "New Moon", "Waxing Crescent", "First Quarter", "Waxing Gibbous",
        "Full Moon", "Waning Gibbous", "Last Quarter", "Waning Crescent",
    ]
    icons = ["🌑", "🌒", "🌓", "🌔", "🌕", "🌖", "🌗", "🌘"]
    idx = int(frac * 8 + 0.5) % 8
    return round(frac, 3), names[idx], icons[idx]


def dew_point_f(temp_f: Optional[float], humidity_pct: Optional[float]) -> Optional[float]:
    """Magnus-formula dew point. Open-Meteo's `current` block omits dew point, so we derive it."""
    if temp_f is None or humidity_pct is None or humidity_pct <= 0:
        return None
    import math

    t_c = f_to_c(temp_f)
    a, b = 17.625, 243.04
    gamma = math.log(humidity_pct / 100.0) + (a * t_c) / (b + t_c)
    dp_c = (b * gamma) / (a - gamma)
    return round(c_to_f(dp_c), 1)


_CARDINALS = [
    "N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
    "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW",
]


def deg_to_cardinal(deg: Optional[float]) -> Optional[str]:
    if deg is None:
        return None
    idx = int((deg / 22.5) + 0.5) % 16
    return _CARDINALS[idx]


# --- WMO weather code mapping ----------------------------------------------
# (text, day icon, night icon). Icons are emoji for a lightweight first version;
# they can be swapped for SVG/PNG assets in frontend/icons/ later.
_WMO = {
    0:  ("Clear sky", "☀️", "🌙"),
    1:  ("Mainly clear", "🌤️", "🌙"),
    2:  ("Partly cloudy", "⛅", "☁️"),
    3:  ("Overcast", "☁️", "☁️"),
    45: ("Fog", "🌫️", "🌫️"),
    48: ("Rime fog", "🌫️", "🌫️"),
    51: ("Light drizzle", "🌦️", "🌧️"),
    53: ("Drizzle", "🌦️", "🌧️"),
    55: ("Heavy drizzle", "🌧️", "🌧️"),
    56: ("Freezing drizzle", "🌧️", "🌧️"),
    57: ("Freezing drizzle", "🌧️", "🌧️"),
    61: ("Light rain", "🌦️", "🌧️"),
    63: ("Rain", "🌧️", "🌧️"),
    65: ("Heavy rain", "🌧️", "🌧️"),
    66: ("Freezing rain", "🌧️", "🌧️"),
    67: ("Freezing rain", "🌧️", "🌧️"),
    71: ("Light snow", "🌨️", "🌨️"),
    73: ("Snow", "🌨️", "🌨️"),
    75: ("Heavy snow", "❄️", "❄️"),
    77: ("Snow grains", "🌨️", "🌨️"),
    80: ("Light showers", "🌦️", "🌧️"),
    81: ("Showers", "🌧️", "🌧️"),
    82: ("Violent showers", "⛈️", "⛈️"),
    85: ("Snow showers", "🌨️", "🌨️"),
    86: ("Snow showers", "❄️", "❄️"),
    95: ("Thunderstorm", "⛈️", "⛈️"),
    96: ("Thunderstorm, hail", "⛈️", "⛈️"),
    99: ("Thunderstorm, hail", "⛈️", "⛈️"),
}


def wmo_text(code: Optional[int]) -> str:
    if code is None:
        return "Unknown"
    return _WMO.get(int(code), ("Unknown", "❓", "❓"))[0]


def wmo_icon(code: Optional[int], is_day: bool = True) -> str:
    if code is None:
        return "❓"
    entry = _WMO.get(int(code))
    if not entry:
        return "❓"
    return entry[1] if is_day else entry[2]

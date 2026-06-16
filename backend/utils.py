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

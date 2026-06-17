"""Normalized data model shared by all weather sources and served to the frontend.

Every provider (Open-Meteo today; NWS / Tempest / Ambient later) normalizes into
these structures, so the frontend never needs to know which source produced the data.
"""

from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field


class Location(BaseModel):
    name: str
    latitude: float
    longitude: float
    timezone: Optional[str] = None


class Current(BaseModel):
    temperature_f: Optional[float] = None
    feels_like_f: Optional[float] = None
    humidity_pct: Optional[float] = None
    dew_point_f: Optional[float] = None
    pressure_inhg: Optional[float] = None
    cloud_cover_pct: Optional[float] = None
    wind_speed_mph: Optional[float] = None
    wind_gust_mph: Optional[float] = None
    wind_direction_deg: Optional[float] = None
    wind_direction_cardinal: Optional[str] = None
    condition_code: Optional[int] = None
    condition_text: Optional[str] = None
    condition_icon: Optional[str] = None
    is_day: Optional[bool] = None
    uv_index: Optional[float] = None
    precip_rate_in: Optional[float] = None
    visibility_mi: Optional[float] = None
    pressure_trend: Optional[str] = None        # "rising" | "falling" | "steady"
    pressure_change_inhg: Optional[float] = None  # change over the last ~3 hours
    moon_phase: Optional[float] = None          # 0..1 fraction through the synodic month
    moon_phase_name: Optional[str] = None
    moon_icon: Optional[str] = None
    sunrise: Optional[str] = None
    sunset: Optional[str] = None
    updated_at: Optional[str] = None
    source: str = "open-meteo"


class HourlyPoint(BaseModel):
    time: str
    temperature_f: Optional[float] = None
    feels_like_f: Optional[float] = None
    precip_probability_pct: Optional[float] = None
    condition_code: Optional[int] = None
    condition_icon: Optional[str] = None
    wind_speed_mph: Optional[float] = None
    is_day: Optional[bool] = None


class DailyPoint(BaseModel):
    date: str
    temp_max_f: Optional[float] = None
    temp_min_f: Optional[float] = None
    condition_code: Optional[int] = None
    condition_text: Optional[str] = None
    condition_icon: Optional[str] = None
    precip_probability_pct: Optional[float] = None
    snowfall_in: Optional[float] = None
    uv_index_max: Optional[float] = None
    sunrise: Optional[str] = None
    sunset: Optional[str] = None


class Alert(BaseModel):
    id: str
    event: str
    severity: Optional[str] = None
    headline: Optional[str] = None
    description: Optional[str] = None
    onset: Optional[str] = None
    expires: Optional[str] = None
    source: str = "nws"


class AirQuality(BaseModel):
    us_aqi: Optional[int] = None
    category: Optional[str] = None          # "Good", "Moderate", ...
    level: Optional[int] = None             # 0..5, drives the color band
    pm2_5: Optional[float] = None
    pm10: Optional[float] = None
    ozone: Optional[float] = None
    nitrogen_dioxide: Optional[float] = None
    updated_at: Optional[str] = None
    source: str = "open-meteo"


class NowcastPoint(BaseModel):
    minute_offset: int                      # minutes from now
    precip_in: Optional[float] = None


class Nowcast(BaseModel):
    summary: str = ""                        # e.g. "Rain starting in ~20 min"
    starts_in_min: Optional[int] = None      # minutes until precip begins, if any
    precipitating: bool = False              # precip happening right now
    points: List[NowcastPoint] = Field(default_factory=list)


class WindObservation(BaseModel):
    """A single live wind reading pushed over /ws/live by a live source.

    `live=True` means a genuinely continuous source (simulator/hardware);
    `live=False` means periodic real observations (e.g. an NWS station).
    """

    wind_speed_mph: Optional[float] = None
    wind_gust_mph: Optional[float] = None
    wind_direction_deg: Optional[float] = None
    wind_direction_cardinal: Optional[str] = None
    observed_at: Optional[str] = None
    source: str = "live"
    live: bool = False
    interval_seconds: Optional[float] = None


class Status(BaseModel):
    api_ok: bool = False
    stale: bool = False
    source: Optional[str] = None             # which provider produced the data
    last_successful_refresh: Optional[str] = None
    last_error: Optional[str] = None


class WeatherData(BaseModel):
    location: Location
    current: Optional[Current] = None
    hourly: List[HourlyPoint] = Field(default_factory=list)
    daily: List[DailyPoint] = Field(default_factory=list)
    alerts: List[Alert] = Field(default_factory=list)
    air_quality: Optional[AirQuality] = None
    nowcast: Optional[Nowcast] = None
    status: Status = Field(default_factory=Status)

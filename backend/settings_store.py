"""User-editable settings persisted outside config.yaml.

config.yaml holds install-time defaults (and is hand-edited); this store holds
what the user changes at runtime from the settings page — the active location
and up to four saved preset locations — in a small JSON file next to it.

The file (settings.json) is gitignored so a user's chosen locations stay local
and survive `git` updates, just like config.yaml and the house image.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from typing import List, Optional

from backend import utils

log = logging.getLogger("weatherpi.settings")

SETTINGS_PATH = os.environ.get(
    "WEATHERPI_SETTINGS", os.path.join(utils.PROJECT_ROOT, "settings.json")
)

MAX_PRESETS = 4


def sanitize_location(raw: dict) -> Optional[dict]:
    """Validate and normalize a location dict, or return None if invalid."""
    if not isinstance(raw, dict):
        return None
    try:
        name = str(raw["name"]).strip()
        lat = float(raw["latitude"])
        lon = float(raw["longitude"])
    except (KeyError, TypeError, ValueError):
        return None
    if not name or not (-90.0 <= lat <= 90.0) or not (-180.0 <= lon <= 180.0):
        return None
    tz = raw.get("timezone")
    tz = str(tz).strip() if tz else None
    return {"name": name, "latitude": lat, "longitude": lon, "timezone": tz or None}


def _same_place(a: dict, b: dict) -> bool:
    return (
        round(a.get("latitude", 0), 4) == round(b.get("latitude", 0), 4)
        and round(a.get("longitude", 0), 4) == round(b.get("longitude", 0), 4)
    )


class SettingsStore:
    """Holds the active location and preset list, persisted to settings.json."""

    def __init__(self, cfg: dict):
        self._lock = threading.Lock()
        default = sanitize_location(cfg.get("location", {})) or {
            "name": "Unknown",
            "latitude": 0.0,
            "longitude": 0.0,
            "timezone": None,
        }
        self.active: dict = dict(default)
        self.presets: List[dict] = [dict(default)]
        self._load(default)

    # --- persistence -------------------------------------------------------

    def _load(self, default: dict) -> None:
        try:
            with open(SETTINGS_PATH, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except FileNotFoundError:
            self._save()  # seed the file with the config default
            return
        except Exception as exc:  # noqa: BLE001 - corrupt file: keep defaults
            log.warning("Could not read %s: %s (using defaults)", SETTINGS_PATH, exc)
            return
        active = sanitize_location(data.get("active_location", {}))
        if active:
            self.active = active
        presets = [p for p in (sanitize_location(x) for x in data.get("presets", [])) if p]
        if presets:
            self.presets = presets[:MAX_PRESETS]

    def _save(self) -> None:
        try:
            tmp = SETTINGS_PATH + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(
                    {"active_location": self.active, "presets": self.presets},
                    fh,
                    indent=2,
                )
            os.replace(tmp, SETTINGS_PATH)
        except Exception as exc:  # noqa: BLE001 - non-fatal; runtime state still updated
            log.warning("Could not write %s: %s", SETTINGS_PATH, exc)

    # --- mutations ---------------------------------------------------------

    def set_active(self, raw: dict) -> dict:
        """Set the active location (validated). Returns the stored location."""
        loc = sanitize_location(raw)
        if not loc:
            raise ValueError("invalid location")
        with self._lock:
            self.active = loc
            self._save()
        return loc

    def set_presets(self, raw_list: list) -> List[dict]:
        """Replace the preset list (validated, capped at MAX_PRESETS)."""
        presets = [p for p in (sanitize_location(x) for x in (raw_list or [])) if p]
        with self._lock:
            self.presets = presets[:MAX_PRESETS]
            self._save()
        return self.presets

    def add_preset(self, raw: dict) -> List[dict]:
        """Add a location to the presets if there's room and it isn't a dupe."""
        loc = sanitize_location(raw)
        if not loc:
            raise ValueError("invalid location")
        with self._lock:
            if not any(_same_place(loc, p) for p in self.presets):
                if len(self.presets) >= MAX_PRESETS:
                    raise ValueError(f"preset limit reached ({MAX_PRESETS})")
                self.presets.append(loc)
                self._save()
            return list(self.presets)

    # --- views -------------------------------------------------------------

    def as_dict(self) -> dict:
        return {
            "active_location": dict(self.active),
            "presets": [dict(p) for p in self.presets],
            "max_presets": MAX_PRESETS,
        }

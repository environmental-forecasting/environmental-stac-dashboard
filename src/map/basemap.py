"""Free XYZ basemap catalogue (Carto / OSM-derived)."""

import os
from typing import Any

BASEMAP_ATTRIBUTION_CARTO = (
    '© <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener noreferrer">OpenStreetMap</a> '
    'contributors © <a href="https://carto.com/attributions" target="_blank" rel="noopener noreferrer">CARTO</a>'
)
BASEMAP_ATTRIBUTION_OSM = (
    '© <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener noreferrer">OpenStreetMap</a> '
    'contributors'
)

CARTO_API_KEY_ENV = "CARTO_API_KEY"
CARTO_API_KEY_URL = "https://carto.com/basemaps/apikey"

# Stable ids used by the UI control and user-prefs.
BASEMAP_OSM = "osm"
BASEMAP_VOYAGER = "voyager"
BASEMAP_POSITRON = "positron"
BASEMAP_DARK_MATTER = "dark_matter"

# Default to OpenStreetMap (free, no API key required).
DEFAULT_BASEMAP_ID = BASEMAP_OSM

_BASEMAPS: dict[str, dict[str, str]] = {
    BASEMAP_OSM: {
        "id": BASEMAP_OSM,
        "label": "OpenStreetMap",
        "type": "xyz",
        "url": "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
        "attribution": BASEMAP_ATTRIBUTION_OSM,
        "provider": "osm",
    },
    BASEMAP_VOYAGER: {
        "id": BASEMAP_VOYAGER,
        "label": "Voyager",
        "type": "xyz",
        "url": (
            "https://basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}.png"
        ),
        "attribution": BASEMAP_ATTRIBUTION_CARTO,
        "provider": "carto",
    },
    BASEMAP_POSITRON: {
        "id": BASEMAP_POSITRON,
        "label": "Positron",
        "type": "xyz",
        "url": "https://basemaps.cartocdn.com/light_all/{z}/{x}/{y}.png",
        "attribution": BASEMAP_ATTRIBUTION_CARTO,
        "provider": "carto",
    },
    BASEMAP_DARK_MATTER: {
        "id": BASEMAP_DARK_MATTER,
        "label": "Dark Matter",
        "type": "xyz",
        "url": "https://basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png",
        "attribution": BASEMAP_ATTRIBUTION_CARTO,
        "provider": "carto",
    },
}


def get_carto_api_key() -> str | None:
    """Read optional CARTO API key from environment."""
    key = os.getenv(CARTO_API_KEY_ENV)
    return key.strip() if key and key.strip() else None


def list_basemap_options() -> list[dict[str, str]]:
    """Return dropdown/radio options for the basemap control."""
    return [
        {"label": entry["label"], "value": entry["id"]}
        for entry in _BASEMAPS.values()
    ]


def normalise_basemap_id(basemap_id: Any) -> str:
    """Return a known basemap id, falling back to the default."""
    if isinstance(basemap_id, str) and basemap_id in _BASEMAPS:
        return basemap_id
    return DEFAULT_BASEMAP_ID


def basemap_descriptor(
    basemap_id: Any = None,
    api_key: str | None = None,
) -> dict[str, str]:
    """
    Return the ``map-state`` basemap payload for an id.

    Includes ``id`` so clients and prefs can round-trip the choice.
    If the selected basemap is provided by CARTO, appends the CARTO API
    key (?key=...) when configured.
    """
    entry = _BASEMAPS[normalise_basemap_id(basemap_id)]
    url = entry["url"]
    if entry.get("provider") == "carto":
        key = api_key if api_key is not None else get_carto_api_key()
        if key:
            sep = "&" if "?" in url else "?"
            url = f"{url}{sep}key={key}"

    return {
        "id": entry["id"],
        "type": entry["type"],
        "url": url,
        "attribution": entry["attribution"],
    }

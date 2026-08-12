"""Free XYZ basemap catalogue (Carto / OSM-derived)."""

from typing import Any

BASEMAP_ATTRIBUTION_CARTO = "© OpenStreetMap contributors © CARTO"
BASEMAP_ATTRIBUTION_OSM = "© OpenStreetMap contributors"
# Shared default attribution string for host fallbacks.
BASEMAP_ATTRIBUTION = BASEMAP_ATTRIBUTION_CARTO

# Stable ids used by the UI control and user-prefs.
BASEMAP_VOYAGER = "voyager"
BASEMAP_POSITRON = "positron"
BASEMAP_DARK_MATTER = "dark_matter"
BASEMAP_OSM = "osm"
# Readable middle ground under forecast tiles (not near-black like Dark Matter).
DEFAULT_BASEMAP_ID = BASEMAP_VOYAGER

_BASEMAPS: dict[str, dict[str, str]] = {
    BASEMAP_VOYAGER: {
        "id": BASEMAP_VOYAGER,
        "label": "Voyager",
        "type": "xyz",
        "url": (
            "https://basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}.png"
        ),
        "attribution": BASEMAP_ATTRIBUTION_CARTO,
    },
    BASEMAP_POSITRON: {
        "id": BASEMAP_POSITRON,
        "label": "Positron",
        "type": "xyz",
        "url": "https://basemaps.cartocdn.com/light_all/{z}/{x}/{y}.png",
        "attribution": BASEMAP_ATTRIBUTION_CARTO,
    },
    BASEMAP_DARK_MATTER: {
        "id": BASEMAP_DARK_MATTER,
        "label": "Dark Matter",
        "type": "xyz",
        "url": "https://basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png",
        "attribution": BASEMAP_ATTRIBUTION_CARTO,
    },
    BASEMAP_OSM: {
        "id": BASEMAP_OSM,
        "label": "OpenStreetMap",
        "type": "xyz",
        "url": "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
        "attribution": BASEMAP_ATTRIBUTION_OSM,
    },
}


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


def basemap_descriptor(basemap_id: Any = None) -> dict[str, str]:
    """
    Return the ``map-state`` basemap payload for an id.

    Includes ``id`` so clients and prefs can round-trip the choice.
    """
    entry = _BASEMAPS[normalise_basemap_id(basemap_id)]
    return {
        "id": entry["id"],
        "type": entry["type"],
        "url": entry["url"],
        "attribution": entry["attribution"],
    }


# Convenience aliases used by map hosts.
DEFAULT_BASEMAP_XYZ_URL = _BASEMAPS[DEFAULT_BASEMAP_ID]["url"]
DEFAULT_BASEMAP_ATTRIBUTION = _BASEMAPS[DEFAULT_BASEMAP_ID]["attribution"]
# Back-compat with older OSM naming (now points at the default style URL).
OSM_XYZ_URL = DEFAULT_BASEMAP_XYZ_URL

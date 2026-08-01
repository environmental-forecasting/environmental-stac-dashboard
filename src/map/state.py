"""Build and compare the shared ``map-state`` payload for map hosts."""

from __future__ import annotations

from typing import Any

from .projections import MapEngine, MapViewMode

# Standard OSM raster tiles for global Web Mercator basemaps.
OSM_XYZ_URL = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"


def initial_map_state() -> dict[str, Any]:
    """
    Return the default ``map-state`` store payload.

    Returns:
        State with OpenLayers engine, global Web Mercator mode, and no layers.
    """
    return {
        "engine": MapEngine.OPENLAYERS.value,
        "mode": MapViewMode.GLOBAL_3857.value,
        "basemap": {"type": "xyz", "url": OSM_XYZ_URL},
        "layers": [],
        "view": None,
        "revision": 0,
    }


def build_map_state(
    *,
    previous: dict[str, Any] | None,
    engine: str,
    mode: str,
    layers: list[dict[str, Any]],
    view: dict[str, Any] | None = None,
    basemap: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Build the next ``map-state``, bumping ``revision`` when content changes.

    Args:
        previous: Existing store payload, or None on first build.
        engine: Active map engine id.
        mode: Active view mode id.
        layers: Forecast overlay descriptors (``id``, ``title``, ``tileUrl``, …).
        view: Optional fit / centre hint for the client.
        basemap: Optional basemap descriptor; defaults to OSM XYZ.

    Returns:
        New map-state dict. Reuses the previous ``revision`` when nothing
        meaningful changed so clients can no-op.
    """
    previous = previous or initial_map_state()
    basemap = basemap or {"type": "xyz", "url": OSM_XYZ_URL}
    candidate = {
        "engine": engine,
        "mode": mode,
        "basemap": basemap,
        "layers": layers,
        "view": view,
        "revision": previous.get("revision", 0),
    }
    if _state_content_equal(previous, candidate):
        return previous

    candidate["revision"] = int(previous.get("revision", 0)) + 1
    return candidate


def _state_content_equal(left: dict[str, Any], right: dict[str, Any]) -> bool:
    """Compare map-state fields that affect rendering (ignore revision)."""
    keys = ("engine", "mode", "basemap", "layers", "view")
    return all(left.get(key) == right.get(key) for key in keys)

"""Build and compare the shared ``map-state`` payload for map hosts."""

from typing import Any

from .projections import MapEngine, MapViewMode, view_hint_for_mode

# Standard OSM raster tiles for global Web Mercator basemaps.
OSM_XYZ_URL = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"

# Omit a field to keep the previous value; pass None to clear it.
_UNSET: Any = object()


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
        "prefetchLayers": [],
        "leadtimeCogUrls": None,
        "lead": None,
        "view": view_hint_for_mode(MapViewMode.GLOBAL_3857),
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
    prefetch_layers: list[dict[str, Any]] | None = None,
    leadtime_cog_urls: Any = _UNSET,
    lead: Any = _UNSET,
) -> dict[str, Any]:
    """
    Build the next ``map-state``, bumping ``revision`` when content changes.

    Args:
        previous: Existing store payload, or None on first build.
        engine: Active map engine id.
        mode: Active view mode id.
        layers: Forecast overlay descriptors (``id``, ``title``, ``tileUrl``, ...).
        view: Optional fit / centre hint for the client.
        basemap: Optional basemap descriptor; defaults to OSM XYZ.
        prefetch_layers: Optional overlays for the next leadtime step.
        leadtime_cog_urls: Cached COG URLs per leadtime for fast client-side
            swaps. Omit to keep the previous value; pass ``None`` to clear.
        lead: Current leadtime step (used for adjacent-step prefetch).

    Returns:
        New map-state dict. Reuses the previous ``revision`` when nothing
        meaningful changed so clients can no-op.
    """
    previous = previous or initial_map_state()
    basemap = basemap or {"type": "xyz", "url": OSM_XYZ_URL}
    if view is None:
        view = previous.get("view")
    if leadtime_cog_urls is _UNSET:
        leadtime_cog_urls = previous.get("leadtimeCogUrls")
    if lead is _UNSET:
        lead = previous.get("lead")
    candidate = {
        "engine": engine,
        "mode": mode,
        "basemap": basemap,
        "layers": layers,
        "prefetchLayers": list(prefetch_layers or []),
        "leadtimeCogUrls": leadtime_cog_urls,
        "lead": lead,
        "view": view,
        "revision": previous.get("revision", 0),
    }
    if _state_content_equal(previous, candidate):
        return previous

    candidate["revision"] = int(previous.get("revision", 0)) + 1
    return candidate


def _state_content_equal(left: dict[str, Any], right: dict[str, Any]) -> bool:
    """Compare map-state fields that affect rendering (ignore revision)."""
    keys = (
        "engine",
        "mode",
        "basemap",
        "layers",
        "prefetchLayers",
        "leadtimeCogUrls",
        "lead",
        "view",
    )
    return all(left.get(key) == right.get(key) for key in keys)

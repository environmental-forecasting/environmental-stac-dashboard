"""View modes, map engines, and TiTiler tile-matrix identifiers."""

import logging
from enum import StrEnum
from typing import Any

from .tms_client import (
    CUSTOM_EPSG_TMS_ID_RE,
    get_tile_grid,
    list_custom_epsg_tms_ids,
)

logger = logging.getLogger(__name__)

# Built-in TiTiler / morecantile Web Mercator matrix.
WEB_MERCATOR_QUAD = "WebMercatorQuad"

# Labels for known custom grids; unknown EPSG#### fall back to EPSG:n.
_TMS_LABELS: dict[str, str] = {
    "EPSG6931": "Arctic",
    "EPSG6932": "Antarctic",
}


class MapViewMode(StrEnum):
    """Fixed product view modes (not discovered from TiTiler)."""

    GLOBAL_3857 = "global_3857"
    GLOBAL_LEAFLET = "global_leaflet"
    GLOBE_CESIUM = "globe_cesium"


class MapEngine(StrEnum):
    """Which client renders the map host."""

    OPENLAYERS = "openlayers"
    CESIUM = "cesium"
    LEAFLET_LEGACY = "leaflet_legacy"


_WEB_MERCATOR_MODES = frozenset(
    (
        MapViewMode.GLOBAL_3857.value,
        MapViewMode.GLOBAL_LEAFLET.value,
        MapViewMode.GLOBE_CESIUM.value,
    )
)


def normalise_view_mode(mode: str | None) -> str:
    """
    Normalise a view-mode id (empty defaults to global).

    Args:
        mode: Raw mode string from the UI or store.

    Returns:
        Mode id (e.g. ``global_3857``, ``global_leaflet``, ``globe_cesium``,
        or ``EPSG####``).
    """
    if not mode:
        return MapViewMode.GLOBAL_3857.value
    return mode


def is_custom_tms_mode(mode: str | None) -> bool:
    """Return whether ``mode`` is a discovered ``EPSG####`` tile matrix view."""
    return bool(CUSTOM_EPSG_TMS_ID_RE.fullmatch(normalise_view_mode(mode)))


def tile_matrix_set_for_mode(mode: str) -> str:
    """
    Return the TiTiler tile matrix set id for a view mode.

    Args:
        mode: View mode id (``global_3857``, ``global_leaflet``,
            ``globe_cesium``, or ``EPSG####``).

    Returns:
        Tile matrix set identifier such as ``WebMercatorQuad`` or ``EPSG6931``.

    Raises:
        ValueError: If ``mode`` is not a known product or custom TMS mode.
    """
    view_mode = normalise_view_mode(mode)
    if view_mode in _WEB_MERCATOR_MODES:
        return WEB_MERCATOR_QUAD
    if CUSTOM_EPSG_TMS_ID_RE.fullmatch(view_mode):
        return view_mode
    raise ValueError(f"unknown view mode: {mode!r}")


def epsg_code_for_mode(mode: str) -> int:
    """
    Return the EPSG code used for the 2D view of a mode.

    Args:
        mode: View mode id.

    Returns:
        EPSG code (globe mode reports 3857 for its imagery grid).

    Raises:
        ValueError: If ``mode`` is not recognised.
    """
    view_mode = normalise_view_mode(mode)
    if view_mode in _WEB_MERCATOR_MODES:
        return 3857
    match = CUSTOM_EPSG_TMS_ID_RE.fullmatch(view_mode)
    if match:
        return int(match.group(1))
    raise ValueError(f"unknown view mode: {mode!r}")


def proj4_for_epsg(epsg: int) -> str | None:
    """
    Return a proj4 string for an EPSG code via pyproj.

    OpenLayers needs this to register custom CRS; TiTiler TMS JSON only
    carries an EPSG URI.

    Args:
        epsg: EPSG code such as ``6931``.

    Returns:
        proj4 definition string, or None if the code is unknown to pyproj.
    """
    try:
        from pyproj import CRS
    except ImportError:
        logger.warning("pyproj is not installed; cannot resolve EPSG:%s", epsg)
        return None

    try:
        # PROJ may warn that proj4 loses axis order; proj4js still needs it.
        import warnings

        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            return CRS.from_epsg(epsg).to_proj4()
    except Exception as exc:
        logger.warning("Could not resolve proj4 for EPSG:%s: %s", epsg, exc)
        return None


def label_for_view_mode(mode: str) -> str:
    """
    Return a short UI label for a view mode.

    Args:
        mode: View mode id.

    Returns:
        Label such as ``Global``, ``Arctic``, or ``EPSG:3031``.
    """
    view_mode = normalise_view_mode(mode)
    if view_mode == MapViewMode.GLOBAL_3857.value:
        return "Global"
    if view_mode == MapViewMode.GLOBAL_LEAFLET.value:
        return "Leaflet"
    if view_mode == MapViewMode.GLOBE_CESIUM.value:
        return "Globe"
    if view_mode in _TMS_LABELS:
        return _TMS_LABELS[view_mode]
    match = CUSTOM_EPSG_TMS_ID_RE.fullmatch(view_mode)
    if match:
        return f"EPSG:{match.group(1)}"
    return view_mode


def list_view_mode_options(tiler_url: str) -> list[dict[str, str]]:
    """
    Build RadioItems options: Global, Leaflet, Globe, then custom TMS grids.

    Engine is derived from the selected mode (no separate renderer control).

    Args:
        tiler_url: TiTiler base URL used to list tile matrix sets.

    Returns:
        List of ``{"label", "value"}`` dicts for Dash.
    """
    options = [
        {
            "label": label_for_view_mode(MapViewMode.GLOBAL_3857.value),
            "value": MapViewMode.GLOBAL_3857.value,
        },
        {
            "label": label_for_view_mode(MapViewMode.GLOBAL_LEAFLET.value),
            "value": MapViewMode.GLOBAL_LEAFLET.value,
        },
        {
            "label": label_for_view_mode(MapViewMode.GLOBE_CESIUM.value),
            "value": MapViewMode.GLOBE_CESIUM.value,
        },
    ]
    for tms_id in list_custom_epsg_tms_ids(tiler_url):
        options.append({"label": label_for_view_mode(tms_id), "value": tms_id})
    return options


def list_view_mode_presets(tiler_url: str) -> dict[str, dict[str, Any]]:
    """
    Build ``{mode: view_hint}`` presets for optimistic client-side switches.

    Polar modes include TiTiler tile-grid hints so the browser can change
    projection without waiting on Python.

    Args:
        tiler_url: TiTiler base URL used to resolve custom TMS grids.

    Returns:
        Mapping of view-mode id to OpenLayers / Cesium view hint dict.
    """
    presets: dict[str, dict[str, Any]] = {}
    for option in list_view_mode_options(tiler_url):
        mode = option["value"]
        _resolved, hint = view_mode_and_hint(mode, tiler_url)
        presets[mode] = hint
    return presets


def resolve_view_mode(mode: str | None, tiler_url: str) -> str:
    """
    Resolve a requested view mode against TiTiler-registered matrices.

    Custom ``EPSG####`` modes need that TMS on TiTiler. If it is missing,
    fall back to global Web Mercator (same capability as the old Leaflet map).

    Args:
        mode: Requested view mode id.
        tiler_url: TiTiler base URL used to look up tile matrix sets.

    Returns:
        A mode id that can be rendered with the current tiler configuration.
    """
    view_mode = normalise_view_mode(mode)
    if view_mode in _WEB_MERCATOR_MODES:
        return view_mode

    if CUSTOM_EPSG_TMS_ID_RE.fullmatch(view_mode):
        if get_tile_grid(tiler_url, view_mode) is None:
            logger.warning(
                "Tile matrix set %s is not available from %s; "
                "falling back to global Web Mercator",
                view_mode,
                tiler_url,
            )
            return MapViewMode.GLOBAL_3857.value
        epsg = epsg_code_for_mode(view_mode)
        if proj4_for_epsg(epsg) is None:
            logger.warning(
                "No proj4 definition for EPSG:%s; falling back to global Web Mercator",
                epsg,
            )
            return MapViewMode.GLOBAL_3857.value
        return view_mode

    logger.warning("Unknown view mode %r; falling back to global Web Mercator", mode)
    return MapViewMode.GLOBAL_3857.value


def view_hint_for_mode(
    mode: str,
    *,
    tile_grid: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Return client view hints for a map mode (projection, fit, basemap).

    Custom TMS hints require ``tile_grid`` from TiTiler (see ``get_tile_grid``).
    Without it, returns the global Web Mercator hint.

    Args:
        mode: View mode id.
        tile_grid: Optional ``extent`` / ``origin`` / ``resolutions`` from TMS.

    Returns:
        Dict consumed by the OpenLayers renderer.
    """
    view_mode = normalise_view_mode(mode)
    if view_mode == MapViewMode.GLOBE_CESIUM.value:
        return {
            "projection": "EPSG:3857",
            "showBasemap": True,
            "fit": False,
            "globe": True,
        }
    if CUSTOM_EPSG_TMS_ID_RE.fullmatch(view_mode):
        if not tile_grid:
            return view_hint_for_mode(MapViewMode.GLOBAL_3857.value)
        epsg = epsg_code_for_mode(view_mode)
        proj4 = proj4_for_epsg(epsg)
        if not proj4:
            return view_hint_for_mode(MapViewMode.GLOBAL_3857.value)
        return {
            "projection": f"EPSG:{epsg}",
            "proj4": proj4,
            "extent": list(tile_grid["extent"]),
            "origin": list(tile_grid["origin"]),
            "resolutions": list(tile_grid["resolutions"]),
            # XYZ basemap stays Web Mercator; OpenLayers reprojects it into this view.
            "showBasemap": True,
            "fit": True,
        }
    return {
        "projection": "EPSG:3857",
        "center": [0, 0],
        # Zoom 0 + fit world so the first Global view shows the full map.
        "zoom": 0,
        "showBasemap": True,
        "fit": True,
        "showFullExtent": True,
        # One world only; wrapping repeats overlays beside the basemap.
        "multiWorld": False,
        "minZoom": 0,
    }


def view_mode_and_hint(
    mode: str | None, tiler_url: str
) -> tuple[str, dict[str, Any]]:
    """
    Resolve mode (with TMS fallback) and build the matching view hint.

    Args:
        mode: Requested view mode.
        tiler_url: TiTiler base URL for custom TMS lookup.

    Returns:
        ``(resolved_mode, view_hint)``.
    """
    resolved = resolve_view_mode(mode, tiler_url)
    tile_grid = None
    if is_custom_tms_mode(resolved):
        tile_grid = get_tile_grid(tiler_url, tile_matrix_set_for_mode(resolved))
    return resolved, view_hint_for_mode(resolved, tile_grid=tile_grid)


def resolve_engine_for_mode(mode: str) -> str:
    """
    Return the map engine for a view mode.

    Globe uses Cesium, Leaflet mode uses Leaflet, everything else OpenLayers.

    Args:
        mode: View mode id.

    Returns:
        Engine id for ``mode``.
    """
    view_mode = normalise_view_mode(mode)
    if view_mode == MapViewMode.GLOBE_CESIUM.value:
        return MapEngine.CESIUM.value
    if view_mode == MapViewMode.GLOBAL_LEAFLET.value:
        return MapEngine.LEAFLET_LEGACY.value
    return MapEngine.OPENLAYERS.value

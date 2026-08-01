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

# Hemisphere fitness for known polar EPSG codes (centre latitude sign).
_ARCTIC_EPSG_CODES = frozenset({6931})
_ANTARCTIC_EPSG_CODES = frozenset({6932})


class MapViewMode(StrEnum):
    """Fixed product view modes (not discovered from TiTiler)."""

    GLOBAL_3857 = "global_3857"
    GLOBE_CESIUM = "globe_cesium"


class MapEngine(StrEnum):
    """Which client renders the map host."""

    OPENLAYERS = "openlayers"
    CESIUM = "cesium"
    LEAFLET_LEGACY = "leaflet_legacy"


def normalise_view_mode(mode: str | None) -> str:
    """
    Normalise a view-mode id (empty -> global).

    Args:
        mode: Raw mode string from the UI or store.

    Returns:
        Mode id (e.g. ``global_3857``, ``globe_cesium``, or ``EPSG####``).
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
        mode: View mode id (``global_3857``, ``globe_cesium``, or ``EPSG####``).

    Returns:
        Tile matrix set identifier such as ``WebMercatorQuad`` or ``EPSG6931``.

    Raises:
        ValueError: If ``mode`` is not a known product or custom TMS mode.
    """
    view_mode = normalise_view_mode(mode)
    if view_mode in (
        MapViewMode.GLOBAL_3857.value,
        MapViewMode.GLOBE_CESIUM.value,
    ):
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
    if view_mode in (
        MapViewMode.GLOBAL_3857.value,
        MapViewMode.GLOBE_CESIUM.value,
    ):
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
    Build RadioItems options: Global, custom ``EPSG####`` grids, then Globe.

    Args:
        tiler_url: TiTiler base URL used to list tile matrix sets.

    Returns:
        List of ``{"label", "value"}`` dicts for Dash.
    """
    options = [
        {
            "label": label_for_view_mode(MapViewMode.GLOBAL_3857.value),
            "value": MapViewMode.GLOBAL_3857.value,
        }
    ]
    for tms_id in list_custom_epsg_tms_ids(tiler_url):
        options.append({"label": label_for_view_mode(tms_id), "value": tms_id})
    options.append(
        {
            "label": label_for_view_mode(MapViewMode.GLOBE_CESIUM.value),
            "value": MapViewMode.GLOBE_CESIUM.value,
        }
    )
    return options


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
    if view_mode in (
        MapViewMode.GLOBAL_3857.value,
        MapViewMode.GLOBE_CESIUM.value,
    ):
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
            # OSM stays Web Mercator; OpenLayers reprojects it into this view.
            "showBasemap": True,
            "fit": True,
        }
    return {
        "projection": "EPSG:3857",
        "center": [0, 0],
        "showBasemap": True,
        # Fit the full Mercator world on entry (same idea as polar defaults).
        "fit": True,
        "showFullExtent": True,
        "multiWorld": True,
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


_ENGINE_LABELS: dict[str, str] = {
    MapEngine.OPENLAYERS.value: "OpenLayers",
    MapEngine.CESIUM.value: "Cesium",
    MapEngine.LEAFLET_LEGACY.value: "Leaflet (legacy)",
}


def normalise_engine(engine: str | None) -> str:
    """
    Return a known map engine, defaulting to OpenLayers when the value is missing or unrecognised.

    Args:
        engine: Raw engine string from the UI or store.

    Returns:
        One of ``MapEngine`` values.
    """
    if engine in (
        MapEngine.OPENLAYERS.value,
        MapEngine.CESIUM.value,
        MapEngine.LEAFLET_LEGACY.value,
    ):
        return engine
    return MapEngine.OPENLAYERS.value


def label_for_engine(engine: str) -> str:
    """Return a short UI label for a map engine."""
    return _ENGINE_LABELS.get(normalise_engine(engine), normalise_engine(engine))


def list_map_engine_options() -> list[dict[str, str]]:
    """Build RadioItems options for OpenLayers, Cesium, and legacy Leaflet."""
    return [
        {"label": label_for_engine(engine.value), "value": engine.value}
        for engine in (
            MapEngine.OPENLAYERS,
            MapEngine.CESIUM,
            MapEngine.LEAFLET_LEGACY,
        )
    ]


def resolve_engine_for_mode(engine: str, mode: str) -> str:
    """
    Return an engine that can render the requested view mode.

    Globe always uses Cesium. Custom polar grids need OpenLayers. On Global,
    the requested engine is honoured (OpenLayers, Cesium, or Leaflet).

    Args:
        engine: Requested map engine id.
        mode: View mode id.

    Returns:
        Engine id safe for ``mode`` (may equal ``engine``).
    """
    view_mode = normalise_view_mode(mode)
    requested = normalise_engine(engine)
    if view_mode == MapViewMode.GLOBE_CESIUM.value:
        return MapEngine.CESIUM.value
    if is_custom_tms_mode(view_mode):
        return MapEngine.OPENLAYERS.value
    return requested


def resolve_mode_and_engine(
    mode: str | None,
    engine: str | None,
    *,
    triggered: str | None = None,
) -> tuple[str, str]:
    """
    Pick a view and map engine that work together.

    Choosing Globe always uses the 3D globe. Choosing a flat map while Globe
    is selected switches back to the Global view. Arctic and Antarctic views
    always use the flat OpenLayers map.

    Args:
        mode: Requested view mode id.
        engine: Requested map engine id.
        triggered: Dash ``callback_context.triggered_id`` when known.

    Returns:
        ``(resolved_mode, resolved_engine)`` before TiTiler TMS fallback.
    """
    view_mode = normalise_view_mode(mode)
    requested_engine = normalise_engine(engine)

    if triggered == "map-view-mode":
        if view_mode == MapViewMode.GLOBE_CESIUM.value:
            return view_mode, MapEngine.CESIUM.value
        if is_custom_tms_mode(view_mode):
            return view_mode, MapEngine.OPENLAYERS.value
        return view_mode, requested_engine

    if triggered == "map-engine":
        if is_custom_tms_mode(view_mode):
            return view_mode, MapEngine.OPENLAYERS.value
        if (
            view_mode == MapViewMode.GLOBE_CESIUM.value
            and requested_engine != MapEngine.CESIUM.value
        ):
            return MapViewMode.GLOBAL_3857.value, requested_engine
        return view_mode, requested_engine

    if is_custom_tms_mode(view_mode):
        return view_mode, MapEngine.OPENLAYERS.value
    if view_mode == MapViewMode.GLOBE_CESIUM.value:
        return view_mode, MapEngine.CESIUM.value
    return view_mode, requested_engine


def collection_fits_view_mode(collection, mode: str) -> bool:
    """
    Return whether a STAC Collection belongs in the given map view.

    Uses spatial bbox centre latitude (WGS84) for known polar EPSG codes.
    Global / globe / unknown custom grids accept all collections. Unknown
    extent is treated as a fit so listing still works.

    Args:
        collection: ``pystac.Collection`` (or object with ``extent``).
        mode: View mode id.

    Returns:
        True if the collection should be drawn in this mode.
    """
    view_mode = normalise_view_mode(mode)
    if view_mode in (
        MapViewMode.GLOBAL_3857.value,
        MapViewMode.GLOBE_CESIUM.value,
    ):
        return True

    try:
        bboxes = collection.extent.spatial.bboxes
    except Exception:
        return True
    if not bboxes:
        return True

    return bbox_fits_view_mode(bboxes[0], view_mode)


def bbox_fits_view_mode(bbox, mode: str) -> bool:
    """
    Return whether a WGS84 bbox centre belongs in the given map view.

    Known Arctic / Antarctic EPSG codes filter by hemisphere. Other custom
    TMS modes do not filter (all collections are shown).

    Args:
        bbox: Bounding box as ``[west, south, east, north, ...]``.
        mode: View mode id.

    Returns:
        True if the bbox should be drawn in this mode. Malformed bboxes fit.
    """
    view_mode = normalise_view_mode(mode)
    if view_mode in (
        MapViewMode.GLOBAL_3857.value,
        MapViewMode.GLOBE_CESIUM.value,
    ):
        return True
    if bbox is None or len(bbox) < 4:
        return True

    try:
        epsg = epsg_code_for_mode(view_mode)
    except ValueError:
        return True

    if epsg not in _ARCTIC_EPSG_CODES and epsg not in _ANTARCTIC_EPSG_CODES:
        return True

    _west, south, _east, north = bbox[:4]
    try:
        centre_lat = (float(south) + float(north)) / 2.0
    except (TypeError, ValueError):
        return True

    if epsg in _ARCTIC_EPSG_CODES:
        return centre_lat > 0
    if epsg in _ANTARCTIC_EPSG_CODES:
        return centre_lat < 0
    return True

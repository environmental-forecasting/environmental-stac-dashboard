"""View modes, map engines, and TiTiler tile-matrix identifiers."""

from enum import StrEnum

# TiTiler / morecantile tile matrix set IDs.
WEB_MERCATOR_QUAD = "WebMercatorQuad"
EPSG_6931_TMS = "EPSG6931"
EPSG_6932_TMS = "EPSG6932"


class MapViewMode(StrEnum):
    """How the forecast map is framed."""

    GLOBAL_3857 = "global_3857"
    ARCTIC_6931 = "arctic_6931"
    ANTARCTIC_6932 = "antarctic_6932"
    GLOBE_CESIUM = "globe_cesium"


class MapEngine(StrEnum):
    """Which client renders the map host."""

    OPENLAYERS = "openlayers"
    CESIUM = "cesium"
    LEAFLET_LEGACY = "leaflet_legacy"


_TILE_MATRIX_BY_MODE: dict[MapViewMode, str] = {
    MapViewMode.GLOBAL_3857: WEB_MERCATOR_QUAD,
    MapViewMode.ARCTIC_6931: EPSG_6931_TMS,
    MapViewMode.ANTARCTIC_6932: EPSG_6932_TMS,
    MapViewMode.GLOBE_CESIUM: WEB_MERCATOR_QUAD,
}

_EPSG_BY_MODE: dict[MapViewMode, int] = {
    MapViewMode.GLOBAL_3857: 3857,
    MapViewMode.ARCTIC_6931: 6931,
    MapViewMode.ANTARCTIC_6932: 6932,
    # Globe drapes Web Mercator imagery; there is no single EPSG "globe" code.
    MapViewMode.GLOBE_CESIUM: 3857,
}


def tile_matrix_set_for_mode(mode: MapViewMode | str) -> str:
    """
    Return the TiTiler tile matrix set id for a view mode.

    Args:
        mode: View mode enum or its string value.

    Returns:
        Tile matrix set identifier such as ``WebMercatorQuad``.

    Raises:
        ValueError: If ``mode`` is not a known view mode.
    """
    view_mode = MapViewMode(mode)
    return _TILE_MATRIX_BY_MODE[view_mode]


def epsg_code_for_mode(mode: MapViewMode | str) -> int:
    """
    Return the EPSG code used for the 2D view of a mode.

    Args:
        mode: View mode enum or its string value.

    Returns:
        EPSG code (globe mode reports 3857 for its imagery grid).

    Raises:
        ValueError: If ``mode`` is not a known view mode.
    """
    view_mode = MapViewMode(mode)
    return _EPSG_BY_MODE[view_mode]

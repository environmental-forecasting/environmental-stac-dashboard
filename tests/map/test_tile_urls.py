"""Tests for map projection policy and TiTiler URL building."""

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

SRC_DIR = Path(__file__).resolve().parents[2] / "src"
sys.path.insert(0, str(SRC_DIR))

from map.projections import (  # noqa: E402
    WEB_MERCATOR_QUAD,
    MapViewMode,
    bbox_fits_view_mode,
    epsg_code_for_mode,
    label_for_view_mode,
    list_view_mode_options,
    normalise_view_mode,
    proj4_for_epsg,
    resolve_engine_for_mode,
    resolve_view_mode,
    tile_matrix_set_for_mode,
    view_hint_for_mode,
    view_mode_and_hint,
)
from map.tile_urls import build_cog_tile_url  # noqa: E402
from map.tms_client import (  # noqa: E402
    clear_tile_grid_cache,
    get_tile_grid,
    tile_grid_from_tms,
)


def _sample_polar_tms(cell0: float = 70390.3496875) -> dict:
    """Minimal OGC TMS document shaped like TiTiler's EPSG6931 response."""
    origin = [-8918256.31, 9009964.76]
    return {
        "id": "EPSG6931",
        "crs": "http://www.opengis.net/def/crs/EPSG/0/6931",
        "tileMatrices": [
            {
                "id": "0",
                "cellSize": cell0,
                "pointOfOrigin": origin,
                "tileWidth": 256,
                "tileHeight": 256,
                "matrixWidth": 1,
                "matrixHeight": 1,
            },
            {
                "id": "1",
                "cellSize": cell0 / 2,
                "pointOfOrigin": origin,
                "tileWidth": 256,
                "tileHeight": 256,
                "matrixWidth": 2,
                "matrixHeight": 2,
            },
        ],
    }


def test_tile_matrix_set_for_global_and_custom_modes():
    assert tile_matrix_set_for_mode(MapViewMode.GLOBAL_3857) == WEB_MERCATOR_QUAD
    assert tile_matrix_set_for_mode("EPSG6931") == "EPSG6931"
    assert tile_matrix_set_for_mode(MapViewMode.GLOBE_CESIUM) == WEB_MERCATOR_QUAD


def test_epsg_code_for_mode():
    assert epsg_code_for_mode("EPSG6931") == 6931
    assert epsg_code_for_mode("EPSG6932") == 6932
    assert epsg_code_for_mode(MapViewMode.GLOBE_CESIUM) == 3857


def test_normalise_empty_mode_defaults_to_global():
    assert normalise_view_mode(None) == "global_3857"
    assert normalise_view_mode("") == "global_3857"
    assert normalise_view_mode("EPSG6931") == "EPSG6931"


def test_label_for_known_and_unknown_custom_tms():
    assert label_for_view_mode(MapViewMode.GLOBAL_3857) == "Global"
    assert label_for_view_mode("EPSG6931") == "Arctic"
    assert label_for_view_mode("EPSG3031") == "EPSG:3031"


def test_list_view_mode_options_includes_global_and_custom_epsg():
    clear_tile_grid_cache()
    with patch(
        "map.projections.list_custom_epsg_tms_ids",
        return_value=["EPSG6931", "EPSG6932", "EPSG3031"],
    ):
        options = list_view_mode_options("http://tiler")
    assert options[0] == {"label": "Global", "value": "global_3857"}
    assert {"label": "Arctic", "value": "EPSG6931"} in options
    assert {"label": "Antarctic", "value": "EPSG6932"} in options
    assert {"label": "EPSG:3031", "value": "EPSG3031"} in options
    assert not any(o["value"] == "WebMercatorQuad" for o in options)


def test_failed_tile_grid_fetch_is_not_cached():
    clear_tile_grid_cache()
    with patch("map.tms_client.fetch_tile_matrix_set", return_value=None) as fetch:
        assert get_tile_grid("http://tiler", "EPSG6931") is None
        assert get_tile_grid("http://tiler", "EPSG6931") is None
    assert fetch.call_count == 2


def test_successful_tile_grid_fetch_is_cached():
    clear_tile_grid_cache()
    tms = _sample_polar_tms()
    with patch("map.tms_client.fetch_tile_matrix_set", return_value=tms) as fetch:
        first = get_tile_grid("http://tiler", "EPSG6931")
        second = get_tile_grid("http://tiler", "EPSG6931")
    assert first is not None and first == second
    assert fetch.call_count == 1


def test_tile_grid_from_tms_uses_origin_and_cell_sizes():
    grid = tile_grid_from_tms(_sample_polar_tms())
    assert grid["origin"] == [-8918256.31, 9009964.76]
    assert grid["resolutions"][0] == 70390.3496875
    assert grid["resolutions"][1] == 70390.3496875 / 2
    width = 256 * 70390.3496875
    assert grid["extent"][0] == pytest.approx(-8918256.31)
    assert grid["extent"][2] == pytest.approx(-8918256.31 + width)
    assert grid["extent"][3] == pytest.approx(9009964.76)
    assert grid["extent"][1] == pytest.approx(9009964.76 - width)


def test_view_hint_for_custom_mode_requires_tile_grid():
    without = view_hint_for_mode("EPSG6931")
    assert without["projection"] == "EPSG:3857"

    grid = tile_grid_from_tms(_sample_polar_tms())
    hint = view_hint_for_mode("EPSG6931", tile_grid=grid)
    assert hint["projection"] == "EPSG:6931"
    assert hint["showBasemap"] is False
    assert hint["fit"] is True
    assert hint["extent"] == grid["extent"]
    assert hint["proj4"]
    assert "+proj=laea" in hint["proj4"]
    assert "lat_0=90" in hint["proj4"]


def test_proj4_for_epsg_resolves_polar_codes():
    arctic = proj4_for_epsg(6931)
    antarctic = proj4_for_epsg(6932)
    assert arctic is not None and "lat_0=90" in arctic
    assert antarctic is not None and "lat_0=-90" in antarctic


def test_view_hint_for_global_shows_basemap():
    hint = view_hint_for_mode(MapViewMode.GLOBAL_3857)
    assert hint["projection"] == "EPSG:3857"
    assert hint["showBasemap"] is True
    assert hint["fit"] is True
    assert hint["showFullExtent"] is True
    assert hint["multiWorld"] is True
    assert hint["minZoom"] == 0


def test_resolve_view_mode_falls_back_to_global_without_tms():
    clear_tile_grid_cache()
    with patch("map.projections.get_tile_grid", return_value=None):
        assert resolve_view_mode("EPSG6931", "http://tiler") == "global_3857"


def test_view_mode_and_hint_uses_tiler_grid_when_available():
    clear_tile_grid_cache()
    grid = tile_grid_from_tms(_sample_polar_tms())
    with patch("map.projections.get_tile_grid", return_value=grid):
        mode, hint = view_mode_and_hint("EPSG6931", "http://tiler")
    assert mode == "EPSG6931"
    assert hint["projection"] == "EPSG:6931"
    assert hint["resolutions"][0] == grid["resolutions"][0]


def test_bbox_fits_view_mode_by_hemisphere():
    arctic = [-180, 50, 180, 90]
    antarctic = [-180, -90, 180, -50]
    assert bbox_fits_view_mode(arctic, "EPSG6931")
    assert not bbox_fits_view_mode(antarctic, "EPSG6931")
    assert bbox_fits_view_mode(antarctic, "EPSG6932")
    assert not bbox_fits_view_mode(arctic, "EPSG6932")
    assert bbox_fits_view_mode(arctic, MapViewMode.GLOBAL_3857)
    # Unknown custom EPSG: no hemisphere filter.
    assert bbox_fits_view_mode(antarctic, "EPSG3031")


def test_resolve_engine_forces_openlayers_for_custom_tms_leaflet():
    assert (
        resolve_engine_for_mode("leaflet_legacy", "EPSG6931") == "openlayers"
    )
    assert (
        resolve_engine_for_mode("leaflet_legacy", MapViewMode.GLOBAL_3857)
        == "leaflet_legacy"
    )


def test_unknown_mode_raises():
    with pytest.raises(ValueError):
        tile_matrix_set_for_mode("not_a_mode")


def test_build_cog_tile_url_rewrites_file_server_and_keeps_xyz_placeholders():
    url = build_cog_tile_url(
        "http://localhost:8001/data/cogs/demo.tif",
        tiler_url="http://localhost:8002",
        file_server_url="http://localhost:8001",
        file_server_internal_url="http://file-server",
        tile_matrix_set=WEB_MERCATOR_QUAD,
    )

    assert url.startswith(
        "http://localhost:8002/cog/tiles/WebMercatorQuad/{z}/{x}/{y}?url="
    )
    assert "http://file-server/data/cogs/demo.tif" in url
    assert "localhost:8001" not in url.split("url=")[1]


def test_build_cog_tile_url_appends_style_query_params():
    url = build_cog_tile_url(
        "http://file-server/data/cogs/demo.tif",
        tiler_url="http://tiler",
        file_server_url="http://localhost:8001",
        file_server_internal_url="http://file-server",
        tile_matrix_set="EPSG6931",
        colormap="blues_r",
        rescale=(0.0, 1.0),
        band_index=2,
    )

    assert "/cog/tiles/EPSG6931/{z}/{x}/{y}?" in url
    assert "colormap_name=blues_r" in url
    assert "rescale=0.0,1.0" in url
    assert "bidx=2" in url

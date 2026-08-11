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
    epsg_code_for_mode,
    label_for_view_mode,
    list_view_mode_options,
    list_view_mode_presets,
    normalise_view_mode,
    proj4_for_epsg,
    resolve_engine_for_mode,
    resolve_view_mode,
    tile_matrix_set_for_mode,
    view_hint_for_mode,
    view_mode_and_hint,
)
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


def test_list_view_mode_options_includes_global_custom_and_globe():
    clear_tile_grid_cache()
    with patch(
        "map.projections.list_custom_epsg_tms_ids",
        return_value=["EPSG6931", "EPSG6932", "EPSG3031"],
    ):
        options = list_view_mode_options("http://tiler")
    assert options[0] == {"label": "Global", "value": "global_3857"}
    assert options[1] == {"label": "Leaflet", "value": "global_leaflet"}
    assert options[2] == {"label": "Globe", "value": "globe_cesium"}
    assert {"label": "Arctic", "value": "EPSG6931"} in options
    assert {"label": "Antarctic", "value": "EPSG6932"} in options
    assert {"label": "EPSG:3031", "value": "EPSG3031"} in options
    assert not any(o["value"] == "WebMercatorQuad" for o in options)


def test_view_hint_for_globe_uses_web_mercator_without_fit():
    hint = view_hint_for_mode(MapViewMode.GLOBE_CESIUM)
    assert hint["projection"] == "EPSG:3857"
    assert hint["showBasemap"] is True
    assert hint["fit"] is False
    assert hint["globe"] is True


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
    assert hint["showBasemap"] is True
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
    assert hint["zoom"] == 0
    assert hint["showFullExtent"] is True
    assert hint["multiWorld"] is False
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


def test_resolve_engine_for_modes():
    assert resolve_engine_for_mode("EPSG6931") == "openlayers"
    assert resolve_engine_for_mode("globe_cesium") == "cesium"
    assert resolve_engine_for_mode("global_3857") == "openlayers"
    assert resolve_engine_for_mode("global_leaflet") == "leaflet_legacy"


def test_unknown_mode_raises():
    with pytest.raises(ValueError):
        tile_matrix_set_for_mode("not_a_mode")


def test_list_view_mode_presets_includes_polar_grid(monkeypatch):
    monkeypatch.setattr(
        "map.projections.list_custom_epsg_tms_ids",
        lambda _url: ("EPSG6931",),
    )
    monkeypatch.setattr(
        "map.projections.get_tile_grid",
        lambda _url, tms_id: {
            "extent": [-1.0, -1.0, 1.0, 1.0],
            "origin": [-1.0, 1.0],
            "resolutions": [1.0, 0.5],
        },
    )
    monkeypatch.setattr(
        "map.projections.proj4_for_epsg",
        lambda code: "+proj=laea" if code == 6931 else None,
    )
    presets = list_view_mode_presets("http://tiler")
    assert MapViewMode.GLOBAL_3857.value in presets
    assert presets[MapViewMode.GLOBAL_3857.value]["projection"] == "EPSG:3857"
    assert presets["EPSG6931"]["projection"] == "EPSG:6931"
    assert presets["EPSG6931"]["resolutions"] == [1.0, 0.5]

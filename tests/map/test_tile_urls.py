"""Tests for map projection policy and TiTiler URL building."""

import sys
from pathlib import Path

import pytest

SRC_DIR = Path(__file__).resolve().parents[2] / "src"
sys.path.insert(0, str(SRC_DIR))

from map.projections import (  # noqa: E402
    EPSG_6931_TMS,
    WEB_MERCATOR_QUAD,
    MapViewMode,
    epsg_code_for_mode,
    tile_matrix_set_for_mode,
)
from map.tile_urls import build_cog_tile_url  # noqa: E402


def test_tile_matrix_set_for_global_and_polar_modes():
    assert tile_matrix_set_for_mode(MapViewMode.GLOBAL_3857) == WEB_MERCATOR_QUAD
    assert tile_matrix_set_for_mode("arctic_6931") == EPSG_6931_TMS
    assert tile_matrix_set_for_mode(MapViewMode.GLOBE_CESIUM) == WEB_MERCATOR_QUAD


def test_epsg_code_for_mode():
    assert epsg_code_for_mode(MapViewMode.ARCTIC_6931) == 6931
    assert epsg_code_for_mode(MapViewMode.ANTARCTIC_6932) == 6932
    assert epsg_code_for_mode(MapViewMode.GLOBE_CESIUM) == 3857


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
        tile_matrix_set=EPSG_6931_TMS,
        colormap="blues_r",
        rescale=(0.0, 1.0),
        band_index=2,
    )

    assert "/cog/tiles/EPSG6931/{z}/{x}/{y}?" in url
    assert "colormap_name=blues_r" in url
    assert "rescale=0.0,1.0" in url
    assert "bidx=2" in url

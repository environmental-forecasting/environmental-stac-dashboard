"""Tests for the map-state leadtime COG URL cache helpers."""

import sys
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parents[2] / "src"
sys.path.insert(0, str(SRC_DIR))

from map.leadtime_cog_urls import (  # noqa: E402
    layers_from_leadtime_cog_urls,
    rewrite_leadtime_cog_urls_tms,
)


def test_layers_from_leadtime_cog_urls_builds_styled_urls():
    cache = {
        "tilerBase": "http://tiler",
        "tileMatrixSet": "WebMercatorQuad",
        "colormap": "blues_r",
        "rescale": [0.0, 1.0],
        "bidx": 2,
        "collections": {
            "demo": {
                "hrefs": [
                    "file:///data/cogs/a.tif",
                    "file:///data/cogs/b.tif",
                ]
            }
        },
    }
    layers = layers_from_leadtime_cog_urls(cache, 1)
    assert len(layers) == 1
    assert layers[0]["id"] == "demo"
    assert "file:///data/cogs/b.tif" in layers[0]["tileUrl"]
    assert "colormap_name=blues_r" in layers[0]["tileUrl"]
    assert "rescale=0.0,1.0" in layers[0]["tileUrl"]
    assert "bidx=2" in layers[0]["tileUrl"]
    assert layers_from_leadtime_cog_urls(cache, 9) == []


def test_rewrite_leadtime_cog_urls_tms_updates_matrix_set():
    cache = {
        "tilerBase": "http://tiler",
        "tileMatrixSet": "WebMercatorQuad",
        "collections": {},
    }
    rewritten = rewrite_leadtime_cog_urls_tms(cache, "EPSG6931")
    assert rewritten is not None
    assert rewritten["tileMatrixSet"] == "EPSG6931"
    assert cache["tileMatrixSet"] == "WebMercatorQuad"

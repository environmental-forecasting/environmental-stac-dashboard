"""Tests for TiTiler tile URL colour and rescale rewriting."""

import sys
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parents[2] / "src"
sys.path.insert(0, str(SRC_DIR))

from map.leadtime_cog_urls import rewrite_leadtime_cog_urls_style  # noqa: E402
from map.tile_urls import (  # noqa: E402
    rewrite_layer_entries_style,
    rewrite_tile_url_style,
)


def test_rewrite_tile_url_style_replaces_existing_params():
    url = (
        "http://tiler/cog/tiles/WebMercatorQuad/{z}/{x}/{y}"
        "?url=file:///data/a.tif&colormap_name=viridis&rescale=0,1&bidx=1"
    )
    out = rewrite_tile_url_style(url, colormap="blues_r", rescale=(2, 5))
    assert "colormap_name=blues_r" in out
    assert "rescale=2,5" in out
    assert "bidx=1" in out
    assert "viridis" not in out
    assert "rescale=0,1" not in out


def test_rewrite_tile_url_style_appends_missing_params():
    url = "http://tiler/cog/tiles/WebMercatorQuad/{z}/{x}/{y}?url=file:///data/a.tif"
    out = rewrite_tile_url_style(url, colormap="plasma", rescale=[-1, 3])
    assert "colormap_name=plasma" in out
    assert "rescale=-1,3" in out


def test_rewrite_layer_and_leadtime_cog_urls_style():
    layers = [
        {
            "id": "demo",
            "tileUrl": (
                "http://t/cog/tiles/WebMercatorQuad/{z}/{x}/{y}"
                "?url=x&colormap_name=a&rescale=0,1"
            ),
        }
    ]
    rewritten = rewrite_layer_entries_style(
        layers, colormap="b", rescale=(4, 8)
    )
    assert "colormap_name=b" in rewritten[0]["tileUrl"]
    assert "rescale=4,8" in rewritten[0]["tileUrl"]

    cache = rewrite_leadtime_cog_urls_style(
        {"colormap": "a", "rescale": [0, 1], "tilerBase": "http://t"},
        colormap="b",
        rescale=(4, 8),
    )
    assert cache["colormap"] == "b"
    assert cache["rescale"] == [4.0, 8.0]

"""Tests for the map-state leadtime COG URL cache helpers."""

import sys
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parents[2] / "src"
sys.path.insert(0, str(SRC_DIR))

from map.leadtime_cog_urls import (  # noqa: E402
    build_leadtime_cog_urls,
    layers_from_leadtime_cog_urls,
    leadtime_cog_urls_match_style,
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
                ],
                "bbox": [-180.0, -90.0, 180.0, -50.0],
            }
        },
    }
    layers = layers_from_leadtime_cog_urls(cache, 1)
    assert len(layers) == 1
    assert layers[0]["id"] == "demo"
    assert layers[0]["bbox"] == [-180.0, -90.0, 180.0, -50.0]
    assert "file:///data/cogs/b.tif" in layers[0]["tileUrl"]
    assert "colormap_name=blues_r" in layers[0]["tileUrl"]
    assert "rescale=0.0,1.0" in layers[0]["tileUrl"]
    assert "bidx=2" in layers[0]["tileUrl"]
    assert layers_from_leadtime_cog_urls(cache, 9) == []


def test_build_leadtime_cog_urls_publishes_hrefs_per_collection():
    payload = build_leadtime_cog_urls(
        tiler_base="http://tiler/",
        tile_matrix_set="WebMercatorQuad",
        hrefs_by_collection={
            "demo": ["file:///data/a.tif", "file:///data/b.tif"],
            "empty": [],
        },
        bbox_by_collection={"demo": [-40.0, -80.0, 40.0, -55.0]},
        colormap="blues_r",
        rescale=(0, 1),
        band_index=2,
        reference_time="2024-01-01T00:00:00Z",
    )
    assert payload is not None
    assert payload["tilerBase"] == "http://tiler"
    assert payload["rescale"] == [0.0, 1.0]
    assert payload["bidx"] == 2
    assert payload["refTime"] == "2024-01-01T00:00:00Z"
    assert list(payload["collections"]) == ["demo"]
    assert len(payload["collections"]["demo"]["hrefs"]) == 2
    assert payload["collections"]["demo"]["bbox"] == [-40.0, -80.0, 40.0, -55.0]

    # The payload feeds the same URL builder the browser mirrors.
    layers = layers_from_leadtime_cog_urls(payload, 0)
    assert len(layers) == 1
    assert "file:///data/a.tif" in layers[0]["tileUrl"]
    assert layers[0]["bbox"] == [-40.0, -80.0, 40.0, -55.0]


def test_build_leadtime_cog_urls_returns_none_without_hrefs():
    assert (
        build_leadtime_cog_urls(
            tiler_base="http://tiler",
            tile_matrix_set="WebMercatorQuad",
            hrefs_by_collection={"demo": []},
        )
        is None
    )


def test_leadtime_cog_urls_match_style_guards_every_style_field():
    payload = build_leadtime_cog_urls(
        tiler_base="http://tiler",
        tile_matrix_set="WebMercatorQuad",
        hrefs_by_collection={"demo": ["file:///data/a.tif"]},
        colormap="blues_r",
        rescale=(0.0, 1.0),
        band_index=2,
    )
    matching = {
        "tile_matrix_set": "WebMercatorQuad",
        "colormap": "blues_r",
        "rescale": (0.0, 1.0),
        "band_index": 2,
        "collection_ids": ["demo", "other"],
    }
    assert leadtime_cog_urls_match_style(payload, **matching)

    for field, value in (
        ("tile_matrix_set", "EPSG6931"),
        ("colormap", "viridis"),
        ("rescale", (0.0, 2.0)),
        ("band_index", 3),
        # A cached collection that is no longer selected must force a rebuild.
        ("collection_ids", ["other"]),
    ):
        assert not leadtime_cog_urls_match_style(
            payload, **{**matching, field: value}
        )

    assert not leadtime_cog_urls_match_style(None, **matching)


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

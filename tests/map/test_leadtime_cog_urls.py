"""Tests for the map-state leadtime Item tile cache helpers."""

import sys
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parents[2] / "src"
sys.path.insert(0, str(SRC_DIR))

from map.leadtime_cog_urls import (  # noqa: E402
    bank_has_item_ids,
    build_leadtime_cog_urls,
    layers_from_leadtime_cog_urls,
    leadtime_cog_urls_match_style,
)


def test_layers_from_leadtime_cog_urls_builds_styled_item_urls():
    cache = {
        "tilerBase": "http://tiler",
        "tileMatrixSet": "WebMercatorQuad",
        "colormap": "blues_r",
        "rescale": [0.0, 1.0],
        "bidx": 2,
        "collections": {
            "demo": {
                "hrefs": ["2026-07-19T00:00:00Z", "2026-07-20T00:00:00Z"],
                "itemId": "forecast-init-demo",
                "bbox": [-180.0, -90.0, 180.0, -50.0],
                "gsd": 25000.0,
            }
        },
    }
    layers = layers_from_leadtime_cog_urls(cache, 1)
    assert len(layers) == 1
    assert layers[0]["id"] == "demo"
    assert layers[0]["bbox"] == [-180.0, -90.0, 180.0, -50.0]
    assert layers[0]["gsd"] == 25000.0
    url = layers[0]["tileUrl"]
    assert "/collections/demo/items/forecast-init-demo/tiles/WebMercatorQuad/" in url
    assert "assets=2026-07-20T00%3A00%3A00Z%7Cbidx%3D2" in url
    assert "colormap_name=blues_r" in url
    assert "rescale=0.0,1.0" in url
    assert layers_from_leadtime_cog_urls(cache, 9) == []


def test_layers_from_leadtime_cog_urls_skips_collections_without_item_id():
    cache = {
        "tilerBase": "http://tiler",
        "tileMatrixSet": "WebMercatorQuad",
        "collections": {
            "demo": {"hrefs": ["2026-07-19T00:00:00Z"]},
        },
    }
    assert layers_from_leadtime_cog_urls(cache, 0) == []


def test_build_leadtime_cog_urls_requires_item_ids():
    payload = build_leadtime_cog_urls(
        tiler_base="http://tiler/",
        tile_matrix_set="WebMercatorQuad",
        hrefs_by_collection={
            "demo": ["2026-07-19T00:00:00Z", "2026-07-20T00:00:00Z"],
            "empty": [],
        },
        item_ids_by_collection={"demo": "forecast-init-demo"},
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
    assert payload["collections"]["demo"]["itemId"] == "forecast-init-demo"
    assert len(payload["collections"]["demo"]["hrefs"]) == 2
    assert payload["collections"]["demo"]["bbox"] == [-40.0, -80.0, 40.0, -55.0]

    layers = layers_from_leadtime_cog_urls(payload, 0)
    assert len(layers) == 1
    assert "/collections/demo/items/forecast-init-demo/tiles/" in layers[0]["tileUrl"]
    assert layers[0]["bbox"] == [-40.0, -80.0, 40.0, -55.0]


def test_build_leadtime_cog_urls_returns_none_without_item_ids():
    assert (
        build_leadtime_cog_urls(
            tiler_base="http://tiler",
            tile_matrix_set="WebMercatorQuad",
            hrefs_by_collection={"demo": ["2026-07-19T00:00:00Z"]},
        )
        is None
    )


def test_leadtime_cog_urls_match_style_guards_every_style_field():
    payload = build_leadtime_cog_urls(
        tiler_base="http://tiler",
        tile_matrix_set="WebMercatorQuad",
        hrefs_by_collection={"demo": ["2026-07-19T00:00:00Z"]},
        item_ids_by_collection={"demo": "forecast-init-demo"},
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
        ("collection_ids", ["other"]),
    ):
        assert not leadtime_cog_urls_match_style(
            payload, **{**matching, field: value}
        )

    assert not leadtime_cog_urls_match_style(None, **matching)


def test_layers_from_leadtime_cog_urls_builds_item_tile_urls():
    payload = build_leadtime_cog_urls(
        tiler_base="http://tiler/",
        tile_matrix_set="EPSG6931",
        hrefs_by_collection={
            "demo": ["2026-07-19T00:00:00Z", "2026-07-20T00:00:00Z"],
        },
        item_ids_by_collection={"demo": "forecast-init-demo"},
        bbox_by_collection={"demo": [-40.0, 50.0, 40.0, 90.0]},
        colormap="blues_r",
        rescale=(0, 1),
        band_index=2,
    )
    assert payload is not None
    assert bank_has_item_ids(payload)
    assert payload["collections"]["demo"]["itemId"] == "forecast-init-demo"

    layers = layers_from_leadtime_cog_urls(payload, 1)
    assert len(layers) == 1
    url = layers[0]["tileUrl"]
    assert "/collections/demo/items/forecast-init-demo/tiles/EPSG6931/" in url
    assert "assets=2026-07-20T00%3A00%3A00Z%7Cbidx%3D2" in url
    assert "colormap_name=blues_r" in url
    assert "rescale=0.0,1.0" in url
    assert "/cog/tiles/" not in url
    assert "url=file://" not in url

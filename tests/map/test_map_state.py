"""Tests for shared map-state helpers."""

import sys
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parents[2] / "src"
sys.path.insert(0, str(SRC_DIR))

from map.state import build_map_state, initial_map_state  # noqa: E402


def test_initial_map_state_defaults_to_openlayers_global():
    state = initial_map_state()
    assert state["engine"] == "openlayers"
    assert state["mode"] == "global_3857"
    assert state["layers"] == []
    assert state["prefetchLayers"] == []
    assert state["leadtimeCogUrls"] is None
    assert state["lead"] is None
    assert state["revision"] == 0
    assert state["view"]["projection"] == "EPSG:3857"
    assert state["view"]["showBasemap"] is True
    assert "cartocdn.com/rastertiles/voyager" in state["basemap"]["url"]


def test_build_map_state_bumps_revision_when_view_changes():
    previous = initial_map_state()
    polar_view = {
        "projection": "EPSG:6931",
        "showBasemap": True,
        "fit": True,
        "extent": [-1, -1, 1, 1],
    }
    changed = build_map_state(
        previous=previous,
        engine="openlayers",
        mode="EPSG6931",
        layers=[],
        view=polar_view,
    )
    assert changed["revision"] == 1
    assert changed["mode"] == "EPSG6931"
    assert changed["view"]["projection"] == "EPSG:6931"


def test_build_map_state_bumps_revision_only_when_content_changes():
    previous = initial_map_state()
    same = build_map_state(
        previous=previous,
        engine="openlayers",
        mode="global_3857",
        layers=[],
    )
    assert same["revision"] == 0

    changed = build_map_state(
        previous=previous,
        engine="openlayers",
        mode="global_3857",
        layers=[
            {
                "id": "demo",
                "title": "demo",
                "tileUrl": "http://example/{z}/{x}/{y}",
                "opacity": 1,
                "visible": True,
            }
        ],
    )
    assert changed["revision"] == 1
    assert len(changed["layers"]) == 1


def test_build_map_state_includes_prefetch_layers():
    previous = initial_map_state()
    prefetch = [
        {
            "id": "demo",
            "tileUrl": "http://example/next/{z}/{x}/{y}",
            "opacity": 1,
            "visible": True,
        }
    ]
    changed = build_map_state(
        previous=previous,
        engine="openlayers",
        mode="global_3857",
        layers=[],
        prefetch_layers=prefetch,
    )
    assert changed["revision"] == 1
    assert changed["prefetchLayers"] == prefetch


def test_build_map_state_includes_leadtime_cog_urls_and_lead():
    previous = initial_map_state()
    cache = {
        "tilerBase": "http://tiler",
        "tileMatrixSet": "WebMercatorQuad",
        "colormap": "blues_r",
        "rescale": [0.0, 1.0],
        "bidx": 1,
        "collections": {
            "demo": {"hrefs": ["file:///data/a.tif", "file:///data/b.tif"]}
        },
    }
    changed = build_map_state(
        previous=previous,
        engine="openlayers",
        mode="global_3857",
        layers=[],
        leadtime_cog_urls=cache,
        lead=3,
    )
    assert changed["revision"] == 1
    assert changed["leadtimeCogUrls"] == cache
    assert changed["lead"] == 3

    # Omitting leadtime_cog_urls keeps the previous cache.
    kept = build_map_state(
        previous=changed,
        engine="openlayers",
        mode="global_3857",
        layers=changed["layers"],
        lead=4,
    )
    assert kept["leadtimeCogUrls"] == cache
    assert kept["lead"] == 4

    cleared = build_map_state(
        previous=kept,
        engine="openlayers",
        mode="global_3857",
        layers=[],
        leadtime_cog_urls=None,
        lead=None,
    )
    assert cleared["leadtimeCogUrls"] is None
    assert cleared["lead"] is None

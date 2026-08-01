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
    assert state["revision"] == 0
    assert state["view"]["projection"] == "EPSG:3857"
    assert state["view"]["showBasemap"] is True


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
